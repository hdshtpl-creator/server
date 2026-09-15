"""Giấy tờ trong thẻ Hồ sơ khách 360° — GET /clients/{id}/360 (app/api.py).

Thẻ 360 giờ mở được BẢN GỐC ngay tại chỗ: mỗi dòng giấy tờ có nút Xem / Tải
về gọi /files/{id}/preview|download. Hai endpoint đó chặn bằng
rag.can_open_doc, nên danh sách 360 phải đi qua ĐÚNG cửa ấy — kê ra thứ bấm
vào chỉ nhận 403 là mời người dùng đâm vào tường, mà kê kèm tóm tắt của tài
liệu ngoài quyền thì rò rỉ nội dung dù nút có khoá.

Luật cần giữ:
  · không mở được → tên bị che, tóm tắt rỗng, has_file tắt;
  · mở được nhưng KHÔNG có tệp gốc (nạp từ hội thoại) → has_file tắt;
  · doc_type_raw là nguyên liệu nội bộ của cửa quyền, không lọt ra ngoài.

db.session được vá bằng kết nối giả: không câu nào chạm Postgres thật —
deploy/update.sh chạy bộ test này ngay trên máy chủ đang phục vụ.
"""
import contextlib
import unittest
import unittest.mock

from fastapi import HTTPException

from app import api, rag


class _Cursor:
    def __init__(self, row):
        self._row = row

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        pass

    def fetchone(self):
        return self._row


class _Conn:
    def __init__(self, row):
        self._row = row

    def cursor(self):
        return _Cursor(self._row)


def _endpoint(path, method):
    for route in api.app.routes:
        if getattr(route, "path", None) == path and method in (getattr(route, "methods", None) or ()):
            return route.endpoint
    raise AssertionError(f"không thấy route {method} {path}")


CHUYEN_VIEN = {"id": 11, "role": "chuyen_vien", "is_banqt": False, "can_review": False,
               "can_finance": False, "dept_ids": [3], "dept_codes": ["tranh-tung"]}
KHACH = {"id": 99, "role": "client_admin", "is_banqt": False, "can_review": False,
         "can_finance": False, "dept_ids": [], "dept_codes": []}


def _doc(doc_id, **thay):
    d = {"id": doc_id, "title": f"Hợp đồng số {doc_id}", "doc_type": "Hợp đồng",
         "summary": "Tóm tắt nội dung", "created_at": "2026-09-01", "matter_id": None,
         "has_file": True, "doc_type_raw": "contract", "access_level": "client",
         "department_id": 3, "department_name": "Tranh tụng"}
    d.update(thay)
    return d


class HoSo360(unittest.TestCase):
    def setUp(self):
        self.doc_360 = _endpoint("/clients/{client_id}/360", "GET")

    def _chay(self, user, docs, mo_duoc):
        """Gọi endpoint với khách thuộc phòng 3 và danh sách giấy tờ cho sẵn.

        mo_duoc: hàm nhận title của tài liệu, trả True nếu người này mở được.
        """
        dossier = {"client": {"id": 7, "name": "Khách A", "code": "9", "department": "Tranh tụng"},
                   "profile": {"history": None, "issues": None, "warnings": None,
                               "suggestions": None},
                   "matters": [], "documents": list(docs)}

        @contextlib.contextmanager
        def session(**_kw):
            yield _Conn((3,))

        with contextlib.ExitStack() as stack:
            stack.enter_context(unittest.mock.patch.object(api.db, "session", session))
            stack.enter_context(unittest.mock.patch.object(rag, "client_360",
                                                          lambda *a, **k: dossier))
            stack.enter_context(unittest.mock.patch.object(rag, "load_access_rules",
                                                          lambda: {}))
            stack.enter_context(unittest.mock.patch.object(
                rag, "can_open_doc",
                lambda *a, **k: mo_duoc(a[3]["title"])))
            try:
                return self.doc_360(client_id=7, user=user), None
            except HTTPException as exc:
                return None, exc

    def test_khach_dang_nhap_khong_vao_the_360(self):
        ket_qua, loi = self._chay(KHACH, [_doc(1)], lambda _t: True)
        self.assertIsNone(ket_qua)
        self.assertEqual(loi.status_code, 403)

    def test_mo_duoc_thi_giu_nguyen_ten_va_bat_nut(self):
        ket_qua, loi = self._chay(CHUYEN_VIEN, [_doc(1)], lambda _t: True)
        self.assertIsNone(loi)
        doc = ket_qua["documents"][0]
        self.assertTrue(doc["can_open"])
        self.assertTrue(doc["has_file"])
        self.assertEqual(doc["title"], "Hợp đồng số 1")
        self.assertEqual(doc["summary"], "Tóm tắt nội dung")

    def test_ngoai_quyen_thi_che_ten_xoa_tom_tat_tat_nut(self):
        ket_qua, loi = self._chay(CHUYEN_VIEN, [_doc(2)], lambda _t: False)
        self.assertIsNone(loi)
        doc = ket_qua["documents"][0]
        self.assertFalse(doc["can_open"])
        # Nút Xem / Tải về phải tắt: hai endpoint kia sẽ trả 403 chứ không mở.
        self.assertFalse(doc["has_file"])
        self.assertIsNone(doc["summary"])
        self.assertNotIn("Hợp đồng số 2", doc["title"])

    def test_khong_co_tep_goc_thi_tat_nut_du_mo_duoc(self):
        ket_qua, loi = self._chay(CHUYEN_VIEN, [_doc(3, has_file=False)],
                                  lambda _t: True)
        self.assertIsNone(loi)
        doc = ket_qua["documents"][0]
        self.assertTrue(doc["can_open"])
        self.assertFalse(doc["has_file"])

    def test_doc_type_raw_khong_lot_ra_ngoai(self):
        ket_qua, _ = self._chay(CHUYEN_VIEN, [_doc(4)], lambda _t: True)
        self.assertNotIn("doc_type_raw", ket_qua["documents"][0])
        # Nhãn tiếng Việt vẫn là thứ giao diện đọc.
        self.assertEqual(ket_qua["documents"][0]["doc_type"], "Hợp đồng")

    def test_moi_tai_lieu_duoc_soi_rieng(self):
        docs = [_doc(5, title="Mở được"), _doc(6, title="Chặn")]
        ket_qua, _ = self._chay(CHUYEN_VIEN, docs, lambda t: t == "Mở được")
        mo, chan = ket_qua["documents"]
        self.assertTrue(mo["can_open"])
        self.assertFalse(chan["can_open"])


if __name__ == "__main__":
    unittest.main()
