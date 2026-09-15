"""
models.py — Gọi AI: tạo vector và sinh câu trả lời.

TẠO VECTOR luôn chạy bằng bge-m3 trên máy chủ (Ollama) và KHÔNG BAO GIỜ đi ra
ngoài: mọi đoạn đã lưu trong kho đều theo model đó, đổi là hỏng toàn bộ tra cứu.

SINH CÂU TRẢ LỜI có ba đường, chọn bằng chính tên model (xem provider_of):
Ollama trên máy chủ (mặc định), API Anthropic, hoặc endpoint tương thích
OpenAI (Qwen/DashScope, DeepSeek, OpenRouter…). Không cần PyTorch, không lỗi
CUDA trên card Blackwell.
"""
import json
import os
import re
import time
import unicodedata

import requests
from dotenv import load_dotenv

load_dotenv()

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen3:14b")
EMBED_MODEL = os.getenv("EMBED_MODEL", "bge-m3")
EMBED_DIM = int(os.getenv("EMBED_DIM", "1024"))

# Giữ model nằm sẵn trong bộ nhớ bao lâu sau lần dùng cuối. Mặc định của Ollama
# là 5 phút: hỏi cách nhau 6 phút là phải nạp lại model từ ổ cứng, mất hàng chục
# giây trước khi sinh được chữ đầu tiên. Hệ thống chỉ có 2 model (sinh câu trả
# lời + tạo vector) nên giữ thường trú là đáng.
KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "30m")

# Model có chế độ "suy nghĩ": trước khi trả lời chúng sinh một đoạn lập luận
# trong <think>…</think>. Đoạn đó bị cắt bỏ khi hiển thị — nghĩa là máy chủ tốn
# thời gian sinh ra hàng trăm token rồi vứt đi. Với máy chạy CPU thì riêng phần
# này đã đủ làm quá hạn 100 giây của Cloudflare.
THINKING_MODELS = ("qwen3", "deepseek-r1", "magistral", "reasoning", "gpt-oss", "qwq")

# Số token bắt model sinh ra khi đo tốc độ. Đo trên vài token thì chi phí cố
# định (dựng phiên, lấy mẫu token đầu) lấn át và ra tốc độ sai hẳn.
BENCH_TOKENS = 64

# ================= NHÀ CUNG CẤP MODEL =================
# Tên model MANG THEO nhà cung cấp, nhờ vậy mọi chỗ đang truyền một chuỗi tên
# model (cài đặt của admin, bộ chọn ở ô chat, cột model_used trong messages)
# không phải đổi kiểu dữ liệu:
#     'qwen3:14b'            → Ollama trên máy chủ (mặc định, không tiền tố)
#     'claude:claude-sonnet-5' → API Anthropic
#     'api:qwen-plus'        → endpoint tương thích OpenAI (DashScope/Qwen,
#                              DeepSeek, OpenRouter, vLLM tự dựng…)
# Tên trần bắt đầu bằng 'claude-' cũng được hiểu là Anthropic, để admin gõ
# thẳng 'claude-sonnet-5' vào ô cài đặt mà không cần nhớ tiền tố.
P_LOCAL, P_CLAUDE, P_COMPAT = "local", "claude", "compat"
PREFIX_CLAUDE, PREFIX_COMPAT = "claude:", "api:"

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
# Danh sách hiện trong bộ chọn model. Không phải mọi model Anthropic — chỉ mấy
# cái đã cân nhắc giá/chất lượng cho việc của HDS (xem bảng giá bên dưới).
CLAUDE_MODELS = [m.strip() for m in os.getenv(
    "CLAUDE_MODELS", "claude-sonnet-5,claude-opus-5,claude-haiku-4-5").split(",") if m.strip()]

# Endpoint tương thích OpenAI. Một adapter dùng chung cho cả nhóm vì họ nói
# CÙNG một giao thức (POST /chat/completions): Qwen trên DashScope
# (https://dashscope.aliyuncs.com/compatible-mode/v1), DeepSeek, OpenRouter,
# Groq, hay chính máy vLLM tự dựng sau này.
COMPAT_BASE_URL = (os.getenv("COMPAT_BASE_URL", "")
                   or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
COMPAT_API_KEY = os.getenv("COMPAT_API_KEY", "") or os.getenv("OPENAI_API_KEY", "")
COMPAT_MODELS = [m.strip() for m in os.getenv(
    "COMPAT_MODELS", os.getenv("OPENAI_MODEL", "")).split(",") if m.strip()]

# Giá USD trên 1 TRIỆU token (vào, ra) — chỉ để ƯỚC chi phí mỗi lượt rồi ghi
# vào stats/log. Giá nhà cung cấp đổi thì sửa ở đây; sai số ở đây không ảnh
# hưởng câu trả lời, chỉ ảnh hưởng con số báo cáo.
CLAUDE_PRICES = {
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-fable-5": (10.0, 50.0),
}

# Cửa sổ ngữ cảnh (token) của model cloud — dùng để quy ra trần ký tự cho
# phần tài liệu, y như num_ctx làm với Ollama. Không có tên trong bảng thì
# lấy mức dè dặt nhất.
CLOUD_CTX_TOKENS = {
    "claude-haiku-4-5": 200_000,
    "claude-sonnet-5": 1_000_000,
    "claude-opus-5": 1_000_000,
    "claude-opus-4-8": 1_000_000,
    "claude-fable-5": 1_000_000,
}
CLOUD_CTX_DEFAULT = 128_000


def provider_of(name: str) -> str:
    """Nhà cung cấp của một tên model. Không rõ thì là local — mặc định an
    toàn: chạy trên máy nhà, không gửi gì ra ngoài, không tốn tiền."""
    n = (name or "").strip().lower()
    if n.startswith(PREFIX_CLAUDE) or n.startswith("claude-"):
        return P_CLAUDE
    if n.startswith(PREFIX_COMPAT):
        return P_COMPAT
    return P_LOCAL


def is_cloud(name: str) -> bool:
    return provider_of(name) != P_LOCAL


def bare_model(name: str) -> str:
    """Bỏ tiền tố nhà cung cấp → tên model để gửi lên API."""
    n = (name or "").strip()
    for pre in (PREFIX_CLAUDE, PREFIX_COMPAT):
        if n.lower().startswith(pre):
            return n[len(pre):].strip()
    return n


def cloud_models() -> list:
    """Model cloud DÙNG ĐƯỢC lúc này = đã cấu hình khoá API. Chưa có khoá thì
    không hiện trong bộ chọn — thà không thấy còn hơn chọn xong báo lỗi."""
    out = []
    if ANTHROPIC_API_KEY:
        out += [PREFIX_CLAUDE + m for m in CLAUDE_MODELS]
    if COMPAT_API_KEY and COMPAT_MODELS:
        out += [PREFIX_COMPAT + m for m in COMPAT_MODELS]
    return out


def cloud_context_tokens(name: str) -> int:
    return CLOUD_CTX_TOKENS.get(bare_model(name), CLOUD_CTX_DEFAULT)


def cloud_config() -> dict:
    """Tham số nhánh cloud, admin sửa trên web (app_settings). Import lười
    như effective_llm_model: models.py nạp rất sớm, trước cả khi CSDL sẵn."""
    cfg = {"enabled": False, "model": "claude:claude-sonnet-5",
           "channels": "internal", "effort": "medium", "max_tokens": 8000,
           "fallback_local": True, "scope": "law_only",
           "context_char_budget": 0}
    try:
        from app import settings
        g = settings.get_all()
        truthy = lambda v: str(v).strip().lower() not in {"0", "false", "no", ""}
        cfg["enabled"] = truthy(g.get("cloud_enabled", "false"))
        cfg["model"] = (g.get("cloud_model") or cfg["model"]).strip()
        cfg["channels"] = (g.get("cloud_channels") or cfg["channels"]).strip()
        cfg["effort"] = (g.get("cloud_effort") or cfg["effort"]).strip().lower()
        cfg["scope"] = (g.get("cloud_scope") or cfg["scope"]).strip().lower()
        cfg["fallback_local"] = truthy(g.get("cloud_fallback_local", "true"))
        cfg["max_tokens"] = settings.get_int("cloud_max_tokens", cfg["max_tokens"])
        cfg["context_char_budget"] = settings.get_int(
            "cloud_context_char_budget", cfg["context_char_budget"])
    except Exception:
        pass
    return cfg


def local_default_model() -> str:
    """Model LOCAL để lui về. KHÔNG lấy thẳng cài đặt llm_model: admin có thể
    đã đặt chính nó thành một model cloud, lúc ấy "lui về" lại quay ra ngoài."""
    try:
        from app import settings
        cur = (settings.get("llm_model") or "").strip()
        if cur and not is_cloud(cur):
            return cur
    except Exception:
        pass
    return LLM_MODEL


def model_soan_thao(model_choice: str | None) -> str:
    """Model cho các luồng SOẠN THẢO: điền mẫu, dựng bộ file .docx, phác nội
    dung hợp đồng.

    Những luồng này không đi qua rag.prepare nên không có chốt phạm vi ở đó —
    mà chúng lại luôn cầm dữ liệu định danh: CCCD, ngày sinh, lương, điều
    khoản hợp đồng của một người cụ thể. Vì vậy chỉ cho ra ngoài ở mức phạm vi
    rộng nhất, và mức đó admin phải chọn tay. Mọi trường hợp khác: chạy bằng
    model trên máy chủ, im lặng và an toàn.
    """
    if not is_cloud(model_choice or ""):
        return model_choice
    cfg = cloud_config()
    if cfg["enabled"] and cfg["scope"] == "all_but_finance" and cloud_models():
        return model_choice
    return local_default_model()


def cloud_enabled_for(channel: str) -> bool:
    """Kênh này có được phép gọi API không. Mặc định CHỈ kênh nội bộ: kênh
    public là cửa cho người ngoài gõ câu hỏi không giới hạn số lượt — mở cloud
    ở đó là mở luôn hoá đơn cho người lạ bơm."""
    cfg = cloud_config()
    if not cfg["enabled"] or not cloud_models():
        return False
    allow = {c.strip() for c in (cfg["channels"] or "").split(",") if c.strip()}
    return (channel or "internal") in allow


def is_thinking_model(name: str) -> bool:
    return any(k in (name or "").lower() for k in THINKING_MODELS)


def embed(texts, batch_size: int = 16, stats: dict | None = None):
    single = isinstance(texts, str)
    if single:
        texts = [texts]
    if not texts:
        return []
    out = []
    load_ns = total_ns = prompt_tokens = 0
    for i in range(0, len(texts), batch_size):
        r = requests.post(f"{OLLAMA_URL}/api/embed",
                          json={"model": EMBED_MODEL, "input": texts[i:i + batch_size],
                                "keep_alive": KEEP_ALIVE}, timeout=300)
        r.raise_for_status()
        data = r.json()
        vecs = data.get("embeddings")
        if not vecs:
            raise RuntimeError(f"Ollama không trả vector. Tải model: ollama pull {EMBED_MODEL}")
        out.extend(vecs)
        load_ns += data.get("load_duration") or 0
        total_ns += data.get("total_duration") or 0
        prompt_tokens += data.get("prompt_eval_count") or 0
    if out and len(out[0]) != EMBED_DIM:
        raise RuntimeError(f"Model trả {len(out[0])} chiều, cấu hình EMBED_DIM={EMBED_DIM}. "
                           f"Sửa .env và cột vector({EMBED_DIM}) trong schema.sql cho khớp.")
    if stats is not None:
        stats.update({
            "embed_model": EMBED_MODEL,
            "embed_load_ms": int(load_ns / 1_000_000),
            "embed_total_ms": int(total_ns / 1_000_000),
            "embed_tokens": prompt_tokens,
            "embed_batches": (len(texts) + batch_size - 1) // batch_size,
        })
    return out[0] if single else out


def effective_llm_model() -> str:
    """Model sinh câu trả lời đang dùng: ưu tiên admin chọn trên web (app_settings),
    ngược lại lấy LLM_MODEL trong .env. Đọc tại thời điểm gọi nên đổi là ăn ngay.

    Import settings kiểu lười để tránh vòng import lúc nạp module (models nạp rất
    sớm, trước cả khi CSDL sẵn sàng)."""
    try:
        from app import settings
        m = (settings.get("llm_model") or "").strip()
        if m:
            return m
    except Exception:
        pass
    return LLM_MODEL


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return s.replace("đ", "d").replace("Đ", "d").lower()


def _param_size(name: str) -> float:
    """Số tham số (tỉ) đọc từ tên model: 'qwen3:8b' → 8, 'qwen2.5:14b' → 14.
    Không đọc được thì coi là lớn để 'auto' không lỡ chọn model nặng."""
    m = re.search(r"(\d+(?:\.\d+)?)\s*b\b", name.lower())
    return float(m.group(1)) if m else 999.0


def generation_models(names, embed_model=None) -> list:
    """Danh sách model SINH câu trả lời (loại model tạo vector ra)."""
    embed_base = (embed_model or EMBED_MODEL).split(":")[0]
    return [n for n in names if n.split(":")[0] != embed_base]


# Dấu hiệu câu hỏi phức tạp → 'auto' mới dùng model mạnh (mặc định của admin).
_COMPLEX_WORDS = {
    "phan tich", "soan", "du thao", "so sanh", "danh gia", "lap luan",
    "chi tiet", "toan dien", "rui ro", "tu van", "du bao", "chien luoc",
    "giai thich", "lap dan y", "du thao hop dong",
}


def loaded_models() -> list:
    """Model ĐANG nằm sẵn trong bộ nhớ (Ollama /api/ps).

    Khác check_ollama() vốn liệt kê model đã CÀI trên đĩa. Phân biệt hai thứ này
    là mấu chốt của tốc độ: dùng model đã nạp sẵn thì bắt đầu trả lời ngay, còn
    đổi sang model khác phải đọc vài GB từ ổ cứng trước đã.
    """
    try:
        r = requests.get(f"{OLLAMA_URL}/api/ps", timeout=5)
        r.raise_for_status()
        return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        return []


def auto_pick_model(question: str, configured_model: str | None = None,
                    quality_required: bool = False) -> str:
    """'Tự động' — chọn model theo hai nguyên tắc, xếp theo thứ tự ưu tiên:

    1. ƯU TIÊN MODEL ĐANG NÓNG. Đổi model tốn một lần nạp lại từ ổ cứng (vài
       giây tới cả phút). Khoản đó gần như luôn lớn hơn phần tiết kiệm được nhờ
       model nhẹ hơn, nên hỏi xen kẽ câu dễ/câu khó mà cứ đổi qua đổi lại thì
       chậm hơn là không đổi gì cả.
    2. KHÔNG BAO GIỜ NẶNG HƠN MẶC ĐỊNH. Model nóng sẵn nhưng nặng hơn mức admin
       đặt (vì ai đó vừa chọn tay model lớn) thì bỏ qua — nếu không, một lựa
       chọn tay sẽ kéo dài ảnh hưởng sang mọi câu hỏi sau đó.

    Câu hỏi phức tạp luôn dùng đúng model admin đã đặt, chấp nhận nạp lại nếu cần.
    """
    configured = configured_model or effective_llm_model()
    # Model cloud KHÔNG đi qua bộ chọn theo cỡ. _param_size đọc số trong tên
    # ('claude-sonnet-5' → không khớp mẫu '<số>b' → 999) nên trần cỡ thành vô
    # hạn, và mọi model local đang nóng đều lọt — auto sẽ lặng lẽ hạ một lựa
    # chọn cloud xuống Qwen mà không ai biết. Cloud thì dùng đúng cloud.
    if is_cloud(configured):
        return configured
    # Các câu đếm/chào hỏi đã được fast-path trả trực tiếp trước khi tới đây.
    # Phần còn lại là tra cứu/phân tích tài liệu, nơi tự hạ 8B xuống 4B làm tăng
    # nguy cơ bỏ citation và hiểu sai điều khoản. Auto lúc này ưu tiên chất lượng
    # đã được admin kiểm thử; người dùng vẫn có thể chọn tay model nhẹ nếu muốn.
    if quality_required:
        return configured
    up, names = check_ollama()
    if not up or not names:
        return configured
    gens = generation_models(names)
    if not gens:
        return configured

    q = _fold(question)
    is_complex = len(q.split()) > 25 or any(w in q for w in _COMPLEX_WORDS)
    if is_complex:
        return configured

    ceiling = _param_size(configured)
    warm = [m for m in generation_models(loaded_models()) if _param_size(m) <= ceiling]
    if warm:
        return min(warm, key=_param_size)     # đã nóng → trả lời được ngay

    smallest = min(gens, key=_param_size)
    return smallest if _param_size(smallest) <= ceiling else configured


def gen_options() -> dict:
    """Tham số sinh câu trả lời — admin chỉnh trên web được.

    num_ctx  : cửa sổ ngữ cảnh. Prompt DÀI HƠN mức này bị Ollama cắt đầu (mất
               luôn phần DỮ LIỆU CÔNG TY nằm ở đầu prompt) mà vẫn phải trả tiền
               thời gian để đọc hết phần còn lại. Nên giữ prompt nhỏ hơn nó, chứ
               không phải cứ đặt num_ctx thật to.
    num_predict: trần số token sinh ra. Chính sách 20/08/2026: KHÔNG chặt cụt
               câu trả lời — mặc định -1 (Ollama hiểu là không giới hạn); chất
               lượng/độ gọn do lượt "bot đọc lại" đảm nhiệm thay vì cắt cứng.
    """
    ctx, predict, threads = 32768, -1, 0
    try:
        from app import settings
        ctx = settings.get_int("llm_num_ctx", ctx)
        predict = settings.get_int("llm_num_predict", predict)
        threads = settings.get_int("llm_num_thread", threads)
    except Exception:
        pass
    opts = {"num_ctx": ctx}
    if predict and predict > 0:
        opts["num_predict"] = predict   # admin vẫn đặt được trần tay khi cần
    # 0 = để Ollama tự quyết. Đặt tay chỉ có ý nghĩa với máy chạy CPU: mặc định
    # thư viện bên dưới thường chỉ dùng số nhân VẬT LÝ, nên máy có nhiều nhân
    # logic có thể nhanh hơn khi khai đúng số nhân.
    if threads > 0:
        opts["num_thread"] = threads
    return opts


def llm_local(prompt: str, system: str = "", temperature: float = 0.2,
              model: str | None = None, stats: dict | None = None,
              num_predict: int | None = None) -> tuple[str, int]:
    """Sinh câu trả lời. `stats` (nếu truyền vào) được điền số liệu chi tiết do
    Ollama báo về: số token prompt, số token sinh ra, thời gian nạp model, thời
    gian đọc prompt, thời gian sinh. Đây là cơ sở để biết chậm ở đâu."""
    name = model or effective_llm_model()
    opts = gen_options()
    if num_predict:
        opts["num_predict"] = num_predict          # phép đo cần số token cố định
    body = {
        "model": name, "prompt": prompt, "system": system, "stream": False,
        "keep_alive": KEEP_ALIVE,
        "options": {"temperature": temperature, **opts},
    }
    if is_thinking_model(name):
        # Cách chính thức (Ollama từ 0.9). Bản cũ bỏ qua cờ này nên thêm cả công
        # tắc mềm "/no_think" của Qwen3 ở cuối prompt cho chắc.
        body["think"] = False
        if "qwen3" in name.lower():
            body["prompt"] = prompt + "\n/no_think"

    t0 = time.time()
    r = requests.post(f"{OLLAMA_URL}/api/generate", json=body, timeout=300)
    if r.status_code == 400 and "think" in body:
        body.pop("think")                      # model không có chế độ suy nghĩ
        r = requests.post(f"{OLLAMA_URL}/api/generate", json=body, timeout=300)
    r.raise_for_status()
    data = r.json()
    ans = (data.get("response") or "").strip()
    if "<think>" in ans:                       # phòng khi model vẫn cố suy nghĩ
        ans = re.sub(r"<think>.*?</think>", "", ans, flags=re.S).strip()

    elapsed = int((time.time() - t0) * 1000)
    if stats is not None:
        ms = lambda ns: int((data.get(ns) or 0) / 1_000_000)
        stats.update({
            "model": name,
            "num_ctx": opts["num_ctx"],
            "prompt_chars": len(body["prompt"]) + len(system or ""),
            "prompt_tokens": data.get("prompt_eval_count"),
            "gen_tokens": data.get("eval_count"),
            "load_ms": ms("load_duration"),        # nạp model từ ổ cứng
            "prefill_ms": ms("prompt_eval_duration"),  # đọc prompt
            "gen_ms": ms("eval_duration"),         # viết câu trả lời
            "total_ms": elapsed,
        })
    return ans, elapsed


class StripThink:
    """Bỏ đoạn <think>…</think> khi chữ về theo từng mẩu nhỏ.

    Ở chế độ không streaming chỉ cần một lệnh thay thế trên cả chuỗi, nhưng khi
    chữ chảy dần thì thẻ có thể bị cắt đôi giữa hai mẩu ("<thi" | "nk>"). Lớp
    này giữ lại phần đuôi nghi là thẻ dở dang cho tới khi đủ dữ kiện để quyết.

    Bình thường không dùng tới — llm_* đã tắt chế độ suy nghĩ. Đây là lưới an
    toàn cho bản Ollama cũ chưa hiểu cờ `think`.
    """

    OPEN, CLOSE = "<think>", "</think>"

    def __init__(self):
        self.buf = ""
        self.inside = False

    def feed(self, piece: str) -> str:
        self.buf += piece
        out = []
        while self.buf:
            if self.inside:
                i = self.buf.find(self.CLOSE)
                if i < 0:
                    # Chưa thấy thẻ đóng: bỏ hết, chỉ giữ đuôi có thể là thẻ dở.
                    self.buf = self.buf[-(len(self.CLOSE) - 1):]
                    break
                self.buf = self.buf[i + len(self.CLOSE):]
                self.inside = False
                continue
            i = self.buf.find(self.OPEN)
            if i < 0:
                keep = len(self.OPEN) - 1
                if len(self.buf) > keep:
                    out.append(self.buf[:-keep])
                    self.buf = self.buf[-keep:]
                break
            out.append(self.buf[:i])
            self.buf = self.buf[i + len(self.OPEN):]
            self.inside = True
        return "".join(out)

    def flush(self) -> str:
        """Phần còn kẹt trong bộ đệm khi dòng kết thúc."""
        rest = "" if self.inside else self.buf
        self.buf = ""
        return rest


def ollama_stream(prompt: str, system: str = "", temperature: float = 0.2,
                  model: str | None = None, stats: dict | None = None):
    """Sinh câu trả lời THEO DÒNG bằng model chạy trên máy chủ (Ollama) — trả về generator từng mẩu chữ.

    Đây là cách duy nhất giữ được trải nghiệm chấp nhận được trên máy chạy CPU:
    người dùng thấy chữ ngay sau khi model đọc xong ngữ cảnh, thay vì ngồi nhìn
    màn hình trống tới lúc viết xong. Nó cũng chấm dứt lỗi 524 vì Cloudflare
    tính giờ từ byte ĐẦU TIÊN của phản hồi.

    `stats` được điền ở gói cuối cùng, y như llm_local.
    """
    name = model or effective_llm_model()
    opts = gen_options()
    body = {
        "model": name, "prompt": prompt, "system": system, "stream": True,
        "keep_alive": KEEP_ALIVE,
        "options": {"temperature": temperature, **opts},
    }
    if is_thinking_model(name):
        body["think"] = False
        if "qwen3" in name.lower():
            body["prompt"] = prompt + "\n/no_think"

    t0 = time.time()
    strip = StripThink()
    r = requests.post(f"{OLLAMA_URL}/api/generate", json=body, timeout=600, stream=True)
    if r.status_code == 400 and "think" in body:
        r.close()
        body.pop("think")
        r = requests.post(f"{OLLAMA_URL}/api/generate", json=body, timeout=600, stream=True)
    try:
        r.raise_for_status()
        for line in r.iter_lines(decode_unicode=True):
            if not line:
                continue
            try:
                data = json.loads(line)
            except ValueError:
                continue
            piece = strip.feed(data.get("response") or "")
            if piece:
                yield piece
            if data.get("done"):
                tail = strip.flush()
                if tail:
                    yield tail
                if stats is not None:
                    ms = lambda ns: int((data.get(ns) or 0) / 1_000_000)
                    stats.update({
                        "model": name,
                        "num_ctx": opts["num_ctx"],
                        "prompt_tokens": data.get("prompt_eval_count"),
                        "gen_tokens": data.get("eval_count"),
                        "load_ms": ms("load_duration"),
                        "prefill_ms": ms("prompt_eval_duration"),
                        "gen_ms": ms("eval_duration"),
                        "total_ms": int((time.time() - t0) * 1000),
                    })
                return
    finally:
        r.close()


# ===================== GỌI API NGOÀI =====================
# Ba điều khiến nhánh này KHÔNG phải bản sao của nhánh Ollama:
#
# 1. KHÔNG gửi `temperature`. Claude Sonnet 5 / Opus 5 đã bỏ hẳn tham số lấy
#    mẫu — gửi lên là lỗi 400, mất câu trả lời. Chữ ký hàm vẫn nhận temperature
#    để mọi lời gọi sẵn có không phải sửa; nhánh Claude lặng lẽ bỏ qua nó.
# 2. KHÔNG có num_ctx. Trần vật lý biến mất nghĩa là KHÔNG CÒN GÌ chặn độ dài
#    prompt — tức không còn gì chặn hoá đơn. Trần cho nhánh cloud nằm ở
#    cloud_context_char_budget (rag.py đọc), không phải ở đây.
# 3. Hỏng thì phải quay về máy nhà. Mất mạng/hết quota mà không có đường lui
#    là mất luôn trợ lý — nên mọi lỗi TRƯỚC token đầu tiên đều rơi xuống
#    Ollama; sau token đầu tiên thì không lui nữa (người dùng đã đọc chữ rồi).


class CloudError(RuntimeError):
    """Lỗi ở nhánh API ngoài. Tách riêng để chỗ gọi phân biệt được 'API hỏng,
    lui về local' với lỗi lập trình của chính mình."""


def _usd(model: str, tok_in: int, tok_out: int, cached_in: int = 0):
    """Ước chi phí một lượt (USD). Token đọc lại từ bộ đệm prompt chỉ tính 10%
    giá vào — đó là lý do đáng đặt cache_control lên system prompt."""
    price = CLAUDE_PRICES.get(bare_model(model))
    if not price:
        return None
    pin, pout = price
    cached_in = cached_in or 0
    fresh = max(0, (tok_in or 0) - cached_in)
    return round((fresh * pin + cached_in * pin * 0.1
                  + (tok_out or 0) * pout) / 1_000_000, 6)


def _anthropic_client():
    try:
        import anthropic
    except ImportError:
        raise CloudError("Chưa cài SDK Anthropic: pip install anthropic") from None
    if not ANTHROPIC_API_KEY:
        raise CloudError("Chưa cấu hình ANTHROPIC_API_KEY trong .env")
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def claude_stream(prompt: str, system: str = "", temperature: float = 0.2,
                  model: str | None = None, stats: dict | None = None):
    """Sinh câu trả lời THEO DÒNG qua API Anthropic.

    `temperature` bị BỎ QUA (xem ghi chú đầu mục). Độ sâu suy nghĩ chỉnh bằng
    `cloud_effort` — đây là nút chỉnh chi phí chính: 'low' cho câu tra cứu
    thường, 'high' cho rà soát hồ sơ. Mặc định 'medium'.

    Khối `system` được đánh dấu cache_control: nó là phong cách tư vấn dài
    hàng nghìn token và LẶP LẠI y hệt ở mọi câu hỏi, nên đọc lại từ bộ đệm chỉ
    còn 10% giá. Phần tài liệu đổi theo từng câu nên không đệm được.
    """
    cfg = cloud_config()
    name = bare_model(model or cfg["model"])
    client = _anthropic_client()
    kw = {
        "model": name,
        "max_tokens": max(1024, int(cfg["max_tokens"] or 8000)),
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        kw["system"] = [{"type": "text", "text": system,
                         "cache_control": {"type": "ephemeral"}}]
    tuned = dict(kw, thinking={"type": "adaptive"},
                 output_config={"effort": cfg["effort"] or "medium"})

    t0 = time.time()
    try:
        ctx = client.messages.stream(**tuned)
    except TypeError:
        # Bản SDK cũ hơn chưa biết thinking/output_config. Chạy được vẫn hơn
        # là chết vì một tham số tinh chỉnh.
        ctx = client.messages.stream(**kw)
    with ctx as stream:
        for piece in stream.text_stream:
            if piece:
                yield piece
        final = stream.get_final_message()
    if stats is not None:
        u = getattr(final, "usage", None)
        tok_in = getattr(u, "input_tokens", 0) or 0
        tok_out = getattr(u, "output_tokens", 0) or 0
        cached = getattr(u, "cache_read_input_tokens", 0) or 0
        stats.update({
            "model": PREFIX_CLAUDE + name, "provider": P_CLAUDE,
            "prompt_tokens": tok_in + cached, "gen_tokens": tok_out,
            "cache_read_tokens": cached,
            "cost_usd": _usd(name, tok_in + cached, tok_out, cached),
            "stop_reason": getattr(final, "stop_reason", None),
            "total_ms": int((time.time() - t0) * 1000),
        })


def compat_stream(prompt: str, system: str = "", temperature: float = 0.2,
                  model: str | None = None, stats: dict | None = None):
    """Sinh câu trả lời THEO DÒNG qua endpoint TƯƠNG THÍCH OpenAI.

    Một hàm cho cả nhóm: Qwen trên DashScope, DeepSeek, OpenRouter, Groq, hay
    máy vLLM tự dựng sau này — họ nói chung giao thức POST /chat/completions
    với SSE. Đổi nhà cung cấp chỉ là đổi COMPAT_BASE_URL + COMPAT_API_KEY.
    """
    if not COMPAT_API_KEY:
        raise CloudError("Chưa cấu hình COMPAT_API_KEY (hoặc OPENAI_API_KEY)")
    name = bare_model(model or "")
    if not name:
        raise CloudError("Chưa chọn model cho endpoint tương thích OpenAI")
    cfg = cloud_config()
    msgs = ([{"role": "system", "content": system}] if system else [])
    msgs.append({"role": "user", "content": prompt})
    body = {"model": name, "messages": msgs, "stream": True,
            "temperature": temperature,
            "max_tokens": max(1024, int(cfg["max_tokens"] or 8000))}
    t0 = time.time()
    strip = StripThink()      # qwen/deepseek qua API vẫn có thể trả <think>
    tok_in = tok_out = 0
    r = requests.post(f"{COMPAT_BASE_URL}/chat/completions",
                      headers={"Authorization": f"Bearer {COMPAT_API_KEY}"},
                      json=body, timeout=600, stream=True)
    try:
        r.raise_for_status()
        for line in r.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                data = json.loads(payload)
            except ValueError:
                continue
            for ch in data.get("choices") or []:
                piece = strip.feed((ch.get("delta") or {}).get("content") or "")
                if piece:
                    yield piece
            usage = data.get("usage") or {}
            tok_in = usage.get("prompt_tokens") or tok_in
            tok_out = usage.get("completion_tokens") or tok_out
        tail = strip.flush()
        if tail:
            yield tail
    finally:
        r.close()
    if stats is not None:
        stats.update({
            "model": PREFIX_COMPAT + name, "provider": P_COMPAT,
            "prompt_tokens": tok_in, "gen_tokens": tok_out,
            "total_ms": int((time.time() - t0) * 1000),
        })


def llm_stream(prompt: str, system: str = "", temperature: float = 0.2,
               model: str | None = None, stats: dict | None = None):
    """Bộ ĐIỀU PHỐI dòng chữ: chọn nhà cung cấp theo tên model rồi chuyển tiếp.

    Vẫn là generator (dùng `yield from`) nên `close()` ở rag.py xuyên tới tận
    generator con — nút "Dừng" ngắt được cả Ollama lẫn kết nối API.
    """
    prov = provider_of(model or "")
    if prov == P_LOCAL:
        yield from ollama_stream(prompt, system, temperature, model, stats)
        return

    fn = claude_stream if prov == P_CLAUDE else compat_stream
    da_ra_chu = False
    try:
        for piece in fn(prompt, system, temperature, model, stats):
            da_ra_chu = True
            yield piece
        return
    except GeneratorExit:
        raise                      # người dùng bấm Dừng — không phải lỗi
    except Exception as e:
        # Đã ra chữ thì không lui được nữa: chèn tiếp bản của model khác vào
        # giữa câu còn tệ hơn dừng hẳn.
        if da_ra_chu or not cloud_config()["fallback_local"]:
            raise
        loi = f"{type(e).__name__}: {e}"
    if stats is not None:
        stats["cloud_error"] = loi
        stats["fallback"] = "local"
    yield from ollama_stream(prompt, system, temperature, None, stats)


def llm_cloud(prompt: str, system: str = "", temperature: float = 0.2,
              model: str | None = None, stats: dict | None = None):
    """Bản KHÔNG streaming của nhánh cloud — gom dòng chữ lại.

    Gom từ luồng chứ không gọi endpoint non-stream: câu trả lời dài (rà soát
    hồ sơ) vượt quá hạn HTTP của bản non-stream, mà đằng nào người gọi cũng
    phải chờ trọn câu nên chẳng mất gì.
    """
    t0 = time.time()
    text = "".join(llm_stream(prompt, system, temperature, model, stats))
    return text.strip(), int((time.time() - t0) * 1000)


def llm_openai(prompt: str, system: str = "", temperature: float = 0.2):
    """Giữ tên cũ cho mã đã có: gọi endpoint tương thích OpenAI theo OPENAI_MODEL."""
    name = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    return llm_cloud(prompt, system, temperature, model=PREFIX_COMPAT + name)


def llm(prompt: str, system: str = "", prefer: str = "local", model: str | None = None,
        stats: dict | None = None, **kw):
    """Sinh câu trả lời, KHÔNG streaming. Nhà cung cấp do TÊN MODEL quyết định.

    `prefer="cloud"` là đường cũ (chỉ OPENAI_MODEL) — giữ nguyên cho mã cũ,
    nhưng cách đúng bây giờ là truyền thẳng tên model có tiền tố.
    """
    if is_cloud(model or ""):
        return llm_cloud(prompt, system, model=model, stats=stats, **kw)
    if prefer == "cloud" and COMPAT_API_KEY:
        return llm_openai(prompt, system, **kw)
    return llm_local(prompt, system, model=model, stats=stats, **kw)


def benchmark(model: str | None = None, prompt_chars: int = 4000) -> dict:
    """Đo tốc độ thật của máy chủ: đọc prompt bao nhiêu token/giây, sinh câu trả
    lời bao nhiêu token/giây. Dùng cho lệnh chẩn đoán và endpoint quản trị.

    Hai con số này quyết định toàn bộ thời gian trả lời:
        thời gian ≈ (số token prompt / tốc độ đọc) + (số token sinh / tốc độ viết)
    """
    if is_cloud(model or ""):
        # Phép đo này nói về PHẦN CỨNG máy chủ (token/giây khi đọc prompt và
        # khi viết). Với model chạy ở nhà người ta thì con số ấy không có ý
        # nghĩa gì để admin ra quyết định — nói thẳng thay vì trả số vô nghĩa.
        return {"ok": False, "error": "Model cloud không đo bằng phép đo phần cứng "
                                      "này. Chọn một model Ollama để đo máy chủ."}
    filler = ("Đây là đoạn văn bản mẫu dùng để đo tốc độ đọc ngữ cảnh của máy chủ. "
              * ((prompt_chars // 80) + 1))[:prompt_chars]
    st: dict = {}
    try:
        # Phải buộc model sinh ĐỦ NHIỀU token thì tốc độ viết mới có ý nghĩa:
        # đo trên vài token thì phần chi phí cố định lấn át, ra số sai lệch.
        _ans, _ms = llm_local(
            f"{filler}\n\nĐếm từ 1 đến 60, mỗi số cách nhau một dấu phẩy.",
            temperature=0.0, model=model, stats=st, num_predict=BENCH_TOKENS)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    # Sinh quá ít token so với yêu cầu → phép đo không đáng tin, báo rõ ra.
    thin = (st.get("gen_tokens") or 0) < BENCH_TOKENS // 3
    speed = lambda tok, ms: round(tok / (ms / 1000), 1) if tok and ms else None
    return {
        "ok": True, "model": st.get("model"), "do_tin_cay_thap": thin,
        "prompt_tokens": st.get("prompt_tokens"), "gen_tokens": st.get("gen_tokens"),
        "load_ms": st.get("load_ms"), "prefill_ms": st.get("prefill_ms"),
        "gen_ms": st.get("gen_ms"), "total_ms": st.get("total_ms"),
        "read_tok_s": speed(st.get("prompt_tokens"), st.get("prefill_ms")),
        "write_tok_s": speed(st.get("gen_tokens"), st.get("gen_ms")),
    }


def summarize(text: str, title: str = "") -> str:
    """Tạo tóm tắt 1-2 câu cho một tài liệu, để hiển thị trong danh sách.
    Chỉ đọc phần đầu (đủ để nắm ý chính) cho nhanh."""
    head = text[:3000]
    prompt = (f"Tóm tắt tài liệu pháp lý sau trong 1-2 câu ngắn gọn tiếng Việt, "
              f"nêu đúng loại văn bản và nội dung chính. Không mở đầu dài dòng.\n\n"
              f"Tên: {title}\n\nNội dung:\n{head}")
    try:
        ans, _ = llm_local(prompt, temperature=0.1)
        return ans.strip()[:500]
    except Exception:
        return ""


def check_ollama():
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        r.raise_for_status()
        return True, [m["name"] for m in r.json().get("models", [])]
    except Exception:
        return False, []


def check_models():
    up, names = check_ollama()
    cur = effective_llm_model()
    cloud = cloud_models()
    cfg = cloud_config()
    phan_cloud = {"cloud": cloud, "cloud_enabled": bool(cfg["enabled"] and cloud),
                  "cloud_model": cfg["model"], "cloud_channels": cfg["channels"]}
    if not up:
        # Ollama chết mà cloud còn sống thì hệ thống vẫn trả lời được — báo
        # đúng như vậy thay vì "llm: false" khiến người trực tưởng hỏng hết.
        return {"ollama": False, "llm": bool(phan_cloud["cloud_enabled"]),
                "embed": False, "models": [], "loaded": [],
                "llm_model": cur, "embed_model": EMBED_MODEL, **phan_cloud}
    has = lambda m: is_cloud(m) or any(n.split(":")[0] == m.split(":")[0] for n in names)
    return {"ollama": True, "llm": has(cur), "embed": has(EMBED_MODEL),
            "models": names, "loaded": loaded_models(),
            "llm_model": cur, "embed_model": EMBED_MODEL, **phan_cloud}


if __name__ == "__main__":
    st = check_models()
    print("Ollama:", st["ollama"], "| LLM:", st["llm"], "| Embed:", st["embed"])
    if st["embed"]:
        print("Vector:", len(embed("kiểm tra")), "chiều")
    if st["llm"]:
        a, ms = llm_local("2+2=?")
        print(f"AI ({ms}ms):", a[:60])
        b = benchmark()
        if b.get("ok"):
            print(f"Tốc độ đọc prompt : {b['read_tok_s']} token/giây")
            print(f"Tốc độ viết       : {b['write_tok_s']} token/giây")
