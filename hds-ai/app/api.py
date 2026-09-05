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

from app import company_context, db, rag, auth, settings, van_ban
from app.admin_ui import ADMIN_HTML

app = FastAPI(title="HDS AI", version="1.0")

# CORS chỉ cần khi giao diện chạy ở origin KHÁC backend (ví dụ frontend trên
# Vercel gọi sang API). Khi deploy chung một máy chủ (nginx proxy /api cùng
# origin) thì để trống CORS_ORIGINS — trình duyệt coi là cùng nguồn, không cần
# CORS. Nhiều origin ngăn cách bằng dấu phẩy.
_cors_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
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
            cur.execute("""SELECT id,role,client_id,can_review,full_name,
                           monthly_quota,used_this_month,can_view_finance
                           FROM users WHERE id=%s AND active""", (user_id,))
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
            "can_finance": row[1] == "admin" or bool(row[7])}


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


@app.post("/auth/login")
def login(body: LoginIn):
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT id, role, password_hash, full_name, active
                           FROM users WHERE email=%s""", (body.email,))
            row = cur.fetchone()
    if not row or not row[4]:
        raise HTTPException(401, "Sai email hoặc mật khẩu")
    uid, role, phash, name, _ = row
    if not auth.verify_password(body.password, phash):
        raise HTTPException(401, "Sai email hoặc mật khẩu")
    token = auth.make_token(uid, role)
    return {"access_token": token, "token_type": "bearer",
            "user": {"id": uid, "role": role, "full_name": name}}


@app.get("/auth/me")
def whoami(user=Depends(current_user)):
    return {"id": user["id"], "role": user["role"], "name": user.get("name"),
            "can_review": user["can_review"], "is_banqt": user["is_banqt"],
            "can_finance": user["can_finance"], "dept_ids": user["dept_ids"]}


class ChangePwIn(BaseModel):
    old_password: str
    new_password: str


@app.post("/auth/change-password")
def change_password(body: ChangePwIn, user=Depends(current_user)):
    if len(body.new_password) < 6:
        raise HTTPException(400, "Mật khẩu mới tối thiểu 6 ký tự")
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT password_hash FROM users WHERE id=%s", (user["id"],))
            phash = cur.fetchone()[0]
            if not auth.verify_password(body.old_password, phash):
                raise HTTPException(400, "Mật khẩu cũ không đúng")
            cur.execute("UPDATE users SET password_hash=%s WHERE id=%s",
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


_CHAT_MODES = {None, "", "legal_review"}


def _chat_mode(body: ChatIn, internal: bool) -> str | None:
    """Chế độ đặc biệt của khung chat — chỉ nhân viên nội bộ được dùng."""
    if body.mode not in _CHAT_MODES:
        raise HTTPException(422, "mode chỉ nhận 'legal_review'")
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


def _public_rate_check(request: Request):
    if PUBLIC_RATE_MAX <= 0:      # đặt 0 để tắt van (môi trường dev/test)
        return
    now = time.monotonic()
    ip = _client_ip(request)
    with _public_hits_lock:
        hits = [t for t in _public_hits.get(ip, []) if now - t < PUBLIC_RATE_WINDOW_SEC]
        if len(hits) >= PUBLIC_RATE_MAX:
            raise HTTPException(
                429, "Bạn đã hỏi quá nhiều trong thời gian ngắn. Vui lòng quay "
                     "lại sau, hoặc liên hệ trực tiếp luật sư của HDS.")
        hits.append(now)
        _public_hits[ip] = hits
        # Dọn IP nguội để dict không phình vô hạn theo thời gian chạy.
        if len(_public_hits) > 10_000:
            for stale in [k for k, v in _public_hits.items()
                          if not v or now - v[-1] >= PUBLIC_RATE_WINDOW_SEC]:
                _public_hits.pop(stale, None)


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
    conv = _resolve_conv(user, body, "internal")
    res = rag.answer(question, "internal", user_id=user["id"], conversation_id=conv,
                     use_temp=body.use_temp, use_method=body.use_method,
                     dept_ids=user["dept_ids"], is_banqt=user["is_banqt"],
                     can_finance=user["can_finance"], model=body.model,
                     source_document_ids=source_ids,
                     mode=_chat_mode(body, internal=True),
                     template_doc_id=_chat_template_id(body, internal=True),
                     make_files=_chat_make_files(body, internal=True),
                     # role + dept_codes: kênh internal không dùng cho tier,
                     # nhưng luồng điền mẫu cần chúng để soi ma trận access_rules.
                     role=user["role"], dept_codes=user["dept_codes"])
    res["conversation_id"] = conv
    return res


@app.post("/chat/portal")
def chat_portal(body: ChatIn, user=Depends(current_user)):
    require(user, CLIENT_ROLES)
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
    question = _clean_question(body)
    source_ids = _chat_source_ids(body)
    is_client = user["role"] in CLIENT_ROLES
    chat_mode = _chat_mode(body, internal=not is_client)
    template_doc_id = _chat_template_id(body, internal=not is_client)
    make_files = _chat_make_files(body, internal=not is_client)

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
                        cancel=cancel):
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
    require(user, INTERNAL_ROLES)
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

    require(user, INTERNAL_ROLES)
    check_conversation(user, conversation_id, "internal")
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
@app.get("/review/pending")
def review_pending(user=Depends(current_user), limit: int = 50):
    require_reviewer(user)
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT d.id,d.title,d.doc_type,d.access_level,d.client_id,d.confidence,
                           d.source_kind,c.name,d.extraction_status,d.extraction_error,
                           (SELECT left(content,200) FROM chunks WHERE document_id=d.id ORDER BY chunk_index LIMIT 1),
                           d.so_hieu,d.loai_van_ban,d.trich_yeu,d.ngay_ban_hanh,
                           d.ngay_hieu_luc,d.trang_thai_hieu_luc
                           FROM documents d LEFT JOIN clients c ON c.id=d.client_id
                           WHERE NOT d.label_verified ORDER BY d.confidence NULLS FIRST, d.id LIMIT %s""",
                        (limit,))
            rows = cur.fetchall()
    return [{"id": r[0], "title": r[1], "doc_type": r[2], "access_level": r[3], "client_id": r[4],
             "confidence": r[5], "source_kind": r[6], "client_name": r[7],
             "extraction_status": r[8], "extraction_warning": r[9],
             "preview": r[10],
             # Metadata máy bóc sẵn — form duyệt điền trước cho người soát/sửa.
             "so_hieu": r[11], "loai_van_ban": r[12], "trich_yeu": r[13],
             "ngay_ban_hanh": str(r[14]) if r[14] else None,
             "ngay_hieu_luc": str(r[15]) if r[15] else None,
             "trang_thai_hieu_luc": r[16]} for r in rows]


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


class ContentIn(BaseModel):
    content: str


@app.put("/review/{doc_id}/content")
def review_content_put(doc_id: int, body: ContentIn, user=Depends(current_user)):
    """Lưu nội dung người duyệt đã sửa: chia đoạn lại, tạo vector lại — bot học
    ĐÚNG BẢN ĐÃ SỬA, không phải bản OCR thô. Trạng thái duyệt giữ nguyên (đang
    chờ thì vẫn chờ — sửa xong bấm Duyệt như thường); extraction_status thành
    'edited' để phân biệt với bản máy tự trích."""
    require_reviewer(user)
    text = (body.content or "").strip()
    if len(text) < 30:
        raise HTTPException(422, "Nội dung sau sửa quá ngắn (dưới 30 ký tự)")
    if len(text) > 2_000_000:
        raise HTTPException(422, "Nội dung vượt 2 triệu ký tự — tách nhỏ tài liệu")
    from app.ingest import (ExtractionResult, apply_context_headers,
                            client_display_name, split_document_with_metadata)
    from app.models import embed, summarize
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT title,doc_type,access_level,client_id,department_id
                             FROM documents WHERE id=%s""", (doc_id,))
            doc = cur.fetchone()
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
        db.audit(conn, user["id"], "edit_document_content", "documents", doc_id,
                 {"chunks": len(pieces), "characters": len(text)})
    return {"ok": True, "document_id": doc_id, "chunks": len(pieces),
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


@app.post("/review/{doc_id}/approve")
def review_approve(doc_id: int, body: LabelIn, user=Depends(current_user)):
    require_reviewer(user)
    if body.access_level == "client" and body.client_id is None:
        raise HTTPException(400, "Tài liệu của khách bắt buộc chọn khách hàng")
    if (body.trang_thai_hieu_luc
            and body.trang_thai_hieu_luc not in van_ban.TRANG_THAI_HIEU_LUC):
        raise HTTPException(422, "Trạng thái hiệu lực không hợp lệ")
    # Cột nào người duyệt gửi thì mới đổi — form cũ không gửi các trường này
    # vẫn hoạt động y nguyên.
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
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
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
                van_ban.cap_nhat_hieu_luc(cur)
        db.audit(conn, user["id"], "approve_label", "documents", doc_id, body.model_dump())
    return {"ok": True, "document_id": doc_id}


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
    password: str = "hds12345"           # mật khẩu ban đầu (user tự đổi sau)
    can_review: bool = False
    client_id: int | None = None
    department_ids: list[int] = []       # phòng user thuộc (nội bộ)
    head_of: list[int] = []              # phòng user làm trưởng
    monthly_quota: int = 0               # hạn mức câu hỏi/tháng (khách)


@app.get("/users")
def users_list(user=Depends(current_user)):
    require(user, {"admin"})
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            # Không trả api_key_hash ra ngoài — chỉ cho biết CÓ khoá hay không
            cur.execute("""SELECT id,email,full_name,role,can_review,active,
                                  can_view_finance,
                                  (api_key_hash IS NOT NULL) AS has_api_key,
                                  api_key_at
                             FROM users ORDER BY id""")
            rows = cur.fetchall()
    return [{"id": r[0], "email": r[1], "full_name": r[2], "role": r[3],
             "can_review": r[4], "active": r[5], "can_view_finance": r[6],
             "has_api_key": r[7], "api_key_at": str(r[8])[:10] if r[8] else None}
            for r in rows]


@app.post("/users")
def users_add(body: UserIn, user=Depends(current_user)):
    require(user, {"admin"})
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO users (email,password_hash,full_name,role,can_review,client_id,monthly_quota)
                           VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                        (body.email, auth.hash_password(body.password), body.full_name,
                         body.role, body.can_review, body.client_id, body.monthly_quota))
            uid = cur.fetchone()[0]
            for did in body.department_ids:
                cur.execute("""INSERT INTO user_departments (user_id,department_id,is_head)
                               VALUES (%s,%s,%s) ON CONFLICT DO NOTHING""",
                            (uid, did, did in body.head_of))
        db.audit(conn, user["id"], "create_user", "users", uid,
                 {"role": body.role, "depts": body.department_ids})
    return {"ok": True, "user_id": uid}


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
        sql += " AND (d.title ILIKE %s OR d.summary ILIKE %s)"
        params += [f"%{q}%", f"%{q}%"]
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
                (SELECT count(*) FROM documents WHERE NOT label_verified),
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
    """
    require(user, INTERNAL_ROLES)
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
                            dept_codes=user["dept_codes"]):
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
    resolved, _title = _original_file(doc_id, user)
    with db.session(role="internal", admin=True) as conn:
        db.audit(conn, user["id"], "download_document", "documents", doc_id, {})
    return FileResponse(resolved, filename=resolved.name.split("_", 1)[-1])


# Các định dạng trình duyệt tự mở được — trả thẳng, không cần chuyển đổi.
_INLINE_SUFFIXES = {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".txt", ".md"}
# Định dạng Office: chuyển sang PDF một lần bằng LibreOffice rồi cache lại.
_CONVERT_SUFFIXES = {".docx", ".doc", ".xlsx", ".csv"}
DATA_WORK = Path(os.getenv("DATA_WORK", "./data/work"))


def _preview_pdf(resolved: Path, doc_id: int) -> Path:
    """Bản PDF xem trước của một file Office, sinh một lần rồi dùng lại.

    Cache theo mtime: file gốc đổi (Drive đồng bộ bản mới) thì sinh lại.
    LibreOffice đã có sẵn trên máy chủ (update.sh cài libreoffice-writer cho
    khâu đọc .doc) — máy dev thiếu thì trả 409 để giao diện lùi về nút Tải về.
    """
    import shutil as _shutil
    import subprocess
    import tempfile

    out_dir = DATA_WORK / "preview"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{doc_id}.pdf"
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


@app.get("/files/{doc_id}/preview")
def files_preview(doc_id: int, user=Depends(current_user)):
    """XEM TRƯỚC bản gốc ngay trong trình duyệt (không phải tải về).

    PDF/ảnh/text trả thẳng; .docx/.doc/.xlsx chuyển sang PDF một lần bằng
    LibreOffice rồi cache ở data/work/preview. Cùng chốt quyền với tải về
    (_original_file) — không có cửa phân quyền thứ hai."""
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


@app.get("/template-fills/{token}/download")
def template_fill_download(token: str, user=Depends(current_user)):
    """Tải file mẫu ĐÃ ĐIỀN chủ thể (tạo từ khung chat). File là hàng tạm
    trong data/work/template_fills, tự dọn sau 24 giờ."""
    require(user, INTERNAL_ROLES)
    from app import template_fill as _tf
    path = _tf.find_fill_file(token)
    if path is None:
        raise HTTPException(404, "File đã điền không còn trên máy chủ (quá 24 "
                                 "giờ hoặc token sai). Hãy tạo lại từ khung chat.")
    with db.session(role="internal", admin=True) as conn:
        db.audit(conn, user["id"], "download_template_fill", "template_fill",
                 None, {"token": token})
    return FileResponse(path, filename=path.name)


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
