#!/usr/bin/env bash
# luu-tru-drive.sh — Kéo TOÀN BỘ Google Drive của HDS về máy chủ làm KHO LƯU TRỮ.
#
# Vì sao cần khi đã có auto_learn (bot tự học 15 phút/lần)?
#   auto_learn chỉ tải các định dạng bot ĐỌC được (.docx .pdf .xlsx ảnh…) và có
#   trần dung lượng mỗi file — nó là cái GƯƠNG PHỤC VỤ HỌC, không phải bản lưu
#   trữ. Script này mirror MỌI file, mọi định dạng, không trần — đúng yêu cầu
#   "chuyển tất cả từ Drive về local" (26/08/2026). Hai tầng độc lập:
#     data/raw/        ← auto_learn — file bot học (đừng đụng)
#     /data/archive/   ← script này — bản lưu trữ đầy đủ (đổi bằng ARCHIVE_DIR)
#
# Dùng chung service account với auto_learn (credentials/service-account.json,
# quyền Viewer trên thư mục gốc) — KHÔNG cần rclone config.
#
# Chạy:
#   bash deploy/luu-tru-drive.sh                # mirror một lần
#   bash deploy/luu-tru-drive.sh --thu          # xem sẽ tải gì, không ghi
#   bash deploy/luu-tru-drive.sh --install-timer   # hẹn giờ hằng đêm 01:30
#   bash deploy/luu-tru-drive.sh --remove-timer
#
# LƯU Ý DUNG LƯỢNG: kế hoạch gốc đã dặn ổ 512GB sẽ chật — kho lưu trữ nên đặt
# trên ổ gắn thêm (ARCHIVE_DIR=/mnt/data2/archive bash deploy/luu-tru-drive.sh).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "$SCRIPT_DIR/../hds-ai" && pwd)"
ARCHIVE_DIR="${ARCHIVE_DIR:-/data/archive}"
LOG_TAG="hds-luu-tru"

# Đọc DRIVE_FOLDER_ID + DRIVE_SA_FILE từ .env của backend — một nguồn cấu hình.
# `|| true`: thiếu dòng thì grep exit 1, mà set -e -o pipefail sẽ giết script
# CÂM LẶNG ngay tại phép gán — phải để rơi xuống thông báo lỗi tử tế bên dưới.
ENV_FILE="$BACKEND_DIR/.env"
[ -f "$ENV_FILE" ] || { echo "[LỖI] Không thấy $ENV_FILE"; exit 1; }
FOLDER_ID="$(grep -E '^DRIVE_FOLDER_ID=' "$ENV_FILE" | tail -1 | cut -d= -f2- | tr -d '"' | tr -d "'" || true)"
SA_REL="$(grep -E '^DRIVE_SA_FILE=' "$ENV_FILE" | tail -1 | cut -d= -f2- | tr -d '"' | tr -d "'" || true)"
SA_FILE="$BACKEND_DIR/${SA_REL:-credentials/service-account.json}"
[ -n "$FOLDER_ID" ] || { echo "[LỖI] Chưa đặt DRIVE_FOLDER_ID trong .env"; exit 1; }
[ -f "$SA_FILE" ] || { echo "[LỖI] Không thấy khoá service account: $SA_FILE"; exit 1; }

if ! command -v rclone >/dev/null 2>&1; then
  echo "[LỖI] Chưa cài rclone. Cài bằng:  sudo apt-get install -y rclone"
  exit 1
fi

# Remote tại chỗ, không cần rclone config. Tham số truyền bằng cờ --drive-*
# thay vì chuỗi ":drive,key=val:" — cú pháp chuỗi cần rclone ≥1.55, còn bản
# apt của Ubuntu 22.04 là 1.53. scope drive.readonly — chỉ đọc.
REMOTE=":drive:"

# `copy` chứ KHÔNG `sync`: file bị xoá nhầm trên Drive vẫn còn trong kho lưu
# trữ — đây là bản phòng thân, không phải bản sao y hiện trạng.
RCLONE_ARGS=(copy "$REMOTE" "$ARCHIVE_DIR"
  --drive-scope drive.readonly
  --drive-service-account-file "$SA_FILE"
  --drive-root-folder-id "$FOLDER_ID"
  --drive-export-formats docx,xlsx,pptx   # Google Docs/Sheets/Slides → Office
  --create-empty-src-dirs                 # giữ cả thư mục rỗng cho đủ cây
  --transfers 4 --checkers 8
  --log-level INFO)

case "${1:-}" in
  --thu)
    rclone "${RCLONE_ARGS[@]}" --dry-run
    ;;
  --install-timer)
    [ "$(id -u)" = 0 ] || { echo "Cần sudo để cài timer."; exit 1; }
    cat > /etc/systemd/system/hds-luu-tru.service <<EOF
[Unit]
Description=HDS - mirror toan bo Drive ve kho luu tru local
After=network-online.target

[Service]
Type=oneshot
Environment=ARCHIVE_DIR=$ARCHIVE_DIR
ExecStart=/usr/bin/env bash $SCRIPT_DIR/luu-tru-drive.sh
EOF
    cat > /etc/systemd/system/hds-luu-tru.timer <<EOF
[Unit]
Description=HDS - luu tru Drive hang dem

[Timer]
OnCalendar=*-*-* 01:30:00
Persistent=true

[Install]
WantedBy=timers.target
EOF
    systemctl daemon-reload
    systemctl enable --now hds-luu-tru.timer
    echo "Đã hẹn giờ mirror hằng đêm 01:30. Xem lịch: systemctl list-timers hds-luu-tru*"
    ;;
  --remove-timer)
    [ "$(id -u)" = 0 ] || { echo "Cần sudo để gỡ timer."; exit 1; }
    systemctl disable --now hds-luu-tru.timer 2>/dev/null || true
    rm -f /etc/systemd/system/hds-luu-tru.service /etc/systemd/system/hds-luu-tru.timer
    systemctl daemon-reload
    echo "Đã gỡ timer lưu trữ."
    ;;
  "")
    mkdir -p "$ARCHIVE_DIR"
    echo ">> Mirror Drive ($FOLDER_ID) → $ARCHIVE_DIR"
    rclone "${RCLONE_ARGS[@]}"
    echo ">> Xong. Dung lượng kho lưu trữ: $(du -sh "$ARCHIVE_DIR" 2>/dev/null | cut -f1)"
    df -h "$ARCHIVE_DIR" | tail -1 | awk '{print ">> Ổ chứa còn trống: " $4}'
    ;;
  *)
    echo "Cách dùng: bash deploy/luu-tru-drive.sh [--thu | --install-timer | --remove-timer]"
    exit 1
    ;;
esac
