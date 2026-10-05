# -*- coding: utf-8 -*-
"""Chuẩn bị môi trường thử trên máy chủ: tài khoản TK-*, khách thử B, 4 chim mồi."""
import os, time
from kt_lib import *  # noqa

CANARY = {
    "CONGKHAI": ("CANARY_CONG_KHAI.docx", "1. VĂN BẢN PHÁP LUẬT", "HDS-CANARY-CONGKHAI-4417"),
    "NOIBO":    ("CANARY_NOI_BO.docx", "6. QUY TRÌNH NỘI BỘ", "HDS-CANARY-NOIBO-2290"),
    "KHACHA":   ("CANARY_KHACH_A.docx", "9. HỒ SƠ KHÁCH HÀNG/0999. KHÁCH THỬ NGHIỆM API (xoá được)", "HDS-CANARY-KHACHA-8812"),
    "KHACHB":   ("CANARY_KHACH_B.docx", "9. HỒ SƠ KHÁCH HÀNG/0998. KHÁCH THỬ NGHIỆM B (xoá được)", "HDS-CANARY-KHACHB-3307"),
}
TK = [  # (mã, email, họ tên, vai, phòng dn-dt id=1, quyền duyệt)
    ("QT", "kt.banqt@hdslaw.vn", "KIỂM THỬ Ban QT", "ban_qt", [], True),
    ("TP", "kt.truongphong@hdslaw.vn", "KIỂM THỬ Trưởng BP", "truong_bph", [1], True),
    ("CV", "kt.chuyenvien@hdslaw.vn", "KIỂM THỬ Chuyên viên", "chuyen_vien", [1], False),
    ("TL", "kt.troly@hdslaw.vn", "KIỂM THỬ Trợ lý", "tro_ly", [1], False),
]


def admin():
    st = load_state()
    return User("admin", token=mint(st.get("admin_id", 1), "admin"), ip="10.77.0.1")


def nguoi(ma):
    """User ảo cho mã TK-xx từ state (token mint theo id/vai)."""
    st = load_state()
    if ma == "AD":
        return admin()
    t = st["tk"][ma]
    return User(ma, token=mint(t["id"], t["role"]), ip=t["ip"])


def doi_mk_lan_dau(ma):
    """Tài khoản còn cờ mật khẩu tạm (03/10: máy chủ chặn mọi API — F-04): đặt
    lại mật khẩu tạm qua admin rồi tự đổi như người dùng thật ở lần đầu."""
    st = load_state()
    ad = admin()
    t = st["tk"][ma]
    s, d = ad.j("POST", f"/users/{t['id']}/reset-password", json={})
    tam = d.get("mat_khau_tam") or d.get("password")
    if s != 200 or not tam:
        log(f"{ma}: reset-password → {s} {str(d)[:120]}")
        return False
    u = User(ma, token=mint(t["id"], t["role"]), ip=t["ip"])
    moi = mat_khau_moi()
    s2, d2 = u.j("POST", "/auth/change-password", json={"old_password": tam, "new_password": moi})
    if s2 == 200:
        t["pw"] = moi
        save_state(st)
    log(f"{ma}: đổi mật khẩu lần đầu → {s2}")
    return s2 == 200


def setup():
    st = load_state()
    ad = admin()
    s, me = ad.j("GET", "/auth/me")
    assert s == 200 and me.get("role") == "admin", f"admin token hỏng: {s} {me}"
    log(f"admin OK: {me.get('name')}")
    st.setdefault("tk", {})
    # --- tài khoản nội bộ
    s, users = ad.j("GET", "/users")
    by_email = {u["email"]: u for u in users}
    for ma, email, ten, role, depts, duyet in TK:
        if email in by_email:
            u = by_email[email]
            if not u["active"]:
                ad.patch(f"/users/{u['id']}", json={"active": True})
            uid = u["id"]
        else:
            pw = mat_khau_moi()
            s, d = ad.j("POST", "/users", json={"email": email, "full_name": ten, "role": role,
                                                 "password": pw, "can_review": duyet, "department_ids": depts})
            assert s == 200, f"tạo {email}: {s} {d}"
            uid = d["user_id"]
            st["tk"].setdefault(ma, {})["pw"] = pw
        st["tk"].setdefault(ma, {}).update({"id": uid, "email": email, "role": role,
                                             "ip": f"10.77.1.{len(st['tk']) + 1}"})
        if duyet:
            ad.post(f"/users/{uid}/review-permission?grant=true")
    save_state(st)
    # --- khách thử B: thư mục có mã trong ngăn 9
    s, d = ad.j("POST", "/kho/thu-muc", json={"path": "9. HỒ SƠ KHÁCH HÀNG", "ten": "0998. KHÁCH THỬ NGHIỆM B (xoá được)"})
    log(f"thư mục khách B: {s} {d}")
    # --- chim mồi
    st.setdefault("canary", {})
    for k, (fn, folder, code) in CANARY.items():
        p = os.path.join(IN, fn)
        with open(p, "rb") as f:
            r = ad.post("/kho/tai-len", data={"path": folder, "auto_approve": "false"},
                        files=[("files", (fn, f))], timeout=300)
        try:
            d = r.json()
        except Exception:
            d = {"_text": r.text[:300]}
        log(f"tải {fn} → {r.status_code} {str(d)[:300]}")
        st["canary"][k] = {"file": fn, "folder": folder, "code": code, "tai_len": d}
    save_state(st)
    # --- chờ học xong + lấy id tài liệu
    def xong():
        s, items = ad.j("GET", "/kho/tim?q=CANARY&limit=50")
        if s != 200:
            return False
        ok = True
        for k, c in st["canary"].items():
            hit = [i for i in items if (i.get("ten") or "") == c["file"]]
            if hit and hit[0].get("trang_thai") in ("da_hoc", "canh_bao", "cho_duyet"):
                c["document_id"] = hit[0].get("document_id")
                c["trang_thai"] = hit[0].get("trang_thai")
                c["approved"] = hit[0].get("approved")
                c["label_verified"] = hit[0].get("label_verified")
            else:
                ok = False
        save_state(st)
        return ok
    doi(xong, 10, 600, "chim mồi học xong")
    # kho/tim có thể không trả document_id → tra qua /documents?q=
    for k, c in st["canary"].items():
        if not c.get("document_id"):
            s, docs = ad.j("GET", f"/documents?q={c['file'].replace('.docx','')}&limit=5")
            if s == 200 and docs:
                c["document_id"] = docs[0]["id"]
    # duyệt nếu còn chờ
    for k, c in st["canary"].items():
        if c.get("document_id") and (c.get("trang_thai") == "cho_duyet" or not (c.get("approved") and c.get("label_verified"))):
            lab = {"doc_type": "law" if k == "CONGKHAI" else ("quy_trinh" if k == "NOIBO" else "ho_so_kh"),
                   "access_level": "public" if k == "CONGKHAI" else ("internal" if k == "NOIBO" else "client")}
            ad.post(f"/review/{c['document_id']}/approve", json=lab)
    log("chim mồi: " + ", ".join(f"{k}={c.get('trang_thai')}#{c.get('document_id')}" for k, c in st["canary"].items()))
    # --- khách: id A (0999) + B (0998)
    s, clients = ad.j("GET", "/clients")
    code = {c.get("code"): c for c in clients}
    st["khach"] = {"A": code.get("0999", {}).get("id"), "B": code.get("0998", {}).get("id"),
                   "A_ten": code.get("0999", {}).get("name"), "B_ten": code.get("0998", {}).get("name")}
    log(f"khách A={st['khach']['A']} B={st['khach']['B']}")
    st["khach_A_phong_cu"] = None
    # --- tài khoản khách
    for ma, email, ten, cid in (("KA", "kt.khacha@hdslaw.vn", "KIỂM THỬ Khách A", st["khach"]["A"]),
                                ("KB", "kt.khachb@hdslaw.vn", "KIỂM THỬ Khách B", st["khach"]["B"])):
        if not cid:
            log(f"BỎ: không có client cho {ma}")
            continue
        s, users = ad.j("GET", "/users")
        u = next((x for x in users if x["email"] == email), None)
        if u:
            ad.patch(f"/users/{u['id']}", json={"active": True, "client_id": cid})
            uid = u["id"]
        else:
            pw = mat_khau_moi()
            s, d = ad.j("POST", "/users", json={"email": email, "full_name": ten, "role": "client_plus",
                                                 "password": pw, "client_id": cid})
            assert s == 200, f"tạo {email}: {s} {d}"
            uid = d["user_id"]
            st["tk"].setdefault(ma, {})["pw"] = pw
        st["tk"].setdefault(ma, {}).update({"id": uid, "email": email, "role": "client_plus",
                                             "ip": f"10.77.2.{1 if ma == 'KA' else 2}", "client_id": cid})
    save_state(st)
    # --- 03/10: đổi mật khẩu tạm cho mọi tài khoản thử (máy chủ chặn mọi API khi
    # còn cờ mật khẩu tạm — F-04), đúng như người dùng thật ở lần đăng nhập đầu
    for ma in ("QT", "TP", "CV", "TL", "KA", "KB"):
        if ma in st.get("tk", {}):
            doi_mk_lan_dau(ma)
    st = load_state()
    log("SETUP XONG: " + ", ".join(f"{k}#{v['id']}" for k, v in st["tk"].items()))


if __name__ == "__main__":
    setup()
