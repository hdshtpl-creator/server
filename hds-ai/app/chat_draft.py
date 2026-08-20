"""chat_draft.py — Soạn tài liệu THEO MẪU ngay từ khung chat.

"tạo hợp đồng lao động cho Ngân như của Nhi" phải cho ra một BẢN NHÁP thật
(bảng document_drafts, tải được .docx) sinh từ đúng cấu trúc tài liệu mẫu của
Nhi cộng dữ liệu đã xác minh của Ngân — không phải một đoạn văn tả lại việc đó,
càng không phải câu "không tìm thấy trong tài liệu".

Nguyên tắc:
  · Nhận diện bằng cụm khuôn "tạo/soạn <loại giấy> cho <A> như/theo mẫu (của)
    <B>" — đủ chặt để câu hỏi tra cứu bình thường ("hợp đồng của SUNGROUP có
    điều khoản gì") không bị nuốt thành lệnh soạn thảo.
  · Nguồn (tài liệu mẫu của B + hồ sơ của A) được TÌM QUA PHIÊN CÓ RLS của
    chính người hỏi — không thấy nghĩa là không có quyền, tuyệt đối không mở
    bằng phiên admin rồi mới lọc.
  · Không tạo được thì nói RÕ thiếu gì và bổ sung ở đâu — có suy nghĩ, không
    im lặng, không bịa.
"""
from __future__ import annotations

import json
import re
import unicodedata

from app import db, drafting


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = s.replace("đ", "d").replace("Đ", "d")
    return re.sub(r"[\s_]+", " ", s).strip().lower()


# Loại giấy tờ nhận soạn từ chat. Cụm DÀI đứng trước để regex ưu tiên khớp
# "hợp đồng lao động" thay vì dừng ở "hợp đồng".
_KINDS = [
    ("hop dong lao dong", "hợp đồng lao động"),
    ("hdld", "hợp đồng lao động"),
    ("hop dong thu viec", "hợp đồng thử việc"),
    ("hop dong dich vu", "hợp đồng dịch vụ"),
    ("hop dong", "hợp đồng"),
    ("quyet dinh bo nhiem", "quyết định bổ nhiệm"),
    ("quyet dinh tuyen dung", "quyết định tuyển dụng"),
    ("quyet dinh", "quyết định"),
    ("thu tu van", "thư tư vấn"),
    ("bien ban", "biên bản"),
    ("giay uy quyen", "giấy ủy quyền"),
    ("don", "đơn"),
    ("thu", "thư"),
    ("van ban", "văn bản"),
]
_KIND_ALT = "|".join(k for k, _ in _KINDS)

# "tạo/soạn <loại> cho <A> như/giống/theo mẫu (của) <B>"
RE_DRAFT = re.compile(
    r"(?:^|\s)(?:tao|soan thao|soan|lam|viet)\s+"
    r"(?:giup toi\s+|giup\s+|ho toi\s+|ho\s+|mot\s+|ban\s+)*"
    rf"({_KIND_ALT})\s+(?:moi\s+)?"
    r"cho\s+(.{2,60}?)\s+"
    r"(?:nhu cua|giong cua|giong nhu cua|theo mau cua|dua tren mau cua|"
    r"nhu|giong nhu|giong|theo mau|dua tren)\s+"
    r"(?:cua\s+)?(.{2,60}?)\s*[?.!…]*\s*$"
)

# Đại từ/xưng hô đứng trước tên — bỏ đi để so khớp với tên file/sổ nhân sự.
_HONORIFICS = {"anh", "chi", "co", "ong", "ba", "em", "ban", "bac", "nhan vien"}


def _clean_name(raw: str) -> str:
    tokens = _fold(raw).split()
    while tokens and tokens[0] in _HONORIFICS:
        tokens = tokens[1:]
    return " ".join(tokens)


def detect_request(question: str):
    """Câu chat có phải lệnh soạn-theo-mẫu không. Trả dict hoặc None.

    Chỉ nhận khuôn đầy đủ "cho A ... như/theo mẫu B": thiếu vế mẫu thì đây là
    việc của tab Soạn tài liệu với mẫu chuẩn, không đoán bừa từ chat.
    """
    m = RE_DRAFT.search(_fold(question))
    if not m:
        return None
    kind_key = m.group(1)
    for_name = _clean_name(m.group(2))
    like_name = _clean_name(m.group(3))
    if not for_name or not like_name or for_name == like_name:
        return None
    kind_label = dict(_KINDS).get(kind_key, kind_key)
    return {"kind": kind_key, "kind_label": kind_label,
            "for_name": for_name, "like_name": like_name}


def _kind_match(folded_title: str, kind: str) -> bool:
    """Tiêu đề tài liệu có đúng LOẠI giấy đang cần không."""
    if kind in ("hop dong lao dong", "hdld"):
        return ("hdld" in folded_title
                or ("hop dong" in folded_title and "lao dong" in folded_title))
    return all(tok in folded_title for tok in kind.split())


def _name_match(folded_title: str, name: str) -> bool:
    return all(tok in folded_title for tok in name.split())


def pick_sources(docs, kind: str, for_name: str, like_name: str):
    """Chọn (tài liệu mẫu của B, các hồ sơ của A) từ danh sách (id, title, doc_type).

    Tách thuần để test không cần CSDL. `docs` là những gì NGƯỜI HỎI được thấy
    (đã qua RLS) — hàm này chỉ chọn, không mở rộng quyền.
    """
    template_doc = None
    fallback_doc = None
    person_docs = []
    for doc_id, title, doc_type in docs:
        t = _fold(title)
        if _name_match(t, like_name):
            if _kind_match(t, kind):
                template_doc = template_doc or (doc_id, title)
            elif doc_type == "ho_so_ns":
                fallback_doc = fallback_doc or (doc_id, title)
        if _name_match(t, for_name) and doc_type == "ho_so_ns":
            person_docs.append((doc_id, title))
    # Hồ sơ định danh xếp trước (CCCD/sơ yếu/CV) để bằng chứng ưu tiên đúng chỗ.
    priority = ("cccd", "can cuoc", "so yeu", "ly lich", "cv", "hdld", "hop dong")
    person_docs.sort(key=lambda item: min(
        (i for i, key in enumerate(priority) if key in _fold(item[1])),
        default=len(priority)))
    return template_doc or fallback_doc, template_doc is None, person_docs[:4]


def _visible_documents(dept_ids, is_banqt, can_finance):
    with db.session(role="internal", dept_ids=dept_ids, is_banqt=is_banqt,
                    can_finance=can_finance) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT id, title, coalesce(doc_type,'other')
                             FROM documents
                            WHERE approved AND label_verified AND coalesce(active,true)
                            ORDER BY updated_at DESC LIMIT 500""")
            return cur.fetchall()


def _employee_info(for_name: str):
    """Dòng sổ nhân sự khớp tên — dữ liệu ĐÃ XÁC MINH để điền vào bản nháp."""
    try:
        with db.session(role="internal") as conn:
            with conn.cursor() as cur:
                cur.execute("""SELECT e.full_name, e.employee_code, e.title, d.name
                                 FROM employees e
                                 LEFT JOIN departments d ON d.id=e.department_id
                                WHERE e.active LIMIT 200""")
                rows = cur.fetchall()
    except Exception:
        return None
    for full_name, code, title, dept in rows:
        if _name_match(_fold(full_name or ""), for_name):
            return {"ho_ten": full_name, "ma_nhan_vien": code,
                    "chuc_danh": title, "phong_ban": dept}
    return None


def _missing_answer(req) -> dict:
    """Không có mẫu để bám — nói rõ thiếu gì, bổ sung ở đâu. Không đoán."""
    like = req["like_name"].title()
    answer = (
        f"Mình chưa tạo bản nháp được: **trong kho chưa có {req['kind_label']} "
        f"nào của {like}** để làm mẫu.\n\n"
        f"Bạn có thể:\n"
        f"- Thả file {req['kind_label']} của {like} vào thư mục "
        f"`8. HỒ SƠ NHÂN SỰ/{like}/` trên Drive rồi chờ đồng bộ (≤15 phút), hoặc\n"
        f"- Mở tab **Soạn tài liệu** để soạn từ mẫu chuẩn của HDS mà không cần "
        f"bản của {like}."
    )
    return {"answer": answer, "answer_mode": "structured",
            "grounding_status": "verified",
            "evidence": [], "state": {}}


def handle(question, req, *, user_id, dept_ids=None, is_banqt=False,
           can_finance=False) -> dict:
    """Tạo bản nháp thật rồi trả lời chat bằng kết quả — hoặc nói rõ vì sao chưa.

    Trả dict cùng dạng với structured_answer để rag.prepare dùng làm câu trả
    lời trực tiếp (cả hai đường thường và stream cùng hưởng, lịch sử tự lưu).
    """
    from app import draft_api  # import muộn để tránh vòng rag ↔ draft_api

    docs = _visible_documents(dept_ids, is_banqt, can_finance)
    template_doc, is_fallback, person_docs = pick_sources(
        docs, req["kind"], req["for_name"], req["like_name"])
    if not template_doc:
        return _missing_answer(req)

    for_display = req["for_name"].title()
    employee = _employee_info(req["for_name"])
    if employee and employee.get("ho_ten"):
        for_display = employee["ho_ten"]

    title = f"{req['kind_label'].capitalize()} — {for_display} (theo mẫu {template_doc[1]})"
    source_ids = [template_doc[0]] + [doc_id for doc_id, _ in person_docs]
    input_data = {"soan_cho": for_display, "theo_mau_cua": req["like_name"].title()}
    if employee:
        input_data.update({k: v for k, v in employee.items() if v})
    instructions = (
        f"Soạn {req['kind_label']} cho {for_display}, bám NGUYÊN cấu trúc, thứ tự "
        f"điều khoản và văn phong của tài liệu mẫu ({template_doc[1]}). Thay toàn bộ "
        f"thông tin cá nhân của người trong mẫu bằng dữ liệu đã xác minh của "
        f"{for_display} lấy từ DỮ LIỆU ĐÃ XÁC MINH và các nguồn hồ sơ đính kèm. "
        f"Thông tin nào của {for_display} không có trong nguồn (số CCCD, địa chỉ, "
        f"mức lương, ngày ký…) thì ghi [CẦN BỔ SUNG: …] — tuyệt đối không lấy "
        f"số liệu của người trong mẫu điền sang."
    )

    user = {"id": user_id}
    with db.session(role="internal", admin=True) as conn:
        template = draft_api._template(conn, None)
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO document_drafts
                     (title,document_type,template_id,instructions,input_data,created_by)
                     VALUES (%s,%s,%s,%s,%s,%s) RETURNING id, coalesce(current_version,0)""",
                (title[:200], "contract", template["id"], instructions,
                 json.dumps(input_data, ensure_ascii=False), user_id),
            )
            draft_id, current_version = cur.fetchone()
        db.audit(conn, user_id, "create_draft", "document_drafts", draft_id,
                 {"from": "chat", "source_document_ids": source_ids})
        evidence = drafting.retrieve_evidence(conn, source_ids, f"{title} {question}")

    result = drafting.generate_content(
        title=title, instructions=instructions, input_data=input_data,
        body_template=template["body_template"],
        template_instructions=template["system_instructions"],
        evidence=evidence, missing_fields=None, model=None,
    )
    version_no = draft_api._save_version(
        user, {"id": draft_id, "current_version": current_version}, result,
        source_ids, instructions, input_data, "Tạo từ khung chat")

    placeholders = result.get("placeholder_count") or 0
    lines = [
        f"Đã tạo bản nháp **{title}** (phiên bản {version_no}).",
        f"- Mẫu áp dụng: **{template_doc[1]}**"
        + (" *(hồ sơ gần nhất tìm được — kho chưa có đúng loại này của "
           f"{req['like_name'].title()})*" if is_fallback else ""),
    ]
    if employee:
        detail = ", ".join(f"{k.replace('_', ' ')}: {v}"
                           for k, v in employee.items() if v)
        lines.append(f"- Dữ liệu đã xác minh từ sổ nhân sự: {detail}")
    if person_docs:
        lines.append("- Hồ sơ nguồn của " + for_display + ": "
                     + ", ".join(t for _, t in person_docs))
    else:
        lines.append(f"- ⚠ Chưa có hồ sơ nào của {for_display} trong kho — các "
                     "trường cá nhân sẽ ở dạng [CẦN BỔ SUNG].")
    if placeholders:
        lines.append(f"- Còn **{placeholders} chỗ [CẦN BỔ SUNG]** cần bạn điền/kiểm.")
    if result.get("grounding_status") != "grounded":
        lines.append("- Bản nháp cần người rà lại trước khi dùng (chưa đủ căn cứ "
                     "cho mọi đoạn).")
    lines.append(f"\n👉 Mở tab **Soạn tài liệu** → “{title}” để rà, sửa và bấm "
                 f"**Tải DOCX**. (API: `GET /api/drafts/{draft_id}/export?format=docx`)")

    evid = [{
        "kind": "system", "title": "Bản nháp soạn thảo",
        "source_locator": f"document_drafts#{draft_id}",
        "quote": f"template={template_doc[1]}; nguồn={len(source_ids)}; "
                 f"placeholder={placeholders}",
        "as_of": None,
    }]
    return {"answer": "\n".join(lines), "answer_mode": "structured",
            "grounding_status": "verified", "evidence": evid,
            "state": {}, "draft_id": draft_id}
