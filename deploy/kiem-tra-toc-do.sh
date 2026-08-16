#!/usr/bin/env bash
# ====================================================================
# HDS AI — Chẩn đoán TỐC ĐỘ trả lời.
#
#   bash deploy/kiem-tra-toc-do.sh
#
# Trả lời đúng một câu hỏi: vì sao bot trả lời lâu / báo lỗi 524?
#
# Nguyên lý: thời gian trả lời ≈ (số token prompt ÷ tốc độ ĐỌC)
#                              + (số token đáp  ÷ tốc độ VIẾT)
# Hai tốc độ đó do PHẦN CỨNG quyết định; độ dài prompt do CÀI ĐẶT quyết định.
# Lượng dữ liệu đã học KHÔNG nằm trong công thức — tra cứu vector luôn trả về
# đúng top_k đoạn, nên kho lớn lên không làm câu trả lời chậm đi.
# ====================================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "$SCRIPT_DIR/../hds-ai" && pwd)"
OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"
PY="$BACKEND_DIR/.venv/bin/python"

R='\033[0;31m'; G='\033[0;32m'; Y='\033[1;33m'; B='\033[1;34m'; N='\033[0m'
ok()    { echo -e "  ${G}✓${N} $*"; }
warn()  { echo -e "  ${Y}!${N} $*"; }
bad()   { echo -e "  ${R}✗${N} $*"; }
head_() { echo -e "\n${B}== $* ==${N}"; }

# --------------------------------------------------------------
head_ "1. Phần cứng"
# --------------------------------------------------------------
CORES=$(nproc 2>/dev/null || echo '?')
RAM_GB=$(awk '/MemTotal/ {printf "%.0f", $2/1048576}' /proc/meminfo 2>/dev/null || echo '?')
RAM_FREE=$(awk '/MemAvailable/ {printf "%.1f", $2/1048576}' /proc/meminfo 2>/dev/null || echo '?')
echo "  CPU: $CORES nhân · RAM: ${RAM_GB}GB (còn trống ${RAM_FREE}GB)"

HAS_GPU=0
if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
  HAS_GPU=1
  ok "GPU: $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null | paste -sd'; ')"
else
  bad "KHÔNG có GPU NVIDIA dùng được → model chạy bằng CPU."
  echo "     Đây thường là nguyên nhân gốc của mọi thứ chậm bên dưới."
fi

# --------------------------------------------------------------
head_ "2. Ollama"
# --------------------------------------------------------------
if ! curl -fsS --max-time 5 "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
  bad "Không kết nối được Ollama tại $OLLAMA_URL — chạy: sudo systemctl start ollama"
  exit 1
fi
ok "Ollama đang chạy"

echo "  Model đã cài:"
curl -fsS "$OLLAMA_URL/api/tags" |
  grep -o '"name":"[^"]*"' | cut -d'"' -f4 | sed 's/^/    · /'

if command -v ollama >/dev/null 2>&1; then
  PS_OUT="$(ollama ps 2>/dev/null)"
  echo "  Model đang nằm sẵn trong bộ nhớ:"
  echo "$PS_OUT" | sed 's/^/    /'
  # Cột PROCESSOR là sự thật quan trọng nhất: GPU hay CPU.
  if echo "$PS_OUT" | grep -qi "100% CPU"; then
    bad "Model đang chạy 100% CPU."
  elif echo "$PS_OUT" | grep -qi "GPU"; then
    ok "Model đang chạy bằng GPU."
  elif [ "$(echo "$PS_OUT" | tail -n +2 | grep -c .)" = "0" ]; then
    warn "Không model nào nằm sẵn → câu hỏi kế tiếp phải nạp lại model từ ổ cứng (mất thêm hàng chục giây)."
  fi
fi

# --------------------------------------------------------------
head_ "3. Đo tốc độ thật"
# --------------------------------------------------------------
if [ ! -x "$PY" ]; then
  bad "Chưa có môi trường Python tại $PY — chạy trước: sudo bash deploy/setup.sh"
  exit 1
fi

echo "  Đang đo bằng đúng model và cài đặt mà web app dùng (chờ chút…)"
# Gọi thẳng hàm benchmark của backend: cùng model, cùng num_ctx/num_predict,
# cùng cờ tắt suy nghĩ — nên con số đo được đúng với lúc chạy thật.
BENCH="$(cd "$BACKEND_DIR" && "$PY" -c \
  'import json; from app import models; print(json.dumps(models.benchmark()))' 2>&1)"

if ! echo "$BENCH" | grep -q '"ok": true'; then
  bad "Không đo được:"
  echo "$BENCH" | tail -5 | sed 's/^/    /'
  exit 1
fi

# json.dumps để giá trị luôn được bọc nháy — eval không vấp tên model lạ.
eval "$(echo "$BENCH" | "$PY" -c '
import json, sys
d = json.load(sys.stdin)
for k in ("model", "read_tok_s", "write_tok_s", "load_ms", "prompt_tokens", "gen_tokens"):
    print(k.upper() + "=" + json.dumps(str(d.get(k) or 0)))
')"

echo "  Model đo được         : $MODEL"
echo "  Nạp model vào bộ nhớ  : $(awk -v m="$LOAD_MS" 'BEGIN{printf "%.1f", m/1000}')s"
echo "  Tốc độ ĐỌC ngữ cảnh   : ${READ_TOK_S} token/giây  (đọc $PROMPT_TOKENS token)"
echo "  Tốc độ VIẾT trả lời   : ${WRITE_TOK_S} token/giây  (viết $GEN_TOKENS token)"

# --------------------------------------------------------------
head_ "4. Kết luận"
# --------------------------------------------------------------
# 4000 token ≈ ngân sách mặc định: 6000 ký tự tài liệu, cộng hồ sơ công ty,
# 3 lượt hội thoại cũ và câu hỏi. 700 token ≈ trần độ dài câu trả lời.
EST=$(awk -v r="$READ_TOK_S" -v w="$WRITE_TOK_S" \
      'BEGIN{ if (r>0 && w>0) printf "%.0f", 4000/r + 700/w; else print 999 }')
echo "  Ước tính một câu hỏi có đầy đủ ngữ cảnh: khoảng ${EST} giây."

if [ "$EST" -gt 90 ]; then
  bad "VƯỢT mốc 100 giây của Cloudflare → sẽ gặp lỗi 524."
  echo "     Cách xử lý, xếp theo hiệu quả:"
  echo "       1. Model nhẹ hơn:  ollama pull qwen3:4b"
  echo "          rồi web → Quản trị → Cài đặt AI → Model AI → chọn qwen3:4b"
  echo "       2. Giảm 'Trần ký tự tài liệu' 7000 → 4000  (Cài đặt AI → Tham số)"
  echo "       3. Giảm 'Trần độ dài câu trả lời' 700 → 400"
  [ "$HAS_GPU" -eq 0 ] && \
  echo "       4. Về lâu dài: lắp GPU — đổi CPU mạnh hơn chỉ nhanh hơn được vài lần"
elif [ "$EST" -gt 45 ]; then
  warn "Chạy được nhưng còn chậm. Cân nhắc model nhẹ hơn hoặc giảm trần ký tự tài liệu."
else
  ok "Tốc độ ổn cho vận hành."
fi

if awk -v w="$WRITE_TOK_S" 'BEGIN{exit !(w>0 && w<8)}'; then
  echo ""
  warn "Viết dưới 8 token/giây là đặc trưng của chạy CPU."
  echo "     Model 14B trên CPU không có cách nào đủ nhanh — hãy dùng 4B hoặc 8B."
fi

echo ""
echo "  Xem lại các câu trả lời chậm gần đây:"
echo "    sudo journalctl -u hds-ai-backend -n 200 | grep CHAM"
echo ""
