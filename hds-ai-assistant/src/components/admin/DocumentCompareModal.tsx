/**
 * DocumentCompareModal — khung ĐỐI CHIẾU HAI CỘT khi duyệt nhãn một tài liệu.
 *
 * Trái: BẢN GỐC (trang scan / file Word đã chuyển PDF) nhúng thẳng trong khung.
 * Phải: đúng thứ BOT SẼ ĐỌC — toàn văn trích xuất (sửa được) hoặc từng đoạn RAG.
 *
 * Vì sao hai cột: chính sách 20/08/2026 bắt mắt người soát nội dung trước khi
 * duyệt, nhưng trước đây bản gốc mở ở TAB KHÁC — người duyệt phải nhớ con số ở
 * tab này rồi lật sang tab kia để so. OCR sai một chữ số là sai căn cứ, mà cái
 * sai đó chỉ lộ ra khi hai bản nằm cạnh nhau.
 *
 * Gán nhãn và bấm Duyệt ngay trong khung — mở ra rồi còn phải đóng lại mới
 * duyệt được thì không ai dùng.
 */
import React, { useEffect, useRef, useState } from 'react';
import * as api from '../../api';
import type { Client, PendingReviewDoc, ReviewChunk } from '../../types';
import { ACCESS_LEVELS, DOC_TYPES } from '../../constants';
import {
  AlertCircle, CheckCircle2, Download, ExternalLink, FileText, Loader2, Save, X,
} from 'lucide-react';

const EDIT_REASONS: Array<{ value: string; label: string }> = [
  { value: 'sua_loi_trich_xuat', label: 'Sửa lỗi trích xuất / OCR' },
  { value: 'luat_thay_doi', label: 'Luật thay đổi' },
  { value: 'rui_ro', label: 'Rủi ro' },
  { value: 'yeu_cau_khach', label: 'Yêu cầu khách hàng' },
  { value: 'khac', label: 'Khác' },
];

const inputClass =
  'w-full px-3 py-2 border rounded-xl bg-white dark:bg-slate-800 dark:text-slate-100 border-slate-300 dark:border-slate-700 focus:ring-2 focus:ring-hds-blue focus:outline-none text-xs font-medium transition-colors';

export interface CompareLabels {
  doc_type: string;
  access_level: string;
  client_id: string;
  so_hieu: string;
  loai_van_ban: string;
  trich_yeu: string;
  ngay_ban_hanh: string;
  ngay_hieu_luc: string;
}

interface Props {
  doc: PendingReviewDoc;
  clients: Client[];
  labels: CompareLabels;
  onChangeLabels: (patch: Partial<CompareLabels>) => void;
  onClose: () => void;
  /** Duyệt tài liệu này (dùng lại hàm của tab, kèm dọn danh sách). */
  onApprove: () => Promise<void> | void;
  showToast: (msg: string, kind?: any) => void;
}

export const DocumentCompareModal: React.FC<Props> = ({
  doc, clients, labels, onChangeLabels, onClose, onApprove, showToast,
}) => {
  // --- Cột trái: bản gốc ---
  const [goc, setGoc] = useState<{ url: string; mime: string } | null>(null);
  const [gocLoi, setGocLoi] = useState<string | null>(null);
  const [gocDangTai, setGocDangTai] = useState(false);
  // Giữ url trong ref để dọn được kể cả khi component đã tháo.
  const urlRef = useRef<string | null>(null);

  // --- Cột phải: nội dung bot đọc ---
  const [cach, setCach] = useState<'toan_van' | 'theo_doan'>('toan_van');
  const [noiDung, setNoiDung] = useState('');
  const [soDoan, setSoDoan] = useState<number | null>(null);
  const [trangThai, setTrangThai] = useState<string | null>(null);
  const [dangTai, setDangTai] = useState(true);
  const [dangLuu, setDangLuu] = useState(false);
  const [lyDo, setLyDo] = useState('sua_loi_trich_xuat');
  const [ghiChu, setGhiChu] = useState('');
  const [doan, setDoan] = useState<ReviewChunk[] | null>(null);
  const [dangDuyet, setDangDuyet] = useState(false);
  const [loiNhan, setLoiNhan] = useState<string | null>(null);

  useEffect(() => {
    let huy = false;
    setDangTai(true);
    api.getReviewContent(doc.id)
      .then((data) => {
        if (huy) return;
        setNoiDung(data.content || '');
        setSoDoan(data.chunk_count ?? null);
        setTrangThai(data.extraction_status || null);
      })
      .catch((err: any) => {
        if (!huy) showToast(err?.message || 'Không tải được nội dung trích xuất.', 'error');
      })
      .finally(() => { if (!huy) setDangTai(false); });
    return () => { huy = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc.id]);

  // Bản gốc: chỉ tải khi tài liệu THỰC SỰ có tệp trên máy chủ.
  useEffect(() => {
    let huy = false;
    if (doc.co_tep === false) {
      setGocLoi('Tài liệu này không có tệp gốc trên máy chủ (nạp từ hội thoại hoặc tệp đã bị dọn).');
      return () => { huy = true; };
    }
    setGocDangTai(true);
    api.previewDocumentBlob(doc.id)
      .then((res) => {
        if (huy) { URL.revokeObjectURL(res.url); return; }
        urlRef.current = res.url;
        setGoc(res);
        setGocLoi(null);
      })
      .catch((err: any) => {
        if (!huy) setGocLoi(err?.message || 'Không mở được bản gốc.');
      })
      .finally(() => { if (!huy) setGocDangTai(false); });
    return () => {
      huy = true;
      if (urlRef.current) { URL.revokeObjectURL(urlRef.current); urlRef.current = null; }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc.id]);

  // Đóng bằng phím Esc — khung chiếm cả màn hình, không ai đi tìm nút X.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const xemTheoDoan = async () => {
    setCach('theo_doan');
    if (doan) return;
    try {
      const res = await api.getReviewChunks(doc.id);
      setDoan(res.items || []);
    } catch (err: any) {
      showToast(err?.message || 'Không tải được danh sách đoạn.', 'error');
      setCach('toan_van');
    }
  };

  const luuNoiDung = async () => {
    if (noiDung.trim().length < 30) {
      showToast('Nội dung sau sửa quá ngắn (dưới 30 ký tự).', 'error');
      return;
    }
    setDangLuu(true);
    try {
      const res = await api.saveReviewContent(doc.id, noiDung, lyDo, ghiChu);
      setSoDoan(res.chunks ?? null);
      setTrangThai('edited');
      setDoan(null);               // đoạn cũ không còn đúng sau khi chia lại
      // Backend vừa bóc LẠI danh tính từ bản đã sửa: không nạp đè thì nút Duyệt
      // ngay sau đó gửi số hiệu bóc từ bản OCR CŨ, xoá đúng con số vừa chữa.
      if (res.van_ban) {
        onChangeLabels({
          so_hieu: res.van_ban.so_hieu || '',
          loai_van_ban: res.van_ban.loai_van_ban || '',
          trich_yeu: res.van_ban.trich_yeu || '',
          ngay_ban_hanh: res.van_ban.ngay_ban_hanh || '',
          ngay_hieu_luc: res.van_ban.ngay_hieu_luc || '',
        });
      }
      showToast(`Đã lưu nội dung sửa và tạo lại ${res.chunks} đoạn vector.`, 'success');
    } catch (err: any) {
      showToast(err?.message || 'Không lưu được nội dung.', 'error');
    } finally {
      setDangLuu(false);
    }
  };

  const duyet = async () => {
    if (labels.access_level === 'client' && !labels.client_id) {
      setLoiNhan('Mức "Hồ sơ khách hàng" bắt buộc phải chọn khách hàng sở hữu.');
      return;
    }
    setLoiNhan(null);
    setDangDuyet(true);
    try {
      await onApprove();
    } finally {
      setDangDuyet(false);
    }
  };

  const canDanhTinh = ['law', 'an_le', 'ban_an'].includes(labels.doc_type);
  const pdfGoc = (goc?.mime || '').includes('pdf');
  const anhGoc = (goc?.mime || '').startsWith('image/');

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-2 sm:p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="Đối chiếu bản gốc và nội dung AI đọc"
    >
      <div
        className="bg-white dark:bg-slate-900 rounded-2xl shadow-xl border border-slate-200 dark:border-slate-700 w-full max-w-[1500px] h-[94vh] flex flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Đầu khung: tên + vị trí trong cây thư mục */}
        <div className="flex items-start justify-between gap-3 px-5 py-3.5 border-b border-slate-200 dark:border-slate-800 shrink-0">
          <div className="min-w-0">
            <h3 className="text-sm font-bold text-slate-900 dark:text-slate-100 flex items-center gap-2">
              <FileText className="w-4 h-4 text-hds-navy dark:text-blue-300 shrink-0" />
              <span className="truncate">{doc.title || doc.ten_tep || '(không có tiêu đề)'}</span>
            </h3>
            <p className="text-[11px] text-slate-500 dark:text-slate-400 mt-0.5 break-all">
              <span className="font-mono bg-slate-100 dark:bg-slate-800 px-1.5 py-0.5 rounded mr-1.5">
                ID: {doc.id}
              </span>
              {doc.duong_dan ? (
                <>Vị trí: <strong className="text-slate-700 dark:text-slate-300">{doc.duong_dan}</strong></>
              ) : (
                <>Không nằm trong cây thư mục kho (nguồn: {doc.source_kind})</>
              )}
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800 shrink-0"
            aria-label="Đóng"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Hai cột */}
        <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-2 gap-0 divide-y lg:divide-y-0 lg:divide-x divide-slate-200 dark:divide-slate-800">
          {/* ----- Cột trái: bản gốc ----- */}
          <div className="flex flex-col min-h-0">
            <div className="flex items-center justify-between gap-2 px-4 py-2 bg-slate-50 dark:bg-slate-800/60 border-b border-slate-200 dark:border-slate-800">
              <span className="text-[11px] font-bold uppercase tracking-wide text-slate-600 dark:text-slate-300">
                Bản gốc {doc.duoi ? `(${doc.duoi})` : ''}
              </span>
              <div className="flex items-center gap-1.5">
                <button
                  onClick={() => api.previewDocument(doc.id).catch((e: any) =>
                    showToast(e?.message || 'Không mở được bản gốc.', 'error'))}
                  className="flex items-center gap-1 px-2 py-1 text-[11px] font-semibold rounded-lg bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800"
                  title="Mở bản gốc ở tab riêng (để phóng to)"
                >
                  <ExternalLink className="w-3.5 h-3.5" /> Tab mới
                </button>
                <button
                  onClick={() => api.downloadDocument(doc.id, doc.ten_tep || undefined).catch((e: any) =>
                    showToast(e?.message || 'Không tải được tệp gốc.', 'error'))}
                  className="flex items-center gap-1 px-2 py-1 text-[11px] font-semibold rounded-lg bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800"
                >
                  <Download className="w-3.5 h-3.5" /> Tải về
                </button>
              </div>
            </div>
            <div className="flex-1 min-h-0 bg-slate-100 dark:bg-slate-950">
              {gocDangTai ? (
                <div className="h-full flex items-center justify-center gap-2 text-xs text-slate-500 dark:text-slate-400">
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>Đang mở bản gốc… (file Word phải chuyển PDF lần đầu)</span>
                </div>
              ) : gocLoi ? (
                <div className="h-full flex flex-col items-center justify-center gap-2 p-6 text-center">
                  <AlertCircle className="w-8 h-8 text-amber-500" />
                  <p className="text-xs text-slate-600 dark:text-slate-300 max-w-sm">{gocLoi}</p>
                  <p className="text-[11px] text-slate-500 dark:text-slate-400 max-w-sm">
                    Vẫn soát được nội dung ở cột phải, nhưng không có bản gốc để đối chiếu —
                    hãy cân nhắc trước khi duyệt tài liệu quét từ giấy.
                  </p>
                </div>
              ) : anhGoc ? (
                <div className="h-full overflow-auto p-3">
                  <img src={goc!.url} alt="Bản gốc" className="max-w-full mx-auto" />
                </div>
              ) : goc ? (
                <iframe
                  src={goc.url}
                  title="Bản gốc"
                  className={`w-full h-full ${pdfGoc ? '' : 'bg-white dark:bg-slate-900'}`}
                />
              ) : null}
            </div>
          </div>

          {/* ----- Cột phải: thứ bot đọc ----- */}
          <div className="flex flex-col min-h-0">
            <div className="flex items-center justify-between gap-2 px-4 py-2 bg-slate-50 dark:bg-slate-800/60 border-b border-slate-200 dark:border-slate-800">
              <span className="text-[11px] font-bold uppercase tracking-wide text-slate-600 dark:text-slate-300">
                AI đọc được {soDoan != null && <>· {soDoan} đoạn</>}
                {trangThai === 'edited' && (
                  <span className="ml-1.5 text-hds-green dark:text-emerald-400">· đã sửa tay</span>
                )}
              </span>
              <div className="flex items-center gap-1 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg p-0.5">
                <button
                  onClick={() => setCach('toan_van')}
                  className={`px-2 py-1 text-[11px] font-semibold rounded-md transition-colors ${
                    cach === 'toan_van'
                      ? 'bg-hds-navy text-white'
                      : 'text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800'
                  }`}
                >
                  Toàn văn (sửa được)
                </button>
                <button
                  onClick={xemTheoDoan}
                  className={`px-2 py-1 text-[11px] font-semibold rounded-md transition-colors ${
                    cach === 'theo_doan'
                      ? 'bg-hds-navy text-white'
                      : 'text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800'
                  }`}
                  title="Xem đúng các đoạn bot lấy ra khi trả lời — thấy chỗ bị cắt giữa chừng"
                >
                  Theo đoạn RAG
                </button>
              </div>
            </div>

            <div className="flex-1 min-h-0 overflow-auto p-3">
              {dangTai ? (
                <div className="h-full flex items-center justify-center gap-2 text-xs text-slate-500 dark:text-slate-400">
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>Đang tải nội dung trích xuất…</span>
                </div>
              ) : cach === 'toan_van' ? (
                <textarea
                  value={noiDung}
                  onChange={(e) => setNoiDung(e.target.value)}
                  spellCheck={false}
                  className="w-full h-full min-h-[300px] text-xs font-mono leading-relaxed p-3 rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 dark:text-slate-100 focus:ring-2 focus:ring-hds-blue focus:outline-none resize-none"
                />
              ) : (
                <div className="space-y-2">
                  {/* doan === null nghĩa là ĐANG TẢI. Nhập nhằng nó với mảng
                      rỗng là hiện "tài liệu hỏng hẳn" cho mọi tài liệu lành,
                      trong đúng khoảnh khắc chờ máy chủ. */}
                  {doan === null && (
                    <div className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400 p-3">
                      <Loader2 className="w-4 h-4 animate-spin" />
                      <span>Đang tải các đoạn…</span>
                    </div>
                  )}
                  {doan !== null && doan.length === 0 && (
                    <p className="text-xs text-slate-500 dark:text-slate-400 p-3">
                      Tài liệu chưa có đoạn nào — trích xuất hỏng hẳn, đừng duyệt.
                    </p>
                  )}
                  {(doan || []).map((c) => (
                    <div
                      key={c.chunk_index}
                      className="border border-slate-200 dark:border-slate-700 rounded-xl overflow-hidden"
                    >
                      <div className="flex items-center justify-between gap-2 px-3 py-1.5 bg-slate-50 dark:bg-slate-800/60 text-[11px] text-slate-500 dark:text-slate-400">
                        <span className="font-semibold text-slate-700 dark:text-slate-300">
                          Đoạn {c.chunk_index + 1}
                          {c.section_title ? ` · ${c.section_title}` : ''}
                          {c.page_number ? ` · trang ${c.page_number}` : ''}
                        </span>
                        <span className={c.ty_le_rac >= 0.2
                          ? 'text-red-600 dark:text-red-400 font-bold'
                          : ''}>
                          {c.so_ky_tu} ký tự · đọc lỗi {Math.round(c.ty_le_rac * 100)}%
                        </span>
                      </div>
                      <pre className="p-3 text-[11px] font-mono whitespace-pre-wrap break-words text-slate-700 dark:text-slate-300 max-h-64 overflow-auto">
                        {c.content}
                      </pre>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {cach === 'toan_van' && !dangTai && (
              <div className="flex flex-wrap items-center gap-2 px-3 py-2 border-t border-slate-200 dark:border-slate-800 bg-slate-50/60 dark:bg-slate-800/40">
                <select
                  value={lyDo}
                  onChange={(e) => setLyDo(e.target.value)}
                  className="px-2 py-1.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 dark:text-slate-100 text-[11px]"
                  title="Lý do sửa — ghi vào lịch sử phiên bản của tài liệu"
                >
                  {EDIT_REASONS.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
                </select>
                <input
                  value={ghiChu}
                  onChange={(e) => setGhiChu(e.target.value)}
                  placeholder="Ghi chú sửa (tuỳ chọn)"
                  className="flex-1 min-w-[140px] px-3 py-1.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 dark:text-slate-100 text-[11px]"
                />
                <button
                  onClick={luuNoiDung}
                  disabled={dangLuu}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg font-bold text-[11px] text-white bg-hds-blue hover:bg-hds-blue-light disabled:bg-slate-300 dark:disabled:bg-slate-700 transition-colors"
                >
                  {dangLuu ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
                  <span>{dangLuu ? 'Đang chia đoạn & tạo vector…' : 'Lưu nội dung đã sửa'}</span>
                </button>
              </div>
            )}
          </div>
        </div>

        {/* Chân khung: gán nhãn + duyệt ngay tại đây */}
        <div className="shrink-0 border-t border-slate-200 dark:border-slate-800 p-3 space-y-2 bg-white dark:bg-slate-900">
          {loiNhan && (
            <div role="alert" className="flex items-start gap-2 p-2 rounded-lg bg-red-50 dark:bg-red-950/50 border border-red-200 dark:border-red-900 text-[11px] text-red-800 dark:text-red-200">
              <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-px" />
              <span className="font-medium">{loiNhan}</span>
            </div>
          )}
          <div className="grid grid-cols-1 sm:grid-cols-4 gap-2 items-end">
            <div>
              <label className="block text-[11px] font-semibold text-slate-700 dark:text-slate-300 mb-1">
                Loại tài liệu
              </label>
              <select
                value={labels.doc_type}
                onChange={(e) => onChangeLabels({ doc_type: e.target.value })}
                className={inputClass}
              >
                {DOC_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-[11px] font-semibold text-slate-700 dark:text-slate-300 mb-1">
                Mức truy cập
              </label>
              <select
                value={labels.access_level}
                onChange={(e) => onChangeLabels({ access_level: e.target.value })}
                className={inputClass}
              >
                {ACCESS_LEVELS.map((a) => <option key={a.value} value={a.value}>{a.label}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-[11px] font-semibold text-slate-700 dark:text-slate-300 mb-1">
                Khách hàng sở hữu
                {labels.access_level === 'client' && (
                  <span className="ml-1 text-hds-red dark:text-red-400 font-bold">*</span>
                )}
              </label>
              <select
                value={labels.client_id}
                onChange={(e) => onChangeLabels({ client_id: e.target.value })}
                className={`${inputClass} ${
                  labels.access_level === 'client' && !labels.client_id
                    ? 'border-red-400 dark:border-red-700 bg-red-50/40 dark:bg-red-950/30' : ''
                }`}
              >
                <option value="">— Không gắn khách hàng —</option>
                {clients.map((c) => (
                  <option key={c.id} value={String(c.id)}>[{c.code}] {c.name}</option>
                ))}
              </select>
            </div>
            <div className="flex items-center gap-2 justify-end">
              <button
                onClick={onClose}
                className="px-3 py-2.5 rounded-xl font-semibold text-xs text-slate-600 dark:text-slate-300 bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors"
              >
                Để sau
              </button>
              <button
                onClick={duyet}
                disabled={dangDuyet}
                className="flex-1 px-4 py-2.5 rounded-xl font-bold text-xs text-white shadow-sm flex items-center justify-center gap-1.5 bg-hds-navy hover:bg-hds-navy-light disabled:bg-slate-300 dark:disabled:bg-slate-700 transition-colors"
              >
                {dangDuyet ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle2 className="w-4 h-4 text-hds-gold" />}
                <span>{dangDuyet ? 'Đang xử lý…' : 'Duyệt và nạp vào AI'}</span>
              </button>
            </div>
          </div>

          {/* Danh tính văn bản luật — chỉ hiện khi nhãn là luật/án lệ/bản án */}
          {canDanhTinh && (
            <div className="grid sm:grid-cols-5 gap-2 pt-1">
              <div>
                <label className="block text-[11px] font-semibold text-slate-700 dark:text-slate-300 mb-1">Số hiệu</label>
                <input value={labels.so_hieu} placeholder="45/2019/QH14"
                  onChange={(e) => onChangeLabels({ so_hieu: e.target.value })} className={inputClass} />
              </div>
              <div>
                <label className="block text-[11px] font-semibold text-slate-700 dark:text-slate-300 mb-1">Loại văn bản</label>
                <input value={labels.loai_van_ban} placeholder="Bộ luật / Nghị định…"
                  onChange={(e) => onChangeLabels({ loai_van_ban: e.target.value })} className={inputClass} />
              </div>
              <div>
                <label className="block text-[11px] font-semibold text-slate-700 dark:text-slate-300 mb-1">Trích yếu</label>
                <input value={labels.trich_yeu} placeholder="Lao động"
                  onChange={(e) => onChangeLabels({ trich_yeu: e.target.value })} className={inputClass} />
              </div>
              <div>
                <label className="block text-[11px] font-semibold text-slate-700 dark:text-slate-300 mb-1">Ngày ban hành</label>
                <input type="date" value={labels.ngay_ban_hanh}
                  onChange={(e) => onChangeLabels({ ngay_ban_hanh: e.target.value })} className={inputClass} />
              </div>
              <div>
                <label className="block text-[11px] font-semibold text-slate-700 dark:text-slate-300 mb-1">Ngày hiệu lực</label>
                <input type="date" value={labels.ngay_hieu_luc}
                  onChange={(e) => onChangeLabels({ ngay_hieu_luc: e.target.value })} className={inputClass} />
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
