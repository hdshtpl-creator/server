"""Sửa lỗi lộ ra khi đo bộ câu hỏi mẫu 05/10/2026 (deploy/kiem-thu/BO_CAU_HOI_*).

Mỗi lỗi ở đây đều KHÔNG báo lỗi gì — bot vẫn trả lời, chỉ là trả lời sai nguồn:
mẫu SEC bị luật VN đẩy xuống, luật cũ mang nhãn còn hiệu lực, câu luật lao
động bị trả danh bạ nhân sự… Test thuần, không CSDL, không mạng.
"""
import unittest
from unittest import mock

from app import company_context as cc
from app import luat_nen, rag, van_ban


class NhanDienYDinhTests(unittest.TestCase):
    def test_nguoi_lao_dong_dung_mot_minh_khong_phai_danh_ba(self):
        self.assertIsNone(cc.infer_intent(
            "Thỏa thuận bảo vệ bí mật kinh doanh với người lao động cần có những nội dung gì?"))

    def test_hoi_nguoi_cua_cong_ty_van_la_nhan_su(self):
        self.assertEqual(cc.infer_intent("Công ty có bao nhiêu người lao động?"), "staff_directory")
        self.assertEqual(cc.infer_intent("Danh sách người lao động của HDS"), "staff_directory")

    def test_kho_du_lieu_dem_ban_an_tra_thang(self):
        self.assertEqual(cc.infer_intent("Kho dữ liệu đang có bao nhiêu tài liệu bản án?"),
                         "doc_inventory")

    def test_hoi_mot_loai_mau_cu_the_khong_liet_ke_ca_kho(self):
        self.assertIsNone(cc.infer_intent(
            "Trong kho có những mẫu hợp đồng thuê bất động sản bằng tiếng Anh nào?"))
        self.assertEqual(cc.infer_intent("Kho đang có bao nhiêu mẫu hợp đồng?"), "doc_inventory")

    def test_liet_ke_kho_co_tran(self):
        self.assertGreater(cc.INVENTORY_LIST_MAX, 0)


class DinhTuyenMauTests(unittest.TestCase):
    def test_cau_mau_dieu_khoan_va_tieng_anh_vao_ngan_mau(self):
        for q in ("Cho tôi một mẫu điều khoản bất khả kháng trong hợp đồng Hoa Kỳ",
                  "Điều khoản tiếng Anh về bảo mật",
                  "Find a governing law clause with a jury trial waiver",
                  "What conditions precedent apply in the US contract templates?",
                  "Giải thích thuật ngữ indemnify and hold harmless, waiver of jury trial"):
            self.assertIn("mau_hd", cc.detect_doc_scopes(q), q)

    def test_cau_luat_thuong_khong_bi_keo_sang_ngan_mau(self):
        self.assertNotIn("mau_hd", cc.detect_doc_scopes("Thời hiệu khởi kiện hợp đồng là bao lâu?"))


class LuatNenTests(unittest.TestCase):
    def test_chu_de_ra_dung_bo_luat(self):
        self.assertEqual(luat_nen.chu_de_luat(
            "Người lao động muốn nghỉ việc phải báo trước bao nhiêu ngày?")[0], "blld")
        self.assertIn("shtt", luat_nen.chu_de_luat("Nhãn hiệu có hiệu lực bao lâu?"))
        self.assertIn("ldn", luat_nen.chu_de_luat("Trình tự giải thể doanh nghiệp tự nguyện"))
        self.assertIn("blttds", luat_nen.chu_de_luat("Đơn khởi kiện cần nội dung gì?"))
        self.assertIn("ltm", luat_nen.chu_de_luat(
            "So sánh mức phạt chậm trả với giới hạn phạt vi phạm theo pháp luật Việt Nam"))
        self.assertEqual(luat_nen.chu_de_luat("Hôm nay trời đẹp"), [])

    def test_dieu_nen_cac_cau_tung_truot(self):
        """Bảy câu trượt Điều ở lượt đo 05/10/2026."""
        cases = [
            ("Người lao động làm hợp đồng không xác định thời hạn muốn nghỉ việc thì phải báo trước bao nhiêu ngày?", "blld", 35),
            ("Giấy chứng nhận đăng ký nhãn hiệu có hiệu lực bao lâu?", "shtt", 93),
            ("Trình tự giải thể doanh nghiệp tự nguyện gồm những bước nào?", "ldn", 208),
            ("Muốn khởi kiện đòi nợ thì đơn khởi kiện cần những nội dung gì?", "blttds", 189),
            ("Nhãn hiệu SUNMILK có đăng ký được không, nếu đã có nhãn hiệu SUN MILK?", "shtt", 74),
            ("Thời hạn góp vốn khi thành lập công ty TNHH là bao lâu?", "ldn", 47),
            ("Người lao động nghỉ không phép 3 ngày, công ty ra quyết định sa thải.", "blld", 125),
            ('Có đăng ký được nhãn hiệu chỉ gồm chữ "NGON" cho dịch vụ nhà hàng không?', "shtt", 74),
        ]
        for q, khoa, dieu in cases:
            self.assertIn(dieu, luat_nen.dieu_nen(q, khoa), q)

    def test_chon_doan_dieu_nen_dung_truoc(self):
        ds = [{"chunk_id": 1, "section_title": "Bộ luật Lao động — Điều 29", "score": 0.9},
              {"chunk_id": 2, "section_title": "Bộ luật Lao động — Điều 35", "score": 0.5},
              {"chunk_id": 3, "content": "[Bộ luật Lao động — Điều 125 — phần 2/3] …", "score": 0.4},
              {"chunk_id": 4, "section_title": "Bộ luật Lao động — Điều 20", "score": 0.8}]
        out = luat_nen.chon_doan(ds, [125, 35], them=1)
        # điều nền trước (điểm cao trước), rồi đoạn khớp nhất còn lại
        self.assertEqual([c["chunk_id"] for c in out], [2, 3, 1])

    def test_doc_ids_loi_csdl_thi_rong(self):
        luat_nen._cache.update({"at": 0.0, "ids": {}})

        def hong():
            raise RuntimeError("không có CSDL")
        self.assertEqual(luat_nen.doc_ids(hong), {})


class TenCongTyTrongCauHoiTests(unittest.TestCase):
    def test_lay_ten_in_hoa_bo_viet_tat_luat(self):
        self.assertEqual(rag.ten_rieng_in_hoa(
            "Dịch điều khoản Force Majeure trong hợp đồng thuê của BOXABL theo BLDS"), ["BOXABL"])
        self.assertEqual(rag.ten_rieng_in_hoa(
            "So sánh phạt chậm trả của APPLIED OPTOELECTRONICS với LTM"),
            ["APPLIED", "OPTOELECTRONICS"])
        self.assertEqual(rag.ten_rieng_in_hoa("Hợp đồng NDA của công ty TNHH"), [])

    def test_luat_nuoc_ngoai_khong_phai_van_ban_trong_kho(self):
        self.assertEqual(rag._van_ban_nhac_trong_cau_hoi(
            "Trong kho có mẫu hợp đồng tiếng Anh theo luật Anh (English law) hoặc luật Singapore không?"), [])
        ten = [v["ten"] for v in rag._van_ban_nhac_trong_cau_hoi("Theo Luật Hàng không thì sao?")]
        self.assertEqual(ten, ["hang khong"])
        ten = [v["ten"] for v in rag._van_ban_nhac_trong_cau_hoi("Kho có Luật Thương mại không?")]
        self.assertEqual(ten, ["thuong mai"])

    def test_cau_hoi_hop_dong_nuoc_ngoai(self):
        f = lambda q: bool(rag._RE_HOI_HOP_DONG_NUOC_NGOAI.search(rag._fold_text(q)))
        self.assertTrue(f("Mẫu hợp đồng thuê bất động sản bằng tiếng Anh"))
        self.assertTrue(f("Mẫu hợp đồng Mỹ về bảo mật"))
        self.assertFalse(f("Mẫu hợp đồng mua bán mỹ phẩm"))
        self.assertFalse(f("Mẫu hợp đồng dịch vụ thẩm mỹ"))

    def test_loai_hop_dong_sec_theo_cau_hoi(self):
        self.assertEqual(rag.loai_hop_dong_sec(
            "Trong kho có những mẫu hợp đồng thuê bất động sản bằng tiếng Anh nào?"),
            ["Hop_dong_day_du/Thue - Bat dong san"])
        self.assertEqual(rag.loai_hop_dong_sec("Mẫu hợp đồng li-xăng phần mềm của Mỹ"),
                         ["Hop_dong_day_du/Cap phep - Li-xang"])
        self.assertEqual(rag.loai_hop_dong_sec("Điều khoản luật áp dụng trong hợp đồng Mỹ"), [])

    def test_chon_ben_ky_khop_nhieu_chu_nhat(self):
        rows = [(1, "APPLIED OPTOELECTRONICS, INC"), (2, "APPLIED OPTOELECTRONICS, INC"),
                (3, "Applied Materials Inc"), (4, "Applied Digital Corp")]
        self.assertEqual(rag.chon_ben_ky(rows, ["APPLIED", "OPTOELECTRONICS"]), [1, 2])

    def test_chu_chung_chung_khop_qua_nhieu_ben_ky_thi_bo(self):
        rows = [(i, f"GLOBAL {i} Inc") for i in range(10)]
        self.assertEqual(rag.chon_ben_ky(rows, ["GLOBAL"]), [])


class KhopTenVanBanTests(unittest.TestCase):
    def test_khop_chat_thang_khop_long_cung_nam(self):
        nhac = rag._van_ban_nhac_trong_cau_hoi("Theo Luật Doanh nghiệp 2014, thời hạn góp vốn là bao lâu?")
        docs = [{"id": 1, "so_hieu": "69/2014/QH13", "loai_van_ban": "Luật",
                 "trich_yeu": "Quản lý, sử dụng vốn nhà nước đầu tư vào sản xuất, kinh doanh tại doanh nghiệp",
                 "title": "69-2014-QH13", "ngay_ban_hanh": None},
                {"id": 2, "so_hieu": "59/2020/QH14", "loai_van_ban": "Luật",
                 "trich_yeu": "Doanh nghiệp", "title": "Luật số 59-2020-QH14", "ngay_ban_hanh": None}]
        k = rag._khop_van_ban_nhac_chi_tiet(nhac, docs)
        self.assertEqual(k[0]["ids"], [2])


class BocQuanHeTests(unittest.TestCase):
    def test_het_hieu_luc_ke_tu(self):
        q = van_ban.boc_quan_he("Bộ luật dân sự số 33/2005/QH11 hết hiệu lực kể từ ngày Bộ luật này có hiệu lực.",
                                so_hieu_minh="91/2015/QH13")
        self.assertEqual([(x["loai"], x["so_hieu_dich"]) for x in q], [("thay_the", "33/2005/QH11")])

    def test_chu_ngu_dau_cau_khong_phai_luat_sua_doi(self):
        ds = ", ".join(f"Luật số {i:02d}/2022/QH15" for i in range(1, 40))
        t = (f"4. Luật Đầu tư số 61/2020/QH14 đã được sửa đổi, bổ sung một số điều theo Luật số "
             f"72/2020/QH14, {ds} hết hiệu lực kể từ ngày Luật này có hiệu lực thi hành.")
        q = van_ban.boc_quan_he(t, so_hieu_minh="143/2025/QH15")
        self.assertEqual([x["so_hieu_dich"] for x in q], ["61/2020/QH14"])

    def test_moc_thoi_gian_khong_phai_khai_tu(self):
        q = van_ban.boc_quan_he("Luật này có hiệu lực thi hành từ ngày Nghị quyết số 61/2022/QH15 hết hiệu lực.",
                                so_hieu_minh="31/2024/QH15")
        self.assertEqual(q, [])

    def test_ke_tu_ngay_van_ban_nay(self):
        q = van_ban.boc_quan_he("Kể từ ngày Thông tư này có hiệu lực, Quyết định số 12/2005/QĐ-BTC hết hiệu lực.",
                                so_hieu_minh="90/2005/TT-BTC")
        self.assertEqual([x["so_hieu_dich"] for x in q], ["12/2005/QĐ-BTC"])

    def test_danh_sach_sau_dau_hai_cham(self):
        q = van_ban.boc_quan_he("Các Nghị định sau đây hết hiệu lực kể từ ngày Nghị định này có hiệu lực: "
                                "a) Nghị định số 01/2021/NĐ-CP; b) Nghị định số 122/2020/NĐ-CP.",
                                so_hieu_minh="168/2025/NĐ-CP")
        self.assertEqual(sorted(x["so_hieu_dich"] for x in q), ["01/2021/NĐ-CP", "122/2020/NĐ-CP"])

    def test_danh_sach_dai_doc_den_muc_cuoi(self):
        """NĐ 145/2020 khai tử 9 nghị định, NĐ 27/2014 ở mục h) — xa quá 600 ký tự."""
        muc = "; ".join(
            f"{c}) Nghị định số {i:02d}/2014/NĐ-CP ngày 07 tháng 4 năm 2014 của Chính phủ quy định "
            f"chi tiết thi hành một số điều của Bộ luật Lao động số 10/2012/QH13 về lĩnh vực {i}"
            for i, c in zip(range(20, 29), "abcdeghik"))
        t = ("2. Các Nghị định sau đây hết hiệu lực kể từ ngày Nghị định này có hiệu lực thi hành: "
             + muc + ".\n\nĐiều 125. Trách nhiệm thi hành")
        q = van_ban.boc_quan_he(t, so_hieu_minh="145/2020/NĐ-CP")
        het = [x["so_hieu_dich"] for x in q if x["loai"] == "thay_the"]
        self.assertIn("27/2014/NĐ-CP", het)
        self.assertEqual(len(het), 9)
        self.assertNotIn("10/2012/QH13", het)

    def test_cau_chuong_trinh_khong_phai_bai_bo(self):
        t = ("Chính phủ tổ chức rà soát để bãi bỏ, sửa đổi, bổ sung, ban hành văn bản mới hoặc đề nghị "
             "Quốc hội bãi bỏ, sửa đổi, bổ sung hoặc ban hành văn bản mới phù hợp với quy định của "
             "Bộ luật tố tụng dân sự số 92/2015/QH13.")
        self.assertEqual(van_ban.boc_quan_he(t, so_hieu_minh="103/2015/QH13"), [])

    def test_cap_duoi_khong_khai_tu_cap_tren(self):
        q = van_ban.boc_quan_he("Bãi bỏ Luật Đất đai số 31/2024/QH15 và Quyết định số 07/2014/QĐ-UBND.",
                                so_hieu_minh="115/2025/QĐ-UBND")
        self.assertEqual([x["so_hieu_dich"] for x in q], ["07/2014/QĐ-UBND"])

    def test_van_ban_hop_nhat_khong_khai_tu(self):
        q = van_ban.boc_quan_he("Luật Đầu tư số 61/2020/QH14 hết hiệu lực kể từ ngày 01/3/2026.",
                                so_hieu_minh="06/VBHN-VPQH")
        self.assertEqual(q, [])

    def test_cap_van_ban(self):
        self.assertEqual(van_ban.cap_van_ban("31/2024/QH15"), 1)
        self.assertEqual(van_ban.cap_van_ban("1037/2006/NQ-UBTVQH11"), 2)
        self.assertEqual(van_ban.cap_van_ban("14/2022/QĐ-TT"), 3)
        self.assertEqual(van_ban.cap_van_ban("18/2012/TT-BGTVT"), 4)
        self.assertEqual(van_ban.cap_van_ban("12/2024/NQ-HĐND"), 5)
        self.assertIsNone(van_ban.cap_van_ban("67/VBHN-VPQH"))


class VanBanCuTests(unittest.TestCase):
    def test_canh_bao_dau_cau_tra_loi(self):
        t = rag._canh_bao_van_ban_cu("Thời hạn góp vốn là 90 ngày [Nguồn 1].", [
            {"hien_thi": "Luật Doanh nghiệp 2014", "so_hieu_cu": "68/2014/QH13",
             "thay_boi": "Luật Doanh nghiệp số 59/2020/QH14"}])
        self.assertTrue(t.startswith("**ℹ Luật Doanh nghiệp 2014 (68/2014/QH13) đã hết hiệu lực"))
        self.assertIn("90 ngày", t)

    def test_khong_co_gi_thi_giu_nguyen(self):
        self.assertEqual(rag._canh_bao_van_ban_cu("abc", []), "abc")


class TaiLieuCongKhaiTests(unittest.TestCase):
    def test_tro_ly_mo_duoc_tai_lieu_sec_nhung_khong_mo_mau_hds(self):
        rules = {("tro_ly", "*", "mau_hd"): False}
        with mock.patch.object(rag, "tai_lieu_cong_khai_ids", return_value=frozenset({7})):
            sec = {"id": 7, "access_level": "internal", "doc_type": "mau_hd"}
            hds = {"id": 8, "access_level": "internal", "doc_type": "mau_hd"}
            self.assertTrue(rag.can_open_doc("tro_ly", [], False, sec, rules=rules, dept_codes=[]))
            self.assertFalse(rag.can_open_doc("tro_ly", [], False, hds, rules=rules, dept_codes=[]))
            # chunk từ retrieve mang document_id thay vì id
            self.assertTrue(rag.can_open_doc("tro_ly", [], False,
                                             {"document_id": 7, "access_level": "internal",
                                              "doc_type": "mau_hd"}, rules=rules, dept_codes=[]))

    def test_chat_loc_quyen_mo_ap_ngoai_le_va_chan_doan_lien_ke(self):
        """Đo 05/10 bằng vai trợ lý: đoạn LIỀN KỀ (không mang access_level) của
        mẫu HĐ HDS bị khoá vẫn lọt vào nguồn; còn SEC chỉ lọt nhờ đúng lỗ đó."""
        rules = {("tro_ly", "*", "mau_hd"): False}
        sec = {"chunk_id": 1, "document_id": 7, "doc_type": "mau_hd", "access_level": "internal",
               "department_id": None}
        hds = {"chunk_id": 2, "document_id": 8, "doc_type": "mau_hd", "access_level": "internal",
               "department_id": None}
        lien_ke = {"chunk_id": 3, "document_id": 8, "doc_type": "mau_hd", "is_neighbour": True}
        dinh_kem = {"chunk_id": "t1", "content": "file người dùng gửi kèm"}
        with mock.patch.object(rag, "tai_lieu_cong_khai_ids", return_value=frozenset({7})):
            ok, khoa = rag.loc_theo_quyen_mo([sec, hds, lien_ke, dinh_kem], "tro_ly", [], False,
                                             dept_codes=[], rules=rules)
        self.assertEqual([c["chunk_id"] for c in ok], [1, "t1"])
        self.assertEqual([c["chunk_id"] for c in khoa], [2, 3])

    def test_khach_khong_duoc_mo_vi_ngoai_le_nay(self):
        with mock.patch.object(rag, "tai_lieu_cong_khai_ids", return_value=frozenset({7})):
            self.assertFalse(rag.can_open_doc("client_free", [], False,
                                              {"id": 7, "access_level": "internal",
                                               "doc_type": "mau_hd"}, client_id=3))


if __name__ == "__main__":
    unittest.main()
