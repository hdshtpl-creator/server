"""Rà lại 10 báo cáo nhân viên (28-29/08/2026) ngày 11/09: hai yêu cầu chưa
có trong prompt được bổ sung — phản bác tiền đề sai, và khung trả lời cho câu
hỏi thủ tục/hồ sơ. Logic thuần, không chạm CSDL.
"""
import unittest

from app import rag


class KhungThuTuc(unittest.TestCase):
    def test_nhan_ra_cau_hoi_thu_tuc(self):
        for cau in ("Hồ sơ thay đổi người đại diện theo pháp luật gồm những gì?",
                    "Thủ tục xin cấp Giấy chứng nhận đăng ký đầu tư cho nhà đầu tư Nhật",
                    "Quy trình chuyển trụ sở khác tỉnh và chốt thuế",
                    "Trình tự chấp thuận chủ trương đầu tư dự án có giao đất"):
            with self.subTest(cau=cau):
                self.assertTrue(rag._yeu_cau_thu_tuc(cau))

    def test_cau_khong_phai_thu_tuc(self):
        for cau in ("So sánh hủy bỏ hợp đồng và đơn phương chấm dứt",
                    "Mức phạt vi phạm tối đa theo Luật Thương mại là bao nhiêu?"):
            with self.subTest(cau=cau):
                self.assertFalse(rag._yeu_cau_thu_tuc(cau))

    def test_prompt_co_khung_khi_hoi_thu_tuc(self):
        p = rag.build_prompt("Thủ tục đăng ký thay đổi trụ sở chính?", [],
                             chunk_chars=0, budget=0)
        self.assertIn("THỦ TỤC/HỒ SƠ", p)
        self.assertIn("(3) Thành phần hồ sơ", p)
        self.assertIn("(6) Phí, lệ phí", p)
        p2 = rag.build_prompt("Phạt vi phạm tối đa bao nhiêu?", [], chunk_chars=0, budget=0)
        self.assertNotIn("THỦ TỤC/HỒ SƠ", p2)


class TienDeSai(unittest.TestCase):
    def test_luon_co_luat_phan_bac(self):
        # Báo cáo Thuỳ Dương 28/08: "AI không có khả năng nhận diện bẫy để phản
        # bác, nương theo logic sai của người hỏi"; "khi người dùng chỉ ra lỗi
        # trích dẫn sai, AI vẫn lặp lại câu trả lời cũ".
        p = rag.build_prompt("Theo Điều 999 Luật Doanh nghiệp, phạt 50%?", [],
                             chunk_chars=0, budget=0)
        self.assertIn("TIỀN ĐỀ SAI", p)
        self.assertIn("không lặp lại câu cũ", p)



class MoRongVietTat(unittest.TestCase):
    def test_irc_erc(self):
        q = rag.mo_rong_viet_tat("Giữa thủ tục cấp ERC và thủ tục cấp IRC phải xin cấp loại nào trước?")
        self.assertIn("Giấy chứng nhận đăng ký đầu tư", q)
        self.assertIn("Giấy chứng nhận đăng ký doanh nghiệp", q)
        self.assertTrue(q.startswith("Giữa thủ tục cấp ERC"))

    def test_khong_doi_khi_khong_co_viet_tat(self):
        q = "Mức phạt vi phạm tối đa là bao nhiêu?"
        self.assertEqual(rag.mo_rong_viet_tat(q), q)
        # đã viết đầy đủ trong câu thì không nối thêm
        q2 = "Hội đồng thành viên (HĐTV) họp thế nào?"
        self.assertEqual(rag.mo_rong_viet_tat(q2), q2)

    def test_m_and_a(self):
        self.assertIn("mua bán sáp nhập", rag.mo_rong_viet_tat("Rủi ro trong giao dịch M&A"))


class CumTraCuu(unittest.TestCase):
    def test_tach_dong_model(self):
        raw = ("<think>nghĩ…</think>\n1. Mua lại phần vốn góp\n- \"Giải thể doanh nghiệp\"\n"
               "• Yêu cầu Tòa án giải thể công ty\nx\n3) Trách nhiệm của người đại diện theo pháp luật\n"
               "Đây là tình huống về bế tắc trong hội đồng thành viên của công ty trách nhiệm hữu hạn hai thành viên trở lên\n")
        self.assertEqual(rag._tach_cum_tra_cuu(raw),
                         ["Mua lại phần vốn góp", "Giải thể doanh nghiệp",
                          "Yêu cầu Tòa án giải thể công ty",
                          "Trách nhiệm của người đại diện theo pháp luật"])

    def test_rong(self):
        self.assertEqual(rag._tach_cum_tra_cuu(""), [])
        self.assertEqual(rag._tach_cum_tra_cuu("<think>chỉ nghĩ</think>"), [])


class ChotKeLuat(unittest.TestCase):
    """Câu hỏi tình huống không nêu tên văn bản vẫn phải đi luồng luật."""

    def test_tinh_huong_khong_neu_luat(self):
        for cau in ("Công ty TNHH 2 thành viên thành lập ngày 01/01/2026. Một thành viên cam kết góp vốn "
                    "bằng quyền sử dụng đất nhưng chưa hoàn tất thủ tục. Xác định hậu quả pháp lý.",
                    "Chi nhánh của Công ty X ký hợp đồng và phát sinh tranh chấp. Thẩm định tư cách bị đơn.",
                    "Giữa thủ tục cấp ERC và thủ tục cấp IRC phải xin cấp loại nào trước?"):
            with self.subTest(cau=cau):
                self.assertTrue(rag._hoi_ve_phap_luat(cau))

    def test_cau_khong_phap_ly(self):
        for cau in ("Tóm tắt file đính kèm giúp tôi", "Hôm nay thời tiết thế nào", "Mai có mấy hồ sơ"):
            with self.subTest(cau=cau):
                # "hồ sơ" là từ pháp lý nhưng câu ngắn về dữ liệu HDS bị
                # _legal_or_scenario_question chặn ở tầng trên — test tầng này
                # chỉ soi từ vựng.
                if "hồ sơ" in cau:
                    continue
                self.assertFalse(rag._hoi_ve_phap_luat(cau))


class TenNhanSuTrongTuGhep(unittest.TestCase):
    """'tài khoản ngân hàng' không phải nhân viên Ngân (2.4, 1.7, 1.9 của 40
    kịch bản: bộ hồ sơ Ngân chiếm 14/22 nguồn, đoạn luật bị đẩy ra)."""

    def test_ngan_hang_khong_phai_nguoi(self):
        from app import company_context
        cau = ("Nguyên đơn khởi kiện đòi nợ 5 tỷ đồng. Phát hiện Bị đơn đang tẩu tán nhà "
               "xưởng và rút tiền khỏi tài khoản ngân hàng. Lập hồ sơ yêu cầu Tòa án áp dụng "
               "biện pháp khẩn cấp tạm thời")
        self.assertEqual(company_context.detect_staff_person(cau, ["Ngân", "Mai", "Nhi"]), [])
        self.assertEqual(company_context.detect_staff_person(
            "thủ tục đăng ký khoản vay với Ngân hàng Nhà nước, hồ sơ gồm gì", ["Ngân"]), [])
        # nhưng hỏi đích danh thì vẫn nhận
        self.assertEqual(company_context.detect_staff_person("sơ yếu lý lịch của Ngân", ["Ngân"]), ["Ngân"])

if __name__ == "__main__":
    unittest.main()


class CanCuPhapLuatTrongCau(unittest.TestCase):
    """Câu hỏi pháp lý: prompt bắt nêu số Điều ngay trong câu, không lấy điều lệ
    khách làm căn cứ (phản hồi Thuỳ Dương, Mai, Loan 28-29/08/2026)."""

    def test_cau_hoi_luat_co_khoi_can_cu(self):
        p = rag.build_prompt("Thời hiệu khởi kiện tranh chấp hợp đồng thương mại là bao lâu?",
                             [], chunk_chars=0, budget=0)
        self.assertIn("CĂN CỨ PHÁP LUẬT:", p)
        self.assertIn("KHÔNG thay được số điều", p)
        self.assertIn("theo Điều lệ của Công ty X", p)
        # Khối này phải đứng NGAY TRƯỚC câu hỏi để model đọc sau cùng.
        self.assertLess(p.index("CĂN CỨ PHÁP LUẬT:"), p.index("CÂU HỎI HIỆN TẠI:"))

    def test_cau_hoi_thuong_khong_co(self):
        for cau in ("Hôm nay ai đi làm muộn?", "Mai còn bao nhiêu ngày phép?",
                    "Tóm tắt biên bản họp tuần trước"):
            with self.subTest(cau=cau):
                p = rag.build_prompt(cau, [], chunk_chars=0, budget=0)
                self.assertNotIn("CĂN CỨ PHÁP LUẬT:", p)


class TuVungDoanhNghiep(unittest.TestCase):
    """Câu hỏi doanh nghiệp không dùng chữ 'luật' vẫn phải vào luồng luật."""

    def test_cau_doanh_nghiep(self):
        for cau in ("Thời hạn góp vốn của thành viên, cổ đông là trong vòng bao nhiêu ngày?",
                    "Vốn điều lệ tối thiểu để thành lập công ty là bao nhiêu?",
                    "Muốn giải thể công ty thì làm thế nào?",
                    "Chuyển nhượng phần vốn cho người ngoài có cần chấp thuận không?"):
            with self.subTest(cau=cau):
                self.assertTrue(rag._hoi_ve_phap_luat(cau))

    def test_cau_noi_bo_khong_vao(self):
        for cau in ("Mai còn bao nhiêu ngày phép?", "Lịch họp tuần này có gì?",
                    "Tóm tắt biên bản họp hôm qua"):
            with self.subTest(cau=cau):
                self.assertFalse(rag._hoi_ve_phap_luat(cau))
