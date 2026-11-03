# 🌾 Hệ thống Phân tích Dữ liệu và Dự báo Biến động Giá Nông sản theo Chuỗi Thời gian sử dụng Học máy (SRS v1.1)

Đồ án Tốt nghiệp xây dựng hệ thống khép kín (End-to-End Data Engineering & Machine Learning System) thu thập, kiểm định chất lượng, chuẩn hóa, tạo đặc trưng chuỗi thời gian, huấn luyện đa mô hình dự báo (Baseline, Prophet, Random Forest, XGBoost, LSTM), phát cảnh báo sớm và hiển thị trên **Giao diện Web Hai Chế Độ** (Chế độ Đơn giản cho Nông dân lớn tuổi & Chế độ Chuyên sâu cho GVHD/Hội đồng).

---

## 1. Kiến trúc Hệ thống & Cấu trúc Thư mục (NFR-07)

```text
agri-price-forecast/
├── api/                        # FastAPI Backend, Trình diễn giải ngôn ngữ nông dân & Dịch vụ Cảnh báo
│   ├── main.py                 # RESTful API Endpoints & Phục vụ SPA tĩnh (ui/dist)
│   ├── farmer_translator.py    # Chuyển đổi dự báo & MAPE sang ngôn ngữ đời thường tiếng Việt (FR-49..FR-51)
│   ├── alert_service.py        # Động cơ quét cảnh báo chống gửi trùng (FR-24..FR-27, FR-52, FR-53)
│   ├── pipeline_runner.py      # Điều phối Pipeline & Giám sát Data/Model Drift (FR-28, FR-29, FR-42)
│   └── schemas.py              # Pydantic v2 Request/Response Validation (NFR-05)
├── collector/                  # Thu thập dữ liệu Giá nông sản & Thời tiết thực tế, Backfill có Checkpoint
│   ├── base.py                 # BaseCollector: Retry exponential backoff, Rate-limit, Pipeline Logger, Upsert
│   ├── weather_collector.py    # Open-Meteo Archive & Forecast API cho 8 tỉnh trọng điểm (FR-03, FR-34)
│   ├── price_collector.py      # Bộ thu thập giá & chuẩn hóa đơn vị về VNĐ/kg + Truy vết nguồn (FR-01, FR-32)
│   └── backfill.py             # Backfill lịch sử 2023-2026 có lưu mốc checkpoint (FR-40, FR-41)
├── processing/                 # Kiểm tra chất lượng, Làm sạch, Nội suy ngắn hạn & Kỹ thuật Đặc trưng
│   ├── normalize.py            # Chuẩn hóa chuỗi tiếng Việt & Ánh xạ biệt danh tỉnh/huyện (FR-33)
│   ├── quality_check.py        # Kiểm định chất lượng, Z-score/IQR Outlier & Đối chiếu chéo nguồn (FR-35)
│   ├── cleaner.py              # Nội suy tuyến tính khoảng trống ngắn (<= 3 ngày) có gắn cờ (FR-08, FR-36)
│   ├── features.py             # Tạo 31 đặc trưng Lag, Rolling, Thời tiết & Mùa vụ chống rò rỉ tương lai (NFR-04)
│   └── eda.py                  # Phân tích khám phá (STL Decomposition, Correlation, ACF) & Xuất biểu đồ 150 DPI
├── models/                     # Huấn luyện, Đánh giá Chia theo Thời gian, Chọn Mô hình & Backtesting
│   ├── evaluation.py           # Cố định Seed (42), MAE/RMSE/MAPE, Rolling-Origin Split & Phân tích phần dư
│   ├── forecasters.py          # 7 Mô hình: NAIVE, SEASONAL_NAIVE, MOVING_AVG, PROPHET, RANDOM_FOREST, XGBOOST, LSTM
│   ├── trainer.py              # Huấn luyện thực nghiệm 77 model runs & Tự động chọn Champion (is_selected=True)
│   └── predictor.py            # Sinh dự báo 30 ngày tương lai kèm CI 95% & Kiểm chứng ngược 30 ngày quá khứ
├── db/                         # Cơ sở dữ liệu PostgreSQL 15 + TimescaleDB (SQLAlchemy 2.0 ORM)
│   ├── database.py             # Kết nối DB, SessionLocal & Múi giờ chuẩn Asia/Ho_Chi_Minh (UTC+7)
│   ├── models.py               # 14 thực thể ORM đầy đủ ràng buộc UniqueConstraint
│   └── views.py                # SQL View `data_coverage_view` thống kê độ phủ dữ liệu (FR-42)
├── ui/                         # Giao diện Web 2 Chế độ (React 18 + Vite + Tailwind CSS)
│   ├── src/App.jsx             # Khung điều hướng 2 chế độ, Phóng to cỡ chữ (18/20/22px) & Hộp thoại Trợ giúp
│   ├── src/components/         # FarmerModeView.jsx (Nông dân), ExpertModeView.jsx (Chuyên gia), SvgCharts.jsx
│   └── Dockerfile              # Đóng gói container giao diện Frontend
├── scripts/                    # Các công cụ CLI khởi tạo, thực thi từng Phase & Lập lịch tự động
│   ├── init_db.py              # Khởi tạo Schema, SQL View & Seed Master Data
│   └── scheduler.py            # Lập lịch tự động hàng ngày bằng Prefect & Giám sát Drift (FR-04, FR-29)
├── docs/                       # Tài liệu SRS v1.1, Biểu đồ EDA, Báo cáo Đánh giá Mô hình & Usability Report
├── tests/                      # Bộ 30 bài kiểm thử tự động (Unit, Integration & End-to-End Pytest)
├── Dockerfile.api              # Đóng gói container FastAPI Backend & Modeling Engine
└── docker-compose.yml          # Khởi chạy toàn hệ thống (TimescaleDB + FastAPI + React UI) với 1 lệnh
```

---

## 2. Đối chiếu Hoàn thành Yêu cầu Chức năng & Phi chức năng (SRS v1.1)

| Nhóm yêu cầu | Mã yêu cầu trong SRS v1.1 | Trạng thái | Module đáp ứng |
| :--- | :--- | :---: | :--- |
| **Thu thập & Backfill** | **FR-01..FR-05, FR-30..FR-34, FR-40..FR-42** | ✅ **100%** | `collector/base.py`, `price_collector.py`, `weather_collector.py`, `backfill.py` |
| **Làm sạch, Nội suy & EDA** | **FR-06..FR-10, FR-35..FR-38** | ✅ **100%** | `processing/quality_check.py`, `cleaner.py`, `features.py`, `eda.py` |
| **Huấn luyện & Backtesting** | **FR-11..FR-18, FR-43..FR-46** | ✅ **100%** | `models/evaluation.py`, `forecasters.py`, `trainer.py`, `predictor.py` |
| **Dashboard & Chế độ Chuyên gia** | **FR-19..FR-23, FR-28, FR-29, FR-39** | ✅ **100%** | `api/main.py`, `ui/src/components/ExpertModeView.jsx` |
| **Cảnh báo & Đăng ký 1 bước** | **FR-24..FR-27, FR-52, FR-53** | ✅ **100%** | `api/alert_service.py`, `logs/sent_alerts.log` |
| **Chế độ Nông dân lớn tuổi** | **FR-47..FR-51, FR-54, FR-55** | ✅ **100%** | `api/farmer_translator.py`, `ui/src/components/FarmerModeView.jsx`, `docs/usability_test_report.md` |
| **Yêu cầu Phi chức năng** | **NFR-01..NFR-15** | ✅ **100%** | Độ trễ API `< 70ms` (`<< 3000ms`), Không rò rỉ dữ liệu tương lai, WCAG AA, Docker Compose |

---

## 3. Hướng dẫn Khởi chạy Hệ thống

### Cách 1: Khởi chạy Toàn hệ thống bằng Docker Compose (NFR-08)
```bash
cp .env.example .env
docker compose up -d --build
```
- **TimescaleDB (PostgreSQL 15):** `localhost:5432`
- **FastAPI Backend & Swagger Docs:** `http://localhost:8000` (`http://localhost:8000/docs`)
- **React Web Dashboard (2 Chế độ):** `http://localhost:5173`

### Cách 2: Khởi chạy Môi trường Phát triển (Local Development)
1. **Khởi động CSDL TimescaleDB & Cài đặt thư viện Python:**
   ```bash
   docker compose up -d timescaledb
   pip install -r requirements.txt
   ```
2. **Chạy lần lượt các Pipeline (Khởi tạo DB -> Thu thập/Backfill -> Làm sạch/Đặc trưng -> Huấn luyện/Dự báo -> Kiểm định API):**
   ```bash
   python scripts/init_db.py
   python scripts/run_phase2_collector.py
   python scripts/run_phase3_processing.py
   python scripts/run_phase4_modeling.py
   python scripts/run_phase5_api_check.py
   ```
3. **Khởi động Backend API & Giao diện Web React:**
   ```bash
   # Terminal 1: Chạy FastAPI Server (đồng thời phục vụ luôn ui/dist tại http://localhost:8000)
   uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

   # Terminal 2: Chạy Vite Dev Server tại http://localhost:5173
   cd ui
   npm install
   npm run dev
   ```
4. **Chạy Bộ Lập lịch Tự động & Giám sát Độ ổn định (FR-04, FR-29):**
   ```bash
   python scripts/scheduler.py --once
   ```
5. **Chạy Toàn bộ Bộ Kiểm thử Tự động (Phase 1 -> Phase 6):**
   ```bash
   python -m pytest tests/ -v
   ```

---

## 4. Quy ước Quản lý Mã nguồn & Commit (NFR-07)
Dự án áp dụng chuẩn Conventional Commits:
- `feat(collector): ...` — Thêm tính năng thu thập dữ liệu & backfill
- `feat(processing): ...` — Làm sạch, nội suy ngắn hạn và kỹ thuật đặc trưng
- `feat(models): ...` — Huấn luyện mô hình dự báo và kiểm chứng ngược
- `feat(api): ...` — Dịch vụ FastAPI, diễn giải ngôn ngữ nông dân và cảnh báo
- `feat(ui): ...` — Giao diện Web 2 chế độ hỗ trợ nông dân lớn tuổi và chuyên gia
- `test(e2e): ...` — Kiểm thử đơn vị, tích hợp và kiểm thử đầu-cuối
