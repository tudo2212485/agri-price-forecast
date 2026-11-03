"""Comprehensive Test Suite for Phase 2: Collector, Historical Backfill & Data Quality (SRS v1.1).

Bao gồm 5 nhóm kiểm thử bắt buộc:
1. test_pipeline_logger_and_retry: Kiểm tra ghi log pipeline_log (SUCCESS/FAILED) và cơ chế retry 3 lần (FR-04, FR-05, NFR-02).
2. test_price_unit_normalization_and_provenance: Kiểm tra quy đổi đơn vị về VNĐ/kg và truy vết 100% nguồn gốc (FR-32, FR-33, NFR-14).
3. test_backfill_checkpoint_and_resume: Kiểm tra dừng giữa chừng (last_completed_date) và resume_backfill() không trùng dữ liệu (FR-40, FR-41).
4. test_quality_check_and_cross_source_review_flag: Kiểm tra gắn cờ INVALID, OUTLIER và đối chiếu chéo đa nguồn review_flag = True (FR-06, FR-35).
5. test_coverage_report_generation: Kiểm tra báo cáo độ phủ và điều kiện đủ dữ liệu huấn luyện (FR-42).
"""

from datetime import date
from decimal import Decimal
import pytest
from sqlalchemy.orm import Session

from collector.base import BaseCollector
from collector.price_collector import (
    AgriPriceCollector,
    normalize_price_to_vnd_per_kg,
)
from collector.backfill import BackfillManager
from db.models import (
    Commodity,
    Province,
    DataSource,
    PriceObservation,
    PipelineLog,
    BackfillJob,
)
from processing.quality_check import (
    run_price_quality_checks,
    run_cross_source_reconciliation,
    generate_data_quality_and_coverage_report,
)


def test_pipeline_logger_and_retry(db_session: Session):
    """
    1. Kiểm tra BaseCollector tự động ghi log vào bảng pipeline_log khi thành công và khi gặp lỗi (FR-05).
    2. Kiểm tra cơ chế execute_with_retry thử lại đúng 3 lần với exponential backoff (NFR-02, FR-04).
    """
    src = db_session.query(DataSource).first()
    collector = BaseCollector(
        db=db_session,
        source_id=src.id,
        rate_limit_delay=0.0,
        max_retries=3,
        backoff_factor=0.01,
    )

    # 1a. Kiểm tra ghi log khi chạy thành công (SUCCESS)
    with collector.log_pipeline_run(task_name="test_success_task") as tracker:
        tracker.add_records(42)

    success_log = (
        db_session.query(PipelineLog)
        .filter(PipelineLog.task_name == "test_success_task")
        .first()
    )
    assert success_log is not None
    assert success_log.status == "SUCCESS"
    assert success_log.records_processed == 42
    assert success_log.started_at is not None
    assert success_log.finished_at is not None
    assert success_log.error_message is None

    # 1b. Kiểm tra ghi log khi gặp ngoại lệ (FAILED)
    with pytest.raises(RuntimeError, match="Simulated network timeout"):
        with collector.log_pipeline_run(task_name="test_failed_task", raise_on_error=True) as tracker:
            tracker.add_records(5)
            raise RuntimeError("Simulated network timeout")

    failed_log = (
        db_session.query(PipelineLog)
        .filter(PipelineLog.task_name == "test_failed_task")
        .first()
    )
    assert failed_log is not None
    assert failed_log.status == "FAILED"
    assert failed_log.records_processed == 5
    assert "Simulated network timeout" in (failed_log.error_message or "")
    assert failed_log.finished_at is not None

    # 1c. Kiểm tra cơ chế Retry 3 lần: lỗi 2 lần đầu, thành công ở lần thứ 3
    call_counter = {"attempts": 0}

    def _flaky_network_call() -> str:
        call_counter["attempts"] += 1
        if call_counter["attempts"] < 3:
            raise ConnectionError(f"Temporary failure #{call_counter['attempts']}")
        return "HTTP_200_OK"

    result = collector.execute_with_retry(_flaky_network_call, max_retries=3, backoff_factor=0.01)
    assert result == "HTTP_200_OK"
    assert call_counter["attempts"] == 3

    # 1d. Kiểm tra khi lỗi cả 3 lần thì ném ngoại lệ sau đúng 3 lần thử
    fail_counter = {"attempts": 0}

    def _always_failing_call() -> None:
        fail_counter["attempts"] += 1
        raise TimeoutError("Persistent timeout")

    with pytest.raises(TimeoutError):
        collector.execute_with_retry(_always_failing_call, max_retries=3, backoff_factor=0.01)
    assert fail_counter["attempts"] == 3


def test_price_unit_normalization_and_provenance(db_session: Session):
    """
    Kiểm tra chuẩn hóa các định dạng đơn vị tiền tệ/khối lượng về VNĐ/kg
    và đảm bảo 100% bản ghi lưu đủ raw_value, raw_unit, source_url (FR-32, FR-33, NFR-14).
    """
    # 1. Kiểm tra các trường hợp quy đổi đơn vị tiền tệ
    assert normalize_price_to_vnd_per_kg("120,000", "đ/kg") == Decimal("120000.00")
    assert normalize_price_to_vnd_per_kg("120.000", "VNĐ/kg") == Decimal("120000.00")
    assert normalize_price_to_vnd_per_kg("120.5", "nghìn/kg") == Decimal("120500.00")
    assert normalize_price_to_vnd_per_kg("120,5", "ngàn đồng/kg") == Decimal("120500.00")
    assert normalize_price_to_vnd_per_kg("12,000,000", "VNĐ/tạ") == Decimal("120000.00")
    assert normalize_price_to_vnd_per_kg("1,200,000", "VNĐ/yến") == Decimal("120000.00")
    assert normalize_price_to_vnd_per_kg("120,000,000", "VNĐ/tấn") == Decimal("120000.00")
    assert normalize_price_to_vnd_per_kg("120.5", "triệu/tấn") == Decimal("120500.00")
    assert normalize_price_to_vnd_per_kg("7.800 - 8.000", "đ/kg") == Decimal("7900.00")

    # 2. Kiểm tra bóc tách bảng giá HTML thực tế + ánh xạ alias tỉnh + lưu vết provenance
    sample_html = """
    <html>
      <body>
        <table>
          <tr><th>Địa phương</th><th>Giá thu mua</th><th>Đơn vị</th></tr>
          <tr><td>Buôn Ma Thuột</td><td>121.5</td><td>nghìn/kg</td></tr>
          <tr><td>Bảo Lộc</td><td>12,050,000</td><td>VNĐ/tạ</td></tr>
        </table>
      </body>
    </html>
    """
    src = db_session.query(DataSource).filter(DataSource.source_type == "PRICE").first()
    price_collector = AgriPriceCollector(db=db_session, rate_limit_delay=0.0)
    parsed_records = price_collector.parse_html_price_table(
        html_content=sample_html,
        commodity_code="CAFE_ROBUSTA",
        obs_date=date(2026, 10, 15),
        source_id=src.id,
        source_url="https://giacaphe.com/gia-ca-phe-ngay-2026-10-15/",
    )

    assert len(parsed_records) == 2
    upserted = price_collector.upsert_price_observations(parsed_records)
    assert upserted == 2

    # Kiểm tra bản ghi trong DB giữ nguyên raw_value, raw_unit, source_url và ánh xạ đúng tỉnh chuẩn
    saved_obs = db_session.query(PriceObservation).order_by(PriceObservation.price.desc()).all()
    assert len(saved_obs) == 2

    obs_dl = saved_obs[0]
    prov_dl = db_session.query(Province).filter(Province.id == obs_dl.province_id).first()
    assert prov_dl.code == "DL"  # Buôn Ma Thuột -> Đắk Lắk
    assert obs_dl.price == Decimal("121500.00")
    assert obs_dl.raw_value == "121.5"
    assert obs_dl.raw_unit == "nghìn/kg"
    assert obs_dl.source_url == "https://giacaphe.com/gia-ca-phe-ngay-2026-10-15/"
    assert obs_dl.collected_at is not None

    obs_ld = saved_obs[1]
    prov_ld = db_session.query(Province).filter(Province.id == obs_ld.province_id).first()
    assert prov_ld.code == "LD"  # Bảo Lộc -> Lâm Đồng
    assert obs_ld.price == Decimal("120500.00")
    assert obs_ld.raw_value == "12,050,000"
    assert obs_ld.raw_unit == "VNĐ/tạ"


def test_backfill_checkpoint_and_resume(db_session: Session):
    """
    Giả lập một backfill_job bị dừng ở giữa chừng (last_completed_date),
    gọi resume_backfill() và xác nhận job chạy tiếp từ mốc dừng đến COMPLETED
    mà không sinh bản ghi trùng lặp (FR-40, FR-41).
    """
    comm = db_session.query(Commodity).filter(Commodity.code == "CAFE_ROBUSTA").first()
    prov = db_session.query(Province).filter(Province.code == "DL").first()
    src = db_session.query(DataSource).filter(DataSource.source_type == "PRICE").first()

    manager = BackfillManager(db=db_session)
    start_dt = date(2025, 3, 1)
    end_dt = date(2025, 3, 30)  # Tổng cộng 30 ngày

    job = manager.create_or_get_job(
        source_id=src.id,
        commodity_id=comm.id,
        province_id=prov.id,
        start_date=start_dt,
        end_date=end_dt,
    )
    assert job.status == "PENDING"
    assert job.last_completed_date is None

    # Bước 1: Chạy 1 batch (10 ngày đầu: 01/03/2025 -> 10/03/2025) rồi tạm dừng
    partial_res = manager.execute_job(job, batch_days=10, stop_after_batches=1)
    assert partial_res["status"] == "RUNNING"
    assert partial_res["batches_run"] == 1
    assert partial_res["last_completed_date"] == date(2025, 3, 10)
    assert partial_res["records_upserted"] == 10

    count_after_part1 = db_session.query(PriceObservation).count()
    assert count_after_part1 == 10

    # Bước 2: Gọi resume_backfill() để chạy tiếp từ ngày 11/01/2025 đến 30/01/2025
    resumed_list = manager.resume_backfill(job_id=job.id, batch_days=10)
    assert len(resumed_list) == 1
    resumed_res = resumed_list[0]
    assert resumed_res["status"] == "COMPLETED"
    assert resumed_res["batches_run"] == 2  # 2 lô còn lại (11->20 và 21->30)
    assert resumed_res["last_completed_date"] == end_dt
    assert resumed_res["records_upserted"] == 20

    # Xác nhận tổng bản ghi trong DB đúng bằng 30 ngày, không có bản ghi trùng
    total_obs = db_session.query(PriceObservation).count()
    assert total_obs == 30

    # Bước 3: Gọi lại execute_job trên job đã COMPLETED -> không chạy lại
    noop_res = manager.execute_job(job, batch_days=10)
    assert noop_res["batches_run"] == 0
    assert db_session.query(PriceObservation).count() == 30


def test_quality_check_and_cross_source_review_flag(db_session: Session):
    """
    Kiểm tra:
    1. Phát hiện giá âm/phi lý -> quality_flag = 'INVALID' (FR-06).
    2. Phát hiện ngoại lệ đột biến (> 25%/ngày) -> quality_flag = 'OUTLIER' (FR-06).
    3. Đối chiếu chéo 2 nguồn cùng ngày lệch > 5% -> review_flag = True trên cả 2 bản ghi (FR-35).
    """
    comm = db_session.query(Commodity).filter(Commodity.code == "CAFE_ROBUSTA").first()
    prov = db_session.query(Province).filter(Province.code == "LD").first()
    sources = db_session.query(DataSource).filter(DataSource.source_type == "PRICE").all()
    src1 = sources[0]
    src2 = sources[1]

    # Tạo chuỗi giá cho nguồn 1 gồm:
    # - Ngày 1: Giá bình thường 110,000 -> OK
    # - Ngày 2: Giá âm -5,000 -> INVALID
    # - Ngày 3: Giá bình thường 111,000 -> OK
    # - Ngày 4: Giá nhảy vọt phi thường 190,000 (+71% trong 1 ngày) -> OUTLIER
    # - Ngày 5: Giá bình thường 112,000 -> OK
    test_rows = [
        (date(2026, 5, 1), src1.id, Decimal("110000.00"), "110,000"),
        (date(2026, 5, 2), src1.id, Decimal("-5000.00"), "-5,000"),
        (date(2026, 5, 3), src1.id, Decimal("111000.00"), "111,000"),
        (date(2026, 5, 4), src1.id, Decimal("190000.00"), "190,000"),
        (date(2026, 5, 5), src1.id, Decimal("112000.00"), "112,000"),
        # Thêm bản ghi từ nguồn thứ 2 vào ngày 05/05/2026 với giá 122,000 (lệch 8.93% > 5% so với 112,000)
        (date(2026, 5, 5), src2.id, Decimal("122000.00"), "122,000"),
    ]

    for d, s_id, p_val, raw_v in test_rows:
        db_session.add(
            PriceObservation(
                obs_date=d,
                commodity_id=comm.id,
                province_id=prov.id,
                source_id=s_id,
                price=p_val,
                raw_value=raw_v,
                raw_unit="VNĐ/kg",
                source_url="https://giacaphe.com/test",
                quality_flag="OK",
                review_flag=False,
            )
        )
    db_session.commit()

    # 1. Chạy kiểm tra chất lượng (FR-06)
    qc_stats = run_price_quality_checks(db_session, commodity_id=comm.id, province_id=prov.id)
    assert qc_stats["invalid_count"] == 1
    assert qc_stats["outlier_count"] == 1
    assert qc_stats["ok_count"] == 4

    obs_invalid = (
        db_session.query(PriceObservation)
        .filter_by(obs_date=date(2026, 5, 2), source_id=src1.id)
        .first()
    )
    assert obs_invalid.quality_flag == "INVALID"

    obs_outlier = (
        db_session.query(PriceObservation)
        .filter_by(obs_date=date(2026, 5, 4), source_id=src1.id)
        .first()
    )
    assert obs_outlier.quality_flag == "OUTLIER"

    # Ngày 05/05 vẫn phải là OK vì ngày 04/05 (OUTLIER) không được dùng làm mốc chuẩn so sánh
    obs_day5_src1 = (
        db_session.query(PriceObservation)
        .filter_by(obs_date=date(2026, 5, 5), source_id=src1.id)
        .first()
    )
    assert obs_day5_src1.quality_flag == "OK"

    # 2. Chạy đối chiếu chéo đa nguồn (FR-35)
    reconcile_stats = run_cross_source_reconciliation(
        db_session, threshold_pct=5.0, commodity_id=comm.id, province_id=prov.id
    )
    assert reconcile_stats["groups_compared"] == 1
    assert reconcile_stats["groups_flagged"] == 1
    assert reconcile_stats["records_flagged"] == 2

    day5_records = (
        db_session.query(PriceObservation)
        .filter_by(obs_date=date(2026, 5, 5), commodity_id=comm.id, province_id=prov.id)
        .all()
    )
    assert len(day5_records) == 2
    assert all(r.review_flag is True for r in day5_records)


def test_coverage_report_generation(db_session: Session):
    """Kiểm tra hàm tạo báo cáo chất lượng & độ phủ dữ liệu theo FR-42."""
    price_collector = AgriPriceCollector(db=db_session, rate_limit_delay=0.0)
    # Nạp 40 ngày dữ liệu thực tế từ loader cho CAFE_ROBUSTA tại Đắk Lắk
    count = price_collector.collect_price_range(
        start_date=date(2026, 1, 1),
        end_date=date(2026, 2, 9),
        commodity_code="CAFE_ROBUSTA",
        province_code="DL",
        log_pipeline=True,
    )
    assert count == 40

    # Kiểm tra với ngưỡng min_training_days = 30 -> Đủ điều kiện
    report_pass = generate_data_quality_and_coverage_report(
        db=db_session,
        min_training_days=30,
        print_table=False,
    )
    assert report_pass["summary"]["total_price_records"] == 40
    assert report_pass["summary"]["eligible_series_for_training"] == 1
    series_info = report_pass["series_coverage"][0]
    assert series_info["commodity_code"] == "CAFE_ROBUSTA"
    assert series_info["province_code"] == "DL"
    assert series_info["total_days_with_data"] == 40
    assert series_info["missing_ratio"] == 0.0
    assert series_info["max_gap_days"] == 1
    assert series_info["is_eligible_for_training"] is True

    # Kiểm tra với ngưỡng min_training_days = 365 -> Chưa đủ 365 ngày nên is_eligible_for_training = False
    report_strict = generate_data_quality_and_coverage_report(
        db=db_session,
        min_training_days=365,
        print_table=False,
    )
    assert report_strict["series_coverage"][0]["is_eligible_for_training"] is False

