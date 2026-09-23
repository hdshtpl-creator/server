"""Tab DUYỆT NHÃN 20/09/2026: vị trí trong cây thư mục, bộ lọc, duyệt nhanh.

Ba thứ dễ hỏng mà không ai thấy ngay:

  · VỊ TRÍ tài liệu. Người duyệt gán nhãn theo NGĂN chứa tệp; tính sai đường
    dẫn thì thẻ hiện một nơi còn tệp nằm một nơi khác — gán nhãn theo cái sai
    mà vẫn "có vẻ đúng".
  · BỘ LỌC. Giá trị người dùng phải đi bằng THAM SỐ; ghép thẳng vào SQL là mở
    cửa cho tên thư mục có dấu nháy phá câu lệnh. Tên ngăn có '%' hay '_'
    (ký tự đại diện của LIKE) phải được thoát, không thì lọc ra nhầm lô.
  · DUYỆT NHANH hàng loạt. Đây là đường DUY NHẤT trong hệ thống ghi nhãn cho
    nhiều tài liệu trong một cú bấm — chốt "hồ sơ khách phải có chủ sở hữu"
    tuột ở đây là hồ sơ khách này lọt vào tầm nhìn của người phòng khác.

db.session được vá bằng kết nối giả: không câu nào chạm Postgres thật —
deploy/update.sh chạy bộ test này ngay trên máy chủ đang phục vụ.
"""
import contextlib
import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from fastapi import HTTPException

from app import api, kho


ADMIN = {"id": 1, "role": "admin", "can_review": True, "is_banqt": True,
         "can_finance": True, "dept_ids": [], "dept_codes": []}


# ---------------------------------------------------------------------------
# 1. Vị trí trong cây thư mục kho
# ---------------------------------------------------------------------------
class ViTriTrongKho(unittest.TestCase):
    GOC = Path("/srv/hds/kho")

    def test_danh_tinh_bo_quet_cho_du_ca_cay(self):
        v = kho.vi_tri_trong_kho("local:9. HỒ SƠ KHÁCH HÀNG/[BH-07] Nguyễn An/4. Đơn.pdf",
                                 "/srv/hds/kho/9. HỒ SƠ KHÁCH HÀNG/[BH-07] Nguyễn An/4. Đơn.pdf",
                                 root=self.GOC)
        self.assertTrue(v["trong_kho"])
        self.assertEqual(v["ngan"], "9. HỒ SƠ KHÁCH HÀNG")
        self.assertEqual(v["thu_muc"], "9. HỒ SƠ KHÁCH HÀNG/[BH-07] Nguyễn An")
        self.assertEqual(v["ten_tep"], "4. Đơn.pdf")
        self.assertEqual(v["duoi"], ".pdf")

    def test_tep_ngay_goc_kho_khong_thuoc_ngan_nao(self):
        v = kho.vi_tri_trong_kho("local:ghi chú chung.docx", None, root=self.GOC)
        self.assertTrue(v["trong_kho"])
        self.assertIsNone(v["ngan"])
        self.assertIsNone(v["thu_muc"])
        self.assertEqual(v["ten_tep"], "ghi chú chung.docx")

    def test_nap_tu_hoi_thoai_khong_co_tep(self):
        v = kho.vi_tri_trong_kho(None, None, root=self.GOC)
        self.assertFalse(v["trong_kho"])
        self.assertIsNone(v["duong_dan"])
        self.assertIsNone(v["ten_tep"])

    def test_tep_ngoai_kho_van_cho_biet_ten_tep(self):
        """Tải lên qua web nằm ở data/raw/uploads, ngoài cây kho: không bịa ra
        đường dẫn trong kho, nhưng vẫn phải nói được tệp tên gì."""
        v = kho.vi_tri_trong_kho(None, "/srv/hds/data/raw/uploads/abc_hop-dong.docx",
                                 root=self.GOC)
        self.assertFalse(v["trong_kho"])
        self.assertIsNone(v["duong_dan"])
        self.assertEqual(v["ten_tep"], "abc_hop-dong.docx")
        self.assertEqual(v["duoi"], ".docx")

    def test_dau_gach_nguoc_windows_khong_lam_lech_cay(self):
        v = kho.vi_tri_trong_kho("local:1. VĂN BẢN PHÁP LUẬT\\2019\\Luật.docx", None,
                                 root=self.GOC)
        self.assertEqual(v["ngan"], "1. VĂN BẢN PHÁP LUẬT")
        self.assertEqual(v["ten_tep"], "Luật.docx")


# ---------------------------------------------------------------------------
# 2. Bộ lọc hàng chờ
# ---------------------------------------------------------------------------
class BoLocHangCho(unittest.TestCase):
    def test_khong_loc_thi_khong_them_dieu_kien(self):
        where, params = api._review_dieu_kien(None, None, None, None, None, None)
        self.assertEqual(where, [])
        self.assertEqual(params, [])

    def test_tu_khoa_tim_ca_trong_duong_dan(self):
        where, params = api._review_dieu_kien("bản án", None, None, None, None, None)
        self.assertEqual(len(where), 1)
        self.assertIn("drive_file_id ILIKE", where[0])
        self.assertEqual(params, ["%bản án%"] * 3)

    def test_gia_tri_nguoi_dung_khong_bao_gio_nam_trong_cau_lenh(self):
        doc = "'; DROP TABLE documents; --"
        where, params = api._review_dieu_kien(doc, None, None, None, None, None)
        self.assertNotIn("DROP TABLE", " ".join(where))
        self.assertIn(f"%{doc}%", params)

    def test_ky_tu_dai_dien_cua_like_bi_thoat(self):
        """Ngăn tên '100%_KH' mà không thoát thì LIKE khớp mọi thứ."""
        where, params = api._review_dieu_kien(None, "100%_KH", None, None, None, None)
        self.assertEqual(params, ["local:100\\%\\_KH/%"])
        self.assertIn("ESCAPE", where[0])

    def test_ngan_ngoai_kho_va_goc_kho_la_hai_tap_khac_nhau(self):
        ngoai, p_ngoai = api._review_dieu_kien(None, api.NGAN_NGOAI_KHO, None, None, None, None)
        goc, p_goc = api._review_dieu_kien(None, api.NGAN_GOC_KHO, None, None, None, None)
        self.assertEqual(p_ngoai, ["local:%"])
        self.assertEqual(p_goc, ["local:%", "local:%/%"])
        self.assertNotEqual(ngoai[0], goc[0])

    def test_khong_menh_de_nao_viet_thang_dau_phan_tram(self):
        """psycopg coi mọi '%' trong chuỗi SQL là chỗ chèn tham số. Một dấu %
        viết thẳng vào mệnh đề là câu lệnh vỡ ngay lúc chạy — mà bộ test logic
        thuần không thấy, vì nó không gọi CSDL."""
        for ngan in (api.NGAN_NGOAI_KHO, api.NGAN_GOC_KHO, "9. HỒ SƠ KHÁCH HÀNG"):
            where, _ = api._review_dieu_kien("tìm", ngan, "law", "local", "doc_loi", 7)
            cau = " AND ".join(where)
            self.assertEqual(cau.count("%"), cau.count("%s"),
                             f"còn dấu % lạc trong mệnh đề (ngăn={ngan}): {cau}")

    def test_loai_nguon_khach_di_bang_tham_so(self):
        where, params = api._review_dieu_kien(None, None, "ho_so_kh", "local", None, 237)
        self.assertEqual(params, ["ho_so_kh", "local", 237])
        self.assertEqual(len(where), 3)

    def test_trang_thai_doc_loi_dung_dung_nguong_cua_duyet_hang_loat(self):
        _where, params = api._review_dieu_kien(None, None, None, None, "doc_loi", None)
        self.assertEqual(params, [api.NGUONG_DOC_LOI])
        from app import duyet_hang_loat
        self.assertEqual(api.NGUONG_DOC_LOI, duyet_hang_loat.NGUONG_MAC_DINH)

    def test_trang_thai_bay_bi_bo_qua_chu_khong_vao_sql(self):
        where, params = api._review_dieu_kien(None, None, None, None, "xoa_het", None)
        self.assertEqual(where, [])
        self.assertEqual(params, [])

    def test_sap_xep_la_whitelist(self):
        self.assertIsNone(api._REVIEW_SAP_XEP.get("id; DROP TABLE documents"))
        for menh_de in api._REVIEW_SAP_XEP.values():
            self.assertNotIn(";", menh_de)


# ---------------------------------------------------------------------------
# 3. Tệp gốc còn trên đĩa không
# ---------------------------------------------------------------------------
class TepGoc(unittest.TestCase):
    def test_tep_co_that_thi_bao_kich_thuoc(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.txt"
            p.write_text("xin chào", encoding="utf-8")
            co_tep, size = api._tep_goc_info(str(p))
            self.assertTrue(co_tep)
            self.assertEqual(size, os.path.getsize(p))

    def test_khong_co_duong_dan_hoac_tep_da_mat(self):
        self.assertEqual(api._tep_goc_info(None), (False, None))
        self.assertEqual(api._tep_goc_info("/khong/co/that/x.pdf"), (False, None))


# ---------------------------------------------------------------------------
# 4. Duyệt nhanh hàng loạt
# ---------------------------------------------------------------------------
class _Cursor:
    """Con trỏ giả: câu SELECT kiểm tra hàng chờ trả về theo bảng cho sẵn."""

    def __init__(self, con_trong_hang_cho):
        self._con = con_trong_hang_cho
        self.lenh = []
        self._ket_qua = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.lenh.append((sql, params))
        if "FROM documents" in sql and "NOT label_verified" in sql:
            doc_id = params[0]
            self._ket_qua = (1,) if self._con.get(doc_id, True) else None
        else:
            self._ket_qua = None

    def fetchone(self):
        return self._ket_qua


class _Conn:
    def __init__(self, cur):
        self._cur = cur

    def cursor(self):
        return self._cur


def _endpoint(path, method):
    for route in api.app.routes:
        if (getattr(route, "path", None) == path
                and method in (getattr(route, "methods", None) or ())):
            return route.endpoint
    raise AssertionError(f"không thấy route {method} {path}")


def _item(doc_id, **thay):
    d = {"id": doc_id, "doc_type": "ho_so_kh", "access_level": "internal",
         "client_id": None}
    d.update(thay)
    return api.NhanhItem(**d)


class DuyetNhanh(unittest.TestCase):
    def setUp(self):
        self.endpoint = _endpoint("/review/duyet-nhanh", "POST")

    def _chay(self, items, con_trong_hang_cho=None):
        cur = _Cursor(con_trong_hang_cho or {})
        da_ghi, hieu_luc = [], []

        @contextlib.contextmanager
        def session(**_kw):
            yield _Conn(cur)

        with contextlib.ExitStack() as stack:
            stack.enter_context(unittest.mock.patch.object(api.db, "session", session))
            stack.enter_context(unittest.mock.patch.object(
                api.db, "audit", lambda *a, **k: None))
            stack.enter_context(unittest.mock.patch.object(
                api, "_ghi_nhan_duyet",
                lambda _cur, doc_id, body: (da_ghi.append(doc_id),
                                            body.doc_type in ("law", "an_le", "ban_an"))[1]))
            stack.enter_context(unittest.mock.patch.object(
                api.van_ban, "cap_nhat_hieu_luc", lambda _cur: hieu_luc.append(1)))
            ket_qua = self.endpoint(body=api.NhanhIn(items=items), user=ADMIN)
        return ket_qua, da_ghi, hieu_luc

    def test_duyet_ca_lo_binh_thuong(self):
        ket_qua, da_ghi, _ = self._chay([_item(11), _item(12)])
        self.assertEqual(ket_qua["da_duyet"], 2)
        self.assertEqual(da_ghi, [11, 12])
        self.assertEqual(ket_qua["bo_qua"], [])

    def test_ho_so_khach_thieu_chu_so_huu_bi_giu_lai(self):
        """Chốt client_doc_must_have_owner — KHÔNG được tuột ở đường hàng loạt."""
        ket_qua, da_ghi, _ = self._chay([
            _item(11, access_level="client", client_id=None),
            _item(12),
        ])
        self.assertEqual(da_ghi, [12])
        self.assertEqual(ket_qua["da_duyet"], 1)
        self.assertEqual([b["id"] for b in ket_qua["bo_qua"]], [11])
        self.assertIn("khách hàng", ket_qua["bo_qua"][0]["ly_do"])

    def test_ho_so_khach_co_chu_so_huu_thi_duyet(self):
        ket_qua, da_ghi, _ = self._chay(
            [_item(11, access_level="client", client_id=237)])
        self.assertEqual(da_ghi, [11])
        self.assertEqual(ket_qua["bo_qua"], [])

    def test_tai_lieu_da_roi_hang_cho_bi_bo_qua(self):
        ket_qua, da_ghi, _ = self._chay([_item(11), _item(12)],
                                        con_trong_hang_cho={11: False})
        self.assertEqual(da_ghi, [12])
        self.assertEqual(ket_qua["bo_qua"][0]["id"], 11)
        self.assertIn("hàng chờ", ket_qua["bo_qua"][0]["ly_do"])

    def test_hieu_luc_chi_soi_lai_MOT_lan_cho_ca_lo(self):
        _ket_qua, _da_ghi, hieu_luc = self._chay(
            [_item(i, doc_type="law") for i in (1, 2, 3)])
        self.assertEqual(len(hieu_luc), 1)

    def test_khong_cham_van_ban_luat_thi_khong_soi_hieu_luc(self):
        _ket_qua, _da_ghi, hieu_luc = self._chay([_item(11), _item(12)])
        self.assertEqual(hieu_luc, [])

    def test_lo_rong_va_lo_qua_lon_bi_chan(self):
        with self.assertRaises(HTTPException) as ctx:
            self._chay([])
        self.assertEqual(ctx.exception.status_code, 422)
        with self.assertRaises(HTTPException) as ctx:
            self._chay([_item(i) for i in range(api.TOI_DA_DUYET_NHANH + 1)])
        self.assertEqual(ctx.exception.status_code, 413)

    def test_nguoi_khong_co_quyen_duyet_bi_chan(self):
        nhan_vien = {**ADMIN, "role": "chuyen_vien", "can_review": False}
        with self.assertRaises(HTTPException) as ctx:
            self.endpoint(body=api.NhanhIn(items=[_item(11)]), user=nhan_vien)
        self.assertEqual(ctx.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
