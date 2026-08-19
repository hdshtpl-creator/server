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
MAX_WORK_CHARS = 2500     # ngân sách ký tự cho nội dung hợp đồng/công việc của khách
MAX_HR_CHARS = 9000       # ngân sách nội dung hồ sơ nhân sự (danh mục tính riêng)

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

# Câu hỏi đếm/liệt kê khách nói chung ("có bao nhiêu công ty", "danh sách khách")
# — không nhắc tên khách cụ thể nên phần nhận diện khách không bắt được, nhưng
# đây là câu một thư ký phải trả lời được.
ROSTER_WORDS = {
    "bao nhieu khach", "bao nhieu cong ty", "bao nhieu cty", "bao nhieu doanh nghiep",
    "may khach", "may cong ty", "may cty", "tong so khach", "so luong khach",
    "danh sach khach", "danh sach cong ty", "co nhung khach nao", "nhung khach nao",
    "liet ke khach", "cac khach hang", "khach hang nao",
}

# Câu hỏi ĐẾM / LIỆT KÊ chính KHO TÀI LIỆU ("HDS có mấy tài liệu bản án",
# "kho có bao nhiêu văn bản luật"). Đây là câu metadata về kho — phải đếm bằng
# SQL trên bảng documents, không để model đoán từ vài đoạn tìm được rồi trả
# lời "không thấy" trong khi câu hỏi là về SỐ LƯỢNG.
INVENTORY_TYPE_WORDS = {
    "ban an": "ban_an", "an le": "an_le",
    "van ban luat": "law", "van ban phap luat": "law",
    "hop dong mau": "mau_hd", "mau hop dong": "mau_hd",
    "thu mau": "thu_mau", "quy trinh": "quy_trinh",
    "nhan hieu": "nhan_hieu", "thu tu van": "advisory",
}

# Câu hỏi về chính công ty mình: quân số, ai làm phòng nào. Dữ liệu nằm ở bảng
# users/departments — không nằm trong tài liệu nào để mà tìm bằng vector, nên
# phải rút bằng SQL giống cách làm với khách hàng.
STAFF_WORDS = {
    "bao nhieu nhan vien", "bao nhieu nhan su", "bao nhieu nguoi",
    "may nhan vien", "may nguoi", "tong so nhan vien", "so luong nhan vien",
    "danh sach nhan vien", "danh sach nhan su", "nhan su cong ty",
    "co bao nhieu luat su", "bao nhieu luat su", "bao nhieu chuyen vien",
    "bao nhieu phong", "danh sach phong ban", "co nhung phong nao",
    "nhan vien nao", "quan so", "co bao nhieu nhan",
    # Câu hỏi CHI TIẾT về người — hay xuất hiện ở lượt hỏi tiếp
    "chi tiet tung ca nhan", "tung ca nhan", "tung nguoi", "moi nguoi",
    "ho ten", "ten nhan vien", "ai lam gi", "gom nhung ai", "bao gom ai",
    "danh sach nguoi", "liet ke nhan vien", "thong tin nhan su",
    "nhan su hds", "nguoi lao dong", "hop dong lao dong",
    # Viết tắt/ngôn ngữ nói thường gặp. Các cụm ngắn như "nv" được kiểm tra
    # theo ranh giới từ ở _staff_intent, không dùng phép `in` lỏng.
    "bao nhieu nv", "may nv", "danh sach nv", "cty toi co may nguoi",
    "cong ty toi co may nguoi", "hds co may nguoi", "hds co bao nhieu nguoi",
}

# Phân biệt tài khoản phần mềm với người lao động. Đây là hai khái niệm dữ liệu
# khác nhau; trộn chúng là nguyên nhân trực tiếp khiến bot báo "5 người" khi
# CSDL thực ra chỉ có 5 tài khoản đăng nhập.
ACCOUNT_WORDS = {
    "tai khoan", "account", "user", "nguoi dung", "dang nhap",
    "tai khoan noi bo", "tai khoan phan mem",
}

EMPLOYMENT_CONTRACT_WORDS = {
    "hop dong lao dong", "hdld", "hd lao dong", "con hop dong",
    "con han hop dong", "hop dong con han", "het hop dong", "het han hop dong",
    "dang co hop dong", "thoi han hop dong", "gia han hop dong",
}

# Tên cấp bậc hiển thị cho người đọc — khớp với CHECK role trong schema.
ROLE_VN = {
    "admin": "Quản trị hệ thống", "ban_qt": "Ban quản trị",
    "truong_bph": "Trưởng bộ phận", "chuyen_vien": "Chuyên viên",
    "tro_ly": "Trợ lý",
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
def _visible_clients(cur, dept_ids, is_banqt, limit=None):
    """Khách mà người hỏi được phép thấy. Lọc theo phòng vì clients không có RLS.
    Khách chưa gán phòng (department_id NULL) coi như dùng chung — mọi nội bộ thấy,
    khớp với cách RLS xử lý (app_in_dept trả true khi dept NULL)."""
    suffix = " ORDER BY name LIMIT %s" if limit else ""
    if is_banqt:
        cur.execute("SELECT id, name, code FROM clients" + suffix,
                    (limit,) if limit else ())
    else:
        sql = """SELECT id, name, code FROM clients
                  WHERE department_id = ANY(%s) OR department_id IS NULL""" + suffix
        params = [dept_ids or [-1]]
        if limit:
            params.append(limit)
        cur.execute(sql, params)
    return cur.fetchall()


def detect_clients(cur, question, dept_ids, is_banqt):
    """Khách được nhắc trong câu hỏi — khớp theo mã, hoặc theo từ đặc trưng của tên."""
    q = _fold(question)
    q_tokens = set(re.findall(r"[a-z0-9]+", q))
    # Không tải toàn bộ bảng clients về Python trên MỌI câu hỏi. Lọc ứng viên
    # bằng mã/từ đặc trưng trước; idx_clients_*_trgm giúp truy vấn này giữ được
    # tốc độ khi danh mục lên hàng trăm nghìn khách.
    stop = {
        "cong", "ty", "tnhh", "co", "phan", "tap", "doan", "doanh", "nghiep",
        "khach", "hang", "hds", "luat", "van", "phong", "cho", "toi", "cua",
        "nay", "kia", "dang", "lam", "viec", "ho", "so", "thong", "tin",
        "the", "nao", "bao", "nhieu", "may", "gi", "va", "voi", "ve",
    }
    name_tokens = sorted((t for t in q_tokens if len(t) >= 3 and t not in stop),
                         key=len, reverse=True)[:10]
    code_tokens = sorted(t for t in q_tokens if len(t) >= 3)[:20]
    if not name_tokens and not code_tokens:
        return []
    patterns = [f"%{token}%" for token in name_tokens]
    scope_sql = "" if is_banqt else (
        " AND (department_id=ANY(%s) OR department_id IS NULL)")
    params = [code_tokens, patterns]
    if not is_banqt:
        params.append(dept_ids or [-1])
    cur.execute(
        """SELECT id,name,code FROM clients
            WHERE (lower(coalesce(code,''))=ANY(%s)
                   OR lower(name) LIKE ANY(%s))""" + scope_sql
        + " ORDER BY name LIMIT 200",
        params,
    )
    hits = []
    for cid, name, code in cur.fetchall():
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
                         AND (c.department_id = ANY(%s) OR c.department_id IS NULL)""",
                    (list(codes), dept_ids or [-1]))
    return cur.fetchall()


def _alert_intent(q_folded: str) -> bool:
    """Câu hỏi có đang hỏi về hạn chót / tiến độ nói chung hay không."""
    return any(w in q_folded for w in ALERT_WORDS)


def _roster_intent(q_folded: str) -> bool:
    """Câu hỏi kiểu đếm/liệt kê khách nói chung."""
    return any(w in q_folded for w in ROSTER_WORDS)


# Từ khoá cho thấy câu hỏi thật ra về TÀI LIỆU/HỢP ĐỒNG, không phải đếm đầu
# người. "bao nhiêu người CÒN HỢP ĐỒNG" là hỏi về hợp đồng lao động — trả lời
# bằng bộ đếm tài khoản là sai. Có mặt các từ này thì không coi là câu danh bạ.
_DOC_TOPIC_WORDS = {"hop dong", "hd lao dong", "hdld", "hop dong lao dong",
                    "con han", "het han", "gia han", "ky hop dong", "thanh ly"}


def _staff_intent(q_folded: str) -> bool:
    """Câu hỏi về nhân sự của chính HDS (quân số, cơ cấu, từng người).

    KHÔNG loại trừ câu về hợp đồng nữa: câu 'bao nhiêu người còn hợp đồng' cần
    CẢ HAI nguồn — số tài khoản trong hệ thống VÀ nội dung hợp đồng lao động đã
    học. Trước đây chặn ở đây khiến bot mất sạch dữ liệu nhân sự cho đúng loại
    câu hỏi ấy. Việc phân biệt 'tài khoản' với 'người lao động theo hợp đồng'
    do khối dữ liệu tự nói rõ, không phải bằng cách giấu dữ liệu đi."""
    if re.search(r"(?:^|\s)nv(?:$|\s)", q_folded):
        return True
    # "nhân sự" / "nhân viên" ĐỨNG MỘT MÌNH cũng là câu hỏi nhân sự. Trước đây
    # danh sách chỉ có các cụm ghép ("danh sách nhân sự", "nhân sự công ty"),
    # nên câu rất tự nhiên như "tất cả nhân sự trước giờ gồm những ai" trượt
    # hết — không ghim hồ sơ, không bổ sung nguồn, bot phải mò bằng vector và
    # vớ phải Điều lệ công ty rồi kết luận công ty có 01 người.
    if re.search(r"(?:^|\s)nhan (?:su|vien)(?:$|\s)", q_folded):
        return True
    return any(w in q_folded for w in STAFF_WORDS)


def _account_intent(q_folded: str) -> bool:
    """Người hỏi đang hỏi rõ về tài khoản phần mềm, không phải nhân sự HR."""
    return any(w in q_folded for w in ACCOUNT_WORDS)


def _doc_inventory_intent(q_folded: str) -> bool:
    """Câu hỏi ĐẾM/LIỆT KÊ kho tài liệu — 'HDS có mấy tài liệu bản án'.

    Cố tình chặt để không nuốt câu tra cứu NỘI DUNG: 'bao nhiêu bản án VỀ
    tranh chấp đất' là hỏi về một chủ đề — phải đi tìm tài liệu thật, không
    phải đếm kho, nên có ' ve ' là bỏ qua.
    """
    if " ve " in f" {q_folded} ":
        return False
    counting = bool(re.search(
        r"\b(bao nhieu|co may|dang co may|may|danh sach|liet ke|thong ke)\b",
        q_folded))
    if not counting and not re.search(r"\btai lieu (nao|gi)\b", q_folded):
        return False
    if re.search(r"\b(tai lieu|van ban|kho du lieu|kho tai lieu)\b", q_folded):
        return True
    return any(w in q_folded for w in INVENTORY_TYPE_WORDS)


def _requested_doc_types(q_folded: str) -> list[str]:
    """Loại tài liệu được nhắc đích danh trong câu đếm kho (có thể rỗng)."""
    return sorted({dt for w, dt in INVENTORY_TYPE_WORDS.items() if w in q_folded})


def _employment_contract_intent(q_folded: str) -> bool:
    """Câu hỏi về hiệu lực HĐLĐ của nhân sự HDS."""
    return any(w in q_folded for w in EMPLOYMENT_CONTRACT_WORDS)


# Từ khoá cho thấy câu hỏi muốn CHI TIẾT từng khách (dịch vụ, hợp đồng, tình
# hình…), không phải chỉ đếm/liệt kê tên. "mấy khách VÀ dịch vụ cung cấp" cần
# đọc hồ sơ từng khách, không được bỏ qua tài liệu.
DETAIL_WORDS = {
    "dich vu", "cung cap", "dang lam", "dang cung cap", "phi", "muc phi",
    "hop dong", "cong viec", "chi tiet", "thong tin", "ho so", "tinh hinh",
    "hop tac", "da dung", "su dung", "cong no", "da lam", "lam gi",
}

# Số khách tối đa được BUNG chi tiết cho câu "liệt kê khách kèm dịch vụ". Nhiều
# hơn thì prompt quá dài — lúc đó chỉ liệt kê tên và mời hỏi từng khách.
ROSTER_DETAIL_MAX = 5


def _detail_intent(q_folded: str) -> bool:
    """Câu hỏi có đòi CHI TIẾT (dịch vụ, hợp đồng, tình hình) từng khách không."""
    return any(w in q_folded for w in DETAIL_WORDS)


def is_directory_query(question: str) -> bool:
    """Câu hỏi ĐẾM / LIỆT KÊ danh bạ của chính công ty — bao nhiêu khách, bao
    nhiêu nhân viên, danh sách phòng ban…

    Loại câu này trả lời hoàn toàn từ dữ liệu có cấu trúc trong CSDL. Đưa thêm
    tài liệu tìm bằng vector vào chỉ có hại: câu 'HDS có mấy khách' sẽ lôi về
    hợp đồng lao động, đơn nghỉ phép — vừa hiện làm 'nguồn' sai lệch, vừa dễ
    khiến model trả lời theo mớ tài liệu đó thay vì con số thật.

    NHƯNG nếu câu hỏi còn đòi CHI TIẾT (dịch vụ, hợp đồng của từng khách) thì
    KHÔNG bỏ tra tài liệu — lúc đó phải mở hồ sơ bên trong ra đọc. Chỉ câu ĐẾM
    THUẦN mới bỏ. Cũng không gộp câu về hạn/cảnh báo vào đây.

    CHỈ áp cho danh sách KHÁCH HÀNG. Câu hỏi NHÂN SỰ thì luôn tra tài liệu: hồ
    sơ nhân sự và hợp đồng lao động đã học chính là nguồn để trả lời "công ty có
    mấy người", "chi tiết từng người". Bỏ tra tài liệu ở đó khiến bot chỉ còn
    biết đếm tài khoản đăng nhập — đúng lỗi "trả lời 5 người" vừa gặp.
    """
    q = _fold(question)
    if _detail_intent(q) or _staff_intent(q):
        return False
    return _roster_intent(q)


def is_staff_query(question: str) -> bool:
    """Câu hỏi này đang hỏi về NGƯỜI LAO ĐỘNG của HDS hay không.

    rag.prepare dùng để thu hẹp tìm kiếm về đúng loại 'hồ sơ nhân sự'. Cần thiết
    vì Điều lệ công ty đầy chữ 'thành viên', 'người quản lý', 'danh sách những
    người có liên quan' — xét theo ngữ nghĩa thì nó khớp câu hỏi nhân sự rất
    cao, đủ để đẩy hợp đồng lao động ra khỏi top-k.
    """
    q = _fold(question)
    return _staff_intent(q) or _employment_contract_intent(q)


def _staff_block(cur, is_banqt):
    """Quân số và cơ cấu phòng ban của HDS.

    Chỉ đếm tài khoản NỘI BỘ đang hoạt động — tài khoản khách hàng (client_*)
    không phải nhân viên. Không đưa email hay thông tin liên hệ vào prompt: câu
    hỏi ở đây là về quân số, không phải danh bạ.

    Người không thuộc Ban QT vẫn thấy tổng quân số và cơ cấu phòng — đây là
    thông tin tổ chức bình thường trong nội bộ — nhưng không thấy danh sách tên.
    """
    cur.execute("""SELECT role, count(*) FROM users
                    WHERE active AND role NOT IN ('client_free','client_plus','client_pro')
                    GROUP BY role""")
    by_role = cur.fetchall()
    if not by_role:
        return ["### Nhân sự HDS: hệ thống chưa có tài khoản nhân viên nào."]

    total = sum(n for _, n in by_role)
    out = [f"### Tài khoản nội bộ trên phần mềm: {total} tài khoản đang hoạt động.",
           "  LƯU Ý QUAN TRỌNG: đây CHỈ là số tài khoản đăng nhập, KHÔNG phải "
           "quân số nhân sự của công ty. Khi người dùng hỏi công ty có bao nhiêu "
           "người / nhân sự gồm những ai, hãy trả lời dựa vào HỒ SƠ NHÂN SỰ và "
           "HỢP ĐỒNG LAO ĐỘNG trong phần tài liệu tham khảo; chỉ nêu con số tài "
           "khoản này khi được hỏi riêng về tài khoản phần mềm.",
           "- Theo cấp bậc (tài khoản): " + ", ".join(
               f"{ROLE_VN.get(r, r)} {n}" for r, n in
               sorted(by_role, key=lambda x: -x[1]))]

    # count(u.id) chứ không phải count(ud.user_id): điều kiện lọc nằm ở mệnh đề
    # ON nên dòng của tài khoản đã nghỉ vẫn còn, chỉ phần users là NULL.
    cur.execute("""SELECT d.name, count(u.id)
                     FROM departments d
                     LEFT JOIN user_departments ud ON ud.department_id = d.id
                     LEFT JOIN users u ON u.id = ud.user_id
                          AND u.active AND u.role NOT IN ('client_free','client_plus','client_pro')
                    GROUP BY d.name ORDER BY d.name""")
    by_dept = cur.fetchall()
    if by_dept:
        out.append("- Theo phòng ban: " + ", ".join(f"{name} {n}" for name, n in by_dept))

    if is_banqt:
        cur.execute("""SELECT u.full_name, u.role,
                              coalesce(string_agg(d.name, ', ' ORDER BY d.name), '')
                         FROM users u
                         LEFT JOIN user_departments ud ON ud.user_id = u.id
                         LEFT JOIN departments d ON d.id = ud.department_id
                        WHERE u.active AND u.role NOT IN ('client_free','client_plus','client_pro')
                        GROUP BY u.id, u.full_name, u.role
                        ORDER BY u.full_name LIMIT 100""")
        rows = cur.fetchall()
        if rows:
            out.append("- Danh sách tài khoản (chỉ Ban quản trị được xem):")
            for name, role, depts in rows:
                out.append(f"  · {name or '(chưa đặt tên)'} — {ROLE_VN.get(role, role)}"
                           + (f", phòng {depts}" if depts else ""))

    # GHIM nội dung HỒ SƠ NHÂN SỰ đã học (HĐLĐ, quyết định, sơ yếu lý lịch…).
    # Đây mới là nguồn sự thật về nhân sự công ty. Không ghim thì bot phải trông
    # vào may mắn của tìm kiếm vector, và dễ trả lời bằng số tài khoản.
    out += _hr_block(cur)
    return out


def _hr_block(cur, budget=MAX_HR_CHARS):
    """Hồ sơ nhân sự: DANH MỤC ĐẦY ĐỦ trước, nội dung chi tiết sau.

    Bản cũ đổ nguyên văn từng đoạn cho tới khi hết ngân sách. Một hồ sơ dài 55
    đoạn ngốn sạch 5000 ký tự trước khi tới lượt hồ sơ người thứ hai, nên bot
    đọc mười file của cùng một người rồi kết luận "công ty có 01 nhân sự" —
    trung thực với thứ nó nhìn thấy, nhưng sai với thực tế.

    Câu hỏi "công ty có mấy người" cần BIẾT ĐỦ TÊN chứ không cần đọc sâu từng
    hồ sơ. Vì vậy: liệt kê mọi hồ sơ trước (mỗi hồ sơ một dòng — rẻ và không
    bao giờ bỏ sót ai), rồi mới chia đều phần ngân sách còn lại cho nội dung.
    """
    cur.execute("""SELECT d.id, d.title, d.summary
                     FROM documents d
                    WHERE d.client_id IS NULL AND d.doc_type = 'ho_so_ns'
                      AND d.approved AND d.label_verified
                      AND coalesce(d.active, true)
                    ORDER BY d.title""")
    docs = cur.fetchall()
    if not docs:
        return []

    out = [f"- HỒ SƠ NHÂN SỰ ĐÃ HỌC — {len(docs)} hồ sơ (nguồn sự thật về người "
           "lao động; đọc kỹ để trả lời quân số, họ tên, chức danh, thời hạn HĐLĐ).",
           "  DANH MỤC ĐẦY ĐỦ (không hồ sơ nào bị bỏ sót — đếm người theo danh "
           "mục này, một người có thể có NHIỀU hồ sơ nên phải gộp theo TÊN):"]
    for _, title, summary in docs:
        line = f"  · {title}"
        if summary:
            line += f" — {_cut(summary, 180)}"
        out.append(line)

    # Phần còn lại chia ĐỀU cho từng hồ sơ, không để hồ sơ nào chiếm hết.
    share = max(300, budget // max(1, len(docs)))
    out.append("  NỘI DUNG TRÍCH TỪ TỪNG HỒ SƠ:")
    for doc_id, title, _ in docs:
        cur.execute("""SELECT content FROM chunks
                        WHERE document_id = %s
                        ORDER BY chunk_index LIMIT 3""", (doc_id,))
        rows = cur.fetchall()
        if not rows:
            continue
        text = _cut(" ".join((r[0] or "").strip() for r in rows), share)
        out.append(f"  ── {title} ──")
        out.append("  " + text.replace("\n", "\n  "))
    return out


def _roster_block(cur, dept_ids, is_banqt, limit=60):
    """Danh sách khách người hỏi được thấy — cho câu 'có bao nhiêu công ty'.

    Lọc theo phòng ban vì bảng clients không có RLS (Ban QT thấy tất cả)."""
    if is_banqt:
        cur.execute("""SELECT c.name, c.code, d.name FROM clients c
                       LEFT JOIN departments d ON d.id=c.department_id
                       ORDER BY c.name LIMIT %s""", (limit,))
    else:
        cur.execute("""SELECT c.name, c.code, d.name FROM clients c
                       LEFT JOIN departments d ON d.id=c.department_id
                       WHERE c.department_id = ANY(%s) OR c.department_id IS NULL
                       ORDER BY c.name LIMIT %s""", (dept_ids or [-1], limit))
    rows = cur.fetchall()
    # Ban QT thấy toàn công ty; người khác chỉ thấy khách phòng mình. Ghi rõ
    # phạm vi để bot không trả lời con số của một phòng như thể là của cả HDS.
    scope = "toàn công ty" if is_banqt else "trong phạm vi phòng bạn phụ trách"
    if not rows:
        return [f"### Danh sách khách hàng: chưa có khách nào {scope}."]
    out = [f"### Khách hàng ({scope}) — {len(rows)} khách:"]
    for name, code, dept in rows:
        bits = f"  · {name}" + (f" [mã {code}]" if code else "")
        if dept:
            bits += f" — phòng {dept}"
        out.append(bits)
    return out


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

    cid=None: tài liệu KHÔNG thuộc khách nào — dùng cho hồ sơ nhân sự của chính
    HDS (hợp đồng lao động, quyết định, sơ yếu lý lịch).
    """
    if cid is None:
        cur.execute("""SELECT d.title, c.content
                         FROM documents d JOIN chunks c ON c.document_id = d.id
                        WHERE d.client_id IS NULL AND d.doc_type = ANY(%s)
                          AND d.approved AND d.label_verified
                        ORDER BY d.updated_at DESC, d.id, c.chunk_index""",
                    (list(doc_types),))
    else:
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


def _client_lines(cur, cid, name, code, internal, can_finance=False, share=1,
                  detail=False):
    """Một khối text gọn về khách. internal=False thì bỏ hết ghi chú nội bộ.

    `share` là số khách cùng được nhắc trong một câu hỏi: ngân sách file tổng
    hợp chia đều cho từng khách, để câu hỏi so sánh ba khách không dựng ra một
    prompt dài gấp ba rồi bị cắt mất phần đầu.

    `detail=True` (câu hỏi đòi dịch vụ/hợp đồng cụ thể): ghim thêm NỘI DUNG hợp
    đồng/thư tư vấn của khách, để bot đọc thẳng chi tiết bên trong thay vì chỉ
    đếm số tài liệu.
    """
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
        share = max(1, share)
        pinned = _pinned_text(cur, cid, ["ho_so_kh"], MAX_SUMMARY_CHARS // share)
        if pinned:
            lines.append("- FILE TỔNG HỢP THÔNG TIN KHÁCH (dịch vụ đã dùng, phí, hợp tác):")
            lines += pinned

        if detail:
            # Đọc thẳng nội dung hợp đồng / thư tư vấn / hồ sơ của khách — đây là
            # nơi ghi rõ dịch vụ đang cung cấp. Gồm cả 'other' vì hợp đồng trong
            # thư mục khách có thể chưa được gắn đúng loại. KHÔNG gồm cong_no
            # (RLS đã chặn nếu không có quyền tài chính), ho_so_kh đã ghim ở trên.
            work = _pinned_text(cur, cid,
                                ["contract", "advisory", "mau_hd", "filing", "other"],
                                MAX_WORK_CHARS // share)
            if work:
                lines.append("- NỘI DUNG HỢP ĐỒNG / CÔNG VIỆC ĐANG LÀM CHO KHÁCH:")
                lines += work

        if can_finance:
            fin = _pinned_text(cur, cid, ["cong_no"], MAX_FINANCE_CHARS // share)
            if fin:
                lines.append("- CÔNG NỢ / TÀI CHÍNH (hạn chế — chỉ người được cấp quyền):")
                lines += fin

    return lines


# ---------------------------------------------------------------
# Điểm vào duy nhất
# ---------------------------------------------------------------
# Câu hỏi tiếp nối, tự nó không mang chủ đề: "chi tiết từng cá nhân", "còn ai
# nữa", "cụ thể hơn". Gặp loại này phải xét CHỦ ĐỀ CỦA LƯỢT TRƯỚC, nếu không thì
# bot mất sạch dữ liệu ở lượt hỏi thứ hai — đúng lỗi "Không có thông tin cụ thể
# trong tài liệu" dù lượt trước vừa liệt kê xong.
# Chỉ những cụm ĐẶC TRƯNG, nhiều ký tự. Tránh từ ngắn như "ai"/"va"/"do": vì so
# khớp theo chuỗi con, "ai" sẽ trúng cả "tai lieu", "hai", "phai"… làm mọi câu
# ngắn đều bị coi là hỏi tiếp.
FOLLOWUP_WORDS = {
    "chi tiet", "cu the", "chi tiet hon", "ro hon", "them thong tin",
    "con ai", "con gi", "con nua", "the nao", "ra sao", "nhu the nao",
    "bao gom", "liet ke", "day du", "tung nguoi", "tung ca nhan",
    "ho ten", "danh sach", "moi nguoi", "gom nhung",
    # Câu sửa lại ý ở lượt trước. Đây chính là dạng "tôi hỏi người còn hợp
    # đồng mà"; nếu không coi là follow-up thì router mất chủ đề HĐLĐ đã lưu.
    "toi hoi", "y toi", "toi dang hoi", "toi muon hoi", "van de toi hoi",
}


def _is_followup(q_folded: str) -> bool:
    """Câu ngắn mang tính hỏi thêm — cần vay chủ đề của lượt trước."""
    if len(q_folded.split()) > 8:
        return False
    return any(w in q_folded for w in FOLLOWUP_WORDS)


def _topic_question(question, history, turns=3):
    """Câu dùng để NHẬN DIỆN CHỦ ĐỀ (roster / nhân sự / cảnh báo / chi tiết).

    Bình thường là chính câu hỏi. Nhưng nếu đây là câu hỏi tiếp ngắn gọn, ghép
    thêm mấy câu người dùng đã hỏi trước đó để chủ đề không bị mất — nhờ vậy
    "chi tiết từng cá nhân" vẫn được hiểu là đang nói về nhân sự.

    `turns` nhỏ hơn khi dùng để nhận diện KHÁCH HÀNG: vay quá xa dễ lôi tên
    khách của chuyện cũ vào câu hỏi mới, và trả lời sai khách còn tệ hơn thiếu.
    """
    q = _fold(question)
    if not history or not _is_followup(q):
        return question
    prev = [c for role, c in history if role == "user"][-turns:]
    return question + " " + " ".join(prev)


def infer_intent(question, history=None, state=None):
    """Nhận diện nhóm dữ liệu có thể trả lời xác định, không cần LLM.

    `state` là chủ đề có cấu trúc đã lưu ở conversation. Nó chỉ được dùng cho
    câu hỏi tiếp ngắn; câu hỏi đầy đủ luôn tự quyết định lại để tránh kéo nhầm
    chủ đề cũ sang việc mới.
    """
    folded_current = _fold(question)
    if _is_followup(folded_current) and state and state.get("intent"):
        return state.get("intent")

    topic = _fold(_topic_question(question, history))
    if _roster_intent(topic) and not _detail_intent(topic):
        return "client_roster"
    if _account_intent(topic) and (_staff_intent(topic) or any(
            w in topic for w in ("noi bo", "hds", "cong ty", "cty"))):
        return "account_directory"
    if (_employment_contract_intent(topic)
            and (_staff_intent(topic) or any(w in topic for w in (
                "nhan vien", "nhan su", "nguoi lao dong", "nguoi trong hds",
                "cty toi", "cong ty toi")))):
        return "employment_contract"
    if _staff_intent(topic):
        return "staff_directory"
    if _alert_intent(topic):
        return "matter_alerts"
    if _doc_inventory_intent(topic):
        return "doc_inventory"
    return None


def _system_evidence(title, locator, quote):
    """Nguồn dữ liệu vận hành cho UI; không giả làm một tài liệu trích dẫn."""
    return {
        "kind": "system",
        "title": title,
        "source_locator": locator,
        "quote": quote,
        "as_of": date.today().isoformat(),
    }


def _active_accounts():
    """Tài khoản phần mềm đang hoạt động, tách hẳn khỏi dữ liệu nhân sự HR."""
    with db.session(role="internal") as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT u.full_name, u.role,
                                  coalesce(string_agg(d.name, ', ' ORDER BY d.name), '')
                             FROM users u
                             LEFT JOIN user_departments ud ON ud.user_id=u.id
                             LEFT JOIN departments d ON d.id=ud.department_id
                            WHERE u.active
                              AND u.role NOT IN ('client_free','client_plus','client_pro')
                            GROUP BY u.id,u.full_name,u.role ORDER BY u.full_name""")
            return cur.fetchall()


def _employees_with_latest_contract():
    """Đọc sổ nhân sự chuẩn. Trả [] khi máy chủ chưa chạy migration mới.

    Không suy người lao động từ `users`: một người có thể chưa có tài khoản,
    hoặc một tài khoản kỹ thuật không phải một lao động.
    """
    try:
        with db.session(role="internal") as conn:
            with conn.cursor() as cur:
                cur.execute("""SELECT e.id,e.employee_code,e.full_name,e.title,d.name,
                                      e.employment_status,e.active,
                                      ec.contract_no,ec.start_date,ec.end_date,ec.status
                                 FROM employees e
                                 LEFT JOIN departments d ON d.id=e.department_id
                                 LEFT JOIN LATERAL (
                                   SELECT c.contract_no,c.start_date,c.end_date,c.status
                                     FROM employment_contracts c
                                    WHERE c.employee_id=e.id
                                    ORDER BY c.start_date DESC NULLS LAST,c.id DESC LIMIT 1
                                 ) ec ON true
                                WHERE e.active
                                  AND coalesce(e.employment_status,'working')
                                      NOT IN ('terminated','inactive')
                                ORDER BY e.full_name""")
                return cur.fetchall()
    except Exception:
        return []


def _contract_is_current(row):
    """Hiệu lực HĐLĐ được tính từ trạng thái + ngày, không tin riêng một cột."""
    start_date, end_date, status = row[8], row[9], (row[10] or "").lower()
    today = date.today()
    if not row[7] or status in {"expired", "terminated", "cancelled", "inactive"}:
        return False
    if start_date and start_date > today:
        return False
    if end_date and end_date < today:
        return False
    return status in {"active", "valid", "effective", ""}


def structured_answer(question, channel, client_id=None, dept_ids=None,
                      is_banqt=False, can_finance=False, history=None, state=None):
    """Trả lời xác định cho dữ liệu vận hành; `None` nghĩa là chuyển sang RAG.

    Hàm này là cổng chống bịa: câu đếm/danh sách không đi qua model sinh văn
    bản. Kết quả luôn ghi rõ phạm vi, ngày chốt và loại dữ liệu đang đếm.
    """
    if channel != "internal":
        return None
    intent = infer_intent(question, history=history, state=state)
    if not intent:
        return None

    next_state = {"intent": intent, "updated_on": date.today().isoformat()}

    if intent == "client_roster":
        with db.session(role="internal", dept_ids=dept_ids, is_banqt=is_banqt,
                        can_finance=can_finance) as conn:
            with conn.cursor() as cur:
                if is_banqt:
                    cur.execute("SELECT count(*) FROM clients")
                    total = cur.fetchone()[0]
                    cur.execute("""SELECT c.name,c.code,d.name FROM clients c
                                   LEFT JOIN departments d ON d.id=c.department_id
                                   ORDER BY c.name LIMIT 60""")
                else:
                    cur.execute("""SELECT count(*) FROM clients
                                   WHERE department_id=ANY(%s) OR department_id IS NULL""",
                                (dept_ids or [-1],))
                    total = cur.fetchone()[0]
                    cur.execute("""SELECT c.name,c.code,d.name FROM clients c
                                   LEFT JOIN departments d ON d.id=c.department_id
                                   WHERE c.department_id=ANY(%s) OR c.department_id IS NULL
                                   ORDER BY c.name LIMIT 60""", (dept_ids or [-1],))
                rows = cur.fetchall()
        scope = "toàn công ty" if is_banqt else "trong phạm vi phòng bạn phụ trách"
        lines = [f"HDS có **{total} khách hàng {scope}** (tính đến {date.today()})."]
        lines += [f"- {name}" + (f" — mã {code}" if code else "")
                  + (f", phòng {dept}" if dept else "") for name, code, dept in rows]
        if total > len(rows):
            lines.append(f"- … và {total - len(rows)} khách khác; danh sách trên giới hạn 60 dòng.")
        return {
            "answer": "\n".join(lines), "answer_mode": "structured",
            "grounding_status": "verified",
            "evidence": [_system_evidence("Danh mục khách hàng HDS", "clients",
                                          f"COUNT={total}; phạm vi={scope}")],
            "state": next_state,
        }

    if intent == "matter_alerts":
        with db.session(role="internal", dept_ids=dept_ids, is_banqt=is_banqt,
                        can_finance=can_finance) as conn:
            with conn.cursor() as cur:
                lines = _alerts_block(cur, dept_ids, is_banqt)
        return {
            "answer": "\n".join(lines), "answer_mode": "structured",
            "grounding_status": "verified",
            "evidence": [_system_evidence("Cảnh báo vụ việc HDS", "v_matter_alerts",
                                          lines[0])],
            "state": next_state,
        }

    if intent == "doc_inventory":
        # RLS trên documents áp theo phiên: mỗi người chỉ đếm được đúng phần
        # kho mình được xem (công nợ, hồ sơ phòng khác tự bị loại).
        wanted = _requested_doc_types(_fold(_topic_question(question, history)))
        with db.session(role="internal", dept_ids=dept_ids, is_banqt=is_banqt,
                        can_finance=can_finance) as conn:
            with conn.cursor() as cur:
                cur.execute("""SELECT coalesce(doc_type,'other') AS dt, count(*)
                                 FROM documents
                                WHERE approved AND label_verified
                                  AND coalesce(active,true)
                                GROUP BY 1 ORDER BY count(*) DESC, 1""")
                rows = cur.fetchall()
        counts = dict(rows)
        total = sum(counts.values())
        lines = []
        for dt in wanted:
            n = counts.get(dt, 0)
            label = DOC_TYPE_VN.get(dt, dt)
            if n:
                lines.append(f"Kho hiện có **{n} tài liệu {label}** đã duyệt "
                             f"(tính đến {date.today()}).")
            else:
                lines.append(f"Kho **chưa có tài liệu {label} nào** được duyệt "
                             f"(tính đến {date.today()}). Muốn bot trả lời được "
                             f"về {label}, thả file vào đúng thư mục trên Drive "
                             "rồi chờ đồng bộ/duyệt.")
        if total:
            lines.append(f"Toàn kho có {total} tài liệu đã duyệt trong phạm vi "
                         "bạn được xem:")
            lines += [f"- {DOC_TYPE_VN.get(dt, dt)}: {n}" for dt, n in rows]
        else:
            lines.append("Kho chưa có tài liệu nào được duyệt trong phạm vi bạn được xem.")
        return {
            "answer": "\n".join(lines), "answer_mode": "structured",
            "grounding_status": "verified",
            "evidence": [_system_evidence(
                "Kho tài liệu HDS", "documents",
                f"tổng={total}" + (f"; loại được hỏi={', '.join(wanted)}" if wanted else ""))],
            "state": next_state,
        }

    accounts = _active_accounts()
    if intent == "account_directory":
        lines = [f"Hệ thống có **{len(accounts)} tài khoản nội bộ đang hoạt động** "
                 f"(tính đến {date.today()}). Đây là tài khoản phần mềm, không phải quân số HR."]
        if is_banqt:
            lines += [f"- {name or '(chưa đặt tên)'} — {ROLE_VN.get(role, role)}"
                      + (f", phòng {depts}" if depts else "")
                      for name, role, depts in accounts]
        return {
            "answer": "\n".join(lines), "answer_mode": "structured",
            "grounding_status": "verified",
            "evidence": [_system_evidence("Tài khoản nội bộ HDS", "users.active",
                                          f"COUNT={len(accounts)}")],
            "state": next_state,
        }

    employees = _employees_with_latest_contract()
    if not employees:
        # Chưa có sổ nhân sự có cấu trúc KHÔNG có nghĩa là không biết gì. Hợp
        # đồng lao động và hồ sơ nhân sự đã học vẫn trả lời được câu này. Trả
        # None để rơi xuống luồng tra tài liệu, thay vì chặn người dùng bằng một
        # câu từ chối trong khi tài liệu đang nằm sẵn trong kho.
        return None

    if intent == "employment_contract":
        current = [row for row in employees if _contract_is_current(row)]
        lines = [f"Có **{len(current)}/{len(employees)} người có HĐLĐ còn hiệu lực** "
                 f"tính đến {date.today()}."]
        if is_banqt:
            for row in employees:
                state_text = "còn hiệu lực" if _contract_is_current(row) else "không còn hiệu lực/chưa có dữ liệu"
                period = ""
                if row[8] or row[9]:
                    period = f" ({row[8] or '?'} → {row[9] or 'không xác định thời hạn'})"
                lines.append(f"- {row[2]} — {row[7] or 'chưa có số HĐ'}: {state_text}{period}")
        return {
            "answer": "\n".join(lines), "answer_mode": "structured",
            "grounding_status": "verified",
            "evidence": [_system_evidence("Sổ hợp đồng lao động HDS",
                                          "employees + employment_contracts",
                                          f"Còn hiệu lực={len(current)}; tổng nhân sự={len(employees)}")],
            "state": next_state,
        }

    # staff_directory
    lines = [f"HDS có **{len(employees)} nhân sự đang hoạt động** trong sổ nhân sự "
             f"(tính đến {date.today()})."]
    if is_banqt:
        lines += [f"- {row[2]}" + (f" — {row[3]}" if row[3] else "")
                  + (f", phòng {row[4]}" if row[4] else "") for row in employees]
    else:
        lines.append("Danh sách họ tên chỉ hiển thị cho Ban quản trị; bạn đang xem số tổng hợp.")
    return {
        "answer": "\n".join(lines), "answer_mode": "structured",
        "grounding_status": "verified",
        "evidence": [_system_evidence("Sổ nhân sự HDS", "employees",
                                      f"COUNT={len(employees)}")],
        "state": next_state,
    }


def build(question, channel, client_id=None, dept_ids=None, is_banqt=False,
          can_finance=False, history=None):
    """Khối 'DỮ LIỆU CÔNG TY' để ghép vào prompt. Trả '' nếu không có gì liên quan.

    channel='public'  → luôn trả '' (khách lạ trên website, không đưa dữ liệu nào)
    channel='portal'  → chỉ đúng khách đang đăng nhập, không có ghi chú nội bộ,
                        không có file tổng hợp, không có công nợ
    channel='internal'→ nhận diện khách/vụ trong câu hỏi, kèm hồ sơ 360°, file
                        tổng hợp, và công nợ nếu người hỏi được cấp quyền;
                        thêm danh sách khách / quân số nhân sự / cảnh báo hạn
                        khi câu hỏi hướng về các nội dung đó
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
                # Câu hỏi tiếp ngắn gọn thì vay chủ đề của lượt trước, để nhận
                # diện chủ đề không bị rơi ở lượt thứ hai.
                topic = _topic_question(question, history)
                # Nhận diện KHÁCH chỉ vay 1 lượt gần nhất — trả lời bằng số liệu
                # của khách khác còn tệ hơn là không nhận ra khách nào.
                found = detect_clients(cur, _topic_question(question, history, turns=1),
                                       dept_ids, is_banqt)
                seen = {c[0] for c in found}
                for c in detect_clients_by_matter(cur, question, dept_ids, is_banqt):
                    if c[0] not in seen:
                        found.append(c)
                        seen.add(c[0])
                # Dùng CHỦ ĐỀ (đã vay lượt trước nếu là câu hỏi tiếp) cho mọi
                # nhận diện bên dưới — không dùng câu gốc, vì câu tiếp kiểu
                # "chi tiết từng cá nhân" tự nó không chứa từ khoá nào.
                q_folded = _fold(topic)

                # "Liệt kê khách kèm dịch vụ/chi tiết" mà không nêu tên khách cụ
                # thể: bung hồ sơ ĐẦY ĐỦ từng khách trong phạm vi (dịch vụ đã
                # dùng, vụ việc, tài liệu) — miễn là ít khách. Nhờ vậy bot mở
                # được thông tin bên trong thay vì chỉ đọc danh sách tên.
                expand_all = False
                if not found and _roster_intent(q_folded) and _detail_intent(q_folded):
                    # Chỉ cần biết có tối đa 5 khách hay nhiều hơn; không kéo
                    # toàn bộ danh mục về RAM cho câu "liệt kê kèm dịch vụ".
                    visible = _visible_clients(cur, dept_ids, is_banqt,
                                               limit=ROSTER_DETAIL_MAX + 1)
                    if visible and len(visible) <= ROSTER_DETAIL_MAX:
                        found = visible
                        expand_all = True

                cap = ROSTER_DETAIL_MAX if expand_all else MAX_CLIENTS
                picked = found[:cap]
                want_detail = _detail_intent(q_folded)
                blocks = [_client_lines(cur, cid, name, code, internal=True,
                                       can_finance=can_finance, share=len(picked),
                                       detail=want_detail)
                          for cid, name, code in picked]
                # Danh sách tên thu gọn: chỉ thêm khi câu roster mà KHÔNG bung
                # chi tiết (câu đếm thuần, hoặc quá nhiều khách để bung).
                if _roster_intent(q_folded) and not expand_all:
                    blocks.append(_roster_block(cur, dept_ids, is_banqt))
                if _staff_intent(q_folded):
                    blocks.append(_staff_block(cur, is_banqt))
                if _alert_intent(q_folded):
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
