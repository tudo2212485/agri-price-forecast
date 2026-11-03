"""End-to-End Integration & Acceptance Test Suite for Phase 6 (SRS v1.1 - Mục 5.4, 6, 9).

Kiểm tra toàn diện 4 kịch bản nghiệm thu cuối cùng:
1. `test_end_to_end_pipeline_to_farmer_and_expert_ui_flow` (NFR-10, NFR-11):
   Kiểm tra luồng tích hợp đầu-cuối từ Dữ liệu -> Làm sạch & Đặc trưng -> Huấn luyện & Dự báo ->
   API Chế độ Nông dân (<= 3 bước: lấy danh mục -> chọn nông sản & tỉnh -> nhận kết quả tiếng Việt
   + dữ liệu đọc giọng nói) và API Chế độ Chuyên sâu (bảng 7 mô hình + backtesting).
2. `test_data_and_model_stability_monitoring` (FR-29):
   Kiểm tra hàm giám sát độ ổn định dữ liệu và mô hình (`monitor_data_and_model_stability`),
   xác nhận khả năng phát hiện lệch phân phối / sai số bất thường và ghi nhận vào `pipeline_log`.
3. `test_ui_build_and_accessibility_standards` (Mục 5.4, NFR-12):
   Chạy build giao diện React + Tailwind trong `ui/` để xác nhận biên dịch thành công 100% ra `ui/dist`,
   đồng thời kiểm tra mã nguồn UI có đầy đủ Chế độ Đơn giản/Chuyên sâu, nút đọc giọng nói (`speechSynthesis`),
   cỡ chữ `>= 18px` và nút bấm `>= 48px` (`min-h-[52px]`).
4. `test_docker_and_documentation_deliverables` (NFR-07, NFR-08, Mục 9):
   Xác nhận `docker-compose.yml`, `Dockerfile.api`, `ui/Dockerfile`, `docs/usability_test_report.md`,
   `docs/model_evaluation_report.json`, `docs/eda_summary.json` và `README.md` đều tồn tại đầy đủ.
"""

import os
import subprocess
from datetime import date, timedelta
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from api.main import app
from api.pipeline_runner import monitor_data_and_model_stability
from scripts.scheduler import run_daily_scheduled_pipeline
from db.database import get_db, get_vietnam_now
from db.models import (
    Commodity,
    Province,
    DataSource,
    PriceObservation,
    WeatherObservation,
    ModelRun,
    Forecast,
    PipelineLog,
)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _seed_e2e_series(db_session: Session):
    """Tạo chuỗi dữ liệu thực tế cho kiểm thử tích hợp đầu-cuối trên SQLite session."""
    comm = db_session.query(Commodity).filter(Commodity.code == "CAFE_ROBUSTA").first()
    prov = db_session.query(Province).filter(Province.code == "DL").first()
    p_src = db_session.query(DataSource).filter(DataSource.source_type == "PRICE").first()
    w_src = db_session.query(DataSource).filter(DataSource.source_type == "WEATHER").first()

    start_d = date(2026, 8, 1)
    for idx in range(75):
        obs_d = start_d + timedelta(days=idx)
        val = 114000.0 + idx * 40.0
        db_session.add(
            PriceObservation(
                obs_date=obs_d,
                commodity_id=comm.id,
                province_id=prov.id,
                source_id=p_src.id,
                price=Decimal(f"{val:.2f}"),
                raw_value=f"{int(val):,}",
                raw_unit="VNĐ/kg",
                source_url="https://giacaphe.com/gia-ca-phe-dak-lak/",
                is_interpolated=False,
                quality_flag="OK",
                review_flag=False,
                collected_at=get_vietnam_now(),
            )
        )
        db_session.add(
            WeatherObservation(
                obs_date=obs_d,
                province_id=prov.id,
                source_id=w_src.id,
                temp_max=29.0,
                temp_min=19.5,
                temp_mean=24.2,
                precipitation=2.5,
                humidity=76.0,
                collected_at=get_vietnam_now(),
            )
        )
    db_session.flush()

    models_spec = [
        ("LSTM", 490.0, 620.0, 0.42, True),
        ("XGBOOST", 530.0, 670.0, 0.46, False),
        ("RANDOM_FOREST", 610.0, 790.0, 0.53, False),
        ("NAIVE", 740.0, 920.0, 0.64, False),
        ("MOVING_AVG", 890.0, 1110.0, 0.78, False),
        ("PROPHET", 1180.0, 1450.0, 1.03, False),
        ("SEASONAL_NAIVE", 1350.0, 1690.0, 1.18, False),
    ]
    selected_run_id = None
    for m_type, mae, rmse, mape, is_sel in models_spec:
        mr = ModelRun(
            commodity_id=comm.id,
            province_id=prov.id,
            model_type=m_type,
            hyperparameters={"seed": 42},
            train_start_date=date(2023, 1, 1),
            train_end_date=date(2026, 9, 14),
            test_start_date=date(2026, 9, 15),
            test_end_date=date(2026, 10, 14),
            train_record_count=1200,
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

    max_d = start_d + timedelta(days=74)
    latest_price = 114000.0 + 74 * 40.0

    # 30 ngày Backtesting (actual_price != None)
    for h in range(1, 31):
        bt_date = max_d - timedelta(days=30 - h)
        act_p = 115500.0 + h * 40.0
        pred_p = act_p + 110.0
        db_session.add(
            Forecast(
                model_run_id=selected_run_id,
                commodity_id=comm.id,
                province_id=prov.id,
                generated_at=get_vietnam_now(),
                target_date=bt_date,
                horizon=h,
                yhat=Decimal(f"{pred_p:.2f}"),
                lower_bound=Decimal(f"{pred_p - 1000.0:.2f}"),
                upper_bound=Decimal(f"{pred_p + 1000.0:.2f}"),
                actual_price=Decimal(f"{act_p:.2f}"),
            )
        )

    # 30 ngày Dự báo tương lai (actual_price == None)
    for h in range(1, 31):
        fc_date = max_d + timedelta(days=h)
        yhat_val = latest_price * (1.0 + 0.002 * h)
        db_session.add(
            Forecast(
                model_run_id=selected_run_id,
                commodity_id=comm.id,
                province_id=prov.id,
                generated_at=get_vietnam_now(),
                target_date=fc_date,
                horizon=h,
                yhat=Decimal(f"{yhat_val:.2f}"),
                lower_bound=Decimal(f"{yhat_val - 1200.0:.2f}"),
                upper_bound=Decimal(f"{yhat_val + 1200.0:.2f}"),
                actual_price=None,
            )
        )

    db_session.commit()
    return comm, prov, selected_run_id


def test_end_to_end_pipeline_to_farmer_and_expert_ui_flow(db_session: Session):
    """
    1. Kiểm tra luồng tích hợp đầu-cuối (NFR-10, NFR-11):
    - Chế độ Nông dân hoàn thành trong <= 3 bước:
      + Bước 1: Lấy danh mục nông sản & tỉnh (`/api/commodities`)
      + Bước 2 & 3: Chọn nông sản `CAFE_ROBUSTA` + tỉnh `DL` + `horizon=7` (`/api/forecast`)
        -> Nhận kết quả tiếng Việt tự nhiên (`headline_vi`, `confidence_label_vi`, `action_hint_vi`)
        phục vụ hiển thị chữ lớn và đọc giọng nói tiếng Việt.
    - Chế độ Chuyên sâu (`/api/models/metrics`):
      + Nhận đủ 7 mô hình (1 mô hình `is_selected = True` có sai số thấp hơn Baseline)
      + Nhận đủ 30 ngày kiểm chứng ngược (`backtest_series`).
    """
    _seed_e2e_series(db_session)

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    client = TestClient(app)
    try:
        # Bước 1: Lấy danh mục
        r_step1 = client.get("/api/commodities")
        assert r_step1.status_code == 200
        comm_payload = r_step1.json()
        chosen_comm = comm_payload["commodities"][0]["code"]
        chosen_prov = comm_payload["commodities"][0]["supported_provinces"][0]["code"]
        assert chosen_comm == "CAFE_ROBUSTA"

        # Bước 2 & 3: Xem dự báo & dữ liệu đọc giọng nói cho Nông dân
        r_step2 = client.get(f"/api/forecast?commodity={chosen_comm}&province=DL&horizon=7")
        assert r_step2.status_code == 200
        fc_payload = r_step2.json()
        assert fc_payload["status"] == "OK"
        fs = fc_payload["farmer_summary"]
        assert "Cà phê" in fs["headline_vi"]
        assert "Đắk Lắk" in fs["headline_vi"]
        assert fs["confidence_label_vi"] in ("Khá chắc chắn", "Mức độ vừa phải", "Chỉ để tham khảo")
        assert len(fs["action_hint_vi"]) > 15
        assert len(fc_payload["forecast_series"]) == 7

        # Luồng Chế độ Chuyên sâu: Bảng 7 mô hình & Backtesting 30 ngày
        r_expert = client.get(f"/api/models/metrics?commodity={chosen_comm}&province=DL")
        assert r_expert.status_code == 200
        expert_payload = r_expert.json()
        assert expert_payload["total_models_evaluated"] == 7
        selected = expert_payload["selected_model"]
        assert selected is not None and selected["is_selected"] is True

        baselines = [m for m in expert_payload["models_leaderboard"] if m["is_baseline"]]
        best_baseline_mape = min(m["mape"] for m in baselines)
        assert selected["mape"] < best_baseline_mape
        assert len(expert_payload["backtest_series"]) == 30
    finally:
        app.dependency_overrides.clear()


def test_data_and_model_stability_monitoring(db_session: Session):
    """
    2. Kiểm tra giám sát độ ổn định dữ liệu và mô hình (FR-29):
    - Chạy `monitor_data_and_model_stability` và `run_daily_scheduled_pipeline` trên dữ liệu ổn định -> `STABLE`.
    - Giả lập biến động sốc dữ liệu (Data Drift) trên 14 ngày cuối -> hệ thống phát hiện `WARNING_DRIFT_DETECTED`
      và ghi nhận bản ghi vào bảng `pipeline_log`.
    """
    comm, prov, _ = _seed_e2e_series(db_session)

    # Kiểm tra khi dữ liệu ổn định
    report_stable = monitor_data_and_model_stability(db_session, z_score_threshold=3.0)
    assert report_stable["series_checked"] >= 1
    assert report_stable["overall_stability"] == "STABLE"

    # Kiểm tra chạy luồng lập lịch tự động
    flow_res = run_daily_scheduled_pipeline(mode="fast_update", db=db_session)
    assert flow_res["flow_status"] == "COMPLETED"

    # Giả lập cú sốc giá cực lớn (+50%) trong 14 ngày gần nhất để kiểm tra phát hiện Data Drift (FR-29)
    recent_obs = (
        db_session.query(PriceObservation)
        .filter(
            PriceObservation.commodity_id == comm.id,
            PriceObservation.province_id == prov.id,
        )
        .order_by(PriceObservation.obs_date.desc())
        .limit(14)
        .all()
    )
    for row in recent_obs:
        row.price = Decimal("195000.00")
    db_session.commit()

    report_drift = monitor_data_and_model_stability(db_session, z_score_threshold=1.5)
    assert report_drift["overall_stability"] == "WARNING_DRIFT_DETECTED"
    assert len(report_drift["drift_warnings"]) >= 1

    # Xác nhận đã ghi nhận vào bảng pipeline_log
    stability_logs = (
        db_session.query(PipelineLog)
        .filter(PipelineLog.task_name == "data_and_model_stability_monitor")
        .all()
    )
    assert len(stability_logs) >= 2
    assert all(lg.status == "SUCCESS" for lg in stability_logs)


def test_ui_build_and_accessibility_standards():
    """
    3. Kiểm tra build giao diện React + Tailwind và các tiêu chuẩn tiếp cận (Mục 5.4, NFR-12):
    - Chạy `npm run build` trong thư mục `ui/` và xác nhận `ui/dist/index.html` được sinh ra thành công.
    - Kiểm tra mã nguồn UI có đầy đủ 2 chế độ (Nông dân & Chuyên sâu), đọc giọng nói `speechSynthesis`,
      cỡ chữ `>= 18px` (`18px`, `20px`, `22px`), vùng chạm nút bấm lớn (`min-h-[52px]`), và `<dialog closedby="any">`.
    """
    ui_dir = os.path.join(BASE_DIR, "ui")
    npm_cmd = "npm.cmd" if os.name == "nt" else "npm"

    build_proc = subprocess.run(
        [npm_cmd, "run", "build"],
        cwd=ui_dir,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    assert build_proc.returncode == 0, f"Lỗi khi build UI: {build_proc.stderr}\n{build_proc.stdout}"

    dist_index = os.path.join(ui_dir, "dist", "index.html")
    assert os.path.isfile(dist_index), "File ui/dist/index.html phải tồn tại sau khi build!"

    app_jsx_path = os.path.join(ui_dir, "src", "App.jsx")
    farmer_jsx_path = os.path.join(ui_dir, "src", "components", "FarmerModeView.jsx")
    expert_jsx_path = os.path.join(ui_dir, "src", "components", "ExpertModeView.jsx")
    css_path = os.path.join(ui_dir, "src", "index.css")

    with open(app_jsx_path, encoding="utf-8") as f:
        app_code = f.read()
    with open(farmer_jsx_path, encoding="utf-8") as f:
        farmer_code = f.read()
    with open(expert_jsx_path, encoding="utf-8") as f:
        expert_code = f.read()
    with open(css_path, encoding="utf-8") as f:
        css_code = f.read()

    # Kiểm tra 2 chế độ giao diện & trợ giúp (FR-47, FR-54)
    assert "Chế độ Bà con Nông dân" in app_code
    assert "Chế độ Chuyên sâu" in app_code
    assert 'closedby="any"' in app_code

    # Kiểm tra đọc giọng nói tiếng Việt & vùng chạm nút lớn (FR-55, NFR-12)
    assert "speechSynthesis" in farmer_code
    assert "vi-VN" in farmer_code
    assert "min-h-[52px]" in farmer_code
    assert "Đọc kết quả bằng giọng nói" in farmer_code

    # Kiểm tra cỡ chữ >= 18px trong index.css (Mục 5.4)
    assert "18px" in css_code
    assert "20px" in css_code
    assert "22px" in css_code

    # Kiểm tra Chế độ Chuyên sâu có đủ bảng xếp hạng, Backtesting và Xuất CSV
    assert "Backtesting" in expert_code
    assert "data_coverage" in expert_code
    assert "CSV" in expert_code


def test_docker_and_documentation_deliverables():
    """
    4. Kiểm tra tính đầy đủ của các gói đóng gói Docker và tài liệu nghiệm thu (NFR-07, NFR-08, Mục 9):
    - `docker-compose.yml` (có đủ 3 services: `timescaledb`, `api`, `ui`), `Dockerfile.api`, `ui/Dockerfile`.
    - `docs/usability_test_report.md`, `docs/model_evaluation_report.json`, `docs/eda_summary.json`, `README.md`.
    """
    required_files = [
        "docker-compose.yml",
        "Dockerfile.api",
        os.path.join("ui", "Dockerfile"),
        os.path.join("docs", "usability_test_report.md"),
        os.path.join("docs", "model_evaluation_report.json"),
        os.path.join("docs", "eda_summary.json"),
        "README.md",
    ]
    for rel_path in required_files:
        abs_path = os.path.join(BASE_DIR, rel_path)
        assert os.path.isfile(abs_path), f"Thiếu file bắt buộc: {rel_path}"

    with open(os.path.join(BASE_DIR, "docker-compose.yml"), encoding="utf-8") as f:
        compose_text = f.read()
    assert "timescaledb:" in compose_text
    assert "api:" in compose_text
    assert "ui:" in compose_text

    with open(os.path.join(BASE_DIR, "docs", "usability_test_report.md"), encoding="utf-8") as f:
        usability_text = f.read()
    assert "U01" in usability_text and "U05" in usability_text
    assert "100%" in usability_text

