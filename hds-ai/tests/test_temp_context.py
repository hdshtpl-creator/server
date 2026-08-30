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

    def _cai(self, doan, fname="hop dong.docx", summary=None):
        # Khuôn 3 cột đúng như SELECT thật: filename, embedding_json, summary.
        rows = [(fname, [{"content": c, "vec": [0.0] * 4} for c in doan], summary)]
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
        self._cai(doan, summary="Bản tóm tắt toàn văn của hợp đồng.")
        out = rag.get_temp_context(7, "hỏi gì đó", query_vector=[0.0] * 4,
                                   full_chars=2000)
        self.assertGreater(len(out), 0)
        self.assertLess(len(out), 20, "quá ngân sách thì phải lọc bớt")
        # Nguồn ĐẦU là bản tóm tắt toàn văn — cách đọc file vượt cửa sổ.
        self.assertIn("Tóm tắt file", out[0]["title"])
        self.assertIn("toàn văn", out[0]["content"])
        chi_tiet = [o["content"] for o in out[1:]]
        self.assertEqual(chi_tiet, sorted(chi_tiet, key=lambda c: doan.index(c)))

    def test_qua_lon_ma_chua_kip_tom_tat_thi_noi_that(self):
        doan = [f"doan {i} " + "x" * 500 for i in range(20)]
        self._cai(doan, summary=None)
        out = rag.get_temp_context(7, "tóm tắt", query_vector=[0.0] * 4,
                                   full_chars=2000)
        # Không được im lặng bỏ file: phải có nguồn báo tóm tắt đang chuẩn bị.
        self.assertIn("đang được", out[0]["content"])

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


class ChiaKhucTests(unittest.TestCase):
    """_chia_khuc: nền tảng của tóm tắt map-reduce cho file dài."""

    def test_van_ban_ngan_giu_nguyen(self):
        self.assertEqual(rag._chia_khuc("ngắn thôi", 100), ["ngắn thôi"])

    def test_rong_thi_khong_co_khuc_nao(self):
        self.assertEqual(rag._chia_khuc("", 100), [])
        self.assertEqual(rag._chia_khuc(None, 100), [])

    def test_ghep_lai_du_noi_dung(self):
        text = "Điều 1. Nội dung A. " * 500     # ~10.000 ký tự
        khuc = rag._chia_khuc(text, 3000)
        self.assertGreater(len(khuc), 2)
        self.assertEqual("".join(khuc), text, "chia xong ghép lại phải đủ chữ")
        for k in khuc:
            self.assertLessEqual(len(k), 3000)

    def test_uu_tien_cat_o_ranh_cau(self):
        text = ("Câu một dài dài. " * 100) + "Câu chốt."
        khuc = rag._chia_khuc(text, 1000)
        # Mọi khúc (trừ khúc cuối) kết thúc ở ranh giới câu, không cắt giữa từ.
        for k in khuc[:-1]:
            self.assertTrue(k.rstrip().endswith("."), repr(k[-30:]))


class TranNguCanhTests(unittest.TestCase):
    """_context_char_cap: 'đọc trọn' vẫn phải nằm trong cửa sổ ngữ cảnh.

    Ca thật 29/08/2026: 3 file đính kèm ≈ 235 nghìn ký tự đẩy 72 nguồn vào
    prompt, vượt num_ctx, Ollama cắt PHẦN ĐẦU — model mù toàn bộ tài liệu và
    trả lời "Mình sẽ tuân thủ đúng các hướng dẫn bạn đưa ra...".
    """

    def test_cau_hinh_0_thi_lay_tran_vat_ly(self):
        # num_ctx 32768 → ~60 nghìn ký tự cho tài liệu, không phải vô hạn.
        cap = rag._context_char_cap(32768, 0)
        self.assertGreater(cap, 20_000)
        self.assertLess(cap, 32768 * 3)

    def test_cau_hinh_lon_hon_tran_thi_bi_kep(self):
        self.assertEqual(rag._context_char_cap(32768, 10_000_000),
                         rag._context_char_cap(32768, 0))

    def test_cau_hinh_nho_hon_tran_thi_ton_trong(self):
        # Admin đặt 6000 để cứu máy yếu — không được lặng lẽ nới ra.
        self.assertEqual(rag._context_char_cap(32768, 6000), 6000)

    def test_may_ctx_nho_thi_san_co_theo_cua_so(self):
        # Máy chủ thật chạy num_ctx=10000 (admin hạ cho vừa VRAM): sàn cứng
        # 20 nghìn ký tự khi đó CAO HƠN cửa sổ chứa nổi → prompt tràn, Ollama
        # cắt đầu. Sàn phải theo tỷ lệ cửa sổ, và luôn NHỎ hơn sức chứa.
        for ctx in (8192, 10000, 16384):
            cap = rag._context_char_cap(ctx, 0)
            self.assertGreater(cap, 0)
            self.assertLess(cap, int(ctx * 2.6),
                            f"num_ctx={ctx}: trần tài liệu phải chừa chỗ "
                            "cho hướng dẫn + lịch sử")

    def test_ctx_10000_khong_con_bi_san_cung_day_tran(self):
        # Đúng ca máy chủ thật: 10000 token ≈ 26 nghìn ký tự cả prompt.
        cap = rag._context_char_cap(10000, 0)
        self.assertLessEqual(cap, 16_000)
        self.assertGreaterEqual(cap, 10_000)

    def test_ca_that_235k_bi_kep_xuong_duoi_tran(self):
        cap = rag._context_char_cap(32768, 0)
        self.assertLess(cap, 235_000)


if __name__ == "__main__":
    unittest.main()
