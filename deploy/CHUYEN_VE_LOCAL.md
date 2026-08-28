# CHUYỂN KHO TÀI LIỆU TỪ GOOGLE DRIVE VỀ MÁY CHỦ

Quyết định 27/08/2026: **bỏ Google Drive, kho tài liệu nằm hẳn trên máy chủ HDS.**

Tài liệu này là quy trình chuyển đổi một lần. Sau khi làm xong, Drive không còn
vai trò gì trong hệ thống.

---

## 0. HIỂU ĐÚNG TRƯỚC KHI LÀM

**Bot chưa bao giờ đọc từ Drive.** Nó vẫn luôn đọc file trên đĩa máy chủ ở
`hds-ai/data/raw/`. Drive chỉ làm ba việc: chỗ nhân viên thả file, bản sao dự
phòng, và lịch sử phiên bản khi ai đó xoá nhầm.

Vì vậy chuyển đổi này **không đụng gì tới cách bot trả lời**. Việc thật sự phải
làm là **thay ba việc Drive đang gánh** bằng thứ khác:

| Drive đang gánh | Sau khi bỏ, thay bằng |
|---|---|
| Nhân viên kéo-thả file | **Ổ mạng Samba** trỏ vào thư mục kho (mục 2) |
| Bản sao khi ổ server hỏng | **Sao lưu `data/raw` hằng đêm ra ổ ngoài** (mục 6) — bắt buộc |
| Khôi phục file xoá nhầm | **Thùng rác Samba + bản sao lưu**; không còn "thùng rác 30 ngày" |

> ⚠ Sau bước này, thư mục kho là **bản gốc duy nhất** của tài liệu công ty.
> Không sao lưu = một lần ổ hỏng là mất hết. Đừng bỏ qua mục 6.

---

## 1. KÉO NỐT NHỮNG GÌ CÒN TRÊN DRIVE VỀ

`data/raw/` hiện chỉ chứa **file bot đọc được** (PDF, Word, Excel, ảnh) và có
trần dung lượng mỗi file. Trên Drive còn những thứ khác: video, `.zip`, `.pptx`,
file quá lớn. Kéo hết về trước khi ngắt:

```bash
cd /opt/hds-ai-full
sudo apt-get install -y rclone

# Xem trước sẽ tải gì, không ghi gì
ARCHIVE_DIR=$PWD/hds-ai/data/raw bash deploy/luu-tru-drive.sh --thu

# Tải thật — gộp vào đúng cây thư mục đang có, file trùng thì bỏ qua
ARCHIVE_DIR=$PWD/hds-ai/data/raw bash deploy/luu-tru-drive.sh
```

Cây thư mục trên Drive và trong `data/raw` **giống hệt nhau** (bộ đồng bộ cũ giữ
nguyên cấu trúc), nên rclone gộp đúng chỗ, không tạo thư mục lồng.

Kiểm tra dung lượng sau khi kéo:

```bash
du -sh hds-ai/data/raw
df -h .
```

Không đủ chỗ thì chuyển kho sang ổ khác — xem mục 7.

---

## 2. DỰNG Ổ MẠNG CHO NHÂN VIÊN THẢ FILE

Không có bước này thì nhân viên không còn đường đưa tài liệu vào hệ thống.

```bash
sudo apt-get install -y samba
sudo nano /etc/samba/smb.conf
```

Thêm vào cuối file:

```ini
[KhoTaiLieu]
   path = /opt/hds-ai-full/hds-ai/data/raw
   browseable = yes
   read only = no
   valid users = @hdsstaff
   create mask = 0664
   directory mask = 0775
   # Xoá nhầm còn cứu được — thay cho thùng rác của Drive
   vfs objects = recycle
   recycle:repository = .thung-rac/%U
   recycle:keeptree = yes
   recycle:versions = yes
```

```bash
sudo groupadd hdsstaff
sudo useradd -M -s /usr/sbin/nologin ten.nhanvien && sudo usermod -aG hdsstaff ten.nhanvien
sudo smbpasswd -a ten.nhanvien          # đặt mật khẩu truy cập ổ mạng
sudo chgrp -R hdsstaff /opt/hds-ai-full/hds-ai/data/raw
sudo chmod -R g+rw /opt/hds-ai-full/hds-ai/data/raw
sudo systemctl restart smbd
```

Nhân viên nối ổ trên Windows: `\\<IP máy chủ>\KhoTaiLieu` → chuột phải *Map
network drive* để nó hiện như ổ Z:.

> Thư mục `.thung-rac` do Samba tạo bắt đầu bằng dấu chấm nên **bộ quét tự bỏ
> qua** — file xoá nhầm nằm đó sẽ không bị học lại.
>
> Thư mục `uploads/` bên trong kho là nơi hệ thống cất file tải lên qua web.
> Bộ quét bỏ qua nó; **đừng để nhân viên thả tài liệu vào đó**.

---

## 3. NGẮT DRIVE TRƯỚC — THỨ TỰ NÀY BẮT BUỘC

> **Vì sao phải ngắt trước khi chuyển đổi:** bộ quét Drive chạy nền mỗi 15 phút.
> Nếu nó chạy xen vào giữa lúc đang gắn lại danh tính, nó sẽ không nhận ra tài
> liệu vừa đổi và học lại chúng lần nữa — kho nhân đôi. Lệnh chuyển đổi sẽ **từ
> chối chạy** khi thấy `DRIVE_FOLDER_ID` còn trong `.env`.

```bash
cd /opt/hds-ai-full

# 1. Gỡ lịch học từ Drive
sudo bash deploy/auto-learn.sh --remove-timer

# 2. Bỏ khai báo Drive khỏi .env → đây là công tắc chính
sudo nano hds-ai/.env
#    · xoá dòng DRIVE_FOLDER_ID=... (hoặc để trống)
#    · thêm  DATA_LIB=./data/raw   (bỏ qua cũng được, mặc định đã là nó)
```

---

## 4. CHUYỂN ĐỔI DỮ LIỆU (một lần, bắt buộc)

Tài liệu đã học đang được đánh dấu bằng mã file Drive. Phải gắn lại danh tính
theo đường dẫn trong kho, **nếu không lần quét đầu tiên sẽ coi mọi file là mới
và học lại từ đầu** — kho nhân đôi, trích dẫn nhân đôi. Bộ quét đã được lập
trình để **từ chối chạy** khi chưa chuyển đổi, nhưng đừng dựa vào đó.

```bash
cd /opt/hds-ai-full/hds-ai

# 1. Xem trước: bao nhiêu tài liệu sẽ được gắn lại
.venv/bin/python -m app.local_learn --chuyen-doi --dry-run

# 2. Làm thật
.venv/bin/python -m app.local_learn --chuyen-doi
```

Đọc kỹ kết quả in ra:

- `N/M tài liệu đã gắn lại danh tính local` — **hai số phải bằng nhau**.
- `N tài liệu có tệp nằm NGOÀI kho` — bình thường (tài liệu nạp từ hội thoại,
  hoặc file tải lên qua web nằm ngoài `DATA_LIB`); bộ quét không đụng tới chúng.
- `[DỪNG] N tài liệu KHÔNG gắn lại được vì danh tính đã bị bản ghi khác chiếm`
  — **có bản trùng trong kho**, thường do một lượt quét đã chạy trước bước này.
  Xử lý trước khi đi tiếp (xem mục 9).

Kiểm chứng bằng SQL — số này phải bằng **0**:

```bash
docker exec -i hds-postgres psql -U hds -d hdsai -tAX -c \
  "SELECT count(*) FROM documents WHERE drive_file_id IS NOT NULL AND drive_file_id NOT LIKE 'local:%';"
```

---

## 5. BẬT BỘ QUÉT THƯ MỤC

```bash
cd /opt/hds-ai-full/hds-ai
.venv/bin/python -m app.local_learn --dry-run     # chỉ liệt kê, không ghi gì
```

Bản in ra phải cho thấy **hầu hết file là "không đổi"**. Nếu thấy hàng loạt dòng
`[MỚI]` thì bước 4 chưa chạy hoặc `DATA_LIB` trỏ sai thư mục — **dừng lại, đừng
chạy thật**.

Ổn rồi thì bật lịch:

```bash
cd /opt/hds-ai-full
sudo bash deploy/hoc-tu-thu-muc.sh --install-timer   # quét mỗi 15 phút
systemctl list-timers hds-ai-quet-kho.timer
journalctl -u hds-ai-quet-kho.service -n 40 --no-pager
```

Lệnh cài lịch cũng **tự tắt** lịch học Drive cũ nếu còn.

Kiểm tra trên web: **Quản trị → Kho tài liệu đã học** → thẻ trạng thái phải đổi
tiêu đề thành **“Quét kho tài liệu trên máy chủ”** kèm đường dẫn thư mục.

---

## 6. SAO LƯU — BẮT BUỘC TỪ LÚC NÀY

Trước đây mất `data/raw` chỉ mất chức năng tải bản gốc, vì Drive còn giữ. **Giờ
không còn ai giữ hộ.** Sao lưu cả hai thứ:

```bash
mkdir -p /backup && chmod 700 /backup
sudo crontab -e
```

```cron
# 02:30 — cơ sở dữ liệu (tri thức, vector, hội thoại, phân quyền)
30 2 * * * /usr/bin/docker exec hds-postgres pg_dump -U hds -Fc hdsai > /backup/hdsai_$(date +\%F).dump 2>>/backup/pg_dump.err

# 03:00 — kho tài liệu (BẢN GỐC DUY NHẤT) ra ổ ngoài đã mount ở /mnt/backup
0 3 * * * /usr/bin/rsync -a --delete /opt/hds-ai-full/hds-ai/data/raw/ /mnt/backup/kho-tai-lieu/ 2>>/backup/rsync.err

# 04:00 chủ nhật — xoá dump cũ hơn 60 ngày
0 4 * * 0 /usr/bin/find /backup -name 'hdsai_*.dump' -mtime +60 -delete
```

Chép tay và cất nơi an toàn: `hds-ai/.env`. (Không còn cần
`credentials/service-account.json` sau khi bỏ Drive — nhưng đừng xoá vội, giữ
tới khi chắc chắn không quay lại.)

**Mỗi tháng thử phục hồi một lần.** Bản sao lưu chưa từng thử phục hồi thì chưa
phải bản sao lưu.

---

## 7. NẾU MUỐN ĐẶT KHO Ở Ổ KHÁC

Ổ 512 GB gốc sẽ chật. Chuyển kho sang ổ thứ hai:

```bash
sudo systemctl stop hds-ai-quet-kho.timer
sudo rsync -a /opt/hds-ai-full/hds-ai/data/raw/ /mnt/data2/kho/
sudo nano /opt/hds-ai-full/hds-ai/.env      # DATA_LIB=/mnt/data2/kho
```

Đường dẫn cũ vẫn còn trong cột `source_path` của các tài liệu đã học, nên phải
cập nhật để nút **Tải về / Xem trước** không hỏng:

```bash
docker exec -i hds-postgres psql -U hds -d hdsai -c \
  "UPDATE documents SET source_path = replace(source_path, '/opt/hds-ai-full/hds-ai/data/raw', '/mnt/data2/kho') WHERE source_path LIKE '/opt/hds-ai-full/hds-ai/data/raw%';"
```

Rồi sửa `path` trong `smb.conf`. **Không cần** chạy lại `--chuyen-doi`: danh
tính tài liệu là đường dẫn TƯƠNG ĐỐI trong kho nên đổi gốc không ảnh hưởng, và
lượt chạy thứ hai chỉ quét những bản ghi chưa mang tiền tố `local:` — sau lần
đầu là rỗng, không có gì để làm.

**Rào an toàn của nút Tải về / Xem trước** đọc CẢ HAI biến `DATA_LIB` và
`DATA_RAW` (hàm `local_learn.allowed_roots()`), nên chỉ cần `DATA_LIB` trỏ đúng
thư mục kho mới là xong — không phải nhét kho vào trong `DATA_RAW`.

Sửa `.env` xong **bắt buộc khởi động lại backend** rồi mới kiểm tra: biến môi
trường chỉ được đọc một lần lúc tiến trình khởi động (`load_dotenv()` ở đầu
module), nên uvicorn đang chạy vẫn giữ `DATA_LIB` cũ và nút Tải về vẫn 404.

```bash
sudo systemctl restart hds-ai-backend
cd /opt/hds-ai-full/hds-ai && .venv/bin/python -c "from app.local_learn import allowed_roots; print(allowed_roots())"
```

Đường dẫn kho phải có trong danh sách in ra. Thiếu nó thì nút Tải về trả 404
"Tệp gốc không còn trên máy chủ" cho toàn bộ tài liệu.

> Backend chạy bằng **systemd + venv** (`hds-ai-backend.service`), không phải
> container — `docker compose` trên máy này chỉ dựng mỗi Postgres.

Cách gọn nhất là mount ổ mới **vào đúng chỗ cũ** (`/opt/hds-ai-full/hds-ai/data/raw`)
thay vì đổi đường dẫn — khi đó không phải sửa gì cả.

---

## 8. SAU KHI CHUYỂN XONG

Quy trình hằng ngày của nhân viên đổi một chỗ duy nhất: **thả file vào ổ mạng
`Z:\` thay vì Google Drive**. Cây thư mục, quy tắc đặt tên thư mục khách
`[MÃ] Tên khách`, và bước duyệt nhãn trên web **giữ nguyên không đổi** — xem
[CAU_TRUC_DRIVE.md](CAU_TRUC_DRIVE.md).

Việc cần theo dõi tuần đầu:

- **Quản trị → Kho tài liệu đã học**: thẻ “Quét lần cuối” phải trong vòng 15 phút.
- Danh sách vàng *“chưa xác định được nhãn”* — thường do nhân viên tạo thư mục
  mới không đúng quy ước.
- Danh sách đỏ *“bot chưa đọc được”* — file scan mờ.
- Mục **“tài liệu còn trong kho tri thức nhưng KHÔNG còn tệp trong thư mục”**
  trong log lần quét: dấu hiệu ai đó xoá file khỏi ổ mạng. Bot vẫn trả lời bằng
  nội dung đã học. Muốn gỡ hẳn khỏi kho tri thức thì hiện phải làm bằng SQL
  (xem mục 9) — giao diện web chưa có nút xoá tài liệu.

---

## 9. XỬ LÝ SỰ CỐ

### Quay lại dùng Drive

```bash
cd /opt/hds-ai-full/hds-ai
.venv/bin/python -m app.local_learn --chuyen-doi --nguoc   # trả lại mã Drive cũ
sudo nano .env                                             # khai lại DRIVE_FOLDER_ID
cd .. && sudo bash deploy/hoc-tu-thu-muc.sh --remove-timer
sudo bash deploy/auto-learn.sh --install-timer
```

Bộ quét Drive **từ chối chạy** khi kho còn tài liệu mang danh tính local, nên
bước `--nguoc` là bắt buộc; nó dùng cột `prev_source_key` đã lưu lúc chuyển đổi.

### Lỡ quét trước khi chuyển đổi → kho có bản trùng

Triệu chứng: `--chuyen-doi` báo `[DỪNG] N tài liệu KHÔNG gắn lại được`. Đếm số
bản trùng:

```bash
docker exec -i hds-postgres psql -U hds -d hdsai -c "
  SELECT source_path, count(*) FROM documents
   WHERE source_path IS NOT NULL GROUP BY source_path HAVING count(*) > 1;"
```

Xoá bản **cũ** (mang mã Drive), giữ bản mang danh tính `local:` — bản local mới
là bản khớp với tệp trên đĩa:

```bash
docker exec -i hds-postgres psql -U hds -d hdsai -c "
  DELETE FROM documents d
   WHERE d.drive_file_id IS NOT NULL
     AND d.drive_file_id NOT LIKE 'local:%'
     AND EXISTS (SELECT 1 FROM documents x
                  WHERE x.source_path = d.source_path
                    AND x.drive_file_id LIKE 'local:%');"
```

Chunks tự xoá theo. Sau đó chạy lại `--chuyen-doi` rồi `--dry-run` để xác nhận.
**Sao lưu CSDL trước khi chạy lệnh xoá.**

### Gỡ hẳn một tài liệu không còn tệp

```bash
docker exec -i hds-postgres psql -U hds -d hdsai -c \
  "UPDATE documents SET active=false WHERE id=123;"   # bot ngừng dùng, dữ liệu còn
```

Dùng `active=false` thay vì `DELETE`: bot ngừng trích dẫn ngay, nhưng lịch sử
hội thoại cũ không hỏng và còn đường bật lại.

### Bộ quét báo dừng

| Thông báo | Nghĩa | Xử lý |
|---|---|---|
| `[DỪNG] N tài liệu vẫn mang danh tính Drive` | Chưa chạy bước 4 | Chạy `--chuyen-doi` |
| `[DỪNG] Kho chỉ thấy N tệp trong khi đã học M` | Ổ chưa mount hoặc mất quyền đọc | `mount \| grep <đường dẫn>`, kiểm tra quyền |
| `[DỪNG] .env vẫn còn DRIVE_FOLDER_ID` | Chưa làm bước 3 | Gỡ timer Drive + xoá dòng đó |
| `N tài liệu đang phục vụ vừa rơi lại hàng chờ duyệt` | File sửa nội dung; PDF luôn phải duyệt lại | Vào **Duyệt nhãn tài liệu** duyệt lại |
