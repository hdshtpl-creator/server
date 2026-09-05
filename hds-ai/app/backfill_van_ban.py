"""backfill_van_ban.py — Điền danh tính + quan hệ văn bản cho KHO ĐÃ HỌC.

Metadata mới (số hiệu, loại, trích yếu, ngày, quan hệ thay thế/sửa đổi) chỉ tự
được bóc khi file được học MỚI hoặc học LẠI (nội dung đổi). Kho hiện có hàng
trăm văn bản luật nội dung không đổi — bộ quét bỏ qua chúng mãi mãi, nên phải
backfill một lần sau deploy. TUYỆT ĐỐI không "học lại cả kho" để backfill:
decide_approval bắt mọi PDF rơi lại hàng chờ duyệt — làm vậy là gỡ cả kho
luật đang phục vụ trả lời (bài học được ghi ở learn-paths 27/08).

Ba việc, theo thứ tự:

1. **Metadata** (mặc định): tài liệu law/an_le/ban_an chưa có so_hieu → đọc
   lại file gốc (source_path), bóc danh tính, UPDATE documents. File mất trên
   đĩa thì bóc từ chunks ghép lại (kém hơn: phần mở đầu của kho cũ đã bị vứt
   lúc cắt đoạn, nhưng số hiệu vẫn nằm trong header từng đoạn).
   KHÔNG lọc label_verified: tài liệu đang chờ duyệt cũng cần metadata để
   form duyệt điền sẵn.
2. **Quan hệ**: với văn bản law có số hiệu → bóc quan hệ từ toàn văn, ghi
   van_ban_quan_he, rồi hạ trạng thái hiệu lực toàn kho một lượt.
3. **--lam-lai-doan** (tùy chọn, tốn thời gian embed): cắt lại + embed lại
   đoạn cho văn bản law có file gốc — để kho cũ cũng có đoạn "Phần mở đầu"
   và trích dẫn đầy đủ ("Bộ luật Lao động số 45/2019/QH14" thay vì
   "Bộ luật số 45/2019/QH14") trong TỪNG vector. Giữ nguyên bản ghi documents
   (id, trạng thái duyệt KHÔNG đổi) — chỉ DELETE/INSERT chunks, đúng khuôn
   PUT /review/{id}/content.

Chạy:  python -m app.backfill_van_ban            # metadata + quan hệ
       python -m app.backfill_van_ban --dry-run  # chỉ liệt kê, không ghi
       python -m app.backfill_van_ban --lam-lai-doan   # thêm bước 3
       python -m app.backfill_van_ban --doc-id 123     # một tài liệu
"""
import json
import sys
from pathlib import Path

from app import db, van_ban


def _doc_text(doc_id, source_path, da_sua_tay=False):
    """Toàn văn của tài liệu: ưu tiên file gốc, rơi về chunks khi file mất.

    ``da_sua_tay`` (extraction_status='edited'): người duyệt đã chữa chữ OCR
    trong CSDL, file gốc trên đĩa vẫn là bản sai. Đọc lại file là bóc metadata
    từ đúng những con số vừa được sửa — phải lấy chữ từ chunks.
    """
    if source_path and not da_sua_tay:
        path = Path(source_path)
        if path.exists():
            try:
                from app.ingest import clean, extract_text_with_metadata
                return clean(extract_text_with_metadata(path).text), "file"
            except Exception as e:  # noqa: BLE001 - file hỏng thì còn đường chunks
                print(f"     [!] đọc file gốc lỗi ({e}) — dùng chunks")
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT string_agg(content, E'\n\n' ORDER BY chunk_index)
                             FROM chunks WHERE document_id=%s""", (doc_id,))
            row = cur.fetchone()
    return (row[0] or "") if row else "", "chunks"


def buoc_metadata(dry_run=False, doc_id=None, tat_ca=False):
    """Bước 1+2: điền danh tính, ghi quan hệ, hạ trạng thái hiệu lực."""
    sql = """SELECT d.id, d.title, d.doc_type, d.source_path,
                    coalesce(d.extraction_status,'ready')='edited'
               FROM documents d
              WHERE d.doc_type IN ('law','an_le','ban_an')
                AND coalesce(d.active,true)"""
    params = []
    if not tat_ca:
        sql += " AND d.so_hieu IS NULL"
    if doc_id:
        sql += " AND d.id=%s"
        params.append(doc_id)
    sql += " ORDER BY d.id"
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    if not rows:
        print("Không có tài liệu nào cần điền metadata.")
        return
    print(f">> Điền danh tính cho {len(rows)} tài liệu...")
    n_ok = n_qh = 0
    for did, title, dtype, spath, da_sua_tay in rows:
        text, nguon_chu = _doc_text(did, spath, da_sua_tay)
        if not text.strip():
            print(f"  [{did}] {str(title)[:45]:45s} — KHÔNG CÓ CHỮ, bỏ qua")
            continue
        meta = van_ban.boc_metadata(text)
        if not meta.get("so_hieu") and not meta.get("loai_van_ban"):
            print(f"  [{did}] {str(title)[:45]:45s} — không bóc được gì ({nguon_chu})")
            continue
        if dry_run:
            print(f"  [{did}] {str(title)[:45]:45s} → {meta.get('so_hieu')} "
                  f"| {meta.get('loai_van_ban')} | {str(meta.get('trich_yeu'))[:40]}")
            continue
        with db.session(role="internal", admin=True) as conn:
            with conn.cursor() as cur:
                cur.execute("""UPDATE documents SET so_hieu=%s,loai_van_ban=%s,
                                      trich_yeu=%s,ngay_ban_hanh=%s,ngay_hieu_luc=%s
                                WHERE id=%s""",
                            (meta.get("so_hieu"), meta.get("loai_van_ban"),
                             meta.get("trich_yeu"), meta.get("ngay_ban_hanh"),
                             meta.get("ngay_hieu_luc"), did))
                qh, _ = van_ban.xu_ly_sau_hoc(cur, dtype, text, meta)
                n_qh += qh
        n_ok += 1
        print(f"  [{did}] {str(title)[:45]:45s} → {meta.get('so_hieu')} "
              f"({nguon_chu}, {qh} quan hệ)")
    if not dry_run:
        with db.session(role="internal", admin=True) as conn:
            with conn.cursor() as cur:
                n_ha = van_ban.cap_nhat_hieu_luc(cur)
        print(f"\nXong: {n_ok}/{len(rows)} tài liệu, {n_qh} quan hệ, "
              f"{n_ha} văn bản bị hạ trạng thái hiệu lực.")


def buoc_lam_lai_doan(dry_run=False, doc_id=None):
    """Bước 3: cắt + embed lại đoạn cho văn bản luật có file gốc.

    Chỉ chọn tài liệu CHƯA có đoạn 'phan_mo_dau' (dấu hiệu đã cắt theo khuôn
    mới) — chạy lại lần hai không làm lại việc đã làm. Trạng thái duyệt và
    documents.id giữ nguyên tuyệt đối.

    Ngoại lệ đã biết: văn bản bắt đầu THẲNG bằng "Điều 1" (không có phần mở
    đầu) không sinh đoạn 'phan_mo_dau' nào, nên mỗi lượt chạy lại đều cắt +
    embed lại nó. Kết quả giống hệt nhau nên không hỏng dữ liệu, chỉ tốn thời
    gian embed — chấp nhận được cho một lệnh chạy tay một lần; dùng --doc-id
    nếu muốn chạy đúng vài tài liệu.

    KHÔNG đụng tài liệu extraction_status='edited': bản người duyệt chữa tay
    nằm trong chunks, còn file gốc trên đĩa vẫn là bản OCR sai.
    """
    sql = """SELECT d.id, d.title, d.doc_type, d.source_path, d.access_level,
                    d.client_id, d.department_id
               FROM documents d
              WHERE d.doc_type='law' AND coalesce(d.active,true)
                AND d.source_path IS NOT NULL
                -- Bản người duyệt đã chữa tay nằm trong chunks, KHÔNG nằm trong
                -- file gốc: cắt lại từ file là xoá sạch công sửa OCR của họ.
                AND coalesce(d.extraction_status,'ready') <> 'edited'
                AND NOT EXISTS (SELECT 1 FROM chunks c WHERE c.document_id=d.id
                                  AND c.source_locator='phan_mo_dau')"""
    params = []
    if doc_id:
        sql += " AND d.id=%s"
        params.append(doc_id)
    sql += " ORDER BY d.id"
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    if not rows:
        print("Không có văn bản luật nào cần cắt lại đoạn.")
        return
    print(f">> Cắt + embed lại đoạn cho {len(rows)} văn bản luật...")
    from app.ingest import extract_text_with_metadata, split_document_with_metadata
    from app.models import embed
    n_ok = 0
    for did, title, dtype, spath, access_level, client_id, department_id in rows:
        path = Path(spath)
        if not path.exists():
            print(f"  [{did}] {str(title)[:45]:45s} — file gốc mất, bỏ qua")
            continue
        if dry_run:
            print(f"  [{did}] {str(title)[:45]:45s} — sẽ cắt lại")
            continue
        try:
            extraction = extract_text_with_metadata(path)
            pieces = split_document_with_metadata(extraction, dtype)
            if not pieces:
                print(f"  [{did}] {str(title)[:45]:45s} — không chia được đoạn")
                continue
            vecs = embed([p.content for p in pieces])
        except Exception as e:  # noqa: BLE001 - một file hỏng không dừng cả lượt
            print(f"  [{did}] LỖI: {e}")
            continue
        with db.session(role="internal", admin=True) as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM chunks WHERE document_id=%s", (did,))
                for idx, (piece, vec) in enumerate(zip(pieces, vecs)):
                    cur.execute("""INSERT INTO chunks
                        (document_id,chunk_index,content,page_number,section_title,
                         source_locator,access_level,client_id,department_id,doc_type,embedding)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (did, idx, piece.content, piece.page_number,
                         piece.section_title, piece.source_locator, access_level,
                         client_id, department_id, dtype, json.dumps(vec)))
        n_ok += 1
        print(f"  [{did}] {str(title)[:45]:45s} → {len(pieces)} đoạn")
    print(f"\nXong: {n_ok}/{len(rows)} văn bản đã có đoạn khuôn mới.")


if __name__ == "__main__":
    args = sys.argv[1:]
    dry = "--dry-run" in args
    mot_id = None
    if "--doc-id" in args:
        mot_id = int(args[args.index("--doc-id") + 1])
    buoc_metadata(dry_run=dry, doc_id=mot_id, tat_ca="--tat-ca" in args)
    if "--lam-lai-doan" in args:
        buoc_lam_lai_doan(dry_run=dry, doc_id=mot_id)
