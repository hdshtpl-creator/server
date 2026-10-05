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


def _van_ban(s):
    vb = []
    for k in ("LDN", "Luật Doanh nghiệp", "Luật Đầu tư", "BLDS", "LTM", "Luật Thương mại", "BLLĐ", "Bộ luật Lao động",
              "BLTTDS", "Tố tụng dân sự", "Luật SHTT", "Sở hữu trí tuệ", "NĐ 01/2021", "Nghị định 01/2021", "NĐ 31/2021",
              "Nghị quyết 01/2014", "QĐ 27/2018", "Luật Đất đai", "Luật Quản lý thuế", "NHNN", "Hiến pháp"):
        if k.lower() in s.lower():
            vb.append(k)
    return vb


VB_ALIAS = {"LDN": ["doanh nghiệp"], "Luật Doanh nghiệp": ["doanh nghiệp"], "Luật Đầu tư": ["đầu tư"], "BLDS": ["dân sự"],
            "LTM": ["thương mại"], "Luật Thương mại": ["thương mại"], "BLLĐ": ["lao động"], "Bộ luật Lao động": ["lao động"],
            "BLTTDS": ["tố tụng dân sự"], "Tố tụng dân sự": ["tố tụng dân sự"], "Luật SHTT": ["sở hữu trí tuệ"], "Sở hữu trí tuệ": ["sở hữu trí tuệ"],
            "NĐ 01/2021": ["01/2021"], "Nghị định 01/2021": ["01/2021"], "NĐ 31/2021": ["31/2021"], "Nghị quyết 01/2014": ["01/2014"],
            "QĐ 27/2018": ["27/2018"], "Luật Đất đai": ["đất đai"], "Luật Quản lý thuế": ["quản lý thuế"], "NHNN": ["ngân hàng nhà nước"], "Hiến pháp": ["hiến pháp"]}


def cham(k, a, d):
    """ĐÚNG / MỘT PHẦN / SAI (sơ bộ, máy chấm theo số Điều + tên văn bản; luật sư chấm lại)."""
    can = _dieu_bat_buoc(k["dieu"])
    vb = _van_ban(k["dieu"])
    co_dieu = [n for n in can if dieu(a, n)]
    co_vb = [v for v in vb if any(has(a, al) for al in VB_ALIAS.get(v, [v]))]
    tu_choi = d.get("answer_mode") == "insufficient_evidence" or d.get("grounding_status") == "uncited_blocked"
    if tu_choi:
        return "MỘT PHẦN", f"bot từ chối có lý do (kho thiếu) — Điều dẫn {dieu_list(a)[:6]}"
    if not can:  # tiêu chí không nêu số điều → chấm theo văn bản + có nguồn
        if co_vb and cites(a):
            return "MỘT PHẦN", f"không có số Điều tiêu chí; dẫn văn bản {co_vb}, Điều {dieu_list(a)[:8]} — luật sư chấm nội dung"
        return "SAI", f"không dẫn văn bản tiêu chí ({vb}); Điều dẫn {dieu_list(a)[:8]}"
    if len(co_dieu) == len(can) and cites(a):
        return "ĐÚNG", f"đủ Điều {co_dieu}, văn bản {co_vb}"
    if co_dieu:
        return "MỘT PHẦN", f"dẫn {co_dieu}/{can}, thiếu {sorted(set(can)-set(co_dieu))}; văn bản {co_vb}"
    return "SAI", f"không dẫn Điều nào trong {can}; Điều bot dẫn {dieu_list(a)[:8]}; văn bản {co_vb}"


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
