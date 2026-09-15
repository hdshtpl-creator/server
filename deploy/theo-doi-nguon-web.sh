#!/usr/bin/env bash
# theo-doi-nguon-web.sh — Bộ quét theo dõi NGUỒN VĂN BẢN TRÊN MẠNG (app.web_watch).
#
# Nó chỉ TẢI FILE về đúng thư mục kho. Việc học (bóc chữ, OCR, tách theo Điều,
# vào hàng chờ duyệt) vẫn do bộ quét kho làm — deploy/hoc-tu-thu-muc.sh. Hai
# lịch tách nhau là có chủ ý: trang nguồn ra văn bản mới vài lần một ngày,
# không đáng gõ cửa 15 phút một lần.
#
# Trước khi bật: thêm nguồn ở web → Cài đặt AI → 'web_sources' (mặc định trống,
# không nguồn nào bật). Thử trước bằng --dry-run để xem nó nhặt ra những link
# nào mà chưa tải gì cả.
#
# Chạy:
#   bash deploy/theo-doi-nguon-web.sh                      # quét và tải ngay
#   bash deploy/theo-doi-nguon-web.sh --dry-run            # chỉ liệt kê
#   bash deploy/theo-doi-nguon-web.sh --nguon "Công báo"   # một nguồn
#   sudo bash deploy/theo-doi-nguon-web.sh --install-timer # tự chạy mỗi 6 giờ
#   sudo bash deploy/theo-doi-nguon-web.sh --remove-timer
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "$SCRIPT_DIR/../hds-ai" && pwd)"
SERVICE_USER="${SUDO_USER:-$(stat -c '%U' "$BACKEND_DIR")}"

case "${1:-}" in
  --install-timer)
    [ "$(id -u)" = 0 ] || { echo "Cần quyền root: sudo bash deploy/theo-doi-nguon-web.sh --install-timer"; exit 1; }
    cat > /etc/systemd/system/hds-ai-nguon-web.service <<EOF
[Unit]
Description=HDS AI - theo doi nguon van ban tren mang va tai file moi ve kho
After=network-online.target hds-ai-backend.service

[Service]
Type=oneshot
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$BACKEND_DIR
ExecStart=$BACKEND_DIR/.venv/bin/python -m app.web_watch
EOF
    cat > /etc/systemd/system/hds-ai-nguon-web.timer <<EOF
[Unit]
Description=HDS AI - theo doi nguon van ban tren mang dinh ky

[Timer]
OnBootSec=10min
OnUnitActiveSec=6h
Persistent=true
RandomizedDelaySec=10min

[Install]
WantedBy=timers.target
EOF
    systemctl daemon-reload
    systemctl enable --now hds-ai-nguon-web.timer
    echo "✓ Đã bật lịch theo dõi nguồn web mỗi 6 giờ."
    echo "  Xem lần chạy tới : systemctl list-timers hds-ai-nguon-web.timer"
    echo "  Xem log          : journalctl -u hds-ai-nguon-web.service -n 40 --no-pager"
    echo "  Chạy ngay 1 lần  : sudo systemctl start hds-ai-nguon-web.service"
    echo
    echo "  Nhớ: file tải về CHƯA vào kho tri thức cho tới khi bộ quét kho chạy"
    echo "  (hds-ai-quet-kho.timer), và sau đó vẫn nằm ở hàng CHỜ DUYỆT."
    ;;
  --remove-timer)
    [ "$(id -u)" = 0 ] || { echo "Cần quyền root."; exit 1; }
    systemctl disable --now hds-ai-nguon-web.timer 2>/dev/null || true
    rm -f /etc/systemd/system/hds-ai-nguon-web.service /etc/systemd/system/hds-ai-nguon-web.timer
    systemctl daemon-reload
    echo "✓ Đã gỡ lịch theo dõi nguồn web."
    ;;
  *)
    cd "$BACKEND_DIR" && exec .venv/bin/python -m app.web_watch "$@"
    ;;
esac
