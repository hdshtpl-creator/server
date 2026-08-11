import React, { useEffect, useState } from 'react';
import { useApp } from '../../context/AppContext';
import * as api from '../../api';
import type { FeedbackItem } from '../../types';
import { ROLE_META, ACCESS_LEVELS } from '../../constants';
import {
  RefreshCw,
  ThumbsUp,
  ThumbsDown,
  CheckCircle2,
  XCircle,
  HelpCircle,
  Edit3,
  MessageSquareWarning,
  Loader2,
} from 'lucide-react';

interface ItemState {
  corrected_answer: string;
  admin_note: string;
  access_level: string;
  isSubmitting: boolean;
}

export const FeedbackReviewTab: React.FC = () => {
  const { showToast } = useApp();
  const [items, setItems] = useState<FeedbackItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [states, setStates] = useState<Record<string, ItemState>>({});

  const load = async () => {
    setIsLoading(true);
    try {
      const data = await api.getFeedbackPending();
      setItems(data);
      setStates(
        Object.fromEntries(
          data.map((f) => [
            String(f.id),
            {
              corrected_answer: f.answer,
              admin_note: '',
              access_level: 'internal',
              isSubmitting: false,
            },
          ])
        )
      );
    } catch (err: any) {
      showToast(err?.message || 'Không tải được danh sách báo cáo.', 'error');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const patch = (id: string, p: Partial<ItemState>) =>
    setStates((prev) => ({ ...prev, [id]: { ...prev[id], ...p } }));

  const handle = async (fid: number, action: 'apply' | 'reject') => {
    const key = String(fid);
    const st = states[key];
    if (!st) return;
    if (action === 'apply' && !st.corrected_answer.trim()) {
      showToast('Nội dung nạp vào bộ nhớ không được để trống.', 'error');
      return;
    }
    patch(key, { isSubmitting: true });
    try {
      await api.reviewFeedback(fid, {
        action,
        corrected_answer: action === 'apply' ? st.corrected_answer : undefined,
        admin_note: st.admin_note || undefined,
        access_level: st.access_level,
      });
      showToast(
        action === 'apply' ? 'Đã nạp câu trả lời vào bộ nhớ AI.' : 'Đã bỏ qua báo cáo.',
        'success'
      );
      setItems((prev) => prev.filter((f) => f.id !== fid));
    } catch (err: any) {
      patch(key, { isSubmitting: false });
      showToast(err?.message || 'Không xử lý được báo cáo.', 'error');
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center p-12 text-slate-500 dark:text-slate-400 gap-2 text-sm">
        <RefreshCw className="w-5 h-5 animate-spin text-hds-navy dark:text-blue-400" />
        <span>Đang tải báo cáo chất lượng…</span>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 bg-white dark:bg-slate-900 p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm">
        <div>
          <h2 className="text-lg font-bold text-slate-900 dark:text-slate-100">
            Duyệt báo cáo chất lượng
          </h2>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
            Người dùng báo cáo câu trả lời của AI. Sửa lại nếu cần rồi nạp vào bộ nhớ để bot trả lời
            tốt hơn lần sau.
          </p>
        </div>
        <button
          onClick={load}
          className="flex items-center gap-1.5 px-3.5 py-2 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 font-semibold text-xs rounded-xl transition-colors shrink-0"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          <span>Tải lại</span>
        </button>
      </div>

      {items.length === 0 ? (
        <div className="bg-white dark:bg-slate-900 rounded-2xl p-12 text-center border border-slate-200 dark:border-slate-800 space-y-3">
          <MessageSquareWarning className="w-12 h-12 text-slate-300 dark:text-slate-600 mx-auto" />
          <h3 className="font-bold text-slate-800 dark:text-slate-100 text-base">
            Không có báo cáo nào chờ xử lý
          </h3>
          <p className="text-xs text-slate-500 dark:text-slate-400 max-w-sm mx-auto">
            Khi người dùng bấm 👍/👎 cạnh câu trả lời của AI, báo cáo sẽ hiện ở đây.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {items.map((f) => {
            const key = String(f.id);
            const st = states[key] || {
              corrected_answer: f.answer,
              admin_note: '',
              access_level: 'internal',
              isSubmitting: false,
            };
            const role = ROLE_META[f.reporter_role as keyof typeof ROLE_META];
            const isBad = f.rating === 'bad';

            return (
              <div
                key={f.id}
                className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm p-5 space-y-4"
              >
                <div className="flex flex-wrap items-center justify-between gap-2 pb-3 border-b border-slate-100 dark:border-slate-800">
                  <div className="flex items-center gap-2">
                    <span
                      className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-bold border ${
                        isBad
                          ? 'bg-red-100 dark:bg-red-950 text-hds-red dark:text-red-300 border-red-300 dark:border-red-800'
                          : 'bg-emerald-100 dark:bg-emerald-950 text-hds-green dark:text-emerald-300 border-emerald-300 dark:border-emerald-800'
                      }`}
                    >
                      {isBad ? <ThumbsDown className="w-3 h-3" /> : <ThumbsUp className="w-3 h-3" />}
                      {isBad ? 'Chưa tốt' : 'Tốt'}
                    </span>
                    <span className="text-xs text-slate-600 dark:text-slate-300 font-medium">
                      {f.reporter || 'Ẩn danh'}
                    </span>
                    {role && (
                      <span
                        className={`text-[10px] font-semibold px-2 py-0.5 rounded-full border ${role.badge}`}
                      >
                        {role.label}
                      </span>
                    )}
                  </div>
                  <span className="text-[11px] text-slate-400 dark:text-slate-500 font-mono">
                    {f.created_at}
                  </span>
                </div>

                {f.note && (
                  <div className="bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-900 rounded-xl p-3 text-xs text-amber-900 dark:text-amber-200">
                    <span className="font-semibold">Ghi chú của người báo cáo: </span>
                    {f.note}
                  </div>
                )}

                <div className="bg-slate-50 dark:bg-slate-800/60 rounded-xl p-3 border border-slate-200 dark:border-slate-700 space-y-1">
                  <div className="flex items-center gap-1.5 text-xs font-bold text-hds-navy dark:text-blue-300">
                    <HelpCircle className="w-3.5 h-3.5 text-hds-gold" />
                    <span>Câu hỏi</span>
                  </div>
                  <p className="text-xs text-slate-700 dark:text-slate-300 pl-5 leading-relaxed">
                    {f.question || '(không lấy được câu hỏi gốc)'}
                  </p>
                </div>

                <div className="space-y-1.5">
                  <label
                    htmlFor={`ans-${f.id}`}
                    className="flex items-center gap-1.5 text-xs font-bold text-slate-800 dark:text-slate-200"
                  >
                    <Edit3 className="w-3.5 h-3.5 text-hds-blue" />
                    Câu trả lời của AI (sửa lại trước khi nạp nếu cần)
                  </label>
                  <textarea
                    id={`ans-${f.id}`}
                    rows={5}
                    value={st.corrected_answer}
                    onChange={(e) => patch(key, { corrected_answer: e.target.value })}
                    className="w-full p-3 border border-slate-300 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 rounded-xl text-xs leading-relaxed focus:ring-2 focus:ring-hds-blue focus:outline-none resize-y"
                  />
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div>
                    <label
                      htmlFor={`note-${f.id}`}
                      className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1"
                    >
                      Ghi chú của admin (không bắt buộc)
                    </label>
                    <input
                      id={`note-${f.id}`}
                      type="text"
                      value={st.admin_note}
                      onChange={(e) => patch(key, { admin_note: e.target.value })}
                      className="w-full px-3 py-2 border border-slate-300 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 rounded-xl text-xs focus:ring-2 focus:ring-hds-blue focus:outline-none"
                    />
                  </div>
                  <div>
                    <label
                      htmlFor={`acc-${f.id}`}
                      className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1"
                    >
                      Mức truy cập khi nạp
                    </label>
                    <select
                      id={`acc-${f.id}`}
                      value={st.access_level}
                      onChange={(e) => patch(key, { access_level: e.target.value })}
                      className="w-full px-3 py-2 border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 dark:text-slate-100 rounded-xl text-xs font-medium focus:ring-2 focus:ring-hds-blue focus:outline-none"
                    >
                      {ACCESS_LEVELS.map((a) => (
                        <option key={a.value} value={a.value}>
                          {a.label}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>

                <div className="flex flex-wrap items-center justify-end gap-2 pt-2 border-t border-slate-100 dark:border-slate-800">
                  <button
                    onClick={() => handle(f.id, 'reject')}
                    disabled={st.isSubmitting}
                    className="px-4 py-2 bg-red-50 dark:bg-red-950/50 hover:bg-red-100 dark:hover:bg-red-950 text-hds-red dark:text-red-300 border border-red-200 dark:border-red-900 font-bold text-xs rounded-xl flex items-center gap-1.5 transition-colors disabled:opacity-50"
                  >
                    <XCircle className="w-4 h-4" />
                    Bỏ qua
                  </button>
                  <button
                    onClick={() => handle(f.id, 'apply')}
                    disabled={st.isSubmitting}
                    className="px-5 py-2 bg-hds-green hover:bg-emerald-800 text-white font-bold text-xs rounded-xl shadow-sm flex items-center gap-1.5 transition-colors disabled:opacity-50"
                  >
                    {st.isSubmitting ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <CheckCircle2 className="w-4 h-4" />
                    )}
                    Nạp vào bộ nhớ AI
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
