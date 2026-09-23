"""web_watch.py — Bộ quét ĐỊNH KỲ theo dõi nguồn văn bản trên mạng.

Việc của module này rất hẹp và cố ý hẹp: **tải file mới từ vài trang nguồn đã
chọn về đúng thư mục kho**, rồi thôi. Không có LLM nào quyết định gì ở đây.

    Trang nguồn (RSS / sitemap / trang danh sách HTML)
        └── web_watch.py: lọc link → tải file → đặt vào DATA_LIB/<thư mục>/
                └── local_learn.py (đã chạy sẵn mỗi 15 phút) học như file
                    nhân viên thả vào thư mục: bóc chữ, OCR bản scan, tách
                    theo Điều, gắn nhãn theo tên thư mục, vào hàng CHỜ DUYỆT.

Đi vòng qua kho local thay vì tự gọi ingest là có chủ ý: mọi thứ đã được kiểm
chứng ở đường học hiện tại (nhận diện file di chuyển bằng md5, kế thừa trạng
thái duyệt, ghi nhận file không đọc được, phân quyền theo thư mục) được dùng
lại nguyên vẹn, không có đường thứ hai để lệch nhau.

NĂM CHỐT AN TOÀN — đây là cửa duy nhất trong hệ thống nhận dữ liệu từ Internet,
gỡ chốt nào là mở đúng cửa đó:

1. **Chỉ tải từ miền đã ghi rõ.** Không có danh sách miền thì không tải gì.
   Kiểm CẢ SAU KHI đi hết chuyển hướng — một link hợp lệ vẫn có thể đẩy sang
   miền khác ở bước cuối.
2. **Chỉ đuôi file kho đọc được**, và nội dung phải ĐÚNG là định dạng đó (xem
   `dung_dinh_dang`). Trang lỗi trả về HTML mang tên .pdf là ca thường gặp
   nhất; không chặn thì kho đầy "văn bản luật" chứa chữ "404 Not Found".
3. **Trần dung lượng** dùng chung với đường Drive cũ (DRIVE_MAX_DOWNLOAD_BYTES),
   kiểm cả lúc đang tải chứ không chỉ tin Content-Length.
4. **File tải từ mạng LUÔN chờ người duyệt**, bất kể AUTO_LEARN_AUTO_APPROVE.
   Tài liệu trong kho tới giờ đều do nhân viên tự tay đặt vào; đây là loại đầu
   tiên không ai nhìn qua trước. Chốt nằm ở local_learn (đọc `keys_tu_web`).
5. **Không chạm thư mục ngoài kho.** Thư mục đích trong cấu hình được ghép rồi
   resolve, phải nằm trong DATA_LIB — chuỗi '../../etc' là chuyện phải chặn ở
   đây chứ không phải tin admin gõ đúng.

Cấu hình nguồn nằm ở app_settings khoá `web_sources` (admin sửa trên web, y
như drive_map). Mỗi nguồn:

    {"ten": "Công báo — văn bản mới",
     "bat": true,
     "kieu": "rss",                       # rss | sitemap | html
     "url": "https://…",
     "mien_cho_phep": ["vanban.chinhphu.vn"],
     "thu_muc": "1. VĂN BẢN PHÁP LUẬT",   # thư mục con trong kho
     "duoi_file": [".pdf", ".doc", ".docx"],
     "mau_lien_ket": "",                  # regex lọc thêm, để trống là bỏ qua
     "toi_da_moi_lan": 20}

Chạy tay:      python -m app.web_watch                 # quét và tải
               python -m app.web_watch --dry-run       # chỉ liệt kê, không tải
               python -m app.web_watch --nguon "Công báo"   # một nguồn
Chạy định kỳ:  sudo bash deploy/theo-doi-nguon-web.sh --install-timer
"""
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse
from xml.etree import ElementTree

import requests
from dotenv import load_dotenv

from app import auto_learn, settings
from app.ingest import SUPPORTED_EXTENSIONS
from app.local_learn import library_root

load_dotenv()

SETTING_TRANG_THAI = "web_watch_status"
SETTING_DA_TAI = "web_watch_seen"

# Tự giới thiệu đàng hoàng: trang nguồn nhìn log biết ai đang tải và liên hệ
# với ai khi thấy bất thường. Giấu mặt bằng UA trình duyệt là cách nhanh nhất
# để bị chặn IP máy chủ.
USER_AGENT = os.getenv(
    "WEB_WATCH_UA",
    "HDS-AI-DocWatcher/1.0 (bo quet tai lieu phap luat cua Cong ty Luat HDS)")
TIMEOUT = int(os.getenv("WEB_WATCH_TIMEOUT", "60"))

# Nghỉ giữa hai lần tải. Bộ quét chạy nền, không ai chờ nó — dồn dập vài chục
# request vào một trang nhà nước là cách tự chuốc lấy lệnh chặn.
NGHI_GIAY = float(os.getenv("WEB_WATCH_DELAY", "1.5"))

# Số URL nhớ là "đã tải". Vượt thì cắt bớt phần cũ nhất: không mất mát gì vì
# còn hai lớp chặn trùng nữa — file đã nằm trên đĩa, và local_learn nhận ra
# nội dung trùng bằng md5.
MAX_DA_TAI = 2000

# Số dòng chi tiết lưu vào trạng thái, dùng chung mức với bộ quét kho.
MAX_STATUS_ITEMS = auto_learn.MAX_STATUS_ITEMS

# Chữ ký đầu file. Cách rẻ nhất để biết thứ vừa tải có đúng là định dạng nó
# tự xưng không — CHỐT 2.
CHU_KY = {
    ".pdf": (b"%PDF",),
    ".docx": (b"PK\x03\x04",),
    ".xlsx": (b"PK\x03\x04",),
    ".doc": (b"\xd0\xcf\x11\xe0", b"{\\rt"),   # OLE2, hoặc RTF đặt nhầm tên
}

# Tên máy nội bộ: bộ quét chỉ có việc ra Internet, trỏ nó vào mạng nhà là dấu
# hiệu cấu hình sai (hoặc tệ hơn). Chặn thẳng.
_HOST_NOI_BO = re.compile(
    r"^(localhost|.*\.local|.*\.internal|127\.|10\.|192\.168\.|169\.254\.|"
    r"172\.(1[6-9]|2\d|3[01])\.|\[?::1\]?)", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Cấu hình nguồn
# ---------------------------------------------------------------------------
def nguon_list() -> list:
    """Danh sách nguồn ĐANG BẬT, đã bỏ bản ghi thiếu trường bắt buộc.

    Cấu hình sai thì bỏ qua nguồn đó và nói ra, chứ không dừng cả lượt quét:
    một dòng JSON gõ nhầm không nên làm chết việc theo dõi mấy nguồn còn lại.
    """
    raw = settings.get_json("web_sources") or {}
    out = []
    for i, ng in enumerate(raw.get("nguon") or []):
        if not isinstance(ng, dict) or not ng.get("bat"):
            continue
        thieu = [k for k in ("ten", "url", "thu_muc", "mien_cho_phep") if not ng.get(k)]
        if thieu:
            print(f"[BỎ QUA] Nguồn #{i + 1} thiếu trường: {', '.join(thieu)}")
            continue
        out.append(ng)
    return out


def _duoi_cho_phep(ng) -> set:
    """Đuôi file được tải. Giao với SUPPORTED_EXTENSIONS: admin gõ '.html' vào
    cấu hình cũng không mở được cửa cho thứ kho không học."""
    khai = ng.get("duoi_file") or [".pdf", ".doc", ".docx"]
    return {d.lower() for d in khai if d.lower() in SUPPORTED_EXTENSIONS}


# ---------------------------------------------------------------------------
# Bóc link — hàm thuần, không chạm mạng, để test được
# ---------------------------------------------------------------------------
def _the(el) -> str:
    """Tên thẻ đã bỏ namespace: '{http://…}link' → 'link'."""
    return el.tag.rsplit("}", 1)[-1].lower() if isinstance(el.tag, str) else ""


def lien_ket_tu_xml(noi_dung: str, base_url: str) -> list:
    """Link trong RSS 2.0, Atom hoặc sitemap.xml — một hàm cho cả ba.

    Ba chuẩn khác nhau ở chỗ đặt link (<link>text</link> của RSS, thuộc tính
    href của Atom, <loc> của sitemap) nhưng giống nhau ở chỗ đều là XML và đều
    chỉ có bấy nhiêu chỗ để nhìn. Gộp lại thì admin đổi 'rss' thành 'sitemap'
    trong cấu hình cũng không sai được.
    """
    try:
        root = ElementTree.fromstring(noi_dung)
    except ElementTree.ParseError:
        return []
    out = []
    for el in root.iter():
        ten = _the(el)
        if ten in ("link", "loc"):
            gia_tri = (el.get("href") or el.text or "").strip()
            if gia_tri:
                out.append(urljoin(base_url, gia_tri))
        elif ten == "enclosure" and el.get("url"):
            out.append(urljoin(base_url, el.get("url").strip()))
    return out


_HREF = re.compile(r"""<a\b[^>]*?\bhref\s*=\s*["']([^"'>]+)["']""", re.IGNORECASE)


def lien_ket_tu_html(noi_dung: str, base_url: str) -> list:
    """Link trong một trang danh sách HTML.

    Cố tình dùng regex chứ không kéo thêm thư viện bóc HTML: ta chỉ cần thuộc
    tính href, không cần hiểu cây tài liệu, và mỗi phụ thuộc mới là một thứ
    phải vá khi có lỗ hổng. Đổi lại, trang dựng link bằng JavaScript sẽ không
    ra kết quả — lúc đó dùng RSS/sitemap của chính trang đó.
    """
    return [urljoin(base_url, m.group(1).strip()) for m in _HREF.finditer(noi_dung)]


def host_hop_le(url: str, mien_cho_phep) -> bool:
    """CHỐT 1 — URL này có thuộc miền đã cho phép không.

    Khớp cả tên miền con: 'vanban.chinhphu.vn' cho phép 'a.vanban.chinhphu.vn'
    nhưng KHÔNG cho phép 'vanban.chinhphu.vn.kesau.com' (đuôi phải trùng sau
    một dấu chấm, không phải trùng chuỗi).
    """
    try:
        p = urlparse(url)
    except ValueError:
        return False
    if p.scheme not in ("http", "https"):
        return False
    host = (p.hostname or "").lower()
    if not host or _HOST_NOI_BO.match(host):
        return False
    for mien in mien_cho_phep or []:
        m = (mien or "").strip().lower().lstrip(".")
        if m and (host == m or host.endswith("." + m)):
            return True
    return False


def loc_lien_ket(urls, ng) -> list:
    """Từ mớ link thô của một trang → những link ĐÁNG tải, giữ nguyên thứ tự
    và bỏ trùng."""
    duoi = _duoi_cho_phep(ng)
    mau = (ng.get("mau_lien_ket") or "").strip()
    try:
        loc_regex = re.compile(mau, re.IGNORECASE) if mau else None
    except re.error as e:
        print(f"[BỎ QUA] mau_lien_ket của '{ng.get('ten')}' sai cú pháp: {e}")
        loc_regex = None
    out, da_thay = [], set()
    for url in urls:
        url = url.split("#", 1)[0]
        if url in da_thay or not host_hop_le(url, ng.get("mien_cho_phep")):
            continue
        if Path(unquote(urlparse(url).path)).suffix.lower() not in duoi:
            continue
        if loc_regex and not loc_regex.search(url):
            continue
        da_thay.add(url)
        out.append(url)
    return out


# ---------------------------------------------------------------------------
# Đích đến trên đĩa
# ---------------------------------------------------------------------------
_TEN_XAU = re.compile(r"[^0-9A-Za-zÀ-ỹà-ỹ._ -]+")


def ten_file_an_toan(url: str, mac_dinh_duoi=".pdf") -> str:
    """Tên file lấy từ URL, đã tước mọi thứ có thể trỏ ra ngoài thư mục đích.

    Không tin phần path của URL: '/a/../../../etc/passwd.pdf' là chuỗi hợp lệ
    với urlparse. Chỉ lấy đúng phần tên cuối, bỏ mọi dấu phân cách và dấu chấm
    dẫn đầu, rồi giới hạn độ dài (một số nguồn nhét cả câu tiếng Việt vào tên).
    """
    ten = Path(unquote(urlparse(url).path)).name
    ten = _TEN_XAU.sub("_", ten).strip(" ._")
    if not ten:
        ten = "tai-lieu"
    goc, duoi = os.path.splitext(ten)
    if not duoi:
        duoi = mac_dinh_duoi
    return (goc[:120] or "tai-lieu") + duoi.lower()


def thu_muc_dich(root: Path, thu_muc: str) -> Path:
    """CHỐT 5 — thư mục đích, đã ràng phải nằm trong kho."""
    dich = (root / (thu_muc or "").strip("/\\")).resolve()
    if dich != root and root not in dich.parents:
        raise ValueError(f"Thư mục đích nằm ngoài kho: {thu_muc}")
    return dich


def dung_dinh_dang(suffix: str, dau_file: bytes) -> bool:
    """CHỐT 2 — nội dung có đúng là định dạng mà tên file tự xưng không.

    Ca thường gặp: trang nguồn đổi đường dẫn, link .pdf trả về trang lỗi HTML.
    Không chặn thì kho có một "văn bản luật" mà toàn văn là '404 Not Found',
    bot trích dẫn nó y như trích dẫn luật thật.
    """
    ky = CHU_KY.get((suffix or "").lower())
    if not ky:
        return True                     # định dạng không có chữ ký rõ: cho qua
    return any(dau_file.startswith(k) for k in ky)


# ---------------------------------------------------------------------------
# Sổ theo dõi "đã tải"
# ---------------------------------------------------------------------------
def _da_tai() -> dict:
    try:
        return json.loads(settings.get(SETTING_DA_TAI) or "{}")
    except (TypeError, ValueError):
        return {}


def _ghi_da_tai(so: dict):
    if len(so) > MAX_DA_TAI:
        moi_nhat = sorted(so.items(), key=lambda kv: kv[1].get("luc", ""))[-MAX_DA_TAI:]
        so = dict(moi_nhat)
    settings.set_system(SETTING_DA_TAI, json.dumps(so, ensure_ascii=False))


def keys_tu_web() -> set:
    """Danh tính kho (`local:<đường dẫn tương đối>`) của mọi file do bộ quét
    này tải về.

    CHỐT 4 sống ở đây: local_learn đọc tập này để KHÔNG tự duyệt file tải từ
    mạng, kể cả khi admin đã bật tự duyệt cho kho. Trả về tập rỗng khi chưa
    dùng bộ quét — không có nguồn nào thì không có gì phải chặn.
    """
    return {v.get("key") for v in _da_tai().values() if v.get("key")}


# ---------------------------------------------------------------------------
# Tải
# ---------------------------------------------------------------------------
def _phien():
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


def tai_mot_file(phien, url: str, dich: Path, mien_cho_phep) -> tuple:
    """Tải một file về `dich`. Trả về (đường dẫn, lý do bỏ qua).

    Ghi qua file tạm rồi đổi tên: bộ quét kho chạy song song mỗi 15 phút, gặp
    file đang tải dở thì học nửa vời rồi ghi vào tri thức bản cụt.
    """
    r = phien.get(url, timeout=TIMEOUT, stream=True, allow_redirects=True)
    try:
        # CHỐT 1 (lần hai) — kiểm lại SAU chuyển hướng.
        if not host_hop_le(r.url, mien_cho_phep):
            return None, f"chuyển hướng ra ngoài miền cho phép: {r.url}"
        r.raise_for_status()
        kieu = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if kieu in ("text/html", "application/xhtml+xml"):
            return None, "máy chủ trả về trang HTML, không phải file"
        do_dai = r.headers.get("Content-Length")
        if do_dai and do_dai.isdigit() and int(do_dai) > auto_learn.MAX_DOWNLOAD_BYTES:
            return None, f"lớn hơn giới hạn {auto_learn.MAX_DOWNLOAD_BYTES:,} byte"

        dich.parent.mkdir(parents=True, exist_ok=True)
        tam = dich.with_name(dich.name + ".dangtai")
        tong = 0
        dau_file = b""
        with open(tam, "wb") as f:
            for mau in r.iter_content(chunk_size=64 * 1024):
                if not mau:
                    continue
                if not dau_file:
                    dau_file = mau[:8]
                tong += len(mau)
                # CHỐT 3 — Content-Length có thể thiếu hoặc nói dối.
                if tong > auto_learn.MAX_DOWNLOAD_BYTES:
                    f.close()
                    tam.unlink(missing_ok=True)
                    return None, f"vượt giới hạn {auto_learn.MAX_DOWNLOAD_BYTES:,} byte khi tải"
                f.write(mau)
        if not tong:
            tam.unlink(missing_ok=True)
            return None, "file rỗng"
        if not dung_dinh_dang(dich.suffix, dau_file):
            tam.unlink(missing_ok=True)
            return None, f"nội dung không phải {dich.suffix} (nhiều khả năng là trang lỗi)"
        tam.replace(dich)
        return dich, None
    finally:
        r.close()


# ---------------------------------------------------------------------------
# Lượt quét
# ---------------------------------------------------------------------------
def quet_mot_nguon(phien, ng, root: Path, so: dict, dry_run=False) -> dict:
    """Quét một nguồn. Trả về thống kê + danh sách file mới của nguồn đó."""
    ket = {"ten": ng.get("ten"), "url": ng.get("url"), "moi": [], "bo_qua": [],
           "loi": None, "so_link": 0}
    try:
        r = phien.get(ng["url"], timeout=TIMEOUT)
        r.raise_for_status()
        noi_dung = r.text
    except Exception as e:  # noqa: BLE001 - lỗi mạng đủ kiểu, ghi lại rồi đi tiếp
        ket["loi"] = f"{type(e).__name__}: {e}"
        return ket

    kieu = (ng.get("kieu") or "rss").strip().lower()
    tho = (lien_ket_tu_html(noi_dung, ng["url"]) if kieu == "html"
           else lien_ket_tu_xml(noi_dung, ng["url"]))
    links = loc_lien_ket(tho, ng)
    ket["so_link"] = len(links)

    try:
        dich_dir = thu_muc_dich(root, ng.get("thu_muc"))
    except ValueError as e:
        ket["loi"] = str(e)
        return ket

    toi_da = int(ng.get("toi_da_moi_lan") or 20)
    for url in links:
        if len(ket["moi"]) >= toi_da:
            ket["bo_qua"].append({"url": url, "ly_do": f"đã đủ {toi_da} file lượt này"})
            break
        if url in so:
            continue                      # đã tải lần trước
        dich = dich_dir / ten_file_an_toan(url)
        if dich.exists():
            # Lớp chặn trùng thứ hai: sổ theo dõi có thể đã bị cắt bớt.
            so[url] = {"key": "local:" + str(dich.relative_to(root)).replace("\\", "/"),
                       "luc": datetime.now(timezone.utc).isoformat(), "ten": dich.name}
            continue
        if dry_run:
            ket["moi"].append({"url": url, "file": str(dich.relative_to(root))})
            continue
        duong_dan, ly_do = tai_mot_file(phien, url, dich, ng.get("mien_cho_phep"))
        if ly_do:
            ket["bo_qua"].append({"url": url, "ly_do": ly_do})
        else:
            key = "local:" + str(duong_dan.relative_to(root)).replace("\\", "/")
            so[url] = {"key": key, "luc": datetime.now(timezone.utc).isoformat(),
                       "ten": duong_dan.name}
            ket["moi"].append({"url": url, "file": str(duong_dan.relative_to(root))})
        time.sleep(NGHI_GIAY)
    return ket


def run(dry_run=False, chi_nguon=None) -> dict:
    root = library_root()
    started_at = datetime.now(timezone.utc)
    if not root.exists():
        print(f"[LỖI] Không thấy thư mục kho: {root}")
        sys.exit(1)

    nguon = nguon_list()
    if chi_nguon:
        loc = chi_nguon.strip().lower()
        nguon = [n for n in nguon if loc in (n.get("ten") or "").lower()]
    if not nguon:
        print("Chưa có nguồn nào đang bật. Thêm ở Cài đặt AI → khoá 'web_sources'.")
        return {"nguon": [], "counts": {"moi": 0, "bo_qua": 0, "loi": 0}}

    print(f">> Kho tài liệu: {root}")
    print(f">> {len(nguon)} nguồn đang bật"
          f"{' — CHỈ LIỆT KÊ, không tải gì (--dry-run)' if dry_run else ''}\n")

    phien = _phien()
    so = _da_tai()
    ket_qua, n_moi, n_bo, n_loi = [], 0, 0, 0
    for ng in nguon:
        print(f"— {ng.get('ten')}")
        ket = quet_mot_nguon(phien, ng, root, so, dry_run=dry_run)
        ket_qua.append(ket)
        if ket["loi"]:
            n_loi += 1
            print(f"  [LỖI] {ket['loi']}")
            continue
        n_moi += len(ket["moi"])
        n_bo += len(ket["bo_qua"])
        print(f"  {ket['so_link']} link hợp lệ · {len(ket['moi'])} file mới"
              f" · {len(ket['bo_qua'])} bỏ qua")
        for m in ket["moi"]:
            print(f"    + {m['file']}")
        for b in ket["bo_qua"]:
            print(f"    ! {b['ly_do']} — {b['url']}")

    if not dry_run:
        _ghi_da_tai(so)
        _ghi_trang_thai(started_at, root, ket_qua, n_moi, n_bo, n_loi)

    print(f"\n>> Xong: {n_moi} file mới, {n_bo} bỏ qua, {n_loi} nguồn lỗi.")
    if n_moi and not dry_run:
        print("   File đang CHỜ bộ quét kho học (mỗi 15 phút) rồi vào hàng chờ duyệt.")
        print("   Muốn học ngay: sudo systemctl start hds-ai-quet-kho.service")
    return {"nguon": ket_qua, "counts": {"moi": n_moi, "bo_qua": n_bo, "loi": n_loi}}


def _ghi_trang_thai(started_at, root, ket_qua, n_moi, n_bo, n_loi):
    """Ghi tóm tắt lượt quét vào app_settings — KHOÁ RIÊNG, không dùng chung
    `drive_sync_status` với bộ quét kho: hai bộ chạy hai lịch khác nhau, ghi
    chung một khoá thì thẻ trạng thái trên web nhấp nháy giữa hai lượt việc
    chẳng liên quan gì tới nhau."""
    summary = {
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "counts": {"moi": n_moi, "bo_qua": n_bo, "loi": n_loi},
        "nguon": [{"ten": k["ten"], "url": k["url"], "so_link": k["so_link"],
                   "loi": k["loi"],
                   "moi": k["moi"][-MAX_STATUS_ITEMS:],
                   "bo_qua": k["bo_qua"][-MAX_STATUS_ITEMS:]}
                  for k in ket_qua],
    }
    try:
        settings.set_system(SETTING_TRANG_THAI, json.dumps(summary, ensure_ascii=False))
    except Exception as e:  # noqa: BLE001
        print(f"[CẢNH BÁO] Không ghi được trạng thái vào CSDL: {e}")


if __name__ == "__main__":
    argv = sys.argv[1:]
    ten = None
    if "--nguon" in argv:
        i = argv.index("--nguon")
        ten = argv[i + 1] if i + 1 < len(argv) else None
    run(dry_run="--dry-run" in argv, chi_nguon=ten)
