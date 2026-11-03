# Collector Module

Module chịu trách nhiệm thu thập dữ liệu giá nông sản và thông số thời tiết từ các nguồn công khai:
- `scrapers/`: Trích xuất dữ liệu giá cà phê, hồ tiêu, lúa gạo hàng ngày.
- `weather/`: Tích hợp Open-Meteo API thu thập dữ liệu thời tiết lịch sử và hiện tại cho 8 tỉnh trọng điểm.
- `backfill/`: Quản lý các tiến trình nạp bù dữ liệu lịch sử theo batch và checkpoint trạng thái (hỗ trợ tiếp tục khi gián đoạn).

