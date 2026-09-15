#!/usr/bin/env bash
# =====================================================================
# xem-noi-luu.sh — CHỈ ĐỌC. Mở ra cho xem tận mắt ba thứ hay bị hỏi:
#
#   1. Model AI (qwen3) cài ở đâu, nặng bao nhiêu, đang chạy bằng gì
#   2. Bộ nhớ hội thoại nằm ở đâu, gồm những gì, giữ bao lâu
#   3. Kho vector nằm ở đâu, bao nhiêu đoạn, chiếm bao nhiêu dung lượng
#
# Mỗi mục IN RA CẢ LỆNH rồi mới in kết quả — người xem tự kiểm chứng được,
# không phải tin lời script.
#
#   bash deploy/xem-noi-luu.sh
#
# Không sửa gì, không xoá gì. An toàn chạy trước mặt khách bất cứ lúc nào.
# =====================================================================
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

BACKEND_DIR="$(pwd)/hds-ai"
ENV_FILE="$BACKEND_DIR/.env"
OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"
PG_CONTAINER="${PG_CONTAINER:-hds-postgres}"

c_head() { printf '\n\033[1;36m══ %s\033[0m\n' "$1"; }
c_sub()  { printf '\n\033[1m%s\033[0m\n' "$1"; }
c_cmd()  { printf '\033[90m   $ %s\033[0m\n' "$1"; }
c_ok()   { printf '\033[32m   ✔ %s\033[0m\n' "$1"; }
c_bad()  { printf '\033[31m   ✘ %s\033[0m\n' "$1"; }
c_warn() { printf '\033[33m   ! %s\033[0m\n' "$1"; }
indent() { sed 's/^/   /'; }

getenv() {
  [ -f "$ENV_FILE" ] || return 0
  grep -E "^$1=" "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"' | tr -d "'"
}

# PostgreSQL chạy trong container (setup.sh dựng bằng docker compose), nên máy
# chủ thường KHÔNG có psql. Gọi thẳng psql ở host là lỗi socket — không phải
# CSDL hỏng, chỉ là gọi nhầm chỗ.
if command -v docker >/dev/null 2>&1 &&
   docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$PG_CONTAINER"; then
  HAS_DB=1
  q() { docker exec -i "$PG_CONTAINER" psql -U hds -d hdsai -tAX -c "$1" 2>/dev/null; }
  qt() { docker exec -i "$PG_CONTAINER" psql -U hds -d hdsai -X -c "$1" 2>/dev/null; }
else
  HAS_DB=0
  c_bad "Container '$PG_CONTAINER' không chạy — phần CSDL sẽ bị bỏ qua."
  echo "     Kiểm tra bằng: docker ps"
fi

# =====================================================================
c_head "1. MODEL AI — cài ở đâu, nặng bao nhiêu"

c_sub "1a. Các model đã tải về máy"
c_cmd "ollama list"
if command -v ollama >/dev/null 2>&1; then
  ollama list 2>/dev/null | indent
else
  c_warn "Không thấy lệnh ollama trong PATH; thử: sudo -u ollama ollama list"
fi

c_sub "1b. Model đang NẰM TRONG BỘ NHỚ và chạy bằng GPU hay CPU"
c_cmd "ollama ps"
if command -v ollama >/dev/null 2>&1; then
  ollama ps 2>/dev/null | indent
  echo "   → cột PROCESSOR ghi '100% GPU' là model nằm trọn trên card đồ hoạ."
fi

c_sub "1c. File model nằm ở thư mục nào, chiếm bao nhiêu ổ cứng"
MODEL_DIR=""
for d in /usr/share/ollama/.ollama/models "$HOME/.ollama/models" /var/lib/ollama/.ollama/models; do
  [ -d "$d" ] && { MODEL_DIR="$d"; break; }
done
if [ -n "$MODEL_DIR" ]; then
  c_cmd "du -sh $MODEL_DIR"
  du -sh "$MODEL_DIR" 2>/dev/null | indent
  c_cmd "ls -la $MODEL_DIR/blobs | head"
  ls -la "$MODEL_DIR/blobs" 2>/dev/null | head -8 | indent
  echo "   → mỗi 'blob' là một lát trọng số model. Đây là file THẬT của qwen3."
else
  c_warn "Chưa tìm thấy thư mục model của Ollama ở các vị trí thường gặp."
fi

c_sub "1d. Dịch vụ Ollama và card đồ hoạ"
c_cmd "systemctl is-active ollama ; nvidia-smi --query-gpu=name,memory.total,memory.used --format=csv,noheader"
systemctl is-active ollama 2>/dev/null | indent || true
command -v nvidia-smi >/dev/null 2>&1 &&
  nvidia-smi --query-gpu=name,memory.total,memory.used --format=csv,noheader 2>/dev/null | indent

c_sub "1e. Hệ thống ĐANG cấu hình dùng model nào"
CFG_MODEL=""
[ "$HAS_DB" = 1 ] && CFG_MODEL="$(q "SELECT value FROM app_settings WHERE key='llm_model'" | tr -d '\r')"
if [ -n "$CFG_MODEL" ]; then
  c_ok "Model sinh câu trả lời: $CFG_MODEL   (đặt trong Quản trị → Cài đặt AI)"
else
  c_ok "Model sinh câu trả lời: $(getenv LLM_MODEL)   (lấy từ hds-ai/.env)"
fi
c_ok "Model tạo vector      : $(getenv EMBED_MODEL)   (cố định — đổi là phải học lại toàn kho)"

# =====================================================================
c_head "2. BỘ NHỚ HỘI THOẠI — nằm ở đâu, giữ những gì"

if [ "$HAS_DB" = 1 ]; then
  echo "   Tất cả nằm trong PostgreSQL, KHÔNG nằm ở file rời trên đĩa."
  echo "   Ba bảng, ba vai trò khác nhau:"

  c_sub "2a. conversations — mỗi dòng là một cuộc trò chuyện"
  c_cmd "psql -c \"SELECT count(*) FROM conversations\""
  printf '   Số cuộc trò chuyện đang lưu: %s\n' "$(q 'SELECT count(*) FROM conversations')"
  printf '   Trong đó tab Kiểm tra pháp lý: %s\n' "$(q "SELECT count(*) FROM conversations WHERE kind='legal'")"

  c_sub "2b. messages — từng câu hỏi và câu trả lời, kèm nguồn trích dẫn"
  c_cmd "psql -c \"SELECT count(*) FROM messages\""
  printf '   Tổng số tin nhắn: %s\n' "$(q 'SELECT count(*) FROM messages')"
  echo "   Mỗi tin nhắn của AI giữ thêm: nguồn đã trích (sources), bằng chứng"
  echo "   (evidence), model đã dùng, thời gian trả lời — nên mở lại hội thoại cũ"
  echo "   là thấy đúng bot đã dựa vào tài liệu nào."

  c_sub "2c. Bộ nhớ DÀI — hội thoại quá dài thì phần cũ được cô đọng lại"
  c_cmd "psql -c \"SELECT count(*) FROM conversations WHERE summary IS NOT NULL\""
  printf '   Số cuộc đã có bản tóm tắt luỹ tiến: %s\n' \
    "$(q 'SELECT count(*) FROM conversations WHERE summary IS NOT NULL')"
  echo "   Cột summary giữ bản cô đọng, summary_upto đánh dấu đã gộp tới tin nào."
  echo "   Các tin sau mốc đó vẫn vào prompt NGUYÊN VĂN — giống cách Claude/ChatGPT"
  echo "   nhớ hội thoại dài mà không phình vô hạn."

  c_sub "2d. Năm cuộc trò chuyện gần nhất (chỉ tiêu đề, KHÔNG mở nội dung)"
  qt "SELECT id, kind AS loai, left(coalesce(title,''),40) AS tieu_de,
             (SELECT count(*) FROM messages m WHERE m.conversation_id=c.id) AS so_tin,
             (summary IS NOT NULL) AS co_tom_tat,
             to_char(started_at,'DD/MM HH24:MI') AS bat_dau
        FROM conversations c ORDER BY id DESC LIMIT 5" | indent

  c_sub "2e. File đính kèm trong chat — hàng TẠM, tự xoá sau 6 giờ"
  printf '   Đang còn hạn: %s file\n' "$(q 'SELECT count(*) FROM temp_files WHERE expires_at > now()')"
  echo "   Bảng temp_files. File đính kèm KHÔNG vào kho tri thức: hết 6 giờ là"
  echo "   bản ghi lẫn file gốc trong data/work/chat_uploads/ đều bị dọn."
else
  c_warn "Bỏ qua — không kết nối được CSDL."
fi

# =====================================================================
c_head "3. KHO VECTOR — nằm ở đâu, lớn cỡ nào"

if [ "$HAS_DB" = 1 ]; then
  c_sub "3a. Vector nằm TRONG PostgreSQL, không phải một thư mục riêng"
  echo "   Đây là điểm hay bị hiểu nhầm: hệ thống KHÔNG có 'thư mục vector'."
  echo "   Vector là một CỘT trong bảng chunks (kiểu vector(1024) của pgvector),"
  echo "   nằm cùng chỗ với nội dung đoạn văn và nhãn phân quyền của nó."
  c_cmd "psql -c \"\\d chunks\"  → cột embedding vector(1024)"
  printf '   Tiện ích pgvector: %s\n' \
    "$(q "SELECT 'đã bật, bản ' || extversion FROM pg_extension WHERE extname='vector'")"

  c_sub "3b. Bao nhiêu đoạn đã có vector"
  c_cmd "psql -c \"SELECT count(*) FROM chunks WHERE embedding IS NOT NULL\""
  printf '   Tài liệu đã học : %s\n' "$(q 'SELECT count(*) FROM documents')"
  printf '   Tổng số đoạn    : %s\n' "$(q 'SELECT count(*) FROM chunks')"
  printf '   Đoạn CÓ vector  : %s\n' "$(q 'SELECT count(*) FROM chunks WHERE embedding IS NOT NULL')"
  MISS="$(q 'SELECT count(*) FROM chunks WHERE embedding IS NULL')"
  if [ "${MISS:-0}" = "0" ]; then
    c_ok "Không đoạn nào thiếu vector — cả kho đều tra cứu được."
  else
    c_warn "$MISS đoạn CHƯA có vector — những đoạn này bot không tìm thấy."
  fi

  c_sub "3c. Chiếm bao nhiêu dung lượng"
  c_cmd "psql -c \"SELECT pg_size_pretty(pg_total_relation_size('chunks'))\""
  printf '   Bảng chunks (kèm chỉ mục): %s\n' \
    "$(q "SELECT pg_size_pretty(pg_total_relation_size('chunks'))")"
  printf '   Toàn bộ CSDL hdsai       : %s\n' \
    "$(q "SELECT pg_size_pretty(pg_database_size('hdsai'))")"

  c_sub "3d. Chỉ mục tìm kiếm — vì sao tra cứu nhanh"
  qt "SELECT indexname AS chi_muc,
             pg_size_pretty(pg_relation_size(indexname::regclass)) AS kich_thuoc
        FROM pg_indexes WHERE tablename='chunks' ORDER BY indexname" | indent
  echo "   idx_chunks_vec (HNSW)  = tìm theo NGHĨA."
  echo "   idx_chunks_fts (GIN)   = tìm theo TỪ KHOÁ, giữ được số hiệu văn bản."
  echo "   Hai chỉ mục chạy song song rồi trộn điểm — nên hỏi bằng lời thường"
  echo "   hay gõ đúng mã hồ sơ đều ra."
else
  c_warn "Bỏ qua — không kết nối được CSDL."
fi

c_sub "3e. File CSDL nằm ở chỗ nào trên ổ cứng"
c_cmd "docker volume inspect hds-ai_pgdata"
VOL="$(docker volume ls --format '{{.Name}}' 2>/dev/null | grep -E 'pgdata$' | head -1)"
if [ -n "$VOL" ]; then
  MP="$(docker volume inspect "$VOL" --format '{{.Mountpoint}}' 2>/dev/null)"
  c_ok "Volume Docker: $VOL"
  c_ok "Thư mục thật : $MP"
  [ -n "$MP" ] && [ -d "$MP" ] && du -sh "$MP" 2>/dev/null | indent
  echo "   → ĐÂY là thứ bắt buộc phải sao lưu. Mất nó là mất vector, hội thoại,"
  echo "     nhãn phân quyền và cài đặt. Model qwen3 thì tải lại được."
else
  c_warn "Không thấy volume pgdata — kiểm tra: docker volume ls"
fi

# =====================================================================
c_head "TÓM TẮT BỐN NƠI LƯU"
printf '   %-22s %s\n' "Bản gốc tài liệu"  "$BACKEND_DIR/data/raw/"
printf '   %-22s %s\n' "Hàng tạm tự sinh"  "$BACKEND_DIR/data/work/"
printf '   %-22s %s\n' "Vector + hội thoại" "PostgreSQL, volume ${VOL:-hds-ai_pgdata}"
printf '   %-22s %s\n' "Model AI"          "${MODEL_DIR:-/usr/share/ollama/.ollama/models}"
echo
echo "   Chi tiết và sơ đồ luồng dữ liệu: deploy/LUU_TRU_DU_LIEU.md"
