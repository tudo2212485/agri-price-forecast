# API Module

Cung cấp các điểm cuối RESTful API hiệu năng cao bằng FastAPI (Section 5.2, Section 6):
- `/api/commodities`: Danh mục nông sản và tỉnh thành trọng điểm.
- `/api/prices`: Dữ liệu giá lịch sử kèm bộ lọc nông sản, tỉnh thành, khoảng thời gian.
- `/api/forecast`: Dữ liệu dự báo 7-30 ngày cùng khoảng tin cậy từ mô hình tốt nhất đã chọn.
- `/api/models/metrics`: Bảng so sánh chỉ số sai số MAE, RMSE, MAPE giữa các mô hình.
- `/api/alerts`: Quản lý quy tắc và lịch sử sự kiện cảnh báo biến động giá.
- `/api/subscriptions`: Đăng ký nhận thông báo cảnh báo qua Email/SMS/Zalo.
- `/api/pipeline/status`: Trạng thái và nhật ký thực thi của hệ thống thu thập & huấn luyện.

