/**
 * DocumentDetailModal — thẻ căn cước một tài liệu + VĂN BẢN LIÊN QUAN hai chiều.
 *
 * Yêu cầu 31/08/2026: khi nhân viên xem một tài liệu gốc phải thấy đầy đủ
 * danh tính (tên đầy đủ, số hiệu, ngày ban hành/hiệu lực, trạng thái hiệu lực)
 * và các văn bản liên quan — cái nào thay thế nó, nó sửa đổi cái nào — với
 * tiêu đề đầy đủ, bấm mở được bản gốc nếu có trong kho và có quyền.
 *
 * Người có quyền duyệt sửa được tại chỗ: thêm/gỡ quan hệ, đổi trạng thái
 * hiệu lực. Mọi giá trị enum lấy từ constants.ts (khớp CHECK backend).
 */
import React, { useEffect, useState } from 'react';
import { useApp } from '../../context/AppContext';
import * as api from '../../api';
import type { DocRelation, DocumentDetail, DocumentVersion, SoSanhKetQua } from '../../types';
import {
  HIEU_LUC_BADGE_CLASS,
  HIEU_LUC_LABELS,
  HIEU_LUC_STATUS,
  RELATION_TYPES,
} from '../../constants';
import {
  BookOpen, Calendar, Eye, Link2, Loader2, Plus, RefreshCw, Trash2, X, History, Download, GitCompare,
} from 'lucide-react';
import { DiffView } from '../common/DiffView';

/**
 * Lịch sử sửa nội dung (document_versions) — kế hoạch ngày 3: "mỗi tài liệu
 * lưu theo từng phiên bản, không ghi đè; ai sửa, lúc nào, lý do". Chỉ người
 * có quyền duyệt xem được (nội dung đầy đủ của tài liệu).
 */
const VersionHistory: React.FC<{ docId: number; title: string; showToast: (m: string, k?: any) => void }> = ({ docId, title, showToast }) => {
  const [items, setItems] = useState<DocumentVersion[] | null>(null);
  const [tu, setTu] = useState<number | null>(null);
  const [den, setDen] = useState<number | null>(null);
  const [ketQua, setKetQua] = useState<SoSanhKetQua | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.getDocumentVersions(docId)
      .then((res) => {
        const list: DocumentVersion[] = res?.items || [];
        setItems(list);
        if (list.length >= 2) { setDen(list[0].version_no); setTu(list[1].version_no); }
      })
      .catch(() => setItems([]));
  }, [docId]);

  const compare = async () => {
    if (tu == null || den == null || tu === den) return;
    setBusy(true);
    try {
      setKetQua(await api.compareDocumentVersions(docId, tu, den));
    } catch (err: any) {
      showToast(err?.message || 'Không so sánh được.', 'error');
    } finally {
      setBusy(false);
    }
  };

  if (!items) return null;
  return (
    <div>
      <h4 className="font-bold text-slate-800 dark:text-slate-100 flex items-center gap-1.5 mb-1">
        <History className="w-3.5 h-3.5 text-hds-navy dark:text-blue-300" />
        Lịch sử sửa nội dung
      </h4>
      {items.length === 0 ? (
        <p className="text-slate-400 italic">Nội dung chưa từng được sửa tay — đang dùng bản trích xuất ban đầu.</p>
      ) : (
        <>
          <ul className="space-y-1">
            {items.map((v) => (
              <li key={v.version_no} className="flex flex-wrap items-center gap-2 text-[11px]">
                <span className="font-mono font-bold">v{v.version_no}</span>
                <span className="px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800">{v.edit_reason_label || v.edit_reason}</span>
                <span className="text-slate-500">{v.edited_by_name} · {String(v.created_at).slice(0, 16).replace('T', ' ')}</span>
                {v.edit_note && <span className="text-slate-600 dark:text-slate-300">— {v.edit_note}</span>}
              </li>
            ))}
          </ul>
          {items.length >= 2 && (
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <select value={tu ?? ''} onChange={(e) => setTu(Number(e.target.value))} className="px-2 py-1 rounded-lg border border-slate-200 dark:border-slate-700 dark:bg-slate-800 text-[11px]">
                {items.map((v) => <option key={v.version_no} value={v.version_no}>v{v.version_no}</option>)}
              </select>
              <span className="text-slate-400">→</span>
              <select value={den ?? ''} onChange={(e) => setDen(Number(e.target.value))} className="px-2 py-1 rounded-lg border border-slate-200 dark:border-slate-700 dark:bg-slate-800 text-[11px]">
                {items.map((v) => <option key={v.version_no} value={v.version_no}>v{v.version_no}</option>)}
              </select>
              <button type="button" onClick={compare} disabled={busy || tu === den} className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-hds-navy text-hds-gold text-[11px] font-bold disabled:opacity-50">
                {busy ? <Loader2 className="w-3 h-3 animate-spin" /> : <GitCompare className="w-3 h-3" />} So sánh
              </button>
              {ketQua && (
                <button
                  type="button"
                  onClick={() => api.exportDocumentCompare(docId, ketQua.tu, ketQua.den, `${title}-so-sanh-v${ketQua.tu}-v${ketQua.den}.docx`).catch((e: any) => showToast(e?.message || 'Không xuất được.', 'error'))}
                  className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg border border-slate-300 dark:border-slate-700 text-[11px] font-bold"
                >
                  <Download className="w-3 h-3" /> Word (track changes)
                </button>
              )}
            </div>
          )}
          {ketQua && <div className="mt-2"><DiffView ketQua={ketQua} labelCu={`v${ketQua.tu}`} labelMoi={`v${ketQua.den}`} /></div>}
        </>
      )}
    </div>
  );
};

interface Props {
  docId: number;
  canReview: boolean;
  onClose: () => void;
}

const RelationRow: React.FC<{
  rel: DocRelation;
  chieu: 'xuoi' | 'nguoc';
  canReview: boolean;
  onOpen: (documentId: number) => void;
  onDelete: (relId: number) => void;
}> = ({ rel, chieu, canReview, onOpen, onDelete }) => {
  // Chiều đọc cho người: xuôi = "tài liệu này <loại> X", ngược = "X <loại> tài liệu này".
  const ten =
    (rel.document_id != null ? rel.title : null) ||
    (chieu === 'xuoi' ? rel.ten_dich : rel.ten_nguon) ||
    (chieu === 'xuoi' ? rel.so_hieu_dich : rel.so_hieu_nguon) ||
    '(không rõ)';
  const soHieu = chieu === 'xuoi' ? rel.so_hieu_dich : rel.so_hieu_nguon;
  return (
    <li className="flex items-start justify-between gap-2 py-2 border-b border-slate-100 dark:border-slate-800 last:border-0">
      <div className="min-w-0 text-xs">
        <span className="inline-block mr-1.5 px-1.5 py-0.5 rounded bg-hds-soft dark:bg-slate-800 text-hds-navy dark:text-blue-300 font-bold text-[10px] uppercase whitespace-nowrap">
          {chieu === 'nguoc' ? `bị ${rel.loai_vn}` : rel.loai_vn}
        </span>
        <span className="font-semibold text-slate-800 dark:text-slate-100 break-words">{ten}</span>
        {soHieu && ten !== soHieu && (
          <span className="ml-1 text-slate-500 dark:text-slate-400">— số {soHieu}</span>
        )}
        {rel.document_id == null && (
          <span className="ml-1 text-[10px] text-slate-400">(chưa có trong kho)</span>
        )}
        {rel.trang_thai_hieu_luc && rel.trang_thai_hieu_luc !== 'chua_ro' && (
          <span className={`ml-1.5 px-1.5 py-0.5 rounded text-[9px] font-bold uppercase ${HIEU_LUC_BADGE_CLASS[rel.trang_thai_hieu_luc] || ''}`}>
            {HIEU_LUC_LABELS[rel.trang_thai_hieu_luc] || rel.trang_thai_hieu_luc}
          </span>
        )}
        {rel.nguon === 'manual' && (
          <span className="ml-1.5 text-[9px] text-purple-600 dark:text-purple-400 font-semibold">thêm tay</span>
        )}
        {rel.ghi_chu && (
          <span className="block text-[10px] text-slate-500 dark:text-slate-400 mt-0.5">{rel.ghi_chu}</span>
        )}
      </div>
      <span className="flex items-center gap-1.5 shrink-0">
        {rel.document_id != null && rel.can_open && (
          <button
            type="button"
            onClick={() => onOpen(rel.document_id!)}
            className="inline-flex items-center gap-1 text-[11px] font-semibold text-hds-navy dark:text-blue-300 hover:underline"
            title="Mở bản gốc văn bản này"
          >
            <Eye className="w-3 h-3" />
            Mở
          </button>
        )}
        {canReview && (
          <button
            type="button"
            onClick={() => onDelete(rel.id)}
            className="text-slate-400 hover:text-red-600 transition-colors"
            title="Gỡ quan hệ này"
          >
            <Trash2 className="w-3 h-3" />
          </button>
        )}
      </span>
    </li>
  );
};

export const DocumentDetailModal: React.FC<Props> = ({ docId, canReview, onClose }) => {
  const { showToast } = useApp();
  const [detail, setDetail] = useState<DocumentDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [newRel, setNewRel] = useState({ loai: 'thay_the', so_hieu_dich: '', ten_dich: '' });

  const load = async () => {
    setIsLoading(true);
    try {
      setDetail(await api.getDocumentDetail(docId));
    } catch (err: any) {
      showToast(err?.message || 'Không tải được chi tiết tài liệu.', 'error');
      onClose();
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [docId]);

  const openPreview = async (id: number) => {
    try {
      await api.previewDocument(id);
    } catch (err: any) {
      showToast(err?.message || 'Không mở được bản xem trước.', 'error');
    }
  };

  const handleDeleteRel = async (relId: number) => {
    try {
      await api.deleteDocumentRelation(docId, relId);
      showToast('Đã gỡ quan hệ.', 'success');
      load();
    } catch (err: any) {
      showToast(err?.message || 'Không gỡ được quan hệ.', 'error');
    }
  };

  const handleAddRel = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newRel.so_hieu_dich.trim() && !newRel.ten_dich.trim()) {
      showToast('Cần số hiệu hoặc tên văn bản đích.', 'error');
      return;
    }
    setSaving(true);
    try {
      await api.addDocumentRelation(docId, {
        loai: newRel.loai,
        so_hieu_dich: newRel.so_hieu_dich.trim() || null,
        ten_dich: newRel.ten_dich.trim() || null,
      });
      showToast('Đã thêm quan hệ.', 'success');
      setNewRel({ loai: 'thay_the', so_hieu_dich: '', ten_dich: '' });
      setAddOpen(false);
      load();
    } catch (err: any) {
      showToast(err?.message || 'Không thêm được quan hệ.', 'error');
    } finally {
      setSaving(false);
    }
  };

  const handleStatusChange = async (value: string) => {
    setSaving(true);
    try {
      await api.updateDocumentVanBan(docId, { trang_thai_hieu_luc: value });
      showToast('Đã cập nhật trạng thái hiệu lực.', 'success');
      load();
    } catch (err: any) {
      showToast(err?.message || 'Không cập nhật được trạng thái.', 'error');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
    >
      <div
        className="bg-white dark:bg-slate-900 rounded-2xl shadow-xl border border-slate-200 dark:border-slate-700 w-full max-w-2xl max-h-[85vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 p-5 border-b border-slate-200 dark:border-slate-800 sticky top-0 bg-white dark:bg-slate-900 rounded-t-2xl">
          <div className="min-w-0">
            <h3 className="text-sm font-bold text-slate-900 dark:text-slate-100 flex items-center gap-2">
              <BookOpen className="w-4 h-4 text-hds-navy dark:text-blue-300 shrink-0" />
              <span className="break-words">{detail?.ten_day_du || 'Chi tiết tài liệu'}</span>
            </h3>
            {detail && detail.ten_day_du !== detail.title && (
              <p className="text-[11px] text-slate-500 dark:text-slate-400 mt-0.5 break-words">
                Tên file: {detail.title}
              </p>
            )}
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600 shrink-0" aria-label="Đóng">
            <X className="w-4 h-4" />
          </button>
        </div>

        {isLoading || !detail ? (
          <div className="p-10 text-center text-slate-400">
            <Loader2 className="w-5 h-5 animate-spin mx-auto" />
          </div>
        ) : (
          <div className="p-5 space-y-5 text-xs">
            {/* Danh tính */}
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
              {detail.so_hieu && (
                <div>
                  <span className="block text-[10px] uppercase font-bold text-slate-400">Số hiệu</span>
                  <span className="font-semibold text-slate-800 dark:text-slate-100">{detail.so_hieu}</span>
                </div>
              )}
              {detail.loai_van_ban && (
                <div>
                  <span className="block text-[10px] uppercase font-bold text-slate-400">Loại văn bản</span>
                  <span className="font-semibold text-slate-800 dark:text-slate-100">{detail.loai_van_ban}</span>
                </div>
              )}
              <div>
                <span className="block text-[10px] uppercase font-bold text-slate-400">Hiệu lực</span>
                {canReview ? (
                  <select
                    value={detail.trang_thai_hieu_luc || 'chua_ro'}
                    onChange={(e) => handleStatusChange(e.target.value)}
                    disabled={saving}
                    className="mt-0.5 text-[11px] font-semibold rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-1.5 py-1"
                  >
                    {HIEU_LUC_STATUS.map((s) => (
                      <option key={s.value} value={s.value}>{s.label}</option>
                    ))}
                  </select>
                ) : (
                  <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-bold ${HIEU_LUC_BADGE_CLASS[detail.trang_thai_hieu_luc || 'chua_ro'] || ''}`}>
                    {HIEU_LUC_LABELS[detail.trang_thai_hieu_luc || 'chua_ro'] || detail.trang_thai_hieu_luc}
                  </span>
                )}
              </div>
              {detail.ngay_ban_hanh && (
                <div>
                  <span className="block text-[10px] uppercase font-bold text-slate-400">
                    <Calendar className="inline w-3 h-3 mr-0.5 -mt-0.5" />Ngày ban hành
                  </span>
                  <span className="font-mono text-slate-700 dark:text-slate-300">{detail.ngay_ban_hanh}</span>
                </div>
              )}
              {detail.ngay_hieu_luc && (
                <div>
                  <span className="block text-[10px] uppercase font-bold text-slate-400">
                    <Calendar className="inline w-3 h-3 mr-0.5 -mt-0.5" />Ngày hiệu lực
                  </span>
                  <span className="font-mono text-slate-700 dark:text-slate-300">{detail.ngay_hieu_luc}</span>
                </div>
              )}
              <div>
                <span className="block text-[10px] uppercase font-bold text-slate-400">Số đoạn đã học</span>
                <span className="font-semibold text-slate-800 dark:text-slate-100">{detail.so_doan}</span>
              </div>
            </div>

            {detail.summary && (
              <p className="text-slate-600 dark:text-slate-400 leading-relaxed border-l-2 border-hds-gold pl-2">
                {detail.summary}
              </p>
            )}

            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={() => openPreview(detail.id)}
                className="inline-flex items-center gap-1 px-2.5 py-1 bg-hds-soft dark:bg-slate-800 text-hds-navy dark:text-blue-300 hover:bg-blue-100 dark:hover:bg-slate-700 font-bold rounded-lg border border-blue-200 dark:border-slate-700 text-[11px] transition-colors"
              >
                <Eye className="w-3 h-3" />
                Xem bản gốc
              </button>
              <button
                type="button"
                onClick={load}
                className="inline-flex items-center gap-1 text-[11px] text-slate-500 hover:text-slate-700 dark:hover:text-slate-300"
              >
                <RefreshCw className="w-3 h-3" />
                Tải lại
              </button>
            </div>

            {canReview && <VersionHistory docId={detail.id} title={detail.title} showToast={showToast} />}

            {/* Văn bản liên quan — chiều NGƯỢC trước: "bị ai thay thế" là điều
                người tra cứu cần biết nhất về một văn bản. */}
            <div>
              <h4 className="font-bold text-slate-800 dark:text-slate-100 flex items-center gap-1.5 mb-1">
                <Link2 className="w-3.5 h-3.5 text-hds-navy dark:text-blue-300" />
                Văn bản liên quan
              </h4>
              {detail.quan_he_nguoc.length === 0 && detail.quan_he_xuoi.length === 0 ? (
                <p className="text-slate-400 italic">
                  Chưa ghi nhận quan hệ nào{detail.so_hieu ? '' : ' — tài liệu chưa có số hiệu'}.
                </p>
              ) : (
                <>
                  {detail.quan_he_nguoc.length > 0 && (
                    <div className="mb-2">
                      <span className="text-[10px] uppercase font-bold text-slate-400">
                        Văn bản khác nói về tài liệu này
                      </span>
                      <ul>
                        {detail.quan_he_nguoc.map((rel) => (
                          <RelationRow key={`n-${rel.id}`} rel={rel} chieu="nguoc"
                                       canReview={canReview} onOpen={openPreview}
                                       onDelete={handleDeleteRel} />
                        ))}
                      </ul>
                    </div>
                  )}
                  {detail.quan_he_xuoi.length > 0 && (
                    <div>
                      <span className="text-[10px] uppercase font-bold text-slate-400">
                        Tài liệu này dẫn tới
                      </span>
                      <ul>
                        {detail.quan_he_xuoi.map((rel) => (
                          <RelationRow key={`x-${rel.id}`} rel={rel} chieu="xuoi"
                                       canReview={canReview} onOpen={openPreview}
                                       onDelete={handleDeleteRel} />
                        ))}
                      </ul>
                    </div>
                  )}
                </>
              )}

              {canReview && (
                addOpen ? (
                  <form onSubmit={handleAddRel} className="mt-3 p-3 rounded-xl bg-hds-soft/60 dark:bg-slate-800/50 border border-blue-100 dark:border-slate-700 space-y-2">
                    <div className="grid sm:grid-cols-3 gap-2">
                      <select
                        value={newRel.loai}
                        onChange={(e) => setNewRel({ ...newRel, loai: e.target.value })}
                        className="text-[11px] rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-1.5 py-1.5"
                      >
                        {RELATION_TYPES.map((r) => (
                          <option key={r.value} value={r.value}>{r.label}</option>
                        ))}
                      </select>
                      <input
                        value={newRel.so_hieu_dich}
                        onChange={(e) => setNewRel({ ...newRel, so_hieu_dich: e.target.value })}
                        placeholder="Số hiệu đích (45/2019/QH14)"
                        className="text-[11px] rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-2 py-1.5"
                      />
                      <input
                        value={newRel.ten_dich}
                        onChange={(e) => setNewRel({ ...newRel, ten_dich: e.target.value })}
                        placeholder="Tên văn bản đích (nếu chưa rõ số)"
                        className="text-[11px] rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-2 py-1.5"
                      />
                    </div>
                    <p className="text-[10px] text-slate-500">
                      Chiều đọc: <b>tài liệu này</b> {`→ ${RELATION_TYPES.find((r) => r.value === newRel.loai)?.label.toLowerCase()} → văn bản đích`}.
                    </p>
                    <div className="flex gap-2">
                      <button
                        type="submit"
                        disabled={saving}
                        className="px-3 py-1.5 bg-hds-navy hover:bg-hds-navy-light text-white font-semibold text-[11px] rounded-lg disabled:opacity-50"
                      >
                        {saving ? 'Đang lưu…' : 'Thêm quan hệ'}
                      </button>
                      <button
                        type="button"
                        onClick={() => setAddOpen(false)}
                        className="px-3 py-1.5 text-[11px] font-semibold text-slate-500 hover:text-slate-700"
                      >
                        Huỷ
                      </button>
                    </div>
                  </form>
                ) : (
                  <button
                    type="button"
                    onClick={() => setAddOpen(true)}
                    className="mt-2 inline-flex items-center gap-1 text-[11px] font-semibold text-hds-navy dark:text-blue-300 hover:underline"
                  >
                    <Plus className="w-3 h-3" />
                    Thêm quan hệ
                  </button>
                )
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
