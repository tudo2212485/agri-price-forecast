"""Database initialization and master data seeding script (Section 4.1, 4.2, 4.3).

Thực hiện:
1. Kết nối PostgreSQL/TimescaleDB, tự động tạo CSDL nếu chưa tồn tại.
2. Khởi tạo toàn bộ các bảng theo SQLAlchemy 2.0 Models.
3. Tạo SQL View data_coverage_view phục vụ báo cáo độ phủ (FR-42).
4. Seed dữ liệu thực tế (Idempotent - an toàn khi chạy lại nhiều lần):
   - 8 Tỉnh trọng điểm kèm tọa độ địa lý và aliases (FR-33).
   - 3 Nông sản chủ lực: Cà phê Robusta, Hồ tiêu đen, Lúa IR50404.
   - 4 Nguồn dữ liệu uy tín (giá nông sản và Open-Meteo Weather API).
   - 3 Quy tắc cảnh báo mặc định (ngưỡng 5%, cửa sổ 7 ngày).
"""

import sys
import os

# Đảm bảo in tiếng Việt trên console Windows không bị UnicodeEncodeError
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from typing import Dict, Any
from urllib.parse import urlparse
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from sqlalchemy.orm import Session

# Thêm thư mục gốc vào PYTHONPATH để import module dễ dàng
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from db.database import engine, Base, SessionLocal, DATABASE_URL
from db.models import Province, ProvinceAlias, Commodity, DataSource, AlertRule
from db.views import create_data_coverage_view


# Danh mục 8 Tỉnh trọng điểm và aliases theo yêu cầu SRS v1.1
SEED_PROVINCES = [
    {
        "code": "LD",
        "standard_name": "Lâm Đồng",
        "region": "Tây Nguyên",
        "lat": 11.5753,
        "lon": 108.1429,
        "aliases": ["Lâm Đồng", "Lam Dong", "Bảo Lộc", "Di Linh", "Đức Trọng"],
    },
    {
        "code": "DL",
        "standard_name": "Đắk Lắk",
        "region": "Tây Nguyên",
        "lat": 12.6667,
        "lon": 108.0500,
        "aliases": ["Đắk Lắk", "Dak Lak", "Đăk Lăk", "Buôn Ma Thuột", "Cư M'gar"],
    },
    {
        "code": "GL",
        "standard_name": "Gia Lai",
        "region": "Tây Nguyên",
        "lat": 13.9833,
        "lon": 108.0000,
        "aliases": ["Gia Lai", "Pleiku", "Chư Sê"],
    },
    {
        "code": "DN",
        "standard_name": "Đắk Nông",
        "region": "Tây Nguyên",
        "lat": 12.0042,
        "lon": 107.6907,
        "aliases": ["Đắk Nông", "Dak Nong", "Đăk Nông", "Gia Nghĩa"],
    },
    {
        "code": "BRVT",
        "standard_name": "Bà Rịa - Vũng Tàu",
        "region": "Đông Nam Bộ",
        "lat": 10.5417,
        "lon": 107.2429,
        "aliases": ["Bà Rịa - Vũng Tàu", "Bà Rịa Vũng Tàu", "BR-VT", "Châu Đức"],
    },
    {
        "code": "AG",
        "standard_name": "An Giang",
        "region": "ĐBSCL",
        "lat": 10.5216,
        "lon": 105.1259,
        "aliases": ["An Giang", "Long Xuyên", "Châu Đốc"],
    },
    {
        "code": "DT",
        "standard_name": "Đồng Tháp",
        "region": "ĐBSCL",
        "lat": 10.4938,
        "lon": 105.6882,
        "aliases": ["Đồng Tháp", "Dong Thap", "Cao Lãnh"],
    },
    {
        "code": "CT",
        "standard_name": "Cần Thơ",
        "region": "ĐBSCL",
        "lat": 10.0452,
        "lon": 105.7469,
        "aliases": ["Cần Thơ", "Can Tho"],
    },
]

# Danh mục 3 Nông sản chủ lực
SEED_COMMODITIES = [
    {
        "code": "CAFE_ROBUSTA",
        "name": "Cà phê nhân xô (Robusta)",
        "unit": "VNĐ/kg",
        "category": "Cây công nghiệp",
    },
    {
        "code": "TIEU_DEN",
        "name": "Hồ tiêu đen",
        "unit": "VNĐ/kg",
        "category": "Cây công nghiệp",
    },
    {
        "code": "LUA_IR50404",
        "name": "Lúa tươi IR50404",
        "unit": "VNĐ/kg",
        "category": "Lương thực",
    },
]

# Danh mục Nguồn dữ liệu thật (Section 3.7.1, 4.1)
SEED_DATA_SOURCES = [
    {
        "name": "Chuyên trang Giá Cà Phê / Hiệp hội Vicofa",
        "publisher": "Hiệp hội Cà phê - Ca cao Việt Nam (VICOFA)",
        "url_or_api": "https://giacaphe.com/gia-ca-phe-noi-dia/",
        "source_type": "PRICE",
        "price_type": "Thu mua tại vườn",
        "raw_unit": "VNĐ/kg",
        "frequency": "DAILY",
        "reliability_level": "HIGH",
        "terms_of_use": "Dữ liệu khảo sát thị trường công khai hàng ngày phục vụ nghiên cứu phi thương mại",
        "is_active": True,
    },
    {
        "name": "Hiệp hội Hồ tiêu và Cây gia vị Việt Nam (VPSA) / GiaTieu",
        "publisher": "Hiệp hội Hồ tiêu và Cây gia vị Việt Nam (VPSA)",
        "url_or_api": "https://giatieu.com/gia-tieu-hom-nay/",
        "source_type": "PRICE",
        "price_type": "Thu mua tại vườn",
        "raw_unit": "VNĐ/kg",
        "frequency": "DAILY",
        "reliability_level": "HIGH",
        "terms_of_use": "Bản tin tổng hợp giá giao dịch đại lý công khai",
        "is_active": True,
    },
    {
        "name": "Sở NN&PTNT An Giang / Hiệp hội Lương thực Việt Nam (VFA)",
        "publisher": "Sở Nông nghiệp và PTNT Tỉnh An Giang / VFA",
        "url_or_api": "https://vfa.gov.vn/gia-lua-gao-noi-dia/",
        "source_type": "PRICE",
        "price_type": "Thu mua tại ruộng",
        "raw_unit": "VNĐ/kg",
        "frequency": "DAILY",
        "reliability_level": "HIGH",
        "terms_of_use": "Số liệu thống kê giá nông sản tỉnh định kỳ công khai",
        "is_active": True,
    },
    {
        "name": "Open-Meteo Historical & Forecast API",
        "publisher": "Open-Meteo GmbH",
        "url_or_api": "https://archive-api.open-meteo.com/v1/archive",
        "source_type": "WEATHER",
        "price_type": None,
        "raw_unit": "°C, mm, %",
        "frequency": "DAILY",
        "reliability_level": "HIGH",
        "terms_of_use": "Open-source weather API under Non-Commercial Educational and Research license",
        "is_active": True,
    },
]


def ensure_postgres_database_exists(db_url: str) -> None:
    """Tự động kết nối database server và tạo database mục tiêu nếu chưa tồn tại."""
    if not db_url.startswith("postgresql"):
        return

    parsed = urlparse(db_url)
    target_db = parsed.path.lstrip("/")
    user = parsed.username or "postgres"
    password = parsed.password or "postgres"
    host = parsed.hostname or "localhost"
    port = parsed.port or 5432

    # Kết nối đến database hệ thống 'postgres' để kiểm tra và tạo database mục tiêu
    try:
        conn = psycopg2.connect(
            dbname="postgres",
            user=user,
            password=password,
            host=host,
            port=port
        )
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (target_db,))
            exists = cur.fetchone()
            if not exists:
                print(f"[Init DB] Database '{target_db}' chưa tồn tại. Đang tiến hành tạo mới...")
                cur.execute(f'CREATE DATABASE "{target_db}"')
                print(f"[Init DB] Đã tạo thành công database '{target_db}'.")
            else:
                print(f"[Init DB] Database '{target_db}' đã sẵn sàng.")
        conn.close()
    except Exception as exc:
        print(f"[Init DB Warning] Không thể tự động tạo DB qua kết nối hệ thống (lỗi: {exc}). Tiếp tục thử kết nối trực tiếp...")


def seed_master_data(db: Session) -> Dict[str, int]:
    """
    Thực hiện seed danh mục mẫu vào CSDL một cách Idempotent.
    Chạy lại nhiều lần không sinh bản ghi trùng hoặc lỗi Unique Constraint.
    """
    stats = {
        "provinces_added": 0,
        "aliases_added": 0,
        "commodities_added": 0,
        "sources_added": 0,
        "alert_rules_added": 0,
    }

    # 1. Seed Tỉnh thành và Aliases
    for p_info in SEED_PROVINCES:
        prov = db.query(Province).filter(Province.code == p_info["code"]).first()
        if not prov:
            prov = Province(
                code=p_info["code"],
                standard_name=p_info["standard_name"],
                region=p_info["region"],
                lat=p_info["lat"],
                lon=p_info["lon"]
            )
            db.add(prov)
            db.flush()  # Sinh ID
            stats["provinces_added"] += 1

        for alias in p_info["aliases"]:
            existing_alias = db.query(ProvinceAlias).filter(ProvinceAlias.alias_name == alias).first()
            if not existing_alias:
                pa = ProvinceAlias(alias_name=alias, province_id=prov.id)
                db.add(pa)
                stats["aliases_added"] += 1

    # 2. Seed Nông sản
    for c_info in SEED_COMMODITIES:
        comm = db.query(Commodity).filter(Commodity.code == c_info["code"]).first()
        if not comm:
            comm = Commodity(
                code=c_info["code"],
                name=c_info["name"],
                unit=c_info["unit"],
                category=c_info["category"]
            )
            db.add(comm)
            stats["commodities_added"] += 1

    db.flush()

    # 3. Seed Nguồn dữ liệu
    for s_info in SEED_DATA_SOURCES:
        source = db.query(DataSource).filter(DataSource.name == s_info["name"]).first()
        if not source:
            source = DataSource(**s_info)
            db.add(source)
            stats["sources_added"] += 1
        else:
            source.url_or_api = s_info["url_or_api"]
            source.publisher = s_info["publisher"]

    db.flush()

    # 4. Seed Quy tắc cảnh báo mặc định (ngưỡng 5%, cửa sổ 7 ngày cho cả 3 nông sản)
    commodities = db.query(Commodity).all()
    for comm in commodities:
        rule = db.query(AlertRule).filter(
            AlertRule.commodity_id == comm.id,
            AlertRule.threshold_pct == 5.0,
            AlertRule.window_days == 7
        ).first()
        if not rule:
            alert_rule = AlertRule(
                commodity_id=comm.id,
                province_id=None,  # Áp dụng chung cho nông sản
                threshold_pct=5.0,
                window_days=7,
                channel="EMAIL",
                is_active=True
            )
            db.add(alert_rule)
            stats["alert_rules_added"] += 1

    db.commit()
    return stats


def init_database() -> None:
    """Hàm điều phối toàn bộ quá trình khởi tạo CSDL & Seed."""
    print("==================================================================")
    print("KHỞI TẠO HỆ CƠ SỞ DỮ LIỆU & SCHEMA (PHASE 1 - SRS v1.1)")
    print("==================================================================")
    print(f"Target Database URL: {DATABASE_URL}")

    # 1. Đảm bảo database mục tiêu tồn tại
    ensure_postgres_database_exists(DATABASE_URL)

    # 2. Tạo toàn bộ bảng
    print("[Init DB] Đang khởi tạo các bảng qua SQLAlchemy metadata...")
    Base.metadata.create_all(bind=engine)
    print("[Init DB] Đã tạo thành công 13 bảng theo thiết kế Section 4.1, 4.3.")

    # 3. Tạo View thống kê độ phủ
    print("[Init DB] Đang tạo SQL View data_coverage_view...")
    create_data_coverage_view(engine)
    print("[Init DB] Hoàn tất cấu hình data_coverage_view.")

    # 4. Seed master data
    print("[Init DB] Đang thực hiện seed danh mục master data...")
    with SessionLocal() as db:
        stats = seed_master_data(db)
        print(f"[Init DB] Kết quả Seed Master Data:")
        print(f"  + Tỉnh mới: {stats['provinces_added']}")
        print(f"  + Tên gọi khác (Aliases) mới: {stats['aliases_added']}")
        print(f"  + Nông sản mới: {stats['commodities_added']}")
        print(f"  + Nguồn dữ liệu mới: {stats['sources_added']}")
        print(f"  + Quy tắc cảnh báo mới: {stats['alert_rules_added']}")

    print("==================================================================")
    print("HOÀN TẤT KHỞI TẠO DATABASE PHASE 1 THÀNH CÔNG!")
    print("==================================================================")


if __name__ == "__main__":
    init_database()
