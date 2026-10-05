"""Bật/tắt lịch chạy tự động từ web (app/lich_chay.py, 01/10/2026) — THUẦN.

Không chạm crontab thật: doc_crontab / ghi_crontab / dang_chay đều vá bằng
một crontab giả trong bộ nhớ. Điều phải đúng tuyệt đối: chỉ thêm/bỏ tiền tố
'#TAT# ' ở ĐÚNG dòng có nhãn đã chọn, mọi dòng khác (kể cả dòng không phải
của hệ thống) giữ nguyên từng ký tự.
"""
import tempfile
import unittest
import unittest.mock as mock
from datetime import datetime
from pathlib import Path

from app import lich_chay

CRON = """# m h  dom mon dow   command
MAILTO=""
*/3 * * * * /usr/bin/env bash '/home/pc/hds-ai-full/deploy/hoc-tu-thu-muc.sh' --cron  # hds-ai: quet kho tai lieu
*/15 * * * * flock -n /tmp/hds-duyet-tu-dong.lock /home/pc/tu-duyet.sh >> /home/pc/hds-ai-full/hds-ai/data/duyet_tu_dong.log 2>&1  # hds-ai: tu duyet <20% loi
7 * * * * flock -n /tmp/hds-hieu-luc.lock /home/pc/cap-nhat-hieu-luc.sh >> /x/hieu_luc.log 2>&1  # hds-ai: hieu luc tu vbpl
37 * * * * flock -n /tmp/hds-go-ban-cu.lock python3 /home/pc/go-ban-thay-the.py --thuc-hien >> /x/go_ban_cu.log 2>&1  # hds-ai: go ban thay the
0 4 * * 0 /home/pc/viec-rieng.sh
"""


class DongCrontab(unittest.TestCase):
    def test_phan_tich(self):
        d = lich_chay.phan_tich_dong(CRON.splitlines()[2])
        self.assertEqual((d["bat"], d["bieu_thuc"], d["nhan"]), (True, "*/3 * * * *", "quet kho tai lieu"))
        tat = lich_chay.phan_tich_dong("#TAT# 30 2 * * * bash x.sh --cron  # hds-ai: sao luu CSDL + kho")
        self.assertEqual((tat["bat"], tat["bieu_thuc"], tat["nhan"]), (False, "30 2 * * *", "sao luu CSDL + kho"))
        self.assertIsNone(lich_chay.phan_tich_dong("0 4 * * 0 /home/pc/viec-rieng.sh"))
        self.assertIsNone(lich_chay.phan_tich_dong("# hds-ai: chỉ là chú thích"))
        self.assertIsNone(lich_chay.phan_tich_dong("# */3 * * * * x  # hds-ai: tắt tay kiểu khác"))
        self.assertIsNone(lich_chay.phan_tich_dong(""))

    def test_doi_dong_chi_them_bo_tien_to(self):
        goc = CRON.splitlines()[3]
        tat = lich_chay.doi_dong(goc, False)
        self.assertEqual(tat, "#TAT# " + goc)
        self.assertEqual(lich_chay.doi_dong(tat, True), goc)
        self.assertEqual(lich_chay.doi_dong(tat, False), tat)       # tắt lần nữa không chồng tiền tố
        self.assertEqual(lich_chay.doi_dong(goc, True), goc)

    def test_mo_ta_lich(self):
        self.assertEqual(lich_chay.mo_ta_lich("*/3 * * * *"), "Mỗi 3 phút")
        self.assertEqual(lich_chay.mo_ta_lich("7 * * * *"), "Mỗi giờ, phút 07")
        self.assertEqual(lich_chay.mo_ta_lich("30 2 * * *"), "Hằng ngày lúc 02:30")
        self.assertEqual(lich_chay.mo_ta_lich("0 4 * * 0"), "0 4 * * 0")

    def test_lan_ke_tiep(self):
        t = datetime(2026, 10, 1, 10, 58, 30)
        self.assertEqual(lich_chay.lan_ke_tiep("*/3 * * * *", t), datetime(2026, 10, 1, 11, 0))
        self.assertEqual(lich_chay.lan_ke_tiep("7 * * * *", t), datetime(2026, 10, 1, 11, 7))
        self.assertEqual(lich_chay.lan_ke_tiep("37 * * * *", datetime(2026, 10, 1, 10, 20)),
                         datetime(2026, 10, 1, 10, 37))
        self.assertEqual(lich_chay.lan_ke_tiep("30 2 * * *", t), datetime(2026, 10, 2, 2, 30))
        self.assertEqual(lich_chay.lan_ke_tiep("30 2 * * *", datetime(2026, 10, 1, 1, 0)),
                         datetime(2026, 10, 1, 2, 30))
        self.assertIsNone(lich_chay.lan_ke_tiep("0 4 * * 0", t))

    def test_dong_cuoi_nhat_ky(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.log"
            p.write_text("dòng 1\ndòng 2\n\n", encoding="utf-8")
            self.assertEqual(lich_chay.dong_cuoi(p), "dòng 2")
            self.assertIsNone(lich_chay.dong_cuoi(Path(d) / "khong-co.log"))

    def test_moi_lich_da_biet_co_ma_va_ten(self):
        ma = [v["ma"] for v in lich_chay.LICH.values()]
        self.assertEqual(len(ma), len(set(ma)))
        for v in lich_chay.LICH.values():
            if v.get("cai"):
                d = lich_chay.phan_tich_dong(v["cai"].format(repo="/r"))
                self.assertIsNotNone(d, v["ma"])
                self.assertEqual(lich_chay._chuan(d["nhan"]), [k for k, x in lich_chay.LICH.items() if x is v][0])


class BatTat(unittest.TestCase):
    def setUp(self):
        self.cron = {"v": CRON}
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [
            mock.patch.object(lich_chay, "doc_crontab", lambda: self.cron["v"]),
            mock.patch.object(lich_chay, "ghi_crontab", lambda s: self.cron.__setitem__("v", s + "\n")),
            mock.patch.object(lich_chay, "dang_chay", lambda mau: False),
            mock.patch.object(lich_chay, "_DATA", Path(self.tmp.name)),
            mock.patch.object(lich_chay, "_audit", lambda *a, **k: None),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_danh_sach_gom_lich_thieu(self):
        ds = {x["ma"]: x for x in lich_chay.danh_sach(datetime(2026, 10, 1, 10, 0))}
        self.assertEqual(ds["quet-kho"]["trang_thai"], "bat")
        self.assertEqual(ds["quet-kho"]["lich_mo_ta"], "Mỗi 3 phút")
        self.assertEqual(ds["quet-kho"]["ke_tiep"], "2026-10-01T10:03")
        # Sao lưu KHÔNG có trong crontab → hiện "chưa cài", cài lại được
        self.assertEqual((ds["sao-luu"]["trang_thai"], ds["sao-luu"]["cai_duoc"]), ("chua_cai", True))
        self.assertEqual(ds["sao-luu"]["lich_mo_ta"], "Hằng ngày lúc 02:30")
        # Dòng không có nhãn hds-ai không hiện
        self.assertEqual(len(ds), 5)

    def test_tat_roi_bat_chi_dung_dong_do(self):
        truoc = self.cron["v"].splitlines()
        kq = lich_chay.dat("tu-duyet", False)
        self.assertEqual(kq["trang_thai"], "tat")
        self.assertIsNone(kq["ke_tiep"])
        sau = self.cron["v"].splitlines()
        khac = [(a, b) for a, b in zip(truoc, sau) if a != b]
        self.assertEqual(len(khac), 1)
        self.assertEqual(khac[0][1], "#TAT# " + khac[0][0])
        self.assertEqual(sau[-1], "0 4 * * 0 /home/pc/viec-rieng.sh")      # dòng lạ giữ nguyên
        kq = lich_chay.dat("tu-duyet", True)
        self.assertEqual(kq["trang_thai"], "bat")
        self.assertEqual(self.cron["v"].splitlines(), truoc)

    def test_dat_trang_thai_da_co_khong_ghi_lai(self):
        with mock.patch.object(lich_chay, "ghi_crontab", side_effect=AssertionError("không được ghi")):
            self.assertEqual(lich_chay.dat("quet-kho", True)["trang_thai"], "bat")

    def test_lich_khong_co(self):
        with self.assertRaises(lich_chay.LoiLich) as c:
            lich_chay.dat("sao-luu", True)
        self.assertEqual(c.exception.status, 404)
        self.assertIn("Cài lại", str(c.exception))
        with self.assertRaises(lich_chay.LoiLich):
            lich_chay.dat("khong-ton-tai", False)

    def test_cai_lai(self):
        kq = lich_chay.cai_lai("sao-luu")
        self.assertEqual(kq["trang_thai"], "bat")
        self.assertIn("sao-luu.sh' --cron  # hds-ai: sao luu CSDL + kho", self.cron["v"])
        self.assertTrue(self.cron["v"].startswith("# m h"))                  # phần cũ giữ nguyên
        with self.assertRaises(lich_chay.LoiLich) as c:
            lich_chay.cai_lai("sao-luu")
        self.assertEqual(c.exception.status, 409)
        with self.assertRaises(lich_chay.LoiLich):
            lich_chay.cai_lai("tu-duyet")          # script ngoài git — không cài từ web

    def test_nhat_ky_lan_cuoi(self):
        (Path(self.tmp.name) / "quet_kho_lich_su.log").write_text(
            "2026-10-01 02:21:01 → 02:21:11 rc=0 0 mới\n", encoding="utf-8")
        ds = {x["ma"]: x for x in lich_chay.danh_sach()}
        self.assertTrue(ds["quet-kho"]["ket_qua_cuoi"].startswith("2026-10-01 02:21:01"))
        self.assertIsNotNone(ds["quet-kho"]["lan_cuoi"])
        self.assertIsNone(ds["hieu-luc"]["lan_cuoi"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
