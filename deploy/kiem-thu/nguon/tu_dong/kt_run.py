# -*- coding: utf-8 -*-
"""Điều phối: python kt_run.py setup | TK PQ CH ... | kb40 | cleanup | all
Chạy: cd ~/hds-ai-full/hds-ai && KT_DIR=/tmp/kt .venv/bin/python /tmp/kt/kt_run.py all"""
import os, sys, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kt_lib import *  # noqa
import kt_setup, kt_cases_1, kt_cases_2, kt_cases_3, kt_kb40

NHOM = {"TK": kt_cases_1.run_TK, "PQ": kt_cases_1.run_PQ, "CH": kt_cases_1.run_CH,
        "KT": kt_cases_2.run_KT, "RR": kt_cases_2.run_RR, "ST": kt_cases_2.run_ST, "BM": kt_cases_2.run_BM,
        "KHO": kt_cases_3.run_KHO, "DN": kt_cases_3.run_DN, "TH": kt_cases_3.run_TH, "WEB": kt_cases_3.run_WEB,
        "KH": kt_cases_3.run_KH, "API": kt_cases_3.run_API, "QT": kt_cases_3.run_QT, "HT": kt_cases_3.run_HT,
        "PNF": kt_cases_3.run_PNF, "CHUA": kt_cases_3.run_CHUA,
        "MOI1": kt_cases_1.run_MOI_1, "MOI3": kt_cases_3.run_MOI_3}
THU_TU = ["TK", "PQ", "CH", "KT", "RR", "ST", "BM", "KHO", "DN", "TH", "WEB", "KH", "API", "QT", "HT", "PNF", "CHUA", "MOI1", "MOI3"]


def cleanup():
    st = load_state()
    ad = kt_setup.admin()
    don = []
    # tài khoản thử: KHOÁ Ở CUỐI hàm — khoá trước thì các bước xoá hội thoại /
    # nháp / lead (gọi BẰNG chính tài khoản thử) bị 401 và không dọn được gì.
    for ma, t in st.get("tk", {}).items():
        if t.get("id"):
            ad.j("PATCH", f"/users/{t['id']}", json={"active": True})
    # khoá tích hợp
    for k, v in (st.get("api_keys") or {}).items():
        if v.get("id"):
            s, _ = ad.j("DELETE", f"/khoa-tich-hop/{v['id']}")
            don.append(f"thu hồi khoá {k}={s}")
    # tài liệu thử: chim mồi, DN, TH, CRM, KHO-08
    ids = [c.get("document_id") for c in st.get("canary", {}).values()] + [st.get("dn01_doc"), st.get("dn02_doc"), st.get("th01_doc"), st.get("th02_doc")] + (st.get("don") or [])
    s, docs = ad.j("GET", "/documents?q=KIEMTHU&limit=50")
    ids += [d["id"] for d in docs] if s == 200 else []
    s, docs = ad.j("GET", "/documents?q=Hỏi đáp&limit=100")
    ids += [d["id"] for d in docs if "KIỂM THỬ" in (d.get("summary") or "") or "KIỂM THỬ" in (d.get("title") or "")] if s == 200 else []
    s, items = ad.j("GET", "/kho/tim?q=RR0&limit=50")
    ids += [i.get("document_id") for i in items if (i.get("ten") or "").startswith(("RR04_KT", "RR01_KT"))] if s == 200 else []
    s, items = ad.j("GET", "/kho/tim?q=KIEMTHU&limit=50")
    ids += [i.get("document_id") for i in items if i.get("document_id")] if s == 200 else []
    for did in sorted({i for i in ids if i}):
        s, d = ad.j("POST", "/kho/go", json={"document_id": did})
        don.append(f"gỡ #{did}={s}")
    # bộ mẫu
    if st.get("bm_id"):
        s, _ = ad.j("DELETE", f"/bo-mau/{st['bm_id']}")
        don.append(f"xoá bộ mẫu={s}")
    # hội thoại + bản nháp + note của các tài khoản thử (mỗi tài khoản tự xoá)
    for ma in ("CV", "TP", "TL", "QT", "KA", "KB"):
        try:
            u = kt_setup.nguoi(ma)
        except Exception:
            continue
        s, convs = u.j("GET", "/conversations?kind=all&limit=500")
        n = 0
        for c in (convs if isinstance(convs, list) else []):
            if u.delete(f"/conversations/{c['id']}").status_code == 200:
                n += 1
        s, ds = u.j("GET", "/drafts?limit=200")
        m = 0
        for d in (ds.get("items") or []) if isinstance(ds, dict) else []:
            if kt_setup.admin().delete(f"/drafts/{d['id']}").status_code == 200:
                m += 1
        s, hs = u.j("GET", "/ho-so-da-luu")
        for h in (hs.get("items") or []) if isinstance(hs, dict) else []:
            u.delete(f"/ho-so-da-luu/{h['ma']}")
        don.append(f"{ma}: xoá {n} hội thoại, {m} nháp")
    # lead: chỉ đánh dấu bỏ qua
    if st.get("lead_id"):
        s, _ = kt_setup.nguoi("QT").j("PATCH", f"/leads/{st['lead_id']}", json={"status": "bo_qua", "note": "KIỂM THỬ — bỏ qua"})
        don.append(f"lead bỏ qua={s}")
    for ma, t in st.get("tk", {}).items():
        if t.get("id"):
            s, _ = ad.j("PATCH", f"/users/{t['id']}", json={"active": False})
            don.append(f"khoá {t['email']}={s}")
    # mật khẩu thử trong state
    for t in st.get("tk", {}).values():
        t.pop("pw", None)
    save_state(st)
    for f in ("big.txt", "virus.exe"):
        try:
            os.remove(os.path.join(KT_DIR, f))
        except Exception:
            pass
    log("DỌN: " + "; ".join(don))
    return don


if __name__ == "__main__":
    load_kq()
    args = sys.argv[1:] or ["all"]
    st = load_state()
    st.setdefault("admin_id", 1)
    save_state(st)
    t0 = time.time()
    for a in args:
        if a == "setup":
            kt_setup.setup()
        elif a == "all":
            kt_setup.setup()
            for n in THU_TU:
                log(f"===== NHÓM {n}")
                try:
                    NHOM[n]()
                except Exception as e:  # noqa: BLE001 — một nhóm hỏng không dừng cả lượt
                    log(f"NHÓM {n} LỖI: {e!r}")
            kt_kb40.run_KB40()
        elif a == "kb40":
            kt_kb40.run_KB40()
        elif a.startswith("kb40:"):
            kt_kb40.run_KB40(chi=a.split(":", 1)[1].split(","))
        elif a == "cleanup":
            cleanup()
        elif a in NHOM:
            log(f"===== NHÓM {a}")
            try:
                NHOM[a]()
            except Exception as e:  # noqa: BLE001
                log(f"NHÓM {a} LỖI: {e!r}")
        else:
            print("không hiểu:", a)
    tong = {}
    for k in load_kq():
        tong[k["ket_qua"]] = tong.get(k["ket_qua"], 0) + 1
    log(f"XONG {args} sau {int(time.time()-t0)}s — {tong}")
