# -*- coding: utf-8 -*-
"""40 kịch bản pháp lý của HDS (Kịch bản test AI.docx) — dạng có cấu trúc.
Sinh từ kb40.json (parse_kb.py) + cột 'Điều bắt buộc' viết tay từ Tiêu chí."""
import json, re, os

HERE = os.path.dirname(os.path.abspath(__file__))

# Điều/văn bản BẮT BUỘC phải xuất hiện trong câu trả lời — rút từ cột Tiêu chí.
# Chấm: ĐÚNG = dẫn đủ mọi mục; MỘT PHẦN = dẫn ≥ 1 mục và không sai bản chất;
# SAI = không dẫn mục nào hoặc kết luận ngược tiêu chí.
DIEU = {
    "1.1": "Điều 47 LDN 2020 (90 ngày); Điều 35 LDN 2020",
    "1.2": "Điều 26 Luật Đầu tư 2020",
    "1.3": "Điều 117 LDN 2020",
    "1.4": "Điều 46 Luật Đầu tư 2020; Luật Đất đai (đất thuê trả tiền hằng năm)",
    "1.5": "Điều 202 LDN 2020",
    "1.6": "Điều 127 LDN 2020; Điều 3 BLDS 2015",
    "1.7": "(không nêu số Điều) — phải bóc nghĩa vụ xin chấp thuận ngân hàng tài trợ",
    "1.8": "Điều 51 LDN 2020; điều kiện giải thể bắt buộc",
    "1.9": "Quy định NHNN về vay, trả nợ nước ngoài; vốn vay ≤ tổng vốn đầu tư − vốn góp",
    "1.10": "Điều 68 / Điều 112 LDN 2020",
    "2.1": "Nghị quyết 01/2014/NQ-HĐTP",
    "2.2": "Điều 301 LTM 2005 (8%); Điều 302 LTM 2005",
    "2.3": "Điều 42, 44, 47 BLLĐ 2019",
    "2.4": "Điều 111, 124, 125, 136 BLTTDS 2015",
    "2.5": "Hiến pháp/BLLĐ (quyền tự do việc làm) và BLDS (tự do thoả thuận); án lệ/phán quyết nếu có",
    "2.6": "Điều 423, 424, 427 BLDS 2015",
    "2.7": "Điều 74, 84 BLDS 2015; Điều 68 BLTTDS 2015",
    "2.8": "Điều 156 BLDS 2015; Điều 294 LTM 2005; Điều 420 BLDS 2015",
    "2.9": "(không nêu số Điều) — bộ câu hỏi bám yếu tố bắt buộc của HĐ chuyển nhượng QSDĐ",
    "2.10": "Điều 310 BLTTDS 2015",
    "3.1": "(không nêu số Điều) — phân tích cấu trúc, nghĩa, phát âm, phạm vi dịch vụ",
    "3.2": "Điều 112, 112a, 75 Luật SHTT",
    "3.3": "Điểm d khoản 1 Điều 95 Luật SHTT",
    "3.4": "Điều 19, 20, 39 Luật SHTT",
    "3.5": "Nghị định xử phạt VPHC lĩnh vực sở hữu công nghiệp; kết luận giám định",
    "3.6": "LTM 2005 Mục 8 (Nhượng quyền thương mại); Nghị định hướng dẫn",
    "3.7": "Điều 142 Luật SHTT",
    "3.8": "Quy định SHTT về phạm vi bảo hộ kiểu dáng công nghiệp",
    "3.9": "Điều 130 Luật SHTT; Thông tư về tranh chấp tên miền .vn",
    "3.10": "Điều 60 Luật SHTT (ân hạn 12 tháng)",
    "4.1": "Điều 38, 39, 41 LDN 2020; Điều 19 NĐ 01/2021/NĐ-CP",
    "4.2": "Điều 17 LDN 2020; Luật CB-CC, Luật Viên chức, Luật PCTN",
    "4.3": "QĐ 27/2018/QĐ-TTg (VSIC); NĐ về TMĐT; quy định NHNN về trung gian thanh toán",
    "4.4": "Điều 57, 58 LDN 2020; NĐ 01/2021/NĐ-CP",
    "4.5": "Luật Quản lý thuế; Thông tư đăng ký thuế; Điều 47 NĐ 01/2021/NĐ-CP",
    "4.6": "Điều 123, 125, 148 LDN 2020",
    "4.7": "Điều 22, 37, 38 Luật Đầu tư 2020; NĐ 31/2021/NĐ-CP",
    "4.8": "Điều 29, 30, 31, 32 Luật Đầu tư 2020; Luật Đất đai",
    "4.9": "Điều 41, 44 Luật Đầu tư 2020",
    "4.10": "Điểm b khoản 2 Điều 26 Luật Đầu tư 2020; NĐ 31/2021/NĐ-CP",
}

# Kết quả các lượt trước (biên bản 15/09, lượt 11/09) để tester so tiến bộ.
LUOT_TRUOC = {
    "1.1": "15/09: Một phần (dẫn Điều 47, thiếu Điều 35)",
    "1.6": "15/09: Chưa (không dẫn điều nào)",
    "2.4": "15/09: Một phần (dẫn Điều 136)",
    "4.1": "15/09: Chưa (không dẫn điều nào)",
    "4.7": "15/09: Một phần (dẫn Điều 22)",
}


def load():
    cases = json.load(open(os.path.join(HERE, "kb40.json"), encoding="utf-8"))
    for c in cases:
        c["tieu_chi"] = re.sub(r"\s*(Dưới đây là.*|\d\.\s*Nhóm Kịch bản:.*)$", "",
                               c["tieu_chi"]).strip()
        c["dieu"] = DIEU[c["id"]]
        c["luot_truoc"] = LUOT_TRUOC.get(c["id"], "")
        # Câu gửi bot = Tình huống + Yêu cầu, nguyên văn của HDS.
        c["cau_hoi"] = f"{c['tinh_huong']} {c['yeu_cau']}".strip()
    return cases


if __name__ == "__main__":
    cs = load()
    print(len(cs), cs[29]["id"], cs[29]["tieu_chi"][-80:])
