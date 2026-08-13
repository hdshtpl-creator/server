"""
company_context.py — Cho bot đọc DỮ LIỆU VẬN HÀNH của công ty, không chỉ tài liệu.

Trước đây bộ hỏi đáp chỉ tìm vector trong các đoạn văn bản tài liệu, nên câu
hỏi kiểu "khách SUNGROUP đang có mấy vụ, hạn gần nhất ngày nào" không trả lời
được: dữ liệu đó nằm ở bảng clients/matters/client_profiles, không nằm trong
bất kỳ tài liệu nào để mà tìm.

Module này nhận ra câu hỏi đang nói về khách/vụ việc nào, rút dữ liệu có cấu
trúc bằng SQL, rồi trả về một khối văn bản để ghép vào prompt.

PHÂN QUYỀN — đọc kỹ trước khi sửa:
  Bảng clients/matters/client_profiles KHÔNG có Row-Level Security (chỉ chunks
  và documents có). Vì vậy MỌI truy vấn ở đây phải TỰ lọc theo phòng ban của
  người hỏi, giống cách /clients làm. Không được dựa vào RLS ở đây.

  Kênh portal (khách tự hỏi) chỉ thấy đúng khách đang đăng nhập, và KHÔNG BAO
  GIỜ thấy ghi chú nội bộ trong hồ sơ 360° (lịch sử, vấn đề, cảnh báo thời
  hiệu, gợi ý chiến lược) — đó là nhận định nội bộ của HDS, không phải thông
  tin để đưa cho khách.
"""
import re
import unicodedata
from datetime import date

from app import db

MAX_CLIENTS = 3           # câu hỏi nhắc nhiều khách thì chỉ lấy mấy khách đầu
MAX_MATTERS = 12          # số vụ việc liệt kê tối đa cho mỗi khách
MAX_NOTE_CHARS = 700      # cắt ghi chú dài để prompt không phình
MAX_SUMMARY_CHARS = 3000  # ngân sách ký tự cho file tổng hợp thông tin khách
MAX_FINANCE_CHARS = 1500  # ngân sách ký tự cho tài liệu công nợ

# Mã vụ việc theo quy ước [M-2026-001]
RE_MATTER_CODE = re.compile(r"\b([A-Z]{1,3}-\d{4}-\d{1,4})\b", re.I)

# Từ chung trong tên doanh nghiệp — bỏ đi thì còn lại phần nhận dạng được.
# Nếu không bỏ, câu hỏi nào có chữ "công ty" cũng khớp mọi khách.
ENTITY_STOPWORDS = {
    "cong", "ty", "cp", "co", "phan", "tnhh", "mtv", "tap", "doan", "chi",
    "nhanh", "doanh", "nghiep", "trach", "nhiem", "huu", "han", "hop", "danh",
    "viet", "nam", "quoc", "te", "dau", "tu", "thuong", "mai", "dich", "vu",
    "san", "xuat", "xay", "dung", "phat", "trien", "group", "holdings",
}


def _fold(s: str) -> str:
    """Bỏ dấu tiếng Việt, hạ chữ thường, gộp khoảng trắng."""
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = s.replace("đ", "d").replace("Đ", "d")
    return re.sub(r"[\s_]+", " ", s).strip().lower()


def _name_tokens(name: str) -> set[str]:
    """Phần riêng của tên khách: bỏ các từ chung về loại hình doanh nghiệp.

    'Công ty CP Vinapharma' → {'vinapharma'}; 'Công ty Thành Đạt' → {'thanh','dat'}.
    KHÔNG lọc theo độ dài ở đây — 'dat' ngắn nhưng là một nửa danh tính của
    khách, bỏ nó đi thì điều kiện khớp bên dưới bị lỏng ra.
    """
    return {t for t in _fold(name).split()
            if len(t) >= 2 and t not in ENTITY_STOPWORDS}


def _name_mentioned(name: str, q_folded: str, q_tokens: set[str]) -> bool:
    """Tên khách có thật sự được nhắc trong câu hỏi hay không.

    Nhận nhầm khách còn tệ hơn không nhận ra: bot sẽ trả lời chắc nịch bằng số
    liệu của người khác. Nên luật ở đây cố tình chặt:

      · nhiều từ riêng  → phải có ĐỦ tất cả. 'Thành Đạt' cần cả 'thanh' và
        'dat', nhờ vậy câu 'thủ tục thành lập doanh nghiệp' không khớp.
      · một từ riêng    → từ đó phải dài từ 4 ký tự. Tên một chữ ngắn kiểu
        'Công ty Hoa' quá dễ trùng từ thông thường, bỏ qua cho an toàn.
      · không từ nào riêng ('Công ty Đầu tư Việt Nam') → phải viết đủ tên.

    Trường hợp bị bỏ sót thì gọi khách bằng mã là chắc chắn nhất.
    """
    toks = _name_tokens(name)
    if len(toks) == 1:
        only = next(iter(toks))
        return len(only) >= 4 and only in q_tokens
    if toks:
        return toks <= q_tokens
    folded = _fold(name)
    return len(folded) >= 8 and folded in q_folded


def _cut(text, limit=MAX_NOTE_CHARS):
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def _deadline_note(d):
    """Diễn giải hạn thành ngôn ngữ có mức độ gấp — mầm của engine cảnh báo."""
    if not d:
        return "chưa đặt hạn"
    left = (d - date.today()).days
    if left < 0:
        return f"hạn {d}, ĐÃ QUÁ HẠN {abs(left)} ngày"
    if left == 0:
        return f"hạn {d}, HẾT HẠN HÔM NAY"
    if left <= 7:
        return f"hạn {d}, còn {left} ngày — GẤP"
    if left <= 30:
        return f"hạn {d}, còn {left} ngày"
    return f"hạn {d}"


STATUS_VN = {
    "tiep_nhan": "mới tiếp nhận", "dang_xu_ly": "đang xử lý",
    "tam_dung": "tạm dừng", "hoan_thanh": "hoàn thành",
}

# Nhãn cảnh báo, khai một chỗ để api.py và prompt dùng chung, không lệch chữ.
ALERT_KIND_VN = {
    "qua_han": "ĐÃ QUÁ HẠN",
    "den_han_gap": "sắp hết hạn trong 7 ngày",
    "den_han_gan": "đến hạn trong 30 ngày",
    "thieu_han": "đang xử lý nhưng chưa đặt hạn",
    "treo_lau": "treo quá 60 ngày không có tài liệu mới",
}

# Câu hỏi chứa các từ này là đang hỏi về tiến độ/hạn chót nói chung, kể cả khi
# không nhắc tên khách nào — lúc đó phải đưa cảnh báo toàn phạm vi người hỏi.
ALERT_WORDS = {
    "qua han", "quan han", "sap den han", "den han", "han chot", "deadline",
    "canh bao", "tre han", "cham tien do", "thoi hieu", "sap het han",
    "vu nao gap", "viec gap", "treo lau", "ton dong", "sap toi han",
}

DOC_TYPE_VN = {
    "law": "văn bản luật", "ban_an": "bản án", "an_le": "án lệ",
    "mau_hd": "mẫu hợp đồng", "nhan_hieu": "data nhãn hiệu",
    "thu_mau": "thư mẫu", "quy_trinh": "quy trình", "ho_so_ns": "hồ sơ nhân sự",
    "ho_so_kh": "hồ sơ khách hàng", "advisory": "thư tư vấn",
    "filing": "hồ sơ nộp", "contract": "hợp đồng",
    "cong_no": "công nợ - tài chính", "other": "khác",
}


# ---------------------------------------------------------------
# Nhận diện khách / vụ việc được nhắc trong câu hỏi
# ---------------------------------------------------------------
def _visible_clients(cur, dept_ids, is_banqt):
    """Khách mà người hỏi được phép thấy. Lọc theo phòng vì clients không có RLS."""
    if is_banqt:
        cur.execute("SELECT id, name, code FROM clients")
    else:
        cur.execute("SELECT id, name, code FROM clients WHERE department_id = ANY(%s)",
                    (dept_ids or [-1],))
    return cur.fetchall()


def detect_clients(cur, question, dept_ids, is_banqt):
    """Khách được nhắc trong câu hỏi — khớp theo mã, hoặc theo từ đặc trưng của tên."""
    q = _fold(question)
    q_tokens = set(re.findall(r"[a-z0-9]+", q))
    hits = []
    for cid, name, code in _visible_clients(cur, dept_ids, is_banqt):
        folded = _fold(code) if code else ""
        if folded and len(folded) >= 3 and re.search(rf"\b{re.escape(folded)}\b", q):
            hits.append((cid, name, code))
            continue
        if _name_mentioned(name, q, q_tokens):
            hits.append((cid, name, code))
    return hits[:MAX_CLIENTS]


def detect_clients_by_matter(cur, question, dept_ids, is_banqt):
    """Nhắc mã vụ việc [M-2026-001] cũng phải suy ra được khách của vụ đó."""
    codes = {c.upper() for c in RE_MATTER_CODE.findall(question or "")}
    if not codes:
        return []
    if is_banqt:
        cur.execute("""SELECT DISTINCT c.id, c.name, c.code FROM matters m
                       JOIN clients c ON c.id = m.client_id
                       WHERE upper(m.code) = ANY(%s)""", (list(codes),))
    else:
        cur.execute("""SELECT DISTINCT c.id, c.name, c.code FROM matters m
                       JOIN clients c ON c.id = m.client_id
                       WHERE upper(m.code) = ANY(%s)
                         AND c.department_id = ANY(%s)""",
                    (list(codes), dept_ids or [-1]))
    return cur.fetchall()


def _alert_intent(q_folded: str) -> bool:
    """Câu hỏi có đang hỏi về hạn chót / tiến độ nói chung hay không."""
    return any(w in q_folded for w in ALERT_WORDS)


def _alerts_block(cur, dept_ids, is_banqt, limit=15):
    """Cảnh báo trong toàn bộ phạm vi người hỏi được thấy.

    Dùng khi câu hỏi kiểu "có vụ nào quá hạn không" — không nhắc tên khách nào
    nên phần nhận diện khách không bắt được gì, nhưng đây đúng là loại câu hỏi
    một thư ký phải trả lời được.
    """
    sql = """SELECT client_name, client_code, matter_code, matter_title,
                    status, deadline, kind
               FROM v_matter_alerts"""
    params = []
    if not is_banqt:
        sql += " WHERE department_id = ANY(%s)"
        params.append(dept_ids or [-1])
    sql += """ ORDER BY CASE severity WHEN 'gap' THEN 0 ELSE 1 END,
                        days_left NULLS LAST LIMIT %s"""
    params.append(limit)
    cur.execute(sql, params)
    rows = cur.fetchall()
    if not rows:
        return ["### Cảnh báo vụ việc: không có vụ nào quá hạn hoặc sắp đến hạn "
                "trong phạm vi người hỏi phụ trách."]
    out = [f"### Cảnh báo vụ việc ({len(rows)} vụ cần chú ý, gấp xếp trước):"]
    for cname, ccode, mcode, title, status, deadline, kind in rows:
        who = cname + (f" [{ccode}]" if ccode else "")
        out.append(f"  · {who} — {mcode or '[chưa có mã]'} {title}: "
                   f"{ALERT_KIND_VN.get(kind, kind)}; {_deadline_note(deadline)}; "
                   f"trạng thái {STATUS_VN.get(status, status)}")
    return out


# ---------------------------------------------------------------
# Dựng khối dữ liệu cho một khách
# ---------------------------------------------------------------
def _pinned_text(cur, cid, doc_types, budget):
    """Nội dung tài liệu 'ghim' của khách — luôn đưa vào ngữ cảnh, không phụ
    thuộc vào việc tìm kiếm vector có bắt được hay không.

    File tổng hợp thông tin khách là nguồn sự thật về dịch vụ đã dùng, mức phí,
    tình hình hợp tác. Nếu để bộ tìm kiếm vector tự bắt thì câu hỏi diễn đạt
    lệch một chút là trượt, nên với khách đã nhận diện được thì ghim cứng.

    Bảng chunks có RLS: phiên không được cấp quyền tài chính sẽ không đọc nổi
    đoạn nào của tài liệu công nợ, dù hàm này có hỏi tới.
    """
    cur.execute("""SELECT d.title, c.content
                     FROM documents d JOIN chunks c ON c.document_id = d.id
                    WHERE d.client_id = %s AND d.doc_type = ANY(%s)
                      AND d.approved AND d.label_verified
                    ORDER BY d.updated_at DESC, d.id, c.chunk_index""",
                (cid, list(doc_types)))
    out, used, last_title = [], 0, None
    for title, content in cur.fetchall():
        if used >= budget:
            break
        if title != last_title:
            out.append(f"  ── {title} ──")
            last_title = title
        piece = (content or "").strip()
        room = budget - used
        if len(piece) > room:
            piece = piece[:room].rstrip() + "…"
        out.append("  " + piece.replace("\n", "\n  "))
        used += len(piece)
    return out


def _client_lines(cur, cid, name, code, internal, can_finance=False):
    """Một khối text gọn về khách. internal=False thì bỏ hết ghi chú nội bộ."""
    lines = [f"### Khách hàng: {name}" + (f" [mã {code}]" if code else "")]

    if internal:
        # Cơ cấu phòng ban là thông tin nội bộ, không đưa sang kênh khách.
        cur.execute("""SELECT d.name FROM clients c
                       LEFT JOIN departments d ON d.id = c.department_id
                       WHERE c.id = %s""", (cid,))
        row = cur.fetchone()
        if row and row[0]:
            lines.append(f"- Phòng phụ trách: {row[0]}")

        cur.execute("""SELECT history_note, issues_note, warnings, suggestions, updated_at
                       FROM client_profiles WHERE client_id = %s""", (cid,))
        p = cur.fetchone()
        if p and any(p[:4]):
            lines.append(f"- Hồ sơ 360° (nội bộ, cập nhật {str(p[4])[:10] if p[4] else '?'}):")
            for label, val in (("Lịch sử hợp tác", p[0]), ("Vấn đề đang tồn", p[1]),
                               ("Cảnh báo thời hiệu", p[2]), ("Gợi ý chiến lược", p[3])):
                if val and val.strip():
                    lines.append(f"  · {label}: {_cut(val)}")

    cur.execute("""SELECT code, title, matter_type, status, deadline FROM matters
                   WHERE client_id = %s
                   ORDER BY (deadline IS NULL), deadline, opened_at DESC
                   LIMIT %s""", (cid, MAX_MATTERS))
    matters = cur.fetchall()
    if matters:
        lines.append(f"- Vụ việc ({len(matters)} vụ gần/gấp nhất):")
        for m_code, title, m_type, status, deadline in matters:
            bits = [f"[{m_code}]" if m_code else "[chưa có mã]", title]
            if m_type:
                bits.append(f"({m_type})")
            bits.append(f"— {STATUS_VN.get(status, status)}, {_deadline_note(deadline)}")
            lines.append("  · " + " ".join(bits))
    else:
        lines.append("- Vụ việc: chưa có vụ nào được mở trong hệ thống")

    cur.execute("""SELECT doc_type, count(*) FROM documents
                   WHERE client_id = %s AND approved AND label_verified
                   GROUP BY doc_type ORDER BY count(*) DESC""", (cid,))
    docs = cur.fetchall()
    if docs:
        detail = ", ".join(f"{DOC_TYPE_VN.get(t, t)} {n}" for t, n in docs)
        lines.append(f"- Tài liệu của khách đã vào kho: {sum(n for _, n in docs)} ({detail})")

    if internal:
        # File tổng hợp là nơi HDS ghi dịch vụ đã dùng, mức phí, diễn biến hợp
        # tác. Chỉ ghim cho kênh nội bộ: đây là tài liệu làm việc của công ty,
        # không phải bản gửi khách.
        pinned = _pinned_text(cur, cid, ["ho_so_kh"], MAX_SUMMARY_CHARS)
        if pinned:
            lines.append("- FILE TỔNG HỢP THÔNG TIN KHÁCH (dịch vụ đã dùng, phí, hợp tác):")
            lines += pinned

        if can_finance:
            fin = _pinned_text(cur, cid, ["cong_no"], MAX_FINANCE_CHARS)
            if fin:
                lines.append("- CÔNG NỢ / TÀI CHÍNH (hạn chế — chỉ người được cấp quyền):")
                lines += fin

    return lines


# ---------------------------------------------------------------
# Điểm vào duy nhất
# ---------------------------------------------------------------
def build(question, channel, client_id=None, dept_ids=None, is_banqt=False,
          can_finance=False):
    """Khối 'DỮ LIỆU CÔNG TY' để ghép vào prompt. Trả '' nếu không có gì liên quan.

    channel='public'  → luôn trả '' (khách lạ trên website, không đưa dữ liệu nào)
    channel='portal'  → chỉ đúng khách đang đăng nhập, không có ghi chú nội bộ,
                        không có file tổng hợp, không có công nợ
    channel='internal'→ nhận diện khách/vụ trong câu hỏi, kèm hồ sơ 360°, file
                        tổng hợp, và công nợ nếu người hỏi được cấp quyền
    """
    try:
        if channel == "public":
            return ""

        if channel == "portal":
            if not client_id:
                return ""
            with db.session(role="client", client_id=client_id) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT id, name, code FROM clients WHERE id = %s", (client_id,))
                    row = cur.fetchone()
                    if not row:
                        return ""
                    lines = _client_lines(cur, row[0], row[1], row[2], internal=False)
            head = ("DỮ LIỆU HỒ SƠ CỦA BẠN (truy vấn trực tiếp hệ thống HDS, "
                    f"thời điểm {date.today()}):")
            return head + "\n" + "\n".join(lines)

        with db.session(role="internal", dept_ids=dept_ids, is_banqt=is_banqt,
                        can_finance=can_finance) as conn:
            with conn.cursor() as cur:
                found = detect_clients(cur, question, dept_ids, is_banqt)
                seen = {c[0] for c in found}
                for c in detect_clients_by_matter(cur, question, dept_ids, is_banqt):
                    if c[0] not in seen:
                        found.append(c)
                        seen.add(c[0])
                blocks = [_client_lines(cur, cid, name, code, internal=True,
                                       can_finance=can_finance)
                          for cid, name, code in found[:MAX_CLIENTS]]
                if _alert_intent(_fold(question)):
                    blocks.append(_alerts_block(cur, dept_ids, is_banqt))
                if not blocks:
                    return ""

        head = ("DỮ LIỆU CÔNG TY (truy vấn trực tiếp hệ thống HDS, "
                f"thời điểm {date.today()}):")
        return head + "\n" + "\n".join("\n".join(b) for b in blocks)
    except Exception:
        # Thiếu dữ liệu công ty thì bot vẫn phải trả lời được bằng tài liệu.
        # Không để lỗi ở đây làm sập cả lượt hỏi.
        return ""
