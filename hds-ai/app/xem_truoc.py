"""xem_truoc.py — Bản XEM THẲNG TRONG TRÌNH DUYỆT của một tệp gốc.

Dùng chung cho nút "Xem trước" của web HDS (api._preview_pdf) và cho CRM
(/integration/v1/…/preview, link xem tạm — 01/10/2026: "CRM mở file khách bất
kỳ đều xem nhanh được, không cần tải").

  · PDF, ảnh PNG/JPG/WEBP, văn bản thuần: trả nguyên tệp, trình duyệt tự hiện.
  · Word / Excel / CSV: đổi sang PDF MỘT LẦN bằng LibreOffice (có sẵn trên máy
    chủ cho khâu đọc .doc) rồi giữ ở data/work/preview; lần sau trả ngay.
  · Loại khác (TIFF, BMP, ZIP…): không xem thẳng được — báo để tải về.

CHỐT AN TOÀN: chỉ trả inline đúng các loại trên, văn bản luôn là text/plain.
Tệp khách có thể là HTML đội lốt .doc (Confluence, trang Word web) — không bao
giờ được phát ra dưới dạng text/html trên tên miền của hệ thống.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

HIEN_THANG = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/plain; charset=utf-8",
}
DOI_SANG_PDF = {".docx", ".doc", ".xlsx", ".csv"}
TIEN_TO_CACHE_TICH_HOP = "th-"
GIU_CACHE_NGAY = 30


class LoiXemTruoc(Exception):
    def __init__(self, msg: str, status: int = 409):
        super().__init__(msg)
        self.status = status


def thu_muc_cache() -> Path:
    p = Path(os.getenv("DATA_WORK", "./data/work")) / "preview"
    p.mkdir(parents=True, exist_ok=True)
    return p


def khoa_cache(path: Path) -> str:
    """Khoá cache theo (đường dẫn, kích thước, mtime) — không phải băm cả tệp
    lớn mỗi lần xem; tệp đổi nội dung là mtime/kích thước đổi → sinh lại."""
    st = path.stat()
    h = hashlib.sha1(f"{path.resolve()}|{st.st_size}|{st.st_mtime_ns}".encode()).hexdigest()
    return TIEN_TO_CACHE_TICH_HOP + h[:32]


def pdf_tu_office(resolved: Path, cache_key) -> Path:
    """Bản PDF của một tệp Office, sinh một lần rồi dùng lại (theo mtime)."""
    out = thu_muc_cache() / (re.sub(r"[^A-Za-z0-9_-]", "_", str(cache_key)) + ".pdf")
    try:
        if out.exists() and out.stat().st_mtime >= resolved.stat().st_mtime:
            return out
    except OSError:
        pass
    soffice = shutil.which("libreoffice") or shutil.which("soffice")
    if not soffice:
        raise LoiXemTruoc("Máy chủ chưa có LibreOffice để tạo bản xem trước — hãy tải về.")
    with tempfile.TemporaryDirectory() as tmp:
        # Hồ sơ LibreOffice riêng cho mỗi lượt — hai lượt chuyển song song
        # không giẫm profile của nhau.
        cmd = [soffice, "--headless", "--convert-to", "pdf", "--outdir", tmp,
               f"-env:UserInstallation=file://{tmp}/profile", str(resolved)]
        try:
            subprocess.run(cmd, capture_output=True, timeout=120, check=True)
        except (subprocess.SubprocessError, OSError):
            raise LoiXemTruoc("Chưa chuyển được tệp này sang PDF để xem trước — hãy tải về.")
        produced = Path(tmp) / (resolved.stem + ".pdf")
        if not produced.exists():
            raise LoiXemTruoc("Chưa chuyển được tệp này sang PDF để xem trước — hãy tải về.")
        shutil.move(str(produced), str(out))
    return out


def xem_duoc(path: Path) -> bool:
    s = path.suffix.lower()
    return s in HIEN_THANG or s in DOI_SANG_PDF


def ban_xem(path: Path) -> tuple[Path, str, str]:
    """(tệp để phát, media type, tên hiển thị) cho chế độ xem thẳng."""
    s = path.suffix.lower()
    if s in HIEN_THANG:
        return path, HIEN_THANG[s], path.name
    if s in DOI_SANG_PDF:
        pdf = pdf_tu_office(path, khoa_cache(path))
        return pdf, "application/pdf", path.stem + ".pdf"
    raise LoiXemTruoc(f"Định dạng {s or '(không đuôi)'} chưa xem thẳng được trong trình duyệt — hãy tải về.", 415)


def don_cache(bay_gio: float | None = None, ngay: int = GIU_CACHE_NGAY) -> int:
    """Xoá bản xem trước của CRM (tiền tố th-) cũ hơn `ngay` ngày — xem lại thì
    sinh lại. Không đụng bản xem trước của web HDS (khoá theo id tài liệu)."""
    bay_gio = bay_gio or time.time()
    n = 0
    for p in thu_muc_cache().glob(TIEN_TO_CACHE_TICH_HOP + "*.pdf"):
        try:
            if bay_gio - p.stat().st_mtime > ngay * 86400:
                p.unlink()
                n += 1
        except OSError:
            continue
    return n
