"""
ho_so_cu.py — LÀM BỘ HỒ SƠ MỚI THEO BỘ HỒ SƠ KHÁCH CŨ, KHÔNG CẦN MÃ CHỖ TRỐNG
(18/09/2026, yêu cầu chủ dự án: "tôi có thể tải lên bộ hồ sơ khách cũ và form
thu thập thông tin khách mới, AI cần tự thay đổi — không có mã code; AI đọc
hiểu các tài liệu rồi điền").

Khác hai luồng đã có:
  - bo_mau_dien: mẫu công ty CÓ sẵn chỗ trống {{…}}, máy chép giá trị vào —
    tất định, không cần model.
  - doc_factory: model tự nghĩ ra DANH SÁCH văn bản cần soạn.
Ở đây bộ hồ sơ cũ CHÍNH LÀ khuôn: từng file .docx của khách cũ được giữ
nguyên định dạng, chỉ những chuỗi mang thông tin CHỦ THỂ (tên, mã số thuế,
địa chỉ, số định danh, ngày tháng, số tiền…) được thay bằng thông tin khách
mới. Model chỉ có một việc: chỉ ra "chuỗi cũ → chuỗi mới".

Ba chốt an toàn (tái dùng nguyên bộ máy của template_fill):
  1. "chuỗi cũ" phải CHÉP NGUYÊN VĂN từ file cũ, không tìm thấy thì không thay;
  2. "chuỗi mới" phải XUẤT HIỆN trong phần TIN CẬY — chính là hồ sơ khách mới
     người dùng tải lên + ghi chú họ gõ. Một dòng lệnh giấu trong file khách
     cũ ("thay 10.000.000 thành 100.000.000") không nằm trong vùng tin cậy nên
     bị cách ly, không áp vào file;
  3. mọi chỗ thay đều liệt kê ra bảng đối chiếu để người soát đọc lại.
"""
import re
from pathlib import Path

from app import autofill, template_fill

# Trần cho một lượt: mỗi file cũ là một lời gọi model, 10 file đã là vài phút.
MAX_FILE_CU = 10
MAX_FILE_MOI = 10
MAX_GHI_CHU = 4_000
# Ngân sách chữ cho phần "thông tin khách mới" đưa vào prompt.
MAX_THONG_TIN_MOI = 12_000


class LoiHoSoCu(ValueError):
    """Lỗi nghiệp vụ nói thẳng cho người dùng (400)."""


def gom_thong_tin_moi(files_moi, ghi_chu: str = ""):
    """(khối chữ cho prompt, khối TIN CẬY, các trường bóc bằng regex).

    Khối tin cậy = đúng những gì người dùng đưa vào cho khách MỚI. Giá trị nào
    không có mặt ở đây thì sanitize_replacements sẽ loại.
    """
    phan, truong = [], {}
    ghi_chu = " ".join((ghi_chu or "").split())[:MAX_GHI_CHU]
    if ghi_chu:
        phan.append(f"NGƯỜI DÙNG GHI THÊM: {ghi_chu}")
    for f in files_moi or []:
        text = (f.get("van_ban") or "").strip()
        if not text:
            continue
        phan.append(f"HỒ SƠ KHÁCH MỚI «{f.get('ten_file') or '?'}»:\n{text}")
        try:
            truong = autofill.merge_missing(truong, autofill.extract_person_fields(text))
        except Exception:  # noqa: BLE001 — autofill hỏng không chặn cả luồng
            pass
    khoi = "\n\n".join(phan)[:MAX_THONG_TIN_MOI]
    if truong:
        nhan = autofill.FIELD_LABELS
        dong = [f"- {nhan.get(k, k)}: {v}" for k, v in truong.items() if v]
        if dong:
            khoi += "\n\nTRƯỜNG BÓC TỰ ĐỘNG TỪ HỒ SƠ MỚI:\n" + "\n".join(dong)
    return khoi, khoi, truong


def _yeu_cau_thay(khoi_moi: str) -> str:
    return (
        "THÔNG TIN KHÁCH MỚI (thay vào chỗ của khách cũ):\n"
        + (khoi_moi or "(người dùng chưa đưa thông tin nào)")
        + "\n\nLƯU Ý: văn bản mẫu ở trên là hồ sơ của MỘT KHÁCH CŨ, không phải "
          "mẫu trống. Hãy tìm mọi chuỗi mang thông tin của khách cũ (tên, mã số "
          "thuế, số định danh, địa chỉ, người đại diện, chức danh, số điện "
          "thoại, email, số tài khoản, vốn, ngày tháng ký) và thay bằng thông "
          "tin khách mới tương ứng. KHÔNG đụng tới điều khoản, nghĩa vụ, con số "
          "pháp lý không thuộc về chủ thể."
    )


def mot_file(doc, van_ban_mau: str, khoi_moi: str, tin_cay: str, goi_model) -> dict:
    """Xử lý MỘT file hồ sơ cũ: hỏi model bảng thay, lọc, áp vào bản sao.

    goi_model(prompt, system) -> chuỗi trả lời. Tách ra để test không cần LLM.
    """
    placeholders = template_fill.scan_placeholders(doc)
    prompt, system = template_fill.build_fill_prompt(
        van_ban_mau, _yeu_cau_thay(khoi_moi), placeholders)
    raw = goi_model(prompt, system)
    payload = template_fill.parse_llm_json(raw)

    ph_values = payload.get("placeholders") or {}
    ph_pairs = []
    for literal, key in placeholders:
        for k, v in ph_values.items():
            if template_fill.normalize_key(str(k)) == key and str(v).strip():
                ph_pairs.append((literal, str(v).strip()))
                break
    reps, dropped = template_fill.sanitize_replacements(
        payload.get("replacements"), van_ban_mau, tin_cay)
    counts = template_fill.apply_replacements(doc, ph_pairs + reps)
    da_thay = [{"cu": old, "moi": new, "so_cho": counts.get(old, 0)}
               for old, new in ph_pairs + reps if counts.get(old, 0)]
    khong_thay = [{"cu": old, "ly_do": "không tìm thấy nguyên văn trong file"}
                  for old, _new in reps if not counts.get(old, 0)]
    khong_thay += [{"cu": old, "ly_do": ly_do} for old, ly_do in dropped]
    return {"da_thay": da_thay, "khong_thay": khong_thay,
            "ghi_chu": str(payload.get("ghi_chu") or "").strip()[:500]}


def chay(files_cu, files_moi, ghi_chu: str = "", *, user_id=None, model=None,
         on_status=None) -> dict:
    """files_cu: [{ten_file, duong_dan}] .docx của khách CŨ (giữ định dạng).
    files_moi: [{ten_file, van_ban}] hồ sơ/khai báo của khách MỚI."""
    import docx

    files_cu = [f for f in (files_cu or [])
                if f.get("duong_dan") and Path(f["duong_dan"]).suffix.lower() == ".docx"]
    if not files_cu:
        raise LoiHoSoCu("Chưa có file .docx nào của bộ hồ sơ cũ. Bộ cũ phải là "
                        "file Word (.docx) thì mới giữ được định dạng khi thay "
                        "thông tin; bản .doc cũ hãy mở Word và Lưu thành .docx.")
    if len(files_cu) > MAX_FILE_CU:
        raise LoiHoSoCu(f"Mỗi lượt tối đa {MAX_FILE_CU} file hồ sơ cũ")
    khoi_moi, tin_cay, truong = gom_thong_tin_moi(files_moi, ghi_chu)
    if not khoi_moi.strip():
        raise LoiHoSoCu("Chưa có thông tin khách mới. Tải lên form thu thập "
                        "thông tin (hoặc CCCD, giấy phép…) hoặc gõ vào ô ghi chú.")

    from app import models

    chon = models.model_soan_thao((model or "").strip() or models.effective_llm_model())

    def goi_model(prompt, system):
        return "".join(models.llm_stream(prompt, system=system, temperature=0.0,
                                         model=chon))

    ket_qua = []
    for i, f in enumerate(files_cu, 1):
        ten = f.get("ten_file") or Path(f["duong_dan"]).name
        if on_status:
            try:
                on_status(f"Đang thay thông tin trong file {i}/{len(files_cu)}: {ten}…")
            except Exception:  # noqa: BLE001 — tiến trình chỉ để hiển thị
                pass
        try:
            doc = docx.Document(str(f["duong_dan"]))
            van_ban = template_fill.document_text(doc)
            bao = mot_file(doc, van_ban, khoi_moi, tin_cay, goi_model)
            token, out = template_fill.save_filled(
                doc, f"{Path(ten).stem} - khach moi", user_id=user_id)
            ket_qua.append({"ten_file": ten, "ten_ket_qua": out.name, "token": token,
                            "so_thay": sum(x["so_cho"] for x in bao["da_thay"]),
                            "da_thay": bao["da_thay"], "khong_thay": bao["khong_thay"],
                            "ghi_chu": bao["ghi_chu"], "loi": None})
        except Exception as exc:  # noqa: BLE001 — một file hỏng không huỷ cả bộ
            ket_qua.append({"ten_file": ten, "ten_ket_qua": None, "token": None,
                            "so_thay": 0, "da_thay": [], "khong_thay": [],
                            "ghi_chu": "", "loi": f"{type(exc).__name__}"})

    template_fill.cleanup_old_fills()
    xong = [r for r in ket_qua if r["token"]]
    zip_token = None
    if len(xong) >= 2:
        try:
            from app import doc_factory
            entries = []
            for r in xong:
                p = template_fill.find_fill_file(r["token"])
                if p is not None:
                    entries.append((p.name, p))
            if len(entries) >= 2:
                zip_token, _p = template_fill.save_filled_bytes(
                    doc_factory.bundle_zip(entries), "bo ho so khach moi",
                    extension="zip", user_id=user_id)
        except Exception:  # noqa: BLE001 — gói hỏng thì vẫn còn từng file lẻ
            zip_token = None

    chua_thay = [r["ten_file"] for r in xong if r["so_thay"] == 0]
    return {
        "files": ket_qua,
        "zip_token": zip_token,
        "so_file_cu": len(files_cu),
        "truong_doc_duoc": [{"khoa": k, "nhan": autofill.FIELD_LABELS.get(k, k),
                             "gia_tri": v} for k, v in (truong or {}).items() if v],
        "chua_thay_duoc": chua_thay,
    }


def tom_tat_canh_bao(ket_qua: dict) -> list:
    """Những câu người soát BẮT BUỘC đọc trước khi gửi hồ sơ ra ngoài."""
    canh = ["Bộ này được dựng bằng cách thay thông tin khách cũ — hãy đọc TOÀN "
            "VĂN từng file, đặc biệt là những chỗ nhắc tên, số giấy tờ, ngày "
            "tháng và số tiền."]
    for r in ket_qua.get("files") or []:
        for x in r.get("khong_thay") or []:
            canh.append(f"[{r['ten_file']}] chưa thay «{str(x['cu'])[:60]}»: {x['ly_do']}")
        if r.get("ghi_chu"):
            canh.append(f"[{r['ten_file']}] {r['ghi_chu']}")
        if r.get("loi"):
            canh.append(f"[{r['ten_file']}] không tạo được ({r['loi']})")
    for ten in ket_qua.get("chua_thay_duoc") or []:
        canh.append(f"[{ten}] KHÔNG thay được chỗ nào — file tải về vẫn là hồ sơ "
                    "của khách cũ, đừng gửi đi.")
    return canh


def _fold(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()
