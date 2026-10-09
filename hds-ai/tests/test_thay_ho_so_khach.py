"""thay_ho_so_khach: cất bộ cũ, gỡ CSDL, đặt bộ mới — hỏng giữa chừng phải trả
bộ cũ về chỗ. Không chạm CSDL thật: db.session là đồ giả."""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import thay_ho_so_khach as t


class _Cur:
    def __init__(self, hong_o=None):
        self.lenh, self.hong_o, self.rowcount = [], hong_o, 0
        self._kq = []

    def execute(self, sql, args=None):
        self.lenh.append(sql)
        if self.hong_o and self.hong_o in sql:
            raise RuntimeError("CSDL hỏng")
        if sql.startswith("SELECT id FROM documents"):
            self._kq = [(1,), (2,)]
        elif sql.startswith("SELECT count(*), count(*) FILTER"):
            self._kq = [(2, 1, 1)]
        elif sql.startswith("SELECT count(*)"):
            self._kq = [(0,)]
        elif sql.startswith("SELECT code"):
            self._kq = [("1001", 5, "Khách A")]
        self.rowcount = 2

    def fetchone(self):
        return self._kq[0]

    def fetchall(self):
        return self._kq

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Conn:
    def __init__(self, cur):
        self.cur = cur

    def cursor(self):
        return self.cur


def _tao_cay(goc: Path, tep: dict):
    for duong, noi_dung in tep.items():
        p = goc / duong
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(noi_dung, encoding="utf-8")


class ThayHoSoKhachTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        goc = Path(self.tmp.name)
        self.lib = goc / "raw"
        self.moi = goc / "_tai_ve" / "moi"
        _tao_cay(self.lib, {f"{t.NGAN}/1001. Khách A/hd.txt": "cũ",
                            "1. VĂN BẢN PHÁP LUẬT/luat.txt": "luật"})
        _tao_cay(self.moi, {"1001. Khách A/hd mới.txt": "mới",
                            "1500. Khách B/bb.txt": "mới",
                            "Tài liệu chung/x.txt": "?"})
        self.cur = _Cur()
        self.vá = [
            mock.patch.object(t, "DATA_LIB", self.lib),
            mock.patch.object(t, "giu_khoa", contextlib.nullcontext),
            mock.patch.object(t.db, "audit", lambda *a, **k: None),
        ]
        for v in self.vá:
            v.start()

    def tearDown(self):
        for v in self.vá:
            v.stop()
        self.tmp.cleanup()

    def _session(self, cur):
        @contextlib.contextmanager
        def s(**kw):
            yield _Conn(cur)
        return mock.patch.object(t.db, "session", s)

    def _chay(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = t.main(list(args))
        return rc, out.getvalue()

    def test_xem_truoc_khong_doi_gi(self):
        with self._session(self.cur):
            rc, out = self._chay(str(self.moi))
        self.assertEqual(rc, 0)
        self.assertTrue((self.lib / t.NGAN / "1001. Khách A/hd.txt").exists())
        self.assertTrue(self.moi.exists())
        self.assertFalse(any(s.startswith("DELETE") for s in self.cur.lenh))
        self.assertIn("Mã khách trùng khách đã có trong CSDL: 1 · mã mới: 1", out)
        self.assertIn("Tài liệu chung", out)

    def test_thay_that(self):
        with self._session(self.cur):
            rc, _ = self._chay(str(self.moi), "--thuc-hien")
        self.assertEqual(rc, 0)
        ngan = self.lib / t.NGAN
        self.assertTrue((ngan / "1001. Khách A/hd mới.txt").exists())
        self.assertFalse((ngan / "1001. Khách A/hd.txt").exists())
        self.assertFalse(self.moi.exists())
        cat = list((self.lib.parent / "_da_go").glob("ho-so-khach-cu-*"))
        self.assertEqual(len(cat), 1)
        self.assertTrue((cat[0] / "1001. Khách A/hd.txt").exists())
        self.assertTrue((self.lib / "1. VĂN BẢN PHÁP LUẬT/luat.txt").exists())
        self.assertTrue(any(s.startswith("DELETE FROM documents") for s in self.cur.lenh))

    def test_csdl_hong_tra_bo_cu_ve_cho(self):
        cur = _Cur(hong_o="DELETE FROM documents")
        with self._session(cur), self.assertRaises(RuntimeError):
            self._chay(str(self.moi), "--thuc-hien")
        self.assertTrue((self.lib / t.NGAN / "1001. Khách A/hd.txt").exists())
        self.assertTrue(self.moi.exists())
        self.assertEqual(list((self.lib.parent / "_da_go").glob("ho-so-khach-cu-*")), [])

    def test_tu_choi_bo_moi_nam_trong_kho(self):
        trong_kho = self.lib / "tam"
        _tao_cay(trong_kho, {"1001. A/x.txt": "x"})
        with self._session(self.cur), self.assertRaises(SystemExit):
            self._chay(str(trong_kho), "--thuc-hien")
        self.assertTrue((self.lib / t.NGAN / "1001. Khách A/hd.txt").exists())

    def test_tu_choi_bo_moi_khong_co_thu_muc_khach(self):
        rong = Path(self.tmp.name) / "_tai_ve" / "rong"
        _tao_cay(rong, {"Tài liệu/x.txt": "x"})
        with self._session(self.cur), self.assertRaises(SystemExit):
            self._chay(str(rong), "--thuc-hien")
        self.assertTrue((self.lib / t.NGAN / "1001. Khách A/hd.txt").exists())


if __name__ == "__main__":
    unittest.main()
