"""tich_hop.py — Cửa cho HỆ THỐNG NGOÀI (CRM, chatbot bên thứ ba) nói chuyện với kho.

Bối cảnh (28/09/2026): CRM của công ty sẽ là NƠI DUY NHẤT lưu và sửa hồ sơ
khách + hợp đồng; kho của trợ lý AI chỉ giữ một bản sao để trả lời. Hai hệ
thống đặt cùng máy chủ, CRM gọi các API ở đây (deploy/API_TICH_HOP.md).

Ba mảnh, để chung một mô-đun cho đọc một chỗ là hiểu hết:

1. KHOÁ API CÓ QUYỀN (bảng khoa_tich_hop). Khác khoá `hds_` của tài khoản
   khách (api._user_by_api_key — chỉ để hỏi đáp thay khách), khoá `hdsi_` ở
   đây KHÔNG gắn với người dùng mà gắn với một HỆ THỐNG, mang danh sách quyền
   (QUYEN) admin tick lúc cấp. Mất khoá thì thu hồi, cấp khoá mới cùng `nguon`
   — dữ liệu đã gửi vẫn nhận ra vì ánh xạ theo `nguon`, không theo khoá.

2. KHÁCH HÀNG: CRM tra/tạo khách theo MÃ (clients.code = số trong tên thư mục
   "1729. Công ty X"). Thiếu mã thì máy chủ cấp mã kế tiếp = lớn nhất hiện có
   + 1 — đếm cả mã trong CSDL LẪN mã trong tên thư mục trên đĩa: 1.237 thư
   mục khách trống chưa có bản ghi clients, cấp trùng mã một thư mục như vậy
   là bộ quét gán tệp của thư mục cũ sang khách mới.

3. TÀI LIỆU / BỘ HỒ SƠ: tệp CRM gửi được ĐẶT VÀO ĐÚNG THƯ MỤC KHÁCH trong kho
   (9. HỒ SƠ KHÁCH HÀNG/<mã>. <tên>/<thư mục con>/) rồi học bằng đúng đường
   của bộ quét (kho.hoc_file). Nhờ vậy nhãn, quyền, màn 360°, nút Tải về đều
   như tệp nhân viên tự thả vào kho; bộ quét 3 phút/lượt thấy tệp đã học
   (cùng danh tính local:<đường dẫn>, cùng md5) nên KHÔNG học lại. Ánh xạ
   (nguon, ma_ngoai) ↔ khoa_kho nằm ở bảng tich_hop_tai_lieu; cố ý KHÔNG lưu
   documents.id vì id đổi mỗi lần học lại (learn_one DELETE + INSERT).

4. (29/09/2026) MÁY CHỦ LÀ NƠI GIỮ BẢN GỐC DUY NHẤT, CRM CHỈ LÀ ĐẦU CẦU:
   CRM tải về được MỌI tệp của một hồ sơ (liet_ke_tep + duong_dan_trong),
   gắn mã ngoài cho tệp cũ (gan_ma), và bản cũ không bao giờ mất — trước khi
   ghi đè / đổi tên / gỡ, bản hiện tại được CHÉP sang data/_phien_ban/<nguồn>/
   <mã ngoài>/ (luu_phien_ban). Nhân viên có bộ API riêng như khách: "chủ hồ
   sơ" (chu_khach / chu_nhan_vien) là khái niệm chung, tài liệu của nhân viên
   cần thêm quyền employees:read (kiem_quyen_loai).

Chốt an toàn — đừng gỡ:
 · Không đặt danh tính kiểu 'crm:…' cho documents.drive_file_id: bộ quét từ
   chối chạy khi thấy danh tính không phải local: (chống nhân đôi kho).
 · Học chạy NỀN, một luồng, và GIỮ CÙNG KHOÁ FILE với bộ quét cron
   (/tmp/hds-ai-quet-kho.lock) để hai bộ học không chạy chồng lên cùng tệp.
 · Cùng khách + cùng md5 đã có trong kho → chỉ gắn ánh xạ, không chép tệp thứ
   hai (đường chuyển 7.000 tệp cũ sang CRM rồi CRM đẩy ngược lại).
 · Mọi đường dẫn tệp đều nằm DƯỚI thư mục khách; tên tệp/thư mục con đi qua
   cùng bộ lọc với giao diện web (kho.ten_thu_muc_hop_le).
"""
from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import json
import os
import queue
import re
import secrets
import shutil
import threading
import time
from pathlib import Path

from app import auto_learn, db, kho, xem_truoc
from app.local_learn import ALLOWED, LOCAL_PREFIX, file_md5, local_key
from app.quyen_tinh_nang import CLIENT_ROLES

TIEN_TO_KHOA = "hdsi_"
# Cùng tệp khoá với deploy/hoc-tu-thu-muc.sh --cron (flock -n): luồng học nền
# giữ khoá này lúc học nên lượt cron trùng giờ tự nhường, không chạy chồng.
KHOA_QUET = Path(os.getenv("HDS_KHOA_QUET_KHO", "/tmp/hds-ai-quet-kho.lock"))
SO_TEP_MOT_LAN = 50
# Mã số khách dài quá mức này coi là thư mục đặt nhầm (mốc ngày "20260912…"),
# không dùng làm gốc để cấp mã kế tiếp.
SO_CHU_SO_MA_KHACH_TOI_DA = 6

# Danh sách quyền tick được cho một khoá. Khoá là tên dùng trong CSDL và API —
# chỉ thêm, đừng đổi tên (đổi là khoá đã cấp mất quyền). 29/09/2026 đã đổi MỘT
# LẦN sang tiếng Anh theo yêu cầu chủ dự án (trước khi CRM tích hợp); mã cũ vẫn
# được hiểu qua QUYEN_CU và schema.sql đổi luôn dữ liệu đã lưu.
QUYEN = {
    "clients:read": {
        "ten": "Xem danh sách khách hàng",
        "mo_ta": "Tra mã, tên khách và số tài liệu đã có trong kho.",
    },
    "clients:write": {
        "ten": "Tạo khách hàng / cấp mã mới",
        "mo_ta": "Tạo bản ghi khách và thư mục khách trong kho; thiếu mã thì máy chủ cấp mã kế tiếp.",
    },
    "employees:read": {
        "ten": "Xem danh sách nhân viên",
        "mo_ta": "Tra mã, họ tên, thư mục hồ sơ nhân viên. Cần có để thao tác tài liệu nhân viên.",
    },
    "employees:write": {
        "ten": "Tạo / cập nhật nhân viên",
        "mo_ta": "Tạo nhân viên và thư mục hồ sơ trong ngăn nhân sự; thiếu mã thì máy chủ cấp mã NV kế tiếp.",
    },
    "documents:read": {
        "ten": "Xem và tải tài liệu",
        "mo_ta": "Danh sách tệp, trạng thái, tải tệp gốc và các phiên bản cũ.",
    },
    "documents:write": {
        "ten": "Gửi tài liệu / bộ hồ sơ vào kho",
        "mo_ta": "Tệp được đặt vào đúng thư mục hồ sơ và học ngay; gửi lại cùng mã là thay bản mới (bản cũ được lưu).",
    },
    "documents:delete": {
        "ten": "Gỡ tài liệu khỏi kho",
        "mo_ta": "Trợ lý ngừng dùng ngay; bản gốc được lưu lại, không xoá hẳn.",
    },
    "chat": {
        "ten": "Hỏi đáp với trợ lý",
        "mo_ta": "Dưới danh nghĩa tài khoản khách gắn với khoá — phạm vi dữ liệu đúng bằng của khách đó.",
    },
}

# Mã quyền tiếng Việt dùng tới 29/09/2026 → mã hiện hành. Khoá cấp trước ngày đó
# (hoặc CSDL chưa chạy lượt đổi trong schema.sql) vẫn giữ nguyên quyền.
QUYEN_CU = {"khach:doc": "clients:read", "khach:ghi": "clients:write",
            "nhan_vien:doc": "employees:read", "nhan_vien:ghi": "employees:write",
            "tai_lieu:doc": "documents:read", "tai_lieu:ghi": "documents:write",
            "tai_lieu:xoa": "documents:delete"}

# Bộ quyền gợi ý trên giao diện cấp khoá — admin vẫn sửa từng ô được.
BO_QUYEN_MAU = {
    "crm": {
        "ten": "CRM — hồ sơ khách, hợp đồng, nhân viên",
        "quyen": ["clients:read", "clients:write", "employees:read", "employees:write",
                  "documents:read", "documents:write", "documents:delete"],
    },
    "chatbot": {
        "ten": "Chatbot bên thứ ba — chỉ hỏi đáp",
        "quyen": ["chat"],
    },
    "doi_soat": {
        "ten": "Chỉ đọc — đối soát",
        "quyen": ["clients:read", "documents:read"],
    },
}

TRANG_THAI = ("da_nhan", "dang_hoc", "da_hoc", "cho_duyet", "loi", "da_go")
MO_TA_TRANG_THAI = {
    "da_nhan": "Đã nhận tệp, đang xếp hàng học",
    "dang_hoc": "Đang đọc và học nội dung",
    "da_hoc": "Đã học — trợ lý dùng được ngay",
    "cho_duyet": "Đã học nhưng chất lượng đọc thấp — chờ người duyệt trên web",
    "loi": "Không đọc được nội dung tệp",
    "da_go": "Đã gỡ khỏi kho",
}


class LoiTichHop(ValueError):
    """Lỗi trả thẳng cho hệ thống gọi; router đổi thành HTTP với mã `status`."""

    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


# ---------------------------------------------------------------------------
# Phần THUẦN — kiểm tra đầu vào, không chạm CSDL (test được trực tiếp)
# ---------------------------------------------------------------------------
RE_NGUON = re.compile(r"^[a-z0-9][a-z0-9_-]{1,29}$")
RE_MA_NGOAI = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,99}$")
RE_MA_KHACH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,29}$")
_RE_TEN_TEP_XAU = re.compile(r"[^\w\s.\-()À-ỹ]", re.UNICODE)
_RE_KY_TU_CAM_THU_MUC = re.compile(r'[\\/:*?"<>|]')


def chuan_hoa_nguon(nguon: str) -> str:
    """Tên nguồn = không gian mã ngoài: chữ thường, số, gạch; 2–30 ký tự."""
    s = (nguon or "").strip().lower()
    if not RE_NGUON.match(s):
        raise LoiTichHop("Tên nguồn chỉ gồm chữ thường, số, '-' hoặc '_' (2–30 ký tự), ví dụ: crm")
    return s


def chuan_hoa_quyen(quyen) -> list:
    """Danh sách quyền hợp lệ, khử trùng, theo thứ tự cố định của QUYEN."""
    if isinstance(quyen, str):
        quyen = quyen.split(",")
    ds = [str(q).strip() for q in (quyen or []) if str(q).strip()]
    ds = [QUYEN_CU.get(q, q) for q in ds]
    la = [q for q in ds if q not in QUYEN]
    if la:
        raise LoiTichHop("Quyền không hợp lệ: " + ", ".join(sorted(set(la))))
    if not ds:
        raise LoiTichHop("Khoá phải có ít nhất một quyền")
    return [q for q in QUYEN if q in ds]


def co_quyen(khoa: dict | None, quyen: str) -> bool:
    return bool(khoa) and quyen in (khoa.get("quyen") or [])


def bam_khoa(raw: str) -> str:
    return hashlib.sha256((raw or "").encode()).hexdigest()


def sinh_khoa() -> tuple[str, str, str]:
    """(khoá thật, bản băm để lưu, 12 ký tự đầu để nhận diện).

    Cùng lý do với auth.new_api_key: SHA-256 chứ không bcrypt vì phải tra
    được theo khoá; an toàn nằm ở 256 bit ngẫu nhiên, không ở độ chậm."""
    raw = TIEN_TO_KHOA + secrets.token_urlsafe(32)
    return raw, bam_khoa(raw), raw[:12]


def la_khoa_tich_hop(raw: str | None) -> bool:
    return bool(raw) and str(raw).startswith(TIEN_TO_KHOA)


def chuan_hoa_ma_ngoai(ma: str) -> str:
    s = (ma or "").strip()
    if not RE_MA_NGOAI.match(s):
        raise LoiTichHop("external_id chỉ gồm chữ, số, '.', '_', '-' — tối đa 100 ký tự")
    return s


def chuan_hoa_ma_khach(ma: str) -> str:
    s = (ma or "").strip()
    if not RE_MA_KHACH.match(s):
        raise LoiTichHop("Mã khách (code) chỉ gồm chữ, số, '.', '_', '-' — tối đa 30 ký tự")
    return s


def ma_ngoai_mac_dinh(ma_khach: str, ten_tep: str) -> str:
    """CRM không gửi ma_ngoai → suy từ mã khách + tên tệp, đủ ổn định để gửi
    lại cùng tệp là nhận ra (đổi tên tệp thì thành tài liệu mới)."""
    goc = f"{ma_khach}__{Path(ten_tep or '').name}"
    s = re.sub(r"[^A-Za-z0-9._\-]+", "_", goc).strip("._-")
    return (s or "tai-lieu")[:100]


def ten_tep_an_toan(ten: str) -> str:
    """Cùng luật với api._safe_filename: bỏ thành phần đường dẫn, thay ký tự lạ.
    Bỏ thêm tiền tố '~$' / '.' vì tệp mang tiền tố đó bị bộ quét bỏ qua."""
    ten = Path(ten or "").name
    ten = re.sub(r"^(~\$|\.+)", "", ten)
    ten = _RE_TEN_TEP_XAU.sub("_", ten).strip().lstrip(".")
    return ten[:150] or "tai_lieu"


def thu_muc_con_hop_le(rel: str) -> list:
    """'Hợp đồng/2026' → ['Hợp đồng', '2026']; tối đa 3 tầng, mỗi tầng qua
    đúng bộ lọc tên thư mục của giao diện web."""
    s = (rel or "").replace("\\", "/").strip().strip("/")
    if not s:
        return []
    doan = [p for p in s.split("/") if p.strip()]
    if len(doan) > 3:
        raise LoiTichHop("Thư mục con tối đa 3 tầng")
    try:
        return [kho.ten_thu_muc_hop_le(p) for p in doan]
    except kho.LoiKho as e:
        raise LoiTichHop(f"Thư mục con không hợp lệ: {e}")


def ten_thu_muc_khach(ma: str, ten: str) -> str:
    """Tên thư mục khách theo quy ước kho: '1729. Công ty X' — cùng khuôn với
    auto_learn.RE_CLIENT_NUM để bộ quét tách lại được mã."""
    ten = _RE_KY_TU_CAM_THU_MUC.sub(" ", ten or "")
    ten = " ".join(ten.split())
    if not str(ma).isdigit():
        # Mã có chữ ("SUNGROUP", "TEST-1"): khuôn "[MÃ] Tên" — "TEST-1. Tên" thì
        # bộ quét không tách được mã, tệp trong thư mục sẽ không bao giờ học.
        return f"[{ma}] {ten}".strip()[:120].rstrip(" .")
    goc = f"{ma}. {ten}" if ten else str(ma)
    return goc[:120].rstrip(" .")


def ma_so_lon_nhat(ma_csdl, ten_thu_muc) -> int:
    """Mã SỐ lớn nhất trong (mã ở bảng clients) ∪ (mã tách từ tên thư mục
    khách trên đĩa). Mã có chữ ([SUNGROUP]) và mã quá dài bị bỏ qua."""
    lon = 0
    for ma in ma_csdl or ():
        s = str(ma or "").strip()
        if s.isdigit() and len(s) <= SO_CHU_SO_MA_KHACH_TOI_DA:
            lon = max(lon, int(s))
    for ten in ten_thu_muc or ():
        code, _ = auto_learn._client_code_and_name(str(ten))
        if code and code.isdigit() and len(code) <= SO_CHU_SO_MA_KHACH_TOI_DA:
            lon = max(lon, int(code))
    return lon


def suy_trang_thai(trang_thai_hang_doi: str, doc: dict | None) -> str:
    """Trạng thái hiển thị = mốc hàng đợi, ĐƯỢC bản ghi documents ghi đè khi đã
    có: người duyệt tay trên web / bộ quét học trước đều phản ánh đúng."""
    tt = trang_thai_hang_doi or "da_nhan"
    if tt == "da_go":
        return tt
    if doc:
        if not doc.get("active", True):
            return "da_go"
        if doc.get("approved") and doc.get("label_verified"):
            return "da_hoc"
        return "cho_duyet" if tt != "dang_hoc" else tt
    return tt


# ---------------------------------------------------------------------------
# Khoá tích hợp — CSDL
# ---------------------------------------------------------------------------
def _quyen_tu_csdl(v) -> list:
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            v = []
    return list(dict.fromkeys(QUYEN_CU.get(q, q) for q in (v or []) if QUYEN_CU.get(q, q) in QUYEN))


def _iso(t):
    return t.isoformat() if t is not None and hasattr(t, "isoformat") else t


_COT_KHOA = ("id", "ten", "nguon", "key_dau", "quyen", "user_id", "ghi_chu", "created_at",
             "last_used_at", "so_lan_goi", "revoked_at", "email", "full_name", "client_name",
             "so_tai_lieu")


def _dong_khoa(r) -> dict:
    d = dict(zip(_COT_KHOA, r))
    d["quyen"] = _quyen_tu_csdl(d["quyen"])
    for k in ("created_at", "last_used_at", "revoked_at"):
        d[k] = _iso(d[k])
    d["hoat_dong"] = d["revoked_at"] is None
    return d


def tao_khoa(ten: str, nguon: str, quyen, user_id=None, ghi_chu=None, created_by=None) -> dict:
    """Cấp khoá mới. Khoá thật CHỈ có trong kết quả lần này (trường `khoa`)."""
    ten = " ".join((ten or "").split())[:80]
    if not ten:
        raise LoiTichHop("Tên khoá trống — đặt tên để biết cấp cho hệ thống nào")
    nguon = chuan_hoa_nguon(nguon)
    quyen = chuan_hoa_quyen(quyen)
    if "chat" in quyen and not user_id:
        raise LoiTichHop("Quyền hỏi đáp phải gắn một tài khoản KHÁCH đại diện "
                         "(phạm vi dữ liệu của khoá = của khách đó)")
    raw, h, dau = sinh_khoa()
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            if user_id and "chat" not in quyen:
                user_id = None          # tài khoản đại diện chỉ có nghĩa với quyền hỏi đáp
            if user_id:
                cur.execute("SELECT role, active FROM users WHERE id=%s", (user_id,))
                row = cur.fetchone()
                if not row or not row[1]:
                    raise LoiTichHop("Tài khoản đại diện không tồn tại hoặc đã khoá", 404)
                if row[0] not in CLIENT_ROLES:
                    raise LoiTichHop("Tài khoản đại diện phải là tài khoản khách (client_*) — "
                                     "không gắn khoá tích hợp với tài khoản nội bộ")
            cur.execute("""INSERT INTO khoa_tich_hop
                               (ten, nguon, key_hash, key_dau, quyen, user_id, ghi_chu, created_by)
                           VALUES (%s,%s,%s,%s,%s::jsonb,%s,%s,%s) RETURNING id, created_at""",
                        (ten, nguon, h, dau, json.dumps(quyen), user_id,
                         (ghi_chu or "").strip()[:500] or None, created_by))
            kid, tao_luc = cur.fetchone()
        db.audit(conn, created_by, "tich_hop_tao_khoa", "khoa_tich_hop", kid,
                 {"ten": ten, "nguon": nguon, "quyen": quyen, "user_id": user_id})
    return {"id": kid, "ten": ten, "nguon": nguon, "quyen": quyen, "user_id": user_id,
            "key_dau": dau, "khoa": raw, "created_at": _iso(tao_luc),
            "note": "Lưu lại ngay — khoá này không hiển thị lại lần nào nữa."}


def danh_sach_khoa() -> list:
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT k.id, k.ten, k.nguon, k.key_dau, k.quyen, k.user_id, k.ghi_chu,
                                  k.created_at, k.last_used_at, k.so_lan_goi, k.revoked_at,
                                  u.email, u.full_name, c.name,
                                  (SELECT count(*) FROM tich_hop_tai_lieu t
                                    WHERE t.nguon = k.nguon AND t.trang_thai <> 'da_go')
                             FROM khoa_tich_hop k
                             LEFT JOIN users u ON u.id = k.user_id
                             LEFT JOIN clients c ON c.id = u.client_id
                            ORDER BY (k.revoked_at IS NULL) DESC, k.created_at DESC""")
            return [_dong_khoa(r) for r in cur.fetchall()]


def sua_khoa(khoa_id: int, quyen=None, ten: str | None = None, user_id=None,
             doi_user: bool = False, by=None) -> dict:
    """Đổi quyền / tên / tài khoản đại diện của một khoá ĐANG hoạt động mà
    không đổi chuỗi khoá — bên tích hợp không phải cấu hình lại."""
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT ten, quyen, user_id FROM khoa_tich_hop
                            WHERE id=%s AND revoked_at IS NULL""", (khoa_id,))
            row = cur.fetchone()
            if not row:
                raise LoiTichHop("Không thấy khoá hoặc khoá đã thu hồi", 404)
            ten_moi = " ".join((ten or "").split())[:80] or row[0]
            quyen_moi = chuan_hoa_quyen(quyen) if quyen is not None else _quyen_tu_csdl(row[1])
            uid = user_id if doi_user else row[2]
            if "chat" in quyen_moi and not uid:
                raise LoiTichHop("Quyền hỏi đáp phải gắn một tài khoản KHÁCH đại diện")
            if doi_user and uid:
                cur.execute("SELECT role, active FROM users WHERE id=%s", (uid,))
                u = cur.fetchone()
                if not u or not u[1]:
                    raise LoiTichHop("Tài khoản đại diện không tồn tại hoặc đã khoá", 404)
                if u[0] not in CLIENT_ROLES:
                    raise LoiTichHop("Tài khoản đại diện phải là tài khoản khách (client_*)")
            cur.execute("""UPDATE khoa_tich_hop SET ten=%s, quyen=%s::jsonb, user_id=%s
                            WHERE id=%s""", (ten_moi, json.dumps(quyen_moi), uid, khoa_id))
        db.audit(conn, by, "tich_hop_sua_khoa", "khoa_tich_hop", khoa_id,
                 {"ten": ten_moi, "quyen_cu": _quyen_tu_csdl(row[1]), "quyen": quyen_moi,
                  "user_id": uid})
    return {"ok": True, "id": khoa_id, "ten": ten_moi, "quyen": quyen_moi, "user_id": uid}


def thu_hoi_khoa(khoa_id: int, by=None) -> dict:
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""UPDATE khoa_tich_hop SET revoked_at=now(), revoked_by=%s
                            WHERE id=%s AND revoked_at IS NULL RETURNING ten, nguon""",
                        (by, khoa_id))
            row = cur.fetchone()
            if not row:
                raise LoiTichHop("Không thấy khoá hoặc khoá đã thu hồi trước đó", 404)
        db.audit(conn, by, "tich_hop_thu_hoi_khoa", "khoa_tich_hop", khoa_id,
                 {"ten": row[0], "nguon": row[1]})
    return {"ok": True, "id": khoa_id, "ten": row[0]}


def xac_thuc_khoa(raw: str | None) -> dict | None:
    """Khoá còn hiệu lực → {id, ten, nguon, quyen, user_id}; đồng thời ghi mốc
    dùng gần nhất. Không phải khoá hdsi_ hoặc đã thu hồi → None."""
    if not la_khoa_tich_hop(raw):
        return None
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""UPDATE khoa_tich_hop
                              SET last_used_at=now(), so_lan_goi=so_lan_goi+1
                            WHERE key_hash=%s AND revoked_at IS NULL
                        RETURNING id, ten, nguon, quyen, user_id""", (bam_khoa(raw),))
            row = cur.fetchone()
    if not row:
        return None
    return {"id": row[0], "ten": row[1], "nguon": row[2],
            "quyen": _quyen_tu_csdl(row[3]), "user_id": row[4]}


# ---------------------------------------------------------------------------
# Khách hàng
# ---------------------------------------------------------------------------
_KHOA_TAO_KHACH = threading.Lock()


def _ten_thu_muc_khach_tren_dia() -> list:
    out = []
    for goc in kho.thu_muc_goc_khach():
        try:
            out.extend(d.name for d in goc.iterdir() if d.is_dir() and not kho._bo_qua(d))
        except OSError:
            continue
    return out


def thu_muc_khach_tren_dia(ma: str) -> Path | None:
    """Thư mục của khách mã `ma` trong ngăn Hồ sơ khách hàng (tên thư mục nào
    tách ra đúng mã đó), hoặc None."""
    ma = (ma or "").strip().upper()
    for goc in kho.thu_muc_goc_khach():
        try:
            con = sorted(goc.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            continue
        for d in con:
            if not d.is_dir() or kho._bo_qua(d):
                continue
            code, _ = auto_learn._client_code_and_name(d.name)
            if code and code.upper() == ma:
                return d
    return None


def ma_khach_ke_tiep() -> str:
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT code FROM clients WHERE code IS NOT NULL")
            ma_csdl = [r[0] for r in cur.fetchall()]
    return str(ma_so_lon_nhat(ma_csdl, _ten_thu_muc_khach_tren_dia()) + 1)


def thu_muc_khach(ma: str, ten: str | None = None, tao: bool = True) -> Path:
    d = thu_muc_khach_tren_dia(ma)
    if d is not None:
        return d
    if not tao:
        raise LoiTichHop(f"Khách {ma} chưa có thư mục trong kho", 404)
    gocs = kho.thu_muc_goc_khach()
    if not gocs:
        raise LoiTichHop("Kho chưa có ngăn 'Hồ sơ khách hàng' — kiểm tra bản đồ thư mục (drive_map)", 500)
    d = gocs[0] / ten_thu_muc_khach(ma, ten or "")
    d.mkdir(parents=True, exist_ok=True)
    kho.quen_dem()
    return d


def _dong_khach(cur, where: str, params: tuple) -> dict | None:
    cur.execute(f"""SELECT c.id, c.name, c.code, c.ma_ngoai, c.nguon_ngoai, c.department_id,
                           dep.name, c.created_at,
                           (SELECT count(*) FROM documents d
                             WHERE d.client_id=c.id AND coalesce(d.active,true)),
                           (SELECT count(*) FROM documents d
                             WHERE d.client_id=c.id AND coalesce(d.active,true)
                               AND d.approved AND d.label_verified)
                      FROM clients c LEFT JOIN departments dep ON dep.id=c.department_id
                     WHERE {where}""", params)
    r = cur.fetchone()
    if not r:
        return None
    return {"id": r[0], "ten": r[1], "ma": r[2], "ma_ngoai": r[3], "nguon_ngoai": r[4],
            "department_id": r[5], "phong_phu_trach": r[6], "created_at": _iso(r[7]),
            "so_tai_lieu": r[8], "so_tai_lieu_da_hoc": r[9]}


def khach_theo_ma(ma: str, kem_thu_muc: bool = True) -> dict | None:
    ma = chuan_hoa_ma_khach(ma)
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            k = _dong_khach(cur, "upper(c.code)=upper(%s)", (ma,))
    if k and kem_thu_muc:
        d = thu_muc_khach_tren_dia(k["ma"])
        k["thu_muc"] = kho.rel_cua(d) if d else None
    return k


def tim_khach(q: str = "", ma_ngoai: str = "", nguon: str | None = None,
              offset: int = 0, limit: int = 100) -> dict:
    dk, ps = ["c.code IS NOT NULL"], []
    if ma_ngoai:
        dk.append("c.ma_ngoai=%s")
        ps.append(ma_ngoai.strip())
        if nguon:
            dk.append("c.nguon_ngoai=%s")
            ps.append(nguon)
    for tu in (q or "").split()[:6]:
        dk.append("(c.name ILIKE %s OR c.code ILIKE %s)")
        ps += [f"%{tu}%", f"%{tu}%"]
    where = " AND ".join(dk)
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT count(*) FROM clients c WHERE {where}", ps)
            tong = cur.fetchone()[0]
            cur.execute(f"""SELECT c.id, c.name, c.code, c.ma_ngoai, c.nguon_ngoai,
                                   c.department_id,
                                   (SELECT count(*) FROM documents d
                                     WHERE d.client_id=c.id AND coalesce(d.active,true))
                              FROM clients c WHERE {where}
                             ORDER BY (c.code ~ '^[0-9]+$') DESC,
                                      CASE WHEN c.code ~ '^[0-9]+$' THEN c.code::bigint END DESC,
                                      c.name
                             OFFSET %s LIMIT %s""", ps + [max(0, offset), max(1, limit)])
            items = [{"id": r[0], "ten": r[1], "ma": r[2], "ma_ngoai": r[3],
                      "nguon_ngoai": r[4], "department_id": r[5], "so_tai_lieu": r[6]}
                     for r in cur.fetchall()]
    return {"items": items, "tong": tong, "offset": offset, "limit": limit}


def tao_khach(ten: str, ma: str | None = None, ma_ngoai: str | None = None,
              nguon: str | None = None, khoa_id=None) -> dict:
    """Tạo khách (hoặc trả khách đã có nếu trùng mã). Thiếu mã → cấp mã kế tiếp.

    Khoá luồng + thử lại khi đụng mã: hai lời gọi CRM cùng lúc không được nhận
    cùng một mã mới."""
    ten = " ".join((ten or "").split())[:200]
    if not ten:
        raise LoiTichHop("Tên khách trống")
    ma = chuan_hoa_ma_khach(ma) if ma else None
    ma_ngoai = (ma_ngoai or "").strip()[:100] or None
    with _KHOA_TAO_KHACH:
        with db.session(role="internal", admin=True) as conn:
            with conn.cursor() as cur:
                cu = None
                if ma:
                    cu = _dong_khach(cur, "upper(c.code)=upper(%s)", (ma,))
                elif ma_ngoai and nguon:
                    cu = _dong_khach(cur, "c.ma_ngoai=%s AND c.nguon_ngoai=%s", (ma_ngoai, nguon))
                if cu:
                    if ma_ngoai and not cu.get("ma_ngoai"):
                        cur.execute("UPDATE clients SET ma_ngoai=%s, nguon_ngoai=%s WHERE id=%s",
                                    (ma_ngoai, nguon, cu["id"]))
                        cu["ma_ngoai"], cu["nguon_ngoai"] = ma_ngoai, nguon
                    d = thu_muc_khach(cu["ma"], cu["ten"])
                    cu.update({"da_co": True, "thu_muc": kho.rel_cua(d)})
                    return cu
        moi_id = None
        for _ in range(5):
            ma_dung = ma or ma_khach_ke_tiep()
            with db.session(role="internal", admin=True) as conn:
                with conn.cursor() as cur:
                    cur.execute("""INSERT INTO clients (name, code, note, ma_ngoai, nguon_ngoai)
                                   VALUES (%s,%s,%s,%s,%s)
                                   ON CONFLICT (code) DO NOTHING RETURNING id""",
                                (ten, ma_dung, f"Tạo từ hệ thống ngoài ({nguon or 'api'})",
                                 ma_ngoai, nguon))
                    r = cur.fetchone()
                    if r:
                        moi_id = r[0]
                        db.audit(conn, None, "tich_hop_tao_khach", "clients", moi_id,
                                 {"ten": ten, "ma": ma_dung, "ma_ngoai": ma_ngoai,
                                  "nguon": nguon, "khoa_id": khoa_id})
                        break
            if ma:          # mã do CRM đưa mà đụng → khách vừa được tạo bởi lời gọi khác
                return khach_theo_ma(ma) | {"da_co": True}
        if moi_id is None:
            raise LoiTichHop("Không cấp được mã khách mới — thử lại", 500)
        d = thu_muc_khach(ma_dung, ten)
    k = khach_theo_ma(ma_dung, kem_thu_muc=False) or {}
    k.update({"da_co": False, "thu_muc": kho.rel_cua(d)})
    return k


# ---------------------------------------------------------------------------
# Nhân viên — ngăn "8. HỒ SƠ NHÂN SỰ/<thư mục người>" + bảng employees
# ---------------------------------------------------------------------------
# Kho đang có thư mục theo TÊN người ("Mai", "Ngân", "Nhi"), chưa có mã nhân
# viên; bảng employees thì trống. Gắn hai bên bằng cột employees.thu_muc. Trợ
# lý đếm quân số theo bảng employees khi bảng có dữ liệu (company_context) —
# nên CRM phải đăng ký ĐỦ mọi nhân viên, kể cả người đã có thư mục sẵn.
_KHOA_TAO_NV = threading.Lock()
RE_MA_NV_TU_CAP = re.compile(r"^NV(\d{1,6})$")


def goc_nhan_su(root: Path | None = None) -> Path | None:
    """Thư mục ngăn hồ sơ nhân sự ở tầng gốc kho (ngăn mà bản đồ nhãn gán
    doc_type 'ho_so_ns'), hoặc None."""
    root = root or kho.library_root()
    cats = kho._ban_do_nhan()[0]
    try:
        con = sorted(root.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return None
    for p in con:
        if p.is_dir() and not kho._bo_qua(p):
            if (cats.get(auto_learn._norm(p.name)) or {}).get("doc_type") == "ho_so_ns":
                return p
    return None


def ten_thu_muc_nhan_vien(ho_ten: str) -> str:
    """Tên thư mục người theo quy ước kho (chính họ tên, bỏ ký tự cấm)."""
    ten = " ".join(_RE_KY_TU_CAM_THU_MUC.sub(" ", ho_ten or "").split())[:120].rstrip(" .")
    try:
        return kho.ten_thu_muc_hop_le(ten)
    except kho.LoiKho as e:
        raise LoiTichHop(f"Họ tên không dùng làm tên thư mục được: {e}")


def ma_nv_ke_tiep_tu(ma_da_co) -> str:
    """'NV0001', 'NV0002'… — số lớn nhất trong các mã dạng NVxxxx + 1."""
    lon = 0
    for ma in ma_da_co or ():
        m = RE_MA_NV_TU_CAP.match(str(ma or "").strip().upper())
        if m:
            lon = max(lon, int(m.group(1)))
    return f"NV{lon + 1:04d}"


def chuan_hoa_ma_nv(ma: str) -> str:
    from app.hr_api import _employee_code
    try:
        return _employee_code(ma)
    except ValueError as e:
        raise LoiTichHop(str(e))


def chuan_hoa_trang_thai_nv(tt) -> str:
    from app.hr_api import _employee_status
    try:
        return _employee_status(tt)
    except ValueError as e:
        raise LoiTichHop(str(e))


_COT_NV = ("id", "ma", "ho_ten", "chuc_danh", "trang_thai", "active", "thu_muc_ten",
           "ma_ngoai", "nguon_ngoai", "created_at")


def _dong_nv(r) -> dict:
    d = dict(zip(_COT_NV, r))
    d["created_at"] = _iso(d["created_at"])
    return d


def _so_tai_lieu_nv(ten_thu_muc: list) -> dict:
    """{tên thư mục người: (số tài liệu, số đã học)} — một truy vấn."""
    if not ten_thu_muc:
        return {}
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT person_folder, count(*),
                                  count(*) FILTER (WHERE approved AND label_verified)
                             FROM documents
                            WHERE doc_type='ho_so_ns' AND coalesce(active,true)
                              AND person_folder = ANY(%s)
                            GROUP BY person_folder""", (list(ten_thu_muc),))
            return {r[0]: (r[1], r[2]) for r in cur.fetchall()}


def _hoan_thien_nv(d: dict, dem: dict | None = None) -> dict:
    goc = goc_nhan_su()
    ten = d.pop("thu_muc_ten", None)
    d["thu_muc"] = kho.rel_cua(goc / ten) if (goc and ten and (goc / ten).is_dir()) else None
    so, da_hoc = (dem or {}).get(ten, (0, 0))
    d["so_tai_lieu"], d["so_tai_lieu_da_hoc"] = so, da_hoc
    return d


def nhan_vien_theo_ma(ma_nv: str) -> dict | None:
    ma_nv = chuan_hoa_ma_nv(ma_nv)
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"""SELECT id, employee_code, full_name, title, employment_status, active,
                                   thu_muc, ma_ngoai, nguon_ngoai, created_at
                              FROM employees WHERE upper(employee_code)=upper(%s)""", (ma_nv,))
            r = cur.fetchone()
    if not r:
        return None
    d = _dong_nv(r)
    return _hoan_thien_nv(d, _so_tai_lieu_nv([d["thu_muc_ten"]] if d["thu_muc_ten"] else []))


def thu_muc_nhan_su_chua_gan(bound: set | None = None) -> list:
    """Thư mục người trên đĩa CHƯA gắn với nhân viên nào — để CRM nhận về."""
    goc = goc_nhan_su()
    if goc is None:
        return []
    if bound is None:
        with db.session(role="internal", admin=True) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT thu_muc FROM employees WHERE thu_muc IS NOT NULL")
                bound = {r[0] for r in cur.fetchall()}
    out = []
    for p in sorted(goc.iterdir(), key=lambda x: x.name.lower()):
        if p.is_dir() and not kho._bo_qua(p) and p.name not in bound:
            out.append({"ten": p.name, "thu_muc": kho.rel_cua(p),
                        "so_tep": len(kho._tep_trong(p))})
    return out


def tim_nhan_vien(q: str = "", ma_ngoai: str = "", nguon: str | None = None,
                  offset: int = 0, limit: int = 100) -> dict:
    dk, ps = ["TRUE"], []
    if ma_ngoai:
        dk.append("ma_ngoai=%s")
        ps.append(ma_ngoai.strip())
        if nguon:
            dk.append("nguon_ngoai=%s")
            ps.append(nguon)
    for tu in (q or "").split()[:6]:
        dk.append("(full_name ILIKE %s OR employee_code ILIKE %s)")
        ps += [f"%{tu}%", f"%{tu}%"]
    where = " AND ".join(dk)
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT count(*) FROM employees WHERE {where}", ps)
            tong = cur.fetchone()[0]
            cur.execute(f"""SELECT id, employee_code, full_name, title, employment_status, active,
                                   thu_muc, ma_ngoai, nguon_ngoai, created_at
                              FROM employees WHERE {where}
                             ORDER BY employee_code OFFSET %s LIMIT %s""",
                        ps + [max(0, offset), max(1, limit)])
            rows = [_dong_nv(r) for r in cur.fetchall()]
    dem = _so_tai_lieu_nv([r["thu_muc_ten"] for r in rows if r["thu_muc_ten"]])
    items = [_hoan_thien_nv(r, dem) for r in rows]
    return {"items": items, "tong": tong, "offset": offset, "limit": limit,
            "thu_muc_chua_gan": thu_muc_nhan_su_chua_gan() if offset == 0 else []}


def _chon_thu_muc_nv(cur, goc: Path, ho_ten: str, ma_nv: str, thu_muc: str | None,
                     employee_id: int | None) -> str:
    """Tên thư mục người cho nhân viên: CRM chỉ định (nhận thư mục sẵn có) hoặc
    theo họ tên; trùng với thư mục đã gắn người khác thì thêm '(mã NV)'."""
    cur.execute("SELECT thu_muc, id FROM employees WHERE thu_muc IS NOT NULL")
    da_gan = {r[0]: r[1] for r in cur.fetchall()}
    if thu_muc:
        ten = kho.ten_thu_muc_hop_le(Path(str(thu_muc).replace("\\", "/")).name)
        chu = da_gan.get(ten)
        if chu is not None and chu != employee_id:
            raise LoiTichHop(f"Thư mục '{ten}' đã gắn với nhân viên khác", 409)
        return ten
    ten = ten_thu_muc_nhan_vien(ho_ten)
    chu = da_gan.get(ten)
    if chu is None or chu == employee_id:
        return ten
    return ten_thu_muc_nhan_vien(f"{ho_ten} ({ma_nv})")


def tao_nhan_vien(ho_ten: str, ma_nv: str | None = None, chuc_danh: str | None = None,
                  trang_thai_nv: str | None = None, ma_ngoai: str | None = None,
                  thu_muc: str | None = None, nguon: str | None = None, khoa_id=None) -> dict:
    """Tạo hoặc cập nhật nhân viên (theo mã NV). Thiếu mã → cấp 'NVxxxx'.
    Luôn bảo đảm có thư mục hồ sơ trong ngăn nhân sự."""
    ho_ten = " ".join((ho_ten or "").split())[:200]
    if not ho_ten:
        raise LoiTichHop("Họ tên trống")
    ma_nv = chuan_hoa_ma_nv(ma_nv) if ma_nv else None
    tt = chuan_hoa_trang_thai_nv(trang_thai_nv) if trang_thai_nv else None
    chuc_danh = (chuc_danh or "").strip()[:200] or None
    ma_ngoai = (ma_ngoai or "").strip()[:100] or None
    goc = goc_nhan_su()
    if goc is None:
        raise LoiTichHop("Kho chưa có ngăn 'Hồ sơ nhân sự' — kiểm tra bản đồ thư mục", 500)
    with _KHOA_TAO_NV:
        with db.session(role="internal", admin=True) as conn:
            with conn.cursor() as cur:
                cu = None
                if ma_nv:
                    cur.execute("SELECT id, thu_muc FROM employees WHERE upper(employee_code)=upper(%s)",
                                (ma_nv,))
                    cu = cur.fetchone()
                elif ma_ngoai and nguon:
                    cur.execute("""SELECT id, thu_muc, employee_code FROM employees
                                    WHERE ma_ngoai=%s AND nguon_ngoai=%s""", (ma_ngoai, nguon))
                    r = cur.fetchone()
                    if r:
                        cu, ma_nv = (r[0], r[1]), r[2]
                if cu:
                    emp_id, thu_muc_cu = cu
                    ten_tm = thu_muc_cu if (thu_muc_cu and not thu_muc) else \
                        _chon_thu_muc_nv(cur, goc, ho_ten, ma_nv, thu_muc, emp_id)
                    cur.execute("""UPDATE employees
                                      SET full_name=%s, title=coalesce(%s,title),
                                          employment_status=coalesce(%s,employment_status),
                                          active = CASE WHEN %s IS NULL THEN active
                                                        ELSE %s NOT IN ('terminated','inactive') END,
                                          thu_muc=%s,
                                          ma_ngoai=coalesce(%s,ma_ngoai),
                                          nguon_ngoai=CASE WHEN %s IS NULL THEN nguon_ngoai ELSE %s END,
                                          updated_at=now()
                                    WHERE id=%s""",
                                (ho_ten, chuc_danh, tt, tt, tt, ten_tm, ma_ngoai, ma_ngoai, nguon,
                                 emp_id))
                    da_co = True
                else:
                    da_co = False
                    emp_id = ten_tm = None
        if not da_co:
            for _ in range(5):
                if not ma_nv:
                    with db.session(role="internal", admin=True) as conn:
                        with conn.cursor() as cur:
                            cur.execute("SELECT employee_code FROM employees")
                            ma_dung = ma_nv_ke_tiep_tu([r[0] for r in cur.fetchall()])
                else:
                    ma_dung = ma_nv
                with db.session(role="internal", admin=True) as conn:
                    with conn.cursor() as cur:
                        ten_tm = _chon_thu_muc_nv(cur, goc, ho_ten, ma_dung, thu_muc, None)
                        cur.execute("""INSERT INTO employees
                                           (employee_code, full_name, title, employment_status,
                                            active, thu_muc, ma_ngoai, nguon_ngoai)
                                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                                       ON CONFLICT (employee_code) DO NOTHING RETURNING id""",
                                    (ma_dung, ho_ten, chuc_danh, tt or "active",
                                     (tt or "active") not in ("terminated", "inactive"),
                                     ten_tm, ma_ngoai, nguon))
                        r = cur.fetchone()
                        if r:
                            emp_id = r[0]
                            db.audit(conn, None, "tich_hop_tao_nhan_vien", "employees", emp_id,
                                     {"ma_nv": ma_dung, "ho_ten": ho_ten, "thu_muc": ten_tm,
                                      "nguon": nguon, "khoa_id": khoa_id})
                            ma_nv = ma_dung
                            break
                if ma_nv:        # mã CRM đưa mà đụng → lời gọi khác vừa tạo
                    return (nhan_vien_theo_ma(ma_nv) or {}) | {"da_co": True}
            if emp_id is None:
                raise LoiTichHop("Không cấp được mã nhân viên mới — thử lại", 500)
        (goc / ten_tm).mkdir(parents=True, exist_ok=True)
        kho.quen_dem()
    nv = nhan_vien_theo_ma(ma_nv) or {}
    nv["da_co"] = da_co
    return nv


# ---------------------------------------------------------------------------
# Chủ hồ sơ: một khách HOẶC một nhân viên — mọi thao tác tài liệu đi qua đây
# ---------------------------------------------------------------------------
LOAI_CHU = {
    "khach": {"quyen": "clients:read", "ten": "khách hàng"},
    "nhan_vien": {"quyen": "employees:read", "ten": "nhân viên"},
}


def kiem_quyen_loai(khoa: dict | None, loai: str):
    """Tài liệu của khách cần thêm quyền clients:read; của nhân viên cần
    employees:read — documents:* một mình không mở được hồ sơ nhân sự."""
    if khoa is None:
        return
    can = LOAI_CHU.get(loai or "khach", LOAI_CHU["khach"])["quyen"]
    if not co_quyen(khoa, can):
        raise LoiTichHop(f"Khoá này không có quyền '{can}' ({QUYEN[can]['ten']}) "
                         f"nên không thao tác được tài liệu của {LOAI_CHU[loai]['ten']}", 403)


def chu_khach(ma: str, tao_thu_muc: bool = True) -> dict:
    k = khach_theo_ma(ma, kem_thu_muc=False)
    if not k:
        raise LoiTichHop(f"Chưa có khách mã '{ma}' — tạo khách trước (POST /integration/v1/clients)", 404)
    if tao_thu_muc:
        d = thu_muc_khach(k["ma"], k["ten"])
    else:
        d = thu_muc_khach_tren_dia(k["ma"])
    return {"loai": "khach", "ma": k["ma"], "ten": k["ten"], "client_id": k["id"],
            "employee_id": None, "thu_muc": d}


def chu_nhan_vien(ma_nv: str, tao_thu_muc: bool = True) -> dict:
    nv = nhan_vien_theo_ma(ma_nv)
    if not nv:
        raise LoiTichHop(f"Chưa có nhân viên mã '{ma_nv}' — tạo trước (POST /integration/v1/employees)", 404)
    goc = goc_nhan_su()
    d = None
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT thu_muc FROM employees WHERE id=%s", (nv["id"],))
            ten = (cur.fetchone() or [None])[0]
    if goc is not None and ten:
        d = goc / ten
        if tao_thu_muc:
            d.mkdir(parents=True, exist_ok=True)
        elif not d.is_dir():
            d = None
    elif tao_thu_muc:
        raise LoiTichHop("Nhân viên chưa gắn thư mục hồ sơ — gọi lại POST /integration/v1/employees", 409)
    return {"loai": "nhan_vien", "ma": nv["ma"], "ten": nv["ho_ten"], "client_id": None,
            "employee_id": nv["id"], "thu_muc": d}


def duong_dan_trong(thu_muc: Path, rel: str) -> Path:
    """Đường dẫn tương đối CRM gửi → tệp NẰM TRONG thư mục chủ hồ sơ.
    Chặn '..', đường dẫn tuyệt đối, ổ đĩa, đoạn ẩn/'~$', thư mục bộ quét bỏ qua."""
    s = (rel or "").replace("\\", "/").strip().strip("/")
    if not s or re.match(r"^[A-Za-z]:", s):
        raise LoiTichHop("Đường dẫn tệp trống hoặc không hợp lệ")
    parts = [p for p in s.split("/") if p not in ("", ".")]
    for p in parts:
        if p == ".." or p.startswith(("~$", ".")) or p in kho.SKIP_DIRS:
            raise LoiTichHop("Đường dẫn tệp không hợp lệ")
    goc = thu_muc.resolve()
    path = goc.joinpath(*parts)
    try:
        path.resolve().relative_to(goc)
    except ValueError:
        raise LoiTichHop("Đường dẫn nằm ngoài hồ sơ")
    if not path.is_file():
        raise LoiTichHop("Không thấy tệp này trong hồ sơ", 404)
    return path


def _dong_tep(p: Path, folder: Path, key: str, row: dict | None, loi: dict | None,
              ma_ngoai: str | None) -> dict:
    st = p.stat()
    tt = kho.trang_thai_file(row, p.suffix, loi)
    return {
        "duong_dan": p.relative_to(folder).as_posix(),
        "ten_file": p.name,
        "thu_muc_con": "" if p.parent == folder else p.parent.relative_to(folder).as_posix(),
        "kich_thuoc": st.st_size,
        "sua_luc": _iso(__import__("datetime").datetime.fromtimestamp(st.st_mtime).astimezone()),
        "trang_thai": tt,
        "document_id": row["id"] if row else None,
        "tieu_de": row["title"] if row else None,
        "checksum": row.get("checksum") if row else None,
        "ma_ngoai": ma_ngoai,
        "loi": (loi or {}).get("message") if tt == "loi" else None,
    }


def _ma_ngoai_theo_khoa(nguon: str, keys: list) -> dict:
    if not keys:
        return {}
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT khoa_kho, ma_ngoai FROM tich_hop_tai_lieu
                            WHERE nguon=%s AND trang_thai <> 'da_go' AND khoa_kho = ANY(%s)
                            ORDER BY created_at""", (nguon, list(keys)))
            out = {}
            for k, m in cur.fetchall():
                out.setdefault(k, m)
            return out


def liet_ke_tep(chu: dict, nguon: str, gioi_han: int = 5000) -> dict:
    """MỌI tệp trong hồ sơ trên đĩa (kể cả tệp cũ không do CRM gửi), kèm
    trạng thái học và mã ngoài nếu đã gắn."""
    folder = chu.get("thu_muc")
    base = {"loai": chu["loai"], "ma": chu["ma"], "ten": chu["ten"],
            "thu_muc": kho.rel_cua(folder) if folder else None}
    if folder is None or not folder.is_dir():
        return base | {"items": [], "tong": 0}
    root = kho.library_root()
    tep = kho._tep_trong(folder)
    tong = len(tep)
    tep = tep[:gioi_han]
    ks = [local_key(root, p) for p in tep]
    rows = kho._theo_lo(ks, kho._tai_lieu_theo_khoa)
    loi = kho._theo_lo(ks, kho._loi_theo_khoa)
    ma = _ma_ngoai_theo_khoa(nguon, ks)
    items = [_dong_tep(p, folder, k, rows.get(k), loi.get(k), ma.get(k)) for p, k in zip(tep, ks)]
    return base | {"items": items, "tong": tong}


# ---------------------------------------------------------------------------
# Tài liệu — ánh xạ mã ngoài ↔ tệp trong kho
# ---------------------------------------------------------------------------
_COT_AX = ("nguon", "ma_ngoai", "khoa_kho", "checksum", "client_id", "ten_file",
           "trang_thai", "loi", "meta", "khoa_id", "created_at", "updated_at",
           "loai", "employee_id")


def _anh_xa(nguon: str, ma_ngoai: str) -> dict | None:
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT {', '.join(_COT_AX)} FROM tich_hop_tai_lieu "
                        "WHERE nguon=%s AND ma_ngoai=%s", (nguon, ma_ngoai))
            r = cur.fetchone()
    return dict(zip(_COT_AX, r)) if r else None


def _luu_anh_xa(nguon, ma_ngoai, khoa_kho, checksum, chu, ten_file, trang_thai,
                khoa_id=None, meta=None, loi=None):
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO tich_hop_tai_lieu
                               (nguon, ma_ngoai, khoa_kho, checksum, client_id, employee_id, loai,
                                ten_file, trang_thai, loi, meta, khoa_id)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)
                           ON CONFLICT (nguon, ma_ngoai) DO UPDATE
                             SET khoa_kho=EXCLUDED.khoa_kho, checksum=EXCLUDED.checksum,
                                 client_id=EXCLUDED.client_id, employee_id=EXCLUDED.employee_id,
                                 loai=EXCLUDED.loai, ten_file=EXCLUDED.ten_file,
                                 trang_thai=EXCLUDED.trang_thai, loi=EXCLUDED.loi,
                                 meta=coalesce(EXCLUDED.meta, tich_hop_tai_lieu.meta),
                                 khoa_id=EXCLUDED.khoa_id, updated_at=now()""",
                        (nguon, ma_ngoai, khoa_kho, checksum, chu.get("client_id"),
                         chu.get("employee_id"), chu["loai"], ten_file, trang_thai,
                         loi, json.dumps(meta, ensure_ascii=False) if meta else None, khoa_id))


def _cap_nhat_trang_thai(nguon, ma_ngoai, trang_thai, loi=None):
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""UPDATE tich_hop_tai_lieu SET trang_thai=%s, loi=%s, updated_at=now()
                            WHERE nguon=%s AND ma_ngoai=%s""", (trang_thai, loi, nguon, ma_ngoai))


def _con_anh_xa_khac(nguon: str, ma_ngoai: str, khoa_kho: str) -> bool:
    """Còn mã ngoài KHÁC (còn hiệu lực) trỏ cùng tệp? Khi đó không được rút,
    ghi đè hay đổi tệp đó — nó cũng là tài liệu của mã kia."""
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT count(*) FROM tich_hop_tai_lieu
                            WHERE khoa_kho=%s AND trang_thai <> 'da_go'
                              AND NOT (nguon=%s AND ma_ngoai=%s)""",
                        (khoa_kho, nguon, ma_ngoai))
            return cur.fetchone()[0] > 0


_COT_DOC = ("id", "title", "approved", "label_verified", "extraction_status", "ty_le_rac",
            "active", "created_at", "drive_file_id")


def _tai_lieu_theo_khoa_kho(khoa_kho: str) -> dict | None:
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT id, title, approved, label_verified, extraction_status,
                                  ty_le_rac, coalesce(active,true), created_at, drive_file_id
                             FROM documents WHERE drive_file_id=%s""", (khoa_kho,))
            r = cur.fetchone()
    return dict(zip(_COT_DOC, r)) if r else None


def _tai_lieu_cung_md5(md5: str, chu: dict) -> dict | None:
    """Tệp y hệt (md5) đã nằm trong CHÍNH hồ sơ này, còn tệp trên đĩa."""
    folder = chu.get("thu_muc")
    if folder is None:
        return None
    tien_to = LOCAL_PREFIX + kho.rel_cua(folder) + "/"
    tien_to = tien_to.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT id, title, approved, label_verified, extraction_status,
                                  ty_le_rac, coalesce(active,true), created_at, drive_file_id
                             FROM documents
                            WHERE checksum=%s AND coalesce(active,true)
                              AND drive_file_id LIKE %s
                            ORDER BY (approved AND label_verified) DESC, id LIMIT 1""",
                        (md5, tien_to + "%"))
            r = cur.fetchone()
    if not r:
        return None
    doc = dict(zip(_COT_DOC, r))
    rel = kho.rel_tu_khoa(doc["drive_file_id"])
    try:
        if rel and kho.duong_dan_kho(rel).is_file():
            return doc
    except kho.LoiKho:
        pass
    return None


def _ma_chu_cua(ax: dict) -> tuple:
    """(ma_khach, ma_nhan_vien) của một ánh xạ."""
    ma_khach = ma_nv = None
    if ax.get("client_id") or ax.get("employee_id"):
        with db.session(role="internal", admin=True) as conn:
            with conn.cursor() as cur:
                if ax.get("client_id"):
                    cur.execute("SELECT code FROM clients WHERE id=%s", (ax["client_id"],))
                    ma_khach = (cur.fetchone() or [None])[0]
                if ax.get("employee_id"):
                    cur.execute("SELECT employee_code FROM employees WHERE id=%s", (ax["employee_id"],))
                    ma_nv = (cur.fetchone() or [None])[0]
    return ma_khach, ma_nv


def _dong_trang_thai(ax: dict, doc: dict | None, ma_khach: str | None = None,
                     ma_nv: str | None = None) -> dict:
    tt = suy_trang_thai(ax.get("trang_thai"), doc)
    return {
        "ma_ngoai": ax["ma_ngoai"], "loai": ax.get("loai") or "khach",
        "ma_khach": ma_khach, "ma_nhan_vien": ma_nv,
        "trang_thai": tt, "mo_ta": MO_TA_TRANG_THAI.get(tt, tt),
        "ten_file": ax.get("ten_file"),
        "duong_dan": kho.rel_tu_khoa(ax.get("khoa_kho")),
        "checksum": ax.get("checksum"),
        "document_id": doc["id"] if doc and doc.get("active", True) else None,
        "tieu_de": doc["title"] if doc else None,
        "ty_le_rac": (round(float(doc["ty_le_rac"]), 4)
                      if doc and doc.get("ty_le_rac") is not None else None),
        "chat_luong_doc": doc.get("extraction_status") if doc else None,
        "loi": ax.get("loi") if tt == "loi" else None,
        "nhan_luc": _iso(ax.get("created_at")), "cap_nhat_luc": _iso(ax.get("updated_at")),
    }


def _anh_xa_hoac_404(nguon: str, ma_ngoai: str, khoa: dict | None = None) -> dict:
    ma_ngoai = chuan_hoa_ma_ngoai(ma_ngoai)
    ax = _anh_xa(nguon, ma_ngoai)
    if not ax:
        raise LoiTichHop(f"Không có tài liệu external_id '{ma_ngoai}' của nguồn '{nguon}'", 404)
    kiem_quyen_loai(khoa, ax.get("loai") or "khach")
    return ax


def trang_thai(nguon: str, ma_ngoai: str, khoa: dict | None = None) -> dict:
    ax = _anh_xa_hoac_404(nguon, ma_ngoai, khoa)
    doc = _tai_lieu_theo_khoa_kho(ax["khoa_kho"])
    return _dong_trang_thai(ax, doc, *_ma_chu_cua(ax))


def danh_sach_tai_lieu(nguon: str, ma_khach: str | None = None, tu_luc: str | None = None,
                       offset: int = 0, limit: int = 200, ma_nv: str | None = None,
                       loai_duoc_xem=("khach", "nhan_vien")) -> dict:
    """Đối soát: mọi tài liệu nguồn này đã gửi / đã gắn mã (một truy vấn, phân
    trang). `tu_luc` (ISO) chỉ lấy dòng đổi từ mốc đó — kể cả đổi do người
    duyệt. `loai_duoc_xem` lọc theo quyền của khoá."""
    loai_duoc_xem = [x for x in loai_duoc_xem if x in LOAI_CHU]
    if not loai_duoc_xem:
        return {"items": [], "tong": 0, "offset": offset, "limit": limit}
    dk, ps = ["t.nguon=%s", "coalesce(t.loai,'khach') = ANY(%s)"], [nguon, list(loai_duoc_xem)]
    if ma_khach:
        dk.append("upper(c.code)=upper(%s)")
        ps.append(chuan_hoa_ma_khach(ma_khach))
    if ma_nv:
        dk.append("upper(e.employee_code)=upper(%s)")
        ps.append(chuan_hoa_ma_nv(ma_nv))
    if tu_luc:
        dk.append("(t.updated_at >= %s::timestamptz OR d.updated_at >= %s::timestamptz)")
        ps += [tu_luc, tu_luc]
    where = " AND ".join(dk)
    tu = """FROM tich_hop_tai_lieu t
            LEFT JOIN clients c ON c.id=t.client_id
            LEFT JOIN employees e ON e.id=t.employee_id
            LEFT JOIN documents d ON d.drive_file_id=t.khoa_kho"""
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT count(*) {tu} WHERE {where}", ps)
            tong = cur.fetchone()[0]
            cur.execute(f"""SELECT t.nguon, t.ma_ngoai, t.khoa_kho, t.checksum, t.client_id,
                                   t.ten_file, t.trang_thai, t.loi, t.meta, t.khoa_id,
                                   t.created_at, t.updated_at, t.loai, t.employee_id,
                                   c.code, e.employee_code,
                                   d.id, d.title, d.approved, d.label_verified,
                                   d.extraction_status, d.ty_le_rac, coalesce(d.active,true),
                                   d.created_at, d.drive_file_id
                              {tu} WHERE {where}
                             ORDER BY t.updated_at DESC, t.ma_ngoai
                             OFFSET %s LIMIT %s""", ps + [max(0, offset), max(1, limit)])
            items = []
            for r in cur.fetchall():
                ax = dict(zip(_COT_AX, r[:14]))
                doc = dict(zip(_COT_DOC, r[16:25])) if r[16] is not None else None
                items.append(_dong_trang_thai(ax, doc, r[14], r[15]))
    return {"items": items, "tong": tong, "offset": offset, "limit": limit}


# ---------------------------------------------------------------------------
# Phiên bản — bản cũ không bao giờ mất (máy chủ là nơi giữ bản gốc duy nhất)
# ---------------------------------------------------------------------------
def thu_muc_phien_ban() -> Path:
    """data/_phien_ban cạnh kho (ngoài kho để bộ quét không học lại bản cũ).
    Đặt DATA_PHIEN_BAN trong .env nếu muốn khác."""
    raw = os.getenv("DATA_PHIEN_BAN")
    if raw:
        p = Path(raw)
        return (p if p.is_absolute() else Path.cwd() / p).resolve()
    return kho.library_root().parent / "_phien_ban"


def _so_phien_ban_ke_tiep(nguon: str, ma_ngoai: str) -> int:
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT coalesce(max(so),0)+1 FROM tich_hop_phien_ban
                            WHERE nguon=%s AND ma_ngoai=%s""", (nguon, ma_ngoai))
            return cur.fetchone()[0]


def _ghi_phien_ban(nguon, ma_ngoai, so, ten_file, checksum, kich_thuoc, duong_dan_luu, ly_do):
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO tich_hop_phien_ban
                               (nguon, ma_ngoai, so, ten_file, checksum, kich_thuoc,
                                duong_dan_luu, ly_do)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (nguon, ma_ngoai, so, ten_file, checksum, kich_thuoc,
                         duong_dan_luu, ly_do))


def _tep_hien_tai(ax: dict) -> Path | None:
    rel = kho.rel_tu_khoa(ax.get("khoa_kho"))
    if not rel:
        return None
    try:
        p = kho.duong_dan_kho(rel)
    except kho.LoiKho:
        return None
    return p if p.is_file() else None


def luu_phien_ban(ax: dict, ly_do: str) -> dict | None:
    """CHÉP bản hiện tại của một mã ngoài sang thư mục phiên bản trước khi nó
    bị ghi đè / đổi tên / gỡ. Không có tệp thì thôi (không có gì để mất)."""
    p = _tep_hien_tai(ax)
    if p is None:
        return None
    nguon, ma_ngoai = ax["nguon"], ax["ma_ngoai"]
    so = _so_phien_ban_ke_tiep(nguon, ma_ngoai)
    dest = thu_muc_phien_ban() / nguon / ma_ngoai / f"{so:03d}__{p.name}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(p, dest)
    md5 = ax.get("checksum") or file_md5(p)
    _ghi_phien_ban(nguon, ma_ngoai, so, p.name, md5, dest.stat().st_size, str(dest), ly_do)
    return {"so": so, "duong_dan_luu": str(dest)}


def danh_sach_phien_ban(nguon: str, ma_ngoai: str, khoa: dict | None = None) -> dict:
    ax = _anh_xa_hoac_404(nguon, ma_ngoai, khoa)
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT so, ten_file, checksum, kich_thuoc, ly_do, created_at
                             FROM tich_hop_phien_ban
                            WHERE nguon=%s AND ma_ngoai=%s ORDER BY so""", (nguon, ax["ma_ngoai"]))
            cu = [{"so": r[0], "ten_file": r[1], "checksum": r[2], "kich_thuoc": r[3],
                   "ly_do": r[4], "luu_luc": _iso(r[5]), "hien_tai": False}
                  for r in cur.fetchall()]
    items = list(cu)
    p = _tep_hien_tai(ax)
    if p is not None and ax.get("trang_thai") != "da_go":
        items.append({"so": (cu[-1]["so"] + 1) if cu else 1, "ten_file": p.name,
                      "checksum": ax.get("checksum"), "kich_thuoc": p.stat().st_size,
                      "ly_do": None, "luu_luc": _iso(ax.get("updated_at")), "hien_tai": True})
    return {"ma_ngoai": ax["ma_ngoai"], "items": items}


def tep_phien_ban(nguon: str, ma_ngoai: str, so: int, khoa: dict | None = None) -> tuple:
    """(Path, tên tệp, md5) của một phiên bản — số hiện tại trả tệp đang dùng."""
    ax = _anh_xa_hoac_404(nguon, ma_ngoai, khoa)
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT duong_dan_luu, ten_file, checksum FROM tich_hop_phien_ban
                            WHERE nguon=%s AND ma_ngoai=%s AND so=%s""", (nguon, ax["ma_ngoai"], so))
            r = cur.fetchone()
    if r:
        p = Path(r[0])
        goc = thu_muc_phien_ban().resolve()
        try:
            p.resolve().relative_to(goc)
        except ValueError:
            raise LoiTichHop("Bản lưu nằm ngoài thư mục phiên bản", 500)
        if not p.is_file():
            raise LoiTichHop("Tệp của phiên bản này không còn trên máy chủ", 410)
        return p, r[1], r[2]
    ds = danh_sach_phien_ban(nguon, ax["ma_ngoai"])["items"]
    ht = [x for x in ds if x["hien_tai"] and x["so"] == so]
    if ht:
        p = _tep_hien_tai(ax)
        return p, p.name, ax.get("checksum")
    raise LoiTichHop(f"Không có phiên bản số {so}", 404)


def tep_hien_tai(nguon: str, ma_ngoai: str, khoa: dict | None = None) -> tuple:
    """(Path, tên tệp, md5) của bản đang dùng; đã gỡ → 410 kèm gợi ý."""
    ax = _anh_xa_hoac_404(nguon, ma_ngoai, khoa)
    if ax.get("trang_thai") == "da_go":
        raise LoiTichHop("Tài liệu đã gỡ — tải bản lưu qua /versions", 410)
    p = _tep_hien_tai(ax)
    if p is None:
        raise LoiTichHop("Tệp gốc không còn trên máy chủ", 410)
    return p, p.name, ax.get("checksum")


# ---------------------------------------------------------------------------
# Nhận / gắn mã / gỡ
# ---------------------------------------------------------------------------
def _don_ban_cu(ax: dict) -> str | None:
    """Bản cũ của cùng mã ngoài nằm ở đường dẫn khác → gỡ như nút Gỡ trên web
    (active=false + chuyển tệp sang thùng đã gỡ). Tệp còn mã ngoài khác dùng
    chung thì KHÔNG đụng tới."""
    khoa_cu = ax.get("khoa_kho")
    if not khoa_cu or _con_anh_xa_khac(ax["nguon"], ax["ma_ngoai"], khoa_cu):
        return None
    doc = _tai_lieu_theo_khoa_kho(khoa_cu)
    if doc and doc.get("active", True):
        try:
            return (kho.go_tai_lieu(doc["id"], None) or {}).get("da_chuyen_toi")
        except kho.LoiKho:
            return None
    rel = kho.rel_tu_khoa(khoa_cu)
    try:
        p = kho.duong_dan_kho(rel) if rel else None
    except kho.LoiKho:
        return None
    if p and p.is_file():
        dest = kho.dich_da_go(kho.thung_da_go(), rel)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(p), str(dest))
        return str(dest)
    return None


def _kiem_tep(ten_file: str, noi_dung: bytes, meta, gioi_han_mb: int) -> tuple:
    ten = ten_tep_an_toan(ten_file)
    duoi = Path(ten).suffix.lower()
    if duoi not in ALLOWED:
        raise LoiTichHop(f"Định dạng {duoi or '(không có đuôi)'} chưa hỗ trợ; nhận: "
                         + ", ".join(sorted(e.lstrip('.').upper() for e in ALLOWED)), 415)
    if not noi_dung:
        raise LoiTichHop("Tệp rỗng")
    if len(noi_dung) > gioi_han_mb * 1024 * 1024:
        raise LoiTichHop(f"Tệp vượt quá {gioi_han_mb} MB", 413)
    if meta is not None and not isinstance(meta, dict):
        raise LoiTichHop("metadata phải là một đối tượng JSON")
    return ten, duoi


def nhan_tai_lieu(khoa: dict, ma_khach: str, ma_ngoai: str, ten_file: str, noi_dung: bytes,
                  thu_muc_con: str = "", meta: dict | None = None,
                  gioi_han_mb: int = 50) -> dict:
    """Nhận MỘT tệp cho một KHÁCH (giữ chữ ký cũ — xem nhan_tai_lieu_chu)."""
    ma_ngoai = chuan_hoa_ma_ngoai(ma_ngoai)
    ma = chuan_hoa_ma_khach(ma_khach)
    _kiem_tep(ten_file, noi_dung, meta, gioi_han_mb)
    return nhan_tai_lieu_chu(khoa, chu_khach(ma), ma_ngoai, ten_file, noi_dung,
                             thu_muc_con=thu_muc_con, meta=meta, gioi_han_mb=gioi_han_mb)


def nhan_tai_lieu_nhan_vien(khoa: dict, ma_nv: str, ma_ngoai: str, ten_file: str,
                            noi_dung: bytes, thu_muc_con: str = "", meta: dict | None = None,
                            gioi_han_mb: int = 50) -> dict:
    ma_ngoai = chuan_hoa_ma_ngoai(ma_ngoai)
    _kiem_tep(ten_file, noi_dung, meta, gioi_han_mb)
    return nhan_tai_lieu_chu(khoa, chu_nhan_vien(ma_nv), ma_ngoai, ten_file, noi_dung,
                             thu_muc_con=thu_muc_con, meta=meta, gioi_han_mb=gioi_han_mb)


def nhan_tai_lieu_chu(khoa: dict, chu: dict, ma_ngoai: str, ten_file: str, noi_dung: bytes,
                      thu_muc_con: str = "", meta: dict | None = None,
                      gioi_han_mb: int = 50) -> dict:
    """Nhận MỘT tệp vào hồ sơ của `chu` (khách hoặc nhân viên): đặt vào thư
    mục hồ sơ, ghi ánh xạ, xếp hàng học nền. Gửi lại cùng (nguồn, mã ngoài):
      · cùng md5      → không làm gì ("khong_doi");
      · md5 khác      → phiên bản mới; bản cũ CHÉP sang thư mục phiên bản
                        trước khi ghi đè / đổi tên.
    Hồ sơ đã có tệp y hệt (nhân viên thả tay từ trước) → chỉ gắn ánh xạ."""
    nguon = khoa["nguon"]
    ma_ngoai = chuan_hoa_ma_ngoai(ma_ngoai)
    ten, duoi = _kiem_tep(ten_file, noi_dung, meta, gioi_han_mb)
    md5 = hashlib.md5(noi_dung).hexdigest()
    root = kho.library_root()          # qua kho để test vá một chỗ
    cu = _anh_xa(nguon, ma_ngoai)
    if cu and (cu.get("loai") or "khach") != chu["loai"]:
        raise LoiTichHop(f"external_id '{ma_ngoai}' đã dùng cho hồ sơ {LOAI_CHU[cu.get('loai') or 'khach']['ten']}", 409)
    if cu and cu.get("trang_thai") != "da_go" and (
            cu.get("client_id") != chu.get("client_id") or cu.get("employee_id") != chu.get("employee_id")):
        raise LoiTichHop(f"external_id '{ma_ngoai}' đang thuộc hồ sơ khác — gỡ trước hoặc dùng mã khác", 409)
    song = cu is not None and cu.get("trang_thai") != "da_go"

    # 1. Không đổi: cùng mã ngoài, cùng md5, tệp còn trên đĩa.
    if song and cu.get("checksum") == md5 and _tep_hien_tai(cu) is not None:
        return trang_thai(nguon, ma_ngoai) | {"ok": True, "ket_qua": "khong_doi"}

    # 2. Hồ sơ đã có tệp y hệt → gắn ánh xạ, không chép thêm.
    co_san = _tai_lieu_cung_md5(md5, chu)
    if co_san:
        if song and cu.get("khoa_kho") != co_san["drive_file_id"]:
            luu_phien_ban(cu, "doi_ten")
            _don_ban_cu(cu)
        _luu_anh_xa(nguon, ma_ngoai, co_san["drive_file_id"], md5, chu, ten,
                    suy_trang_thai("da_nhan", co_san), khoa.get("id"), meta)
        _audit_nhan(khoa, chu["ma"], ma_ngoai, co_san["drive_file_id"], md5, "da_co_trong_kho")
        return trang_thai(nguon, ma_ngoai) | {"ok": True, "ket_qua": "da_co_trong_kho"}

    # 3. Ghi tệp vào thư mục hồ sơ.
    thu_muc = chu["thu_muc"]
    dest_dir = thu_muc.joinpath(*thu_muc_con_hop_le(thu_muc_con))
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / ten
    khoa_cu = cu.get("khoa_kho") if song else None
    chia_se = bool(khoa_cu) and _con_anh_xa_khac(nguon, ma_ngoai, khoa_cu)
    if dest.exists() and (local_key(root, dest) != khoa_cu or chia_se):
        # Trùng tên tệp của mã khác / tệp nhân viên thả tay / tệp dùng chung → hậu tố.
        dest = dest_dir / f"{Path(ten).stem} [{ma_ngoai}]{duoi}"
    key = local_key(root, dest)
    if song:
        luu_phien_ban(cu, "thay_ban" if khoa_cu == key else "doi_ten")
    tam = dest_dir / f".tmp-{secrets.token_hex(6)}{duoi}"
    tam.write_bytes(noi_dung)
    os.replace(tam, dest)
    if song and khoa_cu and khoa_cu != key:
        _don_ban_cu(cu)
    _luu_anh_xa(nguon, ma_ngoai, key, md5, chu, ten, "da_nhan", khoa.get("id"), meta)
    kho.quen_dem()
    ket_qua = "phien_ban_moi" if song else "da_nhan"
    _audit_nhan(khoa, chu["ma"], ma_ngoai, key, md5, ket_qua)
    xep_hang_hoc(nguon, ma_ngoai)
    return {"ok": True, "ket_qua": ket_qua, "ma_ngoai": ma_ngoai, "loai": chu["loai"],
            "ma_khach": chu["ma"] if chu["loai"] == "khach" else None,
            "ma_nhan_vien": chu["ma"] if chu["loai"] == "nhan_vien" else None,
            "trang_thai": "da_nhan", "mo_ta": MO_TA_TRANG_THAI["da_nhan"],
            "ten_file": dest.name, "duong_dan": kho.rel_cua(dest, root), "checksum": md5,
            "document_id": None}


def gan_ma(khoa: dict, chu: dict, duong_dan: str, ma_ngoai: str, meta: dict | None = None) -> dict:
    """Gắn mã ngoài cho một tệp ĐÃ CÓ trong hồ sơ (tệp cũ không do CRM gửi) để
    từ đó CRM thay bản / gỡ / xem phiên bản theo mã của mình."""
    nguon = khoa["nguon"]
    ma_ngoai = chuan_hoa_ma_ngoai(ma_ngoai)
    if meta is not None and not isinstance(meta, dict):
        raise LoiTichHop("metadata phải là một đối tượng JSON")
    folder = chu.get("thu_muc")
    if folder is None:
        raise LoiTichHop("Hồ sơ chưa có thư mục trong kho", 404)
    p = duong_dan_trong(folder, duong_dan)
    root = kho.library_root()
    key = local_key(root, p)
    cu = _anh_xa(nguon, ma_ngoai)
    if cu and cu.get("trang_thai") != "da_go":
        if cu.get("khoa_kho") == key:
            return trang_thai(nguon, ma_ngoai) | {"ok": True, "ket_qua": "da_gan_truoc_do"}
        raise LoiTichHop(f"external_id '{ma_ngoai}' đã gắn cho tệp khác", 409)
    khac = _ma_ngoai_theo_khoa(nguon, [key]).get(key)
    if khac:
        raise LoiTichHop(f"Tệp này đã gắn external_id '{khac}'", 409)
    if p.suffix.lower() not in ALLOWED:
        raise LoiTichHop(f"Định dạng {p.suffix} chưa hỗ trợ — không gắn mã được", 415)
    md5 = file_md5(p)
    doc = _tai_lieu_theo_khoa_kho(key)
    tt = suy_trang_thai("da_nhan", doc if doc and doc.get("active", True) else None)
    _luu_anh_xa(nguon, ma_ngoai, key, md5, chu, p.name, tt, khoa.get("id"), meta)
    _audit_nhan(khoa, chu["ma"], ma_ngoai, key, md5, "gan_ma")
    if not (doc and doc.get("active", True)):
        xep_hang_hoc(nguon, ma_ngoai)
    return trang_thai(nguon, ma_ngoai) | {"ok": True, "ket_qua": "da_gan_ma"}


def _audit_nhan(khoa, ma, ma_ngoai, key, md5, ket_qua):
    try:
        with db.session(role="internal", admin=True) as conn:
            db.audit(conn, None, "tich_hop_nhan_tai_lieu", None, None,
                     {"khoa_id": khoa.get("id"), "nguon": khoa.get("nguon"), "ma": ma,
                      "ma_ngoai": ma_ngoai, "key": key, "md5": md5, "ket_qua": ket_qua})
    except Exception:  # noqa: BLE001 — nhật ký hỏng không được chặn tài liệu
        pass


def go(nguon: str, ma_ngoai: str, khoa: dict | None = None) -> dict:
    """Gỡ theo mã ngoài — bản hiện tại CHÉP sang thư mục phiên bản rồi gỡ như
    nút Gỡ trên web; gọi lặp lại vô hại."""
    ax = _anh_xa_hoac_404(nguon, ma_ngoai, khoa)
    ma_ngoai = ax["ma_ngoai"]
    if ax.get("trang_thai") == "da_go":
        return trang_thai(nguon, ma_ngoai) | {"ok": True, "ket_qua": "da_go_truoc_do"}
    pb = luu_phien_ban(ax, "go")
    # Mã ngoài khác dùng chung tệp → chỉ bỏ ánh xạ này (_don_ban_cu tự nhường).
    da_chuyen = _don_ban_cu(ax)
    _cap_nhat_trang_thai(nguon, ma_ngoai, "da_go")
    kho.quen_dem()
    try:
        with db.session(role="internal", admin=True) as conn:
            db.audit(conn, None, "tich_hop_go", None, None,
                     {"khoa_id": (khoa or {}).get("id"), "nguon": nguon, "ma_ngoai": ma_ngoai,
                      "key": ax["khoa_kho"], "da_chuyen_toi": da_chuyen,
                      "phien_ban": (pb or {}).get("so")})
    except Exception:  # noqa: BLE001
        pass
    return trang_thai(nguon, ma_ngoai) | {"ok": True, "ket_qua": "da_go",
                                         "phien_ban_luu": (pb or {}).get("so")}


# ---------------------------------------------------------------------------
# Link xem tạm — trình duyệt người dùng CRM mở thẳng tệp, khoá không lộ
# ---------------------------------------------------------------------------
# 01/10/2026 chủ dự án: "CRM tải file lên và xem thẳng được luôn, mở file khách
# bất kỳ đều xem nhanh". Khoá hdsi_ KHÔNG được xuống trình duyệt (mở toàn bộ
# hồ sơ), nên máy chủ CRM xin một link có chữ ký, hết hạn sau vài phút, gắn
# đúng MỘT tệp + MỘT chế độ (xem / tải). Trình duyệt mở link đó trực tiếp.
#
# Không lưu gì trong CSDL: link tự mang (tệp, chế độ, hạn, khoá tạo ra nó) và
# chữ ký HMAC bằng khoá bí mật của máy chủ (dẫn xuất riêng từ JWT_SECRET, không
# dùng chung chữ ký với token đăng nhập). Lúc mở, máy chủ kiểm lại: chữ ký, hạn,
# khoá tạo link CÒN hiệu lực và CÒN quyền — thu hồi khoá hay bỏ quyền là mọi
# link của khoá đó chết ngay, không phải chờ hết hạn.
CHE_DO_LINK = {"preview", "download"}
LINK_MAC_DINH_GIAY = 600
LINK_TOI_THIEU_GIAY = 60
LINK_TOI_DA_GIAY = 3600


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _khoa_ky_link() -> bytes:
    from app import auth
    return hashlib.sha256(b"hds-view-link|" + auth._get_jwt_secret().encode()).digest()


def _ky(noi_dung: str) -> str:
    return _b64(hmac.new(_khoa_ky_link(), noi_dung.encode(), hashlib.sha256).digest())


def tao_link(khoa: dict, dich: dict, che_do: str = "preview", het_han_giay: int | None = None,
             bay_gio: float | None = None) -> dict:
    """dich = {"x": external_id} hoặc {"o": "khach"|"nhan_vien", "c": mã, "p": path}."""
    if che_do not in CHE_DO_LINK:
        raise LoiTichHop("mode chỉ nhận 'preview' hoặc 'download'")
    ttl = LINK_MAC_DINH_GIAY if het_han_giay is None else int(het_han_giay)
    ttl = max(LINK_TOI_THIEU_GIAY, min(LINK_TOI_DA_GIAY, ttl))
    het_han = int((bay_gio or time.time()) + ttl)
    payload = {"v": 1, "k": khoa["id"], "n": khoa["nguon"], "m": che_do, "e": het_han, **dich}
    than = _b64(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode())
    return {"token": f"{than}.{_ky(than)}", "het_han": het_han, "ttl": ttl, "che_do": che_do}


def doc_link(token: str, bay_gio: float | None = None) -> dict:
    """Kiểm chữ ký + hạn; trả payload. Sai → 401, hết hạn → 410."""
    try:
        than, chu_ky = (token or "").split(".")
        hop_le = hmac.compare_digest(chu_ky, _ky(than))
        payload = json.loads(_unb64(than)) if hop_le else None
    except (ValueError, TypeError):
        payload = None
    if not isinstance(payload, dict) or payload.get("v") != 1:
        raise LoiTichHop("Link không hợp lệ", 401)
    if (bay_gio or time.time()) > payload.get("e", 0):
        raise LoiTichHop("Link đã hết hạn — mở lại tệp từ CRM để lấy link mới", 410)
    return payload


def khoa_theo_id(khoa_id: int) -> dict | None:
    """Khoá còn hiệu lực (chưa thu hồi) theo id — để link chết theo khoá."""
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT id, ten, nguon, quyen, user_id FROM khoa_tich_hop
                            WHERE id=%s AND revoked_at IS NULL""", (khoa_id,))
            r = cur.fetchone()
    if not r:
        return None
    return {"id": r[0], "ten": r[1], "nguon": r[2], "quyen": _quyen_tu_csdl(r[3]), "user_id": r[4]}


def tep_theo_dich(khoa: dict, dich: dict) -> tuple:
    """(Path, tên tệp, md5 hoặc None) mà một link / lời gọi trỏ tới — kiểm lại
    quyền theo loại hồ sơ và nhốt đường dẫn trong hồ sơ như mọi đường khác."""
    if not co_quyen(khoa, "documents:read"):
        raise LoiTichHop("Khoá này không có quyền 'documents:read'", 403)
    if dich.get("x"):
        return tep_hien_tai(khoa["nguon"], dich["x"], khoa)
    loai = dich.get("o")
    if loai not in LOAI_CHU:
        raise LoiTichHop("Link không hợp lệ", 401)
    kiem_quyen_loai(khoa, loai)
    chu = (chu_khach if loai == "khach" else chu_nhan_vien)(dich.get("c") or "", tao_thu_muc=False)
    if chu["thu_muc"] is None:
        raise LoiTichHop("Hồ sơ chưa có thư mục trên máy chủ", 404)
    p = duong_dan_trong(chu["thu_muc"], dich.get("p") or "")
    return p, p.name, None


def mo_link(token: str, bay_gio: float | None = None) -> tuple:
    """Link → (khoá, payload, Path, tên, md5). Dùng cho GET /view/{token}."""
    payload = doc_link(token, bay_gio)
    khoa = khoa_theo_id(payload.get("k"))
    if not khoa or khoa["nguon"] != payload.get("n"):
        raise LoiTichHop("Khoá tạo link đã bị thu hồi — link không còn dùng được", 401)
    p, ten, md5 = tep_theo_dich(khoa, payload)
    return khoa, payload, p, ten, md5


def ghi_nhat_ky_xem(khoa: dict, dich: dict, che_do: str, qua_link: bool):
    """Hồ sơ khách / nhân sự là dữ liệu nhạy cảm: mỗi lần CRM mở xem đều ghi."""
    try:
        with db.session(role="internal", admin=True) as conn:
            db.audit(conn, None, "tich_hop_xem", None, None,
                     {"khoa_id": khoa.get("id"), "nguon": khoa.get("nguon"), "che_do": che_do,
                      "qua_link": qua_link, **{k: v for k, v in dich.items() if k in ("x", "o", "c", "p")}})
    except Exception:  # noqa: BLE001
        pass


def tao_ban_xem_truoc_nen(rel: str):
    """Sau khi học xong tệp Word/Excel CRM gửi: sinh sẵn bản PDF xem trước để
    lần mở đầu tiên hiện ngay (không phải chờ LibreOffice). Hỏng thì thôi —
    lúc xem sẽ thử sinh lại."""
    try:
        p = kho.duong_dan_kho(rel)
        if p.is_file() and p.suffix.lower() in xem_truoc.DOI_SANG_PDF:
            xem_truoc.ban_xem(p)
            xem_truoc.don_cache()
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# Học nền — một luồng, giữ cùng khoá tệp với bộ quét cron
# ---------------------------------------------------------------------------
_HANG_DOI: "queue.Queue[tuple[str, str]]" = queue.Queue()
_LUONG: threading.Thread | None = None
_LUONG_LOCK = threading.Lock()
_DA_KHOI_PHUC = False


@contextlib.contextmanager
def _giu_khoa_quet():
    """Chờ rồi giữ khoá tệp của bộ quét cron trong lúc học một tệp. Máy không
    có fcntl (Windows) hay không mở được tệp khoá thì học không khoá."""
    fh = None
    fcntl = None
    try:
        import fcntl as _fcntl
        fcntl = _fcntl
        fh = open(KHOA_QUET, "a")
        fcntl.flock(fh, fcntl.LOCK_EX)
    except (ImportError, OSError):
        if fh:
            fh.close()
        fh = None
    try:
        yield
    finally:
        if fh is not None:
            try:
                fcntl.flock(fh, fcntl.LOCK_UN)
            except OSError:
                pass
            fh.close()


def hoc_mot(nguon: str, ma_ngoai: str) -> str | None:
    """Học (ĐỒNG BỘ) một tài liệu đã nhận — luồng nền gọi; test gọi thẳng.
    Trả về trạng thái sau khi học, hoặc None nếu không còn gì để học."""
    ax = _anh_xa(nguon, ma_ngoai)
    if not ax or ax.get("trang_thai") == "da_go":
        return None
    rel = kho.rel_tu_khoa(ax["khoa_kho"])
    if not rel:
        _cap_nhat_trang_thai(nguon, ma_ngoai, "loi", "Danh tính tệp không nằm trong kho")
        return "loi"
    _cap_nhat_trang_thai(nguon, ma_ngoai, "dang_hoc")
    with _giu_khoa_quet():
        try:
            r = kho.hoc_file(rel, None, auto_approve=False)
        except kho.LoiKho as e:
            _cap_nhat_trang_thai(nguon, ma_ngoai, "loi", str(e))
            return "loi"
        except Exception as e:  # noqa: BLE001 — lỗi lạ cũng phải hiện cho CRM thấy
            _cap_nhat_trang_thai(nguon, ma_ngoai, "loi", f"{type(e).__name__}: {e}"[:500])
            return "loi"
    tt = "da_hoc" if r.get("trang_thai") in ("da_hoc", "canh_bao") else "cho_duyet"
    _cap_nhat_trang_thai(nguon, ma_ngoai, tt, None)
    tao_ban_xem_truoc_nen(rel)          # ngoài khoá quét: không giữ chân cron
    return tt


def _vong_hoc():
    while True:
        nguon, ma_ngoai = _HANG_DOI.get()
        try:
            hoc_mot(nguon, ma_ngoai)
        except Exception as e:  # noqa: BLE001 — luồng nền không được chết
            print(f"[tich_hop] lỗi học {nguon}/{ma_ngoai}: {e}")
        finally:
            _HANG_DOI.task_done()


def _bao_dam_luong():
    global _LUONG
    with _LUONG_LOCK:
        if _LUONG is None or not _LUONG.is_alive():
            _LUONG = threading.Thread(target=_vong_hoc, name="tich-hop-hoc", daemon=True)
            _LUONG.start()


def xep_hang_hoc(nguon: str, ma_ngoai: str):
    _bao_dam_luong()
    _HANG_DOI.put((nguon, ma_ngoai))


def khoi_phuc_hang_doi_mot_lan():
    """Máy chủ khởi động lại giữa chừng thì hàng đợi trong bộ nhớ mất; xếp lại
    những tài liệu còn ở mốc da_nhan/dang_hoc. Gọi ở lời gọi API đầu tiên (không
    gọi lúc import để test/không có CSDL vẫn nạp được mô-đun)."""
    global _DA_KHOI_PHUC
    if _DA_KHOI_PHUC:
        return 0
    _DA_KHOI_PHUC = True
    try:
        with db.session(role="internal", admin=True) as conn:
            with conn.cursor() as cur:
                cur.execute("""SELECT nguon, ma_ngoai FROM tich_hop_tai_lieu
                                WHERE trang_thai IN ('da_nhan','dang_hoc')
                                ORDER BY updated_at""")
                rows = cur.fetchall()
    except Exception:  # noqa: BLE001
        return 0
    for nguon, ma_ngoai in rows:
        xep_hang_hoc(nguon, ma_ngoai)
    return len(rows)


def so_dang_cho() -> int:
    return _HANG_DOI.qsize()
