# Cấu trúc Google Drive chuẩn cho HDS AI

Bám theo phong cách đánh số tiếng Việt bạn đang dùng (`1. HỒ SƠ KHÁCH HÀNG`,
`Văn bản pháp luật`) và 4 nhóm nguồn trong *260725. HDS. Nguồn tài liệu pháp luật*.

**Tên thư mục CHÍNH LÀ nhãn phân loại + mức bảo mật.** Thả file đúng chỗ là xong —
không phải vào web bấm gì. Bot chuẩn hoá tên trước khi so khớp (bỏ số thứ tự, bỏ dấu,
hạ chữ thường) nên `1. VĂN BẢN PHÁP LUẬT` = `Văn bản pháp luật` = `van ban phap luat`.
**Đánh số lại thư mục không làm hỏng gì.**

---

## Cây thư mục đầy đủ

Tạo **một** thư mục gốc, chia sẻ nó cho service account, và trỏ `DRIVE_FOLDER_ID` vào đó.

```
HDS. CƠ SỞ DỮ LIỆU/                        ← DRIVE_FOLDER_ID trỏ vào thư mục NÀY
│
├── 1. VĂN BẢN PHÁP LUẬT/                  → law · CÔNG KHAI
│   ├── 1.1 Luật - Bộ luật/                  (nguồn: chinhphu.vn, vbpl.vn)
│   ├── 1.2 Nghị định/
│   ├── 1.3 Thông tư/
│   ├── 1.4 Nghị quyết - Quyết định/
│   └── 1.5 Văn bản hợp nhất/
│
├── 2. BẢN ÁN - ÁN LỆ/                     → NỘI BỘ
│   ├── 2.1 Án lệ/                         → an_le   (anle.toaan.gov.vn)
│   └── 2.2 Bản án/                        → ban_an  (congbobanan.toaan.gov.vn)
│
├── 3. HỢP ĐỒNG MẪU/                       → mau_hd · NỘI BỘ
│   ├── 3.1 Doanh nghiệp - Đầu tư/           (lawinsider, moj.gov.vn, bvntd.gov.vn)
│   ├── 3.2 Thương mại/
│   ├── 3.3 Lao động/
│   ├── 3.4 Đất đai - Xây dựng/
│   └── 3.5 Sở hữu trí tuệ/
│
├── 4. QUAN ĐIỂM PHÁP LÝ/                  → advisory · NỘI BỘ
│   ├── 4.1 Nghiên cứu - Trao đổi/           (moj.gov.vn, danchuphapluat.vn)
│   ├── 4.2 Hướng dẫn nghiệp vụ/             (phapdien.moj.gov.vn)
│   └── 4.3 Ý kiến pháp lý HDS/              (bản do HDS soạn)
│
├── 5. THƯ MẪU - BIỂU MẪU/                 → thu_mau · NỘI BỘ
│   ├── 5.1 Thư tư vấn mẫu/
│   ├── 5.2 Đơn - Tờ khai/
│   └── 5.3 Biểu mẫu nội bộ/
│
├── 6. QUY TRÌNH NỘI BỘ/                   → quy_trinh · NỘI BỘ
│   ├── 6.1 Quy trình tiếp nhận vụ việc/
│   ├── 6.2 Quy trình tố tụng/
│   └── 6.3 Quy trình ĐKKD/
│
├── 7. NHÃN HIỆU - SHTT/                   → nhan_hieu · NỘI BỘ
│   ├── 7.1 Dữ liệu nhãn hiệu/
│   └── 7.2 Hướng dẫn đăng ký/
│
├── 8. HỒ SƠ NHÂN SỰ/                      → ho_so_ns · NỘI BỘ (hạn chế)
│
└── 9. HỒ SƠ KHÁCH HÀNG/                   → access_level = client
    │
    ├── [SUNGROUP] Tập đoàn SunGroup/      ← BẮT BUỘC có [MÃ_KHÁCH]
    │   ├── 1. Thông tin khách hàng/       → ho_so_kh   ★ FILE TỔNG HỢP
    │   ├── 2. Dự án - Vụ việc/
    │   │   ├── [M-2026-001] Tái cấu trúc vốn SunPhuQuoc/   ← tự gắn vụ việc
    │   │   └── [M-2026-014] Thuê đất thương mại/
    │   ├── 3. Hợp đồng/                   → contract
    │   ├── 4. Thư tư vấn/                 → advisory
    │   ├── 5. Hồ sơ nộp cơ quan/          → filing
    │   └── 6. Công nợ - Tài chính/        → cong_no  🔒 HẠN CHẾ
    │
    └── [VINAPHARMA] Công ty CP Vinapharma/
        └── ...
```

---

## Hai thư mục đặc biệt trong hồ sơ khách

**★ `1. Thông tin khách hàng/` — file tổng hợp, bot luôn đọc**

Đây là nơi bạn viết tổng quan về khách: dịch vụ đã dùng, mức phí, diễn biến hợp
tác, lưu ý riêng. Khác mọi tài liệu khác ở một điểm quan trọng:

> Khi câu hỏi nhắc tới khách này, bot **luôn nạp nguyên file tổng hợp** vào ngữ
> cảnh — không phụ thuộc vào việc tìm kiếm ngữ nghĩa có bắt được hay không.

Vì vậy hỏi *"khách SUNGROUP đã dùng dịch vụ gì, phí bao nhiêu"* là chắc chắn ra,
kể cả khi diễn đạt lệch so với chữ trong file. Các loại tài liệu khác thì vẫn
theo cơ chế tìm kiếm thông thường.

Chỉ kênh **nội bộ** được nạp file này. Cổng khách hàng không bao giờ thấy nó —
đây là tài liệu làm việc của HDS, không phải bản gửi khách.

**🔒 `6. Công nợ - Tài chính/` — chỉ người được cấp quyền**

Tài liệu trong thư mục này nhận nhãn `cong_no` và bị **chặn ở tầng CSDL**
(Row-Level Security), không phải chỉ ẩn trên giao diện. Người chưa được cấp
quyền thì:

- tra cứu không ra, kể cả hỏi vòng vo hay hỏi khéo;
- không thấy trong danh sách tài liệu, không tải về được;
- bot không hề biết tài liệu đó tồn tại nên không thể nhắc tới.

Cấp quyền: **Quản trị → Người dùng → nút "Không xem công nợ"** để bật thành
"Xem được công nợ". Vai `admin` luôn có sẵn. **Ban QT không tự động có** — phải
cấp như người khác, vì tài chính là nhóm dữ liệu tách riêng khỏi quyền xem
phòng ban.

Nếu bạn muốn cả công ty đọc được công nợ thì cứ để chung trong
`1. Thông tin khách hàng/`, đừng dùng thư mục này.

---

## Ba quy tắc bắt buộc

**1. Thư mục khách phải mang mã khách ở đầu tên — chấp nhận hai kiểu:**

- **Số đầu tên** (≥3 chữ số): `1729. Công ty Cổ phần Đại Hữu` → mã khách = `1729`.
  Hợp với cách HDS đang đánh mã khách sẵn.
- **Ngoặc vuông**: `[SUNGROUP] Tập đoàn SunGroup` → mã khách = `SUNGROUP`.

Bot tự tách mã, và **tự tạo bản ghi khách** nếu chưa có (lấy tên từ thư mục, để
trống phòng phụ trách — admin gán sau nếu cần). Không tách được mã (tên không có
số đầu cũng không có ngoặc) → **bot bỏ qua** để tránh gắn nhầm hồ sơ sang khách khác.

> Mã ở đây phải là **mã định danh khách**, không phải số thứ tự sắp xếp. `1729`,
> `1696` là mã khách — đúng. Còn `1.`, `2.` (một chữ số) bị coi là số thứ tự mục,
> không phải mã.

**2. Vụ việc cũng dùng ngoặc vuông: `[MÃ_VỤ_VIỆC] Tên vụ việc`**

Đặt trong `2. Dự án - Vụ việc/`. Mã khớp mã vụ việc trong hệ thống → tài liệu tự gắn đúng
vụ việc, hiện lên trong Hồ sơ khách 360°. Không có mã cũng không sao, chỉ là không tự gắn.

**3. Không để file trơ ở thư mục gốc**

File nằm ngoài các thư mục trên → bỏ qua kèm cảnh báo. Cứ chạy `--dry-run` để xem trước.

---

## Định dạng nhận được

| Nhận | Ghi chú |
|---|---|
| `.pdf` | PDF scan được **OCR tiếng Việt** tự động |
| `.docx` | Đọc cả bảng biểu |
| `.txt` `.md` | |
| `.xlsx` `.csv` | Giữ tên sheet/cột/dòng để tra cứu; sheet ẩn không được học tự động |
| Google Docs / Sheets | Tự xuất sang `.docx` / `.xlsx` rồi trích nội dung |

`.doc` cũ được chuyển bằng LibreOffice trên server; nếu chuyển lỗi, dashboard ghi mã lỗi
và giữ tài liệu cũ (nếu có). Nên lưu lại thành `.docx` để ổn định hơn.

File rỗng, file hỏng/đặt mật khẩu, PDF scan thiếu OCR, bảng tính quá lớn hoặc nội dung
quá ngắn đều được ghi rõ trong trạng thái đồng bộ. File có cảnh báo luôn vào hàng chờ
duyệt, kể cả khi đã bật tự duyệt.

Khi chia đoạn, bot giữ vị trí nguồn: số trang PDF, tiêu đề mục DOCX và tên sheet +
khoảng dòng XLSX/CSV. Phần trả lời có thể dùng các trường này để mở đúng nơi làm căn cứ,
thay vì chỉ dẫn về tên file chung chung.

Tên file nên giữ nguyên quy ước bạn đang dùng (`07_2022_QH15_458435.pdf`) — bot dùng tên
file làm tiêu đề tài liệu nên tên rõ ràng thì tra cứu dễ hơn.

---

## Thêm/đổi nhãn thư mục — không cần sửa code

Bản đồ *thư mục → nhãn* nằm trong **web: Quản trị → Cài đặt AI → Bản đồ thư mục Drive**
(khoá `drive_map`). Muốn thêm thư mục `10. HỢP ĐỒNG QUỐC TẾ` chỉ cần thêm một dòng:

```json
{
  "categories": {
    "hợp đồng quốc tế": { "doc_type": "contract", "access_level": "internal" }
  }
}
```

Khoá viết thường không dấu cũng được — hệ thống chuẩn hoá cả hai bên trước khi so.

Các `doc_type` hợp lệ: `law` `ban_an` `an_le` `mau_hd` `contract` `advisory` `filing`
`nhan_hieu` `thu_mau` `quy_trinh` `ho_so_ns` `ho_so_kh` `cong_no` `other`.
`access_level`: `public` `internal` `client`.

`cong_no` là loại duy nhất bị chặn thêm một lớp theo quyền từng người — đặt nhãn
này cho thư mục nào là thư mục đó thành vùng hạn chế.

---

## Vận hành

```bash
cd ~/hds-ai-full
bash deploy/auto-learn.sh --dry-run           # xem sẽ học file nào, nhãn gì
bash deploy/auto-learn.sh                     # học thật
sudo bash deploy/auto-learn.sh --install-timer # tự học mỗi 15 phút
```

Bot chỉ xử lý file **mới hoặc đã sửa** (file thường so checksum; Google Docs/Sheets
so `modifiedTime`) → chạy lại rất nhanh.
Sửa nội dung file trên Drive → lần sau bot tự thay bản cũ bằng bản mới.

Mặc định an toàn: file mới **chờ người duyệt** trước khi được dùng để trả lời. Sau khi
đã kiểm tra quy trình và dashboard, có thể chủ động bật trong `hds-ai/.env`:

```env
AUTO_LEARN_AUTO_APPROVE=1
```

Biến cũ vẫn tương thích: `AUTO_LEARN_REVIEW=1` là chờ duyệt,
`AUTO_LEARN_REVIEW=0` là tự duyệt. Không nên đặt đồng thời hai biến; biến mới được ưu tiên.

## Thứ tự làm cho bản demo

1. Tạo cây thư mục ở trên (chưa cần đủ file, cứ có khung trước).
2. Trên web: tạo **khách hàng** + **vụ việc** với mã đúng như tên thư mục `[MÃ]`.
3. Thả vài file mỗi loại — nên có: 2–3 văn bản luật, 1 hợp đồng mẫu, 1 án lệ, 1 hồ sơ khách.
4. `bash deploy/auto-learn.sh --dry-run` → soát nhãn có đúng không.
5. Chạy thật, rồi vào chat hỏi thử — câu trả lời phải kèm **nguồn trích dẫn** đúng file đó.
6. Bật timer.
