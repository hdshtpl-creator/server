"""
local_learn.py — Bot TỰ HỌC tài liệu từ THƯ MỤC TRÊN MÁY CHỦ.

Quyết định 27/08/2026 của chủ dự án: **bỏ Google Drive, kho tài liệu nằm hẳn
trên máy chủ HDS.** Module này thay `auto_learn.py` ở phần lấy file; toàn bộ
phần đã được kiểm chứng — phân nhãn theo tên thư mục, cổng duyệt (PDF luôn
chờ người), kế thừa trạng thái duyệt, ghi nhận file không đọc được — được
TÁI DÙNG NGUYÊN từ auto_learn chứ không viết lại, để hai đường không lệch nhau.

    Thư mục kho (DATA_LIB, mặc định ./data/raw)
    ├── 1. VĂN BẢN PHÁP LUẬT/        → law · công khai
    ├── ...
    ├── 9. HỒ SƠ KHÁCH HÀNG/
    │   └── [SUNGROUP] Tập đoàn Sun/ → access_level=client
    └── uploads/                     ← BỎ QUA: file tải lên qua web, đã có bản ghi riêng

DANH TÍNH một tài liệu = **đường dẫn tương đối trong kho**, lưu ở cột
`documents.drive_file_id` dưới dạng `local:1. VĂN BẢN PHÁP LUẬT/luat-dn.pdf`.
Dùng lại đúng cột đó (thay vì thêm cột mới) để mọi thứ đang khoá theo nó vẫn
chạy nguyên: `existing()`, kế thừa duyệt khi thay bản mới, bảng
`relearn_approvals`, và hai script học lại trong deploy/.

BỐN CHỐT AN TOÀN (đều do rà soát đối kháng 27/08/2026 chỉ ra, đừng gỡ):

1. **Chưa chuyển danh tính thì KHÔNG quét.** Quét khi bảng còn tài liệu mang
   mã Drive sẽ tạo một bản ghi thứ hai cho TỪNG file trong kho — kho nhân đôi,
   trích dẫn nhân đôi, và bản cũ đóng băng vĩnh viễn.
2. **Kho vơi bất thường thì DỪNG.** Ổ mạng chưa mount trông y hệt "người dùng
   xoá sạch tài liệu"; báo xanh trong tình huống đó là nguy hiểm hơn im lặng.
3. **Đổi tên / chuyển thư mục là DI CHUYỂN, không phải file mới.** Nhận ra
   bằng md5 nội dung, rồi gắn lại nhãn theo thư mục mới — nếu không, một cú
   kéo-thả giữa hai thư mục khách sẽ nhân đôi tài liệu và giữ nhãn khách CŨ.
4. **Mất trạng thái duyệt phải kêu to**, kể cả khi trích xuất sạch — PDF sửa
   nội dung luôn rơi lại hàng chờ, đó là lúc bot lặng lẽ mất tài liệu.

Chạy tay:      python -m app.local_learn              # học file mới/sửa
               python -m app.local_learn --dry-run    # chỉ liệt kê, không ghi
Chuyển đổi:    python -m app.local_learn --chuyen-doi # gắn lại danh tính cho
               tài liệu đã học từ Drive (chạy MỘT LẦN, TRƯỚC mọi lượt quét)
               thêm --nguoc để trả lại danh tính Drive cũ
Chạy định kỳ:  deploy/hoc-tu-thu-muc.sh --install-timer
"""
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from app import auto_learn, db
from app.ingest import ExtractionError, SUPPORTED_EXTENSIONS

load_dotenv()

LOCAL_PREFIX = "local:"

# Thư mục KHO tài liệu. Mặc định trùng DATA_RAW: cây file đồng bộ từ Drive
# trước đây đã nằm sẵn ở đó, nên chuyển sang chế độ local KHÔNG phải chép lại
# gì. Muốn tách riêng (vd chia sẻ Samba một thư mục sạch) thì đặt DATA_LIB —
# nhớ rằng rào an toàn của nút Tải về/Xem trước đọc CẢ HAI (xem allowed_roots).
DATA_LIB = Path(os.getenv("DATA_LIB", os.getenv("DATA_RAW", "./data/raw")))

# Kho vơi hơn tỉ lệ này so với số tài liệu đã học → coi là ổ chưa mount, DỪNG.
MIN_LIBRARY_RATIO = 0.5

# Thư mục con KHÔNG quét: 'uploads' là nơi API cất file người dùng tải lên qua
# web — những file đó đã có bản ghi documents riêng (source_kind='web'); quét
# lại là tạo bản ghi trùng.
SKIP_DIRS = {"uploads", ".git", ".tmp", "__pycache__"}

# Rác của hệ điều hành và file khoá của Office (~$ban_hop_dong.docx).
SKIP_PREFIXES = ("~$", ".")
SKIP_NAMES = {"thumbs.db", "desktop.ini", ".ds_store"}

ALLOWED = set(SUPPORTED_EXTENSIONS)


# ---------------------------------------------------------------------------
# Đường dẫn
# ---------------------------------------------------------------------------
def library_root() -> Path:
    root = DATA_LIB
    if not root.is_absolute():
        root = Path.cwd() / root
    return root.resolve()


def allowed_roots() -> list:
    """Các thư mục được phép mở tệp gốc: KHO (DATA_LIB) + DATA_RAW.

    api.py và template_fill.py nhốt đường dẫn trong DATA_RAW. Tách kho ra chỗ
    khác mà không mở rào ở đây thì nút Tải về / Xem trước trả 404 "Tệp gốc
    không còn trên máy chủ" cho toàn bộ tài liệu — dùng CHUNG một hàm để hai
    rào không lệch nhau.
    """
    roots, seen = [], set()
    for raw in (os.getenv("DATA_LIB"), os.getenv("DATA_RAW", "./data/raw")):
        if not raw:
            continue
        p = Path(raw)
        p = (p if p.is_absolute() else Path.cwd() / p).resolve()
        if p not in seen:
            seen.add(p)
            roots.append(p)
    return roots


def is_skippable(path: Path) -> bool:
    name = path.name
    if name.lower() in SKIP_NAMES:
        return True
    return name.startswith(SKIP_PREFIXES)


def walk_library(root: Path):
    """[(đường dẫn file, [thư mục cha…])] — cùng dạng dữ liệu với auto_learn.walk
    để dùng lại resolve_labels không phải sửa gì."""
    out = []
    if not root.exists():
        return out
    for path in sorted(root.rglob("*")):
        if not path.is_file() or is_skippable(path):
            continue
        rel = path.relative_to(root)
        parts = list(rel.parts[:-1])
        if any(part in SKIP_DIRS or part.startswith(SKIP_PREFIXES) for part in parts):
            continue
        out.append((path, parts))
    return out


def local_key(root: Path, path: Path) -> str:
    """Danh tính bền của một file trong kho: đường dẫn tương đối, dấu / xuôi."""
    return LOCAL_PREFIX + path.relative_to(root).as_posix()


def file_md5(path: Path, chunk=1024 * 1024) -> str:
    h = hashlib.md5()
    with path.open("rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Truy vấn dùng chung
# ---------------------------------------------------------------------------
def unmigrated_drive_docs() -> int:
    """Số tài liệu còn mang danh tính Drive. Khác 0 nghĩa là CHƯA chuyển đổi."""
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT count(*) FROM documents
                            WHERE drive_file_id IS NOT NULL
                              AND drive_file_id NOT LIKE %s""", (LOCAL_PREFIX + "%",))
            return cur.fetchone()[0]


def known_local_keys():
    """{danh tính: (doc_id, tiêu đề, checksum)} của tài liệu gắn với kho local."""
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT drive_file_id, id, title, checksum FROM documents
                            WHERE drive_file_id LIKE %s""", (LOCAL_PREFIX + "%",))
            return {r[0]: (r[1], r[2], r[3]) for r in cur.fetchall()}


def rekey_document(doc_id, new_key, new_path):
    """Gắn tài liệu sang danh tính mới khi người dùng đổi tên / chuyển thư mục."""
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""UPDATE documents SET drive_file_id=%s, source_path=%s,
                                                updated_at=now()
                            WHERE id=%s""", (new_key, str(new_path), doc_id))
        db.audit(conn, None, "local_move", "documents", doc_id,
                 {"new_key": new_key, "path": str(new_path)})


# ---------------------------------------------------------------------------
# Chuyển đổi một lần: tài liệu học từ Drive → danh tính local
# ---------------------------------------------------------------------------
def migrate_drive_keys(root: Path, dry_run=False):
    """Gắn lại danh tính cho tài liệu đã học từ Drive, dựa trên source_path.

    KHÔNG có bước này, lần quét đầu tiên coi mọi file trong kho là MỚI và học
    lại từ đầu — vừa mất hàng giờ vừa nhân đôi cả kho.

    Đồng thời **đặt lại mốc so sánh** (`checksum`) bằng md5 BYTE của tệp đang
    nằm trên đĩa. Cần thiết vì bản ghi nạp tay (`app.ingest`) lưu md5 của
    *văn bản đã trích xuất*, không phải của tệp — không đặt lại thì lượt quét
    đầu tiên coi chúng là "đã sửa" và học lại toàn bộ.

    Giữ mã Drive cũ ở `prev_source_key` để còn đường lùi.

    Trả về dict: {"updated", "blocked", "outside", "total"}.
    """
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT id, source_path FROM documents
                            WHERE source_path IS NOT NULL
                              AND (drive_file_id IS NULL OR drive_file_id NOT LIKE %s)
                              AND coalesce(source_kind,'') IN ('drive','manual','local')""",
                        (LOCAL_PREFIX + "%",))
            rows = cur.fetchall()

    moved, outside = [], 0
    for doc_id, source_path in rows:
        p = Path(source_path)
        if not p.is_absolute():
            p = Path.cwd() / p
        try:
            key = local_key(root, p.resolve())
        except (ValueError, OSError):
            outside += 1
            continue
        try:
            digest = file_md5(p)     # tệp còn trên đĩa → lấy md5 byte làm mốc mới
        except OSError:
            digest = None            # không đọc được: giữ nguyên mốc cũ
        moved.append((doc_id, key, digest))

    if dry_run or not moved:
        return {"updated": 0, "blocked": [], "outside": outside, "total": len(moved)}

    updated, blocked = 0, []
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            for doc_id, key, digest in moved:
                # Trùng khoá (hai bản ghi cùng trỏ một tệp) thì KHÔNG ghi đè —
                # nhưng phải đếm và báo, đừng để báo thành công cho việc đã từ chối.
                cur.execute("""UPDATE documents
                                  SET prev_source_key = coalesce(prev_source_key, drive_file_id),
                                      drive_file_id = %s,
                                      source_kind = 'local',
                                      checksum = coalesce(%s, checksum),
                                      updated_at = now()
                                WHERE id = %s
                                  AND NOT EXISTS (SELECT 1 FROM documents d2
                                                   WHERE d2.drive_file_id=%s AND d2.id<>%s)""",
                            (key, digest, doc_id, key, doc_id))
                if cur.rowcount:
                    updated += 1
                else:
                    blocked.append((doc_id, key))
        db.audit(conn, None, "local_migrate_keys", "documents", None,
                 {"updated": updated, "blocked": len(blocked),
                  "outside": outside, "root": str(root)})
    return {"updated": updated, "blocked": blocked, "outside": outside,
            "total": len(moved)}


def revert_drive_keys(dry_run=False):
    """Trả lại danh tính Drive cũ (đường lùi của --chuyen-doi)."""
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT count(*) FROM documents
                            WHERE prev_source_key IS NOT NULL""")
            n = cur.fetchone()[0]
            if dry_run or not n:
                return n
            cur.execute("""UPDATE documents
                              SET drive_file_id = prev_source_key,
                                  prev_source_key = NULL,
                                  source_kind = 'drive',
                                  updated_at = now()
                            WHERE prev_source_key IS NOT NULL""")
        db.audit(conn, None, "local_revert_keys", "documents", None, {"rows": n})
    return n


# ---------------------------------------------------------------------------
# Lượt quét
# ---------------------------------------------------------------------------
def _keys_tu_web() -> set:
    """Danh tính những file do bộ quét web tải về (app/web_watch.py).

    Bọc try/except vì đây là quan hệ MỘT CHIỀU và tuỳ chọn: kho local chạy
    được trọn vẹn khi chưa ai bật bộ quét web, và một lỗi ở đó không được
    phép làm hỏng lượt học của cả kho.
    """
    try:
        from app import web_watch
        return web_watch.keys_tu_web()
    except Exception as e:  # noqa: BLE001
        print(f"[CẢNH BÁO] Không đọc được danh sách file tải từ web: {e}")
        return set()


def run(dry_run=False):
    root = library_root()
    started_at = datetime.now(timezone.utc)
    if not root.exists():
        print(f"[LỖI] Không thấy thư mục kho: {root}")
        print("      Tạo thư mục đó (hoặc đặt DATA_LIB trong .env) rồi chạy lại.")
        sys.exit(1)

    # CHỐT 1 — chưa chuyển danh tính thì không được quét (xem docstring đầu file).
    stale = unmigrated_drive_docs()
    if stale:
        print(f"[DỪNG] {stale} tài liệu vẫn mang danh tính Drive.")
        print("       Quét bây giờ sẽ học lại TOÀN BỘ kho và tạo bản ghi TRÙNG.")
        print("       Chạy trước:  python -m app.local_learn --chuyen-doi")
        if not dry_run:
            sys.exit(1)
        print("       (--dry-run: vẫn liệt kê bên dưới, nhưng con số sẽ sai lệch.)")

    review_mode = ("TỰ DUYỆT" if auto_learn.AUTO_APPROVE
                   else "CHỜ NGƯỜI DUYỆT (mặc định an toàn)")
    print(f">> Chế độ nhập: {review_mode}")
    print(f">> Quét kho tài liệu: {root}")
    items = walk_library(root)
    print(f"   {len(items)} file.\n")

    known = known_local_keys()
    # CHỐT 2 — kho vơi bất thường: ổ mạng chưa mount trông y hệt "xoá sạch".
    if known and len(items) < max(1, int(len(known) * MIN_LIBRARY_RATIO)):
        print(f"[DỪNG] Kho chỉ thấy {len(items)} tệp trong khi đã học "
              f"{len(known)} tài liệu từ thư mục này.")
        print(f"       Nhiều khả năng ổ chưa mount hoặc mất quyền đọc: {root}")
        print("       KHÔNG ghi kết quả quét. Kiểm tra:  mount | grep " + str(root))
        sys.exit(1)

    seen_keys = set()
    pending = []          # file chưa có bản ghi — chờ đối chiếu di chuyển
    n_new = n_upd = n_skip = n_move = n_unmapped = n_badext = 0
    new_items, updated_items, skipped_items = [], [], []
    error_items, warning_items, unapproved_items = [], [], []

    def note_learn_result(path, loc, extraction_info, was_live):
        """Ghi nhận cảnh báo trích xuất VÀ việc mất trạng thái duyệt.

        CHỐT 4: hai chuyện này khác nhau. Một PDF sửa nội dung có thể trích
        xuất sạch (không cảnh báo) nhưng vẫn rơi lại hàng chờ vì chính sách
        'PDF luôn phải người duyệt' — trước đây chuông chỉ reo khi có cảnh
        báo, nên đúng ca đó bot lặng lẽ mất tài liệu đang phục vụ.
        """
        if extraction_info.get("warnings"):
            warning_items.append({
                "name": path.name, "location": loc,
                "method": extraction_info.get("method"),
                "warnings": extraction_info["warnings"],
                "requires_review": not extraction_info.get("approved", False),
                "was_live": was_live,
            })
        if was_live and not extraction_info.get("approved"):
            print(f"     [GỠ KHỎI KHO] {path.name}: bản đã duyệt bị thay bằng bản "
                  "chờ duyệt. Bot KHÔNG dùng tài liệu này cho tới khi duyệt lại "
                  "— vào Quản trị → Duyệt nhãn tài liệu.")
            unapproved_items.append({
                "name": path.name, "location": loc,
                "reason": ("PDF luôn phải duyệt lại sau khi đổi nội dung"
                           if path.suffix.lower() == ".pdf"
                           else "trích xuất có cảnh báo"),
                "warnings": extraction_info.get("warnings") or [],
            })

    # CHỐT 4 của bộ quét web: file do máy tự tải từ Internet luôn chờ người
    # duyệt, kể cả khi kho đang bật tự duyệt. Đọc một lần cho cả lượt quét —
    # không có bộ quét web thì đây là tập rỗng và không ai bị ảnh hưởng.
    tu_web = _keys_tu_web()

    def learn(path, loc, labels, key, fingerprint, row):
        """Học một file (mới hoặc thay bản cũ). Trả về True nếu thành công."""
        try:
            extraction_info = {}
            was_live = bool(row and row[7] and row[8])
            ok = auto_learn.learn_one(path, labels, key, fingerprint,
                                      replace_id=row[0] if row else None,
                                      diagnostics=extraction_info,
                                      prev_approved=was_live, source_kind="local",
                                      force_pending=key in tu_web)
            if ok:
                note_learn_result(path, loc, extraction_info, was_live)
                auto_learn._clear_failure(key)
                return True
            error = extraction_info.get("error") or {
                "code": "extraction_failed", "message": "Không đọc được nội dung.",
                "hint": "Kiểm tra định dạng file rồi học lại.",
            }
            error_items.append({
                "name": path.name, "location": loc,
                "code": error.get("code"), "error": error.get("message"),
                "hint": error.get("hint"), "preserved_existing": bool(row),
            })
            auto_learn._record_failure(key, path.name, loc, error)
            return False
        except Exception as e:  # noqa: BLE001 — một file hỏng không dừng cả lượt
            print(f"     [LỖI] {path.name}: {e}")
            if isinstance(e, ExtractionError):
                d = e.as_dict()
                error_items.append({"name": path.name, "location": loc,
                                    "code": d["code"], "error": d["message"],
                                    "hint": d["hint"], "preserved_existing": bool(row)})
            else:
                error_items.append({"name": path.name, "location": loc,
                                    "code": "unexpected_error", "error": str(e)[:500],
                                    "hint": "Xem journal của hds-ai-quet-kho.",
                                    "preserved_existing": bool(row)})
            return False

    def apply_labels(row, path, labels, loc):
        """Nội dung không đổi — chỉ cập nhật nhãn/tiêu đề nếu thư mục đã đổi."""
        cur_labels = (row[2], row[3], row[4], row[5], row[6], row[10])
        new_labels = (labels["doc_type"], labels["access_level"], labels["client_id"],
                      labels["department_id"], labels.get("matter_id"),
                      labels.get("title_context"))
        wanted_title = auto_learn.compose_title(path.stem, labels.get("title_context"))
        new_title = wanted_title if row[9] != wanted_title else None
        if cur_labels != new_labels or new_title:
            if not dry_run:
                auto_learn.relabel(row[0], labels, title=new_title)
            why = ("cập nhật nhãn (khách/loại)" if cur_labels != new_labels
                   else f"đổi tiêu đề → '{new_title}'")
            print(f"   [GẮN LẠI] {path.name}  ← {loc}: {why}")
            updated_items.append({"name": path.name, "location": loc,
                                  "doc_type": labels["doc_type"],
                                  "access_level": labels["access_level"]})
            return True
        return False

    # ---- Vòng 1: file đã có bản ghi xử lý ngay, file lạ để dành ------------
    for path, parts in items:
        loc = "/".join(parts) or "(gốc)"
        key = local_key(root, path)
        seen_keys.add(key)
        ext = path.suffix.lower()

        if ext not in ALLOWED:
            n_badext += 1
            reason = (f"định dạng '{ext or '(không có đuôi)'}' chưa hỗ trợ; "
                      "dùng PDF, DOCX, DOC, TXT, MD, XLSX hoặc CSV")
            print(f"   [BỎ QUA] {path.name}  ← {loc}: {reason}")
            skipped_items.append({"name": path.name, "location": loc,
                                  "reason": reason, "code": "unsupported_format"})
            continue

        labels, reason = auto_learn.resolve_labels(parts, create_missing_client=not dry_run)
        if labels is None:
            print(f"   [BỎ QUA] {path.name}  ← {loc}: {reason}")
            n_unmapped += 1
            skipped_items.append({"name": path.name, "location": loc, "reason": reason})
            continue

        try:
            fingerprint = file_md5(path)
        except OSError as exc:
            error_items.append({"name": path.name, "location": loc,
                                "code": "file_unreadable", "error": str(exc)[:300],
                                "hint": "Kiểm tra quyền đọc tệp trên máy chủ.",
                                "preserved_existing": True})
            continue

        row = auto_learn.existing(key)
        if row is None:
            # Chưa rõ là file MỚI hay file CŨ vừa đổi tên — quyết định sau khi
            # biết trọn danh sách file còn lại trong kho (CHỐT 3).
            pending.append((path, parts, loc, labels, key, fingerprint))
            continue

        if row[1] == fingerprint:
            if apply_labels(row, path, labels, loc):
                n_upd += 1
            else:
                n_skip += 1
            continue

        tag = f"{labels['access_level']}/{labels['doc_type']}"
        if labels["client_id"]:
            tag += f"/client={labels['client_id']}"
        print(f"   [CẬP NHẬT] {path.name}  ← {loc}  → {tag}")
        item_info = {"name": path.name, "location": loc, "doc_type": labels["doc_type"],
                     "access_level": labels["access_level"]}
        if dry_run:
            updated_items.append(item_info)
            n_upd += 1
        elif learn(path, loc, labels, key, fingerprint, row):
            updated_items.append(item_info)
            n_upd += 1

    # ---- Vòng 2: đối chiếu di chuyển / đổi tên trước khi coi là file mới ----
    missing = {k: v for k, v in known.items() if k not in seen_keys}
    # Chỉ ghép khi md5 khớp DUY NHẤT ở cả hai phía; trùng md5 nhiều bản (hai
    # bản sao giống hệt) thì thà học mới còn hơn gắn nhầm tài liệu sang khách khác.
    by_sum_missing = {}
    for k, (doc_id, title, checksum) in missing.items():
        by_sum_missing.setdefault(checksum, []).append((k, doc_id, title))
    by_sum_pending = {}
    for entry in pending:
        by_sum_pending.setdefault(entry[5], []).append(entry)

    for path, parts, loc, labels, key, fingerprint in pending:
        cands = by_sum_missing.get(fingerprint) or []
        if len(cands) == 1 and len(by_sum_pending.get(fingerprint, [])) == 1:
            old_key, doc_id, _title = cands[0]
            print(f"   [DI CHUYỂN] {path.name}: {old_key[len(LOCAL_PREFIX):]} → {loc}")
            if not dry_run:
                rekey_document(doc_id, key, path)
                row = auto_learn.existing(key)
                if row:
                    apply_labels(row, path, labels, loc)
            missing.pop(old_key, None)
            by_sum_missing.pop(fingerprint, None)
            n_move += 1
            continue

        tag = f"{labels['access_level']}/{labels['doc_type']}"
        if labels["client_id"]:
            tag += f"/client={labels['client_id']}"
        print(f"   [MỚI] {path.name}  ← {loc}  → {tag}")
        item_info = {"name": path.name, "location": loc, "doc_type": labels["doc_type"],
                     "access_level": labels["access_level"]}
        if dry_run:
            new_items.append(item_info)
            n_new += 1
        elif learn(path, loc, labels, key, fingerprint, None):
            new_items.append(item_info)
            n_new += 1

    # ---- File đã biến mất khỏi thư mục -------------------------------------
    # CHỈ BÁO, không tự xoá: xoá tài liệu là mất cả vector lẫn lịch sử trích dẫn.
    missing_items = [{"name": title or k, "location": k[len(LOCAL_PREFIX):],
                      "document_id": doc_id}
                     for k, (doc_id, title, _sum) in missing.items()]
    if missing_items:
        print(f"\n[CHÚ Ý] {len(missing_items)} tài liệu còn trong kho tri thức "
              "nhưng KHÔNG còn tệp trong thư mục:")
        for item in missing_items[:10]:
            print(f"   · #{item['document_id']} {item['name']}")
        print("   Bot vẫn trả lời bằng nội dung đã học. Muốn gỡ hẳn: đưa tệp trở "
              "lại kho, hoặc nhờ IT chạy SQL (xem deploy/CHUYEN_VE_LOCAL.md).")

    n_ig = n_unmapped + n_badext
    print(f"\n{n_new} mới | {n_upd} cập nhật | {n_move} di chuyển | {n_skip} không đổi | "
          f"{n_ig} bỏ qua | {len(error_items)} lỗi | {len(warning_items)} cảnh báo")
    if unapproved_items:
        print(f"{len(unapproved_items)} tài liệu ĐANG PHỤC VỤ vừa rơi lại hàng chờ duyệt "
              "— mở Quản trị → Duyệt nhãn tài liệu.")
    if not dry_run and (n_new or n_upd):
        if auto_learn.AUTO_APPROVE:
            print("Đã học xong — file sạch dùng ngay; file có cảnh báo vẫn chờ duyệt.")
        else:
            print("Đang chờ duyệt — mở /admin → Duyệt nhãn tài liệu.")

    if not dry_run:
        counts = {"scanned": len(items), "new": n_new, "updated": n_upd,
                  "moved": n_move, "unchanged": n_skip, "unmapped": n_unmapped,
                  "bad_format": n_badext, "errors": len(error_items),
                  "warnings": len(warning_items), "missing": len(missing_items),
                  "unapproved": len(unapproved_items),
                  "auto_approved": auto_learn.AUTO_APPROVE}
        _write_status(started_at, root, counts, new_items, updated_items,
                      skipped_items, error_items, warning_items, missing_items,
                      unapproved_items)


def _write_status(started_at, root, counts, new_items, updated_items,
                  skipped_items, error_items, warning_items, missing_items,
                  unapproved_items):
    """Ghi tóm tắt lượt quét — dùng CHUNG khoá `drive_sync_status` với bộ quét
    Drive cũ để thẻ trạng thái trên web không phải đổi hợp đồng dữ liệu; thêm
    `source: "local"` và `root` để giao diện hiển thị đúng chữ."""
    from app import settings
    cap = auto_learn.MAX_STATUS_ITEMS
    summary = {
        "source": "local",
        "root": str(root),
        "folder_id": None,
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "finished": True,
        "counts": counts,
        "new_items": new_items[-cap:],
        "updated_items": updated_items[-cap:],
        "skipped_items": skipped_items[-cap:],
        "error_items": error_items[-cap:],
        "warning_items": warning_items[-cap:],
        "missing_items": missing_items[-cap:],
        "unapproved_items": unapproved_items[-cap:],
    }
    try:
        settings.set_system("drive_sync_status", json.dumps(summary, ensure_ascii=False))
    except Exception as e:  # noqa: BLE001
        print(f"[CẢNH BÁO] Không ghi được trạng thái quét vào CSDL: {e}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _cli_migrate(argv):
    thu = "--dry-run" in argv
    root = library_root()

    if "--nguoc" in argv:
        n = revert_drive_keys(dry_run=thu)
        print(f"   {n} tài liệu {'sẽ được' if thu else 'đã'} trả lại danh tính Drive.")
        if not thu and n:
            print("   Nhớ khai lại DRIVE_FOLDER_ID trong .env rồi bật lại lịch học Drive.")
        return 0

    # Không cho chuyển đổi khi Drive còn đang bật: bộ quét Drive chạy xen giữa
    # sẽ không nhận ra tài liệu vừa đổi danh tính và học lại chúng lần nữa.
    if auto_learn.FOLDER_ID and "--toi-biet-rui-ro" not in argv:
        print("[DỪNG] .env vẫn còn DRIVE_FOLDER_ID — bộ quét Drive có thể đang chạy.")
        print("       Làm trước:")
        print("         1. Xoá dòng DRIVE_FOLDER_ID trong hds-ai/.env")
        print("         2. sudo bash deploy/auto-learn.sh --remove-timer")
        print("       Rồi chạy lại lệnh này. (Cố tình giữ Drive: thêm --toi-biet-rui-ro)")
        return 1

    print(f">> Gắn lại danh tính cho tài liệu đã học, theo kho: {root}")
    res = migrate_drive_keys(root, dry_run=thu)
    if thu:
        print(f"   {res['total']} tài liệu sẽ được gắn lại danh tính local.")
    else:
        print(f"   {res['updated']}/{res['total']} tài liệu đã gắn lại danh tính local.")
    if res["outside"]:
        print(f"   {res['outside']} tài liệu có tệp nằm NGOÀI kho — giữ nguyên, "
              "bộ quét sẽ không đụng tới.")
    blocked = res["blocked"]
    if blocked:
        print(f"\n[DỪNG] {len(blocked)} tài liệu KHÔNG gắn lại được vì danh tính "
              "đã bị bản ghi khác chiếm — kho đang có bản TRÙNG:")
        for doc_id, key in blocked[:10]:
            print(f"   · #{doc_id} → {key}")
        print("   Xử lý các bản trùng này trước khi bật lịch quét "
              "(xem deploy/CHUYEN_VE_LOCAL.md).")
        return 1
    if not thu:
        print("   Bước tiếp: python -m app.local_learn --dry-run")
    return 0


if __name__ == "__main__":
    if "--chuyen-doi" in sys.argv:
        sys.exit(_cli_migrate(sys.argv))
    run(dry_run="--dry-run" in sys.argv)
