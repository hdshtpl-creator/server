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
c_warn() { printf '\033[33m  ! %s\033[0m\n' "$*"; }
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

c_info "1/5  Cập nhật thư viện Python"
run_as "cd '$BACKEND_DIR' && .venv/bin/pip install -q -r requirements.txt"
c_ok "Xong"

# Công cụ đọc tài liệu ở tầng hệ điều hành. setup.sh cài chúng cho máy MỚI,
# nhưng máy đã cài từ bản trước không tự có — update.sh phải bù, nếu không mọi
# PDF scan và file .doc cứ âm thầm rơi vào danh sách "không học được".
NEED_PKGS=""
command -v tesseract >/dev/null 2>&1 || NEED_PKGS="$NEED_PKGS tesseract-ocr"
tesseract --list-langs 2>/dev/null | grep -q '^vie$' || NEED_PKGS="$NEED_PKGS tesseract-ocr-vie"
command -v pdftoppm >/dev/null 2>&1 || NEED_PKGS="$NEED_PKGS poppler-utils"
# Ba gói LibreOffice, kiểm TỪNG cái: `soffice` có mặt chỉ chứng minh writer đã
# cài. Máy nâng cấp từ bản trước chỉ có writer, nên .xls/.ods (calc) và
# .ppt/.pptx/.odp (impress) sẽ báo "không chuyển được" khi người dùng kéo vào
# chat — đúng loại lỗi khó đoán vì soffice vẫn chạy.
dpkg -s libreoffice-writer >/dev/null 2>&1 || NEED_PKGS="$NEED_PKGS libreoffice-writer"
dpkg -s libreoffice-calc >/dev/null 2>&1 || NEED_PKGS="$NEED_PKGS libreoffice-calc"
dpkg -s libreoffice-impress >/dev/null 2>&1 || NEED_PKGS="$NEED_PKGS libreoffice-impress"
if [ -n "$NEED_PKGS" ]; then
  c_info "Cài công cụ đọc tài liệu còn thiếu:$NEED_PKGS"
  apt-get update -qq && apt-get install -y -qq $NEED_PKGS >/dev/null \
    && c_ok "Đã cài$NEED_PKGS" \
    || c_warn "Không cài được$NEED_PKGS — PDF scan / file Office cũ sẽ không đọc được"
fi

c_info "2/5  Cập nhật schema (bắt buộc chạy trước code mới)"
[ -f "$BACKEND_DIR/.env" ] || die "Thiếu $BACKEND_DIR/.env — không thể migrate an toàn"
# shellcheck disable=SC1090
set -a; . "$BACKEND_DIR/.env"; set +a
[ -n "${APP_DB_PASSWORD:-}" ] || die "Thiếu APP_DB_PASSWORD trong .env"
docker exec -i hds-postgres psql -U hds -d hdsai -v ON_ERROR_STOP=1 \
  -v app_pass="$APP_DB_PASSWORD" < "$BACKEND_DIR/sql/schema.sql" >/dev/null \
  || die "Migration schema thất bại — backend cũ vẫn được giữ nguyên"
c_ok "Schema đã đồng bộ"

c_info "3/5  Chạy kiểm tra backend"
run_as "cd '$BACKEND_DIR' && .venv/bin/python -m unittest discover -s tests -v" \
  || die "Backend test thất bại — không khởi động code mới"
c_ok "Backend tests đạt"

c_info "4/5  Build lại giao diện"
# Dấu bản build in vào giao diện (tooltip logo, hộp "Cấu hình kết nối", chân
# khung chat). Nhìn là biết tab đang chạy bản nào — hết cảnh "update rồi mà lỗi
# cũ còn nguyên" không phân biệt được tại trình duyệt giữ bản cũ hay tại mã.
BUILD_ID="$(run_as "git -C '$REPO_ROOT' rev-parse --short HEAD" 2>/dev/null || echo tay)-$(date +%d%m.%H%M)"
run_as "cd '$FRONTEND_DIR' && { [ -f package-lock.json ] && npm ci || npm install; } && VITE_BUILD_ID='$BUILD_ID' npm run build"
[ -f "$FRONTEND_DIR/dist/index.html" ] || die "Build frontend thất bại"
c_ok "Đã build bản $BUILD_ID"

c_info "5/5  Khởi động lại dịch vụ"

# Máy cài từ bản cũ có cấu hình nginx chưa tắt đệm. Không vá thì nginx gom cả
# câu trả lời rồi mới gửi, và tính năng trả lời chảy dần mất sạch tác dụng —
# FastAPI vẫn đẩy chữ ra đúng nhịp nhưng người dùng không thấy gì tới lúc xong.
NGINX_SITE="/etc/nginx/sites-available/hds-ai"
if [ -f "$NGINX_SITE" ] && ! grep -q "proxy_buffering" "$NGINX_SITE"; then
  cp "$NGINX_SITE" "$NGINX_SITE.bak.$(date +%Y%m%d%H%M%S)"
  sed -i '/proxy_send_timeout 320s;/a\        # Trả lời theo dòng (SSE): tắt đệm để chữ tới trình duyệt ngay.\n        proxy_buffering off;\n        proxy_cache off;' "$NGINX_SITE"
  if nginx -t >/dev/null 2>&1; then
    c_ok "Đã tắt đệm nginx cho tính năng trả lời chảy dần"
  else
    # Sai cú pháp thì trả lại nguyên trạng — thà không có streaming còn hơn
    # sập cả web vì nginx không khởi động được.
    cp "$(ls -t "$NGINX_SITE".bak.* | head -1)" "$NGINX_SITE"
    c_info "Không vá được nginx tự động — hãy thêm 'proxy_buffering off;' vào khối location /api/"
  fi
fi

# Deploy xong mà trình duyệt vẫn giữ index.html cũ → tải JS cũ → lỗi đã sửa
# "còn nguyên" (06/09/2026; Cloudflare còn gắn max-age 4 giờ cho JS). index.html
# phải luôn hỏi lại máy chủ; file trong /assets/ có mã băm trong tên nên giữ
# được cả năm. Chèn trước khối `location /` bằng awk để giữ nguyên thụt dòng
# và chỉ chèn MỘT lần (file có certbot sửa có thể có hai khối server).
CACHE_BLOCK='    # index.html không cache (deploy là thấy ngay); /assets/ băm tên nên bất biến.
    location = /index.html {
        add_header Cache-Control "no-cache, must-revalidate";
    }
    location /assets/ {
        add_header Cache-Control "public, max-age=31536000, immutable";
        try_files $uri =404;
    }
'
if [ -f "$NGINX_SITE" ] && ! grep -q "Cache-Control" "$NGINX_SITE"; then
  cp "$NGINX_SITE" "$NGINX_SITE.bak.$(date +%Y%m%d%H%M%S)"
  awk -v blk="$CACHE_BLOCK" '
    /^[[:space:]]*location \/ \{/ && !done { printf "%s", blk; done = 1 }
    { print }
  ' "$NGINX_SITE" > "$NGINX_SITE.tmp" && mv "$NGINX_SITE.tmp" "$NGINX_SITE"
  if nginx -t >/dev/null 2>&1; then
    c_ok "Đã thêm header chống cache cho index.html"
  else
    cp "$(ls -t "$NGINX_SITE".bak.* | head -1)" "$NGINX_SITE"
    c_warn "Không vá được nginx tự động — chép tay khối 'location = /index.html' từ deploy/setup.sh"
  fi
fi

systemctl restart hds-ai-backend
systemctl reload nginx
sleep 2
systemctl is-active --quiet hds-ai-backend \
  && c_ok "Backend đang chạy" \
  || die "Backend lỗi — xem: journalctl -u hds-ai-backend -n 40 --no-pager"

# Danh tính văn bản luật (số hiệu/quan hệ/hiệu lực) chỉ tự bóc khi file được
# học MỚI. Kho đã học từ trước phải backfill một lần — 06/09/2026 phát hiện
# 65/65 văn bản luật so_hieu=NULL, bảng quan hệ trống, tức toàn bộ cơ chế
# "luật sau sửa luật trước" bất động suốt một tuần mà không ai biết. Không tự
# chạy ở đây (đọc lại file + embed lại đoạn mất hàng chục phút), chỉ đếm và
# nhắc to.
CHUA_DANH_TINH="$(docker exec -i hds-postgres psql -U hds -d hdsai -At -c \
  "SELECT count(*) FROM documents WHERE doc_type='law' AND so_hieu IS NULL AND coalesce(active,true)" 2>/dev/null || echo '?')"
if [ "$CHUA_DANH_TINH" != "0" ]; then
  c_warn "Còn $CHUA_DANH_TINH văn bản luật CHƯA có danh tính (số hiệu/quan hệ/hiệu lực)."
  c_warn "Chạy một lần (không cần sudo):  cd $BACKEND_DIR && .venv/bin/python -m app.backfill_van_ban --lam-lai-doan"
fi

echo
c_ok "CẬP NHẬT XONG."
