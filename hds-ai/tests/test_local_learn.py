"""
Test app/local_learn.py — phần THUẦN (không cần PostgreSQL/Ollama).

Chay: python -m unittest tests.test_local_learn -v

Bộ quét thư mục nội bộ thay bộ quét Drive (quyết định 27/08/2026). Ba thứ phải
đúng tuyệt đối, vì sai là học trùng hoặc mất tài liệu đang phục vụ:
  · danh tính file = đường dẫn tương đối, ổn định giữa các lần quét;
  · bỏ đúng thứ cần bỏ (uploads/, file khoá Office, rác hệ điều hành);
  · cây thư mục cắt ra `parts` khớp dạng auto_learn.resolve_labels đang nhận.
"""
import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from app import local_learn as ll


class WalkLibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def touch(self, rel: str, content: bytes = b"noi dung"):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
        return p

    def test_cat_dung_cay_thu_muc_thanh_parts(self):
        self.touch("9. HỒ SƠ KHÁCH HÀNG/[SUN] Tập đoàn Sun/3. Hợp đồng/hd.docx")
        items = ll.walk_library(self.root)
        self.assertEqual(len(items), 1)
        _path, parts = items[0]
        self.assertEqual(parts, ["9. HỒ SƠ KHÁCH HÀNG", "[SUN] Tập đoàn Sun", "3. Hợp đồng"])

    def test_file_o_goc_co_parts_rong(self):
        self.touch("ghi-chu.txt")
        _path, parts = ll.walk_library(self.root)[0]
        self.assertEqual(parts, [])

    def test_bo_qua_thu_muc_uploads(self):
        """uploads/ là nơi API cất file tải lên qua web — đã có bản ghi riêng,
        quét lại là tạo bản ghi trùng cho cùng một tài liệu."""
        self.touch("uploads/other/2026-08/abc_hop-dong.pdf")
        self.touch("1. VĂN BẢN PHÁP LUẬT/luat.pdf")
        names = [p.name for p, _ in ll.walk_library(self.root)]
        self.assertEqual(names, ["luat.pdf"])

    def test_bo_qua_rac_he_dieu_hanh_va_file_khoa_office(self):
        self.touch("1. VĂN BẢN PHÁP LUẬT/~$hop-dong.docx")   # file khoá Word
        self.touch("1. VĂN BẢN PHÁP LUẬT/Thumbs.db")
        self.touch("1. VĂN BẢN PHÁP LUẬT/.DS_Store")
        self.touch("1. VĂN BẢN PHÁP LUẬT/that.docx")
        names = [p.name for p, _ in ll.walk_library(self.root)]
        self.assertEqual(names, ["that.docx"])

    def test_bo_qua_ca_thu_muc_an(self):
        self.touch(".git/objects/abc")
        self.touch("__pycache__/x.pyc")
        self.assertEqual(ll.walk_library(self.root), [])

    def test_thu_muc_khong_ton_tai_tra_rong(self):
        self.assertEqual(ll.walk_library(self.root / "khong-co"), [])


class LocalKeyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_khoa_la_duong_dan_tuong_doi_dau_gach_xuoi(self):
        p = self.root / "8. HỒ SƠ NHÂN SỰ" / "Ngân" / "cv.pdf"
        key = ll.local_key(self.root, p)
        self.assertEqual(key, "local:8. HỒ SƠ NHÂN SỰ/Ngân/cv.pdf")
        self.assertTrue(key.startswith(ll.LOCAL_PREFIX))

    def test_khoa_on_dinh_giua_hai_lan_goi(self):
        p = self.root / "a" / "b.docx"
        self.assertEqual(ll.local_key(self.root, p), ll.local_key(self.root, p))

    def test_hai_file_khac_thu_muc_khac_khoa(self):
        a = ll.local_key(self.root, self.root / "Mai" / "cv.pdf")
        b = ll.local_key(self.root, self.root / "Ngân" / "cv.pdf")
        self.assertNotEqual(a, b)


class FileMd5Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_noi_dung_giong_nhau_cho_cung_ma(self):
        a = self.root / "a.txt"; a.write_bytes(b"HDS")
        b = self.root / "b.txt"; b.write_bytes(b"HDS")
        self.assertEqual(ll.file_md5(a), ll.file_md5(b))

    def test_sua_noi_dung_thi_ma_doi(self):
        p = self.root / "a.txt"
        p.write_bytes(b"ban cu")
        truoc = ll.file_md5(p)
        p.write_bytes(b"ban moi da sua")
        self.assertNotEqual(truoc, ll.file_md5(p))

    def test_khop_md5_cua_drive(self):
        """Drive trả md5Checksum của CHÍNH byte tệp. Nhờ trùng thuật toán, tài
        liệu đồng bộ từ Drive trước đây sau khi gắn lại danh tính local sẽ có
        checksum khớp và KHÔNG bị học lại — đây là chốt của bước chuyển đổi."""
        import hashlib
        p = self.root / "a.pdf"
        data = b"%PDF-1.7 noi dung gia lap"
        p.write_bytes(data)
        self.assertEqual(ll.file_md5(p), hashlib.md5(data).hexdigest())


class AllowedRootsTests(unittest.TestCase):
    """Rào an toàn của nút Tải về/Xem trước phải bao CẢ kho lẫn DATA_RAW.

    Tách kho sang ổ khác mà rào chỉ biết DATA_RAW thì mọi tài liệu trả 404
    'Tệp gốc không còn trên máy chủ' (rà soát 27/08/2026)."""

    def test_gom_ca_hai_thu_muc_khi_khac_nhau(self):
        with unittest.mock.patch.dict(
                os.environ, {"DATA_LIB": "/mnt/data2/kho", "DATA_RAW": "./data/raw"}):
            roots = [str(p) for p in ll.allowed_roots()]
        self.assertEqual(len(roots), 2)
        self.assertTrue(any("kho" in r for r in roots))
        self.assertTrue(any("raw" in r for r in roots))

    def test_khong_lap_khi_trung_nhau(self):
        with unittest.mock.patch.dict(
                os.environ, {"DATA_LIB": "./data/raw", "DATA_RAW": "./data/raw"}):
            roots = ll.allowed_roots()
        self.assertEqual(len(roots), 1)

    def test_duong_dan_luon_tuyet_doi(self):
        with unittest.mock.patch.dict(os.environ, {"DATA_LIB": "./data/raw"}):
            for p in ll.allowed_roots():
                self.assertTrue(p.is_absolute())


class MinLibraryRatioTests(unittest.TestCase):
    """Ngưỡng phát hiện 'ổ chưa mount': kho vơi quá nửa là dừng, không báo xanh."""

    def _abort(self, n_items, n_known):
        return bool(n_known) and n_items < max(1, int(n_known * ll.MIN_LIBRARY_RATIO))

    def test_o_chua_mount_thi_dung(self):
        self.assertTrue(self._abort(0, 800))      # thư mục rỗng
        self.assertTrue(self._abort(12, 800))     # mount nhầm chỗ

    def test_xoa_vai_file_thi_van_chay(self):
        self.assertFalse(self._abort(795, 800))
        self.assertFalse(self._abort(400, 800))   # đúng ngưỡng, chưa chặn

    def test_kho_moi_tinh_khong_bi_chan(self):
        self.assertFalse(self._abort(0, 0))       # chưa học gì thì không có mốc


class SkipRuleTests(unittest.TestCase):
    def test_is_skippable(self):
        self.assertTrue(ll.is_skippable(Path("~$hop-dong.docx")))
        self.assertTrue(ll.is_skippable(Path(".hidden")))
        self.assertTrue(ll.is_skippable(Path("Thumbs.db")))
        self.assertTrue(ll.is_skippable(Path("desktop.ini")))
        self.assertFalse(ll.is_skippable(Path("hop-dong.docx")))
        self.assertFalse(ll.is_skippable(Path("1. Luật Doanh nghiệp.pdf")))


if __name__ == "__main__":
    unittest.main()
