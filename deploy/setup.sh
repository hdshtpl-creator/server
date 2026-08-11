#!/usr/bin/env bash
# ====================================================================
# HDS AI — Cài đặt & triển khai TRỌN GÓI trên MỘT máy chủ Ubuntu.
#
#   nginx  : phục vụ giao diện tĩnh (hds-ai-assistant/dist)
#            + reverse-proxy /api  ->  FastAPI 127.0.0.1:8000
#   backend: uvicorn chạy bằng systemd (app.api:app trong hds-ai/)
#   CSDL   : PostgreSQL + pgvector qua docker compose (hds-ai/)
#
# Chạy MỘT LẦN (từ thư mục gốc repo):
#     sudo bash deploy/setup.sh
#
# Chạy lại nhiều lần đều an toàn (không xoay lại mật khẩu đã sinh).
# ====================================================================
set -euo pipefail

# ---------- Tiện ích in ----------
c_ok()   { printf '\033[32m  ✓ %s\033[0m\n' "$*"; }
c_info() { printf '\033[36m» %s\033[0m\n' "$*"; }
c_warn() { printf '\033[33m  ! %s\033[0m\n' "$*"; }
c_err()  { printf '\033[31m  ✗ %s\033[0m\n' "$*" >&2; }
die()    { c_err "$*"; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Hãy chạy bằng quyền root:  sudo bash deploy/setup.sh"

# ---------- 0. Xác định đường dẫn & người dùng dịch vụ ----------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$REPO_ROOT/hds-ai"
FRONTEND_DIR="$REPO_ROOT/hds-ai-assistant"
DEPLOY_ENV="$SCRIPT_DIR/deploy.env"

[ -d "$BACKEND_DIR" ]  || die "Không thấy thư mục backend: $BACKEND_DIR"
[ -d "$FRONTEND_DIR" ] || die "Không thấy thư mục frontend: $FRONTEND_DIR"

# Người sẽ sở hữu tiến trình backend (không chạy web bằng root).
SERVICE_USER="${SUDO_USER:-}"
[ -z "$SERVICE_USER" ] && SERVICE_USER="$(stat -c '%U' "$REPO_ROOT")"
[ -z "$SERVICE_USER" ] && SERVICE_USER="root"

if [ "$SERVICE_USER" = "root" ]; then
  run_as() { bash -c "$1"; }
else
  run_as() { sudo -u "$SERVICE_USER" bash -c "$1"; }
fi

c_info "Thư mục repo   : $REPO_ROOT"
c_info "Chạy backend bằng người dùng: $SERVICE_USER"

# ---------- 1. Cấu hình domain ----------
DOMAIN="${DOMAIN:-}"
LETSENCRYPT_EMAIL="${LETSENCRYPT_EMAIL:-}"
if [ -f "$DEPLOY_ENV" ]; then
  # shellcheck disable=SC1090
  set -a; . "$DEPLOY_ENV"; set +a
fi
if [ -z "${DOMAIN}${CI:-}" ] && [ ! -f "$DEPLOY_ENV" ]; then
  echo
  c_info "Cấu hình tên miền (Enter để bỏ trống = chạy bằng IP, chỉ HTTP)"
  read -rp "  Tên miền đã trỏ về máy chủ này (vd app.hdslaw.vn): " DOMAIN || true
  if [ -n "$DOMAIN" ]; then
    read -rp "  Email cho chứng chỉ HTTPS Let's Encrypt: " LETSENCRYPT_EMAIL || true
  fi
  printf 'DOMAIN=%s\nLETSENCRYPT_EMAIL=%s\n' "$DOMAIN" "$LETSENCRYPT_EMAIL" > "$DEPLOY_ENV"
  chown "$SERVICE_USER":"$SERVICE_USER" "$DEPLOY_ENV" 2>/dev/null || true
fi

if [ -n "$DOMAIN" ]; then
  SERVER_NAME="$DOMAIN"
  c_info "Tên miền: $DOMAIN  (sẽ cấp HTTPS nếu DNS đã trỏ đúng)"
else
  SERVER_NAME="_"
  c_warn "Không có tên miền — phục vụ bằng IP qua HTTP. Chỉ nên dùng trong mạng nội bộ."
fi

# ---------- 2. Gói hệ thống ----------
c_info "2/8  Cài gói hệ thống cần thiết"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq ca-certificates curl gnupg openssl \
  python3-venv python3-pip postgresql-client nginx >/dev/null
c_ok "python3-venv, nginx, postgresql-client, openssl"

# Docker
if ! command -v docker >/dev/null 2>&1; then
  c_info "     Cài Docker Engine..."
  curl -fsSL https://get.docker.com | sh >/dev/null
fi
docker compose version >/dev/null 2>&1 || die "Thiếu 'docker compose' (Docker Compose v2)."
c_ok "Docker $(docker --version | awk '{print $3}' | tr -d ,)"
# Cho người dùng dịch vụ dùng docker ở các lần chạy sau (phiên này vẫn dùng root)
[ "$SERVICE_USER" != "root" ] && usermod -aG docker "$SERVICE_USER" 2>/dev/null || true

# Node.js 20 (frontend cần >= 20)
NODE_MAJOR="$(command -v node >/dev/null 2>&1 && node -p 'process.versions.node.split(".")[0]' || echo 0)"
if [ "$NODE_MAJOR" -lt 20 ]; then
  c_info "     Cài Node.js 20..."
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash - >/dev/null
  apt-get install -y -qq nodejs >/dev/null
fi
c_ok "Node.js $(node --version)"

# Certbot (chỉ khi có domain)
if [ -n "$DOMAIN" ] && ! command -v certbot >/dev/null 2>&1; then
  apt-get install -y -qq certbot python3-certbot-nginx >/dev/null
  c_ok "certbot"
fi

# ---------- 3. Sinh / vá .env backend ----------
c_info "3/8  Cấu hình bí mật backend"
BACKEND_ENV="$BACKEND_DIR/.env"
gen_hex() { openssl rand -hex 24; }   # 48 ký tự 0-9a-f (an toàn cho mọi nơi)
gen_jwt() { openssl rand -hex 32; }   # 64 ký tự 0-9a-f (>= 32, không ký tự đặc biệt)

# JWT yếu nếu: rỗng, dưới 32 ký tự, hoặc còn là chuỗi mẫu.
is_weak_jwt() {
  local v="$1"
  [ -z "$v" ] && return 0
  [ "${#v}" -lt 32 ] && return 0
  case "$v" in *doi_*|*change_me*) return 0 ;; esac
  return 1
}

if [ -f "$BACKEND_ENV" ]; then
  # Máy đã cài sẵn: TUYỆT ĐỐI không đổi mật khẩu CSDL (phải khớp dữ liệu cũ),
  # chỉ vá JWT_SECRET nếu còn yếu — đây là chỗ khiến bản mã mới từ chối đăng nhập.
  c_ok "Đã có $BACKEND_ENV — giữ nguyên mật khẩu CSDL đang khớp với dữ liệu."
  cur_jwt="$(sed -n 's/^JWT_SECRET=//p' "$BACKEND_ENV" | head -1)"
  if is_weak_jwt "$cur_jwt"; then
    new_jwt="$(gen_jwt)"
    if grep -qE '^JWT_SECRET=' "$BACKEND_ENV"; then
      sed -i "s|^JWT_SECRET=.*|JWT_SECRET=$new_jwt|" "$BACKEND_ENV"
    else
      printf '\nJWT_SECRET=%s\n' "$new_jwt" >> "$BACKEND_ENV"
    fi
    c_warn "JWT_SECRET cũ yếu/để mặc định → đã thay bằng khoá ngẫu nhiên mạnh."
    c_warn "Mọi người cần đăng nhập lại (bình thường)."
  else
    c_ok "JWT_SECRET hiện tại đủ mạnh — giữ nguyên."
  fi
  grep -qE '^CORS_ORIGINS=' "$BACKEND_ENV" || printf 'CORS_ORIGINS=\n' >> "$BACKEND_ENV"
else
  DB_PW="$(gen_hex)"; APP_PW="$(gen_hex)"; JWT="$(gen_jwt)"
  cat > "$BACKEND_ENV" <<EOF
# Sinh tự động bởi deploy/setup.sh — KHÔNG commit tệp này.
DB_HOST=localhost
DB_PORT=5432
DB_NAME=hdsai
DB_USER=hds
DB_PASSWORD=$DB_PW
APP_DB_USER=hds_app
APP_DB_PASSWORD=$APP_PW

OLLAMA_URL=http://localhost:11434
LLM_MODEL=qwen3:8b
EMBED_MODEL=bge-m3
EMBED_DIM=1024

OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o-mini

DATA_RAW=./data/raw
DATA_WORK=./data/work

JWT_SECRET=$JWT
TOKEN_HOURS=12

# Cùng một máy chủ (nginx proxy /api) nên không cần CORS.
CORS_ORIGINS=
EOF
  chown "$SERVICE_USER":"$SERVICE_USER" "$BACKEND_ENV"
  chmod 600 "$BACKEND_ENV"
  c_ok "Đã sinh $BACKEND_ENV (mật khẩu CSDL + JWT ngẫu nhiên)."
fi
mkdir -p "$BACKEND_DIR/data/raw" "$BACKEND_DIR/data/work" "$BACKEND_DIR/logs"
chown -R "$SERVICE_USER":"$SERVICE_USER" "$BACKEND_DIR/data" "$BACKEND_DIR/logs" 2>/dev/null || true

# ---------- 4. PostgreSQL + pgvector ----------
c_info "4/8  Khởi động PostgreSQL (docker compose)"
( cd "$BACKEND_DIR" && docker compose up -d )
for i in $(seq 1 30); do
  if docker exec hds-postgres pg_isready -U hds -d hdsai >/dev/null 2>&1; then
    c_ok "CSDL sẵn sàng."; break
  fi
  sleep 2
  [ "$i" -eq 30 ] && die "PostgreSQL không lên sau 60s. Xem: docker compose -f $BACKEND_DIR/docker-compose.yml logs"
done

# ---------- 5. Môi trường Python + nạp schema + seed ----------
c_info "5/8  Cài thư viện Python & nạp CSDL"
# requirements.txt đi kèm repo là nguồn chuẩn; chỉ sinh dự phòng nếu thiếu.
if [ ! -f "$BACKEND_DIR/requirements.txt" ]; then
  cat > "$BACKEND_DIR/requirements.txt" <<'REQ'
psycopg[binary]==3.2.3
python-dotenv==1.0.1
requests==2.32.3
python-docx==1.1.2
pypdf==5.1.0
pdfplumber==0.11.4
pytesseract==0.3.13
pdf2image==1.17.0
Pillow==11.0.0
fastapi==0.115.6
uvicorn[standard]==0.34.0
python-multipart==0.0.20
pydantic==2.10.4
bcrypt==4.2.1
PyJWT==2.10.1
google-api-python-client==2.156.0
google-auth==2.37.0
REQ
  chown "$SERVICE_USER":"$SERVICE_USER" "$BACKEND_DIR/requirements.txt"
fi

run_as "cd '$BACKEND_DIR' && { [ -d .venv ] || python3 -m venv .venv; } && \
        .venv/bin/pip install -q --upgrade pip && \
        .venv/bin/pip install -q -r requirements.txt"
c_ok "Đã cài thư viện Python vào .venv"

# Nạp schema bằng quyền root (docker exec), mật khẩu vai hds_app truyền qua -v.
# shellcheck disable=SC1090
set -a; . "$BACKEND_ENV"; set +a
docker exec -i hds-postgres psql -U hds -d hdsai -v ON_ERROR_STOP=1 \
  -v app_pass="$APP_DB_PASSWORD" < "$BACKEND_DIR/sql/schema.sql" >/dev/null
c_ok "Đã nạp schema + RLS"

# Đồng bộ mật khẩu vai hds_app với .env. CSDL tạo từ bản cũ có thể đặt mật khẩu
# hds_app khác với .env (khiến truy vấn RLS/chat lỗi dù đăng nhập vẫn chạy vì
# đăng nhập đi bằng vai admin). ALTER ở đây bảo đảm luôn khớp.
docker exec -i hds-postgres psql -U hds -d hdsai -v ON_ERROR_STOP=1 \
  -v app_pass="$APP_DB_PASSWORD" \
  -c "ALTER ROLE hds_app WITH LOGIN PASSWORD :'app_pass'" >/dev/null 2>&1 \
  && c_ok "Mật khẩu vai hds_app đã khớp .env" \
  || c_warn "Không ALTER được hds_app (bỏ qua nếu vai chưa tồn tại)"

# Seed phòng ban + tài khoản (chạy bằng người dùng dịch vụ, kết nối DB qua TCP).
run_as "cd '$BACKEND_DIR' && .venv/bin/python -m app.seed_departments" >/dev/null 2>&1 \
  && c_ok "Đã nạp 4 bộ phận + ma trận quyền" \
  || c_warn "seed_departments báo lỗi (có thể đã nạp trước đó) — bỏ qua"

SEED_OUT="$(run_as "cd '$BACKEND_DIR' && .venv/bin/python -m app.seed_accounts" 2>&1 || true)"
echo "$SEED_OUT" | grep -q hdslaw.vn && c_ok "Đã tạo tài khoản đăng nhập demo" \
  || c_warn "seed_accounts: $(echo "$SEED_OUT" | tail -1)"

# ---------- 6. systemd cho backend ----------
c_info "6/8  Cài dịch vụ systemd cho backend"
SERVICE_FILE="/etc/systemd/system/hds-ai-backend.service"
cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=HDS AI Backend (FastAPI / uvicorn)
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$BACKEND_DIR
ExecStart=$BACKEND_DIR/.venv/bin/uvicorn app.api:app --host 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable hds-ai-backend >/dev/null 2>&1 || true
# Nhường cổng 8000: dừng dịch vụ cũ + uvicorn chạy tay (nếu có) trước khi khởi động.
systemctl stop hds-ai-backend >/dev/null 2>&1 || true
pkill -f 'uvicorn app.api' 2>/dev/null || true
sleep 1
systemctl start hds-ai-backend
sleep 3
if curl -fsS --max-time 10 http://127.0.0.1:8000/health >/dev/null 2>&1; then
  c_ok "Backend phản hồi /health (127.0.0.1:8000)"
elif systemctl is-active --quiet hds-ai-backend; then
  c_warn "Tiến trình chạy nhưng /health chưa phản hồi — xem: journalctl -u hds-ai-backend -n 40 --no-pager"
else
  c_err "Backend chưa chạy. Xem log: journalctl -u hds-ai-backend -n 40 --no-pager"
fi

# ---------- 7. Build frontend ----------
c_info "7/8  Build giao diện (npm)"
run_as "cd '$FRONTEND_DIR' && { [ -f package-lock.json ] && npm ci || npm install; } && npm run build"
[ -f "$FRONTEND_DIR/dist/index.html" ] || die "Build frontend thất bại — không thấy dist/index.html"
c_ok "Đã build vào $FRONTEND_DIR/dist"

# ---------- 8. nginx ----------
c_info "8/8  Cấu hình nginx"
NGINX_SITE="/etc/nginx/sites-available/hds-ai"
cat > "$NGINX_SITE" <<'NGINX'
server {
    listen 80;
    listen [::]:80;
    server_name __SERVER_NAME__;

    root __FRONTEND_DIST__;
    index index.html;

    # Nội dung tải lên gửi trong thân JSON; giao diện giới hạn 2MB.
    client_max_body_size 5m;

    # Chuyển /api/* sang FastAPI, cắt bỏ tiền tố /api (nhờ dấu '/' cuối proxy_pass).
    location /api/ {
        proxy_pass http://127.0.0.1:8000/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        # Tra cứu RAG gọi Ollama có thể mất tới ~300s.
        proxy_read_timeout 320s;
        proxy_send_timeout 320s;
    }

    # SPA: mọi đường dẫn khác trả về index.html để React tự định tuyến.
    location / {
        try_files $uri $uri/ /index.html;
    }
}
NGINX
sed -i "s|__SERVER_NAME__|$SERVER_NAME|g; s|__FRONTEND_DIST__|$FRONTEND_DIR/dist|g" "$NGINX_SITE"

ln -sf "$NGINX_SITE" /etc/nginx/sites-enabled/hds-ai
rm -f /etc/nginx/sites-enabled/default
nginx -t >/dev/null 2>&1 || die "Cấu hình nginx sai — kiểm tra: nginx -t"
systemctl reload nginx
c_ok "nginx đã phục vụ giao diện + proxy /api"

case "$FRONTEND_DIR" in
  /root/*) c_warn "Repo nằm trong /root — nginx (www-data) thường KHÔNG đọc được, dễ báo 403." ;
           c_warn "Nên đặt repo ở /home/$SERVICE_USER/ hoặc /opt/ rồi chạy lại." ;;
esac

# HTTPS
if [ -n "$DOMAIN" ] && [ -n "$LETSENCRYPT_EMAIL" ]; then
  c_info "Xin chứng chỉ HTTPS cho $DOMAIN ..."
  if certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos \
       -m "$LETSENCRYPT_EMAIL" --redirect >/dev/null 2>&1; then
    c_ok "HTTPS đã bật (tự gia hạn qua certbot.timer)."
  else
    c_warn "Chưa cấp được HTTPS. Thường do DNS của $DOMAIN chưa trỏ về máy chủ này."
    c_warn "Trỏ DNS xong chạy lại:  sudo certbot --nginx -d $DOMAIN"
  fi
elif [ -n "$DOMAIN" ]; then
  c_warn "Có domain nhưng thiếu email — bỏ qua HTTPS. Chạy: sudo certbot --nginx -d $DOMAIN"
fi

# ---------- Ollama (chỉ cảnh báo) ----------
if ! curl -s --max-time 3 http://localhost:11434/api/tags >/dev/null 2>&1; then
  echo
  c_warn "Ollama chưa chạy — ĐĂNG NHẬP và phần Quản trị vẫn hoạt động, nhưng HỎI ĐÁP AI sẽ lỗi."
  c_warn "Cài & tải model:  curl -fsSL https://ollama.com/install.sh | sh  &&  ollama pull qwen3:8b bge-m3"
fi

# ---------- Tổng kết ----------
if [ -n "$DOMAIN" ]; then URL="http://$DOMAIN (hoặc https:// nếu đã cấp chứng chỉ)"; else URL="http://<IP-máy-chủ>"; fi
echo
printf '\033[32m════════════════════════════════════════════════════════════\033[0m\n'
c_ok "HOÀN TẤT. Mở giao diện tại: $URL"
echo
echo "  Tài khoản đăng nhập (đổi mật khẩu ngay sau lần đầu):"
echo "$SEED_OUT" | grep hdslaw.vn | sed 's/^/    /' || echo "    (xem: cd $BACKEND_DIR && .venv/bin/python -m app.seed_accounts)"
echo
echo "  Lệnh thường dùng:"
echo "    systemctl status hds-ai-backend      # trạng thái backend"
echo "    journalctl -u hds-ai-backend -f      # xem log backend"
echo "    sudo bash deploy/update.sh           # cập nhật sau khi git pull"
printf '\033[32m════════════════════════════════════════════════════════════\033[0m\n'
