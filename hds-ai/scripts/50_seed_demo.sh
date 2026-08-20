#!/usr/bin/env bash
# 50_seed_demo.sh — Nạp dữ liệu mẫu
set -e
cd "$(dirname "$0")/.."
source .venv/bin/activate
mkdir -p data/demo
cat > data/demo/luat_mau.txt <<'EOF'
LUẬT DOANH NGHIỆP (TRÍCH)

Điều 17. Quyền thành lập và quản lý doanh nghiệp
1. Tổ chức, cá nhân có quyền thành lập và quản lý doanh nghiệp tại Việt Nam, trừ trường hợp tại khoản 2.
2. Không có quyền thành lập và quản lý doanh nghiệp: cán bộ, công chức, viên chức; người chưa thành niên; người bị mất năng lực hành vi dân sự.

Điều 46. Công ty trách nhiệm hữu hạn hai thành viên trở lên
1. Là doanh nghiệp có từ 02 đến 50 thành viên là tổ chức, cá nhân.
2. Thành viên chịu trách nhiệm trong phạm vi số vốn đã góp.
3. Có tư cách pháp nhân kể từ ngày được cấp Giấy chứng nhận đăng ký doanh nghiệp.
EOF
cat > data/demo/hopdong_mau.txt <<'EOF'
MẪU HỢP ĐỒNG DỊCH VỤ PHÁP LÝ

Điều 2. Phí dịch vụ
Thanh toán theo tiến độ: 30% khi ký, 40% giữa kỳ, 30% khi nghiệm thu. Chưa gồm VAT.

Điều 5. Bảo mật
Mỗi bên cam kết không tiết lộ thông tin của bên kia, hiệu lực vô thời hạn.
EOF
echo ">> Nạp luật (chia theo Điều)..."
python3 -c "from pathlib import Path;from app.ingest import ingest_file;ingest_file(Path('data/demo/luat_mau.txt'),doc_type='law',access_level='public',approved=True,label_verified=True)"
echo ">> Nạp hợp đồng mẫu..."
python3 -c "from pathlib import Path;from app.ingest import ingest_file;ingest_file(Path('data/demo/hopdong_mau.txt'),doc_type='contract',access_level='internal',approved=True,label_verified=True)"
echo ">> Thống kê:"
docker exec hds-postgres psql -U hds -d hdsai -c "SELECT * FROM v_kb_stats;"
echo "Xong. Thử: python -m app.cli \"Ai không được thành lập doanh nghiệp?\" internal"
