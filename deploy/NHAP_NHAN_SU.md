# Nhập SỔ NHÂN SỰ — để câu "công ty có bao nhiêu nhân sự" trả lời chính xác 100%

## Vì sao phải nhập

Hệ thống có sẵn đường trả lời **xác định** (đếm bằng SQL, không qua model sinh
văn bản) cho các câu:

- "công ty tôi có bao nhiêu nhân sự / mấy người"
- "bao nhiêu người còn hợp đồng lao động"
- "danh sách nhân sự gồm những ai"

Đường này chỉ chạy khi bảng `employees` + `employment_contracts` có dữ liệu.
Khi bảng trống, câu hỏi rơi xuống tra cứu tài liệu và model phải **suy ra** con
số từ các đoạn tìm được — đã từng trả lời nhầm bằng "tổng số lao động dự kiến:
02" trong hồ sơ đăng ký doanh nghiệp CỦA KHÁCH.

Nhập một lần, sau đó chỉ cập nhật khi có người vào/ra hoặc ký/gia hạn HĐLĐ.

## Cách nhập

API `/hr` đã bật sẵn trên backend (xem đủ tham số tại `https://<máy chủ>/docs`,
mục **hr**). Quyền: tài khoản nội bộ xem được; **thêm/sửa cần Ban QT hoặc admin**.

1. Sửa file mẫu [`mau-nhap-nhan-su.csv`](./mau-nhap-nhan-su.csv) — theo thư mục
   `8. HỒ SƠ NHÂN SỰ` trên Drive hiện có **3 nhân sự: Mai, Ngân, Nhi**. Hai dòng
   đầu lấy số HĐ/ngày ký từ hồ sơ đã học; dòng Ngân chưa có số HĐLĐ trong Drive
   (chỉ có CV, báo cáo) nên phải điền họ tên đầy đủ + hợp đồng trước khi import.
   **Kiểm tra lại trước khi import**, nhất là khi HĐLĐ đã được gia hạn (mỗi hợp
   đồng một dòng, lặp lại mã + họ tên nhân viên; hệ thống tự gộp theo mã).

   Cột nhận cả tên tiếng Việt không dấu: `ma_nhan_vien`, `ho_ten`, `chuc_danh`,
   `trang_thai_nhan_su` (dang_lam_viec / nghi_viec / nghi_phep),
   `so_hop_dong`, `ngay_bat_dau`, `ngay_ket_thuc` (DD/MM/YYYY hoặc YYYY-MM-DD),
   `trang_thai_hop_dong` (con_hieu_luc / het_han / cham_dut). Nhận cả `.xlsx`.

2. Đăng nhập lấy token rồi **kiểm tra thử** (không ghi gì):

   ```bash
   TOKEN=$(curl -s -X POST https://<máy chủ>/auth/login \
     -H 'Content-Type: application/json' \
     -d '{"email":"<email admin>","password":"<mật khẩu>"}' | jq -r .access_token)

   curl -s -X POST https://<máy chủ>/hr/import/validate \
     -H "Authorization: Bearer $TOKEN" \
     -F "upload=@deploy/mau-nhap-nhan-su.csv"
   ```

3. Kết quả validate sạch lỗi thì import thật:

   ```bash
   curl -s -X POST https://<máy chủ>/hr/import \
     -H "Authorization: Bearer $TOKEN" \
     -F "upload=@deploy/mau-nhap-nhan-su.csv"
   ```

4. Vào chat nội bộ hỏi lại **"cty tôi có bao nhiêu nhân sự"** — câu trả lời
   phải là dạng "HDS có **N nhân sự đang hoạt động** trong sổ nhân sự (tính đến
   ngày …)", nguồn ghi `employees`, KHÔNG còn dẫn tài liệu của khách.

Chạy lại import với file mới là CẬP NHẬT (khớp theo `ma_nhan_vien`), không tạo
trùng. Người nghỉ việc: đổi `trang_thai_nhan_su` thành `nghi_viec` — bot sẽ
ngừng đếm người đó.
