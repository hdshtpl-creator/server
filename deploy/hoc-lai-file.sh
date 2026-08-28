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

# --- Chọn bộ học TRƯỚC khi lọc ----------------------------------------
# Phải biết bộ học nào sẽ chạy mới quyết được tài liệu nào "học lại được":
# Drive thì cần drive_file_id, kho local thì cần khoá local: VÀ tệp còn trên
# đĩa. Đoán sai ở đây là xoá tài liệu không có gì phục hồi (rà soát 27/08/2026).
if grep -qE '^DRIVE_FOLDER_ID=.+' hds-ai/.env 2>/dev/null; then
  LEARNER="app.auto_learn"; SRC="Drive"
else
  LEARNER="app.local_learn"; SRC="kho trên máy chủ"
fi
LIB="$(grep -E '^DATA_LIB=' hds-ai/.env 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"'"'"'' || true)"
[ -n "$LIB" ] || LIB="$(grep -E '^DATA_RAW=' hds-ai/.env 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"'"'"'' || true)"
[ -n "$LIB" ] || LIB="./data/raw"
case "$LIB" in /*) ;; *) LIB="hds-ai/${LIB#./}" ;; esac

# Con dấu duyệt được nhớ theo drive_file_id. Học lại bằng bộ quét local trong
# khi bảng còn tài liệu mang danh tính Drive thì khoá không khớp và TOÀN BỘ
# con dấu mất — cả kho rơi về hàng chờ duyệt.
if [ "$LEARNER" = "app.local_learn" ]; then
  DRIVE_KEYS="$(q "SELECT count(*) FROM documents WHERE drive_file_id IS NOT NULL AND drive_file_id NOT LIKE 'local:%'")"
  if [ "${DRIVE_KEYS:-0}" != "0" ]; then
    c_bad "$DRIVE_KEYS tài liệu vẫn mang danh tính Drive, nhưng sắp học lại bằng bộ quét thư mục."
    echo "     Con dấu duyệt sẽ KHÔNG trả lại được. Chạy trước:"
    echo "       cd hds-ai && .venv/bin/python -m app.local_learn --chuyen-doi"
    exit 1
  fi
fi

# --- Xem trước ---------------------------------------------------------
c_head "Tài liệu sẽ được đọc lại (bộ học: $SRC)"
LIST="$(q "SELECT d.id || '|' || d.title || '|' ||
                  coalesce(d.extraction_status,'ready') || '|' ||
                  coalesce(d.drive_file_id,'')
             FROM documents d WHERE $WHERE ORDER BY d.title")"
[ -n "$LIST" ] || { c_bad "Không có tài liệu nào khớp."; exit 0; }

TOTAL=0; SCAN=0; NO_SRC=0; SKIP_IDS=""
while IFS='|' read -r id title status key; do
  [ -z "$id" ] && continue
  TOTAL=$((TOTAL + 1))
  # "Học lại được" theo đúng bộ học sắp chạy.
  RELEARNABLE=1; WHY=""
  if [ -z "$key" ]; then
    RELEARNABLE=0; WHY="không có nguồn gốc (tải lên qua web) — xoá là mất hẳn"
  elif [ "$LEARNER" = "app.local_learn" ]; then
    case "$key" in
      local:*)
        REL="${key#local:}"
        [ -f "$LIB/$REL" ] || { RELEARNABLE=0; WHY="không còn tệp trong kho ($REL) — xoá là mất hẳn"; }
        ;;
      *) RELEARNABLE=0; WHY="danh tính cũ từ Drive, Drive đã ngắt — xoá là mất hẳn" ;;
    esac
  else
    case "$key" in
      local:*) RELEARNABLE=0; WHY="danh tính kho local, không tải lại từ Drive được" ;;
    esac
  fi
  if [ "$RELEARNABLE" = "0" ]; then
    NO_SRC=$((NO_SRC + 1)); SKIP_IDS="$SKIP_IDS $id"
    c_warn "#$id  $title  — BỎ QUA: $WHY"
    continue
  fi
  if [ "$status" != "ready" ]; then
    SCAN=$((SCAN + 1)); c_warn "#$id  $title  [$status]"
  else
    c_ok "#$id  $title"
  fi
done <<< "$LIST"

# Không đụng tới tài liệu không có nguồn học lại: xoá đi là mất hẳn.
if [ -n "${SKIP_IDS// /}" ]; then
  WHERE="($WHERE) AND d.id <> ALL(ARRAY[${SKIP_IDS// /,}]::int[])"
  TOTAL=$((TOTAL - NO_SRC))
fi
[ "$TOTAL" -gt 0 ] || { c_bad "Không còn tài liệu nào học lại được."; exit 0; }

CHUNKS="$(q "SELECT count(*) FROM chunks c JOIN documents d ON d.id=c.document_id WHERE $WHERE")"
c_head "Tóm tắt"
echo "  Sẽ đọc lại       : $TOTAL tài liệu ($CHUNKS đoạn phải tạo lại vector)"
echo "  Trong đó bản scan: $SCAN — các file này BẮT BUỘC qua người duyệt lại"
echo "  Bỏ qua           : $NO_SRC tài liệu không có nguồn để học lại"
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
# /var/backups là thư mục hệ thống: user thường TẠO được (nó có sẵn) nhưng
# GHI thì không. Kiểm tra quyền ghi thật, đừng tin mỗi mkdir — nếu không, script
# đi tới bước ghi rồi mới chết vì Permission denied (gặp thật 21/08/2026).
BACKUP_DIR="/var/backups"
mkdir -p "$BACKUP_DIR" 2>/dev/null
[ -w "$BACKUP_DIR" ] || BACKUP_DIR="$HOME"
BACKUP="$BACKUP_DIR/hds-ai-tailieu-$(date +%Y%m%d-%H%M%S).sql.gz"
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
  SELECT d.drive_file_id, d.source_path, d.approved, d.label_verified
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
# ($LEARNER và $SRC đã chọn ở đầu script, trước bước lọc tài liệu.)
c_head "Đọc lại từ $SRC — bắt đầu $(date '+%H:%M:%S')"
# Bộ học chết giữa chừng mà script chạy tiếp là mất trắng con dấu duyệt: bảng
# relearn_approvals bị DROP ở cuối, trong khi tài liệu đã xoá và chưa học lại.
if ! ( cd hds-ai && .venv/bin/python -m "$LEARNER" ); then
  c_bad "Bộ học DỪNG GIỮA CHỪNG — tài liệu vừa bị xoá và CHƯA học lại."
  echo "  Con dấu duyệt VẪN GIỮ trong bảng relearn_approvals (script không xoá bảng này)."
  echo "  Sửa nguyên nhân (thường là thư mục kho chưa mount / sai DATA_LIB), rồi chạy:"
  echo "    cd hds-ai && .venv/bin/python -m $LEARNER"
  echo "  sau đó chạy lại script này để trả con dấu duyệt, hoặc phục hồi từ: $BACKUP"
  exit 1
fi
c_head "Đã học xong lúc $(date '+%H:%M:%S')"

# --- Trả lại con dấu duyệt cho file đọc SẠCH --------------------------
psql_in <<'SQL'
-- Ghép theo danh tính nguồn, hoặc theo đường dẫn tệp nếu danh tính đã đổi.
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

PENDING="$(q "SELECT count(*) FROM documents WHERE NOT (approved AND label_verified)")"
c_head "Kết quả"
c_ok "Đã trả lại trạng thái duyệt cho các tài liệu đọc sạch."
[ "${PENDING:-0}" != "0" ] && c_warn "$PENDING tài liệu đang chờ duyệt — mở Quản trị → Duyệt nhãn tài liệu."
echo
echo "  Kiểm tra một bộ hồ sơ:  bash deploy/soi-ho-so.sh <tên bộ>"
echo "  Sao lưu kho cũ giữ tại: $BACKUP (chạy tốt vài ngày rồi hãy xoá)"
