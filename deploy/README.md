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
- **RAM ≥ 16 GB** nếu chạy Ollama cùng máy (mô hình `qwen3:8b` + `bge-m3` khá nặng).
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
ollama pull qwen3:8b
ollama pull bge-m3
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
