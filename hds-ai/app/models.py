"""
models.py — Gọi AI: tạo vector (bge-m3) và sinh câu trả lời (Qwen3), đều qua Ollama.
Không cần PyTorch, không lỗi CUDA trên card Blackwell.
"""
import os
import re
import time
import unicodedata

import requests
from dotenv import load_dotenv

load_dotenv()

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen3:8b")
EMBED_MODEL = os.getenv("EMBED_MODEL", "bge-m3")
EMBED_DIM = int(os.getenv("EMBED_DIM", "1024"))


def embed(texts, batch_size: int = 16):
    single = isinstance(texts, str)
    if single:
        texts = [texts]
    if not texts:
        return []
    out = []
    for i in range(0, len(texts), batch_size):
        r = requests.post(f"{OLLAMA_URL}/api/embed",
                          json={"model": EMBED_MODEL, "input": texts[i:i + batch_size]}, timeout=300)
        r.raise_for_status()
        vecs = r.json().get("embeddings")
        if not vecs:
            raise RuntimeError(f"Ollama không trả vector. Tải model: ollama pull {EMBED_MODEL}")
        out.extend(vecs)
    if out and len(out[0]) != EMBED_DIM:
        raise RuntimeError(f"Model trả {len(out[0])} chiều, cấu hình EMBED_DIM={EMBED_DIM}. "
                           f"Sửa .env và cột vector({EMBED_DIM}) trong schema.sql cho khớp.")
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


def auto_pick_model(question: str) -> str:
    """'Tự động': câu ĐƠN GIẢN dùng model nhanh nhất; câu PHỨC TẠP dùng model
    admin đã đặt. KHÔNG bao giờ chọn model nặng hơn mặc định → tránh chậm/524."""
    configured = effective_llm_model()
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
    smallest = min(gens, key=_param_size)
    # Chỉ hạ xuống model nhẹ hơn/bằng mặc định, không nâng lên nặng hơn.
    return smallest if _param_size(smallest) <= _param_size(configured) else configured


def llm_local(prompt: str, system: str = "", temperature: float = 0.2,
              model: str | None = None) -> tuple[str, int]:
    t0 = time.time()
    # num_predict chặn số token sinh ra → chặn TRẦN thời gian trả lời. Không có
    # nó, model chậm có thể sinh cả nghìn token, vượt 100s và bị Cloudflare cắt
    # (lỗi 524). Câu trả lời pháp lý gọn gàng hiếm khi cần quá ngần này.
    r = requests.post(f"{OLLAMA_URL}/api/generate", json={
        "model": model or effective_llm_model(), "prompt": prompt, "system": system,
        "stream": False,
        "options": {"temperature": temperature, "num_ctx": 8192, "num_predict": 1024}}, timeout=300)
    r.raise_for_status()
    ans = r.json().get("response", "").strip()
    if "<think>" in ans:                       # Qwen3 chế độ suy nghĩ
        ans = re.sub(r"<think>.*?</think>", "", ans, flags=re.S).strip()
    return ans, int((time.time() - t0) * 1000)


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


def llm(prompt: str, system: str = "", prefer: str = "local", model: str | None = None, **kw):
    if prefer == "cloud" and os.getenv("OPENAI_API_KEY"):
        return llm_openai(prompt, system, **kw)   # kênh đám mây dùng OPENAI_MODEL
    return llm_local(prompt, system, model=model, **kw)


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
                "llm_model": cur, "embed_model": EMBED_MODEL}
    has = lambda m: any(n.split(":")[0] == m.split(":")[0] for n in names)
    return {"ollama": True, "llm": has(cur), "embed": has(EMBED_MODEL),
            "models": names, "llm_model": cur, "embed_model": EMBED_MODEL}


if __name__ == "__main__":
    st = check_models()
    print("Ollama:", st["ollama"], "| LLM:", st["llm"], "| Embed:", st["embed"])
    if st["embed"]:
        print("Vector:", len(embed("kiểm tra")), "chiều")
    if st["llm"]:
        a, ms = llm_local("2+2=?")
        print(f"AI ({ms}ms):", a[:60])
