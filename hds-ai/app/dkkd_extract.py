"""
dkkd_extract.py — Đọc giấy tờ (CCCD / hộ chiếu / Giấy ĐKDN) cho app Đăng ký
kinh doanh bằng model NHÌN ẢNH chạy trên Ollama.

Vì sao là một module riêng, không đi qua rag.py:
  * Model chat mặc định (qwen3) là model CHỮ, không nhìn được ảnh. Việc này cần
    một model thị giác (VISION_MODEL, mặc định qwen2.5vl:7b) — nạp riêng.
  * App ĐKKD là web công khai cho khách tự điền hồ sơ, KHÔNG có tài khoản trên
    hệ thống này. Không đi qua kho tri thức, không chạm CSDL, không cần đăng
    nhập — chỉ nhận ảnh, trả JSON các trường, xong.
  * GPU 16GB không chứa cùng lúc qwen3:14b lẫn model thị giác. Mặc định
    VISION_KEEP_ALIVE=0: Ollama dỡ model thị giác khỏi VRAM NGAY sau khi trả
    lời — "chỉ nạp khi dùng". Lượt đọc kế tiếp nạp lại mất vài giây, đổi lại
    chat nội bộ không bị chiếm VRAM giữa chừng.

Hợp đồng dữ liệu bám đúng cái app ĐKKD đang gửi cho n8n (src/services/
geminiService.ts) — đổi URL webhook là chạy, không phải sửa app:

  Vào : {"documents":[{"image":"data:image/jpeg;base64,...","mimeType":"image/jpeg",
                       "filename":"cccd-truoc.jpg"}, ...]}
        (bản cũ: "images":[...dataURL] hoặc "image": dataURL — vẫn nhận)
  Ra  : {"documentType":"cccd","name":"...","dob":"dd/mm/yyyy", ... 14 trường}
        Ảnh không phải giấy tờ → documentType="none", mọi trường rỗng.

Bộ lọc chống bịa (NGUYỄN VĂN A, 123456789012...) app vẫn chạy ở phía trình
duyệt (sanitizeExtracted) nên máy chủ chỉ cần trả đúng những gì model đọc được.
"""
import base64
import io
import json
import logging
import os
import re
from urllib.parse import urlparse

import requests

from app import models

log = logging.getLogger("hds.dkkd")

# ---- Cấu hình (đọc từ .env qua dotenv đã nạp ở app.models) -------------------
VISION_MODEL = os.getenv("VISION_MODEL", "qwen2.5vl:7b").strip()
# "0" = dỡ khỏi VRAM ngay sau khi trả lời (chỉ nạp khi dùng). Đặt "2m" nếu
# khách hay tải nhiều giấy tờ liên tiếp và card đủ chỗ cho cả hai model.
VISION_KEEP_ALIVE = os.getenv("VISION_KEEP_ALIVE", "0").strip() or "0"
# Ngữ cảnh cho model thị giác: 2 mặt CCCD + prompt + JSON trả về nằm gọn trong
# 8K. Không dùng llm_num_ctx (32K) — KV cache của ngữ cảnh 32K là thứ đẩy model
# tràn VRAM (xem HUONG_DAN_IT.md, mục GPU 16GB).
VISION_NUM_CTX = int(os.getenv("VISION_NUM_CTX", "8192"))
VISION_NUM_PREDICT = int(os.getenv("VISION_NUM_PREDICT", "700"))
VISION_TIMEOUT_SEC = int(os.getenv("VISION_TIMEOUT_SEC", "300"))
# Ảnh điện thoại 4000x3000 tốn hàng nghìn token thị giác mà chữ trên CCCD không
# rõ hơn. 1600px cạnh dài là đủ đọc số nhỏ, nhanh gấp nhiều lần.
VISION_MAX_EDGE = int(os.getenv("VISION_MAX_EDGE", "1600"))

# Origin (scheme://host[:port]) của web được phép gọi. TRỐNG = tắt endpoint.
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("DKKD_ALLOWED_ORIGINS", "").split(",")
                   if o.strip()]
MAX_DOCS = int(os.getenv("DKKD_MAX_DOCS", "4"))
MAX_IMAGE_MB = int(os.getenv("DKKD_MAX_IMAGE_MB", "10"))
MAX_PDF_PAGES = int(os.getenv("DKKD_MAX_PDF_PAGES", "2"))

IMAGE_MIMES = {"image/jpeg", "image/jpg", "image/png", "image/webp", "image/bmp",
               "image/tiff", "image/heic", "image/heif"}
PDF_MIME = "application/pdf"

FIELDS = ["documentType", "name", "dob", "gender", "idNumber", "address",
          "addressDetail", "ward", "district", "province", "phone", "email",
          "orgName", "orgCode"]
DOC_TYPES = ["cccd", "passport", "dkdn", "none"]

# Ép model trả đúng khung — Ollama (>=0.5) nhận JSON Schema ở trường `format`.
# Bản Ollama cũ chỉ nhận format="json": gọi thử schema, bị 400 thì lùi.
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        **{f: {"type": "string"} for f in FIELDS},
        "documentType": {"type": "string", "enum": DOC_TYPES},
    },
    "required": FIELDS,
}

PROMPT = """Bạn là chuyên gia OCR giấy tờ pháp lý Việt Nam. Có thể có NHIỀU ảnh đính kèm —
thường là MẶT TRƯỚC và MẶT SAU của cùng một thẻ Căn cước/CCCD, hoặc Hộ chiếu,
hoặc Giấy chứng nhận đăng ký doanh nghiệp.

GỘP thông tin từ TẤT CẢ các ảnh vào MỘT object JSON duy nhất. Mặt trước có họ tên,
ngày sinh, giới tính, số định danh; mặt sau có nơi cư trú. Chỉ trả JSON, không giải thích.

=== CHỐNG BỊA - QUAN TRỌNG NHẤT ===
Hồ sơ này dùng để đăng ký kinh doanh, dữ liệu sai gây hậu quả pháp lý.
- Chỉ chép lại ký tự BẠN THỰC SỰ NHÌN THẤY trên ảnh. Không suy đoán, không điền dữ liệu mẫu.
- Nếu ảnh trắng trơn, mờ, bị che, không phải giấy tờ, hoặc không đọc được chữ nào:
  đặt documentType = "none" và TẤT CẢ các trường còn lại để chuỗi rỗng.
- Trường nào không nhìn rõ thì để chuỗi rỗng. Thà để rỗng còn hơn đoán sai.
- TUYỆT ĐỐI không được tự nghĩ ra tên như NGUYỄN VĂN A, số như 123456789012,
  hay địa chỉ như 123 Đường Lê Lợi. Đó là bịa, không được phép.

Các trường (thiếu thì để chuỗi rỗng ""):
- documentType: loại giấy tờ đọc được, chỉ một trong: cccd, passport, dkdn, none.
- name: Họ và tên cá nhân (mục "Họ và tên / Full name"), HOẶC tên doanh nghiệp nếu là Giấy ĐKDN. VIẾT HOA, GIỮ NGUYÊN dấu tiếng Việt.
- dob: Ngày sinh, định dạng dd/mm/yyyy (ví dụ 25/12/1990).
- gender: Chỉ "Nam" hoặc "Nữ" (từ mục Giới tính/Sex; "Male"->Nam, "Female"->Nữ).
- idNumber: Số định danh cá nhân — mục "Số / No." trên CCCD (đúng 12 chữ số), hoặc số hộ chiếu, hoặc Mã số doanh nghiệp nếu là Giấy ĐKDN. CHỈ giữ chữ số cho CCCD.
- address: Nơi cư trú/thường trú GHI ĐẦY ĐỦ như in trên thẻ (mặt sau), hoặc địa chỉ trụ sở nếu là Giấy ĐKDN.
- addressDetail: CHỈ phần số nhà / tổ / khu phố / thôn / đường, cắt ra từ address (bỏ phường/xã, quận/huyện, tỉnh).
- ward: CHỈ tên Phường/Xã/Thị trấn trong address, không kèm chữ "Phường"/"Xã".
- district: CHỈ tên Quận/Huyện/Thị xã/Thành phố thuộc tỉnh trong address (thẻ cũ mới có),
  không kèm chữ "Quận"/"Huyện". Thẻ cấp sau 01/7/2025 không in cấp huyện -> để rỗng.
- province: CHỈ tên Tỉnh/Thành phố trong address, không kèm chữ "Tỉnh"/"Thành phố".
- phone: Số điện thoại nếu có.
- email: Email nếu có.
- orgName: Tên doanh nghiệp (chỉ khi là Giấy ĐKDN), VIẾT HOA.
- orgCode: Mã số doanh nghiệp (chỉ khi là Giấy ĐKDN).

Quy tắc:
- Ngày LUÔN dd/mm/yyyy. Không suy đoán thông tin không có trên giấy.
- Chép đúng địa danh in trên thẻ, KHÔNG tự quy đổi sang đơn vị hành chính mới.
- KHÔNG trích "ngày cấp", "nơi cấp" (không cần)."""


class DkkdError(Exception):
    """Lỗi có mã HTTP kèm câu chữ đưa thẳng cho người dùng."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


# ---- 1. Kiểm tra nguồn gọi ------------------------------------------------------
def origin_allowed(origin, referer, allowed=None) -> bool:
    """Web nào được gọi. So `Origin` (trình duyệt luôn gửi khi POST chéo
    nguồn); thiếu thì lấy gốc của `Referer`. Danh sách trống = không ai.

    Đây là hàng rào "chỉ web của tôi" cho TRÌNH DUYỆT — kẻ dùng curl giả được
    header, nên phía sau còn van tần suất theo IP (api.py). Endpoint không mở
    vào dữ liệu nào của hệ thống, chỉ tốn GPU, nên hai lớp này là đủ.
    """
    allowed = ALLOWED_ORIGINS if allowed is None else allowed
    if not allowed:
        return False
    src = (origin or "").strip()
    if not src or src.lower() == "null":
        p = urlparse((referer or "").strip())
        src = f"{p.scheme}://{p.netloc}" if p.scheme and p.netloc else ""
    if not src:
        return False
    src = src.rstrip("/").lower()
    return src in {a.rstrip("/").lower() for a in allowed}


# ---- 2. Đọc payload của app ------------------------------------------------------
_DATA_URL = re.compile(r"^data:(?P<mime>[\w.+-]+/[\w.+-]+)?(?:;[\w=-]+)*;base64,(?P<b64>.*)$",
                       re.S)


def _decode_data_url(value: str, mime_hint: str = "") -> tuple[str, bytes]:
    """'data:image/jpeg;base64,....' -> (mime, bytes). Chuỗi base64 trần cũng nhận."""
    value = (value or "").strip()
    if not value:
        raise DkkdError(400, "Thiếu dữ liệu ảnh")
    m = _DATA_URL.match(value)
    mime = (m.group("mime") if m else "") or mime_hint or ""
    b64 = m.group("b64") if m else value
    try:
        data = base64.b64decode(re.sub(r"\s+", "", b64), validate=True)
    except Exception:
        raise DkkdError(400, "Ảnh không phải base64 hợp lệ") from None
    if not data:
        raise DkkdError(400, "Ảnh rỗng")
    return mime.lower().strip(), data


def parse_documents(body) -> list[dict]:
    """Chuẩn hoá mọi kiểu payload app từng gửi về một danh sách
    [{"mime", "data", "filename"}], kiểm cỡ + định dạng ngay tại đây."""
    if not isinstance(body, dict):
        raise DkkdError(400, "Body phải là JSON object")
    raw: list = []
    docs = body.get("documents")
    if isinstance(docs, list) and docs:
        for d in docs:
            if isinstance(d, dict):
                raw.append((d.get("image") or d.get("data") or "",
                            d.get("mimeType") or d.get("mime_type") or "",
                            d.get("filename") or ""))
            elif isinstance(d, str):
                raw.append((d, "", ""))
    elif isinstance(body.get("images"), list) and body["images"]:
        raw = [(s, "", "") for s in body["images"] if isinstance(s, str)]
    elif isinstance(body.get("image"), str) and body["image"].strip():
        raw = [(body["image"], body.get("mimeType") or "", body.get("filename") or "")]
    if not raw:
        raise DkkdError(400, "Không có ảnh nào trong yêu cầu (cần trường documents)")
    if len(raw) > MAX_DOCS:
        raise DkkdError(413, f"Tối đa {MAX_DOCS} ảnh mỗi lượt")

    limit = MAX_IMAGE_MB * 1024 * 1024
    out = []
    for value, mime_hint, filename in raw:
        mime, data = _decode_data_url(value, str(mime_hint or "").lower())
        if len(data) > limit:
            raise DkkdError(413, f"Ảnh vượt quá {MAX_IMAGE_MB} MB")
        if not mime:
            mime = _sniff_mime(data)
        if mime == "image/jpg":
            mime = "image/jpeg"
        if mime != PDF_MIME and mime not in IMAGE_MIMES:
            raise DkkdError(400, f"Không nhận định dạng {mime or '(không rõ)'} — "
                                 "gửi ảnh JPG/PNG/WEBP hoặc PDF")
        out.append({"mime": mime, "data": data, "filename": str(filename or "")[:120]})
    return out


def _sniff_mime(data: bytes) -> str:
    head = data[:16]
    if head.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG"):
        return "image/png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head.startswith(b"%PDF"):
        return PDF_MIME
    if head.startswith(b"BM"):
        return "image/bmp"
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return "image/tiff"
    return ""


# ---- 3. Ảnh -> JPEG gọn cho model ---------------------------------------------
def _pil_to_jpeg_b64(img, max_edge: int = None) -> str:
    from PIL import Image, ImageOps

    max_edge = max_edge or VISION_MAX_EDGE
    img = ImageOps.exif_transpose(img)         # ảnh điện thoại hay xoay theo EXIF
    if img.mode in ("RGBA", "LA", "P"):
        # PNG trong suốt: đặt lên nền trắng, không để nền đen nuốt chữ tối.
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.getchannel("A"))
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")
    if max(img.size) > max_edge:
        img.thumbnail((max_edge, max_edge), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90, optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _image_bytes_to_b64(data: bytes, max_edge: int = None) -> str:
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            return _pil_to_jpeg_b64(img, max_edge)
    except UnidentifiedImageError:
        raise DkkdError(400, "Không mở được ảnh — file hỏng hoặc không phải ảnh") from None
    except Image.DecompressionBombError:
        raise DkkdError(413, "Ảnh quá lớn (số điểm ảnh vượt giới hạn)") from None


def _pdf_bytes_to_b64(data: bytes, max_edge: int = None) -> list[str]:
    try:
        from pdf2image import convert_from_bytes
    except ImportError:
        raise DkkdError(503, "Máy chủ thiếu pdf2image/poppler để đọc PDF — "
                             "gửi ảnh JPG/PNG thay thế") from None
    try:
        pages = convert_from_bytes(data, dpi=200, first_page=1, last_page=MAX_PDF_PAGES)
    except Exception as e:                     # poppler thiếu, PDF hỏng, mã hoá...
        raise DkkdError(400, f"Không đọc được PDF: {str(e)[:120]}") from None
    if not pages:
        raise DkkdError(400, "PDF không có trang nào")
    return [_pil_to_jpeg_b64(p, max_edge) for p in pages]


def to_images(docs: list[dict], max_edge: int = None) -> list[str]:
    """Danh sách tài liệu đã parse -> danh sách JPEG base64 đưa cho model.
    Một PDF có thể thành nhiều ảnh (mỗi trang một ảnh, tối đa MAX_PDF_PAGES)."""
    out: list[str] = []
    for d in docs:
        if d["mime"] == PDF_MIME:
            out.extend(_pdf_bytes_to_b64(d["data"], max_edge))
        else:
            out.append(_image_bytes_to_b64(d["data"], max_edge))
    if len(out) > MAX_DOCS * MAX_PDF_PAGES:
        raise DkkdError(413, "Quá nhiều trang trong một lượt")
    return out


# ---- 4. Gọi model thị giác trên Ollama ------------------------------------------
def _keep_alive_value():
    """Ollama nhận keep_alive là số giây hoặc chuỗi thời lượng ('2m'). Giữ
    '0' thành số 0 để chắc chắn được hiểu là 'dỡ ngay'."""
    v = VISION_KEEP_ALIVE
    return int(v) if re.fullmatch(r"-?\d+", v) else v


def _build_body(images_b64: list[str], model: str, fmt) -> dict:
    body = {
        "model": model,
        "prompt": PROMPT,
        "images": images_b64,
        "stream": False,
        "format": fmt,
        "keep_alive": _keep_alive_value(),
        "options": {"temperature": 0, "num_ctx": VISION_NUM_CTX,
                    "num_predict": VISION_NUM_PREDICT},
    }
    if models.is_thinking_model(model):
        body["think"] = False
    return body


def call_vision(images_b64: list[str], model: str = None, post=None) -> str:
    """Gửi ảnh + prompt cho Ollama, trả CHUỖI phản hồi thô của model.

    Hai đường lùi cho Ollama bản cũ, mỗi đường thử đúng một lần:
      * 400 khi có `think`   -> bỏ cờ think (model không có chế độ suy nghĩ);
      * 400 khi format=schema -> hạ về format="json".
    `post` thay được trong test để không gọi mạng thật."""
    model = model or VISION_MODEL
    post = post or requests.post
    if not model:
        raise DkkdError(503, "Chưa cấu hình VISION_MODEL trong .env")
    body = _build_body(images_b64, model, RESPONSE_SCHEMA)
    tried_think = tried_schema = False
    for _ in range(3):
        try:
            r = post(f"{models.OLLAMA_URL}/api/generate", json=body,
                     timeout=VISION_TIMEOUT_SEC)
        except requests.exceptions.ConnectionError:
            raise DkkdError(503, "Không kết nối được Ollama trên máy chủ") from None
        except requests.exceptions.Timeout:
            raise DkkdError(504, "Model đọc ảnh quá lâu, thử lại với ảnh nhỏ hơn") from None
        if r.status_code == 404:
            raise DkkdError(503, f"Ollama chưa có model '{model}'. "
                                 f"Chạy trên máy chủ: ollama pull {model}")
        if r.status_code == 400:
            if "think" in body and not tried_think:
                body.pop("think")
                tried_think = True
                continue
            if isinstance(body.get("format"), dict) and not tried_schema:
                body["format"] = "json"
                tried_schema = True
                continue
            raise DkkdError(502, f"Ollama từ chối yêu cầu: {_err_text(r)}")
        if r.status_code >= 500:
            raise DkkdError(502, f"Ollama lỗi {r.status_code}: {_err_text(r)}")
        try:
            data = r.json()
        except ValueError:
            raise DkkdError(502, "Ollama trả về dữ liệu không phải JSON") from None
        return (data.get("response") or "").strip()
    raise DkkdError(502, "Ollama từ chối yêu cầu sau khi đã thử các cách lùi")


def _err_text(r) -> str:
    try:
        return str(r.json().get("error") or "")[:200]
    except Exception:
        return (r.text or "")[:200]


# ---- 5. Chuẩn hoá kết quả -------------------------------------------------------
def parse_model_json(text: str) -> dict:
    """Model đôi khi vẫn bọc ```json hoặc kèm một câu; lấy object đầu tiên."""
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.S).strip()
    try:
        obj = json.loads(t)
    except ValueError:
        m = re.search(r"\{.*\}", t, re.S)
        if not m:
            return {}
        try:
            obj = json.loads(m.group(0))
        except ValueError:
            return {}
    return obj if isinstance(obj, dict) else {}


def normalize_result(raw: dict) -> dict:
    """Đủ 14 trường, toàn chuỗi, documentType thuộc danh sách cho phép."""
    out = {}
    for f in FIELDS:
        v = raw.get(f) if isinstance(raw, dict) else None
        if v is None or isinstance(v, bool):
            v = ""
        elif isinstance(v, (list, dict)):
            v = ""
        out[f] = str(v).strip()
    dt = out["documentType"].lower()
    out["documentType"] = dt if dt in DOC_TYPES else ("none" if not any(
        out[f] for f in FIELDS if f != "documentType") else "")
    if out["documentType"] == "none":
        for f in FIELDS:
            if f != "documentType":
                out[f] = ""
    return out


def extract(docs: list[dict], model: str = None, post=None) -> dict:
    """Trọn luồng: tài liệu đã parse -> ảnh gọn -> model -> JSON 14 trường."""
    images = to_images(docs)
    text = call_vision(images, model=model, post=post)
    obj = parse_model_json(text)
    if not obj:
        log.warning("dkkd: model trả về không phải JSON: %.200s", text)
        raise DkkdError(502, "Model không trả về JSON hợp lệ, thử lại")
    return normalize_result(obj)


# ---- 6. Tình trạng để IT kiểm tra ------------------------------------------------
def status(get=None) -> dict:
    get = get or requests.get
    info = {"model": VISION_MODEL, "keep_alive": VISION_KEEP_ALIVE,
            "allowed_origins": len(ALLOWED_ORIGINS), "enabled": bool(ALLOWED_ORIGINS),
            "ollama": False, "pulled": False, "loaded": False}
    try:
        r = get(f"{models.OLLAMA_URL}/api/tags", timeout=5)
        if r.status_code != 200:
            raise RuntimeError(f"/api/tags trả {r.status_code}")
        names = {m.get("name", "") for m in r.json().get("models", [])}
        info["ollama"] = True
        want = VISION_MODEL if ":" in VISION_MODEL else VISION_MODEL + ":latest"
        info["pulled"] = want in names or VISION_MODEL in names
        r2 = get(f"{models.OLLAMA_URL}/api/ps", timeout=5)
        if r2.status_code == 200:
            running = {m.get("name", "") for m in r2.json().get("models", [])}
            info["loaded"] = want in running or VISION_MODEL in running
    except Exception as e:                     # Ollama tắt / không tới được
        info["error"] = str(e)[:160]
    return info
