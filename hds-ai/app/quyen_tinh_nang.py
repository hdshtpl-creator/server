"""quyen_tinh_nang.py — Bật/tắt từng chức năng cho một tài khoản.

Vì sao có mô-đun này (yêu cầu chủ dự án 20/09/2026): tài khoản khách trước
đây chỉ có đúng một mức — đăng nhập vào là thấy khung trò chuyện, không hơn
không kém. Khách trả phí khác nhau thì cần mở khác nhau: khách này chỉ hỏi
đáp, khách kia được tải hồ sơ về, khách nữa được tự soạn giấy tờ.

Nguyên tắc:

1. **Quyền là lớp THỨ HAI, không thay thế lớp cô lập dữ liệu.** Bật hết mọi
   chức năng cho một tài khoản khách thì họ vẫn chỉ nhìn thấy hồ sơ của chính
   mình — việc đó do khoá dòng ở CSDL (RLS) lo, không liên quan tới đây. Ở đây
   chỉ quyết định "được dùng chức năng nào", không quyết định "thấy dữ liệu
   của ai".

2. **Không tick gì = theo mặc định của vai.** Cột `users.features` để NULL
   nghĩa là dùng MAC_DINH_THEO_VAI, tức đúng hành vi trước ngày 20/09/2026 —
   tài khoản cũ không đổi gì sau khi nâng cấp.

3. **Nhân viên nội bộ không bị siết bằng cơ chế này.** Quyền của họ đã khoá
   theo vai và theo phòng ban (access_rules). Tick ở đây chỉ dùng để MỞ THÊM
   cho khách; với vai nội bộ, mặc định là mở hết những gì vai đó vốn có.
"""
from __future__ import annotations

# Danh sách chức năng bật/tắt được. Khoá là tên dùng trong CSDL và API — đổi
# tên khoá là mất quyền đã cấp cho tài khoản cũ, nên chỉ thêm, đừng sửa.
TINH_NANG = {
    "chat": {
        "ten": "Hỏi đáp với trợ lý",
        "mo_ta": "Đặt câu hỏi và nhận câu trả lời kèm trích dẫn nguồn.",
    },
    "dinh_kem": {
        "ten": "Đính kèm tệp trong khung trò chuyện",
        "mo_ta": "Tải hợp đồng, giấy tờ lên để hỏi về chính tệp đó. Tệp tự xoá sau 6 giờ.",
    },
    "tai_lieu": {
        "ten": "Xem và tải tài liệu của mình",
        "mo_ta": "Mở bản gốc những tài liệu thuộc hồ sơ của mình từ bảng nguồn trích dẫn.",
    },
    "kiem_tra": {
        "ten": "Kiểm tra pháp lý & rà soát rủi ro",
        "mo_ta": "Tải hợp đồng lên, đối chiếu danh mục điều khoản chuẩn và luật.",
    },
    "soan_thao": {
        "ten": "Soạn tài liệu",
        "mo_ta": "Tự tạo bản nháp, điền mẫu và tải về .docx.",
    },
}

CLIENT_ROLES = {"client_free", "client_plus", "client_pro"}

# Mặc định khi tài khoản chưa được tick gì (features IS NULL).
#
# Khách: CHỈ hỏi đáp. Đây là mức của mọi tài khoản khách trước 20/09/2026, giữ
# nguyên để nâng cấp không vô tình mở thêm cửa cho ai.
# Nội bộ: mở hết — quyền thật của họ nằm ở vai và ma trận phòng ban.
MAC_DINH_KHACH = {"chat": True, "dinh_kem": False, "tai_lieu": False,
                  "kiem_tra": False, "soan_thao": False}
MAC_DINH_NOI_BO = {ten: True for ten in TINH_NANG}


def mac_dinh_theo_vai(role: str) -> dict:
    return dict(MAC_DINH_KHACH if role in CLIENT_ROLES else MAC_DINH_NOI_BO)


def chuan_hoa(gia_tri) -> dict | None:
    """Làm sạch dữ liệu tick trước khi lưu: chỉ giữ tên chức năng có thật, ép
    về True/False. Trả None khi không có gì hợp lệ (nghĩa là 'theo vai')."""
    if not isinstance(gia_tri, dict):
        return None
    sach = {ten: bool(gia_tri[ten]) for ten in TINH_NANG if ten in gia_tri}
    return sach or None


def quyen_hieu_luc(role: str, features) -> dict:
    """Quyền THẬT SỰ của tài khoản: mặc định của vai, bị ghi đè bởi phần đã tick.

    Nhận cả dict lẫn chuỗi JSON (psycopg trả JSONB thành dict, nhưng vài
    đường cũ đưa vào chuỗi).
    """
    if isinstance(features, str):
        import json
        try:
            features = json.loads(features)
        except ValueError:
            features = None
    ket_qua = mac_dinh_theo_vai(role)
    if isinstance(features, dict):
        for ten, bat in features.items():
            if ten in ket_qua:
                ket_qua[ten] = bool(bat)
    return ket_qua


def co_quyen(user: dict, ten: str) -> bool:
    """Tài khoản này có được dùng chức năng `ten` không.

    Tên chức năng lạ trả về True: một chốt gõ sai tên không được âm thầm khoá
    cả tính năng của mọi người — lỗi kiểu đó rất khó thấy. Tên đúng thì tra
    quyền hiệu lực đã tính sẵn lúc đăng nhập (`user["features"]`).
    """
    if ten not in TINH_NANG:
        return True
    quyen = user.get("features")
    if not isinstance(quyen, dict):
        quyen = quyen_hieu_luc(user.get("role") or "", quyen)
    return bool(quyen.get(ten, False))


def mo_ta_quyen(role: str, features) -> list:
    """Danh sách cho giao diện: tên chức năng, đang bật hay tắt, có phải mặc
    định của vai không (để màn hình quản trị hiện rõ cái nào đã sửa tay)."""
    hieu_luc = quyen_hieu_luc(role, features)
    goc = mac_dinh_theo_vai(role)
    return [{
        "ma": ma,
        "ten": cau_hinh["ten"],
        "mo_ta": cau_hinh["mo_ta"],
        "bat": hieu_luc[ma],
        "theo_mac_dinh": hieu_luc[ma] == goc[ma],
    } for ma, cau_hinh in TINH_NANG.items()]
