/**
 * DocumentReviewTab — hàng chờ DUYỆT NHÃN tài liệu.
 *
 * Ba việc phải làm được trên màn này (yêu cầu 20/09/2026):
 *  1. Thấy RÕ tài liệu là cái gì — trước hết là VỊ TRÍ TRONG CÂY THƯ MỤC kho.
 *     Ngăn chứa tệp chính là căn cứ gán nhãn ("9. HỒ SƠ KHÁCH HÀNG" thì là hồ
 *     sơ khách), mà tiêu đề không nói lên điều đó.
 *  2. LỌC được: hàng chờ thật có hàng nghìn tài liệu; không lọc thì người duyệt
 *     chỉ nhìn thấy 50 cái đầu bảng và không cách nào chọn đúng lô cần xử lý.
 *  3. DUYỆT NHANH: cái đã rõ thì một cú bấm (hoặc chọn nhiều rồi duyệt cả lô);
 *     cái đáng ngờ thì mở khung đối chiếu hai cột (bản gốc ↔ nội dung AI đọc).
 *
 * Chốt an toàn giữ nguyên: mức "Hồ sơ khách hàng" bắt buộc có khách sở hữu —
 * cả ở nút duyệt từng cái lẫn duyệt nhanh hàng loạt (backend chặn lần nữa).
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useApp } from '../../context/AppContext';
import * as api from '../../api';
import type { Client, PendingReviewDoc, ReviewBoLoc } from '../../types';
import { ACCESS_LEVELS, DOC_TYPES, DOC_TYPE_LABELS } from '../../constants';
import {
  AlertCircle, CheckCircle2, ChevronDown, Columns2, Eye, FileText, FolderTree,
  Loader2, RefreshCw, Search, X, Zap,
} from 'lucide-react';
import { DocumentCompareModal, type CompareLabels } from './DocumentCompareModal';

interface DocForm extends CompareLabels {
  error: string | null;
  isSubmitting: boolean;
}

const MOI_TRANG = 50;

const inputClass =
  'w-full px-3 py-2 border rounded-xl bg-white dark:bg-slate-800 dark:text-slate-100 border-slate-300 dark:border-slate-700 focus:ring-2 focus:ring-hds-blue focus:outline-none font-medium transition-colors';

const selectLocClass =
  'px-2.5 py-2 text-xs rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 dark:text-slate-100 font-medium focus:ring-2 focus:ring-hds-blue focus:outline-none';

const NGUON_LABELS: Record<string, string> = {
  local: 'Kho máy chủ', drive: 'Drive (cũ)', manual: 'Tải tay',
  chat: 'Từ hội thoại', web: 'Tải lên web',
};

const TRANG_THAI_DOC: Array<{ value: string; label: string; key?: keyof ReviewBoLoc['trang_thai'] }> = [
  { value: '', label: 'Mọi trạng thái đọc' },
  { value: 'doc_loi', label: 'Đọc lỗi nhiều', key: 'doc_loi' },
  { value: 'canh_bao', label: 'Trích xuất có cảnh báo', key: 'canh_bao' },
  { value: 'da_sua', label: 'Đã sửa tay', key: 'da_sua' },
  { value: 'chua_cham', label: 'Chưa chấm chất lượng', key: 'chua_cham' },
  { value: 'sach', label: 'Đọc sạch', key: 'sach' },
];

const SAP_XEP = [
  { value: 'can_soat', label: 'Cần soát trước (đọc lỗi nhiều)' },
  { value: 'de_duyet', label: 'Dễ duyệt trước (đọc sạch)' },
  { value: 'moi_nhat', label: 'Mới nạp trước' },
  { value: 'cu_nhat', label: 'Cũ nhất trước' },
  { value: 'duong_dan', label: 'Theo đường dẫn thư mục' },
  { value: 'ten', label: 'Theo tên tài liệu' },
];

const formTuDoc = (doc: PendingReviewDoc): DocForm => ({
  doc_type: doc.doc_type || 'other',
  access_level: doc.access_level || 'internal',
  client_id: doc.client_id != null ? String(doc.client_id) : '',
  so_hieu: doc.so_hieu || '',
  loai_van_ban: doc.loai_van_ban || '',
  trich_yeu: doc.trich_yeu || '',
  ngay_ban_hanh: doc.ngay_ban_hanh || '',
  ngay_hieu_luc: doc.ngay_hieu_luc || '',
  error: null,
  isSubmitting: false,
});

/** Cây thư mục thật sâu tới 7-8 cấp (kho có cả thư mục giải nén lồng nhau).
 *  Giữ NGĂN (cấp 1) và hai cấp cuối, giữa thay bằng "…"; đường dẫn đầy đủ nằm
 *  ở thuộc tính title. Ngăn là căn cứ gán nhãn, hai cấp cuối cho biết bộ hồ sơ
 *  nào — khúc giữa chỉ làm dài dòng. */
const rutGonCay = (thuMuc?: string | null): string[] => {
  const parts = (thuMuc || '').split('/').filter(Boolean);
  if (parts.length <= 4) return parts;
  return [parts[0], '…', parts[parts.length - 2], parts[parts.length - 1]];
};

/** 2411520 → "2,3 MB" — người duyệt cần biết tệp nặng cỡ nào trước khi mở. */
const doLon = (byte?: number | null): string => {
  if (byte == null) return '';
  if (byte < 1024) return `${byte} B`;
  if (byte < 1024 * 1024) return `${(byte / 1024).toFixed(0)} KB`;
  return `${(byte / 1024 / 1024).toFixed(1)} MB`;
};

export const DocumentReviewTab: React.FC = () => {
  const { showToast } = useApp();
  const [docs, setDocs] = useState<PendingReviewDoc[]>([]);
  const [clients, setClients] = useState<Client[]>([]);
  const [boLoc, setBoLoc] = useState<ReviewBoLoc | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [dangTaiThem, setDangTaiThem] = useState(false);
  const [conNua, setConNua] = useState(false);
  const [docForms, setDocForms] = useState<Record<string, DocForm>>({});
  const [chon, setChon] = useState<Set<number>>(new Set());
  const [dangDuyetLo, setDangDuyetLo] = useState(false);
  const [moDoiChieu, setMoDoiChieu] = useState<number | null>(null);
  const [moDanhTinh, setMoDanhTinh] = useState<Set<number>>(new Set());

  // Bộ lọc. `q` gõ tới đâu lọc tới đó nhưng có hoãn 400ms — hàng chờ hàng
  // nghìn dòng, gọi máy chủ theo từng phím là tự làm nghẽn chính mình.
  const [q, setQ] = useState('');
  const [qHoan, setQHoan] = useState('');
  const [ngan, setNgan] = useState('');
  const [loai, setLoai] = useState('');
  const [nguon, setNguon] = useState('');
  const [trangThai, setTrangThai] = useState('');
  const [sapXep, setSapXep] = useState('can_soat');

  useEffect(() => {
    const t = setTimeout(() => setQHoan(q.trim()), 400);
    return () => clearTimeout(t);
  }, [q]);

  const thamSo = useMemo(
    () => ({ q: qHoan, ngan, doc_type: loai, nguon, trang_thai: trangThai, sap_xep: sapXep }),
    [qHoan, ngan, loai, nguon, trangThai, sapXep]
  );

  const napForm = (data: PendingReviewDoc[], gop = false) => {
    setDocForms((prev) => {
      const tiep = gop ? { ...prev } : {};
      data.forEach((doc) => { tiep[String(doc.id)] = formTuDoc(doc); });
      return tiep;
    });
  };

  const taiDanhSach = useCallback(async () => {
    setIsLoading(true);
    try {
      // Danh sách khách hàng dùng cho ô chọn chủ sở hữu; lỗi ở đây không chặn
      // màn hình. Số liệu bộ lọc cũng vậy — mất nó thì chỉ mất các con số.
      const [data, clientList, loc] = await Promise.all([
        api.getPendingReviews({ ...thamSo, limit: MOI_TRANG, offset: 0 }),
        api.getClients().catch(() => [] as Client[]),
        api.getReviewFilters().catch(() => null as ReviewBoLoc | null),
      ]);
      setDocs(data);
      setConNua(data.length >= MOI_TRANG);
      setClients(clientList);
      if (loc) setBoLoc(loc);
      napForm(data);
      setChon(new Set());
    } catch (err: any) {
      showToast(err?.message || 'Lỗi khi tải danh sách tài liệu chờ duyệt', 'error');
    } finally {
      setIsLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [thamSo]);

  useEffect(() => { taiDanhSach(); }, [taiDanhSach]);

  const taiThem = async () => {
    setDangTaiThem(true);
    try {
      const data = await api.getPendingReviews({
        ...thamSo, limit: MOI_TRANG, offset: docs.length,
      });
      setDocs((prev) => [...prev, ...data]);
      napForm(data, true);
      setConNua(data.length >= MOI_TRANG);
    } catch (err: any) {
      showToast(err?.message || 'Không tải thêm được.', 'error');
    } finally {
      setDangTaiThem(false);
    }
  };

  const patchForm = (docId: string, patch: Partial<DocForm>) => {
    setDocForms((prev) => ({ ...prev, [docId]: { ...prev[docId], ...patch } }));
  };

  const xoaKhoiDanhSach = (ids: number[]) => {
    const bo = new Set(ids);
    setDocs((prev) => prev.filter((d) => !bo.has(d.id)));
    setChon((prev) => {
      const tiep = new Set(prev);
      ids.forEach((id) => tiep.delete(id));
      return tiep;
    });
    setBoLoc((prev) => (prev ? { ...prev, tong: Math.max(0, prev.tong - ids.length) } : prev));
  };

  const handleApprove = async (docId: number) => {
    const key = String(docId);
    const form = docForms[key];
    if (!form) return;

    // Ràng buộc client_doc_must_have_owner trong schema.sql
    if (form.access_level === 'client' && !form.client_id) {
      patchForm(key, { error: 'Mức "Hồ sơ khách hàng" bắt buộc phải chọn khách hàng sở hữu.' });
      return;
    }
    patchForm(key, { isSubmitting: true, error: null });
    try {
      await api.approveReview(docId, {
        doc_type: form.doc_type,
        access_level: form.access_level,
        client_id: form.client_id || null,
        // Danh tính văn bản pháp lý — gửi cả chuỗi rỗng (nghĩa "xoá") để
        // người duyệt sửa được cái máy bóc sai.
        ...(['law', 'an_le', 'ban_an'].includes(form.doc_type)
          ? {
              so_hieu: form.so_hieu,
              loai_van_ban: form.loai_van_ban,
              trich_yeu: form.trich_yeu,
              ngay_ban_hanh: form.ngay_ban_hanh,
              ngay_hieu_luc: form.ngay_hieu_luc,
            }
          : {}),
      });
      showToast('Đã duyệt và nạp tài liệu vào kho tri thức.', 'success');
      xoaKhoiDanhSach([docId]);
      setMoDoiChieu((cur) => (cur === docId ? null : cur));
    } catch (err: any) {
      const msg = err?.message || 'Không duyệt được tài liệu.';
      patchForm(key, { isSubmitting: false, error: msg });
      showToast(msg, 'error');
    }
  };

  /** Duyệt nhanh cả lô đang chọn — nhãn lấy đúng cái đang hiện trên danh sách. */
  const duyetLo = async () => {
    const items = [...chon]
      .map((id) => ({ id, form: docForms[String(id)] }))
      .filter((x) => x.form)
      .map((x) => ({
        id: x.id,
        doc_type: x.form.doc_type,
        access_level: x.form.access_level,
        client_id: x.form.client_id || null,
      }));
    if (!items.length) return;
    setDangDuyetLo(true);
    try {
      const res = await api.approveReviewBatch(items);
      if (res.ids?.length) xoaKhoiDanhSach(res.ids);
      const boQua = res.bo_qua || [];
      if (boQua.length) {
        boQua.forEach((b) => patchForm(String(b.id), { error: b.ly_do }));
        showToast(
          `Đã duyệt ${res.da_duyet} tài liệu; ${boQua.length} tài liệu bị giữ lại — xem lý do trên từng thẻ.`,
          'error'
        );
      } else {
        showToast(`Đã duyệt và nạp ${res.da_duyet} tài liệu vào kho tri thức.`, 'success');
      }
    } catch (err: any) {
      showToast(err?.message || 'Không duyệt nhanh được.', 'error');
    } finally {
      setDangDuyetLo(false);
    }
  };

  const doiChon = (id: number) => {
    setChon((prev) => {
      const tiep = new Set(prev);
      if (tiep.has(id)) tiep.delete(id); else tiep.add(id);
      return tiep;
    });
  };

  const chonHet = chon.size > 0 && chon.size === docs.length;
  const xoaLoc = () => {
    setQ(''); setNgan(''); setLoai(''); setNguon(''); setTrangThai(''); setSapXep('can_soat');
  };
  const dangLoc = Boolean(qHoan || ngan || loai || nguon || trangThai);

  const docDangMo = moDoiChieu != null ? docs.find((d) => d.id === moDoiChieu) : null;
  const formDangMo = moDoiChieu != null ? docForms[String(moDoiChieu)] : null;

  return (
    <div className="space-y-4">
      {/* Tiêu đề khu vực */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 bg-white dark:bg-slate-900 p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm">
        <div>
          <h2 className="text-lg font-bold text-slate-900 dark:text-slate-100">
            Kiểm duyệt và gán nhãn tài liệu
          </h2>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
            Xác định loại văn bản, mức truy cập bảo mật và khách hàng sở hữu trước khi nạp vào AI
            {boLoc && (
              <> · hàng chờ <strong className="text-slate-700 dark:text-slate-300">{boLoc.tong.toLocaleString('vi-VN')}</strong> tài liệu
                {/* Lọc xong mà vẫn chỉ thấy con số tổng thì người duyệt tưởng
                    bộ lọc không ăn — nói rõ đang hiện bao nhiêu. */}
                {dangLoc && <>, đang hiện <strong className="text-slate-700 dark:text-slate-300">{docs.length}</strong></>}
              </>
            )}
          </p>
        </div>
        <button
          onClick={taiDanhSach}
          className="flex items-center gap-1.5 px-3.5 py-2 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 font-semibold text-xs rounded-xl transition-colors shrink-0"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          <span>Làm mới danh sách</span>
        </button>
      </div>

      {/* Thanh bộ lọc */}
      <div className="bg-white dark:bg-slate-900 p-3 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative flex-1 min-w-[220px]">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Tìm theo tên tài liệu hoặc đường dẫn thư mục…"
              className="w-full pl-9 pr-8 py-2 text-xs rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 dark:text-slate-100 focus:ring-2 focus:ring-hds-blue focus:outline-none"
            />
            {q && (
              <button
                onClick={() => setQ('')}
                className="absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
                aria-label="Xoá ô tìm"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>

          <select value={ngan} onChange={(e) => setNgan(e.target.value)} className={selectLocClass}
                  title="Ngăn (thư mục cấp 1) trong kho tài liệu">
            <option value="">Mọi ngăn trong kho</option>
            {(boLoc?.ngan || []).map((n) => (
              <option key={n.ten} value={n.ten}>{n.ten} ({n.so})</option>
            ))}
          </select>

          <select value={loai} onChange={(e) => setLoai(e.target.value)} className={selectLocClass}>
            <option value="">Mọi loại tài liệu</option>
            {(boLoc?.loai || []).map((l) => (
              <option key={l.ma} value={l.ma}>
                {DOC_TYPE_LABELS[l.ma] || l.ma} ({l.so})
              </option>
            ))}
          </select>

          <select value={nguon} onChange={(e) => setNguon(e.target.value)} className={selectLocClass}>
            <option value="">Mọi nguồn</option>
            {(boLoc?.nguon || []).map((n) => (
              <option key={n.ma} value={n.ma}>{NGUON_LABELS[n.ma] || n.ma} ({n.so})</option>
            ))}
          </select>

          <select value={trangThai} onChange={(e) => setTrangThai(e.target.value)} className={selectLocClass}>
            {TRANG_THAI_DOC.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
                {t.key && boLoc ? ` (${boLoc.trang_thai[t.key]})` : ''}
              </option>
            ))}
          </select>

          <select value={sapXep} onChange={(e) => setSapXep(e.target.value)} className={selectLocClass}
                  title="Thứ tự hàng chờ">
            {SAP_XEP.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
          </select>

          {dangLoc && (
            <button
              onClick={xoaLoc}
              className="flex items-center gap-1 px-3 py-2 text-xs font-semibold rounded-xl bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700"
            >
              <X className="w-3.5 h-3.5" /> Bỏ lọc
            </button>
          )}
        </div>

        {/* Chọn & duyệt nhanh cả lô */}
        <div className="flex flex-wrap items-center gap-2 pt-2 border-t border-slate-100 dark:border-slate-800">
          <label className="flex items-center gap-2 text-xs font-semibold text-slate-700 dark:text-slate-300 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={chonHet}
              onChange={() => setChon(chonHet ? new Set() : new Set(docs.map((d) => d.id)))}
              className="w-4 h-4 rounded border-slate-300 dark:border-slate-600 text-hds-navy focus:ring-hds-blue"
            />
            <span>Chọn {docs.length} tài liệu đang hiện</span>
          </label>
          <span className="text-xs text-slate-500 dark:text-slate-400">
            Đã chọn <strong className="text-slate-700 dark:text-slate-300">{chon.size}</strong>
          </span>
          <button
            onClick={duyetLo}
            disabled={!chon.size || dangDuyetLo}
            className="flex items-center gap-1.5 px-4 py-2 rounded-xl font-bold text-xs text-white bg-hds-green hover:brightness-110 disabled:bg-slate-300 dark:disabled:bg-slate-700 disabled:cursor-not-allowed transition-all"
            title="Duyệt cả lô bằng đúng nhãn đang hiện trên từng thẻ"
          >
            {dangDuyetLo ? <Loader2 className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />}
            <span>{dangDuyetLo ? 'Đang duyệt…' : `Duyệt nhanh ${chon.size || ''} tài liệu đã chọn`}</span>
          </button>
          <span className="text-[11px] text-slate-500 dark:text-slate-400">
            Tài liệu mức "Hồ sơ khách hàng" chưa chọn khách sẽ bị giữ lại, không duyệt lẫn.
          </span>
        </div>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center p-12 text-slate-500 dark:text-slate-400 gap-2 text-sm">
          <RefreshCw className="w-5 h-5 animate-spin text-hds-navy dark:text-blue-400" />
          <span>Đang tải danh sách tài liệu chờ kiểm duyệt…</span>
        </div>
      ) : docs.length === 0 ? (
        <div className="bg-white dark:bg-slate-900 rounded-2xl p-12 text-center border border-slate-200 dark:border-slate-800 space-y-3">
          <CheckCircle2 className="w-12 h-12 text-hds-green mx-auto opacity-80" />
          <h3 className="font-bold text-slate-800 dark:text-slate-100 text-base">
            {dangLoc ? 'Không có tài liệu nào khớp bộ lọc' : 'Hàng chờ trống'}
          </h3>
          <p className="text-xs text-slate-500 dark:text-slate-400 max-w-sm mx-auto">
            {dangLoc
              ? 'Thử bỏ bớt điều kiện lọc để xem những tài liệu còn lại trong hàng chờ.'
              : 'Không còn tài liệu nào chờ kiểm duyệt. Mọi văn bản đã được phân loại đầy đủ.'}
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {docs.map((doc) => {
            const key = String(doc.id);
            const form: DocForm = docForms[key] || formTuDoc(doc);
            const needsClient = form.access_level === 'client';
            // AI có thể chưa chấm điểm — không hiển thị "NaN%"
            const confidencePct =
              typeof doc.confidence === 'number' ? Math.round(doc.confidence * 100) : null;
            const racPct = typeof doc.ty_le_rac === 'number' ? Math.round(doc.ty_le_rac * 100) : null;
            const daChon = chon.has(doc.id);
            const hienDanhTinh = ['law', 'an_le', 'ban_an'].includes(form.doc_type);

            return (
              <div
                key={doc.id}
                className={`bg-white dark:bg-slate-900 rounded-2xl border shadow-sm p-4 transition-colors space-y-3 ${
                  daChon
                    ? 'border-hds-blue dark:border-blue-500 ring-1 ring-hds-blue/30'
                    : 'border-slate-200 dark:border-slate-800 hover:border-slate-300 dark:hover:border-slate-700'
                }`}
              >
                {/* Thông tin tài liệu */}
                <div className="flex flex-col md:flex-row md:items-start justify-between gap-3 pb-3 border-b border-slate-100 dark:border-slate-800">
                  <div className="flex items-start gap-3 min-w-0">
                    <input
                      type="checkbox"
                      checked={daChon}
                      onChange={() => doiChon(doc.id)}
                      className="mt-2.5 w-4 h-4 shrink-0 rounded border-slate-300 dark:border-slate-600 text-hds-navy focus:ring-hds-blue"
                      aria-label={`Chọn tài liệu ${doc.id}`}
                    />
                    <span className="p-2.5 bg-hds-soft dark:bg-slate-800 text-hds-navy dark:text-blue-300 rounded-xl shrink-0">
                      <FileText className="w-5 h-5" />
                    </span>
                    <div className="min-w-0">
                      <button
                        onClick={() => setMoDoiChieu(doc.id)}
                        className="text-left font-bold text-sm text-slate-900 dark:text-slate-100 leading-snug break-words hover:text-hds-blue dark:hover:text-blue-400 transition-colors"
                        title="Mở khung đối chiếu bản gốc ↔ nội dung AI đọc"
                      >
                        {doc.title || doc.ten_tep || '(không có tiêu đề)'}
                      </button>

                      {/* VỊ TRÍ trong cây thư mục — căn cứ chính để gán nhãn */}
                      <div className="mt-1 flex items-start gap-1.5 text-[11px] text-slate-600 dark:text-slate-300">
                        <FolderTree className="w-3.5 h-3.5 mt-px shrink-0 text-slate-400" />
                        {doc.duong_dan ? (
                          <span className="break-all" title={doc.duong_dan}>
                            {rutGonCay(doc.thu_muc).map((phan, i) => (
                              <React.Fragment key={`${phan}-${i}`}>
                                <span className={i === 0 && phan !== '…'
                                  ? 'font-semibold text-slate-700 dark:text-slate-200' : ''}>
                                  {phan}
                                </span>
                                <span className="text-slate-400 mx-1">/</span>
                              </React.Fragment>
                            ))}
                            <span className="font-mono">{doc.ten_tep}</span>
                          </span>
                        ) : (
                          <span className="italic text-slate-500 dark:text-slate-400">
                            Không nằm trong cây thư mục kho
                            {doc.source_kind ? ` — nguồn: ${NGUON_LABELS[doc.source_kind] || doc.source_kind}` : ''}
                            {doc.co_tep === false ? ' · không có tệp gốc để đối chiếu' : ''}
                          </span>
                        )}
                      </div>

                      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 mt-1.5 text-[11px] text-slate-500 dark:text-slate-400">
                        <span className="bg-slate-100 dark:bg-slate-800 px-2 py-0.5 rounded font-mono">
                          ID: {doc.id}
                        </span>
                        <span>Nguồn: <strong className="text-slate-700 dark:text-slate-300">
                          {NGUON_LABELS[doc.source_kind] || doc.source_kind}
                        </strong></span>
                        {doc.so_doan != null && (
                          <span>Đoạn: <strong className="text-slate-700 dark:text-slate-300">{doc.so_doan}</strong></span>
                        )}
                        {doc.kich_thuoc != null && <span>{doLon(doc.kich_thuoc)}</span>}
                        {doc.created_at && <span>Nạp: {String(doc.created_at).slice(0, 16)}</span>}
                        {doc.nguoi_nap && <span>Bởi: {doc.nguoi_nap}</span>}
                        {doc.phong && <span>Phòng: {doc.phong}</span>}
                        <span>
                          Độ tin cậy AI:{' '}
                          {confidencePct !== null ? (
                            <strong className="text-hds-green dark:text-emerald-400">{confidencePct}%</strong>
                          ) : (
                            <strong className="text-slate-400">chưa chấm</strong>
                          )}
                        </span>
                        {doc.client_name && (
                          <span className="text-slate-700 dark:text-slate-300">
                            Khách: <strong>{doc.client_name}</strong>
                          </span>
                        )}
                        {doc.person_folder && (
                          <span className="text-slate-700 dark:text-slate-300">
                            Nhân sự: <strong>{doc.person_folder}</strong>
                          </span>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="flex flex-col items-end gap-1.5 shrink-0 self-start">
                    <span className="text-xs bg-amber-100 dark:bg-amber-950 text-amber-800 dark:text-amber-300 border border-amber-300 dark:border-amber-800 px-2.5 py-1 rounded-full font-semibold">
                      Chờ duyệt
                    </span>
                    {doc.extraction_status === 'warning' && (
                      <span
                        title={doc.extraction_warning || 'Trích xuất có cảnh báo — soát nội dung trước khi duyệt'}
                        className="text-[10px] bg-red-100 dark:bg-red-950 text-red-700 dark:text-red-300 border border-red-300 dark:border-red-800 px-2 py-0.5 rounded-full font-bold"
                      >
                        ⚠ Học không ổn — soát nội dung
                      </span>
                    )}
                    {racPct !== null && racPct > 20 && (
                      <span
                        title="Lượt duyệt hàng loạt đã giữ tài liệu này lại: phần lớn chữ đọc ra không thành từ. Mở bản gốc đối chiếu trước khi duyệt."
                        className="text-[10px] bg-red-100 dark:bg-red-950 text-red-700 dark:text-red-300 border border-red-300 dark:border-red-800 px-2 py-0.5 rounded-full font-bold"
                      >
                        ⚠ Đọc lỗi {racPct}%
                      </span>
                    )}
                    {doc.extraction_status === 'edited' && (
                      <span className="text-[10px] bg-emerald-100 dark:bg-emerald-950 text-emerald-700 dark:text-emerald-300 border border-emerald-300 dark:border-emerald-800 px-2 py-0.5 rounded-full font-bold">
                        ✓ Đã sửa tay
                      </span>
                    )}
                  </div>
                </div>

                {/* Trích đoạn nội dung */}
                {doc.preview && (
                  <blockquote className="bg-slate-50 dark:bg-slate-800/60 rounded-xl p-3 text-xs text-slate-700 dark:text-slate-300 italic border border-slate-100 dark:border-slate-700 leading-relaxed">
                    {doc.preview}
                  </blockquote>
                )}

                {form.error && (
                  <div
                    role="alert"
                    className="p-3 bg-red-50 dark:bg-red-950/50 border border-red-200 dark:border-red-900 rounded-xl text-xs text-red-800 dark:text-red-200 flex items-start gap-2"
                  >
                    <AlertCircle className="w-4 h-4 shrink-0 mt-px" />
                    <span className="font-medium">{form.error}</span>
                  </div>
                )}

                {/* Biểu mẫu gán nhãn */}
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs">
                  <div>
                    <label
                      htmlFor={`doc-type-${doc.id}`}
                      className="block font-semibold text-slate-700 dark:text-slate-300 mb-1"
                    >
                      Loại tài liệu
                    </label>
                    <select
                      id={`doc-type-${doc.id}`}
                      value={form.doc_type}
                      onChange={(e) => patchForm(key, { doc_type: e.target.value, error: null })}
                      className={inputClass}
                    >
                      {DOC_TYPES.map((t) => (
                        <option key={t.value} value={t.value}>{t.label}</option>
                      ))}
                    </select>
                  </div>

                  <div>
                    <label
                      htmlFor={`access-${doc.id}`}
                      className="block font-semibold text-slate-700 dark:text-slate-300 mb-1"
                    >
                      Mức truy cập
                    </label>
                    <select
                      id={`access-${doc.id}`}
                      value={form.access_level}
                      onChange={(e) => patchForm(key, { access_level: e.target.value, error: null })}
                      className={inputClass}
                    >
                      {ACCESS_LEVELS.map((a) => (
                        <option key={a.value} value={a.value}>{a.label}</option>
                      ))}
                    </select>
                    <p className="text-[10px] text-slate-500 dark:text-slate-400 mt-1 leading-snug">
                      {ACCESS_LEVELS.find((a) => a.value === form.access_level)?.hint}
                    </p>
                  </div>

                  <div>
                    <label
                      htmlFor={`client-${doc.id}`}
                      className="font-semibold text-slate-700 dark:text-slate-300 mb-1 flex items-center justify-between gap-2"
                    >
                      <span>Khách hàng sở hữu</span>
                      {needsClient && (
                        <span className="text-[10px] text-hds-red dark:text-red-400 font-bold uppercase">
                          Bắt buộc
                        </span>
                      )}
                    </label>
                    <select
                      id={`client-${doc.id}`}
                      value={form.client_id}
                      onChange={(e) => patchForm(key, { client_id: e.target.value, error: null })}
                      className={`${inputClass} ${
                        needsClient && !form.client_id
                          ? 'border-red-400 dark:border-red-700 bg-red-50/40 dark:bg-red-950/30'
                          : ''
                      }`}
                    >
                      <option value="">— Không gắn khách hàng —</option>
                      {clients.map((c) => (
                        <option key={c.id} value={String(c.id)}>[{c.code}] {c.name}</option>
                      ))}
                    </select>
                    {clients.length === 0 && (
                      <p className="text-[10px] text-amber-600 dark:text-amber-400 mt-1">
                        Chưa tải được danh sách khách hàng.
                      </p>
                    )}
                  </div>
                </div>

                {/* Danh tính văn bản pháp lý — máy bóc sẵn, người duyệt soát và
                    sửa. Số hiệu sai là căn cứ sai. Gấp lại cho danh sách gọn,
                    nhưng nút mở luôn HIỆN (không giấu sau thao tác rê chuột). */}
                {hienDanhTinh && (
                  <div className="space-y-2">
                    <button
                      onClick={() => setMoDanhTinh((prev) => {
                        const tiep = new Set(prev);
                        if (tiep.has(doc.id)) tiep.delete(doc.id); else tiep.add(doc.id);
                        return tiep;
                      })}
                      className="flex items-center gap-1.5 text-[11px] font-semibold text-hds-navy dark:text-blue-300 hover:underline"
                    >
                      <ChevronDown
                        className={`w-3.5 h-3.5 transition-transform ${moDanhTinh.has(doc.id) ? '' : '-rotate-90'}`}
                      />
                      <span>
                        Danh tính văn bản
                        {form.so_hieu ? ` · ${form.so_hieu}` : ' · chưa có số hiệu'}
                      </span>
                    </button>
                    {moDanhTinh.has(doc.id) && (
                      <div className="grid sm:grid-cols-5 gap-3 text-xs">
                        <div>
                          <label className="block font-semibold text-slate-700 dark:text-slate-300 mb-1">Số hiệu</label>
                          <input value={form.so_hieu} placeholder="45/2019/QH14"
                            onChange={(e) => patchForm(key, { so_hieu: e.target.value, error: null })}
                            className={inputClass} />
                        </div>
                        <div>
                          <label className="block font-semibold text-slate-700 dark:text-slate-300 mb-1">Loại văn bản</label>
                          <input value={form.loai_van_ban} placeholder="Bộ luật / Nghị định…"
                            onChange={(e) => patchForm(key, { loai_van_ban: e.target.value, error: null })}
                            className={inputClass} />
                        </div>
                        <div>
                          <label className="block font-semibold text-slate-700 dark:text-slate-300 mb-1">Trích yếu (tên đầy đủ)</label>
                          <input value={form.trich_yeu} placeholder="Lao động"
                            onChange={(e) => patchForm(key, { trich_yeu: e.target.value, error: null })}
                            className={inputClass} />
                        </div>
                        <div>
                          <label className="block font-semibold text-slate-700 dark:text-slate-300 mb-1">Ngày ban hành</label>
                          <input type="date" value={form.ngay_ban_hanh}
                            onChange={(e) => patchForm(key, { ngay_ban_hanh: e.target.value, error: null })}
                            className={inputClass} />
                        </div>
                        <div>
                          <label className="block font-semibold text-slate-700 dark:text-slate-300 mb-1">Ngày hiệu lực</label>
                          <input type="date" value={form.ngay_hieu_luc}
                            onChange={(e) => patchForm(key, { ngay_hieu_luc: e.target.value, error: null })}
                            className={inputClass} />
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {/* Hàng nút — luôn hiện, không giấu sau thao tác rê chuột */}
                <div className="flex flex-wrap items-center justify-end gap-2 pt-1">
                  <button
                    onClick={() => setMoDoiChieu(doc.id)}
                    className="flex items-center gap-1.5 px-3 py-2 text-[11px] font-semibold rounded-xl bg-hds-soft dark:bg-slate-800 text-hds-navy dark:text-blue-300 hover:bg-blue-100 dark:hover:bg-slate-700 transition-colors"
                    title="Xem bản gốc và nội dung AI đọc cạnh nhau, sửa được nội dung"
                  >
                    <Columns2 className="w-3.5 h-3.5" />
                    <span>Đối chiếu bản gốc ↔ AI đọc</span>
                  </button>
                  <button
                    onClick={() => api.previewDocument(doc.id).catch((e: any) =>
                      showToast(e?.message || 'Không mở được bản xem trước.', 'error'))}
                    className="flex items-center gap-1.5 px-3 py-2 text-[11px] font-semibold rounded-xl bg-hds-soft dark:bg-slate-800 text-hds-navy dark:text-blue-300 hover:bg-blue-100 dark:hover:bg-slate-700 transition-colors"
                    title="Mở bản gốc ở tab riêng"
                  >
                    <Eye className="w-3.5 h-3.5" />
                    <span>Xem bản gốc</span>
                  </button>
                  <button
                    onClick={() => handleApprove(doc.id)}
                    disabled={form.isSubmitting}
                    className="px-5 py-2.5 rounded-xl font-bold text-xs text-white shadow-sm flex items-center gap-1.5 bg-hds-navy hover:bg-hds-navy-light disabled:bg-slate-300 dark:disabled:bg-slate-700 disabled:cursor-not-allowed transition-colors"
                  >
                    {form.isSubmitting ? (
                      <>
                        <Loader2 className="w-4 h-4 animate-spin" />
                        <span>Đang xử lý…</span>
                      </>
                    ) : (
                      <>
                        <CheckCircle2 className="w-4 h-4 text-hds-gold" />
                        <span>Duyệt và nạp vào AI</span>
                      </>
                    )}
                  </button>
                </div>
              </div>
            );
          })}

          {conNua && (
            <div className="flex justify-center pt-1">
              <button
                onClick={taiThem}
                disabled={dangTaiThem}
                className="flex items-center gap-1.5 px-5 py-2.5 rounded-xl font-semibold text-xs bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors"
              >
                {dangTaiThem ? <Loader2 className="w-4 h-4 animate-spin" /> : <ChevronDown className="w-4 h-4" />}
                <span>Tải thêm {MOI_TRANG} tài liệu</span>
              </button>
            </div>
          )}
        </div>
      )}

      {docDangMo && formDangMo && (
        <DocumentCompareModal
          doc={docDangMo}
          clients={clients}
          labels={formDangMo}
          onChangeLabels={(patch) => patchForm(String(docDangMo.id), { ...patch, error: null })}
          onClose={() => setMoDoiChieu(null)}
          onApprove={() => handleApprove(docDangMo.id)}
          showToast={showToast}
        />
      )}
    </div>
  );
};
