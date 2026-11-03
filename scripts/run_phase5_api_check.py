"""CLI Script to Verify Phase 5 FastAPI Endpoints, Farmer Translation, Alert Engine & Latency (SRS v1.1).

Thực thi tuần tự:
1. Khởi tạo các quy tắc cảnh báo thực tế (`ensure_practical_alert_rules`) và kích hoạt
   `evaluate_and_trigger_alerts()` trên CSDL PostgreSQL thật để bảng `alert_event` có dữ liệu mẫu.
2. Sử dụng `fastapi.testclient.TestClient` kiểm tra toàn bộ các REST API trong `api/main.py`.
3. Đo thời gian phản hồi (ms) của từng endpoint và kiểm chứng ràng buộc `< 3000ms` (NFR-01).
4. In báo cáo tổng hợp gồm:
   - Bảng độ trễ & trạng thái HTTP của tất cả các API.
   - Mẫu câu diễn giải ngôn ngữ đời thường cho nông dân (`headline_vi`, `confidence_label_vi`, `action_hint_vi`).
   - Danh sách các sự kiện cảnh báo (`alert_event`) đã kích hoạt và chống gửi trùng.
"""

import os
import sys
import time
from typing import List, Dict, Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from db.database import SessionLocal
from api.main import app
from api.alert_service import ensure_practical_alert_rules, evaluate_and_trigger_alerts


def run_phase5_verification() -> None:
    print("=" * 95)
    print("PHASE 5: KIỂM ĐỊNH FASTAPI BACKEND, TRÌNH DIỄN GIẢI NÔNG DÂN & HỆ THỐNG CẢNH BÁO (SRS v1.1)")
    print("=" * 95)

    # 1. Tạo quy tắc cảnh báo thực tế & kích hoạt đánh giá cảnh báo trên PostgreSQL
    db = SessionLocal()
    try:
        ensure_practical_alert_rules(db)
        first_eval = evaluate_and_trigger_alerts(db, force_check_all_thresholds=True)
        second_eval = evaluate_and_trigger_alerts(db, force_check_all_thresholds=False)
    finally:
        db.close()

    print(
        f"\n[1] Đánh giá Cảnh báo lần 1: Đã quét {first_eval['rules_evaluated']} quy tắc | "
        f"Kích hoạt mới: {first_eval['new_events_triggered']} | Bỏ qua trùng: {first_eval['skipped_duplicates']}"
    )
    print(
        f"[2] Đánh giá Cảnh báo lần 2 (Kiểm tra chống gửi trùng FR-26): "
        f"Kích hoạt mới: {second_eval['new_events_triggered']} | Bỏ qua trùng: {second_eval['skipped_duplicates']}"
    )

    client = TestClient(app)
    api_checks: List[Dict[str, Any]] = []

    def _call_and_measure(name: str, method: str, url: str, **kwargs) -> Any:
        t0 = time.perf_counter()
        if method == "GET":
            resp = client.get(url, **kwargs)
        elif method == "POST":
            resp = client.post(url, **kwargs)
        elif method == "DELETE":
            resp = client.delete(url, **kwargs)
        else:
            raise ValueError(f"Unsupported method {method}")
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        api_checks.append(
            {
                "name": name,
                "method": method,
                "url": url,
                "status_code": resp.status_code,
                "latency_ms": elapsed_ms,
                "pass_nfr01": elapsed_ms < 3000.0,
            }
        )
        return resp

    # 2. Gọi toàn bộ các API chính
    r_comm = _call_and_measure("Danh mục Nông sản & Tỉnh", "GET", "/api/commodities")
    r_over = _call_and_measure("Tổng quan KPI Dashboard", "GET", "/api/overview")
    r_prices_ok = _call_and_measure(
        "Giá lịch sử (Cà phê - Đắk Lắk)",
        "GET",
        "/api/prices?commodity=CAFE_ROBUSTA&province=DL&start_date=2025-01-01&end_date=2026-11-01",
    )
    r_prices_insuff = _call_and_measure(
        "Xử lý Tỉnh thiếu dữ liệu (Lúa - Lâm Đồng FR-37)",
        "GET",
        "/api/prices?commodity=LUA_IR50404&province=LD",
    )
    r_fc_cafe = _call_and_measure(
        "Dự báo 7 ngày & Ngôn ngữ Nông dân (Cà phê - Đắk Lắk)",
        "GET",
        "/api/forecast?commodity=CAFE_ROBUSTA&province=DL&horizon=7",
    )
    r_fc_tieu = _call_and_measure(
        "Dự báo 14 ngày & Ngôn ngữ Nông dân (Hồ tiêu - Gia Lai)",
        "GET",
        "/api/forecast?commodity=TIEU_DEN&province=GL&horizon=14",
    )
    r_fc_lua = _call_and_measure(
        "Dự báo 30 ngày & Ngôn ngữ Nông dân (Lúa - An Giang)",
        "GET",
        "/api/forecast?commodity=LUA_IR50404&province=AG&horizon=30",
    )
    r_metrics = _call_and_measure(
        "Chế độ Chuyên gia & Backtesting 30 ngày (Cà phê - Đắk Lắk)",
        "GET",
        "/api/models/metrics?commodity=CAFE_ROBUSTA&province=DL",
    )
    r_csv = _call_and_measure(
        "Xuất dữ liệu CSV kèm Dự báo (FR-23)",
        "GET",
        "/api/export/csv?commodity=CAFE_ROBUSTA&province=DL&include_forecast=true",
    )
    r_alerts = _call_and_measure("Danh sách Cảnh báo & Quy tắc", "GET", "/api/alerts")
    r_sub_create = _call_and_measure(
        "Đăng ký nhận tin 1 bước (FR-27, FR-53)",
        "POST",
        "/api/subscriptions",
        json={
            "contact_info": "nongdan.daklak@agri-forecast.vn",
            "channel": "EMAIL",
            "commodity_code": "CAFE_ROBUSTA",
            "province_code": "DL",
        },
    )
    sub_id = r_sub_create.json()["subscription"]["id"]
    r_sub_del = _call_and_measure(
        "Hủy đăng ký nhận tin 1 bước",
        "DELETE",
        f"/api/subscriptions/{sub_id}",
    )
    r_pipe_status = _call_and_measure("Trạng thái Pipeline & Độ phủ dữ liệu", "GET", "/api/pipeline/status")
    r_pipe_run = _call_and_measure(
        "Kích hoạt Pipeline thủ công (FR-28)",
        "POST",
        "/api/pipeline/run",
        json={"mode": "fast_update", "commodity_code": "CAFE_ROBUSTA", "province_code": "DL"},
    )

    # 3. In bảng tổng kết hiệu năng & trạng thái API
    print("\n" + "-" * 95)
    print(f"{'TÊN ENDPOINT KIỂM THỬ':<48} | {'METHOD':<6} | {'HTTP':<5} | {'LATENCY (ms)':<12} | {'NFR-01 (<3s)'}")
    print("-" * 95)
    for item in api_checks:
        status_str = "PASS" if item["pass_nfr01"] and item["status_code"] in (200, 201) else "FAIL"
        print(
            f"{item['name']:<48} | {item['method']:<6} | {item['status_code']:<5} | "
            f"{item['latency_ms']:>10.2f} ms | {status_str}"
        )
    print("-" * 95)

    # 4. In mẫu câu diễn giải ngôn ngữ đời thường cho nông dân lớn tuổi
    print("\n[3] MẪU DIỄN GIẢI NGÔN NGỮ TỰ NHIÊN CHO NÔNG DÂN LỚN TUỔI (FR-49, FR-50, FR-51):")
    for resp in (r_fc_cafe, r_fc_tieu, r_fc_lua):
        payload = resp.json()
        fs = payload["farmer_summary"]
        model_info = payload["selected_model_info"]
        print(f"  * {fs['commodity_name']} - {fs['province_name']} ({fs['horizon_days']} ngày tới):")
        print(f"    - Kết luận (Headline) : {fs['headline_vi']}")
        print(f"    - Gợi ý tham khảo     : {fs['action_hint_vi']}")
        print(
            f"    - Độ tin cậy (FR-51)  : [{fs['confidence_label_vi']}] ({fs['confidence_level']}) "
            f"- {fs['confidence_explanation_vi']}"
        )
        print(
            f"    - Mô hình đứng sau    : {model_info['model_type']} "
            f"(MAPE = {model_info['mape']}%, MAE = {model_info['mae']} VNĐ/kg)"
        )

    # 5. In kết quả xử lý tỉnh thiếu dữ liệu (FR-37)
    insuff_data = r_prices_insuff.json()
    print("\n[4] KIỂM TRA XỬ LÝ TỈNH KHÔNG ĐỦ DỮ LIỆU (FR-37):")
    print(f"  * Truy vấn: LUA_IR50404 tại Lâm Đồng (LD) -> status = {insuff_data['status']}")
    print(f"  * Thông báo: {insuff_data['message_vi']}")
    print(
        f"  * Các tỉnh hỗ trợ gợi ý: "
        f"{', '.join(p['name'] + ' (' + p['code'] + ')' for p in insuff_data['supported_provinces'])}"
    )

    # 6. In danh sách các sự kiện cảnh báo đã kích hoạt
    alerts_data = r_alerts.json()
    print(
        f"\n[5] TỔNG HỢP SỰ KIỆN CẢNH BÁO TRONG DATABASE (`alert_event`): "
        f"{alerts_data['events_count']} sự kiện | {alerts_data['rules_count']} quy tắc"
    )
    for ev in alerts_data["events"][:6]:
        print(
            f"  - [Event #{ev['id']} | Rule #{ev['rule_id']} | {ev['sent_status']}] "
            f"{ev['commodity_name']} ({ev['province_name']}) ngày {ev['target_date']} "
            f"({ev['change_pct']:+.2f}%): {ev['message'][:110]}..."
        )

    # Xác nhận tất cả API đều PASS
    assert all(c["pass_nfr01"] and c["status_code"] in (200, 201) for c in api_checks), (
        "Có API không đạt yêu cầu HTTP 200/201 hoặc vượt quá 3000ms!"
    )
    assert alerts_data["events_count"] > 0, "Bảng alert_event phải có ít nhất 1 sự kiện cảnh báo mẫu!"
    print("\n=> HOÀN TẤT KIỂM ĐỊNH PHASE 5 THÀNH CÔNG 100%!")


if __name__ == "__main__":
    run_phase5_verification()

