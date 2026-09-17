import React, { useCallback, useEffect, useState } from 'react';
import { useApp } from '../../context/AppContext';
import * as api from '../../api';
import type {
  KhoDanhSachKhach,
  KhoTepKhach,
  KhoTepTrongThuMucKhach,
  KhoThuMucKhach,
  KhoTinhTrangKhach,
} from '../../types';
import { TrangThaiBadge } from './KhoTaiLieuCard';
import {
  ChevronDown,
  ChevronRight,
  Eye,
  Folder,
  FolderOpen,
  GraduationCap,
  HardDrive,
  Info,
  Loader2,
  RefreshCw,
  Search,
  UserCheck,
} from 'lucide-react';

/**
 * Thư mục hồ sơ khách nhìn từ phía ĐĨA (yêu cầu 18/09/2026).
 *
 * Hồ sơ 360° chỉ thấy khách ĐÃ có tài liệu học xong — bản ghi khách sinh ra
 * lúc bộ quét học được tệp đầu tiên trong thư mục. Đo 17/09: 1.230 trên 1.571
 * thư mục khách trống hoặc chỉ chứa zip nên không hiện ở đâu cả, người xem
 * tưởng hệ thống bỏ sót. Bảng này liệt kê MỌI thư mục khách trên máy chủ, kể
 * cả trống, kèm số tệp theo nhãn học; mở một dòng là thấy từng tệp và nhãn
 * của nó, học ngay được tệp chưa học.
 */

const TINH_TRANG: Record<KhoTinhTrangKhach, { label: string; cls: string; giaiThich: string }> = {
  trong: {
    label: 'Trống',
    cls: 'bg-slate-100 text-slate-500 border-slate-200 dark:bg-slate-800 dark:text-slate-400 dark:border-slate-700',
    giaiThich:
      'Chưa có tệp nào trên máy chủ (có thể chỉ có khung thư mục con). Chép tệp vào là bộ quét tự học.',
  },
  bo_qua: {
    label: 'Bộ quét bỏ qua',
    cls: 'bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-950 dark:text-rose-300 dark:border-rose-900',
    giaiThich: 'Tên thư mục không tách được mã khách nên mọi tệp bên trong bị bỏ qua.',
  },
  khong_doc_duoc: {
    label: 'Không đọc được',
    cls: 'bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-950 dark:text-rose-300 dark:border-rose-900',
    giaiThich: 'Chỉ có định dạng không hỗ trợ (zip, rar, xls, video…) hoặc mọi tệp đều đọc lỗi.',
  },
  chua_hoc: {
    label: 'Chưa học',
    cls: 'bg-slate-100 text-slate-600 border-slate-300 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-700',
    giaiThich: 'Có tệp đọc được nhưng chưa học tệp nào — chờ lượt quét kế tiếp hoặc bấm Học ngay.',
  },
  cho_duyet: {
    label: 'Chờ duyệt',
    cls: 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950 dark:text-amber-300 dark:border-amber-900',
    giaiThich: 'Đã học nhưng chưa tệp nào được duyệt nhãn — chưa hiện trong hồ sơ 360°.',
  },
  mot_phan: {
    label: 'Học một phần',
    cls: 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950 dark:text-amber-300 dark:border-amber-900',
    giaiThich: 'Một số tệp đã học; số còn lại chờ duyệt, chưa học hoặc lỗi.',
  },
  da_hoc: {
    label: 'Đã học đủ',
    cls: 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-950 dark:text-emerald-300 dark:border-emerald-900',
    giaiThich: 'Mọi tệp đọc được đều đã học và duyệt nhãn.',
  },
};

const THU_TU_TINH_TRANG: KhoTinhTrangKhach[] = [
  'trong',
  'bo_qua',
  'khong_doc_duoc',
  'chua_hoc',
  'cho_duyet',
  'mot_phan',
  'da_hoc',
];

const LOC: { value: string; label: string }[] = [
  { value: '', label: 'Tất cả thư mục' },
  { value: 'can_xu_ly', label: 'Cần xử lý (có tệp, chưa học đủ)' },
  { value: 'co_tep', label: 'Có tệp' },
  { value: 'trong', label: 'Trống — chưa có tệp' },
  { value: 'bo_qua', label: 'Bộ quét bỏ qua (tên thư mục)' },
  { value: 'khong_doc_duoc', label: 'Không đọc được (zip/rar/lỗi)' },
  { value: 'chua_hoc', label: 'Có tệp, chưa học' },
  { value: 'cho_duyet', label: 'Chờ duyệt nhãn' },
  { value: 'mot_phan', label: 'Học một phần' },
  { value: 'da_hoc', label: 'Đã học đủ' },
];

const TRANG = 100;

const NUT =
  'inline-flex items-center gap-1 px-2 py-1 rounded-lg border text-[11px] font-bold transition-colors disabled:opacity-50';
const NUT_XANH = `${NUT} bg-hds-soft dark:bg-slate-800 text-hds-navy dark:text-blue-300 hover:bg-blue-100 dark:hover:bg-slate-700 border-blue-200 dark:border-slate-700`;

const so = (n: number) => n.toLocaleString('vi-VN');

const TinhTrangBadge: React.FC<{ tinhTrang: KhoTinhTrangKhach; lyDo?: string | null }> = ({
  tinhTrang,
  lyDo,
}) => {
  const t = TINH_TRANG[tinhTrang] || TINH_TRANG.chua_hoc;
  return (
    <span
      title={lyDo || t.giaiThich}
      className={`inline-block text-[10px] font-semibold px-2 py-0.5 rounded-full border whitespace-nowrap ${t.cls}`}
    >
      {t.label}
    </span>
  );
};

/** Ô số trong bảng: 0 mờ đi để mắt bắt ngay chỗ có số. */
const O = (n: number, nhan?: string) => (
  <td className={`p-2 text-right font-mono ${n === 0 ? 'text-slate-300 dark:text-slate-600' : nhan || ''}`}>
    {so(n)}
  </td>
);

interface MoRong {
  dangTai: boolean;
  chiTiet?: KhoTepTrongThuMucKhach;
  loi?: string;
}

export const ThuMucKhachPanel: React.FC<{ onMoHoSo?: (clientId: number) => void }> = ({
  onMoHoSo,
}) => {
  const { showToast, currentUser } = useApp();
  const canReview = Boolean(
    currentUser && (currentUser.role === 'admin' || currentUser.can_review)
  );

  const [data, setData] = useState<KhoDanhSachKhach | null>(null);
  const [q, setQ] = useState('');
  const [qApDung, setQApDung] = useState('');
  const [loc, setLoc] = useState('');
  const [offset, setOffset] = useState(0);
  const [dangTai, setDangTai] = useState(true);
  const [loiTai, setLoiTai] = useState<string | null>(null);
  const [moRong, setMoRong] = useState<Record<string, MoRong>>({});
  const [dangHoc, setDangHoc] = useState<string | null>(null);

  // Gõ tìm xong 300 ms mới hỏi máy chủ — 1.571 dòng không đáng hỏi mỗi phím.
  useEffect(() => {
    const t = setTimeout(() => {
      setQApDung(q.trim());
      setOffset(0);
    }, 300);
    return () => clearTimeout(t);
  }, [q]);

  const tai = useCallback(async () => {
    setDangTai(true);
    setLoiTai(null);
    try {
      const res = await api.getThuMucKhach({ q: qApDung, loc, offset, limit: TRANG });
      setData(res);
    } catch (err: any) {
      setLoiTai(err?.message || 'Không tải được danh sách thư mục khách');
    } finally {
      setDangTai(false);
    }
  }, [qApDung, loc, offset]);

  useEffect(() => {
    tai();
  }, [tai]);

  const doiLoc = (moi: string) => {
    setLoc(moi);
    setOffset(0);
  };

  const moThuMuc = async (path: string, epTai = false) => {
    const hien = moRong[path];
    if (hien && !epTai) {
      setMoRong((s) => {
        const c = { ...s };
        delete c[path];
        return c;
      });
      return;
    }
    setMoRong((s) => ({ ...s, [path]: { dangTai: true, chiTiet: hien?.chiTiet } }));
    try {
      const ct = await api.getTepThuMucKhach(path);
      setMoRong((s) => ({ ...s, [path]: { dangTai: false, chiTiet: ct } }));
    } catch (err: any) {
      setMoRong((s) => ({
        ...s,
        [path]: { dangTai: false, loi: err?.message || 'Không đọc được thư mục này' },
      }));
    }
  };

  const hocNgay = async (thuMuc: string, tep: KhoTepKhach) => {
    setDangHoc(tep.path);
    try {
      const kq = await api.hocFileKho({ path: tep.path });
      showToast(kq.note || (kq.ok ? `Đã học ${tep.ten}.` : kq.loi || 'Không học được'), kq.ok ? 'success' : 'error');
      await moThuMuc(thuMuc, true);
      await tai();
    } catch (err: any) {
      showToast(err?.message || `Không học được ${tep.ten}`, 'error');
    } finally {
      setDangHoc(null);
    }
  };

  const xem = async (docId: number) => {
    try {
      await api.previewDocument(docId);
    } catch (err: any) {
      showToast(err?.message || 'Không mở được bản xem trước.', 'error');
    }
  };

  const tong = data?.tong;
  const coTep = tong ? tong.tong_thu_muc - tong.theo_tinh_trang.trong : 0;
  const daHoc = tong ? tong.dem.da_hoc + tong.dem.canh_bao : 0;

  return (
    <div className="space-y-4">
      {/* Con số toàn ngăn khách — bấm một ô là lọc theo ô đó */}
      <div className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 p-5 shadow-sm space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-sm font-bold text-slate-900 dark:text-slate-100">
            <HardDrive className="w-4 h-4 text-hds-navy dark:text-blue-400" />
            <span>Thư mục khách trong kho trên máy chủ</span>
            {data?.goc?.length ? (
              <span className="font-mono font-normal text-[11px] text-slate-500 dark:text-slate-400">
                {data.goc.join(' · ')}
              </span>
            ) : null}
          </div>
          <button
            type="button"
            onClick={() => tai()}
            className={NUT_XANH}
            title="Tải lại danh sách (máy chủ nhớ kết quả 2 phút)"
          >
            <RefreshCw className={`w-3 h-3 ${dangTai ? 'animate-spin' : ''}`} />
            Tải lại
          </button>
        </div>

        {tong && (
          <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-2 text-xs">
            <div className="rounded-xl border border-slate-200 dark:border-slate-800 p-3">
              <div className="text-[10px] uppercase tracking-wide text-slate-500 dark:text-slate-400">
                Thư mục khách
              </div>
              <div className="text-xl font-black text-slate-900 dark:text-slate-100">
                {so(tong.tong_thu_muc)}
              </div>
              <div className="text-[11px] text-slate-500 dark:text-slate-400">
                có tệp {so(coTep)} · trống {so(tong.theo_tinh_trang.trong)}
              </div>
            </div>
            <div className="rounded-xl border border-slate-200 dark:border-slate-800 p-3">
              <div className="text-[10px] uppercase tracking-wide text-slate-500 dark:text-slate-400">
                Tệp trên đĩa
              </div>
              <div className="text-xl font-black text-slate-900 dark:text-slate-100">
                {so(tong.tong_tep)}
              </div>
              <div className="text-[11px] text-slate-500 dark:text-slate-400">
                đã học {so(daHoc)} · chờ duyệt {so(tong.dem.cho_duyet)}
              </div>
            </div>
            <div className="rounded-xl border border-slate-200 dark:border-slate-800 p-3">
              <div className="text-[10px] uppercase tracking-wide text-slate-500 dark:text-slate-400">
                Tệp chưa vào bot
              </div>
              <div className="text-xl font-black text-amber-700 dark:text-amber-400">
                {so(tong.dem.chua_hoc + tong.dem.loi + tong.dem.khong_ho_tro)}
              </div>
              <div className="text-[11px] text-slate-500 dark:text-slate-400">
                chưa học {so(tong.dem.chua_hoc)} · lỗi {so(tong.dem.loi)} · không hỗ trợ{' '}
                {so(tong.dem.khong_ho_tro)}
              </div>
            </div>
            <div className="col-span-2 sm:col-span-4 lg:col-span-3 rounded-xl border border-slate-200 dark:border-slate-800 p-3">
              <div className="text-[10px] uppercase tracking-wide text-slate-500 dark:text-slate-400 mb-1.5">
                Thư mục theo tình trạng — bấm để lọc
              </div>
              <div className="flex flex-wrap gap-1.5">
                {THU_TU_TINH_TRANG.map((tt) => (
                  <button
                    key={tt}
                    type="button"
                    onClick={() => doiLoc(loc === tt ? '' : tt)}
                    title={TINH_TRANG[tt].giaiThich}
                    className={`inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full border transition-colors ${
                      TINH_TRANG[tt].cls
                    } ${loc === tt ? 'ring-2 ring-hds-blue' : 'hover:opacity-80'}`}
                  >
                    {TINH_TRANG[tt].label}
                    <span className="font-mono">{so(tong.theo_tinh_trang[tt])}</span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}

        <div className="flex flex-col sm:flex-row gap-2">
          <div className="relative flex-1">
            <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
            <input
              type="search"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Tìm mã hoặc tên thư mục khách (không cần dấu)…"
              aria-label="Tìm thư mục khách"
              className="w-full pl-9 pr-3 py-2 text-xs border border-slate-300 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 rounded-xl focus:ring-2 focus:ring-hds-blue focus:outline-none transition-colors"
            />
          </div>
          <select
            value={loc}
            onChange={(e) => doiLoc(e.target.value)}
            aria-label="Lọc theo tình trạng"
            className="px-3 py-2 border border-slate-300 dark:border-slate-700 rounded-xl bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 text-xs font-bold focus:ring-2 focus:ring-hds-blue focus:outline-none transition-colors"
          >
            {LOC.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Bảng thư mục */}
      <div className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm overflow-hidden">
        {loiTai ? (
          <div className="p-8 text-center text-xs text-rose-700 dark:text-rose-300">{loiTai}</div>
        ) : dangTai && !data ? (
          <div className="p-10 flex items-center justify-center gap-2 text-sm text-slate-500 dark:text-slate-400">
            <Loader2 className="w-5 h-5 animate-spin" />
            <span>Đang đếm tệp trong từng thư mục khách…</span>
          </div>
        ) : !data || data.thu_muc.length === 0 ? (
          <div className="p-10 text-center space-y-1">
            <Folder className="w-8 h-8 text-slate-300 dark:text-slate-600 mx-auto" />
            <p className="text-xs text-slate-500 dark:text-slate-400">
              {qApDung || loc ? 'Không có thư mục nào khớp.' : 'Ngăn hồ sơ khách chưa có thư mục nào.'}
            </p>
          </div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs min-w-[900px]">
                <thead className="bg-slate-50 dark:bg-slate-800 text-slate-600 dark:text-slate-300 font-bold uppercase tracking-wider text-[10px]">
                  <tr>
                    <th scope="col" className="p-2 w-8" />
                    <th scope="col" className="p-2 w-16">Mã</th>
                    <th scope="col" className="p-2">Thư mục khách</th>
                    <th scope="col" className="p-2 text-right">Tệp</th>
                    <th scope="col" className="p-2 text-right">Đã học</th>
                    <th scope="col" className="p-2 text-right">Chờ duyệt</th>
                    <th scope="col" className="p-2 text-right">Chưa học</th>
                    <th scope="col" className="p-2 text-right">Lỗi</th>
                    <th scope="col" className="p-2 text-right">Không hỗ trợ</th>
                    <th scope="col" className="p-2">Tình trạng</th>
                    <th scope="col" className="p-2 text-right">Hồ sơ 360°</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                  {data.thu_muc.map((d: KhoThuMucKhach) => {
                    const mo = moRong[d.path];
                    return (
                      <React.Fragment key={d.path}>
                        <tr
                          className={`transition-colors ${
                            mo ? 'bg-hds-soft/60 dark:bg-slate-800/60' : 'hover:bg-hds-soft/40 dark:hover:bg-slate-800/40'
                          }`}
                        >
                          <td className="p-2 align-top">
                            <button
                              type="button"
                              onClick={() => moThuMuc(d.path)}
                              className="p-1 rounded-md hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-300"
                              aria-label={mo ? 'Thu gọn' : 'Xem tệp bên trong'}
                              title={mo ? 'Thu gọn' : 'Xem tệp bên trong'}
                            >
                              {mo ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                            </button>
                          </td>
                          <td className="p-2 align-top font-mono font-bold text-hds-navy dark:text-blue-300">
                            {d.ma || <span className="text-slate-300 dark:text-slate-600">—</span>}
                          </td>
                          <td className="p-2 align-top">
                            <button
                              type="button"
                              onClick={() => moThuMuc(d.path)}
                              className="text-left font-semibold text-slate-900 dark:text-slate-100 hover:underline break-words"
                            >
                              {d.ten}
                            </button>
                            {d.client_name && d.client_name !== d.ten_khach && (
                              <div className="text-[10px] text-slate-500 dark:text-slate-400">
                                Trong hệ thống: {d.client_name}
                              </div>
                            )}
                            {d.ly_do && (
                              <div className="text-[10px] text-rose-700 dark:text-rose-300 flex items-start gap-1 mt-0.5">
                                <Info className="w-3 h-3 shrink-0 mt-0.5" />
                                <span>{d.ly_do}</span>
                              </div>
                            )}
                          </td>
                          {O(d.so_file, 'text-slate-900 dark:text-slate-100 font-bold')}
                          {O(d.dem.da_hoc + d.dem.canh_bao, 'text-emerald-700 dark:text-emerald-300')}
                          {O(d.dem.cho_duyet, 'text-amber-700 dark:text-amber-300')}
                          {O(d.dem.chua_hoc, 'text-slate-700 dark:text-slate-200')}
                          {O(d.dem.loi, 'text-rose-700 dark:text-rose-300')}
                          {O(d.dem.khong_ho_tro, 'text-slate-500 dark:text-slate-400')}
                          <td className="p-2 align-top">
                            <TinhTrangBadge tinhTrang={d.tinh_trang} lyDo={d.ly_do} />
                          </td>
                          <td className="p-2 align-top text-right whitespace-nowrap">
                            {d.client_id ? (
                              <button
                                type="button"
                                onClick={() => onMoHoSo?.(d.client_id as number)}
                                className={NUT_XANH}
                                title="Mở hồ sơ 360° của khách này"
                              >
                                <UserCheck className="w-3 h-3" />
                                Mở
                              </button>
                            ) : (
                              <span
                                className="text-[10px] text-slate-400 dark:text-slate-500"
                                title="Khách được tạo tự động khi bộ quét học được tệp đầu tiên trong thư mục"
                              >
                                chưa có khách
                              </span>
                            )}
                          </td>
                        </tr>
                        {mo && (
                          <tr className="bg-slate-50/70 dark:bg-slate-900/60">
                            <td colSpan={11} className="p-0">
                              <ChiTietThuMuc
                                mo={mo}
                                thuMuc={d}
                                canReview={canReview}
                                dangHoc={dangHoc}
                                onHoc={(tep) => hocNgay(d.path, tep)}
                                onXem={xem}
                              />
                            </td>
                          </tr>
                        )}
                      </React.Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <div className="flex flex-wrap items-center justify-between gap-2 p-3 border-t border-slate-100 dark:border-slate-800 text-[11px] text-slate-500 dark:text-slate-400">
              <span>
                Hiện {so(data.offset + 1)}–{so(Math.min(data.offset + data.limit, data.tong_khop))} trên{' '}
                {so(data.tong_khop)} thư mục
                {qApDung || loc ? ` khớp (tổng ${so(data.tong.tong_thu_muc)})` : ''}
              </span>
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  disabled={data.offset === 0 || dangTai}
                  onClick={() => setOffset(Math.max(0, data.offset - data.limit))}
                  className={NUT_XANH}
                >
                  Trước
                </button>
                <button
                  type="button"
                  disabled={data.offset + data.limit >= data.tong_khop || dangTai}
                  onClick={() => setOffset(data.offset + data.limit)}
                  className={NUT_XANH}
                >
                  Sau
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
};

const ChiTietThuMuc: React.FC<{
  mo: MoRong;
  thuMuc: KhoThuMucKhach;
  canReview: boolean;
  dangHoc: string | null;
  onHoc: (tep: KhoTepKhach) => void;
  onXem: (docId: number) => void;
}> = ({ mo, thuMuc, canReview, dangHoc, onHoc, onXem }) => {
  if (mo.dangTai && !mo.chiTiet) {
    return (
      <div className="p-4 flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
        <Loader2 className="w-4 h-4 animate-spin" />
        <span>Đang liệt kê tệp…</span>
      </div>
    );
  }
  if (mo.loi) {
    return <div className="p-4 text-xs text-rose-700 dark:text-rose-300">{mo.loi}</div>;
  }
  const ct = mo.chiTiet;
  if (!ct) return null;
  if (ct.tap_tin.length === 0) {
    return (
      <div className="p-4 text-xs text-slate-500 dark:text-slate-400 flex items-start gap-2">
        <FolderOpen className="w-4 h-4 shrink-0" />
        <span>
          Thư mục này chưa có tệp nào trên máy chủ
          {ct.so_thu_muc_con > 0 ? ` (chỉ có ${so(ct.so_thu_muc_con)} thư mục con trống)` : ''}. Chép
          tệp của khách vào đây, bộ quét sẽ tự học ở lượt kế tiếp.
        </span>
      </div>
    );
  }
  return (
    <div className="px-3 py-2">
      <div className="text-[10px] text-slate-500 dark:text-slate-400 mb-1 font-mono">
        {ct.path} · {so(ct.tap_tin.length)} tệp · {so(ct.so_thu_muc_con)} thư mục con
      </div>
      <table className="w-full text-left text-xs">
        <thead className="text-[10px] uppercase tracking-wider text-slate-500 dark:text-slate-400">
          <tr>
            <th scope="col" className="py-1 pr-2">Tệp</th>
            <th scope="col" className="py-1 pr-2">Thư mục con</th>
            <th scope="col" className="py-1 pr-2">Nhãn</th>
            <th scope="col" className="py-1 text-right">Thao tác</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
          {ct.tap_tin.map((t) => {
            const hocDuoc = canReview && (t.trang_thai === 'chua_hoc' || t.trang_thai === 'loi');
            return (
              <tr key={t.path}>
                <td className="py-1.5 pr-2 align-top">
                  <div className="font-semibold text-slate-800 dark:text-slate-100 break-all">{t.ten}</div>
                  {t.title && t.title !== t.ten && (
                    <div className="text-[10px] text-slate-500 dark:text-slate-400">{t.title}</div>
                  )}
                  {t.loi?.message && (
                    <div className="text-[10px] text-rose-700 dark:text-rose-300">
                      {t.loi.message}
                      {t.loi.hint ? ` — ${t.loi.hint}` : ''}
                    </div>
                  )}
                </td>
                <td className="py-1.5 pr-2 align-top text-slate-500 dark:text-slate-400 break-words">
                  {t.thu_muc_con || <span className="text-slate-300 dark:text-slate-600">(ngay trong thư mục)</span>}
                </td>
                <td className="py-1.5 pr-2 align-top">
                  <TrangThaiBadge trangThai={t.trang_thai} title={t.loi?.message || undefined} />
                </td>
                <td className="py-1.5 align-top text-right whitespace-nowrap">
                  {t.document_id && (
                    <button
                      type="button"
                      onClick={() => onXem(t.document_id as number)}
                      className={`${NUT_XANH} mr-1`}
                      title="Mở bản xem trước"
                    >
                      <Eye className="w-3 h-3" />
                      Xem
                    </button>
                  )}
                  {hocDuoc && (
                    <button
                      type="button"
                      onClick={() => onHoc(t)}
                      disabled={dangHoc === t.path}
                      className={NUT_XANH}
                      title="Học ngay tệp này, không chờ lượt quét"
                    >
                      {dangHoc === t.path ? (
                        <Loader2 className="w-3 h-3 animate-spin" />
                      ) : (
                        <GraduationCap className="w-3 h-3" />
                      )}
                      Học ngay
                    </button>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {thuMuc.ly_do && (
        <p className="mt-2 text-[11px] text-rose-700 dark:text-rose-300">
          Bộ quét bỏ qua cả thư mục: {thuMuc.ly_do}
        </p>
      )}
    </div>
  );
};
