import React, { useState, useRef, useEffect } from 'react';
import { useApp } from '../../context/AppContext';
import { ConversationSidebar } from './ConversationSidebar';
import { ChatMessageItem } from './ChatMessageItem';
import { FileUploadModal } from './FileUploadModal';
import * as api from '../../api';
import type { MethodTemplate } from '../../types';
import { isClientRole } from '../../constants';
import { Send, Upload, Sliders, FileText, X, Loader2, Sparkles, AlertCircle } from 'lucide-react';

const nowLabel = () =>
  new Date().toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' });

export const ChatLayout: React.FC = () => {
  const {
    activeConversation,
    activeConvId,
    addMessageToConv,
    setConvServerId,
    setConvTempFile,
    currentUser,
    isMockMode,
  } = useApp();

  const [inputQuestion, setInputQuestion] = useState('');
  const [useMethod, setUseMethod] = useState(false);
  const [methodTemplates, setMethodTemplates] = useState<MethodTemplate[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [showUploadModal, setShowUploadModal] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [quota, setQuota] = useState<{ used: number; limit: number } | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const isClient = isClientRole(currentUser?.role);
  const serverConvId = activeConversation?.server_id;
  // Backend yêu cầu conversation_id kiểu int cho POST /upload, mã này chỉ có
  // sau câu hỏi đầu tiên. Giả lập thì không ràng buộc.
  const canUpload = !isClient && (isMockMode || Boolean(serverConvId));

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [activeConversation?.messages, isLoading]);

  useEffect(() => {
    if (isClient) return;
    api
      .getMethods()
      .then((templates) => setMethodTemplates(Array.isArray(templates) ? templates : []))
      .catch(() => setMethodTemplates([]));
  }, [isClient]);

  const handleSendMessage = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const questionText = inputQuestion.trim();
    if (!questionText || isLoading || !activeConversation) return;

    setInputQuestion('');
    setErrorMessage(null);

    const tempFileName = activeConversation.temp_file?.filename;

    addMessageToConv(activeConvId, {
      id: `msg-${Date.now()}`,
      sender: 'user',
      text: questionText,
      timestamp: nowLabel(),
      used_method: useMethod && !isClient,
      used_temp_file: tempFileName,
    });

    setIsLoading(true);
    try {
      const response = isClient
        ? await api.chatPortal({ question: questionText, conversation_id: serverConvId ?? null })
        : await api.chatInternal({
            question: questionText,
            conversation_id: serverConvId ?? null,
            use_temp: Boolean(tempFileName),
            use_method: useMethod,
          });

      // Ghi nhớ mã hội thoại do backend cấp để các lượt sau nối đúng ngữ cảnh
      if (response.conversation_id) {
        setConvServerId(activeConvId, response.conversation_id);
      }
      if (response.quota) setQuota(response.quota);

      addMessageToConv(activeConvId, {
        id: `ai-${Date.now()}`,
        sender: 'ai',
        text: response.answer,
        sources: response.sources,
        timestamp: nowLabel(),
        latency_ms: response.latency_ms,
      });
    } catch (err: any) {
      const errMsg = err?.message || 'Có lỗi xảy ra khi hỏi AI.';
      setErrorMessage(errMsg);
      addMessageToConv(activeConvId, {
        id: `err-${Date.now()}`,
        sender: 'ai',
        text: errMsg,
        timestamp: nowLabel(),
        isError: true,
      });
    } finally {
      setIsLoading(false);
      textareaRef.current?.focus();
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  const messages = activeConversation?.messages ?? [];
  const hasConversation = messages.length > 0;

  return (
    <div className="flex flex-1 h-[calc(100dvh-4rem)] bg-hds-soft dark:bg-slate-950 overflow-hidden">
      <ConversationSidebar />

      <main className="flex-1 flex flex-col h-full bg-white dark:bg-slate-900 min-w-0">
        {/* Thanh công cụ trên cùng */}
        <div className="border-b border-slate-200 dark:border-slate-800 px-3 sm:px-4 py-2.5 flex items-center justify-between gap-3 shrink-0">
          <div className="flex items-center gap-2.5 min-w-0">
            <h2 className="font-bold text-sm text-slate-800 dark:text-slate-100 truncate">
              {activeConversation?.title || 'Cuộc trò chuyện'}
            </h2>

            {activeConversation?.temp_file && (
              <span className="hidden sm:flex items-center gap-1 bg-amber-50 dark:bg-amber-950/60 text-amber-900 dark:text-amber-200 border border-amber-300 dark:border-amber-800 text-[11px] px-2.5 py-1 rounded-full shrink-0">
                <FileText className="w-3.5 h-3.5 shrink-0" />
                <span className="font-medium truncate max-w-[150px]">
                  {activeConversation.temp_file.filename}
                </span>
                <button
                  onClick={() => setConvTempFile(activeConvId, undefined)}
                  className="hover:text-amber-600 ml-0.5 p-0.5"
                  title="Gỡ tài liệu tạm"
                  aria-label="Gỡ tài liệu tạm"
                >
                  <X className="w-3 h-3" />
                </button>
              </span>
            )}
          </div>

          <div className="flex items-center gap-2 shrink-0">
            {/* Hạn mức câu hỏi — chỉ hiện với tài khoản khách hàng */}
            {isClient && quota && (
              <span className="text-[11px] font-semibold px-2.5 py-1 rounded-lg border bg-indigo-50 dark:bg-indigo-950/60 text-indigo-800 dark:text-indigo-300 border-indigo-200 dark:border-indigo-800">
                Đã dùng {quota.used}/{quota.limit} lượt tháng này
              </span>
            )}

            {/* Mẫu phương pháp phân tích */}
            {!isClient && methodTemplates.length > 0 && (
              <label
                htmlFor="use-method-checkbox"
                className="flex items-center gap-1.5 bg-slate-50 dark:bg-slate-800 px-2.5 py-1.5 rounded-xl border border-slate-200 dark:border-slate-700 text-xs cursor-pointer select-none"
                title={methodTemplates.map((m) => m.case_type).join(' • ')}
              >
                <input
                  id="use-method-checkbox"
                  type="checkbox"
                  checked={useMethod}
                  onChange={(e) => setUseMethod(e.target.checked)}
                  className="w-3.5 h-3.5 accent-[#1f3864] cursor-pointer"
                />
                <Sliders className="w-3.5 h-3.5 text-hds-navy dark:text-blue-400" />
                <span className="font-semibold text-slate-700 dark:text-slate-300 hidden sm:inline">
                  Mẫu phương pháp
                </span>
              </label>
            )}

            {!isClient && (
              <button
                id="chat-upload-btn"
                onClick={() => setShowUploadModal(true)}
                disabled={!canUpload}
                className="flex items-center gap-1.5 bg-hds-soft dark:bg-slate-800 text-hds-navy dark:text-blue-300 font-semibold text-xs px-3 py-1.5 rounded-xl border border-blue-200 dark:border-slate-700 hover:bg-blue-100 dark:hover:bg-slate-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                title={
                  canUpload
                    ? 'Tải tài liệu lên cuộc trò chuyện'
                    : 'Hãy gửi câu hỏi đầu tiên để hệ thống cấp mã hội thoại, sau đó mới tải tài liệu lên được'
                }
              >
                <Upload className="w-3.5 h-3.5" />
                <span className="hidden sm:inline">Tải tài liệu</span>
              </button>
            )}
          </div>
        </div>

        {/* Dải báo lỗi */}
        {errorMessage && (
          <div className="bg-red-50 dark:bg-red-950/50 border-b border-red-200 dark:border-red-900 px-4 py-2 text-xs text-red-800 dark:text-red-200 flex items-start justify-between gap-3 shrink-0">
            <span className="flex items-start gap-2">
              <AlertCircle className="w-4 h-4 shrink-0 mt-px" />
              <span>{errorMessage}</span>
            </span>
            <button
              onClick={() => setErrorMessage(null)}
              className="p-0.5 shrink-0"
              aria-label="Đóng thông báo lỗi"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        )}

        {/* Danh sách tin nhắn */}
        <div className="flex-1 overflow-y-auto min-h-0">
          {hasConversation ? (
            messages.map((msg) => <ChatMessageItem key={msg.id} message={msg} />)
          ) : (
            <div className="h-full flex flex-col items-center justify-center p-8 text-center">
              <Sparkles className="w-12 h-12 text-hds-navy dark:text-blue-400 mb-3 opacity-40" />
              <h3 className="font-bold text-slate-700 dark:text-slate-200 text-base">
                Trợ lý AI Pháp lý HDS
              </h3>
              <p className="text-xs max-w-sm mt-1 text-slate-500 dark:text-slate-400">
                Đặt câu hỏi pháp lý hoặc tải tài liệu lên để tra cứu điều khoản, hợp đồng và tiền lệ
                tư vấn của HDS.
              </p>
            </div>
          )}

          {isLoading && (
            <div className="p-6 border-b border-slate-100 dark:border-slate-800">
              <div className="max-w-3xl mx-auto flex items-center gap-3 text-xs">
                <Loader2 className="w-5 h-5 text-hds-navy dark:text-blue-400 animate-spin shrink-0" />
                <div>
                  <p className="font-semibold text-slate-900 dark:text-slate-100">
                    HDS AI đang tra cứu văn bản và phân tích…
                  </p>
                  <p className="text-[11px] text-slate-400 dark:text-slate-500 mt-0.5">
                    Đang đối chiếu trích dẫn pháp luật và tiền lệ vụ việc.
                  </p>
                </div>
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Ô nhập */}
        <div className="p-3 sm:p-4 border-t border-slate-200 dark:border-slate-800 shrink-0">
          <form onSubmit={handleSendMessage} className="max-w-3xl mx-auto space-y-2">
            <div className="flex items-end gap-2 border border-slate-300 dark:border-slate-700 rounded-2xl p-2 shadow-sm bg-slate-50/60 dark:bg-slate-800/50 focus-within:border-hds-blue focus-within:ring-2 focus-within:ring-hds-blue/30 transition-colors">
              <textarea
                id="chat-input-textarea"
                ref={textareaRef}
                rows={2}
                value={inputQuestion}
                onChange={(e) => setInputQuestion(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Nhập câu hỏi pháp lý… (Enter để gửi, Shift+Enter để xuống dòng)"
                aria-label="Câu hỏi gửi tới trợ lý AI"
                className="flex-1 px-2 py-1.5 bg-transparent text-sm text-slate-900 dark:text-slate-100 placeholder-slate-400 dark:placeholder-slate-500 focus:outline-none resize-none min-w-0"
              />

              <div className="flex items-center gap-1 shrink-0 pb-0.5">
                {!isClient && (
                  <button
                    type="button"
                    onClick={() => setShowUploadModal(true)}
                    disabled={!canUpload}
                    className="p-2 text-slate-400 hover:text-hds-navy dark:hover:text-blue-400 hover:bg-slate-200/70 dark:hover:bg-slate-700 rounded-xl transition-colors disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-transparent"
                    title={
                      canUpload
                        ? 'Tải tài liệu lên'
                        : 'Hãy gửi câu hỏi đầu tiên trước khi tải tài liệu'
                    }
                    aria-label="Tải tài liệu lên"
                  >
                    <Upload className="w-4 h-4" />
                  </button>
                )}

                <button
                  id="send-chat-btn"
                  type="submit"
                  disabled={!inputQuestion.trim() || isLoading}
                  className="p-2.5 rounded-xl transition-colors bg-hds-navy text-hds-gold hover:bg-hds-navy-light disabled:bg-slate-200 dark:disabled:bg-slate-800 disabled:text-slate-400 disabled:cursor-not-allowed"
                  title="Gửi câu hỏi"
                  aria-label="Gửi câu hỏi"
                >
                  {isLoading ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Send className="w-4 h-4" />
                  )}
                </button>
              </div>
            </div>

            <div className="flex items-center justify-between gap-3 text-[11px] text-slate-400 dark:text-slate-500 px-1">
              <span className="flex items-center gap-1.5 min-w-0">
                <span className="shrink-0">Chế độ:</span>
                {activeConversation?.temp_file ? (
                  <span className="text-amber-700 dark:text-amber-300 font-semibold bg-amber-50 dark:bg-amber-950/60 px-1.5 py-0.5 rounded border border-amber-200 dark:border-amber-800 truncate">
                    Có tài liệu tạm đính kèm
                  </span>
                ) : (
                  <span className="truncate">
                    {isClient ? 'Cổng khách hàng' : 'Tra cứu kho tri thức nội bộ'}
                  </span>
                )}
              </span>
              <span className="hidden sm:inline shrink-0">HDS Law Firm — Nền tảng AI Pháp lý</span>
            </div>
          </form>
        </div>
      </main>

      <FileUploadModal
        isOpen={showUploadModal}
        onClose={() => setShowUploadModal(false)}
        conversationId={serverConvId ?? null}
        localConversationId={activeConvId}
      />
    </div>
  );
};
