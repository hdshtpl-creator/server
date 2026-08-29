#!/usr/bin/env bash
# 00_preflight.sh — Kiểm tra máy chủ (chỉ đọc, không cài gì)
PASS=0; FAIL=0; WARN=0
ok(){ echo -e "  \033[32m[OK]\033[0m   $1"; PASS=$((PASS+1)); }
bad(){ echo -e "  \033[31m[LỖI]\033[0m  $1"; FAIL=$((FAIL+1)); }
warn(){ echo -e "  \033[33m[LƯU Ý]\033[0m $1"; WARN=$((WARN+1)); }

echo "=== KIỂM TRA MÁY CHỦ HDS AI ==="
echo "-- Hệ điều hành --"
. /etc/os-release 2>/dev/null && echo "  $PRETTY_NAME"
echo "-- Phần cứng --"
echo "  CPU: $(nproc) luồng | RAM: $(free -g|awk '/^Mem:/{print $2}')GB"
FREE=$(df -BG / | tail -1 | awk '{gsub("G","",$4);print $4}')
[ "$FREE" -ge 100 ] && ok "Ổ còn ${FREE}GB" || warn "Ổ chỉ còn ${FREE}GB — gắn thêm ổ"
echo "-- GPU --"
if command -v nvidia-smi >/dev/null; then
  ok "$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader | head -1)"
else bad "Chưa có nvidia-smi"; fi
echo "-- Ollama + model --"
if curl -s --max-time 3 http://localhost:11434/api/tags >/dev/null 2>&1; then
  ok "Ollama chạy"
  ollama list 2>/dev/null | grep -qi qwen && ok "Có Qwen" || warn "Chưa có Qwen — ollama pull qwen3:8b"
  ollama list 2>/dev/null | grep -qi bge && ok "Có bge-m3" || warn "Chưa có bge-m3 — ollama pull bge-m3"
else bad "Ollama chưa chạy"; fi
echo "-- Docker --"
command -v docker >/dev/null && ok "Có docker" || bad "Chưa có docker"
docker ps >/dev/null 2>&1 && ok "Docker chạy được" || warn "Cần: sudo usermod -aG docker \$USER"
echo "-- Python --"
python3 -c 'import sys;exit(0 if sys.version_info>=(3,10) else 1)' 2>/dev/null && ok "Python >=3.10" || bad "Cần Python >=3.10"
echo "-- OCR --"
command -v tesseract >/dev/null && tesseract --list-langs 2>/dev/null | grep -q '^vie$' && ok "Có tesseract + tiếng Việt" || warn "Thiếu tesseract-ocr-vie"
echo ""
echo -e "KẾT QUẢ: \033[32m$PASS OK\033[0m | \033[33m$WARN lưu ý\033[0m | \033[31m$FAIL lỗi\033[0m"
[ "$FAIL" -gt 0 ] && echo "→ Xử lý lỗi trước khi tiếp." || echo "→ Sẵn sàng. Chạy: bash scripts/01_setup.sh"
