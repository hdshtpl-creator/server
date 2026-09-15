"""Hoàn thiện giai đoạn 1 (15/09/2026) — phần THUẦN của các API mới, không
cần PostgreSQL/Ollama: form khách quan tâm, tóm tắt nhật ký, lý do sửa tài
liệu, và dây nối giữa API với ba mô-đun mới (so_sanh, ra_soat_rui_ro,
kiem_tra_mau_thuan).

Chạy: python -m unittest tests.test_hoan_thien_1509 -v
"""
import types
import unittest

from fastapi import HTTPException

from app import api, draft_api, kiem_tra_mau_thuan, ra_soat_rui_ro, so_sanh


def _lead(**kw):
    base = {"name": "Nguyễn Văn An", "phone": "0912345678", "email": None,
            "need": "Tranh chấp hợp đồng thuê", "conversation_id": None, "website": None}
    base.update(kw)
    return types.SimpleNamespace(**base)


class LeadValidationTests(unittest.TestCase):
    def test_hop_le_voi_sdt(self):
        out = api.kiem_tra_lead(_lead())
        self.assertEqual(out["name"], "Nguyễn Văn An")
        self.assertEqual(out["phone"], "0912345678")
        self.assertIsNone(out["email"])

    def test_hop_le_voi_email_khong_sdt(self):
        out = api.kiem_tra_lead(_lead(phone="", email="  Bich.Tran@Example.com "))
        self.assertEqual(out["email"], "bich.tran@example.com")

    def test_sdt_co_khoang_trang_va_cham(self):
        out = api.kiem_tra_lead(_lead(phone="+84 91 234.5678"))
        self.assertEqual(out["phone"], "+84912345678")

    def test_thieu_ca_sdt_lan_email(self):
        with self.assertRaises(HTTPException) as ctx:
            api.kiem_tra_lead(_lead(phone="", email=""))
        self.assertEqual(ctx.exception.status_code, 422)

    def test_ten_qua_ngan(self):
        with self.assertRaises(HTTPException):
            api.kiem_tra_lead(_lead(name="A"))

    def test_sdt_sai(self):
        with self.assertRaises(HTTPException):
            api.kiem_tra_lead(_lead(phone="abc"))

    def test_email_sai(self):
        with self.assertRaises(HTTPException):
            api.kiem_tra_lead(_lead(phone="", email="khong-phai-email"))

    def test_nhu_cau_qua_dai(self):
        with self.assertRaises(HTTPException) as ctx:
            api.kiem_tra_lead(_lead(need="x" * 2001))
        self.assertEqual(ctx.exception.status_code, 422)

    def test_nhu_cau_duoc_gom_khoang_trang(self):
        out = api.kiem_tra_lead(_lead(need="  cần   tư vấn \n thuê nhà "))
        self.assertEqual(out["need"], "cần tư vấn thuê nhà")


class AuditSummaryTests(unittest.TestCase):
    def test_ten_viet_va_chi_tiet(self):
        s = api.tom_tat_audit("chat_query", "conversations", 43,
                              {"question": "Thời hiệu khởi kiện?"})
        self.assertIn("Hỏi AI", s)
        self.assertIn("conversations#43", s)
        self.assertIn("question=Thời hiệu", s)

    def test_action_la_khong_vo(self):
        s = api.tom_tat_audit("hanh_dong_moi", None, None, None)
        self.assertEqual(s, "hanh_dong_moi")

    def test_detail_khong_phai_dict(self):
        s = api.tom_tat_audit("approve", "documents", 1, "chuoi")
        self.assertIn("Duyệt", s)


class EditReasonTests(unittest.TestCase):
    def test_bon_ly_do_ke_hoach_co_mat(self):
        for ma in ("luat_thay_doi", "rui_ro", "yeu_cau_khach", "khac"):
            self.assertIn(ma, api.EDIT_REASONS)

    def test_lead_statuses(self):
        self.assertEqual(set(api.LEAD_STATUSES), {"moi", "da_lien_he", "bo_qua"})


class DraftCompareHelperTests(unittest.TestCase):
    def test_mac_dinh_hai_ban_gan_nhat(self):
        self.assertEqual(draft_api._cap_phien_ban({"current_version": 3}, None, None), (2, 3))

    def test_mot_phien_ban_khong_so_duoc(self):
        with self.assertRaises(HTTPException) as ctx:
            draft_api._cap_phien_ban({"current_version": 1}, None, None)
        self.assertEqual(ctx.exception.status_code, 409)

    def test_trung_nhau_bi_chan(self):
        with self.assertRaises(HTTPException):
            draft_api._cap_phien_ban({"current_version": 3}, 2, 2)

    def test_chon_tay(self):
        self.assertEqual(draft_api._cap_phien_ban({"current_version": 5}, 1, 4), (1, 4))


class WiringTests(unittest.TestCase):
    """Ba mô-đun mới thật sự được API dùng đúng tên hàm (đổi tên là gãy ở đây,
    không phải lúc người dùng bấm nút)."""

    def test_so_sanh_co_ham_api_goi(self):
        for ten in ("so_sanh_van_ban", "xuat_docx_theo_doi", "tom_tat_thay_doi"):
            self.assertTrue(callable(getattr(so_sanh, ten)))

    def test_ra_soat_co_ham_api_goi(self):
        for ten in ("ra_soat", "cau_hoi_tra_luat", "xuat_bao_cao_docx"):
            self.assertTrue(callable(getattr(ra_soat_rui_ro, ten)))
        self.assertIn("hop_dong_lao_dong", ra_soat_rui_ro.LOAI_HOP_DONG)

    def test_kiem_tra_co_ham_api_goi(self):
        self.assertTrue(callable(kiem_tra_mau_thuan.chay_kiem_tra))
        kq = kiem_tra_mau_thuan.chay_kiem_tra("Lãi suất 2%/tháng.", llm=None, tim_luat=None)
        self.assertEqual(kq["tong_ket"]["ket_luan"], "canh_bao")

    def test_route_moi_ton_tai(self):
        paths = {r.path for r in api.app.routes}
        for p in ("/leads", "/leads/{lead_id}", "/audit", "/audit/actions",
                  "/documents/{doc_id}/versions", "/documents/{doc_id}/versions/compare",
                  "/legal/ra-soat", "/legal/ra-soat/export", "/legal/ra-soat/loai",
                  "/drafts/{draft_id}/compare", "/drafts/{draft_id}/compare/export",
                  "/drafts/{draft_id}/checks"):
            self.assertIn(p, paths, p)

    def test_kiem_tra_nen_khong_no_khi_thieu_bang(self):
        """CSDL hỏng / thiếu bảng → khoi_dong_kiem_tra trả False, KHÔNG ném —
        lưu bản thảo không được chết vì tính năng phụ. Giả lập db.session lỗi:
        test này chạy cả trên máy chủ thật (update.sh) nên TUYỆT ĐỐI không được
        chạm CSDL — chạm là ghi một dòng draft_checks + khởi động model thật."""
        from contextlib import contextmanager
        from unittest import mock

        @contextmanager
        def session_hong(*_a, **_k):
            raise RuntimeError("không có CSDL")
            yield  # noqa: unreachable — giữ dạng generator

        with mock.patch.object(draft_api.db, "session", session_hong):
            self.assertFalse(draft_api.khoi_dong_kiem_tra(1, 1, "x"))

    def test_kiem_tra_nen_tat_bang_cai_dat(self):
        from unittest import mock
        with mock.patch("app.settings.get", lambda k, d=None: "0" if k == "draft_check_auto" else d):
            self.assertFalse(draft_api.khoi_dong_kiem_tra(1, 1, "x"))


if __name__ == "__main__":
    unittest.main()
