"""07/10/2026: LibreOffice quá giờ để lại soffice.bin mồ côi quay 100% CPU
(máy chủ: hai tiến trình chạy 7 ngày). chay_soffice phải giết cả nhóm."""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from app import chay_soffice, ingest, xem_truoc


def _con_song(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # Tiến trình đã chết nhưng chưa được init thu dọn vẫn trả lời kill(0).
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().split()[2] != "Z"
    except OSError:
        return False


class ChaySofficeTest(unittest.TestCase):
    def test_ma_thoat_khac_0_la_loi(self):
        with self.assertRaises(subprocess.CalledProcessError):
            chay_soffice.chay([sys.executable, "-c", "import sys; sys.exit(3)"], timeout=30)

    def test_thanh_cong_khong_loi(self):
        chay_soffice.chay([sys.executable, "-c", "pass"], timeout=30)

    def test_qua_gio_bao_timeout(self):
        t0 = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired):
            chay_soffice.chay([sys.executable, "-c", "import time; time.sleep(60)"], timeout=0.5)
        self.assertLess(time.monotonic() - t0, 20)

    @unittest.skipUnless(os.name == "posix", "nhóm tiến trình chỉ có trên Linux")
    def test_qua_gio_giet_ca_tien_trinh_chau(self):
        # Giống libreoffice → oosplash → soffice.bin: cha sinh cháu rồi chờ.
        with tempfile.TemporaryDirectory() as d:
            pid_file = Path(d) / "chau.pid"
            ma = (
                "import subprocess, sys, time\n"
                "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
                f"open({str(pid_file)!r}, 'w').write(str(p.pid))\n"
                "p.wait()\n"
            )
            with self.assertRaises(subprocess.TimeoutExpired):
                chay_soffice.chay([sys.executable, "-c", ma], timeout=2)
            pid = int(pid_file.read_text())
            for _ in range(50):
                if not _con_song(pid):
                    break
                time.sleep(0.1)
            self.assertFalse(_con_song(pid), "tiến trình cháu còn sống sau khi quá giờ")


class NoiGoiDungChaySofficeTest(unittest.TestCase):
    """Ba chỗ gọi LibreOffice đều phải đi qua chay_soffice.chay."""

    def _qua_gio(self, cmd, timeout):
        raise subprocess.TimeoutExpired(cmd, timeout)

    def test_doc_word97(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.doc"
            p.write_bytes(b"\xd0\xcf\x11\xe0" + b"\0" * 100)
            with mock.patch("shutil.which", return_value="/usr/bin/soffice"), \
                    mock.patch.object(chay_soffice, "chay", self._qua_gio):
                with self.assertRaises(ingest.ExtractionError) as c:
                    ingest._extract_doc_strict(p)
            self.assertEqual(c.exception.code, "doc_conversion_failed")

    def test_chuyen_dinh_dang(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.odt"
            p.write_bytes(b"x")
            with mock.patch("shutil.which", return_value="/usr/bin/soffice"), \
                    mock.patch.object(chay_soffice, "chay", self._qua_gio):
                with self.assertRaises(ingest.ExtractionError) as c:
                    ingest._convert_via_libreoffice(p, "docx")
            self.assertEqual(c.exception.code, "office_conversion_failed")

    def test_xem_truoc(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.docx"
            p.write_bytes(b"x")
            with mock.patch.object(xem_truoc, "thu_muc_cache", return_value=Path(d)), \
                    mock.patch("shutil.which", return_value="/usr/bin/soffice"), \
                    mock.patch.object(chay_soffice, "chay", self._qua_gio):
                with self.assertRaises(xem_truoc.LoiXemTruoc):
                    xem_truoc.pdf_tu_office(p, "k")


if __name__ == "__main__":
    unittest.main()
