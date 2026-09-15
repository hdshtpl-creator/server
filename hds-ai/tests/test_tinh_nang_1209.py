"""Tính năng bổ sung 12/09/2026 theo phản hồi nhân viên — test thuần logic.

- Khung LÀM RÕ DỮ KIỆN cho câu hỏi tình huống (Loan 28/08).
- Khung ĐÁNH GIÁ NHÃN HIỆU (Nhi 29/08).
- Soạn văn bản tố tụng / đơn từ / công văn từ chat không cần "cho <tên>" (Huế, Nhi).
- Chế độ template_check: mẫu công ty vào nguồn, prompt rà soát riêng (Nhi).
"""
import unittest

from app import chat_draft, rag, settings


class KhungLamRo(unittest.TestCase):
    TINH_HUONG = ("Công ty TNHH 2 thành viên thành lập ngày 01/01/2026. Một thành viên cam kết "
                  "góp vốn bằng quyền sử dụng đất nhưng đến ngày 10/04/2026 chưa hoàn tất thủ "
                  "tục chuyển quyền sở hữu. Xác định hậu quả pháp lý về tư cách thành viên và "
                  "nghĩa vụ điều chỉnh vốn điều lệ của công ty.")

    def test_tinh_huong_dai_co_khung(self):
        self.assertTrue(rag._yeu_cau_lam_ro(self.TINH_HUONG))
        p = rag.build_prompt(self.TINH_HUONG, [], chunk_chars=0, budget=0)
        self.assertIn("LÀM RÕ DỮ KIỆN", p)
        self.assertIn("Không cần làm rõ thêm", p)

    def test_cau_ngan_khong_hoi_lai(self):
        for cau in ("Thời hiệu khởi kiện tranh chấp hợp đồng thương mại là bao lâu?",
                    "Mức phạt vi phạm tối đa theo Luật Thương mại?"):
            with self.subTest(cau=cau):
                self.assertFalse(rag._yeu_cau_lam_ro(cau))
                self.assertNotIn("LÀM RÕ DỮ KIỆN",
                                 rag.build_prompt(cau, [], chunk_chars=0, budget=0))

    def test_cau_dai_khong_phap_ly_khong_hoi(self):
        cau = " ".join(["tóm tắt biên bản họp tuần trước về kế hoạch tổ chức tiệc cuối năm"] * 4)
        self.assertFalse(rag._yeu_cau_lam_ro(cau))


class KhungNhanHieu(unittest.TestCase):
    def test_nhan_ra_cau_danh_gia(self):
        for cau in ("Đánh giá khả năng bảo hộ của nhãn hiệu SUNRISE cho nhóm 30",
                    "Nhãn hiệu LAVIE và LA VIE có tương tự gây nhầm lẫn không?",
                    "Thẩm định nhãn hiệu chữ GOLDEN SEA so với nhãn đối chứng GOLDEN SEE",
                    "Logo này có khả năng phân biệt để đăng ký làm nhãn hiệu không"):
            with self.subTest(cau=cau):
                self.assertTrue(rag._yeu_cau_nhan_hieu(cau))

    def test_khong_phai_danh_gia(self):
        for cau in ("Thủ tục gia hạn văn bằng bảo hộ nhãn hiệu gồm những gì?",
                    "Thời hiệu khởi kiện tranh chấp hợp đồng là bao lâu?",
                    "Đánh giá rủi ro khi chuyển nhượng dự án đầu tư"):
            with self.subTest(cau=cau):
                self.assertFalse(rag._yeu_cau_nhan_hieu(cau))

    def test_prompt_co_thang_ba_muc(self):
        p = rag.build_prompt("Đánh giá khả năng bảo hộ của nhãn hiệu SUNRISE cho nhóm 30",
                             [], chunk_chars=0, budget=0)
        self.assertIn("ĐÁNH GIÁ NHÃN HIỆU", p)
        for muc in ("Khả năng bảo hộ cao", "Có rủi ro, cần lập luận thêm",
                    "Khả năng bị từ chối cao"):
            self.assertIn(muc, p)
        self.assertIn("KHÔNG mặc định kết luận từ chối", p)
        self.assertIn("không lặp một công thức chung", p)


class SoanVanBanTuDo(unittest.TestCase):
    def test_don_khang_cao_khong_can_ten(self):
        q = ("Soạn đơn kháng cáo bản án sơ thẩm số 12/2026/KDTM-ST vì Toà không triệu tập "
             "bên bảo lãnh thanh toán tham gia phiên toà")
        r = chat_draft.detect_request(q)
        self.assertIsNotNone(r)
        self.assertEqual(r["kind"], "don khang cao")
        self.assertTrue(r["tu_do"])
        self.assertIsNone(r["for_name"])
        self.assertIn("12/2026/KDTM-ST", r["boi_canh"])
        # Tên bản nháp không lặp lại lệnh: bối cảnh ngắn bắt đầu ngay sau "đơn kháng cáo".
        self.assertTrue(r["boi_canh_ngan"].startswith("bản án sơ thẩm"), r["boi_canh_ngan"])
        self.assertEqual(chat_draft._bo_cum_lenh("soan don khang cao khong dau", "đơn kháng cáo"),
                         "soan don khang cao khong dau")

    def test_cac_loai_moi(self):
        for q, kind in (("Hãy viết công văn gửi Sở Tài chính đề nghị hướng dẫn hồ sơ", "cong van"),
                        ("soạn bản tự khai cho vụ tranh chấp hợp đồng vay", "ban tu khai"),
                        ("Dự thảo đơn phản đối cấp văn bằng nhãn hiệu số 4-2026-01234", "don phan doi"),
                        ("viết đơn khởi kiện đòi nợ 5 tỷ đồng theo hợp đồng mua bán", "don khoi kien"),
                        ("tạo bản luận cứ bảo vệ bị đơn trong vụ án KDTM", "ban luan cu")):
            with self.subTest(q=q):
                r = chat_draft.detect_request(q)
                self.assertIsNotNone(r, q)
                self.assertEqual(r["kind"], kind)
                self.assertTrue(r.get("tu_do"))

    def test_cau_hoi_cach_soan_khong_bi_nuot(self):
        for q in ("Soạn đơn kháng cáo cần những nội dung gì?",
                  "đơn khởi kiện gồm những mục nào",
                  "Hướng dẫn cách soạn công văn",
                  "Soạn đơn khởi kiện có cần công chứng không"):
            with self.subTest(q=q):
                self.assertIsNone(chat_draft.detect_request(q))

    def test_khuon_cu_van_nguyen(self):
        r = chat_draft.detect_request("tạo hợp đồng lao động cho Nguyễn Văn An")
        self.assertIsNotNone(r)
        self.assertEqual(r["kind"], "hop dong lao dong")
        self.assertFalse(r.get("tu_do"))
        # Hợp đồng lao động không có vế "cho ai" thì vẫn KHÔNG là lệnh soạn.
        self.assertIsNone(chat_draft.detect_request("soạn hợp đồng lao động"))

    def test_khung_muc_bat_buoc(self):
        muc = chat_draft.muc_bat_buoc("don khang cao")
        for ten in ("Người kháng cáo", "Bản án, quyết định sơ thẩm bị kháng cáo",
                    "Nội dung và phạm vi kháng cáo", "Lý do kháng cáo",
                    "Yêu cầu của người kháng cáo"):
            self.assertIn(ten, muc)
        # Đơn phản đối phải có thông tin nhãn hiệu bị phản đối (Nhi: "thiếu phần
        # quan trọng nhất là thông tin về nhãn hiệu sẽ phản đối").
        self.assertTrue(any("Đơn đăng ký bị phản đối" in m for m in chat_draft.muc_bat_buoc("don phan doi")))
        self.assertIn("[CẦN BỔ SUNG", chat_draft.khung_van_ban("cong van"))
        self.assertEqual(chat_draft.khung_van_ban("hop dong lao dong"), "")


class DoiChieuMau(unittest.TestCase):
    def test_prompt_rieng_ton_tai(self):
        p = settings.DEFAULTS["prompt_template_check"]
        self.assertIn("[Mẫu công ty:", p)
        for muc in ("MẪU YÊU CẦU GÌ", "BẢNG ĐỐI CHIẾU", "LỖI THỂ THỨC", "VIỆC CẦN SỬA"):
            self.assertIn(muc, p)
        self.assertIn("ĐỦ / THIẾU / KHÁC MẪU / CẦN XEM LẠI", p)

    def test_nguon_mau_khong_co_thi_rong(self):
        # Không có CSDL → hàm phải trả [] chứ không ném lỗi.
        self.assertEqual(rag._nguon_mau_cong_ty(-1), [])


if __name__ == "__main__":
    unittest.main()
