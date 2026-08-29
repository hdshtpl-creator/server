"""Tests của chính quality-eval harness.

Chạy:
    python -m unittest tests.quality_eval_test -v
"""

import unittest

from scripts import quality_eval


class StatisticsTests(unittest.TestCase):
    def test_percentile_empty_and_single(self):
        self.assertIsNone(quality_eval.percentile([], 95))
        self.assertEqual(quality_eval.percentile([42], 50), 42)
        self.assertEqual(quality_eval.percentile([42], 95), 42)

    def test_percentile_interpolates(self):
        self.assertEqual(quality_eval.percentile([0, 10], 50), 5)
        value = quality_eval.percentile([0, 10], 95)
        self.assertIsNotNone(value)
        assert value is not None
        self.assertAlmostEqual(value, 9.5)


class LiveAssertionsTests(unittest.TestCase):
    direct_case = {
        "expected_modes": ["structured"],
        "expected_grounding": ["verified"],
        "answer_contains_any": ["khách hàng"],
        "source_locator_contains_any": ["clients"],
    }

    def test_direct_accepts_system_evidence(self):
        response = {
            "answer": "HDS có 3 khách hàng.",
            "answer_mode": "structured",
            "grounding_status": "verified",
            "latency_ms": 0,
            "conversation_id": 10,
            "timings": {"ai_ms": 0, "tong_ms": 8},
            "sources": [{"kind": "system", "title": "Danh mục khách hàng",
                         "source_locator": "clients"}],
        }
        self.assertEqual(quality_eval._direct_errors(response, self.direct_case), [])

    def test_direct_rejects_document_evidence_and_ai(self):
        response = {
            "answer": "HDS có 3 khách hàng.",
            "answer_mode": "structured",
            "grounding_status": "verified",
            "latency_ms": 9,
            "conversation_id": 10,
            "timings": {"ai_ms": 9},
            "sources": [{"kind": "document", "document_id": 7, "chunk_id": 70}],
        }
        errors = quality_eval._direct_errors(response, self.direct_case)
        self.assertTrue(any("ai_ms" in error for error in errors))
        self.assertTrue(any("nguồn tài liệu" in error for error in errors))

    def test_retrieval_requires_citation_and_stays_in_selected_sources(self):
        case = {
            "expected_modes": ["grounded"],
            "expected_grounding": ["verified"],
        }
        response = {
            "answer": "Nội dung được kiểm chứng. [Nguồn 1]",
            "answer_mode": "grounded",
            "grounding_status": "verified",
            "sources": [
                {"n": 1, "kind": "document", "document_id": 123, "chunk_id": 9}
            ],
        }
        self.assertEqual(quality_eval._retrieval_errors(response, case, [123]), [])

    def test_retrieval_rejects_leaked_source_and_missing_citation(self):
        case = {
            "expected_modes": ["grounded"],
            "expected_grounding": ["verified"],
        }
        response = {
            "answer": "Nội dung không gắn nguồn.",
            "answer_mode": "grounded",
            "grounding_status": "verified",
            "sources": [
                {"n": 1, "kind": "document", "document_id": 999, "chunk_id": 9}
            ],
        }
        errors = quality_eval._retrieval_errors(response, case, [123])
        self.assertTrue(any("lọt nguồn" in error for error in errors))
        self.assertTrue(any("không có [Nguồn n]" in error for error in errors))


class GoldenSuiteTests(unittest.TestCase):
    def test_all_offline_golden_cases_pass(self):
        cases = quality_eval.load_cases()
        results = quality_eval.run_offline(cases)
        failures = [f"{result.case_id}: {result.detail}"
                    for result in results if not result.passed]
        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
