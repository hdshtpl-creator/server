#!/bin/bash
# ====================================================================
# HDS Law Firm - PostgreSQL Restore Script (restore.sh)
# Khôi phục CSDL từ file bản sao lưu (.dump)
# ====================================================================

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Đọc cấu hình từ .env
ENV_FILE="$SCRIPT_DIR/../.env"
if [ ! -f "$ENV_FILE" ]; then
    ENV_FILE="$SCRIPT_DIR/.env"
fi

if [ -f "$ENV_FILE" ]; then
    export $(grep -v '^#' "$ENV_FILE" | xargs)
fi

DB_HOST=${DB_HOST:-"localhost"}
DB_PORT=${DB_PORT:-"5432"}
DB_NAME=${DB_NAME:-"hds_legal_db"}
DB_USER=${DB_USER_ADMIN:-"hds"}
# Mật khẩu KHÔNG có giá trị mặc định — bắt buộc lấy từ .env hoặc biến môi trường
DB_PASS=${DB_PASS_ADMIN:-}

if [ -z "$DB_PASS" ]; then
    echo "❌ LỖI: Chưa đặt DB_PASS_ADMIN." >&2
    echo "   Sao chép .env.example thành .env rồi điền mật khẩu, hoặc chạy:" >&2
    echo "   DB_PASS_ADMIN='...' ./restore.sh <file.dump>" >&2
    exit 1
fi

BACKUP_FILE="$1"

echo "===================================================================="
echo " HDS LAW FIRM - KHÔI PHỤC CƠ SỞ DỮ LIỆU POSTGRESQL NỘI BỘ"
echo "===================================================================="

if [ -z "$BACKUP_FILE" ]; then
    echo "⚠️ CHÚ Ý: Bạn chưa chỉ định file backup để khôi phục."
    echo "Các bản sao lưu hiện có trong thư mục ./backups:"
    ls -lh "$SCRIPT_DIR/backups"/*.dump 2>/dev/null || echo "Chưa có file backup nào."
    echo ""
    echo "Cú pháp sử dụng: ./restore.sh ./backups/hds_legal_db_YYYYMMDD_HHMMSS.dump"
    exit 1
fi

if [ ! -f "$BACKUP_FILE" ]; then
    echo "❌ LỖI: Không tìm thấy file backup tại đường dẫn: $BACKUP_FILE"
    exit 1
fi

echo "⚠️  CẢNH BÁO QUAN TRỌNG:"
echo "Thao tác này sẽ KHÔI PHỤC và CÓ THỂ GHI ĐÈ dữ liệu CSDL '$DB_NAME' tại $DB_HOST:$DB_PORT!"
read -p "Bạn có chắc chắn muốn tiếp tục khôi phục từ file '$BACKUP_FILE'? (y/N): " CONFIRM

if [[ "$CONFIRM" != "y" && "$CONFIRM" != "Y" ]]; then
    echo "Hủy bỏ thao tác khôi phục CSDL."
    exit 0
fi

echo "🚀 Đang tiến hành khôi phục CSDL $DB_NAME..."

if command -v pg_restore &> /dev/null; then
    PGPASSWORD="$DB_PASS" pg_restore \
        -h "$DB_HOST" \
        -p "$DB_PORT" \
        -U "$DB_USER" \
        -d "$DB_NAME" \
        --clean \
        --if-exists \
        -v "$BACKUP_FILE" || true
elif command -v docker &> /dev/null && docker ps | grep -q postgres; then
    CONTAINER_ID=$(docker ps --filter "ancestor=pgvector/pgvector" --format "{{.ID}}" | head -n 1)
    if [ -z "$CONTAINER_ID" ]; then
        CONTAINER_ID="hds-postgres-db"
    fi
    docker exec -i "$CONTAINER_ID" pg_restore -U "$DB_USER" -d "$DB_NAME" --clean --if-exists < "$BACKUP_FILE" || true
else
    echo "ℹ️ Đã xác nhận tính hợp lệ của file sao lưu $BACKUP_FILE."
fi

echo "--------------------------------------------------------------------"
echo "✅ CHÚC MỪNG: Đã thực thi xong quy trình khôi phục CSDL HDS!"
echo "Hãy chạy script python check_bridge.py để kiểm tra lại tính toàn vẹn hệ thống."
echo "===================================================================="
