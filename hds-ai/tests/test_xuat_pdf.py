"""Nút "Tải PDF" của bản nháp — docx_sang_pdf.

07/09/2026: bản đầu gọi nhầm tên hàm (_convert_WITH_libreoffice, không tồn
tại) → NameError → nút trả 500 trên máy chủ suốt từ lúc deploy 7729476, không
test nào bắt được vì chưa có test cho hàm này. Test này thay LibreOffice bằng
hàm giả (không cần soffice trên máy chạy test) và kiểm ba điều: gọi đúng hàm,
trả đúng bytes, dọn sạch cả hai thư mục tạm.
"""
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import ingest


class DocxSangPdf(unittest.TestCase):
    def test_goi_dung_ham_tra_bytes_va_don_tam(self):
        thu_muc_ra = []

        def gia_lap(path, target, timeout=180):
            self.assertEqual("pdf", target)
            self.assertEqual(b"DOCX-GIA", Path(path).read_bytes())
            out_dir = Path(tempfile.mkdtemp(prefix="hds_conv_test_"))
            thu_muc_ra.append(out_dir)
            out = out_dir / f"{Path(path).stem}.pdf"
            out.write_bytes(b"%PDF-1.4 gia")
            return out

        with mock.patch.object(ingest, "_convert_via_libreoffice", gia_lap):
            pdf = ingest.docx_sang_pdf(b"DOCX-GIA")
        self.assertEqual(b"%PDF-1.4 gia", pdf)
        self.assertEqual(1, len(thu_muc_ra))
        self.assertFalse(thu_muc_ra[0].exists(), "thư mục tạm của LibreOffice phải được dọn")
        # Thư mục tạm của chính docx_sang_pdf cũng không được để lại.
        con = [p for p in Path(tempfile.gettempdir()).glob("hds_pdf_*") if p.is_dir()]
        for p in con:
            shutil.rmtree(p, ignore_errors=True)
        self.assertEqual([], con, "docx_sang_pdf để sót thư mục tạm hds_pdf_*")

    def test_libreoffice_hong_thi_khong_de_sot_thu_muc_tam(self):
        def hong(path, target, timeout=180):
            raise ingest.ExtractionError("office_conversion_failed", "hỏng", "mở lại file")

        with mock.patch.object(ingest, "_convert_via_libreoffice", hong):
            with self.assertRaises(ingest.ExtractionError):
                ingest.docx_sang_pdf(b"x")
        con = [p for p in Path(tempfile.gettempdir()).glob("hds_pdf_*") if p.is_dir()]
        for p in con:
            shutil.rmtree(p, ignore_errors=True)
        self.assertEqual([], con)


if __name__ == "__main__":
    unittest.main()
