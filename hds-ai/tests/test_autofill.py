"""Test bóc thông tin cá nhân từ hồ sơ (app/autofill.py).

Mẫu văn bản mô phỏng đúng ba loại hồ sơ hay được tải lên để tự điền bản nháp:
CCCD (song ngữ, giá trị rớt dòng), sơ yếu lý lịch (nhiều trường một dòng) và
CV. Kèm các ca OCR mất dấu và các ca PHẢI KHÔNG khớp để vá một nhãn không làm
regex nuốt nhầm chữ thường.
"""
import unittest

from app import autofill


CCCD_TEXT = """CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM
Độc lập - Tự do - Hạnh phúc
CĂN CƯỚC CÔNG DÂN
Số / No.: 049195003678
Họ và tên / Full name:
NGUYỄN THỊ NGÂN
Ngày sinh / Date of birth: 15/08/1995
Giới tính / Sex: Nữ    Quốc tịch / Nationality: Việt Nam
Quê quán / Place of origin: Hòa Vang, Đà Nẵng
Nơi thường trú / Place of residence:
25 Lê Lợi, Hải Châu, Đà Nẵng
Có giá trị đến / Date of expiry: 15/08/2035
"""

SO_YEU_TEXT = """SƠ YẾU LÝ LỊCH
1. Họ và tên: Nguyễn Thị Ngân
2. Sinh ngày: 15/08/1995        3. Giới tính: Nữ
4. Nơi thường trú: 25 Lê Lợi, Hải Châu, Đà Nẵng
5. Số CCCD: 049195003678 cấp ngày 20/01/2021 nơi cấp Cục Cảnh sát QLHC về TTXH
6. Dân tộc: Kinh    7. Tôn giáo: Không
8. Trình độ học vấn: Cử nhân Luật
Điện thoại: 0905123456  Email: ngan.nguyen@example.com
"""

CV_TEXT = """NGUYỄN THỊ NGÂN
Vị trí ứng tuyển: Chuyên viên pháp lý
Ngày sinh: 15/08/1995
Điện thoại: +84 905 123 456
Email: ngan.nguyen@example.com
Địa chỉ liên hệ: 25 Lê Lợi, Hải Châu, Đà Nẵng
KINH NGHIỆM LÀM VIỆC
2019 - nay: Trợ lý luật sư tại Công ty Luật ABC, phụ trách soạn thảo hợp đồng
"""


class ExtractCccdTests(unittest.TestCase):
    def setUp(self):
        self.fields = autofill.extract_person_fields(CCCD_TEXT)

    def test_ten_lay_tu_dong_duoi_nhan(self):
        self.assertEqual(self.fields.get("ho_ten"), "NGUYỄN THỊ NGÂN")

    def test_so_cccd_tu_nhan_song_ngu(self):
        self.assertEqual(self.fields.get("so_cccd"), "049195003678")

    def test_ngay_sinh_va_han(self):
        self.assertEqual(self.fields.get("ngay_sinh"), "15/08/1995")
        self.assertEqual(self.fields.get("gia_tri_den"), "15/08/2035")

    def test_hai_truong_tren_mot_dong(self):
        # "Nữ" phải thắng dù dòng chứa cả chữ "Việt Nam" phía sau.
        self.assertEqual(self.fields.get("gioi_tinh"), "Nữ")
        self.assertEqual(self.fields.get("quoc_tich"), "Việt Nam")

    def test_dia_chi_rot_dong(self):
        self.assertEqual(self.fields.get("noi_thuong_tru"),
                         "25 Lê Lợi, Hải Châu, Đà Nẵng")


class ExtractSoYeuTests(unittest.TestCase):
    def setUp(self):
        self.fields = autofill.extract_person_fields(SO_YEU_TEXT)

    def test_ten_viet_hoa_chu_dau(self):
        self.assertEqual(self.fields.get("ho_ten"), "Nguyễn Thị Ngân")

    def test_truong_giua_dong_khong_nuot_truong_ke(self):
        # "Dân tộc: Kinh    7. Tôn giáo: Không" — giá trị phải cắt trước nhãn kế.
        self.assertEqual(self.fields.get("dan_toc"), "Kinh")
        self.assertEqual(self.fields.get("ton_giao"), "Không")

    def test_cap_ngay_va_noi_cap_giua_dong(self):
        self.assertEqual(self.fields.get("ngay_cap"), "20/01/2021")
        self.assertEqual(self.fields.get("noi_cap"),
                         "Cục Cảnh sát QLHC về TTXH")

    def test_lien_lac(self):
        self.assertEqual(self.fields.get("dien_thoai"), "0905123456")
        self.assertEqual(self.fields.get("email"), "ngan.nguyen@example.com")

    def test_trinh_do(self):
        self.assertEqual(self.fields.get("trinh_do"), "Cử nhân Luật")


class ExtractCvTests(unittest.TestCase):
    def setUp(self):
        self.fields = autofill.extract_person_fields(CV_TEXT)

    def test_vi_tri_ung_tuyen(self):
        self.assertEqual(self.fields.get("chuc_danh"), "Chuyên viên pháp lý")

    def test_dien_thoai_dinh_dang_84(self):
        self.assertEqual(self.fields.get("dien_thoai"), "0905123456")

    def test_dia_chi_lien_he(self):
        self.assertEqual(self.fields.get("cho_o_hien_nay"),
                         "25 Lê Lợi, Hải Châu, Đà Nẵng")


class OcrMatDauTests(unittest.TestCase):
    """OCR hay trả chữ mất dấu — nhãn vẫn phải nhận ra."""

    def test_nhan_mat_dau(self):
        fields = autofill.extract_person_fields(
            "Ho va ten: TRAN VAN BINH\nNgay sinh: 02/09/1988\nSo CCCD: 038088001234")
        self.assertEqual(fields.get("ho_ten"), "TRAN VAN BINH")
        self.assertEqual(fields.get("ngay_sinh"), "02/09/1988")
        self.assertEqual(fields.get("so_cccd"), "038088001234")

    def test_ngay_bang_chu(self):
        fields = autofill.extract_person_fields("Ngày cấp: ngày 20 tháng 1 năm 2021")
        self.assertEqual(fields.get("ngay_cap"), "20/01/2021")

    def test_so_12_chu_so_tren_anh_the(self):
        # Ảnh OCR mất chữ nhãn nhưng còn dãy số — văn bản ngắn cỡ tấm thẻ.
        fields = autofill.extract_person_fields(
            "CAN CUOC CONG DAN\n049195003678\nNGUYEN THI NGAN")
        self.assertEqual(fields.get("so_cccd"), "049195003678")


class KhongKhopNhamTests(unittest.TestCase):
    """Các ca PHẢI KHÔNG khớp — nhãn lỏng là bóc nhầm dữ liệu người khác."""

    def test_so_yeu_khong_phai_nhan_so(self):
        fields = autofill.extract_person_fields("SƠ YẾU LÝ LỊCH TỰ THUẬT")
        self.assertNotIn("so_cccd", fields)

    def test_van_ban_dai_khong_vot_so_12_chu_so(self):
        # Hợp đồng dài chứa số tài khoản 12 số — không được đoán đó là CCCD.
        text = "ĐIỀU 5. Thanh toán vào tài khoản 123456789012 tại ngân hàng X.\n"
        text += "Nội dung khác về nghĩa vụ các bên trong hợp đồng dịch vụ.\n" * 40
        fields = autofill.extract_person_fields(text)
        self.assertNotIn("so_cccd", fields)

    def test_gioi_tinh_khong_lay_tu_quoc_tich(self):
        fields = autofill.extract_person_fields("Quốc tịch: Việt Nam")
        self.assertNotIn("gioi_tinh", fields)
        self.assertEqual(fields.get("quoc_tich"), "Việt Nam")

    def test_doan_van_dai_khong_thanh_gia_tri(self):
        long_line = "Quê quán: " + "quá trình sinh sống và làm việc " * 10
        fields = autofill.extract_person_fields(long_line)
        self.assertNotIn("que_quan", fields)


class MergeMissingTests(unittest.TestCase):
    def test_khong_de_du_lieu_nguoi_dung_da_go(self):
        merged = autofill.merge_missing(
            {"ho_ten": "Đã Gõ Tay", "so_cccd": ""},
            {"ho_ten": "TỪ HỒ SƠ", "so_cccd": "049195003678", "email": "a@b.vn"})
        self.assertEqual(merged["ho_ten"], "Đã Gõ Tay")   # người dùng thắng
        self.assertEqual(merged["so_cccd"], "049195003678")  # ô trống được điền
        self.assertEqual(merged["email"], "a@b.vn")

    def test_chiu_duoc_none(self):
        self.assertEqual(autofill.merge_missing(None, {"a": "1"}), {"a": "1"})


if __name__ == "__main__":
    unittest.main()
