"""Panel nguồn trích dẫn — phản hồi 06/09/2026.

Hỏi "tóm tắt file" với một PDF scan đính kèm: panel hiện 55 nguồn, tất cả
"[File: 005_2024HĐM 91.pdf] — Liên quan 100%", nguồn số 1 là dòng nhắn
"(File dài, bản tóm tắt đang chuẩn bị ở nền…)", đoạn trích đầy ".~. ..—" và
mốc [Trang n]. Các test dưới khoá lại từng lỗi đó ở tầng backend.

Toàn bộ là logic thuần — không chạm CSDL, không gọi Ollama (deploy/update.sh
chạy nguyên bộ test ngay trên máy chủ đang phục vụ).
"""
import unittest

from app import rag


def _dinh_kem(ten, noi_dung, tom_tat=False):
    return rag._nguon_dinh_kem(ten, noi_dung, tom_tat=tom_tat)


class LamSachDoanTrich(unittest.TestCase):
    def test_bo_moc_trang_ky_tu_vo_hinh_va_rac_ocr(self):
        raw = ("\ufeff[Trang 1] .~. ..— MẪU HỢP ĐỒNG MUA BÁN CĂN HỘ CHUNG CƯ "
               "[Trang 2] CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM Độc lập — Tự do - "
               "Hạnh phúc ¬—- , Ngày......tháng......năm 20")
        s = rag.lam_sach_trich(raw)
        self.assertNotIn("[Trang", s)
        self.assertNotIn("\ufeff", s)
        self.assertNotIn(".~.", s)
        self.assertNotIn("..—", s)
        self.assertNotIn("¬", s)
        self.assertNotIn("......", s)
        self.assertIn("MẪU HỢP ĐỒNG MUA BÁN CĂN HỘ CHUNG CƯ", s)
        self.assertIn("Độc lập — Tự do - Hạnh phúc", s)   # gạch thật giữ nguyên
        self.assertIn("Ngày… tháng… năm 20", s)

    def test_khong_pha_dau_cau_that(self):
        # ")." và "--" là dấu thật của văn bản — bỏ đi câu đọc sai nghĩa.
        s = rag.lam_sach_trich("theo khoản 2 (Điều 5 ). Ghi chú -- xem thêm")
        self.assertIn("(Điều 5 ).", s)
        self.assertIn("--", s)


class PhanLoaiNguon(unittest.TestCase):
    def test_uu_tien_kind_gan_san(self):
        self.assertEqual(("attachment", "a.pdf", False),
                         rag.phan_loai_nguon(_dinh_kem("a.pdf", "x")))
        self.assertEqual(("attachment", "a.pdf", True),
                         rag.phan_loai_nguon(_dinh_kem("a.pdf", "x", tom_tat=True)))
        self.assertEqual("notice", rag.phan_loai_nguon(rag._nguon_chua_tom_tat("a.pdf"))[0])

    def test_doan_tu_tieu_de_cho_du_lieu_cu(self):
        # Tin nhắn lưu từ trước 06/09 không có `kind` — vẫn nhận ra qua tiêu đề.
        self.assertEqual(("attachment", "cu.docx", False),
                         rag.phan_loai_nguon({"title": "[File: cu.docx]"}))
        self.assertEqual(("attachment", "cu.docx", True),
                         rag.phan_loai_nguon({"title": "[Tóm tắt file: cu.docx]"}))
        self.assertEqual("user_provided",
                         rag.phan_loai_nguon({"title": rag.NGUOI_DUNG_DAN_TITLE})[0])
        self.assertEqual("document", rag.phan_loai_nguon({"title": "Luật X"})[0])


class FormatSourcesChoFileDinhKem(unittest.TestCase):
    def test_trang_lay_tu_moc_trong_doan_va_quote_sach(self):
        chunk = _dinh_kem("hd.pdf", "[Trang 1] .~. ..— MẪU HỢP ĐỒNG [Trang 2] Điều 1")
        src = rag.format_sources([chunk])[0]
        self.assertEqual("attachment", src["kind"])
        self.assertEqual("hd.pdf", src["attachment_name"])
        self.assertEqual("1–2", src["page_number"])
        self.assertNotIn("[Trang", src["quote"])
        self.assertNotIn(".~.", src["quote"])

    def test_mot_trang_thi_khong_thanh_khoang(self):
        src = rag.format_sources([_dinh_kem("hd.pdf", "[Trang 3] Điều 7 phạt")])[0]
        self.assertEqual("3", src["page_number"])

    def test_khong_de_page_number_cua_kho(self):
        src = rag.format_sources([{"title": "Luật X", "content": "[Trang 9] x",
                                   "page_number": 4}])[0]
        self.assertEqual(4, src["page_number"])
        self.assertEqual("document", src["kind"])


class LocNguonLienQuanVoiFileDinhKem(unittest.TestCase):
    """Đúng ca 06/09: một file 55 đoạn, bot dẫn 2 đoạn."""

    def _evidence(self, so_doan=55, co_tom_tat=False, co_notice=False):
        chunks = []
        if co_notice:
            chunks.append(rag._nguon_chua_tom_tat("hd.pdf"))
        if co_tom_tat:
            chunks.append(_dinh_kem("hd.pdf", "tóm tắt cả file", tom_tat=True))
        chunks += [_dinh_kem("hd.pdf", f"[Trang {i}] đoạn {i}") for i in range(1, so_doan + 1)]
        return rag.format_sources(chunks)

    def test_chi_giu_doan_duoc_dan(self):
        ev = self._evidence()
        kept = rag.relevant_sources("Thời hạn 30 ngày [Nguồn 3] và phạt [Nguồn 17].", ev)
        self.assertEqual([3, 17], [e["n"] for e in kept])

    def test_thong_bao_chua_tom_tat_khong_bao_gio_la_nguon(self):
        ev = self._evidence(co_notice=True)
        self.assertEqual("notice", ev[0]["kind"])
        kept = rag.relevant_sources("Nội dung [Nguồn 2].", ev)
        self.assertTrue(all(e["kind"] != "notice" for e in kept))
        self.assertEqual([2], [e["n"] for e in kept])

    def test_file_khong_duoc_dan_van_hien_mot_lan(self):
        # Tóm tắt thường không đánh số nguồn — vẫn cần MỘT thẻ để biết bot đã
        # đọc file, không phải 55 thẻ.
        ev = self._evidence()
        kept = rag.relevant_sources("Hợp đồng gồm 12 điều, không trích dẫn số.", ev)
        self.assertEqual(1, len(kept))
        self.assertEqual("hd.pdf", kept[0]["attachment_name"])

    def test_uu_tien_ban_tom_tat_lam_dai_dien(self):
        ev = self._evidence(co_tom_tat=True)
        kept = rag.relevant_sources("không dẫn số", ev)
        self.assertEqual(1, len(kept))
        self.assertTrue(kept[0]["is_summary"])

    def test_hai_file_moi_file_mot_the(self):
        ev = rag.format_sources(
            [_dinh_kem("a.pdf", f"a{i}") for i in range(5)]
            + [_dinh_kem("b.docx", f"b{i}") for i in range(5)])
        kept = rag.relevant_sources("không dẫn", ev)
        self.assertEqual(["a.pdf", "b.docx"], [e["attachment_name"] for e in kept])

    def test_nguoi_dung_dan_chi_giu_khi_duoc_dan(self):
        ev = rag.format_sources([
            {"title": rag.NGUOI_DUNG_DAN_TITLE, "content": "Điều 429…", "score": 1.0,
             "kind": "user_provided"},
            {"title": "Luật X", "content": "x", "score": 0.7},
        ])
        self.assertEqual([2], [e["n"] for e in rag.relevant_sources("theo luật", ev)])
        self.assertEqual([1, 2], [e["n"] for e in rag.relevant_sources("[Nguồn 1]", ev)])

    def test_quy_tac_cu_cho_tai_lieu_kho_khong_doi(self):
        ev = [
            {"n": 1, "kind": "document", "title": "A", "score": 0.37},
            {"n": 2, "kind": "document", "title": "B", "score": 0.36},
            {"n": 3, "kind": "document", "title": "C", "score": 0.62},
        ]
        self.assertEqual([2, 3], [e["n"] for e in rag.relevant_sources("[Nguồn 2]", ev)])

    def test_thu_tu_theo_so_nguon(self):
        ev = self._evidence(so_doan=6)
        kept = rag.relevant_sources("[Nguồn 5] rồi [Nguồn 2]", ev)
        self.assertEqual([2, 5], [e["n"] for e in kept])


if __name__ == "__main__":
    unittest.main()
