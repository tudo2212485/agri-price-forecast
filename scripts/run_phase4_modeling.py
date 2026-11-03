"""CLI Script to Execute Phase 4: Multi-Model Training, Rolling-Origin Evaluation, Backtesting & 30-Day Forecasting.

Thực hiện tuần tự cho toàn bộ 11 chuỗi (Nông sản - Tỉnh):
1. Huấn luyện & đánh giá Rolling-Origin cho cả 7 mô hình:
   NAIVE, SEASONAL_NAIVE, MOVING_AVG, PROPHET, RANDOM_FOREST, XGBOOST, LSTM.
2. Tự động bình chọn mô hình tốt nhất (is_selected = True) theo MAPE/RMSE thấp nhất,
   lưu vào bảng model_run và lưu model artifacts tại models/artifacts/.
3. Chạy Kiểm chứng ngược (Backtesting 30 ngày quá khứ có actual_price - FR-44)
   và Sinh dự báo tương lai 30 ngày (h = 1..30 sau max_date - FR-17, FR-43) lưu vào bảng forecast.
4. Xuất báo cáo thực nghiệm tổng hợp ra docs/model_evaluation_report.json và in bảng kết quả ra console.
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
from models.evaluation import set_global_seed
from models.trainer import ModelTrainer
from models.predictor import ForecastPredictor, export_model_evaluation_report


def main() -> None:
    print("=" * 120)
    print("KHỞI CHẠY PHASE 4: MODEL TRAINING, ROLLING-ORIGIN EVALUATION, BACKTESTING & 30-DAY FORECASTING")
    print("=" * 120)

    set_global_seed(42)
    Base.metadata.create_all(bind=engine)

    with SessionLocal() as db:
        # Bước 1 & 2: Huấn luyện 7 mô hình cho 11 chuỗi và bình chọn mô hình tốt nhất
        print("\n[Bước 1/3] Đang huấn luyện 7 mô hình (Baseline, Prophet, RF, XGBoost, LSTM) cho 11 chuỗi...")
        trainer = ModelTrainer(db=db, test_days=90, max_horizon=30, eval_stride=5, seed=42)
        training_results = trainer.train_all_eligible_series()
        print(f"  + Đã huấn luyện hoàn tất {len(training_results)} chuỗi ({len(training_results) * 7} model runs).")

        # Bước 3: Chạy Backtesting (FR-44) & Sinh dự báo 30 ngày tương lai (FR-17, FR-43)
        print("\n[Bước 2/3] Đang chạy Backtesting lịch sử (30 ngày) và Sinh dự báo tương lai (30 ngày)...")
        predictor = ForecastPredictor(db=db, horizon=30)
        forecast_summary = predictor.generate_all_forecasts_and_backtests(
            horizon=30,
            backtest_days=30,
        )
        print(
            f"  + Đã lưu {forecast_summary['backtest_forecasts_generated']:,} bản ghi Backtesting (actual_price != NULL)"
        )
        print(
            f"  + Đã lưu {forecast_summary['future_forecasts_generated']:,} bản ghi Dự báo tương lai 30 ngày (actual_price == NULL)"
        )

        # Bước 4: Xuất báo cáo thực nghiệm JSON và in bảng so sánh ra console
        print("\n[Bước 3/3] Đang xuất báo cáo thực nghiệm docs/model_evaluation_report.json...")
        report_path = export_model_evaluation_report(
            training_results=training_results,
            forecast_summary=forecast_summary,
        )

        print("\n" + "=" * 120)
        print("BẢNG SO SÁNH SAI SỐ MAPE (%) GIỮA CÁC MÔ HÌNH & MÔ HÌNH CHIẾN THẮNG (FR-15, FR-16, TIÊU CHÍ NGHIỆM THU SỐ 3)")
        print("=" * 120)
        header = (
            f"{'Nông sản':<13} | {'Tỉnh':<17} | {'NAIVE':>6} | {'S_NAIVE':>7} | {'MOV_AVG':>7} | "
            f"{'PROPHET':>7} | {'R_FOREST':>8} | {'XGBOOST':>7} | {'LSTM':>6} | {'MÔ HÌNH CHỌN (MAPE / RMSE)':<26}"
        )
        print(header)
        print("-" * 120)

        for res in training_results:
            m_map = {m["model_type"]: m for m in res["models"]}

            def _fmt_mape(m_type: str) -> str:
                if m_type not in m_map:
                    return "  N/A "
                return f"{m_map[m_type]['mape']:>5.2f}%"

            win_str = f"{res['selected_model_type']} ({res['selected_mape']:.2f}% / {res['selected_rmse']:,.0f})"
            print(
                f"{res['commodity_code']:<13} | {res['province_name']:<17} | "
                f"{_fmt_mape('NAIVE'):>6} | {_fmt_mape('SEASONAL_NAIVE'):>7} | {_fmt_mape('MOVING_AVG'):>7} | "
                f"{_fmt_mape('PROPHET'):>7} | {_fmt_mape('RANDOM_FOREST'):>8} | {_fmt_mape('XGBOOST'):>7} | "
                f"{_fmt_mape('LSTM'):>6} | {win_str:<26}"
            )

        print("-" * 120)
        print(f"File báo cáo đánh giá mô hình đã lưu tại: {report_path}")
        print("=" * 120)
        print("HOÀN TẤT PHASE 4 THÀNH CÔNG!")


if __name__ == "__main__":
    main()

