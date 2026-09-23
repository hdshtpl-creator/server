"""
drive_sync.py — Đồng bộ tài liệu từ Google Drive về máy chủ.
Chạy: python -m app.drive_sync [--dry-run]
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from app.ingest import (ExtractionError, MAX_SOURCE_BYTES, SUPPORTED_EXTENSIONS,
                        safe_path_component)

load_dotenv()

FOLDER_ID = os.getenv("DRIVE_FOLDER_ID", "")
SA_FILE = os.getenv("DRIVE_SA_FILE", "credentials/service-account.json")
DEST = Path(os.getenv("DATA_RAW", "./data/raw"))
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


def drive_fingerprint(file_info):
    """Google Docs/Sheets không có md5Checksum, nên dùng modifiedTime ổn định."""
    if file_info.get("md5Checksum"):
        return file_info["md5Checksum"]
    if file_info.get("modifiedTime"):
        return f"gdrive-modified:{file_info['modifiedTime']}"
    return None


def get_service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    if not Path(SA_FILE).exists():
        print(f"[LỖI] Không thấy khoá: {SA_FILE} (xem hướng dẫn tạo service account)")
        sys.exit(1)
    creds = service_account.Credentials.from_service_account_file(
        SA_FILE, scopes=["https://www.googleapis.com/auth/drive.readonly"])
    return build("drive", "v3", credentials=creds)


def list_files(service, folder_id):
    out, stack = [], [folder_id]
    while stack:
        fid = stack.pop()
        page = None
        while True:
            resp = service.files().list(
                q=f"'{fid}' in parents and trashed=false",
                fields="nextPageToken, files(id,name,mimeType,md5Checksum,modifiedTime,size)",
                pageSize=200, pageToken=page).execute()
            for f in resp.get("files", []):
                if f["mimeType"] == "application/vnd.google-apps.folder":
                    stack.append(f["id"])
                else:
                    out.append(f)
            page = resp.get("nextPageToken")
            if not page:
                break
    return out


def already_synced(drive_id, checksum):
    from app import db
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT checksum FROM documents WHERE drive_file_id=%s", (drive_id,))
            row = cur.fetchone()
    return bool(row) and checksum is not None and row[0] == checksum


def download(service, f, dest_dir):
    import io
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
    out = dest_dir / safe_path_component(name)
    out.parent.mkdir(parents=True, exist_ok=True)
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


def _record(f, path):
    from app import db
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO documents (title,source_path,drive_file_id,checksum,source_kind)
                VALUES (%s,%s,%s,%s,'drive')
                ON CONFLICT (drive_file_id) DO UPDATE
                  SET checksum=EXCLUDED.checksum, source_path=EXCLUDED.source_path, updated_at=now()""",
                (path.stem, str(path), f["id"], drive_fingerprint(f)))


def sync(dry_run=False):
    if not FOLDER_ID:
        print("[LỖI] Chưa đặt DRIVE_FOLDER_ID trong .env")
        sys.exit(1)
    service = get_service()
    print(f">> Liệt kê file trong Drive {FOLDER_ID}...")
    files = list_files(service, FOLDER_ID)
    print(f"   {len(files)} file.\n")
    DEST.mkdir(parents=True, exist_ok=True)
    n_new = n_skip = n_ig = 0
    for f in files:
        ext = Path(f["name"]).suffix.lower()
        if f["mimeType"] not in EXPORT_MAP and ext not in ALLOWED:
            n_ig += 1
            continue
        if already_synced(f["id"], drive_fingerprint(f)):
            n_skip += 1
            continue
        if dry_run:
            print(f"   [SẼ TẢI] {f['name']}")
            n_new += 1
            continue
        try:
            p = download(service, f, DEST)
            if p:
                print(f"   [TẢI VỀ] {p.name}")
                _record(f, p)
                n_new += 1
        except Exception as e:
            print(f"   [LỖI] {f['name']}: {e}")
    print(f"\n{n_new} mới/sửa | {n_skip} đã có bỏ qua | {n_ig} bỏ định dạng")
    if not dry_run and n_new:
        print("Bước tiếp: python -m app.ingest data/raw")


if __name__ == "__main__":
    sync(dry_run="--dry-run" in sys.argv)
