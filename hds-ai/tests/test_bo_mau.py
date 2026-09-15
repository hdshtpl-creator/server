"""
Test BỘ MẪU HỒ SƠ + tạo bộ file từ chat thường (15/09/2026) — phần THUẦN,
không cần PostgreSQL/Ollama.

Chay: python -m unittest tests.test_bo_mau -v

Ba thứ phải đứng vững:
  1. Lệnh "tạo bộ hồ sơ / các file …" trong chat thường được nhận ra, còn câu
     HỎI cách làm và lệnh soạn MỘT giấy tờ (chat_draft) thì KHÔNG bị nuốt.
  2. Gọi tên bộ mẫu trong câu → khớp đúng bộ (bỏ dấu, tên dài thắng tên ngắn).
  3. Kế hoạch từ bộ mẫu là TẤT ĐỊNH (mỗi file mẫu một file điền), không trần
     mặc định; dữ liệu hội thoại vào prompt và giữ lượt gần nhất khi vượt
     ngân sách; gói .zip cả bộ tải được qua find_fill_file.
"""
import io
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from app import bo_mau, chat_draft, doc_factory as df, template_fill as tf


class DetectRequestTests(unittest.TestCase):
    def test_lenh_tao_bo_ho_so(self):
        for q in [
            "Tạo bộ hồ sơ theo bộ mẫu Thuê nhà cho khách Minh",
            "tạo giúp tôi các file hợp đồng cho khách vừa trao đổi",
            "làm bộ file cho khách Nguyễn Văn A với thông tin ở trên",
            "Điền thông tin khách vào bộ mẫu HĐ dịch vụ",
            "hãy tạo file hợp đồng với thông tin khách từ lịch sử chat",
            "xuất hồ sơ cho khách này",
            "Tạo trọn bộ hợp đồng từ file tổng hợp đính kèm",
        ]:
            with self.subTest(q=q):
                self.assertIsNotNone(df.detect_request(q))

    def test_nhac_bo_mau(self):
        self.assertTrue(df.detect_request("tạo bộ hồ sơ theo bộ mẫu X")["nhac_bo_mau"])
        self.assertFalse(df.detect_request("tạo bộ hồ sơ cho khách A")["nhac_bo_mau"])

    def test_cau_hoi_cach_lam_khong_phai_lenh(self):
        for q in [
            "tạo bộ hồ sơ như thế nào?",
            "làm sao để tạo file hợp đồng",
            "tạo bộ hồ sơ thành lập công ty cần những gì?",
            "hồ sơ khởi kiện gồm những file nào",
            "bộ mẫu là gì",
        ]:
            with self.subTest(q=q):
                self.assertIsNone(df.detect_request(q))

    def test_file_ky_thuat_khong_phai_lenh(self):
        self.assertIsNone(df.detect_request("tạo file excel danh sách khách"))
        self.assertIsNone(df.detect_request("tạo file pdf từ hợp đồng này"))

    def test_cau_thuong_khong_phai_lenh(self):
        for q in [
            "thời hiệu khởi kiện tranh chấp hợp đồng là bao lâu",
            "tóm tắt file đính kèm",
            "khách Minh có bao nhiêu vụ việc",
        ]:
            with self.subTest(q=q):
                self.assertIsNone(df.detect_request(q))

    def test_khong_giao_voi_chat_draft(self):
        """Lệnh soạn MỘT giấy tờ đi luồng bản nháp; lệnh bộ file đi doc_factory.
        Hai bộ nhận diện không được cùng bắt một câu."""
        mot_giay = [
            "tạo hợp đồng lao động cho Ngân như của Nhi",
            "soạn đơn kháng cáo bản án sơ thẩm số 12/2026",
            "tạo quyết định bổ nhiệm cho Mai",
        ]
        for q in mot_giay:
            with self.subTest(q=q):
                self.assertIsNotNone(chat_draft.detect_request(q))
                self.assertIsNone(df.detect_request(q))
        bo_file = [
            "tạo bộ hồ sơ theo bộ mẫu Thuê nhà cho khách Minh",
            "tạo các file cho khách Minh",
        ]
        for q in bo_file:
            with self.subTest(q=q):
                self.assertIsNotNone(df.detect_request(q))
                self.assertIsNone(chat_draft.detect_request(q))


class MatchSetTests(unittest.TestCase):
    SETS = [
        {"id": 1, "ten": "HĐ thuê nhà", "so_file": 3},
        {"id": 2, "ten": "HĐ thuê nhà + phụ lục", "so_file": 5},
        {"id": 3, "ten": "Thành lập công ty", "so_file": 7},
    ]

    def test_khop_bo_dau_va_hoa_thuong(self):
        bo = bo_mau.match_set("tạo bộ hồ sơ THANH LAP CONG TY cho khách A", self.SETS)
        self.assertEqual(bo["id"], 3)

    def test_ten_dai_thang_ten_ngan(self):
        bo = bo_mau.match_set("điền bộ mẫu «HĐ thuê nhà + phụ lục» cho Minh", self.SETS)
        self.assertEqual(bo["id"], 2)

    def test_khong_khop(self):
        self.assertIsNone(bo_mau.match_set("tạo bộ hồ sơ theo bộ mẫu Ly hôn", self.SETS))
        self.assertIsNone(bo_mau.match_set("", self.SETS))
        self.assertIsNone(bo_mau.match_set("tạo bộ hồ sơ", []))

    def test_nhac_bo_mau(self):
        self.assertTrue(bo_mau.nhac_bo_mau("theo BỘ MẪU thuê nhà"))
        self.assertFalse(bo_mau.nhac_bo_mau("tạo bộ hồ sơ cho khách"))


class PlanTuBoMauTests(unittest.TestCase):
    BO = {"id": 9, "ten": "HĐ thuê nhà", "files": [
        {"id": 11, "ten_file": "01 Hop dong thue nha.docx", "duong_dan": "x/a.docx"},
        {"id": 12, "ten_file": "02 Phu luc 1.docx", "duong_dan": "x/b.docx"},
        {"id": 13, "ten_file": "03 Bien ban ban giao.docx", "duong_dan": "x/c.docx"},
    ]}

    def test_moi_file_mau_mot_file_dien_giu_thu_tu(self):
        plan = df.plan_tu_bo_mau(self.BO)
        self.assertEqual([p["ten_file"] for p in plan],
                         ["01 Hop dong thue nha", "02 Phu luc 1", "03 Bien ban ban giao"])
        self.assertEqual(plan[0]["khuon"], "bo_mau:11")
        self.assertEqual(plan[0]["duong_dan"], "x/a.docx")

    def test_thu_hep_theo_file_ids(self):
        plan = df.plan_tu_bo_mau(self.BO, file_ids=[13, 11])
        self.assertEqual([p["khuon"] for p in plan], ["bo_mau:11", "bo_mau:13"])

    def test_tran_admin(self):
        self.assertEqual(len(df.plan_tu_bo_mau(self.BO, max_files=2)), 2)
        self.assertEqual(len(df.plan_tu_bo_mau(self.BO, max_files=0)), 3)


class HistoryBlockTests(unittest.TestCase):
    def test_co_tom_tat_va_luot(self):
        block = df.build_history_block(
            "Khách Minh thuê nhà 12 Lê Lợi, 15 triệu/tháng.",
            [("user", "khách tên Nguyễn Văn Minh, CCCD 0123"),
             ("assistant", "Đã ghi nhận."),
             ("user", "  tạo bộ hồ sơ  ")])
        self.assertIn("TÓM TẮT PHẦN ĐẦU", block)
        self.assertIn("12 Lê Lợi", block)
        self.assertIn("- Người dùng: khách tên Nguyễn Văn Minh, CCCD 0123", block)
        self.assertIn("- Trợ lý: Đã ghi nhận.", block)

    def test_vuot_ngan_sach_giu_luot_gan_nhat(self):
        history = [("user", f"lượt {i} " + "x" * 300) for i in range(50)]
        block = df.build_history_block("", history, budget=1_000)
        self.assertIn("lượt 49", block)
        self.assertNotIn("lượt 0 ", block)

    def test_rong(self):
        self.assertEqual(df.build_history_block("", []), "")
        self.assertEqual(df.build_history_block(None, None), "")

    def test_vung_tin_cay_chi_lay_nguoi_dung(self):
        text = df.user_history_text([("user", "MST 0101"), ("assistant", "MST 0999")])
        self.assertIn("0101", text)
        self.assertNotIn("0999", text)


class PromptHoiThoaiTests(unittest.TestCase):
    def test_plan_prompt_co_du_lieu_hoi_thoai_va_khong_tran(self):
        prompt, _ = df.build_plan_prompt("tạo các file", [], None,
                                         du_lieu_hoi_thoai="- Người dùng: khách Minh",
                                         max_files=0)
        self.assertIn("DỮ LIỆU TỪ HỘI THOẠI", prompt)
        self.assertIn("khách Minh", prompt)
        self.assertNotIn("Tối đa", prompt)
        self.assertIn("Tạo ĐỦ số file", prompt)

    def test_plan_prompt_co_tran_khi_admin_dat(self):
        prompt, _ = df.build_plan_prompt("tạo các file", [], None, max_files=5)
        self.assertIn("Tối đa 5 file", prompt)

    def test_draft_prompt_co_du_lieu_hoi_thoai(self):
        prompt, _ = df.build_draft_prompt("BBNT", "", "nghiệm thu", [], "",
                                          du_lieu_hoi_thoai="- Người dùng: số HĐ 05")
        self.assertIn("DỮ LIỆU TỪ HỘI THOẠI", prompt)
        self.assertIn("số HĐ 05", prompt)


class ZipBundleTests(unittest.TestCase):
    def test_goi_zip_va_tim_lai_duoc(self):
        with tempfile.TemporaryDirectory() as d:
            old_work = tf.DATA_WORK
            tf.DATA_WORK = Path(d)
            try:
                a = Path(d) / "a.docx"
                b = Path(d) / "b.docx"
                a.write_bytes(b"AAA")
                b.write_bytes(b"BBB")
                payload = df.bundle_zip([("HD.docx", a), ("HD.docx", b)])
                names = zipfile.ZipFile(io.BytesIO(payload)).namelist()
                self.assertEqual(names, ["HD.docx", "HD (2).docx"])
                token, out = tf.save_filled_bytes(payload, "bo thue nha", extension="zip")
                self.assertTrue(out.name.endswith(".zip"))
                found = tf.find_fill_file(token)
                self.assertEqual(found, out.resolve())
            finally:
                tf.DATA_WORK = old_work

    def test_duoi_la_bi_chan(self):
        with self.assertRaises(ValueError):
            tf.save_filled_bytes(b"x", "a", extension="exe")


class ResolvePathTests(unittest.TestCase):
    def test_khong_cho_ra_ngoai_thu_muc_bo_mau(self):
        with tempfile.TemporaryDirectory() as d:
            old = bo_mau.DATA_WORK
            bo_mau.DATA_WORK = Path(d)
            try:
                goc = bo_mau.goc_bo_mau()
                (goc / "1").mkdir(parents=True)
                ok = goc / "1" / "x.docx"
                ok.write_bytes(b"x")
                self.assertEqual(bo_mau.resolve_path(str(ok)), ok.resolve())
                ngoai = Path(d) / "ngoai.docx"
                ngoai.write_bytes(b"x")
                with self.assertRaises(ValueError):
                    bo_mau.resolve_path(str(ngoai))
                with self.assertRaises(ValueError):
                    bo_mau.resolve_path(str(goc / "1" / ".." / ".." / "ngoai.docx"))
            finally:
                bo_mau.DATA_WORK = old

    def test_ten_file_an_toan(self):
        self.assertEqual(bo_mau.safe_name("../../etc/passwd.docx"), "passwd.docx")
        self.assertTrue(bo_mau.safe_name("Hợp đồng (bản 2).docx").endswith(".docx"))


if __name__ == "__main__":
    unittest.main()
