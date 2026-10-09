"""thay_ho_so_khach.py — THAY cả ngăn hồ sơ khách bằng một bộ mới.

07/10/2026, chủ dự án: "xoá hồ sơ khách cũ và kéo về mới từ Drive". Bộ mới
tải về một thư mục tạm bằng app.keo_drive, rồi:

    python -m app.thay_ho_so_khach <thư mục mới>              # XEM TRƯỚC, không đổi gì
    python -m app.thay_ho_so_khach <thư mục mới> --thuc-hien  # thay thật
    python -m app.thay_ho_so_khach --don-khach-rong [--thuc-hien]

Thay thật = trong lúc GIỮ khoá của bộ quét (cron, web, CRM đều chờ):
  1. CẤT bộ cũ: đổi tên `data/raw/9. HỒ SƠ KHÁCH HÀNG` → `data/_da_go/
     ho-so-khach-cu-<giờ>` (cùng ổ nên tức thì, không chép; muốn lùi thì đổi
     tên ngược lại + chạy bộ quét). KHÔNG xoá tệp nào.
  2. GỠ khỏi kho tri thức mọi tài liệu mang danh tính `local:9. HỒ SƠ KHÁCH
     HÀNG/…` (đoạn, phiên bản xoá theo), đóng các lỗi học của ngăn đó.
     Một giao dịch: hỏng giữa chừng thì CSDL như cũ và bộ cũ được trả về chỗ.
  3. ĐẶT bộ mới vào đúng chỗ bộ cũ.
Nhả khoá → lượt cron kế tiếp (≤ 3 phút) học lại cả ngăn từ đầu.

Vì sao gỡ CSDL TRƯỚC khi bộ mới vào: bộ quét coi tệp mới trùng md5 một tài
liệu "mất tệp" là DI CHUYỂN và giữ nguyên bản đã học từ trước. Chủ dự án muốn
bỏ hẳn bộ cũ, nên mọi tệp của bộ mới phải được đọc lại bằng bộ đọc hiện hành.

Bản ghi KHÁCH (bảng clients) được GIỮ: bộ quét tra khách theo MÃ trong tên thư
mục, mã còn trong bộ mới thì nhận lại đúng khách cũ (tài khoản khách, hội
thoại, mã CRM gắn với khách vẫn đúng). Khách không còn tài liệu nào sau khi
học xong thì dọn bằng --don-khach-rong (bỏ qua khách còn được tham chiếu).
"""
from __future__ import annotations

import argparse
import collections
import contextlib
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from app import db
from app.auto_learn import RE_CLIENT_NUM
from app.local_learn import DATA_LIB, LOCAL_PREFIX, walk_library

NGAN = "9. HỒ SƠ KHÁCH HÀNG"
KHOA_QUET = Path(os.getenv("HDS_KHOA_QUET_KHO", "/tmp/hds-ai-quet-kho.lock"))
# Bảng tham chiếu clients mà KHÔNG xoá theo (NO ACTION) — còn dòng nào trỏ tới
# thì không được xoá khách. client_profiles xoá theo (CASCADE), drafts SET NULL.
THAM_CHIEU_KHACH = ("documents", "users", "conversations", "matters", "tich_hop_tai_lieu")


@contextlib.contextmanager
def giu_khoa(cho_giay: int = 1800):
    """Giữ khoá bộ quét, chờ tối đa `cho_giay` (một lượt học lớn có thể giữ
    khoá hàng giờ — khi đó dừng hẳn chứ không chen vào)."""
    import fcntl
    import time
    fh = open(KHOA_QUET, "a")
    het = time.monotonic() + cho_giay
    try:
        while True:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() > het:
                    raise SystemExit(f"[!] Bộ quét/học đang giữ {KHOA_QUET} quá {cho_giay} giây — "
                                     "chờ lượt học xong rồi chạy lại.")
                time.sleep(5)
        yield
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(fh, fcntl.LOCK_UN)
        fh.close()


def _ma_khach(ten_thu_muc: str):
    m = RE_CLIENT_NUM.match(ten_thu_muc)
    return m.group(1) if m else None


def tom_tat_cay(goc: Path) -> dict:
    tep = walk_library(goc)
    cap1 = collections.Counter(parts[0] if parts else "(gốc)" for _, parts in tep)
    thu_muc = sorted(p.name for p in goc.iterdir() if p.is_dir()) if goc.exists() else []
    co_ma = [t for t in thu_muc if _ma_khach(t)]
    duoi = collections.Counter(p.suffix.lower() or "(không đuôi)" for p, _ in tep)
    return {"so_tep": len(tep), "thu_muc": thu_muc, "co_ma": co_ma,
            "khong_ma": [t for t in thu_muc if not _ma_khach(t)],
            "cap1": cap1, "duoi": duoi,
            "tep_o_goc": [p.name for p, parts in tep if not parts]}


def _dem_csdl(cur, tien_to: str) -> dict:
    like = tien_to.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    cur.execute("SELECT count(*), count(*) FILTER (WHERE approved), "
                "count(DISTINCT client_id) FROM documents WHERE drive_file_id LIKE %s", (like,))
    tl, duyet, khach = cur.fetchone()
    cur.execute("SELECT count(*) FROM chunks c JOIN documents d ON d.id = c.document_id "
                "WHERE d.drive_file_id LIKE %s", (like,))
    doan = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM ingest_failures WHERE drive_file_id LIKE %s "
                "AND resolved_at IS NULL", (like,))
    loi = cur.fetchone()[0]
    return {"like": like, "tai_lieu": tl, "da_duyet": duyet, "khach": khach,
            "doan": doan, "loi_hoc": loi}


def _ma_khach_csdl(cur) -> dict:
    cur.execute("SELECT code, id, name FROM clients WHERE code IS NOT NULL")
    out = {}
    for code, cid, name in cur.fetchall():
        # Bộ quét so mã y nguyên (upper(code)=upper(%s)) — "0999" khác "999".
        out.setdefault(str(code).upper(), []).append((cid, name))
    return out


def xem_truoc(moi: Path) -> dict:
    cu = DATA_LIB / NGAN
    a, b = tom_tat_cay(cu), tom_tat_cay(moi)
    with db.session(admin=True) as conn, conn.cursor() as cur:
        csdl = _dem_csdl(cur, LOCAL_PREFIX + NGAN + "/")
        ma_csdl = _ma_khach_csdl(cur)
    ma_moi = {_ma_khach(t).upper() for t in b["co_ma"]}
    trung = sorted(m for m in ma_moi if m in ma_csdl)
    print(f"BỘ CŨ  {cu}")
    print(f"   {a['so_tep']} tệp đọc được trong {len(a['thu_muc'])} thư mục cấp 1 "
          f"({len(a['co_ma'])} có mã khách)")
    print(f"   CSDL: {csdl['tai_lieu']} tài liệu ({csdl['da_duyet']} đã duyệt) của "
          f"{csdl['khach']} khách · {csdl['doan']} đoạn · {csdl['loi_hoc']} lỗi học mở")
    print(f"BỘ MỚI {moi}")
    print(f"   {b['so_tep']} tệp đọc được trong {len(b['thu_muc'])} thư mục cấp 1 "
          f"({len(b['co_ma'])} có mã khách)")
    print("   Đuôi: " + ", ".join(f"{d} {n}" for d, n in b["duoi"].most_common(15)))
    print(f"   Mã khách trùng khách đã có trong CSDL: {len(trung)} · mã mới: {len(ma_moi) - len(trung)}")
    if b["khong_ma"]:
        print(f"   [CHÚ Ý] {len(b['khong_ma'])} thư mục cấp 1 KHÔNG có mã khách "
              "(bộ quét sẽ không gắn tài liệu trong đó cho khách nào):")
        for t in b["khong_ma"][:15]:
            print(f"      · {t}  ({b['cap1'].get(t, 0)} tệp)")
    if b["tep_o_goc"]:
        print(f"   [CHÚ Ý] {len(b['tep_o_goc'])} tệp nằm thẳng ở gốc, không trong thư mục khách nào.")
    return {"cu": a, "moi": b, "csdl": csdl}


def _kiem_dieu_kien(moi: Path, b: dict):
    moi_r, lib_r = moi.resolve(), DATA_LIB.resolve()
    if moi_r == lib_r or lib_r in moi_r.parents:
        raise SystemExit(f"[!] Thư mục mới {moi} đang nằm TRONG kho {DATA_LIB} — bộ quét sẽ học "
                         "nó ở chỗ sai. Tải về ngoài kho (vd data/_tai_ve/…).")
    if b["so_tep"] == 0 or not b["co_ma"]:
        raise SystemExit("[!] Thư mục mới không có tệp đọc được hoặc không có thư mục khách "
                         "nào mang mã — dừng, không thay.")
    if os.stat(moi).st_dev != os.stat(DATA_LIB).st_dev:
        raise SystemExit("[!] Thư mục mới khác ổ với kho — đổi tên không tức thì được; "
                         "tải về trong cùng ổ (vd data/_tai_ve/…).")


def thay(moi: Path) -> int:
    tt = xem_truoc(moi)
    _kiem_dieu_kien(moi, tt["moi"])
    cu = DATA_LIB / NGAN
    cat = DATA_LIB.parent / "_da_go" / f"ho-so-khach-cu-{datetime.now():%Y%m%d-%H%M}"
    if cat.exists():
        raise SystemExit(f"[!] {cat} đã có — chờ một phút rồi chạy lại.")
    print("\nChờ khoá bộ quét…", flush=True)
    with giu_khoa():
        print("Đã giữ khoá. 1/3 cất bộ cũ →", cat, flush=True)
        cat.parent.mkdir(parents=True, exist_ok=True)
        if cu.exists():
            os.rename(cu, cat)
        try:
            print("2/3 gỡ tài liệu của ngăn khỏi kho tri thức…", flush=True)
            with db.session(admin=True) as conn, conn.cursor() as cur:
                cur.execute("SET LOCAL lock_timeout = '10s'")
                like = tt["csdl"]["like"]
                cur.execute("SELECT id FROM documents WHERE drive_file_id LIKE %s", (like,))
                ids = [r[0] for r in cur.fetchall()]
                cur.execute("UPDATE messages SET promoted_doc_id = NULL "
                            "WHERE promoted_doc_id = ANY(%s)", (ids,))
                cur.execute("DELETE FROM documents WHERE id = ANY(%s)", (ids,))
                so_xoa = cur.rowcount
                cur.execute("UPDATE ingest_failures SET resolved_at = now() "
                            "WHERE drive_file_id LIKE %s AND resolved_at IS NULL", (like,))
                so_loi = cur.rowcount
                db.audit(conn, None, "thay_ho_so_khach", "documents", None,
                         {"go": so_xoa, "loi_dong": so_loi, "cat_bo_cu": str(cat),
                          "bo_moi": str(moi), "so_tep_moi": tt["moi"]["so_tep"]})
        except BaseException:
            if cat.exists() and not cu.exists():
                os.rename(cat, cu)
                print("[!] Gỡ CSDL hỏng — đã trả bộ cũ về chỗ, CSDL không đổi.")
            raise
        print(f"   đã gỡ {so_xoa} tài liệu, đóng {so_loi} lỗi học", flush=True)
        print("3/3 đặt bộ mới vào", cu, flush=True)
        try:
            os.rename(moi, cu)
        except OSError:
            # CSDL đã gỡ xong, bộ cũ đã cất — chỉ còn thiếu bước đổi tên này.
            print(f"[!] Không đổi tên được {moi} → {cu}. Làm tay: mv '{moi}' '{cu}'")
            raise
    print("\nXONG. Lượt quét cron kế tiếp (≤ 3 phút) sẽ học cả ngăn từ đầu.")
    print(f"Bộ cũ cất ở {cat} — muốn lùi: đổi tên ngược lại rồi để bộ quét học lại.")
    print("Học xong: python -m app.thay_ho_so_khach --don-khach-rong  (xem khách không còn tài liệu)")
    return 0


def don_khach_rong(thuc_hien: bool) -> int:
    dieu_kien = " AND ".join(
        f"NOT EXISTS (SELECT 1 FROM {b} x WHERE x.client_id = c.id)" for b in THAM_CHIEU_KHACH)
    with db.session(admin=True) as conn, conn.cursor() as cur:
        cur.execute(f"SELECT c.id, c.code, c.name FROM clients c WHERE {dieu_kien} ORDER BY c.code")
        rong = cur.fetchall()
        cur.execute("SELECT count(*) FROM clients")
        tong = cur.fetchone()[0]
        print(f"{len(rong)}/{tong} khách không còn tài liệu và không được gì tham chiếu:")
        for cid, code, name in rong[:30]:
            print(f"   · #{cid} [{code}] {name}")
        if len(rong) > 30:
            print(f"   … và {len(rong) - 30} khách nữa")
        if not thuc_hien or not rong:
            print("(xem trước — thêm --thuc-hien để xoá các khách trên)" if rong else "")
            return 0
        cur.execute(f"DELETE FROM clients c WHERE c.id = ANY(%s) AND {dieu_kien}",
                    ([r[0] for r in rong],))
        print(f"Đã xoá {cur.rowcount} khách.")
        db.audit(conn, None, "don_khach_rong", "clients", None, {"xoa": cur.rowcount})
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("moi", nargs="?", help="thư mục bộ hồ sơ mới (ngoài kho, cùng ổ)")
    ap.add_argument("--thuc-hien", action="store_true")
    ap.add_argument("--don-khach-rong", action="store_true")
    a = ap.parse_args(argv)
    if a.don_khach_rong:
        return don_khach_rong(a.thuc_hien)
    if not a.moi:
        ap.error("cần thư mục bộ mới (hoặc --don-khach-rong)")
    moi = Path(a.moi)
    if not moi.is_dir():
        raise SystemExit(f"[!] Không có thư mục {moi}")
    if not a.thuc_hien:
        xem_truoc(moi)
        print("\n(xem trước — chưa đổi gì; thêm --thuc-hien để thay thật)")
        return 0
    return thay(moi)


if __name__ == "__main__":
    sys.exit(main())
