"""lich_chay.py — Bật/tắt các LỊCH CHẠY TỰ ĐỘNG (cron) từ trang Cài đặt.

Yêu cầu chủ dự án 01/10/2026: "thêm tất cả cron (on/off) lên web, trong cài
đặt để nhân viên chủ động" — ví dụ tạm dừng bộ quét kho trong lúc chép lô hồ
sơ từ USB (không thì nó học tệp chép dở), hay tắt một việc định kỳ đang gây
nghi ngờ mà không phải nhờ IT SSH vào máy chủ.

Cách làm — cố ý KHÔNG sửa script của từng việc:
  · Mọi lịch của hệ thống nằm trong crontab của user chạy backend (pc) và
    mang nhãn `# hds-ai: <tên>` ở cuối dòng. Có 3 lịch là script nằm ngoài
    git (~/tu-duyet.sh…) — không đụng được mã của chúng, nên công tắc phải
    nằm ở chính dòng cron.
  · TẮT = thêm tiền tố `#TAT# ` vào đầu dòng (cron coi là chú thích); BẬT =
    bỏ tiền tố. Dòng lệnh giữ nguyên từng ký tự — web KHÔNG sửa được lệnh,
    lịch hay thêm dòng lạ, chỉ bật/tắt đúng dòng có nhãn đã biết.
  · Hai lịch có trong mã nguồn (quét kho, sao lưu) còn "Cài lại" được nếu
    dòng biến mất khỏi crontab — đúng sự cố 16–29/09/2026: lịch sao lưu mất
    mà không ai biết, 13 ngày không có bản sao lưu.

Tắt một lịch không dừng lượt ĐANG chạy; lượt đó chạy tới hết, các lượt sau
bỏ. `--install-cron` của script (IT chạy tay) xoá dòng cũ rồi thêm dòng bật
— tức là cài lại thì lịch bật lại, đúng ý người chạy lệnh.
"""
from __future__ import annotations

import re
import subprocess
import threading
from datetime import datetime, timedelta
from pathlib import Path

from app import db

NHAN = "# hds-ai:"
TIEN_TO_TAT = "#TAT# "
_BACKEND = Path(__file__).resolve().parents[1]          # …/hds-ai
_GOC_REPO = _BACKEND.parent                              # …/hds-ai-full
_DATA = _BACKEND / "data"
_KHOA_GHI = threading.Lock()


class LoiLich(ValueError):
    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


def _chuan(s: str) -> str:
    return " ".join((s or "").lower().split())


# Các lịch đã biết. Khoá = nhãn sau "# hds-ai:" (chuẩn hoá). Lịch mang nhãn
# hds-ai lạ vẫn hiện (bật/tắt được) với tên = nhãn, chỉ thiếu mô tả.
LICH = {
    "quet kho tai lieu": {
        "ma": "quet-kho",
        "ten": "Quét kho tài liệu",
        "mo_ta": "Học tệp mới / tệp đã sửa được thả vào kho (ổ mạng, chép tay). "
                 "Tắt trong lúc chép lô lớn (USB, ổ mạng) để không học tệp chép dở, "
                 "chép xong bật lại.",
        "khi_tat": "Tệp thả vào kho sẽ KHÔNG được học cho tới khi bật lại. Tải lên "
                   "trên web và qua API vẫn học ngay.",
        "nhat_ky": "quet_kho_lich_su.log",
        "tien_trinh": r"python -m app\.local_learn",
        "cai": "*/3 * * * * /usr/bin/env bash '{repo}/deploy/hoc-tu-thu-muc.sh' --cron  # hds-ai: quet kho tai lieu",
    },
    "sao luu csdl + kho": {
        "ma": "sao-luu",
        "ten": "Sao lưu CSDL + kho",
        "mo_ta": "Sao lưu cơ sở dữ liệu (giữ 3 bản gần nhất) và toàn bộ kho tài liệu, "
                 "bản đã gỡ, phiên bản cũ ra ~/hds-backup.",
        "khi_tat": "KHÔNG có bản sao lưu mới. Máy chủ là nơi giữ bản gốc duy nhất — "
                   "chỉ tắt tạm thời, nhớ bật lại.",
        "nhat_ky": "sao_luu_lich_su.log",
        "tien_trinh": r"sao-luu\.sh",
        "nguy_hiem": True,
        "cai": "30 2 * * * /usr/bin/env bash '{repo}/deploy/sao-luu.sh' --cron  # hds-ai: sao luu CSDL + kho",
    },
    "tu duyet <20% loi": {
        "ma": "tu-duyet",
        "ten": "Tự duyệt tài liệu đọc tốt",
        "mo_ta": "Duyệt bù các tài liệu đang chờ duyệt mà tỉ lệ chữ đọc lỗi ≤ 20%.",
        "khi_tat": "Tài liệu chờ duyệt phải duyệt tay ở tab Duyệt nhãn. Tài liệu mới "
                   "đọc tốt vẫn được tự duyệt ngay lúc học.",
        "nhat_ky": "duyet_tu_dong.log",
        "tien_trinh": r"tu-duyet\.sh",
    },
    "hieu luc tu vbpl": {
        "ma": "hieu-luc",
        "ten": "Cập nhật hiệu lực văn bản luật",
        "mo_ta": "Lấy trạng thái hiệu lực chính thức từ vbpl.vn cho văn bản luật trong kho.",
        "khi_tat": "Trạng thái còn / hết hiệu lực của văn bản luật không được cập nhật.",
        "nhat_ky": "hieu_luc.log",
        "tien_trinh": r"cap-nhat-hieu-luc\.sh",
    },
    "go ban thay the": {
        "ma": "go-ban-thay-the",
        "ten": "Gỡ bản văn bản đã bị thay thế",
        "mo_ta": "Gỡ bản cũ của văn bản luật khi tệp đã được tải lại ở định dạng khác.",
        "khi_tat": "Bản cũ không tự gỡ — trợ lý có thể trả lời từ cả bản cũ lẫn bản mới.",
        "nhat_ky": "go_ban_cu.log",
        "tien_trinh": r"go-ban-thay-the\.py",
    },
}


# ---------------------------------------------------------------------------
# Phần THUẦN — đọc / sửa dòng crontab, mô tả lịch (test không cần máy chủ)
# ---------------------------------------------------------------------------
_RE_TRUONG = r"(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)"
_RE_DONG = re.compile(r"^\s*(?:#TAT#\s*)?" + _RE_TRUONG + r"\s+(.+?)\s*$")


def slug(nhan: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", _chuan(nhan)).strip("-")
    return s or "lich"


def phan_tich_dong(dong: str) -> dict | None:
    """Một dòng crontab → {bat, bieu_thuc, lenh, nhan} nếu là lịch hds-ai.
    Tắt = bắt đầu bằng '#TAT#'; chú thích khác (# …) không phải lịch."""
    if NHAN not in (dong or ""):
        return None
    s = dong.strip()
    tat = s.startswith("#TAT#")
    if s.startswith("#") and not tat:
        return None
    m = _RE_DONG.match(s)
    if not m:
        return None
    bieu_thuc = " ".join(m.group(i) for i in range(1, 6))
    lenh = m.group(6)
    nhan = lenh.split(NHAN, 1)[1].strip() if NHAN in lenh else ""
    return {"bat": not tat, "bieu_thuc": bieu_thuc, "lenh": lenh, "nhan": nhan}


def doi_dong(dong: str, bat: bool) -> str:
    """Bật/tắt một dòng — chỉ thêm / bỏ tiền tố, phần còn lại giữ nguyên."""
    s = dong.rstrip("\n")
    goc = re.sub(r"^\s*#TAT#\s*", "", s)
    return goc if bat else TIEN_TO_TAT + goc


def _mot_so(truong: str) -> int | None:
    return int(truong) if truong.isdigit() else None


def mo_ta_lich(bieu_thuc: str) -> str:
    """'*/3 * * * *' → 'Mỗi 3 phút'; '7 * * * *' → 'Mỗi giờ, phút 07';
    '30 2 * * *' → 'Hằng ngày lúc 02:30'. Dạng khác trả nguyên biểu thức."""
    t = (bieu_thuc or "").split()
    if len(t) != 5:
        return bieu_thuc
    phut, gio, ngay, thang, thu = t
    if (ngay, thang, thu) != ("*", "*", "*"):
        return bieu_thuc
    m = re.fullmatch(r"\*/(\d+)", phut)
    if m and gio == "*":
        return f"Mỗi {int(m.group(1))} phút"
    if _mot_so(phut) is not None and gio == "*":
        return f"Mỗi giờ, phút {int(phut):02d}"
    if _mot_so(phut) is not None and _mot_so(gio) is not None:
        return f"Hằng ngày lúc {int(gio):02d}:{int(phut):02d}"
    return bieu_thuc


def lan_ke_tiep(bieu_thuc: str, bay_gio: datetime) -> datetime | None:
    """Lần chạy kế tiếp cho ba dạng lịch trên (đủ cho các lịch của hệ thống)."""
    t = (bieu_thuc or "").split()
    if len(t) != 5 or tuple(t[2:]) != ("*", "*", "*"):
        return None
    phut, gio = t[0], t[1]
    goc = bay_gio.replace(second=0, microsecond=0) + timedelta(minutes=1)
    m = re.fullmatch(r"\*/(\d+)", phut)
    if m and gio == "*":
        n = int(m.group(1))
        if n <= 0:
            return None
        while goc.minute % n:
            goc += timedelta(minutes=1)
        return goc
    if _mot_so(phut) is not None and gio == "*":
        p = int(phut)
        kq = goc.replace(minute=p)
        return kq if kq >= goc else kq + timedelta(hours=1)
    if _mot_so(phut) is not None and _mot_so(gio) is not None:
        kq = goc.replace(hour=int(gio), minute=int(phut))
        return kq if kq >= goc else kq + timedelta(days=1)
    return None


def dong_cuoi(duong_dan: Path, toi_da: int = 220) -> str | None:
    """Dòng không rỗng cuối cùng của nhật ký (đọc 8 KB cuối)."""
    try:
        with duong_dan.open("rb") as fh:
            fh.seek(0, 2)
            n = fh.tell()
            fh.seek(max(0, n - 8192))
            du_lieu = fh.read().decode("utf-8", "replace")
    except OSError:
        return None
    dong = [x.strip() for x in du_lieu.splitlines() if x.strip()]
    return dong[-1][:toi_da] if dong else None


# ---------------------------------------------------------------------------
# Crontab + tiến trình — tách hàm để test vá
# ---------------------------------------------------------------------------
def doc_crontab() -> str:
    try:
        r = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=15)
    except FileNotFoundError:
        raise LoiLich("Máy chủ này không có crontab — không quản lý lịch chạy được", 501)
    if r.returncode != 0:
        if "no crontab" in (r.stderr or "").lower():
            return ""
        raise LoiLich(f"Không đọc được crontab: {(r.stderr or '').strip()[:200]}", 500)
    return r.stdout


def ghi_crontab(noi_dung: str):
    if noi_dung and not noi_dung.endswith("\n"):
        noi_dung += "\n"
    r = subprocess.run(["crontab", "-"], input=noi_dung, capture_output=True, text=True, timeout=15)
    if r.returncode != 0:
        raise LoiLich(f"Không ghi được crontab: {(r.stderr or '').strip()[:200]}", 500)


def dang_chay(mau: str | None) -> bool:
    if not mau:
        return False
    try:
        return subprocess.run(["pgrep", "-f", mau], capture_output=True, timeout=10).returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


# ---------------------------------------------------------------------------
# Nghiệp vụ
# ---------------------------------------------------------------------------
def _thong_tin(nhan: str) -> dict:
    return LICH.get(_chuan(nhan)) or {"ma": slug(nhan), "ten": nhan or "Lịch không tên"}


def _dong_lich(info: dict, dong: dict | None, bay_gio: datetime) -> dict:
    if dong:
        bieu_thuc = dong["bieu_thuc"]
    else:
        mau = phan_tich_dong(info["cai"].format(repo=str(_GOC_REPO))) if info.get("cai") else None
        bieu_thuc = mau["bieu_thuc"] if mau else None
    nhat_ky = _DATA / info["nhat_ky"] if info.get("nhat_ky") else None
    lan_cuoi = None
    if nhat_ky and nhat_ky.exists():
        lan_cuoi = datetime.fromtimestamp(nhat_ky.stat().st_mtime).isoformat(timespec="minutes")
    bat = bool(dong and dong["bat"])
    ke_tiep = lan_ke_tiep(bieu_thuc, bay_gio) if (bat and bieu_thuc) else None
    return {
        "ma": info["ma"],
        "ten": info["ten"],
        "mo_ta": info.get("mo_ta"),
        "khi_tat": info.get("khi_tat"),
        "nguy_hiem": bool(info.get("nguy_hiem")),
        "trang_thai": "bat" if bat else ("tat" if dong else "chua_cai"),
        "cai_duoc": bool(info.get("cai")) and dong is None,
        "lich": bieu_thuc,
        "lich_mo_ta": mo_ta_lich(bieu_thuc) if bieu_thuc else None,
        "ke_tiep": ke_tiep.isoformat(timespec="minutes") if ke_tiep else None,
        "dang_chay": dang_chay(info.get("tien_trinh")),
        "lan_cuoi": lan_cuoi,
        "ket_qua_cuoi": dong_cuoi(nhat_ky) if nhat_ky else None,
    }


def danh_sach(bay_gio: datetime | None = None) -> list:
    """Mọi lịch hds-ai trong crontab + lịch đã biết mà crontab thiếu."""
    bay_gio = bay_gio or datetime.now()
    tim_thay = {}
    for dong in doc_crontab().splitlines():
        d = phan_tich_dong(dong)
        if d:
            info = _thong_tin(d["nhan"])
            tim_thay.setdefault(info["ma"], (info, d))
    out = [_dong_lich(info, d, bay_gio) for info, d in tim_thay.values()]
    for info in LICH.values():
        if info["ma"] not in tim_thay and info.get("cai"):
            out.append(_dong_lich(info, None, bay_gio))
    thu_tu = {v["ma"]: i for i, v in enumerate(LICH.values())}
    return sorted(out, key=lambda x: (thu_tu.get(x["ma"], 99), x["ten"]))


def _audit(user_id, hanh_dong, ma, chi_tiet):
    try:
        with db.session(role="internal", admin=True) as conn:
            db.audit(conn, user_id, hanh_dong, "lich_chay", None, {"ma": ma, **chi_tiet})
    except Exception:  # noqa: BLE001 — nhật ký hỏng không chặn thao tác đã xong
        pass


def dat(ma: str, bat: bool, user_id=None) -> dict:
    """Bật / tắt MỘT lịch theo mã. Đọc lại crontab sau khi ghi để chắc chắn."""
    with _KHOA_GHI:
        moi, co, doi = [], False, 0
        for dong in doc_crontab().splitlines():
            d = phan_tich_dong(dong)
            if d and _thong_tin(d["nhan"])["ma"] == ma:
                co = True
                if d["bat"] != bat:
                    dong = doi_dong(dong, bat)
                    doi += 1
            moi.append(dong)
        if not co:
            cai_duoc = any(v["ma"] == ma and v.get("cai") for v in LICH.values())
            raise LoiLich("Lịch này chưa có trên máy chủ — bấm Cài lại" if cai_duoc
                          else "Không thấy lịch này", 404)
        if doi:
            ghi_crontab("\n".join(moi))
    kq = next((x for x in danh_sach() if x["ma"] == ma), None)
    if not kq or (kq["trang_thai"] == "bat") != bat:
        raise LoiLich("Đã ghi crontab nhưng đọc lại không thấy thay đổi — kiểm tra máy chủ", 500)
    if doi:
        _audit(user_id, "lich_chay_bat" if bat else "lich_chay_tat", ma, {"ten": kq["ten"]})
    return kq


def cai_lai(ma: str, user_id=None) -> dict:
    """Thêm lại dòng lịch đã biết (chỉ lịch có trong mã nguồn) khi crontab thiếu."""
    info = next((v for v in LICH.values() if v["ma"] == ma), None)
    if not info or not info.get("cai"):
        raise LoiLich("Lịch này không cài lại từ web được — nhờ IT", 400)
    with _KHOA_GHI:
        hien_tai = doc_crontab()
        for dong in hien_tai.splitlines():
            d = phan_tich_dong(dong)
            if d and _thong_tin(d["nhan"])["ma"] == ma:
                raise LoiLich("Lịch đã có trên máy chủ — dùng công tắc bật / tắt", 409)
        dong_moi = info["cai"].format(repo=str(_GOC_REPO))
        ghi_crontab((hien_tai.rstrip("\n") + "\n" if hien_tai.strip() else "") + dong_moi)
    kq = next((x for x in danh_sach() if x["ma"] == ma), None)
    if not kq or kq["trang_thai"] != "bat":
        raise LoiLich("Đã ghi crontab nhưng đọc lại không thấy lịch — kiểm tra máy chủ", 500)
    _audit(user_id, "lich_chay_cai", ma, {"ten": kq["ten"]})
    return kq
