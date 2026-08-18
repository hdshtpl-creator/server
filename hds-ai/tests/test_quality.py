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
        text, status = rag.validate_grounding(
            "Một kết luận không có nguồn.", self.chunks, "grounded", True)
        self.assertEqual(status, "uncited_blocked")
        self.assertIn("đã chặn", text)

    def test_uncited_long_block_is_hidden_not_marked_verified(self):
        text, status = rag.validate_grounding(
            "Thông tin có căn cứ. [Nguồn 1]\n\n"
            "Đây là một đoạn khẳng định rất dài nhưng hoàn toàn không có nguồn "
            "kiểm chứng đi kèm nên không được phép hiển thị như sự thật.",
            self.chunks, "grounded", True)
        self.assertEqual(status, "partial")
        self.assertIn("Đã ẩn đoạn", text)
        self.assertNotIn("hoàn toàn không có nguồn", text)

    def test_structured_answer_does_not_require_document_citation(self):
        text, status = rag.validate_grounding(
            "Có 3 khách hàng.", [], "structured", True)
        self.assertEqual(status, "verified")
        self.assertEqual(text, "Có 3 khách hàng.")


if __name__ == "__main__":
    unittest.main()
