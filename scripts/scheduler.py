"""Automated Daily Pipeline Scheduler & Stability Monitor using Prefect / Loop (SRS v1.1 - FR-04, FR-18, FR-29).

Thực hiện:
1. Tác vụ thu thập & cập nhật dữ liệu hàng ngày (`daily_pipeline_update_task`).
2. Tác vụ giám sát độ ổn định phân phối dữ liệu và sai số mô hình (`stability_monitoring_task` - FR-29):
   - Phát hiện lệch phân phối dữ liệu (Data Drift) hoặc sai số dự báo tăng bất thường (Model Drift).
   - Tự động ghi kết quả giám sát vào bảng `pipeline_log`.
3. Tác vụ quét quy tắc cảnh báo và gửi thông báo không trùng lặp (`alert_evaluation_task` - FR-25, FR-26).

Cách chạy:
- Chạy 1 chu kỳ kiểm tra ngay lập tức: `python scripts/scheduler.py --once`
- Chạy vòng lặp lập lịch tự động hàng ngày: `python scripts/scheduler.py --interval-hours 24`
"""

import argparse
import os
import sys
import time
from typing import Dict, Any, Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import Session
from db.database import SessionLocal, get_vietnam_now
from api.pipeline_runner import PipelineOrchestrator, monitor_data_and_model_stability
from api.alert_service import evaluate_and_trigger_alerts

try:
    from prefect import flow, task
    PREFECT_AVAILABLE = True
except Exception:
    PREFECT_AVAILABLE = False

    def task(*args, **kwargs):
        def decorator(fn):
            return fn
        return decorator

    def flow(*args, **kwargs):
        def decorator(fn):
            return fn
        return decorator


@task(name="daily_pipeline_update_task", retries=2, retry_delay_seconds=5)
def daily_pipeline_update_task(mode: str = "fast_update", db: Optional[Session] = None) -> Dict[str, Any]:
    """Thực thi cập nhật pipeline định kỳ (FR-04, FR-18)."""
    own_session = db is None
    session = db or SessionLocal()
    try:
        orchestrator = PipelineOrchestrator(db=session)
        return orchestrator.trigger_manual_pipeline_run(mode=mode)
    finally:
        if own_session:
            session.close()


@task(name="stability_monitoring_task", retries=1)
def stability_monitoring_task(
    z_score_threshold: float = 2.5,
    mape_warning_threshold: float = 3.5,
    db: Optional[Session] = None,
) -> Dict[str, Any]:
    """Giám sát độ ổn định dữ liệu và sai số mô hình, ghi nhận vào `pipeline_log` (FR-29)."""
    own_session = db is None
    session = db or SessionLocal()
    try:
        return monitor_data_and_model_stability(
            db=session,
            z_score_threshold=z_score_threshold,
            mape_warning_threshold=mape_warning_threshold,
        )
    finally:
        if own_session:
            session.close()


@task(name="alert_evaluation_task", retries=1)
def alert_evaluation_task(db: Optional[Session] = None) -> Dict[str, Any]:
    """Đánh giá các quy tắc cảnh báo và gửi thông báo chống trùng lặp (FR-25, FR-26)."""
    own_session = db is None
    session = db or SessionLocal()
    try:
        return evaluate_and_trigger_alerts(db=session, force_check_all_thresholds=False)
    finally:
        if own_session:
            session.close()


@flow(name="agri_price_daily_scheduled_flow", log_prints=True)
def run_daily_scheduled_pipeline(
    mode: str = "fast_update",
    db: Optional[Session] = None,
) -> Dict[str, Any]:
    """
    Luồng điều phối tự động hàng ngày kết hợp Cập nhật Pipeline -> Giám sát Độ ổn định (FR-29) -> Cảnh báo.
    """
    started_at = get_vietnam_now().isoformat()
    pipeline_res = daily_pipeline_update_task(mode=mode, db=db)
    stability_res = stability_monitoring_task(db=db)
    alert_res = alert_evaluation_task(db=db)

    return {
        "flow_status": "COMPLETED",
        "prefect_enabled": PREFECT_AVAILABLE,
        "started_at": started_at,
        "finished_at": get_vietnam_now().isoformat(),
        "pipeline_update": pipeline_res,
        "stability_monitoring": stability_res,
        "alert_evaluation": alert_res,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bộ lập lịch tự động hàng ngày cho Hệ thống Dự báo Giá Nông sản (SRS v1.1)"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        default=True,
        help="Chạy 1 chu kỳ điều phối và giám sát rồi kết thúc (mặc định).",
    )
    parser.add_argument(
        "--continuous",
        action="store_true",
        default=False,
        help="Chạy vòng lặp lập lịch liên tục theo chu kỳ --interval-hours.",
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        default=False,
        help="Chạy nền liên tục (daemon mode) kiểm tra lịch hàng ngày.",
    )
    parser.add_argument(
        "--interval-hours",
        type=float,
        default=24.0,
        help="Khoảng cách giờ giữa 2 lần chạy tự động (mặc định: 24 giờ).",
    )
    parser.add_argument(
        "--mode",
        type=str,
        default="fast_update",
        choices=["fast_update", "full_refresh"],
        help="Chế độ cập nhật pipeline.",
    )
    args = parser.parse_args()

    print("=" * 90)
    print("KHỞI ĐỘNG BỘ LẬP LỊCH TỰ ĐỘNG & GIÁM SÁT ĐỘ ỔN ĐỊNH MÔ HÌNH (SRS v1.1 - FR-04, FR-29)")
    print("=" * 90)

    if not (args.continuous or args.daemon):
        summary = run_daily_scheduled_pipeline(mode=args.mode)
        stab = summary["stability_monitoring"]
        print(f"- Trạng thái luồng        : {summary['flow_status']}")
        print(f"- Số chuỗi giám sát Drift : {stab['series_checked']} chuỗi")
        print(f"- Đánh giá độ ổn định    : {stab['overall_stability']}")
        print(f"- Bản ghi xử lý Pipeline : {summary['pipeline_update']['records_processed']}")
        return

    interval_sec = max(60.0, args.interval_hours * 3600.0)
    while True:
        summary = run_daily_scheduled_pipeline(mode=args.mode)
        print(
            f"[{summary['finished_at']}] Hoàn tất chu kỳ lập lịch: "
            f"stability={summary['stability_monitoring']['overall_stability']}"
        )
        time.sleep(interval_sec)


if __name__ == "__main__":
    main()

