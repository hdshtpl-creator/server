"""
goi_y_ly_do.py — GỢI Ý LÝ DO SỬA khi người duyệt sửa nội dung một tài liệu kho
(hợp đồng mục 2 "Tự động Diff & Tag": highlight điểm thay đổi + gợi ý tag lý do
Luật mới / Rủi ro / Client request, người dùng xác nhận một click).

Hai tầng: (1) QUY TẮC tất định trên phần chữ thật sự đổi — sửa lỗi OCR (bản
cũ toàn chữ rác / chỉ khác dấu), luật thay đổi (thêm số hiệu, "sửa đổi, bổ
sung", "hiệu lực"), rủi ro, yêu cầu khách; (2) không quy tắc nào chắc thì hỏi
model một câu ngắn, ép trả đúng một nhãn. Gợi ý KHÔNG tự lưu — người duyệt
vẫn chọn và bấm Lưu; lý do cuối cùng ghi vào lịch sử phiên bản như cũ.
"""
import difflib
import json
import re
import unicodedata

LY_DO = {
    "luat_thay_doi": "Luật thay đổi",
    "rui_ro": "Rủi ro",
    "yeu_cau_khach": "Yêu cầu khách hàng",
    "sua_loi_trich_xuat": "Sửa lỗi trích xuất / OCR",
    "khac": "Khác",
}

_TOKEN = re.compile(r"\w+", re.UNICODE)


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFD", (s or "").lower())
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return s.replace("đ", "d")


def phan_doi(cu: str, moi: str) -> tuple[list[str], list[str]]:
    """Các từ bị XOÁ và các từ được THÊM (theo thứ tự xuất hiện)."""
    a, b = _TOKEN.findall(cu or ""), _TOKEN.findall(moi or "")
    xoa, them = [], []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op in ("delete", "replace"):
            xoa += a[i1:i2]
        if op in ("insert", "replace"):
            them += b[j1:j2]
    return xoa, them


def _rac(tu: str) -> bool:
    """Từ 'rác OCR': lẫn chữ-số, ký tự lạ, hoặc không có nguyên âm nào."""
    f = _fold(tu)
    if re.search(r"[a-z]\d|\d[a-z]", f):
        return True
    if len(f) >= 3 and f.isalpha() and not re.search(r"[aeiouy]", f):
        return True
    return False


_LUAT = re.compile(r"sua doi|bo sung|thay the|het hieu luc|co hieu luc|hieu luc thi hanh|"
                   r"\b(?:luat|nghi dinh|thong tu|nghi quyet|quyet dinh)\s+so\b|"
                   r"/\d{4}/(?:qh|nd|tt|nq|qd)")
_RUI_RO = re.compile(r"rui ro|canh bao|luu y|bat loi|phat vi pham|boi thuong|vo hieu|tranh chap")
_KHACH = re.compile(r"theo yeu cau|khach hang (?:yeu cau|de nghi|muon)|theo de nghi cua|khach yeu cau")


def goi_y(cu: str, moi: str, doc_type: str = "", llm=None) -> dict:
    """→ {ly_do, nhan, giai_thich, nguon: 'quy_tac'|'ai', so_tu_xoa, so_tu_them}."""
    xoa, them = phan_doi(cu, moi)

    def kq(ly_do, giai_thich, nguon="quy_tac"):
        return {"ly_do": ly_do, "nhan": LY_DO[ly_do], "giai_thich": giai_thich,
                "nguon": nguon, "so_tu_xoa": len(xoa), "so_tu_them": len(them)}

    if not xoa and not them:
        return kq("khac", "Nội dung chưa thay đổi so với bản đang lưu.")
    f_xoa, f_them = " ".join(_fold(t) for t in xoa), " ".join(_fold(t) for t in them)
    # (1) Chỉ khác dấu / hoa-thường → sửa lỗi đọc
    if f_xoa == f_them:
        return kq("sua_loi_trich_xuat", "Các chỗ sửa chỉ khác dấu tiếng Việt / chữ hoa — "
                                        "giống sửa lỗi nhận dạng chữ (OCR).")
    # (2) Phần bị xoá phần lớn là chữ rác
    if xoa and sum(_rac(t) for t in xoa) / len(xoa) >= 0.4:
        return kq("sua_loi_trich_xuat", f"{sum(_rac(t) for t in xoa)}/{len(xoa)} từ bị thay là "
                                        "chữ rác (lẫn chữ-số, không có nguyên âm) — sửa lỗi OCR.")
    # (3) Phần thêm mới nói về văn bản luật mới / hiệu lực
    if _LUAT.search(f_them) or (doc_type == "law" and re.search(r"\bdieu \d+", f_them)):
        return kq("luat_thay_doi", "Phần thêm mới nhắc văn bản sửa đổi, bổ sung / số hiệu / "
                                   "hiệu lực — thường là cập nhật theo luật mới.")
    if _KHACH.search(f_them):
        return kq("yeu_cau_khach", "Phần thêm mới ghi rõ là theo yêu cầu / đề nghị của khách hàng.")
    if _RUI_RO.search(f_them):
        return kq("rui_ro", "Phần thêm mới nói về rủi ro / cảnh báo / phạt / bồi thường.")
    # (4) Không chắc → hỏi model một nhãn
    if llm is not None:
        try:
            nhan = _hoi_model(llm, xoa, them)
            if nhan:
                return kq(nhan[0], nhan[1], "ai")
        except Exception:  # noqa: BLE001 — model hỏng thì lùi về 'khac', không chặn người sửa
            pass
    return kq("khac", "Không nhận ra lý do rõ ràng từ phần sửa — hãy chọn tay.")


_PROMPT = (
    "Người duyệt vừa sửa nội dung một tài liệu pháp lý. Dưới đây là các TỪ BỊ XOÁ và các "
    "TỪ ĐƯỢC THÊM. Chọn MỘT lý do sửa phù hợp nhất trong: luat_thay_doi (cập nhật theo "
    "luật/văn bản mới), rui_ro (bổ sung/điều chỉnh vì rủi ro pháp lý), yeu_cau_khach (theo "
    "yêu cầu khách hàng), sua_loi_trich_xuat (sửa lỗi đọc chữ/OCR, chính tả), khac.\n"
    "Chỉ trả về JSON: {\"ly_do\": \"<mã>\", \"giai_thich\": \"<một câu tiếng Việt>\"}\n\n"
)


def _hoi_model(llm, xoa, them):
    noi_dung = (f"TỪ BỊ XOÁ: {' '.join(xoa)[:1200]}\nTỪ ĐƯỢC THÊM: {' '.join(them)[:1200]}")
    raw = llm(_PROMPT + noi_dung)
    raw = re.sub(r"<think>.*?</think>", "", raw or "", flags=re.S)
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    d = json.loads(m.group(0))
    ma = (d.get("ly_do") or "").strip()
    if ma not in LY_DO:
        return None
    return ma, (d.get("giai_thich") or "").strip()[:300] or LY_DO[ma]
