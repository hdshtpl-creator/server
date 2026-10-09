"""Lọc nguồn câu hỏi luật — sửa theo lượt soát 40 kịch bản ngày 07/10/2026.

Ba nguyên nhân làm điều cần dẫn không tới được model: cùng một điều đứng hai
lần (luật gốc + văn bản hợp nhất), văn bản địa phương chen vào câu hỏi luật
chung, và bảng luật nền thiếu chủ đề / còn trỏ Luật Đầu tư đã hết hiệu lực.
Test thuần, không CSDL, không mạng.
"""
import unittest

from app import luat_nen, rag


def _d(doc, nhan, so="59/2020/QH14", noi_dung="…"):
    return {"document_id": doc, "doc_type": "law", "so_hieu": so,
            "section_title": nhan, "content": noi_dung}


GOC = "Luật Doanh nghiệp số 59/2020/QH14 — Chương IX — Điều {}"
HN = "Luật Doanh nghiệp số 59/2020/QH14 (văn bản hợp nhất 67/VBHN-VPQH) — Chương IX — Điều {}"


class KhuTrungLuatGocVaHopNhat(unittest.TestCase):
    def test_moi_dieu_mot_lan_uu_tien_ban_hop_nhat_giu_thu_hang(self):
        chunks = [
            _d(42920, GOC.format(202)),
            _d(427, HN.format(202), so="67/VBHN-VPQH"),
            _d(42920, GOC.format(203)),
            _d(427, HN.format(204) + " — phần 1/2", so="67/VBHN-VPQH"),
            _d(42920, GOC.format(204)),
            _d(427, HN.format(204) + " — phần 2/2", so="67/VBHN-VPQH"),
        ]
        out = rag.bo_ban_trung_so_hieu(chunks)
        self.assertEqual([(c["document_id"], rag.luat_nen.dieu_cua_doan(c)) for c in out],
                         [(427, 202), (42920, 203), (427, 204), (427, 204)])

    def test_bo_luat_va_luat_cung_ten_la_mot(self):
        chunks = [_d(35869, "Bộ luật Lao động số 45/2019/QH14 — Chương II — Điều 25", so="45/2019/QH14"),
                  _d(42934, "Luật Lao động số 45/2019/QH14 — Chương II — Điều 25", so="45/2019/QH14")]
        self.assertEqual([c["document_id"] for c in rag.bo_ban_trung_so_hieu(chunks)], [35869])

    def test_cung_so_hieu_khac_van_ban_khong_gop(self):
        # 91/2015/QH13 vừa là Bộ luật Dân sự vừa là Nghị quyết giám sát của Quốc hội.
        chunks = [_d(399, "Bộ luật Dân sự số 91/2015/QH13 — Phần thứ nhất — Điều 3", so="91/2015/QH13"),
                  _d(100776, "Nghị quyết số 91/2015/QH13 — Điều 3", so="91/2015/QH13")]
        self.assertEqual(len(rag.bo_ban_trung_so_hieu(chunks)), 2)

    def test_hop_nhat_cua_luat_khac_cung_so_vbhn_khong_gop(self):
        # 11/VBHN-VPQH là hợp nhất của CẢ Luật SHTT lẫn BLTTDS.
        chunks = [_d(35866, "Luật Sở hữu trí tuệ số 50/2005/QH11 (văn bản hợp nhất 11/VBHN-VPQH) — Điều 142",
                     so="11/VBHN-VPQH"),
                  _d(102628, "Bộ luật Tố tụng dân sự số 92/2015/QH13 (văn bản hợp nhất 11/VBHN-VPQH) — Điều 142",
                     so="11/VBHN-VPQH")]
        self.assertEqual(len(rag.bo_ban_trung_so_hieu(chunks)), 2)

    def test_doan_khong_phai_luat_giu_nguyen(self):
        chunks = [{"document_id": 7, "doc_type": "contract", "content": "HĐ"},
                  _d(427, HN.format(47), so="67/VBHN-VPQH")]
        self.assertEqual(len(rag.bo_ban_trung_so_hieu(chunks)), 2)


class VanBanDiaPhuong(unittest.TestCase):
    UB = {"document_id": 5, "doc_type": "law", "so_hieu": "1068/1998/QĐ-UB",
          "section_title": "Quyết định Của ubnd tỉnh nghệ an số 1068/1998/QĐ-UB — Điều 15"}
    UB_KHONG_SO = {"document_id": 6, "doc_type": "law", "so_hieu": "",
                   "section_title": "Quyết định của Ủy ban nhân dân tỉnh Bình Dương — Điều 2"}
    LUAT = _d(427, HN.format(47), so="67/VBHN-VPQH")
    BAN_AN = {"document_id": 9, "doc_type": "ban_an", "so_hieu": "",
              "section_title": "Bản án của TAND tỉnh Nghệ An"}

    def test_cau_luat_chung_bo_van_ban_dia_phuong(self):
        giu, n = rag.bo_van_ban_dia_phuong(
            [self.UB, self.LUAT, self.UB_KHONG_SO, self.BAN_AN],
            "Thành viên góp vốn bằng quyền sử dụng đất chưa xong thủ tục thì sao?")
        self.assertEqual(n, 2)
        self.assertEqual([c["document_id"] for c in giu], [427, 9])

    def test_cau_co_dia_phuong_giu_nguyen(self):
        for q in ("Thẩm quyền của UBND cấp tỉnh khi chấp thuận chủ trương đầu tư?",
                  "Giá đất ở Nghệ An năm 2026", "Thủ tục tại TP HCM",
                  "Quy định của tỉnh về hạn mức đất ở"):
            giu, n = rag.bo_van_ban_dia_phuong([self.UB, self.LUAT], q)
            self.assertEqual(n, 0, q)

    def test_chu_khong_dau_khong_bat_nham(self):
        # "phương án", "quản lý", "xã hội" không phải dấu hiệu địa phương.
        self.assertFalse(rag._cau_hoi_dia_phuong(
            "Phương án sử dụng lao động và quản lý bảo hiểm xã hội"))


class LuatNen0710(unittest.TestCase):
    def test_luat_dau_tu_tro_ban_2025(self):
        self.assertEqual(luat_nen.LUAT["ldt"][0], ("143/2025/QH15",))

    def test_dieu_nen_cac_cau_truot_07_10(self):
        cases = [
            ("Công ty TNHH 2 thành viên, thành viên cam kết góp vốn bằng quyền sử dụng đất nhưng chưa hoàn tất thủ tục chuyển quyền sở hữu", "ldn", 35),
            ("Công ty Cổ phần muốn chuyển đổi thành Công ty TNHH 2 TV", "ldn", 204),
            ("Đặt tên doanh nghiệp trùng hoặc gây nhầm lẫn với công ty khác", "ldn", 41),
            ("Công chức có được thành lập doanh nghiệp không?", "ldn", 17),
            ("Điều kiện tiến hành họp Hội đồng thành viên lần hai", "ldn", 58),
            ("Điều kiện thông qua nghị quyết Đại hội đồng cổ đông", "ldn", 148),
            ("Yêu cầu phong tỏa tài khoản bị đơn tại ngân hàng", "blttds", 124),
            ("Thẩm định tư cách bị đơn khi khởi kiện chi nhánh", "blttds", 68),
            ("Chi nhánh của công ty có phải pháp nhân không?", "blds", 84),
            ("Nhà cung cấp viện dẫn biến động giá nguyên vật liệu", "blds", 420),
            ("Nhà cung cấp tuyên bố bất khả kháng để từ chối giao hàng", "ltm", 294),
            ("Chủ sở hữu nhãn hiệu cấp quyền sử dụng nhãn hiệu (Li-xăng không độc quyền)", "shtt", 142),
            ("Nhà đầu tư Hàn Quốc muốn mua lại 51% vốn góp của công ty Việt Nam", "ldt", 21),
            ("Thẩm quyền chấp thuận chủ trương đầu tư dự án khu nghỉ dưỡng", "ldt", 25),
            ("Nhà đầu tư muốn điều chỉnh tăng vốn và giãn tiến độ thực hiện dự án", "ldt", 33),
            ("Chuyển nhượng toàn bộ dự án đầu tư cho doanh nghiệp khác", "ldt", 34),
        ]
        for q, khoa, dieu in cases:
            self.assertIn(dieu, luat_nen.dieu_nen(q, khoa), q)

    def test_cum_dac_trung_thang_cum_chung_chung(self):
        q = ("Doanh nghiệp trong nước xin cấp phép dự án khu nghỉ dưỡng tại Phú Quốc, chuyển mục đích "
             "sử dụng đất rừng sang đất thương mại dịch vụ. Xác định thẩm quyền chấp thuận chủ "
             "trương đầu tư và hình thức lựa chọn nhà đầu tư.")
        self.assertIn("ldt", luat_nen.chu_de_luat(q))

    def test_ba_bo_luat_mot_cau(self):
        q = ("Nhà cung cấp viện dẫn gián đoạn chuỗi cung ứng để tuyên bố sự kiện bất khả kháng nhằm "
             "từ chối giao hàng và không chịu phạt hợp đồng.")
        ld = luat_nen.chu_de_luat(q)
        self.assertIn("ltm", ld)
        self.assertIn("blds", ld)


if __name__ == "__main__":
    unittest.main()
