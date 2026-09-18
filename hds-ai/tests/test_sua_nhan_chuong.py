"""
Test bước --sua-nhan của backfill (18/09/2026): sửa NHÃN Chương/Mục của đoạn
luật đã học mà KHÔNG embed lại.

Chay: python -m unittest tests.test_sua_nhan_chuong -v

Ba thứ phải đứng vững:
  1. Đoạn chỉ khác NHÃN → sửa được, và chỉ những đoạn thật sự sai mới nằm
     trong danh sách ghi (không đụng 390 nghìn đoạn còn nguyên).
  2. THÂN đoạn khác đi → BỎ QUA cả văn bản: bộ cắt đã đổi cách chia, vá nhãn
     lúc đó là ghi đè nội dung bằng bản cắt mới mà vector vẫn của bản cũ.
  3. Lệch số đoạn → bỏ qua, nêu lý do.
"""
import unittest

from app.backfill_van_ban import doi_chieu_nhan, tach_nhan
from app.ingest import chunk_law_structured


class TachNhanTests(unittest.TestCase):
    def test_tach_dung_dong_nhan(self):
        nhan, than = tach_nhan("[Luật X số 1/2020 — Chương II — Điều 5]\nĐiều 5. Nội dung")
        self.assertEqual(nhan, "[Luật X số 1/2020 — Chương II — Điều 5]")
        self.assertEqual(than, "Điều 5. Nội dung")

    def test_doan_khong_co_nhan(self):
        self.assertEqual(tach_nhan("Điều 5. Nội dung"), ("", "Điều 5. Nội dung"))
        # Dòng mở "[" nhưng không đóng "]" thì KHÔNG phải nhãn.
        self.assertEqual(tach_nhan("[chưa đóng\nthân"), ("", "[chưa đóng\nthân"))


class DoiChieuNhanTests(unittest.TestCase):
    LAW_CU = """LUẬT DOANH NGHIỆP
Số: 59/2020/QH14

Chương III
CÔNG TY TRÁCH NHIỆM HỮU HẠN

Mục 2. CÔNG TY TRÁCH NHIỆM HỮU HẠN MỘT THÀNH VIÊN

Điều 74. Công ty trách nhiệm hữu hạn một thành viên
Nội dung điều 74.

Chương V
CÔNG TY CỔ PHẦN

Điều 113. Thanh toán cổ phần đã đăng ký mua
Trong thời hạn 90 ngày kể từ ngày được cấp Giấy chứng nhận đăng ký doanh nghiệp.
"""

    def _rows_tu_pieces(self, pieces, nhan_sai_o=None):
        """Giả lập đoạn ĐÃ HỌC trong kho; nhan_sai_o: chỉ số đoạn mang nhãn cũ sai."""
        rows = []
        for i, p in enumerate(pieces):
            content, section = p.content, p.section_title
            if nhan_sai_o is not None and i == nhan_sai_o:
                nhan, than = tach_nhan(p.content)
                sai = nhan.replace("Chương V", "Chương V, Mục 2. CÔNG TY TRÁCH "
                                               "NHIỆM HỮU HẠN MỘT THÀNH VIÊN")
                content = f"{sai}\n{than}"
                section = (p.section_title or "").replace(
                    "Chương V", "Chương V, Mục 2. CÔNG TY TRÁCH NHIỆM HỮU HẠN MỘT THÀNH VIÊN")
            rows.append((100 + i, i, content, section))
        return rows

    def test_chi_sua_dung_doan_sai_nhan(self):
        pieces = chunk_law_structured(self.LAW_CU)
        i_113 = next(i for i, p in enumerate(pieces) if p.source_locator == "dieu:113")
        rows = self._rows_tu_pieces(pieces, nhan_sai_o=i_113)
        sua, vi_sao = doi_chieu_nhan(pieces, rows)
        self.assertEqual(vi_sao, "")
        self.assertEqual(len(sua), 1)          # chỉ một đoạn, không đụng phần còn lại
        cid, content, section = sua[0]
        self.assertEqual(cid, 100 + i_113)
        self.assertIn("Chương V", section)
        self.assertNotIn("Mục", section)       # nhãn mới đã bỏ Mục của Chương III
        self.assertIn("Trong thời hạn 90 ngày", content)   # thân giữ nguyên

    def test_khong_sai_thi_khong_ghi_gi(self):
        pieces = chunk_law_structured(self.LAW_CU)
        sua, vi_sao = doi_chieu_nhan(pieces, self._rows_tu_pieces(pieces))
        self.assertEqual((sua, vi_sao), ([], ""))

    def test_than_doan_khac_thi_bo_qua_ca_van_ban(self):
        pieces = chunk_law_structured(self.LAW_CU)
        rows = self._rows_tu_pieces(pieces)
        cid, idx, content, section = rows[-1]
        nhan, than = tach_nhan(content)
        rows[-1] = (cid, idx, f"{nhan}\n{than} — người duyệt đã sửa tay", section)
        sua, vi_sao = doi_chieu_nhan(pieces, rows)
        self.assertEqual(sua, [])
        self.assertIn("thân đoạn", vi_sao)

    def test_lech_so_doan_thi_bo_qua(self):
        pieces = chunk_law_structured(self.LAW_CU)
        rows = self._rows_tu_pieces(pieces)[:-1]
        sua, vi_sao = doi_chieu_nhan(pieces, rows)
        self.assertEqual(sua, [])
        self.assertIn("lệch số đoạn", vi_sao)


if __name__ == "__main__":
    unittest.main()
