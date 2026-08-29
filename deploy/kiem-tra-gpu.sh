#!/usr/bin/env bash
# =====================================================================
# kiem-tra-gpu.sh — GPU có đang GÁNH model không, hay lặng lẽ rơi về CPU?
#
# Máy có GPU 16GB không có nghĩa Ollama đang dùng trọn nó. Ca kinh điển:
# num_ctx đặt to làm (trọng số + bộ nhớ ngữ cảnh KV) vượt VRAM → Ollama
# đẩy MỘT PHẦN model sang CPU mà không báo ai — tốc độ rơi từ vài chục
# token/giây xuống một chữ số, nhìn hệt như "máy không có GPU".
#
#   bash deploy/kiem-tra-gpu.sh
# =====================================================================
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

c_ok()   { printf '\033[32m  ✔ %s\033[0m\n' "$1"; }
c_bad()  { printf '\033[31m  ✘ %s\033[0m\n' "$1"; }
c_warn() { printf '\033[33m  ! %s\033[0m\n' "$1"; }
c_head() { printf '\n\033[1m%s\033[0m\n' "$1"; }

OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"

c_head "1) Card đồ hoạ"
if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi --query-gpu=name,memory.total,memory.used,utilization.gpu \
             --format=csv,noheader | sed 's/^/   /'
else
  c_bad "Không có nvidia-smi — driver NVIDIA chưa cài, Ollama chắc chắn chạy CPU."
  echo "   Cài driver rồi chạy lại: sudo ubuntu-drivers install"
fi

c_head "2) Model đang nạp và nằm ở đâu (cột PROCESSOR là câu trả lời)"
if command -v ollama >/dev/null 2>&1; then
  ollama ps | sed 's/^/   /'
  echo "   → '100% GPU' là chuẩn. Thấy 'xx%/yy% CPU/GPU' nghĩa là model bị"
  echo "     CHẺ ĐÔI vì thiếu VRAM — tốc độ rơi xuống gần mức CPU thuần."
else
  c_warn "Không thấy lệnh ollama trong PATH — thử: sudo -u ollama ollama ps"
fi

c_head "3) Đo tốc độ THẬT với đúng num_ctx hệ thống đang dùng"
NUM_CTX="$(docker exec -i "${PG_CONTAINER:-hds-postgres}" psql -U hds -d hdsai -tA \
  -c "SELECT value FROM app_settings WHERE key='llm_num_ctx'" 2>/dev/null | tr -d '\r')"
[ -n "$NUM_CTX" ] || NUM_CTX=32768
MODEL="$(docker exec -i "${PG_CONTAINER:-hds-postgres}" psql -U hds -d hdsai -tA \
  -c "SELECT value FROM app_settings WHERE key='llm_model'" 2>/dev/null | tr -d '\r')"
[ -n "$MODEL" ] || MODEL="$(grep -E '^LLM_MODEL=' hds-ai/.env 2>/dev/null | cut -d= -f2)"
[ -n "$MODEL" ] || MODEL="qwen3:14b"
echo "   Model: $MODEL — num_ctx: $NUM_CTX"
RES="$(curl -s "$OLLAMA_URL/api/generate" -d "{
  \"model\": \"$MODEL\", \"prompt\": \"Viết một đoạn 5 câu về hợp đồng lao động.\",
  \"stream\": false, \"options\": {\"num_ctx\": $NUM_CTX, \"num_predict\": 128}}")"
if [ -z "$RES" ]; then
  c_bad "Ollama không phản hồi tại $OLLAMA_URL"
else
  echo "$RES" | python3 -c "
import json, sys
d = json.load(sys.stdin)
ev, ed = d.get('eval_count') or 0, d.get('eval_duration') or 1
pv, pd = d.get('prompt_eval_count') or 0, d.get('prompt_eval_duration') or 1
sinh = ev * 1e9 / ed
print(f'   Sinh chữ : {sinh:.1f} token/giây ({ev} token)')
print(f'   Đọc prompt: {pv * 1e9 / pd:.1f} token/giây')
print(f'   Nạp model : {(d.get(\"load_duration\") or 0)/1e9:.1f} giây')
if sinh < 12:
    print('   → MỨC CPU. Gần như chắc chắn model đang bị chẻ CPU/GPU — xem mục 2 và 4.')
elif sinh < 25:
    print('   → Lửng lơ — một phần model có thể đang nằm ngoài GPU.')
else:
    print('   → Tốc độ mức GPU. Ổn.')
"
fi

c_head "4) Ollama có than thiếu VRAM không (log 30 dòng gần nhất có chữ memory/offload)"
journalctl -u ollama -n 400 --no-pager 2>/dev/null \
  | grep -iE "offload|not enough|insufficient|memory|gpu" | tail -8 | sed 's/^/   /' \
  || c_warn "Không đọc được log ollama (thử chạy bằng sudo)."

c_head "5) Ước lượng VRAM cho cấu hình hiện tại"
python3 - "$NUM_CTX" <<'PY'
import sys
ctx = int(sys.argv[1])
# qwen3:14b: 40 lớp, 8 đầu KV (GQA), chiều 128 → mỗi token ~0.31MB KV ở f16.
kv_f16 = ctx * 2 * 40 * 8 * 128 * 2 / 1024**3
w = 9.3   # trọng số q4_K_M
print(f"   qwen3:14b @ num_ctx={ctx}:")
print(f"     Trọng số ~{w:.1f}GB + KV f16 ~{kv_f16:.1f}GB + đệm ~1.5GB ≈ {w+kv_f16+1.5:.1f}GB")
print(f"     Với KV nén q8_0: ≈ {w+kv_f16/2+1.5:.1f}GB  (bge-m3 chiếm thêm ~1.2GB khi cùng nạp)")
if w + kv_f16 + 1.5 > 16:
    print("   → VƯỢT 16GB ở KV f16. Hai đường: bật nén KV (khuyến nghị) hoặc hạ num_ctx.")
PY

c_head "Khuyến nghị cho card 16GB + qwen3:14b (làm khi mục 2/3 cho thấy bị chẻ)"
cat <<'HD'
   sudo mkdir -p /etc/systemd/system/ollama.service.d
   printf '[Service]\nEnvironment="OLLAMA_FLASH_ATTENTION=1"\nEnvironment="OLLAMA_KV_CACHE_TYPE=q8_0"\n' \
     | sudo tee /etc/systemd/system/ollama.service.d/vram.conf
   sudo systemctl daemon-reload && sudo systemctl restart ollama
   # Rồi chạy lại script này — mục 2 phải ra '100% GPU', mục 3 phải tăng rõ.
   # Vẫn chẻ? Hạ cửa sổ ngữ cảnh trên web: Quản trị → Cài đặt AI →
   # "Cửa sổ ngữ cảnh của model" = 24576 (trần ký tự tài liệu tự co theo).
HD
