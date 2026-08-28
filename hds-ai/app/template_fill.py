"""
template_fill.py — Thay thông tin CHỦ THỂ vào file mẫu .docx, GIỮ NGUYÊN file gốc.

Khác hẳn tab Soạn tài liệu (drafting.py sinh lại .docx từ Markdown, mất định
dạng): ở đây file mẫu gốc trong kho được mở bằng python-docx và chỉ những chuỗi
định danh chủ thể (tên, địa chỉ, MST, CCCD, SĐT…) bị thay — font, bảng, đánh số
điều khoản của HDS còn nguyên. Yêu cầu chủ dự án 26/08/2026: "ai tự thay chủ thể
vào file mẫu sao cho khớp, cần chính xác hơn thì đặt placeholder cơ bản".

Hai tầng thay thế, tầng nào chắc hơn chạy trước:
  1. Placeholder {{ten_ben_a}} đặt sẵn trong file mẫu — thay trực tiếp, không
     cần model đoán vị trí. Đây là đường CHÍNH XÁC NHẤT, nên khuyến khích.
  2. Không có placeholder: model đọc văn bản mẫu + thông tin chủ thể mới rồi trả
     về bảng "chuỗi cũ → chuỗi mới". Chuỗi cũ phải CHÉP NGUYÊN VĂN từ mẫu; chuỗi
     nào không tìm thấy đúng từng ký tự thì KHÔNG thay và báo lại người dùng —
     thà bắt người dùng sửa tay một chỗ còn hơn thay nhầm giữa hợp đồng.

Mọi lượt thay đều trả về bảng đối chiếu để luật sư kiểm tra — chính xác đặt
trên nhanh (yêu cầu 26/08/2026).
"""
import json
import os
import re
import time
import unicodedata
import uuid
from pathlib import Path

# An toàn import: rag nạp module này TRỄ (trong prepare), nên tới lúc chạy thì
# app.rag đã nạp xong — không tạo vòng import. Đừng đưa template_fill vào import
# đầu file của rag.py.
from app import autofill, db, settings

PLACEHOLDER_RE = re.compile(r"\{\{\s*([^{}\n]{1,60}?)\s*\}\}")

# Chuỗi cũ quá ngắn ("A", "01") xuất hiện khắp văn bản — thay là nát file.
MIN_OLD_CHARS = 2
# Một chuỗi định danh thật (tên công ty, số giấy tờ) hiếm khi lặp quá mức này;
# lặp nhiều hơn nghĩa là model đưa nhầm một từ phổ thông — bỏ, báo người dùng.
MAX_HITS_PER_OLD = 50
MAX_REPLACEMENTS = 60
MAX_NEW_CHARS = 500

# Trần ký tự đưa vào prompt. Mẫu hợp đồng HDS vài trang ~ 10-20k ký tự; hồ sơ
# đính kèm chỉ cần phần đầu (thông tin chủ thể nằm ở trang đầu giấy tờ).
MAX_TEMPLATE_PROMPT_CHARS = 24_000
MAX_PARTY_PROMPT_CHARS = 10_000

DATA_RAW = Path(os.getenv("DATA_RAW", "./data/raw"))
DATA_WORK = Path(os.getenv("DATA_WORK", "./data/work"))
FILL_KEEP_HOURS = 24
FILL_TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")


# ---------------------------------------------------------------------------
# Đọc / ghi docx — mọi thao tác giữ nguyên run để không phá định dạng
# ---------------------------------------------------------------------------
def _iter_container_paragraphs(container):
    """Paragraph của một khối (body/cell/header) KÈM mọi bảng lồng bên trong."""
    for p in container.paragraphs:
        yield p
    for table in container.tables:
        for row in table.rows:
            for cell in row.cells:
                yield from _iter_container_paragraphs(cell)


def iter_all_paragraphs(doc):
    """Mọi paragraph của tài liệu: thân bài, bảng, header/footer từng section.

    Thiếu header/footer là thiếu đúng chỗ hay ghi tên công ty nhất.
    """
    yield from _iter_container_paragraphs(doc)
    for section in doc.sections:
        for part in (section.header, section.footer,
                     section.first_page_header, section.first_page_footer,
                     section.even_page_header, section.even_page_footer):
            if part is not None:
                yield from _iter_container_paragraphs(part)


def paragraph_text(par) -> str:
    return "".join(run.text for run in par.runs)


def document_text(doc) -> str:
    return "\n".join(paragraph_text(p) for p in iter_all_paragraphs(doc))


def replace_in_paragraph(par, old: str, new: str) -> int:
    """Thay `old` → `new` trong một paragraph, chịu được chữ bị Word xé nhỏ.

    Word tách một cụm từ thành nhiều run (sửa lỗi chính tả, đổi font giữa
    chừng…), nên chuỗi nhìn thấy trên màn hình thường KHÔNG tồn tại nguyên vẹn
    trong bất kỳ run nào. Cách làm: ghép text mọi run để tìm vị trí khớp, rồi
    đặt chuỗi mới vào run ĐẦU TIÊN dính vùng khớp (giữ định dạng của run đó),
    các run còn lại trong vùng bị cắt phần trùng.

    Tìm tiếp từ SAU chuỗi vừa thay — nhờ vậy `new` chứa `old` ("Công ty ABC" →
    "Công ty ABC — chi nhánh 2") không gây lặp vô hạn.
    """
    count = 0
    search_from = 0
    while count < MAX_HITS_PER_OLD:
        runs = par.runs
        full = "".join(r.text for r in runs)
        idx = full.find(old, search_from)
        if idx < 0:
            return count
        end = idx + len(old)
        pos = 0
        replaced = False
        for run in runs:
            r_start, r_end = pos, pos + len(run.text)
            pos = r_end
            if r_end <= idx or r_start >= end:
                continue
            keep_head = run.text[:max(0, idx - r_start)]
            keep_tail = run.text[end - r_start:] if r_end > end else ""
            if not replaced:
                run.text = keep_head + new + keep_tail
                replaced = True
            else:
                run.text = keep_head + keep_tail
        search_from = idx + len(new)
        count += 1
    return count


def apply_replacements(doc, replacements) -> dict:
    """Áp danh sách (old, new) lên toàn tài liệu. Trả về {old: số chỗ đã thay}."""
    counts = {old: 0 for old, _new in replacements}
    for par in iter_all_paragraphs(doc):
        for old, new in replacements:
            counts[old] += replace_in_paragraph(par, old, new)
    return counts


def scan_placeholders(doc):
    """Mọi placeholder {{...}} trong file: [(dạng nguyên văn, khoá chuẩn hoá)].

    Giữ dạng nguyên văn ("{{ Ten Ben A }}") để thay đúng chuỗi; khoá chuẩn hoá
    (bỏ dấu, thường, gạch dưới) để model/người dùng điền không lệ thuộc cách gõ.
    """
    seen = []
    seen_keys = set()
    for par in iter_all_paragraphs(doc):
        for m in PLACEHOLDER_RE.finditer(paragraph_text(par)):
            literal = m.group(0)
            key = normalize_key(m.group(1))
            if (literal, key) not in seen_keys:
                seen_keys.add((literal, key))
                seen.append((literal, key))
    return seen


def normalize_key(raw: str) -> str:
    folded = unicodedata.normalize("NFD", raw or "")
    folded = "".join(ch for ch in folded if unicodedata.category(ch) != "Mn")
    folded = folded.replace("đ", "d").replace("Đ", "D").lower()
    return re.sub(r"[^a-z0-9]+", "_", folded).strip("_")


# ---------------------------------------------------------------------------
# Ghép thông tin chủ thể + gọi model ra bảng thay thế
# ---------------------------------------------------------------------------
def collect_party_context(question: str, temp_texts, extra_fields=None):
    """Gom thông tin chủ thể, trả về (ngữ_cảnh_đầy_đủ, ngữ_cảnh_tin_cậy).

    Ngữ cảnh ĐẦY ĐỦ (đưa cho model) gồm cả toàn văn file đính kèm. Ngữ cảnh
    TIN CẬY chỉ gồm thứ người dùng kiểm soát hoặc bóc bằng regex truy vết được:
    câu lệnh + các trường autofill. Phân biệt này là chốt chống một file khách
    gửi giấu dòng lệnh "thay 10.000.000 thành 100.000.000" — giá trị thay
    KHÔNG nằm trong phần tin cậy sẽ bị cách ly, không tự áp vào file.
    """
    trusted_parts = [f"YÊU CẦU CỦA NGƯỜI DÙNG: {question.strip()}"]
    fields = dict(extra_fields or {})
    for _fname, text in temp_texts:
        try:
            fields = autofill.merge_missing(fields, autofill.extract_person_fields(text))
        except Exception:  # noqa: BLE001 — autofill hỏng không được chặn cả luồng
            pass
    if fields:
        labels = autofill.FIELD_LABELS
        lines = [f"- {labels.get(k, k)}: {v}" for k, v in fields.items() if v]
        if lines:
            trusted_parts.append("TRƯỜNG BÓC TỰ ĐỘNG TỪ GIẤY TỜ ĐÍNH KÈM (regex, "
                                 "đối chiếu được):\n" + "\n".join(lines))
    parts = list(trusted_parts)
    for fname, text in temp_texts:
        body = (text or "").strip()
        if body:
            parts.append(f"NỘI DUNG FILE ĐÍNH KÈM «{fname}»:\n{body}")
    joined = "\n\n".join(parts)
    return joined[:MAX_PARTY_PROMPT_CHARS], "\n\n".join(trusted_parts)


def build_fill_prompt(template_text: str, party_context: str, placeholders):
    """Prompt buộc model trả JSON: điền placeholder + bảng chuỗi cũ → mới."""
    ph_lines = ""
    if placeholders:
        ph_lines = ("\nFILE MẪU CÓ CÁC CHỖ TRỐNG ĐẶT SẴN (ưu tiên điền vào "
                    "đây):\n" + "\n".join(f"- {lit}" for lit, _k in placeholders))
    system = (
        "Bạn là công cụ điền thông tin chủ thể vào văn bản mẫu của công ty "
        "luật. Bạn chỉ trả về DUY NHẤT một khối JSON, không giải thích gì "
        "thêm bên ngoài JSON."
    )
    prompt = (
        "VĂN BẢN MẪU (trích nguyên văn từ file .docx):\n"
        "-----\n"
        f"{template_text[:MAX_TEMPLATE_PROMPT_CHARS]}\n"
        "-----\n"
        f"{ph_lines}\n"
        "THÔNG TIN CHỦ THỂ MỚI:\n"
        "-----\n"
        f"{party_context}\n"
        "-----\n\n"
        "Nhiệm vụ: xác định những chuỗi trong VĂN BẢN MẪU là thông tin định "
        "danh chủ thể (tên công ty/cá nhân, mã số thuế, số CCCD/hộ chiếu, địa "
        "chỉ, số điện thoại, email, người đại diện, chức vụ, số tài khoản, "
        "ngày ký) và cần thay bằng thông tin chủ thể mới ở trên.\n"
        "Trả về JSON đúng khung sau:\n"
        "{\n"
        '  "placeholders": {"khoa_cho_trong": "giá trị điền"},\n'
        '  "replacements": [{"old": "chuỗi chép NGUYÊN VĂN từ văn bản mẫu", '
        '"new": "chuỗi thay vào"}],\n'
        '  "ghi_chu": "thông tin còn thiếu hoặc chỗ người dùng cần tự kiểm tra"\n'
        "}\n"
        "Quy tắc bắt buộc:\n"
        "- \"old\" phải chép ĐÚNG TỪNG KÝ TỰ (kể cả dấu, khoảng trắng) một "
        "chuỗi có mặt trong VĂN BẢN MẪU; không tự chế.\n"
        "- Chỉ thay thông tin định danh chủ thể. TUYỆT ĐỐI không sửa nội dung "
        "điều khoản, nghĩa vụ, giá trị pháp lý.\n"
        "- Thông tin mới không có trong dữ liệu thì BỎ QUA chỗ đó và ghi vào "
        "\"ghi_chu\"; không bịa số liệu.\n"
        "- \"placeholders\" chỉ điền cho các chỗ trống liệt kê ở trên (nếu có).\n"
    )
    return prompt, system


def parse_llm_json(text: str) -> dict:
    """Bóc khối JSON từ câu trả lời của model, chịu được ```json và <think>."""
    body = re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL)
    body = re.sub(r"```(?:json)?", "", body).strip()
    start = body.find("{")
    if start < 0:
        raise ValueError("Không thấy JSON trong câu trả lời của model")
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(body)):
        ch = body[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(body[start:i + 1])
    raise ValueError("JSON trong câu trả lời của model không đóng ngoặc")


def sanitize_replacements(raw, template_text: str, trusted_text: str | None = None):
    """Lọc bảng thay thế của model trước khi đụng vào file.

    Trả về (đạt: [(old, new)], loại: [(old, lý do)]). Nguyên tắc: nghi ngờ thì
    LOẠI và báo — một chỗ thay nhầm trong hợp đồng đắt hơn nhiều lần một chỗ
    người dùng phải tự sửa.

    trusted_text (nếu có) là chốt chống chèn lệnh qua file đính kèm: giá trị
    MỚI phải xuất hiện trong phần tin cậy (câu lệnh của người dùng + trường
    autofill), nếu không thì cách ly — model chỉ được LẤY dữ liệu từ hồ sơ,
    không được NGHE lệnh từ hồ sơ.
    """
    ok, dropped = [], []
    seen = set()
    trusted_fold = _fold_for_match(trusted_text) if trusted_text is not None else None
    for item in (raw or [])[:MAX_REPLACEMENTS]:
        if not isinstance(item, dict):
            continue
        old = str(item.get("old") or "")
        new = str(item.get("new") or "").strip()
        if not old.strip() or old in seen:
            continue
        seen.add(old)
        if len(old.strip()) < MIN_OLD_CHARS:
            dropped.append((old, "chuỗi quá ngắn, thay là hỏng cả file"))
            continue
        if not new or new == old:
            dropped.append((old, "không có giá trị mới"))
            continue
        if len(new) > MAX_NEW_CHARS:
            dropped.append((old, "giá trị mới dài bất thường"))
            continue
        hits = template_text.count(old)
        if hits == 0:
            dropped.append((old, "không tìm thấy nguyên văn trong file mẫu"))
            continue
        if hits > MAX_HITS_PER_OLD:
            dropped.append((old, f"lặp {hits} lần — nghi là từ phổ thông, không thay"))
            continue
        if trusted_fold is not None and _fold_for_match(new) not in trusted_fold:
            dropped.append((old, f"giá trị mới «{new}» không có trong câu lệnh/"
                                 "trường đã bóc — muốn thay, gõ giá trị đó trực "
                                 "tiếp vào câu lệnh rồi tạo lại"))
            continue
        ok.append((old, new))
    return ok, dropped


def _fold_for_match(text: str) -> str:
    """So khớp giá-trị-mới với phần tin cậy: bỏ khác biệt khoảng trắng/hoa
    thường để "NGUYỄN THỊ MAI" trong CCCD khớp "Nguyễn Thị Mai" trong câu lệnh."""
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


# ---------------------------------------------------------------------------
# Lưu file kết quả + dọn dẹp
# ---------------------------------------------------------------------------
def fills_dir() -> Path:
    return DATA_WORK / "template_fills"


def cleanup_old_fills(now: float | None = None):
    """File điền xong là hàng tạm — quá FILL_KEEP_HOURS giờ thì dọn."""
    root = fills_dir()
    if not root.exists():
        return
    cutoff = (now or time.time()) - FILL_KEEP_HOURS * 3600
    for child in root.iterdir():
        try:
            if child.is_dir() and child.stat().st_mtime < cutoff:
                for f in child.iterdir():
                    f.unlink(missing_ok=True)
                child.rmdir()
        except OSError:
            continue


def save_filled(doc, filename: str) -> tuple[str, Path]:
    from app.drafting import safe_export_name
    token = uuid.uuid4().hex
    out_dir = fills_dir() / token
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / safe_export_name(filename, "docx")
    doc.save(str(out))
    return token, out


def save_filled_bytes(payload: bytes, filename: str) -> tuple[str, Path]:
    """Như save_filled nhưng nhận sẵn bytes .docx — cho file soạn mới bằng
    drafting.render_docx (luồng tạo bộ file)."""
    from app.drafting import safe_export_name
    token = uuid.uuid4().hex
    out_dir = fills_dir() / token
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / safe_export_name(filename, "docx")
    out.write_bytes(payload)
    return token, out


def find_fill_file(token: str) -> Path | None:
    """Tìm file .docx theo token — dùng cho endpoint tải về."""
    if not FILL_TOKEN_RE.match(token or ""):
        return None
    out_dir = (fills_dir() / token)
    try:
        resolved_dir = out_dir.resolve(strict=True)
        resolved_dir.relative_to(fills_dir().resolve())
    except (FileNotFoundError, ValueError, OSError):
        return None
    for f in sorted(resolved_dir.iterdir()):
        if f.suffix.lower() == ".docx" and f.is_file():
            return f
    return None


# ---------------------------------------------------------------------------
# Luồng chính — gọi từ rag.prepare khi người dùng bấm "Tạo file mẫu"
# ---------------------------------------------------------------------------
def _template_row(template_doc_id: int, dept_ids, is_banqt, can_finance,
                  role_level=None, dept_codes=None):
    """Đọc bản ghi file mẫu qua RLS CỦA CHÍNH NGƯỜI HỎI (nguyên tắc chat_draft:
    không mở admin=True cho việc chọn tài liệu). Chỉ nhận kệ mẫu.

    RLS documents cho vai internal là USING(true) nên MỘT MÌNH nó không chặn
    gì — phải đối chiếu thêm ma trận access_rules qua rag.can_open_doc, đúng
    chốt mà /files/{id}/download và /preview đang dùng. Thiếu bước này, trợ lý
    bị 403 khi tải mẫu vẫn rút được nguyên văn file qua đường điền mẫu (lỗ
    phát hiện khi rà soát 26/08/2026).
    """
    with db.session(role="internal", dept_ids=dept_ids, is_banqt=is_banqt,
                    can_finance=can_finance) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, title, doc_type, source_path,
                          access_level, department_id, client_id
                     FROM documents
                    WHERE id=%s AND doc_type IN ('mau_hd','thu_mau')
                      AND approved AND label_verified AND coalesce(active,true)""",
                (template_doc_id,))
            row = cur.fetchone()
    if not row:
        return None
    from app import rag  # nạp trễ — rag nạp module này trễ, tránh vòng import
    doc = {"access_level": row[4], "department_id": row[5], "doc_type": row[2],
           "client_id": row[6], "title": row[1]}
    if not rag.can_open_doc(role_level, dept_ids, is_banqt, doc,
                            can_finance=can_finance,
                            rules=rag.load_access_rules(),
                            dept_codes=dept_codes):
        return None
    return row[:4]


def _temp_texts(conversation_id):
    """Toàn văn các file 'dùng xong bỏ' của hội thoại — quyền sở hữu hội thoại
    đã được api.check_conversation xác nhận trước khi vào đây."""
    if not conversation_id:
        return []
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT filename, content FROM temp_files
                            WHERE conversation_id=%s AND expires_at > now()
                            ORDER BY id""", (conversation_id,))
            return [(r[0], r[1]) for r in cur.fetchall()]


def _load_docx(source_path: str):
    """Mở file mẫu gốc trong rào thư mục dữ liệu — cùng luật với
    /files/{id}/download (dùng chung local_learn.allowed_roots)."""
    import docx
    from app.local_learn import allowed_roots
    path = Path(source_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    resolved = path.resolve(strict=True)
    for root in allowed_roots():
        try:
            resolved.relative_to(root)
            break
        except ValueError:
            continue
    else:
        raise ValueError("ngoai_thu_muc_du_lieu")
    if resolved.suffix.lower() != ".docx":
        raise ValueError("khong_phai_docx")
    return docx.Document(str(resolved)), resolved


def handle(question, template_doc_id, *, user_id, dept_ids=None, is_banqt=False,
           can_finance=False, conversation_id=None, model=None, on_status=None,
           role_level=None, dept_codes=None, use_temp=True):
    """Điền chủ thể vào file mẫu, trả về dict kiểu direct-answer cho rag.prepare.

    Mọi lỗi dự kiến trả về câu trả lời hướng dẫn (không raise) — chat không
    được sập vì một file mẫu thiếu.
    """
    def note(label):
        if on_status:
            try:
                on_status(label)
            except Exception:  # noqa: BLE001 — tiến trình chỉ để hiển thị
                pass

    def _fail(answer_md):
        return {"answer": answer_md, "answer_mode": "structured",
                "grounding_status": "not_applicable", "evidence": [], "state": {}}

    note("Đang mở file mẫu…")
    row = _template_row(template_doc_id, dept_ids, is_banqt, can_finance,
                        role_level=role_level, dept_codes=dept_codes)
    if not row:
        return _fail("Mình không thấy file mẫu này trong kệ **HỢP ĐỒNG MẪU / "
                     "THƯ MẪU - BIỂU MẪU** (hoặc tài khoản của bạn chưa được "
                     "xem). Chọn lại mẫu trong danh sách bên dưới khung chat nhé.")
    doc_id, title, _doc_type, source_path = row
    if not source_path:
        return _fail(f"File mẫu **{title}** không có tệp gốc trên máy chủ "
                     "(tài liệu nạp từ hội thoại). Hãy đưa file .docx mẫu vào "
                     "thư mục HỢP ĐỒNG MẪU trong kho tài liệu rồi chờ quét (≤15 phút).")
    try:
        doc, resolved = _load_docx(source_path)
    except ValueError:
        return _fail(f"File mẫu **{title}** không phải định dạng .docx nên chưa "
                     "thay tự động được (bản .doc/.pdf dễ vỡ định dạng khi sửa "
                     "máy). Bạn lưu lại thành .docx rồi đưa vào kho tài liệu giúp mình.")
    except (FileNotFoundError, OSError):
        return _fail(f"Tệp gốc của mẫu **{title}** không còn trên máy chủ. "
                     "Chờ lượt quét kho kế tiếp hoặc báo quản trị viên.")

    template_text = document_text(doc)
    placeholders = scan_placeholders(doc)

    note("Đang đọc hồ sơ đính kèm và bóc thông tin chủ thể…")
    # Tôn trọng công tắc file đính kèm của giao diện: người dùng đã gỡ hết
    # chip thì use_temp=False và KHÔNG đọc file tạm còn trên máy chủ.
    temp_texts = _temp_texts(conversation_id) if use_temp else []
    party_context, trusted_text = collect_party_context(question, temp_texts)

    note("Đang xác định các chỗ cần thay trong mẫu…")
    from app import models
    prompt, system = build_fill_prompt(template_text, party_context, placeholders)
    chosen_model = (model or "").strip() or models.effective_llm_model()
    raw_answer, _latency = models.llm(prompt, system=system, temperature=0.0,
                                      model=chosen_model)
    try:
        payload = parse_llm_json(raw_answer)
    except (ValueError, json.JSONDecodeError):
        return _fail("Model chưa trả về được bảng thay thế hợp lệ cho mẫu này. "
                     "Bạn thử lại, hoặc mô tả rõ hơn thông tin chủ thể "
                     "(tên, MST, địa chỉ…) ngay trong câu lệnh.")

    note("Đang thay vào file và kiểm tra lại từng chỗ…")
    # Tầng 1 — placeholder đặt sẵn: đường chính xác nhất.
    ph_values = payload.get("placeholders") or {}
    ph_pairs, ph_missing = [], []
    for literal, key in placeholders:
        value = None
        for k, v in ph_values.items():
            if normalize_key(str(k)) == key and str(v).strip():
                value = str(v).strip()
                break
        if value:
            ph_pairs.append((literal, value))
        else:
            ph_missing.append(literal)

    # Tầng 2 — bảng chuỗi cũ → mới, đã qua bộ lọc an toàn. trusted_text chặn
    # giá trị mới không do người dùng đưa ra (chống chèn lệnh qua file khách).
    replacements, dropped = sanitize_replacements(
        payload.get("replacements"), template_text, trusted_text)

    counts = apply_replacements(doc, ph_pairs + replacements)
    not_found = [(old, new) for old, new in replacements if counts.get(old, 0) == 0]

    cleanup_old_fills()
    token, out_path = save_filled(doc, f"{title} - da dien")

    # ---- Câu trả lời: bảng đối chiếu để luật sư kiểm tra ----
    lines = [f"Đã tạo file từ mẫu **{title}** (giữ nguyên định dạng gốc)."]
    done_lines = []
    for literal, value in ph_pairs:
        if counts.get(literal, 0):
            done_lines.append(f"- Chỗ trống `{literal}` → **{value}** "
                              f"({counts[literal]} chỗ)")
    for old, new in replacements:
        n = counts.get(old, 0)
        if n:
            done_lines.append(f"- «{old}» → **{new}** ({n} chỗ)")
    if done_lines:
        lines.append("\n**Đã thay:**")
        lines.extend(done_lines)
    else:
        lines.append("\n**Chưa thay được chỗ nào** — thông tin chủ thể chưa đủ "
                     "hoặc mẫu không có chuỗi khớp. File tải về là bản gốc.")

    warn_lines = []
    for literal in ph_missing:
        warn_lines.append(f"- Chỗ trống `{literal}`: chưa có dữ liệu để điền")
    for old, _new in not_found:
        warn_lines.append(f"- «{old}»: không còn tìm thấy nguyên văn trong file")
    for old, reason in dropped:
        warn_lines.append(f"- «{old}»: {reason}")
    ghi_chu = str(payload.get("ghi_chu") or "").strip()
    if ghi_chu:
        warn_lines.append(f"- Ghi chú của hệ thống: {ghi_chu}")
    if warn_lines:
        lines.append("\n**Cần bạn kiểm tra / bổ sung tay:**")
        lines.extend(warn_lines)

    lines.append("\nBấm nút **Tải file đã điền** ngay dưới tin nhắn này. "
                 "Vui lòng RÀ LẠI TOÀN BỘ văn bản trước khi sử dụng — đối chiếu "
                 "từng dòng trong bảng trên và đọc lại các điều khoản, con số; "
                 "bản điền tự động không thay được trách nhiệm soát của luật sư.")

    evidence = [{
        "kind": "system",
        "title": f"File đã điền từ mẫu: {title}",
        "source_locator": f"template_fill#{token}",
        "quote": out_path.name,
        "as_of": None,
    }]
    with db.session(role="internal", admin=True) as conn:
        db.audit(conn, user_id, "template_fill", "documents", doc_id,
                 {"token": token, "replacements": len(replacements),
                  "placeholders": len(ph_pairs), "not_found": len(not_found)})
    return {"answer": "\n".join(lines), "answer_mode": "structured",
            "grounding_status": "verified", "evidence": evidence,
            "state": {}, "fill_token": token}
