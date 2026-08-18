"""
settings.py — Cài đặt hệ thống lưu trong CSDL, admin sửa được trên web.

Trước đây phong cách tư vấn (system prompt) và bản đồ thư mục Drive nằm cứng
trong mã nguồn → muốn đổi phải sửa code rồi khởi động lại. Nay lưu ở bảng
`app_settings`: admin đổi trên giao diện, có hiệu lực ngay câu hỏi tiếp theo.

Đọc: get(key) / get_json(key) / get_prompt(channel)
Ghi: set(key, value, user_id)  — chỉ admin, kiểm ở tầng API.
"""
import json
import os
import threading
import time

from app import db

# ---------------------------------------------------------------
# Giá trị mặc định. Chỉ dùng khi CSDL chưa có bản ghi tương ứng —
# nghĩa là admin sửa trên web thì bản DB luôn thắng.
# ---------------------------------------------------------------
DEFAULTS = {
    # Phong cách tư vấn cho 3 kênh chat
    "prompt_public": (
        "Bạn là trợ lý của Công ty Luật HDS, trả lời khách trên website. "
        "Chỉ dựa vào TÀI LIỆU THAM KHẢO bên dưới. "
        "Trả lời NGẮN GỌN, khái quát, đúng trọng tâm. Nếu câu hỏi chưa rõ, "
        "hỏi lại một câu ngắn để làm rõ thay vì đoán. Không đủ căn cứ thì nói rõ. "
        "Không bịa điều luật, không nêu số hiệu văn bản nếu không có trong tài liệu. "
        "Kết thúc bằng gợi ý liên hệ luật sư HDS."
    ),
    "prompt_internal": (
        "Bạn là trợ lý pháp lý của HDS Law Firm — trò chuyện TỰ NHIÊN, THÂN "
        "THIỆN và chủ động như một đồng nghiệp giỏi, KHÔNG trả lời cộc lốc hay "
        "máy móc. Xưng 'mình'/'tôi' với người hỏi cho gần gũi. "
        "Dựa trên TÀI LIỆU THAM KHẢO và DỮ LIỆU CÔNG TY bên dưới để trả lời. "
        "LUÔN đọc DIỄN BIẾN CUỘC TRAO ĐỔI TRƯỚC ĐÓ để hiểu câu nối tiếp; nếu "
        "người dùng nói lại cho rõ (vd 'ý tôi là…', 'tôi hỏi X mà'), hiểu là "
        "đang chỉnh lại câu trước rồi trả lời luôn, đừng hỏi lại từ đầu. "
        "Trả lời rõ ràng, đủ ý, mạch lạc — trình bày dễ đọc (gạch đầu dòng khi "
        "cần) nhưng không lan man, không liệt kê máy móc mọi thứ dính từ khoá. "
        "Có ngày tháng/thời hạn thì tự so với HÔM NAY ở đầu prompt để biết còn "
        "hạn hay đã hết. "
        "NGUỒN SỰ THẬT: khi hỏi về nhân sự (bao nhiêu người, gồm những ai, chức "
        "danh, thời hạn hợp đồng), hãy trả lời theo HỒ SƠ NHÂN SỰ và HỢP ĐỒNG "
        "LAO ĐỘNG trong tài liệu — nêu rõ họ tên, chức danh, thời hạn của TỪNG "
        "người. Số tài khoản đăng nhập KHÔNG phải quân số công ty, chỉ nhắc tới "
        "khi được hỏi riêng về tài khoản phần mềm. "
        "Nếu dữ liệu chưa có thứ người dùng cần, nói thẳng một "
        "cách nhẹ nhàng và gợi ý bước tiếp theo (tìm ở đâu, cần bổ sung gì) — "
        "TUYỆT ĐỐI không bịa số liệu hay điều luật. Chỉ hỏi lại khi câu hỏi thật "
        "sự mơ hồ mà lịch sử cũng không giúp làm rõ. Trích Điều/Khoản và ghi "
        "[Nguồn n] khi dùng thông tin từ tài liệu. Đây là bản nháp tham khảo; "
        "luật sư chịu trách nhiệm cuối cùng."
    ),
    "prompt_portal": (
        "Bạn là trợ lý của HDS phục vụ khách hàng đã ký hợp đồng. "
        "Chỉ dùng TÀI LIỆU THAM KHẢO thuộc về khách đang đăng nhập — không nhắc "
        "tới bất kỳ khách hàng nào khác. Trả lời NGẮN GỌN, dễ hiểu, đúng trọng "
        "tâm. Nếu câu hỏi chưa rõ, hỏi lại một câu để làm rõ. Không đủ căn cứ "
        "trong tài liệu thì nói rõ và đề nghị liên hệ luật sư phụ trách."
    ),
    # Tham số sinh câu trả lời
    "llm_temperature": "0.2",
    # ---- Nhóm khoá quyết định TỐC ĐỘ trả lời ----------------------------
    # Thời gian trả lời ≈ (độ dài prompt ÷ tốc độ đọc) + (độ dài đáp ÷ tốc độ viết).
    # Bốn khoá dưới đây điều khiển vế thứ nhất; nới rộng là chậm đi tương ứng.
    # Kho tài liệu lớn lên KHÔNG làm prompt dài thêm — tìm kiếm vector luôn trả
    # đúng top_k đoạn — nên các con số này không cần đổi khi dữ liệu tăng.
    "retrieval_top_k": "5",          # số đoạn tài liệu đưa vào prompt
    "retrieval_candidate_k": "40",   # hybrid search lấy rộng trước khi rerank
    "retrieval_max_chunks_per_doc": "2", # đa dạng nguồn, tránh một file chiếm hết
    "chunk_char_limit": "1500",      # cắt mỗi đoạn còn bấy nhiêu ký tự
    "context_char_budget": "6000",   # trần ký tự cho toàn bộ tài liệu tham khảo
    "min_relevance": "0.25",         # dưới ngưỡng này coi như không liên quan
    "strict_grounding": "true",       # không citation hợp lệ thì chặn câu tài liệu
    # Cửa sổ ngữ cảnh của model. Prompt dài hơn mức này bị Ollama cắt mất phần
    # ĐẦU — đúng chỗ đặt DỮ LIỆU CÔNG TY — mà vẫn tốn thời gian đọc phần còn
    # lại. Nên để rộng hơn prompt thực tế một quãng an toàn, rồi giữ prompt gọn
    # bằng các trần bên trên; đó mới là chỗ quyết định tốc độ.
    #   prompt điển hình ≈ 6000 ký tự tài liệu + hồ sơ công ty + 3 lượt hội thoại
    #                     ≈ 4000 token → 8192 là vừa đủ thoáng.
    "llm_num_ctx": "8192",
    "llm_num_predict": "700",        # trần số token sinh ra = trần thời gian
    # Số luồng CPU cho model. 0 = để Ollama tự quyết (đúng cho máy có GPU).
    # Máy chạy CPU đôi khi nhanh hơn khi khai đúng số nhân — thử rồi đo lại.
    "llm_num_thread": "0",
    # Số lượt hỏi-đáp cũ đưa lại vào ngữ cảnh để bot hiểu "vụ đó", "khách kia".
    # Đặt 0 là tắt bộ nhớ hội thoại (mỗi câu hỏi độc lập).
    "chat_history_turns": "3",
    # Model sinh câu trả lời (Ollama). Rỗng = dùng LLM_MODEL trong .env của máy
    # chủ. Admin đổi trên web để chuyển sang model khác đã cài, không cần sửa
    # .env rồi khởi động lại. KHÔNG áp cho model tạo vector (bge-m3): mọi đoạn
    # đã lưu đều theo model đó, đổi là hỏng tra cứu.
    "llm_model": "",
    # Bản đồ thư mục Drive → nhãn tài liệu (app/auto_learn.py dùng).
    # Khoá được so khớp sau khi chuẩn hoá: bỏ số thứ tự đầu, bỏ dấu, viết thường.
    # Nhờ vậy "1. VĂN BẢN PHÁP LUẬT" và "van ban phap luat" là một.
    "drive_map": json.dumps(
        {
            "categories": {
                "văn bản pháp luật": {"doc_type": "law", "access_level": "public"},
                "bản án": {"doc_type": "ban_an", "access_level": "internal"},
                "án lệ": {"doc_type": "an_le", "access_level": "internal"},
                "bản án - án lệ": {"doc_type": "ban_an", "access_level": "internal"},
                "hợp đồng mẫu": {"doc_type": "mau_hd", "access_level": "internal"},
                "hợp đồng": {"doc_type": "contract", "access_level": "internal"},
                "quan điểm pháp lý": {"doc_type": "advisory", "access_level": "internal"},
                "thư tư vấn": {"doc_type": "advisory", "access_level": "internal"},
                "thư mẫu - biểu mẫu": {"doc_type": "thu_mau", "access_level": "internal"},
                "thư mẫu": {"doc_type": "thu_mau", "access_level": "internal"},
                "quy trình nội bộ": {"doc_type": "quy_trinh", "access_level": "internal"},
                "quy trình": {"doc_type": "quy_trinh", "access_level": "internal"},
                "nhãn hiệu - shtt": {"doc_type": "nhan_hieu", "access_level": "internal"},
                "nhãn hiệu": {"doc_type": "nhan_hieu", "access_level": "internal"},
                "hồ sơ nhân sự": {"doc_type": "ho_so_ns", "access_level": "internal"},
                "hồ sơ nộp cơ quan": {"doc_type": "filing", "access_level": "internal"},
                "tài liệu nội bộ": {"doc_type": "other", "access_level": "internal"},
                "nội bộ": {"doc_type": "other", "access_level": "internal"},
            },
            # Thư mục cấp 1 chứa hồ sơ khách hàng
            "client_roots": ["hồ sơ khách hàng", "khach hang", "khách hàng"],
            # Thư mục con trong hồ sơ khách → loại giấy tờ.
            # 'cong_no' là loại HẠN CHẾ: chặn ở CSDL (RLS), chỉ người được admin
            # cấp quyền xem tài chính mới tra cứu ra và bot mới dám nhắc tới.
            "client_subcategories": {
                "thông tin khách hàng": "ho_so_kh",
                "tổng hợp thông tin khách hàng": "ho_so_kh",
                "dự án": "ho_so_kh",
                "dự án - vụ việc": "ho_so_kh",
                "vụ việc": "ho_so_kh",
                "hợp đồng": "contract",
                "thư tư vấn": "advisory",
                "hồ sơ nộp cơ quan": "filing",
                "bản án": "ban_an",
                "công nợ": "cong_no",
                "công nợ - tài chính": "cong_no",
                "tài chính": "cong_no",
            },
        },
        ensure_ascii=False,
        indent=2,
    ),
}

# Khoá được phép sửa qua API (chặn ghi khoá lạ)
EDITABLE_KEYS = set(DEFAULTS.keys())

# Model generation đọc nhiều tham số trong cùng một request. Trước đây mỗi lần
# `get_int()` lại mở một kết nối và SELECT riêng. Cache rất ngắn giữ cấu hình
# nhất quán trong một lượt chat; set/reset chủ động xoá cache nên thay đổi từ UI
# vẫn có hiệu lực ngay, không phải đợi TTL.
try:
    _CACHE_TTL = max(0.0, float(os.getenv("SETTINGS_CACHE_SECONDS", "2")))
except ValueError:
    _CACHE_TTL = 2.0
_CACHE_LOCK = threading.Lock()
_CACHE_VALUE = None
_CACHE_AT = 0.0


def invalidate_cache():
    global _CACHE_VALUE, _CACHE_AT
    with _CACHE_LOCK:
        _CACHE_VALUE = None
        _CACHE_AT = 0.0


def get(key, default=None):
    """Đọc một cài đặt. Ưu tiên CSDL, không có thì lấy DEFAULTS."""
    return get_all().get(key, default)


def get_all():
    """Toàn bộ cài đặt hiện hành = DEFAULTS bị ghi đè bởi bản trong CSDL."""
    global _CACHE_VALUE, _CACHE_AT
    now = time.monotonic()
    with _CACHE_LOCK:
        if (_CACHE_VALUE is not None and _CACHE_TTL > 0
                and now - _CACHE_AT < _CACHE_TTL):
            return dict(_CACHE_VALUE)
    out = dict(DEFAULTS)
    try:
        with db.session(role="internal", admin=True) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT key, value FROM app_settings")
                for k, v in cur.fetchall():
                    out[k] = v
    except Exception:
        pass
    with _CACHE_LOCK:
        _CACHE_VALUE = dict(out)
        _CACHE_AT = time.monotonic()
    return dict(out)


def get_json(key):
    raw = get(key)
    try:
        return json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {}


def get_float(key, fallback):
    try:
        return float(get(key))
    except (TypeError, ValueError):
        return fallback


def get_int(key, fallback):
    try:
        return int(float(get(key)))
    except (TypeError, ValueError):
        return fallback


def get_prompt(channel):
    """Phong cách tư vấn theo kênh: public | internal | portal."""
    return get(f"prompt_{channel}") or DEFAULTS.get(f"prompt_{channel}", "")


def set(key, value, user_id=None):  # noqa: A001 - đặt tên theo nghiệp vụ
    """Ghi một cài đặt. Kiểm quyền admin ở tầng API trước khi gọi."""
    if key not in EDITABLE_KEYS:
        raise ValueError(f"Khoá cài đặt không hợp lệ: {key}")
    if key == "drive_map":
        json.loads(value)  # sai JSON thì báo lỗi ngay, đừng để hỏng lúc đồng bộ Drive
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO app_settings (key, value, updated_by, updated_at)
                   VALUES (%s,%s,%s,now())
                   ON CONFLICT (key) DO UPDATE
                     SET value=EXCLUDED.value, updated_by=EXCLUDED.updated_by,
                         updated_at=now()""",
                (key, value, user_id),
            )
        db.audit(conn, user_id, "update_setting", "app_settings", None, {"key": key})
    invalidate_cache()
    return True


def reset(key, user_id=None):
    """Xoá bản trong CSDL → quay về giá trị mặc định trong mã nguồn."""
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM app_settings WHERE key=%s", (key,))
        db.audit(conn, user_id, "reset_setting", "app_settings", None, {"key": key})
    invalidate_cache()
    return DEFAULTS.get(key)


def set_system(key, value):
    """Ghi một giá trị hệ thống, KHÔNG qua kiểm tra EDITABLE_KEYS.

    Dùng cho các tiến trình nền tự ghi trạng thái của chính nó (vd auto_learn.py
    ghi 'drive_sync_status' sau mỗi lần quét) — khác với set(), vốn dành cho
    admin sửa tay qua API và phải nằm trong danh sách khoá được phép sửa.
    """
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO app_settings (key, value, updated_at)
                   VALUES (%s,%s,now())
                   ON CONFLICT (key) DO UPDATE
                     SET value=EXCLUDED.value, updated_at=now()""",
                (key, value),
            )
    invalidate_cache()
