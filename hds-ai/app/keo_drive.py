"""keo_drive.py — kéo nguyên một thư mục Google Drive về máy chủ.

07/10/2026: chủ dự án đưa bộ hồ sơ khách mới lên Drive và muốn thay bộ cũ trên
máy chủ. Kho đã bỏ Drive từ 27/08 (local_learn quét thư mục), nên đây chỉ là
công cụ TẢI VỀ một lần — không đồng bộ, không đụng CSDL, không đụng kho:

    python -m app.keo_drive <id thư mục Drive> --chi-liet-ke
    python -m app.keo_drive <id thư mục Drive> <thư mục đích>

Thư mục Drive phải được chia sẻ (Người xem) cho email tài khoản dịch vụ trong
credentials/service-account.json — chạy --chi-liet-ke để biết email đó.

  · Tải vào `.<tên>.part` rồi mới đổi tên (tệp bắt đầu bằng '.' bộ quét kho bỏ
    qua), kiểm md5 với md5Checksum của Drive; sai md5 là tải lại.
  · Chạy lại được: tệp đã có đúng kích thước + md5 thì bỏ qua.
  · Google Docs/Sheets/Slides → .docx/.xlsx/.pdf (bộ học không đọc định dạng
    gốc của Google); Form, lối tắt… ghi vào danh sách bỏ qua.
  · Tên tệp: chuẩn hoá NFC (tên tải lên từ Mac là NFD — regex mã khách và bản
    đồ nhãn so theo NFC), '/' trong tên đổi thành '-', trùng tên trong cùng thư
    mục thêm " (2)".
  · mtime đặt theo modifiedTime của Drive.
  · Nhật ký đầy đủ ở <thư mục đích>.keo_drive.json (bên CẠNH, không nằm trong).
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import random
import re
import sys
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

FOLDER = "application/vnd.google-apps.folder"
SHORTCUT = "application/vnd.google-apps.shortcut"
XUAT_GOOGLE = {
    "application/vnd.google-apps.document":
        (".docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    "application/vnd.google-apps.spreadsheet":
        (".xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    "application/vnd.google-apps.presentation": (".pdf", "application/pdf"),
    "application/vnd.google-apps.drawing": (".pdf", "application/pdf"),
}
TRUONG = "id,name,mimeType,size,md5Checksum,modifiedTime"
SA_MAC_DINH = "credentials/service-account.json"
TOI_DA_BYTE_TEN = 240  # ext4 giới hạn 255 byte/tên; chừa chỗ cho " (2)" và .part
_KY_TU_TRANG_LA = re.compile("[ ]*[\t\r\n\x0b\x0c ​‌‍﻿]+[ ]*")


def ten_an_toan(ten: str) -> str:
    ten = unicodedata.normalize("NFC", ten).replace("/", "-").replace("\0", "")
    # 07/10: 20 thư mục khách trên Drive có TAB ẩn sau mã ("1193. \tPhương Thuý")
    # — dán từ bảng tính. Ký tự trắng lạ (TAB, xuống dòng, NBSP, zero-width)
    # gộp thành MỘT dấu cách; hai dấu cách thường giữ nguyên như Drive.
    ten = _KY_TU_TRANG_LA.sub(" ", ten)
    ten = ten.strip() or "_"
    if ten in (".", ".."):
        ten = "_" + ten
    if len(ten.encode("utf-8")) > TOI_DA_BYTE_TEN:
        goc, duoi = os.path.splitext(ten)
        if len(duoi.encode("utf-8")) > 20:
            goc, duoi = ten, ""
        while len((goc + duoi).encode("utf-8")) > TOI_DA_BYTE_TEN:
            goc = goc[:-1]
        ten = goc.rstrip() + duoi
    return ten


def ten_khong_trung(ten: str, da_dung: set) -> str:
    """Drive cho phép hai TỆP trùng tên trong một thư mục, đĩa thì không."""
    if ten.casefold() not in da_dung:
        da_dung.add(ten.casefold())
        return ten
    goc, duoi = os.path.splitext(ten)
    if len(duoi) > 8 or " " in duoi:  # "HĐ số 1. Bản cuối" không có đuôi thật
        goc, duoi = ten, ""
    n = 2
    while f"{goc} ({n}){duoi}".casefold() in da_dung:
        n += 1
    moi = f"{goc} ({n}){duoi}"
    da_dung.add(moi.casefold())
    return moi


def _dich_vu(sa_file: str):
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    creds = service_account.Credentials.from_service_account_file(
        sa_file, scopes=["https://www.googleapis.com/auth/drive.readonly"])
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _thu_lai(viec, lan=6):
    """Gọi API, lùi lại khi Drive báo bận (429/5xx) hoặc mạng chập chờn."""
    from googleapiclient.errors import HttpError
    for i in range(lan):
        try:
            return viec()
        except HttpError as exc:
            ma = getattr(exc.resp, "status", 0)
            if ma not in (403, 429, 500, 502, 503, 504) or i == lan - 1:
                raise
            if ma == 403 and b"ateLimit" not in (exc.content or b""):
                raise
        except (OSError, TimeoutError):
            if i == lan - 1:
                raise
        time.sleep(min(60, 2 ** i + random.random()))


def con_cua(svc, folder_id):
    out, tok = [], None
    while True:
        r = _thu_lai(lambda: svc.files().list(
            q=f"'{folder_id}' in parents and trashed=false", pageSize=1000, pageToken=tok,
            fields=f"nextPageToken,files({TRUONG})", orderBy="name",
            supportsAllDrives=True, includeItemsFromAllDrives=True).execute())
        out += r.get("files", [])
        tok = r.get("nextPageToken")
        if not tok:
            return out


def liet_ke(sa_file, goc_id, luong=8):
    """[(đường dẫn tương đối, mục Drive)], [(đường dẫn, lý do bỏ qua)], [thư mục].

    Mỗi thư mục là một lượt gọi API; 07/10 bộ hồ sơ khách hơn chục nghìn thư
    mục, hỏi tuần tự mất quá 10 phút — nên hỏi song song `luong` thư mục.

    Hai THƯ MỤC trùng tên dưới cùng một cha (Drive có "1160. … AN PHÚC" hai
    lần) được GỘP làm một, như khi giải nén bản export Drive. Hai TỆP trùng
    tên trên đĩa thì tệp sau thêm " (2)" — thứ tự cố định theo (modifiedTime,
    id) chứ không theo thứ tự API trả về, để chạy lại ra đúng tên cũ."""
    from concurrent.futures import FIRST_COMPLETED, wait
    tho, bo_qua, thu_muc = [], [], set()
    with ThreadPoolExecutor(max_workers=max(1, luong)) as ex:
        dang = {ex.submit(lambda fid: con_cua(_svc_luong(sa_file), fid), goc_id): ()}
        while dang:
            xong, _ = wait(dang, return_when=FIRST_COMPLETED)
            for fut in xong:
                cha = dang.pop(fut)
                for f in fut.result():
                    mime = f["mimeType"]
                    ten = ten_an_toan(f["name"])
                    if mime in XUAT_GOOGLE and not ten.lower().endswith(XUAT_GOOGLE[mime][0]):
                        ten += XUAT_GOOGLE[mime][0]
                    duong = cha + (ten,)
                    if mime == FOLDER:
                        thu_muc.add("/".join(duong))
                        if len(thu_muc) % 1000 == 0:
                            print(f"  … {len(thu_muc)} thư mục, {len(tho)} tệp", flush=True)
                        dang[ex.submit(lambda fid: con_cua(_svc_luong(sa_file), fid),
                                       f["id"])] = duong
                    elif mime == SHORTCUT:
                        bo_qua.append(("/".join(duong), "lối tắt (shortcut) — không theo"))
                    elif mime.startswith("application/vnd.google-apps.") and mime not in XUAT_GOOGLE:
                        bo_qua.append(("/".join(duong), f"định dạng Google không xuất được ({mime})"))
                    else:
                        tho.append(("/".join(cha), ten, f))
    # Đặt tên tệp trên đĩa sau khi có ĐỦ cây: tên thư mục con chiếm chỗ trước.
    da_dung = {}
    for d in thu_muc:
        cha, _, ten = d.rpartition("/")
        da_dung.setdefault(cha, set()).add(ten.casefold())
    tep = []
    for cha, ten, f in sorted(tho, key=lambda x: (x[0], x[1].casefold(),
                                                  x[2].get("modifiedTime") or "", x[2]["id"])):
        ten = ten_khong_trung(ten, da_dung.setdefault(cha, set()))
        tep.append((f"{cha}/{ten}" if cha else ten, f))
    tep.sort(key=lambda x: x[0])
    return tep, bo_qua, sorted(thu_muc)


def md5_tep(p: Path) -> str:
    h = hashlib.md5()
    with p.open("rb") as fh:
        for khoi in iter(lambda: fh.read(1 << 20), b""):
            h.update(khoi)
    return h.hexdigest()


def _dat_mtime(p: Path, modified: str | None):
    if not modified:
        return
    try:
        t = datetime.fromisoformat(modified.replace("Z", "+00:00")).timestamp()
        os.utime(p, (t, t))
    except (ValueError, OSError):
        pass


_rieng = threading.local()


def _svc_luong(sa_file):
    # httplib2 không an toàn đa luồng — mỗi luồng một đối tượng dịch vụ.
    if getattr(_rieng, "svc", None) is None:
        _rieng.svc = _dich_vu(sa_file)
    return _rieng.svc


def tai_mot(sa_file, f, dich: Path) -> str:
    """'co_san' | 'tai' | 'xuat' — ném lỗi nếu hỏng sau khi thử lại."""
    from googleapiclient.http import MediaIoBaseDownload
    mime = f["mimeType"]
    md5 = f.get("md5Checksum")
    co = int(f["size"]) if f.get("size") else None
    if dich.exists() and mime not in XUAT_GOOGLE:
        if (co is None or dich.stat().st_size == co) and (not md5 or md5_tep(dich) == md5):
            return "co_san"
    if dich.exists() and mime in XUAT_GOOGLE:
        return "co_san"  # bản xuất không có md5 để so; muốn xuất lại thì xoá tệp
    dich.parent.mkdir(parents=True, exist_ok=True)
    tam = dich.with_name("." + dich.name[:200] + ".part")
    svc = _svc_luong(sa_file)
    for lan in range(4):
        if mime in XUAT_GOOGLE:
            req = svc.files().export_media(fileId=f["id"], mimeType=XUAT_GOOGLE[mime][1])
        else:
            req = svc.files().get_media(fileId=f["id"], supportsAllDrives=True)
        try:
            with tam.open("wb") as fh:
                dl = MediaIoBaseDownload(fh, req, chunksize=32 << 20)
                xong = False
                while not xong:
                    _, xong = _thu_lai(lambda: dl.next_chunk(num_retries=3))
        except Exception:
            tam.unlink(missing_ok=True)
            if lan == 3:
                raise
            time.sleep(2 ** lan)
            continue
        if md5 and md5_tep(tam) != md5:
            tam.unlink(missing_ok=True)
            if lan == 3:
                raise RuntimeError("md5 không khớp sau 4 lần tải")
            continue
        os.replace(tam, dich)
        _dat_mtime(dich, f.get("modifiedTime"))
        return "xuat" if mime in XUAT_GOOGLE else "tai"
    raise RuntimeError("không tải được")


def tom_tat(tep, bo_qua, so_thu_muc, in_ra=print):
    tong = sum(int(f.get("size") or 0) for _, f in tep)
    in_ra(f"{so_thu_muc} thư mục · {len(tep)} tệp · {tong / 1e9:.2f} GB · {len(bo_qua)} bỏ qua")
    cap1 = collections.Counter(p.split("/")[0] if "/" in p else "(gốc)" for p, _ in tep)
    in_ra(f"Cấp 1: {len(cap1)} mục có tệp")
    for ten, n in sorted(cap1.items())[:40]:
        in_ra(f"   {n:6d}  {ten}")
    if len(cap1) > 40:
        in_ra(f"   … và {len(cap1) - 40} mục nữa")
    duoi = collections.Counter(os.path.splitext(p)[1].lower() or "(không đuôi)" for p, _ in tep)
    in_ra("Đuôi: " + ", ".join(f"{d} {n}" for d, n in duoi.most_common(20)))
    for p, ly_do in bo_qua[:20]:
        in_ra(f"   [BỎ QUA] {p}: {ly_do}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("folder_id")
    ap.add_argument("dich", nargs="?", help="thư mục đích (tạo mới nếu chưa có)")
    ap.add_argument("--sa", default=os.getenv("DRIVE_SA_FILE") or SA_MAC_DINH)
    ap.add_argument("--luong", type=int, default=4)
    ap.add_argument("--chi-liet-ke", action="store_true")
    a = ap.parse_args(argv)

    email = json.loads(Path(a.sa).read_text(encoding="utf-8")).get("client_email")
    svc = _dich_vu(a.sa)
    from googleapiclient.errors import HttpError
    try:
        goc = _thu_lai(lambda: svc.files().get(
            fileId=a.folder_id, fields="id,name,mimeType", supportsAllDrives=True).execute())
    except HttpError as exc:
        if getattr(exc.resp, "status", 0) == 404:
            print(f"[!] Tài khoản dịch vụ {email} không thấy thư mục {a.folder_id}.")
            print("    Chia sẻ thư mục đó (quyền Người xem) cho email trên rồi chạy lại.")
            return 2
        raise
    if goc["mimeType"] != FOLDER:
        print(f"[!] {a.folder_id} không phải thư mục ({goc['mimeType']}).")
        return 2
    print(f"Thư mục Drive: {goc['name']}  (đọc bằng {email})")
    t0 = time.time()
    tep, bo_qua, thu_muc = liet_ke(a.sa, a.folder_id, max(4, a.luong * 2))
    print(f"Liệt kê xong sau {time.time() - t0:.0f} giây.")
    tom_tat(tep, bo_qua, len(thu_muc))
    if a.chi_liet_ke or not a.dich:
        return 0

    dich = Path(a.dich)
    dich.mkdir(parents=True, exist_ok=True)
    # Cả thư mục TRỐNG: tab 360° liệt kê mọi thư mục khách trên đĩa, và mã
    # khách kế tiếp CRM xin được tính cả thư mục chưa có tài liệu.
    for d in thu_muc:
        (dich / d).mkdir(parents=True, exist_ok=True)
    nhat_ky = dich.parent / (dich.name + ".keo_drive.json")
    dem = collections.Counter()
    loi = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=max(1, a.luong)) as ex:
        viec = {ex.submit(tai_mot, a.sa, f, dich / p): (p, f) for p, f in tep}
        for i, xong in enumerate(as_completed(viec), 1):
            p, f = viec[xong]
            try:
                dem[xong.result()] += 1
            except Exception as exc:  # noqa: BLE001 — ghi lại, tải tiếp tệp khác
                dem["loi"] += 1
                loi.append({"path": p, "id": f["id"], "loi": f"{type(exc).__name__}: {exc}"[:300]})
            if i % 200 == 0 or i == len(tep):
                print(f"  {i}/{len(tep)} · {dict(dem)} · {time.time() - t0:.0f}s", flush=True)
    # Tệp có trên đĩa mà cây Drive hiện tại không có: lượt trước tải theo tên
    # cũ, hoặc đã bị xoá/đổi tên trên Drive. Chỉ BÁO — không tự xoá.
    can = {p for p, _ in tep}
    thua = sorted(q.relative_to(dich).as_posix() for q in dich.rglob("*")
                  if q.is_file() and q.relative_to(dich).as_posix() not in can)
    nhat_ky.write_text(json.dumps({
        "folder_id": a.folder_id, "ten": goc["name"], "luc": datetime.now().isoformat(),
        "dem": dict(dem), "loi": loi, "bo_qua": bo_qua, "thua": thua,
        "tep": [{"path": p, "id": f["id"], "md5": f.get("md5Checksum"), "size": f.get("size"),
                 "mime": f["mimeType"]} for p, f in tep],
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"XONG: {dict(dem)} · nhật ký {nhat_ky}")
    for x in loi[:30]:
        print(f"   [LỖI] {x['path']}: {x['loi']}")
    if thua:
        print(f"[CHÚ Ý] {len(thua)} tệp trong {dich} KHÔNG còn trong cây Drive (tên cũ / đã xoá trên Drive):")
        for q in thua[:20]:
            print(f"   · {q}")
    return 1 if loi else 0


if __name__ == "__main__":
    sys.exit(main())
