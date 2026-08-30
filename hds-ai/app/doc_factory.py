"""
doc_factory.py — "Tạo BỘ file" từ khung chat: AI đọc hồ sơ đính kèm, tự lên
danh sách văn bản cần soạn (biên bản nghiệm thu, giấy đề nghị thanh toán từng
đợt…) rồi tạo TỪNG file .docx — yêu cầu chủ dự án 26/08/2026, mô phỏng luồng
"gửi hợp đồng đợt 1, nhờ làm đợt 2-3 + nghiệm thu" trên Claude/ChatGPT.

Khác luồng "Tạo file mẫu" (template_fill — điền chủ thể vào ĐÚNG một mẫu,
chính xác tối đa): ở đây model được chủ động hơn — quyết định số file, chọn
khuôn cho từng file (mẫu kho đã chọn, file .docx đã tải lên, hoặc soạn mới),
và LẤY DỮ LIỆU TỪ CHÍNH HỒ SƠ ĐÍNH KÈM (số hợp đồng, số tài khoản, các đợt
thanh toán…). Đổi lại, câu trả lời BẮT BUỘC có mục "CHỖ AI TỰ QUYẾT ĐỊNH —
KIỂM TRA BẮT BUỘC" liệt kê mọi suy đoán, và lời nhắc rà soát toàn văn — vì
văn bản sẽ gửi cho khách, trách nhiệm cuối vẫn là người soát.

Hai cách tạo một file:
  - dien_mau: mở khuôn .docx (mẫu kho hoặc file tải lên), thay chuỗi theo run
    — giữ nguyên định dạng gốc (tái dùng toàn bộ máy của template_fill).
  - soan_moi: model viết Markdown, render .docx bằng drafting.render_docx
    (Times New Roman 12pt) — cho văn bản không có khuôn sẵn.
"""
import json
import re
from pathlib import Path

from app import db, settings, template_fill

MAX_FILES = 8
MAX_ATTACH_PROMPT_CHARS = 12_000
# Tổng ngân sách ký tự cho MỌI file đính kèm trong một prompt — giữ dưới trần
# llm_num_ctx (32768 token) sau khi trừ văn bản mẫu (24k ký tự) + phần chỉ dẫn.
ATTACH_TOTAL_BUDGET = 40_000
MAX_PLAN_DESC_CHARS = 500


# ---------------------------------------------------------------------------
# Kế hoạch: hỏi model cần tạo những file nào
# ---------------------------------------------------------------------------
def build_plan_prompt(question: str, attachments, kho_template_title: str | None):
    """attachments: [(filename, text, has_docx)] — has_docx = còn bản gốc làm khuôn."""
    lines = []
    for fname, text, has_docx in attachments:
        tag = " (CÓ BẢN .docx GỐC — dùng được làm khuôn)" if has_docx else ""
        body = (text or "").strip()[:MAX_ATTACH_PROMPT_CHARS]
        lines.append(f"### FILE ĐÍNH KÈM «{fname}»{tag}\n{body}")
    khuon_note = []
    if kho_template_title:
        khuon_note.append(f'- "mau_kho": mẫu đã chọn trong kho — «{kho_template_title}»')
    for fname, _text, has_docx in attachments:
        if has_docx:
            khuon_note.append(f'- "{fname}": file .docx người dùng tải lên')
    khuon_note.append('- "soan_moi": không có khuôn phù hợp, soạn mới từ đầu')

    system = ("Bạn là trợ lý soạn thảo của công ty luật. Bạn chỉ trả về DUY "
              "NHẤT một khối JSON, không giải thích gì bên ngoài JSON.")
    prompt = (
        f"YÊU CẦU CỦA NGƯỜI DÙNG: {question.strip()}\n\n"
        + ("\n\n".join(lines) + "\n\n" if lines else "")
        + "Nhiệm vụ: lên DANH SÁCH các văn bản cần tạo để đáp ứng đúng yêu cầu "
          "(ví dụ: mỗi đợt thanh toán một giấy đề nghị, mỗi mốc bàn giao một "
          "biên bản nghiệm thu). Với mỗi văn bản, chọn khuôn trong các lựa "
          "chọn sau:\n" + "\n".join(khuon_note) + "\n\n"
        "Trả về JSON đúng khung:\n"
        "{\n"
        '  "files": [{"ten_file": "DNTT-02 Giấy đề nghị thanh toán đợt 2",\n'
        '             "khuon": "mau_kho" | "<tên file .docx tải lên>" | "soan_moi",\n'
        '             "yeu_cau": "văn bản này chứa gì, dữ liệu lấy từ đâu, số tiền/đợt nào"}],\n'
        '  "ghi_chu": "các điểm bạn TỰ QUYẾT ĐỊNH hoặc còn thiếu dữ liệu, để người dùng kiểm tra"\n'
        "}\n"
        "Quy tắc:\n"
        f"- Tối đa {MAX_FILES} file; chỉ tạo file mà yêu cầu thật sự cần.\n"
        "- Dữ liệu (số hợp đồng, tên bên, số tài khoản, số tiền, tỷ lệ đợt) "
        "phải lấy từ file đính kèm hoặc câu lệnh; thiếu thì ghi vào ghi_chu, "
        "không bịa.\n"
        "- Ngày tháng chưa biết thì để trống và ghi chú, không tự đặt.\n"
    )
    return prompt, system


def parse_plan(raw_answer: str):
    """Bóc + kiểm tra kế hoạch. Trả về (files, ghi_chu). Raise ValueError khi hỏng."""
    payload = template_fill.parse_llm_json(raw_answer)
    files = []
    for item in (payload.get("files") or [])[:MAX_FILES]:
        if not isinstance(item, dict):
            continue
        ten = str(item.get("ten_file") or "").strip()
        if not ten:
            continue
        khuon = str(item.get("khuon") or "soan_moi").strip()
        yeu_cau = str(item.get("yeu_cau") or "").strip()[:MAX_PLAN_DESC_CHARS]
        files.append({"ten_file": ten[:120], "khuon": khuon, "yeu_cau": yeu_cau})
    if not files:
        raise ValueError("Kế hoạch không có file nào")
    return files, str(payload.get("ghi_chu") or "").strip()


# ---------------------------------------------------------------------------
# Soạn mới bằng Markdown
# ---------------------------------------------------------------------------
def clean_markdown(raw_answer: str) -> str:
    body = re.sub(r"<think>.*?</think>", "", raw_answer or "", flags=re.DOTALL)
    body = re.sub(r"^```(?:markdown|md)?\s*$", "", body.strip(),
                  flags=re.MULTILINE)
    return body.strip()


def build_draft_prompt(ten_file: str, yeu_cau: str, question: str,
                       attachments, ghi_chu_plan: str):
    parts = []
    for fname, text, _has in attachments:
        body = (text or "").strip()[:MAX_ATTACH_PROMPT_CHARS]
        if body:
            parts.append(f"### DỮ LIỆU TỪ «{fname}»\n{body}")
    system = ("Bạn là chuyên viên soạn thảo văn bản của công ty luật Việt Nam. "
              "Bạn trả về DUY NHẤT nội dung văn bản ở dạng Markdown (tiêu đề "
              "dùng #, ##; danh sách dùng -), không lời dẫn, không giải thích.")
    prompt = (
        f"Soạn văn bản: {ten_file}\n"
        f"Yêu cầu riêng: {yeu_cau or '(theo thông lệ loại văn bản này)'}\n"
        f"Bối cảnh từ người dùng: {question.strip()}\n\n"
        + ("\n\n".join(parts) + "\n\n" if parts else "")
        + "Quy tắc bắt buộc:\n"
        "- Đúng thể thức văn bản Việt Nam: quốc hiệu, tiêu ngữ, tên văn bản, "
        "căn cứ, nội dung từng điều/mục, phần ký tên hai bên (nếu là văn bản "
        "song phương).\n"
        "- Mọi con số, tên bên, số tài khoản, số hợp đồng phải lấy từ DỮ LIỆU "
        "ở trên hoặc câu lệnh; thông tin chưa có thì ghi [CẦN BỔ SUNG: mô tả] "
        "— tuyệt đối không bịa.\n"
        "- Ngày tháng chưa chốt thì viết 'ngày … tháng … năm 2026'.\n"
    )
    return prompt, system


# ---------------------------------------------------------------------------
# Nguyên liệu
# ---------------------------------------------------------------------------
def _attachments(conversation_id, use_temp):
    """[(filename, text, source_path|None)] từ temp_files của hội thoại."""
    if not conversation_id or not use_temp:
        return []
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT filename, content, source_path FROM temp_files
                            WHERE conversation_id=%s AND expires_at > now()
                            ORDER BY id""", (conversation_id,))
            return [(r[0], r[1], r[2]) for r in cur.fetchall()]


def _load_skeleton(path_str: str):
    """Mở khuôn .docx đã lưu ở data/work/chat_uploads — rào trong DATA_WORK."""
    import docx
    path = Path(path_str)
    if not path.is_absolute():
        path = Path.cwd() / path
    work_root = (Path.cwd() / template_fill.DATA_WORK).resolve()
    resolved = path.resolve(strict=True)
    resolved.relative_to(work_root)
    return docx.Document(str(resolved))


# ---------------------------------------------------------------------------
# Luồng chính
# ---------------------------------------------------------------------------
def handle(question, *, user_id, dept_ids=None, is_banqt=False, can_finance=False,
           conversation_id=None, template_doc_id=None, model=None, on_status=None,
           role_level=None, dept_codes=None, use_temp=True):
    """Tạo bộ file, trả về dict kiểu direct-answer cho rag.prepare."""
    from app import models
    from app.drafting import render_docx

    def note(label):
        if on_status:
            try:
                on_status(label)
            except Exception:  # noqa: BLE001 — tiến trình chỉ để hiển thị
                pass

    def _fail(answer_md):
        return {"answer": answer_md, "answer_mode": "structured",
                "grounding_status": "not_applicable", "evidence": [], "state": {}}

    # Bộ file luôn mang dữ liệu định danh của một người/một khách cụ thể —
    # model_soan_thao giữ nó ở lại máy chủ trừ khi admin đã mở phạm vi rộng nhất.
    chosen_model = models.model_soan_thao(
        (model or "").strip() or models.effective_llm_model())

    def llm_full(prompt, system, temperature):
        """Gọi model qua STREAM rồi ghép lại — một lượt tạo bộ file có tới
        1+N lời gọi model, mỗi lời gọi không-stream chỉ có trần 300 giây tường;
        stream tính sự sống theo từng mẩu chữ nên văn bản dài trên máy chậm
        không chết oan giữa chừng (rà soát 26/08/2026)."""
        from app.models import llm_stream
        return "".join(llm_stream(prompt, system=system,
                                  temperature=temperature, model=chosen_model))

    # ---- Nguyên liệu -----------------------------------------------------
    note("Đang đọc hồ sơ đính kèm…")
    temp_rows = _attachments(conversation_id, use_temp)
    attachments = [(fname, text, bool(src)) for fname, text, src in temp_rows]
    docx_uploads = {fname: src for fname, _text, src in temp_rows if src}

    # NGÂN SÁCH TỔNG cho phần hồ sơ trong prompt: trần vật lý là llm_num_ctx —
    # vượt là Ollama cắt PHẦN ĐẦU prompt (đúng chỗ đặt văn bản mẫu) một cách
    # câm lặng. Nhiều file đính kèm thì chia nhau ngân sách, và phải NÓI RA
    # việc cắt trong mục kiểm tra.
    attachments_truncated = []
    if attachments:
        share = min(MAX_ATTACH_PROMPT_CHARS,
                    max(2_000, ATTACH_TOTAL_BUDGET // len(attachments)))
        cut = []
        for fname, text, has_docx in attachments:
            body = text or ""
            if len(body) > share:
                attachments_truncated.append(fname)
            cut.append((fname, body[:share], has_docx))
        attachments = cut

    kho_doc = kho_text = None
    template_warning = None
    if template_doc_id:
        row = template_fill._template_row(
            template_doc_id, dept_ids, is_banqt, can_finance,
            role_level=role_level, dept_codes=dept_codes)
        if not row:
            return _fail("Mình không mở được file mẫu đã chọn (không còn trong "
                         "kệ mẫu hoặc tài khoản chưa được xem). Bỏ chọn mẫu "
                         "hoặc chọn mẫu khác rồi thử lại nhé.")
        _kid, kho_title, _ktype, kho_source = row
        if kho_source and str(kho_source).lower().endswith(".docx"):
            try:
                kho_doc_obj, _p = template_fill._load_docx(kho_source)
                kho_doc = (kho_title, kho_source)
                kho_text = template_fill.document_text(kho_doc_obj)
            except (ValueError, FileNotFoundError, OSError):
                template_warning = (f"Mẫu đã chọn «{kho_title}» không mở được "
                                    "(tệp gốc hỏng hoặc không còn) — các file "
                                    "được SOẠN MỚI, KHÔNG theo mẫu kho.")
        else:
            # Đừng im lặng bỏ mẫu người dùng đã chọn — họ sẽ tưởng bộ file đi
            # theo khuôn chuẩn của công ty trong khi thực tế là soạn mới.
            template_warning = (f"Mẫu đã chọn «{kho_title}» không phải file "
                                ".docx nên không dùng làm khuôn được — các "
                                "file được SOẠN MỚI, KHÔNG theo mẫu kho.")
    if not attachments and not kho_doc and not question.strip():
        return _fail("Chưa có gì để tạo file: đính kèm hồ sơ, chọn mẫu, hoặc "
                     "mô tả rõ cần những văn bản gì nhé.")

    # VÙNG TIN CẬY để cắm cờ ⚠: câu lệnh của người dùng + các trường bóc bằng
    # regex truy vết được. Luồng này KHÔNG cách ly giá trị ngoài vùng (dữ liệu
    # điền vốn lấy từ hồ sơ đính kèm theo đúng yêu cầu), nhưng giá trị nào
    # ngoài vùng sẽ mang cờ nhắc đối chiếu bản gốc.
    trusted_fields = {}
    for _fname, text, _h in attachments:
        try:
            from app import autofill
            trusted_fields = autofill.merge_missing(
                trusted_fields, autofill.extract_person_fields(text))
        except Exception:  # noqa: BLE001
            pass
    trusted_fold = template_fill._fold_for_match(
        question + " " + " ".join(v for v in trusted_fields.values() if v))

    # ---- Bước 1: kế hoạch ------------------------------------------------
    note("Đang lên danh sách file cần tạo…")
    plan_prompt, plan_system = build_plan_prompt(
        question, attachments, kho_doc[0] if kho_doc else None)
    raw_plan = llm_full(plan_prompt, plan_system, 0.0)
    try:
        plan_files, ghi_chu_plan = parse_plan(raw_plan)
    except (ValueError, json.JSONDecodeError):
        return _fail("Model chưa lên được danh sách file hợp lệ. Bạn mô tả rõ "
                     "hơn: cần những văn bản gì, mỗi văn bản chứa dữ liệu nào?")

    # ---- Bước 2: tạo từng file ------------------------------------------
    # LƯU Ý AN TOÀN: khác luồng "Tạo file mẫu", ở đây dữ liệu điền LẤY TỪ CHÍNH
    # HỒ SƠ ĐÍNH KÈM (người dùng yêu cầu vậy — số hợp đồng, số tài khoản, các
    # đợt tiền đều nằm trong đó), nên KHÔNG áp được chốt trusted_text. Bù lại:
    # (1) mọi thay thế vẫn qua bộ lọc cấu trúc của sanitize_replacements;
    # (2) câu trả lời liệt kê từng chỗ đã thay + mục "TỰ QUYẾT ĐỊNH" bắt buộc;
    # (3) file là hàng tạm 24 giờ, không vào kho tri thức.
    results = []      # (ten_file, token, out_path, mo_ta, warnings)
    total = len(plan_files)
    party_note = (f"YÊU CẦU CHUNG: {question.strip()}\n"
                  f"GHI CHÚ KẾ HOẠCH: {ghi_chu_plan[:1000]}" if ghi_chu_plan
                  else f"YÊU CẦU CHUNG: {question.strip()}")
    for i, spec in enumerate(plan_files, 1):
        ten_file, khuon, yeu_cau = spec["ten_file"], spec["khuon"], spec["yeu_cau"]
        note(f"Đang soạn file {i}/{total}: {ten_file}…")
        warnings = []
        details = []   # bảng đối chiếu «cũ» → «mới» của CHÍNH file này
        if khuon == "mau_kho" and kho_doc:
            skeleton_path, skeleton_text = kho_doc[1], kho_text
        elif khuon in docx_uploads:
            skeleton_path, skeleton_text = docx_uploads[khuon], None
        else:
            skeleton_path = skeleton_text = None
            if khuon not in ("soan_moi", "", None):
                warnings.append(f"khuôn «{khuon}» không mở được — đã soạn mới")

        def _flag(value):
            """⚠ cho giá trị KHÔNG nằm trong câu lệnh/trường đã bóc — tức là
            model tự lấy từ file đính kèm; người soát phải đối chiếu bản gốc."""
            if template_fill._fold_for_match(value) in trusted_fold:
                return ""
            return " ⚠ (lấy từ file đính kèm — đối chiếu bản gốc)"

        try:
            if skeleton_path:
                # Điền vào khuôn giữ định dạng
                if khuon == "mau_kho":
                    doc, _p = template_fill._load_docx(skeleton_path)
                else:
                    doc = _load_skeleton(skeleton_path)
                if skeleton_text is None:
                    skeleton_text = template_fill.document_text(doc)
                placeholders = template_fill.scan_placeholders(doc)
                fill_prompt, fill_system = template_fill.build_fill_prompt(
                    skeleton_text,
                    f"FILE CẦN TẠO: {ten_file}\nYÊU CẦU RIÊNG: {yeu_cau}\n"
                    f"{party_note}\n\n"
                    + "\n\n".join(f"NỘI DUNG «{f}»:\n{t}"
                                  for f, t, _h in attachments),
                    placeholders)
                raw_fill = llm_full(fill_prompt, fill_system, 0.0)
                payload = template_fill.parse_llm_json(raw_fill)
                ph_values = payload.get("placeholders") or {}
                ph_pairs = []
                for literal, key in placeholders:
                    for k, v in ph_values.items():
                        if template_fill.normalize_key(str(k)) == key and str(v).strip():
                            ph_pairs.append((literal, str(v).strip()))
                            break
                reps, dropped = template_fill.sanitize_replacements(
                    payload.get("replacements"), skeleton_text)
                counts = template_fill.apply_replacements(doc, ph_pairs + reps)
                changed = sum(counts.values())
                # BẢNG ĐỐI CHIẾU TỪNG CHỖ THAY — đây là chốt bù cho việc luồng
                # này không cách ly giá trị ngoài vùng tin cậy: người soát phải
                # NHÌN THẤY từng chỗ đã thay, không chỉ một con số tổng.
                for literal, value in ph_pairs:
                    if counts.get(literal, 0):
                        details.append(f"chỗ trống `{literal}` → **{value}**"
                                       f" ({counts[literal]} chỗ){_flag(value)}")
                for old, new in reps:
                    n = counts.get(old, 0)
                    if n:
                        details.append(f"«{old}» → **{new}** ({n} chỗ){_flag(new)}")
                for old, reason in dropped:
                    warnings.append(f"bỏ «{old[:60]}»: {reason}")
                extra_note = str(payload.get("ghi_chu") or "").strip()
                if extra_note:
                    warnings.append(extra_note)
                token, out_path = template_fill.save_filled(doc, ten_file)
                mo_ta = f"điền khuôn ({changed} chỗ thay)"
            else:
                # Soạn mới bằng Markdown → .docx
                d_prompt, d_system = build_draft_prompt(
                    ten_file, yeu_cau, question, attachments, ghi_chu_plan)
                raw_md = llm_full(d_prompt, d_system, 0.1)
                md = clean_markdown(raw_md)
                if not md:
                    raise ValueError("model trả nội dung rỗng")
                n_holes = md.count("[CẦN BỔ SUNG")
                payload_bytes = render_docx(md, ten_file, [])
                token, out_path = template_fill.save_filled_bytes(payload_bytes, ten_file)
                mo_ta = ("soạn mới"
                         + (f", {n_holes} chỗ [CẦN BỔ SUNG]" if n_holes else ""))
        except Exception as exc:  # noqa: BLE001 — một file hỏng không huỷ cả bộ
            results.append((ten_file, None, None,
                            f"KHÔNG TẠO ĐƯỢC ({type(exc).__name__})", warnings, []))
            continue
        results.append((ten_file, token, out_path, mo_ta, warnings, details))

    template_fill.cleanup_old_fills()
    made = [r for r in results if r[1]]
    if not made:
        return _fail("Mình chưa tạo được file nào từ yêu cầu này. Bạn thử mô "
                     "tả lại danh sách file cần soạn và dữ liệu cho từng file.")

    # ---- Câu trả lời ------------------------------------------------------
    lines = [f"Đã tạo **{len(made)}/{total} file** theo yêu cầu:"]
    for ten_file, token, _path, mo_ta, _warn, details in results:
        if token:
            lines.append(f"- **{ten_file}** — {mo_ta}")
            for d in details:
                lines.append(f"  - {d}")
        else:
            lines.append(f"- ~~{ten_file}~~ — {mo_ta}")

    review_lines = []
    if template_warning:
        review_lines.append(f"- {template_warning}")
    if attachments_truncated:
        review_lines.append(
            "- Hồ sơ đính kèm dài, hệ thống chỉ đọc được phần đầu của: "
            + ", ".join(f"«{f}»" for f in attachments_truncated)
            + " — dữ liệu ở các trang sau có thể chưa vào file.")
    if ghi_chu_plan:
        review_lines.append(f"- {ghi_chu_plan}")
    for ten_file, token, _path, _mo_ta, warn, _details in results:
        for w in warn:
            review_lines.append(f"- [{ten_file}] {w}")
    if review_lines:
        lines.append("\n**CHỖ AI TỰ QUYẾT ĐỊNH / CÒN THIẾU — KIỂM TRA BẮT BUỘC:**")
        lines.extend(review_lines)

    lines.append("\nBấm các nút **Tải** ngay dưới tin nhắn này để lấy từng "
                 "file. Văn bản sẽ gửi ra ngoài — vui lòng RÀ TOÀN VĂN từng "
                 "file (tên bên, con số, ngày tháng, điều khoản) trước khi dùng; "
                 "file tự xoá sau 24 giờ.")

    evidence = [{
        "kind": "system",
        "title": f"File đã tạo: {ten_file}",
        "source_locator": f"template_fill#{token}",
        "quote": out_path.name,
        "as_of": None,
    } for ten_file, token, out_path, _m, _w, _d in results if token]

    with db.session(role="internal", admin=True) as conn:
        db.audit(conn, user_id, "doc_factory", "conversation", conversation_id,
                 {"planned": total, "made": len(made),
                  "template_doc_id": template_doc_id})
    return {"answer": "\n".join(lines), "answer_mode": "structured",
            "grounding_status": "verified", "evidence": evidence,
            "state": {}}
