"""Nhánh gọi model qua API ngoài: định tuyến nhà cung cấp và các chốt an toàn.

Ba thứ hỏng ở đây đều KHÔNG có triệu chứng — câu trả lời vẫn ra, chỉ là ra từ
chỗ khác hoặc mang theo dữ liệu không được phép đi:

  * `auto` lặng lẽ hạ một lựa chọn cloud xuống Qwen local (bộ chọn model theo
    cỡ đọc số trong tên: 'claude-sonnet-5' không khớp mẫu '<số>b');
  * hồ sơ khách / công nợ / dữ liệu công ty theo prompt ra khỏi máy chủ HDS;
  * mất trần ký tự → prompt phình theo cửa sổ 1 triệu token, hoá đơn theo sau.

Toàn bộ test thay `settings` và tầng mạng bằng đồ giả nên KHÔNG chạm CSDL,
Ollama lẫn API ngoài (deploy/update.sh chạy bộ test này ngay trên máy chủ đang
phục vụ — xem test_history_memory).
"""
import unittest

from app import models, rag, settings


class _SettingsGia:
    """Thay app.settings: trả cấu hình dựng sẵn, không mở kết nối CSDL nào."""

    def __init__(self, testcase, **overrides):
        self.values = dict(settings.DEFAULTS)
        self.values.update({k: str(v) for k, v in overrides.items()})
        goc_get, goc_all = settings.get, settings.get_all
        goc_int = settings.get_int
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


class ProviderRoutingTests(unittest.TestCase):
    """Tên model quyết định nhà cung cấp — không có bảng ánh xạ nào khác."""

    def test_khong_tien_to_la_local(self):
        for ten in ("qwen3:14b", "qwen3:8b", "gemma3:4b", "", None):
            self.assertEqual(models.provider_of(ten), models.P_LOCAL, ten)
            self.assertFalse(models.is_cloud(ten or ""))

    def test_tien_to_claude_va_ten_tran(self):
        self.assertEqual(models.provider_of("claude:claude-sonnet-5"), models.P_CLAUDE)
        # Admin gõ thẳng tên trần vào ô cài đặt cũng phải nhận ra, không thì
        # nó rơi về local mà chẳng ai biết vì sao model "không đổi".
        self.assertEqual(models.provider_of("claude-opus-5"), models.P_CLAUDE)
        self.assertEqual(models.bare_model("claude:claude-sonnet-5"), "claude-sonnet-5")
        self.assertEqual(models.bare_model("claude-opus-5"), "claude-opus-5")

    def test_tien_to_tuong_thich_openai(self):
        self.assertEqual(models.provider_of("api:qwen-plus"), models.P_COMPAT)
        self.assertEqual(models.bare_model("api:qwen-plus"), "qwen-plus")

    def test_auto_khong_ha_model_cloud_xuong_local(self):
        """Bẫy chính: _param_size không đọc được cỡ của tên model cloud nên
        trần cỡ thành vô hạn và MỌI model local đang nóng đều lọt."""
        goc = models.loaded_models
        models.loaded_models = lambda: ["qwen3:4b", "qwen3:14b"]
        self.addCleanup(setattr, models, "loaded_models", goc)
        chon = models.auto_pick_model("một câu hỏi ngắn",
                                      configured_model="claude:claude-sonnet-5")
        self.assertEqual(chon, "claude:claude-sonnet-5")


class ChiPhiTests(unittest.TestCase):
    def test_uoc_chi_phi_theo_bang_gia(self):
        # Sonnet 5: 2 USD/1 triệu token vào, 10 USD/1 triệu token ra.
        self.assertAlmostEqual(
            models._usd("claude-sonnet-5", 1_000_000, 100_000), 3.0, places=6)

    def test_token_doc_lai_tu_bo_dem_chi_tinh_mot_phan_muoi(self):
        """Lý do đáng đặt cache_control lên system prompt — mất chỗ này thì
        con số báo cáo cao hơn thực tế và admin sẽ chỉnh sai tham số."""
        day_du = models._usd("claude-sonnet-5", 1_000_000, 0)
        co_dem = models._usd("claude-sonnet-5", 1_000_000, 0, cached_in=1_000_000)
        self.assertAlmostEqual(co_dem, day_du * 0.1, places=6)

    def test_model_la_khong_co_gia_thi_khong_bia_so(self):
        self.assertIsNone(models._usd("qwen3:14b", 1000, 100))


class PhamViDuLieuTests(unittest.TestCase):
    """Dữ liệu nào được phép rời máy chủ. Nới nhầm ở đây là rò hồ sơ khách."""

    LUAT = {"khach": False, "cong_no": False, "dinh_kem": False, "cong_ty": False}

    def test_cong_no_chan_cung_o_moi_muc(self):
        payload = dict(self.LUAT, cong_no=True)
        for scope in ("law_only", "plus_attachments", "all_but_finance"):
            self.assertEqual(rag.ngoai_pham_vi_cloud(payload, scope), "cong_no", scope)

    def test_law_only_chan_ho_so_khach_va_du_lieu_cong_ty(self):
        self.assertEqual(
            rag.ngoai_pham_vi_cloud(dict(self.LUAT, khach=True), "law_only"),
            "ho_so_khach")
        self.assertEqual(
            rag.ngoai_pham_vi_cloud(dict(self.LUAT, cong_ty=True), "law_only"),
            "du_lieu_cong_ty")
        self.assertEqual(
            rag.ngoai_pham_vi_cloud(dict(self.LUAT, dinh_kem=True), "law_only"),
            "file_dinh_kem")

    def test_law_only_cho_qua_van_ban_luat(self):
        self.assertIsNone(rag.ngoai_pham_vi_cloud(self.LUAT, "law_only"))

    def test_plus_attachments_mo_dung_file_dinh_kem(self):
        """Mức dành cho tab Kiểm tra pháp lý: nhân viên tự đưa hồ sơ lên để
        rà, nhưng kho hồ sơ khách và dữ liệu công ty vẫn ở lại máy nhà."""
        self.assertIsNone(
            rag.ngoai_pham_vi_cloud(dict(self.LUAT, dinh_kem=True), "plus_attachments"))
        self.assertEqual(
            rag.ngoai_pham_vi_cloud(dict(self.LUAT, khach=True), "plus_attachments"),
            "ho_so_khach")

    def test_gia_tri_la_thi_ve_muc_an_toan_nhat(self):
        self.assertEqual(
            rag.ngoai_pham_vi_cloud(dict(self.LUAT, khach=True), "muc_khong_ton_tai"),
            "ho_so_khach")

    def test_phan_loai_doc_dung_co_cua_doan_tai_lieu(self):
        chunks = [{"doc_type": "law", "client_id": None},
                  {"doc_type": "contract", "client_id": 7}]
        p = rag.phan_loai_du_lieu(chunks, temp_chunks=None, company="")
        self.assertTrue(p["khach"])
        self.assertFalse(p["cong_no"])
        self.assertFalse(p["dinh_kem"])
        self.assertFalse(p["cong_ty"])
        p2 = rag.phan_loai_du_lieu([{"doc_type": "cong_no", "client_id": 7}],
                                   temp_chunks=[{"title": "[File: a.pdf]"}],
                                   company="DỮ LIỆU CÔNG TY…")
        self.assertTrue(p2["cong_no"] and p2["dinh_kem"] and p2["cong_ty"])


class GateCloudTests(unittest.TestCase):
    """Câu hỏi ngoài phạm vi KHÔNG bị cắt xén — nó đổi nơi xử lý."""

    def setUp(self):
        _SettingsGia(self, cloud_enabled="true", cloud_channels="internal",
                     cloud_scope="law_only", llm_model="qwen3:14b")
        goc = models.cloud_models
        models.cloud_models = lambda: ["claude:claude-sonnet-5"]
        self.addCleanup(setattr, models, "cloud_models", goc)

    SACH = {"khach": False, "cong_no": False, "dinh_kem": False, "cong_ty": False}

    def test_du_lieu_sach_thi_giu_nguyen_model_cloud(self):
        model, ly_do = rag.gate_cloud("claude:claude-sonnet-5", "internal", self.SACH)
        self.assertEqual(model, "claude:claude-sonnet-5")
        self.assertIsNone(ly_do)

    def test_ho_so_khach_thi_lui_ve_local(self):
        model, ly_do = rag.gate_cloud("claude:claude-sonnet-5", "internal",
                                      dict(self.SACH, khach=True))
        self.assertFalse(models.is_cloud(model))
        self.assertEqual(ly_do, "ho_so_khach")

    def test_kenh_public_khong_goi_api_du_da_bat(self):
        """Kênh public là cửa cho người lạ gõ câu hỏi — mở cloud ở đó là mở
        hoá đơn cho người lạ bơm."""
        model, ly_do = rag.gate_cloud("claude:claude-sonnet-5", "public", self.SACH)
        self.assertFalse(models.is_cloud(model))
        self.assertEqual(ly_do, "kenh_chua_bat")

    def test_model_local_khong_bi_dong_toi(self):
        model, ly_do = rag.gate_cloud("qwen3:14b", "internal",
                                      dict(self.SACH, cong_no=True))
        self.assertEqual(model, "qwen3:14b")
        self.assertIsNone(ly_do)

    def test_duong_lui_khong_bao_gio_lai_la_model_cloud(self):
        """Admin có thể đã đặt llm_model thành một model cloud. Lấy thẳng cài
        đặt đó làm đường lui thì 'lui về local' lại quay ra ngoài."""
        _SettingsGia(self, cloud_enabled="true", cloud_channels="internal",
                     cloud_scope="law_only", llm_model="claude:claude-opus-5")
        model, _ = rag.gate_cloud("claude:claude-sonnet-5", "internal",
                                  dict(self.SACH, khach=True))
        self.assertFalse(models.is_cloud(model))


class MacDinhLaCloudTests(unittest.TestCase):
    """Admin đặt luôn model mặc định của máy chủ thành model cloud.

    Lúc đó resolve_model trả None ("theo mặc định"), chốt phạm vi không có tên
    nào để soi, còn tên model cloud lại được lấy muộn ở tầng models khi sinh
    chữ — đúng một đường vòng qua chốt, không có triệu chứng nào.
    """

    def setUp(self):
        _SettingsGia(self, cloud_enabled="true", cloud_channels="internal",
                     cloud_scope="law_only", llm_model="claude:claude-sonnet-5")
        goc = models.cloud_models
        models.cloud_models = lambda: ["claude:claude-sonnet-5"]
        self.addCleanup(setattr, models, "cloud_models", goc)

    def test_mac_dinh_cloud_van_phai_qua_chot(self):
        # Mô phỏng đúng đoạn trong prepare: None → nêu đích danh model mặc
        # định khi nó là cloud, rồi mới đưa qua gate.
        chon = rag.resolve_model("", "hỏi gì đó")
        self.assertIsNone(chon)
        mac_dinh = models.effective_llm_model()
        self.assertTrue(models.is_cloud(mac_dinh))
        model, ly_do = rag.gate_cloud(mac_dinh, "internal",
                                      {"khach": True, "cong_no": False,
                                       "dinh_kem": False, "cong_ty": False})
        self.assertFalse(models.is_cloud(model))
        self.assertEqual(ly_do, "ho_so_khach")


class TranKyTuCloudTests(unittest.TestCase):
    """Qua API không còn cửa sổ ngữ cảnh làm trần vật lý — trần phải tự đặt."""

    def test_co_cau_hinh_thi_dung_dung_con_so_do(self):
        self.assertEqual(rag.cloud_char_cap("claude:claude-sonnet-5", 60_000), 60_000)

    def test_de_0_thi_theo_cua_so_that_cua_model(self):
        cap = rag.cloud_char_cap("claude:claude-haiku-4-5", 0)
        self.assertGreater(cap, 400_000)          # 200K token ≈ 520 nghìn ký tự
        self.assertLess(cap, 600_000)

    def test_model_la_van_co_tran(self):
        self.assertGreaterEqual(rag.cloud_char_cap("claude:model-la-hoac", 0), 20_000)


class FallbackTests(unittest.TestCase):
    """API hỏng thì phải chạy tiếp bằng Qwen local, không mất câu trả lời."""

    def setUp(self):
        _SettingsGia(self, cloud_fallback_local="true")
        self.goc_ollama = models.ollama_stream
        self.goc_claude = models.claude_stream
        self.addCleanup(setattr, models, "ollama_stream", self.goc_ollama)
        self.addCleanup(setattr, models, "claude_stream", self.goc_claude)
        models.ollama_stream = lambda *a, **kw: iter(["bản ", "local"])

    def test_loi_truoc_token_dau_thi_lui_ve_local(self):
        def hong(*a, **kw):
            raise models.CloudError("hết quota")
            yield  # pragma: no cover - giữ đây là generator

        models.claude_stream = hong
        stats = {}
        chu = "".join(models.llm_stream("hỏi", model="claude:claude-sonnet-5",
                                        stats=stats))
        self.assertEqual(chu, "bản local")
        self.assertEqual(stats.get("fallback"), "local")
        self.assertIn("hết quota", stats.get("cloud_error", ""))

    def test_loi_giua_chung_thi_khong_ghep_hai_ban_tra_loi(self):
        """Người dùng đã đọc mấy dòng của model kia rồi — chèn tiếp bản khác
        vào giữa còn tệ hơn dừng hẳn."""
        def gay_giua_chung(*a, **kw):
            yield "đang viết…"
            raise RuntimeError("rớt kết nối")

        models.claude_stream = gay_giua_chung
        with self.assertRaises(RuntimeError):
            list(models.llm_stream("hỏi", model="claude:claude-sonnet-5"))

    def test_tat_duong_lui_thi_bao_loi_that(self):
        _SettingsGia(self, cloud_fallback_local="false")

        def hong(*a, **kw):
            raise models.CloudError("mất mạng")
            yield  # pragma: no cover

        models.claude_stream = hong
        with self.assertRaises(models.CloudError):
            list(models.llm_stream("hỏi", model="claude:claude-sonnet-5"))

    def test_model_local_khong_di_qua_nhanh_cloud(self):
        models.claude_stream = lambda *a, **kw: self.fail("không được gọi")
        chu = "".join(models.llm_stream("hỏi", model="qwen3:14b"))
        self.assertEqual(chu, "bản local")


class SoanThaoTests(unittest.TestCase):
    """Luồng soạn thảo không đi qua rag.prepare — chốt phạm vi phải có riêng.

    Điền mẫu và dựng bộ file luôn cầm CCCD, ngày sinh, lương, điều khoản hợp
    đồng của một người cụ thể. Thiếu chốt này thì bật cloud ở mức an toàn nhất
    vẫn có một cửa sau đẩy trọn hồ sơ nhân sự ra ngoài.
    """

    def setUp(self):
        goc = models.cloud_models
        models.cloud_models = lambda: ["claude:claude-sonnet-5"]
        self.addCleanup(setattr, models, "cloud_models", goc)

    def test_pham_vi_hep_thi_o_lai_may_chu(self):
        for scope in ("law_only", "plus_attachments"):
            _SettingsGia(self, cloud_enabled="true", cloud_scope=scope,
                         llm_model="qwen3:14b")
            chon = models.model_soan_thao("claude:claude-sonnet-5")
            self.assertEqual(chon, "qwen3:14b", scope)

    def test_nhanh_cloud_tat_thi_o_lai_may_chu(self):
        _SettingsGia(self, cloud_enabled="false", cloud_scope="all_but_finance",
                     llm_model="qwen3:14b")
        self.assertEqual(models.model_soan_thao("claude:claude-sonnet-5"), "qwen3:14b")

    def test_admin_mo_pham_vi_rong_nhat_thi_cho_qua(self):
        _SettingsGia(self, cloud_enabled="true", cloud_scope="all_but_finance",
                     llm_model="qwen3:14b")
        self.assertEqual(models.model_soan_thao("claude:claude-sonnet-5"),
                         "claude:claude-sonnet-5")

    def test_model_local_di_thang_khong_bi_doi(self):
        _SettingsGia(self, cloud_enabled="false", llm_model="qwen3:14b")
        self.assertEqual(models.model_soan_thao("qwen3:8b"), "qwen3:8b")


if __name__ == "__main__":
    unittest.main()
