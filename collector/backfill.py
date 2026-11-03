"""Historical Data Backfill Manager with Batching & Checkpoint Recovery (FR-40, FR-41, Mục 4.3).

Quản lý bảng backfill_job:
- Chia khoảng thời gian thu thập (tối thiểu 3 năm: 2023-2026) thành các lô (batches) theo tháng/quý/năm.
- Sau mỗi lô thành công, lưu mốc checkpoint vào cột last_completed_date và cập nhật status = 'RUNNING'.
- Hỗ trợ resume_backfill(): khi tiến trình bị ngắt quãng, tự động đọc last_completed_date
  và chạy tiếp từ ngày kế tiếp (last_completed_date + 1 ngày) đến end_date mà không sinh bản ghi trùng.
"""

import logging
from datetime import date, timedelta
from typing import List, Dict, Any, Optional, Tuple

from sqlalchemy.orm import Session

from collector.price_collector import AgriPriceCollector, TARGET_COMMODITY_PROVINCES
from collector.weather_collector import OpenMeteoWeatherCollector
from db.database import get_vietnam_now
from db.models import BackfillJob, Commodity, Province, DataSource

logger = logging.getLogger(__name__)


def split_date_range_into_batches(
    start_date: date,
    end_date: date,
    batch_days: int = 90,
) -> List[Tuple[date, date]]:
    """Chia khoảng ngày [start_date, end_date] thành danh sách các lô (batch_start, batch_end)."""
    if start_date > end_date:
        return []
    batches: List[Tuple[date, date]] = []
    cur_start = start_date
    step = max(1, batch_days) - 1
    while cur_start <= end_date:
        cur_end = min(end_date, cur_start + timedelta(days=step))
        batches.append((cur_start, cur_end))
        cur_start = cur_end + timedelta(days=1)
    return batches


class BackfillManager:
    """
    Điều phối nạp bù dữ liệu lịch sử (Backfill) theo lô có lưu vết Checkpoint (FR-40, FR-41).
    Hỗ trợ cả Giá nông sản (PRICE) và Thời tiết (WEATHER).
    """

    def __init__(
        self,
        db: Session,
        price_collector: Optional[AgriPriceCollector] = None,
        weather_collector: Optional[OpenMeteoWeatherCollector] = None,
    ):
        self.db = db
        self.price_collector = price_collector or AgriPriceCollector(db=db, rate_limit_delay=0.0)
        self.weather_collector = weather_collector or OpenMeteoWeatherCollector(db=db, rate_limit_delay=0.1)

    def create_or_get_job(
        self,
        source_id: int,
        province_id: int,
        start_date: date,
        end_date: date,
        commodity_id: Optional[int] = None,
    ) -> BackfillJob:
        """Tìm hoặc tạo mới một bản ghi BackfillJob cho cặp (source, commodity, province, start_date, end_date)."""
        query = self.db.query(BackfillJob).filter(
            BackfillJob.source_id == source_id,
            BackfillJob.province_id == province_id,
            BackfillJob.start_date == start_date,
            BackfillJob.end_date == end_date,
        )
        if commodity_id is not None:
            query = query.filter(BackfillJob.commodity_id == commodity_id)
        else:
            query = query.filter(BackfillJob.commodity_id.is_(None))

        job = query.first()
        if not job:
            job = BackfillJob(
                source_id=source_id,
                commodity_id=commodity_id,
                province_id=province_id,
                start_date=start_date,
                end_date=end_date,
                last_completed_date=None,
                status="PENDING",
                updated_at=get_vietnam_now(),
            )
            self.db.add(job)
            self.db.commit()
            self.db.refresh(job)
        return job

    def execute_job(
        self,
        job: BackfillJob,
        batch_days: int = 90,
        stop_after_batches: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Thực thi hoặc tiếp tục (resume) một BackfillJob theo từng lô.
        - Nếu job đã có last_completed_date, tự động chạy từ (last_completed_date + 1 ngày).
        - Tham số stop_after_batches hỗ trợ kiểm thử mô phỏng gián đoạn giữa chừng (FR-41).
        """
        if job.status == "COMPLETED" and job.last_completed_date and job.last_completed_date >= job.end_date:
            return {
                "job_id": job.id,
                "status": job.status,
                "batches_run": 0,
                "records_upserted": 0,
                "last_completed_date": job.last_completed_date,
            }

        # Xác định ngày bắt đầu thực tế dựa vào checkpoint last_completed_date
        if job.last_completed_date is not None:
            effective_start = job.last_completed_date + timedelta(days=1)
        else:
            effective_start = job.start_date

        if effective_start > job.end_date:
            job.status = "COMPLETED"
            job.last_completed_date = job.end_date
            job.updated_at = get_vietnam_now()
            self.db.commit()
            return {
                "job_id": job.id,
                "status": job.status,
                "batches_run": 0,
                "records_upserted": 0,
                "last_completed_date": job.last_completed_date,
            }

        batches = split_date_range_into_batches(effective_start, job.end_date, batch_days=batch_days)
        source = self.db.query(DataSource).filter(DataSource.id == job.source_id).first()
        province = self.db.query(Province).filter(Province.id == job.province_id).first()
        commodity = (
            self.db.query(Commodity).filter(Commodity.id == job.commodity_id).first()
            if job.commodity_id is not None
            else None
        )

        if not source or not province:
            job.status = "FAILED"
            job.updated_at = get_vietnam_now()
            self.db.commit()
            raise ValueError(f"BackfillJob #{job.id} thiếu thông tin source hoặc province hợp lệ.")

        job.status = "RUNNING"
        job.updated_at = get_vietnam_now()
        self.db.commit()

        batches_run = 0
        total_records = 0

        try:
            for batch_start, batch_end in batches:
                if source.source_type == "PRICE":
                    if not commodity:
                        raise ValueError(f"BackfillJob #{job.id} loại PRICE nhưng commodity_id là NULL.")
                    count = self.price_collector.collect_price_range(
                        start_date=batch_start,
                        end_date=batch_end,
                        commodity_code=commodity.code,
                        province_code=province.code,
                        log_pipeline=True,
                        source_id=source.id,
                    )
                else:
                    count = self.weather_collector.collect_province_weather(
                        province=province,
                        start_date=batch_start,
                        end_date=batch_end,
                        log_pipeline=True,
                    )

                total_records += count
                batches_run += 1

                # Cập nhật checkpoint sau mỗi lô thành công (FR-41)
                job.last_completed_date = batch_end
                job.status = "RUNNING"
                job.updated_at = get_vietnam_now()
                self.db.commit()

                if stop_after_batches is not None and batches_run >= stop_after_batches:
                    # Tạm dừng chủ động sau N batch (phục vụ kiểm thử gián đoạn hoặc giới hạn quota)
                    return {
                        "job_id": job.id,
                        "status": job.status,
                        "batches_run": batches_run,
                        "records_upserted": total_records,
                        "last_completed_date": job.last_completed_date,
                    }

            # Khi đã hoàn thành toàn bộ các lô đến end_date
            job.status = "COMPLETED"
            job.last_completed_date = job.end_date
            job.updated_at = get_vietnam_now()
            self.db.commit()

        except Exception:
            self.db.rollback()
            persisted_job = self.db.query(BackfillJob).filter(BackfillJob.id == job.id).first()
            if persisted_job:
                persisted_job.status = "FAILED"
                persisted_job.updated_at = get_vietnam_now()
                self.db.commit()
            raise

        return {
            "job_id": job.id,
            "status": job.status,
            "batches_run": batches_run,
            "records_upserted": total_records,
            "last_completed_date": job.last_completed_date,
        }

    def resume_backfill(
        self,
        job_id: Optional[int] = None,
        batch_days: int = 90,
    ) -> List[Dict[str, Any]]:
        """
        Tiếp tục thực thi các backfill_job đang dở dang (PENDING, RUNNING, FAILED)
        hoặc một job_id cụ thể từ mốc last_completed_date (FR-41).
        """
        query = self.db.query(BackfillJob)
        if job_id is not None:
            query = query.filter(BackfillJob.id == job_id)
        else:
            query = query.filter(BackfillJob.status.in_(["PENDING", "RUNNING", "FAILED"]))

        jobs = query.order_by(BackfillJob.id).all()
        results: List[Dict[str, Any]] = []
        for job in jobs:
            res = self.execute_job(job, batch_days=batch_days)
            results.append(res)
        return results

    def run_full_historical_backfill(
        self,
        start_date: date = date(2023, 1, 1),
        end_date: Optional[date] = None,
        price_batch_days: int = 365,
        weather_batch_days: int = 730,
        include_weather: bool = True,
    ) -> Dict[str, Any]:
        """
        Khởi tạo và chạy Backfill toàn bộ lịch sử 3+ năm (2023 -> hiện tại) cho:
        1. Cả 3 nông sản tại các tỉnh trọng điểm (11 chuỗi giá).
        2. Dữ liệu thời tiết thực tế từ Open-Meteo cho toàn bộ 8 tỉnh.
        """
        end_date = end_date or get_vietnam_now().date()
        commodities = {c.code: c for c in self.db.query(Commodity).all()}
        provinces = {p.code: p for p in self.db.query(Province).all()}
        price_sources = self.db.query(DataSource).filter(DataSource.source_type == "PRICE").all()

        def _match_source_for_commodity(comm_code: str) -> DataSource:
            for s in price_sources:
                if comm_code == "CAFE_ROBUSTA" and ("cà phê" in s.name.lower() or "vicofa" in s.name.lower()):
                    return s
                if comm_code == "TIEU_DEN" and ("tiêu" in s.name.lower() or "vpsa" in s.name.lower()):
                    return s
                if comm_code == "LUA_IR50404" and ("lúa" in s.name.lower() or "an giang" in s.name.lower()):
                    return s
            return price_sources[0]

        price_results: List[Dict[str, Any]] = []
        for comm_code, prov_codes in TARGET_COMMODITY_PROVINCES.items():
            comm = commodities.get(comm_code)
            if not comm:
                continue
            src = _match_source_for_commodity(comm_code)
            for p_code in prov_codes:
                prov = provinces.get(p_code)
                if not prov:
                    continue
                job = self.create_or_get_job(
                    source_id=src.id,
                    commodity_id=comm.id,
                    province_id=prov.id,
                    start_date=start_date,
                    end_date=end_date,
                )
                res = self.execute_job(job, batch_days=price_batch_days)
                price_results.append(res)

        weather_results: List[Dict[str, Any]] = []
        if include_weather:
            weather_src = self.weather_collector.source
            for p_code, prov in provinces.items():
                job = self.create_or_get_job(
                    source_id=weather_src.id,
                    commodity_id=None,
                    province_id=prov.id,
                    start_date=start_date,
                    end_date=end_date,
                )
                try:
                    res = self.execute_job(job, batch_days=weather_batch_days)
                    weather_results.append(res)
                except Exception as exc:
                    logger.warning(f"Lỗi khi backfill thời tiết tỉnh {p_code}: {exc}")

        return {
            "price_jobs_completed": len([r for r in price_results if r["status"] == "COMPLETED"]),
            "price_records_upserted": sum(r["records_upserted"] for r in price_results),
            "weather_jobs_completed": len([r for r in weather_results if r["status"] == "COMPLETED"]),
            "weather_records_upserted": sum(r["records_upserted"] for r in weather_results),
            "price_jobs": price_results,
            "weather_jobs": weather_results,
        }

