"""Pydantic v2 Request & Response Schemas for FastAPI Backend (SRS v1.1 - Section 5.2, NFR-05).

Định nghĩa các cấu trúc dữ liệu đầu vào/đầu ra có kiểm tra hợp lệ chặt chẽ:
- Ràng buộc ngưỡng phần trăm cảnh báo (`0.1 <= threshold_pct <= 100.0`), cửa sổ dự báo (`1 <= window_days <= 30`).
- Ràng buộc đăng ký nhận thông báo 1 bước không cần mật khẩu (`SubscriptionCreateRequest`).
- Cấu trúc phản hồi chuẩn cho cả chế độ Nông dân (Simple Mode) và Chuyên gia (Expert Mode).
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator


class AlertRuleCreateRequest(BaseModel):
    """Payload tạo mới quy tắc cảnh báo biến động giá (FR-24)."""

    commodity_code: str = Field(..., min_length=2, max_length=50, description="Mã nông sản (VD: CAFE_ROBUSTA)")
    province_code: Optional[str] = Field(
        default=None, max_length=20, description="Mã tỉnh/thành (VD: DL), để trống nếu áp dụng toàn vùng"
    )
    threshold_pct: float = Field(
        default=5.0, ge=0.1, le=100.0, description="Ngưỡng % biến động tăng/giảm kích hoạt cảnh báo"
    )
    window_days: int = Field(
        default=7, ge=1, le=30, description="Cửa sổ ngày dự báo (1..30 ngày)"
    )
    channel: str = Field(default="EMAIL", description="Kênh thông báo: EMAIL hoặc NOTIFICATION")

    @field_validator("commodity_code")
    @classmethod
    def normalize_commodity_code(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("province_code")
    @classmethod
    def normalize_province_code(cls, v: Optional[str]) -> Optional[str]:
        if v is None or not v.strip():
            return None
        return v.strip().upper()


class SubscriptionCreateRequest(BaseModel):
    """Payload đăng ký nhận thông báo 1 bước không cần tài khoản/mật khẩu (FR-27, FR-53)."""

    contact_info: str = Field(
        ..., min_length=3, max_length=255, description="Địa chỉ Email hoặc Số điện thoại nhận cảnh báo"
    )
    channel: str = Field(default="EMAIL", description="Kênh nhận: EMAIL hoặc SMS_ZALO")
    commodity_code: Optional[str] = Field(
        default=None, description="Mã nông sản quan tâm (để trống nếu nhận tất cả)"
    )
    province_code: Optional[str] = Field(
        default=None, description="Mã tỉnh/thành quan tâm (để trống nếu nhận tất cả)"
    )

    @field_validator("contact_info")
    @classmethod
    def validate_contact_info(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Thông tin liên hệ không được để trống.")
        return cleaned


class PipelineRunRequest(BaseModel):
    """Payload kích hoạt chạy pipeline thủ công (FR-28)."""

    mode: str = Field(
        default="fast_update",
        description="Chế độ chạy: 'fast_update' (kiểm tra nhanh & đánh giá cảnh báo) hoặc 'full_refresh'",
    )
    commodity_code: Optional[str] = Field(default=None, description="Mã nông sản cần cập nhật (tùy chọn)")
    province_code: Optional[str] = Field(default=None, description="Mã tỉnh cần cập nhật (tùy chọn)")


class FarmerSummarySchema(BaseModel):
    """Schema tóm tắt ngôn ngữ tự nhiên cho nông dân lớn tuổi (FR-49, FR-50, FR-51)."""

    commodity_name: str
    province_name: str
    horizon_days: int
    current_price: float
    target_price: float
    trend_direction: str
    trend_label_vi: str
    change_amount: float
    change_pct: float
    headline_vi: str
    action_hint_vi: str
    confidence_level: str
    confidence_label_vi: str
    confidence_explanation_vi: str
    badge_color: str
    disclaimer_vi: str


class InsufficientDataResponse(BaseModel):
    """Phản hồi chuẩn khi tỉnh được chọn chưa đủ dữ liệu lịch sử cho mặt hàng (FR-37)."""

    status: str = "INSUFFICIENT_DATA"
    commodity_code: str
    commodity_name: str
    province_code: str
    province_name: str
    message_vi: str
    supported_provinces: List[Dict[str, Any]]

