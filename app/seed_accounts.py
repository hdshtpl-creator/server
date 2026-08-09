"""
seed_accounts.py — Tạo tài khoản demo để đăng nhập (có mật khẩu mã hóa).
Chạy MỘT LẦN: python -m app.seed_accounts

In ra bảng email + mật khẩu để bạn đăng nhập lúc demo.
Đổi mật khẩu thật trước khi dùng chính thức.
"""
from app import db, auth

# (email, tên, vai, mật khẩu, can_review, [mã phòng], [phòng làm trưởng], quota)
ACCOUNTS = [
    ("admin@hdslaw.vn",   "Quản trị hệ thống", "admin",       "admin123",  True,  [], [], 0),
    ("giamdoc@hdslaw.vn", "Giám đốc (Ban QT)",  "ban_qt",      "demo123",   True,  [], [], 0),
    ("truong.dndt@hdslaw.vn", "Trưởng phòng DN-ĐT", "truong_bph", "demo123", True, ["dn-dt"], ["dn-dt"], 0),
    ("cv.tranhtung@hdslaw.vn", "Chuyên viên Tranh tụng", "chuyen_vien", "demo123", False, ["tranh-tung"], [], 0),
    ("troly@hdslaw.vn",   "Trợ lý",             "tro_ly",      "demo123",   False, ["htpl-tvtx"], [], 0),
]


def run():
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT code,id FROM departments")
            dep = dict(cur.fetchall())
        print(">> Tạo tài khoản demo...\n")
        print(f"{'EMAIL':<28} {'MẬT KHẨU':<12} VAI")
        print("-" * 55)
        for email, name, role, pw, can_rev, depts, heads, quota in ACCOUNTS:
            with conn.cursor() as cur:
                cur.execute("""INSERT INTO users (email,password_hash,full_name,role,can_review,monthly_quota)
                               VALUES (%s,%s,%s,%s,%s,%s)
                               ON CONFLICT (email) DO UPDATE SET
                                 password_hash=EXCLUDED.password_hash, role=EXCLUDED.role,
                                 can_review=EXCLUDED.can_review, full_name=EXCLUDED.full_name
                               RETURNING id""",
                            (email, auth.hash_password(pw), name, role, can_rev, quota))
                uid = cur.fetchone()[0]
                cur.execute("DELETE FROM user_departments WHERE user_id=%s", (uid,))
                for dc in depts:
                    if dc in dep:
                        cur.execute("""INSERT INTO user_departments (user_id,department_id,is_head)
                                       VALUES (%s,%s,%s)""", (uid, dep[dc], dc in heads))
            print(f"{email:<28} {pw:<12} {role}")
        db.audit(conn, None, "seed_accounts", "users", None, {"count": len(ACCOUNTS)})
    print("\nXong. Đăng nhập bằng các tài khoản trên.")
    print("⚠️  Đổi mật khẩu trước khi dùng thật.")


if __name__ == "__main__":
    run()
