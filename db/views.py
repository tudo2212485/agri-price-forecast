"""Database Views and Coverage Analytics (Section 4.3, FR-42).

Thống kê độ phủ dữ liệu theo từng cặp (commodity_id, province_id):
- min_date: Ngày đầu tiên có dữ liệu
- max_date: Ngày cuối cùng có dữ liệu
- total_days_with_data: Tổng số ngày thực tế có bản ghi giá
- total_span_days: Khoảng thời gian từ min_date đến max_date (tính theo ngày)
- missing_ratio: Tỷ lệ ngày bị khuyết dữ liệu
- max_gap_days: Khoảng cách ngày lớn nhất giữa 2 lần cập nhật liên tiếp
"""

from typing import List, Dict, Any, Optional
from datetime import date
from sqlalchemy import text, Engine
from sqlalchemy.orm import Session
import pandas as pd
from db.models import PriceObservation


CREATE_DATA_COVERAGE_VIEW_SQL = """
CREATE OR REPLACE VIEW data_coverage_view AS
WITH date_ordered AS (
    SELECT 
        commodity_id,
        province_id,
        obs_date,
        LEAD(obs_date) OVER (PARTITION BY commodity_id, province_id ORDER BY obs_date) AS next_date
    FROM (
        SELECT DISTINCT commodity_id, province_id, obs_date 
        FROM price_observation
    ) distinct_dates
),
gaps AS (
    SELECT 
        commodity_id,
        province_id,
        COALESCE(MAX(next_date - obs_date), 0) AS max_gap_days
    FROM date_ordered
    GROUP BY commodity_id, province_id
),
aggregates AS (
    SELECT 
        commodity_id,
        province_id,
        MIN(obs_date) AS min_date,
        MAX(obs_date) AS max_date,
        COUNT(DISTINCT obs_date) AS total_days_with_data
    FROM price_observation
    GROUP BY commodity_id, province_id
)
SELECT 
    a.commodity_id,
    a.province_id,
    a.min_date,
    a.max_date,
    a.total_days_with_data,
    (a.max_date - a.min_date + 1) AS total_span_days,
    ROUND(
        CASE 
            WHEN (a.max_date - a.min_date + 1) > 0 
            THEN ((a.max_date - a.min_date + 1 - a.total_days_with_data)::numeric / (a.max_date - a.min_date + 1)::numeric)
            ELSE 0 
        END, 
        4
    ) AS missing_ratio,
    g.max_gap_days
FROM aggregates a
JOIN gaps g ON a.commodity_id = g.commodity_id AND a.province_id = g.province_id;
"""


def create_data_coverage_view(engine: Engine) -> None:
    """Tạo hoặc cập nhật SQL View data_coverage_view trên cơ sở dữ liệu PostgreSQL."""
    if "postgresql" in engine.url.drivername:
        with engine.begin() as conn:
            conn.execute(text(CREATE_DATA_COVERAGE_VIEW_SQL))


def get_data_coverage_metrics(
    db: Session,
    commodity_id: Optional[int] = None,
    province_id: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Truy vấn thống kê độ phủ dữ liệu (FR-42).
    Hỗ trợ cả PostgreSQL (qua SQL View hoặc Query trực tiếp) và SQLite (cho Unit test).
    """
    query = db.query(
        PriceObservation.commodity_id,
        PriceObservation.province_id,
        PriceObservation.obs_date
    )
    if commodity_id is not None:
        query = query.filter(PriceObservation.commodity_id == commodity_id)
    if province_id is not None:
        query = query.filter(PriceObservation.province_id == province_id)

    records = query.all()
    if not records:
        return []

    # Nhóm theo (commodity_id, province_id)
    grouped: Dict[tuple, List[date]] = {}
    for r in records:
        key = (r.commodity_id, r.province_id)
        if key not in grouped:
            grouped[key] = []
        grouped[key].append(r.obs_date)

    results: List[Dict[str, Any]] = []
    for (c_id, p_id), dates in grouped.items():
        unique_dates = sorted(list(set(dates)))
        min_d = unique_dates[0]
        max_d = unique_dates[-1]
        total_days = len(unique_dates)
        span_days = (max_d - min_d).days + 1

        # Tính max gap days
        if len(unique_dates) > 1:
            max_gap = max((unique_dates[i] - unique_dates[i - 1]).days for i in range(1, len(unique_dates)))
        else:
            max_gap = 0

        missing_days = span_days - total_days
        missing_ratio = round(missing_days / span_days, 4) if span_days > 0 else 0.0

        results.append({
            "commodity_id": c_id,
            "province_id": p_id,
            "min_date": min_d,
            "max_date": max_d,
            "total_days_with_data": total_days,
            "total_span_days": span_days,
            "missing_ratio": missing_ratio,
            "max_gap_days": max_gap,
            "is_sufficient_for_training": total_days >= 30 and missing_ratio <= 0.3
        })

    return results

