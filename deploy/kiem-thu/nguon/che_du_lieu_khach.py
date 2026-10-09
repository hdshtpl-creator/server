# -*- coding: utf-8 -*-
"""Che tên khách hàng / đường dẫn hồ sơ khách trong kết quả chạy thật trước khi
lưu vào repo (repo đẩy lên GitHub). Câu trả lời lấy từ máy chủ thật nên lẫn tên
hồ sơ khách (nguồn "[KH: …]", đường dẫn "9. HỒ SƠ KHÁCH HÀNG/…", danh sách hồ
sơ khách của câu M13.2).

    python deploy/kiem-thu/nguon/che_du_lieu_khach.py deploy/kiem-thu/nguon/ket_qua_cau_hoi_mau_0510.json
"""
import json
import re
import sys

_KH = re.compile(r"\[KH:[^\]]*\]")
_DUONG_DAN = re.compile(r"9\. HỒ SƠ KHÁCH HÀNG/[^)\n]*", re.I)
_NGOAC = re.compile(r"\(HỒ SƠ KHÁCH HÀNG — [^)]*\)", re.I)


def che(text: str) -> str:
    if not text:
        return text
    text = _KH.sub("[KH: …]", text)
    text = _DUONG_DAN.sub("9. HỒ SƠ KHÁCH HÀNG/… (đã che)", text)
    return _NGOAC.sub("(HỒ SƠ KHÁCH HÀNG — …)", text)


def che_danh_sach(text: str) -> str:
    """Câu trả lời liệt kê kho (tên từng hồ sơ khách): giữ dòng đầu + dòng tổng."""
    dong = (text or "").splitlines()
    giu = [d for d in dong if not d.lstrip().startswith("- ")]
    n = len(dong) - len(giu)
    if n:
        giu.insert(1, f"[… {n} dòng tên hồ sơ khách đã che khi lưu báo cáo …]")
    return "\n".join(giu)


def che_ban_ghi(rec: dict, la_danh_sach_khach=False) -> dict:
    if rec.get("answer"):
        rec["answer"] = che(che_danh_sach(rec["answer"]) if la_danh_sach_khach else rec["answer"])
    for s in rec.get("nguon") or []:
        if s.get("title"):
            s["title"] = che(s["title"])
        if s.get("doc_type") in ("filing", "ho_so_kh") and s.get("title") and "[KH:" not in s["title"]:
            s["title"] = "[hồ sơ khách — đã che]"
    if rec.get("ban_nhap") and rec["ban_nhap"].get("noi_dung"):
        rec["ban_nhap"]["noi_dung"] = che(rec["ban_nhap"]["noi_dung"])
    return rec


def main(path):
    kq = json.load(open(path, encoding="utf-8"))
    for nhom in ("cau", "truoc_sua_0610"):
        for ma, rec in (kq.get(nhom) or {}).items():
            che_ban_ghi(rec, la_danh_sach_khach=(ma == "M13.2"))
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(kq, f, ensure_ascii=False, indent=1)
    print("đã che", path)


if __name__ == "__main__":
    main(sys.argv[1])
