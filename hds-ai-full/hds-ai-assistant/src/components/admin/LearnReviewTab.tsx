import React, { useEffect, useState } from 'react';
import { useApp } from '../../context/AppContext';
import * as api from '../../api';
import type { PendingLearnMessage } from '../../types';
import { CheckCircle2, XCircle, Edit3, RefreshCw, Sparkles, Save, HelpCircle } from 'lucide-react';

interface ItemState {
  edited_content: string;
  edit_reason: string;
  isSubmitting: boolean;
}

export const LearnReviewTab: React.FC = () => {
  const { showToast } = useApp();
  const [messages, setMessages] = useState<PendingLearnMessage[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [itemStates, setItemStates] = useState<Record<string, ItemState>>({});

  const fetchPendingLearns = async () => {
    setIsLoading(true);
    try {
      const data = await api.getPendingLearns();
      setMessages(data);
      setItemStates(
        Object.fromEntries(
          data.map((item) => [
            String(item.message_id),
            { edited_content: item.answer, edit_reason: '', isSubmitting: false },
          ])
        )
      );
    } catch (err: any) {
      showToast(err?.message || 'Lỗi khi tải danh sách hội thoại chờ duyệt', 'error');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchPendingLearns();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const patchState = (msgId: string, patch: Partial<ItemState>) => {
    setItemStates((prev) => ({ ...prev, [msgId]: { ...prev[msgId], ...patch } }));
  };

  const handleAction = async (msgId: number, action: 'approve' | 'edit' | 'reject') => {
    const key = String(msgId);
    const state = itemStates[key];
    if (!state) return;

    if (action === 'edit' && !state.edited_content.trim()) {
      showToast('Nội dung hiệu chỉnh không được để trống.', 'error');
      return;
    }

    patchState(key, { isSubmitting: true });

    try {
      await api.reviewLearnMessage(msgId, {
        action,
        edited_content: action === 'edit' ? state.edited_content : undefined,
        edit_reason: action === 'edit' ? state.edit_reason : undefined,
      });

      const labels = {
        approve: 'Đã chấp thuận và nạp câu trả lời vào kho tri thức.',
        edit: 'Đã lưu bản hiệu chỉnh và nạp vào kho tri thức.',
        reject: 'Đã loại bỏ câu trả lời khỏi hàng chờ học.',
      } as const;

      showToast(labels[action], 'success');
      setMessages((prev) => prev.filter((m) => m.message_id !== msgId));
    } catch (err: any) {
      patchState(key, { isSubmitting: false });
      showToast(err?.message || 'Lỗi khi xử lý hội thoại', 'error');
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center p-12 text-slate-500 dark:text-slate-400 gap-2 text-sm">
        <RefreshCw className="w-5 h-5 animate-spin text-hds-navy dark:text-blue-400" />
        <span>Đang tải các cuộc hội thoại cần thẩm định…</span>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Tiêu đề khu vực */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 bg-white dark:bg-slate-900 p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm">
        <div>
          <h2 className="text-lg font-bold text-slate-900 dark:text-slate-100">
            Duyệt hội thoại để AI tự học
          </h2>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
            Thẩm định và chuẩn hoá câu trả lời thực tế trước khi đưa vào kho tri thức của HDS
          </p>
        </div>
        <button
          onClick={fetchPendingLearns}
          className="flex items-center gap-1.5 px-3.5 py-2 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 font-semibold text-xs rounded-xl transition-colors shrink-0"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          <span>Tải lại danh sách</span>
        </button>
      </div>

      {messages.length === 0 ? (
        <div className="bg-white dark:bg-slate-900 rounded-2xl p-12 text-center border border-slate-200 dark:border-slate-800 space-y-3">
          <Sparkles className="w-12 h-12 text-indigo-500 mx-auto opacity-80" />
          <h3 className="font-bold text-slate-800 dark:text-slate-100 text-base">
            Không có câu trả lời nào chờ duyệt
          </h3>
          <p className="text-xs text-slate-500 dark:text-slate-400 max-w-sm mx-auto">
            Tất cả hội thoại đã được thẩm định hoặc nạp vào kho tri thức.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {messages.map((msg) => {
            const key = String(msg.message_id);
            const state = itemStates[key] || {
              edited_content: msg.answer,
              edit_reason: '',
              isSubmitting: false,
            };
            const isEdited = state.edited_content !== msg.answer;

            return (
              <div
                key={msg.message_id}
                className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm p-5 space-y-4 hover:border-slate-300 dark:hover:border-slate-700 transition-colors"
              >
                {/* Thông tin tin nhắn */}
                <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500 dark:text-slate-400 pb-3 border-b border-slate-100 dark:border-slate-800">
                  <div className="flex items-center gap-2">
                    <span className="font-mono bg-slate-100 dark:bg-slate-800 px-2 py-0.5 rounded text-[11px]">
                      ID: {msg.message_id}
                    </span>
                    <span>Tạo lúc {msg.created_at}</span>
                  </div>
                  <span className="bg-indigo-50 dark:bg-indigo-950 text-indigo-700 dark:text-indigo-300 border border-indigo-200 dark:border-indigo-800 px-2.5 py-0.5 rounded-full font-semibold text-[11px]">
                    Chờ duyệt học tập
                  </span>
                </div>

                {/* Câu hỏi */}
                <div className="bg-slate-50 dark:bg-slate-800/60 rounded-xl p-3.5 border border-slate-200 dark:border-slate-700 space-y-1">
                  <div className="flex items-center gap-2 text-xs font-bold text-hds-navy dark:text-blue-300">
                    <HelpCircle className="w-4 h-4 text-hds-gold" />
                    <span>Câu hỏi của người dùng</span>
                  </div>
                  <p className="text-xs text-slate-800 dark:text-slate-200 font-medium pl-6 leading-relaxed break-words">
                    {msg.question || '(không lấy được câu hỏi gốc)'}
                  </p>
                </div>

                {/* Câu trả lời có thể sửa */}
                <div className="space-y-2">
                  <label
                    htmlFor={`answer-${msg.message_id}`}
                    className="text-xs font-bold text-slate-800 dark:text-slate-200 flex flex-wrap items-center justify-between gap-2"
                  >
                    <span className="flex items-center gap-1.5">
                      <Edit3 className="w-3.5 h-3.5 text-hds-blue" />
                      <span>Nội dung câu trả lời</span>
                      {isEdited && (
                        <span className="text-[10px] font-semibold text-amber-700 dark:text-amber-300 bg-amber-100 dark:bg-amber-950 border border-amber-300 dark:border-amber-800 px-1.5 py-0.5 rounded">
                          đã sửa
                        </span>
                      )}
                    </span>
                    <span className="text-[10px] text-slate-400 font-normal">
                      Sửa trực tiếp nếu cần bổ sung căn cứ pháp lý
                    </span>
                  </label>

                  <textarea
                    id={`answer-${msg.message_id}`}
                    rows={5}
                    value={state.edited_content}
                    onChange={(e) => patchState(key, { edited_content: e.target.value })}
                    className="w-full p-3 border border-slate-300 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 rounded-xl text-xs font-sans focus:ring-2 focus:ring-hds-blue focus:outline-none leading-relaxed resize-y transition-colors"
                  />
                </div>

                <input
                  type="text"
                  placeholder="Lý do hiệu chỉnh (không bắt buộc)…"
                  value={state.edit_reason}
                  onChange={(e) => patchState(key, { edit_reason: e.target.value })}
                  aria-label="Lý do hiệu chỉnh"
                  className="w-full px-3 py-2 border border-slate-200 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 rounded-lg text-xs placeholder-slate-400 focus:ring-2 focus:ring-hds-blue focus:outline-none transition-colors"
                />

                {/* Ba hành động */}
                <div className="flex flex-wrap items-center justify-end gap-2 pt-3 border-t border-slate-100 dark:border-slate-800">
                  <button
                    onClick={() => handleAction(msg.message_id, 'reject')}
                    disabled={state.isSubmitting}
                    className="px-4 py-2 bg-red-50 dark:bg-red-950/50 hover:bg-red-100 dark:hover:bg-red-950 text-hds-red dark:text-red-300 border border-red-200 dark:border-red-900 font-bold text-xs rounded-xl flex items-center gap-1.5 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    <XCircle className="w-4 h-4" />
                    <span>Bỏ qua</span>
                  </button>

                  <button
                    onClick={() => handleAction(msg.message_id, 'edit')}
                    disabled={state.isSubmitting}
                    className="px-4 py-2 bg-hds-soft dark:bg-slate-800 hover:bg-blue-100 dark:hover:bg-slate-700 text-hds-navy dark:text-blue-300 border border-blue-200 dark:border-slate-700 font-bold text-xs rounded-xl flex items-center gap-1.5 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    <Save className="w-4 h-4" />
                    <span>Lưu bản sửa</span>
                  </button>

                  <button
                    onClick={() => handleAction(msg.message_id, 'approve')}
                    disabled={state.isSubmitting}
                    className="px-5 py-2 bg-hds-green hover:bg-emerald-800 text-white font-bold text-xs rounded-xl shadow-sm flex items-center gap-1.5 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    <CheckCircle2 className="w-4 h-4" />
                    <span>{state.isSubmitting ? 'Đang xử lý…' : 'Đạt — nạp học'}</span>
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
