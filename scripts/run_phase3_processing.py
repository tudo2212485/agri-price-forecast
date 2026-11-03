"""CLI Script to Execute Phase 3: Cleaning, Short-Gap Interpolation, Feature Engineering & EDA.

Thực hiện tuần tự:
1. Khởi tạo bảng feature_set trong PostgreSQL/TimescaleDB (nếu chưa có).
2. Chạy TimeSeriesCleaner & FeatureEngineer cho toàn bộ 11 chuỗi (nông sản - tỉnh):
   - Làm sạch, xử lý ngoại lệ quá khứ, nội suy ngắn hạn (<= 3 ngày) và hợp nhất thời tiết.
   - Tạo 31 cột đặc trưng (Lag, Rolling, Thời tiết tích lũy, Lịch & Mùa vụ) chống rò rỉ tương lai (NFR-04).
   - Lưu (Idempotent Upsert) vào bảng feature_set.
3. Chạy phân tích khám phá dữ liệu (EDA - FR-10) và xuất 4 biểu đồ PNG (150 DPI) vào docs/eda_figures/
   cùng file tổng hợp docs/eda_summary.json.
4. In bảng tổng kết kết quả Phase 3 ra màn hình console.
"""

import os
import sys

# Đảm bảo console Windows hiển thị tiếng Việt UTF-8
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from db.database import SessionLocal, engine, Base
from processing.features import FeatureEngineer
from processing.eda import run_exploratory_data_analysis


def main() -> None:
    print("=" * 105)
    print("KHỞI CHẠY PHASE 3: DATA CLEANING, SHORT-GAP INTERPOLATION, FEATURE ENGINEERING & EDA")
    print("=" * 105)

    # Bước 0: Đảm bảo bảng feature_set được tạo trong CSDL
    Base.metadata.create_all(bind=engine)
    print("[Phase 3] Đã đồng bộ schema bảng 'feature_set' trong CSDL.")

    with SessionLocal() as db:
        # Bước 1 & 2: Làm sạch, Nội suy, Hợp nhất Thời tiết & Sinh Đặc trưng
        print("\n[Bước 1/2] Đang làm sạch, hợp nhất thời tiết và tính toán đặc trưng cho 11 chuỗi...")
        engineer = FeatureEngineer(db=db)
        feat_stats = engineer.build_and_save_all_series()

        print(
            f"  + Đã xử lý thành công : {feat_stats['total_series_processed']} chuỗi (Nông sản - Tỉnh)"
        )
        print(
            f"  + Tổng số dòng đã lưu vào bảng feature_set : {feat_stats['total_rows_upserted']:,} bản ghi"
        )
        print(
            f"  + Tổng số điểm nội suy ngắn hạn (<= 3 ngày) : {feat_stats['total_interpolated_points']:,} điểm"
        )
        print(
            f"  + Số lượng cột đặc trưng (Feature Columns)  : {feat_stats['feature_columns_count']} cột"
        )

        # Bước 3: Phân tích Khám phá Dữ liệu (EDA) & Xuất Biểu đồ
        print("\n[Bước 2/2] Đang thực hiện Phân tích Khám phá (EDA) và kết xuất biểu đồ báo cáo (150 DPI)...")
        eda_summary = run_exploratory_data_analysis(db=db)

        print("\n" + "=" * 105)
        print("BẢNG THỐNG KÊ ĐẶC TRƯNG & PHÂN TÍCH KHÁM PHÁ DỮ LIỆU (PHASE 3 - FR-09, FR-10, NFR-04)")
        print("=" * 105)
        header = (
            f"{'Nông sản':<15} | {'Tỉnh':<18} | {'Số dòng':>8} | {'Giá TB (VNĐ)':>13} | "
            f"{'Min -> Max':>21} | {'ACF(1)':>7} | {'ACF(7)':>7} | {'ACF(30)':>7}"
        )
        print(header)
        print("-" * 105)
        for s in eda_summary["series_statistics"]:
            min_max_str = f"{s['min_price']:,.0f} -> {s['max_price']:,.0f}"
            print(
                f"{s['commodity_code']:<15} | {s['province_name']:<18} | {s['count']:>8,} | "
                f"{s['mean_price']:>13,.0f} | {min_max_str:>21} | "
                f"{s['acf_lag_1']:>7.3f} | {s['acf_lag_7']:>7.3f} | {s['acf_lag_30']:>7.3f}"
            )
        print("-" * 105)
        print("CÁC FILE BIỂU ĐỒ EDA ĐÃ XUẤT THÀNH CÔNG (150 DPI):")
        for fig_name, fig_path in eda_summary["figures_generated"].items():
            file_kb = os.path.getsize(fig_path) / 1024.0 if os.path.exists(fig_path) else 0.0
            print(f"  + [{fig_name:<28}] : {fig_path} ({file_kb:.1f} KB)")
        print("=" * 105)
        print("HOÀN TẤT PHASE 3 THÀNH CÔNG!")


if __name__ == "__main__":
    main()

