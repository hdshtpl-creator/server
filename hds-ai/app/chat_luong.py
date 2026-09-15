"""Đo mức ĐỌC ĐƯỢC của văn bản đã trích xuất.

Vì sao cần: OCR bản scan mờ trả về chuỗi ký tự vụn kiểu
"R34»: 2] %4tiR # 11 : #k ‡UU3*" — vẫn là chữ Latin, vẫn có dấu tiếng Việt,
nên đếm "ký tự lạ" KHÔNG bắt được (mẫu rác thật chỉ có 1% ký tự ngoài Latin).
Thứ hỏng là CẤU TRÚC ÂM TIẾT: tiếng Việt ràng buộc rất chặt
(phụ âm đầu)(nguyên âm)(phụ âm cuối), nên "sục" hợp lệ còn "NNUÊ", "R34",
"otciiN" thì không.

Hàm public: ty_le_rac(text) -> float trong [0,1]. Thuần, không chạm CSDL.

Cố ý NHẬN NHẦM THEO HƯỚNG AN TOÀN: từ tiếng Anh ("Republic", "People")
bị tính là rác. Tài liệu song ngữ vì thế điểm cao hơn thực chất và ở lại hàng
chờ người duyệt — sai về phía bắt người nhìn, không phải về phía tự duyệt
bừa một file không đọc nổi.
"""
import re
import unicodedata

# Phụ âm đầu tiếng Việt (kể cả rỗng: "ăn", "ông"). Thử từ dài tới ngắn.
PHU_AM_DAU = ["ngh", "ng", "nh", "ch", "gh", "gi", "kh", "ph", "qu", "th", "tr",
              "b", "c", "d", "đ", "g", "h", "k", "l", "m", "n", "p", "r", "s",
              "t", "v", "x", ""]
# Phụ âm cuối. Rỗng cũng hợp lệ ("ba", "mẹ").
PHU_AM_CUOI = ["ngh", "ng", "nh", "ch", "c", "m", "n", "p", "t", ""]
# Nguyên âm SAU KHI BỎ DẤU: ă â → a, ê → e, ô ơ → o, ư → u.
NGUYEN_AM_GOC = set("aeiouy")
# Vần dài nhất trong tiếng Việt là ba nguyên âm ("uyê" trong "nguyện",
# "oai" trong "ngoại", "ươi" trong "người").
TOI_DA_NGUYEN_AM = 3
# Viết tắt toàn chữ hoa (TNHH, UBND, HĐQT, CP) không theo luật âm tiết.
TOI_DA_VIET_TAT = 6

# Tách token: mọi thứ không phải chữ/số đều là ranh giới, trừ dấu nối trong
# số hiệu văn bản ("67/VBHN-VPQH") — xử lý riêng ở _la_so_hieu.
_TACH = re.compile(r"[^0-9A-Za-zÀ-ỹĐđ/.\-]+")


def _bo_dau(ch: str) -> str:
    """'ắ' → 'a', 'ế' → 'e', 'ư' → 'u'. 'đ' không tách được nên giữ nguyên."""
    return unicodedata.normalize("NFD", ch)[0]


def _la_chu_cai(ch: str) -> bool:
    return unicodedata.name(ch, "").startswith("LATIN")


def _la_nguyen_am(ch: str) -> bool:
    return _bo_dau(ch) in NGUYEN_AM_GOC


def la_am_tiet(tu: str) -> bool:
    """Chuỗi chữ cái này có phải một âm tiết tiếng Việt hợp lệ không."""
    s = tu.lower()
    if not s or not all(_la_chu_cai(c) for c in s):
        return False
    for dau in PHU_AM_DAU:
        if not s.startswith(dau):
            continue
        con_lai = s[len(dau):]
        if not con_lai:
            continue
        for cuoi in PHU_AM_CUOI:
            if cuoi and not con_lai.endswith(cuoi):
                continue
            van = con_lai[:len(con_lai) - len(cuoi)] if cuoi else con_lai
            if not van or len(van) > TOI_DA_NGUYEN_AM:
                continue
            if all(_la_nguyen_am(c) for c in van):
                return True
    return False


def _la_so(tu: str) -> bool:
    """'2026', '1.234.567', '15/2026', '31-12' — con số và ngày tháng."""
    loi = tu.strip(".-/")
    return bool(loi) and all(c.isdigit() or c in ".-/" for c in loi) and any(
        c.isdigit() for c in loi)


def _la_so_hieu(tu: str) -> bool:
    """Số hiệu văn bản: '67/VBHN-VPQH', '15/2026/NĐ-CP'. Có dấu phân cách,
    các mảnh là số hoặc cụm chữ HOA."""
    if not any(c in "/-" for c in tu) or not any(c.isdigit() for c in tu):
        return False
    # Mảnh hợp lệ: toàn số ('2019') hoặc cụm chữ HOA có thể kèm số ('QH14',
    # 'NĐ', 'VPQH'). isupper() bỏ qua chữ số nên 'QH14' vẫn là True.
    manh = [m for m in re.split(r"[/-]", tu) if m]
    return bool(manh) and all(m.isdigit() or m.isupper() for m in manh)


def _la_viet_tat(tu: str) -> bool:
    return (tu.isupper() and len(tu) <= TOI_DA_VIET_TAT
            and all(_la_chu_cai(c) for c in tu))


def token_doc_duoc(tu: str) -> bool:
    """Một token có đáng tin là chữ thật không."""
    tu = tu.strip(".-/")
    if not tu:
        return False
    if _la_so(tu) or _la_so_hieu(tu) or _la_viet_tat(tu):
        return True
    if all(_la_chu_cai(c) for c in tu):
        return la_am_tiet(tu)
    return False


def ty_le_rac(text: str) -> float:
    """Phần token KHÔNG đọc được, trong [0,1]. Văn bản rỗng coi như rác hoàn
    toàn (1.0): không có chữ nào thì không có gì để duyệt."""
    tokens = [t for t in _TACH.split(text or "") if t.strip(".-/")]
    if not tokens:
        return 1.0
    hong = sum(1 for t in tokens if not token_doc_duoc(t))
    return hong / len(tokens)
