#!/usr/bin/env bash
# =====================================================================
# soi-ho-so.sh — Soi TỪNG GIẤY TỜ trong một bộ hồ sơ nhân sự
#
# Trả lời câu hỏi: "bot đọc được những gì trong hồ sơ của người này?"
# Dùng khi bot nói "không có thông tin" về một người mà giấy tờ nằm sẵn
# trên Drive — hầu hết các ca như vậy là OCR không ra chữ, chứ không phải
# tìm kiếm sai.
#
# Chạy:
#   bash deploy/soi-ho-so.sh Mai          # một bộ hồ sơ
#   bash deploy/soi-ho-so.sh              # liệt kê tất cả các bộ
#   bash deploy/soi-ho-so.sh Mai --xem 3  # in 800 ký tự đầu của giấy tờ #3
#
# Chỉ đọc, không sửa gì.
# =====================================================================
set -uo pipefail

PERSON="${1:-}"
[ "${PERSON:0:2}" = "--" ] && PERSON=""
SHOW_ID=""
if [ "${2:-}" = "--xem" ]; then SHOW_ID="${3:-}"; fi

c_ok()   { printf '\033[32m  ✔ %s\033[0m\n' "$1"; }
c_bad()  { printf '\033[31m  ✘ %s\033[0m\n' "$1"; }
c_warn() { printf '\033[33m  ! %s\033[0m\n' "$1"; }
c_head() { printf '\n\033[1m%s\033[0m\n' "$1"; }

PG_CONTAINER="${PG_CONTAINER:-hds-postgres}"
if command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$PG_CONTAINER"; then
  q() { docker exec -i "$PG_CONTAINER" psql -U hds -d hdsai -tAX -F'|' -c "$1" 2>/dev/null; }
else
  c_bad "Không thấy container '$PG_CONTAINER' đang chạy. Kiểm tra: docker ps"
  exit 1
fi

# --- Không nêu tên: liệt kê các bộ hồ sơ hiện có ----------------------
if [ -z "$PERSON" ]; then
  c_head "Các bộ hồ sơ nhân sự trên cây thư mục"
  q "SELECT person_folder || '  —  ' || count(*) || ' giấy tờ'
       FROM documents
      WHERE doc_type='ho_so_ns' AND person_folder IS NOT NULL
        AND approved AND label_verified AND coalesce(active,true)
      GROUP BY person_folder ORDER BY person_folder" | sed 's/^/  · /'
  echo
  echo "  Soi một bộ:  bash deploy/soi-ho-so.sh <tên thư mục>"
  exit 0
fi

# --- In nội dung đã trích của một giấy tờ cụ thể ----------------------
if [ -n "$SHOW_ID" ]; then
  c_head "Nội dung bot đọc được từ tài liệu #$SHOW_ID"
  q "SELECT left(string_agg(content, E'\n' ORDER BY chunk_index), 800)
       FROM chunks WHERE document_id=$SHOW_ID"
  exit 0
fi

# --- Soi một bộ hồ sơ -------------------------------------------------
c_head "Bộ hồ sơ: $PERSON"
ROWS="$(q "SELECT d.id, d.title, coalesce(d.extraction_status,'ready'),
                  d.approved, d.label_verified,
                  (SELECT count(*) FROM chunks c WHERE c.document_id=d.id),
                  (SELECT coalesce(sum(length(c.content)),0) FROM chunks c WHERE c.document_id=d.id)
             FROM documents d
            WHERE d.doc_type='ho_so_ns'
              AND lower(d.person_folder) = lower('$PERSON')
            ORDER BY d.title")"

if [ -z "$ROWS" ]; then
  c_bad "Không thấy bộ hồ sơ nào tên '$PERSON'."
  echo "     Xem danh sách các bộ:  bash deploy/soi-ho-so.sh"
  exit 1
fi

EMPTY=0
TOTAL=0
while IFS='|' read -r id title status approved verified chunks chars; do
  [ -z "$id" ] && continue
  TOTAL=$((TOTAL + 1))
  # Dưới 200 ký tự cho cả tài liệu = gần như chắc chắn trích xuất hỏng:
  # một trang giấy tờ thật luôn nhiều chữ hơn thế.
  if [ "${chars:-0}" -lt 200 ]; then
    EMPTY=$((EMPTY + 1))
    c_bad "#$id  $title"
    echo "        → chỉ đọc được ${chars} ký tự / ${chunks} đoạn — OCR nhiều khả năng KHÔNG RA CHỮ"
  elif [ "$approved" != "t" ] || [ "$verified" != "t" ]; then
    c_warn "#$id  $title"
    echo "        → ${chars} ký tự nhưng CHƯA DUYỆT (approved=$approved, label_verified=$verified) — bot không dùng"
  elif [ "$status" = "warning" ]; then
    c_warn "#$id  $title"
    echo "        → ${chars} ký tự, ${chunks} đoạn — có CẢNH BÁO trích xuất (bản scan, chữ có thể sai)"
  else
    c_ok "#$id  $title"
    echo "        → ${chars} ký tự, ${chunks} đoạn — đọc tốt"
  fi
done <<< "$ROWS"

echo
echo "  Tổng: $TOTAL giấy tờ, $EMPTY giấy tờ gần như không có chữ."
echo "  Xem bot đọc được gì trong một giấy tờ:  bash deploy/soi-ho-so.sh $PERSON --xem <id>"

# --- Kiểm tra công cụ OCR trên máy chủ --------------------------------
if [ "$EMPTY" -gt 0 ]; then
  c_head "Vì sao OCR không ra chữ — kiểm tra công cụ trên máy chủ"
  if command -v tesseract >/dev/null 2>&1; then
    c_ok "tesseract đã cài ($(tesseract --version 2>&1 | head -1))"
    if tesseract --list-langs 2>/dev/null | grep -qx "vie"; then
      c_ok "Có gói tiếng Việt (vie)."
    else
      c_bad "THIẾU gói tiếng Việt — OCR ra chữ sai bét."
      echo "     Sửa:  sudo apt install -y tesseract-ocr-vie"
    fi
  else
    c_bad "CHƯA cài tesseract — mọi bản scan đều không đọc được."
    echo "     Sửa:  sudo apt install -y tesseract-ocr tesseract-ocr-vie poppler-utils"
  fi
  if command -v pdftoppm >/dev/null 2>&1; then
    c_ok "poppler (pdftoppm) đã cài."
  else
    c_bad "CHƯA cài poppler-utils — không dựng được ảnh từ PDF để OCR."
    echo "     Sửa:  sudo apt install -y poppler-utils"
  fi
  echo
  echo "  Cài xong thì học lại đúng các file đó: sửa/thả lại file trên Drive rồi"
  echo "  chạy  bash deploy/auto-learn.sh  (hoặc chờ lịch tự học 15 phút)."
  echo "  Nếu file vẫn không ra chữ: bản scan quá mờ — scan lại rõ hơn, hoặc vào"
  echo "  Quản trị → Kiểm duyệt → 'Xem & sửa nội dung trích xuất' để gõ tay nội dung."
fi
