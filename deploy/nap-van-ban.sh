#!/usr/bin/env bash
# nap-van-ban.sh — Nạp một lô VĂN BẢN LUẬT vào kho, tự chia đúng ngăn theo TÊN FILE.
#
# Vì sao cần: kho chia sáu ngăn (1.1 Luật, 1.2 Nghị định, 1.3 Thông tư…) và đặt
# nhầm ngăn thì tài liệu mang sai nhãn — hoặc nằm im không ai học. Từ 06/09/2026
# tên file cũng là DANH TÍNH (số hiệu/loại/ngày ban hành, xem van_ban.
# danh_tinh_tu_ten_file), nên chỉ cần đọc tên file là biết văn bản thuộc ngăn nào.
# Script này đọc tên, chọn ngăn, chép vào, rồi gọi bộ quét kho học luôn.
#
# Tên file KHÔNG bóc được số hiệu thì DỪNG file đó lại và in ra khuôn đúng —
# thà bắt sửa tên còn hơn để một văn bản vô danh nằm trong kho luật (bot sẽ
# trích dẫn nó mà không nêu được số hiệu, đúng lỗi nhân viên báo 28-29/08).
#
# Chạy:
#   bash deploy/nap-van-ban.sh ~/van-ban-moi              # kiểm tên, chép, học
#   bash deploy/nap-van-ban.sh ~/van-ban-moi --dry-run    # chỉ xem, không chép
#   bash deploy/nap-van-ban.sh ~/van-ban-moi --khong-hoc  # chép nhưng chưa học
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "$SCRIPT_DIR/../hds-ai" && pwd)"
PY="$BACKEND_DIR/.venv/bin/python"

R='\033[0;31m'; G='\033[0;32m'; Y='\033[1;33m'; B='\033[1;34m'; N='\033[0m'
ok()   { echo -e "  ${G}✓${N} $*"; }
warn() { echo -e "  ${Y}!${N} $*"; }
bad()  { echo -e "  ${R}✗${N} $*"; }
head_(){ echo -e "\n${B}== $* ==${N}"; }

NGUON="${1:-}"
DRY=0; HOC=1
for arg in "$@"; do
  case "$arg" in
    --dry-run)   DRY=1 ;;
    --khong-hoc) HOC=0 ;;
  esac
done

if [ -z "$NGUON" ] || [ ! -d "$NGUON" ]; then
  echo "Dùng: bash deploy/nap-van-ban.sh <thư-mục-chứa-văn-bản> [--dry-run] [--khong-hoc]"
  echo
  echo "Ví dụ: bash deploy/nap-van-ban.sh ~/van-ban-moi"
  exit 1
fi

# Thư mục kho: cùng quy tắc với local_learn (DATA_LIB → DATA_RAW → ./data/raw).
KHO="$(cd "$BACKEND_DIR" && "$PY" - <<'EOF' 2>/dev/null
import os
from pathlib import Path
print(Path(os.getenv("DATA_LIB", os.getenv("DATA_RAW", "./data/raw"))).resolve())
EOF
)"
[ -d "$KHO" ] || { echo "Không thấy thư mục kho: $KHO"; exit 1; }
GOC_LUAT="$KHO/1. VĂN BẢN PHÁP LUẬT"
[ -d "$GOC_LUAT" ] || { echo "Không thấy ngăn '1. VĂN BẢN PHÁP LUẬT' trong $KHO"; exit 1; }

head_ "Kho: $KHO"
echo "  Nguồn: $NGUON"
[ "$DRY" = 1 ] && echo -e "  ${Y}(--dry-run: chỉ xem, không chép gì)${N}"

# Bảng loại → ngăn. Tên ngăn phải khớp thư mục THẬT trên đĩa; script tự dò để
# đổi tên thư mục (thêm/bớt số thứ tự) không làm hỏng gì.
nganh_cho_loai() {
  case "$1" in
    "Bộ luật"|"Luật"|"Pháp lệnh")                         echo "1.1" ;;
    "Nghị định")                                          echo "1.2" ;;
    "Thông tư"|"Thông tư liên tịch")                      echo "1.3" ;;
    "Nghị quyết"|"Quyết định"|"Chỉ thị"|"Công điện")      echo "1.4" ;;
    "Văn bản hợp nhất")                                   echo "1.5" ;;
    *)                                                    echo "" ;;
  esac
}

tim_thu_muc() {   # $1 = tiền tố kiểu "1.2" → đường dẫn thư mục thật
  find "$GOC_LUAT" -maxdepth 1 -type d -name "$1*" | head -1
}

n_ok=0; n_loi=0; n_bo=0
head_ "Đọc danh tính từ tên file"
while IFS= read -r -d '' f; do
  ten="$(basename "$f")"
  # Bóc danh tính bằng CHÍNH hàm mà bộ học dùng — không viết lại logic ở bash.
  doc="$(cd "$BACKEND_DIR" && "$PY" - "$ten" <<'EOF' 2>/dev/null
import sys
from app import van_ban
d = van_ban.danh_tinh_tu_ten_file(sys.argv[1])
print("%s|%s|%s" % (d["so_hieu"] or "", d["loai_van_ban"] or "", d["ngay_ban_hanh"] or ""))
EOF
)"
  so="${doc%%|*}"; rest="${doc#*|}"; loai="${rest%%|*}"; ngay="${rest#*|}"

  if [ -z "$so" ]; then
    bad "$ten"
    echo "      Tên không mang số hiệu. Đổi theo một trong hai khuôn rồi chạy lại:"
    echo "        Nghị-định-96-2026-NĐ-CP.docx      (Loại-số-năm-ký hiệu)"
    echo "        58-2026-ND-CP_13022026.pdf        (số-năm-ký hiệu_ngày)"
    n_loi=$((n_loi + 1)); continue
  fi

  ngan="$(nganh_cho_loai "$loai")"
  if [ -z "$ngan" ]; then
    bad "$ten — số $so nhưng không đoán được loại ('$loai') → không biết xếp ngăn nào"
    n_loi=$((n_loi + 1)); continue
  fi
  dich="$(tim_thu_muc "$ngan")"
  if [ -z "$dich" ]; then
    bad "$ten — cần ngăn '$ngan …' nhưng kho không có thư mục đó"
    n_loi=$((n_loi + 1)); continue
  fi

  # Đã có file cùng tên trong kho: bộ quét nhận ra bằng md5 nội dung, nội dung
  # đổi thì học lại (và PDF rơi về hàng chờ duyệt — xem 4.5 sổ tay). Báo để
  # người chạy biết mình đang THAY một tài liệu đang phục vụ, không phải thêm mới.
  if [ -e "$dich/$ten" ]; then
    warn "$ten — ĐÃ CÓ trong $(basename "$dich"), sẽ ghi đè (bot học lại bản mới)"
  fi

  echo -e "  ${G}→${N} $ten"
  echo "      số $so · $loai${ngay:+ · ban hành $ngay}"
  echo "      vào: $(basename "$dich")/"
  if [ "$DRY" = 0 ]; then
    if cp -f "$f" "$dich/$ten"; then
      n_ok=$((n_ok + 1))
    else
      bad "chép hỏng: $ten"; n_loi=$((n_loi + 1))
    fi
  else
    n_ok=$((n_ok + 1))
  fi
done < <(find "$NGUON" -maxdepth 1 -type f \( -iname "*.doc" -o -iname "*.docx" -o -iname "*.pdf" \) -print0 | sort -z)

# File định dạng khác nằm lẫn trong thư mục nguồn — nói ra, đừng im lặng bỏ.
while IFS= read -r -d '' f; do
  warn "bỏ qua (không phải .doc/.docx/.pdf): $(basename "$f")"
  n_bo=$((n_bo + 1))
done < <(find "$NGUON" -maxdepth 1 -type f ! -iname "*.doc" ! -iname "*.docx" ! -iname "*.pdf" -print0)

head_ "Kết quả"
echo "  $n_ok tệp hợp lệ · $n_loi tệp sai tên · $n_bo tệp bỏ qua"

if [ "$n_loi" -gt 0 ]; then
  warn "Sửa tên các tệp báo ✗ rồi chạy lại — chúng CHƯA được chép."
fi
if [ "$DRY" = 1 ]; then
  echo -e "\n  Bỏ ${Y}--dry-run${N} để chép thật."
  exit 0
fi
if [ "$n_ok" = 0 ]; then
  exit 1
fi

if [ "$HOC" = 1 ]; then
  head_ "Cho bot học"
  bash "$SCRIPT_DIR/hoc-tu-thu-muc.sh"
  echo
  ok "Xong. Tài liệu mới nằm ở hàng CHỜ DUYỆT."
  echo "     Vào web: Quản trị hệ thống → Duyệt nhãn tài liệu → duyệt từng văn bản."
else
  echo -e "\n  Đã chép, chưa học. Chạy tiếp: ${B}bash deploy/hoc-tu-thu-muc.sh${N}"
fi
