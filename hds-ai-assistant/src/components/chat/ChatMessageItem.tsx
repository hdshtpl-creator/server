import React, { useState } from 'react';
import type { ChatMessage } from '../../types';
import { useApp } from '../../context/AppContext';
import * as api from '../../api';
import {
  User,
  Bot,
  BookOpen,
  ChevronDown,
  ChevronUp,
  FileText,
  Sliders,
  Clock,
  AlertTriangle,
  ThumbsUp,
  ThumbsDown,
  Send,
  CheckCircle2,
  Flag,
} from 'lucide-react';

interface ChatMessageItemProps {
  message: ChatMessage;
}

export const ChatMessageItem: React.FC<ChatMessageItemProps> = ({ message }) => {
  const { showToast } = useApp();
  const isUser = message.sender === 'user';
  const isError = Boolean(message.isError);
  const [showSources, setShowSources] = useState(true);

  const canReport = !isUser && !isError && typeof message.serverMessageId === 'number';
  const [noteOpen, setNoteOpen] = useState(false);
  const [note, setNote] = useState('');
  const [sent, setSent] = useState(false);
  const [sending, setSending] = useState(false);

  const submitFeedback = async (rating: 'good' | 'bad', withNote = '') => {
    if (!message.serverMessageId || sending) return;
    setSending(true);
    try {
      await api.sendFeedback({ message_id: message.serverMessageId, rating, note: withNote });
      setSent(true);
      setNoteOpen(false);
    } catch (err: any) {
      showToast(err?.message || 'Không gửi được báo cáo.', 'error');
    } finally {
      setSending(false);
    }
  };

  const rowBg = isError
    ? 'bg-red-50/70 dark:bg-red-950/30'
    : isUser
    ? 'bg-slate-50/80 dark:bg-slate-800/40'
    : 'bg-white dark:bg-slate-900';

  return (
    <div
      className={`group py-5 px-4 sm:px-6 border-b border-slate-100 dark:border-slate-800 ${rowBg}`}
    >
      <div className="max-w-3xl mx-auto flex items-start gap-3.5">
        <div
          className={`w-8 h-8 rounded-xl flex items-center justify-center shrink-0 shadow-sm ${
            isError
              ? 'bg-hds-red text-white'
              : isUser
              ? 'bg-slate-700 dark:bg-slate-600 text-white'
              : 'bg-hds-navy text-hds-gold border border-hds-gold/40'
          }`}
        >
          {isError ? (
            <AlertTriangle className="w-4 h-4" />
          ) : isUser ? (
            <User className="w-4 h-4" />
          ) : (
            <Bot className="w-4 h-4" />
          )}
        </div>

        <div className="flex-1 space-y-2 min-w-0">
          <div className="flex items-center justify-between gap-3 text-xs">
            <span className="font-semibold text-slate-800 dark:text-slate-100">
              {isUser ? 'Bạn' : 'Trợ lý AI HDS'}
            </span>

            <div className="flex items-center gap-2 text-[11px] text-slate-400 dark:text-slate-500 shrink-0">
              {typeof message.latency_ms === 'number' && (
                <span className="flex items-center gap-1 font-mono" title="Thời gian phản hồi">
                  <Clock className="w-3 h-3" />
                  {message.latency_ms}ms
                </span>
              )}
              <span>{message.timestamp}</span>
            </div>
          </div>

          {(message.used_method || message.used_temp_file) && (
            <div className="flex flex-wrap gap-1.5 text-[10px] font-medium">
              {message.used_method && (
                <span className="bg-amber-100 dark:bg-amber-950/60 text-amber-900 dark:text-amber-200 border border-amber-300 dark:border-amber-800 px-2 py-0.5 rounded-md flex items-center gap-1">
                  <Sliders className="w-3 h-3" />
                  Áp dụng mẫu phương pháp
                </span>
              )}
              {message.used_temp_file && (
                <span className="bg-blue-100 dark:bg-blue-950/60 text-blue-900 dark:text-blue-200 border border-blue-300 dark:border-blue-800 px-2 py-0.5 rounded-md flex items-center gap-1 max-w-full">
                  <FileText className="w-3 h-3 shrink-0" />
                  <span className="truncate">Tài liệu tạm: {message.used_temp_file}</span>
                </span>
              )}
            </div>
          )}

          <div
            className={`text-sm leading-relaxed whitespace-pre-wrap break-words ${
              isError
                ? 'text-red-800 dark:text-red-200 font-medium'
                : 'text-slate-800 dark:text-slate-200'
            }`}
          >
            {message.text}
          </div>

          {!isUser && message.sources && message.sources.length > 0 && (
            <div className="mt-3 pt-3 border-t border-slate-100 dark:border-slate-800">
              <button
                onClick={() => setShowSources(!showSources)}
                className="flex items-center justify-between w-full text-xs font-semibold bg-slate-50 dark:bg-slate-800/70 hover:bg-slate-100 dark:hover:bg-slate-800 p-2 rounded-lg border border-slate-200 dark:border-slate-700 transition-colors"
                aria-expanded={showSources}
              >
                <span className="flex items-center gap-1.5 text-hds-navy dark:text-blue-300">
                  <BookOpen className="w-4 h-4 text-hds-gold" />
                  <span>Nguồn trích dẫn ({message.sources.length})</span>
                </span>
                {showSources ? (
                  <ChevronUp className="w-3.5 h-3.5 text-slate-400" />
                ) : (
                  <ChevronDown className="w-3.5 h-3.5 text-slate-400" />
                )}
              </button>

              {showSources && (
                <ul className="mt-2 space-y-1.5">
                  {message.sources.map((src, idx) => {
                    const score =
                      typeof src.relevance_score === 'number'
                        ? Math.round(src.relevance_score * 100)
                        : null;

                    return (
                      <li
                        key={`${src.doc_id ?? 'src'}-${idx}`}
                        className="bg-hds-soft dark:bg-slate-800/50 border border-blue-100 dark:border-slate-700 rounded-lg p-2.5 text-xs flex items-start justify-between gap-3"
                      >
                        <div className="flex items-start gap-2 min-w-0">
                          <BookOpen className="w-3.5 h-3.5 text-hds-navy dark:text-blue-300 shrink-0 mt-0.5" />
                          <div className="min-w-0">
                            <span className="font-semibold text-slate-800 dark:text-slate-100 block break-words">
                              {src.title}
                            </span>
                            {src.doc_id && (
                              <span className="text-[10px] font-mono text-slate-400 dark:text-slate-500 block mt-0.5">
                                Mã tài liệu: {src.doc_id}
                              </span>
                            )}
                          </div>
                        </div>

                        {score !== null && (
                          <div
                            className="shrink-0 flex items-center gap-1 bg-white dark:bg-slate-900 px-2 py-0.5 rounded border border-blue-200 dark:border-slate-700"
                            title="Mức độ liên quan do AI chấm"
                          >
                            <span className="text-[10px] text-slate-500 dark:text-slate-400 hidden sm:inline">
                              Liên quan
                            </span>
                            <span
                              className={`font-bold text-xs ${
                                score >= 90
                                  ? 'text-hds-green dark:text-emerald-400'
                                  : score >= 75
                                  ? 'text-hds-blue dark:text-blue-400'
                                  : 'text-amber-600 dark:text-amber-400'
                              }`}
                            >
                              {score}%
                            </span>
                          </div>
                        )}
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          )}

          {/* Báo cáo chất lượng câu trả lời */}
          {canReport && (
            <div className="pt-1">
              {sent ? (
                <span className="inline-flex items-center gap-1 text-[11px] text-hds-green dark:text-emerald-400 font-medium">
                  <CheckCircle2 className="w-3.5 h-3.5" />
                  Đã gửi báo cáo, cảm ơn bạn.
                </span>
              ) : (
                <div className="flex items-center gap-1 opacity-40 group-hover:opacity-100 focus-within:opacity-100 transition-opacity">
                  <span className="text-[10px] text-slate-400 dark:text-slate-500 mr-0.5">
                    Câu trả lời này thế nào?
                  </span>
                  <button
                    onClick={() => submitFeedback('good')}
                    disabled={sending}
                    title="Câu trả lời tốt"
                    aria-label="Báo cáo: câu trả lời tốt"
                    className="p-1.5 rounded-lg text-slate-400 hover:text-hds-green hover:bg-emerald-50 dark:hover:bg-emerald-950/40 transition-colors"
                  >
                    <ThumbsUp className="w-3.5 h-3.5" />
                  </button>
                  <button
                    onClick={() => setNoteOpen(true)}
                    disabled={sending}
                    title="Báo cáo câu trả lời chưa ổn"
                    aria-label="Báo cáo: câu trả lời chưa tốt"
                    className="p-1.5 rounded-lg text-slate-400 hover:text-hds-red hover:bg-red-50 dark:hover:bg-red-950/40 transition-colors"
                  >
                    <ThumbsDown className="w-3.5 h-3.5" />
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Popup báo cáo — mở khi bấm 👎 */}
      {noteOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
          onClick={() => {
            setNoteOpen(false);
            setNote('');
          }}
        >
          <div
            className="bg-white dark:bg-slate-900 rounded-2xl shadow-xl border border-slate-200 dark:border-slate-800 w-full max-w-md p-5 space-y-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start gap-3">
              <span className="p-2 bg-red-50 dark:bg-red-950 text-hds-red rounded-xl shrink-0">
                <Flag className="w-5 h-5" />
              </span>
              <div>
                <h3 className="font-bold text-sm text-slate-900 dark:text-slate-100">
                  Báo cáo câu trả lời chưa ổn
                </h3>
                <p className="text-[11px] text-slate-500 dark:text-slate-400 mt-0.5 leading-relaxed">
                  Ghi rõ sai ở đâu, thiếu căn cứ nào. Quản trị sẽ sửa lại và dạy AI để lần sau gặp
                  câu tương tự trả lời đúng.
                </p>
              </div>
            </div>
            <textarea
              rows={4}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              autoFocus
              placeholder="Ví dụ: trả lời sai điều luật áp dụng, cần dẫn Điều 159 Luật Doanh nghiệp 2020…"
              className="w-full px-3 py-2 border border-slate-300 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 rounded-xl text-xs focus:ring-2 focus:ring-hds-blue focus:outline-none resize-y"
            />
            <div className="flex items-center justify-end gap-2">
              <button
                onClick={() => {
                  setNoteOpen(false);
                  setNote('');
                }}
                className="px-3.5 py-2 rounded-xl text-xs font-medium text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
              >
                Huỷ
              </button>
              <button
                onClick={() => submitFeedback('bad', note)}
                disabled={sending}
                className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-bold text-white bg-hds-red hover:bg-red-800 disabled:opacity-50 transition-colors"
              >
                <Send className="w-3.5 h-3.5" />
                {sending ? 'Đang gửi…' : 'Gửi báo cáo'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
