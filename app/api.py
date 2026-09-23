"""
api.py — Máy chủ API cho toàn hệ thống.

Nhóm đường dẫn:
  /chat/*     — 3 kênh chat (public/internal/portal); mode=legal_review +
                template_doc_id cho tab "Kiểm tra pháp lý & tạo file mẫu"
  /conversations — tạo hội thoại trống (tải hồ sơ trước, hỏi sau)
  /upload/*   — tải file trong chat: lưu / dùng-xong-bỏ / trích-xuất-máy-chủ
  /review/*   — duyệt nhãn tài liệu (chỉ người có can_review)
  /learn/*    — duyệt hội thoại đưa vào kho (tự học)
  /methods/*  — dạy AI cách phân tích (mẫu phương pháp)
  /drafts/*   — soạn tài liệu có nguồn, version, duyệt và xuất DOCX/Markdown
  /files/*    — tải lên kho, tải bản gốc về, XEM TRƯỚC trong trình duyệt
  /templates/* + /template-fills/* — kệ file mẫu và file đã điền chủ thể
  /bo-mau/*   — bộ mẫu hồ sơ (nhóm .docx mẫu, AI điền cả bộ từ chat)
  /users/*    — quản lý người dùng và quyền (chỉ admin)
  /stats,/health

Chạy: uvicorn app.api:app --host 0.0.0.0 --port 8000 --reload
Giao diện: /admin (web app quản trị)

Xác thực: đăng nhập JWT.
  POST /auth/login {email,password} -> access_token
  Mọi request gửi kèm header: Authorization: Bearer <token>
"""
import json
import os
import re
import threading
import time
import uuid
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Header, HTTPException, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, FileResponse, Response, StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app import company_context, db, kho, rag, auth, settings, van_ban
from app import dkkd_extract, quyen_tinh_nang, ra_soat_rui_ro, so_sanh
from app.admin_ui import ADMIN_HTML

app = FastAPI(title="HDS AI", version="1.0")

# CORS chỉ cần khi giao diện chạy ở origin KHÁC backend (ví dụ frontend trên
# Vercel gọi sang API). Khi deploy chung một máy chủ (nginx proxy /api cùng
# origin) thì để trống CORS_ORIGINS — trình duyệt coi là cùng nguồn, không cần
# CORS. Nhiều origin ngăn cách bằng dấu phẩy.
#
# Web ĐKKD (DKKD_ALLOWED_ORIGINS) gọi /dkkd/extract từ một origin khác nên tự
# động được cộng vào đây — admin khai một chỗ, không phải nhớ khai hai lần
# (quên là trình duyệt chặn ngay ở preflight, endpoint không bao giờ được gọi).
_cors_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
_cors_origins += [o for o in dkkd_extract.ALLOWED_ORIGINS if o not in _cors_origins]
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

bearer = HTTPBearer(auto_error=False)


def _user_by_api_key(raw_key: str):
    """Tra người dùng từ khoá API. CSDL chỉ giữ bản băm nên so bằng bản băm."""
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, role FROM users WHERE api_key_hash=%s AND active",
                        (auth.hash_api_key(raw_key),))
            row = cur.fetchone()
    if not row:
        raise HTTPException(401, "Khoá API không hợp lệ hoặc đã bị thu hồi")
    # Khoá API là loại bí mật sống lâu, dán vào script rồi để đó. Chỉ mở cho vai
    # khách — không để một khoá lọt ra ngoài là mở được toàn bộ dữ liệu nội bộ.
    if row[1] not in CLIENT_ROLES:
        raise HTTPException(403, "Khoá API chỉ dùng cho tài khoản khách hàng")
    return get_user(row[0])


def current_user(cred: HTTPAuthorizationCredentials = Depends(bearer),
                 x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    """Nhận diện người gọi bằng MỘT trong hai cách:

    · Web app: header `Authorization: Bearer <token JWT>` sau khi đăng nhập.
    · Khách tích hợp hệ thống: header `X-API-Key: hds_...` (không hết hạn,
      admin cấp và thu hồi được, chỉ dùng cho vai khách).

    Cả hai đường đều đi qua get_user() nên phạm vi dữ liệu giống nhau —
    phân quyền vẫn do RLS quyết định, không phụ thuộc cách xác thực.
    """
    if x_api_key:
        return _user_by_api_key(x_api_key)
    if cred is None:
        raise HTTPException(401, "Chưa đăng nhập")
    payload = auth.decode_token(cred.credentials)
    if not payload:
        raise HTTPException(401, "Phiên đăng nhập hết hạn hoặc không hợp lệ")
    return get_user(int(payload["sub"]))

INTERNAL_ROLES = {"admin", "ban_qt", "truong_bph", "chuyen_vien", "tro_ly"}
CLIENT_ROLES = {"client_free", "client_plus", "client_pro"}
SEE_ALL = {"admin", "ban_qt"}


def get_user(user_id):
    if user_id is None:
        return {"id": None, "role": "public", "client_id": None, "can_review": False,
                "dept_ids": [], "dept_codes": [], "is_banqt": False,
                "can_finance": False}
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            # Sang kỳ mới thì hoàn lại hạn mức trước khi đọc. Thiếu bước này thì
            # used_this_month chỉ có tăng, khách dùng hết lượt một tháng sẽ bị
            # chặn vĩnh viễn chứ không mở lại tháng sau.
            cur.execute("""UPDATE users
                              SET used_this_month = 0,
                                  quota_reset_at =
                                    (date_trunc('month', now()) + interval '1 month')::date
                            WHERE id=%s AND quota_reset_at <= current_date""",
                        (user_id,))
            cur.execute("""SELECT u.id,u.role,u.client_id,u.can_review,u.full_name,
                           u.monthly_quota,u.used_this_month,u.can_view_finance,
                           u.features, c.name, c.code,
                           coalesce(u.must_change_password, false)
                           FROM users u LEFT JOIN clients c ON c.id=u.client_id
                           WHERE u.id=%s AND u.active""", (user_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(401, "Người dùng không tồn tại hoặc bị khóa")
            # Lấy cả mã phòng: bảng access_rules khoá theo department_code
            cur.execute("""SELECT ud.department_id, d.code
                             FROM user_departments ud
                             JOIN departments d ON d.id = ud.department_id
                            WHERE ud.user_id=%s""", (user_id,))
            dept_rows = cur.fetchall()
            dept_ids = [r[0] for r in dept_rows]
            dept_codes = [r[1] for r in dept_rows]
    return {"id": row[0], "role": row[1], "client_id": row[2], "can_review": row[3],
            "name": row[4], "monthly_quota": row[5], "used_this_month": row[6],
            "dept_ids": dept_ids, "dept_codes": dept_codes,
            "is_banqt": row[1] in SEE_ALL,
            # Quyền xem công nợ: admin luôn có (là người đi cấp quyền), còn lại
            # phải được cấp từng người. Ban QT KHÔNG tự động có.
            "can_finance": row[1] == "admin" or bool(row[7]),
            # Chức năng đã bật cho tài khoản này (20/09/2026). Tính MỘT LẦN ở
            # đây để mọi chốt phía sau chỉ việc tra dict, không hỏi lại CSDL.
            "features": quyen_tinh_nang.quyen_hieu_luc(row[1], row[8]),
            # Tài khoản khách thuộc hồ sơ khách nào — trước 20/09/2026 không
            # chỗ nào trả ra, nên nhìn màn hình không biết tài khoản của ai.
            "client_name": row[9], "client_code": row[10],
            # Đang dùng mật khẩu tạm do quản trị cấp — phải đổi trước khi làm việc.
            "must_change_password": bool(row[11])}


def _can_tinh_nang(user, ten: str):
    """Chặn khi chức năng chưa được bật cho tài khoản này."""
    if not quyen_tinh_nang.co_quyen(user, ten):
        nhan = quyen_tinh_nang.TINH_NANG.get(ten, {}).get("ten", ten)
        raise HTTPException(403, f"Tài khoản của bạn chưa được mở chức năng: {nhan}. "
                                 "Liên hệ luật sư phụ trách của HDS.")


def require(user, roles):
    if user["role"] not in roles:
        raise HTTPException(403, "Không đủ quyền")


def require_reviewer(user):
    # Chỉ admin, hoặc người được cấp can_review, mới được duyệt
    if user["role"] != "admin" and not user["can_review"]:
        raise HTTPException(403, "Chỉ admin hoặc người được cấp quyền duyệt mới thực hiện được")


def _conv_title(question: str) -> str:
    """Tiêu đề hội thoại đặt từ câu hỏi đầu (kiểu ChatGPT)."""
    t = " ".join((question or "").split())[:60].strip()
    return t or "Cuộc trò chuyện mới"


def _resolve_conv(user, body, channel, cid=None):
    """Mã hội thoại cho lượt hỏi: nối tiếp id client gửi (đã kiểm chủ sở hữu),
    hoặc TẠO HỘI THOẠI MỚI kèm tiêu đề nếu chưa có id — mô hình nhiều hội thoại
    như ChatGPT (mỗi 'cuộc trò chuyện mới' là một conversation riêng)."""
    if body.conversation_id:
        conv = check_conversation(user, body.conversation_id, channel)
        _title_first_question(conv, body.question)
        return conv
    return rag.start_conversation(user["id"], channel, cid, title=_conv_title(body.question))


def _title_first_question(conversation_id, question):
    """Đặt tiêu đề cho hội thoại RỖNG bằng câu hỏi đầu tiên.

    Cần từ khi giao diện tạo hội thoại TRƯỚC (kéo file vào là có chip ngay,
    chưa gõ câu nào): hội thoại lúc đó chỉ có tên tạm dạng mốc giờ. Không đặt
    lại thì cột lịch sử toàn dòng "Cuộc trò chuyện 29/08 14:32" giống hệt
    nhau, không nhận ra cuộc nào là cuộc nào. Chỉ đụng khi CHƯA có tin nhắn
    nào — hội thoại đang chạy dở, hoặc người dùng đã tự đổi tên, phải giữ
    nguyên. Và chỉ với kind='chat': phiên Kiểm tra pháp lý cố ý mang tên theo
    mốc giờ để phân biệt chục hồ sơ soát trong cùng một ngày."""
    title = _conv_title(question)
    try:
        with db.session(role="internal", admin=True) as conn:
            with conn.cursor() as cur:
                cur.execute("""UPDATE conversations SET title=%s
                                WHERE id=%s AND kind='chat'
                                  AND NOT EXISTS (SELECT 1 FROM messages
                                                   WHERE conversation_id=%s)""",
                            (title, conversation_id, conversation_id))
    except Exception:  # noqa: BLE001 — đặt tên đẹp không đáng để hỏng cả lượt hỏi
        pass


def check_conversation(user, conversation_id, channel):
    """Xác nhận cuộc trao đổi này thuộc về người đang hỏi.

    BẮT BUỘC gọi trước khi dùng conversation_id do client gửi lên. Bảng
    conversations/messages/temp_files KHÔNG có Row-Level Security, nên nếu bỏ
    bước này thì người dùng chỉ cần đổi conversation_id trong request là đọc
    được lịch sử hội thoại và file tạm của người khác — cả hai đều được đưa vào
    ngữ cảnh sinh câu trả lời.
    """
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id, channel, client_id FROM conversations WHERE id=%s",
                        (conversation_id,))
            row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Cuộc trao đổi không tồn tại")
    owner_id, conv_channel, conv_client = row
    if conv_channel != channel:
        raise HTTPException(403, "Cuộc trao đổi này thuộc kênh khác")
    if channel == "public":
        # Kênh công khai không đăng nhập nên không có chủ sở hữu để đối chiếu;
        # chỉ cho phép nối tiếp đúng các cuộc trao đổi công khai vô danh.
        if owner_id is not None:
            raise HTTPException(403, "Cuộc trao đổi này không thuộc kênh công khai")
    else:
        if owner_id != user["id"]:
            raise HTTPException(403, "Cuộc trao đổi này không thuộc về bạn")
        if channel == "portal" and conv_client != user["client_id"]:
            raise HTTPException(403, "Cuộc trao đổi này thuộc khách hàng khác")
    return conversation_id


# ---------- 1. CHAT ----------
# ---------- 0. ĐĂNG NHẬP ----------
class LoginIn(BaseModel):
    email: str
    password: str


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# Băm của một chuỗi ngẫu nhiên, chỉ để verify_password vẫn tốn thời gian như
# thật khi email không tồn tại — kẻ dò không phân biệt được "sai email" với
# "sai mật khẩu" qua thời gian phản hồi.
_DUMMY_HASH = auth.hash_password(auth.new_temp_password())


def _chuan_hoa_email(email: str) -> str:
    """Email là khoá đăng nhập: bỏ khoảng trắng, hạ chữ thường, kiểm tra dạng.

    Trước 22/09/2026 tạo tài khoản lưu nguyên văn và đăng nhập so khớp đúng
    từng ký tự — quản trị gõ "An.Nguyen@" lúc tạo, nhân viên gõ "an.nguyen@"
    lúc đăng nhập là "sai email hoặc mật khẩu" mà không ai hiểu vì sao."""
    e = (email or "").strip().lower()
    if not _EMAIL_RE.match(e) or len(e) > 254:
        raise HTTPException(422, "Email không đúng định dạng")
    return e


@app.post("/auth/login")
def login(body: LoginIn, request: Request):
    # Van chống dò mật khẩu theo IP: đưa vào vận hành thật thì trang đăng nhập
    # là cửa ngoài cùng, không van là một script thử vài nghìn mật khẩu/phút.
    _login_rate_check(request)
    email = (body.email or "").strip().lower()
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT id, role, password_hash, full_name, active,
                                  coalesce(must_change_password, false)
                             FROM users WHERE lower(email)=%s""", (email,))
            row = cur.fetchone()
    if not row or not row[4]:
        auth.verify_password(body.password, _DUMMY_HASH)
        raise HTTPException(401, "Sai email hoặc mật khẩu")
    uid, role, phash, name, _, phai_doi = row
    if not auth.verify_password(body.password, phash):
        raise HTTPException(401, "Sai email hoặc mật khẩu")
    token = auth.make_token(uid, role)
    try:
        with db.session(role="internal", admin=True) as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE users SET last_login_at=now() WHERE id=%s", (uid,))
    except Exception:  # noqa: BLE001 — ghi mốc đăng nhập hỏng không được chặn đăng nhập
        pass
    return {"access_token": token, "token_type": "bearer",
            "user": {"id": uid, "role": role, "full_name": name,
                     "must_change_password": bool(phai_doi)}}


@app.get("/auth/me")
def whoami(user=Depends(current_user)):
    return {"id": user["id"], "role": user["role"], "name": user.get("name"),
            "can_review": user["can_review"], "is_banqt": user["is_banqt"],
            "can_finance": user["can_finance"], "dept_ids": user["dept_ids"],
            # Đang dùng mật khẩu tạm (vừa tạo / vừa được đặt lại): giao diện
            # bắt đổi trước khi cho làm việc. Backend không chặn các API khác
            # theo cờ này — tài khoản vẫn là của đúng người, chỉ mật khẩu là
            # thứ quản trị viên cũng biết.
            "must_change_password": bool(user.get("must_change_password")),
            # Tài khoản khách cần biết mình đang đại diện hồ sơ khách nào —
            # giao diện in lên đầu trang để người dùng (và người ngồi cạnh)
            # thấy ngay đang mở cổng của ai.
            "client_id": user.get("client_id"),
            "client_name": user.get("client_name"),
            "client_code": user.get("client_code"),
            # Chức năng đã mở: giao diện ẩn/hiện tab theo đây, backend vẫn
            # chặn lại lần nữa ở từng cửa.
            "features": user.get("features") or {},
            "monthly_quota": user.get("monthly_quota"),
            "used_this_month": user.get("used_this_month")}


class ChangePwIn(BaseModel):
    old_password: str
    new_password: str


@app.post("/auth/change-password")
def change_password(body: ChangePwIn, user=Depends(current_user)):
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT password_hash, email FROM users WHERE id=%s", (user["id"],))
            phash, email = cur.fetchone()
            if not auth.verify_password(body.old_password, phash):
                raise HTTPException(400, "Mật khẩu cũ không đúng")
            loi = auth.kiem_tra_mat_khau_moi(body.new_password, cu=body.old_password,
                                             email=email)
            if loi:
                raise HTTPException(400, loi)
            # Đổi xong là hết "mật khẩu tạm": bỏ cờ bắt đổi.
            cur.execute("""UPDATE users SET password_hash=%s, must_change_password=false
                            WHERE id=%s""",
                        (auth.hash_password(body.new_password), user["id"]))
        db.audit(conn, user["id"], "change_password", "users", user["id"], {})
    return {"ok": True}


class ChatIn(BaseModel):
    question: str
    conversation_id: int | None = None
    use_temp: bool = False       # dùng file 'dùng xong bỏ' đã tải trong chat
    use_method: bool = False     # áp mẫu phương pháp phân tích
    model: str | None = None     # '' = mặc định máy chủ | 'auto' | tên model cụ thể
    source_document_ids: list[int] | None = None  # bộ nguồn người dùng chủ động chọn
    # Tab "Kiểm tra pháp lý & tạo file mẫu" (chỉ kênh nội bộ):
    mode: str | None = None            # None | 'legal_review'
    template_doc_id: int | None = None  # điền chủ thể vào file mẫu này
    # "Tạo bộ file": AI tự lên danh sách file cần soạn (biên bản nghiệm thu,
    # giấy đề nghị thanh toán…) từ hồ sơ đính kèm; mẫu là template_doc_id
    # (nếu chọn) hoặc file .docx đã tải lên hội thoại.
    make_files: bool = False
    # BỘ MẪU HỒ SƠ (15/09/2026): bộ .docx mẫu đang chọn dưới khung chat. Chỉ
    # lượt là LỆNH tạo file (make_files hoặc câu "tạo bộ hồ sơ…") mới điền dữ
    # liệu vào TỪNG file của bộ; câu hỏi thường vẫn đi RAG. bo_mau_file_ids
    # thu hẹp về vài file trong bộ (mặc định cả bộ).
    bo_mau_id: int | None = None
    bo_mau_file_ids: list[int] | None = None


_CHAT_MODES = {None, "", "legal_review", "template_check"}


def _chat_bo_mau(body: ChatIn, internal: bool) -> tuple[int | None, list[int] | None]:
    """Validate bộ mẫu sớm (trước khi mở SSE); vai khách bị hạ về None như
    template_doc_id — câu hỏi thường của khách vẫn chạy."""
    bo_id = getattr(body, "bo_mau_id", None)
    if bo_id is None or not internal:
        return None, None
    if isinstance(bo_id, bool) or not isinstance(bo_id, int) or bo_id <= 0:
        raise HTTPException(422, "bo_mau_id phải là số nguyên dương")
    raw_ids = getattr(body, "bo_mau_file_ids", None)
    if raw_ids is None:
        return bo_id, None
    ids, seen = [], set()
    for value in raw_ids:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise HTTPException(422, "bo_mau_file_ids chỉ nhận số nguyên dương")
        if value not in seen:
            seen.add(value)
            ids.append(value)
    return bo_id, (ids or None)


def _chat_mode(body: ChatIn, internal: bool) -> str | None:
    """Chế độ đặc biệt của khung chat — chỉ nhân viên nội bộ được dùng."""
    if body.mode not in _CHAT_MODES:
        raise HTTPException(422, "mode chỉ nhận 'legal_review' hoặc 'template_check'")
    mode = body.mode or None
    return mode if internal else None


def _chat_template_id(body: ChatIn, internal: bool) -> int | None:
    if body.template_doc_id is None:
        return None
    if not internal:
        return None
    if isinstance(body.template_doc_id, bool) or body.template_doc_id <= 0:
        raise HTTPException(422, "template_doc_id phải là số nguyên dương")
    return body.template_doc_id


def _chat_make_files(body: ChatIn, internal: bool) -> bool:
    return bool(body.make_files) and internal


def _chat_source_ids(body: ChatIn) -> list[int] | None:
    """Validate sớm trước khi mở SSE; RAG vẫn chịu trách nhiệm lọc theo quyền/RLS."""
    if body.source_document_ids is None:
        return None
    ids = []
    seen = set()
    for value in body.source_document_ids:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise HTTPException(422, "source_document_ids chỉ nhận số nguyên dương")
        if value not in seen:
            seen.add(value)
            ids.append(value)
    if len(ids) > 50:
        raise HTTPException(422, "Chỉ được chọn tối đa 50 tài liệu nguồn")
    return ids


# ---- Van bảo vệ kênh CÔNG KHAI (người dân, không đăng nhập) -----------------
# Mỗi câu hỏi tốn hàng chục giây LLM trên máy CPU; không có van thì MỘT người
# spam là nghẽn cả hệ thống cho mọi người khác. Đếm theo IP bằng cửa sổ trượt
# trong bộ nhớ — đủ cho một tiến trình uvicorn; chạy nhiều worker thì mỗi
# worker một quota (nới hơn cấu hình, vẫn chặn được spam thô).
PUBLIC_RATE_MAX = int(os.getenv("PUBLIC_RATE_MAX", "30"))          # câu hỏi / cửa sổ / IP
PUBLIC_RATE_WINDOW_SEC = int(os.getenv("PUBLIC_RATE_WINDOW_SEC", "3600"))
MAX_PUBLIC_QUESTION_CHARS = int(os.getenv("MAX_PUBLIC_QUESTION_CHARS", "2000"))
MAX_QUESTION_CHARS = int(os.getenv("MAX_QUESTION_CHARS", "20000"))
_public_hits: dict = {}
_public_hits_lock = threading.Lock()


def _client_ip(request: Request) -> str:
    forwarded = (request.headers.get("x-forwarded-for") or "").strip()
    if forwarded:
        # nginx đặt IP thật ở đầu danh sách; các proxy sau chỉ nối thêm.
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _rate_check(hits_store: dict, lock: threading.Lock, ip: str,
                max_hits: int, window_sec: int, message: str):
    """Cửa sổ trượt theo IP dùng chung cho mọi van công khai. max_hits <= 0 = tắt."""
    if max_hits <= 0:
        return
    now = time.monotonic()
    with lock:
        hits = [t for t in hits_store.get(ip, []) if now - t < window_sec]
        if len(hits) >= max_hits:
            raise HTTPException(429, message)
        hits.append(now)
        hits_store[ip] = hits
        # Dọn IP nguội để dict không phình vô hạn theo thời gian chạy.
        if len(hits_store) > 10_000:
            for stale in [k for k, v in hits_store.items()
                          if not v or now - v[-1] >= window_sec]:
                hits_store.pop(stale, None)


# Van cho trang đăng nhập (22/09/2026): 10 lượt / 5 phút mỗi IP là dư cho
# người gõ nhầm vài lần, nhưng chặn đứng script dò mật khẩu. Đặt 0 để tắt.
LOGIN_RATE_MAX = int(os.getenv("LOGIN_RATE_MAX", "10"))
LOGIN_RATE_WINDOW_SEC = int(os.getenv("LOGIN_RATE_WINDOW_SEC", "300"))
_login_hits: dict = {}
_login_hits_lock = threading.Lock()


def _login_rate_check(request: Request):
    _rate_check(_login_hits, _login_hits_lock, _client_ip(request),
                LOGIN_RATE_MAX, LOGIN_RATE_WINDOW_SEC,
                "Đăng nhập sai quá nhiều lần. Vui lòng đợi vài phút rồi thử "
                "lại, hoặc liên hệ quản trị viên để được đặt lại mật khẩu.")


def _public_rate_check(request: Request):
    _rate_check(_public_hits, _public_hits_lock, _client_ip(request),
                PUBLIC_RATE_MAX, PUBLIC_RATE_WINDOW_SEC,
                "Bạn đã hỏi quá nhiều trong thời gian ngắn. Vui lòng quay "
                "lại sau, hoặc liên hệ trực tiếp luật sư của HDS.")


# Van riêng cho đọc giấy tờ ĐKKD: mỗi lượt là một lần nạp + chạy model thị giác
# trên GPU, nặng hơn một câu chat. Một khách điền hồ sơ thường gửi 2–8 ảnh
# (mỗi thành viên hai mặt CCCD) nên 40 lượt / 15 phút là rộng cho người thật.
DKKD_RATE_MAX = int(os.getenv("DKKD_RATE_MAX", "40"))
DKKD_RATE_WINDOW_SEC = int(os.getenv("DKKD_RATE_WINDOW_SEC", "900"))
_dkkd_hits: dict = {}
_dkkd_hits_lock = threading.Lock()


def _dkkd_rate_check(request: Request):
    _rate_check(_dkkd_hits, _dkkd_hits_lock, _client_ip(request),
                DKKD_RATE_MAX, DKKD_RATE_WINDOW_SEC,
                "Bạn đã gửi quá nhiều ảnh trong thời gian ngắn. Vui lòng đợi "
                "ít phút rồi thử lại, hoặc nhập tay các trường.")


def _clean_question(body: ChatIn, public: bool = False) -> str:
    question = (body.question or "").strip()
    if not question:
        raise HTTPException(422, "Câu hỏi không được để trống")
    cap = MAX_PUBLIC_QUESTION_CHARS if public else MAX_QUESTION_CHARS
    if len(question) > cap:
        raise HTTPException(413, f"Câu hỏi dài quá giới hạn {cap:,} ký tự")
    return question


@app.post("/chat/public")
def chat_public(body: ChatIn, request: Request):
    question = _clean_question(body, public=True)
    _public_rate_check(request)
    source_ids = _chat_source_ids(body)
    conv = (check_conversation(None, body.conversation_id, "public")
            if body.conversation_id else rag.start_conversation(None, "public"))
    res = rag.answer(question, "public", conversation_id=conv,
                     source_document_ids=source_ids)
    res["conversation_id"] = conv
    return res


@app.post("/chat/internal")
def chat_internal(body: ChatIn, user=Depends(current_user)):
    require(user, INTERNAL_ROLES)
    question = _clean_question(body)
    source_ids = _chat_source_ids(body)
    bo_mau_id, bo_mau_file_ids = _chat_bo_mau(body, internal=True)
    conv = _resolve_conv(user, body, "internal")
    res = rag.answer(question, "internal", user_id=user["id"], conversation_id=conv,
                     use_temp=body.use_temp, use_method=body.use_method,
                     dept_ids=user["dept_ids"], is_banqt=user["is_banqt"],
                     can_finance=user["can_finance"], model=body.model,
                     source_document_ids=source_ids,
                     mode=_chat_mode(body, internal=True),
                     template_doc_id=_chat_template_id(body, internal=True),
                     make_files=_chat_make_files(body, internal=True),
                     bo_mau_id=bo_mau_id, bo_mau_file_ids=bo_mau_file_ids,
                     # role + dept_codes: kênh internal không dùng cho tier,
                     # nhưng luồng điền mẫu cần chúng để soi ma trận access_rules.
                     role=user["role"], dept_codes=user["dept_codes"])
    res["conversation_id"] = conv
    return res


@app.post("/chat/portal")
def chat_portal(body: ChatIn, user=Depends(current_user)):
    require(user, CLIENT_ROLES)
    _can_tinh_nang(user, "chat")
    question = _clean_question(body)
    source_ids = _chat_source_ids(body)
    # Hạn mức câu hỏi/tháng theo gói
    quota = user.get("monthly_quota") or 0
    used = user.get("used_this_month") or 0
    if quota > 0 and used >= quota:
        raise HTTPException(429, f"Đã hết lượt hỏi trong tháng ({used}/{quota}). "
                                 f"Nâng cấp gói để hỏi thêm.")
    cid = user["client_id"]
    conv = _resolve_conv(user, body, "portal", cid)
    res = rag.answer(question, "portal", user_id=user["id"], client_id=cid,
                     conversation_id=conv, use_temp=body.use_temp,
                     role=user["role"], source_document_ids=source_ids)
    # Tăng bộ đếm đã dùng
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET used_this_month=used_this_month+1 WHERE id=%s", (user["id"],))
    res["quota"] = {"used": used + 1, "limit": quota}
    res["conversation_id"] = conv
    return res


def _sse(payload: dict) -> str:
    """Một sự kiện Server-Sent Events. Hai dấu xuống dòng là dấu hết sự kiện."""
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


@app.post("/chat/stream")
def chat_stream(body: ChatIn, user=Depends(current_user)):
    """Trả lời THEO DÒNG cho cả nhân viên nội bộ lẫn khách đã đăng nhập.

    Vì sao cần: máy chủ chạy CPU mất hàng chục giây mới viết xong câu trả lời.
    Trả một cục thì người dùng nhìn màn hình trống suốt quãng đó, và nếu quá 100
    giây thì Cloudflare cắt kết nối (lỗi 524). Trả theo dòng đẩy được byte đầu
    tiên đi ngay khi model đọc xong ngữ cảnh — hết 524, và người dùng đọc được
    phần đầu trong lúc phần sau đang viết.

    Toàn bộ phần chuẩn bị ngữ cảnh và phân quyền dùng chung với /chat/internal
    và /chat/portal qua rag.prepare — không có bản sao thứ hai để lệch nhau.
    """
    require(user, INTERNAL_ROLES | CLIENT_ROLES)
    _can_tinh_nang(user, "chat")
    question = _clean_question(body)
    source_ids = _chat_source_ids(body)
    is_client = user["role"] in CLIENT_ROLES
    if body.use_temp:
        _can_tinh_nang(user, "dinh_kem")
    chat_mode = _chat_mode(body, internal=not is_client)
    template_doc_id = _chat_template_id(body, internal=not is_client)
    make_files = _chat_make_files(body, internal=not is_client)
    bo_mau_id, bo_mau_file_ids = _chat_bo_mau(body, internal=not is_client)

    if is_client:
        quota = user.get("monthly_quota") or 0
        used = user.get("used_this_month") or 0
        if quota > 0 and used >= quota:
            raise HTTPException(429, f"Đã hết lượt hỏi trong tháng ({used}/{quota}). "
                                     f"Nâng cấp gói để hỏi thêm.")
        channel, cid = "portal", user["client_id"]
    else:
        channel, cid = "internal", None

    # Kiểm quyền hội thoại TRƯỚC khi mở dòng: lỗi ở đây phải là mã HTTP thật,
    # không phải một sự kiện lỗi lọt vào giữa dòng dữ liệu. Không có id thì đây
    # là "cuộc trò chuyện mới" → tạo conversation riêng kèm tiêu đề.
    conv = _resolve_conv(user, body, channel, cid)

    def events():
        yield _sse({"type": "start", "conversation_id": conv})

        # NHỊP TIM chống lỗi 524 khi máy chậm.
        #
        # Cái bẫy: sau sự kiện 'meta' (nguồn trích dẫn), model bước vào giai đoạn
        # ĐỌC toàn bộ prompt. Trên máy CPU việc này mất cả trăm giây, và trong
        # suốt quãng đó KHÔNG có byte nào chảy ra. Cloudflare thấy kết nối im quá
        # ~100 giây liền cắt → 'network error', trước cả khi chữ đầu tiên xuất
        # hiện. Chỉ gửi 'meta' sớm là chưa đủ — khoảng lặng nằm ở SAU 'meta'.
        #
        # Cách chữa: chạy phần sinh câu trả lời trong một luồng riêng, đẩy sự
        # kiện qua hàng đợi; luồng chính chờ tối đa HEARTBEAT_SEC giây, hết giờ
        # mà chưa có gì thì phát một dòng chú thích SSE (': hb'). Byte đó vô hình
        # với trình duyệt nhưng đủ để Cloudflare coi kết nối vẫn sống.
        import queue as _queue
        import threading

        HEARTBEAT_SEC = 15
        q: "_queue.Queue" = _queue.Queue()
        DONE = object()
        # Cờ HUỶ: bật khi trình duyệt đóng kết nối — người dùng bấm "Dừng",
        # đóng tab, hoặc rớt mạng. Luồng sinh chữ chạy trong thread riêng nên
        # nó KHÔNG tự biết khách đã đi; không có cờ này thì model cứ viết nốt
        # câu trả lời không ai đọc, giữ CPU của máy chạy 14b và chặn luôn câu
        # hỏi kế tiếp.
        cancel = threading.Event()

        def on_status(label):
            # Mốc tiến trình phát TRONG lúc prepare chạy (tìm kho, đọc file
            # mẫu…) — đẩy thẳng vào hàng đợi để người dùng thấy hệ thống đang
            # làm gì thay vì màn hình im lặng hàng chục giây.
            q.put(("event", {"type": "status", "label": str(label)[:300]}))

        def produce():
            try:
                for ev in rag.answer_stream(
                        question, channel, user_id=user["id"], client_id=cid,
                        conversation_id=conv, use_temp=body.use_temp,
                        use_method=body.use_method and not is_client,
                        dept_ids=user["dept_ids"], is_banqt=user["is_banqt"],
                        can_finance=user["can_finance"],
                        # role luôn truyền: portal dùng cho tier gói dịch vụ,
                        # internal dùng cho ma trận access_rules của luồng
                        # điền mẫu (kèm dept_codes).
                        role=user["role"],
                        dept_codes=user["dept_codes"],
                        model=None if is_client else body.model,
                        source_document_ids=source_ids,
                        mode=chat_mode, template_doc_id=template_doc_id,
                        make_files=make_files, on_status=on_status,
                        cancel=cancel, bo_mau_id=bo_mau_id,
                        bo_mau_file_ids=bo_mau_file_ids):
                    q.put(("event", ev))
            except Exception as e:  # noqa: BLE001 - báo lỗi qua dòng, không để luồng chết câm
                q.put(("error", str(e)))
            finally:
                q.put((DONE, None))

        worker = threading.Thread(target=produce, daemon=True)
        worker.start()

        try:
            while True:
                try:
                    kind, payload = q.get(timeout=HEARTBEAT_SEC)
                except _queue.Empty:
                    yield ": hb\n\n"      # đang đọc tài liệu — giữ kết nối sống
                    continue
                if kind is DONE:
                    break
                if kind == "error":
                    yield _sse({"type": "error", "message": payload})
                    continue
                ev = payload
                if ev.get("type") == "done" and is_client:
                    with db.session(role="internal", admin=True) as conn:
                        with conn.cursor() as cur:
                            cur.execute("UPDATE users SET used_this_month=used_this_month+1 "
                                        "WHERE id=%s", (user["id"],))
                    ev["quota"] = {"used": (user.get("used_this_month") or 0) + 1,
                                   "limit": user.get("monthly_quota") or 0}
                yield _sse(ev)
        finally:
            # Trình duyệt đóng kết nối → Starlette đóng generator này → lệnh
            # yield ở trên ném GeneratorExit và ta rơi vào đây. Bật cờ để luồng
            # sinh chữ dừng ở mẩu kế tiếp. Chạy hết bình thường cũng vào đây,
            # lúc đó worker đã xong nên cờ vô hại.
            cancel.set()

    return StreamingResponse(events(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        # Bảo nginx đừng gom phản hồi rồi mới gửi — gom là mất sạch tác dụng.
        "X-Accel-Buffering": "no",
    })


def _user_channel(user):
    """Kênh của người đang đăng nhập (nhân viên → internal, khách → portal)."""
    return "portal" if user["role"] in CLIENT_ROLES else "internal"


def _message_evidence(value):
    """psycopg thường giải mã JSONB sẵn; vẫn chịu được driver trả chuỗi JSON."""
    if value is None:
        return []
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return []
    return value


@app.get("/conversations")
def conversations_list(user=Depends(current_user), limit: int = 100,
                       kind: str = "chat"):
    """Danh sách hội thoại của người đang đăng nhập, mới hoạt động xếp trước —
    để dựng cột 'cuộc trò chuyện' bên trái (mô hình ChatGPT).

    kind: 'chat' (tab Hội thoại AI — mặc định) | 'legal' (tab Kiểm tra pháp
    lý) | 'all'. Tách để phiên kiểm tra hồ sơ không lẫn vào cột hội thoại
    thường và ngược lại — mỗi tab thấy đúng lịch sử của mình."""
    require(user, INTERNAL_ROLES | CLIENT_ROLES)
    if kind not in ("chat", "legal", "all"):
        raise HTTPException(400, "kind chỉ nhận 'chat', 'legal' hoặc 'all'")
    channel = _user_channel(user)
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT c.id, c.title, c.started_at,
                                  coalesce(max(m.created_at), c.started_at) AS last_at,
                                  count(m.id) AS n
                             FROM conversations c
                             LEFT JOIN messages m ON m.conversation_id = c.id
                            WHERE c.user_id=%s AND c.channel=%s
                              AND (%s = 'all' OR c.kind = %s)
                            GROUP BY c.id
                            ORDER BY last_at DESC
                            LIMIT %s""",
                        (user["id"], channel, kind, kind, limit))
            rows = cur.fetchall()
    return [{"id": r[0], "title": r[1] or "Cuộc trò chuyện",
             "updated_at": str(r[3]), "message_count": r[4]} for r in rows]


class ConvPatch(BaseModel):
    title: str


@app.patch("/conversations/{conv_id}")
def conversation_rename(conv_id: int, body: ConvPatch, user=Depends(current_user)):
    """Đổi tên một hội thoại (chỉ chủ sở hữu)."""
    require(user, INTERNAL_ROLES | CLIENT_ROLES)
    check_conversation(user, conv_id, _user_channel(user))
    title = " ".join((body.title or "").split())[:120].strip() or "Cuộc trò chuyện"
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE conversations SET title=%s WHERE id=%s", (title, conv_id))
    return {"ok": True, "id": conv_id, "title": title}


@app.delete("/conversations/{conv_id}")
def conversation_delete(conv_id: int, user=Depends(current_user)):
    """Xoá một hội thoại và toàn bộ tin nhắn của nó (messages có ON DELETE CASCADE)."""
    require(user, INTERNAL_ROLES | CLIENT_ROLES)
    check_conversation(user, conv_id, _user_channel(user))
    # Bản .docx gốc của file đính kèm nằm NGOÀI Postgres (data/work/chat_uploads)
    # — CASCADE chỉ xoá bản ghi, không unlink hộ. Lấy đường dẫn TRƯỚC khi xoá,
    # không thì hồ sơ mật của khách thành file mồ côi nằm lại vô hạn.
    kept_paths = rag.conversation_temp_paths(conv_id)
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM conversations WHERE id=%s", (conv_id,))
        db.audit(conn, user["id"], "delete_conversation", "conversations", conv_id, {})
    for p in kept_paths:
        try:
            path = Path(p)
            path.unlink(missing_ok=True)
            if path.parent.exists() and not any(path.parent.iterdir()):
                path.parent.rmdir()
        except OSError:
            continue
    return {"ok": True, "id": conv_id}


@app.get("/chat/history")
def chat_history(user=Depends(current_user), conversation_id: int | None = None,
                 limit: int = 300):
    """Tin nhắn của MỘT hội thoại cụ thể. Không truyền conversation_id thì trả
    hội thoại mới hoạt động gần nhất (mở app là thấy lại chỗ đang dở)."""
    require(user, INTERNAL_ROLES | CLIENT_ROLES)
    limit = max(1, min(limit, 1000))
    channel = _user_channel(user)
    if conversation_id:
        conv = check_conversation(user, conversation_id, channel)
    else:
        with db.session(role="internal", admin=True) as conn:
            with conn.cursor() as cur:
                # Chỉ xét hội thoại THƯỜNG: mở app mà nhảy vào một phiên Kiểm
                # tra pháp lý (vì nó mới hoạt động nhất) là người dùng thấy
                # cột chat trái trống trơn nhưng khung giữa đầy hồ sơ khách.
                cur.execute("""SELECT c.id FROM conversations c
                                LEFT JOIN messages m ON m.conversation_id=c.id
                               WHERE c.user_id=%s AND c.channel=%s
                                 AND c.kind='chat'
                               GROUP BY c.id
                               ORDER BY coalesce(max(m.created_at), c.started_at) DESC
                               LIMIT 1""", (user["id"], channel))
                row = cur.fetchone()
        conv = row[0] if row else None
    if not conv:
        return {"conversation_id": None, "messages": []}
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT id, role, content, created_at, sources, evidence,
                                  answer_mode, grounding_status
                             FROM messages
                            WHERE conversation_id=%s ORDER BY id DESC LIMIT %s""",
                        (conv, limit))
            rows = cur.fetchall()
    msgs = [{"id": r[0], "role": r[1], "content": r[2], "created_at": str(r[3]),
             "sources": _message_evidence(r[5]) if r[5] is not None else _message_evidence(r[4]),
             "evidence": _message_evidence(r[5]),
             "answer_mode": r[6], "grounding_status": r[7]}
            for r in reversed(rows)]
    return {"conversation_id": conv, "messages": msgs}


@app.get("/chat/search")
def chat_search(q: str, user=Depends(current_user), limit: int = 40):
    """Tìm trong TẤT CẢ hội thoại của chính người đang đăng nhập. Trả kèm
    conversation_id để giao diện mở đúng hội thoại rồi nhảy tới đoạn."""
    require(user, INTERNAL_ROLES | CLIENT_ROLES)
    q = (q or "").strip()
    if len(q) < 2:
        return []
    channel = _user_channel(user)
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            # Chỉ hội thoại THƯỜNG: ô tìm kiếm nằm ở cột trái tab Hội thoại
            # AI — trả hit từ phiên Kiểm tra pháp lý là bấm vào mở ra một
            # hội thoại không có trong cột, lượt hỏi tiếp rơi vào phiên đó
            # mà người dùng không thấy đâu.
            cur.execute("""SELECT m.id, m.role, m.content, m.created_at,
                                  m.conversation_id, c.title
                             FROM messages m JOIN conversations c ON c.id=m.conversation_id
                            WHERE c.user_id=%s AND c.channel=%s AND c.kind='chat'
                              AND m.content ILIKE %s
                            ORDER BY m.id DESC LIMIT %s""",
                        (user["id"], channel, f"%{q}%", limit))
            rows = cur.fetchall()
    return [{"id": r[0], "role": r[1], "content": r[2], "created_at": str(r[3]),
             "conversation_id": r[4], "conversation_title": r[5] or "Cuộc trò chuyện"}
            for r in rows]


class NoteIn(BaseModel):
    content: str
    source_message_id: int | None = None


@app.get("/notes")
def notes_list(user=Depends(current_user), limit: int = 100):
    """Ghi chú cá nhân của người đang đăng nhập."""
    require(user, INTERNAL_ROLES | CLIENT_ROLES)
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT id, content, source_message_id, created_at FROM notes
                            WHERE user_id=%s ORDER BY created_at DESC LIMIT %s""",
                        (user["id"], limit))
            rows = cur.fetchall()
    return [{"id": r[0], "content": r[1], "source_message_id": r[2],
             "created_at": str(r[3])[:16]} for r in rows]


@app.post("/notes")
def notes_add(body: NoteIn, user=Depends(current_user)):
    require(user, INTERNAL_ROLES | CLIENT_ROLES)
    content = (body.content or "").strip()
    if not content:
        raise HTTPException(400, "Ghi chú không được để trống")
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO notes (user_id, content, source_message_id)
                           VALUES (%s,%s,%s) RETURNING id, created_at""",
                        (user["id"], content[:4000], body.source_message_id))
            nid, created = cur.fetchone()
    return {"ok": True, "id": nid, "content": content[:4000],
            "source_message_id": body.source_message_id, "created_at": str(created)[:16]}


@app.delete("/notes/{note_id}")
def notes_delete(note_id: int, user=Depends(current_user)):
    require(user, INTERNAL_ROLES | CLIENT_ROLES)
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            # Chỉ xoá ghi chú của chính mình
            cur.execute("DELETE FROM notes WHERE id=%s AND user_id=%s", (note_id, user["id"]))
            deleted = cur.rowcount
    if not deleted:
        raise HTTPException(404, "Không thấy ghi chú của bạn")
    return {"ok": True, "id": note_id}


# ---------- 1b. TẠO HỘI THOẠI TRỐNG ----------
@app.post("/conversations")
def conversation_create(user=Depends(current_user), kind: str = "legal"):
    """Tạo hội thoại nội bộ TRƯỚC câu hỏi đầu tiên.

    Vì sao cần: file đính kèm phải gắn vào một conversation_id có thật, nên
    luồng cũ bắt người dùng hỏi một câu trước rồi mới tải file được. Cả hai tab
    giờ đều làm ngược lại — kéo hồ sơ vào trước, hỏi sau — nên cho tạo hội
    thoại rỗng ngay khi cần.

    `kind` quyết định hội thoại này hiện ở cột lịch sử NÀO ('chat' = tab Hội
    thoại AI, 'legal' = tab Kiểm tra pháp lý; GET /conversations lọc theo đúng
    cột này). Mặc định để 'legal' là CÓ CHỦ ĐÍCH: bản giao diện cũ còn nằm
    trong cache trình duyệt gọi endpoint này không kèm tham số và chỉ tab Kiểm
    tra pháp lý dùng nó — mặc định 'chat' sẽ ném phiên kiểm tra hồ sơ của họ
    sang nhầm cột cho tới khi trình duyệt nạp lại bản mới."""
    require(user, INTERNAL_ROLES)
    if kind not in ("chat", "legal"):
        raise HTTPException(400, "kind chỉ nhận 'chat' hoặc 'legal'")
    # Gắn mốc thời gian vào tiêu đề: một người kiểm tra chục hồ sơ một ngày,
    # danh sách hội thoại toàn dòng giống hệt nhau thì không mở lại đúng
    # phiên nào được. Hội thoại thường sẽ được backend đổi tên theo câu hỏi
    # đầu tiên, nên mốc này chỉ là tên tạm cho phiên chưa hỏi gì.
    from zoneinfo import ZoneInfo
    stamp = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).strftime("%d/%m %H:%M")
    prefix = "Kiểm tra pháp lý" if kind == "legal" else "Cuộc trò chuyện"
    conv = rag.start_conversation(user["id"], "internal", None,
                                  title=f"{prefix} {stamp}",
                                  kind=kind)
    return {"conversation_id": conv, "kind": kind}


# ---------- 2. UPLOAD FILE TRONG CHAT ----------
class UploadIn(BaseModel):
    conversation_id: int
    filename: str
    content: str                 # văn bản đã trích sẵn (hoặc text thô)
    mode: str = "temp"           # 'temp' = dùng xong bỏ | 'save' = lưu vào kho


@app.post("/upload")
def upload_in_chat(body: UploadIn, user=Depends(current_user)):
    require(user, INTERNAL_ROLES | CLIENT_ROLES)
    _can_tinh_nang(user, "dinh_kem")
    if body.mode == "temp":
        # File tạm gắn vào cuộc trao đổi và sẽ được đọc lại làm ngữ cảnh —
        # phải chắc cuộc trao đổi là của chính người này.
        check_conversation(user, body.conversation_id, "internal")
        n, temp_id = rag.add_temp_file(body.conversation_id, user["id"],
                                       body.filename, body.content)
        return {"ok": True, "mode": "temp", "chunks": n, "temp_file_id": temp_id,
                "note": "File dùng xong bỏ — tự xóa sau 6 giờ, không vào kho."}
    # mode == 'save' → vào hàng chờ duyệt
    from app.ingest import split_document
    from app.models import embed
    pieces = split_document(body.content, "other")
    vecs = embed(pieces) if pieces else []
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO documents (title,doc_type,access_level,source_kind,
                           uploaded_by,approved,label_verified)
                           VALUES (%s,'other','internal','chat',%s,false,false) RETURNING id""",
                        (body.filename, user["id"]))
            doc_id = cur.fetchone()[0]
            for i, (pc, v) in enumerate(zip(pieces, vecs)):
                cur.execute("""INSERT INTO chunks (document_id,chunk_index,content,access_level,doc_type,embedding)
                               VALUES (%s,%s,%s,'internal','other',%s)""",
                            (doc_id, i, pc, json.dumps(v)))
        db.audit(conn, user["id"], "upload_save", "documents", doc_id, {"file": body.filename})
    return {"ok": True, "mode": "save", "document_id": doc_id,
            "note": "Đã vào hàng chờ duyệt. Duyệt xong mới thành tri thức lâu dài."}


@app.get("/upload/formats")
def upload_formats(user=Depends(current_user)):
    """Danh sách đuôi file đính kèm được — để giao diện KHÔNG phải chép tay
    một bản thứ hai rồi lệch với máy chủ (chép tay là cảnh file bị hộp thoại
    chặn dù máy chủ đọc được, hoặc ngược lại)."""
    require(user, INTERNAL_ROLES)
    from app.ingest import ATTACHMENT_EXTENSIONS
    return {"extensions": sorted(ATTACHMENT_EXTENSIONS), "max_mb": MAX_UPLOAD_MB}


@app.post("/upload/extract")
async def upload_extract(conversation_id: int = Form(...),
                         file: UploadFile = File(...),
                         user=Depends(current_user)):
    """Đính kèm file vào hội thoại — MỌI định dạng bộ đọc kham nổi.

    Đây là đường đính kèm DUY NHẤT của cả hai tab chat: người dùng kéo file
    vào, MÁY CHỦ trích văn bản + OCR bằng đúng bộ đọc của kho, bot đọc rồi trả
    lời. File chỉ nằm trong thư mục tạm lúc trích, KHÔNG vào kho tri thức,
    không cần duyệt, tự xoá sau 6 giờ.

    (POST /upload vẫn còn cho các client cũ tự đọc text ở trình duyệt nên chỉ
    kham được .txt/.md/.csv — giao diện hiện tại không dùng nữa.)"""
    import tempfile

    require(user, INTERNAL_ROLES | CLIENT_ROLES)
    _can_tinh_nang(user, "dinh_kem")
    check_conversation(user, conversation_id, _user_channel(user))
    from app.ingest import (ATTACHMENT_EXTENSIONS, ExtractionError,
                            extract_text_with_metadata)

    safe = _safe_filename(file.filename or "tai_lieu")
    suffix = Path(safe).suffix.lower()
    if suffix not in ATTACHMENT_EXTENSIONS:
        raise HTTPException(400, f"Chưa đọc được định dạng {suffix or '(không rõ)'}. "
                                 "Nhận: " + ", ".join(sorted(ATTACHMENT_EXTENSIONS)))
    limit = MAX_UPLOAD_MB * 1024 * 1024
    size = 0
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp_path = Path(tmp.name)
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"Tệp vượt quá {MAX_UPLOAD_MB} MB")
                tmp.write(chunk)
        # OCR một bản scan có thể mất hàng phút CPU — chạy trong threadpool,
        # đừng treo event loop (nghẽn là MỌI request khác đứng theo, kể cả
        # nhịp tim SSE đang chống 524).
        from fastapi.concurrency import run_in_threadpool
        try:
            extraction = await run_in_threadpool(extract_text_with_metadata, tmp_path,
                                                 ATTACHMENT_EXTENSIONS)
        except ExtractionError as e:
            raise HTTPException(400, f"Không đọc được nội dung: {e.message} {e.hint}")
        # File .docx: giữ thêm BẢN GỐC (không chỉ text) trong data/work — luồng
        # "tạo bộ file" dùng nó làm khuôn giữ định dạng. Hàng tạm như temp_files:
        # gỡ chip hoặc quá 6 giờ là mất.
        kept_path = None
        if suffix == ".docx":
            import shutil as _shutil
            import uuid as _uuid
            keep_dir = DATA_WORK / "chat_uploads" / str(conversation_id)
            keep_dir.mkdir(parents=True, exist_ok=True)
            kept = keep_dir / f"{_uuid.uuid4().hex[:8]}_{safe}"
            _shutil.copyfile(tmp_path, kept)
            kept_path = str(kept)
        n, temp_id = await run_in_threadpool(
            rag.add_temp_file, conversation_id, user["id"], safe, extraction.text,
            kept_path)
    finally:
        await file.close()
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)

    with db.session(role="internal", admin=True) as conn:
        db.audit(conn, user["id"], "chat_temp_upload", "conversation",
                 conversation_id, {"file": safe, "bytes": size,
                                   "status": extraction.status})
    note = "File dùng xong bỏ — tự xóa sau 6 giờ, không vào kho."
    if extraction.status == "warning":
        note += (" LƯU Ý: file là bản scan/trích xuất có cảnh báo — nội dung "
                 "đọc ra có thể thiếu hoặc sai ký tự.")
    return {"ok": True, "mode": "temp", "filename": safe, "chunks": n,
            "temp_file_id": temp_id,
            "warnings": extraction.warnings, "status": extraction.status,
            "text_chars": len(extraction.text or ""), "note": note}


@app.get("/conversations/{conv_id}/temp-files")
def conversation_temp_files(conv_id: int, user=Depends(current_user)):
    """File 'dùng xong bỏ' còn hạn của một hội thoại — tab Kiểm tra pháp lý mở
    lại phiên cũ thì dựng lại đúng các chip đính kèm còn dùng được (file quá
    6 giờ đã tự xoá, không dựng lại để người dùng khỏi tưởng bot còn đọc)."""
    require(user, INTERNAL_ROLES)
    check_conversation(user, conv_id, "internal")
    return {"items": rag.list_temp_files(conv_id)}


@app.delete("/temp-files/{temp_id}")
def temp_file_delete(temp_id: int, user=Depends(current_user)):
    """Gỡ một file 'dùng xong bỏ' THẬT SỰ (không chỉ ẩn chip trên giao diện).

    Quyền sở hữu đi qua check_conversation — temp_files không có RLS."""
    require(user, INTERNAL_ROLES)
    conv_id = rag.delete_temp_file(temp_id)
    if conv_id is None:
        return {"ok": True, "note": "File đã hết hạn hoặc đã xoá trước đó."}
    check_conversation(user, conv_id, "internal")
    rag.remove_temp_file(temp_id)
    with db.session(role="internal", admin=True) as conn:
        db.audit(conn, user["id"], "delete_temp_file", "conversation", conv_id,
                 {"temp_file_id": temp_id})
    return {"ok": True}


# ---------- 3. DUYỆT NHÃN ----------
# Ngưỡng "đọc lỗi" — CÙNG con số với app/duyet_hang_loat.NGUONG_MAC_DINH: lượt
# duyệt hàng loạt giữ lại hàng chờ đúng những tài liệu vượt ngưỡng này, nên bộ
# lọc phải hỏi cùng một câu hỏi, không thì người soát lọc ra một tập khác.
NGUONG_DOC_LOI = 0.20

# Thứ tự xếp hàng chờ. Khoá là giá trị giao diện gửi lên, giá trị là mệnh đề
# ORDER BY — WHITELIST, không bao giờ ghép chuỗi người dùng vào SQL.
_REVIEW_SAP_XEP = {
    # Mặc định: cái cần MẮT NGƯỜI nhất lên trước (đọc lỗi nhiều, máy ít tự tin).
    "can_soat": "d.ty_le_rac DESC NULLS LAST, d.confidence ASC NULLS FIRST, d.id",
    # Ngược lại: cái sạch nhất lên trước, để duyệt nhanh hàng loạt cho vơi hàng.
    "de_duyet": "d.ty_le_rac ASC NULLS FIRST, d.confidence DESC NULLS LAST, d.id",
    "moi_nhat": "d.created_at DESC NULLS LAST, d.id DESC",
    "cu_nhat": "d.created_at ASC NULLS FIRST, d.id",
    "ten": "d.title ASC NULLS LAST, d.id",
    "duong_dan": "d.drive_file_id ASC NULLS LAST, d.id",
}

# Trạng thái đọc (một dòng lọc), khớp với nhãn hiện trên thẻ tài liệu.
_REVIEW_TRANG_THAI = {
    "doc_loi": ("d.ty_le_rac >= %s", (NGUONG_DOC_LOI,)),
    "canh_bao": ("d.extraction_status = 'warning'", ()),
    "da_sua": ("d.extraction_status = 'edited'", ()),
    "chua_cham": ("d.ty_le_rac IS NULL", ()),
    "sach": ("d.ty_le_rac < %s AND coalesce(d.extraction_status,'ready') <> 'warning'",
             (NGUONG_DOC_LOI,)),
}

# Ngăn giả cho tài liệu KHÔNG nằm trong cây kho (nạp từ chat, web, tải tay)
# và cho tệp nằm ngay ở gốc kho (không thuộc ngăn nào).
NGAN_NGOAI_KHO = "(ngoài kho)"
NGAN_GOC_KHO = "(gốc kho)"


def _like_an_toan(s: str) -> str:
    """Thoát ký tự đại diện của LIKE: tên thư mục có '%' hay '_' vẫn khớp đúng."""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _review_dieu_kien(q: str | None, ngan: str | None, doc_type: str | None,
                      nguon: str | None, trang_thai: str | None,
                      khach: int | None) -> tuple[list[str], list]:
    """Bộ lọc hàng chờ duyệt → (mệnh đề WHERE, tham số). Thuần, test được.

    Mọi giá trị người dùng đi bằng THAM SỐ; chỉ tên cột và toán tử là chuỗi.
    """
    where, params = [], []
    if q and q.strip():
        # Tìm cả trong ĐƯỜNG DẪN: người duyệt thường nhớ thư mục chứ không nhớ
        # tên tệp ("mấy cái trong ngăn bản án 2019").
        kw = f"%{_like_an_toan(q.strip())}%"
        where.append("(d.title ILIKE %s ESCAPE '\\' OR d.drive_file_id ILIKE %s ESCAPE '\\' "
                     "OR d.source_path ILIKE %s ESCAPE '\\')")
        params += [kw, kw, kw]
    if ngan:
        # Mẫu 'local:%' đi bằng THAM SỐ chứ không viết thẳng vào câu lệnh: câu
        # này có tham số khác, mà psycopg coi mọi '%' trong chuỗi SQL là chỗ
        # chèn — một dấu % viết thẳng là cả câu vỡ ngay lúc chạy.
        if ngan == NGAN_NGOAI_KHO:
            where.append("(d.drive_file_id IS NULL OR d.drive_file_id NOT LIKE %s)")
            params.append("local:%")
        elif ngan == NGAN_GOC_KHO:
            where.append("(d.drive_file_id LIKE %s AND d.drive_file_id NOT LIKE %s)")
            params += ["local:%", "local:%/%"]
        else:
            where.append("d.drive_file_id LIKE %s ESCAPE '\\'")
            params.append(f"local:{_like_an_toan(ngan)}/%")
    if doc_type:
        where.append("coalesce(d.doc_type,'other') = %s")
        params.append(doc_type)
    if nguon:
        where.append("d.source_kind = %s")
        params.append(nguon)
    if trang_thai:
        menh_de = _REVIEW_TRANG_THAI.get(trang_thai)
        if menh_de:
            where.append(f"({menh_de[0]})")
            params += list(menh_de[1])
    if khach:
        where.append("d.client_id = %s")
        params.append(khach)
    return where, params


def _tep_goc_info(source_path: str | None) -> tuple[bool, int | None]:
    """Tệp gốc còn trên đĩa không, và nặng bao nhiêu byte.

    Người duyệt cần biết TRƯỚC khi bấm "Xem bản gốc": tài liệu nạp từ hội
    thoại hoặc tệp đã bị dọn thì không có gì để đối chiếu.
    """
    if not source_path:
        return False, None
    try:
        p = Path(source_path)
        if not p.is_absolute():
            p = Path.cwd() / p
        st = p.stat()
        return True, st.st_size
    except (OSError, ValueError):
        return False, None


@app.get("/review/pending")
def review_pending(user=Depends(current_user), limit: int = 50, offset: int = 0,
                   q: str | None = None, ngan: str | None = None,
                   doc_type: str | None = None, nguon: str | None = None,
                   trang_thai: str | None = None, khach: int | None = None,
                   sap_xep: str = "can_soat"):
    """Hàng chờ duyệt nhãn, có bộ lọc và ĐỦ thông tin để quyết định.

    Hàng chờ thật có hàng nghìn tài liệu: không lọc được thì người duyệt chỉ
    thấy 50 cái đầu và không có cách nào tìm đúng lô mình muốn xử lý. Mỗi dòng
    kèm VỊ TRÍ TRONG CÂY THƯ MỤC (kho.vi_tri_trong_kho) — ngăn chứa tệp chính
    là căn cứ gán nhãn, mà tiêu đề không nói lên điều đó.

    Vẫn trả về MẢNG (không bọc trong object): trang /admin cũ đọc thẳng mảng
    này; số liệu tổng và danh sách ngăn nằm ở /review/pending/bo-loc.
    """
    require_reviewer(user)
    limit = max(1, min(int(limit or 50), 200))
    offset = max(0, int(offset or 0))
    where, params = _review_dieu_kien(q, ngan, doc_type, nguon, trang_thai, khach)
    thu_tu = _REVIEW_SAP_XEP.get(sap_xep) or _REVIEW_SAP_XEP["can_soat"]
    dieu_kien = ("" if not where else " AND " + " AND ".join(where))
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"""SELECT d.id,d.title,d.doc_type,d.access_level,d.client_id,d.confidence,
                           d.source_kind,c.name,d.extraction_status,d.extraction_error,
                           (SELECT left(content,200) FROM chunks WHERE document_id=d.id ORDER BY chunk_index LIMIT 1),
                           d.so_hieu,d.loai_van_ban,d.trich_yeu,d.ngay_ban_hanh,
                           d.ngay_hieu_luc,d.trang_thai_hieu_luc,d.ty_le_rac,
                           d.drive_file_id,d.source_path,d.created_at,d.updated_at,
                           d.person_folder,
                           (SELECT count(*) FROM chunks WHERE document_id=d.id),
                           u.full_name, dep.name
                           FROM documents d
                           LEFT JOIN clients c ON c.id=d.client_id
                           LEFT JOIN users u ON u.id=d.uploaded_by
                           LEFT JOIN departments dep ON dep.id=d.department_id
                           WHERE NOT d.label_verified AND coalesce(d.active, true)
                           {dieu_kien}
                           ORDER BY {thu_tu} LIMIT %s OFFSET %s""",
                        (*params, limit, offset))
            rows = cur.fetchall()
    ket_qua = []
    for r in rows:
        vi_tri = kho.vi_tri_trong_kho(r[18], r[19])
        co_tep, kich_thuoc = _tep_goc_info(r[19])
        ket_qua.append({
            "id": r[0], "title": r[1], "doc_type": r[2], "access_level": r[3],
            "client_id": r[4], "confidence": r[5], "source_kind": r[6],
            "client_name": r[7], "extraction_status": r[8], "extraction_warning": r[9],
            "preview": r[10],
            # Metadata máy bóc sẵn — form duyệt điền trước cho người soát/sửa.
            "so_hieu": r[11], "loai_van_ban": r[12], "trich_yeu": r[13],
            "ngay_ban_hanh": str(r[14]) if r[14] else None,
            "ngay_hieu_luc": str(r[15]) if r[15] else None,
            "trang_thai_hieu_luc": r[16],
            # Tỉ lệ token đọc lỗi do app/duyet_hang_loat chấm. Tài liệu còn ở
            # hàng chờ SAU một lượt duyệt hàng loạt thường là vì con số này
            # vượt ngưỡng — người soát cần thấy ngay nó tệ cỡ nào.
            "ty_le_rac": r[17],
            # VỊ TRÍ trong cây thư mục kho — căn cứ chính để gán nhãn.
            "duong_dan": vi_tri["duong_dan"], "thu_muc": vi_tri["thu_muc"],
            "ngan": vi_tri["ngan"] or (NGAN_GOC_KHO if vi_tri["trong_kho"]
                                       else NGAN_NGOAI_KHO),
            "ten_tep": vi_tri["ten_tep"], "duoi": vi_tri["duoi"],
            "trong_kho": vi_tri["trong_kho"],
            "co_tep": co_tep, "kich_thuoc": kich_thuoc,
            "created_at": str(r[20]) if r[20] else None,
            "updated_at": str(r[21]) if r[21] else None,
            "person_folder": r[22], "so_doan": r[23],
            "nguoi_nap": r[24], "phong": r[25],
        })
    return ket_qua


@app.get("/review/pending/bo-loc")
def review_pending_bo_loc(user=Depends(current_user)):
    """Số liệu cho thanh bộ lọc: tổng hàng chờ, các ngăn, loại, nguồn, trạng thái.

    Đếm trên TOÀN hàng chờ (không theo trang) — người duyệt cần biết còn bao
    nhiêu và nằm ở ngăn nào trước khi chọn lô để xử lý.
    """
    require_reviewer(user)
    co_ban = "FROM documents d WHERE NOT d.label_verified AND coalesce(d.active, true)"
    # split_part trên phần sau 'local:' → tên NGĂN (thư mục cấp 1) của tệp.
    # Tệp nằm ngay gốc kho (không có '/') KHÔNG phải là ngăn: trả NULL rồi gắn
    # nhãn "(gốc kho)" ở Python — đúng bằng cách kho.vi_tri_trong_kho tính, để
    # bấm vào một ngăn trong bộ lọc là ra đúng những dòng mang tên ngăn đó.
    ngan_sql = ("CASE WHEN d.drive_file_id LIKE 'local:%/%' "
                "THEN split_part(substring(d.drive_file_id from 7), '/', 1) "
                "WHEN d.drive_file_id LIKE 'local:%' THEN NULL ELSE '' END")
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT count(*) {co_ban}")
            tong = cur.fetchone()[0]
            cur.execute(f"SELECT {ngan_sql} AS ngan, count(*) {co_ban} "
                        f"GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 80")
            ngan = [{"ten": (r[0] if r[0] else
                             (NGAN_GOC_KHO if r[0] is None else NGAN_NGOAI_KHO)),
                     "so": r[1]} for r in cur.fetchall()]
            cur.execute(f"SELECT coalesce(d.doc_type,'other'), count(*) {co_ban} "
                        f"GROUP BY 1 ORDER BY 2 DESC")
            loai = [{"ma": r[0], "so": r[1]} for r in cur.fetchall()]
            cur.execute(f"SELECT d.source_kind, count(*) {co_ban} GROUP BY 1 ORDER BY 2 DESC")
            nguon = [{"ma": r[0] or "?", "so": r[1]} for r in cur.fetchall()]
            cur.execute(f"""SELECT
                  count(*) FILTER (WHERE d.ty_le_rac >= %s),
                  count(*) FILTER (WHERE d.extraction_status = 'warning'),
                  count(*) FILTER (WHERE d.extraction_status = 'edited'),
                  count(*) FILTER (WHERE d.ty_le_rac IS NULL),
                  count(*) FILTER (WHERE d.ty_le_rac < %s
                                     AND coalesce(d.extraction_status,'ready') <> 'warning')
                {co_ban}""", (NGUONG_DOC_LOI, NGUONG_DOC_LOI))
            tt = cur.fetchone()
    return {"tong": tong, "ngan": ngan, "loai": loai, "nguon": nguon,
            "nguong_doc_loi": NGUONG_DOC_LOI,
            "trang_thai": {"doc_loi": tt[0], "canh_bao": tt[1], "da_sua": tt[2],
                           "chua_cham": tt[3], "sach": tt[4]}}


class LabelIn(BaseModel):
    doc_type: str
    access_level: str
    client_id: int | None = None
    # Danh tính văn bản pháp lý — người duyệt sửa được cái máy bóc. None nghĩa
    # là "không đổi" (giữ giá trị máy bóc); chuỗi rỗng nghĩa là xoá.
    so_hieu: str | None = None
    loai_van_ban: str | None = None
    trich_yeu: str | None = None
    ngay_ban_hanh: str | None = None
    ngay_hieu_luc: str | None = None
    trang_thai_hieu_luc: str | None = None


_CTX_HEADER_RE = re.compile(r"^\[Tài liệu: [^\]]*\]\n?")


@app.get("/review/{doc_id}/content")
def review_content_get(doc_id: int, user=Depends(current_user)):
    """Nội dung TRÍCH XUẤT của tài liệu — để người duyệt đọc và sửa trước khi
    duyệt. PDF scan là giấy tờ pháp lý: OCR sai một con số là sai căn cứ, nên
    chính sách 20/08/2026 bắt buộc mắt người soát nội dung, không chỉ soát nhãn."""
    require_reviewer(user)
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT d.title,d.doc_type,d.extraction_status,d.extraction_error,
                                  d.approved,d.label_verified,c.name
                             FROM documents d LEFT JOIN clients c ON c.id=d.client_id
                            WHERE d.id=%s""", (doc_id,))
            doc = cur.fetchone()
            if not doc:
                raise HTTPException(404, "Không thấy tài liệu")
            cur.execute("""SELECT content FROM chunks WHERE document_id=%s
                            ORDER BY chunk_index""", (doc_id,))
            parts = [r[0] or "" for r in cur.fetchall()]
    # Bỏ dòng danh tính gắn lúc học — người sửa chỉ cần văn bản gốc; khi lưu
    # lại dòng này được gắn mới theo tiêu đề/nhãn hiện hành.
    content = "\n\n".join(_CTX_HEADER_RE.sub("", p, count=1) for p in parts)
    return {"document_id": doc_id, "title": doc[0], "doc_type": doc[1],
            "extraction_status": doc[2], "extraction_warning": doc[3],
            "approved": doc[4], "label_verified": doc[5], "client_name": doc[6],
            "chunk_count": len(parts), "content": content}


@app.get("/review/{doc_id}/chunks")
def review_chunks(doc_id: int, user=Depends(current_user), limit: int = 300):
    """CÁC ĐOẠN đúng như bot sẽ đọc — cột phải của khung đối chiếu.

    Khác /review/{id}/content ở chỗ không nối liền: người duyệt thấy văn bản
    bị CẮT ở đâu, đoạn nào rơi vào giữa một điều luật, đoạn nào toàn chữ rác.
    Mỗi đoạn kèm tỉ lệ token đọc lỗi của CHÍNH đoạn đó (app/chat_luong) — tài
    liệu 5% rác toàn cục vẫn có thể có một trang scan hỏng hoàn toàn.
    """
    require_reviewer(user)
    limit = max(1, min(int(limit or 300), 1000))
    from app.chat_luong import ty_le_rac
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM chunks WHERE document_id=%s", (doc_id,))
            tong = cur.fetchone()[0]
            cur.execute("""SELECT chunk_index,content,section_title,page_number
                             FROM chunks WHERE document_id=%s
                            ORDER BY chunk_index LIMIT %s""", (doc_id, limit))
            rows = cur.fetchall()
    return {"document_id": doc_id, "tong": tong,
            "items": [{"chunk_index": r[0], "content": r[1] or "",
                       "so_ky_tu": len(r[1] or ""),
                       "ty_le_rac": round(ty_le_rac(r[1] or ""), 3),
                       "section_title": r[2], "page_number": r[3]} for r in rows]}


# Lý do sửa nội dung tài liệu kho (kế hoạch ngày 3): dữ liệu quý nhất của cơ
# chế tự học là VÌ SAO phải sửa, không chỉ sửa thành gì.
EDIT_REASONS = {
    "luat_thay_doi": "Luật thay đổi",
    "rui_ro": "Rủi ro",
    "yeu_cau_khach": "Yêu cầu khách hàng",
    "sua_loi_trich_xuat": "Sửa lỗi trích xuất / OCR",
    "khac": "Khác",
}


class ContentIn(BaseModel):
    content: str
    edit_reason: str | None = None
    edit_note: str | None = None


def _luu_phien_ban_tai_lieu(cur, doc_id: int, ban_cu: str, ban_moi: str,
                            user_id: int, edit_reason: str, edit_note: str | None) -> int:
    """Ghi lịch sử sửa nội dung: lần đầu sửa thì cất luôn bản gốc làm v1 (để
    còn so được với bản trước khi ai đụng vào), rồi bản mới là v(n+1)."""
    cur.execute("SELECT coalesce(max(version_no),0) FROM document_versions WHERE document_id=%s",
                (doc_id,))
    n = cur.fetchone()[0]
    if n == 0 and ban_cu.strip():
        cur.execute("""INSERT INTO document_versions
                         (document_id,version_no,content,edited_by,edit_reason,edit_note)
                       VALUES (%s,1,%s,NULL,'ban_goc','Bản trích xuất ban đầu')""",
                    (doc_id, ban_cu))
        n = 1
    cur.execute("""INSERT INTO document_versions
                     (document_id,version_no,content,edited_by,edit_reason,edit_note)
                   VALUES (%s,%s,%s,%s,%s,%s)""",
                (doc_id, n + 1, ban_moi, user_id, edit_reason, (edit_note or "").strip() or None))
    return n + 1


@app.put("/review/{doc_id}/content")
def review_content_put(doc_id: int, body: ContentIn, user=Depends(current_user)):
    """Lưu nội dung người duyệt đã sửa: chia đoạn lại, tạo vector lại — bot học
    ĐÚNG BẢN ĐÃ SỬA, không phải bản OCR thô. Trạng thái duyệt giữ nguyên (đang
    chờ thì vẫn chờ — sửa xong bấm Duyệt như thường); extraction_status thành
    'edited' để phân biệt với bản máy tự trích. Bản cũ KHÔNG mất: ghi vào
    document_versions kèm lý do sửa (bắt buộc chọn)."""
    require_reviewer(user)
    text = (body.content or "").strip()
    if len(text) < 30:
        raise HTTPException(422, "Nội dung sau sửa quá ngắn (dưới 30 ký tự)")
    if len(text) > 2_000_000:
        raise HTTPException(422, "Nội dung vượt 2 triệu ký tự — tách nhỏ tài liệu")
    edit_reason = (body.edit_reason or "").strip()
    if edit_reason not in EDIT_REASONS:
        raise HTTPException(422, "Chọn lý do sửa: " + ", ".join(
            f"{k} ({v})" for k, v in EDIT_REASONS.items()))
    from app.ingest import (ExtractionResult, apply_context_headers,
                            client_display_name, split_document_with_metadata)
    from app.models import embed, summarize
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT title,doc_type,access_level,client_id,department_id
                             FROM documents WHERE id=%s""", (doc_id,))
            doc = cur.fetchone()
            cur.execute("SELECT content FROM chunks WHERE document_id=%s ORDER BY chunk_index",
                        (doc_id,))
            ban_cu = "\n\n".join(_CTX_HEADER_RE.sub("", r[0] or "", count=1)
                                 for r in cur.fetchall())
    if not doc:
        raise HTTPException(404, "Không thấy tài liệu")
    title, doc_type, access_level, client_id, department_id = doc
    extraction = ExtractionResult(text=text, format="manual", method="manual_edit",
                                  warnings=[], metadata={})
    pieces = split_document_with_metadata(extraction, doc_type, ten_file=title)
    if not pieces:
        raise HTTPException(422, "Không chia được nội dung thành đoạn")
    pieces = apply_context_headers(pieces, title, doc_type,
                                   client_display_name(client_id))
    vecs = embed([p.content for p in pieces])
    summary = summarize(text, title)
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM chunks WHERE document_id=%s", (doc_id,))
            for idx, (piece, vec) in enumerate(zip(pieces, vecs)):
                cur.execute("""INSERT INTO chunks
                    (document_id,chunk_index,content,page_number,section_title,
                     source_locator,access_level,client_id,department_id,doc_type,embedding)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (doc_id, idx, piece.content, piece.page_number,
                     piece.section_title, piece.source_locator, access_level,
                     client_id, department_id, doc_type, json.dumps(vec)))
            cur.execute("""UPDATE documents SET summary=%s,extraction_status='edited',
                                  extraction_error=NULL,updated_at=now()
                            WHERE id=%s""", (summary, doc_id))
            # Người duyệt vừa sửa chữ (thường là chữa số hiệu/ngày OCR sai) —
            # bóc lại danh tính + quan hệ từ bản đã sửa cho khớp nội dung mới.
            # CHỈ ghi đè bằng giá trị BÓC ĐƯỢC: bóc trượt trả None, ghi None đè
            # lên số hiệu người duyệt đã gõ tay là xoá lặng lẽ công của họ —
            # mà quan hệ văn bản khoá theo số hiệu nên mất số là đứt hết liên kết.
            if doc_type in ("law", "an_le", "ban_an"):
                vb_meta = van_ban.boc_metadata(text, ten_file=title)
                cot = [(c, vb_meta.get(c)) for c in
                       ("so_hieu", "loai_van_ban", "trich_yeu",
                        "ngay_ban_hanh", "ngay_hieu_luc")
                       if vb_meta.get(c) is not None]
                if cot:
                    cur.execute(
                        f"UPDATE documents SET {','.join(f'{c}=%s' for c, _ in cot)} "
                        "WHERE id=%s", (*[v for _, v in cot], doc_id))
                van_ban.xu_ly_sau_hoc(cur, doc_type, text, vb_meta)
            # Trả metadata VỪA BÓC LẠI cho giao diện: form duyệt đang giữ giá
            # trị bóc từ bản OCR CŨ, bấm Duyệt ngay sau khi lưu là gửi lại số
            # hiệu sai vừa được người duyệt chữa (và chuỗi rỗng = lệnh XOÁ).
            cur.execute("""SELECT so_hieu,loai_van_ban,trich_yeu,
                                  ngay_ban_hanh,ngay_hieu_luc,trang_thai_hieu_luc
                             FROM documents WHERE id=%s""", (doc_id,))
            r = cur.fetchone() or (None,) * 6
            version_no = _luu_phien_ban_tai_lieu(cur, doc_id, ban_cu, text, user["id"],
                                                 edit_reason, body.edit_note)
        db.audit(conn, user["id"], "edit_document_content", "documents", doc_id,
                 {"chunks": len(pieces), "characters": len(text),
                  "version": version_no, "edit_reason": edit_reason})
    return {"ok": True, "document_id": doc_id, "chunks": len(pieces),
            "version_no": version_no, "edit_reason": edit_reason,
            "van_ban": {"so_hieu": r[0], "loai_van_ban": r[1], "trich_yeu": r[2],
                        "ngay_ban_hanh": str(r[3]) if r[3] else None,
                        "ngay_hieu_luc": str(r[4]) if r[4] else None,
                        "trang_thai_hieu_luc": r[5]}}


_NGAY_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _ngay_hop_le(raw, ten):
    """'YYYY-MM-DD' → giữ nguyên cho psycopg; rỗng → None; sai dạng/sai ngày → 422.

    Kiểm cả GIÁ TRỊ chứ không chỉ khuôn: '2024-02-31' khớp regex nhưng Postgres
    ném DatetimeFieldOverflow lúc UPDATE — người duyệt gõ nhầm ngày nhận 500
    Internal Server Error thay vì một câu tiếng Việt nói rõ sai ở đâu.
    """
    raw = (raw or "").strip()
    if not raw:
        return None
    if not _NGAY_ISO_RE.match(raw):
        raise HTTPException(422, f"{ten} phải theo dạng YYYY-MM-DD")
    try:
        date.fromisoformat(raw)
    except ValueError:
        raise HTTPException(422, f"{ten} không phải ngày có thật (YYYY-MM-DD)")
    return raw


def _ghi_nhan_duyet(cur, doc_id: int, body: LabelIn):
    """Ghi nhãn đã duyệt cho MỘT tài liệu (không mở phiên, không audit).

    Tách khỏi endpoint để duyệt nhanh hàng loạt đi ĐÚNG một đường với duyệt
    từng cái — hai đường ghi khác nhau là sớm muộn lệch nhau (bản duyệt hàng
    loạt quên bóc danh tính văn bản luật chẳng hạn).
    Người gọi chịu trách nhiệm gọi van_ban.cap_nhat_hieu_luc một lần sau cùng.
    """
    meta_sets, meta_vals = [], []
    for cot, gia_tri in (("so_hieu", body.so_hieu),
                         ("loai_van_ban", body.loai_van_ban),
                         ("trich_yeu", body.trich_yeu),
                         ("trang_thai_hieu_luc", body.trang_thai_hieu_luc)):
        if gia_tri is not None:
            gia_tri = gia_tri.strip()
            if cot == "so_hieu":
                gia_tri = van_ban.chuan_hoa_so_hieu(gia_tri)
            meta_sets.append(f"{cot}=%s")
            meta_vals.append(gia_tri or None)
    for cot, gia_tri in (("ngay_ban_hanh", body.ngay_ban_hanh),
                         ("ngay_hieu_luc", body.ngay_hieu_luc)):
        if gia_tri is not None:
            meta_sets.append(f"{cot}=%s")
            meta_vals.append(_ngay_hop_le(gia_tri, cot))
    extra_sql = ("," + ",".join(meta_sets)) if meta_sets else ""
    cur.execute(f"""UPDATE documents SET doc_type=%s,access_level=%s,client_id=%s,
                   label_verified=true,approved=true,extraction_status='ready',
                   updated_at=now(){extra_sql}
                   WHERE id=%s""",
                (body.doc_type, body.access_level, body.client_id,
                 *meta_vals, doc_id))
    # Văn bản luật vừa được duyệt có thể chính là bản thay thế một văn
    # bản đang trong kho (hoặc ngược lại) — soi lại trạng thái đôi bên.
    if body.doc_type in ("law", "an_le", "ban_an"):
        cur.execute("SELECT so_hieu, title FROM documents WHERE id=%s", (doc_id,))
        row = cur.fetchone()
        if not (row and row[0]):
            # Tài liệu nạp với nhãn khác (mặc định 'other') rồi người
            # duyệt ĐỔI sang văn bản luật: lượt học đã bỏ qua bước bóc
            # danh tính vì lúc đó doc_type chưa phải luật. Không bóc ở
            # đây thì nó vĩnh viễn không có số hiệu — vô hình với toàn
            # bộ cơ chế hiệu lực, mà không ai biết vì sao.
            cur.execute("""SELECT string_agg(content, E'\n\n' ORDER BY chunk_index)
                             FROM (SELECT content, chunk_index FROM chunks
                                    WHERE document_id=%s
                                    ORDER BY chunk_index LIMIT 4) t""",
                        (doc_id,))
            noi_dung = (cur.fetchone() or [None])[0] or ""
            vb_meta = van_ban.boc_metadata(noi_dung, ten_file=(row[1] if row else None))
            cot = [(c, vb_meta.get(c)) for c in
                   ("so_hieu", "loai_van_ban", "trich_yeu",
                    "ngay_ban_hanh", "ngay_hieu_luc")
                   if vb_meta.get(c) is not None]
            if cot:
                cur.execute(
                    f"UPDATE documents SET {','.join(f'{c}=%s' for c, _ in cot)} "
                    "WHERE id=%s", (*[v for _, v in cot], doc_id))
                van_ban.xu_ly_sau_hoc(cur, body.doc_type, noi_dung, vb_meta)
        return True          # có đụng tới văn bản luật → cần soi lại hiệu lực
    return False


def _kiem_nhan(body: LabelIn):
    """Chốt chung cho cả duyệt một tài liệu lẫn duyệt nhanh hàng loạt."""
    if body.access_level == "client" and body.client_id is None:
        raise HTTPException(400, "Tài liệu của khách bắt buộc chọn khách hàng")
    if (body.trang_thai_hieu_luc
            and body.trang_thai_hieu_luc not in van_ban.TRANG_THAI_HIEU_LUC):
        raise HTTPException(422, "Trạng thái hiệu lực không hợp lệ")


@app.post("/review/{doc_id}/approve")
def review_approve(doc_id: int, body: LabelIn, user=Depends(current_user)):
    require_reviewer(user)
    _kiem_nhan(body)
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            if _ghi_nhan_duyet(cur, doc_id, body):
                van_ban.cap_nhat_hieu_luc(cur)
        db.audit(conn, user["id"], "approve_label", "documents", doc_id, body.model_dump())
    return {"ok": True, "document_id": doc_id}


class NhanhItem(LabelIn):
    id: int


class NhanhIn(BaseModel):
    items: list[NhanhItem]


# Một lượt duyệt nhanh tối đa bấy nhiêu tài liệu: đủ cho cả một trang danh
# sách, mà không biến một cú bấm nhầm thành nghìn tài liệu vào kho.
TOI_DA_DUYET_NHANH = 200


@app.post("/review/duyet-nhanh")
def review_duyet_nhanh(body: NhanhIn, user=Depends(current_user)):
    """DUYỆT NHANH nhiều tài liệu bằng đúng nhãn máy đã đoán (người duyệt đã
    soát trên danh sách, không cần mở từng cái).

    Tài liệu nào không hợp lệ (mức "Hồ sơ khách hàng" mà chưa chọn khách, hoặc
    không còn trong hàng chờ) thì BỎ QUA và báo lại lý do — không để một dòng
    hỏng chặn cả lô, cũng không âm thầm duyệt sai mức truy cập.
    """
    require_reviewer(user)
    items = body.items or []
    if not items:
        raise HTTPException(422, "Chưa chọn tài liệu nào để duyệt")
    if len(items) > TOI_DA_DUYET_NHANH:
        raise HTTPException(413, f"Mỗi lượt duyệt nhanh tối đa {TOI_DA_DUYET_NHANH} tài liệu")
    da_duyet, bo_qua, cham_luat = [], [], False
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            for it in items:
                if it.access_level == "client" and it.client_id is None:
                    bo_qua.append({"id": it.id,
                                   "ly_do": 'Mức "Hồ sơ khách hàng" chưa chọn khách hàng sở hữu'})
                    continue
                if (it.trang_thai_hieu_luc
                        and it.trang_thai_hieu_luc not in van_ban.TRANG_THAI_HIEU_LUC):
                    bo_qua.append({"id": it.id, "ly_do": "Trạng thái hiệu lực không hợp lệ"})
                    continue
                cur.execute("""SELECT 1 FROM documents
                                WHERE id=%s AND NOT label_verified
                                  AND coalesce(active, true)""", (it.id,))
                if not cur.fetchone():
                    bo_qua.append({"id": it.id, "ly_do": "Không còn trong hàng chờ duyệt"})
                    continue
                if _ghi_nhan_duyet(cur, it.id, it):
                    cham_luat = True
                da_duyet.append(it.id)
            # Soi lại hiệu lực MỘT lần cho cả lô — chạy theo từng tài liệu là
            # quét lại toàn bộ bảng quan hệ hàng trăm lần cho một cú bấm.
            if cham_luat:
                van_ban.cap_nhat_hieu_luc(cur)
        for doc_id in da_duyet:
            db.audit(conn, user["id"], "approve_label", "documents", doc_id,
                     {"duyet_nhanh": True})
    return {"ok": True, "da_duyet": len(da_duyet), "ids": da_duyet, "bo_qua": bo_qua}


# ---------- 4. TỰ HỌC (duyệt hội thoại) ----------
@app.get("/learn/pending")
def learn_pending(user=Depends(current_user), limit: int = 30):
    """Câu trả lời BỊ NGƯỜI DÙNG BÁO CÁO đang chờ admin xử lý.

    Chỉ tin nhắn có báo cáo 'chưa tốt' (answer_feedback rating='bad', đang chờ)
    mới hiện ở đây — không còn dội mọi câu trả lời vào hàng chờ. Kèm ghi chú
    người báo cáo để admin biết sai ở đâu. Gộp nhiều báo cáo cho cùng một câu
    thành một dòng."""
    require_reviewer(user)
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT m.id, m.content, m.created_at,
                       (SELECT content FROM messages
                          WHERE conversation_id=m.conversation_id AND role='user' AND id<m.id
                          ORDER BY id DESC LIMIT 1) AS question,
                       (array_agg(f.note ORDER BY f.created_at DESC)
                          FILTER (WHERE f.note IS NOT NULL AND btrim(f.note) <> ''))[1] AS note,
                       max(u.full_name) AS reporter,
                       count(f.id) AS report_count,
                       max(f.created_at) AS reported_at
                  FROM answer_feedback f
                  JOIN messages m ON m.id = f.message_id
                  LEFT JOIN users u ON u.id = f.user_id
                 WHERE f.status='pending' AND f.rating='bad' AND m.review_status='pending'
                 GROUP BY m.id, m.content, m.created_at
                 ORDER BY max(f.created_at) DESC LIMIT %s""", (limit,))
            rows = cur.fetchall()
    return [{"message_id": r[0], "answer": r[1], "created_at": str(r[2]), "question": r[3],
             "note": r[4], "reporter": r[5], "report_count": r[6],
             "reported_at": str(r[7]) if r[7] else None} for r in rows]


class LearnIn(BaseModel):
    action: str                  # approve | edit | reject
    edited_content: str | None = None
    edit_reason: str | None = None
    access_level: str = "internal"


@app.post("/learn/{message_id}")
def learn_review(message_id: int, body: LearnIn, user=Depends(current_user)):
    require_reviewer(user)
    if body.action not in ("approve", "edit", "reject"):
        raise HTTPException(400, "action không hợp lệ")
    # Chỉ hai mức: 'internal' (mặc định) và 'public'. KHÔNG nhận 'client' — bản
    # ghi hỏi đáp không gắn client_id nào, đặt mức 'client' sẽ tạo tài liệu mà
    # RLS lọc theo khách hàng không ai đọc được (hoặc lọt sang khách khác).
    if body.access_level not in ("internal", "public"):
        raise HTTPException(400, "access_level chỉ nhận 'internal' hoặc 'public'")
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT m.content,
                           (SELECT content FROM messages WHERE conversation_id=m.conversation_id
                            AND role='user' AND id<m.id ORDER BY id DESC LIMIT 1)
                           FROM messages m WHERE m.id=%s""", (message_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Không thấy tin nhắn")
            answer_text, question = row
    if body.action == "reject":
        with db.session(role="internal", admin=True) as conn:
            with conn.cursor() as cur:
                cur.execute("""UPDATE messages SET review_status='rejected',reviewed_by=%s,
                               reviewed_at=now() WHERE id=%s""", (user["id"], message_id))
                # Đóng luôn báo cáo đang chờ của tin nhắn này để không còn treo lại
                cur.execute("""UPDATE answer_feedback SET status='rejected',reviewed_by=%s,
                               reviewed_at=now() WHERE message_id=%s AND status='pending'""",
                            (user["id"], message_id))
        return {"ok": True, "action": "rejected"}
    final = body.edited_content if body.action == "edit" else answer_text
    content = f"HỎI: {question}\n\nTRẢ LỜI:\n{final}"
    from app.models import embed
    vec = embed(content)
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO documents (title,doc_type,access_level,approved,label_verified)
                           VALUES (%s,'advisory',%s,true,true) RETURNING id""",
                        (f"Hỏi đáp: {(question or '')[:60]}", body.access_level))
            doc_id = cur.fetchone()[0]
            cur.execute("""INSERT INTO chunks (document_id,chunk_index,content,access_level,doc_type,embedding)
                           VALUES (%s,0,%s,%s,'advisory',%s)""",
                        (doc_id, content, body.access_level, json.dumps(vec)))
            cur.execute("""UPDATE messages SET review_status=%s,reviewed_by=%s,reviewed_at=now(),
                           edited_content=%s,edit_reason=%s,promoted_doc_id=%s WHERE id=%s""",
                        ("edited" if body.action == "edit" else "approved",
                         user["id"], body.edited_content, body.edit_reason, doc_id, message_id))
            # Đã nạp bản chuẩn vào kho → đóng báo cáo đang chờ của tin nhắn này
            cur.execute("""UPDATE answer_feedback SET status='applied',reviewed_by=%s,
                           reviewed_at=now() WHERE message_id=%s AND status='pending'""",
                        (user["id"], message_id))
        db.audit(conn, user["id"], "promote_to_kb", "messages", message_id,
                 {"document_id": doc_id, "action": body.action})
    return {"ok": True, "action": body.action, "document_id": doc_id}


# ---------- 5. MẪU PHƯƠNG PHÁP (dạy AI cách phân tích) ----------
class MethodIn(BaseModel):
    case_type: str
    steps: str


@app.get("/methods")
def methods_list(user=Depends(current_user)):
    require(user, INTERNAL_ROLES)
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id,case_type,steps,approved FROM analysis_methods ORDER BY id DESC")
            rows = cur.fetchall()
    return [{"id": r[0], "case_type": r[1], "steps": r[2], "approved": r[3]} for r in rows]


@app.post("/methods")
def methods_add(body: MethodIn, user=Depends(current_user)):
    """Dạy AI một quy trình phân tích. Chỉ người có quyền duyệt mới tạo (và tự duyệt)."""
    require_reviewer(user)
    from app.models import embed
    vec = embed(f"{body.case_type}. {body.steps}")
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO analysis_methods (case_type,steps,created_by,approved,embedding)
                           VALUES (%s,%s,%s,true,%s) RETURNING id""",
                        (body.case_type, body.steps, user["id"], json.dumps(vec)))
            mid = cur.fetchone()[0]
        db.audit(conn, user["id"], "add_method", "analysis_methods", mid, {"case_type": body.case_type})
    return {"ok": True, "method_id": mid}


# ---------- 6. QUẢN LÝ NGƯỜI DÙNG ----------
class UserIn(BaseModel):
    email: str
    full_name: str
    role: str
    # Để trống = máy chủ sinh mật khẩu tạm ngẫu nhiên, trả về ĐÚNG MỘT LẦN
    # trong phản hồi (mat_khau_tam). Trước 22/09/2026 mặc định là "hds12345"
    # ghi trong mã và trong sổ tay — ai cũng biết mật khẩu của tài khoản mới.
    password: str | None = None
    can_review: bool = False
    client_id: int | None = None
    department_ids: list[int] = []       # phòng user thuộc (nội bộ)
    head_of: list[int] = []              # phòng user làm trưởng
    monthly_quota: int = 0               # hạn mức câu hỏi/tháng (khách)
    # Chức năng mở cho tài khoản này; để trống = theo mặc định của vai
    # (khách chỉ hỏi đáp). Xem app/quyen_tinh_nang.py.
    features: dict | None = None


@app.get("/users")
def users_list(user=Depends(current_user)):
    require(user, {"admin"})
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            # Không trả api_key_hash ra ngoài — chỉ cho biết CÓ khoá hay không.
            # client_id + tên khách: trước 20/09/2026 không trả ra, nên cột
            # "khách hàng" trong màn hình quản trị luôn trống và không ai biết
            # tài khoản nào thuộc khách nào.
            cur.execute("""SELECT u.id,u.email,u.full_name,u.role,u.can_review,u.active,
                                  u.can_view_finance,
                                  (u.api_key_hash IS NOT NULL) AS has_api_key,
                                  u.api_key_at, u.client_id, c.name, c.code,
                                  u.monthly_quota, u.used_this_month, u.features,
                                  coalesce(u.must_change_password, false),
                                  u.last_login_at, u.created_at
                             FROM users u LEFT JOIN clients c ON c.id=u.client_id
                            ORDER BY u.id""")
            rows = cur.fetchall()
            # Phòng ban + cờ trưởng phòng của từng người: màn hình sửa tài
            # khoản cần biết đang gán ở đâu để tick sẵn.
            cur.execute("SELECT user_id, department_id, is_head FROM user_departments")
            phong: dict[int, list[int]] = {}
            truong: dict[int, list[int]] = {}
            for uid, did, is_head in cur.fetchall():
                phong.setdefault(uid, []).append(did)
                if is_head:
                    truong.setdefault(uid, []).append(did)
    return [{"id": r[0], "email": r[1], "full_name": r[2], "role": r[3],
             "can_review": r[4], "active": r[5], "can_view_finance": r[6],
             "has_api_key": r[7], "api_key_at": str(r[8])[:10] if r[8] else None,
             "client_id": r[9], "client_name": r[10], "client_code": r[11],
             "monthly_quota": r[12], "used_this_month": r[13],
             "features": quyen_tinh_nang.quyen_hieu_luc(r[3], r[14]),
             "features_tick": r[14],
             "must_change_password": r[15],
             "last_login_at": str(r[16])[:16] if r[16] else None,
             "created_at": str(r[17])[:10] if r[17] else None,
             "department_ids": phong.get(r[0], []),
             "head_of": truong.get(r[0], [])}
            for r in rows]


@app.get("/tinh-nang")
def tinh_nang_list(user=Depends(current_user)):
    """Danh mục chức năng bật/tắt được, để màn hình quản trị dựng các ô tick."""
    require(user, {"admin"})
    return {"items": [{"ma": ma, **cfg} for ma, cfg in quyen_tinh_nang.TINH_NANG.items()],
            "mac_dinh_khach": quyen_tinh_nang.MAC_DINH_KHACH,
            "mac_dinh_noi_bo": quyen_tinh_nang.MAC_DINH_NOI_BO}


class TinhNangIn(BaseModel):
    features: dict | None = None
    monthly_quota: int | None = None


@app.patch("/users/{uid}/tinh-nang")
def users_set_tinh_nang(uid: int, body: TinhNangIn, user=Depends(current_user)):
    """Bật/tắt chức năng và đặt hạn mức cho một tài khoản.

    Gửi features=null để trả tài khoản về mặc định của vai."""
    require(user, {"admin"})
    sach = quyen_tinh_nang.chuan_hoa(body.features)
    if body.monthly_quota is not None and not (0 <= body.monthly_quota <= 100000):
        raise HTTPException(422, "Hạn mức câu hỏi mỗi tháng phải trong khoảng 0–100.000")
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT role FROM users WHERE id=%s", (uid,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Không thấy người dùng")
            cur.execute("""UPDATE users SET features=%s,
                                  monthly_quota=coalesce(%s, monthly_quota)
                            WHERE id=%s""",
                        (json.dumps(sach, ensure_ascii=False) if sach else None,
                         body.monthly_quota, uid))
        db.audit(conn, user["id"], "set_user_features", "users", uid,
                 {"features": sach, "monthly_quota": body.monthly_quota})
    return {"ok": True, "features": quyen_tinh_nang.quyen_hieu_luc(row[0], sach),
            "features_tick": sach}


@app.get("/users/su-dung")
def users_su_dung(user=Depends(current_user)):
    """AI CỦA AI: từng người dùng đã làm gì và đang giữ bao nhiêu dung lượng.

    Chủ dự án 18/09/2026: "bản nháp / tạo file / lịch sử chat là của riêng
    từng người, không xem được của nhau; chỉ admin được toàn quyền xem user đã
    làm gì và đang tốn bộ nhớ bao nhiêu". Đây là màn hình cho vế sau — CHỈ
    admin, và chỉ trả về SỐ ĐẾM, không trả nội dung hội thoại hay bản nháp của
    ai cả.
    """
    require(user, {"admin"})
    from app import ho_so_da_luu as _hs, template_fill as _tf

    hoi_thoai, tin_nhan, ban_nhap, tai_lieu, hoat_dong = {}, {}, {}, {}, {}
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT id, full_name, email, role, coalesce(active,true)
                             FROM users ORDER BY id""")
            nguoi = cur.fetchall()
            cur.execute("""SELECT user_id, count(*), max(started_at)
                             FROM conversations WHERE user_id IS NOT NULL
                            GROUP BY user_id""")
            for uid, n, luc in cur.fetchall():
                hoi_thoai[uid] = n
                hoat_dong[uid] = max(filter(None, [hoat_dong.get(uid), luc]), default=None)
            cur.execute("""SELECT c.user_id, count(*), max(m.created_at)
                             FROM messages m JOIN conversations c ON c.id=m.conversation_id
                            WHERE c.user_id IS NOT NULL GROUP BY c.user_id""")
            for uid, n, luc in cur.fetchall():
                tin_nhan[uid] = n
                hoat_dong[uid] = max(filter(None, [hoat_dong.get(uid), luc]), default=None)
            cur.execute("""SELECT created_by, count(*), max(updated_at)
                             FROM document_drafts WHERE created_by IS NOT NULL
                            GROUP BY created_by""")
            for uid, n, luc in cur.fetchall():
                ban_nhap[uid] = n
                hoat_dong[uid] = max(filter(None, [hoat_dong.get(uid), luc]), default=None)
            cur.execute("""SELECT uploaded_by, count(*) FROM documents
                            WHERE uploaded_by IS NOT NULL AND coalesce(active,true)
                            GROUP BY uploaded_by""")
            tai_lieu = dict(cur.fetchall())

    # File tạm còn hạn: đọc chủ sở hữu ghi kèm trong từng thư mục token.
    so_file, dung_luong, khong_chu = {}, {}, {"so_file": 0, "bytes": 0}
    root = _tf.fills_dir()
    if root.exists():
        for thu_muc in root.iterdir():
            if not thu_muc.is_dir():
                continue
            try:
                cong = sum(f.stat().st_size for f in thu_muc.iterdir() if f.is_file())
            except OSError:
                continue
            chu = _tf.chu_so_huu(thu_muc.name)
            if chu is None:
                khong_chu["so_file"] += 1
                khong_chu["bytes"] += cong
                continue
            so_file[chu] = so_file.get(chu, 0) + 1
            dung_luong[chu] = dung_luong.get(chu, 0) + cong

    da_luu = _hs.dem_theo_nguoi()

    items = [{
        "id": r[0], "full_name": r[1], "email": r[2], "role": r[3], "active": r[4],
        "hoi_thoai": hoi_thoai.get(r[0], 0), "tin_nhan": tin_nhan.get(r[0], 0),
        "ban_nhap": ban_nhap.get(r[0], 0), "tai_lieu_da_nap": tai_lieu.get(r[0], 0),
        "ho_so_da_luu": da_luu.get(r[0], 0),
        "file_dang_giu": so_file.get(r[0], 0), "dung_luong": dung_luong.get(r[0], 0),
        "hoat_dong_cuoi": str(hoat_dong.get(r[0]))[:19] if hoat_dong.get(r[0]) else None,
    } for r in nguoi]
    items.sort(key=lambda x: (-x["dung_luong"], -x["tin_nhan"], x["id"]))
    return {"items": items, "khong_ro_chu": khong_chu,
            "giu_ngay": _tf.FILL_KEEP_DAYS,
            "tong_dung_luong": sum(dung_luong.values()) + khong_chu["bytes"]}


def _kiem_tra_vai_va_khach(role: str, client_id: int | None) -> None:
    """Ràng buộc vai ↔ hồ sơ khách, báo bằng tiếng Việt.

    CSDL cũng có CHECK role + client_role_needs_client_id, nhưng để nó bắt là
    màn hình nhận lỗi 500 thô. Dùng chung cho tạo mới và sửa."""
    if role not in INTERNAL_ROLES | CLIENT_ROLES:
        raise HTTPException(422, f"Vai không hợp lệ: {role}")
    if role in CLIENT_ROLES and not client_id:
        raise HTTPException(422, "Tài khoản khách phải gắn với một hồ sơ khách hàng")
    if client_id is not None and role not in CLIENT_ROLES:
        raise HTTPException(422, "Chỉ tài khoản khách mới gắn được vào hồ sơ khách hàng")


def _kiem_tra_sua_tai_khoan(*, uid: int, nguoi_sua_id: int, vai_cu: str, vai_moi: str,
                            active_moi: bool, so_admin_khac_dang_mo: int) -> None:
    """Chốt an toàn khi sửa/khoá tài khoản — logic thuần để test không cần CSDL.

    · Không tự hạ vai / tự khoá mình: đang là admin duy nhất mà tự khoá là
      không ai vào được màn hình quản trị nữa, chỉ còn đường SQL.
    · Không hạ vai / khoá admin CUỐI CÙNG còn mở, dù người sửa là ai."""
    if uid == nguoi_sua_id:
        if vai_moi != vai_cu:
            raise HTTPException(400, "Không tự đổi vai của chính mình")
        if not active_moi:
            raise HTTPException(400, "Không tự khoá tài khoản của chính mình")
    if vai_cu == "admin" and (vai_moi != "admin" or not active_moi):
        if so_admin_khac_dang_mo <= 0:
            raise HTTPException(400, "Đây là tài khoản quản trị duy nhất còn hoạt động — "
                                     "hãy tạo/mở một tài khoản admin khác trước")


def _kiem_tra_phong_ban(cur, department_ids: list[int], head_of: list[int]) -> None:
    ids = set(department_ids) | set(head_of)
    if not ids:
        return
    cur.execute("SELECT id FROM departments WHERE id = ANY(%s)", (list(ids),))
    co = {r[0] for r in cur.fetchall()}
    thieu = sorted(ids - co)
    if thieu:
        raise HTTPException(422, f"Phòng ban không tồn tại: {thieu}")
    if set(head_of) - set(department_ids):
        raise HTTPException(422, "Làm trưởng phòng thì phải thuộc phòng đó")


@app.post("/users")
def users_add(body: UserIn, user=Depends(current_user)):
    require(user, {"admin"})
    email = _chuan_hoa_email(body.email)
    ho_ten = " ".join((body.full_name or "").split())
    if not ho_ten:
        raise HTTPException(422, "Thiếu họ tên")
    # Vai khách BẮT BUỘC gắn hồ sơ khách; vai nội bộ không được gắn.
    _kiem_tra_vai_va_khach(body.role, body.client_id)
    features = quyen_tinh_nang.chuan_hoa(body.features)
    # Mật khẩu: quản trị tự đặt (phải qua chính sách) hoặc để máy sinh tạm.
    # Cả hai trường hợp đều là mật khẩu "tạm" — người dùng phải đổi lần đầu.
    if body.password:
        loi = auth.kiem_tra_mat_khau_moi(body.password, email=email)
        if loi:
            raise HTTPException(422, loi)
        mat_khau_tam = body.password
    else:
        mat_khau_tam = auth.new_temp_password()
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM users WHERE lower(email)=%s", (email,))
            if cur.fetchone():
                raise HTTPException(409, f"Email {email} đã có tài khoản")
            if body.client_id is not None:
                cur.execute("SELECT 1 FROM clients WHERE id=%s", (body.client_id,))
                if not cur.fetchone():
                    raise HTTPException(404, "Không thấy hồ sơ khách hàng đã chọn")
            depts = [] if body.role in CLIENT_ROLES else list(dict.fromkeys(body.department_ids))
            heads = [] if body.role in CLIENT_ROLES else list(dict.fromkeys(body.head_of))
            _kiem_tra_phong_ban(cur, depts, heads)
            cur.execute("""INSERT INTO users (email,password_hash,full_name,role,can_review,
                                              client_id,monthly_quota,features,
                                              must_change_password)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,true) RETURNING id""",
                        (email, auth.hash_password(mat_khau_tam), ho_ten,
                         body.role, body.can_review, body.client_id, body.monthly_quota,
                         json.dumps(features, ensure_ascii=False) if features else None))
            uid = cur.fetchone()[0]
            for did in depts:
                cur.execute("""INSERT INTO user_departments (user_id,department_id,is_head)
                               VALUES (%s,%s,%s) ON CONFLICT DO NOTHING""",
                            (uid, did, did in heads))
        db.audit(conn, user["id"], "create_user", "users", uid,
                 {"role": body.role, "depts": depts,
                  "client_id": body.client_id, "features": features,
                  "monthly_quota": body.monthly_quota})
    # mat_khau_tam chỉ trả về đúng lần này; CSDL giữ bản băm nên không xem lại
    # được — mất thì dùng "Đặt lại mật khẩu".
    return {"ok": True, "user_id": uid, "email": email, "mat_khau_tam": mat_khau_tam}


class UserPatchIn(BaseModel):
    """Trường nào None = giữ nguyên."""
    full_name: str | None = None
    role: str | None = None
    client_id: int | None = None
    department_ids: list[int] | None = None
    head_of: list[int] | None = None
    active: bool | None = None


@app.patch("/users/{uid}")
def users_update(uid: int, body: UserPatchIn, user=Depends(current_user)):
    """Sửa tài khoản đã tạo: họ tên, vai, hồ sơ khách, phòng ban, khoá/mở.

    Trước 22/09/2026 những việc này chỉ làm được bằng SQL (sổ tay IT mục 8.2).
    Đưa vào vận hành chính thức thì quản trị phải tự làm trên web."""
    require(user, {"admin"})
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT role, client_id, coalesce(active,true), full_name
                             FROM users WHERE id=%s""", (uid,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Không thấy người dùng")
            vai_cu, khach_cu, active_cu, ten_cu = row
            vai_moi = body.role or vai_cu
            active_moi = active_cu if body.active is None else body.active
            # client_id: gửi lên thì lấy; vai đổi sang nội bộ thì bỏ; không gửi thì giữ.
            if vai_moi in CLIENT_ROLES:
                khach_moi = body.client_id if body.client_id is not None else khach_cu
            else:
                khach_moi = None
            _kiem_tra_vai_va_khach(vai_moi, khach_moi)
            cur.execute("""SELECT count(*) FROM users
                            WHERE role='admin' AND coalesce(active,true) AND id<>%s""", (uid,))
            _kiem_tra_sua_tai_khoan(uid=uid, nguoi_sua_id=user["id"], vai_cu=vai_cu,
                                    vai_moi=vai_moi, active_moi=active_moi,
                                    so_admin_khac_dang_mo=cur.fetchone()[0])
            if khach_moi is not None and khach_moi != khach_cu:
                cur.execute("SELECT 1 FROM clients WHERE id=%s", (khach_moi,))
                if not cur.fetchone():
                    raise HTTPException(404, "Không thấy hồ sơ khách hàng đã chọn")
            ten_moi = ten_cu
            if body.full_name is not None:
                ten_moi = " ".join(body.full_name.split())
                if not ten_moi:
                    raise HTTPException(422, "Thiếu họ tên")
            cur.execute("""UPDATE users SET full_name=%s, role=%s, client_id=%s, active=%s
                            WHERE id=%s""", (ten_moi, vai_moi, khach_moi, active_moi, uid))
            # Phòng ban: vai khách không có phòng; vai nội bộ chỉ ghi lại khi
            # có gửi danh sách (None = giữ nguyên).
            if vai_moi in CLIENT_ROLES:
                cur.execute("DELETE FROM user_departments WHERE user_id=%s", (uid,))
            elif body.department_ids is not None:
                depts = list(dict.fromkeys(body.department_ids))
                heads = [d for d in dict.fromkeys(body.head_of or []) if d in depts]
                _kiem_tra_phong_ban(cur, depts, heads)
                cur.execute("DELETE FROM user_departments WHERE user_id=%s", (uid,))
                for did in depts:
                    cur.execute("""INSERT INTO user_departments (user_id,department_id,is_head)
                                   VALUES (%s,%s,%s)""", (uid, did, did in heads))
            # Khoá tài khoản khách thì khoá luôn khoá API — không để một đường
            # còn mở trong khi đường kia đã đóng.
            if not active_moi:
                cur.execute("UPDATE users SET api_key_hash=NULL, api_key_at=NULL WHERE id=%s",
                            (uid,))
        db.audit(conn, user["id"], "update_user", "users", uid,
                 {"role": vai_moi, "active": active_moi, "client_id": khach_moi,
                  "depts": body.department_ids, "head_of": body.head_of,
                  "renamed": body.full_name is not None and ten_moi != ten_cu})
    return {"ok": True, "user_id": uid, "role": vai_moi, "active": active_moi,
            "client_id": khach_moi, "full_name": ten_moi}


class ResetPwIn(BaseModel):
    new_password: str | None = None   # None = máy sinh mật khẩu tạm


@app.post("/users/{uid}/reset-password")
def users_reset_password(uid: int, body: ResetPwIn, user=Depends(current_user)):
    """Quản trị đặt lại mật khẩu cho người quên. Mật khẩu mới trả về MỘT LẦN
    và người dùng bị bắt đổi ngay lần đăng nhập kế tiếp."""
    require(user, {"admin"})
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT email FROM users WHERE id=%s", (uid,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Không thấy người dùng")
            if body.new_password:
                loi = auth.kiem_tra_mat_khau_moi(body.new_password, email=row[0])
                if loi:
                    raise HTTPException(422, loi)
                mat_khau_tam = body.new_password
            else:
                mat_khau_tam = auth.new_temp_password()
            cur.execute("""UPDATE users SET password_hash=%s, must_change_password=true
                            WHERE id=%s""", (auth.hash_password(mat_khau_tam), uid))
        db.audit(conn, user["id"], "reset_password", "users", uid, {})
    return {"ok": True, "user_id": uid, "mat_khau_tam": mat_khau_tam}


@app.post("/users/{uid}/review-permission")
def users_set_review(uid: int, grant: bool, user=Depends(current_user)):
    """Admin cấp/thu quyền duyệt cho một nhân viên."""
    require(user, {"admin"})
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET can_review=%s WHERE id=%s", (grant, uid))
        db.audit(conn, user["id"], "set_review_perm", "users", uid, {"grant": grant})
    return {"ok": True, "user_id": uid, "can_review": grant}


@app.post("/users/{uid}/finance-permission")
def users_set_finance(uid: int, grant: bool, user=Depends(current_user)):
    """Admin cấp/thu quyền xem công nợ, tài chính của khách.

    Không có quyền này thì tài liệu loại 'cong_no' bị chặn ở CSDL (RLS): không
    tra cứu ra, không hiện trong danh sách, bot cũng không nhắc tới."""
    require(user, {"admin"})
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET can_view_finance=%s WHERE id=%s", (grant, uid))
        db.audit(conn, user["id"], "set_finance_perm", "users", uid, {"grant": grant})
    return {"ok": True, "user_id": uid, "can_view_finance": grant}


@app.post("/users/{uid}/api-key")
def users_issue_api_key(uid: int, user=Depends(current_user)):
    """Cấp khoá API mới cho một tài khoản khách (thu hồi khoá cũ nếu có).

    Khoá thật CHỈ trả về đúng lần này — CSDL giữ bản băm nên không lấy lại được.
    Mất thì cấp khoá mới, không có cách xem lại."""
    require(user, {"admin"})
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT role FROM users WHERE id=%s", (uid,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Không thấy tài khoản")
            if row[0] not in CLIENT_ROLES:
                raise HTTPException(400, "Chỉ cấp khoá API cho tài khoản khách hàng")
            raw, hashed = auth.new_api_key()
            cur.execute("UPDATE users SET api_key_hash=%s, api_key_at=now() WHERE id=%s",
                        (hashed, uid))
        db.audit(conn, user["id"], "issue_api_key", "users", uid, {})
    return {"ok": True, "user_id": uid, "api_key": raw,
            "note": "Lưu lại ngay — khoá này không hiển thị lại lần nào nữa."}


@app.delete("/users/{uid}/api-key")
def users_revoke_api_key(uid: int, user=Depends(current_user)):
    """Thu hồi khoá API. Mọi lời gọi dùng khoá cũ bị chặn ngay lập tức."""
    require(user, {"admin"})
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET api_key_hash=NULL, api_key_at=NULL WHERE id=%s",
                        (uid,))
        db.audit(conn, user["id"], "revoke_api_key", "users", uid, {})
    return {"ok": True, "user_id": uid}


# ---------- 7. DANH SÁCH TÀI LIỆU ĐÃ HỌC ----------
@app.get("/documents")
def documents_list(user=Depends(current_user), q: str = "", doc_type: str = "", limit: int = 200):
    """Danh sách tài liệu đã vào kho, kèm tóm tắt. Chỉ admin hoặc người được cấp quyền.
    q: tìm theo tên/tóm tắt. doc_type: lọc theo loại (law/contract/...)."""
    require_reviewer(user)
    q = (q or "").strip()[:200]
    limit = max(1, min(limit, 500))
    sql = """SELECT d.id, d.title, d.doc_type, d.access_level, d.summary,
                    d.source_kind, d.created_at, c.name,
                    (SELECT count(*) FROM chunks WHERE document_id=d.id) AS so_doan,
                    d.so_hieu, d.loai_van_ban, d.trich_yeu, d.trang_thai_hieu_luc
               FROM documents d LEFT JOIN clients c ON c.id=d.client_id
              WHERE d.label_verified = true AND d.approved = true
                AND coalesce(d.active,true)
                AND coalesce(d.extraction_status,'ready')='ready'"""
    params = []
    # Phiên này mở bằng admin=True nên RLS không áp — phải tự chặn công nợ.
    if not user["can_finance"]:
        sql += " AND d.doc_type <> 'cong_no'"
    if q:
        sql += " AND (d.title ILIKE %s OR d.summary ILIKE %s)"
        params += [f"%{q}%", f"%{q}%"]
    if doc_type:
        sql += " AND d.doc_type = %s"
        params.append(doc_type)
    sql += " ORDER BY d.created_at DESC LIMIT %s"
    params.append(limit)
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    return [{"id": r[0], "title": r[1], "doc_type": r[2], "access_level": r[3],
             "summary": r[4] or "(chưa có tóm tắt)", "source_kind": r[5],
             "created_at": str(r[6])[:10], "client_name": r[7], "so_doan": r[8],
             "so_hieu": r[9], "loai_van_ban": r[10], "trich_yeu": r[11],
             "trang_thai_hieu_luc": r[12]} for r in rows]


@app.get("/drive/sync-status")
def drive_sync_status(user=Depends(current_user)):
    """Trạng thái lần quét kho tài liệu gần nhất.

    Từ 27/08/2026 nguồn là THƯ MỤC TRÊN MÁY CHỦ (app/local_learn.py); máy chủ
    còn khai DRIVE_FOLDER_ID thì vẫn là bộ quét Drive (app/auto_learn.py). Cả
    hai ghi chung một khoá trạng thái, phân biệt bằng trường `source`.

    Đây là nơi admin biết bot đã học file nào, file nào bị bỏ qua và lý do —
    không cần SSH vào máy chủ xem log."""
    require_reviewer(user)
    raw = settings.get("drive_sync_status")
    data = json.loads(raw) if raw else None
    source = (data or {}).get("source") or ("drive" if os.getenv("DRIVE_FOLDER_ID") else "local")
    return {
        "source": source,
        "library_root": (data or {}).get("root"),
        "configured": bool(raw) or bool(os.getenv("DRIVE_FOLDER_ID")),
        "last_run": data,
        # Lỗi CHƯA XỬ LÝ, tích luỹ qua mọi lần quét. Khác `last_run.error_items`
        # vốn chỉ là ảnh chụp lần quét cuối: file hỏng từ lần trước không được
        # quét lại (nội dung không đổi) nên sẽ vắng mặt ở đó và không ai biết.
        "failures": _open_ingest_failures(),
        # Lượt quét đang chạy (bấm "Quét lại" trên web, hoặc ai đó chạy từ SSH)
        # và kết quả lượt web gần nhất — thẻ trạng thái thăm dò mỗi 10 giây.
        "quet": kho.trang_thai_quet(),
    }


def _open_ingest_failures(limit: int = 200):
    """Tài liệu có trong Drive nhưng chưa học được, kèm cách sửa."""
    try:
        with db.session(role="internal", admin=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT id,file_name,location,error_code,error_message,hint,
                              attempts,first_seen_at,last_seen_at,drive_file_id
                         FROM ingest_failures
                        WHERE resolved_at IS NULL
                        ORDER BY last_seen_at DESC LIMIT %s""", (limit,))
                rows = cur.fetchall()
    except Exception:
        # Máy chủ chưa chạy migration mới thì coi như chưa có lỗi nào để hiện,
        # không làm sập cả trang dashboard.
        return []
    return [{"id": r[0], "file_name": r[1], "location": r[2], "error_code": r[3],
             "error_message": r[4], "hint": r[5], "attempts": r[6],
             "first_seen_at": str(r[7])[:19], "last_seen_at": str(r[8])[:19],
             "drive_file_id": r[9]} for r in rows]


@app.get("/documents/browse")
def documents_browse(user=Depends(current_user), q: str = "", limit: int = 300):
    """Danh sách tài liệu cho MỌI nhân viên nội bộ — ÁP CƠ CHẾ CÁCH B:
    thấy tên tất cả, nhưng hồ sơ ngoài phòng bị CHE TÊN và không mở được."""
    require(user, INTERNAL_ROLES)
    q = (q or "").strip()[:200]
    limit = max(1, min(limit, 500))
    sql = """SELECT d.id,d.title,d.doc_type,d.access_level,d.client_id,d.department_id,
                    dep.name, c.name, d.summary,
                    d.so_hieu, d.loai_van_ban, d.trich_yeu, d.trang_thai_hieu_luc
               FROM documents d
               LEFT JOIN clients c ON c.id=d.client_id
               LEFT JOIN departments dep ON dep.id=d.department_id
              WHERE d.label_verified AND d.approved
                AND coalesce(d.active,true)
                AND coalesce(d.extraction_status,'ready')='ready'"""
    params = []
    if q:
        # Tên file luật là "Luật số 59-2020-QH14" — gõ "Luật Doanh nghiệp" mà
        # chỉ soi title thì ra toàn nghị định (kiểm thử 18/09/2026). Trích yếu
        # và số hiệu mới là chỗ tên thật của văn bản nằm.
        sql += (" AND (d.title ILIKE %s OR d.summary ILIKE %s"
                " OR d.trich_yeu ILIKE %s OR d.so_hieu ILIKE %s)")
        params += [f"%{q}%"] * 4
    sql += " ORDER BY d.created_at DESC LIMIT %s"
    params.append(limit)
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    out = []
    # Đọc ma trận MỘT LẦN cho cả danh sách, không mỗi dòng một lượt truy vấn
    rules = rag.load_access_rules()
    for r in rows:
        doc = {"access_level": r[3], "department_id": r[5], "doc_type": r[2],
               "client_id": r[4], "title": r[1], "department_name": r[6]}
        can_open = rag.can_open_doc(user["role"], user["dept_ids"], user["is_banqt"], doc,
                                    can_finance=user["can_finance"],
                                    rules=rules, dept_codes=user["dept_codes"])
        out.append({
            "id": r[0],
            "title": rag.mask_title(doc, can_open),
            "doc_type": rag.DOC_TYPE_VN.get(r[2], r[2]),
            "access_level": r[3],
            "department": r[6],
            "can_open": can_open,
            "summary": (r[8] or "") if can_open else None,   # ẩn tóm tắt nếu không mở được
            # Danh tính văn bản luật là dữ liệu public (kệ luật public) nhưng
            # vẫn theo cùng luật che: không mở được thì không thấy gì thêm.
            "so_hieu": r[9] if can_open else None,
            "loai_van_ban": r[10] if can_open else None,
            "trich_yeu": r[11] if can_open else None,
            "trang_thai_hieu_luc": r[12] if can_open else None,
        })
    return out


# ---------- 7a-ter. CÂY THƯ MỤC KHO TRÊN TRANG TỔNG QUAN (app/kho.py) ----------
# Admin duyệt kho theo đúng cây thư mục trên máy chủ, tìm, gỡ, tải lên và học
# ngay — không cần SSH. Đường dẫn nhận vào là TƯƠNG ĐỐI trong kho; kho.py nhốt
# nó trong library_root nên không mở được gì bên ngoài.
def _kho_hoac_400(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except kho.LoiKho as e:
        raise HTTPException(400, str(e))


@app.get("/kho/cay")
def kho_cay(user=Depends(current_user), path: str = "", q: str = "",
            offset: int = 0, limit: int = 200):
    """Một tầng cây: thư mục con (kèm số đã học) + file trong thư mục."""
    require_reviewer(user)
    return _kho_hoac_400(kho.liet_ke, path, q=(q or "")[:200],
                         offset=max(0, offset), limit=max(1, min(limit, 500)))


@app.get("/kho/tim")
def kho_tim(user=Depends(current_user), q: str = "", limit: int = 100):
    """Tìm tài liệu đã có bản ghi theo tên / số hiệu / đường dẫn."""
    require_reviewer(user)
    q = (q or "").strip()[:200]
    if len(q) < 2:
        return []
    return kho.tim(q, limit=max(1, min(limit, 300)))


class KhoGoBody(BaseModel):
    document_id: int


@app.get("/kho/ho-so-khach")
def kho_ho_so_khach(user=Depends(current_user), q: str = "", loc: str = "",
                    offset: int = 0, limit: int = 100):
    """MỌI thư mục khách trên đĩa (kể cả trống) + số tệp theo nhãn học — cái
    nhìn từ phía kho; tab 360° chỉ thấy khách đã có tài liệu học xong."""
    require_reviewer(user)
    return _kho_hoac_400(kho.danh_sach_thu_muc_khach, q=(q or "")[:200],
                         loc=(loc or "")[:30], offset=max(0, offset),
                         limit=max(1, min(limit, 500)))


@app.get("/kho/ho-so-khach/tep")
def kho_ho_so_khach_tep(user=Depends(current_user), path: str = ""):
    """Từng tệp trong MỘT thư mục khách (đệ quy) kèm nhãn học."""
    require_reviewer(user)
    return _kho_hoac_400(kho.tep_trong_thu_muc_khach, path)


@app.post("/kho/go")
def kho_go(body: KhoGoBody, user=Depends(current_user)):
    """Gỡ tài liệu khỏi kho: chỉ admin — bot ngừng dùng ngay, file chuyển sang
    thùng đã gỡ (không xoá hẳn)."""
    require(user, {"admin"})
    return _kho_hoac_400(kho.go_tai_lieu, body.document_id, user["id"])


class KhoHocBody(BaseModel):
    path: str
    auto_approve: bool = False


@app.post("/kho/hoc")
def kho_hoc(body: KhoHocBody, user=Depends(current_user)):
    """Học ngay một file đang nằm trong kho (chưa học / lỗi / nội dung đổi)."""
    require_reviewer(user)
    return _kho_hoac_400(kho.hoc_file, body.path, user["id"],
                         auto_approve=bool(body.auto_approve))


@app.post("/kho/quet")
def kho_quet(user=Depends(current_user)):
    """Khởi động bộ quét cả kho (python -m app.local_learn) chạy nền; chính
    sách duyệt như mọi lượt quét thường (không cờ tự duyệt)."""
    require_reviewer(user)
    return _kho_hoac_400(kho.bat_dau_quet, user["id"])


@app.get("/kho/tien-do")
def kho_tien_do(user=Depends(current_user)):
    """NHỊP HỌC cho thẻ theo dõi trên Tổng quan (18/09/2026).

    Trả lời đúng câu hỏi của người đang đổ tài liệu vào kho: "máy có đang học
    không, đã học thêm được bao nhiêu, còn kẹt gì". Cố ý KHÔNG đi đếm file
    trên đĩa — kho 35.000 tệp đếm mất hàng chục giây, mà thẻ này thăm dò 8
    giây một lần; mọi con số đều lấy từ CSDL bằng một lượt truy vấn.
    """
    require_reviewer(user)
    quet = kho.trang_thai_quet()
    nhip = {"phut_10": 0, "gio_1": 0, "hom_nay": 0, "cap_nhat_gio_1": 0}
    tong = {"tai_lieu": 0, "cho_duyet": 0}
    tu_luc_quet = None
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT count(*) FILTER (WHERE created_at >= now() - interval '10 minutes'),
                          count(*) FILTER (WHERE created_at >= now() - interval '1 hour'),
                          count(*) FILTER (WHERE created_at >= date_trunc('day', now())),
                          count(*) FILTER (WHERE updated_at >= now() - interval '1 hour'
                                             AND updated_at > created_at + interval '2 seconds'),
                          count(*) FILTER (WHERE NOT (approved AND label_verified)),
                          count(*)
                     FROM documents WHERE coalesce(active,true)""")
            r = cur.fetchone()
            nhip = {"phut_10": r[0], "gio_1": r[1], "hom_nay": r[2],
                    "cap_nhat_gio_1": r[3]}
            tong = {"cho_duyet": r[4], "tai_lieu": r[5]}
            if quet.get("started_at"):
                cur.execute("""SELECT count(*) FROM documents
                                WHERE coalesce(active,true)
                                  AND created_at >= %s::timestamptz""",
                            (quet["started_at"],))
                tu_luc_quet = cur.fetchone()[0]
            try:
                cur.execute("SELECT count(*) FROM ingest_failures "
                            "WHERE resolved_at IS NULL")
                tong["loi"] = cur.fetchone()[0]
            except Exception:  # noqa: BLE001 — kho cũ chưa migrate bảng lỗi
                conn.rollback()
                tong["loi"] = 0

    lan_cuoi = None
    try:
        raw = settings.get("drive_sync_status")
        data = json.loads(raw) if raw else None
        if data:
            counts = data.get("counts") or {}
            lan_cuoi = {
                "finished_at": data.get("finished_at"),
                "started_at": data.get("started_at"),
                "quet": counts.get("scanned") or 0,
                "moi": counts.get("new") or 0,
                "cap_nhat": counts.get("updated") or 0,
                "khong_doi": counts.get("unchanged") or 0,
                "loi": counts.get("errors") or 0,
            }
    except Exception:  # noqa: BLE001 — thiếu tóm tắt không được làm sập thẻ
        lan_cuoi = None

    return {"quet": quet, "nhip": nhip, "tong": tong,
            "tu_luc_quet": tu_luc_quet, "lan_cuoi": lan_cuoi}


class KhoThuMucBody(BaseModel):
    path: str = ""
    ten: str


@app.post("/kho/thu-muc")
def kho_thu_muc(body: KhoThuMucBody, user=Depends(current_user)):
    require_reviewer(user)
    return _kho_hoac_400(kho.tao_thu_muc, body.path, body.ten, user["id"])


@app.post("/kho/tai-len")
async def kho_tai_len(
    files: list[UploadFile] = File(...),
    path: str = Form(""),
    auto_approve: bool = Form(False),
    user=Depends(current_user),
):
    """Tải một hay nhiều file vào ĐÚNG thư mục trong kho rồi học ngay từng
    file. Mỗi file một kết quả riêng — một file hỏng không chặn các file khác."""
    require_reviewer(user)
    if len(files) > 20:
        raise HTTPException(400, "Mỗi lần tối đa 20 file")
    gioi_han = MAX_UPLOAD_MB * 1024 * 1024
    ket_qua = []
    for f in files:
        safe = _safe_filename(f.filename)
        try:
            dest = kho.cho_tai_len(path, safe)
        except kho.LoiKho as e:
            await f.close()
            ket_qua.append({"filename": safe, "ok": False, "loi": str(e)})
            continue
        size, qua_co = 0, False
        try:
            with dest.open("wb") as out:
                while chunk := await f.read(1024 * 1024):
                    size += len(chunk)
                    if size > gioi_han:
                        qua_co = True
                        break
                    out.write(chunk)
        finally:
            await f.close()
        if qua_co:
            dest.unlink(missing_ok=True)
            ket_qua.append({"filename": safe, "ok": False,
                            "loi": f"Tệp vượt quá {MAX_UPLOAD_MB} MB"})
            continue
        try:
            r = kho.hoc_file(kho.rel_cua(dest), user["id"], auto_approve=bool(auto_approve))
            r.update({"filename": safe, "bytes": size, "path": kho.rel_cua(dest)})
        except kho.LoiKho as e:
            # File vẫn nằm trong kho để admin thấy trạng thái "lỗi" trên cây và
            # quyết định gỡ hay sửa; bộ quét lần sau cũng sẽ thử lại.
            r = {"filename": safe, "ok": False, "loi": str(e), "bytes": size,
                 "path": kho.rel_cua(dest), "da_luu": True}
        ket_qua.append(r)
    return {"ok": all(x.get("ok") for x in ket_qua), "ket_qua": ket_qua}


# ---------- 7a-bis. CHI TIẾT MỘT TÀI LIỆU + QUAN HỆ VĂN BẢN ----------
def _doc_row_or_404(cur, doc_id: int):
    cur.execute("""SELECT d.id,d.title,d.doc_type,d.access_level,d.client_id,
                          d.department_id,dep.name,c.name,d.summary,d.source_kind,
                          d.created_at,d.so_hieu,d.loai_van_ban,d.trich_yeu,
                          d.ngay_ban_hanh,d.ngay_hieu_luc,d.trang_thai_hieu_luc,
                          d.extraction_status,
                          (SELECT count(*) FROM chunks WHERE document_id=d.id)
                     FROM documents d
                     LEFT JOIN clients c ON c.id=d.client_id
                     LEFT JOIN departments dep ON dep.id=d.department_id
                    WHERE d.id=%s AND coalesce(d.active,true)""", (doc_id,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Không thấy tài liệu")
    return row


def _quan_he_hien_thi(rel, user, rules, chieu):
    """Một dòng quan hệ đã lọc quyền hiển thị cho tài liệu đối ứng trong kho.

    Văn bản đích NGOÀI kho chỉ có số hiệu + tên (dữ liệu công khai của văn bản
    luật). Văn bản TRONG kho thì tiêu đề đi qua đúng cửa can_open_doc/mask_title
    như mọi danh sách khác — không mở thêm cửa phân quyền thứ ba.

    CHỐT CHE TÊN: `ten_nguon`/`ten_dich` là chuỗi DENORMALIZE trong bảng quan
    hệ (van_ban.ten_day_du của chính tài liệu đối ứng). Che mỗi `title` mà để
    hai trường đó nguyên văn là mở đúng cửa vừa khoá: bản án ở access_level
    'client' mang tên đương sự trong trích yếu, người phòng khác đọc được qua
    quan hệ của một văn bản luật họ mở được. Không mở được ⇒ giấu cả tên, số
    hiệu và document_id của phía bị che.
    """
    doc = rel.get("doc")
    hien_thi = {
        "id": rel["id"], "loai": rel["loai"],
        "loai_vn": van_ban.LOAI_QUAN_HE_VN.get(rel["loai"], rel["loai"]),
        "nguon": rel["nguon"], "ghi_chu": rel["ghi_chu"],
        "so_hieu_nguon": rel["so_hieu_nguon"], "ten_nguon": rel["ten_nguon"],
        "so_hieu_dich": rel["so_hieu_dich"], "ten_dich": rel["ten_dich"],
        "document_id": None, "title": None, "can_open": False,
        "trang_thai_hieu_luc": None,
    }
    if doc:
        d = {"access_level": doc["access_level"],
             "department_id": doc["department_id"], "doc_type": doc["doc_type"],
             "client_id": doc["client_id"], "title": doc["title"]}
        can_open = rag.can_open_doc(user["role"], user["dept_ids"],
                                    user["is_banqt"], d,
                                    can_finance=user["can_finance"],
                                    rules=rules, dept_codes=user["dept_codes"])
        hien_thi.update({
            "document_id": doc["document_id"] if can_open else None,
            "title": rag.mask_title(d, can_open),
            "can_open": can_open,
            "trang_thai_hieu_luc": doc["trang_thai_hieu_luc"] if can_open else None,
        })
        if not can_open:
            # Phía bị che là đầu KIA của quan hệ: chiều 'xuoi' thì đó là đích,
            # chiều 'nguoc' thì đó là nguồn.
            if chieu == "xuoi":
                hien_thi["ten_dich"] = None
                hien_thi["so_hieu_dich"] = None
            else:
                hien_thi["ten_nguon"] = None
                hien_thi["so_hieu_nguon"] = None
    return hien_thi


@app.get("/documents/{doc_id}/detail")
def document_detail(doc_id: int, user=Depends(current_user)):
    """Thẻ căn cước một tài liệu: metadata đầy đủ + VĂN BẢN LIÊN QUAN hai chiều.

    'Xuôi' = tài liệu này nói về ai (thay thế/sửa đổi/căn cứ văn bản nào);
    'ngược' = ai nói về nó (bị ai thay thế/sửa đổi/hướng dẫn). Mỗi dòng mang
    tiêu đề đầy đủ và mở được bản gốc nếu người xem có quyền.
    """
    require(user, INTERNAL_ROLES)
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            r = _doc_row_or_404(cur, doc_id)
            quan_he = (van_ban.doc_quan_he(cur, r[11]) if r[11]
                       else {"xuoi": [], "nguoc": []})
    doc = {"access_level": r[3], "department_id": r[5], "doc_type": r[2],
           "client_id": r[4], "title": r[1], "department_name": r[6]}
    rules = rag.load_access_rules()
    can_open = rag.can_open_doc(user["role"], user["dept_ids"], user["is_banqt"],
                                doc, can_finance=user["can_finance"],
                                rules=rules, dept_codes=user["dept_codes"])
    if not can_open:
        raise HTTPException(403, "Bạn không có quyền xem chi tiết tài liệu này")
    ten = van_ban.ten_day_du({"loai_van_ban": r[12], "trich_yeu": r[13]},
                             so_hieu=r[11])
    return {
        "id": r[0], "title": r[1], "doc_type": r[2], "access_level": r[3],
        "client_name": r[7], "department": r[6],
        "summary": r[8], "source_kind": r[9], "created_at": str(r[10])[:10],
        "so_hieu": r[11], "loai_van_ban": r[12], "trich_yeu": r[13],
        "ten_day_du": ten or r[1],
        "ngay_ban_hanh": str(r[14]) if r[14] else None,
        "ngay_hieu_luc": str(r[15]) if r[15] else None,
        "trang_thai_hieu_luc": r[16], "extraction_status": r[17],
        "so_doan": r[18], "can_open": True,
        "quan_he_xuoi": [_quan_he_hien_thi(q, user, rules, "xuoi")
                         for q in quan_he["xuoi"]],
        "quan_he_nguoc": [_quan_he_hien_thi(q, user, rules, "nguoc")
                          for q in quan_he["nguoc"]],
    }


class RelationIn(BaseModel):
    loai: str
    so_hieu_dich: str | None = None
    ten_dich: str | None = None
    ghi_chu: str | None = None


@app.post("/documents/{doc_id}/relations")
def document_relation_add(doc_id: int, body: RelationIn, user=Depends(current_user)):
    """Người duyệt nối tay một quan hệ mà máy bóc trượt. Khoá theo SỐ HIỆU —
    tài liệu chưa có số hiệu thì điền số hiệu trước (form duyệt / sửa metadata)."""
    require_reviewer(user)
    if body.loai not in van_ban.LOAI_QUAN_HE:
        raise HTTPException(422, "Loại quan hệ không hợp lệ")
    so_dich = van_ban.chuan_hoa_so_hieu(body.so_hieu_dich or "") or None
    ten_dich = (body.ten_dich or "").strip() or None
    if not (so_dich or ten_dich):
        raise HTTPException(422, "Cần số hiệu hoặc tên văn bản đích")
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            r = _doc_row_or_404(cur, doc_id)
            so_nguon = r[11]
            if not so_nguon:
                raise HTTPException(400, "Tài liệu này chưa có số hiệu — điền "
                                    "số hiệu ở phần duyệt nhãn/sửa metadata trước")
            ten_nguon = van_ban.ten_day_du(
                {"loai_van_ban": r[12], "trich_yeu": r[13]}, so_hieu=so_nguon)
            cur.execute(
                """INSERT INTO van_ban_quan_he
                     (so_hieu_nguon, ten_nguon, loai, so_hieu_dich, ten_dich,
                      nguon, ghi_chu, created_by)
                   SELECT %s,%s,%s,%s,%s,'manual',%s,%s
                    WHERE NOT EXISTS (
                      SELECT 1 FROM van_ban_quan_he
                       WHERE lower(so_hieu_nguon)=lower(%s) AND loai=%s
                         AND lower(coalesce(so_hieu_dich,''))=lower(coalesce(%s,''))
                         AND lower(coalesce(ten_dich,''))=lower(coalesce(%s,'')))
                   RETURNING id""",
                (so_nguon, ten_nguon, body.loai, so_dich, ten_dich,
                 (body.ghi_chu or "").strip() or None, user["id"],
                 so_nguon, body.loai, so_dich, ten_dich))
            row = cur.fetchone()
            if not row:
                raise HTTPException(409, "Quan hệ này đã tồn tại")
            if so_dich:
                van_ban.cap_nhat_hieu_luc(cur, [so_dich, so_nguon])
        db.audit(conn, user["id"], "add_doc_relation", "van_ban_quan_he", row[0],
                 {"document_id": doc_id, "loai": body.loai,
                  "so_hieu_dich": so_dich, "ten_dich": ten_dich})
    return {"ok": True, "id": row[0]}


@app.delete("/documents/{doc_id}/relations/{rel_id}")
def document_relation_delete(doc_id: int, rel_id: int, user=Depends(current_user)):
    """Gỡ một dòng quan hệ sai. Trạng thái hiệu lực KHÔNG tự đảo lại (máy chỉ
    đánh dấu chiều xấu đi) — nếu văn bản bị đánh dấu oan, sửa trạng thái ở
    PUT /documents/{id}/van-ban sau khi gỡ."""
    require_reviewer(user)
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            r = _doc_row_or_404(cur, doc_id)
            if not r[11]:
                raise HTTPException(404, "Tài liệu không có số hiệu — không có quan hệ nào")
            cur.execute("""DELETE FROM van_ban_quan_he
                            WHERE id=%s AND (lower(so_hieu_nguon)=lower(%s)
                                             OR lower(coalesce(so_hieu_dich,''))=lower(%s))""",
                        (rel_id, r[11], r[11]))
            if cur.rowcount == 0:
                raise HTTPException(404, "Không thấy quan hệ này của tài liệu")
        db.audit(conn, user["id"], "delete_doc_relation", "van_ban_quan_he",
                 rel_id, {"document_id": doc_id})
    return {"ok": True}


class VanBanMetaIn(BaseModel):
    so_hieu: str | None = None
    loai_van_ban: str | None = None
    trich_yeu: str | None = None
    ngay_ban_hanh: str | None = None
    ngay_hieu_luc: str | None = None
    trang_thai_hieu_luc: str | None = None


@app.put("/documents/{doc_id}/van-ban")
def document_meta_put(doc_id: int, body: VanBanMetaIn, user=Depends(current_user)):
    """Sửa danh tính văn bản của tài liệu ĐÃ duyệt (đường duyệt nhãn chỉ đi qua
    một lần). None = không đổi; chuỗi rỗng = xoá giá trị."""
    require_reviewer(user)
    if (body.trang_thai_hieu_luc
            and body.trang_thai_hieu_luc not in van_ban.TRANG_THAI_HIEU_LUC):
        raise HTTPException(422, "Trạng thái hiệu lực không hợp lệ")
    sets, vals = [], []
    for cot, gia_tri in (("so_hieu", body.so_hieu),
                         ("loai_van_ban", body.loai_van_ban),
                         ("trich_yeu", body.trich_yeu),
                         ("trang_thai_hieu_luc", body.trang_thai_hieu_luc)):
        if gia_tri is not None:
            gia_tri = gia_tri.strip()
            if cot == "so_hieu":
                gia_tri = van_ban.chuan_hoa_so_hieu(gia_tri)
            sets.append(f"{cot}=%s")
            vals.append(gia_tri or None)
    for cot, gia_tri in (("ngay_ban_hanh", body.ngay_ban_hanh),
                         ("ngay_hieu_luc", body.ngay_hieu_luc)):
        if gia_tri is not None:
            sets.append(f"{cot}=%s")
            vals.append(_ngay_hop_le(gia_tri, cot))
    if not sets:
        raise HTTPException(422, "Không có trường nào để sửa")
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            _doc_row_or_404(cur, doc_id)
            cur.execute(f"UPDATE documents SET {','.join(sets)},updated_at=now() "
                        "WHERE id=%s", (*vals, doc_id))
            # Số hiệu đổi có thể nối tài liệu vào các quan hệ đang treo.
            if body.so_hieu is not None:
                van_ban.cap_nhat_hieu_luc(cur)
        db.audit(conn, user["id"], "edit_doc_van_ban_meta", "documents", doc_id,
                 body.model_dump(exclude_none=True))
    return {"ok": True, "document_id": doc_id}


# ---------- 7b. HỒ SƠ KHÁCH 360° ----------
@app.get("/clients")
def clients_list(user=Depends(current_user)):
    """Danh sách khách hàng người dùng được phép thấy (theo phòng)."""
    require(user, INTERNAL_ROLES)
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            if user["is_banqt"]:
                cur.execute("""SELECT c.id,c.name,c.code,d.name FROM clients c
                               LEFT JOIN departments d ON d.id=c.department_id ORDER BY c.name""")
            else:
                cur.execute("""SELECT c.id,c.name,c.code,d.name FROM clients c
                               LEFT JOIN departments d ON d.id=c.department_id
                               WHERE c.department_id = ANY(%s) OR c.department_id IS NULL
                               ORDER BY c.name""",
                            (user["dept_ids"] or [-1],))
            rows = cur.fetchall()
    return [{"id": r[0], "name": r[1], "code": r[2], "department": r[3]} for r in rows]


@app.get("/clients/{client_id}/360")
def client_dossier(client_id: int, user=Depends(current_user)):
    """HỒ SƠ 360° của một khách. Chỉ Ban QT hoặc người cùng phòng khách."""
    require(user, INTERNAL_ROLES)
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT department_id FROM clients WHERE id=%s", (client_id,))
            row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Không thấy khách hàng")
    client_dept = row[0]
    # Khách chưa gán phòng (NULL) coi như dùng chung — mọi nội bộ xem được.
    if (not user["is_banqt"] and client_dept is not None
            and client_dept not in (user["dept_ids"] or [])):
        raise HTTPException(403, "Khách hàng này thuộc phòng khác — không có quyền xem")
    dossier = rag.client_360(client_id, user["dept_ids"], user["is_banqt"])
    if not dossier:
        raise HTTPException(404, "Không dựng được hồ sơ")
    # Giấy tờ trong hồ sơ mở được ngay tại chỗ (nút Xem/Tải về gọi
    # /files/{id}/preview|download) nên phải đi qua ĐÚNG cửa quyền của hai
    # endpoint đó — cùng một hàm can_open_doc, không mở cửa thứ hai. Đọc ma
    # trận MỘT LẦN cho cả danh sách.
    rules = rag.load_access_rules()
    for d in dossier["documents"]:
        doc = {"access_level": d["access_level"], "department_id": d["department_id"],
               "doc_type": d.pop("doc_type_raw"), "client_id": client_id,
               "title": d["title"], "department_name": d["department_name"]}
        can_open = rag.can_open_doc(user["role"], user["dept_ids"], user["is_banqt"],
                                    doc, can_finance=user["can_finance"],
                                    rules=rules, dept_codes=user["dept_codes"])
        d["title"] = rag.mask_title(doc, can_open)
        d["can_open"] = can_open
        if not can_open:
            d["summary"] = None
            d["has_file"] = False
    return dossier


@app.get("/alerts")
def alerts_list(user=Depends(current_user), limit: int = 100):
    """Cảnh báo vụ việc: quá hạn, sắp hết hạn, thiếu hạn, treo lâu.

    Tính trực tiếp từ view v_matter_alerts nên luôn đúng tại thời điểm gọi.
    Bảng matters không có RLS → phải tự lọc theo phòng ban ở đây."""
    require(user, INTERNAL_ROLES)
    sql = """SELECT matter_id, matter_code, matter_title, matter_type, status,
                    deadline, days_left, client_id, client_name, client_code,
                    kind, severity, last_doc_at
               FROM v_matter_alerts"""
    params = []
    if not user["is_banqt"]:
        sql += " WHERE department_id = ANY(%s)"
        params.append(user["dept_ids"] or [-1])
    # Gấp trước, trong mỗi mức thì hạn gần nhất lên đầu
    sql += """ ORDER BY CASE severity WHEN 'gap' THEN 0 ELSE 1 END,
                        days_left NULLS LAST, matter_id LIMIT %s"""
    params.append(limit)
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    items = [{"matter_id": r[0], "matter_code": r[1], "matter_title": r[2],
              "matter_type": r[3], "status": r[4],
              "deadline": str(r[5]) if r[5] else None, "days_left": r[6],
              "client_id": r[7], "client_name": r[8], "client_code": r[9],
              "kind": r[10],
              "kind_label": company_context.ALERT_KIND_VN.get(r[10], r[10]),
              "severity": r[11],
              "last_doc_at": str(r[12])[:10] if r[12] else None} for r in rows]
    return {"total": len(items),
            "urgent": sum(1 for x in items if x["severity"] == "gap"),
            "items": items}


class ProfileIn(BaseModel):
    history_note: str | None = None
    issues_note: str | None = None
    warnings: str | None = None
    suggestions: str | None = None


@app.post("/clients/{client_id}/profile")
def update_client_profile(client_id: int, body: ProfileIn, user=Depends(current_user)):
    """Cập nhật (train) hồ sơ 360°: lịch sử, vấn đề, cảnh báo, gợi ý.
    Chỉ người có quyền duyệt."""
    require_reviewer(user)
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO client_profiles
                (client_id,history_note,issues_note,warnings,suggestions,updated_by,updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,now())
                ON CONFLICT (client_id) DO UPDATE SET
                  history_note=COALESCE(EXCLUDED.history_note, client_profiles.history_note),
                  issues_note =COALESCE(EXCLUDED.issues_note,  client_profiles.issues_note),
                  warnings    =COALESCE(EXCLUDED.warnings,     client_profiles.warnings),
                  suggestions =COALESCE(EXCLUDED.suggestions,  client_profiles.suggestions),
                  updated_by=EXCLUDED.updated_by, updated_at=now()""",
                (client_id, body.history_note, body.issues_note, body.warnings,
                 body.suggestions, user["id"]))
        db.audit(conn, user["id"], "train_client_profile", "clients", client_id, {})
    return {"ok": True, "client_id": client_id}


# ---------- 7c. BỘ PHẬN ----------
@app.get("/departments")
def departments_list(user=Depends(current_user)):
    require(user, INTERNAL_ROLES)
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id,code,name FROM departments ORDER BY id")
            rows = cur.fetchall()
    return [{"id": r[0], "code": r[1], "name": r[2]} for r in rows]


# ---------- 8. Thống kê & sức khoẻ ----------
@app.get("/stats")
def stats():
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT
                (SELECT count(*) FROM documents),
                (SELECT count(*) FROM documents WHERE label_verified),
                -- Tài liệu ĐÃ GỠ (active=false) không còn chờ ai duyệt cả; đếm
                -- nó vào đây thì con số trên Tổng quan lệch với số của tab Duyệt
                -- nhãn (cùng điều kiện với /review/pending) và không ai hiểu vì sao.
                (SELECT count(*) FROM documents
                  WHERE NOT label_verified AND coalesce(active, true)),
                (SELECT count(*) FROM documents WHERE access_level='client' AND client_id IS NULL),
                (SELECT count(*) FROM chunks),
                (SELECT count(DISTINCT m.id) FROM messages m
                   JOIN answer_feedback f ON f.message_id=m.id
                  WHERE f.status='pending' AND f.rating='bad' AND m.review_status='pending'),
                (SELECT count(*) FROM messages WHERE promoted_doc_id IS NOT NULL),
                (SELECT count(*) FROM analysis_methods WHERE approved),
                (SELECT count(*) FROM clients),
                (SELECT count(*) FROM matters WHERE status <> 'hoan_thanh'),
                (SELECT count(*) FROM departments),
                (SELECT count(*) FROM answer_feedback WHERE status='pending')""")
            r = cur.fetchone()
    return {"tai_lieu": r[0], "da_duyet_nhan": r[1], "cho_duyet_nhan": r[2],
            "thieu_chu_so_huu": r[3], "so_doan": r[4], "hoi_thoai_cho_duyet": r[5],
            "da_hoc": r[6], "so_mau_phuong_phap": r[7],
            "so_khach": r[8], "vu_viec_dang_mo": r[9], "so_bo_phan": r[10],
            "bao_cao_cho_xu_ly": r[11]}


@app.get("/health")
def health():
    from app.models import check_models
    st = check_models()
    return {"database": db.check_connection(), **st}


# ---- Đọc giấy tờ cho web Đăng ký kinh doanh -------------------------------------
# Web ĐKKD là app công khai (khách tự điền hồ sơ, không có tài khoản ở đây).
# Không đăng nhập, không khoá API — khoá nhúng vào trang web là lộ. Thay vào đó:
#   1. Origin phải nằm trong DKKD_ALLOWED_ORIGINS ("chỉ web của tôi");
#   2. van tần suất theo IP (_dkkd_rate_check);
#   3. endpoint không chạm CSDL, không đọc kho — chỉ nhận ảnh, trả JSON.
# Chi tiết luồng + hợp đồng dữ liệu: app/dkkd_extract.py, deploy/DOC_GIAY_TO_DKKD.md
def _dkkd_gate(request: Request):
    if not dkkd_extract.ALLOWED_ORIGINS:
        raise HTTPException(503, "Chưa bật đọc giấy tờ ĐKKD trên máy chủ "
                                 "(thiếu DKKD_ALLOWED_ORIGINS trong .env)")
    if not dkkd_extract.origin_allowed(request.headers.get("origin"),
                                       request.headers.get("referer")):
        raise HTTPException(403, "Nguồn gọi không được phép")
    _dkkd_rate_check(request)


@app.post("/dkkd/extract")
async def dkkd_extract_documents(request: Request):
    """Nhận ảnh CCCD / hộ chiếu / Giấy ĐKDN, trả JSON 14 trường để app tự điền.

    Payload y hệt cái app đang gửi cho webhook n8n nên phía app chỉ đổi URL.
    Model thị giác nạp vào GPU lúc gọi và (mặc định) dỡ ngay sau khi trả lời."""
    _dkkd_gate(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Body phải là JSON") from None
    from fastapi.concurrency import run_in_threadpool
    try:
        docs = dkkd_extract.parse_documents(body)
        # Giải mã ảnh + chờ GPU vài giây tới vài chục giây: chạy ngoài event
        # loop để SSE của chat nội bộ không đứng theo.
        result = await run_in_threadpool(dkkd_extract.extract, docs)
    except dkkd_extract.DkkdError as e:
        raise HTTPException(e.status, e.message) from None
    return result


@app.get("/dkkd/status")
def dkkd_status():
    """Cho IT kiểm nhanh: model đã pull chưa, đang nằm trong VRAM không, đã khai
    origin chưa. Không lộ gì ngoài tên model (như /health)."""
    return dkkd_extract.status()


@app.get("/models")
def models_list(user=Depends(current_user)):
    """Model AI đang có trên máy chủ (Ollama) + model mặc định.

    Nội bộ đọc được để hiện bộ chọn model ngay ô chat. Việc ĐỔI model mặc định
    toàn hệ thống vẫn chỉ admin (qua Cài đặt AI / PUT settings)."""
    require(user, INTERNAL_ROLES)
    from app.models import check_models, generation_models
    st = check_models()
    return {
        "ollama": st["ollama"],
        "available": st.get("models", []),   # tên mọi model đã cài trên server
        # chỉ model SINH câu trả lời (loại model tạo vector) — cho bộ chọn ở ô chat
        "generation": generation_models(st.get("models", []), st.get("embed_model")),
        # Model đang nằm sẵn trong bộ nhớ → chọn nó thì không mất thời gian nạp.
        "loaded": st.get("loaded", []),
        "current": st.get("llm_model"),       # model mặc định đang dùng
        "current_ready": st.get("llm"),        # model mặc định có thật sự tồn tại không
        "embed_model": st.get("embed_model"),  # model tạo vector — cố định, không đổi
        "embed_ready": st.get("embed"),
        # Model gọi qua API ngoài. Danh sách RỖNG khi chưa cấu hình khoá API —
        # thà không hiện còn hơn cho chọn rồi báo lỗi. `cloud_enabled` cho biết
        # admin đã bật nhánh này chưa; chưa bật thì chọn cũng tự về Qwen local.
        "cloud": st.get("cloud", []),
        "cloud_enabled": st.get("cloud_enabled", False),
        "cloud_model": st.get("cloud_model"),
        "cloud_channels": st.get("cloud_channels"),
    }


@app.get("/models/benchmark")
def models_benchmark(user=Depends(current_user), model: str | None = None):
    """Đo tốc độ thật của máy chủ: đọc bao nhiêu token/giây, viết bao nhiêu.

    Hai con số này quyết định toàn bộ thời gian trả lời, và chúng phụ thuộc
    PHẦN CỨNG chứ không phụ thuộc lượng dữ liệu đã học. Có chúng thì tính được
    ngay câu hỏi nào sẽ vượt 100 giây (mức Cloudflare cắt kết nối).

    Chạy mất vài chục giây trên máy yếu nên chỉ admin gọi được.
    """
    require(user, {"admin"})
    from app.models import benchmark
    res = benchmark(model)
    if res.get("ok"):
        # Ước lượng thời gian một lượt hỏi điển hình — cho admin thấy hậu quả
        # của việc nới ngân sách.
        #
        # Chính sách 20/08/2026 đặt context_char_budget=0 và llm_num_predict=-1
        # (nghĩa là KHÔNG CẮT). Công thức cũ chia thẳng hai con số đó nên ra
        # ~2 giây trong khi máy chạy vài phút — sai tới mức admin nới thêm
        # ngân sách vì tưởng còn dư. Khi không có trần, phải ước từ trần THẬT:
        # số đoạn lấy về × độ dài mỗi đoạn, và cửa sổ ngữ cảnh của model.
        ctx_chars = settings.get_int("context_char_budget", 0)
        if ctx_chars <= 0:
            top_k = settings.get_int("retrieval_top_k", 24)
            per_chunk = settings.get_int("chunk_char_limit", 0)
            if per_chunk <= 0:
                per_chunk = 2500      # đoạn giữ trọn — cỡ trung bình đo trên kho
            ctx_chars = top_k * per_chunk
        # ~3 ký tự tiếng Việt cho một token, cộng hồ sơ công ty + lịch sử + câu hỏi
        est_prompt = ctx_chars / 3 + 2000
        cap = settings.get_int("llm_num_predict", -1)
        # -1/0 = không chặn độ dài; lấy độ dài câu trả lời điển hình đo được
        # trên kho này (~1200 token) thay cho một trần không tồn tại.
        est_out = cap if cap > 0 else 1200
        # Prompt không thể vượt cửa sổ ngữ cảnh — Ollama cắt phần đầu chứ không
        # đọc thêm. Cửa sổ chứa CẢ phần sinh ra, nên trần của prompt là
        # num_ctx trừ đi chỗ dành cho câu trả lời.
        num_ctx = settings.get_int("llm_num_ctx", 32768)
        if num_ctx > 0:
            est_prompt = min(est_prompt, max(num_ctx - est_out, 512))
        r, w = res.get("read_tok_s"), res.get("write_tok_s")
        if r and w:
            giay = est_prompt / r + est_out / w
            # Lượt "bot đọc lại" là một lượt sinh NỮA, nhưng nó chỉ gửi câu hỏi
            # + bản nháp (rag.review_answer), KHÔNG gửi lại tài liệu tham chiếu
            # — nên cộng đúng phần đó, đừng nhân đôi cả thời gian đọc ngữ cảnh.
            mode = (settings.get("answer_review", "auto") or "auto").strip().lower()
            them = est_out / r + est_out / w
            ghi_chu = ""
            if mode == "always":
                giay += them
                ghi_chu = ", đã cộng lượt bot đọc lại"
            elif mode not in ("off", "0", "false", "no"):
                # auto: chỉ chạy khi câu trả lời có dấu hiệu chưa ổn — mà câu
                # dài hơn REVIEW_LONG_CHARS là đã đủ bật. Câu trả lời điển hình
                # ở đây (~est_out token ≈ 3× ký tự) thường vượt ngưỡng đó, nên
                # báo cả mức xấu nhất thay vì im lặng bỏ qua.
                res["uoc_tinh_giay_toi_da"] = round(giay + them, 1)
                ghi_chu = ", chưa gồm lượt bot đọc lại (chạy khi câu dài)"
            res["uoc_tinh_giay"] = round(giay, 1)
            res["uoc_tinh_dien_giai"] = (
                f"~{int(est_prompt)} token đọc vào, ~{est_out} token viết ra"
                + ghi_chu)
    return res


# ---------- 8a. TỆP: TẢI LÊN / TẢI VỀ QUA WEB ----------
# Khác /upload (nhận text đã trích sẵn, chỉ dùng được .txt): các endpoint dưới đây
# nhận TỆP THẬT (pdf/docx/...), tự lưu vào đúng thư mục trên server, tự trích văn
# bản + OCR nếu là bản scan, rồi nạp vào kho. Không cần SSH, không cần chép tay.

DATA_RAW = Path(os.getenv("DATA_RAW", "./data/raw"))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "50"))
ALLOWED_UPLOAD_EXT = {".pdf", ".docx", ".xlsx", ".csv", ".txt", ".md",
                      # Ảnh chụp giấy tờ (CCCD, sơ yếu, CV…) — đọc bằng OCR,
                      # luôn vào hàng chờ duyệt vì OCR có thể sai ký tự.
                      ".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp"}


def _safe_filename(name: str) -> str:
    """Giữ tên gốc cho người dùng dễ nhận ra, nhưng loại ký tự nguy hiểm.
    Chặn cả path traversal (../) vì tên tệp do người dùng gửi lên."""
    name = Path(name or "").name                      # bỏ mọi thành phần đường dẫn
    name = re.sub(r"[^\w\s.\-()À-ỹ]", "_", name, flags=re.UNICODE).strip()
    return name[:150] or "tai_lieu"


@app.post("/files/upload")
async def files_upload(
    file: UploadFile = File(...),
    doc_type: str = Form("other"),
    access_level: str = Form("internal"),
    client_id: int | None = Form(None),
    matter_id: int | None = Form(None),
    department_id: int | None = Form(None),
    auto_approve: bool = Form(False),
    user=Depends(current_user),
):
    """Tải tệp lên từ giao diện web → lưu vào server → nạp vào kho tri thức.

    auto_approve=true (chỉ người có quyền duyệt) → dùng được ngay.
    Mặc định false → vào hàng chờ duyệt nhãn.
    """
    require(user, INTERNAL_ROLES)
    if access_level == "client" and client_id is None:
        raise HTTPException(400, "Tài liệu mức 'client' bắt buộc chọn khách hàng")
    if auto_approve:
        require_reviewer(user)

    safe = _safe_filename(file.filename)
    ext = Path(safe).suffix.lower()
    if ext not in ALLOWED_UPLOAD_EXT:
        raise HTTPException(400, f"Chỉ nhận {', '.join(sorted(ALLOWED_UPLOAD_EXT))}")

    # Cấu trúc lưu: data/raw/uploads/<doc_type>/<YYYY-MM>/<mã>_<tên gốc>
    dest_dir = DATA_RAW / "uploads" / doc_type / datetime.now().strftime("%Y-%m")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{uuid.uuid4().hex[:8]}_{safe}"

    size = 0
    limit = MAX_UPLOAD_MB * 1024 * 1024
    try:
        with dest.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"Tệp vượt quá {MAX_UPLOAD_MB} MB")
                out.write(chunk)
    except HTTPException:
        dest.unlink(missing_ok=True)
        raise
    finally:
        await file.close()

    from app.ingest import ingest_file
    try:
        doc_id = ingest_file(
            dest, doc_type=doc_type, access_level=access_level, client_id=client_id,
            department_id=department_id, matter_id=matter_id,
            approved=auto_approve, label_verified=auto_approve, source_kind="web",
        )
    except Exception as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(500, f"Không nạp được tài liệu: {e}")

    if not doc_id:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, "Không trích được nội dung văn bản từ tệp này")

    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE documents SET uploaded_by=%s WHERE id=%s", (user["id"], doc_id))
            cur.execute("SELECT approved,extraction_status FROM documents WHERE id=%s", (doc_id,))
            actual_approved, extraction_status = cur.fetchone()
        db.audit(conn, user["id"], "web_upload", "documents", doc_id,
                 {"file": safe, "bytes": size, "auto_approve": auto_approve})

    if extraction_status == "warning":
        note = "Đã trích xuất nhưng có cảnh báo; bắt buộc duyệt thủ công trước khi dùng."
    else:
        note = "Đã nạp vào kho." if actual_approved else "Đã vào hàng chờ duyệt nhãn."
    return {"ok": True, "document_id": doc_id, "filename": safe, "bytes": size,
            "stored_path": str(dest),
            "extraction_status": extraction_status, "note": note}


def _original_file(doc_id: int, user) -> tuple[Path, str]:
    """Tìm tệp gốc của tài liệu VÀ kiểm quyền mở — dùng chung cho tải về lẫn
    xem trước, để hai cửa không bao giờ lệch nhau về phân quyền.

    Quyền mở dùng CHUNG một hàm với cơ chế che tên (rag.can_open_doc) nên
    không thể mở thứ mình không được xem. Đường dẫn bị nhốt trong DATA_RAW.

    Tài khoản khách chỉ vào được khi đã bật chức năng "Xem và tải tài liệu",
    và can_open_doc chặn tiếp theo mã khách: chỉ hồ sơ của chính họ.
    """
    require(user, INTERNAL_ROLES | CLIENT_ROLES)
    if user["role"] in CLIENT_ROLES:
        _can_tinh_nang(user, "tai_lieu")
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT d.title, d.source_path, d.access_level, d.department_id,
                                  d.doc_type, d.client_id, dep.name
                             FROM documents d
                             LEFT JOIN departments dep ON dep.id=d.department_id
                            WHERE d.id=%s""", (doc_id,))
            row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Không thấy tài liệu")

    doc = {"access_level": row[2], "department_id": row[3], "doc_type": row[4],
           "client_id": row[5], "title": row[0], "department_name": row[6]}
    if not rag.can_open_doc(user["role"], user["dept_ids"], user["is_banqt"], doc,
                            can_finance=user["can_finance"],
                            rules=rag.load_access_rules(),
                            dept_codes=user["dept_codes"],
                            client_id=user.get("client_id")):
        raise HTTPException(403, "Tài khoản chưa có quyền mở tài liệu này")

    if not row[1]:
        raise HTTPException(404, "Tài liệu này không có tệp gốc (nạp từ hội thoại)")
    path = Path(row[1])
    if not path.is_absolute():
        path = Path.cwd() / path
    # Chốt an toàn: đường dẫn phải nằm trong một trong các thư mục dữ liệu.
    # Dùng CHUNG local_learn.allowed_roots (KHO tài liệu + DATA_RAW) — tách kho
    # ra ổ khác mà rào chỉ biết DATA_RAW thì mọi nút Tải về/Xem trước trả 404.
    from app.local_learn import allowed_roots
    try:
        resolved = path.resolve(strict=True)
    except (FileNotFoundError, OSError):
        raise HTTPException(404, "Tệp gốc không còn trên máy chủ")
    for root in allowed_roots():
        try:
            resolved.relative_to(root)
            break
        except ValueError:
            continue
    else:
        raise HTTPException(404, "Tệp gốc nằm ngoài thư mục dữ liệu được phép")
    return resolved, row[0] or resolved.stem


@app.get("/files/{doc_id}/download")
def files_download(doc_id: int, user=Depends(current_user)):
    """Tải bản gốc tài liệu về máy người dùng."""
    _can_tinh_nang(user, "tai_lieu")
    resolved, _title = _original_file(doc_id, user)
    with db.session(role="internal", admin=True) as conn:
        db.audit(conn, user["id"], "download_document", "documents", doc_id, {})
    return FileResponse(resolved, filename=resolved.name.split("_", 1)[-1])


# Các định dạng trình duyệt tự mở được — trả thẳng, không cần chuyển đổi.
_INLINE_SUFFIXES = {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".txt", ".md"}
# Định dạng Office: chuyển sang PDF một lần bằng LibreOffice rồi cache lại.
_CONVERT_SUFFIXES = {".docx", ".doc", ".xlsx", ".csv"}
DATA_WORK = Path(os.getenv("DATA_WORK", "./data/work"))


def _preview_pdf(resolved: Path, cache_key) -> Path:
    """Bản PDF xem trước của một file Office, sinh một lần rồi dùng lại.

    cache_key: id tài liệu trong kho, hoặc "fill-<token>" cho file vừa điền.
    Cache theo mtime: file gốc đổi (Drive đồng bộ bản mới) thì sinh lại.
    LibreOffice đã có sẵn trên máy chủ (update.sh cài libreoffice-writer cho
    khâu đọc .doc) — máy dev thiếu thì trả 409 để giao diện lùi về nút Tải về.
    """
    import shutil as _shutil
    import subprocess
    import tempfile

    out_dir = DATA_WORK / "preview"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / (re.sub(r"[^A-Za-z0-9_-]", "_", str(cache_key)) + ".pdf")
    try:
        if out.exists() and out.stat().st_mtime >= resolved.stat().st_mtime:
            return out
    except OSError:
        pass
    soffice = _shutil.which("libreoffice") or _shutil.which("soffice")
    if not soffice:
        raise HTTPException(409, "Máy chủ chưa có LibreOffice để tạo bản xem "
                                 "trước — hãy dùng nút Tải về.")
    with tempfile.TemporaryDirectory() as tmp:
        # Hồ sơ LibreOffice riêng cho mỗi lượt — cùng lý do với khâu đọc .doc
        # trong ingest: hai lượt chuyển đổi chạy song song không giẫm profile.
        cmd = [soffice, "--headless", "--convert-to", "pdf",
               "--outdir", tmp, f"-env:UserInstallation=file://{tmp}/profile",
               str(resolved)]
        try:
            subprocess.run(cmd, capture_output=True, timeout=120, check=True)
        except (subprocess.SubprocessError, OSError):
            raise HTTPException(409, "Chưa chuyển được file này sang PDF để xem "
                                     "trước — hãy dùng nút Tải về.")
        produced = Path(tmp) / (resolved.stem + ".pdf")
        if not produced.exists():
            raise HTTPException(409, "Chưa chuyển được file này sang PDF để xem "
                                     "trước — hãy dùng nút Tải về.")
        _shutil.move(str(produced), str(out))
    return out


def _don_preview_fill(now: float | None = None):
    """File đã điền là hàng tạm 7 ngày — bản PDF xem trước của nó cũng vậy,
    không thì thư mục preview phình theo mỗi lượt điền bộ."""
    from app.template_fill import FILL_KEEP_HOURS
    root = DATA_WORK / "preview"
    if not root.exists():
        return
    cutoff = (now or time.time()) - FILL_KEEP_HOURS * 3600
    for child in root.glob("fill-*.pdf"):
        try:
            if child.stat().st_mtime < cutoff:
                child.unlink(missing_ok=True)
        except OSError:
            continue


@app.get("/files/{doc_id}/preview")
def files_preview(doc_id: int, user=Depends(current_user)):
    """XEM TRƯỚC bản gốc ngay trong trình duyệt (không phải tải về).

    PDF/ảnh/text trả thẳng; .docx/.doc/.xlsx chuyển sang PDF một lần bằng
    LibreOffice rồi cache ở data/work/preview. Cùng chốt quyền với tải về
    (_original_file) — không có cửa phân quyền thứ hai."""
    _can_tinh_nang(user, "tai_lieu")
    resolved, title = _original_file(doc_id, user)
    suffix = resolved.suffix.lower()
    with db.session(role="internal", admin=True) as conn:
        db.audit(conn, user["id"], "preview_document", "documents", doc_id, {})
    if suffix in _INLINE_SUFFIXES:
        media = {".pdf": "application/pdf", ".txt": "text/plain; charset=utf-8",
                 ".md": "text/plain; charset=utf-8"}.get(suffix)
        return FileResponse(resolved, media_type=media,
                            filename=resolved.name.split("_", 1)[-1],
                            content_disposition_type="inline")
    if suffix in {".tif", ".tiff", ".bmp"} or suffix in _CONVERT_SUFFIXES:
        if suffix in {".tif", ".tiff", ".bmp"}:
            # Trình duyệt không mở TIFF/BMP — nhóm này chưa có bản xem trước.
            raise HTTPException(409, "Định dạng ảnh này trình duyệt không mở "
                                     "được — hãy dùng nút Tải về.")
        pdf = _preview_pdf(resolved, doc_id)
        return FileResponse(pdf, media_type="application/pdf",
                            filename=f"{title}.pdf",
                            content_disposition_type="inline")
    raise HTTPException(409, "Định dạng này chưa có bản xem trước — hãy dùng "
                             "nút Tải về.")


# ---------- 8a2. FILE MẪU: DANH SÁCH + TẢI BẢN ĐÃ ĐIỀN ----------
@app.get("/templates/files")
def template_files(user=Depends(current_user)):
    """Danh sách file trong kệ HỢP ĐỒNG MẪU / THƯ MẪU - BIỂU MẪU cho menu
    "Tạo file mẫu" dưới khung chat. Đi qua RLS của chính người hỏi."""
    require(user, INTERNAL_ROLES)
    with db.session(role="internal", dept_ids=user["dept_ids"],
                    is_banqt=user["is_banqt"],
                    can_finance=user["can_finance"]) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT id, title, doc_type, source_path,
                                  access_level, department_id, client_id
                             FROM documents
                            WHERE doc_type IN ('mau_hd','thu_mau')
                              AND approved AND label_verified
                              AND coalesce(active,true)
                            ORDER BY doc_type, title""")
            rows = cur.fetchall()
    # RLS internal cho documents là USING(true) — quyền MỞ thật sự nằm ở ma
    # trận access_rules, cùng chốt với /files/{id}/download. Không lọc ở đây
    # là kê cho người dùng những mẫu mà bấm vào chỉ nhận 403.
    rules = rag.load_access_rules()
    items = []
    for doc_id, title, doc_type, source_path, access_level, dept_id, client_id in rows:
        doc = {"access_level": access_level, "department_id": dept_id,
               "doc_type": doc_type, "client_id": client_id, "title": title}
        if not rag.can_open_doc(user["role"], user["dept_ids"], user["is_banqt"],
                                doc, can_finance=user["can_finance"],
                                rules=rules, dept_codes=user["dept_codes"]):
            continue
        folder = ""
        if source_path:
            folder = Path(source_path).parent.name
        items.append({"id": doc_id, "title": title, "doc_type": doc_type,
                      "folder": folder,
                      "fillable": bool(source_path and
                                       source_path.lower().endswith(".docx"))})
    return {"items": items}


def _fill_cua_toi(token: str, user):
    """File đã tạo là CỦA RIÊNG người tạo (chủ dự án 18/09/2026: "bản nháp
    hoặc tạo file… là của người đó, không xem được của nhau; chỉ admin được
    toàn quyền").

    File sinh trước khi có chốt này không ghi chủ — vẫn cho mở (token là chuỗi
    32 ký tự ngẫu nhiên, chỉ người tạo mới có) và tất cả sẽ tự hết hạn trong 7
    ngày.
    """
    from app import template_fill as _tf
    chu = _tf.chu_so_huu(token)
    if chu is None or chu == user["id"]:
        return
    if user["role"] == "admin" or user.get("is_banqt"):
        return
    raise HTTPException(403, "File này do người khác tạo — bạn không mở được. "
                             "Hãy tự tạo bản của mình.")


@app.get("/template-fills/{token}/download")
def template_fill_download(token: str, user=Depends(current_user)):
    """Tải file mẫu ĐÃ ĐIỀN chủ thể (tạo từ khung chat). File là hàng tạm
    trong data/work/template_fills, của riêng người tạo, tự dọn sau 7 ngày."""
    require(user, INTERNAL_ROLES)
    from app import template_fill as _tf
    _fill_cua_toi(token, user)
    path = _tf.find_fill_file(token)
    if path is None:
        raise HTTPException(404, "File đã điền không còn trên máy chủ (quá 7 "
                                 "ngày hoặc token sai). Hãy tạo lại từ khung chat.")
    with db.session(role="internal", admin=True) as conn:
        db.audit(conn, user["id"], "download_template_fill", "template_fill",
                 None, {"token": token})
    return FileResponse(path, filename=path.name)


# ---------- 8a3. BỘ MẪU HỒ SƠ (nhóm .docx mẫu, điền cả bộ từ chat) ----------
class BoMauIn(BaseModel):
    ten: str
    mo_ta: str | None = None
    department_id: int | None = None     # None = cả công ty


class BoMauUpdate(BaseModel):
    ten: str | None = None
    mo_ta: str | None = None
    department_id: int | None = None
    # Cờ riêng vì department_id=None vừa có nghĩa "không đổi" vừa có nghĩa
    # "mở cho cả công ty" — người gọi phải nói rõ.
    doi_pham_vi: bool = False
    active: bool | None = None


def _bo_mau_or_404(bo_id: int, user):
    from app import bo_mau
    bo = bo_mau.get_set(bo_id, role=user["role"], dept_ids=user["dept_ids"],
                        is_banqt=user["is_banqt"])
    if not bo:
        raise HTTPException(404, "Bộ mẫu không tồn tại hoặc tài khoản chưa được xem")
    return bo


@app.get("/bo-mau")
def bo_mau_list(user=Depends(current_user)):
    """Các bộ mẫu người hỏi dùng được (phạm vi phòng ban), kèm file của từng bộ
    — menu "Bộ mẫu" dưới khung chat và tab Quản trị → Bộ mẫu hồ sơ."""
    require(user, INTERNAL_ROLES)
    from app import bo_mau
    items = bo_mau.list_sets(role=user["role"], dept_ids=user["dept_ids"],
                             is_banqt=user["is_banqt"])
    return {"items": items, "max_bo": bo_mau.MAX_BO,
            "max_file_moi_bo": bo_mau.MAX_FILE_MOI_BO,
            "co_quyen_sua": user["role"] == "admin" or bool(user["can_review"])}


@app.post("/bo-mau")
def bo_mau_create(body: BoMauIn, user=Depends(current_user)):
    require_reviewer(user)
    from app import bo_mau
    try:
        bo_id = bo_mau.create_set(body.ten, body.mo_ta, body.department_id, user["id"])
    except bo_mau.LoiBoMau as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "id": bo_id}


@app.put("/bo-mau/{bo_id}")
def bo_mau_update(bo_id: int, body: BoMauUpdate, user=Depends(current_user)):
    require_reviewer(user)
    from app import bo_mau
    _bo_mau_or_404(bo_id, user)
    try:
        changed = bo_mau.update_set(
            bo_id, user["id"], ten=body.ten, mo_ta=body.mo_ta,
            department_id=body.department_id if body.doi_pham_vi else bo_mau._KHONG_DOI,
            active=body.active)
    except bo_mau.LoiBoMau as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "changed": changed}


@app.delete("/bo-mau/{bo_id}")
def bo_mau_delete(bo_id: int, user=Depends(current_user)):
    require_reviewer(user)
    from app import bo_mau
    _bo_mau_or_404(bo_id, user)
    bo_mau.delete_set(bo_id, user["id"])
    return {"ok": True}


@app.post("/bo-mau/{bo_id}/files")
async def bo_mau_upload(bo_id: int, files: list[UploadFile] = File(...),
                        user=Depends(current_user)):
    """Tải một hay nhiều file .docx mẫu vào bộ. Mỗi file một kết quả riêng —
    một file hỏng không chặn các file khác (cùng lối với /kho/tai-len)."""
    require_reviewer(user)
    from app import bo_mau
    import tempfile
    _bo_mau_or_404(bo_id, user)
    if len(files) > bo_mau.MAX_FILE_MOI_BO:
        raise HTTPException(400, f"Mỗi lần tối đa {bo_mau.MAX_FILE_MOI_BO} file")
    gioi_han = MAX_UPLOAD_MB * 1024 * 1024
    ket_qua = []
    for f in files:
        safe = _safe_filename(f.filename)
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=Path(safe).suffix.lower(),
                                             delete=False) as tmp:
                tmp_path = Path(tmp.name)
                size = 0
                while chunk := await f.read(1024 * 1024):
                    size += len(chunk)
                    if size > gioi_han:
                        raise bo_mau.LoiBoMau(f"«{safe}» vượt quá {MAX_UPLOAD_MB} MB")
                    tmp.write(chunk)
            from fastapi.concurrency import run_in_threadpool
            item = await run_in_threadpool(bo_mau.add_file, bo_id, safe, tmp_path,
                                           user["id"])
            ket_qua.append({"ok": True, **item})
        except bo_mau.LoiBoMau as e:
            ket_qua.append({"ok": False, "ten_file": safe, "loi": str(e)})
        finally:
            await f.close()
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)
    return {"ok": any(k["ok"] for k in ket_qua), "ket_qua": ket_qua}


@app.delete("/bo-mau/{bo_id}/files/{file_id}")
def bo_mau_delete_file(bo_id: int, file_id: int, user=Depends(current_user)):
    require_reviewer(user)
    from app import bo_mau
    _bo_mau_or_404(bo_id, user)
    if not bo_mau.delete_file(bo_id, file_id, user["id"]):
        raise HTTPException(404, "File không có trong bộ này")
    return {"ok": True}


@app.get("/bo-mau/{bo_id}/files/{file_id}/download")
def bo_mau_download_file(bo_id: int, file_id: int, user=Depends(current_user)):
    """Tải bản gốc một file mẫu trong bộ (để xem chỗ trống, sửa rồi tải lại)."""
    require(user, INTERNAL_ROLES)
    from app import bo_mau
    bo = _bo_mau_or_404(bo_id, user)
    row = next((x for x in bo["files"] if int(x["id"]) == int(file_id)), None)
    if not row:
        raise HTTPException(404, "File không có trong bộ này")
    try:
        path = bo_mau.resolve_path(row["duong_dan"])
    except (FileNotFoundError, ValueError, OSError):
        raise HTTPException(404, "Tệp gốc không còn trên máy chủ — tải lại file vào bộ")
    with db.session(role="internal", admin=True) as conn:
        db.audit(conn, user["id"], "bo_mau_download_file", "bo_mau_file", file_id, {})
    return FileResponse(path, filename=row["ten_file"])


# ---------- 8a4. ĐIỀN CẢ BỘ TỪ TỜ KHAI (18/09/2026) ----------
# Nhân viên tải TỜ KHAI về, điền, tải lên → máy điền vào từng file của bộ rồi
# trả bản XEM NHANH ngay trên giao diện (app/bo_mau_dien.py). Dùng bộ mẫu là
# quyền của mọi vai nội bộ trong phạm vi — chỉ TẠO/SỬA bộ mới cần can_review.
MAX_FILE_DIEN = 10


@app.get("/bo-mau/{bo_id}/cho-trong")
def bo_mau_cho_trong(bo_id: int, user=Depends(current_user)):
    """Mọi chỗ trống {{…}} của bộ, gộp theo khoá — giao diện dựng form gõ tay
    và đối chiếu sau khi điền."""
    require(user, INTERNAL_ROLES)
    from app import bo_mau_dien
    bo = _bo_mau_or_404(bo_id, user)
    dong, loi = bo_mau_dien.quet_bo(bo)
    return {"bo": {"id": bo["id"], "ten": bo["ten"]}, "items": dong,
            "loi_mau": loi, "so_file": len(bo.get("files") or [])}


@app.get("/bo-mau/{bo_id}/to-khai")
def bo_mau_to_khai(bo_id: int, user=Depends(current_user)):
    """Tải TỜ KHAI THÔNG TIN (.docx) sinh từ mọi chỗ trống của bộ."""
    require(user, INTERNAL_ROLES)
    from app import bo_mau_dien
    from app.drafting import safe_export_name
    bo = _bo_mau_or_404(bo_id, user)
    dong, _loi = bo_mau_dien.quet_bo(bo)
    if not dong:
        raise HTTPException(409, "Các file mẫu trong bộ chưa có chỗ trống dạng "
                                 "{{TÊN_Ô}} nên chưa dựng được tờ khai. Mở file "
                                 "Word, đặt chỗ trống rồi tải lại vào bộ.")
    payload = bo_mau_dien.to_khai_bytes(bo, dong)
    with db.session(role="internal", admin=True) as conn:
        db.audit(conn, user["id"], "bo_mau_to_khai", "bo_mau", bo_id,
                 {"so_o": len(dong)})
    name = safe_export_name(f"To khai - {bo['ten']}", "docx")
    return Response(
        content=payload,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition":
                 f"attachment; filename*=UTF-8''{quote(name)}"})


@app.post("/bo-mau/{bo_id}/dien")
async def bo_mau_dien_ca_bo(bo_id: int,
                            files: list[UploadFile] = File(default=[]),
                            file_ids: str = Form(""),
                            gia_tri: str = Form(""),
                            dung_ai: bool = Form(True),
                            model: str = Form(""),
                            user=Depends(current_user)):
    """Điền dữ liệu vào TỪNG file của bộ.

    files: tờ khai đã điền / bản sao file mẫu đã gõ đè / hồ sơ rời (CCCD, giấy
    phép — chỉ dùng cho bước AI đoán ô còn trống). file_ids: JSON mảng id file
    trong bộ cần điền (rỗng = cả bộ). gia_tri: JSON {khoá ô: giá trị} người
    dùng gõ tay, thắng mọi nguồn khác."""
    import tempfile

    require(user, INTERNAL_ROLES)
    from app import bo_mau_dien
    from app.ingest import (ATTACHMENT_EXTENSIONS, ExtractionError,
                            extract_text_with_metadata)
    from fastapi.concurrency import run_in_threadpool

    bo = _bo_mau_or_404(bo_id, user)
    files = files or []
    if len(files) > MAX_FILE_DIEN:
        raise HTTPException(400, f"Mỗi lượt điền tối đa {MAX_FILE_DIEN} file tải lên")

    def _json_or_400(raw, kieu, ten):
        if not (raw or "").strip():
            return kieu()
        try:
            value = json.loads(raw)
        except ValueError:
            raise HTTPException(422, f"{ten} không phải JSON hợp lệ")
        if not isinstance(value, kieu):
            raise HTTPException(422, f"{ten} phải là {kieu.__name__}")
        return value

    chon_file = [int(x) for x in _json_or_400(file_ids, list, "file_ids")
                 if isinstance(x, (int, float, str)) and str(x).strip().isdigit()]
    co_trong_bo = {int(f["id"]) for f in (bo.get("files") or [])}
    if chon_file and not (set(chon_file) & co_trong_bo):
        # Không có id nào thuộc bộ: trả rỗng thì người dùng tưởng bộ hỏng.
        raise HTTPException(400, "Các file được chọn không thuộc bộ mẫu này "
                                 "(bộ vừa bị sửa?) — tải lại trang rồi chọn lại.")
    tay = {str(k): v for k, v in
           _json_or_400(gia_tri, dict, "gia_tri").items()}
    if len(tay) > bo_mau_dien.MAX_DONG_TO_KHAI:
        raise HTTPException(422, "Quá nhiều ô gõ tay trong một lượt")

    limit = MAX_UPLOAD_MB * 1024 * 1024
    uploads, doc_loi = [], []
    with tempfile.TemporaryDirectory() as tmp_dir:
        for f in files:
            safe = _safe_filename(f.filename or "ho_so")
            suffix = Path(safe).suffix.lower()
            if suffix not in ATTACHMENT_EXTENSIONS:
                doc_loi.append({"ten_file": safe,
                                "loi": f"chưa đọc được định dạng {suffix or '(không rõ)'}"})
                await f.close()
                continue
            dest = Path(tmp_dir) / f"{uuid.uuid4().hex[:8]}{suffix}"
            size = 0
            try:
                with dest.open("wb") as out:
                    while chunk := await f.read(1024 * 1024):
                        size += len(chunk)
                        if size > limit:
                            raise HTTPException(413, f"«{safe}» vượt quá {MAX_UPLOAD_MB} MB")
                        out.write(chunk)
            finally:
                await f.close()
            van_ban = ""
            try:
                extraction = await run_in_threadpool(extract_text_with_metadata, dest,
                                                     ATTACHMENT_EXTENSIONS)
                van_ban = extraction.text or ""
            except ExtractionError as e:
                # .docx vẫn mở được bằng python-docx để bóc tờ khai — chỉ mất
                # phần văn bản cho bước AI.
                doc_loi.append({"ten_file": safe, "loi": f"{e.message} {e.hint}".strip()})
            uploads.append({"ten_file": safe, "duong_dan": dest, "van_ban": van_ban})

        try:
            ket_qua = await run_in_threadpool(
                bo_mau_dien.chay, bo, uploads=uploads, file_ids=chon_file,
                gia_tri_tay=tay, dung_ai=bool(dung_ai),
                model=(model or "").strip() or None, user_id=user["id"])
        except bo_mau_dien.LoiDien as e:
            raise HTTPException(400, str(e))

    ket_qua["loi_tai_len"] = doc_loi
    with db.session(role="internal", admin=True) as conn:
        db.audit(conn, user["id"], "bo_mau_dien", "bo_mau", bo_id,
                 {"so_file_tai_len": len(uploads),
                  "so_file_dien": len([r for r in ket_qua["files"] if r["token"]]),
                  "so_o_dien": len(ket_qua["da_dien"]),
                  "so_o_thieu": len(ket_qua["con_thieu"]),
                  "dung_ai": bool(dung_ai)})
    return ket_qua


@app.post("/ho-so/theo-ban-cu")
async def ho_so_theo_ban_cu(cu: list[UploadFile] = File(...),
                            moi: list[UploadFile] = File(default=[]),
                            ghi_chu: str = Form(""),
                            model: str = Form(""),
                            user=Depends(current_user)):
    """Dựng bộ hồ sơ cho khách MỚI theo bộ hồ sơ khách CŨ — KHÔNG cần mã chỗ
    trống (18/09/2026).

    cu: các file .docx của khách cũ (giữ nguyên định dạng, chỉ thay thông tin
    chủ thể). moi: hồ sơ / form thông tin của khách mới (mọi định dạng máy đọc
    được). ghi_chu: người dùng gõ thêm (tên mới, mã số thuế mới…).
    """
    import tempfile

    require(user, INTERNAL_ROLES)
    from app import ho_so_cu
    from app.ingest import (ATTACHMENT_EXTENSIONS, ExtractionError,
                            extract_text_with_metadata)
    from fastapi.concurrency import run_in_threadpool

    cu, moi = cu or [], moi or []
    if len(cu) > ho_so_cu.MAX_FILE_CU:
        raise HTTPException(400, f"Mỗi lượt tối đa {ho_so_cu.MAX_FILE_CU} file hồ sơ cũ")
    if len(moi) > ho_so_cu.MAX_FILE_MOI:
        raise HTTPException(400, f"Mỗi lượt tối đa {ho_so_cu.MAX_FILE_MOI} file khách mới")

    limit = MAX_UPLOAD_MB * 1024 * 1024

    async def _nhan(f, tmp_dir, chi_docx: bool):
        """Lưu một file tải lên vào thư mục tạm, trả (tên, đường dẫn, lỗi)."""
        safe = _safe_filename(f.filename or "ho_so")
        suffix = Path(safe).suffix.lower()
        try:
            if chi_docx and suffix != ".docx":
                return safe, None, "bộ hồ sơ cũ chỉ nhận .docx (giữ định dạng Word)"
            if not chi_docx and suffix not in ATTACHMENT_EXTENSIONS:
                return safe, None, f"chưa đọc được định dạng {suffix or '(không rõ)'}"
            dest = Path(tmp_dir) / f"{uuid.uuid4().hex[:8]}{suffix}"
            size = 0
            with dest.open("wb") as out:
                while chunk := await f.read(1024 * 1024):
                    size += len(chunk)
                    if size > limit:
                        return safe, None, f"vượt quá {MAX_UPLOAD_MB} MB"
                    out.write(chunk)
            return safe, dest, None
        finally:
            await f.close()

    loi_tai_len = []
    with tempfile.TemporaryDirectory() as tmp_dir:
        files_cu = []
        for f in cu:
            ten, dest, loi = await _nhan(f, tmp_dir, chi_docx=True)
            if loi:
                loi_tai_len.append({"ten_file": ten, "loi": loi})
            else:
                files_cu.append({"ten_file": ten, "duong_dan": dest})
        files_moi = []
        for f in moi:
            ten, dest, loi = await _nhan(f, tmp_dir, chi_docx=False)
            if loi:
                loi_tai_len.append({"ten_file": ten, "loi": loi})
                continue
            van_ban = ""
            try:
                extraction = await run_in_threadpool(extract_text_with_metadata, dest,
                                                     ATTACHMENT_EXTENSIONS)
                van_ban = extraction.text or ""
            except ExtractionError as e:
                loi_tai_len.append({"ten_file": ten,
                                    "loi": f"{e.message} {e.hint}".strip()})
            files_moi.append({"ten_file": ten, "van_ban": van_ban})

        try:
            ket_qua = await run_in_threadpool(
                ho_so_cu.chay, files_cu, files_moi, ghi_chu,
                user_id=user["id"], model=(model or "").strip() or None)
        except ho_so_cu.LoiHoSoCu as e:
            raise HTTPException(400, str(e))

    ket_qua["loi_tai_len"] = loi_tai_len
    ket_qua["canh_bao"] = ho_so_cu.tom_tat_canh_bao(ket_qua)
    with db.session(role="internal", admin=True) as conn:
        db.audit(conn, user["id"], "ho_so_theo_ban_cu", "template_fill", None,
                 {"so_file_cu": len(files_cu), "so_file_moi": len(files_moi),
                  "so_file_tao": len([r for r in ket_qua["files"] if r["token"]])})
    return ket_qua


@app.get("/template-fills/{token}/xem")
def template_fill_xem(token: str, user=Depends(current_user)):
    """XEM NHANH nội dung file đã điền ngay trên giao diện (không tải về, không
    cần LibreOffice) — người soát đối chiếu số liệu trước khi lấy file."""
    require(user, INTERNAL_ROLES)
    from app import bo_mau_dien, template_fill as _tf
    _fill_cua_toi(token, user)
    path = _tf.find_fill_file(token)
    if path is None:
        raise HTTPException(404, "File đã điền không còn trên máy chủ (quá 7 "
                                 "ngày hoặc token sai).")
    if path.suffix.lower() != ".docx":
        raise HTTPException(409, "Gói .zip không có bản xem nhanh — hãy tải về.")
    try:
        noi_dung = bo_mau_dien.xem_nhanh(path)
    except Exception:  # noqa: BLE001
        raise HTTPException(409, "Không đọc được nội dung file này để xem nhanh "
                                 "— hãy tải về.")
    return {"ten_file": path.name, **noi_dung}


@app.get("/template-fills/{token}/preview")
def template_fill_preview(token: str, user=Depends(current_user)):
    """Bản PDF xem trước của file đã điền — giữ nguyên định dạng Word (cần
    LibreOffice trên máy chủ; thiếu thì 409 để giao diện lùi về xem nhanh)."""
    require(user, INTERNAL_ROLES)
    from app import template_fill as _tf
    _fill_cua_toi(token, user)
    path = _tf.find_fill_file(token)
    if path is None:
        raise HTTPException(404, "File đã điền không còn trên máy chủ (quá 7 "
                                 "ngày hoặc token sai).")
    if path.suffix.lower() != ".docx":
        raise HTTPException(409, "Gói .zip không có bản xem trước — hãy tải về.")
    _don_preview_fill()
    pdf = _preview_pdf(path, f"fill-{token}")
    return FileResponse(pdf, media_type="application/pdf",
                        filename=f"{path.stem}.pdf",
                        content_disposition_type="inline")


# ---------- 8a4. BỘ HỒ SƠ ĐÃ ĐIỀN — LƯU ĐỂ MỞ LẠI (7 ngày) ----------
class HoSoLuuFileIn(BaseModel):
    token: str
    ten_file: str = ""
    ten_ket_qua: str = ""
    so_trong: int = 0


class HoSoLuuOIn(BaseModel):
    khoa: str
    literal: str = ""
    goi_y: str = ""
    gia_tri: str = ""
    nguon: str = ""


class HoSoLuuIn(BaseModel):
    ten: str
    kieu: str = "bo_mau"
    bo_id: int | None = None
    bo_ten: str = ""
    files: list[HoSoLuuFileIn] = []
    zip_token: str | None = None
    so_o: int = 0
    da_dien: list[HoSoLuuOIn] = []
    con_thieu: list[HoSoLuuOIn] = []


class HoSoLuuTen(BaseModel):
    ten: str


def _ho_so_luu_ra(ban_ghi: dict, day_du: bool = False) -> dict:
    """Bản ghi trên đĩa → JSON cho giao diện.

    Thêm hai thứ chỉ biết lúc đọc: hạn còn lại, và file nào CÒN trên máy chủ —
    bản ghi sống cùng mốc 7 ngày với file nhưng một lượt dọn có thể xen vào
    giữa, đừng để người dùng bấm Tải rồi mới thấy 404.
    """
    from app import ho_so_da_luu as _hs, template_fill as _tf
    files = [{**f, "con": _tf.find_fill_file(f.get("token") or "") is not None}
             for f in (ban_ghi.get("files") or [])]
    zip_token = ban_ghi.get("zip_token")
    ra = {
        "ma": ban_ghi.get("ma"),
        "ten": ban_ghi.get("ten"),
        "kieu": ban_ghi.get("kieu"),
        "bo_id": ban_ghi.get("bo_id"),
        "bo_ten": ban_ghi.get("bo_ten"),
        "luc": ban_ghi.get("luc"),
        "so_o": ban_ghi.get("so_o") or 0,
        "so_da_dien": len(ban_ghi.get("da_dien") or []),
        "so_thieu": len(ban_ghi.get("con_thieu") or []),
        "so_file": len(files),
        "so_file_con": sum(1 for f in files if f["con"]),
        "con_lai_ngay": round(_hs.con_lai_ngay(ban_ghi), 2),
        "zip_token": zip_token,
        "zip_con": bool(zip_token) and _tf.find_fill_file(zip_token) is not None,
        "files": files,
    }
    if day_du:
        ra["da_dien"] = ban_ghi.get("da_dien") or []
        ra["con_thieu"] = ban_ghi.get("con_thieu") or []
    return ra


@app.get("/ho-so-da-luu")
def ho_so_da_luu_list(user=Depends(current_user)):
    """Hồ sơ đã điền mà NGƯỜI NÀY bấm Lưu — danh sách bên trái khu Soạn tài
    liệu. Không ai xem được của nhau (kể cả admin: bên Quản trị chỉ thấy số
    lượng và dung lượng, không mở nội dung)."""
    require(user, INTERNAL_ROLES)
    from app import ho_so_da_luu as _hs
    return {"items": [_ho_so_luu_ra(b) for b in _hs.danh_sach(user["id"])],
            "giu_ngay": _hs.GIU_NGAY, "toi_da": _hs.MAX_MOI_NGUOI}


@app.post("/ho-so-da-luu")
def ho_so_da_luu_tao(body: HoSoLuuIn, user=Depends(current_user)):
    """Lưu kết quả vừa điền để mở lại trong 7 ngày.

    Không nhân bản file: bản ghi chỉ trỏ tới token đã có. Mọi token phải là
    của chính người bấm Lưu — token do giao diện gửi lên nên phải soát lại,
    không tin lời khai của trình duyệt.
    """
    require(user, INTERNAL_ROLES)
    from app import ho_so_da_luu as _hs, template_fill as _tf
    if len(body.files) > _hs.MAX_FILE:
        raise HTTPException(422, f"Một bộ tối đa {_hs.MAX_FILE} file")
    if len(body.da_dien) > _hs.MAX_O or len(body.con_thieu) > _hs.MAX_O:
        raise HTTPException(422, "Bảng đối chiếu quá dài")
    tokens = [f.token for f in body.files if f.token]
    if body.zip_token:
        tokens.append(body.zip_token)
    if not tokens:
        raise HTTPException(400, "Chưa có file kết quả nào để lưu — hãy bấm "
                                 "Điền trước.")
    mat = []
    for tk in tokens:
        _fill_cua_toi(tk, user)
        if _tf.find_fill_file(tk) is None:
            mat.append(tk)
    if mat:
        raise HTTPException(404, "Một số file kết quả không còn trên máy chủ "
                                 "(quá 7 ngày) — hãy điền lại rồi lưu.")
    ban_ghi = _hs.luu(user_id=user["id"], ten=body.ten, kieu=body.kieu,
                      bo_id=body.bo_id, bo_ten=body.bo_ten,
                      files=[f.model_dump() for f in body.files],
                      zip_token=body.zip_token, so_o=body.so_o,
                      da_dien=[o.model_dump() for o in body.da_dien],
                      con_thieu=[o.model_dump() for o in body.con_thieu])
    with db.session(role="internal", admin=True) as conn:
        db.audit(conn, user["id"], "luu_ho_so_da_dien", "template_fill", None,
                 {"ma": ban_ghi["ma"], "so_file": len(ban_ghi["files"]),
                  "so_thieu": len(ban_ghi["con_thieu"]), "kieu": ban_ghi["kieu"]})
    return _ho_so_luu_ra(ban_ghi, day_du=True)


@app.get("/ho-so-da-luu/{ma}")
def ho_so_da_luu_get(ma: str, user=Depends(current_user)):
    """Mở lại một hồ sơ đã lưu — kèm bảng đối chiếu để điền lại chỗ còn thiếu."""
    require(user, INTERNAL_ROLES)
    from app import ho_so_da_luu as _hs
    ban_ghi = _hs.lay(ma, user["id"])
    if ban_ghi is None:
        raise HTTPException(404, "Hồ sơ đã lưu không còn (quá 7 ngày) hoặc "
                                 "không phải của bạn.")
    return _ho_so_luu_ra(ban_ghi, day_du=True)


@app.put("/ho-so-da-luu/{ma}")
def ho_so_da_luu_doi_ten(ma: str, body: HoSoLuuTen, user=Depends(current_user)):
    require(user, INTERNAL_ROLES)
    from app import ho_so_da_luu as _hs
    ban_ghi = _hs.doi_ten(ma, user["id"], body.ten)
    if ban_ghi is None:
        raise HTTPException(404, "Hồ sơ đã lưu không còn hoặc không phải của bạn.")
    return _ho_so_luu_ra(ban_ghi)


@app.delete("/ho-so-da-luu/{ma}")
def ho_so_da_luu_xoa(ma: str, user=Depends(current_user)):
    """Xoá bản ghi. File .docx vẫn tự hết hạn theo lịch 7 ngày của nó."""
    require(user, INTERNAL_ROLES)
    from app import ho_so_da_luu as _hs
    if not _hs.xoa(ma, user["id"]):
        raise HTTPException(404, "Hồ sơ đã lưu không còn hoặc không phải của bạn.")
    with db.session(role="internal", admin=True) as conn:
        db.audit(conn, user["id"], "xoa_ho_so_da_luu", "template_fill", None,
                 {"ma": ma})
    return {"ok": True}


# ---------- 8b. CÀI ĐẶT AI (phong cách tư vấn, bản đồ Drive) ----------
@app.get("/settings")
def settings_get(user=Depends(current_user)):
    """Đọc toàn bộ cài đặt. Chỉ admin — đây là nơi chứa prompt và bản đồ Drive."""
    require(user, {"admin"})
    return {"settings": settings.get_all(), "editable_keys": sorted(settings.EDITABLE_KEYS),
            "defaults": settings.DEFAULTS}


class SettingIn(BaseModel):
    value: str


@app.put("/settings/{key}")
def settings_put(key: str, body: SettingIn, user=Depends(current_user)):
    """Sửa một cài đặt. Có hiệu lực ngay ở câu hỏi tiếp theo, không cần khởi động lại."""
    require(user, {"admin"})
    try:
        settings.set(key, body.value, user["id"])
    except json.JSONDecodeError:
        raise HTTPException(400, "Giá trị không phải JSON hợp lệ")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "key": key}


@app.post("/settings/{key}/reset")
def settings_reset(key: str, user=Depends(current_user)):
    """Trả một cài đặt về giá trị mặc định trong mã nguồn."""
    require(user, {"admin"})
    if key not in settings.EDITABLE_KEYS:
        raise HTTPException(400, f"Khoá cài đặt không hợp lệ: {key}")
    return {"ok": True, "key": key, "value": settings.reset(key, user["id"])}


# ---------- 8c. BÁO CÁO CHẤT LƯỢNG CÂU TRẢ LỜI ----------
class FeedbackIn(BaseModel):
    message_id: int
    rating: str                  # 'good' | 'bad'
    note: str | None = None


@app.post("/feedback")
def feedback_create(body: FeedbackIn, user=Depends(current_user)):
    """MỌI vai đều gửi được — nút nhỏ cạnh câu trả lời của AI trong chat."""
    if body.rating not in ("good", "bad"):
        raise HTTPException(400, "rating chỉ nhận 'good' hoặc 'bad'")
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            # Chỉ cho báo cáo tin nhắn của AI, và phải thuộc hội thoại của chính mình
            # (admin/ban_qt được báo cáo mọi tin) — chặn dò tin nhắn người khác.
            cur.execute("""SELECT m.id FROM messages m
                           JOIN conversations cv ON cv.id = m.conversation_id
                           WHERE m.id=%s AND m.role='assistant'
                             AND (cv.user_id=%s OR %s)""",
                        (body.message_id, user["id"], user["role"] in ("admin", "ban_qt")))
            if not cur.fetchone():
                raise HTTPException(404, "Không thấy câu trả lời này trong hội thoại của bạn")
            cur.execute("""INSERT INTO answer_feedback (message_id,user_id,rating,note)
                           VALUES (%s,%s,%s,%s) RETURNING id""",
                        (body.message_id, user["id"], body.rating, body.note))
            fid = cur.fetchone()[0]
        db.audit(conn, user["id"], "send_feedback", "messages", body.message_id,
                 {"rating": body.rating})
    return {"ok": True, "feedback_id": fid}


@app.delete("/feedback/{fid}")
def feedback_retract(fid: int, user=Depends(current_user)):
    """Rút lại đánh giá của CHÍNH mình (lỡ bấm nhầm like/báo cáo).
    Chỉ rút được khi báo cáo còn 'pending' — admin chưa xử lý."""
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""DELETE FROM answer_feedback
                            WHERE id=%s AND user_id=%s AND status='pending'""",
                        (fid, user["id"]))
            deleted = cur.rowcount
    if not deleted:
        raise HTTPException(404, "Không rút được (đã được xử lý hoặc không phải của bạn)")
    return {"ok": True, "id": fid}


@app.get("/feedback/pending")
def feedback_pending(user=Depends(current_user), limit: int = 50):
    """Hàng chờ xử lý báo cáo. Chỉ admin hoặc người được cấp quyền duyệt."""
    require_reviewer(user)
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT f.id, f.message_id, f.rating, f.note, f.created_at,
                                  u.full_name, u.role, m.content,
                                  (SELECT content FROM messages
                                    WHERE conversation_id=m.conversation_id
                                      AND role='user' AND id<m.id
                                    ORDER BY id DESC LIMIT 1)
                             FROM answer_feedback f
                             JOIN messages m ON m.id=f.message_id
                             LEFT JOIN users u ON u.id=f.user_id
                            WHERE f.status='pending'
                            ORDER BY f.created_at DESC LIMIT %s""", (limit,))
            rows = cur.fetchall()
    return [{"id": r[0], "message_id": r[1], "rating": r[2], "note": r[3],
             "created_at": str(r[4]), "reporter": r[5], "reporter_role": r[6],
             "answer": r[7], "question": r[8]} for r in rows]


class FeedbackReviewIn(BaseModel):
    action: str                          # 'apply' | 'reject'
    corrected_answer: str | None = None  # bản sửa của admin (khi apply)
    admin_note: str | None = None
    access_level: str = "internal"


@app.post("/feedback/{fid}/review")
def feedback_review(fid: int, body: FeedbackReviewIn, user=Depends(current_user)):
    """Admin xử lý báo cáo.

    apply  → nạp câu hỏi + câu trả lời (đã sửa nếu có) thành tri thức lâu dài.
    reject → chỉ đóng báo cáo, không nạp gì.
    """
    require_reviewer(user)
    if body.action not in ("apply", "reject"):
        raise HTTPException(400, "action chỉ nhận 'apply' hoặc 'reject'")
    # Cùng lý do như /learn/{id}: bản ghi hỏi đáp không gắn client_id nào, đặt
    # mức 'client' là tạo tài liệu mồ côi — RLS lọc theo khách hàng nên không
    # ai đọc được, mà thống kê "thiếu chủ sở hữu" thì kêu mãi.
    if body.access_level not in ("internal", "public"):
        raise HTTPException(400, "access_level chỉ nhận 'internal' hoặc 'public'")

    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT f.message_id, m.content,
                                  (SELECT content FROM messages
                                    WHERE conversation_id=m.conversation_id
                                      AND role='user' AND id<m.id
                                    ORDER BY id DESC LIMIT 1)
                             FROM answer_feedback f JOIN messages m ON m.id=f.message_id
                            WHERE f.id=%s AND f.status='pending'""", (fid,))
            row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Không thấy báo cáo đang chờ xử lý")
    message_id, answer_text, question = row

    doc_id = None
    if body.action == "apply":
        final = (body.corrected_answer or answer_text).strip()
        if not final:
            raise HTTPException(400, "Nội dung nạp vào bộ nhớ không được để trống")
        content = f"HỎI: {question}\n\nTRẢ LỜI:\n{final}"
        from app.models import embed
        vec = embed(content)
        with db.session(role="internal", admin=True) as conn:
            with conn.cursor() as cur:
                cur.execute("""INSERT INTO documents (title,doc_type,access_level,approved,label_verified)
                               VALUES (%s,'advisory',%s,true,true) RETURNING id""",
                            (f"Hỏi đáp (từ báo cáo): {(question or '')[:60]}", body.access_level))
                doc_id = cur.fetchone()[0]
                cur.execute("""INSERT INTO chunks (document_id,chunk_index,content,access_level,doc_type,embedding)
                               VALUES (%s,0,%s,%s,'advisory',%s)""",
                            (doc_id, content, body.access_level, json.dumps(vec)))
                cur.execute("""UPDATE messages SET review_status='edited', reviewed_by=%s,
                               reviewed_at=now(), edited_content=%s, promoted_doc_id=%s
                               WHERE id=%s""",
                            (user["id"], body.corrected_answer, doc_id, message_id))

    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""UPDATE answer_feedback
                              SET status=%s, admin_note=%s, reviewed_by=%s, reviewed_at=now()
                            WHERE id=%s""",
                        ("applied" if body.action == "apply" else "rejected",
                         body.admin_note, user["id"], fid))
        db.audit(conn, user["id"], "review_feedback", "answer_feedback", fid,
                 {"action": body.action, "document_id": doc_id})

    return {"ok": True, "feedback_id": fid, "action": body.action, "document_id": doc_id}


# ---------- 11. Soạn tài liệu có nguồn ----------
# Router nhận lại chính dependency xác thực/duyệt ở file này để không sinh một
# cơ chế quyền thứ hai. Đăng ký trước route /admin; các endpoint được liệt kê
# trong OpenAPI như phần còn lại của ứng dụng.
# ---------- 12. HOÀN THIỆN GIAI ĐOẠN 1 (15/09/2026) ----------
# Bốn nhóm còn thiếu so với kế hoạch 10 ngày: khách quan tâm từ website
# (leads), nhật ký hệ thống xem trên web, lịch sử phiên bản tài liệu kho,
# rà soát rủi ro theo danh mục điều khoản chuẩn.

# ---- 12a. Khách quan tâm (form trên khung chat nhúng website) ----
LEAD_STATUSES = {"moi": "Mới", "da_lien_he": "Đã liên hệ", "bo_qua": "Bỏ qua"}
_RE_PHONE = re.compile(r"^\+?[0-9]{9,15}$")
_RE_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")


class LeadIn(BaseModel):
    name: str
    phone: str | None = None
    email: str | None = None
    need: str | None = None
    conversation_id: int | None = None
    # Ô bẫy: người thật không thấy, máy quét form điền bừa → bỏ lặng lẽ.
    website: str | None = None


def kiem_tra_lead(body: LeadIn) -> dict:
    """Làm sạch + kiểm tra form liên hệ. Trả dict sẵn sàng INSERT, hoặc ném 422.
    Tách riêng để test không cần CSDL."""
    name = " ".join((body.name or "").split())
    # Người gõ "091 234.5678" hay "+84-91…" đều là một số — chỉ giữ chữ số (và
    # dấu + đầu) rồi mới kiểm định dạng.
    phone = re.sub(r"[\s.\-()]", "", body.phone or "")
    email = (body.email or "").strip().lower()
    need = " ".join((body.need or "").split())
    if len(name) < 2 or len(name) > 120:
        raise HTTPException(422, "Vui lòng nhập họ tên (2–120 ký tự)")
    if not phone and not email:
        raise HTTPException(422, "Cần số điện thoại hoặc email để HDS liên hệ lại")
    if phone and not _RE_PHONE.match(phone):
        raise HTTPException(422, "Số điện thoại không hợp lệ")
    if email and (len(email) > 200 or not _RE_EMAIL.match(email)):
        raise HTTPException(422, "Email không hợp lệ")
    if len(need) > 2000:
        raise HTTPException(422, "Nội dung cần tư vấn tối đa 2.000 ký tự")
    return {"name": name, "phone": phone or None, "email": email or None,
            "need": need or None, "conversation_id": body.conversation_id}


@app.post("/leads")
def lead_create(body: LeadIn, request: Request):
    """Người dân để lại liên hệ từ khung chat trên website HDS (không đăng
    nhập). Dùng chung van chống spam theo IP của kênh công khai."""
    if (body.website or "").strip():
        return {"ok": True}           # bot điền ô bẫy — giả vờ nhận, không lưu
    lead = kiem_tra_lead(body)
    _public_rate_check(request)
    conv_id = lead["conversation_id"]
    if conv_id is not None:
        try:
            check_conversation(None, conv_id, "public")
        except HTTPException:
            conv_id = None            # id lạ → vẫn nhận liên hệ, chỉ bỏ liên kết
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO leads (name,phone,email,need,conversation_id,source,ip)
                           VALUES (%s,%s,%s,%s,%s,'website',%s) RETURNING id""",
                        (lead["name"], lead["phone"], lead["email"], lead["need"],
                         conv_id, _client_ip(request)))
            lead_id = cur.fetchone()[0]
        db.audit(conn, None, "lead_create", "leads", lead_id, {"source": "website"})
    return {"ok": True, "id": lead_id,
            "message": "HDS đã nhận thông tin, luật sư sẽ liên hệ lại sớm nhất."}


def _require_lead_viewer(user):
    if user["role"] not in SEE_ALL and not (user.get("can_review") and user["role"] == "truong_bph"):
        raise HTTPException(403, "Chỉ Ban quản trị / trưởng bộ phận xem danh sách khách quan tâm")


@app.get("/leads")
def leads_list(user=Depends(current_user), status: str = "", limit: int = 200):
    _require_lead_viewer(user)
    if status and status not in LEAD_STATUSES:
        raise HTTPException(422, "Trạng thái không hợp lệ")
    limit = max(1, min(limit, 500))
    sql = """SELECT l.id,l.name,l.phone,l.email,l.need,l.status,l.note,l.source,
                    l.conversation_id,l.created_at,l.handled_at,u.full_name
               FROM leads l LEFT JOIN users u ON u.id=l.handled_by WHERE true"""
    params: list = []
    if status:
        sql += " AND l.status=%s"; params.append(status)
    sql += " ORDER BY (l.status='moi') DESC, l.created_at DESC LIMIT %s"; params.append(limit)
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            cur.execute("SELECT status,count(*) FROM leads GROUP BY 1")
            dem = dict(cur.fetchall())
    return {"items": [{
        "id": r[0], "name": r[1], "phone": r[2], "email": r[3], "need": r[4],
        "status": r[5], "note": r[6], "source": r[7], "conversation_id": r[8],
        "created_at": r[9], "handled_at": r[10], "handled_by_name": r[11],
    } for r in rows], "counts": {k: int(dem.get(k, 0)) for k in LEAD_STATUSES},
        "statuses": LEAD_STATUSES}


class LeadPatch(BaseModel):
    status: str | None = None
    note: str | None = None


@app.patch("/leads/{lead_id}")
def lead_update(lead_id: int, body: LeadPatch, user=Depends(current_user)):
    _require_lead_viewer(user)
    if body.status is not None and body.status not in LEAD_STATUSES:
        raise HTTPException(422, "Trạng thái không hợp lệ")
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""UPDATE leads SET status=coalesce(%s,status), note=coalesce(%s,note),
                                  handled_by=%s, handled_at=now()
                            WHERE id=%s RETURNING id""",
                        (body.status, body.note, user["id"], lead_id))
            if not cur.fetchone():
                raise HTTPException(404, "Không thấy khách quan tâm")
        db.audit(conn, user["id"], "lead_update", "leads", lead_id,
                 {"status": body.status, "note": bool(body.note)})
    return {"ok": True}


# ---- 12b. Nhật ký hệ thống xem trên web (chỉ đọc; bảng có trigger cấm sửa/xoá) ----
def _require_audit_viewer(user):
    require(user, SEE_ALL)


def tom_tat_audit(action: str, entity: str | None, entity_id, detail) -> str:
    """Một dòng tiếng Việt dễ đọc cho từng bản ghi — người quản trị không phải
    đọc JSON."""
    d = detail if isinstance(detail, dict) else {}
    ten = {
        "chat_query": "Hỏi AI", "auto_learn": "Bộ quét học tài liệu",
        "auto_relabel": "Bộ quét gắn lại nhãn", "approve_label": "Duyệt nhãn tài liệu",
        "approve": "Duyệt", "delete_conversation": "Xoá hội thoại",
        "preview_document": "Xem trước tài liệu", "download_document": "Tải tài liệu",
        "generate_draft_version": "Sinh phiên bản bản thảo", "create_draft": "Tạo bản nháp",
        "delete_draft": "Xoá bản nháp", "approve_draft": "Duyệt bản thảo",
        "export_draft": "Xuất bản thảo", "export_draft_compare": "Xuất so sánh phiên bản",
        "run_draft_check": "Kiểm tra mâu thuẫn bản thảo",
        "update_setting": "Đổi cài đặt AI", "chat_temp_upload": "Đính kèm file trong chat",
        "edit_document_content": "Sửa nội dung tài liệu kho", "create_user": "Tạo người dùng",
        "update_user": "Sửa tài khoản", "reset_password": "Đặt lại mật khẩu",
        "change_password": "Đổi mật khẩu", "set_review_perm": "Cấp/thu quyền duyệt",
        "set_finance_perm": "Cấp/thu quyền xem công nợ", "set_user_features": "Bật/tắt chức năng",
        "issue_api_key": "Cấp khoá API", "revoke_api_key": "Thu hồi khoá API",
        "seed_accounts": "Tạo tài khoản ban đầu", "ra_soat_tai_khoan": "Rà soát tài khoản",
        "login": "Đăng nhập", "lead_create": "Khách để lại liên hệ",
        "lead_update": "Xử lý khách quan tâm", "legal_checklist": "Rà soát rủi ro hợp đồng",
        "learn_review": "Duyệt câu trả lời (tự học)", "feedback_review": "Xử lý phản hồi",
    }.get(action, action)
    phu = []
    for k in ("question", "title", "file", "version", "edit_reason", "status", "model"):
        if d.get(k) not in (None, "", []):
            phu.append(f"{k}={str(d[k])[:80]}")
    dau = f"{ten}"
    if entity and entity_id is not None:
        dau += f" · {entity}#{entity_id}"
    return dau + (" · " + ", ".join(phu) if phu else "")


@app.get("/audit")
def audit_list(user=Depends(current_user), limit: int = 200, offset: int = 0,
               action: str = "", user_id: int | None = None, q: str = ""):
    _require_audit_viewer(user)
    limit = max(1, min(limit, 1000)); offset = max(0, offset)
    sql = """SELECT a.id,a.user_id,u.full_name,u.email,a.action,a.entity,a.entity_id,
                    a.detail,a.created_at, c.name
               FROM audit_log a
               LEFT JOIN users u ON u.id=a.user_id
               LEFT JOIN clients c ON c.id=u.client_id
              WHERE true"""
    params: list = []
    if action:
        sql += " AND a.action=%s"; params.append(action)
    if user_id is not None:
        sql += " AND a.user_id=%s"; params.append(user_id)
    if q.strip():
        sql += " AND (a.detail::text ILIKE %s OR a.action ILIKE %s OR a.entity ILIKE %s)"
        like = f"%{q.strip()}%"; params += [like, like, like]
    sql += " ORDER BY a.id DESC LIMIT %s OFFSET %s"; params += [limit, offset]
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            cur.execute("SELECT count(*) FROM audit_log")
            tong = cur.fetchone()[0]
    items = []
    for r in rows:
        detail = r[7] if isinstance(r[7], dict) else (json.loads(r[7]) if r[7] else {})
        items.append({"id": r[0], "user_id": r[1], "user_name": r[2] or ("Hệ thống" if r[1] is None else None),
                      "user_email": r[3], "action": r[4], "entity": r[5], "entity_id": r[6],
                      "detail": detail, "created_at": r[8],
                      # Tài khoản khách: kèm tên hồ sơ khách để đọc nhật ký là
                      # biết ngay thao tác này của khách nào.
                      "client_name": r[9],
                      "tom_tat": tom_tat_audit(r[4], r[5], r[6], detail)})
    return {"items": items, "total": tong, "limit": limit, "offset": offset}


@app.get("/audit/actions")
def audit_actions(user=Depends(current_user)):
    _require_audit_viewer(user)
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT action,count(*) FROM audit_log GROUP BY 1 ORDER BY 2 DESC")
            rows = cur.fetchall()
    return {"items": [{"action": r[0], "count": r[1],
                       "label": tom_tat_audit(r[0], None, None, None)} for r in rows]}


# ---- 12c. Lịch sử phiên bản tài liệu kho + so sánh ----
def _noi_dung_phien_ban_tai_lieu(doc_id: int, version_no: int) -> str:
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT content FROM document_versions WHERE document_id=%s AND version_no=%s",
                        (doc_id, version_no))
            row = cur.fetchone()
    if not row:
        raise HTTPException(404, f"Không thấy phiên bản {version_no}")
    return row[0] or ""


@app.get("/documents/{doc_id}/versions")
def document_versions(doc_id: int, user=Depends(current_user)):
    require_reviewer(user)
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT title FROM documents WHERE id=%s", (doc_id,))
            if not cur.fetchone():
                raise HTTPException(404, "Không thấy tài liệu")
            cur.execute("""SELECT v.version_no,v.edit_reason,v.edit_note,v.created_at,
                                  u.full_name,length(v.content)
                             FROM document_versions v LEFT JOIN users u ON u.id=v.edited_by
                            WHERE v.document_id=%s ORDER BY v.version_no DESC""", (doc_id,))
            rows = cur.fetchall()
    return {"document_id": doc_id, "reasons": EDIT_REASONS, "items": [{
        "version_no": r[0], "edit_reason": r[1],
        "edit_reason_label": EDIT_REASONS.get(r[1], "Bản gốc" if r[1] == "ban_goc" else r[1]),
        "edit_note": r[2], "created_at": r[3], "edited_by_name": r[4] or "Hệ thống",
        "characters": r[5],
    } for r in rows]}


@app.get("/documents/{doc_id}/versions/compare")
def document_versions_compare(doc_id: int, tu: int, den: int, user=Depends(current_user)):
    require_reviewer(user)
    if tu == den:
        raise HTTPException(409, "Chọn hai phiên bản khác nhau")
    cu = _noi_dung_phien_ban_tai_lieu(doc_id, tu)
    moi = _noi_dung_phien_ban_tai_lieu(doc_id, den)
    ket_qua = so_sanh.so_sanh_van_ban(cu, moi)
    return {"document_id": doc_id, "tu": tu, "den": den, **ket_qua,
            "tom_tat": so_sanh.tom_tat_thay_doi(ket_qua)}


@app.get("/documents/{doc_id}/versions/compare/export")
def document_versions_compare_export(doc_id: int, tu: int, den: int, user=Depends(current_user)):
    require_reviewer(user)
    if tu == den:
        raise HTTPException(409, "Chọn hai phiên bản khác nhau")
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT title FROM documents WHERE id=%s", (doc_id,))
            row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Không thấy tài liệu")
    cu = _noi_dung_phien_ban_tai_lieu(doc_id, tu)
    moi = _noi_dung_phien_ban_tai_lieu(doc_id, den)
    payload = so_sanh.xuat_docx_theo_doi(cu, moi, f"{row[0]} — so sánh v{tu} → v{den}",
                                         tac_gia=user.get("name") or "HDS AI")
    return Response(payload,
                    media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={"Content-Disposition":
                             f"attachment; filename=\"document_{doc_id}_compare_v{tu}_v{den}.docx\""})


@app.get("/documents/{doc_id}/versions/{version_no}")
def document_version_get(doc_id: int, version_no: int, user=Depends(current_user)):
    require_reviewer(user)
    return {"document_id": doc_id, "version_no": version_no,
            "content": _noi_dung_phien_ban_tai_lieu(doc_id, version_no)}


# ---- 12d. Rà soát rủi ro theo danh mục điều khoản chuẩn (kế hoạch ngày 7–8) ----
RA_SOAT_MAX_CHARS = 500_000
RA_SOAT_TRA_LUAT_TOI_DA = 8


class RaSoatIn(BaseModel):
    text: str | None = None
    temp_file_id: int | None = None      # file đính kèm trong chat (dùng xong bỏ)
    draft_id: int | None = None          # bản thảo ở tab Soạn tài liệu
    document_id: int | None = None       # tài liệu trong kho
    loai: str | None = None              # ép loại hợp đồng; None = tự nhận diện
    tieu_de: str | None = None
    tra_luat: bool = True                # kèm đoạn luật trong kho cho mục cảnh báo/thiếu


def _van_ban_de_ra_soat(body: RaSoatIn, user) -> tuple[str, str]:
    """(nội dung, tiêu đề) từ đúng MỘT nguồn; mọi nguồn đều qua đúng cửa
    quyền hiện có (file tạm phải là của người hỏi; bản thảo qua _get_draft;
    tài liệu kho qua can_open_doc)."""
    if body.text and body.text.strip():
        return body.text, body.tieu_de or "Văn bản dán vào"
    if body.temp_file_id is not None:
        with db.session(role="internal", admin=True) as conn:
            with conn.cursor() as cur:
                cur.execute("""SELECT t.filename,t.content,t.user_id,c.user_id
                                 FROM temp_files t LEFT JOIN conversations c ON c.id=t.conversation_id
                                WHERE t.id=%s AND t.expires_at > now()""", (body.temp_file_id,))
                row = cur.fetchone()
        if not row:
            raise HTTPException(404, "File đính kèm không còn (đã quá 6 giờ) hoặc không tồn tại")
        if user["id"] not in (row[2], row[3]):
            raise HTTPException(403, "File đính kèm này không thuộc hội thoại của bạn")
        return row[1] or "", body.tieu_de or row[0] or "File đính kèm"
    if body.draft_id is not None:
        from app import draft_api
        detail = draft_api._detail(user, body.draft_id)
        latest = detail.get("latest_version") or {}
        if not latest.get("content_markdown"):
            raise HTTPException(409, "Bản nháp chưa có nội dung")
        return latest["content_markdown"], body.tieu_de or detail["title"]
    if body.document_id is not None:
        with db.session(role="internal", admin=True) as conn:
            with conn.cursor() as cur:
                cur.execute("""SELECT d.id,d.title,d.doc_type,d.access_level,d.client_id,
                                      d.department_id,dep.name
                                 FROM documents d LEFT JOIN departments dep ON dep.id=d.department_id
                                WHERE d.id=%s""", (body.document_id,))
                d = cur.fetchone()
                if not d:
                    raise HTTPException(404, "Không thấy tài liệu")
                doc = {"id": d[0], "title": d[1], "doc_type": d[2], "access_level": d[3],
                       "client_id": d[4], "department_id": d[5], "department_name": d[6]}
                if not rag.can_open_doc(user["role"], user["dept_ids"], user["is_banqt"], doc,
                                        can_finance=user["can_finance"],
                                        rules=rag.load_access_rules(),
                                        dept_codes=user["dept_codes"],
                                        client_id=user.get("client_id")):
                    raise HTTPException(403, "Không có quyền mở tài liệu này")
                cur.execute("SELECT content FROM chunks WHERE document_id=%s ORDER BY chunk_index",
                            (body.document_id,))
                text = "\n\n".join(_CTX_HEADER_RE.sub("", r[0] or "", count=1) for r in cur.fetchall())
        return text, body.tieu_de or d[1] or "Tài liệu kho"
    raise HTTPException(422, "Cần một nguồn: text, temp_file_id, draft_id hoặc document_id")


def _kem_can_cu_kho(muc: list[dict], user) -> None:
    """Gắn đoạn luật thật trong kho cho mục cảnh báo/thiếu — người đọc thấy
    nguyên văn điều luật, không chỉ số điều do danh mục gợi ý."""
    dem = 0
    for m in muc:
        if m.get("trang_thai") == "dat" or dem >= RA_SOAT_TRA_LUAT_TOI_DA:
            continue
        dem += 1
        try:
            rows = rag.retrieve(ra_soat_rui_ro.cau_hoi_tra_luat(m), "internal",
                                dept_ids=user["dept_ids"], is_banqt=user["is_banqt"],
                                doc_types=["law"], top_k=2, neighbours=False)
        except Exception:
            rows = []
        m["can_cu_kho"] = [{
            "document_id": r.get("document_id"), "chunk_id": r.get("chunk_id"),
            "title": r.get("title"), "so_hieu": r.get("so_hieu"),
            "trich": " ".join((r.get("content") or "").split())[:400],
        } for r in rows or []]


@app.get("/legal/ra-soat/loai")
def ra_soat_loai(user=Depends(current_user)):
    require(user, INTERNAL_ROLES | CLIENT_ROLES)
    _can_tinh_nang(user, "kiem_tra")
    return {"items": [{"ma": ma, "ten": cfg["ten"],
                       "so_dieu_khoan": len(cfg.get("dieu_khoan", [])),
                       "so_nguong": len(cfg.get("nguong", []))}
                      for ma, cfg in ra_soat_rui_ro.LOAI_HOP_DONG.items()]}


@app.post("/legal/ra-soat")
def ra_soat_hop_dong(body: RaSoatIn, user=Depends(current_user)):
    """Đối chiếu một hợp đồng với danh mục điều khoản chuẩn theo loại + ngưỡng
    bất thường theo luật → bảng Đạt / Cảnh báo / Thiếu, kèm đoạn luật trong kho."""
    require(user, INTERNAL_ROLES | CLIENT_ROLES)
    _can_tinh_nang(user, "kiem_tra")
    if body.loai and body.loai not in ra_soat_rui_ro.LOAI_HOP_DONG:
        raise HTTPException(422, "Loại hợp đồng không có trong danh mục")
    text, tieu_de = _van_ban_de_ra_soat(body, user)
    if len(text.strip()) < 100:
        raise HTTPException(422, "Văn bản quá ngắn để rà soát (dưới 100 ký tự)")
    if len(text) > RA_SOAT_MAX_CHARS:
        raise HTTPException(413, f"Văn bản vượt {RA_SOAT_MAX_CHARS:,} ký tự")
    t0 = time.perf_counter()
    ket_qua = ra_soat_rui_ro.ra_soat(text, tieu_de, body.loai)
    if body.tra_luat:
        _kem_can_cu_kho(ket_qua.get("muc") or [], user)
    ket_qua.update(tieu_de=tieu_de, so_ky_tu=len(text),
                   thoi_gian_ms=int((time.perf_counter() - t0) * 1000))
    with db.session(role="internal", admin=True) as conn:
        db.audit(conn, user["id"], "legal_checklist", "documents", body.document_id, {
            "title": tieu_de[:120], "loai": ket_qua.get("loai"),
            "tong_ket": ket_qua.get("tong_ket"), "draft_id": body.draft_id,
            "temp_file_id": body.temp_file_id,
        })
    return ket_qua


class RaSoatExportIn(BaseModel):
    ket_qua: dict
    tieu_de: str | None = None


@app.post("/legal/ra-soat/export")
def ra_soat_export(body: RaSoatExportIn, user=Depends(current_user)):
    require(user, INTERNAL_ROLES | CLIENT_ROLES)
    _can_tinh_nang(user, "kiem_tra")
    if not isinstance(body.ket_qua.get("muc"), list):
        raise HTTPException(422, "ket_qua không hợp lệ")
    tieu_de = body.tieu_de or body.ket_qua.get("tieu_de") or "Hợp đồng"
    payload = ra_soat_rui_ro.xuat_bao_cao_docx(body.ket_qua, tieu_de,
                                               nguoi_lap=user.get("name") or "")
    fname = re.sub(r"[^\w\-. ]+", "_", f"ra-soat-{tieu_de}")[:80] + ".docx"
    return Response(payload,
                    media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={"Content-Disposition":
                             f"attachment; filename=\"ra-soat.docx\"; filename*=UTF-8''{quote(fname)}"})


from app.draft_api import build_router as _build_draft_router
app.include_router(_build_draft_router(current_user, require_reviewer))

# ---------- 12. Sổ nhân sự (employees + employment_contracts) ----------
# Đây là NGUỒN SỰ THẬT cho câu "công ty có bao nhiêu nhân sự": có dữ liệu ở đây
# thì structured_answer trả lời xác định bằng SQL, không đi qua model sinh văn
# bản. Router /hr (kèm import CSV/XLSX) đã viết và test sẵn nhưng trước đây
# quên đăng ký nên bảng employees không có đường nhập — câu đếm nhân sự vì thế
# luôn rơi xuống RAG và từng trả lời bằng số lao động dự kiến của công ty khách.
from app.hr_api import build_router as _build_hr_router
app.include_router(_build_hr_router(current_user))


# ---------- 9. Giao diện quản trị ----------
@app.get("/admin", response_class=HTMLResponse)
def admin_page():
    return ADMIN_HTML
