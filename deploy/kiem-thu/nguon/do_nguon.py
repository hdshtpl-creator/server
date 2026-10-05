# -*- coding: utf-8 -*-
"""Đo phần TÌM NGUỒN cho bộ câu hỏi mẫu (cau_hoi_mau.py) — chạy TRÊN MÁY CHỦ.

Chỉ gọi rag.prepare (tìm kho + dựng prompt), KHÔNG gọi model sinh chữ: vài giây
mỗi câu, không chiếm GPU của người đang dùng. Kết quả cho biết TRƯỚC KHI nhân
viên thử: câu nào bot đã có đúng nguồn trong tay, câu nào chưa — câu chưa có
nguồn thì câu trả lời gần như chắc chắn sai, đó là lỗi tìm kiếm chứ không phải
lỗi model.

    cd ~/hds-ai-full/hds-ai && .venv/bin/python /tmp/do_nguon.py > /tmp/do_nguon.json
"""
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.expanduser("~/hds-ai-full/hds-ai"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.expanduser("~/hds-ai-full/hds-ai"))

from app import rag  # noqa: E402
import cau_hoi_mau as Q  # noqa: E402

RE_SEC = re.compile(r"_EX-10")


def khop(e, kiem):
    if "doc_id" in kiem:
        return e.get("document_id") == kiem["doc_id"]
    if "ngan" in kiem:
        return e.get("doc_type") == "mau_hd" and bool(RE_SEC.search(e.get("title") or ""))
    nhan = " ".join(str(e.get(k) or "") for k in ("title", "so_hieu", "trich_yeu"))
    if not any(p in nhan for p in kiem["vb"]):
        return False
    vi_tri = f"{e.get('section_title') or ''} {(e.get('quote') or '')[:400]}"
    return bool(re.search(rf"Điều {kiem['dieu']}\b", vi_tri))


def do(cau, kiem):
    kw = {}
    if "doc_id" in kiem:
        kw["source_document_ids"] = [kiem["doc_id"]]
    if kiem.get("mode"):
        kw["mode"] = kiem["mode"]
    # "vai": đo bằng tài khoản thường (vd trợ lý) để thấy chốt quyền mở thật.
    vai = kiem.get("vai") or "admin"
    t0 = time.time()
    if vai != "admin":
        kw.update(dept_ids=[], dept_codes=[])
    p = rag.prepare(cau, "internal", is_banqt=(vai == "admin"), role=vai, **kw)
    ms = int((time.time() - t0) * 1000)
    ev = p.get("evidence") or []
    if kiem.get("truc_tiep"):
        ok = p.get("direct_answer") is not None and p.get("answer_mode") in ("structured", "operational")
        return {"ok": ok, "ms": ms, "ghi": "trả lời thẳng từ CSDL" if ok else "đi qua tìm kho (không trả thẳng)",
                "tra_loi": (p.get("direct_answer") or "")[:200]}
    trung = [e.get("n") for e in ev if khop(e, kiem)]
    return {"ok": bool(trung), "ms": ms, "so_nguon": len(ev), "vi_tri": trung[:5], "vai": vai,
            "bi_khoa": (p.get("timings") or {}).get("bo_qua_khong_quyen_mo", 0),
            "dau": [f"{e.get('doc_type')}: {(e.get('title') or '')[:70]}" for e in ev[:5]]}


out = {}
for row in Q.VN:
    if row[8]:
        out[row[0]] = do(row[4], row[8])
for row in Q.EN:
    if row[6]:
        out[row[0]] = do(row[3], row[6])
print(json.dumps(out, ensure_ascii=False, indent=1))
