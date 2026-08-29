#!/usr/bin/env bash
# 01_setup.sh — Cài môi trường & khởi động dịch vụ
set -e
cd "$(dirname "$0")/.."

echo "=== CÀI ĐẶT MÔI TRƯỜNG HDS AI ==="

echo ">> 1/5 Gói hệ thống (cần sudo)"
sudo apt-get update -qq
sudo apt-get install -y -qq python3-venv python3-pip tesseract-ocr tesseract-ocr-vie \
  poppler-utils libreoffice-writer postgresql-client curl jq

echo ">> 2/5 File cấu hình .env"
[ -f .env ] || { cp .env.example .env; echo "   Đã tạo .env — SỬA MẬT KHẨU trước khi chạy thật."; }
mkdir -p data/raw data/work logs backups credentials

echo ">> 3/5 Môi trường Python"
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
pip install -q --upgrade pip
# requirements.txt đi kèm repo là nguồn chuẩn; chỉ sinh dự phòng nếu thiếu.
[ -f requirements.txt ] || cat > requirements.txt <<'REQ'
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
echo "   Cài thư viện Python (1-2 phút)..."
pip install -q -r requirements.txt

echo ">> 4/5 PostgreSQL + pgvector"
docker compose up -d
for i in $(seq 1 30); do
  docker exec hds-postgres pg_isready -U hds -d hdsai >/dev/null 2>&1 && { echo "   CSDL sẵn sàng."; break; }
  sleep 2; [ "$i" = 30 ] && { echo "   LỖI: CSDL không lên"; exit 1; }
done

echo ">> 5/5 Kiểm tra Ollama"
if curl -s --max-time 3 http://localhost:11434/api/tags >/dev/null 2>&1; then
  for M in qwen3:8b bge-m3; do
    ollama list 2>/dev/null | grep -q "${M%%:*}" && echo "   Model $M OK" || echo "   THIẾU $M — ollama pull $M"
  done
else
  echo "   CẢNH BÁO: Ollama chưa chạy"
fi

echo ""
echo "=== XONG. Bước tiếp: ==="
echo "  1. nano .env                       # sửa mật khẩu"
echo "  2. bash scripts/10_init_db.sh      # nạp schema"
echo "  3. bash scripts/50_seed_demo.sh    # dữ liệu mẫu"
echo "  4. bash scripts/99_healthcheck.sh  # kiểm tra"
