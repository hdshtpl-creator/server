"""Cây thư mục kho tài liệu cho trang Quản trị: duyệt theo thư mục, tìm, gỡ,
tải lên và học ngay một file — không cần SSH vào máy chủ (yêu cầu 11/09/2026).

Nguồn sự thật là THƯ MỤC KHO trên máy chủ (local_learn.library_root); bảng
documents chỉ cho biết file nào đã học, đang chờ duyệt hay lỗi. Mọi đường dẫn
người dùng gửi lên là đường dẫn TƯƠNG ĐỐI trong kho và bị nhốt trong đó
(`duong_dan_kho`) — không có cách nào trỏ ra ngoài.

Gỡ tài liệu = active=false + CHUYỂN file gốc sang data/_da_go/<đường dẫn cũ>.
Bộ quét bỏ qua tài liệu đã gỡ (known_local_keys), nhưng file còn nằm trong kho
thì lần quét sau nó học lại thành tài liệu mới (bài học 07/09/2026).

Tải lên / học ngay đi ĐÚNG đường của bộ quét (auto_learn.resolve_labels theo
thư mục + learn_one) nên tài liệu nhận nhãn y như khi thả file vào thư mục và
đợi quét; chỉ khác là thấy kết quả ngay.
"""
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from app import auto_learn, db
from app.local_learn import (ALLOWED, LOCAL_PREFIX, SKIP_DIRS, SKIP_NAMES,
                             SKIP_PREFIXES, allowed_roots, file_md5,
                             is_skippable, library_root, local_key)


class LoiKho(ValueError):
    """Lỗi có thể hiện thẳng cho người dùng; api.py đổi thành HTTP 400."""


# ---------------------------------------------------------------------------
# Đường dẫn — phần thuần, test được không cần CSDL
# ---------------------------------------------------------------------------
def duong_dan_kho(rel: str, root: Path | None = None) -> Path:
    """Đường dẫn tương đối người dùng gửi → Path tuyệt đối NẰM TRONG kho.

    '' hoặc '/' là gốc kho. Chặn '..', đường dẫn tuyệt đối, ổ đĩa Windows và
    mọi đoạn bắt đầu bằng '.' hoặc '~$' (SKIP_PREFIXES của bộ quét) — cùng một
    luật với bộ quét để giao diện không hiện thứ bộ quét không bao giờ học.
    """
    root = (root or library_root()).resolve()
    rel = (rel or "").replace("\\", "/").strip().strip("/")
    if not rel:
        return root
    if re.match(r"^[A-Za-z]:", rel):
        raise LoiKho("Đường dẫn không hợp lệ")
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    for p in parts:
        if p == ".." or p.startswith(SKIP_PREFIXES) or p in SKIP_DIRS:
            raise LoiKho("Đường dẫn không hợp lệ")
    path = root.joinpath(*parts)
    try:
        path.resolve().relative_to(root)
    except ValueError:
        raise LoiKho("Đường dẫn nằm ngoài kho tài liệu")
    return path


def rel_cua(path: Path, root: Path | None = None) -> str:
    """Đường dẫn tương đối (dấu / xuôi) của một file/thư mục trong kho."""
    root = (root or library_root()).resolve()
    return path.resolve().relative_to(root).as_posix()


def rel_tu_khoa(khoa: str | None) -> str | None:
    """'local:2. BẢN ÁN/2026/x.pdf' → '2. BẢN ÁN/2026/x.pdf'; khoá khác → None."""
    if khoa and khoa.startswith(LOCAL_PREFIX):
        return khoa[len(LOCAL_PREFIX):]
    return None


def vi_tri_trong_kho(drive_file_id: str | None, source_path: str | None,
                     root: Path | None = None) -> dict:
    """VỊ TRÍ của một tài liệu trong cây thư mục kho, để hiện cho người duyệt.

    Người duyệt nhãn nhìn tiêu đề thôi thì không biết tệp nằm ở ngăn nào —
    mà ngăn chính là căn cứ gán nhãn (thư mục "9. HỒ SƠ KHÁCH HÀNG" thì là hồ
    sơ khách, "1. VĂN BẢN PHÁP LUẬT" thì là luật). Hàm thuần, không chạm CSDL.

    Ưu tiên danh tính bộ quét ('local:<đường dẫn tương đối>') vì nó luôn là
    đường dẫn TRONG kho; không có thì thử rút gọn source_path theo gốc kho.
    Tài liệu nạp từ chat/web không có tệp trên đĩa → trong_kho=False.
    """
    rel = rel_tu_khoa(drive_file_id)
    if rel is None and source_path:
        p = Path(str(source_path).replace("\\", "/"))
        goc = (root or library_root())
        try:
            goc = Path(goc).resolve()
            abs_p = p if p.is_absolute() else Path.cwd() / p
            rel = abs_p.resolve(strict=False).relative_to(goc).as_posix()
        except (ValueError, OSError):
            rel = None
    ten_tep = None
    if rel:
        rel = rel.replace("\\", "/").strip("/")
        parts = [x for x in rel.split("/") if x]
        ten_tep = parts[-1] if parts else None
        thu_muc = "/".join(parts[:-1])
        return {"trong_kho": True, "duong_dan": rel, "thu_muc": thu_muc or None,
                "ngan": parts[0] if len(parts) > 1 else None,
                "ten_tep": ten_tep,
                "duoi": Path(ten_tep).suffix.lower() if ten_tep else None}
    if source_path:
        ten_tep = Path(str(source_path).replace("\\", "/")).name or None
    return {"trong_kho": False, "duong_dan": None, "thu_muc": None, "ngan": None,
            "ten_tep": ten_tep,
            "duoi": Path(ten_tep).suffix.lower() if ten_tep else None}


def ten_thu_muc_hop_le(ten: str) -> str:
    """Tên thư mục con do người dùng đặt: một đoạn, không dấu phân cách, không
    bắt đầu bằng '.'/'~$', tối đa 120 ký tự."""
    ten = " ".join((ten or "").split())
    if not ten:
        raise LoiKho("Tên thư mục trống")
    if len(ten) > 120:
        raise LoiKho("Tên thư mục quá dài (tối đa 120 ký tự)")
    if re.search(r'[\\/:*?"<>|]', ten):
        raise LoiKho('Tên thư mục không được chứa \\ / : * ? " < > |')
    if ten in ("..", ".") or ten.startswith(SKIP_PREFIXES) or ten in SKIP_DIRS:
        raise LoiKho("Tên thư mục này bị bộ quét bỏ qua, hãy đặt tên khác")
    return ten


def thung_da_go() -> Path:
    """Nơi cất file của tài liệu đã gỡ: cạnh kho (data/_da_go), không nằm
    trong kho để bộ quét không thấy. Đặt DATA_DA_GO trong .env nếu muốn khác."""
    raw = os.getenv("DATA_DA_GO")
    if raw:
        p = Path(raw)
        return (p if p.is_absolute() else Path.cwd() / p).resolve()
    return library_root().parent / "_da_go"


def dich_da_go(thung: Path, rel: str) -> Path:
    """Đích chuyển file khi gỡ: giữ nguyên cây thư mục cũ, trùng tên thì thêm
    hậu tố thời gian — không bao giờ ghi đè một bản đã gỡ trước."""
    dest = thung / rel
    if dest.exists():
        dest = dest.with_name(f"{dest.stem}__{int(time.time())}{dest.suffix}")
    return dest


def trang_thai_file(row: dict | None, ext: str, loi: dict | None = None) -> str:
    """Nhãn trạng thái một file trong kho, từ bản ghi documents (nếu có).

    khong_ho_tro: đuôi file bộ quét không đọc · loi: đã thử học và hỏng ·
    chua_hoc: chưa có bản ghi · cho_duyet: có bản ghi nhưng chưa duyệt ·
    canh_bao: đã duyệt nhưng trích xuất có cảnh báo (scan/OCR) · da_hoc.
    """
    if ext.lower() not in ALLOWED:
        return "khong_ho_tro"
    if not row:
        return "loi" if loi else "chua_hoc"
    if not (row.get("approved") and row.get("label_verified")):
        return "cho_duyet"
    if (row.get("extraction_status") or "ready") != "ready":
        return "canh_bao"
    return "da_hoc"


# ---------------------------------------------------------------------------
# Truy vấn CSDL — tách nhỏ để test vá được
# ---------------------------------------------------------------------------
_COT = ("id", "title", "doc_type", "access_level", "approved", "label_verified",
        "extraction_status", "so_hieu", "checksum", "client_name", "active",
        "so_doan", "created_at")


def _tai_lieu_theo_khoa(keys: list) -> dict:
    """{khoá local: bản ghi} cho các file đang hỏi — chỉ tài liệu còn active."""
    if not keys:
        return {}
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT d.drive_file_id, d.id, d.title, d.doc_type, d.access_level,
                                  d.approved, d.label_verified, d.extraction_status,
                                  d.so_hieu, d.checksum, c.name, coalesce(d.active,true),
                                  (SELECT count(*) FROM chunks WHERE document_id=d.id),
                                  d.created_at
                             FROM documents d LEFT JOIN clients c ON c.id=d.client_id
                            WHERE d.drive_file_id = ANY(%s)
                              AND coalesce(d.active,true)""", (list(keys),))
            return {r[0]: dict(zip(_COT, r[1:])) for r in cur.fetchall()}


def _loi_theo_khoa(keys: list) -> dict:
    """{khoá local: lỗi học chưa xử lý} từ ingest_failures."""
    if not keys:
        return {}
    try:
        with db.session(role="internal", admin=True) as conn:
            with conn.cursor() as cur:
                cur.execute("""SELECT drive_file_id, error_code, error_message, hint
                                 FROM ingest_failures
                                WHERE resolved_at IS NULL AND drive_file_id = ANY(%s)""",
                            (list(keys),))
                return {r[0]: {"code": r[1], "message": r[2], "hint": r[3]}
                        for r in cur.fetchall()}
    except Exception:            # kho cũ chưa có bảng — không làm sập cây
        return {}


def _dem_theo_tien_to(rel_thu_muc: str) -> dict:
    """Số tài liệu đã học / chờ duyệt nằm dưới một thư mục (đệ quy)."""
    tien_to = LOCAL_PREFIX + rel_thu_muc.rstrip("/") + "/"
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT count(*),
                                  count(*) FILTER (WHERE approved AND label_verified),
                                  count(*) FILTER (WHERE NOT (approved AND label_verified))
                             FROM documents
                            WHERE drive_file_id LIKE %s AND coalesce(active,true)""",
                        (tien_to.replace("%", r"\%").replace("_", r"\_") + "%",))
            tong, da_hoc, cho_duyet = cur.fetchone()
    return {"da_hoc": da_hoc, "cho_duyet": cho_duyet, "tong_ban_ghi": tong}


# Đếm file trên đĩa của một thư mục (đệ quy) — ngăn bản án 33.000 file mất
# ~0,5 giây mỗi lần đếm, nên nhớ 2 phút; tải lên / gỡ / tạo thư mục xoá nhớ.
_NHO_DEM: dict = {}
_NHO_DEM_GIAY = 120


def _dem_file(folder: Path) -> int:
    key = str(folder)
    now = time.time()
    hit = _NHO_DEM.get(key)
    if hit and now - hit[0] < _NHO_DEM_GIAY:
        return hit[1]
    n = 0
    for duong, thu_muc_con, tap_tin in os.walk(folder):
        thu_muc_con[:] = [d for d in thu_muc_con
                          if d not in SKIP_DIRS and not d.startswith(SKIP_PREFIXES)]
        n += sum(1 for f in tap_tin
                 if not f.startswith(SKIP_PREFIXES) and f.lower() not in SKIP_NAMES)
    _NHO_DEM[key] = (now, n)
    return n


def quen_dem():
    _NHO_DEM.clear()
    _NHO_KHACH.clear()


# ---------------------------------------------------------------------------
# Duyệt cây + tìm
# ---------------------------------------------------------------------------
def _bo_qua(p: Path) -> bool:
    return (p.name in SKIP_DIRS or p.name.startswith(SKIP_PREFIXES)
            or p.name.lower() in SKIP_NAMES or is_skippable(p))


def _dong_file(p: Path, key: str, row: dict | None, loi: dict | None) -> dict:
    st = p.stat()
    trang_thai = trang_thai_file(row, p.suffix, loi)
    out = {
        "ten": p.name, "path": rel_tu_khoa(key), "kich_thuoc": st.st_size,
        "sua_luc": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime)),
        "trang_thai": trang_thai,
        "document_id": row["id"] if row else None,
        "title": row["title"] if row else None,
        "doc_type": row["doc_type"] if row else None,
        "access_level": row["access_level"] if row else None,
        "so_hieu": row["so_hieu"] if row else None,
        "client_name": row["client_name"] if row else None,
        "so_doan": row["so_doan"] if row else None,
        "loi": loi,
    }
    return out


def liet_ke(rel: str = "", q: str = "", offset: int = 0, limit: int = 200) -> dict:
    """Một tầng của cây: thư mục con (kèm số đã học) + file trong thư mục
    (phân trang, lọc theo tên) kèm trạng thái học của từng file."""
    root = library_root()
    folder = duong_dan_kho(rel, root)
    if not folder.is_dir():
        raise LoiKho("Không có thư mục này trong kho")
    rel = rel_cua(folder, root) if folder != root else ""
    thu_muc, tap_tin = [], []
    for p in sorted(folder.iterdir(), key=lambda x: x.name.lower()):
        if _bo_qua(p):
            continue
        (thu_muc if p.is_dir() else tap_tin).append(p)
    q_thap = (q or "").strip().lower()
    if q_thap:
        tap_tin = [p for p in tap_tin if q_thap in p.name.lower()]
    tong = len(tap_tin)
    trang = tap_tin[offset:offset + limit]
    keys = [local_key(root, p) for p in trang]
    rows = _tai_lieu_theo_khoa(keys)
    loi = _loi_theo_khoa(keys)
    return {
        "path": rel,
        "ten": folder.name if rel else "Kho tài liệu",
        "root": str(root),
        "thu_muc": [{"ten": d.name, "path": rel_cua(d, root), "so_file": _dem_file(d),
                     **_dem_theo_tien_to(rel_cua(d, root))} for d in thu_muc],
        "tap_tin": [_dong_file(p, k, rows.get(k), loi.get(k)) for p, k in zip(trang, keys)],
        "tong_tap_tin": tong,
        "offset": offset,
        "limit": limit,
    }


def dieu_kien_tim(q: str) -> tuple:
    """Mệnh đề WHERE + tham số cho tìm kiếm: MỖI từ trong câu tìm phải xuất
    hiện (không phân biệt hoa thường) trong tên + số hiệu + loại + trích yếu +
    đường dẫn. Tên file văn bản luật là 'Bộ-luật-91-2015-QH13' nên so cả bản
    thay '-' bằng ' ', và ghép loại + trích yếu để "Bộ luật Dân sự" khớp được
    (thử 11/09/2026: tìm 'Bộ luật Dân sự' ra 0 khi chỉ so tên). Xếp văn bản
    luật / án lệ lên trước, rồi tên ngắn hơn (khớp gọn hơn), rồi mới nhất —
    không thì 32.000 bản án nhắc "Bộ luật Dân sự" trong trích yếu chôn mất BLDS."""
    tokens = [t for t in (q or "").split() if t][:6]
    hay = ("concat_ws(' ', d.title, replace(d.title, '-', ' '), d.so_hieu, "
           "d.loai_van_ban, d.trich_yeu, d.drive_file_id)")
    return (" AND ".join(f"{hay} ILIKE %s" for _ in tokens) or "TRUE",
            [f"%{t}%" for t in tokens])


def tim(q: str, limit: int = 100) -> list:
    """Tìm tài liệu ĐÃ CÓ BẢN GHI theo tên, số hiệu, loại/trích yếu hoặc
    đường dẫn — trả kèm thư mục chứa để giao diện nhảy tới đúng chỗ trong cây."""
    dieu_kien, tham_so = dieu_kien_tim(q)
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"""SELECT d.id, d.title, d.doc_type, d.access_level, d.approved,
                                   d.label_verified, d.extraction_status, d.so_hieu,
                                   d.drive_file_id, d.source_path, c.name
                              FROM documents d LEFT JOIN clients c ON c.id=d.client_id
                             WHERE coalesce(d.active,true) AND ({dieu_kien})
                             ORDER BY (d.doc_type IN ('law','an_le')) DESC,
                                      length(d.title) ASC, d.created_at DESC
                             LIMIT %s""",
                        (*tham_so, limit))
            rows = cur.fetchall()
    root = library_root()
    out = []
    for r in rows:
        rel = rel_tu_khoa(r[8])
        if rel is None and r[9]:
            try:
                rel = Path(r[9]).resolve().relative_to(root).as_posix()
            except (ValueError, OSError):
                rel = None
        row = {"approved": r[4], "label_verified": r[5], "extraction_status": r[6]}
        out.append({
            "document_id": r[0], "title": r[1], "doc_type": r[2], "access_level": r[3],
            "so_hieu": r[7], "client_name": r[10],
            "path": rel, "thu_muc": rel.rsplit("/", 1)[0] if rel and "/" in rel else "",
            "ten": rel.rsplit("/", 1)[-1] if rel else None,
            "trang_thai": trang_thai_file(row, Path(rel).suffix if rel else ".pdf"),
        })
    return out


# ---------------------------------------------------------------------------
# Gỡ · học ngay · tải lên · tạo thư mục
# ---------------------------------------------------------------------------
def go_tai_lieu(doc_id: int, user_id) -> dict:
    """active=false + chuyển file gốc ra thùng đã gỡ. Bot ngừng dùng ngay
    (retrieve lọc active); bộ quét không học lại vì file không còn trong kho."""
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT id, title, source_path, drive_file_id, coalesce(active,true)
                             FROM documents WHERE id=%s""", (doc_id,))
            row = cur.fetchone()
    if not row:
        raise LoiKho("Không thấy tài liệu")
    if not row[4]:
        raise LoiKho("Tài liệu này đã được gỡ trước đó")

    da_chuyen = None
    if row[2]:
        path = Path(row[2])
        if not path.is_absolute():
            path = Path.cwd() / path
        try:
            resolved = path.resolve(strict=True)
        except (FileNotFoundError, OSError):
            resolved = None
        if resolved is not None:
            for goc in allowed_roots():
                try:
                    rel = resolved.relative_to(goc).as_posix()
                except ValueError:
                    continue
                dest = dich_da_go(thung_da_go(), rel)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(resolved), str(dest))
                da_chuyen = str(dest)
                break

    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE documents SET active=false, updated_at=now() WHERE id=%s",
                        (doc_id,))
        db.audit(conn, user_id, "kho_go", "documents", doc_id,
                 {"title": row[1], "key": row[3], "da_chuyen_toi": da_chuyen})
    quen_dem()
    return {"ok": True, "document_id": doc_id, "title": row[1], "da_chuyen_toi": da_chuyen}


def hoc_file(rel: str, user_id, auto_approve: bool = False) -> dict:
    """Học (hoặc học lại nếu nội dung đổi) MỘT file trong kho, đúng đường của
    bộ quét. `auto_approve`: người có quyền duyệt cho dùng ngay — chỉ khi trích
    xuất sạch, cùng luật với /files/upload."""
    root = library_root()
    path = duong_dan_kho(rel, root)
    if not path.is_file():
        raise LoiKho("Không thấy file này trong kho")
    if path.suffix.lower() not in ALLOWED:
        raise LoiKho(f"Định dạng {path.suffix} chưa hỗ trợ; dùng "
                     + ", ".join(sorted(e.lstrip('.').upper() for e in ALLOWED)))
    parts = list(path.relative_to(root).parts[:-1])
    labels, ly_do = auto_learn.resolve_labels(parts)
    if not labels:
        raise LoiKho(f"Thư mục chưa xếp được loại tài liệu: {ly_do}")

    key = local_key(root, path)
    fp = file_md5(path)
    cu = _tai_lieu_theo_khoa([key]).get(key)
    if cu and cu.get("checksum") == fp:
        return {"ok": True, "document_id": cu["id"], "title": cu["title"],
                "trang_thai": trang_thai_file(cu, path.suffix), "warnings": [],
                "note": "Nội dung không đổi so với bản đã học — không học lại."}

    loc = " / ".join(parts)
    diag: dict = {}
    ok = auto_learn.learn_one(
        path, labels, key, fp, replace_id=cu["id"] if cu else None,
        diagnostics=diag,
        prev_approved=bool(cu and cu.get("approved") and cu.get("label_verified")),
        source_kind="local")
    if not ok:
        err = diag.get("error") or {"code": "extraction_failed",
                                    "message": "Không đọc được nội dung.",
                                    "hint": "Kiểm tra định dạng file rồi học lại."}
        auto_learn._record_failure(key, path.name, loc, err)
        raise LoiKho(f"Không học được: {err.get('message')} {err.get('hint') or ''}".strip())
    auto_learn._clear_failure(key)

    moi = _tai_lieu_theo_khoa([key]).get(key)
    if not moi:
        raise LoiKho("Đã học nhưng không thấy bản ghi — thử tải lại trang")
    if (auto_approve and moi.get("extraction_status", "ready") == "ready"
            and not (moi["approved"] and moi["label_verified"])):
        with db.session(role="internal", admin=True) as conn:
            with conn.cursor() as cur:
                cur.execute("""UPDATE documents SET approved=true, label_verified=true,
                                                    uploaded_by=coalesce(uploaded_by,%s)
                                WHERE id=%s""", (user_id, moi["id"]))
        moi["approved"] = moi["label_verified"] = True
    with db.session(role="internal", admin=True) as conn:
        db.audit(conn, user_id, "kho_hoc", "documents", moi["id"],
                 {"key": key, "auto_approve": auto_approve,
                  "warnings": (diag.get("warnings") or [])[:5]})
    quen_dem()
    trang_thai = trang_thai_file(moi, path.suffix)
    note = {"da_hoc": "Đã học, bot dùng được ngay.",
            "canh_bao": "Đã học nhưng trích xuất có cảnh báo (scan/OCR).",
            "cho_duyet": "Đã học, đang chờ duyệt nhãn trước khi bot dùng."}.get(trang_thai, "")
    return {"ok": True, "document_id": moi["id"], "title": moi["title"],
            "trang_thai": trang_thai, "warnings": diag.get("warnings") or [], "note": note}


def cho_tai_len(rel_thu_muc: str, ten_file: str) -> Path:
    """Đích để ghi file tải lên: thư mục phải có thật, đuôi file bộ quét đọc
    được, và KHÔNG ghi đè file đang có (gỡ bản cũ trước nếu muốn thay)."""
    root = library_root()
    folder = duong_dan_kho(rel_thu_muc, root)
    if not folder.is_dir():
        raise LoiKho("Không có thư mục này trong kho")
    if folder == root:
        raise LoiKho("Không tải thẳng vào gốc kho — chọn một ngăn (thư mục) để bộ quét biết loại tài liệu")
    ten = Path(ten_file or "").name
    if not ten or ten.startswith(SKIP_PREFIXES):
        raise LoiKho("Tên file không hợp lệ")
    if Path(ten).suffix.lower() not in ALLOWED:
        raise LoiKho(f"Định dạng {Path(ten).suffix or '(không có đuôi)'} chưa hỗ trợ; dùng "
                     + ", ".join(sorted(e.lstrip('.').upper() for e in ALLOWED)))
    dest = folder / ten
    if dest.exists():
        raise LoiKho(f"Trong thư mục đã có file tên '{ten}' — gỡ bản cũ trước nếu muốn thay")
    return dest


def tao_thu_muc(rel_cha: str, ten: str, user_id=None) -> dict:
    root = library_root()
    cha = duong_dan_kho(rel_cha, root)
    if not cha.is_dir():
        raise LoiKho("Không có thư mục cha này trong kho")
    ten = ten_thu_muc_hop_le(ten)
    moi = cha / ten
    if moi.exists():
        raise LoiKho(f"Đã có '{ten}' trong thư mục này")
    moi.mkdir()
    quen_dem()
    with db.session(role="internal", admin=True) as conn:
        db.audit(conn, user_id, "kho_tao_thu_muc", None, None, {"path": rel_cua(moi, root)})
    return {"ok": True, "path": rel_cua(moi, root), "ten": ten}


# ---------------------------------------------------------------------------
# Thư mục hồ sơ khách — nhìn từ phía ĐĨA (yêu cầu 18/09/2026)
# ---------------------------------------------------------------------------
# Tab Hồ sơ khách 360° chỉ liệt kê khách ĐÃ có tài liệu học xong: bản ghi
# clients sinh ra lúc bộ quét học được tệp đầu tiên trong thư mục khách. Đo
# 17/09/2026: 1.230 trên 1.571 thư mục khách trống hoặc chỉ chứa zip, không
# hiện ở đâu cả, và người xem tưởng hệ thống bỏ sót. Ở đây MỖI thư mục khách
# trên đĩa là một dòng, kể cả trống, kèm số tệp theo nhãn học; mở dòng ra là
# từng tệp với nhãn của nó. Cùng luật bỏ rác và cùng luật nhãn với bộ quét.
TRANG_THAI_DEM = ("da_hoc", "canh_bao", "cho_duyet", "chua_hoc", "loi", "khong_ho_tro")
TINH_TRANG_THU_MUC = ("trong", "bo_qua", "khong_doc_duoc", "chua_hoc", "cho_duyet",
                      "mot_phan", "da_hoc")
# Bộ lọc giao diện: từng tình trạng, 'co_tep' (có tệp), 'can_xu_ly' (chưa học đủ
# vì bất kỳ lý do gì trừ trống).
LOC_HOP_LE = {"", "co_tep", "can_xu_ly", *TINH_TRANG_THU_MUC}
_NHO_KHACH: dict = {}


def _ban_do_nhan():
    """(cats, subs, roots) từ cài đặt drive_map — tách để test vá được."""
    return auto_learn._load_map()


def _khach_theo_ma() -> dict:
    """{MÃ viết hoa: (id, tên)} của mọi khách trong hệ thống."""
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT upper(code), id, name FROM clients WHERE code IS NOT NULL")
            return {r[0]: (r[1], r[2]) for r in cur.fetchall()}


def _khong_dau(s: str) -> str:
    """Bỏ dấu, hạ chữ thường, gộp khoảng trắng — để gõ 'cong ty' ra 'CÔNG TY'."""
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", s.replace("đ", "d").replace("Đ", "d")).strip().lower()


def thu_muc_goc_khach(root: Path | None = None, roots=None) -> list:
    """Các thư mục 'Hồ sơ khách hàng' ở tầng gốc kho, theo bản đồ nhãn
    (client_roots) — cùng cách nhận ra ngăn khách với auto_learn.resolve_labels."""
    root = root or library_root()
    if roots is None:
        roots = _ban_do_nhan()[2]
    if not root.is_dir():
        return []
    return [p for p in sorted(root.iterdir(), key=lambda x: x.name.lower())
            if p.is_dir() and not _bo_qua(p) and auto_learn._norm(p.name) in roots]


def _tep_trong(folder: Path) -> list:
    """Mọi tệp trong một thư mục (đệ quy), bỏ đúng rác như bộ quét; tệp nằm
    ngay trong thư mục đứng trước tệp ở thư mục con, thứ tự ổn định."""
    out = []
    for duong, thu_muc_con, tap_tin in os.walk(folder):
        thu_muc_con[:] = sorted((d for d in thu_muc_con
                                 if d not in SKIP_DIRS and not d.startswith(SKIP_PREFIXES)),
                                key=str.lower)
        for f in sorted(tap_tin, key=str.lower):
            if f.startswith(SKIP_PREFIXES) or f.lower() in SKIP_NAMES:
                continue
            out.append(Path(duong) / f)
    return out


def _dem_thu_muc_con(folder: Path) -> int:
    n = 0
    for _duong, thu_muc_con, _tap_tin in os.walk(folder):
        thu_muc_con[:] = [d for d in thu_muc_con
                          if d not in SKIP_DIRS and not d.startswith(SKIP_PREFIXES)]
        n += len(thu_muc_con)
    return n


def ly_do_thu_muc_khach(ten: str, ban_do=None) -> tuple:
    """(mã, tên khách, lý do bộ quét BỎ QUA cả thư mục hoặc None) — cùng luật
    với auto_learn.resolve_labels nhưng không chạm CSDL, không tạo khách."""
    cats, subs, roots = ban_do or _ban_do_nhan()
    code, cname = auto_learn._client_code_and_name(ten)
    if not code:
        return None, None, ("Chưa tách được mã khách từ tên thư mục — đặt tên dạng "
                            "'1729. Tên công ty' hoặc '[MÃ] Tên khách' rồi bộ quét sẽ học")
    if auto_learn._ma_ngan_dat_nham(code, cname, cats, subs, roots):
        return code, cname, ("Trông như ngăn con đặt nhầm ở tầng khách (mã 1–2 chữ số, tên "
                             "trùng một loại giấy tờ) — chuyển vào đúng thư mục khách")
    return code, cname, None


def _dem_trang_thai(tep: list, keys: list, rows: dict, loi: dict) -> dict:
    dem = {k: 0 for k in TRANG_THAI_DEM}
    for p, k in zip(tep, keys):
        dem[trang_thai_file(rows.get(k), p.suffix, loi.get(k))] += 1
    return dem


def tinh_trang_thu_muc(so_file: int, dem: dict, ly_do) -> str:
    """Một chữ cho cả thư mục: trống · bộ quét bỏ qua · không đọc được (chỉ
    zip/rar hoặc toàn tệp lỗi) · chưa học · chờ duyệt · học một phần · đã học đủ."""
    if so_file == 0:
        return "trong"
    if ly_do:
        return "bo_qua"
    doc_duoc = so_file - dem["khong_ho_tro"]
    da_hoc = dem["da_hoc"] + dem["canh_bao"]
    if doc_duoc == 0 or dem["loi"] == doc_duoc:
        return "khong_doc_duoc"
    if da_hoc == doc_duoc:
        return "da_hoc"
    if da_hoc > 0:
        return "mot_phan"
    if dem["cho_duyet"] > 0:
        return "cho_duyet"
    return "chua_hoc"


def _khop_loc(dong: dict, loc: str) -> bool:
    if not loc:
        return True
    if loc == "co_tep":
        return dong["so_file"] > 0
    if loc == "can_xu_ly":
        return dong["tinh_trang"] not in ("trong", "da_hoc")
    return dong["tinh_trang"] == loc


def _khoa_sap_xep(dong: dict):
    """Mã số xếp theo số thật (9 trước 1729), rồi mã chữ, rồi thư mục không mã."""
    ma = dong.get("ma") or ""
    ten = _khong_dau(dong["ten"])
    if ma.isdigit():
        return (0, int(ma), ten)
    if ma:
        return (1, 0, _khong_dau(ma) + " " + ten)
    return (2, 0, ten)


def _theo_lo(keys: list, fn, co: int = 4000) -> dict:
    """Gọi truy vấn theo lô — kho khách 7.000 tệp vẫn một vài truy vấn."""
    out = {}
    for i in range(0, len(keys), co):
        out.update(fn(keys[i:i + co]))
    return out


def _dong_thu_muc_khach(d: Path, tep: list, ks: list, rows: dict, loi: dict,
                        ban_do, khach: dict, root: Path) -> dict:
    ma, ten_khach, ly_do = ly_do_thu_muc_khach(d.name, ban_do)
    dem = _dem_trang_thai(tep, ks, rows, loi)
    kh = khach.get((ma or "").upper())
    return {
        "ten": d.name, "path": rel_cua(d, root), "ma": ma, "ten_khach": ten_khach,
        "client_id": kh[0] if kh else None, "client_name": kh[1] if kh else None,
        "ly_do": ly_do, "so_file": len(tep), "dem": dem,
        "tinh_trang": tinh_trang_thu_muc(len(tep), dem, ly_do),
    }


def _tom_tat_thu_muc_khach(root: Path, ban_do) -> list:
    """Một dòng cho MỖI thư mục khách trên đĩa (kể cả trống). Đi cây 7.000 tệp
    + hỏi CSDL mất khoảng một giây, nên nhớ 2 phút; học/gỡ/tải lên xoá nhớ."""
    now = time.time()
    hit = _NHO_KHACH.get(str(root))
    if hit and now - hit[0] < _NHO_DEM_GIAY:
        return hit[1]
    muc = []
    for goc in thu_muc_goc_khach(root, ban_do[2]):
        for d in sorted(goc.iterdir(), key=lambda x: x.name.lower()):
            if not d.is_dir() or _bo_qua(d):
                continue
            tep = _tep_trong(d)
            muc.append((d, tep, [local_key(root, p) for p in tep]))
    moi_khoa = [k for _d, _t, ks in muc for k in ks]
    rows = _theo_lo(moi_khoa, _tai_lieu_theo_khoa)
    loi = _theo_lo(moi_khoa, _loi_theo_khoa)
    khach = _khach_theo_ma()
    out = [_dong_thu_muc_khach(d, tep, ks, rows, loi, ban_do, khach, root)
           for d, tep, ks in muc]
    out.sort(key=_khoa_sap_xep)
    _NHO_KHACH[str(root)] = (now, out)
    return out


def danh_sach_thu_muc_khach(q: str = "", loc: str = "", offset: int = 0,
                            limit: int = 100) -> dict:
    """Danh sách thư mục khách trên đĩa: lọc theo tình trạng, tìm theo tên/mã
    (không dấu), phân trang; kèm tổng cho cả kho khách để thẻ đầu trang có số."""
    if loc not in LOC_HOP_LE:
        raise LoiKho("Bộ lọc không hợp lệ")
    root = library_root()
    ban_do = _ban_do_nhan()
    goc = thu_muc_goc_khach(root, ban_do[2])
    if not goc:
        raise LoiKho("Kho chưa có thư mục 'Hồ sơ khách hàng' (xem bản đồ nhãn, mục client_roots)")
    tat_ca = _tom_tat_thu_muc_khach(root, ban_do)
    tong = {"tong_thu_muc": len(tat_ca), "tong_tep": 0,
            "theo_tinh_trang": {k: 0 for k in TINH_TRANG_THU_MUC},
            "dem": {k: 0 for k in TRANG_THAI_DEM}}
    for d in tat_ca:
        tong["tong_tep"] += d["so_file"]
        tong["theo_tinh_trang"][d["tinh_trang"]] += 1
        for k in TRANG_THAI_DEM:
            tong["dem"][k] += d["dem"][k]
    tu = _khong_dau(q).split()
    ket = []
    for d in tat_ca:
        if not _khop_loc(d, loc):
            continue
        if tu:
            hay = _khong_dau(f"{d['ten']} {d['client_name'] or ''}")
            if not all(t in hay for t in tu):
                continue
        ket.append(d)
    return {"goc": [rel_cua(g, root) for g in goc], "tong": tong,
            "thu_muc": ket[offset:offset + limit], "tong_khop": len(ket),
            "offset": offset, "limit": limit}


def tep_trong_thu_muc_khach(rel: str) -> dict:
    """Từng tệp trong MỘT thư mục khách (đệ quy) kèm nhãn học và thư mục con
    chứa nó. Chỉ nhận thư mục nằm ngay dưới ngăn 'Hồ sơ khách hàng'."""
    root = library_root()
    folder = duong_dan_kho(rel, root)
    ban_do = _ban_do_nhan()
    if not folder.is_dir() or folder.parent not in thu_muc_goc_khach(root, ban_do[2]):
        raise LoiKho("Không phải thư mục khách trong ngăn 'Hồ sơ khách hàng'")
    tep = _tep_trong(folder)[:3000]
    ks = [local_key(root, p) for p in tep]
    rows = _theo_lo(ks, _tai_lieu_theo_khoa)
    loi = _theo_lo(ks, _loi_theo_khoa)
    dong = _dong_thu_muc_khach(folder, tep, ks, rows, loi, ban_do, _khach_theo_ma(), root)
    tap_tin = []
    for p, k in zip(tep, ks):
        t = _dong_file(p, k, rows.get(k), loi.get(k))
        t["thu_muc_con"] = "" if p.parent == folder else p.parent.relative_to(folder).as_posix()
        tap_tin.append(t)
    dong["tap_tin"] = tap_tin
    dong["so_thu_muc_con"] = _dem_thu_muc_con(folder)
    return dong


# ---------------------------------------------------------------------------
# Quét lại cả kho từ giao diện (nút "Quét lại" trên thẻ trạng thái quét)
# ---------------------------------------------------------------------------
# Máy chủ không có lịch quét (hds-ai-quet-kho.timer chưa cài), nên ngoài SSH
# đây là cách duy nhất để học file nhân viên thả qua Samba. Bộ quét chạy như
# tiến trình con của backend (python -m app.local_learn, phiên riêng để sống
# qua lúc backend khởi động lại), nhật ký ghi ra data/quet_kho.log; hai lượt
# quét KHÔNG được chạy song song (cùng scanner, cùng bảng — bài học 07/09).
_QUET: dict = {}


def _log_quet() -> Path:
    return library_root().parent / "quet_kho.log"


def duoi_log(path: Path, n: int = 6) -> list:
    """n dòng cuối có nghĩa của nhật ký (bỏ cảnh báo thư viện, dòng trống)."""
    try:
        data = path.read_bytes()[-8000:].decode("utf-8", "replace")
    except OSError:
        return []
    bo = ("warnings.warn", "RequestsDependencyWarning", "urllib3")
    lines = [l.rstrip() for l in data.splitlines()
             if l.strip() and not any(x in l for x in bo)]
    return lines[-n:]


def la_lenh_quet(cmdline: bytes) -> bool:
    """/proc/<pid>/cmdline là một bộ quét thật (không phải --dry-run)."""
    return b"app.local_learn" in cmdline and b"--dry-run" not in cmdline


def _tien_trinh_quet_khac():
    """pid của bộ quét đang chạy ngoài tầm theo dõi (khởi động từ SSH/nohup)."""
    proc_dir = Path("/proc")
    if not proc_dir.is_dir():
        return None
    me = os.getpid()
    for p in proc_dir.iterdir():
        if not p.name.isdigit() or int(p.name) == me:
            continue
        try:
            cmd = (p / "cmdline").read_bytes()
        except OSError:
            continue
        if la_lenh_quet(cmd):
            return int(p.name)
    return None


def trang_thai_quet() -> dict:
    """Đang quét không, ai khởi động, đuôi nhật ký; và kết quả lượt web gần nhất."""
    q = _QUET
    proc = q.get("proc")
    if proc is not None:
        rc = proc.poll()
        if rc is None:
            return {"dang_chay": True, "started_at": q["started_at"], "pid": proc.pid,
                    "nguon": "web", "log_tail": duoi_log(q["log"]), "ket_thuc": None}
        q["ket_thuc"] = {"started_at": q["started_at"],
                         "finished_at": datetime.now(timezone.utc).isoformat(),
                         "ma_thoat": rc, "log_tail": duoi_log(q["log"])}
        q["proc"] = None
        quen_dem()
    pid = _tien_trinh_quet_khac()
    if pid:
        return {"dang_chay": True, "started_at": None, "pid": pid, "nguon": "ngoai",
                "log_tail": duoi_log(_log_quet()), "ket_thuc": None}
    return {"dang_chay": False, "started_at": None, "pid": None, "nguon": None,
            "log_tail": [], "ket_thuc": q.get("ket_thuc")}


def bat_dau_quet(user_id) -> dict:
    if trang_thai_quet()["dang_chay"]:
        raise LoiKho("Đang có một lượt quét chạy — đợi xong rồi bấm lại")
    log = _log_quet()
    log.parent.mkdir(parents=True, exist_ok=True)
    backend_dir = Path(__file__).resolve().parent.parent
    with log.open("wb") as fh:
        proc = subprocess.Popen(
            [sys.executable, "-m", "app.local_learn"],
            cwd=str(backend_dir), stdout=fh, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, start_new_session=True,
            env={**os.environ, "PYTHONUNBUFFERED": "1"})
    started_at = datetime.now(timezone.utc).isoformat()
    _QUET.update({"proc": proc, "started_at": started_at, "log": log,
                  "user_id": user_id, "ket_thuc": None})
    with db.session(role="internal", admin=True) as conn:
        db.audit(conn, user_id, "kho_quet", None, None, {"pid": proc.pid})
    return {"ok": True, "pid": proc.pid, "started_at": started_at}
