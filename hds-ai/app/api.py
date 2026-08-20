"""
api.py — Máy chủ API cho toàn hệ thống.

Nhóm đường dẫn:
  /chat/*     — 3 kênh chat (public/internal/portal)
  /upload/*   — tải file trong chat: chế độ lưu / dùng-xong-bỏ
  /review/*   — duyệt nhãn tài liệu (chỉ người có can_review)
  /learn/*    — duyệt hội thoại đưa vào kho (tự học)
  /methods/*  — dạy AI cách phân tích (mẫu phương pháp)
  /drafts/*   — soạn tài liệu có nguồn, version, duyệt và xuất DOCX/Markdown
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
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Header, HTTPException, Depends, File, Form, UploadFile
from fastapi.responses import HTMLResponse, FileResponse, Response, StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app import company_context, db, rag, auth, settings
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
        return check_conversation(user, body.conversation_id, channel)
    return rag.start_conversation(user["id"], channel, cid, title=_conv_title(body.question))


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


@app.post("/chat/public")
def chat_public(body: ChatIn):
    source_ids = _chat_source_ids(body)
    conv = (check_conversation(None, body.conversation_id, "public")
            if body.conversation_id else rag.start_conversation(None, "public"))
    res = rag.answer(body.question, "public", conversation_id=conv,
                     source_document_ids=source_ids)
    res["conversation_id"] = conv
    return res


@app.post("/chat/internal")
def chat_internal(body: ChatIn, user=Depends(current_user)):
    require(user, INTERNAL_ROLES)
    source_ids = _chat_source_ids(body)
    conv = _resolve_conv(user, body, "internal")
    res = rag.answer(body.question, "internal", user_id=user["id"], conversation_id=conv,
                     use_temp=body.use_temp, use_method=body.use_method,
                     dept_ids=user["dept_ids"], is_banqt=user["is_banqt"],
                     can_finance=user["can_finance"], model=body.model,
                     source_document_ids=source_ids)
    res["conversation_id"] = conv
    return res


@app.post("/chat/portal")
def chat_portal(body: ChatIn, user=Depends(current_user)):
    require(user, CLIENT_ROLES)
    source_ids = _chat_source_ids(body)
    # Hạn mức câu hỏi/tháng theo gói
    quota = user.get("monthly_quota") or 0
    used = user.get("used_this_month") or 0
    if quota > 0 and used >= quota:
        raise HTTPException(429, f"Đã hết lượt hỏi trong tháng ({used}/{quota}). "
                                 f"Nâng cấp gói để hỏi thêm.")
    cid = user["client_id"]
    conv = _resolve_conv(user, body, "portal", cid)
    res = rag.answer(body.question, "portal", user_id=user["id"], client_id=cid,
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
    source_ids = _chat_source_ids(body)
    is_client = user["role"] in CLIENT_ROLES

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

        def produce():
            try:
                for ev in rag.answer_stream(
                        body.question, channel, user_id=user["id"], client_id=cid,
                        conversation_id=conv, use_temp=body.use_temp,
                        use_method=body.use_method and not is_client,
                        dept_ids=user["dept_ids"], is_banqt=user["is_banqt"],
                        can_finance=user["can_finance"],
                        role=user["role"] if is_client else None,
                        model=None if is_client else body.model,
                        source_document_ids=source_ids):
                    q.put(("event", ev))
            except Exception as e:  # noqa: BLE001 - báo lỗi qua dòng, không để luồng chết câm
                q.put(("error", str(e)))
            finally:
                q.put((DONE, None))

        worker = threading.Thread(target=produce, daemon=True)
        worker.start()

        while True:
            try:
                kind, payload = q.get(timeout=HEARTBEAT_SEC)
            except _queue.Empty:
                yield ": hb\n\n"          # đang đọc tài liệu — giữ kết nối sống
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
def conversations_list(user=Depends(current_user), limit: int = 100):
    """Danh sách hội thoại của người đang đăng nhập, mới hoạt động xếp trước —
    để dựng cột 'cuộc trò chuyện' bên trái (mô hình ChatGPT)."""
    require(user, INTERNAL_ROLES | CLIENT_ROLES)
    channel = _user_channel(user)
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT c.id, c.title, c.started_at,
                                  coalesce(max(m.created_at), c.started_at) AS last_at,
                                  count(m.id) AS n
                             FROM conversations c
                             LEFT JOIN messages m ON m.conversation_id = c.id
                            WHERE c.user_id=%s AND c.channel=%s
                            GROUP BY c.id
                            ORDER BY last_at DESC
                            LIMIT %s""", (user["id"], channel, limit))
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
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM conversations WHERE id=%s", (conv_id,))
        db.audit(conn, user["id"], "delete_conversation", "conversations", conv_id, {})
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
                cur.execute("""SELECT c.id FROM conversations c
                                LEFT JOIN messages m ON m.conversation_id=c.id
                               WHERE c.user_id=%s AND c.channel=%s
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
            cur.execute("""SELECT m.id, m.role, m.content, m.created_at,
                                  m.conversation_id, c.title
                             FROM messages m JOIN conversations c ON c.id=m.conversation_id
                            WHERE c.user_id=%s AND c.channel=%s AND m.content ILIKE %s
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
        n = rag.add_temp_file(body.conversation_id, user["id"], body.filename, body.content)
        return {"ok": True, "mode": "temp", "chunks": n,
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


# ---------- 3. DUYỆT NHÃN ----------
@app.get("/review/pending")
def review_pending(user=Depends(current_user), limit: int = 50):
    require_reviewer(user)
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT d.id,d.title,d.doc_type,d.access_level,d.client_id,d.confidence,
                           d.source_kind,c.name,d.extraction_status,d.extraction_error,
                           (SELECT left(content,200) FROM chunks WHERE document_id=d.id ORDER BY chunk_index LIMIT 1)
                           FROM documents d LEFT JOIN clients c ON c.id=d.client_id
                           WHERE NOT d.label_verified ORDER BY d.confidence NULLS FIRST, d.id LIMIT %s""",
                        (limit,))
            rows = cur.fetchall()
    return [{"id": r[0], "title": r[1], "doc_type": r[2], "access_level": r[3], "client_id": r[4],
             "confidence": r[5], "source_kind": r[6], "client_name": r[7],
             "extraction_status": r[8], "extraction_warning": r[9],
             "preview": r[10]} for r in rows]


class LabelIn(BaseModel):
    doc_type: str
    access_level: str
    client_id: int | None = None


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
    pieces = split_document_with_metadata(extraction, doc_type)
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
        db.audit(conn, user["id"], "edit_document_content", "documents", doc_id,
                 {"chunks": len(pieces), "characters": len(text)})
    return {"ok": True, "document_id": doc_id, "chunks": len(pieces)}


@app.post("/review/{doc_id}/approve")
def review_approve(doc_id: int, body: LabelIn, user=Depends(current_user)):
    require_reviewer(user)
    if body.access_level == "client" and body.client_id is None:
        raise HTTPException(400, "Tài liệu của khách bắt buộc chọn khách hàng")
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""UPDATE documents SET doc_type=%s,access_level=%s,client_id=%s,
                           label_verified=true,approved=true,extraction_status='ready',updated_at=now()
                           WHERE id=%s""",
                        (body.doc_type, body.access_level, body.client_id, doc_id))
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
                    (SELECT count(*) FROM chunks WHERE document_id=d.id) AS so_doan
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
             "created_at": str(r[6])[:10], "client_name": r[7], "so_doan": r[8]} for r in rows]


@app.get("/drive/sync-status")
def drive_sync_status(user=Depends(current_user)):
    """Trạng thái lần quét Google Drive gần nhất (app/auto_learn.py ghi lại).

    Đây là nơi admin biết bot đã học file nào, file nào bị bỏ qua và lý do —
    không cần SSH vào máy chủ xem log."""
    require_reviewer(user)
    raw = settings.get("drive_sync_status")
    data = json.loads(raw) if raw else None
    return {
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
                    dep.name, c.name, d.summary
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
        })
    return out


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
        # Ước lượng thời gian một lượt hỏi điển hình với ngân sách ngữ cảnh
        # đang đặt — cho admin thấy hậu quả của việc nới ngân sách.
        ctx_chars = settings.get_int("context_char_budget", 6000)
        # ~3 ký tự tiếng Việt cho một token, cộng hồ sơ công ty + lịch sử + câu hỏi
        est_prompt = ctx_chars / 3 + 2000
        r, w = res.get("read_tok_s"), res.get("write_tok_s")
        if r and w:
            res["uoc_tinh_giay"] = round(est_prompt / r + settings.get_int(
                "llm_num_predict", 700) / w, 1)
    return res


# ---------- 8a. TỆP: TẢI LÊN / TẢI VỀ QUA WEB ----------
# Khác /upload (nhận text đã trích sẵn, chỉ dùng được .txt): các endpoint dưới đây
# nhận TỆP THẬT (pdf/docx/...), tự lưu vào đúng thư mục trên server, tự trích văn
# bản + OCR nếu là bản scan, rồi nạp vào kho. Không cần SSH, không cần chép tay.

DATA_RAW = Path(os.getenv("DATA_RAW", "./data/raw"))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "50"))
ALLOWED_UPLOAD_EXT = {".pdf", ".docx", ".xlsx", ".csv", ".txt", ".md"}


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


@app.get("/files/{doc_id}/download")
def files_download(doc_id: int, user=Depends(current_user)):
    """Tải bản gốc tài liệu. Quyền mở dùng CHUNG một hàm với cơ chế che tên
    (rag.can_open_doc) nên không thể tải thứ mình không được xem."""
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
    # Chốt an toàn: đường dẫn phải nằm trong thư mục dữ liệu
    data_root = (Path.cwd() / DATA_RAW).resolve()
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(data_root)
    except (FileNotFoundError, ValueError):
        raise HTTPException(404, "Tệp gốc không còn trên máy chủ")

    with db.session(role="internal", admin=True) as conn:
        db.audit(conn, user["id"], "download_document", "documents", doc_id, {})
    return FileResponse(resolved, filename=resolved.name.split("_", 1)[-1])


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
