#!/usr/bin/env bash
# hoc-tu-thu-muc.sh — Bot học tài liệu từ THƯ MỤC TRÊN MÁY CHỦ (app.local_learn).
#
# Thay deploy/auto-learn.sh sau khi bỏ Google Drive (quyết định 27/08/2026).
#
# Chạy:
#   bash deploy/hoc-tu-thu-muc.sh                 # quét và học ngay
#   bash deploy/hoc-tu-thu-muc.sh --dry-run       # chỉ liệt kê, không ghi gì
#   bash deploy/hoc-tu-thu-muc.sh --chuyen-doi    # MỘT LẦN khi vừa bỏ Drive
#   sudo bash deploy/hoc-tu-thu-muc.sh --install-timer   # quét mỗi 15 phút
#   sudo bash deploy/hoc-tu-thu-muc.sh --remove-timer
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "$SCRIPT_DIR/../hds-ai" && pwd)"
SERVICE_USER="${SUDO_USER:-$(stat -c '%U' "$BACKEND_DIR")}"

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
OnUnitActiveSec=15min
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
    echo "✓ Đã bật lịch quét kho mỗi 15 phút."
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
  *)
    cd "$BACKEND_DIR" && exec .venv/bin/python -m app.local_learn "$@"
    ;;
esac
