import React, { useState } from 'react';
import type { ChatMessage } from '../../types';
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
} from 'lucide-react';

interface ChatMessageItemProps {
  message: ChatMessage;
}

export const ChatMessageItem: React.FC<ChatMessageItemProps> = ({ message }) => {
  const isUser = message.sender === 'user';
  const isError = Boolean(message.isError);
  const [showSources, setShowSources] = useState(true);

  const rowBg = isError
    ? 'bg-red-50/70 dark:bg-red-950/30'
    : isUser
    ? 'bg-slate-50/80 dark:bg-slate-800/40'
    : 'bg-white dark:bg-slate-900';

  return (
    <div className={`py-5 px-4 sm:px-6 border-b border-slate-100 dark:border-slate-800 ${rowBg}`}>
      <div className="max-w-3xl mx-auto flex items-start gap-3.5">
        {/* Ảnh đại diện */}
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

        {/* Nội dung */}
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

          {/* Nhãn tuỳ chọn đã áp dụng */}
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

          {/* Nội dung tin nhắn */}
          <div
            className={`text-sm leading-relaxed whitespace-pre-wrap break-words ${
              isError
                ? 'text-red-800 dark:text-red-200 font-medium'
                : 'text-slate-800 dark:text-slate-200'
            }`}
          >
            {message.text}
          </div>

          {/* Nguồn trích dẫn */}
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
        </div>
      </div>
    </div>
  );
};
