import React, { useState, useRef, useEffect } from 'react';
import { formatDateVN, formatShortDateVi, computeThousandRoundedTicks } from '../utils.js';

export function formatVnd(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return '—';
  }
  return Math.round(Number(value)).toLocaleString('vi-VN');
}

export { formatShortDateVi };

/**
 * 1. Biểu đồ Tối giản 2 Đường cho Chế độ Nông dân (FR-50):
 * - Chỉ giữ: 1 đường nét liền cho giá đã qua, 1 đường nét đứt cho giá dự báo,
 *   1 chấm tròn đánh dấu "Giá mới nhất (dd/mm)".
 * - Đo chiều rộng thực tế (1 đơn vị SVG = 1px CSS) để nhãn trục và chú thích luôn >= 16px
 *   trên cả điện thoại 360x800 lẫn máy tính 1366x768.
 * - Trục dọc gồm 3 mốc giá làm tròn chẵn đến 1.000 đồng (vd 113.000 / 116.000 / 119.000).
 * - Trục ngang chỉ 3 mốc ngày dạng dd/mm.
 * - Chú thích bằng chữ đặt ngay dưới biểu đồ.
 */
export function SimpleDualLineChart({ historySeries = [], forecastSeries = [], unit = 'VNĐ/kg' }) {
  const [hovered, setHovered] = useState(null);
  const containerRef = useRef(null);
  const [svgWidth, setSvgWidth] = useState(() => {
    if (typeof window !== 'undefined') {
      return Math.max(280, Math.min(640, window.innerWidth - 64));
    }
    return 600;
  });

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return undefined;

    const updateWidth = () => {
      if (el.clientWidth > 0) {
        setSvgWidth(Math.max(220, Math.round(el.clientWidth)));
      }
    };
    updateWidth();

    if (typeof ResizeObserver !== 'undefined') {
      const ro = new ResizeObserver(updateWidth);
      ro.observe(el);
      return () => ro.disconnect();
    }
    window.addEventListener('resize', updateWidth);
    return () => window.removeEventListener('resize', updateWidth);
  }, []);

  const recentHistory = historySeries.slice(-21);
  if (recentHistory.length === 0 && forecastSeries.length === 0) {
    return (
      <div className="p-6 text-center text-[#334155] bg-slate-50 rounded-[12px] border border-slate-300">
        Chưa có dữ liệu biểu đồ để hiển thị.
      </div>
    );
  }

  const histPoints = recentHistory.map((d) => ({
    date: d.obs_date,
    price: Number(d.price),
    type: 'HISTORY',
  }));
  const fcPoints = forecastSeries.map((d) => ({
    date: d.target_date,
    price: Number(d.yhat),
    type: 'FORECAST',
  }));

  const allPrices = [...histPoints.map((p) => p.price), ...fcPoints.map((p) => p.price)];
  const minPrice = Math.min(...allPrices);
  const maxPrice = Math.max(...allPrices);

  // 3 mốc giá làm tròn chẵn đến 1.000 đồng (vd 113.000 / 116.000 / 119.000)
  const yTicks = computeThousandRoundedTicks(minPrice, maxPrice);
  const yMin = yTicks[0];
  const yMax = yTicks[yTicks.length - 1];

  const width = svgWidth;
  const height = 260;
  const padLeft = 74;
  const padRight = 12;
  const padTop = 42;
  const padBottom = 42;
  const plotW = Math.max(140, width - padLeft - padRight);
  const plotH = height - padTop - padBottom;

  const totalCount = histPoints.length + fcPoints.length;
  const getX = (index) => {
    if (totalCount <= 1) return padLeft + plotW / 2;
    return padLeft + (index / (totalCount - 1)) * plotW;
  };
  const getY = (val) => {
    if (yMax <= yMin) return padTop + plotH / 2;
    return padTop + plotH - ((val - yMin) / (yMax - yMin)) * plotH;
  };

  const histCoords = histPoints.map((p, idx) => ({
    ...p,
    x: getX(idx),
    y: getY(p.price),
  }));

  const fcCoords = fcPoints.map((p, idx) => ({
    ...p,
    x: getX(histPoints.length + idx),
    y: getY(p.price),
  }));

  const histPath = histCoords
    .map((pt, i) => `${i === 0 ? 'M' : 'L'} ${pt.x.toFixed(1)} ${pt.y.toFixed(1)}`)
    .join(' ');

  // Nối điểm cuối lịch sử sang điểm đầu dự báo để đường biểu đồ liền mạch
  const bridgeCoords =
    histCoords.length > 0 ? [histCoords[histCoords.length - 1], ...fcCoords] : fcCoords;
  const fcPath = bridgeCoords
    .map((pt, i) => `${i === 0 ? 'M' : 'L'} ${pt.x.toFixed(1)} ${pt.y.toFixed(1)}`)
    .join(' ');

  const lastHist = histCoords[histCoords.length - 1];
  const lastFc = fcCoords[fcCoords.length - 1];

  // Gom toàn bộ điểm để bắt sự kiện hover/chạm
  const allInteractivePoints = [
    ...histCoords.map((pt) => ({ ...pt, label: 'Giá đã qua' })),
    ...fcCoords.map((pt) => ({ ...pt, label: 'Giá dự báo' })),
  ];

  // Giữ nhãn "Giá mới nhất (dd/mm)" luôn nằm gọn trong khung SVG trên màn 360px
  const latestLabelX = lastHist
    ? Math.max(padLeft + 74, Math.min(width - padRight - 74, lastHist.x))
    : padLeft;

  return (
    <div ref={containerRef} className="w-full relative">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width={width}
        height={height}
        className="w-full h-auto bg-white rounded-[12px] border-2 border-slate-300 shadow-sm select-none block"
        role="img"
        aria-label="Biểu đồ đường biểu diễn giá nông sản những ngày qua và dự báo những ngày tới"
        onMouseLeave={() => setHovered(null)}
      >
        {/* Lưới ngang & 3 mốc giá làm tròn đến 1.000 đồng (cỡ chữ 16px thực tế) */}
        {yTicks.map((tickVal, idx) => {
          const y = getY(tickVal);
          return (
            <g key={idx}>
              <line
                x1={padLeft}
                y1={y}
                x2={width - padRight}
                y2={y}
                stroke="#CBD5E1"
                strokeDasharray="4 4"
                strokeWidth="1.5"
              />
              <text
                x={padLeft - 8}
                y={y + 6}
                textAnchor="end"
                fill="#14171A"
                fontWeight="700"
                fontSize="16"
              >
                {formatVnd(tickVal)}
              </text>
            </g>
          );
        })}

        {/* Vạch ngăn cách dọc tại "Giá mới nhất (dd/mm)" */}
        {lastHist && (
          <g>
            <line
              x1={lastHist.x}
              y1={padTop}
              x2={lastHist.x}
              y2={height - padBottom}
              stroke="#475569"
              strokeWidth="1.5"
              strokeDasharray="4 4"
            />
            <text
              x={latestLabelX}
              y={padTop - 12}
              textAnchor="middle"
              fill="#14171A"
              fontWeight="800"
              fontSize="16"
            >
              Giá mới nhất ({formatShortDateVi(lastHist.date)})
            </text>
          </g>
        )}

        {/* Đường 1: Giá đã qua (Nét liền >= 3px) */}
        {histPath && (
          <path
            d={histPath}
            fill="none"
            stroke="#14532D"
            strokeWidth="3.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        )}

        {/* Đường 2: Giá dự báo (Nét đứt >= 3px) */}
        {fcPath && (
          <path
            d={fcPath}
            fill="none"
            stroke="#C2410C"
            strokeWidth="3.5"
            strokeDasharray="9 6"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        )}

        {/* 1 chấm tròn đánh dấu "Giá mới nhất (dd/mm)" */}
        {lastHist && (
          <circle
            cx={lastHist.x}
            cy={lastHist.y}
            r="7"
            fill="#14532D"
            stroke="#FFFFFF"
            strokeWidth="3"
          />
        )}

        {/* 3 mốc ngày dạng dd/mm ở trục ngang (cỡ chữ 16px thực tế) */}
        {histCoords.length > 0 && (
          <text
            x={histCoords[0].x}
            y={height - 12}
            textAnchor="start"
            fill="#14171A"
            fontWeight="700"
            fontSize="16"
          >
            {formatShortDateVi(histCoords[0].date)}
          </text>
        )}
        {lastHist && (
          <text
            x={
              lastFc
                ? Math.max(padLeft + 46, Math.min(lastHist.x, lastFc.x - 54))
                : lastHist.x
            }
            y={height - 12}
            textAnchor="middle"
            fill="#14532D"
            fontWeight="800"
            fontSize="16"
          >
            {formatShortDateVi(lastHist.date)}
          </text>
        )}
        {lastFc && (
          <text
            x={lastFc.x}
            y={height - 12}
            textAnchor="end"
            fill="#C2410C"
            fontWeight="800"
            fontSize="16"
          >
            {formatShortDateVi(lastFc.date)}
          </text>
        )}

        {/* VÙNG HOVER VÀ TOOLTIP TƯƠNG TÁC */}
        {allInteractivePoints.map((pt, i) => (
          <circle
            key={i}
            cx={pt.x}
            cy={pt.y}
            r="14"
            fill="transparent"
            className="cursor-pointer"
            onMouseEnter={() => setHovered(pt)}
          />
        ))}

        {hovered && (
          <g className="pointer-events-none">
            <circle cx={hovered.x} cy={hovered.y} r="7" fill="#FFFFFF" stroke="#14171A" strokeWidth="3" />
            {(() => {
              const tipW = 195;
              const tipH = 62;
              const tipX = Math.max(
                padLeft + 4,
                Math.min(width - padRight - tipW, hovered.x - tipW / 2)
              );
              const tipY = hovered.y > padTop + tipH + 16 ? hovered.y - tipH - 12 : hovered.y + 16;
              return (
                <g>
                  <rect
                    x={tipX}
                    y={tipY}
                    width={tipW}
                    height={tipH}
                    rx="10"
                    fill="#14171A"
                    fillOpacity="0.95"
                  />
                  <text x={tipX + 12} y={tipY + 24} fill="#E2E8F0" fontSize="16" fontWeight="600">
                    {formatShortDateVi(hovered.date)} ({hovered.label})
                  </text>
                  <text x={tipX + 12} y={tipY + 48} fill="#FFFFFF" fontSize="16" fontWeight="800">
                    {formatVnd(hovered.price)} đồng/kg
                  </text>
                </g>
              );
            })()}
          </g>
        )}
      </svg>

      {/* CHÚ THÍCH BẰNG CHỮ ĐẶT NGAY DƯỚI BIỂU ĐỒ (cỡ chữ >= 16px) */}
      <div className="mt-3 pt-3 border-t border-slate-200 flex flex-col sm:flex-row sm:flex-wrap sm:items-center justify-between gap-2.5 text-[16px] sm:text-[18px] font-bold text-[#14171A]">
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
          <span className="inline-flex items-center gap-2">
            <span className="inline-block w-7 h-1 bg-[#14532D] rounded" />
            <span>Giá những ngày qua (Nét liền)</span>
          </span>
          <span className="inline-flex items-center gap-2">
            <span className="inline-block w-7 h-0 border-t-[3.5px] border-dashed border-[#C2410C]" />
            <span>Giá dự báo sắp tới (Nét đứt)</span>
          </span>
          {lastHist && (
            <span className="inline-flex items-center gap-2">
              <span className="inline-block w-3.5 h-3.5 rounded-full bg-[#14532D] border-2 border-white ring-1 ring-[#14532D]" />
              <span>Giá mới nhất ({formatShortDateVi(lastHist.date)})</span>
            </span>
          )}
        </div>
        <span className="text-[#334155] font-bold">
          Đơn vị: đồng/kg ({unit})
        </span>
      </div>
    </div>
  );
}

/**
 * 2. Biểu đồ Chuyên sâu kèm Khoảng tin cậy 95% [lower_bound, upper_bound] (FR-20):
 * - Hỗ trợ lọc theo khoảng thời gian lịch sử từ component cha.
 * - Hỗ trợ Tooltip hover hiển thị đầy đủ Ngày, Giá dự báo và Khoảng tin cậy 95%.
 */
export function ExpertConfidenceChart({ historySeries = [], forecastSeries = [], unit = 'VNĐ/kg' }) {
  const [hovered, setHovered] = useState(null);

  if (historySeries.length === 0 && forecastSeries.length === 0) {
    return (
      <div className="p-6 text-center text-slate-600 bg-slate-50 rounded-xl border border-slate-200">
        Không có dữ liệu chuỗi thời gian để hiển thị.
      </div>
    );
  }

  const allValues = [
    ...historySeries.map((d) => Number(d.price)),
    ...forecastSeries.flatMap((d) => [
      Number(d.yhat),
      Number(d.lower_bound ?? d.yhat),
      Number(d.upper_bound ?? d.yhat),
    ]),
  ];

  const minVal = Math.min(...allValues);
  const maxVal = Math.max(...allValues);
  const padVal = Math.max((maxVal - minVal) * 0.18, maxVal * 0.01, 60);
  const yMin = Math.max(0, minVal - padVal);
  const yMax = maxVal + padVal;

  const width = 920;
  const height = 370;
  const padLeft = 105;
  const padRight = 45;
  const padTop = 36;
  const padBottom = 54;
  const plotW = width - padLeft - padRight;
  const plotH = height - padTop - padBottom;

  const totalPoints = historySeries.length + forecastSeries.length;
  const getX = (idx) => {
    if (totalPoints <= 1) return padLeft + plotW / 2;
    return padLeft + (idx / (totalPoints - 1)) * plotW;
  };
  const getY = (v) => {
    if (yMax <= yMin) return padTop + plotH / 2;
    return padTop + plotH - ((v - yMin) / (yMax - yMin)) * plotH;
  };

  const histPts = historySeries.map((d, i) => ({
    date: d.obs_date,
    price: Number(d.price),
    isInterpolated: Boolean(d.is_interpolated),
    type: 'HISTORICAL',
    x: getX(i),
    y: getY(Number(d.price)),
  }));

  const fcPts = forecastSeries.map((d, i) => ({
    date: d.target_date,
    yhat: Number(d.yhat),
    lower: Number(d.lower_bound ?? d.yhat),
    upper: Number(d.upper_bound ?? d.yhat),
    type: 'FORECAST',
    x: getX(historySeries.length + i),
    y: getY(Number(d.yhat)),
    yLow: getY(Number(d.lower_bound ?? d.yhat)),
    yHigh: getY(Number(d.upper_bound ?? d.yhat)),
  }));

  const histPath = histPts
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`)
    .join(' ');

  const lastHist = histPts[histPts.length - 1];
  const fcWithStart = lastHist
    ? [
        {
          x: lastHist.x,
          y: lastHist.y,
          yLow: lastHist.y,
          yHigh: lastHist.y,
        },
        ...fcPts,
      ]
    : fcPts;

  const fcLinePath = fcWithStart
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`)
    .join(' ');

  // Dải băng khoảng tin cậy 95% [lower_bound, upper_bound]
  const ciAreaPath =
    fcWithStart.length > 1
      ? [
          ...fcWithStart.map(
            (p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.yHigh.toFixed(1)}`
          ),
          ...[...fcWithStart]
            .reverse()
            .map((p) => `L ${p.x.toFixed(1)} ${p.yLow.toFixed(1)}`),
          'Z',
        ].join(' ')
      : '';

  const yTicks = [yMin, yMin + (yMax - yMin) * 0.33, yMin + (yMax - yMin) * 0.67, yMax];
  const allHoverPoints = [...histPts, ...fcPts];

  return (
    <div className="w-full relative">
      <div className="flex flex-wrap items-center justify-between gap-4 mb-3 text-sm font-medium text-slate-700">
        <div className="flex flex-wrap items-center gap-5">
          <span className="inline-flex items-center gap-2">
            <span className="inline-block w-6 h-1 bg-slate-900 rounded" />
            <span>Giá lịch sử thực tế ({unit})</span>
          </span>
          <span className="inline-flex items-center gap-2">
            <span className="inline-block w-6 h-0 border-t-2 border-dashed border-emerald-700" />
            <span>Dự báo điểm (yhat)</span>
          </span>
          <span className="inline-flex items-center gap-2">
            <span className="inline-block w-5 h-3 bg-emerald-200/80 border border-emerald-500 rounded-sm" />
            <span>Khoảng tin cậy 95% [lower_bound, upper_bound]</span>
          </span>
        </div>
      </div>

      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full h-auto bg-white rounded-xl border border-slate-300 select-none"
        role="img"
        aria-label="Biểu đồ phân tích chuỗi thời gian chuyên sâu kèm khoảng tin cậy 95 phần trăm"
        onMouseLeave={() => setHovered(null)}
      >
        {yTicks.map((tv, i) => {
          const y = getY(tv);
          return (
            <g key={i}>
              <line
                x1={padLeft}
                y1={y}
                x2={width - padRight}
                y2={y}
                stroke="#e2e8f0"
                strokeWidth="1"
              />
              <text
                x={padLeft - 10}
                y={y + 4}
                textAnchor="end"
                className="fill-slate-700 font-semibold"
                fontSize="13"
              >
                {formatVnd(tv)}
              </text>
            </g>
          );
        })}

        {/* Dải băng Khoảng tin cậy 95% */}
        {ciAreaPath && <path d={ciAreaPath} fill="rgba(16, 185, 129, 0.22)" stroke="none" />}

        {/* Vạch chia mốc dự báo */}
        {lastHist && (
          <line
            x1={lastHist.x}
            y1={padTop}
            x2={lastHist.x}
            y2={height - padBottom}
            stroke="#64748b"
            strokeDasharray="4 4"
            strokeWidth="1.5"
          />
        )}

        {/* Đường lịch sử */}
        {histPath && (
          <path d={histPath} fill="none" stroke="#0f172a" strokeWidth="2.8" strokeLinejoin="round" />
        )}

        {/* Đường dự báo */}
        {fcLinePath && (
          <path
            d={fcLinePath}
            fill="none"
            stroke="#047857"
            strokeWidth="3"
            strokeDasharray="7 5"
            strokeLinejoin="round"
          />
        )}

        {/* Đánh dấu các điểm nội suy */}
        {histPts
          .filter((p) => p.isInterpolated)
          .map((p, idx) => (
            <circle
              key={idx}
              cx={p.x}
              cy={p.y}
              r="4.5"
              fill="#f59e0b"
              stroke="#ffffff"
              strokeWidth="1.5"
            >
              <title>{`Ngày ${p.date}: Nội suy (${formatVnd(p.price)} đ/kg)`}</title>
            </circle>
          ))}

        {histPts.length > 0 && (
          <text x={histPts[0].x} y={height - 18} className="fill-slate-600 font-semibold" fontSize="12">
            {formatShortDateVi(histPts[0].date)}
          </text>
        )}
        {lastHist && (
          <text
            x={lastHist.x}
            y={height - 18}
            textAnchor="middle"
            className="fill-slate-900 font-extrabold"
            fontSize="12"
          >
            Hiện tại: {formatShortDateVi(lastHist.date)}
          </text>
        )}
        {fcPts.length > 0 && (
          <text
            x={fcPts[fcPts.length - 1].x}
            y={height - 18}
            textAnchor="end"
            className="fill-emerald-800 font-extrabold"
            fontSize="12"
          >
            {formatShortDateVi(fcPts[fcPts.length - 1].date)}
          </text>
        )}

        {/* VÙNG HOVER & TOOLTIP TƯƠNG TÁC */}
        {allHoverPoints.map((pt, i) => (
          <circle
            key={i}
            cx={pt.x}
            cy={pt.y}
            r="12"
            fill="transparent"
            className="cursor-pointer"
            onMouseEnter={() => setHovered(pt)}
          />
        ))}

        {hovered && (
          <g className="pointer-events-none">
            <line
              x1={hovered.x}
              y1={padTop}
              x2={hovered.x}
              y2={height - padBottom}
              stroke="#334155"
              strokeWidth="1.5"
              strokeDasharray="3 3"
            />
            <circle cx={hovered.x} cy={hovered.y} r="7" fill="#ffffff" stroke="#047857" strokeWidth="2.5" />

            {(() => {
              const tipW = 220;
              const tipH = hovered.type === 'FORECAST' ? 82 : 62;
              const tipX = Math.max(padLeft + 10, Math.min(width - padRight - tipW, hovered.x - tipW / 2));
              const tipY = hovered.y > padTop + tipH + 20 ? hovered.y - tipH - 14 : hovered.y + 18;
              return (
                <g>
                  <rect
                    x={tipX}
                    y={tipY}
                    width={tipW}
                    height={tipH}
                    rx="8"
                    fill="#0f172a"
                    fillOpacity="0.95"
                  />
                  <text x={tipX + 12} y={tipY + 20} fill="#94a3b8" fontSize="12" fontWeight="600">
                    {formatDateVN(hovered.date)} ({hovered.type === 'HISTORICAL' ? 'Giá thực tế' : 'Dự báo'})
                  </text>
                  <text x={tipX + 12} y={tipY + 44} fill="#ffffff" fontSize="16" fontWeight="800">
                    {formatVnd(hovered.type === 'HISTORICAL' ? hovered.price : hovered.yhat)} {unit}
                  </text>
                  {hovered.type === 'FORECAST' && (
                    <text x={tipX + 12} y={tipY + 66} fill="#6ee7b7" fontSize="11" fontWeight="600">
                      CI 95%: [{formatVnd(hovered.lower)} – {formatVnd(hovered.upper)}]
                    </text>
                  )}
                </g>
              );
            })()}
          </g>
        )}
      </svg>
    </div>
  );
}

/**
 * 3. Biểu đồ Cột So sánh Sai số MAPE (%) & RMSE (VNĐ/kg) giữa 7 Mô hình (FR-22).
 */
export function ModelMetricsBarChart({ leaderboard = [] }) {
  if (!leaderboard || leaderboard.length === 0) return null;

  const maxMape = Math.max(...leaderboard.map((m) => Number(m.mape || 0)), 0.1);
  const maxRmse = Math.max(...leaderboard.map((m) => Number(m.rmse || 0)), 1);

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <div className="bg-slate-50 p-4 rounded-xl border border-slate-200">
        <h4 className="font-bold text-slate-900 mb-3 text-base">
          So sánh MAPE (%) giữa 7 Mô hình (Thấp hơn là tốt hơn)
        </h4>
        <div className="space-y-2.5">
          {leaderboard.map((m) => {
            const pctWidth = Math.max(6, Math.min(100, (Number(m.mape || 0) / maxMape) * 100));
            return (
              <div key={m.model_type} className="text-sm">
                <div className="flex justify-between font-semibold mb-1">
                  <span className="text-slate-900">
                    {m.is_selected ? '🏆 ' : ''}
                    {m.model_type}
                  </span>
                  <span className="text-slate-800">{Number(m.mape || 0).toFixed(4)}%</span>
                </div>
                <div className="w-full bg-slate-200 h-3.5 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full ${
                      m.is_selected ? 'bg-emerald-700' : m.is_baseline ? 'bg-slate-500' : 'bg-sky-700'
                    }`}
                    style={{ width: `${pctWidth}%` }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div className="bg-slate-50 p-4 rounded-xl border border-slate-200">
        <h4 className="font-bold text-slate-900 mb-3 text-base">
          So sánh RMSE (VNĐ/kg) giữa 7 Mô hình (Thấp hơn là tốt hơn)
        </h4>
        <div className="space-y-2.5">
          {leaderboard.map((m) => {
            const pctWidth = Math.max(6, Math.min(100, (Number(m.rmse || 0) / maxRmse) * 100));
            return (
              <div key={m.model_type} className="text-sm">
                <div className="flex justify-between font-semibold mb-1">
                  <span className="text-slate-900">
                    {m.is_selected ? '🏆 ' : ''}
                    {m.model_type}
                  </span>
                  <span className="text-slate-800">{formatVnd(m.rmse)} đ/kg</span>
                </div>
                <div className="w-full bg-slate-200 h-3.5 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full ${
                      m.is_selected ? 'bg-emerald-700' : m.is_baseline ? 'bg-slate-500' : 'bg-indigo-700'
                    }`}
                    style={{ width: `${pctWidth}%` }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

/**
 * 4. Biểu đồ Kiểm chứng ngược Backtesting 30 ngày quá khứ (FR-44):
 * Đối chiếu trực tiếp Giá Thực tế (actual_price) vs Giá Mô hình Dự báo (predicted_price) kèm Tooltip hover.
 */
export function BacktestComparisonChart({ backtestSeries = [] }) {
  const [hovered, setHovered] = useState(null);

  if (!backtestSeries || backtestSeries.length === 0) {
    return (
      <div className="p-6 text-center text-slate-600 bg-slate-50 rounded-xl border border-slate-200">
        Chưa có dữ liệu kiểm chứng ngược (Backtesting).
      </div>
    );
  }

  const allVals = backtestSeries.flatMap((d) => [
    Number(d.actual_price),
    Number(d.predicted_price),
  ]);
  const minVal = Math.min(...allVals);
  const maxVal = Math.max(...allVals);
  const padVal = Math.max((maxVal - minVal) * 0.2, maxVal * 0.008, 50);
  const yMin = Math.max(0, minVal - padVal);
  const yMax = maxVal + padVal;

  const width = 900;
  const height = 330;
  const padLeft = 105;
  const padRight = 35;
  const padTop = 30;
  const padBottom = 50;
  const plotW = width - padLeft - padRight;
  const plotH = height - padTop - padBottom;

  const getX = (idx) => {
    if (backtestSeries.length <= 1) return padLeft + plotW / 2;
    return padLeft + (idx / (backtestSeries.length - 1)) * plotW;
  };
  const getY = (v) => {
    if (yMax <= yMin) return padTop + plotH / 2;
    return padTop + plotH - ((v - yMin) / (yMax - yMin)) * plotH;
  };

  const actualPath = backtestSeries
    .map((d, i) => `${i === 0 ? 'M' : 'L'} ${getX(i).toFixed(1)} ${getY(Number(d.actual_price)).toFixed(1)}`)
    .join(' ');

  const predPath = backtestSeries
    .map((d, i) => `${i === 0 ? 'M' : 'L'} ${getX(i).toFixed(1)} ${getY(Number(d.predicted_price)).toFixed(1)}`)
    .join(' ');

  const yTicks = [yMin, (yMin + yMax) / 2, yMax];

  return (
    <div className="w-full relative">
      <div className="flex flex-wrap items-center gap-6 mb-3 text-sm font-semibold text-slate-800">
        <span className="inline-flex items-center gap-2">
          <span className="inline-block w-7 h-1 bg-slate-900 rounded" />
          <span>Giá thực tế đã xảy ra (actual_price)</span>
        </span>
        <span className="inline-flex items-center gap-2">
          <span className="inline-block w-7 h-0 border-t-3 border-dashed border-rose-700" />
          <span>Giá mô hình đã dự báo từ 30 ngày trước (yhat)</span>
        </span>
      </div>

      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full h-auto bg-white rounded-xl border border-slate-300 select-none"
        role="img"
        aria-label="Biểu đồ kiểm chứng ngược đối chiếu giá thực tế và giá dự báo trong 30 ngày qua"
        onMouseLeave={() => setHovered(null)}
      >
        {yTicks.map((tv, i) => {
          const y = getY(tv);
          return (
            <g key={i}>
              <line
                x1={padLeft}
                y1={y}
                x2={width - padRight}
                y2={y}
                stroke="#e2e8f0"
                strokeWidth="1"
              />
              <text
                x={padLeft - 10}
                y={y + 4}
                textAnchor="end"
                className="fill-slate-700 font-semibold"
                fontSize="13"
              >
                {formatVnd(tv)}
              </text>
            </g>
          );
        })}

        <path d={actualPath} fill="none" stroke="#0f172a" strokeWidth="3" strokeLinejoin="round" />
        <path
          d={predPath}
          fill="none"
          stroke="#be123c"
          strokeWidth="3"
          strokeDasharray="8 5"
          strokeLinejoin="round"
        />

        <text x={padLeft} y={height - 16} className="fill-slate-700 font-semibold" fontSize="12">
          {formatDateVN(backtestSeries[0].target_date)}
        </text>
        <text
          x={width - padRight}
          y={height - 16}
          textAnchor="end"
          className="fill-slate-700 font-semibold"
          fontSize="12"
        >
          {formatDateVN(backtestSeries[backtestSeries.length - 1].target_date)}
        </text>

        {/* Hover detection for Backtest */}
        {backtestSeries.map((d, i) => (
          <circle
            key={i}
            cx={getX(i)}
            cy={getY(Number(d.actual_price))}
            r="12"
            fill="transparent"
            className="cursor-pointer"
            onMouseEnter={() => setHovered({ ...d, x: getX(i), y: getY(Number(d.actual_price)) })}
          />
        ))}

        {hovered && (
          <g className="pointer-events-none">
            <line
              x1={hovered.x}
              y1={padTop}
              x2={hovered.x}
              y2={height - padBottom}
              stroke="#475569"
              strokeWidth="1.5"
              strokeDasharray="3 3"
            />
            {(() => {
              const tipW = 210;
              const tipH = 75;
              const tipX = Math.max(padLeft + 8, Math.min(width - padRight - tipW, hovered.x - tipW / 2));
              const tipY = hovered.y > padTop + tipH + 20 ? hovered.y - tipH - 12 : hovered.y + 16;
              return (
                <g>
                  <rect
                    x={tipX}
                    y={tipY}
                    width={tipW}
                    height={tipH}
                    rx="8"
                    fill="#0f172a"
                    fillOpacity="0.94"
                  />
                  <text x={tipX + 12} y={tipY + 20} fill="#94a3b8" fontSize="11" fontWeight="600">
                    {formatDateVN(hovered.target_date)} (h={hovered.horizon})
                  </text>
                  <text x={tipX + 12} y={tipY + 42} fill="#ffffff" fontSize="14" fontWeight="bold">
                    Thực tế: {formatVnd(hovered.actual_price)} đ
                  </text>
                  <text x={tipX + 12} y={tipY + 62} fill="#f43f5e" fontSize="14" fontWeight="bold">
                    Dự báo: {formatVnd(hovered.predicted_price)} đ ({hovered.error_amount > 0 ? '+' : ''}
                    {formatVnd(hovered.error_amount)} đ)
                  </text>
                </g>
              );
            })()}
          </g>
        )}
      </svg>
    </div>
  );
}
