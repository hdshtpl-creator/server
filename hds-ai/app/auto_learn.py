"""
auto_learn.py — Bot TỰ HỌC tài liệu từ Google Drive theo CẤU TRÚC THƯ MỤC.

Khác với drive_sync + classify (gộp phẳng rồi nhờ AI đoán nhãn + người duyệt tay),
module này lấy chính THƯ MỤC trên Drive làm nhãn — không cần đoán, không cần duyệt.
Mỗi lần chạy chỉ xử lý file MỚI hoặc file ĐÃ SỬA (so bằng checksum).

────────────────────────────────────────────────────────────────────────
CÂY THƯ MỤC (xem đầy đủ ở deploy/CAU_TRUC_DRIVE.md):

  HDS. CƠ SỞ DỮ LIỆU/            ← DRIVE_FOLDER_ID trỏ vào đây
  ├── 1. VĂN BẢN PHÁP LUẬT/      → law      (công khai)
  ├── 2. BẢN ÁN - ÁN LỆ/         → ban_an / an_le
  ├── 3. HỢP ĐỒNG MẪU/           → mau_hd
  ├── 4. QUAN ĐIỂM PHÁP LÝ/      → advisory
  ├── ...
  └── 9. HỒ SƠ KHÁCH HÀNG/
      └── [SUNGROUP] Tập đoàn SunGroup/     → access_level=client
          ├── 1. Thông tin khách hàng/
          └── 2. Dự án - Vụ việc/
              └── [M-2026-001] Tái cấu trúc vốn/   → tự gắn matter_id

Tên thư mục được CHUẨN HOÁ trước khi so khớp (bỏ số thứ tự đầu, bỏ dấu, hạ chữ
thường) nên "1. VĂN BẢN PHÁP LUẬT" = "Văn bản pháp luật" = "van ban phap luat".
Đánh số lại thư mục không làm hỏng gì.

Bản đồ thư mục → nhãn nằm trong CÀI ĐẶT (bảng app_settings, khoá `drive_map`),
admin sửa trực tiếp trên web mà không cần sửa code.

Hồ sơ khách: tên thư mục nên có mã trong ngoặc vuông — `[MÃ_KHÁCH] Tên khách` —
và mã phải khớp cột `code` bảng clients. Không xác định được khách thì file bị
BỎ QUA (thà thiếu còn hơn lộ dữ liệu chéo giữa các khách).
────────────────────────────────────────────────────────────────────────

Chạy tay:      python -m app.auto_learn            # học file mới/sửa
               python -m app.auto_learn --dry-run  # chỉ liệt kê, không ghi
Chạy định kỳ:  xem deploy/auto-learn.sh + hướng dẫn cron trong deploy/README.md
"""
import hashlib
import io
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from app import db, settings
from app.ingest import extract_text, split_document
from app.models import embed, summarize

load_dotenv()

MAX_STATUS_ITEMS = 30  # giới hạn số dòng chi tiết lưu vào trạng thái để không phình CSDL

FOLDER_ID = os.getenv("DRIVE_FOLDER_ID", "")
SA_FILE = os.getenv("DRIVE_SA_FILE", "credentials/service-account.json")
DEST = Path(os.getenv("DATA_RAW", "./data/raw"))
# Mặc định tự duyệt luôn (thư mục CHÍNH LÀ nhãn). Đặt AUTO_LEARN_REVIEW=1 nếu
# muốn cẩn trọng: file vào hàng chờ /review thay vì học ngay.
AUTO_APPROVE = os.getenv("AUTO_LEARN_REVIEW", "0") not in ("1", "true", "True")

EXPORT_MAP = {
    "application/vnd.google-apps.document":
        ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"),
    "application/vnd.google-apps.spreadsheet":
        ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"),
}
ALLOWED = {".pdf", ".docx", ".doc", ".txt", ".md"}


# Bắt mã trong ngoặc vuông ở đầu tên thư mục: "[SUNGROUP] Tập đoàn SunGroup"
RE_CODE = re.compile(r"^\s*\[([A-Za-z0-9._\-]+)\]")
# Bỏ số thứ tự đầu tên: "1. ", "2.3 ", "09) ", "1 - "
RE_ORDINAL = re.compile(r"^\s*\d+(\.\d+)*\s*[.)\-–]?\s*")
# Mã khách theo kiểu số đầu tên: "1729. Công ty..." → 1729 (≥3 chữ số để không
# nhầm với số thứ tự mục "1.", "9." của cây thư mục chung).
RE_CLIENT_NUM = re.compile(r"^\s*(\d{3,})\s*[.)\-–]?\s+(.*\S)")


def _norm(name: str) -> str:
    """Chuẩn hoá tên thư mục để so khớp bản đồ nhãn.

    Bỏ số thứ tự đầu, bỏ dấu tiếng Việt, hạ chữ thường, gộp khoảng trắng.
    Nhờ vậy "1. VĂN BẢN PHÁP LUẬT", "Văn bản pháp luật", "van ban phap luat"
    đều khớp cùng một khoá — bạn đánh số lại thư mục cũng không hỏng.
    """
    s = (name or "").strip()
    s = RE_ORDINAL.sub("", s)
    s = RE_CODE.sub("", s).strip()          # bỏ phần [MÃ] nếu có
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")   # bỏ dấu
    s = s.replace("đ", "d").replace("Đ", "d")
    s = re.sub(r"[\s_]+", " ", s).strip().lower()
    return s


def _extract_code(name: str) -> str | None:
    """Lấy mã trong [ ] ở đầu tên thư mục, vd '[SUNGROUP] Tập đoàn SunGroup' → SUNGROUP."""
    m = RE_CODE.match(name or "")
    return m.group(1).strip() if m else None


def _client_code_and_name(folder: str):
    """Tách (mã khách, tên khách) từ tên thư mục khách. Hỗ trợ hai kiểu:

        '[SUNGROUP] Tập đoàn SunGroup'   → ('SUNGROUP', 'Tập đoàn SunGroup')
        '1729. Công ty Cổ phần Đại Hữu'  → ('1729', 'Công ty Cổ phần Đại Hữu')

    Trả (None, None) nếu không tách được mã — khi đó bỏ qua để tránh gắn nhầm
    hồ sơ sang khách khác."""
    folder = (folder or "").strip()
    m = RE_CODE.match(folder)
    if m:
        name = RE_CODE.sub("", folder).strip()
        return m.group(1).strip(), (name or folder)
    m = RE_CLIENT_NUM.match(folder)
    if m:
        return m.group(1), m.group(2).strip()
    return None, None


def _load_map():
    """Bản đồ thư mục → nhãn, lấy từ cài đặt (admin sửa trên web)."""
    raw = settings.get_json("drive_map") or {}
    cats = {_norm(k): v for k, v in (raw.get("categories") or {}).items()}
    subs = {_norm(k): v for k, v in (raw.get("client_subcategories") or {}).items()}
    roots = {_norm(r) for r in (raw.get("client_roots") or ["ho so khach hang"])}
    return cats, subs, roots


def get_service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    if not Path(SA_FILE).exists():
        print(f"[LỖI] Không thấy khoá service account: {SA_FILE}")
        print("      Tạo theo hướng dẫn ở deploy/README.md rồi chia sẻ thư mục Drive cho email của nó.")
        sys.exit(1)
    creds = service_account.Credentials.from_service_account_file(
        SA_FILE, scopes=["https://www.googleapis.com/auth/drive.readonly"])
    return build("drive", "v3", credentials=creds)


def walk(service, root_id):
    """Duyệt cây Drive, trả về (file_dict, [tên các thư mục cha từ gốc])."""
    out, stack = [], [(root_id, [])]
    while stack:
        fid, parts = stack.pop()
        page = None
        while True:
            resp = service.files().list(
                q=f"'{fid}' in parents and trashed=false",
                fields="nextPageToken, files(id,name,mimeType,md5Checksum)",
                pageSize=200, pageToken=page).execute()
            for f in resp.get("files", []):
                if f["mimeType"] == "application/vnd.google-apps.folder":
                    stack.append((f["id"], parts + [f["name"]]))
                else:
                    out.append((f, parts))
            page = resp.get("nextPageToken")
            if not page:
                break
    return out


def resolve_labels(parts):
    """Từ đường dẫn thư mục → nhãn. Trả về dict nhãn, hoặc (None, lý do bỏ qua)."""
    if not parts:
        return None, "nằm ở thư mục gốc (không rõ loại)"

    cats, subs, roots = _load_map()
    top = _norm(parts[0])

    # ---- Nhánh hồ sơ khách hàng ----
    if top in roots:
        if len(parts) < 2:
            return None, "nằm ngay trong 'Hồ sơ khách hàng' — cần thêm thư mục của từng khách"

        # Mã + tên khách từ tên thư mục: '[MÃ] Tên' hoặc 'số. Tên' (số đầu = mã).
        folder = parts[1].strip()
        code, cname = _client_code_and_name(folder)
        if not code:
            return None, (f"chưa tách được mã khách từ thư mục '{folder}'. "
                          f"Đặt tên dạng '1729. Tên công ty' hoặc '[MÃ] Tên khách'")
        with db.session(role="internal", admin=True) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, department_id FROM clients WHERE upper(code)=upper(%s)", (code,))
                row = cur.fetchone()
                if not row:
                    # Chưa có trong hệ thống → tự tạo bản ghi khách từ thư mục.
                    # DO NOTHING để không ghi đè tên/phòng admin đã sửa tay.
                    cur.execute(
                        """INSERT INTO clients (name, code, note)
                           VALUES (%s, %s, 'Tự tạo từ thư mục Drive — gán phòng phụ trách nếu cần')
                           ON CONFLICT (code) DO NOTHING""",
                        (cname or code, code))
                    cur.execute("SELECT id, department_id FROM clients WHERE upper(code)=upper(%s)",
                                (code,))
                    row = cur.fetchone()
        if not row:
            return None, f"không tạo được bản ghi khách cho '{folder}'"
        client_id, dept_id = row

        # Loại giấy tờ: quét các thư mục con, lấy khớp SÂU NHẤT (cụ thể nhất)
        doc_type = "ho_so_kh"
        for seg in parts[2:]:
            key = _norm(seg)
            if key in subs:
                doc_type = subs[key]
            elif key in cats:
                doc_type = cats[key]["doc_type"]

        # Vụ việc: thư mục dạng [MÃ_VỤ_VIỆC] Tên → tự gắn matter_id
        matter_id = None
        for seg in parts[2:]:
            mcode = _extract_code(seg)
            if not mcode:
                continue
            with db.session(role="internal", admin=True) as conn:
                with conn.cursor() as cur:
                    cur.execute("""SELECT id FROM matters
                                    WHERE upper(code)=upper(%s) AND client_id=%s""",
                                (mcode, client_id))
                    mrow = cur.fetchone()
            if mrow:
                matter_id = mrow[0]
                break

        return {"doc_type": doc_type, "access_level": "client",
                "client_id": client_id, "department_id": dept_id,
                "matter_id": matter_id}, None

    # ---- Nhánh tài liệu chung: lấy khớp SÂU NHẤT trên đường dẫn ----
    hit = None
    for seg in parts:
        key = _norm(seg)
        if key in cats:
            hit = cats[key]
    if hit:
        return {"doc_type": hit.get("doc_type", "other"),
                "access_level": hit.get("access_level", "internal"),
                "client_id": None, "department_id": None, "matter_id": None}, None

    return None, (f"thư mục '{parts[0]}' chưa có trong bản đồ nhãn "
                  f"(thêm ở web: Cài đặt AI → Bản đồ thư mục Drive)")


def existing(drive_id):
    """(doc_id, checksum, doc_type, access_level, client_id, department_id, matter_id)
    của tài liệu đã học từ file Drive này, hoặc None."""
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT id, checksum, doc_type, access_level,
                                  client_id, department_id, matter_id
                             FROM documents WHERE drive_file_id=%s""", (drive_id,))
            return cur.fetchone()


def relabel(doc_id, labels):
    """Cập nhật NHÃN cho tài liệu mà không nạp lại nội dung (file không đổi, chỉ
    đổi khách/loại). Trigger sync_chunk_labels tự lan nhãn xuống các chunk."""
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""UPDATE documents SET doc_type=%s, access_level=%s, client_id=%s,
                           department_id=%s, matter_id=%s, updated_at=now() WHERE id=%s""",
                        (labels["doc_type"], labels["access_level"], labels["client_id"],
                         labels["department_id"], labels.get("matter_id"), doc_id))
        db.audit(conn, None, "auto_relabel", "documents", doc_id, {"labels": labels})


def download(service, f, parts):
    from googleapiclient.http import MediaIoBaseDownload
    name, mime = f["name"], f["mimeType"]
    if mime in EXPORT_MAP:
        emime, ext = EXPORT_MAP[mime]
        if not name.endswith(ext):
            name += ext
        req = service.files().export_media(fileId=f["id"], mimeType=emime)
    else:
        if Path(name).suffix.lower() not in ALLOWED:
            return None
        req = service.files().get_media(fileId=f["id"])
    out_dir = DEST.joinpath(*parts) if parts else DEST
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / name
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, req)
    done = False
    while not done:
        _, done = dl.next_chunk()
    out.write_bytes(buf.getvalue())
    return out


def learn_one(path, labels, drive_id, drive_md5, replace_id=None):
    text = extract_text(path)
    if not text.strip():
        print("     [BỎ QUA] không trích được nội dung.")
        return False
    pieces = split_document(text, labels["doc_type"])
    if not pieces:
        print("     [BỎ QUA] không chia được đoạn.")
        return False
    checksum = drive_md5 or hashlib.md5(text.encode()).hexdigest()
    vecs = embed(pieces)
    summary = summarize(text, path.stem)
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            if replace_id:                       # file đã đổi → xoá bản cũ (chunks tự xoá theo)
                cur.execute("DELETE FROM documents WHERE id=%s", (replace_id,))
            cur.execute("""INSERT INTO documents
                (title, source_path, drive_file_id, checksum, doc_type, access_level,
                 client_id, department_id, matter_id, approved, label_verified, source_kind, summary)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'drive',%s) RETURNING id""",
                (path.stem, str(path), drive_id, checksum,
                 labels["doc_type"], labels["access_level"],
                 labels["client_id"], labels["department_id"], labels.get("matter_id"),
                 AUTO_APPROVE, AUTO_APPROVE, summary))
            doc_id = cur.fetchone()[0]
            for idx, (piece, vec) in enumerate(zip(pieces, vecs)):
                cur.execute("""INSERT INTO chunks
                    (document_id, chunk_index, content, access_level, client_id, department_id, doc_type, embedding)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (doc_id, idx, piece, labels["access_level"],
                     labels["client_id"], labels["department_id"], labels["doc_type"],
                     json.dumps(vec)))
        db.audit(conn, None, "auto_learn", "documents", doc_id,
                 {"file": path.name, "chunks": len(pieces), "labels": labels})
    state = "đã học" if AUTO_APPROVE else "vào hàng chờ duyệt"
    print(f"     [OK] document_id={doc_id}, {len(pieces)} đoạn — {state}.")
    return True


def _write_status(started_at, folder_id, counts, new_items, updated_items,
                  skipped_items, error_items, finished=True):
    """Ghi tóm tắt lần quét gần nhất vào app_settings để dashboard đọc được.

    Đây chính là 'cơ chế nhận biết file đã học và file mới chưa học': admin
    không cần SSH vào máy chủ hay xem log, chỉ cần mở web là thấy lần quét gần
    nhất chạy khi nào, học được bao nhiêu, và — quan trọng nhất — file nào bị
    BỎ QUA kèm lý do cụ thể để sửa (đổi tên thư mục, tạo khách hàng, v.v.).
    """
    summary = {
        "folder_id": folder_id,
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat() if finished else None,
        "finished": finished,
        "counts": counts,
        "new_items": new_items[-MAX_STATUS_ITEMS:],
        "updated_items": updated_items[-MAX_STATUS_ITEMS:],
        "skipped_items": skipped_items[-MAX_STATUS_ITEMS:],
        "error_items": error_items[-MAX_STATUS_ITEMS:],
    }
    try:
        settings.set_system("drive_sync_status", json.dumps(summary, ensure_ascii=False))
    except Exception as e:
        print(f"[CẢNH BÁO] Không ghi được trạng thái đồng bộ vào CSDL: {e}")


def run(dry_run=False):
    if not FOLDER_ID:
        print("[LỖI] Chưa đặt DRIVE_FOLDER_ID trong .env")
        sys.exit(1)
    started_at = datetime.now(timezone.utc)
    service = get_service()
    print(f">> Duyệt cây thư mục Drive {FOLDER_ID}...")
    items = walk(service, FOLDER_ID)
    print(f"   {len(items)} file.\n")

    n_new = n_upd = n_skip = n_unmapped = n_badext = 0
    new_items, updated_items, skipped_items, error_items = [], [], [], []

    for f, parts in items:
        ext = Path(f["name"]).suffix.lower()
        loc = "/".join(parts) or "(gốc)"

        if f["mimeType"] not in EXPORT_MAP and ext not in ALLOWED:
            n_badext += 1
            continue

        labels, reason = resolve_labels(parts)
        if labels is None:
            print(f"   [BỎ QUA] {f['name']}  ← {loc}: {reason}")
            n_unmapped += 1
            # Chỉ dòng "không xác định được nhãn" mới đáng để admin xem trên
            # dashboard — sai định dạng tệp thì không cần hành động gì.
            skipped_items.append({"name": f["name"], "location": loc, "reason": reason})
            continue

        row = existing(f["id"])
        drive_md5 = f.get("md5Checksum")
        if row and drive_md5 and row[1] == drive_md5:
            # Nội dung không đổi. Nhưng nếu NHÃN đã khác (vd trước đây chưa gắn
            # được khách, giờ gắn được), thì cập nhật nhãn — không nạp lại nội dung.
            cur_labels = (row[2], row[3], row[4], row[5], row[6])
            new_labels = (labels["doc_type"], labels["access_level"], labels["client_id"],
                          labels["department_id"], labels.get("matter_id"))
            if cur_labels != new_labels:
                if not dry_run:
                    relabel(row[0], labels)
                print(f"   [GẮN LẠI] {f['name']}  ← {loc}: cập nhật nhãn (khách/loại)")
                updated_items.append({"name": f["name"], "location": loc,
                                      "doc_type": labels["doc_type"],
                                      "access_level": labels["access_level"]})
                n_upd += 1
            else:
                n_skip += 1
            continue

        tag = f"{labels['access_level']}/{labels['doc_type']}"
        if labels["client_id"]:
            tag += f"/client={labels['client_id']}"
        action = "CẬP NHẬT" if row else "MỚI"
        print(f"   [{action}] {f['name']}  ← {loc}  → {tag}")
        item_info = {"name": f["name"], "location": loc, "doc_type": labels["doc_type"],
                     "access_level": labels["access_level"]}
        if dry_run:
            (updated_items if row else new_items).append(item_info)
            if row:
                n_upd += 1
            else:
                n_new += 1
            continue

        try:
            p = download(service, f, parts)
            if not p:
                n_badext += 1
                continue
            if learn_one(p, labels, f["id"], drive_md5, replace_id=row[0] if row else None):
                (updated_items if row else new_items).append(item_info)
                if row:
                    n_upd += 1
                else:
                    n_new += 1
            else:
                # learn_one bỏ qua vì không đọc được nội dung. Trước đây file này
                # biến mất không dấu vết — admin tưởng đã học. Giờ đưa vào danh
                # sách lỗi để thấy trên dashboard và biết đường xử lý.
                error_items.append({
                    "name": f["name"], "location": loc,
                    "error": "không đọc được nội dung — nếu là PDF scan cần cài OCR "
                             "(tesseract-ocr-vie, poppler-utils) rồi học lại"})
        except Exception as e:
            print(f"     [LỖI] {f['name']}: {e}")
            error_items.append({"name": f["name"], "location": loc, "error": str(e)})

    n_ig = n_unmapped + n_badext
    print(f"\n{n_new} mới | {n_upd} cập nhật | {n_skip} không đổi | {n_ig} bỏ qua")
    if not dry_run and (n_new or n_upd):
        if AUTO_APPROVE:
            print("Đã học xong — bot dùng được ngay. Kiểm tra: /admin → Kho tài liệu đã học.")
        else:
            print("Đang chờ duyệt — mở /admin → Duyệt nhãn tài liệu.")

    if not dry_run:
        counts = {"scanned": len(items), "new": n_new, "updated": n_upd,
                  "unchanged": n_skip, "unmapped": n_unmapped, "bad_format": n_badext,
                  "errors": len(error_items)}
        _write_status(started_at, FOLDER_ID, counts, new_items, updated_items,
                     skipped_items, error_items)


if __name__ == "__main__":
    run(dry_run="--dry-run" in sys.argv)
