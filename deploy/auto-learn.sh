#!/usr/bin/env bash
# ====================================================================
# HDS AI — Chạy "bot tự học từ Drive" (app.auto_learn).
#
#   bash deploy/auto-learn.sh                 # học ngay 1 lần
#   bash deploy/auto-learn.sh --dry-run       # chỉ liệt kê, không ghi
#   sudo bash deploy/auto-learn.sh --install-timer   # cài chạy tự động mỗi 15'
#   sudo bash deploy/auto-learn.sh --remove-timer    # gỡ lịch tự động
# ====================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "$SCRIPT_DIR/../hds-ai" && pwd)"
SERVICE_USER="${SUDO_USER:-$(stat -c '%U' "$BACKEND_DIR")}"

install_timer() {
  [ "$(id -u)" -eq 0 ] || { echo "Cần quyền root: sudo bash deploy/auto-learn.sh --install-timer"; exit 1; }
  cat > /etc/systemd/system/hds-ai-learn.service <<EOF
[Unit]
Description=HDS AI - tự học tài liệu từ Google Drive
After=network-online.target hds-ai-backend.service

[Service]
Type=oneshot
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$BACKEND_DIR
ExecStart=$BACKEND_DIR/.venv/bin/python -m app.auto_learn
EOF
  cat > /etc/systemd/system/hds-ai-learn.timer <<EOF
[Unit]
Description=Chạy bot tự học Drive mỗi 15 phút

[Timer]
OnBootSec=3min
OnUnitActiveSec=15min
Persistent=true

[Install]
WantedBy=timers.target
EOF
  systemctl daemon-reload
  systemctl enable --now hds-ai-learn.timer
  echo "✓ Đã bật lịch tự học mỗi 15 phút."
  echo "  Xem lần chạy tới : systemctl list-timers hds-ai-learn.timer"
  echo "  Xem log          : journalctl -u hds-ai-learn.service -n 40 --no-pager"
  echo "  Chạy ngay 1 lần  : sudo systemctl start hds-ai-learn.service"
}

remove_timer() {
  [ "$(id -u)" -eq 0 ] || { echo "Cần quyền root."; exit 1; }
  systemctl disable --now hds-ai-learn.timer 2>/dev/null || true
  rm -f /etc/systemd/system/hds-ai-learn.timer /etc/systemd/system/hds-ai-learn.service
  systemctl daemon-reload
  echo "✓ Đã gỡ lịch tự học."
}

case "${1:-}" in
  --install-timer) install_timer ;;
  --remove-timer)  remove_timer ;;
  *)               cd "$BACKEND_DIR" && exec .venv/bin/python -m app.auto_learn "$@" ;;
esac
