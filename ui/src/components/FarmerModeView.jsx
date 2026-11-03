import React, { useState } from 'react';
import { SimpleDualLineChart, formatVnd } from './SvgCharts.jsx';
import { apiClient } from '../api.js';
import {
  formatDateVN,
  formatShortDateVi,
  getProvinceDisplayInfo,
  formatPlainWeatherSentence,
  formatActionHintForHorizon,
  getAlertSeverityInfo,
  formatConciseAlertMessage,
} from '../utils.js';

/**
 * Hình minh họa SVG trực quan cho 3 loại nông sản (Màn hình 1 - Bước 1/3):
 * - Cà phê nhân xô Robusta: Hạt cà phê rang nâu đậm
 * - Hồ tiêu đen: Chùm hạt tiêu đen trên cành lá
 * - Lúa tươi IR50404: Bông lúa vàng trĩu hạt
 */
function CommodityIllustration({ code }) {
  if (code === 'CAFE_ROBUSTA') {
    return (
      <svg
        viewBox="0 0 64 64"
        aria-hidden="true"
        className="w-16 h-16 shrink-0 rounded-[12px] bg-amber-100 p-2 border-2 border-amber-800/30"
      >
        <ellipse cx="26" cy="34" rx="14" ry="19" transform="rotate(-18 26 34)" fill="#6B3E26" />
        <path
          d="M22 17 C27 28, 23 40, 29 51"
          stroke="#FDE68A"
          strokeWidth="3"
          strokeLinecap="round"
          fill="none"
        />
        <ellipse cx="42" cy="31" rx="13" ry="18" transform="rotate(16 42 31)" fill="#4A2511" />
        <path
          d="M44 15 C39 26, 43 37, 38 47"
          stroke="#FDE68A"
          strokeWidth="2.8"
          strokeLinecap="round"
          fill="none"
        />
      </svg>
    );
  }

  if (code === 'TIEU_DEN') {
    return (
      <svg
        viewBox="0 0 64 64"
        aria-hidden="true"
        className="w-16 h-16 shrink-0 rounded-[12px] bg-emerald-100 p-2 border-2 border-emerald-800/30"
      >
        <path
          d="M32 10 L32 54"
          stroke="#15803D"
          strokeWidth="4"
          strokeLinecap="round"
        />
        <path
          d="M32 14 C44 10, 50 18, 40 24 C35 26, 32 20, 32 14 Z"
          fill="#16A34A"
        />
        <circle cx="24" cy="24" r="6" fill="#1F2937" stroke="#FFFFFF" strokeWidth="1.5" />
        <circle cx="40" cy="27" r="6" fill="#111827" stroke="#FFFFFF" strokeWidth="1.5" />
        <circle cx="23" cy="37" r="6.5" fill="#111827" stroke="#FFFFFF" strokeWidth="1.5" />
        <circle cx="39" cy="40" r="6" fill="#1F2937" stroke="#FFFFFF" strokeWidth="1.5" />
        <circle cx="32" cy="49" r="6.5" fill="#111827" stroke="#FFFFFF" strokeWidth="1.5" />
      </svg>
    );
  }

  // Mặc định: Bông lúa vàng (LUA_IR50404)
  return (
    <svg
      viewBox="0 0 64 64"
      aria-hidden="true"
      className="w-16 h-16 shrink-0 rounded-[12px] bg-amber-50 p-2 border-2 border-amber-600/40"
    >
      <path
        d="M32 56 Q32 30 36 10"
        stroke="#15803D"
        strokeWidth="3.5"
        strokeLinecap="round"
        fill="none"
      />
      <path
        d="M32 52 Q20 38 14 26"
        stroke="#16A34A"
        strokeWidth="3"
        strokeLinecap="round"
        fill="none"
      />
      <ellipse cx="26" cy="20" rx="5" ry="8" transform="rotate(-30 26 20)" fill="#D97706" />
      <ellipse cx="40" cy="18" rx="5" ry="8" transform="rotate(25 40 18)" fill="#F59E0B" />
      <ellipse cx="24" cy="31" rx="5" ry="8" transform="rotate(-30 24 31)" fill="#F59E0B" />
      <ellipse cx="41" cy="29" rx="5" ry="8" transform="rotate(25 41 29)" fill="#D97706" />
      <ellipse cx="26" cy="42" rx="5" ry="8" transform="rotate(-25 26 42)" fill="#D97706" />
      <ellipse cx="35" cy="11" rx="4.5" ry="7.5" transform="rotate(10 35 11)" fill="#F59E0B" />
    </svg>
  );
}

/**
 * CHẾ ĐỘ ĐƠN GIẢN - DÀNH CHO NÔNG DÂN LỚN TUỔI (Mặc định - Mục 5.4, FR-48..FR-55, NFR-11..NFR-13).
 * - Tương phản cao WCAG AA (>= 4.5:1), cỡ chữ >= 18px, tiêu đề >= 26px.
 * - Giá ở thẻ chọn nông sản >= 32px; Giá mới nhất ở màn kết quả >= 40px.
 * - Mọi nút bấm chính có kích thước tối thiểu >= 48px (min-h-[52px]), bo góc 12px, cách nhau >= 12px.
 * - Luồng 3 màn hình tuần tự: Bước 1/3 (Chọn nông sản) -> Bước 2/3 (Chọn tỉnh & số ngày) -> Bước 3/3 (Xem kết quả).
 * - Nút "Tiếp tục" ở Màn 1 và Màn 2 cố định ở đáy màn hình (sticky bottom-0).
 * - Tích hợp đọc to giọng nói tiếng Việt qua window.speechSynthesis (FR-55), báo rõ nếu thiếu giọng vi-VN.
 */
export default function FarmerModeView({
  commodities = [],
  provinces = [],
  overviewData = null,
  selectedCommodity,
  selectedProvince,
  horizon,
  onSelectCommodity,
  onSelectProvince,
  onSelectHorizon,
  onResetHome,
  forecastData,
  alertsData,
  loading,
  onRefreshAlerts,
}) {
  // Luồng 3 màn hình: 1 = Chọn nông sản, 2 = Chọn tỉnh & số ngày, 3 = Kết quả dự báo & cảnh báo
  const [currentStep, setCurrentStep] = useState(1);
  const [showMoreDetails, setShowMoreDetails] = useState(false);

  const [speaking, setSpeaking] = useState(false);
  const [speechNotice, setSpeechNotice] = useState('');

  // Trạng thái đăng ký nhận tin báo giá 1 bước không mật khẩu (FR-53)
  const [contactInput, setContactInput] = useState('');
  const [subChannel, setSubChannel] = useState('EMAIL');
  const [subStatusMsg, setSubStatusMsg] = useState('');
  const [subErrorMsg, setSubErrorMsg] = useState('');
  const [subSubmitting, setSubSubmitting] = useState(false);

  const currentCommObj =
    commodities.find((c) => c.code === selectedCommodity) || {
      code: selectedCommodity,
      name: 'Nông sản',
      supported_provinces: [],
    };

  const supportedProvs = currentCommObj.supported_provinces || [];
  const currentProvObj =
    provinces.find((p) => p.code === selectedProvince) ||
    supportedProvs.find((p) => p.code === selectedProvince) || {
      code: selectedProvince,
      name: forecastData?.province_name || selectedProvince,
    };
  const currentProvDisplay = getProvinceDisplayInfo(currentProvObj);

  // Đồng bộ aria-invalid theo chuẩn validate-input-after-interaction
  const syncAriaInvalid = (e) => {
    const el = e.target;
    if (el && typeof el.matches === 'function') {
      try {
        el.setAttribute('aria-invalid', el.matches(':user-invalid') ? 'true' : 'false');
      } catch {
        // Fallback nếu trình duyệt cũ
      }
    }
  };

  // Đọc to kết quả bằng giọng nói tiếng Việt (FR-55), kiểm tra rõ giọng vi-VN
  const handleSpeakSummary = () => {
    if (typeof window === 'undefined' || !('speechSynthesis' in window)) {
      setSpeechNotice(
        '⚠️ Trình duyệt trên thiết bị này chưa hỗ trợ tính năng đọc giọng nói tự động. Bà con vui lòng xem dòng chữ kết luận lớn ở trên nhé.'
      );
      return;
    }

    if (speaking) {
      window.speechSynthesis.cancel();
      setSpeaking(false);
      setSpeechNotice('⏹️ Đã dừng đọc giọng nói.');
      return;
    }

    const voices = window.speechSynthesis.getVoices ? window.speechSynthesis.getVoices() : [];
    const viVoice = voices.find(
      (v) => v.lang && (v.lang.toLowerCase().startsWith('vi') || v.name.toLowerCase().includes('vietnam'))
    );

    if (voices.length > 0 && !viVoice) {
      setSpeechNotice(
        '⚠️ Thiết bị hoặc trình duyệt của bà con hiện chưa cài đặt giọng đọc tiếng Việt (vi-VN). Bà con vui lòng đọc phần chữ kết luận lớn ở trên nhé.'
      );
      return;
    }

    const fs = forecastData?.farmer_summary;
    if (!fs) return;

    const localizedHint = formatActionHintForHorizon(fs.action_hint_vi, fs.horizon_days || horizon);
    const textToRead = [
      fs.headline_vi,
      `Giá mới nhất là ${formatVnd(fs.current_price)} đồng một ki-lô-gam.`,
      `Giá dự báo sau ${fs.horizon_days} ngày tới là khoảng ${formatVnd(fs.target_price)} đồng một ki-lô-gam.`,
      `Mức độ tin cậy: ${fs.confidence_label_vi}.`,
      localizedHint,
    ]
      .filter(Boolean)
      .join(' ');

    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(textToRead);
    utterance.lang = 'vi-VN';
    if (viVoice) {
      utterance.voice = viVoice;
    }
    utterance.rate = 0.9; // Tốc độ đọc chậm rãi, rõ ràng cho người lớn tuổi
    utterance.onstart = () => {
      setSpeaking(true);
      setSpeechNotice('🔊 Hệ thống đang đọc to kết quả dự báo bằng tiếng Việt...');
    };
    utterance.onend = () => {
      setSpeaking(false);
      setSpeechNotice('✅ Đã đọc xong kết quả dự báo.');
    };
    utterance.onerror = () => {
      setSpeaking(false);
      setSpeechNotice(
        '⚠️ Không thể phát giọng đọc tiếng Việt trên trình duyệt này. Bà con vui lòng xem chữ kết luận lớn ở trên nhé.'
      );
    };

    window.speechSynthesis.speak(utterance);
  };

  // Kiểm tra lỗi bằng tiếng Việt đời thường trước khi gửi đăng ký nhận tin
  const handleQuickSubscribe = async (e) => {
    e.preventDefault();
    setSubStatusMsg('');
    setSubErrorMsg('');

    const trimmed = contactInput.trim();
    if (!trimmed) {
      setSubErrorMsg(
        subChannel === 'EMAIL'
          ? 'Bà con vui lòng nhập địa chỉ Email (ví dụ: nongdan@gmail.com) vào ô bên trên.'
          : 'Bà con vui lòng nhập Số điện thoại (ví dụ: 0912345678) vào ô bên trên.'
      );
      return;
    }

    if (subChannel === 'EMAIL') {
      const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
      if (!emailRegex.test(trimmed)) {
        setSubErrorMsg(
          'Địa chỉ Email chưa đúng dạng (cần có ký tự @ và tên miền, ví dụ: nongdan.daklak@gmail.com).'
        );
        return;
      }
    } else {
      const digitsOnly = trimmed.replace(/[\s.-]/g, '');
      const phoneRegex = /^(0|\+84)\d{8,10}$/;
      if (!phoneRegex.test(digitsOnly)) {
        setSubErrorMsg(
          'Số điện thoại chưa đúng (vui lòng nhập 10 chữ số bắt đầu bằng số 0, ví dụ: 0912345678).'
        );
        return;
      }
    }

    setSubSubmitting(true);
    try {
      const res = await apiClient.createSubscription({
        contact_info: trimmed,
        channel: subChannel,
        commodity_code: selectedCommodity,
        province_code: selectedProvince,
      });
      setSubStatusMsg(`✅ ${res.message_vi}`);
      setContactInput('');
      if (onRefreshAlerts) onRefreshAlerts();
    } catch (err) {
      setSubErrorMsg(`Không thể gửi đăng ký lúc này: ${err.message}`);
    } finally {
      setSubSubmitting(false);
    }
  };

  const isInsufficient = forecastData?.status === 'INSUFFICIENT_DATA';
  const farmerSummary = forecastData?.farmer_summary;
  const sourceMeta = forecastData?.source_metadata;

  // Tìm điểm dự báo tại ngày đích để lấy lower_bound / upper_bound trực tiếp từ API (nếu có đủ)
  const forecastSeries = forecastData?.forecast_series || [];
  const targetPoint =
    forecastSeries.length > 0 ? forecastSeries[forecastSeries.length - 1] : null;
  const hasTargetBounds =
    targetPoint &&
    targetPoint.lower_bound !== null &&
    targetPoint.lower_bound !== undefined &&
    targetPoint.upper_bound !== null &&
    targetPoint.upper_bound !== undefined;

  // Cấu hình 3 màu ngữ nghĩa kèm ký hiệu: Tăng (xanh lá + ▲), Giảm (đỏ + ▼), Ổn định (xám + ■)
  const getTrendVisual = (changePctOrDirection) => {
    let dir = 'STABLE';
    if (typeof changePctOrDirection === 'string') {
      dir = changePctOrDirection;
    } else if (typeof changePctOrDirection === 'number') {
      if (changePctOrDirection >= 0.5) dir = 'UP';
      else if (changePctOrDirection <= -0.5) dir = 'DOWN';
    }

    if (dir === 'UP') {
      return {
        symbol: '▲',
        label: 'Tăng',
        badgeClass: 'bg-[#DCFCE7] text-[#14532D] border-2 border-[#15803D]',
        cardBorderClass: 'border-[#15803D] bg-[#F0FDF4]',
      };
    }
    if (dir === 'DOWN') {
      return {
        symbol: '▼',
        label: 'Giảm',
        badgeClass: 'bg-[#FEE2E2] text-[#991B1B] border-2 border-[#B91C1C]',
        cardBorderClass: 'border-[#B91C1C] bg-[#FEF2F2]',
      };
    }
    return {
      symbol: '■',
      label: 'Ổn định',
      badgeClass: 'bg-[#F3F4F6] text-[#1F2937] border-2 border-[#4B5563]',
      cardBorderClass: 'border-[#4B5563] bg-[#F9FAFB]',
    };
  };

  const trendVisual = getTrendVisual(farmerSummary?.trend_direction);

  // Lọc tối đa 3 cảnh báo gần nhất của đúng nông sản + tỉnh đang chọn (hiện cả tăng, giảm và ổn định)
  const filteredAlerts = (alertsData?.events || [])
    .filter(
      (ev) =>
        ev.commodity_code === selectedCommodity && ev.province_code === selectedProvince
    )
    .slice(0, 3);

  return (
    <div className="space-y-5">
      {/* THANH CHỈ BÁO 3 BƯỚC DUY NHẤT (Không lặp lại huy hiệu hay chữ "Bước x/3" ở tiêu đề dưới) */}
      <nav
        aria-label="Các bước xem giá nông sản"
        className="bg-white p-3 sm:p-4 rounded-[12px] border-2 border-slate-300 shadow-sm"
      >
        <div className="grid grid-cols-3 gap-3">
          {[
            { step: 1, title: 'Bước 1/3: Nông sản' },
            { step: 2, title: 'Bước 2/3: Tỉnh & Ngày' },
            { step: 3, title: 'Bước 3/3: Kết quả' },
          ].map((item) => {
            const isCurrentStep = currentStep === item.step;
            return (
              <button
                key={item.step}
                type="button"
                onClick={() => setCurrentStep(item.step)}
                aria-current={isCurrentStep ? 'step' : undefined}
                className={`touch-target-btn min-h-[48px] px-2.5 sm:px-3 py-2 rounded-[12px] font-extrabold text-[15px] sm:text-base leading-tight text-center transition ${
                  isCurrentStep
                    ? 'bg-[#ECFDF5] text-[#14532D] border-[3px] border-[#14532D] shadow-sm'
                    : 'bg-slate-100 text-[#334155] border-2 border-slate-300 hover:bg-slate-200'
                }`}
              >
                {isCurrentStep ? `✓ ${item.title}` : item.title}
              </button>
            );
          })}
        </div>
      </nav>

      {/* ==========================================================================
          MÀN HÌNH 1 — CHỌN NÔNG SẢN
          ========================================================================== */}
      {currentStep === 1 && (
        <section
          aria-labelledby="step1-heading"
          className="bg-white p-5 sm:p-6 rounded-[12px] border-2 border-slate-300 shadow-sm space-y-5"
        >
          <div className="space-y-1">
            <h2
              id="step1-heading"
              className="text-[26px] sm:text-[28px] font-extrabold text-[#14171A] leading-snug"
            >
              Chọn loại nông sản bà con muốn xem giá
            </h2>
            <p className="text-[#334155] font-semibold">
              Bấm chọn 1 trong 3 loại nông sản bên dưới, rồi bấm nút <strong>&ldquo;Tiếp tục&rdquo;</strong>:
            </p>
          </div>

          {/* Danh sách 3 thẻ nông sản lớn xếp 1 cột dọc (khoảng cách 16px >= 12px) */}
          <div className="flex flex-col gap-4">
            {commodities.map((comm) => {
              const isSelected = comm.code === selectedCommodity;
              const kpiItem = (overviewData?.featured_commodity_kpis || []).find(
                (k) => k.commodity_code === comm.code
              );
              const latestPrice = kpiItem?.current_price;
              const latestDateShort = kpiItem?.latest_date
                ? formatShortDateVi(kpiItem.latest_date)
                : '';
              const changePct = kpiItem?.forecast_7d_change_pct ?? 0;
              const forecast7dPrice = kpiItem?.forecast_7d_price;
              const kpiProvName = kpiItem?.province_name || '';
              const trendInfo = getTrendVisual(changePct);

              return (
                <button
                  key={comm.code}
                  type="button"
                  onClick={() => onSelectCommodity(comm.code)}
                  aria-pressed={isSelected}
                  className={`touch-target-btn w-full p-4 sm:p-5 rounded-[12px] text-left transition flex flex-col gap-3 ${
                    isSelected
                      ? 'elderly-card-selected shadow-md'
                      : 'bg-white text-[#14171A] border-2 border-slate-300 hover:border-[#14532D] hover:bg-emerald-50/40'
                  }`}
                >
                  {/* Hàng trên: Hình minh họa SVG + Tên đầy đủ + Huy hiệu ✓ Đang chọn */}
                  <div className="flex flex-wrap sm:flex-nowrap items-start justify-between gap-2.5 w-full">
                    <div className="flex items-center gap-3 min-w-0">
                      <CommodityIllustration code={comm.code} />
                      <div className="min-w-0">
                        <div className="text-[21px] sm:text-[24px] font-extrabold text-[#14171A] leading-snug break-words">
                          {comm.name}
                        </div>
                        {kpiProvName && (
                          <div className="text-base font-bold text-[#334155]">
                            Vùng trọng điểm: {kpiProvName}
                          </div>
                        )}
                      </div>
                    </div>

                    <span
                      className={`shrink-0 px-3 py-1 rounded-[12px] text-base font-extrabold border-2 ${
                        isSelected
                          ? 'bg-[#14532D] text-white border-[#0F3F22]'
                          : 'bg-slate-100 text-[#14171A] border-slate-300'
                      }`}
                    >
                      {isSelected ? '✓ Đang chọn' : 'Chọn'}
                    </span>
                  </div>

                  {/* Hàng giữa: Giá mới nhất cỡ chữ >= 32px kèm ngày cập nhật (dd/mm) */}
                  {latestPrice !== undefined && latestPrice !== null && (
                    <div className="pt-1 border-t border-slate-200/90 flex flex-wrap items-baseline justify-between gap-2">
                      <div>
                        <span className="text-base font-bold text-[#334155] block">
                          Giá mới nhất {latestDateShort ? `(${latestDateShort})` : ''}:
                        </span>
                        <span className="text-[32px] sm:text-[36px] font-extrabold text-[#14171A] leading-tight">
                          {formatVnd(latestPrice)}
                        </span>{' '}
                        <span className="text-xl font-bold text-[#334155]">đồng/kg</span>
                      </div>

                      {/* Mũi tên xu hướng kèm màu ngữ nghĩa (Tăng ▲ xanh lá / Giảm ▼ đỏ / Ổn định ■ xám) */}
                      <div
                        className={`px-3.5 py-2 rounded-[12px] font-extrabold text-base ${trendInfo.badgeClass}`}
                      >
                        {trendInfo.symbol} 7 ngày tới: {trendInfo.label}{' '}
                        {changePct > 0 ? '+' : ''}
                        {String(changePct).replace('.', ',')}%
                        {forecast7dPrice
                          ? ` (~${formatVnd(forecast7dPrice)} đ/kg)`
                          : ''}
                      </div>
                    </div>
                  )}
                </button>
              );
            })}
          </div>

          {/* Nút lớn "Tiếp tục" cố định ở đáy màn hình (sticky bottom-0) để không bắt cuộn mới thấy */}
          <div className="sticky bottom-0 z-20 bg-white/95 backdrop-blur-sm pt-3 pb-3 -mx-5 sm:-mx-6 px-5 sm:px-6 -mb-5 sm:-mb-6 rounded-b-[12px] border-t-2 border-slate-300 shadow-[0_-4px_12px_rgba(0,0,0,0.08)]">
            <button
              type="button"
              onClick={() => {
                setCurrentStep(2);
                window.scrollTo({ top: 0, behavior: 'smooth' });
              }}
              className="touch-target-btn min-h-[54px] w-full px-5 py-3 rounded-[12px] font-extrabold text-[20px] sm:text-[22px] bg-[#C2410C] hover:bg-[#9A3412] text-white border-[3px] border-amber-900 shadow-md flex items-center justify-center gap-2.5"
            >
              <span>Tiếp tục: Chọn Tỉnh &amp; Số ngày</span>
              <span aria-hidden="true">➔</span>
            </button>
          </div>
        </section>
      )}

      {/* ==========================================================================
          MÀN HÌNH 2 — CHỌN TỈNH VÀ SỐ NGÀY
          ========================================================================== */}
      {currentStep === 2 && (
        <section
          aria-labelledby="step2-heading"
          className="bg-white p-5 sm:p-6 rounded-[12px] border-2 border-slate-300 shadow-sm space-y-5"
        >
          <div className="space-y-1">
            <h2
              id="step2-heading"
              className="text-[26px] sm:text-[28px] font-extrabold text-[#14171A] leading-snug"
            >
              Chọn Tỉnh và Số ngày dự báo
            </h2>
            <p className="text-[#334155] font-semibold">
              Nông sản đang chọn: <strong className="text-[#14532D]">{currentCommObj.name}</strong>
            </p>
          </div>

          {/* Danh sách các tỉnh có dữ liệu của nông sản đã chọn, xếp 1 cột dọc */}
          <div className="space-y-3">
            <p className="font-extrabold text-xl text-[#14171A]">
              1. Chọn Tỉnh / Vùng thu mua ({supportedProvs.length} tỉnh trồng chính):
            </p>
            <div className="flex flex-col gap-3">
              {supportedProvs.map((prov) => {
                const isSelected = prov.code === selectedProvince;
                const displayInfo = getProvinceDisplayInfo(prov);
                return (
                  <button
                    key={prov.code}
                    type="button"
                    onClick={() => onSelectProvince(prov.code)}
                    aria-pressed={isSelected}
                    className={`touch-target-btn min-h-[54px] w-full px-4 sm:px-5 py-3 rounded-[12px] font-extrabold text-xl text-left transition flex items-center justify-between gap-3 ${
                      isSelected
                        ? 'elderly-card-selected text-[#14532D] shadow-sm'
                        : 'bg-slate-50 text-[#14171A] border-2 border-slate-300 hover:border-[#14532D] hover:bg-emerald-50/40'
                    }`}
                  >
                    <div>
                      <span>📍 {displayInfo.primaryName}</span>
                      {displayInfo.subNote && (
                        <span className="block text-sm font-semibold text-[#334155] mt-0.5">
                          {displayInfo.subNote}
                        </span>
                      )}
                    </div>
                    <span
                      className={`px-3.5 py-1 rounded-[12px] text-base font-extrabold border-2 ${
                        isSelected
                          ? 'bg-[#14532D] text-white border-[#0F3F22]'
                          : 'bg-white text-[#334155] border-slate-300'
                      }`}
                    >
                      {isSelected ? '✓ Đang chọn' : 'Chọn'}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* 3 nút chọn số ngày: 7 ngày tới (mặc định), 14 ngày tới, 30 ngày tới */}
          <div className="space-y-3">
            <p className="font-extrabold text-xl text-[#14171A]">
              2. Chọn số ngày muốn xem dự báo:
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              {[
                { days: 7, label: '7 ngày tới' },
                { days: 14, label: '14 ngày tới' },
                { days: 30, label: '30 ngày tới' },
              ].map((opt) => {
                const active = Number(horizon) === opt.days;
                return (
                  <button
                    key={opt.days}
                    type="button"
                    onClick={() => onSelectHorizon(opt.days)}
                    aria-pressed={active}
                    className={`touch-target-btn min-h-[52px] px-4 py-3 rounded-[12px] font-extrabold text-xl transition ${
                      active
                        ? 'elderly-card-selected text-[#14532D] shadow-sm'
                        : 'bg-slate-50 text-[#14171A] border-2 border-slate-300 hover:border-[#14532D]'
                    }`}
                  >
                    {active ? `✓ ${opt.label}` : opt.label}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Nút "Quay lại" và Nút lớn "Tiếp tục / Xem giá" cố định ở đáy màn hình (sticky bottom-0) */}
          <div className="sticky bottom-0 z-20 bg-white/95 backdrop-blur-sm pt-3 pb-3 -mx-5 sm:-mx-6 px-5 sm:px-6 -mb-5 sm:-mb-6 rounded-b-[12px] border-t-2 border-slate-300 shadow-[0_-4px_12px_rgba(0,0,0,0.08)] flex flex-row items-center justify-between gap-3">
            <button
              type="button"
              onClick={() => {
                setCurrentStep(1);
                window.scrollTo({ top: 0, behavior: 'smooth' });
              }}
              className="touch-target-btn min-h-[52px] px-4 sm:px-5 py-2.5 rounded-[12px] font-extrabold text-lg sm:text-xl bg-slate-100 hover:bg-slate-200 text-[#14171A] border-2 border-slate-400 shrink-0"
            >
              ⬅ Quay lại
            </button>

            <button
              type="button"
              onClick={() => {
                setCurrentStep(3);
                window.scrollTo({ top: 0, behavior: 'smooth' });
              }}
              className="touch-target-btn min-h-[54px] flex-1 px-4 sm:px-6 py-3 rounded-[12px] font-extrabold text-[20px] sm:text-[22px] bg-[#C2410C] hover:bg-[#9A3412] text-white border-[3px] border-amber-900 shadow-md flex items-center justify-center gap-2 whitespace-nowrap"
            >
              <span>Xem giá</span>
              <span aria-hidden="true">➔</span>
            </button>
          </div>
        </section>
      )}

      {/* ==========================================================================
          MÀN HÌNH 3 — KẾT QUẢ VÀ BIỂU ĐỒ + ĐĂNG KÝ NHẬN TIN & CẢNH BÁO
          ========================================================================== */}
      {currentStep === 3 && (
        <div className="space-y-6">
          <section
            aria-labelledby="step3-heading"
            className="bg-white p-5 sm:p-6 rounded-[12px] border-2 border-slate-300 shadow-sm space-y-6"
          >
            {loading && (
              <div className="p-8 rounded-[12px] bg-[#ECFDF5] border-2 border-[#15803D] text-[#14532D] font-extrabold text-xl">
                ⏳ Đang tải dữ liệu giá và tính toán dự báo cho bà con...
              </div>
            )}

            {/* XỬ LÝ TỈNH CHƯA ĐỦ DỮ LIỆU (FR-37) */}
            {!loading && isInsufficient && (
              <div
                role="alert"
                className="p-6 rounded-[12px] bg-amber-50 border-2 border-amber-600 text-[#14171A] space-y-4"
              >
                <h2 id="step3-heading" className="text-[26px] font-extrabold text-amber-950">
                  ⚠️ Chưa đủ dữ liệu tại tỉnh này ({forecastData.province_name})
                </h2>
                <p className="text-xl font-semibold">{forecastData.message_vi}</p>
                <div className="flex flex-wrap gap-3 pt-2">
                  {(forecastData.supported_provinces || []).map((sp) => (
                    <button
                      key={sp.code}
                      type="button"
                      onClick={() => onSelectProvince(sp.code)}
                      className="touch-target-btn min-h-[52px] px-5 py-3 rounded-[12px] font-extrabold bg-[#14532D] text-white hover:bg-[#0F3F22]"
                    >
                      👉 Xem tại {sp.name}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* 8 THÀNH PHẦN THEO ĐÚNG THỨ TỰ TỪ TRÊN XUỐNG DƯỚI (Màn hình 3) */}
            {!loading && !isInsufficient && farmerSummary && (
              <div className="space-y-6">
                {/* (1) Tóm tắt lựa chọn ở đầu màn: tên nông sản · tỉnh · số ngày, kèm nút "Đổi lựa chọn" */}
                <div className="flex flex-wrap items-center justify-between gap-3 p-4 rounded-[12px] bg-slate-100 border-2 border-slate-300">
                  <div>
                    <span className="text-sm font-bold text-[#334155] block">
                      Đang xem kết quả dự báo cho:
                    </span>
                    <h2
                      id="step3-heading"
                      className="text-[22px] sm:text-[24px] font-extrabold text-[#14532D]"
                    >
                      {currentCommObj.name} · {currentProvDisplay.primaryName} · {horizon} ngày tới
                    </h2>
                    {currentProvDisplay.subNote && (
                      <span className="text-sm font-semibold text-[#334155]">
                        {currentProvDisplay.subNote}
                      </span>
                    )}
                  </div>
                  <button
                    type="button"
                    onClick={() => setCurrentStep(1)}
                    className="touch-target-btn min-h-[48px] px-4 py-2 rounded-[12px] font-extrabold bg-white hover:bg-slate-200 text-[#14171A] border-2 border-slate-400"
                  >
                    🔄 Đổi lựa chọn
                  </button>
                </div>

                {/* (2) Câu kết luận một dòng, in đậm, cỡ chữ lớn, đặt trong khung có màu viền theo xu hướng */}
                <div
                  className={`p-5 rounded-[12px] border-[3px] ${trendVisual.cardBorderClass} space-y-3`}
                >
                  <div className="inline-flex items-center px-3.5 py-1.5 rounded-[12px] font-extrabold text-lg border-2 bg-white text-[#14171A] border-slate-300">
                    {trendVisual.symbol} Xu hướng {farmerSummary.horizon_days} ngày tới:{' '}
                    {trendVisual.label} ({farmerSummary.change_pct > 0 ? '+' : ''}
                    {String(farmerSummary.change_pct).replace('.', ',')}%)
                  </div>
                  <p className="text-[26px] sm:text-[28px] leading-snug font-extrabold text-[#14171A]">
                    {farmerSummary.headline_vi}
                  </p>
                </div>

                {/* (3) Hai thẻ số đặt dọc:
                        - Giá mới nhất (cỡ chữ >= 40px) + ngày cập nhật
                        - Giá dự báo sau N ngày + chênh lệch (bỏ gạch chân) + khoảng dao động */}
                <div className="flex flex-col gap-4">
                  <div className="p-5 rounded-[12px] bg-white border-2 border-slate-300 shadow-sm">
                    <div className="text-lg font-bold text-[#334155]">
                      Giá mới nhất{' '}
                      {forecastData.latest_actual_date
                        ? `(Cập nhật ngày ${formatDateVN(forecastData.latest_actual_date)})`
                        : ''}
                    </div>
                    <div className="mt-1 flex items-baseline gap-2 flex-wrap">
                      <span className="text-[40px] sm:text-[44px] font-extrabold text-[#14171A] leading-none">
                        {formatVnd(farmerSummary.current_price)}
                      </span>
                      <span className="text-2xl font-bold text-[#334155]">đồng/kg</span>
                    </div>
                  </div>

                  <div className="p-5 rounded-[12px] bg-[#ECFDF5] border-2 border-[#15803D] shadow-sm space-y-2">
                    <div className="text-lg font-bold text-[#14532D]">
                      Giá dự báo sau {farmerSummary.horizon_days} ngày tới
                      {targetPoint?.date ? ` (ngày ${formatDateVN(targetPoint.date)})` : ''}
                    </div>
                    <div className="flex items-baseline gap-2 flex-wrap">
                      <span className="text-[36px] sm:text-[40px] font-extrabold text-[#14532D] leading-none">
                        {formatVnd(farmerSummary.target_price)}
                      </span>
                      <span className="text-2xl font-bold text-[#14532D]">đồng/kg</span>
                    </div>
                    <div className="text-xl font-extrabold text-[#14171A]">
                      Chênh lệch dự kiến:{' '}
                      <span className="text-[#14532D]">
                        {farmerSummary.change_amount > 0 ? '+' : ''}
                        {formatVnd(farmerSummary.change_amount)} đồng/kg (
                        {farmerSummary.change_pct > 0 ? '+' : ''}
                        {String(farmerSummary.change_pct).replace('.', ',')}%)
                      </span>
                    </div>
                    {hasTargetBounds && (
                      <p className="text-lg font-bold text-[#334155] pt-1">
                        ↔ Có thể dao động từ{' '}
                        <strong className="text-[#14171A]">
                          {formatVnd(Math.round(targetPoint.lower_bound / 100) * 100)}
                        </strong>{' '}
                        đến{' '}
                        <strong className="text-[#14171A]">
                          {formatVnd(Math.round(targetPoint.upper_bound / 100) * 100)}
                        </strong>{' '}
                        đồng/kg.
                      </p>
                    )}
                  </div>
                </div>

                {/* (4) Gợi ý hành động ngắn gọn theo đúng số ngày đang chọn (7, 14 hoặc 30 ngày) */}
                <div className="p-5 rounded-[12px] bg-amber-50 border-2 border-amber-500 text-[#14171A]">
                  <p className="text-xl font-bold leading-relaxed">
                    💡 <strong>Lời khuyên tham khảo:</strong>{' '}
                    {formatActionHintForHorizon(
                      farmerSummary.action_hint_vi,
                      farmerSummary.horizon_days || horizon
                    )}
                  </p>
                </div>

                {/* (5) Nút lớn "🔊 Đọc to" đặt ngay dưới phần gợi ý (cao >= 56px, kiểm tra giọng vi-VN) */}
                <div className="space-y-3">
                  <button
                    type="button"
                    onClick={handleSpeakSummary}
                    className="touch-target-btn min-h-[56px] w-full px-6 py-4 rounded-[12px] font-extrabold text-[22px] bg-[#C2410C] hover:bg-[#9A3412] text-white border-[3px] border-amber-950 shadow-md flex items-center justify-center gap-3"
                  >
                    <span aria-hidden="true" className="text-2xl">
                      {speaking ? '⏹️' : '🔊'}
                    </span>
                    <span>
                      {speaking
                        ? 'Dừng đọc giọng nói'
                        : 'Đọc to (Đọc kết quả bằng giọng nói)'}
                    </span>
                  </button>
                  {speechNotice && (
                    <div
                      role="status"
                      className="p-4 rounded-[12px] bg-white border-2 border-slate-400 font-bold text-[#14171A]"
                    >
                      {speechNotice}
                    </div>
                  )}
                </div>

                {/* (6) Biểu đồ đơn giản hóa */}
                <div className="bg-slate-50 p-3 sm:p-5 rounded-[12px] border-2 border-slate-300 space-y-3">
                  <h3 className="text-[22px] font-extrabold text-[#14171A]">
                    📈 Biểu đồ giá những ngày qua và dự báo sắp tới
                  </h3>
                  <SimpleDualLineChart
                    historySeries={forecastData.recent_history_series || []}
                    forecastSeries={forecastData.forecast_series || []}
                    unit={forecastData.unit || 'VNĐ/kg'}
                  />
                </div>

                {/* (7) Mục "Xem thêm": nút lớn >= 48px có mũi tên ▼/▲, bỏ chữ "Bấm để mở/đóng" nhỏ gạch chân */}
                <div className="bg-white rounded-[12px] border-2 border-slate-300 overflow-hidden">
                  <button
                    type="button"
                    onClick={() => setShowMoreDetails((prev) => !prev)}
                    aria-expanded={showMoreDetails}
                    className="touch-target-btn min-h-[54px] w-full px-5 py-3.5 font-extrabold text-xl text-[#14532D] bg-slate-100 hover:bg-slate-200 text-left flex items-center justify-between gap-3"
                  >
                    <span>📂 Xem thêm (Độ tin cậy, Thời tiết &amp; Nguồn dữ liệu)</span>
                    <span aria-hidden="true" className="text-2xl font-extrabold shrink-0">
                      {showMoreDetails ? '▲' : '▼'}
                    </span>
                  </button>
                  {showMoreDetails && (
                    <div className="p-5 space-y-3 border-t-2 border-slate-200 text-[#14171A]">
                      <p>
                        🛡️ <strong>Mức độ tin cậy ({farmerSummary.confidence_label_vi}):</strong>{' '}
                        {farmerSummary.confidence_explanation_vi}
                      </p>
                      {forecastData?.weather_context && (
                        <p>
                          ⛅ <strong>Thời tiết &amp; Mùa vụ:</strong>{' '}
                          {formatPlainWeatherSentence(forecastData.weather_context)}
                        </p>
                      )}
                      {sourceMeta && (
                        <p>
                          🏛️ <strong>Nguồn dữ liệu &amp; Ngày cập nhật:</strong>{' '}
                          {sourceMeta.price_source || sourceMeta.source_name || 'Tổng hợp thị trường'}{' '}
                          — Cập nhật mới nhất ngày{' '}
                          {forecastData.latest_actual_date
                            ? formatDateVN(forecastData.latest_actual_date)
                            : sourceMeta.last_updated || ''}
                          .
                        </p>
                      )}
                      <p className="text-[#334155] italic pt-1 border-t border-slate-200">
                        ⚠️ <strong>Lưu ý:</strong> {farmerSummary.disclaimer_vi}
                      </p>
                    </div>
                  )}
                </div>

                {/* (8) Hai nút điều hướng cuối màn: "Quay lại" và "Chọn nông sản khác" */}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-2">
                  <button
                    type="button"
                    onClick={() => setCurrentStep(2)}
                    className="touch-target-btn min-h-[52px] px-5 py-3 rounded-[12px] font-extrabold text-xl bg-slate-100 hover:bg-slate-200 text-[#14171A] border-2 border-slate-400"
                  >
                    ⬅ Quay lại (Đổi tỉnh / số ngày)
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      onResetHome();
                      setCurrentStep(1);
                    }}
                    className="touch-target-btn min-h-[52px] px-5 py-3 rounded-[12px] font-extrabold text-xl bg-[#14532D] hover:bg-[#0F3F22] text-white border-2 border-[#0F3F22]"
                  >
                    🌾 Chọn nông sản khác
                  </button>
                </div>
              </div>
            )}
          </section>

          {/* KHU VỰC ĐĂNG KÝ NHẬN TIN & CẢNH BÁO (Nằm dưới phần kết quả ở Bước 3/3) */}
          <section
            aria-labelledby="farmer-alert-heading"
            className="bg-white p-5 sm:p-6 rounded-[12px] border-2 border-slate-300 shadow-sm space-y-6"
          >
            <h2
              id="farmer-alert-heading"
              className="text-[24px] sm:text-[26px] font-extrabold text-[#14171A]"
            >
              🔔 Nhận tin báo giá tự động
            </h2>

            <form
              onSubmit={handleQuickSubscribe}
              noValidate
              className="space-y-4 bg-[#ECFDF5] p-5 rounded-[12px] border-2 border-[#15803D]"
            >
              {/* Chọn kênh trước để đổi nhãn & placeholder phù hợp */}
              <div className="space-y-2">
                <span className="block font-extrabold text-lg text-[#14171A]">
                  1. Chọn cách nhận tin:
                </span>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <button
                    type="button"
                    onClick={() => {
                      setSubChannel('EMAIL');
                      setSubErrorMsg('');
                    }}
                    aria-pressed={subChannel === 'EMAIL'}
                    className={`touch-target-btn min-h-[52px] px-4 py-2.5 rounded-[12px] font-extrabold text-lg transition ${
                      subChannel === 'EMAIL'
                        ? 'bg-[#14532D] text-white border-[3px] border-[#0F3F22]'
                        : 'bg-white text-[#14171A] border-2 border-slate-400'
                    }`}
                  >
                    {subChannel === 'EMAIL' ? '✓ ' : ''}📧 Nhận qua Email
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setSubChannel('SMS_ZALO');
                      setSubErrorMsg('');
                    }}
                    aria-pressed={subChannel === 'SMS_ZALO'}
                    className={`touch-target-btn min-h-[52px] px-4 py-2.5 rounded-[12px] font-extrabold text-lg transition ${
                      subChannel === 'SMS_ZALO'
                        ? 'bg-[#14532D] text-white border-[3px] border-[#0F3F22]'
                        : 'bg-white text-[#14171A] border-2 border-slate-400'
                    }`}
                  >
                    {subChannel === 'SMS_ZALO' ? '✓ ' : ''}📱 Nhận qua Tin nhắn / Zalo
                  </button>
                </div>
              </div>

              <div>
                <label
                  htmlFor="farmer-contact-input"
                  className="block font-extrabold text-[#14171A] text-xl mb-1"
                >
                  2. {subChannel === 'EMAIL' ? 'Nhập địa chỉ Email của bà con:' : 'Nhập Số điện thoại của bà con:'}
                </label>
                <span id="farmer-contact-hint" className="form-hint font-semibold text-[#334155]">
                  {subChannel === 'EMAIL'
                    ? `Ví dụ: nongdan.daklak@gmail.com (Nhận tin giá ${currentCommObj.name} tại ${currentProvDisplay.primaryName})`
                    : `Ví dụ: 0912345678 (Nhận tin giá ${currentCommObj.name} tại ${currentProvDisplay.primaryName})`}
                </span>
                <input
                  id="farmer-contact-input"
                  type={subChannel === 'EMAIL' ? 'email' : 'tel'}
                  required
                  minLength={5}
                  value={contactInput}
                  onChange={(e) => {
                    setContactInput(e.target.value);
                    setSubErrorMsg('');
                    syncAriaInvalid(e);
                  }}
                  onBlur={syncAriaInvalid}
                  aria-describedby="farmer-contact-hint"
                  aria-errormessage="farmer-contact-error"
                  placeholder={
                    subChannel === 'EMAIL'
                      ? 'Nhập địa chỉ Email (vd: nongdan@gmail.com)...'
                      : 'Nhập Số điện thoại (vd: 0912345678)...'
                  }
                  className="deferred-validate w-full min-h-[54px] px-4 py-3 text-xl font-semibold rounded-[12px] border-2 border-slate-400 bg-white text-[#14171A]"
                />
                {subErrorMsg && (
                  <div
                    id="farmer-contact-error"
                    role="alert"
                    className="mt-2 p-3 rounded-[12px] bg-[#FEE2E2] border-2 border-[#B91C1C] text-[#991B1B] font-extrabold"
                  >
                    ⚠️ {subErrorMsg}
                  </div>
                )}
              </div>

              <button
                type="submit"
                disabled={subSubmitting}
                className="touch-target-btn min-h-[54px] w-full px-6 py-3 rounded-[12px] font-extrabold text-xl bg-[#14532D] hover:bg-[#0F3F22] text-white shadow-md"
              >
                {subSubmitting ? 'Đang gửi đăng ký...' : '🔔 Đăng ký nhận tin báo giá'}
              </button>

              {subStatusMsg && (
                <div
                  role="status"
                  className="p-4 rounded-[12px] bg-white border-2 border-[#15803D] font-extrabold text-[#14532D]"
                >
                  {subStatusMsg}
                </div>
              )}
            </form>

            {/* Khu vực cảnh báo: Chỉ hiện tối đa 3 cảnh báo gần nhất của đúng nông sản + tỉnh đang chọn,
                dùng ngưỡng 3% (STRONG_ALERT_THRESHOLD_PCT) cho nhãn tăng/giảm mạnh vs nhẹ, hỗ trợ ▲/▼/■ */}
            <div className="space-y-3">
              <h3 className="text-[22px] font-extrabold text-[#14171A]">
                📢 Cảnh báo biến động giá ({currentCommObj.name} · {currentProvDisplay.primaryName}):
              </h3>

              {filteredAlerts.length === 0 ? (
                <div className="p-4 rounded-[12px] bg-slate-50 border-2 border-slate-300 text-[#334155] font-bold">
                  Hiện không có cảnh báo biến động nào cho {currentCommObj.name} tại{' '}
                  {currentProvDisplay.primaryName}.
                </div>
              ) : (
                filteredAlerts.map((ev) => {
                  const sev = getAlertSeverityInfo(ev.change_pct);
                  const cleanMessage = formatConciseAlertMessage(ev.message);
                  return (
                    <div
                      key={ev.id}
                      className={`p-4 rounded-[12px] border-2 space-y-1.5 ${sev.cardClass}`}
                    >
                      <div className="flex flex-wrap items-center justify-between gap-2 font-extrabold text-lg">
                        <span className={sev.titleClass}>
                          {sev.title} (Ngày {formatDateVN(ev.target_date)})
                        </span>
                        <span className={`px-3 py-0.5 rounded-[12px] border ${sev.badgeClass}`}>
                          {ev.change_pct > 0 ? '+' : ''}
                          {String(ev.change_pct).replace('.', ',')}%
                        </span>
                      </div>
                      <p className="text-[#14171A] font-semibold leading-relaxed">{cleanMessage}</p>
                    </div>
                  );
                })
              )}
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
