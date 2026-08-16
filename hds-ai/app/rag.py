"""
rag.py — Bộ máy hỏi đáp dùng chung cho CẢ 3 kênh (website / nội bộ / cổng khách).

QUY TẮC: cả 3 kênh gọi cùng answer(). KHÔNG viết 3 bản riêng.
Phân quyền do RLS ở CSDL lo — SQL bên dưới KHÔNG có điều kiện lọc quyền.

Hỗ trợ thêm:
  - temp_files: file "dùng xong bỏ" trong chat (không vào kho)
  - analysis_methods: áp mẫu phương pháp admin đã dạy
"""
import json
import time

from app import company_context, db, settings
from app.models import embed, llm

# --------------------------------------------------------------------
# NGÂN SÁCH NGỮ CẢNH — phần quyết định tốc độ trả lời
#
# Thời gian trả lời ≈ thời gian ĐỌC prompt + thời gian VIẾT câu trả lời.
# Phần đọc tỉ lệ thuận với độ dài prompt và KHÔNG phụ thuộc câu hỏi khó hay dễ:
# nhồi 8 đoạn × 700 từ vào mỗi lượt thì câu "chào bạn" cũng nặng như câu phân
# tích hợp đồng. Vì vậy giới hạn ở đây, chứ không phải ở kích thước kho dữ liệu.
#
# Lưu ý: kho có 1 tài liệu hay 1 triệu tài liệu thì prompt vẫn bằng nhau — tìm
# kiếm vector luôn trả về đúng top_k đoạn. Kho lớn lên KHÔNG làm chậm trả lời.
# --------------------------------------------------------------------
TOP_K = 5                 # số đoạn tài liệu đưa vào prompt
CHUNK_CHARS = 1500        # cắt mỗi đoạn còn bấy nhiêu ký tự
CONTEXT_CHARS = 6000      # tổng ngân sách cho toàn bộ tài liệu tham khảo
HISTORY_CHARS = 300       # mỗi lượt hỏi-đáp cũ chỉ giữ bấy nhiêu ký tự
MIN_SCORE = 0.25          # dưới ngưỡng này coi như không liên quan, bỏ đi

CHANNEL_LEVEL = {"public": "public", "internal": "internal", "portal": "client"}

# Phong cách tư vấn (system prompt) KHÔNG còn nằm cứng ở đây nữa — admin sửa
# trên web, lưu ở bảng app_settings. Xem app/settings.py (khoá prompt_<kênh>).


def retrieve(question, channel, client_id=None, dept_ids=None, is_banqt=False,
             top_k=None, can_finance=False, doc_types=None):
    """Tìm đoạn liên quan. SQL KHÔNG lọc quyền — RLS tự lo (kể cả theo phòng
    và quyền xem công nợ).

    doc_types: giới hạn theo GÓI DỊCH VỤ của khách (không phải ranh giới bảo
    mật — việc khách A không thấy dữ liệu khách B vẫn do RLS lo). None là
    không giới hạn.
    """
    if top_k is None:
        top_k = settings.get_int("retrieval_top_k", TOP_K)
    qjson = json.dumps(embed(question))
    level = CHANNEL_LEVEL[channel]
    sql = """SELECT c.id, c.content, c.document_id, d.title,
                    1 - (c.embedding <=> %s::vector) AS score
               FROM chunks c JOIN documents d ON d.id=c.document_id
              WHERE c.embedding IS NOT NULL AND d.approved AND d.label_verified"""
    params = [qjson]
    if doc_types is not None:
        sql += " AND c.doc_type = ANY(%s)"
        params.append(list(doc_types))
    sql += " ORDER BY c.embedding <=> %s::vector LIMIT %s"
    params += [qjson, top_k]
    with db.session(role=level, client_id=client_id, dept_ids=dept_ids, is_banqt=is_banqt,
                    can_finance=can_finance) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    return [{"chunk_id": r[0], "content": r[1], "document_id": r[2], "title": r[3],
             "score": float(r[4])} for r in rows]


def tier_doc_types(role_level):
    """Loại tài liệu một GÓI KHÁCH được tra cứu, lấy từ bảng access_rules.

    Trả None khi ma trận chưa có dòng nào cho vai này — nghĩa là chưa cấu hình
    gói, khi đó không lọc theo loại. Nếu chặn sạch thì chỉ cần quên chạy
    seed_departments là cổng khách ngưng trả lời, hỏng nặng hơn là hở gói.

    Trả set rỗng khi có cấu hình nhưng gói không được phép loại nào.
    """
    rules = load_access_rules()
    if not any(role == role_level for (role, _dept, _dt) in rules):
        return None
    return {dt for (role, dept, dt), can_open in rules.items()
            if role == role_level and dept == "*" and can_open}


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


def get_history(conversation_id, channel, client_id=None, turns=None):
    """Mấy lượt hỏi-đáp gần nhất trong cùng cuộc chat.

    Không có phần này thì mỗi câu hỏi là một lần đầu tiên: hỏi tiếp "còn vụ kia
    thì sao" là bot không biết "vụ kia" là gì. Đọc TRƯỚC khi ghi câu hỏi hiện
    tại nên lịch sử luôn là các lượt đã xong.
    """
    if not conversation_id:
        return []
    if turns is None:
        turns = settings.get_int("chat_history_turns", 3)
    if turns <= 0:
        return []
    level = CHANNEL_LEVEL[channel]
    try:
        with db.session(role=level, client_id=client_id) as conn:
            with conn.cursor() as cur:
                cur.execute("""SELECT role, content FROM messages
                                WHERE conversation_id=%s
                                ORDER BY id DESC LIMIT %s""",
                            (conversation_id, turns * 2))
                rows = cur.fetchall()
    except Exception:
        return []
    return list(reversed(rows))


def fit_context(chunks, chunk_chars=None, budget=None):
    """Cắt danh sách đoạn cho vừa ngân sách ký tự, giữ nguyên thứ tự liên quan.

    Mỗi đoạn bị cắt về `chunk_chars`, và dừng nhận thêm khi đã đủ `budget`. Đoạn
    xếp trên là đoạn khớp nhất nên bị cắt sau cùng — cắt từ đuôi danh sách là
    mất phần ít liên quan nhất.
    """
    chunk_chars = chunk_chars or settings.get_int("chunk_char_limit", CHUNK_CHARS)
    budget = budget or settings.get_int("context_char_budget", CONTEXT_CHARS)
    out, used = [], 0
    for c in chunks:
        if used >= budget:
            break
        content = (c.get("content") or "")[:chunk_chars]
        room = budget - used
        if len(content) > room:
            content = content[:room].rstrip() + "…"
        out.append({**c, "content": content})
        used += len(content)
    return out


def build_prompt(question, chunks, temp_chunks=None, method=None,
                 company="", history=None, chunk_chars=None, budget=None):
    parts = []
    if method:
        parts.append(f"QUY TRÌNH PHÂN TÍCH (loại: {method['case_type']}):\n{method['steps']}\n"
                     "Hãy phân tích theo đúng quy trình trên.\n")
    if company:
        # Số liệu thật trong CSDL, không phải trích từ tài liệu → không đánh [Nguồn n]
        parts.append(company + "\n")
    if history:
        parts.append("DIỄN BIẾN CUỘC TRAO ĐỔI TRƯỚC ĐÓ:")
        for role, content in history:
            who = "Người hỏi" if role == "user" else "Trợ lý"
            parts.append(f"{who}: {(content or '')[:HISTORY_CHARS]}")
        parts.append("")
    # Ngân sách áp cho CẢ tài liệu trong kho lẫn file tạm đính kèm — nếu không,
    # một file tải lên trong chat vẫn đủ sức thổi prompt lên quá cỡ.
    all_ctx = fit_context(list(chunks) + list(temp_chunks or []), chunk_chars, budget)
    if all_ctx:
        parts.append("TÀI LIỆU THAM KHẢO:")
        for i, c in enumerate(all_ctx, 1):
            parts.append(f"[Nguồn {i}] {c.get('title','')}\n{c['content']}\n")
    else:
        parts.append("(Không tìm thấy tài liệu liên quan trong kho.)")
    parts.append(f"\nCÂU HỎI: {question}\n"
                 "Trả lời dựa trên tài liệu tham khảo, ghi rõ [Nguồn n] khi dùng thông tin.")
    if company:
        parts.append("Phần DỮ LIỆU CÔNG TY là số liệu thực tế trong hệ thống — dùng trực tiếp, "
                     "không cần ghi [Nguồn]. Nêu rõ ngày/hạn khi trả lời về tiến độ vụ việc.")
    return "\n".join(parts)


def start_conversation(user_id, channel, client_id=None, title=None):
    level = CHANNEL_LEVEL[channel]
    with db.session(role=level, client_id=client_id) as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO conversations (user_id, channel, client_id, title)
                           VALUES (%s,%s,%s,%s) RETURNING id""",
                        (user_id, channel, client_id, title))
            return cur.fetchone()[0]


def get_or_create_conversation(user_id, channel, client_id=None):
    """MỖI NGƯỜI một hội thoại bền cho mỗi kênh (mô hình Messenger) — không mở
    hội thoại mới mỗi lần. Nhờ vậy bot nắm được toàn bộ lịch sử và đóng vai thư
    ký riêng của người đó. Kênh public (khách vãng lai) không có user_id nên vẫn
    dùng start_conversation theo phiên."""
    if not user_id:
        return start_conversation(None, channel, client_id, title="Khách")
    level = CHANNEL_LEVEL[channel]
    with db.session(role=level, client_id=client_id) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT id FROM conversations
                            WHERE user_id=%s AND channel=%s ORDER BY id LIMIT 1""",
                        (user_id, channel))
            row = cur.fetchone()
            if row:
                return row[0]
            cur.execute("""INSERT INTO conversations (user_id, channel, client_id, title)
                           VALUES (%s,%s,%s,'Trợ lý') RETURNING id""",
                        (user_id, channel, client_id))
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


def resolve_model(model_choice, question):
    """Từ lựa chọn của người dùng → tên model cụ thể (hoặc None = mặc định).
      ''/None      → None (dùng model mặc định của máy chủ)
      'auto'       → models.auto_pick_model (câu đơn giản chọn model nhanh)
      '<tên model>'→ đúng model đó"""
    choice = (model_choice or "").strip()
    if not choice:
        return None
    if choice.lower() == "auto":
        from app.models import auto_pick_model
        return auto_pick_model(question)
    return choice


SLOW_MS = 20000   # trên mức này thì ghi log để soi lại, dưới thì im lặng


def _log_slow(question, t):
    """In một dòng chẩn đoán khi câu trả lời chậm bất thường.

    Xem bằng:  sudo journalctl -u hds-ai-backend -n 200 | grep CHAM
    Đọc dòng này là biết ngay chậm ở đâu: `doc` lớn nghĩa là prompt quá dài,
    `nap` lớn nghĩa là model bị đẩy ra khỏi bộ nhớ và phải nạp lại từ ổ cứng,
    `viet` lớn nghĩa là model quá nặng so với máy.
    """
    if t.get("ai_ms", 0) < SLOW_MS:
        return
    print(f"[CHAM] {t.get('ai_ms')}ms | model={t.get('model')} "
          f"| prompt={t.get('prompt_tokens')} token, doc={t.get('prefill_ms')}ms "
          f"| sinh={t.get('gen_tokens')} token, viet={t.get('gen_ms')}ms "
          f"| nap={t.get('load_ms')}ms | tim={t.get('tim_kiem_ms')}ms "
          f"| doan={t.get('so_doan')} | hoi={(question or '')[:60]!r}", flush=True)


def answer(question, channel, user_id=None, client_id=None, conversation_id=None,
           prefer="local", use_temp=False, use_method=False,
           dept_ids=None, is_banqt=False, can_finance=False, role=None, model=None):
    """Hàm chính — cả 3 kênh gọi hàm này."""
    if channel not in CHANNEL_LEVEL:
        raise ValueError(f"Kênh không hợp lệ: {channel}")
    if channel == "portal" and client_id is None:
        raise ValueError("Kênh portal bắt buộc có client_id")

    # Đọc cài đặt MỘT LẦN cho cả lượt hỏi (prompt, nhiệt độ, top_k) thay vì mở
    # ba kết nối CSDL riêng. Vẫn lấy tươi mỗi câu hỏi nên admin sửa là ăn ngay.
    cfg = settings.get_all()

    def _num(key, fallback, cast):
        try:
            return cast(float(cfg.get(key)))
        except (TypeError, ValueError):
            return fallback

    # Cổng khách: giới hạn loại tài liệu theo gói dịch vụ (Free/Plus/Pro).
    # Kênh nội bộ không giới hạn ở đây — quyền nội bộ nằm ở RLS và can_open_doc.
    doc_types = tier_doc_types(role) if (channel == "portal" and role) else None

    # Đo từng chặng để biết chậm ở đâu — không đo thì chỉ đoán mò.
    timings: dict = {}
    clock = [time.time()]

    def tick(key):
        now = time.time()
        timings[key] = int((now - clock[0]) * 1000)
        clock[0] = now

    chunks = retrieve(question, channel, client_id, dept_ids=dept_ids, is_banqt=is_banqt,
                      top_k=_num("retrieval_top_k", TOP_K, int), can_finance=can_finance,
                      doc_types=doc_types)
    # Đoạn điểm thấp là đoạn không liên quan tới câu hỏi: nó không giúp câu trả
    # lời mà vẫn ngốn thời gian đọc prompt. Câu hỏi ngoài phạm vi kho tài liệu
    # (vd hỏi về nhân sự công ty) nhờ vậy đi thẳng, không phải cõng 5 đoạn luật.
    min_score = _num("min_relevance", MIN_SCORE, float)
    kept = [c for c in chunks if c["score"] >= min_score]
    timings["bo_qua_doan_yeu"] = len(chunks) - len(kept)
    chunks = kept
    tick("tim_kiem_ms")

    temp_chunks = get_temp_context(conversation_id, question) if (use_temp and conversation_id) else None
    method = find_method(question) if use_method else None

    # Hai nguồn ngữ cảnh song song: tài liệu (vector) và dữ liệu vận hành (SQL).
    # Thiếu nguồn thứ hai thì bot không trả lời được câu hỏi về khách/vụ việc.
    company = company_context.build(question, channel, client_id=client_id,
                                    dept_ids=dept_ids, is_banqt=is_banqt,
                                    can_finance=can_finance)
    history = get_history(conversation_id, channel, client_id)
    tick("du_lieu_cong_ty_ms")

    # Truyền thẳng ngân sách đã đọc từ `cfg` — để build_prompt tự đọc lại thì
    # mỗi câu hỏi phải mở thêm hai kết nối CSDL cho hai con số.
    prompt = build_prompt(question, chunks, temp_chunks, method,
                          company=company, history=history,
                          chunk_chars=_num("chunk_char_limit", CHUNK_CHARS, int),
                          budget=_num("context_char_budget", CONTEXT_CHARS, int))
    system_prompt = cfg.get(f"prompt_{channel}") or settings.DEFAULTS.get(f"prompt_{channel}", "")
    chosen_model = resolve_model(model, question)
    llm_stats: dict = {}
    text, latency = llm(prompt, system=system_prompt, prefer=prefer,
                        temperature=_num("llm_temperature", 0.2, float),
                        model=chosen_model, stats=llm_stats)
    timings["ai_ms"] = latency
    timings.update({k: v for k, v in llm_stats.items()
                    if k in ("prompt_tokens", "gen_tokens", "load_ms",
                             "prefill_ms", "gen_ms", "num_ctx", "model")})
    timings["so_doan"] = len(chunks)
    _log_slow(question, timings)

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
                             chosen_model or prefer, latency))
                msg_id = cur.fetchone()[0]
            db.audit(conn, user_id, "chat_query", "conversation", conversation_id,
                     {"channel": channel, "n_sources": len(chunks), "used_method": bool(method)})

    return {"answer": text,
            "sources": [{"n": i, "title": c["title"], "document_id": c.get("document_id"),
                         "score": round(c["score"], 3)} for i, c in enumerate(chunks, 1)],
            "used_method": method["case_type"] if method else None,
            "latency_ms": latency, "message_id": msg_id, "timings": timings}


# =============================================================
# LỚP 2 — HỒ SƠ KHÁCH 360° và cơ chế "hiện tên che / khóa mở"
# =============================================================

# Tên loại tài liệu hiển thị
DOC_TYPE_VN = {
    "law": "Văn bản luật", "ban_an": "Bản án", "an_le": "Án lệ",
    "mau_hd": "Mẫu hợp đồng", "nhan_hieu": "Data nhãn hiệu", "thu_mau": "Thư mẫu",
    "quy_trinh": "Quy trình", "ho_so_ns": "Hồ sơ nhân sự", "ho_so_kh": "Hồ sơ khách hàng",
    "advisory": "Tư vấn", "filing": "Hồ sơ nộp", "contract": "Hợp đồng",
    "cong_no": "Công nợ - Tài chính", "other": "Khác",
}


def load_access_rules():
    """Ma trận quyền loại tài liệu × cấp × phòng, đọc từ bảng access_rules.

    Bảng này do app/seed_departments.py nạp từ bảng phân quyền nhân sự của HDS.
    Trả về dict {(role_level, department_code, doc_type): can_open}.

    Đọc mỗi lần gọi để sửa bảng là có hiệu lực ngay, không phải khởi động lại —
    cùng nguyên tắc với app_settings. Bảng chỉ vài trăm dòng nên không đáng lo.
    """
    try:
        with db.session(role="internal", admin=True) as conn:
            with conn.cursor() as cur:
                cur.execute("""SELECT role_level, department_code, doc_type, can_open
                                 FROM access_rules""")
                return {(r[0], r[1], r[2]): r[3] for r in cur.fetchall()}
    except Exception:
        return {}


def _rules_allow_open(rules, role_level, dept_codes, doc_type):
    """Ma trận có cho cấp này mở loại tài liệu này không.

    Người thuộc nhiều phòng: chỉ cần MỘT phòng được phép là mở được. Dòng '*'
    áp cho mọi phòng.

    Không tìm thấy dòng nào khớp thì TRẢ VỀ FALSE (chặn). Bảng đã có dữ liệu mà
    thiếu dòng cho một loại tài liệu nghĩa là loại đó chưa được cấp phép — mặc
    định mở sẽ khiến mỗi lần thêm doc_type mới là tự động hở cho mọi người.
    """
    if rules.get((role_level, "*", doc_type)):
        return True
    return any(rules.get((role_level, code, doc_type)) for code in (dept_codes or []))


def can_open_doc(role_level, dept_ids, is_banqt, doc, can_finance=False,
                 rules=None, dept_codes=None):
    """Quyết định user có được MỞ/tải tài liệu này không (tầng ứng dụng).
    doc: dict có access_level, department_id, doc_type, client_id.
    Trả về True/False. RLS đã lọc thô, đây là lớp chi tiết theo phòng + loại.

    Tài liệu công nợ chặn trước mọi điều kiện khác, kể cả Ban QT: các endpoint
    duyệt/tải mở phiên bằng admin=True nên RLS không áp — chốt phải nằm ở đây.

    rules/dept_codes: truyền vào để áp ma trận access_rules. Bỏ trống thì giữ
    hành vi cũ (mọi nội bộ mở được tài liệu chung) — dùng cho các lời gọi chưa
    có thông tin phòng, và cho hệ thống chưa nạp ma trận."""
    if doc.get("doc_type") == "cong_no" and not can_finance:
        return False
    if is_banqt:
        return True
    acc = doc.get("access_level")
    doc_type = doc.get("doc_type")
    if acc in ("public", "internal"):
        if rules:
            return _rules_allow_open(rules, role_level, dept_codes, doc_type)
        return True
    # hồ sơ khách: phải cùng phòng, VÀ ma trận phải cho phép mở loại này
    dep = doc.get("department_id")
    if dep is None or dep not in (dept_ids or []):
        return False
    if rules:
        return _rules_allow_open(rules, role_level, dept_codes, doc_type)
    return True


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
