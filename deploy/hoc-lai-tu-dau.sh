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
# /var/backups la thu muc he thong: user thuong TAO duoc (no co san) nhung GHI
# thi khong. Kiem tra quyen ghi that, dung tin moi mkdir - neu khong, script di
# toi buoc ghi roi moi chet vi Permission denied (gap that 21/08/2026).
BACKUP_DIR="/var/backups"
mkdir -p "$BACKUP_DIR" 2>/dev/null
[ -w "$BACKUP_DIR" ] || BACKUP_DIR="$HOME"
BACKUP="$BACKUP_DIR/hds-ai-tailieu-$(date +%Y%m%d-%H%M%S).sql.gz"
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
# Con dấu duyệt được nhớ theo drive_file_id. Nếu sắp học lại bằng bộ quét thư
# mục trong khi bảng còn tài liệu mang danh tính Drive, khoá hai bên không khớp
# và TOÀN BỘ con dấu mất — cả kho rơi về hàng chờ duyệt (rà soát 27/08/2026).
if grep -qE '^DRIVE_FOLDER_ID=.+' "$BACKEND_DIR/.env" 2>/dev/null; then
  LEARNER_CHECK="app.auto_learn"
else
  LEARNER_CHECK="app.local_learn"
fi
if [ "$LEARNER_CHECK" = "app.local_learn" ]; then
  DRIVE_KEYS="$(q "SELECT count(*) FROM documents WHERE drive_file_id IS NOT NULL AND drive_file_id NOT LIKE 'local:%'")"
  if [ "${DRIVE_KEYS:-0}" != "0" ]; then
    c_bad "$DRIVE_KEYS tài liệu vẫn mang danh tính Drive, nhưng sẽ học lại bằng bộ quét thư mục."
    echo "     Con dấu duyệt sẽ KHÔNG trả lại được — cả kho rơi về hàng chờ duyệt."
    echo "     Chạy trước:  cd $BACKEND_DIR && .venv/bin/python -m app.local_learn --chuyen-doi"
    exit 1
  fi
fi

c_head "Ghi nhớ trạng thái duyệt hiện tại..."
psql_in <<'SQL'
DROP TABLE IF EXISTS relearn_approvals;
CREATE TABLE relearn_approvals AS
  SELECT drive_file_id, source_path, approved, label_verified
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
# Bảng documents đã trống nên bộ học coi mọi file là mới và học lại toàn bộ.
LEARNER="$LEARNER_CHECK"
SRC_LABEL="$([ "$LEARNER" = "app.auto_learn" ] && echo "Google Drive" || echo "kho trên máy chủ")"
c_head "Bắt đầu học lại từ $SRC_LABEL (có thể mất nhiều giờ)..."
echo "Theo dõi tiến độ ở cửa sổ này, hoặc mở Quản trị → Kho tài liệu đã học."
echo "   Bộ học: $LEARNER"
echo

# Bộ học chết giữa chừng mà script chạy tiếp là mất trắng con dấu duyệt: khối
# bên dưới DROP bảng relearn_approvals trong khi kho vừa bị xoá sạch.
cd "$BACKEND_DIR" || { c_bad "Không vào được $BACKEND_DIR."; exit 1; }
if ! "$BACKEND_DIR/.venv/bin/python" -m "$LEARNER"; then
  c_bad "Bộ học $LEARNER DỪNG GIỮA CHỪNG — kho vừa bị xoá và CHƯA học lại."
  echo "  Con dấu duyệt (${KEPT:-0}) VẪN GIỮ trong bảng relearn_approvals."
  echo "  Sửa nguyên nhân (thường là thư mục kho chưa mount / sai DATA_LIB), rồi chạy:"
  echo "    cd $BACKEND_DIR && .venv/bin/python -m $LEARNER"
  echo "  sau đó chạy lại script này để trả con dấu duyệt, hoặc phục hồi: $BACKUP"
  exit 1
fi

# Học xong mà kho vẫn trống = bộ học chạy nhưng không thấy tệp nào (ổ chưa
# mount). Đừng DROP bảng con dấu duyệt trong tình huống đó.
LEARNED="$(q 'SELECT count(*) FROM documents')"
if [ "${LEARNED:-0}" = "0" ] && [ "${KEPT:-0}" != "0" ]; then
  c_bad "Học xong nhưng kho TRỐNG (0 tài liệu) trong khi trước đó có ${KEPT} tài liệu đã duyệt."
  echo "  Nhiều khả năng thư mục kho chưa mount. Con dấu duyệt vẫn giữ trong relearn_approvals."
  echo "  Kiểm tra thư mục rồi chạy lại bộ học; hoặc phục hồi: $BACKUP"
  exit 1
fi

# --- Trả lại con dấu duyệt --------------------------------------------
# Chỉ trả cho tài liệu đọc SẠCH lần này. File nào lần này bị cảnh báo trích xuất
# (OCR mờ, bảng bị cắt) thì phải để người xem lại, dù trước đây đã duyệt — nội
# dung đã khác đi thì con dấu cũ không còn nói lên điều gì.
c_head "Trả lại trạng thái duyệt cho tài liệu đã được duyệt trước đây..."
psql_in <<'SQL'
-- Ghép theo danh tính nguồn, hoặc theo đường dẫn tệp nếu danh tính đã đổi
-- (đổi bộ học Drive ↔ local). Thiếu vế source_path là mất sạch con dấu duyệt
-- khi khoá hai bên khác không gian tên.
UPDATE documents d
   SET approved       = d.approved OR r.approved,
       label_verified = d.label_verified OR r.label_verified,
       updated_at     = now()
  FROM relearn_approvals r
 WHERE (d.drive_file_id = r.drive_file_id
        OR (r.source_path IS NOT NULL AND d.source_path = r.source_path))
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
