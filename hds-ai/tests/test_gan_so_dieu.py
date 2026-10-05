"""Máy gắn số Điều cho [Nguồn n] trỏ vào đoạn luật một-điều (03/10/2026, CH-01)."""
import unittest

from app import rag

CH = [
    {"doc_type": "law", "so_hieu": "91/2015/QH13", "loai_van_ban": "Bộ luật",
     "section_title": "BLDS — Điều 429",
     "content": "[BLDS — Điều 429]\nĐiều 429. Thời hiệu khởi kiện về hợp đồng\nThời hiệu là 03 năm"},
    {"doc_type": "law", "so_hieu": "91/2015/QH13", "loai_van_ban": "Bộ luật",
     "section_title": "BLDS — Điều 149",
     "content": "Điều 149. Thời hiệu\n1. …\nĐiều 150. Các loại thời hiệu"},
    {"doc_type": "ban_an", "content": "Bản án số 12/2020"},
    {"doc_type": "law", "so_hieu": "45/2019/QH14", "loai_van_ban": "Bộ luật",
     "section_title": "BLLĐ — Điều 25 (phần 2)",
     "content": "2. Không quá 60 ngày đối với công việc …"},
]


class TestGanSoDieu(unittest.TestCase):
    def test_gan_khi_cau_chua_neu_dieu(self):
        out = rag.gan_so_dieu("Thời hiệu là 03 năm [Nguồn 1].", CH)
        self.assertIn("(Điều 429 Bộ luật 91/2015/QH13) [Nguồn 1]", out)

    def test_khong_gan_khi_da_neu_hoac_khong_chac(self):
        t = "Theo Điều 429 thì 03 năm [Nguồn 1]. Xem [Nguồn 2] và bản án [Nguồn 3]."
        self.assertEqual(rag.gan_so_dieu(t, CH), t)

    def test_da_neu_so_hieu_thi_chi_gan_so_dieu(self):
        out = rag.gan_so_dieu("Theo Bộ luật 91/2015/QH13 thì 03 năm [Nguồn 1].", CH)
        self.assertIn("(Điều 429) [Nguồn 1]", out)

    def test_phan_sau_cua_dieu_dai_lay_tu_muc(self):
        out = rag.gan_so_dieu("Thử việc không quá 60 ngày [Nguồn 4].", CH)
        self.assertIn("(Điều 25 Bộ luật 45/2019/QH14) [Nguồn 4]", out)

    def test_nguon_vuot_tran_giu_nguyen(self):
        self.assertEqual(rag.gan_so_dieu("x [Nguồn 9].", CH), "x [Nguồn 9].")


if __name__ == "__main__":
    unittest.main()
