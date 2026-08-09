#!/usr/bin/env bash
# 10_init_db.sh — Nạp schema
set -e
cd "$(dirname "$0")/.."

# Nạp .env để lấy mật khẩu vai ứng dụng (không hardcode trong schema.sql)
if [ -f .env ]; then
  set -a; . ./.env; set +a
fi

if [ -z "${APP_DB_PASSWORD:-}" ]; then
  echo "❌ Thiếu APP_DB_PASSWORD trong .env — không thể tạo vai hds_app." >&2
  echo "   Chạy: cp .env.example .env && nano .env" >&2
  exit 1
fi

echo ">> Nạp schema..."
docker exec -i hds-postgres psql -U hds -d hdsai \
  -v ON_ERROR_STOP=1 -v app_pass="$APP_DB_PASSWORD" < sql/schema.sql
echo ">> Các bảng:"
docker exec hds-postgres psql -U hds -d hdsai -c "\dt"
echo ">> Kiểm tra RLS (phải là 't'):"
docker exec hds-postgres psql -U hds -d hdsai -c \
  "SELECT tablename,rowsecurity FROM pg_tables WHERE tablename IN ('chunks','documents');"

echo ">> Nạp 4 bộ phận + ma trận quyền..."
source .venv/bin/activate 2>/dev/null
python -m app.seed_departments || echo "   (chạy lại thủ công: python -m app.seed_departments)"

echo ">> Tạo tài khoản demo để đăng nhập..."
python -m app.seed_accounts || echo "   (chạy lại thủ công: python -m app.seed_accounts)"

echo "Xong. Bước tiếp: bash scripts/50_seed_demo.sh"
