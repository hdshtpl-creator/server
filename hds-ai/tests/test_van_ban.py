# -*- coding: utf-8 -*-
"""Danh tính + quan hệ văn bản pháp luật (app/van_ban.py) — toàn hàm thuần.

KHÔNG chạm CSDL: update.sh chạy unittest ngay trên máy chủ production
(bài học 28/08/2026). Các hàm ghi/đọc CSDL nhận cursor nên phần bóc tách
test được trọn vẹn bằng chuỗi.
"""
import unittest
from datetime import date

from app.van_ban import (boc_metadata, boc_quan_he, chuan_hoa_so_hieu,
                         ten_day_du, trich_dan)


BO_LUAT = """QUỐC HỘI                CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM
Độc lập - Tự do - Hạnh phúc

Số: 45/2019/QH14        Hà Nội, ngày 20 tháng 11 năm 2019

BỘ LUẬT
LAO ĐỘNG

Căn cứ Hiến pháp nước Cộng hòa xã hội chủ nghĩa Việt Nam;
Quốc hội ban hành Bộ luật Lao động.

Điều 1. Phạm vi điều chỉnh
Bộ luật này quy định tiêu chuẩn lao động.

Điều 220. Hiệu lực thi hành
1. Bộ luật này có hiệu lực thi hành từ ngày 01 tháng 01 năm 2021.
2. Bộ luật Lao động số 10/2012/QH13 hết hiệu lực thi hành kể từ ngày Bộ luật
này có hiệu lực. Bộ luật này thay thế Bộ luật Lao động số 10/2012/QH13.
"""

NGHI_DINH = """CHÍNH PHỦ            CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM
Độc lập - Tự do - Hạnh phúc

Số: 145/2020/NĐ-CP      Hà Nội, ngày 14 tháng 12 năm 2020

NGHỊ ĐỊNH
Quy định chi tiết và hướng dẫn thi hành một số điều của Bộ luật Lao động
số 45/2019/QH14 về điều kiện lao động và quan hệ lao động

Căn cứ Luật Tổ chức Chính phủ ngày 19 tháng 6 năm 2015;
Căn cứ Bộ luật Lao động số 45/2019/QH14;

Điều 1. Phạm vi điều chỉnh
Nghị định này quy định chi tiết một số điều của Bộ luật Lao động.

Điều 114. Hiệu lực thi hành
1. Nghị định này có hiệu lực từ ngày 01/02/2021.
2. Nghị định này thay thế Nghị định số 05/2015/NĐ-CP ngày 12 tháng 01 năm 2015
và Nghị định số 148/2018/NĐ-CP ngày 24 tháng 10 năm 2018 của Chính phủ.
"""

LUAT_SUA_DOI = """QUỐC HỘI

Số: 51/2024/QH15

LUẬT
SỬA ĐỔI, BỔ SUNG MỘT SỐ ĐIỀU CỦA LUẬT ĐẤU GIÁ TÀI SẢN SỐ 01/2016/QH14

Điều 1. Sửa đổi, bổ sung một số điều của Luật Đấu giá tài sản số 01/2016/QH14
1. Sửa đổi khoản 1 Điều 5 như sau: "Điều 5. Giải thích từ ngữ".
"""


class ChuanHoaSoHieuTests(unittest.TestCase):
    def test_bo_khoang_trang_va_viet_hoa(self):
        self.assertEqual("45/2019/QH14", chuan_hoa_so_hieu("45 / 2019 / qh14"))

    def test_rong_tra_rong(self):
        self.assertEqual("", chuan_hoa_so_hieu(None))


class BocMetadataTests(unittest.TestCase):
    def test_bo_luat_du_danh_tinh(self):
        m = boc_metadata(BO_LUAT)
        self.assertEqual("45/2019/QH14", m["so_hieu"])
        self.assertEqual("Bộ luật", m["loai_van_ban"])
        self.assertEqual("Lao động", m["trich_yeu"])
        self.assertEqual(date(2019, 11, 20), m["ngay_ban_hanh"])
        self.assertEqual(date(2021, 1, 1), m["ngay_hieu_luc"])

    def test_nghi_dinh_trich_yeu_nhieu_dong(self):
        m = boc_metadata(NGHI_DINH)
        self.assertEqual("145/2020/NĐ-CP", m["so_hieu"])
        self.assertEqual("Nghị định", m["loai_van_ban"])
        self.assertIn("Quy định chi tiết", m["trich_yeu"])
        self.assertEqual(date(2020, 12, 14), m["ngay_ban_hanh"])
        # Ngày hiệu lực dạng số 01/02/2021 cũng phải đọc được.
        self.assertEqual(date(2021, 2, 1), m["ngay_hieu_luc"])

    def test_ngay_trong_cau_can_cu_khong_bi_vo_nham(self):
        """'Căn cứ Luật Tổ chức Chính phủ ngày 19/6/2015' KHÔNG phải ngày ban
        hành — ngày ban hành đòi dấu phẩy của dòng địa danh đứng trước."""
        m = boc_metadata(NGHI_DINH)
        self.assertNotEqual(date(2015, 6, 19), m["ngay_ban_hanh"])

    def test_so_hieu_dan_chieu_trong_than_khong_de_so_hieu_chinh(self):
        m = boc_metadata(BO_LUAT)
        self.assertEqual("45/2019/QH14", m["so_hieu"])   # không phải 10/2012/QH13

    def test_van_ban_thuong_tra_none_khong_no(self):
        m = boc_metadata("Biên bản họp phòng kinh doanh ngày 03/03/2026.")
        self.assertIsNone(m["so_hieu"])
        self.assertIsNone(m["loai_van_ban"])


class TrichDanTests(unittest.TestCase):
    def test_trich_dan_mang_ten_van_ban(self):
        self.assertEqual("Bộ luật Lao động số 45/2019/QH14", trich_dan(BO_LUAT))

    def test_trich_yeu_qua_dai_thi_luoc(self):
        """Trích yếu nghị định dài dằng dặc không được nhét vào header từng đoạn."""
        self.assertEqual("Nghị định số 145/2020/NĐ-CP", trich_dan(NGHI_DINH))

    def test_ten_day_du_ghep_du_ba_phan(self):
        self.assertEqual(
            "Bộ luật Lao động số 45/2019/QH14",
            ten_day_du({"loai_van_ban": "Bộ luật", "trich_yeu": "Lao động"},
                       so_hieu="45/2019/QH14"))


class BocQuanHeTests(unittest.TestCase):
    def test_thay_the_bat_ca_danh_sach(self):
        qh = boc_quan_he(NGHI_DINH, so_hieu_minh="145/2020/NĐ-CP")
        thay = {q["so_hieu_dich"] for q in qh if q["loai"] == "thay_the"}
        self.assertEqual({"05/2015/NĐ-CP", "148/2018/NĐ-CP"}, thay)

    def test_huong_dan_tu_trich_yeu(self):
        qh = boc_quan_he(NGHI_DINH, so_hieu_minh="145/2020/NĐ-CP")
        loai_cua = {q["so_hieu_dich"]: q["loai"] for q in qh if q["so_hieu_dich"]}
        self.assertEqual("huong_dan", loai_cua.get("45/2019/QH14"))

    def test_can_cu_theo_ten_khi_khong_co_so_hieu(self):
        qh = boc_quan_he(NGHI_DINH, so_hieu_minh="145/2020/NĐ-CP")
        ten = [q["ten_dich"] for q in qh
               if q["loai"] == "can_cu" and not q["so_hieu_dich"]]
        self.assertTrue(any("Luật Tổ chức Chính phủ" in t for t in ten))

    def test_sua_doi_tu_tieu_de(self):
        qh = boc_quan_he(LUAT_SUA_DOI, so_hieu_minh="51/2024/QH15")
        sua = [q for q in qh if q["loai"] == "sua_doi_bo_sung"]
        self.assertTrue(any(q["so_hieu_dich"] == "01/2016/QH14" for q in sua))

    def test_thay_the_trong_bo_luat(self):
        qh = boc_quan_he(BO_LUAT, so_hieu_minh="45/2019/QH14")
        thay = [q for q in qh if q["loai"] == "thay_the"]
        self.assertEqual(["10/2012/QH13"], [q["so_hieu_dich"] for q in thay])

    def test_khong_tu_tro_vao_chinh_minh(self):
        qh = boc_quan_he(BO_LUAT, so_hieu_minh="45/2019/QH14")
        self.assertFalse(any(q["so_hieu_dich"] == "45/2019/QH14" for q in qh))

    def test_thay_the_khong_co_ten_loai_thi_bo_qua(self):
        """'thay thế phương án 05/2019/BC-X' trong một báo cáo thường —
        không có tên loại văn bản trước số hiệu thì không được nhặt."""
        text = "Phòng đề xuất thay thế phương án 05/2019/BC-KD bằng phương án mới."
        self.assertEqual([], [q for q in boc_quan_he(text)
                              if q["loai"] in ("thay_the", "bai_bo")])

    def test_bai_bo_mot_dieu_la_sua_doi(self):
        text = ("THÔNG TƯ\nSố: 09/2025/TT-BTC\n\nĐiều 5. Điều khoản thi hành\n"
                "Bãi bỏ Điều 12 của Thông tư số 02/2020/TT-BTC.")
        qh = boc_quan_he(text, so_hieu_minh="09/2025/TT-BTC")
        loai_cua = {q["so_hieu_dich"]: q["loai"] for q in qh if q["so_hieu_dich"]}
        self.assertEqual("sua_doi_bo_sung", loai_cua.get("02/2020/TT-BTC"))


class BayBocTachTests(unittest.TestCase):
    """Các bẫy đợt rà soát 31/08/2026 phát hiện — mỗi case một lỗi đã sửa."""

    def test_cau_bi_dong_khong_dao_chieu_quan_he(self):
        """'Nghị định này ĐƯỢC thay thế bởi X' — ghi xuôi là khai tử nhầm X,
        văn bản đang còn hiệu lực, và giữ lại chính văn bản đã chết."""
        text = ("NGHỊ ĐỊNH\nSố: 05/2015/NĐ-CP\nĐiều 10. Hiệu lực\n"
                "Nghị định này được thay thế bởi Nghị định số 145/2020/NĐ-CP.")
        qh = boc_quan_he(text, so_hieu_minh="05/2015/NĐ-CP")
        self.assertEqual([], [q for q in qh if q["loai"] in ("thay_the", "bai_bo")])

    def test_cau_chu_dong_van_bat_duoc(self):
        text = ("NGHỊ ĐỊNH\nSố: 145/2020/NĐ-CP\nĐiều 114. Hiệu lực\n"
                "Nghị định này thay thế Nghị định số 05/2015/NĐ-CP.")
        qh = boc_quan_he(text, so_hieu_minh="145/2020/NĐ-CP")
        self.assertEqual([("thay_the", "05/2015/NĐ-CP")],
                         [(q["loai"], q["so_hieu_dich"]) for q in qh])

    def test_thay_the_cum_tu_la_sua_doi_khong_phai_khai_tu(self):
        """'Thay thế cụm từ … tại khoản 2 Điều 3 Nghị định X' sửa MỘT PHẦN —
        ghi thay_the là xoá sổ cả nghị định còn hiệu lực."""
        text = ('THÔNG TƯ\nSố: 09/2025/TT-BTC\nĐiều 2. Sửa đổi\n'
                'Thay thế cụm từ "cơ quan thuế" bằng "cơ quan quản lý" tại '
                'khoản 2 Điều 3 Nghị định số 126/2020/NĐ-CP.')
        qh = boc_quan_he(text, so_hieu_minh="09/2025/TT-BTC")
        self.assertEqual({"sua_doi_bo_sung"}, {q["loai"] for q in qh})

    def test_so_hieu_khong_theo_khuon_khong_vo_nham_van_ban_khac(self):
        """Công văn '1234/BTC-TCT' không khớp khuôn /YYYY/ — trước bản vá,
        lưới quét tự do vơ số hiệu ở dòng 'Căn cứ' của văn bản KHÁC."""
        text = ("BỘ TÀI CHÍNH\nSố: 1234/BTC-TCT\nCÔNG VĂN\nV/v hướng dẫn thuế\n"
                "Căn cứ Nghị định số 126/2020/NĐ-CP;")
        self.assertEqual("1234/BTC-TCT", boc_metadata(text)["so_hieu"])

    def test_loai_van_ban_nhan_duoc_khi_khong_dung_dong_rieng(self):
        """Bản trích xuất dồn dòng vẫn phải ra 'Nghị định số 15/2020/NĐ-CP',
        không được cụt còn 'số 15/2020/NĐ-CP'."""
        text = ("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM\n"
                "   Nghị định số 15/2020/NĐ-CP ngày 03 tháng 02 năm 2020\n"
                "Điều 1. Phạm vi")
        self.assertEqual("Nghị định số 15/2020/NĐ-CP", trich_dan(text))

    def test_trich_dan_rong_khi_khong_ro_loai_de_con_luoi_do(self):
        """Trả '' chứ không phải chuỗi cụt — bên gọi mới dùng được lưới đỡ cũ."""
        self.assertEqual("", trich_dan("Số: 15/2020/NĐ-CP\nĐiều 1. Phạm vi"))

    # Trích nguyên phần đầu một bản án THẬT trên congbobanan.toaan.gov.vn
    # (ID 1358254) — dạng trình bày khác hẳn văn bản QPPL.
    BAN_AN = """TÒA ÁN NHÂN DÂN HUYỆN ĐẮK SONG TỈNH ĐẮK NÔNG
Bản án số: 58/2023/HNGĐ-ST. Ngày: 29/9/2023 “V/v ly hôn, tranh chấp về nuôi con”.

CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM
Căn cứ Quyết định hoãn phiên toà số: 37/2023/QĐST - HNGĐ, ngày 25/8/2023;
"""

    def test_ban_an_that_doc_dung_so_hieu_loai_va_ngay(self):
        m = boc_metadata(self.BAN_AN)
        self.assertEqual("58/2023/HNGĐ-ST", m["so_hieu"])
        self.assertEqual("Bản án", m["loai_van_ban"])
        self.assertEqual("Bản án số 58/2023/HNGĐ-ST", trich_dan(self.BAN_AN))

    def test_khong_lay_ngay_cua_van_ban_duoc_dan_chieu(self):
        """Ngày ban hành phải là 29/9 của chính bản án, KHÔNG phải 25/8 của
        quyết định hoãn phiên toà nó dẫn chiếu — dấu phẩy giữa câu có ở khắp
        nơi, chỉ dòng địa danh đứng riêng mới đáng tin."""
        self.assertEqual(date(2023, 9, 29),
                         boc_metadata(self.BAN_AN)["ngay_ban_hanh"])

    def test_dong_dia_danh_van_ban_qppl_van_doc_dung(self):
        self.assertEqual(date(2019, 11, 20),
                         boc_metadata(BO_LUAT)["ngay_ban_hanh"])

    def test_so_hieu_cung_dong_tieu_de_khong_lot_vao_trich_yeu(self):
        text = ("NGHỊ ĐỊNH số 145/2020/NĐ-CP\n"
                "Quy định chi tiết Bộ luật Lao động\nĐiều 1. Phạm vi")
        m = boc_metadata(text)
        self.assertEqual("145/2020/NĐ-CP", m["so_hieu"])
        self.assertNotIn("145/2020", m["trich_yeu"] or "")
        self.assertEqual(1, trich_dan(text).count("145/2020/NĐ-CP"))


class UuTienHieuLucTests(unittest.TestCase):
    """Phạt điểm văn bản mất hiệu lực trong rerank — hàm thuần bên rag."""

    def _item(self, **kw):
        base = {"doc_type": "law", "score": 0.60,
                "trang_thai_hieu_luc": "chua_ro"}
        base.update(kw)
        return base

    def test_het_hieu_luc_bi_phat(self):
        from app.rag import uu_tien_hieu_luc
        items = [self._item(trang_thai_hieu_luc="het_hieu_luc")]
        uu_tien_hieu_luc(items, san=0.26)
        self.assertAlmostEqual(0.52, items[0]["score"], places=3)

    def test_khong_phat_xuong_duoi_san(self):
        """Cảnh báo, không chặn: phạt không được đẩy nguồn xuống dưới MIN_SCORE
        (0.25) — văn bản cũ vẫn phải hiện được để đối chiếu lịch sử."""
        from app.rag import MIN_SCORE, uu_tien_hieu_luc
        items = [self._item(score=0.30, trang_thai_hieu_luc="het_hieu_luc")]
        uu_tien_hieu_luc(items, san=MIN_SCORE + 0.01)
        self.assertGreater(items[0]["score"], MIN_SCORE)

    def test_san_bam_theo_nguong_loc_dang_cau_hinh(self):
        """Admin nâng min_relevance lên 0.35 mà sàn cứng 0.26 thì văn bản hết
        hiệu lực bị lọc CÂM khỏi kết quả — hoá ra chặn, trái nguyên tắc hệ."""
        from app.rag import uu_tien_hieu_luc
        items = [self._item(score=0.38, trang_thai_hieu_luc="het_hieu_luc")]
        uu_tien_hieu_luc(items, san=0.36)
        self.assertGreater(items[0]["score"], 0.35)

    def test_khong_dung_vao_van_ban_thuong(self):
        from app.rag import uu_tien_hieu_luc
        items = [self._item(doc_type="contract",
                            trang_thai_hieu_luc="het_hieu_luc")]
        uu_tien_hieu_luc(items, san=0.26)
        self.assertEqual(0.60, items[0]["score"])

    def test_chua_ro_va_con_hieu_luc_khong_bi_phat(self):
        from app.rag import uu_tien_hieu_luc
        items = [self._item(), self._item(trang_thai_hieu_luc="con_hieu_luc")]
        uu_tien_hieu_luc(items, san=0.26)
        self.assertEqual([0.60, 0.60], [i["score"] for i in items])


if __name__ == "__main__":
    unittest.main()
