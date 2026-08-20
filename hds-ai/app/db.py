"""
db.py — Kết nối CSDL và thiết lập ngữ cảnh phân quyền.

Ánh xạ vai -> mức truy cập (app.role):
  admin, ban_qt, truong_bph, chuyen_vien, tro_ly  -> 'internal'
  client_free, client_plus, client_pro             -> 'client'
  (website / chưa đăng nhập)                        -> 'public'

Với mức 'internal', truyền thêm:
  dept_ids : danh sách phòng user thuộc (để lọc hồ sơ khách theo phòng)
  is_banqt : True nếu admin/ban_qt (thấy MỌI phòng)

Cô lập dữ liệu khách hàng luôn khóa ở CSDL (RLS), không phó mặc cho code.
"""
import os
import threading
from contextlib import contextmanager

import psycopg
from dotenv import load_dotenv

try:
    from psycopg_pool import ConnectionPool
except ImportError:  # Triển khai cũ vẫn chạy; requirements mới sẽ bật pool.
    ConnectionPool = None

load_dotenv()

ROLE_TO_DBLEVEL = {
    "admin": "internal", "ban_qt": "internal", "truong_bph": "internal",
    "chuyen_vien": "internal", "tro_ly": "internal",
    "client_free": "client", "client_plus": "client", "client_pro": "client",
    "public": "public",
}
# Cấp thấy mọi phòng (không bị giới hạn bộ phận)
SEE_ALL_DEPTS = {"admin", "ban_qt"}

# Một câu chat trước đây mở nhiều kết nối TCP/PostgreSQL nối tiếp (xác thực,
# settings, retrieval, history, ghi message...). Pool tách riêng tài khoản app
# và tài khoản chủ để không bao giờ cho một kết nối bypass-RLS lọt sang truy vấn
# người dùng. min_size=0 giúp các lệnh CLI ngắn không giữ tiến trình sống.
_POOLS = {}
_POOL_LOCK = threading.Lock()


def _env_int(name: str, fallback: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(fallback))))
    except (TypeError, ValueError):
        return fallback


def _pool(as_app: bool):
    if ConnectionPool is None:
        return None
    key = "app" if as_app else "admin"
    existing = _POOLS.get(key)
    if existing is not None:
        return existing
    with _POOL_LOCK:
        existing = _POOLS.get(key)
        if existing is None:
            maximum = _env_int("DB_POOL_MAX" if as_app else "DB_ADMIN_POOL_MAX",
                               12 if as_app else 4)
            existing = ConnectionPool(
                conninfo=_conn_str(as_app=as_app), min_size=0, max_size=maximum,
                timeout=_env_int("DB_POOL_TIMEOUT", 10), max_idle=300,
                name=f"hds-{key}", open=True,
            )
            _POOLS[key] = existing
    return existing


@contextmanager
def _connection(as_app: bool):
    pool = _pool(as_app)
    if pool is None:
        with psycopg.connect(_conn_str(as_app=as_app)) as conn:
            yield conn
        return
    with pool.connection() as conn:
        yield conn


def db_level(role: str) -> str:
    return ROLE_TO_DBLEVEL.get(role, "public")


def _conn_str(as_app: bool = True) -> str:
    # Tên đăng nhập có mặc định được (không phải bí mật), mật khẩu thì không:
    # mật khẩu mặc định nằm trong mã nguồn công khai là mật khẩu ai cũng biết.
    if as_app:
        user = os.getenv("APP_DB_USER", "hds_app")
        pwd = os.getenv("APP_DB_PASSWORD", "")
        var = "APP_DB_PASSWORD"
    else:
        user = os.getenv("DB_USER", "hds")
        pwd = os.getenv("DB_PASSWORD", "")
        var = "DB_PASSWORD"

    if not pwd:
        raise RuntimeError(
            f"Chưa đặt {var} cho tài khoản CSDL '{user}'. "
            "Tạo .env từ .env.example rồi điền mật khẩu."
        )

    return (f"host={os.getenv('DB_HOST','localhost')} port={os.getenv('DB_PORT','5432')} "
            f"dbname={os.getenv('DB_NAME','hdsai')} user={user} password={pwd}")


@contextmanager
def session(role: str = "public", client_id: int | None = None,
            dept_ids: list[int] | None = None, is_banqt: bool = False,
            can_finance: bool = False, admin: bool = False):
    """Mở phiên CSDL đã set quyền.

    role       : 1 trong 8 vai, hoặc 'internal'/'client'/'public'.
    client_id  : bắt buộc khi mức 'client'.
    dept_ids   : phòng user thuộc (mức 'internal', để lọc hồ sơ khách theo phòng).
    is_banqt   : True nếu thấy mọi phòng.
    can_finance: True nếu được xem tài liệu công nợ/tài chính (admin cấp từng người).
                 Mặc định False — không truyền là không thấy, đúng hướng an toàn.
    admin      : True -> kết nối tài khoản chủ 'hds', BỎ QUA RLS (chỉ ingest/migration).
    """
    if role in ("internal", "client", "public"):
        level = role
    else:
        level = db_level(role)
        if role in SEE_ALL_DEPTS:
            is_banqt = True
    if level == "client" and client_id is None:
        raise ValueError("Mức 'client' bắt buộc phải có client_id")

    dept_csv = ",".join(str(d) for d in dept_ids) if dept_ids else ""
    with _connection(as_app=not admin) as conn:
        try:
            # Luôn ghi đè TOÀN BỘ context trên mỗi lần mượn connection. Không
            # được dựa vào giá trị của request trước còn lưu trong pool.
            with conn.cursor() as cur:
                cur.execute("SELECT set_config('app.role', %s, false)", (level,))
                cur.execute("SELECT set_config('app.client_id', %s, false)",
                            (str(client_id) if client_id is not None else "",))
                cur.execute("SELECT set_config('app.dept_ids', %s, false)", (dept_csv,))
                cur.execute("SELECT set_config('app.is_banqt', %s, false)",
                            ("yes" if is_banqt else "no",))
                cur.execute("SELECT set_config('app.can_finance', %s, false)",
                            ("yes" if can_finance else "no",))
            yield conn
            conn.commit()
        except BaseException:
            try:
                conn.rollback()
            except Exception:
                pass
            raise


def audit(conn, user_id, action, entity=None, entity_id=None, detail=None):
    import json
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO audit_log (user_id, action, entity, entity_id, detail) VALUES (%s,%s,%s,%s,%s)",
            (user_id, action, entity, entity_id, json.dumps(detail, ensure_ascii=False) if detail else None))


def get_user_departments(conn, user_id):
    """Trả về (dept_ids, is_head_of) cho một user."""
    with conn.cursor() as cur:
        cur.execute("SELECT department_id, is_head FROM user_departments WHERE user_id=%s", (user_id,))
        rows = cur.fetchall()
    return [r[0] for r in rows], [r[0] for r in rows if r[1]]


def check_connection() -> bool:
    try:
        with psycopg.connect(_conn_str(as_app=False), connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                return cur.fetchone()[0] == 1
    except Exception:
        return False
