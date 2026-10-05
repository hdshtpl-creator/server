"""Cửa tích hợp CRM (app/tich_hop.py + app/tich_hop_api.py, 28/09/2026) — THUẦN.

Không chạm CSDL (update.sh chạy unittest ngay trên máy chủ thật): mọi hàm truy
vấn đều vá; đĩa là thư mục tạm. Bốn thứ phải đúng tuyệt đối:
  · khoá hdsi_ và khoá hds_ không đi lẫn cửa nhau; thiếu quyền là 403 rõ tên;
  · cấp mã khách mới không đụng mã đã có trong CSDL LẪN trên đĩa;
  · tệp CRM gửi nằm ĐÚNG thư mục khách, danh tính local:, gửi lại cùng md5
    không làm gì, md5 khác là phiên bản mới, đổi tên là gỡ bản cũ;
  · chính sách duyệt 28/09: tự duyệt khi rác ≤ ngưỡng, 'off' = chính sách cũ.
"""
import contextlib
import json
import io
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

from app import auto_learn, kho, tich_hop

GOC = "9. HỒ SƠ KHÁCH HÀNG"
BAN_DO = ({"hop dong": {"doc_type": "contract"}}, {}, {"ho so khach hang"})


class DauVao(unittest.TestCase):
    def test_nguon(self):
        self.assertEqual(tich_hop.chuan_hoa_nguon("  CRM "), "crm")
        for xau in ("", "c", "CRM của Đức", "a/b", "x" * 31):
            with self.subTest(xau=xau):
                with self.assertRaises(tich_hop.LoiTichHop):
                    tich_hop.chuan_hoa_nguon(xau)

    def test_quyen_theo_thu_tu_va_khu_trung(self):
        self.assertEqual(tich_hop.chuan_hoa_quyen(["documents:write", "clients:read", "clients:read"]),
                         ["clients:read", "documents:write"])
        self.assertEqual(tich_hop.chuan_hoa_quyen("chat, clients:read"), ["clients:read", "chat"])
        # Mã cũ tiếng Việt vẫn được hiểu (khoá cấp trước 29/09/2026)
        self.assertEqual(tich_hop.chuan_hoa_quyen(["khach:doc", "tai_lieu:ghi"]),
                         ["clients:read", "documents:write"])
        self.assertEqual(tich_hop._quyen_tu_csdl('["khach:doc", "clients:read", "la"]'), ["clients:read"])
        with self.assertRaises(tich_hop.LoiTichHop):
            tich_hop.chuan_hoa_quyen(["admin:*"])
        with self.assertRaises(tich_hop.LoiTichHop):
            tich_hop.chuan_hoa_quyen([])

    def test_bo_quyen_mau_deu_hop_le(self):
        for ma, bo in tich_hop.BO_QUYEN_MAU.items():
            with self.subTest(bo=ma):
                self.assertEqual(tich_hop.chuan_hoa_quyen(bo["quyen"]),
                                 [q for q in tich_hop.QUYEN if q in bo["quyen"]])
        self.assertEqual(tich_hop.BO_QUYEN_MAU["chatbot"]["quyen"], ["chat"])
        self.assertNotIn("chat", tich_hop.BO_QUYEN_MAU["crm"]["quyen"])

    def test_khoa(self):
        raw, h, dau = tich_hop.sinh_khoa()
        self.assertTrue(raw.startswith("hdsi_"))
        self.assertEqual(h, tich_hop.bam_khoa(raw))
        self.assertEqual(dau, raw[:12])
        self.assertTrue(tich_hop.la_khoa_tich_hop(raw))
        self.assertFalse(tich_hop.la_khoa_tich_hop("hds_abc"))
        self.assertFalse(tich_hop.la_khoa_tich_hop(None))
        self.assertTrue(tich_hop.co_quyen({"quyen": ["chat"]}, "chat"))
        self.assertFalse(tich_hop.co_quyen({"quyen": ["chat"]}, "documents:write"))
        self.assertFalse(tich_hop.co_quyen(None, "chat"))

    def test_ma_ngoai_va_ma_khach(self):
        self.assertEqual(tich_hop.chuan_hoa_ma_ngoai(" HD-2026.001 "), "HD-2026.001")
        for xau in ("", "a/b", "../x", "x" * 101, "-dau"):
            with self.subTest(xau=xau):
                with self.assertRaises(tich_hop.LoiTichHop):
                    tich_hop.chuan_hoa_ma_ngoai(xau)
        self.assertEqual(tich_hop.chuan_hoa_ma_khach("1729"), "1729")
        with self.assertRaises(tich_hop.LoiTichHop):
            tich_hop.chuan_hoa_ma_khach("17 29")

    def test_ma_ngoai_mac_dinh(self):
        self.assertEqual(tich_hop.ma_ngoai_mac_dinh("1729", "Hợp đồng số 1.pdf"),
                         "1729__H_p_ng_s_1.pdf")
        self.assertEqual(tich_hop.ma_ngoai_mac_dinh("1729", "../../x.pdf"), "1729__x.pdf")
        self.assertLessEqual(len(tich_hop.ma_ngoai_mac_dinh("1", "a" * 300 + ".pdf")), 100)

    def test_ten_tep_an_toan(self):
        self.assertEqual(tich_hop.ten_tep_an_toan("../../etc/passwd"), "passwd")
        self.assertEqual(tich_hop.ten_tep_an_toan("Hợp đồng (bản ký).docx"), "Hợp đồng (bản ký).docx")
        self.assertEqual(tich_hop.ten_tep_an_toan("~$tmp.docx"), "tmp.docx")
        self.assertEqual(tich_hop.ten_tep_an_toan(".env"), "env")
        self.assertEqual(tich_hop.ten_tep_an_toan(""), "tai_lieu")

    def test_thu_muc_con(self):
        self.assertEqual(tich_hop.thu_muc_con_hop_le(""), [])
        self.assertEqual(tich_hop.thu_muc_con_hop_le("Hợp đồng\\2026/"), ["Hợp đồng", "2026"])
        for xau in ("a/b/c/d", "../x", "uploads", ".an", 'a:b'):
            with self.subTest(xau=xau):
                with self.assertRaises(tich_hop.LoiTichHop):
                    tich_hop.thu_muc_con_hop_le(xau)

    def test_ten_thu_muc_khach_bo_quet_tach_lai_duoc_ma(self):
        ten = tich_hop.ten_thu_muc_khach("1730", 'Công ty TNHH "A/B" <Việt Nam>')
        self.assertEqual(ten, "1730. Công ty TNHH A B Việt Nam")
        self.assertEqual(auto_learn._client_code_and_name(ten), ("1730", "Công ty TNHH A B Việt Nam"))
        self.assertEqual(tich_hop.ten_thu_muc_khach("5", ""), "5")
        ten_chu = tich_hop.ten_thu_muc_khach("TEST-1", "Khách thử")
        self.assertEqual(ten_chu, "[TEST-1] Khách thử")
        self.assertEqual(auto_learn._client_code_and_name(ten_chu), ("TEST-1", "Khách thử"))

    def test_ma_so_lon_nhat_dem_ca_csdl_lan_dia(self):
        ma_csdl = ["1043", "SUNGROUP", None, "0900"]
        thu_muc = ["1729. Công ty X", "[ZEGNA] Zegna", "1043.Chị Trang", "9. Khách đời đầu",
                   "20260912. Gói export", "Không mã"]
        self.assertEqual(tich_hop.ma_so_lon_nhat(ma_csdl, thu_muc), 1729)
        self.assertEqual(tich_hop.ma_so_lon_nhat([], []), 0)
        self.assertEqual(tich_hop.ma_so_lon_nhat(["2000"], ["1999. A"]), 2000)

    def test_suy_trang_thai(self):
        duyet = {"active": True, "approved": True, "label_verified": True}
        cho = {"active": True, "approved": False, "label_verified": False}
        go = {"active": False, "approved": True, "label_verified": True}
        self.assertEqual(tich_hop.suy_trang_thai("da_nhan", None), "da_nhan")
        self.assertEqual(tich_hop.suy_trang_thai("da_nhan", duyet), "da_hoc")
        self.assertEqual(tich_hop.suy_trang_thai("cho_duyet", duyet), "da_hoc")
        self.assertEqual(tich_hop.suy_trang_thai("da_hoc", cho), "cho_duyet")
        self.assertEqual(tich_hop.suy_trang_thai("dang_hoc", cho), "dang_hoc")
        self.assertEqual(tich_hop.suy_trang_thai("da_hoc", go), "da_go")
        self.assertEqual(tich_hop.suy_trang_thai("da_go", duyet), "da_go")
        self.assertEqual(tich_hop.suy_trang_thai("loi", None), "loi")


class ChinhSachDuyet(unittest.TestCase):
    SACH = "Hợp đồng dịch vụ pháp lý giữa Công ty Luật HDS và khách hàng về việc tư vấn thường xuyên. " * 5
    RAC = "xq zzt kkf pqw mnb vcx ; :: ,, hgf dsa ~ ` | \\ ^^ %% qwe rty" * 5

    def test_tu_duyet_khi_rac_duoi_nguong(self):
        ok, ty_le, ly_do = auto_learn.quyet_dinh_duyet(self.SACH, ".pdf", True, False, nguong=0.2)
        self.assertTrue(ok, ly_do)
        self.assertLess(ty_le, 0.2)
        self.assertTrue(ly_do.endswith("duoi_nguong"))

    def test_cho_duyet_khi_rac_qua_nguong(self):
        ok, ty_le, ly_do = auto_learn.quyet_dinh_duyet(self.RAC, ".docx", True, True, nguong=0.2)
        self.assertFalse(ok)
        self.assertGreater(ty_le, 0.2)
        self.assertTrue(ly_do.endswith("qua_nguong"))

    def test_van_ban_rong_khong_tu_duyet(self):
        ok, ty_le, _ = auto_learn.quyet_dinh_duyet("", ".docx", True, True, nguong=0.2)
        self.assertFalse(ok)
        self.assertEqual(ty_le, 1.0)

    def test_bat_buoc_duyet_thang_moi_cau_hinh(self):
        ok, _, ly_do = auto_learn.quyet_dinh_duyet(self.SACH, ".docx", True, True,
                                                    force_pending=True, nguong=1.0)
        self.assertFalse(ok)
        self.assertEqual(ly_do, "bat_buoc_duyet")

    def test_off_quay_ve_chinh_sach_cu(self):
        with mock.patch.object(auto_learn, "AUTO_APPROVE", True), \
                mock.patch.object(auto_learn, "APPROVE_PDF", False):
            ok_pdf, _, ly_do = auto_learn.quyet_dinh_duyet(self.SACH, ".pdf", True, False, nguong=None)
            ok_docx, _, _ = auto_learn.quyet_dinh_duyet(self.SACH, ".docx", True, False, nguong=None)
        self.assertFalse(ok_pdf)
        self.assertEqual(ly_do, "pdf_cho_duyet")
        self.assertTrue(ok_docx)

    def test_nguong_doc_tu_cai_dat(self):
        with mock.patch("app.settings.get", lambda k, d=None: {"tu_duyet_nguong_rac": "0.35"}.get(k, d)):
            self.assertEqual(auto_learn.nguong_tu_duyet(), 0.35)
        with mock.patch("app.settings.get", lambda k, d=None: {"tu_duyet_nguong_rac": "off"}.get(k, d)):
            self.assertIsNone(auto_learn.nguong_tu_duyet())
        with mock.patch("app.settings.get", lambda k, d=None: {"tu_duyet_nguong_rac": "xyz"}.get(k, d)):
            self.assertEqual(auto_learn.nguong_tu_duyet(), 0.2)
        with mock.patch("app.settings.get", lambda k, d=None: {"tu_duyet_nguong_rac": "-1"}.get(k, d)):
            self.assertIsNone(auto_learn.nguong_tu_duyet())


class KhoaGhiNganKhach(unittest.TestCase):
    """Cài đặt kho_khach_chi_doc: web không tải/tạo thư mục trong ngăn khách."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        (self.root / GOC / "1000. Anh A").mkdir(parents=True)
        (self.root / "3. HỢP ĐỒNG MẪU").mkdir()
        self.patches = [
            mock.patch.object(kho, "library_root", lambda: self.root),
            mock.patch.object(kho, "_ban_do_nhan", lambda: BAN_DO),
            mock.patch("app.settings.get", lambda k, d=None: "true" if k == "kho_khach_chi_doc" else d),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_chan_ngan_khach_nhung_ngan_khac_van_mo(self):
        with self.assertRaises(kho.LoiKho) as ctx:
            kho.cho_tai_len(f"{GOC}/1000. Anh A", "hd.docx")
        self.assertIn("CRM", str(ctx.exception))
        with self.assertRaises(kho.LoiKho):
            kho.tao_thu_muc(GOC, "1001. Chị B")
        self.assertEqual(kho.cho_tai_len("3. HỢP ĐỒNG MẪU", "mau.docx"),
                         self.root / "3. HỢP ĐỒNG MẪU" / "mau.docx")

    def test_tat_cai_dat_thi_mo_lai(self):
        with mock.patch("app.settings.get", lambda k, d=None: "false"):
            self.assertEqual(kho.cho_tai_len(f"{GOC}/1000. Anh A", "hd.docx"),
                             self.root / GOC / "1000. Anh A" / "hd.docx")


class ThuMucKhachTrenDia(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        for ten in ("1000. Anh A", "1043.Chị Trang", "[ZEGNA] Zegna", "Không mã", "~$rac"):
            (self.root / GOC / ten).mkdir(parents=True)
        self.patches = [
            mock.patch.object(kho, "library_root", lambda: self.root),
            mock.patch.object(kho, "_ban_do_nhan", lambda: BAN_DO),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_tim_theo_ma_khong_phan_biet_hoa_thuong(self):
        self.assertEqual(tich_hop.thu_muc_khach_tren_dia("1043").name, "1043.Chị Trang")
        self.assertEqual(tich_hop.thu_muc_khach_tren_dia("zegna").name, "[ZEGNA] Zegna")
        self.assertIsNone(tich_hop.thu_muc_khach_tren_dia("9999"))

    def test_tao_thu_muc_moi_dung_ngan_khach(self):
        d = tich_hop.thu_muc_khach("1044", "Công ty Mới")
        self.assertEqual(d, self.root / GOC / "1044. Công ty Mới")
        self.assertTrue(d.is_dir())
        # Gọi lại thì dùng lại, không tạo thư mục thứ hai cùng mã
        self.assertEqual(tich_hop.thu_muc_khach("1044", "Tên khác"), d)
        with self.assertRaises(tich_hop.LoiTichHop):
            tich_hop.thu_muc_khach("7777", "X", tao=False)

    def test_ma_ke_tiep_dem_ca_thu_muc_chua_co_ban_ghi(self):
        with mock.patch.object(tich_hop.db, "session") as s:
            cur = mock.MagicMock()
            cur.fetchall.return_value = [("1000",), ("SUNGROUP",)]
            s.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = cur
            self.assertEqual(tich_hop.ma_khach_ke_tiep(), "1044")


class NhanTaiLieu(unittest.TestCase):
    """Luồng nhận tệp với kho giả trên đĩa tạm và CSDL ánh xạ giả trong bộ nhớ."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        (self.root / GOC / "1000. Anh A").mkdir(parents=True)
        self.thung = self.root.parent / (self.root.name + "_da_go")
        self.pb_dir = self.root.parent / (self.root.name + "_phien_ban")
        self.anh_xa: dict = {}
        self.hang_doi: list = []
        self.phien_ban: list = []
        self.chia_se = False
        self.khoa = {"id": 3, "nguon": "crm", "quyen": ["clients:read", "documents:write"]}
        khach = {"1000": {"id": 7, "ten": "Anh A", "ma": "1000"},
                 "1001": {"id": 8, "ten": "Chị B", "ma": "1001"}}

        def _luu(nguon, ma_ngoai, khoa_kho, checksum, chu, ten_file, trang_thai,
                 khoa_id=None, meta=None, loi=None):
            self.anh_xa[(nguon, ma_ngoai)] = {
                "nguon": nguon, "ma_ngoai": ma_ngoai, "khoa_kho": khoa_kho, "checksum": checksum,
                "client_id": chu.get("client_id"), "employee_id": chu.get("employee_id"),
                "loai": chu["loai"], "ten_file": ten_file, "trang_thai": trang_thai,
                "loi": loi, "meta": meta, "khoa_id": khoa_id, "created_at": None, "updated_at": None}

        def _tt(nguon, ma_ngoai, khoa=None):
            ax = self.anh_xa[(nguon, ma_ngoai)]
            return tich_hop._dong_trang_thai(ax, None, "1000")

        phien = mock.MagicMock()
        phien.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value \
            .fetchone.return_value = (0,)
        self.patches = [
            mock.patch.object(kho, "library_root", lambda: self.root),
            mock.patch.object(kho, "_ban_do_nhan", lambda: BAN_DO),
            mock.patch.object(kho, "thung_da_go", lambda: self.thung),
            mock.patch.object(tich_hop, "thu_muc_phien_ban", lambda: self.pb_dir),
            mock.patch.object(tich_hop.db, "session", phien),
            mock.patch.object(tich_hop, "khach_theo_ma",
                              lambda ma, kem_thu_muc=True: khach.get(ma)),
            mock.patch.object(tich_hop, "_anh_xa", lambda n, m: self.anh_xa.get((n, m))),
            mock.patch.object(tich_hop, "_luu_anh_xa", _luu),
            mock.patch.object(tich_hop, "_cap_nhat_trang_thai",
                              lambda n, m, tt, loi=None: self.anh_xa[(n, m)].update(
                                  {"trang_thai": tt, "loi": loi})),
            mock.patch.object(tich_hop, "_tai_lieu_cung_md5", lambda md5, chu: None),
            mock.patch.object(tich_hop, "_tai_lieu_theo_khoa_kho", lambda k: None),
            mock.patch.object(tich_hop, "_con_anh_xa_khac", lambda n, m, k: self.chia_se),
            mock.patch.object(tich_hop, "_ma_ngoai_theo_khoa", lambda n, ks: {}),
            mock.patch.object(tich_hop, "_so_phien_ban_ke_tiep",
                              lambda n, m: 1 + sum(1 for x in self.phien_ban if x[:2] == (n, m))),
            mock.patch.object(tich_hop, "_ghi_phien_ban",
                              lambda *a: self.phien_ban.append(a)),
            mock.patch.object(tich_hop, "_audit_nhan", lambda *a, **k: None),
            mock.patch.object(tich_hop, "trang_thai", _tt),
            mock.patch.object(tich_hop, "xep_hang_hoc", lambda n, m: self.hang_doi.append((n, m))),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()
        import shutil
        for d in (self.thung, self.pb_dir):
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)

    def _ban_luu(self, i=0):
        """(số, tên tệp, nội dung, lý do) của phiên bản đã lưu thứ i."""
        nguon, ma_ngoai, so, ten, _md5, _kt, duong_dan, ly_do = self.phien_ban[i]
        return so, ten, Path(duong_dan).read_bytes(), ly_do

    def test_dat_dung_thu_muc_khach_va_xep_hang_hoc(self):
        r = tich_hop.nhan_tai_lieu(self.khoa, "1000", "HD-1", "Hợp đồng.docx", b"noi dung",
                                   thu_muc_con="Hợp đồng/2026")
        self.assertTrue(r["ok"])
        self.assertEqual(r["ket_qua"], "da_nhan")
        self.assertEqual(r["duong_dan"], f"{GOC}/1000. Anh A/Hợp đồng/2026/Hợp đồng.docx")
        self.assertTrue((self.root / r["duong_dan"]).is_file())
        ax = self.anh_xa[("crm", "HD-1")]
        self.assertEqual(ax["khoa_kho"], "local:" + r["duong_dan"])
        self.assertEqual((ax["trang_thai"], ax["loai"], ax["client_id"]), ("da_nhan", "khach", 7))
        self.assertEqual(self.hang_doi, [("crm", "HD-1")])
        self.assertEqual(self.phien_ban, [])          # tệp mới: không có gì để lưu
        # Không để lại tệp tạm nào bộ quét có thể nhặt
        self.assertEqual([p.name for p in (self.root / GOC / "1000. Anh A" / "Hợp đồng" / "2026").iterdir()],
                         ["Hợp đồng.docx"])

    def test_gui_lai_cung_md5_khong_lam_gi(self):
        tich_hop.nhan_tai_lieu(self.khoa, "1000", "HD-1", "hd.docx", b"v1")
        r = tich_hop.nhan_tai_lieu(self.khoa, "1000", "HD-1", "hd.docx", b"v1")
        self.assertEqual(r["ket_qua"], "khong_doi")
        self.assertEqual(len(self.hang_doi), 1)
        self.assertEqual(self.phien_ban, [])

    def test_md5_khac_la_phien_ban_moi_va_ban_cu_duoc_luu(self):
        tich_hop.nhan_tai_lieu(self.khoa, "1000", "HD-1", "hd.docx", b"v1")
        r = tich_hop.nhan_tai_lieu(self.khoa, "1000", "HD-1", "hd.docx", b"v2 dai hon")
        self.assertEqual(r["ket_qua"], "phien_ban_moi")
        self.assertEqual((self.root / r["duong_dan"]).read_bytes(), b"v2 dai hon")
        self.assertEqual(len(list((self.root / GOC / "1000. Anh A").iterdir())), 1)
        self.assertEqual(self._ban_luu(0), (1, "hd.docx", b"v1", "thay_ban"))
        # Bản lưu nằm NGOÀI kho — bộ quét không học lại bản cũ
        self.assertNotIn(self.root, Path(self.phien_ban[0][6]).parents)
        tich_hop.nhan_tai_lieu(self.khoa, "1000", "HD-1", "hd.docx", b"v3")
        self.assertEqual(self._ban_luu(1)[:3], (2, "hd.docx", b"v2 dai hon"))

    def test_doi_ten_tep_thi_luu_va_go_ban_cu(self):
        r1 = tich_hop.nhan_tai_lieu(self.khoa, "1000", "HD-1", "cu.docx", b"v1")
        r2 = tich_hop.nhan_tai_lieu(self.khoa, "1000", "HD-1", "moi.docx", b"v2")
        self.assertFalse((self.root / r1["duong_dan"]).exists())
        self.assertTrue((self.root / r2["duong_dan"]).is_file())
        self.assertTrue((self.thung / r1["duong_dan"]).is_file())
        self.assertEqual(self.anh_xa[("crm", "HD-1")]["khoa_kho"], "local:" + r2["duong_dan"])
        self.assertEqual(self._ban_luu(0), (1, "cu.docx", b"v1", "doi_ten"))

    def test_trung_ten_voi_tep_khac_thi_them_hau_to(self):
        tich_hop.nhan_tai_lieu(self.khoa, "1000", "HD-1", "hd.docx", b"a")
        r = tich_hop.nhan_tai_lieu(self.khoa, "1000", "HD-2", "hd.docx", b"b")
        self.assertEqual(r["ten_file"], "hd [HD-2].docx")
        self.assertEqual((self.root / r["duong_dan"]).read_bytes(), b"b")

    def test_tep_dung_chung_khong_bi_ghi_de_hay_go(self):
        r1 = tich_hop.nhan_tai_lieu(self.khoa, "1000", "HD-1", "hd.docx", b"v1")
        self.chia_se = True       # một mã ngoài khác cũng trỏ tệp này
        r2 = tich_hop.nhan_tai_lieu(self.khoa, "1000", "HD-1", "hd.docx", b"v2")
        self.assertEqual((self.root / r1["duong_dan"]).read_bytes(), b"v1")
        self.assertEqual(r2["ten_file"], "hd [HD-1].docx")
        self.assertFalse(self.thung.exists())

    def test_ma_ngoai_dang_thuoc_ho_so_khac_thi_409(self):
        tich_hop.nhan_tai_lieu(self.khoa, "1000", "HD-1", "hd.docx", b"v1")
        with self.assertRaises(tich_hop.LoiTichHop) as c:
            tich_hop.nhan_tai_lieu(self.khoa, "1001", "HD-1", "hd.docx", b"v2")
        self.assertEqual(c.exception.status, 409)

    def test_cung_khach_da_co_tep_y_het_thi_chi_gan_anh_xa(self):
        co_san = {"id": 55, "drive_file_id": f"local:{GOC}/1000. Anh A/cu/hd.pdf",
                  "approved": True, "label_verified": True, "active": True,
                  "extraction_status": "ready", "ty_le_rac": 0.01, "title": "HĐ"}
        with mock.patch.object(tich_hop, "_tai_lieu_cung_md5", lambda md5, chu: co_san):
            r = tich_hop.nhan_tai_lieu(self.khoa, "1000", "HD-9", "hd.pdf", b"%PDF")
        self.assertEqual(r["ket_qua"], "da_co_trong_kho")
        self.assertEqual(self.anh_xa[("crm", "HD-9")]["khoa_kho"], co_san["drive_file_id"])
        self.assertEqual(self.anh_xa[("crm", "HD-9")]["trang_thai"], "da_hoc")
        self.assertFalse((self.root / GOC / "1000. Anh A" / "hd.pdf").exists())
        self.assertEqual(self.hang_doi, [])

    def test_chan_dau_vao_xau(self):
        with self.assertRaises(tich_hop.LoiTichHop) as c1:
            tich_hop.nhan_tai_lieu(self.khoa, "1000", "HD-1", "virus.exe", b"x")
        self.assertEqual(c1.exception.status, 415)
        with self.assertRaises(tich_hop.LoiTichHop) as c2:
            tich_hop.nhan_tai_lieu(self.khoa, "9999", "HD-1", "hd.docx", b"x")
        self.assertEqual(c2.exception.status, 404)
        with self.assertRaises(tich_hop.LoiTichHop) as c3:
            tich_hop.nhan_tai_lieu(self.khoa, "1000", "HD-1", "hd.docx", b"x" * 2_000_000,
                                   gioi_han_mb=1)
        self.assertEqual(c3.exception.status, 413)
        with self.assertRaises(tich_hop.LoiTichHop):
            tich_hop.nhan_tai_lieu(self.khoa, "1000", "HD-1", "hd.docx", b"")
        with self.assertRaises(tich_hop.LoiTichHop):
            tich_hop.nhan_tai_lieu(self.khoa, "1000", "HD-1", "hd.docx", b"x", meta=["x"])
        # Không có gì lọt ra đĩa khi bị chặn
        self.assertEqual(list((self.root / GOC / "1000. Anh A").iterdir()), [])

    def test_hoc_mot_cap_nhat_trang_thai_theo_ket_qua(self):
        tich_hop.nhan_tai_lieu(self.khoa, "1000", "HD-1", "hd.docx", b"v1")
        with mock.patch.object(kho, "hoc_file", lambda rel, uid, auto_approve=False:
                               {"trang_thai": "da_hoc"}):
            self.assertEqual(tich_hop.hoc_mot("crm", "HD-1"), "da_hoc")
        with mock.patch.object(kho, "hoc_file", lambda rel, uid, auto_approve=False:
                               {"trang_thai": "cho_duyet"}):
            self.assertEqual(tich_hop.hoc_mot("crm", "HD-1"), "cho_duyet")

        def _hong(rel, uid, auto_approve=False):
            raise kho.LoiKho("Không học được: PDF không có lớp chữ")
        with mock.patch.object(kho, "hoc_file", _hong):
            self.assertEqual(tich_hop.hoc_mot("crm", "HD-1"), "loi")
        self.assertIn("lớp chữ", self.anh_xa[("crm", "HD-1")]["loi"])
        self.assertIsNone(tich_hop.hoc_mot("crm", "khong-co"))

    def test_go_luu_ban_cuoi_roi_go(self):
        r1 = tich_hop.nhan_tai_lieu(self.khoa, "1000", "HD-1", "hd.docx", b"v1")
        r = tich_hop.go("crm", "HD-1", self.khoa)
        self.assertEqual((r["ket_qua"], r["phien_ban_luu"]), ("da_go", 1))
        self.assertFalse((self.root / r1["duong_dan"]).exists())
        self.assertTrue((self.thung / r1["duong_dan"]).is_file())
        self.assertEqual(self._ban_luu(0), (1, "hd.docx", b"v1", "go"))
        self.assertEqual(self.anh_xa[("crm", "HD-1")]["trang_thai"], "da_go")
        self.assertEqual(tich_hop.go("crm", "HD-1", self.khoa)["ket_qua"], "da_go_truoc_do")
        with self.assertRaises(tich_hop.LoiTichHop) as c:
            tich_hop.go("crm", "khong-co", self.khoa)
        self.assertEqual(c.exception.status, 404)
        with self.assertRaises(tich_hop.LoiTichHop) as c410:
            tich_hop.tep_hien_tai("crm", "HD-1", self.khoa)
        self.assertEqual(c410.exception.status, 410)

    def test_tai_ve_ban_hien_tai(self):
        tich_hop.nhan_tai_lieu(self.khoa, "1000", "HD-1", "hd.docx", b"v1")
        p, ten, md5 = tich_hop.tep_hien_tai("crm", "HD-1", self.khoa)
        self.assertEqual((p.read_bytes(), ten), (b"v1", "hd.docx"))
        self.assertEqual(md5, __import__("hashlib").md5(b"v1").hexdigest())

    def test_liet_ke_moi_tep_ke_ca_tep_cu_va_tai_ve_theo_duong_dan(self):
        cu = self.root / GOC / "1000. Anh A" / "cu" / "giay phep.pdf"
        cu.parent.mkdir(parents=True)
        cu.write_bytes(b"%PDF cu")
        (self.root / GOC / "1000. Anh A" / "Thumbs.db").write_bytes(b"x")
        tich_hop.nhan_tai_lieu(self.khoa, "1000", "HD-1", "hd.docx", b"moi")
        with mock.patch.object(kho, "_tai_lieu_theo_khoa", lambda ks: {}), \
                mock.patch.object(kho, "_loi_theo_khoa", lambda ks: {}):
            chu = tich_hop.chu_khach("1000", tao_thu_muc=False)
            r = tich_hop.liet_ke_tep(chu, "crm")
        self.assertEqual(r["tong"], 2)
        dd = {x["duong_dan"]: x for x in r["items"]}
        self.assertEqual(set(dd), {"hd.docx", "cu/giay phep.pdf"})
        self.assertEqual(dd["cu/giay phep.pdf"]["thu_muc_con"], "cu")
        self.assertEqual(dd["cu/giay phep.pdf"]["trang_thai"], "chua_hoc")
        p = tich_hop.duong_dan_trong(chu["thu_muc"], "cu/giay phep.pdf")
        self.assertEqual(p.read_bytes(), b"%PDF cu")
        for xau in ("../1001. Chị B/x.pdf", "/etc/passwd", "C:/x", "cu/../../x", ".an/x", ""):
            with self.subTest(xau=xau):
                with self.assertRaises(tich_hop.LoiTichHop):
                    tich_hop.duong_dan_trong(chu["thu_muc"], xau)
        with self.assertRaises(tich_hop.LoiTichHop) as c:
            tich_hop.duong_dan_trong(chu["thu_muc"], "cu")      # thư mục, không phải tệp
        self.assertEqual(c.exception.status, 404)

    def test_khach_chua_co_thu_muc_thi_danh_sach_rong(self):
        chu = tich_hop.chu_khach("1001", tao_thu_muc=False)
        self.assertIsNone(chu["thu_muc"])
        self.assertEqual(tich_hop.liet_ke_tep(chu, "crm")["items"], [])

    def test_gan_ma_cho_tep_cu(self):
        cu = self.root / GOC / "1000. Anh A" / "cu" / "giay.pdf"
        cu.parent.mkdir(parents=True)
        cu.write_bytes(b"%PDF")
        chu = tich_hop.chu_khach("1000", tao_thu_muc=False)
        r = tich_hop.gan_ma(self.khoa, chu, "cu/giay.pdf", "HD-OLD")
        self.assertEqual(r["ket_qua"], "da_gan_ma")
        ax = self.anh_xa[("crm", "HD-OLD")]
        self.assertEqual(ax["khoa_kho"], f"local:{GOC}/1000. Anh A/cu/giay.pdf")
        self.assertEqual(self.hang_doi, [("crm", "HD-OLD")])     # chưa học → xếp hàng học
        self.assertEqual(tich_hop.gan_ma(self.khoa, chu, "cu/giay.pdf", "HD-OLD")["ket_qua"],
                         "da_gan_truoc_do")
        with self.assertRaises(tich_hop.LoiTichHop) as c:
            (self.root / GOC / "1000. Anh A" / "khac.pdf").write_bytes(b"k")
            tich_hop.gan_ma(self.khoa, chu, "khac.pdf", "HD-OLD")
        self.assertEqual(c.exception.status, 409)
        with mock.patch.object(tich_hop, "_ma_ngoai_theo_khoa",
                               lambda n, ks: {ks[0]: "HD-OLD"}):
            with self.assertRaises(tich_hop.LoiTichHop) as c2:
                tich_hop.gan_ma(self.khoa, chu, "cu/giay.pdf", "HD-MOI")
        self.assertEqual(c2.exception.status, 409)
        # Sau khi gắn mã, gửi bản mới cùng mã là thay đúng tệp cũ và lưu bản trước
        r2 = tich_hop.nhan_tai_lieu(self.khoa, "1000", "HD-OLD", "giay.pdf", b"%PDF v2",
                                    thu_muc_con="cu")
        self.assertEqual(r2["ket_qua"], "phien_ban_moi")
        self.assertEqual(cu.read_bytes(), b"%PDF v2")
        self.assertEqual(self._ban_luu(0)[2:], (b"%PDF", "thay_ban"))

    def test_ho_so_nhan_vien_vao_ngan_nhan_su(self):
        ns = self.root / "8. HỒ SƠ NHÂN SỰ" / "Ngân"
        ns.mkdir(parents=True)
        chu_nv = {"loai": "nhan_vien", "ma": "NV0001", "ten": "Nguyễn Thị Ngân",
                  "client_id": None, "employee_id": 21, "thu_muc": ns}
        with mock.patch.object(tich_hop, "chu_nhan_vien", lambda ma, tao_thu_muc=True: chu_nv):
            r = tich_hop.nhan_tai_lieu_nhan_vien(self.khoa, "NV0001", "NS-1", "CCCD.pdf", b"%PDF")
        self.assertEqual(r["duong_dan"], "8. HỒ SƠ NHÂN SỰ/Ngân/CCCD.pdf")
        self.assertEqual((r["loai"], r["ma_nhan_vien"], r["ma_khach"]), ("nhan_vien", "NV0001", None))
        ax = self.anh_xa[("crm", "NS-1")]
        self.assertEqual((ax["loai"], ax["employee_id"], ax["client_id"]), ("nhan_vien", 21, None))
        # Cùng mã ngoài mà gửi sang hồ sơ khách → 409
        with self.assertRaises(tich_hop.LoiTichHop) as c:
            tich_hop.nhan_tai_lieu(self.khoa, "1000", "NS-1", "x.pdf", b"x")
        self.assertEqual(c.exception.status, 409)


class NhanVien(unittest.TestCase):
    """Phần thuần của hồ sơ nhân viên + quyền theo loại hồ sơ."""

    def test_ma_nv_ke_tiep(self):
        self.assertEqual(tich_hop.ma_nv_ke_tiep_tu([]), "NV0001")
        self.assertEqual(tich_hop.ma_nv_ke_tiep_tu(["NV0003", "nv12", "ABC", None, "NV-9"]), "NV0013")

    def test_chuan_hoa_ma_nv_va_trang_thai(self):
        self.assertEqual(tich_hop.chuan_hoa_ma_nv("nv-01"), "NV-01")
        with self.assertRaises(tich_hop.LoiTichHop):
            tich_hop.chuan_hoa_ma_nv("nv 01")
        self.assertEqual(tich_hop.chuan_hoa_trang_thai_nv("active"), "active")
        with self.assertRaises(tich_hop.LoiTichHop):
            tich_hop.chuan_hoa_trang_thai_nv("dang_ngu")

    def test_ten_thu_muc_nhan_vien(self):
        self.assertEqual(tich_hop.ten_thu_muc_nhan_vien('Nguyễn Thị "Ngân"/HR'), "Nguyễn Thị Ngân HR")
        with self.assertRaises(tich_hop.LoiTichHop):
            tich_hop.ten_thu_muc_nhan_vien("   ")

    def test_chon_thu_muc(self):
        cur = mock.MagicMock()
        cur.fetchall.return_value = [("Ngân", 5)]
        goc = Path(".")
        self.assertEqual(tich_hop._chon_thu_muc_nv(cur, goc, "Mai", "NV0002", None, None), "Mai")
        self.assertEqual(tich_hop._chon_thu_muc_nv(cur, goc, "Ngân", "NV0002", None, None),
                         "Ngân (NV0002)")
        self.assertEqual(tich_hop._chon_thu_muc_nv(cur, goc, "Nguyễn Thị Ngân", "NV0001", "Ngân", 5),
                         "Ngân")
        with self.assertRaises(tich_hop.LoiTichHop) as c:
            tich_hop._chon_thu_muc_nv(cur, goc, "Người khác", "NV0009", "Ngân", 9)
        self.assertEqual(c.exception.status, 409)

    def test_goc_nhan_su(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t).resolve()
            (root / "8. HỒ SƠ NHÂN SỰ" / "Mai").mkdir(parents=True)
            (root / GOC).mkdir()
            ban_do = ({"ho so nhan su": {"doc_type": "ho_so_ns"}}, {}, {"ho so khach hang"})
            with mock.patch.object(kho, "library_root", lambda: root), \
                    mock.patch.object(kho, "_ban_do_nhan", lambda: ban_do):
                self.assertEqual(tich_hop.goc_nhan_su().name, "8. HỒ SƠ NHÂN SỰ")
            with mock.patch.object(kho, "library_root", lambda: root), \
                    mock.patch.object(kho, "_ban_do_nhan", lambda: BAN_DO):
                self.assertIsNone(tich_hop.goc_nhan_su())

    def test_quyen_theo_loai_ho_so(self):
        chi_tai_lieu = {"quyen": ["documents:read"]}
        with self.assertRaises(tich_hop.LoiTichHop) as c:
            tich_hop.kiem_quyen_loai(chi_tai_lieu, "nhan_vien")
        self.assertEqual(c.exception.status, 403)
        self.assertIn("employees:read", str(c.exception))
        with self.assertRaises(tich_hop.LoiTichHop):
            tich_hop.kiem_quyen_loai(chi_tai_lieu, "khach")
        tich_hop.kiem_quyen_loai({"quyen": ["documents:read", "employees:read"]}, "nhan_vien")
        tich_hop.kiem_quyen_loai(None, "nhan_vien")        # gọi nội bộ, không khoá

    def test_bo_quyen_crm_co_nhan_vien(self):
        crm = tich_hop.BO_QUYEN_MAU["crm"]["quyen"]
        for q in ("employees:read", "employees:write", "documents:read", "documents:write", "documents:delete"):
            self.assertIn(q, crm)
        self.assertNotIn("chat", crm)


class HangDoi(unittest.TestCase):
    def test_khoi_phuc_khong_sap_khi_khong_co_csdl(self):
        def _no(*a, **k):
            raise RuntimeError("không có CSDL")
        tich_hop._DA_KHOI_PHUC = False
        with mock.patch.object(tich_hop.db, "session", _no):
            self.assertEqual(tich_hop.khoi_phuc_hang_doi_mot_lan(), 0)
        self.assertEqual(tich_hop.khoi_phuc_hang_doi_mot_lan(), 0)  # chỉ chạy một lần

    def test_giu_khoa_quet_khong_can_fcntl(self):
        with tich_hop._giu_khoa_quet():
            pass


class DuongHttp(unittest.TestCase):
    """Router: hai không gian khoá tách nhau, thiếu quyền là 403 rõ tên."""

    @classmethod
    def setUpClass(cls):
        try:
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
        except (ImportError, RuntimeError):  # pragma: no cover — máy dev thiếu httpx
            raise unittest.SkipTest("Thiếu fastapi/httpx")
        from app import tich_hop_api

        def current_user():
            return {"id": 1, "role": "admin"}

        def require(user, roles):
            if user["role"] not in roles:
                from fastapi import HTTPException
                raise HTTPException(403, "Không đủ quyền")

        app = FastAPI()
        app.include_router(tich_hop_api.build_router(
            current_user, require, lambda uid: {"id": uid, "role": "client_plus"},
            lambda body, user: {"answer": f"{user['id']}:{body.question}"}))
        cls.client = TestClient(app)

    def setUp(self):
        self.khoa = {"id": 3, "ten": "CRM", "nguon": "crm", "quyen": ["clients:read", "documents:read"],
                     "user_id": None}
        self.patches = [
            mock.patch.object(tich_hop, "xac_thuc_khoa",
                              lambda raw: self.khoa if raw == "hdsi_ok" else None),
            mock.patch.object(tich_hop, "khoi_phuc_hang_doi_mot_lan", lambda: 0),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_thieu_khoa_va_khoa_sai_loai(self):
        self.assertEqual(self.client.get("/integration/v1/me").status_code, 401)
        r = self.client.get("/integration/v1/me", headers={"X-API-Key": "hds_khach"})
        self.assertEqual(r.status_code, 401)
        self.assertIn("hdsi_", r.json()["detail"])
        self.assertEqual(self.client.get("/integration/v1/me",
                                         headers={"X-API-Key": "hdsi_thu_hoi"}).status_code, 401)
        # Đường tiếng Việt cũ không còn
        self.assertEqual(self.client.get("/tich-hop/v1/toi", headers={"X-API-Key": "hdsi_ok"}).status_code, 404)

    def test_khoa_qua_bearer_cung_duoc(self):
        r = self.client.get("/integration/v1/me", headers={"Authorization": "Bearer hdsi_ok"})
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual((d["name"], d["source"], d["permissions"], d["has_chat_account"]),
                         ("CRM", "crm", ["clients:read", "documents:read"], False))

    def test_khoa_dung_va_thieu_quyen(self):
        h = {"X-API-Key": "hdsi_ok"}
        r = self.client.get("/integration/v1/me", headers=h)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["source"], "crm")
        r = self.client.post("/integration/v1/clients", json={"name": "X"}, headers=h)
        self.assertEqual(r.status_code, 403)
        self.assertIn("clients:write", r.json()["detail"])
        r = self.client.delete("/integration/v1/documents/HD-1", headers=h)
        self.assertEqual(r.status_code, 403)
        self.assertIn("documents:delete", r.json()["detail"])
        r = self.client.post("/integration/v1/chat", json={"question": "?"}, headers=h)
        self.assertEqual(r.status_code, 403)

    def test_chat_can_tai_khoan_dai_dien(self):
        self.khoa["quyen"] = ["chat"]
        h = {"X-API-Key": "hdsi_ok"}
        r = self.client.post("/integration/v1/chat", json={"question": "hỏi"}, headers=h)
        self.assertEqual(r.status_code, 403)
        self.khoa["user_id"] = 42
        r = self.client.post("/integration/v1/chat", json={"question": "hỏi"}, headers=h)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["answer"], "42:hỏi")

    def test_loi_nghiep_vu_thanh_ma_http(self):
        self.khoa["quyen"] = ["documents:read"]

        def _404(*_a):
            raise tich_hop.LoiTichHop("không có", 404)
        with mock.patch.object(tich_hop, "trang_thai", _404):
            r = self.client.get("/integration/v1/documents/HD-1", headers={"X-API-Key": "hdsi_ok"})
        self.assertEqual(r.status_code, 404)

    def test_trang_thai_tra_ten_truong_tieng_anh(self):
        self.khoa["quyen"] = ["documents:read"]
        tt = {"ma_ngoai": "HD-1", "loai": "khach", "ma_khach": "1729", "ma_nhan_vien": None,
              "trang_thai": "cho_duyet", "mo_ta": "Chờ duyệt", "ten_file": "a.pdf",
              "duong_dan": "9. HỒ SƠ KHÁCH HÀNG/1729. X/Hợp đồng/a.pdf", "checksum": "m",
              "document_id": 5, "tieu_de": "a", "ty_le_rac": 0.31, "chat_luong_doc": "warning",
              "loi": None, "nhan_luc": "t1", "cap_nhat_luc": "t2"}
        with mock.patch.object(tich_hop, "trang_thai", lambda *a: tt):
            r = self.client.get("/integration/v1/documents/HD-1", headers={"X-API-Key": "hdsi_ok"})
        d = r.json()
        self.assertEqual((d["external_id"], d["owner_type"], d["client_code"], d["status"]),
                         ("HD-1", "client", "1729", "pending_review"))
        self.assertEqual(d["path"], "Hợp đồng/a.pdf")
        self.assertEqual((d["md5"], d["unreadable_ratio"], d["extraction_quality"]), ("m", 0.31, "warning"))
        self.assertNotIn("ma_ngoai", d)

    def test_gui_bo_ho_so_moi_tep_mot_ket_qua(self):
        self.khoa["quyen"] = ["clients:read", "documents:write"]
        goi = []

        def _nhan(khoa, ma, mn, ten, noi_dung, thu_muc_con="", meta=None, gioi_han_mb=50):
            goi.append((ma, mn, ten, noi_dung, thu_muc_con, meta))
            if ten.endswith(".exe"):
                raise tich_hop.LoiTichHop("Định dạng .exe chưa hỗ trợ", 415)
            return {"ok": True, "ket_qua": "da_nhan", "ma_ngoai": mn, "trang_thai": "da_nhan"}

        with mock.patch.object(tich_hop, "nhan_tai_lieu", _nhan):
            r = self.client.post(
                "/integration/v1/clients/1000/documents",
                headers={"X-API-Key": "hdsi_ok"},
                data={"external_id": ["HD-1", "HD-2"], "folder": "Hợp đồng",
                      "metadata": '{"so_hop_dong": "01/2026"}'},
                files=[("files", ("a.docx", b"aaa")), ("files", ("b.exe", b"bbb"))])
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual((body["ok"], body["code"], body["sent"], body["accepted"]), (False, "1000", 2, 1))
        self.assertEqual(body["results"][0]["result"], "created")
        self.assertEqual(body["results"][0]["status"], "received")
        self.assertEqual(body["results"][1], {"ok": False, "external_id": "HD-2", "file_name": "b.exe",
                                              "error": "Định dạng .exe chưa hỗ trợ", "status_code": 415})
        self.assertEqual(goi[0][:3], ("1000", "HD-1", "a.docx"))
        self.assertEqual(goi[0][4], "Hợp đồng")
        self.assertEqual(goi[0][5], {"so_hop_dong": "01/2026"})
        # Sai số external_id → 400, chưa gọi nhận
        with mock.patch.object(tich_hop, "nhan_tai_lieu", _nhan):
            r = self.client.post("/integration/v1/clients/1000/documents",
                                 headers={"X-API-Key": "hdsi_ok"},
                                 data={"external_id": ["chi-mot"]},
                                 files=[("files", ("a.docx", b"a")), ("files", ("b.docx", b"b"))])
        self.assertEqual(r.status_code, 400)
        # Không gửi external_id → máy chủ tự đặt theo mã khách + tên tệp
        with mock.patch.object(tich_hop, "nhan_tai_lieu", _nhan):
            r = self.client.post("/integration/v1/clients/1000/documents",
                                 headers={"X-API-Key": "hdsi_ok"},
                                 files=[("files", ("c.docx", b"c"))])
        self.assertEqual(r.status_code, 200)
        self.assertEqual(goi[-1][1], "1000__c.docx")

    def test_tao_khach_nhan_truong_tieng_anh(self):
        self.khoa["quyen"] = ["clients:write"]
        goi = {}

        def _tao(ten, **k):
            goi.update(k, ten=ten)
            return {"id": 9, "ten": ten, "ma": "1770", "ma_ngoai": k["ma_ngoai"], "da_co": False,
                    "so_tai_lieu": 0, "thu_muc": "9. HỒ SƠ KHÁCH HÀNG/1770. Mặt Trời"}
        with mock.patch.object(tich_hop, "tao_khach", _tao):
            r = self.client.post("/integration/v1/clients", headers={"X-API-Key": "hdsi_ok"},
                                 json={"name": "Mặt Trời", "external_id": "CRM-1"})
        self.assertEqual((goi["ten"], goi["ma"], goi["ma_ngoai"]), ("Mặt Trời", None, "CRM-1"))
        self.assertEqual(r.json(), {"id": 9, "code": "1770", "name": "Mặt Trời", "external_id": "CRM-1",
                                    "document_count": 0, "folder": "9. HỒ SƠ KHÁCH HÀNG/1770. Mặt Trời",
                                    "existed": False})

    def test_quan_tri_khoa_can_admin(self):
        with mock.patch.object(tich_hop, "danh_sach_khoa", lambda: [{"id": 1}]):
            self.assertEqual(self.client.get("/khoa-tich-hop").json(), [{"id": 1}])
        r = self.client.get("/khoa-tich-hop/quyen")
        self.assertEqual(r.status_code, 200)
        self.assertEqual({q["ma"] for q in r.json()["quyen"]}, set(tich_hop.QUYEN))
        with mock.patch.object(tich_hop, "tao_khoa", lambda *a, **k: {"id": 9, "khoa": "hdsi_x"}):
            r = self.client.post("/khoa-tich-hop", json={"ten": "CRM", "nguon": "crm",
                                                         "quyen": ["clients:read"]})
        self.assertEqual(r.json()["khoa"], "hdsi_x")

    def test_tai_ve_tra_nguyen_byte_va_md5(self):
        self.khoa["quyen"] = ["clients:read", "documents:read"]
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "x.pdf"
            p.write_bytes(b"%PDF-noi-dung")
            with mock.patch.object(tich_hop, "tep_hien_tai",
                                   lambda n, m, k: (p, "Hợp đồng số 1.pdf", "abc123")):
                r = self.client.get("/integration/v1/documents/HD-1/download",
                                    headers={"X-API-Key": "hdsi_ok"})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.content, b"%PDF-noi-dung")
            self.assertEqual(r.headers["x-checksum-md5"], "abc123")
            self.assertIn("filename*=utf-8''", r.headers["content-disposition"])

    def test_tai_ve_theo_duong_dan_bi_nhot_trong_ho_so(self):
        self.khoa["quyen"] = ["clients:read", "documents:read"]
        with tempfile.TemporaryDirectory() as t:
            ho_so = Path(t) / "1000. Anh A"
            (ho_so / "cu").mkdir(parents=True)
            (ho_so / "cu" / "a.pdf").write_bytes(b"A")
            (Path(t) / "bi_mat.pdf").write_bytes(b"S")
            chu = {"loai": "khach", "ma": "1000", "ten": "Anh A", "client_id": 7,
                   "employee_id": None, "thu_muc": ho_so}
            h = {"X-API-Key": "hdsi_ok"}
            with mock.patch.object(tich_hop, "chu_khach", lambda ma, tao_thu_muc=True: chu):
                ok = self.client.get("/integration/v1/clients/1000/files/download",
                                     params={"path": "cu/a.pdf"}, headers=h)
                xau = self.client.get("/integration/v1/clients/1000/files/download",
                                      params={"path": "../bi_mat.pdf"}, headers=h)
        self.assertEqual((ok.status_code, ok.content), (200, b"A"))
        self.assertEqual(xau.status_code, 400)

    def test_duong_nhan_vien_can_quyen_nhan_vien(self):
        h = {"X-API-Key": "hdsi_ok"}
        r = self.client.get("/integration/v1/employees", headers=h)
        self.assertEqual(r.status_code, 403)
        self.assertIn("employees:read", r.json()["detail"])
        self.khoa["quyen"] = ["employees:read", "documents:read"]
        with mock.patch.object(tich_hop, "tim_nhan_vien",
                               lambda **k: {"items": [], "tong": 0, "offset": 0, "limit": 100,
                                            "thu_muc_chua_gan": [{"ten": "Ngân", "thu_muc": "8. X/Ngân",
                                                                  "so_tep": 3}]}):
            r = self.client.get("/integration/v1/employees", headers=h)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["unassigned_folders"],
                         [{"name": "Ngân", "folder": "8. X/Ngân", "file_count": 3}])
        r = self.client.post("/integration/v1/employees", json={"full_name": "A"}, headers=h)
        self.assertEqual(r.status_code, 403)
        self.assertIn("employees:write", r.json()["detail"])

    def test_doi_soat_chi_tra_loai_ho_so_duoc_xem(self):
        goi = {}

        def _ds(nguon, **k):
            goi.update(k)
            return {"items": [], "tong": 0}
        with mock.patch.object(tich_hop, "danh_sach_tai_lieu", _ds):
            r = self.client.get("/integration/v1/documents", headers={"X-API-Key": "hdsi_ok"},
                                params={"updated_since": "2026-09-29T00:00:00+07:00"})
        self.assertEqual(goi["loai_duoc_xem"], ["khach"])
        self.assertEqual(goi["tu_luc"], "2026-09-29T00:00:00+07:00")
        self.assertEqual(r.json()["total"], 0)

    def test_sua_quyen_khoa(self):
        goi = {}

        def _sua(kid, **k):
            goi.update(k, id=kid)
            return {"ok": True, "id": kid, "quyen": k["quyen"]}
        with mock.patch.object(tich_hop, "sua_khoa", _sua):
            r = self.client.patch("/khoa-tich-hop/5", json={"quyen": ["clients:read", "employees:read"]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual((goi["id"], goi["quyen"], goi["doi_user"]), (5, ["clients:read", "employees:read"], False))


class DichTiengAnh(unittest.TestCase):
    """Phần dịch ở biên API (tich_hop_api.*_en) — thuần."""

    @classmethod
    def setUpClass(cls):
        try:
            from app import tich_hop_api
        except (ImportError, RuntimeError):  # pragma: no cover
            raise unittest.SkipTest("Thiếu fastapi")
        cls.api = tich_hop_api

    def test_moi_trang_thai_deu_co_ban_dich(self):
        self.assertEqual(set(self.api.STATUS_EN), set(tich_hop.TRANG_THAI))
        for tt in ("da_hoc", "canh_bao", "cho_duyet", "chua_hoc", "loi", "khong_ho_tro"):
            self.assertIn(tt, self.api.FILE_STATUS_EN)
        self.assertIn(kho.trang_thai_file(None, ".zip"), self.api.FILE_STATUS_EN)

    def test_duong_dan_trong_ho_so(self):
        f = self.api._duong_dan_trong_ho_so
        self.assertEqual(f("9. HỒ SƠ KHÁCH HÀNG/1729. X/Hợp đồng/a.pdf"), "Hợp đồng/a.pdf")
        self.assertEqual(f("8. HỒ SƠ NHÂN SỰ/Ngân/CCCD.pdf"), "CCCD.pdf")
        self.assertIsNone(f(None))

    def test_tep_va_phien_ban(self):
        tep = self.api.files_en({"loai": "nhan_vien", "ma": "NV0001", "ten": "Ngân", "thu_muc": "8. X/Ngân",
                                 "tong": 1, "items": [{"duong_dan": "a.pdf", "ten_file": "a.pdf",
                                                       "thu_muc_con": "", "kich_thuoc": 3,
                                                       "trang_thai": "khong_ho_tro", "ma_ngoai": None}]})
        self.assertEqual(tep["owner_type"], "employee")
        self.assertEqual(tep["items"][0], {"path": "a.pdf", "file_name": "a.pdf", "subfolder": "",
                                           "size": 3, "status": "unsupported", "external_id": None})
        pb = self.api.versions_en({"ma_ngoai": "HD-1", "items": [
            {"so": 1, "ten_file": "a.pdf", "checksum": "x", "kich_thuoc": 1, "ly_do": "thay_ban",
             "luu_luc": "t", "hien_tai": False}]})
        self.assertEqual((pb["items"][0]["version"], pb["items"][0]["reason"]), (1, "replaced"))

    def test_ket_qua_go_khong_lo_duong_dan_may_chu(self):
        d = self.api.document_en({"ok": True, "ket_qua": "da_go", "ma_ngoai": "HD-1", "trang_thai": "da_go",
                                  "da_chuyen_toi": "/home/pc/hds-ai-full/hds-ai/data/_da_go/x.pdf",
                                  "phien_ban_luu": 2})
        self.assertEqual((d["result"], d["status"], d["archived_version"]), ("removed", "removed", 2))
        self.assertNotIn("/home/pc", json.dumps(d))


if __name__ == "__main__":  # pragma: no cover
    with contextlib.redirect_stdout(io.StringIO()):
        unittest.main()
