"""autofill.py — Bóc thông tin cá nhân từ hồ sơ (CCCD, sơ yếu lý lịch, CV).

Phục vụ nút "Tự điền từ hồ sơ" ở tab Soạn tài liệu: người dùng tải một file
(PDF/ảnh/DOCX), hệ thống trích văn bản (kể cả OCR), rồi các hàm ở đây đọc ra
những trường định danh — họ tên, ngày sinh, số CCCD, địa chỉ… — để điền sẵn
vào ``input_data`` của bản nháp thay vì bắt người dùng gõ tay từng ô.

Nguyên tắc:
  · CHỈ dùng regex, không gọi LLM: giá trị bóc ra phải truy vết được về đúng
    dòng chữ trong hồ sơ. Trường bóc thiếu thì để trống — chỗ trống sẽ thành
    [CẦN BỔ SUNG] trong bản nháp, đúng cơ chế an toàn sẵn có; còn một trường
    do model "đoán" thì không ai phát hiện được cho tới khi hợp đồng đã ký.
  · Chịu được chữ OCR: nhãn mất dấu ("Ho va ten"), nhãn song ngữ trên CCCD
    ("Họ và tên / Full name"), giá trị nằm cuối dòng hoặc RỚT xuống dòng sau.
  · Người dùng luôn thấy và sửa được kết quả trước khi sinh bản nháp — đây là
    gợi ý điền sẵn, không phải nguồn sự thật.
"""
from __future__ import annotations

import re

# Chữ cái không dấu → lớp ký tự khớp mọi biến thể có dấu. Nhờ đó một nhãn viết
# "ho va ten" khớp được cả "Họ và tên" (bản gõ chuẩn) lẫn "Ho va ten" (OCR mất
# dấu) mà không phải liệt kê từng biến thể.
_VARIANTS = {
    "a": "aàáảãạăằắẳẵặâầấẩẫậ",
    "d": "dđ",
    "e": "eèéẻẽẹêềếểễệ",
    "i": "iìíỉĩị",
    "o": "oòóỏõọôồốổỗộơờớởỡợ",
    "u": "uùúủũụưừứửữự",
    "y": "yỳýỷỹỵ",
}


def _label_pattern(label: str) -> str:
    """'ho va ten' → regex khớp nguyên cụm với mọi dấu và mọi hoa/thường."""
    out = []
    for ch in label:
        if ch == " ":
            out.append(r"[ \t]+")
        elif ch in _VARIANTS:
            variants = _VARIANTS[ch]
            out.append(f"[{variants}{variants.upper()}]")
        elif ch.isalpha():
            out.append(f"[{ch}{ch.upper()}]")
        else:
            out.append(re.escape(ch))
    return "".join(out)


# (khoá, [các nhãn nhận diện — KHÔNG dấu, nhãn dài đứng trước], kiểu giá trị)
# Khoá đặt theo quy ước input_data sẵn có (ho_ten, chuc_danh… như sổ nhân sự).
_FIELD_SPECS = [
    ("ho_ten", ["ho, chu dem va ten khai sinh", "ho chu dem va ten khai sinh",
                "ho va ten khai sinh", "ho va ten", "ho ten", "full name"], "name"),
    ("ngay_sinh", ["ngay, thang, nam sinh", "ngay thang nam sinh", "ngay sinh",
                   "sinh ngay", "date of birth"], "date"),
    ("gioi_tinh", ["gioi tinh", "sex"], "gender"),
    ("quoc_tich", ["quoc tich", "nationality"], "line"),
    ("dan_toc", ["dan toc"], "line"),
    ("ton_giao", ["ton giao"], "line"),
    ("so_cccd", ["so can cuoc cong dan", "can cuoc cong dan so",
                 "so dinh danh ca nhan", "so cccd", "cccd so", "so can cuoc",
                 "so cmnd", "cmnd so", "cccd", "cmnd", "so / no", "so/no"], "id"),
    ("ngay_cap", ["ngay cap", "cap ngay", "date of issue"], "date"),
    ("noi_cap", ["noi cap", "place of issue"], "line"),
    ("gia_tri_den", ["co gia tri den", "gia tri den", "date of expiry"], "date"),
    ("que_quan", ["que quan", "nguyen quan", "place of origin"], "line"),
    ("noi_thuong_tru", ["noi thuong tru", "dia chi thuong tru",
                        "ho khau thuong tru", "noi cu tru",
                        "place of residence"], "line"),
    ("cho_o_hien_nay", ["noi o hien nay", "cho o hien nay", "cho o hien tai",
                        "dia chi hien nay", "dia chi lien he"], "line"),
    ("dien_thoai", ["so dien thoai", "dien thoai", "sdt", "di dong",
                    "phone", "mobile"], "phone"),
    ("email", ["e-mail", "email", "thu dien tu"], "email"),
    ("trinh_do", ["trinh do chuyen mon", "trinh do hoc van",
                  "trinh do van hoa", "hoc van"], "line"),
    ("chuc_danh", ["chuc danh", "chuc vu", "vi tri ung tuyen"], "line"),
]

# Nhãn hiển thị trên giao diện cho từng khoá.
FIELD_LABELS = {
    "ho_ten": "Họ và tên", "ngay_sinh": "Ngày sinh", "gioi_tinh": "Giới tính",
    "quoc_tich": "Quốc tịch", "dan_toc": "Dân tộc", "ton_giao": "Tôn giáo",
    "so_cccd": "Số CCCD/CMND", "ngay_cap": "Ngày cấp", "noi_cap": "Nơi cấp",
    "gia_tri_den": "Có giá trị đến", "que_quan": "Quê quán",
    "noi_thuong_tru": "Nơi thường trú", "cho_o_hien_nay": "Chỗ ở hiện nay",
    "dien_thoai": "Số điện thoại", "email": "Email",
    "trinh_do": "Trình độ", "chuc_danh": "Chức danh / Vị trí",
}

# Nhãn ở đầu dòng: cho phép vài ký tự trang trí trước ("- ", "1. ", "• ") và
# bắt buộc ranh giới từ sau nhãn để "so" không khớp giữa chữ "sơ yếu".
_COMPILED = [
    (key, [re.compile(r"^[\d\W]{0,6}" + _label_pattern(lbl) + r"(?![\wà-ỹÀ-Ỹ])(?P<rest>.*)$")
           for lbl in labels], kind)
    for key, labels, kind in _FIELD_SPECS
]
_ALL_LABEL_RES = [regex for _, regexes, _ in _COMPILED for regex in regexes]

# Nhãn GIỮA DÒNG cho lượt vét: giấy tờ hay in nhiều trường trên cùng một dòng
# ("Giới tính: Nữ    Quốc tịch: Việt Nam"), lượt đầu chỉ bắt được trường đứng
# đầu dòng. Ranh giới từ hai phía để "nam" trong "Việt Nam" không thành nhãn.
_FLOATING = [
    (key, [re.compile(r"(?<![\wà-ỹÀ-Ỹ])" + _label_pattern(lbl)
                      + r"(?![\wà-ỹÀ-Ỹ])(?P<rest>[^\n]*)")
           for lbl in labels], kind)
    for key, labels, kind in _FIELD_SPECS
]
_ALL_FLOATING_RES = [regex for _, regexes, _ in _FLOATING for regex in regexes]


def _truncate_at_next_label(rest: str) -> str:
    """Cắt giá trị trước nhãn KẾ TIẾP trên cùng dòng (nếu có)."""
    cut = len(rest)
    for regex in _ALL_FLOATING_RES:
        match = regex.search(rest)
        if match and 0 < match.start() < cut:
            cut = match.start()
    if cut < len(rest):
        # Bỏ luôn số thứ tự của trường kế còn dính lại ("Kinh    7." → "Kinh").
        return re.sub(r"\s+\d{1,2}[.)]\s*$", "", rest[:cut])
    return rest

_DATE_RE = re.compile(r"(\d{1,2})\s?[/.\-]\s?(\d{1,2})\s?[/.\-]\s?(\d{4})")
_DATE_WORDS_RE = re.compile(
    _label_pattern("ngay") + r"\s+(\d{1,2})\s+" + _label_pattern("thang")
    + r"\s+(\d{1,2})\s+" + _label_pattern("nam") + r"\s+(\d{4})")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(r"(?:\+?84|0)(?:[ .\-]?\d){8,10}\b")
_ID_RUN_RE = re.compile(r"\d(?:[ .]?\d){8,11}")


def _strip_bilingual(rest: str) -> str:
    """Bỏ nhãn tiếng Anh đi kèm trên CCCD ("/ Full name:") và dấu phân cách."""
    rest = re.sub(r"^\s*/\s*[A-Za-z ,.'\-]{0,40}?[:.]", "", rest)
    return rest.strip(" \t:.-—–|")


def _valid_date(day: str, month: str, year: str) -> str | None:
    d, m, y = int(day), int(month), int(year)
    if not (1 <= d <= 31 and 1 <= m <= 12 and 1900 <= y <= 2100):
        return None
    return f"{d:02d}/{m:02d}/{y}"


def _find_date(candidates: list[str]) -> str | None:
    for text in candidates:
        match = _DATE_RE.search(text)
        if match:
            value = _valid_date(*match.groups())
            if value:
                return value
        match = _DATE_WORDS_RE.search(text)
        if match:
            value = _valid_date(*match.groups())
            if value:
                return value
    return None


def _extract_name(candidates: list[str]) -> str | None:
    """Chuỗi tên người hợp lệ trong các dòng ứng viên.

    Tên trên giấy tờ Việt Nam viết hoa chữ đầu từng từ (CCCD in hoa toàn bộ),
    nên một "run" tên là dãy 2–6 từ toàn chữ cái, từ nào cũng mở đầu bằng chữ
    hoa. Ưu tiên run IN HOA toàn bộ (kiểu CCCD) vì đó gần như chắc chắn là tên.
    """
    for text in candidates:
        runs: list[list[str]] = []
        current: list[str] = []
        for token in text.split():
            core = token.strip(",.;:()[]{}|/")
            if core and core.isalpha() and len(core) <= 12 and core[:1].isupper():
                current.append(core)
            else:
                if current:
                    runs.append(current)
                current = []
        if current:
            runs.append(current)
        runs = [run for run in runs if 2 <= len(run) <= 6]
        if not runs:
            continue
        upper = [run for run in runs if all(t == t.upper() for t in run)]
        return " ".join((upper or runs)[0])
    return None


def _extract_gender(candidates: list[str]) -> str | None:
    for text in candidates:
        folded = text.lower()
        if re.search(r"\bn[ữu]\b", folded):
            return "Nữ"
        if re.search(r"\bnam\b", folded):
            return "Nam"
    return None


def _extract_id(candidates: list[str]) -> str | None:
    """Số CCCD (12 số) hoặc CMND (9 số); chịu được OCR chèn khoảng trắng."""
    for text in candidates:
        for match in _ID_RUN_RE.finditer(text):
            digits = re.sub(r"\D", "", match.group(0))
            if len(digits) in (12, 9):
                return digits
    return None


def _extract_phone(candidates: list[str]) -> str | None:
    for text in candidates:
        match = _PHONE_RE.search(text)
        if match:
            digits = re.sub(r"\D", "", match.group(0))
            if digits.startswith("84"):
                digits = "0" + digits[2:]
            if len(digits) in (10, 11):
                return digits
    return None


def _extract_email(candidates: list[str]) -> str | None:
    for text in candidates:
        match = _EMAIL_RE.search(text)
        if match:
            return match.group(0).rstrip(".")
    return None


def _extract_line(candidates: list[str]) -> str | None:
    for text in candidates:
        value = " ".join(text.split()).strip(" :.-—–|,")
        # Giá trị quá dài gần như chắc chắn là cả một đoạn văn, không phải
        # một trường; bỏ để không nhét nguyên đoạn tiểu sử vào ô "Quê quán".
        if 1 < len(value) <= 120:
            return value
    return None


def _is_label_line(line: str) -> bool:
    return any(regex.match(line) for regex in _ALL_LABEL_RES)


_EXTRACTORS = {
    "name": _extract_name,
    "date": _find_date,
    "gender": _extract_gender,
    "id": _extract_id,
    "phone": _extract_phone,
    "email": _extract_email,
    "line": _extract_line,
}


def extract_person_fields(text: str) -> dict[str, str]:
    """Đọc các trường định danh từ văn bản hồ sơ. Chỉ trả trường TÌM THẤY."""
    lines = [ln.strip() for ln in (text or "").splitlines()]
    lines = [ln for ln in lines if ln]
    found: dict[str, str] = {}

    for index, line in enumerate(lines):
        # Dòng quá dài là đoạn văn xuôi — nhãn trường luôn nằm ở dòng ngắn.
        if len(line) > 160:
            continue
        for key, regexes, kind in _COMPILED:
            if key in found:
                continue
            for regex in regexes:
                match = regex.match(line)
                if not match:
                    continue
                rest = _truncate_at_next_label(_strip_bilingual(match.group("rest")))
                rest = rest.strip(" \t:.-—–|,")
                candidates = [rest] if rest else []
                # CCCD hay in giá trị Ở DÒNG DƯỚI nhãn — lấy thêm tối đa hai
                # dòng kế, trừ khi dòng đó lại là nhãn của trường khác.
                for offset in (1, 2):
                    if index + offset < len(lines):
                        nxt = lines[index + offset]
                        if not _is_label_line(nxt):
                            candidates.append(nxt)
                value = _EXTRACTORS[kind](candidates)
                if value:
                    found[key] = value
                break  # nhãn đầu tiên khớp là đủ cho trường này

    # Lượt vét GIỮA DÒNG cho các trường còn thiếu: "Giới tính: Nữ  Quốc tịch:
    # Việt Nam" chỉ cho lượt đầu bắt được trường đứng đầu dòng.
    for line in lines:
        if len(line) > 160:
            continue
        for key, regexes, kind in _FLOATING:
            if key in found:
                continue
            for regex in regexes:
                match = regex.search(line)
                if not match:
                    continue
                rest = _truncate_at_next_label(_strip_bilingual(match.group("rest")))
                value = _EXTRACTORS[kind]([rest] if rest.strip() else [])
                if value:
                    found[key] = value
                break

    # Không dòng nào mang nhãn số CCCD (ảnh OCR mất chữ nhãn) — vớt bằng dãy
    # 12 số đứng riêng, nhưng CHỈ trên văn bản ngắn cỡ một tấm thẻ: trong hợp
    # đồng/hồ sơ dài, dãy 12 số có thể là số tài khoản hay mã bất kỳ.
    if "so_cccd" not in found and len(text or "") <= 2000:
        for match in re.finditer(r"(?<!\d)\d{12}(?!\d)", text or ""):
            found["so_cccd"] = match.group(0)
            break
    return found


def merge_missing(existing: dict | None, fields: dict[str, str]) -> dict:
    """Điền các trường bóc được vào input_data, KHÔNG đè thứ người dùng đã gõ."""
    out = dict(existing or {})
    for key, value in (fields or {}).items():
        if out.get(key) in (None, "", []):
            out[key] = value
    return out
