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
