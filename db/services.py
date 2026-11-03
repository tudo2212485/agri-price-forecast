"""Database service layer: Helper functions for seed data, metadata lookup and queries."""

from typing import Optional, List
from sqlalchemy.orm import Session
from db.models import Province, Commodity, DataSource, AlertRule


def get_all_provinces(db: Session) -> List[Province]:
    """Lấy danh sách tất cả các tỉnh thành."""
    return db.query(Province).order_by(Province.id).all()


def get_all_commodities(db: Session) -> List[Commodity]:
    """Lấy danh sách tất cả nông sản."""
    return db.query(Commodity).order_by(Commodity.id).all()


def get_all_sources(db: Session) -> List[DataSource]:
    """Lấy danh sách các nguồn dữ liệu."""
    return db.query(DataSource).order_by(DataSource.id).all()


def get_active_alert_rules(db: Session) -> List[AlertRule]:
    """Lấy danh sách các quy tắc cảnh báo đang hoạt động."""
    return db.query(AlertRule).filter(AlertRule.is_active.is_(True)).all()

