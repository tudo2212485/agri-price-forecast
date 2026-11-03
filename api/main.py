"""FastAPI Application Backend for Agricultural Price Analysis & Forecasting System (SRS v1.1).

Tuân thủ chặt chẽ Mục 3.4, 3.5, 3.6, 3.7, Mục 5.2, 5.3 và NFR-01, NFR-05, NFR-11, NFR-15:
- `GET /api/commodities`: Danh mục nông sản, tỉnh/thành, nguồn dữ liệu và ma trận tỉnh hỗ trợ.
- `GET /api/overview`: Thẻ KPI tổng quan, biến động 7/30 ngày, dự báo 7 ngày tới, khu vực biến động mạnh nhất.
- `GET /api/prices`: Chuỗi giá lịch sử thực tế đã chuẩn hóa (VNĐ/kg), thống kê min/max/mean/std,
  metadata nguồn thu thập (FR-39, NFR-15), và xử lý tỉnh không đủ dữ liệu `INSUFFICIENT_DATA` (FR-37).
- `GET /api/forecast`: Chuỗi dự báo tương lai (horizon 7..30 ngày), khối diễn giải ngôn ngữ tự nhiên
  cho nông dân (`farmer_summary` - FR-49..FR-51), metadata nguồn và mô hình tốt nhất (`is_selected=True`).
- `GET /api/models/metrics`: Bảng xếp hạng 7 mô hình từ `model_run` và dữ liệu kiểm chứng ngược 30 ngày
  (`backtest_series` có `actual_price` - FR-22, FR-44, FR-46).
- `GET /api/export/csv`: Xuất CSV dữ liệu lịch sử + dự báo kèm nguồn và cờ nội suy (FR-23).
- `GET /api/alerts`, `POST /api/alerts/rules`, `POST /api/subscriptions`, `DELETE /api/subscriptions/{sub_id}`:
  Hệ thống cảnh báo biến động và đăng ký nhận tin 1 bước không mật khẩu (FR-24..FR-27, FR-52, FR-53).
- `GET /api/pipeline/status`, `POST /api/pipeline/run`: Giám sát độ phủ & điều phối pipeline (FR-28, FR-42).
"""

import asyncio
import csv
import io
import logging
import os
from contextlib import asynccontextmanager
from datetime import date
from typing import Optional, List, Dict, Any

import numpy as np
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func
from sqlalchemy.orm import Session

from collector.price_collector import TARGET_COMMODITY_PROVINCES
from db.database import get_db, get_vietnam_now, SessionLocal
from db.models import (
    Commodity,
    Province,
    DataSource,
    PriceObservation,
    WeatherObservation,
    ModelRun,
    Forecast,
    AlertRule,
    AlertEvent,
    Subscriber,
)
from processing.features import HARVEST_MONTHS_BY_COMMODITY
from models.evaluation import compute_all_metrics
from api.farmer_translator import generate_farmer_friendly_summary
from api.alert_service import (
    evaluate_and_trigger_alerts,
    create_passwordless_subscription,
    unsubscribe_by_id,
)
from api.pipeline_runner import PipelineOrchestrator, monitor_data_and_model_stability
from api.schemas import (
    AlertRuleCreateRequest,
    SubscriptionCreateRequest,
    PipelineRunRequest,
)

logger = logging.getLogger(__name__)


def _run_startup_or_scheduled_sync() -> Optional[Dict[str, Any]]:
    """Chạy kiểm tra và đồng bộ bù dữ liệu lên ngày hôm nay trong một DB session độc lập."""
    session = SessionLocal()
    try:
        orchestrator = PipelineOrchestrator(db=session)
        return orchestrator.ensure_data_up_to_date()
    except Exception as exc:
        logger.warning(f"Lỗi khi tự động đồng bộ bù ngày mới: {exc}")
        return None
    finally:
        session.close()


async def _background_daily_sync_loop() -> None:
    """
    Vòng lặp nền nhẹ ngay trong tiến trình FastAPI:
    Định kỳ kiểm tra mỗi 1 giờ (và khi bước qua 00:05 ngày mới) để tự động gọi ensure_data_up_to_date().
    """
    while True:
        try:
            now_vn = get_vietnam_now()
            # Nếu đang ở sát thời điểm 00:00..00:05 của ngày mới thì chờ vài phút rồi đồng bộ ngay
            if now_vn.hour == 0 and now_vn.minute < 5:
                sleep_seconds = max(30, (5 - now_vn.minute) * 60)
            else:
                sleep_seconds = 3600
            await asyncio.sleep(sleep_seconds)
            await asyncio.to_thread(_run_startup_or_scheduled_sync)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning(f"Background sync loop warning: {exc}")
            await asyncio.sleep(300)


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    """
    Lifespan của FastAPI (FR-04, FR-28):
    1. Khi khởi động server (và không phải môi trường unit test override DB), tự động gọi ensure_data_up_to_date().
    2. Khởi chạy Background Task định kỳ mỗi 1 giờ kiểm tra và cập nhật dữ liệu khi sang ngày mới.
    """
    bg_task: Optional[asyncio.Task] = None
    if not app_instance.dependency_overrides:
        await asyncio.to_thread(_run_startup_or_scheduled_sync)
        bg_task = asyncio.create_task(_background_daily_sync_loop())
    try:
        yield
    finally:
        if bg_task is not None:
            bg_task.cancel()


app = FastAPI(
    title="Hệ thống Phân tích và Dự báo Biến động Giá Nông sản (SRS v1.1)",
    description=(
        "Backend API phục vụ Dashboard Hai Chế Độ (Chế độ Đơn giản cho Nông dân & "
        "Chế độ Chuyên gia cho Nhà phân tích), Cảnh báo sớm và Giám sát Pipeline."
    ),
    version="1.1.0",
    lifespan=lifespan,
)

# Cấu hình CORS cho phép React + Tailwind CSS Dashboard truy cập (NFR-05)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

INSUFFICIENT_DATA_MSG_VI = (
    "Chưa đủ dữ liệu lịch sử cho nông sản này tại tỉnh đã chọn để phân tích và dự báo."
)


def _resolve_commodity_and_province(
    db: Session,
    commodity_code: str,
    province_code: str,
) -> tuple[Commodity, Province, List[Dict[str, Any]]]:
    """
    Tìm đối tượng Commodity và Province từ mã code, đồng thời trả về danh sách các tỉnh hợp lệ
    có dữ liệu cho mặt hàng đó. Nếu mã không tồn tại trong danh mục gốc, trả về HTTP 404.
    """
    comm = db.query(Commodity).filter(Commodity.code == commodity_code.strip().upper()).first()
    if not comm:
        raise HTTPException(
            status_code=404,
            detail=f"Không tìm thấy mặt hàng nông sản với mã '{commodity_code}'.",
        )

    prov = db.query(Province).filter(Province.code == province_code.strip().upper()).first()
    if not prov:
        raise HTTPException(
            status_code=404,
            detail=f"Không tìm thấy tỉnh/thành phố với mã '{province_code}'.",
        )

    all_provinces = {p.code: p for p in db.query(Province).all()}
    valid_prov_codes = TARGET_COMMODITY_PROVINCES.get(comm.code, [])
    supported_provinces: List[Dict[str, Any]] = []
    for code in valid_prov_codes:
        p_obj = all_provinces.get(code)
        if p_obj:
            supported_provinces.append(
                {
                    "id": p_obj.id,
                    "code": p_obj.code,
                    "name": p_obj.standard_name,
                    "region": p_obj.region,
                }
            )

    return comm, prov, supported_provinces


def _build_insufficient_data_payload(
    comm: Commodity,
    prov: Province,
    supported_provinces: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Trả về cấu trúc chuẩn khi cặp (Nông sản - Tỉnh) không có đủ dữ liệu lịch sử (FR-37)."""
    return {
        "status": "INSUFFICIENT_DATA",
        "commodity_code": comm.code,
        "commodity_name": comm.name,
        "province_code": prov.code,
        "province_name": prov.standard_name,
        "message_vi": INSUFFICIENT_DATA_MSG_VI,
        "supported_provinces": supported_provinces,
    }


def _extract_source_metadata(
    db: Session,
    latest_obs: PriceObservation,
) -> Dict[str, Any]:
    """Trích xuất thông tin minh bạch về nguồn dữ liệu và loại giá (FR-39, NFR-15)."""
    src = db.query(DataSource).filter(DataSource.id == latest_obs.source_id).first()
    return {
        "source_id": latest_obs.source_id,
        "source_name": src.name if src else "Nguồn tổng hợp nông sản",
        "publisher": src.publisher if src else "Báo địa phương & Cổng thông tin nông nghiệp",
        "price_type": src.price_type if src and src.price_type else "Giá thu mua nông sản thực tế",
        "raw_unit": latest_obs.raw_unit,
        "normalized_unit": "VNĐ/kg",
        "source_url": latest_obs.source_url,
        "reliability_level": src.reliability_level if src else "HIGH",
        "last_updated": str(latest_obs.obs_date),
        "collected_at": latest_obs.collected_at.isoformat() if latest_obs.collected_at else None,
    }


# ==============================================================================
# 1. GET /api/commodities
# ==============================================================================
@app.get("/api/commodities", tags=["Master Data"])
def list_commodities_and_provinces(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Trả về danh sách các mặt hàng nông sản (`commodity`), danh sách các tỉnh/thành (`province`),
    ma trận ánh xạ các tỉnh có dữ liệu cho từng mặt hàng và danh sách nguồn thu thập (`data_sources`).
    """
    commodities = db.query(Commodity).order_by(Commodity.id).all()
    provinces = db.query(Province).order_by(Province.id).all()
    sources = db.query(DataSource).filter(DataSource.is_active.is_(True)).order_by(DataSource.id).all()
    prov_by_code = {p.code: p for p in provinces}

    commodity_list: List[Dict[str, Any]] = []
    commodity_provinces_map: Dict[str, List[Dict[str, Any]]] = {}

    for comm in commodities:
        valid_codes = TARGET_COMMODITY_PROVINCES.get(comm.code, [])
        supported_provs = [
            {
                "id": prov_by_code[c].id,
                "code": prov_by_code[c].code,
                "name": prov_by_code[c].standard_name,
                "region": prov_by_code[c].region,
            }
            for c in valid_codes
            if c in prov_by_code
        ]
        commodity_provinces_map[comm.code] = supported_provs
        commodity_list.append(
            {
                "id": comm.id,
                "code": comm.code,
                "name": comm.name,
                "unit": comm.unit,
                "category": comm.category,
                "default_province_code": valid_codes[0] if valid_codes else None,
                "supported_provinces": supported_provs,
            }
        )

    province_list = [
        {
            "id": p.id,
            "code": p.code,
            "name": p.standard_name,
            "region": p.region,
            "lat": p.lat,
            "lon": p.lon,
        }
        for p in provinces
    ]

    source_list = [
        {
            "id": s.id,
            "name": s.name,
            "publisher": s.publisher,
            "url_or_api": s.url_or_api,
            "source_type": s.source_type,
            "price_type": s.price_type,
            "raw_unit": s.raw_unit,
            "frequency": s.frequency,
            "reliability_level": s.reliability_level,
        }
        for s in sources
    ]

    return {
        "status": "OK",
        "commodities": commodity_list,
        "provinces": province_list,
        "commodity_provinces_map": commodity_provinces_map,
        "data_sources": source_list,
    }


# ==============================================================================
# 2. GET /api/overview
# ==============================================================================
@app.get("/api/overview", tags=["Dashboard Overview"])
def get_dashboard_overview(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Trả về dữ liệu cho các thẻ KPI trên trang Tổng quan (FR-19):
    - Giá hiện tại, biến động 7 ngày / 30 ngày qua, dự báo xu hướng 7 ngày tới kèm tóm tắt cho nông dân.
    - Khu vực biến động mạnh nhất (`highest_volatility_region`).
    - Số cảnh báo đang kích hoạt và danh sách sự kiện cảnh báo gần nhất.
    """
    commodities = {c.code: c for c in db.query(Commodity).all()}
    provinces = {p.code: p for p in db.query(Province).all()}

    series_cards: List[Dict[str, Any]] = []
    highest_volatility: Optional[Dict[str, Any]] = None

    for comm_code, prov_codes in TARGET_COMMODITY_PROVINCES.items():
        comm = commodities.get(comm_code)
        if not comm:
            continue
        for p_code in prov_codes:
            prov = provinces.get(p_code)
            if not prov:
                continue

            recent_obs = (
                db.query(PriceObservation)
                .filter(
                    PriceObservation.commodity_id == comm.id,
                    PriceObservation.province_id == prov.id,
                )
                .order_by(PriceObservation.obs_date.desc())
                .limit(35)
                .all()
            )
            if not recent_obs:
                continue

            latest_row = recent_obs[0]
            curr_price = float(latest_row.price)
            latest_date = latest_row.obs_date

            price_7d_ago = float(recent_obs[min(7, len(recent_obs) - 1)].price)
            price_30d_ago = float(recent_obs[min(30, len(recent_obs) - 1)].price)

            change_7d_pct = round(((curr_price - price_7d_ago) / price_7d_ago) * 100.0, 2) if price_7d_ago > 0 else 0.0
            change_30d_pct = round(((curr_price - price_30d_ago) / price_30d_ago) * 100.0, 2) if price_30d_ago > 0 else 0.0

            # Lấy dự báo ở horizon = 7 ngày tới
            fc_7d = (
                db.query(Forecast)
                .filter(
                    Forecast.commodity_id == comm.id,
                    Forecast.province_id == prov.id,
                    Forecast.actual_price.is_(None),
                    Forecast.horizon == 7,
                )
                .order_by(Forecast.id.desc())
                .first()
            )
            if not fc_7d:
                fc_7d = (
                    db.query(Forecast)
                    .filter(
                        Forecast.commodity_id == comm.id,
                        Forecast.province_id == prov.id,
                        Forecast.actual_price.is_(None),
                    )
                    .order_by(Forecast.horizon.desc())
                    .first()
                )

            selected_run = (
                db.query(ModelRun)
                .filter(
                    ModelRun.commodity_id == comm.id,
                    ModelRun.province_id == prov.id,
                    ModelRun.is_selected.is_(True),
                )
                .order_by(ModelRun.id.desc())
                .first()
            )
            mape_val = selected_run.mape if selected_run and selected_run.mape is not None else 0.6

            target_7d_price = float(fc_7d.yhat) if fc_7d else curr_price
            ci_width_pct = None
            if fc_7d and fc_7d.lower_bound is not None and fc_7d.upper_bound is not None and target_7d_price > 0:
                ci_width_pct = ((float(fc_7d.upper_bound) - float(fc_7d.lower_bound)) / target_7d_price) * 100.0

            farmer_summary = generate_farmer_friendly_summary(
                commodity_name=comm.name,
                province_name=prov.standard_name,
                current_price=curr_price,
                target_price=target_7d_price,
                horizon_days=7,
                mape_score=mape_val,
                ci_width_pct=ci_width_pct,
            )

            card_item = {
                "commodity_code": comm.code,
                "commodity_name": comm.name,
                "unit": comm.unit,
                "category": comm.category,
                "province_code": prov.code,
                "province_name": prov.standard_name,
                "region": prov.region,
                "latest_date": str(latest_date),
                "current_price": curr_price,
                "change_7d_pct": change_7d_pct,
                "change_7d_amount": round(curr_price - price_7d_ago, 2),
                "change_30d_pct": change_30d_pct,
                "change_30d_amount": round(curr_price - price_30d_ago, 2),
                "forecast_7d_price": round(target_7d_price, 2),
                "forecast_7d_change_pct": farmer_summary["change_pct"],
                "trend_direction": farmer_summary["trend_direction"],
                "confidence_label_vi": farmer_summary["confidence_label_vi"],
                "farmer_summary": farmer_summary,
                "selected_model": selected_run.model_type if selected_run else "NAIVE",
                "selected_model_mape": round(float(mape_val), 4) if mape_val is not None else None,
            }
            series_cards.append(card_item)

            volatility_score = max(abs(change_7d_pct), abs(farmer_summary["change_pct"]))
            if highest_volatility is None or volatility_score > highest_volatility["volatility_score"]:
                highest_volatility = {
                    "commodity_code": comm.code,
                    "commodity_name": comm.name,
                    "province_code": prov.code,
                    "province_name": prov.standard_name,
                    "region": prov.region,
                    "current_price": curr_price,
                    "change_7d_pct": change_7d_pct,
                    "forecast_7d_change_pct": farmer_summary["change_pct"],
                    "volatility_score": round(volatility_score, 2),
                    "headline_vi": farmer_summary["headline_vi"],
                }

    # Đại diện từng mặt hàng chính (3 thẻ KPI hàng đầu cho 3 nông sản chủ lực)
    primary_commodity_Defaults = {"CAFE_ROBUSTA": "DL", "TIEU_DEN": "GL", "LUA_IR50404": "AG"}
    featured_kpis = [
        c for c in series_cards if primary_commodity_Defaults.get(c["commodity_code"]) == c["province_code"]
    ]
    if not featured_kpis and series_cards:
        featured_kpis = series_cards[:3]

    active_rules_count = db.query(func.count(AlertRule.id)).filter(AlertRule.is_active.is_(True)).scalar() or 0
    total_events_count = db.query(func.count(AlertEvent.id)).scalar() or 0
    recent_events = (
        db.query(AlertEvent)
        .order_by(AlertEvent.created_at.desc(), AlertEvent.id.desc())
        .limit(5)
        .all()
    )
    comm_by_id = {c.id: c for c in commodities.values()}
    prov_by_id = {p.id: p for p in provinces.values()}

    recent_alerts_payload = [
        {
            "id": ev.id,
            "rule_id": ev.rule_id,
            "commodity_code": comm_by_id[ev.commodity_id].code if ev.commodity_id in comm_by_id else "",
            "commodity_name": comm_by_id[ev.commodity_id].name if ev.commodity_id in comm_by_id else "",
            "province_code": prov_by_id[ev.province_id].code if ev.province_id in prov_by_id else "",
            "province_name": prov_by_id[ev.province_id].standard_name if ev.province_id in prov_by_id else "",
            "target_date": str(ev.target_date),
            "change_pct": ev.change_pct,
            "message": ev.message,
            "sent_status": ev.sent_status,
            "created_at": ev.created_at.isoformat() if ev.created_at else None,
        }
        for ev in recent_events
    ]

    return {
        "status": "OK",
        "generated_at": get_vietnam_now().isoformat(),
        "featured_commodity_kpis": featured_kpis,
        "all_series_kpis": series_cards,
        "highest_volatility_region": highest_volatility,
        "alerts_summary": {
            "active_rules_count": int(active_rules_count),
            "triggered_events_count": int(total_events_count),
            "recent_events": recent_alerts_payload,
        },
    }


# ==============================================================================
# 3. GET /api/prices
# ==============================================================================
@app.get("/api/prices", tags=["Historical Prices & Analytics"])
def get_historical_prices(
    commodity: str = Query(..., description="Mã mặt hàng nông sản (VD: CAFE_ROBUSTA, TIEU_DEN, LUA_IR50404)"),
    province: str = Query(..., description="Mã tỉnh/thành phố (VD: DL, LD, GL, DN, BRVT, AG, DT, CT)"),
    start_date: Optional[date] = Query(default=None, description="Ngày bắt đầu lọc (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(default=None, description="Ngày kết thúc lọc (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Trả về chuỗi giá lịch sử thực tế đã chuẩn hóa (`VNĐ/kg`), kèm thống kê `min`, `max`, `mean`, `std` (FR-21),
    metadata nguồn dữ liệu minh bạch (FR-39, NFR-15), và xử lý an toàn khi tỉnh không có dữ liệu (FR-37).
    """
    comm, prov, supported_provinces = _resolve_commodity_and_province(db, commodity, province)

    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=422,
            detail="Ngày bắt đầu (start_date) không được lớn hơn ngày kết thúc (end_date).",
        )

    # Kiểm tra xem cặp (commodity, province) có dữ liệu trong hệ thống không (FR-37)
    total_obs_for_pair = (
        db.query(func.count(PriceObservation.id))
        .filter(
            PriceObservation.commodity_id == comm.id,
            PriceObservation.province_id == prov.id,
        )
        .scalar()
        or 0
    )
    if total_obs_for_pair < 10:
        return _build_insufficient_data_payload(comm, prov, supported_provinces)

    query = db.query(PriceObservation).filter(
        PriceObservation.commodity_id == comm.id,
        PriceObservation.province_id == prov.id,
    )
    if start_date:
        query = query.filter(PriceObservation.obs_date >= start_date)
    if end_date:
        query = query.filter(PriceObservation.obs_date <= end_date)

    rows = query.order_by(PriceObservation.obs_date.asc()).all()
    if not rows:
        return {
            "status": "OK",
            "commodity_code": comm.code,
            "commodity_name": comm.name,
            "province_code": prov.code,
            "province_name": prov.standard_name,
            "unit": comm.unit,
            "record_count": 0,
            "statistics": None,
            "source_metadata": None,
            "series": [],
        }

    prices_arr = np.array([float(r.price) for r in rows], dtype=float)
    latest_obs = rows[-1]
    source_meta = _extract_source_metadata(db, latest_obs)

    stats = {
        "min_price": round(float(np.min(prices_arr)), 2),
        "max_price": round(float(np.max(prices_arr)), 2),
        "mean_price": round(float(np.mean(prices_arr)), 2),
        "median_price": round(float(np.median(prices_arr)), 2),
        "std_price": round(float(np.std(prices_arr)), 2),
        "latest_price": round(float(prices_arr[-1]), 2),
        "start_date": str(rows[0].obs_date),
        "end_date": str(rows[-1].obs_date),
        "interpolated_count": sum(1 for r in rows if r.is_interpolated),
    }

    series_payload = [
        {
            "obs_date": str(r.obs_date),
            "price": float(r.price),
            "raw_value": r.raw_value,
            "raw_unit": r.raw_unit,
            "is_interpolated": bool(r.is_interpolated),
            "quality_flag": r.quality_flag,
            "source_url": r.source_url,
        }
        for r in rows
    ]

    return {
        "status": "OK",
        "commodity_code": comm.code,
        "commodity_name": comm.name,
        "province_code": prov.code,
        "province_name": prov.standard_name,
        "region": prov.region,
        "unit": comm.unit,
        "record_count": len(series_payload),
        "statistics": stats,
        "source_metadata": source_meta,
        "supported_provinces": supported_provinces,
        "series": series_payload,
    }


# ==============================================================================
# 4. GET /api/forecast
# ==============================================================================
@app.get("/api/forecast", tags=["Forecasting & Farmer Translation"])
def get_commodity_forecast(
    commodity: str = Query(..., description="Mã mặt hàng nông sản (VD: CAFE_ROBUSTA)"),
    province: str = Query(..., description="Mã tỉnh/thành phố (VD: DL)"),
    horizon: int = Query(default=7, ge=7, le=30, description="Tầm xa dự báo từ 7 đến 30 ngày (7, 14, 30)"),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Trả về chuỗi dự báo tương lai (`target_date`, `yhat`, `lower_bound`, `upper_bound`) từ bảng `forecast`,
    kèm khối diễn giải ngôn ngữ đời thường `farmer_summary` (FR-49, FR-50, FR-51),
    metadata nguồn dữ liệu (`source_metadata`) và thông tin mô hình tốt nhất đang chọn (`selected_model_info` - FR-46).
    """
    comm, prov, supported_provinces = _resolve_commodity_and_province(db, commodity, province)

    latest_obs = (
        db.query(PriceObservation)
        .filter(
            PriceObservation.commodity_id == comm.id,
            PriceObservation.province_id == prov.id,
        )
        .order_by(PriceObservation.obs_date.desc())
        .first()
    )
    if not latest_obs:
        return _build_insufficient_data_payload(comm, prov, supported_provinces)

    future_rows = (
        db.query(Forecast)
        .filter(
            Forecast.commodity_id == comm.id,
            Forecast.province_id == prov.id,
            Forecast.actual_price.is_(None),
            Forecast.target_date > latest_obs.obs_date,
            Forecast.horizon <= horizon,
        )
        .order_by(Forecast.horizon.asc())
        .all()
    )
    if not future_rows:
        return _build_insufficient_data_payload(comm, prov, supported_provinces)

    selected_run = (
        db.query(ModelRun)
        .filter(
            ModelRun.commodity_id == comm.id,
            ModelRun.province_id == prov.id,
            ModelRun.is_selected.is_(True),
        )
        .order_by(ModelRun.id.desc())
        .first()
    )

    current_price = float(latest_obs.price)
    horizon_target_row = future_rows[-1]
    target_price = float(horizon_target_row.yhat)

    ci_width_pct = None
    if (
        horizon_target_row.lower_bound is not None
        and horizon_target_row.upper_bound is not None
        and target_price > 0
    ):
        ci_width_pct = (
            (float(horizon_target_row.upper_bound) - float(horizon_target_row.lower_bound))
            / target_price
        ) * 100.0

    mape_score = selected_run.mape if selected_run and selected_run.mape is not None else 0.6

    farmer_summary = generate_farmer_friendly_summary(
        commodity_name=comm.name,
        province_name=prov.standard_name,
        current_price=current_price,
        target_price=target_price,
        horizon_days=horizon,
        mape_score=mape_score,
        ci_width_pct=ci_width_pct,
    )

    # Lấy thêm 30 ngày lịch sử gần nhất để UI vẽ biểu đồ nối tiếp mượt mà giữa quá khứ và tương lai (FR-20)
    recent_history_rows = (
        db.query(PriceObservation)
        .filter(
            PriceObservation.commodity_id == comm.id,
            PriceObservation.province_id == prov.id,
        )
        .order_by(PriceObservation.obs_date.desc())
        .limit(60)
        .all()
    )
    recent_history_series = [
        {
            "obs_date": str(r.obs_date),
            "price": float(r.price),
            "is_interpolated": bool(r.is_interpolated),
        }
        for r in reversed(recent_history_rows)
    ]

    forecast_series = [
        {
            "target_date": str(fc.target_date),
            "horizon": fc.horizon,
            "yhat": float(fc.yhat),
            "lower_bound": float(fc.lower_bound) if fc.lower_bound is not None else float(fc.yhat),
            "upper_bound": float(fc.upper_bound) if fc.upper_bound is not None else float(fc.yhat),
        }
        for fc in future_rows
    ]

    selected_model_info = (
        {
            "model_run_id": selected_run.id,
            "model_type": selected_run.model_type,
            "mae": round(float(selected_run.mae), 4) if selected_run.mae is not None else None,
            "rmse": round(float(selected_run.rmse), 4) if selected_run.rmse is not None else None,
            "mape": round(float(selected_run.mape), 4) if selected_run.mape is not None else None,
            "train_start_date": str(selected_run.train_start_date),
            "train_end_date": str(selected_run.train_end_date),
            "test_start_date": str(selected_run.test_start_date),
            "test_end_date": str(selected_run.test_end_date),
            "train_record_count": selected_run.train_record_count,
            "hyperparameters": selected_run.hyperparameters,
            "is_selected": bool(selected_run.is_selected),
            "created_at": selected_run.created_at.isoformat() if selected_run.created_at else None,
        }
        if selected_run
        else None
    )

    # 4. Trích xuất bối cảnh Thời tiết 7 ngày qua & Tình trạng Mùa vụ thực tế (FR-03, FR-07, FR-09)
    recent_weather = (
        db.query(WeatherObservation)
        .filter(WeatherObservation.province_id == prov.id)
        .order_by(WeatherObservation.obs_date.desc())
        .limit(7)
        .all()
    )
    harvest_months = HARVEST_MONTHS_BY_COMMODITY.get(comm.code, [])
    current_month = latest_obs.obs_date.month
    is_harvest_season = current_month in harvest_months

    if is_harvest_season:
        harvest_label_vi = f"Đang trong chính vụ thu hoạch (Tháng {current_month} - Nguồn cung dồi dào)"
    else:
        harvest_label_vi = f"Ngoài vụ thu hoạch chính (Tháng {current_month} - Nguồn cung ổn định)"

    if recent_weather:
        temps = [float(w.temp_mean) for w in recent_weather if w.temp_mean is not None]
        precips = [float(w.precipitation) for w in recent_weather if w.precipitation is not None]
        avg_temp = round(float(np.mean(temps)), 1) if temps else 24.5
        sum_precip = round(float(np.sum(precips)), 1) if precips else 0.0
        weather_summary_vi = (
            f"Nhiệt độ TB 7 ngày qua: {avg_temp}°C | Lượng mưa tích lũy: {sum_precip} mm | Vụ mùa: {harvest_label_vi}"
        )
        weather_context = {
            "avg_temp_7d": avg_temp,
            "sum_precipitation_7d": sum_precip,
            "is_harvest_season": is_harvest_season,
            "harvest_season_label_vi": harvest_label_vi,
            "weather_summary_vi": weather_summary_vi,
        }
    else:
        weather_summary_vi = f"Vụ mùa: {harvest_label_vi}"
        weather_context = {
            "avg_temp_7d": 24.5,
            "sum_precipitation_7d": 0.0,
            "is_harvest_season": is_harvest_season,
            "harvest_season_label_vi": harvest_label_vi,
            "weather_summary_vi": weather_summary_vi,
        }

    return {
        "status": "OK",
        "commodity_code": comm.code,
        "commodity_name": comm.name,
        "province_code": prov.code,
        "province_name": prov.standard_name,
        "region": prov.region,
        "unit": comm.unit,
        "requested_horizon": horizon,
        "latest_actual_date": str(latest_obs.obs_date),
        "latest_actual_price": current_price,
        "farmer_summary": farmer_summary,
        "weather_context": weather_context,
        "selected_model_info": selected_model_info,
        "source_metadata": _extract_source_metadata(db, latest_obs),
        "recent_history_series": recent_history_series,
        "forecast_series": forecast_series,
    }


# ==============================================================================
# 5. GET /api/models/metrics
# ==============================================================================
@app.get("/api/models/metrics", tags=["Expert Mode & Backtesting"])
def get_expert_model_metrics_and_backtesting(
    commodity: str = Query(..., description="Mã mặt hàng nông sản (VD: CAFE_ROBUSTA)"),
    province: str = Query(..., description="Mã tỉnh/thành phố (VD: DL)"),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Phục vụ Chế độ Chuyên gia (FR-22, FR-44, FR-46):
    - Trả về bảng xếp hạng toàn bộ 7 mô hình (`NAIVE`, `SEASONAL_NAIVE`, `MOVING_AVG`, `PROPHET`,
      `RANDOM_FOREST`, `XGBOOST`, `LSTM`) từ bảng `model_run`.
    - Trả về chuỗi dữ liệu kiểm chứng ngược 30 ngày qua (`backtest_series`: các bản ghi trong bảng
      `forecast` có `actual_price IS NOT NULL`) để vẽ biểu đồ đối chiếu "Giá thực tế vs Giá mô hình dự báo".
    """
    comm, prov, supported_provinces = _resolve_commodity_and_province(db, commodity, province)

    model_runs = (
        db.query(ModelRun)
        .filter(
            ModelRun.commodity_id == comm.id,
            ModelRun.province_id == prov.id,
        )
        .order_by(ModelRun.mape.asc())
        .all()
    )
    if not model_runs:
        return _build_insufficient_data_payload(comm, prov, supported_provinces)

    # Nếu có nhiều lần chạy trong lịch sử, lấy bản ghi mới nhất cho mỗi model_type
    latest_by_type: Dict[str, ModelRun] = {}
    for mr in sorted(model_runs, key=lambda x: x.id):
        latest_by_type[mr.model_type] = mr

    sorted_runs = sorted(
        latest_by_type.values(),
        key=lambda x: (x.mape if x.mape is not None else 9999.0),
    )

    leaderboard: List[Dict[str, Any]] = []
    selected_model_entry: Optional[Dict[str, Any]] = None

    for rank_idx, mr in enumerate(sorted_runs, start=1):
        entry = {
            "rank": rank_idx,
            "model_run_id": mr.id,
            "model_type": mr.model_type,
            "is_baseline": mr.model_type in ("NAIVE", "SEASONAL_NAIVE", "MOVING_AVG"),
            "mae": round(float(mr.mae), 4) if mr.mae is not None else None,
            "rmse": round(float(mr.rmse), 4) if mr.rmse is not None else None,
            "mape": round(float(mr.mape), 4) if mr.mape is not None else None,
            "train_start_date": str(mr.train_start_date),
            "train_end_date": str(mr.train_end_date),
            "test_start_date": str(mr.test_start_date),
            "test_end_date": str(mr.test_end_date),
            "train_record_count": mr.train_record_count,
            "hyperparameters": mr.hyperparameters,
            "is_selected": bool(mr.is_selected),
            "created_at": mr.created_at.isoformat() if mr.created_at else None,
        }
        leaderboard.append(entry)
        if mr.is_selected:
            selected_model_entry = entry

    # Truy vấn dữ liệu Backtesting 30 ngày qua (actual_price IS NOT NULL - FR-44)
    backtest_rows = (
        db.query(Forecast)
        .filter(
            Forecast.commodity_id == comm.id,
            Forecast.province_id == prov.id,
            Forecast.actual_price.is_not(None),
        )
        .order_by(Forecast.target_date.asc())
        .all()
    )

    backtest_series: List[Dict[str, Any]] = []
    y_true_bt: List[float] = []
    y_pred_bt: List[float] = []

    for fc in backtest_rows:
        act_val = float(fc.actual_price)
        pred_val = float(fc.yhat)
        err_val = pred_val - act_val
        abs_pct_err = (abs(err_val) / act_val * 100.0) if act_val > 0 else 0.0
        y_true_bt.append(act_val)
        y_pred_bt.append(pred_val)
        backtest_series.append(
            {
                "target_date": str(fc.target_date),
                "horizon": fc.horizon,
                "actual_price": round(act_val, 2),
                "predicted_price": round(pred_val, 2),
                "lower_bound": round(float(fc.lower_bound), 2) if fc.lower_bound is not None else round(pred_val, 2),
                "upper_bound": round(float(fc.upper_bound), 2) if fc.upper_bound is not None else round(pred_val, 2),
                "error_amount": round(err_val, 2),
                "abs_pct_error": round(abs_pct_err, 4),
            }
        )

    bt_metrics = (
        compute_all_metrics(np.array(y_true_bt), np.array(y_pred_bt))
        if y_true_bt
        else {"mae": 0.0, "rmse": 0.0, "mape": 0.0}
    )

    return {
        "status": "OK",
        "commodity_code": comm.code,
        "commodity_name": comm.name,
        "province_code": prov.code,
        "province_name": prov.standard_name,
        "unit": comm.unit,
        "total_models_evaluated": len(leaderboard),
        "selected_model": selected_model_entry,
        "models_leaderboard": leaderboard,
        "backtest_summary": {
            "backtest_days": len(backtest_series),
            "origin_date": backtest_series[0]["target_date"] if backtest_series else None,
            "end_date": backtest_series[-1]["target_date"] if backtest_series else None,
            "mae": bt_metrics["mae"],
            "rmse": bt_metrics["rmse"],
            "mape": bt_metrics["mape"],
        },
        "backtest_series": backtest_series,
    }


# ==============================================================================
# 6. GET /api/export/csv
# ==============================================================================
@app.get("/api/export/csv", tags=["Data Export"])
def export_series_to_csv(
    commodity: str = Query(..., description="Mã mặt hàng nông sản (VD: CAFE_ROBUSTA)"),
    province: str = Query(..., description="Mã tỉnh/thành phố (VD: DL)"),
    include_forecast: bool = Query(default=True, description="Bao gồm cả dữ liệu dự báo tương lai"),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """
    Xuất dữ liệu chuỗi giá lịch sử và kết quả dự báo ra định dạng CSV (UTF-8-SIG có BOM
    hỗ trợ mở trực tiếp trong Microsoft Excel tiếng Việt) kèm cột nguồn thu thập và cờ nội suy (FR-23).
    """
    comm, prov, _ = _resolve_commodity_and_province(db, commodity, province)
    sources_by_id = {s.id: s for s in db.query(DataSource).all()}

    obs_rows = (
        db.query(PriceObservation)
        .filter(
            PriceObservation.commodity_id == comm.id,
            PriceObservation.province_id == prov.id,
        )
        .order_by(PriceObservation.obs_date.asc())
        .all()
    )
    if not obs_rows:
        raise HTTPException(
            status_code=404,
            detail=INSUFFICIENT_DATA_MSG_VI,
        )

    output = io.StringIO()
    # Ghi UTF-8 BOM để Excel hiển thị tiếng Việt có dấu chính xác
    output.write("\ufeff")
    writer = csv.writer(output)
    writer.writerow(
        [
            "date",
            "record_type",
            "commodity_code",
            "commodity_name",
            "province_code",
            "province_name",
            "unit",
            "actual_price",
            "forecast_yhat",
            "lower_bound",
            "upper_bound",
            "is_interpolated",
            "quality_flag",
            "source_name",
            "source_url",
        ]
    )

    for r in obs_rows:
        src = sources_by_id.get(r.source_id)
        writer.writerow(
            [
                str(r.obs_date),
                "HISTORICAL",
                comm.code,
                comm.name,
                prov.code,
                prov.standard_name,
                comm.unit,
                f"{float(r.price):.2f}",
                "",
                "",
                "",
                "TRUE" if r.is_interpolated else "FALSE",
                r.quality_flag,
                src.name if src else "Nguồn nông sản",
                r.source_url,
            ]
        )

    if include_forecast:
        latest_date = obs_rows[-1].obs_date
        fc_rows = (
            db.query(Forecast)
            .filter(
                Forecast.commodity_id == comm.id,
                Forecast.province_id == prov.id,
                Forecast.actual_price.is_(None),
                Forecast.target_date > latest_date,
            )
            .order_by(Forecast.target_date.asc())
            .all()
        )
        for fc in fc_rows:
            writer.writerow(
                [
                    str(fc.target_date),
                    "FORECAST",
                    comm.code,
                    comm.name,
                    prov.code,
                    prov.standard_name,
                    comm.unit,
                    "",
                    f"{float(fc.yhat):.2f}",
                    f"{float(fc.lower_bound):.2f}" if fc.lower_bound is not None else "",
                    f"{float(fc.upper_bound):.2f}" if fc.upper_bound is not None else "",
                    "FALSE",
                    "FORECAST",
                    f"Model Run #{fc.model_run_id}",
                    "",
                ]
            )

    output.seek(0)
    filename = f"agri_price_{comm.code.lower()}_{prov.code.lower()}.csv"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers=headers,
    )


# ==============================================================================
# 7. GET /api/alerts, POST /api/alerts/rules, POST /api/subscriptions, DELETE /api/subscriptions/{sub_id}
# ==============================================================================
@app.get("/api/alerts", tags=["Alerts & Subscriptions"])
def get_alerts_and_rules(
    commodity: Optional[str] = Query(default=None, description="Lọc theo mã mặt hàng nông sản"),
    province: Optional[str] = Query(default=None, description="Lọc theo mã tỉnh/thành"),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Trả về danh sách các sự kiện cảnh báo đã kích hoạt (`alert_event`),
    danh sách quy tắc cảnh báo (`alert_rule`) và danh sách người đăng ký nhận tin (`subscriber`).
    """
    commodities_by_id = {c.id: c for c in db.query(Commodity).all()}
    provinces_by_id = {p.id: p for p in db.query(Province).all()}
    commodities_by_code = {c.code: c for c in commodities_by_id.values()}
    provinces_by_code = {p.code: p for p in provinces_by_id.values()}

    events_query = db.query(AlertEvent)
    rules_query = db.query(AlertRule)

    if commodity:
        c_obj = commodities_by_code.get(commodity.strip().upper())
        if c_obj:
            events_query = events_query.filter(AlertEvent.commodity_id == c_obj.id)
            rules_query = rules_query.filter(AlertRule.commodity_id == c_obj.id)

    if province:
        p_obj = provinces_by_code.get(province.strip().upper())
        if p_obj:
            events_query = events_query.filter(AlertEvent.province_id == p_obj.id)
            rules_query = rules_query.filter(
                (AlertRule.province_id == p_obj.id) | (AlertRule.province_id.is_(None))
            )

    events = events_query.order_by(AlertEvent.target_date.desc(), AlertEvent.id.desc()).all()
    rules = rules_query.order_by(AlertRule.id.asc()).all()
    subscribers = db.query(Subscriber).filter(Subscriber.is_active.is_(True)).order_by(Subscriber.id.desc()).all()

    formatted_events = [
        {
            "id": ev.id,
            "rule_id": ev.rule_id,
            "commodity_id": ev.commodity_id,
            "commodity_code": commodities_by_id[ev.commodity_id].code if ev.commodity_id in commodities_by_id else "",
            "commodity_name": commodities_by_id[ev.commodity_id].name if ev.commodity_id in commodities_by_id else "",
            "province_id": ev.province_id,
            "province_code": provinces_by_id[ev.province_id].code if ev.province_id in provinces_by_id else "",
            "province_name": provinces_by_id[ev.province_id].standard_name if ev.province_id in provinces_by_id else "",
            "target_date": str(ev.target_date),
            "change_pct": ev.change_pct,
            "message": ev.message,
            "sent_status": ev.sent_status,
            "created_at": ev.created_at.isoformat() if ev.created_at else None,
        }
        for ev in events
    ]

    formatted_rules = [
        {
            "id": r.id,
            "commodity_id": r.commodity_id,
            "commodity_code": commodities_by_id[r.commodity_id].code if r.commodity_id in commodities_by_id else "",
            "commodity_name": commodities_by_id[r.commodity_id].name if r.commodity_id in commodities_by_id else "",
            "province_id": r.province_id,
            "province_code": provinces_by_id[r.province_id].code if r.province_id in provinces_by_id else None,
            "province_name": (
                provinces_by_id[r.province_id].standard_name
                if r.province_id in provinces_by_id
                else "Toàn vùng trồng trọng điểm"
            ),
            "threshold_pct": r.threshold_pct,
            "window_days": r.window_days,
            "channel": r.channel,
            "is_active": r.is_active,
        }
        for r in rules
    ]

    formatted_subscribers = [
        {
            "id": s.id,
            "contact_info": s.contact_info,
            "channel": s.channel,
            "commodity_code": commodities_by_id[s.commodity_id].code if s.commodity_id in commodities_by_id else None,
            "commodity_name": (
                commodities_by_id[s.commodity_id].name
                if s.commodity_id in commodities_by_id
                else "Tất cả nông sản"
            ),
            "province_code": provinces_by_id[s.province_id].code if s.province_id in provinces_by_id else None,
            "province_name": (
                provinces_by_id[s.province_id].standard_name
                if s.province_id in provinces_by_id
                else "Tất cả tỉnh/thành"
            ),
            "is_active": s.is_active,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in subscribers
    ]

    return {
        "status": "OK",
        "events_count": len(formatted_events),
        "rules_count": len(formatted_rules),
        "active_subscribers_count": len(formatted_subscribers),
        "events": formatted_events,
        "rules": formatted_rules,
        "subscribers": formatted_subscribers,
    }


@app.post("/api/alerts/rules", tags=["Alerts & Subscriptions"], status_code=201)
def create_alert_rule(
    payload: AlertRuleCreateRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Tạo mới một quy tắc cảnh báo biến động giá (`alert_rule` - FR-24) và tự động đánh giá cảnh báo ngay.
    """
    comm = db.query(Commodity).filter(Commodity.code == payload.commodity_code).first()
    if not comm:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy mã nông sản '{payload.commodity_code}'.")

    prov_id: Optional[int] = None
    prov_name = "Toàn vùng trồng trọng điểm"
    if payload.province_code:
        prov = db.query(Province).filter(Province.code == payload.province_code).first()
        if not prov:
            raise HTTPException(status_code=404, detail=f"Không tìm thấy mã tỉnh/thành '{payload.province_code}'.")
        prov_id = prov.id
        prov_name = prov.standard_name

    rule = AlertRule(
        commodity_id=comm.id,
        province_id=prov_id,
        threshold_pct=payload.threshold_pct,
        window_days=payload.window_days,
        channel=payload.channel.upper(),
        is_active=True,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)

    eval_summary = evaluate_and_trigger_alerts(db, force_check_all_thresholds=False)

    return {
        "status": "CREATED",
        "rule": {
            "id": rule.id,
            "commodity_code": comm.code,
            "commodity_name": comm.name,
            "province_code": payload.province_code,
            "province_name": prov_name,
            "threshold_pct": rule.threshold_pct,
            "window_days": rule.window_days,
            "channel": rule.channel,
            "is_active": rule.is_active,
        },
        "evaluation_summary": eval_summary,
    }


@app.post("/api/subscriptions", tags=["Alerts & Subscriptions"], status_code=201)
def subscribe_alerts(
    payload: SubscriptionCreateRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Đăng ký nhận cảnh báo 1 bước không cần tài khoản/mật khẩu (FR-27, FR-53).
    """
    try:
        sub = create_passwordless_subscription(
            db=db,
            contact_info=payload.contact_info,
            channel=payload.channel,
            commodity_code=payload.commodity_code,
            province_code=payload.province_code,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {
        "status": "SUBSCRIBED",
        "message_vi": (
            f"Đăng ký nhận cảnh báo giá nông sản thành công qua {sub.channel} ({sub.contact_info}). "
            "Bà con không cần mật khẩu và có thể hủy bất cứ lúc nào."
        ),
        "subscription": {
            "id": sub.id,
            "contact_info": sub.contact_info,
            "channel": sub.channel,
            "commodity_id": sub.commodity_id,
            "province_id": sub.province_id,
            "is_active": sub.is_active,
            "created_at": sub.created_at.isoformat() if sub.created_at else None,
        },
    }


@app.delete("/api/subscriptions/{sub_id}", tags=["Alerts & Subscriptions"])
def unsubscribe_alerts(
    sub_id: int,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Hủy đăng ký nhận thông báo 1 bước (`is_active = False` - FR-27, FR-53).
    """
    sub = unsubscribe_by_id(db=db, sub_id=sub_id)
    if not sub:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy đăng ký với ID={sub_id}.")

    return {
        "status": "UNSUBSCRIBED",
        "message_vi": f"Đã hủy nhận thông báo cho '{sub.contact_info}' thành công.",
        "subscription": {
            "id": sub.id,
            "contact_info": sub.contact_info,
            "is_active": sub.is_active,
        },
    }


# ==============================================================================
# 8. GET /api/pipeline/status & POST /api/pipeline/run
# ==============================================================================
@app.get("/api/pipeline/status", tags=["Pipeline Orchestration"])
def get_pipeline_status_endpoint(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Trả về trạng thái vận hành toàn diện của hệ thống, ngày dữ liệu mới nhất (`data_freshness_date`),
    thống kê độ phủ từ `data_coverage_view` và lịch sử `pipeline_log` (FR-05, FR-28, FR-42).
    """
    orchestrator = PipelineOrchestrator(db=db)
    return orchestrator.get_pipeline_status()


@app.post("/api/pipeline/run", tags=["Pipeline Orchestration"])
def trigger_pipeline_run_endpoint(
    payload: Optional[PipelineRunRequest] = None,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Kích hoạt chạy cập nhật dữ liệu, dự báo và đánh giá cảnh báo thủ công (FR-28).
    """
    req = payload or PipelineRunRequest()
    orchestrator = PipelineOrchestrator(db=db)
    return orchestrator.trigger_manual_pipeline_run(
        mode=req.mode,
        commodity_code=req.commodity_code,
        province_code=req.province_code,
    )


@app.get("/api/pipeline/stability", tags=["Pipeline Orchestration"])
def check_pipeline_stability_endpoint(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Giám sát độ ổn định dữ liệu và mô hình (Data Drift & Model Drift - FR-29).
    """
    return monitor_data_and_model_stability(db=db)


# ==============================================================================
# 9. Phục vụ Giao diện Tĩnh SPA (ui/dist) nếu đã build (Phase 6 - Mục 2)
# ==============================================================================
BASE_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI_DIST_DIR = os.path.join(BASE_PROJECT_DIR, "ui", "dist")
UI_ASSETS_DIR = os.path.join(UI_DIST_DIR, "assets")

if os.path.isdir(UI_ASSETS_DIR):
    app.mount("/assets", StaticFiles(directory=UI_ASSETS_DIR), name="ui_assets")


@app.get("/", include_in_schema=False)
def serve_spa_index():
    """Phục vụ trang giao diện React SPA tại `/` nếu thư mục `ui/dist` tồn tại."""
    index_path = os.path.join(UI_DIST_DIR, "index.html")
    if os.path.isfile(index_path):
        return FileResponse(index_path)
    return {
        "service": "Agricultural Price Forecasting API (SRS v1.1)",
        "docs_url": "/docs",
        "ui_note": "Run `npm run build` in `ui/` or access the React UI container on port 5173.",
    }


