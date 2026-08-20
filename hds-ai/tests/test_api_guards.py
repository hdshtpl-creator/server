"""Van bảo vệ kênh chat công khai (app/api.py) — logic thuần, không cần CSDL.

Kênh public phục vụ người dân KHÔNG đăng nhập: không van là một người spam
nghẽn cả máy (mỗi câu tốn hàng chục giây LLM trên CPU), và một câu hỏi dài
cả megabyte thổi phồng prompt/embedding vô tội vạ.
"""
import types
import unittest

from fastapi import HTTPException

from app import api


def _request(ip="203.0.113.9", forwarded=None):
    headers = {}
    if forwarded:
        headers["x-forwarded-for"] = forwarded
    return types.SimpleNamespace(headers=headers,
                                 client=types.SimpleNamespace(host=ip))


def _body(question):
    return types.SimpleNamespace(question=question)


class CleanQuestionTests(unittest.TestCase):
    def test_cau_hoi_trong_bi_chan(self):
        with self.assertRaises(HTTPException) as ctx:
            api._clean_question(_body("   "))
        self.assertEqual(ctx.exception.status_code, 422)

    def test_cau_hoi_qua_dai_kenh_public(self):
        with self.assertRaises(HTTPException) as ctx:
            api._clean_question(_body("x" * (api.MAX_PUBLIC_QUESTION_CHARS + 1)),
                                public=True)
        self.assertEqual(ctx.exception.status_code, 413)

    def test_kenh_noi_bo_tran_rong_hon(self):
        long_q = "x" * (api.MAX_PUBLIC_QUESTION_CHARS + 1)
        self.assertEqual(api._clean_question(_body(long_q)), long_q)

    def test_cau_binh_thuong_duoc_strip(self):
        self.assertEqual(api._clean_question(_body("  thời hiệu là gì?  ")),
                         "thời hiệu là gì?")


class PublicRateLimitTests(unittest.TestCase):
    def setUp(self):
        self._old_max = api.PUBLIC_RATE_MAX
        api.PUBLIC_RATE_MAX = 3
        api._public_hits.clear()

    def tearDown(self):
        api.PUBLIC_RATE_MAX = self._old_max
        api._public_hits.clear()

    def test_qua_nguong_bi_429(self):
        req = _request(ip="198.51.100.7")
        for _ in range(3):
            api._public_rate_check(req)      # trong hạn mức — không ném
        with self.assertRaises(HTTPException) as ctx:
            api._public_rate_check(req)
        self.assertEqual(ctx.exception.status_code, 429)

    def test_ip_khac_khong_bi_lay(self):
        for _ in range(3):
            api._public_rate_check(_request(ip="198.51.100.7"))
        # IP khác vẫn hỏi được bình thường.
        api._public_rate_check(_request(ip="198.51.100.8"))

    def test_lay_ip_tu_x_forwarded_for(self):
        # Sau nginx, IP thật nằm đầu danh sách X-Forwarded-For.
        for _ in range(3):
            api._public_rate_check(
                _request(ip="127.0.0.1", forwarded="198.51.100.9, 10.0.0.1"))
        with self.assertRaises(HTTPException):
            api._public_rate_check(
                _request(ip="127.0.0.1", forwarded="198.51.100.9, 10.0.0.1"))
        # Cùng địa chỉ proxy nhưng IP thật khác → không bị chặn lây.
        api._public_rate_check(
            _request(ip="127.0.0.1", forwarded="198.51.100.10, 10.0.0.1"))

    def test_dat_0_la_tat_van(self):
        api.PUBLIC_RATE_MAX = 0
        for _ in range(10):
            api._public_rate_check(_request(ip="198.51.100.7"))


if __name__ == "__main__":
    unittest.main()
