"""chat_draft.py — Soạn tài liệu THEO MẪU ngay từ khung chat.

"tạo hợp đồng lao động cho Ngân như của Nhi" phải cho ra một BẢN NHÁP thật
(bảng document_drafts, tải được .docx) sinh từ đúng cấu trúc tài liệu mẫu của
Nhi cộng dữ liệu đã xác minh của Ngân — không phải một đoạn văn tả lại việc đó,
càng không phải câu "không tìm thấy trong tài liệu".

Nguyên tắc:
  · Nhận diện bằng cụm khuôn "tạo/soạn <loại giấy> cho <A> như/theo mẫu (của)
    <B>" — đủ chặt để câu hỏi tra cứu bình thường ("hợp đồng của SUNGROUP có
    điều khoản gì") không bị nuốt thành lệnh soạn thảo.
  · Nguồn (tài liệu mẫu của B + hồ sơ của A) được TÌM QUA PHIÊN CÓ RLS của
    chính người hỏi — không thấy nghĩa là không có quyền, tuyệt đối không mở
    bằng phiên admin rồi mới lọc.
  · Không tạo được thì nói RÕ thiếu gì và bổ sung ở đâu — có suy nghĩ, không
    im lặng, không bịa.
"""
from __future__ import annotations

import json
import re
import unicodedata

from app import db, drafting


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = s.replace("đ", "d").replace("Đ", "d")
    return re.sub(r"[\s_]+", " ", s).strip().lower()


# Loại giấy tờ nhận soạn từ chat. Cụm DÀI đứng trước để regex ưu tiên khớp
# "hợp đồng lao động" thay vì dừng ở "hợp đồng".
_KINDS = [
    ("hop dong lao dong", "hợp đồng lao động"),
    ("hdld", "hợp đồng lao động"),
    ("hop dong thu viec", "hợp đồng thử việc"),
    ("hop dong dich vu", "hợp đồng dịch vụ"),
    ("hop dong", "hợp đồng"),
    ("quyet dinh bo nhiem", "quyết định bổ nhiệm"),
    ("quyet dinh tuyen dung", "quyết định tuyển dụng"),
    ("quyet dinh", "quyết định"),
    ("thu tu van", "thư tư vấn"),
    ("bien ban", "biên bản"),
    ("giay uy quyen", "giấy ủy quyền"),
    # Văn bản tố tụng / đơn từ / công văn — phản hồi Huế, Nhi, Ngân 29/08/2026:
    # "soạn đơn kháng cáo", "đơn phản đối cấp văn bằng" không có vế "cho ai".
    ("don khoi kien", "đơn khởi kiện"),
    ("don khang cao", "đơn kháng cáo"),
    ("don yeu cau", "đơn yêu cầu"),
    ("don de nghi", "đơn đề nghị"),
    ("don phan doi", "đơn phản đối"),
    ("don khieu nai", "đơn khiếu nại"),
    ("cong van", "công văn"),
    ("thong bao", "thông báo"),
    ("ban tu khai", "bản tự khai"),
    ("ban luan cu", "bản luận cứ"),
    ("ban bao ve", "bản bảo vệ quyền và lợi ích hợp pháp"),
    ("ban y kien", "bản ý kiến"),
    ("y kien phap ly", "ý kiến pháp lý"),
    ("don", "đơn"),
    ("thu", "thư"),
    ("van ban", "văn bản"),
]
_KIND_ALT = "|".join(k for k, _ in _KINDS)

# "tạo/soạn <loại> cho <A> như/giống/theo mẫu (của) <B>"
RE_DRAFT = re.compile(
    r"(?:^|\s)(?:tao|soan thao|soan|lam|viet)\s+"
    r"(?:giup toi\s+|giup\s+|ho toi\s+|ho\s+|mot\s+|ban\s+)*"
    rf"({_KIND_ALT})\s+(?:moi\s+)?"
    r"cho\s+(.{2,60}?)\s+"
    r"(?:nhu cua|giong cua|giong nhu cua|theo mau cua|dua tren mau cua|"
    r"nhu|giong nhu|giong|theo mau|dua tren)\s+"
    r"(?:cua\s+)?(.{2,60}?)\s*[?.!…]*\s*$"
)

# "tạo/soạn <loại> cho <A>" — KHÔNG có vế mẫu → dùng MẪU CHUẨN trong kho
# (ngăn 4. HỢP ĐỒNG MẪU / 6. THƯ MẪU). Yêu cầu 21/08/2026 của chủ dự án:
# "làm hợp đồng lao động thì ra file docx để điền chỗ trống hoặc tự điền".
RE_DRAFT_SIMPLE = re.compile(
    r"(?:^|\s)(?:tao|soan thao|soan|lam|viet)\s+"
    r"(?:giup toi\s+|giup\s+|ho toi\s+|ho\s+|mot\s+|ban\s+)*"
    rf"({_KIND_ALT})\s+(?:moi\s+)?"
    r"cho\s+(.{2,60}?)\s*[?.!…]*\s*$"
)

# Loại văn bản soạn được KHÔNG cần "cho <tên>": bối cảnh là cả câu lệnh.
_KIND_TU_DO = {
    "don khoi kien", "don khang cao", "don yeu cau", "don de nghi", "don phan doi",
    "don khieu nai", "cong van", "thong bao", "ban tu khai", "ban luan cu",
    "ban bao ve", "ban y kien", "y kien phap ly",
}
# "soạn đơn kháng cáo bản án sơ thẩm số …" / "hãy viết công văn gửi Sở …"
RE_DRAFT_TU_DO = re.compile(
    r"^\s*(?:hay\s+|nho\s+|giup toi\s+|giup\s+)?(?:tao|soan thao|soan|lam|viet|du thao)\s+"
    r"(?:giup toi\s+|giup\s+|ho toi\s+|ho\s+|mot\s+|ban\s+|du thao\s+|cai\s+)*"
    rf"({_KIND_ALT})(?:\s+(.*))?\s*$", re.S)
# Câu hỏi CÁCH soạn ("soạn đơn kháng cáo cần những nội dung gì?") là tra cứu,
# không phải lệnh soạn — trả None để rơi về luồng luật.
_RE_HOI_CACH_SOAN = re.compile(
    r"\b(?:gi|nao|the nao|ra sao|bao nhieu|co can|can gi|gom nhung|co phai|"
    r"nhu the nao)\b|\bkhong\s*$|\bhuong dan\s+(?:toi\s+|minh\s+)?cach\b|"
    r"\bcach\s+(?:soan|viet|lam|trinh bay)\b")

# Khung mục bắt buộc theo thể thức thông dụng — dùng làm KHUNG TÀI LIỆU khi kho
# chưa có mẫu đúng loại, và luôn liệt kê vào chỉ dẫn để model không bỏ mục
# (phản hồi Huế 29/08: "chưa xác định được loại văn bản, mục đích, bố cục").
_KHUNG_VAN_BAN = {
    "don khoi kien": """# CỘNG HOÀ XÃ HỘI CHỦ NGHĨA VIỆT NAM
## Độc lập - Tự do - Hạnh phúc
[CẦN BỔ SUNG: địa danh], ngày … tháng … năm 2026
# ĐƠN KHỞI KIỆN
## Kính gửi: Toà án nhân dân [CẦN BỔ SUNG: cấp, địa phương]
## Người khởi kiện
[CẦN BỔ SUNG: tên, địa chỉ, CCCD/mã số doanh nghiệp, người đại diện theo pháp luật]
## Người bị kiện
[CẦN BỔ SUNG: tên, địa chỉ]
## Người có quyền lợi, nghĩa vụ liên quan
[CẦN BỔ SUNG: nếu có]
## Nội dung vụ việc
(tóm tắt diễn biến theo thời gian, quan hệ pháp luật tranh chấp)
## Yêu cầu Toà án giải quyết
(từng yêu cầu cụ thể, số tiền, căn cứ pháp lý)
## Danh mục tài liệu, chứng cứ kèm theo
## Người khởi kiện
(ký, ghi rõ họ tên; đóng dấu nếu là tổ chức)
""",
    "don khang cao": """# CỘNG HOÀ XÃ HỘI CHỦ NGHĨA VIỆT NAM
## Độc lập - Tự do - Hạnh phúc
[CẦN BỔ SUNG: địa danh], ngày … tháng … năm 2026
# ĐƠN KHÁNG CÁO
## Kính gửi: Toà án nhân dân [CẦN BỔ SUNG: Toà đã xét xử sơ thẩm]
## Người kháng cáo
[CẦN BỔ SUNG: tên, địa chỉ, tư cách tố tụng trong vụ án]
## Bản án, quyết định sơ thẩm bị kháng cáo
[CẦN BỔ SUNG: số, ngày, Toà án đã tuyên]
## Nội dung và phạm vi kháng cáo
(kháng cáo toàn bộ hay phần nào của bản án)
## Lý do kháng cáo
(từng căn cứ, dẫn điều luật tố tụng/nội dung)
## Yêu cầu của người kháng cáo
(huỷ, sửa bản án; giải quyết lại…)
## Tài liệu, chứng cứ kèm theo
## Người kháng cáo
(ký, ghi rõ họ tên)
""",
    "don yeu cau": """# CỘNG HOÀ XÃ HỘI CHỦ NGHĨA VIỆT NAM
## Độc lập - Tự do - Hạnh phúc
[CẦN BỔ SUNG: địa danh], ngày … tháng … năm 2026
# ĐƠN YÊU CẦU
## Kính gửi: [CẦN BỔ SUNG: cơ quan]
## Người yêu cầu
[CẦN BỔ SUNG: tên, địa chỉ, giấy tờ]
## Nội dung sự việc
## Căn cứ yêu cầu
## Yêu cầu cụ thể
## Tài liệu kèm theo
## Người làm đơn
""",
    "don de nghi": """# CỘNG HOÀ XÃ HỘI CHỦ NGHĨA VIỆT NAM
## Độc lập - Tự do - Hạnh phúc
[CẦN BỔ SUNG: địa danh], ngày … tháng … năm 2026
# ĐƠN ĐỀ NGHỊ
## Kính gửi: [CẦN BỔ SUNG: cơ quan]
## Người đề nghị
## Nội dung sự việc
## Căn cứ đề nghị
## Đề nghị cụ thể
## Tài liệu kèm theo
## Người làm đơn
""",
    "don phan doi": """# CỘNG HOÀ XÃ HỘI CHỦ NGHĨA VIỆT NAM
## Độc lập - Tự do - Hạnh phúc
[CẦN BỔ SUNG: địa danh], ngày … tháng … năm 2026
# ĐƠN PHẢN ĐỐI CẤP VĂN BẰNG BẢO HỘ
## Kính gửi: Cục Sở hữu trí tuệ
## Người phản đối
[CẦN BỔ SUNG: tên, địa chỉ, đại diện sở hữu công nghiệp nếu có]
## Đơn đăng ký bị phản đối
[CẦN BỔ SUNG: số đơn, ngày nộp, chủ đơn, mẫu nhãn hiệu, nhóm hàng hoá/dịch vụ]
## Nhãn hiệu, quyền đối chứng của người phản đối
[CẦN BỔ SUNG: số văn bằng/số đơn, ngày ưu tiên, mẫu nhãn, nhóm hàng hoá/dịch vụ]
## Căn cứ phản đối
(dẫn điều, khoản, điểm Luật Sở hữu trí tuệ)
## Lập luận so sánh
(cấu trúc, phát âm, ý nghĩa, hình thức, hàng hoá/dịch vụ; khả năng gây nhầm lẫn)
## Yêu cầu
(từ chối cấp văn bằng toàn bộ/một phần)
## Tài liệu, chứng cứ kèm theo
## Người phản đối
""",
    "don khieu nai": """# CỘNG HOÀ XÃ HỘI CHỦ NGHĨA VIỆT NAM
## Độc lập - Tự do - Hạnh phúc
[CẦN BỔ SUNG: địa danh], ngày … tháng … năm 2026
# ĐƠN KHIẾU NẠI
## Kính gửi: [CẦN BỔ SUNG: cơ quan có thẩm quyền giải quyết]
## Người khiếu nại
## Quyết định, hành vi bị khiếu nại
[CẦN BỔ SUNG: số, ngày, cơ quan/người ban hành]
## Nội dung khiếu nại và lý do
## Yêu cầu giải quyết
## Tài liệu kèm theo
## Người khiếu nại
""",
    "cong van": """# [CẦN BỔ SUNG: TÊN CƠ QUAN, TỔ CHỨC]
Số: [CẦN BỔ SUNG]/CV-[CẦN BỔ SUNG]
V/v [CẦN BỔ SUNG: trích yếu]
[CẦN BỔ SUNG: địa danh], ngày … tháng … năm 2026
## Kính gửi: [CẦN BỔ SUNG: cơ quan nhận]
## Căn cứ
## Nội dung
(trình bày, đề nghị, thời hạn phản hồi)
## Nơi nhận
## Người ký
(chức danh, ký tên, đóng dấu)
""",
    "thong bao": """# [CẦN BỔ SUNG: TÊN CƠ QUAN, TỔ CHỨC]
Số: [CẦN BỔ SUNG]/TB-[CẦN BỔ SUNG]
[CẦN BỔ SUNG: địa danh], ngày … tháng … năm 2026
# THÔNG BÁO
## V/v [CẦN BỔ SUNG: trích yếu]
## Kính gửi: [CẦN BỔ SUNG]
## Căn cứ
## Nội dung thông báo
## Hiệu lực và việc cần thực hiện
## Nơi nhận
## Người ký
""",
    "ban tu khai": """# CỘNG HOÀ XÃ HỘI CHỦ NGHĨA VIỆT NAM
## Độc lập - Tự do - Hạnh phúc
[CẦN BỔ SUNG: địa danh], ngày … tháng … năm 2026
# BẢN TỰ KHAI
## Kính gửi: Toà án nhân dân [CẦN BỔ SUNG]
## Người khai
[CẦN BỔ SUNG: tên, địa chỉ, tư cách tố tụng, vụ án]
## Nội dung trình bày
(theo diễn biến thời gian; chứng cứ kèm theo từng ý)
## Yêu cầu, đề nghị
## Cam đoan
## Người khai
""",
    "ban luan cu": """# BẢN LUẬN CỨ BẢO VỆ
## Kính gửi: Hội đồng xét xử Toà án nhân dân [CẦN BỔ SUNG]
## Luật sư và người được bảo vệ
[CẦN BỔ SUNG: luật sư, tổ chức hành nghề, bảo vệ cho ai, tư cách tố tụng]
## Tóm tắt vụ án
## Các vấn đề cần giải quyết
## Phân tích từng vấn đề
(chứng cứ + căn cứ pháp luật cho mỗi vấn đề)
## Kết luận và đề nghị Hội đồng xét xử
## Luật sư
""",
    "ban bao ve": """# BẢN BẢO VỆ QUYỀN VÀ LỢI ÍCH HỢP PHÁP
## Kính gửi: Hội đồng xét xử Toà án nhân dân [CẦN BỔ SUNG]
## Người bảo vệ và người được bảo vệ
## Tóm tắt vụ án
## Các vấn đề cần giải quyết
## Phân tích từng vấn đề
(chứng cứ + căn cứ pháp luật)
## Kết luận và đề nghị Hội đồng xét xử
## Người bảo vệ
""",
    "ban y kien": """# BẢN Ý KIẾN
## Kính gửi: [CẦN BỔ SUNG]
## Người trình bày ý kiến
## Về việc
## Ý kiến
(từng điểm, kèm căn cứ)
## Đề nghị
## Người trình bày
""",
    "y kien phap ly": """# Ý KIẾN PHÁP LÝ
## Gửi: [CẦN BỔ SUNG: khách hàng]
## Vấn đề được hỏi
## Dữ kiện và giả định
## Căn cứ pháp luật
## Phân tích
## Kết luận
## Giới hạn của ý kiến
## Luật sư
""",
}


def khung_van_ban(kind: str) -> str:
    """Khung Markdown theo thể thức thông dụng của loại văn bản; '' nếu không có."""
    return _KHUNG_VAN_BAN.get(kind, "")


def muc_bat_buoc(kind: str) -> list[str]:
    """Tên các mục (dòng '## ') trong khung — đưa vào chỉ dẫn để model không bỏ."""
    return [line[3:].strip() for line in khung_van_ban(kind).splitlines()
            if line.startswith("## ")]


def _detect_tu_do(question: str, folded: str):
    m = RE_DRAFT_TU_DO.search(folded)
    if not m or m.group(1) not in _KIND_TU_DO:
        return None
    phan_sau = (m.group(2) or "").strip(" ?.!…")
    if _RE_HOI_CACH_SOAN.search(phan_sau) or folded.rstrip().endswith("?"):
        return None
    kind_key = m.group(1)
    kind_label = dict(_KINDS)[kind_key]
    boi_canh = (question or "").strip()
    return {"kind": kind_key, "kind_label": kind_label,
            "for_name": None, "like_name": None, "for_self": False,
            "tu_do": True, "boi_canh": boi_canh,
            "boi_canh_ngan": _bo_cum_lenh(boi_canh, kind_label)}


def _bo_cum_lenh(question: str, kind_label: str) -> str:
    """Bối cảnh SAU cụm "soạn <loại>": để đặt tên bản nháp không lặp lại lệnh.

    So trên bản gốc có dấu; người gõ không dấu thì giữ nguyên cả câu — chỉ là
    tên hiển thị, không ảnh hưởng nội dung soạn."""
    m = re.match(
        r"\s*(?:hãy\s+|nhờ\s+|giúp tôi\s+|giúp\s+)?(?:tạo|soạn thảo|soạn|làm|viết|dự thảo)\s+"
        r"(?:giúp tôi\s+|giúp\s+|hộ tôi\s+|hộ\s+|một\s+|bản\s+|dự thảo\s+|cái\s+)*"
        + re.escape(kind_label) + r"\s*[:,\-–—]?\s*", question, re.IGNORECASE)
    return question[m.end():].strip() if m and question[m.end():].strip() else question

# Đại từ/xưng hô đứng trước tên — bỏ đi để so khớp với tên file/sổ nhân sự.
_HONORIFICS = {"anh", "chi", "co", "ong", "ba", "em", "ban", "bac", "nhan vien"}

# Từ KHÔNG THỂ là tên người trong vế "cho <A>" của khuôn đơn. Câu tra cứu luật
# rất hay mang khuôn y hệt ("tạo hợp đồng lao động cho người lao động cần điều
# kiện gì") — một từ nghi vấn/danh từ chung lọt vào tên là phải trả None để câu
# rơi về tra cứu, tuyệt đối không đè lên câu hỏi pháp lý.
_NAME_STOP = {
    "gi", "nao", "sao", "the", "bao", "nhieu", "khong", "can", "phai", "duoc",
    "la", "va", "hay", "hoac", "nhu", "theo", "ai", "dau", "may", "gom",
    "nguoi", "lao", "dong", "moi", "cu", "cong", "ty", "khach", "hang",
    "doanh", "nghiep", "ben", "cac", "nhung", "mot", "hai", "thue",
}
# Xưng hô ngôi thứ nhất: "tạo HĐLĐ cho tôi" — soạn cho CHÍNH người đang chat.
_SELF_WORDS = {"toi", "minh", "tui", "em", "anh", "chi"}


def _clean_name(raw: str) -> str:
    tokens = _fold(raw).split()
    while tokens and tokens[0] in _HONORIFICS:
        tokens = tokens[1:]
    return " ".join(tokens)


def detect_request(question: str):
    """Câu chat có phải lệnh soạn thảo không. Trả dict hoặc None.

    Hai khuôn, thử khuôn CHẶT trước:
      1. "tạo <loại> cho A như/theo mẫu (của) B" → like_name=B, bám tài liệu
         của B làm mẫu.
      2. "tạo <loại> cho A" (không vế mẫu) → like_name=None, dùng mẫu chuẩn
         trong kho (hợp đồng mẫu/thư mẫu). Vế tên bị kiểm nghiêm hơn hẳn để
         câu tra cứu pháp lý cùng khuôn không bị nuốt thành lệnh soạn thảo.
    """
    folded = _fold(question)
    m = RE_DRAFT.search(folded)
    if m:
        kind_key = m.group(1)
        for_name = _clean_name(m.group(2))
        like_name = _clean_name(m.group(3))
        if not for_name or not like_name or for_name == like_name:
            return None
        kind_label = dict(_KINDS).get(kind_key, kind_key)
        return {"kind": kind_key, "kind_label": kind_label,
                "for_name": for_name, "like_name": like_name}

    m = RE_DRAFT_SIMPLE.search(folded)
    if m:
        kind_key = m.group(1)
        raw_name = _fold(m.group(2))
        for_self = raw_name in _SELF_WORDS
        for_name = raw_name if for_self else _clean_name(m.group(2))
        tokens = for_name.split()
        # Tên người thật: 1-4 tiếng, không tiếng nào là từ nghi vấn/danh từ chung.
        if for_self or (1 <= len(tokens) <= 4
                        and not any(t in _NAME_STOP for t in tokens)):
            kind_label = dict(_KINDS).get(kind_key, kind_key)
            return {"kind": kind_key, "kind_label": kind_label,
                    "for_name": for_name, "like_name": None, "for_self": for_self}
        if kind_key not in _KIND_TU_DO:
            return None
    # Văn bản tố tụng / đơn từ / công văn: không cần "cho ai", cả câu là bối cảnh.
    return _detect_tu_do(question, folded)


def _kind_match(folded_title: str, kind: str) -> bool:
    """Tiêu đề tài liệu có đúng LOẠI giấy đang cần không."""
    if kind in ("hop dong lao dong", "hdld"):
        return ("hdld" in folded_title
                or ("hop dong" in folded_title and "lao dong" in folded_title))
    return all(tok in folded_title for tok in kind.split())


def _name_match(folded_title: str, name: str) -> bool:
    return all(tok in folded_title for tok in name.split())


# Hồ sơ định danh xếp trước (CCCD/sơ yếu/CV) để bằng chứng ưu tiên đúng chỗ.
_PERSON_DOC_PRIORITY = ("cccd", "can cuoc", "so yeu", "ly lich", "cv",
                        "hdld", "hop dong")


def _sort_person_docs(person_docs):
    person_docs.sort(key=lambda item: min(
        (i for i, key in enumerate(_PERSON_DOC_PRIORITY) if key in _fold(item[1])),
        default=len(_PERSON_DOC_PRIORITY)))
    return person_docs


def pick_sources(docs, kind: str, for_name: str, like_name: str):
    """Chọn (tài liệu mẫu của B, các hồ sơ của A) từ danh sách (id, title, doc_type).

    Tách thuần để test không cần CSDL. `docs` là những gì NGƯỜI HỎI được thấy
    (đã qua RLS) — hàm này chỉ chọn, không mở rộng quyền.
    """
    template_doc = None
    fallback_doc = None
    person_docs = []
    for doc_id, title, doc_type in docs:
        t = _fold(title)
        if _name_match(t, like_name):
            if _kind_match(t, kind):
                template_doc = template_doc or (doc_id, title)
            elif doc_type == "ho_so_ns":
                fallback_doc = fallback_doc or (doc_id, title)
        if _name_match(t, for_name) and doc_type == "ho_so_ns":
            person_docs.append((doc_id, title))
    return (template_doc or fallback_doc, template_doc is None,
            _sort_person_docs(person_docs)[:4])


def pick_template(docs, kind: str):
    """Chọn tài liệu MẪU CHUẨN đúng loại giấy từ kho, cho khuôn không vế mẫu.

    Ưu tiên tuyệt đối ngăn mẫu (doc_type mau_hd/thu_mau — admin đã xếp tay);
    ngoài ngăn đó chỉ chấp nhận tài liệu mà chính tiêu đề nói nó là "mẫu".
    KHÔNG lấy đại một hợp đồng thật của người/khách khác làm mẫu — muốn thế
    người dùng phải nói rõ "như của ai" để tự chịu lựa chọn đó.
    """
    fallback = None
    for doc_id, title, doc_type in docs:
        t = _fold(title)
        if not _kind_match(t, kind):
            continue
        if doc_type in ("mau_hd", "thu_mau"):
            return (doc_id, title)
        if fallback is None and "mau" in t.split():
            fallback = (doc_id, title)
    return fallback


def pick_person_docs(docs, for_name: str):
    """Các hồ sơ nhân sự của A. Tên đầy đủ không khớp tên file (file thường đặt
    theo TÊN GỌI: 'Ngân — CCCD') thì thử lại bằng tiếng cuối của tên."""
    person_docs = [(doc_id, title) for doc_id, title, doc_type in docs
                   if doc_type == "ho_so_ns" and _name_match(_fold(title), for_name)]
    if not person_docs and len(for_name.split()) > 1:
        last = for_name.split()[-1]
        person_docs = [(doc_id, title) for doc_id, title, doc_type in docs
                       if doc_type == "ho_so_ns" and _name_match(_fold(title), last)]
    return _sort_person_docs(person_docs)[:4]


def _visible_documents(dept_ids, is_banqt, can_finance):
    with db.session(role="internal", dept_ids=dept_ids, is_banqt=is_banqt,
                    can_finance=can_finance) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT id, title, coalesce(doc_type,'other')
                             FROM documents
                            WHERE approved AND label_verified AND coalesce(active,true)
                            ORDER BY updated_at DESC LIMIT 500""")
            rows = cur.fetchall()
            # Ngăn MẪU CHUẨN phải luôn có mặt: kho lớn lên thì mẫu cũ rơi khỏi
            # 500 dòng mới nhất, và lệnh "tạo hợp đồng lao động cho X" mất mẫu
            # một cách im lặng. Ngăn mẫu chỉ vài chục file nên ghép thêm rẻ.
            seen = {row[0] for row in rows}
            cur.execute("""SELECT id, title, coalesce(doc_type,'other')
                             FROM documents
                            WHERE approved AND label_verified AND coalesce(active,true)
                              AND doc_type IN ('mau_hd','thu_mau')
                            ORDER BY updated_at DESC LIMIT 200""")
            rows.extend(row for row in cur.fetchall() if row[0] not in seen)
            return rows


def _employee_info(for_name: str):
    """Dòng sổ nhân sự khớp tên — dữ liệu ĐÃ XÁC MINH để điền vào bản nháp."""
    try:
        with db.session(role="internal") as conn:
            with conn.cursor() as cur:
                cur.execute("""SELECT e.full_name, e.employee_code, e.title, d.name
                                 FROM employees e
                                 LEFT JOIN departments d ON d.id=e.department_id
                                WHERE e.active LIMIT 200""")
                rows = cur.fetchall()
    except Exception:
        return None
    for full_name, code, title, dept in rows:
        if _name_match(_fold(full_name or ""), for_name):
            return {"ho_ten": full_name, "ma_nhan_vien": code,
                    "chuc_danh": title, "phong_ban": dept}
    return None


def _missing_answer(req) -> dict:
    """Không có mẫu để bám — nói rõ thiếu gì, bổ sung ở đâu. Không đoán."""
    like = req["like_name"].title()
    answer = (
        f"Mình chưa tạo bản nháp được: **trong kho chưa có {req['kind_label']} "
        f"nào của {like}** để làm mẫu.\n\n"
        f"Bạn có thể:\n"
        f"- Thả file {req['kind_label']} của {like} vào thư mục "
        f"`8. HỒ SƠ NHÂN SỰ/{like}/` trên Drive rồi chờ đồng bộ (≤15 phút), hoặc\n"
        f"- Mở tab **Soạn tài liệu** để soạn từ mẫu chuẩn của HDS mà không cần "
        f"bản của {like}."
    )
    return {"answer": answer, "answer_mode": "structured",
            "grounding_status": "verified",
            "evidence": [], "state": {}}


def _missing_template_answer(req) -> dict:
    """Khuôn đơn nhưng kho chưa có MẪU CHUẨN đúng loại — chỉ chỗ bổ sung."""
    answer = (
        f"Mình chưa tạo bản nháp được: **trong kho chưa có mẫu "
        f"{req['kind_label']}** để bám theo.\n\n"
        f"Bạn có thể:\n"
        f"- Thả file mẫu {req['kind_label']} vào thư mục `4. HỢP ĐỒNG MẪU/` "
        f"(hoặc `6. THƯ MẪU - BIỂU MẪU/`) trên Drive rồi chờ đồng bộ "
        f"(≤15 phút), hoặc\n"
        f"- Nói rõ muốn theo bản của ai: *\"tạo {req['kind_label']} cho "
        f"{req['for_name'].title()} như của …\"*, hoặc\n"
        f"- Mở tab **Soạn tài liệu** → Tạo bản nháp và chọn mẫu/nguồn thủ công."
    )
    return {"answer": answer, "answer_mode": "structured",
            "grounding_status": "verified",
            "evidence": [], "state": {}}


def _user_full_name(user_id) -> str:
    """Họ tên người đang chat — cho lệnh "tạo … cho tôi"."""
    try:
        with db.session(role="internal", admin=True) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT full_name FROM users WHERE id=%s", (user_id,))
                row = cur.fetchone()
        return (row[0] or "").strip() if row else ""
    except Exception:
        return ""


def handle(question, req, *, user_id, dept_ids=None, is_banqt=False,
           can_finance=False) -> dict:
    """Tạo bản nháp thật rồi trả lời chat bằng kết quả — hoặc nói rõ vì sao chưa.

    Trả dict cùng dạng với structured_answer để rag.prepare dùng làm câu trả
    lời trực tiếp (cả hai đường thường và stream cùng hưởng, lịch sử tự lưu).
    """
    from app import draft_api  # import muộn để tránh vòng rag ↔ draft_api

    if req.get("tu_do"):
        return _handle_tu_do(question, req, user_id=user_id, dept_ids=dept_ids,
                             is_banqt=is_banqt, can_finance=can_finance)

    docs = _visible_documents(dept_ids, is_banqt, can_finance)
    if req.get("like_name"):
        # Khuôn đầy đủ: bám tài liệu của B làm mẫu.
        template_doc, is_fallback, person_docs = pick_sources(
            docs, req["kind"], req["for_name"], req["like_name"])
        if not template_doc:
            return _missing_answer(req)
    else:
        # Khuôn đơn "tạo <loại> cho A": dùng MẪU CHUẨN trong kho.
        if req.get("for_self"):
            full_name = _user_full_name(user_id)
            if full_name:
                # for_name (đã fold) dùng để SO KHỚP; display giữ nguyên dấu.
                req = {**req, "for_name": _fold(full_name),
                       "display_name": full_name}
        template_doc = pick_template(docs, req["kind"])
        is_fallback = False
        person_docs = pick_person_docs(docs, req["for_name"])
        if not template_doc:
            return _missing_template_answer(req)

    for_display = req.get("display_name") or req["for_name"].title()
    employee = _employee_info(req["for_name"])
    if employee and employee.get("ho_ten"):
        for_display = employee["ho_ten"]

    title = f"{req['kind_label'].capitalize()} — {for_display} (theo mẫu {template_doc[1]})"
    source_ids = [template_doc[0]] + [doc_id for doc_id, _ in person_docs]
    input_data = {"soan_cho": for_display}
    if req.get("like_name"):
        input_data["theo_mau_cua"] = req["like_name"].title()
    else:
        input_data["theo_mau"] = template_doc[1]
    if employee:
        input_data.update({k: v for k, v in employee.items() if v})
    if req.get("like_name"):
        instructions = (
            f"Soạn {req['kind_label']} cho {for_display}, bám NGUYÊN cấu trúc, thứ tự "
            f"điều khoản và văn phong của tài liệu mẫu ({template_doc[1]}). Thay toàn bộ "
            f"thông tin cá nhân của người trong mẫu bằng dữ liệu đã xác minh của "
            f"{for_display} lấy từ DỮ LIỆU ĐÃ XÁC MINH và các nguồn hồ sơ đính kèm. "
            f"Thông tin nào của {for_display} không có trong nguồn (số CCCD, địa chỉ, "
            f"mức lương, ngày ký…) thì ghi [CẦN BỔ SUNG: …] — tuyệt đối không lấy "
            f"số liệu của người trong mẫu điền sang."
        )
    else:
        instructions = (
            f"Soạn {req['kind_label']} cho {for_display} DỰA TRÊN mẫu chuẩn "
            f"({template_doc[1]}): giữ NGUYÊN cấu trúc, thứ tự điều khoản và văn "
            f"phong của mẫu. Điền thông tin của {for_display} từ DỮ LIỆU ĐÃ XÁC "
            f"MINH và các nguồn hồ sơ đính kèm vào đúng các chỗ trống của mẫu. "
            f"Chỗ trống nào chưa có dữ liệu (số CCCD, địa chỉ, mức lương, ngày "
            f"ký…) thì giữ nguyên dạng [CẦN BỔ SUNG: …] để người dùng tự điền — "
            f"tuyệt đối không tự bịa giá trị."
        )

    user = {"id": user_id}
    with db.session(role="internal", admin=True) as conn:
        template = draft_api._template(conn, None)
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO document_drafts
                     (title,document_type,template_id,instructions,input_data,created_by)
                     VALUES (%s,%s,%s,%s,%s,%s) RETURNING id, coalesce(current_version,0)""",
                (title[:200], "contract", template["id"], instructions,
                 json.dumps(input_data, ensure_ascii=False), user_id),
            )
            draft_id, current_version = cur.fetchone()
        db.audit(conn, user_id, "create_draft", "document_drafts", draft_id,
                 {"from": "chat", "source_document_ids": source_ids})
        evidence = drafting.retrieve_evidence(conn, source_ids, f"{title} {question}")

    result = drafting.generate_content(
        title=title, instructions=instructions, input_data=input_data,
        body_template=template["body_template"],
        template_instructions=template["system_instructions"],
        evidence=evidence, missing_fields=None, model=None,
    )
    version_no = draft_api._save_version(
        user, {"id": draft_id, "current_version": current_version}, result,
        source_ids, instructions, input_data, "Tạo từ khung chat")

    placeholders = result.get("placeholder_count") or 0
    lines = [
        f"Đã tạo bản nháp **{title}** (phiên bản {version_no}).",
        f"- Mẫu áp dụng: **{template_doc[1]}**"
        + (" *(hồ sơ gần nhất tìm được — kho chưa có đúng loại này của "
           f"{req['like_name'].title()})*" if is_fallback else ""),
    ]
    if employee:
        detail = ", ".join(f"{k.replace('_', ' ')}: {v}"
                           for k, v in employee.items() if v)
        lines.append(f"- Dữ liệu đã xác minh từ sổ nhân sự: {detail}")
    if person_docs:
        lines.append("- Hồ sơ nguồn của " + for_display + ": "
                     + ", ".join(t for _, t in person_docs))
    else:
        lines.append(f"- ⚠ Chưa có hồ sơ nào của {for_display} trong kho — các "
                     "trường cá nhân sẽ ở dạng [CẦN BỔ SUNG].")
    if placeholders:
        lines.append(f"- Còn **{placeholders} chỗ [CẦN BỔ SUNG]** cần bạn điền/kiểm.")
    if result.get("grounding_status") != "grounded":
        lines.append("- Bản nháp cần người rà lại trước khi dùng (chưa đủ căn cứ "
                     "cho mọi đoạn).")
    lines.append(f"\n👉 Mở tab **Soạn tài liệu** → “{title}” để rà nội dung, bấm "
                 f"**Điền chỗ trống** cho các mục [CẦN BỔ SUNG] rồi **Tải DOCX**. "
                 f"(API: `GET /api/drafts/{draft_id}/export?format=docx`)")

    evid = [{
        "kind": "system", "title": "Bản nháp soạn thảo",
        "source_locator": f"document_drafts#{draft_id}",
        "quote": f"template={template_doc[1]}; nguồn={len(source_ids)}; "
                 f"placeholder={placeholders}",
        "as_of": None,
    }]
    return {"answer": "\n".join(lines), "answer_mode": "structured",
            "grounding_status": "verified", "evidence": evid,
            "state": {}, "draft_id": draft_id}


# Số văn bản luật tối đa kéo vào làm bằng chứng cho một bản nháp tự do.
_LUAT_CHO_BAN_NHAP = 3


def _luat_lien_quan(kind_label: str, boi_canh: str, dept_ids, is_banqt, can_finance):
    """Mã các văn bản luật liên quan nhất (qua kệ luật) để model dẫn điều thật."""
    from app import rag  # nạp trễ: rag nhập chat_draft
    try:
        hits = rag.retrieve(f"{kind_label} {boi_canh}", "internal", dept_ids=dept_ids,
                            is_banqt=is_banqt, can_finance=can_finance, top_k=8,
                            doc_types=["law"], lexical="or", neighbours=False)
    except Exception:
        return []
    ids = []
    for c in hits:
        d = c.get("document_id")
        if d and d not in ids:
            ids.append(d)
    return ids[:_LUAT_CHO_BAN_NHAP]


def _handle_tu_do(question, req, *, user_id, dept_ids=None, is_banqt=False,
                  can_finance=False) -> dict:
    """Soạn văn bản tố tụng / đơn từ / công văn từ một câu lệnh có bối cảnh.

    Kho có mẫu đúng loại thì bám mẫu; không có thì soạn theo KHUNG thể thức
    thông dụng — không từ chối như khuôn "cho <tên>" (nhân viên tố tụng cần
    bản dự thảo có bố cục để sửa tiếp, xem phản hồi Huế 29/08/2026).
    """
    from app import draft_api  # import muộn để tránh vòng rag ↔ draft_api

    kind, kind_label, boi_canh = req["kind"], req["kind_label"], req["boi_canh"]
    docs = _visible_documents(dept_ids, is_banqt, can_finance)
    template_doc = pick_template(docs, kind)
    luat_ids = _luat_lien_quan(kind_label, boi_canh, dept_ids, is_banqt, can_finance)
    source_ids = ([template_doc[0]] if template_doc else []) + luat_ids
    muc = muc_bat_buoc(kind)
    khung = khung_van_ban(kind)

    title = f"{kind_label.capitalize()} — {(req.get('boi_canh_ngan') or boi_canh)[:70]}"
    instructions = (
        f"Soạn {kind_label} theo bối cảnh người dùng nêu: «{boi_canh}». "
        + (f"Bám cấu trúc, thứ tự mục và văn phong của mẫu ({template_doc[1]}). "
           if template_doc else
           "Kho chưa có mẫu đúng loại — soạn theo KHUNG TÀI LIỆU bên dưới. ")
        + (f"Bắt buộc đủ các mục: {', '.join(muc)}. " if muc else "")
        + "Mọi tên, số, ngày, số tiền không có trong bối cảnh hoặc nguồn thì ghi "
          "[CẦN BỔ SUNG: …], không tự bịa. Phần lý do/căn cứ chỉ dẫn điều luật CÓ "
          "trong bằng chứng và gắn [Nn]; bằng chứng có điều luật quy định nội dung "
          "bắt buộc của loại văn bản này thì bám theo. Lập luận phải bám đúng dữ kiện "
          "trong bối cảnh, mỗi lý do một đoạn."
    )
    input_data = {"loai_van_ban": kind_label, "boi_canh": boi_canh}
    if template_doc:
        input_data["theo_mau"] = template_doc[1]

    user = {"id": user_id}
    with db.session(role="internal", admin=True) as conn:
        template = draft_api._template(conn, None)
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO document_drafts
                     (title,document_type,template_id,instructions,input_data,created_by)
                     VALUES (%s,%s,%s,%s,%s,%s) RETURNING id, coalesce(current_version,0)""",
                (title[:200], "other", template["id"], instructions,
                 json.dumps(input_data, ensure_ascii=False), user_id),
            )
            draft_id, current_version = cur.fetchone()
        db.audit(conn, user_id, "create_draft", "document_drafts", draft_id,
                 {"from": "chat", "source_document_ids": source_ids, "tu_do": True})
        evidence = (drafting.retrieve_evidence(conn, source_ids, f"{title} {question}")
                    if source_ids else [])

    result = drafting.generate_content(
        title=title, instructions=instructions, input_data=input_data,
        body_template=(template["body_template"] if template_doc else (khung or template["body_template"])),
        template_instructions=template["system_instructions"],
        evidence=evidence, missing_fields=None, model=None,
    )
    version_no = draft_api._save_version(
        user, {"id": draft_id, "current_version": current_version}, result,
        source_ids, instructions, input_data, "Tạo từ khung chat")

    placeholders = result.get("placeholder_count") or 0
    lines = [f"Đã tạo bản nháp **{title}** (phiên bản {version_no})."]
    if template_doc:
        lines.append(f"- Mẫu áp dụng: **{template_doc[1]}**")
    else:
        lines.append(f"- Kho chưa có mẫu {kind_label}; bản nháp soạn theo khung thể thức "
                     f"thông dụng ({len(muc)} mục). Muốn bám mẫu riêng của công ty thì thả "
                     f"file mẫu vào ngăn `6. THƯ MẪU - BIỂU MẪU/`.")
    if luat_ids:
        lines.append(f"- Căn cứ pháp lý kéo từ kệ luật: {len(luat_ids)} văn bản — chỉ điều "
                     "nào có trong bằng chứng mới được dẫn.")
    if placeholders:
        lines.append(f"- Còn **{placeholders} chỗ [CẦN BỔ SUNG]** cần bạn điền/kiểm.")
    if result.get("grounding_status") != "grounded":
        lines.append("- Bản nháp cần luật sư rà lại trước khi dùng.")
    lines.append(f"\n👉 Mở tab **Soạn tài liệu** → “{title}” để sửa, bấm **Điền chỗ "
                 f"trống** rồi **Tải DOCX** hoặc **Tải PDF**.")
    evid = [{
        "kind": "system", "title": "Bản nháp soạn thảo",
        "source_locator": f"document_drafts#{draft_id}",
        "quote": f"loại={kind_label}; mẫu={(template_doc[1] if template_doc else 'khung chuẩn')}; "
                 f"luật={len(luat_ids)}; placeholder={placeholders}",
        "as_of": None,
    }]
    return {"answer": "\n".join(lines), "answer_mode": "structured",
            "grounding_status": "verified", "evidence": evid,
            "state": {}, "draft_id": draft_id}
