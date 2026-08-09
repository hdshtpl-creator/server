"""
auth.py — Đăng nhập thật: mật khẩu mã hóa (bcrypt) + token JWT.
Thay cho cách nhận diện tạm bằng header X-User-Id.

Luồng:
  1. POST /auth/login {email, password} -> trả về access_token (JWT)
  2. Client gửi kèm mọi request: header Authorization: Bearer <token>
  3. get_current_user() giải mã token -> biết user là ai (không giả được)
"""
import os
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


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


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
