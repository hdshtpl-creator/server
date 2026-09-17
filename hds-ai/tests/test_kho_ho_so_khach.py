"""Thư mục hồ sơ khách nhìn từ phía đĩa (app/kho.py, 18/09/2026) — phần THUẦN.

Vì sao có nó: tab Hồ sơ khách 360° chỉ thấy khách đã có tài liệu học xong;
1.230/1.571 thư mục khách trống hoặc chỉ chứa zip không hiện ở đâu. Màn hình
mới phải liệt kê MỌI thư mục khách kể cả trống, đếm đúng nhãn từng tệp, lọc
và tìm đúng, và không cho mở thư mục ngoài ngăn khách.
Không chạm CSDL: bản đồ nhãn, bảng khách và hai truy vấn tài liệu/lỗi đều vá.
"""
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from app import kho

GOC = "9. HỒ SƠ KHÁCH HÀNG"
BAN_DO = ({"tong hop thong tin khach hang": {"doc_type": "ho_so_kh"}}, {}, {"ho so khach hang"})
KHACH = {"1000": (7, "Anh A (đã có trong hệ thống)")}
BAN_GHI = {
    f"local:{GOC}/1000. Anh A/2. Dự án/896. Thành lập/x.pdf": {
        "id": 11, "title": "Điều lệ", "doc_type": "filing", "access_level": "client",
        "approved": True, "label_verified": True, "extraction_status": "ready",
        "so_hieu": None, "checksum": "a", "client_name": "Anh A", "active": True,
        "so_doan": 5, "created_at": None},
    f"local:{GOC}/1000. Anh A/1. Thông tin/y.docx": {
        "id": 12, "title": "CCCD", "doc_type": "ho_so_kh", "access_level": "client",
        "approved": False, "label_verified": False, "extraction_status": "ready",
        "so_hieu": None, "checksum": "b", "client_name": "Anh A", "active": True,
        "so_doan": 1, "created_at": None},
}
LOI = {f"local:{GOC}/1003. Lỗi/l.pdf": {"code": "no_text", "message": "Không có chữ",
                                        "hint": "Scan lại"}}


class ThuMucKhach(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        for rel in (f"{GOC}/1000. Anh A/2. Dự án/896. Thành lập/x.pdf",
                    f"{GOC}/1000. Anh A/1. Thông tin/y.docx",
                    f"{GOC}/1000. Anh A/Thumbs.db",
                    f"{GOC}/1002. Chỉ zip/a.zip",
                    f"{GOC}/1003. Lỗi/l.pdf",
                    f"{GOC}/1004. Chưa học/c.pdf",
                    f"{GOC}/Không mã/z.pdf",
                    f"{GOC}/1. Tổng hợp thông tin khách hàng/t.pdf",
                    f"{GOC}/9. Khách đời đầu/d.docx",
                    "2. BẢN ÁN/2026/b.pdf", "uploads/u.pdf"):
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"x")
        # Trống hẳn, và trống nhưng có khung thư mục con (export Drive hay tạo vậy)
        (self.root / GOC / "1001. Trống").mkdir()
        (self.root / GOC / "1005. Chỉ khung" / "1. Thông tin").mkdir(parents=True)
        (self.root / GOC / "1005. Chỉ khung" / "2. Dự án").mkdir(parents=True)
        kho.quen_dem()
        self.patches = [
            unittest.mock.patch.object(kho, "library_root", lambda: self.root),
            unittest.mock.patch.object(kho, "_ban_do_nhan", lambda: BAN_DO),
            unittest.mock.patch.object(kho, "_khach_theo_ma", lambda: dict(KHACH)),
            unittest.mock.patch.object(kho, "_tai_lieu_theo_khoa",
                                       lambda keys: {k: BAN_GHI[k] for k in keys if k in BAN_GHI}),
            unittest.mock.patch.object(kho, "_loi_theo_khoa",
                                       lambda keys: {k: LOI[k] for k in keys if k in LOI}),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        kho.quen_dem()
        self.tmp.cleanup()

    def test_moi_thu_muc_mot_dong_ke_ca_trong_xep_theo_ma_so(self):
        ds = kho.danh_sach_thu_muc_khach()
        self.assertEqual(ds["goc"], [GOC])
        self.assertEqual([d["ten"] for d in ds["thu_muc"]],
                         ["1. Tổng hợp thông tin khách hàng", "9. Khách đời đầu",
                          "1000. Anh A", "1001. Trống", "1002. Chỉ zip", "1003. Lỗi",
                          "1004. Chưa học", "1005. Chỉ khung", "Không mã"])
        self.assertEqual(ds["tong_khop"], 9)
        tong = ds["tong"]
        self.assertEqual(tong["tong_thu_muc"], 9)
        self.assertEqual(tong["tong_tep"], 8)            # Thumbs.db không tính
        self.assertEqual(tong["theo_tinh_trang"],
                         {"trong": 2, "bo_qua": 2, "khong_doc_duoc": 2, "chua_hoc": 2,
                          "cho_duyet": 0, "mot_phan": 1, "da_hoc": 0})
        self.assertEqual(tong["dem"], {"da_hoc": 1, "canh_bao": 0, "cho_duyet": 1,
                                       "chua_hoc": 4, "loi": 1, "khong_ho_tro": 1})

    def test_tung_dong(self):
        theo_ten = {d["ten"]: d for d in kho.danh_sach_thu_muc_khach()["thu_muc"]}
        a = theo_ten["1000. Anh A"]
        self.assertEqual((a["ma"], a["ten_khach"], a["client_id"]), ("1000", "Anh A", 7))
        self.assertEqual(a["path"], f"{GOC}/1000. Anh A")
        self.assertEqual(a["so_file"], 2)
        self.assertEqual((a["dem"]["da_hoc"], a["dem"]["cho_duyet"]), (1, 1))
        self.assertEqual(a["tinh_trang"], "mot_phan")
        self.assertIsNone(a["ly_do"])

        self.assertEqual(theo_ten["1001. Trống"]["tinh_trang"], "trong")
        self.assertEqual(theo_ten["1005. Chỉ khung"]["tinh_trang"], "trong")
        self.assertEqual(theo_ten["1002. Chỉ zip"]["tinh_trang"], "khong_doc_duoc")
        self.assertEqual(theo_ten["1002. Chỉ zip"]["dem"]["khong_ho_tro"], 1)
        self.assertEqual(theo_ten["1003. Lỗi"]["tinh_trang"], "khong_doc_duoc")
        self.assertEqual(theo_ten["1003. Lỗi"]["dem"]["loi"], 1)
        self.assertEqual(theo_ten["1004. Chưa học"]["tinh_trang"], "chua_hoc")
        # Khách chưa có trong hệ thống: mã tách được nhưng client_id trống
        self.assertEqual((theo_ten["1004. Chưa học"]["ma"], theo_ten["1004. Chưa học"]["client_id"]),
                         ("1004", None))
        # Bộ quét bỏ qua: không mã, và mã 1 chữ số trùng tên một loại giấy tờ
        km = theo_ten["Không mã"]
        self.assertEqual(km["tinh_trang"], "bo_qua")
        self.assertIsNone(km["ma"])
        self.assertIn("Chưa tách được mã khách", km["ly_do"])
        th = theo_ten["1. Tổng hợp thông tin khách hàng"]
        self.assertEqual(th["tinh_trang"], "bo_qua")
        self.assertIn("ngăn con đặt nhầm", th["ly_do"])
        # Mã 1 chữ số nhưng tên KHÔNG trùng ngăn con là khách thật
        self.assertEqual(theo_ten["9. Khách đời đầu"]["tinh_trang"], "chua_hoc")

    def test_loc_tim_va_phan_trang(self):
        ten = lambda **kw: [d["ten"] for d in kho.danh_sach_thu_muc_khach(**kw)["thu_muc"]]
        self.assertEqual(ten(loc="trong"), ["1001. Trống", "1005. Chỉ khung"])
        self.assertEqual(ten(loc="bo_qua"), ["1. Tổng hợp thông tin khách hàng", "Không mã"])
        self.assertEqual(ten(loc="co_tep"),
                         ["1. Tổng hợp thông tin khách hàng", "9. Khách đời đầu", "1000. Anh A",
                          "1002. Chỉ zip", "1003. Lỗi", "1004. Chưa học", "Không mã"])
        self.assertEqual(len(ten(loc="can_xu_ly")), 7)
        # Tìm không dấu, theo tên thư mục hoặc tên khách trong hệ thống
        self.assertEqual(ten(q="anh a"), ["1000. Anh A"])
        self.assertEqual(ten(q="1002"), ["1002. Chỉ zip"])
        self.assertEqual(ten(q="he thong"), ["1000. Anh A"])
        self.assertEqual(ten(q="chi KHUNG"), ["1005. Chỉ khung"])
        self.assertEqual(ten(q="khong co"), [])
        # Phân trang không làm lệch tổng
        ds = kho.danh_sach_thu_muc_khach(offset=2, limit=3)
        self.assertEqual([d["ten"] for d in ds["thu_muc"]],
                         ["1000. Anh A", "1001. Trống", "1002. Chỉ zip"])
        self.assertEqual((ds["tong_khop"], ds["tong"]["tong_thu_muc"]), (9, 9))
        with self.assertRaises(kho.LoiKho):
            kho.danh_sach_thu_muc_khach(loc="bay")

    def test_tep_cua_mot_khach(self):
        ct = kho.tep_trong_thu_muc_khach(f"{GOC}/1000. Anh A")
        self.assertEqual((ct["ten"], ct["ma"], ct["client_id"], ct["so_file"]),
                         ("1000. Anh A", "1000", 7, 2))
        self.assertEqual(ct["so_thu_muc_con"], 3)
        self.assertEqual([(t["ten"], t["thu_muc_con"], t["trang_thai"]) for t in ct["tap_tin"]],
                         [("y.docx", "1. Thông tin", "cho_duyet"),
                          ("x.pdf", "2. Dự án/896. Thành lập", "da_hoc")])
        x = ct["tap_tin"][1]
        self.assertEqual((x["document_id"], x["title"], x["path"]),
                         (11, "Điều lệ", f"{GOC}/1000. Anh A/2. Dự án/896. Thành lập/x.pdf"))
        loi = kho.tep_trong_thu_muc_khach(f"{GOC}/1003. Lỗi")["tap_tin"][0]
        self.assertEqual((loi["trang_thai"], loi["loi"]["code"]), ("loi", "no_text"))
        trong = kho.tep_trong_thu_muc_khach(f"{GOC}/1005. Chỉ khung")
        self.assertEqual((trong["tap_tin"], trong["so_thu_muc_con"], trong["tinh_trang"]),
                         ([], 2, "trong"))

    def test_chi_mo_thu_muc_ngay_duoi_ngan_khach(self):
        for rel in (GOC, f"{GOC}/1000. Anh A/2. Dự án", "2. BẢN ÁN/2026", "2. BẢN ÁN",
                    f"{GOC}/khong-co", "../", "uploads"):
            with self.subTest(rel=rel):
                with self.assertRaises(kho.LoiKho):
                    kho.tep_trong_thu_muc_khach(rel)

    def test_nho_2_phut_va_quen_khi_hoc(self):
        kho.danh_sach_thu_muc_khach()
        (self.root / GOC / "1001. Trống" / "moi.pdf").write_bytes(b"x")
        self.assertEqual(kho.danh_sach_thu_muc_khach(q="1001")["thu_muc"][0]["so_file"], 0)
        kho.quen_dem()
        self.assertEqual(kho.danh_sach_thu_muc_khach(q="1001")["thu_muc"][0]["so_file"], 1)


class TinhTrang(unittest.TestCase):
    def dem(self, **kw):
        d = {k: 0 for k in kho.TRANG_THAI_DEM}
        d.update(kw)
        return d

    def test_bang_quyet_dinh(self):
        tt = kho.tinh_trang_thu_muc
        self.assertEqual(tt(0, self.dem(), None), "trong")
        self.assertEqual(tt(3, self.dem(chua_hoc=3), "lý do"), "bo_qua")
        self.assertEqual(tt(2, self.dem(khong_ho_tro=2), None), "khong_doc_duoc")
        self.assertEqual(tt(3, self.dem(khong_ho_tro=1, loi=2), None), "khong_doc_duoc")
        self.assertEqual(tt(3, self.dem(da_hoc=2, canh_bao=1), None), "da_hoc")
        self.assertEqual(tt(3, self.dem(da_hoc=2, khong_ho_tro=1), None), "da_hoc")
        self.assertEqual(tt(3, self.dem(da_hoc=1, cho_duyet=2), None), "mot_phan")
        self.assertEqual(tt(3, self.dem(da_hoc=1, loi=2), None), "mot_phan")
        self.assertEqual(tt(3, self.dem(cho_duyet=1, chua_hoc=2), None), "cho_duyet")
        self.assertEqual(tt(3, self.dem(chua_hoc=2, loi=1), None), "chua_hoc")

    def test_ly_do_thu_muc(self):
        ld = lambda ten: kho.ly_do_thu_muc_khach(ten, BAN_DO)
        self.assertEqual(ld("1729. Công ty Cổ phần Đại Hữu")[:2], ("1729", "Công ty Cổ phần Đại Hữu"))
        self.assertIsNone(ld("1729. Công ty Cổ phần Đại Hữu")[2])
        self.assertEqual(ld("[SUNGROUP] Tập đoàn Sun")[:2], ("SUNGROUP", "Tập đoàn Sun"))
        self.assertEqual(ld("1043.Chị Trang Gola")[:2], ("1043", "Chị Trang Gola"))
        self.assertIsNotNone(ld("Nguyễn Văn A")[2])
        self.assertIsNotNone(ld("1. Tổng hợp thông tin khách hàng")[2])
        self.assertIsNone(ld("9. CHI NHÁNH DFK")[2])


if __name__ == "__main__":
    unittest.main()
