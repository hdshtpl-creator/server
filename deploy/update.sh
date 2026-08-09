#!/usr/bin/env bash
# ====================================================================
# HDS AI — Cập nhật sau khi đã git pull mã mới.
# Cài lại thư viện, build lại giao diện, khởi động lại backend, reload nginx.
#
#   cd hds-ai-full
#   git pull
#   sudo bash deploy/update.sh
# ====================================================================
set -euo pipefail

c_ok()   { printf '\033[32m  ✓ %s\033[0m\n' "$*"; }
c_info() { printf '\033[36m» %s\033[0m\n' "$*"; }
die()    { printf '\033[31m  ✗ %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Hãy chạy bằng quyền root:  sudo bash deploy/update.sh"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$REPO_ROOT/hds-ai"
FRONTEND_DIR="$REPO_ROOT/hds-ai-assistant"

SERVICE_USER="${SUDO_USER:-}"
[ -z "$SERVICE_USER" ] && SERVICE_USER="$(stat -c '%U' "$REPO_ROOT")"
if [ "$SERVICE_USER" = "root" ]; then
  run_as() { bash -c "$1"; }
else
  run_as() { sudo -u "$SERVICE_USER" bash -c "$1"; }
fi

c_info "1/4  Cập nhật thư viện Python"
run_as "cd '$BACKEND_DIR' && .venv/bin/pip install -q -r requirements.txt"
c_ok "Xong"

c_info "2/4  Cập nhật schema (an toàn, chỉ thêm cái còn thiếu)"
if [ -f "$BACKEND_DIR/.env" ]; then
  # shellcheck disable=SC1090
  set -a; . "$BACKEND_DIR/.env"; set +a
  docker exec -i hds-postgres psql -U hds -d hdsai -v ON_ERROR_STOP=1 \
    -v app_pass="${APP_DB_PASSWORD:-}" < "$BACKEND_DIR/sql/schema.sql" >/dev/null \
    && c_ok "Schema đã đồng bộ" || c_info "Bỏ qua cập nhật schema"
fi

c_info "3/4  Build lại giao diện"
run_as "cd '$FRONTEND_DIR' && { [ -f package-lock.json ] && npm ci || npm install; } && npm run build"
[ -f "$FRONTEND_DIR/dist/index.html" ] || die "Build frontend thất bại"
c_ok "Đã build"

c_info "4/4  Khởi động lại dịch vụ"
systemctl restart hds-ai-backend
systemctl reload nginx
sleep 2
systemctl is-active --quiet hds-ai-backend \
  && c_ok "Backend đang chạy" \
  || die "Backend lỗi — xem: journalctl -u hds-ai-backend -n 40 --no-pager"

echo
c_ok "CẬP NHẬT XONG."
