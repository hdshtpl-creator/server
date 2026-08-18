#!/usr/bin/env bash
# =====================================================================
# hoc-lai-tu-dau.sh — XOÁ SẠCH kho tài liệu đã học rồi học lại từ Drive
#
# Dùng khi nào: sau khi đổi cách tách đoạn (chia nhỏ hơn, tách theo Điều
# luật), hoặc khi nghi kho vector bị lỗi. Tài liệu GỐC trên Google Drive
# KHÔNG bị đụng tới — script chỉ xoá bản đã học trong CSDL rồi đọc lại.
#
# Chạy:  sudo bash deploy/hoc-lai-tu-dau.sh
#
# THỜI GIAN: học lại toàn bộ kho mất khá lâu (mỗi đoạn phải tạo vector).
# Kho vài trăm tài liệu có thể mất nhiều giờ. Nên chạy ngoài giờ làm việc.
# =====================================================================
set -uo pipefail

BACKEND_DIR="${BACKEND_DIR:-/opt/hds-ai}"
[ -d "$BACKEND_DIR" ] || BACKEND_DIR="$(cd "$(dirname "$0")/../hds-ai" && pwd)"
ENV_FILE="$BACKEND_DIR/.env"

c_ok()   { printf '\033[32m  ✔ %s\033[0m\n' "$1"; }
c_bad()  { printf '\033[31m  ✘ %s\033[0m\n' "$1"; }
c_head() { printf '\n\033[1m%s\033[0m\n' "$1"; }

[ -f "$ENV_FILE" ] || { c_bad "Không thấy $ENV_FILE — chạy trên máy chủ đã cài backend."; exit 1; }
DB_URL="$(grep -E '^DATABASE_URL=' "$ENV_FILE" | tail -1 | cut -d= -f2- | tr -d '"' | tr -d "'")"
[ -n "$DB_URL" ] || { c_bad "Thiếu DATABASE_URL trong .env"; exit 1; }

q() { psql "$DB_URL" -tAX -c "$1" 2>/dev/null; }

# --- Cho xem sẽ mất gì TRƯỚC khi hỏi ---------------------------------
c_head "Sắp xoá khỏi CSDL (tệp gốc trên Drive KHÔNG bị đụng tới):"
echo "  Tài liệu đã học : $(q 'SELECT count(*) FROM documents')"
echo "  Đoạn đã vector  : $(q 'SELECT count(*) FROM chunks')"

c_head "KHÔNG bị xoá:"
echo "  · Toàn bộ tệp gốc trên Google Drive"
echo "  · Lịch sử hội thoại, ghi chú, bản nháp đã soạn"
echo "  · Khách hàng, vụ việc, nhân sự, hoá đơn, tài khoản người dùng"

printf '\n\033[1;33mGõ đúng chữ  XOA  rồi Enter để tiếp tục (Enter suông = huỷ): \033[0m'
read -r CONFIRM
if [ "$CONFIRM" != "XOA" ]; then
  echo "Đã huỷ, không thay đổi gì."
  exit 0
fi

# --- Sao lưu trước khi xoá -------------------------------------------
# Xoá xong mới phát hiện sai thì không còn đường lùi. Bản sao này nhỏ vì
# chỉ chứa hai bảng, nhưng đủ để khôi phục nếu lần học lại gặp sự cố.
BACKUP="/var/backups/hds-ai-tailieu-$(date +%Y%m%d-%H%M%S).sql.gz"
mkdir -p /var/backups 2>/dev/null || BACKUP="$HOME/hds-ai-tailieu-$(date +%Y%m%d-%H%M%S).sql.gz"
c_head "Sao lưu trước khi xoá → $BACKUP"
if pg_dump "$DB_URL" -t documents -t chunks 2>/dev/null | gzip > "$BACKUP"; then
  c_ok "Đã sao lưu ($(du -h "$BACKUP" | cut -f1))."
else
  c_bad "Sao lưu THẤT BẠI. Dừng lại để bạn không mất dữ liệu không phục hồi được."
  rm -f "$BACKUP"
  exit 1
fi

# --- Xoá ---------------------------------------------------------------
# messages.promoted_doc_id không có ON DELETE nên phải gỡ tham chiếu trước,
# nếu không lệnh DELETE sẽ bị khoá ngoại chặn lại. Làm trong MỘT giao dịch:
# hỏng giữa chừng thì quay về nguyên trạng, không để kho nửa vời.
c_head "Đang xoá kho đã học..."
psql "$DB_URL" -v ON_ERROR_STOP=1 <<'SQL'
BEGIN;
UPDATE messages SET promoted_doc_id = NULL WHERE promoted_doc_id IS NOT NULL;
DELETE FROM chunks;
DELETE FROM documents;
-- Lịch sử lỗi học cũng phải dọn: file hỏng sẽ được ghi lại ở lần quét tới,
-- giữ bản cũ chỉ làm dashboard hiện lỗi của lần học trước. Bảng này mới có
-- nên máy chủ chưa chạy migration vẫn phải xoá được kho — kiểm tra trước khi
-- gọi, đừng để cả giao dịch đổ vì một bảng chưa tồn tại.
DO $$
BEGIN
  IF to_regclass('public.ingest_failures') IS NOT NULL THEN
    DELETE FROM ingest_failures;
  END IF;
END $$;
COMMIT;
SQL
if [ $? -ne 0 ]; then
  c_bad "Xoá thất bại — CSDL giữ nguyên như cũ. Xem lỗi ở trên."
  echo "Bản sao lưu vẫn còn tại: $BACKUP"
  exit 1
fi
c_ok "Đã xoá sạch kho đã học."

# --- Học lại ------------------------------------------------------------
# Xoá checksum nghĩa là auto_learn coi mọi file là mới và học lại toàn bộ.
c_head "Bắt đầu học lại từ Google Drive (có thể mất nhiều giờ)..."
echo "Theo dõi tiến độ ở cửa sổ này, hoặc mở Quản trị → Kho tài liệu đã học."
echo

if [ -x "$(dirname "$0")/auto-learn.sh" ]; then
  bash "$(dirname "$0")/auto-learn.sh"
else
  cd "$BACKEND_DIR" && "$BACKEND_DIR/.venv/bin/python" -m app.auto_learn
fi

c_head "Xong. Kiểm tra lại kho:"
echo "  bash deploy/kiem-tra-vector.sh"
echo
echo "Bản sao lưu kho cũ vẫn giữ tại: $BACKUP"
echo "Chạy tốt vài ngày rồi hãy xoá bản sao đó."
