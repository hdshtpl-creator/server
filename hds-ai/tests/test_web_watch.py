"""Bộ quét nguồn web (app/web_watch.py) — lọc link, đặt tên file, kiểm định dạng.

Đây là cửa DUY NHẤT trong hệ thống nhận dữ liệu từ Internet, nên test tập
trung vào đúng chỗ có thể lọt: link ra ngoài miền cho phép, tên file trỏ ra
ngoài thư mục kho, và trang lỗi HTML đội lốt file .pdf.

Toàn bộ test chỉ gọi các hàm THUẦN (không chạm mạng, đĩa hay CSDL) — trừ hai
test thư mục đích, dùng thư mục tạm.
"""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from app import web_watch


NGUON = {
    "ten": "thử",
    "url": "https://vanban.vi-du.gov.vn/moi",
    "mien_cho_phep": ["vi-du.gov.vn"],
    "thu_muc": "1. VĂN BẢN PHÁP LUẬT",
    "duoi_file": [".pdf", ".doc", ".docx"],
}


class BocLienKetTests(unittest.TestCase):
    def test_rss_lay_ca_link_va_enclosure(self):
        xml = """<?xml version="1.0"?><rss version="2.0"><channel>
          <item><link>https://vi-du.gov.vn/a.pdf</link></item>
          <item><enclosure url="/b.doc" type="application/msword"/></item>
        </channel></rss>"""
        ra = web_watch.lien_ket_tu_xml(xml, "https://vi-du.gov.vn/rss")
        self.assertIn("https://vi-du.gov.vn/a.pdf", ra)
        self.assertIn("https://vi-du.gov.vn/b.doc", ra)   # đường dẫn tương đối

    def test_atom_lay_thuoc_tinh_href(self):
        xml = """<?xml version="1.0"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry><link href="https://vi-du.gov.vn/nghi-dinh.pdf"/></entry>
        </feed>"""
        self.assertEqual(web_watch.lien_ket_tu_xml(xml, "https://vi-du.gov.vn/"),
                         ["https://vi-du.gov.vn/nghi-dinh.pdf"])

    def test_sitemap_lay_the_loc(self):
        xml = """<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>https://vi-du.gov.vn/thong-tu.docx</loc></url>
        </urlset>"""
        self.assertEqual(web_watch.lien_ket_tu_xml(xml, "https://vi-du.gov.vn/"),
                         ["https://vi-du.gov.vn/thong-tu.docx"])

    def test_xml_hong_thi_khong_no(self):
        """Trang nguồn đổi cấu trúc hoặc trả trang lỗi — bỏ qua nguồn đó, đừng
        làm chết cả lượt quét."""
        self.assertEqual(web_watch.lien_ket_tu_xml("<rss><item", "https://a.vn"), [])

    def test_html_lay_href_va_ghep_duong_dan_tuong_doi(self):
        html = ('<div><a class="x" href="/vb/luat.pdf">Luật</a>'
                "<a href='ho-so/thong-tu.doc'>TT</a><a>không có href</a></div>")
        ra = web_watch.lien_ket_tu_html(html, "https://vi-du.gov.vn/danh-sach/")
        self.assertEqual(ra, ["https://vi-du.gov.vn/vb/luat.pdf",
                              "https://vi-du.gov.vn/danh-sach/ho-so/thong-tu.doc"])


class MienChoPhepTests(unittest.TestCase):
    """CHỐT 1 — không có miền thì không tải gì."""

    def test_dung_mien_va_mien_con(self):
        self.assertTrue(web_watch.host_hop_le("https://vi-du.gov.vn/a.pdf", ["vi-du.gov.vn"]))
        self.assertTrue(web_watch.host_hop_le("https://vanban.vi-du.gov.vn/a.pdf",
                                              ["vi-du.gov.vn"]))

    def test_mien_gia_dinh_kem_duoi(self):
        """'vi-du.gov.vn.kesau.com' trùng chuỗi nhưng KHÔNG phải miền con."""
        self.assertFalse(
            web_watch.host_hop_le("https://vi-du.gov.vn.kesau.com/a.pdf", ["vi-du.gov.vn"]))

    def test_khong_co_danh_sach_thi_chan_het(self):
        self.assertFalse(web_watch.host_hop_le("https://vi-du.gov.vn/a.pdf", []))
        self.assertFalse(web_watch.host_hop_le("https://vi-du.gov.vn/a.pdf", None))

    def test_chan_giao_thuc_la(self):
        for url in ("file:///etc/passwd", "ftp://vi-du.gov.vn/a.pdf",
                    "javascript:alert(1)"):
            self.assertFalse(web_watch.host_hop_le(url, ["vi-du.gov.vn"]), url)

    def test_chan_may_noi_bo(self):
        """Bộ quét chỉ có việc ra Internet; trỏ vào mạng nhà là cấu hình sai."""
        for host in ("localhost", "127.0.0.1", "192.168.1.10", "10.0.0.5",
                     "nas.local", "172.16.0.9"):
            self.assertFalse(web_watch.host_hop_le(f"http://{host}/a.pdf", [host]), host)


class LocLienKetTests(unittest.TestCase):
    def test_giu_thu_tu_bo_trung_va_bo_link_ngoai_mien(self):
        ra = web_watch.loc_lien_ket([
            "https://vi-du.gov.vn/a.pdf",
            "https://vi-du.gov.vn/a.pdf",          # trùng
            "https://vi-du.gov.vn/a.pdf#trang2",   # trùng sau khi bỏ neo
            "https://khac.com/b.pdf",              # ngoài miền
            "https://vi-du.gov.vn/c.docx",
        ], NGUON)
        self.assertEqual(ra, ["https://vi-du.gov.vn/a.pdf",
                              "https://vi-du.gov.vn/c.docx"])

    def test_bo_duoi_file_khong_nam_trong_danh_sach(self):
        ra = web_watch.loc_lien_ket(["https://vi-du.gov.vn/trang.aspx",
                                     "https://vi-du.gov.vn/anh.png"], NGUON)
        self.assertEqual(ra, [])

    def test_duoi_kho_khong_hoc_thi_khong_mo_duoc_bang_cau_hinh(self):
        """Admin gõ '.html' vào duoi_file cũng không mở cửa: kho chỉ học các
        định dạng trong SUPPORTED_EXTENSIONS."""
        ng = dict(NGUON, duoi_file=[".html", ".exe", ".pdf"])
        ra = web_watch.loc_lien_ket(["https://vi-du.gov.vn/x.html",
                                     "https://vi-du.gov.vn/y.exe",
                                     "https://vi-du.gov.vn/z.pdf"], ng)
        self.assertEqual(ra, ["https://vi-du.gov.vn/z.pdf"])

    def test_mau_lien_ket_loc_them(self):
        ng = dict(NGUON, mau_lien_ket=r"/van-ban/")
        ra = web_watch.loc_lien_ket(["https://vi-du.gov.vn/van-ban/a.pdf",
                                     "https://vi-du.gov.vn/tin-tuc/b.pdf"], ng)
        self.assertEqual(ra, ["https://vi-du.gov.vn/van-ban/a.pdf"])

    def test_mau_lien_ket_sai_cu_phap_thi_bo_qua_bo_loc(self):
        ng = dict(NGUON, mau_lien_ket="[chua dong ngoac")
        # Hứng stdout: hàm có in cảnh báo, mà console Windows (cp1252) không
        # in nổi chữ Việt. Máy chủ chạy UTF-8 nên đây thuần là chuyện của máy
        # lập trình — test không được phụ thuộc bảng mã của terminal.
        with contextlib.redirect_stdout(io.StringIO()):
            ra = web_watch.loc_lien_ket(["https://vi-du.gov.vn/a.pdf"], ng)
        self.assertEqual(ra, ["https://vi-du.gov.vn/a.pdf"])


class TenFileTests(unittest.TestCase):
    """CHỐT 5 — phần path của URL là chuỗi do người khác viết."""

    def test_bo_moi_thu_tro_ra_ngoai_thu_muc(self):
        ten = web_watch.ten_file_an_toan(
            "https://vi-du.gov.vn/a/../../../etc/passwd.pdf")
        self.assertEqual(ten, "passwd.pdf")
        self.assertNotIn("/", ten)
        self.assertNotIn("\\", ten)
        self.assertFalse(ten.startswith("."))

    def test_giu_dau_tieng_viet_bo_ky_tu_la(self):
        ten = web_watch.ten_file_an_toan(
            "https://vi-du.gov.vn/Lu%E1%BA%ADt%20Doanh%20nghi%E1%BB%87p.pdf")
        self.assertEqual(ten, "Luật Doanh nghiệp.pdf")

    def test_bo_chuoi_truy_van_va_gioi_han_do_dai(self):
        ten = web_watch.ten_file_an_toan(
            "https://vi-du.gov.vn/" + "a" * 400 + ".pdf?token=abc&v=2")
        self.assertTrue(ten.endswith(".pdf"))
        self.assertLessEqual(len(ten), 130)

    def test_url_khong_co_ten_van_ra_ten_dung_duoc(self):
        ten = web_watch.ten_file_an_toan("https://vi-du.gov.vn/")
        self.assertEqual(ten, "tai-lieu.pdf")


class ThuMucDichTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()

    def test_thu_muc_con_hop_le(self):
        dich = web_watch.thu_muc_dich(self.root, "1. VĂN BẢN PHÁP LUẬT")
        self.assertEqual(dich.parent, self.root)

    def test_chan_thu_muc_ngoai_kho(self):
        for xau in ("../../etc", "a/../../../tmp", "..", "../"):
            with self.assertRaises(ValueError, msg=xau):
                web_watch.thu_muc_dich(self.root, xau)

    def test_duong_dan_tuyet_doi_bi_keo_ve_trong_kho(self):
        """'/etc' không ném lỗi mà thành thư mục con 'etc' trong kho — dấu
        gạch đầu bị tước trước khi ghép. Vẫn nằm trong kho là đủ an toàn;
        ghi ra đây để lần sau không ai tưởng đó là lỗ thủng."""
        dich = web_watch.thu_muc_dich(self.root, "/etc")
        self.assertEqual(dich, self.root / "etc")
        self.assertIn(self.root, dich.parents)


class DinhDangTests(unittest.TestCase):
    """CHỐT 2 — trang lỗi HTML mang tên .pdf là ca hỏng thường gặp nhất."""

    def test_pdf_that_thi_qua(self):
        self.assertTrue(web_watch.dung_dinh_dang(".pdf", b"%PDF-1.7\n%"))

    def test_trang_loi_html_doi_lot_pdf_bi_chan(self):
        self.assertFalse(web_watch.dung_dinh_dang(".pdf", b"<!DOCTYPE html>"))

    def test_docx_la_goi_zip(self):
        self.assertTrue(web_watch.dung_dinh_dang(".docx", b"PK\x03\x04\x14\x00"))
        self.assertFalse(web_watch.dung_dinh_dang(".docx", b"<html><body>"))

    def test_dinh_dang_khong_co_chu_ky_thi_cho_qua(self):
        self.assertTrue(web_watch.dung_dinh_dang(".txt", b"bat ky noi dung nao"))


class SoTheoDoiTests(unittest.TestCase):
    def test_cat_bot_ban_ghi_cu_khi_qua_day(self):
        """Cắt bớt là an toàn: file đã nằm trên đĩa và local_learn còn nhận ra
        nội dung trùng bằng md5 — mất sổ chỉ tốn thêm một lần tải."""
        ghi = {}
        goc = web_watch.settings.set_system
        web_watch.settings.set_system = lambda k, v: ghi.__setitem__(k, v)
        self.addCleanup(setattr, web_watch.settings, "set_system", goc)

        so = {f"https://vi-du.gov.vn/{i}.pdf": {"luc": f"2026-08-{i % 28 + 1:02d}",
                                                "key": f"local:{i}.pdf"}
              for i in range(web_watch.MAX_DA_TAI + 50)}
        web_watch._ghi_da_tai(so)
        import json
        self.assertEqual(len(json.loads(ghi[web_watch.SETTING_DA_TAI])),
                         web_watch.MAX_DA_TAI)


if __name__ == "__main__":
    unittest.main()
