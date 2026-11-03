"""Automated Pytest Suite for Phase 5: FastAPI Backend, Farmer Translation, Alert Engine & Pipeline Status (SRS v1.1).

Bao gồm đầy đủ 6 bài kiểm thử trọng tâm:
1. `test_commodities_and_overview_endpoints`: Kiểm tra `/api/commodities` và `/api/overview` trả về HTTP 200,
   đầy đủ 3 nông sản, 8 tỉnh, và thời gian phản hồi `< 3.0s` (NFR-01).
2. `test_insufficient_data_province_handling`: Kiểm tra truy vấn cặp không hợp lệ (`LUA_IR50404` tại `LD`)
   trên `/api/prices` và `/api/forecast` trả về `INSUFFICIENT_DATA` và thông báo tiếng Việt thân thiện (FR-37).
3. `test_forecast_and_farmer_friendly_translation`: Kiểm tra `/api/forecast` với `horizon=7, 14, 30`
   trả về `lower_bound <= yhat <= upper_bound`, khối `farmer_summary` (`headline_vi`, `confidence_label_vi`) (FR-17, FR-49, FR-51),
   và truyền `horizon=99` bị từ chối với HTTP 422 (NFR-05).
4. `test_expert_metrics_and_backtesting_api`: Kiểm tra `/api/models/metrics` trả về bảng xếp hạng đủ 7 mô hình
   (có đúng 1 mô hình `is_selected = True`) và chuỗi `backtest_series` có cả `actual_price` lẫn `predicted_price` (FR-22, FR-44).
5. `test_alert_evaluation_no_duplicate_and_subscription`: Kiểm tra tạo quy tắc cảnh báo, chạy
   `evaluate_and_trigger_alerts()` 2 lần liên tiếp không sinh bản ghi trùng trong `alert_event` (FR-26);
   kiểm tra đăng ký và hủy đăng ký nhận thông báo 1 bước (FR-27, FR-53).
6. `test_csv_export_and_pipeline_status`: Kiểm tra `/api/export/csv` trả về nội dung CSV hợp lệ kèm nguồn (FR-23)
   và `/api/pipeline/status` trả về log cùng độ phủ dữ liệu (FR-28, FR-42).
"""

import time
from datetime import date, timedelta
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from api.main import app
from api.alert_service import evaluate_and_trigger_alerts
from db.database import get_db, get_vietnam_now
from db.models import (
    Commodity,
    Province,
    DataSource,
    PriceObservation,
    WeatherObservation,
    ModelRun,
    Forecast,
    AlertEvent,
)


@pytest.fixture(scope="function")
def seeded_api_client(db_session: Session):
    """
    Khởi tạo dữ liệu kiểm thử đầy đủ trên SQLite in-memory session và gắn dependency override cho FastAPI TestClient.
    """
    comm_cafe = db_session.query(Commodity).filter(Commodity.code == "CAFE_ROBUSTA").first()
    comm_tieu = db_session.query(Commodity).filter(Commodity.code == "TIEU_DEN").first()
    comm_lua = db_session.query(Commodity).filter(Commodity.code == "LUA_IR50404").first()

    prov_dl = db_session.query(Province).filter(Province.code == "DL").first()
    prov_gl = db_session.query(Province).filter(Province.code == "GL").first()
    prov_ag = db_session.query(Province).filter(Province.code == "AG").first()

    price_source = db_session.query(DataSource).filter(DataSource.source_type == "PRICE").first()
    weather_source = db_session.query(DataSource).filter(DataSource.source_type == "WEATHER").first()

    base_date = date(2026, 9, 1)
    # Seed 60 ngày giá lịch sử cho CAFE_ROBUSTA (DL), TIEU_DEN (GL), LUA_IR50404 (AG)
    series_configs = [
        (comm_cafe, prov_dl, 114000.0, 50.0),
        (comm_tieu, prov_gl, 142000.0, 40.0),
        (comm_lua, prov_ag, 7700.0, 5.0),
    ]

    for comm, prov, base_price, daily_step in series_configs:
        for i in range(60):
            d = base_date + timedelta(days=i)
            p_val = base_price + i * daily_step
            db_session.add(
                PriceObservation(
                    obs_date=d,
                    commodity_id=comm.id,
                    province_id=prov.id,
                    source_id=price_source.id,
                    price=Decimal(f"{p_val:.2f}"),
                    raw_value=f"{int(p_val):,}",
                    raw_unit="VNĐ/kg",
                    source_url="https://giacaphe.com/gia-ca-phe-dak-lak/",
                    is_interpolated=(i % 25 == 0),
                    quality_flag="INTERPOLATED" if (i % 25 == 0) else "OK",
                    review_flag=False,
                    collected_at=get_vietnam_now(),
                )
            )
            if comm.code == "CAFE_ROBUSTA":
                db_session.add(
                    WeatherObservation(
                        obs_date=d,
                        province_id=prov.id,
                        source_id=weather_source.id,
                        temp_max=29.5,
                        temp_min=20.0,
                        temp_mean=24.8,
                        precipitation=3.2,
                        humidity=78.0,
                        collected_at=get_vietnam_now(),
                    )
                )

    db_session.flush()

    # Seed đủ 7 mô hình trong bảng model_run cho CAFE_ROBUSTA tại Đắk Lắk (DL)
    all_7_models = [
        ("XGBOOST", 520.0, 680.0, 0.45, True),
        ("LSTM", 590.0, 740.0, 0.51, False),
        ("RANDOM_FOREST", 630.0, 810.0, 0.55, False),
        ("NAIVE", 780.0, 990.0, 0.68, False),
        ("MOVING_AVG", 950.0, 1180.0, 0.83, False),
        ("PROPHET", 1250.0, 1520.0, 1.09, False),
        ("SEASONAL_NAIVE", 1420.0, 1790.0, 1.24, False),
    ]
    selected_run_id = None
    for m_type, mae, rmse, mape, is_sel in all_7_models:
        mr = ModelRun(
            commodity_id=comm_cafe.id,
            province_id=prov_dl.id,
            model_type=m_type,
            hyperparameters={"seed": 42},
            train_start_date=date(2023, 1, 1),
            train_end_date=date(2026, 8, 31),
            test_start_date=date(2026, 9, 1),
            test_end_date=date(2026, 10, 30),
            train_record_count=1000,
            mae=mae,
            rmse=rmse,
            mape=mape,
            artifact_path=f"models/artifacts/CAFE_ROBUSTA_DL_{m_type}.pkl",
            is_selected=is_sel,
            created_at=get_vietnam_now(),
        )
        db_session.add(mr)
        db_session.flush()
        if is_sel:
            selected_run_id = mr.id

    max_obs_date = base_date + timedelta(days=59)  # 2026-10-30
    last_actual_price = 114000.0 + 59 * 50.0  # 116950.0

    # Seed 30 ngày Backtesting (actual_price != None) cho CAFE_ROBUSTA tại Đắk Lắk
    for h in range(1, 31):
        bt_date = max_obs_date - timedelta(days=30 - h)
        act_p = 115000.0 + h * 45.0
        pred_p = act_p + 120.0
        db_session.add(
            Forecast(
                model_run_id=selected_run_id,
                commodity_id=comm_cafe.id,
                province_id=prov_dl.id,
                generated_at=get_vietnam_now(),
                target_date=bt_date,
                horizon=h,
                yhat=Decimal(f"{pred_p:.2f}"),
                lower_bound=Decimal(f"{pred_p - 1200.0:.2f}"),
                upper_bound=Decimal(f"{pred_p + 1200.0:.2f}"),
                actual_price=Decimal(f"{act_p:.2f}"),
            )
        )

    # Seed 30 ngày Dự báo tương lai (actual_price == None) cho CAFE_ROBUSTA tại Đắk Lắk
    for h in range(1, 31):
        fc_date = max_obs_date + timedelta(days=h)
        # Tăng dần ~2.5% sau 7-14 ngày để kiểm thử cả farmer_summary lẫn alert_service
        yhat_val = last_actual_price * (1.0 + 0.0025 * h)
        db_session.add(
            Forecast(
                model_run_id=selected_run_id,
                commodity_id=comm_cafe.id,
                province_id=prov_dl.id,
                generated_at=get_vietnam_now(),
                target_date=fc_date,
                horizon=h,
                yhat=Decimal(f"{yhat_val:.2f}"),
                lower_bound=Decimal(f"{yhat_val - 1500.0:.2f}"),
                upper_bound=Decimal(f"{yhat_val + 1500.0:.2f}"),
                actual_price=None,
            )
        )

    db_session.commit()

    def _override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    client = TestClient(app)
    try:
        yield client, db_session
    finally:
        app.dependency_overrides.clear()


def test_commodities_and_overview_endpoints(seeded_api_client):
    """
    1. Kiểm tra `/api/commodities` và `/api/overview` trả về HTTP 200,
    đầy đủ 3 nông sản, 8 tỉnh, và thời gian phản hồi `< 3.0s` (NFR-01).
    """
    client, _ = seeded_api_client

    t0 = time.perf_counter()
    resp_comm = client.get("/api/commodities")
    elapsed_comm = time.perf_counter() - t0
    assert resp_comm.status_code == 200
    assert elapsed_comm < 3.0

    data_comm = resp_comm.json()
    assert data_comm["status"] == "OK"
    assert len(data_comm["commodities"]) == 3
    assert len(data_comm["provinces"]) == 8
    assert "CAFE_ROBUSTA" in data_comm["commodity_provinces_map"]
    assert len(data_comm["commodity_provinces_map"]["CAFE_ROBUSTA"]) == 4

    t1 = time.perf_counter()
    resp_over = client.get("/api/overview")
    elapsed_over = time.perf_counter() - t1
    assert resp_over.status_code == 200
    assert elapsed_over < 3.0

    data_over = resp_over.json()
    assert data_over["status"] == "OK"
    assert len(data_over["all_series_kpis"]) >= 1
    assert data_over["highest_volatility_region"] is not None
    assert "alerts_summary" in data_over


def test_insufficient_data_province_handling(seeded_api_client):
    """
    2. Kiểm tra truy vấn cặp không hợp lệ (ví dụ `LUA_IR50404` tại tỉnh `LD` - Lâm Đồng)
    trên `/api/prices` và `/api/forecast` trả về trạng thái `INSUFFICIENT_DATA`
    và thông báo tiếng Việt thân thiện (FR-37).
    """
    client, _ = seeded_api_client

    resp_prices = client.get("/api/prices?commodity=LUA_IR50404&province=LD")
    assert resp_prices.status_code == 200
    body_prices = resp_prices.json()
    assert body_prices["status"] == "INSUFFICIENT_DATA"
    assert "Chưa đủ dữ liệu lịch sử" in body_prices["message_vi"]
    supported_codes = [p["code"] for p in body_prices["supported_provinces"]]
    assert set(supported_codes) == {"AG", "DT", "CT"}

    resp_fc = client.get("/api/forecast?commodity=LUA_IR50404&province=LD&horizon=7")
    assert resp_fc.status_code == 200
    body_fc = resp_fc.json()
    assert body_fc["status"] == "INSUFFICIENT_DATA"
    assert "Chưa đủ dữ liệu lịch sử" in body_fc["message_vi"]


def test_forecast_and_farmer_friendly_translation(seeded_api_client):
    """
    3. Kiểm tra `/api/forecast` với `horizon=7, 14, 30` trả về chuỗi dự báo có
    `lower_bound <= yhat <= upper_bound` và khối `farmer_summary` chứa câu tiếng Việt rõ ràng
    (`headline_vi`, `confidence_label_vi`) (FR-17, FR-49, FR-51).
    Kiểm tra truyền `horizon=99` bị từ chối với HTTP 422 (NFR-05).
    """
    client, _ = seeded_api_client

    for h in (7, 14, 30):
        resp = client.get(f"/api/forecast?commodity=CAFE_ROBUSTA&province=DL&horizon={h}")
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["status"] == "OK"
        assert payload["requested_horizon"] == h
        assert len(payload["forecast_series"]) == h

        for point in payload["forecast_series"]:
            assert point["lower_bound"] <= point["yhat"] <= point["upper_bound"]

        farmer = payload["farmer_summary"]
        assert farmer["trend_direction"] in ("UP", "DOWN", "STABLE")
        assert "Cà phê" in farmer["headline_vi"]
        assert "Đắk Lắk" in farmer["headline_vi"]
        assert f"{h} ngày tới" in farmer["headline_vi"]
        assert farmer["confidence_label_vi"] in (
            "Khá chắc chắn",
            "Mức độ vừa phải",
            "Chỉ để tham khảo",
        )
        assert farmer["confidence_level"] in ("HIGH", "MEDIUM", "LOW")

    # Kiểm tra truyền horizon=99 ngoài miền [7..30] bị từ chối với HTTP 422 (NFR-05)
    resp_invalid = client.get("/api/forecast?commodity=CAFE_ROBUSTA&province=DL&horizon=99")
    assert resp_invalid.status_code == 422


def test_expert_metrics_and_backtesting_api(seeded_api_client):
    """
    4. Kiểm tra `/api/models/metrics` trả về bảng xếp hạng đủ 7 mô hình
    (có đúng 1 mô hình `is_selected = True`) và chuỗi `backtest_series` có cả
    `actual_price` lẫn `predicted_price` (FR-22, FR-44).
    """
    client, _ = seeded_api_client

    resp = client.get("/api/models/metrics?commodity=CAFE_ROBUSTA&province=DL")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "OK"
    assert data["total_models_evaluated"] == 7
    assert len(data["models_leaderboard"]) == 7

    selected_models = [m for m in data["models_leaderboard"] if m["is_selected"]]
    assert len(selected_models) == 1
    assert selected_models[0]["model_type"] == "XGBOOST"

    bt_series = data["backtest_series"]
    assert len(bt_series) == 30
    for row in bt_series:
        assert row["actual_price"] is not None and row["actual_price"] > 0
        assert row["predicted_price"] is not None and row["predicted_price"] > 0
        assert "error_amount" in row


def test_alert_evaluation_no_duplicate_and_subscription(seeded_api_client):
    """
    5. Kiểm tra tạo quy tắc cảnh báo, chạy `evaluate_and_trigger_alerts()` 2 lần liên tiếp —
    lần 2 tuyệt đối không sinh bản ghi trùng lặp trong `alert_event` (FR-26);
    kiểm tra đăng ký và hủy đăng ký nhận thông báo 1 bước (FR-27, FR-53).
    """
    client, db_session = seeded_api_client

    # Tạo quy tắc cảnh báo ngưỡng 1.0% trong 14 ngày cho CAFE_ROBUSTA tại Đắk Lắk
    resp_rule = client.post(
        "/api/alerts/rules",
        json={
            "commodity_code": "CAFE_ROBUSTA",
            "province_code": "DL",
            "threshold_pct": 1.0,
            "window_days": 14,
            "channel": "EMAIL",
        },
    )
    assert resp_rule.status_code == 201
    rule_data = resp_rule.json()
    assert rule_data["status"] == "CREATED"

    count_after_first = db_session.query(AlertEvent).count()
    assert count_after_first >= 1

    # Chạy evaluate_and_trigger_alerts() lần 2 liên tiếp -> không được tạo thêm bản ghi trùng (FR-26)
    second_eval = evaluate_and_trigger_alerts(db_session, force_check_all_thresholds=False)
    count_after_second = db_session.query(AlertEvent).count()
    assert second_eval["new_events_triggered"] == 0
    assert second_eval["skipped_duplicates"] >= 1
    assert count_after_second == count_after_first

    # Kiểm tra đăng ký nhận cảnh báo 1 bước không cần mật khẩu (FR-27, FR-53)
    resp_sub = client.post(
        "/api/subscriptions",
        json={
            "contact_info": "nongdan.test@example.com",
            "channel": "EMAIL",
            "commodity_code": "CAFE_ROBUSTA",
            "province_code": "DL",
        },
    )
    assert resp_sub.status_code == 201
    sub_body = resp_sub.json()
    assert sub_body["status"] == "SUBSCRIBED"
    sub_id = sub_body["subscription"]["id"]
    assert sub_body["subscription"]["is_active"] is True

    # Kiểm tra hủy đăng ký 1 bước
    resp_unsub = client.delete(f"/api/subscriptions/{sub_id}")
    assert resp_unsub.status_code == 200
    assert resp_unsub.json()["subscription"]["is_active"] is False


def test_csv_export_and_pipeline_status(seeded_api_client):
    """
    6. Kiểm tra `/api/export/csv` trả về nội dung CSV hợp lệ có header chuẩn và dữ liệu nguồn (FR-23);
    kiểm tra `/api/pipeline/status` trả về log và độ phủ dữ liệu (FR-28, FR-42).
    """
    client, _ = seeded_api_client

    resp_csv = client.get("/api/export/csv?commodity=CAFE_ROBUSTA&province=DL&include_forecast=true")
    assert resp_csv.status_code == 200
    assert "text/csv" in resp_csv.headers["content-type"]
    csv_text = resp_csv.text
    assert "record_type,commodity_code,commodity_name,province_code" in csv_text
    assert "HISTORICAL,CAFE_ROBUSTA" in csv_text
    assert "FORECAST,CAFE_ROBUSTA" in csv_text
    assert "https://giacaphe.com/gia-ca-phe-dak-lak/" in csv_text

    # Kích hoạt chạy pipeline thủ công để có bản ghi pipeline_log rồi kiểm tra /api/pipeline/status
    resp_run = client.post("/api/pipeline/run", json={"mode": "fast_update"})
    assert resp_run.status_code == 200
    assert resp_run.json()["status"] == "SUCCESS"

    resp_status = client.get("/api/pipeline/status")
    assert resp_status.status_code == 200
    status_body = resp_status.json()
    assert status_body["system_status"] == "HEALTHY"
    assert status_body["data_freshness_date"] == "2026-10-30"
    assert len(status_body["data_coverage"]) >= 3
    assert len(status_body["recent_pipeline_logs"]) >= 1

