"""
rag.py — Bộ máy hỏi đáp dùng chung cho CẢ 3 kênh (website / nội bộ / cổng khách).

QUY TẮC: cả 3 kênh gọi cùng answer(). KHÔNG viết 3 bản riêng.
Phân quyền do RLS ở CSDL lo — SQL bên dưới KHÔNG có điều kiện lọc quyền.

Hỗ trợ thêm:
  - temp_files: file "dùng xong bỏ" trong chat (không vào kho)
  - analysis_methods: áp mẫu phương pháp admin đã dạy
"""
import json

from app import db
from app.models import embed, llm

TOP_K = 8

SYSTEM_PROMPTS = {
    "public": ("Bạn là trợ lý của Công ty Luật HDS, trả lời khách trên website. "
               "Chỉ dựa vào TÀI LIỆU THAM KHẢO bên dưới. Không đủ căn cứ thì nói rõ. "
               "Trả lời khái quát, luôn kết thúc bằng gợi ý liên hệ luật sư HDS. "
               "Không bịa điều luật, không nêu số hiệu văn bản nếu không có trong tài liệu."),
    "internal": ("Bạn là trợ lý pháp lý nội bộ của HDS, phục vụ luật sư và chuyên viên. "
                 "Chỉ dựa vào TÀI LIỆU THAM KHẢO. Trả lời chuyên sâu, trích tới Điều/Khoản khi có. "
                 "Nêu rõ điểm nào chắc chắn, điểm nào cần luật sư kiểm chứng. "
                 "Kết quả là bản nháp; luật sư rà soát và chịu trách nhiệm cuối cùng."),
    "portal": ("Bạn là trợ lý của HDS phục vụ khách hàng đã ký hợp đồng. "
               "Chỉ dựa vào TÀI LIỆU THAM KHẢO — chỉ thuộc về khách đang đăng nhập. "
               "Không nhắc tới bất kỳ khách hàng nào khác. Không đủ căn cứ thì đề nghị liên hệ luật sư."),
}
CHANNEL_LEVEL = {"public": "public", "internal": "internal", "portal": "client"}


def retrieve(question, channel, client_id=None, dept_ids=None, is_banqt=False, top_k=TOP_K):
    """Tìm đoạn liên quan. SQL KHÔNG lọc quyền — RLS tự lo (kể cả theo phòng)."""
    qvec = embed(question)
    level = CHANNEL_LEVEL[channel]
    sql = """SELECT c.id, c.content, c.document_id, d.title,
                    1 - (c.embedding <=> %s::vector) AS score
               FROM chunks c JOIN documents d ON d.id=c.document_id
              WHERE c.embedding IS NOT NULL AND d.approved AND d.label_verified
              ORDER BY c.embedding <=> %s::vector LIMIT %s"""
    with db.session(role=level, client_id=client_id, dept_ids=dept_ids, is_banqt=is_banqt) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (json.dumps(qvec), json.dumps(qvec), top_k))
            rows = cur.fetchall()
    return [{"chunk_id": r[0], "content": r[1], "document_id": r[2], "title": r[3],
             "score": float(r[4])} for r in rows]


def find_method(case_desc):
    """Tìm mẫu phương pháp phân tích phù hợp (nếu admin đã dạy)."""
    try:
        qvec = embed(case_desc)
        with db.session(role="internal") as conn:
            with conn.cursor() as cur:
                cur.execute("""SELECT case_type, steps, 1-(embedding <=> %s::vector) AS s
                                 FROM analysis_methods
                                WHERE approved AND embedding IS NOT NULL
                                ORDER BY embedding <=> %s::vector LIMIT 1""",
                            (json.dumps(qvec), json.dumps(qvec)))
                row = cur.fetchone()
        if row and row[2] > 0.6:               # đủ giống mới áp dụng
            return {"case_type": row[0], "steps": row[1]}
    except Exception:
        pass
    return None


def build_prompt(question, chunks, temp_chunks=None, method=None):
    parts = []
    if method:
        parts.append(f"QUY TRÌNH PHÂN TÍCH (loại: {method['case_type']}):\n{method['steps']}\n"
                     "Hãy phân tích theo đúng quy trình trên.\n")
    all_ctx = list(chunks) + list(temp_chunks or [])
    if all_ctx:
        parts.append("TÀI LIỆU THAM KHẢO:")
        for i, c in enumerate(all_ctx, 1):
            parts.append(f"[Nguồn {i}] {c.get('title','')}\n{c['content']}\n")
    else:
        parts.append("(Không tìm thấy tài liệu liên quan trong kho.)")
    parts.append(f"\nCÂU HỎI: {question}\n"
                 "Trả lời dựa trên tài liệu tham khảo, ghi rõ [Nguồn n] khi dùng thông tin.")
    return "\n".join(parts)


def start_conversation(user_id, channel, client_id=None, title=None):
    level = CHANNEL_LEVEL[channel]
    with db.session(role=level, client_id=client_id) as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO conversations (user_id, channel, client_id, title)
                           VALUES (%s,%s,%s,%s) RETURNING id""",
                        (user_id, channel, client_id, title))
            return cur.fetchone()[0]


def add_temp_file(conversation_id, user_id, filename, content):
    """Nạp file 'dùng xong bỏ' — cắt đoạn, tạo vector, lưu tạm (tự xóa sau 6h)."""
    from app.ingest import split_document
    pieces = split_document(content, "other")
    vecs = embed(pieces) if pieces else []
    with db.session(role="internal") as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO temp_files (conversation_id, user_id, filename, content, embedding_json)
                           VALUES (%s,%s,%s,%s,%s)""",
                        (conversation_id, user_id, filename, content,
                         json.dumps([{"content": p, "vec": v} for p, v in zip(pieces, vecs)])))
    return len(pieces)


def get_temp_context(conversation_id, question, top_k=5):
    """Lấy các đoạn liên quan nhất từ file tạm của cuộc chat này."""
    qvec = embed(question)
    with db.session(role="internal") as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT filename, embedding_json FROM temp_files
                            WHERE conversation_id=%s AND expires_at > now()""", (conversation_id,))
            rows = cur.fetchall()
    scored = []
    import math
    for fname, ej in rows:
        for item in (ej or []):
            v = item["vec"]
            dot = sum(a * b for a, b in zip(qvec, v))
            scored.append({"title": f"[File: {fname}]", "content": item["content"], "score": dot})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]


def answer(question, channel, user_id=None, client_id=None, conversation_id=None,
           prefer="local", use_temp=False, use_method=False,
           dept_ids=None, is_banqt=False):
    """Hàm chính — cả 3 kênh gọi hàm này."""
    if channel not in CHANNEL_LEVEL:
        raise ValueError(f"Kênh không hợp lệ: {channel}")
    if channel == "portal" and client_id is None:
        raise ValueError("Kênh portal bắt buộc có client_id")

    chunks = retrieve(question, channel, client_id, dept_ids=dept_ids, is_banqt=is_banqt)
    temp_chunks = get_temp_context(conversation_id, question) if (use_temp and conversation_id) else None
    method = find_method(question) if use_method else None

    prompt = build_prompt(question, chunks, temp_chunks, method)
    text, latency = llm(prompt, system=SYSTEM_PROMPTS[channel], prefer=prefer)

    msg_id = None
    if conversation_id:
        level = CHANNEL_LEVEL[channel]
        with db.session(role=level, client_id=client_id) as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO messages (conversation_id,role,content) VALUES (%s,'user',%s)",
                            (conversation_id, question))
                cur.execute("""INSERT INTO messages (conversation_id,role,content,sources,model_used,latency_ms)
                               VALUES (%s,'assistant',%s,%s,%s,%s) RETURNING id""",
                            (conversation_id, text, json.dumps([c["chunk_id"] for c in chunks]),
                             prefer, latency))
                msg_id = cur.fetchone()[0]
            db.audit(conn, user_id, "chat_query", "conversation", conversation_id,
                     {"channel": channel, "n_sources": len(chunks), "used_method": bool(method)})

    return {"answer": text,
            "sources": [{"n": i, "title": c["title"], "document_id": c.get("document_id"),
                         "score": round(c["score"], 3)} for i, c in enumerate(chunks, 1)],
            "used_method": method["case_type"] if method else None,
            "latency_ms": latency, "message_id": msg_id}


# =============================================================
# LỚP 2 — HỒ SƠ KHÁCH 360° và cơ chế "hiện tên che / khóa mở"
# =============================================================

# Tên loại tài liệu hiển thị
DOC_TYPE_VN = {
    "law": "Văn bản luật", "ban_an": "Bản án", "an_le": "Án lệ",
    "mau_hd": "Mẫu hợp đồng", "nhan_hieu": "Data nhãn hiệu", "thu_mau": "Thư mẫu",
    "quy_trinh": "Quy trình", "ho_so_ns": "Hồ sơ nhân sự", "ho_so_kh": "Hồ sơ khách hàng",
    "advisory": "Tư vấn", "filing": "Hồ sơ nộp", "contract": "Hợp đồng", "other": "Khác",
}


def can_open_doc(role_level, dept_ids, is_banqt, doc):
    """Quyết định user có được MỞ/tải tài liệu này không (tầng ứng dụng).
    doc: dict có access_level, department_id, doc_type, client_id.
    Trả về True/False. RLS đã lọc thô, đây là lớp chi tiết theo phòng + loại."""
    if is_banqt:
        return True
    acc = doc.get("access_level")
    if acc in ("public", "internal"):
        # tài liệu chung: mọi nội bộ mở được (lọc loại theo access_rules ở nơi khác nếu cần)
        return True
    # hồ sơ khách: chỉ mở nếu cùng phòng
    dep = doc.get("department_id")
    return dep is not None and dep in (dept_ids or [])


def mask_title(doc, can_open):
    """Cách B: nếu KHÔNG được mở và là hồ sơ khách → che tên.
    Tài liệu nội bộ chung thì luôn hiện tên đầy đủ."""
    if can_open:
        return doc.get("title") or "(không tiêu đề)"
    if doc.get("access_level") == "client":
        loai = DOC_TYPE_VN.get(doc.get("doc_type"), "Hồ sơ")
        phong = doc.get("department_name") or "phòng khác"
        return f"[{loai} - {phong}] 🔒 Tài khoản chưa có quyền xem"
    # nội bộ chung nhưng loại bị hạn chế: hiện tên, chỉ khóa mở
    return (doc.get("title") or "(không tiêu đề)") + " 🔒 (chưa có quyền mở)"


def client_360(client_id, requester_dept_ids=None, is_banqt=False):
    """Dựng HỒ SƠ 360° của một khách: thông tin, hồ sơ đã train, vụ việc, giấy tờ.
    Người gọi phải cùng phòng khách hoặc là Ban QT (kiểm ở api trước khi gọi)."""
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT c.id,c.name,c.code,d.name,
                           p.history_note,p.issues_note,p.warnings,p.suggestions
                           FROM clients c
                           LEFT JOIN departments d ON d.id=c.department_id
                           LEFT JOIN client_profiles p ON p.client_id=c.id
                           WHERE c.id=%s""", (client_id,))
            row = cur.fetchone()
            if not row:
                return None
            cur.execute("""SELECT id,code,title,matter_type,status,deadline,opened_at
                           FROM matters WHERE client_id=%s ORDER BY opened_at DESC""", (client_id,))
            matters = cur.fetchall()
            cur.execute("""SELECT id,title,doc_type,summary,created_at,matter_id
                           FROM documents WHERE client_id=%s AND label_verified
                           ORDER BY created_at DESC""", (client_id,))
            docs = cur.fetchall()
    return {
        "client": {"id": row[0], "name": row[1], "code": row[2], "department": row[3]},
        "profile": {"history": row[4], "issues": row[5], "warnings": row[6], "suggestions": row[7]},
        "matters": [{"id": m[0], "code": m[1], "title": m[2], "type": m[3],
                     "status": m[4], "deadline": str(m[5]) if m[5] else None,
                     "opened_at": str(m[6])} for m in matters],
        "documents": [{"id": d[0], "title": d[1], "doc_type": DOC_TYPE_VN.get(d[2], d[2]),
                       "summary": d[3], "created_at": str(d[4])[:10], "matter_id": d[5]} for d in docs],
    }
