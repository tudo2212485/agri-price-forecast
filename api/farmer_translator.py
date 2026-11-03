"""Natural Language Translator for Older Farmers & Non-Technical Users (SRS v1.1).

Tuân thủ chặt chẽ:
- FR-49 (Tóm tắt xu hướng bằng ngôn ngữ tự nhiên dễ hiểu): Sinh câu kết luận chữ to, rõ ràng
  về xu hướng giá dự báo (TĂNG / GIẢM / GIỮ ỔN ĐỊNH) kèm mức chênh lệch VNĐ/kg và %.
- FR-50 (Chế độ hiển thị Đơn giản): Cung cấp thông điệp hành động tham khảo (không vi phạm
  phạm vi tư vấn tài chính Mục 1.3).
- FR-51 (Chỉ báo mức độ tin cậy dễ hiểu): Chuyển đổi chỉ số sai số kỹ thuật MAPE và độ rộng
  khoảng tin cậy sang 3 mức ngôn ngữ đời thường:
  + "Khá chắc chắn" (HIGH)
  + "Mức độ vừa phải" (MEDIUM)
  + "Chỉ để tham khảo" (LOW)
"""

from typing import Dict, Any, Optional


def format_vnd_number(value: float, round_to_hundred: bool = True) -> str:
    """
    Định dạng số tiền VNĐ/kg theo chuẩn tiếng Việt (dấu chấm phân cách hàng nghìn).
    Làm tròn đến hàng trăm đồng (hoặc hàng chục đồng nếu giá trị nhỏ dưới 500 đồng).
    """
    abs_val = abs(float(value))
    if round_to_hundred and abs_val >= 500:
        rounded = int(round(abs_val / 100.0) * 100)
    elif round_to_hundred and abs_val >= 50:
        rounded = int(round(abs_val / 10.0) * 10)
    else:
        rounded = int(round(abs_val))
    return f"{rounded:,}".replace(",", ".")


def format_pct_vi(pct_val: float) -> str:
    """Định dạng phần trăm theo chuẩn tiếng Việt (dấu phẩy thập phân, ví dụ: 3,2)."""
    abs_pct = abs(float(pct_val))
    formatted = f"{abs_pct:.2f}".rstrip("0").rstrip(".")
    if not formatted:
        formatted = "0"
    return formatted.replace(".", ",")


def translate_confidence_level(
    mape_score: Optional[float],
    ci_width_pct: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Dịch chỉ số kỹ thuật MAPE (%) và độ rộng khoảng tin cậy sang 3 mức ngôn ngữ tự nhiên (FR-51).
    """
    eff_mape = float(mape_score) if mape_score is not None else 1.5

    # Nếu khoảng tin cậy quá rộng (> 12%), hạ bậc tin cậy để cảnh báo an toàn cho nông dân
    wide_ci_penalty = ci_width_pct is not None and float(ci_width_pct) > 12.0

    if eff_mape <= 1.0 and not wide_ci_penalty:
        return {
            "confidence_level": "HIGH",
            "confidence_label_vi": "Khá chắc chắn",
            "confidence_explanation_vi": (
                "Dữ liệu lịch sử ổn định, sai số dự báo của hệ thống rất thấp."
            ),
            "badge_color": "green",
        }
    elif eff_mape <= 2.5 and not (ci_width_pct is not None and float(ci_width_pct) > 18.0):
        return {
            "confidence_level": "MEDIUM",
            "confidence_label_vi": "Mức độ vừa phải",
            "confidence_explanation_vi": (
                "Thị trường có dao động nhẹ, bà con nên kết hợp tham khảo giá đại lý địa phương."
            ),
            "badge_color": "amber",
        }
    else:
        return {
            "confidence_level": "LOW",
            "confidence_label_vi": "Chỉ để tham khảo",
            "confidence_explanation_vi": (
                "Giá đang trong giai đoạn biến động thất thường, dự báo chỉ mang tính định hướng."
            ),
            "badge_color": "red",
        }


def generate_farmer_friendly_summary(
    commodity_name: str,
    province_name: str,
    current_price: float,
    target_price: float,
    horizon_days: int = 7,
    mape_score: Optional[float] = 0.5,
    ci_width_pct: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Sinh bản tóm tắt ngôn ngữ tự nhiên tiếng Việt thân thiện cho nông dân lớn tuổi (FR-49, FR-50, FR-51).
    Đồng bộ chính xác phép tính: current_price + change_amount = target_price.
    """
    curr_val = float(current_price) if current_price and current_price > 0 else 1.0
    targ_val = float(target_price) if target_price is not None else curr_val

    raw_diff = targ_val - curr_val

    # Làm tròn chênh lệch: Nếu nông sản giá thấp (< 20.000 đ/kg như lúa) thì làm tròn đến hàng chục đồng
    # Nếu nông sản giá cao (> 20.000 đ/kg như cà phê, hồ tiêu) thì làm tròn đến hàng trăm đồng
    if abs(curr_val) < 20000:
        if abs(raw_diff) >= 50:
            change_amount = float(round(raw_diff / 10.0) * 10)
        else:
            change_amount = float(round(raw_diff))
    else:
        if abs(raw_diff) >= 200:
            change_amount = float(round(raw_diff / 100.0) * 100)
        elif abs(raw_diff) >= 50:
            change_amount = float(round(raw_diff / 10.0) * 10)
        else:
            change_amount = float(round(raw_diff))

    # Đồng bộ tuyệt đối giá dự kiến: current_price + change_amount = unified_target_price
    unified_target_price = curr_val + change_amount
    change_pct = round((change_amount / curr_val) * 100.0, 2) if curr_val > 0 else 0.0

    # Phân loại xu hướng với ngưỡng 0.5% (FR-49)
    if change_pct >= 0.5:
        trend_direction = "UP"
        trend_label_vi = "Tăng"
    elif change_pct <= -0.5:
        trend_direction = "DOWN"
        trend_label_vi = "Giảm"
    else:
        trend_direction = "STABLE"
        trend_label_vi = "Ổn định"

    pct_str = format_pct_vi(change_pct)
    amt_str = format_vnd_number(abs(change_amount))
    curr_str = format_vnd_number(curr_val)
    targ_str = format_vnd_number(unified_target_price)

    if trend_direction == "UP":
        headline_vi = (
            f"Giá {commodity_name} tại {province_name} dự kiến TĂNG khoảng {pct_str}% "
            f"(tăng thêm {amt_str} đồng/kg, lên mức khoảng {targ_str} đồng/kg) trong {horizon_days} ngày tới."
        )
        action_hint_vi = (
            "Bà con có thể theo dõi thêm nhịp tăng giá trong tuần này để cân nhắc thời điểm bán phù hợp."
        )
    elif trend_direction == "DOWN":
        headline_vi = (
            f"Giá {commodity_name} tại {province_name} dự kiến GIẢM khoảng {pct_str}% "
            f"(giảm {amt_str} đồng/kg, về mức khoảng {targ_str} đồng/kg) trong {horizon_days} ngày tới."
        )
        action_hint_vi = (
            "Bà con nên theo dõi sát giá thu mua thực tế tại địa phương và tham khảo giá từ nhiều đại lý trước khi xuất bán."
        )
    else:
        headline_vi = (
            f"Giá {commodity_name} tại {province_name} dự kiến GIỮ ỔN ĐỊNH quanh mức "
            f"{curr_str} đồng/kg trong {horizon_days} ngày tới."
        )
        action_hint_vi = (
            "Thị trường dự kiến ít biến động lớn, bà con có thể chủ động kế hoạch thu hoạch, phơi sấy và bán hàng bình thường."
        )

    conf_info = translate_confidence_level(mape_score=mape_score, ci_width_pct=ci_width_pct)

    return {
        "commodity_name": commodity_name,
        "province_name": province_name,
        "horizon_days": int(horizon_days),
        "current_price": round(curr_val, 2),
        "target_price": round(unified_target_price, 2),
        "trend_direction": trend_direction,
        "trend_label_vi": trend_label_vi,
        "change_amount": change_amount,
        "change_pct": change_pct,
        "headline_vi": headline_vi,
        "action_hint_vi": action_hint_vi,
        "confidence_level": conf_info["confidence_level"],
        "confidence_label_vi": conf_info["confidence_label_vi"],
        "confidence_explanation_vi": conf_info["confidence_explanation_vi"],
        "badge_color": conf_info["badge_color"],
        "disclaimer_vi": (
            "Lưu ý: Kết quả dự báo được tính toán từ dữ liệu lịch sử để bà con tham khảo thông tin thị trường, "
            "không phải khuyến nghị đầu cơ hay cam kết giá mua bán."
        ),
    }

