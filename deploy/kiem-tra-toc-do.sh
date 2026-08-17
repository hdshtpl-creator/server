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
# Phân biệt ba trạng thái: (a) GPU chạy tốt, (b) CÓ card nhưng driver hỏng —
# sửa được, không cần mua, (c) không có card nào. Nhầm (b) thành (c) là bỏ lỡ
# cú tăng tốc lớn nhất mà lại miễn phí.
GPU_HW="$(lspci 2>/dev/null | grep -iE 'vga|3d|display' | grep -i nvidia || true)"
if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
  HAS_GPU=1
  ok "GPU NVIDIA hoạt động: $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null | paste -sd'; ')"
elif [ -n "$GPU_HW" ]; then
  bad "CÓ card NVIDIA nhưng DRIVER ĐANG LỖI — model buộc chạy CPU (chậm)."
  echo "     Phần cứng phát hiện được: $GPU_HW"
  echo "     Đây là lỗi driver phần mềm, KHÔNG phải thiếu GPU. Sửa xong sẽ nhanh"
  echo "     gấp hàng chục lần mà không tốn tiền mua card. Thử theo thứ tự:"
  echo "       1. Khởi động lại (rẻ nhất, thường đủ):   sudo reboot"
  echo "       2. Còn lỗi thì cài lại driver:            sudo ubuntu-drivers autoinstall && sudo reboot"
  echo "       3. Secure Boot chặn driver không:         mokutil --sb-state"
  echo "       4. Xem lỗi cụ thể của card:               sudo dmesg | grep -i nvidia | tail"
  echo "     Sau khi nvidia-smi chạy được, Ollama TỰ dùng GPU — không cần chỉnh gì."
else
  bad "KHÔNG tìm thấy card NVIDIA nào → model chạy bằng CPU."
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
if [ "$GEN_TOKENS" -lt 20 ] 2>/dev/null; then
  warn "Model sinh quá ít token — con số tốc độ viết ở trên không đáng tin."
fi

# --------------------------------------------------------------
head_ "4. RAM có chứa nổi CẢ HAI model cùng lúc không"
# --------------------------------------------------------------
# Mỗi câu hỏi dùng 2 model: bge-m3 hiểu câu hỏi, rồi model kia viết câu trả lời.
# Nếu bộ nhớ chỉ chứa được một, Ollama phải đẩy cái này ra để nạp cái kia — và
# lặp lại y hệt ở câu hỏi tiếp theo. Khi đó đặt keep_alive bao lâu cũng vô ích.
EMBED_MODEL="$(grep -E '^EMBED_MODEL=' "$BACKEND_DIR/.env" 2>/dev/null | cut -d= -f2- | tr -d '"' | tr -d "'")"
EMBED_MODEL="${EMBED_MODEL:-bge-m3}"

curl -fsS --max-time 120 -X POST "$OLLAMA_URL/api/embed" \
     -H 'Content-Type: application/json' \
     -d "{\"model\":\"$EMBED_MODEL\",\"input\":\"kiem tra\",\"keep_alive\":\"30m\"}" \
     >/dev/null 2>&1

if command -v ollama >/dev/null 2>&1; then
  RESIDENT="$(ollama ps 2>/dev/null | tail -n +2 | grep -c .)"
  echo "  Sau khi dùng cả hai model, số model còn nằm trong bộ nhớ: $RESIDENT"
  ollama ps 2>/dev/null | sed 's/^/    /'
  if [ "$RESIDENT" -ge 2 ]; then
    ok "Cả hai cùng nằm trong bộ nhớ — không phải nạp lại giữa các câu hỏi."
  else
    bad "Chỉ giữ được MỘT model → mỗi câu hỏi phải nạp lại model từ ổ cứng."
    echo "     Đây thường là nguyên nhân lớn nhất và không sửa được bằng cài đặt."
    echo "     Cách xử lý: dùng model sinh câu trả lời nhỏ hơn (qwen3:4b) để cả"
    echo "     hai cùng vừa bộ nhớ, hoặc lắp thêm RAM/VRAM."
  fi
fi

# --------------------------------------------------------------
head_ "5. Kết luận"
# --------------------------------------------------------------
# 4000 token ≈ ngân sách mặc định: 6000 ký tự tài liệu, cộng hồ sơ công ty,
# 3 lượt hội thoại cũ và câu hỏi. 700 token ≈ trần độ dài câu trả lời.
EST=$(awk -v r="$READ_TOK_S" -v w="$WRITE_TOK_S" \
      'BEGIN{ if (r>0 && w>0) printf "%.0f", 4000/r + 700/w; else print 999 }')
echo "  Ước tính một câu hỏi có đầy đủ ngữ cảnh: khoảng ${EST} giây."

READ_SHARE=$(awk -v r="$READ_TOK_S" 'BEGIN{printf "%.0f", r>0 ? 4000/r : 0}')
WRITE_SHARE=$(awk -v w="$WRITE_TOK_S" 'BEGIN{printf "%.0f", w>0 ? 700/w : 0}')
echo "    trong đó ĐỌC ngữ cảnh ${READ_SHARE}s · VIẾT trả lời ${WRITE_SHARE}s"

if [ "$EST" -gt 90 ]; then
  bad "VƯỢT mốc 100 giây của Cloudflare → sẽ gặp lỗi 524."
  echo "     Cách xử lý, xếp theo hiệu quả:"
  echo "       1. Model nhẹ hơn:  ollama pull qwen3:4b"
  echo "          rồi web → Quản trị → Cài đặt AI → Model AI → chọn qwen3:4b"
  echo "          (mỗi lần giảm một nửa số tham số thì nhanh lên khoảng gấp đôi)"
  echo "       2. Cài đặt AI → Tham số, đặt lại cho máy chậm:"
  echo "            Trần ký tự tài liệu   6000 → 2500"
  echo "            Số đoạn tham chiếu       5 → 3"
  echo "            Cắt mỗi đoạn          1500 → 900"
  echo "            Số lượt hội thoại cũ     3 → 2"
  echo "            Trần độ dài trả lời    700 → 400"
  echo "            Cửa sổ ngữ cảnh       8192 → 4096"
  [ "$HAS_GPU" -eq 0 ] && {
  echo "       3. Thử đặt 'Số luồng CPU cho model' = số nhân của máy ($CORES),"
  echo "          rồi chạy lại script này xem tốc độ ĐỌC có tăng không."
  echo "       4. Về lâu dài: lắp GPU. Đây là khác biệt bậc thang, không phải"
  echo "          vài phần trăm — CPU mạnh hơn cũng chỉ hơn được vài lần."; }
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
