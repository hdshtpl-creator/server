"""
so_sanh.py — SO SÁNH HAI BẢN VĂN BẢN (bản cũ ↔ bản mới) và xuất .docx có
"theo dõi thay đổi" (tracked changes) để luật sư mở bằng Word/LibreOffice,
thấy phần thêm gạch chân, phần xoá gạch ngang, chấp nhận/từ chối từng chỗ
như một bản chỉnh sửa do đồng nghiệp gửi.

Mô-đun THUẦN: không CSDL, không mạng, chỉ stdlib — để nơi khác (so bản nháp
với bản đã duyệt, kiểm tra pháp lý, tải bản đối chiếu) gọi vào và để test
chạy không cần Postgres/Ollama.

Hai tầng so sánh, vì một tầng không đủ:
  - Căn ĐOẠN trước (SequenceMatcher trên danh sách dòng): văn bản pháp lý dài,
    người sửa thường thêm/xoá cả điều khoản; so mức từ trên toàn văn sẽ trộn
    từ của điều này với điều kia thành một mớ gạch xoá không đọc nổi.
  - Trong cặp đoạn bị sửa mới so mức TỪ, để đổi một chữ chỉ hiện một chữ.

Token gồm cả KHOẢNG TRẮNG (không bỏ đi rồi chèn lại) để ''.join(token) trả về
đúng chuỗi gốc — nhờ vậy bản .docx giữ nguyên cách dòng/khoảng cách người
soạn đã gõ, và tab/nhiều dấu cách không bị "chuẩn hoá" ngầm thành thay đổi giả.

Tracked changes tự dựng bằng OOXML (python-docx không có API ins/del), chỉ
dùng zipfile + chuỗi XML; escape bằng xml.sax.saxutils để '&', '<' trong hợp
đồng không làm hỏng file.
"""
import difflib
import io
import itertools
import re
import zipfile
from datetime import datetime, timezone
from xml.sax.saxutils import escape, quoteattr

TAC_GIA_MAC_DINH = "HDS AI"

# Token = một cụm khoảng trắng HOẶC một cụm không-khoảng-trắng; hai loại xen kẽ
# nên nối lại luôn ra đúng chuỗi gốc.
_TOKEN = re.compile(r"\s+|\S+")
_TU = re.compile(r"\S+")
# Dòng Markdown '# ', '## ', '### ' (tối đa 3 cấp; '####' không tính).
_HEADING = re.compile(r"^(#{1,3})\s+(.*)$")
# Ký tự điều khiển XML 1.0 cấm (trừ tab/LF/CR): zip vẫn mở nhưng Word báo file
# hỏng — loại trước khi ghi.
_KY_TU_CAM = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
# Cỡ chữ (half-point) cho dòng '#', '##', '###'; Normal là 24 (12pt).
_CO_CHU_HEADING = {1: 28, 2: 26, 3: 24}

_NS_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


# ---------------------------------------------------------------------------
# Mức từ
# ---------------------------------------------------------------------------
def tach_tu(text: str) -> list[str]:
    """Token từ / khoảng trắng xen kẽ; ''.join(tach_tu(s)) == s là bất biến
    mọi hàm dưới dựa vào (nối lại hai vế diff phải ra đúng bản cũ / bản mới)."""
    return _TOKEN.findall(text or "")


def _dem_tu(text: str) -> int:
    return len(_TU.findall(text or ""))


def _gop(ket_qua: list[dict], op: str, text: str) -> None:
    """Gộp mảnh liên tiếp cùng op: .docx sinh ít run hơn và người đọc thấy
    'một cụm bị xoá' thay vì từng chữ gạch riêng lẻ."""
    if not text:
        return
    if ket_qua and ket_qua[-1]["op"] == op:
        ket_qua[-1]["text"] += text
    else:
        ket_qua.append({"op": op, "text": text})


def so_sanh_doan(cu: str, moi: str) -> list[dict]:
    """Diff mức từ trong MỘT đoạn → [{"op": equal|delete|insert, "text"}].

    autojunk=False vì dấu cách là token phổ biến nhất: để autojunk mặc định,
    SequenceMatcher coi nó là 'rác' với đoạn ≥200 token và căn lệch cả câu.
    'replace' tách thành delete rồi insert — đúng thứ tự Word hiển thị."""
    a, b = tach_tu(cu), tach_tu(moi)
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    ket_qua: list[dict] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            _gop(ket_qua, "equal", "".join(a[i1:i2]))
        elif tag == "delete":
            _gop(ket_qua, "delete", "".join(a[i1:i2]))
        elif tag == "insert":
            _gop(ket_qua, "insert", "".join(b[j1:j2]))
        else:
            _gop(ket_qua, "delete", "".join(a[i1:i2]))
            _gop(ket_qua, "insert", "".join(b[j1:j2]))
    return ket_qua


# ---------------------------------------------------------------------------
# Mức đoạn
# ---------------------------------------------------------------------------
def _tach_dong(text: str) -> list[str]:
    """Bỏ '\\r' để bản gõ trên Windows (CRLF) so với bản LF không thành khác
    nhau giả. Văn bản rỗng → KHÔNG có đoạn nào (chứ không phải một đoạn rỗng),
    để bản rỗng so với bản có nội dung ra toàn insert/delete thay vì một cặp
    replace vô nghĩa."""
    text = (text or "").replace("\r", "")
    return text.split("\n") if text else []


def _muc(op: str, cu, moi, phan: list[dict]) -> dict:
    return {"op": op, "cu": cu, "moi": moi, "phan": phan}


def _can_doan(a: list, b: list, lay_text) -> list[dict]:
    """Căn hai danh sách đoạn (phần tử hashable; lay_text lấy chuỗi để so từ).

    Khối 'replace' n đoạn cũ ↔ m đoạn mới ghép cặp theo thứ tự (i với i), phần
    dư là delete/insert: người sửa hợp đồng thường sửa tại chỗ từng khoản, nên
    ghép theo vị trí đúng nhiều hơn là đi tìm cặp 'giống nhất' (tốn O(n·m)
    diff từ và dễ ghép nhầm hai khoản có khuôn câu giống nhau)."""
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    doan: list[dict] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for x in a[i1:i2]:
                doan.append(_muc("equal", x, x, [{"op": "equal", "text": lay_text(x)}]))
        elif tag == "delete":
            for x in a[i1:i2]:
                doan.append(_muc("delete", x, None, [{"op": "delete", "text": lay_text(x)}]))
        elif tag == "insert":
            for y in b[j1:j2]:
                doan.append(_muc("insert", None, y, [{"op": "insert", "text": lay_text(y)}]))
        else:
            khoi_cu, khoi_moi = a[i1:i2], b[j1:j2]
            for i in range(max(len(khoi_cu), len(khoi_moi))):
                if i < len(khoi_cu) and i < len(khoi_moi):
                    x, y = khoi_cu[i], khoi_moi[i]
                    doan.append(_muc("replace", x, y, so_sanh_doan(lay_text(x), lay_text(y))))
                elif i < len(khoi_cu):
                    x = khoi_cu[i]
                    doan.append(_muc("delete", x, None, [{"op": "delete", "text": lay_text(x)}]))
                else:
                    y = khoi_moi[i]
                    doan.append(_muc("insert", None, y, [{"op": "insert", "text": lay_text(y)}]))
    return doan


def _thong_ke(doan: list[dict], cu: str, moi: str) -> dict:
    tk = {"them": 0, "xoa": 0, "doan_them": 0, "doan_xoa": 0, "doan_sua": 0}
    for d in doan:
        if d["op"] == "insert":
            tk["doan_them"] += 1
        elif d["op"] == "delete":
            tk["doan_xoa"] += 1
        elif d["op"] == "replace":
            tk["doan_sua"] += 1
        for p in d["phan"]:
            if p["op"] == "insert":
                tk["them"] += _dem_tu(p["text"])
            elif p["op"] == "delete":
                tk["xoa"] += _dem_tu(p["text"])
    # Độ giống trên TOÀN văn bản mức từ, độc lập với cách căn đoạn ở trên, để
    # con số không đổi nếu sau này đổi luật ghép cặp. Hai bản rỗng → 1.0.
    sm = difflib.SequenceMatcher(None, tach_tu(cu), tach_tu(moi), autojunk=False)
    tk["giong_nhau"] = round(sm.ratio(), 3)
    return tk


def so_sanh_van_ban(cu: str, moi: str) -> dict:
    """Căn đoạn rồi so từ trong cặp đoạn bị sửa.

    Trả {"doan": [{"op", "cu", "moi", "phan"}...], "thong_ke": {...}}; "cu"/
    "moi" là None ở phía không có đoạn (insert/delete)."""
    dong_cu, dong_moi = _tach_dong(cu), _tach_dong(moi)
    doan = _can_doan(dong_cu, dong_moi, lambda s: s)
    return {"doan": doan,
            "thong_ke": _thong_ke(doan, "\n".join(dong_cu), "\n".join(dong_moi))}


def tom_tat_thay_doi(ket_qua: dict) -> str:
    tk = (ket_qua or {}).get("thong_ke") or {}

    def lay(k):
        return int(tk.get(k) or 0)

    giong = int(round(float(tk.get("giong_nhau") or 0.0) * 100))
    return (f"Thêm {lay('them')} từ, xoá {lay('xoa')} từ; "
            f"{lay('doan_sua')} đoạn sửa, {lay('doan_them')} đoạn thêm, "
            f"{lay('doan_xoa')} đoạn xoá; giống nhau {giong}%")


# ---------------------------------------------------------------------------
# Xuất .docx có tracked changes
# ---------------------------------------------------------------------------
def _esc(text: str) -> str:
    return escape(_KY_TU_CAM.sub("", text or ""))


def _iso(ngay: datetime | None) -> str:
    """w:date theo ISO UTC 'Z'. Giờ có múi thì quy về UTC; giờ 'trần' coi như
    đã là UTC (Word chỉ cần một mốc nhất quán để sắp thứ tự sửa)."""
    if ngay is None:
        ngay = datetime.now(timezone.utc)
    elif ngay.tzinfo is not None:
        ngay = ngay.astimezone(timezone.utc)
    return ngay.strftime("%Y-%m-%dT%H:%M:%SZ")


def _bo_dau_heading(dong: str) -> tuple[int, str]:
    """(cấp, chữ) — cấp 0 là đoạn thường. Cặp (cấp, chữ) làm phần tử căn đoạn
    để đổi cấp tiêu đề cũng là một thay đổi chứ không bị coi là giống nhau."""
    m = _HEADING.match(dong)
    if m:
        return len(m.group(1)), m.group(2)
    return 0, dong


def _rpr_run(cap: int) -> str:
    if not cap:
        return ""
    sz = _CO_CHU_HEADING[cap]
    return f'<w:rPr><w:b/><w:bCs/><w:sz w:val="{sz}"/><w:szCs w:val="{sz}"/></w:rPr>'


def _run(text: str, rpr: str, xoa: bool = False) -> str:
    # Chữ bị xoá phải nằm trong w:delText (không phải w:t), nếu không Word vẫn
    # hiện nó như chữ thường và mất nút "từ chối".
    tag = "w:delText" if xoa else "w:t"
    return f'<w:r>{rpr}<{tag} xml:space="preserve">{_esc(text)}</{tag}></w:r>'


def _the_theo_doi(loai: str, dem, tac_gia: str, ngay_iso: str,
                  ruot: str | None = None) -> str:
    """<w:ins>/<w:del> bọc run, hoặc thẻ rỗng (dấu đoạn trong w:pPr/w:rPr).
    w:id lấy từ bộ đếm chung cả tài liệu — trùng id là Word báo lỗi."""
    thuoc_tinh = f'w:id="{next(dem)}" w:author={quoteattr(tac_gia)} w:date="{ngay_iso}"'
    if ruot is None:
        return f"<w:{loai} {thuoc_tinh}/>"
    return f"<w:{loai} {thuoc_tinh}>{ruot}</w:{loai}>"


def _p_tieu_de(tieu_de: str) -> str:
    return ('<w:p><w:pPr><w:jc w:val="center"/></w:pPr>'
            '<w:r><w:rPr><w:b/><w:bCs/><w:sz w:val="28"/><w:szCs w:val="28"/></w:rPr>'
            f'<w:t xml:space="preserve">{_esc(tieu_de)}</w:t></w:r></w:p>')


def _p_theo_doi(d: dict, dem, tac_gia: str, ngay_iso: str) -> str:
    """Một w:p từ một mục căn đoạn; cấp tiêu đề lấy theo bản MỚI (bản .docx
    thể hiện trạng thái sau sửa), đoạn bị xoá thì theo bản cũ."""
    goc = d["moi"] if d["moi"] is not None else d["cu"]
    cap = goc[0]
    rpr = _rpr_run(cap)

    # Thuộc tính đoạn dựng TRƯỚC run để w:id tăng theo thứ tự xuất hiện.
    ppr: list[str] = []
    if cap:
        ppr.append("<w:keepNext/>")
    if d["op"] == "delete":
        ppr.append(f"<w:rPr>{_the_theo_doi('del', dem, tac_gia, ngay_iso)}</w:rPr>")
    elif d["op"] == "insert":
        ppr.append(f"<w:rPr>{_the_theo_doi('ins', dem, tac_gia, ngay_iso)}</w:rPr>")

    runs: list[str] = []
    for p in d["phan"]:
        if not p["text"]:
            continue
        if p["op"] == "equal":
            runs.append(_run(p["text"], rpr))
        elif p["op"] == "delete":
            runs.append(_the_theo_doi("del", dem, tac_gia, ngay_iso,
                                      _run(p["text"], rpr, xoa=True)))
        else:
            runs.append(_the_theo_doi("ins", dem, tac_gia, ngay_iso,
                                      _run(p["text"], rpr)))

    ppr_xml = f"<w:pPr>{''.join(ppr)}</w:pPr>" if ppr else ""
    return f"<w:p>{ppr_xml}{''.join(runs)}</w:p>"


_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
    '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
    '</Types>')

_RELS_GOC = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
    '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
    '</Relationships>')

_RELS_DOCUMENT = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
    '</Relationships>')

# Times New Roman 12pt + vi-VN: kiểm tra chính tả/ngắt từ của Word chạy đúng
# tiếng Việt thay vì gạch đỏ cả trang.
_STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    f'<w:styles xmlns:w="{_NS_W}">'
    '<w:docDefaults><w:rPrDefault><w:rPr>'
    '<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:cs="Times New Roman" w:eastAsia="Times New Roman"/>'
    '<w:sz w:val="24"/><w:szCs w:val="24"/><w:lang w:val="vi-VN" w:eastAsia="vi-VN" w:bidi="ar-SA"/>'
    '</w:rPr></w:rPrDefault>'
    '<w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="276" w:lineRule="auto"/></w:pPr></w:pPrDefault>'
    '</w:docDefaults>'
    '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/>'
    '<w:rPr><w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:cs="Times New Roman"/>'
    '<w:sz w:val="24"/><w:szCs w:val="24"/><w:lang w:val="vi-VN"/></w:rPr></w:style>'
    '</w:styles>')


def _core_xml(tieu_de: str, tac_gia: str, ngay_iso: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        f'<dc:title>{_esc(tieu_de)}</dc:title><dc:creator>{_esc(tac_gia)}</dc:creator>'
        f'<cp:lastModifiedBy>{_esc(tac_gia)}</cp:lastModifiedBy>'
        f'<dcterms:created xsi:type="dcterms:W3CDTF">{ngay_iso}</dcterms:created>'
        f'<dcterms:modified xsi:type="dcterms:W3CDTF">{ngay_iso}</dcterms:modified>'
        '</cp:coreProperties>')


def _document_xml(body: str) -> str:
    # A4, lề theo thể thức văn bản (NĐ 30/2020): trên/dưới/phải 2cm, trái 3cm
    # — 1134 twip = 2cm, 1701 twip = 3cm.
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<w:document xmlns:w="{_NS_W}" xmlns:r="{_NS_R}"><w:body>{body}'
        '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1701" w:header="709" w:footer="709" w:gutter="0"/>'
        '</w:sectPr></w:body></w:document>')


def xuat_docx_theo_doi(cu: str, moi: str, tieu_de: str = "",
                       tac_gia: str = TAC_GIA_MAC_DINH,
                       ngay: datetime | None = None) -> bytes:
    """File .docx thật có tracked changes: đoạn/từ thêm nằm trong w:ins, xoá
    nằm trong w:del (+ dấu đoạn bị xoá/thêm trong w:pPr/w:rPr) để Word và
    LibreOffice cho chấp nhận/từ chối từng chỗ.

    Dòng Markdown '# ' → bỏ dấu, in đậm, cỡ lớn hơn; tieu_de (nếu có) là đoạn
    đầu in đậm căn giữa và KHÔNG nằm trong tracked change (nó là nhãn của bản
    đối chiếu, không phải nội dung ai đó sửa)."""
    tac_gia = (tac_gia or "").strip() or TAC_GIA_MAC_DINH
    ngay_iso = _iso(ngay)
    tieu_de = (tieu_de or "").strip()

    dong_cu = [_bo_dau_heading(d) for d in _tach_dong(cu)]
    dong_moi = [_bo_dau_heading(d) for d in _tach_dong(moi)]
    doan = _can_doan(dong_cu, dong_moi, lambda t: t[1])

    dem = itertools.count(1)
    body: list[str] = []
    if tieu_de:
        body.append(_p_tieu_de(tieu_de))
    for d in doan:
        body.append(_p_theo_doi(d, dem, tac_gia, ngay_iso))

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        # [Content_Types].xml đứng đầu theo quy ước OPC; một số bộ đọc dò nó
        # ngay ở entry đầu tiên.
        z.writestr("[Content_Types].xml", _CONTENT_TYPES.encode("utf-8"))
        z.writestr("_rels/.rels", _RELS_GOC.encode("utf-8"))
        z.writestr("word/document.xml", _document_xml("".join(body)).encode("utf-8"))
        z.writestr("word/_rels/document.xml.rels", _RELS_DOCUMENT.encode("utf-8"))
        z.writestr("word/styles.xml", _STYLES.encode("utf-8"))
        z.writestr("docProps/core.xml",
                   _core_xml(tieu_de, tac_gia, ngay_iso).encode("utf-8"))
    return buf.getvalue()
