# -*- coding: utf-8 -*-
"""Các phần VĂN XUÔI cố định của tài liệu kiểm thử (không phải bảng ca test)."""

TIEU_DE = "KẾ HOẠCH & KỊCH BẢN KIỂM THỬ NGHIỆM THU — TRỢ LÝ AI HDS"

MO_DAU = """\
Tài liệu dành cho **tester** (người kiểm thử của Diginix hoặc HDS) để kiểm tra hệ thống
có chạy **đúng hợp đồng** và **đúng kỳ vọng của một công ty luật** hay không. Mỗi ca
kiểm thử ghi rõ: dùng tài khoản nào, **gửi gì vào** (câu gõ / file đính kèm / thao tác),
và **phải nhận được gì** (nhãn, con số, mã lỗi, file) — đủ cụ thể để hai người chấm
độc lập ra cùng một kết quả.

- Bản này lập ngày **02/10/2026**, cập nhật **03/10/2026** sau đợt sửa lỗi nghiệm thu (31 phát
  hiện ngày 02/10 + 1 phát hiện khi chạy lại); đối chiếu với mã nguồn đang chạy trên máy chủ
  (đã so mã băm từng tệp backend + frontend với bản phát triển).
- Địa chỉ thử: `https://app.diginix.io.vn` (tên miền `app.hdslaw.vn` chưa trỏ).
- Sổ ghi kết quả: **`KICH_BAN_KIEM_THU.xlsx`** cùng thư mục — mọi ca ở đây đều có một
  dòng trong sheet *Ca kiểm thử*, tester chỉ điền các cột tô vàng.
- File đầu vào mẫu: thư mục **`du-lieu-mau/`** (hợp đồng cài sẵn vi phạm, CCCD/CV giả,
  tài liệu chèn lệnh, 4 tài liệu "chim mồi" kiểm tra phân quyền). Kết quả mong đợi
  của các file này **đã được chạy thật** qua bộ quy tắc của hệ thống (chạy lại 03/10 sau khi sửa quy tắc).

> **Nguyên tắc chấm:** hệ thống là công cụ hỗ trợ luật sư, không thay luật sư. Một câu
> trả lời "nghe hợp lý" nhưng **không có nguồn** hoặc **dẫn sai điều luật** là KHÔNG ĐẠT.
> Một câu từ chối trung thực ("kho chưa có căn cứ") khi kho thật sự không có tài liệu là ĐẠT.
"""

CAN_CU = """\
| Tài liệu | Nội dung dùng để đối chiếu | Ghi chú |
|---|---|---|
| **Báo giá & Kế hoạch 6 tuần** (`BAO_GIA_HDS_AI_6TUAN.docx`) | HT1–HT4 (nền tảng) + Nhóm 1–3 (mục 1–18) — phần có giá trị hợp đồng 15,6 triệu | Nhóm 4 (mục 19–36) **TẠM HOÃN**, không kiểm thử |
| **Kế hoạch triển khai 10 ngày** (`KE_HOACH_10NGAY.docx`, 24/07/2026) | 16 hạng mục, cột "Kết quả bàn giao" và cam kết bảo mật | Dùng làm chuẩn ở biên bản nghiệm thu 15/09 |
| **Kịch bản test AI** (`Kịch bản test AI.docx`, HDS cung cấp) | 40 tình huống pháp lý + tiêu chí điều luật | Chấm độ chính xác tra cứu luật (sheet *40 KB pháp lý*) |
| **Biên bản / báo cáo nghiệm thu 15/09/2026** | Trạng thái từng hạng mục, cách nghiệm thu đã thống nhất | Ca test ở đây kế thừa cột "Cách nghiệm thu" |
| **Sổ tay nhân viên, Sổ tay IT, API_TICH_HOP, API_KHACH_HANG** (`deploy/`) | Hành vi đã hứa với người dùng | Chỗ sổ tay lệch với hệ thống được liệt kê ở mục 10 |
| **Bảng theo dõi triển khai** (`DIGINIX-HDS_Theo-doi-trien-khai.xlsx`, 18/09) | Trạng thái từng mục theo báo giá | Mục 14, 16, 17, 18 ghi "Chưa bắt đầu"; mục 2 "Tạm hoãn" — **03/10 đã bàn giao mục 2, 14, 17, 18** (xem ma trận mục 3) |
"""

CHUAN_BI = """\
### 4.1 Tài khoản thử — KHÔNG dùng tài khoản thật của nhân viên

Admin tạo ở **Quản trị → Người dùng & Phòng ban → Tạo tài khoản** (để trống mật khẩu →
máy sinh mật khẩu tạm, hiện **đúng một lần** — chép ngay). Đặt tên dễ nhận biết, ví dụ:

| Mã | Email đề xuất | Vai | Phòng ban / khách | Dùng cho |
|---|---|---|---|---|
| TK-AD | `kt.admin@hdslaw.vn` | Quản trị hệ thống (`admin`) | — | Quản trị, tài khoản, cài đặt |
| TK-QT | `kt.banqt@hdslaw.vn` | Ban Quản trị (`ban_qt`) | — | Duyệt, nhật ký, 360° |
| TK-TP | `kt.truongphong@hdslaw.vn` | Trưởng bộ phận (`truong_bph`) | Phòng Doanh nghiệp | Hồ sơ khách theo phòng, duyệt bản nháp |
| TK-CV | `kt.chuyenvien@hdslaw.vn` | Chuyên viên (`chuyen_vien`) | Phòng Doanh nghiệp | Hội thoại, kiểm tra pháp lý, soạn thảo |
| TK-TL | `kt.troly@hdslaw.vn` | Trợ lý (`tro_ly`) | Phòng Doanh nghiệp | Kiểm tra giới hạn quyền |
| TK-KA | `kt.khacha@hdslaw.vn` | Khách (`client_plus`) | **Khách thử A** | Cổng khách hàng |
| TK-KB | `kt.khachb@hdslaw.vn` | Khách (`client_plus`) | **Khách thử B** | Cổng khách hàng, test chéo |

Máy chủ hiện có sẵn 2 tài khoản khách thử từ 15/09 (khách 129 và 114, **đang khoá**) —
có thể mở khoá dùng lại thay cho TK-KA/TK-KB.

### 4.2 Khách thử và tài liệu "chim mồi"

1. Tạo **hai thư mục khách thử** trong ngăn `9. HỒ SƠ KHÁCH HÀNG` (Quản trị → Kho tài
   liệu → Tạo thư mục; tên **bắt buộc có mã**), ví dụ `0998. KHÁCH THỬ NGHIỆM A (xoá được)`
   và `0997. KHÁCH THỬ NGHIỆM B (xoá được)`. Khách `0999` (khách thử API 29/09) dùng được làm A.
2. Tải 4 file `du-lieu-mau/CANARY_*.docx` vào đúng chỗ ghi trong file (Công khai → ngăn
   `1. VĂN BẢN PHÁP LUẬT`; Nội bộ → `6. QUY TRÌNH NỘI BỘ`; Khách A, Khách B → thư mục khách tương ứng).
3. Đợi ≤ 3 phút (lịch quét) hoặc bấm **Quét ngay**; kiểm tra cả 4 đã **Đã học / đã duyệt**.
4. Gắn TK-KA với khách A, TK-KB với khách B (Người dùng & Phòng ban → Sửa → Khách hàng).

Mỗi file chim mồi chứa **một mã duy nhất** (`HDS-CANARY-CONGKHAI-4417`, `…NOIBO-2290`,
`…KHACHA-8812`, `…KHACHB-3307`). Ca kiểm thử phân quyền chỉ cần hỏi đúng mã đó: mã
**xuất hiện** trong câu trả lời / bảng nguồn ⇒ tài khoản đó **đọc được** tài liệu.

### 4.3 Lưu ý vận hành khi kiểm thử

- **Đăng nhập bị giới hạn 10 lượt / 5 phút cho MỖI ĐỊA CHỈ IP — tính cả lượt đúng mật
  khẩu.** Cả nhóm ngồi chung văn phòng (chung IP) đổi tài khoản liên tục sẽ gặp
  *"Đăng nhập sai quá nhiều lần…"* (429). Mỗi vai dùng **một cửa sổ trình duyệt riêng /
  một hồ sơ Chrome riêng** (phiên giữ 12 giờ) thay vì đăng xuất – đăng nhập lại.
- Kênh website giới hạn **30 câu / giờ / IP** — ca test ngưỡng 429 (WEB-05) chạy **cuối
  cùng** hoặc từ mạng khác (4G), nếu không sẽ khoá cả nhóm khỏi kênh website 1 giờ.
- Bot chạy trên GPU nội bộ (qwen3:14b): câu tra cứu thường **10–60 giây**, câu tình
  huống dài có thể tới **~110 giây**. Chỉ ghi lỗi hiệu năng khi vượt ngưỡng ở mục 9.
- Sau mỗi lần nhà phát triển cập nhật hệ thống: bấm **Ctrl+F5** và ghi **dấu build ở
  chân trang** vào cột *Bản build* — "đã sửa mà vẫn lỗi" thường là trình duyệt giữ bản cũ.
- Mọi ca tạo dữ liệu (tài khoản, tài liệu, bản nháp, hội thoại) đều **ghi vào hệ thống
  thật**. Đặt tên có chữ **"KIỂM THỬ"** để dọn sau (mục 4.4).

### 4.4 Dọn dẹp sau kiểm thử

Khoá (không xoá) các tài khoản TK-*; gỡ 4 tài liệu chim mồi và tài liệu tải lên trong ca
KHO-* (Kho tài liệu → Gỡ); xoá bản nháp / hội thoại có chữ "KIỂM THỬ"; thu hồi khoá API
cấp trong ca API-*. Nhật ký hệ thống **không xoá được** — đó là đúng thiết kế.
"""

GHI_KET_QUA = """\
| Cột trong sổ Excel | Cách điền |
|---|---|
| **Kết quả** | `ĐẠT` · `KHÔNG ĐẠT` · `CHẶN` (không chạy được vì ca trước lỗi / thiếu điều kiện) · `BỎ QUA` (ngoài phạm vi, ghi lý do) |
| **Thực tế quan sát** | Ghi ngắn cái thấy được — đặc biệt khi KHÔNG ĐẠT: nhãn/thông báo nguyên văn, con số |
| **Bằng chứng** | Tên ảnh chụp màn hình (`<Mã ca>_<ngày>.png`) hoặc file tải về |
| **Mã lỗi** | Nếu KHÔNG ĐẠT: mã dòng ở sheet *Báo lỗi* (BUG-001…) |
| **Người test / Ngày / Bản build** | Bản build = dấu ở chân trang web |

**Mức độ lỗi** (ghi ở sheet *Báo lỗi*):

| Mức | Khi nào | Ví dụ |
|---|---|---|
| **Nghiêm trọng** | Lộ dữ liệu, sai quyền, mất dữ liệu, sai luật có thể gây hại khi dùng thật | Khách A thấy mã chim mồi của khách B; bot khẳng định trần phạt 12% là hợp lệ |
| **Cao** | Chức năng hợp đồng không dùng được / ra kết quả sai | Rà soát rủi ro không bắt lãi 36%/năm; xuất Word lỗi |
| **Trung bình** | Chạy được nhưng sai một phần, có cách vòng | Thiếu một điều luật trong câu trả lời; nhãn hiển thị sai |
| **Thấp** | Giao diện, chính tả, sổ tay lệch | Nút lệch, chữ sai dấu |

**Mẫu báo lỗi** (1 lỗi = 1 dòng): Mã ca · Tài khoản · Bước tái hiện (gửi gì) · Mong đợi · Thực tế (nguyên văn) · Ảnh · Mức độ · Bản build.
"""

TIEU_CHI_NGHIEM_THU = """\
Đề xuất tiêu chí (HDS chốt trước khi chạy):

1. **100%** ca loại *Bảo mật / Phân quyền* ĐẠT — một ca không đạt là **chưa nghiệm thu**.
2. **≥ 95%** ca mức ưu tiên *Cao* ĐẠT; không còn lỗi mức *Nghiêm trọng* / *Cao* đang mở.
3. **40 kịch bản pháp lý**: HDS chốt chuẩn chấm theo bản luật nào (2020 hay bản sửa đổi
   2025 đang có trong kho — lý do lệch ở biên bản 15/09) và ngưỡng đạt, ví dụ ≥ 60% ĐÚNG
   hoặc MỘT PHẦN, 0 câu SAI bản chất.
4. Mục 2 (gợi ý lý do), 14 (dự báo tranh tụng), 17 (dịch & bản địa hoá), 18 (chuẩn bị
   phiên toà) **đã bàn giao 03/10** và chấm như ca thường (CHUA-01, 03, 06, 07). Riêng mục 4
   (nguồn thu thập web — chờ HDS chốt danh sách nguồn) ghi *BỎ QUA* và **không tính** vào tỉ lệ
   đạt; mục 14 thể hiện dự báo bằng 3 mức định tính thay cho "% thắng" — HDS xác nhận ở biên bản.
"""
