"""sua_thuat_ngu_sec.py — Chữa thuật ngữ dịch máy sai trong lô hợp đồng Hoa Kỳ – SEC
(05/10/2026).

Bản dịch tham khảo của lô 2.304 tài liệu SEC do qwen3:14b dịch: "jury trial"
thành "tòa án dân sự" / "thử tụng bởi tòa án"…, "Non-Disclosure Agreement" thành
"Thỏa thuận Mật khẩu". Mỗi đoạn dịch sai một kiểu nên không thay chữ máy móc
được; cách chắc chắn:
  · chữ sai rõ ràng, một nghĩa → thay thẳng ("Thỏa thuận Mật khẩu");
  · đoạn có thuật ngữ hay bị dịch sai (jury trial…) → GẮN một dòng ghi chú
    thuật ngữ vào cuối đoạn, để bot đọc đúng nghĩa thay vì lặp bản dịch sai.
Sửa trong CSDL (nội dung + tạo lại vector của đúng các đoạn đó), giữ nguyên tài
liệu, trạng thái duyệt, id. Chạy lại được: đoạn đã có ghi chú thì bỏ qua.

Chạy:  python -m app.sua_thuat_ngu_sec --dry-run
       python -m app.sua_thuat_ngu_sec
"""
import json
import re
import sys

from app import db

NGAN = "%Hợp đồng Hoa Kỳ – SEC/%"
THAY = (("Thỏa thuận Mật khẩu", "Thỏa thuận Bảo mật"),
        ("Thoả thuận Mật khẩu", "Thoả thuận Bảo mật"))
# (mẫu tiếng Anh trong đoạn, dòng ghi chú gắn thêm)
GHI_CHU = (
    (re.compile(r"\bjury\b", re.IGNORECASE),
     "Ghi chú thuật ngữ: “jury trial / trial by jury” = xét xử có BỒI THẨM ĐOÀN "
     "(thủ tục tố tụng Hoa Kỳ, Việt Nam không có); “waive … trial by jury” = từ bỏ "
     "quyền được xét xử có bồi thẩm đoàn. Bản dịch máy phía trên có thể dịch sai cụm này."),
    (re.compile(r"\bforum non conveniens\b", re.IGNORECASE),
     "Ghi chú thuật ngữ: “forum non conveniens” = phản đối thẩm quyền vì tòa án được "
     "chọn là nơi xét xử không thuận tiện."),
)
DAU_GHI_CHU = "Ghi chú thuật ngữ:"


def main():
    ghi = "--dry-run" not in sys.argv
    from app.models import embed
    sua = []
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT c.id, c.content FROM chunks c
                             JOIN documents d ON d.id=c.document_id
                            WHERE d.source_path LIKE %s AND c.content ~* 'Bản dịch tham khảo'
                              AND (c.content ~* 'jury|forum non conveniens'
                                   OR c.content ~ 'Tho[ảả] thuận Mật khẩu')""", (NGAN,))
            for cid, t in cur.fetchall():
                moi = t
                for cu, dung in THAY:
                    moi = moi.replace(cu, dung)
                them = [note for rx, note in GHI_CHU if rx.search(t) and note not in t]
                if them:
                    moi = moi.rstrip() + "\n\n" + "\n".join(f"_{n}_" for n in them)
                if moi != t:
                    sua.append((cid, moi))
            print(f"{len(sua)} đoạn cần sửa")
            for cid, moi in sua[:3]:
                print(f"--- đoạn {cid}: …{moi[-300:]}")
            if ghi and sua:
                vecs = embed([m for _c, m in sua])
                for (cid, moi), v in zip(sua, vecs):
                    cur.execute("UPDATE chunks SET content=%s, embedding=%s::vector WHERE id=%s",
                                (moi, json.dumps(v), cid))
    print("ĐÃ GHI." if ghi else "CHẠY THỬ — chưa ghi.")


if __name__ == "__main__":
    main()
