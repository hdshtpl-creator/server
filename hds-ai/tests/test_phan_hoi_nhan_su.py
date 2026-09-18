"""Khoá lại các lỗi nhân viên báo trong đợt rà soát 28-29/08/2026.

Nguồn: 10 báo cáo trong "nv phản hồi" (Thuỳ Dương, Phạm Loan, Ngân, Huế, Mai,
Nhi, Thư…). Mỗi test ở đây là MỘT câu hỏi thật đã bị chấm KHÔNG ĐẠT, giữ
nguyên văn để lần sau có sửa gì cũng không tái phát.

Toàn bộ là logic thuần — không chạm CSDL, không gọi Ollama (deploy/update.sh
chạy nguyên bộ test ngay trên máy chủ đang phục vụ).
"""
import unittest

from app import company_context, rag


class CauHoiPhapLyKhongDuocTraLoiBangDuLieuNoiBo(unittest.TestCase):
    """Lỗi nặng nhất, 4 người báo độc lập.

    Bộ nhận diện ý định so khớp theo cụm từ, mà nhiều cụm của nó nằm ngay
    trong câu hỏi pháp lý bình thường: "nguoi lao dong" và "nhan su" thuộc
    STAFF_WORDS, "canh bao" thuộc ALERT_WORDS. Hậu quả: câu hỏi về Bộ luật
    Lao động bị trả lời bằng danh sách 3 nhân sự HDS, câu hỏi về Nghị định
    13/2023 bị trả lời "không có vụ nào quá hạn".
    """

    def _phai_ve_tra_cuu(self, cau_hoi):
        self.assertIsNone(
            company_context.infer_intent(cau_hoi),
            f"Câu này phải đi luồng tra cứu tài liệu, không phải bộ đếm nội "
            f"bộ:\n  {cau_hoi[:90]}")

    def test_thoi_gio_lam_them_bi_tra_loi_bang_ho_so_nhan_su(self):
        # Báo cáo Thuỳ Dương: "AI trả lời hoàn toàn sai trọng tâm. Hệ thống tự
        # động lấy dữ liệu nhân sự nội bộ công ty để phản hồi."
        self._phai_ve_tra_cuu(
            "Quy định về thời giờ làm thêm tối đa trong một tháng và một năm "
            "của người lao động hiện hành là bao nhiêu? Trích dẫn chính xác "
            "điều khoản trong Bộ luật Lao động 2019")

    def test_canh_bao_phap_ly_bi_tra_loi_bang_han_chot_vu_viec(self):
        # Báo cáo Thuỳ Dương: phản hồi bị lệch thành "Không có vụ nào quá hạn
        # hoặc sắp đến hạn trong phạm vi người hỏi phụ trách".
        self._phai_ve_tra_cuu(
            "Khách hàng chuẩn bị mua lại 51% cổ phần của một startup công nghệ "
            "đang lưu giữ dữ liệu cá nhân của 1 triệu người dùng. Hãy đưa ra "
            "các cảnh báo pháp lý trọng yếu liên quan đến Nghị định "
            "13/2023/NĐ-CP về bảo vệ dữ liệu cá nhân")

    def test_cat_giam_nhan_su_bi_tra_loi_bang_danh_ba(self):
        self._phai_ve_tra_cuu(
            "Doanh nghiệp cắt giảm 10 nhân sự do ứng dụng công nghệ tự động "
            "hóa. Công ty muốn ra quyết định chấm dứt HĐLĐ ngay sau khi thông "
            "báo trước 30 ngày. Rà soát quy trình: xây dựng phương án sử dụng "
            "lao động, thông báo cho Sở LĐ-TB&XH")

    def test_be_tac_hoi_dong_thanh_vien_bi_tra_loi_bang_ho_so_nhan_su(self):
        # Báo cáo Thư, tình huống 8: "Trả lời linh tinh KHÔNG ĐẠT" — bot đáp
        # bằng "Theo cây thư mục 8. HỒ SƠ NHÂN SỰ, HDS đang có 3 bộ hồ sơ".
        self._phai_ve_tra_cuu(
            "Công ty TNHH có 02 thành viên, mỗi người sở hữu 50% vốn điều lệ. "
            "Hai bên phát sinh mâu thuẫn dẫn tới việc không thể thông qua bất "
            "kỳ Nghị quyết Hội đồng thành viên nào trong 06 tháng liên tiếp")

    def test_dieu_luat_gia_lap_van_di_luong_tra_cuu(self):
        self._phai_ve_tra_cuu(
            "Theo Điều 999 Bộ luật Dân sự 2015, quy định về quyền sở hữu đối "
            "với tài sản vô hình là gì?")

    def test_nda_nca_nhan_su_cap_cao(self):
        # Báo cáo Ngân: "Câu trả lời đầu tiên: Không liên quan đến nội dung
        # công việc" rồi ra danh sách hồ sơ nhân sự.
        self._phai_ve_tra_cuu(
            "Giám đốc R&D ký cam kết không làm việc cho các đối thủ cạnh tranh "
            "trong vòng 02 năm sau khi nghỉ việc, nếu vi phạm bồi thường 1 tỷ "
            "đồng. Đánh giá khả năng khởi kiện đòi bồi thường vi phạm NDA theo "
            "thực tiễn xét xử tại Tòa án và Trọng tài")


class CauHoiNoiBoVanPhaiChayNhuCu(unittest.TestCase):
    """Chốt mới KHÔNG được nuốt các câu hỏi vận hành thật.

    Đây là nửa còn lại của bài toán: chặn quá tay thì mất luôn tính năng trả
    lời xác định (đếm khách, danh bạ, hạn chót) vốn là cổng chống bịa.
    """

    def test_dem_nhan_su(self):
        self.assertEqual(company_context.infer_intent("hds có bao nhiêu nv"),
                         "staff_directory")

    def test_dem_nguoi_cong_ty_minh(self):
        self.assertEqual(company_context.infer_intent("cty tôi có mấy người"),
                         "staff_directory")

    def test_han_chot_vu_viec(self):
        self.assertEqual(company_context.infer_intent("vụ nào sắp đến hạn"),
                         "matter_alerts")

    def test_dem_kho_tai_lieu_ban_an(self):
        # Có chữ "bản án" nhưng là câu ĐẾM KHO của HDS — không được đẩy sang
        # luồng tra cứu chỉ vì trùng từ khoá pháp lý.
        self.assertEqual(
            company_context.infer_intent("hds đang có mấy tài liệu bản án"),
            "doc_inventory")

    def test_dem_khach_hang(self):
        self.assertEqual(
            company_context.infer_intent("hds có bao nhiêu khách hàng"),
            "client_roster")


class DoiChuDeSangPhapLuat(unittest.TestCase):
    """Hỏi nhân sự rồi hỏi sang pháp luật thì phải rời hẳn luồng đếm.

    Chốt đặt TRƯỚC nhánh dùng `state`, nếu không câu pháp lý tiếp sau một câu
    đếm sẽ kế thừa intent cũ và lại ra bảng nhân sự.
    """

    def test_state_cu_khong_keo_sang_cau_phap_ly(self):
        state = {"intent": "staff_directory"}
        self.assertIsNone(company_context.infer_intent(
            "Trích dẫn Điều 500 Bộ luật Lao động 2019 quy định về chế độ nghỉ "
            "hưu sớm", state=state))


class TrichDanSaiSoHieuVanBan(unittest.TestCase):
    """Lỗi 5/10 báo cáo cùng nêu: nội dung điều luật đúng nhưng SỐ HIỆU bịa.

    Ví dụ thật trong báo cáo: "Nghị định số 63/2025/QH15" (một nghị định
    không bao giờ mang đuôi QH15 — đó là ký hiệu của Quốc hội), "Luật số
    203/2025/QH15", "Luật Doanh nghiệp số 62/2020/QH14" (số thật: 59/2020).
    """

    def test_nhan_dien_so_hieu_van_ban(self):
        so = rag._so_hieu_van_ban(
            "Theo khoản 4 Điều 21 Luật số 203/2025/QH15 và Nghị định số "
            "63/2025/QH15 thì...")
        self.assertIn("203/2025/QH15", so)
        self.assertIn("63/2025/QH15", so)

    def test_nghi_dinh_mang_duoi_quoc_hoi_la_bia(self):
        # Không cần đối chiếu kho cũng biết sai: nghị định do Chính phủ ban
        # hành, ký hiệu ND-CP; QH15 là của Quốc hội.
        self.assertTrue(rag._so_hieu_vo_ly("Nghị định số 63/2025/QH15"))
        self.assertTrue(rag._so_hieu_vo_ly("Thông tư số 143/2025/QH15"))

    def test_so_hieu_hop_le_khong_bi_bao_nham(self):
        self.assertFalse(rag._so_hieu_vo_ly(
            "Luật Doanh nghiệp số 59/2020/QH14"))
        self.assertFalse(rag._so_hieu_vo_ly("Nghị định 13/2023/NĐ-CP"))
        self.assertFalse(rag._so_hieu_vo_ly("Thông tư 121/2026/TT-BTC"))


class CanCuNguoiDungDanVaoChat(unittest.TestCase):
    """Người dùng dán điều luật đúng vào chat thì bot phải theo nó.

    Thuỳ Dương 28/08/2026: "Khi cung cấp cả nội dung của căn cứ, AI vẫn trả
    lời sai như câu trả lời cũ." Nguyên nhân: đoạn dán chỉ nằm ở phần diễn
    biến hội thoại, không phải một [Nguồn n] — bot không trích dẫn được nên
    mọi câu dựa vào nó bị bộ kiểm chứng cắt, phần sống sót lại là câu dựa
    trên tài liệu kho SAI.
    """

    DIEU_LUAT = (
        "Điều 429 Bộ luật Dân sự 2015 quy định: Thời hiệu khởi kiện để yêu cầu "
        "Tòa án giải quyết tranh chấp hợp đồng là 03 năm, kể từ ngày người có "
        "quyền yêu cầu biết hoặc phải biết quyền và lợi ích hợp pháp của mình "
        "bị xâm phạm. Đây là quy định thay thế cho cách tính thời hiệu trước "
        "đây, áp dụng cho mọi tranh chấp hợp đồng dân sự và thương mại."
    )

    def test_doan_dan_thanh_nguon_trich_dan_duoc(self):
        out = rag._can_cu_nguoi_dung_dan(self.DIEU_LUAT, history=None)
        self.assertEqual(len(out), 1)
        self.assertIn("Người dùng cung cấp", out[0]["title"])
        self.assertIn("03 năm", out[0]["content"])

    def test_lay_ca_doan_dan_o_luot_truoc(self):
        history = [("user", self.DIEU_LUAT), ("assistant", "Đã ghi nhận.")]
        out = rag._can_cu_nguoi_dung_dan("vậy trả lời lại giúp tôi", history)
        self.assertEqual(len(out), 1)

    def test_cau_hoi_thuong_khong_bi_bien_thanh_nguon(self):
        # Câu hỏi bình thường, dù có chữ "luật", không phải là căn cứ dán vào.
        self.assertEqual(
            rag._can_cu_nguoi_dung_dan("thời hiệu khởi kiện theo luật là bao lâu?",
                                       history=None), [])

    def test_doan_dai_khong_co_moc_phap_ly_thi_bo_qua(self):
        van_xuoi = "Hôm nay tôi đi gặp khách hàng ở Hà Nội. " * 12
        self.assertEqual(rag._can_cu_nguoi_dung_dan(van_xuoi, history=None), [])

    def test_khong_lap_lai_cung_mot_doan(self):
        history = [("user", self.DIEU_LUAT)]
        out = rag._can_cu_nguoi_dung_dan(self.DIEU_LUAT, history)
        self.assertEqual(len(out), 1, "cùng một đoạn không được đếm hai lần")


class TrinhBayBangKhiSoSanh(unittest.TestCase):
    """Phạm Loan 28/08/2026: câu hỏi so sánh bị trả lời bằng văn xuôi lặp từ,
    và hai khái niệm khác nhau được diễn giải gần như đồng nhất."""

    def test_bat_cau_so_sanh(self):
        for q in ("So sánh hủy bỏ và chấm dứt đề nghị giao kết hợp đồng",
                  "Phân biệt phạt vi phạm và bồi thường thiệt hại",
                  "Hai khái niệm này khác nhau chỗ nào?",
                  "Đối chiếu Điều 423 và Điều 428"):
            self.assertTrue(rag._yeu_cau_bang(q), q)

    def test_khong_bat_cau_hoi_thuong(self):
        for q in ("Thời hiệu khởi kiện là bao lâu?",
                  "Soạn giúp tôi hợp đồng lao động"):
            self.assertFalse(rag._yeu_cau_bang(q), q)

    def test_prompt_co_huong_dan_bang_khi_can(self):
        p = rag.build_prompt("So sánh hủy bỏ và chấm dứt đề nghị giao kết",
                             [{"content": "nội dung", "title": "Luật X"}])
        self.assertIn("BẢNG Markdown", p)

    def test_prompt_khong_phinh_khi_khong_can(self):
        p = rag.build_prompt("Thời hiệu khởi kiện là bao lâu?",
                             [{"content": "nội dung", "title": "Luật X"}])
        self.assertNotIn("BẢNG Markdown", p)


class PromptCoDuBaChinhSachMoi(unittest.TestCase):
    """Ba yêu cầu của nhân viên phải nằm trong câu nhắn hệ thống."""

    def test_phan_bac_tien_de_sai(self):
        from app import settings
        p = settings.DEFAULTS["prompt_internal"]
        self.assertIn("PHẢN BÁC TIỀN ĐỀ SAI", p)
        self.assertIn("không sáng tác quy định", p)

    def test_tiep_thu_can_cu_nguoi_dung(self):
        from app import settings
        p = settings.DEFAULTS["prompt_internal"]
        self.assertIn("NGƯỜI DÙNG SỬA LẠI CĂN CỨ", p)
        self.assertIn("không lặp lại câu trả lời cũ", p)

    def test_hoi_lai_khi_thieu_du_kien(self):
        from app import settings
        p = settings.DEFAULTS["prompt_internal"]
        self.assertIn("THIẾU DỮ KIỆN", p)
        self.assertIn("Cần bổ sung để kết luận chắc chắn", p)


if __name__ == "__main__":
    unittest.main()


class CauHoiQuyPhamKhongPhaiDemNhanSuTests(unittest.TestCase):
    """Kiểm thử vai thực tập sinh 18/09/2026: câu hỏi về một QUY PHẠM (mức,
    thời hạn) có chữ "người lao động" từng bị trả lời bằng danh sách nhân sự
    HDS — sai hoàn toàn và lộ tên người cho vai trợ lý."""

    def test_thu_viec_toi_da_la_cau_hoi_luat(self):
        self.assertIsNone(company_context.infer_intent(
            "Thời gian thử việc tối đa đối với người lao động có trình độ cao "
            "đẳng là bao nhiêu ngày?"))

    def test_muc_quy_pham_khac(self):
        for q in [
            "người lao động được nghỉ phép năm bao nhiêu ngày?",
            "lương tối thiểu vùng áp dụng cho người lao động là bao nhiêu?",
            "người lao động phải báo trước bao nhiêu ngày khi nghỉ việc?",
            "làm thêm giờ tối đa bao nhiêu giờ một tháng?",
        ]:
            with self.subTest(q=q):
                self.assertIsNone(company_context.infer_intent(q))

    def test_cau_van_hanh_van_la_van_hanh(self):
        # "bao nhiêu ngày" đi kèm vụ việc / hạn chót vẫn là dữ liệu HDS.
        self.assertEqual(company_context.infer_intent("vụ SunGroup còn bao nhiêu ngày đến hạn"),
                         "matter_alerts")
        self.assertEqual(company_context.infer_intent("hds có bao nhiêu người lao động"),
                         "staff_directory")
