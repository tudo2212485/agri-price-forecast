/**
 * Tiện ích định dạng ngày tháng, tiền tệ, tên tỉnh, nhãn cảnh báo và ngôn ngữ đời thường cho Nông dân lớn tuổi.
 */

/**
 * Ngưỡng biến động (%) để phân biệt cảnh báo "tăng mạnh / giảm mạnh" (>= 3%)
 * và "tăng nhẹ / giảm nhẹ" (< 3%).
 */
export const STRONG_ALERT_THRESHOLD_PCT = 3.0;

export function formatDateVN(dateStr) {
  if (!dateStr) return '';
  const parts = String(dateStr).split('-');
  if (parts.length !== 3) return String(dateStr);
  const [year, month, day] = parts;
  return `${day}/${month}/${year}`;
}

export function formatShortDateVi(dateStr) {
  if (!dateStr) return '';
  const parts = String(dateStr).split('-');
  if (parts.length !== 3) return String(dateStr);
  return `${parts[2]}/${parts[1]}`;
}

/**
 * Làm tròn giá về bội số 1.000 đồng gần nhất (dùng cho trục dọc biểu đồ nông dân).
 */
export function roundToNearestThousand(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return 0;
  return Math.round(Number(value) / 1000) * 1000;
}

/**
 * Tính 3–4 mốc giá trên trục dọc (Y-axis) đều nhau và làm tròn chẵn đến hàng nghìn đồng (1.000 đ).
 * Ví dụ: [113000, 116000, 119000], tuyệt đối không để số lẻ như 118.971.
 */
export function computeThousandRoundedTicks(minPrice, maxPrice) {
  if (!Number.isFinite(minPrice) || !Number.isFinite(maxPrice)) {
    return [0, 1000, 2000];
  }
  const pad = Math.max((maxPrice - minPrice) * 0.15, 400);
  const lowTick = Math.max(0, Math.floor((minPrice - pad) / 1000) * 1000);
  const targetHigh = Math.ceil((maxPrice + pad) / 1000) * 1000;
  const rawSpan = Math.max(2000, targetHigh - lowTick);

  // Bước nhảy làm tròn lên bội số 1.000 đồng (chia làm 2 khoảng -> 3 mốc giá chẵn nghìn)
  const step = Math.max(1000, Math.ceil(rawSpan / 2000) * 1000);
  return [lowTick, lowTick + step, lowTick + step * 2];
}

/**
 * Chỗ cấu hình hiển thị tên tỉnh hiện hành / tên cũ (nếu cần cập nhật hành chính ở tầng giao diện).
 * Lưu ý: Không tự điền ánh xạ sáp nhập khi chưa có cấu hình chính thức; không sửa dữ liệu CSDL.
 * Ví dụ cấu trúc khi cần bật:
 *   DL: { currentName: 'Đắk Lắk', formerName: '' }
 */
export const PROVINCE_NAME_CONFIG = {};

export function getProvinceDisplayInfo(provinceObj) {
  if (!provinceObj) return { primaryName: '', subNote: '' };
  const code = provinceObj.code || '';
  const cfg = PROVINCE_NAME_CONFIG[code];
  if (cfg && cfg.currentName) {
    return {
      primaryName: cfg.currentName,
      subNote: cfg.formerName ? `(trước đây: ${cfg.formerName})` : '',
    };
  }
  return {
    primaryName: provinceObj.name || code,
    subNote: '',
  };
}

/**
 * Đồng bộ câu lời khuyên theo đúng số ngày dự báo đang chọn (7, 14 hoặc 30 ngày),
 * tránh nói "trong tuần này" khi người dùng đang xem dự báo 14 hoặc 30 ngày.
 */
export function formatActionHintForHorizon(actionHintVi, horizonDays) {
  if (!actionHintVi) return '';
  const days = Number(horizonDays) || 7;
  return String(actionHintVi)
    .replace(/trong tuần này/gi, `trong ${days} ngày tới`)
    .replace(/tuần này/gi, `${days} ngày tới`);
}

/**
 * Phân loại nhãn và màu sắc cảnh báo theo ngưỡng STRONG_ALERT_THRESHOLD_PCT (3%):
 * - >= 3%: ▲ Dự báo tăng mạnh / ▼ Dự báo giảm mạnh
 * - 0.5% .. < 3%: ▲ Dự báo tăng nhẹ / ▼ Dự báo giảm nhẹ
 * - < 0.5%: ■ Dự báo ổn định
 */
export function getAlertSeverityInfo(changePct) {
  const pct = Number(changePct || 0);
  const absPct = Math.abs(pct);

  if (absPct < 0.5) {
    return {
      symbol: '■',
      title: '■ Dự báo ổn định',
      cardClass: 'bg-[#F9FAFB] border-[#4B5563] text-[#14171A]',
      titleClass: 'text-[#1F2937]',
      badgeClass: 'bg-[#F3F4F6] text-[#1F2937] border-[#4B5563]',
    };
  }

  if (pct > 0) {
    const isStrong = absPct >= STRONG_ALERT_THRESHOLD_PCT;
    return {
      symbol: '▲',
      title: isStrong ? '▲ Dự báo tăng mạnh' : '▲ Dự báo tăng nhẹ',
      cardClass: 'bg-[#F0FDF4] border-[#15803D] text-[#14171A]',
      titleClass: 'text-[#14532D]',
      badgeClass: 'bg-[#DCFCE7] text-[#14532D] border-[#15803D]',
    };
  }

  const isStrong = absPct >= STRONG_ALERT_THRESHOLD_PCT;
  return {
    symbol: '▼',
    title: isStrong ? '▼ Dự báo giảm mạnh' : '▼ Dự báo giảm nhẹ',
    cardClass: 'bg-[#FEF2F2] border-[#B91C1C] text-[#14171A]',
    titleClass: 'text-[#991B1B]',
    badgeClass: 'bg-[#FEE2E2] text-[#991B1B] border-[#B91C1C]',
  };
}

/**
 * Rút gọn văn bản cảnh báo còn 1–2 câu thông tin cốt lõi:
 * - Bỏ tiền tố "[CẢNH BÁO GIÁ NÔNG SẢN]"
 * - Bỏ câu lời khuyên lặp lại ở cuối mỗi mục ("Bà con nông dân...")
 */
export function formatConciseAlertMessage(rawMessage) {
  if (!rawMessage) return '';
  let text = String(rawMessage)
    .replace(/^\[CẢNH BÁO GIÁ NÔNG SẢN\]\s*/i, '')
    .trim();

  // Cắt bỏ câu lời khuyên chung lặp lại ở cuối mỗi cảnh báo
  text = text.replace(/\s*Bà con nông dân[^.]*\.\s*$/i, '').trim();
  return text;
}

/**
 * Chuyển thông tin thời tiết & mùa vụ từ API sang 1 câu chữ đời thường dễ hiểu,
 * lược bỏ các con số kỹ thuật phức tạp (như "23,2 mm", "28,4 °C").
 */
export function formatPlainWeatherSentence(weatherContext) {
  if (!weatherContext) return '';
  const season = weatherContext.season_stage || '';
  const rawSummary = weatherContext.weather_summary_vi || '';
  const anomaly = (weatherContext.anomaly_note || '').toLowerCase();

  let weatherCondition = 'thời tiết tại vùng trồng tương đối ổn định';
  if (anomaly.includes('mưa lớn') || anomaly.includes('ngập') || rawSummary.toLowerCase().includes('mưa nhiều')) {
    weatherCondition = 'vùng trồng đang có mưa nhiều, cần chú ý khâu phơi sấy và bảo quản nông sản';
  } else if (anomaly.includes('khô hạn') || anomaly.includes('nắng nóng') || rawSummary.toLowerCase().includes('khô')) {
    weatherCondition = 'thời tiết vùng trồng đang nắng khô, thuận lợi cho việc phơi sấy và vận chuyển';
  } else if (rawSummary.toLowerCase().includes('mưa')) {
    weatherCondition = 'vùng trồng có mưa rải rác, bà con lưu ý giữ khô ráo khi thu hoạch và phơi sấy';
  }

  if (season) {
    return `Hiện đang trong giai đoạn ${season.toLowerCase()}, ${weatherCondition}.`;
  }
  return `Hiện tại ${weatherCondition}.`;
}
