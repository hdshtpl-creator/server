#!/usr/bin/env bash
# ====================================================================
# HDS AI — Đưa web ra Internet, tự động tối đa.
#
# Máy đứng sau router (IP LAN 192.168.x, IP công khai do router giữ).
# Script này:
#   1. Dò IP công khai + IP LAN.
#   2. Thử tự mở cổng 80/443 trên router qua UPnP (nhiều router gia đình
#      bật sẵn tính năng này — không cần đăng nhập router thủ công).
#   3. Gắn thêm một tên miền dùng NGAY, KHÔNG cần sửa gì ở Namecheap:
#      sslip.io tự phân giải theo IP nhúng trong tên (vd 14-248-82-87.sslip.io
#      luôn trỏ đúng về 14.248.82.87 — không cấu hình DNS, có ngay lập tức).
#   4. Nếu bạn có tên miền thật đã trỏ A record đúng, truyền vào làm đối số
#      để script xin luôn HTTPS cho tên đó.
#   5. Tự xin chứng chỉ HTTPS (Let's Encrypt) cho tên nào đã sẵn sàng.
#
# Cách chạy:
#   sudo bash deploy/go-public.sh                        # chỉ dùng sslip.io
#   sudo bash deploy/go-public.sh app.hdslaw.vn           # kèm tên miền thật
#   sudo bash deploy/go-public.sh app.hdslaw.vn ban@hdslaw.vn   # + email riêng
# ====================================================================
set -euo pipefail

c_ok()   { printf '\033[32m  ✓ %s\033[0m\n' "$*"; }
c_info() { printf '\033[36m» %s\033[0m\n' "$*"; }
c_warn() { printf '\033[33m  ! %s\033[0m\n' "$*"; }
c_err()  { printf '\033[31m  ✗ %s\033[0m\n' "$*" >&2; }
die()    { c_err "$*"; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Hãy chạy bằng quyền root:  sudo bash deploy/go-public.sh"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
NGINX_SITE="/etc/nginx/sites-available/hds-ai"
DEPLOY_ENV="$SCRIPT_DIR/deploy.env"

[ -f "$NGINX_SITE" ] || die "Chưa thấy $NGINX_SITE — chạy 'sudo bash deploy/setup.sh' trước đã."

REAL_DOMAIN="${1:-}"
EMAIL="${2:-}"
if [ -z "$EMAIL" ] && [ -f "$DEPLOY_ENV" ]; then
  EMAIL="$(sed -n 's/^LETSENCRYPT_EMAIL=//p' "$DEPLOY_ENV" | head -1)"
fi
[ -z "$REAL_DOMAIN" ] && [ -f "$DEPLOY_ENV" ] && \
  REAL_DOMAIN="$(sed -n 's/^DOMAIN=//p' "$DEPLOY_ENV" | head -1)"

# ---------- 1. Dò IP ----------
c_info "1/5  Dò địa chỉ IP"
PUBLIC_IP="$(curl -fsS --max-time 6 https://ifconfig.me || true)"
LAN_IP="$(ip route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if ($i=="src") print $(i+1)}')"
[ -n "$PUBLIC_IP" ] || die "Không dò được IP công khai — kiểm tra máy có ra được Internet không."
[ -n "$LAN_IP" ]    || die "Không dò được IP LAN."
c_ok "IP công khai (Internet nhìn thấy) : $PUBLIC_IP"
c_ok "IP LAN (máy trong mạng nội bộ)    : $LAN_IP"

if [[ "$PUBLIC_IP" =~ ^(10\.|172\.(1[6-9]|2[0-9]|3[01])\.|192\.168\.|100\.(6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\.) ]]; then
  c_warn "IP công khai vẫn là dải riêng tư — nhà mạng đang CGNAT, không thể mở cổng được."
  c_warn "Cách duy nhất lúc này: Cloudflare Tunnel (xem mục Cách A trong deploy/README.md)."
  exit 1
fi

# ---------- 2. Thử tự mở cổng qua UPnP ----------
c_info "2/5  Thử tự mở cổng 80/443 trên router (UPnP)"
UPNP_OK=0
if ! command -v upnpc >/dev/null 2>&1; then
  apt-get update -qq >/dev/null 2>&1 || true
  apt-get install -y -qq miniupnpc >/dev/null 2>&1 || true
fi
if command -v upnpc >/dev/null 2>&1; then
  if upnpc -a "$LAN_IP" 80 80 TCP >/tmp/upnp80.log 2>&1 \
     && upnpc -a "$LAN_IP" 443 443 TCP >/tmp/upnp443.log 2>&1; then
    UPNP_OK=1
    c_ok "Router đã tự mở cổng 80 + 443 về $LAN_IP qua UPnP."
  else
    c_warn "Router không hỗ trợ UPnP (hoặc đang tắt tính năng này)."
  fi
else
  c_warn "Không cài được công cụ UPnP — bỏ qua bước tự mở cổng."
fi

if [ "$UPNP_OK" -eq 0 ]; then
  echo
  c_warn "CẦN LÀM TAY: đăng nhập trang quản trị router (thường http://192.168.1.1),"
  c_warn "tìm mục 'Port Forwarding' / 'Virtual Server', thêm 2 dòng:"
  c_warn "  TCP 80  -> $LAN_IP : 80"
  c_warn "  TCP 443 -> $LAN_IP : 443"
  c_warn "Làm xong chạy lại đúng lệnh này để script tiếp tục xin HTTPS."
  echo
fi

# ---------- 3. Chọn tên miền dùng ngay (sslip.io) ----------
c_info "3/5  Chuẩn bị tên miền dùng ngay — không cần sửa gì ở nơi mua tên miền"
IP_DASHED="$(echo "$PUBLIC_IP" | tr '.' '-')"
SSLIP_DOMAIN="hds-ai.${IP_DASHED}.sslip.io"
c_ok "Tên dùng ngay: $SSLIP_DOMAIN  (tự động trỏ đúng IP này, không cấu hình DNS)"

DOMAINS_TO_TRY=("$SSLIP_DOMAIN")
if [ -n "$REAL_DOMAIN" ]; then
  RESOLVED="$(getent hosts "$REAL_DOMAIN" 2>/dev/null | awk '{print $1}' | head -1)"
  if [ "$RESOLVED" = "$PUBLIC_IP" ]; then
    c_ok "Tên miền $REAL_DOMAIN đã trỏ đúng IP này — sẽ xin HTTPS luôn."
    DOMAINS_TO_TRY+=("$REAL_DOMAIN")
  else
    c_warn "Tên miền $REAL_DOMAIN chưa trỏ về $PUBLIC_IP (hiện là: ${RESOLVED:-chưa phân giải được})."
    c_warn "Sửa ở Namecheap: Domain List → Manage → Advanced DNS → Add A Record"
    c_warn "  Host: app (hoặc @)   Value: $PUBLIC_IP   TTL: Automatic"
    c_warn "(CHỈ thêm bản ghi A — không cần đổi Nameservers.) Đợi DNS cập nhật rồi chạy lại lệnh này."
  fi
fi

# ---------- 4. Gắn tên miền vào nginx ----------
c_info "4/5  Cập nhật cấu hình nginx"
CUR_NAMES="$(sed -n 's/^\s*server_name \(.*\);/\1/p' "$NGINX_SITE" | head -1)"
ALL_NAMES="$CUR_NAMES"
for d in "${DOMAINS_TO_TRY[@]}"; do
  case " $ALL_NAMES " in
    *" $d "*) ;;
    *) ALL_NAMES="$ALL_NAMES $d" ;;
  esac
done
ALL_NAMES="$(echo "$ALL_NAMES" | sed 's/^_ *//' | xargs)"   # bỏ "_" mặc định nếu còn
sed -i "s|^\(\s*\)server_name .*;|\1server_name $ALL_NAMES;|" "$NGINX_SITE"
nginx -t >/dev/null 2>&1 || die "Cấu hình nginx sai sau khi sửa — kiểm tra: nginx -t"
systemctl reload nginx
c_ok "nginx phục vụ: $ALL_NAMES"

# ---------- 5. Xin HTTPS ----------
c_info "5/5  Xin chứng chỉ HTTPS (Let's Encrypt)"
command -v certbot >/dev/null 2>&1 || { apt-get install -y -qq certbot python3-certbot-nginx >/dev/null; }

EMAIL_ARGS=(--register-unsafely-without-email)
[ -n "$EMAIL" ] && EMAIL_ARGS=(-m "$EMAIL")

OK_URLS=()
FAIL_DOMAINS=()
for d in "${DOMAINS_TO_TRY[@]}"; do
  echo "   → $d ..."
  if certbot --nginx -d "$d" --non-interactive --agree-tos "${EMAIL_ARGS[@]}" --redirect \
       >/tmp/certbot-"$d".log 2>&1; then
    OK_URLS+=("https://$d")
    c_ok "HTTPS OK: https://$d"
  else
    FAIL_DOMAINS+=("$d")
    c_warn "Chưa cấp được HTTPS cho $d (xem chi tiết: /tmp/certbot-$d.log)"
  fi
done

# ---------- Tổng kết ----------
echo
printf '\033[32m════════════════════════════════════════════════════════════\033[0m\n'
if [ "${#OK_URLS[@]}" -gt 0 ]; then
  c_ok "WEB ĐÃ CÔNG KHAI. Mở thử (kể cả bằng 4G, không dùng wifi công ty):"
  for u in "${OK_URLS[@]}"; do echo "    $u"; done
else
  c_warn "Chưa có HTTPS nào cấp được. Trong lúc chờ mở cổng/trỏ DNS, dùng tạm nội bộ:"
  echo "    http://$LAN_IP"
fi
if [ "${#FAIL_DOMAINS[@]}" -gt 0 ]; then
  echo
  c_warn "Chưa xong: ${FAIL_DOMAINS[*]}"
  c_warn "Nguyên nhân thường gặp: cổng 80/443 chưa mở ra ngoài, hoặc DNS chưa trỏ đúng."
  c_warn "Kiểm tra cổng đã mở chưa (chạy TỪ MÁY KHÁC, không phải server này):"
  echo "    curl -I http://$PUBLIC_IP"
  c_warn "Mở/tự trỏ xong, chạy lại đúng lệnh này để thử tiếp — script không làm hỏng gì khi chạy lại."
fi
printf '\033[32m════════════════════════════════════════════════════════════\033[0m\n'
