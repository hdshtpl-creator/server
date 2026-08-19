"""
auto_learn.py — Bot TỰ HỌC tài liệu từ Google Drive theo CẤU TRÚC THƯ MỤC.

Khác với drive_sync + classify (gộp phẳng rồi nhờ AI đoán nhãn + người duyệt tay),
module này lấy chính THƯ MỤC trên Drive làm nhãn — không cần AI đoán. File mới mặc
định vẫn chờ người duyệt chất lượng trích xuất trước khi được dùng để trả lời.
Mỗi lần chạy chỉ xử lý file MỚI hoặc file ĐÃ SỬA (checksum; Google-native dùng modifiedTime).

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
from app.ingest import (ExtractionError, MAX_SOURCE_BYTES, SUPPORTED_EXTENSIONS,
                        apply_context_headers, client_display_name,
                        extract_text_with_metadata, safe_path_component,
                        split_document_with_metadata)
from app.models import embed, summarize

load_dotenv()

MAX_STATUS_ITEMS = 30  # giới hạn số dòng chi tiết lưu vào trạng thái để không phình CSDL

FOLDER_ID = os.getenv("DRIVE_FOLDER_ID", "")
SA_FILE = os.getenv("DRIVE_SA_FILE", "credentials/service-account.json")
DEST = Path(os.getenv("DATA_RAW", "./data/raw"))


def _env_bool(value, default=False):
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def auto_approve_from_env(env=None):
    """Mặc định an toàn là chờ duyệt; vẫn hiểu biến AUTO_LEARN_REVIEW cũ."""
    env = os.environ if env is None else env
    explicit = env.get("AUTO_LEARN_AUTO_APPROVE")
    if explicit is not None:
        return _env_bool(explicit, default=False)
    legacy_review = env.get("AUTO_LEARN_REVIEW")
    if legacy_review is not None:
        return not _env_bool(legacy_review, default=True)
    return False


# Biến mới diễn đạt trực tiếp. Tương thích cũ: AUTO_LEARN_REVIEW=0 vẫn tự duyệt,
# AUTO_LEARN_REVIEW=1 vẫn đưa vào hàng chờ. Khi không đặt biến nào, luôn chờ duyệt.
AUTO_APPROVE = auto_approve_from_env()
try:
    MAX_DOWNLOAD_BYTES = int(os.getenv("DRIVE_MAX_DOWNLOAD_BYTES", str(MAX_SOURCE_BYTES)))
    if MAX_DOWNLOAD_BYTES <= 0:
        raise ValueError
except (TypeError, ValueError):
    MAX_DOWNLOAD_BYTES = MAX_SOURCE_BYTES

EXPORT_MAP = {
    "application/vnd.google-apps.document":
        ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"),
    "application/vnd.google-apps.spreadsheet":
        ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"),
}
ALLOWED = set(SUPPORTED_EXTENSIONS)


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


def _matter_code_candidates(segment: str) -> list[str]:
    """Các mã vụ việc KHẢ DĨ trong tên một thư mục dự án, xếp theo độ ưu tiên.

    HDS đặt tên dự án theo quy ước số giống mã khách — '1572. Thành lập mới…',
    thậm chí kèm ngày phía trước: '160426. 1593. Thành lập mới…'. Kiểu ngoặc
    vuông '[M-2026-001] Tên' vẫn được nhận như cũ.

    Chỉ lấy các CỤM SỐ NỐI TIẾP NHAU Ở ĐẦU TÊN (không quét số trong thân tên,
    tránh vớ nhầm năm/tỷ lệ), và cụm đứng SÁT TÊN xếp trước — trong
    '160426. 1593. Thành lập' thì 1593 là mã, 160426 là ngày. An toàn vì nơi
    gọi chỉ gắn khi hệ thống THẬT SỰ có vụ việc mang mã đó của đúng khách này.
    """
    out: list[str] = []
    m = RE_CODE.match(segment or "")
    if m:
        out.append(m.group(1).strip().upper())
    numbers: list[str] = []
    rest = (segment or "").strip()
    while True:
        m = re.match(r"^(\d{3,})\s*[.)\-–]\s*", rest)
        if not m:
            break
        numbers.append(m.group(1))
        rest = rest[m.end():]
    out.extend(reversed(numbers))
    return out


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
                fields="nextPageToken, files(id,name,mimeType,md5Checksum,modifiedTime,size)",
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


def drive_fingerprint(file_info):
    """Dấu vết ổn định cả cho file Google-native (vốn không có md5Checksum)."""
    if file_info.get("md5Checksum"):
        # Giữ đúng định dạng md5 cũ để file nhị phân đã học không bị nạp lại hàng loạt.
        return file_info["md5Checksum"]
    if file_info.get("modifiedTime"):
        return f"gdrive-modified:{file_info['modifiedTime']}"
    return None


def resolve_labels(parts, create_missing_client=True):
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
                if not row and create_missing_client:
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
            action = ("chưa có trong hệ thống (dry-run không tạo dữ liệu)"
                      if not create_missing_client else "không tạo được bản ghi khách")
            return None, f"{action} cho '{folder}'"
        client_id, dept_id = row

        # Loại giấy tờ: quét các thư mục con, lấy khớp SÂU NHẤT (cụ thể nhất)
        doc_type = "ho_so_kh"
        for seg in parts[2:]:
            key = _norm(seg)
            if key in subs:
                doc_type = subs[key]
            elif key in cats:
                doc_type = cats[key]["doc_type"]

        # Vụ việc: '[MÃ] Tên' hoặc quy ước số '1572. Tên' / '160426. 1593. Tên'
        # → tự gắn matter_id. Chỉ gắn khi mã khớp vụ việc CÓ THẬT của đúng
        # khách này, nên tên thư mục không theo quy ước cũng không gắn nhầm.
        matter_id = None
        for seg in parts[2:]:
            candidates = _matter_code_candidates(seg)
            if not candidates:
                continue
            with db.session(role="internal", admin=True) as conn:
                with conn.cursor() as cur:
                    cur.execute("""SELECT id FROM matters
                                    WHERE upper(code)=ANY(%s) AND client_id=%s
                                    ORDER BY array_position(%s::text[], upper(code))
                                    LIMIT 1""",
                                (candidates, client_id, candidates))
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
        labels = {"doc_type": hit.get("doc_type", "other"),
                  "access_level": hit.get("access_level", "internal"),
                  "client_id": None, "department_id": None, "matter_id": None}
        if labels["doc_type"] == "ho_so_ns":
            # Thư mục con dưới "8. HỒ SƠ NHÂN SỰ" là TÊN NGƯỜI ("Ngân", "Mai").
            # Tên file lại chung chung ("Sơ yếu lý lịch.pdf") nên ba nhân sự là
            # ba tài liệu trùng tên — nguồn trích dẫn không biết của ai, và
            # dòng danh tính nhúng vào embedding cũng không mang tên người.
            # Giữ lại thư mục con (đoạn sâu nhất KHÔNG phải nhãn) để learn_one
            # ghép vào tiêu đề: "Ngân — Sơ yếu lý lịch".
            for seg in parts[1:]:
                key = _norm(seg)
                if key not in cats and key not in subs:
                    labels["title_context"] = seg.strip()
        return labels, None

    return None, (f"thư mục '{parts[0]}' chưa có trong bản đồ nhãn "
                  f"(thêm ở web: Cài đặt AI → Bản đồ thư mục Drive)")


def existing(drive_id):
    """(doc_id, checksum, doc_type, access_level, client_id, department_id,
    matter_id, approved, label_verified, title) của tài liệu đã học từ file
    Drive này, hoặc None. Cột mới nằm CUỐI để chỗ khác dùng row[0..6] không
    xê dịch."""
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT id, checksum, doc_type, access_level,
                                  client_id, department_id, matter_id,
                                  approved, label_verified, title
                             FROM documents WHERE drive_file_id=%s""", (drive_id,))
            return cur.fetchone()


def relabel(doc_id, labels, title=None):
    """Cập nhật NHÃN cho tài liệu mà không nạp lại nội dung (file không đổi, chỉ
    đổi khách/loại). Trigger sync_chunk_labels tự lan nhãn xuống các chunk.

    ``title``: tiêu đề hiển thị mới (vd hồ sơ nhân sự học trước khi tiêu đề
    mang tên người). Chỉ đổi phần hiển thị/nguồn trích dẫn — vector đã lưu giữ
    nguyên, muốn danh tính vào cả embedding thì học lại file."""
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""UPDATE documents SET doc_type=%s, access_level=%s, client_id=%s,
                           department_id=%s, matter_id=%s,
                           title=coalesce(%s, title), updated_at=now() WHERE id=%s""",
                        (labels["doc_type"], labels["access_level"], labels["client_id"],
                         labels["department_id"], labels.get("matter_id"), title, doc_id))
        db.audit(conn, None, "auto_relabel", "documents", doc_id,
                 {"labels": labels, **({"title": title} if title else {})})


def download(service, f, parts):
    from googleapiclient.http import MediaIoBaseDownload
    name, mime = f["name"], f["mimeType"]
    try:
        remote_size = int(f.get("size") or 0)
    except (TypeError, ValueError):
        remote_size = 0
    if remote_size > MAX_DOWNLOAD_BYTES:
        raise ExtractionError(
            "drive_file_too_large", f"File Drive lớn hơn giới hạn {MAX_DOWNLOAD_BYTES:,} byte.",
            "Tách file hoặc tăng DRIVE_MAX_DOWNLOAD_BYTES có kiểm soát.")
    if mime in EXPORT_MAP:
        emime, ext = EXPORT_MAP[mime]
        if not name.lower().endswith(ext):
            name += ext
        req = service.files().export_media(fileId=f["id"], mimeType=emime)
    else:
        if Path(name).suffix.lower() not in ALLOWED:
            return None
        req = service.files().get_media(fileId=f["id"])
    safe_parts = [safe_path_component(part) for part in parts]
    out_dir = DEST.joinpath(*safe_parts) if safe_parts else DEST
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / safe_path_component(name)
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, req)
    done = False
    while not done:
        _, done = dl.next_chunk()
        if buf.tell() > MAX_DOWNLOAD_BYTES:
            raise ExtractionError(
                "drive_file_too_large", f"File tải về vượt giới hạn {MAX_DOWNLOAD_BYTES:,} byte.",
                "Tách file hoặc tăng DRIVE_MAX_DOWNLOAD_BYTES có kiểm soát.")
    out.write_bytes(buf.getvalue())
    return out


def compose_title(stem: str, title_context=None) -> str:
    """Tiêu đề hiển thị: 'Ngân — Sơ yếu lý lịch' khi biết thư mục con tên người.

    Không ghép trùng: file người dùng đã tự đặt 'Ngân. KPI quý.xlsx' thì thôi.
    """
    ctx = (title_context or "").strip()
    if not ctx or _norm(ctx) in _norm(stem):
        return stem
    return f"{ctx} — {stem}"


def learn_one(path, labels, drive_id, drive_md5, replace_id=None, diagnostics=None,
              prev_approved=False):
    """Học một file; ``diagnostics`` nhận method/warnings/lỗi mà không phá API bool cũ.

    ``prev_approved``: bản cũ của CHÍNH file này đã được duyệt và đang phục vụ
    trả lời. Truyền vào để bản thay thế kế thừa trạng thái duyệt (xem chú thích
    tại chỗ tính ``should_approve``)."""
    diagnostics = diagnostics if diagnostics is not None else {}
    try:
        extraction = extract_text_with_metadata(path)
    except ExtractionError as exc:
        diagnostics["error"] = exc.as_dict()
        print(f"     [BỎ QUA] [{exc.code}] {exc}")
        return False
    text = extraction.text
    diagnostics.update({
        "method": extraction.method,
        "status": extraction.status,
        "warnings": extraction.warnings,
        "metadata": extraction.metadata,
    })
    print(f"     Trích xuất bằng {extraction.method}; {len(text):,} ký tự.")
    for warning in extraction.warnings:
        print(f"     [CẢNH BÁO] {warning}")
    pieces = split_document_with_metadata(extraction, labels["doc_type"])
    if not pieces:
        error = ExtractionError("no_chunks", "Không chia được nội dung thành đoạn.",
                                "Kiểm tra nội dung trích xuất trước khi học lại.")
        diagnostics["error"] = error.as_dict()
        print(f"     [BỎ QUA] [{error.code}] {error}")
        return False
    # Danh tính (tên tài liệu + loại + khách sở hữu) nhúng thẳng vào nội dung
    # được embedding — xem chú thích ở ingest.context_header. Tiêu đề mang cả
    # thư mục con tên người ("Ngân — Sơ yếu lý lịch") để ba hồ sơ trùng tên
    # file phân biệt được ở nguồn trích dẫn LẪN trong vector.
    title = compose_title(path.stem, labels.get("title_context"))
    pieces = apply_context_headers(pieces, title, labels["doc_type"],
                                   client_display_name(labels.get("client_id")))
    checksum = drive_md5 or hashlib.md5(text.encode()).hexdigest()
    # Bản cũ ĐÃ DUYỆT thì bản thay thế kế thừa trạng thái duyệt — miễn là lần
    # trích xuất này sạch. Trước đây sửa một file trên Drive là bản đã duyệt bị
    # XÓA và bản mới rơi về hàng chờ (khi chưa bật tự duyệt): tài liệu đang
    # phục vụ trả lời lặng lẽ biến mất, không ai được báo. Đúng ca 19/08/2026 —
    # "Sơ yếu lý lịch.pdf" của Ngân đang trả lời được, file bị đụng trên Drive,
    # bot chỉ còn tìm thấy sơ yếu của người khác với 37% liên quan.
    # Bản mới có CẢNH BÁO trích xuất thì vẫn chờ duyệt như cũ (nội dung nghi
    # ngờ không được tự thay nội dung đã duyệt), nhưng caller sẽ báo to việc
    # "tài liệu đang dùng bị gỡ" thay vì im lặng.
    should_approve = (AUTO_APPROVE or prev_approved) and extraction.status == "ok"
    diagnostics["approved"] = should_approve
    diagnostics["was_live"] = bool(prev_approved)
    vecs = embed([piece.content for piece in pieces])
    summary = summarize(text, title)
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            source_version = 1
            if replace_id:                       # file đã đổi → xoá bản cũ (chunks tự xoá theo)
                cur.execute("SELECT coalesce(source_version,1)+1 FROM documents WHERE id=%s",
                            (replace_id,))
                version_row = cur.fetchone()
                source_version = version_row[0] if version_row else 1
                cur.execute("DELETE FROM documents WHERE id=%s", (replace_id,))
            cur.execute("""INSERT INTO documents
                (title, source_path, drive_file_id, checksum, doc_type, access_level,
                 client_id, department_id, matter_id, approved, label_verified, source_kind, summary,
                 extraction_status,extraction_error,source_version)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'drive',%s,%s,%s,%s) RETURNING id""",
                (title, str(path), drive_id, checksum,
                 labels["doc_type"], labels["access_level"],
                 labels["client_id"], labels["department_id"], labels.get("matter_id"),
                 should_approve, should_approve, summary,
                 "warning" if extraction.warnings else "ready",
                 json.dumps(extraction.warnings, ensure_ascii=False) if extraction.warnings else None,
                 source_version))
            doc_id = cur.fetchone()[0]
            for idx, (piece, vec) in enumerate(zip(pieces, vecs)):
                cur.execute("""INSERT INTO chunks
                    (document_id, chunk_index, content, page_number, section_title, source_locator,
                     access_level, client_id, department_id, doc_type, embedding)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (doc_id, idx, piece.content, piece.page_number, piece.section_title,
                     piece.source_locator, labels["access_level"], labels["client_id"],
                     labels["department_id"], labels["doc_type"], json.dumps(vec)))
        db.audit(conn, None, "auto_learn", "documents", doc_id,
                 {"file": path.name, "chunks": len(pieces), "labels": labels,
                  "extraction": {"method": extraction.method,
                                 "status": extraction.status,
                                 "warnings": extraction.warnings,
                                 "metadata": extraction.metadata}})
    state = "đã học" if should_approve else "vào hàng chờ duyệt"
    print(f"     [OK] document_id={doc_id}, {len(pieces)} đoạn — {state}.")
    return True


def _record_failure(drive_file_id, name, location, error):
    """Ghi/cập nhật một file KHÔNG HỌC ĐƯỢC để dashboard thấy được lâu dài.

    Lần quét sau, nếu file vẫn hỏng thì chỉ tăng `attempts` chứ không tạo dòng
    mới — admin cần biết "hỏng từ bao giờ, đã thử mấy lần", không cần một trang
    dài toàn dòng trùng nhau.
    """
    try:
        with db.session(role="internal", admin=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO ingest_failures
                         (drive_file_id,file_name,location,error_code,error_message,hint)
                       VALUES (%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (drive_file_id) DO UPDATE SET
                         file_name=EXCLUDED.file_name,
                         location=EXCLUDED.location,
                         error_code=EXCLUDED.error_code,
                         error_message=EXCLUDED.error_message,
                         hint=EXCLUDED.hint,
                         attempts=ingest_failures.attempts+1,
                         last_seen_at=now(),
                         resolved_at=NULL""",
                    (drive_file_id, name, location, error.get("code") or "unknown",
                     error.get("message"), error.get("hint")))
    except Exception as exc:
        # Không để việc ghi báo cáo làm hỏng cả lần quét.
        print(f"     [CẢNH BÁO] không ghi được nhật ký lỗi học: {exc}")


def _clear_failure(drive_file_id):
    """Đánh dấu đã xử lý khi file học được — thẻ trên dashboard tự biến mất."""
    if not drive_file_id:
        return
    try:
        with db.session(role="internal", admin=True) as conn:
            with conn.cursor() as cur:
                cur.execute("""UPDATE ingest_failures SET resolved_at=now()
                                WHERE drive_file_id=%s AND resolved_at IS NULL""",
                            (drive_file_id,))
    except Exception:
        pass


def _write_status(started_at, folder_id, counts, new_items, updated_items,
                  skipped_items, error_items, warning_items=None, finished=True):
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
        "warning_items": (warning_items or [])[-MAX_STATUS_ITEMS:],
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
    review_mode = "TỰ DUYỆT" if AUTO_APPROVE else "CHỜ NGƯỜI DUYỆT (mặc định an toàn)"
    print(f">> Chế độ nhập: {review_mode}")
    print(f">> Duyệt cây thư mục Drive {FOLDER_ID}...")
    items = walk(service, FOLDER_ID)
    print(f"   {len(items)} file.\n")

    n_new = n_upd = n_skip = n_unmapped = n_badext = 0
    new_items, updated_items, skipped_items, error_items, warning_items = [], [], [], [], []

    for f, parts in items:
        ext = Path(f["name"]).suffix.lower()
        loc = "/".join(parts) or "(gốc)"

        if f["mimeType"] not in EXPORT_MAP and ext not in ALLOWED:
            n_badext += 1
            reason = (f"định dạng '{ext or '(không có đuôi)'}' chưa hỗ trợ; "
                      "dùng PDF, DOCX, DOC, TXT, MD, XLSX hoặc CSV")
            print(f"   [BỎ QUA] {f['name']}  ← {loc}: {reason}")
            skipped_items.append({"name": f["name"], "location": loc,
                                  "reason": reason, "code": "unsupported_format"})
            continue

        labels, reason = resolve_labels(parts, create_missing_client=not dry_run)
        if labels is None:
            print(f"   [BỎ QUA] {f['name']}  ← {loc}: {reason}")
            n_unmapped += 1
            # Chỉ dòng "không xác định được nhãn" mới đáng để admin xem trên
            # dashboard — sai định dạng tệp thì không cần hành động gì.
            skipped_items.append({"name": f["name"], "location": loc, "reason": reason})
            continue

        row = existing(f["id"])
        remote_fingerprint = drive_fingerprint(f)
        if row and remote_fingerprint and row[1] == remote_fingerprint:
            # Nội dung không đổi. Nhưng nếu NHÃN đã khác (vd trước đây chưa gắn
            # được khách, giờ gắn được), thì cập nhật nhãn — không nạp lại nội dung.
            cur_labels = (row[2], row[3], row[4], row[5], row[6])
            new_labels = (labels["doc_type"], labels["access_level"], labels["client_id"],
                          labels["department_id"], labels.get("matter_id"))
            # Tiêu đề kỳ vọng có thể đã đổi dù nội dung y nguyên — hồ sơ nhân
            # sự học từ trước khi tiêu đề mang tên người ("Sơ yếu lý lịch" →
            # "Ngân — Sơ yếu lý lịch"). Cập nhật để nguồn trích dẫn phân biệt
            # được ba hồ sơ trùng tên file của ba người.
            wanted_title = compose_title(Path(f["name"]).stem,
                                         labels.get("title_context"))
            new_title = wanted_title if row[9] != wanted_title else None
            if cur_labels != new_labels or new_title:
                if not dry_run:
                    relabel(row[0], labels, title=new_title)
                why = ("cập nhật nhãn (khách/loại)" if cur_labels != new_labels
                       else f"đổi tiêu đề → '{new_title}'")
                print(f"   [GẮN LẠI] {f['name']}  ← {loc}: {why}")
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
                skipped_items.append({"name": f["name"], "location": loc,
                                      "reason": "định dạng chưa hỗ trợ",
                                      "code": "unsupported_format"})
                continue
            extraction_info = {}
            was_live = bool(row and row[7] and row[8])
            if learn_one(p, labels, f["id"], remote_fingerprint,
                         replace_id=row[0] if row else None, diagnostics=extraction_info,
                         prev_approved=was_live):
                (updated_items if row else new_items).append(item_info)
                if extraction_info.get("warnings"):
                    requires_review = not extraction_info.get("approved", False)
                    if was_live and requires_review:
                        # Bản đã duyệt vừa bị thay bằng bản chờ duyệt — bot MẤT
                        # tài liệu này cho tới khi admin duyệt lại. Phải nói to,
                        # đừng để "tự nhiên mất" thêm lần nào nữa.
                        print(f"     [GỠ KHỎI KHO] {f['name']}: bản đã duyệt bị thay "
                              "bằng bản chờ duyệt (trích xuất có cảnh báo). Bot sẽ "
                              "không dùng tài liệu này cho tới khi duyệt lại — "
                              "vào Quản trị → Duyệt nhãn tài liệu.")
                    warning_items.append({
                        "name": f["name"], "location": loc,
                        "method": extraction_info.get("method"),
                        "warnings": extraction_info["warnings"],
                        "requires_review": requires_review,
                        "was_live": was_live,
                    })
                # Học được rồi thì gỡ khỏi danh sách lỗi cũ (nếu có).
                _clear_failure(f.get("id"))
                if row:
                    n_upd += 1
                else:
                    n_new += 1
            else:
                # learn_one bỏ qua vì không đọc được nội dung. Trước đây file này
                # biến mất không dấu vết — admin tưởng đã học. Giờ đưa vào danh
                # sách lỗi để thấy trên dashboard và biết đường xử lý.
                error = extraction_info.get("error") or {
                    "code": "extraction_failed", "message": "Không đọc được nội dung.",
                    "hint": "Kiểm tra định dạng file rồi học lại.",
                }
                error_items.append({
                    "name": f["name"], "location": loc,
                    "code": error.get("code"), "error": error.get("message"),
                    "hint": error.get("hint"), "preserved_existing": bool(row),
                })
                _record_failure(f.get("id"), f["name"], loc, error)
        except Exception as e:
            print(f"     [LỖI] {f['name']}: {e}")
            if isinstance(e, ExtractionError):
                detail = e.as_dict()
                error_items.append({"name": f["name"], "location": loc,
                                    "code": detail["code"], "error": detail["message"],
                                    "hint": detail["hint"], "preserved_existing": bool(row)})
            else:
                error_items.append({"name": f["name"], "location": loc,
                                    "code": "unexpected_error", "error": str(e)[:500],
                                    "hint": "Xem journal của hds-ai-learn để biết chi tiết.",
                                    "preserved_existing": bool(row)})

    n_ig = n_unmapped + n_badext
    print(f"\n{n_new} mới | {n_upd} cập nhật | {n_skip} không đổi | "
          f"{n_ig} bỏ qua | {len(error_items)} lỗi | {len(warning_items)} cảnh báo")
    if not dry_run and (n_new or n_upd):
        if AUTO_APPROVE:
            print("Đã học xong — file sạch dùng ngay; file có cảnh báo vẫn chờ duyệt. "
                  "Kiểm tra: /admin → Kho tài liệu đã học.")
        else:
            print("Đang chờ duyệt — mở /admin → Duyệt nhãn tài liệu.")

    if not dry_run:
        counts = {"scanned": len(items), "new": n_new, "updated": n_upd,
                  "unchanged": n_skip, "unmapped": n_unmapped, "bad_format": n_badext,
                  "errors": len(error_items), "warnings": len(warning_items),
                  "auto_approved": AUTO_APPROVE}
        _write_status(started_at, FOLDER_ID, counts, new_items, updated_items,
                     skipped_items, error_items, warning_items)


if __name__ == "__main__":
    run(dry_run="--dry-run" in sys.argv)
