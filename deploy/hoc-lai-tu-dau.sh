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

# setup.sh dựng PostgreSQL trong container `hds-postgres`; máy chủ thường không
# có psql. Dò container trước, host chỉ là phương án hai. Ba hàm dưới là toàn
# bộ chỗ script này chạm vào CSDL, nên đổi cách kết nối chỉ cần sửa ở đây.
PG_CONTAINER="${PG_CONTAINER:-hds-postgres}"
if command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$PG_CONTAINER"; then
  q()       { docker exec -i "$PG_CONTAINER" psql -U hds -d hdsai -tAX -c "$1" 2>/dev/null; }
  psql_in() { docker exec -i "$PG_CONTAINER" psql -U hds -d hdsai -v ON_ERROR_STOP=1; }
  dump_docs() { docker exec -i "$PG_CONTAINER" pg_dump -U hds -d hdsai -t documents -t chunks 2>/dev/null; }
elif command -v psql >/dev/null 2>&1 && [ -n "$DB_URL" ]; then
  q()       { psql "$DB_URL" -tAX -c "$1" 2>/dev/null; }
  psql_in() { psql "$DB_URL" -v ON_ERROR_STOP=1; }
  dump_docs() { pg_dump "$DB_URL" -t documents -t chunks 2>/dev/null; }
else
  c_bad "Không tìm được cách kết nối CSDL."
  echo "     · Container '$PG_CONTAINER' không chạy — kiểm tra: docker ps"
  echo "     · Máy chủ cũng không có lệnh psql."
  exit 1
fi

if [ "$(q 'SELECT 1')" != "1" ]; then
  c_bad "Không kết nối được PostgreSQL. Kiểm tra: docker ps | grep $PG_CONTAINER"
  exit 1
fi

# --- Cho xem sẽ mất gì TRƯỚC khi hỏi ---------------------------------
c_head "Sắp xoá khỏi CSDL (tệp gốc trên Drive KHÔNG bị đụng tới):"
echo "  Tài liệu đã học : $(q 'SELECT count(*) FROM documents')"
echo "  Đoạn đã vector  : $(q 'SELECT count(*) FROM chunks')"

c_head "KHÔNG bị xoá:"
echo "  · Toàn bộ tệp gốc trên Google Drive"
echo "  · Lịch sử hội thoại, ghi chú, bản nháp đã soạn"
echo "  · Khách hàng, vụ việc, nhân sự, hoá đơn, tài khoản người dùng"
echo "  · Trạng thái đã duyệt: script tự ghi nhớ rồi trả lại sau khi học xong,"
echo "    nên bạn KHÔNG phải ngồi duyệt tay lại từ đầu."

c_head "Trong lúc chạy:"
echo "  Bot sẽ TẠM THỜI không tra cứu được tài liệu nào cho tới khi học xong."
echo "  Nên chạy ngoài giờ làm việc."

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
if dump_docs | gzip > "$BACKUP" && [ -s "$BACKUP" ]; then
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
# --- Giữ lại quyết định duyệt của con người ---------------------------
# Học lại đưa MỌI tài liệu vào hàng chờ duyệt (AUTO_LEARN_AUTO_APPROVE mặc định
# tắt). Không giữ gì thì sau khi chạy xong bot mất sạch tài liệu dùng được, và
# người ta phải ngồi duyệt tay lại từng file — trong khi chính họ đã duyệt
# những file đó rồi, từ cùng thư mục Drive, cùng nhãn.
#
# Nhãn bám theo cấu trúc thư mục nên học lại cho ra nhãn y hệt; thứ duy nhất
# đáng giữ là con dấu "đã có người xem và đồng ý". Ghi ra bảng thật (không phải
# temp) vì nó phải sống qua nhiều phiên psql và cả lượt chạy python ở giữa.
c_head "Ghi nhớ trạng thái duyệt hiện tại..."
psql_in <<'SQL'
DROP TABLE IF EXISTS relearn_approvals;
CREATE TABLE relearn_approvals AS
  SELECT drive_file_id, approved, label_verified
    FROM documents
   WHERE drive_file_id IS NOT NULL AND (approved OR label_verified);
SQL
KEPT="$(q 'SELECT count(*) FROM relearn_approvals')"
c_ok "Đã ghi nhớ ${KEPT:-0} tài liệu từng được duyệt."

c_head "Đang xoá kho đã học..."
psql_in <<'SQL'
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

# --- Trả lại con dấu duyệt --------------------------------------------
# Chỉ trả cho tài liệu đọc SẠCH lần này. File nào lần này bị cảnh báo trích xuất
# (OCR mờ, bảng bị cắt) thì phải để người xem lại, dù trước đây đã duyệt — nội
# dung đã khác đi thì con dấu cũ không còn nói lên điều gì.
c_head "Trả lại trạng thái duyệt cho tài liệu đã được duyệt trước đây..."
psql_in <<'SQL'
UPDATE documents d
   SET approved       = d.approved OR r.approved,
       label_verified = d.label_verified OR r.label_verified,
       updated_at     = now()
  FROM relearn_approvals r
 WHERE d.drive_file_id = r.drive_file_id
   AND coalesce(d.extraction_status,'ready') = 'ready';
DROP TABLE IF EXISTS relearn_approvals;
SQL

USABLE="$(q "SELECT count(*) FROM documents WHERE approved AND label_verified AND coalesce(active,true) AND coalesce(extraction_status,'ready')='ready'")"
PENDING="$(q "SELECT count(*) FROM documents WHERE NOT (approved AND label_verified)")"
c_ok "Bot dùng được ${USABLE:-0} tài liệu."
[ "${PENDING:-0}" != "0" ] && printf '\033[33m  ! %s tài liệu đang chờ duyệt — mở Quản trị → Duyệt nhãn tài liệu.\033[0m\n' "$PENDING"

c_head "Xong. Kiểm tra lại kho:"
echo "  bash deploy/kiem-tra-vector.sh"
echo
echo "Bản sao lưu kho cũ vẫn giữ tại: $BACKUP"
echo "Chạy tốt vài ngày rồi hãy xoá bản sao đó."
