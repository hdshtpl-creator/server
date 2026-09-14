"""
Test app/doc_factory.py — phần THUẦN (không cần PostgreSQL/Ollama).

Chay: python -m unittest tests.test_doc_factory -v

Luồng "tạo bộ file" đứng trên hai chân: kế hoạch JSON của model phải được
kiểm tra chặt (số file có trần, thiếu tên là loại), và prompt phải nói rõ
nguồn dữ liệu + cấm bịa — vì file sinh ra sẽ gửi cho khách.
"""
import unittest

from app import doc_factory as df


class ParsePlanTests(unittest.TestCase):
    def test_ke_hoach_hop_le(self):
        raw = ('{"files": [{"ten_file": "DNTT-02 đợt 2", "khuon": "mau_kho", '
               '"yeu_cau": "50% còn lại, dẫn chiếu BBNT-01"}, '
               '{"ten_file": "BBNT-01 nghiệm thu website", "khuon": "soan_moi", '
               '"yeu_cau": "checklist 9 mục"}], '
               '"ghi_chu": "ngày tháng để trống"}')
        files, ghi_chu = df.parse_plan(raw)
        self.assertEqual(len(files), 2)
        self.assertEqual(files[0]["ten_file"], "DNTT-02 đợt 2")
        self.assertEqual(files[0]["khuon"], "mau_kho")
        self.assertEqual(files[1]["khuon"], "soan_moi")
        self.assertEqual(ghi_chu, "ngày tháng để trống")

    def test_mac_dinh_khong_tran(self):
        # 15/09/2026: bỏ trần 8 file — bộ hồ sơ 30-100 file phải ra đủ.
        items = ", ".join(f'{{"ten_file": "File {i}", "khuon": "soan_moi"}}'
                          for i in range(40))
        files, _ = df.parse_plan(f'{{"files": [{items}]}}')
        self.assertEqual(len(files), 40)
        self.assertEqual(df.MAX_FILES, 0)

    def test_admin_dat_tran_thi_cat(self):
        items = ", ".join(f'{{"ten_file": "File {i}", "khuon": "soan_moi"}}'
                          for i in range(20))
        files, _ = df.parse_plan(f'{{"files": [{items}]}}', max_files=8)
        self.assertEqual(len(files), 8)

    def test_thieu_ten_file_bi_loai(self):
        files, _ = df.parse_plan(
            '{"files": [{"ten_file": "", "khuon": "soan_moi"}, '
            '{"ten_file": "Giấy đề nghị", "khuon": "soan_moi"}]}')
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0]["ten_file"], "Giấy đề nghị")

    def test_khong_co_file_nao_bao_loi(self):
        with self.assertRaises(ValueError):
            df.parse_plan('{"files": [], "ghi_chu": "?"}')

    def test_khuon_mac_dinh_soan_moi(self):
        files, _ = df.parse_plan('{"files": [{"ten_file": "Biên bản"}]}')
        self.assertEqual(files[0]["khuon"], "soan_moi")

    def test_json_trong_fence_va_think(self):
        raw = ('<think>nghĩ đã</think>```json\n'
               '{"files": [{"ten_file": "X", "khuon": "soan_moi"}]}\n```')
        files, _ = df.parse_plan(raw)
        self.assertEqual(files[0]["ten_file"], "X")


class PlanPromptTests(unittest.TestCase):
    def test_liet_ke_du_cac_lua_chon_khuon(self):
        prompt, system = df.build_plan_prompt(
            "Làm đợt 2-3 và nghiệm thu",
            [("HD dot 1.pdf", "Hợp đồng số 05/2026, TK 1236789789", False),
             ("Mau DNTT.docx", "GIẤY ĐỀ NGHỊ THANH TOÁN", True)],
            "Giấy đề nghị thanh toán mẫu")
        self.assertIn("mau_kho", prompt)
        self.assertIn("Giấy đề nghị thanh toán mẫu", prompt)
        self.assertIn("Mau DNTT.docx", prompt)          # khuôn tải lên
        self.assertIn("CÓ BẢN .docx GỐC", prompt)
        self.assertIn("soan_moi", prompt)
        self.assertIn("không bịa", prompt)
        self.assertIn("JSON", system)

    def test_khong_dinh_kem_van_chay(self):
        prompt, _ = df.build_plan_prompt("Soạn 2 giấy đề nghị thanh toán", [], None)
        self.assertIn("Soạn 2 giấy đề nghị", prompt)
        self.assertNotIn("FILE ĐÍNH KÈM", prompt)


class DraftPromptTests(unittest.TestCase):
    def test_prompt_soan_moi_cam_bia_va_co_du_lieu(self):
        prompt, system = df.build_draft_prompt(
            "BBNT-01 Nghiệm thu website", "checklist 9 mục",
            "Nghiệm thu để làm căn cứ thanh toán đợt 2",
            [("HD dot 1.pdf", "Số HĐ 05/2026/HĐ-DV ký 26/08/2026", False)],
            "ngày để trống")
        self.assertIn("BBNT-01 Nghiệm thu website", prompt)
        self.assertIn("Số HĐ 05/2026/HĐ-DV", prompt)
        self.assertIn("[CẦN BỔ SUNG", prompt)
        self.assertIn("không bịa", prompt)
        self.assertIn("Markdown", system)


class CleanMarkdownTests(unittest.TestCase):
    def test_boc_fence_va_think(self):
        raw = ("<think>đang nghĩ</think>\n```markdown\n"
               "# GIẤY ĐỀ NGHỊ THANH TOÁN\n- Đợt 2: 2.000.000đ\n```")
        out = df.clean_markdown(raw)
        self.assertTrue(out.startswith("# GIẤY ĐỀ NGHỊ THANH TOÁN"))
        self.assertIn("2.000.000đ", out)
        self.assertNotIn("```", out)
        self.assertNotIn("think", out)

    def test_markdown_tran_giu_nguyen(self):
        self.assertEqual(df.clean_markdown("# A\nB"), "# A\nB")


if __name__ == "__main__":
    unittest.main()
