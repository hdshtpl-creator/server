# Cổng API cho khách hàng

Khách hàng hỏi bot qua hai đường, **cùng một phạm vi dữ liệu**:

| Đường | Dùng khi |
|---|---|
| Đăng nhập web (JWT) | Người thật mở dashboard hỏi |
| Khoá API (`X-API-Key`) | Hệ thống của khách gọi tự động |

Khoá API **chỉ cấp cho tài khoản khách**. Vai nội bộ không cấp được — một khoá
lọt ra ngoài không được phép mở toàn bộ dữ liệu công ty.

---

## Cấp khoá

**Quản trị → Người dùng & Phòng ban → nút "Cấp khoá API"** trên thẻ tài khoản khách.

Khoá hiện **đúng một lần**. Máy chủ chỉ lưu bản băm SHA-256, không có đường nào
xem lại. Mất thì bấm cấp lại — khoá cũ tự mất hiệu lực ngay.

Thu hồi: bấm **"Thu hồi khoá API"**. Mọi lời gọi bằng khoá cũ bị chặn tức thì.

---

## Khách gọi như thế nào

```bash
curl -X POST https://app.diginix.io.vn/api/chat/portal \
  -H "X-API-Key: hds_xxxxxxxxxxxxxxxxxxxx" \
  -H "Content-Type: application/json" \
  -d '{"question": "Hợp đồng của chúng tôi có điều khoản phạt chậm thanh toán không?"}'
```

Trả về:

```json
{
  "answer": "…",
  "sources": [{ "n": 1, "title": "…", "document_id": 12, "score": 0.82 }],
  "conversation_id": 41,
  "quota": { "used": 7, "limit": 50 }
}
```

Hỏi tiếp trong cùng mạch trao đổi: gửi thêm `conversation_id` nhận được ở lượt
trước. Bot nhớ mấy lượt gần nhất nên hỏi "còn điều khoản kia thì sao" là hiểu.

**Không truyền `conversation_id` của người khác** — máy chủ kiểm tra chủ sở hữu
và trả 403.

---

## Ba gói khách được tra cứu những gì

Bảng `access_rules` quyết định, không nằm trong mã nguồn. Sửa bảng là có hiệu
lực ngay.

| Loại tài liệu | Free | Plus | Pro |
|---|:--:|:--:|:--:|
| Văn bản pháp luật | ✓ | ✓ | ✓ |
| Quy trình dịch vụ | | ✓ | ✓ |
| Thư mẫu, biểu mẫu | | ✓ | ✓ |
| Hồ sơ / hợp đồng / thư tư vấn của chính khách | | ✓ | ✓ |
| Án lệ, hợp đồng mẫu | | | ✓ |
| **Công nợ, tài chính** | ✗ | ✗ | ✗ |

Công nợ **không gói nào** tra được — đó là tài liệu nội bộ, chặn ở tầng CSDL
theo quyền từng nhân viên (xem `CAU_TRUC_DRIVE.md`).

Đổi phạm vi gói: sửa `CLIENT_TIERS` trong `hds-ai/app/seed_departments.py` rồi
chạy lại `python -m app.seed_departments`, hoặc sửa trực tiếp bảng `access_rules`.

---

## Hạn mức

Mỗi tài khoản khách có `monthly_quota` (đặt khi tạo tài khoản, 0 = không giới hạn).
Hết lượt thì trả **429** kèm số đã dùng. Đầu tháng sau tự hoàn lại.

---

## Hai lằn ranh không bao giờ vượt qua

Cả hai khoá ở tầng CSDL (Row-Level Security), không phụ thuộc mã nguồn ứng dụng:

1. **Khách A không thấy dữ liệu khách B.** Kể cả hỏi khéo, kể cả câu "bỏ qua mọi
   chỉ dẫn trước đó". Truy vấn không trả về dòng nào để mà lộ.
2. **Khách không thấy ghi chú nội bộ.** Hồ sơ 360° (nhận định, cảnh báo thời
   hiệu, gợi ý chiến lược) và file tổng hợp khách là tài liệu làm việc của HDS,
   không đưa sang cổng khách.

Kiểm chứng: `cd hds-ai && python -m tests.test_security` — phải 0 dòng `[HỎNG]`.
