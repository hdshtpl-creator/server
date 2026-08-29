# Kiểm tra chất lượng chat HDS AI

Bộ eval này khóa lại ba lỗi đã gặp: hiểu sai câu hỏi đếm nhân sự, mất chủ đề ở
câu hỏi nối tiếp, và trả nội dung tài liệu không có citation kiểm chứng. Nó chỉ
dùng thư viện chuẩn Python; chế độ offline không gọi PostgreSQL, Ollama hay mạng.

## 1. Chạy sau khi cập nhật mã nguồn

Đứng tại thư mục dự án trên máy chủ (`~/hds-ai`):

```bash
python -m unittest tests.quality_eval_test -v
python scripts/quality_eval.py --mode offline
```

Offline đọc [quality_eval_cases.json](quality_eval_cases.json) và kiểm tra:

- intent chính xác cho nhân sự, HĐLĐ, tài khoản phần mềm và khách hàng;
- câu “chi tiết từng cá nhân” giữ đúng chủ đề từ state/lịch sử;
- câu hỏi mới không bị lịch sử cũ làm nhiễu retrieval;
- citation thật được giữ, citation giả hoặc câu grounded không nguồn bị chặn.

Exit code `0` nghĩa là tất cả đạt, `1` nghĩa là có case sai, `2` nghĩa là thiếu
cấu hình. Vì vậy lệnh có thể dùng trực tiếp trong CI/deploy.

## 2. Lấy token và chạy API thật

Khởi động backend, chạy migration/ingest xong rồi lấy JWT nội bộ:

```bash
export TOKEN="$(curl -fsS http://127.0.0.1:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@hdslaw.vn","password":"<MAT_KHAU>"}' \
  | python -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')"

python scripts/quality_eval.py \
  --mode all \
  --base-url http://127.0.0.1:8000 \
  --repeat 3 \
  --json-out quality-eval-report.json
```

`TOKEN` phải thuộc người dùng nội bộ. Có thể không export token bằng cách dùng
`--email ... --password ...`; cách dùng biến môi trường tránh lưu JWT/mật khẩu
trong lịch sử lệnh tốt hơn.

Live suite kiểm tra:

- câu đếm có cấu trúc không gọi model: `timings.ai_ms == 0`, `latency_ms == 0`;
- câu có cấu trúc không mang bất kỳ nguồn `kind=document` nào (nguồn hệ thống
  `kind=system` vẫn hợp lệ);
- lượt hỏi tiếp dùng cùng `conversation_id` và vẫn đi đúng đường có cấu trúc;
- câu retrieval có ít nhất một `[Nguồn n]` hợp lệ;
- tất cả `sources[].document_id` nằm trong đúng bộ nguồn đã chọn;
- báo pass rate theo nhóm và latency client/API ở p50, p95.

Live eval tạo conversation/message kiểm thử trong CSDL giống một người dùng thật.

## 3. Chọn nguồn retrieval đáng tin cậy

Nếu không truyền ID, harness gọi `/documents/browse` và chọn tài liệu đầu tiên có
`can_open=true`. Để kết quả ổn định, nên chỉ rõ một tài liệu đã ingest thành công
và đặt câu phù hợp với tài liệu đó:

```bash
python scripts/quality_eval.py --mode live \
  --document-id 123 \
  --retrieval-question 'Theo tài liệu đã chọn, điều kiện chấm dứt hợp đồng là gì?' \
  --repeat 3 \
  --json-out quality-eval-report.json
```

Nhiều nguồn:

```bash
export QUALITY_EVAL_DOCUMENT_IDS=123,456
export QUALITY_EVAL_RETRIEVAL_QUESTION='So sánh nghĩa vụ của các bên trong hai tài liệu đã chọn.'
python scripts/quality_eval.py --mode live --repeat 3
```

Nếu chỉ muốn xác minh router/state mà chưa ingest tài liệu:

```bash
python scripts/quality_eval.py --mode live --skip-retrieval
```

## 4. Đọc kết quả

Ví dụ:

```text
[PASS] live.direct/live_staff_count (18.2ms): OK
[FAIL] live.retrieval/live_selected_source_retrieval (6400.8ms): câu trả lời retrieval không có [Nguồn n]

TỔNG: 20/21 đạt (95.24%), 1 lỗi
  Live client wall: p50=19.4ms, p95=6430.2ms, n=7
  Live API end-to-end: p50=14.0ms, p95=6390.0ms, n=7
```

- `client wall` gồm mạng + backend; `API end-to-end` là thời gian backend tự đo.
- Câu staff/HĐLĐ vẫn được coi là an toàn khi trả `insufficient_evidence` với
  `ai_ms=0`: điều đó có nghĩa sổ HR chưa có dữ liệu và hệ thống không lấy số tài
  khoản đăng nhập để giả làm quân số.
- Retrieval không nguồn, citation sai số, hoặc lọt `document_id` ngoài bộ chọn là
  lỗi bắt buộc; không nên nới golden case để che lỗi.
- JSON report không ghi TOKEN hay mật khẩu, phù hợp để lưu làm baseline giữa các
  lần đổi model/cấu hình.

Xem toàn bộ tùy chọn và các biến môi trường được hỗ trợ:

```bash
python scripts/quality_eval.py --help
```
