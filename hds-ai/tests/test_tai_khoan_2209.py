"""Đưa tài khoản vào vận hành chính thức (22/09/2026).

Vì sao có bộ test này:

1. Trước đó mọi tài khoản mới nhận cùng mật khẩu "hds12345" ghi trong mã và
   sổ tay; seed tạo 5 tài khoản demo123 và GHI ĐÈ mật khẩu mỗi lần chạy lại.
   Nay mật khẩu tạm ngẫu nhiên, bắt đổi lần đầu, seed chỉ tạo admin và không
   đụng tài khoản đã có.
2. Sửa/khoá tài khoản chuyển từ SQL lên web — phải có chốt: không tự khoá
   mình, không khoá admin cuối cùng.
3. Trang đăng nhập là cửa ngoài cùng: có van chống dò mật khẩu.

Toàn bộ là logic thuần, KHÔNG chạm CSDL (update.sh chạy unittest ngay trên
máy chủ thật). Chạy: python -m unittest tests.test_tai_khoan_2209 -v
"""
import os
import threading
import types
import unittest
from unittest import mock

from fastapi import HTTPException

from app import api, auth, ra_soat_tai_khoan, seed_accounts


class MatKhauTamTests(unittest.TestCase):
    def test_du_dai_va_qua_duoc_chinh_sach(self):
        for _ in range(50):
            pw = auth.new_temp_password()
            self.assertEqual(len(pw), auth.TEMP_PASSWORD_LEN)
            self.assertIsNone(auth.kiem_tra_mat_khau_moi(pw), pw)

    def test_khong_co_ky_tu_de_nham(self):
        """0/O, 1/l/I bỏ hẳn — mật khẩu đọc qua điện thoại cũng không nhầm."""
        for _ in range(50):
            self.assertFalse(set("0O1lI") & set(auth.new_temp_password()))

    def test_moi_lan_moi_khac(self):
        self.assertEqual(len({auth.new_temp_password() for _ in range(30)}), 30)


class ChinhSachMatKhauTests(unittest.TestCase):
    def test_qua_ngan(self):
        self.assertIn("tối thiểu", auth.kiem_tra_mat_khau_moi("Ab1"))

    def test_phai_co_chu_va_so(self):
        self.assertIn("chữ và số", auth.kiem_tra_mat_khau_moi("abcdefgh"))
        self.assertIn("chữ và số", auth.kiem_tra_mat_khau_moi("12345678"))

    def test_cam_dung_lai_mat_khau_mac_dinh_cu(self):
        for pw in ("hds12345", "HDS12345", "admin123", "demo123"):
            self.assertIsNotNone(auth.kiem_tra_mat_khau_moi(pw), pw)

    def test_phai_khac_mat_khau_cu(self):
        self.assertIn("khác", auth.kiem_tra_mat_khau_moi("MatKhau99", cu="MatKhau99"))

    def test_khong_chua_ten_email(self):
        self.assertIsNotNone(
            auth.kiem_tra_mat_khau_moi("an.nguyen2026", email="an.nguyen@hdslaw.vn"))

    def test_mat_khau_tot(self):
        self.assertIsNone(auth.kiem_tra_mat_khau_moi("HdsLaw2026", cu="abc",
                                                     email="an.nguyen@hdslaw.vn"))


class ChuanHoaEmailTests(unittest.TestCase):
    def test_ha_chu_thuong_bo_khoang_trang(self):
        self.assertEqual(api._chuan_hoa_email("  An.Nguyen@HDSLaw.vn "), "an.nguyen@hdslaw.vn")

    def test_sai_dang_thi_422(self):
        for xau in ("", "khong-phai-email", "a@b", "a b@c.vn"):
            with self.assertRaises(HTTPException) as ctx:
                api._chuan_hoa_email(xau)
            self.assertEqual(ctx.exception.status_code, 422, xau)


class RangBuocVaiTests(unittest.TestCase):
    def test_vai_la(self):
        with self.assertRaises(HTTPException) as ctx:
            api._kiem_tra_vai_va_khach("sieu_admin", None)
        self.assertEqual(ctx.exception.status_code, 422)

    def test_khach_phai_co_ho_so(self):
        with self.assertRaises(HTTPException):
            api._kiem_tra_vai_va_khach("client_plus", None)

    def test_noi_bo_khong_gan_khach(self):
        with self.assertRaises(HTTPException):
            api._kiem_tra_vai_va_khach("chuyen_vien", 7)

    def test_hop_le(self):
        api._kiem_tra_vai_va_khach("client_free", 7)
        api._kiem_tra_vai_va_khach("tro_ly", None)


class ChotSuaTaiKhoanTests(unittest.TestCase):
    """Sửa/khoá tài khoản trên web phải không tự bắn vào chân."""

    def _goi(self, **kw):
        mac_dinh = dict(uid=5, nguoi_sua_id=1, vai_cu="chuyen_vien", vai_moi="chuyen_vien",
                        active_moi=True, so_admin_khac_dang_mo=1)
        mac_dinh.update(kw)
        return api._kiem_tra_sua_tai_khoan(**mac_dinh)

    def test_khong_tu_doi_vai_minh(self):
        with self.assertRaises(HTTPException) as ctx:
            self._goi(uid=1, vai_cu="admin", vai_moi="ban_qt")
        self.assertIn("chính mình", ctx.exception.detail)

    def test_khong_tu_khoa_minh(self):
        with self.assertRaises(HTTPException):
            self._goi(uid=1, vai_cu="admin", vai_moi="admin", active_moi=False)

    def test_khong_khoa_admin_cuoi_cung(self):
        with self.assertRaises(HTTPException) as ctx:
            self._goi(uid=5, vai_cu="admin", vai_moi="admin", active_moi=False,
                      so_admin_khac_dang_mo=0)
        self.assertIn("duy nhất", ctx.exception.detail)

    def test_khong_ha_vai_admin_cuoi_cung(self):
        with self.assertRaises(HTTPException):
            self._goi(uid=5, vai_cu="admin", vai_moi="chuyen_vien",
                      so_admin_khac_dang_mo=0)

    def test_con_admin_khac_thi_duoc(self):
        self._goi(uid=5, vai_cu="admin", vai_moi="chuyen_vien", so_admin_khac_dang_mo=1)
        self._goi(uid=5, vai_cu="admin", vai_moi="admin", active_moi=False,
                  so_admin_khac_dang_mo=2)

    def test_khoa_nhan_vien_thuong_khong_bi_can(self):
        self._goi(active_moi=False)


class VanDangNhapTests(unittest.TestCase):
    """Dò mật khẩu: quá LOGIN_RATE_MAX lượt trong cửa sổ là 429."""

    def _request(self, ip="203.0.113.7"):
        return types.SimpleNamespace(headers={}, client=types.SimpleNamespace(host=ip))

    def test_qua_so_lan_thi_429(self):
        with mock.patch.object(api, "_login_hits", {}), \
             mock.patch.object(api, "_login_hits_lock", threading.Lock()), \
             mock.patch.object(api, "LOGIN_RATE_MAX", 3):
            for _ in range(3):
                api._login_rate_check(self._request())
            with self.assertRaises(HTTPException) as ctx:
                api._login_rate_check(self._request())
            self.assertEqual(ctx.exception.status_code, 429)
            # IP khác không bị vạ lây
            api._login_rate_check(self._request(ip="198.51.100.2"))

    def test_mac_dinh_khong_tat(self):
        self.assertGreater(api.LOGIN_RATE_MAX, 0)


class SeedChiTaoAdminTests(unittest.TestCase):
    def test_mac_dinh_khong_co_tai_khoan_mau(self):
        with mock.patch.dict(os.environ, {"ADMIN_INITIAL_PASSWORD": ""}):
            ds = seed_accounts.tai_khoan_can_tao()
        self.assertEqual([t[0] for t in ds], [seed_accounts.ADMIN_EMAIL])
        self.assertEqual(ds[0][2], "admin")
        # Mật khẩu sinh ngẫu nhiên, không phải admin123
        self.assertNotIn(ds[0][3], auth.MAT_KHAU_MAC_DINH_CU)
        self.assertIsNone(auth.kiem_tra_mat_khau_moi(ds[0][3]))

    def test_demo_phai_xin_ro(self):
        ds = seed_accounts.tai_khoan_can_tao(demo=True)
        self.assertEqual(len(ds), 1 + len(seed_accounts.ACCOUNTS_DEMO))
        # Mật khẩu demo nằm trong danh sách mặc định cũ để ra_soat nhận ra
        for tk in seed_accounts.ACCOUNTS_DEMO:
            self.assertIn(tk[3], auth.MAT_KHAU_MAC_DINH_CU)

    def test_mat_khau_admin_tu_bien_moi_truong(self):
        with mock.patch.dict(os.environ, {"ADMIN_INITIAL_PASSWORD": "TuDatRieng2026"}):
            self.assertEqual(seed_accounts.tai_khoan_can_tao()[0][3], "TuDatRieng2026")


class RaSoatTaiKhoanTests(unittest.TestCase):
    def _tk(self, id, email, role, mac_dinh=None, active=True, last=None):
        return {"id": id, "email": email, "role": role, "active": active,
                "mac_dinh": mac_dinh, "last_login_at": last}

    def test_tai_khoan_mau_con_mat_khau_mac_dinh_thi_khoa(self):
        ds = ra_soat_tai_khoan.phan_loai([
            self._tk(1, "admin@hdslaw.vn", "admin", "admin123"),
            self._tk(2, "giamdoc@hdslaw.vn", "ban_qt", "demo123"),
            self._tk(3, "troly@hdslaw.vn", "tro_ly", "demo123"),
        ])
        hd = {t["email"]: t["hanh_dong"] for t in ds}
        self.assertEqual(hd["giamdoc@hdslaw.vn"], "khoa")
        self.assertEqual(hd["troly@hdslaw.vn"], "khoa")
        # admin duy nhất: KHÔNG khoá, chỉ bắt đổi
        self.assertEqual(hd["admin@hdslaw.vn"], "bat_doi_mat_khau")

    def test_nhan_vien_that_con_hds12345_chi_bat_doi(self):
        ds = ra_soat_tai_khoan.phan_loai([
            self._tk(1, "admin@hdslaw.vn", "admin"),
            self._tk(9, "an.nguyen@hdslaw.vn", "chuyen_vien", "hds12345", last="2026-09-20"),
        ])
        self.assertEqual(ds[1]["hanh_dong"], "bat_doi_mat_khau")

    def test_da_doi_mat_khau_thi_giu(self):
        ds = ra_soat_tai_khoan.phan_loai([
            self._tk(1, "admin@hdslaw.vn", "admin"),
            self._tk(2, "giamdoc@hdslaw.vn", "ban_qt", None, last="2026-09-01"),
        ])
        self.assertTrue(all(t["hanh_dong"] == "giu" for t in ds))

    def test_da_khoa_thi_khong_dong_toi(self):
        ds = ra_soat_tai_khoan.phan_loai([
            self._tk(1, "admin@hdslaw.vn", "admin"),
            self._tk(2, "troly@hdslaw.vn", "tro_ly", "demo123", active=False),
        ])
        self.assertEqual(ds[1]["hanh_dong"], "giu")


class MoTaVaiKhachTests(unittest.TestCase):
    """UserIn không còn mật khẩu mặc định ghi sẵn trong mã."""

    def test_user_in_mat_khau_mac_dinh_la_none(self):
        self.assertIsNone(api.UserIn(email="a@b.vn", full_name="A", role="tro_ly").password)


if __name__ == "__main__":
    unittest.main()
