"""Bộ quét kho: KHÔNG đọc lại tệp hỏng mỗi lượt (16/09/2026).

Vì sao có bộ test này: đo trên máy chủ ngày 16/09, một lượt quét mất 5 phút
32 giây trong khi đi hết 42.103 tệp và so md5 chỉ tốn 8 giây. Hơn 5 phút còn
lại là 65 tệp KHÔNG ĐỌC ĐƯỢC bị thử lại ở mọi lượt — 54 tệp trong đó là PDF
không có lớp chữ nên lần nào cũng chạy OCR rồi lại hỏng (một tệp đã thử 924
lần kể từ 19/08). Nay md5 lúc hỏng được ghi lại; nội dung chưa đổi thì bỏ qua.

Ba điều phải đứng vững:
  1. Chỉ bỏ qua khi md5 TRÙNG md5 lúc hỏng, và chỉ khi việc sắp làm là đọc
     lại tệp. Tệp được sửa, tệp lỗi đã học được, tệp lạ: vẫn xử lý như cũ.
  2. Không đọc được nhật ký lỗi (thiếu cột, CSDL trục trặc) thì bộ quét chạy
     y như trước, không nổ.
  3. md5 lúc hỏng thực sự được ghi xuống, nếu không lượt sau lại thử lại.

Chạy: python -m unittest tests.test_quet_nhanh -v
"""
import contextlib
import io
import unittest
from unittest import mock

from app import auto_learn, local_learn as ll

MD5_CU = "a" * 32
MD5_MOI = "b" * 32
KEY = "local:9. HỒ SƠ KHÁCH HÀNG/1043. Chị Trang/scan.pdf"


def _row(checksum):
    """Bản ghi tài liệu như auto_learn.existing() trả về: chỉ cột 1 (md5) được
    dùng ở chốt này."""
    return (123, checksum) + (None,) * 9


class BoQuaTepHongTests(unittest.TestCase):
    def test_hong_va_chua_doi_thi_bo_qua(self):
        self.assertTrue(ll.nen_bo_qua_tep_hong({KEY: MD5_CU}, KEY, MD5_CU, None))

    def test_tep_duoc_sua_thi_thu_lai(self):
        """md5 đổi = người đã sửa/quét lại tệp — phải đọc lại."""
        self.assertFalse(ll.nen_bo_qua_tep_hong({KEY: MD5_CU}, KEY, MD5_MOI, None))

    def test_tep_chua_tung_hong_khong_bi_cham(self):
        self.assertFalse(ll.nen_bo_qua_tep_hong({}, KEY, MD5_CU, None))
        self.assertFalse(ll.nen_bo_qua_tep_hong({"local:khac.pdf": MD5_CU},
                                                KEY, MD5_CU, None))

    def test_da_hoc_duoc_va_khong_doi_thi_khong_chan(self):
        """Tệp từng hỏng nhưng sau đó đã học được: luồng thường của nó chỉ cập
        nhật nhãn, không đọc tệp — chặn ở đây là chặn nhầm việc gắn lại nhãn."""
        self.assertFalse(
            ll.nen_bo_qua_tep_hong({KEY: MD5_CU}, KEY, MD5_CU, _row(MD5_CU)))

    def test_ban_ghi_mang_md5_khac_thi_van_bo_qua(self):
        """Bản ghi cũ mang md5 khác nghĩa là sắp HỌC ĐÈ bằng tệp hiện tại — mà
        tệp hiện tại đúng là bản đã hỏng, nên đọc lại cũng vô ích."""
        self.assertTrue(
            ll.nen_bo_qua_tep_hong({KEY: MD5_CU}, KEY, MD5_CU, _row(MD5_MOI)))

    def test_khong_co_md5_thi_khong_bo_qua(self):
        """Dòng lỗi cũ (trước 16/09) chưa có md5 — phải thử lại một lần để ghi
        md5 xuống, sau đó mới yên."""
        self.assertFalse(ll.nen_bo_qua_tep_hong({KEY: None}, KEY, None, None))
        self.assertFalse(ll.nen_bo_qua_tep_hong({KEY: None}, KEY, MD5_CU, None))


class NhatKyLoiTests(unittest.TestCase):
    def test_doc_duoc_thi_tra_ve_dict(self):
        cur = mock.MagicMock()
        cur.fetchall.return_value = [(KEY, MD5_CU), ("local:x.pdf", MD5_MOI)]
        with mock.patch.object(auto_learn.db, "session") as ses:
            ses.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = cur
            self.assertEqual(auto_learn.failed_fingerprints(),
                             {KEY: MD5_CU, "local:x.pdf": MD5_MOI})

    def test_csdl_hong_thi_tra_ve_rong_khong_no(self):
        """Thiếu cột checksum (chưa migrate) không được làm chết lượt quét:
        trả về rỗng = bộ quét chạy y như trước khi có tính năng này."""
        # Hứng phần in cảnh báo: bảng mã console Windows không in được tiếng
        # Việt, mà test này phải chạy cả trên máy phát triển lẫn máy chủ.
        with mock.patch.object(auto_learn.db, "session",
                               side_effect=RuntimeError("column does not exist")), \
                contextlib.redirect_stdout(io.StringIO()) as ra:
            self.assertEqual(auto_learn.failed_fingerprints(), {})
        self.assertIn("CẢNH BÁO", ra.getvalue())

    def test_ghi_loi_co_kem_md5(self):
        cur = mock.MagicMock()
        with mock.patch.object(auto_learn.db, "session") as ses:
            ses.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = cur
            auto_learn._record_failure(KEY, "scan.pdf", "9. HỒ SƠ",
                                       {"code": "no_text", "message": "m", "hint": "h"},
                                       checksum=MD5_CU)
        sql, params = cur.execute.call_args[0]
        self.assertIn("checksum", sql)
        self.assertEqual(params[-1], MD5_CU)

    def test_ghi_loi_khong_kem_md5_van_chay(self):
        """Đường cũ (api.py gọi khi tải tệp qua web) không truyền md5 — vẫn phải
        ghi được, chỉ là lượt quét sau sẽ thử tệp đó thêm một lần."""
        cur = mock.MagicMock()
        with mock.patch.object(auto_learn.db, "session") as ses:
            ses.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = cur
            auto_learn._record_failure(KEY, "scan.pdf", "9. HỒ SƠ",
                                       {"code": "no_text", "message": "m", "hint": "h"})
        self.assertIsNone(cur.execute.call_args[0][1][-1])


class LichQuetTests(unittest.TestCase):
    def test_cron_ba_phut(self):
        """Chu kỳ quét trong deploy/hoc-tu-thu-muc.sh phải khớp con số nêu ở
        sổ tay: đổi một chỗ mà quên chỗ kia là người vận hành đọc sai."""
        from pathlib import Path
        sh = (Path(__file__).resolve().parents[2] / "deploy" / "hoc-tu-thu-muc.sh")
        noi_dung = sh.read_text(encoding="utf-8")
        self.assertIn('CRON_LINE="*/3 * * * *', noi_dung)
        self.assertIn("OnUnitActiveSec=3min", noi_dung)
        self.assertNotIn("*/15 * * * *", noi_dung)


class LamSachKyTuDieuKhienTests(unittest.TestCase):
    """Ký tự NUL từ OCR làm PostgreSQL từ chối ghi, và cả lượt học chết ở bước
    cuối. Làm sạch ngay trong ingest.clean() — điểm mọi đường trích xuất đi qua."""

    def test_bo_ky_tu_nul(self):
        from app import ingest
        self.assertEqual(ingest.clean("Điều 1.\x00 Nội dung"), "Điều 1. Nội dung")

    def test_bo_ky_tu_dieu_khien_khac(self):
        from app import ingest
        self.assertEqual(ingest.clean("A\x01B\x1fC\x7fD"), "ABCD")

    def test_giu_tab_va_xuong_dong(self):
        from app import ingest
        self.assertEqual(ingest.clean("dòng 1\n\ndòng 2"), "dòng 1\n\ndòng 2")
        self.assertEqual(ingest.clean("cột 1\tcột 2"), "cột 1 cột 2")

    def test_van_ban_sach_khong_doi(self):
        from app import ingest
        goc = "Điều 5. Thời hiệu khởi kiện\nHai năm kể từ ngày quyền bị xâm phạm."
        self.assertEqual(ingest.clean(goc), goc)


class NapBanGhiMotLanTests(unittest.TestCase):
    """Vòng 1 của bộ quét phải đọc bản ghi từ bộ nhớ, không hỏi CSDL từng tệp.
    Đo 16/09/2026: 6,9 ms mỗi lời gọi existing() × 42 nghìn tệp = 288 giây."""

    def test_existing_map_giu_dung_thu_tu_cot(self):
        """Hàng trả về phải xếp cột y như existing(), nếu không row[1] (md5)
        thành thứ khác và bộ quét học lại toàn kho."""
        hang = (1, "md5", "law", "public", None, None, None, True, True, "Tên", None)
        cur = mock.MagicMock()
        cur.fetchall.return_value = [("local:a.pdf",) + hang]
        with mock.patch.object(auto_learn.db, "session") as ses:
            ses.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = cur
            ket_qua = auto_learn.existing_map("local:")
        self.assertEqual(ket_qua, {"local:a.pdf": hang})
        self.assertEqual(ket_qua["local:a.pdf"][1], "md5")

    def test_existing_map_truy_van_mot_lan(self):
        cur = mock.MagicMock()
        cur.fetchall.return_value = []
        with mock.patch.object(auto_learn.db, "session") as ses:
            ses.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = cur
            auto_learn.existing_map("local:")
        self.assertEqual(cur.execute.call_count, 1)
        self.assertEqual(cur.execute.call_args[0][1], ("local:%",))

class NhoNhanTheoThuMucTests(unittest.TestCase):
    """Nhãn suy từ đường dẫn thư mục nên mọi tệp cùng thư mục có cùng nhãn;
    hỏi CSDL lại cho từng tệp là 74 giây mỗi lượt quét (đo 16/09/2026)."""

    def _chay_vong_nhan(self, danh_sach_parts, dry_run=False):
        """Dựng lại đúng đoạn đệm nhãn của run() để kiểm mà không cần CSDL."""
        goi = []

        def gia_resolve(parts, create_missing_client=True):
            goi.append(tuple(parts))
            return {"doc_type": "ho_so_kh", "client_id": 7}, None

        label_cache = {}

        def nhan_cho(parts):
            khoa = tuple(parts)
            if khoa not in label_cache:
                label_cache[khoa] = gia_resolve(parts, create_missing_client=not dry_run)
            labels, reason = label_cache[khoa]
            return (dict(labels) if labels is not None else None), reason

        ket = [nhan_cho(p) for p in danh_sach_parts]
        return goi, ket

    def test_cung_thu_muc_chi_hoi_mot_lan(self):
        parts = ["9. HỒ SƠ KHÁCH HÀNG", "1043. Chị Trang"]
        goi, ket = self._chay_vong_nhan([parts, parts, parts])
        self.assertEqual(len(goi), 1)
        self.assertEqual(len(ket), 3)

    def test_thu_muc_khac_thi_hoi_lai(self):
        goi, _ = self._chay_vong_nhan([["9. HỒ SƠ", "A"], ["9. HỒ SƠ", "B"]])
        self.assertEqual(len(goi), 2)

    def test_moi_te_p_nhan_ban_sao_rieng(self):
        """Nơi gọi thêm khoá vào dict nhãn; sửa bản trong đệm là tệp sau lĩnh đủ."""
        parts = ["9. HỒ SƠ", "A"]
        _, ket = self._chay_vong_nhan([parts, parts])
        ket[0][0]["title_context"] = "Chị Trang"
        self.assertNotIn("title_context", ket[1][0])

if __name__ == "__main__":
    unittest.main()
