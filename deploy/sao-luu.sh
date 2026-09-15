#!/usr/bin/env bash
# sao-luu.sh — Sao lưu CSDL + kho tài liệu, có xoay vòng và thử phục hồi.
#
# Từ khi bỏ Google Drive (27/08/2026) kho trên máy chủ là BẢN GỐC DUY NHẤT;
# CSDL giữ vector, nhãn duyệt, hội thoại, nhật ký. Mất một trong hai là làm
# lại từ đầu. Script này KHÔNG cần root: chạy bằng user chạy backend (user
# đó trong nhóm docker nên pg_dump qua `docker exec` được).
#
#   bash deploy/sao-luu.sh --run            # sao lưu ngay (CSDL + kho)
#   bash deploy/sao-luu.sh --run --chi-db   # chỉ CSDL (nhanh, vài phút)
#   bash deploy/sao-luu.sh --restore-test   # phục hồi bản mới nhất vào CSDL TẠM rồi đếm, không đụng CSDL thật
#   bash deploy/sao-luu.sh --status         # bản gần nhất, dung lượng, lịch
#   bash deploy/sao-luu.sh --install-cron   # 02:30 hằng đêm (crontab của user, không cần root)
#   bash deploy/sao-luu.sh --remove-cron
#
# Nơi lưu: $HDS_BACKUP_DIR (đặt trong hds-ai/.env hoặc môi trường), mặc định
# $HOME/hds-backup. Đặt biến này trỏ sang ổ ngoài / ổ mạng khi có — bản sao
# nằm cùng ổ với bản gốc chỉ chống được xoá nhầm, không chống được hỏng ổ.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "$SCRIPT_DIR/../hds-ai" && pwd)"
ENV_FILE="$BACKEND_DIR/.env"
if [ -f "$ENV_FILE" ]; then
  # Chỉ lấy mấy khoá cần: không `source` cả file để một dòng lạ trong .env
  # không thành lệnh chạy.
  _env() { grep -E "^$1=" "$ENV_FILE" | tail -n1 | cut -d= -f2- | tr -d '"' || true; }
  DB_NAME="${DB_NAME:-$(_env DB_NAME)}"
  DB_USER="${DB_USER:-$(_env DB_USER)}"
  HDS_BACKUP_DIR="${HDS_BACKUP_DIR:-$(_env HDS_BACKUP_DIR)}"
  DATA_LIB="${DATA_LIB:-$(_env DATA_LIB)}"
fi
DB_NAME="${DB_NAME:-hdsai}"
DB_USER="${DB_USER:-hds}"
CONTAINER="${PG_CONTAINER:-hds-postgres}"
BACKUP_DIR="${HDS_BACKUP_DIR:-$HOME/hds-backup}"
KHO_DIR="${DATA_LIB:-$BACKEND_DIR/data/raw}"
GIU_BAN="${HDS_BACKUP_KEEP:-14}"        # số bản dump giữ lại
LOG="$BACKEND_DIR/data/sao_luu.log"      # lượt gần nhất (ghi đè)
HIST="$BACKEND_DIR/data/sao_luu_lich_su.log"  # một dòng mỗi lượt
CRON_MARK="sao-luu.sh' --cron"
CRON_LINE="30 2 * * * /usr/bin/env bash '$SCRIPT_DIR/sao-luu.sh' --cron  # hds-ai: sao luu CSDL + kho"

cron_cmd() { if [ "$(id -u)" = 0 ] && [ "$1" != root ]; then crontab -u "$1" "${@:2}"; else crontab "${@:2}"; fi; }
go_cron_line() { cron_cmd "$1" -l 2>/dev/null | grep -vF "$CRON_MARK" || true; }
ts() { date '+%Y-%m-%d %H:%M:%S'; }

sao_luu() {  # $1 = "db" | "all"
  mkdir -p "$BACKUP_DIR/db" "$BACKUP_DIR/kho" "$BACKEND_DIR/data"
  chmod 700 "$BACKUP_DIR" 2>/dev/null || true
  local start rc=0 dump size kho_msg=""
  start="$(date +%s)"
  dump="$BACKUP_DIR/db/${DB_NAME}-$(date +%Y%m%d-%H%M).dump"
  echo "[$(ts)] pg_dump $DB_NAME → $dump"
  # -Fc: định dạng nén của pg_restore (khôi phục từng bảng được, không phải
  # SQL thuần như bản hoc-lai-*.sh tạo ra).
  if docker exec "$CONTAINER" pg_dump -U "$DB_USER" -Fc "$DB_NAME" > "$dump.part"; then
    mv "$dump.part" "$dump"
    size="$(du -h "$dump" | cut -f1)"
    echo "[$(ts)] CSDL xong: $size"
  else
    rc=1; rm -f "$dump.part"
    echo "[$(ts)] LỖI pg_dump" >&2
  fi
  # Xoay vòng: giữ $GIU_BAN bản mới nhất.
  ls -1t "$BACKUP_DIR"/db/*.dump 2>/dev/null | tail -n +$((GIU_BAN + 1)) | xargs -r rm -f
  # .env không nằm trong dump nhưng thiếu nó là không dựng lại được máy.
  [ -f "$ENV_FILE" ] && cp -p "$ENV_FILE" "$BACKUP_DIR/env.backup" && chmod 600 "$BACKUP_DIR/env.backup"
  if [ "$1" = "all" ]; then
    if [ -d "$KHO_DIR" ]; then
      echo "[$(ts)] rsync kho $KHO_DIR → $BACKUP_DIR/kho/"
      # --delete để bản sao phản ánh đúng kho (file đã gỡ không sống mãi
      # trong bản sao); lỗi từng file (đang ghi dở) không làm hỏng cả lượt.
      if rsync -a --delete --exclude 'uploads/.tmp*' "$KHO_DIR/" "$BACKUP_DIR/kho/"; then
        kho_msg="kho $(du -sh "$BACKUP_DIR/kho" 2>/dev/null | cut -f1)"
      else
        rc=1; kho_msg="kho LỖI rsync"
      fi
      echo "[$(ts)] $kho_msg"
    else
      echo "[$(ts)] Không thấy thư mục kho $KHO_DIR — bỏ qua phần kho" >&2
      kho_msg="kho không thấy"
    fi
  fi
  local giay=$(( $(date +%s) - start ))
  echo "$(date -d @"$start" '+%Y-%m-%d %H:%M:%S') → $(date '+%H:%M:%S') rc=$rc db=${size:-LỖI} ${kho_msg} (${giay}s) đích=$BACKUP_DIR" >> "$HIST"
  return "$rc"
}

restore_test() {
  local dump tmpdb n_doc n_chunk n_bang
  dump="$(ls -1t "$BACKUP_DIR"/db/*.dump 2>/dev/null | head -n1 || true)"
  [ -n "$dump" ] || { echo "Chưa có bản dump nào trong $BACKUP_DIR/db — chạy --run trước."; exit 1; }
  tmpdb="${DB_NAME}_kiemtra_$(date +%H%M%S)"
  echo "Phục hồi $(basename "$dump") vào CSDL tạm $tmpdb (CSDL thật không bị đụng)…"
  docker exec "$CONTAINER" psql -U "$DB_USER" -d postgres -qc "CREATE DATABASE \"$tmpdb\"" >/dev/null
  # pg_restore trả mã khác 0 khi có cảnh báo vặt (role không tồn tại…) —
  # không dừng ở đó, đếm bảng để kết luận.
  docker exec -i "$CONTAINER" pg_restore -U "$DB_USER" -d "$tmpdb" --no-owner --no-privileges < "$dump" 2> "$BACKEND_DIR/data/sao_luu_restore.err" || true
  n_bang="$(docker exec "$CONTAINER" psql -U "$DB_USER" -d "$tmpdb" -At -c "select count(*) from information_schema.tables where table_schema='public'")"
  n_doc="$(docker exec "$CONTAINER" psql -U "$DB_USER" -d "$tmpdb" -At -c "select count(*) from documents" 2>/dev/null || echo 0)"
  n_chunk="$(docker exec "$CONTAINER" psql -U "$DB_USER" -d "$tmpdb" -At -c "select count(*) from chunks" 2>/dev/null || echo 0)"
  docker exec "$CONTAINER" psql -U "$DB_USER" -d postgres -qc "DROP DATABASE \"$tmpdb\"" >/dev/null
  echo "Bản sao phục hồi được: $n_bang bảng, $n_doc tài liệu, $n_chunk đoạn."
  echo "$(ts) RESTORE-TEST $(basename "$dump"): $n_bang bảng, $n_doc tài liệu, $n_chunk đoạn" >> "$HIST"
  [ "${n_doc:-0}" -gt 0 ] && [ "${n_chunk:-0}" -gt 0 ] || { echo "✘ Bản sao KHÔNG dùng được (0 tài liệu/đoạn) — xem $BACKEND_DIR/data/sao_luu_restore.err"; exit 1; }
  echo "✓ Thử phục hồi ĐẠT."
}

case "${1:-}" in
  --run)
    kieu="all"; [ "${2:-}" = "--chi-db" ] && kieu="db"
    sao_luu "$kieu" 2>&1 | tee "$LOG"
    ;;
  --cron)
    export PATH="/usr/local/bin:/usr/bin:/bin:$PATH"
    exec 9>"/tmp/hds-ai-sao-luu.lock"
    flock -n 9 || exit 0
    sao_luu all > "$LOG" 2>&1 || true
    ;;
  --restore-test)
    restore_test
    ;;
  --status)
    echo "Nơi lưu      : $BACKUP_DIR"
    echo "Bản CSDL     : $(ls -1t "$BACKUP_DIR"/db/*.dump 2>/dev/null | head -n1 || echo '(chưa có)')"
    echo "Dung lượng   : $(du -sh "$BACKUP_DIR" 2>/dev/null | cut -f1 || echo '?')"
    echo "Lịch cron    : $(crontab -l 2>/dev/null | grep -F "$CRON_MARK" || echo '(chưa đặt — chạy --install-cron)')"
    echo "Lượt gần nhất: $(tail -n1 "$HIST" 2>/dev/null || echo '(chưa chạy lượt nào)')"
    ;;
  --install-cron)
    command -v crontab >/dev/null || { echo "Máy không có crontab."; exit 1; }
    command -v flock   >/dev/null || { echo "Thiếu flock (util-linux)."; exit 1; }
    me="$(id -un)"
    { go_cron_line "$me"; echo "$CRON_LINE"; } | cron_cmd "$me" -
    echo "✓ Đã đặt lịch sao lưu 02:30 hằng đêm (crontab của $me). Đích: $BACKUP_DIR"
    echo "  Kiểm tra : bash deploy/sao-luu.sh --status"
    echo "  Thử phục hồi : bash deploy/sao-luu.sh --restore-test"
    ;;
  --remove-cron)
    me="$(id -un)"; go_cron_line "$me" | cron_cmd "$me" -
    echo "✓ Đã gỡ lịch sao lưu."
    ;;
  *)
    sed -n '2,20p' "$0"; exit 1
    ;;
esac
