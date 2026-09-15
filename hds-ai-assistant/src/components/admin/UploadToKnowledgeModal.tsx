import React, { useEffect, useState } from 'react';
import { useApp } from '../../context/AppContext';
import * as api from '../../api';
import type { Client } from '../../types';
import { DOC_TYPES, ACCESS_LEVELS } from '../../constants';
import { Upload, FileText, AlertCircle, X, Loader2 } from 'lucide-react';

/**
 * Nạp một tài liệu vào KHO TRI THỨC — việc của người quản trị, không phải của
 * khung chat.
 *
 * Vì sao tách khỏi chat (29/08/2026): trước đây nút "Tải tài liệu" trong chat
 * bắt người dùng chọn giữa "dùng xong bỏ" và "lưu vào kho", và chế độ dùng tạm
 * chỉ nhận .txt/.md/.csv vì trình duyệt tự đọc nội dung. Người dùng chỉ muốn
 * đưa một file .docx/.pdf cho bot đọc thì vướng cả hai. Nay chat chỉ còn một
 * việc — đính kèm cho bot đọc (máy chủ trích + OCR, mọi định dạng) — còn việc
 * đưa tài liệu vào tri thức lâu dài nằm ở đây, nơi có đủ ngữ cảnh để gán nhãn
 * và quyết định mức truy cập.
 */

const SAVE_EXTENSIONS = ['pdf', 'docx', 'doc', 'txt', 'md', 'csv', 'xlsx',
                         'jpg', 'jpeg', 'png', 'webp', 'tif', 'tiff', 'bmp'];
const SAVE_MAX = 50 * 1024 * 1024;

const inputClass =
  'w-full px-3 py-2 border border-slate-300 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 rounded-xl text-xs focus:ring-2 focus:ring-hds-blue focus:outline-none';

interface UploadToKnowledgeModalProps {
  isOpen: boolean;
  onClose: () => void;
  /** Gọi sau khi tải lên xong để danh sách tài liệu tự nạp lại. */
  onUploaded?: () => void;
}

export const UploadToKnowledgeModal: React.FC<UploadToKnowledgeModalProps> = ({
  isOpen,
  onClose,
  onUploaded,
}) => {
  const { showToast, currentUser } = useApp();
  const canReview = Boolean(currentUser?.can_review) || currentUser?.role === 'admin';

  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [errorMsg, setErrorMsg] = useState<string>('');

  const [docType, setDocType] = useState('other');
  const [accessLevel, setAccessLevel] = useState('internal');
  const [clientId, setClientId] = useState('');
  const [autoApprove, setAutoApprove] = useState(false);
  const [clients, setClients] = useState<Client[]>([]);

  useEffect(() => {
    if (isOpen && clients.length === 0) {
      api.getClients().then(setClients).catch(() => {});
    }
  }, [isOpen, clients.length]);

  if (!isOpen) return null;

  const reset = () => {
    setSelectedFile(null);
    setErrorMsg('');
    setProgress(0);
    setDocType('other');
    setAccessLevel('internal');
    setClientId('');
    setAutoApprove(false);
  };

  const handleClose = () => {
    reset();
    onClose();
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setErrorMsg('');

    const ext = file.name.split('.').pop()?.toLowerCase() || '';
    if (!SAVE_EXTENSIONS.includes(ext)) {
      setSelectedFile(null);
      setErrorMsg(`Kho tri thức nhận: ${SAVE_EXTENSIONS.map((x) => `.${x}`).join(', ')}`);
      return;
    }
    if (file.size > SAVE_MAX) {
      setSelectedFile(null);
      setErrorMsg(
        `Tệp nặng ${(file.size / 1024 / 1024).toFixed(1)} MB, vượt giới hạn ${(
          SAVE_MAX /
          1024 /
          1024
        ).toFixed(0)} MB.`
      );
      return;
    }
    setSelectedFile(file);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedFile) {
      setErrorMsg('Vui lòng chọn tệp.');
      return;
    }
    if (accessLevel === 'client' && !clientId) {
      setErrorMsg('Mức "Hồ sơ khách hàng" bắt buộc chọn khách hàng.');
      return;
    }

    setIsUploading(true);
    setErrorMsg('');
    setProgress(0);
    try {
      const res = await api.uploadDocument({
        file: selectedFile,
        doc_type: docType,
        access_level: accessLevel,
        client_id: clientId ? Number(clientId) : null,
        auto_approve: autoApprove && canReview,
        onProgress: setProgress,
      });
      showToast(res.note || `Đã tải lên "${selectedFile.name}".`, 'success');
      onUploaded?.();
      handleClose();
    } catch (err: any) {
      const msg = err?.message || 'Lỗi khi tải tệp lên.';
      setErrorMsg(msg);
      showToast(msg, 'error');
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <div
      className="fixed inset-0 bg-slate-900/60 backdrop-blur-sm flex items-center justify-center z-50 p-4 animate-fade-in"
      onClick={handleClose}
      role="presentation"
    >
      <div
        className="bg-white dark:bg-slate-900 rounded-2xl shadow-2xl border border-slate-200 dark:border-slate-700 w-full max-w-lg p-6 text-slate-800 dark:text-slate-100 animate-pop-in max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="kb-upload-title"
      >
        <div className="flex items-start justify-between pb-4 border-b border-slate-100 dark:border-slate-800">
          <div className="flex items-center gap-2.5">
            <span className="p-2 bg-emerald-50 dark:bg-emerald-950/60 text-hds-green dark:text-emerald-300 rounded-lg">
              <Upload className="w-5 h-5" />
            </span>
            <div>
              <h3 id="kb-upload-title" className="font-bold text-base">
                Nạp tài liệu vào kho tri thức
              </h3>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                Máy chủ tự trích văn bản và OCR tiếng Việt, rồi đưa vào bộ nhớ trích dẫn của AI
              </p>
            </div>
          </div>
          <button
            onClick={handleClose}
            className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 p-1"
            aria-label="Đóng"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="mt-4 space-y-4 text-xs">
          <p className="text-[11px] leading-relaxed text-slate-500 dark:text-slate-400 bg-slate-50 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700 rounded-xl p-2.5">
            Tài liệu ở đây thành tri thức LÂU DÀI, mọi người trong phạm vi truy cập đều tra
            được. Chỉ cần bot đọc một file trong một cuộc trao đổi thì đính kèm thẳng ở khung
            chat — nhanh hơn và không để lại gì trong kho.
          </p>

          <div>
            <span className="block font-semibold text-slate-700 dark:text-slate-300 mb-1.5">
              Chọn tệp ({SAVE_EXTENSIONS.map((x) => `.${x}`).join(', ')})
            </span>
            <div className="border-2 border-dashed border-slate-300 dark:border-slate-700 rounded-xl p-4 text-center hover:border-hds-navy dark:hover:border-blue-500 transition-colors bg-slate-50/60 dark:bg-slate-800/40">
              <input
                type="file"
                accept={SAVE_EXTENSIONS.map((x) => `.${x}`).join(',')}
                onChange={handleFileChange}
                className="sr-only"
                id="kb-file-input"
              />
              <label
                htmlFor="kb-file-input"
                className="cursor-pointer flex flex-col items-center gap-2"
              >
                <FileText className="w-8 h-8 text-hds-navy/60 dark:text-blue-400/60" />
                <span className="text-xs font-semibold text-hds-navy dark:text-blue-300 break-all px-2">
                  {selectedFile ? selectedFile.name : 'Nhấp để chọn tệp từ máy tính'}
                </span>
                <span className="text-[11px] text-slate-400 dark:text-slate-500">
                  {selectedFile
                    ? `${(selectedFile.size / 1024).toFixed(1)} KB`
                    : `Tối đa ${(SAVE_MAX / 1024 / 1024).toFixed(0)} MB`}
                </span>
              </label>
            </div>
          </div>

          <div className="space-y-3 bg-slate-50 dark:bg-slate-800/50 rounded-xl p-3 border border-slate-200 dark:border-slate-700">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="block font-semibold text-slate-700 dark:text-slate-300 mb-1">
                  Loại tài liệu
                </label>
                <select
                  value={docType}
                  onChange={(e) => setDocType(e.target.value)}
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
                <label className="block font-semibold text-slate-700 dark:text-slate-300 mb-1">
                  Mức truy cập
                </label>
                <select
                  value={accessLevel}
                  onChange={(e) => setAccessLevel(e.target.value)}
                  className={inputClass}
                >
                  {ACCESS_LEVELS.map((a) => (
                    <option key={a.value} value={a.value}>
                      {a.label}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {accessLevel === 'client' && (
              <div>
                <label className="flex items-center justify-between font-semibold text-slate-700 dark:text-slate-300 mb-1">
                  <span>Khách hàng sở hữu</span>
                  <span className="text-[10px] text-hds-red dark:text-red-400 font-bold uppercase">
                    Bắt buộc
                  </span>
                </label>
                <select
                  value={clientId}
                  onChange={(e) => setClientId(e.target.value)}
                  className={`${inputClass} ${
                    !clientId ? 'border-red-400 dark:border-red-700' : ''
                  }`}
                >
                  <option value="">— Chọn khách hàng —</option>
                  {clients.map((c) => (
                    <option key={c.id} value={String(c.id)}>
                      [{c.code}] {c.name}
                    </option>
                  ))}
                </select>
              </div>
            )}

            {canReview && (
              <label className="flex items-center gap-2 cursor-pointer text-[11px] text-slate-700 dark:text-slate-300">
                <input
                  type="checkbox"
                  checked={autoApprove}
                  onChange={(e) => setAutoApprove(e.target.checked)}
                  className="rounded accent-[#1f3864]"
                />
                <span>Duyệt luôn, không qua hàng chờ (dùng được ngay)</span>
              </label>
            )}
          </div>

          {errorMsg && (
            <div className="p-2.5 bg-red-50 dark:bg-red-950/50 border border-red-200 dark:border-red-900 rounded-lg text-red-800 dark:text-red-200 flex items-start gap-2 text-[11px]">
              <AlertCircle className="w-4 h-4 shrink-0 mt-px" />
              <span>{errorMsg}</span>
            </div>
          )}

          {isUploading && progress > 0 && progress < 100 && (
            <div className="h-1.5 bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden">
              <div className="h-full bg-hds-navy transition-all" style={{ width: `${progress}%` }} />
            </div>
          )}

          <div className="flex justify-end gap-2 pt-3 border-t border-slate-100 dark:border-slate-800">
            <button
              type="button"
              onClick={handleClose}
              className="px-4 py-2 border border-slate-300 dark:border-slate-700 rounded-xl font-semibold text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors"
            >
              Huỷ
            </button>
            <button
              type="submit"
              disabled={isUploading || !selectedFile}
              className="px-5 py-2 rounded-xl font-semibold text-white shadow-sm flex items-center gap-2 bg-hds-navy hover:bg-hds-navy-light disabled:bg-slate-300 dark:disabled:bg-slate-700 disabled:cursor-not-allowed transition-colors"
            >
              {isUploading ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>Đang tải lên…</span>
                </>
              ) : (
                <>
                  <Upload className="w-4 h-4" />
                  <span>Tải lên kho</span>
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
