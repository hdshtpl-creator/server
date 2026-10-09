"""keo_drive: tên tệp từ Drive phải thành tên hợp lệ, ổn định trên đĩa."""
import unicodedata
import unittest
from unittest import mock

from app import keo_drive as kd


class TenTepTest(unittest.TestCase):
    def test_nfd_thanh_nfc(self):
        nfd = unicodedata.normalize("NFD", "1043. Chị Trang")
        self.assertEqual(kd.ten_an_toan(nfd), "1043. Chị Trang")
        self.assertTrue(unicodedata.is_normalized("NFC", kd.ten_an_toan(nfd)))

    def test_gach_cheo_va_ten_rong(self):
        self.assertEqual(kd.ten_an_toan("HĐ 01/2024/HĐLĐ.docx"), "HĐ 01-2024-HĐLĐ.docx")
        self.assertEqual(kd.ten_an_toan("   "), "_")
        self.assertEqual(kd.ten_an_toan(".."), "_..")

    def test_tab_an_thanh_mot_dau_cach(self):
        self.assertEqual(kd.ten_an_toan("1193. \tPhương Thuý"), "1193. Phương Thuý")
        self.assertEqual(kd.ten_an_toan("A ​B\r\nC"), "A B C")
        self.assertEqual(kd.ten_an_toan("HĐ  số 1"), "HĐ  số 1")

    def test_ten_qua_dai_giu_duoi(self):
        ten = kd.ten_an_toan("Hợp đồng " * 60 + ".pdf")
        self.assertTrue(ten.endswith(".pdf"))
        self.assertLessEqual(len(ten.encode("utf-8")), kd.TOI_DA_BYTE_TEN)

    def test_trung_ten(self):
        da = set()
        self.assertEqual(kd.ten_khong_trung("a.pdf", da), "a.pdf")
        self.assertEqual(kd.ten_khong_trung("A.pdf", da), "A (2).pdf")
        self.assertEqual(kd.ten_khong_trung("a.pdf", da), "a (3).pdf")


class LietKeTest(unittest.TestCase):
    def test_cay_va_dinh_dang_google(self):
        cay = {
            "goc": [
                {"id": "k1", "name": "1001. Khách A", "mimeType": kd.FOLDER},
                {"id": "g1", "name": "Ghi chú", "mimeType": "application/vnd.google-apps.document"},
                {"id": "s1", "name": "Lối tắt", "mimeType": kd.SHORTCUT},
                {"id": "f0", "name": "Form", "mimeType": "application/vnd.google-apps.form"},
            ],
            "k1": [
                {"id": "p1", "name": "HĐ.pdf", "mimeType": "application/pdf", "size": "10", "md5Checksum": "x"},
                {"id": "p2", "name": "HĐ.pdf", "mimeType": "application/pdf", "size": "11", "md5Checksum": "y"},
                {"id": "x1", "name": "Bảng", "mimeType": "application/vnd.google-apps.spreadsheet"},
            ],
        }
        with mock.patch.object(kd, "con_cua", lambda svc, fid: cay.get(fid, [])), \
                mock.patch.object(kd, "_svc_luong", lambda sa: None):
            tep, bo_qua, thu_muc = kd.liet_ke("sa.json", "goc", luong=3)
        self.assertEqual(thu_muc, ["1001. Khách A"])
        self.assertEqual([p for p, _ in tep], [
            "1001. Khách A/Bảng.xlsx", "1001. Khách A/HĐ (2).pdf", "1001. Khách A/HĐ.pdf",
            "Ghi chú.docx"])
        self.assertEqual(len(bo_qua), 2)

    def test_thu_muc_trung_ten_gop_ten_tep_co_dinh(self):
        # Drive 07/10: "1160. … AN PHÚC" có HAI thư mục cùng tên ở gốc.
        cay = {
            "goc": [
                {"id": "k2", "name": "1160. An Phúc", "mimeType": kd.FOLDER},
                {"id": "k1", "name": "1160. An Phúc ", "mimeType": kd.FOLDER},
            ],
            "k1": [{"id": "b", "name": "GP.docx", "mimeType": "x", "modifiedTime": "2024-02-01"},
                   {"id": "c", "name": "Khác.pdf", "mimeType": "x"}],
            "k2": [{"id": "a", "name": "GP.docx", "mimeType": "x", "modifiedTime": "2024-01-01"}],
        }
        for _ in range(3):  # thứ tự API trả về không được làm đổi tên
            with mock.patch.object(kd, "con_cua", lambda svc, fid: cay.get(fid, [])), \
                    mock.patch.object(kd, "_svc_luong", lambda sa: None):
                tep, _, thu_muc = kd.liet_ke("sa.json", "goc", luong=3)
            self.assertEqual(thu_muc, ["1160. An Phúc"])
            self.assertEqual([(p, f["id"]) for p, f in tep], [
                ("1160. An Phúc/GP (2).docx", "b"), ("1160. An Phúc/GP.docx", "a"),
                ("1160. An Phúc/Khác.pdf", "c")])
            cay["goc"].reverse()

    def test_ten_khong_duoi_that(self):
        da = {"hđ số 1. bản cuối"}
        self.assertEqual(kd.ten_khong_trung("HĐ số 1. Bản cuối", da), "HĐ số 1. Bản cuối (2)")


if __name__ == "__main__":
    unittest.main()
