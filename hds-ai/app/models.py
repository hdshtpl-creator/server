"""
models.py — Gọi AI: tạo vector (bge-m3) và sinh câu trả lời (Qwen3), đều qua Ollama.
Không cần PyTorch, không lỗi CUDA trên card Blackwell.
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
    num_predict: trần số token sinh ra → trần thời gian trả lời.
    """
    ctx, predict, threads = 8192, 700, 0
    try:
        from app import settings
        ctx = settings.get_int("llm_num_ctx", ctx)
        predict = settings.get_int("llm_num_predict", predict)
        threads = settings.get_int("llm_num_thread", threads)
    except Exception:
        pass
    opts = {"num_ctx": ctx, "num_predict": predict}
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


def llm_stream(prompt: str, system: str = "", temperature: float = 0.2,
               model: str | None = None, stats: dict | None = None):
    """Sinh câu trả lời THEO DÒNG — trả về generator từng mẩu chữ.

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


def llm_openai(prompt: str, system: str = "", temperature: float = 0.2) -> tuple[str, int]:
    key = os.getenv("OPENAI_API_KEY", "")
    if not key:
        raise RuntimeError("Chưa cấu hình OPENAI_API_KEY")
    t0 = time.time()
    r = requests.post("https://api.openai.com/v1/chat/completions",
                      headers={"Authorization": f"Bearer {key}"},
                      json={"model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                            "messages": (([{"role": "system", "content": system}] if system else [])
                                         + [{"role": "user", "content": prompt}]),
                            "temperature": temperature}, timeout=300)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip(), int((time.time() - t0) * 1000)


def llm(prompt: str, system: str = "", prefer: str = "local", model: str | None = None,
        stats: dict | None = None, **kw):
    if prefer == "cloud" and os.getenv("OPENAI_API_KEY"):
        return llm_openai(prompt, system, **kw)   # kênh đám mây dùng OPENAI_MODEL
    return llm_local(prompt, system, model=model, stats=stats, **kw)


def benchmark(model: str | None = None, prompt_chars: int = 4000) -> dict:
    """Đo tốc độ thật của máy chủ: đọc prompt bao nhiêu token/giây, sinh câu trả
    lời bao nhiêu token/giây. Dùng cho lệnh chẩn đoán và endpoint quản trị.

    Hai con số này quyết định toàn bộ thời gian trả lời:
        thời gian ≈ (số token prompt / tốc độ đọc) + (số token sinh / tốc độ viết)
    """
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
    if not up:
        return {"ollama": False, "llm": False, "embed": False, "models": [],
                "loaded": [], "llm_model": cur, "embed_model": EMBED_MODEL}
    has = lambda m: any(n.split(":")[0] == m.split(":")[0] for n in names)
    return {"ollama": True, "llm": has(cur), "embed": has(EMBED_MODEL),
            "models": names, "loaded": loaded_models(),
            "llm_model": cur, "embed_model": EMBED_MODEL}


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
