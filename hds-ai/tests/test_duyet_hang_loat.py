"""Duyệt nhãn hàng loạt (app/duyet_hang_loat.py) — CSDL giả, không chạm Postgres.

Script này bật approved+label_verified cho hàng nghìn tài liệu một lượt, nên
sai một điều kiện là bot học phải chuỗi ký tự vụn hoặc hồ sơ sạch bị nhốt lại.
deploy/update.sh chạy bộ test này ngay trên máy chủ đang phục vụ.

Luật cần giữ:
  · chỉ đụng tài liệu CHƯA duyệt nhãn và còn active;
  · file đọc lỗi trên ngưỡng ở lại hàng chờ;
  · file KHÔNG cắt được đoạn nào luôn ở lại, dù tỉ lệ có đẹp;
  · tỉ lệ rác được ghi cho TẤT CẢ, kể cả cái bị giữ lại;
  · xem trước không ghi một câu UPDATE nào.
"""
import contextlib
import os
import tempfile
import unittest
import unittest.mock

try:
    import fcntl
except ImportError:      # Windows: không có flock, các ca liên quan sẽ bỏ qua
    fcntl = None

from app import duyet_hang_loat as dhl

SACH = ("Điều 15. Hợp đồng lao động phải được giao kết bằng văn bản và làm "
        "thành hai bản, mỗi bên giữ một bản.")
RAC = "R34 %4tiR 8H12 0m84 V387 otciiN NNUÊ Mimistry 2d 9f ÅISIÈFìLH G119"


class _Cursor:
    """Trả tài liệu cho truy vấn ứng viên, trả đoạn cho truy vấn chunks."""

    def __init__(self, docs, doan, log):
        self._docs, self._doan, self._log = docs, doan, log
        self._cho = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        gon = " ".join(sql.split())
        self._log.append((gon, params))
        if gon.startswith("SELECT content FROM chunks"):
            noi_dung = self._doan.get(params[0], "")
            self._cho = [(noi_dung,)] if noi_dung else []
        elif gon.startswith("SELECT id, title, client_id FROM documents"):
            self._cho = list(self._docs)
        else:
            self._cho = []

    def fetchall(self):
        return self._cho


class _Conn:
    def __init__(self, docs, doan, log):
        self._a = (docs, doan, log)

    def cursor(self):
        return _Cursor(*self._a)


class DuyetHangLoat(unittest.TestCase):
    def _chay(self, docs, doan, thuc_hien=False, nguong=0.20):
        log = []

        @contextlib.contextmanager
        def session(**_kw):
            yield _Conn(docs, doan, log)

        with unittest.mock.patch.object(dhl.db, "session", session):
            with unittest.mock.patch.object(dhl, "dang_quet_kho", lambda: False):
                argv = ["--nguong", str(nguong)]
                if thuc_hien:
                    argv.append("--thuc-hien")
                with unittest.mock.patch("sys.stdout"):
                    ma = dhl.main(argv)
        return ma, log

    @staticmethod
    def _id_duoc_duyet(log):
        for sql, params in log:
            if "SET label_verified=true, approved=true" in sql:
                return list(params[0])
        return []

    @staticmethod
    def _ty_le_da_ghi(log):
        return {p[1]: p[0] for sql, p in log
                if sql.startswith("UPDATE documents SET ty_le_rac")}

    def test_file_sach_duoc_duyet_file_rac_o_lai(self):
        docs = [(1, "Hợp đồng lao động", 237), (2, "Bản sao hộ chiếu", 237)]
        _ma, log = self._chay(docs, {1: SACH, 2: RAC}, thuc_hien=True)
        self.assertEqual(self._id_duoc_duyet(log), [1])

    def test_khong_cat_duoc_doan_thi_giu_lai(self):
        docs = [(3, "PDF scan hỏng", 237)]
        _ma, log = self._chay(docs, {3: ""}, thuc_hien=True)
        self.assertEqual(self._id_duoc_duyet(log), [])
        # Không đoạn nào → tỉ lệ 1.0, và phải được ghi lại để người soát thấy.
        self.assertEqual(self._ty_le_da_ghi(log), {3: 1.0})

    def test_ghi_ty_le_cho_ca_cai_bi_giu_lai(self):
        docs = [(1, "sạch", 237), (2, "rác", 237)]
        _ma, log = self._chay(docs, {1: SACH, 2: RAC}, thuc_hien=True)
        da_ghi = self._ty_le_da_ghi(log)
        self.assertEqual(sorted(da_ghi), [1, 2])
        self.assertLess(da_ghi[1], 0.20)
        self.assertGreater(da_ghi[2], 0.20)

    def test_xem_truoc_khong_ghi_gi(self):
        docs = [(1, "sạch", 237), (2, "rác", 237)]
        _ma, log = self._chay(docs, {1: SACH, 2: RAC}, thuc_hien=False)
        self.assertFalse([s for s, _ in log if s.startswith("UPDATE")])
        self.assertFalse([s for s, _ in log if s.startswith("INSERT")])

    def test_chi_lay_tai_lieu_chua_duyet_va_con_active(self):
        _ma, log = self._chay([(1, "x", None)], {1: SACH})
        chon = [s for s, _ in log if s.startswith("SELECT id, title, client_id")][0]
        self.assertIn("NOT label_verified", chon)
        self.assertIn("coalesce(active, true)", chon)

    def test_nguong_cao_hon_thi_duyet_ca_file_rac(self):
        docs = [(2, "rác", 237)]
        _ma, log = self._chay(docs, {2: RAC}, thuc_hien=True, nguong=0.95)
        self.assertEqual(self._id_duoc_duyet(log), [2])

    def test_nguong_vo_ly_bi_tu_choi(self):
        for xau in ("0", "1", "-0.2", "1.5"):
            with unittest.mock.patch("sys.stderr"):
                self.assertEqual(dhl.main(["--nguong", xau]), 2)

    def test_dang_quet_kho_thi_khong_cho_ghi(self):
        @contextlib.contextmanager
        def session(**_kw):
            raise AssertionError("không được mở CSDL khi kho đang quét")
            yield

        with unittest.mock.patch.object(dhl.db, "session", session):
            with unittest.mock.patch.object(dhl, "dang_quet_kho", lambda: True):
                with unittest.mock.patch("sys.stderr"):
                    self.assertEqual(dhl.main(["--thuc-hien"]), 3)


class KhoaQuetKho(unittest.TestCase):
    """Bộ quét kho giữ chỗ bằng flock, KHÔNG bằng sự tồn tại của file.

    File /tmp/hds-ai-quet-kho.lock nằm lại sau mỗi lượt quét. Nếu chốt này đọc
    nhầm "file còn đó = đang quét" thì --thuc-hien từ chối chạy vĩnh viễn kể
    từ lượt quét đầu tiên — đúng lỗi đã gặp ngày 15/09/2026.
    """

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(delete=False)
        self.tmp.close()
        self.addCleanup(os.unlink, self.tmp.name)
        va_khoa = unittest.mock.patch.object(dhl, "KHOA_QUET_KHO", self.tmp.name)
        va_khoa.start()
        self.addCleanup(va_khoa.stop)

    def test_khong_co_file_thi_khong_phai_dang_quet(self):
        with unittest.mock.patch.object(dhl, "KHOA_QUET_KHO", self.tmp.name + "_khong_ton_tai"):
            self.assertFalse(dhl.dang_quet_kho())

    @unittest.skipUnless(fcntl, "cần fcntl (Linux) — máy chủ chạy test này")
    def test_file_con_do_nhung_khong_ai_giu_thi_duoc_chay(self):
        self.assertFalse(dhl.dang_quet_kho())

    @unittest.skipUnless(fcntl, "cần fcntl (Linux) — máy chủ chạy test này")
    def test_co_nguoi_giu_khoa_thi_bao_dang_quet(self):
        with open(self.tmp.name, "a") as giu:
            fcntl.flock(giu.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                self.assertTrue(dhl.dang_quet_kho())
            finally:
                fcntl.flock(giu.fileno(), fcntl.LOCK_UN)
        # Nhả khoá ra là chạy lại được ngay.
        self.assertFalse(dhl.dang_quet_kho())


if __name__ == "__main__":
    unittest.main()
