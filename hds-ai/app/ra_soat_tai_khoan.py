"""
ra_soat_tai_khoan.py — Rà tài khoản trước khi đưa hệ thống vào vận hành thật.

    python -m app.ra_soat_tai_khoan               # chỉ BÁO CÁO, không sửa gì
    python -m app.ra_soat_tai_khoan --thuc-hien   # áp các việc bên dưới

Tìm gì:
  1. Tài khoản còn dùng mật khẩu từng ghi trong mã / sổ tay
     (auth.MAT_KHAU_MAC_DINH_CU: hds12345, admin123, demo123).
  2. Tài khoản mẫu của seed_accounts --demo còn mở.
  3. Tài khoản chưa đăng nhập lần nào / bao nhiêu admin đang mở.

--thuc-hien làm gì (xem phan_loai — logic thuần, có test):
  · Tài khoản MẪU còn mật khẩu mặc định và không phải admin → KHOÁ
    (active=false, thu khoá API). Chưa ai đổi mật khẩu nghĩa là chưa ai
    dùng thật; khoá không mất gì, mở lại được trên web.
  · Tài khoản khác còn mật khẩu mặc định → bật must_change_password: lần
    đăng nhập kế tiếp phải đổi. KHÔNG khoá vì có thể là người thật đang dùng.
  · Admin duy nhất còn mở thì KHÔNG khoá dù thế nào — chỉ bắt đổi mật khẩu.

Mỗi tài khoản phải thử bcrypt với 3 mật khẩu (~0,3 giây/lần) nên vài chục
tài khoản mất khoảng nửa phút. Không chạy trong request web.
"""
import sys

from app import auth, db
from app.seed_accounts import DEMO_EMAILS


def mat_khau_mac_dinh(password_hash: str) -> str | None:
    """Trả về mật khẩu mặc định đang dùng, hoặc None nếu đã đổi."""
    for pw in auth.MAT_KHAU_MAC_DINH_CU:
        if auth.verify_password(pw, password_hash):
            return pw
    return None


def phan_loai(tai_khoan: list[dict]) -> list[dict]:
    """Quyết định làm gì với từng tài khoản. Thuần — không CSDL.

    Mỗi phần tử vào: {id, email, role, active, mac_dinh (str|None),
                      last_login_at (str|None)}
    Trả về danh sách {id, email, hanh_dong, ly_do} với hanh_dong ∈
    {'khoa', 'bat_doi_mat_khau', 'giu'}."""
    so_admin_mo = sum(1 for t in tai_khoan if t["role"] == "admin" and t.get("active", True))
    ket_qua = []
    for t in tai_khoan:
        email = (t.get("email") or "").lower()
        active = t.get("active", True)
        mac_dinh = t.get("mac_dinh")
        if not active:
            ket_qua.append({**t, "hanh_dong": "giu", "ly_do": "đã khoá"})
            continue
        if not mac_dinh:
            ket_qua.append({**t, "hanh_dong": "giu",
                            "ly_do": "mật khẩu đã đổi" + ("" if t.get("last_login_at")
                                                          else " (chưa đăng nhập lần nào)")})
            continue
        la_admin_cuoi = t["role"] == "admin" and so_admin_mo <= 1
        if email in DEMO_EMAILS and t["role"] != "admin":
            ket_qua.append({**t, "hanh_dong": "khoa",
                            "ly_do": f"tài khoản mẫu còn mật khẩu '{mac_dinh}', chưa ai dùng"})
            continue
        ket_qua.append({**t, "hanh_dong": "bat_doi_mat_khau",
                        "ly_do": f"còn mật khẩu mặc định '{mac_dinh}'"
                                 + (" — admin duy nhất, không khoá" if la_admin_cuoi else "")})
    return ket_qua


def run(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    thuc_hien = "--thuc-hien" in argv
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT id, email, role, coalesce(active,true), password_hash,
                                  last_login_at, coalesce(must_change_password,false)
                             FROM users ORDER BY id""")
            rows = cur.fetchall()
        print(f">> Đang thử {len(rows)} tài khoản với {len(auth.MAT_KHAU_MAC_DINH_CU)} "
              "mật khẩu mặc định (bcrypt, hơi lâu)…")
        tai_khoan = [{"id": r[0], "email": r[1], "role": r[2], "active": r[3],
                      "mac_dinh": mat_khau_mac_dinh(r[4]),
                      "last_login_at": str(r[5])[:16] if r[5] else None,
                      "phai_doi": r[6]} for r in rows]
        ds = phan_loai(tai_khoan)

        print(f"\n{'ID':<4} {'EMAIL':<30} {'VAI':<12} {'ĐĂNG NHẬP CUỐI':<17} VIỆC CẦN LÀM")
        print("-" * 100)
        for t in ds:
            nhan = {"khoa": "KHOÁ", "bat_doi_mat_khau": "BẮT ĐỔI MK", "giu": "giữ"}[t["hanh_dong"]]
            print(f"{t['id']:<4} {t['email']:<30} {t['role']:<12} "
                  f"{(t['last_login_at'] or 'chưa bao giờ'):<17} {nhan} — {t['ly_do']}")
        so_admin = sum(1 for t in tai_khoan if t["role"] == "admin" and t["active"])
        print(f"\nAdmin đang mở: {so_admin}. "
              f"Cần sửa: {sum(1 for t in ds if t['hanh_dong'] != 'giu')} tài khoản.")

        if not thuc_hien:
            print("\n(Chỉ xem trước. Thêm --thuc-hien để áp.)")
            return ds
        with conn.cursor() as cur:
            for t in ds:
                if t["hanh_dong"] == "khoa":
                    cur.execute("""UPDATE users SET active=false, api_key_hash=NULL,
                                          api_key_at=NULL, must_change_password=true
                                    WHERE id=%s""", (t["id"],))
                elif t["hanh_dong"] == "bat_doi_mat_khau":
                    cur.execute("UPDATE users SET must_change_password=true WHERE id=%s",
                                (t["id"],))
        db.audit(conn, None, "ra_soat_tai_khoan", "users", None,
                 {"khoa": [t["email"] for t in ds if t["hanh_dong"] == "khoa"],
                  "bat_doi": [t["email"] for t in ds if t["hanh_dong"] == "bat_doi_mat_khau"]})
        print("\nĐã áp. Tài khoản bị khoá mở lại được ở Quản trị → Người dùng & Phòng ban.")
    return ds


if __name__ == "__main__":
    run()
