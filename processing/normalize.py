"""Normalization utilities for agricultural price forecasting system (FR-07, FR-33)."""

from typing import Optional
import unicodedata
from sqlalchemy.orm import Session
from sqlalchemy import func
from db.models import Province, ProvinceAlias


def remove_vietnamese_accents(text: str) -> str:
    """Loại bỏ dấu tiếng Việt để so khớp tương đối khi cần."""
    if not text:
        return ""
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return text.replace("đ", "d").replace("Đ", "D")


def clean_string(val: Optional[str]) -> str:
    """Chuẩn hóa chuỗi ký tự cơ bản: loại bỏ khoảng trắng thừa, chuẩn hóa Unicode NFC."""
    if not val:
        return ""
    text = unicodedata.normalize("NFC", str(val).strip())
    # Gộp nhiều khoảng trắng liền kề
    return " ".join(text.split())


def resolve_province_by_name_or_alias(
    input_name: str,
    db: Session
) -> Optional[Province]:
    """
    Chuẩn hóa và ánh xạ tên tỉnh từ nguồn thu thập về bản ghi Province chuẩn (FR-33).
    Hỗ trợ:
    1. So khớp chính xác tên chuẩn (standard_name) hoặc mã tỉnh (code).
    2. So khớp alias_name trong bảng province_alias (không phân biệt hoa thường).
    3. Thử nghiệm chuẩn hóa dấu tiếng Việt nếu chưa tìm thấy.
    """
    cleaned = clean_string(input_name)
    if not cleaned:
        return None

    # 1. So khớp với code hoặc standard_name trong Province
    province = db.query(Province).filter(
        (func.lower(Province.code) == cleaned.lower()) |
        (func.lower(Province.standard_name) == cleaned.lower())
    ).first()
    if province:
        return province

    # 2. So khớp với alias_name trong ProvinceAlias (case-insensitive)
    alias_match = db.query(ProvinceAlias).filter(
        func.lower(ProvinceAlias.alias_name) == cleaned.lower()
    ).first()
    if alias_match:
        return alias_match.province

    # 3. So khớp không dấu / biến thể viết tắt (ví dụ BR-VT, Lam Dong)
    cleaned_no_accents = remove_vietnamese_accents(cleaned).lower()
    all_aliases = db.query(ProvinceAlias).all()
    for alias in all_aliases:
        alias_no_accents = remove_vietnamese_accents(alias.alias_name).lower()
        if cleaned_no_accents == alias_no_accents:
            return alias.province

    all_provinces = db.query(Province).all()
    for prov in all_provinces:
        prov_no_accents = remove_vietnamese_accents(prov.standard_name).lower()
        if cleaned_no_accents == prov_no_accents:
            return prov

    return None

