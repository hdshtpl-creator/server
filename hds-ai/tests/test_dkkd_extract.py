"""Đọc giấy tờ cho web ĐKKD (app/dkkd_extract.py + hai endpoint /dkkd/*).

Ba thứ hỏng ở đây đều âm thầm:
  * hàng rào Origin thủng → web lạ nhúng được máy chủ GPU của HDS;
  * payload app đổi hình (documents / images / image) mà máy chủ chỉ đọc một
    kiểu → khách thấy "không đọc được" dù ảnh đẹp;
  * Ollama bản cũ từ chối JSON Schema / cờ think → 502 thay vì lùi êm.

Toàn bộ test thay tầng mạng bằng đồ giả: KHÔNG chạm Ollama, không cần GPU,
không cần CSDL (deploy/update.sh chạy bộ test này trên máy chủ đang phục vụ).
"""
import base64
import io
import json
import types
import unittest

from fastapi import HTTPException

from app import api, dkkd_extract as dk


def _png_bytes(w=40, h=30, mode="RGB"):
    from PIL import Image
    img = Image.new(mode, (w, h), (200, 30, 30) if mode == "RGB" else (200, 30, 30, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _data_url(data: bytes, mime="image/png") -> str:
    return f"data:{mime};base64," + base64.b64encode(data).decode()


class _Resp:
    def __init__(self, status, payload=None, text=""):
        self.status_code = status
        self._payload = payload
        self.text = text
        self.ok = status < 400

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class OriginTests(unittest.TestCase):
    ALLOWED = ["https://dkkd.hdslaw.vn", "http://localhost:3000/"]

    def test_origin_dung_duoc_qua(self):
        self.assertTrue(dk.origin_allowed("https://dkkd.hdslaw.vn", None, self.ALLOWED))
        # Không phân biệt hoa thường, bỏ qua dấu '/' cuối.
        self.assertTrue(dk.origin_allowed("HTTPS://DKKD.hdslaw.vn/", None, self.ALLOWED))
        self.assertTrue(dk.origin_allowed("http://localhost:3000", None, self.ALLOWED))

    def test_origin_la_bi_chan(self):
        self.assertFalse(dk.origin_allowed("https://ke-la.vn", None, self.ALLOWED))
        # Cùng host nhưng khác scheme/port là khác origin.
        self.assertFalse(dk.origin_allowed("http://dkkd.hdslaw.vn", None, self.ALLOWED))
        self.assertFalse(dk.origin_allowed("https://dkkd.hdslaw.vn:8443", None, self.ALLOWED))
        # Tiền tố giống không đủ.
        self.assertFalse(dk.origin_allowed("https://dkkd.hdslaw.vn.evil.com", None, self.ALLOWED))

    def test_thieu_origin_thi_lay_goc_referer(self):
        self.assertTrue(dk.origin_allowed(None, "https://dkkd.hdslaw.vn/form?x=1", self.ALLOWED))
        self.assertTrue(dk.origin_allowed("null", "https://dkkd.hdslaw.vn/", self.ALLOWED))
        self.assertFalse(dk.origin_allowed(None, "https://ke-la.vn/", self.ALLOWED))
        self.assertFalse(dk.origin_allowed(None, None, self.ALLOWED))

    def test_danh_sach_trong_la_khong_ai_duoc(self):
        self.assertFalse(dk.origin_allowed("https://dkkd.hdslaw.vn", None, []))


class ParseDocumentsTests(unittest.TestCase):
    def test_documents_moi_du_truong(self):
        png = _png_bytes()
        docs = dk.parse_documents({"documents": [
            {"image": _data_url(png), "mimeType": "image/png", "filename": "truoc.png"},
            {"image": _data_url(png, "image/jpeg"), "mimeType": "image/jpeg"},
        ]})
        self.assertEqual([d["mime"] for d in docs], ["image/png", "image/jpeg"])
        self.assertEqual(docs[0]["data"], png)
        self.assertEqual(docs[0]["filename"], "truoc.png")

    def test_payload_cu_images_va_image(self):
        png = _png_bytes()
        self.assertEqual(len(dk.parse_documents({"images": [_data_url(png), _data_url(png)]})), 2)
        one = dk.parse_documents({"image": _data_url(png), "mimeType": "image/png"})
        self.assertEqual(one[0]["mime"], "image/png")

    def test_thieu_mime_thi_doan_tu_byte(self):
        png = _png_bytes()
        raw_b64 = base64.b64encode(png).decode()
        docs = dk.parse_documents({"images": [raw_b64]})
        self.assertEqual(docs[0]["mime"], "image/png")
        pdf = dk.parse_documents({"images": ["data:;base64," + base64.b64encode(b"%PDF-1.4 x").decode()]})
        self.assertEqual(pdf[0]["mime"], "application/pdf")

    def test_image_jpg_doi_thanh_jpeg(self):
        docs = dk.parse_documents({"documents": [{"image": _data_url(_png_bytes(), "image/jpg")}]})
        self.assertEqual(docs[0]["mime"], "image/jpeg")

    def test_loi_ro_rang(self):
        for body, status in [
            ({}, 400),
            ([], 400),
            ({"documents": []}, 400),
            ({"images": ["data:image/png;base64,@@@"]}, 400),
            ({"images": ["data:text/plain;base64," + base64.b64encode(b"hi").decode()]}, 400),
            ({"images": [_data_url(_png_bytes())] * (dk.MAX_DOCS + 1)}, 413),
        ]:
            with self.assertRaises(dk.DkkdError, msg=body) as ctx:
                dk.parse_documents(body)
            self.assertEqual(ctx.exception.status, status, body)

    def test_anh_qua_co(self):
        goc = dk.MAX_IMAGE_MB
        dk.MAX_IMAGE_MB = 0
        try:
            with self.assertRaises(dk.DkkdError) as ctx:
                dk.parse_documents({"images": [_data_url(_png_bytes())]})
            self.assertEqual(ctx.exception.status, 413)
        finally:
            dk.MAX_IMAGE_MB = goc


class ToImagesTests(unittest.TestCase):
    def test_thu_nho_va_xuat_jpeg(self):
        from PIL import Image
        big = _png_bytes(4000, 3000)
        out = dk.to_images([{"mime": "image/png", "data": big}], max_edge=1600)
        self.assertEqual(len(out), 1)
        img = Image.open(io.BytesIO(base64.b64decode(out[0])))
        self.assertEqual(img.format, "JPEG")
        self.assertEqual(max(img.size), 1600)
        self.assertEqual(img.mode, "RGB")

    def test_anh_nho_khong_phong_to(self):
        from PIL import Image
        out = dk.to_images([{"mime": "image/png", "data": _png_bytes(40, 30)}], max_edge=1600)
        img = Image.open(io.BytesIO(base64.b64decode(out[0])))
        self.assertEqual(img.size, (40, 30))

    def test_png_trong_suot_len_nen_trang(self):
        from PIL import Image
        out = dk.to_images([{"mime": "image/png", "data": _png_bytes(10, 10, "RGBA")}])
        img = Image.open(io.BytesIO(base64.b64decode(out[0]))).convert("RGB")
        r, g, b = img.getpixel((5, 5))
        self.assertGreater(min(r, g, b), 240)     # trắng, không phải đen

    def test_file_khong_phai_anh(self):
        with self.assertRaises(dk.DkkdError) as ctx:
            dk.to_images([{"mime": "image/png", "data": b"khong phai anh"}])
        self.assertEqual(ctx.exception.status, 400)


class CallVisionTests(unittest.TestCase):
    def _post_ok(self, calls):
        def post(url, json=None, timeout=None):
            calls.append(json)
            return _Resp(200, {"response": '{"documentType":"cccd","name":"A"}'})
        return post

    def test_body_gui_ollama_dung_khung(self):
        calls = []
        text = dk.call_vision(["abc"], model="qwen2.5vl:7b", post=self._post_ok(calls))
        self.assertIn('"cccd"', text)
        body = calls[0]
        self.assertEqual(body["model"], "qwen2.5vl:7b")
        self.assertEqual(body["images"], ["abc"])
        self.assertFalse(body["stream"])
        self.assertEqual(body["format"], dk.RESPONSE_SCHEMA)
        self.assertEqual(body["options"]["temperature"], 0)
        self.assertNotIn("think", body)             # qwen2.5vl không có chế độ suy nghĩ

    def test_keep_alive_mac_dinh_do_ngay(self):
        goc = dk.VISION_KEEP_ALIVE
        try:
            dk.VISION_KEEP_ALIVE = "0"
            self.assertEqual(dk._keep_alive_value(), 0)
            dk.VISION_KEEP_ALIVE = "2m"
            self.assertEqual(dk._keep_alive_value(), "2m")
            dk.VISION_KEEP_ALIVE = "-1"
            self.assertEqual(dk._keep_alive_value(), -1)
        finally:
            dk.VISION_KEEP_ALIVE = goc

    def test_model_qwen3_gui_think_false_va_lui_khi_400(self):
        calls = []

        def post(url, json=None, timeout=None):
            calls.append(dict(json))
            if "think" in json:
                return _Resp(400, {"error": "unknown field think"})
            return _Resp(200, {"response": "{}"})
        dk.call_vision(["x"], model="qwen3-vl:8b", post=post)
        self.assertIs(calls[0]["think"], False)
        self.assertEqual(len(calls), 2)
        self.assertNotIn("think", calls[1])

    def test_ollama_cu_khong_nhan_schema_thi_ha_ve_json(self):
        calls = []

        def post(url, json=None, timeout=None):
            calls.append(dict(json))
            if isinstance(json["format"], dict):
                return _Resp(400, {"error": "invalid format"})
            return _Resp(200, {"response": "{}"})
        dk.call_vision(["x"], model="qwen2.5vl:7b", post=post)
        self.assertEqual(calls[-1]["format"], "json")

    def test_thieu_model_bao_ro_lenh_pull(self):
        def post(url, json=None, timeout=None):
            return _Resp(404, {"error": "model 'qwen2.5vl:7b' not found"})
        with self.assertRaises(dk.DkkdError) as ctx:
            dk.call_vision(["x"], model="qwen2.5vl:7b", post=post)
        self.assertEqual(ctx.exception.status, 503)
        self.assertIn("ollama pull qwen2.5vl:7b", ctx.exception.message)

    def test_ollama_tat(self):
        import requests

        def post(url, json=None, timeout=None):
            raise requests.exceptions.ConnectionError("refused")
        with self.assertRaises(dk.DkkdError) as ctx:
            dk.call_vision(["x"], model="m", post=post)
        self.assertEqual(ctx.exception.status, 503)


class NormalizeTests(unittest.TestCase):
    def test_parse_json_boc_fence_hoac_kem_cau(self):
        self.assertEqual(dk.parse_model_json('```json\n{"a":1}\n```'), {"a": 1})
        self.assertEqual(dk.parse_model_json('Đây là kết quả: {"a":1} xong'), {"a": 1})
        self.assertEqual(dk.parse_model_json("không json"), {})
        self.assertEqual(dk.parse_model_json("[1,2]"), {})

    def test_du_14_truong_toan_chuoi(self):
        out = dk.normalize_result({"documentType": "CCCD", "name": "NGUYỄN A", "dob": None,
                                   "idNumber": 123, "phone": ["x"], "extra": "bỏ"})
        self.assertEqual(set(out), set(dk.FIELDS))
        self.assertEqual(out["documentType"], "cccd")
        self.assertEqual(out["idNumber"], "123")
        self.assertEqual(out["dob"], "")
        self.assertEqual(out["phone"], "")
        self.assertNotIn("extra", out)

    def test_none_xoa_sach_moi_truong(self):
        out = dk.normalize_result({"documentType": "none", "name": "NGUYỄN VĂN A"})
        self.assertEqual(out["documentType"], "none")
        self.assertEqual(out["name"], "")

    def test_loai_la_va_khong_co_gi_thi_thanh_none(self):
        self.assertEqual(dk.normalize_result({"documentType": "hoa_don"})["documentType"], "none")
        # Loại lạ nhưng có dữ liệu: để trống loại, giữ dữ liệu cho app tự lọc.
        out = dk.normalize_result({"documentType": "hoa_don", "name": "X"})
        self.assertEqual(out["documentType"], "")
        self.assertEqual(out["name"], "X")

    def test_extract_tron_luong(self):
        def post(url, json=None, timeout=None):
            self.assertEqual(len(json["images"]), 1)
            return _Resp(200, {"response": json_dumps({"documentType": "cccd", "name": "TRẦN B",
                                                       "idNumber": "012345678901"})})
        out = dk.extract([{"mime": "image/png", "data": _png_bytes()}], model="m", post=post)
        self.assertEqual(out["name"], "TRẦN B")
        self.assertEqual(out["ward"], "")

    def test_extract_model_tra_rac(self):
        def post(url, json=None, timeout=None):
            return _Resp(200, {"response": "xin lỗi tôi không đọc được"})
        with self.assertRaises(dk.DkkdError) as ctx:
            dk.extract([{"mime": "image/png", "data": _png_bytes()}], model="m", post=post)
        self.assertEqual(ctx.exception.status, 502)


def json_dumps(o):
    return json.dumps(o, ensure_ascii=False)


class StatusTests(unittest.TestCase):
    def test_bao_pulled_va_loaded(self):
        def get(url, timeout=None):
            if url.endswith("/api/tags"):
                return _Resp(200, {"models": [{"name": "qwen2.5vl:7b"}, {"name": "qwen3:14b"}]})
            return _Resp(200, {"models": [{"name": "qwen3:14b"}]})
        goc = dk.VISION_MODEL
        try:
            dk.VISION_MODEL = "qwen2.5vl:7b"
            st = dk.status(get=get)
            self.assertTrue(st["ollama"])
            self.assertTrue(st["pulled"])
            self.assertFalse(st["loaded"])
            dk.VISION_MODEL = "qwen3-vl:8b"
            self.assertFalse(dk.status(get=get)["pulled"])
        finally:
            dk.VISION_MODEL = goc

    def test_ollama_tat_khong_no(self):
        def get(url, timeout=None):
            raise OSError("refused")
        st = dk.status(get=get)
        self.assertFalse(st["ollama"])
        self.assertIn("error", st)


def _request(origin=None, referer=None, ip="203.0.113.9"):
    headers = {}
    if origin:
        headers["origin"] = origin
    if referer:
        headers["referer"] = referer
    return types.SimpleNamespace(headers=headers, client=types.SimpleNamespace(host=ip))


class GateTests(unittest.TestCase):
    """Cổng vào /dkkd/extract trong api.py: tắt khi chưa khai origin, chặn origin
    lạ, van tần suất riêng không dùng chung bộ đếm với /chat/public."""

    def setUp(self):
        self._goc_allowed = dk.ALLOWED_ORIGINS
        self._goc_max = api.DKKD_RATE_MAX
        api._dkkd_hits.clear()
        api._public_hits.clear()

    def tearDown(self):
        dk.ALLOWED_ORIGINS = self._goc_allowed
        api.DKKD_RATE_MAX = self._goc_max
        api._dkkd_hits.clear()
        api._public_hits.clear()

    def test_chua_khai_origin_la_503(self):
        dk.ALLOWED_ORIGINS = []
        with self.assertRaises(HTTPException) as ctx:
            api._dkkd_gate(_request(origin="https://dkkd.hdslaw.vn"))
        self.assertEqual(ctx.exception.status_code, 503)

    def test_origin_la_403(self):
        dk.ALLOWED_ORIGINS = ["https://dkkd.hdslaw.vn"]
        with self.assertRaises(HTTPException) as ctx:
            api._dkkd_gate(_request(origin="https://ke-la.vn"))
        self.assertEqual(ctx.exception.status_code, 403)
        with self.assertRaises(HTTPException) as ctx:
            api._dkkd_gate(_request())
        self.assertEqual(ctx.exception.status_code, 403)

    def test_origin_dung_qua_va_van_rieng(self):
        dk.ALLOWED_ORIGINS = ["https://dkkd.hdslaw.vn"]
        api.DKKD_RATE_MAX = 2
        req = _request(origin="https://dkkd.hdslaw.vn")
        api._dkkd_gate(req)
        api._dkkd_gate(req)
        with self.assertRaises(HTTPException) as ctx:
            api._dkkd_gate(req)
        self.assertEqual(ctx.exception.status_code, 429)
        # IP khác vẫn gọi được; bộ đếm kênh chat công khai không bị đụng.
        api._dkkd_gate(_request(origin="https://dkkd.hdslaw.vn", ip="198.51.100.7"))
        self.assertEqual(api._public_hits, {})

    def test_cors_gom_origin_dkkd(self):
        # Origin ĐKKD phải có mặt trong danh sách CORS, không thì trình duyệt
        # chặn ở preflight và endpoint không bao giờ được gọi.
        for o in dk.ALLOWED_ORIGINS:
            self.assertIn(o, api._cors_origins)


if __name__ == "__main__":
    unittest.main()
