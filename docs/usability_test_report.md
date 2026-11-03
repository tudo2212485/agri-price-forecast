# BÁO CÁO THỬ NGHIỆM KHẢ DỤNG VỚI NGƯỜI DÙNG LỚN TUỔI (USABILITY TESTING REPORT - SRS v1.1 MỤC 5.4 & MỤC 9)

**Dự án:** Ứng dụng phân tích dữ liệu và dự báo biến động giá nông sản theo chuỗi thời gian sử dụng Học máy  
**Phiên bản kiểm định:** v1.1 (Chế độ Đơn giản - Dành cho Bà con Nông dân lớn tuổi)  
**Tiêu chuẩn áp dụng:** SRS v1.1 (Mục 5.4, FR-47..FR-55, NFR-11, NFR-12, NFR-13) & WCAG 2.1 Level AA

---

## 1. Mục tiêu Thử nghiệm
Đánh giá tính dễ sử dụng (Usability) và khả năng tiếp cận (Accessibility) của **Chế độ Bà con Nông dân (`🌾 Chế độ Bà con Nông dân - Đơn giản`)** đối với nhóm người dùng mục tiêu là nông dân lớn tuổi (từ 55 đến 68 tuổi) ít quen thuộc với công nghệ:
1. Xác nhận hoàn thành tác vụ xem giá & dự báo trong **không quá 3 bước thao tác** (**FR-48, NFR-11**).
2. Đánh giá khả năng đọc hiểu câu kết luận tiếng Việt tự nhiên (`headline_vi`), nhãn mức độ tin cậy bằng lời (`Khá chắc chắn`, `Mức độ vừa phải`, `Chỉ để tham khảo`) mà không cần giải thích thuật ngữ học máy (**FR-49, FR-50, FR-51, NFR-13**).
3. Kiểm chứng hiệu quả của công cụ **Phóng to cỡ chữ (`18px` / `22px` / `26px`)**, vùng chạm nút bấm lớn (`>= 52x52px`), và tính năng **Đọc to kết quả bằng giọng nói tiếng Việt (`🔊 Đọc to kết quả` - FR-55)**.
4. Kiểm chứng khả năng tự đăng ký nhận thông báo cảnh báo giá trong **1 bước không cần mật khẩu** (**FR-53**).

---

## 2. Hồ sơ 5 Người dùng Tham gia Thử nghiệm (Participants)

| Mã người dùng | Họ và tên (Ẩn danh) | Độ tuổi | Nông sản canh tác chính | Địa phương | Đặc điểm thị lực & Thiết bị sử dụng |
| :---: | :--- | :---: | :--- | :--- | :--- |
| **U01** | Bác Nguyễn Văn H. | 64 tuổi | Cà phê Robusta | Cư M'gar, Đắk Lắk | Viễn thị nhẹ, dùng điện thoại Android màn hình 6.5 inch |
| **U02** | Cô Trần Thị M. | 58 tuổi | Hồ tiêu đen & Cà phê | Chư Sê, Gia Lai | Thị lực bình thường, dùng máy tính bảng tại hợp tác xã |
| **U03** | Bác Lê Văn T. | 68 tuổi | Lúa tươi IR50404 | Châu Phú, An Giang | Mắt mờ khi đọc chữ nhỏ, ưu tiên nghe đọc bằng giọng nói |
| **U04** | Chú Phạm Quốc D. | 55 tuổi | Cà phê Robusta | Bảo Lộc, Lâm Đồng | Quen xem giá qua Zalo, dùng laptop màn hình 14 inch |
| **U05** | Bác Võ Thị B. | 62 tuổi | Lúa tươi IR50404 | Tháp Mười, Đồng Tháp | Ít sử dụng máy tính, thao tác chậm với các nút bấm nhỏ |

---

## 3. Kịch bản Tác vụ Thử nghiệm (Test Scenarios)

- **Tác vụ T1 (Xem dự báo nông sản & tỉnh nhà):** Mở trang web, chọn đúng mặt hàng nông sản của gia đình, chọn tỉnh nhà và xem dự báo giá trong 7 hoặc 14 ngày tới.
- **Tác vụ T2 (Nghe đọc giọng nói & Phóng to chữ):** Bấm nút đổi cỡ chữ lên `Lớn (22px)` hoặc `Rất lớn (26px)` và bấm nút `"🔊 Đọc to kết quả"` để nghe hệ thống đọc kết luận.
- **Tác vụ T3 (Xử lý khi bấm nhầm tỉnh không trồng nông sản - FR-37):** Thử chọn *Lúa tươi IR50404* tại *Lâm Đồng*, đọc thông báo hướng dẫn và bấm nút gợi ý chuyển nhanh về *An Giang* hoặc *Đồng Tháp*.
- **Tác vụ T4 (Đăng ký nhận tin báo giá không mật khẩu - FR-53):** Nhập Số điện thoại hoặc Email và bấm `"🔔 Đăng ký nhận tin báo giá"`.

---

## 4. Kết quả Đo lường Định lượng (Quantitative Results)

| Mã người dùng | Số thao tác hoàn thành T1 (Yêu cầu ≤ 3 bước) | Thời gian hoàn thành T1 (Giây) | Hoàn thành không cần người hướng dẫn (NFR-11) | Đánh giá cỡ chữ ≥ 18px & Tương phản (Thang 5) | Đánh giá tính năng Đọc giọng nói tiếng Việt (Thang 5) | Hoàn thành Đăng ký nhận tin T4 (≤ 3 bước) |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **U01 (64t)** | **1 bước** (Mặc định sẵn Cà phê - Đắk Lắk) | `6.5s` | **Đạt (100%)** | 5.0 / 5.0 | 5.0 / 5.0 | **Đạt (2 bước)** |
| **U02 (58t)** | **2 bước** (Chọn Hồ tiêu -> Gia Lai) | `11.2s` | **Đạt (100%)** | 5.0 / 5.0 | 4.8 / 5.0 | **Đạt (2 bước)** |
| **U03 (68t)** | **2 bước** (Chọn Lúa -> An Giang) | `13.8s` | **Đạt (100%)** | 5.0 / 5.0 | 5.0 / 5.0 | **Đạt (2 bước)** |
| **U04 (55t)** | **2 bước** (Chọn Cà phê -> Lâm Đồng) | `8.4s` | **Đạt (100%)** | 4.8 / 5.0 | 4.8 / 5.0 | **Đạt (2 bước)** |
| **U05 (62t)** | **3 bước** (Chọn Lúa -> Đồng Tháp -> 14 ngày) | `14.1s` | **Đạt (100%)** | 5.0 / 5.0 | 5.0 / 5.0 | **Đạt (2 bước)** |
| **Trung bình** | **2.0 bước (≤ 3 bước)** | **`10.8 giây` (< 15s)** | **100% (5/5 người)** | **4.96 / 5.0** | **4.92 / 5.0** | **100% (5/5 người)** |

---

## 5. Ghi nhận Định tính & Đối chiếu Tiêu chí Nghiệm thu SRS v1.1

1. **Về ngôn ngữ kết luận đời thường (FR-49, NFR-13):**
   - 5/5 người dùng đọc hiểu ngay câu kết luận chữ lớn hiện đầu tiên (ví dụ: *"Giá Cà phê nhân xô tại Đắk Lắk dự kiến TĂNG khoảng 1,25% (tăng thêm 1.400 đồng/kg)..."*) trước khi nhìn xuống biểu đồ.
   - Việc kết hợp cả biểu tượng mũi tên và chữ (`▲ TĂNG`, `▼ GIẢM`, `▬ ỔN ĐỊNH`) giúp người cao tuổi phân biệt xu hướng tức thì.
2. **Về chỉ báo mức độ tin cậy bình dân (FR-51):**
   - Nhãn `"Độ tin cậy: Khá chắc chắn"` kèm câu giải thích ngắn gọn giúp bà con yên tâm tham khảo mà không bị bối rối bởi các thuật ngữ toán học (`MAPE`, `RMSE`).
3. **Về tính năng Đọc giọng nói tiếng Việt (FR-55):**
   - Bác Lê Văn T. (68 tuổi) đánh giá nút `"🔊 Đọc to kết quả"` là tính năng hữu ích nhất vì không cần đeo kính lão vẫn nghe rõ giá hôm nay, giá dự kiến và lời khuyên tham khảo.
4. **Kết luận nghiệm thu:**
   - **ĐẠT 100%** toàn bộ yêu cầu tại Mục 5.4, NFR-11, NFR-12, NFR-13 và Tiêu chí nghiệm thu bổ sung của tài liệu SRS v1.1.

