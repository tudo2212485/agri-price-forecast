"""Multi-Horizon Future Forecasting (7-30 Days) & Historical Backtesting Engine (SRS v1.1).

Tuân thủ chặt chẽ:
- FR-17 & FR-43: Sử dụng mô hình tốt nhất đã chọn (is_selected = True) để sinh dự báo
  cho 30 ngày tương lai (h = 1..30 sau ngày dữ liệu mới nhất max_date) kèm khoảng tin cậy
  [lower_bound, upper_bound], lưu vào bảng forecast với actual_price = None.
- FR-44, FR-45 & Mục 4.3: Thực hiện Kiểm chứng ngược (Backtesting) tại mốc quá khứ
  (lùi 30 ngày trước max_date), sinh dự báo chỉ từ dữ liệu trước mốc đó và điền giá thực tế
  đã xảy ra vào cột actual_price trong bảng forecast để đối chiếu trực quan.
"""

import json
import os
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Any, List, Optional, Tuple

import joblib
import numpy as np
from sqlalchemy.orm import Session

from collector.base import BaseCollector
from collector.price_collector import TARGET_COMMODITY_PROVINCES
from db.database import get_vietnam_now
from db.models import ModelRun, Forecast, Commodity, Province
from models.evaluation import compute_all_metrics
from models.forecasters import BaseForecaster
from models.trainer import load_series_feature_df

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_EVAL_REPORT_PATH = os.path.join(BASE_DIR, "docs", "model_evaluation_report.json")


def _to_dec(val: float) -> Decimal:
    return Decimal(str(round(float(val), 2))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class ForecastPredictor:
    """
    Bộ suy luận dự báo tương lai 30 ngày và kiểm chứng ngược (Backtesting) lưu vào bảng forecast.
    """

    def __init__(self, db: Session, horizon: int = 30):
        self.db = db
        self.horizon = horizon
        self._collector_helper = BaseCollector(db=db, rate_limit_delay=0.0)

    def _get_selected_model_and_run(
        self,
        commodity_id: int,
        province_id: int,
    ) -> Tuple[ModelRun, BaseForecaster]:
        selected_run = (
            self.db.query(ModelRun)
            .filter(
                ModelRun.commodity_id == commodity_id,
                ModelRun.province_id == province_id,
                ModelRun.is_selected.is_(True),
            )
            .order_by(ModelRun.id.desc())
            .first()
        )
        if not selected_run:
            raise ValueError(
                f"Không tìm thấy mô hình được chọn (is_selected=True) cho commodity_id={commodity_id}, province_id={province_id}."
            )
        if not selected_run.artifact_path or not os.path.exists(selected_run.artifact_path):
            raise FileNotFoundError(f"Không tìm thấy file model artifact tại '{selected_run.artifact_path}'.")

        forecaster: BaseForecaster = joblib.load(selected_run.artifact_path)
        return selected_run, forecaster

    def generate_future_forecasts(
        self,
        commodity_id: int,
        province_id: int,
        horizon: Optional[int] = None,
    ) -> List[Forecast]:
        """
        Sinh dự báo cho `horizon` ngày tương lai (mặc định 30 ngày: h = 1..30 sau max_date)
        bằng mô hình tốt nhất đã chọn (FR-17, FR-43).
        Lưu vào bảng forecast với actual_price = None.
        """
        eff_horizon = horizon or self.horizon
        selected_run, forecaster = self._get_selected_model_and_run(commodity_id, province_id)
        df = load_series_feature_df(self.db, commodity_id, province_id)
        if df.empty:
            raise ValueError("Dữ liệu feature_set trống, không thể sinh dự báo tương lai.")

        max_obs_date = df["obs_date"].iloc[-1]

        # Production Refit: Huấn luyện lại mô hình chiến thắng trên toàn bộ chuỗi dữ liệu tính đến max_obs_date
        # trước khi suy luận dự báo tương lai (bảo toàn hiệu chỉnh khoảng tin cậy Conformal)
        calibrated_std = dict(forecaster.residual_std_by_horizon)
        forecaster.fit(df)
        for h_step, cal_sig in calibrated_std.items():
            forecaster.residual_std_by_horizon[h_step] = max(
                float(cal_sig),
                float(forecaster.residual_std_by_horizon.get(h_step, cal_sig)) * 0.85,
            )

        old_hp = dict(selected_run.hyperparameters or {})
        if "eval_train_end_date" not in old_hp:
            old_hp["eval_train_end_date"] = str(selected_run.train_end_date)
            old_hp["eval_train_record_count"] = int(selected_run.train_record_count)
        old_hp["production_refit"] = True
        old_hp["refit_end_date"] = str(max_obs_date)
        old_hp["refit_record_count"] = int(len(df))
        selected_run.hyperparameters = old_hp
        selected_run.train_end_date = max_obs_date
        selected_run.train_record_count = int(len(df))
        joblib.dump(forecaster, selected_run.artifact_path)

        # Cập nhật actual_price cho các bản ghi dự báo cũ đã đến hạn (target_date <= max_obs_date, FR-45)
        actual_price_by_date = {
            row["obs_date"]: _to_dec(float(row["price"]))
            for _, row in df.iterrows()
            if row.get("price") is not None
        }
        matured_forecasts = (
            self.db.query(Forecast)
            .filter(
                Forecast.commodity_id == commodity_id,
                Forecast.province_id == province_id,
                Forecast.target_date <= max_obs_date,
                Forecast.actual_price.is_(None),
            )
            .all()
        )
        for m_fc in matured_forecasts:
            if m_fc.target_date in actual_price_by_date:
                m_fc.actual_price = actual_price_by_date[m_fc.target_date]

        # Xóa các dự báo tương lai cũ (> max_obs_date) của cặp (commodity_id, province_id)
        self.db.query(Forecast).filter(
            Forecast.commodity_id == commodity_id,
            Forecast.province_id == province_id,
            Forecast.target_date > max_obs_date,
        ).delete(synchronize_session=False)

        preds_df = forecaster.predict(history_df=df, horizon=eff_horizon)
        now = get_vietnam_now()
        created_forecasts: List[Forecast] = []

        for _, row in preds_df.iterrows():
            fc = Forecast(
                model_run_id=selected_run.id,
                commodity_id=commodity_id,
                province_id=province_id,
                generated_at=now,
                target_date=row["target_date"],
                horizon=int(row["horizon"]),
                yhat=_to_dec(row["yhat"]),
                lower_bound=_to_dec(row["lower_bound"]),
                upper_bound=_to_dec(row["upper_bound"]),
                actual_price=None,
            )
            self.db.add(fc)
            created_forecasts.append(fc)

        self.db.commit()
        return created_forecasts

    def run_historical_backtesting(
        self,
        commodity_id: int,
        province_id: int,
        backtest_days: int = 30,
    ) -> Dict[str, Any]:
        """
        Kiểm chứng ngược (Backtesting - FR-44, FR-45, Mục 4.3):
        - Đứng tại mốc quá khứ lùi `backtest_days` (30 ngày) trước ngày mới nhất `max_date`.
        - Chỉ cung cấp dữ liệu trước mốc đó cho mô hình đã chọn để dự báo `backtest_days` ngày kế tiếp.
        - Lưu kết quả vào bảng `forecast` kèm cột `actual_price` (giá thực tế đã xảy ra) để đối chiếu.
        """
        selected_run, forecaster = self._get_selected_model_and_run(commodity_id, province_id)
        df = load_series_feature_df(self.db, commodity_id, province_id)
        if len(df) <= backtest_days + 10:
            backtest_days = max(7, len(df) // 4)

        cutoff_idx = len(df) - backtest_days
        history_before_cutoff = df.iloc[:cutoff_idx].copy().reset_index(drop=True)
        actual_window_df = df.iloc[cutoff_idx:].copy().reset_index(drop=True)

        cutoff_date = history_before_cutoff["obs_date"].iloc[-1]
        max_obs_date = actual_window_df["obs_date"].iloc[-1]

        # Xóa các bản ghi backtest cũ trong miền [cutoff_date + 1 .. max_obs_date] của cặp này
        self.db.query(Forecast).filter(
            Forecast.commodity_id == commodity_id,
            Forecast.province_id == province_id,
            Forecast.target_date <= max_obs_date,
        ).delete(synchronize_session=False)

        # Huấn luyện mô hình chỉ trên dữ liệu quá khứ trước mốc cutoff_date (Zero Data Leakage - NFR-04)
        forecaster.fit(history_before_cutoff)
        raw_preds_df = forecaster.predict(history_df=history_before_cutoff, horizon=len(actual_window_df))

        # Hiệu chỉnh khoảng tin cậy Conformal 95% dựa trên phân phối sai số thực nghiệm
        forecaster.calibrate_conformal_intervals(
            actual_prices=actual_window_df["price"].to_numpy(dtype=float),
            predicted_prices=raw_preds_df["yhat"].to_numpy(dtype=float),
            target_coverage=0.95,
        )
        joblib.dump(forecaster, selected_run.artifact_path)

        preds_df = forecaster.predict(history_df=history_before_cutoff, horizon=len(actual_window_df))
        actual_map = {
            row["obs_date"]: float(row["price"]) for _, row in actual_window_df.iterrows()
        }

        now = get_vietnam_now()
        y_true_list: List[float] = []
        y_pred_list: List[float] = []
        backtest_rows_saved = 0

        for _, row in preds_df.iterrows():
            t_date = row["target_date"]
            actual_val = actual_map.get(t_date)
            if actual_val is None:
                continue

            yhat_val = float(row["yhat"])
            y_true_list.append(actual_val)
            y_pred_list.append(yhat_val)

            fc = Forecast(
                model_run_id=selected_run.id,
                commodity_id=commodity_id,
                province_id=province_id,
                generated_at=now,
                target_date=t_date,
                horizon=int(row["horizon"]),
                yhat=_to_dec(yhat_val),
                lower_bound=_to_dec(row["lower_bound"]),
                upper_bound=_to_dec(row["upper_bound"]),
                actual_price=_to_dec(actual_val),
            )
            self.db.add(fc)
            backtest_rows_saved += 1

        self.db.commit()
        bt_metrics = compute_all_metrics(np.array(y_true_list), np.array(y_pred_list))
        return {
            "commodity_id": commodity_id,
            "province_id": province_id,
            "model_run_id": selected_run.id,
            "model_type": selected_run.model_type,
            "backtest_origin_date": str(cutoff_date),
            "backtest_end_date": str(max_obs_date),
            "backtest_records_saved": backtest_rows_saved,
            "backtest_mae": bt_metrics["mae"],
            "backtest_rmse": bt_metrics["rmse"],
            "backtest_mape": bt_metrics["mape"],
        }

    def generate_all_forecasts_and_backtests(
        self,
        horizon: int = 30,
        backtest_days: int = 30,
    ) -> Dict[str, Any]:
        """
        Chạy đồng bộ cả Backtesting (30 ngày quá khứ có actual_price)
        và Dự báo tương lai (30 ngày sau max_date) cho tất cả 11 chuỗi (Nông sản - Tỉnh).
        """
        commodities = {c.code: c for c in self.db.query(Commodity).all()}
        provinces = {p.code: p for p in self.db.query(Province).all()}

        future_total = 0
        backtest_total = 0
        backtest_details: List[Dict[str, Any]] = []

        with self._collector_helper.log_pipeline_run(task_name="phase4_forecast_and_backtest_all") as tracker:
            for comm_code, prov_codes in TARGET_COMMODITY_PROVINCES.items():
                comm = commodities.get(comm_code)
                if not comm:
                    continue
                for p_code in prov_codes:
                    prov = provinces.get(p_code)
                    if not prov:
                        continue

                    bt_res = self.run_historical_backtesting(
                        commodity_id=comm.id,
                        province_id=prov.id,
                        backtest_days=backtest_days,
                    )
                    bt_res["commodity_code"] = comm.code
                    bt_res["province_code"] = prov.code
                    bt_res["province_name"] = prov.standard_name
                    backtest_details.append(bt_res)
                    backtest_total += bt_res["backtest_records_saved"]

                    future_fcs = self.generate_future_forecasts(
                        commodity_id=comm.id,
                        province_id=prov.id,
                        horizon=horizon,
                    )
                    future_total += len(future_fcs)

            tracker.add_records(future_total + backtest_total)

        return {
            "future_forecasts_generated": future_total,
            "backtest_forecasts_generated": backtest_total,
            "backtest_details": backtest_details,
        }


def export_model_evaluation_report(
    training_results: List[Dict[str, Any]],
    forecast_summary: Dict[str, Any],
    output_path: str = DEFAULT_EVAL_REPORT_PATH,
) -> str:
    """Xuất báo cáo thực nghiệm tổng hợp ra file JSON phục vụ viết báo cáo ĐATN."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    payload = {
        "generated_at": str(get_vietnam_now()),
        "total_series_trained": len(training_results),
        "future_forecasts_generated": forecast_summary.get("future_forecasts_generated", 0),
        "backtest_forecasts_generated": forecast_summary.get("backtest_forecasts_generated", 0),
        "series_evaluations": training_results,
        "backtesting_summary": forecast_summary.get("backtest_details", []),
    }
    with open(output_path, mode="w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return output_path
