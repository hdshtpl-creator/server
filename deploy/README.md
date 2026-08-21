# Triển khai HDS AI — một máy chủ, một lệnh

Toàn bộ hệ thống chạy trên **một máy chủ Ubuntu**:

```
Trình duyệt ──HTTPS──▶ nginx ──▶ /            → giao diện tĩnh (React build)
                              └▶ /api/*       → FastAPI (127.0.0.1:8000)
                                                  ├─ PostgreSQL + pgvector (Docker)
                                                  └─ Ollama (127.0.0.1:11434)
```

Vì giao diện và API cùng một tên miền nên **không cần CORS, không dính mixed-content**.

## Yêu cầu máy chủ

- **Ubuntu 22.04 / 24.04**, quyền `sudo`.
- **RAM ≥ 24 GB** nếu chạy Ollama cùng máy (mặc định `qwen3:14b` + `bge-m3`). Máy 16 GB nên đổi sang `qwen3:8b` trong `.env`.
- Đặt mã nguồn ở `/home/<user>/` hoặc `/opt/` — **đừng** đặt trong `/root/` (nginx không đọc được).
- Cổng 80/443 mở ra Internet nếu dùng tên miền + HTTPS.

Máy chủ tự cài giúp bạn: Docker, Node.js 20, nginx, certbot, thư viện Python. Bạn không phải cài tay.

## Cài đặt (chạy một lần)

```bash
git clone <repo-cua-ban> hds-ai-full
cd hds-ai-full
sudo bash deploy/setup.sh
```

Script sẽ hỏi **tên miền** và **email** (Enter để bỏ qua nếu chạy bằng IP nội bộ).
Muốn khỏi bị hỏi, điền trước:

```bash
cp deploy/deploy.env.example deploy/deploy.env
nano deploy/deploy.env          # điền DOMAIN và LETSENCRYPT_EMAIL
sudo bash deploy/setup.sh
```

Xong, script tự làm hết: sinh mật khẩu ngẫu nhiên, dựng CSDL, nạp schema, tạo tài khoản
đăng nhập, chạy backend bằng systemd, build giao diện, cấu hình nginx, và cấp HTTPS nếu
có tên miền. Cuối cùng nó in ra địa chỉ truy cập và danh sách tài khoản demo.

## Đưa ra Internet ngay — không cần sửa gì ở Namecheap

Sau khi `setup.sh` chạy xong (đã có giao diện, chỉ chưa công khai), chạy tiếp:

```bash
sudo bash deploy/go-public.sh
```

Script này tự động: dò IP công khai, **thử tự mở cổng 80/443 trên router qua UPnP**
(nhiều router gia đình bật sẵn, không cần đăng nhập router), gắn thêm một tên miền
**dùng ngay lập tức** dạng `hds-ai.<ip>.sslip.io` (dịch vụ DNS công cộng tự trỏ theo IP
nhúng trong tên — **không cần đụng vào Namecheap**), rồi tự xin HTTPS Let's Encrypt.

Có tên miền thật muốn dùng luôn (vd `app.hdslaw.vn`, chỉ cần **thêm bản ghi A** ở
Namecheap Advanced DNS — không phải đổi nameserver):

```bash
sudo bash deploy/go-public.sh app.hdslaw.vn ban@hdslaw.vn
```

Nếu tên miền thật chưa trỏ kịp, script vẫn cấp HTTPS cho `sslip.io` để bạn xem web ngay;
chạy lại y nguyên lệnh sau khi trỏ DNS xong — an toàn khi chạy nhiều lần.

Nếu router không hỗ trợ UPnP, script in ra chính xác 2 dòng cần thêm trong trang quản trị
router (Port Forwarding / Virtual Server: TCP 80 và 443 trỏ về IP LAN của máy).

## Nếu máy chủ ĐÃ chạy backend (nâng cấp từ bản demo)

Trường hợp bạn đã cài `~/hds-ai` trước đó và backend đang chạy: **không cần làm lại từ
đầu, không mất dữ liệu.** Chỉ cần đưa mã mới (có frontend + deploy) về và giữ lại cấu
hình CSDL đang chạy:

```bash
cd ~
git clone <repo-url> hds-ai-full            # mã mới: backend + frontend + deploy
cp ~/hds-ai/.env hds-ai-full/hds-ai/.env    # GIỮ mật khẩu CSDL cũ (khớp dữ liệu sẵn có)
pkill -f 'uvicorn app.api' || true          # dừng backend chạy tay cũ
cd hds-ai-full
sudo bash deploy/setup.sh
```

Vì thấy `.env` đã có, `setup.sh` **giữ nguyên mật khẩu CSDL** (không đụng dữ liệu), chỉ
**thay `JWT_SECRET` mẫu bằng khoá mạnh** (mã mới từ chối khoá mẫu — nếu không đổi sẽ
không đăng nhập được) và tự đồng bộ mật khẩu vai `hds_app`. Sau đó nó cài systemd (thay
cho `uvicorn` chạy tay), build giao diện và cấu hình nginx.

> Bản demo chạy `uvicorn ... --host 0.0.0.0` phơi thẳng cổng 8000. Sau khi dùng bộ này,
> backend chỉ nghe `127.0.0.1:8000` (chỉ nginx gọi tới), an toàn hơn.

## Đưa mã lên máy chủ: GitHub hay chép tay?

**Nên dùng GitHub** — về sau chỉ cần `git pull && sudo bash deploy/update.sh` là cập nhật
cả frontend lẫn backend, có lịch sử phiên bản, không sợ chép thiếu file. Chép tay
(`scp`/tar) chỉ hợp khi máy chủ không ra được Internet để `git clone`.

```bash
# Chép tay (thay cho git clone) nếu cần:
#   scp -r hds-ai-full user@server:~/       (từ máy của bạn)
```

`.env` (chứa bí mật) và `dist/` (build) đều được `.gitignore` loại khỏi GitHub — đó là lý
do phải `cp .env` thủ công như bước trên, và giao diện được build lại trên máy chủ.

## Đưa ra Internet + tên miền

Trước tiên kiểm tra máy chủ có IP công khai thật hay không (chạy trên server):

```bash
curl -s https://ifconfig.me; echo          # IP mà Internet nhìn thấy
ip -4 addr show | grep inet                 # IP trên card mạng của máy
```

Nếu IP ở card mạng là dạng **riêng tư** (`192.168.x`, `10.x`, `172.16–31.x`, `100.64–127.x`)
hoặc khác với `ifconfig.me`, nghĩa là máy **nằm sau NAT/CGNAT** — rất phổ biến với cáp
quang doanh nghiệp ở VN. Khi đó không thể "trỏ A record thẳng vào máy" được.

Có hai đường:

### Cách A — Cloudflare Tunnel (khuyến nghị cho máy vật lý sau NAT)

Miễn phí, tự có HTTPS, dùng tên miền riêng, **không cần IP công khai, không mở cổng router**.
Chỉ cần máy ra được Internet.

1. Có sẵn tên miền (vd `hdslaw.vn`). Tạo tài khoản **Cloudflare** (free) → Add site →
   `hdslaw.vn` → đổi **nameserver** ở nhà cung cấp tên miền sang cặp Cloudflare cho.
2. Cloudflare dashboard → **Zero Trust → Networks → Tunnels → Create a tunnel** →
   chọn **Cloudflared** → đặt tên (vd `hds`). Nó hiện một lệnh cài kèm token — copy chạy
   trên server:
   ```bash
   # ví dụ (lệnh thật lấy từ dashboard, đã kèm token của bạn):
   curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb -o cloudflared.deb
   sudo dpkg -i cloudflared.deb
   sudo cloudflared service install <TOKEN-TỪ-DASHBOARD>
   ```
3. Vẫn trong tunnel đó → **Public Hostname → Add**:
   - Subdomain `app`, Domain `hdslaw.vn`
   - Service: **HTTP** → `localhost:80`
4. Xong. `https://app.hdslaw.vn` chạy, HTTPS tự động. Chạy `setup.sh` **để trống tên miền**
   (nginx nghe cổng 80 nội bộ, tunnel trỏ vào đó) — **không** dùng certbot.

### Cách B — IP công khai thật (VPS, hoặc ISP cấp IP tĩnh + mở cổng)

Chỉ khả thi khi `ifconfig.me` = IP máy và bạn mở được cổng 80/443 ra Internet
(VPS thuê thì có sẵn; máy văn phòng thì phải xin ISP cấp **IP tĩnh công khai** + NAT
port-forward 80,443 trên router về máy).

1. Tạo bản ghi **A**: `app.hdslaw.vn → <IP công khai>`. Kiểm tra: `dig +short app.hdslaw.vn`.
2. Chạy `sudo bash deploy/setup.sh` và điền tên miền — certbot tự cấp HTTPS. (Nếu chạy
   trước khi DNS kịp trỏ: sau đó `sudo certbot --nginx -d app.hdslaw.vn`.)

Chưa cần tên miền vẫn dùng được ngay qua `http://<IP nội bộ hoặc Tailscale>`.

### Máy chủ truy cập qua Tailscale (IP dạng 100.x, không có IP công khai)

Let's Encrypt công khai **không cấp được** cho máy chỉ có trong Tailscale. Hai lựa chọn:

- **Dùng HTTP qua Tailscale (đơn giản nhất):** chạy `setup.sh`, để trống tên miền. Truy
  cập `http://<tailscale-ip>` (vd `http://100.101.107.89`). Lưu lượng đã được Tailscale
  mã hoá sẵn nên HTTP trong mạng này là chấp nhận được cho dùng nội bộ.
- **Muốn HTTPS + tên đẹp:** dùng Tailscale Serve (cần bật HTTPS trong bảng điều khiển
  Tailscale › DNS › MagicDNS + HTTPS Certificates):
  ```bash
  sudo tailscale serve --bg 80          # đưa nginx (cổng 80) ra HTTPS của Tailscale
  ```
  Địa chỉ sẽ là `https://<tên-máy>.<tailnet>.ts.net`. Khi đó **không** chạy certbot.

Muốn dùng tên miền công ty thật (`app.hdslaw.vn`) với HTTPS Let's Encrypt thì máy chủ
phải có **IP công khai** và mở cổng 80/443 ra Internet — không thể chỉ nằm trong Tailscale.

## Ollama (phần Hỏi đáp AI)

Đăng nhập và toàn bộ khu Quản trị chạy được **không cần Ollama**. Riêng phần hỏi đáp AI cần nó:

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen3:14b
ollama pull bge-m3
```

## Dạy bot học tài liệu (train)

Bot tự học **mỗi file mới thả vào Google Drive** theo cấu trúc thư mục:

| Tài liệu | Nội dung |
|---|---|
| [**CAU_TRUC_DRIVE.md**](CAU_TRUC_DRIVE.md) | **Cây thư mục Drive chuẩn** — làm cái này trước |
| [TRAIN_DRIVE.md](TRAIN_DRIVE.md) | Tạo service account, cấp quyền, bật lịch tự học |
| [LUU_TRU_DU_LIEU.md](LUU_TRU_DU_LIEU.md) | Sơ đồ luồng dữ liệu, dữ liệu AI nằm ở đâu, sao lưu |
| [API_KHACH_HANG.md](API_KHACH_HANG.md) | Cấp khoá API cho khách, phạm vi 3 gói Free/Plus/Pro |

```bash
bash deploy/auto-learn.sh --dry-run              # xem sẽ học gì
bash deploy/auto-learn.sh                          # học một lần
sudo bash deploy/auto-learn.sh --install-timer     # tự học mỗi 15 phút
```

### Kiểm tra kho đã học có ổn không

```bash
bash deploy/kiem-tra-vector.sh
```

Chỉ đọc và báo cáo, không sửa gì. Nó trả lời: pgvector đã cài chưa, chỉ mục
còn không, có đoạn nào thiếu vector không, model tạo vector còn chạy không, và
**tài liệu nào có trong Drive mà chưa học được**.

### Bot nói "không có thông tin" về một người, dù giấy tờ nằm sẵn trên Drive

Gần như luôn là **giấy tờ vào kho nhưng không có chữ** (bản scan mờ, PDF nhiều
cột, thiếu công cụ OCR), chứ không phải tìm kiếm sai. Soi thẳng bộ hồ sơ đó:

```bash
bash deploy/soi-ho-so.sh Mai
```

Mỗi giấy tờ hiện ra kèm số ký tự đọc được. Dòng đỏ = gần như không có chữ →
script tự kiểm tra luôn `tesseract`, gói tiếng Việt và `poppler` trên máy chủ
rồi in lệnh cài nếu thiếu. Muốn xem bot thật sự đọc được gì trong một giấy tờ:

```bash
bash deploy/soi-ho-so.sh Mai --xem 137
```

Chạy không kèm tên để liệt kê tất cả các bộ hồ sơ đang có.

**Giấy tờ có chữ nhưng là chữ hỏng.** Bản scan mờ hoặc có nền hoa văn (CCCD,
bằng cấp) cho ra ký tự vụn kiểu `bai bel La n Å l Å _ ¬ s ,ã bô`. Bot **không**
dùng những đoạn như vậy làm căn cứ nữa — nó nhận ra và nói thẳng là chưa đọc
được file, thay vì suy đoán. Để đọc lại cho tử tế:

```bash
bash deploy/hoc-lai-file.sh --hong        # CHỈ file đọc hỏng — nên dùng
bash deploy/hoc-lai-file.sh --pdf --thu   # xem trước: tất cả PDF, chưa xoá gì
bash deploy/hoc-lai-file.sh --pdf         # đọc lại toàn bộ PDF
bash deploy/hoc-lai-file.sh --bo Mai      # một bộ hồ sơ nhân sự
bash deploy/hoc-lai-file.sh 567 573       # theo mã tài liệu
```

`--hong` tự tìm file có chữ hỏng: bản trích xuất mang cảnh báo, hoặc nội dung
chứa chữ của bảng mã khác (Å, Ø, ƒ, Ð) — thứ gần như không bao giờ có trong hồ
sơ tiếng Việt thật. Đây là lựa chọn nên dùng: nó bỏ qua các PDF vốn đã đọc tốt,
nên nhanh hơn `--pdf` rất nhiều và không làm xáo trộn phần kho đang chạy ổn.

Trước khi xoá, script luôn sao lưu hai bảng `documents`/`chunks`, in danh sách
và bắt gõ xác nhận. Trạng thái duyệt được ghi nhớ rồi **trả lại cho những file
lần này đọc sạch**; file scan mang cảnh báo vẫn phải qua người duyệt vì nội
dung đã khác đi. Tài liệu tải lên qua web (không có trên Drive) được bỏ qua —
xoá chúng là mất hẳn, không có nguồn nào để học lại.

Thêm `--thu` để chỉ xem danh sách và ước lượng khối lượng. Chạy `--pdf` trên
kho lớn có thể mất hàng giờ (mỗi đoạn tạo lại vector, bản scan còn phải OCR
400 dpi), nên làm ngoài giờ và cân nhắc `nohup`/`tmux`.

Bộ đọc hiện tại dùng 400 dpi kèm xám hoá + kéo giãn tương phản, thường cứu được
phần lớn bản scan kém. Nếu vẫn hỏng thì bản gốc quá mờ: thay bản scan rõ hơn
trên Drive, hoặc vào Quản trị → Kiểm duyệt → "Xem & sửa nội dung trích xuất"
gõ tay phần quan trọng.

### Tài liệu có trong Drive nhưng bot không đọc được

Xem ở **Quản trị → Kho tài liệu đã học**, khối đỏ trên cùng. Mỗi dòng ghi rõ
tên tệp, vị trí trong Drive, lý do, **cách sửa**, và đã thử bao nhiêu lần.

Khối này giữ lỗi cho tới khi tệp học được — khác báo cáo "lần quét gần nhất"
vốn chỉ hiện những tệp vừa được đụng tới. Trước đây một tệp hỏng từ ba lần quét
trước sẽ biến mất khỏi báo cáo (lần sau nó không đổi nên không được học lại) và
không ai biết là kho đang thiếu.

### Cách bot cắt đoạn tài liệu

Đoạn **không có kích thước cố định**. Thứ tự ưu tiên khi cắt:

1. **Tiêu đề mục** — `Điều 5`, `CHƯƠNG II`, `1.1.`, dòng viết hoa toàn bộ, dòng
   ngắn kết thúc bằng dấu hai chấm. Đây là ranh giới do chính tác giả đặt ra.
2. **Câu trọn vẹn** — không bao giờ cắt giữa câu. Viết tắt tiếng Việt (`NĐ.`,
   `TP.`, `ông.`) không bị hiểu nhầm là hết câu.
3. **Chỗ chuyển ý** — mục dài hơn ngân sách thì tìm điểm ngắt ở chỗ hai bên
   dùng chung ít từ nhất, tức chỗ chủ đề chuyển.

Nhờ vậy một sơ yếu lý lịch một trang giữ nguyên một đoạn, còn một bộ luật thì
tách theo từng Điều. Văn bản luật (`doc_type=law`) đi theo nhánh riêng, mỗi đoạn
mang sẵn số hiệu văn bản + Chương/Mục/Điều.

Khi tra cứu, đoạn khớp nhất được kèm thêm **đoạn liền trước và liền sau** để câu
trả lời không bị cụt ở chỗ ý vắt sang đoạn kế (điều kiện ở đoạn này, ngoại lệ ở
đoạn sau).

### Học lại toàn bộ từ đầu

Cần khi vừa đổi cách tách đoạn, hoặc nghi kho vector bị lỗi:

```bash
sudo bash deploy/hoc-lai-tu-dau.sh
```

Script tự sao lưu hai bảng `documents`/`chunks` trước khi xoá, hỏi xác nhận
bằng cách gõ `XOA`, rồi học lại toàn bộ từ Drive. **Tệp gốc trên Drive không bị
đụng tới**; lịch sử hội thoại, ghi chú, bản nháp, khách hàng, vụ việc cũng giữ
nguyên. Kho vài trăm tài liệu có thể mất nhiều giờ — nên chạy ngoài giờ làm.

## Soạn tài liệu từ mẫu (tab Soạn tài liệu + lệnh chat)

Ba đường tạo một bản nháp giấy tờ (HĐLĐ, quyết định, thư…), đều ra **DOCX tải
được ngay** — chỗ thiếu dữ liệu tự đánh dấu `[CẦN BỔ SUNG: …]`:

1. **Từ chat** (nhân viên nội bộ):
   - `tạo hợp đồng lao động cho Ngân` → bám **mẫu chuẩn** trong ngăn
     `4. HỢP ĐỒNG MẪU` / `6. THƯ MẪU - BIỂU MẪU`, điền dữ liệu đã xác minh
     của Ngân (sổ nhân sự + hồ sơ trong `8. HỒ SƠ NHÂN SỰ/Ngân/`).
   - `tạo hợp đồng lao động cho Ngân như của Nhi` → bám đúng bản của Nhi
     làm mẫu, thay thông tin cá nhân.
   - Thiếu mẫu/hồ sơ thì bot nói rõ thiếu gì và thả file vào thư mục nào.
2. **Tab Soạn tài liệu → Tạo bản nháp**: chọn mẫu, chọn nguồn, bấm Sinh nội
   dung. Nút **"Tự điền từ hồ sơ"** nhận CCCD / sơ yếu lý lịch / CV
   (PDF, **ảnh chụp**, DOCX) — hệ thống OCR rồi bóc họ tên, ngày sinh, số
   CCCD, địa chỉ… điền sẵn vào biểu mẫu (file bóc xong bỏ, không vào kho).
3. **Điền chỗ trống**: mở bản nháp → nút "Điền chỗ trống (N)" liệt kê từng
   `[CẦN BỔ SUNG]` để gõ giá trị, lưu thành phiên bản mới rồi **Tải DOCX**.

Bản nháp chưa phê duyệt vẫn tải được (để in ra điền tiếp); trạng thái nháp ghi
trong file và header `X-Draft-Status`. Phê duyệt mới khoá phiên bản.

## Bot trả lời chậm / lỗi 524

```bash
bash deploy/kiem-tra-toc-do.sh
```

Script báo GPU hay CPU, model có nằm sẵn trong bộ nhớ không, và **đo tốc độ thật**
của máy chủ (đọc bao nhiêu token/giây, viết bao nhiêu token/giây), rồi ước tính
một câu hỏi sẽ mất bao lâu. Trên 100 giây là Cloudflare cắt → lỗi 524.

Công thức chi phối mọi thứ:

```
thời gian trả lời ≈ (số token prompt ÷ tốc độ đọc) + (số token đáp ÷ tốc độ viết)
```

Trong đó **độ dài prompt là thứ chỉnh được ngay** ở web → Quản trị → Cài đặt AI →
Tham số (`Trần ký tự tài liệu`, `Số đoạn tham chiếu`, `Số lượt hỏi-đáp cũ`), còn
tốc độ đọc/viết là do phần cứng.

Lượng tài liệu đã học **không** nằm trong công thức: tra cứu vector luôn trả về
đúng `top_k` đoạn, nên kho phình từ 100 lên 1 triệu tài liệu cũng không làm câu
trả lời chậm thêm.

### Trả lời chảy dần (streaming)

Khung chat hiện chữ ngay khi model viết ra, thay vì chờ xong cả bài. Không làm
máy nhanh hơn một mili-giây nào, nhưng đổi hẳn cảm giác chờ — và **chấm dứt lỗi
524**, vì Cloudflare tính giờ từ byte đầu tiên của phản hồi chứ không phải byte
cuối.

Đường đi: `POST /chat/stream` (Server-Sent Events) → nginx → Cloudflare → trình
duyệt. Mắt xích dễ hỏng nhất là **nginx gom phản hồi**; `deploy/update.sh` tự vá
`proxy_buffering off` vào cấu hình cũ, có sao lưu và tự hoàn tác nếu `nginx -t`
báo sai.

Kiểm tra streaming có thật sự tới trình duyệt không:

```bash
curl -N -X POST https://app.diginix.io.vn/api/chat/stream \
  -H "Authorization: Bearer <token>" -H 'Content-Type: application/json' \
  -d '{"question":"thời hiệu khởi kiện là bao lâu"}'
```

Chữ phải hiện dần từng dòng `data: {...}`. Nếu im lặng rồi đổ ra một lượt thì
còn chỗ nào đó đang đệm — kiểm `proxy_buffering` trong
`/etc/nginx/sites-available/hds-ai`.

Ba kênh cũ (`/chat/internal`, `/chat/portal`, `/chat/public`) vẫn giữ nguyên, trả
một cục như trước — dành cho khách gọi qua API.

**Cái bẫy prefill (đã xử lý).** Ngay cả khi streaming, vẫn có một khoảng lặng dài
NGAY SAU khi hiện nguồn trích dẫn: model đang ĐỌC toàn bộ prompt (prefill), trên
máy CPU mất cả trăm giây và không đẩy byte nào ra. Cloudflare thấy kết nối im quá
~100 giây liền cắt → "network error" trước khi có chữ. `/chat/stream` gửi "nhịp
tim" vô hình mỗi 15 giây trong quãng này để giữ kết nối sống. Nếu vẫn thấy network
error sau khi hiện nguồn, kiểm tra `proxy_read_timeout` (phải ≥ 320s) và bảo đảm
`proxy_buffering off` — nginx gom byte thì nhịp tim cũng bị chặn.

### Nạp lại model — cái bẫy hay bị bỏ sót

Mỗi câu hỏi dùng **hai** model: `bge-m3` hiểu câu hỏi, rồi model kia viết câu trả
lời. Nếu bộ nhớ không chứa nổi cả hai, Ollama đẩy cái này ra để nạp cái kia — và
lặp lại ở câu sau. Khi đó `keep_alive` đặt bao lâu cũng vô nghĩa. Mục 4 của script
kiểm tra đúng điều này.

Ứng dụng gửi `keep_alive=30m` mỗi lần gọi nên model nằm lại 30 phút sau lần dùng
cuối. Muốn giữ lâu hơn (máy dư RAM), đặt biến môi trường trước khi chạy backend:

```bash
OLLAMA_KEEP_ALIVE=-1   # giữ mãi, chỉ nên dùng khi RAM chứa được cả hai model
```

Trong ô chọn model ở khung chat, `●` là model đang nằm sẵn (trả lời được ngay),
`○` là model phải nạp từ ổ cứng trước.

Trong khung chat, bấm vào con số thời gian cạnh mỗi câu trả lời để xem thời gian
đi vào chặng nào — dòng **Nạp model** chính là chi phí nạp lại. Xem lại các câu
chậm đã qua:

```bash
sudo journalctl -u hds-ai-backend -n 200 | grep CHAM
```

## Cập nhật khi có mã mới

```bash
cd hds-ai-full
git pull
sudo bash deploy/update.sh
```

## Vận hành

| Việc | Lệnh |
| --- | --- |
| Trạng thái backend | `systemctl status hds-ai-backend` |
| Xem log backend | `journalctl -u hds-ai-backend -f` |
| Khởi động lại backend | `sudo systemctl restart hds-ai-backend` |
| Log CSDL | `docker compose -f hds-ai/docker-compose.yml logs` |
| Đổi mật khẩu / bí mật | sửa `hds-ai/.env` rồi `sudo systemctl restart hds-ai-backend` |

## Bí mật sinh tự động

`deploy/setup.sh` sinh sẵn `hds-ai/.env` với mật khẩu CSDL và `JWT_SECRET` ngẫu nhiên
(không có mật khẩu nào nằm trong mã nguồn). Chạy lại script **không** xoay lại các bí mật
đã có. Muốn tạo lại toàn bộ từ đầu (xoá cả dữ liệu):

```bash
cd hds-ai && docker compose down -v && rm -f .env && cd ..
sudo bash deploy/setup.sh
```

## Xử lý sự cố nhanh

- **Trang trắng / 403**: mã nguồn có nằm trong `/root/` không? Chuyển sang `/home` hoặc `/opt`.
- **Hỏi đáp AI báo lỗi**: Ollama chưa chạy hoặc chưa `ollama pull` model.
- **Đăng nhập lỗi 500**: xem `journalctl -u hds-ai-backend -n 40` — thường do `.env` thiếu biến.
- **HTTPS không cấp được**: DNS chưa trỏ đúng IP; sửa xong chạy `sudo certbot --nginx -d <domain>`.
- **502 Bad Gateway**: backend chưa lên; `sudo systemctl restart hds-ai-backend`.
