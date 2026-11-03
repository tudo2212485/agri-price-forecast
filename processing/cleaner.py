"""Data Cleaning, Outlier Winsorizing, Flagged Short-Gap Interpolation & Weather Merging.

Tuân thủ chặt chẽ SRS v1.1:
- FR-07: Chuẩn hóa, hợp nhất dữ liệu giá với biến ngoại sinh thời tiết theo ngày và tỉnh.
- FR-08 & Mục 4.2: Giữ nguyên dữ liệu thô; xử lý ngoại lệ (OUTLIER) bằng Winsorizing quá khứ;
  gắn cờ truy vết (is_interpolated, quality_flag) cho mọi bản ghi đã xử lý.
- FR-36: Quy tắc nội suy nghiêm ngặt:
  + Chỉ nội suy tuyến tính cho khoảng thiếu ngắn <= MAX_INTERPOLATION_GAP (3 ngày).
  + Khoảng thiếu dài (> 3 ngày liên tiếp) bắt buộc ĐỂ TRỐNG (NaN / None), tuyệt đối không điền giả.
- NFR-04: Toàn bộ quá trình xử lý ngoại lệ và điền khuyết thời tiết chỉ nhìn về quá khứ (Zero Data Leakage).
"""

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Dict, Any, List, Tuple

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from collector.base import BaseCollector
from db.database import get_vietnam_now
from db.models import PriceObservation, WeatherObservation, DataSource

# Ngưỡng tối đa số ngày liên tiếp được phép nội suy tuyến tính (FR-36)
MAX_INTERPOLATION_GAP = 3

# Trọng số độ tin cậy nguồn dữ liệu khi gộp nhiều nguồn trong cùng 1 ngày
RELIABILITY_WEIGHTS: Dict[str, float] = {
    "HIGH": 2.0,
    "MEDIUM": 1.0,
    "LOW": 0.5,
}


class TimeSeriesCleaner:
    """
    Bộ làm sạch chuỗi thời gian giá nông sản, nội suy có gắn cờ và hợp nhất biến thời tiết.
    """

    def __init__(
        self,
        db: Session,
        max_interpolation_gap: int = MAX_INTERPOLATION_GAP,
         persist_interpolated_to_db: bool = True,
    ):
        self.db = db
        self.max_interpolation_gap = max_interpolation_gap
        self.persist_interpolated_to_db = persist_interpolated_to_db
        self._collector_helper = BaseCollector(db=db, rate_limit_delay=0.0)

    def _load_daily_aggregated_prices(
        self,
        commodity_id: int,
        province_id: int,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> Tuple[pd.DataFrame, Optional[int]]:
        """
        Đọc các bản ghi giá từ price_observation (loại bỏ INVALID),
        gộp theo obs_date bằng trung bình có trọng số theo reliability_level của nguồn.
        """
        sources = {s.id: s for s in self.db.query(DataSource).all()}

        query = self.db.query(PriceObservation).filter(
            PriceObservation.commodity_id == commodity_id,
            PriceObservation.province_id == province_id,
            PriceObservation.quality_flag != "INVALID",
        )
        if start_date is not None:
            query = query.filter(PriceObservation.obs_date >= start_date)
        if end_date is not None:
            query = query.filter(PriceObservation.obs_date <= end_date)

        records: List[PriceObservation] = query.order_by(PriceObservation.obs_date.asc()).all()
        if not records:
            return pd.DataFrame(), None

        primary_source_id = records[0].source_id
        daily_buckets: Dict[date, List[PriceObservation]] = {}
        for rec in records:
            if rec.price is None or float(rec.price) <= 0:
                continue
            daily_buckets.setdefault(rec.obs_date, []).append(rec)

        if not daily_buckets:
            return pd.DataFrame(), primary_source_id

        rows: List[Dict[str, Any]] = []
        for obs_dt in sorted(daily_buckets.keys()):
            day_recs = daily_buckets[obs_dt]
            # Ưu tiên các bản ghi thực đo (không phải bản ghi nội suy từ lần chạy trước) nếu có
            measured_recs = [r for r in day_recs if not r.is_interpolated]
            active_recs = measured_recs if measured_recs else day_recs

            weights = [
                RELIABILITY_WEIGHTS.get(
                    sources[r.source_id].reliability_level if r.source_id in sources else "HIGH",
                    1.0,
                )
                for r in active_recs
            ]
            prices = [float(r.price) for r in active_recs]
            weighted_price = float(np.average(prices, weights=weights))

            # Nếu bất kỳ bản ghi gốc nào bị đánh dấu OUTLIER thì giữ cờ OUTLIER để bước tiếp theo xử lý
            flags = {r.quality_flag for r in active_recs}
            if "OUTLIER" in flags:
                q_flag = "OUTLIER"
            elif all(r.is_interpolated for r in active_recs):
                q_flag = "INTERPOLATED"
            else:
                q_flag = "OK"

            is_interp = all(r.is_interpolated for r in active_recs)
            rows.append({
                "obs_date": pd.Timestamp(obs_dt),
                "price": weighted_price,
                "is_interpolated": is_interp,
                "quality_flag": q_flag,
            })

        df = pd.DataFrame(rows).sort_values("obs_date").reset_index(drop=True)
        return df, primary_source_id

    @staticmethod
    def _winsorize_past_only_outliers(df: pd.DataFrame, window: int = 30) -> pd.DataFrame:
        """
        Xử lý các điểm có quality_flag == 'OUTLIER' bằng phương pháp Winsorizing
        chỉ sử dụng dữ liệu quá khứ [t - window, t - 1] (Zero Data Leakage - NFR-04).
        Giữ nguyên quality_flag == 'OUTLIER' để đảm bảo khả năng truy vết (FR-08).
        """
        if df.empty or "OUTLIER" not in df["quality_flag"].values:
            return df

        df = df.copy()
        prices = df["price"].to_numpy(dtype=float).copy()
        flags = df["quality_flag"].tolist()

        for idx in range(len(df)):
            if flags[idx] != "OUTLIER":
                continue

            # Lấy tối đa `window` điểm hợp lệ (OK / INTERPOLATED) nằm hoàn toàn ở quá khứ (< idx)
            past_indices = [
                j for j in range(max(0, idx - window), idx)
                if flags[j] in ("OK", "INTERPOLATED") and not np.isnan(prices[j])
            ]
            if len(past_indices) >= 4:
                past_vals = prices[past_indices]
                q25, q75 = np.percentile(past_vals, [25, 75])
                iqr = q75 - q25
                if iqr > 0:
                    lower_clip = q25 - 1.5 * iqr
                    upper_clip = q75 + 1.5 * iqr
                    prices[idx] = float(np.clip(prices[idx], lower_clip, upper_clip))
                else:
                    prices[idx] = float(np.median(past_vals))
            elif len(past_indices) >= 1:
                prices[idx] = float(prices[past_indices[-1]])

        df["price"] = prices
        return df

    def clean_and_interpolate_series(
        self,
        commodity_id: int,
        province_id: int,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> pd.DataFrame:
        """
        Thực hiện quy trình làm sạch, nội suy ngắn hạn (<= 3 ngày) và hợp nhất thời tiết
        cho một cặp (commodity_id, province_id):
        1. Loại bỏ bản ghi INVALID, tổng hợp theo ngày.
        2. Winsorize điểm OUTLIER dựa trên lịch sử quá khứ.
        3. Tái lập lưới ngày liên tục:
           - Khoảng trống <= 3 ngày: Nội suy tuyến tính, gắn is_interpolated=True, quality_flag='INTERPOLATED',
             và lưu ngược vào price_observation để truy vết.
           - Khoảng trống > 3 ngày: Bắt buộc giữ nguyên NaN (FR-36).
        4. Hợp nhất với bảng weather_observation theo (obs_date, province_id), ffill(limit=2) cho thời tiết.
        """
        df_price, primary_source_id = self._load_daily_aggregated_prices(
            commodity_id=commodity_id,
            province_id=province_id,
            start_date=start_date,
            end_date=end_date,
        )
        if df_price.empty:
            return pd.DataFrame()

        # Bước 1: Xử lý ngoại lệ không nhìn tương lai
        df_price = self._winsorize_past_only_outliers(df_price)

        # Bước 2: Tái lập lưới ngày liên tục từ min_date đến max_date
        min_dt = df_price["obs_date"].min()
        max_dt = df_price["obs_date"].max()
        full_index = pd.date_range(start=min_dt, end=max_dt, freq="D", name="obs_date")

        df_reindexed = (
            df_price.set_index("obs_date")
            .reindex(full_index)
            .reset_index()
        )

        # Xác định các khoảng trống (NaN) và độ dài từng khoảng trống liên tiếp
        is_missing = df_reindexed["price"].isna()
        gap_group_ids = is_missing.ne(is_missing.shift()).cumsum()
        gap_lengths = is_missing.groupby(gap_group_ids).transform("sum")

        # Thực hiện nội suy tuyến tính với limit=max_interpolation_gap và limit_area='inside'
        interpolated_series = df_reindexed["price"].interpolate(
            method="linear",
            limit=self.max_interpolation_gap,
            limit_area="inside",
        )

        # Chỉ chấp nhận nội suy tại các khoảng thiếu ngắn <= max_interpolation_gap (FR-36)
        short_gap_mask = (
            is_missing
            & (gap_lengths <= self.max_interpolation_gap)
            & interpolated_series.notna()
        )
        # Các khoảng thiếu dài (> max_interpolation_gap) bắt buộc giữ nguyên là NaN (FR-36)
        long_gap_mask = is_missing & (gap_lengths > self.max_interpolation_gap)

        df_reindexed.loc[short_gap_mask, "price"] = interpolated_series[short_gap_mask].round(2)
        df_reindexed.loc[short_gap_mask, "is_interpolated"] = True
        df_reindexed.loc[short_gap_mask, "quality_flag"] = "INTERPOLATED"

        df_reindexed.loc[long_gap_mask, "price"] = np.nan
        df_reindexed.loc[long_gap_mask, "is_interpolated"] = False
        df_reindexed.loc[long_gap_mask, "quality_flag"] = "MISSING"

        df_reindexed["is_interpolated"] = (
            df_reindexed["is_interpolated"]
            .where(df_reindexed["is_interpolated"].notna(), False)
            .astype(bool)
        )
        df_reindexed["quality_flag"] = (
            df_reindexed["quality_flag"]
            .where(df_reindexed["quality_flag"].notna(), "OK")
            .astype(str)
        )
        df_reindexed["commodity_id"] = commodity_id
        df_reindexed["province_id"] = province_id

        # Bước 3: Lưu vết các bản ghi nội suy ngược vào bảng price_observation (FR-08, FR-36)
        if self.persist_interpolated_to_db and primary_source_id is not None and short_gap_mask.any():
            interp_rows = df_reindexed.loc[short_gap_mask]
            now = get_vietnam_now()
            upsert_payload: List[Dict[str, Any]] = []
            for _, row in interp_rows.iterrows():
                price_dec = Decimal(str(row["price"])).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                upsert_payload.append({
                    "obs_date": row["obs_date"].date(),
                    "commodity_id": commodity_id,
                    "province_id": province_id,
                    "source_id": primary_source_id,
                    "price": price_dec,
                    "raw_value": "INTERPOLATED",
                    "raw_unit": "VNĐ/kg",
                    "source_url": f"system://linear_interpolation_limit_{self.max_interpolation_gap}",
                    "is_interpolated": True,
                    "quality_flag": "INTERPOLATED",
                    "review_flag": False,
                    "collected_at": now,
                })
            self._collector_helper.upsert_price_observations(upsert_payload)

        # Bước 4: Hợp nhất với dữ liệu thời tiết từ bảng weather_observation (FR-07)
        df_merged = self._merge_weather_observations(
            df_price_grid=df_reindexed,
            province_id=province_id,
            min_date=min_dt.date(),
            max_date=max_dt.date(),
        )
        return df_merged

    def _merge_weather_observations(
        self,
        df_price_grid: pd.DataFrame,
        province_id: int,
        min_date: date,
        max_date: date,
    ) -> pd.DataFrame:
        """Left-join dữ liệu thời tiết theo (obs_date, province_id) và ffill tối đa 2 ngày."""
        weather_recs = (
            self.db.query(WeatherObservation)
            .filter(
                WeatherObservation.province_id == province_id,
                WeatherObservation.obs_date >= min_date,
                WeatherObservation.obs_date <= max_date,
            )
            .order_by(WeatherObservation.obs_date.asc())
            .all()
        )

        weather_cols = ["temp_max", "temp_min", "temp_mean", "precipitation", "humidity"]
        if not weather_recs:
            for col in weather_cols:
                df_price_grid[col] = np.nan
            df_price_grid["obs_date"] = df_price_grid["obs_date"].dt.date
            return df_price_grid

        w_rows = []
        for w in weather_recs:
            w_rows.append({
                "obs_date": pd.Timestamp(w.obs_date),
                "temp_max": w.temp_max,
                "temp_min": w.temp_min,
                "temp_mean": w.temp_mean,
                "precipitation": w.precipitation,
                "humidity": w.humidity,
            })
        df_weather = (
            pd.DataFrame(w_rows)
            .drop_duplicates(subset=["obs_date"], keep="last")
            .sort_values("obs_date")
        )

        merged = pd.merge(df_price_grid, df_weather, on="obs_date", how="left")
        # Chỉ dùng forward-fill tối đa 2 ngày từ quá khứ, tuyệt đối không dùng bfill (NFR-04)
        for col in weather_cols:
            merged[col] = merged[col].ffill(limit=2)

        merged["obs_date"] = merged["obs_date"].dt.date
        return merged
