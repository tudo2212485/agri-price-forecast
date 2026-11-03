# Processing Module

Module xử lý tiền xử lý dữ liệu nông sản & thời tiết:
- `normalize.py`: Chuẩn hóa tên tỉnh/khu vực (FR-33) qua bảng `province_alias`, chuẩn hóa chuỗi và đơn vị tiền tệ (`VNĐ/kg`).
- `quality_check.py`: Kiểm tra tính toàn vẹn (thiếu, trùng, ngoại lệ, giá âm, chéo nguồn theo FR-06, FR-35).
- `imputation.py`: Xử lý giá trị khuyết thiếu và gán cờ nội suy (`is_interpolated`, `quality_flag` theo FR-08, FR-36).
- `features.py`: Tạo đặc trưng chuỗi thời gian (lags, rolling mean/std, seasonality, weather features theo FR-09).

