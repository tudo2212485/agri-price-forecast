"""Exploratory Data Analysis (EDA) & Thesis Report Visualization Generator (FR-10).

Tự động phân tích dữ liệu chuỗi thời gian trong bảng feature_set và xuất:
1. docs/eda_figures/trend_and_seasonality.png (150 DPI): Xu hướng giá 2023-2026 & vùng mùa vụ thu hoạch.
2. docs/eda_figures/seasonal_decomposition.png (150 DPI): Phân rã chuỗi thời gian (Observed, Trend, Seasonal, Residual)
   bằng statsmodels.tsa.seasonal.seasonal_decompose.
3. docs/eda_figures/acf_pacf_plots.png (150 DPI): Đồ thị tự tương quan ACF & PACF chứng minh cơ sở chọn lag_1, lag_7, lag_14, lag_30.
4. docs/eda_figures/weather_correlation_heatmap.png (150 DPI): Ma trận tương quan giữa Giá nông sản và Biến ngoại sinh Thời tiết.
5. docs/eda_summary.json: Thống kê mô tả, hệ số tự tương quan và đường dẫn biểu đồ phục vụ báo cáo ĐATN.
"""

import json
import os
from typing import Dict, Any, List, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from sqlalchemy.orm import Session
from statsmodels.tsa.seasonal import seasonal_decompose
from statsmodels.tsa.stattools import acf, pacf

from db.models import FeatureSet, Commodity, Province

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_FIGURES_DIR = os.path.join(BASE_DIR, "docs", "eda_figures")
DEFAULT_SUMMARY_JSON_PATH = os.path.join(BASE_DIR, "docs", "eda_summary.json")


def _load_feature_dataframe(db: Session) -> pd.DataFrame:
    """Đọc toàn bộ dữ liệu từ bảng feature_set kèm mã nông sản và mã tỉnh."""
    commodities = {c.id: (c.code, c.name) for c in db.query(Commodity).all()}
    provinces = {p.id: (p.code, p.standard_name) for p in db.query(Province).all()}

    rows = db.query(FeatureSet).order_by(FeatureSet.obs_date.asc()).all()
    if not rows:
        return pd.DataFrame()

    data = []
    for r in rows:
        c_code, c_name = commodities.get(r.commodity_id, (str(r.commodity_id), ""))
        p_code, p_name = provinces.get(r.province_id, (str(r.province_id), ""))
        data.append({
            "obs_date": pd.Timestamp(r.obs_date),
            "commodity_id": r.commodity_id,
            "commodity_code": c_code,
            "commodity_name": c_name,
            "province_id": r.province_id,
            "province_code": p_code,
            "province_name": p_name,
            "price": r.price,
            "lag_1": r.lag_1,
            "lag_7": r.lag_7,
            "lag_14": r.lag_14,
            "lag_30": r.lag_30,
            "rolling_mean_7": r.rolling_mean_7,
            "rolling_mean_30": r.rolling_mean_30,
            "temp_max": r.temp_max,
            "temp_min": r.temp_min,
            "temp_mean": r.temp_mean,
            "temp_mean_7d": r.temp_mean_7d,
            "precipitation": r.precipitation,
            "precip_sum_7d": r.precip_sum_7d,
            "precip_sum_30d": r.precip_sum_30d,
            "humidity": r.humidity,
            "is_harvest_season": r.is_harvest_season,
        })
    return pd.DataFrame(data)


def plot_trend_and_seasonality(df: pd.DataFrame, output_path: str) -> str:
    """1. Xuất biểu đồ diễn biến lịch sử giá & dải mùa vụ thu hoạch của 3 nông sản chủ lực."""
    fig, axes = plt.subplots(3, 1, figsize=(14, 11), sharex=True)
    sns.set_theme(style="whitegrid")

    configs = [
        ("CAFE_ROBUSTA", "Cà phê nhân xô Robusta (VNĐ/kg) - Tây Nguyên", "#1b5e20"),
        ("TIEU_DEN", "Hồ tiêu đen xô (VNĐ/kg) - Tây Nguyên & Đông Nam Bộ", "#b71c1c"),
        ("LUA_IR50404", "Lúa tươi IR50404 (VNĐ/kg) - Đồng bằng Sông Cửu Long", "#e65100"),
    ]

    for ax, (comm_code, title, base_color) in zip(axes, configs):
        sub = df[df["commodity_code"] == comm_code]
        if sub.empty:
            continue

        for p_name, grp in sub.groupby("province_name"):
            grp_sorted = grp.sort_values("obs_date")
            ax.plot(grp_sorted["obs_date"], grp_sorted["price"], label=p_name, linewidth=1.3, alpha=0.88)

        # Tô bóng dải mùa thu hoạch (is_harvest_season == True)
        rep_prov = sub["province_code"].iloc[0]
        rep_df = sub[sub["province_code"] == rep_prov].sort_values("obs_date")
        in_harvest = rep_df["is_harvest_season"].astype(bool).to_numpy()
        dates = rep_df["obs_date"].to_numpy()

        start_idx = None
        harvest_labeled = False
        for i, flag in enumerate(in_harvest):
            if flag and start_idx is None:
                start_idx = i
            elif not flag and start_idx is not None:
                ax.axvspan(
                    dates[start_idx],
                    dates[i - 1],
                    color="#fff59d",
                    alpha=0.35,
                    label="Mùa thu hoạch chính vụ" if not harvest_labeled else None,
                )
                harvest_labeled = True
                start_idx = None
        if start_idx is not None:
            ax.axvspan(
                dates[start_idx],
                dates[-1],
                color="#fff59d",
                alpha=0.35,
                label="Mùa thu hoạch chính vụ" if not harvest_labeled else None,
            )

        ax.set_title(title, fontsize=12, fontweight="bold", color=base_color)
        ax.set_ylabel("Giá (VNĐ/kg)", fontsize=10)
        ax.legend(loc="upper left", ncol=5, fontsize=9)
        ax.grid(True, linestyle="--", alpha=0.5)

    axes[-1].set_xlabel("Thời gian quan sát", fontsize=11)
    fig.suptitle(
        "DIỄN BIẾN XU HƯỚNG GIÁ NÔNG SẢN & CHU KỲ MÙA VỤ THU HOẠCH",
        fontsize=14,
        fontweight="bold",
        y=0.98,
    )
    plt.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    return output_path


def plot_seasonal_decomposition(df: pd.DataFrame, output_path: str) -> str:
    """2. Phân rã chuỗi thời gian (Observed, Trend, Seasonal, Residual) cho 3 chuỗi đại diện."""
    targets = [
        ("CAFE_ROBUSTA", "DL", "Cà phê Robusta - Đắk Lắk"),
        ("TIEU_DEN", "DL", "Hồ tiêu đen - Đắk Lắk"),
        ("LUA_IR50404", "AG", "Lúa IR50404 - An Giang"),
    ]

    fig, axes = plt.subplots(4, 3, figsize=(16, 11), sharex="col")
    row_titles = ["Chuỗi gốc (Observed)", "Xu hướng dài hạn (Trend)", "Mùa vụ (Seasonal)", "Phần dư (Residual)"]
    colors = ["#0d47a1", "#2e7d32", "#ef6c00", "#6a1b9a"]

    for col_idx, (c_code, p_code, label) in enumerate(targets):
        sub = df[(df["commodity_code"] == c_code) & (df["province_code"] == p_code)].sort_values("obs_date")
        if sub.empty:
            sub = df[df["commodity_code"] == c_code].sort_values("obs_date")
        if sub.empty:
            continue

        s = sub.set_index("obs_date")["price"].asfreq("D").ffill().bfill()
        period = min(365, max(7, len(s) // 2))
        decomp = seasonal_decompose(s, model="additive", period=period)

        components = [
            decomp.observed,
            decomp.trend.bfill().ffill(),
            decomp.seasonal,
            decomp.resid.fillna(0.0),
        ]
        for row_idx, comp in enumerate(components):
            ax = axes[row_idx, col_idx]
            ax.plot(comp.index, comp.values, color=colors[row_idx], linewidth=1.1)
            if row_idx == 0:
                ax.set_title(label, fontsize=11, fontweight="bold")
            if col_idx == 0:
                ax.set_ylabel(row_titles[row_idx], fontsize=9, fontweight="bold")
            ax.grid(True, linestyle=":", alpha=0.6)

    fig.suptitle(
        "PHÂN RÃ CHUỖI THỜI GIAN (SEASONAL DECOMPOSITION - STATSMODELS)",
        fontsize=14,
        fontweight="bold",
        y=0.98,
    )
    plt.tight_layout(rect=[0, 0, 1, 0.95])
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    return output_path


def plot_acf_pacf(df: pd.DataFrame, output_path: str) -> str:
    """3. Đồ thị Autocorrelation (ACF) và Partial Autocorrelation (PACF) chứng minh việc chọn Lag Features."""
    targets = [
        ("CAFE_ROBUSTA", "DL", "Cà phê Robusta (Đắk Lắk)"),
        ("TIEU_DEN", "DL", "Hồ tiêu đen (Đắk Lắk)"),
        ("LUA_IR50404", "AG", "Lúa IR50404 (An Giang)"),
    ]

    fig, axes = plt.subplots(3, 2, figsize=(14, 10))
    highlighted_lags = [1, 7, 14, 21, 30]

    for row_idx, (c_code, p_code, label) in enumerate(targets):
        sub = df[(df["commodity_code"] == c_code) & (df["province_code"] == p_code)].sort_values("obs_date")
        if sub.empty:
            sub = df[df["commodity_code"] == c_code].sort_values("obs_date")
        if sub.empty:
            continue

        prices = sub["price"].dropna().to_numpy(dtype=float)
        max_lags = min(35, max(5, len(prices) // 3 - 1))

        acf_vals = acf(prices, nlags=max_lags, fft=True)
        pacf_vals = pacf(prices, nlags=max_lags, method="ywm")
        lags = np.arange(len(acf_vals))
        conf_bound = 1.96 / np.sqrt(len(prices))

        # Cột trái: ACF
        ax_acf = axes[row_idx, 0]
        ax_acf.bar(lags, acf_vals, width=0.45, color="#1976d2", alpha=0.75, label="ACF")
        for hl in highlighted_lags:
            if hl <= max_lags:
                ax_acf.bar(hl, acf_vals[hl], width=0.55, color="#d32f2f")
        ax_acf.axhline(conf_bound, linestyle="--", color="gray", linewidth=0.9)
        ax_acf.axhline(-conf_bound, linestyle="--", color="gray", linewidth=0.9)
        ax_acf.axhline(0, color="black", linewidth=0.8)
        ax_acf.set_title(f"ACF - {label}", fontsize=10, fontweight="bold")
        ax_acf.set_xlabel("Độ trễ (Lag - Ngày)")
        ax_acf.set_ylabel("Hệ số ACF")

        # Cột phải: PACF
        ax_pacf = axes[row_idx, 1]
        ax_pacf.bar(lags, pacf_vals, width=0.45, color="#388e3c", alpha=0.75, label="PACF")
        for hl in highlighted_lags:
            if hl <= max_lags:
                ax_pacf.bar(hl, pacf_vals[hl], width=0.55, color="#d32f2f")
        ax_pacf.axhline(conf_bound, linestyle="--", color="gray", linewidth=0.9)
        ax_pacf.axhline(-conf_bound, linestyle="--", color="gray", linewidth=0.9)
        ax_pacf.axhline(0, color="black", linewidth=0.8)
        ax_pacf.set_title(f"PACF - {label}", fontsize=10, fontweight="bold")
        ax_pacf.set_xlabel("Độ trễ (Lag - Ngày)")
        ax_pacf.set_ylabel("Hệ số PACF")

    fig.suptitle(
        "PHÂN TÍCH TỰ TƯƠNG QUAN (ACF & PACF) - CƠ SỞ LỰA CHỌN ĐẶC TRƯNG TRỄ (LAG 1, 7, 14, 21, 30)",
        fontsize=13,
        fontweight="bold",
        y=0.98,
    )
    plt.tight_layout(rect=[0, 0, 1, 0.95])
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    return output_path


def plot_weather_correlation_heatmap(df: pd.DataFrame, output_path: str) -> str:
    """4. Heatmap tương quan giữa Giá nông sản, Đặc trưng Trễ và Biến ngoại sinh Thời tiết."""
    commodities = ["CAFE_ROBUSTA", "TIEU_DEN", "LUA_IR50404"]
    titles = [
        "Cà phê Robusta (Tây Nguyên)",
        "Hồ tiêu đen (Tây Nguyên & ĐNB)",
        "Lúa IR50404 (ĐBSCL)",
    ]
    corr_cols = [
        "price",
        "lag_7",
        "rolling_mean_30",
        "temp_max",
        "temp_mean_7d",
        "precip_sum_7d",
        "precip_sum_30d",
        "humidity",
    ]
    col_labels = [
        "Giá (t)",
        "Giá trễ 7d",
        "TB trượt 30d",
        "Nhiệt độ Max",
        "Nhiệt độ TB 7d",
        "Mưa tích lũy 7d",
        "Mưa tích lũy 30d",
        "Độ ẩm (%)",
    ]

    fig, axes = plt.subplots(1, 3, figsize=(18, 6))

    for ax, c_code, title in zip(axes, commodities, titles):
        sub = df[df["commodity_code"] == c_code][corr_cols].dropna(how="all")
        if sub.empty:
            continue
        corr_matrix = sub.corr().fillna(0.0)
        corr_matrix.index = col_labels
        corr_matrix.columns = col_labels

        sns.heatmap(
            corr_matrix,
            ax=ax,
            annot=True,
            fmt=".2f",
            cmap="RdYlBu_r",
            vmin=-1.0,
            vmax=1.0,
            cbar=False,
             annot_kws={"size": 8},
        )
        ax.set_title(title, fontsize=11, fontweight="bold")
        ax.tick_params(axis="x", rotation=40)
        ax.tick_params(axis="y", rotation=0)

    fig.suptitle(
        "MA TRẬN TƯƠNG QUAN GIỮA GIÁ NÔNG SẢN, BIẾN TRỄ & BIẾN NGOẠI SINH THỜI TIẾT",
        fontsize=14,
        fontweight="bold",
        y=0.99,
    )
    plt.tight_layout(rect=[0, 0, 1, 0.94])
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    return output_path


def run_exploratory_data_analysis(
    db: Session,
    figures_dir: str = DEFAULT_FIGURES_DIR,
    summary_json_path: str = DEFAULT_SUMMARY_JSON_PATH,
) -> Dict[str, Any]:
    """
    Thực thi toàn bộ phân tích khám phá dữ liệu (EDA - FR-10),
    lưu 4 biểu đồ PNG 150 DPI vào docs/eda_figures/ và xuất file docs/eda_summary.json.
    """
    os.makedirs(figures_dir, exist_ok=True)
    os.makedirs(os.path.dirname(summary_json_path), exist_ok=True)

    df = _load_feature_dataframe(db)
    if df.empty:
        raise ValueError("Bảng feature_set đang trống. Hãy chạy FeatureEngineer trước khi chạy EDA.")

    fig1_path = os.path.join(figures_dir, "trend_and_seasonality.png")
    fig2_path = os.path.join(figures_dir, "seasonal_decomposition.png")
    fig3_path = os.path.join(figures_dir, "acf_pacf_plots.png")
    fig4_path = os.path.join(figures_dir, "weather_correlation_heatmap.png")

    plot_trend_and_seasonality(df, fig1_path)
    plot_seasonal_decomposition(df, fig2_path)
    plot_acf_pacf(df, fig3_path)
    plot_weather_correlation_heatmap(df, fig4_path)

    # Tính thống kê mô tả và hệ số tự tương quan theo từng chuỗi
    series_summary: List[Dict[str, Any]] = []
    for (c_code, p_code), grp in df.groupby(["commodity_code", "province_code"]):
        grp_sorted = grp.sort_values("obs_date")
        prices = grp_sorted["price"].dropna().to_numpy(dtype=float)
        if len(prices) == 0:
            continue

        max_lag = min(30, len(prices) - 1)
        acf_vals = acf(prices, nlags=max_lag, fft=True) if max_lag >= 1 else [1.0]

        def _safe_acf(lag_idx: int) -> Optional[float]:
            if lag_idx < len(acf_vals):
                return round(float(acf_vals[lag_idx]), 4)
            return None

        # Tương quan với lượng mưa 30 ngày và nhiệt độ 7 ngày
        corr_precip_30d = 0.0
        if grp_sorted["precip_sum_30d"].notna().sum() > 5:
            c_val = grp_sorted["price"].corr(grp_sorted["precip_sum_30d"])
            corr_precip_30d = round(float(c_val), 4) if not pd.isna(c_val) else 0.0

        corr_temp_7d = 0.0
        if grp_sorted["temp_mean_7d"].notna().sum() > 5:
            t_val = grp_sorted["price"].corr(grp_sorted["temp_mean_7d"])
            corr_temp_7d = round(float(t_val), 4) if not pd.isna(t_val) else 0.0

        series_summary.append({
            "commodity_code": c_code,
            "province_code": p_code,
            "province_name": grp_sorted["province_name"].iloc[0],
            "count": int(len(prices)),
            "min_date": grp_sorted["obs_date"].min().strftime("%Y-%m-%d"),
            "max_date": grp_sorted["obs_date"].max().strftime("%Y-%m-%d"),
            "mean_price": round(float(np.mean(prices)), 2),
            "std_price": round(float(np.std(prices)), 2),
            "min_price": round(float(np.min(prices)), 2),
            "median_price": round(float(np.median(prices)), 2),
            "max_price": round(float(np.max(prices)), 2),
            "acf_lag_1": _safe_acf(1),
            "acf_lag_7": _safe_acf(7),
            "acf_lag_14": _safe_acf(14),
            "acf_lag_30": _safe_acf(30),
            "corr_price_precip_30d": corr_precip_30d,
            "corr_price_temp_7d": corr_temp_7d,
        })

    summary_payload = {
        "total_feature_records": int(len(df)),
        "total_series_analyzed": len(series_summary),
        "figures_generated": {
            "trend_and_seasonality": fig1_path,
            "seasonal_decomposition": fig2_path,
            "acf_pacf_plots": fig3_path,
            "weather_correlation_heatmap": fig4_path,
        },
        "series_statistics": series_summary,
    }

    with open(summary_json_path, mode="w", encoding="utf-8") as f:
        json.dump(summary_payload, f, ensure_ascii=False, indent=2)

    return summary_payload

