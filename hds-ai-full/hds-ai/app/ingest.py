"""
ingest.py — Đưa tài liệu vào kho: đọc → OCR → chia đoạn → vector → lưu.
Chạy: python -m app.ingest data/raw [doc_type]
"""
import hashlib
import json
import re
import sys
from pathlib import Path

from app import db
from app.models import embed, summarize

CHUNK_WORDS = 700
CHUNK_OVERLAP = 100


def extract_text(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in (".txt", ".md"):
        return path.read_text(encoding="utf-8", errors="ignore")
    if ext == ".docx":
        from docx import Document as Docx
        d = Docx(str(path))
        parts = [p.text for p in d.paragraphs]
        for tbl in d.tables:
            for row in tbl.rows:
                parts.append(" | ".join(c.text for c in row.cells))
        return "\n".join(parts)
    if ext == ".pdf":
        text = ""
        try:
            import pdfplumber
            with pdfplumber.open(str(path)) as pdf:
                text = "\n".join((pg.extract_text() or "") for pg in pdf.pages)
        except Exception as e:
            print(f"  [!] pdfplumber lỗi: {e}")
        if len(text.strip()) < 100:
            print(f"  [OCR] {path.name} có vẻ là bản scan...")
            text = ocr_pdf(path)
        return text
    if ext == ".doc":
        print(f"  [!] {path.name} .doc cũ — convert trước: libreoffice --headless --convert-to docx")
        return ""
    return ""


def ocr_pdf(path: Path) -> str:
    try:
        import pytesseract
        from pdf2image import convert_from_path
        return "\n".join(pytesseract.image_to_string(img, lang="vie")
                         for img in convert_from_path(str(path), dpi=300))
    except Exception as e:
        print(f"  [!] OCR lỗi: {e} (cần: tesseract-ocr-vie, poppler-utils)")
        return ""


def clean(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


RE_DIEU = re.compile(r"^\s*(Điều\s+\d+[a-z]?)\s*[.:]?", re.MULTILINE | re.IGNORECASE)


def chunk_law(text):
    marks = [(m.start(), m.group(1)) for m in RE_DIEU.finditer(text)]
    if not marks:
        return chunk_generic(text)
    out = []
    for i, (pos, label) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        body = text[pos:end].strip()
        if len(body) < 20:
            continue
        if len(body.split()) > CHUNK_WORDS * 2:
            for j, sub in enumerate(chunk_generic(body), 1):
                out.append(f"[{label} - phần {j}]\n{sub}")
        else:
            out.append(body)
    return out


def chunk_generic(text):
    words = text.split()
    if not words:
        return []
    out, i, step = [], 0, CHUNK_WORDS - CHUNK_OVERLAP
    while i < len(words):
        piece = " ".join(words[i:i + CHUNK_WORDS])
        if piece.strip():
            out.append(piece)
        i += step
    return out


def split_document(text, doc_type):
    text = clean(text)
    if not text:
        return []
    return chunk_law(text) if doc_type == "law" else chunk_generic(text)


def ingest_file(path: Path, doc_type="other", access_level="internal", client_id=None,
                department_id=None, matter_id=None,
                approved=False, label_verified=False, source_kind="manual"):
    print(f">> {path.name}")
    if access_level == "client" and client_id is None:
        print("  [BỎ QUA] client thiếu client_id → nguy cơ lộ dữ liệu chéo.")
        return None
    text = extract_text(path)
    if not text.strip():
        print("  [BỎ QUA] không trích được nội dung.")
        return None
    pieces = split_document(text, doc_type)
    if not pieces:
        print("  [BỎ QUA] không chia được đoạn.")
        return None
    print(f"  {len(text)} ký tự → {len(pieces)} đoạn, đang tạo vector...")
    vecs = embed(pieces)
    print("  Đang tạo tóm tắt...")
    summary = summarize(text, path.stem)
    checksum = hashlib.md5(text.encode()).hexdigest()
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO documents
                (title,source_path,checksum,doc_type,access_level,client_id,department_id,matter_id,
                 approved,label_verified,source_kind,summary)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (path.stem, str(path), checksum, doc_type, access_level, client_id, department_id, matter_id,
                 approved, label_verified, source_kind, summary))
            doc_id = cur.fetchone()[0]
            for idx, (piece, vec) in enumerate(zip(pieces, vecs)):
                cur.execute("""INSERT INTO chunks
                    (document_id,chunk_index,content,access_level,client_id,department_id,doc_type,embedding)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (doc_id, idx, piece, access_level, client_id, department_id, doc_type, json.dumps(vec)))
        db.audit(conn, None, "ingest_document", "documents", doc_id,
                 {"file": path.name, "chunks": len(pieces)})
    print(f"  [OK] document_id={doc_id}, {len(pieces)} đoạn.")
    return doc_id


def ingest_folder(folder, **kw):
    root = Path(folder)
    if not root.exists():
        print(f"Không thấy thư mục: {folder}")
        return
    files = [p for p in root.rglob("*") if p.suffix.lower() in {".txt", ".md", ".docx", ".pdf"}]
    print(f"Tìm thấy {len(files)} file.\n")
    ok = 0
    for p in files:
        try:
            if ingest_file(p, **kw):
                ok += 1
        except Exception as e:
            print(f"  [LỖI] {p.name}: {e}")
    print(f"\nHoàn tất: {ok}/{len(files)} file.")


if __name__ == "__main__":
    folder = sys.argv[1] if len(sys.argv) > 1 else "data/raw"
    dtype = sys.argv[2] if len(sys.argv) > 2 else "other"
    ingest_folder(folder, doc_type=dtype, access_level="internal",
                  approved=True, label_verified=True)
