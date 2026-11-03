# Models Module

Quản lý toàn bộ vòng đời huấn luyện, đánh giá và suy luận mô hình học máy:
- `baselines/`: Triển khai Naive, Seasonal Naive, Moving Average (FR-11).
- `prophet/`: Huấn luyện mô hình Facebook Prophet kèm biến ngoại sinh thời tiết và mùa vụ (FR-12).
- `machine_learning/`: Huấn luyện Random Forest và XGBoost đa bước (FR-13).
- `deep_learning/`: Huấn luyện PyTorch LSTM khi đủ điều kiện dữ liệu (FR-14).
- `evaluation/`: Đánh giá TimeSeriesSplit rolling origin, tính MAE, RMSE, MAPE và phân tích sai số (FR-15, FR-16).
- `inference/`: Sinh dự báo từ 7 đến 30 ngày kèm khoảng tin cậy (FR-17).

