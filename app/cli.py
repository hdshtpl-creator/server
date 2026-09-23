"""
cli.py — Hỏi đáp thử từ dòng lệnh.
  python -m app.cli "câu hỏi" [internal|public|portal] [client_id]
  python -m app.cli                # chế độ hỏi liên tục
"""
import sys

from app.rag import answer, retrieve


def ask(question, channel="internal", client_id=None):
    print(f"\n{'='*60}\nKÊNH: {channel}" + (f" | khách #{client_id}" if client_id else ""))
    print(f"HỎI: {question}\n{'='*60}")
    chunks = retrieve(question, channel, client_id)
    if not chunks:
        print("\n[!] Không tìm thấy tài liệu liên quan (đã nạp + duyệt chưa?).")
        return
    print(f"\nTÌM ĐƯỢC {len(chunks)} đoạn:")
    for i, c in enumerate(chunks[:5], 1):
        print(f"  [{i}] {c['title']} ({c['score']:.3f})")
    print("\nĐANG HỎI AI...")
    res = answer(question, channel, client_id=client_id)
    print(f"\n{'-'*60}\nTRẢ LỜI:\n{'-'*60}\n{res['answer']}")
    print(f"\n({res['latency_ms']}ms, {len(res['sources'])} nguồn)")


def interactive():
    print("HỎI ĐÁP THỬ — gõ 'thoat' để dừng, '/kenh public' để đổi kênh")
    channel, client_id = "internal", None
    while True:
        try:
            q = input(f"\n[{channel}] > ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not q:
            continue
        if q.lower() in ("thoat", "exit"):
            break
        if q.startswith("/kenh "):
            parts = q.split()
            channel = parts[1]
            client_id = int(parts[2]) if len(parts) > 2 else None
            continue
        try:
            ask(q, channel, client_id)
        except Exception as e:
            print(f"[LỖI] {e}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        interactive()
    else:
        ask(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "internal",
            int(sys.argv[3]) if len(sys.argv) > 3 else None)
