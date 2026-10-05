# -*- coding: utf-8 -*-
"""Thư viện chung cho bộ chạy kiểm thử trên máy chủ (gọi thẳng 127.0.0.1:8000).
Chạy bằng .venv của backend, cwd = ~/hds-ai-full/hds-ai (để app.auth đọc .env)."""
import json, os, re, sys, time, random, string, unicodedata
import requests

BASE = os.environ.get("KT_BASE", "http://127.0.0.1:8000")
KT_DIR = os.environ.get("KT_DIR", "/tmp/kt")
IN = os.path.join(KT_DIR, "in")
STATE_F = os.path.join(KT_DIR, "state.json")
KQ_F = os.path.join(KT_DIR, "ket_qua.json")
LOG_F = os.path.join(KT_DIR, "run.log")
LLM_TIMEOUT = 420

# ---------------------------------------------------------------- trạng thái
def load_state():
    try:
        return json.load(open(STATE_F, encoding="utf-8"))
    except Exception:
        return {}


def save_state(st):
    tmp = STATE_F + ".tmp"
    json.dump(st, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, STATE_F)
    os.chmod(STATE_F, 0o600)


KQ = []


def load_kq():
    global KQ
    try:
        KQ = json.load(open(KQ_F, encoding="utf-8"))
    except Exception:
        KQ = []
    return KQ


def save_kq():
    tmp = KQ_F + ".tmp"
    json.dump(KQ, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, KQ_F)


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG_F, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def ghi(ma, ket_qua, thuc_te, giay=None, chi_tiet=None):
    """ket_qua: ĐẠT | KHÔNG ĐẠT | CHẶN | BỎ QUA"""
    if CHI and ma not in CHI:
        return
    thuc_te = (thuc_te or "")[:1500]
    KQ[:] = [k for k in KQ if k["ma"] != ma]
    KQ.append({"ma": ma, "ket_qua": ket_qua, "thuc_te": thuc_te,
               "giay": round(giay, 1) if giay else None, "chi_tiet": chi_tiet,
               "luc": time.strftime("%Y-%m-%d %H:%M:%S")})
    save_kq()
    log(f"{ma}: {ket_qua} — {thuc_te[:160]}")


CHI = {x.strip() for x in os.environ.get("KT_CHI", "").split(",") if x.strip()}


def ca(ma):
    """decorator: bắt mọi lỗi → CHẶN. Đặt KT_CHI=mã,mã để chỉ chạy các ca liệt kê (chạy lại chọn lọc)."""
    def deco(fn):
        def wrap(*a, **k):
            if CHI and ma not in CHI:
                return None
            t = time.time()
            try:
                return fn(*a, **k)
            except Exception as e:  # noqa: BLE001
                ghi(ma, "CHẶN", f"Lỗi khi chạy: {type(e).__name__}: {str(e)[:300]}", time.time() - t)
        wrap.__name__ = fn.__name__
        return wrap
    return deco


# ---------------------------------------------------------------- HTTP
class User:
    """Một 'người dùng ảo': token + IP giả riêng (van đăng nhập/công khai đếm theo IP)."""
    def __init__(self, ten, token=None, ip=None, api_key=None):
        self.ten, self.token, self.api_key = ten, token, api_key
        self.ip = ip or f"10.77.{random.randint(1, 250)}.{random.randint(1, 250)}"
        self.s = requests.Session()

    def h(self, extra=None):
        h = {"X-Forwarded-For": self.ip}
        if self.api_key:
            h["X-API-Key"] = self.api_key
        elif self.token:
            h["Authorization"] = f"Bearer {self.token}"
        if extra:
            h.update(extra)
        return h

    def req(self, method, path, timeout=120, **kw):
        kw.setdefault("timeout", timeout)
        return self.s.request(method, BASE + path, headers=self.h(kw.pop("headers", None)), **kw)

    def get(self, path, **kw):
        return self.req("GET", path, **kw)

    def post(self, path, **kw):
        return self.req("POST", path, **kw)

    def patch(self, path, **kw):
        return self.req("PATCH", path, **kw)

    def put(self, path, **kw):
        return self.req("PUT", path, **kw)

    def delete(self, path, **kw):
        return self.req("DELETE", path, **kw)

    def j(self, method, path, **kw):
        r = self.req(method, path, **kw)
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, {"_text": r.text[:500]}

    # --- chat
    def chat(self, question, conv=None, channel="internal", **extra):
        body = {"question": question, "conversation_id": conv}
        body.update(extra)
        path = {"internal": "/chat/internal", "portal": "/chat/portal", "public": "/chat/public"}[channel]
        t = time.time()
        r = self.req("POST", path, json=body, timeout=LLM_TIMEOUT)
        dt = time.time() - t
        try:
            d = r.json()
        except Exception:
            d = {"_text": r.text[:500]}
        d["_status"], d["_giay"] = r.status_code, round(dt, 1)
        return d

    def upload_temp(self, conv, path):
        with open(path, "rb") as f:
            r = self.req("POST", "/upload/extract", data={"conversation_id": conv},
                         files={"file": (os.path.basename(path), f)}, timeout=600)
        return r.status_code, (r.json() if r.headers.get("content-type", "").startswith("application/json") else {"_text": r.text[:300]})

    def new_conv(self, kind="chat"):
        s, d = self.j("POST", f"/conversations?kind={kind}")
        return d.get("conversation_id") if s == 200 else None

    def me(self):
        return self.j("GET", "/auth/me")[1]


def mint(uid, role):
    """JWT cho tài khoản có sẵn — ký bằng khoá của chính máy chủ (không in ra)."""
    sys.path.insert(0, os.getcwd())
    from app import auth
    return auth.make_token(uid, role)


def login(email, password, ip=None):
    u = User(email, ip=ip)
    r = u.post("/auth/login", json={"email": email, "password": password})
    if r.status_code == 200:
        u.token = r.json()["access_token"]
        return u, r
    return None, r


def detail(resp):
    try:
        return resp.json().get("detail")
    except Exception:
        return resp.text[:200]


def mat_khau_moi():
    return "Kt" + "".join(random.choices(string.ascii_letters + string.digits, k=10)) + "9"


# ---------------------------------------------------------------- chấm
def fold(s):
    s = unicodedata.normalize("NFD", (s or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn").replace("đ", "d")


def has(text, *subs):
    f = fold(text)
    return all(fold(x) in f for x in subs)


def has_any(text, *subs):
    f = fold(text)
    return any(fold(x) in f for x in subs)


def cites(text):
    return len(re.findall(r"\[Nguồn \d+\]", text or ""))


def dieu(text, n):
    return re.search(rf"(?i)\bđiều\s+{n}\b", text or "") is not None


def dieu_list(text):
    return sorted({int(x) for x in re.findall(r"(?i)\bđiều\s+(\d{1,4})\b", text or "")})


def tom(d, n=220):
    a = (d.get("answer") or d.get("_text") or "")
    return f"[{d.get('_status')} {d.get('grounding_status')}/{d.get('answer_mode')} {d.get('_giay')}s] " + re.sub(r"\s+", " ", a)[:n]


def src_titles(d):
    return [s.get("title") or s.get("attachment_name") or "" for s in (d.get("sources") or [])]


def src_ids(d):
    return [s.get("document_id") for s in (d.get("sources") or []) if s.get("document_id")]


def src_clients(d):
    return sorted({(s.get("client_name") or "") for s in (d.get("sources") or []) if s.get("client_name")})


def doi(fn, moi_giay=5, toi_da=180, msg=""):
    """Chờ fn() trả True."""
    t = time.time()
    while time.time() - t < toi_da:
        try:
            if fn():
                return True
        except Exception:
            pass
        time.sleep(moi_giay)
    log(f"hết {toi_da}s chờ: {msg}")
    return False
