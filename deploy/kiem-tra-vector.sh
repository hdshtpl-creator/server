#!/usr/bin/env bash
# =====================================================================
# kiem-tra-vector.sh — Kiểm tra sức khoẻ kho vector của HDS AI
#
# Trả lời đúng một câu hỏi: "bot đọc tài liệu ổn chưa?"
#
# Chạy:  sudo bash deploy/kiem-tra-vector.sh
#
# Không sửa gì cả, chỉ đọc và báo cáo. An toàn chạy bất cứ lúc nào.
# =====================================================================
set -uo pipefail

BACKEND_DIR="${BACKEND_DIR:-/opt/hds-ai}"
[ -d "$BACKEND_DIR" ] || BACKEND_DIR="$(cd "$(dirname "$0")/../hds-ai" && pwd)"

c_ok()   { printf '\033[32m  ✔ %s\033[0m\n' "$1"; }
c_bad()  { printf '\033[31m  ✘ %s\033[0m\n' "$1"; }
c_warn() { printf '\033[33m  ! %s\033[0m\n' "$1"; }
c_head() { printf '\n\033[1m%s\033[0m\n' "$1"; }

# --- Đọc thông số kết nối từ .env của backend -------------------------
ENV_FILE="$BACKEND_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
  c_bad "Không thấy $ENV_FILE — chạy script này trên MÁY CHỦ đã cài backend."
  exit 1
fi
getenv() { grep -E "^$1=" "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"' | tr -d "'"; }

DB_URL="$(getenv DATABASE_URL)"
EMBED_MODEL="$(getenv EMBED_MODEL)"; EMBED_MODEL="${EMBED_MODEL:-bge-m3}"
OLLAMA_URL="$(getenv OLLAMA_URL)";   OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"

if [ -z "$DB_URL" ]; then
  c_bad "Thiếu DATABASE_URL trong .env"
  exit 1
fi

q() { psql "$DB_URL" -tAX -c "$1" 2>/dev/null; }

# =====================================================================
c_head "1. Kết nối CSDL và tiện ích pgvector"
if ! q "SELECT 1" >/dev/null; then
  c_bad "Không kết nối được PostgreSQL. Kiểm tra DATABASE_URL và dịch vụ postgres."
  exit 1
fi
c_ok "Kết nối PostgreSQL bình thường."

if [ "$(q "SELECT count(*) FROM pg_extension WHERE extname='vector'")" = "1" ]; then
  c_ok "Tiện ích pgvector đã cài."
else
  c_bad "CHƯA cài pgvector — không tra cứu ngữ nghĩa được. Chạy: CREATE EXTENSION vector;"
fi

# =====================================================================
c_head "2. Chỉ mục tìm kiếm"
if [ "$(q "SELECT count(*) FROM pg_indexes WHERE indexname='idx_chunks_vec'")" = "1" ]; then
  c_ok "Chỉ mục vector HNSW có sẵn (tra cứu nhanh)."
else
  c_warn "THIẾU chỉ mục idx_chunks_vec — kho lớn sẽ tra cứu rất chậm."
fi
if [ "$(q "SELECT count(*) FROM information_schema.columns WHERE table_name='chunks' AND column_name='search_vector'")" = "1" ]; then
  c_ok "Cột tìm kiếm từ khoá có sẵn (tra cứu lai vector + từ khoá)."
else
  c_warn "Thiếu cột search_vector — chỉ còn tra cứu bằng vector, mã hồ sơ/số điều dễ trượt."
fi

# =====================================================================
c_head "3. Số liệu kho tài liệu"
DOCS="$(q "SELECT count(*) FROM documents")"
DOCS_READY="$(q "SELECT count(*) FROM documents WHERE approved AND label_verified AND coalesce(active,true) AND coalesce(extraction_status,'ready')='ready'")"
CHUNKS="$(q "SELECT count(*) FROM chunks")"
NOVEC="$(q "SELECT count(*) FROM chunks WHERE embedding IS NULL")"
NOCHUNK="$(q "SELECT count(*) FROM documents d WHERE NOT EXISTS (SELECT 1 FROM chunks c WHERE c.document_id=d.id)")"

echo "  Tài liệu:            ${DOCS:-0}"
echo "  Bot được phép dùng:  ${DOCS_READY:-0}"
echo "  Tổng số đoạn:        ${CHUNKS:-0}"

if [ "${CHUNKS:-0}" = "0" ]; then
  c_bad "KHO RỖNG — chưa học tài liệu nào. Chạy: bash deploy/auto-learn.sh"
elif [ "${NOVEC:-0}" != "0" ]; then
  c_bad "${NOVEC} đoạn CHƯA CÓ VECTOR — những đoạn này bot không bao giờ tìm ra."
  echo "     Nguyên nhân thường gặp: Ollama tắt giữa chừng lúc đang học."
  echo "     Cách sửa: học lại các tài liệu đó (bash deploy/hoc-lai-tu-dau.sh)."
else
  c_ok "Mọi đoạn đều có vector."
fi

[ "${NOCHUNK:-0}" != "0" ] && c_warn "${NOCHUNK} tài liệu không có đoạn nào — đọc được file nhưng không tách được nội dung."

if [ "${DOCS:-0}" != "0" ] && [ "${DOCS_READY:-0}" = "0" ]; then
  c_bad "Có tài liệu nhưng KHÔNG tài liệu nào được bot dùng (chưa duyệt nhãn)."
  echo "     Vào Quản trị → Duyệt nhãn tài liệu."
fi

# --- Số chiều vector phải khớp model ---------------------------------
DIM="$(q "SELECT vector_dims(embedding) FROM chunks WHERE embedding IS NOT NULL LIMIT 1")"
if [ -n "${DIM:-}" ]; then
  if [ "$DIM" = "1024" ]; then
    c_ok "Vector 1024 chiều — khớp model $EMBED_MODEL."
  else
    c_bad "Vector đang là $DIM chiều nhưng schema khai 1024. Kho đã học bằng model khác!"
    echo "     Đổi model tạo vector là HỎNG toàn bộ tra cứu — phải học lại từ đầu."
  fi
fi

# =====================================================================
c_head "4. Model tạo vector"
if curl -fsS --max-time 5 "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
  c_ok "Ollama đang chạy tại $OLLAMA_URL"
  if curl -fsS --max-time 10 "$OLLAMA_URL/api/embed" \
       -d "{\"model\":\"$EMBED_MODEL\",\"input\":\"kiem tra vector\"}" 2>/dev/null | grep -q '"embeddings"'; then
    c_ok "Model tạo vector '$EMBED_MODEL' trả kết quả bình thường."
  else
    c_bad "Model '$EMBED_MODEL' KHÔNG tạo được vector. Chạy: ollama pull $EMBED_MODEL"
  fi
else
  c_bad "Không gọi được Ollama tại $OLLAMA_URL — bot không tra cứu được."
fi

# =====================================================================
c_head "5. Thử một truy vấn thật"
# Lấy một đoạn bất kỳ rồi tìm hàng xóm gần nhất của chính nó. Đoạn gần nhất
# phải là chính nó (khoảng cách ~0); nếu không, chỉ mục hoặc dữ liệu có vấn đề.
SELF="$(q "WITH s AS (SELECT id, embedding FROM chunks WHERE embedding IS NOT NULL LIMIT 1)
           SELECT c.id FROM chunks c, s WHERE c.embedding IS NOT NULL
            ORDER BY c.embedding <=> s.embedding LIMIT 1")"
SRC="$(q "SELECT id FROM chunks WHERE embedding IS NOT NULL LIMIT 1")"
if [ -n "${SELF:-}" ] && [ "$SELF" = "$SRC" ]; then
  c_ok "Truy vấn tương đồng chạy đúng (đoạn gần nhất chính là nó)."
elif [ -n "${SELF:-}" ]; then
  c_warn "Truy vấn chạy nhưng kết quả bất thường — kiểm tra lại chỉ mục."
else
  c_warn "Chưa đủ dữ liệu để thử truy vấn."
fi

# =====================================================================
c_head "6. Tài liệu có trong Drive nhưng KHÔNG học được"
FAILS="$(q "SELECT count(*) FROM ingest_failures WHERE resolved_at IS NULL")"
if [ -z "${FAILS:-}" ]; then
  c_warn "Chưa có bảng ingest_failures — máy chủ chưa chạy migration mới."
  echo "     Chạy: psql \"\$DATABASE_URL\" -f $BACKEND_DIR/sql/schema.sql"
elif [ "$FAILS" = "0" ]; then
  c_ok "Không có tài liệu nào bị lỗi đọc."
else
  c_bad "$FAILS tài liệu KHÔNG học được — xem chi tiết ở Quản trị → Kho tài liệu đã học."
  q "SELECT '     · '||file_name||'  ['||error_code||']' FROM ingest_failures
      WHERE resolved_at IS NULL ORDER BY last_seen_at DESC LIMIT 10"
fi

c_head "Xong."
echo "Có dòng ✘ nào ở trên thì sửa dòng đó trước, rồi chạy lại script này."
