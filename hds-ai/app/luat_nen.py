"""
luat_nen.py — LUẬT NỀN theo chủ đề + ĐIỀU NỀN theo câu hỏi.

Vì sao có (đo bộ câu hỏi mẫu 05/10/2026 trên kho 61 nghìn văn bản luật): câu
hỏi luật phổ thông KHÔNG nêu tên văn bản — "người lao động muốn nghỉ việc phải
báo trước bao nhiêu ngày?" — thì vector so cả kệ luật và kéo về nghị định cũ,
quyết định UBND, thông tư hướng dẫn; điều luật gốc (Điều 35 BLLĐ) không có
trong 8 nguồn đầu. Nhưng khi tìm KHOANH trong đúng bộ luật nền, điều cần dẫn
đứng top 6 ở 5/7 câu trượt. Vậy: nhận ra chủ đề → bộ luật nền → tìm riêng
trong bộ luật đó; chủ đề phổ biến có sẵn ĐIỀU NỀN (bảng tra của luật sư) để
điều đúng chắc chắn có mặt dù vector xếp nó thấp.

Nguyên tắc:
  · chỉ CHÈN THÊM nguồn, không loại nguồn nào (cùng nguyên tắc các lượt phụ
    khác trong rag.prepare);
  · cụm chủ đề phải ĐẶC TRƯNG cho bộ luật — "hợp đồng" trần không đứng một
    mình; tối đa 2 bộ luật nền mỗi câu;
  · bộ luật nhận theo SỐ HIỆU + TRÍCH YẾU (id đổi khi học lại; 11/VBHN-VPQH
    vừa là văn bản hợp nhất Luật SHTT vừa là của BLTTDS — trích yếu phân biệt);
  · bảng điều nền chỉ ghi điều chắc chắn đúng, đối chiếu văn bản trong kho.
"""
from __future__ import annotations

import re
import threading
import time
import unicodedata


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFD", (s or "").lower())
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = s.replace("đ", "d")
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s/.-]", " ", s)).strip()


# khoá → (số hiệu ưu tiên — bản hợp nhất mới nhất trước, trích yếu phải chứa)
LUAT = {
    "blld": (("45/2019/QH14",), "lao dong"),
    "blds": (("91/2015/QH13",), "dan su"),
    "ltm": (("17/VBHN-VPQH", "36/2005/QH11"), "thuong mai"),
    "ldn": (("67/VBHN-VPQH", "59/2020/QH14"), "doanh nghiep"),
    "shtt": (("11/VBHN-VPQH", "50/2005/QH11"), "so huu tri tue"),
    "blttds": (("11/VBHN-VPQH", "92/2015/QH13"), "to tung dan su"),
    # Luật Đầu tư 61/2020/QH14 hết hiệu lực từ 01/03/2026 — Luật 143/2025/QH15
    # thay thế và ĐÁNH SỐ LẠI toàn bộ (Điều 26 cũ "thủ tục góp vốn, mua cổ
    # phần" là Điều 21 mới). Trỏ bản cũ là kéo điều đã chết vào mọi câu đầu tư
    # (đo 40 kịch bản 07/10/2026: 1.2, 4.7–4.10).
    "ldt": (("143/2025/QH15",), "dau tu"),
    "ldd": (("31/2024/QH15",), "dat dai"),
    # Trọng tài (12/10/2026, câu 2.1 "VIAC hoặc Toà án"): luật + nghị quyết
    # hướng dẫn của HĐTP — điều quyết định nằm ở nghị quyết (Điều 2–4).
    "lttm": (("54/2010/QH12",), "trong tai"),
    "nq_tt": (("01/2014/NQ-HĐTP",), "trong tai"),
    # Thuế hộ kinh doanh (12/10/2026, "hộ kinh doanh đang được miễn thuế bao
    # nhiêu" — bot dẫn Nghị định 96/CP năm 1995). Trích yếu hai văn bản này
    # trong kho trống (tên tệp "68-2026-NĐ-CP_05032026") nên để "" — số hiệu đã
    # là duy nhất. Ngưỡng 500 triệu ở Nghị định 68 đã bị Nghị định 141/2026/NĐ-CP
    # sửa thành 01 tỷ; Điều 7 Luật 109 bị Luật 09/2026/QH16 sửa — rag.prepare tự
    # kéo đoạn sửa đổi (chen_doan_sua_doi), đừng trỏ thẳng bảng này vào chúng.
    "nd_hkd": (("68/2026/NĐ-CP",), ""),
    "tncn": (("109/2025/QH15",), ""),
}

TEN_LUAT = {
    "blld": "Bộ luật Lao động 2019", "blds": "Bộ luật Dân sự 2015",
    "ltm": "Luật Thương mại 2005", "ldn": "Luật Doanh nghiệp 2020",
    "shtt": "Luật Sở hữu trí tuệ", "blttds": "Bộ luật Tố tụng dân sự 2015",
    "ldt": "Luật Đầu tư 2025", "ldd": "Luật Đất đai 2024",
    "lttm": "Luật Trọng tài thương mại 2010",
    "nq_tt": "Nghị quyết 01/2014/NQ-HĐTP hướng dẫn Luật Trọng tài thương mại",
    "nd_hkd": "Nghị định 68/2026/NĐ-CP về thuế hộ kinh doanh, cá nhân kinh doanh",
    "tncn": "Luật Thuế thu nhập cá nhân 2025",
}

# Cụm chủ đề (đã bỏ dấu, chữ thường) → bộ luật nền.
CHU_DE = {
    "blld": ("nguoi lao dong", "nguoi su dung lao dong", "hop dong lao dong",
             "thu viec", "sa thai", "ky luat lao dong", "nghi viec", "thoi viec",
             "mat viec", "tien luong", "lam them gio", "thoi gio lam viec",
             "nghi phep", "bo viec", "cham dut hop dong lao dong", "tro cap thoi viec"),
    "blds": ("dat coc", "thua ke", "di san", "di chuc", "hop dong vay", "cho vay",
             "lai suat", "giao dich dan su", "boi thuong thiet hai", "quyen so huu",
             "bat kha khang", "hop dong dan su", "huy bo hop dong", "the chap",
             "cam co", "thoi hieu khoi kien ve hop dong", "bo luat dan su",
             "gioi han trach nhiem", "thiet hai", "loi nhuan bi mat",
             "chi nhanh", "phap nhan", "van phong dai dien"),
    "ltm": ("thuong mai", "thuong nhan", "mua ban hang hoa", "nhuong quyen",
            "dai ly thuong mai", "logistics", "giao hang", "nha cung cap",
            "phat hop dong", "mien trach nhiem",
            # "giới hạn phạt vi phạm theo pháp luật Việt Nam" (EN-D3 05/10) —
            # trần 8% của Điều 301 là thứ người hỏi cần đối chiếu.
            "gioi han phat vi pham", "muc phat vi pham", "phat vi pham hop dong",
            "phat cham tra", "tran phat vi pham"),
    "ldn": ("doanh nghiep", "cong ty tnhh", "cong ty trach nhiem huu han",
            "cong ty co phan", "co dong", "von dieu le", "gop von",
            "hoi dong thanh vien", "hoi dong quan tri", "giai the",
            "nguoi dai dien theo phap luat", "thanh lap cong ty", "giam von",
            "tang von", "phat hanh co phan", "ten doanh nghiep", "chuyen doi",
            "chuyen nhuong co phan", "chao ban co phan", "dai hoi dong co dong",
            "von gop", "phan von gop", "tai san gop von"),
    "shtt": ("nhan hieu", "sang che", "kieu dang cong nghiep", "quyen tac gia",
             "ban quyen", "so huu tri tue", "van bang bao ho", "chi dan dia ly",
             "giai phap huu ich"),
    "blttds": ("khoi kien", "khang cao", "to tung dan su", "thu ly", "an phi",
               "bien phap khan cap tam thoi", "phuc tham", "so tham",
               "giam doc tham", "nguyen don", "bi don", "phong toa", "duong su"),
    "ldt": ("nha dau tu nuoc ngoai", "du an dau tu", "chu truong dau tu",
            "giay chung nhan dang ky dau tu", "uu dai dau tu", "von dau tu nuoc ngoai",
            "chap thuan chu truong", "lua chon nha dau tu", "tien do thuc hien",
            "tiep can thi truong", "dieu chinh du an", "chuyen nhuong du an",
            "hop dong bcc", "dau tu ra nuoc ngoai", "nha dau tu han quoc",
            "nha dau tu nhat ban", "nha dau tu trung quoc", "nha dau tu singapore"),
    "ldd": ("quyen su dung dat", "giao dat", "thu hoi dat", "thue dat",
            "dat nong nghiep", "so do", "chuyen muc dich su dung dat"),
    "lttm": ("trong tai", "thoa thuan trong tai", "phan quyet trong tai",
             "trung tam trong tai", "hoi dong trong tai", "viac"),
    "nq_tt": ("trong tai", "thoa thuan trong tai", "phan quyet trong tai",
              "trung tam trong tai", "hoi dong trong tai", "viac"),
    "nd_hkd": ("ho kinh doanh", "ca nhan kinh doanh", "thue khoan", "hkd"),
    "tncn": ("thue thu nhap ca nhan", "tncn", "giam tru gia canh",
             "ho kinh doanh", "ca nhan kinh doanh"),
}

# Điều nền: (bộ luật, mẫu trên câu đã bỏ dấu, các điều). Mỗi dòng đã đối chiếu
# với văn bản đang có trong kho ngày 05/10/2026.
DIEU_NEN = (
    ("blld", r"bao truoc|nghi viec|don phuong cham dut|thoi viec", (35, 36)),
    ("blld", r"thu viec", (24, 25, 26, 27)),
    ("blld", r"sa thai|bo viec", (125,)),
    ("blld", r"ky luat lao dong", (124, 125)),
    ("blld", r"trai phap luat|huy quyet dinh", (41,)),
    ("blld", r"thoi han hop dong|xac dinh thoi han|loai hop dong", (20,)),
    ("blld", r"lam them", (107,)),
    ("blld", r"thoi gio lam viec|gio lam viec|gio moi ngay|gio/ngay", (105,)),
    ("blld", r"tro cap thoi viec", (46,)),
    ("blld", r"tro cap mat viec|cat giam|thay doi co cau", (42, 47)),
    ("blld", r"bi mat kinh doanh|bi mat cong nghe", (21,)),
    ("blds", r"dat coc", (328,)),
    ("blds", r"lai suat|cho vay|hop dong vay", (468,)),
    ("blds", r"thoi hieu", (429, 155)),
    ("blds", r"thua ke|di san", (623,)),
    ("blds", r"phat vi pham", (418,)),
    ("blds", r"boi thuong thiet hai|gioi han trach nhiem|loi nhuan bi mat|thiet hai", (360, 419)),
    ("blds", r"bat kha khang", (156, 351)),
    ("blds", r"huy bo hop dong", (423, 424, 427)),
    ("blds", r"hoan canh thay doi|thay doi co ban|bien dong gia", (420,)),
    ("blds", r"phap nhan|chi nhanh|van phong dai dien", (74, 84)),
    ("ltm", r"phat vi pham|muc phat", (301, 300)),
    ("ltm", r"boi thuong", (302, 303, 307)),
    ("ltm", r"mien trach|bat kha khang", (294,)),
    ("ltm", r"thoi hieu", (319,)),
    ("ldn", r"gop von|thoi han gop", (47, 75, 113)),
    ("ldn", r"tai san gop von|chuyen quyen so huu|gop von bang", (35,)),
    ("ldn", r"giai the", (207, 208)),
    ("ldn", r"giam von|hoan tra (?:mot phan )?von", (68, 112)),
    # Đã đối chiếu tên điều trong 67/VBHN-VPQH ngày 07/10/2026.
    ("ldn", r"ten doanh nghiep|dat ten|ten cong ty|trung ten|ten trung|gay nham lan|ten viet tat",
     (37, 38, 39, 41)),
    ("ldn", r"chuyen doi", (202, 203, 204, 205)),
    ("ldn", r"chia cong ty|tach cong ty|hop nhat cong ty|sap nhap", (198, 199, 200, 201)),
    ("ldn", r"quyen thanh lap|khong duoc (?:thanh lap|gop von)|cam thanh lap|can bo|cong chuc|vien chuc",
     (17,)),
    ("ldn", r"hop hoi dong thanh vien|trieu tap hop", (57, 58, 59)),
    ("ldn", r"chuyen nhuong co phan", (127,)),
    ("ldn", r"mua lai phan von|thoai von|be tac|chuyen nhuong phan von", (51, 52)),
    ("ldn", r"chao ban|phat hanh rieng le|rieng le", (123, 125)),
    ("ldn", r"dai hoi dong co dong|nghi quyet .{0,30}thong qua|ty le bieu quyet", (148,)),
    ("ldn", r"phat hanh co phan", (111, 74)),
    ("ldn", r"bien ban hop", (60,)),
    ("ldn", r"nguoi dai dien theo phap luat", (12,)),
    ("ldn", r"ho so dang ky|thanh lap cong ty|dang ky doanh nghiep|cap giay chung nhan dang ky doanh nghiep",
     (21, 22, 26)),
    ("shtt", r"tuong tu|nham lan|trung|kha nang phan biet|dang ky duoc|da co nhan hieu"
             r"|chi gom (?:chu|so|hinh)|chu don gian",
     (74,)),
    ("shtt", r"hieu luc|bao lau|thoi han bao ho|bao ho bao lau", (93,)),
    ("shtt", r"gia han", (94,)),
    ("shtt", r"tham dinh|xu ly don|thu tuc dang ky", (119,)),
    ("shtt", r"tinh moi", (60,)),
    ("shtt", r"cham dut hieu luc|khong su dung", (95,)),
    ("shtt", r"chuyen quyen su dung|cap quyen su dung|li.?xang|cap phep su dung|hop dong su dung",
     (142,)),
    ("shtt", r"nhan hieu noi tieng", (75,)),
    # Điều 112 (ý kiến người thứ ba) và 112a (phản đối đơn) — dieu_cua_doan đọc
    # "Điều 112a" thành 112 nên một số điều phủ cả hai.
    ("shtt", r"y kien (?:cua )?(?:nguoi|ben) thu ba|phan doi don|cong bao so huu cong nghiep", (112,)),
    ("blttds", r"don khoi kien|noi dung don|nop don", (189, 190)),
    ("blttds", r"khang cao", (271, 272, 273)),
    ("blttds", r"bien phap khan cap", (111, 114)),
    ("blttds", r"phong toa", (124, 125)),
    ("blttds", r"bien phap bao dam", (136,)),
    ("blttds", r"duong su|tu cach (?:to tung|khoi kien|bi don|nguyen don)|tham gia to tung", (68,)),
    ("blttds", r"huy ban an", (310,)),
    ("blld", r"phuong an su dung lao dong", (44,)),
    # Luật Đầu tư 143/2025/QH15 — số điều MỚI, đối chiếu kho ngày 07/10/2026.
    ("ldt", r"nganh nghe cam", (6,)),
    ("ldt", r"(?:nganh nghe|kinh doanh) co dieu kien", (7,)),
    ("ldt", r"tiep can thi truong|ty le so huu|nha dau tu nuoc ngoai|von dau tu nuoc ngoai", (8,)),
    ("ldt", r"uu dai dau tu|ho tro dau tu", (14, 15)),
    ("ldt", r"thanh lap (?:to chuc kinh te|cong ty|doanh nghiep)", (19, 20)),
    ("ldt", r"gop von|mua co phan|mua phan von gop|mua lai", (21,)),
    ("ldt", r"hop dong bcc|hop tac kinh doanh", (22, 37)),
    ("ldt", r"lua chon nha dau tu", (23,)),
    ("ldt", r"chu truong dau tu", (24, 25)),
    ("ldt", r"giay chung nhan dang ky dau tu|chung nhan dau tu|\birc\b", (26, 27)),
    ("ldt", r"thu tuc dau tu dac biet", (28,)),
    ("ldt", r"thoi han hoat dong|tien do thuc hien", (31,)),
    ("ldt", r"dieu chinh", (33,)),
    ("ldt", r"chuyen nhuong (?:\w+ ){0,3}du an", (34,)),
    ("ldt", r"ngung hoat dong", (35,)),
    ("ldt", r"cham dut hoat dong", (36,)),
    ("ldt", r"dau tu ra nuoc ngoai", (39, 42)),
    # Trọng tài — tên điều đối chiếu 54/2010/QH12 (id 35870) và 01/2014/NQ-HĐTP
    # (id 35871) ngày 12/10/2026.
    ("lttm", r"thoa thuan trong tai|hieu luc|vo hieu", (5, 16, 18, 19)),
    ("lttm", r"toa an|khoi kien|thu ly", (6,)),
    ("nq_tt", r"thoa thuan trong tai|toa an|khoi kien|tham quyen|vo hieu", (2, 3, 4)),
    # Nghị định 68/2026/NĐ-CP (id 45471): Điều 3 thuế GTGT, Điều 4 thuế TNCN của
    # hộ/cá nhân kinh doanh — đối chiếu kho ngày 12/10/2026.
    ("nd_hkd", r"mien|khong phai nop|khong chiu thue|nguong|doanh thu|bao nhieu|thue", (3, 4)),
    # Luật 109/2025/QH15 Điều 7: thuế TNCN với thu nhập từ kinh doanh.
    ("tncn", r"kinh doanh|hkd", (7,)),
)

# 3 chứ không 2 (07/10/2026): tình huống thật hay chạm 3 bộ luật — câu 2.8 cần
# BLDS (bất khả kháng, hoàn cảnh thay đổi) + LTM (miễn trách) mà LDN chen lên
# vì có chữ "doanh nghiệp", LTM bị gạt và Điều 294 không bao giờ có mặt.
TOI_DA_LUAT = 3       # tối đa bộ luật nền mỗi câu
DOAN_CHUNG = 3        # ngoài điều nền, lấy thêm bấy nhiêu đoạn khớp nhất


def chu_de_luat(question: str) -> list:
    """Các bộ luật nền câu hỏi chạm tới, điểm cao trước. Hàm thuần.

    Điểm = tổng SỐ CHỮ của các cụm khớp, không phải số cụm: cụm dài là cụm
    đặc trưng. Đếm cụm thì "thương mại" (trong "đất thương mại dịch vụ") và
    "doanh nghiệp" ngang hàng "chấp thuận chủ trương đầu tư" và thắng nhờ thứ
    tự bảng — câu 4.8 (07/10/2026) mất hẳn Luật Đầu tư."""
    q = f" {_fold(question)} "
    diem = []
    for i, (khoa, cum) in enumerate(CHU_DE.items()):
        n = sum(len(c.split()) for c in cum if f" {c} " in q)
        if n:
            diem.append((-n, i, khoa))
    return [k for _n, _i, k in sorted(diem)][:TOI_DA_LUAT]


def dieu_nen(question: str, khoa: str) -> list:
    """Các điều nền của bộ luật `khoa` mà câu hỏi gợi tới (giữ thứ tự bảng)."""
    q = _fold(question)
    ra = []
    for k, mau, cac_dieu in DIEU_NEN:
        if k == khoa and re.search(mau, q):
            for d in cac_dieu:
                if d not in ra:
                    ra.append(d)
    return ra


def dieu_cua_doan(c) -> int | None:
    """Số Điều của một đoạn luật (nhãn section_title hoặc dòng nhãn đầu đoạn)."""
    for s in (c.get("section_title") or "", (c.get("content") or "")[:300]):
        m = re.search(r"Điều\s+(\d+)[a-zđ]?\s*(?:\]|—|$|\(|phần|\.)", s)
        if m:
            return int(m.group(1))
    return None


# Tiêu đề Điều kiểu Markdown giữa đoạn ("## Điều 3. Thuế giá trị gia tăng"):
# văn bản luật nạp từ tệp .md không được cắt theo Điều, một đoạn chứa cuối Điều
# 2 và cả Điều 3 nhưng nhãn chỉ ra "Điều 2" (Nghị định 68/2026/NĐ-CP, 12/10/2026).
_RE_TIEU_DE_MD = re.compile(r"(?:^|\n|##)\s*Điều\s+(\d+)[a-zđ]?\.\s")


def cac_dieu_cua_doan(c) -> list:
    """Mọi số Điều có TIÊU ĐỀ trong đoạn: nhãn trước, rồi tiêu đề "## Điều n."
    trong nội dung. Hàm thuần."""
    ra = []
    d = dieu_cua_doan(c)
    if d is not None:
        ra.append(d)
    for m in _RE_TIEU_DE_MD.finditer(c.get("content") or ""):
        n = int(m.group(1))
        if n not in ra:
            ra.append(n)
    return ra


def chon_doan(chunks, cac_dieu, them=DOAN_CHUNG) -> list:
    """Từ kết quả tìm KHOANH trong một bộ luật: đoạn của điều nền trước (điểm
    khớp cao trước — "thử việc" gợi Điều 24–27 mà câu hỏi thời gian thử việc
    cần Điều 25 đứng đầu), rồi `them` đoạn điểm cao nhất còn lại. Hàm thuần."""
    uniq = {}
    for c in chunks or []:
        if c["chunk_id"] not in uniq or (c.get("score") or 0) > (uniq[c["chunk_id"]].get("score") or 0):
            uniq[c["chunk_id"]] = c
    chunks = list(uniq.values())
    theo_dieu = {}
    for c in chunks:
        for d in cac_dieu_cua_doan(c):
            theo_dieu.setdefault(d, []).append(c)
    ra, da = [], set()
    for d in cac_dieu or []:
        for c in theo_dieu.get(d, []):
            if c["chunk_id"] not in da:
                da.add(c["chunk_id"])
                ra.append(c)
    ra.sort(key=lambda c: -(c.get("score") or 0))
    con = sorted((c for c in chunks if c["chunk_id"] not in da),
                 key=lambda c: -(c.get("score") or 0))
    return ra + con[:them]


# ---------------------------------------------------------------- id bộ luật
_cache = {"at": 0.0, "ids": {}}
_lock = threading.Lock()
TTL = 600


def doc_ids(db_session_factory) -> dict:
    """{khoá: id tài liệu} của các bộ luật nền đang phục vụ (đã duyệt). Đệm 10
    phút; lỗi CSDL → {} (prepare chạy như chưa có tính năng)."""
    now = time.time()
    with _lock:
        if _cache["ids"] and now - _cache["at"] < TTL:
            return dict(_cache["ids"])
    ids = {}
    try:
        with db_session_factory() as conn:
            with conn.cursor() as cur:
                for khoa, (so_hieu, trich) in LUAT.items():
                    cur.execute(
                        """SELECT id, so_hieu, trich_yeu, title FROM documents
                            WHERE doc_type='law' AND coalesce(active,true)
                              AND approved AND label_verified
                              AND so_hieu = ANY(%s)""", (list(so_hieu),))
                    hop = [r for r in cur.fetchall()
                           if trich in _fold(f"{r[2] or ''} {r[3] or ''}")]
                    if not hop:
                        continue
                    # Ưu tiên theo thứ tự số hiệu (bản hợp nhất mới nhất trước),
                    # rồi tệp chuẩn hoá tên "0X_…", rồi id nhỏ.
                    hop.sort(key=lambda r: (list(so_hieu).index(r[1]),
                                            0 if re.match(r"^\d\d_", r[3] or "") else 1,
                                            r[0]))
                    ids[khoa] = hop[0][0]
    except Exception:  # noqa: BLE001
        return {}
    with _lock:
        _cache.update({"at": now, "ids": ids})
    return dict(ids)
