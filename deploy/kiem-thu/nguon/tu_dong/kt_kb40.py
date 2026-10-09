# -*- coding: utf-8 -*-
"""40 kịch bản pháp lý của HDS — mỗi kịch bản một hội thoại mới, chấm sơ bộ theo số Điều."""
import os, re, json, time
from kt_lib import *  # noqa
from kt_setup import nguoi
import kb_cases

KB_F = os.path.join(KT_DIR, "kb40_ket_qua.json")

# Điều bắt buộc (số) + tên văn bản gợi ý — rút từ cột 'Phải dẫn' (kb_cases.DIEU)
def _dieu_bat_buoc(s):
    nums = set()
    for m in re.finditer(r"Điều\s+([\d ,/]+)", s):
        for x in re.split(r"[ ,/]+", m.group(1)):
            if x.isdigit():
                nums.add(int(x))
    return sorted(nums)


def _nhom_dieu(s):
    """Các NHÓM điều bắt buộc: "Điều 68 / Điều 112" là MỘT nhóm (dẫn một trong
    hai là đủ — 07/10/2026 câu 1.10 dẫn đúng Điều 68 cho công ty TNHH mà bị chấm
    thiếu Điều 112 của công ty cổ phần); các điều còn lại mỗi điều một nhóm."""
    nhom = []
    for m in re.finditer(r"Điều\s+(\d+)\s*/\s*Điều\s+(\d+)", s):
        nhom.append({int(m.group(1)), int(m.group(2))})
    con = re.sub(r"Điều\s+\d+\s*/\s*Điều\s+\d+", " ", s)
    nhom += [{n} for n in _dieu_bat_buoc(con)]
    return nhom


def _van_ban(s):
    vb = []
    for k in ("LDN", "Luật Doanh nghiệp", "Luật Đầu tư", "BLDS", "LTM", "Luật Thương mại", "BLLĐ", "Bộ luật Lao động",
              "BLTTDS", "Tố tụng dân sự", "Luật SHTT", "Sở hữu trí tuệ", "NĐ 01/2021", "Nghị định 01/2021", "NĐ 31/2021",
              "NĐ 168/2025", "NĐ 96/2026",
              "Nghị quyết 01/2014", "QĐ 27/2018", "Luật Đất đai", "Luật Quản lý thuế", "NHNN", "Hiến pháp"):
        if k.lower() in s.lower():
            vb.append(k)
    return vb


VB_ALIAS = {"LDN": ["doanh nghiệp"], "Luật Doanh nghiệp": ["doanh nghiệp"], "Luật Đầu tư": ["đầu tư"], "BLDS": ["dân sự"],
            "LTM": ["thương mại"], "Luật Thương mại": ["thương mại"], "BLLĐ": ["lao động"], "Bộ luật Lao động": ["lao động"],
            "BLTTDS": ["tố tụng dân sự"], "Tố tụng dân sự": ["tố tụng dân sự"], "Luật SHTT": ["sở hữu trí tuệ"], "Sở hữu trí tuệ": ["sở hữu trí tuệ"],
            "NĐ 01/2021": ["01/2021"], "Nghị định 01/2021": ["01/2021"], "NĐ 31/2021": ["31/2021"], "Nghị quyết 01/2014": ["01/2014"],
            "QĐ 27/2018": ["27/2018"], "Luật Đất đai": ["đất đai"], "Luật Quản lý thuế": ["quản lý thuế"], "NHNN": ["ngân hàng nhà nước"], "Hiến pháp": ["hiến pháp"]}


HANG = {"ĐÚNG": 3, "MỘT PHẦN": 2, "BỎ QUA": 1, "SAI": 0}


def _cham_theo(tieu_chi, a, d):
    nhom = _nhom_dieu(tieu_chi)
    vb = _van_ban(tieu_chi)
    co_vb = [v for v in vb if any(has(a, al) for al in VB_ALIAS.get(v, [v]))]
    tu_choi = d.get("answer_mode") == "insufficient_evidence" or d.get("grounding_status") == "uncited_blocked"
    if tu_choi:
        return "MỘT PHẦN", f"bot từ chối có lý do (kho thiếu) — Điều dẫn {dieu_list(a)[:6]}"
    if not nhom:  # tiêu chí không nêu số điều → máy không chấm nổi nội dung
        if not vb:
            return "BỎ QUA", f"tiêu chí không nêu điều / văn bản — LUẬT SƯ CHẤM; Điều bot dẫn {dieu_list(a)[:8]}"
        if co_vb and cites(a):
            return "MỘT PHẦN", f"không có số Điều tiêu chí; dẫn văn bản {co_vb}, Điều {dieu_list(a)[:8]} — luật sư chấm nội dung"
        return "SAI", f"không dẫn văn bản tiêu chí ({vb}); Điều dẫn {dieu_list(a)[:8]}"
    dat = [g for g in nhom if any(dieu(a, n) for n in g)]
    ten = lambda gs: [sorted(g)[0] if len(g) == 1 else "/".join(map(str, sorted(g))) for g in gs]  # noqa: E731
    if len(dat) == len(nhom) and cites(a):
        return "ĐÚNG", f"đủ Điều {ten(dat)}, văn bản {co_vb}"
    if dat:
        thieu = [g for g in nhom if g not in dat]
        return "MỘT PHẦN", f"dẫn {ten(dat)}/{ten(nhom)}, thiếu {ten(thieu)}; văn bản {co_vb}"
    return "SAI", f"không dẫn Điều nào trong {ten(nhom)}; Điều bot dẫn {dieu_list(a)[:8]}; văn bản {co_vb}"


def cham(k, a, d):
    """ĐÚNG / MỘT PHẦN / SAI / BỎ QUA (sơ bộ, máy chấm theo số Điều + tên văn bản;
    luật sư chấm lại). Chấm theo tiêu chí HDS VÀ theo tiêu chí luật hiện hành
    (kb_cases.DIEU_HIEN_HANH, đề xuất 07/10) — lấy kết quả tốt hơn, ghi rõ."""
    kq, ly_do = _cham_theo(k["dieu"], a, d)
    if k.get("dieu_hien_hanh"):
        kq2, ly_do2 = _cham_theo(k["dieu_hien_hanh"], a, d)
        if HANG[kq2] > HANG[kq]:
            return kq2, f"theo luật hiện hành ({k['dieu_hien_hanh']}): {ly_do2} | theo tiêu chí HDS: {kq}"
    return kq, ly_do


def run_KB40(chi=None):
    cv = nguoi("CV")
    try:
        kq = json.load(open(KB_F, encoding="utf-8"))
    except Exception:
        kq = {}
    for k in kb_cases.load():
        if chi and k["id"] not in chi:
            continue
        if k["id"] in kq and kq[k["id"]].get("status") == 200:
            continue
        d = cv.chat(k["cau_hoi"])
        a = d.get("answer") or ""
        ket, ly_do = cham(k, a, d) if d.get("_status") == 200 else ("CHẶN", str(d.get("detail") or d.get("_text"))[:100])
        kq[k["id"]] = {"status": d.get("_status"), "ket_qua": ket, "ly_do": ly_do, "giay": d.get("_giay"),
                       "grounding": d.get("grounding_status"), "mode": d.get("answer_mode"), "dieu": dieu_list(a)[:15],
                       "nguon": src_titles(d)[:5], "answer": a, "phai_dan": k["dieu"], "cau_hoi": k["cau_hoi"][:200]}
        json.dump(kq, open(KB_F, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        log(f"KB {k['id']}: {ket} ({d.get('_giay')}s) {ly_do[:90]}")
    tong = {}
    for v in kq.values():
        tong[v["ket_qua"]] = tong.get(v["ket_qua"], 0) + 1
    log(f"KB40 xong: {tong}")
    return kq
