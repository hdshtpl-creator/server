"""Cây thư mục kho trên trang Tổng quan (app/kho.py) — phần THUẦN.

Ba thứ phải đúng tuyệt đối:
  · đường dẫn người dùng gửi bị NHỐT trong kho — không '..' , không tuyệt đối,
    không đoạn ẩn/khoá Office, không thư mục bộ quét bỏ qua (uploads/);
  · trạng thái từng file suy từ bản ghi documents đúng luật của bộ quét;
  · liệt kê một tầng bỏ đúng rác, phân trang và lọc đúng.
Không chạm CSDL: các hàm truy vấn được vá bằng dict giả.
"""
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from app import kho


class DuongDanKho(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()

    def tearDown(self):
        self.tmp.cleanup()

    def test_goc(self):
        self.assertEqual(kho.duong_dan_kho("", self.root), self.root)
        self.assertEqual(kho.duong_dan_kho("/", self.root), self.root)
        self.assertEqual(kho.duong_dan_kho("  ", self.root), self.root)

    def test_thu_muc_con_va_dau_gach_nguoc(self):
        muon = self.root / "2. BẢN ÁN" / "2026"
        self.assertEqual(kho.duong_dan_kho("2. BẢN ÁN/2026", self.root), muon)
        self.assertEqual(kho.duong_dan_kho("2. BẢN ÁN\\2026\\", self.root), muon)
        self.assertEqual(kho.duong_dan_kho("/2. BẢN ÁN/./2026/", self.root), muon)

    def test_chan_thoat_ra_ngoai_kho(self):
        for xau in ("..", "a/../..", "../x", "C:/Windows", "a/.git/x",
                    "~$tmp.docx", "uploads/x.pdf", ".env"):
            with self.subTest(xau=xau):
                with self.assertRaises(kho.LoiKho):
                    kho.duong_dan_kho(xau, self.root)
        # Dấu / đầu chỉ bị bỏ — đường dẫn "tuyệt đối" vẫn bị nhốt trong kho.
        self.assertEqual(kho.duong_dan_kho("/etc/passwd", self.root),
                         self.root / "etc" / "passwd")

    def test_rel_cua_va_rel_tu_khoa(self):
        self.assertEqual(kho.rel_cua(self.root / "a" / "b.pdf", self.root), "a/b.pdf")
        self.assertEqual(kho.rel_tu_khoa("local:2. BẢN ÁN/2026/x.pdf"), "2. BẢN ÁN/2026/x.pdf")
        self.assertIsNone(kho.rel_tu_khoa("1AbCdrive"))
        self.assertIsNone(kho.rel_tu_khoa(None))


class TenThuMuc(unittest.TestCase):
    def test_hop_le_va_gom_khoang_trang(self):
        self.assertEqual(kho.ten_thu_muc_hop_le("Lao dong 2027"), "Lao dong 2027")
        self.assertEqual(kho.ten_thu_muc_hop_le("  a   b "), "a b")

    def test_khong_hop_le(self):
        for ten in ("", "a/b", "a\\b", "..", ".x", "~$x", "x" * 121, "a:b", "uploads", "a?b"):
            with self.subTest(ten=ten):
                with self.assertRaises(kho.LoiKho):
                    kho.ten_thu_muc_hop_le(ten)


class DieuKienTim(unittest.TestCase):
    def test_moi_tu_mot_dieu_kien(self):
        sql, tham_so = kho.dieu_kien_tim("  Bộ luật  Dân sự ")
        self.assertEqual(sql.count(" ILIKE %s"), 4)
        self.assertEqual(sql.count(" AND "), 3)
        self.assertEqual(tham_so, ["%Bộ%", "%luật%", "%Dân%", "%sự%"])
        self.assertIn("replace(d.title, '-', ' ')", sql)
        self.assertIn("d.trich_yeu", sql)

    def test_rong_va_qua_dai(self):
        self.assertEqual(kho.dieu_kien_tim(""), ("TRUE", []))
        _sql, tham_so = kho.dieu_kien_tim("a b c d e f g h")
        self.assertEqual(len(tham_so), 6)


class TrangThaiFile(unittest.TestCase):
    def test_theo_ban_ghi(self):
        self.assertEqual(kho.trang_thai_file(None, ".xls"), "khong_ho_tro")
        self.assertEqual(kho.trang_thai_file(None, ".pdf"), "chua_hoc")
        self.assertEqual(kho.trang_thai_file(None, ".pdf", {"code": "pdf_no_text"}), "loi")
        self.assertEqual(kho.trang_thai_file(
            {"approved": False, "label_verified": False, "extraction_status": "ready"}, ".PDF"),
            "cho_duyet")
        self.assertEqual(kho.trang_thai_file(
            {"approved": True, "label_verified": True, "extraction_status": "warning"}, ".pdf"),
            "canh_bao")
        self.assertEqual(kho.trang_thai_file(
            {"approved": True, "label_verified": True, "extraction_status": "ready"}, ".docx"),
            "da_hoc")


class DichDaGo(unittest.TestCase):
    def test_giu_cay_cu_khong_ghi_de(self):
        with tempfile.TemporaryDirectory() as t:
            thung = Path(t)
            d1 = kho.dich_da_go(thung, "2. BẢN ÁN/2026/x.pdf")
            self.assertEqual(d1, thung / "2. BẢN ÁN" / "2026" / "x.pdf")
            d1.parent.mkdir(parents=True)
            d1.write_bytes(b"cu")
            d2 = kho.dich_da_go(thung, "2. BẢN ÁN/2026/x.pdf")
            self.assertNotEqual(d1, d2)
            self.assertEqual(d2.parent, d1.parent)
            self.assertTrue(d2.name.startswith("x__") and d2.suffix == ".pdf")


BAN_GHI = {
    "local:2. BẢN ÁN/2026/x.pdf": {
        "id": 11, "title": "Bản án x", "doc_type": "ban_an", "access_level": "public",
        "approved": True, "label_verified": True, "extraction_status": "ready",
        "so_hieu": "01/2026/LĐ-ST", "checksum": "abc", "client_name": None,
        "active": True, "so_doan": 12, "created_at": None},
    "local:2. BẢN ÁN/2026/y.pdf": {
        "id": 12, "title": "Bản án y", "doc_type": "ban_an", "access_level": "public",
        "approved": False, "label_verified": False, "extraction_status": "warning",
        "so_hieu": None, "checksum": "def", "client_name": None,
        "active": True, "so_doan": 3, "created_at": None},
}
LOI = {"local:2. BẢN ÁN/2025/z.pdf": {"code": "pdf_no_text", "message": "Không có chữ",
                                     "hint": "Scan lại"}}


class LietKe(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        for rel in ("1. VĂN BẢN LUẬT/Luật-01.docx", "2. BẢN ÁN/2026/x.pdf",
                    "2. BẢN ÁN/2026/y.pdf", "2. BẢN ÁN/2026/ghi chu.xls",
                    "2. BẢN ÁN/2025/z.pdf", "uploads/a.pdf", ".git/config",
                    "~$khoa.docx", "2. BẢN ÁN/Thumbs.db"):
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"x")
        kho.quen_dem()
        self.patches = [
            unittest.mock.patch.object(kho, "library_root", lambda: self.root),
            unittest.mock.patch.object(kho, "_tai_lieu_theo_khoa",
                                       lambda keys: {k: BAN_GHI[k] for k in keys if k in BAN_GHI}),
            unittest.mock.patch.object(kho, "_loi_theo_khoa",
                                       lambda keys: {k: LOI[k] for k in keys if k in LOI}),
            unittest.mock.patch.object(kho, "_dem_theo_tien_to",
                                       lambda rel: {"da_hoc": 1, "cho_duyet": 1, "tong_ban_ghi": 2}),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_goc_bo_uploads_va_rac(self):
        tang = kho.liet_ke("")
        self.assertEqual(tang["path"], "")
        self.assertEqual([d["ten"] for d in tang["thu_muc"]], ["1. VĂN BẢN LUẬT", "2. BẢN ÁN"])
        self.assertEqual(tang["tap_tin"], [])
        ban_an = tang["thu_muc"][1]
        self.assertEqual(ban_an["path"], "2. BẢN ÁN")
        self.assertEqual(ban_an["so_file"], 4)          # Thumbs.db không tính
        self.assertEqual(ban_an["da_hoc"], 1)

    def test_tang_con_trang_thai_tung_file(self):
        tang = kho.liet_ke("2. BẢN ÁN/2026")
        self.assertEqual(tang["ten"], "2026")
        self.assertEqual([f["ten"] for f in tang["tap_tin"]], ["ghi chu.xls", "x.pdf", "y.pdf"])
        self.assertEqual([f["trang_thai"] for f in tang["tap_tin"]],
                         ["khong_ho_tro", "da_hoc", "cho_duyet"])
        x = tang["tap_tin"][1]
        self.assertEqual(x["document_id"], 11)
        self.assertEqual(x["path"], "2. BẢN ÁN/2026/x.pdf")
        self.assertEqual(x["so_hieu"], "01/2026/LĐ-ST")
        self.assertEqual(tang["tong_tap_tin"], 3)

    def test_file_loi_hoc(self):
        tang = kho.liet_ke("2. BẢN ÁN/2025")
        z = tang["tap_tin"][0]
        self.assertEqual(z["trang_thai"], "loi")
        self.assertEqual(z["loi"]["code"], "pdf_no_text")

    def test_loc_va_phan_trang(self):
        # Lọc theo chuỗi con, không phân biệt hoa thường — "x" khớp cả ".xls".
        tang = kho.liet_ke("2. BẢN ÁN/2026", q="X")
        self.assertEqual([f["ten"] for f in tang["tap_tin"]], ["ghi chu.xls", "x.pdf"])
        tang = kho.liet_ke("2. BẢN ÁN/2026", q="Y.P")
        self.assertEqual([f["ten"] for f in tang["tap_tin"]], ["y.pdf"])
        tang = kho.liet_ke("2. BẢN ÁN/2026", offset=1, limit=1)
        self.assertEqual([f["ten"] for f in tang["tap_tin"]], ["x.pdf"])
        self.assertEqual(tang["tong_tap_tin"], 3)

    def test_thu_muc_khong_co_hoac_ngoai_kho(self):
        with self.assertRaises(kho.LoiKho):
            kho.liet_ke("khong-co")
        with self.assertRaises(kho.LoiKho):
            kho.liet_ke("../")

    def test_cho_tai_len(self):
        dest = kho.cho_tai_len("2. BẢN ÁN/2026", "moi.pdf")
        self.assertEqual(dest, self.root / "2. BẢN ÁN" / "2026" / "moi.pdf")
        # tên có đường dẫn → chỉ lấy tên file
        self.assertEqual(kho.cho_tai_len("2. BẢN ÁN/2026", "../../moi2.PDF").name, "moi2.PDF")
        for thu_muc, ten in (("", "a.pdf"), ("2. BẢN ÁN/2026", "x.pdf"),
                             ("2. BẢN ÁN/2026", ".an.pdf"), ("2. BẢN ÁN/2026", "a.xyz"),
                             ("khong-co", "a.pdf")):
            with self.subTest(thu_muc=thu_muc, ten=ten):
                with self.assertRaises(kho.LoiKho):
                    kho.cho_tai_len(thu_muc, ten)


class QuetLai(unittest.TestCase):
    def test_nhan_ra_lenh_quet(self):
        self.assertTrue(kho.la_lenh_quet(b".venv/bin/python\x00-m\x00app.local_learn\x00"))
        self.assertFalse(kho.la_lenh_quet(b"python\x00-m\x00app.local_learn\x00--dry-run\x00"))
        self.assertFalse(kho.la_lenh_quet(b"bash\x00-c\x00tail -f /tmp/x.log\x00"))

    def test_duoi_log_bo_canh_bao(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "quet.log"
            p.write_text("a\n\n/x/requests/__init__.py: RequestsDependencyWarning: urllib3\n"
                         "  warnings.warn(\nb\nc\n", encoding="utf-8")
            self.assertEqual(kho.duoi_log(p, n=2), ["b", "c"])
            self.assertEqual(kho.duoi_log(Path(t) / "khong-co.log"), [])

    def test_trang_thai_khi_khong_co_gi(self):
        with unittest.mock.patch.object(kho, "_tien_trinh_quet_khac", lambda: None):
            kho._QUET.clear()
            tt = kho.trang_thai_quet()
            self.assertFalse(tt["dang_chay"])
            self.assertIsNone(tt["ket_thuc"])
        with unittest.mock.patch.object(kho, "_tien_trinh_quet_khac", lambda: 4242):
            tt = kho.trang_thai_quet()
            self.assertTrue(tt["dang_chay"])
            self.assertEqual((tt["pid"], tt["nguon"]), (4242, "ngoai"))
            with self.assertRaises(kho.LoiKho):
                kho.bat_dau_quet(1)


if __name__ == "__main__":
    unittest.main()
