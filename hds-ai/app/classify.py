"""
classify.py — AI tự gán nhãn tài liệu (loại, mức truy cập, khách hàng).
⚠️ Gán xong ở trạng thái CHỜ NGƯỜI DUYỆT (label_verified=false).
Chạy: python -m app.classify [--report]
"""
import json
import re
import sys

from app import db
from app.models import llm_local

PROMPT = """Bạn phân loại tài liệu cho công ty luật. Đọc và trả về DUY NHẤT một JSON:
{{"doc_type":"contract|advisory|filing|law|other","access_level":"public|internal|client",
"client_hint":"tên khách nếu có, không thì rỗng","confidence":0.0-1.0}}

TÊN FILE: {title}
NỘI DUNG (2000 ký tự đầu):
{content}

Hướng dẫn: law=văn bản luật/bản án; contract=hợp đồng; advisory=thư tư vấn;
filing=hồ sơ nộp cơ quan. public=luật/giới thiệu; client=gắn khách cụ thể; internal=mẫu/quy trình chung."""


def parse_json(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group())
    except json.JSONDecodeError:
        return None


def match_client(hint):
    if not hint or len(hint.strip()) < 3:
        return None
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT id FROM clients WHERE similarity(name,%s)>0.5
                           ORDER BY similarity(name,%s) DESC LIMIT 1""", (hint, hint))
            row = cur.fetchone()
    return row[0] if row else None


def classify_pending(limit=100):
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT d.id,d.title,
                (SELECT content FROM chunks WHERE document_id=d.id ORDER BY chunk_index LIMIT 1)
                FROM documents d WHERE d.doc_type IS NULL OR NOT d.label_verified
                ORDER BY d.id LIMIT %s""", (limit,))
            rows = cur.fetchall()
    if not rows:
        print("Không có tài liệu cần phân loại.")
        return
    print(f">> Phân loại {len(rows)} tài liệu...\n")
    stats = {"ok": 0, "loi": 0, "can_nguoi": 0}
    for doc_id, title, content in rows:
        if not content:
            continue
        try:
            ans, _ = llm_local(PROMPT.format(title=title or "", content=content[:2000]), temperature=0.1)
            data = parse_json(ans)
            if not data:
                stats["loi"] += 1
                continue
            doc_type = data.get("doc_type", "other")
            access = data.get("access_level", "internal")
            conf = float(data.get("confidence", 0))
            client_id = match_client(data.get("client_hint", "")) if access == "client" else None
            note = ""
            if access == "client" and client_id is None:
                access, conf, note = "internal", 0.0, "  ⚠️ không rõ khách → cần gán tay"
                stats["can_nguoi"] += 1
            with db.session(role="internal", admin=True) as conn:
                with conn.cursor() as cur:
                    cur.execute("""UPDATE documents SET doc_type=%s,access_level=%s,client_id=%s,
                                   confidence=%s,label_verified=false,updated_at=now() WHERE id=%s""",
                                (doc_type, access, client_id, conf, doc_id))
                db.audit(conn, None, "auto_classify", "documents", doc_id, data)
            print(f"  [{doc_id}] {(title or '')[:38]:38s} → {doc_type}/{access} ({conf:.2f}){note}")
            stats["ok"] += 1
        except Exception as e:
            print(f"  [{doc_id}] LỖI: {e}")
            stats["loi"] += 1
    print(f"\nXong: {stats['ok']} gán | {stats['loi']} lỗi | {stats['can_nguoi']} cần gán khách tay")
    print("⚠️  TẤT CẢ đang CHỜ DUYỆT — mở /review để duyệt.")


def report():
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT count(*) FILTER (WHERE label_verified),
                count(*) FILTER (WHERE NOT label_verified),
                count(*) FILTER (WHERE access_level='client' AND client_id IS NULL)
                FROM documents""")
            a, b, cc = cur.fetchone()
    print(f"Đã duyệt: {a} | Chờ duyệt: {b} | Thiếu chủ sở hữu: {cc}")
    if cc:
        print("⚠️ CÓ tài liệu khách thiếu client_id — xử lý ngay!")


if __name__ == "__main__":
    report() if "--report" in sys.argv else classify_pending()
