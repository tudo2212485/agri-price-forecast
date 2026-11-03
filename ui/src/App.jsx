import React, { useState, useEffect, useRef, useCallback } from 'react';
import { apiClient } from './api.js';
import FarmerModeView from './components/FarmerModeView.jsx';
import ExpertModeView from './components/ExpertModeView.jsx';
import { formatVnd } from './components/SvgCharts.jsx';
import { formatDateVN } from './utils.js';

const FONT_SCALE_STORAGE_KEY = 'agri_font_scale';

/**
 * Ứng dụng Dashboard Hai Chế Độ (SRS v1.1 - FR-47..FR-55, Mục 5.1, 5.4, NFR-11..NFR-13):
 * - Chế độ Mặc định: "🌾 Chế độ Bà con Nông dân (Đơn giản)" (font >= 18px, nút >= 48x48px, đọc giọng nói vi-VN).
 * - Chế độ Chuyên sâu: "🔬 Chế độ Chuyên sâu (GVHD / Hội đồng)" (4 Tab phân tích kỹ thuật, 7 mô hình, Backtesting).
 * - Thanh công cụ Hỗ trợ Tiếp cận luôn hiển thị: Phóng to cỡ chữ (18px / 22px / 26px) lưu localStorage & Hộp thoại Trợ giúp.
 */
export default function App() {
  // Mặc định mở ở Chế độ Bà con Nông dân (FR-47)
  const [viewMode, setViewMode] = useState('farmer');

  // Cỡ chữ hỗ trợ tiếp cận lưu trong localStorage: 'normal' (18px), 'large' (22px), 'xlarge' (26px)
  const [fontScale, setFontScale] = useState(() => {
    try {
      const saved = window.localStorage.getItem(FONT_SCALE_STORAGE_KEY);
      if (saved === 'normal' || saved === 'large' || saved === 'xlarge') {
        return saved;
      }
    } catch {
      // Bỏ qua nếu trình duyệt chặn localStorage
    }
    return 'normal';
  });

  // Bộ lọc hiện tại (mặc định chọn sẵn Cà phê nhân xô tại Đắk Lắk, 7 ngày tới)
  const [selectedCommodity, setSelectedCommodity] = useState('CAFE_ROBUSTA');
  const [selectedProvince, setSelectedProvince] = useState('DL');
  const [horizon, setHorizon] = useState(7);
  const [historyStack, setHistoryStack] = useState([]);

  // Dữ liệu từ FastAPI Backend
  const [commodities, setCommodities] = useState([]);
  const [provinces, setProvinces] = useState([]);
  const [overviewData, setOverviewData] = useState(null);
  const [pricesData, setPricesData] = useState(null);
  const [forecastData, setForecastData] = useState(null);
  const [metricsData, setMetricsData] = useState(null);
  const [alertsData, setAlertsData] = useState(null);
  const [pipelineStatus, setPipelineStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [apiError, setApiError] = useState('');

  // Tham chiếu tới hộp thoại <dialog closedby="any"> hướng dẫn trực quan (FR-54)
  const helpDialogRef = useRef(null);

  // Fallback light-dismiss cho trình duyệt chưa hỗ trợ thuộc tính closedby trên <dialog>
  useEffect(() => {
    const dialog = helpDialogRef.current;
    if (!dialog) return;

    const handleBackdropClick = (event) => {
      if ('closedBy' in HTMLDialogElement.prototype) return;
      if (event.target !== dialog) return;
      const rect = dialog.getBoundingClientRect();
      const isDialogContent =
        rect.top <= event.clientY &&
        event.clientY <= rect.top + rect.height &&
        rect.left <= event.clientX &&
        event.clientX <= rect.left + rect.width;
      if (isDialogContent) return;
      dialog.close();
    };

    dialog.addEventListener('click', handleBackdropClick);
    return () => dialog.removeEventListener('click', handleBackdropClick);
  }, []);

  const openHelpModal = () => {
    if (helpDialogRef.current && typeof helpDialogRef.current.showModal === 'function') {
      helpDialogRef.current.showModal();
    }
  };

  const closeHelpModal = () => {
    if (helpDialogRef.current && typeof helpDialogRef.current.close === 'function') {
      helpDialogRef.current.close();
    }
  };

  // Tải danh mục Nông sản, Tỉnh, Tổng quan, Cảnh báo và Trạng thái Pipeline khi khởi động
  const fetchGlobalData = useCallback(async () => {
    try {
      const [commRes, overRes, alertsRes, pipeRes] = await Promise.all([
        apiClient.getCommodities(),
        apiClient.getOverview(),
        apiClient.getAlerts(),
        apiClient.getPipelineStatus(),
      ]);
      setCommodities(commRes.commodities || []);
      setProvinces(commRes.provinces || []);
      setOverviewData(overRes);
      setAlertsData(alertsRes);
      setPipelineStatus(pipeRes);
      setApiError('');
    } catch (err) {
      setApiError(`Không thể kết nối tới Backend API: ${err.message}`);
    }
  }, []);

  // Tải dữ liệu chuỗi giá, dự báo và bảng xếp hạng mô hình khi đổi (commodity, province, horizon)
  const fetchSeriesData = useCallback(async (commCode, provCode, hDays) => {
    setLoading(true);
    try {
      const [fcRes, prRes, metRes] = await Promise.all([
        apiClient.getForecast(commCode, provCode, hDays),
        apiClient.getPrices(commCode, provCode),
        apiClient.getModelMetrics(commCode, provCode),
      ]);
      setForecastData(fcRes);
      setPricesData(prRes);
      setMetricsData(metRes);
      setApiError('');
    } catch (err) {
      setApiError(`Lỗi tải dữ liệu dự báo: ${err.message}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchGlobalData();
  }, [fetchGlobalData]);

  useEffect(() => {
    fetchSeriesData(selectedCommodity, selectedProvince, horizon);
  }, [selectedCommodity, selectedProvince, horizon, fetchSeriesData]);

  const pushHistoryState = () => {
    setHistoryStack((prev) => [
      ...prev.slice(-10),
      { commodity: selectedCommodity, province: selectedProvince, horizon },
    ]);
  };

  const handleSelectCommodity = (newCommCode) => {
    if (newCommCode === selectedCommodity) return;
    pushHistoryState();
    setSelectedCommodity(newCommCode);
    const commObj = commodities.find((c) => c.code === newCommCode);
    if (commObj && commObj.supported_provinces && commObj.supported_provinces.length > 0) {
      const stillSupported = commObj.supported_provinces.some((p) => p.code === selectedProvince);
      if (!stillSupported) {
        setSelectedProvince(commObj.supported_provinces[0].code);
      }
    }
  };

  const handleSelectProvince = (newProvCode) => {
    if (newProvCode === selectedProvince) return;
    pushHistoryState();
    setSelectedProvince(newProvCode);
  };

  const handleSelectHorizon = (newHorizon) => {
    if (Number(newHorizon) === Number(horizon)) return;
    pushHistoryState();
    setHorizon(Number(newHorizon));
  };

  const handleResetHome = () => {
    pushHistoryState();
    setSelectedCommodity('CAFE_ROBUSTA');
    setSelectedProvince('DL');
    setHorizon(7);
  };

  const handleGoBack = () => {
    if (historyStack.length === 0) return;
    const last = historyStack[historyStack.length - 1];
    setHistoryStack((prev) => prev.slice(0, -1));
    setSelectedCommodity(last.commodity);
    setSelectedProvince(last.province);
    setHorizon(last.horizon);
  };

  const cycleFontScale = () => {
    const nextScale =
      fontScale === 'normal' ? 'large' : fontScale === 'large' ? 'xlarge' : 'normal';
    setFontScale(nextScale);
    try {
      window.localStorage.setItem(FONT_SCALE_STORAGE_KEY, nextScale);
    } catch {
      // Bỏ qua nếu trình duyệt chặn localStorage
    }
  };

  const fontScaleLabel =
    fontScale === 'normal'
      ? 'Thường (18px)'
      : fontScale === 'large'
      ? 'Lớn (22px)'
      : 'Rất lớn (26px)';

  const fontScaleClass =
    fontScale === 'normal'
      ? 'font-scale-normal'
      : fontScale === 'large'
      ? 'font-scale-large'
      : 'font-scale-xlarge';

  return (
    <div className={`min-h-screen flex flex-col bg-[#FAF6EE] text-[#14171A] ${fontScaleClass}`}>
      {/* HEADER CHÍNH GỌN GÀNG, TƯƠNG PHẢN CAO WCAG AA (FR-47, FR-54, Mục 5.4) */}
      <header className="sticky top-0 z-30 bg-[#14532D] text-white border-b-4 border-[#C2410C] shadow-md">
        <div className="max-w-7xl mx-auto px-3 sm:px-4 lg:px-6 py-2.5 flex flex-col lg:flex-row lg:items-center lg:justify-between gap-2.5">
          {/* Bên trái: Biểu tượng bông lúa + Tiêu đề rõ ràng */}
          <div className="flex items-center gap-2 min-w-0 lg:shrink-0">
            <span aria-hidden="true" className="text-2xl sm:text-3xl shrink-0">
              🌾
            </span>
            <h1 className="text-[19px] sm:text-[21px] font-extrabold tracking-tight leading-tight truncate lg:overflow-visible">
              Dự Báo Giá Nông Sản Việt Nam
            </h1>
          </div>

          {/* Ở giữa: Cụm 2 nút chuyển đổi chế độ (khoảng cách >= 12px, nút đang chọn có viền 3px + ✓ + đổi nền) */}
          <div
            role="group"
            aria-label="Chuyển đổi chế độ hiển thị"
            className="grid grid-cols-2 lg:flex items-center bg-[#0F3F22] p-1.5 rounded-[12px] border border-emerald-700 gap-2.5 lg:gap-3 w-full lg:w-auto lg:shrink-0"
          >
            <button
              type="button"
              onClick={() => setViewMode('farmer')}
              aria-pressed={viewMode === 'farmer'}
              className={`touch-target-btn min-h-[48px] px-2.5 lg:px-3.5 py-2 rounded-[12px] font-extrabold text-[15px] lg:text-base leading-tight text-center lg:whitespace-nowrap transition ${
                viewMode === 'farmer'
                  ? 'bg-[#FBBF24] text-[#14171A] border-[3px] border-white shadow-sm'
                  : 'bg-transparent text-emerald-50 border-2 border-transparent hover:bg-emerald-800/80'
              }`}
            >
              {viewMode === 'farmer' ? '✓ ' : ''}🌾 Bà con Nông dân
            </button>
            <button
              type="button"
              onClick={() => setViewMode('expert')}
              aria-pressed={viewMode === 'expert'}
              className={`touch-target-btn min-h-[48px] px-2.5 lg:px-3.5 py-2 rounded-[12px] font-extrabold text-[15px] lg:text-base leading-tight text-center lg:whitespace-nowrap transition ${
                viewMode === 'expert'
                  ? 'bg-white text-[#14171A] border-[3px] border-[#FBBF24] shadow-sm'
                  : 'bg-transparent text-emerald-50 border-2 border-transparent hover:bg-emerald-800/80'
              }`}
            >
              {viewMode === 'expert' ? '✓ ' : ''}🔬 Chuyên sâu (Hội đồng)
            </button>
          </div>

          {/* Bên phải: Nút Cỡ chữ (3 mức lưu localStorage) & Nút Trợ giúp cách nhau >= 12px */}
          <div className="grid grid-cols-2 lg:flex items-center gap-2.5 lg:gap-3 w-full lg:w-auto lg:shrink-0">
            <button
              type="button"
              onClick={cycleFontScale}
              className="touch-target-btn min-h-[48px] px-2.5 lg:px-3.5 py-2 rounded-[12px] font-extrabold bg-[#0F3F22] hover:bg-emerald-800 border-2 border-emerald-300 text-white text-[15px] lg:text-base leading-tight text-center lg:whitespace-nowrap"
              title="Bấm để đổi cỡ chữ: Thường (18px), Lớn (22px), Rất lớn (26px)"
            >
              🔍 Cỡ chữ: {fontScaleLabel}
            </button>

            <button
              type="button"
              onClick={openHelpModal}
              className="touch-target-btn min-h-[48px] px-3 lg:px-3.5 py-2 rounded-[12px] font-extrabold bg-[#C2410C] hover:bg-[#9A3412] text-white border-2 border-amber-200 text-[15px] lg:text-base leading-tight text-center lg:whitespace-nowrap"
            >
              ❓ Trợ giúp
            </button>
          </div>
        </div>
      </header>

      {/* HỘP THOẠI TRỢ GIÚP TRỰC QUAN (<dialog closedby="any"> - FR-54) */}
      <dialog
        ref={helpDialogRef}
        closedby="any"
        aria-labelledby="helpDialogTitle"
        className="w-full max-w-2xl rounded-[16px] p-0 border-4 border-[#14532D] shadow-2xl bg-white text-[#14171A]"
      >
        <div className="p-6 md:p-8 space-y-5">
          <div className="flex items-center justify-between border-b-2 border-slate-200 pb-4 gap-3">
            <h2 id="helpDialogTitle" className="text-[26px] font-extrabold text-[#14532D]">
              ❓ Hướng dẫn sử dụng nhanh cho Bà con
            </h2>
            <button
              type="button"
              onClick={closeHelpModal}
              className="touch-target-btn min-h-[48px] min-w-[48px] px-4 py-2 rounded-[12px] font-extrabold bg-slate-200 text-[#14171A] hover:bg-slate-300"
            >
              ✖ Đóng
            </button>
          </div>

          <div className="space-y-4 text-[#14171A]">
            <div className="p-4 rounded-[12px] bg-[#ECFDF5] border-2 border-[#15803D]">
              <p className="font-extrabold text-xl text-[#14532D] mb-1">
                Bước 1/3: Chọn loại nông sản
              </p>
              <p>
                Bấm vào thẻ lớn có hình <strong>Cà phê nhân xô Robusta</strong>,{' '}
                <strong>Hồ tiêu đen</strong> hoặc <strong>Lúa tươi IR50404</strong>, rồi bấm nút{' '}
                <strong>&ldquo;Tiếp tục&rdquo;</strong>.
              </p>
            </div>

            <div className="p-4 rounded-[12px] bg-amber-50 border-2 border-amber-500">
              <p className="font-extrabold text-xl text-amber-950 mb-1">
                Bước 2/3: Chọn Tỉnh và Số ngày muốn xem
              </p>
              <p>
                Bấm chọn Tỉnh của bà con (ví dụ: Đắk Lắk, Gia Lai, An Giang), chọn xem{' '}
                <strong>7 ngày tới</strong>, <strong>14 ngày tới</strong> hoặc{' '}
                <strong>30 ngày tới</strong>, rồi bấm <strong>&ldquo;Xem giá&rdquo;</strong>.
              </p>
            </div>

            <div className="p-4 rounded-[12px] bg-sky-50 border-2 border-sky-500">
              <p className="font-extrabold text-xl text-sky-950 mb-1">
                Bước 3/3: Xem kết quả hoặc Bấm &ldquo;Đọc to&rdquo;
              </p>
              <p>
                Đọc câu kết luận in đậm ở đầu trang hoặc bấm nút màu cam{' '}
                <strong>&ldquo;🔊 Đọc to&rdquo;</strong> để điện thoại tự đọc bằng tiếng Việt.
              </p>
            </div>
          </div>

          <div className="flex justify-end pt-2">
            <button
              type="button"
              onClick={closeHelpModal}
              className="touch-target-btn min-h-[52px] px-8 py-3 rounded-[12px] font-extrabold text-xl bg-[#14532D] text-white hover:bg-[#0F3F22]"
            >
              👍 Đã hiểu, quay lại trang chính
            </button>
          </div>
        </div>
      </dialog>

      {/* NỘI DUNG CHÍNH: Chế độ Nông dân dùng 1 cột dọc max-w-[720px] căn giữa; Chế độ Chuyên sâu dùng max-w-7xl */}
      <main
        className={`flex-1 w-full mx-auto px-4 py-6 space-y-6 ${
          viewMode === 'farmer' ? 'max-w-[720px]' : 'max-w-7xl'
        }`}
      >
        {apiError && (
          <div
            role="alert"
            className="p-4 rounded-[12px] bg-rose-50 border-2 border-rose-600 text-rose-950 font-bold"
          >
            ⚠️ {apiError}
          </div>
        )}

        {/* Dải thẻ KPI Tổng quan nhanh chỉ hiển thị riêng ở Chế độ Chuyên sâu (ở Chế độ Nông dân đã gộp thẳng vào thẻ chọn nông sản ở Màn hình 1) */}
        {viewMode === 'expert' && overviewData?.featured_commodity_kpis && (
          <section aria-label="Điểm tin giá nông sản hôm nay" className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {overviewData.featured_commodity_kpis.map((item) => {
              const isCurrent =
                item.commodity_code === selectedCommodity && item.province_code === selectedProvince;
              return (
                <button
                  key={`${item.commodity_code}_${item.province_code}`}
                  type="button"
                  onClick={() => {
                    pushHistoryState();
                    setSelectedCommodity(item.commodity_code);
                    setSelectedProvince(item.province_code);
                  }}
                  className={`touch-target-btn min-h-[96px] p-4 rounded-[12px] text-left border-2 transition ${
                    isCurrent
                      ? 'bg-[#14532D] text-white border-[#0F3F22] shadow-md'
                      : 'bg-white text-[#14171A] border-slate-300 hover:border-[#14532D]'
                  }`}
                >
                  <div className="flex items-center justify-between font-bold text-sm opacity-90 gap-2">
                    <span className="truncate">
                      {item.commodity_name} ({item.province_name})
                    </span>
                    <span className="whitespace-nowrap font-medium text-xs bg-slate-100 text-slate-800 px-2 py-0.5 rounded border border-slate-300">
                      Cập nhật: {formatDateVN(item.latest_date)}
                    </span>
                  </div>
                  <div className="text-2xl font-extrabold mt-1">
                    Hôm nay: {formatVnd(item.current_price)} đ/kg
                  </div>
                  <div
                    className={`text-sm font-bold mt-1 ${
                      isCurrent ? 'text-amber-300' : 'text-[#14532D]'
                    }`}
                  >
                    Dự kiến 7 ngày tới: {formatVnd(item.forecast_7d_price)} đ/kg (
                    {item.forecast_7d_change_pct > 0 ? '▲ +' : item.forecast_7d_change_pct < 0 ? '▼ ' : '■ '}
                    {String(item.forecast_7d_change_pct).replace('.', ',')}%)
                  </div>
                </button>
              );
            })}
          </section>
        )}

        {/* HIỂN THỊ THEO CHẾ ĐỘ ĐANG CHỌN (FR-47) */}
        {viewMode === 'farmer' ? (
          <FarmerModeView
            commodities={commodities}
            provinces={provinces}
            overviewData={overviewData}
            selectedCommodity={selectedCommodity}
            selectedProvince={selectedProvince}
            horizon={horizon}
            onSelectCommodity={handleSelectCommodity}
            onSelectProvince={handleSelectProvince}
            onSelectHorizon={handleSelectHorizon}
            onResetHome={handleResetHome}
            onGoBack={handleGoBack}
            canGoBack={historyStack.length > 0}
            forecastData={forecastData}
            alertsData={alertsData}
            loading={loading}
            onRefreshAlerts={fetchGlobalData}
          />
        ) : (
          <ExpertModeView
            commodities={commodities}
            provinces={provinces}
            selectedCommodity={selectedCommodity}
            selectedProvince={selectedProvince}
            horizon={horizon}
            onSelectCommodity={handleSelectCommodity}
            onSelectProvince={handleSelectProvince}
            onSelectHorizon={handleSelectHorizon}
            pricesData={pricesData}
            forecastData={forecastData}
            metricsData={metricsData}
            alertsData={alertsData}
            pipelineStatus={pipelineStatus}
            loading={loading}
            onRefreshAll={() => {
              fetchGlobalData();
              fetchSeriesData(selectedCommodity, selectedProvince, horizon);
            }}
          />
        )}
      </main>

      {/* FOOTER */}
      <footer className="bg-slate-900 text-slate-200 border-t border-slate-800 py-5 px-4 mt-10">
        <div className="max-w-7xl mx-auto flex flex-wrap justify-between items-center gap-4 text-sm">
          <div>
            <strong>Đồ án Tốt nghiệp (SRS v1.1):</strong> Ứng dụng phân tích dữ liệu và dự báo biến
            động giá nông sản theo chuỗi thời gian sử dụng Học máy
          </div>
          <div>
            Hỗ trợ 2 chế độ: Nông dân lớn tuổi (WCAG AA, ≥18px, Giọng nói tiếng Việt) &amp; Chuyên
            gia (7 Mô hình, Backtesting, TimescaleDB)
          </div>
        </div>
      </footer>
    </div>
  );
}
