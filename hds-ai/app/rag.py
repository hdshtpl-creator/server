"""
rag.py — Bộ máy hỏi đáp dùng chung cho CẢ 3 kênh (website / nội bộ / cổng khách).

QUY TẮC: cả 3 kênh gọi cùng answer(). KHÔNG viết 3 bản riêng.
Phân quyền do RLS ở CSDL lo — SQL bên dưới KHÔNG có điều kiện lọc quyền.

Hỗ trợ thêm:
  - temp_files: file "dùng xong bỏ" trong chat (không vào kho)
  - analysis_methods: áp mẫu phương pháp admin đã dạy
"""
import json
import re
import time
import unicodedata
from collections import defaultdict
from datetime import date

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
# `top_k` giữ prompt ổn định khi kho lớn, nhưng thời gian retrieval và RAM cho
# chỉ mục vẫn tăng theo dữ liệu. Vì vậy kho triệu đoạn phải kiểm chứng bằng
# EXPLAIN/load-test; không được coi câu "prompt không đổi" là cam kết tốc độ.
# --------------------------------------------------------------------
TOP_K = 8                 # số đoạn tài liệu đưa vào prompt
CHUNK_CHARS = 2400        # cắt mỗi đoạn còn bấy nhiêu ký tự
CONTEXT_CHARS = 14000     # tổng ngân sách cho toàn bộ tài liệu tham khảo
HISTORY_CHARS = 300       # mỗi lượt hỏi-đáp cũ chỉ giữ bấy nhiêu ký tự
MIN_SCORE = 0.25          # dưới ngưỡng này coi như không liên quan, bỏ đi
RETRIEVAL_CANDIDATES = 60 # lấy rộng rồi xếp hạng lại trước khi cắt top_k
MAX_CHUNKS_PER_DOC = 3    # tránh một tài liệu chiếm hết mọi vị trí nguồn

CHANNEL_LEVEL = {"public": "public", "internal": "internal", "portal": "client"}


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFD", text or "")
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", text.replace("đ", "d").replace("Đ", "d").lower()).strip()


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", _fold(text)) if len(t) > 1}


def _or_tsquery(question: str) -> str | None:
    """Chuỗi to_tsquery dạng 'sơ | yếu | ngân' cho lượt tìm từ khoá NỚI LỎNG.

    plainto_tsquery đòi khớp TẤT CẢ các từ — một chữ lệch chính tả là nhánh từ
    khoá chết cả lượt. Ca thật 19/08/2026: "sơ yếu LÍ lịch CỬA Ngân" (i ngắn +
    gõ nhầm) không khớp tài liệu nào vì kho ghi "lý lịch"; chỉ còn semantic,
    mà embedding thì coi mọi sơ yếu lý lịch na ná nhau — từ "Ngân" mất sạch
    sức nặng, bot lấy nhầm sơ yếu của người khác.

    Nới thành OR thì ts_rank_cd tự thưởng tài liệu khớp NHIỀU từ: file chứa
    "sơ yếu lý lịch" + họ tên có "Ngân" (4 từ) vẫn thắng file chỉ khớp từ phổ
    thông. GIỮ NGUYÊN DẤU: search_vector dùng cấu hình 'simple' nên token trong
    chỉ mục có dấu; fold ở đây là tự tay làm hỏng phép khớp.
    """
    tokens = re.findall(r"[0-9a-zà-ỹ]+", (question or "").lower())
    tokens = [t for t in dict.fromkeys(tokens) if len(t) >= 2][:12]
    if not tokens:
        return None
    return " | ".join(tokens)


def resolve_search_question(question, history=None, state=None) -> str:
    """Viết lại câu tra cứu ngắn bằng chủ đề đã biết, không gọi thêm LLM.

    Lịch sử trước đây chỉ được đưa vào prompt SAU khi retrieval đã xong, nên
    câu "chi tiết từng cá nhân" đi tìm tài liệu bằng chính năm chữ mơ hồ đó.
    Hàm này chạy trước retrieval và chỉ nối tối đa câu hỏi người dùng gần nhất.
    """
    folded = _fold(question)
    followup = (len(folded.split()) <= 10 and any(w in folded for w in (
        "chi tiet", "cu the", "ro hon", "tung ca nhan", "tung nguoi",
        "con nua", "con ai", "the nao", "ra sao", "toi hoi", "y toi",
        "danh sach", "liet ke",
    )))
    if not followup:
        return question
    previous = [content for role, content in (history or []) if role == "user"]
    context = previous[-1] if previous else (state or {}).get("last_question", "")
    return f"{context}. {question}".strip(". ") if context else question


def _smalltalk_answer(question: str):
    folded = _fold(question).strip(" .!?\t\r\n")
    if folded in {"chao", "xin chao", "hello", "hi", "alo"}:
        return "Chào bạn, mình là Trợ lý AI HDS. Bạn muốn tra cứu hồ sơ, dữ liệu công ty hay soạn tài liệu gì?"
    if folded in {"cam on", "cảm ơn", "thanks", "thank you"}:
        return "Mình rất vui được hỗ trợ."
    return None

# Phong cách tư vấn (system prompt) KHÔNG còn nằm cứng ở đây nữa — admin sửa
# trên web, lưu ở bảng app_settings. Xem app/settings.py (khoá prompt_<kênh>).


def retrieve(question, channel, client_id=None, dept_ids=None, is_banqt=False,
             top_k=None, can_finance=False, doc_types=None, document_ids=None,
             candidate_k=None, max_per_document=None, query_vector=None,
             neighbours=True):
    """Hybrid retrieval: vector + từ khoá chính xác rồi xếp hạng lại.

    RLS vẫn là ranh giới bảo mật. `document_ids` chỉ THU HẸP bộ nguồn người dùng
    đã chọn; nó không thể mở rộng quyền. Lấy nhiều ứng viên để mã hồ sơ/Điều luật
    có cơ hội thắng, sau đó đa dạng hoá theo tài liệu để một file không chiếm
    toàn bộ top-k.
    """
    if top_k is None:
        top_k = settings.get_int("retrieval_top_k", TOP_K)
    if document_ids is not None:
        safe_ids = set()
        for raw_id in document_ids:
            try:
                value = int(raw_id)
            except (TypeError, ValueError):
                continue
            if value > 0:
                safe_ids.add(value)
        document_ids = sorted(safe_ids)[:50]
        if not document_ids:
            return []
    candidate_k = candidate_k or settings.get_int(
        "retrieval_candidate_k", max(RETRIEVAL_CANDIDATES, top_k * 8))
    candidate_k = max(top_k, min(int(candidate_k), 200))
    max_per_document = max_per_document or settings.get_int(
        "retrieval_max_chunks_per_doc", MAX_CHUNKS_PER_DOC)
    max_per_document = max(1, min(int(max_per_document), top_k))

    qjson = json.dumps(query_vector if query_vector is not None else embed(question))
    level = CHANNEL_LEVEL[channel]
    # LEFT JOIN clients để mỗi đoạn tự biết nó thuộc hồ sơ của KHÁCH NÀO.
    # Không có cột này thì "Giấy đề nghị ĐKDN" của khách đọc y hệt tài liệu của
    # chính HDS, và model từng lấy "tổng số lao động dự kiến: 02" của công ty
    # khách ra trả lời câu "công ty tôi có bao nhiêu nhân sự". Bảng clients
    # không có RLS nhưng chunks/documents có — hàng không được phép xem đã bị
    # chặn từ trước khi join.
    select = """SELECT c.id,c.content,c.document_id,d.title,d.drive_file_id,
                       1-(c.embedding <=> %s::vector) AS semantic_score,
                       {lexical} AS lexical_score,
                       c.page_number,c.section_title,c.source_locator,
                       d.source_version,c.chunk_index,d.doc_type,d.client_id,cl.name
                  FROM chunks c JOIN documents d ON d.id=c.document_id
                  LEFT JOIN clients cl ON cl.id=d.client_id"""
    where = """ WHERE c.embedding IS NOT NULL AND d.approved AND d.label_verified
                       AND coalesce(d.active,true)
                       AND coalesce(d.extraction_status,'ready')='ready'"""
    filter_params = []
    if doc_types is not None:
        where += " AND c.doc_type=ANY(%s)"
        filter_params.append(list(doc_types))
    if document_ids is not None:
        where += " AND d.id=ANY(%s)"
        filter_params.append(document_ids)

    vector_sql = select.format(lexical="0::real") + where
    vector_sql += " ORDER BY c.embedding <=> %s::vector LIMIT %s"
    vector_params = [qjson, *filter_params, qjson, candidate_k]

    # `simple` tách token tiếng Việt theo khoảng trắng, phù hợp cho mã hồ sơ,
    # số điều và tên riêng. Query lexical vẫn tính semantic_score để hai nhánh
    # có chung thang điểm khi gộp.
    lexical_select = select.format(
        lexical="ts_rank_cd(c.search_vector,q.query)")
    lexical_tail = (" CROSS JOIN q " + where
                    + " AND q.query @@ c.search_vector"
                    + " ORDER BY lexical_score DESC LIMIT %s")
    lexical_sql = ("WITH q AS (SELECT plainto_tsquery('simple',%s) AS query) "
                   + lexical_select + lexical_tail)
    lexical_params = [question, qjson, *filter_params, candidate_k]
    # Lượt hai NỚI LỎNG (OR) — chỉ chạy khi lượt AND trắng tay, để câu gõ chuẩn
    # giữ nguyên hành vi cũ còn câu lệch một chữ không mất cả nhánh từ khoá.
    lexical_or_sql = ("WITH q AS (SELECT to_tsquery('simple',%s) AS query) "
                      + lexical_select + lexical_tail)

    with db.session(role=level, client_id=client_id, dept_ids=dept_ids,
                    is_banqt=is_banqt, can_finance=can_finance) as conn:
        with conn.cursor() as cur:
            cur.execute(vector_sql, vector_params)
            rows = cur.fetchall()
            try:
                cur.execute(lexical_sql, lexical_params)
                lex_rows = cur.fetchall()
                if not lex_rows:
                    or_query = _or_tsquery(question)
                    if or_query:
                        cur.execute(lexical_or_sql,
                                    [or_query, qjson, *filter_params, candidate_k])
                        lex_rows = cur.fetchall()
                rows += lex_rows
            except Exception:
                # Kho cũ chưa có chỉ mục FTS vẫn phải phục vụ được bằng vector.
                conn.rollback()

    merged = {}
    for r in rows:
        item = merged.setdefault(r[0], {
            "chunk_id": r[0], "content": r[1], "document_id": r[2],
            "title": r[3], "drive_file_id": r[4],
            "semantic_score": float(r[5] or 0), "lexical_score": 0.0,
            "page_number": r[7], "section_title": r[8],
            "source_locator": r[9], "source_version": r[10],
            "chunk_index": r[11], "doc_type": r[12], "client_id": r[13],
            "client_name": r[14],
        })
        item["semantic_score"] = max(item["semantic_score"], float(r[5] or 0))
        item["lexical_score"] = max(item["lexical_score"], float(r[6] or 0))

    max_lex = max((x["lexical_score"] for x in merged.values()), default=0.0)
    qtokens = _tokens(question)
    qfold = _fold(question)
    for item in merged.values():
        ctokens = _tokens(item["content"])
        coverage = len(qtokens & ctokens) / max(1, len(qtokens))
        lexical = item["lexical_score"] / max_lex if max_lex else 0.0
        exact = 1.0 if len(qfold) >= 4 and qfold in _fold(item["content"]) else 0.0
        semantic = max(0.0, min(1.0, item["semantic_score"]))
        item["score"] = min(1.0, 0.75 * semantic + 0.15 * lexical
                            + 0.08 * coverage + 0.02 * exact)

    ranked = sorted(merged.values(), key=lambda x: x["score"], reverse=True)
    chosen, counts, used = [], defaultdict(int), set()
    for item in ranked:
        if counts[item["document_id"]] >= max_per_document:
            continue
        chosen.append(item)
        used.add(item["chunk_id"])
        counts[item["document_id"]] += 1
        if len(chosen) >= top_k:
            break
    # Khi bộ nguồn chỉ có một/hai file, lấp đủ top-k thay vì trả thiếu vô cớ.
    for item in ranked:
        if len(chosen) >= top_k:
            break
        if item["chunk_id"] not in used:
            chosen.append(item)
            used.add(item["chunk_id"])
    return _with_neighbours(chosen, level, client_id, dept_ids, is_banqt,
                            can_finance) if neighbours else chosen


def _with_neighbours(chosen, level, client_id, dept_ids, is_banqt, can_finance,
                     top_n=3):
    """Kèm đoạn LIỀN TRƯỚC và LIỀN SAU của mấy đoạn khớp nhất.

    Tra cứu trả về từng đoạn rời rạc, nên câu trả lời hay bị cụt ở chỗ ý vắt
    sang đoạn kế: điều khoản nêu điều kiện ở đoạn này và ngoại lệ ở đoạn sau,
    bot chỉ thấy một nửa rồi khẳng định chắc nịch nửa ấy.

    Chỉ mở rộng cho `top_n` đoạn đầu — mở rộng tất cả thì ngân sách ngữ cảnh bị
    đoạn phụ chiếm mất chỗ của đoạn chính. Đoạn hàng xóm mang điểm thấp hơn
    đoạn gốc một chút để khi sắp xếp/cắt bớt thì chúng nhường chỗ trước.
    """
    if not chosen:
        return chosen
    wanted = []
    for item in chosen[:top_n]:
        index = item.get("chunk_index")
        if index is None:
            continue
        for neighbour in (index - 1, index + 1):
            if neighbour >= 0:
                wanted.append((item["document_id"], neighbour, item["score"]))
    if not wanted:
        return chosen

    have = {(c["document_id"], c.get("chunk_index")) for c in chosen}
    pairs = [(d, i) for d, i, _ in wanted if (d, i) not in have]
    if not pairs:
        return chosen
    score_of = {(d, i): s for d, i, s in wanted}
    # Hai mảng song song rồi ghép bằng unnest. Truyền thẳng danh sách cặp vào
    # ANY(%s) đòi hỏi một kiểu composite trong CSDL — psycopg3 không tự dựng.
    doc_ids = [d for d, _ in pairs]
    idxs = [i for _, i in pairs]

    with db.session(role=level, client_id=client_id, dept_ids=dept_ids,
                    is_banqt=is_banqt, can_finance=can_finance) as conn:
        with conn.cursor() as cur:
            # RLS vẫn chặn ở đây: đoạn hàng xóm nằm ngoài quyền sẽ không trả về.
            cur.execute("""SELECT c.id,c.content,c.document_id,d.title,d.drive_file_id,
                                  c.page_number,c.section_title,c.source_locator,
                                  d.source_version,c.chunk_index,
                                  d.doc_type,d.client_id,cl.name
                             FROM chunks c JOIN documents d ON d.id=c.document_id
                             LEFT JOIN clients cl ON cl.id=d.client_id
                            WHERE (c.document_id, c.chunk_index) IN (
                                    SELECT * FROM unnest(%s::int[], %s::int[]))
                              AND d.approved AND d.label_verified
                              AND coalesce(d.active,true)
                              AND coalesce(d.extraction_status,'ready')='ready'""",
                        (doc_ids, idxs))
            rows = cur.fetchall()

    for r in rows:
        chosen.append({
            "chunk_id": r[0], "content": r[1], "document_id": r[2],
            "title": r[3], "drive_file_id": r[4],
            "semantic_score": 0.0, "lexical_score": 0.0,
            "page_number": r[5], "section_title": r[6],
            "source_locator": r[7], "source_version": r[8],
            "chunk_index": r[9], "doc_type": r[10], "client_id": r[11],
            "client_name": r[12],
            # Thấp hơn đoạn gốc: hàng xóm là ngữ cảnh bổ trợ, không phải căn cứ chính.
            "score": max(0.0, score_of.get((r[2], r[9]), 0.3) - 0.05),
            "is_neighbour": True,
        })
    return chosen


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


def find_method(case_desc, query_vector=None):
    """Tìm mẫu phương pháp phân tích phù hợp (nếu admin đã dạy)."""
    try:
        qvec = query_vector if query_vector is not None else embed(case_desc)
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


def get_conversation_state(conversation_id, channel, client_id=None):
    """Chủ đề có cấu trúc của lượt trước; text history chỉ là lớp bổ sung."""
    if not conversation_id:
        return {}
    try:
        with db.session(role=CHANNEL_LEVEL[channel], client_id=client_id) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT context_state FROM conversations WHERE id=%s",
                            (conversation_id,))
                row = cur.fetchone()
        return row[0] if row and isinstance(row[0], dict) else {}
    except Exception:
        # Tương thích trong lúc schema cũ chưa được migrate.
        return {}


def _best_window(content: str, question: str, limit: int) -> str:
    """Lấy khúc LIÊN QUAN NHẤT trong một đoạn dài, thay vì cắt từ đầu.

    Một đoạn được lưu dài tới ~700 từ (khoảng 4000+ ký tự), trong khi ngân sách
    chỉ cho vài nghìn ký tự. Cắt thẳng `content[:limit]` là đọc phần ĐẦU đoạn —
    nhưng câu trả lời thường nằm ở giữa hoặc cuối. Bot vì thế nhận được đúng
    tài liệu mà vẫn không thấy chỗ chứa đáp án, nên không gắn nổi trích dẫn.

    Cách làm: trượt theo từng câu, cộng điểm cho câu chứa từ khoá của câu hỏi,
    rồi giữ lại cửa sổ liên tiếp ghi điểm cao nhất. Không tra cứu gì thêm, chỉ
    là đếm chữ nên gần như không tốn thời gian.
    """
    content = content or ""
    if len(content) <= limit:
        return content
    qtokens = _tokens(question)
    # Không có từ khoá nào để bám thì giữ hành vi cũ — cắt từ đầu.
    if not qtokens:
        return content[:limit].rstrip() + "…"

    # Tách theo câu, giữ nguyên dấu câu để đoạn trích còn đọc được.
    sentences = re.split(r"(?<=[.!?;:\n])\s+", content)
    scores = [len(qtokens & _tokens(s)) for s in sentences]

    best_start, best_score, best_end = 0, -1, 0
    start = 0
    while start < len(sentences):
        length, score, end = 0, 0, start
        while end < len(sentences) and length + len(sentences[end]) + 1 <= limit:
            length += len(sentences[end]) + 1
            score += scores[end]
            end += 1
        if end == start:            # một câu dài hơn cả ngân sách
            end = start + 1
            score = scores[start]
        if score > best_score:
            best_start, best_score, best_end = start, score, end
        start += 1

    window = " ".join(sentences[best_start:best_end]).strip()[:limit]
    prefix = "… " if best_start > 0 else ""
    suffix = " …" if best_end < len(sentences) else ""
    return f"{prefix}{window}{suffix}"


def fit_context(chunks, chunk_chars=None, budget=None, question=""):
    """Cắt danh sách đoạn cho vừa ngân sách ký tự, giữ nguyên thứ tự liên quan.

    Mỗi đoạn được thu về `chunk_chars` bằng cách giữ KHÚC LIÊN QUAN NHẤT (xem
    `_best_window`), và dừng nhận thêm khi đã đủ `budget`. Đoạn xếp trên là đoạn
    khớp nhất nên bị cắt sau cùng — cắt từ đuôi danh sách là mất phần ít liên
    quan nhất.
    """
    chunk_chars = chunk_chars or settings.get_int("chunk_char_limit", CHUNK_CHARS)
    budget = budget or settings.get_int("context_char_budget", CONTEXT_CHARS)
    out, used = [], 0
    for c in chunks:
        if used >= budget:
            break
        content = _best_window(c.get("content") or "", question, chunk_chars)
        room = budget - used
        if len(content) > room:
            content = content[:room].rstrip() + "…"
        out.append({**c, "content": content})
        used += len(content)
    return out


def _source_owner_tag(chunk) -> str:
    """Nhãn CHỦ SỞ HỮU đặt trước tên tài liệu trong prompt.

    Tên file kiểu '1. Giấy đề nghị' không nói lên nó là hồ sơ của ai. Thiếu
    nhãn này, model đọc 'tổng số lao động (dự kiến): 02' trong hồ sơ đăng ký
    doanh nghiệp CỦA KHÁCH và trả lời như thể đó là quân số của chính HDS.
    """
    client = (chunk.get("client_name") or "").strip()
    if client:
        return f"(HỒ SƠ KHÁCH HÀNG — {client}) "
    if chunk.get("client_id"):
        return "(HỒ SƠ KHÁCH HÀNG) "
    doc_type = chunk.get("doc_type")
    if doc_type == "ho_so_ns":
        return "(hồ sơ nhân sự của chính HDS) "
    label = company_context.DOC_TYPE_VN.get(doc_type or "")
    return f"({label}) " if label and doc_type != "other" else ""


def build_prompt(question, chunks, temp_chunks=None, method=None,
                 company="", history=None, chunk_chars=None, budget=None):
    # Model KHÔNG tự biết hôm nay là ngày nào. Không nói cho nó thì nó đọc "hợp
    # đồng đến 01/08/2024" mà tưởng còn hiệu lực, dù thực tế đã qua 2 năm. Đây
    # là mốc để nó phán đoán còn hạn / đã hết hạn / quá hạn.
    parts = [f"HÔM NAY LÀ NGÀY {date.today().isoformat()}. Mọi so sánh về thời "
             "hạn, ngày hết hạn, còn hiệu lực hay đã quá hạn đều lấy ngày này "
             "làm hiện tại: ngày kết thúc đã trôi qua nghĩa là ĐÃ HẾT HẠN.\n"]
    if method:
        parts.append(f"QUY TRÌNH PHÂN TÍCH (loại: {method['case_type']}):\n{method['steps']}\n"
                     "Hãy phân tích theo đúng quy trình trên.\n")
    if company:
        # Số liệu thật trong CSDL, không phải trích từ tài liệu → không đánh [Nguồn n]
        parts.append(company + "\n")
    # Ngân sách áp cho CẢ tài liệu trong kho lẫn file tạm đính kèm — nếu không,
    # một file tải lên trong chat vẫn đủ sức thổi prompt lên quá cỡ.
    all_ctx = fit_context(list(chunks) + list(temp_chunks or []), chunk_chars,
                          budget, question=question)
    if all_ctx:
        parts.append("TÀI LIỆU THAM KHẢO ĐÃ ĐƯỢC PHÉP DÙNG:")
        for i, c in enumerate(all_ctx, 1):
            locator = c.get("source_locator") or ""
            if not locator and c.get("page_number"):
                locator = f"trang {c['page_number']}"
            if c.get("section_title"):
                locator = (locator + ", " if locator else "") + c["section_title"]
            label = f" — {locator}" if locator else ""
            owner = _source_owner_tag(c)
            parts.append(f"[Nguồn {i}] {owner}{c.get('title','')}{label}\n{c['content']}\n")
        # Chỉ dẫn phân biệt chủ thể — chỉ chèn khi thật sự có hồ sơ khách trong
        # bộ nguồn, để câu hỏi thuần pháp lý không phải cõng thêm chữ thừa.
        if any(c.get("client_id") or c.get("client_name") for c in all_ctx):
            parts.append(
                "PHÂN BIỆT CHỦ THỂ: nguồn mang nhãn (HỒ SƠ KHÁCH HÀNG — X) là hồ "
                "sơ HDS thực hiện CHO công ty khách X. Mọi số liệu trong đó — số "
                "lao động, vốn điều lệ, thành viên, người đại diện theo pháp luật "
                "— là CỦA CÔNG TY KHÁCH X, tuyệt đối KHÔNG phải của HDS. Khi "
                "người hỏi nói 'công ty tôi' / 'HDS' thì KHÔNG được lấy số liệu "
                "từ các nguồn đó để trả lời; hãy dùng DỮ LIỆU CÔNG TY và các "
                "nguồn hồ sơ nhân sự của chính HDS.\n")
    elif not company:
        # Chỉ báo "không có tài liệu" khi cũng KHÔNG có dữ liệu công ty. Câu hỏi
        # đếm khách/nhân sự cố tình không tra tài liệu — lúc đó dòng này thừa và
        # dễ khiến model do dự dù đã có sẵn con số trong DỮ LIỆU CÔNG TY.
        parts.append("(Không tìm thấy tài liệu liên quan trong kho.)")
    # Lịch sử đặt NGAY TRƯỚC câu hỏi (không phải sau phần dữ liệu công ty) để
    # model nhỏ nhớ được lượt vừa rồi khi đọc câu mới. Câu nối tiếp kiểu "ý tôi
    # là…" chỉ hiểu được khi lượt trước nằm sát ngay đây.
    if history:
        parts.append("DIỄN BIẾN CUỘC TRAO ĐỔI TRƯỚC ĐÓ (đọc để hiểu câu hỏi nối tiếp):")
        for role, content in history:
            who = "Người hỏi" if role == "user" else "Trợ lý"
            parts.append(f"{who}: {(content or '')[:HISTORY_CHARS]}")
        parts.append("")
    parts.append(f"CÂU HỎI HIỆN TẠI: {question}\n"
                 "Nếu đây là câu nói lại/chỉnh lại câu trước, hiểu theo diễn biến ở "
                 "trên và trả lời luôn. MỖI đoạn có khẳng định lấy từ tài liệu phải kết "
                 "thúc bằng đúng một hoặc nhiều ký hiệu [Nguồn n]. Chỉ được dùng số nguồn "
                 "đang có ở trên. KHÔNG suy đoán và không tự điền tên/ngày/số tiền/chức danh. "
                 "Thiếu căn cứ cho một ý nào thì bỏ ý đó và nói rõ còn thiếu thông tin gì, "
                 "nhưng vẫn phải trả lời đầy đủ những phần ĐÃ có căn cứ — không được từ chối "
                 "cả câu khi mới chỉ thiếu một phần. "
                 "Khi dẫn quy định pháp luật, chép ĐÚNG tên văn bản và số hiệu như ghi "
                 "trong nguồn (vd 'khoản 2 Điều 35 Bộ luật Lao động số 45/2019/QH14'); "
                 "nguồn nào có sẵn dòng [Thông tư/Nghị định… — Chương… — Điều…] ở đầu thì "
                 "dùng nguyên dòng đó làm căn cứ, KHÔNG viết chung chung 'theo quy định "
                 "pháp luật' và KHÔNG tự bịa số hiệu. "
                 "Khi câu hỏi liên quan hiệu lực/thời hạn (hợp đồng còn hạn không, ai "
                 "còn hợp đồng, vụ nào quá hạn), TỰ so từng ngày kết thúc trong tài liệu "
                 "với HÔM NAY ở đầu prompt: ngày kết thúc đã qua = ĐÃ HẾT HẠN, ĐỪNG coi "
                 "là còn hiệu lực. Nói rõ hợp đồng nào còn, hợp đồng nào đã hết và hết từ khi nào.")
    if company:
        # Đặt CUỐI CÙNG và viết mạnh: đây là thứ model đọc ngay trước khi viết.
        # Trước đây phần này chỉ là một dòng nhắc nhẹ giữa hàng loạt yêu cầu về
        # trích dẫn, nên model gặp mấy đoạn tài liệu lạc đề là kết luận "không
        # đủ căn cứ" trong khi câu trả lời nằm sẵn ở DỮ LIỆU CÔNG TY ngay trên.
        parts.append(
            "QUAN TRỌNG NHẤT: phần DỮ LIỆU CÔNG TY ở đầu prompt là số liệu THẬT lấy "
            "trực tiếp từ hệ thống HDS — nó là CĂN CỨ CÓ GIÁ TRỊ CAO NHẤT, cao hơn "
            "tài liệu tra cứu. Câu hỏi nào trả lời được từ phần đó thì PHẢI trả lời, "
            "dùng thẳng số liệu và tên trong đó, KHÔNG cần ghi [Nguồn], và TUYỆT ĐỐI "
            "không được nói là thiếu căn cứ. Riêng danh mục hồ sơ nhân sự: một người "
            "thường có nhiều hồ sơ (hợp đồng, CV, đơn từ, báo cáo) — hãy GỘP THEO TÊN "
            "NGƯỜI rồi mới đếm, đừng đếm số hồ sơ. Nêu rõ ngày/hạn khi trả lời về "
            "tiến độ vụ việc.")
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


def get_temp_context(conversation_id, question, top_k=5, query_vector=None):
    """Lấy các đoạn liên quan nhất từ file tạm của cuộc chat này."""
    qvec = query_vector if query_vector is not None else embed(question)
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


def resolve_model(model_choice, question, configured_model=None, quality_required=False):
    """Từ lựa chọn của người dùng → tên model cụ thể (hoặc None = mặc định).
      ''/None      → None (dùng model mặc định của máy chủ)
      'auto'       → models.auto_pick_model (câu đơn giản chọn model nhanh)
      '<tên model>'→ đúng model đó"""
    choice = (model_choice or "").strip()
    if not choice:
        return None
    if choice.lower() == "auto":
        from app.models import auto_pick_model
        return auto_pick_model(question, configured_model=configured_model,
                               quality_required=quality_required)
    return choice


_CITATION_RE = re.compile(r"\[\s*Nguồn\s+(\d+)\s*\]", re.IGNORECASE)

# Tỉ lệ chữ của một đoạn phải tìm thấy trong đoạn tài liệu thì mới được coi là
# có căn cứ. 0.6 là mức đòi hỏi đoạn văn phải thực sự lấy từ nguồn, chứ không
# chỉ tình cờ trùng vài từ phổ thông.
AUTOCITE_MIN_COVERAGE = 0.6

# Từ quá phổ thông thì trùng nhau cũng không chứng minh được gì.
_STOP_TOKENS = {
    "va", "cua", "cho", "trong", "voi", "duoc", "cac", "nhung", "mot", "la",
    "co", "khong", "den", "tu", "theo", "tai", "ve", "nay", "do", "se", "da",
    "thi", "ma", "nhu", "hoac", "neu", "khi", "boi", "tren", "duoi", "ben",
}


def _content_tokens(text: str) -> set[str]:
    """Chữ mang nghĩa của một câu — bỏ hư từ để phép so khớp có sức nặng."""
    return {t for t in _tokens(text) if t not in _STOP_TOKENS}


def autocite(text, chunks, min_coverage=AUTOCITE_MIN_COVERAGE):
    """Tự gắn [Nguồn n] cho những đoạn CHỨNG MINH ĐƯỢC là lấy từ tài liệu.

    Model nhỏ hay quên ký hiệu trích dẫn dù nội dung hoàn toàn đúng và lấy từ
    nguồn. Chặn sạch câu trả lời vì lỗi hình thức đó là phí phạm — người dùng
    mất luôn phần nội dung đúng.

    Đây KHÔNG phải bịa nguồn: chỉ gắn khi phần lớn chữ mang nghĩa của đoạn văn
    thực sự có mặt trong đúng đoạn tài liệu đó, tức là trích dẫn được KIẾM ĐƯỢC
    bằng đối chiếu chứ không phải gán bừa. Đoạn không đạt ngưỡng vẫn để nguyên
    cho bước kiểm tra phía sau xử lý.
    """
    if not chunks or not (text or "").strip():
        return text, 0
    chunk_tokens = [_content_tokens(c.get("content") or "") for c in chunks]

    blocks = re.split(r"(\n\s*\n)", text)
    attached = 0
    for index in range(0, len(blocks), 2):
        block = blocks[index]
        if _CITATION_RE.search(block):
            continue
        body_lines = [line for line in block.splitlines()
                      if not line.lstrip().startswith(("#", ">"))]
        body = re.sub(r"[`*_>#-]", "", " ".join(body_lines)).strip()
        if len(body) < 35 or "[CẦN BỔ SUNG" in body.upper():
            continue
        btokens = _content_tokens(body)
        if len(btokens) < 4:
            continue
        best_n, best_cov = 0, 0.0
        for n, ctokens in enumerate(chunk_tokens, 1):
            coverage = len(btokens & ctokens) / len(btokens)
            if coverage > best_cov:
                best_n, best_cov = n, coverage
        if best_n and best_cov >= min_coverage:
            blocks[index] = block.rstrip() + f" [Nguồn {best_n}]"
            attached += 1
    return "".join(blocks), attached


def validate_grounding(text, chunks, answer_mode="grounded", strict=True):
    """Kiểm tra citation có trỏ tới nguồn thật; fail-closed khi hoàn toàn mất nguồn.

    Đây không khẳng định model đã suy luận đúng mọi chữ, nhưng chặn hai lỗi nguy
    hiểm nhất: tự tạo `[Nguồn 9]` không tồn tại và trả lời tài liệu không có bất
    kỳ căn cứ nào để người dùng kiểm tra.
    """
    text = (text or "").strip()
    if not chunks or answer_mode not in {"grounded", "mixed"}:
        return text, "verified" if answer_mode == "structured" else "not_applicable"

    # BƯỚC 1: cứu những đoạn đúng nội dung nhưng thiếu ký hiệu trích dẫn. Làm
    # trước khi kiểm tra để lỗi hình thức của model không xoá mất nội dung đúng.
    text, _ = autocite(text, chunks)

    valid_max = len(chunks)
    seen_valid = []

    def replace(match):
        n = int(match.group(1))
        if 1 <= n <= valid_max:
            seen_valid.append(n)
            return f"[Nguồn {n}]"
        return ""

    cleaned = _CITATION_RE.sub(replace, text)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned).strip()
    if seen_valid:
        unsupported = []
        blocks = re.split(r"(\n\s*\n)", cleaned)
        for index in range(0, len(blocks), 2):
            block = blocks[index]
            body_lines = [line for line in block.splitlines()
                          if not line.lstrip().startswith(("#", ">"))]
            body = re.sub(r"[`*_>#-]", "", " ".join(body_lines)).strip()
            # Tiêu đề, câu nối rất ngắn và placeholder không phải một khẳng
            # định cần nguồn. Các khối nội dung đáng kể thì bắt buộc phải có.
            if (len(body) >= 35 and "[CẦN BỔ SUNG" not in body.upper()
                    and not _CITATION_RE.search(block)):
                unsupported.append(index)
        if unsupported and strict and answer_mode == "grounded":
            # BỎ HẲN khối không căn cứ thay vì chèn "[Đã ẩn đoạn…]" vào từng
            # chỗ. Ba placeholder chen giữa nội dung đọc như tài liệu bị kiểm
            # duyệt nham nhở — người dùng mất niềm tin vào cả phần ĐÚNG còn
            # lại. Một ghi chú gọn ở cuối nói đủ điều cần nói: có N đoạn đã
            # lược, và vì sao.
            for index in unsupported:
                heading = "\n".join(
                    line for line in blocks[index].splitlines()
                    if line.lstrip().startswith("#")
                )
                blocks[index] = heading.strip()
                # Nuốt luôn dấu ngắt đoạn kề sau để không còn khoảng trắng kép.
                if index + 1 < len(blocks):
                    blocks[index + 1] = "" if not heading else "\n\n"
            note = (f"\n\n---\n*Đã lược {len(unsupported)} đoạn chưa đối chiếu "
                    "được với nguồn — mở **Nguồn trích dẫn** để tự kiểm tra, "
                    "hoặc hỏi cụ thể hơn để mình tìm thêm căn cứ.*")
            cleaned_out = re.sub(r"\n{3,}", "\n\n", "".join(blocks)).strip()
            return cleaned_out + note, "partial"
        return cleaned, "partial" if unsupported else "verified"
    if not strict or answer_mode == "mixed":
        return cleaned, "uncited"
    # Tới đây nghĩa là autocite cũng không đối chiếu được đoạn nào với nguồn:
    # nội dung sinh ra KHÔNG nằm trong tài liệu đã tìm được. Với công cụ pháp lý
    # thì đó là câu phải giữ lại, không phải câu để hiển thị.
    return (
        "Mình tìm được tài liệu liên quan (xem phần **Nguồn trích dẫn** bên dưới) "
        "nhưng chưa đoạn nào nói thẳng vào câu bạn hỏi, nên mình không đưa ra câu "
        "trả lời để tránh suy đoán.\n\n"
        "Bạn thử một trong ba cách:\n"
        "- Hỏi cụ thể hơn (nêu tên khách, tên vụ việc, số hợp đồng hoặc mốc thời gian).\n"
        "- Mở **Nguồn trích dẫn** bên dưới, chọn đúng tài liệu cần dùng rồi hỏi lại.\n"
        "- Nếu hồ sơ chưa có trong kho, tải tệp lên rồi hỏi lại."
    ), "uncited_blocked"


def _insufficient_answer(source_selected=False):
    scope = "trong bộ nguồn bạn đã chọn" if source_selected else "trong kho dữ liệu được phép truy cập"
    return (f"Mình chưa tìm thấy căn cứ đủ liên quan {scope} để trả lời chính xác. "
            "Mình sẽ không đoán. Bạn có thể chọn thêm tài liệu, nêu tên khách/vụ việc, "
            "hoặc tải đúng hồ sơ lên rồi hỏi lại.")


SLOW_MS = 20000   # trên mức này thì ghi log để soi lại, dưới thì im lặng


def _log_slow(question, t):
    """In một dòng chẩn đoán khi câu trả lời chậm bất thường.

    Xem bằng:  sudo journalctl -u hds-ai-backend -n 200 | grep CHAM
    Đọc dòng này là biết ngay chậm ở đâu: `doc` lớn nghĩa là prompt quá dài,
    `nap` lớn nghĩa là model bị đẩy ra khỏi bộ nhớ và phải nạp lại từ ổ cứng,
    `viet` lớn nghĩa là model quá nặng so với máy.
    """
    measured_total = t.get("tong_ms") or (
        (t.get("chuan_bi_ms") or 0) + (t.get("ai_ms") or 0))
    if measured_total < SLOW_MS:
        return
    print(f"[CHAM] tong={measured_total}ms ai={t.get('ai_ms')}ms | model={t.get('model')} "
          f"| prompt={t.get('prompt_tokens')} token, doc={t.get('prefill_ms')}ms "
          f"| sinh={t.get('gen_tokens')} token, viet={t.get('gen_ms')}ms "
          f"| nap={t.get('load_ms')}ms | embed={t.get('embed_ms')}ms "
          f"(nap={t.get('embed_load_ms')}ms) | vector={t.get('vector_db_ms')}ms "
          f"| doan={t.get('so_doan')} | hoi={(question or '')[:60]!r}", flush=True)


def prepare(question, channel, client_id=None, conversation_id=None,
            use_temp=False, use_method=False, dept_ids=None, is_banqt=False,
            can_finance=False, role=None, model=None, source_document_ids=None):
    """Dựng đủ nguyên liệu cho một lượt trả lời, DỪNG NGAY TRƯỚC khi gọi model.

    Tách riêng vì có hai cách sinh câu trả lời — trả một cục (answer) và trả
    theo dòng (answer_stream) — nhưng toàn bộ phần trước đó phải giống hệt
    nhau. Nhân đôi đoạn này là nhân đôi cả logic phân quyền, sớm muộn hai bản
    sẽ lệch và một bên hở dữ liệu.

    Trả về dict: prompt, system, model, temperature, chunks, method, timings.
    """
    if channel not in CHANNEL_LEVEL:
        raise ValueError(f"Kênh không hợp lệ: {channel}")
    if channel == "portal" and client_id is None:
        raise ValueError("Kênh portal bắt buộc có client_id")

    prepare_started = time.time()

    # Đọc cài đặt MỘT LẦN cho cả lượt hỏi (prompt, nhiệt độ, top_k) thay vì mở
    # ba kết nối CSDL riêng. Vẫn lấy tươi mỗi câu hỏi nên admin sửa là ăn ngay.
    cfg = settings.get_all()

    def _num(key, fallback, cast):
        try:
            return cast(float(cfg.get(key)))
        except (TypeError, ValueError):
            return fallback

    # Đo từng chặng để biết chậm ở đâu — không đo thì chỉ đoán mò.
    timings: dict = {"cai_dat_ms": int((time.time() - prepare_started) * 1000)}
    clock = [time.time()]

    def tick(key):
        now = time.time()
        timings[key] = int((now - clock[0]) * 1000)
        clock[0] = now

    # Lịch sử + state phải có TRƯỚC router và retrieval. Đây là thứ tự quan
    # trọng nhất để câu nối tiếp không đi tìm bằng một cụm từ mơ hồ.
    history = get_history(conversation_id, channel, client_id)
    state = get_conversation_state(conversation_id, channel, client_id)
    search_question = resolve_search_question(question, history, state)
    timings["search_question"] = search_question[:300]
    tick("lich_su_ms")

    smalltalk = _smalltalk_answer(question)
    direct = None
    if smalltalk:
        direct = {"answer": smalltalk, "answer_mode": "chat",
                  "grounding_status": "not_applicable", "evidence": [], "state": {}}
    else:
        direct = company_context.structured_answer(
            question, channel, client_id=client_id, dept_ids=dept_ids,
            is_banqt=is_banqt, can_finance=can_finance,
            history=history, state=state)
    tick("du_lieu_cau_truc_ms")

    state_update = dict(state or {})
    state_update.update((direct or {}).get("state") or {})
    state_update["last_question"] = question[:1000]

    if direct:
        timings.update({"bo_qua_doan_yeu": 0, "bo_tra_tai_lieu": True,
                        "tim_kiem_ms": 0, "so_doan": 0})
        timings["chuan_bi_ms"] = int((time.time() - prepare_started) * 1000)
        return {
            "prompt": "", "system": "", "model": None, "temperature": 0,
            "chunks": [], "method": None, "timings": timings,
            "direct_answer": direct["answer"],
            "answer_mode": direct["answer_mode"],
            "grounding_status": direct["grounding_status"],
            "evidence": direct.get("evidence") or [], "state": state_update,
            "strict_grounding": True,
        }

    # Cổng khách: giới hạn loại tài liệu theo gói dịch vụ (Free/Plus/Pro).
    doc_types = tier_doc_types(role) if (channel == "portal" and role) else None
    # Chỉ tạo embedding MỘT LẦN rồi tái dùng cho kho chính, file tạm và phương
    # pháp phân tích. Trước đây bật cả ba tính năng khiến cùng câu bị embed 3 lần.
    embed_stats: dict = {}
    embed_started = time.time()
    query_vector = embed(search_question, stats=embed_stats)
    timings["embed_ms"] = int((time.time() - embed_started) * 1000)
    timings.update(embed_stats)

    vector_started = time.time()
    chunks = retrieve(
        search_question, channel, client_id, dept_ids=dept_ids, is_banqt=is_banqt,
        top_k=_num("retrieval_top_k", TOP_K, int), can_finance=can_finance,
        doc_types=doc_types, document_ids=source_document_ids,
        candidate_k=_num("retrieval_candidate_k", RETRIEVAL_CANDIDATES, int),
        max_per_document=_num("retrieval_max_chunks_per_doc", MAX_CHUNKS_PER_DOC, int),
        query_vector=query_vector,
    )
    min_score = _num("min_relevance", MIN_SCORE, float)
    kept = [c for c in chunks if c["score"] >= min_score]
    timings["bo_qua_doan_yeu"] = len(chunks) - len(kept)

    # Câu hỏi về nhân sự HDS: BẢO ĐẢM hồ sơ nhân sự có mặt trong nguồn.
    #
    # Điều lệ công ty đầy chữ "thành viên", "người quản lý", "danh sách những
    # người có liên quan" nên xét ngữ nghĩa nó khớp câu hỏi nhân sự rất cao, đủ
    # để chiếm hết top-k và đẩy hợp đồng lao động ra ngoài — người dùng thấy bot
    # dẫn Điều lệ cho câu hỏi "ai đang làm ở đây".
    #
    # Không thu hẹp cứng về ho_so_ns: cụm "hợp đồng lao động" cũng nằm trong từ
    # khoá nhân sự, mà câu hỏi PHÁP LÝ về HĐLĐ thì cần Bộ luật Lao động. Vì vậy
    # chỉ CHÈN THÊM, không loại bỏ thứ gì.
    if channel == "internal" and company_context.is_staff_query(question):
        hr_extra = retrieve(
            search_question, channel, client_id, dept_ids=dept_ids,
            is_banqt=is_banqt, top_k=3, can_finance=can_finance,
            doc_types=["ho_so_ns"], document_ids=source_document_ids,
            query_vector=query_vector,
        )
        seen_ids = {c["chunk_id"] for c in kept}
        # Đặt LÊN TRƯỚC để không bị ngân sách ký tự cắt mất ở cuối danh sách.
        kept = [c for c in hr_extra if c["chunk_id"] not in seen_ids] + kept
        timings["ho_so_ns_them"] = len(kept) - len(seen_ids)
    chunks = fit_context(kept,
                         _num("chunk_char_limit", CHUNK_CHARS, int),
                         _num("context_char_budget", CONTEXT_CHARS, int),
                         question=search_question)
    timings["vector_db_ms"] = int((time.time() - vector_started) * 1000)
    timings["tim_kiem_ms"] = timings["embed_ms"] + timings["vector_db_ms"]
    clock[0] = time.time()

    temp_chunks = (get_temp_context(conversation_id, search_question,
                                    query_vector=query_vector)
                   if (use_temp and conversation_id) else None)
    method = find_method(search_question, query_vector=query_vector) if use_method else None

    # Nguồn vận hành dùng song song với tài liệu, nhưng các câu đếm xác định đã
    # được structured_answer chặn ở trên và không còn đi qua LLM.
    company = company_context.build(question, channel, client_id=client_id,
                                    dept_ids=dept_ids, is_banqt=is_banqt,
                                    can_finance=can_finance, history=history)
    tick("du_lieu_cong_ty_ms")

    if not chunks and not temp_chunks and not company:
        direct_text = _insufficient_answer(source_document_ids is not None)
        timings["so_doan"] = 0
        timings["chuan_bi_ms"] = int((time.time() - prepare_started) * 1000)
        return {
            "prompt": "", "system": "", "model": None, "temperature": 0,
            "chunks": [], "method": method, "timings": timings,
            "direct_answer": direct_text,
            "answer_mode": "insufficient_evidence",
            "grounding_status": "insufficient", "evidence": [],
            "state": state_update, "strict_grounding": True,
        }

    # Truyền thẳng ngân sách đã đọc từ `cfg` — để build_prompt tự đọc lại thì
    # mỗi câu hỏi phải mở thêm hai kết nối CSDL cho hai con số.
    prompt = build_prompt(question, chunks, temp_chunks, method,
                          company=company, history=history,
                          chunk_chars=_num("chunk_char_limit", CHUNK_CHARS, int),
                          budget=_num("context_char_budget", CONTEXT_CHARS, int))
    timings["so_doan"] = len(chunks)
    answer_mode = "mixed" if company and chunks else ("grounded" if chunks else "operational")
    strict = str(cfg.get("strict_grounding", "true")).lower() not in {"0", "false", "no"}
    model_started = time.time()
    configured_model = (cfg.get("llm_model") or "").strip() or None
    chosen_model = resolve_model(model, question, configured_model=configured_model,
                                 quality_required=True)
    timings["chon_model_ms"] = int((time.time() - model_started) * 1000)
    timings["chuan_bi_ms"] = int((time.time() - prepare_started) * 1000)
    return {
        "prompt": prompt,
        "system": cfg.get(f"prompt_{channel}") or settings.DEFAULTS.get(f"prompt_{channel}", ""),
        "model": chosen_model,
        "temperature": _num("llm_temperature", 0.2, float),
        "chunks": chunks,
        "method": method,
        "timings": timings,
        "direct_answer": None,
        "answer_mode": answer_mode,
        "grounding_status": "pending",
        "evidence": format_sources(chunks),
        "state": state_update,
        "strict_grounding": strict,
    }


def format_sources(chunks):
    """Nguồn kiểm chứng đủ để mở đúng đoạn, không chỉ là tên file chung chung."""
    out = []
    for i, c in enumerate(chunks, 1):
        quote = re.sub(r"\s+", " ", (c.get("content") or "")).strip()
        if len(quote) > 600:
            quote = quote[:600].rstrip() + "…"
        score = round(float(c.get("score") or 0), 3)
        # Tên khách đứng ngay trong tiêu đề nguồn: người đọc panel trích dẫn
        # phải thấy được '1. Giấy đề nghị' là hồ sơ của khách nào mà không cần
        # mở file gốc.
        title = c.get("title") or "(không tiêu đề)"
        if (c.get("client_name") or "").strip():
            title = f"[KH: {c['client_name'].strip()}] {title}"
        out.append({
            "n": i, "kind": "document", "chunk_id": c.get("chunk_id"),
            "title": title,
            "doc_type": c.get("doc_type"),
            "client_name": c.get("client_name"),
            "document_id": c.get("document_id"),
            "drive_file_id": c.get("drive_file_id"),
            "source_version": c.get("source_version"),
            "page_number": c.get("page_number"),
            "section_title": c.get("section_title"),
            "source_locator": c.get("source_locator"),
            "quote": quote, "snippet": quote,
            "score": score, "relevance_score": score,
            "semantic_score": round(float(c.get("semantic_score") or 0), 3),
            "lexical_score": round(float(c.get("lexical_score") or 0), 3),
        })
    return out


def save_turn(question, text, chunks, conversation_id, channel, client_id=None,
              user_id=None, model_used=None, latency=0, method=None,
              evidence=None, answer_mode=None, grounding_status=None, state=None):
    """Ghi cặp hỏi-đáp vào CSDL, trả về mã tin nhắn của câu trả lời.

    Ghi SAU khi đã có câu trả lời đầy đủ — kể cả ở luồng chảy dần. Nhờ vậy lịch
    sử hội thoại không bao giờ chứa câu trả lời dở dang, và mã tin nhắn chỉ được
    cấp cho nội dung đã hoàn tất (nút báo cáo/ghi chú luôn trỏ vào bản đầy đủ).
    """
    if not conversation_id:
        return None
    level = CHANNEL_LEVEL[channel]
    with db.session(role=level, client_id=client_id) as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO messages (conversation_id,role,content) VALUES (%s,'user',%s)",
                        (conversation_id, question))
            cur.execute("""INSERT INTO messages
                           (conversation_id,role,content,sources,model_used,latency_ms,
                            answer_mode,grounding_status,evidence)
                           VALUES (%s,'assistant',%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                        (conversation_id, text,
                         json.dumps([c["chunk_id"] for c in chunks if c.get("chunk_id")]),
                         model_used, latency, answer_mode, grounding_status,
                         json.dumps(evidence or [], ensure_ascii=False)))
            msg_id = cur.fetchone()[0]
            if state is not None:
                cur.execute("UPDATE conversations SET context_state=%s WHERE id=%s",
                            (json.dumps(state, ensure_ascii=False), conversation_id))
        db.audit(conn, user_id, "chat_query", "conversation", conversation_id,
                 {"channel": channel, "n_sources": len(chunks),
                  "used_method": bool(method), "answer_mode": answer_mode,
                  "grounding_status": grounding_status})
    return msg_id


def answer(question, channel, user_id=None, client_id=None, conversation_id=None,
           prefer="local", use_temp=False, use_method=False,
           dept_ids=None, is_banqt=False, can_finance=False, role=None, model=None,
           source_document_ids=None):
    """Trả lời MỘT CỤC — dùng cho kênh website, API khách và các lời gọi nội bộ."""
    request_started = time.time()
    p = prepare(question, channel, client_id=client_id, conversation_id=conversation_id,
                use_temp=use_temp, use_method=use_method, dept_ids=dept_ids,
                is_banqt=is_banqt, can_finance=can_finance, role=role, model=model,
                source_document_ids=source_document_ids)
    timings, chunks, method = p["timings"], p["chunks"], p["method"]

    if p.get("direct_answer") is not None:
        text, latency = p["direct_answer"], 0
        timings["ai_ms"] = 0
        grounding_status = p["grounding_status"]
    else:
        llm_stats: dict = {}
        text, latency = llm(p["prompt"], system=p["system"], prefer=prefer,
                            temperature=p["temperature"], model=p["model"], stats=llm_stats)
        text, grounding_status = validate_grounding(
            text, chunks, p["answer_mode"], p["strict_grounding"])
        timings["ai_ms"] = latency
        timings.update({k: v for k, v in llm_stats.items()
                        if k in ("prompt_tokens", "gen_tokens", "load_ms",
                                 "prefill_ms", "gen_ms", "num_ctx", "model")})

    evidence = p.get("evidence") or format_sources(chunks)

    msg_id = save_turn(question, text, chunks, conversation_id, channel,
                       client_id=client_id, user_id=user_id,
                       model_used=p["model"] or ("none" if latency == 0 else prefer),
                       latency=latency, method=method, evidence=evidence,
                       answer_mode=p["answer_mode"], grounding_status=grounding_status,
                       state=p.get("state"))
    timings["tong_ms"] = int((time.time() - request_started) * 1000)
    _log_slow(question, timings)

    return {"answer": text, "sources": evidence,
            "used_method": method["case_type"] if method else None,
            "latency_ms": latency, "message_id": msg_id, "timings": timings,
            "answer_mode": p["answer_mode"], "grounding_status": grounding_status,
            "end_to_end_ms": timings["tong_ms"]}


def answer_stream(question, channel, user_id=None, client_id=None, conversation_id=None,
                  use_temp=False, use_method=False, dept_ids=None, is_banqt=False,
                  can_finance=False, role=None, model=None, source_document_ids=None):
    """Trả lời THEO DÒNG — generator sinh ra các sự kiện dict:

        {"type": "meta",  "sources": [...]}        gửi ngay khi biết nguồn
        {"type": "delta", "text": "…"}             từng mẩu chữ
        {"type": "done",  "message_id": .., "timings": {...}}

    Người gọi (api.py) chỉ việc đóng gói thành SSE.
    """
    from app.models import llm_stream
    request_started = time.time()

    p = prepare(question, channel, client_id=client_id, conversation_id=conversation_id,
                use_temp=use_temp, use_method=use_method, dept_ids=dept_ids,
                is_banqt=is_banqt, can_finance=can_finance, role=role, model=model,
                source_document_ids=source_document_ids)
    timings, chunks, method = p["timings"], p["chunks"], p["method"]

    # Nguồn trích dẫn đã biết trước khi model viết chữ nào — gửi ngay để giao
    # diện có cái hiển thị, và để trình duyệt nhận byte đầu tiên sớm nhất.
    evidence = p.get("evidence") or format_sources(chunks)
    yield {"type": "meta", "sources": evidence,
           "used_method": method["case_type"] if method else None,
           "answer_mode": p["answer_mode"],
           "grounding_status": p["grounding_status"]}

    if p.get("direct_answer") is not None:
        text, latency = p["direct_answer"], 0
        timings["ai_ms"] = 0
        yield {"type": "delta", "text": text}
        msg_id = save_turn(
            question, text, chunks, conversation_id, channel,
            client_id=client_id, user_id=user_id, model_used="none", latency=0,
            method=method, evidence=evidence, answer_mode=p["answer_mode"],
            grounding_status=p["grounding_status"], state=p.get("state"))
        timings["tong_ms"] = int((time.time() - request_started) * 1000)
        _log_slow(question, timings)
        yield {"type": "done", "message_id": msg_id, "latency_ms": 0,
               "timings": timings, "answer_mode": p["answer_mode"],
               "grounding_status": p["grounding_status"],
               "end_to_end_ms": timings["tong_ms"]}
        return

    llm_stats: dict = {}
    t0 = time.time()
    parts = []
    for piece in llm_stream(p["prompt"], system=p["system"],
                            temperature=p["temperature"], model=p["model"],
                            stats=llm_stats):
        parts.append(piece)
        yield {"type": "delta", "text": piece}

    raw_text = "".join(parts).strip()
    text, grounding_status = validate_grounding(
        raw_text, chunks, p["answer_mode"], p["strict_grounding"])
    if text != raw_text:
        # Giao diện thay toàn bộ nội dung đã stream khi bộ kiểm chứng phải bỏ
        # citation giả hoặc chặn một câu không có citation.
        yield {"type": "replace", "text": text,
               "grounding_status": grounding_status}
    latency = int((time.time() - t0) * 1000)
    timings["ai_ms"] = latency
    timings.update({k: v for k, v in llm_stats.items()
                    if k in ("prompt_tokens", "gen_tokens", "load_ms",
                             "prefill_ms", "gen_ms", "num_ctx", "model")})

    msg_id = save_turn(question, text, chunks, conversation_id, channel,
                       client_id=client_id, user_id=user_id,
                       model_used=p["model"] or "local", latency=latency, method=method,
                       evidence=evidence, answer_mode=p["answer_mode"],
                       grounding_status=grounding_status, state=p.get("state"))
    timings["tong_ms"] = int((time.time() - request_started) * 1000)
    _log_slow(question, timings)

    yield {"type": "done", "message_id": msg_id, "latency_ms": latency,
           "timings": timings, "answer_mode": p["answer_mode"],
           "grounding_status": grounding_status,
           "end_to_end_ms": timings["tong_ms"]}


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
