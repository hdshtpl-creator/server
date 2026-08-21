#!/usr/bin/env bash
# =====================================================================
# hoc-lai-file.sh — Đọc lại tài liệu bằng bộ trích xuất/OCR hiện tại
#
# Dùng khi vừa cải thiện OCR, hoặc khi một bản scan đọc ra chữ hỏng.
# Khác `hoc-lai-tu-dau.sh` (xoá sạch cả kho): script này chỉ động vào
# đúng những tài liệu bạn chọn.
#
#   bash deploy/hoc-lai-file.sh --hong            # CHỈ file đọc hỏng (nên dùng)
#   bash deploy/hoc-lai-file.sh --pdf             # TẤT CẢ file PDF
#   bash deploy/hoc-lai-file.sh --bo Mai          # một bộ hồ sơ nhân sự
#   bash deploy/hoc-lai-file.sh 567 573           # theo mã tài liệu
#   bash deploy/hoc-lai-file.sh --pdf --thu       # chỉ xem danh sách, không xoá
#
# Tệp gốc trên Drive KHÔNG bị đụng tới. Trạng thái duyệt được ghi nhớ và
# trả lại cho những file lần này đọc SẠCH; file scan có cảnh báo vẫn phải
# qua người duyệt — nội dung đã khác thì con dấu cũ không còn nói lên gì.
# =====================================================================
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1

c_ok()   { printf '\033[32m  ✔ %s\033[0m\n' "$1"; }
c_bad()  { printf '\033[31m  ✘ %s\033[0m\n' "$1"; }
c_warn() { printf '\033[33m  ! %s\033[0m\n' "$1"; }
c_head() { printf '\n\033[1m%s\033[0m\n' "$1"; }

PG_CONTAINER="${PG_CONTAINER:-hds-postgres}"
if command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$PG_CONTAINER"; then
  q()       { docker exec -i "$PG_CONTAINER" psql -U hds -d hdsai -tAX -F'|' -c "$1" 2>/dev/null; }
  psql_in() { docker exec -i "$PG_CONTAINER" psql -U hds -d hdsai -v ON_ERROR_STOP=1; }
  dump_docs() { docker exec -i "$PG_CONTAINER" pg_dump -U hds -d hdsai -t documents -t chunks 2>/dev/null; }
else
  c_bad "Không thấy container '$PG_CONTAINER' đang chạy. Kiểm tra: docker ps"
  exit 1
fi
[ "$(q 'SELECT 1')" = "1" ] || { c_bad "Không kết nối được PostgreSQL."; exit 1; }

# Định dạng phải qua bộ đọc ảnh/OCR — dùng để nhận diện file "cần đọc lại".
SCAN_EXT="\\.(pdf|jpe?g|png|webp|tiff?|bmp)$"

# --- Đọc tham số ------------------------------------------------------
MODE=""; PERSON=""; DRY=0; IDS=""
while [ $# -gt 0 ]; do
  case "$1" in
    --hong)  MODE="hong" ;;
    --pdf)   MODE="pdf" ;;
    --bo)    MODE="bo"; PERSON="${2:-}"; shift ;;
    --thu|--dry-run) DRY=1 ;;
    ''|*[!0-9]*) c_bad "Tham số không hiểu: '$1'"; exit 1 ;;
    *) MODE="${MODE:-ids}"; IDS="$IDS $1" ;;
  esac
  shift
done

if [ -z "$MODE" ]; then
  echo "Dùng:"
  echo "  bash deploy/hoc-lai-file.sh --hong        # chỉ file đọc hỏng (nên dùng)"
  echo "  bash deploy/hoc-lai-file.sh --pdf         # tất cả PDF"
  echo "  bash deploy/hoc-lai-file.sh --bo <tên>    # một bộ hồ sơ nhân sự"
  echo "  bash deploy/hoc-lai-file.sh <mã…>         # theo mã tài liệu"
  echo "  thêm --thu để chỉ xem danh sách, không xoá gì"
  exit 1
fi

# --- Dựng điều kiện chọn tài liệu -------------------------------------
# Chữ OCR hỏng có dấu vân tay riêng: chữ cái của bảng mã khác (Å Ø ƒ Ð ¬)
# gần như không bao giờ xuất hiện trong hồ sơ pháp lý tiếng Việt thật.
case "$MODE" in
  hong) WHERE="d.source_path ~* '$SCAN_EXT'
                AND (coalesce(d.extraction_status,'ready') <> 'ready'
                     OR EXISTS (SELECT 1 FROM chunks c
                                 WHERE c.document_id = d.id
                                   AND c.content ~ '[ÅØƒÐ¬]'))" ;;
  pdf)  WHERE="d.source_path ~* '\\.pdf$'" ;;
  bo)   [ -n "$PERSON" ] || { c_bad "Thiếu tên bộ hồ sơ sau --bo."; exit 1; }
        WHERE="d.doc_type='ho_so_ns' AND lower(d.person_folder)=lower('$PERSON')" ;;
  ids)  WHERE="d.id = ANY(ARRAY[${IDS// /,}]::int[])" ;;
esac

# --- Xem trước ---------------------------------------------------------
c_head "Tài liệu sẽ được đọc lại"
LIST="$(q "SELECT d.id || '|' || d.title || '|' ||
                  coalesce(d.extraction_status,'ready') || '|' ||
                  (CASE WHEN d.drive_file_id IS NULL THEN 'x' ELSE 'd' END)
             FROM documents d WHERE $WHERE ORDER BY d.title")"
[ -n "$LIST" ] || { c_bad "Không có tài liệu nào khớp."; exit 0; }

TOTAL=0; SCAN=0; NO_DRIVE=0; SKIP_IDS=""
while IFS='|' read -r id title status drive; do
  [ -z "$id" ] && continue
  TOTAL=$((TOTAL + 1))
  if [ "$drive" = "x" ]; then
    NO_DRIVE=$((NO_DRIVE + 1)); SKIP_IDS="$SKIP_IDS $id"
    c_warn "#$id  $title  — KHÔNG từ Drive, sẽ BỎ QUA (xoá là mất hẳn)"
    continue
  fi
  if [ "$status" != "ready" ]; then
    SCAN=$((SCAN + 1)); c_warn "#$id  $title  [$status]"
  else
    c_ok "#$id  $title"
  fi
done <<< "$LIST"

# Không đụng tới file tải lên qua web: xoá đi thì không có nguồn nào học lại.
if [ -n "${SKIP_IDS// /}" ]; then
  WHERE="($WHERE) AND d.id <> ALL(ARRAY[${SKIP_IDS// /,}]::int[])"
  TOTAL=$((TOTAL - NO_DRIVE))
fi
[ "$TOTAL" -gt 0 ] || { c_bad "Không còn tài liệu nào học lại được."; exit 0; }

CHUNKS="$(q "SELECT count(*) FROM chunks c JOIN documents d ON d.id=c.document_id WHERE $WHERE")"
c_head "Tóm tắt"
echo "  Sẽ đọc lại       : $TOTAL tài liệu ($CHUNKS đoạn phải tạo lại vector)"
echo "  Trong đó bản scan: $SCAN — các file này BẮT BUỘC qua người duyệt lại"
echo "  Bỏ qua           : $NO_DRIVE tài liệu không có trên Drive"
echo
echo "  Thời gian: mỗi đoạn phải tạo vector lại, bản scan còn phải OCR 400 dpi."
echo "  Vài trăm đoạn mất vài phút; vài nghìn đoạn có thể mất hàng giờ."
echo "  Trong lúc chạy, các tài liệu này tạm thời không tra cứu được."

if [ "$DRY" = "1" ]; then
  c_head "Chế độ --thu: không xoá gì cả."
  exit 0
fi

echo
printf '\033[1;33mGõ đúng chữ  DOC LAI  rồi Enter để tiếp tục (Enter suông = huỷ): \033[0m'
read -r CONFIRM </dev/tty
[ "$CONFIRM" = "DOC LAI" ] || { echo "Đã huỷ, không thay đổi gì."; exit 0; }

# --- Sao lưu ----------------------------------------------------------
BACKUP="/var/backups/hds-ai-tailieu-$(date +%Y%m%d-%H%M%S).sql.gz"
mkdir -p /var/backups 2>/dev/null || BACKUP="$HOME/hds-ai-tailieu-$(date +%Y%m%d-%H%M%S).sql.gz"
c_head "Sao lưu trước khi xoá → $BACKUP"
if dump_docs | gzip > "$BACKUP" && [ -s "$BACKUP" ]; then
  c_ok "Đã sao lưu ($(du -h "$BACKUP" | cut -f1))."
else
  c_bad "Sao lưu THẤT BẠI — dừng lại để không mất dữ liệu."
  rm -f "$BACKUP"; exit 1
fi

# --- Ghi nhớ trạng thái duyệt rồi xoá ---------------------------------
c_head "Ghi nhớ trạng thái duyệt rồi xoá bản đã học..."
psql_in <<SQL
BEGIN;
DROP TABLE IF EXISTS relearn_approvals;
CREATE TABLE relearn_approvals AS
  SELECT d.drive_file_id, d.approved, d.label_verified
    FROM documents d
   WHERE ($WHERE) AND d.drive_file_id IS NOT NULL
     AND (d.approved OR d.label_verified);
UPDATE messages SET promoted_doc_id = NULL
 WHERE promoted_doc_id IN (SELECT d.id FROM documents d WHERE $WHERE);
DELETE FROM documents d WHERE $WHERE;
COMMIT;
SQL
[ $? -eq 0 ] || { c_bad "Xoá thất bại — CSDL giữ nguyên. Bản sao lưu: $BACKUP"; exit 1; }
c_ok "Đã xoá $TOTAL bản ghi (ghi nhớ $(q 'SELECT count(*) FROM relearn_approvals') con dấu duyệt)."

# --- Học lại ----------------------------------------------------------
c_head "Đồng bộ lại từ Drive — bắt đầu $(date '+%H:%M:%S')"
bash deploy/auto-learn.sh
c_head "Đã học xong lúc $(date '+%H:%M:%S')"

# --- Trả lại con dấu duyệt cho file đọc SẠCH --------------------------
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

PENDING="$(q "SELECT count(*) FROM documents WHERE NOT (approved AND label_verified)")"
c_head "Kết quả"
c_ok "Đã trả lại trạng thái duyệt cho các tài liệu đọc sạch."
[ "${PENDING:-0}" != "0" ] && c_warn "$PENDING tài liệu đang chờ duyệt — mở Quản trị → Duyệt nhãn tài liệu."
echo
echo "  Kiểm tra một bộ hồ sơ:  bash deploy/soi-ho-so.sh <tên bộ>"
echo "  Sao lưu kho cũ giữ tại: $BACKUP (chạy tốt vài ngày rồi hãy xoá)"
