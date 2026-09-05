"""Chạy 17 câu nhân viên chấm KHÔNG ĐẠT qua bot thật trên máy chủ (06/09/2026)
lộ ra ba lỗi mã; mỗi test dưới đây là một ca thật đã tái hiện.

Toàn bộ là logic thuần — không chạm CSDL, không gọi Ollama (deploy/update.sh
chạy nguyên bộ test ngay trên máy chủ đang phục vụ).
"""
import unittest

from app import rag

CAU_TD5 = ("Khách hàng chuẩn bị mua lại 51% cổ phần của một startup công nghệ "
           "đang lưu giữ dữ liệu cá nhân của 1 triệu người dùng. Hãy đưa ra các "
           "cảnh báo pháp lý trọng yếu liên quan đến Nghị định 13/2023/NĐ-CP về "
           "bảo vệ dữ liệu cá nhân")
CAU_THU8 = ("Công ty TNHH có 02 thành viên, mỗi người sở hữu 50% vốn điều lệ. "
            "Hai bên phát sinh mâu thuẫn dẫn tới việc không thể thông qua bất kỳ "
            "Nghị quyết Hội đồng thành viên nào trong 06 tháng liên tiếp. Đưa ra "
            "các giải pháp pháp lý để giải quyết bế tắc (kích hoạt điều khoản mua "
            "lại/thoái vốn, yêu cầu Tòa án giải thể, hay khởi kiện yêu cầu bồi "
            "thường thiệt hại của người đại diện theo pháp luật).")
DAN_DIEU_107 = ("Điều 107 Bộ luật Lao động 2019 quy định: 1. Thời gian làm thêm "
                "giờ là khoảng thời gian làm việc ngoài thời giờ làm việc bình "
                "thường theo quy định của pháp luật, thỏa ước lao động tập thể "
                "hoặc nội quy lao động. 2. Người sử dụng lao động được sử dụng "
                "người lao động làm thêm giờ khi đáp ứng đầy đủ các yêu cầu sau "
                "đây: a) Phải được sự đồng ý của người lao động; b) Bảo đảm số giờ "
                "làm thêm không quá 40 giờ trong 01 tháng. Dựa vào điều luật trên, "
                "thời giờ làm thêm tối đa một tháng là bao nhiêu?")


class CauHoiDaiKhongPhaiLuatNguoiDungDan(unittest.TestCase):
    """TD5/THU8/BC2: câu hỏi tình huống dài có NHẮC tên văn bản bị coi là nguồn
    → model trích dẫn chính câu hỏi [Nguồn 1] cho nội dung bịa từ trí nhớ."""

    def test_tinh_huong_nhac_nghi_dinh_khong_thanh_nguon(self):
        self.assertEqual([], rag._can_cu_nguoi_dung_dan(CAU_TD5, []))

    def test_tinh_huong_nhac_nghi_quyet_khong_thanh_nguon(self):
        self.assertEqual([], rag._can_cu_nguoi_dung_dan(CAU_THU8, []))

    def test_dieu_khoan_hop_dong_trong_tinh_huong_khong_phai_luat(self):
        # BC2: "Hợp đồng … quy định: nếu bên B…" là điều khoản hợp đồng.
        bc2 = ("Hợp đồng dịch vụ logistics giữa 2 thương nhân quy định: nếu bên B "
               "giao hàng chậm trễ thì phải chịu phạt 20% giá trị phần nghĩa vụ hợp "
               "đồng bị vi phạm và bồi thường khoản tiền phạt ước tính là 500 triệu "
               "đồng mà không cần chứng minh thiệt hại thực tế. Thẩm định tính hợp "
               "pháp của điều khoản phạt theo Luật Thương mại 2005.")
        self.assertEqual([], rag._can_cu_nguoi_dung_dan(bc2, []))

    def test_dan_nguyen_van_dieu_luat_van_la_nguon(self):
        out = rag._can_cu_nguoi_dung_dan(DAN_DIEU_107, [])
        self.assertEqual(1, len(out))
        self.assertEqual("user_provided", out[0]["kind"])

    def test_dan_dieu_luat_mot_khoan_van_la_nguon(self):
        # "… quy định: …" đủ dấu hiệu dù không có khoản đánh số.
        text = ("Điều 429 Bộ luật Dân sự 2015 quy định: Thời hiệu khởi kiện để yêu "
                "cầu Tòa án giải quyết tranh chấp hợp đồng là 03 năm, kể từ ngày "
                "người có quyền yêu cầu biết hoặc phải biết quyền và lợi ích hợp "
                "pháp của mình bị xâm phạm. Vậy tranh chấp năm 2021 còn kiện được không?")
        self.assertEqual(1, len(rag._can_cu_nguoi_dung_dan(text, [])))


class VanBanNhacTrongCauHoi(unittest.TestCase):
    def _ten(self, q):
        return [(v["loai"], v["ten"], v["nam"], v["so_hieu"]) for v in rag._van_ban_nhac_trong_cau_hoi(q)]

    def test_ten_va_nam(self):
        self.assertIn(("bo luat", "lao dong", "2019", None),
                      self._ten("Trích dẫn chính xác điều khoản trong Bộ luật Lao động 2019"))

    def test_ten_khong_nam(self):
        self.assertIn(("luat", "thuong mai", None, None),
                      self._ten("theo Luật Thương mại, mức phạt tối đa là bao nhiêu"))

    def test_so_hieu(self):
        self.assertIn(("nghi dinh", None, "2023", "13/2023/NĐ-CP"), self._ten(CAU_TD5))

    def test_luat_khong_ton_tai_van_duoc_nhac(self):
        self.assertIn(("luat", "to tung thuong mai", "2011", None),
                      self._ten("Thời gian hòa giải tối đa theo Luật Tố tụng Thương mại 2011?"))

    def test_hien_thi_giu_nguyen_chu_nguoi_hoi(self):
        v = rag._van_ban_nhac_trong_cau_hoi("Theo Bộ luật Dân sự 2015 thì sao?")[0]
        self.assertEqual("Bộ luật Dân sự 2015", v["hien_thi"])

    def test_tu_dung_khong_thanh_ten(self):
        # "luật hiện hành", "luật này", "luật sư" — không phải văn bản nào.
        self.assertEqual([], self._ten("theo luật hiện hành thì luật này ra sao, hỏi luật sư"))

    def test_hinh_su_dan_su_la_ten_that(self):
        self.assertIn(("bo luat", "hinh su", "2015", None), self._ten("Bộ luật Hình sự 2015"))
        self.assertIn(("bo luat", "dan su", "2015", None), self._ten("Bộ luật Dân sự 2015"))


class VanBanThieuTrongKho(unittest.TestCase):
    KHO = [
        {"doc_type": "law", "so_hieu": "91/2015/QH13", "loai_van_ban": "Bộ luật",
         "trich_yeu": "Dân sự", "title": "Bộ-luật-91-2015-QH13", "content": "Điều 6…"},
        {"doc_type": "law", "so_hieu": "96/2026/NĐ-CP", "loai_van_ban": "Nghị định",
         "trich_yeu": "Quy định chi tiết Luật Đầu tư", "title": "Nghị-định-96-2026-NĐ-CP",
         "content": "…"},
        # Hợp đồng lao động của nhân viên có dòng "Căn cứ Bộ luật Lao động 2019"
        # — KHÔNG được tính là kho có BLLĐ.
        {"doc_type": "ho_so_ns", "title": "HĐLĐ-Nhi",
         "content": "Căn cứ Bộ luật Lao động 2019; Căn cứ nhu cầu…"},
    ]

    def _thieu(self, q, kho=None):
        return [v["hien_thi"] for v in rag._van_ban_thieu_trong_kho(q, self.KHO if kho is None else kho)]

    def test_bo_luat_lao_dong_thieu(self):
        self.assertEqual(["Bộ luật Lao động 2019"],
                         self._thieu("Thời giờ làm thêm tối đa theo Bộ luật Lao động 2019?"))

    def test_bo_luat_dan_su_co(self):
        self.assertEqual([], self._thieu("Theo Điều 6 Bộ luật Dân sự 2015, áp dụng tương tự pháp luật là gì?"))

    def test_so_hieu_co_trong_kho(self):
        self.assertEqual([], self._thieu("Điều kiện tiếp cận thị trường theo Nghị định 96/2026/NĐ-CP"))

    def test_so_hieu_khong_co(self):
        self.assertEqual(["Nghị định 13/2023/NĐ-CP"], self._thieu(CAU_TD5))

    def test_kho_cu_chua_backfill_khop_yeu_theo_loai_va_nam(self):
        # Chưa backfill: không có trích yếu, nhãn đoạn không tên — đúng loại +
        # đúng năm thì coi là có, đừng bảo model "kho không có BLDS".
        kho = [{"doc_type": "law", "title": "Bộ-luật-91-2015-QH13",
                "section_title": "Bộ Luật — Chương XV — Điều 668", "content": "Điều 668…"}]
        self.assertEqual([], self._thieu("Bộ luật Dân sự 2015 quy định gì về hợp đồng?", kho))
        self.assertEqual(["Bộ luật Lao động 2019"],
                         self._thieu("Bộ luật Lao động 2019 quy định gì?", kho))

    def test_nguoi_dung_dan_dieu_luat_thi_coi_nhu_co(self):
        kho = [{"kind": "user_provided", "title": rag.NGUOI_DUNG_DAN_TITLE,
                "content": DAN_DIEU_107}]
        self.assertEqual([], self._thieu("Theo Bộ luật Lao động 2019 thì sao?", kho))

    def test_luat_khong_ton_tai_bi_bao_thieu(self):
        self.assertEqual(["Luật Tố tụng Thương mại 2011"],
                         self._thieu("Thời gian hòa giải theo Luật Tố tụng Thương mại 2011?"))

    def test_prompt_co_dong_bao_thieu(self):
        thieu = rag._van_ban_thieu_trong_kho("Theo Luật Thương mại 2005?", self.KHO)
        p = rag.build_prompt("Theo Luật Thương mại 2005?", [], van_ban_thieu=thieu)
        self.assertIn("KHO KHÔNG CÓ VĂN BẢN NGƯỜI HỎI NÊU: Luật Thương mại 2005", p)
        p2 = rag.build_prompt("Theo Luật Thương mại 2005?", [], van_ban_thieu=[])
        self.assertNotIn("KHO KHÔNG CÓ VĂN BẢN", p2)


class DongCanhBaoKhoThieuDoMayChen(unittest.TestCase):
    def test_chen_truoc_cau_tra_loi(self):
        thieu = [{"hien_thi": "Bộ luật Lao động 2019"}]
        out = rag._canh_bao_kho_thieu("Không quá 50 giờ/tháng [Nguồn 7].", thieu)
        self.assertTrue(out.startswith("**⚠ Kho tài liệu chưa có: Bộ luật Lao động 2019.**"))
        self.assertTrue(out.endswith("Không quá 50 giờ/tháng [Nguồn 7]."))

    def test_khong_thieu_thi_giu_nguyen(self):
        self.assertEqual("x", rag._canh_bao_kho_thieu("x", []))
        self.assertEqual("", rag._canh_bao_kho_thieu("", [{"hien_thi": "BLLĐ"}]))


class CauHoiPhapLy(unittest.TestCase):
    def test_nhan_dien(self):
        self.assertTrue(rag._la_cau_hoi_phap_ly("Điều 107 Bộ luật Lao động"))
        self.assertTrue(rag._la_cau_hoi_phap_ly("theo Luật Thương mại 2005"))
        self.assertFalse(rag._la_cau_hoi_phap_ly("hds có bao nhiêu nhân viên"))

    def test_viet_tat_luat_su_hay_dung(self):
        # NGAN2 06/09: "…hệ quả pháp lý của việc hủy bỏ hợp đồng theo BLDS 2015."
        # không có chữ "luật" nào → trước đây không được coi là câu hỏi luật.
        self.assertTrue(rag._la_cau_hoi_phap_ly("hệ quả hủy bỏ hợp đồng theo BLDS 2015"))
        self.assertTrue(rag._la_cau_hoi_phap_ly("thời hạn góp vốn theo LDN"))
        v = rag._van_ban_nhac_trong_cau_hoi("hủy bỏ hợp đồng theo BLDS 2015.")
        self.assertEqual([("bo luat", "dan su", "2015", "BLDS 2015")],
                         [(x["loai"], x["ten"], x["nam"], x["hien_thi"]) for x in v])
        kho = [{"doc_type": "law", "so_hieu": "91/2015/QH13", "loai_van_ban": "Bộ luật",
                "trich_yeu": "Dân sự", "title": "Bộ-luật-91-2015-QH13", "content": "…"}]
        self.assertEqual([], rag._van_ban_thieu_trong_kho("theo BLDS 2015", kho))
        self.assertEqual(["BLLĐ 2019"],
                         [x["hien_thi"] for x in rag._van_ban_thieu_trong_kho("theo BLLĐ 2019", kho)])


class SoHieuTuTenFile(unittest.TestCase):
    def test_ten_file_gach_ngang_la_so_that(self):
        # Kho chưa backfill: nhãn đoạn "Nghị Định — Chương III — Điều 25" không
        # có số, chỉ tên file mang "168-2025-NĐ-CP" — đừng gắn cờ số đúng.
        chunks = [{"title": "Nghị-định-168-2025-NĐ-CP",
                   "content": "[Nghị Định — Chương III — Điều 25] Điều 25. Hồ sơ…"}]
        text = "Hồ sơ theo Điều 25 Nghị định 168/2025/NĐ-CP [Nguồn 1]."
        self.assertEqual(text, rag._canh_bao_so_hieu(text, chunks))

    def test_so_bia_van_bi_bao(self):
        chunks = [{"title": "Nghị-định-168-2025-NĐ-CP", "content": "Điều 25…"}]
        text = "Theo Nghị định 63/2025/NĐ-CP [Nguồn 1]."
        self.assertIn("63/2025/NĐ-CP", rag._canh_bao_so_hieu(text, chunks))


class TenNhanVienTrongTuGhep(unittest.TestCase):
    """BC2 lượt ba: 'Luật Thương MẠI' bỏ dấu thành 'mai' → bộ hồ sơ của nhân viên
    Mai (CCCD, bằng đại học, HĐLĐ) bị ghim vào nguồn của câu hỏi luật."""

    TEN = ["Mai", "Ngân", "Nhi"]

    def test_thuong_mai_khong_phai_nhan_vien_mai(self):
        from app import company_context
        q = ("Hợp đồng dịch vụ logistics giữa 2 thương nhân quy định phạt 20%. Thẩm "
             "định tính hợp pháp của điều khoản phạt theo Luật Thương mại 2005.")
        self.assertEqual([], company_context.detect_staff_person(q, self.TEN))
        self.assertEqual([], company_context.detect_staff_person(
            "hợp đồng này ngày mai hết hạn", self.TEN))

    def test_hoi_dich_danh_van_nhan_ra(self):
        from app import company_context
        self.assertEqual(["Mai"], company_context.detect_staff_person(
            "cho tôi xem hợp đồng lao động của Mai", self.TEN))


class ThieuVanBanKhongTinhAnLe(unittest.TestCase):
    def test_an_le_nhac_bo_luat_khong_lam_kho_co_luat(self):
        # TD1 lượt ba: án lệ lao động 071/2018 lọt vào nguồn, chốt tưởng kho có BLLĐ.
        kho = [{"doc_type": "an_le", "title": "071_20-2018-AL",
                "content": "Án lệ về hợp đồng lao động, áp dụng Bộ luật Lao động 2019…"}]
        self.assertEqual(["Bộ luật Lao động 2019"], [
            v["hien_thi"] for v in rag._van_ban_thieu_trong_kho(
                "thời giờ làm thêm theo Bộ luật Lao động 2019", kho)])

    def test_cung_ten_khac_nam_van_thieu(self):
        kho = [{"doc_type": "law", "so_hieu": "10/2012/QH13", "loai_van_ban": "Bộ luật",
                "trich_yeu": "Lao động", "title": "Bộ-luật-10-2012-QH13", "content": "…"}]
        self.assertEqual(["Bộ luật Lao động 2019"], [
            v["hien_thi"] for v in rag._van_ban_thieu_trong_kho(
                "theo Bộ luật Lao động 2019", kho)])
        self.assertEqual([], rag._van_ban_thieu_trong_kho("theo Bộ luật Lao động 2012", kho))


class WordHeadingLaDieuLuat(unittest.TestCase):
    """Bộ luật Dân sự .docx: từng Điều là Heading → '[Mục: Điều 6. …]'; bộ cắt
    chỉ thấy 1/917 điều, cả Bộ luật thành 229 mảnh 'Điều 274 — phần k/229'."""

    VAN_BAN = ("[Mục: BỘ LUẬT]\n[Mục: DÂN SỰ]\nCăn cứ Hiến pháp;\nQuốc hội ban hành Bộ "
               "luật Dân sự.\n[Mục: Phần thứ nhất]\n[Mục: QUY ĐỊNH CHUNG]\n[Mục: Chương I]\n"
               "[Mục: Điều 5. Áp dụng tập quán]\n1. Tập quán là quy tắc xử sự có nội "
               "dung rõ ràng.\n[Mục: Điều 6. Áp dụng tương tự pháp luật]\n1. Trường hợp "
               "phát sinh quan hệ thuộc phạm vi điều chỉnh của pháp luật dân sự mà các "
               "bên không có thỏa thuận thì áp dụng quy định của pháp luật điều chỉnh "
               "quan hệ dân sự tương tự.\n")

    def test_mo_nhan_muc(self):
        from app import van_ban
        s = van_ban.mo_nhan_muc(self.VAN_BAN)
        self.assertNotIn("[Mục:", s)
        self.assertIn("\nĐiều 6. Áp dụng tương tự pháp luật\n", s)

    def test_cat_ra_tung_dieu_va_co_ten_van_ban(self):
        from app.ingest import chunk_law_structured
        pieces = chunk_law_structured(self.VAN_BAN, ten_file="Bộ-luật-91-2015-QH13.docx")
        locators = [p.source_locator for p in pieces]
        self.assertIn("dieu:5", locators)
        self.assertIn("dieu:6", locators)
        dieu_6 = next(p for p in pieces if p.source_locator == "dieu:6")
        self.assertTrue(dieu_6.content.startswith("[Bộ luật Dân sự số 91/2015/QH13"),
                        dieu_6.content[:70])

    def test_metadata_doc_duoc_loai_va_trich_yeu_tu_heading(self):
        from app import van_ban
        m = van_ban.boc_metadata(self.VAN_BAN, ten_file="Bộ-luật-91-2015-QH13.docx")
        self.assertEqual(("Bộ luật", "Dân sự", "91/2015/QH13"),
                         (m["loai_van_ban"], m["trich_yeu"], m["so_hieu"]))


if __name__ == "__main__":
    unittest.main()
