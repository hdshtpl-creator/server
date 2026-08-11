# Dạy bot học tài liệu — qua Google Drive

Bot học bằng cách: **đọc file → chia đoạn → tạo vector** rồi lưu vào CSDL. Khi có người
hỏi, nó tìm các đoạn liên quan nhất và trả lời kèm trích dẫn (RAG). "Train" ở đây =
đưa đúng tài liệu vào kho, gán đúng **loại / mức bảo mật / khách hàng**.

Có 3 cách đưa tài liệu vào. Cách 1 là thứ bạn hỏi — **tự học mỗi file mới theo thư mục**.

---

## Cách 1 — Tự học từ Google Drive theo CẤU TRÚC THƯ MỤC (khuyến nghị)

Thả file vào đúng thư mục trên Drive → bot tự tải về, tự gán nhãn theo thư mục, tự học.
Không cần vào web bấm gì. Đây là `app/auto_learn.py`.

### 1a. Cấu trúc thư mục quy ước

Tạo một thư mục gốc trên Drive (vd `HDS-AI`), bên trong đặt **đúng tên** các thư mục sau
(tên thư mục chính là nhãn — bỏ dấu, viết thường, nối bằng gạch ngang):

```
HDS-AI/
├── luat/              → Văn bản luật            (công khai — ai cũng tra được)
├── ban-an/            → Bản án                  (nội bộ)
├── an-le/             → Án lệ                   (nội bộ)
├── mau-hop-dong/      → Mẫu hợp đồng            (nội bộ)
├── hop-dong/          → Hợp đồng                (nội bộ)
├── thu-tu-van/        → Thư tư vấn / ý kiến PL   (nội bộ)
├── quy-trinh/         → Quy trình               (nội bộ)
├── thu-mau/           → Thư mẫu                 (nội bộ)
├── nhan-hieu/         → Dữ liệu nhãn hiệu       (nội bộ)
├── noi-bo/            → Tài liệu nội bộ khác    (nội bộ)
└── khach-hang/
    ├── SUNGROUP/      → Hồ sơ khách (chỉ Ban QT + phòng của khách xem được)
    │   ├── hop-dong/      (không bắt buộc — chia nhỏ loại giấy tờ trong hồ sơ khách)
    │   └── thu-tu-van/
    └── VINAPHARMA/
        └── ...
```

**Quy tắc quan trọng về `khach-hang/`:**
- Tên thư mục con phải **trùng mã khách** (`code` trong hệ thống, vd `SUNGROUP`). Tạo khách
  trước trong web (tab *Người dùng & Phòng ban* / dữ liệu khách) rồi mới thả file.
- Đặt sai mã (khách chưa tồn tại) → **bot BỎ QUA file đó** và báo lý do, để tránh lộ dữ liệu
  của khách này sang khách khác. An toàn là ưu tiên số một.
- File nằm ở thư mục gốc hoặc thư mục lạ (không đúng quy ước) → cũng bỏ qua kèm cảnh báo.

Định dạng nhận: `.pdf .docx .txt .md` và Google Docs/Sheets (tự xuất ra .docx/.xlsx).
PDF scan sẽ được OCR tiếng Việt tự động.

### 1b. Cho bot quyền đọc thư mục Drive (làm một lần)

Bot đọc Drive bằng **service account** (một "tài khoản máy", không phải tài khoản Gmail của bạn):

1. Vào <https://console.cloud.google.com> → tạo project (vd `hds-ai`).
2. **APIs & Services → Library** → tìm **Google Drive API** → **Enable**.
3. **APIs & Services → Credentials → Create credentials → Service account** → đặt tên → Done.
4. Bấm vào service account vừa tạo → tab **Keys → Add key → Create new key → JSON** → tải file JSON về.
5. Chép file JSON đó lên server vào `hds-ai/credentials/service-account.json`:
   ```bash
   # từ máy của bạn:
   scp service-account.json pc@<server>:~/hds-ai-full/hds-ai/credentials/
   ```
6. Mở file JSON, copy dòng `"client_email"` (dạng `...@...iam.gserviceaccount.com`).
   Trên Google Drive, **chia sẻ thư mục gốc `HDS-AI`** cho email đó, quyền **Viewer**.
7. Lấy **ID thư mục gốc**: mở thư mục trên Drive, ID nằm ở cuối URL
   `https://drive.google.com/drive/folders/`**`<ID>`**. Ghi vào `hds-ai/.env`:
   ```
   DRIVE_FOLDER_ID=<ID>
   DRIVE_SA_FILE=credentials/service-account.json
   ```

### 1c. Chạy thử rồi bật tự động

Trên server:

```bash
cd ~/hds-ai-full
bash deploy/auto-learn.sh --dry-run      # xem nó SẼ học file nào, nhãn gì (chưa ghi)
bash deploy/auto-learn.sh                # học thật một lần
```

Ổn rồi thì bật lịch tự chạy **mỗi 15 phút** (từ đó chỉ cần thả file vào Drive):

```bash
sudo bash deploy/auto-learn.sh --install-timer
```

Kiểm tra:
```bash
systemctl list-timers hds-ai-learn.timer          # lần chạy kế tiếp
journalctl -u hds-ai-learn.service -n 40 --no-pager   # kết quả lần chạy gần nhất
```

Bot chỉ xử lý **file mới hoặc file đã sửa** (so bằng checksum) nên chạy lại rất nhanh.
Sửa nội dung một file trên Drive → lần chạy sau bot tự cập nhật lại (xoá bản cũ, học bản mới).

> **Mặc định bot tự duyệt luôn** (thư mục chính là nhãn nên tin được). Muốn cẩn trọng hơn
> — mọi file vào hàng chờ để người duyệt tay trước khi thành tri thức — đặt trong `.env`:
> `AUTO_LEARN_REVIEW=1` rồi vào web tab *Duyệt nhãn tài liệu*.

---

## Cách 2 — Chép file thẳng lên server (không qua Drive)

```bash
cd ~/hds-ai-full/hds-ai && source .venv/bin/activate
# chép file vào data/raw/ rồi:
python -m app.ingest data/raw law        # hoặc: contract / advisory / other ...
```
Cách này nạp tất cả là `internal` + tự duyệt; muốn phân loại kỹ dùng Cách 1 hoặc Cách 3.

## Cách 3 — Tải trong lúc chat + duyệt tay

Ngay trong giao diện chat: nút **Tải tài liệu** → chọn *Lưu vào kho* → file vào hàng chờ
→ vào tab *Duyệt nhãn tài liệu* gán loại/mức/khách rồi Duyệt. Hợp khi thêm lẻ vài file.

---

## Dạy bot "cách phân tích" (khác với dạy tài liệu)

Ngoài tài liệu, bạn dạy được **quy trình xử lý** từng loại vụ việc: web → tab *Mẫu phương
pháp* → thêm các bước. Khi hỏi, bật "Mẫu phương pháp" để bot phân tích theo đúng quy trình đó.

## Dạy "hồ sơ khách 360°"

Web → tab *Hồ sơ khách 360°* → chọn khách → điền lịch sử / vấn đề / cảnh báo thời hiệu /
gợi ý chiến lược → Lưu. Bot dùng phần này khi tư vấn liên quan đến khách đó.

---

## Kiểm tra bot đã học chưa

- Web → *Kho tài liệu đã học*: thấy file mới, số đoạn, loại, mức truy cập.
- Vào chat hỏi một câu liên quan nội dung file vừa thả → câu trả lời phải kèm **nguồn trích dẫn**
  chính file đó.
- Trên server, sức khoẻ tổng thể: `cd ~/hds-ai-full/hds-ai && .venv/bin/python -m app.classify --report`
