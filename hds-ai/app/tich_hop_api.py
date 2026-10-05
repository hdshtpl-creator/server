"""tich_hop_api.py — Đường HTTP cho app/tich_hop.py.

Hai nhóm, hai cách xác thực KHÁC NHAU, cố ý không dùng chung:

  /khoa-tich-hop/*   admin đăng nhập web (JWT qua `current_user`) cấp / xem /
                     sửa quyền / thu hồi khoá. Chỉ giao diện quản trị gọi.
  /integration/v1/*  hệ thống ngoài (CRM, chatbot bên thứ ba) gọi bằng khoá
                     `hdsi_…` trong `X-API-Key` hoặc `Authorization: Bearer`.
                     Khoá `hds_` của tài khoản khách gửi vào đây bị 401 — và
                     ngược lại khoá `hdsi_` gửi vào các đường thường cũng 401.

API CÔNG KHAI BẰNG TIẾNG ANH (29/09/2026, chủ dự án: "cho chuyên nghiệp"):
đường dẫn, tên trường, giá trị trạng thái, mã quyền đều tiếng Anh; thông báo
lỗi `detail` và `description` vẫn tiếng Việt cho người dùng cuối đọc. Lõi
nghiệp vụ (tich_hop.py) và CSDL giữ tên tiếng Việt — việc dịch nằm GỌN ở các
hàm `*_en` dưới đây, nên đổi tên trường chỉ sửa một chỗ và test được thuần.

Từng đường khai rõ QUYỀN cần có bằng `can("…")`; thiếu là 403 kèm tên quyền.
Đường theo external_id (/documents/{external_id}/…) còn kiểm thêm quyền theo
LOẠI hồ sơ trong tich_hop.kiem_quyen_loai: tài liệu nhân viên cần employees:read.

(Không dùng `from __future__ import annotations` ở đây: các model Pydantic khai
bên trong build_router là lớp cục bộ, FastAPI không giải được chuỗi chú thích
từ globals của mô-đun và lặng lẽ coi `body` là tham số query → 422.)
"""
import json
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app import kho, tich_hop, xem_truoc

TIEN_TO = "/integration/v1"
# Hồ sơ khách / nhân sự: không để proxy (Cloudflare) hay trình duyệt dùng chung
# giữ bản sao; nosniff để trình duyệt không "đoán" tệp khách thành HTML.
KHONG_LUU = {"Cache-Control": "private, no-store, max-age=0",
             "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"}

# ---------------------------------------------------------------------------
# Dịch sang tiếng Anh ở biên API — thuần, test được không cần CSDL
# ---------------------------------------------------------------------------
STATUS_EN = {"da_nhan": "received", "dang_hoc": "processing", "da_hoc": "learned",
             "cho_duyet": "pending_review", "loi": "failed", "da_go": "removed"}
FILE_STATUS_EN = {"da_hoc": "learned", "canh_bao": "learned_with_warnings",
                  "cho_duyet": "pending_review", "chua_hoc": "not_learned",
                  "loi": "failed", "khong_ho_tro": "unsupported"}
RESULT_EN = {"da_nhan": "created", "phien_ban_moi": "new_version", "khong_doi": "unchanged",
             "da_co_trong_kho": "linked_existing_file", "da_gan_ma": "linked",
             "da_gan_truoc_do": "already_linked", "da_go": "removed",
             "da_go_truoc_do": "already_removed"}
REASON_EN = {"thay_ban": "replaced", "doi_ten": "renamed", "go": "removed"}
OWNER_EN = {"khach": "client", "nhan_vien": "employee"}


def _chon(d: dict, bang: dict) -> dict:
    """Đổi tên khoá theo `bang` {khoá_vi: khoá_en}; chỉ lấy khoá có trong d."""
    return {en: d[vi] for vi, en in bang.items() if vi in d}


def _duong_dan_trong_ho_so(duong_dan_kho: str | None) -> str | None:
    """'9. HỒ SƠ KHÁCH HÀNG/1729. X/Hợp đồng/a.pdf' → 'Hợp đồng/a.pdf' — đường
    dẫn trong hồ sơ, dùng thẳng cho /files/download. Thư mục hồ sơ (khách lẫn
    nhân viên) luôn nằm ở tầng thứ hai của kho."""
    if not duong_dan_kho:
        return None
    parts = [p for p in str(duong_dan_kho).replace("\\", "/").split("/") if p]
    return "/".join(parts[2:]) or None


def document_en(d: dict) -> dict:
    """Trạng thái / kết quả của một tài liệu theo external_id."""
    if d.get("ok") is False and "ket_qua" not in d:
        return {"ok": False, "external_id": d.get("ma_ngoai"), "file_name": d.get("ten_file"),
                "error": d.get("loi"), "status_code": d.get("ma_loi")}
    out = {}
    if "ok" in d:
        out["ok"] = d["ok"]
    if "ket_qua" in d:
        out["result"] = RESULT_EN.get(d["ket_qua"], d["ket_qua"])
    out.update({
        "external_id": d.get("ma_ngoai"),
        "owner_type": OWNER_EN.get(d.get("loai") or "khach"),
        "client_code": d.get("ma_khach"),
        "employee_code": d.get("ma_nhan_vien"),
        "status": STATUS_EN.get(d.get("trang_thai"), d.get("trang_thai")),
        "description": d.get("mo_ta"),
        "file_name": d.get("ten_file"),
        "path": _duong_dan_trong_ho_so(d.get("duong_dan")),
        "storage_path": d.get("duong_dan"),
        "md5": d.get("checksum"),
        "document_id": d.get("document_id"),
        "title": d.get("tieu_de"),
        "unreadable_ratio": d.get("ty_le_rac"),
        "extraction_quality": d.get("chat_luong_doc"),
        "error": d.get("loi"),
        "received_at": d.get("nhan_luc"),
        "updated_at": d.get("cap_nhat_luc"),
    })
    if "phien_ban_luu" in d:
        out["archived_version"] = d["phien_ban_luu"]
    return out


def page_en(d: dict, item_fn) -> dict:
    out = {"items": [item_fn(x) for x in d.get("items") or []], "total": d.get("tong", 0),
           "offset": d.get("offset", 0), "limit": d.get("limit")}
    return out


_CLIENT = {"id": "id", "ma": "code", "ten": "name", "ma_ngoai": "external_id",
           "nguon_ngoai": "source", "department_id": "department_id",
           "phong_phu_trach": "department_name", "created_at": "created_at",
           "so_tai_lieu": "document_count", "so_tai_lieu_da_hoc": "learned_count",
           "thu_muc": "folder", "da_co": "existed"}
_EMPLOYEE = {"id": "id", "ma": "code", "ho_ten": "full_name", "chuc_danh": "title",
             "trang_thai": "status", "active": "active", "ma_ngoai": "external_id",
             "nguon_ngoai": "source", "created_at": "created_at", "thu_muc": "folder",
             "so_tai_lieu": "document_count", "so_tai_lieu_da_hoc": "learned_count",
             "da_co": "existed"}
_FILE = {"duong_dan": "path", "ten_file": "file_name", "thu_muc_con": "subfolder",
         "kich_thuoc": "size", "sua_luc": "modified_at", "trang_thai": "status",
         "document_id": "document_id", "tieu_de": "title", "checksum": "md5",
         "ma_ngoai": "external_id", "loi": "error"}


def client_en(d: dict) -> dict:
    return _chon(d, _CLIENT)


def employee_en(d: dict) -> dict:
    return _chon(d, _EMPLOYEE)


def employee_page_en(d: dict) -> dict:
    out = page_en(d, employee_en)
    out["unassigned_folders"] = [{"name": x.get("ten"), "folder": x.get("thu_muc"),
                                  "file_count": x.get("so_tep")}
                                 for x in d.get("thu_muc_chua_gan") or []]
    return out


def file_en(d: dict) -> dict:
    out = _chon(d, _FILE)
    out["status"] = FILE_STATUS_EN.get(out.get("status"), out.get("status"))
    return out


def files_en(d: dict) -> dict:
    return {"owner_type": OWNER_EN.get(d.get("loai")), "code": d.get("ma"), "name": d.get("ten"),
            "folder": d.get("thu_muc"), "total": d.get("tong", 0),
            "items": [file_en(x) for x in d.get("items") or []]}


def versions_en(d: dict) -> dict:
    return {"external_id": d.get("ma_ngoai"),
            "items": [{"version": x.get("so"), "file_name": x.get("ten_file"),
                       "md5": x.get("checksum"), "size": x.get("kich_thuoc"),
                       "reason": REASON_EN.get(x.get("ly_do"), x.get("ly_do")),
                       "saved_at": x.get("luu_luc"), "current": x.get("hien_tai")}
                      for x in d.get("items") or []]}


def batch_en(d: dict) -> dict:
    return {"ok": d.get("ok"), "code": d.get("ma"), "sent": d.get("so_gui"),
            "accepted": d.get("so_nhan"), "results": [document_en(x) for x in d.get("ket_qua") or []]}


def url_goc(headers, scheme: str = "http") -> str:
    """Địa chỉ công khai của API, để dựng link mà TRÌNH DUYỆT người dùng CRM mở.

    Đặt PUBLIC_API_BASE trong .env nếu cần ép (vd https://app.hdslaw.vn/api).
    Không đặt: nginx giữ nguyên Host của tên miền và cắt tiền tố /api trước khi
    chuyển vào backend, nên link công khai là https://<Host>/api/...; gọi thẳng
    cổng nội bộ (127.0.0.1:8000, test) thì giữ nguyên địa chỉ đó.
    """
    env = (os.getenv("PUBLIC_API_BASE") or "").strip().rstrip("/")
    if env:
        return env
    host = (headers.get("x-forwarded-host") or headers.get("host") or "127.0.0.1:8000").split(",")[0].strip()
    if host.split(":")[0] in ("127.0.0.1", "localhost", "0.0.0.0", "testserver"):
        return f"{scheme}://{host}"
    return f"https://{host}/api"


def build_router(current_user, require, get_user, tra_loi_khach, max_upload_mb: int = 50) -> APIRouter:
    router = APIRouter()

    def _hoac_http(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except tich_hop.LoiTichHop as e:
            raise HTTPException(e.status, str(e))
        except kho.LoiKho as e:
            raise HTTPException(400, str(e))

    def _tra_tep(path, ten, md5=None):
        """Tệp gốc nguyên byte. Tên tiếng Việt đi qua filename* (RFC 5987) do
        Starlette tự mã hoá; md5 trong header để bên gọi tự kiểm toàn vẹn."""
        headers = dict(KHONG_LUU)
        if md5:
            headers["X-Checksum-MD5"] = md5
        return FileResponse(str(path), filename=ten, headers=headers,
                            media_type="application/octet-stream")

    def _phat_xem(path):
        """Xem thẳng trong trình duyệt: PDF / ảnh / văn bản trả nguyên, Word /
        Excel đổi sang PDF (xem_truoc). Loại khác → 415 kèm gợi ý tải về."""
        try:
            tep, media, ten = xem_truoc.ban_xem(path)
        except xem_truoc.LoiXemTruoc as e:
            raise HTTPException(e.status, str(e))
        return FileResponse(str(tep), media_type=media, filename=ten, headers=dict(KHONG_LUU),
                            content_disposition_type="inline")

    def _link(request, khoa, dich, che_do="preview", ttl=None):
        l = tich_hop.tao_link(khoa, dich, che_do, ttl)
        return {"url": f"{url_goc(request.headers, request.url.scheme)}{TIEN_TO}/view/{l['token']}",
                "mode": l["che_do"], "expires_in": l["ttl"],
                "expires_at": datetime.fromtimestamp(l["het_han"], tz=timezone.utc).isoformat()}

    # ------------------------------------------------------------------
    # Quản trị khoá — chỉ admin, đăng nhập web (giao diện nội bộ gọi)
    # ------------------------------------------------------------------
    @router.get("/khoa-tich-hop/quyen", tags=["integration-admin"])
    def khoa_quyen(user=Depends(current_user)):
        """Danh sách quyền + bộ quyền mẫu để giao diện vẽ ô tick."""
        require(user, {"admin"})
        return {"quyen": [{"ma": k, **v} for k, v in tich_hop.QUYEN.items()],
                "bo_mau": [{"ma": k, **v} for k, v in tich_hop.BO_QUYEN_MAU.items()],
                "tien_to": tich_hop.TIEN_TO_KHOA}

    @router.get("/khoa-tich-hop", tags=["integration-admin"])
    def khoa_danh_sach(user=Depends(current_user)):
        require(user, {"admin"})
        return tich_hop.danh_sach_khoa()

    class KhoaMoi(BaseModel):
        ten: str
        nguon: str
        quyen: list[str]
        user_id: int | None = None
        ghi_chu: str | None = None

    @router.post("/khoa-tich-hop", tags=["integration-admin"])
    def khoa_tao(body: KhoaMoi, user=Depends(current_user)):
        """Cấp khoá. Khoá thật chỉ có trong kết quả lần này."""
        require(user, {"admin"})
        return _hoac_http(tich_hop.tao_khoa, body.ten, body.nguon, body.quyen,
                          user_id=body.user_id, ghi_chu=body.ghi_chu, created_by=user["id"])

    class KhoaSua(BaseModel):
        quyen: list[str] | None = None
        ten: str | None = None
        # Gửi doi_user=true mới đổi tài khoản đại diện (kể cả về null).
        user_id: int | None = None
        doi_user: bool = False

    @router.patch("/khoa-tich-hop/{khoa_id}", tags=["integration-admin"])
    def khoa_sua(khoa_id: int, body: KhoaSua, user=Depends(current_user)):
        """Sửa quyền / tên của khoá đang dùng — chuỗi khoá giữ nguyên."""
        require(user, {"admin"})
        return _hoac_http(tich_hop.sua_khoa, khoa_id, quyen=body.quyen, ten=body.ten,
                          user_id=body.user_id, doi_user=body.doi_user, by=user["id"])

    @router.delete("/khoa-tich-hop/{khoa_id}", tags=["integration-admin"])
    def khoa_thu_hoi(khoa_id: int, user=Depends(current_user)):
        require(user, {"admin"})
        return _hoac_http(tich_hop.thu_hoi_khoa, khoa_id, user["id"])

    # ------------------------------------------------------------------
    # API công khai — /integration/v1/*
    # ------------------------------------------------------------------
    def khoa_hien_tai(x_api_key: str | None = Header(default=None, alias="X-API-Key"),
                      authorization: str | None = Header(default=None)) -> dict:
        raw = x_api_key
        if not raw and authorization and authorization.lower().startswith("bearer "):
            raw = authorization[7:].strip()
        if not raw:
            raise HTTPException(401, "Thiếu khoá: gửi header X-API-Key hoặc Authorization: Bearer")
        if not tich_hop.la_khoa_tich_hop(raw):
            raise HTTPException(401, f"Khoá này không phải khoá tích hợp ({tich_hop.TIEN_TO_KHOA}…)")
        khoa = tich_hop.xac_thuc_khoa(raw)
        if not khoa:
            raise HTTPException(401, "Khoá tích hợp không hợp lệ hoặc đã bị thu hồi")
        tich_hop.khoi_phuc_hang_doi_mot_lan()
        return khoa

    def can(*ds_quyen: str):
        def _kiem(khoa: dict = Depends(khoa_hien_tai)) -> dict:
            for quyen in ds_quyen:
                if not tich_hop.co_quyen(khoa, quyen):
                    ten = tich_hop.QUYEN.get(quyen, {}).get("ten", quyen)
                    raise HTTPException(403, f"Khoá này không có quyền '{quyen}' ({ten})")
            return khoa
        return _kiem

    def _loai_duoc_xem(khoa: dict) -> list:
        return [loai for loai, v in tich_hop.LOAI_CHU.items() if tich_hop.co_quyen(khoa, v["quyen"])]

    T = ["integration"]

    @router.get(f"{TIEN_TO}/me", tags=T)
    def me(khoa: dict = Depends(khoa_hien_tai)):
        """Who this key is and what it may do — call first to test the connection."""
        return {"ok": True, "name": khoa["ten"], "source": khoa["nguon"],
                "permissions": khoa["quyen"], "has_chat_account": bool(khoa.get("user_id")),
                "queued": tich_hop.so_dang_cho()}

    # ---- Dùng chung cho khách và nhân viên ----
    def _ds_external_id(external_id: list[str], so_tep: int) -> list[str] | None:
        """Hai kiểu: trường lặp `external_id=a&external_id=b` hoặc MỘT chuỗi
        JSON '["a","b"]'. Rỗng = máy chủ tự đặt theo mã hồ sơ + tên tệp."""
        ds = [x for x in (external_id or []) if x is not None]
        if len(ds) == 1 and ds[0].strip().startswith("["):
            try:
                ds = [str(x) for x in json.loads(ds[0])]
            except ValueError:
                raise HTTPException(400, "external_id không phải JSON hợp lệ")
        if not ds:
            return None
        if len(ds) != so_tep:
            raise HTTPException(400, f"external_id có {len(ds)} phần tử nhưng gửi {so_tep} tệp — "
                                     "mỗi tệp một external_id, cùng thứ tự")
        return ds

    def _metadata(metadata: str):
        if not (metadata or "").strip():
            return None
        try:
            d = json.loads(metadata)
        except ValueError:
            raise HTTPException(400, "metadata phải là JSON")
        if not isinstance(d, dict):
            raise HTTPException(400, "metadata phải là một đối tượng JSON")
        return d

    async def _gui_bo(request, khoa, ma, files, external_id, folder, metadata, nhan_fn):
        if len(files) > tich_hop.SO_TEP_MOT_LAN:
            raise HTTPException(400, f"Mỗi lần tối đa {tich_hop.SO_TEP_MOT_LAN} tệp")
        ds_ma = _ds_external_id(external_id, len(files))
        meta_d = _metadata(metadata)
        ket_qua = []
        for i, f in enumerate(files):
            ten = f.filename or ""
            mn = ds_ma[i] if ds_ma else tich_hop.ma_ngoai_mac_dinh(ma, ten)
            try:
                noi_dung = await f.read()
            finally:
                await f.close()
            try:
                r = nhan_fn(khoa, ma, mn, ten, noi_dung, thu_muc_con=folder,
                            meta=meta_d, gioi_han_mb=max_upload_mb)
            except (tich_hop.LoiTichHop, kho.LoiKho) as e:
                r = {"ok": False, "ma_ngoai": mn, "ten_file": ten, "loi": str(e),
                     "ma_loi": getattr(e, "status", 400)}
            ket_qua.append(r)
        out = batch_en({"ok": all(x.get("ok") for x in ket_qua), "ma": ma,
                        "so_gui": len(ket_qua), "so_nhan": sum(1 for x in ket_qua if x.get("ok")),
                        "ket_qua": ket_qua})
        # "Tải lên xong là xem được ngay": mỗi tệp nhận kèm link xem tạm.
        for x in out["results"]:
            if x.get("ok") and x.get("external_id") and x.get("file_name") \
                    and xem_truoc.xem_duoc(__import__("pathlib").Path(x["file_name"])):
                l = _link(request, khoa, {"x": x["external_id"]})
                x["preview_url"], x["preview_expires_at"] = l["url"], l["expires_at"]
        return out

    class LinkIn(BaseModel):
        path: str
        external_id: str
        metadata: dict | None = None

    def _tep_kem_link(request, khoa, chu, with_links):
        out = files_en(_hoac_http(tich_hop.liet_ke_tep, chu, khoa["nguon"]))
        if with_links:
            for x in out["items"]:
                dich = {"o": chu["loai"], "c": chu["ma"], "p": x["path"]}
                if xem_truoc.xem_duoc(__import__("pathlib").Path(x["file_name"])):
                    x["preview_url"] = _link(request, khoa, dich)["url"]
                x["download_url"] = _link(request, khoa, dich, "download")["url"]
        return out

    class ViewLinkIn(BaseModel):
        mode: str = "preview"
        expires_in: int | None = None

    class FileViewLinkIn(ViewLinkIn):
        path: str

    def _xin_link(request, khoa, dich, body):
        body = body or ViewLinkIn()
        p, _ten, _md5 = _hoac_http(tich_hop.tep_theo_dich, khoa, dich)
        if body.mode == "preview" and not xem_truoc.xem_duoc(p):
            raise HTTPException(415, f"Định dạng {p.suffix or '(không đuôi)'} chưa xem thẳng được — "
                                     "xin link với mode=download")
        return _hoac_http(_link, request, khoa, dich, body.mode, body.expires_in)

    def _xem_trong(khoa, chu, path):
        if chu["thu_muc"] is None:
            raise HTTPException(404, "Hồ sơ chưa có thư mục trên máy chủ")
        p = _hoac_http(tich_hop.duong_dan_trong, chu["thu_muc"], path)
        tich_hop.ghi_nhat_ky_xem(khoa, {"o": chu["loai"], "c": chu["ma"], "p": path}, "preview", False)
        return _phat_xem(p)

    def _tai_ve_trong(chu, path):
        if chu["thu_muc"] is None:
            raise HTTPException(404, "Hồ sơ chưa có thư mục trên máy chủ")
        p = _hoac_http(tich_hop.duong_dan_trong, chu["thu_muc"], path)
        return _tra_tep(p, p.name)

    # ---- Clients ----
    @router.get(f"{TIEN_TO}/clients", tags=T)
    def clients_list(q: str = "", external_id: str = "", offset: int = 0, limit: int = 100,
                     khoa: dict = Depends(can("clients:read"))):
        """All clients (newest code first, paginated) or search with `q`."""
        d = _hoac_http(tich_hop.tim_khach, q=(q or "")[:200], ma_ngoai=(external_id or "")[:100],
                       nguon=khoa["nguon"], offset=max(0, offset), limit=max(1, min(limit, 500)))
        return page_en(d, client_en)

    class ClientIn(BaseModel):
        name: str
        code: str | None = None
        external_id: str | None = None

    @router.post(f"{TIEN_TO}/clients", tags=T)
    def clients_create(body: ClientIn, khoa: dict = Depends(can("clients:write"))):
        """Create a client. With `code`: use it (existing → returned, `existed`=true).
        Without: the server assigns the next code."""
        return client_en(_hoac_http(tich_hop.tao_khach, body.name, ma=body.code,
                                    ma_ngoai=body.external_id, nguon=khoa["nguon"],
                                    khoa_id=khoa["id"]))

    @router.get(f"{TIEN_TO}/clients/{{code}}", tags=T)
    def clients_get(code: str, khoa: dict = Depends(can("clients:read"))):
        k = _hoac_http(tich_hop.khach_theo_ma, code)
        if not k:
            raise HTTPException(404, f"Không có khách mã '{code}'")
        return client_en(k)

    @router.get(f"{TIEN_TO}/clients/{{code}}/files", tags=T)
    def clients_files(code: str, request: Request, with_links: bool = False,
                      khoa: dict = Depends(can("clients:read", "documents:read"))):
        """EVERY file in the client's folder on the server, including legacy files.
        `with_links=true`: each file also gets `preview_url` / `download_url`."""
        chu = _hoac_http(tich_hop.chu_khach, code, tao_thu_muc=False)
        return _tep_kem_link(request, khoa, chu, with_links)

    @router.get(f"{TIEN_TO}/clients/{{code}}/files/download", tags=T)
    def clients_file_download(code: str, path: str,
                              khoa: dict = Depends(can("clients:read", "documents:read"))):
        """Download one original file by its `path` (from /files)."""
        return _tai_ve_trong(_hoac_http(tich_hop.chu_khach, code, tao_thu_muc=False), path)

    @router.post(f"{TIEN_TO}/clients/{{code}}/files/link", tags=T)
    def clients_file_link(code: str, body: LinkIn,
                          khoa: dict = Depends(can("clients:read", "documents:write"))):
        """Attach your `external_id` to an existing file."""
        chu = _hoac_http(tich_hop.chu_khach, code, tao_thu_muc=False)
        return document_en(_hoac_http(tich_hop.gan_ma, khoa, chu, body.path, body.external_id,
                                      body.metadata))

    @router.post(f"{TIEN_TO}/clients/{{code}}/documents", tags=T)
    async def clients_upload(code: str, request: Request, files: list[UploadFile] = File(...),
                             external_id: list[str] = Form(default=[]), folder: str = Form(""),
                             metadata: str = Form(""),
                             khoa: dict = Depends(can("clients:read", "documents:write"))):
        """Upload one file or a whole set (multipart, ≤50 files). Learning runs in
        the background — poll GET /documents/{external_id}."""
        return await _gui_bo(request, khoa, code, files, external_id, folder, metadata,
                             tich_hop.nhan_tai_lieu)

    @router.get(f"{TIEN_TO}/clients/{{code}}/documents", tags=T)
    def clients_documents(code: str, updated_since: str = "", offset: int = 0, limit: int = 200,
                          khoa: dict = Depends(can("clients:read", "documents:read"))):
        """Documents of a client that carry an external_id."""
        d = _hoac_http(tich_hop.danh_sach_tai_lieu, khoa["nguon"], ma_khach=code,
                       tu_luc=(updated_since or "").strip()[:40] or None,
                       offset=max(0, offset), limit=max(1, min(limit, 1000)),
                       loai_duoc_xem=["khach"])
        return page_en(d, document_en)

    # ---- Employees ----
    @router.get(f"{TIEN_TO}/employees", tags=T)
    def employees_list(q: str = "", external_id: str = "", offset: int = 0, limit: int = 100,
                       khoa: dict = Depends(can("employees:read"))):
        """Employees + `unassigned_folders`: existing staff folders not yet bound
        to an employee (bind with POST /employees and `folder`)."""
        d = _hoac_http(tich_hop.tim_nhan_vien, q=(q or "")[:200],
                       ma_ngoai=(external_id or "")[:100], nguon=khoa["nguon"],
                       offset=max(0, offset), limit=max(1, min(limit, 500)))
        return employee_page_en(d)

    class EmployeeIn(BaseModel):
        full_name: str
        code: str | None = None
        title: str | None = None
        status: str | None = None
        external_id: str | None = None
        folder: str | None = None

    @router.post(f"{TIEN_TO}/employees", tags=T)
    def employees_upsert(body: EmployeeIn, khoa: dict = Depends(can("employees:write"))):
        """Create or update an employee by `code`; without `code` the server
        assigns NVxxxx. `folder` = an existing staff folder to take over."""
        return employee_en(_hoac_http(tich_hop.tao_nhan_vien, body.full_name, ma_nv=body.code,
                                      chuc_danh=body.title, trang_thai_nv=body.status,
                                      ma_ngoai=body.external_id, thu_muc=body.folder,
                                      nguon=khoa["nguon"], khoa_id=khoa["id"]))

    @router.get(f"{TIEN_TO}/employees/{{code}}", tags=T)
    def employees_get(code: str, khoa: dict = Depends(can("employees:read"))):
        nv = _hoac_http(tich_hop.nhan_vien_theo_ma, code)
        if not nv:
            raise HTTPException(404, f"Không có nhân viên mã '{code}'")
        return employee_en(nv)

    @router.get(f"{TIEN_TO}/employees/{{code}}/files", tags=T)
    def employees_files(code: str, request: Request, with_links: bool = False,
                        khoa: dict = Depends(can("employees:read", "documents:read"))):
        chu = _hoac_http(tich_hop.chu_nhan_vien, code, tao_thu_muc=False)
        return _tep_kem_link(request, khoa, chu, with_links)

    @router.get(f"{TIEN_TO}/employees/{{code}}/files/download", tags=T)
    def employees_file_download(code: str, path: str,
                                khoa: dict = Depends(can("employees:read", "documents:read"))):
        return _tai_ve_trong(_hoac_http(tich_hop.chu_nhan_vien, code, tao_thu_muc=False), path)

    @router.post(f"{TIEN_TO}/employees/{{code}}/files/link", tags=T)
    def employees_file_link(code: str, body: LinkIn,
                            khoa: dict = Depends(can("employees:read", "documents:write"))):
        chu = _hoac_http(tich_hop.chu_nhan_vien, code, tao_thu_muc=False)
        return document_en(_hoac_http(tich_hop.gan_ma, khoa, chu, body.path, body.external_id,
                                      body.metadata))

    @router.post(f"{TIEN_TO}/employees/{{code}}/documents", tags=T)
    async def employees_upload(code: str, request: Request, files: list[UploadFile] = File(...),
                               external_id: list[str] = Form(default=[]), folder: str = Form(""),
                               metadata: str = Form(""),
                               khoa: dict = Depends(can("employees:read", "documents:write"))):
        return await _gui_bo(request, khoa, code, files, external_id, folder, metadata,
                             tich_hop.nhan_tai_lieu_nhan_vien)

    @router.get(f"{TIEN_TO}/employees/{{code}}/documents", tags=T)
    def employees_documents(code: str, updated_since: str = "", offset: int = 0, limit: int = 200,
                            khoa: dict = Depends(can("employees:read", "documents:read"))):
        d = _hoac_http(tich_hop.danh_sach_tai_lieu, khoa["nguon"], ma_nv=code,
                       tu_luc=(updated_since or "").strip()[:40] or None,
                       offset=max(0, offset), limit=max(1, min(limit, 1000)),
                       loai_duoc_xem=["nhan_vien"])
        return page_en(d, document_en)

    # ---- Documents by external_id (client or employee) ----
    @router.get(f"{TIEN_TO}/documents", tags=T)
    def documents_list(client_code: str = "", employee_code: str = "", updated_since: str = "",
                       offset: int = 0, limit: int = 200,
                       khoa: dict = Depends(can("documents:read"))):
        """Reconciliation across the whole source. `updated_since` (ISO 8601):
        only rows changed since then, including approvals done on the web."""
        d = _hoac_http(tich_hop.danh_sach_tai_lieu, khoa["nguon"],
                       ma_khach=(client_code or "").strip() or None,
                       ma_nv=(employee_code or "").strip() or None,
                       tu_luc=(updated_since or "").strip()[:40] or None,
                       offset=max(0, offset), limit=max(1, min(limit, 1000)),
                       loai_duoc_xem=_loai_duoc_xem(khoa))
        return page_en(d, document_en)

    @router.get(f"{TIEN_TO}/documents/{{external_id}}", tags=T)
    def documents_get(external_id: str, khoa: dict = Depends(can("documents:read"))):
        return document_en(_hoac_http(tich_hop.trang_thai, khoa["nguon"], external_id, khoa))

    @router.get(f"{TIEN_TO}/documents/{{external_id}}/download", tags=T)
    def documents_download(external_id: str, khoa: dict = Depends(can("documents:read"))):
        """The current original file (byte-exact, with X-Checksum-MD5)."""
        p, ten, md5 = _hoac_http(tich_hop.tep_hien_tai, khoa["nguon"], external_id, khoa)
        return _tra_tep(p, ten, md5)

    @router.get(f"{TIEN_TO}/documents/{{external_id}}/versions", tags=T)
    def documents_versions(external_id: str, khoa: dict = Depends(can("documents:read"))):
        """Every archived version plus the current one (`current`=true)."""
        return versions_en(_hoac_http(tich_hop.danh_sach_phien_ban, khoa["nguon"], external_id, khoa))

    @router.get(f"{TIEN_TO}/documents/{{external_id}}/versions/{{version}}/download", tags=T)
    def documents_version_download(external_id: str, version: int,
                                   khoa: dict = Depends(can("documents:read"))):
        p, ten, md5 = _hoac_http(tich_hop.tep_phien_ban, khoa["nguon"], external_id, version, khoa)
        return _tra_tep(p, ten, md5)

    @router.delete(f"{TIEN_TO}/documents/{{external_id}}", tags=T)
    def documents_delete(external_id: str, khoa: dict = Depends(can("documents:delete"))):
        """Remove: the assistant stops using it at once; the last version is archived."""
        return document_en(_hoac_http(tich_hop.go, khoa["nguon"], external_id, khoa))

    # ---- Xem thẳng trong trình duyệt (01/10/2026) ----
    @router.get(f"{TIEN_TO}/documents/{{external_id}}/preview", tags=T)
    def documents_preview(external_id: str, khoa: dict = Depends(can("documents:read"))):
        """View inline: PDF/images/text as-is, Word/Excel converted to PDF."""
        p, _ten, _md5 = _hoac_http(tich_hop.tep_hien_tai, khoa["nguon"], external_id, khoa)
        tich_hop.ghi_nhat_ky_xem(khoa, {"x": external_id}, "preview", False)
        return _phat_xem(p)

    @router.get(f"{TIEN_TO}/clients/{{code}}/files/preview", tags=T)
    def clients_file_preview(code: str, path: str,
                             khoa: dict = Depends(can("clients:read", "documents:read"))):
        return _xem_trong(khoa, _hoac_http(tich_hop.chu_khach, code, tao_thu_muc=False), path)

    @router.get(f"{TIEN_TO}/employees/{{code}}/files/preview", tags=T)
    def employees_file_preview(code: str, path: str,
                               khoa: dict = Depends(can("employees:read", "documents:read"))):
        return _xem_trong(khoa, _hoac_http(tich_hop.chu_nhan_vien, code, tao_thu_muc=False), path)

    @router.post(f"{TIEN_TO}/documents/{{external_id}}/view-link", tags=T)
    def documents_view_link(external_id: str, request: Request, body: ViewLinkIn | None = None,
                            khoa: dict = Depends(can("documents:read"))):
        """Short-lived signed URL the END USER's browser opens directly (no key).
        `mode`: preview (default) | download; `expires_in`: 60–3600 s (default 600)."""
        return _xin_link(request, khoa, {"x": external_id}, body)

    @router.post(f"{TIEN_TO}/clients/{{code}}/files/view-link", tags=T)
    def clients_file_view_link(code: str, body: FileViewLinkIn, request: Request,
                               khoa: dict = Depends(can("clients:read", "documents:read"))):
        chu = _hoac_http(tich_hop.chu_khach, code, tao_thu_muc=False)
        return _xin_link(request, khoa, {"o": "khach", "c": chu["ma"], "p": body.path}, body)

    @router.post(f"{TIEN_TO}/employees/{{code}}/files/view-link", tags=T)
    def employees_file_view_link(code: str, body: FileViewLinkIn, request: Request,
                                 khoa: dict = Depends(can("employees:read", "documents:read"))):
        chu = _hoac_http(tich_hop.chu_nhan_vien, code, tao_thu_muc=False)
        return _xin_link(request, khoa, {"o": "nhan_vien", "c": chu["ma"], "p": body.path}, body)

    @router.get(f"{TIEN_TO}/view/{{token}}", tags=T)
    def view(token: str):
        """Open a signed link — NO API key: the link itself is the permission.
        Checked on every open: signature, expiry, and that the key which issued
        it is still active and still has the permissions."""
        khoa, payload, p, ten, md5 = _hoac_http(tich_hop.mo_link, token)
        tich_hop.ghi_nhat_ky_xem(khoa, payload, payload.get("m"), True)
        if payload.get("m") == "download":
            return _tra_tep(p, ten, md5)
        return _phat_xem(p)

    # ---- Chat (third-party chatbot) ----
    class ChatIn(BaseModel):
        question: str
        conversation_id: int | None = None
        # Để dùng chung lõi với /chat/portal; mặc định tắt.
        use_temp: bool = False
        source_document_ids: list[int] | None = None

    @router.post(f"{TIEN_TO}/chat", tags=T)
    def chat(body: ChatIn, khoa: dict = Depends(can("chat"))):
        """Ask the assistant as the client account bound to this key: same quota,
        same enabled features and same data boundary as that client."""
        if not khoa.get("user_id"):
            raise HTTPException(403, "Khoá chưa gắn tài khoản khách đại diện — admin sửa khoá")
        user = get_user(khoa["user_id"])
        return tra_loi_khach(body, user)

    return router
