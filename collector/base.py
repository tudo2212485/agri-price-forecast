"""Base Collector: Retry, Rate-Limiting, robots.txt Compliance, Pipeline Logger & Idempotent Upsert.

Tuân thủ tài liệu SRS v1.1:
- NFR-02 & FR-04: Tự động thử lại tối thiểu 3 lần với exponential backoff; lỗi 1 nguồn không dừng nguồn khác.
- NFR-06: Kiểm tra và tôn trọng robots.txt, giới hạn tần suất request (rate limit), User-Agent minh bạch.
- FR-05: Tự động ghi log tiến trình vào bảng pipeline_log.
- FR-04 & Mục 4.2: Idempotent Upsert dựa trên UniqueConstraint uq_price_obs_key và uq_weather_obs_key.
"""

import time
import logging
from abc import ABC
from contextlib import contextmanager
from datetime import datetime
from typing import Optional, Dict, Any, List, Callable, Generator
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from db.database import get_vietnam_now
from db.models import PipelineLog, PriceObservation, WeatherObservation

logger = logging.getLogger(__name__)


class PipelineRunTracker:
    """Đối tượng theo dõi số lượng bản ghi xử lý trong một phiên chạy pipeline."""

    def __init__(self, log_entry: PipelineLog):
        self.log_entry = log_entry
        self.records_processed: int = 0

    def add_records(self, count: int) -> None:
        self.records_processed += count
        self.log_entry.records_processed = self.records_processed


class BaseCollector(ABC):
    """
    Lớp cơ sở cho toàn bộ các bộ thu thập dữ liệu (Giá nông sản & Thời tiết).
    Cung cấp:
    - HTTP Client có Retry + Exponential Backoff
    - Kiểm tra robots.txt & Rate-limiting
    - Ghi log tự động vào bảng pipeline_log
    - Upsert Idempotent cho price_observation và weather_observation
    """

    DEFAULT_USER_AGENT = (
        "AgriPriceForecastBot/1.1 "
        "(Graduation Thesis Research Project; +https://github.com/agri-price-forecast; contact: research@agri-forecast.vn)"
    )

    def __init__(
        self,
        db: Session,
        source_id: Optional[int] = None,
        rate_limit_delay: float = 0.2,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
        timeout: int = 15,
        respect_robots: bool = True,
    ):
        self.db = db
        self.source_id = source_id
        self.rate_limit_delay = rate_limit_delay
        self.max_retries = max(1, max_retries)
        self.backoff_factor = backoff_factor
        self.timeout = timeout
        self.respect_robots = respect_robots

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json,*/*;q=0.8",
            "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
        })
        self._robots_cache: Dict[str, Optional[RobotFileParser]] = {}

    def is_allowed_by_robots(self, url: str) -> bool:
        """
        Kiểm tra quyền truy cập URL theo file robots.txt của tên miền nguồn (NFR-06).
        Nếu website không có robots.txt hoặc không phản hồi, mặc định cho phép truy cập hợp lệ.
        """
        if not self.respect_robots:
            return True

        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return True

        base_domain = f"{parsed.scheme}://{parsed.netloc}"
        if base_domain not in self._robots_cache:
            robots_url = f"{base_domain}/robots.txt"
            rp = RobotFileParser()
            try:
                resp = self.session.get(robots_url, timeout=5)
                if resp.status_code == 200:
                    rp.parse(resp.text.splitlines())
                    self._robots_cache[base_domain] = rp
                else:
                    self._robots_cache[base_domain] = None
            except Exception:
                self._robots_cache[base_domain] = None

        rp = self._robots_cache.get(base_domain)
        if rp is None:
            return True
        return rp.can_fetch(self.DEFAULT_USER_AGENT, url)

    def execute_with_retry(
        self,
        func: Callable[..., Any],
        *args: Any,
        max_retries: Optional[int] = None,
        backoff_factor: Optional[float] = None,
        **kwargs: Any,
    ) -> Any:
        """
        Thực thi một hàm bất kỳ với cơ chế tự động thử lại tối thiểu 3 lần (NFR-02, FR-04)
        kèm thời gian chờ tăng theo cấp số nhân (Exponential Backoff).
        """
        retries = max_retries if max_retries is not None else self.max_retries
        backoff = backoff_factor if backoff_factor is not None else self.backoff_factor
        last_exception: Optional[Exception] = None

        for attempt in range(1, retries + 1):
            try:
                return func(*args, **kwargs)
            except Exception as exc:
                last_exception = exc
                logger.warning(
                    f"[Retry {attempt}/{retries}] Lỗi khi thực thi {getattr(func, '__name__', str(func))}: {exc}"
                )
                if attempt < retries:
                    sleep_time = backoff * (2 ** (attempt - 1))
                    if sleep_time > 0:
                        time.sleep(sleep_time)

        assert last_exception is not None
        raise last_exception

    def fetch_url(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        max_retries: Optional[int] = None,
    ) -> requests.Response:
        """
        Gửi HTTP GET request có kiểm tra robots.txt, rate-limit delay và retry tự động.
        """
        if not self.is_allowed_by_robots(url):
            raise PermissionError(f"Truy cập tới URL '{url}' bị từ chối bởi quy tắc robots.txt (NFR-06).")

        if self.rate_limit_delay > 0:
            time.sleep(self.rate_limit_delay)

        def _do_request() -> requests.Response:
            response = self.session.get(
                url,
                params=params,
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response

        return self.execute_with_retry(_do_request, max_retries=max_retries)

    @contextmanager
    def log_pipeline_run(
        self,
        task_name: str,
        source_id: Optional[int] = None,
        raise_on_error: bool = True,
    ) -> Generator[PipelineRunTracker, None, None]:
        """
        Context manager tự động khởi tạo và cập nhật bản ghi trong bảng pipeline_log (FR-05).
        - Khi bắt đầu: tạo bản ghi trạng thái RUNNING.
        - Khi kết thúc thành công: cập nhật trạng thái SUCCESS, finished_at, records_processed.
        - Khi gặp ngoại lệ: cập nhật trạng thái FAILED, finished_at, error_message.
          Nếu raise_on_error=False, nuốt lỗi để một nguồn lỗi không làm dừng các nguồn khác (NFR-02).
        """
        effective_source_id = source_id if source_id is not None else self.source_id
        log_entry = PipelineLog(
            task_name=task_name,
            source_id=effective_source_id,
            started_at=get_vietnam_now(),
            status="RUNNING",
            records_processed=0,
        )
        self.db.add(log_entry)
        self.db.commit()
        self.db.refresh(log_entry)

        tracker = PipelineRunTracker(log_entry)
        try:
            yield tracker
            log_entry.status = "SUCCESS"
            log_entry.finished_at = get_vietnam_now()
            log_entry.records_processed = tracker.records_processed
            self.db.commit()
        except Exception as exc:
            self.db.rollback()
            # Đảm bảo bản ghi log được cập nhật trạng thái FAILED sau khi rollback transaction lỗi
            persisted_log = self.db.query(PipelineLog).filter(PipelineLog.id == log_entry.id).first()
            if persisted_log is None:
                persisted_log = PipelineLog(
                    task_name=task_name,
                    source_id=effective_source_id,
                    started_at=log_entry.started_at,
                )
                self.db.add(persisted_log)
            persisted_log.status = "FAILED"
            persisted_log.finished_at = get_vietnam_now()
            persisted_log.records_processed = tracker.records_processed
            persisted_log.error_message = str(exc)
            self.db.commit()
            if raise_on_error:
                raise

    def upsert_price_observations(
        self,
        records: List[Dict[str, Any]],
        batch_size: int = 500,
    ) -> int:
        """
        Idempotent Upsert danh sách bản ghi giá vào bảng price_observation (FR-04, Mục 4.2).
        Sử dụng ON CONFLICT DO UPDATE trên khóa duy nhất ('obs_date', 'commodity_id', 'province_id', 'source_id').
        Hỗ trợ tương thích cả PostgreSQL/TimescaleDB và SQLite (phục vụ Unit Test).
        """
        if not records:
            return 0

        dialect_name = self.db.bind.dialect.name if self.db.bind is not None else "postgresql"
        insert_fn = sqlite_insert if dialect_name == "sqlite" else pg_insert

        now = get_vietnam_now()
        total_upserted = 0

        # Khử trùng lặp ngay trong cùng 1 batch nếu có để tránh lỗi CardinalityViolation của PostgreSQL
        deduped_map: Dict[tuple, Dict[str, Any]] = {}
        for rec in records:
            key = (rec["obs_date"], rec["commodity_id"], rec["province_id"], rec["source_id"])
            row = {
                "obs_date": rec["obs_date"],
                "commodity_id": rec["commodity_id"],
                "province_id": rec["province_id"],
                "source_id": rec["source_id"],
                "price": rec["price"],
                "raw_value": str(rec["raw_value"]),
                "raw_unit": str(rec["raw_unit"]),
                "source_url": str(rec["source_url"]),
                "is_interpolated": bool(rec.get("is_interpolated", False)),
                "quality_flag": str(rec.get("quality_flag", "OK")),
                "review_flag": bool(rec.get("review_flag", False)),
                "collected_at": rec.get("collected_at", now),
            }
            deduped_map[key] = row

        clean_records = list(deduped_map.values())

        for i in range(0, len(clean_records), batch_size):
            batch = clean_records[i : i + batch_size]
            stmt = insert_fn(PriceObservation).values(batch)
            stmt = stmt.on_conflict_do_update(
                index_elements=["obs_date", "commodity_id", "province_id", "source_id"],
                set_={
                    "price": stmt.excluded.price,
                    "raw_value": stmt.excluded.raw_value,
                    "raw_unit": stmt.excluded.raw_unit,
                    "source_url": stmt.excluded.source_url,
                    "is_interpolated": stmt.excluded.is_interpolated,
                    "quality_flag": stmt.excluded.quality_flag,
                    "review_flag": stmt.excluded.review_flag,
                    "collected_at": stmt.excluded.collected_at,
                },
            )
            self.db.execute(stmt)
            total_upserted += len(batch)

        self.db.commit()
        return total_upserted

    def upsert_weather_observations(
        self,
        records: List[Dict[str, Any]],
        batch_size: int = 500,
    ) -> int:
        """
        Idempotent Upsert danh sách bản ghi thời tiết vào bảng weather_observation (FR-03, FR-04).
        Sử dụng ON CONFLICT DO UPDATE trên khóa duy nhất ('obs_date', 'province_id', 'source_id').
        """
        if not records:
            return 0

        dialect_name = self.db.bind.dialect.name if self.db.bind is not None else "postgresql"
        insert_fn = sqlite_insert if dialect_name == "sqlite" else pg_insert

        now = get_vietnam_now()
        total_upserted = 0

        deduped_map: Dict[tuple, Dict[str, Any]] = {}
        for rec in records:
            key = (rec["obs_date"], rec["province_id"], rec["source_id"])
            row = {
                "obs_date": rec["obs_date"],
                "province_id": rec["province_id"],
                "source_id": rec["source_id"],
                "temp_max": rec.get("temp_max"),
                "temp_min": rec.get("temp_min"),
                "temp_mean": rec.get("temp_mean"),
                "precipitation": rec.get("precipitation"),
                "humidity": rec.get("humidity"),
                "collected_at": rec.get("collected_at", now),
            }
            deduped_map[key] = row

        clean_records = list(deduped_map.values())

        for i in range(0, len(clean_records), batch_size):
            batch = clean_records[i : i + batch_size]
            stmt = insert_fn(WeatherObservation).values(batch)
            stmt = stmt.on_conflict_do_update(
                index_elements=["obs_date", "province_id", "source_id"],
                set_={
                    "temp_max": stmt.excluded.temp_max,
                    "temp_min": stmt.excluded.temp_min,
                    "temp_mean": stmt.excluded.temp_mean,
                    "precipitation": stmt.excluded.precipitation,
                    "humidity": stmt.excluded.humidity,
                    "collected_at": stmt.excluded.collected_at,
                },
            )
            self.db.execute(stmt)
            total_upserted += len(batch)

        self.db.commit()
        return total_upserted

