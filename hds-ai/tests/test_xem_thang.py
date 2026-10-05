"""Xem thẳng trong trình duyệt + link xem tạm cho CRM (01/10/2026) — THUẦN.

Không chạm CSDL / LibreOffice: khoá, tệp đích, chuyển PDF đều vá. Phải đúng:
  · link giả, sửa một ký tự, hết hạn, khoá bị thu hồi → không mở được;
  · mở link KHÔNG cần khoá API, nhưng quyền của khoá tạo link vẫn được kiểm lại;
  · chỉ phát inline đúng PDF / ảnh / văn bản thuần; tệp lạ → 415;
  · phản hồi không cho proxy / trình duyệt dùng chung lưu bản sao.
"""
import os
import tempfile
import time
import unittest
import unittest.mock as mock
from pathlib import Path

from app import tich_hop, xem_truoc

BI_MAT = "k" * 20 + "-thu-nghiem-khong-dung-that-" + "z" * 20
KHOA = {"id": 7, "ten": "CRM", "nguon": "crm", "quyen": ["clients:read", "documents:read"], "user_id": None}


class XemTruoc(unittest.TestCase):
    def test_ban_xem_theo_loai(self):
        with tempfile.TemporaryDirectory() as d:
            for ten, media in (("a.pdf", "application/pdf"), ("b.JPG", "image/jpeg"),
                               ("c.txt", "text/plain; charset=utf-8"), ("d.md", "text/plain; charset=utf-8")):
                p = Path(d) / ten
                p.write_bytes(b"x")
                self.assertEqual(xem_truoc.ban_xem(p), (p, media, ten))
            for ten in ("e.zip", "f.tif", "g.html", "h"):
                p = Path(d) / ten
                p.write_bytes(b"<html>")
                with self.assertRaises(xem_truoc.LoiXemTruoc) as c:
                    xem_truoc.ban_xem(p)
                self.assertEqual(c.exception.status, 415)
            # Word → PDF qua bộ chuyển (vá)
            w = Path(d) / "hd.docx"
            w.write_bytes(b"PK")
            with mock.patch.object(xem_truoc, "pdf_tu_office", lambda path, key: Path(d) / "out.pdf"):
                self.assertEqual(xem_truoc.ban_xem(w), (Path(d) / "out.pdf", "application/pdf", "hd.pdf"))

    def test_html_khong_bao_gio_phat_inline(self):
        self.assertNotIn(".html", xem_truoc.HIEN_THANG)
        self.assertNotIn(".htm", xem_truoc.HIEN_THANG)
        self.assertTrue(all("html" not in v for v in xem_truoc.HIEN_THANG.values()))

    def test_khoa_cache_doi_khi_tep_doi(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.docx"
            p.write_bytes(b"1")
            k1 = xem_truoc.khoa_cache(p)
            self.assertTrue(k1.startswith("th-"))
            self.assertEqual(xem_truoc.khoa_cache(p), k1)
            p.write_bytes(b"22")
            self.assertNotEqual(xem_truoc.khoa_cache(p), k1)

    def test_don_cache_chi_xoa_ban_crm_cu(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"DATA_WORK": d}):
            thu_muc = xem_truoc.thu_muc_cache()
            cu, moi, web = thu_muc / "th-cu.pdf", thu_muc / "th-moi.pdf", thu_muc / "123.pdf"
            for f in (cu, moi, web):
                f.write_bytes(b"%PDF")
            xua = time.time() - 40 * 86400
            os.utime(cu, (xua, xua))
            os.utime(web, (xua, xua))
            self.assertEqual(xem_truoc.don_cache(), 1)
            self.assertFalse(cu.exists())
            self.assertTrue(moi.exists() and web.exists())

    def test_url_goc(self):
        try:
            from app.tich_hop_api import url_goc
        except (ImportError, RuntimeError):  # pragma: no cover
            self.skipTest("Thiếu fastapi")
        with mock.patch.dict(os.environ, {"PUBLIC_API_BASE": ""}):
            self.assertEqual(url_goc({"host": "app.diginix.io.vn"}), "https://app.diginix.io.vn/api")
            self.assertEqual(url_goc({"host": "127.0.0.1:8000"}, "http"), "http://127.0.0.1:8000")
            self.assertEqual(url_goc({"host": "testserver"}, "http"), "http://testserver")
        with mock.patch.dict(os.environ, {"PUBLIC_API_BASE": "https://app.hdslaw.vn/api/"}):
            self.assertEqual(url_goc({"host": "x"}), "https://app.hdslaw.vn/api")


class LinkTam(unittest.TestCase):
    def setUp(self):
        self.p = mock.patch.dict(os.environ, {"JWT_SECRET": BI_MAT})
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def test_tao_va_doc_link(self):
        l = tich_hop.tao_link(KHOA, {"x": "HD-1"}, "preview", 300, bay_gio=1_000_000)
        self.assertEqual((l["ttl"], l["het_han"], l["che_do"]), (300, 1_000_300, "preview"))
        pl = tich_hop.doc_link(l["token"], bay_gio=1_000_100)
        self.assertEqual((pl["k"], pl["n"], pl["m"], pl["x"]), (7, "crm", "preview", "HD-1"))

    def test_han_bi_kep_trong_khoang(self):
        self.assertEqual(tich_hop.tao_link(KHOA, {"x": "a"}, het_han_giay=5)["ttl"], 60)
        self.assertEqual(tich_hop.tao_link(KHOA, {"x": "a"}, het_han_giay=99999)["ttl"], 3600)
        self.assertEqual(tich_hop.tao_link(KHOA, {"x": "a"})["ttl"], 600)
        with self.assertRaises(tich_hop.LoiTichHop):
            tich_hop.tao_link(KHOA, {"x": "a"}, "edit")

    def test_het_han_sua_ky_tu_va_link_gia(self):
        l = tich_hop.tao_link(KHOA, {"x": "HD-1"}, het_han_giay=60, bay_gio=1_000_000)
        with self.assertRaises(tich_hop.LoiTichHop) as c:
            tich_hop.doc_link(l["token"], bay_gio=1_000_061)
        self.assertEqual(c.exception.status, 410)
        than, ky = l["token"].split(".")
        # Đổi tệp đích trong phần thân nhưng giữ chữ ký cũ
        gia = tich_hop._b64(tich_hop._unb64(than).replace(b"HD-1", b"HD-2")) + "." + ky
        for tk in (gia, l["token"][:-2] + "AA", "abc", "", "a.b.c"):
            with self.subTest(tk=tk[:20]):
                with self.assertRaises(tich_hop.LoiTichHop) as c:
                    tich_hop.doc_link(tk, bay_gio=1_000_001)
                self.assertEqual(c.exception.status, 401)

    def test_doi_bi_mat_may_chu_la_link_cu_chet(self):
        l = tich_hop.tao_link(KHOA, {"x": "HD-1"})
        with mock.patch.dict(os.environ, {"JWT_SECRET": BI_MAT[::-1]}):
            with self.assertRaises(tich_hop.LoiTichHop):
                tich_hop.doc_link(l["token"])

    def test_mo_link_kiem_lai_khoa(self):
        l = tich_hop.tao_link(KHOA, {"x": "HD-1"})
        with mock.patch.object(tich_hop, "khoa_theo_id", lambda k: None):
            with self.assertRaises(tich_hop.LoiTichHop) as c:
                tich_hop.mo_link(l["token"])
            self.assertEqual(c.exception.status, 401)
        with mock.patch.object(tich_hop, "khoa_theo_id", lambda k: dict(KHOA, nguon="khac")):
            with self.assertRaises(tich_hop.LoiTichHop):
                tich_hop.mo_link(l["token"])
        # Khoá bị bỏ quyền documents:read sau khi tạo link → link chết
        with mock.patch.object(tich_hop, "khoa_theo_id", lambda k: dict(KHOA, quyen=["clients:read"])):
            with self.assertRaises(tich_hop.LoiTichHop) as c:
                tich_hop.mo_link(l["token"])
            self.assertEqual(c.exception.status, 403)
        with mock.patch.object(tich_hop, "khoa_theo_id", lambda k: dict(KHOA)), \
                mock.patch.object(tich_hop, "tep_hien_tai", lambda n, x, k: (Path("a.pdf"), "a.pdf", "m")):
            khoa, pl, p, ten, md5 = tich_hop.mo_link(l["token"])
            self.assertEqual((khoa["id"], pl["x"], ten, md5), (7, "HD-1", "a.pdf", "m"))

    def test_link_theo_duong_dan_nhot_trong_ho_so(self):
        with tempfile.TemporaryDirectory() as d:
            ho_so = Path(d) / "1000. A"
            ho_so.mkdir()
            (ho_so / "x.pdf").write_bytes(b"%PDF")
            (Path(d) / "ngoai.pdf").write_bytes(b"%PDF")
            chu = {"loai": "khach", "ma": "1000", "ten": "A", "client_id": 1, "employee_id": None,
                   "thu_muc": ho_so}
            with mock.patch.object(tich_hop, "chu_khach", lambda c, tao_thu_muc=True: chu):
                p, ten, _ = tich_hop.tep_theo_dich(KHOA, {"o": "khach", "c": "1000", "p": "x.pdf"})
                self.assertEqual(ten, "x.pdf")
                with self.assertRaises(tich_hop.LoiTichHop):
                    tich_hop.tep_theo_dich(KHOA, {"o": "khach", "c": "1000", "p": "../ngoai.pdf"})
            # Hồ sơ nhân viên cần employees:read
            with self.assertRaises(tich_hop.LoiTichHop) as c:
                tich_hop.tep_theo_dich(KHOA, {"o": "nhan_vien", "c": "NV1", "p": "a.pdf"})
            self.assertEqual(c.exception.status, 403)


class DuongHttpXem(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
        except (ImportError, RuntimeError):  # pragma: no cover
            raise unittest.SkipTest("Thiếu fastapi/httpx")
        from app import tich_hop_api
        app = FastAPI()
        app.include_router(tich_hop_api.build_router(
            lambda: {"id": 1, "role": "admin"}, lambda u, r: None, lambda uid: {"id": uid},
            lambda body, user: {}))
        cls.client = TestClient(app)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pdf = Path(self.tmp.name) / "HĐ số 1.pdf"
        self.pdf.write_bytes(b"%PDF-1.4 noi dung")
        self.patches = [
            mock.patch.dict(os.environ, {"JWT_SECRET": BI_MAT, "PUBLIC_API_BASE": ""}),
            mock.patch.object(tich_hop, "xac_thuc_khoa", lambda raw: dict(KHOA) if raw == "hdsi_ok" else None),
            mock.patch.object(tich_hop, "khoi_phuc_hang_doi_mot_lan", lambda: 0),
            mock.patch.object(tich_hop, "khoa_theo_id", lambda k: dict(KHOA)),
            mock.patch.object(tich_hop, "tep_hien_tai", lambda n, x, k: (self.pdf, self.pdf.name, "md5x")),
            mock.patch.object(tich_hop, "ghi_nhat_ky_xem", lambda *a, **k: None),
        ]
        for p in self.patches:
            p.start()
        self.h = {"X-API-Key": "hdsi_ok"}

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_preview_inline_khong_luu(self):
        r = self.client.get("/integration/v1/documents/HD-1/preview", headers=self.h)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["content-type"], "application/pdf")
        self.assertTrue(r.headers["content-disposition"].startswith("inline"))
        self.assertIn("no-store", r.headers["cache-control"])
        self.assertEqual(r.headers["x-content-type-options"], "nosniff")
        self.assertEqual(r.content, b"%PDF-1.4 noi dung")

    def test_xin_link_roi_mo_khong_can_khoa(self):
        r = self.client.post("/integration/v1/documents/HD-1/view-link", headers=self.h,
                             json={"expires_in": 120})
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual((d["mode"], d["expires_in"]), ("preview", 120))
        self.assertTrue(d["url"].startswith("http://testserver/integration/v1/view/"))
        duong = d["url"].replace("http://testserver", "")
        r2 = self.client.get(duong)                      # KHÔNG gửi khoá
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(r2.headers["content-disposition"].startswith("inline"))
        self.assertEqual(r2.content, b"%PDF-1.4 noi dung")
        # Link tải về: attachment + md5
        r3 = self.client.post("/integration/v1/documents/HD-1/view-link", headers=self.h,
                              json={"mode": "download"})
        r4 = self.client.get(r3.json()["url"].replace("http://testserver", ""))
        self.assertTrue(r4.headers["content-disposition"].startswith("attachment"))
        self.assertEqual(r4.headers["x-checksum-md5"], "md5x")
        # Không gửi thân yêu cầu → mặc định preview 600 s
        r5 = self.client.post("/integration/v1/documents/HD-1/view-link", headers=self.h)
        self.assertEqual((r5.status_code, r5.json()["expires_in"]), (200, 600))

    def test_link_hong_het_han_thu_hoi(self):
        self.assertEqual(self.client.get("/integration/v1/view/abc.def").status_code, 401)
        cu = tich_hop.tao_link(KHOA, {"x": "HD-1"}, het_han_giay=60, bay_gio=time.time() - 120)
        self.assertEqual(self.client.get(f"/integration/v1/view/{cu['token']}").status_code, 410)
        moi = tich_hop.tao_link(KHOA, {"x": "HD-1"})
        with mock.patch.object(tich_hop, "khoa_theo_id", lambda k: None):
            self.assertEqual(self.client.get(f"/integration/v1/view/{moi['token']}").status_code, 401)

    def test_xin_link_xem_cho_dinh_dang_khong_xem_duoc(self):
        z = Path(self.tmp.name) / "a.zip"
        z.write_bytes(b"PK")
        with mock.patch.object(tich_hop, "tep_hien_tai", lambda n, x, k: (z, z.name, None)):
            r = self.client.post("/integration/v1/documents/Z-1/view-link", headers=self.h)
            self.assertEqual(r.status_code, 415)
            r = self.client.post("/integration/v1/documents/Z-1/view-link", headers=self.h,
                                 json={"mode": "download"})
            self.assertEqual(r.status_code, 200)

    def test_gui_tep_kem_link_xem_ngay(self):
        def _nhan(khoa, ma, mn, ten, noi_dung, thu_muc_con="", meta=None, gioi_han_mb=50):
            return {"ok": True, "ket_qua": "da_nhan", "ma_ngoai": mn, "trang_thai": "da_nhan",
                    "ten_file": ten}
        with mock.patch.object(tich_hop, "nhan_tai_lieu", _nhan), \
                mock.patch.object(tich_hop, "xac_thuc_khoa",
                                  lambda raw: dict(KHOA, quyen=KHOA["quyen"] + ["documents:write"])):
            r = self.client.post("/integration/v1/clients/1000/documents", headers=self.h,
                                 data={"external_id": ["HD-1", "ZIP-1"]},
                                 files=[("files", ("hd.docx", b"PK")), ("files", ("a.zip", b"PK"))])
        kq = r.json()["results"]
        self.assertTrue(kq[0]["preview_url"].startswith("http://testserver/integration/v1/view/"))
        self.assertIn("preview_expires_at", kq[0])
        self.assertNotIn("preview_url", kq[1])            # zip không xem thẳng được

    def test_danh_sach_tep_kem_link(self):
        chu = {"loai": "khach", "ma": "1000", "ten": "A", "client_id": 1, "employee_id": None,
               "thu_muc": Path(self.tmp.name)}
        ds = {"loai": "khach", "ma": "1000", "ten": "A", "thu_muc": "9/1000", "tong": 2, "items": [
            {"duong_dan": "HĐ số 1.pdf", "ten_file": "HĐ số 1.pdf", "trang_thai": "da_hoc"},
            {"duong_dan": "a.zip", "ten_file": "a.zip", "trang_thai": "khong_ho_tro"}]}
        with mock.patch.object(tich_hop, "chu_khach", lambda c, tao_thu_muc=True: chu), \
                mock.patch.object(tich_hop, "liet_ke_tep", lambda c, n: ds):
            r = self.client.get("/integration/v1/clients/1000/files", headers=self.h,
                                params={"with_links": "true"})
            items = r.json()["items"]
            self.assertIn("preview_url", items[0])
            self.assertIn("download_url", items[0])
            self.assertNotIn("preview_url", items[1])
            self.assertIn("download_url", items[1])
            # Mở link xem của tệp theo đường dẫn → đúng tệp
            r2 = self.client.get(items[0]["preview_url"].replace("http://testserver", ""))
            self.assertEqual((r2.status_code, r2.content), (200, b"%PDF-1.4 noi dung"))
            r3 = self.client.get("/integration/v1/clients/1000/files", headers=self.h)
            self.assertNotIn("preview_url", r3.json()["items"][0])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
