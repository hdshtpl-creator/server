"""Câu hỏi luật "đang áp dụng" — sửa theo ca 12/10/2026.

"hộ kinh doanh đang được miễn thuế bao nhiêu": bot dẫn Nghị định 96/CP năm
1995, Thông tư 154/2011… trong khi kho có Nghị định 141/2026/NĐ-CP (ngưỡng 1 tỷ
đồng, sửa Nghị định 68/2026/NĐ-CP). Bốn nguyên nhân: câu thuế không được nhận là
câu hỏi luật; nhãn hiệu lực của văn bản cũ sai (văn bản 1995 mang nhãn còn hiệu
lực); văn bản bị sửa vào nguồn mà đoạn sửa đổi thì không; không có luật nền chủ
đề thuế hộ kinh doanh. Test thuần, không CSDL, không mạng.
"""
import unittest
from datetime import date
from unittest import mock

from app import luat_nen, rag

CAU = "hộ kinh doanh đang được miễn thuế bao nhiêu"


def _luat(doc, so, nam=None, diem=0.5, loai="Nghị định", nhan=None, noi_dung="…", **kw):
    c = {"chunk_id": doc * 10, "document_id": doc, "doc_type": "law", "so_hieu": so,
         "loai_van_ban": loai, "ngay_ban_hanh": date(nam, 1, 1) if nam else None,
         "score": diem, "section_title": nhan or f"{loai} số {so}", "content": noi_dung}
    c.update(kw)
    return c


class NhanDienCauHoiThue(unittest.TestCase):
    def test_cau_thue_la_cau_hoi_luat(self):
        self.assertTrue(rag._hoi_ve_phap_luat(CAU))
        self.assertTrue(rag._hoi_ve_phap_luat("lệ phí trước bạ ô tô là bao nhiêu"))

    def test_viet_tat_hkd_mo_ra_ho_kinh_doanh(self):
        q = rag.mo_rong_viet_tat("hkd đang được miễn bao nhiêu")
        self.assertIn("hộ kinh doanh", q)
        self.assertTrue(rag._hoi_ve_phap_luat(q))

    def test_vat_tu_khong_bi_hieu_la_thue(self):
        # So khớp sau khi bỏ dấu: "vật" = "vat" — không được thêm nghĩa thuế.
        self.assertEqual("mua vật tư xây dựng", rag.mo_rong_viet_tat("mua vật tư xây dựng"))

    def test_hoi_muc_ngan_thi_tra_loi_thang(self):
        self.assertTrue(rag._yeu_cau_tra_loi_thang(CAU))
        self.assertTrue(rag._yeu_cau_tra_loi_thang("thuế suất thuế thu nhập doanh nghiệp hiện nay"))
        # Câu tình huống dài vẫn đi khung phân tích / làm rõ như cũ.
        dai = ("Công ty TNHH 2 thành viên thành lập ngày 01/01/2026, một thành viên chưa góp đủ "
               "vốn đúng hạn; hỏi mức phạt vi phạm hành chính là bao nhiêu và hậu quả pháp lý "
               "đối với tư cách thành viên ra sao")
        self.assertFalse(rag._yeu_cau_tra_loi_thang(dai))
        self.assertFalse(rag._yeu_cau_tra_loi_thang("chào bạn"))


class UuTienVanBanMoi(unittest.TestCase):
    def _chay(self, items, cau=CAU):
        return rag.uu_tien_van_ban_moi(items, cau, nam_nay=2026, san=0.26)

    def test_nghi_dinh_1995_xuong_duoi_nghi_dinh_2026(self):
        cu = _luat(1, "96/CP", 1995, diem=0.54)
        moi = _luat(2, "141/2026/NĐ-CP", 2026, diem=0.50)
        self._chay([cu, moi])
        self.assertGreater(moi["score"], cu["score"])
        self.assertAlmostEqual(0.48, cu["score"])
        self.assertAlmostEqual(0.53, moi["score"])

    def test_van_ban_duoi_luat_ha_theo_tuoi(self):
        tt = _luat(1, "154/2011/TT-BTC", 2011, diem=0.52, loai="Thông tư")
        vua = _luat(2, "68/2020/NĐ-CP", 2020, diem=0.52)
        self._chay([tt, vua])
        self.assertAlmostEqual(0.49, tt["score"])      # 15 năm: −0,03 (từ 16 năm: −0,06)
        self.assertAlmostEqual(0.52, vua["score"])     # 6 năm: giữ nguyên

    def test_luat_cu_khong_bi_ha_vi_tuoi(self):
        ltm = _luat(1, "36/2005/QH11", 2005, diem=0.6, loai="Luật")
        blds = _luat(2, "91/2015/QH13", 2015, diem=0.6, loai="Bộ luật")
        self._chay([ltm, blds])
        self.assertEqual(0.6, ltm["score"])
        self.assertEqual(0.6, blds["score"])

    def test_nam_lay_tu_so_hieu_khi_thieu_ngay(self):
        c = _luat(1, "97/1995/TT-TC", None, diem=0.5, loai="Thông tư")
        self._chay([c])
        self.assertAlmostEqual(0.44, c["score"])

    def test_khong_ro_nam_thi_giu_nguyen(self):
        c = _luat(1, "12/VBHN-BTC", None, diem=0.5)
        self._chay([c])
        self.assertEqual(0.5, c["score"])

    def test_cau_neu_nam_cu_giu_nguyen_xep_hang(self):
        cu = _luat(1, "96/CP", 1995, diem=0.54)
        self._chay([cu], "Nghị định năm 1995 quy định miễn thuế doanh thu thế nào")
        self.assertEqual(0.54, cu["score"])
        dn = _luat(2, "01/2021/NĐ-CP", 2021, diem=0.5)
        self._chay([dn], "theo Luật Doanh nghiệp 2020 thì đăng ký thế nào")
        self.assertEqual(0.5, dn["score"])

    def test_khong_day_xuong_duoi_san(self):
        cu = _luat(1, "96/CP", 1995, diem=0.30)
        self._chay([cu])
        self.assertAlmostEqual(0.26, cu["score"])       # đang trên sàn 0,26 → dừng ở sàn
        cu2 = _luat(2, "96/CP", 1995, diem=0.40)
        self._chay([cu2])
        self.assertAlmostEqual(0.34, cu2["score"])

    def test_chi_dung_doan_luat(self):
        hs = {"doc_type": "ho_so_kh", "so_hieu": "01/1995", "score": 0.5,
              "ngay_ban_hanh": date(1995, 1, 1)}
        self._chay([hs])
        self.assertEqual(0.5, hs["score"])


class KeoDoanSuaDoi(unittest.TestCase):
    MOI_HON = [
        {"document_id": 141, "loai": "sua_doi_bo_sung", "so_hieu_cu": "68/2026/NĐ-CP",
         "so_hieu": "141/2026/NĐ-CP", "ngay_ban_hanh": date(2026, 4, 29), "ten": "NĐ 141"},
        # Quan hệ bóc ngược chiều (văn bản "sửa" cũ hơn văn bản bị sửa) — bỏ.
        {"document_id": 9, "loai": "sua_doi_bo_sung", "so_hieu_cu": "68/2026/NĐ-CP",
         "so_hieu": "12/2019/NĐ-CP", "ngay_ban_hanh": date(2019, 1, 1), "ten": "NĐ 12"},
        # Thay thế không thuộc khối này (khối thay thế riêng đã lo).
        {"document_id": 7, "loai": "thay_the", "so_hieu_cu": "68/2026/NĐ-CP",
         "so_hieu": "7/2026/NĐ-CP", "ngay_ban_hanh": date(2026, 9, 1), "ten": "NĐ 7"},
    ]

    def test_chon_van_ban_sua_doi_moi_hon(self):
        kept = [_luat(68, "68/2026/NĐ-CP", 2026)]
        self.assertEqual({141: "68/2026/NĐ-CP"}, rag.chon_van_ban_sua_doi(kept, self.MOI_HON))

    def test_ban_hop_nhat_khong_keo(self):
        kept = [_luat(5, "24/2026/VBHN-BTC", 2026)]
        moi_hon = [dict(self.MOI_HON[0], so_hieu_cu="24/2026/VBHN-BTC")]
        self.assertEqual({}, rag.chon_van_ban_sua_doi(kept, moi_hon))
        # Bản hợp nhất cũng không bao giờ là văn bản SỬA ĐỔI.
        kept = [_luat(89, "89/2026/TT-BTC", 2026, loai="Thông tư")]
        moi_hon = [{"document_id": 425, "loai": "sua_doi_bo_sung", "so_hieu_cu": "89/2026/TT-BTC",
                    "so_hieu": "24/2026/VBHN-TT-BTC", "ngay_ban_hanh": None, "ten": "VBHN"}]
        self.assertEqual({}, rag.chon_van_ban_sua_doi(kept, moi_hon))

    def test_van_ban_cap_duoi_khong_sua_duoc_cap_tren(self):
        luat = [_luat(59, "59/2020/QH14", 2020, loai="Luật")]
        sai = [{"document_id": 64, "loai": "sua_doi_bo_sung", "so_hieu_cu": "59/2020/QH14",
                "so_hieu": "64/2025/TT-NHNN", "ngay_ban_hanh": date(2025, 1, 1), "ten": "TT"},
               {"document_id": 129, "loai": "sua_doi_bo_sung", "so_hieu_cu": "59/2020/QH14",
                "so_hieu": "129/2026/QĐ-CTUBND", "ngay_ban_hanh": date(2026, 1, 1), "ten": "QĐ"},
               {"document_id": 18, "loai": "sua_doi_bo_sung", "so_hieu_cu": "59/2020/QH14",
                "so_hieu": "18/2026/NQ-CP", "ngay_ban_hanh": date(2026, 1, 1), "ten": "NQ"}]
        dung = [{"document_id": 136, "loai": "sua_doi_bo_sung", "so_hieu_cu": "59/2020/QH14",
                 "so_hieu": "136/2025/QH15", "ngay_ban_hanh": date(2025, 6, 1), "ten": "Luật"}]
        self.assertEqual({136: "59/2020/QH14"}, rag.chon_van_ban_sua_doi(luat, sai + dung))
        nd = [_luat(65, "65/2023/NĐ-CP", 2023)]
        tt = [{"document_id": 6, "loai": "sua_doi_bo_sung", "so_hieu_cu": "65/2023/NĐ-CP",
               "so_hieu": "06/2024/TT-BKHCN", "ngay_ban_hanh": date(2024, 1, 1), "ten": "TT"}]
        self.assertEqual({}, rag.chon_van_ban_sua_doi(nd, tt))

    def test_chi_keo_cho_van_ban_o_nhom_nguon_dau(self):
        kept = [_luat(i, f"{i}/2020/TT-BTC", 2020, loai="Thông tư") for i in range(1, 13)]
        kept.append(_luat(68, "68/2026/NĐ-CP", 2026))
        self.assertEqual({}, rag.chon_van_ban_sua_doi(kept, self.MOI_HON))
        self.assertEqual({141: "68/2026/NĐ-CP"}, rag.chon_van_ban_sua_doi(kept[1:], self.MOI_HON))

    def test_cung_nam_thi_so_ngay(self):
        kept = [_luat(68, "68/2026/NĐ-CP", None, ngay_ban_hanh=date(2026, 3, 5))]
        moi_hon = [dict(self.MOI_HON[0]),
                   {"document_id": 8, "loai": "sua_doi_bo_sung", "so_hieu_cu": "68/2026/NĐ-CP",
                    "so_hieu": "8/2026/NĐ-CP", "ngay_ban_hanh": date(2026, 1, 9), "ten": "NĐ 8"}]
        self.assertEqual({141: "68/2026/NĐ-CP"}, rag.chon_van_ban_sua_doi(kept, moi_hon))

    def test_cau_moi_cuoi_khong_bi_gan_nguon_khong_bi_luoc(self):
        nguon = [{"content": "Hộ kinh doanh có doanh thu năm từ 01 tỷ đồng trở xuống không phải "
                             "nộp thuế thu nhập cá nhân; cung cấp thêm thông tin doanh thu năm."}]
        tra_loi = ("Hộ kinh doanh có doanh thu năm từ 01 tỷ đồng trở xuống không phải nộp thuế "
                   "thu nhập cá nhân [Nguồn 1].\n\nNếu bạn cần xác định cụ thể, vui lòng cung cấp "
                   "thêm thông tin về doanh thu năm của hộ kinh doanh đó.")
        ra, _n = rag.autocite(tra_loi, nguon)
        self.assertTrue(ra.rstrip().endswith("hộ kinh doanh đó."))
        with mock.patch.object(rag, "_canh_bao_so_hieu", side_effect=lambda t, c: t), \
                mock.patch.object(rag, "_canh_bao_hieu_luc", side_effect=lambda t, c: t):
            ra, trang_thai = rag.validate_grounding(tra_loi, nguon, "grounded", strict=True)
        self.assertEqual("verified", trang_thai)
        self.assertIn("vui lòng cung cấp", ra)

    def test_van_ban_sua_doi_da_co_doan_khac_van_duoc_chon(self):
        # Ca thật 12/10: Điều 2, Điều 4 Nghị định 141 đã ở cuối nguồn, Điều 1 (đoạn
        # sửa "500 triệu" thành "01 tỷ") thì không — vẫn phải đi tìm.
        kept = [_luat(68, "68/2026/NĐ-CP", 2026), _luat(141, "141/2026/NĐ-CP", 2026)]
        self.assertEqual({141: "68/2026/NĐ-CP"}, rag.chon_van_ban_sua_doi(kept, self.MOI_HON))

    def test_doan_da_co_dung_sau_thi_doi_len_dung_truoc_thi_gan_nhan(self):
        a = _luat(68, "68/2026/NĐ-CP", 2026, chunk_id=681)
        x = _luat(5, "5/2020/NĐ-CP", 2020, chunk_id=50)
        s_sau = _luat(141, "141/2026/NĐ-CP", 2026, chunk_id=1414)
        ra = rag.chen_doan_sua_doi([a, x, s_sau], [dict(s_sau)], {141: "68/2026/NĐ-CP"})
        self.assertEqual([681, 1414, 50], [c["chunk_id"] for c in ra])
        s_truoc = _luat(141, "141/2026/NĐ-CP", 2026, chunk_id=1414)
        ra = rag.chen_doan_sua_doi([s_truoc, a, x], [dict(s_truoc)], {141: "68/2026/NĐ-CP"})
        self.assertEqual([1414, 681, 50], [c["chunk_id"] for c in ra])
        self.assertEqual("68/2026/NĐ-CP", ra[0]["sua_doi_cho"])

    def test_doan_hieu_luc_thi_hanh(self):
        hl = _luat(141, "141/2026/NĐ-CP", 2026, nhan="Nghị định số 141/2026/NĐ-CP — Điều 3",
                   noi_dung="Điều 3. Hiệu lực thi hành\nNghị định này có hiệu lực thi hành từ "
                            "ngày 01 tháng 01 năm 2026.", chunk_id=3)
        hd = _luat(9, "9/2026/NĐ-CP", 2026, nhan="Nghị định số 9/2026/NĐ-CP — Điều 12",
                   noi_dung="Điều 12. Hiệu lực của hợp đồng", chunk_id=12)
        self.assertEqual([3], [c["chunk_id"] for c in rag.doan_hieu_luc([hd, hl])])

    def test_moi_van_ban_toi_da_hai_cai_gan_nhat_va_tran_tong(self):
        kept = [_luat(1, "91/2015/QH13", 2015, loai="Bộ luật")]
        moi_hon = [{"document_id": 100 + i, "loai": "sua_doi_bo_sung",
                    "so_hieu_cu": "91/2015/QH13", "so_hieu": f"{i}/202{i}/QH15",
                    "ngay_ban_hanh": date(2020 + i, 1, 1), "ten": str(i)} for i in range(1, 6)]
        self.assertEqual({105: "91/2015/QH13", 104: "91/2015/QH13"},
                         rag.chon_van_ban_sua_doi(kept, moi_hon))
        kept = [_luat(i, f"{i}/2020/NĐ-CP", 2020) for i in range(1, 4)]
        moi_hon = [{"document_id": 100 + i * 10 + j, "loai": "sua_doi_bo_sung",
                    "so_hieu_cu": f"{i}/2020/NĐ-CP", "so_hieu": f"{j}/2025/NĐ-CP",
                    "ngay_ban_hanh": date(2025, j, 1), "ten": "x"}
                   for i in range(1, 4) for j in range(1, 4)]
        self.assertEqual(4, len(rag.chon_van_ban_sua_doi(kept, moi_hon)))

    def test_chon_doan_neu_dich_danh_van_ban_bi_sua(self):
        sua_cho = {141: "68/2026/NĐ-CP"}
        ung_vien = [
            _luat(141, "141/2026/NĐ-CP", 2026, diem=0.62, nhan="Nghị định số 141/2026/NĐ-CP — Điều 2",
                  noi_dung="Bổ sung khoản 15 Điều 4 Nghị định số 320/2025/NĐ-CP", chunk_id=2),
            _luat(141, "141/2026/NĐ-CP", 2026, diem=0.58, nhan="Nghị định số 141/2026/NĐ-CP — Điều 1",
                  noi_dung="Sửa đổi một số điều của Nghị định số 68/2026/NĐ-CP: sửa cụm từ "
                           "“500 triệu đồng” thành “01 tỷ đồng”", chunk_id=1),
            _luat(141, "141/2026/NĐ-CP", 2026, diem=0.70,
                  nhan="Nghị định số 141/2026/NĐ-CP — Phần mở đầu",
                  noi_dung="Sửa đổi, bổ sung một số điều của Nghị định số 68/2026/NĐ-CP", chunk_id=0),
        ]
        ra = rag.chon_doan_sua_doi(ung_vien, sua_cho, {"68/2026/NĐ-CP": 0.55}, 0.25)
        self.assertEqual([1], [c["chunk_id"] for c in ra])

    def test_khong_doan_nao_neu_ten_thi_lay_mot_doan_du_diem(self):
        sua_cho = {9: "109/2025/QH15"}
        dieu1 = _luat(9, "09/2026/QH16", 2026, diem=0.50, loai="Luật", chunk_id=1,
                      noi_dung="Sửa đổi, bổ sung khoản 1 Điều 7 của Luật Thuế thu nhập cá nhân")
        dieu4 = _luat(9, "09/2026/QH16", 2026, diem=0.40, loai="Luật", chunk_id=4,
                      noi_dung="xe chạy bằng pin")
        ra = rag.chon_doan_sua_doi([dieu4, dieu1], sua_cho, {"109/2025/QH15": 0.55}, 0.25)
        self.assertEqual([1], [c["chunk_id"] for c in ra])        # Điều 4 thua quá 0,10
        ra = rag.chon_doan_sua_doi([dieu4, dieu1], sua_cho, {"109/2025/QH15": 0.48}, 0.25)
        self.assertEqual([1, 4], [c["chunk_id"] for c in ra])
        # Thua đoạn của văn bản bị sửa quá 0,10 → không kéo.
        ra = rag.chon_doan_sua_doi([dieu1], sua_cho, {"109/2025/QH15": 0.65}, 0.25)
        self.assertEqual([], ra)

    def test_chen_ngay_sau_van_ban_bi_sua(self):
        a = _luat(68, "68/2026/NĐ-CP", 2026, chunk_id=681)
        b = _luat(68, "68/2026/NĐ-CP", 2026, chunk_id=682)
        x = _luat(5, "5/2020/NĐ-CP", 2020, chunk_id=50)
        s1 = _luat(141, "141/2026/NĐ-CP", 2026, chunk_id=1411)
        s2 = _luat(141, "141/2026/NĐ-CP", 2026, chunk_id=1412)
        ra = rag.chen_doan_sua_doi([a, x, b], [s1, s2], {141: "68/2026/NĐ-CP"})
        self.assertEqual([681, 50, 682, 1411, 1412], [c["chunk_id"] for c in ra])
        self.assertEqual("68/2026/NĐ-CP", s1["sua_doi_cho"])

    def test_prompt_noi_doan_nao_sua_doan_nao(self):
        bi_sua = _luat(68, "68/2026/NĐ-CP", 2026, nhan="Nghị định số 68/2026/NĐ-CP",
                       noi_dung="Điều 4. doanh thu năm từ 500 triệu đồng trở xuống không phải nộp thuế",
                       trang_thai_hieu_luc="het_hieu_luc_mot_phan")
        sua = _luat(141, "141/2026/NĐ-CP", 2026, nhan="Nghị định số 141/2026/NĐ-CP — Điều 1",
                    noi_dung="sửa cụm từ “500 triệu đồng” thành “01 tỷ đồng”",
                    sua_doi_cho="68/2026/NĐ-CP")
        with mock.patch.object(rag.settings, "get_float", return_value=0.25):
            p = rag.build_prompt(CAU, [bi_sua, sua], chunk_chars=0, budget=0)
        self.assertIn("ĐOẠN SỬA ĐỔI văn bản này có ở [Nguồn 2]", p)
        self.assertIn("VĂN BẢN SỬA ĐỔI: đoạn này sửa đổi, bổ sung văn bản số 68/2026/NĐ-CP [Nguồn 1]", p)
        self.assertIn("TRẢ LỜI THẲNG", p)
        self.assertIn("NGOẠI LỆ", p)


class TuGanNguonKhongLac(unittest.TestCase):
    """13/10/2026: "Theo Nghị định số 293/2025/NĐ-CP, mức lương tối thiểu vùng hiện
    nay được quy định như sau: [Nguồn 27]" — nguồn 27 là một bản án."""
    ND293 = {"doc_type": "law", "so_hieu": "293/2025/NĐ-CP", "section_title": "Nghị định số 293/2025/NĐ-CP",
             "content": "Điều 3. Mức lương tối thiểu vùng I 5.310.000 đồng/tháng, vùng II 4.730.000 "
                        "đồng/tháng áp dụng đối với người lao động theo hợp đồng lao động"}
    BAN_AN = {"doc_type": "ban_an", "so_hieu": "25/2025/LĐ-PT",
              "content": "Nghị định 293/2025 quy định mức lương tối thiểu vùng hiện nay, theo đó "
                         "bị đơn phải trả lương không thấp hơn mức lương tối thiểu vùng I"}

    def test_cau_dan_khong_gan_nguon_rieng(self):
        tl = ("Theo Nghị định số 293/2025/NĐ-CP, mức lương tối thiểu vùng hiện nay được quy định như sau:"
              "\n\n- Vùng I: 5.310.000 đồng/tháng, vùng II 4.730.000 đồng/tháng áp dụng cho người lao "
              "động theo hợp đồng lao động")
        ra, _n = rag.autocite(tl, [self.ND293, self.BAN_AN])
        dong_dau = ra.split("\n\n")[0]
        self.assertNotIn("[Nguồn", dong_dau)
        self.assertTrue(ra.rstrip().endswith("[Nguồn 1]"))

    def test_doan_neu_so_hieu_chi_gan_vao_van_ban_do(self):
        tl = ("Nghị định 293/2025/NĐ-CP quy định mức lương tối thiểu vùng hiện nay, người lao động "
              "phải được trả không thấp hơn mức lương tối thiểu vùng.")
        ra, _n = rag.autocite(tl, [self.BAN_AN, self.ND293], min_coverage=0.3)
        self.assertTrue(ra.rstrip().endswith("[Nguồn 2]"), ra)

    def test_ngang_diem_thi_chon_van_ban_con_hieu_luc(self):
        noi_dung = ("Điều 4. Áp dụng mức lương tối thiểu tháng là mức lương thấp nhất làm cơ sở thỏa "
                    "thuận và trả lương đối với người lao động áp dụng hình thức trả lương theo tháng")
        cu = {"doc_type": "law", "so_hieu": "02/VBHN-BNV", "trang_thai_hieu_luc": "het_hieu_luc",
              "content": noi_dung}
        moi = {"doc_type": "law", "so_hieu": "293/2025/NĐ-CP", "content": noi_dung}
        tl = ("- Mức lương tối thiểu tháng là mức lương thấp nhất làm cơ sở thỏa thuận và trả lương "
              "đối với người lao động áp dụng hình thức trả lương theo tháng.")
        ra, _n = rag.autocite(tl, [cu, moi])
        self.assertTrue(ra.rstrip().endswith("[Nguồn 2]"), ra)


class BanHopNhatChetTheoVanBanGoc(unittest.TestCase):
    """"Lương tối thiểu vùng hiện nay": kho chỉ có bản hợp nhất 02/VBHN-BNV của
    Nghị định 74/2024 (mức 2025), quan hệ "293/2025/NĐ-CP thay thế 74/2024/NĐ-CP"
    ghi theo số gốc."""
    NHAN = "Nghị định số 74/2024/NĐ-CP (văn bản hợp nhất 02/VBHN-BNV) — Điều 3"

    def test_so_hieu_quan_he_lay_so_goc_cua_vbhn(self):
        vbhn = _luat(1, "02/VBHN-BNV", 2025, nhan=self.NHAN)
        self.assertEqual("74/2024/NĐ-CP", rag.so_hieu_quan_he(vbhn))
        self.assertEqual("293/2025/NĐ-CP", rag.so_hieu_quan_he(_luat(2, "293/2025/NĐ-CP", 2025)))
        la = _luat(3, "02/VBHN-BNV", 2025, nhan="Văn bản hợp nhất 02/VBHN-BNV")
        self.assertEqual("02/VBHN-BNV", rag.so_hieu_quan_he(la))

    def test_vbhn_cua_van_ban_bi_thay_mang_nhan_het_hieu_luc(self):
        vbhn = _luat(1, "02/VBHN-BNV", 2025, nhan=self.NHAN, trang_thai_hieu_luc="chua_ro")
        khac = _luat(2, "02/VBHN-BNV", 2020, trang_thai_hieu_luc="chua_ro",
                     nhan="Nghị định số 145/2020/NĐ-CP (văn bản hợp nhất 02/VBHN-BNV) — Điều 1")
        moi_hon = [{"document_id": 293, "loai": "thay_the", "so_hieu_cu": "74/2024/NĐ-CP",
                    "so_hieu": "293/2025/NĐ-CP", "ngay_ban_hanh": date(2025, 11, 10), "ten": "NĐ 293"},
                   # Thông tư "thay thế" nghị định là quan hệ bóc nhầm — bỏ.
                   {"document_id": 9, "loai": "thay_the", "so_hieu_cu": "145/2020/NĐ-CP",
                    "so_hieu": "9/2026/TT-BNV", "ngay_ban_hanh": date(2026, 1, 1), "ten": "TT"}]
        self.assertEqual(1, rag.danh_dau_vbhn_bi_thay([vbhn, khac], moi_hon))
        self.assertEqual("het_hieu_luc", vbhn["trang_thai_hieu_luc"])
        self.assertEqual("chua_ro", khac["trang_thai_hieu_luc"])


class LuatNenThueHoKinhDoanh(unittest.TestCase):
    def test_chu_de_va_dieu_nen(self):
        self.assertIn("nd_hkd", luat_nen.chu_de_luat(CAU))
        self.assertEqual([3, 4], luat_nen.dieu_nen(CAU, "nd_hkd"))
        self.assertIn("nd_hkd", luat_nen.chu_de_luat(rag.mo_rong_viet_tat("hkd đang được miễn bao nhiêu")))
        self.assertEqual([7], luat_nen.dieu_nen(CAU, "tncn"))

    def test_doan_markdown_chua_nhieu_dieu(self):
        c = {"chunk_id": 1, "section_title": "Nghị định số 68/2026/NĐ-CP", "score": 0.5,
             "content": "## Điều 2. Đối tượng áp dụng 1. Người nộp thuế … ## Chương II "
                        "## Điều 3. Thuế giá trị gia tăng 1. Hộ kinh doanh … tại Điều 7 Luật."}
        self.assertEqual(2, luat_nen.dieu_cua_doan(c))
        self.assertEqual([2, 3], luat_nen.cac_dieu_cua_doan(c))
        khac = {"chunk_id": 2, "section_title": "Nghị định số 68/2026/NĐ-CP", "score": 0.9,
                "content": "## Điều 9. Hộ kinh doanh mới ra kinh doanh"}
        self.assertEqual([1, 2], [x["chunk_id"] for x in luat_nen.chon_doan([khac, c], [3], them=1)])

    def test_tham_chieu_giua_cau_khong_phai_tieu_de(self):
        c = {"section_title": "Nghị định số 68/2026/NĐ-CP",
             "content": "## Điều 4. Thuế TNCN 2. nộp thuế theo quy định tại Điều 7. Luật"}
        self.assertEqual([4], luat_nen.cac_dieu_cua_doan(c))


if __name__ == "__main__":
    unittest.main()
