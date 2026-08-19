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
