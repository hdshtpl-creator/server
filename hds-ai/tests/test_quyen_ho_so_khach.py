"""Quyền MỞ hồ sơ khách — rag.can_open_doc — logic thuần, không cần CSDL.

Đây là cửa duy nhất cho cả tải về, xem trước, tra cứu và thẻ 360; sai một
nhánh ở đây là hoặc khoá sạch hồ sơ của chính phòng mình, hoặc mở hồ sơ khách
cho người ngoài phòng.

Thay đổi 15/09/2026 (quyết định của chủ dự án): tài liệu khách CHƯA GÁN phòng
phụ trách coi như dùng chung cho nội bộ. Trước đó 'department_id IS NULL' bị
xử như 'khác phòng' → 6.303 tài liệu khách đóng kín với mọi người trừ Ban QT,
vì bộ quét kho không gán phòng cho tài liệu nào.

Luật cần giữ:
  · NULL → mọi nội bộ mở được;
  · có phòng → chỉ người thuộc phòng đó (và Ban QT) mở được — KHÔNG được nới;
  · công nợ vẫn chặn trước mọi thứ, kể cả khi NULL, kể cả Ban QT;
  · ma trận access_rules vẫn phải cho phép loại tài liệu đó.
"""
import unittest

from app import rag

NHAN_VIEN = dict(role_level="chuyen_vien", dept_ids=[3], is_banqt=False)
PHONG_KHAC = dict(role_level="chuyen_vien", dept_ids=[5], is_banqt=False)
BAN_QT = dict(role_level="ban_qt", dept_ids=[], is_banqt=True)


def _doc(**thay):
    d = {"access_level": "client", "department_id": None, "doc_type": "ho_so_kh",
         "client_id": 237, "title": "Biên bản họp HĐQT"}
    d.update(thay)
    return d


def _mo(ai, doc, **kw):
    return rag.can_open_doc(ai["role_level"], ai["dept_ids"], ai["is_banqt"],
                            doc, **kw)


class HoSoKhachChuaGanPhong(unittest.TestCase):
    def test_chua_gan_phong_thi_moi_noi_bo_mo_duoc(self):
        self.assertTrue(_mo(NHAN_VIEN, _doc(department_id=None)))
        self.assertTrue(_mo(PHONG_KHAC, _doc(department_id=None)))

    def test_nguoi_khong_thuoc_phong_nao_van_mo_duoc(self):
        khong_phong = dict(role_level="tro_ly", dept_ids=[], is_banqt=False)
        self.assertTrue(_mo(khong_phong, _doc(department_id=None)))


class HoSoKhachDaGanPhong(unittest.TestCase):
    """Phần KHÔNG được nới: gán phòng vào là siết lại ngay."""

    def test_cung_phong_thi_mo_duoc(self):
        self.assertTrue(_mo(NHAN_VIEN, _doc(department_id=3)))

    def test_khac_phong_thi_bi_chan(self):
        self.assertFalse(_mo(PHONG_KHAC, _doc(department_id=3)))

    def test_khong_thuoc_phong_nao_bi_chan(self):
        khong_phong = dict(role_level="tro_ly", dept_ids=[], is_banqt=False)
        self.assertFalse(_mo(khong_phong, _doc(department_id=3)))


class CongNoVaBanQT(unittest.TestCase):
    def test_cong_no_chan_truoc_ca_khi_chua_gan_phong(self):
        cn = _doc(doc_type="cong_no", department_id=None)
        self.assertFalse(_mo(NHAN_VIEN, cn))
        # Chặn trước mọi điều kiện khác — kể cả Ban QT.
        self.assertFalse(_mo(BAN_QT, cn))

    def test_cong_no_mo_duoc_khi_co_quyen_tai_chinh(self):
        cn = _doc(doc_type="cong_no", department_id=None)
        self.assertTrue(_mo(NHAN_VIEN, cn, can_finance=True))

    def test_ban_qt_mo_duoc_moi_ho_so_khach(self):
        self.assertTrue(_mo(BAN_QT, _doc(department_id=3)))


class MaTranVanApDung(unittest.TestCase):
    """Nới phòng ban KHÔNG được phép qua mặt ma trận access_rules."""

    def test_ma_tran_cam_thi_van_chan_du_chua_gan_phong(self):
        rules = {("chuyen_vien", "*", "contract"): True}
        self.assertFalse(_mo(NHAN_VIEN, _doc(department_id=None), rules=rules,
                             dept_codes=["tranh-tung"]))

    def test_ma_tran_cho_phep_thi_mo_duoc(self):
        rules = {("chuyen_vien", "*", "ho_so_kh"): True}
        self.assertTrue(_mo(NHAN_VIEN, _doc(department_id=None), rules=rules,
                            dept_codes=["tranh-tung"]))

    def test_ma_tran_theo_dung_phong(self):
        rules = {("chuyen_vien", "tranh-tung", "ho_so_kh"): True}
        self.assertTrue(_mo(NHAN_VIEN, _doc(department_id=None), rules=rules,
                            dept_codes=["tranh-tung"]))
        self.assertFalse(_mo(NHAN_VIEN, _doc(department_id=None), rules=rules,
                             dept_codes=["shtt"]))


if __name__ == "__main__":
    unittest.main()
