import React, { useState } from 'react';
import {
  ExpertConfidenceChart,
  ModelMetricsBarChart,
  BacktestComparisonChart,
  formatVnd,
} from './SvgCharts.jsx';
import { apiClient, getCsvExportUrl } from '../api.js';

/**
 * CHẾ ĐỘ CHUYÊN SÂU - DÀNH CHO GVHD, HỘI ĐỒNG & QUẢN TRỊ (Mục 2.2, 5.1, FR-20..FR-29, FR-44).
 * Bao gồm đầy đủ 4 Tab chuyên môn:
 * 1. Phân tích Dự báo & Khoảng tin cậy 95% + Xuất CSV (FR-20, FR-21, FR-23)
 * 2. So sánh 7 Mô hình & Kiểm chứng ngược Backtesting 30 ngày (FR-15, FR-16, FR-22, FR-44, FR-46)
 * 3. Quản lý Quy tắc Cảnh báo, Lịch sử Alert Event & Người đăng ký (FR-24..FR-27)
 * 4. Giám sát Pipeline Log & Báo cáo Độ phủ Dữ liệu data_coverage_view (FR-05, FR-28, FR-42)
 */
export default function ExpertModeView({
  commodities = [],
  provinces = [],
  selectedCommodity,
  selectedProvince,
  horizon,
  onSelectCommodity,
  onSelectProvince,
  onSelectHorizon,
  pricesData,
  forecastData,
  metricsData,
  alertsData,
  pipelineStatus,
  loading,
  onRefreshAll,
}) {
  const [activeTab, setActiveTab] = useState('forecast');
  const [historyRange, setHistoryRange] = useState('90'); // '30', '90', '365', 'all' (FR-20)

  // Form tạo quy tắc cảnh báo mới (Tab 3)
  const [ruleThreshold, setRuleThreshold] = useState('1.5');
  const [ruleWindow, setRuleWindow] = useState('14');
  const [ruleChannel, setRuleChannel] = useState('EMAIL');
  const [ruleMsg, setRuleMsg] = useState('');
  const [creatingRule, setCreatingRule] = useState(false);

  // Trạng thái chạy cập nhật Pipeline thủ công (Tab 4)
  const [runningPipeline, setRunningPipeline] = useState(false);
  const [pipelineRunMsg, setPipelineRunMsg] = useState('');

  const handleCreateRule = async (e) => {
    e.preventDefault();
    setCreatingRule(true);
    setRuleMsg('');
    try {
      const res = await apiClient.createAlertRule({
        commodity_code: selectedCommodity,
        province_code: selectedProvince,
        threshold_pct: parseFloat(ruleThreshold) || 2.0,
        window_days: parseInt(ruleWindow, 10) || 7,
        channel: ruleChannel,
      });
      setRuleMsg(
        `✅ Đã tạo quy tắc #${res.rule.id} (±${res.rule.threshold_pct}% / ${res.rule.window_days} ngày).`
      );
      if (onRefreshAll) onRefreshAll();
    } catch (err) {
      setRuleMsg(`⚠️ Lỗi tạo quy tắc: ${err.message}`);
    } finally {
      setCreatingRule(false);
    }
  };

  const handleUnsubscribe = async (subId) => {
    try {
      await apiClient.deleteSubscription(subId);
      if (onRefreshAll) onRefreshAll();
    } catch {
      // ignore
    }
  };

  const handleTriggerPipeline = async () => {
    setRunningPipeline(true);
    setPipelineRunMsg('');
    try {
      const res = await apiClient.triggerPipelineRun({
        mode: 'fast_update',
        commodity_code: selectedCommodity,
        province_code: selectedProvince,
      });
      setPipelineRunMsg(
        `✅ Đã thực thi tác vụ '${res.task_name}' thành công (${res.records_processed} bản ghi được kiểm tra).`
      );
      if (onRefreshAll) onRefreshAll();
    } catch (err) {
      setPipelineRunMsg(`⚠️ Lỗi chạy pipeline: ${err.message}`);
    } finally {
      setRunningPipeline(false);
    }
  };

  const stats = pricesData?.statistics;
  const selectedModel = forecastData?.selected_model_info || metricsData?.selected_model;
  const leaderboard = metricsData?.models_leaderboard || [];
  const backtestSeries = metricsData?.backtest_series || [];
  const backtestSummary = metricsData?.backtest_summary;

  const fullHistory =
    pricesData?.series && pricesData.series.length > 0
      ? pricesData.series
      : forecastData?.recent_history_series || [];

  const filteredHistorySeries = React.useMemo(() => {
    if (!fullHistory || fullHistory.length === 0) return [];
    if (historyRange === '30') return fullHistory.slice(-30);
    if (historyRange === '90') return fullHistory.slice(-90);
    if (historyRange === '365') return fullHistory.slice(-365);
    return fullHistory;
  }, [fullHistory, historyRange]);

  return (
    <div className="space-y-6">
      {/* BỘ LỌC KỸ THUẬT CHUNG */}
      <section className="bg-white p-5 rounded-2xl border border-slate-300 shadow-sm">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4 items-end">
          <div>
            <label htmlFor="expert-commodity-select" className="block font-bold text-slate-800 mb-1">
              Mặt hàng Nông sản:
            </label>
            <select
              id="expert-commodity-select"
              value={selectedCommodity}
              onChange={(e) => onSelectCommodity(e.target.value)}
              className="touch-target-btn w-full min-h-[52px] px-3 py-2 rounded-xl border-2 border-slate-300 font-semibold text-slate-900 bg-slate-50"
            >
              {commodities.map((c) => (
                <option key={c.code} value={c.code}>
                  {c.name} ({c.code})
                </option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor="expert-province-select" className="block font-bold text-slate-800 mb-1">
              Tỉnh / Vùng thu mua:
            </label>
            <select
              id="expert-province-select"
              value={selectedProvince}
              onChange={(e) => onSelectProvince(e.target.value)}
              className="touch-target-btn w-full min-h-[52px] px-3 py-2 rounded-xl border-2 border-slate-300 font-semibold text-slate-900 bg-slate-50"
            >
              {provinces.map((p) => (
                <option key={p.code} value={p.code}>
                  {p.name} ({p.code} - {p.region})
                </option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor="expert-horizon-select" className="block font-bold text-slate-800 mb-1">
              Tầm xa Dự báo (Horizon h):
            </label>
            <select
              id="expert-horizon-select"
              value={horizon}
              onChange={(e) => onSelectHorizon(Number(e.target.value))}
              className="touch-target-btn w-full min-h-[52px] px-3 py-2 rounded-xl border-2 border-slate-300 font-semibold text-slate-900 bg-slate-50"
            >
              <option value={7}>h = 7 ngày</option>
              <option value={14}>h = 14 ngày</option>
              <option value={21}>h = 21 ngày</option>
              <option value={30}>h = 30 ngày</option>
            </select>
          </div>

          <div>
            <a
              href={getCsvExportUrl(selectedCommodity, selectedProvince, true)}
              target="_blank"
              rel="noreferrer"
              className="touch-target-btn min-h-[52px] w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl font-bold bg-emerald-800 text-white hover:bg-emerald-900 shadow-sm text-center"
            >
              📥 Xuất dữ liệu ra CSV (Excel)
            </a>
          </div>
        </div>
      </section>

      {/* THANH CHUYỂN 4 TAB CHUYÊN SÂU */}
      <div
        role="tablist"
        aria-label="Các phân hệ phân tích chuyên sâu"
        className="flex flex-wrap gap-2 bg-white p-2 rounded-2xl border border-slate-300 shadow-sm"
      >
        {[
          { id: 'forecast', label: '📈 1. Phân tích Dự báo & Khoảng tin cậy 95%' },
          { id: 'models', label: '🏆 2. So sánh 7 Mô hình & Backtesting 30 ngày' },
          { id: 'alerts', label: '🔔 3. Quản lý Cảnh báo & Người đăng ký' },
          { id: 'pipeline', label: '⚙️ 4. Vận hành Pipeline & Độ phủ Dữ liệu' },
        ].map((tab) => {
          const active = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => setActiveTab(tab.id)}
              className={`touch-target-btn min-h-[52px] px-4 py-2.5 rounded-xl font-bold transition ${
                active
                  ? 'bg-slate-900 text-white shadow'
                  : 'bg-slate-100 text-slate-800 hover:bg-slate-200'
              }`}
            >
              {tab.label}
            </button>
          );
        })}
      </div>

      {/* TAB 1: PHÂN TÍCH DỰ BÁO & KHOẢNG TIN CẬY 95% (FR-20, FR-21, FR-23) */}
      {activeTab === 'forecast' && (
        <div className="space-y-6">
          {forecastData?.status === 'INSUFFICIENT_DATA' ? (
            <div className="bg-amber-50 border-2 border-amber-500 p-6 rounded-2xl text-slate-900 space-y-3">
              <h3 className="text-xl font-extrabold text-amber-950">
                ⚠️ Cặp Nông sản - Tỉnh chưa có dữ liệu ({forecastData.commodity_name} tại{' '}
                {forecastData.province_name})
              </h3>
              <p>{forecastData.message_vi}</p>
              <div className="flex flex-wrap gap-3">
                {(forecastData.supported_provinces || []).map((sp) => (
                  <button
                    key={sp.code}
                    type="button"
                    onClick={() => onSelectProvince(sp.code)}
                    className="touch-target-btn min-h-[52px] px-4 py-2 rounded-xl font-bold bg-emerald-800 text-white"
                  >
                    Chuyển sang {sp.name} ({sp.code})
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <>
              {/* Thẻ thống kê kỹ thuật */}
              <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
                <div className="bg-white p-4 rounded-xl border border-slate-300 shadow-sm">
                  <div className="text-sm font-semibold text-slate-600">Giá thực tế mới nhất</div>
                  <div className="text-2xl font-extrabold text-slate-900">
                    {formatVnd(forecastData?.latest_actual_price)} đ/kg
                  </div>
                  <div className="text-xs text-slate-600 mt-1">
                    Ngày: {forecastData?.latest_actual_date || '—'}
                  </div>
                </div>

                <div className="bg-white p-4 rounded-xl border border-slate-300 shadow-sm">
                  <div className="text-sm font-semibold text-slate-600">
                    Giá Trung bình / Độ lệch chuẩn
                  </div>
                  <div className="text-xl font-extrabold text-slate-900">
                    {formatVnd(stats?.mean_price)} ± {formatVnd(stats?.std_price)}
                  </div>
                  <div className="text-xs text-slate-600 mt-1">
                    Số bản ghi: {pricesData?.record_count || 0} ngày
                  </div>
                </div>

                <div className="bg-white p-4 rounded-xl border border-slate-300 shadow-sm">
                  <div className="text-sm font-semibold text-slate-600">Biên độ Min / Max lịch sử</div>
                  <div className="text-xl font-extrabold text-slate-900">
                    {formatVnd(stats?.min_price)} – {formatVnd(stats?.max_price)}
                  </div>
                  <div className="text-xs text-slate-600 mt-1">
                    Nội suy: {stats?.interpolated_count || 0} điểm (≤ 3 ngày)
                  </div>
                </div>

                <div className="bg-white p-4 rounded-xl border border-slate-300 shadow-sm">
                  <div className="text-sm font-semibold text-slate-600">
                    Dự báo h={horizon} ngày tới
                  </div>
                  <div className="text-2xl font-extrabold text-emerald-900">
                    {formatVnd(forecastData?.farmer_summary?.target_price)} đ/kg
                  </div>
                  <div className="text-xs font-bold text-emerald-800 mt-1">
                    Biến động: {forecastData?.farmer_summary?.change_pct > 0 ? '+' : ''}
                    {forecastData?.farmer_summary?.change_pct}%
                  </div>
                </div>

                <div className="bg-emerald-50 p-4 rounded-xl border border-emerald-400 shadow-sm">
                  <div className="text-sm font-bold text-emerald-950">
                    🏆 Mô hình Champion đang chọn
                  </div>
                  <div className="text-2xl font-extrabold text-emerald-950">
                    {selectedModel?.model_type || '—'}
                  </div>
                  <div className="text-xs font-semibold text-emerald-900 mt-1">
                    MAPE: {selectedModel?.mape}% | MAE: {formatVnd(selectedModel?.mae)} đ
                  </div>
                </div>
              </div>

              {/* Biểu đồ Khoảng tin cậy 95% */}
              <div className="bg-white p-6 rounded-2xl border border-slate-300 shadow-sm space-y-4">
                <div className="flex flex-wrap justify-between items-center gap-2">
                  <h3 className="text-xl font-extrabold text-slate-900">
                    Biểu đồ Chuỗi thời gian & Khoảng tin cậy 95% [lower_bound, upper_bound] (FR-20)
                  </h3>
                  <span className="text-sm font-semibold text-slate-700">
                    Mô hình: <strong>{selectedModel?.model_type}</strong> (Train:{' '}
                    {selectedModel?.train_start_date} → {selectedModel?.train_end_date}, N=
                    {selectedModel?.train_record_count})
                  </span>
                </div>

                {/* Cụm nút lọc nhanh khoảng thời gian lịch sử (FR-20) */}
                <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-bold text-slate-800">Khoảng lịch sử hiển thị:</span>
                    <div className="inline-flex rounded-xl border border-slate-300 p-1 bg-slate-50 gap-1">
                      {[
                        { id: '30', label: '30 ngày' },
                        { id: '90', label: '90 ngày' },
                        { id: '365', label: '1 năm' },
                        { id: 'all', label: 'Tất cả' },
                      ].map((btn) => (
                        <button
                          key={btn.id}
                          type="button"
                          onClick={() => setHistoryRange(btn.id)}
                          className={`touch-target-btn min-h-[40px] px-3.5 py-1.5 rounded-lg text-xs md:text-sm font-extrabold transition ${
                            historyRange === btn.id
                              ? 'bg-slate-900 text-white shadow'
                              : 'text-slate-700 hover:bg-slate-200'
                          }`}
                        >
                          {btn.label}
                        </button>
                      ))}
                    </div>
                  </div>
                  <span className="text-xs text-slate-600 font-medium">
                    Đang hiển thị {filteredHistorySeries.length} điểm quan sát lịch sử
                  </span>
                </div>

                <ExpertConfidenceChart
                  historySeries={filteredHistorySeries}
                  forecastSeries={forecastData?.forecast_series || []}
                  unit={forecastData?.unit || 'VNĐ/kg'}
                />

                {forecastData?.source_metadata && (
                  <div className="text-sm text-slate-700 bg-slate-50 p-3 rounded-xl border border-slate-200 flex flex-wrap justify-between gap-2">
                    <span>
                      <strong>Nguồn thu thập (FR-39):</strong> {forecastData.source_metadata.source_name} —{' '}
                      {forecastData.source_metadata.publisher} ({forecastData.source_metadata.price_type})
                    </span>
                    <span>
                      <strong>URL gốc:</strong> {forecastData.source_metadata.source_url}
                    </span>
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      )}

      {/* TAB 2: SO SÁNH 7 MÔ HÌNH & KIỂM CHỨNG NGƯỢC BACKTESTING 30 NGÀY (FR-15, FR-16, FR-22, FR-44) */}
      {activeTab === 'models' && (
        <div className="space-y-6">
          <div className="bg-white p-6 rounded-2xl border border-slate-300 shadow-sm space-y-4">
            <div className="flex flex-wrap justify-between items-center gap-2">
              <h3
                id="model-leaderboard-caption"
                className="text-xl font-extrabold text-slate-900"
              >
                🏆 Bảng Xếp hạng Thực nghiệm 7 Mô hình Dự báo (FR-15, FR-16, FR-22, FR-46)
              </h3>
              <span className="text-sm font-semibold text-emerald-900 bg-emerald-50 border border-emerald-300 px-3 py-1 rounded-lg">
                Tiêu chí nghiệm thu #3: Mô hình được chọn có MAPE & RMSE thấp hơn toàn bộ nhóm Baseline
              </span>
            </div>

            <div
              tabIndex={0}
              role="region"
              aria-labelledby="model-leaderboard-caption"
              className="table-wrapper rounded-xl border border-slate-300"
            >
              <table className="responsive-stack text-left text-sm">
                <thead className="bg-slate-900 text-white">
                  <tr>
                    <th className="p-3 font-bold">Hạng</th>
                    <th className="p-3 font-bold">Mô hình (model_type)</th>
                    <th className="p-3 font-bold">Phân nhóm</th>
                    <th className="p-3 font-bold">MAPE (%)</th>
                    <th className="p-3 font-bold">MAE (VNĐ/kg)</th>
                    <th className="p-3 font-bold">RMSE (VNĐ/kg)</th>
                    <th className="p-3 font-bold">Miền ngày Train</th>
                    <th className="p-3 font-bold">Số bản ghi Train</th>
                    <th className="p-3 font-bold">Trạng thái</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200 bg-white">
                  {leaderboard.map((row) => (
                    <tr
                      key={row.model_type}
                      className={row.is_selected ? 'bg-emerald-50/90 font-semibold' : 'hover:bg-slate-50'}
                    >
                      <td className="p-3 font-bold">#{row.rank}</td>
                      <th scope="row" className="p-3 font-extrabold text-slate-900">
                        {row.is_selected ? '🏆 ' : ''}
                        {row.model_type}
                      </th>
                      <td className="p-3">
                        <span
                          className={`px-2.5 py-0.5 rounded-md text-xs font-bold ${
                            row.is_baseline
                              ? 'bg-slate-200 text-slate-800'
                              : 'bg-sky-100 text-sky-900'
                          }`}
                        >
                          {row.is_baseline ? 'Baseline' : 'ML / Deep Learning'}
                        </span>
                      </td>
                      <td className="p-3 font-bold text-emerald-950">{Number(row.mape).toFixed(4)}%</td>
                      <td className="p-3">{formatVnd(row.mae)} đ</td>
                      <td className="p-3">{formatVnd(row.rmse)} đ</td>
                      <td className="p-3 text-xs">
                        {row.train_start_date} → {row.train_end_date}
                      </td>
                      <td className="p-3 font-semibold">{row.train_record_count}</td>
                      <td className="p-3">
                        {row.is_selected ? (
                          <span className="px-3 py-1 rounded-lg bg-emerald-800 text-white text-xs font-extrabold">
                            🏆 Đang chọn (is_selected=True)
                          </span>
                        ) : (
                          <span className="text-slate-600 text-xs">Đã lưu log</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <ModelMetricsBarChart leaderboard={leaderboard} />
          </div>

          {/* Kiểm chứng ngược Backtesting 30 ngày quá khứ (FR-44) */}
          <div className="bg-white p-6 rounded-2xl border border-slate-300 shadow-sm space-y-4">
            <div className="flex flex-wrap justify-between items-center gap-3">
              <h3 id="backtest-table-caption" className="text-xl font-extrabold text-slate-900">
                🔍 Kiểm chứng ngược (Historical Backtesting 30 ngày qua - FR-44, FR-45)
              </h3>
              {backtestSummary && (
                <div className="flex flex-wrap gap-3 text-sm font-bold">
                  <span className="bg-slate-100 px-3 py-1 rounded-lg border border-slate-300">
                    Kỳ đối chiếu: {backtestSummary.origin_date} → {backtestSummary.end_date} (
                    {backtestSummary.backtest_days} ngày)
                  </span>
                  <span className="bg-emerald-50 text-emerald-950 px-3 py-1 rounded-lg border border-emerald-300">
                    Backtest MAPE: {Number(backtestSummary.mape || 0).toFixed(4)}% | MAE:{' '}
                    {formatVnd(backtestSummary.mae)} đ/kg
                  </span>
                </div>
              )}
            </div>

            <BacktestComparisonChart backtestSeries={backtestSeries} />

            <div
              tabIndex={0}
              role="region"
              aria-labelledby="backtest-table-caption"
              className="table-wrapper rounded-xl border border-slate-300 max-h-72"
            >
              <table className="text-left text-sm">
                <thead className="bg-slate-800 text-white">
                  <tr>
                    <th className="p-2.5">Ngày đích (target_date)</th>
                    <th className="p-2.5">Horizon (h)</th>
                    <th className="p-2.5">Giá thực tế (actual_price)</th>
                    <th className="p-2.5">Giá dự báo (yhat)</th>
                    <th className="p-2.5">Khoảng tin cậy 95%</th>
                    <th className="p-2.5">Chênh lệch (VNĐ/kg)</th>
                    <th className="p-2.5">Sai số tuyệt đối (%)</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200 bg-white">
                  {backtestSeries.slice(0, 15).map((b) => (
                    <tr key={b.target_date} className="hover:bg-slate-50">
                      <th scope="row" className="p-2.5 font-semibold text-slate-900">
                        {b.target_date}
                      </th>
                      <td className="p-2.5">h={b.horizon}</td>
                      <td className="p-2.5 font-bold text-slate-900">{formatVnd(b.actual_price)} đ</td>
                      <td className="p-2.5 font-bold text-emerald-900">
                        {formatVnd(b.predicted_price)} đ
                      </td>
                      <td className="p-2.5 text-xs text-slate-600">
                        [{formatVnd(b.lower_bound)} – {formatVnd(b.upper_bound)}]
                      </td>
                      <td className="p-2.5">
                        {b.error_amount > 0 ? '+' : ''}
                        {formatVnd(b.error_amount)} đ
                      </td>
                      <td className="p-2.5 font-semibold">{Number(b.abs_pct_error).toFixed(3)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* TAB 3: QUẢN LÝ CẢNH BÁO & NGƯỜI ĐĂNG KÝ (FR-24..FR-27) */}
      {activeTab === 'alerts' && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Form thêm quy tắc cảnh báo */}
            <form
              onSubmit={handleCreateRule}
              className="bg-white p-5 rounded-2xl border border-slate-300 shadow-sm space-y-4"
            >
              <h3 className="text-lg font-extrabold text-slate-900">
                ➕ Tạo Quy tắc Cảnh báo Mới (FR-24)
              </h3>
              <p className="text-sm text-slate-600">
                Áp dụng cho <strong>{selectedCommodity}</strong> tại tỉnh{' '}
                <strong>{selectedProvince}</strong>
              </p>

              <div>
                <label htmlFor="rule-threshold-input" className="block text-sm font-bold text-slate-800 mb-1">
                  Ngưỡng biến động kích hoạt (%):
                </label>
                <input
                  id="rule-threshold-input"
                  type="number"
                  step="0.1"
                  min="0.1"
                  max="100"
                  value={ruleThreshold}
                  onChange={(e) => setRuleThreshold(e.target.value)}
                  className="w-full min-h-[48px] px-3 py-2 rounded-xl border border-slate-300 font-semibold"
                />
              </div>

              <div>
                <label htmlFor="rule-window-input" className="block text-sm font-bold text-slate-800 mb-1">
                  Cửa sổ ngày dự báo (window_days):
                </label>
                <input
                  id="rule-window-input"
                  type="number"
                  min="1"
                  max="30"
                  value={ruleWindow}
                  onChange={(e) => setRuleWindow(e.target.value)}
                  className="w-full min-h-[48px] px-3 py-2 rounded-xl border border-slate-300 font-semibold"
                />
              </div>

              <div>
                <label htmlFor="rule-channel-select" className="block text-sm font-bold text-slate-800 mb-1">
                  Kênh cảnh báo:
                </label>
                <select
                  id="rule-channel-select"
                  value={ruleChannel}
                  onChange={(e) => setRuleChannel(e.target.value)}
                  className="w-full min-h-[48px] px-3 py-2 rounded-xl border border-slate-300 font-semibold"
                >
                  <option value="EMAIL">EMAIL</option>
                  <option value="NOTIFICATION">NOTIFICATION</option>
                </select>
              </div>

              <button
                type="submit"
                disabled={creatingRule}
                className="touch-target-btn min-h-[52px] w-full px-4 py-2.5 rounded-xl font-bold bg-emerald-800 text-white hover:bg-emerald-900"
              >
                {creatingRule ? 'Đang lưu & quét cảnh báo...' : 'Lưu Quy tắc & Đánh giá ngay'}
              </button>

              {ruleMsg && (
                <div className="p-3 rounded-xl bg-emerald-50 border border-emerald-300 text-sm font-bold text-slate-900">
                  {ruleMsg}
                </div>
              )}
            </form>

            {/* Danh sách Quy tắc đang hoạt động */}
            <div className="lg:col-span-2 bg-white p-5 rounded-2xl border border-slate-300 shadow-sm space-y-3">
              <h3 id="alert-rules-caption" className="text-lg font-extrabold text-slate-900">
                📋 Danh sách Quy tắc Cảnh báo ({alertsData?.rules_count || 0} quy tắc)
              </h3>
              <div
                tabIndex={0}
                role="region"
                aria-labelledby="alert-rules-caption"
                className="table-wrapper rounded-xl border border-slate-200 max-h-80"
              >
                <table className="text-left text-sm">
                  <thead className="bg-slate-800 text-white">
                    <tr>
                      <th className="p-2.5">Rule ID</th>
                      <th className="p-2.5">Nông sản</th>
                      <th className="p-2.5">Tỉnh/Vùng</th>
                      <th className="p-2.5">Ngưỡng (%)</th>
                      <th className="p-2.5">Cửa sổ</th>
                      <th className="p-2.5">Kênh</th>
                      <th className="p-2.5">Trạng thái</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-200">
                    {(alertsData?.rules || []).map((r) => (
                      <tr key={r.id}>
                        <th scope="row" className="p-2.5 font-bold">
                          #{r.id}
                        </th>
                        <td className="p-2.5 font-semibold">{r.commodity_name}</td>
                        <td className="p-2.5">{r.province_name}</td>
                        <td className="p-2.5 font-bold text-amber-900">±{r.threshold_pct}%</td>
                        <td className="p-2.5">{r.window_days} ngày</td>
                        <td className="p-2.5">{r.channel}</td>
                        <td className="p-2.5">
                          <span className="px-2 py-0.5 rounded bg-emerald-100 text-emerald-900 text-xs font-bold">
                            {r.is_active ? 'ACTIVE' : 'INACTIVE'}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          {/* Lịch sử Sự kiện Cảnh báo đã kích hoạt (alert_event) */}
          <div className="bg-white p-5 rounded-2xl border border-slate-300 shadow-sm space-y-3">
            <h3 id="alert-events-caption" className="text-lg font-extrabold text-slate-900">
              🚨 Lịch sử Sự kiện Cảnh báo Đã kích hoạt (`alert_event` - Chống gửi trùng FR-26)
            </h3>
            <div
              tabIndex={0}
              role="region"
              aria-labelledby="alert-events-caption"
              className="table-wrapper rounded-xl border border-slate-200"
            >
              <table className="text-left text-sm">
                <thead className="bg-slate-900 text-white">
                  <tr>
                    <th className="p-3">ID</th>
                    <th className="p-3">Rule</th>
                    <th className="p-3">Nông sản & Tỉnh</th>
                    <th className="p-3">Ngày đích</th>
                    <th className="p-3">Biến động (%)</th>
                    <th className="p-3">Trạng thái gửi</th>
                    <th className="p-3">Nội dung tiếng Việt (FR-52)</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200">
                  {(alertsData?.events || []).map((ev) => (
                    <tr key={ev.id} className="hover:bg-slate-50">
                      <th scope="row" className="p-3 font-bold">
                        #{ev.id}
                      </th>
                      <td className="p-3">Rule #{ev.rule_id}</td>
                      <td className="p-3 font-semibold">
                        {ev.commodity_name} ({ev.province_name})
                      </td>
                      <td className="p-3 font-semibold">{ev.target_date}</td>
                      <td className="p-3 font-bold text-amber-900">
                        {ev.change_pct > 0 ? '+' : ''}
                        {ev.change_pct}%
                      </td>
                      <td className="p-3">
                        <span className="px-2.5 py-0.5 rounded bg-emerald-100 text-emerald-950 text-xs font-extrabold">
                          {ev.sent_status}
                        </span>
                      </td>
                      <td className="p-3 text-slate-800 max-w-xl">{ev.message}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Danh sách Người đăng ký nhận cảnh báo */}
          <div className="bg-white p-5 rounded-2xl border border-slate-300 shadow-sm space-y-3">
            <h3 className="text-lg font-extrabold text-slate-900">
              👥 Danh sách Người đăng ký Nhận thông báo (`subscriber` - FR-27, FR-53)
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              {(alertsData?.subscribers || []).map((sub) => (
                <div
                  key={sub.id}
                  className="p-3.5 rounded-xl bg-slate-50 border border-slate-300 flex items-center justify-between gap-2"
                >
                  <div className="text-sm">
                    <div className="font-bold text-slate-900">{sub.contact_info}</div>
                    <div className="text-xs text-slate-600">
                      Kênh: {sub.channel} | {sub.commodity_name} - {sub.province_name}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => handleUnsubscribe(sub.id)}
                    className="touch-target-btn min-h-[48px] px-3 py-1.5 rounded-lg text-xs font-bold bg-rose-100 text-rose-900 hover:bg-rose-200"
                  >
                    Hủy
                  </button>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* TAB 4: VẬN HÀNH PIPELINE & BÁO CÁO ĐỘ PHỦ DỮ LIỆU (FR-05, FR-28, FR-42) */}
      {activeTab === 'pipeline' && (
        <div className="space-y-6">
          <div className="bg-white p-5 rounded-2xl border border-slate-300 shadow-sm flex flex-wrap items-center justify-between gap-4">
            <div className="space-y-1">
              <div className="flex items-center gap-3">
                <span className="px-3 py-1 rounded-lg bg-emerald-800 text-white font-extrabold text-sm">
                  Trạng thái: {pipelineStatus?.system_status || 'HEALTHY'}
                </span>
                <span className="font-bold text-slate-900">
                  Ngày dữ liệu giá mới nhất: {pipelineStatus?.data_freshness_date || '—'}
                </span>
                <span className="text-slate-700 font-medium">
                  | Thời tiết mới nhất: {pipelineStatus?.weather_freshness_date || '—'}
                </span>
              </div>
              <p className="text-sm text-slate-600">
                Tổng bản ghi: Giá = <strong>{pipelineStatus?.record_counts?.price_observation || 0}</strong> | Thời
                tiết = <strong>{pipelineStatus?.record_counts?.weather_observation || 0}</strong> | Feature Set ={' '}
                <strong>{pipelineStatus?.record_counts?.feature_set || 0}</strong> | Model Runs ={' '}
                <strong>{pipelineStatus?.record_counts?.model_run || 0}</strong> | Forecasts ={' '}
                <strong>{pipelineStatus?.record_counts?.forecast || 0}</strong>
              </p>
            </div>

            <button
              type="button"
              onClick={handleTriggerPipeline}
              disabled={runningPipeline}
              className="touch-target-btn min-h-[52px] px-5 py-3 rounded-xl font-extrabold bg-amber-700 text-white hover:bg-amber-800 shadow"
            >
              {runningPipeline ? '⏳ Đang chạy cập nhật...' : '⚡ Chạy cập nhật Pipeline ngay'}
            </button>
          </div>

          {pipelineRunMsg && (
            <div className="p-4 rounded-xl bg-emerald-50 border border-emerald-400 font-bold text-slate-900">
              {pipelineRunMsg}
            </div>
          )}

          {/* Bảng Báo cáo Độ phủ Lịch sử data_coverage_view (FR-42) */}
          <div className="bg-white p-5 rounded-2xl border border-slate-300 shadow-sm space-y-3">
            <h3 id="coverage-table-caption" className="text-lg font-extrabold text-slate-900">
              📊 Báo cáo Độ phủ Dữ liệu Lịch sử (`data_coverage_view` - FR-42, Tiêu chí nghiệm thu #1)
            </h3>
            <div
              tabIndex={0}
              role="region"
              aria-labelledby="coverage-table-caption"
              className="table-wrapper rounded-xl border border-slate-300"
            >
              <table className="text-left text-sm">
                <thead className="bg-slate-900 text-white">
                  <tr>
                    <th className="p-3">Nông sản</th>
                    <th className="p-3">Tỉnh / Thành</th>
                    <th className="p-3">Từ ngày (min_date)</th>
                    <th className="p-3">Đến ngày (max_date)</th>
                    <th className="p-3">Số ngày có dữ liệu</th>
                    <th className="p-3">Tỷ lệ thiếu (missing_ratio)</th>
                    <th className="p-3">Khoảng trống lớn nhất (max_gap)</th>
                    <th className="p-3">Đủ ĐK Huấn luyện</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200">
                  {(pipelineStatus?.data_coverage || []).map((cov, idx) => (
                    <tr key={idx} className="hover:bg-slate-50">
                      <th scope="row" className="p-3 font-bold text-slate-900">
                        {cov.commodity_name} ({cov.commodity_code})
                      </th>
                      <td className="p-3 font-semibold">
                        {cov.province_name} ({cov.province_code})
                      </td>
                      <td className="p-3">{cov.min_date}</td>
                      <td className="p-3">{cov.max_date}</td>
                      <td className="p-3 font-bold">{cov.total_days_with_data} ngày</td>
                      <td className="p-3">{(Number(cov.missing_ratio) * 100).toFixed(2)}%</td>
                      <td className="p-3">{cov.max_gap_days} ngày</td>
                      <td className="p-3">
                        <span className="px-2.5 py-0.5 rounded bg-emerald-100 text-emerald-950 text-xs font-extrabold">
                          {cov.is_sufficient_for_training ? '✓ Đạt chuẩn (≥ 24 tháng)' : 'Chưa đủ'}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Bảng Nhật ký Thực thi pipeline_log (FR-05) */}
          <div className="bg-white p-5 rounded-2xl border border-slate-300 shadow-sm space-y-3">
            <h3 id="pipeline-log-caption" className="text-lg font-extrabold text-slate-900">
              📜 Nhật ký Thực thi Pipeline (`pipeline_log` - FR-05)
            </h3>
            <div
              tabIndex={0}
              role="region"
              aria-labelledby="pipeline-log-caption"
              className="table-wrapper rounded-xl border border-slate-300 max-h-80"
            >
              <table className="text-left text-sm">
                <thead className="bg-slate-800 text-white">
                  <tr>
                    <th className="p-2.5">Log ID</th>
                    <th className="p-2.5">Tác vụ (task_name)</th>
                    <th className="p-2.5">Nguồn</th>
                    <th className="p-2.5">Bắt đầu (started_at)</th>
                    <th className="p-2.5">Số bản ghi xử lý</th>
                    <th className="p-2.5">Trạng thái</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200">
                  {(pipelineStatus?.recent_pipeline_logs || []).map((lg) => (
                    <tr key={lg.id} className="hover:bg-slate-50">
                      <th scope="row" className="p-2.5 font-bold">
                        #{lg.id}
                      </th>
                      <td className="p-2.5 font-semibold text-slate-900">{lg.task_name}</td>
                      <td className="p-2.5">{lg.source_name}</td>
                      <td className="p-2.5 text-xs">{lg.started_at}</td>
                      <td className="p-2.5 font-bold">{lg.records_processed}</td>
                      <td className="p-2.5">
                        <span
                          className={`px-2.5 py-0.5 rounded text-xs font-extrabold ${
                            lg.status === 'SUCCESS'
                              ? 'bg-emerald-100 text-emerald-900'
                              : lg.status === 'FAILED'
                              ? 'bg-rose-100 text-rose-900'
                              : 'bg-amber-100 text-amber-900'
                          }`}
                        >
                          {lg.status}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

