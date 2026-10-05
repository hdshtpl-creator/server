# Bộ chạy kiểm thử TỰ ĐỘNG trên máy chủ (02/10, cập nhật 03/10/2026)

Chạy toàn bộ ca API (TK, PQ, CH, KT, RR, ST, BM, KHO, DN, TH, WEB, KH, API, QT, HT, PNF, CHUA, MOI1, MOI3)
và 40 kịch bản HDS **trên máy chủ thật**, gọi thẳng `127.0.0.1:8000`. Kết quả từng lượt:

| Thư mục | Lượt | Ca chức năng | 40 KB (máy chấm, 30 câu có số Điều) |
|---|---|---|---|
| `ket_qua_0210/` | 02/10 trước đợt sửa | 148 ca: 114 ĐẠT · 18 KHÔNG ĐẠT · 16 BỎ QUA | 8 ĐÚNG · 13 MỘT PHẦN · 9 SAI |
| `ket_qua_0310/` | 03/10 sau đợt sửa | 154 ca: 143 ĐẠT · 1 KHÔNG ĐẠT · 10 BỎ QUA | 14 ĐÚNG · 9 MỘT PHẦN · 7 SAI |

## Chuẩn bị trên máy chủ (user pc)
```bash
mkdir -p /tmp/kt/in && chmod 700 /tmp/kt
cp deploy/kiem-thu/nguon/tu_dong/*.py deploy/kiem-thu/nguon/kb_cases.py deploy/kiem-thu/nguon/kb40.json /tmp/kt/
cp deploy/kiem-thu/du-lieu-mau/*.docx deploy/kiem-thu/du-lieu-mau/*.txt deploy/kiem-thu/nguon/tu_dong/in_them/* /tmp/kt/in/
```
`kt_lib.mint()` ký JWT bằng `app.auth.make_token` ngay trên máy chủ (đọc JWT_SECRET từ `.env`, không in ra) —
vì vậy phải chạy từ thư mục `hds-ai` bằng `.venv` của backend.

## Chạy
Chạy NỀN qua một script, tách khỏi phiên SSH (`nohup setsid`), để đứt SSH không giết lượt chạy:
```bash
cat > /tmp/kt/chay.sh <<'EOS'
#!/usr/bin/env bash
cd ~/hds-ai-full/hds-ai
rm -f /tmp/kt/ket_qua.json /tmp/kt/kb40_ket_qua.json; : > /tmp/kt/run.log
KT_DIR=/tmp/kt exec .venv/bin/python /tmp/kt/kt_run.py all     # ~1 giờ 45 ca + ~55 phút 40 KB
EOS
chmod +x /tmp/kt/chay.sh && nohup setsid /tmp/kt/chay.sh > /tmp/kt/nohup.out 2>&1 < /dev/null &
tail -f /tmp/kt/run.log
```
Chạy lại chọn lọc: `KT_DIR=/tmp/kt KT_CHI=CH-01,RR-03 .venv/bin/python /tmp/kt/kt_run.py CH RR`.
Dọn: `KT_DIR=/tmp/kt .venv/bin/python /tmp/kt/kt_run.py cleanup` (xoá hội thoại/nháp/lead → gỡ tài liệu thử → KHOÁ tài khoản ở cuối).
Rồi về máy phát triển:
`python deploy/kiem-thu/nguon/dien_ket_qua.py <thư mục json lượt này> deploy/kiem-thu <ngày> <build> [<thư mục json lượt trước>]`
(tham số cuối sinh mục *So với lượt chạy trước*).

## Lưu ý (bẫy đã gặp)
- **Không khởi động lại backend khi bộ chạy đang chạy**: mọi ca phía sau nhận `Connection refused` (03/10 02:51
  làm hỏng cả lượt). `kt_run.py` nay bọc từng nhóm để một nhóm hỏng không dừng cả lượt, nhưng kết quả nhóm đó vẫn hỏng.
- Tài khoản thử còn cờ mật khẩu tạm bị máy chủ chặn (F-04) → `setup` tự đặt lại + đổi mật khẩu (`doi_mk_lan_dau`).
- TL2/TL3 (TK-05…TK-09) mang dấu lượt chạy (`kt.troly2.<ddHHMM>`) và IP của TK-04 đổi theo lượt — van đăng nhập giữ IP 5 phút.
- Tệp thử của DN-01/DN-02 mang dấu lượt chạy: tải lại đúng tệp đã duyệt ở lượt trước thì kho trả "nội dung không đổi".
- Dừng bộ chạy: `for p in $(pgrep -f "^.venv/bin/python /tmp/kt/kt_run"); do kill $p; done` — ĐỪNG `pkill -f "kt_run.py all"`
  qua SSH (giết luôn chính lệnh SSH chứa chuỗi đó).
- Mỗi "người dùng ảo" gửi `X-Forwarded-For` riêng vì van đăng nhập / công khai đếm theo IP (cổng 8000 chỉ bind localhost).
- Khách thử A = `0999` (có sẵn), B = `0998` (thư mục tạo khi setup, để lại sau cleanup). Tài khoản thử `kt.*@hdslaw.vn` chỉ bị khoá, không xoá.
- Chấm 40 kịch bản chỉ sơ bộ theo số Điều; luật sư chấm lại ở sheet *Trả lời 40 KB (toàn văn)*.
