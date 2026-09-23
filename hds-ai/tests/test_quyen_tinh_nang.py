"""Tài khoản khách: gắn hồ sơ khách + bật/tắt từng chức năng (20/09/2026).

Vì sao có bộ test này:

1. `rag.can_open_doc` vốn CHỈ viết cho người nội bộ — nó lọc theo phòng ban và
   không hề so mã khách. Chừng nào khách chỉ có khung trò chuyện thì không sao
   (mọi đường của họ đi qua khoá dòng RLS), nhưng các cửa tải tệp / rà soát /
   soạn thảo mở phiên CSDL bằng tài khoản chủ nên RLS KHÔNG áp. Mở chức năng
   cho khách mà quên nhánh này là khách A đọc được hồ sơ khách B.

2. Không tick gì thì tài khoản phải giữ nguyên hành vi cũ — nâng cấp không
   được âm thầm mở thêm cửa cho ai.

Chạy: python -m unittest tests.test_quyen_tinh_nang -v
"""
import unittest

from app import quyen_tinh_nang as q, rag


def _doc(access_level, client_id=None, doc_type="ho_so_kh", department_id=None):
    return {"access_level": access_level, "client_id": client_id,
            "doc_type": doc_type, "department_id": department_id}


class MoTaiLieuCuaKhachTests(unittest.TestCase):
    """Khách chỉ mở được hồ sơ của chính mình và tài liệu công khai."""

    def test_khach_mo_duoc_ho_so_cua_minh(self):
        self.assertTrue(rag.can_open_doc(
            "client_plus", [], False, _doc("client", client_id=7), client_id=7))

    def test_khach_KHONG_mo_duoc_ho_so_khach_khac(self):
        self.assertFalse(rag.can_open_doc(
            "client_plus", [], False, _doc("client", client_id=9), client_id=7))

    def test_khach_KHONG_mo_duoc_tai_lieu_noi_bo(self):
        self.assertFalse(rag.can_open_doc(
            "client_plus", [], False, _doc("internal", doc_type="ban_an"), client_id=7))

    def test_khach_mo_duoc_tai_lieu_cong_khai(self):
        self.assertTrue(rag.can_open_doc(
            "client_free", [], False, _doc("public", doc_type="law"), client_id=7))

    def test_phien_thieu_ma_khach_thi_chan_het(self):
        """Không biết khách nào thì thà chặn nhầm còn hơn lộ hồ sơ."""
        self.assertFalse(rag.can_open_doc(
            "client_pro", [], False, _doc("client", client_id=7), client_id=None))

    def test_cong_no_van_chan_truoc_moi_thu(self):
        self.assertFalse(rag.can_open_doc(
            "client_pro", [], False, _doc("client", client_id=7, doc_type="cong_no"),
            client_id=7))

    def test_khach_khong_muon_thanh_ban_qt(self):
        """Truyền nhầm is_banqt=True cho vai khách cũng không mở được hồ sơ
        khách khác — nhánh khách chặn TRƯỚC nhánh Ban quản trị."""
        self.assertFalse(rag.can_open_doc(
            "client_plus", [], True, _doc("client", client_id=9), client_id=7))

    def test_noi_bo_khong_bi_anh_huong(self):
        """Người nội bộ giữ nguyên luật cũ: hồ sơ khách chưa gán phòng thì mở."""
        self.assertTrue(rag.can_open_doc(
            "chuyen_vien", [3], False, _doc("client", client_id=9)))
        self.assertFalse(rag.can_open_doc(
            "chuyen_vien", [3], False, _doc("client", client_id=9, department_id=5)))


class MacDinhTheoVaiTests(unittest.TestCase):
    def test_khach_chua_tick_chi_co_hoi_dap(self):
        quyen = q.quyen_hieu_luc("client_free", None)
        self.assertTrue(quyen["chat"])
        for ten in ("dinh_kem", "tai_lieu", "kiem_tra", "soan_thao"):
            self.assertFalse(quyen[ten], ten)

    def test_noi_bo_chua_tick_mo_het(self):
        quyen = q.quyen_hieu_luc("chuyen_vien", None)
        self.assertTrue(all(quyen.values()))

    def test_tick_ghi_de_mac_dinh(self):
        quyen = q.quyen_hieu_luc("client_plus", {"tai_lieu": True, "soan_thao": True})
        self.assertTrue(quyen["tai_lieu"])
        self.assertTrue(quyen["soan_thao"])
        self.assertFalse(quyen["kiem_tra"])

    def test_tat_bot_cua_nguoi_noi_bo(self):
        quyen = q.quyen_hieu_luc("tro_ly", {"soan_thao": False})
        self.assertFalse(quyen["soan_thao"])
        self.assertTrue(quyen["chat"])

    def test_nhan_chuoi_json(self):
        self.assertTrue(q.quyen_hieu_luc("client_free", '{"tai_lieu": true}')["tai_lieu"])

    def test_json_hong_thi_ve_mac_dinh(self):
        self.assertFalse(q.quyen_hieu_luc("client_free", "{hỏng")["tai_lieu"])


class ChuanHoaTickTests(unittest.TestCase):
    def test_bo_ten_chuc_nang_la(self):
        self.assertEqual(q.chuan_hoa({"chat": True, "xoa_het_kho": True}),
                         {"chat": True})

    def test_ep_ve_true_false(self):
        self.assertEqual(q.chuan_hoa({"chat": 1, "tai_lieu": 0}),
                         {"chat": True, "tai_lieu": False})

    def test_rong_thi_ve_None_nghia_la_theo_vai(self):
        self.assertIsNone(q.chuan_hoa({}))
        self.assertIsNone(q.chuan_hoa(None))
        self.assertIsNone(q.chuan_hoa("bậy"))


class CoQuyenTests(unittest.TestCase):
    def test_doc_tu_dict_da_tinh_san(self):
        user = {"role": "client_free", "features": {"chat": True, "tai_lieu": False}}
        self.assertTrue(q.co_quyen(user, "chat"))
        self.assertFalse(q.co_quyen(user, "tai_lieu"))

    def test_chua_tinh_thi_tu_suy_theo_vai(self):
        self.assertTrue(q.co_quyen({"role": "chuyen_vien", "features": None}, "soan_thao"))
        self.assertFalse(q.co_quyen({"role": "client_free", "features": None}, "soan_thao"))

    def test_ten_chuc_nang_la_thi_khong_chan(self):
        """Gõ sai tên chốt không được âm thầm khoá tính năng của mọi người."""
        self.assertTrue(q.co_quyen({"role": "client_free", "features": {}}, "khong_co_that"))


class MoTaChoManHinhTests(unittest.TestCase):
    def test_danh_dau_muc_da_sua_tay(self):
        ds = q.mo_ta_quyen("client_plus", {"tai_lieu": True})
        theo = {m["ma"]: m for m in ds}
        self.assertTrue(theo["tai_lieu"]["bat"])
        self.assertFalse(theo["tai_lieu"]["theo_mac_dinh"])
        self.assertTrue(theo["chat"]["theo_mac_dinh"])

    def test_du_nam_chuc_nang(self):
        self.assertEqual(len(q.mo_ta_quyen("client_free", None)), 5)


if __name__ == "__main__":
    unittest.main()
