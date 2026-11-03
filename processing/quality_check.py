"""Data Quality Validation, Cross-Source Reconciliation & Coverage Reporting (FR-06, FR-35, FR-42).

Thực hiện:
1. Kiểm tra chất lượng dữ liệu giá (FR-06):
   - Phát hiện giá âm, bằng 0 hoặc vượt ngưỡng vật lý/thị trường hợp lý -> gắn quality_flag = 'INVALID'.
   - Phát hiện điểm dị biệt (Outlier) theo ngưỡng biến động ngày (> 25%/ngày) kết hợp khoảng tứ phân vị trượt (Rolling IQR) -> gắn quality_flag = 'OUTLIER'.
2. Đối chiếu chéo đa nguồn (FR-35):
   - Khi cùng (obs_date, commodity_id, province_id) có >= 2 nguồn (source_id) chênh lệch > threshold_pct (mặc định 5%),
     tự động bật cờ review_flag = True trên các bản ghi đó mà không xóa hay ghi đè dữ liệu.
3. Xuất báo cáo chất lượng & độ phủ dữ liệu lịch sử (FR-06, FR-42):
   - Tích hợp kết quả từ data_coverage_view (db/views.py) để đánh giá điều kiện đủ dữ liệu huấn luyện (>= 365 ngày).
"""

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Dict, Any, List, Optional, Tuple

import numpy as np
from sqlalchemy.orm import Session

from db.models import PriceObservation, WeatherObservation, Commodity, Province
from db.views import get_data_coverage_metrics


# Ngưỡng giá hợp lý theo từng mặt hàng tại thị trường Việt Nam (VNĐ/kg)
COMMODITY_PRICE_BOUNDS: Dict[str, Tuple[Decimal, Decimal]] = {
    "CAFE_ROBUSTA": (Decimal("20000.00"), Decimal("250000.00")),
    "TIEU_DEN": (Decimal("25000.00"), Decimal("300000.00")),
    "LUA_IR50404": (Decimal("3000.00"), Decimal("30000.00")),
}
DEFAULT_PRICE_BOUNDS: Tuple[Decimal, Decimal] = (Decimal("100.00"), Decimal("1000000.00"))


def run_price_quality_checks(
    db: Session,
    commodity_id: Optional[int] = None,
    province_id: Optional[int] = None,
    max_daily_Jump_pct: float = 25.0,
    iqr_multiplier: float = 2.5,
    rolling_window: int = 30,
) -> Dict[str, int]:
    """
    Quét và kiểm định chất lượng các bản ghi trong bảng price_observation (FR-06).
    Cập nhật cột quality_flag thành:
    - 'INVALID': Giá <= 0 hoặc nằm ngoài khoảng hợp lý của nông sản.
    - 'OUTLIER': Biến động đột ngột > 25%/ngày hoặc vượt ngưỡng Rolling IQR cục bộ.
    - 'INTERPOLATED': Bản ghi được nội suy (is_interpolated = True).
    - 'OK': Bản ghi đạt chuẩn chất lượng.
    """
    commodities = {c.id: c.code for c in db.query(Commodity).all()}

    query = db.query(PriceObservation)
    if commodity_id is not None:
        query = query.filter(PriceObservation.commodity_id == commodity_id)
    if province_id is not None:
        query = query.filter(PriceObservation.province_id == province_id)

    all_records: List[PriceObservation] = query.order_by(
        PriceObservation.commodity_id,
        PriceObservation.province_id,
        PriceObservation.source_id,
        PriceObservation.obs_date,
    ).all()

    stats = {
        "total_checked": len(all_records),
        "ok_count": 0,
        "invalid_count": 0,
        "outlier_count": 0,
        "interpolated_count": 0,
    }

    if not all_records:
        return stats

    # Nhóm theo chuỗi (commodity_id, province_id, source_id)
    series_groups: Dict[Tuple[int, int, int], List[PriceObservation]] = defaultdict(list)
    for rec in all_records:
        series_groups[(rec.commodity_id, rec.province_id, rec.source_id)].append(rec)

    for (c_id, p_id, s_id), series in series_groups.items():
        comm_code = commodities.get(c_id, "")
        min_bound, max_bound = COMMODITY_PRICE_BOUNDS.get(comm_code, DEFAULT_PRICE_BOUNDS)

        # Bước 1: Kiểm tra INVALID (giá âm, bằng 0 hoặc vượt biên độ vật lý)
        valid_candidates: List[PriceObservation] = []
        for rec in series:
            price_val = Decimal(str(rec.price)) if rec.price is not None else Decimal("-1")
            if price_val <= Decimal("0") or price_val < min_bound or price_val > max_bound:
                rec.quality_flag = "INVALID"
                stats["invalid_count"] += 1
            else:
                valid_candidates.append(rec)

        if not valid_candidates:
            continue

        # Bước 2: Phát hiện OUTLIER trên các bản ghi không bị INVALID
        prices_float = [float(r.price) for r in valid_candidates]
        n_valid = len(valid_candidates)
        prev_ok_price: Optional[float] = None

        for idx, rec in enumerate(valid_candidates):
            cur_price = prices_float[idx]
            is_outlier = False

            # Tiêu chí 2a: Biến động vượt quá max_daily_Jump_pct (mặc định 25%) so với giá hợp lệ liền trước
            if prev_ok_price is not None and prev_ok_price > 0:
                pct_change = abs(cur_price - prev_ok_price) / prev_ok_price * 100.0
                if pct_change > max_daily_Jump_pct:
                    is_outlier = True

            # Tiêu chí 2b: Phương pháp IQR trên cửa sổ lân cận (Rolling IQR) khi chuỗi đủ điểm (>= 7)
            if not is_outlier and n_valid >= 7:
                half_w = max(3, rolling_window // 2)
                w_start = max(0, idx - half_w)
                w_end = min(n_valid, idx + half_w + 1)
                window_vals = prices_float[w_start:w_end]
                q25, q75 = np.percentile(window_vals, [25, 75])
                iqr = q75 - q25
                median_val = float(np.median(window_vals))
                if iqr > 0:
                    lower_fence = q25 - iqr_multiplier * iqr
                    upper_fence = q75 + iqr_multiplier * iqr
                    if (cur_price < lower_fence or cur_price > upper_fence) and (
                        abs(cur_price - median_val) / median_val > 0.20
                    ):
                        is_outlier = True

            if is_outlier:
                rec.quality_flag = "OUTLIER"
                stats["outlier_count"] += 1
                # Không cập nhật prev_ok_price bằng điểm dị biệt để tránh làm lệch ngày kế tiếp
            else:
                if rec.is_interpolated:
                    rec.quality_flag = "INTERPOLATED"
                    stats["interpolated_count"] += 1
                else:
                    rec.quality_flag = "OK"
                    stats["ok_count"] += 1
                prev_ok_price = cur_price

    db.commit()
    return stats


def run_cross_source_reconciliation(
    db: Session,
    threshold_pct: float = 5.0,
    commodity_id: Optional[int] = None,
    province_id: Optional[int] = None,
) -> Dict[str, int]:
    """
    Đối chiếu chéo dữ liệu giá giữa nhiều nguồn cho cùng (obs_date, commodity_id, province_id) (FR-35).
    - Nếu chênh lệch giữa giá cao nhất và giá thấp nhất của các nguồn trong cùng ngày > threshold_pct (mặc định 5%):
      bật cờ review_flag = True trên TẤT CẢ các bản ghi của ngày/nông sản/tỉnh đó.
    - Tuyệt đối không tự ý xóa hay ghi đè bất kỳ bản ghi nào.
    """
    query = db.query(PriceObservation)
    if commodity_id is not None:
        query = query.filter(PriceObservation.commodity_id == commodity_id)
    if province_id is not None:
        query = query.filter(PriceObservation.province_id == province_id)

    records = query.all()
    grouped: Dict[Tuple[date, int, int], List[PriceObservation]] = defaultdict(list)

    for rec in records:
        grouped[(rec.obs_date, rec.commodity_id, rec.province_id)].append(rec)

    groups_multi_source = 0
    groups_flagged = 0
    records_flagged = 0

    for key, group_recs in grouped.items():
        distinct_sources = {r.source_id for r in group_recs}
        if len(distinct_sources) < 2:
            for r in group_recs:
                if r.review_flag:
                    r.review_flag = False
            continue

        groups_multi_source += 1
        positive_prices = [float(r.price) for r in group_recs if r.price is not None and float(r.price) > 0]

        if len(positive_prices) >= 2:
            min_p = min(positive_prices)
            max_p = max(positive_prices)
            diff_pct = ((max_p - min_p) / min_p) * 100.0 if min_p > 0 else 0.0
        else:
            diff_pct = 0.0

        if diff_pct > threshold_pct:
            groups_flagged += 1
            for r in group_recs:
                r.review_flag = True
                records_flagged += 1
        else:
            for r in group_recs:
                r.review_flag = False

    db.commit()
    return {
        "groups_compared": groups_multi_source,
        "groups_flagged": groups_flagged,
        "records_flagged": records_flagged,
    }


def generate_data_quality_and_coverage_report(
    db: Session,
    min_training_days: int = 365,
    max_missing_ratio: float = 0.30,
    print_table: bool = False,
) -> Dict[str, Any]:
    """
    Tổng hợp Báo cáo Chất lượng Dữ liệu & Độ phủ Lịch sử (FR-06, FR-42).
    Kết hợp kết quả từ data_coverage_view (db/views.py) và thống kê quality_flag/review_flag.
    """
    commodities = {c.id: c for c in db.query(Commodity).all()}
    provinces = {p.id: p for p in db.query(Province).all()}

    coverage_rows = get_data_coverage_metrics(db)

    # Thống kê chi tiết cờ chất lượng theo từng cặp (commodity_id, province_id)
    all_price_records = db.query(PriceObservation).all()
    pair_quality_counts: Dict[Tuple[int, int], Dict[str, int]] = defaultdict(
        lambda: {"total": 0, "OK": 0, "OUTLIER": 0, "INVALID": 0, "INTERPOLATED": 0, "review": 0}
    )

    total_summary = {
        "total_price_records": len(all_price_records),
        "ok_records": 0,
        "outlier_records": 0,
        "invalid_records": 0,
        "interpolated_records": 0,
        "review_flagged_records": 0,
        "total_weather_records": db.query(WeatherObservation).count(),
    }

    for rec in all_price_records:
        key = (rec.commodity_id, rec.province_id)
        pair_quality_counts[key]["total"] += 1
        flag = rec.quality_flag or "OK"
        if flag in pair_quality_counts[key]:
            pair_quality_counts[key][flag] += 1

        if flag == "OK":
            total_summary["ok_records"] += 1
        elif flag == "OUTLIER":
            total_summary["outlier_records"] += 1
        elif flag == "INVALID":
            total_summary["invalid_records"] += 1
        elif flag == "INTERPOLATED":
            total_summary["interpolated_records"] += 1

        if rec.review_flag:
            pair_quality_counts[key]["review"] += 1
            total_summary["review_flagged_records"] += 1

    detailed_coverage: List[Dict[str, Any]] = []
    eligible_pairs_count = 0

    for cov in sorted(coverage_rows, key=lambda x: (x["commodity_id"], x["province_id"])):
        c_id = cov["commodity_id"]
        p_id = cov["province_id"]
        comm = commodities.get(c_id)
        prov = provinces.get(p_id)
        q_counts = pair_quality_counts[(c_id, p_id)]

        is_eligible = (
            cov["total_days_with_data"] >= min_training_days
            and cov["missing_ratio"] <= max_missing_ratio
        )
        if is_eligible:
            eligible_pairs_count += 1

        detailed_coverage.append({
            "commodity_id": c_id,
            "commodity_code": comm.code if comm else str(c_id),
            "commodity_name": comm.name if comm else str(c_id),
            "province_id": p_id,
            "province_code": prov.code if prov else str(p_id),
            "province_name": prov.standard_name if prov else str(p_id),
            "min_date": cov["min_date"].strftime("%Y-%m-%d") if isinstance(cov["min_date"], date) else str(cov["min_date"]),
            "max_date": cov["max_date"].strftime("%Y-%m-%d") if isinstance(cov["max_date"], date) else str(cov["max_date"]),
            "total_days_with_data": cov["total_days_with_data"],
            "total_span_days": cov["total_span_days"],
            "missing_ratio": cov["missing_ratio"],
            "max_gap_days": cov["max_gap_days"],
            "total_records": q_counts["total"],
            "ok_records": q_counts["OK"],
            "outlier_records": q_counts["OUTLIER"],
            "invalid_records": q_counts["INVALID"],
            "interpolated_records": q_counts["INTERPOLATED"],
            "review_flagged_records": q_counts["review"],
            "is_eligible_for_training": is_eligible,
        })

    report = {
        "summary": {
            **total_summary,
            "total_series_evaluated": len(detailed_coverage),
            "eligible_series_for_training": eligible_pairs_count,
            "min_training_days_threshold": min_training_days,
        },
        "series_coverage": detailed_coverage,
    }

    if print_table:
        _print_coverage_report_table(report)

    return report


def _print_coverage_report_table(report: Dict[str, Any]) -> None:
    """In bảng báo cáo chất lượng và độ phủ dữ liệu ra màn hình console."""
    summary = report["summary"]
    print("\n" + "=" * 118)
    print("BÁO CÁO CHẤT LƯỢNG DỮ LIỆU & ĐỘ PHỦ LỊCH SỬ (FR-06, FR-35, FR-42)")
    print("=" * 118)
    print(
        f"Tổng bản ghi Giá: {summary['total_price_records']:,} "
        f"(Hợp lệ: {summary['ok_records']:,} | Ngoại lệ: {summary['outlier_records']:,} | "
        f"Lỗi: {summary['invalid_records']:,} | Cần Review chéo: {summary['review_flagged_records']:,})"
    )
    print(
        f"Tổng bản ghi Thời tiết (Open-Meteo): {summary['total_weather_records']:,} | "
        f"Số chuỗi đủ điều kiện huấn luyện (>= {summary['min_training_days_threshold']} ngày): "
        f"{summary['eligible_series_for_training']}/{summary['total_series_evaluated']}"
    )
    print("-" * 118)
    header = (
        f"{'Nông sản':<15} | {'Tỉnh':<18} | {'Từ ngày':<10} | {'Đến ngày':<10} | "
        f"{'Số ngày':>8} | {'Tỷ lệ thiếu':>11} | {'Max Gap':>7} | {'OK/Out/Rev':>14} | {'Đủ ĐK Train':<11}"
    )
    print(header)
    print("-" * 118)
    for row in report["series_coverage"]:
        status_str = "ĐẠT (YES)" if row["is_eligible_for_training"] else "CHƯA ĐẠT"
        q_str = f"{row['ok_records']}/{row['outlier_records']}/{row['review_flagged_records']}"
        print(
            f"{row['commodity_code']:<15} | {row['province_name']:<18} | "
            f"{row['min_date']:<10} | {row['max_date']:<10} | "
            f"{row['total_days_with_data']:>8,} | {row['missing_ratio'] * 100:>10.2f}% | "
            f"{row['max_gap_days']:>5}d | {q_str:>14} | {status_str:<11}"
        )
    print("=" * 118 + "\n")

