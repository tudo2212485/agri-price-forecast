"""CLI Script to Execute Phase 2: Data Collection, 3-Year Historical Backfill & Quality Check.

Thực hiện tuần tự:
1. Đảm bảo CSDL và Master Data sẵn sàng.
2. Chạy Backfill dữ liệu lịch sử > 3 năm (01/01/2023 - 01/11/2026) theo lô có Checkpoint cho:
   - 3 Nông sản chủ lực (CAFE_ROBUSTA, TIEU_DEN, LUA_IR50404) tại các tỉnh trọng điểm.
   - Dữ liệu thời tiết thực tế từ Open-Meteo API cho toàn bộ 8 tỉnh.
3. Chạy kiểm định chất lượng dữ liệu (FR-06) và đối chiếu chéo đa nguồn (FR-35).
4. Xuất và in bảng Báo cáo Chất lượng & Độ phủ Lịch sử (FR-06, FR-42) ra màn hình console.
"""

import argparse
import os
import sys
from datetime import datetime, date

# Cấu hình UTF-8 cho console Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from db.database import SessionLocal, engine, Base, get_vietnam_now
from db.models import PriceObservation, BackfillJob, DataSource, FeatureSet
from db.views import create_data_coverage_view
from scripts.init_db import ensure_postgres_database_exists, seed_master_data, DATABASE_URL
from collector.price_collector import ensure_verified_historical_csv_exists
from collector.backfill import BackfillManager
from processing.quality_check import (
    run_price_quality_checks,
    run_cross_source_reconciliation,
    generate_data_quality_and_coverage_report,
)


def parse_args() -> argparse.Namespace:
    default_today_str = get_vietnam_now().date().strftime("%Y-%m-%d")
    parser = argparse.ArgumentParser(
        description="Phase 2 Runner: Backfill lịch sử giá nông sản & thời tiết + Kiểm định chất lượng"
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default="2023-01-01",
        help="Ngày bắt đầu backfill (YYYY-MM-DD), mặc định: 2023-01-01",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default=default_today_str,
        help=f"Ngày kết thúc backfill (YYYY-MM-DD), mặc định theo ngày hiện tại: {default_today_str}",
    )
    parser.add_argument(
        "--price-batch-days",
        type=int,
        default=365,
        help="Số ngày mỗi lô backfill giá nông sản (mặc định: 365 ngày)",
    )
    parser.add_argument(
        "--weather-batch-days",
        type=int,
        default=730,
        help="Số ngày mỗi lô backfill thời tiết Open-Meteo (mặc định: 730 ngày)",
    )
    parser.add_argument(
        "--skip-weather",
        action="store_true",
        help="Bỏ qua bước gọi Open-Meteo API nếu chỉ muốn chạy backfill giá",
    )
    parser.add_argument(
        "--min-training-days",
        type=int,
        default=365,
        help="Ngưỡng số ngày tối thiểu để đánh giá đủ điều kiện huấn luyện (mặc định: 365)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    start_dt = datetime.strptime(args.start_date, "%Y-%m-%d").date()
    end_dt = datetime.strptime(args.end_date, "%Y-%m-%d").date()

    print("=" * 90)
    print("KHỞI CHẠY PHASE 2: COLLECTOR, 3-YEAR HISTORICAL BACKFILL & QUALITY CHECK")
    print("=" * 90)
    print(f"Khoảng thời gian Backfill : {start_dt} -> {end_dt} ({(end_dt - start_dt).days + 1} ngày)")

    # Bước 0: Đảm bảo Database, Schema, View và Master Data
    ensure_postgres_database_exists(DATABASE_URL)
    Base.metadata.create_all(bind=engine)
    create_data_coverage_view(engine)

    csv_path = ensure_verified_historical_csv_exists(force_rebuild=True)
    print(f"[Phase 2] Tập dữ liệu lịch sử xác thực sẵn sàng tại: {csv_path}")

    with SessionLocal() as db:
        seed_master_data(db)

        # Làm sạch bảng price_observation, feature_set và các backfill_job giá cũ để nạp lại dữ liệu chuẩn mới
        price_src_ids = [
            s.id for s in db.query(DataSource).filter(DataSource.source_type == "PRICE").all()
        ]
        if price_src_ids:
            db.query(BackfillJob).filter(BackfillJob.source_id.in_(price_src_ids)).delete(synchronize_session=False)
        db.query(PriceObservation).delete(synchronize_session=False)
        db.query(FeatureSet).delete(synchronize_session=False)
        db.commit()

        # Bước 1: Chạy Backfill lịch sử cho Giá nông sản & Thời tiết
        print("\n[Bước 1/3] Đang thực thi Backfill lịch sử theo lô kèm Checkpoint...")
        manager = BackfillManager(db=db)
        backfill_summary = manager.run_full_historical_backfill(
            start_date=start_dt,
            end_date=end_dt,
            price_batch_days=args.price_batch_days,
            weather_batch_days=args.weather_batch_days,
            include_weather=not args.skip_weather,
        )
        print(
            f"  + Hoàn tất {backfill_summary['price_jobs_completed']} jobs Giá nông sản "
            f"(Upserted trong phiên: {backfill_summary['price_records_upserted']:,} bản ghi)"
        )
        if not args.skip_weather:
            print(
                f"  + Hoàn tất {backfill_summary['weather_jobs_completed']} jobs Thời tiết Open-Meteo "
                f"(Upserted trong phiên: {backfill_summary['weather_records_upserted']:,} bản ghi)"
            )

        # Bước 2: Kiểm định chất lượng dữ liệu & Đối chiếu chéo đa nguồn
        print("\n[Bước 2/3] Đang chạy Kiểm tra Chất lượng (FR-06) & Đối chiếu chéo đa nguồn (FR-35)...")
        qc_stats = run_price_quality_checks(db)
        reconcile_stats = run_cross_source_reconciliation(db, threshold_pct=5.0)
        print(
            f"  + Kết quả Quality Check: Đã quét {qc_stats['total_checked']:,} bản ghi -> "
            f"OK: {qc_stats['ok_count']:,}, OUTLIER: {qc_stats['outlier_count']:,}, INVALID: {qc_stats['invalid_count']:,}"
        )
        print(
            f"  + Kết quả Đối chiếu chéo: Đã so sánh {reconcile_stats['groups_compared']:,} nhóm đa nguồn -> "
            f"Cảnh báo review_flag: {reconcile_stats['records_flagged']:,} bản ghi"
        )

        # Bước 3: Xuất báo cáo độ phủ và chất lượng dữ liệu
        print("\n[Bước 3/3] Đang tổng hợp Báo cáo Chất lượng & Độ phủ Lịch sử (FR-06, FR-42)...")
        generate_data_quality_and_coverage_report(
            db=db,
            min_training_days=args.min_training_days,
            print_table=True,
        )

    print("HOÀN TẤT PHASE 2 THÀNH CÔNG!")


if __name__ == "__main__":
    main()

