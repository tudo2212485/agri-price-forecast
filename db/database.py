"""Database connection, configuration and session management (Section 2.3, 4.1, 4.2)."""

import os
from datetime import datetime, timezone, timedelta
from typing import Generator
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session

# Tải cấu hình biến môi trường từ .env
load_dotenv()

# Múi giờ chuẩn thống nhất toàn hệ thống: UTC+7 (Asia/Ho_Chi_Minh) - Section 4.2
VIETNAM_TZ = timezone(timedelta(hours=7))


def get_vietnam_now() -> datetime:
    """Trả về thời gian hiện tại theo múi giờ chuẩn UTC+7 có tzinfo."""
    return datetime.now(VIETNAM_TZ)


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/agri_price_db"
)

# Cấu hình engine: pool_pre_ping kiểm tra kết nối sống trước khi sử dụng
is_postgres = "postgresql" in DATABASE_URL
connect_args = {}
if "sqlite" in DATABASE_URL:
    connect_args["check_same_thread"] = False

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=is_postgres,
    echo=False,
    connect_args=connect_args
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    expire_on_commit=False
)


class Base(DeclarativeBase):
    """SQLAlchemy 2.0 Declarative Base."""
    pass


def get_db() -> Generator[Session, None, None]:
    """Dependency cung cấp DB session cho FastAPI và các tác vụ nền."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

