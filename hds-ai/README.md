# HDS AI — Bộ mã đầy đủ (Lớp 1 + Lớp 2)

Trợ lý AI local cho công ty luật: phân quyền theo BỘ PHẬN, hồ sơ khách 360°,
vụ việc (matter), tự học, 2 chế độ file, hạn mức khách, sẵn nền mở API.

---

## Chạy nhanh — theo thứ tự

> **Triển khai lên máy chủ (frontend + tên miền)?** Xem [`../deploy/README.md`](../deploy/README.md)
> — một lệnh `sudo bash deploy/setup.sh` dựng trọn gói. Phần dưới đây chỉ là cách
> chạy backend thủ công để phát triển.

```bash
cd hds-ai
bash scripts/00_preflight.sh      # kiểm tra máy (chỉ đọc)
bash scripts/01_setup.sh          # cài môi trường + PostgreSQL
nano .env                         # BẮT BUỘC đổi JWT_SECRET + mật khẩu CSDL (xem lưu ý dưới)
bash scripts/10_init_db.sh        # nạp schema + RLS + 4 bộ phận + ma trận quyền
bash scripts/50_seed_demo.sh      # dữ liệu mẫu
bash scripts/99_healthcheck.sh    # kiểm tra

python -m tests.test_security     # ⚠️ BẮT BUỘC — test cô lập khách + phòng
```

> **⚠️ Không còn "để mặc định lần đầu".** Mã đã siết bảo mật: `app/auth.py` từ chối
> khởi động nếu `JWT_SECRET` trống, dưới 32 ký tự, hoặc còn là chuỗi mẫu; `app/db.py`
> và `docker-compose.yml` từ chối nếu thiếu mật khẩu CSDL. Sinh khoá mạnh:
> ```bash
> sed -i "s/^JWT_SECRET=.*/JWT_SECRET=$(openssl rand -hex 32)/" .env
> sed -i "s/^DB_PASSWORD=.*/DB_PASSWORD=$(openssl rand -hex 24)/" .env
> sed -i "s/^APP_DB_PASSWORD=.*/APP_DB_PASSWORD=$(openssl rand -hex 24)/" .env
> ```
> Làm việc này **trước** `01_setup.sh` (lần đầu). Nếu CSDL đã tạo bằng mật khẩu cũ,
> đừng đổi `DB_PASSWORD`/`APP_DB_PASSWORD` thủ công — hãy để `deploy/setup.sh` lo,
> nó tự đồng bộ vai `hds_app` cho khớp.

Chạy máy chủ:

```bash
source .venv/bin/activate
uvicorn app.api:app --host 0.0.0.0 --port 8000
# http://localhost:8000/admin   (bảng quản trị)
# http://localhost:8000/docs    (thử API)
```

---

## Phân quyền — 6 vai nội bộ + 3 gói khách

| Vai | Mức RLS | Thấy gì |
|---|---|---|
| admin | internal + banqt | Quản trị kỹ thuật, thấy tất cả |
| ban_qt | internal + banqt | Thấy TẤT CẢ (Ban Quản trị: GĐ, Phó GĐ) |
| truong_bph | internal + phòng | Nội bộ + hồ sơ khách phòng mình |
| chuyen_vien | internal + phòng | Khách phòng mình, lọc theo loại tài liệu |
| tro_ly | internal + phòng | Nội bộ chung, KHÔNG hồ sơ khách |
| client_free/plus/pro | client | Chỉ hồ sơ của mình + hạn mức câu hỏi/tháng |

**Một người nhiều phòng:** gán qua bảng `user_departments` (Ngân, Nhi thuộc nhiều phòng).

**Quyền duyệt** là quyền riêng (`can_review`), admin cấp từng người — không phải cứ trưởng phòng là có.

**Cô lập dữ liệu** khóa ở tầng CSDL bằng RLS (`app.role`, `app.dept_ids`, `app.is_banqt`).
Khách A không thấy khách B; phòng 1 không thấy hồ sơ khách phòng 2. Dù code lỗi, CSDL vẫn chặn.

---

## Cách B — hiện tên che / khóa mở

Endpoint `/documents/browse` cho mọi nhân viên: thấy được có tài liệu tồn tại, nhưng
hồ sơ khách ngoài phòng bị CHE TÊN thành `[Hồ sơ KH - Phòng X] 🔒 chưa có quyền xem`
và không mở/tải được. Tài liệu nội bộ chung (luật, mẫu) hiện tên đầy đủ.

Ma trận quyền chi tiết (ai mở được loại nào) nằm ở bảng `access_rules` — đổi quyền chỉ
sửa dữ liệu, không sửa code. Nạp sẵn theo bảng nhân sự HDS trong `app/seed_departments.py`.

---

## Hồ sơ khách 360° (như thư ký vụ việc)

`GET /clients/{id}/360` trả về, gom theo khách:
- Tóm tắt lịch sử dịch vụ, vấn đề nổi bật, cảnh báo, gợi ý (admin train qua `/clients/{id}/profile`)
- Danh sách vụ việc (matters) và trạng thái
- Toàn bộ giấy tờ đã có — tải về được

Chỉ Ban QT hoặc người cùng phòng khách mới xem được. Xem ở tab "Hồ sơ khách 360°" trong dashboard.

---

## Vụ việc (matter)

Mỗi tài liệu/hồ sơ gắn vào một vụ việc của khách (bảng `matters`). Đây là nền cho
hồ sơ 360° và cho Lớp 3 sau này (thời hiệu, timeline, án lệ).

---

## Hai chế độ file & tự học

- **temp (dùng xong bỏ):** `POST /upload {mode:"temp"}` → tự xóa sau 6h, không vào kho.
- **save:** `POST /upload {mode:"save"}` → vào hàng chờ duyệt.
- **Học câu trả lời hay:** dashboard → Duyệt hội thoại → "Đạt".
- **Học cách phân tích:** dashboard → Mẫu phương pháp. Hỏi kèm `use_method:true`.

---

## Hạn mức khách

Gói khách có `monthly_quota`. Hỏi quá → API trả 429 "hết lượt". Đặt khi tạo user
(trường `monthly_quota`).

---

## Cấu trúc

```
hds-ai/
├── sql/schema.sql            Toàn bộ bảng + RLS theo phòng  ← đọc kỹ
├── app/
│   ├── db.py                 Kết nối + set app.role/dept_ids/is_banqt
│   ├── models.py             Qwen + bge-m3 + tóm tắt
│   ├── rag.py                RAG chung 3 kênh + mask + client_360
│   ├── ingest.py             Đọc → OCR → đoạn → vector (có department)
│   ├── classify.py           AI tự gán nhãn (chờ duyệt)
│   ├── backfill_summaries.py Tóm tắt cho tài liệu nạp trước
│   ├── seed_departments.py   4 phòng + ma trận quyền (bảng khách)
│   ├── drive_sync.py         Đồng bộ Google Drive
│   ├── api.py                FastAPI: chat, upload, duyệt, học, 360°, phòng, người dùng
│   ├── admin_ui.py           Web quản trị (7 tab)
│   └── cli.py                Hỏi đáp thử
├── scripts/                  00 → 99
└── tests/test_security.py    8 nhóm test (khách + phòng)
```

---

## Model AI — có thể nâng cấp

Đang chạy qwen3:8b (~6GB). Card 16GB dư sức lên `qwen3:14b` (~10GB, thông minh hơn):

```bash
ollama pull qwen3:14b
# sửa .env: LLM_MODEL=qwen3:14b
```

Không đổi code. GPU chỉ nạp model khi có câu hỏi rồi nhả sau ~5 phút — thấy VRAM "rảnh" là bình thường.

---

## Đăng nhập (JWT)

Đã có đăng nhập thật: mật khẩu mã hóa bcrypt + token JWT.

```
POST /auth/login {email,password} → {access_token,user}
Mọi request sau đó: header  Authorization: Bearer <token>
POST /auth/change-password {old_password,new_password}
GET  /auth/me
```

`10_init_db.sh` tự tạo tài khoản demo (in ra email + mật khẩu). Đăng nhập ở `/admin`.
`JWT_SECRET` phải là chuỗi ngẫu nhiên dài — mã đã **bắt buộc** (xem lưu ý ở phần đầu).

## ⚠️ Trước khi công khai ra internet

- **HTTPS + Nginx + giao diện React**: đã có sẵn bộ triển khai một lệnh ở
  [`../deploy/`](../deploy/README.md) (nginx phục vụ frontend + proxy `/api`, tự cấp
  Let's Encrypt cho tên miền). Không phải dựng tay nữa.
- **Rate limit theo gói**: khách đã có `monthly_quota` (429 khi hết lượt).
- Đổi mật khẩu các tài khoản demo (`admin123` / `demo123`) trước khi mở ra ngoài.

---

## Lớp 3 (giai đoạn kế tiếp — theo app.jpg)

Chưa làm ở bản này, thêm sau khi lõi chạy ổn (không đụng phân quyền nhạy cảm):
quản lý thời hiệu & deadline + cảnh báo, kho án lệ/bản án, timeline vụ việc,
soạn thảo theo 8 chặng tố tụng.

---

## Nguyên tắc không được vi phạm

1. Phân quyền bằng RLS ở CSDL, không filter quyền trong Python.
2. RAG viết chung 1 lần cho 3 kênh.
3. Hồ sơ khách thiếu client_id → CSDL chặn.
4. App kết nối bằng `hds_app` (bị RLS ràng buộc), không dùng `hds`.
5. `python -m tests.test_security` phải đạt 100% (gồm cô lập theo phòng) trước khi bàn giao.
