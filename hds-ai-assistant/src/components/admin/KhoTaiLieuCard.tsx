import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useApp } from '../../context/AppContext';
import * as api from '../../api';
import type { KhoKetQuaTim, KhoTang, KhoTapTin, KhoThuMuc, KhoTrangThai } from '../../types';
import { DOC_TYPE_LABELS } from '../../constants';
import {
  ChevronDown,
  ChevronRight,
  Download,
  Eye,
  FolderOpen,
  Folder,
  FolderPlus,
  GraduationCap,
  HardDrive,
  Info,
  RefreshCw,
  Search,
  Trash2,
  Upload,
  X,
} from 'lucide-react';
import { DocumentDetailModal } from './DocumentDetailModal';

/**
 * Thẻ "Kho tài liệu trên máy chủ" trên trang Tổng quan: cây thư mục thật của
 * kho (data/raw), trạng thái học từng file, tìm nhanh, gỡ, tải lên và học
 * ngay — admin kiểm soát kho mà không cần SSH (yêu cầu 11/09/2026).
 *
 * Cây tải LƯỜI từng tầng (kho có 35.000 file, ngăn bản án hơn 30.000): mở
 * thư mục nào mới gọi /kho/cay cho thư mục đó; danh sách file phân trang.
 */

export const TRANG_THAI: Record<KhoTrangThai, { label: string; cls: string }> = {
  da_hoc: {
    label: 'Đã học',
    cls: 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-950 dark:text-emerald-300 dark:border-emerald-900',
  },
  canh_bao: {
    label: 'Đã học · cảnh báo',
    cls: 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950 dark:text-amber-300 dark:border-amber-900',
  },
  cho_duyet: {
    label: 'Chờ duyệt',
    cls: 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950 dark:text-amber-300 dark:border-amber-900',
  },
  chua_hoc: {
    label: 'Chưa học',
    cls: 'bg-slate-100 text-slate-600 border-slate-300 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-700',
  },
  loi: {
    label: 'Lỗi học',
    cls: 'bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-950 dark:text-rose-300 dark:border-rose-900',
  },
  khong_ho_tro: {
    label: 'Không hỗ trợ',
    cls: 'bg-slate-100 text-slate-500 border-slate-200 dark:bg-slate-800 dark:text-slate-400 dark:border-slate-700',
  },
};

const TRANG = 200;

function dinhDangKichThuoc(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export const TrangThaiBadge: React.FC<{ trangThai: KhoTrangThai; title?: string }> = ({ trangThai, title }) => {
  const t = TRANG_THAI[trangThai] || TRANG_THAI.chua_hoc;
  return (
    <span
      title={title}
      className={`inline-block text-[10px] font-semibold px-2 py-0.5 rounded-full border whitespace-nowrap ${t.cls}`}
    >
      {t.label}
    </span>
  );
};

const NUT = 'inline-flex items-center gap-1 px-2 py-1 rounded-lg border text-[11px] font-bold transition-colors disabled:opacity-50';
const NUT_XANH = `${NUT} bg-hds-soft dark:bg-slate-800 text-hds-navy dark:text-blue-300 hover:bg-blue-100 dark:hover:bg-slate-700 border-blue-200 dark:border-slate-700`;
const NUT_DO = `${NUT} bg-rose-50 dark:bg-rose-950 text-rose-700 dark:text-rose-300 hover:bg-rose-100 dark:hover:bg-rose-900 border-rose-200 dark:border-rose-900`;

/** Một nút trên cây thư mục; con được tải khi mở lần đầu. */
interface NutCay {
  thuMuc: KhoThuMuc;
  con?: KhoThuMuc[];
  dangTai?: boolean;
}

export const KhoTaiLieuCard: React.FC = () => {
  const { showToast, currentUser } = useApp();
  const isAdmin = currentUser?.role === 'admin';
  const canReview = Boolean(currentUser && (isAdmin || currentUser.can_review));

  // Cây bên trái
  const [goc, setGoc] = useState<KhoThuMuc[] | null>(null);
  const [nut, setNut] = useState<Record<string, NutCay>>({});
  const [moRong, setMoRong] = useState<Set<string>>(new Set());
  const [rootPath, setRootPath] = useState<string>('');

  // Ngăn đang xem bên phải
  const [path, setPath] = useState<string>('');
  const [tang, setTang] = useState<KhoTang | null>(null);
  const [locTen, setLocTen] = useState('');
  const [locTenApDung, setLocTenApDung] = useState('');
  const [offset, setOffset] = useState(0);
  const [dangTai, setDangTai] = useState(true);
  const [loiTai, setLoiTai] = useState<string | null>(null);

  // Tìm toàn kho
  const [timQ, setTimQ] = useState('');
  const [ketQuaTim, setKetQuaTim] = useState<KhoKetQuaTim[] | null>(null);
  const [dangTim, setDangTim] = useState(false);

  // Hành động
  const [detailId, setDetailId] = useState<number | null>(null);
  const [downloadingId, setDownloadingId] = useState<number | null>(null);
  const [xacNhanGo, setXacNhanGo] = useState<KhoTapTin | KhoKetQuaTim | null>(null);
  const [dangGo, setDangGo] = useState(false);
  const [dangHoc, setDangHoc] = useState<string | null>(null);
  const [duyetLuon, setDuyetLuon] = useState(false);
  const [dangTaiLen, setDangTaiLen] = useState(false);
  const [tienDo, setTienDo] = useState(0);
  const [ketQuaTaiLen, setKetQuaTaiLen] = useState<KhoTaiLenKq[] | null>(null);
  const [moTaoThuMuc, setMoTaoThuMuc] = useState(false);
  const [tenThuMucMoi, setTenThuMucMoi] = useState('');
  const fileInput = useRef<HTMLInputElement | null>(null);

  type KhoTaiLenKq = { filename?: string; ok: boolean; note?: string; loi?: string; trang_thai?: KhoTrangThai; warnings?: string[] };

  const taiTang = useCallback(
    async (p: string, q: string, off: number) => {
      setDangTai(true);
      setLoiTai(null);
      try {
        const data = await api.getKhoTang({ path: p, q, offset: off, limit: TRANG });
        setTang(data);
        setRootPath(data.root);
        // Đồng bộ con của nút tương ứng trên cây (nếu đã mở) — sau tải lên /
        // tạo thư mục số liệu trong cây phải đổi theo.
        setNut((cu) => ({ ...cu, [p]: { ...(cu[p] || { thuMuc: { ten: data.ten, path: p, so_file: 0, da_hoc: 0, cho_duyet: 0, tong_ban_ghi: 0 } }), con: data.thu_muc, dangTai: false } }));
        if (p === '') setGoc(data.thu_muc);
      } catch (err: any) {
        const msg = err?.message || 'Không tải được thư mục.';
        setLoiTai(msg);
        showToast(msg, 'error');
      } finally {
        setDangTai(false);
      }
    },
    [showToast]
  );

  useEffect(() => {
    taiTang('', '', 0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const moThuMuc = (p: string, giuLoc = false) => {
    setKetQuaTim(null);
    setPath(p);
    setOffset(0);
    if (!giuLoc) {
      setLocTen('');
      setLocTenApDung('');
    }
    taiTang(p, giuLoc ? locTenApDung : '', 0);
  };

  const lamMoi = () => {
    taiTang(path, locTenApDung, offset);
    if (path !== '') api.getKhoTang({ path: '', limit: 1 }).then((d) => setGoc(d.thu_muc)).catch(() => {});
  };

  const batTatNut = async (tm: KhoThuMuc) => {
    const dangMo = moRong.has(tm.path);
    const moi = new Set(moRong);
    if (dangMo) {
      moi.delete(tm.path);
      setMoRong(moi);
      return;
    }
    moi.add(tm.path);
    setMoRong(moi);
    if (!nut[tm.path]?.con) {
      setNut((cu) => ({ ...cu, [tm.path]: { thuMuc: tm, dangTai: true } }));
      try {
        const d = await api.getKhoTang({ path: tm.path, limit: 1 });
        setNut((cu) => ({ ...cu, [tm.path]: { thuMuc: tm, con: d.thu_muc, dangTai: false } }));
      } catch (err: any) {
        setNut((cu) => ({ ...cu, [tm.path]: { thuMuc: tm, con: [], dangTai: false } }));
        showToast(err?.message || 'Không mở được thư mục.', 'error');
      }
    }
  };

  const apDungLoc = (e: React.FormEvent) => {
    e.preventDefault();
    setLocTenApDung(locTen);
    setOffset(0);
    taiTang(path, locTen, 0);
  };

  const doiTrang = (off: number) => {
    setOffset(off);
    taiTang(path, locTenApDung, off);
  };

  const timToanKho = async (e: React.FormEvent) => {
    e.preventDefault();
    const q = timQ.trim();
    if (q.length < 2) {
      showToast('Nhập ít nhất 2 ký tự để tìm.', 'info');
      return;
    }
    setDangTim(true);
    try {
      setKetQuaTim(await api.timTrongKho(q));
    } catch (err: any) {
      showToast(err?.message || 'Không tìm được.', 'error');
    } finally {
      setDangTim(false);
    }
  };

  const handlePreview = async (docId: number) => {
    try {
      await api.previewDocument(docId);
    } catch (err: any) {
      showToast(err?.message || 'Không mở được bản xem trước.', 'error');
    }
  };

  const handleDownload = async (docId: number, title: string) => {
    setDownloadingId(docId);
    try {
      await api.downloadDocument(docId, title);
    } catch (err: any) {
      showToast(err?.message || 'Không tải được tệp gốc.', 'error');
    } finally {
      setDownloadingId(null);
    }
  };

  const goTaiLieu = async () => {
    if (!xacNhanGo || xacNhanGo.document_id == null) return;
    setDangGo(true);
    try {
      const r = await api.goTaiLieuKho(xacNhanGo.document_id);
      showToast(
        r.da_chuyen_toi
          ? 'Đã gỡ khỏi kho. Bot ngừng dùng ngay; file gốc chuyển sang thùng đã gỡ.'
          : 'Đã gỡ khỏi kho. Bot ngừng dùng ngay.',
        'success'
      );
      setXacNhanGo(null);
      if (ketQuaTim) setKetQuaTim(ketQuaTim.filter((k) => k.document_id !== xacNhanGo.document_id));
      lamMoi();
    } catch (err: any) {
      showToast(err?.message || 'Không gỡ được tài liệu.', 'error');
    } finally {
      setDangGo(false);
    }
  };

  const hocNgay = async (f: KhoTapTin) => {
    setDangHoc(f.path);
    try {
      const r = await api.hocFileKho({ path: f.path, auto_approve: duyetLuon });
      showToast(`${f.ten}: ${r.note || 'đã học.'}`, r.trang_thai === 'da_hoc' ? 'success' : 'info');
      lamMoi();
    } catch (err: any) {
      showToast(err?.message || 'Không học được file.', 'error');
      lamMoi();
    } finally {
      setDangHoc(null);
    }
  };

  const chonFile = () => fileInput.current?.click();

  const taiLen = async (files: FileList | null) => {
    if (!files || files.length === 0 || !path) return;
    setDangTaiLen(true);
    setTienDo(0);
    setKetQuaTaiLen(null);
    try {
      const r = await api.taiLenKho({ path, files, auto_approve: duyetLuon, onProgress: setTienDo });
      setKetQuaTaiLen(r.ket_qua);
      const ok = r.ket_qua.filter((k) => k.ok).length;
      showToast(
        ok === r.ket_qua.length
          ? `Đã tải lên và học ${ok} file.`
          : `Học được ${ok}/${r.ket_qua.length} file — xem chi tiết bên dưới.`,
        ok === r.ket_qua.length ? 'success' : 'info'
      );
      lamMoi();
    } catch (err: any) {
      showToast(err?.message || 'Tải lên thất bại.', 'error');
    } finally {
      setDangTaiLen(false);
      if (fileInput.current) fileInput.current.value = '';
    }
  };

  const taoThuMuc = async (e: React.FormEvent) => {
    e.preventDefault();
    const ten = tenThuMucMoi.trim();
    if (!ten) return;
    try {
      const r = await api.taoThuMucKho({ path, ten });
      showToast(`Đã tạo thư mục "${r.ten}".`, 'success');
      setTenThuMucMoi('');
      setMoTaoThuMuc(false);
      lamMoi();
    } catch (err: any) {
      showToast(err?.message || 'Không tạo được thư mục.', 'error');
    }
  };

  // ---- Cây bên trái ------------------------------------------------------
  const renderNut = (tm: KhoThuMuc, sau: number): React.ReactNode => {
    const n = nut[tm.path];
    const mo = moRong.has(tm.path);
    const dangXem = path === tm.path && !ketQuaTim;
    return (
      <li key={tm.path}>
        <div
          className={`flex items-center gap-1 rounded-lg pr-2 ${
            dangXem ? 'bg-hds-soft dark:bg-slate-800 text-hds-navy dark:text-blue-300' : 'hover:bg-slate-50 dark:hover:bg-slate-800/60'
          }`}
          style={{ paddingLeft: `${sau * 14}px` }}
        >
          <button
            type="button"
            onClick={() => batTatNut(tm)}
            className="p-1 text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 shrink-0"
            aria-label={mo ? 'Thu gọn' : 'Mở rộng'}
          >
            {n?.dangTai ? (
              <RefreshCw className="w-3 h-3 animate-spin" />
            ) : mo ? (
              <ChevronDown className="w-3 h-3" />
            ) : (
              <ChevronRight className="w-3 h-3" />
            )}
          </button>
          <button
            type="button"
            onClick={() => moThuMuc(tm.path)}
            className="flex-1 min-w-0 flex items-center gap-1.5 py-1 text-left"
            title={tm.path}
          >
            {dangXem ? <FolderOpen className="w-3.5 h-3.5 shrink-0 text-amber-500" /> : <Folder className="w-3.5 h-3.5 shrink-0 text-amber-500" />}
            <span className="truncate text-xs font-medium">{tm.ten}</span>
          </button>
          <span
            className="text-[10px] font-mono text-slate-400 dark:text-slate-500 shrink-0"
            title={`${tm.da_hoc.toLocaleString('vi-VN')} đã học / ${tm.so_file.toLocaleString('vi-VN')} file trên đĩa${tm.cho_duyet ? ` · ${tm.cho_duyet} chờ duyệt` : ''}`}
          >
            {tm.da_hoc.toLocaleString('vi-VN')}/{tm.so_file.toLocaleString('vi-VN')}
          </span>
          {tm.cho_duyet > 0 && (
            <span className="text-[9px] font-bold px-1 rounded bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300 shrink-0">
              {tm.cho_duyet}
            </span>
          )}
        </div>
        {mo && n?.con && n.con.length > 0 && (
          <ul>{n.con.map((c) => renderNut(c, sau + 1))}</ul>
        )}
        {mo && n?.con && n.con.length === 0 && !n.dangTai && (
          <div className="text-[10px] text-slate-400 py-0.5" style={{ paddingLeft: `${(sau + 1) * 14 + 22}px` }}>
            (không có thư mục con)
          </div>
        )}
      </li>
    );
  };

  // ---- Đường dẫn -----------------------------------------------------------
  const breadcrumb = path ? path.split('/') : [];

  // ---- Hàng file -----------------------------------------------------------
  const nutHanhDong = (f: KhoTapTin) => (
    <div className="flex flex-wrap justify-end gap-1">
      {f.document_id != null && (
        <>
          <button onClick={() => setDetailId(f.document_id!)} className={NUT_XANH} title="Metadata + văn bản liên quan">
            <Info className="w-3 h-3" />
            <span>Chi tiết</span>
          </button>
          <button onClick={() => handlePreview(f.document_id!)} className={NUT_XANH} title="Mở bản gốc trong trình duyệt">
            <Eye className="w-3 h-3" />
            <span>Xem</span>
          </button>
          <button
            onClick={() => handleDownload(f.document_id!, f.title || f.ten)}
            disabled={downloadingId === f.document_id}
            className={NUT_XANH}
            title="Tải bản gốc về máy"
          >
            {downloadingId === f.document_id ? <RefreshCw className="w-3 h-3 animate-spin" /> : <Download className="w-3 h-3" />}
            <span>Tải về</span>
          </button>
        </>
      )}
      {canReview && (f.trang_thai === 'chua_hoc' || f.trang_thai === 'loi') && (
        <button
          onClick={() => hocNgay(f)}
          disabled={dangHoc === f.path}
          className={NUT_XANH}
          title={f.loi?.hint ? `Lần trước lỗi: ${f.loi.message || ''} ${f.loi.hint}` : 'Học file này ngay, không đợi lượt quét'}
        >
          {dangHoc === f.path ? <RefreshCw className="w-3 h-3 animate-spin" /> : <GraduationCap className="w-3 h-3" />}
          <span>Học ngay</span>
        </button>
      )}
      {isAdmin && f.document_id != null && (
        <button onClick={() => setXacNhanGo(f)} className={NUT_DO} title="Gỡ khỏi kho: bot ngừng dùng, file chuyển sang thùng đã gỡ">
          <Trash2 className="w-3 h-3" />
          <span>Bỏ</span>
        </button>
      )}
    </div>
  );

  const tongTrang = tang ? Math.max(1, Math.ceil(tang.tong_tap_tin / TRANG)) : 1;
  const trangHienTai = Math.floor(offset / TRANG) + 1;

  return (
    <div className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm overflow-hidden">
      {/* Đầu thẻ */}
      <div className="p-5 border-b border-slate-200 dark:border-slate-800 flex flex-col lg:flex-row lg:items-center justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-base font-bold text-slate-900 dark:text-slate-100 flex items-center gap-2">
            <HardDrive className="w-4 h-4 text-hds-navy dark:text-blue-300" />
            Kho tài liệu trên máy chủ
          </h3>
          <p className="text-[11px] text-slate-500 dark:text-slate-400 mt-0.5 font-mono truncate" title={rootPath}>
            {rootPath || '…'}
          </p>
        </div>
        <form onSubmit={timToanKho} className="flex items-center gap-2 lg:w-[420px]">
          <div className="relative flex-1">
            <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
            <input
              type="search"
              value={timQ}
              onChange={(e) => setTimQ(e.target.value)}
              placeholder="Tìm trong cả kho: tên, số hiệu, đường dẫn…"
              aria-label="Tìm tài liệu trong kho"
              className="w-full pl-9 pr-3 py-2 text-xs border border-slate-300 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 rounded-xl focus:ring-2 focus:ring-hds-blue focus:outline-none"
            />
          </div>
          <button type="submit" disabled={dangTim} className="px-3.5 py-2 bg-hds-navy hover:bg-hds-navy-light text-white text-xs font-bold rounded-xl shrink-0 disabled:opacity-60">
            {dangTim ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : 'Tìm'}
          </button>
          {ketQuaTim && (
            <button type="button" onClick={() => setKetQuaTim(null)} className="p-2 text-slate-400 hover:text-slate-700 dark:hover:text-slate-200" aria-label="Đóng kết quả tìm">
              <X className="w-4 h-4" />
            </button>
          )}
        </form>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[300px_1fr] min-h-[420px]">
        {/* Cây thư mục */}
        <div className="border-b lg:border-b-0 lg:border-r border-slate-200 dark:border-slate-800 p-3 overflow-auto max-h-[560px]">
          <button
            type="button"
            onClick={() => moThuMuc('')}
            className={`w-full flex items-center gap-1.5 px-2 py-1.5 rounded-lg text-xs font-bold ${
              path === '' && !ketQuaTim ? 'bg-hds-soft dark:bg-slate-800 text-hds-navy dark:text-blue-300' : 'hover:bg-slate-50 dark:hover:bg-slate-800/60'
            }`}
          >
            <HardDrive className="w-3.5 h-3.5" />
            <span>Kho tài liệu</span>
          </button>
          {goc === null ? (
            <div className="text-xs text-slate-400 p-2 flex items-center gap-2">
              <RefreshCw className="w-3 h-3 animate-spin" /> Đang tải cây…
            </div>
          ) : (
            <ul className="mt-1">{goc.map((tm) => renderNut(tm, 0))}</ul>
          )}
        </div>

        {/* Nội dung ngăn / kết quả tìm */}
        <div className="p-4 space-y-3 min-w-0">
          {ketQuaTim ? (
            <>
              <div className="text-xs text-slate-600 dark:text-slate-300">
                <span className="font-bold">{ketQuaTim.length}</span> kết quả cho "{timQ.trim()}" (chỉ tài liệu đã có bản ghi; tối đa 100)
              </div>
              {ketQuaTim.length === 0 ? (
                <div className="p-8 text-center text-xs text-slate-500">Không thấy tài liệu nào khớp.</div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs min-w-[720px]">
                    <thead className="bg-slate-50 dark:bg-slate-800 text-slate-600 dark:text-slate-300 font-bold uppercase tracking-wider text-[10px]">
                      <tr>
                        <th className="p-2.5">Tài liệu</th>
                        <th className="p-2.5">Thư mục</th>
                        <th className="p-2.5">Trạng thái</th>
                        <th className="p-2.5 text-right">Thao tác</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                      {ketQuaTim.map((k) => (
                        <tr key={k.document_id} className="hover:bg-hds-soft/60 dark:hover:bg-slate-800/50">
                          <td className="p-2.5 max-w-sm">
                            <div className="font-semibold text-slate-900 dark:text-slate-100 break-words">{k.title}</div>
                            <div className="text-[10px] text-slate-400 font-mono">
                              ID {k.document_id} · {DOC_TYPE_LABELS[k.doc_type] || k.doc_type}
                              {k.so_hieu ? ` · ${k.so_hieu}` : ''}
                              {k.client_name ? ` · ${k.client_name}` : ''}
                            </div>
                          </td>
                          <td className="p-2.5 text-slate-600 dark:text-slate-300 font-mono text-[10px] break-all max-w-xs">
                            {k.path ? (
                              <button type="button" onClick={() => { moThuMuc(k.thu_muc); setLocTen(k.ten || ''); setLocTenApDung(k.ten || ''); taiTang(k.thu_muc, k.ten || '', 0); }} className="text-hds-navy dark:text-blue-300 hover:underline text-left" title="Mở thư mục chứa file này">
                                {k.thu_muc || '(gốc kho)'}
                              </button>
                            ) : (
                              <span className="text-slate-400">(không có file trong kho)</span>
                            )}
                          </td>
                          <td className="p-2.5"><TrangThaiBadge trangThai={k.trang_thai} /></td>
                          <td className="p-2.5 text-right">
                            <div className="flex flex-wrap justify-end gap-1">
                              <button onClick={() => setDetailId(k.document_id)} className={NUT_XANH}><Info className="w-3 h-3" /><span>Chi tiết</span></button>
                              {k.path && (
                                <button onClick={() => handlePreview(k.document_id)} className={NUT_XANH}><Eye className="w-3 h-3" /><span>Xem</span></button>
                              )}
                              {isAdmin && (
                                <button onClick={() => setXacNhanGo(k)} className={NUT_DO}><Trash2 className="w-3 h-3" /><span>Bỏ</span></button>
                              )}
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          ) : (
            <>
              {/* Đường dẫn + hành động của ngăn */}
              <div className="flex flex-col md:flex-row md:items-center justify-between gap-2">
                <nav className="text-xs text-slate-600 dark:text-slate-300 flex flex-wrap items-center gap-1 min-w-0" aria-label="Đường dẫn">
                  <button type="button" onClick={() => moThuMuc('')} className="hover:underline font-semibold">Kho</button>
                  {breadcrumb.map((seg, i) => {
                    const p = breadcrumb.slice(0, i + 1).join('/');
                    return (
                      <React.Fragment key={p}>
                        <span className="text-slate-300">/</span>
                        <button type="button" onClick={() => moThuMuc(p)} className={`hover:underline ${i === breadcrumb.length - 1 ? 'font-bold text-slate-900 dark:text-slate-100' : ''}`}>
                          {seg}
                        </button>
                      </React.Fragment>
                    );
                  })}
                </nav>
                <div className="flex flex-wrap items-center gap-1.5 shrink-0">
                  {canReview && (
                    <label className="flex items-center gap-1 text-[11px] text-slate-600 dark:text-slate-300 cursor-pointer mr-1" title="Với người có quyền duyệt: file trích xuất sạch được dùng ngay, không qua hàng chờ">
                      <input type="checkbox" checked={duyetLuon} onChange={(e) => setDuyetLuon(e.target.checked)} className="rounded" />
                      Duyệt luôn
                    </label>
                  )}
                  {canReview && (
                    <button type="button" onClick={chonFile} disabled={!path || dangTaiLen} className={NUT_XANH} title={path ? `Tải file vào "${tang?.ten}"` : 'Chọn một ngăn (thư mục) trước — bộ quét xếp loại tài liệu theo thư mục'}>
                      {dangTaiLen ? <RefreshCw className="w-3 h-3 animate-spin" /> : <Upload className="w-3 h-3" />}
                      <span>{dangTaiLen ? `Đang tải ${tienDo}%` : 'Tải lên vào đây'}</span>
                    </button>
                  )}
                  {canReview && (
                    <button type="button" onClick={() => setMoTaoThuMuc((v) => !v)} className={NUT_XANH} title="Tạo thư mục con trong ngăn đang xem">
                      <FolderPlus className="w-3 h-3" />
                      <span>Thư mục con</span>
                    </button>
                  )}
                  <button type="button" onClick={lamMoi} className={NUT_XANH} title="Tải lại">
                    <RefreshCw className={`w-3 h-3 ${dangTai ? 'animate-spin' : ''}`} />
                  </button>
                  <input ref={fileInput} type="file" multiple className="hidden" onChange={(e) => taiLen(e.target.files)} />
                </div>
              </div>

              {moTaoThuMuc && (
                <form onSubmit={taoThuMuc} className="flex items-center gap-2 text-xs">
                  <input
                    autoFocus
                    value={tenThuMucMoi}
                    onChange={(e) => setTenThuMucMoi(e.target.value)}
                    placeholder={`Tên thư mục con trong "${tang?.ten || 'Kho'}"`}
                    className="flex-1 px-3 py-1.5 border border-slate-300 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 rounded-lg focus:ring-2 focus:ring-hds-blue focus:outline-none"
                  />
                  <button type="submit" className="px-3 py-1.5 bg-hds-navy text-white font-bold rounded-lg">Tạo</button>
                  <button type="button" onClick={() => setMoTaoThuMuc(false)} className="px-2 py-1.5 text-slate-500">Huỷ</button>
                </form>
              )}

              {ketQuaTaiLen && (
                <div className="rounded-xl border border-slate-200 dark:border-slate-700 p-3 text-[11px] space-y-1 bg-slate-50 dark:bg-slate-800/60">
                  <div className="flex items-center justify-between">
                    <span className="font-bold text-slate-700 dark:text-slate-200">Kết quả tải lên</span>
                    <button type="button" onClick={() => setKetQuaTaiLen(null)} className="text-slate-400 hover:text-slate-700" aria-label="Đóng"><X className="w-3.5 h-3.5" /></button>
                  </div>
                  {ketQuaTaiLen.map((k, i) => (
                    <div key={i} className="flex flex-wrap items-center gap-2">
                      <span className="font-mono truncate max-w-xs" title={k.filename}>{k.filename}</span>
                      {k.ok && k.trang_thai ? <TrangThaiBadge trangThai={k.trang_thai} /> : <TrangThaiBadge trangThai="loi" />}
                      <span className={k.ok ? 'text-slate-600 dark:text-slate-300' : 'text-rose-700 dark:text-rose-300'}>{k.ok ? k.note : k.loi}</span>
                      {k.warnings && k.warnings.length > 0 && <span className="text-amber-700 dark:text-amber-300">· {k.warnings[0]}</span>}
                    </div>
                  ))}
                </div>
              )}

              {/* Lọc trong ngăn */}
              <form onSubmit={apDungLoc} className="flex items-center gap-2 text-xs">
                <input
                  type="search"
                  value={locTen}
                  onChange={(e) => setLocTen(e.target.value)}
                  placeholder={tang ? `Lọc ${tang.tong_tap_tin.toLocaleString('vi-VN')} file trong "${tang.ten}" theo tên…` : 'Lọc theo tên file…'}
                  aria-label="Lọc file trong thư mục"
                  className="flex-1 px-3 py-1.5 border border-slate-300 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 rounded-lg focus:ring-2 focus:ring-hds-blue focus:outline-none"
                />
                <button type="submit" className="px-3 py-1.5 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 font-bold rounded-lg">Lọc</button>
              </form>

              {loiTai ? (
                <div className="p-6 text-center text-xs text-rose-700 dark:text-rose-300">{loiTai}</div>
              ) : dangTai && !tang ? (
                <div className="p-8 text-center text-xs text-slate-500 flex items-center justify-center gap-2">
                  <RefreshCw className="w-4 h-4 animate-spin" /> Đang tải…
                </div>
              ) : tang && tang.tap_tin.length === 0 ? (
                <div className="p-8 text-center text-xs text-slate-500">
                  {tang.thu_muc.length > 0
                    ? 'Ngăn này chỉ có thư mục con — chọn một thư mục bên trái để xem file.'
                    : 'Thư mục trống. Bấm "Tải lên vào đây" để thêm tài liệu.'}
                </div>
              ) : tang ? (
                <>
                  <div className="overflow-x-auto">
                    <table className="w-full text-left text-xs min-w-[820px]">
                      <thead className="bg-slate-50 dark:bg-slate-800 text-slate-600 dark:text-slate-300 font-bold uppercase tracking-wider text-[10px]">
                        <tr>
                          <th className="p-2.5">Tên file</th>
                          <th className="p-2.5">Trạng thái</th>
                          <th className="p-2.5">Loại</th>
                          <th className="p-2.5 text-right">Kích thước</th>
                          <th className="p-2.5">Sửa lúc</th>
                          <th className="p-2.5 text-right">Thao tác</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                        {tang.tap_tin.map((f) => (
                          <tr key={f.path} className="hover:bg-hds-soft/60 dark:hover:bg-slate-800/50">
                            <td className="p-2.5 max-w-md">
                              <div className="font-semibold text-slate-900 dark:text-slate-100 break-words leading-snug">{f.ten}</div>
                              {(f.so_hieu || f.client_name || f.document_id != null) && (
                                <div className="text-[10px] text-slate-400 font-mono">
                                  {f.document_id != null ? `ID ${f.document_id}` : ''}
                                  {f.so_hieu ? ` · ${f.so_hieu}` : ''}
                                  {f.client_name ? ` · ${f.client_name}` : ''}
                                  {f.so_doan != null ? ` · ${f.so_doan} đoạn` : ''}
                                </div>
                              )}
                              {f.loi && (
                                <div className="text-[10px] text-rose-600 dark:text-rose-300">
                                  {f.loi.message} {f.loi.hint ? `— ${f.loi.hint}` : ''}
                                </div>
                              )}
                            </td>
                            <td className="p-2.5"><TrangThaiBadge trangThai={f.trang_thai} /></td>
                            <td className="p-2.5 text-slate-600 dark:text-slate-300 whitespace-nowrap">{f.doc_type ? DOC_TYPE_LABELS[f.doc_type] || f.doc_type : '—'}</td>
                            <td className="p-2.5 text-right font-mono text-slate-500 whitespace-nowrap">{dinhDangKichThuoc(f.kich_thuoc)}</td>
                            <td className="p-2.5 font-mono text-slate-500 whitespace-nowrap">{f.sua_luc}</td>
                            <td className="p-2.5 text-right">{nutHanhDong(f)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {tongTrang > 1 && (
                    <div className="flex items-center justify-between text-[11px] text-slate-500">
                      <span>
                        Trang {trangHienTai}/{tongTrang} · {tang.tong_tap_tin.toLocaleString('vi-VN')} file
                      </span>
                      <div className="flex gap-1">
                        <button type="button" disabled={offset === 0} onClick={() => doiTrang(Math.max(0, offset - TRANG))} className={NUT_XANH}>Trước</button>
                        <button type="button" disabled={offset + TRANG >= tang.tong_tap_tin} onClick={() => doiTrang(offset + TRANG)} className={NUT_XANH}>Sau</button>
                      </div>
                    </div>
                  )}
                </>
              ) : null}
            </>
          )}
        </div>
      </div>

      {/* Xác nhận gỡ */}
      {xacNhanGo && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-labelledby="kho-go-title">
          <div className="bg-white dark:bg-slate-900 rounded-2xl shadow-xl max-w-md w-full p-5 space-y-3">
            <h4 id="kho-go-title" className="font-bold text-slate-900 dark:text-slate-100">Gỡ tài liệu khỏi kho?</h4>
            <p className="text-xs text-slate-600 dark:text-slate-300 break-words">
              <span className="font-semibold">{'title' in xacNhanGo && xacNhanGo.title ? xacNhanGo.title : xacNhanGo.ten}</span>
            </p>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Bot ngừng dùng tài liệu này ngay. File gốc được chuyển sang thùng đã gỡ trên máy chủ (không xoá hẳn), bộ quét sẽ không học lại.
            </p>
            <div className="flex justify-end gap-2 pt-1">
              <button type="button" onClick={() => setXacNhanGo(null)} className="px-3 py-1.5 text-xs font-semibold text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg">Huỷ</button>
              <button type="button" onClick={goTaiLieu} disabled={dangGo} className="px-3 py-1.5 text-xs font-bold text-white bg-hds-red hover:bg-red-700 rounded-lg disabled:opacity-60 inline-flex items-center gap-1">
                {dangGo ? <RefreshCw className="w-3 h-3 animate-spin" /> : <Trash2 className="w-3 h-3" />}
                Gỡ khỏi kho
              </button>
            </div>
          </div>
        </div>
      )}

      {detailId != null && (
        <DocumentDetailModal docId={detailId} canReview={canReview} onClose={() => { setDetailId(null); lamMoi(); }} />
      )}
    </div>
  );
};
