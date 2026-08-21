"""Regression tests cho các lỗi chất lượng đã gặp ngoài thực tế.

Chạy trên máy chủ:
    python -m unittest tests.test_quality -v

Các test này không cần PostgreSQL/Ollama; chúng giữ ổn định router, câu nối tiếp
và cổng citation trước khi chạy bộ eval end-to-end với dữ liệu thật.
"""
import unittest
from unittest.mock import patch

from app import company_context, rag


class IntentTests(unittest.TestCase):
    def test_nv_alias_is_staff(self):
        self.assertEqual(
            company_context.infer_intent("hds có bao nhiêu nv"),
            "staff_directory",
        )

    def test_company_people_is_staff_not_clients(self):
        self.assertEqual(
            company_context.infer_intent("cty tôi có mấy người"),
            "staff_directory",
        )

    def test_employment_contract_is_not_account_count(self):
        self.assertEqual(
            company_context.infer_intent("có bao nhiêu người trong HDS còn hợp đồng"),
            "employment_contract",
        )

    def test_bare_nhan_su_is_staff_query(self):
        """Lỗi thực tế: 'tất cả nhân sự trước giờ…' trượt hết từ khoá.

        Danh sách cũ chỉ có cụm ghép ('danh sách nhân sự', 'nhân sự công ty'),
        nên câu hỏi tự nhiên nhất lại không được nhận là câu nhân sự — bot mò
        bằng vector, vớ phải Điều lệ công ty và trả lời công ty có 01 người.
        """
        self.assertTrue(company_context.is_staff_query(
            "tất cả nhân sự trước giờ bao gồm cả hết hạn"))
        self.assertTrue(company_context.is_staff_query("công ty có mấy nhân viên"))

    def test_unrelated_legal_question_is_not_staff_query(self):
        """Không được bắt nhầm: 'nhân thân' không phải 'nhân sự'."""
        self.assertFalse(company_context.is_staff_query(
            "quy định về nhân thân người phạm tội"))
        self.assertFalse(company_context.is_staff_query(
            "thủ tục thành lập doanh nghiệp"))

    def test_hr_document_question_is_staff_query(self):
        """Lỗi thực tế 19/08: 'sơ yếu lí lịch cửa Ngân' (kèm typo) không được
        nhận là câu nhân sự → tìm toàn kho, vớ sơ yếu của NGƯỜI KHÁC 37% và
        phiếu lý lịch tư pháp của KHÁCH, rồi từ chối trả lời."""
        self.assertTrue(company_context.is_staff_query("sơ yếu lí lịch cửa Ngân"))
        self.assertTrue(company_context.is_staff_query("sơ yếu lý lịch của Ngân"))
        self.assertTrue(company_context.is_staff_query("CV của Mai"))
        self.assertTrue(company_context.is_staff_query("KPI quý của Ngân thế nào"))

    def test_hr_document_question_is_not_structured_count(self):
        """Câu hỏi NỘI DUNG giấy tờ không được nuốt thành bảng đếm quân số."""
        self.assertIsNone(company_context.infer_intent("sơ yếu lí lịch cửa Ngân"))
        self.assertIsNone(company_context.infer_intent("CV của Mai"))

    def test_hr_doc_words_do_not_overreach(self):
        """'cv' phải theo ranh giới từ (không match TCVN); lý lịch TƯ PHÁP là
        giấy của khách hàng, không phải hồ sơ nhân sự."""
        self.assertFalse(company_context.is_staff_query("tiêu chuẩn TCVN về xây dựng"))
        self.assertFalse(company_context.is_staff_query("phiếu lý lịch tư pháp là gì"))


class LexicalFallbackTests(unittest.TestCase):
    """Lỗi thực tế 19/08: 'sơ yếu LÍ lịch CỬA Ngân' (i ngắn + gõ nhầm) làm
    plainto_tsquery (AND mọi từ) trắng tay — nhánh từ khoá chết, chỉ còn
    semantic, và từ 'Ngân' mất sạch sức nặng nên bot lấy sơ yếu người khác."""

    def test_or_query_keeps_accents_and_order(self):
        from app import rag
        q = rag._or_tsquery("sơ yếu lí lịch cửa Ngân")
        # GIỮ DẤU vì chỉ mục 'simple' lưu token có dấu; bỏ dấu là hết khớp.
        self.assertEqual(q, "sơ | yếu | lí | lịch | cửa | ngân")

    def test_or_query_drops_short_and_duplicate_tokens(self):
        from app import rag
        self.assertEqual(rag._or_tsquery("a hợp đồng hợp đồng b"), "hợp | đồng")
        self.assertIsNone(rag._or_tsquery("a b ."))
        self.assertIsNone(rag._or_tsquery(""))

    def test_or_query_strips_tsquery_operators(self):
        from app import rag
        # Ký tự điều khiển tsquery (&, |, !, :, *) không được lọt vào chuỗi.
        q = rag._or_tsquery("điều 35 & khoản! 2:*")
        self.assertEqual(q, "điều | 35 | khoản")


class FolderScopeTests(unittest.TestCase):
    """30 mẫu: câu hỏi phải được hiểu là đang nhắm vào NGĂN NÀO của cây thư mục
    Drive (CAU_TRUC_DRIVE.md), để tìm kiếm chạy trong đúng ngăn — tên thư mục
    kết hợp nội dung văn bản — thay vì so vector toàn kho.

    set() nghĩa là "không đoán" — các câu đó đã có đường riêng (hồ sơ khách,
    nhân sự, câu đếm structured) hoặc mơ hồ thật sự thì giữ tìm toàn kho."""

    CASES = [
        # ---- Ngăn 1: VĂN BẢN PHÁP LUẬT ----
        ("thời hiệu khởi kiện tranh chấp đất là bao lâu", {"law"}),
        ("nghị định về xử phạt vi phạm hành chính trong xây dựng", {"law"}),
        ("thông tư 55 quy định về đầu tư có nội dung gì", {"law"}),
        ("theo luật lao động thì người lao động được nghỉ mấy ngày phép", {"law"}),
        ("mức phạt chậm nộp thuế là bao nhiêu", {"law"}),
        ("văn bản hợp nhất luật doanh nghiệp mới nhất", {"law"}),
        ("căn cứ pháp lý để đơn phương chấm dứt hợp đồng thuê nhà", {"law"}),
        # ---- Ngăn 2: BẢN ÁN – ÁN LỆ (hỏi một loại lấy cả ngăn) ----
        ("có bản án nào về tranh chấp lối đi chung không", {"ban_an", "an_le"}),
        ("án lệ về hợp đồng vay tài sản", {"an_le", "ban_an"}),
        ("tiền lệ xét xử tranh chấp thừa kế thế nào", {"an_le", "ban_an"}),
        ("phán quyết của toà về đặt cọc mua đất", {"ban_an", "an_le"}),
        # ---- Ngăn 3: HỢP ĐỒNG MẪU ----
        ("cho tôi mẫu hợp đồng thuê nhà xưởng", {"mau_hd"}),
        ("hợp đồng mẫu mua bán hàng hóa quốc tế", {"mau_hd"}),
        ("điều khoản mẫu về bảo mật thông tin", {"mau_hd"}),
        # ---- Ngăn 4: QUAN ĐIỂM PHÁP LÝ ----
        ("quan điểm pháp lý về góp vốn bằng quyền sử dụng đất", {"advisory"}),
        ("ý kiến pháp lý về việc sáp nhập hai công ty con", {"advisory"}),
        # ---- Ngăn 5: THƯ MẪU – BIỂU MẪU ----
        ("mẫu đơn xin ly hôn thuận tình", {"thu_mau"}),
        ("biểu mẫu tờ khai đăng ký doanh nghiệp", {"thu_mau"}),
        ("mẫu thư gửi khách hàng thông báo tăng phí", {"thu_mau"}),
        # ---- Ngăn 6: QUY TRÌNH NỘI BỘ ----
        ("quy trình tiếp nhận vụ việc mới của công ty", {"quy_trinh"}),
        ("quy trình tố tụng gồm những bước nào", {"quy_trinh"}),
        # ---- Ngăn 7: NHÃN HIỆU – SHTT ----
        ("thủ tục đăng ký nhãn hiệu mất bao lâu", {"nhan_hieu"}),
        ("tra cứu thương hiệu này đã được bảo hộ chưa", {"nhan_hieu"}),
        ("hồ sơ sở hữu trí tuệ cần những giấy tờ gì", {"nhan_hieu"}),
        # ---- Câu chạm NHIỀU ngăn ----
        ("quy trình đăng ký nhãn hiệu cho khách mới", {"quy_trinh", "nhan_hieu"}),
        ("có án lệ hay điều luật nào về lãi suất cho vay không",
         {"an_le", "ban_an", "law"}),
        # ---- KHÔNG đoán: đã có đường riêng hoặc mơ hồ thật ----
        ("sơ yếu lý lịch của Ngân", set()),                     # nhân sự → is_staff_query
        ("hợp đồng của SUNGROUP có điều khoản phạt chậm thanh toán không",
         set()),                                                # hồ sơ khách → detect_clients
        ("đang lưu mấy khách", set()),                          # câu đếm → structured
        ("xin chào", set()),
    ]

    def test_thirty_folder_scope_samples(self):
        self.assertEqual(len(self.CASES), 30, "bộ mẫu phải đủ 30 câu")
        for question, expected in self.CASES:
            with self.subTest(question=question):
                got = set(company_context.detect_doc_scopes(question))
                self.assertEqual(got, expected)

    def test_scope_order_and_cap(self):
        # Ngăn xuất hiện trước trong câu đứng trước; không quá MAX_DOC_SCOPES.
        got = company_context.detect_doc_scopes(
            "quy trình đăng ký nhãn hiệu cho khách mới")
        self.assertEqual(got[0], "quy_trinh")
        self.assertLessEqual(len(got), company_context.MAX_DOC_SCOPES)


class InventoryAnswerTests(unittest.TestCase):
    """20/08/2026: 'án lệ có mấy bộ' nhận nguyên bảng 11 loại; 'liệt kê' thì
    lặp lại y chang. Hỏi đích danh một loại phải thấy TÊN từng bộ."""

    ROWS = [("filing", 57), ("mau_hd", 31), ("an_le", 3)]
    TITLES = {"an_le": ["Án lệ số 43", "Án lệ số 78", "Án lệ số 90"]}

    def test_specific_type_lists_names_not_full_table(self):
        lines = company_context._inventory_lines(["an_le"], self.ROWS, self.TITLES)
        text = "\n".join(lines)
        self.assertIn("3 tài liệu án lệ", text)
        for name in self.TITLES["an_le"]:
            self.assertIn(name, text)
        # Không đổ bảng toàn kho: các loại khác không xuất hiện thành dòng đếm.
        self.assertNotIn("hồ sơ nộp: 57", text)
        self.assertNotIn("mẫu hợp đồng: 31", text)

    def test_specific_type_empty_says_missing(self):
        lines = company_context._inventory_lines(["ban_an"], self.ROWS, {})
        self.assertIn("chưa có tài liệu bản án", "\n".join(lines))

    def test_general_question_keeps_full_table(self):
        lines = company_context._inventory_lines([], self.ROWS, {})
        text = "\n".join(lines)
        self.assertIn("hồ sơ nộp: 57", text)
        self.assertIn("án lệ: 3", text)

    def test_full_list_by_default_and_capped_when_admin_sets(self):
        """Chính sách 20/08/2026: mặc định (0) liệt kê ĐỦ, không cắt. Admin đặt
        số dương thì cắt nhưng phải tự khai '… và N khác'."""
        titles = {"law": [f"Luật số {i}" for i in range(1, 41)]}
        lines = company_context._inventory_lines(["law"], [("law", 40)], titles)
        text = "\n".join(lines)
        self.assertIn("Luật số 40", text)          # 0 = in hết
        self.assertNotIn("tài liệu khác", text)
        from unittest.mock import patch
        with patch.object(company_context, "INVENTORY_LIST_MAX", 15):
            capped = "\n".join(company_context._inventory_lines(
                ["law"], [("law", 40)], titles))
        self.assertIn("Luật số 15", capped)
        self.assertNotIn("Luật số 16", capped)
        self.assertIn("và 25 tài liệu khác", capped)

    def test_zero_budget_means_no_cut(self):
        """0 = không giới hạn ở mọi van nội dung."""
        long_text = "x" * 5000
        self.assertEqual(company_context._cut(long_text, 0), long_text)
        self.assertEqual(company_context._cut(long_text, 100)[:100], "x" * 100)
        from app import rag
        chunk = {"chunk_id": 1, "content": "y" * 9000, "title": "T", "score": 0.9}
        out = rag.fit_context([chunk], chunk_chars=0, budget=0, question="")
        self.assertEqual(len(out[0]["content"]), 9000)   # giữ trọn đoạn

    def test_tree_staff_lines_counts_folders_as_people(self):
        """Nguyên tắc 21/08: cây là nguồn sự thật — N bộ hồ sơ = N nhân sự,
        chi tiết nằm trong từng bộ."""
        rows = [("Mai", 11), ("Ngân", 10), ("Nhi", 8)]
        text = "\n".join(company_context._tree_staff_lines(rows))
        self.assertIn("3 bộ hồ sơ = 3 nhân sự", text)
        self.assertIn("Ngân** — 10 giấy tờ", text)
        self.assertIn("hỏi tiếp", text)   # chỉ đường đọc chi tiết trong bộ

    def test_inventory_declares_unlearned_files(self):
        """File trên cây chưa học được phải được KHAI, không đếm thiếu im lặng."""
        lines = company_context._inventory_lines(
            ["ban_an"], [("ban_an", 4)], {"ban_an": ["BA 1", "BA 2", "BA 3", "BA 4"]},
            unlearned=1)
        text = "\n".join(lines)
        self.assertIn("4 tài liệu bản án", text)
        self.assertIn("1 file trên cây Drive CHƯA học được", text)

    def test_warehouse_map_shows_staff_sets_and_clients(self):
        rows = [("ho_so_ns", False, 29), ("law", False, 15)]
        text = "\n".join(company_context._warehouse_lines(
            rows, staff_folders=[("Mai", 11), ("Ngân", 10), ("Nhi", 8)],
            client_count=3))
        self.assertIn("3 BỘ hồ sơ = 3 nhân sự (Mai, Ngân, Nhi)", text)
        self.assertIn("3 KHÁCH HÀNG", text)

    def test_warehouse_map_lines(self):
        """Bản đồ kho: ngăn 1–8 theo doc_type ngoài khách, ngăn 9 gom mọi giấy
        tờ thuộc khách — nạp mọi câu nội bộ để bot biết cây thư mục."""
        rows = [("law", False, 15), ("an_le", False, 3), ("ban_an", False, 4),
                ("ho_so_ns", False, 29), ("contract", True, 1),
                ("ho_so_kh", True, 3), ("other", False, 2)]
        text = "\n".join(company_context._warehouse_lines(rows))
        self.assertIn("1. VĂN BẢN PHÁP LUẬT: 15", text)
        self.assertIn("2. BẢN ÁN – ÁN LỆ: 7", text)
        self.assertIn("8. HỒ SƠ NHÂN SỰ: 29", text)
        self.assertIn("9. HỒ SƠ KHÁCH HÀNG: 4", text)
        self.assertIn("Khác/chưa xếp ngăn: 2", text)
        self.assertIn("57 tài liệu", text)   # tổng

    def test_followup_liet_ke_keeps_doc_inventory_intent(self):
        state = {"intent": "doc_inventory", "doc_types": ["an_le"]}
        self.assertEqual(company_context.infer_intent("liệt kê", state=state),
                         "doc_inventory")

    def test_followup_tom_tat_opens_document_instead_of_recount(self):
        """Ca thật 21/08: 'tóm tắt 90' hỏi ngay sau khi bot liệt kê 3 án lệ —
        phải rơi xuống luồng tra cứu (mở tài liệu) với câu tra được vay đủ
        ngữ cảnh 'án lệ', không lặp bảng đếm, không tra bằng số 90 trần trụi."""
        from app import rag
        state = {"intent": "doc_inventory", "doc_types": ["an_le"]}
        hist = [("user", "có mấy án lệ và tên"), ("assistant", "Kho có 3 án lệ.")]
        self.assertTrue(company_context._is_followup(company_context._fold("tóm tắt 90")))
        self.assertIsNone(company_context.infer_intent("tóm tắt 90",
                                                       history=hist, state=state))
        rewritten = rag.resolve_search_question("tóm tắt 90", hist, state)
        self.assertIn("án lệ", rewritten)
        self.assertIn("tóm tắt 90", rewritten)
        self.assertEqual(set(company_context.detect_doc_scopes(rewritten)),
                         {"an_le", "ban_an"})


class UnreadableFileTests(unittest.TestCase):
    """Yêu cầu 20/08/2026: đọc được TÊN file mà ruột hỏng thì bot phải nói
    'có file nhưng bên trong không đọc được' — tên người nằm ở THƯ MỤC."""

    FAILURES = [
        ("CV.pdf", "8. HỒ SƠ NHÂN SỰ/Ngân", "OCR PDF thất bại — file nhiều khả năng hỏng cấu trúc.",
         "Mở file bằng trình đọc PDF rồi lưu lại thành bản mới."),
        ("Hợp đồng dịch vụ.pdf", "9. HỒ SƠ KHÁCH HÀNG/[AGENTPRO]", "Không đọc được PDF.", ""),
    ]

    def test_question_about_person_matches_folder_name(self):
        got = company_context._match_unreadable("sơ yếu lý lịch của Ngân", self.FAILURES)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0][0], "CV.pdf")

    def test_unrelated_question_matches_nothing(self):
        self.assertEqual(
            company_context._match_unreadable("án lệ có mấy bộ", self.FAILURES), [])

    def test_stopword_only_question_matches_nothing(self):
        self.assertEqual(
            company_context._match_unreadable("cho tôi file pdf", self.FAILURES), [])


class PromptWarningTests(unittest.TestCase):
    """Đoạn nguồn từ file scan CÓ CẢNH BÁO phải được dán nhãn trong prompt để
    model nói 'nội dung chưa đọc được' thay vì suy đoán từ chữ OCR rác."""

    def _chunk(self, status):
        return {"chunk_id": 1, "content": "NỘI DUNG OCR CÓ THỂ RÁC", "title": "Ngân — CCCD",
                "document_id": 5, "doc_type": "ho_so_ns", "score": 0.9,
                "extraction_status": status}

    def test_warning_chunk_carries_caveat(self):
        from app import rag
        prompt = rag.build_prompt("số CCCD của Ngân", [self._chunk("warning")],
                                  chunk_chars=2000, budget=8000)
        self.assertIn("CÓ CẢNH BÁO", prompt)
        self.assertIn("chưa đọc được", prompt)

    def test_ready_chunk_has_no_caveat(self):
        from app import rag
        prompt = rag.build_prompt("số CCCD của Ngân", [self._chunk("ready")],
                                  chunk_chars=2000, budget=8000)
        self.assertNotIn("CÓ CẢNH BÁO", prompt)


class OcrGarbageTests(unittest.TestCase):
    """Ca thật 21/08/2026: panel Nguồn trích dẫn hiện nguyên khối ký tự vụn từ
    bản scan CCCD/bằng đại học. Người đọc thấy thứ đó được gọi là 'căn cứ' thì
    mất tin cả những nguồn đọc tốt nằm ngay cạnh."""

    # Chép nguyên từ màn hình người dùng (nguồn 5 và nguồn 8).
    GARBAGE_CCCD = ("[Trang 1] bai bel La n Å l Å _ ¬ _..' s _ ,ã bô ˚i lyML OI "
                    "NON CHỨNG THỰC BẢN $A0 BÙNG VỚI BẢN (Hồ Ø9-03-74-2013-·· "
                    ": dT | Ngày: 18-07-. 122 lyHd OM1 NOON Số chứng thực: "
                    "=sses=es.(QUYỀN Số:........ 9 TỊI CÔNG CHỨNG VIÊN dựng "
                    "˚ổúự Åui J/Åani ẫ")
    GARBAGE_SYLL = ("[Trang 1] IEOESJ: => SGO\\% bi CHỦ NGHĨA VIỆT NAM Ðề Mức: "
                    "Từ dã2N: 1 phú ALỔ 2 22s = -= vi 252277892 XS) S 9292 sản "
                    "sS: °I6 6T Tà xà ° ° AT 2: XE -Å. cục) \\OXSXSkMÅj ƒ 79/ Q "
                    "St 4 M*h JO/-Å ị TU V2 . s (6 : 2 fk T1 nh Tư ~Å.")

    CLEAN_CONTRACT = ("CÔNG TY LUẬT TNHH HDS CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM "
                      "Số: 28/HĐLĐ-HDS Độc lập - Tự do - Hạnh phúc HỢP ĐỒNG LAO "
                      "ĐỘNG Hôm nay, ngày 27 tháng 01 năm 2022 tại CÔNG TY LUẬT "
                      "TNHH HDS. Người Lao Động: Bà BẠC THỊ MAI Sinh ngày: "
                      "28/10/1996 Giới tính: Nữ Quốc tịch: Việt Nam")

    CLEAN_TABLE = ("[Bảng: BC Tính thưởng Tháng 7] BÁO CÁO CÔNG VIỆC THÁNG 07 "
                   "NĂM 2025: Cột 1 | Cột 2 | Cột 3 | Cột 4 | Cột 5 | Cột 6 | "
                   "Cột 7 | Cột 8 | Cột 9 | Cột 10 | Cột 11 | Cột 12")

    def test_nhan_ra_chu_ocr_hong(self):
        self.assertTrue(rag.looks_like_ocr_garbage(self.GARBAGE_CCCD))
        self.assertTrue(rag.looks_like_ocr_garbage(self.GARBAGE_SYLL))

    def test_van_ban_that_khong_bi_coi_la_rac(self):
        self.assertFalse(rag.looks_like_ocr_garbage(self.CLEAN_CONTRACT))
        # Dòng bảng đầy dấu | vẫn là nội dung thật — không được nhầm là rác.
        self.assertFalse(rag.looks_like_ocr_garbage(self.CLEAN_TABLE))

    def test_doan_ngan_khong_du_mau_thi_giu_nguyen(self):
        self.assertFalse(rag.looks_like_ocr_garbage("CÔNG CHỨNG VIÊN"))
        self.assertFalse(rag.looks_like_ocr_garbage(""))

    def test_prompt_thay_chu_rac_bang_loi_noi_that(self):
        prompt = rag.build_prompt(
            "số cccd của Mai",
            [{"chunk_id": 1, "content": self.GARBAGE_CCCD, "title": "Mai — CCCD",
              "doc_type": "ho_so_ns", "score": 0.6, "extraction_status": "warning"}],
            chunk_chars=0, budget=0)
        self.assertIn("CHƯA ĐỌC ĐƯỢC NỘI DUNG", prompt)
        self.assertNotIn("lyML", prompt)          # chữ vụn không vào prompt
        self.assertIn("Mai — CCCD", prompt)       # nhưng vẫn biết file tồn tại

    def test_panel_nguon_khong_hien_chu_rac(self):
        sources = rag.format_sources(
            [{"chunk_id": 1, "content": self.GARBAGE_CCCD, "title": "Mai — CCCD",
              "score": 0.6}])
        self.assertNotIn("lyML", sources[0]["quote"])
        self.assertIn("chưa đọc được", sources[0]["quote"])

    def test_nguon_tot_giu_nguyen_trich_dan(self):
        sources = rag.format_sources(
            [{"chunk_id": 2, "content": self.CLEAN_CONTRACT, "title": "HĐLĐ",
              "score": 0.9}])
        self.assertIn("28/10/1996", sources[0]["quote"])


class PersonFolderLabelTests(unittest.TestCase):
    """Mỗi đoạn hồ sơ nhân sự phải nói rõ nó thuộc BỘ CỦA AI. Ba bộ hồ sơ đọc
    na ná nhau (sơ yếu, CCCD, HĐLĐ) — thiếu nhãn là model gán số CCCD của
    người này cho người kia mà không có tín hiệu nào báo sai."""

    def _chunk(self, person, content):
        return {"chunk_id": hash(person) % 1000, "content": content,
                "title": f"{person} — Sơ yếu lý lịch", "document_id": 5,
                "doc_type": "ho_so_ns", "score": 0.9, "person_folder": person}

    def test_owner_tag_names_the_folder(self):
        tag = rag._source_owner_tag(self._chunk("Mai", "x"))
        self.assertIn("BỘ CỦA Mai", tag)

    def test_owner_tag_falls_back_when_folder_unknown(self):
        chunk = self._chunk("Mai", "x")
        chunk["person_folder"] = None
        self.assertIn("hồ sơ nhân sự", rag._source_owner_tag(chunk))

    def test_prompt_warns_against_mixing_people(self):
        prompt = rag.build_prompt(
            "chi tiết Mai",
            [self._chunk("Mai", "Sinh năm 1995, CCCD 049195003678."),
             self._chunk("Nhi", "Sinh năm 1990, CCCD 038090001234.")],
            chunk_chars=2000, budget=8000)
        self.assertIn("PHÂN BIỆT TỪNG NGƯỜI", prompt)
        self.assertIn("BỘ CỦA Mai", prompt)
        self.assertIn("BỘ CỦA Nhi", prompt)
        self.assertIn("không lấy họ tên, ngày sinh, số CCCD", prompt)

    def test_identity_documents_uu_tien_giay_to_dinh_danh(self):
        # Ca thật 21/08/2026: hỏi "chi tiết Mai", bot đọc trúng bảng công việc
        # tháng rồi kể tên cột; CV — nơi có ngày sinh — không lọt vào nguồn.
        pairs = [
            (1, "2026. Mẫu Báo Cáo Công Tháng. Mai"),
            (2, "Mai — CV"),
            (3, "Mai — KPI quý 3"),
            (4, "Mai — Sơ yếu lý lịch"),
            (5, "HĐLĐ BAC THI MAI"),
        ]
        got = rag.identity_documents(pairs)
        ids = [doc_id for doc_id, _ in got]
        self.assertIn(4, ids)                    # sơ yếu
        self.assertIn(2, ids)                    # CV
        self.assertIn(5, ids)                    # HĐLĐ
        self.assertNotIn(3, ids)                 # KPI không phải giấy định danh
        self.assertEqual(ids[0], 4)              # sơ yếu đứng trước CV
        # Báo cáo công việc chỉ lọt vì tiêu đề không có từ định danh nào.
        self.assertNotIn(1, ids)

    def test_identity_documents_gioi_han_so_luong(self):
        pairs = [(i, f"Mai — Hợp đồng {i}") for i in range(1, 20)]
        self.assertEqual(len(rag.identity_documents(pairs)), 6)

    def test_prompt_cam_liet_ke_ten_cot(self):
        prompt = rag.build_prompt(
            "chi tiết Mai",
            [{"chunk_id": 3, "content": "[Dòng 16] BÁO CÁO | Cột 3: 1142",
              "title": "Báo cáo tháng", "doc_type": "other", "score": 0.9}],
            chunk_chars=2000, budget=8000)
        self.assertIn("KHÔNG MÔ TẢ CẤU TRÚC TÀI LIỆU", prompt)
        self.assertIn("không\nliệt kê tên cột".replace("\n", " "), prompt)

    def test_no_person_no_extra_instruction(self):
        # Câu hỏi luật không phải cõng thêm chỉ dẫn về hồ sơ nhân sự.
        prompt = rag.build_prompt(
            "thời hiệu khởi kiện",
            [{"chunk_id": 9, "content": "Điều 429 Bộ luật Dân sự…",
              "title": "Bộ luật Dân sự", "doc_type": "law", "score": 0.9}],
            chunk_chars=2000, budget=8000)
        self.assertNotIn("PHÂN BIỆT TỪNG NGƯỜI", prompt)


class AnswerPolicyTests(unittest.TestCase):
    """Chính sách 20/08/2026: không chặt cụt câu trả lời (num_predict=-1);
    thay vào đó bot ĐỌC LẠI khi có dấu hiệu chưa ổn; và CHỈ hiện nguồn
    liên quan (được trích dẫn / điểm cao)."""

    def test_pdf_always_requires_human_review(self):
        from app.auto_learn import decide_approval
        # PDF: luôn chờ duyệt — kể cả tự-duyệt bật, bản cũ từng duyệt, trích sạch.
        self.assertFalse(decide_approval(".pdf", True, True, True))
        self.assertFalse(decide_approval(".PDF", True, False, True))
        # Định dạng khác giữ nếp cũ.
        self.assertTrue(decide_approval(".docx", True, False, True))   # auto
        self.assertTrue(decide_approval(".xlsx", True, True, False))   # kế thừa
        self.assertFalse(decide_approval(".docx", False, True, True))  # có cảnh báo

    def test_needs_review_on_truncated_answer(self):
        from app import rag
        cut = "Theo Điều 35 Bộ luật Lao động, người lao động phải báo trước bốn mươi"
        self.assertTrue(rag._answer_needs_review(cut))

    def test_needs_review_on_repetition_and_length(self):
        from app import rag
        loop = ("Người lao động phải báo trước 45 ngày theo quy định hiện hành.\n" * 4)
        self.assertTrue(rag._answer_needs_review(loop))
        self.assertTrue(rag._answer_needs_review("Dài. " * 1000))

    def test_clean_answer_skips_review(self):
        from app import rag
        good = ("Người lao động phải báo trước ít nhất 45 ngày [Nguồn 1].\n"
                "- Căn cứ: điểm a khoản 1 Điều 35 Bộ luật Lao động số 45/2019/QH14.")
        self.assertFalse(rag._answer_needs_review(good))
        # Chạm trần token do admin đặt tay → phải rà.
        self.assertTrue(rag._answer_needs_review(good, gen_tokens=1200, num_predict=1200))

    def test_parse_review_ok_keeps_original(self):
        from app import rag
        self.assertIsNone(rag._parse_review("OK"))
        self.assertIsNone(rag._parse_review("  ok.  "))
        self.assertIsNone(rag._parse_review("Ổn"))
        fixed = "Bản thay thế đã gọn, giữ nguyên [Nguồn 1] và kết thúc trọn vẹn."
        self.assertEqual(rag._parse_review(fixed), fixed)

    def test_relevant_sources_keeps_cited_and_high_score(self):
        from app import rag
        evidence = [
            {"n": 1, "kind": "document", "title": "A", "score": 0.37},
            {"n": 2, "kind": "document", "title": "B", "score": 0.36},
            {"n": 3, "kind": "document", "title": "C", "score": 0.62},
        ]
        text = "Kết luận dựa trên hồ sơ [Nguồn 2]."
        kept = rag.relevant_sources(text, evidence)
        self.assertEqual([e["n"] for e in kept], [2, 3])   # cite + điểm cao; rác 37% bị bỏ

    def test_relevant_sources_never_hides_everything(self):
        from app import rag
        evidence = [{"n": 1, "kind": "document", "title": "A", "score": 0.3}]
        self.assertEqual(rag.relevant_sources("không trích dẫn gì", evidence), evidence)

    def test_relevant_sources_keeps_system_evidence(self):
        from app import rag
        evidence = [{"kind": "system", "title": "Sổ nhân sự", "quote": "COUNT=3"}]
        self.assertEqual(rag.relevant_sources("bất kỳ", evidence), evidence)


class ChatDraftTests(unittest.TestCase):
    """Yêu cầu 20/08/2026: 'tạo hợp đồng lao động cho Ngân như của Nhi' từ chat
    phải ra BẢN NHÁP thật (tải được .docx), không phải một đoạn văn tả lại."""

    def test_detect_full_pattern_variants(self):
        from app import chat_draft
        for q in [
            "tạo hợp đồng lao động cho Ngân như của Nhi",
            "soạn hợp đồng lao động cho chị Ngân theo mẫu của Nhi",
            "tao hop dong lao dong cho ngan nhu cua nhi",   # gõ không dấu
        ]:
            got = chat_draft.detect_request(q)
            self.assertIsNotNone(got, q)
            self.assertEqual((got["kind_label"], got["for_name"], got["like_name"]),
                             ("hợp đồng lao động", "ngan", "nhi"), q)

    def test_detect_rejects_lookup_and_incomplete(self):
        from app import chat_draft
        self.assertIsNone(chat_draft.detect_request(
            "hợp đồng của SUNGROUP có điều khoản phạt không"))
        self.assertIsNone(chat_draft.detect_request(
            "tạo hợp đồng cho Ngân như của Ngân"))       # A trùng B

    def test_detect_simple_pattern_uses_standard_template(self):
        # Yêu cầu 21/08/2026: "tạo hợp đồng lao động cho Ngân" (không vế mẫu)
        # phải ra bản nháp từ MẪU CHUẨN trong kho, không trả lời "không thấy".
        from app import chat_draft
        for q in ["tạo hợp đồng lao động cho Ngân",
                  "soạn giúp tôi hợp đồng lao động cho chị Ngân",
                  "tao hop dong lao dong cho ngan"]:
            got = chat_draft.detect_request(q)
            self.assertIsNotNone(got, q)
            self.assertEqual((got["kind_label"], got["for_name"], got["like_name"]),
                             ("hợp đồng lao động", "ngan", None), q)

    def test_detect_simple_for_self(self):
        from app import chat_draft
        got = chat_draft.detect_request("tạo hợp đồng lao động cho tôi")
        self.assertIsNotNone(got)
        self.assertTrue(got.get("for_self"))

    def test_detect_simple_rejects_legal_lookup(self):
        # Câu tra cứu pháp lý cùng khuôn "tạo … cho <danh từ chung>" PHẢI trượt
        # để rơi về tra cứu Bộ luật Lao động, không thành lệnh soạn thảo.
        from app import chat_draft
        for q in ["tạo hợp đồng lao động cho người lao động cần điều kiện gì",
                  "soạn hợp đồng cho người nước ngoài được không",
                  "làm hợp đồng lao động cho nhân viên mới",
                  "tạo hợp đồng dịch vụ cho công ty được không",
                  "viết đơn cho tất cả mọi trường hợp thế nào"]:
            self.assertIsNone(chat_draft.detect_request(q), q)

    def test_pick_template_prefers_mau_hd_shelf(self):
        from app import chat_draft
        docs = [
            (553, "HĐLĐ-Nhi", "ho_so_ns"),               # hợp đồng THẬT của người khác
            (12, "Mẫu hợp đồng lao động 2025", "mau_hd"),
            (13, "Mẫu hợp đồng dịch vụ", "mau_hd"),
        ]
        self.assertEqual(chat_draft.pick_template(docs, "hop dong lao dong"),
                         (12, "Mẫu hợp đồng lao động 2025"))
        # Không có ngăn mẫu → KHÔNG lấy hợp đồng thật của người khác làm mẫu.
        docs_no_shelf = [(553, "HĐLĐ-Nhi", "ho_so_ns")]
        self.assertIsNone(chat_draft.pick_template(docs_no_shelf, "hop dong lao dong"))

    def test_pick_person_docs_retries_with_last_token(self):
        from app import chat_draft
        docs = [(537, "Ngân — CCCD", "ho_so_ns"), (541, "Ngân — CV", "ho_so_ns")]
        got = chat_draft.pick_person_docs(docs, "nguyen thi ngan")
        self.assertEqual([d[0] for d in got], [537, 541])

    def test_missing_template_answer_points_to_shelf(self):
        from app import chat_draft
        req = {"kind": "hop dong lao dong", "kind_label": "hợp đồng lao động",
               "for_name": "ngan", "like_name": None}
        text = chat_draft._missing_template_answer(req)["answer"]
        self.assertIn("chưa có mẫu hợp đồng lao động", text)
        self.assertIn("4. HỢP ĐỒNG MẪU", text)
        self.assertIn("Soạn tài liệu", text)

    DOCS = [
        (553, "HĐLĐ-Nhi", "ho_so_ns"),
        (555, "Nhi — Sơ yếu lý lịch", "ho_so_ns"),
        (537, "Ngân — CCCD", "ho_so_ns"),
        (541, "Ngân — CV", "ho_so_ns"),
        (531, "Ngân. KPI quý", "ho_so_ns"),
        (12, "Mẫu hợp đồng dịch vụ", "mau_hd"),
    ]

    def test_pick_sources_finds_template_and_person_files(self):
        from app import chat_draft
        template, is_fallback, person = chat_draft.pick_sources(
            self.DOCS, "hop dong lao dong", "ngan", "nhi")
        self.assertEqual(template, (553, "HĐLĐ-Nhi"))
        self.assertFalse(is_fallback)
        # Hồ sơ định danh (CCCD, CV) xếp trước file KPI.
        self.assertEqual([d[0] for d in person][:2], [537, 541])

    def test_pick_sources_falls_back_when_kind_missing(self):
        from app import chat_draft
        docs = [d for d in self.DOCS if d[0] != 553]   # bỏ HĐLĐ của Nhi
        template, is_fallback, _ = chat_draft.pick_sources(
            docs, "hop dong lao dong", "ngan", "nhi")
        self.assertEqual(template, (555, "Nhi — Sơ yếu lý lịch"))
        self.assertTrue(is_fallback)

    def test_pick_sources_none_when_person_unknown(self):
        from app import chat_draft
        template, _, person = chat_draft.pick_sources(
            self.DOCS, "hop dong lao dong", "hoa", "tuan")
        self.assertIsNone(template)
        self.assertEqual(person, [])

    def test_missing_answer_says_what_and_where(self):
        from app import chat_draft
        req = {"kind": "hdld", "kind_label": "hợp đồng lao động",
               "for_name": "ngan", "like_name": "tuan"}
        text = chat_draft._missing_answer(req)["answer"]
        self.assertIn("chưa có hợp đồng lao động", text)
        self.assertIn("8. HỒ SƠ NHÂN SỰ/Tuan/", text)
        self.assertIn("Soạn tài liệu", text)


class PublicChannelMessageTests(unittest.TestCase):
    """Kênh public phục vụ NGƯỜI DÂN: mọi câu nhắn hệ thống phải khả thi với
    họ — không mời chào tính năng nội bộ (chọn nguồn, tải tệp, hồ sơ khách)."""

    def test_smalltalk_public_khong_moi_tinh_nang_noi_bo(self):
        from app import rag
        text = rag._smalltalk_answer("chào", "public")
        self.assertIsNotNone(text)
        self.assertNotIn("hồ sơ", text)
        self.assertNotIn("soạn tài liệu", text)
        self.assertIn("pháp luật", text)
        # Kênh nội bộ giữ nguyên lời chào cũ.
        self.assertIn("hồ sơ", rag._smalltalk_answer("chào", "internal"))

    def test_insufficient_public_kha_thi_voi_nguoi_dan(self):
        from app import rag
        text = rag._insufficient_answer(False, "public")
        self.assertNotIn("tải", text)
        self.assertNotIn("tên khách", text)
        self.assertIn("luật sư", text)

    def test_blocked_public_khong_bao_tai_tep(self):
        from app import rag
        chunks = [{"content": "Điều 35 Bộ luật Lao động quy định quyền đơn "
                              "phương chấm dứt hợp đồng của người lao động."}]
        answer = ("Doanh nghiệp bắt buộc phải thưởng tháng lương thứ mười ba "
                  "cho toàn bộ nhân viên vào dịp cuối năm theo thông lệ chung.")
        text, status = rag.validate_grounding(answer, chunks, "grounded", True,
                                              "public")
        self.assertEqual(status, "uncited_blocked")
        self.assertNotIn("tải tệp", text)
        self.assertIn("luật sư", text)


class TitleScoreTests(unittest.TestCase):
    """Tên tài liệu (đặt tay trên Drive) phải góp điểm xếp hạng — 'từ tên thư
    mục kết hợp văn bản trong đó', không phó mặc cho vector."""

    def test_title_coverage_matches_person_file(self):
        from app import rag
        qtokens = rag._tokens("sơ yếu lí lịch của Ngân")
        cov = rag._title_coverage(qtokens, "Ngân — Sơ yếu lý lịch")
        # so/yeu/lich/ngan khớp; li (chính tả i ngắn) và cua thì không → 4/6.
        self.assertAlmostEqual(cov, 4 / 6, places=3)

    def test_title_coverage_empty_inputs(self):
        from app import rag
        self.assertEqual(rag._title_coverage(set(), "Bất kỳ"), 0.0)
        self.assertEqual(rag._title_coverage({"luat"}, None), 0.0)
        self.assertEqual(rag._title_coverage({"luat"}, "—"), 0.0)


class HrTitleTests(unittest.TestCase):
    """Ba nhân sự ba file cùng tên 'Sơ yếu lý lịch.pdf' → ba tài liệu trùng
    tiêu đề, nguồn trích dẫn không biết của ai. Tiêu đề phải mang thư mục con
    tên người."""

    def test_compose_title_prefixes_person(self):
        from app import auto_learn
        self.assertEqual(auto_learn.compose_title("Sơ yếu lý lịch", "Ngân"),
                         "Ngân — Sơ yếu lý lịch")

    def test_compose_title_skips_when_already_named(self):
        from app import auto_learn
        # Người dùng đã tự đặt 'Ngân. KPI quý' thì không ghép trùng.
        self.assertEqual(auto_learn.compose_title("Ngân. KPI quý", "Ngân"),
                         "Ngân. KPI quý")
        self.assertEqual(auto_learn.compose_title("CV", None), "CV")

    def test_resolve_labels_carries_person_folder(self):
        from app import auto_learn
        labels, reason = auto_learn.resolve_labels(["8. HỒ SƠ NHÂN SỰ", "Ngân"])
        self.assertIsNone(reason)
        self.assertEqual(labels["doc_type"], "ho_so_ns")
        self.assertEqual(labels.get("title_context"), "Ngân")

    def test_resolve_labels_no_person_for_other_types(self):
        from app import auto_learn
        labels, reason = auto_learn.resolve_labels(["1. VĂN BẢN PHÁP LUẬT", "1.3 Thông tư"])
        self.assertIsNone(reason)
        self.assertEqual(labels["doc_type"], "law")
        self.assertNotIn("title_context", labels)

    def test_followup_uses_structured_state(self):
        state = {"intent": "staff_directory", "last_question": "cty tôi có mấy người"}
        self.assertEqual(
            company_context.infer_intent("chi tiết từng cá nhân", state=state),
            "staff_directory",
        )

    def test_correction_keeps_employment_contract_intent(self):
        state = {"intent": "employment_contract"}
        self.assertEqual(
            company_context.infer_intent("tôi hỏi người còn hợp đồng mà", state=state),
            "employment_contract",
        )

    def test_document_store_count_is_inventory(self):
        """Lỗi thực tế 19/08/2026: 'có mấy tài liệu bản án' đi qua RAG nên model
        phải đoán từ vài đoạn tìm được — đếm kho là câu metadata, đếm bằng SQL."""
        self.assertEqual(
            company_context.infer_intent("hds đang có mấy tài liệu bản án"),
            "doc_inventory",
        )
        self.assertEqual(
            company_context.infer_intent("kho dữ liệu đang có bao nhiêu tài liệu"),
            "doc_inventory",
        )

    def test_topic_search_is_not_inventory(self):
        """'bao nhiêu bản án VỀ tranh chấp đất' là tra cứu nội dung, không phải đếm kho."""
        self.assertIsNone(
            company_context.infer_intent("có bao nhiêu bản án về tranh chấp đất đai"))

    def test_hr_dossier_count_stays_staff(self):
        """Câu về hồ sơ nhân sự vẫn thuộc luồng nhân sự, không bị intent kho nuốt."""
        self.assertEqual(
            company_context.infer_intent("hds đang có mấy bộ hồ sơ nhân sự"),
            "staff_directory",
        )


class StaffPersonTests(unittest.TestCase):
    """Ca thật 21/08/2026: sau bảng "3 bộ = 3 nhân sự", người dùng hỏi "chi tiết
    mai" và nhận lại Y NGUYÊN bảng đó (0ms) — câu hỏi về MỘT CON NGƯỜI bị nhánh
    đếm quân số nuốt. Tên riêng một tiếng (Mai/Ngân/Nhi) trùng từ thông thường
    nên mỗi ca khớp phải đi kèm một ca gần giống PHẢI KHÔNG khớp."""

    NAMES = ["Mai", "Ngân", "Nhi", "Nguyễn Thị Hồng"]

    def test_goi_ten_kem_tin_hieu_ho_so(self):
        for q, expect in [
            ("chi tiết mai", "Mai"),
            ("chi tiet mai", "Mai"),                    # gõ không dấu
            ("hồ sơ của Ngân", "Ngân"),
            ("sơ yếu lý lịch của Nhi", "Nhi"),
            ("cccd của mai", "Mai"),
            ("thông tin nhân sự Ngân", "Ngân"),
        ]:
            self.assertEqual(
                company_context.detect_staff_person(q, self.NAMES), [expect], q)

    def test_ten_day_du_khong_can_tin_hieu(self):
        self.assertEqual(
            company_context.detect_staff_person(
                "Nguyễn Thị Hồng ký hợp đồng ngày nào", self.NAMES),
            ["Nguyễn Thị Hồng"])

    def test_khong_khop_khi_khong_co_tin_hieu_ho_so(self):
        # Tên một tiếng đứng trơ trọi giữa câu tra cứu pháp luật: không đủ căn
        # cứ để coi là hỏi về người, và đoán nhầm thì bot ghim sai bộ hồ sơ.
        for q in ["quy định về ngân sách nhà nước là gì",
                  "thủ tục vay ngân hàng thế chấp",
                  "ngày mai có deadline nào không",
                  "án lệ về tranh chấp đất đai"]:
            self.assertEqual(company_context.detect_staff_person(q, self.NAMES),
                             [], q)

    def test_tu_ghep_khong_thanh_ten_nguoi(self):
        # "hồ sơ ngân hàng" có tín hiệu "ho so" nhưng "ngân hàng" là từ ghép.
        self.assertEqual(
            company_context.detect_staff_person("hồ sơ ngân hàng của khách", self.NAMES),
            [])
        self.assertEqual(
            company_context.detect_staff_person("thông tin khoa nhi đồng", self.NAMES),
            [])

    def test_hoi_dem_quan_so_khong_phai_hoi_mot_nguoi(self):
        for q in ["có mấy nhân viên", "cty tôi có bao nhiêu nhân sự",
                  "danh sách nhân sự công ty"]:
            self.assertEqual(company_context.detect_staff_person(q, self.NAMES),
                             [], q)

    def test_hoi_tung_truong_trong_bo_ho_so(self):
        for q, expect in [
            ("mai làm gì ở công ty", "Mai"),
            ("ngày sinh của Nhi", "Nhi"),
            ("số điện thoại Ngân là gì", "Ngân"),
            ("Mai vào làm từ bao giờ", "Mai"),
        ]:
            self.assertEqual(
                company_context.detect_staff_person(q, self.NAMES), [expect], q)

    def test_nhieu_nguoi_trong_mot_cau(self):
        got = company_context.detect_staff_person(
            "so sánh hợp đồng lao động của Mai và Nhi", self.NAMES)
        self.assertEqual(sorted(got), ["Mai", "Nhi"])

    def test_cau_cut_hoi_truong_ho_so_duoc_vay_ten(self):
        # "Sinh nhật" hỏi ngay sau "chi tiết Mai": phải nhận ra là câu hỏi một
        # TRƯỜNG hồ sơ để rag.prepare vay lại tên người của lượt trước.
        for q in ["Sinh nhật", "sinh nhat", "quê quán", "lương bao nhiêu",
                  "số điện thoại", "tốt nghiệp trường nào", "cccd"]:
            self.assertTrue(company_context.person_field_question(q), q)

    def test_cau_tra_cuu_phap_luat_khong_bi_vay_ten(self):
        # Vay nhầm là ghim hồ sơ nhân sự vào một câu hỏi luật.
        for q in ["thời hiệu là gì", "án lệ 90 nói gì", "tóm tắt điều 35",
                  "công ty có mấy khách", "hợp đồng dịch vụ mẫu"]:
            self.assertFalse(company_context.person_field_question(q), q)

    def test_danh_sach_ten_rong_khong_no(self):
        self.assertEqual(company_context.detect_staff_person("chi tiết mai", []), [])
        self.assertEqual(company_context.detect_staff_person("", self.NAMES), [])

    def test_tree_staff_lines_van_dem_theo_bo(self):
        # Bảng đếm giữ nguyên hành vi cũ cho câu hỏi quân số.
        text = "\n".join(company_context._tree_staff_lines(
            [("Mai", 12), ("Ngân", 11), ("Nhi", 7)]))
        self.assertIn("3 bộ hồ sơ = 3 nhân sự", text)


class StaffAnswerRoutingTests(unittest.TestCase):
    """Toàn tuyến router nhân sự khi sổ employees TRỐNG (đúng cấu hình đang
    chạy thật): cây thư mục là nguồn đếm, còn câu hỏi về một người phải nhường
    cho tra cứu đọc hồ sơ."""

    INDEX = {
        "Mai": [(101, "Mai — Sơ yếu lý lịch"), (102, "Mai — CCCD")],
        "Ngân": [(201, "Ngân — HĐLĐ")],
        "Nhi": [(301, "Nhi — CV"), (302, "Nhi — Bằng đại học")],
    }

    def test_person_files_block_liet_ke_du_giay_to(self):
        block = company_context.person_files_block(self.INDEX, ["Mai"])
        self.assertIn("BỘ HỒ SƠ NHÂN SỰ CỦA Mai — 2 giấy tờ", block)
        self.assertIn("Mai — Sơ yếu lý lịch", block)
        self.assertIn("Mai — CCCD", block)
        self.assertNotIn("Ngân", block)          # không lẫn bộ người khác

    def test_person_files_block_rong_khi_khong_co_bo(self):
        self.assertEqual(company_context.person_files_block(self.INDEX, ["Hoa"]), "")
        self.assertEqual(company_context.person_files_block({}, ["Mai"]), "")

    def _answer(self, question, state=None):
        with patch.object(company_context, "_employees_with_latest_contract",
                          return_value=[]):
            return company_context.structured_answer(
                question, "internal", is_banqt=True, state=state,
                person_index=self.INDEX)

    def test_cau_dem_van_tra_bang_cay(self):
        got = self._answer("có mấy nhân viên")
        self.assertIsNotNone(got)
        self.assertIn("3 bộ hồ sơ = 3 nhân sự", got["answer"])
        self.assertEqual(got["state"]["intent"], "staff_directory")

    def test_hoi_ten_mot_nguoi_khong_tra_bang_dem(self):
        # ĐÂY là lỗi 21/08/2026: "chi tiết mai" ngay sau bảng đếm nhận lại
        # nguyên bảng đó. None = nhường cho RAG mở bộ hồ sơ của Mai ra đọc.
        state = {"intent": "staff_directory", "last_question": "có mấy nhân viên"}
        self.assertIsNone(self._answer("chi tiết mai", state=state))
        self.assertIsNone(self._answer("hồ sơ của Ngân", state=state))
        self.assertIsNone(self._answer("sơ yếu lý lịch của Nhi"))

    def test_follow_up_doi_chi_tiet_khong_lap_lai_bang(self):
        # Không nêu tên ai, nhưng đòi chi tiết sau khi vừa nhận bảng đếm: bảng
        # cây chỉ có tên + số giấy tờ, trả lại lần nữa là bot lặp chính nó.
        state = {"intent": "staff_directory", "last_question": "có mấy nhân viên"}
        self.assertIsNone(self._answer("chi tiết từng người", state=state))

    def test_cau_dem_lan_dau_khong_bi_chan_nham(self):
        # Câu ĐẦU TIÊN (chưa có state) vẫn phải ra bảng đếm dù chứa chữ "chi
        # tiết"/"hồ sơ" — nếu không thì mất luôn câu trả lời đếm quân số.
        got = self._answer("hds đang có mấy bộ hồ sơ nhân sự")
        self.assertIsNotNone(got)
        self.assertIn("3 bộ hồ sơ", got["answer"])


class RetrievalQuestionTests(unittest.TestCase):
    def test_followup_is_rewritten_before_retrieval(self):
        history = [
            ("user", "cty tôi có mấy người"),
            ("assistant", "Hệ thống chưa có sổ nhân sự."),
        ]
        rewritten = rag.resolve_search_question("chi tiết từng cá nhân", history)
        self.assertIn("cty tôi có mấy người", rewritten)
        self.assertIn("chi tiết từng cá nhân", rewritten)

    def test_full_question_is_not_polluted_by_old_history(self):
        history = [("user", "khách SUNGROUP có vụ nào")]
        question = "Phân tích Điều 12 Luật Doanh nghiệp"
        self.assertEqual(rag.resolve_search_question(question, history), question)


class GroundingTests(unittest.TestCase):
    chunks = [
        {"chunk_id": 1, "title": "Luật A", "content": "Điều 1 quy định A."},
        {"chunk_id": 2, "title": "Luật B", "content": "Điều 2 quy định B."},
    ]

    def test_valid_citation_passes(self):
        text, status = rag.validate_grounding(
            "Nội dung A. [Nguồn 1]", self.chunks, "grounded", True)
        self.assertEqual(status, "verified")
        self.assertIn("[Nguồn 1]", text)

    def test_fake_citation_is_removed_and_blocked(self):
        text, status = rag.validate_grounding(
            "Tự bịa. [Nguồn 9]", self.chunks, "grounded", True)
        self.assertEqual(status, "uncited_blocked")
        self.assertNotIn("Nguồn 9", text)

    def test_document_answer_without_citation_is_blocked(self):
        claim = "Một kết luận không có nguồn."
        text, status = rag.validate_grounding(claim, self.chunks, "grounded", True)
        self.assertEqual(status, "uncited_blocked")
        # Kiểm tra TÍNH CHẤT AN TOÀN, không kiểm câu chữ: nội dung không có căn
        # cứ tuyệt đối không được lọt ra ngoài. Bản cũ soi chữ "đã chặn" trong
        # lời thông báo nên chỉ cần sửa lời văn là test đỏ, dù hành vi y nguyên.
        self.assertNotIn(claim, text)
        self.assertTrue(text.strip(), "Phải thay bằng lời hướng dẫn, không trả rỗng")

    def test_uncited_long_block_is_hidden_not_marked_verified(self):
        uncited = ("Đây là một đoạn khẳng định rất dài nhưng hoàn toàn không có "
                   "nguồn kiểm chứng đi kèm nên không được phép hiển thị như sự thật.")
        text, status = rag.validate_grounding(
            "Thông tin có căn cứ. [Nguồn 1]\n\n" + uncited,
            self.chunks, "grounded", True)
        self.assertEqual(status, "partial")
        # Tính chất phải giữ: nội dung vô căn cứ biến mất, phần có nguồn còn
        # nguyên, và người đọc được BÁO là có đoạn bị lược (một lần, ở cuối —
        # không rải placeholder vào giữa bài).
        self.assertNotIn(uncited, text)
        self.assertIn("[Nguồn 1]", text)
        self.assertIn("Đã lược", text)
        self.assertEqual(text.count("Đã lược"), 1)
        self.assertNotIn("hoàn toàn không có nguồn", text)

    def test_structured_answer_does_not_require_document_citation(self):
        text, status = rag.validate_grounding(
            "Có 3 khách hàng.", [], "structured", True)
        self.assertEqual(status, "verified")
        self.assertEqual(text, "Có 3 khách hàng.")


class PromptShapeTests(unittest.TestCase):
    """Prompt không được tự tay mớm cho model một câu từ chối.

    Lỗi thực tế 19/08/2026: prompt viết «không có đoạn hỗ trợ thì nói 'chưa đủ
    căn cứ trong nguồn'». Model nhỏ gặp prompt dài với mấy đoạn tài liệu lạc đề
    đã chép nguyên văn câu trong dấu nháy đó và trả lời đúng một dòng, dù DỮ
    LIỆU CÔNG TY ngay trên có đủ câu trả lời.
    """

    CHUNKS = [{"content": "Nội dung tài liệu mẫu.", "title": "Tài liệu A"}]

    def test_prompt_does_not_hand_model_a_ready_made_refusal(self):
        prompt = rag.build_prompt("cty tôi có bao nhiêu nhân sự", self.CHUNKS)
        self.assertNotIn("'chưa đủ căn cứ trong nguồn'", prompt)
        self.assertNotIn('"chưa đủ căn cứ trong nguồn"', prompt)

    def test_company_data_is_declared_highest_authority(self):
        """Có DỮ LIỆU CÔNG TY thì prompt phải nói rõ đó là căn cứ mạnh nhất."""
        prompt = rag.build_prompt(
            "cty tôi có bao nhiêu nhân sự", self.CHUNKS,
            company="### Nhân sự: 2 người\n · HĐLĐ-Nhi\n · CV — Bạc Thị Mai")
        self.assertIn("CĂN CỨ CÓ GIÁ TRỊ CAO NHẤT", prompt)
        self.assertIn("không được nói là thiếu căn cứ", prompt)
        # Và phải dặn gộp theo tên người, vì một người có nhiều hồ sơ.
        self.assertIn("GỘP THEO TÊN NGƯỜI", prompt)

    def test_no_company_data_means_no_such_claim(self):
        """Không có dữ liệu hệ thống thì đừng khẳng định có — tránh bịa."""
        prompt = rag.build_prompt("câu hỏi bất kỳ", self.CHUNKS)
        self.assertNotIn("CĂN CỨ CÓ GIÁ TRỊ CAO NHẤT", prompt)

    def test_client_document_is_labeled_with_owner(self):
        """Lỗi thực tế 19/08/2026: 'Giấy đề nghị ĐKDN' của khách không mang tên
        chủ sở hữu, model đọc 'tổng số lao động (dự kiến): 02' và trả lời như
        thể đó là quân số của chính HDS."""
        chunks = [{"content": "Tổng số lao động (dự kiến): 02 người.",
                   "title": "1. Giấy đề nghị", "client_id": 7,
                   "client_name": "CÔNG TY TNHH AGENT PRO"}]
        prompt = rag.build_prompt("cty tôi có bao nhiêu nhân sự", chunks)
        self.assertIn("(HỒ SƠ KHÁCH HÀNG — CÔNG TY TNHH AGENT PRO)", prompt)
        self.assertIn("PHÂN BIỆT CHỦ THỂ", prompt)

    def test_hds_only_sources_need_no_owner_warning(self):
        """Không có hồ sơ khách trong bộ nguồn thì đừng chèn chỉ dẫn thừa."""
        prompt = rag.build_prompt("câu hỏi bất kỳ", self.CHUNKS)
        self.assertNotIn("PHÂN BIỆT CHỦ THỂ", prompt)


class AutociteTests(unittest.TestCase):
    """`autocite` gắn lại trích dẫn cho đoạn ĐỐI CHIẾU ĐƯỢC với nguồn.

    Ranh giới sống còn của cả hệ thống nằm ở đây: gắn lỏng tay là bịa nguồn —
    người đọc thấy [Nguồn 1] và tin rằng tài liệu có nói điều đó.
    """

    def setUp(self):
        self.chunks = [
            {"content": "Người lao động được nghỉ hằng năm mười hai ngày làm việc "
                        "khi làm đủ mười hai tháng cho một người sử dụng lao động."},
            {"content": "Doanh nghiệp phải nộp báo cáo tài chính năm chậm nhất "
                        "chín mươi ngày kể từ ngày kết thúc năm tài chính."},
        ]

    def test_paragraph_copied_from_source_gets_cited(self):
        text, attached = rag.autocite(
            "Người lao động được nghỉ hằng năm mười hai ngày làm việc khi làm "
            "đủ mười hai tháng cho một người sử dụng lao động.", self.chunks)
        self.assertEqual(attached, 1)
        self.assertIn("[Nguồn 1]", text)

    def test_invented_claim_is_never_cited(self):
        """Nội dung không có trong nguồn TUYỆT ĐỐI không được gắn trích dẫn."""
        text, attached = rag.autocite(
            "Mức phạt vi phạm hành chính trong lĩnh vực xây dựng là hai trăm "
            "triệu đồng theo quy định mới nhất hiện hành.", self.chunks)
        self.assertEqual(attached, 0)
        self.assertNotIn("[Nguồn", text)

    def test_existing_citation_is_left_alone(self):
        original = "Đoạn đã có nguồn sẵn rồi. [Nguồn 2]"
        text, attached = rag.autocite(original, self.chunks)
        self.assertEqual(attached, 0)
        self.assertEqual(text, original)

    def test_short_filler_line_is_not_cited(self):
        """Câu nối ngắn không phải khẳng định, không cần và không được gắn nguồn."""
        text, attached = rag.autocite("Tóm lại như sau:", self.chunks)
        self.assertEqual(attached, 0)


class ContextWindowTests(unittest.TestCase):
    """`_best_window` giữ khúc LIÊN QUAN trong đoạn dài, không cắt từ đầu."""

    def test_relevant_tail_survives_truncation(self):
        filler = "Nội dung mở đầu không liên quan. " * 40
        answer = "Thời hiệu khởi kiện tranh chấp thương mại là hai năm."
        window = rag._best_window(filler + answer, "thời hiệu khởi kiện", 300)
        self.assertIn("Thời hiệu khởi kiện", window)
        self.assertLessEqual(len(window), 320)

    def test_short_chunk_is_returned_untouched(self):
        content = "Một đoạn ngắn."
        self.assertEqual(rag._best_window(content, "bất kỳ", 1000), content)


if __name__ == "__main__":
    unittest.main()
