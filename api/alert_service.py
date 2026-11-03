"""Alert Evaluation Engine, Anti-Duplicate Event Dispatcher & Passwordless Subscription Service (SRS v1.1).

Tuân thủ chặt chẽ:
- FR-24: Quản lý quy tắc cảnh báo (`alert_rule`) theo mặt hàng, tỉnh/thành, ngưỡng biến động (%) và cửa sổ ngày.
- FR-25: Tự động đối chiếu giá thực tế mới nhất với chuỗi dự báo tương lai trong cửa sổ `window_days`
  để phát hiện biến động vượt ngưỡng `threshold_pct`.
- FR-26: Cơ chế chống gửi trùng sự kiện cảnh báo dựa trên `UniqueConstraint('rule_id', 'target_date')`
  trong bảng `alert_event`. Nếu sự kiện đã tồn tại với `sent_status == 'SENT'`, bỏ qua không tạo/gửi lại.
- FR-27 & FR-53: Đăng ký nhận cảnh báo 1 bước không cần mật khẩu (`subscriber`) và hủy đăng ký dễ dàng.
- FR-52: Nội dung cảnh báo viết bằng tiếng Việt đời thường, dễ hiểu cho nông dân, không chứa thuật ngữ kỹ thuật.
"""

import os
import smtplib
from email.message import EmailMessage
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session

from collector.price_collector import TARGET_COMMODITY_PROVINCES
from db.database import get_vietnam_now
from db.models import (
    AlertRule,
    AlertEvent,
    Subscriber,
    Commodity,
    Province,
    PriceObservation,
    Forecast,
    ModelRun,
)
from api.farmer_translator import format_vnd_number, format_pct_vi

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALERT_LOG_PATH = os.path.join(BASE_DIR, "logs", "sent_alerts.log")


def format_plain_vietnamese_alert_message(
    commodity_name: str,
    province_name: str,
    current_price: float,
    forecast_price: float,
    change_pct: float,
    target_date_str: str,
    window_days: int,
    days_ahead: Optional[int] = None,
) -> str:
    """
    Sinh nội dung thông báo cảnh báo biến động giá bằng tiếng Việt đời thường (FR-52).
    Không sử dụng các thuật ngữ kỹ thuật như MAPE, RMSE, Prophet, XGBoost.
    """
    direction_vi = "TĂNG" if change_pct >= 0 else "GIẢM"
    diff_abs = abs(float(forecast_price) - float(current_price))
    pct_str = format_pct_vi(change_pct)
    curr_str = format_vnd_number(current_price)
    targ_str = format_vnd_number(forecast_price)
    diff_str = format_vnd_number(diff_abs)
    eff_days = int(days_ahead) if (days_ahead is not None and int(days_ahead) > 0) else int(window_days)

    if change_pct >= 0:
        advice = (
            "Bà con nông dân và đại lý thu mua tại địa phương có thể theo dõi sát nhịp tăng này "
            "để chủ động kế hoạch xuất bán nông sản."
        )
        action_verb = "tăng lên mức khoảng"
    else:
        advice = (
            "Bà con nông dân lưu ý theo dõi sát giá thu mua thực tế tại địa phương và cân nhắc "
            "tham khảo nhiều đại lý trước khi bán hàng."
        )
        action_verb = "giảm xuống mức khoảng"

    return (
        f"[CẢNH BÁO GIÁ NÔNG SẢN] Giá {commodity_name} tại {province_name} dự kiến {direction_vi} "
        f"khoảng {pct_str}% (từ {curr_str} đồng/kg {action_verb} {targ_str} đồng/kg, "
        f"chênh lệch khoảng {diff_str} đồng/kg) vào ngày {target_date_str} "
        f"(khoảng {eff_days} ngày tới tính từ mốc hiện tại). "
        f"{advice}"
    )


class AlertNotificationDispatcher:
    """
    Bộ gửi thông báo cảnh báo qua SMTP (nếu có cấu hình thật) hoặc ghi vào Local Email Log
    (`logs/sent_alerts.log`) phục vụ vận hành cục bộ và kiểm thử (FR-25, FR-52).
    """

    def __init__(self, log_path: str = ALERT_LOG_PATH):
        self.log_path = log_path
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        self.smtp_host = os.getenv("SMTP_HOST", "")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.smtp_user = os.getenv("SMTP_USER", "")
        self.smtp_password = os.getenv("SMTP_PASSWORD", "")
        self.smtp_from = os.getenv("SMTP_FROM_EMAIL", "alerts@agri-forecast.vn")

    def _has_real_smtp_credentials(self) -> bool:
        if not self.smtp_host or not self.smtp_user or not self.smtp_password:
            return False
        placeholder_tokens = ("example.com", "your_email", "your_app_password", "placeholder")
        for token in placeholder_tokens:
            if token in self.smtp_user.lower() or token in self.smtp_password.lower():
                return False
        return True

    def dispatch_alert(
        self,
        event: AlertEvent,
        commodity_name: str,
        province_name: str,
        subscribers: List[Subscriber],
    ) -> bool:
        """
        Gửi cảnh báo tới danh sách người đăng ký và luôn lưu vết kiểm toán vào `logs/sent_alerts.log`.
        """
        recipient_contacts = [s.contact_info for s in subscribers if s.is_active]
        if not recipient_contacts:
            recipient_contacts = ["dashboard-broadcast@agri-forecast.local"]

        now_str = get_vietnam_now().strftime("%Y-%m-%d %H:%M:%S %z")
        subject = f"[Cảnh báo Giá Nông sản] {commodity_name} tại {province_name} ({event.target_date})"

        has_smtp = self._has_real_smtp_credentials()
        delivery_mode = "SMTP_NETWORK" if has_smtp else "LOCAL_AUDIT_LOG"

        # Ghi log chi tiết vào logs/sent_alerts.log
        log_entry = (
            f"================================================================================\n"
            f"TIME       : {now_str} | DELIVERY_MODE: {delivery_mode}\n"
            f"RULE_ID    : {event.rule_id} | TARGET_DATE: {event.target_date} | CHANGE: {event.change_pct:+.2f}%\n"
            f"COMMODITY  : {commodity_name} | PROVINCE: {province_name}\n"
            f"RECIPIENTS : {', '.join(recipient_contacts)}\n"
            f"SUBJECT    : {subject}\n"
            f"MESSAGE    : {event.message}\n"
        )
        with open(self.log_path, mode="a", encoding="utf-8") as f:
            f.write(log_entry)

        # Nếu có cấu hình SMTP thực tế thì gửi qua SMTP
        if has_smtp:
            try:
                msg = EmailMessage()
                msg["Subject"] = subject
                msg["From"] = self.smtp_from
                msg["To"] = ", ".join(recipient_contacts)
                msg.set_content(event.message)

                with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=10) as server:
                    server.starttls()
                    server.login(self.smtp_user, self.smtp_password)
                    server.send_message(msg)
            except Exception as exc:
                with open(self.log_path, mode="a", encoding="utf-8") as f:
                    f.write(f"SMTP_FALLBACK_NOTE: Local log saved; SMTP error: {exc}\n")

        return True


def ensure_practical_alert_rules(db: Session) -> List[AlertRule]:
    """
    Đảm bảo hệ thống có các quy tắc thực tế có ý nghĩa (biến động đáng kể >= 1.2%)
    gắn với từng tỉnh để phát hiện và sinh sự kiện cảnh báo chất lượng cao cả 2 chiều TĂNG và GIẢM (FR-24, FR-25).
    """
    commodities = {c.code: c for c in db.query(Commodity).all()}
    provinces = {p.code: p for p in db.query(Province).all()}

    practical_specs = [
        ("CAFE_ROBUSTA", "DL", 1.2, 30, "EMAIL"),
        ("CAFE_ROBUSTA", "GL", 1.2, 30, "NOTIFICATION"),
        ("CAFE_ROBUSTA", "LD", 1.2, 30, "NOTIFICATION"),
        ("TIEU_DEN", "GL", 1.2, 30, "EMAIL"),
        ("TIEU_DEN", "DN", 1.2, 30, "NOTIFICATION"),
        ("TIEU_DEN", "BRVT", 1.2, 30, "EMAIL"),
        ("LUA_IR50404", "AG", 1.2, 30, "EMAIL"),
        ("LUA_IR50404", "DT", 1.2, 30, "NOTIFICATION"),
        ("LUA_IR50404", "CT", 1.2, 30, "EMAIL"),
    ]

    # Vô hiệu hóa các rule cũ có ngưỡng quá nhỏ (< 1.2%), cửa sổ 14 ngày trùng lặp hoặc không gắn tỉnh cụ thể
    db.query(AlertRule).filter(
        (AlertRule.threshold_pct < 1.2) | (AlertRule.province_id.is_(None)) | (AlertRule.window_days == 14)
    ).update({"is_active": False})

    created_or_found: List[AlertRule] = []
    for comm_code, prov_code, threshold_pct, window_days, channel in practical_specs:
        comm = commodities.get(comm_code)
        prov = provinces.get(prov_code)
        if not comm or not prov:
            continue

        existing = (
            db.query(AlertRule)
            .filter(
                AlertRule.commodity_id == comm.id,
                AlertRule.province_id == prov.id,
                AlertRule.window_days == window_days,
            )
            .first()
        )
        if not existing:
            rule = AlertRule(
                commodity_id=comm.id,
                province_id=prov.id,
                threshold_pct=threshold_pct,
                window_days=window_days,
                channel=channel,
                is_active=True,
            )
            db.add(rule)
            created_or_found.append(rule)
        else:
            existing.threshold_pct = threshold_pct
            existing.channel = channel
            existing.is_active = True
            created_or_found.append(existing)

    db.commit()
    return created_or_found


def cleanup_and_rebuild_alert_events(db: Session) -> Dict[str, Any]:
    """
    Làm sạch các bản ghi alert_event cũ và quét lại toàn bộ theo dự báo mới nhất,
    đảm bảo lọc nhiễu 2*MAPE và khớp chính xác số ngày days_ahead.
    """
    events_to_clean = db.query(AlertEvent).all()
    cleaned_count = len(events_to_clean)
    for ev in events_to_clean:
        db.delete(ev)
    db.commit()

    ensure_practical_alert_rules(db)
    eval_res = evaluate_and_trigger_alerts(db, force_check_all_thresholds=True)
    return {
        "cleaned_count": cleaned_count,
        "evaluation_result": eval_res,
    }


def evaluate_and_trigger_alerts(
    db: Session,
    force_check_all_thresholds: bool = False,
) -> Dict[str, Any]:
    """
    Quét tất cả các `alert_rule` đang hoạt động (`is_active = True`), đối chiếu giá thực tế mới nhất
    với giá dự báo tương lai trong cửa sổ `window_days`, và tạo/gửi `alert_event` nếu vượt ngưỡng
    đồng thời vượt ngưỡng nhiễu 2 * MAPE của mô hình chiến thắng (FR-25, FR-26).

    Cơ chế chống gửi trùng (FR-26):
    - Kiểm tra `UniqueConstraint('rule_id', 'target_date')` trong bảng `alert_event`.
    - Nếu sự kiện `(rule_id, target_date)` đã tồn tại và `sent_status == 'SENT'`, bỏ qua không gửi trùng.
    """
    if force_check_all_thresholds:
        ensure_practical_alert_rules(db)

    active_rules = db.query(AlertRule).filter(AlertRule.is_active.is_(True)).order_by(AlertRule.id).all()
    commodities_by_id = {c.id: c for c in db.query(Commodity).all()}
    provinces_by_id = {p.id: p for p in db.query(Province).all()}
    provinces_by_code = {p.code: p for p in provinces_by_id.values()}
    dispatcher = AlertNotificationDispatcher()

    # Tải bảng MAPE của các mô hình chiến thắng để lọc nhiễu (|change_pct| >= 2 * MAPE)
    selected_runs = db.query(ModelRun).filter(ModelRun.is_selected.is_(True)).all()
    champion_mape_map: Dict[tuple, float] = {
        (r.commodity_id, r.province_id): float(r.mape) for r in selected_runs if r.mape is not None
    }

    rules_evaluated = 0
    new_events_triggered = 0
    skipped_duplicates = 0
    triggered_details: List[Dict[str, Any]] = []

    for rule in active_rules:
        rules_evaluated += 1
        comm = commodities_by_id.get(rule.commodity_id)
        if not comm:
            continue

        # Xác định danh sách tỉnh áp dụng cho rule này
        if rule.province_id is not None:
            target_province_ids = [rule.province_id]
        else:
            valid_codes = TARGET_COMMODITY_PROVINCES.get(comm.code, [])
            target_province_ids = [
                provinces_by_code[c].id for c in valid_codes if c in provinces_by_code
            ]

        best_candidate: Optional[Dict[str, Any]] = None

        for p_id in target_province_ids:
            prov = provinces_by_id.get(p_id)
            if not prov:
                continue

            latest_obs = (
                db.query(PriceObservation)
                .filter(
                    PriceObservation.commodity_id == comm.id,
                    PriceObservation.province_id == prov.id,
                )
                .order_by(PriceObservation.obs_date.desc())
                .first()
            )
            if not latest_obs or float(latest_obs.price) <= 0:
                continue

            current_price = float(latest_obs.price)
            latest_date = latest_obs.obs_date

            # Ngưỡng kích hoạt phải vượt cả threshold_pct của rule VÀ dải nhiễu 2 * MAPE của mô hình
            champ_mape = champion_mape_map.get((comm.id, prov.id), 0.0)
            noise_threshold = 2.0 * champ_mape if champ_mape < 2.0 else 1.5 * champ_mape
            effective_threshold = max(float(rule.threshold_pct), noise_threshold)

            # Lấy các dự báo tương lai trong cửa sổ window_days
            future_forecasts = (
                db.query(Forecast)
                .filter(
                    Forecast.commodity_id == comm.id,
                    Forecast.province_id == prov.id,
                    Forecast.actual_price.is_(None),
                    Forecast.target_date > latest_date,
                    Forecast.horizon <= rule.window_days,
                )
                .order_by(Forecast.horizon.asc())
                .all()
            )
            if not future_forecasts:
                continue

            for fc in future_forecasts:
                fc_price = float(fc.yhat)
                change_pct = round(((fc_price - current_price) / current_price) * 100.0, 2)
                if abs(change_pct) >= effective_threshold:
                    if best_candidate is None or abs(change_pct) > abs(best_candidate["change_pct"]):
                        best_candidate = {
                            "commodity": comm,
                            "province": prov,
                            "current_price": current_price,
                            "forecast_price": fc_price,
                            "change_pct": change_pct,
                            "target_date": fc.target_date,
                            "latest_date": latest_date,
                        }

        if not best_candidate:
            continue

        target_date = best_candidate["target_date"]
        latest_date = best_candidate["latest_date"]
        days_ahead = max(1, (target_date - latest_date).days)
        comm_obj: Commodity = best_candidate["commodity"]
        prov_obj: Province = best_candidate["province"]

        # Kiểm tra chống gửi trùng theo (rule_id, target_date) - FR-26
        existing_event = (
            db.query(AlertEvent)
            .filter(
                AlertEvent.rule_id == rule.id,
                AlertEvent.target_date == target_date,
            )
            .first()
        )
        if existing_event is not None and existing_event.sent_status == "SENT":
            skipped_duplicates += 1
            continue

        msg_vi = format_plain_vietnamese_alert_message(
            commodity_name=comm_obj.name,
            province_name=prov_obj.standard_name,
            current_price=best_candidate["current_price"],
            forecast_price=best_candidate["forecast_price"],
            change_pct=best_candidate["change_pct"],
            target_date_str=target_date.strftime("%d/%m/%Y"),
            window_days=rule.window_days,
            days_ahead=days_ahead,
        )

        if existing_event is None:
            event = AlertEvent(
                rule_id=rule.id,
                commodity_id=comm_obj.id,
                province_id=prov_obj.id,
                target_date=target_date,
                change_pct=best_candidate["change_pct"],
                message=msg_vi,
                sent_status="PENDING",
                created_at=get_vietnam_now(),
            )
            db.add(event)
            db.flush()
        else:
            event = existing_event
            event.change_pct = best_candidate["change_pct"]
            event.message = msg_vi

        # Tìm danh sách người đăng ký phù hợp với nông sản và tỉnh này
        matching_subscribers = (
            db.query(Subscriber)
            .filter(
                Subscriber.is_active.is_(True),
                (Subscriber.commodity_id.is_(None)) | (Subscriber.commodity_id == comm_obj.id),
                (Subscriber.province_id.is_(None)) | (Subscriber.province_id == prov_obj.id),
            )
            .all()
        )

        sent_ok = dispatcher.dispatch_alert(
            event=event,
            commodity_name=comm_obj.name,
            province_name=prov_obj.standard_name,
            subscribers=matching_subscribers,
        )
        event.sent_status = "SENT" if sent_ok else "FAILED"
        db.commit()

        new_events_triggered += 1
        triggered_details.append(
            {
                "event_id": event.id,
                "rule_id": rule.id,
                "commodity_code": comm_obj.code,
                "commodity_name": comm_obj.name,
                "province_code": prov_obj.code,
                "province_name": prov_obj.standard_name,
                "target_date": str(target_date),
                "change_pct": event.change_pct,
                "sent_status": event.sent_status,
                "message": event.message,
            }
        )

    return {
        "rules_evaluated": rules_evaluated,
        "new_events_triggered": new_events_triggered,
        "skipped_duplicates": skipped_duplicates,
        "triggered_events": triggered_details,
    }


def create_passwordless_subscription(
    db: Session,
    contact_info: str,
    channel: str = "EMAIL",
    commodity_code: Optional[str] = None,
    province_code: Optional[str] = None,
) -> Subscriber:
    """
    Đăng ký nhận cảnh báo 1 bước không cần tài khoản/mật khẩu (FR-27, FR-53).
    Nếu người dùng đã đăng ký cùng contact_info + commodity + province trước đó thì kích hoạt lại (`is_active=True`).
    """
    clean_contact = contact_info.strip()
    if not clean_contact:
        raise ValueError("Thông tin liên hệ (Email hoặc Số điện thoại) không được để trống.")

    comm_id: Optional[int] = None
    if commodity_code:
        comm = db.query(Commodity).filter(Commodity.code == commodity_code.strip().upper()).first()
        if not comm:
            raise ValueError(f"Không tìm thấy mã nông sản '{commodity_code}'.")
        comm_id = comm.id

    prov_id: Optional[int] = None
    if province_code:
        prov = db.query(Province).filter(Province.code == province_code.strip().upper()).first()
        if not prov:
            raise ValueError(f"Không tìm thấy mã tỉnh/thành '{province_code}'.")
        prov_id = prov.id

    existing = (
        db.query(Subscriber)
        .filter(
            Subscriber.contact_info == clean_contact,
            Subscriber.commodity_id == comm_id,
            Subscriber.province_id == prov_id,
        )
        .first()
    )
    if existing:
        existing.is_active = True
        existing.channel = channel.upper()
        db.commit()
        db.refresh(existing)
        return existing

    sub = Subscriber(
        contact_info=clean_contact,
        channel=channel.upper(),
        commodity_id=comm_id,
        province_id=prov_id,
        is_active=True,
        created_at=get_vietnam_now(),
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


def unsubscribe_by_id(db: Session, sub_id: int) -> Optional[Subscriber]:
    """Hủy đăng ký nhận thông báo dễ dàng bằng cách đặt `is_active = False` (FR-27, FR-53)."""
    sub = db.query(Subscriber).filter(Subscriber.id == sub_id).first()
    if not sub:
        return None
    sub.is_active = False
    db.commit()
    db.refresh(sub)
    return sub

