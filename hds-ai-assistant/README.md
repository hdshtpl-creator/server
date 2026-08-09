# HDS AI Assistant — Giao diện Trợ lý Pháp lý & Quản trị

Giao diện web cho hệ thống trợ lý AI pháp lý nội bộ của **Công ty Luật HDS**.
Đây là phần frontend; toàn bộ nghiệp vụ, phân quyền và RAG nằm ở backend FastAPI
trong thư mục [`../hds-ai`](../hds-ai).

## Yêu cầu

- Node.js 20 trở lên
- Backend `hds-ai` đang chạy tại `http://localhost:8000` (không bắt buộc — xem
  phần Chế độ giả lập bên dưới)

## Chạy ứng dụng

```bash
npm install
```

```bash
npm run dev
```

Ứng dụng chạy tại `http://localhost:3000`.

Các lệnh khác:

```bash
npm run build
```

```bash
npm run lint
```

## Kết nối backend

Mặc định frontend gọi `http://localhost:8000`. Đổi địa chỉ này trong hộp thoại
**Cấu hình kết nối** (biểu tượng máy chủ trên thanh tiêu đề).

Xác thực dùng **JWT**: sau khi `POST /auth/login` thành công, token được lưu vào
`localStorage` và tự đính kèm vào mọi request qua header
`Authorization: Bearer <token>`. Quyền hạn do backend đọc từ token, giao diện
không thể tự nâng quyền.

### Chế độ giả lập

Khi không kết nối được backend, ứng dụng tự chuyển sang dữ liệu mẫu và hiển thị
cảnh báo, đồng thời huy hiệu trên thanh tiêu đề đổi thành *Dữ liệu giả lập*.
Bạn cũng có thể bật/tắt thủ công trong hộp thoại Cấu hình kết nối. Chế độ này
chỉ để xem giao diện — mọi số liệu đều là dữ liệu mẫu.

### Tài khoản

Tài khoản do backend tạo bằng `python -m app.seed_accounts`. Màn hình đăng nhập
có nút điền nhanh email của các vai mẫu; **mật khẩu không được nhúng trong mã
nguồn** và phải lấy từ đầu ra của lệnh seed. Hãy đổi mật khẩu ngay sau lần đăng
nhập đầu tiên.

## Bí mật và cấu hình

Không có mật khẩu nào nằm trong mã nguồn. Mọi thành phần đọc bí mật từ biến môi
trường và **dừng lại kèm thông báo** nếu thiếu, thay vì âm thầm dùng một giá trị
mặc định mà bất kỳ ai đọc repo cũng biết:

| Biến | Nơi dùng | Khi thiếu |
| --- | --- | --- |
| `DB_PASS_ADMIN` | `backend/db.py`, `backup.sh`, `restore.sh`, `init_schema.sql` | Script thoát với mã lỗi; `db.py` cảnh báo và chuyển sang SQLite thử nghiệm |
| `DB_PASS_APP` | `backend/db.py`, `init_schema.sql` | Như trên |
| `JWT_SECRET` | `hds-ai/app/auth.py` | Đăng nhập báo lỗi ngay; cũng bị từ chối nếu ngắn hơn 32 ký tự hoặc còn là chuỗi mẫu |
| `DB_PASSWORD`, `APP_DB_PASSWORD` | `hds-ai/app/db.py`, `docker-compose.yml` | Kết nối báo lỗi; `docker compose up` dừng kèm thông báo |

Nạp cấu hình trước khi chạy các script backend:

```bash
cp .env.example .env && set -a && . ./.env && set +a
```

Sinh khoá JWT ngẫu nhiên:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

`.gitignore` chặn `.env`, `backups/`, `*.dump` và `__pycache__/`. Bản sao lưu
CSDL chứa mật khẩu vai PostgreSQL nên tuyệt đối không commit.

## Cấu trúc mã nguồn

| Đường dẫn | Vai trò |
| --- | --- |
| `src/api.js` | Toàn bộ lệnh gọi backend và dữ liệu giả lập. Nơi duy nhất biết về HTTP. |
| `src/api.ts` | Khai báo kiểu cho `api.js`. |
| `src/types.ts` | Hình dạng dữ liệu trao đổi với backend. |
| `src/constants.ts` | Enum dùng chung: loại tài liệu, mức truy cập, trạng thái vụ việc, vai người dùng. |
| `src/context/AppContext.tsx` | Phiên đăng nhập, hội thoại, chủ đề sáng/tối, thông báo. |
| `src/components/chat/` | Màn hình hội thoại: danh sách hội thoại, bong bóng tin nhắn, tải tài liệu. |
| `src/components/admin/` | 8 tab quản trị. |
| `src/components/auth/` | Đăng nhập và đổi mật khẩu. |
| `src/index.css` | Bảng màu thương hiệu HDS, biến thể chế độ tối, keyframes. |

### Khu vực quản trị

1. **Tổng quan** — số liệu hệ thống. Thẻ *Thiếu chủ sở hữu* tô đỏ khi khác 0.
2. **Hồ sơ khách 360°** — lịch sử, vấn đề tồn đọng, cảnh báo thời hiệu, gợi ý
   chiến lược, danh sách vụ việc và tài liệu.
3. **Tra cứu tài liệu** — danh mục toàn công ty, tự che tên hồ sơ ngoài phòng ban.
4. **Duyệt nhãn tài liệu** — gán loại, mức truy cập và khách hàng sở hữu.
5. **Duyệt hội thoại AI** — thẩm định câu trả lời trước khi nạp vào kho tri thức.
6. **Mẫu phương pháp** — quy trình phân tích chuẩn theo từng loại vụ việc.
7. **Kho tài liệu đã học** — tra cứu tri thức AI đã tiếp thu.
8. **Người dùng & Phòng ban** — chỉ vai `admin` mới thấy tab này.

## Ràng buộc dữ liệu cần lưu ý

Các giá trị dưới đây có ràng buộc `CHECK` trong `hds-ai/sql/schema.sql`. Gửi sai
sẽ bị backend từ chối, nên khi bổ sung tính năng hãy lấy từ `src/constants.ts`
thay vì viết chuỗi trực tiếp.

- `doc_type`: `law`, `ban_an`, `an_le`, `mau_hd`, `nhan_hieu`, `thu_mau`,
  `quy_trinh`, `ho_so_ns`, `ho_so_kh`, `advisory`, `filing`, `contract`, `other`
- `access_level`: `public`, `internal`, `client`
- `matters.status`: `tiep_nhan`, `dang_xu_ly`, `tam_dung`, `hoan_thanh`
- `users.role`: `admin`, `ban_qt`, `truong_bph`, `chuyen_vien`, `tro_ly`,
  `client_free`, `client_plus`, `client_pro`

Ngoài ra:

- `conversation_id`, `client_id`, `document_id` đều là **số nguyên**.
- Tài liệu `access_level = 'client'` bắt buộc có `client_id`.
- Tài khoản vai `client_*` bắt buộc gắn với một khách hàng.
- `POST /upload` yêu cầu `conversation_id`, nên chỉ tải tài liệu lên được sau khi
  đã gửi câu hỏi đầu tiên trong cuộc trò chuyện.

## Giao diện

Bảng màu lấy đúng theo bộ biến của giao diện quản trị gốc
(`hds-ai/app/admin_ui.py`) và khai báo lại thành token Tailwind trong
`src/index.css`:

| Token | Mã màu | Dùng cho |
| --- | --- | --- |
| `hds-navy` | `#1f3864` | Màu chủ đạo: thanh tiêu đề, nút chính |
| `hds-blue` | `#2e74b5` | Nhấn phụ, viền focus |
| `hds-soft` | `#f2f6fb` | Nền trang ở chế độ sáng |
| `hds-gold` | `#f9a825` | Điểm nhấn thương hiệu, tab đang chọn |
| `hds-red` | `#c00000` | Cảnh báo, lỗi |
| `hds-green` | `#2e7d32` | Thành công, đã duyệt |

Chế độ tối bật bằng class `dark` trên thẻ `<html>` (khai báo qua
`@custom-variant` trong `src/index.css`) và được ghi nhớ trong `localStorage`.
