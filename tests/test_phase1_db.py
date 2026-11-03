"""Comprehensive unit and integration test suite for Phase 1 (SRS v1.1).

Covers:
- Database schema verification & Master Data Seeding (Section 4.1, 4.3).
- Idempotent Seeding verification (FR-04).
- UniqueConstraint enforcement for price_observation & weather_observation (Section 4.2).
- Province Alias Resolution (FR-33).
- Data Coverage View / Analytics calculation (Section 4.3, FR-42).
"""

from datetime import date, timedelta
from decimal import Decimal
import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db.models import (
    Province,
    ProvinceAlias,
    Commodity,
    DataSource,
    PriceObservation,
    WeatherObservation,
    AlertRule,
    PipelineLog,
    BackfillJob,
)
from processing.normalize import resolve_province_by_name_or_alias
from db.views import get_data_coverage_metrics
from scripts.init_db import seed_master_data


def test_schema_and_master_data_seeded(db_session: Session):
    """Kiểm tra 13 bảng và danh mục master data đã được khởi tạo đầy đủ."""
    # 1. Kiểm tra 8 Tỉnh trọng điểm
    provinces = db_session.query(Province).all()
    assert len(provinces) == 8
    prov_codes = {p.code for p in provinces}
    expected_codes = {"LD", "DL", "GL", "DN", "BRVT", "AG", "DT", "CT"}
    assert prov_codes == expected_codes

    # Kiểm tra tọa độ vĩ độ/kinh độ hợp lệ của các tỉnh
    for p in provinces:
        assert 8.0 <= p.lat <= 24.0, f"Vĩ độ {p.lat} của {p.standard_name} không hợp lệ với lãnh thổ VN"
        assert 102.0 <= p.lon <= 110.0, f"Kinh độ {p.lon} của {p.standard_name} không hợp lệ với lãnh thổ VN"

    # Kiểm tra aliases đã được tạo
    aliases = db_session.query(ProvinceAlias).all()
    assert len(aliases) >= 20

    # 2. Kiểm tra 3 Nông sản chủ lực
    commodities = db_session.query(Commodity).all()
    assert len(commodities) == 3
    comm_codes = {c.code for c in commodities}
    assert comm_codes == {"CAFE_ROBUSTA", "TIEU_DEN", "LUA_IR50404"}

    # 3. Kiểm tra Nguồn dữ liệu
    sources = db_session.query(DataSource).all()
    assert len(sources) == 4
    source_types = {s.source_type for s in sources}
    assert source_types == {"PRICE", "WEATHER"}

    # 4. Kiểm tra Alert Rules mặc định
    rules = db_session.query(AlertRule).all()
    assert len(rules) == 3
    for r in rules:
        assert r.threshold_pct == 5.0
        assert r.window_days == 7
        assert r.is_active is True


def test_idempotent_seeding(db_session: Session):
    """Kiểm tra chạy seed nhiều lần không sinh bản ghi trùng lặp (Idempotent)."""
    stats = seed_master_data(db_session)
    assert stats["provinces_added"] == 0
    assert stats["aliases_added"] == 0
    assert stats["commodities_added"] == 0
    assert stats["sources_added"] == 0
    assert stats["alert_rules_added"] == 0


def test_price_observation_unique_constraint(db_session: Session):
    """
    Kiểm tra ràng buộc UniqueConstraint ('obs_date', 'commodity_id', 'province_id', 'source_id').
    Cố tình chèn 2 bản ghi trùng khóa phải bị ném lỗi IntegrityError (Section 4.2 & 4.3, FR-04).
    """
    comm = db_session.query(Commodity).filter(Commodity.code == "CAFE_ROBUSTA").first()
    prov = db_session.query(Province).filter(Province.code == "LD").first()
    src = db_session.query(DataSource).filter(DataSource.source_type == "PRICE").first()

    obs_date = date(2026, 11, 1)

    # Bản ghi 1: Hợp lệ
    record1 = PriceObservation(
        obs_date=obs_date,
        commodity_id=comm.id,
        province_id=prov.id,
        source_id=src.id,
        price=Decimal("115000.00"),
        raw_value="115.000",
        raw_unit="đ/kg",
        source_url="https://giacaphe.com/gia-ca-phe-lam-dong/",
        quality_flag="OK",
    )
    db_session.add(record1)
    db_session.commit()

    # Bản ghi 2: Trùng chính xác khóa duy nhất
    record2 = PriceObservation(
        obs_date=obs_date,
        commodity_id=comm.id,
        province_id=prov.id,
        source_id=src.id,
        price=Decimal("116000.00"),
        raw_value="116.000",
        raw_unit="đ/kg",
        source_url="https://giacaphe.com/gia-ca-phe-lam-dong/",
        quality_flag="OK",
    )
    db_session.add(record2)

    with pytest.raises(IntegrityError):
        db_session.commit()

    db_session.rollback()


def test_weather_observation_unique_constraint(db_session: Session):
    """Kiểm tra ràng buộc UniqueConstraint của weather_observation ('obs_date', 'province_id', 'source_id')."""
    prov = db_session.query(Province).filter(Province.code == "DL").first()
    src = db_session.query(DataSource).filter(DataSource.source_type == "WEATHER").first()

    obs_date = date(2026, 11, 1)

    weather1 = WeatherObservation(
        obs_date=obs_date,
        province_id=prov.id,
        source_id=src.id,
        temp_max=31.5,
        temp_min=20.2,
        temp_mean=25.8,
        precipitation=5.2,
        humidity=80.0,
    )
    db_session.add(weather1)
    db_session.commit()

    weather2 = WeatherObservation(
        obs_date=obs_date,
        province_id=prov.id,
        source_id=src.id,
        temp_max=32.0,
        temp_min=21.0,
        temp_mean=26.0,
        precipitation=0.0,
        humidity=75.0,
    )
    db_session.add(weather2)

    with pytest.raises(IntegrityError):
        db_session.commit()

    db_session.rollback()


def test_province_alias_resolution(db_session: Session):
    """
    Kiểm tra chức năng chuẩn hóa tên tỉnh/khu vực qua bảng province_alias (FR-33).
    Các biến thể khác nhau từ các nguồn thu thập phải ánh xạ đúng về Province ID chuẩn.
    """
    # 1. Test Buôn Ma Thuột -> Đắk Lắk (DL)
    prov_bmt = resolve_province_by_name_or_alias("Buôn Ma Thuột", db_session)
    assert prov_bmt is not None
    assert prov_bmt.code == "DL"
    assert prov_bmt.standard_name == "Đắk Lắk"

    # 2. Test Đăk Lắk (cách viết sai dấu phổ biến) -> Đắk Lắk (DL)
    prov_daklak = resolve_province_by_name_or_alias("Đăk Lăk", db_session)
    assert prov_daklak is not None
    assert prov_daklak.code == "DL"

    # 3. Test không dấu Dak Lak -> Đắk Lắk (DL)
    prov_no_accent = resolve_province_by_name_or_alias("Dak Lak", db_session)
    assert prov_no_accent is not None
    assert prov_no_accent.code == "DL"

    # 4. Test huyện Bảo Lộc -> Lâm Đồng (LD)
    prov_bl = resolve_province_by_name_or_alias("Bảo Lộc", db_session)
    assert prov_bl is not None
    assert prov_bl.code == "LD"
    assert prov_bl.standard_name == "Lâm Đồng"

    # 5. Test viết tắt BR-VT -> Bà Rịa - Vũng Tàu (BRVT)
    prov_brvt = resolve_province_by_name_or_alias("BR-VT", db_session)
    assert prov_brvt is not None
    assert prov_brvt.code == "BRVT"

    # 6. Test Cao Lãnh -> Đồng Tháp (DT)
    prov_dt = resolve_province_by_name_or_alias("Cao Lãnh", db_session)
    assert prov_dt is not None
    assert prov_dt.code == "DT"

    # 7. Test tên không hợp lệ -> None
    prov_unknown = resolve_province_by_name_or_alias("Địa phương không tồn tại", db_session)
    assert prov_unknown is None


def test_data_coverage_metrics(db_session: Session):
    """Kiểm tra hàm tính độ phủ dữ liệu data_coverage (FR-42)."""
    comm = db_session.query(Commodity).first()
    prov = db_session.query(Province).first()
    src = db_session.query(DataSource).filter(DataSource.source_type == "PRICE").first()

    # Thêm chuỗi giá có 4 ngày: ngày 1, 2, 3, và ngày 7 (có gap 4 ngày từ ngày 3 đến ngày 7)
    dates = [
        date(2026, 10, 1),
        date(2026, 10, 2),
        date(2026, 10, 3),
        date(2026, 10, 7),
    ]

    for d in dates:
        obs = PriceObservation(
            obs_date=d,
            commodity_id=comm.id,
            province_id=prov.id,
            source_id=src.id,
            price=Decimal("100000.00"),
            raw_value="100.000",
            raw_unit="đ/kg",
            source_url="https://example.com/price",
            quality_flag="OK",
        )
        db_session.add(obs)
    db_session.commit()

    metrics = get_data_coverage_metrics(db_session, commodity_id=comm.id, province_id=prov.id)
    assert len(metrics) == 1
    m = metrics[0]
    assert m["min_date"] == date(2026, 10, 1)
    assert m["max_date"] == date(2026, 10, 7)
    assert m["total_days_with_data"] == 4
    assert m["total_span_days"] == 7
    assert m["max_gap_days"] == 4  # Từ 03/10 đến 07/10 là 4 ngày
    # Missing 3 days out of 7 -> 3/7 ≈ 0.4286
    assert abs(m["missing_ratio"] - 0.4286) < 0.001


def test_pipeline_log_and_backfill_job(db_session: Session):
    """Kiểm tra ghi log pipeline và checkpoint của backfill job (FR-05, FR-40, FR-41)."""
    src = db_session.query(DataSource).first()
    prov = db_session.query(Province).first()
    comm = db_session.query(Commodity).first()

    # 1. Pipeline Log
    log = PipelineLog(
        task_name="daily_coffee_scraper",
        source_id=src.id,
        status="SUCCESS",
        records_processed=15,
        error_message=None,
    )
    db_session.add(log)
    db_session.commit()
    assert log.id is not None
    assert log.started_at is not None

    # 2. Backfill Job với checkpoint
    job = BackfillJob(
        source_id=src.id,
        commodity_id=comm.id,
        province_id=prov.id,
        start_date=date(2025, 1, 1),
        end_date=date(2026, 1, 1),
        last_completed_date=date(2025, 6, 30),
        status="RUNNING",
    )
    db_session.add(job)
    db_session.commit()
    assert job.id is not None
    assert job.last_completed_date == date(2025, 6, 30)

