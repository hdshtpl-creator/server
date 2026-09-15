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


class BocKetQuaPaddleTests(unittest.TestCase):
    """_paddle_lines: PaddleOCR 3.x đổi hẳn dạng kết quả so với 2.x.

    Bản 3.x trả mỗi trang là một đối tượng tra bằng khoá ('rec_texts'); bản
    2.x trả danh sách [toạ_độ, (chữ, độ_tin_cậy)]. Đọc sai dạng thì OCR chạy
    xong mà ra rỗng — tài liệu vào kho không có chữ nào, không ai biết.
    """

    def test_dang_3x(self):
        trang = {"rec_texts": ["Điều 47", "Luật Doanh nghiệp"]}
        self.assertEqual(ingest._paddle_lines([trang]),
                         ["Điều 47", "Luật Doanh nghiệp"])

    def test_dang_2x(self):
        trang = [[[[0, 0], [9, 0]], ("Điều 47", 0.98)],
                 [[[0, 9], [9, 9]], ("Luật Doanh nghiệp", 0.95)]]
        self.assertEqual(ingest._paddle_lines([trang]),
                         ["Điều 47", "Luật Doanh nghiệp"])

    def test_ket_qua_rong(self):
        self.assertEqual(ingest._paddle_lines(None), [])
        self.assertEqual(ingest._paddle_lines([]), [])
        self.assertEqual(ingest._paddle_lines([None, []]), [])

    def test_bo_dong_trang(self):
        self.assertEqual(ingest._paddle_lines([{"rec_texts": ["  ", "Điều 5"]}]),
                         ["Điều 5"])

    def test_nhieu_trang_noi_lien(self):
        self.assertEqual(
            ingest._paddle_lines([{"rec_texts": ["trang 1"]},
                                  {"rec_texts": ["trang 2"]}]),
            ["trang 1", "trang 2"])


class DungBanDocPaddleTests(unittest.TestCase):
    """_new_paddle_reader: dựng được bản đọc trên MỌI dòng PaddleOCR.

    Ca thật 29/08/2026 trên máy chủ (paddleocr 3.7.0): tham số của dòng 2.x
    làm 3.x ném ValueError("Unknown argument: show_log"). Mã chỉ bắt TypeError
    nên lỗi lọt ra ngoài, bộ tham số tối giản không bao giờ được thử tới, và
    hệ thống lùi về tesseract — cài Paddle xong vẫn chạy tesseract.
    """

    def setUp(self):
        import sys
        import types
        self.sys = sys
        self.cu = sys.modules.get("paddleocr")
        self.da_thu = []

    def tearDown(self):
        if self.cu is None:
            self.sys.modules.pop("paddleocr", None)
        else:
            self.sys.modules["paddleocr"] = self.cu

    def _gia_lap(self, chap_nhan):
        """Cài một module paddleocr giả chỉ nhận đúng bộ tham số cho trước."""
        import types
        da_thu = self.da_thu

        class BanDocGia:
            def __init__(self, **kwargs):
                da_thu.append(set(kwargs))
                la = set(kwargs) - set(chap_nhan)
                if la:
                    # 3.x báo lỗi kiểu này chứ không phải TypeError.
                    raise ValueError(f"Unknown argument: {sorted(la)[0]}")

        mod = types.ModuleType("paddleocr")
        mod.PaddleOCR = BanDocGia
        self.sys.modules["paddleocr"] = mod

    def test_ban_3x_chi_nhan_use_textline_orientation(self):
        self._gia_lap({"lang", "use_textline_orientation"})
        self.assertIsNotNone(ingest._new_paddle_reader())

    def test_ban_2x_chi_nhan_use_angle_cls(self):
        self._gia_lap({"lang", "use_angle_cls", "show_log"})
        self.assertIsNotNone(ingest._new_paddle_reader())

    def test_ban_la_chi_nhan_moi_lang(self):
        # Bộ tham số tối giản PHẢI được thử tới — đây chính là ca đã hỏng.
        self._gia_lap({"lang"})
        self.assertIsNotNone(ingest._new_paddle_reader())
        self.assertGreaterEqual(len(self.da_thu), 2,
                                "phải thử tiếp sau khi bộ đầu bị từ chối")

    def test_khong_bo_nao_chay_thi_bao_loi(self):
        self._gia_lap(set())          # từ chối cả 'lang'
        with self.assertRaises(Exception):
            ingest._new_paddle_reader()


class NhiPhanHoaTheoBoDocTests(unittest.TestCase):
    """_should_binarize: mỗi bộ đọc cần một kiểu ảnh khác nhau.

    Đo thật 29/08/2026 trên cùng một trang nghị định: đưa ảnh đã nhị phân hoá
    cứng vào PaddleOCR cho ra "Đc lp - T do - Hnh phúc" — ngưỡng cứng làm
    mảnh đi dấu thanh, đúng thứ mô hình mạng nơ-ron cần thấy. Tesseract thì
    ngược lại, ăn ảnh hai màu tốt hơn.
    """

    def test_tesseract_thi_nhi_phan_hoa(self):
        self.assertTrue(ingest._should_binarize("tesseract", True))

    def test_paddle_thi_khong(self):
        self.assertFalse(ingest._should_binarize("paddle", True))

    def test_tat_toan_cuc_thi_khong_bo_doc_nao_bi(self):
        self.assertFalse(ingest._should_binarize("tesseract", False))
        self.assertFalse(ingest._should_binarize("paddle", False))

    def test_khong_truyen_thi_theo_cai_dat_chung(self):
        # None = lấy OCR_BINARIZE hiện hành (mặc định bật).
        self.assertEqual(ingest._should_binarize("tesseract"),
                         bool(ingest.OCR_BINARIZE))
        self.assertFalse(ingest._should_binarize("paddle"))


class SoNhanOcrTests(unittest.TestCase):
    """_ocr_worker_count: OCR song song nhưng phải chừa nhân cho model chat.

    Đo thật 29/08/2026: hợp đồng scan 107 nghìn ký tự mất 125 giây vì OCR
    tuần tự từng trang. Ăn hết nhân thì nhanh hơn, nhưng câu hỏi của người
    khác đứng hình vì model 14b không còn chỗ chạy.
    """

    def test_chua_lai_mot_nhan(self):
        self.assertEqual(ingest._ocr_worker_count(cpu=4), 3)
        self.assertEqual(ingest._ocr_worker_count(cpu=8), 4)   # trần 4

    def test_may_yeu_van_chay_duoc(self):
        self.assertEqual(ingest._ocr_worker_count(cpu=1), 1)
        self.assertEqual(ingest._ocr_worker_count(cpu=2), 1)

    def test_dat_tay_thi_theo_y_nguoi_van_hanh(self):
        self.assertEqual(ingest._ocr_worker_count(cpu=2, setting=6), 6)

    def test_dat_0_la_de_he_thong_tu_quyet(self):
        # 0 nghĩa là "không đặt" — phải rơi về cách tính theo số nhân.
        self.assertEqual(ingest._ocr_worker_count(cpu=4, setting=0), 3)

    def test_gia_tri_hien_hanh_hop_ly(self):
        self.assertGreaterEqual(ingest.OCR_WORKERS, 1)
        self.assertLessEqual(ingest.OCR_WORKERS, 8)


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
