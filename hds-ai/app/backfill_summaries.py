"""
backfill_summaries.py — Tạo tóm tắt cho các tài liệu đã nạp trước đó (chưa có summary).
Dùng khi nâng cấp từ bản cũ, hoặc sau khi nạp hàng loạt mà bỏ qua bước tóm tắt.
Chạy: python -m app.backfill_summaries
"""
from app import db
from app.models import summarize


def run():
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT d.id, d.title,
                           (SELECT string_agg(content, ' ' ORDER BY chunk_index)
                              FROM (SELECT content, chunk_index FROM chunks
                                     WHERE document_id=d.id ORDER BY chunk_index LIMIT 3) t)
                           FROM documents d
                           WHERE (d.summary IS NULL OR d.summary='') AND d.label_verified
                           ORDER BY d.id""")
            rows = cur.fetchall()

    if not rows:
        print("Tất cả tài liệu đều đã có tóm tắt.")
        return

    print(f">> Tạo tóm tắt cho {len(rows)} tài liệu...\n")
    done = 0
    for doc_id, title, content in rows:
        if not content:
            continue
        try:
            s = summarize(content, title or "")
            with db.session(role="internal", admin=True) as conn:
                with conn.cursor() as cur:
                    cur.execute("UPDATE documents SET summary=%s WHERE id=%s", (s, doc_id))
            print(f"  [{doc_id}] {(title or '')[:40]:40s} → {s[:60]}...")
            done += 1
        except Exception as e:
            print(f"  [{doc_id}] LỖI: {e}")

    print(f"\nXong: {done}/{len(rows)} tài liệu đã có tóm tắt.")


if __name__ == "__main__":
    run()
