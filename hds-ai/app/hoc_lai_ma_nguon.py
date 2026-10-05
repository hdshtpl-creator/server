"""
hoc_lai_ma_nguon.py — Học lại tài liệu ĐÃ HỌC mà nội dung đọc ra là MÃ NGUỒN
(dòng đầu mục MIME, CSS, thẻ HTML) thay vì chữ của văn bản.

    python -m app.hoc_lai_ma_nguon               # chỉ LIỆT KÊ, không sửa gì
    python -m app.hoc_lai_ma_nguon --thuc-hien   # học lại thật

Vì sao có (29/09/2026): tới lúc đó bộ đọc coi tệp .doc xuất từ Confluence
("Export to Word" ghi ra gói MHTML) là văn bản thuần, nên tài liệu "học xong"
với nội dung "MIME-Version: 1.0 … Content-Transfer-Encoding: quoted-printable
… <html xmlns:o=3D…" — hồ sơ khách 913 Bee Art là một. Ba bản trong số đó
còn được duyệt, bot đang trích dẫn rác từ chúng. Bộ quét không tự sửa: md5
tệp không đổi thì không học lại, còn --thu-lai-loi chỉ đụng tệp trong danh
sách hỏng. Lệnh này tìm theo NỘI DUNG đã học rồi ép học lại bằng bộ đọc mới
(kho.hoc_file ep_hoc_lai=True): bản đã duyệt giữ trạng thái duyệt nếu bản
mới sạch, bản chờ duyệt theo chính sách tự duyệt hiện hành.

Giữ khoá chung với bộ quét cron (kho.giu_khoa_quet) trong lúc học từng tệp;
chạy trên máy chủ SAU khi deploy bộ đọc mới, không cần sudo.
"""
import re
import sys

from app import db, kho

# Dấu hiệu nội dung là mã nguồn — anchored đầu dòng để "MIME" trong câu văn
# bình thường không bị bắt nhầm.
_MA_NGUON = re.compile(
    r"(?m)^(?:MIME-Version:\s*1\.0|Content-Transfer-Encoding:\s*quoted-printable"
    r"|Content-Type:\s*multipart/|<(?:!DOCTYPE\s+html|html|head|body)\b)", re.I)
_XEM_TOI = 4000


def la_ma_nguon(noi_dung: str) -> bool:
    """Đoạn đầu của tài liệu có phải mã nguồn MIME/HTML không. Thuần."""
    return bool(_MA_NGUON.search((noi_dung or "")[:_XEM_TOI]))


def tim_ung_vien() -> list[dict]:
    """Tài liệu đang hoạt động, học từ kho local, đoạn đầu là mã nguồn."""
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT d.id, d.drive_file_id, d.title,
                                  d.approved AND d.label_verified, c.content
                             FROM documents d
                             JOIN chunks c ON c.document_id=d.id AND c.chunk_index=0
                            WHERE coalesce(d.active,true)
                              AND d.drive_file_id LIKE 'local:%%'
                              AND (c.content LIKE '%%MIME-Version: 1.0%%'
                                   OR c.content LIKE '%%quoted-printable%%'
                                   OR c.content LIKE '%%<html%%'
                                   OR c.content LIKE '%%<!DOCTYPE%%')
                            ORDER BY d.id""")
            rows = cur.fetchall()
    ra = []
    for doc_id, key, title, duyet, content in rows:
        if not la_ma_nguon(content):
            continue
        rel = kho.rel_tu_khoa(key)
        ra.append({"id": doc_id, "key": key, "rel": rel, "title": title,
                   "da_duyet": bool(duyet)})
    return ra


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    thuc_hien = "--thuc-hien" in argv
    ung_vien = tim_ung_vien()
    if not ung_vien:
        print("Không có tài liệu nào đọc ra mã nguồn.")
        return 0
    print(f"{len(ung_vien)} tài liệu đọc ra mã nguồn:")
    for uv in ung_vien:
        print(f"  #{uv['id']:<7} {'ĐÃ DUYỆT' if uv['da_duyet'] else 'chờ duyệt':<9} {uv['rel']}")
    if not thuc_hien:
        print("\n(Chỉ xem trước. Thêm --thuc-hien để học lại.)")
        return 0

    root = kho.library_root()
    xong = loi = 0
    for uv in ung_vien:
        rel = uv["rel"]
        if not rel or not kho.duong_dan_kho(rel, root).is_file():
            print(f"  [BỎ QUA] #{uv['id']} không còn tệp trên đĩa: {rel}")
            loi += 1
            continue
        try:
            with kho.giu_khoa_quet():
                r = kho.hoc_file(rel, None, ep_hoc_lai=True)
        except kho.LoiKho as e:
            print(f"  [LỖI] #{uv['id']} {rel}: {e}")
            loi += 1
            continue
        xong += 1
        print(f"  [XONG] #{uv['id']} → #{r['document_id']} {r['trang_thai']}: {rel}")
    print(f"\nHọc lại {xong} tài liệu, {loi} lỗi.")
    return 1 if loi else 0


if __name__ == "__main__":
    sys.exit(main())
