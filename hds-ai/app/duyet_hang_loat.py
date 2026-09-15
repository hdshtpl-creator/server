"""Duyệt nhãn HÀNG LOẠT, có chốt chất lượng đọc.

Vì sao: bộ quét kho đẩy mọi tài liệu vào hàng chờ duyệt nhãn. Hàng chờ đã
vượt ba nghìn và còn tăng mỗi lượt quét, nên duyệt tay từng cái là bất khả
thi; mà chưa duyệt thì thẻ Hồ sơ khách 360° không hiện tài liệu nào và bot
không được dùng chúng để trả lời.

Quyết định của chủ dự án 15/09/2026: DUYỆT TẤT CẢ, chỉ giữ lại hàng chờ những
file đọc lỗi trên 20% để mắt người soát. Việc này CỐ Ý nới chính sách
20/08/2026 ("PDF bắt buộc người duyệt", app/auto_learn.py: decide_approval)
cho đúng lô tồn đọng này — chốt chất lượng thay cho mắt người, không phải bỏ
chốt.

Thước đo là app/chat_luong.ty_le_rac, đo trên chính các đoạn đã cắt của tài
liệu. Tài liệu KHÔNG có đoạn nào (trích xuất hỏng hẳn) luôn ở lại hàng chờ.

Cách dùng trên máy chủ:

    cd ~/hds-ai-full/hds-ai
    .venv/bin/python -m app.duyet_hang_loat                # xem trước, KHÔNG ghi
    .venv/bin/python -m app.duyet_hang_loat --thuc-hien    # ghi thật

Mặc định là xem trước: in bảng phân bố tỉ lệ rác và vài ví dụ quanh ngưỡng để
chủ dự án nhìn trước khi cho ghi.
"""
import argparse
import os
import sys

from app import db
from app.chat_luong import ty_le_rac

# Đủ để biết file đọc được hay không mà không phải kéo cả tài liệu dài về.
TOI_DA_DOAN = 10
TOI_DA_KY_TU = 20_000
NGUONG_MAC_DINH = 0.20
# Bộ quét kho dùng khoá này; hai tiến trình cùng ghi vào documents là chuốc
# lấy tranh chấp hàng không cần thiết.
KHOA_QUET_KHO = "/tmp/hds-ai-quet-kho.lock"


def _lay_van_ban(cur, doc_id: int) -> str:
    cur.execute("""SELECT content FROM chunks WHERE document_id=%s
                   ORDER BY chunk_index LIMIT %s""", (doc_id, TOI_DA_DOAN))
    return " ".join(r[0] or "" for r in cur.fetchall())[:TOI_DA_KY_TU]


def _ung_vien(cur, chi_khach: bool, gioi_han: int | None):
    sql = """SELECT id, title, client_id FROM documents
              WHERE NOT label_verified AND coalesce(active, true)"""
    params: list = []
    if chi_khach:
        sql += " AND client_id IS NOT NULL"
    sql += " ORDER BY id"
    if gioi_han:
        sql += " LIMIT %s"
        params.append(gioi_han)
    cur.execute(sql, params)
    return cur.fetchall()


def cham_diem(chi_khach=False, gioi_han=None):
    """Chấm tỉ lệ rác cho mọi tài liệu đang chờ duyệt. Chỉ ĐỌC."""
    ket_qua = []
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            for doc_id, title, client_id in _ung_vien(cur, chi_khach, gioi_han):
                van_ban = _lay_van_ban(cur, doc_id)
                ket_qua.append({"id": doc_id, "title": title,
                                "client_id": client_id,
                                "ty_le": ty_le_rac(van_ban),
                                "co_doan": bool(van_ban.strip())})
    return ket_qua


def ghi_duyet(dat, nguong):
    """Đặt label_verified/approved cho các tài liệu đạt ngưỡng; ghi tỉ lệ rác
    cho TẤT CẢ (kể cả cái bị giữ lại) để tab Duyệt nhãn sắp xếp theo nó."""
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            for d in dat:
                cur.execute("UPDATE documents SET ty_le_rac=%s WHERE id=%s",
                            (round(d["ty_le"], 4), d["id"]))
            dat_id = [d["id"] for d in dat if d["ty_le"] <= nguong and d["co_doan"]]
            if dat_id:
                cur.execute("""UPDATE documents
                                  SET label_verified=true, approved=true,
                                      updated_at=now()
                                WHERE id = ANY(%s)""", (dat_id,))
            db.audit(conn, None, "duyet_hang_loat", "documents", None,
                     {"nguong": nguong, "da_duyet": len(dat_id),
                      "giu_lai": len(dat) - len(dat_id)})
    return len(dat_id)


def _in_bang(ket_qua, nguong):
    moc = [0.0, 0.05, 0.10, nguong, 0.40, 0.70, 1.01]
    ten = ["0-5%", "5-10%", f"10-{nguong:.0%}", f"{nguong:.0%}-40%",
           "40-70%", "70-100%"]
    print(f"\nTổng tài liệu đang chờ duyệt: {len(ket_qua):,}")
    print(f"Ngưỡng giữ lại cho người soát: trên {nguong:.0%} token đọc lỗi\n")
    print(f"  {'Tỉ lệ đọc lỗi':<14} {'Số tài liệu':>12}   Xử lý")
    for i, nhan in enumerate(ten):
        trong = [k for k in ket_qua if moc[i] <= k["ty_le"] < moc[i + 1]]
        xu_ly = "duyệt" if moc[i + 1] <= nguong + 1e-9 else "GIỮ LẠI"
        print(f"  {nhan:<14} {len(trong):>12,}   {xu_ly}")
    khong_doan = [k for k in ket_qua if not k["co_doan"]]
    print(f"\n  Không cắt được đoạn nào: {len(khong_doan):,} — luôn giữ lại")
    duyet = [k for k in ket_qua if k["ty_le"] <= nguong and k["co_doan"]]
    print(f"\n  => Sẽ duyệt: {len(duyet):,}")
    print(f"  => Giữ lại cho người soát: {len(ket_qua) - len(duyet):,}")
    quanh = sorted((k for k in ket_qua if abs(k["ty_le"] - nguong) < 0.12),
                   key=lambda k: k["ty_le"])
    if quanh:
        print(f"\n  Ví dụ quanh ngưỡng (xem thước có chấm đúng không):")
        for k in quanh[:4] + quanh[-4:]:
            dau = "duyệt " if k["ty_le"] <= nguong else "GIỮ   "
            print(f"    {dau} {k['ty_le']:>6.1%}  #{k['id']:<7} {(k['title'] or '')[:58]}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--thuc-hien", action="store_true",
                    help="ghi thật; không có cờ này thì chỉ xem trước")
    ap.add_argument("--nguong", type=float, default=NGUONG_MAC_DINH,
                    help=f"tỉ lệ token đọc lỗi tối đa còn duyệt (mặc định {NGUONG_MAC_DINH})")
    ap.add_argument("--chi-khach", action="store_true",
                    help="chỉ tài liệu gắn khách hàng")
    ap.add_argument("--gioi-han", type=int, default=None,
                    help="chỉ xét N tài liệu đầu — dùng để chạy thử")
    ap.add_argument("--bo-qua-khoa", action="store_true",
                    help="chạy dù bộ quét kho đang chạy (không khuyến khích)")
    args = ap.parse_args(argv)

    if not 0 < args.nguong < 1:
        print("Ngưỡng phải nằm giữa 0 và 1.", file=sys.stderr)
        return 2
    if args.thuc_hien and os.path.exists(KHOA_QUET_KHO) and not args.bo_qua_khoa:
        print(f"Bộ quét kho đang chạy ({KHOA_QUET_KHO}). Chờ nó xong rồi hãy "
              f"ghi, hoặc thêm --bo-qua-khoa nếu bạn chắc.", file=sys.stderr)
        return 3

    ket_qua = cham_diem(chi_khach=args.chi_khach, gioi_han=args.gioi_han)
    if not ket_qua:
        print("Hàng chờ duyệt nhãn đang trống.")
        return 0
    _in_bang(ket_qua, args.nguong)
    if not args.thuc_hien:
        print("\n(Xem trước — chưa ghi gì. Thêm --thuc-hien để duyệt thật.)")
        return 0
    so = ghi_duyet(ket_qua, args.nguong)
    print(f"\nĐã duyệt {so:,} tài liệu. Phần còn lại nằm trong tab "
          f"Duyệt nhãn tài liệu, sắp theo tỉ lệ đọc lỗi.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
