"""van_ban.py — Danh tính và quan hệ của VĂN BẢN QUY PHẠM PHÁP LUẬT.

Với hãng luật, hai câu hỏi phải trả lời được về BẤT KỲ văn bản nào trong kho:

1. **Nó là gì?** — loại văn bản, số hiệu, trích yếu (tên đầy đủ), ngày ban
   hành, ngày hiệu lực. Trước module này, kho chỉ biết tên file.
2. **Nó liên hệ thế nào với các văn bản khác?** — thay thế ai, bị ai thay thế,
   sửa đổi ai, hướng dẫn ai, căn cứ vào đâu. Trước module này, mỗi văn bản là
   một hòn đảo: luật 2012 đã chết và luật 2019 thay nó nằm cạnh nhau mà bộ tra
   cứu không phân biệt được — trả lời bằng luật chết mà mọi chốt kiểm đều
   xanh, vì nội dung trích đúng từng chữ.

NGUYÊN TẮC THIẾT KẾ:

- **Khoá bền là SỐ HIỆU, không phải documents.id.** Mỗi lần file được học lại,
  auto_learn XOÁ bản ghi documents cũ rồi INSERT bản mới với id MỚI (xem
  learn_one). Bảng quan hệ khoá theo id sẽ bốc hơi im lặng sau mỗi lần sửa
  file; khoá theo số hiệu thì sống mãi. Đổi lại, muốn ra documents.id phải
  JOIN qua ``lower(so_hieu)`` lúc đọc — rẻ, đã có chỉ mục.
- **Bóc danh tính chỉ soi PHẦN ĐẦU** (cùng nguyên tắc với document_citation):
  thân văn bản đầy số hiệu của văn bản KHÁC do dẫn chiếu. Ngược lại, bóc
  QUAN HỆ phải đọc cả thân bài (điều khoản thi hành "thay thế Nghị định số…"
  nằm cuối văn bản) — nhưng phải bám vào CỤM ĐỘNG TỪ đi kèm, không được nhặt
  mọi số hiệu xuất hiện.
- **Bóc trượt không phải lỗi.** Văn bản không phải luật không có số hiệu —
  đó là chuyện bình thường. Mọi hàm ở đây trả None/rỗng khi không thấy,
  KHÔNG thêm warning vào extraction (warning làm safe_approved chặn duyệt
  tự động cả kho — xem chú thích ingest_file).
- **Máy chỉ đánh dấu chiều XẤU đi.** Tự động chỉ đặt 'het_hieu_luc' /
  'het_hieu_luc_mot_phan' khi có văn bản thay thế/sửa đổi NẰM TRONG KHO;
  không bao giờ tự khẳng định 'con_hieu_luc' — vắng bằng chứng không phải
  bằng chứng (nghị định bãi bỏ có thể đơn giản là chưa được đưa vào kho).
  'con_hieu_luc' chỉ do người duyệt đặt tay, và giá trị người đặt tay không
  bị máy ghi đè.

Hàm bóc là hàm THUẦN (chuỗi vào, dict ra) để test không cần CSDL; hàm ghi/đọc
nhận cursor từ bên gọi để module này không phải import app.db.
"""
import re
import unicodedata
from datetime import date

# Trạng thái hiệu lực — phải khớp CHECK constraint trong sql/schema.sql và
# EFFECT_STATUS trong frontend constants.ts.
TRANG_THAI_HIEU_LUC = (
    "chua_ro",                # mặc định: chưa kiểm tra được — nói thật, đừng đoán
    "con_hieu_luc",           # người duyệt xác nhận tay
    "het_hieu_luc_mot_phan",  # đã bị sửa đổi, bổ sung
    "het_hieu_luc",           # đã bị thay thế / bãi bỏ
)

# Loại quan hệ — chiều đọc: <văn bản nguồn> LOẠI <văn bản đích>.
# "A thay_the B" nghĩa là A thay thế B (B chết). Phải khớp CHECK constraint
# và RELATION_TYPES trong frontend.
LOAI_QUAN_HE = ("thay_the", "bai_bo", "sua_doi_bo_sung", "huong_dan",
                "hop_nhat", "can_cu", "lien_quan")

# Nhãn tiếng Việt dùng chung cho prompt/HTML — một nguồn sự thật.
LOAI_QUAN_HE_VN = {
    "thay_the": "thay thế",
    "bai_bo": "bãi bỏ",
    "sua_doi_bo_sung": "sửa đổi, bổ sung",
    "huong_dan": "quy định chi tiết / hướng dẫn",
    "hop_nhat": "hợp nhất",
    "can_cu": "căn cứ",
    "lien_quan": "liên quan",
}

# Loại văn bản, xếp DÀI TRƯỚC NGẮN để "BỘ LUẬT" không bị "LUẬT" ăn mất,
# "THÔNG TƯ LIÊN TỊCH" không bị "THÔNG TƯ" ăn mất. "BẢN ÁN" cho kệ 2.2:
# bản án cũng có số hiệu theo cùng khuôn (58/2023/HNG-ST) và cần trích
# dẫn được là "Bản án số …".
_LOAI = ("VĂN BẢN HỢP NHẤT", "BỘ LUẬT", "THÔNG TƯ LIÊN TỊCH", "PHÁP LỆNH",
         "NGHỊ ĐỊNH", "NGHỊ QUYẾT", "THÔNG TƯ", "QUYẾT ĐỊNH", "CHỈ THỊ",
         "CÔNG ĐIỆN", "CÔNG VĂN", "BẢN ÁN", "LUẬT")
_LOAI_RX = "|".join(re.escape(x) for x in _LOAI)

# Số hiệu văn bản QPPL: 45/2019/QH14, 15/2020/NĐ-CP, 01/2021/TT-BXD…
# Chừa \s* quanh dấu / cho chữ OCR bị giãn.
RE_SO_HIEU = re.compile(r"\b(\d{1,4}\s*/\s*\d{4}\s*/\s*[A-ZĐ][A-ZĐ0-9\-]*)")

_RE_NGAY_CHU = re.compile(r"ngày\s+(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(\d{4})",
                          re.IGNORECASE)
_RE_NGAY_SO = re.compile(r"ngày\s+(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})",
                         re.IGNORECASE)

# Số hiệu dạng KHÔNG có năm ở giữa: công văn (1234/BTC-TCT), quyết định cá biệt
# (05/QĐ-UBND). Chỉ nhận sau chữ "Số:" — dạng này quá lỏng để quét tự do.
_RE_SO_KHAC = re.compile(
    r"\bS[ốô]\s*:\s*(\d{1,5}\s*/\s*[A-ZĐ][A-ZĐ0-9\-]*(?:\s*/\s*[A-ZĐ][A-ZĐ0-9\-]*)?)")

# ---- Danh tính từ TÊN FILE ------------------------------------------------
# Bản .docx tải từ thuvienphapluat/chinhphu.vn thường KHÔNG có dòng "Số: …":
# phần đầu bắt đầu thẳng "NGHỊ ĐỊNH / Quy định chi tiết… / Căn cứ Luật … số
# 63/2025/QH15". Kiểm 65 văn bản trong kho 06/09/2026: 9/15 văn bản cốt lõi
# bóc từ chữ ra None, 2 bóc NHẦM số của văn bản dẫn chiếu, và nhãn đoạn cũ
# ghi "Nghị Định số 63/2025/QH15" cho Nghị định 96/2026 — bot dẫn sai số hiệu
# là chép đúng nhãn sai này. Tên file do người quản trị đặt ("Nghị-định-96-
# 2026-NĐ-CP", "58-2026-ND-CP_13022026") lại mang đúng số hiệu, đôi khi cả
# ngày ban hành — với văn bản luật, đó là nguồn danh tính đáng tin nhất.
_RE_TEN_FILE_SO = re.compile(
    r"(?<![\dA-Za-z])(\d{1,4})-(\d{4})-([A-ZĐ][A-ZĐ0-9]*(?:-[A-ZĐ][A-ZĐ0-9]*)*)")
# Số hiệu không có năm ở giữa: "09-CD-TTg_03022025", "67-VBHN-VPQH".
_RE_TEN_FILE_SO_KHONG_NAM = re.compile(
    r"(?<![\dA-Za-z])(\d{1,5})-([A-ZĐ]{2,}[A-ZĐ0-9]*(?:-[A-ZĐ][A-ZĐa-z0-9]*)*)(?=[_.\s]|$)")
_RE_TEN_FILE_NGAY = re.compile(r"_(\d{2})(\d{2})(\d{4})(?:\D|$)")
# Tên file gõ không dấu ("ND-CP") → ký hiệu chuẩn ("NĐ-CP") để khoá quan hệ
# khớp với số hiệu bóc từ chữ của văn bản khác.
_ASCII_SANG_DAU = {"ND": "NĐ", "QD": "QĐ", "CD": "CĐ", "HDTP": "HĐTP",
                   "HDND": "HĐND", "BKHDT": "BKHĐT", "BGDDT": "BGDĐT", "BTP": "BTP"}
_LOAI_TU_TIEN_TO = (("van ban hop nhat", "Văn bản hợp nhất"), ("bo luat", "Bộ luật"),
                    ("phap lenh", "Pháp lệnh"), ("nghi dinh", "Nghị định"),
                    ("thong tu lien tich", "Thông tư liên tịch"), ("thong tu", "Thông tư"),
                    ("nghi quyet", "Nghị quyết"), ("quyet dinh", "Quyết định"),
                    ("chi thi", "Chỉ thị"), ("cong dien", "Công điện"), ("luat", "Luật"))
_LOAI_TU_DUOI = (("VBHN", "Văn bản hợp nhất"), ("NĐ-CP", "Nghị định"), ("TTLT", "Thông tư liên tịch"),
                 ("TT-", "Thông tư"), ("NQ-", "Nghị quyết"), ("QĐ-", "Quyết định"),
                 ("CĐ-", "Công điện"), ("CT-", "Chỉ thị"), ("QH", "Luật"))


def _chuan_ky_hieu(ky_hieu: str) -> str:
    return "-".join(_ASCII_SANG_DAU.get(p, p) for p in ky_hieu.split("-"))


def danh_tinh_tu_ten_file(ten_file) -> dict:
    """{so_hieu, loai_van_ban, loai_tin_cay, ngay_ban_hanh} đọc từ tên file.

    Không đọc được thì mọi khoá là None — KHÔNG raise. `loai_tin_cay`:
    'tien_to' khi tên file mở đầu bằng loại ("Nghị-định-…"), 'duoi' khi chỉ
    đoán từ ký hiệu ("…-NĐ-CP"); tiền tố là người đặt tay, đáng tin hơn chữ
    trong văn bản; đuôi thì chỉ dùng khi chữ không nói gì.
    """
    out = {"so_hieu": None, "loai_van_ban": None, "loai_tin_cay": None,
           "ngay_ban_hanh": None}
    ten = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", (ten_file or "").strip())
    if not ten:
        return out
    m = _RE_TEN_FILE_SO.search(ten)
    if m:
        out["so_hieu"] = f"{m.group(1)}/{m.group(2)}/{_chuan_ky_hieu(m.group(3).upper())}"
    else:
        m = _RE_TEN_FILE_SO_KHONG_NAM.search(ten)
        if m:
            out["so_hieu"] = f"{m.group(1)}/{_chuan_ky_hieu(m.group(2))}"
    dau = _fold(ten).replace("-", " ").replace("_", " ")
    for tien_to, loai in _LOAI_TU_TIEN_TO:
        if dau.startswith(tien_to + " "):
            out["loai_van_ban"], out["loai_tin_cay"] = loai, "tien_to"
            break
    if not out["loai_van_ban"] and out["so_hieu"]:
        duoi = out["so_hieu"].split("/", 1)[1] if "/" in out["so_hieu"] else ""
        duoi = duoi.split("/", 1)[-1] if duoi[:4].isdigit() else duoi
        for ky, loai in _LOAI_TU_DUOI:
            if duoi.startswith(ky) or (ky == "QH" and re.match(r"QH\d", duoi)):
                out["loai_van_ban"], out["loai_tin_cay"] = loai, "duoi"
                break
    d = _RE_TEN_FILE_NGAY.search(ten)
    if d:
        out["ngay_ban_hanh"] = _lam_ngay(d.group(1), d.group(2), d.group(3))
    return out

# Dòng dẫn chiếu văn bản KHÁC — số hiệu trên các dòng này không bao giờ là số
# hiệu của chính văn bản đang đọc.
_DONG_DAN_CHIEU = re.compile(r"^\s*(Căn\s+cứ|Theo\s+đề\s+nghị|Xét\s+đề\s+nghị|"
                             r"Thực\s+hiện|Để\s+thực\s+hiện)\b", re.IGNORECASE)

HEAD_CHARS = 4000       # cùng cửa sổ với document_citation — danh tính nằm ở đầu

# Bộ đọc Word bọc đoạn kiểu Heading thành "[Mục: …]" (ingest._extract_docx).
# Bộ luật Dân sự .docx đặt TỪNG ĐIỀU là Heading → "[Mục: Điều 6. Áp dụng tương
# tự pháp luật]": bộ cắt theo Điều chỉ nhận 1/917 điều, cả Bộ luật thành 229
# mảnh vô danh mang nhãn "Điều 274 — phần k/229" (kiểm kho 06/09/2026). Với
# văn bản luật, nhãn Heading chỉ là cách trình bày — mở ra trước khi bóc/cắt.
_RE_NHAN_MUC_WORD = re.compile(r"^[ \t]*\[Mục:\s*(.+?)\]\s*$", re.MULTILINE | re.IGNORECASE)


def mo_nhan_muc(text: str) -> str:
    """'[Mục: Điều 6. Áp dụng tương tự pháp luật]' → 'Điều 6. Áp dụng tương tự pháp luật'."""
    return _RE_NHAN_MUC_WORD.sub(lambda m: m.group(1), text or "")


def chuan_hoa_so_hieu(so: str) -> str:
    """'45 / 2019 / qh14' → '45/2019/QH14' — khoá so khớp giữa các văn bản."""
    return re.sub(r"\s+", "", (so or "")).upper()


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.replace("đ", "d").replace("Đ", "D").lower()


def _lam_ngay(d, m, y):
    try:
        d, m, y = int(d), int(m), int(y)
        if not 1945 <= y <= 2100:
            return None
        return date(y, m, d)
    except ValueError:
        return None


def _tim_ngay(doan: str):
    """Ngày đầu tiên trong đoạn chữ, cả dạng chữ lẫn dạng số."""
    m = _RE_NGAY_CHU.search(doan) or _RE_NGAY_SO.search(doan)
    return _lam_ngay(*m.groups()) if m else None


def _dong_loai(head: str):
    """(vị trí, loại hiển thị, phần còn lại trên dòng) của DÒNG tiêu đề loại văn bản.

    Tiêu đề loại đứng ĐẦU DÒNG và viết hoa ("BỘ LUẬT LAO ĐỘNG", "NGHỊ ĐỊNH") —
    chặt hơn regex \\b của document_citation, để "Căn cứ Luật…" giữa dòng
    không bị nhận nhầm là tiêu đề.

    Lưới đỡ: bản trích xuất trình bày lạ (PDF một cột, OCR dồn dòng) không có
    dòng tiêu đề nào đứng riêng. Khi đó vẫn nhận loại từ giữa dòng — nhưng bỏ
    các dòng dẫn chiếu ("Căn cứ Luật…") và KHÔNG lấy trích yếu, vì vị trí dòng
    là thứ duy nhất cho biết đâu là trích yếu. Thiếu lưới này thì trích dẫn
    của cả văn bản cụt còn "số 15/2020/NĐ-CP" — thụt lùi so với bản trước.
    """
    m = re.search(rf"^[ \t]*({_LOAI_RX})\b[ \t]*([^\n]*)$", head, re.MULTILINE)
    if m:
        # "BỘ LUẬT" → "Bộ luật": chỉ hoa chữ đầu, không title-case từng từ.
        return m.start(), m.group(1).capitalize(), (m.group(2) or "").strip()
    for line in head.split("\n"):
        if _DONG_DAN_CHIEU.match(line):
            continue
        m = re.search(rf"\b({_LOAI_RX}|{_LOAI_THUONG_RX})\b", line, re.IGNORECASE)
        if m:
            return None, re.sub(r"\s+", " ", m.group(1)).capitalize(), None
    return None, None, None


_DUNG_TRICH_YEU = re.compile(
    r"^\s*(Căn cứ|Theo đề nghị|Quốc hội ban hành|Chính phủ ban hành|"
    r"Điều\s+\d|Chương\s+[IVXLCDM\d]|Số\s*:|_{3,}|-{3,})", re.IGNORECASE)


def boc_metadata(text: str, ten_file=None) -> dict:
    """Danh tính văn bản từ phần mở đầu + ngày hiệu lực từ điều khoản thi hành.

    Trả dict với các khoá: so_hieu, loai_van_ban, trich_yeu, ngay_ban_hanh,
    ngay_hieu_luc (date hoặc None). Không thấy gì thì mọi khoá là None —
    KHÔNG raise, KHÔNG warning.

    ``ten_file`` (nếu có) là nguồn danh tính ƯU TIÊN cho số hiệu: xem chú
    thích trên danh_tinh_tu_ten_file. Khi chữ trong văn bản nêu một số KHÁC
    (văn bản hợp nhất: chữ mang số của luật gốc, tên file mang số VBHN) thì
    số trong chữ giữ ở ``so_hieu_trong_van_ban`` để trích dẫn và ghi quan hệ
    hợp nhất.
    """
    text = mo_nhan_muc(text or "")
    head = text[:HEAD_CHARS]
    out = {"so_hieu": None, "loai_van_ban": None, "trich_yeu": None,
           "ngay_ban_hanh": None, "ngay_hieu_luc": None}

    # --- Số hiệu: ưu tiên dòng "Số: …" (chắc chắn là của CHÍNH văn bản). Bắt
    # buộc có dấu hai chấm: "Thông tư số 03/2021/TT-BKHĐT" giữa câu là văn bản
    # KHÁC được nhắc tới (ca thật: Thông tư 55/2026 bị gán số 03/2021). ---
    m = re.search(r"\bS[ốô]\s*:\s*(\d{1,4}\s*/\s*\d{4}\s*/\s*[A-ZĐ][A-ZĐ0-9\-]*)",
                  head)
    if not m:
        # Công văn / quyết định cá biệt không có năm ở giữa (1234/BTC-TCT).
        # Không có nhánh này thì văn bản như vậy rơi xuống lưới quét tự do và
        # vơ nhầm số hiệu ở dòng "Căn cứ Nghị định số …" — tức ghi số hiệu của
        # MỘT VĂN BẢN KHÁC vào chính nó, mà quan hệ lại khoá theo số hiệu.
        m = _RE_SO_KHAC.search(head)
    if not m:
        # Lưới cuối: quét tự do nhưng BỎ các dòng dẫn chiếu, và chỉ nhận số
        # đứng GẦN ĐẦU DÒNG (dòng tiêu đề "Luật Doanh nghiệp số 59/2020/QH14").
        # Số nằm sâu trong câu ("Thông tư này thay thế Thông tư số 03/2021/…")
        # là văn bản KHÁC — ca thật 06/09/2026: Thông tư 55/2026 bị gán số
        # 03/2021/TT-BKHĐT của thông tư nó thay thế.
        for line in head.split("\n"):
            if _DONG_DAN_CHIEU.match(line):
                continue
            m = RE_SO_HIEU.search(line)
            if not m:
                continue
            truoc = _c(line[:m.start()])
            if m.start() > 25 or re.search(r"thay thế|bãi bỏ|sửa đổi|hướng dẫn|hợp nhất",
                                           truoc):
                m = None
                continue
            break
    if m:
        out["so_hieu"] = chuan_hoa_so_hieu(m.group(1))

    # --- Loại + trích yếu: dòng tiêu đề loại và (các) dòng ngay sau nó ---
    vi_tri, loai, cung_dong = _dong_loai(head)
    if loai:
        out["loai_van_ban"] = loai
        dong_sau = []
        # Số hiệu hay nằm CÙNG DÒNG tiêu đề ("NGHỊ ĐỊNH số 145/2020/NĐ-CP") —
        # bỏ nó ra khỏi trích yếu, không thì trích dẫn thành "Nghị định số
        # 145/2020/NĐ-CP số 145/2020/NĐ-CP".
        if cung_dong:
            cung_dong = RE_SO_HIEU.sub("", cung_dong)
            cung_dong = re.sub(r"\bs[ốô]\s*:?\s*$", "", cung_dong.strip(),
                               flags=re.IGNORECASE).strip(" -–—:,.")
        if cung_dong and not _DUNG_TRICH_YEU.match(cung_dong):
            dong_sau.append(cung_dong)
        elif vi_tri is None:
            pass          # nhận loại từ giữa dòng: vị trí dòng không đáng tin
        else:
            for line in head[vi_tri:].split("\n")[1:6]:
                line = line.strip()
                if not line:
                    if dong_sau:
                        break               # hết khối trích yếu
                    continue
                if _DUNG_TRICH_YEU.match(line) or RE_SO_HIEU.search(line):
                    break
                dong_sau.append(line)
                if sum(len(x) for x in dong_sau) > 220:
                    break
        trich_yeu = re.sub(r"\s+", " ", " ".join(dong_sau)).strip(" .")
        if trich_yeu:
            # "LAO ĐỘNG" → "Lao động"; trích yếu thường (mixed-case) giữ nguyên.
            if trich_yeu.isupper():
                trich_yeu = trich_yeu.capitalize()
            out["trich_yeu"] = trich_yeu[:300]

    # --- Ngày ban hành ---
    # Ưu tiên 1: ngày đi LIỀN SAU số hiệu của chính văn bản ("Bản án số:
    # 58/2023/HNGĐ-ST. Ngày: 29/9/2023") — đây là dạng của bản án/quyết định.
    if out["so_hieu"] and m:
        ke_ben = head[m.end():m.end() + 90]
        d = re.search(r"[Nn]gày\s*:?\s*(?:(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(\d{4})"
                      r"|(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4}))", ke_ben)
        if d:
            g = [x for x in d.groups() if x]
            out["ngay_ban_hanh"] = _lam_ngay(*g)
    # Ưu tiên 2: DÒNG ĐỊA DANH của văn bản QPPL — "Hà Nội, ngày 20 tháng 11
    # năm 2019" đứng một mình trên dòng. Soi theo dòng chứ không quét cả khối:
    # dấu phẩy giữa câu có ở khắp nơi, và một câu dẫn chiếu như "…Quyết định
    # hoãn phiên toà số 37/2023/QĐST-HNGĐ, ngày 25/8/2023" cũng khớp — tức lấy
    # ngày của MỘT VĂN BẢN KHÁC làm ngày ban hành của chính mình (ca thật trên
    # bản án 58/2023/HNGĐ-ST).
    if not out["ngay_ban_hanh"]:
        for line in head.split("\n"):
            d = re.match(r"^\s*[^\d,\n]{2,50},\s*"
                         r"(?:ngày\s+(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(\d{4})"
                         r"|ngày\s+(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4}))"
                         r"\s*\.?\s*$", line, re.IGNORECASE)
            if d:
                out["ngay_ban_hanh"] = _lam_ngay(*[x for x in d.groups() if x])
                break

    # --- Ngày hiệu lực: "… này có hiệu lực (thi hành) (kể) từ ngày …" —
    # nằm ở điều khoản thi hành cuối văn bản. Ưu tiên câu có chữ "này"
    # (nói về CHÍNH văn bản); không có thì lấy câu nằm ở nửa sau văn bản. ---
    ung_vien = []
    for m in re.finditer(
            r"có\s+hiệu\s+lực(?:\s+thi\s+hành)?(?:\s+kể)?\s+từ\s+ngày\s+"
            r"((?:\d{1,2}\s+tháng\s+\d{1,2}\s+năm\s+\d{4})|(?:\d{1,2}[/.\-]\d{1,2}[/.\-]\d{4}))",
            text, re.IGNORECASE):
        ngay = _tim_ngay("ngày " + m.group(1))
        if not ngay:
            continue
        co_nay = "này" in _c(text[max(0, m.start() - 50):m.start()])
        ung_vien.append((co_nay, m.start(), ngay))
    for co_nay, pos, ngay in ung_vien:
        if co_nay:
            out["ngay_hieu_luc"] = ngay
            break
    else:
        for co_nay, pos, ngay in ung_vien:
            if pos > len(text) * 0.5:
                out["ngay_hieu_luc"] = ngay
                break

    # --- Tên file: số hiệu thắng chữ; loại thắng khi là tiền tố đặt tay hoặc
    # khi chữ chỉ đoán được giữa dòng; ngày ban hành bù khi chữ không có. ---
    tf = danh_tinh_tu_ten_file(ten_file)
    if tf["so_hieu"]:
        if out["so_hieu"] and out["so_hieu"] != tf["so_hieu"]:
            out["so_hieu_trong_van_ban"] = out["so_hieu"]
        out["so_hieu"] = tf["so_hieu"]
    if tf["loai_van_ban"]:
        hop_nhat = tf["loai_van_ban"] == "Văn bản hợp nhất"
        if hop_nhat:
            # Loại hiển thị vẫn là loại của văn bản gốc ("Luật Doanh nghiệp…"),
            # chỉ đánh dấu để trích dẫn ghi thêm "(văn bản hợp nhất …)".
            out["hop_nhat"] = True
            if not out["loai_van_ban"]:
                out["loai_van_ban"] = tf["loai_van_ban"]
        elif (not out["loai_van_ban"] or tf["loai_tin_cay"] == "tien_to"
              or vi_tri is None):
            out["loai_van_ban"] = tf["loai_van_ban"]
    if not out["ngay_ban_hanh"] and tf["ngay_ban_hanh"]:
        out["ngay_ban_hanh"] = tf["ngay_ban_hanh"]
    return out


def _c(s: str) -> str:
    """Hạ chuẩn NFC để 'này' gõ kiểu telex/VNI đều so được."""
    return unicodedata.normalize("NFC", s or "").lower()


def _phan_so_hieu(meta: dict, so_hieu=None) -> list:
    """Phần số hiệu của tên/trích dẫn. Văn bản hợp nhất: số của văn bản gốc
    đứng trước, số VBHN trong ngoặc — đúng cách luật sư dẫn ("Luật Doanh
    nghiệp số 59/2020/QH14 (văn bản hợp nhất 67/VBHN-VPQH)")."""
    so = so_hieu or meta.get("so_hieu")
    goc = meta.get("so_hieu_trong_van_ban")
    if goc and so and goc != so:
        return ["số " + goc, f"(văn bản hợp nhất {so})"]
    if meta.get("hop_nhat") and so:
        return [f"(văn bản hợp nhất {so})"]
    return ["số " + so] if so else []


def trich_dan(text: str, ten_file=None) -> str:
    """Trích dẫn đầy đủ theo chuẩn hành nghề: 'Bộ luật Lao động số 45/2019/QH14'.

    Đây là chuỗi được gắn vào TỪNG đoạn (nằm trong content, được embed) — vì
    vậy trích yếu quá dài (nghị định 'quy định chi tiết một số điều của…')
    thì lược khỏi trích dẫn, chỉ giữ loại + số; tên đầy đủ vẫn nằm ở
    documents.trich_yeu và đoạn mở đầu.

    Trả CHUỖI RỖNG khi không đọc được loại văn bản, để bên gọi
    (ingest.document_citation) còn dùng lưới đỡ cũ: một trích dẫn cụt kiểu
    "số 15/2020/NĐ-CP" trông như có kết quả nhưng lại chặn mất đường lùi.
    """
    meta = boc_metadata(text, ten_file=ten_file)
    if not meta["loai_van_ban"]:
        return ""
    parts = [meta["loai_van_ban"]]
    if meta["trich_yeu"] and len(meta["trich_yeu"]) <= 60:
        parts.append(meta["trich_yeu"])
    parts += _phan_so_hieu(meta)
    return " ".join(parts).strip()


def ten_day_du(meta: dict, so_hieu=None) -> str:
    """Tên hiển thị đầy đủ từ metadata: 'Nghị định quy định chi tiết… số 15/2020/NĐ-CP'."""
    parts = []
    if meta.get("loai_van_ban"):
        parts.append(meta["loai_van_ban"])
    if meta.get("trich_yeu"):
        parts.append(meta["trich_yeu"])
    parts += _phan_so_hieu(meta, so_hieu)
    return " ".join(parts).strip()


# ---------------------------------------------------------------------------
# Quan hệ giữa các văn bản
# ---------------------------------------------------------------------------
_LOAI_THUONG_RX = (r"(?:Bộ\s+luật|Luật|Pháp\s+lệnh|Nghị\s+định|Nghị\s+quyết|"
                   r"Thông\s+tư\s+liên\s+tịch|Thông\s+tư|Quyết\s+định|"
                   r"Chỉ\s+thị|Hiến\s+pháp|Văn\s+bản\s+hợp\s+nhất)")

# Cửa sổ chữ sau một cụm mốc — đủ ôm danh sách "các Nghị định số A, số B và
# số C ngày …", nhưng không tràn sang câu sau.
_CUA_SO = 400


def _cat_cau(doan: str) -> str:
    """Cắt đoạn tại điểm kết câu đầu tiên ('. ', xuống dòng đôi, hoặc dòng dẫn chiếu).

    Dòng "Căn cứ …" mở một mệnh đề mới: không cắt ở đó thì cụm "hướng dẫn thuế"
    ở trích yếu vơ luôn số hiệu của dòng "Căn cứ Nghị định số …" ngay dưới.
    """
    m = re.search(r"\.\s+[A-ZĐ0-9]|\n\s*\n"
                  r"|\n\s*(?:Căn\s+cứ|Theo\s+đề\s+nghị|Xét\s+đề\s+nghị)\b",
                  doan, re.IGNORECASE)
    return doan[:m.start() + 1] if m else doan


def _so_hieu_trong(doan: str, bo_qua=None) -> list:
    bo_qua = chuan_hoa_so_hieu(bo_qua or "")
    ra, seen = [], set()
    for m in RE_SO_HIEU.finditer(doan):
        so = chuan_hoa_so_hieu(m.group(1))
        if so and so != bo_qua and so not in seen:
            seen.add(so)
            ra.append(so)
    return ra


def _ten_dich_trong(doan: str):
    """Tên văn bản đích khi câu không nêu số hiệu ('…của Luật Xây dựng')."""
    m = re.match(rf"\s*({_LOAI_THUONG_RX}[^,;.\n(]{{0,90}}?)"
                 rf"(?=\s+ngày|\s+số|\s*[,;.(\n]|$)", doan, re.IGNORECASE)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else None


def boc_quan_he(text: str, so_hieu_minh=None) -> list:
    """Quan hệ mà VĂN BẢN NÀY tuyên bố với văn bản khác, bóc từ chính lời văn.

    Trả list dict {loai, so_hieu_dich, ten_dich} — so_hieu_dich có thể None
    khi văn bản đích chỉ được nêu tên ("Căn cứ Luật Tổ chức Chính phủ ngày…").
    Ưu tiên quan hệ mạnh: một văn bản vừa bị "thay thế" vừa xuất hiện ở dòng
    "Căn cứ" thì chỉ giữ thay_the.

    Bẫy đã lường: thân văn bản đầy số hiệu DẪN CHIẾU vô hại — chỉ số hiệu
    đứng trong cửa sổ ngay sau cụm động từ ("thay thế", "bãi bỏ", "sửa đổi,
    bổ sung một số điều của…") và có TÊN LOẠI văn bản đứng trước mới được nhặt.
    """
    text = mo_nhan_muc(text or "")
    head = text[:HEAD_CHARS]
    ra, da_co = [], set()

    def them(loai, so_dich=None, ten=None):
        khoa = (so_dich or "") or _fold(ten or "")
        if not khoa or khoa in da_co:
            return
        if so_dich and so_hieu_minh and so_dich == chuan_hoa_so_hieu(so_hieu_minh):
            return
        da_co.add(khoa)
        ra.append({"loai": loai, "so_hieu_dich": so_dich, "ten_dich": ten})

    # --- 1. thay thế / bãi bỏ — điều khoản thi hành, quét CẢ THÂN BÀI ---
    for m in re.finditer(r"thay\s+thế|bãi\s+bỏ", text, re.IGNORECASE):
        loai = "thay_the" if _c(m.group(0)).startswith("thay") else "bai_bo"
        truoc = _c(text[max(0, m.start() - 30):m.start()])
        # CÂU BỊ ĐỘNG — "Nghị định này ĐƯỢC thay thế bởi Nghị định 145/2020":
        # chủ ngữ là CHÍNH văn bản này, văn bản nêu sau là kẻ thay thế. Ghi
        # theo chiều xuôi ở đây là ĐẢO NGƯỢC quan hệ — máy sẽ khai tử đúng
        # văn bản đang còn hiệu lực và giữ văn bản đã chết. Bỏ qua: bản thay
        # thế khi vào kho sẽ tự khai "thay thế X" theo chiều đúng.
        if re.search(r"(được|bị)\s*$", truoc):
            continue
        cua_so = _cat_cau(text[m.end():m.end() + _CUA_SO])
        dau_so = RE_SO_HIEU.search(cua_so)
        if not dau_so:
            continue
        # "bãi bỏ Điều 5 của Nghị định X", "thay thế cụm từ … tại khoản 2 Điều 3
        # Nghị định X" = sửa MỘT PHẦN, không phải khai tử. Soi cả đoạn từ động
        # từ tới số hiệu, không chỉ ngay đầu cửa sổ: mốc Điều/khoản/cụm từ hay
        # đứng giữa câu.
        if re.search(r"\b(Điều|khoản|điểm|cụm\s+từ|Chương|Mục|Phụ\s+lục)\b",
                     cua_so[:dau_so.start()], re.IGNORECASE):
            loai = "sua_doi_bo_sung"
        # CHỐT: phải có tên loại văn bản giữa động từ và số hiệu đầu tiên —
        # "thay thế phương án 05/2019/BC" trong một báo cáo thì bỏ qua.
        if not re.search(_LOAI_THUONG_RX, cua_so[:dau_so.start()], re.IGNORECASE):
            continue
        for so in _so_hieu_trong(cua_so, bo_qua=so_hieu_minh):
            them(loai, so_dich=so)

    # --- 2. sửa đổi, bổ sung — thường nằm ngay TIÊU ĐỀ văn bản sửa đổi ---
    for m in re.finditer(r"sửa\s+đổi,?\s+bổ\s+sung\s+(?:một\s+số\s+điều\s+của\s+)?",
                         head, re.IGNORECASE):
        # "được sửa đổi, bổ sung bởi …" — bị động, xem chú thích ở mục 1.
        if re.search(r"(được|bị)\s*$", _c(head[max(0, m.start() - 30):m.start()])):
            continue
        cua_so = _cat_cau(head[m.end():m.end() + _CUA_SO])
        cac_so = _so_hieu_trong(cua_so, bo_qua=so_hieu_minh)
        if cac_so:
            if re.search(_LOAI_THUONG_RX, cua_so[:RE_SO_HIEU.search(cua_so).start()],
                         re.IGNORECASE):
                for so in cac_so:
                    them("sua_doi_bo_sung", so_dich=so)
        else:
            ten = _ten_dich_trong(cua_so)
            if ten:
                them("sua_doi_bo_sung", ten=ten)

    # --- 3. quy định chi tiết / hướng dẫn thi hành — trích yếu nghị định/thông tư ---
    for m in re.finditer(r"(?:quy\s+định\s+chi\s+tiết|hướng\s+dẫn)"
                         r"(?:\s+và\s+[\wà-ỹ\s]{0,30}?)?(?:\s+thi\s+hành)?"
                         r"\s+(?:một\s+số\s+điều\s+(?:và\s+[\wà-ỹ\s]{0,40}?)?của\s+)?",
                         head, re.IGNORECASE):
        cua_so = _cat_cau(head[m.end():m.end() + _CUA_SO])
        dau_so = RE_SO_HIEU.search(cua_so)
        if dau_so and re.search(_LOAI_THUONG_RX, cua_so[:dau_so.start()],
                                re.IGNORECASE):
            for so in _so_hieu_trong(cua_so, bo_qua=so_hieu_minh):
                them("huong_dan", so_dich=so)
        else:
            ten = _ten_dich_trong(cua_so)
            if ten:
                them("huong_dan", ten=ten)

    # --- 4. căn cứ — các dòng "Căn cứ …" ở phần mở đầu ---
    for line in head.split("\n"):
        line = line.strip()
        if not re.match(r"Căn\s+cứ\b", line, re.IGNORECASE):
            continue
        cac_so = _so_hieu_trong(line, bo_qua=so_hieu_minh)
        if cac_so:
            for so in cac_so:
                them("can_cu", so_dich=so)
        else:
            ten = _ten_dich_trong(re.sub(r"^Căn\s+cứ\s+", "", line,
                                         flags=re.IGNORECASE))
            if ten:
                them("can_cu", ten=ten)
    return ra


# ---------------------------------------------------------------------------
# Ghi / đọc CSDL — nhận cursor từ bên gọi, module này không mở kết nối
# ---------------------------------------------------------------------------
def ghi_quan_he(cur, so_hieu_nguon: str, ten_nguon: str, quan_he: list):
    """Ghi lại toàn bộ quan hệ TỰ ĐỘNG của một văn bản (xoá bản auto cũ trước).

    Chỉ đụng hàng nguon='auto' — quan hệ admin thêm tay (nguon='manual')
    không bị lượt học lại quét mất.
    """
    so_hieu_nguon = chuan_hoa_so_hieu(so_hieu_nguon)
    if not so_hieu_nguon:
        return 0
    cur.execute("DELETE FROM van_ban_quan_he "
                "WHERE lower(so_hieu_nguon)=lower(%s) AND nguon='auto'",
                (so_hieu_nguon,))
    n = 0
    for q in quan_he or []:
        if q.get("loai") not in LOAI_QUAN_HE:
            continue
        if not (q.get("so_hieu_dich") or q.get("ten_dich")):
            continue
        cur.execute(
            """INSERT INTO van_ban_quan_he
                 (so_hieu_nguon, ten_nguon, loai, so_hieu_dich, ten_dich, nguon)
               SELECT %s,%s,%s,%s,%s,'auto'
                WHERE NOT EXISTS (
                  SELECT 1 FROM van_ban_quan_he
                   WHERE lower(so_hieu_nguon)=lower(%s) AND loai=%s
                     AND lower(coalesce(so_hieu_dich,''))=lower(coalesce(%s,''))
                     AND lower(coalesce(ten_dich,''))=lower(coalesce(%s,'')))""",
            (so_hieu_nguon, ten_nguon, q["loai"], q.get("so_hieu_dich"),
             q.get("ten_dich"), so_hieu_nguon, q["loai"],
             q.get("so_hieu_dich"), q.get("ten_dich")))
        n += cur.rowcount
    return n


def cap_nhat_hieu_luc(cur, so_hieu_dich=None) -> int:
    """Hạ trạng thái hiệu lực theo bảng quan hệ — CHỈ chiều xấu đi, CHỈ khi
    văn bản nguồn (bản thay thế/sửa đổi) đang thật sự nằm trong kho.

    'con_hieu_luc' do người đặt tay không bị đè: máy chỉ đụng 'chua_ro' (và
    nâng 'het_hieu_luc_mot_phan' lên 'het_hieu_luc' khi có bản thay thế hẳn).
    Truyền ``so_hieu_dich`` (list) để chỉ cập nhật đúng các văn bản vừa bị
    nhắc tới; None là quét cả kho (dành cho backfill).
    """
    ds = [chuan_hoa_so_hieu(s).lower() for s in (so_hieu_dich or []) if s] or None
    tong = 0
    cur.execute(
        """UPDATE documents d SET trang_thai_hieu_luc='het_hieu_luc'
            WHERE d.doc_type='law' AND d.so_hieu IS NOT NULL
              AND coalesce(d.trang_thai_hieu_luc,'chua_ro')
                  IN ('chua_ro','het_hieu_luc_mot_phan')
              AND (%s::text[] IS NULL OR lower(d.so_hieu)=ANY(%s))
              AND EXISTS (SELECT 1 FROM van_ban_quan_he q
                            JOIN documents s
                              ON lower(s.so_hieu)=lower(q.so_hieu_nguon)
                             AND s.doc_type='law' AND coalesce(s.active,true)
                             -- Cùng điều kiện với van_ban_moi_hon: một tài liệu
                             -- CHƯA DUYỆT không được quyền khai tử văn bản đang
                             -- phục vụ. Thiếu vế này thì kho đánh dấu "hết hiệu
                             -- lực" mà không kéo nổi bản thay thế vào nguồn.
                             AND s.approved AND s.label_verified
                             -- Văn bản không tự thay thế chính nó (bóc trượt
                             -- so_hieu_minh thì chốt trong boc_quan_he không chạy).
                             AND lower(q.so_hieu_nguon) <> lower(q.so_hieu_dich)
                           WHERE q.loai IN ('thay_the','bai_bo')
                             AND lower(q.so_hieu_dich)=lower(d.so_hieu))""",
        (ds, ds))
    tong += cur.rowcount
    cur.execute(
        """UPDATE documents d SET trang_thai_hieu_luc='het_hieu_luc_mot_phan'
            WHERE d.doc_type='law' AND d.so_hieu IS NOT NULL
              AND coalesce(d.trang_thai_hieu_luc,'chua_ro')='chua_ro'
              AND (%s::text[] IS NULL OR lower(d.so_hieu)=ANY(%s))
              AND EXISTS (SELECT 1 FROM van_ban_quan_he q
                            JOIN documents s
                              ON lower(s.so_hieu)=lower(q.so_hieu_nguon)
                             AND s.doc_type='law' AND coalesce(s.active,true)
                             -- Cùng điều kiện với van_ban_moi_hon: một tài liệu
                             -- CHƯA DUYỆT không được quyền khai tử văn bản đang
                             -- phục vụ. Thiếu vế này thì kho đánh dấu "hết hiệu
                             -- lực" mà không kéo nổi bản thay thế vào nguồn.
                             AND s.approved AND s.label_verified
                             -- Văn bản không tự thay thế chính nó (bóc trượt
                             -- so_hieu_minh thì chốt trong boc_quan_he không chạy).
                             AND lower(q.so_hieu_nguon) <> lower(q.so_hieu_dich)
                           WHERE q.loai='sua_doi_bo_sung'
                             AND lower(q.so_hieu_dich)=lower(d.so_hieu))""",
        (ds, ds))
    tong += cur.rowcount
    return tong


def xu_ly_sau_hoc(cur, doc_type: str, text: str, meta: dict):
    """Việc chung sau khi một văn bản luật vào kho: ghi quan hệ + hạ hiệu lực.

    Gọi từ learn_one/ingest_file TRONG cùng transaction ghi documents.
    Trả (số quan hệ ghi, số văn bản bị hạ trạng thái).
    """
    if doc_type != "law" or not (meta or {}).get("so_hieu"):
        return 0, 0
    quan_he = boc_quan_he(text, so_hieu_minh=meta["so_hieu"])
    # Văn bản hợp nhất: tên file mang số VBHN, chữ mang số luật gốc → ghi quan
    # hệ hợp nhất để tra "67/VBHN-VPQH là bản hợp nhất của luật nào".
    goc = meta.get("so_hieu_trong_van_ban")
    if goc and goc != meta["so_hieu"]:
        quan_he.append({"loai": "hop_nhat", "so_hieu_dich": goc, "ten_dich": None})
    n_qh = ghi_quan_he(cur, meta["so_hieu"], ten_day_du(meta), quan_he)
    dich = [q["so_hieu_dich"] for q in quan_he if q.get("so_hieu_dich")]
    n_ha = cap_nhat_hieu_luc(cur, dich) if dich else 0
    # Chiều ngược: văn bản VỪA VÀO KHO có thể chính là văn bản đã bị một bản
    # mới hơn (vào kho trước đó) tuyên thay thế — soi lại chính nó.
    n_ha += cap_nhat_hieu_luc(cur, [meta["so_hieu"]])
    return n_qh, n_ha


# Cột SELECT dùng chung cho hai chiều đọc quan hệ — đổi ở một chỗ.
_QH_COT = """q.id, q.loai, q.nguon, q.ghi_chu, q.so_hieu_nguon, q.ten_nguon,
             q.so_hieu_dich, q.ten_dich,
             d.id, d.title, d.trich_yeu, d.loai_van_ban,
             d.trang_thai_hieu_luc, d.doc_type, d.access_level,
             d.client_id, d.department_id"""


def doc_quan_he(cur, so_hieu: str) -> dict:
    """Quan hệ HAI CHIỀU của một số hiệu, kèm văn bản đối ứng nếu có trong kho.

    ``xuoi``  — văn bản này nói về ai (nó thay thế/sửa đổi/căn cứ văn bản nào).
    ``nguoc`` — ai nói về văn bản này (nó bị ai thay thế/sửa đổi/hướng dẫn).
    Văn bản đối ứng chọn bằng LATERAL (bản duyệt mới nhất) vì một số hiệu có
    thể trùng giữa bản cũ/bản OCR lại. Người gọi TỰ chịu trách nhiệm lọc
    quyền hiển thị (can_open_doc/mask_title) trước khi trả ra ngoài.
    """
    so = chuan_hoa_so_hieu(so_hieu)
    if not so:
        return {"xuoi": [], "nguoc": []}

    def _rows(sql, arg):
        cur.execute(sql, (arg,))
        ra = []
        for r in cur.fetchall():
            ra.append({
                "id": r[0], "loai": r[1], "nguon": r[2], "ghi_chu": r[3],
                "so_hieu_nguon": r[4], "ten_nguon": r[5],
                "so_hieu_dich": r[6], "ten_dich": r[7],
                "doc": None if r[8] is None else {
                    "document_id": r[8], "title": r[9], "trich_yeu": r[10],
                    "loai_van_ban": r[11], "trang_thai_hieu_luc": r[12],
                    "doc_type": r[13], "access_level": r[14],
                    "client_id": r[15], "department_id": r[16]},
            })
        return ra

    lateral = """LEFT JOIN LATERAL (
                   SELECT * FROM documents dd
                    WHERE lower(dd.so_hieu)=lower({khoa})
                      AND coalesce(dd.active,true)
                    ORDER BY dd.approved DESC, dd.id DESC LIMIT 1
                 ) d ON true"""
    xuoi = _rows(
        f"""SELECT {_QH_COT} FROM van_ban_quan_he q
            {lateral.format(khoa='q.so_hieu_dich')}
            WHERE lower(q.so_hieu_nguon)=lower(%s)
            ORDER BY array_position(ARRAY['thay_the','bai_bo','sua_doi_bo_sung',
                     'huong_dan','hop_nhat','can_cu','lien_quan'], q.loai), q.id""",
        so)
    nguoc = _rows(
        f"""SELECT {_QH_COT} FROM van_ban_quan_he q
            {lateral.format(khoa='q.so_hieu_nguon')}
            WHERE lower(q.so_hieu_dich)=lower(%s)
            ORDER BY array_position(ARRAY['thay_the','bai_bo','sua_doi_bo_sung',
                     'huong_dan','hop_nhat','can_cu','lien_quan'], q.loai), q.id""",
        so)
    return {"xuoi": xuoi, "nguoc": nguoc}


def van_ban_moi_hon(cur, so_hieu_list) -> list:
    """Các văn bản TRONG KHO đã thay thế / sửa đổi những số hiệu này.

    Dùng cho bộ tra cứu: nguồn trúng là luật đã chết → kéo bản mới vào prompt.
    Trả [{document_id, title, ten, loai, so_hieu_cu}].
    """
    ds = [chuan_hoa_so_hieu(s).lower() for s in (so_hieu_list or []) if s]
    if not ds:
        return []
    cur.execute(
        """SELECT DISTINCT ON (d.id, q.so_hieu_dich)
                  d.id, d.title, q.ten_nguon, q.loai, q.so_hieu_dich,
                  d.trich_yeu, d.loai_van_ban, d.so_hieu
             FROM van_ban_quan_he q
             JOIN documents d ON lower(d.so_hieu)=lower(q.so_hieu_nguon)
                  AND d.doc_type='law' AND coalesce(d.active,true)
                  AND d.approved AND d.label_verified
            WHERE q.loai IN ('thay_the','bai_bo','sua_doi_bo_sung')
              AND lower(q.so_hieu_dich)=ANY(%s)
            ORDER BY d.id, q.so_hieu_dich""",
        (ds,))
    ra = []
    for r in cur.fetchall():
        ten = r[2] or ten_day_du({"loai_van_ban": r[6], "trich_yeu": r[5]},
                                 so_hieu=r[7]) or r[1]
        ra.append({"document_id": r[0], "title": r[1], "ten": ten,
                   "loai": r[3], "so_hieu_cu": chuan_hoa_so_hieu(r[4] or "")})
    return ra
