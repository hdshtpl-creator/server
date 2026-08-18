"""Unit test thuần cho trích xuất; không cần PostgreSQL, Ollama hay Google Drive.

Chạy: python -m unittest tests.test_ingest -v
"""
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from app import auto_learn
from app.auto_learn import auto_approve_from_env, drive_fingerprint
from app.ingest import (ExtractionError, ExtractionResult, extract_text,
                        extract_text_with_metadata, safe_path_component,
                        split_document_with_metadata)


class IngestExtractionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_csv_keeps_headers_and_vietnamese_values(self):
        path = self.root / "nhan-su.csv"
        path.write_text(
            "Họ tên;Tình trạng;Ngày hết hạn\n"
            "Nguyễn Văn An;Còn hiệu lực;2027-01-10\n",
            encoding="utf-8",
        )

        result = extract_text_with_metadata(path)

        self.assertEqual("csv", result.format)
        self.assertEqual(";", result.metadata["delimiter"])
        self.assertIn("Họ tên: Nguyễn Văn An", result.text)
        self.assertIn("Tình trạng: Còn hiệu lực", result.text)

    def test_xlsx_keeps_sheet_and_columns_but_skips_hidden_sheet(self):
        from openpyxl import Workbook

        path = self.root / "hop-dong.xlsx"
        workbook = Workbook()
        visible = workbook.active
        visible.title = "Hợp đồng"
        visible.append(["Nhân sự", "Ngày hết hạn"])
        visible.append(["Trần Bình", "2028-12-31"])
        hidden = workbook.create_sheet("Dữ liệu ẩn")
        hidden.append(["Mật khẩu", "không được học"])
        hidden.sheet_state = "hidden"
        workbook.save(path)

        result = extract_text_with_metadata(path)

        self.assertEqual("xlsx", result.method)
        self.assertIn("[Bảng: Hợp đồng]", result.text)
        self.assertIn("Nhân sự: Trần Bình", result.text)
        self.assertNotIn("không được học", result.text)
        self.assertTrue(any("sheet ẩn" in warning for warning in result.warnings))
        chunks = split_document_with_metadata(result, "other")
        self.assertEqual("Hợp đồng", chunks[0].section_title)
        self.assertIn("sheet:Hợp đồng;rows:2-2", chunks[0].source_locator)

    def test_corrupt_docx_has_stable_error_code(self):
        path = self.root / "hong.docx"
        path.write_bytes(b"not-a-docx")

        with self.assertRaises(ExtractionError) as caught:
            extract_text_with_metadata(path)

        self.assertEqual("invalid_docx", caught.exception.code)
        # API cũ vẫn không ném lỗi để giữ tương thích với caller hiện hữu.
        with redirect_stdout(io.StringIO()):
            self.assertEqual("", extract_text(path))

    def test_docx_reads_paragraphs_and_table_rows(self):
        from docx import Document

        path = self.root / "ho-so.docx"
        document = Document()
        document.add_heading("Nhân sự", level=1)
        document.add_paragraph("Thông tin hợp đồng lao động")
        table = document.add_table(rows=2, cols=2)
        table.cell(0, 0).text = "Nhân sự"
        table.cell(0, 1).text = "Trạng thái"
        table.cell(1, 0).text = "Lê Minh"
        table.cell(1, 1).text = "Còn hiệu lực"
        document.save(path)

        result = extract_text_with_metadata(path)

        self.assertEqual("python-docx", result.method)
        self.assertIn("Thông tin hợp đồng lao động", result.text)
        self.assertIn("Lê Minh | Còn hiệu lực", result.text)
        chunks = split_document_with_metadata(result, "other")
        self.assertEqual("Nhân sự", chunks[0].section_title)
        self.assertEqual("section:Nhân sự", chunks[0].source_locator)

    def test_pdf_page_markers_become_chunk_provenance(self):
        extraction = ExtractionResult(
            text="[Trang 1]\nNội dung trang thứ nhất.\n\n[Trang 2]\nNội dung trang thứ hai.",
            format="pdf", method="pdfplumber",
        )

        chunks = split_document_with_metadata(extraction, "other")

        self.assertEqual([1, 2], [chunk.page_number for chunk in chunks])
        self.assertEqual(["page:1", "page:2"], [chunk.source_locator for chunk in chunks])

    def test_empty_file_is_reported_explicitly(self):
        path = self.root / "rong.txt"
        path.write_bytes(b"")

        with self.assertRaises(ExtractionError) as caught:
            extract_text_with_metadata(path)

        self.assertEqual("empty_file", caught.exception.code)

    def test_drive_names_cannot_escape_destination(self):
        for unsafe in ("../secret.csv", "..", "a/b.xlsx", "a\\b.xlsx", "NUL.txt"):
            safe = safe_path_component(unsafe)
            self.assertNotIn("/", safe)
            self.assertNotIn("\\", safe)
            self.assertNotIn(safe, {"", ".", ".."})


class AutoLearnSafetyTests(unittest.TestCase):
    def test_review_is_default_and_legacy_env_remains_compatible(self):
        self.assertFalse(auto_approve_from_env({}))
        self.assertTrue(auto_approve_from_env({"AUTO_LEARN_AUTO_APPROVE": "1"}))
        self.assertFalse(auto_approve_from_env({"AUTO_LEARN_AUTO_APPROVE": "invalid"}))
        self.assertTrue(auto_approve_from_env({"AUTO_LEARN_REVIEW": "0"}))
        self.assertFalse(auto_approve_from_env({"AUTO_LEARN_REVIEW": "1"}))

    def test_google_native_file_has_stable_modified_time_fingerprint(self):
        info = {"modifiedTime": "2026-08-19T12:00:00.000Z"}
        self.assertEqual("gdrive-modified:2026-08-19T12:00:00.000Z",
                         drive_fingerprint(info))
        # File nhị phân giữ checksum cũ để không nạp lại một lần không cần thiết.
        self.assertEqual("abc", drive_fingerprint({"md5Checksum": "abc",
                                                   "modifiedTime": "later"}))

    def test_learn_one_writes_chunk_provenance_without_real_db_or_ollama(self):
        from openpyxl import Workbook

        class FakeCursor:
            def __init__(self):
                self.calls = []
                self.row = None

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, sql, params=None):
                self.calls.append((sql, params))
                if "RETURNING id" in sql:
                    self.row = (42,)

            def fetchone(self):
                return self.row

        class FakeConnection:
            def __init__(self, cursor):
                self._cursor = cursor

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def cursor(self):
                return self._cursor

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "nhan-su.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "Nhân sự"
            sheet.append(["Họ tên", "Trạng thái"])
            sheet.append(["Phạm An", "Còn hợp đồng"])
            workbook.save(path)

            cursor = FakeCursor()
            diagnostics = {}
            labels = {"doc_type": "ho_so_ns", "access_level": "internal",
                      "client_id": None, "department_id": None, "matter_id": None}
            with patch.object(auto_learn, "embed", return_value=[[0.1, 0.2]]), \
                    patch.object(auto_learn, "summarize", return_value="Tóm tắt"), \
                    patch.object(auto_learn.db, "session", return_value=FakeConnection(cursor)), \
                    patch.object(auto_learn.db, "audit"):
                with redirect_stdout(io.StringIO()):
                    learned = auto_learn.learn_one(
                        path, labels, "drive-id", "checksum", diagnostics=diagnostics)

        self.assertTrue(learned)
        chunk_call = next(call for call in cursor.calls if "INSERT INTO chunks" in call[0])
        self.assertIn("page_number", chunk_call[0])
        self.assertEqual("Nhân sự", chunk_call[1][4])
        self.assertEqual("sheet:Nhân sự;rows:2-2", chunk_call[1][5])
        self.assertEqual("xlsx", diagnostics["method"])


if __name__ == "__main__":
    unittest.main()
