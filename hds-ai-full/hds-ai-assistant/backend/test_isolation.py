# -*- coding: utf-8 -*-
"""
HDS Law Firm - Script Kiểm Tra Cô Lập Dữ Liệu Khách Hàng (test_isolation.py)
-------------------------------------------------------------------------
Kiểm tra thực tế tính riêng tư dữ liệu giữa Khách hàng A và Khách hàng B.
Đảm bảo khóa phân quyền ở tầng CSDL Row-Level Security (RLS).
"""

import os
import sys

sys.path.append(os.path.dirname(__file__))
import db

# Màu sắc hiển thị terminal
GREEN = "\033[92m"
RED = "\033[91m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"

CLIENT_A_ID = "CLI-TEST-A"
CLIENT_B_ID = "CLI-TEST-B"

DOC_A_ID = "doc-test-a-secret"
DOC_B_ID = "doc-test-b-secret"
DOC_PUB_ID = "doc-test-public"

def setup_test_data():
    """Tạo dữ liệu thử nghiệm hai khách hàng A và B bằng quyền Admin (hds)."""
    print(f"{CYAN}1. Tạo dữ liệu mẫu hai khách hàng A và B (Quyền Admin)...{RESET}")
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            # Insert clients
            cur.execute(
                "INSERT INTO clients (id, code, name, department) VALUES (%s, %s, %s, %s);",
                (CLIENT_A_ID, "CLI-A", "Công ty Cổ phần Khách hàng A", "Tư vấn Doanh nghiệp")
            )
            cur.execute(
                "INSERT INTO clients (id, code, name, department) VALUES (%s, %s, %s, %s);",
                (CLIENT_B_ID, "CLI-B", "Tập đoàn Đầu tư Khách hàng B", "Tranh tụng Thương mại")
            )

            # Insert Documents
            cur.execute(
                "INSERT INTO documents (id, title, access_level, client_id, review_status) VALUES (%s, %s, 'client', %s, 'da_duyet');",
                (DOC_A_ID, "Hợp đồng Mua bán Bất động sản Mật - Công ty A", CLIENT_A_ID)
            )
            cur.execute(
                "INSERT INTO documents (id, title, access_level, client_id, review_status) VALUES (%s, %s, 'client', %s, 'da_duyet');",
                (DOC_B_ID, "Hồ sơ Sáp nhập Doanh nghiệp Bí mật - Tập đoàn B", CLIENT_B_ID)
            )
            cur.execute(
                "INSERT INTO documents (id, title, access_level, client_id, review_status) VALUES (%s, %s, 'public', NULL, 'da_duyet');",
                (DOC_PUB_ID, "Bộ Luật Lao động 2019 (Văn bản công khai)")
            )

            # Insert Chunks cho A và B
            cur.execute(
                "INSERT INTO chunks (id, doc_id, content, access_level, client_id) VALUES ('chk-a-1', %s, 'Thỏa thuận giá bán 50 tỷ Công ty A', 'client', %s);",
                (DOC_A_ID, CLIENT_A_ID)
            )
            cur.execute(
                "INSERT INTO chunks (id, doc_id, content, access_level, client_id) VALUES ('chk-b-1', %s, 'Kế hoạch thâu tóm 80% cổ phần Tập đoàn B', 'client', %s);",
                (DOC_B_ID, CLIENT_B_ID)
            )
            cur.execute(
                "INSERT INTO chunks (id, doc_id, content, access_level, client_id) VALUES ('chk-pub-1', %s, 'Điều 1 Luật Lao động', 'public', NULL);",
                (DOC_PUB_ID,)
            )
    print(f" {GREEN}[OK] Đã tạo thành công dữ liệu mẫu cho Khách hàng A và B.{RESET}\n")

def cleanup_test_data():
    """Xóa sạch dữ liệu thử nghiệm sau khi kiểm tra."""
    try:
        with db.session(role="internal", admin=True) as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM documents WHERE id IN (%s, %s, %s);", (DOC_A_ID, DOC_B_ID, DOC_PUB_ID))
                cur.execute("DELETE FROM clients WHERE id IN (%s, %s);", (CLIENT_A_ID, CLIENT_B_ID))
        print(f"\n{CYAN}4. Dọn dẹp dữ liệu thử nghiệm hoàn tất.{RESET}")
    except Exception as e:
        print(f"Lỗi khi dọn dẹp dữ liệu test: {e}")

def run_isolation_tests() -> bool:
    print(f"{BOLD}{'='*65}{RESET}")
    print(f"{BOLD}{CYAN} HDS LAW FIRM - BÁO CÁO TEST CÔ LẬP DỮ LIỆU TẦNG CSDL (RLS) {RESET}")
    print(f"{BOLD}{'='*65}{RESET}\n")

    setup_test_data()
    all_tests_passed = True

    # TEST 1: KHÁCH HÀNG A TRUY VẤN
    print(f"{BOLD}2. TEST 1: Đăng nhập dưới quyền Khách hàng A (role='client', client_id='{CLIENT_A_ID}'):{RESET}")
    try:
        with db.session(role="client", client_id=CLIENT_A_ID, admin=False) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, title, access_level, client_id FROM documents;")
                docs_a = cur.fetchall()
                doc_ids_a = [d[0] for d in docs_a]

                has_doc_a = DOC_A_ID in doc_ids_a
                has_doc_pub = DOC_PUB_ID in doc_ids_a
                has_doc_b = DOC_B_ID in doc_ids_a

                # Kiểm tra kết quả
                test1_ok = has_doc_a and has_doc_pub and (not has_doc_b)

                print(f"   ├─ Thấy tài liệu sở hữu của A ({DOC_A_ID}) : {GREEN}ĐẠT{RESET}" if has_doc_a else f"   ├─ Thấy tài liệu A : {RED}HỎNG{RESET}")
                print(f"   ├─ Thấy tài liệu Công khai ({DOC_PUB_ID})  : {GREEN}ĐẠT{RESET}" if has_doc_pub else f"   ├─ Thấy tài liệu Công khai : {RED}HỎNG{RESET}")
                print(f"   └─ CHẶN tài liệu bí mật của B ({DOC_B_ID}) : {GREEN}ĐẠT (Không thấy){RESET}" if not has_doc_b else f"   └─ CHẶN tài liệu B : {RED}HỎNG (BỊ RÒ RỈ!){RESET}")

                if not test1_ok:
                    all_tests_passed = False

                print(f"   └─ Kết quả Test 1: {GREEN if test1_ok else RED}{BOLD}{'ĐẠT' if test1_ok else 'HỎNG'}{RESET}\n")
    except Exception as e:
        print(f"   └─ {RED}Lỗi khi thực thi Test 1: {e}{RESET}\n")
        all_tests_passed = False

    # TEST 2: GIẢ LẬP CÂU DÒ / PROMPT INJECTION CỦA A ĐỂ LẤY FILE B
    print(f"{BOLD}3. TEST 2: Giả lập câu 'dò' bypassing SQL từ phía client A:{RESET}")
    try:
        with db.session(role="client", client_id=CLIENT_A_ID, admin=False) as conn:
            with conn.cursor() as cur:
                # Cố tình dùng query tìm kiếm tổng quát với từ khóa của B
                cur.execute(
                    "SELECT id, title FROM documents WHERE title LIKE '%Sáp nhập%' OR title LIKE '%Tập đoàn B%';"
                )
                bypassed_docs = cur.fetchall()

                # Nhờ RLS, kết quả trả về phải bằng 0 dòng
                leak_count = len(bypassed_docs)
                test2_ok = (leak_count == 0)

                print(f"   ├─ Truy vấn từ khóa nhạy cảm của B: 'SELECT ... WHERE title LIKE %Sáp nhập%'")
                print(f"   ├─ Số lượng dòng CSDL trả về: {leak_count} dòng")
                if test2_ok:
                    print(f"   └─ Kết quả Test 2: {GREEN}{BOLD}ĐẠT - CSDL RLS đã chặn hoàn toàn câu dò!{RESET}\n")
                else:
                    print(f"   └─ Kết quả Test 2: {RED}{BOLD}HỎNG - Phát hiện rò rỉ {leak_count} bản ghi của B!{RESET}\n")
                    all_tests_passed = False
    except Exception as e:
        print(f"   └─ {RED}Lỗi khi thực thi Test 2: {e}{RESET}\n")
        all_tests_passed = False

    cleanup_test_data()

    # KẾT LUẬN CÔ LẬP DỮ LIỆU
    print(f"{BOLD}{'='*65}{RESET}")
    if all_tests_passed:
        print(f" {GREEN}{BOLD}🏆 BÁO CÁO TEST CÔ LẬP: TẤT CẢ CÁC BÀI TEST ĐỀU ĐẠT CHUẨN AN TOÀN!{RESET}")
        print(f" {GREEN} Khách hàng A tuyệt đối KHÔNG THỂ truy cập hồ sơ của Khách hàng B.{RESET}")
        print(f"{BOLD}{'='*65}{RESET}\n")
        return True
    else:
        print(f" {RED}{BOLD}💥 BÁO CÁO TEST CÔ LẬP: CÓ LỖ HỔNG RÒ RỈ DỮ LIỆU CẦN KHẮC PHỤC NGAY!{RESET}")
        print(f"{BOLD}{'='*65}{RESET}\n")
        return False

if __name__ == "__main__":
    success = run_isolation_tests()
    sys.exit(0 if success else 1)
