"""FastAPI routes cho khu vực Soạn tài liệu.

Tách khỏi ``api.py`` để luồng chat không phải gánh thêm hàng trăm dòng workflow.
``build_router`` nhận dependency xác thực/reviewer từ API chính, tránh tạo một
cơ chế đăng nhập thứ hai có thể lệch quyền.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from app import autofill, db, drafting, rag


INTERNAL_ROLES = {"admin", "ban_qt", "truong_bph", "chuyen_vien", "tro_ly"}
MAX_INSTRUCTIONS_CHARS = 20_000
MAX_INPUT_JSON_CHARS = 100_000
MAX_MANUAL_DRAFT_CHARS = 500_000
MAX_AUTOFILL_MB = int(os.getenv("MAX_UPLOAD_MB", "50"))
# Các định dạng hồ sơ cá nhân nhận bóc thông tin: giấy tờ số hoá (PDF/DOCX)
# và ảnh chụp điện thoại (CCCD, sơ yếu…) — ảnh đi qua OCR ở app/ingest.py.
AUTOFILL_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".md",
                       ".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp"}


class DraftTemplateIn(BaseModel):
    code: str
    name: str
    document_type: str = "other"
    description: str | None = None
    system_instructions: str | None = None
    body_template: str
    required_fields: list[str] | None = None


class DraftCreateIn(BaseModel):
    title: str
    document_type: str | None = None
    template_id: int | None = None
    client_id: int | None = None
    matter_id: int | None = None
    department_id: int | None = None
    instructions: str | None = None
    input_data: dict | None = None
    source_document_ids: list[int] | None = None


class DraftGenerateIn(BaseModel):
    instructions: str | None = None
    model: str | None = None


class DraftReviseIn(BaseModel):
    instructions: str | None = None
    content_markdown: str | None = None
    source_document_ids: list[int] | None = None
    input_data: dict | None = None
    model: str | None = None
    change_note: str | None = None


class DraftApproveIn(BaseModel):
    note: str | None = None
    allow_placeholders: bool = False
    confirm_needs_review: bool = False


DRAFT_COLUMNS = (
    "id", "title", "document_type", "template_id", "template_name", "client_id",
    "matter_id", "department_id", "instructions", "input_data", "status",
    "current_version", "created_by", "creator_name", "approved_by", "approver_name",
    "approved_at", "approval_note", "created_at", "updated_at",
)


def _require_internal(user):
    if user["role"] not in INTERNAL_ROLES:
        raise HTTPException(403, "Chức năng soạn tài liệu chỉ dành cho nhân viên nội bộ")


def _check_size(value, name: str, maximum: int):
    if value is not None and len(value) > maximum:
        raise HTTPException(413, f"{name} vượt giới hạn {maximum:,} ký tự")


def _check_input_data(value: dict | None):
    if value is not None and len(json.dumps(value, ensure_ascii=False)) > MAX_INPUT_JSON_CHARS:
        raise HTTPException(413, "input_data vượt giới hạn 100.000 ký tự")


def _json_value(value, fallback):
    if value is None:
        return fallback
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return fallback
    return value


def _draft_row(cur, draft_id: int, lock: bool = False):
    cur.execute(
        """SELECT d.id,d.title,d.document_type,d.template_id,t.name,d.client_id,
                  d.matter_id,d.department_id,d.instructions,d.input_data,d.status,
                  d.current_version,d.created_by,u.full_name,d.approved_by,au.full_name,
                  d.approved_at,d.approval_note,d.created_at,d.updated_at
             FROM document_drafts d
             LEFT JOIN document_templates t ON t.id=d.template_id
             LEFT JOIN users u ON u.id=d.created_by
             LEFT JOIN users au ON au.id=d.approved_by
            WHERE d.id=%s""" + (" FOR UPDATE OF d" if lock else ""),
        (draft_id,),
    )
    row = cur.fetchone()
    return dict(zip(DRAFT_COLUMNS, row)) if row else None


def _can_access(user, draft: dict) -> bool:
    if draft["created_by"] == user["id"] or user["is_banqt"]:
        return True
    return bool(
        user.get("can_review")
        and draft.get("department_id") is not None
        and draft["department_id"] in (user.get("dept_ids") or [])
        and draft.get("status") in {"generated", "approved"}
    )


def _get_draft(user, draft_id: int, edit: bool = False) -> dict:
    _require_internal(user)
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            draft = _draft_row(cur, draft_id)
    if not draft:
        raise HTTPException(404, "Không thấy bản nháp")
    if not _can_access(user, draft):
        raise HTTPException(403, "Bạn không có quyền xem bản nháp này")
    if edit and draft["created_by"] != user["id"] and not user["is_banqt"]:
        raise HTTPException(403, "Chỉ người tạo hoặc Ban quản trị được sửa bản nháp")
    return draft


def _source_ids(values: list[int] | None) -> list[int]:
    try:
        return drafting.normalize_source_ids(values)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


def _allowed_documents(user, ids: list[int]) -> list[dict]:
    """Kiểm tra từng nguồn bằng đúng ma trận quyền dùng khi tải/mở tài liệu."""
    if not ids:
        return []
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT d.id,d.title,d.doc_type,d.access_level,d.client_id,
                          d.department_id,dep.name,d.approved,d.label_verified,
                          coalesce(d.active,true),coalesce(d.extraction_status,'ready')
                     FROM documents d
                     LEFT JOIN departments dep ON dep.id=d.department_id
                    WHERE d.id=ANY(%s)""",
                (ids,),
            )
            rows = cur.fetchall()
    found = {row[0]: row for row in rows}
    missing = [doc_id for doc_id in ids if doc_id not in found]
    if missing:
        raise HTTPException(404, f"Không thấy tài liệu nguồn: {missing}")
    rules = rag.load_access_rules()
    result = []
    for doc_id in ids:
        row = found[doc_id]
        doc = {
            "id": row[0], "title": row[1], "doc_type": row[2],
            "access_level": row[3], "client_id": row[4], "department_id": row[5],
            "department_name": row[6],
        }
        if not rag.can_open_doc(
            user["role"], user["dept_ids"], user["is_banqt"], doc,
            can_finance=user["can_finance"], rules=rules,
            dept_codes=user["dept_codes"],
        ):
            raise HTTPException(403, f"Không có quyền dùng tài liệu nguồn #{doc_id}")
        # Cổng con người là approved+label_verified — KHÔNG chặn theo
        # extraction_status: mọi bản scan OCR đều mang 'warning', chặn ở đây là
        # cấm dùng giấy tờ scan ĐÃ DUYỆT làm nguồn soạn thảo (HĐLĐ, CCCD scan
        # chính là loại nguồn hay cần nhất). Cùng bài với rag.retrieve 20/08/2026.
        if not row[7] or not row[8] or not row[9]:
            raise HTTPException(
                409,
                f"Tài liệu #{doc_id} chưa sẵn sàng/được duyệt nên chưa thể dùng làm căn cứ",
            )
        result.append(doc)
    return result


def _resolve_scope(user, client_id: int | None, matter_id: int | None,
                   department_id: int | None) -> tuple[int | None, int | None]:
    resolved_client, resolved_dept = client_id, department_id
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            if matter_id is not None:
                cur.execute("SELECT client_id,department_id FROM matters WHERE id=%s", (matter_id,))
                matter = cur.fetchone()
                if not matter:
                    raise HTTPException(404, "Không thấy vụ việc")
                if resolved_client is not None and resolved_client != matter[0]:
                    raise HTTPException(422, "Vụ việc không thuộc khách hàng đã chọn")
                if resolved_dept is not None and matter[1] is not None and resolved_dept != matter[1]:
                    raise HTTPException(422, "Vụ việc không thuộc phòng đã chọn")
                resolved_client = matter[0]
                resolved_dept = matter[1] if matter[1] is not None else resolved_dept
            if resolved_client is not None:
                cur.execute("SELECT department_id FROM clients WHERE id=%s", (resolved_client,))
                client = cur.fetchone()
                if not client:
                    raise HTTPException(404, "Không thấy khách hàng")
                if resolved_dept is not None and client[0] is not None and resolved_dept != client[0]:
                    raise HTTPException(422, "Khách hàng không thuộc phòng đã chọn")
                resolved_dept = client[0] if client[0] is not None else resolved_dept
            if resolved_dept is not None:
                cur.execute("SELECT 1 FROM departments WHERE id=%s", (resolved_dept,))
                if not cur.fetchone():
                    raise HTTPException(404, "Không thấy phòng ban")
    if (resolved_dept is not None and not user["is_banqt"]
            and resolved_dept not in (user["dept_ids"] or [])):
        raise HTTPException(403, "Khách/vụ việc này thuộc phòng khác")
    return resolved_client, resolved_dept


def _template(conn, template_id: int | None) -> dict:
    with conn.cursor() as cur:
        if template_id is None:
            cur.execute(
                """SELECT id,code,name,document_type,description,system_instructions,
                          body_template,required_fields FROM document_templates
                    WHERE code='generic_grounded' AND active"""
            )
        else:
            cur.execute(
                """SELECT id,code,name,document_type,description,system_instructions,
                          body_template,required_fields FROM document_templates
                    WHERE id=%s AND active""",
                (template_id,),
            )
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Không thấy mẫu tài liệu đang hoạt động")
    return {
        "id": row[0], "code": row[1], "name": row[2], "document_type": row[3],
        "description": row[4], "system_instructions": row[5] or "",
        "body_template": row[6], "required_fields": _json_value(row[7], []),
    }


def _detail(user, draft_id: int) -> dict:
    draft = _get_draft(user, draft_id)
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT d.id,d.title,d.doc_type
                     FROM document_draft_sources s JOIN documents d ON d.id=s.document_id
                    WHERE s.draft_id=%s ORDER BY s.created_at,d.id""",
                (draft_id,),
            )
            sources = [{"id": r[0], "title": r[1], "doc_type": r[2]} for r in cur.fetchall()]
            cur.execute(
                """SELECT id,version_no,change_note,model_used,grounding_status,
                          placeholder_count,created_by,created_at
                     FROM document_draft_versions WHERE draft_id=%s ORDER BY version_no DESC""",
                (draft_id,),
            )
            versions = [{
                "id": r[0], "version_no": r[1], "change_note": r[2], "model_used": r[3],
                "grounding_status": r[4], "placeholder_count": r[5],
                "created_by": r[6], "created_at": r[7],
            } for r in cur.fetchall()]
            latest = None
            if versions:
                cur.execute(
                    "SELECT content_markdown,evidence_snapshot FROM document_draft_versions WHERE id=%s",
                    (versions[0]["id"],),
                )
                content, snapshot = cur.fetchone()
                latest = {**versions[0], "content_markdown": content,
                          "evidence": _json_value(snapshot, [])}
    draft["input_data"] = _json_value(draft.get("input_data"), {})
    draft.update(source_documents=sources, versions=versions, latest_version=latest)
    # Người duyệt không mặc nhiên được đọc mọi nguồn của người tạo. Trước khi
    # trả excerpt/content cho người khác, kiểm lại chính ma trận quyền tài liệu.
    if draft["created_by"] != user["id"]:
        evidence_ids = [
            e.get("document_id") for e in ((latest or {}).get("evidence") or [])
            if e.get("document_id")
        ]
        protected_ids = list(dict.fromkeys([s["id"] for s in sources] + evidence_ids))
        _allowed_documents(user, protected_ids)
    return draft


def _draft_source_ids(draft_id: int) -> list[int]:
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT document_id FROM document_draft_sources WHERE draft_id=%s ORDER BY created_at,document_id",
                (draft_id,),
            )
            return [r[0] for r in cur.fetchall()]


def _prepare_generation(user, draft: dict, source_ids: list[int], instructions: str,
                        input_data: dict, previous_content: str | None,
                        model: str | None) -> dict:
    _allowed_documents(user, source_ids)  # quyền có thể đổi sau lúc tạo
    with db.session(role="internal", admin=True) as conn:
        template = _template(conn, draft["template_id"])
        query = " ".join([
            draft["title"], instructions or "", json.dumps(input_data, ensure_ascii=False)
        ])[:8000]
        evidence = drafting.retrieve_evidence(conn, source_ids, query)
    missing = drafting.missing_required_fields(template["required_fields"], input_data)
    return drafting.generate_content(
        title=draft["title"], instructions=instructions, input_data=input_data,
        body_template=template["body_template"],
        template_instructions=template["system_instructions"], evidence=evidence,
        missing_fields=missing, previous_content=previous_content, model=model,
    )


def _save_version(user, draft: dict, result: dict, source_ids: list[int],
                  instructions: str, input_data: dict, change_note: str) -> int:
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            current = _draft_row(cur, draft["id"], lock=True)
            if not current:
                raise HTTPException(404, "Không thấy bản nháp")
            if current["status"] == "approved":
                raise HTTPException(409, "Bản đã duyệt được khóa; hãy tạo bản nháp mới")
            if current["current_version"] != draft["current_version"]:
                raise HTTPException(409, "Bản nháp vừa được sửa ở nơi khác; hãy tải lại rồi thử lại")
            version_no = current["current_version"] + 1
            cur.execute(
                """INSERT INTO document_draft_versions
                     (draft_id,version_no,content_markdown,change_note,model_used,
                      grounding_status,placeholder_count,evidence_snapshot,created_by)
                     VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (draft["id"], version_no, result["content_markdown"], change_note,
                 result.get("model_used"), result["grounding_status"],
                 result["placeholder_count"],
                 json.dumps(result["evidence"], ensure_ascii=False), user["id"]),
            )
            version_id = cur.fetchone()[0]
            for item in result["evidence"]:
                cur.execute(
                    """INSERT INTO document_draft_evidence
                         (draft_version_id,document_id,document_title,source_version,
                          chunk_id,citation_key,excerpt,page_number,section_title,source_locator)
                         VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (version_id, item["document_id"], item["document_title"],
                     item.get("source_version"),
                     item.get("chunk_id"), item["citation_key"], item["excerpt"],
                     item.get("page_number"), item.get("section_title"),
                     item.get("source_locator")),
                )
            cur.execute("DELETE FROM document_draft_sources WHERE draft_id=%s", (draft["id"],))
            for doc_id in source_ids:
                cur.execute(
                    "INSERT INTO document_draft_sources(draft_id,document_id,added_by) VALUES (%s,%s,%s)",
                    (draft["id"], doc_id, user["id"]),
                )
            cur.execute(
                """UPDATE document_drafts SET status='generated',current_version=%s,
                          instructions=%s,input_data=%s,approved_by=NULL,approved_at=NULL,
                          approval_note=NULL,updated_at=now() WHERE id=%s""",
                (version_no, instructions, json.dumps(input_data, ensure_ascii=False), draft["id"]),
            )
        db.audit(conn, user["id"], "generate_draft_version", "document_drafts", draft["id"], {
            "version": version_no, "model": result.get("model_used"),
            "grounding_status": result["grounding_status"],
            "placeholder_count": result["placeholder_count"],
            "source_document_ids": source_ids, "latency_ms": result.get("latency_ms", 0),
        })
    return version_no


def _markdown_with_evidence(content: str, evidence: list[dict]) -> str:
    if not evidence:
        return content
    lines = [content.rstrip(), "", "---", "", "# Nguồn và bằng chứng", ""]
    for item in evidence:
        locator = []
        if item.get("page_number"):
            locator.append(f"trang {item['page_number']}")
        if item.get("section_title"):
            locator.append(f"mục {item['section_title']}")
        suffix = f" ({', '.join(locator)})" if locator else ""
        lines.extend([
            f"## [{item['citation_key']}] {item['document_title']}{suffix}", "",
            item["excerpt"], "",
        ])
    return "\n".join(lines).rstrip() + "\n"


def build_router(current_user, require_reviewer) -> APIRouter:
    router = APIRouter(tags=["drafting"])

    @router.get("/draft-templates")
    def templates_list(user=Depends(current_user)):
        _require_internal(user)
        with db.session(role="internal", admin=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT id,code,name,document_type,description,body_template,
                              required_fields,created_at
                         FROM document_templates WHERE active ORDER BY name"""
                )
                rows = cur.fetchall()
        return {"items": [{
            "id": r[0], "code": r[1], "name": r[2], "document_type": r[3],
            "description": r[4], "body_template": r[5],
            "required_fields": _json_value(r[6], []), "created_at": r[7],
        } for r in rows]}

    @router.post("/draft-templates")
    def templates_create(body: DraftTemplateIn, user=Depends(current_user)):
        require_reviewer(user)
        _check_size(body.body_template, "Nội dung mẫu", 100_000)
        _check_size(body.system_instructions, "Chỉ dẫn mẫu", MAX_INSTRUCTIONS_CHARS)
        code = (body.code or "").strip().lower()
        if not re.fullmatch(r"[a-z0-9_-]{2,60}", code):
            raise HTTPException(422, "Mã mẫu chỉ gồm a-z, 0-9, gạch ngang/gạch dưới")
        if not body.name.strip() or not body.body_template.strip():
            raise HTTPException(422, "Tên và nội dung mẫu không được để trống")
        with db.session(role="internal", admin=True) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM document_templates WHERE code=%s", (code,))
                if cur.fetchone():
                    raise HTTPException(409, "Mã mẫu đã tồn tại")
                cur.execute(
                    """INSERT INTO document_templates
                         (code,name,document_type,description,system_instructions,body_template,
                          required_fields,created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                         RETURNING id""",
                    (code, body.name.strip(), body.document_type, body.description,
                     body.system_instructions, body.body_template,
                     json.dumps(body.required_fields or [], ensure_ascii=False), user["id"]),
                )
                template_id = cur.fetchone()[0]
            db.audit(conn, user["id"], "create_draft_template", "document_templates",
                     template_id, {"code": code})
        return {"ok": True, "template_id": template_id}

    @router.post("/drafts/autofill")
    async def drafts_autofill(file: UploadFile = File(...), user=Depends(current_user)):
        """Bóc thông tin cá nhân từ MỘT hồ sơ tải lên để điền sẵn bản nháp.

        Nhận CCCD/sơ yếu lý lịch/CV dạng PDF, ảnh chụp hoặc DOCX; trích văn bản
        (OCR nếu là ảnh/scan) rồi đọc ra các trường định danh bằng
        app/autofill.py. File DÙNG XONG BỎ — không vào kho tri thức, không lưu
        lại trên đĩa; muốn lưu thì dùng đường tải tài liệu bình thường.
        """
        _require_internal(user)
        ext = Path(file.filename or "").suffix.lower()
        if ext not in AUTOFILL_EXTENSIONS:
            raise HTTPException(
                400, "Chỉ nhận " + ", ".join(sorted(AUTOFILL_EXTENSIONS)))
        limit = MAX_AUTOFILL_MB * 1024 * 1024
        tmp_path = None
        try:
            size = 0
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                tmp_path = Path(tmp.name)
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > limit:
                        raise HTTPException(413, f"Tệp vượt quá {MAX_AUTOFILL_MB} MB")
                    tmp.write(chunk)
            from app.ingest import ExtractionError, extract_text_with_metadata
            try:
                extraction = extract_text_with_metadata(tmp_path)
            except ExtractionError as exc:
                raise HTTPException(422, f"Không đọc được nội dung tệp: {exc}")
            fields = autofill.extract_person_fields(extraction.text)
            with db.session(role="internal", admin=True) as conn:
                # Ghi vết TÊN TRƯỜNG đã bóc, không ghi giá trị — nhật ký kiểm
                # toán không phải chỗ chứa số CCCD của người khác.
                db.audit(conn, user["id"], "draft_autofill", "document_drafts", None,
                         {"file": file.filename, "bytes": size,
                          "method": extraction.method,
                          "fields": sorted(fields.keys())})
            return {
                "ok": True, "fields": fields,
                "field_labels": {k: autofill.FIELD_LABELS.get(k, k) for k in fields},
                "warnings": extraction.warnings, "method": extraction.method,
                "text_chars": len(extraction.text),
            }
        finally:
            await file.close()
            if tmp_path:
                tmp_path.unlink(missing_ok=True)

    @router.get("/drafts")
    def drafts_list(user=Depends(current_user), status: str = "", limit: int = 100):
        _require_internal(user)
        if status and status not in {"draft", "generated", "approved"}:
            raise HTTPException(422, "Trạng thái bản nháp không hợp lệ")
        limit = max(1, min(limit, 200))
        sql = """SELECT d.id,d.title,d.document_type,d.status,d.current_version,
                        d.department_id,d.client_id,d.matter_id,d.created_by,u.full_name,
                        d.approved_at,d.updated_at,v.grounding_status,v.placeholder_count
                   FROM document_drafts d LEFT JOIN users u ON u.id=d.created_by
                   LEFT JOIN LATERAL (
                     SELECT grounding_status,placeholder_count FROM document_draft_versions
                      WHERE draft_id=d.id ORDER BY version_no DESC LIMIT 1
                   ) v ON true WHERE true"""
        params = []
        if not user["is_banqt"]:
            if user.get("can_review") and user["dept_ids"]:
                sql += " AND (d.created_by=%s OR (d.department_id=ANY(%s) AND d.status IN ('generated','approved')))"
                params += [user["id"], user["dept_ids"]]
            else:
                sql += " AND d.created_by=%s"
                params.append(user["id"])
        if status:
            sql += " AND d.status=%s"
            params.append(status)
        sql += " ORDER BY d.updated_at DESC LIMIT %s"
        params.append(limit)
        with db.session(role="internal", admin=True) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        return {"items": [{
            "id": r[0], "title": r[1], "document_type": r[2], "status": r[3],
            "current_version": r[4], "department_id": r[5], "client_id": r[6],
            "matter_id": r[7], "created_by": r[8], "creator_name": r[9],
            "approved_at": r[10], "updated_at": r[11], "grounding_status": r[12],
            "placeholder_count": r[13],
        } for r in rows]}

    @router.post("/drafts")
    def drafts_create(body: DraftCreateIn, user=Depends(current_user)):
        _require_internal(user)
        _check_size(body.instructions, "Yêu cầu soạn thảo", MAX_INSTRUCTIONS_CHARS)
        _check_input_data(body.input_data)
        title = " ".join((body.title or "").split()).strip()
        if not title or len(title) > 200:
            raise HTTPException(422, "Tên bản nháp phải có 1-200 ký tự")
        ids = _source_ids(body.source_document_ids)
        _allowed_documents(user, ids)
        client_id, department_id = _resolve_scope(
            user, body.client_id, body.matter_id, body.department_id
        )
        with db.session(role="internal", admin=True) as conn:
            template = _template(conn, body.template_id)
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO document_drafts
                         (title,document_type,template_id,client_id,matter_id,department_id,
                          instructions,input_data,created_by)
                         VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                    (title, body.document_type or template["document_type"], template["id"],
                     client_id, body.matter_id, department_id, body.instructions,
                     json.dumps(body.input_data or {}, ensure_ascii=False), user["id"]),
                )
                draft_id = cur.fetchone()[0]
                for doc_id in ids:
                    cur.execute(
                        "INSERT INTO document_draft_sources(draft_id,document_id,added_by) VALUES (%s,%s,%s)",
                        (draft_id, doc_id, user["id"]),
                    )
            db.audit(conn, user["id"], "create_draft", "document_drafts", draft_id,
                     {"source_document_ids": ids, "template_id": template["id"]})
        return _detail(user, draft_id)

    @router.get("/drafts/{draft_id}")
    def drafts_get(draft_id: int, user=Depends(current_user)):
        return _detail(user, draft_id)

    @router.post("/drafts/{draft_id}/generate")
    def drafts_generate(draft_id: int, body: DraftGenerateIn, user=Depends(current_user)):
        _check_size(body.instructions, "Yêu cầu soạn thảo", MAX_INSTRUCTIONS_CHARS)
        draft = _get_draft(user, draft_id, edit=True)
        if draft["status"] == "approved":
            raise HTTPException(409, "Bản đã duyệt được khóa; hãy tạo bản nháp mới")
        instructions = body.instructions if body.instructions is not None else (draft["instructions"] or "")
        input_data = _json_value(draft["input_data"], {})
        ids = _draft_source_ids(draft_id)
        try:
            result = _prepare_generation(
                user, draft, ids, instructions, input_data, None, body.model
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(503, f"Không sinh được bản nháp: {exc}")
        _save_version(user, draft, result, ids, instructions, input_data, "Sinh bản nháp")
        return _detail(user, draft_id)

    @router.post("/drafts/{draft_id}/revise")
    def drafts_revise(draft_id: int, body: DraftReviseIn, user=Depends(current_user)):
        _check_size(body.instructions, "Yêu cầu chỉnh sửa", MAX_INSTRUCTIONS_CHARS)
        _check_size(body.content_markdown, "Nội dung bản nháp", MAX_MANUAL_DRAFT_CHARS)
        _check_input_data(body.input_data)
        draft = _get_draft(user, draft_id, edit=True)
        if draft["status"] == "approved":
            raise HTTPException(409, "Bản đã duyệt được khóa; hãy tạo bản nháp mới")
        if draft["current_version"] < 1:
            raise HTTPException(409, "Hãy sinh phiên bản đầu tiên trước khi sửa")
        detail = _detail(user, draft_id)
        previous = detail["latest_version"]["content_markdown"]
        ids = (_source_ids(body.source_document_ids) if body.source_document_ids is not None
               else [d["id"] for d in detail["source_documents"]])
        input_data = body.input_data if body.input_data is not None else detail["input_data"]
        instructions = body.instructions if body.instructions is not None else (draft["instructions"] or "")
        if body.content_markdown is not None:
            if not body.content_markdown.strip():
                raise HTTPException(422, "Nội dung sửa không được để trống")
            _allowed_documents(user, ids)
            with db.session(role="internal", admin=True) as conn:
                evidence = drafting.assign_citation_keys(drafting.retrieve_evidence(
                    conn, ids, f"{draft['title']} {instructions}"[:8000]
                ))
            content, grounding, placeholders = drafting.clean_and_score(
                body.content_markdown, evidence
            )
            result = {
                "content_markdown": content, "model_used": None, "latency_ms": 0,
                "grounding_status": grounding, "placeholder_count": placeholders,
                "evidence": evidence,
            }
        else:
            try:
                result = _prepare_generation(
                    user, draft, ids, instructions, input_data, previous, body.model
                )
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(503, f"Không sửa được bản nháp bằng AI: {exc}")
        _save_version(
            user, draft, result, ids, instructions, input_data,
            body.change_note or "Chỉnh sửa bản nháp",
        )
        return _detail(user, draft_id)

    @router.get("/drafts/{draft_id}/versions/{version_no}")
    def version_get(draft_id: int, version_no: int, user=Depends(current_user)):
        draft = _get_draft(user, draft_id)
        with db.session(role="internal", admin=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT id,content_markdown,change_note,model_used,grounding_status,
                              placeholder_count,evidence_snapshot,created_by,created_at
                         FROM document_draft_versions
                        WHERE draft_id=%s AND version_no=%s""",
                    (draft_id, version_no),
                )
                row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Không thấy phiên bản")
        evidence = _json_value(row[6], [])
        if draft["created_by"] != user["id"]:
            _allowed_documents(user, list(dict.fromkeys(
                e.get("document_id") for e in evidence if e.get("document_id")
            )))
        return {
            "id": row[0], "draft_id": draft_id, "version_no": version_no,
            "content_markdown": row[1], "change_note": row[2], "model_used": row[3],
            "grounding_status": row[4], "placeholder_count": row[5],
            "evidence": evidence, "created_by": row[7], "created_at": row[8],
        }

    @router.post("/drafts/{draft_id}/approve")
    def drafts_approve(draft_id: int, body: DraftApproveIn, user=Depends(current_user)):
        require_reviewer(user)
        draft = _get_draft(user, draft_id)
        _detail(user, draft_id)  # kiểm quyền với toàn bộ nguồn/excerpt trước khi duyệt
        with db.session(role="internal", admin=True) as conn:
            with conn.cursor() as cur:
                current = _draft_row(cur, draft_id, lock=True)
                if not current or not _can_access(user, current):
                    raise HTTPException(403, "Không có quyền duyệt bản nháp này")
                if current["status"] != "generated" or current["current_version"] < 1:
                    raise HTTPException(409, "Chỉ duyệt được bản đã sinh nội dung")
                cur.execute(
                    """SELECT grounding_status,placeholder_count FROM document_draft_versions
                        WHERE draft_id=%s AND version_no=%s""",
                    (draft_id, current["current_version"]),
                )
                grounding, placeholders = cur.fetchone()
                if placeholders and not body.allow_placeholders:
                    raise HTTPException(
                        409, f"Bản còn {placeholders} chỗ [CẦN BỔ SUNG]; xử lý hết hoặc "
                        "gửi allow_placeholders=true để xác nhận rõ ràng",
                    )
                if grounding != "grounded" and not body.confirm_needs_review:
                    raise HTTPException(
                        409, "Bản chưa đủ trích dẫn; reviewer đã tự kiểm tra thì gửi "
                        "confirm_needs_review=true",
                    )
                cur.execute(
                    """UPDATE document_drafts SET status='approved',approved_by=%s,
                              approved_at=now(),approval_note=%s,updated_at=now() WHERE id=%s""",
                    (user["id"], body.note, draft_id),
                )
            db.audit(conn, user["id"], "approve_draft", "document_drafts", draft_id, {
                "version": current["current_version"], "grounding_status": grounding,
                "placeholder_count": placeholders,
                "allow_placeholders": body.allow_placeholders,
                "confirm_needs_review": body.confirm_needs_review,
            })
        return _detail(user, draft_id)

    @router.get("/drafts/{draft_id}/export")
    def drafts_export(draft_id: int, format: str = "docx", user=Depends(current_user)):
        detail = _detail(user, draft_id)
        latest = detail["latest_version"]
        if not latest:
            raise HTTPException(409, "Bản nháp chưa có nội dung để xuất")
        fmt = (format or "docx").lower()
        if fmt not in {"docx", "md", "markdown"}:
            raise HTTPException(422, "format chỉ nhận docx hoặc md")
        extension = "docx" if fmt == "docx" else "md"
        filename = drafting.safe_export_name(detail["title"], extension)
        fallback = f"draft_{draft_id}.{extension}"
        disposition = f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename)}"
        if fmt == "docx":
            payload = drafting.render_docx(
                latest["content_markdown"], detail["title"], latest["evidence"]
            )
            media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        else:
            payload = _markdown_with_evidence(
                latest["content_markdown"], latest["evidence"]
            ).encode("utf-8")
            media_type = "text/markdown; charset=utf-8"
        with db.session(role="internal", admin=True) as conn:
            db.audit(conn, user["id"], "export_draft", "document_drafts", draft_id, {
                "version": latest["version_no"], "format": extension, "status": detail["status"],
            })
        return Response(payload, media_type=media_type, headers={
            "Content-Disposition": disposition,
            "X-Draft-Version": str(latest["version_no"]),
            "X-Draft-Status": detail["status"],
        })

    return router
