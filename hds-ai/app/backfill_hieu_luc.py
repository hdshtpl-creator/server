"""backfill_hieu_luc.py — Bóc lại quan hệ THAY THẾ / BÃI BỎ cho kệ luật và
tính lại nhãn hiệu lực (05/10/2026).

Vì sao: đo bộ câu hỏi mẫu 05/10/2026 thấy cả kho 61 nghìn văn bản luật chỉ 11
văn bản mang nhãn "hết hiệu lực":
  · bộ bóc quan hệ chưa đọc dạng câu "<Luật X số Y> hết hiệu lực kể từ ngày…"
    — đúng cách luật mới khai tử luật cũ (3.834 văn bản có câu này);
  · bộ bóc nhặt nhầm câu chương trình "… để bãi bỏ, sửa đổi … phù hợp với
    Bộ luật tố tụng dân sự số 92/2015/QH13" thành "bãi bỏ BLTTDS";
  · tệp trạng thái lấy từ vbpl (cron cap-nhat-hieu-luc.sh) không có giá trị
    "hết hiệu lực" nào — văn bản đã chết bị ghi "còn hiệu lực" mỗi giờ.

Việc làm, theo thứ tự (một transaction mỗi bước, giữ khoá chung với bộ quét kho):
  1. Văn bản luật có câu "hết hiệu lực" HOẶC đang là nguồn của quan hệ tự
     động thay_the/bai_bo → bóc lại từ chữ trong CSDL (gộp các bản cùng số
     hiệu), đối chiếu: thêm quan hệ mới, XOÁ quan hệ tự động thay_the/bai_bo
     không còn bóc ra. KHÔNG đụng loại quan hệ khác (căn cứ, hướng dẫn, hợp
     nhất, sửa đổi) và KHÔNG đụng quan hệ admin thêm tay (nguon='manual').
  2. Nhãn: văn bản là đích của quan hệ thay thế/bãi bỏ từ một văn bản ĐANG
     PHỤC VỤ (đã duyệt) → 'het_hieu_luc', ghi đè cả 'con_hieu_luc' do tệp vbpl
     ghi; văn bản đang 'het_hieu_luc' mà hết căn cứ → 'het_hieu_luc_mot_phan'
     (nếu có văn bản sửa đổi trong kho) hoặc 'chua_ro'. Văn bản người duyệt
     đã đặt hiệu lực bằng tay (nhật ký edit_doc_van_ban_meta / approve_label)
     KHÔNG bị đụng.

Chạy:  python -m app.backfill_hieu_luc --dry-run   # đếm + mẫu, không ghi
       python -m app.backfill_hieu_luc             # ghi thật
"""
import contextlib
import fcntl
import re
import sys
from collections import defaultdict

from app import db, van_ban

KHOA_QUET = "/tmp/hds-ai-quet-kho.lock"
LOAI = ("thay_the", "bai_bo")
SO_HIEU_MAU = ("45/2013/QH13", "92/2015/QH13", "91/2015/QH13", "45/2019/QH14",
               "59/2020/QH14", "33/2005/QH11", "68/2014/QH13", "67/2014/QH13",
               "01/2021/NĐ-CP", "31/2024/QH15", "50/2005/QH11", "36/2005/QH11")


@contextlib.contextmanager
def _giu_khoa():
    with open(KHOA_QUET, "w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            sys.exit("Bộ quét kho đang chạy — đợi nó xong rồi chạy lại (khoá chung).")
        yield


def _van_ban_can_boc(cur):
    """{so_hieu (thường): [(id, ten_nguon)]} cần bóc lại."""
    cur.execute(r"""
        SELECT DISTINCT d.id, d.so_hieu, coalesce(d.trich_yeu, d.title)
          FROM documents d
         WHERE d.doc_type='law' AND coalesce(d.active,true) AND d.so_hieu IS NOT NULL
           AND (EXISTS (SELECT 1 FROM chunks c WHERE c.document_id=d.id
                         AND c.content ~* 'hết\s+hiệu\s+lực')
                OR EXISTS (SELECT 1 FROM van_ban_quan_he q
                            WHERE lower(q.so_hieu_nguon)=lower(d.so_hieu)
                              AND q.nguon='auto' AND q.loai IN ('thay_the','bai_bo')))""")
    nhom = defaultdict(list)
    for i, so, ten in cur.fetchall():
        nhom[so.lower()].append((i, so, ten))
    return nhom


_NHAN_DOAN = re.compile(r"^\s*\[[^\]\n]{0,400}\]\s*")


def _chu(cur, doc_id):
    """Toàn văn ghép từ các đoạn: BỎ dòng nhãn "[Văn bản — Chương — Điều N]" ở
    đầu mỗi đoạn và nối liền (không chèn dòng trống) — danh sách khai tử dài
    vắt qua hai đoạn mà bị dòng trống/nhãn chen vào là bộ bóc cắt ngang ở đó
    (NĐ 145/2020: mục h) NĐ 27/2014 nằm ở đoạn sau)."""
    cur.execute("SELECT content FROM chunks WHERE document_id=%s ORDER BY chunk_index",
                (doc_id,))
    return "\n".join(_NHAN_DOAN.sub("", r[0] or "") for r in cur.fetchall())


def buoc_quan_he(cur, ghi):
    nhom = _van_ban_can_boc(cur)
    them = xoa = 0
    mau = []
    for so_l, docs in nhom.items():
        so = docs[0][1]
        moi = {}
        for doc_id, _so, _ten in docs:
            for q in van_ban.boc_quan_he(_chu(cur, doc_id), so_hieu_minh=so):
                if q["loai"] in LOAI and q.get("so_hieu_dich"):
                    moi.setdefault((q["loai"], q["so_hieu_dich"].lower()), q)
        cur.execute("""SELECT id, loai, lower(so_hieu_dich) FROM van_ban_quan_he
                        WHERE lower(so_hieu_nguon)=%s AND nguon='auto'
                          AND loai IN ('thay_the','bai_bo')""", (so_l,))
        cu = {(lo, dich): i for i, lo, dich in cur.fetchall()}
        bo = [i for k, i in cu.items() if k not in moi]
        mo = [q for k, q in moi.items() if k not in cu]
        if (bo or mo) and len(mau) < 40 and (
                so in SO_HIEU_MAU or any(q["so_hieu_dich"] in SO_HIEU_MAU for q in mo)):
            mau.append((so, [f"+{q['loai']} {q['so_hieu_dich']}" for q in mo],
                        [k for k, i in cu.items() if i in bo]))
        if ghi:
            if bo:
                cur.execute("DELETE FROM van_ban_quan_he WHERE id = ANY(%s)", (bo,))
            ten_nguon = docs[0][2]
            for q in mo:
                cur.execute(
                    """INSERT INTO van_ban_quan_he
                         (so_hieu_nguon, ten_nguon, loai, so_hieu_dich, ten_dich, nguon)
                       VALUES (%s,%s,%s,%s,%s,'auto')
                       ON CONFLICT DO NOTHING""",
                    (so, ten_nguon, q["loai"], q["so_hieu_dich"], q.get("ten_dich")))
        them += len(mo)
        xoa += len(bo)
    return len(nhom), them, xoa, mau


_DICH_HOP_LE = """
    SELECT DISTINCT lower(q.so_hieu_dich) FROM van_ban_quan_he q
      JOIN documents s ON lower(s.so_hieu)=lower(q.so_hieu_nguon)
           AND s.doc_type='law' AND coalesce(s.active,true)
           AND s.approved AND s.label_verified
     WHERE q.loai IN ('thay_the','bai_bo') AND q.so_hieu_dich IS NOT NULL
       AND lower(q.so_hieu_nguon) <> lower(q.so_hieu_dich)"""

_DAT_TAY = """
    SELECT DISTINCT entity_id FROM audit_log
     WHERE action IN ('edit_doc_van_ban_meta','approve_label')
       AND entity='documents' AND entity_id IS NOT NULL
       AND detail::text ~ '"trang_thai_hieu_luc":\\s*"'"""


def buoc_nhan(cur, ghi):
    cur.execute(f"""
        SELECT d.id, d.so_hieu, coalesce(d.trang_thai_hieu_luc,'chua_ro')
          FROM documents d
         WHERE d.doc_type='law' AND coalesce(d.active,true) AND d.so_hieu IS NOT NULL
           AND lower(d.so_hieu) IN ({_DICH_HOP_LE})
           AND coalesce(d.trang_thai_hieu_luc,'chua_ro') <> 'het_hieu_luc'
           AND d.id NOT IN ({_DAT_TAY})""")
    ha = cur.fetchall()
    cur.execute(f"""
        SELECT d.id, d.so_hieu,
               EXISTS (SELECT 1 FROM van_ban_quan_he q
                         JOIN documents s ON lower(s.so_hieu)=lower(q.so_hieu_nguon)
                              AND s.doc_type='law' AND coalesce(s.active,true)
                              AND s.approved AND s.label_verified
                        WHERE q.loai='sua_doi_bo_sung'
                          AND lower(q.so_hieu_dich)=lower(d.so_hieu)
                          AND lower(q.so_hieu_nguon) <> lower(d.so_hieu))
          FROM documents d
         WHERE d.doc_type='law' AND coalesce(d.active,true) AND d.so_hieu IS NOT NULL
           AND d.trang_thai_hieu_luc = 'het_hieu_luc'
           AND lower(d.so_hieu) NOT IN ({_DICH_HOP_LE})
           AND d.id NOT IN ({_DAT_TAY})""")
    nang = cur.fetchall()
    if ghi:
        if ha:
            cur.execute("UPDATE documents SET trang_thai_hieu_luc='het_hieu_luc', "
                        "updated_at=now() WHERE id = ANY(%s)", ([r[0] for r in ha],))
        for i, _so, co_sua in nang:
            cur.execute("UPDATE documents SET trang_thai_hieu_luc=%s, updated_at=now() "
                        "WHERE id=%s", ("het_hieu_luc_mot_phan" if co_sua else "chua_ro", i))
    return ha, nang


def _mau_trung_uong(cur, ids, toi_da=60):
    """Mẫu văn bản cấp trung ương (Luật, Pháp lệnh, Nghị định, Quyết định TTg)
    sắp bị đánh hết hiệu lực, kèm văn bản tuyên thay thế — để soát tay."""
    if not ids:
        return []
    cur.execute("""SELECT d.so_hieu, left(coalesce(d.trich_yeu, d.title), 50),
                          string_agg(DISTINCT q.so_hieu_nguon, ', ')
                     FROM documents d
                     JOIN van_ban_quan_he q ON lower(q.so_hieu_dich)=lower(d.so_hieu)
                          AND q.loai IN ('thay_the','bai_bo')
                    WHERE d.id = ANY(%s)
                    GROUP BY 1, 2""", (ids,))
    rows = [r for r in cur.fetchall() if (van_ban.cap_van_ban(r[0]) or 9) <= 3]
    rows.sort(key=lambda r: (van_ban.cap_van_ban(r[0]), r[0]))
    return rows[:toi_da], len(rows)


def main():
    ghi = "--dry-run" not in sys.argv
    with _giu_khoa():
        with db.session(role="internal", admin=True) as conn:
            with conn.cursor() as cur:
                # Chạy thử cũng chạy ĐỦ hai bước trong cùng giao dịch rồi huỷ —
                # bước 2 phải thấy quan hệ bước 1 vừa thêm/xoá mới đúng số.
                n, them, xoa, mau = buoc_quan_he(cur, True)
                ha, nang = buoc_nhan(cur, True)
                mau_tu, n_tu = _mau_trung_uong(cur, [r[0] for r in ha])
            if not ghi:
                conn.rollback()
        print(f"1. Quan hệ: {n} số hiệu được bóc lại · thêm {them} · xoá {xoa} quan hệ sai")
        for so, mo, bo in mau:
            print(f"   {so}: {' '.join(mo)} {'  XOÁ ' + str(bo) if bo else ''}")
        print(f"2. Nhãn: {len(ha)} văn bản → hết hiệu lực · {len(nang)} văn bản gỡ nhãn hết hiệu lực sai")
        dem = defaultdict(int)
        for _i, _so, tt in ha:
            dem[tt] += 1
        print("   trước đó là:", dict(dem))
        print(f"   trong đó {n_tu} văn bản cấp trung ương (Luật/Pháp lệnh/Nghị định/QĐ-TTg), mẫu:")
        for so, ten, nguon in mau_tu:
            print(f"     {so:18} {ten:50} ← {nguon[:60]}")
        for _i, so, co_sua in nang[:20]:
            print(f"   {so}: het_hieu_luc → {'het_hieu_luc_mot_phan' if co_sua else 'chua_ro'}")
    print("ĐÃ GHI." if ghi else "CHẠY THỬ — đã huỷ mọi thay đổi (bỏ --dry-run để ghi).")


if __name__ == "__main__":
    main()
