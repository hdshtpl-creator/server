"""Tệp .doc là gói MHTML (Confluence "Export to Word", Word "Lưu dạng trang
web một tệp") + lệnh học lại tài liệu đã lỡ học thành mã nguồn (29/09/2026).

Hồ sơ khách 913 Bee Art: Word mở ra văn bản bình thường, máy chủ đọc ra
"Date: Mon, 23 Mar 2026 … MIME-Version: 1.0 … <html xmlns:o=3D…" và học luôn
thứ đó. Không chạm CSDL: hoc_file được vá ở lớp hàm truy vấn.
"""
import quopri
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from app import hoc_lai_ma_nguon, kho
from app.ingest import _loai_noi_dung_word, extract_text_with_metadata

HTML = (
    "<html xmlns:o='urn:schemas-microsoft-com:office:office'>\r\n<head>\r\n"
    "<meta http-equiv=\"Content-Type\" content=\"text/html; charset=utf-8\">\r\n"
    "<title>913 Bee Art</title>\r\n<style>body { font-family: Arial; } p { margin: 0 }</style>\r\n"
    "</head>\r\n<body>\r\n<h1>Tổng hợp thông tin khách hàng — Bee Art</h1>\r\n"
    "<table><tr><td>Mã khách</td><td>913</td></tr>\r\n"
    "<tr><td>Người đại diện</td><td>Nguyễn Văn\r\nAn</td></tr></table>\r\n"
    "<p>Vụ việc: tranh chấp hợp đồng thuê mặt bằng tại quận Tân Phú.</p>\r\n"
    "</body></html>\r\n"
)


def _qp(s: str) -> bytes:
    return quopri.encodestring(s.encode("utf-8"))


def _mhtml_confluence() -> bytes:
    b = b"----=_Part_6_1345403053"
    return (
        b"Date: Mon, 23 Mar 2026 14:31:39 +0700 (ICT)\r\n"
        b"Message-ID: <1684413841.7@localhost>\r\n"
        b"Subject: Exported From Confluence\r\n"
        b"MIME-Version: 1.0\r\n"
        b"Content-Type: multipart/related; \r\n\tboundary=\"" + b + b"\"\r\n\r\n"
        b"--" + b + b"\r\n"
        b"Content-Type: text/html; charset=UTF-8\r\n"
        b"Content-Transfer-Encoding: quoted-printable\r\n"
        b"Content-Location: file:///C:/exported.html\r\n\r\n" + _qp(HTML) + b"\r\n"
        b"--" + b + b"\r\n"
        b"Content-Type: image/png\r\nContent-Transfer-Encoding: base64\r\n"
        b"Content-Location: file:///C:/logo.png\r\n\r\niVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==\r\n"
        b"--" + b + b"--\r\n"
    )


def _mhtml_word() -> bytes:
    b = b"----=_NextPart_01DC"
    return (
        b"MIME-Version: 1.0\r\nContent-Type: multipart/related; boundary=\"" + b + b"\"\r\n\r\n"
        b"--" + b + b"\r\nContent-Type: text/html; charset=\"utf-8\"\r\n"
        b"Content-Transfer-Encoding: quoted-printable\r\n\r\n" + _qp(HTML) + b"\r\n"
        b"--" + b + b"--\r\n"
    )


class TepTam(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def ghi(self, ten, du_lieu: bytes) -> Path:
        p = self.dir / ten
        p.write_bytes(du_lieu)
        return p


class DocLaMhtml(TepTam):
    def test_nhan_dang(self):
        self.assertEqual(_loai_noi_dung_word(self.ghi("a.doc", _mhtml_confluence())), "mhtml")
        self.assertEqual(_loai_noi_dung_word(self.ghi("b.doc", _mhtml_word())), "mhtml")
        self.assertEqual(_loai_noi_dung_word(self.ghi("c.doc", HTML.encode())), "html")
        # Văn bản thuần có dòng "Kính gửi:" không phải gói MIME
        self.assertEqual(_loai_noi_dung_word(self.ghi("d.doc", "Kính gửi: Ban giám đốc".encode())), "khac")

    def test_bang_tien_do_giu_vi_tri_o_trong(self):
        """Bảng GIAI ĐOẠN của 913 Bee Art: ô ảnh logo trống, chỉ vài ô có chữ —
        phải còn đếm được ngày nằm dưới cột nào."""
        bang = ("<html><body><table>"
                "<tr><th>Đối tượng</th><th>Nhóm</th><th>Nộp đơn</th><th>Thông báo</th>"
                "<th>Nhận văn bằng</th></tr>\r\n"
                "<tr><td><img src='logo.png'></td><td>25: Quần áo</td><td></td><td></td>"
                "<td>06/06/2024</td></tr></table></body></html>")
        b = b"----=_P"
        du_lieu = (b"MIME-Version: 1.0\r\nContent-Type: multipart/related; boundary=\"" + b + b"\"\r\n\r\n"
                   b"--" + b + b"\r\nContent-Type: text/html; charset=UTF-8\r\n"
                   b"Content-Transfer-Encoding: quoted-printable\r\n\r\n" + _qp(bang) + b"\r\n--" + b + b"--\r\n")
        dong = extract_text_with_metadata(self.ghi("bang.doc", du_lieu)).text.splitlines()
        self.assertEqual(dong[0], "Đối tượng | Nhóm | Nộp đơn | Thông báo | Nhận văn bằng")
        self.assertEqual(dong[1], "| 25: Quần áo | | | 06/06/2024")
        self.assertEqual(dong[1].split("|")[4].strip(), "06/06/2024")

    def test_doc_ra_chu_khong_ra_ma_nguon(self):
        for ten, du_lieu in (("913+Bee+Art.doc", _mhtml_confluence()), ("word.docx", _mhtml_word())):
            with self.subTest(ten=ten):
                r = extract_text_with_metadata(self.ghi(ten, du_lieu))
                self.assertEqual(r.method, "mhtml-word")
                self.assertEqual(r.warnings, [])
                self.assertIn("Tổng hợp thông tin khách hàng — Bee Art", r.text)
                # Ô cùng hàng ngăn bằng " | "; "Văn\r\nAn" bẻ dòng trong mã nguồn phải liền lại
                self.assertIn("Người đại diện | Nguyễn Văn An", r.text)
                self.assertIn("tranh chấp hợp đồng thuê mặt bằng tại quận Tân Phú", r.text)
                for rac in ("MIME-Version", "quoted-printable", "=3D", "font-family",
                            "Content-Location", "iVBORw0", "<html", "Exported From Confluence"):
                    self.assertNotIn(rac, r.text)
                self.assertFalse(hoc_lai_ma_nguon.la_ma_nguon(r.text))


class NhanRaMaNguon(unittest.TestCase):
    def test_thuan(self):
        dau = "[Tài liệu: 913+Bee+Art | hồ sơ khách hàng — Bee Art]\n"
        self.assertTrue(hoc_lai_ma_nguon.la_ma_nguon(
            dau + "Date: Mon, 23 Mar 2026 14:31:39 +0700 (ICT)\nMessage-ID: <x>\n"
                  "Subject: Exported From Confluence\nMIME-Version: 1.0\n"))
        self.assertTrue(hoc_lai_ma_nguon.la_ma_nguon(dau + "<html xmlns:o=3D'urn:x'>\n<head>"))
        self.assertTrue(hoc_lai_ma_nguon.la_ma_nguon("<!DOCTYPE html><body>x</body>"))
        self.assertFalse(hoc_lai_ma_nguon.la_ma_nguon(
            dau + "Điều 1. Các bên thống nhất dùng chuẩn MIME-Version: 1.0 cho thư điện tử."))
        self.assertFalse(hoc_lai_ma_nguon.la_ma_nguon("QUYẾT ĐỊNH\nVề việc công bố văn bản hết hiệu lực"))
        self.assertFalse(hoc_lai_ma_nguon.la_ma_nguon(""))


class EpHocLai(TepTam):
    """kho.hoc_file: md5 không đổi thì thường bỏ qua; ep_hoc_lai phải học."""

    def setUp(self):
        super().setUp()
        self.root = self.dir.resolve()
        self.tep = self.root / "9. HỒ SƠ KHÁCH HÀNG" / "913. Bee Art" / "913+Bee+Art.doc"
        self.tep.parent.mkdir(parents=True)
        self.tep.write_bytes(_mhtml_confluence())
        self.key = "local:9. HỒ SƠ KHÁCH HÀNG/913. Bee Art/913+Bee+Art.doc"
        self.row = {"id": 42205, "title": "913+Bee+Art", "checksum": kho.file_md5(self.tep),
                    "approved": True, "label_verified": True, "extraction_status": "ready"}
        self.goi = []

        def learn_one(path, labels, key, fp, replace_id=None, diagnostics=None, **kw):
            self.goi.append({"path": path, "replace_id": replace_id,
                             "prev_approved": kw.get("prev_approved")})
            return True

        self.patches = [
            unittest.mock.patch.object(kho, "library_root", lambda: self.root),
            unittest.mock.patch.object(kho, "_tai_lieu_theo_khoa", lambda keys: {self.key: self.row}),
            unittest.mock.patch.object(kho.auto_learn, "resolve_labels",
                                       lambda parts, **kw: ({"doc_type": "ho_so_kh"}, None)),
            unittest.mock.patch.object(kho.auto_learn, "learn_one", learn_one),
            unittest.mock.patch.object(kho.auto_learn, "_clear_failure", lambda key: None),
            unittest.mock.patch.object(kho.db, "audit", lambda *a, **k: None),
            unittest.mock.patch.object(kho.db, "session", unittest.mock.MagicMock()),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        super().tearDown()

    def test_khong_ep_thi_bo_qua_khi_md5_khong_doi(self):
        r = kho.hoc_file(kho.rel_cua(self.tep, self.root), None)
        self.assertIn("không đổi", r["note"])
        self.assertEqual(self.goi, [])

    def test_ep_thi_hoc_lai_thay_ban_cu_giu_trang_thai_duyet(self):
        r = kho.hoc_file(kho.rel_cua(self.tep, self.root), None, ep_hoc_lai=True)
        self.assertTrue(r["ok"])
        self.assertEqual(len(self.goi), 1)
        self.assertEqual(self.goi[0]["replace_id"], 42205)
        self.assertTrue(self.goi[0]["prev_approved"])


if __name__ == "__main__":
    unittest.main()
