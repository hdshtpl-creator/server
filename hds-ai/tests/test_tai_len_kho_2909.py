"""Tải tệp lên kho từ web (/kho/tai-len, /kho/hoc) — sửa 29/09/2026.

Bốn lỗi đã gặp, mỗi lỗi một nhóm test:
  · thư mục khách chưa tách được mã: tệp được ghi rồi mới "lỗi học", nằm kẹt
    không gỡ được, tải lại bị "đã có file tên…" → nay từ chối TRƯỚC khi ghi;
  · tệp ghi thẳng vào tên thật: lượt quét cron giữa chừng đọc tệp dở → nay ghi
    tên tạm ẩn rồi đổi tên một bước;
  · học ngay trong hàm async: treo cả máy chủ, lượt dài bị Cloudflare cắt ra
    trang lỗi HTML → nay học ở luồng nền, API chờ tới mốc rồi báo "đang học";
  · một tệp lỗi lạ làm 500 cả lượt, mất kết quả các tệp khác.
Không chạm CSDL: hoc_file, bản đồ nhãn và gốc kho đều được vá.
"""
import tempfile
import threading
import time
import unittest
import unittest.mock
from pathlib import Path

from app import kho

GOC = "9. HỒ SƠ KHÁCH HÀNG"
BAN_DO = ({"hop dong mau": {"doc_type": "contract"}}, {}, {"ho so khach hang"})


class ThuMucHocDuoc(unittest.TestCase):
    def test_ly_do_theo_tung_tang(self):
        ly_do = lambda *parts: kho.ly_do_thu_muc_khong_hoc(parts, BAN_DO)  # noqa: E731
        self.assertIn("gốc kho", ly_do())
        self.assertIn("thư mục của từng khách", ly_do(GOC))
        self.assertIn("mã khách", ly_do(GOC, "Công ty ABC"))
        self.assertIsNone(ly_do(GOC, "1729. Công ty ABC"))
        self.assertIsNone(ly_do(GOC, "[ZEGNA] Zegna", "Hợp đồng", "2026"))
        self.assertIsNone(ly_do("3. HỢP ĐỒNG MẪU"))
        self.assertIsNone(ly_do("3. HỢP ĐỒNG MẪU", "Lao động"))
        self.assertIn("bản đồ nhãn", ly_do("Linh tinh"))


class KhoTam(unittest.TestCase):
    """Có thư mục kho thật trên đĩa tạm + bản đồ nhãn giả."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        for rel in (f"{GOC}/1729. Công ty ABC", f"{GOC}/Công ty chưa mã", "3. HỢP ĐỒNG MẪU"):
            (self.root / rel).mkdir(parents=True)
        self.patches = [
            unittest.mock.patch.object(kho, "library_root", lambda: self.root),
            unittest.mock.patch.object(kho, "_ban_do_nhan", lambda: BAN_DO),
            unittest.mock.patch.object(kho, "kho_khach_chi_doc", lambda: False),
            unittest.mock.patch.object(kho, "_goi_y_ma_khach", lambda: ""),
            unittest.mock.patch.object(kho.db, "audit", lambda *a, **k: None),
            unittest.mock.patch.object(kho.db, "session", unittest.mock.MagicMock()),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()


class GhiTepMotBuoc(KhoTam):
    def test_ten_tam_an_voi_bo_quet_va_cay(self):
        dest = self.root / "3. HỢP ĐỒNG MẪU" / "mau.docx"
        tam = kho.tep_tam_cho(dest)
        self.assertEqual(tam.parent, dest.parent)
        self.assertTrue(kho._bo_qua(tam))
        tam.write_bytes(b"x")
        self.assertEqual([f["ten"] for f in kho.liet_ke("3. HỢP ĐỒNG MẪU")["tap_tin"]], [])

    def test_doi_ten_khong_de_tep_co_san(self):
        dest = self.root / "3. HỢP ĐỒNG MẪU" / "mau.docx"
        tam = kho.tep_tam_cho(dest)
        tam.write_bytes(b"moi")
        kho.dat_vao_cho(tam, dest)
        self.assertEqual(dest.read_bytes(), b"moi")
        self.assertFalse(tam.exists())
        tam2 = kho.tep_tam_cho(dest)
        tam2.write_bytes(b"de")
        with self.assertRaises(kho.LoiKho):
            kho.dat_vao_cho(tam2, dest)
        self.assertEqual(dest.read_bytes(), b"moi")
        self.assertFalse(tam2.exists(), "tệp tạm phải được dọn khi không đặt được")


class TaoThuMucKhach(KhoTam):
    def test_tang_khach_phai_co_ma(self):
        with self.assertRaises(kho.LoiKho) as ctx:
            kho.tao_thu_muc(GOC, "Công ty XYZ")
        self.assertIn("mã khách", str(ctx.exception))
        self.assertFalse((self.root / GOC / "Công ty XYZ").exists())
        self.assertEqual(kho.tao_thu_muc(GOC, "1730. Công ty XYZ")["ten"], "1730. Công ty XYZ")

    def test_ngan_con_va_ngan_chung_dat_ten_tu_do(self):
        kho.tao_thu_muc(f"{GOC}/1729. Công ty ABC", "Hợp đồng 2026")
        kho.tao_thu_muc("3. HỢP ĐỒNG MẪU", "Lao động")


class DuongHttp(KhoTam):
    @classmethod
    def setUpClass(cls):
        try:
            from fastapi.testclient import TestClient
        except (ImportError, RuntimeError):  # pragma: no cover — máy dev thiếu httpx
            raise unittest.SkipTest("Thiếu fastapi/httpx")
        from app import api
        cls.api = api
        api.app.dependency_overrides[api.current_user] = lambda: {
            "id": 1, "role": "admin", "can_review": True}
        cls.client = TestClient(api.app)

    @classmethod
    def tearDownClass(cls):
        cls.api.app.dependency_overrides.pop(cls.api.current_user, None)

    def setUp(self):
        super().setUp()
        self.da_hoc = []

    def _hoc_nhanh(self, rel, uid, auto_approve=False):
        path = kho.duong_dan_kho(rel, self.root)
        # Lúc học, tệp đã nằm ĐỦ ở tên thật — không có chuyện đọc tệp dở.
        self.da_hoc.append((rel, path.read_bytes()))
        return {"ok": True, "document_id": 7, "title": path.stem,
                "trang_thai": "cho_duyet", "warnings": [], "note": "Đã học, đang chờ duyệt."}

    def _gui(self, path, *ten_noi_dung):
        return self.client.post(
            "/kho/tai-len", data={"path": path, "auto_approve": "false"},
            files=[("files", (ten, nd, "application/octet-stream")) for ten, nd in ten_noi_dung])

    def _tep_tren_dia(self):
        return sorted(p.relative_to(self.root).as_posix()
                      for p in self.root.rglob("*") if p.is_file())

    def test_thu_muc_khach_chua_ma_tu_choi_truoc_khi_ghi(self):
        with unittest.mock.patch.object(kho, "hoc_file", self._hoc_nhanh):
            r = self._gui(f"{GOC}/Công ty chưa mã", ("a.pdf", b"%PDF-1"), ("b.docx", b"PK"))
        self.assertEqual(r.status_code, 400)
        self.assertIn("mã khách", r.json()["detail"])
        self.assertEqual(self._tep_tren_dia(), [])
        self.assertEqual(self.da_hoc, [])

    def test_dung_ngan_goc_khach_cung_tu_choi(self):
        r = self._gui(GOC, ("a.pdf", b"%PDF-1"))
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self._tep_tren_dia(), [])

    def test_hoc_xong_trong_han(self):
        with unittest.mock.patch.object(kho, "hoc_file", self._hoc_nhanh):
            r = self._gui(f"{GOC}/1729. Công ty ABC", ("hd.pdf", b"%PDF-noi-dung"))
        self.assertEqual(r.status_code, 200)
        kq = r.json()["ket_qua"]
        self.assertEqual(len(kq), 1)
        self.assertTrue(kq[0]["ok"])
        self.assertEqual(kq[0]["trang_thai"], "cho_duyet")
        self.assertEqual(self.da_hoc, [(f"{GOC}/1729. Công ty ABC/hd.pdf", b"%PDF-noi-dung")])
        self.assertEqual(self._tep_tren_dia(), [f"{GOC}/1729. Công ty ABC/hd.pdf"],
                         "không được sót tệp tạm")

    def test_qua_moc_bao_dang_hoc_va_van_hoc_tiep(self):
        tha = threading.Event()
        xong = threading.Event()

        def hoc_cham(rel, uid, auto_approve=False):
            tha.wait(10)
            xong.set()
            return {"ok": True, "trang_thai": "da_hoc", "warnings": [], "note": "Đã học."}

        with unittest.mock.patch.object(kho, "hoc_file", hoc_cham), \
                unittest.mock.patch.object(self.api, "KHO_HOC_CHO_GIAY", 0.3):
            t0 = time.monotonic()
            r = self._gui("3. HỢP ĐỒNG MẪU", ("scan.pdf", b"%PDF"))
            self.assertLess(time.monotonic() - t0, 5)
            self.assertEqual(r.status_code, 200)
            kq = r.json()["ket_qua"][0]
            self.assertTrue(kq["ok"])
            self.assertEqual(kq["trang_thai"], "dang_hoc")
            self.assertFalse(xong.is_set())
            tha.set()
            self.assertTrue(xong.wait(5), "lượt học phải chạy tiếp sau khi API đã trả lời")

    def test_mot_tep_hong_khong_nuot_ket_qua_ca_luot(self):
        def hoc(rel, uid, auto_approve=False):
            if rel.endswith("hong.pdf"):
                raise RuntimeError("bùm")
            if rel.endswith("rong.pdf"):
                raise kho.LoiKho("Không học được: Không tìm thấy nội dung chữ.")
            return self._hoc_nhanh(rel, uid)

        with unittest.mock.patch.object(kho, "hoc_file", hoc):
            r = self._gui("3. HỢP ĐỒNG MẪU", ("hong.pdf", b"1"), ("rong.pdf", b"2"),
                          ("tot.pdf", b"3"))
        self.assertEqual(r.status_code, 200)
        kq = {k["filename"]: k for k in r.json()["ket_qua"]}
        self.assertFalse(kq["hong.pdf"]["ok"])
        self.assertIn("RuntimeError", kq["hong.pdf"]["loi"])
        self.assertTrue(kq["hong.pdf"]["da_luu"])
        self.assertFalse(kq["rong.pdf"]["ok"])
        self.assertIn("nội dung chữ", kq["rong.pdf"]["loi"])
        self.assertTrue(kq["tot.pdf"]["ok"])
        self.assertFalse(r.json()["ok"])

    def test_trung_ten_va_duoi_la_bao_rieng_tung_tep(self):
        (self.root / "3. HỢP ĐỒNG MẪU" / "co_san.pdf").write_bytes(b"cu")
        with unittest.mock.patch.object(kho, "hoc_file", self._hoc_nhanh):
            r = self._gui("3. HỢP ĐỒNG MẪU", ("co_san.pdf", b"moi"), ("a.xyz", b"?"),
                          ("moi.pdf", b"ok"))
        kq = {k["filename"]: k for k in r.json()["ket_qua"]}
        self.assertIn("đã có file", kq["co_san.pdf"]["loi"])
        self.assertIn("chưa hỗ trợ", kq["a.xyz"]["loi"])
        self.assertTrue(kq["moi.pdf"]["ok"])
        self.assertEqual((self.root / "3. HỢP ĐỒNG MẪU" / "co_san.pdf").read_bytes(), b"cu")

    def test_hoc_ngay_kiem_truoc_roi_moi_xep_hang(self):
        with unittest.mock.patch.object(kho, "hoc_file", self._hoc_nhanh):
            r = self.client.post("/kho/hoc", json={"path": "3. HỢP ĐỒNG MẪU/khong-co.pdf"})
            self.assertEqual(r.status_code, 400)
            (self.root / f"{GOC}/Công ty chưa mã/x.pdf").write_bytes(b"x")
            r = self.client.post("/kho/hoc", json={"path": f"{GOC}/Công ty chưa mã/x.pdf"})
            self.assertEqual(r.status_code, 400)
            self.assertIn("mã khách", r.json()["detail"])
            self.assertEqual(self.da_hoc, [])
            (self.root / "3. HỢP ĐỒNG MẪU/y.pdf").write_bytes(b"y")
            r = self.client.post("/kho/hoc", json={"path": "3. HỢP ĐỒNG MẪU/y.pdf"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["trang_thai"], "cho_duyet")

    def test_hoc_ngay_bao_loi_kho_thanh_400(self):
        (self.root / "3. HỢP ĐỒNG MẪU/z.pdf").write_bytes(b"z")

        def hong(rel, uid, auto_approve=False):
            raise kho.LoiKho("Không học được: PDF hỏng.")

        with unittest.mock.patch.object(kho, "hoc_file", hong):
            r = self.client.post("/kho/hoc", json={"path": "3. HỢP ĐỒNG MẪU/z.pdf"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("PDF hỏng", r.json()["detail"])


if __name__ == "__main__":
    unittest.main()
