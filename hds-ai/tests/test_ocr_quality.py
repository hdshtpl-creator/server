"""Nâng chất lượng OCR: nắn nghiêng, nhị phân hoá theo vùng, chọn bộ đọc.

Bản scan văn bản luật đi thẳng vào kho làm căn cứ pháp lý, nên OCR sai một
chữ số ("Điều 47" thành "Điều 4T") là sai căn cứ. Các test dưới đây khoá phần
LOGIC THUẦN của đường OCR — không cần Pillow, không cần tesseract, không chạm
CSDL (deploy/update.sh chạy nguyên bộ test ngay trên máy chủ đang phục vụ).
"""
import unittest

from app import ingest


class ChonBoDocTests(unittest.TestCase):
    """_choose_ocr_engine: cài PaddleOCR vào là tự nâng cấp, gỡ ra tự lùi."""

    def test_auto_dung_paddle_khi_co(self):
        self.assertEqual(ingest._choose_ocr_engine("auto", True), "paddle")

    def test_auto_lui_ve_tesseract_khi_thieu(self):
        self.assertEqual(ingest._choose_ocr_engine("auto", False), "tesseract")

    def test_khong_dat_gi_cung_la_auto(self):
        self.assertEqual(ingest._choose_ocr_engine("", False), "tesseract")
        self.assertEqual(ingest._choose_ocr_engine(None, True), "paddle")

    def test_ep_dung_tesseract_du_co_paddle(self):
        # Lối lùi khi PaddleOCR đọc tệ hơn trên một lô tài liệu cụ thể.
        self.assertEqual(ingest._choose_ocr_engine("tesseract", True), "tesseract")

    def test_ep_dung_paddle_du_chua_cai(self):
        # Ép thì phải giữ nguyên ý muốn để lỗi nổi lên rõ ràng, không âm thầm
        # đổi bộ đọc rồi người vận hành tưởng đang chạy Paddle.
        self.assertEqual(ingest._choose_ocr_engine("paddle", False), "paddle")

    def test_khong_phan_biet_hoa_thuong_va_khoang_trang(self):
        self.assertEqual(ingest._choose_ocr_engine("  PaddleOCR ", False), "paddle")
        self.assertEqual(ingest._choose_ocr_engine("TESSERACT", True), "tesseract")


class PhuongSaiTests(unittest.TestCase):
    """_variance: điểm số để chấm từng góc nghiêng."""

    def test_day_phang_bang_khong(self):
        self.assertEqual(ingest._variance([7, 7, 7, 7]), 0.0)

    def test_day_qua_ngan(self):
        self.assertEqual(ingest._variance([]), 0.0)
        self.assertEqual(ingest._variance([5]), 0.0)

    def test_tuong_phan_cao_thi_diem_cao(self):
        # Trang thẳng: dòng chữ tối xen khoảng trắng sáng → phương sai lớn.
        thang = ingest._variance([0, 255, 0, 255, 0, 255])
        # Trang nghiêng: chữ trộn đều vào mọi hàng → biểu đồ phẳng hơn.
        nghieng = ingest._variance([120, 130, 125, 135, 128, 122])
        self.assertGreater(thang, nghieng)


class GocThuTests(unittest.TestCase):
    """_skew_angles: dải góc sẽ thử."""

    def test_doi_xung_va_co_goc_khong(self):
        goc = ingest._skew_angles(1.0, 0.5)
        self.assertEqual(goc, [-1.0, -0.5, 0.0, 0.5, 1.0])

    def test_mac_dinh_cua_he_thong(self):
        goc = ingest._skew_angles(ingest.OCR_DESKEW_MAX_DEG, ingest.OCR_DESKEW_STEP)
        self.assertIn(0.0, goc)
        self.assertAlmostEqual(min(goc), -ingest.OCR_DESKEW_MAX_DEG)
        self.assertAlmostEqual(max(goc), ingest.OCR_DESKEW_MAX_DEG)
        # Đủ mịn để bắt được lệch 1 độ, đủ thưa để không đắt.
        self.assertLessEqual(len(goc), 60)

    def test_tham_so_vo_nghia_thi_khong_xoay(self):
        self.assertEqual(ingest._skew_angles(0, 0.5), [0.0])
        self.assertEqual(ingest._skew_angles(3, 0), [0.0])


class BienMoiTruongTests(unittest.TestCase):
    """_bool_env: tắt từng bước tiền xử lý mà không phải sửa mã."""

    def setUp(self):
        import os
        self.os = os
        self.os.environ.pop("HDS_TEST_CO", None)

    def tearDown(self):
        self.os.environ.pop("HDS_TEST_CO", None)

    def test_khong_dat_thi_giu_mac_dinh(self):
        self.assertTrue(ingest._bool_env("HDS_TEST_CO", True))
        self.assertFalse(ingest._bool_env("HDS_TEST_CO", False))

    def test_cac_cach_viet_tat(self):
        for raw in ("0", "false", "no", "off", "FALSE", " Off "):
            self.os.environ["HDS_TEST_CO"] = raw
            self.assertFalse(ingest._bool_env("HDS_TEST_CO", True), raw)

    def test_cac_cach_viet_bat(self):
        for raw in ("1", "true", "yes", "on"):
            self.os.environ["HDS_TEST_CO"] = raw
            self.assertTrue(ingest._bool_env("HDS_TEST_CO", False), raw)


class MacDinhAnToanTests(unittest.TestCase):
    """Giá trị mặc định phải hợp lý cho bản scan giấy tờ Việt Nam."""

    def test_dpi_du_cao_cho_dau_thanh(self):
        # 300 là mức tesseract khuyến nghị; giấy tờ VN nhiều dấu nhỏ nên cao hơn.
        self.assertGreaterEqual(ingest.OCR_DPI, 300)

    def test_lstm_only(self):
        self.assertIn("--oem 1", ingest.OCR_CONFIG)

    def test_hai_buoc_moi_bat_san(self):
        self.assertTrue(ingest.OCR_DESKEW)
        self.assertTrue(ingest.OCR_BINARIZE)

    def test_dai_goc_bao_duoc_lech_thuong_gap(self):
        # Đặt giấy tay thường lệch 1-3 độ; dải phải trùm được mức đó.
        self.assertGreaterEqual(ingest.OCR_DESKEW_MAX_DEG, 2.0)


if __name__ == "__main__":
    unittest.main()
