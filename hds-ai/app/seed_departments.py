"""
seed_departments.py — Nạp 4 bộ phận + ma trận quyền theo bảng nhân sự HDS.
Chạy MỘT LẦN sau khi init_db: python -m app.seed_departments

Ma trận lấy từ file HDS_PHAN_QUYEN_NHAN_SU.xlsx của khách.
Muốn đổi quyền về sau: sửa dữ liệu bảng access_rules, KHÔNG sửa code.
"""
from app import db

DEPARTMENTS = [
    ("dn-dt", "Doanh nghiệp - Đầu tư"),
    ("htpl-tvtx", "Hỗ trợ pháp lý - Tư vấn thường xuyên"),
    ("tranh-tung", "Tranh tụng"),
    ("shtt", "Sở hữu trí tuệ"),
]

# Các loại tài liệu.
# 'cong_no' KHÔNG có trong danh sách này: nó không đi theo ma trận phòng ban mà
# theo quyền riêng từng người (users.can_view_finance), chặn ở RLS.
DOC_TYPES = ["law", "ban_an", "an_le", "mau_hd", "nhan_hieu", "thu_mau",
             "quy_trinh", "ho_so_ns", "ho_so_kh", "advisory", "contract", "filing", "other"]

# Ba gói khách hàng — quyết định khách được TRA CỨU loại tài liệu nào qua cổng
# hỏi đáp và khoá API. Đây là phạm vi gói dịch vụ, không phải ranh giới bảo mật:
# việc khách A không thấy dữ liệu khách B do RLS lo, độc lập hoàn toàn với đây.
#
# Hồ sơ của chính khách (ho_so_kh, contract, advisory, filing) chỉ mở từ gói
# Plus trở lên; gói Free chỉ tra cứu tri thức pháp luật chung.
CLIENT_TIERS = {
    "client_free": ["law"],
    "client_plus": ["law", "quy_trinh", "thu_mau",
                    "ho_so_kh", "contract", "advisory", "filing"],
    "client_pro": ["law", "quy_trinh", "thu_mau", "mau_hd", "an_le",
                   "ho_so_kh", "contract", "advisory", "filing"],
}

# Ma trận: (role_level, department_code, doc_type, can_view, can_open)
# '*' = áp cho mọi phòng.
# Quy tắc từ bảng khách:
#   Ban QT: xem + mở tất cả (không cần dòng — mặc định thấy hết, xử lý ở app.is_banqt)
#   Trưởng BPh: mọi loại nội bộ + hồ sơ khách phòng mình
#   Chuyên viên: luật/thư mẫu/quy trình OK; bản án KHÔNG; mẫu HD & nhãn hiệu tùy phòng
#   Trợ lý: chỉ luật/thư mẫu/quy trình; KHÔNG hồ sơ khách, KHÔNG bản án/mẫu HD/nhãn hiệu


def build_rules():
    rules = []

    def add(role, dept, dtype, view=True, open_=True):
        rules.append((role, dept, dtype, view, open_))

    # ---- TRƯỞNG BỘ PHẬN: xem + mở mọi loại (hồ sơ khách lọc theo phòng ở RLS) ----
    for dt in DOC_TYPES:
        add("truong_bph", "*", dt, True, True)

    # ---- CHUYÊN VIÊN ----
    common_open = ["law", "an_le", "thu_mau", "quy_trinh", "advisory",
                   "contract", "filing", "ho_so_kh", "other"]
    for dt in DOC_TYPES:
        if dt == "ban_an":
            add("chuyen_vien", "*", dt, True, False)      # thấy tên, không mở
        elif dt == "mau_hd":
            # DN-ĐT không mở; HTPL & Tranh tụng mở được
            add("chuyen_vien", "dn-dt", dt, True, False)
            add("chuyen_vien", "htpl-tvtx", dt, True, True)
            add("chuyen_vien", "tranh-tung", dt, True, True)
            add("chuyen_vien", "shtt", dt, True, False)
        elif dt == "nhan_hieu":
            # chỉ SHTT mở được
            add("chuyen_vien", "shtt", dt, True, True)
            for d in ("dn-dt", "htpl-tvtx", "tranh-tung"):
                add("chuyen_vien", d, dt, True, False)
        elif dt == "ho_so_ns":
            add("chuyen_vien", "*", dt, True, False)       # chỉ hồ sơ NS cá nhân (xử lý riêng)
        else:
            add("chuyen_vien", "*", dt, True, dt in common_open)

    # ---- TRỢ LÝ: chỉ nội bộ chung, KHÔNG hồ sơ khách ----
    troly_open = {"law", "an_le", "thu_mau", "quy_trinh", "other"}
    for dt in DOC_TYPES:
        if dt == "ho_so_kh":
            add("tro_ly", "*", dt, True, False)   # thấy tên (che ở app), không mở
        elif dt in ("ban_an", "mau_hd", "nhan_hieu", "ho_so_ns"):
            add("tro_ly", "*", dt, True, False)
        else:
            add("tro_ly", "*", dt, True, dt in troly_open)

    # ---- BA GÓI KHÁCH HÀNG ----
    for tier, allowed in CLIENT_TIERS.items():
        for dt in DOC_TYPES:
            ok = dt in allowed
            add(tier, "*", dt, ok, ok)

    return rules


def run():
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            print(">> Nạp 4 bộ phận...")
            dep_ids = {}
            for code, name in DEPARTMENTS:
                cur.execute("""INSERT INTO departments (code,name) VALUES (%s,%s)
                               ON CONFLICT (code) DO UPDATE SET name=EXCLUDED.name
                               RETURNING id""", (code, name))
                dep_ids[code] = cur.fetchone()[0]
                print(f"   [{dep_ids[code]}] {code} — {name}")

            print(">> Nạp ma trận quyền...")
            cur.execute("DELETE FROM access_rules")
            rules = build_rules()
            for r in rules:
                cur.execute("""INSERT INTO access_rules
                    (role_level,department_code,doc_type,can_view,can_open)
                    VALUES (%s,%s,%s,%s,%s)
                    ON CONFLICT (role_level,department_code,doc_type)
                    DO UPDATE SET can_view=EXCLUDED.can_view, can_open=EXCLUDED.can_open""", r)
            print(f"   {len(rules)} quy tắc.")
        db.audit(conn, None, "seed_departments", "departments", None,
                 {"depts": len(DEPARTMENTS), "rules": len(rules)})
    print("\nXong. Ban QT/Admin thấy tất cả; các cấp khác theo ma trận + phòng.")
    print("Đổi quyền sau này: sửa bảng access_rules, không sửa code.")


if __name__ == "__main__":
    run()
