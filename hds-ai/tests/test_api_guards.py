"""Van bảo vệ kênh chat công khai (app/api.py) — logic thuần, không cần CSDL.

Kênh public phục vụ người dân KHÔNG đăng nhập: không van là một người spam
nghẽn cả máy (mỗi câu tốn hàng chục giây LLM trên CPU), và một câu hỏi dài
cả megabyte thổi phồng prompt/embedding vô tội vạ.
"""
import types
import unittest

from fastapi import HTTPException

from app import api


def _request(ip="203.0.113.9", forwarded=None):
    headers = {}
    if forwarded:
        headers["x-forwarded-for"] = forwarded
    return types.SimpleNamespace(headers=headers,
                                 client=types.SimpleNamespace(host=ip))


def _body(question):
    return types.SimpleNamespace(question=question)


class CleanQuestionTests(unittest.TestCase):
    def test_cau_hoi_trong_bi_chan(self):
        with self.assertRaises(HTTPException) as ctx:
            api._clean_question(_body("   "))
        self.assertEqual(ctx.exception.status_code, 422)

    def test_cau_hoi_qua_dai_kenh_public(self):
        with self.assertRaises(HTTPException) as ctx:
            api._clean_question(_body("x" * (api.MAX_PUBLIC_QUESTION_CHARS + 1)),
                                public=True)
        self.assertEqual(ctx.exception.status_code, 413)

    def test_kenh_noi_bo_tran_rong_hon(self):
        long_q = "x" * (api.MAX_PUBLIC_QUESTION_CHARS + 1)
        self.assertEqual(api._clean_question(_body(long_q)), long_q)

    def test_cau_binh_thuong_duoc_strip(self):
        self.assertEqual(api._clean_question(_body("  thời hiệu là gì?  ")),
                         "thời hiệu là gì?")


class ChatModeGuardTests(unittest.TestCase):
    """Chế độ 'Kiểm tra pháp lý & tạo file mẫu' chỉ dành cho nội bộ.

    Khách đăng nhập (client_*) đi cùng endpoint /chat/stream nên chốt phải nằm
    ở validate: mode/template_doc_id của khách bị hạ về None, không phải 403 —
    câu hỏi thường của khách vẫn chạy."""

    def _body(self, mode=None, template_doc_id=None):
        return types.SimpleNamespace(mode=mode, template_doc_id=template_doc_id)

    def test_mode_hop_le_kenh_noi_bo(self):
        self.assertEqual(api._chat_mode(self._body("legal_review"), internal=True),
                         "legal_review")
        self.assertIsNone(api._chat_mode(self._body(None), internal=True))
        self.assertIsNone(api._chat_mode(self._body(""), internal=True))

    def test_mode_la_khach_bi_ha_ve_none(self):
        self.assertIsNone(api._chat_mode(self._body("legal_review"), internal=False))

    def test_mode_bay_bi_422(self):
        with self.assertRaises(HTTPException) as ctx:
            api._chat_mode(self._body("hack"), internal=True)
        self.assertEqual(ctx.exception.status_code, 422)

    def test_template_id_duong_kenh_noi_bo(self):
        self.assertEqual(
            api._chat_template_id(self._body(template_doc_id=7), internal=True), 7)
        self.assertIsNone(api._chat_template_id(self._body(), internal=True))

    def test_template_id_khach_bi_ha_ve_none(self):
        self.assertIsNone(
            api._chat_template_id(self._body(template_doc_id=7), internal=False))

    def test_template_id_am_bi_422(self):
        with self.assertRaises(HTTPException) as ctx:
            api._chat_template_id(self._body(template_doc_id=0), internal=True)
        self.assertEqual(ctx.exception.status_code, 422)


class PublicRateLimitTests(unittest.TestCase):
    def setUp(self):
        self._old_max = api.PUBLIC_RATE_MAX
        api.PUBLIC_RATE_MAX = 3
        api._public_hits.clear()

    def tearDown(self):
        api.PUBLIC_RATE_MAX = self._old_max
        api._public_hits.clear()

    def test_qua_nguong_bi_429(self):
        req = _request(ip="198.51.100.7")
        for _ in range(3):
            api._public_rate_check(req)      # trong hạn mức — không ném
        with self.assertRaises(HTTPException) as ctx:
            api._public_rate_check(req)
        self.assertEqual(ctx.exception.status_code, 429)

    def test_ip_khac_khong_bi_lay(self):
        for _ in range(3):
            api._public_rate_check(_request(ip="198.51.100.7"))
        # IP khác vẫn hỏi được bình thường.
        api._public_rate_check(_request(ip="198.51.100.8"))

    def test_lay_ip_tu_x_forwarded_for(self):
        # Sau nginx, IP thật nằm đầu danh sách X-Forwarded-For.
        for _ in range(3):
            api._public_rate_check(
                _request(ip="127.0.0.1", forwarded="198.51.100.9, 10.0.0.1"))
        with self.assertRaises(HTTPException):
            api._public_rate_check(
                _request(ip="127.0.0.1", forwarded="198.51.100.9, 10.0.0.1"))
        # Cùng địa chỉ proxy nhưng IP thật khác → không bị chặn lây.
        api._public_rate_check(
            _request(ip="127.0.0.1", forwarded="198.51.100.10, 10.0.0.1"))

    def test_dat_0_la_tat_van(self):
        api.PUBLIC_RATE_MAX = 0
        for _ in range(10):
            api._public_rate_check(_request(ip="198.51.100.7"))


class LearnAccessLevelTests(unittest.TestCase):
    """Phạm vi của bản ghi hỏi-đáp được nạp vào kho.

    Chỉ nhận 'internal' và 'public'. Mức 'client' bị chặn vì bản ghi này không
    gắn client_id nào: đặt mức đó là tạo tài liệu mà RLS lọc theo khách hàng
    không ai đọc được — hoặc tệ hơn, lọt sang khách khác. Chốt nằm TRƯỚC mọi
    lệnh CSDL nên test chạy được không cần Postgres.
    """

    REVIEWER = {"id": 1, "role": "lawyer", "can_review": True}

    def _goi(self, access_level):
        body = api.LearnIn(action="approve", access_level=access_level)
        return api.learn_review(1, body, user=self.REVIEWER)

    def test_muc_client_bi_chan(self):
        with self.assertRaises(HTTPException) as ctx:
            self._goi("client")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_muc_bia_bi_chan(self):
        with self.assertRaises(HTTPException) as ctx:
            self._goi("everyone")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_mac_dinh_la_noi_bo(self):
        self.assertEqual(api.LearnIn(action="approve").access_level, "internal")

    def test_hai_muc_hop_le_qua_duoc_chot(self):
        """'internal' và 'public' phải đi lọt qua chốt.

        CHẶN CSDL bằng patch, tuyệt đối không để test chạm Postgres thật:
        deploy/update.sh chạy nguyên bộ test NGAY TRÊN MÁY CHỦ đang phục vụ,
        có .env và Postgres sống. Gọi thẳng learn_review(action='approve') ở
        đó là nạp tài liệu rác vào kho tri thức và đóng báo cáo của tin nhắn
        id=1 — mỗi lần nâng cấp một lần, mà test vẫn báo OK.
        """
        sentinel = RuntimeError("cham toi CSDL")

        def chan(*a, **kw):
            raise sentinel

        goc = api.db.session
        api.db.session = chan
        try:
            for muc in ("internal", "public"):
                with self.subTest(muc=muc):
                    with self.assertRaises(RuntimeError) as ctx:
                        self._goi(muc)
                    # Đúng sentinel = đã qua chốt access_level, chưa ghi gì.
                    self.assertIs(ctx.exception, sentinel)
        finally:
            api.db.session = goc

    def test_action_la_van_bi_chan_truoc(self):
        with self.assertRaises(HTTPException) as ctx:
            api.learn_review(1, api.LearnIn(action="xoa"), user=self.REVIEWER)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_nguoi_khong_co_quyen_duyet_bi_chan(self):
        with self.assertRaises(HTTPException) as ctx:
            api.learn_review(1, api.LearnIn(action="approve"),
                             user={"id": 2, "role": "staff", "can_review": False})
        self.assertEqual(ctx.exception.status_code, 403)


class ConversationKindTests(unittest.TestCase):
    """GET /conversations?kind=…: chốt giá trị nằm TRƯỚC mọi lệnh CSDL."""

    USER = {"id": 1, "role": "chuyen_vien", "can_review": False}

    def test_kind_la_bi_chan_400(self):
        with self.assertRaises(HTTPException) as ctx:
            api.conversations_list(user=self.USER, kind="tùm lum")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_kind_hop_le_qua_duoc_chot(self):
        # Chặn db.session bằng sentinel (bài học 28/08: update.sh chạy test
        # trên máy chủ thật — không được để lời gọi nào chạm Postgres).
        sentinel = RuntimeError("cham toi CSDL")

        def chan(*a, **kw):
            raise sentinel

        goc = api.db.session
        api.db.session = chan
        try:
            for kind in ("chat", "legal", "all"):
                with self.subTest(kind=kind):
                    with self.assertRaises(RuntimeError) as ctx:
                        api.conversations_list(user=self.USER, kind=kind)
                    self.assertIs(ctx.exception, sentinel)
        finally:
            api.db.session = goc


class ConversationCreateKindTests(unittest.TestCase):
    """POST /conversations?kind=… — hội thoại tạo TRƯỚC câu hỏi đầu (để kéo
    file vào là đính kèm được ngay) phải vào ĐÚNG cột lịch sử của tab gọi nó."""

    USER = {"id": 1, "role": "chuyen_vien", "can_review": False}

    def test_kind_la_bi_chan_400(self):
        with self.assertRaises(HTTPException) as ctx:
            api.conversation_create(user=self.USER, kind="tùm lum")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_moi_kind_dat_dung_tieu_de_va_kind(self):
        """Tab Hội thoại AI không được đẻ ra phiên mang nhãn 'legal' — phiên
        sẽ biến mất khỏi cột trái của chính nó và mọc sang tab kia."""
        ghi = {}

        def gia_lap(user_id, channel, client_id=None, title=None, kind="chat"):
            ghi["title"] = title
            ghi["kind"] = kind
            return 77

        goc = api.rag.start_conversation
        api.rag.start_conversation = gia_lap
        try:
            res = api.conversation_create(user=self.USER, kind="chat")
            self.assertEqual(res["conversation_id"], 77)
            self.assertEqual(ghi["kind"], "chat")
            self.assertTrue(ghi["title"].startswith("Cuộc trò chuyện"))

            api.conversation_create(user=self.USER, kind="legal")
            self.assertEqual(ghi["kind"], "legal")
            self.assertTrue(ghi["title"].startswith("Kiểm tra pháp lý"))
        finally:
            api.rag.start_conversation = goc

    def test_mac_dinh_van_la_legal_cho_giao_dien_cu(self):
        """Bản giao diện còn trong cache trình duyệt gọi không kèm tham số —
        mặc định phải giữ nguyên hành vi cũ, đừng ném phiên của họ sang cột
        khác cho tới khi họ nạp lại trang."""
        ghi = {}

        def gia_lap(user_id, channel, client_id=None, title=None, kind="chat"):
            ghi["kind"] = kind
            return 5

        goc = api.rag.start_conversation
        api.rag.start_conversation = gia_lap
        try:
            api.conversation_create(user=self.USER)
        finally:
            api.rag.start_conversation = goc
        self.assertEqual(ghi["kind"], "legal")


class QuanHeVanBanGuardTests(unittest.TestCase):
    """Endpoint quan hệ/metadata văn bản: chốt quyền + validate TRƯỚC mọi lệnh CSDL."""

    REVIEWER = {"id": 1, "role": "chuyen_vien", "can_review": True,
                "is_banqt": False, "can_finance": False,
                "dept_ids": [], "dept_codes": []}
    STAFF = {"id": 2, "role": "staff", "can_review": False,
             "is_banqt": False, "can_finance": False,
             "dept_ids": [], "dept_codes": []}

    def test_them_quan_he_can_quyen_duyet(self):
        with self.assertRaises(HTTPException) as ctx:
            api.document_relation_add(1, api.RelationIn(loai="thay_the",
                                                        so_hieu_dich="1/2020/NĐ-CP"),
                                      user=self.STAFF)
        self.assertEqual(ctx.exception.status_code, 403)

    def test_loai_quan_he_la_bi_chan_422(self):
        with self.assertRaises(HTTPException) as ctx:
            api.document_relation_add(1, api.RelationIn(loai="ban_be",
                                                        so_hieu_dich="1/2020/NĐ-CP"),
                                      user=self.REVIEWER)
        self.assertEqual(ctx.exception.status_code, 422)

    def test_thieu_ca_so_hieu_lan_ten_bi_chan_422(self):
        with self.assertRaises(HTTPException) as ctx:
            api.document_relation_add(1, api.RelationIn(loai="thay_the"),
                                      user=self.REVIEWER)
        self.assertEqual(ctx.exception.status_code, 422)

    def test_sua_meta_ngay_sai_dang_bi_chan_422(self):
        with self.assertRaises(HTTPException) as ctx:
            api.document_meta_put(1, api.VanBanMetaIn(ngay_ban_hanh="31/08/2026"),
                                  user=self.REVIEWER)
        self.assertEqual(ctx.exception.status_code, 422)

    def test_ngay_dung_khuon_nhung_khong_co_that_bi_chan_422(self):
        """'2024-02-31' khớp regex nhưng Postgres ném DatetimeFieldOverflow lúc
        UPDATE — người duyệt gõ nhầm phải nhận 422 tiếng Việt, không phải 500."""
        for xau in ("2024-02-31", "2024-13-01", "2024-00-10"):
            with self.subTest(ngay=xau):
                with self.assertRaises(HTTPException) as ctx:
                    api.document_meta_put(1, api.VanBanMetaIn(ngay_hieu_luc=xau),
                                          user=self.REVIEWER)
                self.assertEqual(ctx.exception.status_code, 422)


    def test_trang_thai_hieu_luc_la_bi_chan_422(self):
        with self.assertRaises(HTTPException) as ctx:
            api.document_meta_put(1, api.VanBanMetaIn(trang_thai_hieu_luc="chet_roi"),
                                  user=self.REVIEWER)
        self.assertEqual(ctx.exception.status_code, 422)

    def test_hop_le_thi_moi_cham_csdl(self):
        # Sentinel (bài học 28/08): update.sh chạy test trên máy chủ thật.
        sentinel = RuntimeError("cham toi CSDL")

        def chan(*a, **kw):
            raise sentinel

        goc = api.db.session
        api.db.session = chan
        try:
            with self.assertRaises(RuntimeError) as ctx:
                api.document_relation_add(
                    1, api.RelationIn(loai="thay_the", so_hieu_dich="1/2020/NĐ-CP"),
                    user=self.REVIEWER)
            self.assertIs(ctx.exception, sentinel)
            with self.assertRaises(RuntimeError) as ctx:
                api.document_detail(1, user=self.REVIEWER)
            self.assertIs(ctx.exception, sentinel)
        finally:
            api.db.session = goc


class QuanHeCheTenTests(unittest.TestCase):
    """Tài liệu đối ứng không mở được thì KHÔNG lộ gì qua bảng quan hệ.

    `ten_nguon`/`ten_dich` là chuỗi denormalize (van_ban.ten_day_du của chính
    tài liệu bị che) — che mỗi `title` mà để hai trường đó nguyên văn là mở
    đúng cửa vừa khoá: bản án ở mức 'client' mang tên đương sự trong trích yếu.
    """

    NGOAI_PHONG = {"id": 3, "role": "chuyen_vien", "can_review": False,
                   "is_banqt": False, "can_finance": False,
                   "dept_ids": [7], "dept_codes": ["KD"]}

    def _rel(self):
        return {
            "id": 1, "loai": "can_cu", "nguon": "auto", "ghi_chu": None,
            "so_hieu_nguon": "58/2023/HNG-ST",
            "ten_nguon": "Bản án V/v tranh chấp giữa ông Nguyễn Văn A và Công ty Z "
                         "số 58/2023/HNG-ST",
            "so_hieu_dich": "45/2019/QH14", "ten_dich": "Bộ luật Lao động",
            "doc": {"document_id": 42, "title": "Ban an 58-2023",
                    "trich_yeu": "V/v tranh chấp giữa ông Nguyễn Văn A",
                    "loai_van_ban": "Bản án", "trang_thai_hieu_luc": "chua_ro",
                    "doc_type": "ban_an", "access_level": "client",
                    "client_id": 5, "department_id": 9},
        }

    def test_khong_mo_duoc_thi_giau_ca_ten_va_so_hieu_va_id(self):
        ra = api._quan_he_hien_thi(self._rel(), self.NGOAI_PHONG,
                                   rules=[], chieu="nguoc")
        self.assertFalse(ra["can_open"])
        self.assertIsNone(ra["ten_nguon"], "tên đầy đủ của tài liệu bị che vẫn lọt")
        self.assertIsNone(ra["so_hieu_nguon"])
        self.assertIsNone(ra["document_id"])
        self.assertNotIn("Nguyễn Văn A", str(ra))

    def test_van_ban_ngoai_kho_van_hien_binh_thuong(self):
        """Văn bản luật chưa có trong kho chỉ là số hiệu + tên công khai."""
        rel = self._rel()
        rel["doc"] = None
        ra = api._quan_he_hien_thi(rel, self.NGOAI_PHONG, rules=[], chieu="xuoi")
        self.assertEqual("Bộ luật Lao động", ra["ten_dich"])
        self.assertEqual("45/2019/QH14", ra["so_hieu_dich"])


if __name__ == "__main__":
    unittest.main()
