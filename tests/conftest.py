"""Pytest fixtures for Phase 1 Database and Architecture tests."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool
from db.database import Base
from scripts.init_db import seed_master_data


@pytest.fixture(scope="function")
def db_session() -> Session:
    """
    Tạo DB session biệt lập trong bộ nhớ (SQLite in-memory) cho mỗi test case.
    Đảm bảo test chạy cực nhanh, độc lập và tự dọn dẹp sau khi chạy xong.
    """
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=test_engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    
    session = TestingSessionLocal()
    # Seed master data sẵn sàng cho kiểm thử
    seed_master_data(session)
    
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        Base.metadata.drop_all(bind=test_engine)

