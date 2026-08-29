import io
import unittest
from datetime import date

from openpyxl import Workbook

from app.hr_api import HRImportError, is_effective_contract, parse_hr_upload


class EffectiveContractTests(unittest.TestCase):
    def test_date_boundaries_are_inclusive(self):
        target = date(2026, 8, 19)
        self.assertTrue(is_effective_contract("active", target, target, target))
        self.assertTrue(is_effective_contract("valid", None, None, target))
        self.assertFalse(is_effective_contract("active", date(2026, 8, 20), None, target))
        self.assertFalse(is_effective_contract("active", None, date(2026, 8, 18), target))

    def test_inactive_status_never_effective(self):
        target = date(2026, 8, 19)
        for status in ("expired", "terminated", "cancelled", "draft"):
            self.assertFalse(is_effective_contract(status, None, None, target))


class ImportParserTests(unittest.TestCase):
    def test_vietnamese_csv_and_multiple_contracts_are_grouped_by_code(self):
        content = (
            "Mã nhân viên;Họ tên;Phòng ban;Số hợp đồng;Ngày bắt đầu;Ngày kết thúc;Trạng thái hợp đồng\n"
            "nv01;Nguyễn Văn An;TVPL;hd-01;01/01/2026;31/12/2026;Còn hiệu lực\n"
            "NV01;Nguyễn Văn An;TVPL;hd-02;2027-01-01;;active\n"
        ).encode("utf-8")
        batch = parse_hr_upload("nhan-su.csv", content)
        self.assertEqual(batch.source_rows, 2)
        self.assertEqual(len(batch.records), 1)
        self.assertEqual(batch.records[0].employee_code, "NV01")
        self.assertEqual([c.contract_no for c in batch.records[0].contracts], ["HD-01", "HD-02"])
        self.assertFalse(batch.errors)
        self.assertTrue(batch.warnings)

    def test_conflicting_duplicate_employee_is_reported(self):
        content = (
            "employee_code,full_name,contract_no\n"
            "NV01,Nguyễn Văn An,HD01\n"
            "nv01,Nguyễn Văn Bình,HD02\n"
        ).encode("utf-8")
        batch = parse_hr_upload("employees.csv", content)
        self.assertTrue(batch.errors)
        self.assertIn("lặp nhưng khác", batch.errors[0].message)

    def test_invalid_contract_dates_are_reported(self):
        content = (
            "employee_code,full_name,contract_no,start_date,end_date\n"
            "NV01,Nguyễn Văn An,HD01,2026-12-31,2026-01-01\n"
        ).encode("utf-8")
        batch = parse_hr_upload("employees.csv", content)
        self.assertEqual(len(batch.errors), 1)
        self.assertIn("không được sau", batch.errors[0].message)

    def test_xlsx_is_parsed_in_memory(self):
        workbook = Workbook()
        sheet = workbook.worksheets[0]
        sheet.append(["employee_code", "full_name", "employment_status", "active"])
        sheet.append(["NV02", "Trần Thị B", "Đang làm việc", "Có"])
        stream = io.BytesIO()
        workbook.save(stream)
        workbook.close()
        batch = parse_hr_upload("employees.xlsx", stream.getvalue())
        self.assertEqual(batch.records[0].employee_code, "NV02")
        self.assertTrue(batch.records[0].active)
        self.assertFalse(batch.errors)

    def test_unsafe_and_legacy_excel_names_are_rejected(self):
        with self.assertRaises(HRImportError):
            parse_hr_upload("../employees.csv", b"employee_code,full_name\nNV1,A")
        with self.assertRaises(HRImportError):
            parse_hr_upload("employees.xls", b"not-an-xls")

    def test_formula_cells_are_rejected(self):
        workbook = Workbook()
        sheet = workbook.worksheets[0]
        sheet.append(["employee_code", "full_name"])
        sheet.append(["NV03", "=1+1"])
        stream = io.BytesIO()
        workbook.save(stream)
        workbook.close()
        with self.assertRaises(HRImportError):
            parse_hr_upload("employees.xlsx", stream.getvalue())


if __name__ == "__main__":
    unittest.main()
