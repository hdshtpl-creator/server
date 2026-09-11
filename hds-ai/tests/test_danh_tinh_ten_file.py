"""Danh tính văn bản luật lấy từ TÊN FILE — kiểm 65 văn bản trong kho 06/09/2026.

Bản .docx tải về không có dòng "Số: …" nên bóc từ chữ ra None (9/15 văn bản
cốt lõi) hoặc nhầm số của văn bản dẫn chiếu (Thông tư 55/2026 → 03/2021/TT-BKHĐT,
Nghị định 96/2026 → nhãn đoạn "Nghị Định số 63/2025/QH15"). Tên file thì đúng.
Toàn bộ là logic thuần — không CSDL, không Ollama.
"""
import unittest

from app.van_ban import boc_metadata, trich_dan
from datetime import date

from app import van_ban
from app.ingest import chunk_law_structured, document_citation

DAU_ND_96 = ("NGHỊ ĐỊNH\nQuy định chi tiết và hướng dẫn thi hành một số điều của "
             "Luật Đầu tư\nCăn cứ Luật Tổ chức Chính phủ số 63/2025/QH15;\n"
             "Căn cứ Luật Đầu tư số 143/2025/QH15;\nCăn cứ Luật Doanh nghiệp số "
             "59/2020/QH14;\nChính phủ ban hành Nghị định quy định chi tiết và hướng "
             "dẫn thi hành một số điều của Luật Đầu tư.\nChương I\nQUY ĐỊNH CHUNG\n"
             "Điều 1. Phạm vi điều chỉnh\n1. Nghị định này quy định chi tiết Điều 6.\n"
             "Điều 2. Đối tượng áp dụng\nNhà đầu tư.\n")
DAU_TT_55 = ("THÔNG TƯ\nQuy định mẫu văn bản, báo cáo liên quan đến hoạt động đầu tư\n"
             "Căn cứ Luật Đầu tư số 143/2025/QH15 ngày 11 tháng 12 năm 2025;\n"
             "Căn cứ Nghị định số 96/2026/NĐ-CP ngày 31 tháng 3 năm 2026;\n"
             "Bộ trưởng ban hành Thông tư. Thông tư này thay thế Thông tư số "
             "03/2021/TT-BKHĐT ngày 09 tháng 4 năm 2021.\nĐiều 1. Phạm vi\nMẫu.\n")
DAU_VBHN_67 = ("LUẬT\nDOANH NGHIỆP\nLuật số: 59/2020/QH14\nCăn cứ Hiến pháp;\n"
               "Quốc hội ban hành Luật Doanh nghiệp.\nĐiều 1. Phạm vi điều chỉnh\n"
               "Luật này quy định về doanh nghiệp.\n")


class DanhTinhTuTenFile(unittest.TestCase):
    def _d(self, ten):
        return van_ban.danh_tinh_tu_ten_file(ten)

    def test_ten_co_tien_to_loai(self):
        d = self._d("Nghị-định-96-2026-NĐ-CP.docx")
        self.assertEqual(("96/2026/NĐ-CP", "Nghị định", "tien_to"),
                         (d["so_hieu"], d["loai_van_ban"], d["loai_tin_cay"]))
        self.assertEqual("Bộ luật", self._d("Bộ-luật-91-2015-QH13.doc")["loai_van_ban"])
        self.assertEqual("91/2015/QH13", self._d("Bộ-luật-91-2015-QH13.doc")["so_hieu"])
        self.assertEqual("Nghị quyết", self._d("Nghị-quyết-01-2024-NQ-HĐTP.docx")["loai_van_ban"])

    def test_ten_khong_dau_kem_ngay(self):
        d = self._d("58-2026-ND-CP_13022026.pdf")
        self.assertEqual("58/2026/NĐ-CP", d["so_hieu"])          # ND → NĐ
        self.assertEqual("Nghị định", d["loai_van_ban"])
        self.assertEqual("duoi", d["loai_tin_cay"])
        self.assertEqual(date(2026, 2, 13), d["ngay_ban_hanh"])

    def test_so_hieu_khong_co_nam(self):
        self.assertEqual("09/CĐ-TTg", self._d("09-CD-TTg_03022025.pdf")["so_hieu"])
        self.assertEqual("1125/QĐ-TTg", self._d("1125-QD-TTg_23062026.pdf")["so_hieu"])
        d = self._d("Văn-bản-hợp-nhất-67-VBHN-VPQH.docx")
        self.assertEqual("67/VBHN-VPQH", d["so_hieu"])
        self.assertEqual("Văn bản hợp nhất", d["loai_van_ban"])

    def test_ten_file_thuong_khong_bi_nhan_nham(self):
        for ten in ("Bcao test HDS.AI.docx", "HĐLĐ BAC THI MAI.docx", "Điều lệ.docx",
                    "Kịch bản test AI.docx", "005_2024HĐM 91.pdf"):
            self.assertIsNone(self._d(ten)["so_hieu"], ten)


class BocMetadataUuTienTenFile(unittest.TestCase):
    def test_docx_khong_co_dong_so_lay_tu_ten_file(self):
        # Không có tên file: dòng "Căn cứ" bị bỏ qua → None (không nhặt 63/2025).
        self.assertIsNone(van_ban.boc_metadata(DAU_ND_96)["so_hieu"])
        m = van_ban.boc_metadata(DAU_ND_96, ten_file="Nghị-định-96-2026-NĐ-CP.docx")
        self.assertEqual("96/2026/NĐ-CP", m["so_hieu"])
        self.assertEqual("Nghị định", m["loai_van_ban"])
        self.assertNotIn("so_hieu_trong_van_ban", m)

    def test_so_giua_cau_khong_con_bi_lay_lam_so_cua_minh(self):
        # "Thông tư số 03/2021/TT-BKHĐT" trong câu "thay thế…" — không có dấu
        # hai chấm → không phải số của chính văn bản.
        m = van_ban.boc_metadata(DAU_TT_55)
        self.assertNotEqual("03/2021/TT-BKHĐT", m["so_hieu"])
        m = van_ban.boc_metadata(DAU_TT_55, ten_file="Thông-tư-55-2026-TT-BTC.docx")
        self.assertEqual("55/2026/TT-BTC", m["so_hieu"])

    def test_van_ban_hop_nhat_giu_ca_hai_so(self):
        m = van_ban.boc_metadata(DAU_VBHN_67, ten_file="Văn-bản-hợp-nhất-67-VBHN-VPQH.docx")
        self.assertEqual("67/VBHN-VPQH", m["so_hieu"])
        self.assertEqual("59/2020/QH14", m["so_hieu_trong_van_ban"])
        self.assertEqual("Luật", m["loai_van_ban"])      # loại hiển thị của luật gốc
        self.assertTrue(m.get("hop_nhat"))
        self.assertEqual("Luật Doanh nghiệp số 59/2020/QH14 (văn bản hợp nhất 67/VBHN-VPQH)",
                         van_ban.ten_day_du(m))

    def test_dong_so_co_hai_cham_van_thang(self):
        m = van_ban.boc_metadata(DAU_VBHN_67)
        self.assertEqual("59/2020/QH14", m["so_hieu"])


class NhanDoanMangSoDung(unittest.TestCase):
    def test_trich_dan_va_nhan_doan(self):
        self.assertEqual("Nghị định số 96/2026/NĐ-CP",
                         document_citation(DAU_ND_96, ten_file="Nghị-định-96-2026-NĐ-CP.docx"))
        pieces = chunk_law_structured(DAU_ND_96, ten_file="Nghị-định-96-2026-NĐ-CP.docx")
        dieu_1 = next(p for p in pieces if p.source_locator == "dieu:1")
        self.assertTrue(dieu_1.content.startswith("[Nghị định số 96/2026/NĐ-CP — Chương I — Điều 1]"),
                        dieu_1.content[:80])
        self.assertNotIn("63/2025", dieu_1.section_title)

    def test_khong_co_ten_file_khong_nhat_so_dan_chieu(self):
        # Đường cũ (không tên file) không được tái phát nhãn "Nghị Định số 63/2025/QH15".
        self.assertNotIn("63/2025", document_citation(DAU_ND_96))



class BanHopNhatCongBao(unittest.TestCase):
    """PDF Công báo của văn bản hợp nhất: dòng 'VĂN BẢN HỢP NHẤT - VĂN PHÒNG
    QUỐC HỘI' đứng trước tên luật. Ba luật nạp 11/09/2026 (SHTT, Thương mại,
    Cán bộ công chức) bị bóc thành loại 'Văn bản hợp nhất', trích yếu 'Văn
    phòng quốc hội', và nhãn đoạn ghi 'Văn bản hợp nhất Văn phòng quốc hội số
    50/2005/QH11' — luật sư đọc không hiểu đó là Luật Sở hữu trí tuệ."""

    CHU = ("12 CÔNG BÁO/Số 361 + 362/Ngày 13-02-2023\n"
           "VĂN BẢN PHÁP LUẬT KHÁC\n"
           "VĂN BẢN HỢP NHẤT - VĂN PHÒNG QUỐC HỘI\n"
           "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM\n"
           "Độc lập - Tự do - Hạnh phúc\n"
           "LUẬT\n"
           "SỞ HỮU TRÍ TUỆ\n"
           "Luật Sở hữu trí tuệ số 50/2005/QH11 ngày 29 tháng 11 năm 2005 của Quốc\n"
           "hội, có hiệu lực kể từ ngày 01 tháng 7 năm 2006, được sửa đổi, bổ sung bởi:\n"
           "1. Luật số 36/2009/QH12 ngày 19 tháng 6 năm 2009 của Quốc hội sửa đổi, bổ\n"
           "sung một số điều của Luật Sở hữu trí tuệ, có hiệu lực kể từ ngày 01 tháng 01 năm 2010;\n"
           "Căn cứ Hiến pháp nước Cộng hòa xã hội chủ nghĩa Việt Nam;\n"
           "Quốc hội ban hành Luật Sở hữu trí tuệ.\n"
           "Phần thứ nhất\nQUY ĐỊNH CHUNG\n"
           "Điều 1. Phạm vi điều chỉnh\nLuật này quy định về quyền tác giả…\n")

    def test_danh_tinh_tu_cau_dinh_danh(self):
        m = boc_metadata(self.CHU, ten_file="01_Luat_SHTT_11-VBHN-VPQH.pdf")
        self.assertEqual(m["so_hieu"], "11/VBHN-VPQH")
        self.assertEqual(m["so_hieu_trong_van_ban"], "50/2005/QH11")
        self.assertEqual(m["loai_van_ban"], "Luật")
        self.assertEqual(m["trich_yeu"], "Sở hữu trí tuệ")
        self.assertTrue(m.get("hop_nhat"))

    def test_trich_dan_ghi_ten_luat_goc(self):
        self.assertEqual(
            trich_dan(self.CHU, ten_file="01_Luat_SHTT_11-VBHN-VPQH.pdf"),
            "Luật Sở hữu trí tuệ số 50/2005/QH11 (văn bản hợp nhất 11/VBHN-VPQH)")

    def test_bo_luat_va_ten_co_dau_phay(self):
        chu = self.CHU.replace("LUẬT\nSỞ HỮU TRÍ TUỆ", "LUẬT\nCÁN BỘ, CÔNG CHỨC").replace(
            "Luật Sở hữu trí tuệ số 50/2005/QH11 ngày 29 tháng 11 năm 2005",
            "Luật Cán bộ, công chức số 22/2008/QH12 ngày 13 tháng 11 năm 2008")
        m = boc_metadata(chu, ten_file="12_Luat_Can_bo_cong_chuc_25-VBHN-VPQH.pdf")
        self.assertEqual((m["loai_van_ban"], m["trich_yeu"], m["so_hieu_trong_van_ban"]),
                         ("Luật", "Cán bộ, công chức", "22/2008/QH12"))

    def test_van_ban_thuong_khong_bi_anh_huong(self):
        chu = ("QUỐC HỘI\nLuật số: 45/2019/QH14\nCỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM\n"
               "BỘ LUẬT\nLAO ĐỘNG\nCăn cứ Hiến pháp;\nQuốc hội ban hành Bộ luật Lao động.\n"
               "Điều 1. Phạm vi điều chỉnh\n")
        m = boc_metadata(chu, ten_file="Bộ-luật-45-2019-QH14.docx")
        self.assertEqual((m["loai_van_ban"], m["trich_yeu"], m["so_hieu"]),
                         ("Bộ luật", "Lao động", "45/2019/QH14"))
        self.assertFalse(m.get("hop_nhat"))


class LenhCongBoTrongCongBao(unittest.TestCase):
    """Công báo in mục lục 'Lệnh số 21/2015/L-CTN về việc công bố Luật' trước
    'Luật số 92/2015/QH13 Bộ luật tố tụng dân sự' — số của Lệnh bị lấy làm số
    trong văn bản, nhãn đoạn thành 'Bộ luật Tố tụng dân sự số 21/2015/L-CTN
    (văn bản hợp nhất 92/2015/QH13)' (11/09/2026)."""

    CHU = ("CÔNG BÁO/Số 1235 + 1236/Ngày 27-12-2015\nMỤC LỤC\n"
           "CHỦ TỊCH NƯỚC - QUỐC HỘI\n"
           "08-12-2015 - Lệnh số 21/2015/L-CTN về việc công bố Luật.\n"
           "25-11-2015 - Luật số 92/2015/QH13 Bộ luật tố tụng dân sự.\n"
           "QUỐC HỘI\nCỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM\n"
           "BỘ LUẬT\nTỐ TỤNG DÂN SỰ\nCăn cứ Hiến pháp nước Cộng hòa xã hội chủ nghĩa Việt Nam;\n"
           "Quốc hội ban hành Bộ luật tố tụng dân sự.\n"
           "Phần thứ nhất\nNHỮNG QUY ĐỊNH CHUNG\nĐiều 1. Phạm vi điều chỉnh\n")

    def test_bo_qua_so_lenh(self):
        m = boc_metadata(self.CHU, ten_file="03_Bo_luat_To_tung_dan_su_92-2015-QH13.pdf")
        self.assertEqual(m["so_hieu"], "92/2015/QH13")
        self.assertNotEqual(m.get("so_hieu_trong_van_ban"), "21/2015/L-CTN")
        self.assertFalse(m.get("hop_nhat"))
        self.assertEqual(trich_dan(self.CHU, ten_file="03_Bo_luat_To_tung_dan_su_92-2015-QH13.pdf"),
                         "Bộ luật Tố tụng dân sự số 92/2015/QH13")

    def test_khong_bia_van_ban_hop_nhat_khi_ten_file_khong_phai_vbhn(self):
        # số trong chữ khác số tên file vì dẫn chiếu → tên file thắng, không ghi "(văn bản hợp nhất …)"
        chu = "NGHỊ ĐỊNH\nSố: 99/2020/NĐ-CP\nQuy định chi tiết\nĐiều 1. Phạm vi\n"
        self.assertEqual(trich_dan(chu, ten_file="Nghị-định-96-2026-NĐ-CP.docx"),
                         "Nghị định số 96/2026/NĐ-CP")

if __name__ == "__main__":
    unittest.main()
