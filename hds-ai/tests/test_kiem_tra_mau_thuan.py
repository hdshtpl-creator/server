"""
Test KIỂM TRA MÂU THUẪN PHÁP LÝ khi soạn thảo — thuần, không cần PostgreSQL/Ollama
(model và tìm luật giả bằng lambda).

Chay: D:\\hds-venv\\Scripts\\python.exe -m unittest tests.test_kiem_tra_mau_thuan -v

Bốn thứ phải đứng vững:
  1. Regex trích đúng con số + quy đổi đơn vị (2 %/tháng → 24 %/năm), một con số
     chỉ vào MỘT mục, vi_tri gắn đúng "Điều n".
  2. Quy tắc tất định phán đúng trần luật (468 BLDS, 301 LTM, 25/26/20/105 BLLĐ).
  3. doc_json bóc được JSON dù model chèn <think> + fence; hỏng → mặc định.
  4. chay_kiem_tra không bao giờ ném vì callback; có AI thì mục khong_ro được đối
     chiếu và mang "nguon".
"""
import json
import unittest

from app import kiem_tra_mau_thuan as kt


def _theo_loai(muc, loai):
    return [m for m in muc if m["loai"] == loai]


HD_VAY = """HỢP ĐỒNG VAY TIỀN
Điều 1. Số tiền vay
Bên A cho Bên B vay số tiền 500.000.000 đồng (năm trăm triệu đồng).
Điều 2. Lãi suất
Lãi suất cho vay là 2%/tháng, tính trên dư nợ thực tế.
Điều 3. Phạt vi phạm
Bên vi phạm phải chịu phạt vi phạm 10% giá trị hợp đồng.
"""

HD_LAO_DONG = """HỢP ĐỒNG LAO ĐỘNG
Điều 1. Thời hạn và công việc
Loại hợp đồng: xác định thời hạn. Thời hạn hợp đồng: 48 tháng.
Điều 2. Thử việc
Thời gian thử việc 90 ngày. Lương thử việc bằng 80% lương chính thức.
Điều 3. Thời giờ làm việc
Người lao động làm việc 8 giờ/ngày, 48 giờ/tuần.
"""


class BoDauTests(unittest.TestCase):
    def test_bo_dau(self):
        self.assertEqual(kt.bo_dau("Lãi Suất Điều 468"), "lai suat dieu 468")


class TrichXuatTests(unittest.TestCase):
    def test_lai_suat_thang_quy_ve_nam(self):
        muc = kt.trich_xuat_quy_tac(HD_VAY)
        ls = _theo_loai(muc, "lai_suat")
        self.assertEqual(len(ls), 1)
        self.assertAlmostEqual(ls[0]["gia_tri"], 24.0)
        self.assertEqual(ls[0]["don_vi"], "%/nam")
        self.assertEqual(ls[0]["vi_tri"], "Điều 2")
        self.assertIn("2%/tháng", ls[0]["trich"])
        self.assertFalse(ls[0]["ngu_canh_lao_dong"])

    def test_so_tien_va_phat(self):
        muc = kt.trich_xuat_quy_tac(HD_VAY)
        st = _theo_loai(muc, "so_tien")
        self.assertEqual(len(st), 1)
        self.assertEqual(st[0]["gia_tri"], 500_000_000)
        self.assertEqual(st[0]["don_vi"], "dong")
        pv = _theo_loai(muc, "phat_vi_pham")
        self.assertEqual(len(pv), 1)
        self.assertEqual(pv[0]["gia_tri"], 10)
        # Số "10" đã vào phat_vi_pham thì không được thành ty_le nữa.
        self.assertEqual(_theo_loai(muc, "ty_le"), [])
        # Số trong tiêu đề "Điều 1/2/3" không thành mục.
        self.assertEqual(len(muc), 3)

    def test_hop_dong_lao_dong(self):
        muc = kt.trich_xuat_quy_tac(HD_LAO_DONG)
        loai = sorted(m["loai"] for m in muc)
        self.assertEqual(loai, sorted(["thoi_han_hop_dong", "thu_viec", "luong_thu_viec",
                                       "gio_lam_viec_ngay", "gio_lam_viec_tuan"]))
        self.assertTrue(all(m["ngu_canh_lao_dong"] for m in muc))
        self.assertEqual(_theo_loai(muc, "thu_viec")[0]["gia_tri"], 90)
        self.assertEqual(_theo_loai(muc, "luong_thu_viec")[0]["gia_tri"], 80)
        self.assertEqual(_theo_loai(muc, "thoi_han_hop_dong")[0]["gia_tri"], 48)
        self.assertEqual(_theo_loai(muc, "gio_lam_viec_tuan")[0]["vi_tri"], "Điều 3")

    def test_thu_viec_thang_quy_ve_ngay(self):
        muc = kt.trich_xuat_quy_tac("Thời gian thử việc: 02 tháng kể từ ngày nhận việc.")
        self.assertEqual(_theo_loai(muc, "thu_viec")[0]["gia_tri"], 60)

    def test_ngay_khong_bi_bat_thanh_thoi_han(self):
        muc = kt.trich_xuat_quy_tac("Thử việc từ ngày 1 tháng 3 năm 2026.")
        self.assertEqual([m["loai"] for m in muc], ["ngay"])
        self.assertEqual(muc[0]["iso"], "2026-03-01")

    def test_vi_tri_dieu_3(self):
        text = "Điều 1. Chung\nKhông có số.\nĐiều 3. Lãi suất\nLãi suất 12%/năm.\n"
        muc = kt.trich_xuat_quy_tac(text)
        self.assertEqual(muc[0]["loai"], "lai_suat")
        self.assertEqual(muc[0]["vi_tri"], "Điều 3")
        muc2 = kt.trich_xuat_quy_tac("Lãi suất 12%/năm.")
        self.assertIsNone(muc2[0]["vi_tri"])

    def test_dat_coc_va_trieu_ty(self):
        muc = kt.trich_xuat_quy_tac(
            "Bên B đặt cọc 30% giá trị hợp đồng. Giá bán 2,5 tỷ đồng, thanh toán 500 triệu đợt 1.")
        dc = _theo_loai(muc, "dat_coc")
        self.assertEqual((dc[0]["gia_tri"], dc[0]["don_vi"]), (30, "%"))
        st = sorted(m["gia_tri"] for m in _theo_loai(muc, "so_tien"))
        self.assertEqual(st, [500_000_000, 2_500_000_000])

    def test_bao_truoc_lam_them_thoi_han(self):
        muc = kt.trich_xuat_quy_tac(
            "Người lao động phải báo trước ít nhất 30 ngày. Làm thêm không quá 50 giờ/tháng. "
            "Giao hàng trong vòng 15 ngày.")
        self.assertEqual(_theo_loai(muc, "bao_truoc")[0]["gia_tri"], 30)
        self.assertEqual(_theo_loai(muc, "lam_them_thang")[0]["gia_tri"], 50)
        th = _theo_loai(muc, "thoi_han")[0]
        self.assertEqual((th["gia_tri"], th["don_vi"]), (15, "ngay"))

    def test_trich_khong_qua_220(self):
        text = "Lãi suất 25%/năm " + "x" * 600
        muc = kt.trich_xuat_quy_tac(text)
        self.assertLessEqual(len(muc[0]["trich"]), 220)
        self.assertIn("25%/năm", muc[0]["trich"])

    def test_tran_60_muc_uu_tien_cu_the(self):
        text = "Lãi suất 30%/năm.\n" + "\n".join(f"tỷ lệ {i}%" for i in range(1, 100))
        muc = kt.trich_xuat_quy_tac(text)
        self.assertEqual(len(muc), 60)
        self.assertEqual(muc[0]["loai"], "lai_suat")

    def test_rong(self):
        self.assertEqual(kt.trich_xuat_quy_tac(""), [])


class QuyTacTests(unittest.TestCase):
    def test_lai_suat(self):
        cb = kt.kiem_tra_quy_tac(kt.trich_xuat_quy_tac(HD_VAY))
        ls = _theo_loai(cb, "lai_suat")[0]
        self.assertEqual(ls["ket_luan"], "canh_bao")
        self.assertIn("vượt trần lãi suất", ls["ly_do"])
        self.assertIn("Điều 468", ls["can_cu"])
        self.assertEqual(ls["phuong_phap"], "quy_tac")
        ok = kt.kiem_tra_quy_tac(kt.trich_xuat_quy_tac("Lãi suất 12%/năm."))[0]
        self.assertEqual(ok["ket_luan"], "hop_le")

    def test_phat_vi_pham(self):
        cb = kt.kiem_tra_quy_tac(kt.trich_xuat_quy_tac("phạt vi phạm 10% giá trị hợp đồng"))[0]
        self.assertEqual(cb["ket_luan"], "canh_bao")
        self.assertIn("Điều 301", cb["can_cu"])
        self.assertIn("thương mại", cb["ly_do"])
        ok = kt.kiem_tra_quy_tac(kt.trich_xuat_quy_tac("mức phạt 8% giá trị nghĩa vụ"))[0]
        self.assertEqual(ok["ket_luan"], "hop_le")
        self.assertIn("418", ok["ly_do"])

    def test_hop_dong_lao_dong(self):
        muc = kt.kiem_tra_quy_tac(kt.trich_xuat_quy_tac(HD_LAO_DONG))
        cb = {m["loai"] for m in muc if m["ket_luan"] == "canh_bao"}
        hl = {m["loai"] for m in muc if m["ket_luan"] == "hop_le"}
        self.assertEqual(cb, {"thu_viec", "luong_thu_viec", "thoi_han_hop_dong"})
        self.assertEqual(hl, {"gio_lam_viec_ngay", "gio_lam_viec_tuan"})
        can_cu = {m["loai"]: m["can_cu"] for m in muc}
        self.assertIn("Điều 25", can_cu["thu_viec"])
        self.assertIn("Điều 26", can_cu["luong_thu_viec"])
        self.assertIn("Điều 20", can_cu["thoi_han_hop_dong"])
        self.assertIn("Điều 105", can_cu["gio_lam_viec_ngay"])

    def test_thoi_han_dai_ngoai_lao_dong(self):
        muc = kt.kiem_tra_quy_tac(kt.trich_xuat_quy_tac("Thời hạn hợp đồng thuê: 5 năm."))
        self.assertEqual(muc[0]["loai"], "thoi_han_hop_dong")
        self.assertEqual(muc[0]["gia_tri"], 60)
        self.assertEqual(muc[0]["ket_luan"], "khong_ro")
        self.assertIn("cần luật sư xem", muc[0]["ly_do"])

    def test_gio_va_lam_them_vuot(self):
        muc = kt.kiem_tra_quy_tac(kt.trich_xuat_quy_tac(
            "Người lao động làm 10 giờ/ngày, 50 giờ/tuần; làm thêm 45 giờ/tháng và 250 giờ/năm."))
        kl = {m["loai"]: (m["ket_luan"], m["can_cu"]) for m in muc}
        self.assertEqual(kl["gio_lam_viec_ngay"][0], "canh_bao")
        self.assertEqual(kl["gio_lam_viec_tuan"][0], "canh_bao")
        self.assertEqual(kl["lam_them_thang"], ("canh_bao", "Điều 107 Bộ luật Lao động 2019"))
        self.assertEqual(kl["lam_them_nam"][0], "canh_bao")

    def test_bao_truoc(self):
        ld = kt.kiem_tra_quy_tac(kt.trich_xuat_quy_tac(
            "Người lao động muốn nghỉ phải báo trước 15 ngày."))[0]
        self.assertEqual(ld["ket_luan"], "khong_ro")
        self.assertIn("30", ld["ly_do"])
        self.assertIn("45", ld["ly_do"])
        self.assertIn("Điều 35", ld["can_cu"])
        khac = kt.kiem_tra_quy_tac(kt.trich_xuat_quy_tac(
            "Bên thuê phải báo trước 15 ngày khi trả nhà."))[0]
        self.assertEqual(khac["ket_luan"], "khong_ro")

    def test_loai_khac_khong_ro(self):
        muc = kt.kiem_tra_quy_tac(kt.trich_xuat_quy_tac(
            "Đặt cọc 100 triệu đồng. Tỷ lệ chia 40%. Giao trong vòng 10 ngày."))
        self.assertEqual({m["loai"] for m in muc}, {"dat_coc", "ty_le", "thoi_han"})
        self.assertTrue(all(m["ket_luan"] == "khong_ro" for m in muc))
        self.assertTrue(all("đối chiếu" in m["ly_do"] for m in muc))

    def test_khong_sua_dau_vao(self):
        goc = kt.trich_xuat_quy_tac(HD_VAY)
        kt.kiem_tra_quy_tac(goc)
        self.assertNotIn("ket_luan", goc[0])


class MocThoiGianTests(unittest.TestCase):
    def test_ngay_dao_nguoc(self):
        text = ("Hợp đồng có hiệu lực từ ngày 01/10/2026.\n"
                "Hợp đồng hết hạn ngày 01/09/2026.\n")
        muc = kt.kiem_tra_quy_tac(kt.trich_xuat_quy_tac(text))
        self.assertEqual([m["loai"] for m in muc], ["ngay", "ngay"])
        self.assertEqual([m["vai_tro"] for m in muc], ["hieu_luc", "het_han"])
        self.assertTrue(all(m["ket_luan"] == "canh_bao" for m in muc))
        self.assertIn("đảo ngược", muc[0]["ly_do"])

    def test_ngay_dung_thu_tu(self):
        text = "Ký ngày 01 tháng 9 năm 2026, kết thúc ngày 31/12/2027."
        muc = kt.kiem_tra_quy_tac(kt.trich_xuat_quy_tac(text))
        self.assertEqual(len(muc), 2)
        self.assertTrue(all(m["ket_luan"] == "hop_le" for m in muc))

    def test_mot_ngay_hop_le(self):
        muc = kt.kiem_tra_quy_tac(kt.trich_xuat_quy_tac("Ngày sinh 15/05/1990."))
        self.assertEqual(muc[0]["ket_luan"], "hop_le")

    def test_ham_rieng(self):
        muc = [{"loai": "ngay", "iso": "2026-10-01", "vai_tro": "hieu_luc"},
               {"loai": "ngay", "iso": "2026-09-01", "vai_tro": "het_han"},
               {"loai": "ty_le", "gia_tri": 5}]
        ket = kt.kiem_tra_moc_thoi_gian(muc)
        self.assertEqual(ket[0][0], "canh_bao")
        self.assertEqual(ket[1][0], "canh_bao")
        self.assertNotIn(2, ket)


class DocJsonTests(unittest.TestCase):
    def test_boc_think_va_fence(self):
        raw = "<think>suy nghĩ dài\nnhiều dòng</think>Kết quả:\n```json\n[{\"loai\": \"cam_ket\", \"trich\": \"x\"}]\n```"
        self.assertEqual(kt.doc_json(raw, []), [{"loai": "cam_ket", "trich": "x"}])

    def test_khoi_dau_tien(self):
        raw = "Đây là kết quả {\"ket_luan\": \"hop_le\", \"ly_do\": \"ok\"} thêm chữ."
        self.assertEqual(kt.doc_json(raw, None)["ket_luan"], "hop_le")

    def test_hong_ve_mac_dinh(self):
        self.assertEqual(kt.doc_json("không có json gì cả", []), [])
        self.assertEqual(kt.doc_json("{hỏng: ", {"a": 1}), {"a": 1})
        self.assertEqual(kt.doc_json("", "mac"), "mac")
        self.assertEqual(kt.doc_json(None, "mac"), "mac")


class TongHopTests(unittest.TestCase):
    def test_rong(self):
        self.assertEqual(kt.tong_hop([])["ket_luan"], "khong_ro")
        self.assertEqual(kt.tong_hop([])["so_muc"], 0)

    def test_uu_tien_canh_bao(self):
        t = kt.tong_hop([{"ket_luan": "hop_le"}, {"ket_luan": "canh_bao"}, {"ket_luan": "khong_ro"}])
        self.assertEqual(t["ket_luan"], "canh_bao")
        self.assertEqual((t["so_canh_bao"], t["so_hop_le"], t["so_khong_ro"], t["so_muc"]), (1, 1, 1, 3))
        self.assertEqual(kt.tong_hop([{"ket_luan": "hop_le"}, {"ket_luan": "khong_ro"}])["ket_luan"], "hop_le")
        self.assertEqual(kt.tong_hop([{"ket_luan": "khong_ro"}])["ket_luan"], "khong_ro")


class PromptTests(unittest.TestCase):
    def test_prompt_trich_cam_ket_cat_12000(self):
        system, prompt = kt.prompt_trich_cam_ket("a" * 20_000)
        self.assertIn("JSON", system)
        self.assertLess(len(prompt), 12_000 + 1_500)
        self.assertIn("cam_ket", prompt)

    def test_prompt_doi_chieu(self):
        muc = {"loai": "dat_coc", "trich": "Đặt cọc 30%", "gia_tri": 30, "don_vi": "%", "vi_tri": "Điều 4"}
        system, prompt = kt.prompt_doi_chieu(muc, [
            {"title": "BLDS 2015 — Điều 328", "content": "Đặt cọc là việc…", "so_hieu": "91/2015/QH13"}])
        self.assertIn("khong_ro", system)
        self.assertIn("91/2015/QH13", prompt)
        self.assertIn("Điều 328", prompt)
        self.assertIn("Đặt cọc 30%", prompt)
        system2, prompt2 = kt.prompt_doi_chieu(muc, [])
        self.assertIn("không có đoạn luật", prompt2)


HD_AI = """HỢP ĐỒNG MUA BÁN
Điều 1. Giá và lãi
Lãi suất chậm trả 30%/năm.
Điều 2. Đặt cọc
Bên B đặt cọc 30% giá trị hợp đồng ngay khi ký.
Điều 3. Nghĩa vụ
Bên A phải bàn giao nhà đúng hiện trạng.
"""

CAM_KET_JSON = json.dumps([{"loai": "cam_ket", "trich": "Bên A phải bàn giao nhà đúng hiện trạng.",
                            "vi_tri": "Điều 3", "noi_dung": "Nghĩa vụ bàn giao"}], ensure_ascii=False)
DOI_CHIEU_JSON = json.dumps({"ket_luan": "canh_bao", "ly_do": "Mức cọc không được vượt quá giá trị đã thoả thuận",
                             "dieu_luat": "Điều 328 Bộ luật Dân sự 2015"}, ensure_ascii=False)


def _llm_gia(prompt, system):
    return DOI_CHIEU_JSON if "ĐOẠN LUẬT" in prompt else CAM_KET_JSON


def _tim_luat_gia(cau_hoi):
    return [{"title": "BLDS 2015 — Điều 328", "content": "Đặt cọc…", "so_hieu": "91/2015/QH13",
             "document_id": 5, "chunk_id": 77}]


class ChayKiemTraTests(unittest.TestCase):
    def test_chi_quy_tac(self):
        kq = kt.chay_kiem_tra(HD_AI)
        self.assertEqual(kq["phuong_phap"], "quy_tac")
        self.assertEqual(kq["so_ky_tu"], len(HD_AI))
        self.assertEqual(kq["tong_ket"], kt.tong_hop(kq["muc"]))
        self.assertEqual(kq["tong_ket"]["ket_luan"], "canh_bao")
        self.assertEqual({m["loai"] for m in kq["muc"]}, {"lai_suat", "dat_coc"})

    def test_co_ai(self):
        kq = kt.chay_kiem_tra(HD_AI, llm=_llm_gia, tim_luat=_tim_luat_gia, model="qwen")
        self.assertEqual(kq["phuong_phap"], "quy_tac+ai")
        ck = _theo_loai(kq["muc"], "cam_ket")
        self.assertEqual(len(ck), 1)
        self.assertEqual(ck[0]["vi_tri"], "Điều 3")
        dc = _theo_loai(kq["muc"], "dat_coc")[0]
        self.assertEqual(dc["ket_luan"], "canh_bao")
        self.assertEqual(dc["phuong_phap"], "ai")
        self.assertIn("Điều 328", dc["can_cu"])
        self.assertIn("91/2015/QH13", dc["can_cu"])
        self.assertEqual(dc["nguon"], [{"document_id": 5, "chunk_id": 77, "title": "BLDS 2015 — Điều 328"}])
        # Mục quy tắc đã phán thì model KHÔNG được đụng.
        ls = _theo_loai(kq["muc"], "lai_suat")[0]
        self.assertEqual((ls["ket_luan"], ls["phuong_phap"]), ("canh_bao", "quy_tac"))
        self.assertEqual(kq["tong_ket"]["so_khong_ro"], 0)

    def test_toi_da_ai(self):
        goi = []

        def tim(cau_hoi):
            goi.append(cau_hoi)
            return _tim_luat_gia(cau_hoi)
        kq = kt.chay_kiem_tra(HD_AI, llm=_llm_gia, tim_luat=tim, toi_da_ai=1)
        self.assertEqual(len(goi), 1)
        # Ưu tiên cam_ket trước dat_coc.
        self.assertIn("cam kết", goi[0])
        self.assertEqual(_theo_loai(kq["muc"], "dat_coc")[0]["ket_luan"], "khong_ro")

    def test_llm_nem_loi_khong_lam_hong(self):
        def hong(prompt, system):
            raise RuntimeError("ollama chết")
        kq = kt.chay_kiem_tra(HD_AI, llm=hong, tim_luat=_tim_luat_gia)
        self.assertEqual(kq["phuong_phap"], "quy_tac")
        self.assertEqual(_theo_loai(kq["muc"], "lai_suat")[0]["ket_luan"], "canh_bao")

    def test_tim_luat_nem_loi(self):
        def hong(q):
            raise ValueError("db down")
        kq = kt.chay_kiem_tra(HD_AI, llm=_llm_gia, tim_luat=hong)
        self.assertEqual(len(_theo_loai(kq["muc"], "cam_ket")), 1)
        self.assertEqual(_theo_loai(kq["muc"], "dat_coc")[0]["ket_luan"], "khong_ro")

    def test_llm_tra_rac(self):
        kq = kt.chay_kiem_tra(HD_AI, llm=lambda p, s: "tôi không biết", tim_luat=_tim_luat_gia)
        self.assertEqual(_theo_loai(kq["muc"], "cam_ket"), [])
        self.assertEqual(_theo_loai(kq["muc"], "dat_coc")[0]["ket_luan"], "khong_ro")

    def test_van_ban_rong(self):
        kq = kt.chay_kiem_tra("")
        self.assertEqual(kq["muc"], [])
        self.assertEqual(kq["tong_ket"]["ket_luan"], "khong_ro")


if __name__ == "__main__":
    unittest.main()
