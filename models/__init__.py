"""Models Module: Huấn luyện, đánh giá, so sánh các mô hình chuỗi thời gian (Baseline, Prophet, RF, XGBoost, LSTM) và sinh dự báo."""

from models.evaluation import (
    set_global_seed,
    compute_mae,
    compute_rmse,
    compute_mape,
    compute_all_metrics,
    temporal_train_test_split,
    evaluate_forecaster_rolling_origin,
    analyze_residuals,
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
from models.trainer import ModelTrainer, load_series_feature_df, DEFAULT_ARTIFACTS_DIR
from models.predictor import (
    ForecastPredictor,
    export_model_evaluation_report,
    DEFAULT_EVAL_REPORT_PATH,
)

__all__ = [
    "set_global_seed",
    "compute_mae",
    "compute_rmse",
    "compute_mape",
    "compute_all_metrics",
    "temporal_train_test_split",
    "evaluate_forecaster_rolling_origin",
    "analyze_residuals",
    "BaseForecaster",
    "NaiveForecaster",
    "SeasonalNaiveForecaster",
    "MovingAverageForecaster",
    "ProphetForecaster",
    "RandomForestForecaster",
    "XGBoostForecaster",
    "LSTMForecaster",
    "MIN_RECORDS_FOR_LSTM",
    "ModelTrainer",
    "load_series_feature_df",
    "DEFAULT_ARTIFACTS_DIR",
    "ForecastPredictor",
    "export_model_evaluation_report",
    "DEFAULT_EVAL_REPORT_PATH",
]
