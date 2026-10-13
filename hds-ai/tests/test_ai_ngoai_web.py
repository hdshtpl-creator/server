"""Câu trả lời khác bằng ChatGPT / Gemini: tìm web thời gian thực + nhớ lịch sử
khung chat (13/10/2026).

Hỏng ở đây phần lớn KHÔNG có triệu chứng:
  * nguồn web không thành [Nguồn n] → bộ kiểm chứng lược mất đoạn lấy từ web;
  * lịch sử gửi kèm câu trả lời của Qwen trích hồ sơ nội bộ (vượt phạm vi);
  * lượt user/model không xen kẽ → Gemini báo 400;
  * số điện thoại trong câu hỏi CŨ lọt ra ngoài vì chỉ che câu hiện tại.
Mạng, CSDL, settings đều là đồ giả (update.sh chạy bộ test trên máy chủ thật).
"""
import json
import unittest

from app import ai_ngoai, models, rag, settings
from tests.test_ai_ngoai import LUAT, _gan, _PhanHoiGia, _SettingsGia


class NhaCungCapGeminiTests(unittest.TestCase):
    def test_nhan_dien_ten_model(self):
        self.assertEqual(models.provider_of("gemini:gemini-3.8-flash"), models.P_GEMINI)
        self.assertEqual(models.provider_of("gemini-3.5-flash-lite"), models.P_GEMINI)
        self.assertEqual(models.bare_model("gemini:gemini-3.8-flash"), "gemini-3.8-flash")
        self.assertTrue(models.is_cloud("gemini:gemini-3.8-flash"))
        self.assertEqual(ai_ngoai.ten_hien_thi("gemini:gemini-3.8-flash"), "Gemini (gemini-3.8-flash)")
        self.assertEqual(ai_ngoai.ten_hien_thi("api:gpt-6.1-sol"), "ChatGPT (gpt-6.1-sol)")

    def test_khoa_va_bang_gia(self):
        _gan(self, models, "GEMINI_API_KEY", "")
        self.assertFalse(models.co_khoa_api("gemini:gemini-3.8-flash"))
        _gan(self, models, "GEMINI_API_KEY", "g-gia")
        self.assertTrue(models.co_khoa_api("gemini:gemini-3.8-flash"))
        self.assertEqual(models.bang_gia("gemini:gemini-3.8-flash"), (0.75, 3.75))
        self.assertEqual(models.bang_gia("gemini:gemini-3.5-flash-lite-001"), (0.30, 2.50))
        self.assertEqual(models.bang_gia("api:gpt-6.1-sol"), (2.0, 10.0))
        self.assertEqual(models.bang_gia("api:gpt-6-luna-2026-05-01"), (0.10, 0.50))

    def test_ai_tim_web_duoc(self):
        self.assertTrue(models.ho_tro_tim_web("gemini:gemini-3.8-flash"))
        _gan(self, models, "COMPAT_BASE_URL", "https://api.openai.com/v1")
        self.assertTrue(models.ho_tro_tim_web("api:gpt-6.1-sol"))
        _gan(self, models, "COMPAT_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        self.assertFalse(models.ho_tro_tim_web("api:qwen-plus"))
        self.assertFalse(models.ho_tro_tim_web("claude:claude-sonnet-5"))
        self.assertFalse(models.ho_tro_tim_web("qwen3:14b"))

    def test_cai_dat_moi_chan_gia_tri_sai(self):
        with self.assertRaises(ValueError):
            settings.kiem_gia_tri("ai_khac_tim_web", "co")
        with self.assertRaises(ValueError):
            settings.kiem_gia_tri("ai_khac_so_luot_nho", "-2")
        settings.kiem_gia_tri("ai_khac_tim_web", "false")
        settings.kiem_gia_tri("ai_khac_model", "gemini:gemini-3.8-flash")


class GhepLichSuTests(unittest.TestCase):
    EV_LUAT = [{"n": 1, "kind": "document", "doc_type": "law"}]
    EV_KHACH = [{"n": 1, "kind": "document", "doc_type": "contract", "client_name": "Minh Phát"}]

    def test_uu_tien_cau_tra_loi_cua_chinh_model_ngoai(self):
        rows = [
            {"role": "user", "content": "hkd đang được miễn bao nhiêu"},
            {"role": "assistant", "content": "Qwen: 500 triệu [Nguồn 1]", "evidence": self.EV_LUAT,
             "answer_mode": "grounded",
             "ai_khac": {"trang_thai": "xong", "text": "Từ 2026 là 01 tỷ đồng [Nguồn 3].\n\n---\n*⚠ chân trang*"}},
        ]
        ls = ai_ngoai.ghep_lich_su(rows, "law_only", 6)
        self.assertEqual(ls, [("user", "hkd đang được miễn bao nhiêu"),
                              ("assistant", "Từ 2026 là 01 tỷ đồng.")])

    def test_cau_tra_loi_qwen_chi_gui_khi_trong_pham_vi(self):
        rows = [
            {"role": "user", "content": "thời hiệu?"},
            {"role": "assistant", "content": "03 năm [Nguồn 1].", "evidence": self.EV_LUAT,
             "answer_mode": "grounded", "ai_khac": None},
            {"role": "user", "content": "hợp đồng của khách này hết hạn chưa?"},
            {"role": "assistant", "content": "Hết hạn 01/03 [Nguồn 1].", "evidence": self.EV_KHACH,
             "answer_mode": "grounded", "ai_khac": None},
            {"role": "user", "content": "có mấy nhân viên"},
            {"role": "assistant", "content": "5 người", "evidence": [], "answer_mode": "operational"},
        ]
        ls = ai_ngoai.ghep_lich_su(rows, "law_only", 6)
        self.assertEqual([v for v, _ in ls], ["user", "assistant"] * 3)
        self.assertIn("03 năm", ls[1][1])
        self.assertTrue(ls[1][1].startswith("[Trợ lý nội bộ"))
        self.assertNotIn("01/03", ls[3][1])
        self.assertEqual(ls[3][1], ai_ngoai._GIU_CHO_DAP)
        self.assertEqual(ls[5][1], ai_ngoai._GIU_CHO_DAP)

    def test_gioi_han_so_luot_va_cau_hoi_mo_coi(self):
        rows = [{"role": "assistant", "content": "lời chào", "evidence": [], "answer_mode": "chat"}]
        for i in range(5):
            rows += [{"role": "user", "content": f"hỏi {i}"},
                     {"role": "assistant", "content": f"đáp {i}", "evidence": self.EV_LUAT,
                      "answer_mode": "grounded"}]
        rows.append({"role": "user", "content": "câu bị dừng chưa có đáp"})
        ls = ai_ngoai.ghep_lich_su(rows, "law_only", 2)
        self.assertEqual(ls[0], ("user", "hỏi 4"))
        self.assertEqual(ls[2], ("user", "câu bị dừng chưa có đáp"))
        self.assertEqual(ls[3], ("assistant", ai_ngoai._GIU_CHO_DAP))
        self.assertEqual(ai_ngoai.ghep_lich_su(rows, "law_only", 0), [])


class GanNguonWebTests(unittest.TestCase):
    def test_link_chatgpt_thanh_nguon_noi_tiep_kho(self):
        web = {"nguon": [{"url": "https://vbpl.vn/vb/141", "title": ""}],
               "trich": [{"url": "https://vbpl.vn/vb/141?utm_source=openai",
                          "title": "Nghị định 141/2026/NĐ-CP"}]}
        text = ("Ngưỡng là 01 tỷ đồng ([vbpl.vn](https://vbpl.vn/vb/141?utm_source=openai)). "
                "Áp dụng từ 01/01/2026 [vbpl.vn](https://vbpl.vn/vb/141?utm_source=openai) "
                "và [trang lạ](https://vi.wikipedia.org/x).")
        t, nguon = ai_ngoai.gan_nguon_web(text, web, so_dau=2)
        self.assertEqual(t, "Ngưỡng là 01 tỷ đồng [Nguồn 3]. Áp dụng từ 01/01/2026 [Nguồn 3] "
                            "và [Nguồn 4].")
        self.assertEqual([e["n"] for e in nguon], [3, 4])
        self.assertEqual(nguon[0]["title"], "Nghị định 141/2026/NĐ-CP")
        self.assertEqual(nguon[0]["url"], "https://vbpl.vn/vb/141")
        self.assertEqual(nguon[0]["domain"], "vbpl.vn")
        self.assertTrue(nguon[0]["tu_tim_kiem"])
        self.assertFalse(nguon[1]["tu_tim_kiem"])
        self.assertEqual(nguon[1]["kind"], "web")

    def test_gemini_chen_nguon_sau_doan_chu(self):
        web = {"nguon": [{"url": "https://redirect/a", "title": "chinhphu.vn"},
                         {"url": "https://redirect/b", "title": "thuvienphapluat.vn"}],
               "ho_tro": [{"text": "Ngưỡng miễn thuế là 01 tỷ đồng/năm.", "chunks": [0, 1]},
                          {"text": "Áp dụng từ 01/01/2026.", "chunks": [1]}]}
        text = "Ngưỡng miễn thuế là 01 tỷ đồng/năm. Áp dụng từ 01/01/2026. Ý khác."
        t, nguon = ai_ngoai.gan_nguon_web(text, web, so_dau=5)
        self.assertEqual(t, "Ngưỡng miễn thuế là 01 tỷ đồng/năm. [Nguồn 6] [Nguồn 7] "
                            "Áp dụng từ 01/01/2026. [Nguồn 7] Ý khác.")
        self.assertEqual([e["title"] for e in nguon], ["chinhphu.vn", "thuvienphapluat.vn"])

    def test_co_tim_ma_khong_gan_duoc_cho_nao_thi_them_dong_nguon(self):
        web = {"nguon": [{"url": "https://a.gov.vn/1", "title": "Bộ Tài chính"}], "ho_tro": []}
        t, nguon = ai_ngoai.gan_nguon_web("Trả lời không có link.", web, so_dau=0)
        self.assertTrue(t.endswith("Nguồn web đã tra: [Nguồn 1]"))
        self.assertEqual(len(nguon), 1)

    def test_khong_tim_web_thi_giu_nguyen(self):
        text = "Xem [vbpl](https://vbpl.vn/x)."
        self.assertEqual(ai_ngoai.gan_nguon_web(text, None, 3), (text, []))


class GeminiStreamTests(unittest.TestCase):
    def setUp(self):
        _gan(self, models, "GEMINI_API_KEY", "g-gia")
        _gan(self, models, "cloud_config", lambda: {"max_tokens": 8000})
        self.gui = []

    def test_tim_google_va_gom_nguon(self):
        ground = {"webSearchQueries": ["ngưỡng miễn thuế hộ kinh doanh 2026"],
                  "groundingChunks": [{"web": {"uri": "https://r/a", "title": "chinhphu.vn"}}],
                  "groundingSupports": [{"segment": {"startIndex": 0, "endIndex": 20,
                                                     "text": "Ngưỡng là 01 tỷ."},
                                         "groundingChunkIndices": [0]}],
                  "searchEntryPoint": {"renderedContent": "<div>gợi ý</div>"}}
        dong = [
            'data: ' + json.dumps({"candidates": [{"content": {"parts": [
                {"text": "suy nghĩ", "thought": True}, {"text": "Ngưỡng "}]}}]}),
            'data: ' + json.dumps({"candidates": [{"content": {"parts": [{"text": "là 01 tỷ."}]},
                                                    "groundingMetadata": ground,
                                                    "finishReason": "STOP"}],
                                   "usageMetadata": {"promptTokenCount": 1000,
                                                     "candidatesTokenCount": 100,
                                                     "thoughtsTokenCount": 50}}),
        ]
        phan_hoi = [_PhanHoiGia(400, json.dumps({"error": {"message": "Unknown name thinkingConfig"}})),
                    _PhanHoiGia(200, lines=dong)]

        def post(url, headers=None, json=None, timeout=None, stream=None):
            self.gui.append((url, headers, json))
            return phan_hoi.pop(0)

        _gan(self, models.requests, "post", post)
        stats = {}
        text = "".join(models.gemini_stream(
            "Câu hỏi mới", "hệ thống", "gemini:gemini-3.8-flash", stats, effort="medium",
            tim_web=True, lich_su=[("user", "hỏi cũ"), ("assistant", "đáp cũ")]))
        self.assertEqual(text, "Ngưỡng là 01 tỷ.")
        url, headers, body = self.gui[0]
        self.assertIn("models/gemini-3.8-flash:streamGenerateContent?alt=sse", url)
        self.assertEqual(headers["x-goog-api-key"], "g-gia")
        self.assertEqual(body["tools"], [{"google_search": {}}])
        self.assertEqual([c["role"] for c in body["contents"]], ["user", "model", "user"])
        self.assertEqual(body["systemInstruction"]["parts"][0]["text"], "hệ thống")
        self.assertNotIn("temperature", body["generationConfig"], "Gemini 3: để mặc định")
        self.assertIn("thinkingConfig", body["generationConfig"])
        self.assertNotIn("thinkingConfig", self.gui[1][2]["generationConfig"])
        web = stats["web"]
        self.assertEqual(web["nguon"], [{"url": "https://r/a", "title": "chinhphu.vn"}])
        self.assertEqual(web["ho_tro"], [{"text": "Ngưỡng là 01 tỷ.", "chunks": [0]}])
        self.assertEqual(web["so_lan_tim"], 1)
        self.assertEqual(web["goi_y_html"], "<div>gợi ý</div>")
        self.assertEqual(stats["gen_tokens"], 150)
        self.assertAlmostEqual(stats["cost_usd"], (1000 * 0.75 + 150 * 3.75) / 1e6 + 0.014, places=5)

    def test_loi_khoa_bao_ro_khong_lo_khoa(self):
        _gan(self, models.requests, "post", lambda *a, **k: _PhanHoiGia(
            403, json.dumps({"error": {"message": "API key not valid"}})))
        with self.assertRaises(models.CloudError) as ctx:
            list(models.gemini_stream("hỏi", model="gemini:gemini-3.8-flash"))
        self.assertIn("403", str(ctx.exception))
        self.assertNotIn("g-gia", str(ctx.exception))


class OpenAIResponsesTests(unittest.TestCase):
    def setUp(self):
        _gan(self, models, "COMPAT_API_KEY", "sk-gia")
        _gan(self, models, "COMPAT_BASE_URL", "https://api.openai.com/v1")
        _gan(self, models, "cloud_config", lambda: {"max_tokens": 8000})
        self.gui = []

    def test_web_search_va_lich_su(self):
        xong = {"type": "response.completed", "response": {
            "output": [
                {"type": "web_search_call", "action": {
                    "type": "search", "query": "ngưỡng miễn thuế hkd 2026",
                    "sources": [{"url": "https://vbpl.vn/1"}]}},
                {"type": "message", "content": [{
                    "type": "output_text", "text": "01 tỷ ([vbpl.vn](https://vbpl.vn/1))",
                    "annotations": [{"type": "url_citation", "url": "https://vbpl.vn/1",
                                     "title": "NĐ 141/2026", "start_index": 6, "end_index": 34}]}]}],
            "usage": {"input_tokens": 2000, "output_tokens": 300,
                      "input_tokens_details": {"cached_tokens": 0},
                      "output_tokens_details": {"reasoning_tokens": 100}}}}
        dong = ['event: response.output_text.delta',
                'data: ' + json.dumps({"type": "response.output_text.delta", "delta": "01 tỷ "}),
                'data: ' + json.dumps({"type": "response.output_text.delta",
                                       "delta": "([vbpl.vn](https://vbpl.vn/1))"}),
                'data: ' + json.dumps(xong)]
        phan_hoi = [_PhanHoiGia(400, json.dumps({"error": {"message": "x", "param": "reasoning.effort"}})),
                    _PhanHoiGia(200, lines=dong)]

        def post(url, headers=None, json=None, timeout=None, stream=None):
            self.gui.append((url, json))
            return phan_hoi.pop(0)

        _gan(self, models.requests, "post", post)
        stats = {}
        text = "".join(models.goi_dung_model(
            "hỏi mới", "hệ thống", "api:gpt-6.1-sol", effort="medium", stats=stats,
            lich_su=[("user", "hỏi cũ"), ("assistant", "đáp cũ")], tim_web=True))
        self.assertEqual(text, "01 tỷ ([vbpl.vn](https://vbpl.vn/1))")
        url, body = self.gui[0]
        self.assertTrue(url.endswith("/responses"))
        self.assertEqual(body["tools"][0]["type"], "web_search")
        self.assertEqual([m["role"] for m in body["input"]], ["user", "assistant", "user"])
        self.assertEqual(body["instructions"], "hệ thống")
        self.assertFalse(body["store"])
        self.assertEqual(body["reasoning"], {"effort": "medium"})
        self.assertNotIn("reasoning", self.gui[1][1])
        web = stats["web"]
        self.assertEqual(web["so_lan_tim"], 1)
        self.assertEqual(web["truy_van"], ["ngưỡng miễn thuế hkd 2026"])
        self.assertEqual(web["trich"], [{"url": "https://vbpl.vn/1", "title": "NĐ 141/2026"}])
        self.assertAlmostEqual(stats["cost_usd"], (2000 * 2.0 + 300 * 10.0) / 1e6 + 0.010, places=6)

    def test_khong_tim_web_thi_van_di_chat_completions(self):
        def post(url, headers=None, json=None, timeout=None, stream=None):
            self.gui.append((url, json))
            return _PhanHoiGia(200, lines=['data: {"choices":[{"delta":{"content":"ok"}}]}',
                                           "data: [DONE]"])

        _gan(self, models.requests, "post", post)
        text = "".join(models.goi_dung_model("hỏi", "", "api:gpt-6.1-sol",
                                             lich_su=[("user", "a"), ("assistant", "b")]))
        self.assertEqual(text, "ok")
        url, body = self.gui[0]
        self.assertTrue(url.endswith("/chat/completions"))
        self.assertEqual([m["role"] for m in body["messages"]], ["user", "assistant", "user"])


class CauTraLoiKhacCoWebTests(unittest.TestCase):
    def setUp(self):
        _SettingsGia(self, ai_khac_bat="true", ai_ngoai_tran_luot_thang="0",
                     ai_khac_model="gemini:gemini-3.8-flash")
        _gan(self, models, "GEMINI_API_KEY", "g-gia")
        self.cfg = ai_ngoai.cau_hinh()
        self.luu, self.goi = {}, []
        _gan(self, ai_ngoai, "luu_ket_qua",
             lambda mid, cot, kq: self.luu.update({(mid, cot): kq}))
        _gan(self, ai_ngoai, "_ghi_nhat_ky", lambda *a: None)
        _gan(self, ai_ngoai, "_re_ten_khach", lambda: ai_ngoai._dung_re_ten([]))
        _gan(self, ai_ngoai, "_doc_lich_su", lambda cid, truoc, n: [
            {"role": "user", "content": "Tôi là Lan, SĐT 0912345678, hỏi thuế hkd"},
            {"role": "assistant", "content": "x", "evidence": [], "answer_mode": "mixed",
             "ai_khac": {"trang_thai": "xong", "text": "Ngưỡng 500 triệu theo NĐ 68/2026."}}])

        def prepare(question, channel, **kw):
            self.kw_prepare = kw
            ch = [dict(LUAT, chunk_id=1, score=0.9)]
            return {"direct_answer": None, "prompt": "TÀI LIỆU… CÂU HỎI HIỆN TẠI: còn bây giờ?",
                    "system": "sys", "temperature": 0.2, "chunks": ch,
                    "evidence": rag.format_sources(ch), "answer_mode": "grounded",
                    "strict_grounding": True, "ai_ngoai_loc": {"tong": 0}}
        _gan(self, rag, "prepare", prepare)

    def _tn(self):
        return {"id": 77, "conversation_id": 9, "content": "đáp gốc", "evidence": [],
                "answer_mode": "grounded", "tham_so": {}, "ai_soat": None, "ai_khac": None,
                "question_id": 76, "question": "còn bây giờ?"}

    def test_tim_web_nho_lich_su_va_nguon_web_hop_le(self):
        def goi(prompt, system="", model=None, **kw):
            self.goi.append((prompt, kw))
            kw["stats"].update({"model": model, "cost_usd": 0.002, "web": {
                "nguon": [{"url": "https://r/a", "title": "chinhphu.vn"}],
                "ho_tro": [{"text": "Từ 01/01/2026 ngưỡng là 01 tỷ đồng.", "chunks": [0]}],
                "truy_van": ["ngưỡng miễn thuế hộ kinh doanh"], "so_lan_tim": 1,
                "goi_y_html": "<div>g</div>"}})
            yield "Từ 01/01/2026 ngưỡng là 01 tỷ đồng."

        _gan(self, models, "goi_dung_model", goi)
        evs = list(ai_ngoai.cau_tra_loi_khac(self.cfg, self._tn(), {"id": 1}))
        prompt, kw = self.goi[0]
        self.assertTrue(kw["tim_web"])
        self.assertIn("TÌM KIẾM WEB", prompt)
        self.assertTrue(self.kw_prepare["ai_ngoai"]["lich_su_rieng"])
        ls = kw["lich_su"]
        self.assertEqual([v for v, _ in ls], ["user", "assistant"])
        self.assertNotIn("0912345678", ls[0][1], "câu hỏi CŨ cũng phải được che")
        self.assertIn("500 triệu", ls[1][1])
        kq = evs[-1]["ket_qua"]
        self.assertEqual(kq["trang_thai"], "xong")
        self.assertIn("[Nguồn 2]", kq["text"], "nguồn web nối tiếp sau 1 nguồn kho")
        self.assertNotIn("Đã lược", kq["text"], "đoạn có nguồn web không bị lược")
        self.assertEqual(kq["grounding_status"], "verified")
        web = [s for s in kq["sources"] if s.get("kind") == "web"]
        self.assertEqual(len(web), 1)
        self.assertEqual(web[0]["n"], 2)
        self.assertTrue(kq["tim_web"])
        self.assertEqual(kq["nho_lich_su"], 1)
        self.assertEqual(kq["truy_van"], ["ngưỡng miễn thuế hộ kinh doanh"])
        self.assertEqual(kq["goi_y_html"], "<div>g</div>")
        self.assertGreaterEqual(kq["da_che"], 1)

    def test_tat_tim_web_va_lich_su(self):
        _SettingsGia(self, ai_khac_bat="true", ai_ngoai_tran_luot_thang="0",
                     ai_khac_model="gemini:gemini-3.8-flash", ai_khac_tim_web="false",
                     ai_khac_nho_lich_su="false")
        cfg = ai_ngoai.cau_hinh()

        def goi(prompt, system="", model=None, **kw):
            self.goi.append((prompt, kw))
            yield "Ngưỡng theo tài liệu [Nguồn 1]."

        _gan(self, models, "goi_dung_model", goi)
        list(ai_ngoai.cau_tra_loi_khac(cfg, self._tn(), {"id": 1}))
        prompt, kw = self.goi[0]
        self.assertFalse(kw["tim_web"])
        self.assertEqual(kw["lich_su"], [])
        self.assertNotIn("TÌM KIẾM WEB", prompt)
        self.assertFalse(self.kw_prepare["ai_ngoai"]["lich_su_rieng"])

    def test_trang_thai_bao_tim_web(self):
        tt = ai_ngoai.trang_thai(self.cfg)
        self.assertTrue(tt["khac"])
        self.assertTrue(tt["tim_web"])
        self.assertTrue(tt["nho_lich_su"])
        self.assertEqual(tt["ten_khac"], "Gemini (gemini-3.8-flash)")


if __name__ == "__main__":
    unittest.main()
