# HDS INTEGRATION API v1 — CRM VÀ HỆ THỐNG NGOÀI

Tài liệu tham chiếu trong mã nguồn. Phiên bản 29/09/2026. Bản gửi đội CRM (Word,
24 endpoint có ví dụ): `HDS_Integration_API_v1.docx`.

> 29/09/2026: đổi toàn bộ API công khai sang tiếng Anh (chủ dự án: "cho chuyên
> nghiệp") trước khi CRM tích hợp. Đường cũ `/tich-hop/v1/*` đã bỏ; mã quyền cũ
> (`khach:doc`…) vẫn được hiểu và `schema.sql` tự đổi các khoá đã cấp.

## 0. Nguyên tắc

- **Máy chủ HDS là nơi lưu bản gốc DUY NHẤT** của hồ sơ khách, hợp đồng và hồ sơ
  nhân viên. **CRM chỉ là đầu cầu**: không giữ tệp, gọi API để gửi, liệt kê, tải
  về, xem phiên bản cũ và gỡ.
- Mọi tệp của một hồ sơ — kể cả tệp cũ không do CRM gửi — CRM xem và tải được.
  Bản cũ không bao giờ mất: gửi bản sửa / đổi tên / gỡ đều lưu bản trước.
- **Xoá phải đi qua API.** Chỉ xoá tệp trên đĩa thì trợ lý vẫn trả lời bằng nội
  dung đã học.
- **Duyệt:** tài liệu gửi sang **tự duyệt** (trợ lý dùng ngay) trừ khi máy đọc
  lỗi quá 20% chữ — khi đó `pending_review`, chờ người duyệt trên web.
- Đường dẫn, tên trường, giá trị trạng thái, mã quyền: **tiếng Anh**. Nội dung
  `detail` (lỗi) và `description`: tiếng Việt cho người dùng cuối đọc.

## 1. Kết nối và xác thực

| | |
|---|---|
| Base URL | `https://app.diginix.io.vn/api/integration/v1`; cùng máy chủ: `http://127.0.0.1:8000/integration/v1` |
| Khoá | `X-API-Key: hdsi_…` **hoặc** `Authorization: Bearer hdsi_…` |
| Ai cấp | Admin: **Quản trị → Khoá API & tích hợp → Cấp khoá mới**, bộ quyền *CRM* |
| Khoá hiện | **đúng một lần** lúc cấp; máy chủ chỉ giữ bản băm |
| Mất khoá | thu hồi rồi cấp khoá mới **cùng tên nguồn** (`crm`) — dữ liệu đã gửi vẫn nhận ra |
| Sửa quyền | nút **Sửa quyền** trên khoá đang dùng — chuỗi khoá không đổi |

| Permission | Cho phép |
|---|---|
| `clients:read` | Xem khách; cần có để thao tác tài liệu của khách |
| `clients:write` | Tạo khách, xin cấp mã |
| `employees:read` | Xem nhân viên; cần có để thao tác tài liệu của nhân viên |
| `employees:write` | Tạo / cập nhật nhân viên, xin cấp mã NV |
| `documents:read` | Liệt kê tệp, trạng thái, đối soát, tải tệp gốc và phiên bản cũ |
| `documents:write` | Gửi tài liệu, link `external_id` cho tệp cũ |
| `documents:delete` | Gỡ tài liệu |
| `chat` | Hỏi trợ lý (khoá riêng gắn một tài khoản khách, mục 5) |

Lỗi: `401` khoá sai/thu hồi (khoá `hds_…` của tài khoản khách cũng 401) · `403`
thiếu quyền (`detail` nêu tên quyền) · `404` không có mã · `400` dữ liệu sai ·
`409` `external_id` đã dùng cho tệp/hồ sơ khác · `410` tệp đã gỡ · `413`/`415`
tệp quá 50 MB / sai định dạng · `5xx` thử lại sau 1–5 phút (mọi thao tác gọi lặp
lại được).

## 2. Endpoint

| # | Method | Endpoint | Permission | Việc |
|---|---|---|---|---|
| 1 | GET | `/me` | — | Thử kết nối: `name`, `source`, `permissions`, `queued` |
| 2 | GET | `/clients?q=&external_id=&offset=&limit=` | `clients:read` | Danh sách / tìm khách (mã mới nhất trước, `limit` ≤500) |
| 3 | POST | `/clients` `{name, code?, external_id?}` | `clients:write` | Tạo khách; thiếu `code` → máy chủ cấp mã kế tiếp; trùng → `existed: true` |
| 4 | GET | `/clients/{code}` | `clients:read` | Một khách |
| 5 | GET | `/clients/{code}/files` | `clients:read` + `documents:read` | MỌI tệp trong hồ sơ (kể cả tệp cũ) |
| 6 | GET | `/clients/{code}/files/download?path=` | `clients:read` + `documents:read` | Tải một tệp theo `path` |
| 7 | POST | `/clients/{code}/documents` (multipart) | `clients:read` + `documents:write` | Gửi tệp / bộ hồ sơ |
| 8 | POST | `/clients/{code}/files/link` `{path, external_id, metadata?}` | `clients:read` + `documents:write` | Gắn `external_id` cho tệp cũ |
| 9 | GET | `/clients/{code}/documents?updated_since=` | `clients:read` + `documents:read` | Tài liệu có `external_id` của khách |
| 10–17 | | `/employees…` | `employees:*` | Như 2–9, thay `/clients/{code}` bằng `/employees/{code}` |
| 18 | GET | `/documents?client_code=&employee_code=&updated_since=` | `documents:read` | Đối soát (≤1000/trang) |
| 19 | GET | `/documents/{external_id}` | `documents:read` | Trạng thái |
| 20 | GET | `/documents/{external_id}/download` | `documents:read` | Tệp gốc bản đang dùng + `X-Checksum-MD5` |
| 21 | GET | `/documents/{external_id}/versions` | `documents:read` | Phiên bản đã lưu + bản hiện tại |
| 22 | GET | `/documents/{external_id}/versions/{version}/download` | `documents:read` | Tải một phiên bản |
| 23 | DELETE | `/documents/{external_id}` | `documents:delete` | Gỡ (bản cuối được lưu) |
| 24 | GET | `/documents/{external_id}/preview` | `documents:read` | Xem thẳng (inline): PDF/ảnh/văn bản nguyên bản, Word/Excel → PDF |
| 25 | GET | `/clients/{code}/files/preview?path=` | `clients:read` + `documents:read` | Như 24, theo `path` (tệp cũ chưa có mã) |
| 26 | GET | `/employees/{code}/files/preview?path=` | `employees:read` + `documents:read` | Như 25 cho nhân viên |
| 27 | POST | `/documents/{external_id}/view-link` `{mode?, expires_in?}` | `documents:read` | Link tạm cho TRÌNH DUYỆT mở thẳng (không cần khoá) |
| 28 | POST | `/clients/{code}/files/view-link` `{path, mode?, expires_in?}` | `clients:read` + `documents:read` | Như 27, theo `path` |
| 29 | POST | `/employees/{code}/files/view-link` `{path, mode?, expires_in?}` | `employees:read` + `documents:read` | Như 28 cho nhân viên |
| 30 | GET | `/view/{token}` | — (link là quyền) | Mở link tạm: xem inline hoặc tải về |
| 31 | POST | `/chat` `{question, conversation_id?}` | `chat` | Hỏi trợ lý |

Gửi tệp (7, 15) — `multipart/form-data`: `files` (lặp), `external_id` (lặp cùng
thứ tự; bỏ trống → `<code>__<tên tệp>`), `folder` (loại giấy tờ: `Hợp đồng`, `Thư
tư vấn`, `Hồ sơ nộp cơ quan`, `Bản án`, `Công nợ`…; tối đa 3 tầng), `metadata`
(JSON tự do). ≤50 tệp/lần, ≤50 MB/tệp. Không nhận ZIP/RAR.

Nhân viên (11) — `{full_name, code?, title?, status?, external_id?, folder?}`;
thiếu `code` → `NVxxxx`; `folder` = thư mục có sẵn để nhận về (danh sách ở
`unassigned_folders` của đường 10). `status`: `active`, `on_leave`, `inactive`,
`terminated`. Trợ lý đếm quân số theo danh sách nhân viên — **đăng ký đủ**.

## 2c. Xem thẳng trong trình duyệt (01/10/2026)

Mục tiêu: người dùng CRM bấm vào tệp là **xem ngay trong trang**, không phải tải
về; tải lên xong xem được luôn; sửa thì theo luồng tải về → sửa → gửi lại cùng
`external_id` (máy chủ giữ bản cũ).

- **Khoá `hdsi_` KHÔNG được xuống trình duyệt.** Máy chủ CRM xin **link tạm**
  (đường 27–29), trình duyệt mở link đó trực tiếp — nhúng `<iframe src=…>`,
  `<embed>` hoặc mở tab mới. Link ký bằng khoá bí mật máy chủ, gắn đúng một tệp
  + một chế độ (`preview` | `download`), hết hạn sau `expires_in` giây (60–3600,
  mặc định 600). Sửa một ký tự → 401; hết hạn → 410; khoá tạo link bị thu hồi hay
  bị bỏ quyền → link chết ngay.
- **Tải lên xong xem luôn:** kết quả gửi tệp (đường 7, 15) có sẵn `preview_url` +
  `preview_expires_at` cho mỗi tệp xem được.
- **Mở hồ sơ bất kỳ xem nhanh:** `GET /clients/{code}/files?with_links=true` trả
  `preview_url` + `download_url` cho TỪNG tệp (kể cả tệp cũ) trong một lời gọi.
- **Loại xem được:** PDF, PNG/JPG/WEBP, TXT/MD phát nguyên bản; DOCX/DOC/XLSX/CSV
  đổi sang PDF bằng LibreOffice một lần rồi giữ lại (tệp CRM gửi được đổi sẵn ngay
  sau khi học — mở lần đầu cũng nhanh; tệp cũ mở lần đầu chờ vài giây). Loại khác
  (ZIP, TIFF…) → `415`, xin link `mode=download`.
- Phản hồi có `Cache-Control: private, no-store` (Cloudflare / trình duyệt dùng
  chung không lưu bản sao), `X-Content-Type-Options: nosniff`; tệp khách không
  bao giờ phát dạng HTML. Mỗi lần mở được ghi nhật ký (`tich_hop_xem`).
- `PUBLIC_API_BASE` trong `.env` (tuỳ chọn) ép địa chỉ gốc của link; không đặt
  thì dựng `https://<tên miền>/api`.

```json
POST /integration/v1/documents/HD-2026-0001/view-link   {"expires_in": 300}
→ {"url":"https://app.diginix.io.vn/api/integration/v1/view/eyJ2Ijox…","mode":"preview",
   "expires_in":300,"expires_at":"2026-10-01T03:10:00+00:00"}
```

## 3. Giá trị trả về

| Trường | Giá trị |
|---|---|
| `status` (tài liệu) | `received` → `processing` → `learned` / `pending_review` / `failed`; `removed` |
| `status` (tệp, đường 5/13) | `learned`, `learned_with_warnings`, `pending_review`, `not_learned`, `failed`, `unsupported` |
| `result` (gửi / link / gỡ) | `created`, `new_version`, `unchanged`, `linked_existing_file`, `linked`, `already_linked`, `removed`, `already_removed` |
| `reason` (phiên bản) | `replaced`, `renamed`, `removed` |
| `owner_type` | `client`, `employee` |
| `path` | đường dẫn TRONG hồ sơ — dùng cho `/files/download` |
| `storage_path` | vị trí trong kho máy chủ (chỉ để tham khảo) |
| `unreadable_ratio` | 0–1, phần chữ máy không đọc được; >0,2 → `pending_review` |

Ví dụ trạng thái một tài liệu:

```json
{"external_id":"HD-2026-0001","owner_type":"client","client_code":"1729","employee_code":null,
 "status":"learned","description":"Đã học — trợ lý dùng được ngay","file_name":"HD-01-2026.pdf",
 "path":"Hợp đồng/HD-01-2026.pdf","storage_path":"9. HỒ SƠ KHÁCH HÀNG/1729. …/Hợp đồng/HD-01-2026.pdf",
 "md5":"9e107d…","document_id":51234,"title":"HD-01-2026","unreadable_ratio":0.012,
 "extraction_quality":"ready","error":null,"received_at":"…","updated_at":"…"}
```

## 4. Cơ chế phía máy chủ

- Tệp được đặt vào ĐÚNG thư mục hồ sơ trong kho (`9. HỒ SƠ KHÁCH HÀNG/<mã>. <tên>/`
  hoặc `8. HỒ SƠ NHÂN SỰ/<thư mục người>/`), danh tính `local:<đường dẫn>` như tệp
  thả tay — bộ quét 3 phút thấy "không đổi", không học lại. Ánh xạ
  (nguồn, `external_id`) ↔ tệp ở bảng `tich_hop_tai_lieu`.
- Học nền một luồng, giữ khoá `/tmp/hds-ai-quet-kho.lock` cùng cron quét kho.
  Máy chủ khởi động lại → tài liệu còn `received/processing` được xếp lại ở lời
  gọi API đầu tiên.
- Phiên bản: trước ghi đè / đổi tên / gỡ, bản hiện tại được CHÉP sang
  `data/_phien_ban/<nguồn>/<external_id>/<số>__<tên>` (ngoài kho), bảng
  `tich_hop_phien_ban`. `sao-luu.sh` sao lưu thư mục này cùng `data/_da_go`.
- Mã khách mới = mã số lớn nhất (CSDL ∪ tên thư mục trên đĩa) + 1. Mã có chữ →
  thư mục `[MÃ] Tên` (bộ quét chỉ tách được `số. Tên` hoặc `[MÃ] Tên`).
- Dịch tiếng Anh nằm GỌN ở `app/tich_hop_api.py` (`*_en`); lõi `app/tich_hop.py`
  và CSDL giữ tên tiếng Việt.

## 5. Hỏi đáp cho chatbot bên thứ ba

Khoá có quyền `chat` phải gắn **một tài khoản khách đại diện** lúc cấp. Câu hỏi
chạy như chính khách đó đăng nhập: cùng hạn mức, cùng chức năng, **chỉ thấy hồ sơ
của khách đó** (RLS). Hết hạn mức → `429`.

## 6. Kiểm thử thật 29/09/2026 (bản 28/09 trên máy chủ)

Khách thử `0999` ("KHÁCH THỬ NGHIỆM API (xoá được)"), gửi 1 DOCX + 1 PDF có lớp
chữ trong một lời gọi: nhận trong 0,9 giây, học xong sau 10–14 giây, tự duyệt
(rác 1% / 1,9%), loại `contract` theo thư mục, 3/3 câu hỏi thử tìm ra đúng tài
liệu ở vị trí số 1 trên kho ~106.000 tài liệu.

---

Mã nguồn: `hds-ai/app/tich_hop.py` (nghiệp vụ), `hds-ai/app/tich_hop_api.py`
(HTTP + dịch tiếng Anh), test `hds-ai/tests/test_tich_hop.py`.
