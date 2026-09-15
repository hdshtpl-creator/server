"""Thước đo mức đọc được của văn bản (app/chat_luong.py) — logic thuần.

Thước này quyết định tài liệu nào được duyệt nhãn hàng loạt, nên nó sai là
hoặc bot học phải chuỗi ký tự vụn, hoặc hồ sơ sạch bị nhốt trong hàng chờ.

Luật cần giữ:
  · rác OCR thật (chép từ màn hình người dùng) phải vượt xa ngưỡng 20%;
  · điều luật và hồ sơ doanh nghiệp bình thường phải gần 0%;
  · số hiệu văn bản, viết tắt, số tiền KHÔNG bị tính là rác;
  · văn bản rỗng là 1.0 — không có chữ thì không có gì để duyệt.
"""
import unittest

from app.chat_luong import la_am_tiet, token_doc_duoc, ty_le_rac

# Chép nguyên từ tests/test_quality.py: OCR bản sao hộ chiếu trong hồ sơ khách.
RAC_OCR = ("[Trang 2] \\?4È^ R34»: 2] %4tiR # 11 : #k ‡UU3* #}4‡ Nõ. "
           "AT\" V387 8100 % \"....._ nn Sàn The Mimistry. %Ƒ '#otciiN: "
           "Aair- gF _ sàn 2d: 'People's. _Republic- ,9f¬ China - SÀNG "
           "Sa Côn _.. 8H12 /01ME Lộ NNUÊ:: G119; và, TIẾP sục 0m84. "
           "+ ÅISIÈFìLH PEOPLE'S REPUBLIC ORCEH\"NA")

DIEU_LUAT = ("Điều 15. Hợp đồng lao động phải được giao kết bằng văn bản và "
             "được làm thành hai bản, người lao động giữ một bản, người sử "
             "dụng lao động giữ một bản, trừ trường hợp quy định tại khoản 2 "
             "Điều này.")

HO_SO_DN = ("CÔNG TY TNHH THƯƠNG MẠI HL VIỆT NAM. Giấy chứng nhận đăng ký "
            "doanh nghiệp số 0108234567 do Sở Kế hoạch và Đầu tư thành phố "
            "Hà Nội cấp ngày 12/3/2020. Vốn điều lệ: 5.000.000.000 đồng.")

NGUONG = 0.20


class AmTiet(unittest.TestCase):
    def test_am_tiet_tieng_viet_hop_le(self):
        for tu in ["sục", "nghiêng", "người", "ngoại", "nguyễn", "khuyết",
                   "và", "ăn", "ông", "quả", "gì", "hoa", "Điều", "trường"]:
            self.assertTrue(la_am_tiet(tu), tu)

    def test_chuoi_vun_khong_phai_am_tiet(self):
        for tu in ["NNUÊ", "otciiN", "Mimistry", "ORCEHNA", "nn", "Aair"]:
            self.assertFalse(la_am_tiet(tu), tu)


class TokenDocDuoc(unittest.TestCase):
    def test_so_va_ngay_thang(self):
        for tu in ["2026", "1.234.567", "15/2026", "31-12", "0108234567"]:
            self.assertTrue(token_doc_duoc(tu), tu)

    def test_so_hieu_van_ban(self):
        for tu in ["67/VBHN-VPQH", "45/2019/QH14", "15/2026/NĐ-CP"]:
            self.assertTrue(token_doc_duoc(tu), tu)

    def test_viet_tat_toan_chu_hoa(self):
        for tu in ["TNHH", "UBND", "HĐQT", "CP", "SHTT"]:
            self.assertTrue(token_doc_duoc(tu), tu)

    def test_chu_lan_so_la_rac(self):
        for tu in ["R34", "8H12", "0m84", "V387", "4tiR"]:
            self.assertFalse(token_doc_duoc(tu), tu)


class TyLeRac(unittest.TestCase):
    def test_rac_ocr_that_vuot_nguong(self):
        ty_le = ty_le_rac(RAC_OCR)
        self.assertGreater(ty_le, NGUONG)
        # Cách ngưỡng một quãng rộng, không phải vừa chớm — đổi ngưỡng lên
        # 0.3 hay 0.4 vẫn phải bắt được nó.
        self.assertGreater(ty_le, 0.40)

    def test_van_ban_that_gan_khong(self):
        self.assertLess(ty_le_rac(DIEU_LUAT), 0.05)
        self.assertLess(ty_le_rac(HO_SO_DN), 0.05)

    def test_rong_la_rac_hoan_toan(self):
        self.assertEqual(ty_le_rac(""), 1.0)
        self.assertEqual(ty_le_rac("   \n  "), 1.0)
        self.assertEqual(ty_le_rac(None), 1.0)

    def test_khoang_cach_giua_that_va_rac_du_rong(self):
        # Chốt quan trọng nhất: ngưỡng 20% phải nằm trong khoảng trống giữa
        # hai nhóm. Hai nhóm xích lại gần nhau là thước hỏng.
        self.assertLess(max(ty_le_rac(DIEU_LUAT), ty_le_rac(HO_SO_DN)), NGUONG)
        self.assertGreater(ty_le_rac(RAC_OCR), NGUONG)


if __name__ == "__main__":
    unittest.main()
