"""Model Evaluation, Reproducibility Seed Control, TimeSeriesSplit & Residual Analysis.

Tuân thủ chặt chẽ SRS v1.1:
- NFR-03: Cố định toàn bộ random seed (Python random, NumPy, PyTorch) qua set_global_seed(seed=42).
- NFR-04 & FR-15: Chia dữ liệu theo thứ tự thời gian nghiêm ngặt (shuffle=False),
  đánh giá Rolling-Origin trên các chân trời dự báo h = 1..30 (báo cáo chi tiết h=7, 14, 30).
- FR-15 & Mục 10: Tính MAE, RMSE, MAPE thống nhất và phân tích sai số (analyze_residuals)
  theo mùa vụ thu hoạch vs ngoài mùa vụ và giai đoạn biến động mạnh.
"""

import os
import random
from typing import Dict, Any, List, Tuple, Optional

import numpy as np
import pandas as pd
import torch


def set_global_seed(seed: int = 42) -> None:
    """
    Cố định toàn bộ hạt giống ngẫu nhiên (Random Seed) để đảm bảo kết quả huấn luyện
    và đánh giá tái lập 100% (Reproducibility - NFR-03).
    """
    os.environ["PYTHONHASHSEED"] = str(seed)
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
    if hasattr(torch.backends, "cudnn"):
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False


def compute_mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Mean Absolute Error (MAE)."""
    y_t = np.asarray(y_true, dtype=float)
    y_p = np.asarray(y_pred, dtype=float)
    mask = ~(np.isnan(y_t) | np.isnan(y_p))
    if not np.any(mask):
        return 0.0
    return float(np.mean(np.abs(y_t[mask] - y_p[mask])))


def compute_rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Root Mean Squared Error (RMSE)."""
    y_t = np.asarray(y_true, dtype=float)
    y_p = np.asarray(y_pred, dtype=float)
    mask = ~(np.isnan(y_t) | np.isnan(y_p))
    if not np.any(mask):
        return 0.0
    return float(np.sqrt(np.mean(np.square(y_t[mask] - y_p[mask]))))


def compute_mape(y_true: np.ndarray, y_pred: np.ndarray, epsilon: float = 1e-8) -> float:
    """
    Mean Absolute Percentage Error (MAPE - đơn vị %).
    Xử lý an toàn trường hợp mẫu số gần bằng 0 bằng ngưỡng epsilon.
    """
    y_t = np.asarray(y_true, dtype=float)
    y_p = np.asarray(y_pred, dtype=float)
    mask = ~(np.isnan(y_t) | np.isnan(y_p))
    if not np.any(mask):
        return 0.0
    denom = np.maximum(np.abs(y_t[mask]), epsilon)
    return float(np.mean(np.abs(y_t[mask] - y_p[mask]) / denom) * 100.0)


def compute_all_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> Dict[str, float]:
    """Tính đồng thời bộ 3 chỉ số chuẩn MAE, RMSE, MAPE (%)."""
    return {
        "mae": round(compute_mae(y_true, y_pred), 4),
        "rmse": round(compute_rmse(y_true, y_pred), 4),
        "mape": round(compute_mape(y_true, y_pred), 4),
    }


def temporal_train_test_split(
    df: pd.DataFrame,
    test_days: int = 90,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Chia dữ liệu chuỗi thời gian thành tập Train và tập Test theo đúng thứ tự thời gian (FR-15, NFR-04).
    Tuyệt đối không xáo trộn dữ liệu (shuffle=False).
    Mọi ngày trong tập Train đều nhỏ hơn nghiêm ngặt mọi ngày trong tập Test.
    """
    if df.empty:
        raise ValueError("DataFrame đầu vào rỗng, không thể chia Train/Test.")

    sorted_df = df.sort_values("obs_date", ascending=True).reset_index(drop=True)
    n_total = len(sorted_df)
    if n_total <= test_days + 30:
        # Tự động co tỷ lệ test_days nếu chuỗi ngắn trong Unit Test
        effective_test_days = max(7, n_total // 4)
    else:
        effective_test_days = test_days

    split_idx = n_total - effective_test_days
    train_df = sorted_df.iloc[:split_idx].copy().reset_index(drop=True)
    test_df = sorted_df.iloc[split_idx:].copy().reset_index(drop=True)

    # Kiểm chứng bất biến thời gian (Temporal Invariant): max(train.obs_date) < min(test.obs_date)
    assert pd.to_datetime(train_df["obs_date"]).max() < pd.to_datetime(test_df["obs_date"]).min(), (
        "Vi phạm NFR-04: Phát hiện chồng lấn thời gian giữa tập Train và tập Test!"
    )
    return train_df, test_df


def evaluate_forecaster_rolling_origin(
    forecaster: Any,
    full_df: pd.DataFrame,
    train_end_idx: int,
    max_horizon: int = 30,
    stride: int = 5,
) -> Dict[str, Any]:
    """
    Đánh giá mô hình theo phương pháp Rolling-Origin (Walk-Forward Validation - FR-15)
    trên tập kiểm tra bắt đầu từ `train_end_idx`:
    - Tại mỗi điểm gốc đánh giá t_origin, mô hình chỉ được cung cấp lịch sử `full_df.iloc[:t_origin]`
      và dự báo cho `max_horizon` ngày tiếp theo.
    - Tổng hợp sai số MAE, RMSE, MAPE trên toàn bộ dải 1..30 ngày và tại các mốc h = 7, 14, 30.
    """
    sorted_df = full_df.sort_values("obs_date", ascending=True).reset_index(drop=True)
    n_total = len(sorted_df)
    effective_horizon = min(max_horizon, n_total - train_end_idx)
    if effective_horizon < 1:
        raise ValueError("Không đủ dữ liệu kiểm tra để đánh giá Rolling-Origin.")

    all_y_true: List[float] = []
    all_y_pred: List[float] = []
    horizon_errors: Dict[int, Tuple[List[float], List[float]]] = {
        h: ([], []) for h in range(1, effective_horizon + 1)
    }
    residual_records: List[Dict[str, Any]] = []

    # Các điểm gốc đánh giá (rolling origins) trên miền kiểm tra
    last_possible_origin = max(train_end_idx, n_total - effective_horizon)
    origins = list(range(train_end_idx, last_possible_origin + 1, max(1, stride)))
    if not origins:
        origins = [train_end_idx]

    for origin_idx in origins:
        history_slice = sorted_df.iloc[:origin_idx].copy()
        actual_future_slice = sorted_df.iloc[origin_idx : origin_idx + effective_horizon].copy()
        actual_len = len(actual_future_slice)
        if actual_len == 0:
            continue

        preds_df = forecaster.predict(history_df=history_slice, horizon=actual_len)
        y_true_arr = actual_future_slice["price"].to_numpy(dtype=float)
        y_pred_arr = preds_df["yhat"].to_numpy(dtype=float)[:actual_len]

        all_y_true.extend(y_true_arr.tolist())
        all_y_pred.extend(y_pred_arr.tolist())

        for step_idx in range(actual_len):
            h = step_idx + 1
            yt = float(y_true_arr[step_idx])
            yp = float(y_pred_arr[step_idx])
            horizon_errors[h][0].append(yt)
            horizon_errors[h][1].append(yp)

            row_meta = actual_future_slice.iloc[step_idx]
            residual_records.append({
                "obs_date": row_meta["obs_date"],
                "horizon": h,
                "y_true": yt,
                "y_pred": yp,
                "residual": yt - yp,
                "abs_pct_error": abs(yt - yp) / max(abs(yt), 1e-8) * 100.0,
                "is_harvest_season": bool(row_meta.get("is_harvest_season", False)),
                "pct_change_7d": float(row_meta.get("pct_change_7d", 0.0) or 0.0),
            })

    overall_metrics = compute_all_metrics(np.array(all_y_true), np.array(all_y_pred))

    by_horizon: Dict[str, Dict[str, float]] = {}
    for target_h in (1, 7, 14, 30):
        if target_h in horizon_errors and horizon_errors[target_h][0]:
            by_horizon[f"h_{target_h}"] = compute_all_metrics(
                np.array(horizon_errors[target_h][0]),
                np.array(horizon_errors[target_h][1]),
            )

    return {
        "mae": overall_metrics["mae"],
        "rmse": overall_metrics["rmse"],
        "mape": overall_metrics["mape"],
        "horizon_metrics": by_horizon,
        "residual_analysis": analyze_residuals(residual_records),
    }


def analyze_residuals(residual_records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Phân tích sai số dự báo theo mùa vụ thu hoạch vs ngoài mùa vụ
    và giai đoạn thị trường biến động mạnh (FR-15, Mục 10 SRS).
    """
    if not residual_records:
        return {
            "total_evaluated_points": 0,
            "harvest_season_mape": 0.0,
            "off_harvest_season_mape": 0.0,
            "high_volatility_mape": 0.0,
            "normal_volatility_mape": 0.0,
            "mean_bias": 0.0,
        }

    df_res = pd.DataFrame(residual_records)
    harvest_df = df_res[df_res["is_harvest_season"] == True]
    off_harvest_df = df_res[df_res["is_harvest_season"] == False]

    # Biến động mạnh khi |pct_change_7d| >= 2.0%
    high_vol_df = df_res[df_res["pct_change_7d"].abs() >= 2.0]
    norm_vol_df = df_res[df_res["pct_change_7d"].abs() < 2.0]

    return {
        "total_evaluated_points": int(len(df_res)),
        "mean_bias": round(float(df_res["residual"].mean()), 4),
        "p90_abs_pct_error": round(float(np.percentile(df_res["abs_pct_error"], 90)), 4),
        "harvest_season_mape": round(float(harvest_df["abs_pct_error"].mean()), 4) if not harvest_df.empty else 0.0,
        "off_harvest_season_mape": round(float(off_harvest_df["abs_pct_error"].mean()), 4) if not off_harvest_df.empty else 0.0,
        "high_volatility_mape": round(float(high_vol_df["abs_pct_error"].mean()), 4) if not high_vol_df.empty else 0.0,
        "normal_volatility_mape": round(float(norm_vol_df["abs_pct_error"].mean()), 4) if not norm_vol_df.empty else 0.0,
    }

