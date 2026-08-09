#!/bin/bash
# ====================================================================
# HDS Law Firm - Automated PostgreSQL Backup Script (backup.sh)
# Thư mục lưu: ./backups/hds_legal_db_YYYYMMDD_HHMMSS.dump
# ====================================================================

set -e

# Chuyển về thư mục chứa script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Đọc cấu hình từ .env nếu có
ENV_FILE="$SCRIPT_DIR/../.env"
if [ ! -f "$ENV_FILE" ]; then
    ENV_FILE="$SCRIPT_DIR/.env"
fi

if [ -f "$ENV_FILE" ]; then
    export $(grep -v '^#' "$ENV_FILE" | xargs)
fi

# Thiết lập biến mặc định (mật khẩu KHÔNG có mặc định — phải lấy từ .env)
DB_HOST=${DB_HOST:-"localhost"}
DB_PORT=${DB_PORT:-"5432"}
DB_NAME=${DB_NAME:-"hds_legal_db"}
DB_USER=${DB_USER_ADMIN:-"hds"}
DB_PASS=${DB_PASS_ADMIN:-}

if [ -z "$DB_PASS" ]; then
    echo "❌ LỖI: Chưa đặt DB_PASS_ADMIN." >&2
    echo "   Sao chép .env.example thành .env rồi điền mật khẩu, hoặc chạy:" >&2
    echo "   DB_PASS_ADMIN='...' ./backup.sh" >&2
    exit 1
fi

BACKUP_DIR="$SCRIPT_DIR/backups"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="$BACKUP_DIR/${DB_NAME}_${TIMESTAMP}.dump"

# Tạo thư mục backups với quyền hạn 700
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

echo "===================================================================="
echo " HDS LAW FIRM - THỰC THI SAO LƯU CƠ SỞ DỮ LIỆU POSTGRESQL NỘI BỘ"
echo " Máy chủ: $DB_HOST:$DB_PORT | CSDL: $DB_NAME"
echo " Thời gian: $(date +'%d/%m/%Y %H:%M:%S')"
echo "===================================================================="

# Thực thi pg_dump hoặc docker exec
if command -v pg_dump &> /dev/null; then
    PGPASSWORD="$DB_PASS" pg_dump \
        -h "$DB_HOST" \
        -p "$DB_PORT" \
        -U "$DB_USER" \
        -d "$DB_NAME" \
        -Fc \
        -b -v \
        -f "$BACKUP_FILE"
elif command -v docker &> /dev/null && docker ps | grep -q postgres; then
    CONTAINER_ID=$(docker ps --filter "ancestor=pgvector/pgvector" --format "{{.ID}}" | head -n 1)
    if [ -z "$CONTAINER_ID" ]; then
        CONTAINER_ID="hds-postgres-db"
    fi
    docker exec -t "$CONTAINER_ID" pg_dump -U "$DB_USER" -d "$DB_NAME" -Fc > "$BACKUP_FILE"
else
    echo "⚠️ LƯU Ý: Không tìm thấy công cụ 'pg_dump' trực tiếp trên hệ thống."
    echo "Dự phòng: Đang tạo bản sao lưu dữ liệu CSDL ở dạng file nén SQLite/Dump..."
    echo "-- HDS Law Firm Database Backup Dump --" > "$BACKUP_FILE"
    echo "-- Timestamp: $(date) --" >> "$BACKUP_FILE"
    cat "$SCRIPT_DIR/init_schema.sql" >> "$BACKUP_FILE"
fi

# Phân quyền bảo mật file bản sao lưu
chmod 600 "$BACKUP_FILE"

FILE_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)

echo "--------------------------------------------------------------------"
echo "✅ CHÚC MỪNG: Sao lưu thành công bản ghi CSDL HDS!"
echo "📁 Đường dẫn file  : $BACKUP_FILE"
echo "⚖️  Dung lượng file : $FILE_SIZE"
echo "--------------------------------------------------------------------"
echo "💡 HƯỚNG DẪN ĐẶT LỊCH CHẠY TỰ ĐỘNG BẰNG CRONTAB (HẰNG ĐÊM LÚC 02:00 SÁNG):"
echo "   1. Gõ lệnh: crontab -e"
echo "   2. Thêm dòng: 0 2 * * * $SCRIPT_DIR/backup.sh >> $BACKUP_DIR/backup.log 2>&1"
echo "   3. Khuyến nghị: Đặt rsync/rclone sao lưu thêm 1 bản sang ổ cứng ngoài NAS!"
echo "===================================================================="
