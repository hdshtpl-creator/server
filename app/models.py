"""
models.py — Gọi AI: tạo vector (bge-m3) và sinh câu trả lời (Qwen3), đều qua Ollama.
Không cần PyTorch, không lỗi CUDA trên card Blackwell.
"""
import os
import re
import time

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


def llm_local(prompt: str, system: str = "", temperature: float = 0.2) -> tuple[str, int]:
    t0 = time.time()
    r = requests.post(f"{OLLAMA_URL}/api/generate", json={
        "model": LLM_MODEL, "prompt": prompt, "system": system, "stream": False,
        "options": {"temperature": temperature, "num_ctx": 8192}}, timeout=300)
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


def llm(prompt: str, system: str = "", prefer: str = "local", **kw):
    if prefer == "cloud" and os.getenv("OPENAI_API_KEY"):
        return llm_openai(prompt, system, **kw)
    return llm_local(prompt, system, **kw)


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
    if not up:
        return {"ollama": False, "llm": False, "embed": False, "models": []}
    has = lambda m: any(n.split(":")[0] == m.split(":")[0] for n in names)
    return {"ollama": True, "llm": has(LLM_MODEL), "embed": has(EMBED_MODEL), "models": names}


if __name__ == "__main__":
    st = check_models()
    print("Ollama:", st["ollama"], "| LLM:", st["llm"], "| Embed:", st["embed"])
    if st["embed"]:
        print("Vector:", len(embed("kiểm tra")), "chiều")
    if st["llm"]:
        a, ms = llm_local("2+2=?")
        print(f"AI ({ms}ms):", a[:60])
