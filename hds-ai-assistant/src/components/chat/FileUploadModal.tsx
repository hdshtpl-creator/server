import React, { useEffect, useState } from 'react';
import { useApp } from '../../context/AppContext';
import * as api from '../../api';
import type { Client } from '../../types';
import { DOC_TYPES, ACCESS_LEVELS } from '../../constants';
import { Upload, FileText, AlertCircle, Timer, Database, X, Loader2 } from 'lucide-react';

interface FileUploadModalProps {
  isOpen: boolean;
  onClose: () => void;
  conversationId: number | null;
  localConversationId: string;
}

const TEMP_EXTENSIONS = ['txt', 'md', 'csv'];
const SAVE_EXTENSIONS = ['pdf', 'docx', 'txt', 'md'];
const TEMP_MAX = 2 * 1024 * 1024;
const SAVE_MAX = 50 * 1024 * 1024;

const inputClass =
  'w-full px-3 py-2 border border-slate-300 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 rounded-xl text-xs focus:ring-2 focus:ring-hds-blue focus:outline-none';

export const FileUploadModal: React.FC<FileUploadModalProps> = ({
  isOpen,
  onClose,
  conversationId,
  localConversationId,
}) => {
  const { showToast, setConvTempFile, currentUser } = useApp();
  const canReview = Boolean(currentUser?.can_review) || currentUser?.role === 'admin';

  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [fileContent, setFileContent] = useState<string>('');
  const [isReading, setIsReading] = useState(false);
  const [mode, setMode] = useState<'temp' | 'save'>('temp');
  const [isUploading, setIsUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [errorMsg, setErrorMsg] = useState<string>('');

  const [docType, setDocType] = useState('other');
  const [accessLevel, setAccessLevel] = useState('internal');
  const [clientId, setClientId] = useState('');
  const [autoApprove, setAutoApprove] = useState(false);
  const [clients, setClients] = useState<Client[]>([]);

  useEffect(() => {
    if (isOpen && mode === 'save' && clients.length === 0) {
      api.getClients().then(setClients).catch(() => {});
    }
  }, [isOpen, mode, clients.length]);

  if (!isOpen) return null;

  const reset = () => {
    setSelectedFile(null);
    setFileContent('');
    setErrorMsg('');
    setMode('temp');
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

  const extAllowed = mode === 'temp' ? TEMP_EXTENSIONS : SAVE_EXTENSIONS;
  const maxSize = mode === 'temp' ? TEMP_MAX : SAVE_MAX;

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setErrorMsg('');
    setFileContent('');

    const ext = file.name.split('.').pop()?.toLowerCase() || '';
    if (!extAllowed.includes(ext)) {
      setSelectedFile(null);
      setErrorMsg(`Chế độ này chỉ nhận: ${extAllowed.map((x) => `.${x}`).join(', ')}`);
      return;
    }
    if (file.size > maxSize) {
      setSelectedFile(null);
      setErrorMsg(
        `Tệp nặng ${(file.size / 1024 / 1024).toFixed(1)} MB, vượt giới hạn ${(
          maxSize /
          1024 /
          1024
        ).toFixed(0)} MB.`
      );
      return;
    }

    setSelectedFile(file);

    // Chế độ tạm cần nội dung văn bản để làm ngữ cảnh trong phiên chat.
    if (mode === 'temp') {
      setIsReading(true);
      const reader = new FileReader();
      reader.onload = (ev) => {
        setFileContent((ev.target?.result as string) || '');
        setIsReading(false);
      };
      reader.onerror = () => {
        setIsReading(false);
        setSelectedFile(null);
        setErrorMsg('Không đọc được nội dung tệp.');
      };
      reader.readAsText(file);
    }
  };

  const switchMode = (m: 'temp' | 'save') => {
    setMode(m);
    setSelectedFile(null);
    setFileContent('');
    setErrorMsg('');
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedFile) {
      setErrorMsg('Vui lòng chọn tệp.');
      return;
    }
    if (accessLevel === 'client' && mode === 'save' && !clientId) {
      setErrorMsg('Mức "Hồ sơ khách hàng" bắt buộc chọn khách hàng.');
      return;
    }

    setIsUploading(true);
    setErrorMsg('');
    setProgress(0);
    try {
      if (mode === 'temp') {
        await api.uploadFile({
          conversation_id: conversationId,
          filename: selectedFile.name,
          content: fileContent,
          mode: 'temp',
        });
        setConvTempFile(localConversationId, { filename: selectedFile.name, content: fileContent });
        showToast(`Đã nạp tài liệu tạm "${selectedFile.name}".`, 'success');
      } else {
        const res = await api.uploadDocument({
          file: selectedFile,
          doc_type: docType,
          access_level: accessLevel,
          client_id: clientId ? Number(clientId) : null,
          auto_approve: autoApprove && canReview,
          onProgress: setProgress,
        });
        showToast(res.note || `Đã tải lên "${selectedFile.name}".`, 'success');
      }
      handleClose();
    } catch (err: any) {
      const msg = err?.message || 'Lỗi khi tải tệp lên.';
      setErrorMsg(msg);
      showToast(msg, 'error');
    } finally {
      setIsUploading(false);
    }
  };

  const radioCard = (active: boolean, accent: 'navy' | 'green') =>
    `p-3 rounded-xl border-2 cursor-pointer flex items-start gap-3 transition-colors ${
      active
        ? accent === 'navy'
          ? 'border-hds-navy bg-hds-soft dark:bg-slate-800 dark:border-blue-500'
          : 'border-hds-green bg-emerald-50 dark:bg-emerald-950/40 dark:border-emerald-600'
        : 'border-slate-200 dark:border-slate-700 hover:border-slate-300 dark:hover:border-slate-600 bg-white dark:bg-slate-900'
    }`;

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
        aria-labelledby="upload-modal-title"
      >
        <div className="flex items-start justify-between pb-4 border-b border-slate-100 dark:border-slate-800">
          <div className="flex items-center gap-2.5">
            <span className="p-2 bg-hds-soft dark:bg-hds-navy text-hds-navy dark:text-blue-200 rounded-lg">
              <Upload className="w-5 h-5" />
            </span>
            <div>
              <h3 id="upload-modal-title" className="font-bold text-base">
                Tải tài liệu lên
              </h3>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                Dùng tạm trong phiên, hoặc lưu vào kho tri thức
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
          {/* Chế độ */}
          <fieldset>
            <legend className="font-semibold text-slate-700 dark:text-slate-300 mb-2">
              Chế độ xử lý
            </legend>
            <div className="grid grid-cols-1 gap-2.5">
              <label className={radioCard(mode === 'temp', 'navy')}>
                <input
                  type="radio"
                  name="upload_mode"
                  checked={mode === 'temp'}
                  onChange={() => switchMode('temp')}
                  className="mt-1 accent-[#1f3864]"
                />
                <div className="space-y-0.5">
                  <div className="font-bold flex items-center gap-1.5">
                    <Timer className="w-3.5 h-3.5 text-hds-blue" />
                    Dùng xong bỏ
                  </div>
                  <p className="text-[11px] text-slate-500 dark:text-slate-400 leading-snug">
                    Chỉ ghi nhớ trong phiên trò chuyện này, tự xoá sau 6 giờ. Nhận tệp văn bản thuần.
                  </p>
                </div>
              </label>

              <label className={radioCard(mode === 'save', 'green')}>
                <input
                  type="radio"
                  name="upload_mode"
                  checked={mode === 'save'}
                  onChange={() => switchMode('save')}
                  className="mt-1 accent-[#2e7d32]"
                />
                <div className="space-y-0.5">
                  <div className="font-bold flex items-center gap-1.5">
                    <Database className="w-3.5 h-3.5 text-hds-green" />
                    Lưu vào kho
                  </div>
                  <p className="text-[11px] text-slate-500 dark:text-slate-400 leading-snug">
                    Tải PDF/Word lên máy chủ, tự trích văn bản và OCR tiếng Việt, rồi nạp vào tri thức.
                  </p>
                </div>
              </label>
            </div>
          </fieldset>

          {/* Chọn tệp */}
          <div>
            <span className="block font-semibold text-slate-700 dark:text-slate-300 mb-1.5">
              Chọn tệp ({extAllowed.map((x) => `.${x}`).join(', ')})
            </span>
            <div className="border-2 border-dashed border-slate-300 dark:border-slate-700 rounded-xl p-4 text-center hover:border-hds-navy dark:hover:border-blue-500 transition-colors bg-slate-50/60 dark:bg-slate-800/40">
              <input
                type="file"
                accept={extAllowed.map((x) => `.${x}`).join(',')}
                onChange={handleFileChange}
                className="sr-only"
                id="file-input-chat"
              />
              <label
                htmlFor="file-input-chat"
                className="cursor-pointer flex flex-col items-center gap-2"
              >
                <FileText className="w-8 h-8 text-hds-navy/60 dark:text-blue-400/60" />
                <span className="text-xs font-semibold text-hds-navy dark:text-blue-300 break-all px-2">
                  {selectedFile ? selectedFile.name : 'Nhấp để chọn tệp từ máy tính'}
                </span>
                <span className="text-[11px] text-slate-400 dark:text-slate-500">
                  {selectedFile
                    ? `${(selectedFile.size / 1024).toFixed(1)} KB${isReading ? ' — đang đọc…' : ''}`
                    : `Tối đa ${(maxSize / 1024 / 1024).toFixed(0)} MB`}
                </span>
              </label>
            </div>
          </div>

          {/* Phân loại — chỉ ở chế độ lưu vào kho */}
          {mode === 'save' && (
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
          )}

          {errorMsg && (
            <div className="p-2.5 bg-red-50 dark:bg-red-950/50 border border-red-200 dark:border-red-900 rounded-lg text-red-800 dark:text-red-200 flex items-start gap-2 text-[11px]">
              <AlertCircle className="w-4 h-4 shrink-0 mt-px" />
              <span>{errorMsg}</span>
            </div>
          )}

          {isUploading && mode === 'save' && progress > 0 && progress < 100 && (
            <div className="h-1.5 bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden">
              <div
                className="h-full bg-hds-navy transition-all"
                style={{ width: `${progress}%` }}
              />
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
              disabled={isUploading || isReading || !selectedFile}
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
                  <span>{mode === 'temp' ? 'Nạp tài liệu tạm' : 'Tải lên kho'}</span>
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
