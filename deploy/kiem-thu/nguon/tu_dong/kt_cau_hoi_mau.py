# -*- coding: utf-8 -*-
"""Chạy THẬT bộ câu hỏi mẫu 05/10/2026 (cau_hoi_mau.py + 24 tình huống KB) qua
API máy chủ, như nhân viên gõ trên web — có sinh câu trả lời, không chỉ đo nguồn.

    cd ~/hds-ai-full/hds-ai
    KT_DIR=/tmp/kt .venv/bin/python /tmp/kt/kt_cau_hoi_mau.py chay      # ~2 giờ, chạy lại được (bỏ câu đã xong)
    KT_DIR=/tmp/kt .venv/bin/python /tmp/kt/kt_cau_hoi_mau.py don       # xoá hội thoại/nháp thử, khoá tài khoản

Tài khoản: kt.banqt (Ban QT) cho câu "Mọi người", kt.troly (Trợ lý) cho câu phân
quyền, kênh website (không đăng nhập) cho M13.3. Mỗi câu một hội thoại mới; M6.x
hỏi tiếp trong hội thoại của câu gốc; M12.x tải tệp mẫu vào hội thoại tab Kiểm
tra pháp lý. Kết quả: $KT_DIR/cau_hoi_mau_kq.json (ghi sau từng câu).
"""
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from kt_lib import User, mint, log, dieu_list, mat_khau_moi, KT_DIR  # noqa: E402
import cau_hoi_mau as Q  # noqa: E402
import kb_cases  # noqa: E402

KQ_F = os.path.join(KT_DIR, "cau_hoi_mau_kq.json")
DU_LIEU = os.path.expanduser("~/hds-ai-full/deploy/kiem-thu/du-lieu-mau")
TK = {"QT": "kt.banqt@hdslaw.vn", "TL": "kt.troly@hdslaw.vn"}


def doc_kq():
    try:
        return json.load(open(KQ_F, encoding="utf-8"))
    except Exception:
        return {"cau": {}, "tk": {}}


def ghi_kq(kq):
    tmp = KQ_F + ".tmp"
    json.dump(kq, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, KQ_F)


def admin():
    u = User("admin", token=mint(1, "admin"), ip="10.77.0.1")
    s, me = u.j("GET", "/auth/me")
    assert s == 200 and me.get("role") == "admin", f"token admin hỏng: {s} {me}"
    return u


def mo_tai_khoan(kq):
    """Mở khoá kt.banqt / kt.troly; còn cờ mật khẩu tạm thì đổi như lần đầu đăng nhập."""
    ad = admin()
    s, users = ad.j("GET", "/users")
    by = {u["email"]: u for u in users}
    for ma, email in TK.items():
        u = by.get(email)
        assert u, f"thiếu tài khoản thử {email} — chạy kt_setup.py trước"
        ad.j("PATCH", f"/users/{u['id']}", json={"active": True})
        kq["tk"][ma] = {"id": u["id"], "role": u["role"], "ip": f"10.77.5.{len(kq['tk']) + 1}"}
        nd = nguoi(kq, ma)
        s, me = nd.j("GET", "/auth/me")
        s2, _ = nd.j("GET", "/conversations?kind=all&limit=1")
        if s2 != 200:
            s3, d = ad.j("POST", f"/users/{u['id']}/reset-password", json={})
            tam = d.get("mat_khau_tam") or d.get("password")
            s4, _ = nd.j("POST", "/auth/change-password",
                         json={"old_password": tam, "new_password": mat_khau_moi()})
            log(f"{ma}: đổi mật khẩu tạm → {s3}/{s4}")
        log(f"{ma} #{u['id']} {u['role']} mở → /auth/me {s}")
    ghi_kq(kq)


def nguoi(kq, ma):
    t = kq["tk"][ma]
    return User(ma, token=mint(t["id"], t["role"]), ip=t["ip"])


def gon(d):
    """Phần cần giữ của một câu trả lời API."""
    nguon = []
    for s in d.get("sources") or []:
        nguon.append({k: s.get(k) for k in ("n", "kind", "document_id", "title", "doc_type",
                                             "section_title", "so_hieu", "attachment_name")
                      if s.get(k) is not None})
    return {"status": d.get("_status"), "giay": d.get("_giay"), "answer": d.get("answer") or d.get("_text") or d.get("detail"),
            "answer_mode": d.get("answer_mode"), "grounding_status": d.get("grounding_status"),
            "message_id": d.get("message_id"), "conversation_id": d.get("conversation_id"),
            "nguon": nguon, "timings": {k: v for k, v in (d.get("timings") or {}).items()
                                         if k in ("tong_ms", "chuan_bi_ms", "ai_ms", "gen_tokens", "model")}}


def ban_nhap_moi(u, truoc):
    """Bản nháp mới sinh từ lệnh soạn trong chat (nếu có): tiêu đề + nội dung."""
    s, ds = u.j("GET", "/drafts?limit=20")
    items = ds.get("items") or [] if isinstance(ds, dict) else []
    moi = [x for x in items if x.get("id") not in truoc]
    if not moi:
        return None
    dr = moi[0]
    s, nd = u.j("GET", f"/drafts/{dr['id']}")
    md = ((nd.get("latest_version") or {}).get("content_markdown") or "") if s == 200 else ""
    return {"id": dr["id"], "title": dr.get("title"), "noi_dung": md[:6000], "dai": len(md)}


def id_ban_nhap(u):
    s, ds = u.j("GET", "/drafts?limit=200")
    return {x.get("id") for x in (ds.get("items") or [])} if isinstance(ds, dict) else set()


def chay():
    kq = doc_kq()
    if not kq.get("tk"):
        mo_tai_khoan(kq)
    qt, tl = nguoi(kq, "QT"), nguoi(kq, "TL")
    web = User("web", ip="10.77.6.9")
    ad = admin()
    s, cfg = qt.j("GET", "/ai-ngoai/cau-hinh")
    kq["ai_ngoai"] = cfg
    ghi_kq(kq)

    def xong(ma):
        return ma in kq["cau"] and kq["cau"][ma].get("status") == 200

    def luu(ma, loai, cau, rec):
        rec.update({"ma": ma, "loai": loai, "cau": cau})
        kq["cau"][ma] = rec
        ghi_kq(kq)
        a = re.sub(r"\s+", " ", rec.get("answer") or "")[:140]
        log(f"{ma} [{rec.get('status')} {rec.get('giay')}s {rec.get('grounding_status')}] {a}")

    # ------------------------------------------------------------ tiếng Việt
    for r in Q.VN:
        ma, nhom, ai, lam, cau = r[0], r[1], r[2], r[3], r[4]
        kiem = r[8] or {}
        if xong(ma):
            continue
        try:
            if ma.startswith("M14"):
                goc = {"M14.1": "M1.3", "M14.2": "M2.1", "M14.3": "M9.1"}[ma]
                mid = (kq["cau"].get(goc) or {}).get("message_id")
                if not mid:
                    luu(ma, "vn", cau, {"status": 0, "answer": f"BỎ QUA: câu gốc {goc} không có message_id"})
                    continue
                path = f"/messages/{mid}/ai-soat" if ma != "M14.2" else f"/messages/{mid}/cau-tra-loi-khac"
                t = time.time()
                r = qt.post(path, json={}, timeout=420)      # luồng SSE: status… → done
                su_kien = []
                for dong in r.text.splitlines():
                    if dong.startswith("data:"):
                        try:
                            su_kien.append(json.loads(dong[5:].strip()))
                        except Exception:
                            pass
                cuoi = next((e for e in reversed(su_kien) if e.get("type") in ("done", "error")), None)
                van = "".join(e.get("text") or "" for e in su_kien if e.get("type") == "delta")
                ra = cuoi if cuoi else (r.text[:1500] or "")
                luu(ma, "vn", cau, {"status": r.status_code, "giay": round(time.time() - t, 1), "goc": goc,
                                    "answer": (van + "\n\n" if van else "") + json.dumps(ra, ensure_ascii=False)[:4000]})
                continue
            if ma.startswith("M6."):
                goc = {"M6.1": "M1.1", "M6.2": "M1.7", "M6.3": "M1.4"}[ma]
                conv = (kq["cau"].get(goc) or {}).get("conversation_id")
                d = qt.chat(cau, conv=conv)
                luu(ma, "vn", cau, {**gon(d), "goc": goc})
                continue
            if ma == "M13.1":
                d = tl.chat(cau, conv=tl.new_conv())
                luu(ma, "vn", cau, {**gon(d), "tai_khoan": "kt.troly (Trợ lý)"})
                continue
            if ma == "M13.3":
                d = web.chat(cau, channel="public")
                luu(ma, "vn", cau, {**gon(d), "tai_khoan": "website (không đăng nhập)"})
                continue
            if ma in ("M10.1", "M10.2"):
                ten = "Sở hữu trí tuệ" if ma == "M10.1" else "Lao động"
                so = "11/VBHN-VPQH" if ma == "M10.1" else "45/2019/QH14"
                s, docs = ad.j("GET", f"/documents?q={so}&doc_type=law&limit=20")
                hit = [x for x in docs if ten.lower() in ((x.get("trich_yeu") or "") + (x.get("title") or "")).lower()] if s == 200 else []
                if not hit:
                    luu(ma, "vn", cau, {"status": 0, "answer": f"BỎ QUA: không tìm được văn bản {ten} để chọn nguồn"})
                    continue
                d = qt.chat(cau, conv=qt.new_conv(), source_document_ids=[hit[0]["id"]])
                luu(ma, "vn", cau, {**gon(d), "chon_nguon": f"#{hit[0]['id']} {hit[0].get('title')}"})
                continue
            if ma.startswith("M12.") and ma not in ("M12.6", "M12.7"):
                tep = {"M12.1": "RR03_HDLD_vi_pham_nguong.docx", "M12.2": "RR04_HD_dich_vu_hop_le_DOI_CHUNG.docx",
                       "M12.3": "RR05_HD_dieu_khoan_mot_chieu.docx", "M12.4": "RR01_HD_vay_lai_3pt_thang.docx",
                       "M12.5": "EN01_service_agreement.txt"}[ma]
                conv = qt.new_conv("legal")
                s, up = qt.upload_temp(conv, os.path.join(DU_LIEU, tep))
                mode = "du_bao_tranh_tung" if ma == "M12.4" else "legal_review"
                d = qt.chat(cau, conv=conv, use_temp=True, mode=mode)
                luu(ma, "vn", cau, {**gon(d), "dinh_kem": f"{tep} → {s} {str(up.get('status') or '')}", "mode": mode})
                continue
            if ma in ("M12.6", "M12.7"):
                mode = "du_bao_tranh_tung" if ma == "M12.6" else "chuan_bi_phien_toa"
                d = qt.chat(cau, conv=qt.new_conv("legal"), mode=mode)
                luu(ma, "vn", cau, {**gon(d), "mode": mode})
                continue
            if ma.startswith("M11."):
                truoc = id_ban_nhap(qt)
                d = qt.chat(cau, conv=qt.new_conv())
                luu(ma, "vn", cau, {**gon(d), "ban_nhap": ban_nhap_moi(qt, truoc)})
                continue
            d = qt.chat(cau, conv=qt.new_conv(), **({"mode": kiem["mode"]} if kiem.get("mode") else {}))
            luu(ma, "vn", cau, gon(d))
        except Exception as e:  # noqa: BLE001
            luu(ma, "vn", cau, {"status": -1, "answer": f"LỖI BỘ CHẠY: {e!r}"})

    # ------------------------------------------------------------ 24 tình huống KB
    for k in kb_cases.load():
        if k["id"] in Q.KB_DA_DUNG:
            continue
        ma = "KB" + k["id"]
        if xong(ma):
            continue
        try:
            d = qt.chat(k["cau_hoi"], conv=qt.new_conv())
            luu(ma, "kb", k["cau_hoi"], gon(d))
        except Exception as e:  # noqa: BLE001
            luu(ma, "kb", k["cau_hoi"], {"status": -1, "answer": f"LỖI BỘ CHẠY: {e!r}"})

    # ------------------------------------------------------------ tiếng Anh (SEC)
    for r in Q.EN:
        ma, cau, kiem = r[0], r[3], r[6] or {}
        if xong(ma):
            continue
        cau_gui = re.sub(r"^\([^)]*\)\s*", "", cau)     # bỏ ghi chú "(Đăng nhập …)"
        try:
            u = tl if kiem.get("vai") == "tro_ly" else qt
            extra = {"source_document_ids": [kiem["doc_id"]]} if kiem.get("doc_id") else {}
            truoc = id_ban_nhap(u) if ma.startswith("EN-E") else None
            d = u.chat(cau_gui, conv=u.new_conv(), **extra)
            rec = gon(d)
            if extra:
                rec["chon_nguon"] = f"#{kiem['doc_id']} {r[2]}"
            if u is tl:
                rec["tai_khoan"] = "kt.troly (Trợ lý)"
            if truoc is not None:
                rec["ban_nhap"] = ban_nhap_moi(u, truoc)
            luu(ma, "en", cau_gui, rec)
        except Exception as e:  # noqa: BLE001
            luu(ma, "en", cau_gui, {"status": -1, "answer": f"LỖI BỘ CHẠY: {e!r}"})
    kq["xong_luc"] = time.strftime("%Y-%m-%d %H:%M:%S")
    ghi_kq(kq)
    log("XONG bộ câu hỏi mẫu")


def don():
    """Xoá hội thoại + bản nháp của hai tài khoản thử rồi KHOÁ lại (khoá cuối cùng)."""
    kq = doc_kq()
    ad = admin()
    for ma in kq.get("tk", {}):
        u = nguoi(kq, ma)
        s, convs = u.j("GET", "/conversations?kind=all&limit=500")
        n = sum(1 for c in (convs if isinstance(convs, list) else [])
                if u.delete(f"/conversations/{c['id']}").status_code == 200)
        m = sum(1 for x in id_ban_nhap(u) if x and ad.delete(f"/drafts/{x}").status_code == 200)
        log(f"dọn {ma}: xoá {n} hội thoại, {m} bản nháp")
    for ma, t in kq.get("tk", {}).items():
        s, _ = ad.j("PATCH", f"/users/{t['id']}", json={"active": False})
        log(f"khoá {TK[ma]} → {s}")


if __name__ == "__main__":
    {"chay": chay, "don": don}[sys.argv[1]]()
