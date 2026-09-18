"""
Bộ hồ sơ đã điền được LƯU lại để mở trong 7 ngày (18/09/2026).

Chạy: python -m unittest tests.test_ho_so_da_luu -v

Bốn thứ phải đứng vững:
  1. Lưu xong mở lại được — đúng file, đúng bảng đối chiếu.
  2. RIÊNG TƯ: người khác không đọc, không xoá, không thấy trong danh sách.
  3. Quá 7 ngày thì bản ghi tự rụng (cùng mốc với file .docx nó trỏ tới).
  4. Không để một người lấp đĩa: quá trần thì bản cũ nhất rơi trước; chuỗi
     và số dòng bị gọt.
"""
import tempfile
import time
import unittest
from pathlib import Path

from app import ho_so_da_luu as hs


def _ban_ghi(uid=7, ten="Bộ ĐKKD - Công ty A", **kw):
    mac_dinh = dict(
        user_id=uid, ten=ten, bo_id=3, bo_ten="Đăng ký kinh doanh",
        files=[{"token": "a" * 32, "ten_file": "1. Giay de nghi.docx",
                "ten_ket_qua": "1. Giay de nghi.docx", "so_trong": 2}],
        zip_token="b" * 32, so_o=124,
        da_dien=[{"khoa": "ten_cty", "literal": "{{TEN_CTY}}",
                  "gia_tri": "Công ty A", "nguon": "tờ khai"}],
        con_thieu=[{"khoa": "fax", "literal": "{{TSC.FAX}}", "goi_y": "Số fax"}],
    )
    mac_dinh.update(kw)
    return mac_dinh


class HoSoDaLuuTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._cu = hs.DATA_WORK
        hs.DATA_WORK = Path(self._tmp.name)

    def tearDown(self):
        hs.DATA_WORK = self._cu
        self._tmp.cleanup()

    # 1 — lưu rồi mở lại
    def test_luu_va_mo_lai(self):
        ghi = hs.luu(**_ban_ghi())
        self.assertRegex(ghi["ma"], r"^[0-9a-f]{32}$")
        doc = hs.lay(ghi["ma"], 7)
        self.assertEqual(doc["ten"], "Bộ ĐKKD - Công ty A")
        self.assertEqual(doc["files"][0]["ten_file"], "1. Giay de nghi.docx")
        self.assertEqual(doc["zip_token"], "b" * 32)
        self.assertEqual(doc["da_dien"][0]["gia_tri"], "Công ty A")
        self.assertEqual(doc["con_thieu"][0]["khoa"], "fax")
        self.assertEqual([d["ma"] for d in hs.danh_sach(7)], [ghi["ma"]])

    def test_danh_sach_moi_nhat_truoc(self):
        cu = hs.luu(**_ban_ghi(ten="cũ"), now=time.time() - 3600)
        moi = hs.luu(**_ban_ghi(ten="mới"))
        self.assertEqual([d["ma"] for d in hs.danh_sach(7)], [moi["ma"], cu["ma"]])

    def test_doi_ten(self):
        ghi = hs.luu(**_ban_ghi())
        self.assertEqual(hs.doi_ten(ghi["ma"], 7, "Tên mới")["ten"], "Tên mới")
        self.assertEqual(hs.lay(ghi["ma"], 7)["ten"], "Tên mới")
        # Tên rỗng thì giữ tên cũ, không để bản ghi mất nhãn.
        self.assertEqual(hs.doi_ten(ghi["ma"], 7, "   ")["ten"], "Tên mới")

    # 2 — riêng tư
    def test_nguoi_khac_khong_doc_khong_xoa(self):
        ghi = hs.luu(**_ban_ghi(uid=7))
        self.assertIsNone(hs.lay(ghi["ma"], 8))
        self.assertFalse(hs.xoa(ghi["ma"], 8))
        self.assertIsNone(hs.doi_ten(ghi["ma"], 8, "của tôi"))
        self.assertEqual(hs.danh_sach(8), [])
        self.assertIsNotNone(hs.lay(ghi["ma"], 7))     # vẫn còn nguyên

    def test_chu_xoa_duoc(self):
        ghi = hs.luu(**_ban_ghi())
        self.assertTrue(hs.xoa(ghi["ma"], 7))
        self.assertIsNone(hs.lay(ghi["ma"], 7))

    def test_ma_bay_khong_doc_duoc_gi(self):
        hs.luu(**_ban_ghi())
        for xau in ("", "..", "../../etc/passwd", "a" * 31, "Z" * 32, "x/y"):
            with self.subTest(ma=xau):
                self.assertIsNone(hs.lay(xau, 7))
                self.assertFalse(hs.xoa(xau, 7))

    # 3 — hết hạn
    def test_qua_han_thi_rung(self):
        cu = hs.luu(**_ban_ghi(), now=time.time() - (hs.GIU_NGAY * 86400 + 60))
        con = hs.luu(**_ban_ghi())
        self.assertEqual(hs.don_cu(), 1)
        self.assertIsNone(hs.lay(cu["ma"], 7))
        self.assertEqual([d["ma"] for d in hs.danh_sach(7)], [con["ma"]])

    def test_con_lai_ngay(self):
        gio = time.time()
        ghi = hs.luu(**_ban_ghi(), now=gio - 2 * 86400)
        self.assertAlmostEqual(hs.con_lai_ngay(ghi, gio), hs.GIU_NGAY - 2, places=2)
        het = hs.luu(**_ban_ghi(), now=gio - 99 * 86400)
        self.assertEqual(hs.con_lai_ngay(het, gio), 0.0)

    # 4 — trần và gọt
    def test_tran_moi_nguoi(self):
        that = hs.MAX_MOI_NGUOI
        hs.MAX_MOI_NGUOI = 3
        try:
            mas = [hs.luu(**_ban_ghi(ten=f"bộ {i}"))["ma"] for i in range(5)]
        finally:
            hs.MAX_MOI_NGUOI = that
        con = {d["ma"] for d in hs.danh_sach(7)}
        self.assertEqual(len(con), 3)
        self.assertNotIn(mas[0], con)          # cũ nhất rơi trước
        self.assertIn(mas[-1], con)

    def test_tran_cua_nguoi_nay_khong_dung_cua_nguoi_kia(self):
        that = hs.MAX_MOI_NGUOI
        hs.MAX_MOI_NGUOI = 2
        try:
            cua_8 = hs.luu(**_ban_ghi(uid=8, ten="của 8"))
            for i in range(4):
                hs.luu(**_ban_ghi(uid=7, ten=f"của 7 · {i}"))
        finally:
            hs.MAX_MOI_NGUOI = that
        self.assertIsNotNone(hs.lay(cua_8["ma"], 8))
        self.assertEqual(len(hs.danh_sach(7)), 2)

    def test_got_du_lieu_qua_kho(self):
        ghi = hs.luu(**_ban_ghi(
            ten="T" * 500,
            files=[{"token": "c" * 32, "ten_file": "x.docx"}, {"ten_file": "khong_token.docx"}],
            da_dien=[{"khoa": f"k{i}", "gia_tri": "v" * 2000} for i in range(hs.MAX_O + 50)],
        ))
        self.assertEqual(len(ghi["ten"]), hs.MAX_TEN)
        self.assertEqual([f["token"] for f in ghi["files"]], ["c" * 32])   # bỏ dòng thiếu token
        self.assertEqual(len(ghi["da_dien"]), hs.MAX_O)
        self.assertEqual(len(ghi["da_dien"][0]["gia_tri"]), hs.MAX_CHU)

    def test_khong_co_chu_thi_tu_choi(self):
        with self.assertRaises(ValueError):
            hs.luu(**_ban_ghi(uid=None))

    def test_dem_theo_nguoi(self):
        hs.luu(**_ban_ghi(uid=7))
        hs.luu(**_ban_ghi(uid=7))
        hs.luu(**_ban_ghi(uid=9))
        self.assertEqual(hs.dem_theo_nguoi(), {7: 2, 9: 1})

    def test_tep_hong_khong_lam_chet_danh_sach(self):
        ghi = hs.luu(**_ban_ghi())
        (hs.thu_muc() / "hong.json").write_text("{không phải json", encoding="utf-8")
        self.assertEqual([d["ma"] for d in hs.danh_sach(7)], [ghi["ma"]])


if __name__ == "__main__":
    unittest.main()
