"""Nút "Dừng": huỷ lượt trả lời đang chạy (app/rag.answer_stream).

Không có phần này thì bấm Dừng chỉ là giấu chữ trên màn hình: model vẫn viết
nốt (vài phút CPU của máy chạy 14b, chặn luôn câu hỏi kế tiếp) rồi vẫn ghi bản
ĐẦY ĐỦ vào hội thoại — tải lại trang là thấy nguyên câu vừa dừng.

Toàn bộ test dưới đây thay `prepare`, `llm_stream` và `save_turn` bằng đồ giả
nên KHÔNG chạm CSDL lẫn Ollama (deploy/update.sh chạy bộ test này ngay trên
máy chủ đang phục vụ — xem test_history_memory).
"""
import threading
import unittest

from app import models, rag


class _DongChuGia:
    """Giả llm_stream: sinh chữ vô hạn, ghi nhận lúc bị đóng.

    Vô hạn là có chủ ý — nếu vòng lặp không chịu dừng theo cờ huỷ thì test
    treo chứ không âm thầm đi qua.
    """

    def __init__(self):
        self.da_dong = False
        self.so_manh = 0

    def __call__(self, *a, **kw):
        def gen():
            try:
                while True:
                    self.so_manh += 1
                    yield f"mẩu {self.so_manh} "
            finally:
                self.da_dong = True
        return gen()


class AnswerStreamCancelTests(unittest.TestCase):
    def setUp(self):
        self.dong_chu = _DongChuGia()
        self.da_luu = []

        self._prepare_goc = rag.prepare
        self._llm_goc = models.llm_stream
        self._save_goc = rag.save_turn

        rag.prepare = lambda *a, **kw: {
            "prompt": "p", "system": "s", "model": "qwen3:14b", "temperature": 0.2,
            "chunks": [], "method": None, "timings": {}, "evidence": [],
            "answer_mode": "grounded", "grounding_status": "ok",
            "state": {}, "strict_grounding": True,
        }
        models.llm_stream = self.dong_chu
        rag.save_turn = lambda *a, **kw: self.da_luu.append((a, kw)) or 123

    def tearDown(self):
        rag.prepare = self._prepare_goc
        models.llm_stream = self._llm_goc
        rag.save_turn = self._save_goc

    def _chay(self, cancel, so_mau_truoc_khi_dung):
        """Đọc vài mẩu rồi bật cờ huỷ, trả về các sự kiện nhận được."""
        evs = []
        gen = rag.answer_stream("hỏi gì đó", "internal", conversation_id=7,
                                cancel=cancel)
        for ev in gen:
            evs.append(ev)
            if len([e for e in evs if e["type"] == "delta"]) >= so_mau_truoc_khi_dung:
                cancel.set()
        return evs

    def test_dung_thi_ngung_sinh_chu(self):
        cancel = threading.Event()
        evs = self._chay(cancel, 3)
        deltas = [e for e in evs if e["type"] == "delta"]
        # Dừng ở mẩu kế tiếp, không chạy tới vô tận.
        self.assertGreaterEqual(len(deltas), 3)
        self.assertLess(len(deltas), 10)

    def test_dong_ket_noi_toi_ollama(self):
        # Không đóng thì Ollama vẫn sinh chữ cho tới hết dù chẳng ai đọc —
        # đúng thứ nút Dừng sinh ra để tránh.
        cancel = threading.Event()
        self._chay(cancel, 2)
        self.assertTrue(self.dong_chu.da_dong)

    def test_luu_dung_phan_da_hien_kem_dau_bi_cat(self):
        cancel = threading.Event()
        evs = self._chay(cancel, 3)
        self.assertEqual(len(self.da_luu), 1, "phải lưu đúng một lần")
        args, kwargs = self.da_luu[0]
        van_ban = args[1]
        # Phần đã lưu = đúng những mẩu người dùng đã nhìn thấy.
        da_hien = "".join(e["text"] for e in evs if e["type"] == "delta").strip()
        self.assertTrue(van_ban.startswith(da_hien))
        # Và có dấu cho biết bị cắt — lượt hỏi sau đọc lịch sử không được
        # tưởng đây là câu trả lời hoàn chỉnh.
        self.assertIn("dừng câu trả lời giữa chừng", van_ban)
        self.assertEqual(kwargs.get("grounding_status"), "stopped")

    def test_khong_dung_thi_khong_co_dau_cat(self):
        # Cờ huỷ có mà không bật: luồng chạy bình thường, không được lưu nhầm
        # thành "đã dừng".
        cancel = threading.Event()
        gen = rag.answer_stream("hỏi", "internal", conversation_id=7, cancel=cancel)
        deltas = 0
        for ev in gen:
            if ev["type"] == "delta":
                deltas += 1
            if deltas >= 5:
                break          # người gọi bỏ ngang, không phải cờ huỷ
        gen.close()
        self.assertEqual(self.da_luu, [], "bỏ ngang không phải là dừng có chủ ý")

    def test_khong_truyen_cancel_van_chay_duoc(self):
        # Các lối gọi cũ (answer() một cục, script nội bộ) không truyền cancel.
        gen = rag.answer_stream("hỏi", "internal", conversation_id=7)
        first = next(gen)
        self.assertEqual(first["type"], "meta")
        gen.close()


if __name__ == "__main__":
    unittest.main()
