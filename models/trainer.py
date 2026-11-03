"""Model Training, Rolling-Origin Evaluation, Champion Selection & Artifact Persistence (SRS v1.1).

Tuân thủ chặt chẽ:
- FR-16 & FR-46: Huấn luyện 7 loại mô hình (NAIVE, SEASONAL_NAIVE, MOVING_AVG, PROPHET,
  RANDOM_FOREST, XGBOOST, LSTM), lưu siêu tham số, khoảng ngày train/test, số bản ghi train,
  chỉ số MAE/RMSE/MAPE và đường dẫn artifact vào bảng model_run.
- FR-16: Tự động so sánh theo chỉ số thống nhất (MAPE, RMSE) và đánh dấu mô hình tốt nhất
  với is_selected = True cho từng cặp (commodity_id, province_id).
- FR-38 & FR-42: Kiểm tra điều kiện đủ dữ liệu huấn luyện (>= 365 ngày cho mô hình chuẩn,
  >= 500 ngày cho LSTM).
"""

import os
import logging
from datetime import date
from typing import Dict, Any, List, Optional

import joblib
import pandas as pd
from sqlalchemy.orm import Session

from collector.base import BaseCollector
from collector.price_collector import TARGET_COMMODITY_PROVINCES
from db.database import get_vietnam_now
from db.models import FeatureSet, ModelRun, Commodity, Province
from models.evaluation import (
    set_global_seed,
    temporal_train_test_split,
    evaluate_forecaster_rolling_origin,
)
from models.forecasters import (
    BaseForecaster,
    NaiveForecaster,
    SeasonalNaiveForecaster,
    MovingAverageForecaster,
    ProphetForecaster,
    RandomForestForecaster,
    XGBoostForecaster,
    LSTMForecaster,
    MIN_RECORDS_FOR_LSTM,
)

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_ARTIFACTS_DIR = os.path.join(BASE_DIR, "models", "artifacts")


def load_series_feature_df(
    db: Session,
    commodity_id: int,
    province_id: int,
) -> pd.DataFrame:
    """Đọc chuỗi đặc trưng của cặp (commodity_id, province_id) từ bảng feature_set sắp xếp tăng dần theo obs_date."""
    rows = (
        db.query(FeatureSet)
        .filter(
            FeatureSet.commodity_id == commodity_id,
            FeatureSet.province_id == province_id,
        )
        .order_by(FeatureSet.obs_date.asc())
        .all()
    )
    if not rows:
        return pd.DataFrame()

    records: List[Dict[str, Any]] = []
    for r in rows:
        records.append({
            "obs_date": r.obs_date,
            "commodity_id": r.commodity_id,
            "province_id": r.province_id,
            "price": float(r.price),
            "is_interpolated": bool(r.is_interpolated),
            "quality_flag": r.quality_flag,
            "temp_max": r.temp_max,
            "temp_min": r.temp_min,
            "temp_mean": r.temp_mean,
            "precipitation": r.precipitation,
            "humidity": r.humidity,
            "precip_sum_7d": r.precip_sum_7d,
            "precip_sum_30d": r.precip_sum_30d,
            "temp_mean_7d": r.temp_mean_7d,
            "lag_1": r.lag_1,
            "lag_2": r.lag_2,
            "lag_3": r.lag_3,
            "lag_7": r.lag_7,
            "lag_14": r.lag_14,
            "lag_21": r.lag_21,
            "lag_30": r.lag_30,
            "rolling_mean_7": r.rolling_mean_7,
            "rolling_std_7": r.rolling_std_7,
            "rolling_mean_14": r.rolling_mean_14,
            "rolling_std_14": r.rolling_std_14,
            "rolling_mean_30": r.rolling_mean_30,
            "rolling_std_30": r.rolling_std_30,
            "pct_change_1d": r.pct_change_1d,
            "pct_change_7d": r.pct_change_7d,
            "day_of_week": r.day_of_week,
            "day_of_month": r.day_of_month,
            "month": r.month,
            "quarter": r.quarter,
            "day_of_year": r.day_of_year,
            "sin_day_of_year": r.sin_day_of_year,
            "cos_day_of_year": r.cos_day_of_year,
            "is_harvest_season": bool(r.is_harvest_season),
        })
    return pd.DataFrame(records).sort_values("obs_date", ascending=True).reset_index(drop=True)


class ModelTrainer:
    """
    Điều phối huấn luyện, đánh giá Rolling-Origin, lưu artifact và bình chọn mô hình tốt nhất (FR-16, FR-46).
    """

    def __init__(
        self,
        db: Session,
        artifacts_dir: str = DEFAULT_ARTIFACTS_DIR,
        test_days: int = 90,
        max_horizon: int = 30,
        eval_stride: int = 5,
        min_training_days: int = 365,
        min_records_for_lstm: int = MIN_RECORDS_FOR_LSTM,
        lstm_epochs: int = 22,
        seed: int = 42,
    ):
        self.db = db
        self.artifacts_dir = artifacts_dir
        self.test_days = test_days
        self.max_horizon = max_horizon
        self.eval_stride = eval_stride
        self.min_training_days = min_training_days
        self.min_records_for_lstm = min_records_for_lstm
        self.lstm_epochs = lstm_epochs
        self.seed = seed
        os.makedirs(self.artifacts_dir, exist_ok=True)
        self._collector_helper = BaseCollector(db=db, rate_limit_delay=0.0)

    def _build_candidate_forecasters(
        self,
        commodity_code: str,
        total_records: int,
    ) -> List[BaseForecaster]:
        """Khởi tạo danh sách các mô hình ứng viên cho một chuỗi (nông sản, tỉnh)."""
        candidates: List[BaseForecaster] = [
            NaiveForecaster(commodity_code=commodity_code, max_horizon=self.max_horizon, seed=self.seed),
            SeasonalNaiveForecaster(commodity_code=commodity_code, max_horizon=self.max_horizon, seed=self.seed),
            MovingAverageForecaster(commodity_code=commodity_code, max_horizon=self.max_horizon, seed=self.seed),
            ProphetForecaster(commodity_code=commodity_code, max_horizon=self.max_horizon, seed=self.seed),
            RandomForestForecaster(commodity_code=commodity_code, max_horizon=self.max_horizon, seed=self.seed),
            XGBoostForecaster(commodity_code=commodity_code, max_horizon=self.max_horizon, seed=self.seed),
        ]
        if total_records >= self.min_records_for_lstm:
            candidates.append(
                LSTMForecaster(
                    commodity_code=commodity_code,
                    max_horizon=self.max_horizon,
                    epochs=self.lstm_epochs,
                    min_records=min(self.min_records_for_lstm, max(30, total_records - self.test_days - 5)),
                    seed=self.seed,
                )
            )
        return candidates

    def train_and_evaluate_series(
        self,
        commodity: Commodity,
        province: Province,
    ) -> Dict[str, Any]:
        """
        Huấn luyện tất cả các mô hình cho 1 cặp (commodity, province), đánh giá trên tập Test 90 ngày,
        lưu model artifacts, ghi vào bảng model_run và chọn mô hình chiến thắng (is_selected = True).
        """
        df = load_series_feature_df(self.db, commodity.id, province.id)
        if len(df) < self.min_training_days:
            raise ValueError(
                f"Chuỗi ({commodity.code}, {province.code}) chỉ có {len(df)} ngày < ngưỡng {self.min_training_days} ngày (FR-38)."
            )

        train_df, test_df = temporal_train_test_split(df, test_days=self.test_days)
        train_start_dt: date = train_df["obs_date"].iloc[0]
        train_end_dt: date = train_df["obs_date"].iloc[-1]
        test_start_dt: date = test_df["obs_date"].iloc[0]
        test_end_dt: date = test_df["obs_date"].iloc[-1]
        train_count = len(train_df)

        # Đặt tất cả model_run cũ của cặp (commodity_id, province_id) về is_selected = False
        self.db.query(ModelRun).filter(
            ModelRun.commodity_id == commodity.id,
            ModelRun.province_id == province.id,
        ).update({"is_selected": False})
        self.db.commit()

        candidates = self._build_candidate_forecasters(commodity.code, len(df))
        created_runs: List[ModelRun] = []
        eval_details: List[Dict[str, Any]] = []

        for forecaster in candidates:
            set_global_seed(self.seed)
            # 1. Fit chỉ trên tập Train để đánh giá khách quan trên tập Test (NFR-04)
            forecaster.fit(train_df)

            # 2. Đánh giá Rolling-Origin trên miền kiểm tra
            eval_res = evaluate_forecaster_rolling_origin(
                forecaster=forecaster,
                full_df=df,
                train_end_idx=train_count,
                max_horizon=self.max_horizon,
                stride=self.eval_stride,
            )

            # 3. Lưu artifact mô hình ra đĩa
            artifact_filename = f"{commodity.code}_{province.code}_{forecaster.model_type}.pkl"
            artifact_path = os.path.join(self.artifacts_dir, artifact_filename)
            joblib.dump(forecaster, artifact_path)

            hyperparams_payload = {
                **forecaster.get_hyperparameters(),
                "horizon_metrics": eval_res["horizon_metrics"],
                "residual_analysis": eval_res["residual_analysis"],
            }

            run_record = ModelRun(
                commodity_id=commodity.id,
                province_id=province.id,
                model_type=forecaster.model_type,
                hyperparameters=hyperparams_payload,
                train_start_date=train_start_dt,
                train_end_date=train_end_dt,
                test_start_date=test_start_dt,
                test_end_date=test_end_dt,
                train_record_count=train_count,
                mae=eval_res["mae"],
                rmse=eval_res["rmse"],
                mape=eval_res["mape"],
                artifact_path=artifact_path,
                is_selected=False,
                created_at=get_vietnam_now(),
            )
            self.db.add(run_record)
            self.db.flush()
            created_runs.append(run_record)

            eval_details.append({
                "model_run_id": run_record.id,
                "model_type": forecaster.model_type,
                "mae": eval_res["mae"],
                "rmse": eval_res["rmse"],
                "mape": eval_res["mape"],
                "horizon_metrics": eval_res["horizon_metrics"],
                "residual_analysis": eval_res["residual_analysis"],
                "artifact_path": artifact_path,
            })

        # 4. Chọn mô hình tốt nhất theo MAPE thấp nhất (nếu bằng nhau thì xét RMSE) (FR-16)
        best_run = min(created_runs, key=lambda r: (r.mape if r.mape is not None else 9999.0, r.rmse or 999999.0))
        best_run.is_selected = True
        self.db.commit()

        for item in eval_details:
            item["is_selected"] = item["model_run_id"] == best_run.id

        return {
            "commodity_id": commodity.id,
            "commodity_code": commodity.code,
            "commodity_name": commodity.name,
            "province_id": province.id,
            "province_code": province.code,
            "province_name": province.standard_name,
            "train_start_date": str(train_start_dt),
            "train_end_date": str(train_end_dt),
            "test_start_date": str(test_start_dt),
            "test_end_date": str(test_end_dt),
            "train_record_count": train_count,
            "selected_model_run_id": best_run.id,
            "selected_model_type": best_run.model_type,
            "selected_mape": best_run.mape,
            "selected_rmse": best_run.rmse,
            "selected_mae": best_run.mae,
            "models": eval_details,
        }

    def train_all_eligible_series(self) -> List[Dict[str, Any]]:
        """Huấn luyện và chọn mô hình tốt nhất cho toàn bộ 11 chuỗi (Nông sản - Tỉnh) đủ điều kiện."""
        commodities = {c.code: c for c in self.db.query(Commodity).all()}
        provinces = {p.code: p for p in self.db.query(Province).all()}
        results: List[Dict[str, Any]] = []

        with self._collector_helper.log_pipeline_run(task_name="phase4_model_training_all") as tracker:
            for comm_code, prov_codes in TARGET_COMMODITY_PROVINCES.items():
                comm = commodities.get(comm_code)
                if not comm:
                    continue
                for p_code in prov_codes:
                    prov = provinces.get(p_code)
                    if not prov:
                        continue
                    series_res = self.train_and_evaluate_series(commodity=comm, province=prov)
                    results.append(series_res)
                    tracker.add_records(len(series_res["models"]))

        return results

