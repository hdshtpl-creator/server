"""ChatGPT làm việc song song (app/ai_ngoai.py): soát đầu ra + câu trả lời khác.

Hỏng ở đây phần lớn KHÔNG có triệu chứng — nút vẫn chạy, chỉ là gửi ra ngoài
thứ không được phép gửi:

  * hồ sơ nhân sự / tài liệu nội bộ không gắn khách lọt qua mức law_only;
  * câu trả lời trích dẫn hồ sơ khách mà vẫn đem đi soát;
  * số CCCD, điện thoại, tên khách nằm nguyên văn trong prompt gửi đi;
  * gpt-5 từ chối `max_tokens`/`temperature` → nút báo lỗi 400 mãi.

Toàn bộ test thay CSDL, settings và mạng bằng đồ giả (update.sh chạy bộ test
ngay trên máy chủ thật — xem test_history_memory).
"""
import json
import re
import unittest

from app import ai_ngoai, models, rag, settings


class _SettingsGia:
    def __init__(self, testcase, **overrides):
        self.values = dict(settings.DEFAULTS)
        self.values.update({k: str(v) for k, v in overrides.items()})
        goc_get, goc_all, goc_int = settings.get, settings.get_all, settings.get_int
        settings.get = lambda key, default=None: self.values.get(key, default)
        settings.get_all = lambda: dict(self.values)

        def get_int(key, fallback):
            try:
                return int(float(self.values.get(key)))
            except (TypeError, ValueError):
                return fallback

        settings.get_int = get_int
        testcase.addCleanup(setattr, settings, "get", goc_get)
        testcase.addCleanup(setattr, settings, "get_all", goc_all)
        testcase.addCleanup(setattr, settings, "get_int", goc_int)


def _gan(testcase, obj, ten, gia_tri):
    goc = getattr(obj, ten)
    setattr(obj, ten, gia_tri)
    testcase.addCleanup(setattr, obj, ten, goc)


LUAT = {"doc_type": "law", "client_id": None, "access_level": "public",
        "content": "Điều 429. Thời hiệu khởi kiện về hợp đồng là 03 năm."}
NHAN_SU = {"doc_type": "ho_so_ns", "client_id": None, "access_level": "internal",
           "content": "Nguyễn Thị Mai — CCCD 001190012345 — lương 25 triệu"}
KHACH = {"doc_type": "contract", "client_id": 7, "access_level": "client",
         "content": "Hợp đồng thuê nhà của khách"}
CONG_NO = {"doc_type": "cong_no", "client_id": 7, "content": "Còn nợ 300 triệu"}
DINH_KEM = {"kind": "attachment", "attachment_name": "hop-dong.pdf",
            "content": "Bên A ..."}
MAU_CTY = {"kind": "attachment", "attachment_name": "Mẫu: HĐ dịch vụ",
           "content": "Mẫu chuẩn"}


class PhamViCloudChinhTests(unittest.TestCase):
    """Lỗ hổng cũ của nhánh cloud chính: hồ sơ nhân sự KHÔNG gắn khách lọt qua
    mức law_only chỉ vì không mang client_id."""

    def test_ho_so_nhan_su_khong_gan_khach_bi_gan_co_noi_bo(self):
        p = rag.phan_loai_du_lieu([LUAT, NHAN_SU])
        self.assertTrue(p["noi_bo"])
        self.assertFalse(p["khach"])
        self.assertEqual(rag.ngoai_pham_vi_cloud(p, "law_only"), "tai_lieu_noi_bo")
        self.assertEqual(rag.ngoai_pham_vi_cloud(p, "plus_attachments"),
                         "tai_lieu_noi_bo")
        self.assertIsNone(rag.ngoai_pham_vi_cloud(p, "all_but_finance"))

    def test_chi_van_ban_luat_thi_khong_gan_co(self):
        p = rag.phan_loai_du_lieu([LUAT, dict(LUAT, doc_type="an_le"),
                                   dict(LUAT, doc_type="ban_an")])
        self.assertFalse(p["noi_bo"])
        self.assertIsNone(rag.ngoai_pham_vi_cloud(p, "law_only"))

    def test_tai_lieu_dat_muc_cong_khai_duoc_coi_la_phap_luat(self):
        self.assertTrue(rag.la_nguon_phap_luat(
            {"doc_type": "other", "access_level": "public"}))
        self.assertFalse(rag.la_nguon_phap_luat(
            {"doc_type": "law", "access_level": "public", "client_id": 3}))


class LocDuLieuTests(unittest.TestCase):
    LICH_SU = [("user", "hỏi 1"), ("assistant", "đáp có lương 25 triệu"),
               ("user", "hỏi 2"), ("assistant", "đáp 2")]

    def _loc(self, scope, temp=None):
        return ai_ngoai.loc_du_lieu(
            [LUAT, NHAN_SU, KHACH, CONG_NO], temp, "DỮ LIỆU CÔNG TY…",
            list(self.LICH_SU), "tóm tắt có tên khách", "PHÁT HIỆN TỰ ĐỘNG",
            {"case_type": "x"}, scope)

    def test_law_only_chi_con_van_ban_luat(self):
        chunks, temp, company, hist, summ, ph, method, bo = self._loc(
            "law_only", [DINH_KEM])
        self.assertEqual(chunks, [LUAT])
        self.assertIsNone(temp)
        self.assertEqual(company, "")
        self.assertEqual(summ, "")
        self.assertEqual(ph, "")
        self.assertIsNone(method)
        self.assertEqual(hist, [("user", "hỏi 1"), ("user", "hỏi 2")],
                         "câu trả lời cũ có thể chép dữ liệu nội bộ — bỏ")
        self.assertEqual((bo["cong_no"], bo["ho_so_khach"], bo["tai_lieu_noi_bo"],
                          bo["dinh_kem"], bo["du_lieu_cong_ty"], bo["lich_su"]),
                         (1, 1, 1, 1, True, 2))
        self.assertEqual(bo["tong"], 5)

    def test_plus_attachments_giu_file_nguoi_dung_bo_mau_cong_ty(self):
        chunks, temp, *_rest, bo = self._loc("plus_attachments", [DINH_KEM, MAU_CTY])
        self.assertEqual(chunks, [LUAT])
        self.assertEqual(temp, [DINH_KEM])
        self.assertEqual(bo["tai_lieu_noi_bo"], 2)   # hồ sơ NS + mẫu công ty

    def test_all_but_finance_chi_bo_cong_no(self):
        chunks, temp, company, hist, summ, _ph, method, bo = self._loc(
            "all_but_finance", [DINH_KEM, MAU_CTY])
        self.assertEqual(chunks, [LUAT, NHAN_SU, KHACH])
        self.assertEqual(temp, [DINH_KEM, MAU_CTY])
        self.assertTrue(company)
        self.assertEqual(len(hist), 4)
        self.assertTrue(summ)
        self.assertIsNotNone(method)
        self.assertEqual(bo["tong"], 1)

    def test_pham_vi_la_thi_ve_muc_chat_nhat(self):
        chunks, *_rest = self._loc("cho_qua_het")
        self.assertEqual(chunks, [LUAT])


class PhamViSoatTests(unittest.TestCase):
    EV = [{"n": 1, "kind": "document", "doc_type": "law", "title": "BLDS"},
          {"n": 2, "kind": "document", "doc_type": "contract", "client_name": "ABC",
           "title": "[KH: ABC] HĐ"},
          {"n": 3, "kind": "document", "doc_type": "mau_hd", "title": "Mẫu"}]

    def test_nguon_noi_bo_khong_duoc_dan_thi_bo_khoi_phan_gui(self):
        pv = ai_ngoai.pham_vi_soat(self.EV, "grounded", "Theo Điều 429 [Nguồn 1].",
                                   "law_only")
        self.assertIsNone(pv["chan"])
        self.assertEqual([e["n"] for e in pv["gui"]], [1])
        self.assertEqual(pv["bo"], 2)

    def test_cau_tra_loi_dan_ho_so_khach_thi_khong_soat(self):
        pv = ai_ngoai.pham_vi_soat(self.EV, "grounded", "Theo HĐ [Nguồn 2].",
                                   "law_only")
        self.assertIn("hồ sơ khách hàng", pv["chan"])
        self.assertEqual(pv["gui"], [])

    def test_du_lieu_cong_ty_thi_khong_soat(self):
        pv = ai_ngoai.pham_vi_soat([], "operational", "Công ty có 12 người.",
                                   "law_only")
        self.assertTrue(pv["chan"])

    def test_cong_no_chan_ca_o_muc_rong_nhat(self):
        ev = [{"n": 1, "kind": "document", "doc_type": "cong_no"}]
        pv = ai_ngoai.pham_vi_soat(ev, "grounded", "Nợ [Nguồn 1]", "all_but_finance")
        self.assertIn("công nợ", pv["chan"])

    def test_chua_co_cau_tra_loi_thi_coi_moi_nguon_deu_co_the_duoc_dan(self):
        pv = ai_ngoai.pham_vi_soat(self.EV, "grounded", None, "law_only")
        self.assertTrue(pv["chan"])

    def test_file_dinh_kem_theo_pham_vi(self):
        ev = [{"n": 1, "kind": "attachment", "attachment_name": "a.pdf"}]
        self.assertTrue(ai_ngoai.pham_vi_soat(ev, "grounded", "[Nguồn 1]",
                                              "law_only")["chan"])
        self.assertIsNone(ai_ngoai.pham_vi_soat(ev, "grounded", "[Nguồn 1]",
                                                "plus_attachments")["chan"])


class CheDinhDanhTests(unittest.TestCase):
    def setUp(self):
        self.rx = ai_ngoai._dung_re_ten(["Công ty TNHH Minh Phát",
                                         "Nguyễn Văn An", "ABC"])

    def test_che_so_dien_thoai_email_cccd(self):
        s, n = ai_ngoai.che_dinh_danh(
            "Gọi 0912 345 678 hoặc a.b@hds.vn, CCCD 001190012345, MST 0101234567-001",
            re_ten=self.rx)
        self.assertNotIn("0912", s)
        self.assertNotIn("@", s)
        self.assertNotIn("001190012345", s)
        self.assertNotIn("0101234567", s)
        self.assertEqual(n, 4)

    def test_khong_dong_toi_so_hieu_van_ban_va_so_tien(self):
        goc = ("Điều 35 Bộ luật Lao động số 45/2019/QH14; phạt 450000000 đồng; "
               "450.000.000 đ; năm 2026")
        s, n = ai_ngoai.che_dinh_danh(goc, re_ten=self.rx)
        self.assertEqual(s, goc)
        self.assertEqual(n, 0)

    def test_che_ten_khach_ca_ten_day_du_lan_phan_loi(self):
        s, n = ai_ngoai.che_dinh_danh(
            "Công ty TNHH Minh Phát và Minh Phát cùng ông Nguyễn Văn An", re_ten=self.rx)
        self.assertNotIn("Minh Phát", s)
        self.assertNotIn("Nguyễn Văn An", s)
        self.assertEqual(s.count("[Khách hàng]"), 3)

    def test_ten_qua_ngan_khong_che_tran_lan(self):
        """'ABC' (3 ký tự) không vào danh sách — che nhầm chữ thường."""
        s, _ = ai_ngoai.che_dinh_danh("ABC là ví dụ", re_ten=self.rx)
        self.assertIn("ABC", s)


class KetQuaSoatTests(unittest.TestCase):
    def test_doc_json_trong_rao_markdown(self):
        raw = '```json\n{"ket_luan": "cần xem lại", "tom_tat": "Thiếu căn cứ", ' \
              '"van_de": [{"muc_do": "Vừa", "noi_dung": "Sai điều", "goi_y": "Sửa"}]}\n```'
        kq = ai_ngoai.phan_tich_ket_qua_soat(raw)
        self.assertEqual(kq["ket_luan"], "can_xem_lai")
        self.assertEqual(kq["van_de"][0]["muc_do"], "vua")

    def test_model_tu_mau_thuan_thi_tin_phan_chi_tiet(self):
        raw = json.dumps({"ket_luan": "on", "van_de": [
            {"muc_do": "cao", "noi_dung": "Dẫn sai số hiệu"}]})
        self.assertEqual(ai_ngoai.phan_tich_ket_qua_soat(raw)["ket_luan"], "co_sai_sot")

    def test_khong_phai_json_thi_giu_nguyen_van(self):
        kq = ai_ngoai.phan_tich_ket_qua_soat("Câu trả lời ổn.")
        self.assertEqual(kq["ket_luan"], "khong_ro")
        self.assertEqual(kq["tom_tat"], "Câu trả lời ổn.")
        self.assertEqual(kq["van_de"], [])


class ThamSoOpenAITests(unittest.TestCase):
    def test_gpt5_dung_max_completion_tokens_va_bo_temperature(self):
        self.assertTrue(models._la_openai_suy_luan("gpt-5-mini"))
        self.assertTrue(models._la_openai_suy_luan("o4-mini"))
        self.assertFalse(models._la_openai_suy_luan("qwen-plus"))
        self.assertFalse(models._la_openai_suy_luan("gpt-4o"))

    def test_loi_400_theo_param_cua_openai(self):
        body = {"model": "x", "max_tokens": 100, "temperature": 0.2, "stream": True}
        loi = json.dumps({"error": {"message": "Unsupported parameter: 'max_tokens' "
                                    "is not supported with this model. Use "
                                    "'max_completion_tokens' instead.",
                                    "param": "max_tokens"}})
        b = models._sua_body_theo_loi(body, loi)
        self.assertEqual(b["max_completion_tokens"], 100)
        self.assertNotIn("max_tokens", b)
        loi2 = json.dumps({"error": {"message": "Unsupported value: 'temperature'",
                                     "param": "temperature"}})
        b2 = models._sua_body_theo_loi(b, loi2)
        self.assertNotIn("temperature", b2)

    def test_to_chuc_chua_xac_minh_thi_lui_ve_mot_cuc(self):
        body = {"stream": True, "stream_options": {"include_usage": True}}
        loi = json.dumps({"error": {"message": "Your organization must be verified "
                                    "to stream this model.", "param": "stream"}})
        b = models._sua_body_theo_loi(body, loi)
        self.assertFalse(b["stream"])
        self.assertNotIn("stream_options", b)

    def test_loi_khong_biet_sua_gi_thi_tra_none(self):
        self.assertIsNone(models._sua_body_theo_loi(
            {"model": "x"}, json.dumps({"error": {"message": "model not found"}})))

    def test_bang_gia_khop_tien_to_dai_nhat(self):
        self.assertEqual(models.bang_gia("api:gpt-5-mini-2025-08-07"),
                         models.OPENAI_PRICES["gpt-5-mini"])
        self.assertEqual(models.bang_gia("api:gpt-5"), models.OPENAI_PRICES["gpt-5"])
        self.assertEqual(models.bang_gia("claude:claude-sonnet-5"),
                         models.CLAUDE_PRICES["claude-sonnet-5"])
        self.assertIsNone(models.bang_gia("api:qwen-plus"))


class _PhanHoiGia:
    def __init__(self, status, text="", lines=None, data=None):
        self.status_code = status
        self.text = text
        self._lines = lines or []
        self._data = data

    def iter_lines(self, decode_unicode=True):
        return iter(self._lines)

    def json(self):
        return self._data

    def close(self):
        pass


class CompatStreamTests(unittest.TestCase):
    def setUp(self):
        _gan(self, models, "COMPAT_API_KEY", "sk-gia")
        _gan(self, models, "cloud_config", lambda: {
            "max_tokens": 8000, "effort": "medium", "fallback_local": True})
        self.gui = []

    def test_400_thi_sua_tham_so_roi_gui_lai(self):
        phan_hoi = [
            _PhanHoiGia(400, json.dumps({"error": {"message": "x",
                                                   "param": "reasoning_effort"}})),
            _PhanHoiGia(200, lines=[
                'data: {"choices":[{"delta":{"content":"Xin "}}]}',
                'data: {"choices":[{"delta":{"content":"chào"}}]}',
                'data: {"choices":[],"usage":{"prompt_tokens":1000,'
                '"completion_tokens":200,"prompt_tokens_details":{"cached_tokens":0}}}',
                "data: [DONE]"]),
        ]

        def post(url, headers=None, json=None, timeout=None, stream=None):
            self.gui.append(dict(json))
            return phan_hoi.pop(0)

        _gan(self, models.requests, "post", post)
        stats = {}
        text = "".join(models.compat_stream("hỏi", "hệ thống", 0.2, "api:gpt-5-mini",
                                            stats, max_tokens=4000, effort="low"))
        self.assertEqual(text, "Xin chào")
        self.assertEqual(self.gui[0]["max_completion_tokens"], 4000)
        self.assertNotIn("temperature", self.gui[0])
        self.assertEqual(self.gui[0]["reasoning_effort"], "low")
        self.assertNotIn("reasoning_effort", self.gui[1])
        self.assertEqual(stats["gen_tokens"], 200)
        self.assertAlmostEqual(stats["cost_usd"], (1000 * 0.25 + 200 * 2.0) / 1e6)

    def test_loi_khac_bao_loi_ro_khong_lo_khoa(self):
        _gan(self, models.requests, "post",
             lambda *a, **k: _PhanHoiGia(401, json.dumps(
                 {"error": {"message": "Incorrect API key provided"}})))
        with self.assertRaises(models.CloudError) as ctx:
            list(models.compat_stream("hỏi", model="api:gpt-5"))
        self.assertIn("401", str(ctx.exception))
        self.assertNotIn("sk-gia", str(ctx.exception))


class CaiDatTests(unittest.TestCase):
    def test_chan_gia_tri_ngoai_tap(self):
        with self.assertRaises(ValueError):
            settings.kiem_gia_tri("ai_soat_che_do", "tudong")
        with self.assertRaises(ValueError):
            settings.kiem_gia_tri("ai_ngoai_tran_luot_thang", "-1")
        with self.assertRaises(ValueError):
            settings.kiem_gia_tri("ai_khac_model", "gpt 5")
        settings.kiem_gia_tri("ai_soat_che_do", "tu_dong")
        settings.kiem_gia_tri("ai_khac_model", "api:gpt-5")
        settings.kiem_gia_tri("prompt_internal", "bất kỳ")

    def test_mac_dinh_tat_ca_hai_tinh_nang(self):
        self.assertEqual(settings.DEFAULTS["ai_soat_che_do"], "tat")
        self.assertEqual(settings.DEFAULTS["ai_khac_bat"], "false")
        self.assertEqual(settings.DEFAULTS["ai_ngoai_che_dinh_danh"], "true")


class TrangThaiTests(unittest.TestCase):
    def test_bat_ma_chua_co_khoa_thi_khong_hien_nut(self):
        _SettingsGia(self, ai_soat_che_do="tu_dong", ai_khac_bat="true")
        _gan(self, models, "COMPAT_API_KEY", "")
        tt = ai_ngoai.trang_thai()
        self.assertEqual(tt["soat"], "tat")
        self.assertFalse(tt["khac"])

    def test_co_khoa_thi_hien_dung_che_do(self):
        _SettingsGia(self, ai_soat_che_do="nut", ai_khac_bat="true")
        _gan(self, models, "COMPAT_API_KEY", "sk-gia")
        tt = ai_ngoai.trang_thai()
        self.assertEqual(tt["soat"], "nut")
        self.assertTrue(tt["khac"])
        self.assertEqual(tt["ten_khac"], "ChatGPT (gpt-5)")

    def test_thay_doc_lai_chi_khi_chac_soat_duoc(self):
        _SettingsGia(self, ai_soat_che_do="tu_dong", ai_soat_thay_doc_lai="true",
                     ai_ngoai_tran_luot_thang="0")
        _gan(self, models, "COMPAT_API_KEY", "sk-gia")
        ev_luat = [{"n": 1, "kind": "document", "doc_type": "law"}]
        ev_khach = ev_luat + [{"n": 2, "kind": "document", "doc_type": "contract",
                               "client_name": "ABC"}]
        self.assertTrue(ai_ngoai.thay_doc_lai_local("internal", ev_luat, "grounded"))
        self.assertFalse(ai_ngoai.thay_doc_lai_local("internal", ev_khach, "grounded"))
        self.assertFalse(ai_ngoai.thay_doc_lai_local("portal", ev_luat, "grounded"))
        _SettingsGia(self, ai_soat_che_do="nut", ai_soat_thay_doc_lai="true")
        self.assertFalse(ai_ngoai.thay_doc_lai_local("internal", ev_luat, "grounded"))


class SoatTronLuongTests(unittest.TestCase):
    """Chạy trọn soat() với CSDL + API giả: prompt gửi đi đã che định danh,
    nguồn ngoài phạm vi không nằm trong prompt, kết quả được lưu."""

    def setUp(self):
        _SettingsGia(self, ai_soat_che_do="nut", ai_ngoai_tran_luot_thang="0")
        self.cfg = ai_ngoai.cau_hinh()
        self.luu, self.nhat_ky, self.prompt = {}, [], []
        _gan(self, ai_ngoai, "luu_ket_qua",
             lambda mid, cot, kq: self.luu.update({(mid, cot): kq}))
        _gan(self, ai_ngoai, "_ghi_nhat_ky",
             lambda uid, act, mid, d: self.nhat_ky.append((act, d)))
        _gan(self, ai_ngoai, "_noi_dung_nguon",
             lambda gui, trich: [(e, e.get("quote") or "") for e in gui])
        _gan(self, ai_ngoai, "_re_ten_khach",
             lambda: ai_ngoai._dung_re_ten(["Công ty TNHH Minh Phát"]))

        def goi(prompt, system="", model=None, **kw):
            self.prompt.append(prompt)
            kw["stats"].update({"model": model, "cost_usd": 0.001})
            yield '{"ket_luan": "on", "tom_tat": "Ổn", "van_de": []}'

        _gan(self, models, "goi_dung_model", goi)

    def _tn(self, content, evidence, answer_mode="grounded"):
        return {"id": 55, "conversation_id": 9, "content": content,
                "evidence": evidence, "answer_mode": answer_mode, "tham_so": {},
                "ai_soat": None, "ai_khac": None, "question_id": 54,
                "question": "Công ty TNHH Minh Phát (ĐT 0912345678) hỏi thời hiệu?"}

    def test_soat_duoc_thi_che_va_luu(self):
        ev = [{"n": 1, "kind": "document", "doc_type": "law", "quote": "Điều 429…"},
              {"n": 2, "kind": "document", "doc_type": "ho_so_ns",
               "quote": "CCCD 001190012345 của Mai"}]
        kq = ai_ngoai.soat(self.cfg, self._tn("Thời hiệu 3 năm [Nguồn 1].", ev),
                           {"id": 1})
        self.assertEqual(kq["ket_luan"], "on")
        p = self.prompt[0]
        self.assertNotIn("Minh Phát", p)
        self.assertNotIn("0912345678", p)
        self.assertNotIn("001190012345", p, "nguồn nội bộ không được dẫn — không gửi")
        self.assertIn("Điều 429", p)
        self.assertEqual(kq["nguon_gui"], 1)
        self.assertEqual(kq["nguon_bo"], 1)
        self.assertIn((55, "ai_soat"), self.luu)
        self.assertEqual(self.nhat_ky[0][0], "ai_soat")

    def test_bi_chan_thi_khong_goi_api_khong_tinh_luot(self):
        ev = [{"n": 1, "kind": "document", "doc_type": "contract",
               "client_name": "Minh Phát"}]
        kq = ai_ngoai.soat(self.cfg, self._tn("Theo HĐ [Nguồn 1].", ev), {"id": 1})
        self.assertEqual(kq["trang_thai"], "khong_gui")
        self.assertEqual(self.prompt, [])
        self.assertEqual(self.nhat_ky, [])

    def test_het_luot_thang(self):
        _SettingsGia(self, ai_soat_che_do="nut", ai_ngoai_tran_luot_thang="3")
        cfg = ai_ngoai.cau_hinh()
        _gan(self, ai_ngoai, "su_dung_thang", lambda: {"luot": 3})
        ev = [{"n": 1, "kind": "document", "doc_type": "law"}]
        with self.assertRaises(ai_ngoai.LoiAiNgoai) as ctx:
            ai_ngoai.soat(cfg, self._tn("[Nguồn 1]", ev), {"id": 1})
        self.assertEqual(ctx.exception.ma, 429)


class CauTraLoiKhacTests(unittest.TestCase):
    def setUp(self):
        _SettingsGia(self, ai_khac_bat="true", ai_ngoai_tran_luot_thang="0")
        self.cfg = ai_ngoai.cau_hinh()
        self.luu, self.goi_prepare, self.prompt = {}, [], []
        _gan(self, ai_ngoai, "luu_ket_qua",
             lambda mid, cot, kq: self.luu.update({(mid, cot): kq}))
        _gan(self, ai_ngoai, "_ghi_nhat_ky", lambda *a: None)
        _gan(self, ai_ngoai, "_re_ten_khach", lambda: ai_ngoai._dung_re_ten([]))

    def _tn(self, tham_so=None):
        return {"id": 55, "conversation_id": 9, "content": "đáp gốc", "evidence": [],
                "answer_mode": "grounded", "tham_so": tham_so or {}, "ai_soat": None,
                "ai_khac": None, "question_id": 54, "question": "Thời hiệu?"}

    def _prepare(self, direct=None, loc=None):
        def prepare(question, channel, **kw):
            self.goi_prepare.append(kw)
            if direct is not None:
                return {"direct_answer": direct, "ai_ngoai_loc": loc, "chunks": []}
            ch = [dict(LUAT, chunk_id=1, score=0.9)]
            return {"direct_answer": None, "prompt": "Hỏi: SĐT 0912345678",
                    "system": "sys", "temperature": 0.2, "chunks": ch,
                    "evidence": rag.format_sources(ch), "answer_mode": "grounded",
                    "strict_grounding": False, "ai_ngoai_loc": loc}
        _gan(self, rag, "prepare", prepare)

    def test_hoi_lai_dung_tham_so_luot_goc_va_khong_thay_cau_tra_loi_goc(self):
        self._prepare(loc={"tong": 0})

        def goi(prompt, system="", model=None, **kw):
            self.prompt.append(prompt)
            yield "Thời hiệu khởi kiện là 03 năm [Nguồn 1]."

        _gan(self, models, "goi_dung_model", goi)
        evs = list(ai_ngoai.cau_tra_loi_khac(
            self.cfg, self._tn({"mode": "legal_review", "use_temp": True,
                                "source_document_ids": [5]}),
            {"id": 1, "role": "chuyen_vien", "dept_ids": [2]}))
        kw = self.goi_prepare[0]
        self.assertEqual(kw["mode"], "legal_review")
        self.assertTrue(kw["use_temp"])
        self.assertEqual(kw["source_document_ids"], [5])
        self.assertEqual(kw["truoc_id"], 54)
        self.assertEqual(kw["ai_ngoai"]["model"], "api:gpt-5")
        self.assertNotIn("0912345678", self.prompt[0])
        done = evs[-1]
        self.assertEqual(done["type"], "done")
        self.assertEqual(done["ket_qua"]["trang_thai"], "xong")
        self.assertIn("03 năm", done["ket_qua"]["text"])
        self.assertIn((55, "ai_khac"), self.luu)

    def test_moi_nguon_deu_noi_bo_thi_noi_ro_khong_gui(self):
        self._prepare(direct="(không đủ căn cứ)",
                      loc={"tong": 3, "ho_so_khach": 2, "tai_lieu_noi_bo": 1})
        _gan(self, models, "goi_dung_model",
             lambda *a, **k: self.fail("không được gọi API"))
        evs = list(ai_ngoai.cau_tra_loi_khac(self.cfg, self._tn(), {"id": 1}))
        kq = evs[-1]["ket_qua"]
        self.assertEqual(kq["trang_thai"], "khong_gui")
        self.assertIn("hồ sơ khách hàng", kq["ly_do"])

    def test_api_tra_rong_thi_bao_loi_ro(self):
        self._prepare(loc={"tong": 0})
        _gan(self, models, "goi_dung_model", lambda *a, **k: iter(()))
        with self.assertRaises(ai_ngoai.LoiAiNgoai) as ctx:
            list(ai_ngoai.cau_tra_loi_khac(self.cfg, self._tn(), {"id": 1}))
        self.assertEqual(ctx.exception.ma, 502)

    def test_da_co_ket_qua_thi_khong_goi_lai(self):
        tn = self._tn()
        tn["ai_khac"] = {"trang_thai": "xong", "text": "cũ"}
        _gan(self, rag, "prepare", lambda *a, **k: self.fail("không chạy lại"))
        evs = list(ai_ngoai.cau_tra_loi_khac(self.cfg, tn, {"id": 1}))
        self.assertEqual(evs, [{"type": "done", "ket_qua": tn["ai_khac"]}])


class ThamSoLuotTests(unittest.TestCase):
    def test_chi_luu_cho_kenh_noi_bo(self):
        self.assertIsNone(rag.tham_so_luot("portal", "legal_review", True))
        self.assertEqual(rag.tham_so_luot("internal", None, False, False, []),
                         {"mode": None, "use_temp": False, "use_method": False,
                          "source_document_ids": None})


class LichSuTruocMocTests(unittest.TestCase):
    def test_before_id_vao_cau_sql(self):
        bat = {}

        class Cur:
            def execute(self, sql, params):
                bat["sql"], bat["params"] = sql, params

            def fetchall(self):
                return [("assistant", "đ"), ("user", "h")]

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        class Conn:
            def cursor(self):
                return Cur()

        class Sess:
            def __enter__(self):
                return Conn()

            def __exit__(self, *a):
                return False

        _gan(self, rag.db, "session", lambda **kw: Sess())
        out = rag.get_history(9, "internal", turns=3, before_id=54)
        self.assertEqual(out, [("user", "h"), ("assistant", "đ")])
        self.assertIn("id < %s", bat["sql"])
        self.assertEqual(bat["params"], (9, 0, 54, 54, 6))


if __name__ == "__main__":
    unittest.main()
