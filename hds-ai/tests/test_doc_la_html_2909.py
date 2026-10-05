"""Tệp Word nhận dạng theo NỘI DUNG, không theo đuôi (29/09/2026).

Kho thật có 1.626 tệp không học được, trong đó:
  · 1.427 tệp .doc là HTML kiểu Word (bản "tải Word" của trang văn bản luật) —
    LibreOffice không xuất được DOCX từ Writer/Web → doc_conversion_failed;
  · 27 tệp .docx 2026 nén bằng công cụ Windows, tên mục 'word\\document.xml'
    → python-docx KeyError → invalid_docx;
  · 12 tệp là trang báo lỗi SharePoint / trang ASP rỗng (tải về hỏng) — những
    tệp này PHẢI tiếp tục bị từ chối, không được học thành tài liệu rác.
"""
import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from app.ingest import ExtractionError, _loai_noi_dung_word, extract_text_with_metadata

WORD_HTML = (
    "<html xmlns:v='urn:schemas-microsoft-com:vml' xmlns:w='urn:schemas-microsoft-com:office:word'>"
    "<head><!--[if gte mso 9]><xml><w:WordDocument><w:View>Print</w:View></w:WordDocument></xml>"
    "<![endif]--><style>p {margin:0}</style></head>\r\n<body>"
    "<p>ỦY BAN NHÂN\r\nDÂN QUẬN TÂN PHÚ</p><p>Số: 4708/QĐ-UBND</p>"
    "<p><b>Điều 1.</b> Công bố 26 văn bản của Hội đồng nhân dân quận\r\nTân Phú hết hiệu lực.</p>"
    "<p><b>Điều 2.</b> Quyết định này có hiệu lực thi hành kể từ ngày ký.</p>"
    "</body></html>"
)
SHAREPOINT_LOI = (
    '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN" "x.dtd"><html><head><title>Error</title>'
    '<script>RegisterSod("initstrings.js", "\\u002f_layouts\\u002f15\\u002finitstrings.js");</script>'
    "</head><body><div>Sorry, something went wrong</div></body></html>"
)
ASP_RONG = (
    '<!DOCTYPE html><html xmlns="http://www.w3.org/1999/xhtml"><head id="Head1"><title>\r\n</title></head>'
    '<body><form method="post" action="doc.aspx?p=x"><input type="hidden" name="__VIEWSTATE" value="/wEP" />'
    "<div>\r\n</div></form></body></html>"
)


def _docx_bytes(*doan: str) -> bytes:
    from docx import Document
    d = Document()
    for t in doan:
        d.add_paragraph(t)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def _nen_lai_gach_nguoc(du_lieu: bytes) -> bytes:
    """Đóng gói lại như công cụ Windows: tên mục dùng '\\' thay '/'. Gán
    filename SAU khi tạo ZipInfo — hàm dựng tự đổi os.sep thành '/' trên Windows."""
    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(du_lieu)) as src, \
            zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as out:
        for info in src.infolist():
            zi = zipfile.ZipInfo(info.filename)
            zi.filename = info.filename.replace("/", "\\")
            zi.compress_type = zipfile.ZIP_DEFLATED
            out.writestr(zi, src.read(info))
    return buf.getvalue()


class TepTam(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def ghi(self, ten: str, noi_dung) -> Path:
        p = self.dir / ten
        p.write_bytes(noi_dung.encode("utf-8") if isinstance(noi_dung, str) else noi_dung)
        return p


class NhanDang(TepTam):
    def test_theo_byte_dau(self):
        self.assertEqual(_loai_noi_dung_word(self.ghi("a.doc", WORD_HTML)), "html")
        self.assertEqual(_loai_noi_dung_word(self.ghi("b.doc", "﻿\r\n" + ASP_RONG)), "html")
        self.assertEqual(_loai_noi_dung_word(self.ghi("c.doc", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1rest")), "ole")
        self.assertEqual(_loai_noi_dung_word(self.ghi("d.doc", "{\\rtf1\\ansi hello}")), "rtf")
        self.assertEqual(_loai_noi_dung_word(self.ghi("e.doc", _docx_bytes("x"))), "zip")
        self.assertEqual(_loai_noi_dung_word(self.ghi("f.doc", b"\x00\x01binary")), "khac")
        self.assertEqual(_loai_noi_dung_word(self.ghi("g.doc", b"%PDF-1.4\n%\xc7\xec")), "pdf")
        # 14 tệp thật là HTML lưu UTF-16 có BOM
        self.assertEqual(_loai_noi_dung_word(self.ghi("h.doc", WORD_HTML.encode("utf-16"))), "html")


class DocLaHtml(TepTam):
    def test_doc_html_doc_duoc_va_noi_dong_giua_cau(self):
        r = extract_text_with_metadata(self.ghi("4708-QĐ-UBND.doc", WORD_HTML))
        self.assertEqual(r.method, "html-word")
        self.assertEqual(r.warnings, [], "cảnh báo sẽ đẩy tài liệu luật vào hàng chờ duyệt")
        self.assertIn("ỦY BAN NHÂN DÂN QUẬN TÂN PHÚ", r.text)
        self.assertIn("Điều 1. Công bố 26 văn bản của Hội đồng nhân dân quận Tân Phú hết hiệu lực.", r.text)
        dong = r.text.splitlines()
        self.assertTrue(any(d.startswith("Điều 2.") for d in dong), "mỗi Điều phải bắt đầu một dòng")
        self.assertNotIn("WordDocument", r.text)
        self.assertNotIn("Print", r.text)

    def test_html_utf16_co_bom(self):
        r = extract_text_with_metadata(self.ghi("utf16.doc", WORD_HTML.encode("utf-16")))
        self.assertIn("Điều 2. Quyết định này có hiệu lực thi hành kể từ ngày ký.", r.text)
        self.assertNotIn("\x00", r.text)

    def test_trang_loi_va_trang_rong_khong_duoc_hoc(self):
        for ten, nd in (("loi.docx", SHAREPOINT_LOI), ("loi.doc", SHAREPOINT_LOI),
                        ("rong.doc", ASP_RONG)):
            with self.subTest(ten=ten):
                with self.assertRaises(ExtractionError) as ctx:
                    extract_text_with_metadata(self.ghi(ten, nd))
                self.assertEqual(ctx.exception.code, "web_error_page")


class DocxNenGachNguoc(TepTam):
    def test_docx_ten_muc_gach_nguoc_van_doc_duoc(self):
        du_lieu = _nen_lai_gach_nguoc(_docx_bytes("NGHỊ ĐỊNH", "Điều 1. Phạm vi điều chỉnh"))
        # Zipfile trên Windows tự đổi '\\' về '/' lúc đọc nên máy dev không tái
        # hiện được KeyError; máy chủ Linux thì có. Kiểm byte thô của gói.
        self.assertIn(b"word\\document.xml", du_lieu)
        r = extract_text_with_metadata(self.ghi("125-2026-NĐ-CP.docx", du_lieu))
        self.assertIn("Điều 1. Phạm vi điều chỉnh", r.text)

    def test_doc_thuc_ra_la_docx(self):
        r = extract_text_with_metadata(self.ghi("doi-duoi.doc", _docx_bytes("Hợp đồng lao động")))
        self.assertIn("Hợp đồng lao động", r.text)


if __name__ == "__main__":
    unittest.main()
