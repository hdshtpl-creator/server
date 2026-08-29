"""Unit tests thuần cho hàng rào chống bịa của luồng soạn thảo."""
import io
import unittest

from docx import Document

from app import drafting


class DraftingSafetyTests(unittest.TestCase):
    def test_source_ids_are_positive_unique_and_limited(self):
        self.assertEqual(drafting.normalize_source_ids([3, 1, 3]), [3, 1])
        with self.assertRaises(ValueError):
            drafting.normalize_source_ids([0])
        with self.assertRaises(ValueError):
            drafting.normalize_source_ids(list(range(1, 22)))

    def test_no_data_returns_placeholder_scaffold_without_model(self):
        result = drafting.generate_content(
            title="Thư tư vấn", instructions="", input_data={},
            body_template="# Thư\n\n[CẦN BỔ SUNG: yêu cầu]",
            template_instructions="", evidence=[], missing_fields=["client_name"],
        )
        self.assertIsNone(result["model_used"])
        self.assertEqual(result["grounding_status"], "needs_review")
        self.assertGreaterEqual(result["placeholder_count"], 1)
        self.assertIn("CẦN BỔ SUNG", result["content_markdown"])

    def test_unknown_citation_is_replaced(self):
        evidence = [{"citation_key": "N1"}]
        text, status, count = drafting.clean_and_score("Đúng [N1]. Sai [N99].", evidence)
        self.assertIn("[N1]", text)
        self.assertNotIn("[N99]", text)
        self.assertIn("CẦN BỔ SUNG", text)
        self.assertEqual(status, "needs_review")
        self.assertEqual(count, 1)

    def test_one_citation_does_not_ground_other_unsupported_paragraphs(self):
        evidence = [{"citation_key": "N1"}]
        text = ("Đoạn đầu này có thông tin được nguồn xác nhận đầy đủ. [N1]\n\n"
                "Đoạn thứ hai đưa ra một kết luận dài nhưng hoàn toàn không gắn nguồn nào.")
        _cleaned, status, _count = drafting.clean_and_score(text, evidence)
        self.assertEqual(status, "needs_review")

    def test_docx_export_contains_content_and_evidence(self):
        evidence = [{
            "citation_key": "N1", "document_title": "Nguồn A", "excerpt": "Đoạn chứng cứ",
            "page_number": 2, "section_title": "Mục I", "source_locator": None,
        }]
        payload = drafting.render_docx("# Báo cáo\n\nNội dung [N1]", "Báo cáo", evidence)
        parsed = Document(io.BytesIO(payload))
        text = "\n".join(p.text for p in parsed.paragraphs)
        self.assertIn("Báo cáo", text)
        self.assertIn("Nguồn A", text)
        self.assertIn("Đoạn chứng cứ", text)


if __name__ == "__main__":
    unittest.main()
