import React, { useEffect, useState } from 'react';
import { useApp } from '../../context/AppContext';
import * as api from '../../api';
import type { Lead, LeadsResponse } from '../../types';
import { RefreshCw, Loader2, Phone, Mail, UserRound, CheckCircle2, XCircle, Undo2 } from 'lucide-react';

/**
 * Khách quan tâm — người dân để lại liên hệ qua khung chat nhúng trên website
 * HDS (kế hoạch ngày 4–5: "biểu mẫu thu thông tin khách quan tâm").
 * Ban quản trị đánh dấu Đã liên hệ / Bỏ qua kèm ghi chú.
 */
const STATUS_CLS: Record<string, string> = {
  moi: 'bg-amber-100 text-amber-900 dark:bg-amber-950/50 dark:text-amber-300',
  da_lien_he: 'bg-emerald-100 text-emerald-900 dark:bg-emerald-950/50 dark:text-emerald-300',
  bo_qua: 'bg-slate-200 text-slate-600 dark:bg-slate-800 dark:text-slate-400',
};

export const LeadsTab: React.FC = () => {
  const { showToast } = useApp();
  const [data, setData] = useState<LeadsResponse | null>(null);
  const [filter, setFilter] = useState('');
  const [loading, setLoading] = useState(true);
  const [notes, setNotes] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState<number | null>(null);

  const load = async (status = filter) => {
    setLoading(true);
    try {
      const res = await api.getLeads(status);
      setData(res);
      setNotes(Object.fromEntries((res.items || []).map((l: Lead) => [l.id, l.note || ''])));
    } catch (err: any) {
      showToast(err?.message || 'Không tải được danh sách khách quan tâm.', 'error');
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { void load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [filter]);

  const setStatus = async (lead: Lead, status: string) => {
    setBusy(lead.id);
    try {
      await api.updateLead(lead.id, { status, note: notes[lead.id] ?? lead.note ?? '' });
      showToast(status === 'da_lien_he' ? 'Đã ghi nhận đã liên hệ.' : status === 'bo_qua' ? 'Đã bỏ qua.' : 'Đã chuyển về Mới.', 'success');
      await load();
    } catch (err: any) {
      showToast(err?.message || 'Không cập nhật được.', 'error');
    } finally {
      setBusy(null);
    }
  };

  const counts = data?.counts || {};
  const statuses = data?.statuses || { moi: 'Mới', da_lien_he: 'Đã liên hệ', bo_qua: 'Bỏ qua' };

  return (
    <div className="space-y-4">
      <div className="bg-white dark:bg-slate-900 p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-sm font-bold text-slate-900 dark:text-slate-100 flex items-center gap-2">
              <UserRound className="w-4 h-4 text-hds-gold" /> Khách quan tâm từ website
            </h2>
            <p className="mt-1 text-[11px] text-slate-500 dark:text-slate-400 leading-relaxed max-w-2xl">
              Người dân hỏi qua khung chat nhúng trên website HDS rồi để lại họ tên, số điện thoại / email và nhu cầu.
              Nhúng khung chat bằng một dòng: <code className="font-mono text-[10px] bg-slate-100 dark:bg-slate-800 px-1 rounded">&lt;script src="{window.location.origin}/embed/hds-chat.js" defer&gt;&lt;/script&gt;</code>
              {' '}· Xem thử: <a className="text-hds-navy dark:text-blue-300 underline" href="/embed/chat.html" target="_blank" rel="noreferrer">/embed/chat.html</a>
            </p>
          </div>
          <button type="button" onClick={() => load()} disabled={loading} className="p-2 rounded-lg text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800" title="Làm mới">
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {[['', 'Tất cả'], ...Object.entries(statuses)].map(([k, label]) => (
            <button
              key={k}
              type="button"
              onClick={() => setFilter(k)}
              className={`px-3 py-1.5 rounded-lg text-[11px] font-bold border ${
                filter === k ? 'bg-hds-navy text-hds-gold border-hds-navy' : 'border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800'
              }`}
            >
              {label}{k ? ` (${counts[k] ?? 0})` : ''}
            </button>
          ))}
        </div>
      </div>

      {loading && !data ? (
        <div className="py-12 text-center text-slate-400"><Loader2 className="w-5 h-5 animate-spin mx-auto" /></div>
      ) : !data?.items?.length ? (
        <div className="bg-white dark:bg-slate-900 p-10 rounded-2xl border border-dashed border-slate-300 dark:border-slate-700 text-center text-xs text-slate-500">
          Chưa có khách nào để lại liên hệ{filter ? ' ở trạng thái này' : ''}.
        </div>
      ) : (
        <div className="space-y-2">
          {data.items.map((lead) => (
            <div key={lead.id} className="bg-white dark:bg-slate-900 p-4 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-bold text-sm text-slate-900 dark:text-slate-100">{lead.name}</span>
                    <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${STATUS_CLS[lead.status] || STATUS_CLS.moi}`}>{statuses[lead.status] || lead.status}</span>
                    <span className="text-[10px] text-slate-400">{String(lead.created_at).slice(0, 16).replace('T', ' ')}</span>
                  </div>
                  <div className="mt-1 flex flex-wrap gap-3 text-xs text-slate-700 dark:text-slate-300">
                    {lead.phone && <a href={`tel:${lead.phone}`} className="inline-flex items-center gap-1 hover:underline"><Phone className="w-3 h-3" />{lead.phone}</a>}
                    {lead.email && <a href={`mailto:${lead.email}`} className="inline-flex items-center gap-1 hover:underline"><Mail className="w-3 h-3" />{lead.email}</a>}
                  </div>
                  {lead.need && <p className="mt-2 text-xs text-slate-600 dark:text-slate-300 leading-relaxed whitespace-pre-wrap">{lead.need}</p>}
                  {lead.handled_at && (
                    <p className="mt-1 text-[10px] text-slate-400">
                      Xử lý: {lead.handled_by_name || '—'} · {String(lead.handled_at).slice(0, 16).replace('T', ' ')}
                    </p>
                  )}
                </div>
                <div className="w-full sm:w-72 space-y-2">
                  <input
                    value={notes[lead.id] ?? ''}
                    onChange={(e) => setNotes((prev) => ({ ...prev, [lead.id]: e.target.value }))}
                    placeholder="Ghi chú (đã gọi, hẹn gặp…)"
                    className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 dark:bg-slate-800 text-xs"
                  />
                  <div className="flex flex-wrap gap-1.5">
                    {lead.status !== 'da_lien_he' && (
                      <button type="button" disabled={busy === lead.id} onClick={() => setStatus(lead, 'da_lien_he')} className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-emerald-600 text-white text-[11px] font-bold disabled:opacity-50">
                        <CheckCircle2 className="w-3.5 h-3.5" /> Đã liên hệ
                      </button>
                    )}
                    {lead.status !== 'bo_qua' && (
                      <button type="button" disabled={busy === lead.id} onClick={() => setStatus(lead, 'bo_qua')} className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg border border-slate-300 dark:border-slate-700 text-slate-600 dark:text-slate-300 text-[11px] font-bold disabled:opacity-50">
                        <XCircle className="w-3.5 h-3.5" /> Bỏ qua
                      </button>
                    )}
                    {lead.status !== 'moi' && (
                      <button type="button" disabled={busy === lead.id} onClick={() => setStatus(lead, 'moi')} className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg text-slate-500 text-[11px] font-semibold hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-50">
                        <Undo2 className="w-3.5 h-3.5" /> Về Mới
                      </button>
                    )}
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
