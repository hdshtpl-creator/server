"""
settings.py — Cài đặt hệ thống lưu trong CSDL, admin sửa được trên web.

Trước đây phong cách tư vấn (system prompt) và bản đồ thư mục Drive nằm cứng
trong mã nguồn → muốn đổi phải sửa code rồi khởi động lại. Nay lưu ở bảng
`app_settings`: admin đổi trên giao diện, có hiệu lực ngay câu hỏi tiếp theo.

Đọc: get(key) / get_json(key) / get_prompt(channel)
Ghi: set(key, value, user_id)  — chỉ admin, kiểm ở tầng API.
"""
import json

from app import db

# ---------------------------------------------------------------
# Giá trị mặc định. Chỉ dùng khi CSDL chưa có bản ghi tương ứng —
# nghĩa là admin sửa trên web thì bản DB luôn thắng.
# ---------------------------------------------------------------
DEFAULTS = {
    # Phong cách tư vấn cho 3 kênh chat
    "prompt_public": (
        "Bạn là trợ lý của Công ty Luật HDS, trả lời khách trên website. "
        "Chỉ dựa vào TÀI LIỆU THAM KHẢO bên dưới. Không đủ căn cứ thì nói rõ. "
        "Trả lời khái quát, luôn kết thúc bằng gợi ý liên hệ luật sư HDS. "
        "Không bịa điều luật, không nêu số hiệu văn bản nếu không có trong tài liệu."
    ),
    "prompt_internal": (
        "Bạn là trợ lý pháp lý nội bộ của HDS, phục vụ luật sư và chuyên viên. "
        "Chỉ dựa vào TÀI LIỆU THAM KHẢO. Trả lời chuyên sâu, trích tới Điều/Khoản khi có. "
        "Nêu rõ điểm nào chắc chắn, điểm nào cần luật sư kiểm chứng. "
        "Kết quả là bản nháp; luật sư rà soát và chịu trách nhiệm cuối cùng."
    ),
    "prompt_portal": (
        "Bạn là trợ lý của HDS phục vụ khách hàng đã ký hợp đồng. "
        "Chỉ dựa vào TÀI LIỆU THAM KHẢO — chỉ thuộc về khách đang đăng nhập. "
        "Không nhắc tới bất kỳ khách hàng nào khác. Không đủ căn cứ thì đề nghị liên hệ luật sư."
    ),
    # Tham số sinh câu trả lời
    "llm_temperature": "0.2",
    "retrieval_top_k": "8",
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
            # Thư mục con trong hồ sơ khách → loại giấy tờ
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
            },
        },
        ensure_ascii=False,
        indent=2,
    ),
}

# Khoá được phép sửa qua API (chặn ghi khoá lạ)
EDITABLE_KEYS = set(DEFAULTS.keys())


def get(key, default=None):
    """Đọc một cài đặt. Ưu tiên CSDL, không có thì lấy DEFAULTS."""
    try:
        with db.session(role="internal", admin=True) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT value FROM app_settings WHERE key=%s", (key,))
                row = cur.fetchone()
        if row:
            return row[0]
    except Exception:
        # CSDL chưa nạp bảng app_settings (lần đầu chạy) → dùng mặc định
        pass
    return DEFAULTS.get(key, default)


def get_all():
    """Toàn bộ cài đặt hiện hành = DEFAULTS bị ghi đè bởi bản trong CSDL."""
    out = dict(DEFAULTS)
    try:
        with db.session(role="internal", admin=True) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT key, value FROM app_settings")
                for k, v in cur.fetchall():
                    out[k] = v
    except Exception:
        pass
    return out


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
    return True


def reset(key, user_id=None):
    """Xoá bản trong CSDL → quay về giá trị mặc định trong mã nguồn."""
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM app_settings WHERE key=%s", (key,))
        db.audit(conn, user_id, "reset_setting", "app_settings", None, {"key": key})
    return DEFAULTS.get(key)
