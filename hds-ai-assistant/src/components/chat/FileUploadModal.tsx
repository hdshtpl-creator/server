import React, { useState } from 'react';
import { useApp } from '../../context/AppContext';
import * as api from '../../api';
import { Upload, FileText, AlertCircle, Timer, Database, X, Loader2 } from 'lucide-react';

interface FileUploadModalProps {
  isOpen: boolean;
  onClose: () => void;
  /** Mã hội thoại do backend cấp (int). null nếu chưa hỏi câu nào. */
  conversationId: number | null;
  /** Mã cục bộ, dùng để gắn tài liệu tạm vào đúng cuộc trò chuyện trên giao diện. */
  localConversationId: string;
}

const TEXT_EXTENSIONS = ['txt', 'md', 'csv'];
const MAX_SIZE_BYTES = 2 * 1024 * 1024; // 2 MB — nội dung được gửi thẳng trong thân JSON

export const FileUploadModal: React.FC<FileUploadModalProps> = ({
  isOpen,
  onClose,
  conversationId,
  localConversationId,
}) => {
  const { showToast, setConvTempFile } = useApp();

  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [fileContent, setFileContent] = useState<string>('');
  const [isReading, setIsReading] = useState(false);
  const [mode, setMode] = useState<'temp' | 'save'>('temp');
  const [isUploading, setIsUploading] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string>('');

  if (!isOpen) return null;

  const reset = () => {
    setSelectedFile(null);
    setFileContent('');
    setErrorMsg('');
    setMode('temp');
  };

  const handleClose = () => {
    reset();
    onClose();
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setErrorMsg('');
    setFileContent('');

    const ext = file.name.split('.').pop()?.toLowerCase() || '';
    if (!TEXT_EXTENSIONS.includes(ext)) {
      setSelectedFile(null);
      setErrorMsg(
        `Hệ thống chỉ đọc được tệp văn bản thuần (${TEXT_EXTENSIONS.join(', ')}). ` +
          'Với PDF hoặc Word, hãy dùng luồng nạp tài liệu của backend (app/ingest.py).'
      );
      return;
    }

    if (file.size > MAX_SIZE_BYTES) {
      setSelectedFile(null);
      setErrorMsg(
        `Tệp nặng ${(file.size / 1024 / 1024).toFixed(1)} MB, vượt giới hạn 2 MB cho mỗi lần tải lên.`
      );
      return;
    }

    setSelectedFile(file);
    setIsReading(true);

    const reader = new FileReader();
    reader.onload = (event) => {
      setFileContent((event.target?.result as string) || '');
      setIsReading(false);
    };
    reader.onerror = () => {
      setIsReading(false);
      setSelectedFile(null);
      setErrorMsg('Không đọc được nội dung tệp. Hãy thử lại hoặc chọn tệp khác.');
    };
    reader.readAsText(file);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedFile) {
      setErrorMsg('Vui lòng chọn tệp văn bản.');
      return;
    }
    if (isReading) return;
    if (!fileContent.trim()) {
      setErrorMsg('Tệp không có nội dung văn bản để nạp.');
      return;
    }

    setIsUploading(true);
    setErrorMsg('');
    try {
      await api.uploadFile({
        conversation_id: conversationId,
        filename: selectedFile.name,
        content: fileContent,
        mode,
      });

      if (mode === 'temp') {
        setConvTempFile(localConversationId, {
          filename: selectedFile.name,
          content: fileContent,
        });
        showToast(
          `Đã nạp tài liệu tạm "${selectedFile.name}". Các câu hỏi tiếp theo sẽ tự tham chiếu tệp này.`,
          'success'
        );
      } else {
        showToast(
          `Đã gửi "${selectedFile.name}" vào hàng chờ duyệt. Duyệt xong mới thành tri thức lâu dài.`,
          'success'
        );
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
            <div className="p-2 bg-hds-soft dark:bg-hds-navy text-hds-navy dark:text-blue-200 rounded-lg">
              <Upload className="w-5 h-5" />
            </div>
            <div>
              <h3 id="upload-modal-title" className="font-bold text-base">
                Tải tài liệu lên cuộc trò chuyện
              </h3>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                Nạp nội dung văn bản để AI phân tích
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
          {/* Chọn tệp */}
          <div>
            <span className="block font-semibold text-slate-700 dark:text-slate-300 mb-1.5">
              Chọn tệp văn bản ({TEXT_EXTENSIONS.map((e) => `.${e}`).join(', ')})
            </span>
            <div className="border-2 border-dashed border-slate-300 dark:border-slate-700 rounded-xl p-4 text-center hover:border-hds-navy dark:hover:border-blue-500 transition-colors bg-slate-50/60 dark:bg-slate-800/40">
              <input
                type="file"
                accept={TEXT_EXTENSIONS.map((e) => `.${e}`).join(',')}
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
                    ? `${(selectedFile.size / 1024).toFixed(1)} KB${
                        isReading ? ' — đang đọc nội dung…' : ''
                      }`
                    : 'Tối đa 2 MB'}
                </span>
              </label>
            </div>

            {errorMsg && (
              <div className="mt-2 p-2.5 bg-amber-50 dark:bg-amber-950/50 border border-amber-300 dark:border-amber-800 rounded-lg text-amber-900 dark:text-amber-200 flex items-start gap-2 text-[11px]">
                <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
                <span>{errorMsg}</span>
              </div>
            )}
          </div>

          {/* Chế độ xử lý */}
          <fieldset>
            <legend className="font-semibold text-slate-700 dark:text-slate-300 mb-2">
              Chế độ xử lý tài liệu
            </legend>

            <div className="grid grid-cols-1 gap-2.5">
              <label className={radioCard(mode === 'temp', 'navy')}>
                <input
                  type="radio"
                  name="upload_mode"
                  checked={mode === 'temp'}
                  onChange={() => setMode('temp')}
                  className="mt-1 accent-[#1f3864]"
                />
                <div className="space-y-0.5">
                  <div className="font-bold flex items-center gap-1.5">
                    <Timer className="w-3.5 h-3.5 text-hds-blue" />
                    <span>Dùng xong bỏ</span>
                    <code className="font-mono font-normal text-[10px] text-slate-500 dark:text-slate-400">
                      mode=temp
                    </code>
                  </div>
                  <p className="text-[11px] text-slate-500 dark:text-slate-400 leading-snug">
                    Chỉ ghi nhớ trong phiên trò chuyện này và tự xoá sau 6 giờ. Không vào kho tri
                    thức chung.
                  </p>
                </div>
              </label>

              <label className={radioCard(mode === 'save', 'green')}>
                <input
                  type="radio"
                  name="upload_mode"
                  checked={mode === 'save'}
                  onChange={() => setMode('save')}
                  className="mt-1 accent-[#2e7d32]"
                />
                <div className="space-y-0.5">
                  <div className="font-bold flex items-center gap-1.5">
                    <Database className="w-3.5 h-3.5 text-hds-green" />
                    <span>Lưu vào kho</span>
                    <code className="font-mono font-normal text-[10px] text-slate-500 dark:text-slate-400">
                      mode=save
                    </code>
                  </div>
                  <p className="text-[11px] text-slate-500 dark:text-slate-400 leading-snug">
                    Chuyển vào hàng chờ kiểm duyệt. Sau khi người có quyền duyệt gán nhãn, tài liệu
                    mới thành tri thức lâu dài của AI.
                  </p>
                </div>
              </label>
            </div>
          </fieldset>

          {/* Hành động */}
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
                  <span>Nạp tài liệu</span>
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
