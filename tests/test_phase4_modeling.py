"""Comprehensive Test Suite for Phase 4: Modeling, Evaluation, Selection, Backtesting & Forecasting (SRS v1.1).

Bao gồm 4 nhóm kiểm thử bắt buộc:
1. test_time_series_evaluation_and_reproducibility: Chia thời gian không xáo trộn (NFR-04) & tái lập 100% với seed=42 (NFR-03).
2. test_all_model_types_trained_and_logged: Huấn luyện đủ 7 loại mô hình (NAIVE, SEASONAL_NAIVE, MOVING_AVG, PROPHET,
   RANDOM_FOREST, XGBOOST, LSTM), lưu artifact trên đĩa và đúng 1 mô hình is_selected = True (FR-11..14, FR-16, FR-46).
3. test_selected_model_beats_baseline: Mô hình chiến thắng (is_selected = True) có MAPE thấp hơn NAIVE baseline (Mục 9 - Tiêu chí nghiệm thu 3).
4. test_future_forecast_and_backtesting_records: Dự báo tương lai 30 ngày (actual_price IS NULL, lower <= yhat <= upper)
   và Backtesting quá khứ (actual_price IS NOT NULL) (FR-17, FR-43, FR-44).
"""

import os
from datetime import date, timedelta
import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from db.models import Commodity, Province, ModelRun, Forecast
from models.evaluation import (
    set_global_seed,
    temporal_train_test_split,
    evaluate_forecaster_rolling_origin,
)
from models.forecasters import (
    RandomForestForecaster,
    XGBoostForecaster,
    LSTMForecaster,
)
from models.trainer import ModelTrainer
from models.predictor import ForecastPredictor
from processing.features import FeatureEngineer


def _seed_synthetic_feature_series_in_db(
    db_session: Session,
    commodity_id: int,
    province_id: int,
    commodity_code: str = "CAFE_ROBUSTA",
    n_days: int = 240,
) -> pd.DataFrame:
    """
    Khởi tạo chuỗi thời gian có tính quy luật chu kỳ + xu hướng vào bảng feature_set
    phục vụ kiểm thử đơn vị nhanh và độc lập trong bộ nhớ.
    """
    start_dt = date(2025, 1, 1)
    dates = [start_dt + timedelta(days=i) for i in range(n_days)]
    t = np.arange(n_days, dtype=float)

    # Chuỗi giá có xu hướng nhẹ + sóng chu kỳ 14 ngày & mùa vụ năm xác định
    prices = (
        110000.0
        + 25.0 * t
        + 2200.0 * np.sin(2.0 * np.pi * t / 14.0)
        + 1200.0 * np.cos(2.0 * np.pi * t / 7.0)
    )
    temps = 25.0 + 3.0 * np.sin(2.0 * np.pi * t / 365.25)
    precips = 5.0 + 4.0 * np.cos(2.0 * np.pi * t / 30.0)

    raw_df = pd.DataFrame({
        "obs_date": dates,
        "commodity_id": commodity_id,
        "province_id": province_id,
        "price": np.round(prices, 2),
        "is_interpolated": False,
        "quality_flag": "OK",
        "temp_max": temps + 4.0,
        "temp_min": temps - 4.0,
        "temp_mean": temps,
        "precipitation": precips,
        "humidity": np.full(n_days, 78.0),
    })

    engineer = FeatureEngineer(db=db_session)
    feat_df = engineer.compute_features_from_dataframe(raw_df, commodity_code=commodity_code)
    engineer.upsert_feature_dataframe(feat_df)
    return feat_df


def test_time_series_evaluation_and_reproducibility(db_session: Session):
    """
    Kiểm tra:
    1. temporal_train_test_split giữ nguyên thứ tự thời gian nghiêm ngặt (shuffle=False, NFR-04).
    2. Chạy huấn luyện & đánh giá 2 lần với cùng seed=42 cho kết quả MAE, RMSE, MAPE giống hệt nhau 100% (NFR-03).
    """
    comm = db_session.query(Commodity).filter(Commodity.code == "CAFE_ROBUSTA").first()
    prov = db_session.query(Province).filter(Province.code == "DL").first()
    feat_df = _seed_synthetic_feature_series_in_db(
        db_session, comm.id, prov.id, commodity_code="CAFE_ROBUSTA", n_days=180
    )

    train_df, test_df = temporal_train_test_split(feat_df, test_days=40)
    assert len(train_df) == 140
    assert len(test_df) == 40
    assert train_df["obs_date"].is_monotonic_increasing
    assert test_df["obs_date"].is_monotonic_increasing
    assert train_df["obs_date"].max() < test_df["obs_date"].min()

    # Kiểm chứng tính tái lập 100% (Reproducibility) cho RandomForest, XGBoost và LSTM
    for model_cls, kwargs in [
        (RandomForestForecaster, {"n_estimators": 30, "max_horizon": 14, "seed": 42}),
        (XGBoostForecaster, {"n_estimators": 40, "max_horizon": 14, "seed": 42}),
        (LSTMForecaster, {"epochs": 8, "max_horizon": 14, "min_records": 50, "seed": 42}),
    ]:
        set_global_seed(42)
        m1 = model_cls(commodity_code="CAFE_ROBUSTA", **kwargs).fit(train_df)
        eval1 = evaluate_forecaster_rolling_origin(
            m1, full_df=feat_df, train_end_idx=len(train_df), max_horizon=14, stride=10
        )
        pred1 = m1.predict(train_df, horizon=14)["yhat"].to_numpy()

        set_global_seed(42)
        m2 = model_cls(commodity_code="CAFE_ROBUSTA", **kwargs).fit(train_df)
        eval2 = evaluate_forecaster_rolling_origin(
            m2, full_df=feat_df, train_end_idx=len(train_df), max_horizon=14, stride=10
        )
        pred2 = m2.predict(train_df, horizon=14)["yhat"].to_numpy()

        assert eval1["mae"] == eval2["mae"]
        assert eval1["rmse"] == eval2["rmse"]
        assert eval1["mape"] == eval2["mape"]
        assert np.allclose(pred1, pred2, atol=1e-9)


def test_all_model_types_trained_and_logged(db_session: Session, tmp_path):
    """
    Xác nhận ModelTrainer huấn luyện đủ 7 loại mô hình (NAIVE, SEASONAL_NAIVE, MOVING_AVG,
    PROPHET, RANDOM_FOREST, XGBOOST, LSTM), lưu đủ thông tin vào bảng model_run,
    lưu file artifact tồn tại trên đĩa, và đúng 1 mô hình có is_selected = True (FR-11..14, FR-16, FR-46).
    """
    comm = db_session.query(Commodity).filter(Commodity.code == "CAFE_ROBUSTA").first()
    prov = db_session.query(Province).filter(Province.code == "LD").first()
    _seed_synthetic_feature_series_in_db(
        db_session, comm.id, prov.id, commodity_code="CAFE_ROBUSTA", n_days=220
    )

    artifacts_dir = str(tmp_path / "artifacts")
    trainer = ModelTrainer(
        db=db_session,
        artifacts_dir=artifacts_dir,
        test_days=45,
        max_horizon=30,
        eval_stride=10,
        min_training_days=100,
        min_records_for_lstm=100,
        lstm_epochs=8,
        seed=42,
    )

    res = trainer.train_and_evaluate_series(commodity=comm, province=prov)
    expected_types = {
        "NAIVE",
        "SEASONAL_NAIVE",
        "MOVING_AVG",
        "PROPHET",
        "RANDOM_FOREST",
        "XGBOOST",
        "LSTM",
    }

    runs = (
        db_session.query(ModelRun)
        .filter_by(commodity_id=comm.id, province_id=prov.id)
        .all()
    )
    assert len(runs) == 7
    assert {r.model_type for r in runs} == expected_types

    selected_runs = [r for r in runs if r.is_selected]
    assert len(selected_runs) == 1
    assert selected_runs[0].id == res["selected_model_run_id"]

    for r in runs:
        assert r.train_start_date is not None
        assert r.train_end_date is not None
        assert r.test_start_date is not None
        assert r.test_end_date is not None
        assert r.train_end_date < r.test_start_date
        assert r.train_record_count == 175
        assert r.mae is not None and r.mae >= 0
        assert r.rmse is not None and r.rmse >= 0
        assert r.mape is not None and r.mape >= 0
        assert r.artifact_path is not None and os.path.exists(r.artifact_path)
        assert os.path.getsize(r.artifact_path) > 0


def test_selected_model_beats_baseline(db_session: Session, tmp_path):
    """
    Kiểm chứng Tiêu chí nghiệm thu số 3 (Mục 9 SRS):
    Mô hình được chọn (is_selected = True) phải có sai số MAPE và RMSE thấp hơn mô hình NAIVE baseline.
    """
    comm = db_session.query(Commodity).filter(Commodity.code == "TIEU_DEN").first()
    prov = db_session.query(Province).filter(Province.code == "DL").first()
    _seed_synthetic_feature_series_in_db(
        db_session, comm.id, prov.id, commodity_code="TIEU_DEN", n_days=240
    )

    trainer = ModelTrainer(
        db=db_session,
        artifacts_dir=str(tmp_path / "artifacts_beat"),
        test_days=45,
        max_horizon=30,
        eval_stride=10,
        min_training_days=100,
        min_records_for_lstm=100,
        lstm_epochs=8,
        seed=42,
    )
    res = trainer.train_and_evaluate_series(commodity=comm, province=prov)

    models_by_type = {m["model_type"]: m for m in res["models"]}
    naive_metrics = models_by_type["NAIVE"]
    selected_type = res["selected_model_type"]
    selected_metrics = models_by_type[selected_type]

    assert selected_type != "NAIVE"
    assert selected_metrics["mape"] < naive_metrics["mape"], (
        f"Mô hình được chọn ({selected_type}: MAPE={selected_metrics['mape']}%) "
        f"không vượt qua NAIVE baseline (MAPE={naive_metrics['mape']}%)"
    )
    assert selected_metrics["rmse"] < naive_metrics["rmse"]


def test_future_forecast_and_backtesting_records(db_session: Session, tmp_path):
    """
    Kiểm tra:
    1. Sinh đủ 30 ngày dự báo tương lai (h = 1..30 sau max_date) với actual_price IS NULL
       và lower_bound <= yhat <= upper_bound (FR-17, FR-43).
    2. Sinh đủ 30 ngày Backtesting trong quá khứ (<= max_date) với actual_price IS NOT NULL (FR-44).
    """
    comm = db_session.query(Commodity).filter(Commodity.code == "LUA_IR50404").first()
    prov = db_session.query(Province).filter(Province.code == "AG").first()
    feat_df = _seed_synthetic_feature_series_in_db(
        db_session, comm.id, prov.id, commodity_code="LUA_IR50404", n_days=200
    )
    max_obs_date = feat_df["obs_date"].max()

    trainer = ModelTrainer(
        db=db_session,
        artifacts_dir=str(tmp_path / "artifacts_fc"),
        test_days=40,
        max_horizon=30,
        eval_stride=10,
        min_training_days=100,
        min_records_for_lstm=100,
        lstm_epochs=6,
        seed=42,
    )
    trainer.train_and_evaluate_series(commodity=comm, province=prov)

    predictor = ForecastPredictor(db=db_session, horizon=30)
    bt_res = predictor.run_historical_backtesting(
        commodity_id=comm.id,
        province_id=prov.id,
        backtest_days=30,
    )
    assert bt_res["backtest_records_saved"] == 30

    future_fcs = predictor.generate_future_forecasts(
        commodity_id=comm.id,
        province_id=prov.id,
        horizon=30,
    )
    assert len(future_fcs) == 30

    # Kiểm tra các bản ghi tương lai (> max_obs_date)
    db_future = (
        db_session.query(Forecast)
        .filter(
            Forecast.commodity_id == comm.id,
            Forecast.province_id == prov.id,
            Forecast.target_date > max_obs_date,
        )
        .order_by(Forecast.horizon.asc())
        .all()
    )
    assert len(db_future) == 30
    assert [f.horizon for f in db_future] == list(range(1, 31))
    for f in db_future:
        assert f.actual_price is None
        assert f.lower_bound is not None and f.upper_bound is not None
        assert f.lower_bound <= f.yhat <= f.upper_bound

    # Kiểm tra các bản ghi Backtesting (<= max_obs_date)
    db_backtest = (
        db_session.query(Forecast)
        .filter(
            Forecast.commodity_id == comm.id,
            Forecast.province_id == prov.id,
            Forecast.target_date <= max_obs_date,
        )
        .order_by(Forecast.target_date.asc())
        .all()
    )
    assert len(db_backtest) == 30
    for bf in db_backtest:
        assert bf.actual_price is not None
        assert bf.yhat is not None
        assert bf.lower_bound <= bf.yhat <= bf.upper_bound

