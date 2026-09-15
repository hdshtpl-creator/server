# SỔ TAY IT — VẬN HÀNH HỆ THỐNG AI HDS

Dành cho người cài đặt, vận hành và bảo trì máy chủ. Sổ tay người dùng cuối:
[HUONG_DAN_NHAN_VIEN.md](HUONG_DAN_NHAN_VIEN.md).

Mọi lệnh trong tài liệu này chạy trên **máy chủ Ubuntu**, từ **thư mục gốc của repo**
(nơi chứa `deploy/`, `hds-ai/`, `hds-ai-assistant/`), trừ khi ghi khác.

---

## MỤC LỤC

1. [Kiến trúc — cái gì chạy ở đâu](#1-kiến-trúc--cái-gì-chạy-ở-đâu)
2. [Cấu trúc thư mục và dữ liệu nằm đâu](#2-cấu-trúc-thư-mục-và-dữ-liệu-nằm-đâu)
3. [Cài đặt lần đầu](#3-cài-đặt-lần-đầu)
4. [Kho tài liệu trên máy chủ](#4-kho-tài-liệu-trên-máy-chủ)
5. [Tên miền và HTTPS](#5-tên-miền-và-https)
6. [Cập nhật phiên bản mới](#6-cập-nhật-phiên-bản-mới)
7. [Sao lưu và phục hồi](#7-sao-lưu-và-phục-hồi)
8. [Quản lý người dùng và phân quyền](#8-quản-lý-người-dùng-và-phân-quyền)
9. [Cài đặt AI — bảng tham số](#9-cài-đặt-ai--bảng-tham-số)
10. [Bộ công cụ chẩn đoán](#10-bộ-công-cụ-chẩn-đoán)
11. [Triệu chứng → lệnh xử lý](#11-triệu-chứng--lệnh-xử-lý)
12. [Việc định kỳ](#12-việc-định-kỳ)
13. [Cấm kỵ — làm là mất dữ liệu](#13-cấm-kỵ--làm-là-mất-dữ-liệu)
14. [Phụ lục](#14-phụ-lục)

---

## 1. KIẾN TRÚC — CÁI GÌ CHẠY Ở ĐÂU

```
Trình duyệt ──HTTPS──▶ nginx ──▶ /            → giao diện React tĩnh (hds-ai-assistant/dist)
     (80/443)                  └▶ /api/*      → FastAPI  127.0.0.1:8000  (systemd: hds-ai-backend)
                                                   ├─▶ PostgreSQL 16 + pgvector  (Docker: hds-postgres, cổng 5432)
                                                   └─▶ Ollama                    (127.0.0.1:11434)
                                                          ├─ qwen3:14b  — sinh câu trả lời
                                                          └─ bge-m3     — tạo vector 1024 chiều

Kho tài liệu ──15 phút/lần──▶ app.local_learn (systemd timer) ──▶ PostgreSQL
(thư mục trên máy chủ, chia sẻ cho nhân viên qua ổ mạng Samba)
```

Bốn tiến trình cần nhớ:

| Thành phần | Tên | Kiểm tra |
|---|---|---|
| Backend | `hds-ai-backend.service` | `systemctl status hds-ai-backend` |
| CSDL | container `hds-postgres` | `docker ps \| grep hds-postgres` |
| Model AI | `ollama` | `curl -s http://localhost:11434/api/tags` |
| Web server | `nginx` | `nginx -t && systemctl status nginx` |

Timer **tuỳ chọn**, không tự cài: `hds-ai-quet-kho.timer` — quét kho tài liệu mỗi 15 phút (`sudo bash deploy/hoc-tu-thu-muc.sh --install-timer`). Không có root thì `bash deploy/hoc-tu-thu-muc.sh --install-cron` (crontab của user, cùng chu kỳ). Xem mục 4 và 12.

**Backend chỉ lắng nghe 127.0.0.1:8000** — mọi thứ đi vào phải qua nginx `/api/`.

### Luồng trả lời một câu hỏi

1. Nhận câu hỏi → đọc lịch sử hội thoại: 10 lượt gần nhất **nguyên văn** + bản **tóm tắt phần cũ hơn** (cột `summary` trên `conversations`, LLM tự cập nhật ở luồng nền sau mỗi câu trả lời khi hội thoại đủ dài).
2. Câu đếm/danh sách xác định (bao nhiêu nhân sự, khách nào có mấy vụ) → **trả lời thẳng bằng SQL**, không gọi model.
3. Còn lại: tạo vector câu hỏi bằng `bge-m3` → **tìm lai ghép** (vector + từ khoá) trong bảng `chunks`.
4. **Row-Level Security của PostgreSQL lọc quyền** — câu SQL không hề có điều kiện phân quyền, chính CSDL từ chối trả về dòng người hỏi không được xem.
5. Dựng prompt (tài liệu + dữ liệu công ty + lịch sử) → gọi Ollama.
6. **Bot đọc lại** câu trả lời của chính nó (khi quá dài / bỏ lửng / lặp).
7. **Kiểm chứng nguồn**: câu nào không đối chiếu được với tài liệu thì bị cắt; không câu nào có căn cứ thì từ chối trả lời.
8. Lưu hội thoại + nguồn + nhật ký.

---

## 2. CẤU TRÚC THƯ MỤC VÀ DỮ LIỆU NẰM ĐÂU

> **Máy chủ HDS hiện tại đặt repo ở `/home/pc/hds-ai-full`** (user `pc`). Các ví
> dụ trong sổ tay viết `/opt/hds-ai-full` theo quy ước cài mới — đổi đường dẫn
> cho khớp trước khi chạy, nhất là ở mục 6 (cập nhật) và mục 7 (sao lưu).

```
hds-ai-full/                          ← repo, đặt ở /home/<user>/ hoặc /opt/  (KHÔNG đặt trong /root/)
├── deploy/                           ← toàn bộ script vận hành + tài liệu này
│   ├── setup.sh          cài lần đầu
│   ├── update.sh         cập nhật sau git pull
│   ├── go-public.sh      mở ra Internet + HTTPS
│   ├── hoc-tu-thu-muc.sh    quét kho trên máy chủ / cài timer 15 phút
│   ├── theo-doi-nguon-web.sh theo dõi nguồn văn bản trên mạng / timer 6 giờ
│   ├── auto-learn.sh        (cũ) học từ Google Drive — giữ để còn đường lùi
│   ├── luu-tru-drive.sh     (cũ) kéo toàn bộ Drive về, dùng lúc chuyển đổi
│   ├── kiem-tra-toc-do.sh   chẩn đoán tốc độ
│   ├── kiem-tra-vector.sh   chẩn đoán kho vector
│   ├── soi-ho-so.sh         soi một bộ hồ sơ nhân sự
│   ├── hoc-lai-file.sh      đọc lại vài tài liệu   (XOÁ rồi học lại)
│   ├── hoc-lai-tu-dau.sh    đọc lại toàn kho       (XOÁ SẠCH rồi học lại)
│   ├── deploy.env        DOMAIN + LETSENCRYPT_EMAIL   (gitignore, tự tạo)
│   └── *.md              CAU_TRUC_DRIVE, LUU_TRU_DU_LIEU, TRAIN_DRIVE, API_KHACH_HANG, NHAP_NHAN_SU
├── hds-ai/                           ← backend Python
│   ├── .env              ★ TOÀN BỘ BÍ MẬT: mật khẩu CSDL, JWT, đường dẫn kho, model  (gitignore)
│   ├── .venv/            môi trường Python
│   ├── app/              mã nguồn (api.py, rag.py, auto_learn.py, ingest.py…)
│   ├── sql/schema.sql    lược đồ CSDL — chạy lại được nhiều lần
│   ├── credentials/      ★ service-account.json của Google  (gitignore)
│   ├── tests/            bộ kiểm thử — cổng chặn của update.sh
│   └── data/
│       ├── raw/          ★ KHO TÀI LIỆU (DATA_LIB) — bản gốc DUY NHẤT
│       │   ├── 1. VĂN BẢN PHÁP LUẬT/ …    ← cây thư mục nhân viên thả file
│       │   └── uploads/<loại>/<YYYY-MM>/  ← file tải lên qua web (bộ quét bỏ qua)
│       └── work/         hàng tạm, xoá cả thư mục cũng không sao
│           ├── preview/        PDF xem trước của file Office
│           ├── template_fills/ file AI tạo từ chat (tự dọn sau 24h)
│           └── chat_uploads/   bản .docx gốc của file đính kèm chat
├── hds-ai-assistant/                 ← giao diện React
│   ├── dist/             ★ nginx phục vụ thư mục này
│   └── .env.production   VITE_API_BASE_URL=/api  (đường dẫn tương đối — đừng sửa)
└── (tuỳ chọn) kho đặt ở ổ khác — khai DATA_LIB, xem CHUYEN_VE_LOCAL.md mục 7
```

**Dữ liệu quan trọng nằm ngoài repo:** Docker volume `hds-ai_pgdata` (gắn vào `/var/lib/postgresql/data` trong container). **Đây là thứ duy nhất không tạo lại được.**

| Nơi lưu | Chứa gì | Mất thì sao | Sao lưu |
|---|---|---|---|
| Volume `pgdata` | Vector, nhãn, hội thoại, người dùng, phân quyền, cài đặt | **Mất toàn bộ tri thức** | **BẮT BUỘC** |
| `hds-ai/data/raw/` (kho) | **Bản gốc DUY NHẤT** của tài liệu công ty | Mất bản gốc; bot vẫn trả lời bằng nội dung đã học | **BẮT BUỘC** — rsync hằng đêm ra ổ ngoài |
| `hds-ai/.env` | Bí mật kết nối (mật khẩu CSDL, JWT_SECRET) | Phải cài lại từ đầu | **BẮT BUỘC** (chép tay, để nơi an toàn) |
| `credentials/service-account.json` | Khoá Google — **chỉ còn dùng khi muốn quay lại Drive** | Không mất gì nếu đã bỏ Drive | Giữ tới khi chắc chắn không quay lại |
| `hds-ai/data/work/` | Hàng tạm | Không mất gì | Không |
| Model Ollama | qwen3:14b, bge-m3 | Tải lại được | Không |

> ⚠ Từ khi bỏ Drive, **thư mục kho là bản gốc duy nhất** — không còn Google giữ hộ. Sao lưu nó là bắt buộc (mục 7).

---

## 3. CÀI ĐẶT LẦN ĐẦU

### 3.1 Yêu cầu

- **Ubuntu 22.04 hoặc 24.04**, có `sudo`. (Script dùng `apt-get`, `systemd`, layout nginx kiểu Debian — không chạy trên RHEL/Alpine.)
- **RAM ≥ 24 GB** nếu chạy Ollama cùng máy với `qwen3:14b` + `bge-m3`. Máy 16 GB thì đổi sang `qwen3:8b`.
- Ổ cứng: tính OS ~30 GB + model ~20 GB + tài liệu + chỉ mục. Ổ 512 GB sẽ chật khi thêm kho lưu trữ — chuẩn bị ổ thứ hai.
- Repo đặt ở `/home/<user>/` hoặc `/opt/`. **Đặt trong `/root/` là nginx đọc không được → trang trắng / lỗi 403.**
- Mở cổng 80/443 ra Internet nếu dùng tên miền + HTTPS.

Script tự cài giúp: Docker, Node.js 20, nginx, certbot, thư viện Python, **tesseract-ocr + gói tiếng Việt, poppler-utils, libreoffice-writer** (thiếu ba cái cuối thì bản scan và file `.doc` bị bỏ qua âm thầm).

Script **không** cài: Ollama và model, tường lửa, lịch sao lưu, chia sẻ ổ mạng Samba.

### 3.2 Chạy cài đặt

```bash
# 1. Lấy mã nguồn về /opt (hoặc /home/<user>)
cd /opt && sudo git clone <URL repo> hds-ai-full && cd hds-ai-full

# 2. Khai báo tên miền trước (bỏ qua nếu chỉ dùng LAN)
cp deploy/deploy.env.example deploy/deploy.env
nano deploy/deploy.env      # DOMAIN=app.hdslaw.vn   LETSENCRYPT_EMAIL=it@hdslaw.vn

# 3. Cài
sudo bash deploy/setup.sh
```

Không tạo `deploy.env` thì script hỏi trực tiếp hai câu: *"Tên miền đã trỏ về máy chủ này"* và *"Email cho chứng chỉ HTTPS"*. **Để trống tên miền = chạy HTTP bằng IP trong mạng nội bộ.**

Script làm tuần tự: cài gói hệ thống → sinh `hds-ai/.env` với mật khẩu ngẫu nhiên → dựng container Postgres → nạp `schema.sql` → tạo 4 phòng ban + ma trận quyền + 5 tài khoản mẫu → cài thư viện Python → tạo `hds-ai-backend.service` → build giao diện → viết cấu hình nginx → xin chứng chỉ HTTPS.

### 3.3 Cài Ollama và model (thủ công, bắt buộc)

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen3:14b     # model trả lời  (máy 16GB: qwen3:8b)
ollama pull bge-m3        # model tạo vector — KHÔNG BAO GIỜ đổi model này
```

Đổi model trả lời sau này: **Quản trị → Cài đặt AI → Model sinh câu trả lời** (không cần sửa file).
**Đổi `bge-m3` là hỏng toàn bộ tra cứu** — mọi đoạn đã lưu đều tạo vector bằng model đó; muốn đổi phải học lại từ đầu.

### 3.4 Sau khi cài xong

```bash
systemctl status hds-ai-backend           # phải là active (running)
curl -s http://localhost:11434/api/tags   # phải liệt kê qwen3 và bge-m3
```

Mở web bằng địa chỉ script in ra, đăng nhập `admin@hdslaw.vn` / `admin123` → **đổi mật khẩu ngay**.

Tài khoản mẫu tạo sẵn (đổi hoặc xoá trước khi dùng thật):

| Email | Mật khẩu | Vai |
|---|---|---|
| admin@hdslaw.vn | admin123 | admin |
| giamdoc@hdslaw.vn | demo123 | ban_qt |
| truong.dndt@hdslaw.vn | demo123 | truong_bph (Doanh nghiệp - Đầu tư) |
| cv.tranhtung@hdslaw.vn | demo123 | chuyen_vien (Tranh tụng) |
| troly@hdslaw.vn | demo123 | tro_ly (Hỗ trợ pháp lý) |

> ⚠ **Chạy lại `setup.sh` trên máy đang hoạt động sẽ đặt lại mật khẩu 5 tài khoản này về mặc định** và xoá ma trận `access_rules` rồi seed lại (mất chỉnh tay). Mật khẩu CSDL thì được giữ nguyên.

---

## 4. KHO TÀI LIỆU TRÊN MÁY CHỦ

Từ 27/08/2026 hệ thống **không dùng Google Drive**. Kho tài liệu là một thư mục
trên máy chủ, chia sẻ cho nhân viên qua ổ mạng. Đang chuyển đổi từ Drive sang:
làm theo [CHUYEN_VE_LOCAL.md](CHUYEN_VE_LOCAL.md), **đúng thứ tự trong đó**.

### 4.1 Thư mục kho

Khai trong `hds-ai/.env`:

```bash
DATA_LIB=./data/raw              # bỏ trống = dùng DATA_RAW (mặc định)
AUTO_LEARN_AUTO_APPROVE=0        # 0 = mọi tài liệu chờ người duyệt (khuyến nghị)
# DRIVE_FOLDER_ID=               # để TRỐNG — còn giá trị là hệ thống quay về chế độ Drive
```

Cây thư mục bên trong kho: xem [CAU_TRUC_DRIVE.md](CAU_TRUC_DRIVE.md) (tài liệu
vẫn giữ tên cũ; cấu trúc không đổi khi bỏ Drive). Sửa bản đồ thư mục → nhãn ở
**Quản trị → Cài đặt AI → Bản đồ thư mục kho → nhãn tài liệu** (JSON, hiệu lực ngay).

Thư mục `uploads/` bên trong kho là nơi API cất file tải lên qua web — **bộ quét
bỏ qua nó**; đừng để nhân viên thả tài liệu vào đó.

### 4.2 Chia sẻ kho cho nhân viên (Samba)

Không có bước này thì nhân viên không còn đường đưa tài liệu vào hệ thống. Cấu
hình đầy đủ ở [CHUYEN_VE_LOCAL.md](CHUYEN_VE_LOCAL.md) mục 2 — tóm tắt:

```bash
sudo apt-get install -y samba
# thêm khối [KhoTaiLieu] trỏ vào thư mục kho, bật vfs recycle (thùng rác)
sudo smbpasswd -a ten.nhanvien
sudo systemctl restart smbd
```

Nhân viên nối ổ trên Windows: `\\<IP máy chủ>\KhoTaiLieu`.

### 4.3 Chạy bộ quét và bật lịch

```bash
cd hds-ai && .venv/bin/python -m app.local_learn --dry-run   # chỉ liệt kê
cd .. && bash deploy/hoc-tu-thu-muc.sh                       # quét và học một lần
sudo bash deploy/hoc-tu-thu-muc.sh --install-timer           # lịch 15 phút/lần (systemd)
systemctl list-timers hds-ai-quet-kho.timer
journalctl -u hds-ai-quet-kho.service -n 40 --no-pager
# Không có root: crontab của user, cùng chu kỳ, tự khoá chống chạy chồng
bash deploy/hoc-tu-thu-muc.sh --install-cron
tail -n 40 hds-ai/data/quet_kho.log        # lượt gần nhất
tail hds-ai/data/quet_kho_lich_su.log      # một dòng mỗi lượt
```

Bộ quét **tự dừng** trong ba tình huống nguy hiểm, đọc kỹ thông báo:

| Thông báo | Nghĩa | Xử lý |
|---|---|---|
| `[DỪNG] N tài liệu vẫn mang danh tính Drive` | Chưa chạy bước chuyển đổi | `.venv/bin/python -m app.local_learn --chuyen-doi` |
| `[DỪNG] Kho chỉ thấy N tệp trong khi đã học M` | Ổ chưa mount / mất quyền đọc | `mount \| grep <đường dẫn>` |
| `[DỪNG] .env vẫn còn DRIVE_FOLDER_ID` | Bộ quét Drive có thể chạy xen | Gỡ timer Drive + xoá dòng đó |

### 4.4 Ba đường tài liệu vào hệ thống

| Đường | Thao tác | Duyệt |
|---|---|---|
| **Ổ mạng (kho)** | Thả file vào đúng thư mục, chờ ≤15 phút | Chờ duyệt nhãn (PDF **luôn luôn** phải duyệt) |
| **Trang Tổng quan → Kho tài liệu** | Chọn thư mục → *Tải lên vào đây* (học ngay, không đợi quét) | Chờ duyệt, trừ khi người có quyền tick "Duyệt luôn" (xem 4.8) |
| **Tải lên web** | Chat → Tải tài liệu → *Lưu vào kho* | Chờ duyệt, trừ khi người có quyền tick "Duyệt luôn" |
| **Từ hội thoại** | Người dùng 👎 → admin sửa → *Đạt — nạp học* | Chính admin là bước duyệt |

Đường thứ tư dành cho IT, **bỏ qua mọi bước duyệt** — chỉ dùng cho tài liệu nội
bộ chắc chắn an toàn, tuyệt đối không dùng cho hồ sơ khách:

```bash
cd hds-ai && .venv/bin/python -m app.ingest data/raw law
```

### 4.5 Điều bộ quét làm và KHÔNG làm

- **Đổi tên / chuyển thư mục** một file: nhận ra bằng md5 nội dung, gắn lại nhãn
  theo thư mục mới — **không** tạo bản ghi trùng.
- **Xoá file khỏi kho**: chỉ **báo**, không tự gỡ khỏi kho tri thức. Bot vẫn trả
  lời bằng nội dung đã học. Muốn gỡ hẳn: `UPDATE documents SET active=false WHERE id=…`.
- **Sửa nội dung file**: học lại. Nếu bản mới rơi lại hàng chờ duyệt (PDF luôn
  vậy, hoặc trích xuất có cảnh báo) thì in `[GỠ KHỎI KHO]` và hiện cảnh báo cam
  trên thẻ trạng thái — **đó là lúc bot mất một tài liệu đang phục vụ**.

### 4.5b Danh tính + quan hệ văn bản luật (31/08/2026)

Từ bản này, mỗi văn bản luật vào kho được bóc **số hiệu, loại, trích yếu, ngày
ban hành, ngày hiệu lực** và **quan hệ** với văn bản khác (thay thế / sửa đổi,
bổ sung / hướng dẫn / căn cứ) — tự động lúc học, người duyệt soát và sửa được
ngay trên form duyệt nhãn. Văn bản trong kho bị một văn bản khác (cũng trong
kho) thay thế thì tự mang trạng thái **hết hiệu lực**: bot phạt điểm khi tra
cứu, kéo bản thay thế vào nguồn và dán cảnh báo đỏ — **không** ẩn bản cũ.

**Sau lần deploy đầu tiên có tính năng này, chạy backfill MỘT LẦN** để kho cũ
(file không đổi nội dung nên bộ quét bỏ qua) cũng có metadata:

```bash
cd hds-ai
.venv/bin/python -m app.backfill_van_ban --dry-run   # xem trước, không ghi
.venv/bin/python -m app.backfill_van_ban             # điền metadata + quan hệ
# Tùy chọn, tốn thời gian embed (chạy đêm): cắt lại đoạn cho văn bản luật cũ
# để từng vector cũng mang trích dẫn đầy đủ + đoạn "Phần mở đầu":
.venv/bin/python -m app.backfill_van_ban --lam-lai-doan
```

Backfill **không** đụng trạng thái duyệt (tuyệt đối không "học lại cả kho" để
điền metadata — PDF sẽ rơi hết về hàng chờ duyệt, bot mất cả kho luật đang
phục vụ). Máy chỉ tự đánh dấu chiều xấu đi (hết hiệu lực / đã sửa đổi);
"còn hiệu lực" là xác nhận tay của người duyệt trong nút **Chi tiết** ở
Kho tri thức, và giá trị người đặt tay không bị máy ghi đè.

**Bài học 06/09/2026 — backfill chưa từng được chạy.** Kiểm kho thấy 65/65 văn
bản luật `so_hieu = NULL`, bảng quan hệ trống, đoạn vẫn khuôn cũ: toàn bộ cơ chế
hiệu lực đứng im một tuần mà không ai biết. `update.sh` nay **đếm và nhắc** khi
còn văn bản luật thiếu danh tính. Lần này chạy **bắt buộc cả `--lam-lai-doan`**:
nhãn đoạn cũ mang số hiệu SAI (Nghị định 96/2026 bị gắn "Nghị Định số
63/2025/QH15", Luật 143/2025 bị gắn "203/2025/QH15") — bot "bịa số hiệu" thực
ra là chép đúng nhãn sai này. Chỉ cắt lại đoạn mới sửa được.

**Tên file là danh tính.** File .docx tải từ thuvienphapluat/chinhphu.vn không
có dòng "Số: …" ở đầu, nên số hiệu được lấy **ưu tiên từ tên file**. Đặt tên
theo một trong hai khuôn, hệ thống tự đọc số hiệu, loại, và ngày ban hành:

| Khuôn | Ví dụ | Hệ thống hiểu |
|---|---|---|
| `<Loại>-<số>-<năm>-<ký hiệu>` | `Nghị-định-96-2026-NĐ-CP.docx` | Nghị định số 96/2026/NĐ-CP |
| `<số>-<năm>-<ký hiệu>_ddmmyyyy` | `58-2026-ND-CP_13022026.pdf` | Nghị định số 58/2026/NĐ-CP, ban hành 13/02/2026 |
| Không có năm | `09-CD-TTg_03022025.pdf`, `Văn-bản-hợp-nhất-67-VBHN-VPQH.docx` | 09/CĐ-TTg; 67/VBHN-VPQH (giữ thêm số luật gốc đọc trong chữ) |

Tên kiểu "Luat DN moi.docx" thì hệ thống chỉ còn dựa vào chữ trong văn bản —
đúng khi file có dòng "Số:", còn không thì văn bản vô danh. Kho đang có hai bản
Bộ luật Dân sự (`.docx` và `.doc` cùng tên) và hai bản Luật Doanh nghiệp (bản
gốc + văn bản hợp nhất 67/VBHN-VPQH): chúng chiếm chỗ top-k của nhau — nên giữ
một bản cho mỗi văn bản (với luật đã sửa đổi, giữ bản hợp nhất).

### 4.6 Đẩy tài liệu từ máy cá nhân lên kho (qua SSH)

Ngoài ổ mạng Samba (4.2), có thể đẩy thẳng qua SSH — tiện khi IT nạp một lô lớn.

**Bỏ đúng chỗ mới học được.** Ba quy tắc, sai là file nằm im mà không ai báo:

- File để ở **gốc** `data/raw` bị bỏ qua với lý do *"nằm ở thư mục gốc (không rõ
  loại)"*. Phải nằm trong một thư mục cấp 1 — tên thư mục quyết định loại tài
  liệu **và ai được xem**.
- Trong `9. HỒ SƠ KHÁCH HÀNG` phải có thêm một cấp nữa: thư mục của từng khách,
  đặt tên `1729. Tên công ty` hoặc `[MÃ] Tên khách`. Không tách được mã là bỏ qua.
- `uploads/` là chỗ API cất file tải lên qua web — đừng thả tài liệu vào đó.

**Cách 1 — MobaXterm** (dễ nhất): panel SFTP bên trái, gõ đường dẫn kho rồi kéo thả.

**Cách 2 — `scp` từ Git Bash trên Windows:**

```bash
scp -i ~/.ssh/<khoá> -r "/c/Users/<bạn>/Desktop/tai-lieu-moi/." "pc@<IP máy chủ>:/home/pc/hds-ai-full/hds-ai/data/raw/1. VĂN BẢN PHÁP LUẬT/"
```

OpenSSH từ bản 9 trở đi chạy `scp` qua giao thức SFTP, **không** qua shell của
máy chủ. Vì vậy đường dẫn có dấu cách và tiếng Việt chỉ bọc **một lớp** nháy kép;
lồng thêm nháy đơn bên trong sẽ tạo ra thư mục mang cả dấu nháy trong tên.

Máy Windows thường không có `rsync`, máy chủ thì có. Lô lớn cần đồng bộ nhiều
lần thì chép sang máy chủ một lần rồi `rsync` tại chỗ.

**Kiểm sau khi chép** — số file phải tăng:

```bash
ssh pc@<IP máy chủ> "find ~/hds-ai-full/hds-ai/data/raw -type f | wc -l"
```

Chép xong vẫn phải chạy bộ quét (4.3) thì bot mới học; tài liệu vào hàng chờ duyệt.

**Cách 3 — thả cả lô vào một thư mục rồi để `nap-van-ban.sh` chia ngăn** (từ
06/09/2026). Đỡ phải nhớ văn bản nào thuộc ngăn nào, và chặn ngay tên file không
mang số hiệu — thứ sinh ra "văn bản vô danh" trong kho luật:

```bash
bash deploy/nap-van-ban.sh ~/van-ban-moi --dry-run   # xem sẽ vào ngăn nào
bash deploy/nap-van-ban.sh ~/van-ban-moi             # chép + gọi bộ quét học luôn
bash deploy/nap-van-ban.sh ~/van-ban-moi --khong-hoc # chép, để học sau
```

Nó đọc danh tính bằng chính hàm bộ học dùng (`van_ban.danh_tinh_tu_ten_file`),
nên đặt tên đúng khuôn ở 4.5b là đủ. Tệp báo `✗` **không** được chép — sửa tên
rồi chạy lại. Tệp trùng tên trong kho bị ghi đè và bot học lại bản mới, script
cảnh báo trước khi làm.

**Lô rất lớn (hàng nghìn file, ví dụ kho bản án 07/09/2026):** hai cờ đặt
*trước* lệnh chạy, đừng ghi vào `.env`:

```bash
AUTO_LEARN_AUTO_APPROVE=1 AUTO_LEARN_APPROVE_PDF=1 AUTO_LEARN_BO_TOM_TAT=1 bash deploy/hoc-tu-thu-muc.sh
```

- `AUTO_LEARN_BO_TOM_TAT=1` bỏ bước tóm tắt bằng LLM (~8 giây/tài liệu; 26
  nghìn bản án riêng bước này đã 2–3 ngày). Tóm tắt chỉ hiện ở danh sách Kho
  tài liệu, không dùng để trả lời.
- `AUTO_LEARN_APPROVE_PDF=1` (kèm `AUTO_LEARN_AUTO_APPROVE=1`) duyệt luôn cả
  PDF — chỉ cho lô văn bản **công khai** (bản án đã công bố, văn bản luật),
  tuyệt đối không cho hồ sơ khách. Không có cờ này thì 26 nghìn file rơi vào
  hàng chờ duyệt tay.

Tài liệu đã **gỡ** (`active=false`) nên chuyển file gốc ra ngoài kho
(`hds-ai/data/_da_go/`): bộ quét không báo "mất tệp" cho tài liệu đã gỡ, nhưng
file còn nằm trong kho thì lần quét sau nó học lại thành tài liệu mới.

### 4.7 Bộ quét nguồn văn bản trên mạng

Từ 30/08/2026. Theo dõi vài trang nguồn đã chọn, tải file mới về đúng thư mục
kho, rồi **để bộ quét kho (4.3) học như file nhân viên thả vào** — nghĩa là vẫn
qua cổng duyệt, vẫn phân quyền theo tên thư mục. Không có LLM nào quyết định gì
trong bộ quét này.

Khai nguồn ở **Quản trị → Cài đặt AI → Nguồn văn bản trên mạng** (khoá
`web_sources`). Mặc định **không nguồn nào bật**.

```json
{"nguon": [{"ten": "Công báo — văn bản mới",
            "bat": true,
            "kieu": "rss",
            "url": "https://…/rss",
            "mien_cho_phep": ["ten-mien.gov.vn"],
            "thu_muc": "1. VĂN BẢN PHÁP LUẬT",
            "duoi_file": [".pdf", ".doc", ".docx"],
            "mau_lien_ket": "",
            "toi_da_moi_lan": 20}]}
```

`kieu` nhận `rss`, `sitemap` hoặc `html`. `mien_cho_phep` **bắt buộc** — không có
thì không tải gì, kể cả link nằm ngay trong trang đó. `mau_lien_ket` là regex lọc
thêm khi trang trộn văn bản với tin tức, ví dụ `/van-ban/`.

```bash
bash deploy/theo-doi-nguon-web.sh --dry-run            # xem nhặt ra link nào, chưa tải gì
bash deploy/theo-doi-nguon-web.sh                      # tải thật
bash deploy/theo-doi-nguon-web.sh --nguon "Công báo"   # chỉ một nguồn
sudo bash deploy/theo-doi-nguon-web.sh --install-timer # lịch 6 giờ/lần
journalctl -u hds-ai-nguon-web.service -n 40 --no-pager
```

**Luôn chạy `--dry-run` trước khi bật một nguồn mới**: mỗi trang dựng link một
kiểu, phải nhìn nó nhặt ra gì đã.

Năm chốt an toàn — đây là cửa **duy nhất** trong hệ thống nhận dữ liệu từ
Internet, gỡ chốt nào là mở đúng cửa đó:

1. Chỉ tải từ miền trong `mien_cho_phep`, kiểm lại **cả sau khi** đi hết chuyển hướng.
2. Nội dung phải đúng định dạng mà tên file tự xưng. Link `.pdf` trả về trang lỗi
   HTML là ca hỏng thường gặp nhất — không chặn thì kho có "văn bản luật" mà toàn
   văn là `404 Not Found`.
3. Trần dung lượng kiểm cả lúc đang tải, không tin `Content-Length`.
4. **File tải từ mạng luôn chờ người duyệt**, bất kể `AUTO_LEARN_AUTO_APPROVE`.
   Mọi tài liệu khác trong kho đều do nhân viên tự tay đặt vào; đây là loại đầu
   tiên không ai nhìn qua trước.
5. Thư mục đích và tên file lấy từ URL đều bị ràng phải nằm trong kho.

Không làm được: trang dựng danh sách bằng JavaScript (dùng RSS/sitemap của chính
trang đó thay thế), và trang cần đăng nhập.

### 4.8 Quản lý kho từ trang Tổng quan (11/09/2026)

Thẻ **Kho tài liệu trên máy chủ** ở cuối trang Quản trị → Tổng quan là chính
cây thư mục `data/raw` trên máy chủ, đọc trực tiếp từ đĩa — admin không cần SSH.

- **Cây bên trái** tải từng tầng khi mở; mỗi ngăn hiện `đã học/tổng file` và
  số chờ duyệt. Chênh lệch hai số = file chưa học, lỗi, hoặc định dạng không
  hỗ trợ — bấm vào ngăn để thấy từng file với trạng thái: *Đã học*, *Đã học ·
  cảnh báo* (scan/OCR), *Chờ duyệt*, *Chưa học*, *Lỗi học* (kèm lý do), *Không
  hỗ trợ*.
- **Tìm trong cả kho** so từng từ với tên, số hiệu, loại + trích yếu và đường
  dẫn ("Bộ luật Dân sự", "168/2025", "Hop dong mau bao hiem" đều ra); văn bản
  luật xếp trước bản án. Chỉ tìm được tài liệu ĐÃ có bản ghi.
- **Tải lên vào đây** (người có quyền duyệt): file vào đúng thư mục đang xem và
  được học ngay, nhãn lấy theo thư mục y như bộ quét (`resolve_labels`), nên
  KHÔNG tải vào gốc kho — chọn một ngăn. Tối đa 20 file/lần, mỗi file mất
  khoảng 10–20 giây (embedding + tóm tắt). Trùng tên file trong thư mục thì bị
  từ chối: gỡ bản cũ trước nếu muốn thay.
- **Học ngay**: file đang *Chưa học* hoặc *Lỗi học* (ví dụ vừa được thả qua
  Samba) được học tức thì; nội dung không đổi thì không học lại.
- **Bỏ** (chỉ admin): `active=false` + chuyển file gốc sang `data/_da_go/<đường
  dẫn cũ>`. Bot ngừng dùng ngay, bộ quét không học lại. File không bị xoá hẳn —
  muốn khôi phục thì chuyển file về chỗ cũ rồi bấm *Học ngay* (bản ghi mới).
  Đặt `DATA_DA_GO` trong `.env` nếu muốn thùng đã gỡ nằm chỗ khác.
- **Thư mục con**: tạo ngăn con trong thư mục đang xem (không đặt tên bắt đầu
  bằng `.` hoặc `~$`, không dùng `uploads`).
- **Quét lại** (nút trên thẻ *Quét kho tài liệu trên máy chủ*, tab Kho tài liệu
  đã học): khởi động `python -m app.local_learn` chạy nền ngay trên máy chủ —
  học file mới thả qua Samba, nhận file đổi/đổi tên, báo file mất — với chính
  sách duyệt thường (không cờ tự duyệt). Thẻ thăm dò mỗi 10 giây, hiện đuôi
  nhật ký (`data/quet_kho.log`) và báo khi xong; cả kho 35.000 file mất
  khoảng 10 phút. Không bao giờ chạy hai lượt song song: đang có lượt quét
  (kể cả do IT chạy từ SSH) thì nút bị khoá.

Mọi thao tác ghi vào `audit_log` (`kho_hoc`, `kho_go`, `kho_tao_thu_muc`).
API tương ứng: `GET /kho/cay`, `GET /kho/tim`, `POST /kho/tai-len`, `POST
/kho/hoc`, `POST /kho/go`, `POST /kho/thu-muc` (`hds-ai/app/kho.py`).

## 5. TÊN MIỀN VÀ HTTPS

### 5.1 Trỏ tên miền lần đầu

1. **Lấy IP công khai của máy chủ:**
   ```bash
   curl -s https://ifconfig.me
   ```
2. **Tại nhà cung cấp tên miền** (Namecheap, Mắt Bão…): thêm **một bản ghi A**
   `Host: app` → `Value: <IP vừa lấy>` → TTL Automatic.
   **Chỉ cần bản ghi A. Không đổi nameserver.** Không cần AAAA/CNAME/TXT.
3. **Kiểm tra DNS đã lan truyền** (chạy trên máy chủ):
   ```bash
   getent hosts app.hdslaw.vn     # phải trả về đúng IP ở bước 1
   ```
4. **Mở cổng 80 và 443** trên router về IP LAN của máy chủ (script thử mở tự động bằng UPnP, thất bại thì làm tay).
5. **Chạy:**
   ```bash
   sudo bash deploy/go-public.sh app.hdslaw.vn it@hdslaw.vn
   ```

Script sẽ: dò IP → thử mở cổng bằng UPnP → tạo thêm tên tạm `hds-ai.<IP-gạch-nối>.sslip.io` (dùng được ngay, không cần DNS) → thêm tên miền vào nginx → xin chứng chỉ Let's Encrypt cho từng tên → in các URL đã có HTTPS.

DNS chưa trỏ đúng thì script **không báo lỗi** — nó chỉ in hướng dẫn tạo bản ghi A và bỏ qua tên miền đó. Trỏ xong chạy lại chính lệnh đó, chạy lại nhiều lần không hỏng gì.

### 5.2 Khi đổi sang tên miền khác

`go-public.sh` chỉ **thêm** tên, không bao giờ **bỏ** tên cũ. Quy trình đúng:

```bash
# 1. Tạo bản ghi A cho tên mới, kiểm tra đã trỏ đúng
getent hosts new.hdslaw.vn && curl -s https://ifconfig.me

# 2. Thêm tên mới + xin chứng chỉ
sudo bash deploy/go-public.sh new.hdslaw.vn it@hdslaw.vn

# 3. Gỡ tên cũ bằng tay
sudo cp /etc/nginx/sites-available/hds-ai /etc/nginx/sites-available/hds-ai.bak.$(date +%F)
sudo nano /etc/nginx/sites-available/hds-ai
#    · xoá tên cũ khỏi MỌI dòng server_name
#    · xoá khối redirect  if ($host = old.hdslaw.vn) { ... }  do certbot sinh ra
sudo nginx -t && sudo systemctl reload nginx

# 4. Xoá chứng chỉ cũ (không bắt buộc)
sudo certbot delete --cert-name old.hdslaw.vn

# 5. Cập nhật deploy.env để lần cài sau dùng tên mới
sudo nano deploy/deploy.env      # DOMAIN=new.hdslaw.vn
```

**Không cần** làm gì thêm: giao diện gọi API bằng đường dẫn tương đối `/api` nên **không phải build lại**; `CORS_ORIGINS` phải **để trống**; không có cấu hình tên miền nào trong CSDL hay màn hình quản trị.

Hai chỗ ghi tên miền cũ trong tài liệu, sửa tay nếu có gửi cho khách: `deploy/API_KHACH_HANG.md` và `deploy/README.md`.

**Một người dùng lỗi mạng còn cả công ty bình thường?** Trình duyệt người đó có lưu địa chỉ backend cũ (ai đó từng bấm "Cấu hình kết nối"). Sửa: F12 → Application → Local Storage → xoá khoá `hds_api_base_url`, tải lại trang.

### 5.3 Quay lại chỉ dùng LAN

```bash
sudo cp /etc/nginx/sites-available/hds-ai /etc/nginx/sites-available/hds-ai.bak.$(date +%F)
sudo nano /etc/nginx/sites-available/hds-ai
#   · server_name _;   · xoá các dòng listen 443 ssl / ssl_certificate  · xoá khối redirect
sudo nginx -t && sudo systemctl reload nginx
```
Rồi gỡ hai luật port forwarding trên router. Truy cập lại bằng `http://<IP LAN>`.

### 5.4 Ba cạm bẫy phải biết

1. **Chạy lại `setup.sh` sẽ ghi đè toàn bộ file nginx** — mất tên sslip.io, mất các dòng SSL của certbot, mất khối chuyển hướng HTTPS. Sau mỗi lần `setup.sh`, **chạy lại `go-public.sh`**. (`update.sh` thì an toàn, không đụng file này.)
2. **Sau khi có HTTPS, truy cập bằng `http://<IP LAN>` có thể trả 404** — certbot sinh khối chỉ phục vụ đúng tên miền. Trong công ty hãy dùng tên miền https, hoặc thêm một khối server riêng cho IP.
3. **Không script nào cấu hình tường lửa.** Nếu `ufw` đang bật, mở tay: `sudo ufw allow 80,443/tcp`. Certbot thất bại vì tường lửa có triệu chứng y hệt DNS sai.

**Gia hạn chứng chỉ**: dựa vào `certbot.timer` của Ubuntu, repo không cài gì thêm. Kiểm tra một lần cho chắc:
```bash
systemctl list-timers certbot.timer
sudo certbot renew --dry-run
```

---

## 6. CẬP NHẬT PHIÊN BẢN MỚI

```bash
cd /opt/hds-ai-full
git pull
sudo bash deploy/update.sh
```

`update.sh` chạy 5 bước theo đúng thứ tự: cài thư viện Python → bổ sung công cụ OCR/Office còn thiếu → **nạp lược đồ CSDL** → **chạy toàn bộ test** → build giao diện → khởi động lại backend + nginx.

**Test là cổng chặn**: test hỏng thì backend cũ vẫn chạy nguyên, code mới không được khởi động. Nhưng lưu ý **lược đồ CSDL đã được nạp trước đó** — thất bại ở bước test không có nghĩa là chưa động gì tới CSDL.

Gặp lỗi:

| Thông báo | Xử lý |
|---|---|
| `Hãy chạy bằng quyền root` | thêm `sudo` |
| `Thiếu APP_DB_PASSWORD trong .env` | `hds-ai/.env` bị hỏng/thiếu — khôi phục từ bản chép tay |
| `Migration schema thất bại` | đọc lỗi psql phía trên; kiểm tra `docker ps \| grep hds-postgres` |
| `Backend test thất bại` | chạy tay `cd hds-ai && .venv/bin/python -m unittest discover -s tests -v`; cần thì `git checkout <commit cũ>` rồi update lại |
| `Build frontend thất bại` | giao diện cũ vẫn đang được phục vụ; xem log npm |
| `Backend lỗi` | `journalctl -u hds-ai-backend -n 40 --no-pager` |

### Update xong mà người dùng bảo "vẫn lỗi cũ"

Gần như luôn là **trình duyệt còn chạy bản cũ**, không phải mã chưa lên. Tab mở sẵn từ trước không tải gì cả; tab mở mới vẫn có thể lấy `index.html` trong cache (Cloudflare gắn `max-age` 4 giờ cho file JS). Từ 06/09/2026 có ba lớp chống:

1. **nginx** trả `Cache-Control: no-cache` cho `index.html` (update.sh tự chèn vào cấu hình cũ) — mở tab mới là thấy bản mới.
2. **Dải vàng "HDS AI vừa có bản cập nhật — Tải lại ngay"** tự hiện trên tab đang mở: giao diện cứ 5 phút và mỗi lần quay lại tab lại đối chiếu tên bundle với `index.html` trên máy chủ.
3. **Dấu bản build** in ở chân khung chat (`HDS Law Firm — … · a1b2c3d-0609.0227`), tooltip logo và hộp *Cấu hình kết nối*. `update.sh` in cùng dấu đó (`Đã build bản …`). Hai dấu khác nhau → bấm **Ctrl+Shift+R**.

Ảnh chụp lỗi mà cả thanh địa chỉ lẫn DevTools cũng mờ là mờ ở tầng máy/công cụ chụp — trang web không thể làm mờ khung trình duyệt.

---

## 7. SAO LƯU VÀ PHỤC HỒI

> **Hệ thống KHÔNG tự sao lưu.** Không có cron, không có timer nào cho việc này. Bạn phải tự đặt lịch.

### 7.1 Sao lưu

```bash
mkdir -p /root/backup && chmod 700 /root/backup
docker exec hds-postgres pg_dump -U hds -Fc hdsai > /root/backup/hdsai_$(date +%F).dump
```

**Và kho tài liệu** — từ khi bỏ Drive, đây là bản gốc duy nhất:

```bash
rsync -a --delete /opt/hds-ai-full/hds-ai/data/raw/ /mnt/backup/kho-tai-lieu/
```

Đặt lịch hằng đêm 02:30 (`sudo crontab -e`) — nhớ escape dấu `%`:

```cron
# 02:30 — cơ sở dữ liệu
30 2 * * * /usr/bin/docker exec hds-postgres pg_dump -U hds -Fc hdsai > /root/backup/hdsai_$(date +\%F).dump 2>>/root/backup/pg_dump.err
# 03:00 — kho tài liệu (BẢN GỐC DUY NHẤT) ra ổ ngoài
0 3 * * * /usr/bin/rsync -a --delete /opt/hds-ai-full/hds-ai/data/raw/ /mnt/backup/kho-tai-lieu/ 2>>/root/backup/rsync.err
```

Ngoài CSDL, chép tay và cất nơi an toàn (những thứ này không nằm trong dump):
`hds-ai/.env` (và `hds-ai/credentials/service-account.json` nếu máy chủ còn giữ
đường lui về Drive — bỏ Drive rồi thì file này không còn cần thiết).

Nên xoay vòng: giữ 7 bản gần nhất + 1 bản mỗi tháng, và **chép một bản ra máy khác** — dump nằm cùng ổ với CSDL thì ổ hỏng là mất cả hai.

> Bản dump chứa **toàn bộ hồ sơ khách hàng**. Thư mục quyền 700, không đưa lên GitHub/Drive công khai, chép ra ổ ngoài thì cân nhắc mã hoá.

### 7.2 Phục hồi

```bash
docker exec -i hds-postgres pg_restore -U hds -d hdsai --clean --if-exists < /root/backup/hdsai_2026-08-26.dump
sudo systemctl restart hds-ai-backend
```

Kiểm tra phục hồi thành công (không có script tự động, làm 4 bước):

```bash
docker exec -i hds-postgres psql -U hds -d hdsai -tAX -c \
  "SELECT count(*) FROM documents; SELECT count(*) FROM chunks;"   # so với số trước khi restore
sudo bash deploy/kiem-tra-vector.sh                                # không được có dòng ✘
cd hds-ai && .venv/bin/python -m tests.test_security               # không được có dòng [HỎNG]
```
rồi vào web hỏi một câu thật, xem có trả về trích dẫn không.

### 7.3 Bản sao lưu do script học lại tạo ra

`hoc-lai-*.sh` tự dump 2 bảng trước khi xoá, ra `/var/backups/hds-ai-tailieu-*.sql.gz` (hoặc `$HOME` nếu không ghi được `/var/backups`). Đây là **SQL thuần nén gzip**, `pg_restore` không đọc được:

```bash
gunzip -c /var/backups/hds-ai-tailieu-20260826-101500.sql.gz | docker exec -i hds-postgres psql -U hds -d hdsai
```

---

## 8. QUẢN LÝ NGƯỜI DÙNG VÀ PHÂN QUYỀN

### 8.1 Làm được trên web (admin: **Quản trị → Người dùng & Phòng ban**)

| Việc | Cách |
|---|---|
| Tạo tài khoản | Form **Thêm người dùng**. Mật khẩu khởi tạo luôn là **`hds12345`** |
| Gán phòng ban | Tick **Thuộc phòng ban** — **chỉ làm được lúc tạo** |
| Cấp/thu quyền duyệt | Bấm nút **Có quyền duyệt / Không có quyền duyệt** trên thẻ tài khoản |
| Cấp/thu quyền xem công nợ | Nút **Xem được công nợ / Không xem công nợ** |
| Cấp/thu khoá API cho khách | Nút **Cấp khoá API / Thu hồi khoá API** (chỉ tài khoản khách) |
| Đặt hạn mức câu hỏi/tháng | Ô **Hạn mức** lúc tạo tài khoản khách (0 = không giới hạn) |

Tài khoản khách (`client_*`) **bắt buộc** gắn với một khách hàng. Bản ghi khách được tạo tự động từ tên thư mục khách trong kho, hoặc bằng SQL.

### 8.2 Chỉ làm được bằng SQL

Mở psql: `docker exec -it hds-postgres psql -U hds -d hdsai`

```sql
-- Khoá / mở tài khoản (không có nút trên web)
UPDATE users SET active=false WHERE email='nguoi.nghi@hdslaw.vn';
UPDATE users SET active=true  WHERE email='nguoi.nghi@hdslaw.vn';

-- Đổi phòng ban sau khi đã tạo tài khoản
DELETE FROM user_departments WHERE user_id=7;
INSERT INTO user_departments (user_id, department_id, is_head) VALUES (7, 2, false);

-- Thêm phòng ban mới
INSERT INTO departments (code, name) VALUES ('m-a', 'Mua bán - Sáp nhập');

-- Tạo khách hàng mới (không có endpoint tạo khách)
INSERT INTO clients (name, code, department_id) VALUES ('Công ty ABC', 'ABC', 1);

-- Sửa ma trận quyền: cho trợ lý mở được mẫu hợp đồng
UPDATE access_rules SET can_open=true
 WHERE role_level='tro_ly' AND doc_type='mau_hd';    -- hiệu lực NGAY, không cần restart
```

**Đặt lại mật khẩu quên** (không có chức năng trên web):

```bash
cd hds-ai
.venv/bin/python -c "from app import auth; print(auth.hash_password('MatKhauMoi123'))"
# chép chuỗi hash rồi:
docker exec -i hds-postgres psql -U hds -d hdsai -c \
  "UPDATE users SET password_hash='<hash vừa in>' WHERE email='nguoi.quen@hdslaw.vn';"
```

### 8.3 Ma trận quyền mặc định

`access_rules` quyết định **vai nào ở phòng nào mở được loại tài liệu nào**. Mặc định sau khi seed:

- **admin / ban_qt**: không có dòng nào — mặc định thấy hết (công nợ vẫn phải cấp riêng cho ban_qt).
- **truong_bph**: mở được cả 13 loại (hồ sơ khách vẫn giới hạn trong phòng mình).
- **chuyen_vien**: mở hầu hết, **trừ** bản án, hồ sơ nhân sự; mẫu hợp đồng và nhãn hiệu tuỳ phòng.
- **tro_ly**: chỉ mở luật, án lệ, thư mẫu, quy trình, khác.
- **Khách**: Free = chỉ luật · Plus = thêm quy trình, thư mẫu, hồ sơ/hợp đồng/tư vấn của chính họ · Pro = thêm án lệ, mẫu hợp đồng. **Công nợ chặn với cả ba gói.**

Không có dòng khớp = **từ chối**. Thêm `doc_type` mới mà quên thêm dòng thì không ai mở được (trừ admin/ban_qt).

### 8.4 Ba lớp bảo vệ dữ liệu khách

1. **RLS trong PostgreSQL** — câu truy vấn tìm kiếm không có điều kiện phân quyền; chính CSDL từ chối trả dòng. Prompt injection không vượt được vì nó chỉ tác động tới model, không tác động tới CSDL.
2. **`can_open_doc` trong ứng dụng** — chốt thứ hai cho các đường mở/tải file (những đường này mở phiên admin nên RLS không áp).
3. **Công nợ chặn trước tiên** — kiểm tra trước cả quyền Ban QT.

Kiểm tra ba lớp còn nguyên:
```bash
cd hds-ai && .venv/bin/python -m tests.test_security
```

---

## 9. CÀI ĐẶT AI — BẢNG THAM SỐ

**Quản trị → Cài đặt AI** (chỉ admin). Mọi thay đổi có hiệu lực **ngay ở câu hỏi tiếp theo**, không cần khởi động lại.

| Tham số | Mặc định | Ý nghĩa | Khi nào chỉnh |
|---|---|---|---|
| **Model sinh câu trả lời** | `qwen3:14b` | Model trả lời | Máy yếu → `qwen3:8b` hoặc `qwen3:4b` |
| Model tạo vector | `bge-m3` | **Cố định, không có nút đổi** | Không bao giờ |
| Độ sáng tạo (`llm_temperature`) | 0.2 | 0 = bám tài liệu, 1 = phóng khoáng | Pháp lý nên để thấp |
| Số đoạn tham chiếu (`retrieval_top_k`) | 24 | Số đoạn tài liệu đưa vào mỗi câu | Chậm → giảm còn 4–6 |
| Trần ký tự tài liệu (`context_char_budget`) | 0 = không giới hạn | **Ảnh hưởng tốc độ mạnh nhất** | Chậm → đặt 6000 |
| Cắt mỗi đoạn (`chunk_char_limit`) | 0 = giữ trọn | Chặn một đoạn dài chiếm hết chỗ | Chậm → đặt 1500 |
| Ngưỡng liên quan (`min_relevance`) | 0.25 | Dưới ngưỡng bị loại | Bot trả lời lan man → tăng |
| Số lượt hỏi-đáp nhớ lại | 10 | Số lượt giữ NGUYÊN VĂN; phần cũ hơn dồn vào bản tóm tắt | Chậm → giảm còn 3 |
| **Bộ nhớ dài** (`history_summary_enabled`) | `true` | Hội thoại dài thì phần cũ được LLM cô đọng ở LUỒNG NỀN (không cộng thời gian chờ); prompt = tóm tắt + N lượt gần nhất | Máy CPU quá tải vì lượt tóm tắt nền → `false` |
| Trần tóm tắt (`history_summary_max_chars`) | 2500 | Độ dài tối đa bản tóm tắt (ký tự) — to hơn nhớ kỹ hơn, tốn ngữ cảnh hơn | Hiếm khi cần đổi |
| Trần độ dài trả lời (`llm_num_predict`) | -1 = không chặn | | Máy quá yếu → 700 |
| Cửa sổ ngữ cảnh (`llm_num_ctx`) | 32768 | **Trần vật lý duy nhất** | Thiếu RAM → 16384 |
| Số luồng CPU | 0 = tự quyết | Chỉ có tác dụng khi chạy CPU | Máy không GPU → bằng số nhân |
| **Bot đọc lại câu trả lời** (`answer_review`) | `auto` | `auto` = chỉ đọc lại khi có dấu hiệu chưa ổn (quá dài, bỏ lửng, lặp); `always` = mọi câu, **chậm gấp đôi**; `off` = tắt | Máy yếu và cần nhanh → `off` |
| **Chặn câu thiếu trích dẫn** (`strict_grounding`) | `true` | Câu trả lời dựa trên tài liệu mà không có `[Nguồn n]` hợp lệ thì bị chặn, không cho hiện | Chỉ tắt khi đang gỡ lỗi — tắt là mở cửa cho bot bịa |
| Số đoạn ứng viên (`retrieval_candidate_k`) | 300 | Hybrid search lấy rất rộng rồi mới xếp hạng lại. Ảnh hưởng thời gian *tìm*, không ảnh hưởng thời gian *viết* | Tìm chậm → giảm còn 150 |
| Trần đoạn mỗi tài liệu (`retrieval_max_chunks_per_doc`) | 8 | Chặn một file dài chiếm hết chỗ, ép nguồn đa dạng | Câu trả lời chỉ dựa vào một file → giảm còn 4 |
| **Phong cách tư vấn** ×4 | | Prompt hệ thống cho 4 kênh: nội bộ / cổng khách / website / **tab Kiểm tra pháp lý** (`prompt_legal_review` — giọng rà soát hồ sơ, khác hẳn giọng tư vấn) | Đổi giọng văn, quy tắc trích dẫn |
| **Bản đồ thư mục kho** | JSON | Tên thư mục trong kho → nhãn tài liệu | Thêm ngăn mới vào kho |
| **Gọi model qua API** (`cloud_enabled`) | `false` | Bật là dữ liệu câu hỏi **rời khỏi máy chủ** và mỗi lượt hỏi tốn tiền. Cần `ANTHROPIC_API_KEY` (hoặc `COMPAT_*`) trong `.env` | Cần lập luận pháp lý sâu hơn qwen3:14b |
| Phạm vi dữ liệu ra ngoài (`cloud_scope`) | `law_only` | `law_only` / `plus_attachments` / `all_but_finance`. Câu hỏi chạm dữ liệu ngoài phạm vi **không bị cắt xén** — nó tự chạy bằng model trên máy chủ. Công nợ chặn cứng ở mọi mức | Muốn tab Kiểm tra pháp lý dùng cloud → `plus_attachments` |
| Model cloud (`cloud_model`) | `claude:claude-sonnet-5` | Tiền tố `claude:` (API Anthropic) hoặc `api:` (endpoint tương thích OpenAI — Qwen/DashScope, DeepSeek, OpenRouter) | Rẻ hơn → `claude:claude-haiku-4-5` |
| Kênh được gọi API (`cloud_channels`) | `internal` | **Không mở cho `public`** — đó là cửa cho người lạ gõ câu hỏi không giới hạn, mở cloud ở đó là mở hoá đơn cho người lạ bơm | Hiếm khi đổi |
| Độ sâu suy nghĩ (`cloud_effort`) | `medium` | Nút chỉnh chi phí chính sau khi đã chốt model | Rà soát hồ sơ → `high`; tra cứu thường → `low` |
| Trần ký tự cloud (`cloud_context_char_budget`) | 60000 | **Bắt buộc phải có**: qua API không còn `num_ctx` làm trần vật lý, prompt phình bao nhiêu hoá đơn theo bấy nhiêu | 0 = theo cửa sổ thật của model (rất đắt) |
| Trần token trả lời cloud (`cloud_max_tokens`) | 8000 | Khác `llm_num_predict` vì API tính tiền theo token sinh ra | Câu trả lời bị cụt → tăng |
| Lui về local khi API hỏng (`cloud_fallback_local`) | `true` | Mất mạng hoặc hết quota mà không có đường lui là mất luôn trợ lý | Chỉ tắt khi đang tìm nguyên nhân lỗi |
| **Nguồn văn bản trên mạng** (`web_sources`) | không nguồn nào bật | Bộ quét định kỳ tải văn bản mới về kho — xem mục 4.7 | Thêm nguồn theo dõi |

> **Cảnh báo cửa sổ ngữ cảnh:** prompt dài hơn `llm_num_ctx` bị Ollama cắt **phần đầu** — đúng chỗ chứa dữ liệu công ty. Giao diện hiện cảnh báo vàng "Ngữ cảnh đã chạm trần" trong bảng thời gian khi việc này xảy ra. Gặp cảnh báo thì giảm *Trần ký tự tài liệu*, đừng tăng `num_ctx` vô tội vạ (tốn RAM).
>
> **Cạm bẫy:** dòng cài đặt trong CSDL luôn thắng giá trị mặc định trong mã nguồn. Sau khi nâng cấp, nếu một tham số "không chịu đổi", có thể còn dòng cũ trong bảng `app_settings` — dùng nút **Về mặc định** để xoá dòng đó.

---

### GPU 16GB: kiểm model có đang nằm trọn trên card không

Có GPU không có nghĩa Ollama đang dùng trọn nó. Ca kinh điển: `llm_num_ctx`
đặt to làm (trọng số + bộ nhớ ngữ cảnh KV) vượt VRAM → Ollama **lặng lẽ chẻ
model CPU/GPU**, tốc độ rơi từ vài chục token/giây xuống một chữ số — nhìn hệt
như máy không có GPU.

```bash
bash deploy/kiem-tra-gpu.sh
```

Đọc kết quả: mục 2 (`ollama ps`) cột PROCESSOR phải là **100% GPU**; mục 3 tốc
độ sinh ≥25 token/giây là mức GPU. Số liệu tham chiếu của qwen3:14b trên card
16GB: `num_ctx=32768` cần ~9.3GB trọng số + ~10GB KV f16 = **vượt VRAM**; bật
nén KV (`OLLAMA_KV_CACHE_TYPE=q8_0` + `OLLAMA_FLASH_ATTENTION=1`, lệnh in sẵn
trong script) kéo về ~15.5GB — vừa khít; vẫn chẻ thì hạ *Cửa sổ ngữ cảnh* trên
web xuống 24576, trần ký tự tài liệu tự co theo.

### Nạp một lô lớn mà không muốn duyệt tay

Mặc định **mọi PDF đều chờ người duyệt** (chính sách 20/08/2026) — OCR đọc sai
một con số là sai căn cứ. Khi nạp một lô văn bản **công khai** lớn (hàng trăm
nghị định, án lệ tải từ chinhphu.vn / toaan.gov.vn) mà chấp nhận rủi ro đó để
khỏi bấm duyệt hàng trăm lần:

```bash
cd /opt/hds-ai-full
AUTO_LEARN_AUTO_APPROVE=1 AUTO_LEARN_APPROVE_PDF=1 bash deploy/hoc-tu-thu-muc.sh
```

Đặt biến **ngay trước lệnh**, KHÔNG ghi vào `.env`: nó phải là quyết định của
một lượt chạy cụ thể chứ không lặng lẽ thành mặc định của hệ thống. Lượt chạy
sẽ in `TỰ DUYỆT — KỂ CẢ PDF` ở đầu để không ai chạy nhầm mà không biết.

Đòi **cả hai** biến: bật nhầm một cái không mở toang được.

> Đừng dùng cho hồ sơ khách hàng hay hồ sơ nhân sự — đó đúng là loại tài liệu
> mà bước duyệt tay sinh ra để bảo vệ.

### Chất lượng OCR bản scan

PDF scan và ảnh đi qua OCR trước khi vào kho. Với văn bản luật thì OCR sai một
chữ số là **sai căn cứ**, nên phần này đáng chỉnh:

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `INGEST_OCR_ENGINE` | `auto` | `auto` = dùng **PaddleOCR** nếu máy chủ đã cài, không thì tesseract. Đặt `tesseract` để ép về bản cũ, `paddle` để ép bản mới |
| `INGEST_OCR_DPI` | 400 | Cao hơn mức 300 tesseract khuyến nghị — giấy tờ VN nhiều dấu thanh nhỏ |
| `INGEST_OCR_DESKEW` | bật | Nắn trang nghiêng. Đặt giấy tay thường lệch 1-3°, chỉ 2° là dấu thanh dính vào dòng trên |
| `INGEST_OCR_BINARIZE` | bật | Nhị phân hoá **theo vùng** — cứu bản scan giấy ngả vàng / ánh sáng không đều, nơi ngưỡng toàn ảnh làm mất nửa trang |
| `INGEST_MAX_OCR_PAGES` | 200 | Trần số trang OCR mỗi file; vượt thì báo lỗi thay vì âm thầm cắt |

**Nâng lên PaddleOCR** (đọc tiếng Việt tốt hơn tesseract rõ rệt, chạy được CPU):

```bash
cd /opt/hds-ai-full/hds-ai
.venv/bin/pip install paddleocr paddlepaddle
sudo systemctl restart hds-ai-backend
```

Cài xong là tự dùng, **không phải sửa cấu hình** (`auto` tự nhận). Gỡ ra thì tự
lùi về tesseract. Lượt OCR đầu tiên chậm hơn vì phải tải mô hình về.

Nếu PaddleOCR lỗi giữa chừng, hệ thống **tự lùi về tesseract cho các trang còn
lại** và in một dòng `[OCR] PaddleOCR lỗi … — lùi về tesseract` — đọc kém còn
hơn không đọc được gì.

> **Cách tốt nhất vẫn là tránh OCR:** cùng một văn bản luật thường có bản chữ
> thật (`.doc`/`.docx`) trên vbpl.vn hoặc chinhphu.vn. Bản chữ cho nội dung
> chính xác 100%, không rủi ro OCR nào. Chỉ OCR khi không còn cách khác.

---

## 10. BỘ CÔNG CỤ CHẨN ĐOÁN

| Script | Dùng khi | Lệnh |
|---|---|---|
| **kiem-tra-toc-do.sh** | Bot chậm, lỗi 524, "network error" | `bash deploy/kiem-tra-toc-do.sh` |
| **kiem-tra-vector.sh** | Bot nói "không có thông tin" với mọi câu | `sudo bash deploy/kiem-tra-vector.sh` |
| **soi-ho-so.sh** | Bot không biết gì về một người, dù hồ sơ có trong kho | `bash deploy/soi-ho-so.sh Mai` |
| **hoc-tu-thu-muc.sh** | Muốn quét kho ngay, không chờ 15 phút | `bash deploy/hoc-tu-thu-muc.sh` |
| **hoc-lai-file.sh** | Vài tài liệu OCR ra chữ rác | `bash deploy/hoc-lai-file.sh --hong --thu` rồi bỏ `--thu` |
| **hoc-lai-tu-dau.sh** | Đổi cách chia đoạn / kho vector hỏng | `sudo bash deploy/hoc-lai-tu-dau.sh` |
| **luu-tru-drive.sh** | (cũ) Kéo toàn bộ Drive về — chỉ dùng lúc chuyển đổi | `bash deploy/luu-tru-drive.sh` |

Ba script đầu **chỉ đọc, không sửa gì**, chạy lúc nào cũng an toàn.

`kiem-tra-toc-do.sh` in ra ước tính thời gian một câu hỏi đầy đủ. **>90 giây** là sẽ gặp lỗi 524 sau Cloudflare — script in sẵn 4 bước xử lý theo thứ tự (đổi model nhẹ hơn → giảm tham số ngữ cảnh → khai số luồng CPU → mua GPU).

`kiem-tra-vector.sh` kiểm 6 mục: kết nối + pgvector, chỉ mục tìm kiếm, số liệu kho, model tạo vector, thử một truy vấn thật, danh sách file **có trong kho nhưng không học được**.

> **Hai script `hoc-lai-*` XOÁ dữ liệu trong CSDL rồi học lại.** Chúng tự sao lưu trước, hỏi xác nhận (`XOA` / `DOC LAI`, đúng chữ hoa), giữ lại trạng thái đã duyệt và không đụng vào tệp gốc trong kho. Nhưng: chạy **ngoài giờ làm việc** (vài trăm tài liệu = vài giờ), trong lúc chạy bot không tra được các tài liệu đó, và tài liệu không còn tệp trong kho sẽ bị **bỏ qua** vì xoá là mất hẳn (script kiểm tra từng tệp trước khi xoá).

---

## 11. TRIỆU CHỨNG → LỆNH XỬ LÝ

| Triệu chứng | Lệnh đầu tiên |
|---|---|
| **502 Bad Gateway** | `sudo systemctl restart hds-ai-backend` |
| **Trang trắng / 403** | Repo có nằm trong `/root/` không? Chuyển sang `/home` hoặc `/opt` |
| **Đăng nhập lỗi 500** | `journalctl -u hds-ai-backend -n 40` — thường thiếu biến trong `.env` |
| **Đăng nhập được nhưng hỏi AI lỗi** | `curl -s http://localhost:11434/api/tags` — Ollama tắt hoặc chưa `ollama pull` |
| **Chậm / lỗi 524** | `bash deploy/kiem-tra-toc-do.sh` |
| **Chữ hiện một cục thay vì chảy dần** | `grep -n "proxy_buffering" /etc/nginx/sites-available/hds-ai` — thiếu thì thêm `proxy_buffering off;` vào `location /api/` |
| **Update xong mà "vẫn lỗi cũ"** | So dấu bản build ở chân khung chat với dòng `Đã build bản …` của update.sh; khác nhau → Ctrl+Shift+R (mục 6) |
| **Bot không trả lời từ bất kỳ tài liệu nào** | `sudo bash deploy/kiem-tra-vector.sh` |
| **Tài liệu có nhưng bot không dùng** | Xem **Quản trị → Duyệt nhãn tài liệu** — gần như luôn là chưa duyệt |
| **File trong kho không được học** | **Quản trị → Kho tài liệu đã học** → thẻ đỏ/vàng, kèm lý do từng file |
| **Bản scan luôn "không học được"** | `tesseract --list-langs \| grep vie` — thiếu thì `sudo apt install -y tesseract-ocr-vie poppler-utils` rồi `sudo bash deploy/update.sh` |
| **Chữ OCR ra ký tự rác (Å Ø ƒ Ð)** | `bash deploy/hoc-lai-file.sh --hong --thu` rồi chạy thật |
| **Model nạp lại mỗi câu hỏi** | `ollama ps` — phải thấy **cả hai** model thường trú; không đủ RAM thì đổi model nhỏ hơn |
| **GPU có mà chạy CPU** | `nvidia-smi`; `sudo ubuntu-drivers autoinstall && sudo reboot` |
| **`psql: No such file or directory`** | Postgres nằm trong Docker: `docker exec -i hds-postgres psql -U hds -d hdsai` |
| **HTTPS không cấp được** | DNS chưa trỏ đúng, hoặc cổng 80 đóng; `sudo certbot --nginx -d <domain>` |
| **Bảng `ingest_failures` không tồn tại** | Máy chưa chạy migration mới: `sudo bash deploy/update.sh` |
| **Nghi lộ dữ liệu chéo giữa khách** | `cd hds-ai && .venv/bin/python -m tests.test_security` |
| **Câu trả lời chậm bất thường** | `sudo journalctl -u hds-ai-backend -n 200 \| grep CHAM` |

Log ở đâu:

```bash
journalctl -u hds-ai-backend -f            # backend
journalctl -u hds-ai-quet-kho.service -n 40  # lần quét kho gần nhất
docker logs hds-postgres --tail 50         # cơ sở dữ liệu
tail -f /var/log/nginx/error.log           # nginx
journalctl -u ollama -n 50                 # model
```

---

## 12. VIỆC ĐỊNH KỲ

**Hằng ngày (2 phút)** — mở **Quản trị → Tổng quan**:
- Ô **"Thiếu chủ sở hữu"** phải bằng **0**. Khác 0 là có hồ sơ khách chưa gán chủ → xử lý ngay.
- **Chờ duyệt nhãn** không nên dồn quá lâu.
- **Quét kho tài liệu** (trong *Kho tài liệu đã học*): "Quét lần cuối" phải trong vòng 15 phút; và kiểm hai danh sách **"đang phục vụ vừa rơi lại hàng chờ duyệt"** và **"không còn tệp trong thư mục"**.

**Hằng tuần**
```bash
df -h                                  # ổ đĩa còn trống — dưới 100GB thì lo ổ mới
sudo bash deploy/kiem-tra-vector.sh    # kho vector còn khoẻ
ls -lh /root/backup/ | tail -5         # bản sao lưu CSDL có sinh ra thật không
du -sh /mnt/backup/kho-tai-lieu/       # bản sao lưu KHO có chạy không
```

**Hằng tháng**
- Thử phục hồi một bản dump sang CSDL tạm — **bản sao lưu chưa từng thử phục hồi thì chưa phải bản sao lưu**.
- `cd hds-ai && .venv/bin/python -m tests.test_security` — kiểm tra cách ly dữ liệu khách.
- Xoá bản sao lưu cũ, dọn `hds-ai/data/work/` nếu phình.
- Kiểm tra chứng chỉ: `sudo certbot certificates`.

**Khi có bản cập nhật**: `git pull && sudo bash deploy/update.sh` (mục 6).

---

## 13. CẤM KỴ — LÀM LÀ MẤT DỮ LIỆU

| Đừng bao giờ | Vì sao |
|---|---|
| `docker compose down -v` | Cờ `-v` **xoá volume `pgdata`** — mất toàn bộ tri thức, hội thoại, người dùng |
| Đổi `EMBED_MODEL` (bge-m3) trên kho đã có dữ liệu | Mọi vector cũ thành vô nghĩa, phải học lại từ đầu (hàng giờ) |
| Sửa `EMBED_DIM` mà không sửa cột `vector(1024)` | Backend chết ngay khi tạo vector |
| Chạy `setup.sh` trên máy đang chạy mà không báo trước | Đặt lại mật khẩu tài khoản mẫu, xoá ma trận quyền đã chỉnh tay, ghi đè cấu hình nginx (mất HTTPS) |
| Xoá bất cứ thứ gì trong `hds-ai/data/raw/` | Đây là **kho — bản gốc duy nhất** từ khi bỏ Drive; không còn Google giữ hộ |
| Chạy bộ quét kho khi chưa `--chuyen-doi` | Nhân đôi toàn bộ kho (bộ quét tự chặn, đừng ép qua) |
| Bật lại `DRIVE_FOLDER_ID` mà không `--chuyen-doi --nguoc` | Bộ quét Drive không nhận ra tài liệu local → học lại thành bản trùng |
| Chạy `hoc-lai-*.sh` trong giờ làm việc | Tài liệu không tra được suốt quá trình chạy |
| Đặt repo trong `/root/` | nginx không đọc được → 403 |
| Điền `CORS_ORIGINS` cho cùng một máy chủ | Không cần thiết và mở rộng bề mặt tấn công |
| Sửa `VITE_API_BASE_URL` thành URL tuyệt đối | Mỗi lần đổi tên miền phải build lại, sinh lỗi CORS |
| Commit `.env`, `credentials/`, `*.dump` lên git | Lộ mật khẩu CSDL và toàn bộ hồ sơ khách |
| Chạy backend với nhiều `--workers` | Van chống spam kênh công khai đếm theo tiến trình, nhân worker là nhân hạn mức |

---

## 14. PHỤ LỤC

### 14.1 Các khoá quan trọng trong `hds-ai/.env`

```bash
# Cơ sở dữ liệu — setup.sh sinh ngẫu nhiên, ĐỪNG sửa tay khi đã có dữ liệu
DB_HOST=localhost   DB_PORT=5432   DB_NAME=hdsai   DB_USER=hds
DB_PASSWORD=<sinh ngẫu nhiên>          # mật khẩu chủ sở hữu CSDL
APP_DB_PASSWORD=<sinh ngẫu nhiên>      # tài khoản ứng dụng (bị RLS ràng buộc)

# Model
OLLAMA_URL=http://localhost:11434
LLM_MODEL=qwen3:14b                    # web ghi đè được ở Cài đặt AI
EMBED_MODEL=bge-m3                     # ★ KHÔNG ĐỔI
EMBED_DIM=1024                         # ★ phải khớp cột vector(1024)
OLLAMA_KEEP_ALIVE=30m

# Kho tài liệu
DATA_LIB=./data/raw                    # thư mục kho (bỏ trống = dùng DATA_RAW)
AUTO_LEARN_AUTO_APPROVE=0              # 0 = chờ người duyệt (khuyến nghị)
# DRIVE_FOLDER_ID=                     # ★ để TRỐNG — có giá trị là quay về chế độ Drive

# Đường dẫn dữ liệu
DATA_RAW=./data/raw
DATA_WORK=./data/work

# Bảo mật
JWT_SECRET=<64 ký tự ngẫu nhiên>       # đổi = mọi người phải đăng nhập lại
TOKEN_HOURS=12
CORS_ORIGINS=                          # ★ để trống với cài đặt một máy chủ
MAX_UPLOAD_MB=50
PUBLIC_RATE_MAX=30                     # câu hỏi/giờ/IP ở kênh công khai
```

### 14.2 Cổng và tên cố định

| Thứ | Giá trị |
|---|---|
| nginx | 80 / 443 |
| Backend | 127.0.0.1:8000 |
| PostgreSQL | 5432 (container `hds-postgres`, volume `hds-ai_pgdata`) |
| Ollama | 11434 |
| Cấu hình nginx | `/etc/nginx/sites-available/hds-ai` |
| Unit backend | `hds-ai-backend.service` |
| Unit quét kho | `hds-ai-quet-kho.service` + `.timer` |
| Unit lưu trữ | `hds-luu-tru.service` + `.timer` |

> Postgres đang mở cổng 5432 ra máy chủ. Nếu máy có IP công khai và chưa bật tường lửa, đây là một cổng CSDL nhìn thấy được từ Internet. Nên: `sudo ufw allow 80,443/tcp && sudo ufw enable`.

### 14.3 Tài liệu liên quan trong `deploy/`

| File | Nội dung |
|---|---|
| [HUONG_DAN_NHAN_VIEN.md](HUONG_DAN_NHAN_VIEN.md) | Sổ tay người dùng cuối |
| [CHUYEN_VE_LOCAL.md](CHUYEN_VE_LOCAL.md) | **Chuyển kho từ Drive về máy chủ** — quy trình một lần |
| [CAU_TRUC_DRIVE.md](CAU_TRUC_DRIVE.md) | **Cây thư mục kho chuẩn** (bản chính thức) |
| [LUU_TRU_DU_LIEU.md](LUU_TRU_DU_LIEU.md) | Dữ liệu nằm ở đâu, sơ đồ luồng, sao lưu |
| [TRAIN_DRIVE.md](TRAIN_DRIVE.md) | Ba đường nạp tài liệu *(mục 1a mô tả cây thư mục cũ — bỏ qua)* |
| [API_KHACH_HANG.md](API_KHACH_HANG.md) | Khoá API cho khách, ma trận gói dịch vụ |
| [NHAP_NHAN_SU.md](NHAP_NHAN_SU.md) | Nhập sổ nhân sự từ CSV/Excel |
| [README.md](README.md) | Ghi chú kỹ thuật chi tiết hơn |

### 14.4 Bàn giao — checklist cho người tiếp quản

- [ ] Truy cập SSH máy chủ + quyền sudo
- [ ] Bản chép `hds-ai/.env` cất nơi an toàn (`credentials/service-account.json`
      chỉ cần nếu còn giữ đường lui về Drive)
- [ ] Tài khoản admin trên web (đã đổi mật khẩu khỏi `admin123`)
- [ ] Biết thư mục kho nằm ở đâu (`DATA_LIB`) và ai quản trị ổ mạng Samba
- [ ] Tài khoản quản lý tên miền (bản ghi A)
- [ ] Biết bản sao lưu nằm ở đâu và **đã thử phục hồi ít nhất một lần**
- [ ] Đã chạy qua một lượt: `kiem-tra-vector.sh`, `kiem-tra-toc-do.sh`, `test_security`
- [ ] Đã đọc mục 13 (cấm kỵ)
