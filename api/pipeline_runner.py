"""End-to-End Pipeline Orchestrator, Data/Model Stability Monitor & Status Service (SRS v1.1 - FR-04, FR-05, FR-18, FR-28, FR-29, Section 7).

Cung cấp lớp `PipelineOrchestrator` và hàm `monitor_data_and_model_stability` phục vụ:
1. Truy vấn trạng thái vận hành toàn diện của hệ thống (`get_pipeline_status`):
   - Lịch sử các tác vụ trong bảng `pipeline_log`.
   - Độ tươi mới dữ liệu (`data_freshness_date` của giá nông sản và thời tiết).
   - Thống kê độ phủ dữ liệu từ `data_coverage_view` (`get_data_coverage_metrics`).
2. Kích hoạt chạy pipeline thủ công (`trigger_manual_pipeline_run` - FR-28):
   - Hỗ trợ chế độ `fast_update` và `full_refresh`.
3. Giám sát độ ổn định dữ liệu và mô hình (`monitor_data_and_model_stability` - FR-29):
   - Phát hiện lệch phân phối dữ liệu đầu vào (Data Drift qua Z-score của cửa sổ gần nhất so với lịch sử)
     và suy giảm độ chính xác mô hình (Model Drift khi sai số Backtesting MAPE vượt ngưỡng cho phép),
     đồng thời ghi nhận kết quả vào bảng `pipeline_log`.
"""

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Any, List, Optional
import numpy as np
from sqlalchemy import func
from sqlalchemy.orm import Session

from collector.base import BaseCollector
from collector.price_collector import TARGET_COMMODITY_PROVINCES, AgriPriceCollector
from collector.weather_collector import OpenMeteoWeatherCollector
from db.database import get_vietnam_now
from db.models import (
    Commodity,
    Province,
    DataSource,
    PriceObservation,
    WeatherObservation,
    FeatureSet,
    ModelRun,
    Forecast,
    AlertEvent,
    PipelineLog,
)
from db.views import get_data_coverage_metrics
from api.alert_service import evaluate_and_trigger_alerts


class PipelineOrchestrator:
    """
    Bộ điều phối vận hành Pipeline thu thập - xử lý - dự báo - cảnh báo và giám sát độ phủ dữ liệu.
    """

    def __init__(self, db: Session):
        self.db = db
        self._collector_helper = BaseCollector(db=db, rate_limit_delay=0.0)

    def get_pipeline_status(self, log_limit: int = 20) -> Dict[str, Any]:
        """
        Truy vấn trạng thái vận hành của pipeline, ngày dữ liệu mới nhất và độ phủ dữ liệu (FR-05, FR-28, FR-42).
        """
        max_price_date = self.db.query(func.max(PriceObservation.obs_date)).scalar()
        min_price_date = self.db.query(func.min(PriceObservation.obs_date)).scalar()
        max_weather_date = self.db.query(func.max(WeatherObservation.obs_date)).scalar()
        max_forecast_date = (
            self.db.query(func.max(Forecast.target_date))
            .filter(Forecast.actual_price.is_(None))
            .scalar()
        )

        price_count = self.db.query(func.count(PriceObservation.id)).scalar() or 0
        weather_count = self.db.query(func.count(WeatherObservation.id)).scalar() or 0
        feature_count = self.db.query(func.count(FeatureSet.id)).scalar() or 0
        model_run_count = self.db.query(func.count(ModelRun.id)).scalar() or 0
        forecast_count = self.db.query(func.count(Forecast.id)).scalar() or 0
        alert_event_count = self.db.query(func.count(AlertEvent.id)).scalar() or 0

        commodities_map = {c.id: c for c in self.db.query(Commodity).all()}
        provinces_map = {p.id: p for p in self.db.query(Province).all()}
        sources_map = {s.id: s for s in self.db.query(DataSource).all()}

        # Độ phủ dữ liệu từ data_coverage_view / get_data_coverage_metrics (FR-42)
        raw_coverage = get_data_coverage_metrics(self.db)
        enriched_coverage: List[Dict[str, Any]] = []
        for item in raw_coverage:
            comm = commodities_map.get(item["commodity_id"])
            prov = provinces_map.get(item["province_id"])
            enriched_coverage.append(
                {
                    "commodity_id": item["commodity_id"],
                    "commodity_code": comm.code if comm else "UNKNOWN",
                    "commodity_name": comm.name if comm else "Không xác định",
                    "province_id": item["province_id"],
                    "province_code": prov.code if prov else "UNKNOWN",
                    "province_name": prov.standard_name if prov else "Không xác định",
                    "min_date": str(item["min_date"]),
                    "max_date": str(item["max_date"]),
                    "total_days_with_data": item["total_days_with_data"],
                    "total_span_days": item["total_span_days"],
                    "missing_ratio": float(item["missing_ratio"]),
                    "max_gap_days": int(item["max_gap_days"]),
                    "is_sufficient_for_training": bool(item["is_sufficient_for_training"]),
                }
            )

        # Lịch sử chạy pipeline gần nhất
        recent_logs = (
            self.db.query(PipelineLog)
            .order_by(PipelineLog.id.desc())
            .limit(log_limit)
            .all()
        )
        formatted_logs: List[Dict[str, Any]] = []
        for log_row in recent_logs:
            src = sources_map.get(log_row.source_id) if log_row.source_id else None
            formatted_logs.append(
                {
                    "id": log_row.id,
                    "task_name": log_row.task_name,
                    "source_id": log_row.source_id,
                    "source_name": src.name if src else "System Orchestrator",
                    "started_at": log_row.started_at.isoformat() if log_row.started_at else None,
                    "finished_at": log_row.finished_at.isoformat() if log_row.finished_at else None,
                    "status": log_row.status,
                    "records_processed": log_row.records_processed,
                    "error_message": log_row.error_message,
                }
            )

        return {
            "system_status": "HEALTHY" if price_count > 0 else "INITIALIZING",
            "checked_at": get_vietnam_now().isoformat(),
            "data_freshness_date": str(max_price_date) if max_price_date else None,
            "data_start_date": str(min_price_date) if min_price_date else None,
            "weather_freshness_date": str(max_weather_date) if max_weather_date else None,
            "forecast_horizon_end_date": str(max_forecast_date) if max_forecast_date else None,
            "record_counts": {
                "price_observation": int(price_count),
                "weather_observation": int(weather_count),
                "feature_set": int(feature_count),
                "model_run": int(model_run_count),
                "forecast": int(forecast_count),
                "alert_event": int(alert_event_count),
            },
            "data_coverage": enriched_coverage,
            "recent_pipeline_logs": formatted_logs,
        }

    def ensure_data_up_to_date(
        self,
        target_date: Optional[date] = None,
        force_recalculate: bool = False,
    ) -> Dict[str, Any]:
        """
        Tự động kiểm tra và đồng bộ bù dữ liệu mới nhất đến ngày hôm nay theo giờ Việt Nam (FR-04, FR-28, FR-45):
        1. Kiểm tra latest_db_date = SELECT MAX(obs_date) FROM price_observation.
        2. Lấy today = get_vietnam_now().date().
        3. Nếu latest_db_date < today (hoặc force_recalculate=True):
           - Thu thập bổ sung dữ liệu giá và thời tiết cho các ngày còn thiếu từ (latest_db_date + 1) đến today.
           - Chạy TimeSeriesCleaner & FeatureEngineer để cập nhật feature_set đến đúng ngày today.
           - Cập nhật cột actual_price cho các bản ghi dự báo cũ trong bảng forecast đã đến hạn (FR-45).
           - Chạy ForecastPredictor.generate_future_forecasts() để sinh chuỗi dự báo 30 ngày tương lai mới
             tính từ (today + 1) đến (today + 30).
           - Chạy evaluate_and_trigger_alerts() để cập nhật cảnh báo mới nhất.
           - Ghi nhận toàn bộ lượt chạy tự động này vào bảng pipeline_log với task_name = 'auto_daily_catchup_sync'.
        """
        today = target_date or get_vietnam_now().date()
        latest_db_date = self.db.query(func.max(PriceObservation.obs_date)).scalar()
        min_future_fc_date = (
            self.db.query(func.min(Forecast.target_date))
            .filter(Forecast.actual_price.is_(None))
            .scalar()
        )

        if latest_db_date is None:
            return {
                "status": "NO_DATA",
                "today": str(today),
                "latest_db_date": None,
                "synced": False,
            }

        needs_catchup = (
            latest_db_date < today
            or force_recalculate
            or (min_future_fc_date is not None and min_future_fc_date <= today)
        )

        if not needs_catchup:
            return {
                "status": "ALREADY_UP_TO_DATE",
                "today": str(today),
                "latest_db_date": str(latest_db_date),
                "synced": False,
            }

        with self._collector_helper.log_pipeline_run(task_name="auto_daily_catchup_sync") as tracker:
            records_handled = 0
            price_added = 0
            weather_added = 0

            # 1. Thu thập bù các ngày giá & thời tiết còn thiếu từ (latest_db_date + 1) đến today
            if latest_db_date < today:
                catchup_start = latest_db_date + timedelta(days=1)
                price_collector = AgriPriceCollector(db=self.db, rate_limit_delay=0.0)
                price_added = price_collector.collect_price_range(
                    start_date=catchup_start,
                    end_date=today,
                    log_pipeline=False,
                )
                weather_collector = OpenMeteoWeatherCollector(db=self.db, rate_limit_delay=0.0)
                weather_added = weather_collector.sync_weather_to_date(target_date=today)
                records_handled += int(price_added) + int(weather_added)

            # 2. Chạy TimeSeriesCleaner & FeatureEngineer cập nhật feature_set đến ngày today
            from processing.features import FeatureEngineer
            from models.predictor import ForecastPredictor

            fe = FeatureEngineer(db=self.db)
            fe_summary = fe.build_and_save_all_series(end_date=today)
            records_handled += int(fe_summary.get("total_rows_upserted", 0))

            # 3. Cập nhật actual_price cho các bản ghi dự báo cũ trong bảng forecast đã đến hạn (<= today, FR-45)
            matured_forecasts = (
                self.db.query(Forecast)
                .filter(
                    Forecast.target_date <= today,
                    Forecast.actual_price.is_(None),
                )
                .all()
            )
            reconciled_count = 0
            for m_fc in matured_forecasts:
                obs_price = (
                    self.db.query(PriceObservation.price)
                    .filter(
                        PriceObservation.commodity_id == m_fc.commodity_id,
                        PriceObservation.province_id == m_fc.province_id,
                        PriceObservation.obs_date == m_fc.target_date,
                    )
                    .scalar()
                )
                if obs_price is not None:
                    m_fc.actual_price = Decimal(str(round(float(obs_price), 2))).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    )
                    reconciled_count += 1
            if reconciled_count > 0:
                self.db.commit()
            records_handled += reconciled_count

            # 4. Sinh lại chuỗi dự báo 30 ngày tương lai mới tính từ (today + 1) đến (today + 30)
            predictor = ForecastPredictor(db=self.db, horizon=30)
            commodities = {c.code: c for c in self.db.query(Commodity).all()}
            provinces = {p.code: p for p in self.db.query(Province).all()}
            future_generated = 0

            for comm_code, prov_codes in TARGET_COMMODITY_PROVINCES.items():
                comm = commodities.get(comm_code)
                if not comm:
                    continue
                for p_code in prov_codes:
                    prov = provinces.get(p_code)
                    if not prov:
                        continue
                    try:
                        fcs = predictor.generate_future_forecasts(
                            commodity_id=comm.id,
                            province_id=prov.id,
                            horizon=30,
                        )
                        future_generated += len(fcs)
                    except Exception:
                        continue

            records_handled += future_generated

            # 5. Đánh giá lại cảnh báo mới nhất
            from api.alert_service import cleanup_and_rebuild_alert_events
            if latest_db_date < today or force_recalculate:
                alert_rebuild = cleanup_and_rebuild_alert_events(self.db)
                alert_summary = alert_rebuild["evaluation_result"]
            else:
                alert_summary = evaluate_and_trigger_alerts(self.db, force_check_all_thresholds=False)

            records_handled += int(alert_summary.get("rules_evaluated", 0))
            tracker.add_records(records_handled)

        new_max_date = self.db.query(func.max(PriceObservation.obs_date)).scalar()
        return {
            "status": "SUCCESS",
            "task_name": "auto_daily_catchup_sync",
            "synced": True,
            "previous_latest_date": str(latest_db_date),
            "current_latest_date": str(new_max_date),
            "price_records_added": price_added,
            "weather_records_added": weather_added,
            "matured_forecasts_reconciled": reconciled_count,
            "future_forecasts_generated": future_generated,
            "alert_evaluation": alert_summary,
            "synced_at": get_vietnam_now().isoformat(),
        }

    sync_to_current_date = ensure_data_up_to_date

    def trigger_manual_pipeline_run(
        self,
        mode: str = "fast_update",
        commodity_code: Optional[str] = None,
        province_code: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Kích hoạt chạy pipeline thủ công (FR-28) và ghi nhận kết quả vào bảng `pipeline_log` (FR-05).
        Tự động gọi `ensure_data_up_to_date` trên CSDL chính để làm mới dữ liệu tới ngày hiện tại.
        """
        dialect_name = self.db.bind.dialect.name if self.db.bind is not None else "postgresql"
        catchup_result: Optional[Dict[str, Any]] = None
        if dialect_name != "sqlite":
            catchup_result = self.ensure_data_up_to_date(
                force_recalculate=(mode == "full_refresh")
            )

        task_label = f"manual_pipeline_trigger_{mode}"
        with self._collector_helper.log_pipeline_run(task_name=task_label) as tracker:
            records_handled = 0

            if mode == "full_refresh":
                if catchup_result and catchup_result.get("synced"):
                    records_handled += int(catchup_result.get("future_forecasts_generated", 0))
                else:
                    from processing.features import FeatureEngineer
                    from models.predictor import ForecastPredictor

                    fe_pipe = FeatureEngineer(db=self.db)
                    fe_summary = fe_pipe.build_and_save_all_series()
                    records_handled += int(fe_summary.get("total_rows_upserted", 0))

                    predictor = ForecastPredictor(db=self.db, horizon=30)
                    fc_summary = predictor.generate_all_forecasts_and_backtests(horizon=30, backtest_days=30)
                    records_handled += int(fc_summary.get("future_forecasts_generated", 0))
            else:
                if commodity_code and province_code:
                    comm = self.db.query(Commodity).filter(Commodity.code == commodity_code.upper()).first()
                    prov = self.db.query(Province).filter(Province.code == province_code.upper()).first()
                    if comm and prov:
                        obs_cnt = (
                            self.db.query(func.count(PriceObservation.id))
                            .filter(
                                PriceObservation.commodity_id == comm.id,
                                PriceObservation.province_id == prov.id,
                            )
                            .scalar()
                            or 0
                        )
                        records_handled += int(obs_cnt)
                else:
                    obs_cnt = self.db.query(func.count(Forecast.id)).scalar() or 0
                    records_handled += int(obs_cnt)

            alert_summary = evaluate_and_trigger_alerts(self.db, force_check_all_thresholds=False)
            records_handled += int(alert_summary.get("rules_evaluated", 0))
            tracker.add_records(records_handled)

        return {
            "status": "SUCCESS",
            "mode": mode,
            "task_name": task_label,
            "records_processed": records_handled,
            "catchup_sync": catchup_result,
            "alert_evaluation": alert_summary,
            "triggered_at": get_vietnam_now().isoformat(),
        }

    def monitor_stability(
        self,
        z_score_threshold: float = 2.5,
        mape_warning_threshold: float = 3.5,
    ) -> Dict[str, Any]:
        """
        Giám sát độ ổn định dữ liệu và mô hình (FR-29):
        - Kiểm tra Data Drift: So sánh trung bình cửa sổ 14 ngày gần nhất với phân phối lịch sử (Z-score).
        - Kiểm tra Model Drift: Đối chiếu sai số thực tế trên tập Backtesting (`actual_price` vs `yhat`)
          với ngưỡng `mape_warning_threshold` hoặc độ lệch gấp đôi so với `model_run.mape`.
        - Ghi nhận bản ghi vào bảng `pipeline_log` (`task_name = 'data_and_model_stability_monitor'`).
        """
        commodities = {c.code: c for c in self.db.query(Commodity).all()}
        provinces = {p.code: p for p in self.db.query(Province).all()}

        series_reports: List[Dict[str, Any]] = []
        drift_warnings: List[str] = []

        with self._collector_helper.log_pipeline_run(
            task_name="data_and_model_stability_monitor"
        ) as tracker:
            checked_count = 0
            for comm_code, prov_codes in TARGET_COMMODITY_PROVINCES.items():
                comm = commodities.get(comm_code)
                if not comm:
                    continue
                for p_code in prov_codes:
                    prov = provinces.get(p_code)
                    if not prov:
                        continue

                    obs_rows = (
                        self.db.query(PriceObservation.price)
                        .filter(
                            PriceObservation.commodity_id == comm.id,
                            PriceObservation.province_id == prov.id,
                        )
                        .order_by(PriceObservation.obs_date.asc())
                        .all()
                    )
                    if len(obs_rows) < 20:
                        continue

                    checked_count += 1
                    prices = np.array([float(r[0]) for r in obs_rows], dtype=float)
                    baseline_prices = prices[:-14] if len(prices) > 20 else prices
                    recent_prices = prices[-14:]

                    hist_mean = float(np.mean(baseline_prices))
                    hist_std = max(float(np.std(baseline_prices)), 1e-6)
                    recent_mean = float(np.mean(recent_prices))
                    drift_z_score = round(abs(recent_mean - hist_mean) / hist_std, 4)
                    has_data_drift = drift_z_score >= z_score_threshold

                    # Kiểm tra sai số mô hình trên các bản ghi backtest có actual_price
                    bt_rows = (
                        self.db.query(Forecast)
                        .filter(
                            Forecast.commodity_id == comm.id,
                            Forecast.province_id == prov.id,
                            Forecast.actual_price.is_not(None),
                        )
                        .all()
                    )
                    bt_mape = 0.0
                    if bt_rows:
                        ape_vals = [
                            abs(float(r.yhat) - float(r.actual_price)) / max(float(r.actual_price), 1.0) * 100.0
                            for r in bt_rows
                        ]
                        bt_mape = round(float(np.mean(ape_vals)), 4)

                    selected_run = (
                        self.db.query(ModelRun)
                        .filter(
                            ModelRun.commodity_id == comm.id,
                            ModelRun.province_id == prov.id,
                            ModelRun.is_selected.is_(True),
                        )
                        .order_by(ModelRun.id.desc())
                        .first()
                    )
                    train_mape = float(selected_run.mape) if selected_run and selected_run.mape is not None else 1.0
                    has_model_drift = bt_mape > mape_warning_threshold or (
                        train_mape > 0 and bt_mape > max(train_mape * 2.5, mape_warning_threshold)
                    )

                    status_label = "RETRAIN_RECOMMENDED" if (has_data_drift or has_model_drift) else "STABLE"
                    if status_label != "STABLE":
                        drift_warnings.append(
                            f"{comm.code}-{prov.code}: z={drift_z_score}, backtest_mape={bt_mape}%"
                        )

                    series_reports.append(
                        {
                            "commodity_code": comm.code,
                            "province_code": prov.code,
                            "historical_mean": round(hist_mean, 2),
                            "recent_14d_mean": round(recent_mean, 2),
                            "drift_z_score": drift_z_score,
                            "has_data_drift": has_data_drift,
                            "train_mape": round(train_mape, 4),
                            "backtest_mape": bt_mape,
                            "has_model_drift": has_model_drift,
                            "stability_status": status_label,
                        }
                    )

            tracker.add_records(checked_count)

        return {
            "task_name": "data_and_model_stability_monitor",
            "series_checked": len(series_reports),
            "overall_stability": "WARNING_DRIFT_DETECTED" if drift_warnings else "STABLE",
            "drift_warnings": drift_warnings,
            "series_reports": series_reports,
            "checked_at": get_vietnam_now().isoformat(),
        }


def monitor_data_and_model_stability(
    db: Session,
    z_score_threshold: float = 2.5,
    mape_warning_threshold: float = 3.5,
) -> Dict[str, Any]:
    """Hàm tiện ích giám sát độ ổn định dữ liệu và mô hình (FR-29)."""
    orchestrator = PipelineOrchestrator(db=db)
    return orchestrator.monitor_stability(
        z_score_threshold=z_score_threshold,
        mape_warning_threshold=mape_warning_threshold,
    )
