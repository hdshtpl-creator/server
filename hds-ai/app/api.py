"""
api.py — Máy chủ API cho toàn hệ thống.

Nhóm đường dẫn:
  /chat/*     — 3 kênh chat (public/internal/portal)
  /upload/*   — tải file trong chat: chế độ lưu / dùng-xong-bỏ
  /review/*   — duyệt nhãn tài liệu (chỉ người có can_review)
  /learn/*    — duyệt hội thoại đưa vào kho (tự học)
  /methods/*  — dạy AI cách phân tích (mẫu phương pháp)
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

from fastapi import FastAPI, Header, HTTPException, Depends, File, Form, UploadFile
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app import db, rag, auth, settings
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


def current_user(cred: HTTPAuthorizationCredentials = Depends(bearer)):
    """Lấy user từ token JWT (Authorization: Bearer <token>).
    Thay cho X-User-Id — không giả mạo được vì token có chữ ký."""
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
                "dept_ids": [], "is_banqt": False}
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT id,role,client_id,can_review,full_name,
                           monthly_quota,used_this_month
                           FROM users WHERE id=%s AND active""", (user_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(401, "Người dùng không tồn tại hoặc bị khóa")
            cur.execute("SELECT department_id FROM user_departments WHERE user_id=%s", (user_id,))
            dept_ids = [r[0] for r in cur.fetchall()]
    return {"id": row[0], "role": row[1], "client_id": row[2], "can_review": row[3],
            "name": row[4], "monthly_quota": row[5], "used_this_month": row[6],
            "dept_ids": dept_ids, "is_banqt": row[1] in SEE_ALL}


def require(user, roles):
    if user["role"] not in roles:
        raise HTTPException(403, "Không đủ quyền")


def require_reviewer(user):
    # Chỉ admin, hoặc người được cấp can_review, mới được duyệt
    if user["role"] != "admin" and not user["can_review"]:
        raise HTTPException(403, "Chỉ admin hoặc người được cấp quyền duyệt mới thực hiện được")


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
            "dept_ids": user["dept_ids"]}


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


@app.post("/chat/public")
def chat_public(body: ChatIn):
    conv = body.conversation_id or rag.start_conversation(None, "public")
    res = rag.answer(body.question, "public", conversation_id=conv)
    res["conversation_id"] = conv
    return res


@app.post("/chat/internal")
def chat_internal(body: ChatIn, user=Depends(current_user)):
    require(user, INTERNAL_ROLES)
    conv = body.conversation_id or rag.start_conversation(user["id"], "internal")
    res = rag.answer(body.question, "internal", user_id=user["id"], conversation_id=conv,
                     use_temp=body.use_temp, use_method=body.use_method,
                     dept_ids=user["dept_ids"], is_banqt=user["is_banqt"])
    res["conversation_id"] = conv
    return res


@app.post("/chat/portal")
def chat_portal(body: ChatIn, user=Depends(current_user)):
    require(user, CLIENT_ROLES)
    # Hạn mức câu hỏi/tháng theo gói
    quota = user.get("monthly_quota") or 0
    used = user.get("used_this_month") or 0
    if quota > 0 and used >= quota:
        raise HTTPException(429, f"Đã hết lượt hỏi trong tháng ({used}/{quota}). "
                                 f"Nâng cấp gói để hỏi thêm.")
    cid = user["client_id"]
    conv = body.conversation_id or rag.start_conversation(user["id"], "portal", cid)
    res = rag.answer(body.question, "portal", user_id=user["id"], client_id=cid,
                     conversation_id=conv, use_temp=body.use_temp)
    # Tăng bộ đếm đã dùng
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET used_this_month=used_this_month+1 WHERE id=%s", (user["id"],))
    res["quota"] = {"used": used + 1, "limit": quota}
    res["conversation_id"] = conv
    return res


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
                           d.source_kind,c.name,
                           (SELECT left(content,200) FROM chunks WHERE document_id=d.id ORDER BY chunk_index LIMIT 1)
                           FROM documents d LEFT JOIN clients c ON c.id=d.client_id
                           WHERE NOT d.label_verified ORDER BY d.confidence NULLS FIRST, d.id LIMIT %s""",
                        (limit,))
            rows = cur.fetchall()
    return [{"id": r[0], "title": r[1], "doc_type": r[2], "access_level": r[3], "client_id": r[4],
             "confidence": r[5], "source_kind": r[6], "client_name": r[7], "preview": r[8]} for r in rows]


class LabelIn(BaseModel):
    doc_type: str
    access_level: str
    client_id: int | None = None


@app.post("/review/{doc_id}/approve")
def review_approve(doc_id: int, body: LabelIn, user=Depends(current_user)):
    require_reviewer(user)
    if body.access_level == "client" and body.client_id is None:
        raise HTTPException(400, "Tài liệu của khách bắt buộc chọn khách hàng")
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""UPDATE documents SET doc_type=%s,access_level=%s,client_id=%s,
                           label_verified=true,approved=true,updated_at=now() WHERE id=%s""",
                        (body.doc_type, body.access_level, body.client_id, doc_id))
        db.audit(conn, user["id"], "approve_label", "documents", doc_id, body.model_dump())
    return {"ok": True, "document_id": doc_id}


# ---------- 4. TỰ HỌC (duyệt hội thoại) ----------
@app.get("/learn/pending")
def learn_pending(user=Depends(current_user), limit: int = 30):
    require_reviewer(user)
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT m.id,m.content,m.created_at,
                           (SELECT content FROM messages WHERE conversation_id=m.conversation_id
                            AND role='user' AND id<m.id ORDER BY id DESC LIMIT 1)
                           FROM messages m JOIN conversations cv ON cv.id=m.conversation_id
                           WHERE m.role='assistant' AND m.review_status='pending' AND cv.channel='internal'
                           ORDER BY m.created_at DESC LIMIT %s""", (limit,))
            rows = cur.fetchall()
    return [{"message_id": r[0], "answer": r[1], "created_at": str(r[2]), "question": r[3]} for r in rows]


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
            cur.execute("SELECT id,email,full_name,role,can_review,active FROM users ORDER BY id")
            rows = cur.fetchall()
    return [{"id": r[0], "email": r[1], "full_name": r[2], "role": r[3],
             "can_review": r[4], "active": r[5]} for r in rows]


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


# ---------- 7. DANH SÁCH TÀI LIỆU ĐÃ HỌC ----------
@app.get("/documents")
def documents_list(user=Depends(current_user), q: str = "", doc_type: str = "", limit: int = 200):
    """Danh sách tài liệu đã vào kho, kèm tóm tắt. Chỉ admin hoặc người được cấp quyền.
    q: tìm theo tên/tóm tắt. doc_type: lọc theo loại (law/contract/...)."""
    require_reviewer(user)
    sql = """SELECT d.id, d.title, d.doc_type, d.access_level, d.summary,
                    d.source_kind, d.created_at, c.name,
                    (SELECT count(*) FROM chunks WHERE document_id=d.id) AS so_doan
               FROM documents d LEFT JOIN clients c ON c.id=d.client_id
              WHERE d.label_verified = true AND d.approved = true"""
    params = []
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


@app.get("/documents/browse")
def documents_browse(user=Depends(current_user), q: str = "", limit: int = 300):
    """Danh sách tài liệu cho MỌI nhân viên nội bộ — ÁP CƠ CHẾ CÁCH B:
    thấy tên tất cả, nhưng hồ sơ ngoài phòng bị CHE TÊN và không mở được."""
    require(user, INTERNAL_ROLES)
    sql = """SELECT d.id,d.title,d.doc_type,d.access_level,d.client_id,d.department_id,
                    dep.name, c.name, d.summary
               FROM documents d
               LEFT JOIN clients c ON c.id=d.client_id
               LEFT JOIN departments dep ON dep.id=d.department_id
              WHERE d.label_verified AND d.approved"""
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
    for r in rows:
        doc = {"access_level": r[3], "department_id": r[5], "doc_type": r[2],
               "client_id": r[4], "title": r[1], "department_name": r[6]}
        can_open = rag.can_open_doc(user["role"], user["dept_ids"], user["is_banqt"], doc)
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
                               WHERE c.department_id = ANY(%s) ORDER BY c.name""",
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
    if not user["is_banqt"] and client_dept not in (user["dept_ids"] or []):
        raise HTTPException(403, "Khách hàng này thuộc phòng khác — không có quyền xem")
    dossier = rag.client_360(client_id, user["dept_ids"], user["is_banqt"])
    if not dossier:
        raise HTTPException(404, "Không dựng được hồ sơ")
    return dossier


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
                (SELECT count(*) FROM messages WHERE review_status='pending'),
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


# ---------- 8a. TỆP: TẢI LÊN / TẢI VỀ QUA WEB ----------
# Khác /upload (nhận text đã trích sẵn, chỉ dùng được .txt): các endpoint dưới đây
# nhận TỆP THẬT (pdf/docx/...), tự lưu vào đúng thư mục trên server, tự trích văn
# bản + OCR nếu là bản scan, rồi nạp vào kho. Không cần SSH, không cần chép tay.

DATA_RAW = Path(os.getenv("DATA_RAW", "./data/raw"))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "50"))
ALLOWED_UPLOAD_EXT = {".pdf", ".docx", ".txt", ".md"}


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
        db.audit(conn, user["id"], "web_upload", "documents", doc_id,
                 {"file": safe, "bytes": size, "auto_approve": auto_approve})

    return {"ok": True, "document_id": doc_id, "filename": safe, "bytes": size,
            "stored_path": str(dest),
            "note": "Đã nạp vào kho." if auto_approve else "Đã vào hàng chờ duyệt nhãn."}


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
    if not rag.can_open_doc(user["role"], user["dept_ids"], user["is_banqt"], doc):
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
    except ValueError as e:
        raise HTTPException(400, str(e))
    except json.JSONDecodeError:
        raise HTTPException(400, "Giá trị không phải JSON hợp lệ")
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


# ---------- 9. Giao diện quản trị ----------
@app.get("/admin", response_class=HTMLResponse)
def admin_page():
    return ADMIN_HTML
