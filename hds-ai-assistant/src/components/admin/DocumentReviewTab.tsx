import React, { useEffect, useState } from 'react';
import { useApp } from '../../context/AppContext';
import * as api from '../../api';
import type { PendingReviewDoc, Client } from '../../types';
import { DOC_TYPES, ACCESS_LEVELS } from '../../constants';
import {
  FileText, CheckCircle2, AlertCircle, RefreshCw, Loader2, PencilLine, Save,
} from 'lucide-react';

interface DocForm {
  doc_type: string;
  access_level: string;
  client_id: string;
  error: string | null;
  isSubmitting: boolean;
}

/** Khung xem & sửa NỘI DUNG trích xuất của một tài liệu chờ duyệt.
 * PDF scan là giấy tờ pháp lý — OCR sai một con số là sai căn cứ, nên người
 * duyệt phải soát (và sửa được) nội dung trước khi bấm Duyệt. */
interface ContentEditor {
  open: boolean;
  loading: boolean;
  saving: boolean;
  content: string;
  chunkCount: number | null;
  status: string | null;
}

const inputClass =
  'w-full px-3 py-2 border rounded-xl bg-white dark:bg-slate-800 dark:text-slate-100 border-slate-300 dark:border-slate-700 focus:ring-2 focus:ring-hds-blue focus:outline-none font-medium transition-colors';

export const DocumentReviewTab: React.FC = () => {
  const { showToast } = useApp();
  const [docs, setDocs] = useState<PendingReviewDoc[]>([]);
  const [clients, setClients] = useState<Client[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [docForms, setDocForms] = useState<Record<string, DocForm>>({});

  const fetchPendingDocs = async () => {
    setIsLoading(true);
    try {
      // Danh sách khách hàng dùng cho ô chọn chủ sở hữu; lỗi ở đây không chặn màn hình
      const [data, clientList] = await Promise.all([
        api.getPendingReviews(),
        api.getClients().catch(() => [] as Client[]),
      ]);

      setDocs(data);
      setClients(clientList);
      setDocForms(
        Object.fromEntries(
          data.map((doc) => [
            String(doc.id),
            {
              doc_type: doc.doc_type || 'other',
              access_level: doc.access_level || 'internal',
              client_id: doc.client_id != null ? String(doc.client_id) : '',
              error: null,
              isSubmitting: false,
            },
          ])
        )
      );
    } catch (err: any) {
      showToast(err?.message || 'Lỗi khi tải danh sách tài liệu chờ duyệt', 'error');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchPendingDocs();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const patchForm = (docId: string, patch: Partial<DocForm>) => {
    setDocForms((prev) => ({ ...prev, [docId]: { ...prev[docId], ...patch } }));
  };

  const [editors, setEditors] = useState<Record<string, ContentEditor>>({});
  const patchEditor = (docId: string, patch: Partial<ContentEditor>) => {
    setEditors((prev) => ({
      ...prev,
      [docId]: {
        open: false, loading: false, saving: false,
        content: '', chunkCount: null, status: null,
        ...prev[docId], ...patch,
      },
    }));
  };

  const toggleEditor = async (docId: number) => {
    const key = String(docId);
    const cur = editors[key];
    if (cur?.open) {
      patchEditor(key, { open: false });
      return;
    }
    patchEditor(key, { open: true, loading: true });
    try {
      const data = await api.getReviewContent(docId);
      patchEditor(key, {
        loading: false,
        content: data.content || '',
        chunkCount: data.chunk_count ?? null,
        status: data.extraction_status || null,
      });
    } catch (err: any) {
      patchEditor(key, { open: false, loading: false });
      showToast(err?.message || 'Không tải được nội dung trích xuất.', 'error');
    }
  };

  const saveEditor = async (docId: number) => {
    const key = String(docId);
    const cur = editors[key];
    if (!cur || cur.saving) return;
    if ((cur.content || '').trim().length < 30) {
      showToast('Nội dung sau sửa quá ngắn (dưới 30 ký tự).', 'error');
      return;
    }
    patchEditor(key, { saving: true });
    try {
      const res = await api.saveReviewContent(docId, cur.content);
      patchEditor(key, { saving: false, chunkCount: res.chunks ?? null, status: 'edited' });
      showToast(`Đã lưu nội dung sửa và tạo lại ${res.chunks} đoạn vector. Bấm "Duyệt" để nạp vào AI.`, 'success');
    } catch (err: any) {
      patchEditor(key, { saving: false });
      showToast(err?.message || 'Không lưu được nội dung.', 'error');
    }
  };

  const handleApprove = async (docId: number) => {
    const key = String(docId);
    const form = docForms[key];
    if (!form) return;

    // Ràng buộc client_doc_must_have_owner trong schema.sql
    if (form.access_level === 'client' && !form.client_id) {
      patchForm(key, {
        error: 'Mức "Hồ sơ khách hàng" bắt buộc phải chọn khách hàng sở hữu.',
      });
      return;
    }

    patchForm(key, { isSubmitting: true, error: null });

    try {
      await api.approveReview(docId, {
        doc_type: form.doc_type,
        access_level: form.access_level,
        client_id: form.client_id || null,
      });
      showToast('Đã duyệt và nạp tài liệu vào kho tri thức.', 'success');
      setDocs((prev) => prev.filter((d) => d.id !== docId));
    } catch (err: any) {
      const msg = err?.message || 'Không duyệt được tài liệu.';
      patchForm(key, { isSubmitting: false, error: msg });
      showToast(msg, 'error');
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center p-12 text-slate-500 dark:text-slate-400 gap-2 text-sm">
        <RefreshCw className="w-5 h-5 animate-spin text-hds-navy dark:text-blue-400" />
        <span>Đang tải danh sách tài liệu chờ kiểm duyệt…</span>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Tiêu đề khu vực */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 bg-white dark:bg-slate-900 p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm">
        <div>
          <h2 className="text-lg font-bold text-slate-900 dark:text-slate-100">
            Kiểm duyệt và gán nhãn tài liệu
          </h2>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
            Xác định loại văn bản, mức truy cập bảo mật và khách hàng sở hữu trước khi nạp vào AI
          </p>
        </div>
        <button
          onClick={fetchPendingDocs}
          className="flex items-center gap-1.5 px-3.5 py-2 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 font-semibold text-xs rounded-xl transition-colors shrink-0"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          <span>Làm mới danh sách</span>
        </button>
      </div>

      {docs.length === 0 ? (
        <div className="bg-white dark:bg-slate-900 rounded-2xl p-12 text-center border border-slate-200 dark:border-slate-800 space-y-3">
          <CheckCircle2 className="w-12 h-12 text-hds-green mx-auto opacity-80" />
          <h3 className="font-bold text-slate-800 dark:text-slate-100 text-base">Hàng chờ trống</h3>
          <p className="text-xs text-slate-500 dark:text-slate-400 max-w-sm mx-auto">
            Không còn tài liệu nào chờ kiểm duyệt. Mọi văn bản đã được phân loại đầy đủ.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {docs.map((doc) => {
            const key = String(doc.id);
            const form = docForms[key] || {
              doc_type: 'other',
              access_level: 'internal',
              client_id: '',
              error: null,
              isSubmitting: false,
            };
            const needsClient = form.access_level === 'client';
            // AI có thể chưa chấm điểm — không hiển thị "NaN%"
            const confidencePct =
              typeof doc.confidence === 'number' ? Math.round(doc.confidence * 100) : null;

            return (
              <div
                key={doc.id}
                className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm p-5 hover:border-slate-300 dark:hover:border-slate-700 transition-colors space-y-4"
              >
                {/* Thông tin tài liệu */}
                <div className="flex flex-col md:flex-row md:items-start justify-between gap-3 pb-3 border-b border-slate-100 dark:border-slate-800">
                  <div className="flex items-start gap-3 min-w-0">
                    <span className="p-2.5 bg-hds-soft dark:bg-slate-800 text-hds-navy dark:text-blue-300 rounded-xl shrink-0">
                      <FileText className="w-5 h-5" />
                    </span>
                    <div className="min-w-0">
                      <h3 className="font-bold text-sm text-slate-900 dark:text-slate-100 leading-snug break-words">
                        {doc.title || '(không có tiêu đề)'}
                      </h3>
                      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 mt-1.5 text-[11px] text-slate-500 dark:text-slate-400">
                        <span className="bg-slate-100 dark:bg-slate-800 px-2 py-0.5 rounded font-mono">
                          ID: {doc.id}
                        </span>
                        <span>Nguồn: <strong className="text-slate-700 dark:text-slate-300">{doc.source_kind}</strong></span>
                        <span>
                          Độ tin cậy AI:{' '}
                          {confidencePct !== null ? (
                            <strong className="text-hds-green dark:text-emerald-400">
                              {confidencePct}%
                            </strong>
                          ) : (
                            <strong className="text-slate-400">chưa chấm</strong>
                          )}
                        </span>
                        {doc.client_name && (
                          <span className="text-slate-700 dark:text-slate-300">
                            Khách: <strong>{doc.client_name}</strong>
                          </span>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="flex flex-col items-end gap-1.5 shrink-0 self-start">
                    <span className="text-xs bg-amber-100 dark:bg-amber-950 text-amber-800 dark:text-amber-300 border border-amber-300 dark:border-amber-800 px-2.5 py-1 rounded-full font-semibold">
                      Chờ duyệt
                    </span>
                    {(doc as any).extraction_status === 'warning' && (
                      <span
                        title={(doc as any).extraction_warning || 'Trích xuất có cảnh báo — soát nội dung trước khi duyệt'}
                        className="text-[10px] bg-red-100 dark:bg-red-950 text-red-700 dark:text-red-300 border border-red-300 dark:border-red-800 px-2 py-0.5 rounded-full font-bold"
                      >
                        ⚠ Học không ổn — soát nội dung
                      </span>
                    )}
                    {(doc as any).extraction_status === 'edited' && (
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

                {/* Xem & sửa NỘI DUNG trích xuất — PDF scan bắt buộc mắt người
                    soát trước khi duyệt; OCR sai một con số là sai căn cứ. */}
                {(() => {
                  const ed = editors[key];
                  return (
                    <div className="space-y-2">
                      <button
                        onClick={() => toggleEditor(doc.id)}
                        className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] font-semibold rounded-lg bg-hds-soft dark:bg-slate-800 text-hds-navy dark:text-blue-300 hover:bg-blue-100 dark:hover:bg-slate-700 transition-colors"
                      >
                        <PencilLine className="w-3.5 h-3.5" />
                        <span>
                          {ed?.open ? 'Đóng khung sửa nội dung' : 'Xem & sửa nội dung trích xuất'}
                        </span>
                      </button>
                      {ed?.open && (
                        <div className="space-y-2 border border-slate-200 dark:border-slate-700 rounded-xl p-3 bg-slate-50/60 dark:bg-slate-800/40">
                          {ed.loading ? (
                            <div className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400 py-4 justify-center">
                              <Loader2 className="w-4 h-4 animate-spin" />
                              <span>Đang tải nội dung trích xuất…</span>
                            </div>
                          ) : (
                            <>
                              <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-slate-500 dark:text-slate-400">
                                <span>
                                  {ed.chunkCount != null && <>Hiện có <strong>{ed.chunkCount}</strong> đoạn vector · </>}
                                  Sửa trực tiếp phần OCR đọc sai rồi bấm Lưu — bot sẽ học ĐÚNG bản đã sửa.
                                </span>
                                {ed.status === 'edited' && (
                                  <span className="text-hds-green dark:text-emerald-400 font-semibold">đã sửa tay</span>
                                )}
                              </div>
                              <textarea
                                value={ed.content}
                                onChange={(e) => patchEditor(key, { content: e.target.value })}
                                rows={14}
                                spellCheck={false}
                                className="w-full text-xs font-mono leading-relaxed p-3 rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 dark:text-slate-100 focus:ring-2 focus:ring-hds-blue focus:outline-none resize-y"
                              />
                              <div className="flex justify-end">
                                <button
                                  onClick={() => saveEditor(doc.id)}
                                  disabled={ed.saving}
                                  className="flex items-center gap-1.5 px-4 py-2 rounded-xl font-bold text-[11px] text-white bg-hds-blue hover:bg-hds-blue-light disabled:bg-slate-300 dark:disabled:bg-slate-700 disabled:cursor-not-allowed transition-colors"
                                >
                                  {ed.saving ? (
                                    <>
                                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                                      <span>Đang chia đoạn & tạo vector…</span>
                                    </>
                                  ) : (
                                    <>
                                      <Save className="w-3.5 h-3.5" />
                                      <span>Lưu nội dung đã sửa</span>
                                    </>
                                  )}
                                </button>
                              </div>
                            </>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })()}

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
                        <option key={t.value} value={t.value}>
                          {t.label}
                        </option>
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
                      onChange={(e) =>
                        patchForm(key, { access_level: e.target.value, error: null })
                      }
                      className={inputClass}
                    >
                      {ACCESS_LEVELS.map((a) => (
                        <option key={a.value} value={a.value}>
                          {a.label}
                        </option>
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
                        <option key={c.id} value={String(c.id)}>
                          [{c.code}] {c.name}
                        </option>
                      ))}
                    </select>
                    {clients.length === 0 && (
                      <p className="text-[10px] text-amber-600 dark:text-amber-400 mt-1">
                        Chưa tải được danh sách khách hàng.
                      </p>
                    )}
                  </div>
                </div>

                <div className="flex justify-end pt-1">
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
        </div>
      )}
    </div>
  );
};
