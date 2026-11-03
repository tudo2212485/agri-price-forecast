/**
 * API Client kết nối tới FastAPI Backend (Mục 5.2, NFR-01, NFR-05).
 * Hỗ trợ cấu hình qua VITE_API_BASE_URL hoặc tự động fallback sang http://localhost:8000/api.
 */

const ENV_API_BASE = import.meta.env?.VITE_API_BASE_URL || '';

async function requestJson(endpoint, options = {}) {
  const candidateBases = ENV_API_BASE
    ? [ENV_API_BASE.replace(/\/$/, '')]
    : ['/api', 'http://localhost:8000/api'];

  let lastError = null;
  for (const base of candidateBases) {
    const url = `${base}${endpoint}`;
    try {
      const response = await fetch(url, {
        headers: {
          'Content-Type': 'application/json',
          ...(options.headers || {}),
        },
        ...options,
      });
      if (!response.ok) {
        let errDetail = `HTTP ${response.status}`;
        try {
          const errJson = await response.json();
          errDetail = errJson.detail || errJson.message_vi || errDetail;
        } catch {
          // ignore json parse error
        }
        throw new Error(errDetail);
      }
      return await response.json();
    } catch (err) {
      lastError = err;
    }
  }
  throw lastError || new Error('Không thể kết nối tới máy chủ API.');
}

export function getCsvExportUrl(commodityCode, provinceCode, includeForecast = true) {
  const base = ENV_API_BASE ? ENV_API_BASE.replace(/\/$/, '') : 'http://localhost:8000/api';
  const params = new URLSearchParams({
    commodity: commodityCode,
    province: provinceCode,
    include_forecast: String(includeForecast),
  });
  return `${base}/export/csv?${params.toString()}`;
}

export const apiClient = {
  getCommodities: () => requestJson('/commodities'),
  getOverview: () => requestJson('/overview'),
  getPrices: (commodity, province, startDate = '', endDate = '') => {
    const params = new URLSearchParams({ commodity, province });
    if (startDate) params.set('start_date', startDate);
    if (endDate) params.set('end_date', endDate);
    return requestJson(`/prices?${params.toString()}`);
  },
  getForecast: (commodity, province, horizon = 7) => {
    const params = new URLSearchParams({
      commodity,
      province,
      horizon: String(horizon),
    });
    return requestJson(`/forecast?${params.toString()}`);
  },
  getModelMetrics: (commodity, province) => {
    const params = new URLSearchParams({ commodity, province });
    return requestJson(`/models/metrics?${params.toString()}`);
  },
  getAlerts: (commodity = '', province = '') => {
    const params = new URLSearchParams();
    if (commodity) params.set('commodity', commodity);
    if (province) params.set('province', province);
    const qs = params.toString();
    return requestJson(`/alerts${qs ? `?${qs}` : ''}`);
  },
  createAlertRule: (payload) =>
    requestJson('/alerts/rules', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  createSubscription: (payload) =>
    requestJson('/subscriptions', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  deleteSubscription: (subId) =>
    requestJson(`/subscriptions/${subId}`, {
      method: 'DELETE',
    }),
  getPipelineStatus: () => requestJson('/pipeline/status'),
  triggerPipelineRun: (payload = { mode: 'fast_update' }) =>
    requestJson('/pipeline/run', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
};

