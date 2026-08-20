import React, { useState, useRef, useEffect } from 'react';
import { useApp } from '../../context/AppContext';
import { ConversationSidebar } from './ConversationSidebar';
import { ChatMessageItem } from './ChatMessageItem';
import { FileUploadModal } from './FileUploadModal';
import * as api from '../../api';
import type { BrowseDocument, MethodTemplate } from '../../types';
import { isClientRole } from '../../constants';
import {
  Send,
  Upload,
  Sliders,
  FileText,
  X,
  Loader2,
  Sparkles,
  AlertCircle,
  Bot,
  Cpu,
  BookOpen,
  Check,
  Search,
} from 'lucide-react';

const nowLabel = () =>
  new Date().toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' });

export const ChatLayout: React.FC = () => {
  const {
    activeConversation,
    activeConvId,
    addMessageToConv,
    updateMessage,
    setConvServerId,
    setConvTempFile,
    currentUser,
    isChatStreaming,
    setChatStreaming,
  } = useApp();

  const [inputQuestion, setInputQuestion] = useState('');
  const [useMethod, setUseMethod] = useState(false);
  const [methodTemplates, setMethodTemplates] = useState<MethodTemplate[]>([]);
  const [genModels, setGenModels] = useState<string[]>([]);
  const [warmModels, setWarmModels] = useState<string[]>([]);
  // 'auto' = fast-path cho câu xác định, model chất lượng mặc định cho RAG;
  // '' = mặc định máy chủ; hoặc tên model cụ thể
  const [selectedModel, setSelectedModel] = useState('auto');
  const [showUploadModal, setShowUploadModal] = useState(false);
  const [showSourcePicker, setShowSourcePicker] = useState(false);
  const [sourceDocs, setSourceDocs] = useState<BrowseDocument[]>([]);
  const [sourceQuery, setSourceQuery] = useState('');
  const [selectedSourceIds, setSelectedSourceIds] = useState<number[]>([]);
  const [sourcesLoading, setSourcesLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [quota, setQuota] = useState<{ used: number; limit: number } | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const isClient = isClientRole(currentUser?.role);
  const serverConvId = activeConversation?.server_id;
  // Nhân viên nội bộ luôn tải được: chế độ "lưu vào kho" không cần mã hội thoại,
  // chỉ chế độ "dùng tạm" cần (modal tự báo nếu chưa có).
  const canUpload = !isClient;

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [activeConversation?.messages, isChatStreaming]);

  const openSourcePicker = async () => {
    setShowSourcePicker(true);
  };

  // Tìm trên server thay vì chỉ lọc 300 dòng đầu. Với kho lớn, nhập tên/mã
  // tài liệu vẫn tìm được nguồn nằm ngoài trang đầu.
  useEffect(() => {
    if (!showSourcePicker || isClient) return;
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      setSourcesLoading(true);
      try {
        const docs = await api.getBrowseDocuments({ q: sourceQuery.trim() });
        if (!cancelled) {
          setSourceDocs((Array.isArray(docs) ? docs : []).filter((doc) => doc.can_open));
        }
      } catch (err: any) {
        if (!cancelled) setErrorMessage(err?.message || 'Không tải được danh sách nguồn.');
      } finally {
        if (!cancelled) setSourcesLoading(false);
      }
    }, sourceQuery.trim() ? 250 : 0);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [showSourcePicker, sourceQuery, isClient]);

  // Bộ nguồn là phạm vi của hội thoại hiện tại. Đổi hội thoại phải bỏ lựa chọn
  // cũ để không vô tình giới hạn câu hỏi mới vào hồ sơ của cuộc chat trước.
  useEffect(() => {
    setSelectedSourceIds([]);
    setSourceQuery('');
  }, [activeConvId]);

  const refreshModels = () => {
    if (isClient) return;
    api.getModels().then((m) => {
      setGenModels(Array.isArray(m?.generation) ? m.generation : []);
      setWarmModels(Array.isArray(m?.loaded) ? m.loaded : []);
    }).catch(() => undefined);
  };

  useEffect(() => {
    if (isClient) return;
    api
      .getMethods()
      .then((templates) => setMethodTemplates(Array.isArray(templates) ? templates : []))
      .catch(() => setMethodTemplates([]));
    // Danh sách model để chọn ngay ô chat (chỉ nhân viên nội bộ)
    refreshModels();
    // refreshModels chỉ phụ thuộc vai hiện tại; gọi lại khi isClient đổi.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isClient]);

  const handleSendMessage = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const questionText = inputQuestion.trim();
    if (!questionText || isChatStreaming || !activeConversation) return;

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

    setChatStreaming(true);
    // Ô trống cho câu trả lời, chữ sẽ chảy dần vào đây.
    const aiMsgId = `ai-${Date.now()}`;
    let opened = false;

    try {
      await api.chatStream(
        {
          question: questionText,
          conversation_id: serverConvId ?? null,
          use_temp: Boolean(tempFileName),
          use_method: useMethod && !isClient,
          model: isClient ? undefined : selectedModel,
          source_document_ids:
            isClient || selectedSourceIds.length === 0 ? undefined : selectedSourceIds,
        },
        (evt) => {
          if (evt.type === 'start' && evt.conversation_id) {
            // Ghi nhớ mã hội thoại do backend cấp để các lượt sau nối đúng ngữ cảnh
            setConvServerId(activeConvId, evt.conversation_id);
            return;
          }
          if (evt.type === 'meta') {
            // Dựng bong bóng nhưng vẫn khoá lượt gửi mới. Chỉ sự kiện
            // `done` mới xác nhận backend đã lưu xong toàn bộ câu trả lời.
            addMessageToConv(activeConvId, {
              id: aiMsgId,
              sender: 'ai',
              text: '',
              sources: evt.sources,
              timestamp: nowLabel(),
              isStreaming: true,
              grounding_status: evt.grounding_status,
              answer_mode: evt.answer_mode,
            });
            opened = true;
            return;
          }
          if (evt.type === 'delta' && evt.text) {
            const piece = evt.text;
            updateMessage(aiMsgId, (m) => ({ ...m, text: m.text + piece }));
            return;
          }
          if (evt.type === 'replace') {
            updateMessage(aiMsgId, (m) => ({
              ...m,
              text: evt.text ?? m.text,
              grounding_status: evt.grounding_status ?? m.grounding_status,
              answer_mode: evt.answer_mode ?? m.answer_mode,
            }));
            return;
          }
          if (evt.type === 'done') {
            if (evt.quota) setQuota(evt.quota);
            refreshModels();
            updateMessage(aiMsgId, (m) => ({
              ...m,
              isStreaming: false,
              latency_ms: evt.latency_ms,
              serverMessageId: evt.message_id,
              timings: evt.timings,
              grounding_status: evt.grounding_status ?? m.grounding_status,
              answer_mode: evt.answer_mode ?? m.answer_mode,
              // Bản nguồn CUỐI đã lọc "chỉ nguồn liên quan" (được trích dẫn /
              // điểm cao) — thay danh sách đầy đủ đã gửi ở meta.
              sources: evt.sources ?? m.sources,
            }));
          }
        }
      );
    } catch (err: any) {
      const errMsg = err?.message || 'Có lỗi xảy ra khi hỏi AI.';
      setErrorMessage(errMsg);
      if (opened) {
        // Đứt giữa chừng: giữ lại phần đã viết, ghi rõ là chưa trọn vẹn — xoá
        // đi thì người dùng mất luôn phần nội dung có thể vẫn dùng được.
        updateMessage(aiMsgId, (m) => ({
          ...m,
          isStreaming: false,
          text: `${m.text}\n\n_(Câu trả lời bị ngắt giữa chừng: ${errMsg})_`,
        }));
      } else {
        addMessageToConv(activeConvId, {
          id: `err-${Date.now()}`,
          sender: 'ai',
          text: errMsg,
          timestamp: nowLabel(),
          isError: true,
        });
      }
    } finally {
      setChatStreaming(false);
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
  const visibleSourceDocs = sourceDocs;

  return (
    <div className="flex w-full h-[calc(100dvh-4rem)] bg-hds-soft dark:bg-slate-950 overflow-hidden">
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
                type="button"
                onClick={openSourcePicker}
                disabled={isChatStreaming}
                className={`flex items-center gap-1.5 font-semibold text-xs px-3 py-1.5 rounded-xl border transition-colors disabled:opacity-50 ${
                  selectedSourceIds.length > 0
                    ? 'bg-blue-50 dark:bg-blue-950/60 text-hds-navy dark:text-blue-200 border-blue-300 dark:border-blue-800'
                    : 'bg-slate-50 dark:bg-slate-800 text-slate-600 dark:text-slate-300 border-slate-200 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-700'
                }`}
                title="Giới hạn câu trả lời trong các tài liệu đã chọn"
              >
                <BookOpen className="w-3.5 h-3.5" />
                <span className="hidden sm:inline">
                  {selectedSourceIds.length > 0
                    ? `Nguồn đã chọn (${selectedSourceIds.length})`
                    : 'Chọn nguồn'}
                </span>
              </button>
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

          {isChatStreaming && !messages.some((message) => message.isStreaming) && (
            <div className="py-5 px-4 sm:px-6 border-b border-slate-100 dark:border-slate-800 bg-white dark:bg-slate-900">
              <div className="max-w-3xl mx-auto flex items-start gap-3.5">
                {/* Avatar trợ lý — giống hệt tin nhắn thật để nhìn ra ngay là bot đang soạn */}
                <div className="w-8 h-8 rounded-xl flex items-center justify-center shrink-0 shadow-sm bg-hds-navy text-hds-gold border border-hds-gold/40">
                  <Bot className="w-4 h-4" />
                </div>
                <div className="min-w-0 pt-1">
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-sm text-slate-900 dark:text-slate-100">
                      Trợ lý AI HDS
                    </span>
                    <span className="flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400">
                      <span>đang trả lời</span>
                      <span className="flex gap-0.5">
                        <span className="w-1.5 h-1.5 rounded-full bg-hds-navy dark:bg-blue-400 animate-bounce [animation-delay:-0.3s]" />
                        <span className="w-1.5 h-1.5 rounded-full bg-hds-navy dark:bg-blue-400 animate-bounce [animation-delay:-0.15s]" />
                        <span className="w-1.5 h-1.5 rounded-full bg-hds-navy dark:bg-blue-400 animate-bounce" />
                      </span>
                    </span>
                  </div>
                  <p className="text-[11px] text-slate-400 dark:text-slate-500 mt-1">
                    Đang tra cứu tài liệu và dữ liệu công ty — câu hỏi phức tạp có thể mất vài chục giây.
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
                disabled={isChatStreaming}
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
                  disabled={!inputQuestion.trim() || isChatStreaming}
                  className="p-2.5 rounded-xl transition-colors bg-hds-navy text-hds-gold hover:bg-hds-navy-light disabled:bg-slate-200 dark:disabled:bg-slate-800 disabled:text-slate-400 disabled:cursor-not-allowed"
                  title="Gửi câu hỏi"
                  aria-label="Gửi câu hỏi"
                >
                  {isChatStreaming ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Send className="w-4 h-4" />
                  )}
                </button>
              </div>
            </div>

            <div className="flex items-center justify-between gap-3 text-[11px] text-slate-400 dark:text-slate-500 px-1">
              <span className="flex items-center gap-2 min-w-0">
                {/* Bộ chọn model — chỉ nhân viên nội bộ, khi máy chủ có model */}
                {!isClient && genModels.length > 0 && (
                  <span className="flex items-center gap-1 shrink-0">
                    <Cpu className="w-3.5 h-3.5 text-hds-navy dark:text-blue-400" />
                    <select
                      value={selectedModel}
                      onChange={(e) => setSelectedModel(e.target.value)}
                      onFocus={refreshModels}
                      aria-label="Chọn mô hình AI"
                      title="Tự động: câu dữ liệu xác định không gọi model; tra cứu tài liệu dùng model chất lượng mặc định"
                      className="bg-transparent text-slate-500 dark:text-slate-400 font-semibold border border-slate-200 dark:border-slate-700 rounded-lg px-1.5 py-0.5 focus:ring-2 focus:ring-hds-blue focus:outline-none cursor-pointer max-w-[190px]"
                    >
                      <option value="auto">⚡ Tự động</option>
                      {/* Dấu ● = model đang nằm sẵn trong bộ nhớ, trả lời được
                          ngay. Dấu ○ = phải nạp vài GB từ ổ cứng trước đã. */}
                      {genModels.map((m) => (
                        <option key={m} value={m}>
                          {warmModels.includes(m) ? `● ${m}` : `○ ${m} (phải nạp)`}
                        </option>
                      ))}
                    </select>
                  </span>
                )}
                <span className="flex items-center gap-1.5 min-w-0">
                  <span className="shrink-0">Chế độ:</span>
                  {activeConversation?.temp_file ? (
                    <span className="text-amber-700 dark:text-amber-300 font-semibold bg-amber-50 dark:bg-amber-950/60 px-1.5 py-0.5 rounded border border-amber-200 dark:border-amber-800 truncate">
                      Có tài liệu tạm đính kèm
                    </span>
                  ) : (
                    <span className="truncate">
                      {isClient ? 'Cổng khách hàng' : 'Tra cứu kho nội bộ'}
                    </span>
                  )}
                </span>
              </span>
              <span className="hidden sm:inline shrink-0">HDS Law Firm — Nền tảng AI Pháp lý</span>
            </div>
          </form>
        </div>
      </main>

      {showSourcePicker && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/60 backdrop-blur-sm p-4"
          onClick={() => setShowSourcePicker(false)}
          role="presentation"
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="source-picker-title"
            onClick={(event) => event.stopPropagation()}
            className="w-full max-w-2xl max-h-[82vh] flex flex-col bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-2xl shadow-2xl overflow-hidden"
          >
            <div className="p-4 border-b border-slate-200 dark:border-slate-800 flex items-start justify-between gap-3">
              <div>
                <h3 id="source-picker-title" className="font-bold text-sm text-slate-900 dark:text-slate-100">
                  Chọn bộ nguồn cho hội thoại
                </h3>
                <p className="text-[11px] text-slate-500 dark:text-slate-400 mt-0.5">
                  Khi có lựa chọn, backend chỉ tra cứu trong các tài liệu này.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setShowSourcePicker(false)}
                className="p-1 text-slate-400 hover:text-slate-700 dark:hover:text-slate-200"
                aria-label="Đóng bộ chọn nguồn"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="p-3 border-b border-slate-100 dark:border-slate-800">
              <div className="flex items-center gap-2 px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800">
                <Search className="w-4 h-4 text-slate-400" />
                <input
                  value={sourceQuery}
                  onChange={(event) => setSourceQuery(event.target.value)}
                  placeholder="Tìm theo tên tài liệu…"
                  className="flex-1 min-w-0 bg-transparent outline-none text-xs text-slate-800 dark:text-slate-100"
                />
              </div>
            </div>

            <div className="flex-1 overflow-y-auto p-3">
              {sourcesLoading ? (
                <div className="py-12 flex items-center justify-center gap-2 text-xs text-slate-500">
                  <Loader2 className="w-4 h-4 animate-spin" /> Đang tải kho tài liệu…
                </div>
              ) : visibleSourceDocs.length === 0 ? (
                <p className="py-12 text-center text-xs text-slate-500">
                  Không có tài liệu có quyền mở phù hợp.
                </p>
              ) : (
                <div className="space-y-1.5">
                  {visibleSourceDocs.map((doc) => {
                    const checked = selectedSourceIds.includes(doc.id);
                    return (
                      <label
                        key={doc.id}
                        className={`flex items-start gap-3 p-3 rounded-xl border cursor-pointer transition-colors ${
                          checked
                            ? 'bg-blue-50 dark:bg-blue-950/40 border-blue-300 dark:border-blue-800'
                            : 'bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-800'
                        }`}
                      >
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() =>
                            setSelectedSourceIds((ids) =>
                              checked ? ids.filter((id) => id !== doc.id) : [...ids, doc.id]
                            )
                          }
                          className="sr-only"
                        />
                        <span
                          className={`mt-0.5 w-4 h-4 rounded border flex items-center justify-center shrink-0 ${
                            checked
                              ? 'bg-hds-navy border-hds-navy text-hds-gold'
                              : 'border-slate-300 dark:border-slate-600'
                          }`}
                        >
                          {checked && <Check className="w-3 h-3" />}
                        </span>
                        <span className="min-w-0">
                          <span className="block text-xs font-semibold text-slate-800 dark:text-slate-100 break-words">
                            {doc.title}
                          </span>
                          {(doc.doc_type || doc.department) && (
                            <span className="block mt-0.5 text-[10px] text-slate-500 dark:text-slate-400">
                              {[doc.doc_type, doc.department].filter(Boolean).join(' · ')}
                            </span>
                          )}
                        </span>
                      </label>
                    );
                  })}
                </div>
              )}
            </div>

            <div className="p-3 border-t border-slate-200 dark:border-slate-800 flex items-center justify-between gap-3">
              <button
                type="button"
                onClick={() => setSelectedSourceIds([])}
                disabled={selectedSourceIds.length === 0}
                className="px-3 py-2 text-xs font-semibold text-slate-500 hover:text-hds-red disabled:opacity-40"
              >
                Bỏ chọn tất cả
              </button>
              <button
                type="button"
                onClick={() => setShowSourcePicker(false)}
                className="px-4 py-2 rounded-xl bg-hds-navy text-hds-gold text-xs font-bold"
              >
                Dùng {selectedSourceIds.length || 'toàn bộ'} nguồn
              </button>
            </div>
          </div>
        </div>
      )}

      <FileUploadModal
        isOpen={showUploadModal}
        onClose={() => setShowUploadModal(false)}
        conversationId={serverConvId ?? null}
        localConversationId={activeConvId}
      />
    </div>
  );
};
