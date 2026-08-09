#!/usr/bin/env bash
# 99_healthcheck.sh — Kiểm tra toàn hệ thống
cd "$(dirname "$0")/.."
source .venv/bin/activate 2>/dev/null || { echo "Chưa có .venv"; exit 1; }
python3 - <<'PY'
import sys
ok=lambda m:print(f"  \033[32m[OK]\033[0m   {m}")
bad=lambda m:print(f"  \033[31m[LỖI]\033[0m  {m}")
fails=0
print("== CSDL ==")
try:
    from app import db
    ok("Kết nối OK") if db.check_connection() else (bad("Không kết nối"),)
    with db.session(role="internal",admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM pg_policies WHERE schemaname='public'")
            p=cur.fetchone()[0]; (ok if p>=2 else bad)(f"RLS policies: {p}")
            if p<2: fails+=1
            cur.execute("SELECT count(*) FROM documents WHERE access_level='client' AND client_id IS NULL")
            o=cur.fetchone()[0]
            ok("Không có tài liệu thiếu chủ") if o==0 else (bad(f"{o} tài liệu thiếu chủ!"),fails:=fails+1)
except Exception as e: bad(f"CSDL: {e}"); fails+=1
print("== AI ==")
try:
    from app.models import check_models,embed,llm_local,EMBED_DIM,LLM_MODEL,EMBED_MODEL
    st=check_models()
    if st["ollama"]:
        ok("Ollama chạy")
        (ok if st["llm"] else bad)(f"{LLM_MODEL}"); (ok if st["embed"] else bad)(f"{EMBED_MODEL}")
        if not st["llm"] or not st["embed"]: fails+=1
    else: bad("Ollama không chạy"); fails+=1
    v=embed("kiểm tra")
    (ok if len(v)==EMBED_DIM else bad)(f"Vector {len(v)} chiều (cần {EMBED_DIM})")
    if len(v)!=EMBED_DIM: fails+=1
except Exception as e: bad(f"AI: {e}"); fails+=1
print("== RAG ==")
try:
    from app.rag import retrieve
    ch=retrieve("thành lập doanh nghiệp","internal")
    ok(f"Tìm được {len(ch)} đoạn") if ch else print("  [LƯU Ý] Kho trống — chạy 50_seed_demo.sh")
except Exception as e: bad(f"RAG: {e}"); fails+=1
print()
if fails: print(f"\033[31mCÓ {fails} LỖI\033[0m"); sys.exit(1)
print("\033[32mHỆ THỐNG BÌNH THƯỜNG\033[0m — bước tiếp: python -m tests.test_security")
PY
