"""
seed_accounts.py — Tạo tài khoản quản trị đầu tiên để đăng nhập vào web.

    python -m app.seed_accounts              # tạo admin@hdslaw.vn nếu CHƯA có,
                                             # in mật khẩu tạm ĐÚNG MỘT LẦN
    python -m app.seed_accounts --reset-admin   # quên mật khẩu admin: cấp lại
    python -m app.seed_accounts --demo       # thêm 4 tài khoản mẫu (demo123)
                                             # — CHỈ máy thử nghiệm, KHÔNG chạy
                                             # trên máy chủ vận hành thật

Đến 22/09/2026 script này tạo cả 5 tài khoản với mật khẩu ghi sẵn trong mã
(admin123 / demo123) và GHI ĐÈ mật khẩu mỗi lần chạy lại — setup.sh gọi nó
nên chạy lại setup.sh trên máy đang hoạt động là mật khẩu mọi người về mặc
định. Nay:

· Mặc định chỉ tạo MỘT tài khoản admin, mật khẩu tạm ngẫu nhiên (hoặc lấy
  từ biến môi trường ADMIN_INITIAL_PASSWORD), bắt đổi ngay lần đăng nhập đầu.
· Admin đã tồn tại thì KHÔNG đụng tới — chạy lại bao nhiêu lần cũng vô hại.
· Tài khoản mẫu phải xin rõ bằng --demo. Nhân viên thật tạo trên web:
  Quản trị → Người dùng & Phòng ban.
"""
import os
import sys

from app import db, auth

ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@hdslaw.vn").strip().lower()

# (email, tên, vai, mật khẩu, can_review, [mã phòng], [phòng làm trưởng], quota)
# Chỉ dùng khi --demo. Mật khẩu ở đây nằm trong auth.MAT_KHAU_MAC_DINH_CU nên
# app/ra_soat_tai_khoan.py nhận ra và khoá được trước khi vận hành thật.
ACCOUNTS_DEMO = [
    ("giamdoc@hdslaw.vn", "Giám đốc (Ban QT)",  "ban_qt",      "demo123",   True,  [], [], 0),
    ("truong.dndt@hdslaw.vn", "Trưởng phòng DN-ĐT", "truong_bph", "demo123", True, ["dn-dt"], ["dn-dt"], 0),
    ("cv.tranhtung@hdslaw.vn", "Chuyên viên Tranh tụng", "chuyen_vien", "demo123", False, ["tranh-tung"], [], 0),
    ("troly@hdslaw.vn",   "Trợ lý",             "tro_ly",      "demo123",   False, ["htpl-tvtx"], [], 0),
]
DEMO_EMAILS = tuple(a[0] for a in ACCOUNTS_DEMO)


def tai_khoan_can_tao(demo: bool = False, mat_khau_admin: str | None = None):
    """Danh sách tài khoản script sẽ tạo. Tách riêng để test không cần CSDL.

    Mặc định chỉ có admin. Mật khẩu admin: tham số > ADMIN_INITIAL_PASSWORD >
    sinh ngẫu nhiên."""
    pw = mat_khau_admin or os.getenv("ADMIN_INITIAL_PASSWORD") or auth.new_temp_password()
    ds = [(ADMIN_EMAIL, "Quản trị hệ thống", "admin", pw, True, [], [], 0)]
    if demo:
        ds.extend(ACCOUNTS_DEMO)
    return ds


def _upsert(conn, dep, tk, *, ghi_de_mat_khau: bool):
    email, name, role, pw, can_rev, depts, heads, quota = tk
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE lower(email)=%s", (email.lower(),))
        row = cur.fetchone()
        if row:
            if not ghi_de_mat_khau:
                return row[0], False
            # Cấp lại mật khẩu: chỉ đụng mật khẩu + mở khoá, giữ nguyên vai,
            # phòng ban, quyền đã chỉnh tay trên web.
            cur.execute("""UPDATE users SET password_hash=%s, must_change_password=true,
                                  active=true WHERE id=%s""",
                        (auth.hash_password(pw), row[0]))
            return row[0], True
        cur.execute("""INSERT INTO users (email,password_hash,full_name,role,can_review,
                                          monthly_quota,must_change_password)
                       VALUES (%s,%s,%s,%s,%s,%s,true) RETURNING id""",
                    (email, auth.hash_password(pw), name, role, can_rev, quota))
        uid = cur.fetchone()[0]
        for dc in depts:
            if dc in dep:
                cur.execute("""INSERT INTO user_departments (user_id,department_id,is_head)
                               VALUES (%s,%s,%s)""", (uid, dep[dc], dc in heads))
    return uid, True


def run(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    demo = "--demo" in argv
    reset_admin = "--reset-admin" in argv
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT code,id FROM departments")
            dep = dict(cur.fetchall())
        print(">> Tài khoản đăng nhập\n")
        print(f"{'EMAIL':<28} {'MẬT KHẨU TẠM':<14} VAI")
        print("-" * 60)
        so_tao = 0
        for tk in tai_khoan_can_tao(demo=demo):
            la_admin = tk[0] == ADMIN_EMAIL
            uid, moi = _upsert(conn, dep, tk,
                               ghi_de_mat_khau=(la_admin and reset_admin) or (not la_admin and demo))
            if moi:
                so_tao += 1
                print(f"{tk[0]:<28} {tk[3]:<14} {tk[2]}")
            else:
                print(f"{tk[0]:<28} {'(đã có, giữ nguyên)':<14} {tk[2]}")
        db.audit(conn, None, "seed_accounts", "users", None,
                 {"count": so_tao, "demo": demo, "reset_admin": reset_admin})
    print()
    if so_tao:
        print("Mật khẩu tạm CHỈ in ra lần này. Người dùng bị bắt đổi mật khẩu ngay lần đăng nhập đầu.")
    if demo:
        print("⚠️  Đã tạo tài khoản MẪU (demo123). Trước khi vận hành thật chạy: "
              "python -m app.ra_soat_tai_khoan --thuc-hien")


if __name__ == "__main__":
    run()
