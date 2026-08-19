"""Regression tests cho các lỗi chất lượng đã gặp ngoài thực tế.

Chạy trên máy chủ:
    python -m unittest tests.test_quality -v

Các test này không cần PostgreSQL/Ollama; chúng giữ ổn định router, câu nối tiếp
và cổng citation trước khi chạy bộ eval end-to-end với dữ liệu thật.
"""
import unittest

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
