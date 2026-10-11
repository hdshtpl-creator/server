"""Câu trả lời luật — sửa theo lượt 40 kịch bản ngày 11/10/2026.

(1) Model có điều đúng trong nguồn mà không nêu số: build_prompt liệt kê các
"điều luật trọng tâm" (điều nền của luat_nen) kèm số nguồn, và nói rõ thứ bậc
Bộ luật/Luật trước Nghị định/Thông tư. (2) Câu tình huống nhắc "bộ hồ sơ"
không phải lệnh tạo file — chỉ tạo khi người dùng RA LỆNH (chủ dự án chốt
12/10/2026). Test thuần, không CSDL, không mạng.
"""
import unittest

from app import doc_factory as df
from app import luat_nen, rag


def _d(doc, nhan, nen=False, so="91/2015/QH13"):
    c = {"document_id": doc, "doc_type": "law", "so_hieu": so, "section_title": nhan,
         "content": "…", "score": 0.7}
    if nen:
        c["dieu_nen"] = True
    return c


class DieuTrongTam(unittest.TestCase):
    def test_gom_theo_dieu_kem_so_nguon(self):
        ctx = [_d(1, "Luật Thương mại số 36/2005/QH11 (văn bản hợp nhất 17/VBHN-VPQH) — Điều 294", nen=True),
               _d(2, "Thông tư số 32/2015/TT-BCT — Điều 5"),
               _d(3, "Bộ luật Dân sự số 91/2015/QH13 — PHẦN THỨ BA — Điều 156", nen=True),
               _d(3, "Bộ luật Dân sự số 91/2015/QH13 — PHẦN THỨ BA — Điều 156 — phần 2/2", nen=True)]
        self.assertEqual(rag._dieu_trong_tam(ctx), [
            "Điều 294 Luật Thương mại số 36/2005/QH11 (văn bản hợp nhất 17/VBHN-VPQH) [Nguồn 1]",
            "Điều 156 Bộ luật Dân sự số 91/2015/QH13 [Nguồn 3, 4]"])

    def test_khong_co_dieu_nen_thi_rong(self):
        self.assertEqual(rag._dieu_trong_tam([_d(2, "Thông tư số 32/2015/TT-BCT — Điều 5")]), [])

    def test_prompt_cau_luat_co_thu_bac_va_trong_tam(self):
        ctx = [_d(3, "Bộ luật Dân sự số 91/2015/QH13 — PHẦN THỨ BA — Điều 156", nen=True)]
        p = rag.build_prompt("Nhà cung cấp viện dẫn sự kiện bất khả kháng để từ chối giao hàng, "
                             "đánh giá tính hợp pháp theo quy định pháp luật",
                             ctx, chunk_chars=0, budget=0)
        self.assertIn("THỨ BẬC VĂN BẢN", p)
        self.assertIn("ĐIỀU LUẬT TRỌNG TÂM", p)
        self.assertIn("Điều 156 Bộ luật Dân sự số 91/2015/QH13 [Nguồn 1]", p)

    def test_khu_trung_giu_dau_dieu_nen_cho_ban_hop_nhat(self):
        goc = _d(42920, "Luật Doanh nghiệp số 59/2020/QH14 — Chương IX — Điều 204", nen=True,
                 so="59/2020/QH14")
        hn = _d(427, "Luật Doanh nghiệp số 59/2020/QH14 (văn bản hợp nhất 67/VBHN-VPQH) — Chương IX — Điều 204",
                so="67/VBHN-VPQH")
        out = rag.bo_ban_trung_so_hieu([goc, hn])
        self.assertEqual([c["document_id"] for c in out], [427])
        self.assertTrue(out[0].get("dieu_nen"))


class DieuNenBoSung(unittest.TestCase):
    def test_cac_cau_truot_11_10(self):
        cases = [
            ("Công ty TNHH 2 thành viên bế tắc, kích hoạt điều khoản mua lại phần vốn góp / thoái vốn", "ldn", 51),
            ("Đánh giá điều kiện hủy bỏ hợp đồng khi bên B chậm tiến độ 45 ngày", "blds", 424),
            ("Soạn đơn ý kiến của bên thứ ba, chứng minh nhãn hiệu nổi tiếng", "shtt", 75),
            ("Soạn đơn ý kiến của bên thứ ba / phản đối đơn gửi Cục Sở hữu trí tuệ", "shtt", 112),
        ]
        for q, khoa, dieu in cases:
            self.assertIn(dieu, luat_nen.dieu_nen(q, khoa), q)

    def test_trong_tai_ra_luat_va_nghi_quyet(self):
        q = ('Hợp đồng quy định: "Mọi tranh chấp sẽ được giải quyết tại Trung tâm Trọng tài Quốc tế '
             'Việt Nam (VIAC) hoặc Tòa án nhân dân có thẩm quyền." Đánh giá hiệu lực của thỏa thuận '
             'trọng tài và xác định cơ quan có thẩm quyền khi một bên nộp đơn khởi kiện ra Tòa án.')
        ld = luat_nen.chu_de_luat(q)
        self.assertIn("lttm", ld)
        self.assertIn("nq_tt", ld)
        self.assertIn(18, luat_nen.dieu_nen(q, "lttm"))
        self.assertIn(4, luat_nen.dieu_nen(q, "nq_tt"))


class LenhTaoFileRoRang(unittest.TestCase):
    CAU_44 = ("Công ty TNHH 2 thành viên (Thành viên A nắm 60%, Thành viên B kiêm Giám đốc/Đại diện "
              "pháp luật nắm 40%). Thành viên B không chịu triệu tập họp, không ký hồ sơ thay đổi "
              "Người đại diện theo pháp luật sang cho A. Xây dựng quy trình triệu tập họp Hội đồng "
              "thành viên hợp lệ và bộ hồ sơ đăng ký thay đổi Người đại diện theo pháp luật nộp lên "
              "Phòng Đăng ký kinh doanh mà không cần chữ ký của Người đại diện cũ.")

    def test_cau_tinh_huong_nhac_bo_ho_so_khong_phai_lenh(self):
        self.assertIsNone(df.detect_request(self.CAU_44))
        self.assertIsNone(df.detect_request(
            "Người đại diện theo pháp luật vắng mặt thì bộ hồ sơ thay đổi gồm những gì"))

    def test_lenh_o_cau_sau_van_nhan(self):
        for q in ("Khách Minh vừa ký hợp đồng thuê nhà. Hãy điền bộ mẫu Thuê nhà cho khách",
                  "Thông tin khách ở trên. Tạo bộ hồ sơ thành lập công ty cho khách"):
            with self.subTest(q=q):
                self.assertIsNotNone(df.detect_request(q))


if __name__ == "__main__":
    unittest.main()
