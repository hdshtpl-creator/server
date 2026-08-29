"""File đính kèm trong chat phải tới tay model NGUYÊN VẸN.

Ca thật 29/08/2026: tải một .docx 19.368 ký tự lên, chip báo đọc xong, hỏi
"tóm tắt" — bot trả lời như chưa từng thấy file. Hai lỗi chồng nhau:

  1. get_temp_context chỉ lấy 5 đoạn giống câu hỏi nhất. "tóm tắt" không mang
     nội dung gì để so vector nên 5 đoạn đó gần như ngẫu nhiên.
  2. Prompt đánh số nguồn trên (kho + file) trong khi bộ kiểm chứng chỉ biết
     kho, nên trích dẫn trỏ vào file mang số vượt trần -> bị xoá -> đoạn văn
     bị lược theo luật chặn-không-căn-cứ.

Test ở đây chặn lỗi 1 và phần thuần logic của lỗi 2. Không chạm CSDL:
deploy/update.sh chạy nguyên bộ test ngay trên máy chủ đang phục vụ.
"""
import unittest

from app import rag


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, *a, **kw):
        return None

    def fetchall(self):
        return self._rows

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows

    def cursor(self):
        return _FakeCursor(self._rows)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TempContextTests(unittest.TestCase):
    """get_temp_context: đưa TRỌN file khi còn vừa ngân sách."""

    def setUp(self):
        self.goc = rag.db.session

    def tearDown(self):
        rag.db.session = self.goc

    def _cai(self, doan, fname="hop dong.docx"):
        rows = [(fname, [{"content": c, "vec": [0.0] * 4} for c in doan])]
        rag.db.session = lambda *a, **kw: _FakeConn(rows)

    def test_dua_tron_file_theo_dung_thu_tu(self):
        self._cai(["Điều 1. Phạm vi", "Điều 2. Giá", "Điều 3. Thanh toán",
                   "Điều 4. Phạt", "Điều 5. Chấm dứt", "Điều 6. Hiệu lực"])
        out = rag.get_temp_context(7, "tóm tắt", query_vector=[0.0] * 4)
        # SÁU đoạn, không phải 5 — và đúng thứ tự điều khoản.
        self.assertEqual(len(out), 6)
        self.assertEqual([o["content"] for o in out][0], "Điều 1. Phạm vi")
        self.assertEqual([o["content"] for o in out][-1], "Điều 6. Hiệu lực")

    def test_khong_co_file_thi_rong(self):
        self._cai([])
        self.assertEqual(rag.get_temp_context(7, "tóm tắt", query_vector=[0.0] * 4), [])

    def test_file_qua_lon_thi_loc_nhung_van_dung_thu_tu(self):
        doan = [f"doan {i} " + "x" * 500 for i in range(20)]
        self._cai(doan)
        out = rag.get_temp_context(7, "hỏi gì đó", query_vector=[0.0] * 4,
                                   full_chars=2000)
        self.assertGreater(len(out), 0)
        self.assertLess(len(out), 20, "quá ngân sách thì phải lọc bớt")
        thu_tu = [o["content"] for o in out]
        self.assertEqual(thu_tu, sorted(thu_tu, key=lambda c: doan.index(c)))

    def test_tieu_de_mang_ten_file(self):
        self._cai(["nội dung"], fname="011_2023 HĐM 77.docx")
        out = rag.get_temp_context(7, "tóm tắt", query_vector=[0.0] * 4)
        self.assertIn("011_2023 HĐM 77.docx", out[0]["title"])


class DanhSoNguonTests(unittest.TestCase):
    """Số nguồn trong prompt phải khớp bảng nguồn và bộ kiểm chứng.

    Lệch một nhịp là trích dẫn vào file đính kèm bị coi là bịa và bị xoá.
    """

    def test_evidence_danh_so_lien_tuc_tu_1(self):
        gop = [{"title": "[File: a.docx]", "content": "nội dung file", "score": 1.0},
               {"title": "Luật X", "content": "điều khoản", "score": 0.9}]
        ev = rag.format_sources(gop)
        self.assertEqual([e["n"] for e in ev], [1, 2])
        # Nguồn 1 là FILE người dùng vừa đưa, không phải tài liệu kho.
        self.assertIn("a.docx", ev[0]["title"])

    def test_kiem_chung_chap_nhan_moi_so_trong_danh_sach(self):
        gop = [{"content": "nội dung file"}, {"content": "điều khoản"}]
        text, status = rag.validate_grounding(
            "Hợp đồng quy định như sau [Nguồn 2].", gop,
            answer_mode="grounded", strict=True)
        self.assertIn("[Nguồn 2]", text)
        self.assertNotEqual(status, "uncited_blocked")

    def test_so_nguon_vuot_tran_van_bi_xoa(self):
        # Chốt cũ vẫn phải giữ: model bịa [Nguồn 9] khi chỉ có 2 nguồn.
        gop = [{"content": "nội dung file"}, {"content": "điều khoản"}]
        text, _ = rag.validate_grounding(
            "Một khẳng định dài đủ để bị soi [Nguồn 9].", gop,
            answer_mode="grounded", strict=True)
        self.assertNotIn("[Nguồn 9]", text)


if __name__ == "__main__":
    unittest.main()
