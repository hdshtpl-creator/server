# HƯỚNG DẪN CHẠY NHANH — CHUẨN BỊ DEMO (có đăng nhập JWT)

> **⚠️ TÀI LIỆU CŨ — chỉ đúng cho lần demo đầu tiên khi CHƯA có dữ liệu.**
> Giờ server đã chạy và có dữ liệu, hãy dùng bộ triển khai một lệnh ở
> [`../deploy/README.md`](../deploy/README.md) thay cho file này.
>
> **TUYỆT ĐỐI KHÔNG chạy `docker compose down -v` ở Mục 2** — lệnh đó **xoá sạch
> toàn bộ CSDL** (mọi tài liệu, hồ sơ khách, tài khoản). Chỉ dùng khi cố ý làm lại
> từ trắng.

Làm theo đúng thứ tự tối nay. Mỗi phiên SSH mới nhớ 2 lệnh đầu:
`cd ~/hds-ai && source .venv/bin/activate`

---

## 1. Cập nhật code mới (có JWT)

Chép `hds-ai-full.tar.gz` lên máy chủ, giải nén đè:

```bash
cd ~
tar xzf hds-ai-full.tar.gz          # đè lên thư mục hds-ai
cd ~/hds-ai
source .venv/bin/activate
```

Cài 2 thư viện mới (bcrypt, PyJWT):

```bash
pip install bcrypt==4.2.1 PyJWT==2.10.1
```

Thêm JWT_SECRET vào .env (nếu chưa có):

```bash
grep -q JWT_SECRET .env || echo "JWT_SECRET=$(openssl rand -hex 32)" >> .env
grep -q TOKEN_HOURS .env || echo "TOKEN_HOURS=12" >> .env
```

---

## 2. Tạo lại DB (vì schema có bảng/cột mới) + tài khoản demo

Chưa có dữ liệu thật nên tạo lại sạch:

```bash
docker compose down -v
docker compose up -d
sleep 8
docker exec hds-postgres psql -U hds -d hdsai -c "ALTER ROLE hds_app PASSWORD 'hds_app_pass';" 2>/dev/null
# đảm bảo .env khớp:
sed -i 's/^APP_DB_PASSWORD=.*/APP_DB_PASSWORD=hds_app_pass/' .env

bash scripts/10_init_db.sh          # nạp schema + phòng + ma trận quyền + TÀI KHOẢN DEMO
bash scripts/50_seed_demo.sh        # vài tài liệu mẫu
```

`10_init_db.sh` sẽ IN RA bảng tài khoản demo. Ghi lại. Mặc định:

| Email | Mật khẩu | Vai |
|---|---|---|
| admin@hdslaw.vn | admin123 | admin (kỹ thuật) |
| giamdoc@hdslaw.vn | demo123 | ban_qt (thấy tất cả) |
| truong.dndt@hdslaw.vn | demo123 | trưởng phòng DN-ĐT |
| cv.tranhtung@hdslaw.vn | demo123 | chuyên viên Tranh tụng |
| troly@hdslaw.vn | demo123 | trợ lý |

---

## 3. Kiểm tra + test bảo mật

```bash
bash scripts/99_healthcheck.sh
python -m tests.test_security       # phải "Toàn bộ ĐẠT"
```

Thử đăng nhập bằng lệnh (lấy token):

```bash
curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@hdslaw.vn","password":"admin123"}'
```

Ra `access_token` là đăng nhập chạy.

---

## 4. Chạy máy chủ

```bash
nohup uvicorn app.api:app --host 0.0.0.0 --port 8000 > logs/server.log 2>&1 &
```

Mở `/admin` (qua Tailscale nếu không cùng mạng): giờ có MÀN HÌNH ĐĂNG NHẬP.
Đăng nhập admin@hdslaw.vn / admin123.

---

## 5. Gắn frontend đẹp (AI Studio) — nếu đã build

```bash
# sau khi build ra dist/ ở ~/hds-web:
cp -r ~/hds-web/dist ~/hds-ai/webapp_dist
# (api.py đã tự phục vụ /app nếu có webapp_dist — nếu chưa, thêm đoạn StaticFiles như đã hướng dẫn)
pkill -f uvicorn; sleep 2
nohup uvicorn app.api:app --host 0.0.0.0 --port 8000 > logs/server.log 2>&1 &
```

Frontend gọi `/auth/login` rồi gửi `Authorization: Bearer <token>` — xem PROMPT_1 mục Đăng nhập.

---

## 6. SAU DEMO — đẩy tài liệu & train

**Đẩy tài liệu (tạm thời qua Drive hoặc chép tay):**
```bash
# chép file vào data/raw/ rồi:
python -m app.ingest data/raw law        # hoặc: contract / advisory / other
python -m app.classify                    # AI tự gán nhãn (chờ duyệt)
```
Rồi vào /admin → Duyệt tài liệu → gán đúng loại + phòng + khách → Duyệt.

**Train hồ sơ khách 360°:** /admin → Hồ sơ khách 360° → chọn khách → điền
lịch sử / vấn đề / cảnh báo / gợi ý → Lưu.

**Chat test:** /admin hoặc frontend → hỏi câu liên quan tài liệu vừa đẩy →
kiểm tra câu trả lời + nguồn trích dẫn.

---

## Lưu ý demo
- Đăng nhập bằng vai khác nhau để cho khách thấy phân quyền: giamdoc thấy tất cả,
  troly không thấy hồ sơ khách, chuyên viên chỉ thấy phòng mình.
- Nếu chạy chậm do qwen3:14b, câu đầu ~15s (nạp model), câu sau nhanh hơn.
- Đổi JWT_SECRET và mật khẩu demo TRƯỚC khi công khai ra internet.
