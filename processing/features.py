"""Feature Engineering Pipeline with Strict Anti-Data-Leakage Guarantees (FR-09, NFR-04).

Xây dựng bộ đặc trưng chuỗi thời gian cho từng cặp (commodity_id, province_id):
1. Lag Features: lag_1, lag_2, lag_3, lag_7, lag_14, lag_21, lag_30.
2. Past-Only Rolling Statistics (center=False): rolling_mean_7/14/30, rolling_std_7/14/30, pct_change_1d/7d.
3. Cumulative Weather Features: precip_sum_7d, precip_sum_30d, temp_mean_7d.
4. Calendar & Trigonometric Seasonality: day_of_week, day_of_month, month, quarter, day_of_year,
   sin_day_of_year, cos_day_of_year, is_harvest_season (theo lịch mùa vụ thực tế tại Việt Nam).
5. Idempotent Upsert vào bảng feature_set và ghi log vào pipeline_log (FR-05).
"""

from datetime import date
from typing import Optional, Dict, Any, List

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from collector.base import BaseCollector
from collector.price_collector import TARGET_COMMODITY_PROVINCES
from db.database import get_vietnam_now
from db.models import FeatureSet, Commodity, Province
from processing.cleaner import TimeSeriesCleaner

# Lịch thu hoạch thực tế theo tháng của từng nông sản chủ lực tại Việt Nam (FR-09)
HARVEST_MONTHS_BY_COMMODITY: Dict[str, List[int]] = {
    "CAFE_ROBUSTA": [10, 11, 12, 1],          # Vụ thu hoạch cà phê Tây Nguyên: Tháng 10 -> Tháng 1 năm sau
    "TIEU_DEN": [2, 3, 4],                    # Vụ thu hoạch hồ tiêu chính vụ: Tháng 2 -> Tháng 4
    "LUA_IR50404": [2, 3, 4, 7, 8, 9],        # Vụ Đông Xuân (T2-T4) và Hè Thu (T7-T9) tại ĐBSCL
}

FEATURE_COLUMNS: List[str] = [
    "lag_1", "lag_2", "lag_3", "lag_7", "lag_14", "lag_21", "lag_30",
    "rolling_mean_7", "rolling_std_7",
    "rolling_mean_14", "rolling_std_14",
    "rolling_mean_30", "rolling_std_30",
    "pct_change_1d", "pct_change_7d",
    "temp_max", "temp_min", "temp_mean", "precipitation", "humidity",
    "precip_sum_7d", "precip_sum_30d", "temp_mean_7d",
    "day_of_week", "day_of_month", "month", "quarter", "day_of_year",
    "sin_day_of_year", "cos_day_of_year", "is_harvest_season",
]


def _to_nullable_float(val: Any) -> Optional[float]:
    if val is None or pd.isna(val):
        return None
    f_val = float(val)
    if np.isnan(f_val) or np.isinf(f_val):
        return None
    return f_val


class FeatureEngineer:
    """
    Bộ tạo đặc trưng chuỗi thời gian đảm bảo 100% không rò rỉ dữ liệu tương lai (Zero Data Leakage - NFR-04).
    Mọi phép biến đổi tại thời điểm t chỉ sử dụng các quan sát tại thời điểm <= t.
    """

    def __init__(self, db: Optional[Session] = None):
        self.db = db
        self._collector_helper = BaseCollector(db=db, rate_limit_delay=0.0) if db is not None else None

    @staticmethod
    def compute_features_from_dataframe(
        df: pd.DataFrame,
        commodity_code: str = "CAFE_ROBUSTA",
    ) -> pd.DataFrame:
        """
        Tính toán đầy đủ các đặc trưng Lag, Rolling, Thời tiết tích lũy và Mùa vụ từ DataFrame đã làm sạch.
        Nghiêm cấm sử dụng center=True hoặc bfill() để đảm bảo tính nhân quả thời gian (NFR-04).
        """
        if df.empty:
            return df.copy()

        out = df.copy()
        out["obs_date_dt"] = pd.to_datetime(out["obs_date"])
        out = out.sort_values("obs_date_dt", ascending=True).reset_index(drop=True)

        # Đảm bảo các cột thời tiết tồn tại ngay cả khi truyền vào DataFrame chỉ có giá (phục vụ Unit Test)
        for w_col in ["temp_max", "temp_min", "temp_mean", "precipitation", "humidity"]:
            if w_col not in out.columns:
                out[w_col] = np.nan

        price_s = out["price"].astype(float)

        # 1. Đặc trưng trễ (Lag Features: k > 0)
        for lag_k in (1, 2, 3, 7, 14, 21, 30):
            out[f"lag_{lag_k}"] = price_s.shift(lag_k)

        # 2. Đặc trưng trượt quá khứ (Rolling Statistics - tuyệt đối center=False)
        for win in (7, 14, 30):
            out[f"rolling_mean_{win}"] = price_s.rolling(window=win, min_periods=1, center=False).mean()
            # std với ddof=0 hoặc fillna(0.0) cho điểm đầu tiên để không bị mất dòng dữ liệu
            out[f"rolling_std_{win}"] = (
                price_s.rolling(window=win, min_periods=1, center=False).std(ddof=0).fillna(0.0)
            )

        # 3. Biến động phần trăm quá khứ (Percentage Changes)
        out["pct_change_1d"] = np.where(
            out["lag_1"].notna() & (out["lag_1"] != 0),
            (price_s - out["lag_1"]) / out["lag_1"] * 100.0,
            0.0,
        )
        out["pct_change_7d"] = np.where(
            out["lag_7"].notna() & (out["lag_7"] != 0),
            (price_s - out["lag_7"]) / out["lag_7"] * 100.0,
            0.0,
        )
        # Nếu price hiện tại là NaN (khoảng trống dài > 3 ngày) thì các đặc trưng rolling/pct_change tại đúng ngày NaN để NaN
        na_price_mask = price_s.isna()
        if na_price_mask.any():
            for col in [
                "rolling_mean_7", "rolling_std_7",
                "rolling_mean_14", "rolling_std_14",
                "rolling_mean_30", "rolling_std_30",
                "pct_change_1d", "pct_change_7d",
            ]:
                out.loc[na_price_mask, col] = np.nan

        # 4. Đặc trưng Thời tiết tích lũy (Cumulative Weather Features)
        precip_s = out["precipitation"].astype(float)
        temp_s = out["temp_mean"].astype(float)
        out["precip_sum_7d"] = precip_s.rolling(window=7, min_periods=1, center=False).sum()
        out["precip_sum_30d"] = precip_s.rolling(window=30, min_periods=1, center=False).sum()
        out["temp_mean_7d"] = temp_s.rolling(window=7, min_periods=1, center=False).mean()

        # 5. Đặc trưng Lịch & Mùa vụ (Calendar & Trigonometric Seasonality)
        dt_col = out["obs_date_dt"]
        out["day_of_week"] = dt_col.dt.dayofweek.astype(int)
        out["day_of_month"] = dt_col.dt.day.astype(int)
        out["month"] = dt_col.dt.month.astype(int)
        out["quarter"] = dt_col.dt.quarter.astype(int)
        out["day_of_year"] = dt_col.dt.dayofyear.astype(int)

        out["sin_day_of_year"] = np.sin(2.0 * np.pi * out["day_of_year"] / 365.25)
        out["cos_day_of_year"] = np.cos(2.0 * np.pi * out["day_of_year"] / 365.25)

        harvest_months = HARVEST_MONTHS_BY_COMMODITY.get(commodity_code, [10, 11, 12, 1])
        out["is_harvest_season"] = out["month"].isin(harvest_months).astype(bool)

        out["obs_date"] = dt_col.dt.date
        out = out.drop(columns=["obs_date_dt"])
        return out

    def upsert_feature_dataframe(
        self,
        df_features: pd.DataFrame,
        batch_size: int = 500,
    ) -> int:
        """
        Lưu (Idempotent Upsert) các bản ghi từ DataFrame đặc trưng vào bảng feature_set.
        Bỏ qua các dòng có price là NaN (khoảng trống dài > 3 ngày không nội suy theo FR-36).
        """
        if self.db is None or df_features.empty:
            return 0

        valid_df = df_features[df_features["price"].notna()].copy()
        if valid_df.empty:
            return 0

        dialect_name = self.db.bind.dialect.name if self.db.bind is not None else "postgresql"
        insert_fn = sqlite_insert if dialect_name == "sqlite" else pg_insert
        now = get_vietnam_now()

        records: List[Dict[str, Any]] = []
        for _, row in valid_df.iterrows():
            obs_dt = row["obs_date"]
            if isinstance(obs_dt, pd.Timestamp):
                obs_dt = obs_dt.date()

            records.append({
                "obs_date": obs_dt,
                "commodity_id": int(row["commodity_id"]),
                "province_id": int(row["province_id"]),
                "price": float(row["price"]),
                "is_interpolated": bool(row.get("is_interpolated", False)),
                "quality_flag": str(row.get("quality_flag", "OK")),
                "temp_max": _to_nullable_float(row.get("temp_max")),
                "temp_min": _to_nullable_float(row.get("temp_min")),
                "temp_mean": _to_nullable_float(row.get("temp_mean")),
                "precipitation": _to_nullable_float(row.get("precipitation")),
                "humidity": _to_nullable_float(row.get("humidity")),
                "precip_sum_7d": _to_nullable_float(row.get("precip_sum_7d")),
                "precip_sum_30d": _to_nullable_float(row.get("precip_sum_30d")),
                "temp_mean_7d": _to_nullable_float(row.get("temp_mean_7d")),
                "lag_1": _to_nullable_float(row.get("lag_1")),
                "lag_2": _to_nullable_float(row.get("lag_2")),
                "lag_3": _to_nullable_float(row.get("lag_3")),
                "lag_7": _to_nullable_float(row.get("lag_7")),
                "lag_14": _to_nullable_float(row.get("lag_14")),
                "lag_21": _to_nullable_float(row.get("lag_21")),
                "lag_30": _to_nullable_float(row.get("lag_30")),
                "rolling_mean_7": _to_nullable_float(row.get("rolling_mean_7")),
                "rolling_std_7": _to_nullable_float(row.get("rolling_std_7")),
                "rolling_mean_14": _to_nullable_float(row.get("rolling_mean_14")),
                "rolling_std_14": _to_nullable_float(row.get("rolling_std_14")),
                "rolling_mean_30": _to_nullable_float(row.get("rolling_mean_30")),
                "rolling_std_30": _to_nullable_float(row.get("rolling_std_30")),
                "pct_change_1d": _to_nullable_float(row.get("pct_change_1d")),
                "pct_change_7d": _to_nullable_float(row.get("pct_change_7d")),
                "day_of_week": int(row["day_of_week"]),
                "day_of_month": int(row["day_of_month"]),
                "month": int(row["month"]),
                "quarter": int(row["quarter"]),
                "day_of_year": int(row["day_of_year"]),
                "sin_day_of_year": float(row["sin_day_of_year"]),
                "cos_day_of_year": float(row["cos_day_of_year"]),
                "is_harvest_season": bool(row["is_harvest_season"]),
                "updated_at": now,
            })

        update_cols = [
            "price", "is_interpolated", "quality_flag",
            "temp_max", "temp_min", "temp_mean", "precipitation", "humidity",
            "precip_sum_7d", "precip_sum_30d", "temp_mean_7d",
            "lag_1", "lag_2", "lag_3", "lag_7", "lag_14", "lag_21", "lag_30",
            "rolling_mean_7", "rolling_std_7",
            "rolling_mean_14", "rolling_std_14",
            "rolling_mean_30", "rolling_std_30",
            "pct_change_1d", "pct_change_7d",
            "day_of_week", "day_of_month", "month", "quarter", "day_of_year",
            "sin_day_of_year", "cos_day_of_year", "is_harvest_season", "updated_at",
        ]

        total_saved = 0
        for i in range(0, len(records), batch_size):
            batch = records[i : i + batch_size]
            stmt = insert_fn(FeatureSet).values(batch)
            stmt = stmt.on_conflict_do_update(
                index_elements=["obs_date", "commodity_id", "province_id"],
                set_={col: getattr(stmt.excluded, col) for col in update_cols},
            )
            self.db.execute(stmt)
            total_saved += len(batch)

        self.db.commit()
        return total_saved

    def build_and_save_all_series(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> Dict[str, Any]:
        """
        Thực thi toàn bộ luồng Làm sạch -> Nội suy -> Hợp nhất Thời tiết -> Tạo Đặc trưng -> Lưu vào feature_set
        cho tất cả 11 chuỗi (nông sản, tỉnh) và ghi log vào pipeline_log (FR-05).
        """
        if self.db is None or self._collector_helper is None:
            raise ValueError("Cần cung cấp DB session để lưu feature_set.")

        cleaner = TimeSeriesCleaner(db=self.db)
        commodities = {c.code: c for c in self.db.query(Commodity).all()}
        provinces = {p.code: p for p in self.db.query(Province).all()}

        series_stats: List[Dict[str, Any]] = []
        total_rows_upserted = 0
        total_interpolated_points = 0

        with self._collector_helper.log_pipeline_run(task_name="phase3_feature_engineering_all") as tracker:
            for comm_code, prov_codes in TARGET_COMMODITY_PROVINCES.items():
                comm = commodities.get(comm_code)
                if not comm:
                    continue
                for p_code in prov_codes:
                    prov = provinces.get(p_code)
                    if not prov:
                        continue

                    df_clean = cleaner.clean_and_interpolate_series(
                        commodity_id=comm.id,
                        province_id=prov.id,
                        start_date=start_date,
                        end_date=end_date,
                    )
                    if df_clean.empty:
                        continue

                    df_feat = self.compute_features_from_dataframe(
                        df=df_clean,
                        commodity_code=comm_code,
                    )
                    saved_count = self.upsert_feature_dataframe(df_feat)
                    interp_count = int(df_feat["is_interpolated"].sum())
                    missing_count = int(df_feat["price"].isna().sum())

                    total_rows_upserted += saved_count
                    total_interpolated_points += interp_count

                    series_stats.append({
                        "commodity_code": comm_code,
                        "province_code": p_code,
                        "province_name": prov.standard_name,
                        "rows_saved": saved_count,
                        "interpolated_points": interp_count,
                        "unfilled_long_gap_points": missing_count,
                        "feature_columns_count": len(FEATURE_COLUMNS),
                    })

            tracker.add_records(total_rows_upserted)

        return {
            "total_series_processed": len(series_stats),
            "total_rows_upserted": total_rows_upserted,
            "total_feature_rows_upserted": total_rows_upserted,
            "total_interpolated_points": total_interpolated_points,
            "feature_columns_count": len(FEATURE_COLUMNS),
            "series_details": series_stats,
        }


FeatureEngineeringPipeline = FeatureEngineer


