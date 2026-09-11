"""Sau khi nạp 25.130 bản án (08/09/2026) chạy thử lộ hai lỗi:

1. Bot chép nguyên mã tải về trong tên file bản án vào câu trả lời
   ("Bản án số 01463_2112066_số 03 ngày 26022026…").
2. Kệ bản án (436.000 đoạn) nuốt hết chỗ của kệ luật (4.300 đoạn): hỏi "theo
   Bộ luật Dân sự 2015" mà 10 nguồn đều là bản án, bot kết luận BLDS không
   quy định hủy bỏ hợp đồng.

Toàn bộ là logic thuần — không chạm CSDL, không gọi model (deploy/update.sh
chạy nguyên bộ test trên máy chủ đang phục vụ).
"""
import unittest

from app import rag, van_ban

TEN_FILE = ("01463_2112066_số 03 ngày 26022026 của Tòa án nhân dân khu vực 1 - "
            "Đồng Nai, tỉnh Đồng Nai (08.05.2026)")
TEN_CHUAN = ("Bản án số 03/2026/KDTM-ST ngày 26/02/2026 của Tòa án nhân dân "
             "khu vực 1 - Đồng Nai, tỉnh Đồng Nai")


class TenHienThiBanAn(unittest.TestCase):
    def test_ten_file_tai_ve_thanh_ten_phap_ly(self):
        self.assertEqual(
            van_ban.ten_hien_thi_ban_an(TEN_FILE, "03/2026/KDTM-ST", "Bản án"),
            TEN_CHUAN)

    def test_so_hieu_dinh_lien_trong_ten_file_duoc_thay_bang_so_hieu_chuan(self):
        ten = ("17205_1254066_số 122023KDTM-PT ngày 26042023 của TAND TP. "
               "Hải Phòng (10.05.2023)")
        self.assertEqual(
            van_ban.ten_hien_thi_ban_an(ten, "12/2023/KDTM-PT", "Bản án"),
            "Bản án số 12/2023/KDTM-PT ngày 26/04/2023 của TAND TP. Hải Phòng")

    def test_khong_co_so_hieu_van_bo_ma_tai_ve_va_ngay_dang(self):
        ten = ("00907_2147675_số 30 ngày 20052026 của Tòa án nhân dân khu vực 5 "
               "- Hà Nội, TP. Hà Nội (03.07.2026)")
        self.assertEqual(
            van_ban.ten_hien_thi_ban_an(ten, None, None),
            "Bản án số 30 ngày 20/05/2026 của Tòa án nhân dân khu vực 5 - "
            "Hà Nội, TP. Hà Nội")

    def test_quyet_dinh_nhan_theo_ky_hieu_du_loai_boc_sai(self):
        # loai_van_ban bóc từ nội dung trúng 'Bộ luật' (dòng căn cứ) — ký hiệu
        # QĐST trong số hiệu mới là sự thật.
        ten = "01076_2138401_số 1 ngày 22052026 của TAND khu vực 11 - Quảng Ngãi"
        self.assertEqual(
            van_ban.ten_hien_thi_ban_an(ten, "01/2026/QĐST-KDTM", "Bộ luật"),
            "Quyết định số 01/2026/QĐST-KDTM ngày 22/05/2026 của TAND khu vực "
            "11 - Quảng Ngãi")

    def test_ten_khong_theo_khuon_giu_nguyen(self):
        ten = "Án lệ số 09/2016/AL về xác định lãi suất nợ quá hạn"
        self.assertEqual(van_ban.ten_hien_thi_ban_an(ten, "09/2016/AL", "Án lệ"), ten)
        self.assertEqual(van_ban.ten_hien_thi_ban_an("", None, None), "")

    def test_loai_ban_an(self):
        self.assertEqual(van_ban.loai_ban_an("55/2023/QĐ-PT", None), "Quyết định")
        self.assertEqual(van_ban.loai_ban_an("31/2025/KDTM-ST", "Bộ luật"), "Bản án")
        self.assertEqual(van_ban.loai_ban_an("09/2016/AL", None), "Án lệ")
        self.assertEqual(van_ban.loai_ban_an(None, "Quyết định"), "Quyết định")

    def test_panel_nguon_va_prompt_dung_ten_phap_ly(self):
        doan = {"chunk_id": 1, "document_id": 7, "title": TEN_FILE,
                "doc_type": "ban_an", "so_hieu": "03/2026/KDTM-ST",
                "loai_van_ban": "Bản án", "score": 0.7, "extraction_status": "warning",
                "content": "Tòa án chấp nhận mức lãi suất 9,55%/năm do nguyên "
                           "đơn yêu cầu vì thấp hơn mức trung bình của ba ngân "
                           "hàng thương mại tại địa phương."}
        self.assertEqual(rag.format_sources([doan])[0]["title"], TEN_CHUAN)
        self.assertEqual(rag._ten_nguon(doan), TEN_CHUAN)
        prompt = rag.build_prompt("lãi chậm trả", [doan], chunk_chars=0, budget=0)
        self.assertIn(f"[Nguồn 1] (bản án) {TEN_CHUAN}", prompt)
        self.assertNotIn("01463_2112066", prompt)

    def test_tai_lieu_khac_giu_nguyen_ten(self):
        doan = {"title": "HĐLĐ Nguyễn Văn A.docx", "doc_type": "ho_so_ns",
                "content": "Hợp đồng lao động ký ngày 01/03/2024 giữa công ty "
                           "và ông Nguyễn Văn A, thời hạn 12 tháng."}
        self.assertEqual(rag._ten_nguon(doan), "HĐLĐ Nguyễn Văn A.docx")
        self.assertEqual(rag.format_sources([doan])[0]["title"], "HĐLĐ Nguyễn Văn A.docx")


class KhopVanBanNhac(unittest.TestCase):
    """Tìm id văn bản luật trong kho ứng với văn bản người hỏi nêu tên."""

    KE = [
        {"id": 399, "so_hieu": "91/2015/QH13", "loai_van_ban": "Bộ luật",
         "trich_yeu": "Dân sự", "title": "Bộ-luật-91-2015-QH13", "ngay_ban_hanh": None},
        {"id": 401, "so_hieu": "67/VBHN-VPQH", "loai_van_ban": "Luật",
         "trich_yeu": "Doanh nghiệp", "title": "Văn-bản-hợp-nhất-67-VBHN-VPQH",
         "ngay_ban_hanh": "2025-06-30"},
        {"id": 402, "so_hieu": "143/2025/QH15", "loai_van_ban": "Luật",
         "trich_yeu": "Đầu tư", "title": "Luật-143-2025-QH15", "ngay_ban_hanh": "2025-12-11"},
        {"id": 403, "so_hieu": "168/2025/NĐ-CP", "loai_van_ban": "Nghị định",
         "trich_yeu": "Về đăng ký doanh nghiệp", "title": "Nghị-định-168-2025-NĐ-CP",
         "ngay_ban_hanh": None},
    ]

    def khop(self, cau):
        return rag._khop_van_ban_nhac(rag._van_ban_nhac_trong_cau_hoi(cau), self.KE)

    def test_blds_2015_theo_ten_va_nam(self):
        self.assertEqual(self.khop("So sánh hủy bỏ hợp đồng và đơn phương chấm dứt "
                                   "thực hiện hợp đồng theo Bộ luật Dân sự 2015"), [399])

    def test_viet_tat(self):
        self.assertEqual(self.khop("Điều 428 BLDS 2015 quy định gì?"), [399])

    def test_bo_luat_to_tung_dan_su_khong_nham_sang_blds(self):
        self.assertEqual(self.khop("Thời hiệu khởi kiện theo Bộ luật Tố tụng Dân sự 2015"), [])

    def test_luat_dn_2020_ra_ban_hop_nhat_khong_mang_nam(self):
        self.assertEqual(self.khop("Điều 47 Luật Doanh nghiệp 2020"), [401])

    def test_kho_chi_co_ban_khac_nam_van_keo_vao(self):
        self.assertEqual(self.khop("Ngành nghề cấm đầu tư theo Luật Đầu tư 2020"), [402])

    def test_theo_so_hieu(self):
        self.assertEqual(self.khop("Hồ sơ đăng ký theo Nghị định 168/2025/NĐ-CP"), [403])
        self.assertEqual(self.khop("Nghị định 13/2023/NĐ-CP về dữ liệu cá nhân"), [])

    def test_khong_neu_van_ban_hoac_ke_rong(self):
        self.assertEqual(self.khop("Phạt vi phạm hợp đồng tối đa bao nhiêu?"), [])
        self.assertEqual(rag._khop_van_ban_nhac(
            rag._van_ban_nhac_trong_cau_hoi("Điều 428 BLDS 2015"), []), [])

    def test_nam_van_ban(self):
        self.assertEqual(rag._nam_van_ban("91/2015/QH13"), "2015")
        self.assertEqual(rag._nam_van_ban("67/VBHN-VPQH", "2025-06-30"), "2025")
        self.assertIsNone(rag._nam_van_ban("67/VBHN-VPQH", None))


class LuotTuKhoaNoiLong(unittest.TestCase):
    """Lượt OR chỉ cho câu ngắn và chỉ giữ từ phân biệt."""

    def test_bo_tu_pho_thong_giu_tu_phan_biet(self):
        self.assertEqual(rag._or_tsquery("Điều 428 BLDS 2015 quy định gì?"),
                         "428 | blds | 2015")
        self.assertEqual(rag._or_tsquery("sơ yếu lí lịch cửa Ngân"),
                         "sơ | yếu | lí | lịch | cửa | ngân")

    def test_cau_dai_khong_chay_or(self):
        self.assertIsNone(rag._or_tsquery(
            "So sánh hủy bỏ hợp đồng và đơn phương chấm dứt thực hiện hợp đồng "
            "theo Bộ luật Dân sự 2015"))
        self.assertIsNone(rag._or_tsquery("hợp đồng theo quy định của luật"))

    def test_khoanh_vao_van_ban_thi_bo_tran_do_dai(self):
        # Trong một văn bản (vài trăm đoạn) OR không còn đắt — Điều 423 "Hủy
        # bỏ hợp đồng" xếp thứ 10 theo vector, từ khoá "hủy bỏ" kéo nó lên.
        self.assertEqual(
            rag._or_tsquery("So sánh hủy bỏ hợp đồng và đơn phương chấm dứt thực "
                            "hiện hợp đồng theo Bộ luật Dân sự 2015", gioi_han=False),
            "so | sánh | hủy | bỏ | đơn | phương | chấm | dứt | dân | sự | 2015")


class DiemTenDieu(unittest.TestCase):
    """Câu hỏi gọi đúng tên điều / số điều thì đoạn luật đó được thưởng điểm."""

    CAU = ("So sánh hủy bỏ hợp đồng và đơn phương chấm dứt thực hiện hợp đồng "
           "theo Bộ luật Dân sự 2015")

    @staticmethod
    def doan(so, ten):
        return {"doc_type": "law",
                "content": f"[Bộ luật Dân sự số 91/2015/QH13 — PHẦN THỨ BA, Chương XV., "
                           f"Mục 7. HỢP ĐỒNG — Điều {so}]\nĐiều {so}. {ten}\n"
                           f"1. Một bên có quyền …"}

    def test_ten_dieu_nam_nguyen_trong_cau(self):
        q = rag._fold(self.CAU)
        self.assertEqual(rag._diem_dieu_luat(self.doan(423, "Hủy bỏ hợp đồng"), q), 1.0)
        self.assertEqual(rag._diem_dieu_luat(
            self.doan(428, "Đơn phương chấm dứt thực hiện hợp đồng"), q), 1.0)

    def test_ten_dieu_dai_hon_cau_khong_thuong(self):
        q = rag._fold(self.CAU)
        self.assertEqual(rag._diem_dieu_luat(
            self.doan(424, "Hủy bỏ hợp đồng do chậm thực hiện nghĩa vụ"), q), 0.0)
        self.assertEqual(rag._diem_dieu_luat(
            self.doan(520, "Đơn phương chấm dứt thực hiện hợp đồng dịch vụ"), q), 0.0)
        self.assertEqual(rag._diem_dieu_luat(self.doan(422, "Chấm dứt hợp đồng"), q), 0.0)

    def test_so_dieu_trong_cau(self):
        q = rag._fold("Điều 428 BLDS 2015 quy định gì?")
        so = set(rag._RE_SO_DIEU_HOI.findall(q))
        self.assertEqual(so, {"428"})
        self.assertEqual(rag._diem_dieu_luat(
            self.doan(428, "Đơn phương chấm dứt thực hiện hợp đồng"), q, so), 1.0)
        self.assertEqual(rag._diem_dieu_luat(self.doan(423, "Hủy bỏ hợp đồng"), q, so), 0.0)

    def test_tieu_de_dinh_lien_khoan_1(self):
        # Đoạn không xuống dòng sau tên điều: tên dừng ở "1." mở khoản.
        d = {"doc_type": "law", "content": "Điều 423. Hủy bỏ hợp đồng 1. Một bên có quyền hủy bỏ"}
        self.assertEqual(rag._diem_dieu_luat(d, rag._fold(self.CAU)), 1.0)

    def test_doan_khong_phai_dieu_luat(self):
        d = {"doc_type": "law", "content": "Căn cứ Bộ luật Dân sự; Quốc hội ban hành…"}
        self.assertEqual(rag._diem_dieu_luat(d, rag._fold(self.CAU)), 0.0)


if __name__ == "__main__":
    unittest.main()
