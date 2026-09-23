# Đọc giấy tờ cho web Đăng ký kinh doanh (CCCD / hộ chiếu / Giấy ĐKDN)

Web ĐKKD (app `ai-main`, chạy trên Vercel) cho khách chụp CCCD rồi tự điền
form. Trước đây ảnh đi qua n8n → OpenAI. Giờ ảnh đi thẳng sang máy chủ HDS AI,
model **nhìn ảnh** chạy trên GPU của mình, không rời máy chủ, không tốn tiền
API.

```
Trình duyệt khách ──POST /api/dkkd/extract──▶ nginx ─▶ FastAPI ─▶ Ollama (qwen2.5vl)
        ▲                                                            │
        └────────────── JSON 14 trường (name, dob, idNumber...) ◀────┘
```

Model thị giác **chỉ nạp khi dùng**: mỗi lượt đọc, Ollama nạp model vào VRAM,
đọc xong dỡ ngay (`VISION_KEEP_ALIVE=0`). Card 16GB không chứa cùng lúc
`qwen3:14b` và model thị giác, nên cách này giữ VRAM cho chat nội bộ; đổi lại
mỗi lượt đọc mất thêm 3–6 giây nạp model.

---

## 1. Cài trên máy chủ (một lần)

```bash
# 1) Kéo model nhìn ảnh (~6 GB). Cần GPU — chạy CPU mất 1–3 phút/ảnh, không dùng được.
ollama pull qwen2.5vl:7b

# 2) Khai trong hds-ai/.env
VISION_MODEL=qwen2.5vl:7b
VISION_KEEP_ALIVE=0
DKKD_ALLOWED_ORIGINS=https://<domain-web-dkkd>,https://<ten-du-an>.vercel.app

# 3) Khởi động lại backend
sudo systemctl restart hds-ai      # hoặc: bash deploy/update.sh
```

Kiểm tra:

```bash
curl -s https://<domain-hds>/api/dkkd/status
# {"model":"qwen2.5vl:7b","keep_alive":"0","allowed_origins":2,"enabled":true,
#  "ollama":true,"pulled":true,"loaded":false}
```

`pulled: false` → chưa `ollama pull`. `enabled: false` → thiếu
`DKKD_ALLOWED_ORIGINS`. `loaded` gần như luôn `false` vì model dỡ ngay sau khi
dùng — đó là đúng ý.

> **Nâng cấp:** `qwen3-vl:8b` đọc tiếng Việt tốt hơn (cần Ollama ≥ 0.12.7).
> Đổi `VISION_MODEL=qwen3-vl:8b`, `ollama pull qwen3-vl:8b`, khởi động lại.
> Mã đã tự tắt chế độ suy nghĩ cho họ qwen3.

---

## 2. Trỏ web ĐKKD sang máy chủ

Trong Vercel → Project → Settings → Environment Variables (biến `VITE_*` phải
khai ở đây, `.env` local không có tác dụng khi build trên Vercel):

```
VITE_N8N_EXTRACT_URL=https://<domain-hds>/api/dkkd/extract
```

Redeploy. App gửi đúng payload cũ (`documents[]` base64) nên **không sửa code
app**. Bộ lọc chống bịa (NGUYỄN VĂN A, 123456789012...) vẫn chạy ở trình
duyệt như trước.

Origin trong `DKKD_ALLOWED_ORIGINS` phải khớp **đúng** `scheme://host[:port]`
của trang web (không có đường dẫn). Mở DevTools → Network → request
`extract` → header `Origin` để chép cho chắc. Muốn thử local thì thêm
`http://localhost:3000`.

---

## 3. "Chỉ web của tôi được gọi" — ba lớp

| Lớp | Làm gì | Chặn được ai |
|---|---|---|
| CORS (`DKKD_ALLOWED_ORIGINS` tự cộng vào CORS) | Trình duyệt từ chối trả kết quả cho web lạ | Web khác nhúng API vào trang của họ |
| Kiểm tra header `Origin` (thiếu thì lấy gốc `Referer`) | Trả 403 nếu không khớp danh sách | Web lạ, iframe lạ |
| Van tần suất theo IP (`DKKD_RATE_MAX`, mặc định 40 lượt / 15 phút) | Trả 429 | Script curl giả header, spam GPU |

Không dùng khoá API vì app chạy hoàn toàn trong trình duyệt: khoá nhúng vào
JS là ai cũng đọc được (đúng lý do trước đây phải đi vòng qua n8n). Endpoint
này không đọc kho tri thức, không chạm CSDL — kẻ vượt được hàng rào chỉ tốn
GPU của HDS, không lấy được dữ liệu gì.

Muốn chặt hơn nữa: giữ n8n làm trung gian (n8n gọi máy chủ HDS server-side).
Khi đó thêm origin của n8n vào danh sách, hoặc để trống Origin và bật kiểm tra
IP ở nginx (`allow <ip-n8n>; deny all;` trong `location /api/dkkd/`).

---

## 4. Thử bằng tay

```bash
IMG=$(base64 -w0 cccd-truoc.jpg)
curl -s https://<domain-hds>/api/dkkd/extract \
  -H "Origin: https://<domain-web-dkkd>" \
  -H "Content-Type: application/json" \
  -d "{\"documents\":[{\"image\":\"data:image/jpeg;base64,$IMG\",\"mimeType\":\"image/jpeg\"}]}"
```

Trả về:

```json
{"documentType":"cccd","name":"NGUYỄN THỊ ...","dob":"25/12/1990","gender":"Nữ",
 "idNumber":"0790...","address":"...","addressDetail":"...","ward":"...",
 "district":"","province":"...","phone":"","email":"","orgName":"","orgCode":""}
```

Ảnh không phải giấy tờ → `documentType:"none"`, mọi trường rỗng. App hiện
"Không nhận diện được giấy tờ trong ảnh" và để khách nhập tay.

---

## 5. Biến cấu hình

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `VISION_MODEL` | `qwen2.5vl:7b` | Model nhìn ảnh trên Ollama |
| `VISION_KEEP_ALIVE` | `0` | `0` = dỡ khỏi VRAM ngay sau khi trả lời. `2m` nếu khách hay gửi nhiều ảnh liên tiếp **và** card đủ chỗ cho cả hai model |
| `VISION_NUM_CTX` | `8192` | Ngữ cảnh model thị giác. Đừng dùng 32K như chat — KV cache tràn VRAM |
| `VISION_MAX_EDGE` | `1600` | Thu nhỏ ảnh về cạnh dài này trước khi gửi model (ảnh 4000px tốn token gấp nhiều lần mà không rõ hơn) |
| `VISION_TIMEOUT_SEC` | `300` | Chờ Ollama tối đa |
| `DKKD_ALLOWED_ORIGINS` | *(trống = tắt)* | Origin được gọi, phân tách dấu phẩy |
| `DKKD_RATE_MAX` / `DKKD_RATE_WINDOW_SEC` | `40` / `900` | Van theo IP |
| `DKKD_MAX_DOCS` | `4` | Số ảnh tối đa một lượt |
| `DKKD_MAX_IMAGE_MB` | `10` | Cỡ mỗi ảnh |
| `DKKD_MAX_PDF_PAGES` | `2` | PDF chỉ đọc N trang đầu |

---

## 6. Sự cố thường gặp

| Triệu chứng | Nguyên nhân | Xử lý |
|---|---|---|
| App báo "Không gọi được AI đọc giấy tờ", console `403` | Origin không khớp | Chép đúng `Origin` từ DevTools vào `DKKD_ALLOWED_ORIGINS`, restart |
| Console lỗi CORS `No 'Access-Control-Allow-Origin'` | Backend chưa restart sau khi sửa .env, hoặc origin sai | Như trên |
| `503 Ollama chưa có model` | Chưa pull | `ollama pull qwen2.5vl:7b` |
| `504` hoặc rất chậm (>60 s) | Model đang chạy CPU | `bash deploy/kiem-tra-gpu.sh`; `ollama ps` phải thấy `100% GPU` khi đang đọc |
| Đọc xong, hỏi chat nội bộ câu đầu chậm 5–10 s | qwen3:14b bị dỡ để nhường VRAM, nạp lại | Bình thường. Card ≥ 24GB thì đặt `VISION_KEEP_ALIVE=5m` |
| Số CCCD đọc thiếu/sai một chữ số | Ảnh mờ, chụp nghiêng | App đã lọc số bịa; khách sửa tay. Thử `qwen3-vl:8b` |

Kiểm thử không cần GPU: `cd hds-ai && python -m unittest tests.test_dkkd_extract -v`.
