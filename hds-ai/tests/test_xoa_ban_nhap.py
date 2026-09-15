"""Xoá bản nháp — DELETE /drafts/{id} (app/draft_api.py) — logic thuần.

db.session được vá bằng kết nối giả ghi lại từng câu SQL: test khẳng định lệnh
DELETE có/không được gửi đi và audit 'delete_draft' đi kèm. Không câu nào chạm
Postgres thật — deploy/update.sh chạy bộ test này ngay trên máy chủ đang phục vụ.

Luật cần giữ:
  · khách (client_*) bị chặn trước mọi câu SQL;
  · người tạo xoá được bản CHƯA duyệt của mình, không xoá được của người khác;
  · bản ĐÃ DUYỆT chỉ Ban quản trị mới xoá — trạng thái kiểm lại dưới khoá hàng;
  · bản biến mất giữa chừng (người khác vừa xoá) → 404, không DELETE mù.
"""
import contextlib
import unittest
import unittest.mock

from fastapi import HTTPException

from app import api, draft_api


def _row(**thay):
    gia_tri = {c: None for c in draft_api.DRAFT_COLUMNS}
    gia_tri.update(id=5, title="Đơn khởi kiện", document_type="other",
                   status="draft", current_version=1, created_by=11,
                   creator_name="Chuyên viên A", input_data="{}")
    gia_tri.update(thay)
    return tuple(gia_tri[c] for c in draft_api.DRAFT_COLUMNS)


class _Cursor:
    def __init__(self, rows, log):
        self._rows, self._log = rows, log

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self._log.append((" ".join(sql.split()), params))

    def fetchone(self):
        # Mỗi lượt đọc trả bản ghi kế tiếp; hết danh sách thì giữ bản cuối.
        return self._rows.pop(0) if len(self._rows) > 1 else self._rows[0]


class _Conn:
    def __init__(self, rows, log):
        self._rows, self._log = rows, log

    def cursor(self):
        return _Cursor(self._rows, self._log)


def _endpoint(path, method):
    for route in api.app.routes:
        if getattr(route, "path", None) == path and method in (getattr(route, "methods", None) or ()):
            return route.endpoint
    raise AssertionError(f"không thấy route {method} {path}")


CHUYEN_VIEN = {"id": 11, "role": "chuyen_vien", "is_banqt": False, "can_review": False, "dept_ids": []}
NGUOI_KHAC = {"id": 12, "role": "chuyen_vien", "is_banqt": False, "can_review": False, "dept_ids": []}
BAN_QT = {"id": 1, "role": "admin", "is_banqt": True, "can_review": True, "dept_ids": []}
KHACH = {"id": 99, "role": "client_admin", "is_banqt": False, "can_review": False, "dept_ids": []}


class XoaBanNhap(unittest.TestCase):
    def setUp(self):
        self.xoa = _endpoint("/drafts/{draft_id}", "DELETE")

    def _chay(self, user, rows):
        log = []
        # Một dãy bản ghi DÙNG CHUNG cho mọi lượt mở session: _get_draft đọc
        # bản đầu, lượt khoá hàng trong endpoint đọc bản kế — đúng như hai
        # truy vấn nối tiếp trên cùng một hàng đang đổi.
        con_lai = list(rows)

        @contextlib.contextmanager
        def session(**_kw):
            yield _Conn(con_lai, log)

        with unittest.mock.patch.object(draft_api.db, "session", session):
            try:
                return self.xoa(draft_id=5, user=user), None, log
            except HTTPException as exc:
                return None, exc, log

    @staticmethod
    def _co_delete(log):
        return any(sql.startswith("DELETE FROM document_drafts") for sql, _ in log)

    def test_khach_bi_chan_truoc_moi_cau_sql(self):
        ket_qua, loi, log = self._chay(KHACH, [_row()])
        self.assertIsNone(ket_qua)
        self.assertEqual(loi.status_code, 403)
        self.assertEqual(log, [])

    def test_nguoi_tao_xoa_ban_chua_duyet(self):
        ket_qua, loi, log = self._chay(CHUYEN_VIEN, [_row()])
        self.assertIsNone(loi)
        self.assertEqual(ket_qua, {"ok": True, "id": 5})
        self.assertTrue(self._co_delete(log))
        # Khoá hàng trước khi xoá; audit ghi lại tên/trạng thái bản đã mất.
        self.assertTrue(any("FOR UPDATE OF d" in sql for sql, _ in log))
        audit = [p for sql, p in log if sql.startswith("INSERT INTO audit_log")]
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0][0], CHUYEN_VIEN["id"])
        self.assertEqual(audit[0][1], "delete_draft")
        self.assertIn("Đơn khởi kiện", audit[0][4])

    def test_nguoi_khac_khong_xoa_duoc(self):
        ket_qua, loi, log = self._chay(NGUOI_KHAC, [_row()])
        self.assertIsNone(ket_qua)
        self.assertEqual(loi.status_code, 403)
        self.assertFalse(self._co_delete(log))

    def test_nguoi_tao_khong_xoa_duoc_ban_da_duyet(self):
        ket_qua, loi, log = self._chay(CHUYEN_VIEN, [_row(status="approved")])
        self.assertIsNone(ket_qua)
        self.assertEqual(loi.status_code, 409)
        self.assertFalse(self._co_delete(log))

    def test_vua_duoc_duyet_giua_chung_thi_dung_lai(self):
        # Lúc kiểm quyền bản còn là nháp; dưới khoá hàng thì reviewer đã duyệt.
        ket_qua, loi, log = self._chay(CHUYEN_VIEN, [_row(), _row(status="approved")])
        self.assertIsNone(ket_qua)
        self.assertEqual(loi.status_code, 409)
        self.assertFalse(self._co_delete(log))

    def test_ban_quan_tri_xoa_duoc_ban_da_duyet_cua_nguoi_khac(self):
        ket_qua, loi, log = self._chay(BAN_QT, [_row(status="approved")])
        self.assertIsNone(loi)
        self.assertTrue(ket_qua["ok"])
        self.assertTrue(self._co_delete(log))

    def test_ban_bien_mat_giua_chung_thi_404(self):
        ket_qua, loi, log = self._chay(CHUYEN_VIEN, [_row(), None])
        self.assertIsNone(ket_qua)
        self.assertEqual(loi.status_code, 404)
        self.assertFalse(self._co_delete(log))


if __name__ == "__main__":
    unittest.main()
