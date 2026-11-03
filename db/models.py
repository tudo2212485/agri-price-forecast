"""SQLAlchemy 2.0 ORM Models for Agricultural Price Forecasting System (SRS v1.1).

Covers all 13 core entities specified in Section 4.1, 4.2 and 4.3:
1. province
2. province_alias
3. commodity
4. data_source
5. price_observation
6. weather_observation
7. backfill_job
8. model_run
9. forecast
10. alert_rule
11. alert_event
12. subscriber
13. pipeline_log
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Optional, List, Any
from sqlalchemy import (
    Integer,
    BigInteger,
    String,
    Float,
    Numeric,
    Date,
    DateTime,
    Boolean,
    Text,
    JSON,
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from db.database import Base, get_vietnam_now


# ==============================================================================
# 1. Bảng province (Section 4.3, FR-33)
# ==============================================================================
class Province(Base):
    __tablename__ = "province"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    standard_name: Mapped[str] = mapped_column(String(100), nullable=False)
    region: Mapped[str] = mapped_column(String(50), nullable=False)  # Tây Nguyên, Đông Nam Bộ, ĐBSCL
    lat: Mapped[float] = mapped_column(Float, nullable=False)  # Vĩ độ đại diện lấy thời tiết
    lon: Mapped[float] = mapped_column(Float, nullable=False)  # Kinh độ đại diện lấy thời tiết

    # Relationships
    aliases: Mapped[List["ProvinceAlias"]] = relationship(
        "ProvinceAlias", back_populates="province", cascade="all, delete-orphan"
    )
    price_observations: Mapped[List["PriceObservation"]] = relationship(
        "PriceObservation", back_populates="province"
    )
    weather_observations: Mapped[List["WeatherObservation"]] = relationship(
        "WeatherObservation", back_populates="province"
    )
    backfill_jobs: Mapped[List["BackfillJob"]] = relationship(
        "BackfillJob", back_populates="province"
    )
    model_runs: Mapped[List["ModelRun"]] = relationship(
        "ModelRun", back_populates="province"
    )
    forecasts: Mapped[List["Forecast"]] = relationship(
        "Forecast", back_populates="province"
    )
    alert_rules: Mapped[List["AlertRule"]] = relationship(
        "AlertRule", back_populates="province"
    )
    alert_events: Mapped[List["AlertEvent"]] = relationship(
        "AlertEvent", back_populates="province"
    )
    subscribers: Mapped[List["Subscriber"]] = relationship(
        "Subscriber", back_populates="province"
    )

    def __repr__(self) -> str:
        return f"<Province(code='{self.code}', standard_name='{self.standard_name}', region='{self.region}')>"


# ==============================================================================
# 2. Bảng province_alias (Section 4.3, FR-33)
# ==============================================================================
class ProvinceAlias(Base):
    __tablename__ = "province_alias"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    alias_name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    province_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("province.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Relationships
    province: Mapped["Province"] = relationship("Province", back_populates="aliases")

    def __repr__(self) -> str:
        return f"<ProvinceAlias(alias='{self.alias_name}', province_id={self.province_id})>"


# ==============================================================================
# 3. Bảng commodity (Section 4.1)
# ==============================================================================
class Commodity(Base):
    __tablename__ = "commodity"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    unit: Mapped[str] = mapped_column(String(50), default="VNĐ/kg", nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)  # Cây công nghiệp, Lương thực

    # Relationships
    price_observations: Mapped[List["PriceObservation"]] = relationship(
        "PriceObservation", back_populates="commodity"
    )
    backfill_jobs: Mapped[List["BackfillJob"]] = relationship(
        "BackfillJob", back_populates="commodity"
    )
    model_runs: Mapped[List["ModelRun"]] = relationship(
        "ModelRun", back_populates="commodity"
    )
    forecasts: Mapped[List["Forecast"]] = relationship(
        "Forecast", back_populates="commodity"
    )
    alert_rules: Mapped[List["AlertRule"]] = relationship(
        "AlertRule", back_populates="commodity"
    )
    alert_events: Mapped[List["AlertEvent"]] = relationship(
        "AlertEvent", back_populates="commodity"
    )
    subscribers: Mapped[List["Subscriber"]] = relationship(
        "Subscriber", back_populates="commodity"
    )

    def __repr__(self) -> str:
        return f"<Commodity(code='{self.code}', name='{self.name}', category='{self.category}')>"


# ==============================================================================
# 4. Bảng data_source (Section 4.1, 4.3, FR-01, FR-31)
# ==============================================================================
class DataSource(Base):
    __tablename__ = "data_source"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    publisher: Mapped[str] = mapped_column(String(255), nullable=False)  # Đơn vị công bố
    url_or_api: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)  # 'PRICE' hoặc 'WEATHER'
    price_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)  # 'Thu mua tại vườn', 'Bán buôn', etc.
    raw_unit: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    frequency: Mapped[str] = mapped_column(String(50), default="DAILY", nullable=False)  # 'DAILY'
    reliability_level: Mapped[str] = mapped_column(String(20), default="HIGH", nullable=False)  # 'HIGH', 'MEDIUM'
    terms_of_use: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    price_observations: Mapped[List["PriceObservation"]] = relationship(
        "PriceObservation", back_populates="source"
    )
    weather_observations: Mapped[List["WeatherObservation"]] = relationship(
        "WeatherObservation", back_populates="source"
    )
    backfill_jobs: Mapped[List["BackfillJob"]] = relationship(
        "BackfillJob", back_populates="source"
    )
    pipeline_logs: Mapped[List["PipelineLog"]] = relationship(
        "PipelineLog", back_populates="source"
    )

    def __repr__(self) -> str:
        return f"<DataSource(name='{self.name}', source_type='{self.source_type}', reliability='{self.reliability_level}')>"


# ==============================================================================
# 5. Bảng price_observation (Section 4.1, 4.2, 4.3, FR-02, FR-04, FR-32, FR-35, FR-36)
# ==============================================================================
class PriceObservation(Base):
    __tablename__ = "price_observation"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    obs_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    commodity_id: Mapped[int] = mapped_column(Integer, ForeignKey("commodity.id"), nullable=False, index=True)
    province_id: Mapped[int] = mapped_column(Integer, ForeignKey("province.id"), nullable=False, index=True)
    source_id: Mapped[int] = mapped_column(Integer, ForeignKey("data_source.id"), nullable=False, index=True)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)  # Đã chuẩn hóa về VNĐ/kg
    raw_value: Mapped[str] = mapped_column(String(100), nullable=False)  # Giá trị gốc trước chuẩn hóa (FR-32)
    raw_unit: Mapped[str] = mapped_column(String(50), nullable=False)  # Đơn vị gốc trước chuẩn hóa (FR-32)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)  # URL cụ thể nơi thu thập (FR-32, NFR-14)
    is_interpolated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)  # Cờ nội suy (FR-36)
    quality_flag: Mapped[str] = mapped_column(String(20), default="OK", nullable=False)  # 'OK', 'OUTLIER', 'INTERPOLATED', 'INVALID'
    review_flag: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)  # Cảnh báo đối chiếu chéo lệch vượt ngưỡng (FR-35)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=get_vietnam_now, nullable=False)

    # Ràng buộc Unique bắt buộc để chạy lặp lại không sinh bản ghi trùng (Mục 4.2 & 4.3, FR-04)
    __table_args__ = (
        UniqueConstraint("obs_date", "commodity_id", "province_id", "source_id", name="uq_price_obs_key"),
    )

    # Relationships
    commodity: Mapped["Commodity"] = relationship("Commodity", back_populates="price_observations")
    province: Mapped["Province"] = relationship("Province", back_populates="price_observations")
    source: Mapped["DataSource"] = relationship("DataSource", back_populates="price_observations")

    def __repr__(self) -> str:
        return f"<PriceObservation(date={self.obs_date}, commodity_id={self.commodity_id}, province_id={self.province_id}, price={self.price})>"


# ==============================================================================
# 6. Bảng weather_observation (Section 4.1, 4.3, FR-03)
# ==============================================================================
class WeatherObservation(Base):
    __tablename__ = "weather_observation"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    obs_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    province_id: Mapped[int] = mapped_column(Integer, ForeignKey("province.id"), nullable=False, index=True)
    source_id: Mapped[int] = mapped_column(Integer, ForeignKey("data_source.id"), nullable=False, index=True)
    temp_max: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    temp_min: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    temp_mean: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    precipitation: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # Lượng mưa mm
    humidity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # Độ ẩm %
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=get_vietnam_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("obs_date", "province_id", "source_id", name="uq_weather_obs_key"),
    )

    # Relationships
    province: Mapped["Province"] = relationship("Province", back_populates="weather_observations")
    source: Mapped["DataSource"] = relationship("DataSource", back_populates="weather_observations")

    def __repr__(self) -> str:
        return f"<WeatherObservation(date={self.obs_date}, province_id={self.province_id}, temp={self.temp_mean}, precip={self.precipitation})>"


# ==============================================================================
# 7. Bảng backfill_job (Section 4.3, FR-40, FR-41)
# ==============================================================================
class BackfillJob(Base):
    __tablename__ = "backfill_job"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(Integer, ForeignKey("data_source.id"), nullable=False)
    commodity_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("commodity.id"), nullable=True)  # Nullable nếu là thời tiết
    province_id: Mapped[int] = mapped_column(Integer, ForeignKey("province.id"), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    last_completed_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)  # Mốc checkpoint để tiếp tục khi gián đoạn
    status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)  # 'PENDING', 'RUNNING', 'COMPLETED', 'FAILED'
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=get_vietnam_now, onupdate=get_vietnam_now, nullable=False
    )

    # Relationships
    source: Mapped["DataSource"] = relationship("DataSource", back_populates="backfill_jobs")
    commodity: Mapped[Optional["Commodity"]] = relationship("Commodity", back_populates="backfill_jobs")
    province: Mapped["Province"] = relationship("Province", back_populates="backfill_jobs")

    def __repr__(self) -> str:
        return f"<BackfillJob(id={self.id}, source_id={self.source_id}, status='{self.status}', checkpoint={self.last_completed_date})>"


# ==============================================================================
# 8. Bảng model_run (Section 4.1, 4.3, FR-16, FR-46)
# ==============================================================================
class ModelRun(Base):
    __tablename__ = "model_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    commodity_id: Mapped[int] = mapped_column(Integer, ForeignKey("commodity.id"), nullable=False)
    province_id: Mapped[int] = mapped_column(Integer, ForeignKey("province.id"), nullable=False)
    model_type: Mapped[str] = mapped_column(String(50), nullable=False)  # 'NAIVE', 'SEASONAL_NAIVE', 'MOVING_AVG', 'PROPHET', 'RANDOM_FOREST', 'XGBOOST', 'LSTM'
    hyperparameters: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    train_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    train_end_date: Mapped[date] = mapped_column(Date, nullable=False)
    test_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    test_end_date: Mapped[date] = mapped_column(Date, nullable=False)
    train_record_count: Mapped[int] = mapped_column(Integer, nullable=False)
    mae: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rmse: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    mape: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    artifact_path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_selected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)  # Đánh dấu mô hình tốt nhất đang được dùng dự báo
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=get_vietnam_now, nullable=False)

    # Relationships
    commodity: Mapped["Commodity"] = relationship("Commodity", back_populates="model_runs")
    province: Mapped["Province"] = relationship("Province", back_populates="model_runs")
    forecasts: Mapped[List["Forecast"]] = relationship("Forecast", back_populates="model_run")

    def __repr__(self) -> str:
        return f"<ModelRun(id={self.id}, type='{self.model_type}', mape={self.mape}, is_selected={self.is_selected})>"


# ==============================================================================
# 9. Bảng forecast (Section 4.1, 4.3, FR-17, FR-44)
# ==============================================================================
class Forecast(Base):
    __tablename__ = "forecast"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_run_id: Mapped[int] = mapped_column(Integer, ForeignKey("model_run.id"), nullable=False, index=True)
    commodity_id: Mapped[int] = mapped_column(Integer, ForeignKey("commodity.id"), nullable=False, index=True)
    province_id: Mapped[int] = mapped_column(Integer, ForeignKey("province.id"), nullable=False, index=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=get_vietnam_now, nullable=False)
    target_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    horizon: Mapped[int] = mapped_column(Integer, nullable=False)  # Từ 1 đến 30 ngày
    yhat: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)  # Giá trị dự báo
    lower_bound: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)  # Giới hạn dưới khoảng tin cậy
    upper_bound: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)  # Giới hạn trên khoảng tin cậy
    actual_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)  # Giá thực tế điền sau để backtesting (Section 4.3)

    # Relationships
    model_run: Mapped["ModelRun"] = relationship("ModelRun", back_populates="forecasts")
    commodity: Mapped["Commodity"] = relationship("Commodity", back_populates="forecasts")
    province: Mapped["Province"] = relationship("Province", back_populates="forecasts")

    def __repr__(self) -> str:
        return f"<Forecast(target_date={self.target_date}, horizon={self.horizon}, yhat={self.yhat})>"


# ==============================================================================
# 10. Bảng alert_rule (Section 4.1, 4.3, FR-24)
# ==============================================================================
class AlertRule(Base):
    __tablename__ = "alert_rule"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    commodity_id: Mapped[int] = mapped_column(Integer, ForeignKey("commodity.id"), nullable=False)
    province_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("province.id"), nullable=True)  # Nullable nếu áp dụng toàn quốc
    threshold_pct: Mapped[float] = mapped_column(Float, nullable=False)  # Ngưỡng % tăng/giảm (VD: 5.0)
    window_days: Mapped[int] = mapped_column(Integer, default=7, nullable=False)  # Cửa sổ N ngày dự báo
    channel: Mapped[str] = mapped_column(String(50), default="EMAIL", nullable=False)  # 'EMAIL', 'NOTIFICATION'
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    commodity: Mapped["Commodity"] = relationship("Commodity", back_populates="alert_rules")
    province: Mapped[Optional["Province"]] = relationship("Province", back_populates="alert_rules")
    events: Mapped[List["AlertEvent"]] = relationship("AlertEvent", back_populates="rule")

    def __repr__(self) -> str:
        return f"<AlertRule(commodity_id={self.commodity_id}, threshold={self.threshold_pct}%, window={self.window_days}d)>"


# ==============================================================================
# 11. Bảng alert_event (Section 4.1, FR-25, FR-26)
# ==============================================================================
class AlertEvent(Base):
    __tablename__ = "alert_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_id: Mapped[int] = mapped_column(Integer, ForeignKey("alert_rule.id"), nullable=False)
    commodity_id: Mapped[int] = mapped_column(Integer, ForeignKey("commodity.id"), nullable=False)
    province_id: Mapped[int] = mapped_column(Integer, ForeignKey("province.id"), nullable=False)
    target_date: Mapped[date] = mapped_column(Date, nullable=False)
    change_pct: Mapped[float] = mapped_column(Float, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    sent_status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)  # 'PENDING', 'SENT', 'FAILED'
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=get_vietnam_now, nullable=False)

    # UniqueConstraint tránh gửi trùng sự kiện cảnh báo (Section 3.5, FR-26)
    __table_args__ = (
        UniqueConstraint("rule_id", "target_date", name="uq_alert_event_rule_date"),
    )

    # Relationships
    rule: Mapped["AlertRule"] = relationship("AlertRule", back_populates="events")
    commodity: Mapped["Commodity"] = relationship("Commodity", back_populates="alert_events")
    province: Mapped["Province"] = relationship("Province", back_populates="alert_events")

    def __repr__(self) -> str:
        return f"<AlertEvent(id={self.id}, rule_id={self.rule_id}, change_pct={self.change_pct}%, status='{self.sent_status}')>"


# ==============================================================================
# 12. Bảng subscriber (Section 4.1, 4.3, FR-27, FR-53)
# ==============================================================================
class Subscriber(Base):
    __tablename__ = "subscriber"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contact_info: Mapped[str] = mapped_column(String(255), nullable=False)  # Email hoặc SĐT
    channel: Mapped[str] = mapped_column(String(50), default="EMAIL", nullable=False)  # 'EMAIL', 'SMS_ZALO'
    commodity_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("commodity.id"), nullable=True)
    province_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("province.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=get_vietnam_now, nullable=False)

    # Relationships
    commodity: Mapped[Optional["Commodity"]] = relationship("Commodity", back_populates="subscribers")
    province: Mapped[Optional["Province"]] = relationship("Province", back_populates="subscribers")

    def __repr__(self) -> str:
        return f"<Subscriber(contact='{self.contact_info}', channel='{self.channel}', active={self.is_active})>"


# ==============================================================================
# 13. Bảng pipeline_log (Section 4.1, FR-05)
# ==============================================================================
class PipelineLog(Base):
    __tablename__ = "pipeline_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_name: Mapped[str] = mapped_column(String(100), nullable=False)
    source_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("data_source.id"), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=get_vietnam_now, nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="RUNNING", nullable=False)  # 'RUNNING', 'SUCCESS', 'FAILED'
    records_processed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    source: Mapped[Optional["DataSource"]] = relationship("DataSource", back_populates="pipeline_logs")

    def __repr__(self) -> str:
        return f"<PipelineLog(task='{self.task_name}', status='{self.status}', records={self.records_processed})>"


# ==============================================================================
# 14. Bảng feature_set (Section 4.1, 4.3, FR-07, FR-08, FR-09, NFR-04)
# ==============================================================================
class FeatureSet(Base):
    __tablename__ = "feature_set"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    obs_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    commodity_id: Mapped[int] = mapped_column(Integer, ForeignKey("commodity.id"), nullable=False, index=True)
    province_id: Mapped[int] = mapped_column(Integer, ForeignKey("province.id"), nullable=False, index=True)

    # Giá & Cờ truy vết sau làm sạch / nội suy
    price: Mapped[float] = mapped_column(Float, nullable=False)
    is_interpolated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    quality_flag: Mapped[str] = mapped_column(String(20), default="OK", nullable=False)

    # Biến ngoại sinh thời tiết & tích lũy (FR-03, FR-07, FR-09)
    temp_max: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    temp_min: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    temp_mean: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    precipitation: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    humidity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    precip_sum_7d: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    precip_sum_30d: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    temp_mean_7d: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Đặc trưng trễ của giá (Lag features - FR-09)
    lag_1: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lag_2: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lag_3: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lag_7: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lag_14: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lag_21: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lag_30: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Đặc trưng trượt & biến động phần trăm (Rolling features - FR-09, NFR-04)
    rolling_mean_7: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rolling_std_7: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rolling_mean_14: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rolling_std_14: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rolling_mean_30: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rolling_std_30: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pct_change_1d: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pct_change_7d: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Đặc trưng lịch & mùa vụ (Calendar & Seasonality - FR-09)
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)
    day_of_month: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    quarter: Mapped[int] = mapped_column(Integer, nullable=False)
    day_of_year: Mapped[int] = mapped_column(Integer, nullable=False)
    sin_day_of_year: Mapped[float] = mapped_column(Float, nullable=False)
    cos_day_of_year: Mapped[float] = mapped_column(Float, nullable=False)
    is_harvest_season: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=get_vietnam_now, onupdate=get_vietnam_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("obs_date", "commodity_id", "province_id", name="uq_feature_set_key"),
    )

    def __repr__(self) -> str:
        return (
            f"<FeatureSet(date={self.obs_date}, commodity_id={self.commodity_id}, "
            f"province_id={self.province_id}, price={self.price})>"
        )
