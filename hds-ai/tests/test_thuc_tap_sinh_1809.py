"""
Kiểm thử vai THỰC TẬP SINH LUẬT 18/09/2026 — chạy thật trên máy chủ với tài
khoản trợ lý, mỗi bài ở đây là một lỗi đã nhìn thấy bằng mắt rồi mới sửa.

Chay: python -m unittest tests.test_thuc_tap_sinh_1809 -v
"""
import unittest
from unittest import mock

from app import chat_draft, doc_factory, rag


class SoanHopDongTuChatTests(unittest.TestCase):
    """"Soạn hợp đồng dịch vụ … GIỮA A VÀ B" phải thành BẢN NHÁP (sửa / duyệt /
    xuất Word), không phải in hợp đồng ra khung chat rồi thôi."""

    CAU = ("Soạn hợp đồng dịch vụ tư vấn pháp lý giữa Công ty Luật TNHH HDS và "
           "Công ty Cổ phần Khoa học Dữ liệu FOXAI (MST 0109998877), phí dịch vụ "
           "120 triệu đồng, thanh toán 2 đợt 50%/50%, thời hạn 3 tháng.")

    def test_nhan_ra_lenh_soan_hop_dong(self):
        req = chat_draft.detect_request(self.CAU)
        self.assertIsNotNone(req)
        self.assertTrue(req.get("tu_do"))
        self.assertEqual(req["kind"], "hop dong dich vu")
        # Không được giẫm lên luồng "tạo BỘ file".
        self.assertIsNone(doc_factory.detect_request(self.CAU))

    def test_cau_hoi_cach_soan_van_la_tra_cuu(self):
        for q in ["tạo hợp đồng lao động cho người lao động cần điều kiện gì?",
                  "soạn hợp đồng dịch vụ cần những điều khoản nào",
                  "hợp đồng dịch vụ có bắt buộc phải có phụ lục không?"]:
            with self.subTest(q=q):
                self.assertIsNone(chat_draft.detect_request(q))

    def test_hop_dong_co_khung_the_thuc(self):
        muc = chat_draft.muc_bat_buoc("hop dong dich vu")
        self.assertIn("Các bên ký kết", muc)
        self.assertTrue(any("Phạt vi phạm" in m for m in muc))


class TenCongTyKhongPhaiDaoLuatTests(unittest.TestCase):
    """"Công ty Luật TNHH HDS" từng bị đọc thành đạo luật "Luật TNHH HDS" và bot
    mở đầu bằng "⚠ Kho tài liệu chưa có: Luật TNHH HDS"."""

    def test_cong_ty_luat_bi_bo_qua(self):
        nhac = rag._van_ban_nhac_trong_cau_hoi(
            "Soạn hợp đồng giữa Công ty Luật TNHH HDS và Công ty Cổ phần FOXAI")
        self.assertEqual(nhac, [])
        self.assertEqual(rag._van_ban_nhac_trong_cau_hoi(
            "Văn phòng luật sư Minh có được nhận uỷ quyền không"), [])

    def test_dao_luat_that_van_nhan(self):
        nhac = rag._van_ban_nhac_trong_cau_hoi(
            "Theo Luật Doanh nghiệp 2020, thời hạn góp vốn là bao lâu?")
        self.assertEqual(len(nhac), 1)
        self.assertEqual(nhac[0]["ten"], "doanh nghiep")
        self.assertEqual(nhac[0]["nam"], "2020")


class QuyenMoTaiLieuTrongChatTests(unittest.TestCase):
    """Trợ lý không được mở hồ sơ nhân sự nhưng chat vẫn trích nguyên văn CCCD
    của nhân viên trong panel nguồn — chốt mới: không mở được thì không đọc."""

    RULES = {("tro_ly", "*", "law"): True, ("tro_ly", "*", "ho_so_ns"): False,
             ("tro_ly", "*", "ho_so_kh"): False}
    CHUNKS = [
        {"chunk_id": 1, "document_id": 10, "title": "Luật Doanh nghiệp", "doc_type": "law",
         "access_level": "public", "department_id": None, "client_id": None},
        {"chunk_id": 2, "document_id": 11, "title": "Ngân — CCCD", "doc_type": "ho_so_ns",
         "access_level": "internal", "department_id": None, "client_id": None},
        {"chunk_id": 3, "document_id": 12, "title": "Tờ trình 285", "doc_type": "ho_so_kh",
         "access_level": "client", "department_id": None, "client_id": 172},
        # Đoạn không mang access_level (nguồn khác) — giữ nguyên, không đoán.
        {"chunk_id": 4, "document_id": 13, "title": "Ghi chú", "doc_type": "other"},
    ]

    def test_tro_ly_bi_khoa_ho_so_ns_va_ho_so_khach(self):
        ok, khoa = rag.loc_theo_quyen_mo(self.CHUNKS, "tro_ly", [1], False,
                                         dept_codes=["htpl-tvtx"], rules=self.RULES)
        self.assertEqual([c["chunk_id"] for c in ok], [1, 4])
        self.assertEqual([c["chunk_id"] for c in khoa], [2, 3])
        ten = rag._ten_khoa(khoa)
        self.assertEqual(len(ten), 2)
        # Tên bị CHE, không lộ "Ngân — CCCD".
        self.assertFalse(any("CCCD" in t or "Ngân" in t for t in ten))

    def test_ban_quan_tri_thay_het(self):
        ok, khoa = rag.loc_theo_quyen_mo(self.CHUNKS, "ban_qt", [], True, rules=self.RULES)
        self.assertEqual(len(ok), 4)
        self.assertEqual(khoa, [])

    def test_footer_noi_co_tai_lieu_bi_khoa(self):
        ra = rag._canh_bao_khoa("Trả lời.", ["[Hồ sơ nhân sự] 🔒 Tài khoản chưa có quyền xem"])
        self.assertIn("🔒", ra)
        self.assertIn("chưa được mở", ra)
        self.assertEqual(rag._canh_bao_khoa("Trả lời.", []), "Trả lời.")


class PhatHienTuDongTests(unittest.TestCase):
    """Chế độ Kiểm tra pháp lý: bộ quy tắc chạy trước model, con số vượt
    ngưỡng phải nằm sẵn trong prompt."""

    HOP_DONG = (
        "HỢP ĐỒNG DỊCH VỤ TƯ VẤN PHÁP LÝ\n"
        "Bên A (Bên sử dụng dịch vụ): CÔNG TY CỔ PHẦN FOXAI. Bên B (Bên cung cấp dịch vụ): "
        "CÔNG TY LUẬT TNHH HDS.\n"
        "Điều 1. Nội dung dịch vụ: tư vấn thủ tục đăng ký doanh nghiệp.\n"
        "Điều 2. Phí dịch vụ: 120.000.000 đồng. Chậm thanh toán chịu lãi 3%/tháng.\n"
        "Điều 3. Phạt vi phạm: bên vi phạm chịu phạt 20% giá trị hợp đồng.\n"
        "Điều 4. Bên A không được đơn phương chấm dứt hợp đồng trong mọi trường hợp; "
        "Bên B có quyền chấm dứt bất kỳ lúc nào mà không cần báo trước.\n"
        "Điều 5. Bảo mật: Bên B được phép sử dụng thông tin của Bên A cho mục đích "
        "quảng bá mà không cần chấp thuận.\n"
        "Điều 7. Hợp đồng có hiệu lực kể từ ngày ký, không cần chữ ký của người đại "
        "diện theo pháp luật Bên A.\n")

    def test_bat_duoc_lai_phat_va_dieu_khoan_mot_chieu(self):
        with mock.patch("app.template_fill._temp_texts",
                        return_value=[("HD.docx", self.HOP_DONG)]):
            khoi = rag.phat_hien_tu_dong_tu_dinh_kem(conversation_id=1, use_temp=True)
        self.assertIn("Hợp đồng dịch vụ", khoi)
        self.assertIn("Lãi chậm thanh toán", khoi)          # 3%/tháng > 1,67%
        self.assertIn("Mức phạt vi phạm", khoi)              # 20% > 8%
        self.assertIn("Quyền chấm dứt một chiều", khoi)
        self.assertIn("không cần chấp thuận", khoi)
        self.assertIn("Hiệu lực không cần chữ ký", khoi)

    def test_khong_dinh_kem_thi_rong(self):
        self.assertEqual(rag.phat_hien_tu_dong_tu_dinh_kem(None, True), "")
        self.assertEqual(rag.phat_hien_tu_dong_tu_dinh_kem(1, False), "")

    def test_prompt_mang_khoi_phat_hien(self):
        prompt = rag.build_prompt("rà soát", [], phat_hien_tu_dong="- CẢNH BÁO thử")
        self.assertIn("PHÁT HIỆN TỰ ĐỘNG TỪ BỘ QUY TẮC", prompt)
        self.assertIn("CẢNH BÁO thử", prompt)


class RaSoatChiCoMatTests(unittest.TestCase):
    def test_muc_co_mat_khong_giong_dat_that(self):
        from app import ra_soat_rui_ro
        kq = ra_soat_rui_ro.ra_soat(PhatHienTuDongTests.HOP_DONG, loai="hop_dong_dich_vu")
        theo_ma = {m["ma"]: m for m in kq["muc"]}
        self.assertTrue(theo_ma["bao_mat"].get("chi_co_mat"))
        self.assertIn("chưa đánh giá nội dung", theo_ma["bao_mat"]["giai_thich"])
        self.assertEqual(theo_ma["dung_thong_tin_khong_chap_thuan"]["trang_thai"], "canh_bao")
        self.assertEqual(theo_ma["mot_chieu_cham_dut"]["trang_thai"], "canh_bao")
        self.assertEqual(theo_ma["hieu_luc_khong_chu_ky"]["trang_thai"], "canh_bao")
        self.assertEqual(theo_ma["lai_cham_thang"]["trang_thai"], "canh_bao")


if __name__ == "__main__":
    unittest.main()
