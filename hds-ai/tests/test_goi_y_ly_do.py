"""Gợi ý lý do sửa nội dung tài liệu (hợp đồng mục 2 — Diff & Tag)."""
import unittest

from app import goi_y_ly_do as G


class TestGoiYLyDo(unittest.TestCase):
    def test_khong_doi(self):
        self.assertEqual(G.goi_y("Điều 1. Phạm vi", "Điều 1. Phạm vi")["ly_do"], "khac")

    def test_chi_khac_dau_la_loi_ocr(self):
        r = G.goi_y("Dieu 5. Phat vi pham hop dong", "Điều 5. Phạt vi phạm hợp đồng")
        self.assertEqual(r["ly_do"], "sua_loi_trich_xuat")
        self.assertEqual(r["nguon"], "quy_tac")

    def test_chu_rac_la_loi_ocr(self):
        r = G.goi_y("C0NG H0A xA HQI CHU NGHlA V1ET NAM", "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM")
        self.assertEqual(r["ly_do"], "sua_loi_trich_xuat")

    def test_luat_moi(self):
        r = G.goi_y("Thời hạn góp vốn là 90 ngày.",
                    "Thời hạn góp vốn là 90 ngày (đã được sửa đổi, bổ sung bởi Luật số 76/2025/QH15).",
                    doc_type="law")
        self.assertEqual(r["ly_do"], "luat_thay_doi")

    def test_yeu_cau_khach(self):
        r = G.goi_y("Thanh toán một lần.", "Thanh toán hai đợt theo yêu cầu của khách hàng.")
        self.assertEqual(r["ly_do"], "yeu_cau_khach")

    def test_rui_ro(self):
        r = G.goi_y("Bên B giao hàng đúng hạn.",
                    "Bên B giao hàng đúng hạn; chậm giao thì chịu phạt vi phạm và bồi thường thiệt hại.")
        self.assertEqual(r["ly_do"], "rui_ro")

    def test_hoi_model_khi_khong_chac(self):
        r = G.goi_y("Bên A cung cấp tài liệu.", "Bên A cung cấp tài liệu trong 5 ngày làm việc.",
                    llm=lambda p: '<think>x</think>{"ly_do": "khac", "giai_thich": "Bổ sung thời hạn"}')
        self.assertEqual(r["nguon"], "ai")
        self.assertEqual(r["giai_thich"], "Bổ sung thời hạn")

    def test_model_tra_nhan_la_thi_lui_ve_khac(self):
        r = G.goi_y("Bên A cung cấp tài liệu.", "Bên A cung cấp tài liệu đầy đủ.",
                    llm=lambda p: '{"ly_do": "xoa_het_du_lieu"}')
        self.assertEqual((r["ly_do"], r["nguon"]), ("khac", "quy_tac"))

    def test_model_loi_khong_chan(self):
        def hong(_p):
            raise RuntimeError("ollama down")
        r = G.goi_y("Bên A cung cấp tài liệu.", "Bên A cung cấp tài liệu đầy đủ.", llm=hong)
        self.assertEqual(r["ly_do"], "khac")


if __name__ == "__main__":
    unittest.main()
