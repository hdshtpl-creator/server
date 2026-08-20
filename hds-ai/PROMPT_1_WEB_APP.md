# PROMPT 1 — LÀM WEB APP (chat + quản trị) CHO HDS AI — bản Lớp 1+2

> Cách dùng: copy toàn bộ, dán vào công cụ lập trình AI (Claude Code, Cursor, v0, Bolt)
> hoặc khung chat Claude/ChatGPT. Backend đã chạy sẵn tại http://localhost:8000.

---

Bạn là lập trình viên frontend. Xây web app **React + Vite + TailwindCSS** làm giao diện
cho trợ lý AI nội bộ của công ty luật HDS. Backend FastAPI đã có sẵn ở `http://localhost:8000`.
Bạn CHỈ làm frontend, gọi API có sẵn. KHÔNG tự chế API mới.

## Đăng nhập (JWT) — làm phần này TRƯỚC
- Màn hình đăng nhập: email + mật khẩu → gọi `POST /auth/login {email,password}`.
  Nhận về `{access_token, user:{id,role,full_name}}`. Lưu token (trong React state hoặc
  memory; KHÔNG bắt buộc localStorage). Sai thì báo "Sai email hoặc mật khẩu".
- Sau đăng nhập, MỌI request gửi kèm header `Authorization: Bearer <access_token>`.
- Nếu API trả 401 → token hết hạn → đưa về màn hình đăng nhập.
- Có nút Đăng xuất (xóa token). Có thể gọi `GET /auth/me` để lấy thông tin user hiện tại.
- Tùy vai (`user.role`): admin/ban_qt/truong_bph/chuyen_vien/tro_ly thấy giao diện nội bộ;
  ẩn các nút quản trị nếu vai không phải admin (nhưng backend vẫn tự chặn 403 nếu gọi sai).

## Phân quyền — 6 vai nội bộ
admin, ban_qt (Ban Quản trị — thấy tất cả), truong_bph (trưởng phòng), chuyen_vien,
tro_ly, và khách ngoài client_free/plus/pro. Một người có thể thuộc nhiều phòng.

## A. Giao diện Chat (mọi nhân viên nội bộ)
- Bố cục kiểu ChatGPT: cột trái danh sách cuộc trò chuyện, giữa khung chat.
- Câu trả lời AI kèm "Nguồn tham khảo" (trường `sources`: tên tài liệu + điểm liên quan).
- Tải file trong chat, 2 chế độ rõ ràng: "Dùng xong bỏ" (mode=temp) và "Lưu vào kho" (mode=save).
  Sau khi tải temp, hỏi tiếp gửi kèm `use_temp:true`.
- Công tắc "Áp dụng mẫu phân tích" → gửi `use_method:true`.

## B. Web app Quản trị (chỉ admin và người được cấp quyền duyệt)
Trang `/admin` với các tab:
1. **Tổng quan** — số liệu từ `GET /stats`. Thẻ `thieu_chu_so_huu` tô ĐỎ nếu > 0.
   Có thêm: so_khach, vu_viec_dang_mo, so_bo_phan.
2. **Duyệt tài liệu** — `GET /review/pending`, duyệt qua `POST /review/{id}/approve`.
3. **Duyệt hội thoại** — `GET /learn/pending`, `POST /learn/{message_id}`.
4. **Mẫu phương pháp** — `GET/POST /methods`.
5. **Tài liệu đã học** — `GET /documents` (bảng: tên, loại, tóm tắt, ngày). Tìm + lọc loại.
6. **Hồ sơ khách 360°** — chọn khách từ `GET /clients`, xem `GET /clients/{id}/360`:
   hiển thị 4 khối (lịch sử, vấn đề, cảnh báo, gợi ý) + bảng vụ việc + bảng giấy tờ tải về.
   Cho phép admin cập nhật (train) 4 khối qua `POST /clients/{id}/profile`.
7. **Người dùng** — `GET /users`, tạo qua `POST /users` (chọn vai + nhập ID phòng),
   cấp/thu quyền duyệt qua `POST /users/{uid}/review-permission?grant=true|false`.

## C. Duyệt danh sách tài liệu có CHE TÊN (Cách B) — quan trọng
Màn hình cho nhân viên xem toàn bộ tài liệu qua `GET /documents/browse`:
- Trả về mỗi tài liệu có `title` (đã che sẵn nếu ngoài quyền), `can_open` (true/false), `department`.
- Nếu `can_open=false`: hiện tên dạng khóa `[Hồ sơ KH - Phòng X] 🔒 chưa có quyền xem`,
  nút Mở/Tải bị vô hiệu. Backend đã che tên sẵn — frontend chỉ hiển thị đúng và khóa nút.

## Danh sách API có sẵn
(mọi request sau khi đăng nhập gửi kèm header `Authorization: Bearer <token>`)

```
POST /auth/login          body:{email,password} → {access_token,user}
GET  /auth/me             → thông tin user hiện tại
POST /auth/change-password body:{old_password,new_password}

POST /chat/internal   body:{question,conversation_id?,use_temp?,use_method?}
                      → {answer,sources[],conversation_id,latency_ms}
POST /chat/portal     (khách) — có thể trả 429 nếu hết hạn mức tháng
POST /upload          body:{conversation_id,filename,content,mode:"temp"|"save"}

GET  /stats           → {tai_lieu,da_duyet_nhan,cho_duyet_nhan,thieu_chu_so_huu,so_doan,
                         hoi_thoai_cho_duyet,da_hoc,so_mau_phuong_phap,so_khach,vu_viec_dang_mo,so_bo_phan}

GET  /review/pending              
POST /review/{id}/approve           body:{doc_type,access_level,client_id?}
GET  /learn/pending               
POST /learn/{message_id}            body:{action:"approve"|"edit"|"reject",edited_content?,edit_reason?}
GET  /methods                     
POST /methods                       body:{case_type,steps}

GET  /documents?q=&doc_type=        (admin/duyệt) danh sách kèm tóm tắt
GET  /documents/browse?q=           (mọi nhân viên) danh sách CHE TÊN + can_open

GET  /clients                       → [{id,name,code,department}]
GET  /clients/{id}/360              → {client,profile:{history,issues,warnings,suggestions},
                                        matters[],documents[]}
POST /clients/{id}/profile          body:{history_note?,issues_note?,warnings?,suggestions?}
GET  /departments                   → [{id,code,name}]

GET  /users                       
POST /users                         body:{email,full_name,role,can_review,client_id?,
                                          department_ids:[int],head_of:[int],monthly_quota}
POST /users/{uid}/review-permission?grant=true
```

## Yêu cầu kỹ thuật
- React + Vite + TailwindCSS. Gói mọi API vào `src/api.js`, tự thêm header Authorization: Bearer token.
- Lỗi 403 → "Không đủ quyền"; 401 → "Chưa đăng nhập"; 429 → "Hết lượt hỏi trong tháng".
- Tiếng Việt, màu chủ đạo xanh navy (#1f3864). File gọn, kèm README (`npm install`, `npm run dev`).
- KHÔNG tự chế API. KHÔNG tự làm mật khẩu. Trình bày rõ 2 chế độ file và cơ chế che tên (Cách B).

Bắt đầu bằng cấu trúc thư mục, rồi `src/api.js`, rồi từng component.
