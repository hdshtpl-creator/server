"""
auth.py — Đăng nhập thật: mật khẩu mã hóa (bcrypt) + token JWT.
Thay cho cách nhận diện tạm bằng header X-User-Id.

Luồng:
  1. POST /auth/login {email, password} -> trả về access_token (JWT)
  2. Client gửi kèm mọi request: header Authorization: Bearer <token>
  3. get_current_user() giải mã token -> biết user là ai (không giả được)
"""
import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from dotenv import load_dotenv

load_dotenv()

JWT_ALGO = "HS256"
TOKEN_HOURS = int(os.getenv("TOKEN_HOURS", "12"))

# Chuỗi mẫu trong .env.example — có mặt nghĩa là chưa ai đổi.
_PLACEHOLDER_SECRETS = {
    "doi_chuoi_bi_mat_nay_khi_chay_that",
    "doi_chuoi_bi_mat_ngau_nhien_dai_khi_chay_that",
    "change_me",
}
_MIN_SECRET_LEN = 32


def _get_jwt_secret() -> str:
    """Lấy khoá ký JWT, từ chối chạy nếu khoá chưa được đặt tử tế.

    Trước đây hàm này có giá trị dự phòng ngay trong mã nguồn. Khi mã nguồn lên
    GitHub, bất kỳ ai cũng có thể tự ký token vai admin nếu máy chủ quên đặt
    JWT_SECRET. Nay thiếu khoá thì hỏng ngay lúc đăng nhập, không âm thầm chạy
    bằng một khoá ai cũng biết.

    Đọc tại thời điểm gọi (không phải lúc import) để các script chỉ cần
    hash_password vẫn dùng được module này.
    """
    secret = os.getenv("JWT_SECRET", "")
    if not secret:
        raise RuntimeError(
            "Chưa đặt JWT_SECRET. Sinh khoá bằng: python -c "
            "\"import secrets; print(secrets.token_urlsafe(48))\" "
            "rồi ghi vào .env."
        )
    if secret in _PLACEHOLDER_SECRETS:
        raise RuntimeError(
            "JWT_SECRET vẫn đang là chuỗi mẫu trong .env.example. "
            "Hãy thay bằng một chuỗi ngẫu nhiên riêng của máy chủ."
        )
    if len(secret) < _MIN_SECRET_LEN:
        raise RuntimeError(
            f"JWT_SECRET quá ngắn ({len(secret)} ký tự), cần tối thiểu "
            f"{_MIN_SECRET_LEN} ký tự để chống dò khoá."
        )
    return secret


# ---------- Mật khẩu: sinh tạm + chính sách (22/09/2026, đưa vào vận hành) ----------
# Trước đây mọi tài khoản mới đều nhận cùng một mật khẩu "hds12345" ghi thẳng
# trong mã nguồn và trong sổ tay nhân viên — ai cũng biết, tài khoản vừa tạo
# mà người dùng chưa kịp đổi là cửa mở. Nay mỗi tài khoản nhận một mật khẩu
# tạm ngẫu nhiên, hiện đúng MỘT LẦN cho quản trị, và bị bắt đổi ngay lần đăng
# nhập đầu tiên (cột users.must_change_password).
MIN_PASSWORD_LEN = 8
TEMP_PASSWORD_LEN = 10
# Bỏ các ký tự dễ đọc nhầm khi chép tay / đọc qua điện thoại: 0/O, 1/l/I.
_TEMP_PW_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789"
# Mật khẩu từng ghi trong mã / tài liệu — cấm đặt lại, và app/ra_soat_tai_khoan
# dùng danh sách này để tìm tài khoản chưa đổi.
MAT_KHAU_MAC_DINH_CU = ("hds12345", "admin123", "demo123")


def new_temp_password(n: int = TEMP_PASSWORD_LEN) -> str:
    """Mật khẩu tạm ngẫu nhiên, luôn có cả chữ lẫn số để qua được chính sách."""
    while True:
        pw = "".join(secrets.choice(_TEMP_PW_ALPHABET) for _ in range(n))
        if any(c.isdigit() for c in pw) and any(c.isalpha() for c in pw):
            return pw


def kiem_tra_mat_khau_moi(pw: str, *, cu: str | None = None,
                          email: str | None = None) -> str | None:
    """Trả về câu báo lỗi (tiếng Việt) nếu mật khẩu mới không đạt, None nếu đạt.

    Dùng chung cho đổi mật khẩu, tạo tài khoản và đặt lại mật khẩu — một
    chính sách, một chỗ; giao diện chỉ lặp lại câu này chứ không tự kiểm."""
    pw = pw or ""
    if len(pw) < MIN_PASSWORD_LEN:
        return f"Mật khẩu tối thiểu {MIN_PASSWORD_LEN} ký tự"
    if not any(c.isdigit() for c in pw) or not any(c.isalpha() for c in pw):
        return "Mật khẩu phải có cả chữ và số"
    if pw.lower() in MAT_KHAU_MAC_DINH_CU:
        return "Mật khẩu này từng là mật khẩu mặc định, không được dùng lại"
    if cu is not None and pw == cu:
        return "Mật khẩu mới phải khác mật khẩu hiện tại"
    if email:
        local = email.split("@")[0].strip().lower()
        if len(local) >= 4 and local in pw.lower():
            return "Mật khẩu không được chứa phần tên trong email"
    return None


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


API_KEY_PREFIX = "hds_"


def new_api_key() -> tuple[str, str]:
    """Sinh khoá API cho khách tích hợp. Trả về (khoá thật, bản băm để lưu).

    Khoá thật chỉ hiện MỘT LẦN lúc cấp; CSDL chỉ giữ bản băm. Máy chủ bị đọc
    CSDL thì kẻ đọc vẫn không gọi được API thay khách.

    Dùng SHA-256 chứ không bcrypt vì phải tra cứu được theo khoá (bcrypt có
    muối ngẫu nhiên nên không tra được). An toàn ở đây đến từ việc khoá dài và
    ngẫu nhiên thật (256 bit), không phải từ độ chậm của hàm băm.
    """
    raw = API_KEY_PREFIX + secrets.token_urlsafe(32)
    return raw, hash_api_key(raw)


def hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def make_token(user_id: int, role: str) -> str:
    payload = {
        "sub": str(user_id),
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=TOKEN_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, _get_jwt_secret(), algorithm=JWT_ALGO)


def decode_token(token: str) -> dict | None:
    # Lỗi cấu hình khoá (RuntimeError) cố ý KHÔNG bị nuốt ở đây: nếu nuốt, mọi
    # token đều thành "không hợp lệ" và người vận hành sẽ đi tìm nhầm chỗ.
    try:
        return jwt.decode(token, _get_jwt_secret(), algorithms=[JWT_ALGO])
    except jwt.PyJWTError:
        return None
