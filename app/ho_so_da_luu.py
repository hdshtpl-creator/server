"""Bộ hồ sơ đã điền — LƯU LẠI để mở lại trong 7 ngày (18/09/2026).

Vì sao có module này: điền xong cả bộ, đóng cửa sổ là mất dấu. File kết quả
vẫn nằm trong ``data/work/template_fills/<token>`` nhưng không còn đường nào
tìm lại token — chủ dự án hỏi thẳng "nút lưu đâu".

Bản ghi chỉ là MỘT tệp JSON trỏ tới các token đã có sẵn, **không nhân bản**
file .docx: dung lượng gần như bằng 0 và không sinh ra bản sao thứ hai của hồ
sơ khách. Hết hạn thì ``template_fill.cleanup_old_fills`` dọn file, ``don_cu``
dọn bản ghi — cùng mốc 7 ngày nên không có bản ghi nào trỏ vào chỗ trống lâu.

Mỗi bản ghi mang ``user_id``: hồ sơ điền từ dữ liệu khách của một người, người
khác trong công ty không có việc gì phải mở được (chốt quyền 18/09/2026).
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path

DATA_WORK = Path(os.getenv("DATA_WORK", "./data/work"))

# Cùng mốc với template_fill.FILL_KEEP_DAYS — bản ghi không được sống lâu hơn
# file nó trỏ tới.
GIU_NGAY = 7
GIU_GIAY = GIU_NGAY * 24 * 3600

MAX_MOI_NGUOI = 50        # hồ sơ lưu cùng lúc của một người
MAX_FILE = 100            # file trong một bộ
MAX_O = 3000              # dòng bảng đối chiếu giữ lại
MAX_CHU = 500             # độ dài một giá trị
MAX_TEN = 200             # độ dài tên hồ sơ

MA_RE = re.compile(r"^[0-9a-f]{32}$")


def thu_muc() -> Path:
    return DATA_WORK / "ho_so_da_luu"


def _cat(value, gioi_han: int = MAX_CHU) -> str:
    return str(value or "").strip()[:gioi_han]


def _duong_dan(ma: str) -> Path | None:
    if not MA_RE.match(ma or ""):
        return None
    return thu_muc() / f"{ma}.json"


def _doc(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def con_lai_ngay(ban_ghi: dict, now: float | None = None) -> float:
    """Số ngày còn lại trước khi bản ghi tự xoá (làm tròn xuống 0.0)."""
    con = GIU_GIAY - ((now or time.time()) - float(ban_ghi.get("luc") or 0))
    return max(0.0, con / 86400)


def _o(ds, khoa_gia_tri: bool):
    """Gọt danh sách ô xuống đúng những trường cần để mở lại."""
    ra = []
    for o in (ds or [])[:MAX_O]:
        if not isinstance(o, dict):
            continue
        muc = {"khoa": _cat(o.get("khoa"), 200),
               "literal": _cat(o.get("literal"), 200),
               "goi_y": _cat(o.get("goi_y"), 300)}
        if khoa_gia_tri:
            muc["gia_tri"] = _cat(o.get("gia_tri"))
            muc["nguon"] = _cat(o.get("nguon"), 200)
        if muc["khoa"]:
            ra.append(muc)
    return ra


def luu(*, user_id, ten: str, kieu: str = "bo_mau", bo_id=None, bo_ten: str = "",
        files=None, zip_token=None, so_o: int = 0, da_dien=None,
        con_thieu=None, now: float | None = None) -> dict:
    """Ghi một bản ghi mới, trả chính bản ghi đó (kèm ``ma``).

    Không kiểm tra quyền ở đây — người gọi (api.py) phải xác nhận mọi token
    thuộc về ``user_id`` trước, vì token là thứ người dùng gửi lên.
    """
    if user_id is None:
        raise ValueError("bản ghi phải có chủ")
    root = thu_muc()
    root.mkdir(parents=True, exist_ok=True)
    ds_file = []
    for f in (files or [])[:MAX_FILE]:
        if not isinstance(f, dict) or not f.get("token"):
            continue
        ds_file.append({
            "token": _cat(f.get("token"), 64),
            "ten_file": _cat(f.get("ten_file"), MAX_TEN),
            "ten_ket_qua": _cat(f.get("ten_ket_qua"), MAX_TEN),
            "so_trong": int(f.get("so_trong") or 0),
        })
    ban_ghi = {
        "ma": uuid.uuid4().hex,
        "user_id": int(user_id),
        "ten": _cat(ten, MAX_TEN) or "Bộ hồ sơ đã điền",
        "kieu": "ban_cu" if kieu == "ban_cu" else "bo_mau",
        "bo_id": int(bo_id) if str(bo_id or "").strip().isdigit() else None,
        "bo_ten": _cat(bo_ten, MAX_TEN),
        "luc": float(now or time.time()),
        "files": ds_file,
        "zip_token": _cat(zip_token, 64) or None,
        "so_o": int(so_o or 0),
        "da_dien": _o(da_dien, True),
        "con_thieu": _o(con_thieu, False),
    }
    (root / f"{ban_ghi['ma']}.json").write_text(
        json.dumps(ban_ghi, ensure_ascii=False), encoding="utf-8")
    _gioi_han_moi_nguoi(int(user_id))
    return ban_ghi


def _tat_ca() -> list[tuple[Path, dict]]:
    root = thu_muc()
    if not root.exists():
        return []
    ra = []
    for path in root.glob("*.json"):
        data = _doc(path)
        if data:
            ra.append((path, data))
    return ra


def _gioi_han_moi_nguoi(user_id: int):
    """Giữ tối đa MAX_MOI_NGUOI bản ghi mỗi người — cũ nhất rơi trước.

    Không để một người lấp ổ đĩa bằng cách bấm Lưu liên tục; file .docx thì đã
    có hạn 7 ngày lo rồi.
    """
    cua_toi = sorted((p for p, d in _tat_ca() if d.get("user_id") == user_id),
                     key=lambda p: p.stat().st_mtime if p.exists() else 0,
                     reverse=True)
    for path in cua_toi[MAX_MOI_NGUOI:]:
        path.unlink(missing_ok=True)


def don_cu(now: float | None = None) -> int:
    """Xoá bản ghi quá hạn. Trả số bản ghi đã xoá."""
    moc = (now or time.time()) - GIU_GIAY
    so = 0
    for path, data in _tat_ca():
        if float(data.get("luc") or 0) < moc:
            path.unlink(missing_ok=True)
            so += 1
    return so


def danh_sach(user_id, now: float | None = None) -> list[dict]:
    """Hồ sơ đã lưu CỦA NGƯỜI NÀY, mới nhất trước. Dọn luôn bản quá hạn."""
    don_cu(now)
    ra = [d for _p, d in _tat_ca() if d.get("user_id") == int(user_id)]
    ra.sort(key=lambda d: float(d.get("luc") or 0), reverse=True)
    return ra


def lay(ma: str, user_id) -> dict | None:
    """Một bản ghi — chỉ trả khi đúng chủ (None nếu không phải)."""
    path = _duong_dan(ma)
    if path is None or not path.exists():
        return None
    data = _doc(path)
    if not data or data.get("user_id") != int(user_id):
        return None
    return data


def xoa(ma: str, user_id) -> bool:
    if lay(ma, user_id) is None:
        return False
    path = _duong_dan(ma)
    if path is None:
        return False
    path.unlink(missing_ok=True)
    return True


def doi_ten(ma: str, user_id, ten: str) -> dict | None:
    data = lay(ma, user_id)
    if data is None:
        return None
    data["ten"] = _cat(ten, MAX_TEN) or data["ten"]
    path = _duong_dan(ma)
    if path is not None:
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def dem_theo_nguoi() -> dict:
    """{user_id: số hồ sơ đã lưu} — cho thẻ theo dõi dung lượng của Quản trị."""
    dem: dict[int, int] = {}
    for _p, d in _tat_ca():
        uid = d.get("user_id")
        if isinstance(uid, int):
            dem[uid] = dem.get(uid, 0) + 1
    return dem
