#!/usr/bin/env bash
# hoc-tu-thu-muc.sh — Bot học tài liệu từ THƯ MỤC TRÊN MÁY CHỦ (app.local_learn).
#
# Thay deploy/auto-learn.sh sau khi bỏ Google Drive (quyết định 27/08/2026).
#
# Chạy:
#   bash deploy/hoc-tu-thu-muc.sh                 # quét và học ngay
#   bash deploy/hoc-tu-thu-muc.sh --dry-run       # chỉ liệt kê, không ghi gì
#   bash deploy/hoc-tu-thu-muc.sh --chuyen-doi    # MỘT LẦN khi vừa bỏ Drive
#   sudo bash deploy/hoc-tu-thu-muc.sh --install-timer   # quét mỗi 3 phút (systemd)
#   sudo bash deploy/hoc-tu-thu-muc.sh --remove-timer
#   bash deploy/hoc-tu-thu-muc.sh --install-cron  # quét mỗi 3 phút, KHÔNG cần root
#   bash deploy/hoc-tu-thu-muc.sh --remove-cron   #   (crontab của user chạy backend)
#   bash deploy/hoc-tu-thu-muc.sh --cron          # một lượt như cron gọi (có khoá)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "$SCRIPT_DIR/../hds-ai" && pwd)"
SERVICE_USER="${SUDO_USER:-$(stat -c '%U' "$BACKEND_DIR")}"

# Chu kỳ 3 phút (16/09/2026, trước là 15): một lượt quét kho 42 nghìn tệp chỉ
# tốn ~8 giây sau khi thôi đọc lại tệp hỏng mỗi lượt, nên chạy dày hơn vẫn nhẹ
# mà nhân viên thả tệp vào ổ mạng gần như thấy ngay.
# Dòng crontab nhận ra bằng chuỗi "hoc-tu-thu-muc.sh' --cron" — gỡ/cài đều so
# theo chuỗi này, nên đổi tên script là phải đổi cả hai chỗ.
CRON_LINE="*/3 * * * * /usr/bin/env bash '$SCRIPT_DIR/hoc-tu-thu-muc.sh' --cron  # hds-ai: quet kho tai lieu"
CRON_MARK="hoc-tu-thu-muc.sh' --cron"

cron_cmd() {  # crontab của user $1 — chỉ root mới được dùng -u (Debian/Ubuntu)
  if [ "$(id -u)" = 0 ] && [ "$1" != root ]; then crontab -u "$1" "${@:2}"; else crontab "${@:2}"; fi
}
go_cron_line() {  # $1 = user; in crontab đã bỏ dòng quét kho (rỗng nếu chưa có gì)
  cron_cmd "$1" -l 2>/dev/null | grep -vF "$CRON_MARK" || true
}

case "${1:-}" in
  --install-timer)
    [ "$(id -u)" = 0 ] || { echo "Cần quyền root: sudo bash deploy/hoc-tu-thu-muc.sh --install-timer"; exit 1; }
    cat > /etc/systemd/system/hds-ai-quet-kho.service <<EOF
[Unit]
Description=HDS AI - quet kho tai lieu tren may chu va hoc file moi
After=network-online.target hds-ai-backend.service

[Service]
Type=oneshot
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$BACKEND_DIR
ExecStart=$BACKEND_DIR/.venv/bin/python -m app.local_learn
EOF
    cat > /etc/systemd/system/hds-ai-quet-kho.timer <<EOF
[Unit]
Description=HDS AI - quet kho tai lieu dinh ky

[Timer]
OnBootSec=3min
OnUnitActiveSec=3min
Persistent=true

[Install]
WantedBy=timers.target
EOF
    systemctl daemon-reload
    systemctl enable --now hds-ai-quet-kho.timer
    # Bộ quét Drive cũ (nếu còn) phải tắt: hai bộ cùng chạy sẽ tranh nhau ghi
    # cùng một khoá trạng thái và học chồng chéo.
    if systemctl list-unit-files 2>/dev/null | grep -q '^hds-ai-learn.timer'; then
      systemctl disable --now hds-ai-learn.timer 2>/dev/null || true
      echo "  Đã tắt lịch học từ Drive cũ (hds-ai-learn.timer)."
    fi
    # Lịch cron (bản không cần root) cũng phải gỡ — hai lịch cùng chu kỳ chỉ
    # thay nhau bị khoá chặn, vô ích và rối nhật ký.
    if cron_cmd "$SERVICE_USER" -l 2>/dev/null | grep -qF "$CRON_MARK"; then
      go_cron_line "$SERVICE_USER" | cron_cmd "$SERVICE_USER" -
      echo "  Đã gỡ lịch cron cũ của $SERVICE_USER (giờ dùng timer systemd)."
    fi
    echo "✓ Đã bật lịch quét kho mỗi 3 phút."
    echo "  Xem lần chạy tới : systemctl list-timers hds-ai-quet-kho.timer"
    echo "  Xem log          : journalctl -u hds-ai-quet-kho.service -n 40 --no-pager"
    echo "  Chạy ngay 1 lần  : sudo systemctl start hds-ai-quet-kho.service"
    ;;
  --remove-timer)
    [ "$(id -u)" = 0 ] || { echo "Cần quyền root."; exit 1; }
    systemctl disable --now hds-ai-quet-kho.timer 2>/dev/null || true
    rm -f /etc/systemd/system/hds-ai-quet-kho.service /etc/systemd/system/hds-ai-quet-kho.timer
    systemctl daemon-reload
    echo "✓ Đã gỡ lịch quét kho."
    ;;
  --install-cron)
    # Lịch 15 phút bằng crontab của user chạy backend — dùng khi không có root.
    command -v crontab >/dev/null || { echo "Máy không có crontab — dùng --install-timer (cần root)."; exit 1; }
    command -v flock   >/dev/null || { echo "Thiếu lệnh flock (gói util-linux) — không cài được."; exit 1; }
    if systemctl list-unit-files 2>/dev/null | grep -q '^hds-ai-quet-kho.timer'; then
      echo "Đã có hds-ai-quet-kho.timer (systemd) — không cài thêm cron để khỏi chạy hai lịch."
      exit 1
    fi
    me="$(id -un)"
    { go_cron_line "$me"; echo "$CRON_LINE"; } | cron_cmd "$me" -
    echo "✓ Đã bật lịch quét kho mỗi 3 phút (crontab của $me, không cần root)."
    echo "  Xem lịch         : crontab -l"
    echo "  Lượt gần nhất    : tail -n 40 $BACKEND_DIR/data/quet_kho.log"
    echo "  Lịch sử các lượt : tail $BACKEND_DIR/data/quet_kho_lich_su.log"
    echo "  Chạy ngay 1 lần  : bash deploy/hoc-tu-thu-muc.sh --cron"
    ;;
  --remove-cron)
    me="$(id -un)"
    go_cron_line "$me" | cron_cmd "$me" -
    echo "✓ Đã gỡ lịch cron quét kho của $me."
    ;;
  --cron)
    # Một lượt quét do cron gọi. Không có systemd lo hộ nên phải tự lo hai
    # việc: KHÔNG chạy chồng lượt trước (flock) và KHÔNG chen vào lượt quét
    # người dùng bấm từ web / chạy từ SSH (pgrep — cùng scanner, cùng bảng,
    # bài học 07/09/2026). Nhật ký mỗi lượt ghi đè data/quet_kho.log (thẻ
    # trạng thái trên web đọc đuôi tệp này); một dòng tổng kết nối vào
    # data/quet_kho_lich_su.log để còn xem lại các lượt trước.
    export LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONUNBUFFERED=1
    export PATH="/usr/local/bin:/usr/bin:/bin:$PATH"
    cd "$BACKEND_DIR"
    exec 9>"/tmp/hds-ai-quet-kho.lock"
    flock -n 9 || exit 0
    # Bộ quét thật đang chạy chỗ khác (cmdline kết thúc đúng ở app.local_learn;
    # --dry-run không tính) → nhường, 15 phút nữa cron gọi lại.
    pgrep -f 'python -m app\.local_learn$' >/dev/null 2>&1 && exit 0
    LOG="$BACKEND_DIR/data/quet_kho.log"
    HIST="$BACKEND_DIR/data/quet_kho_lich_su.log"
    mkdir -p "$BACKEND_DIR/data"
    start="$(date '+%Y-%m-%d %H:%M:%S')"
    rc=0
    .venv/bin/python -m app.local_learn > "$LOG" 2>&1 || rc=$?
    summary="$(grep -E ' mới \| ' "$LOG" | tail -n 1 || true)"
    echo "$start → $(date '+%H:%M:%S') rc=$rc ${summary:-(không có dòng tổng kết — xem quet_kho.log)}" >> "$HIST"
    exit "$rc"
    ;;
  *)
    cd "$BACKEND_DIR" && exec .venv/bin/python -m app.local_learn "$@"
    ;;
esac
