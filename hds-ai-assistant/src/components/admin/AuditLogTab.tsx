import React, { useEffect, useState } from 'react';
import { useApp } from '../../context/AppContext';
import * as api from '../../api';
import type { AuditEntry } from '../../types';
import { ScrollText, RefreshCw, Loader2, ChevronLeft, ChevronRight, Search } from 'lucide-react';

/**
 * Nhật ký hệ thống — bảng audit_log xem trên web (kế hoạch ngày 3: "nhật ký
 * ghi lại toàn bộ thao tác và không thể xoá"). Chỉ đọc: bảng có trigger CSDL
 * chặn UPDATE/DELETE, giao diện không có nút sửa/xoá nào.
 */
const PAGE = 100;

export const AuditLogTab: React.FC = () => {
  const { showToast } = useApp();
  const [items, setItems] = useState<AuditEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [action, setAction] = useState('');
  const [q, setQ] = useState('');
  const [qDraft, setQDraft] = useState('');
  const [actions, setActions] = useState<Array<{ action: string; count: number; label: string }>>([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState<number | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      const res = await api.getAuditLog({ limit: PAGE, offset, action, q });
      setItems(res.items || []);
      setTotal(res.total || 0);
    } catch (err: any) {
      showToast(err?.message || 'Không tải được nhật ký.', 'error');
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { void load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [offset, action, q]);
  useEffect(() => {
    api.getAuditActions().then(setActions).catch(() => setActions([]));
  }, []);

  return (
    <div className="space-y-4">
      <div className="bg-white dark:bg-slate-900 p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-sm font-bold text-slate-900 dark:text-slate-100 flex items-center gap-2">
              <ScrollText className="w-4 h-4 text-hds-gold" /> Nhật ký hệ thống
            </h2>
            <p className="mt-1 text-[11px] text-slate-500 dark:text-slate-400">
              {total.toLocaleString('vi-VN')} bản ghi · ai làm gì, lúc nào. Bảng chỉ ghi thêm — không sửa, không xoá được, kể cả admin.
            </p>
          </div>
          <button type="button" onClick={() => load()} disabled={loading} className="p-2 rounded-lg text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800" title="Làm mới">
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
        <form
          className="mt-3 flex flex-wrap gap-2"
          onSubmit={(e) => { e.preventDefault(); setOffset(0); setQ(qDraft.trim()); }}
        >
          <select
            value={action}
            onChange={(e) => { setOffset(0); setAction(e.target.value); }}
            className="px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 dark:bg-slate-800 text-xs"
          >
            <option value="">Mọi thao tác</option>
            {actions.map((a) => (
              <option key={a.action} value={a.action}>{a.label} ({a.count.toLocaleString('vi-VN')})</option>
            ))}
          </select>
          <div className="flex items-center gap-2 px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 dark:bg-slate-800 flex-1 min-w-[200px]">
            <Search className="w-3.5 h-3.5 text-slate-400" />
            <input value={qDraft} onChange={(e) => setQDraft(e.target.value)} placeholder="Tìm trong chi tiết (tên file, câu hỏi, số hiệu…)" className="flex-1 bg-transparent text-xs outline-none" />
          </div>
          <button type="submit" className="px-3 py-2 rounded-lg bg-hds-navy text-hds-gold text-xs font-bold">Lọc</button>
        </form>
      </div>

      <div className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm overflow-hidden">
        {loading && !items.length ? (
          <div className="py-12 text-center text-slate-400"><Loader2 className="w-5 h-5 animate-spin mx-auto" /></div>
        ) : !items.length ? (
          <p className="p-8 text-center text-xs text-slate-500">Không có bản ghi nào khớp.</p>
        ) : (
          <table className="w-full text-xs">
            <thead className="bg-slate-50 dark:bg-slate-800 text-[10px] uppercase text-slate-500">
              <tr>
                <th className="text-left px-3 py-2 w-36">Thời điểm</th>
                <th className="text-left px-3 py-2 w-44">Người</th>
                <th className="text-left px-3 py-2">Thao tác</th>
              </tr>
            </thead>
            <tbody>
              {items.map((row) => (
                <React.Fragment key={row.id}>
                  <tr
                    className="border-t border-slate-100 dark:border-slate-800 hover:bg-slate-50 dark:hover:bg-slate-800/60 cursor-pointer"
                    onClick={() => setOpen(open === row.id ? null : row.id)}
                  >
                    <td className="px-3 py-2 font-mono text-[10px] text-slate-500 whitespace-nowrap">{String(row.created_at).slice(0, 19).replace('T', ' ')}</td>
                    <td className="px-3 py-2 text-slate-700 dark:text-slate-300">
                      {row.user_name || (row.user_id == null ? 'Hệ thống' : `#${row.user_id}`)}
                      {row.user_email && <span className="block text-[10px] text-slate-400">{row.user_email}</span>}
                    </td>
                    <td className="px-3 py-2 text-slate-800 dark:text-slate-100 break-words">{row.tom_tat}</td>
                  </tr>
                  {open === row.id && (
                    <tr className="bg-slate-50 dark:bg-slate-900/70">
                      <td colSpan={3} className="px-3 py-2">
                        <pre className="text-[10px] whitespace-pre-wrap break-words text-slate-600 dark:text-slate-300 font-mono">
                          #{row.id} · {row.action}{row.entity ? ` · ${row.entity}#${row.entity_id ?? ''}` : ''}{'\n'}
                          {JSON.stringify(row.detail || {}, null, 2)}
                        </pre>
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              ))}
            </tbody>
          </table>
        )}
        <div className="flex items-center justify-between px-3 py-2 border-t border-slate-100 dark:border-slate-800 text-[11px] text-slate-500">
          <span>{offset + 1}–{Math.min(offset + PAGE, total)} / {total.toLocaleString('vi-VN')}</span>
          <div className="flex gap-1">
            <button type="button" disabled={offset === 0 || loading} onClick={() => setOffset(Math.max(0, offset - PAGE))} className="p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-40"><ChevronLeft className="w-4 h-4" /></button>
            <button type="button" disabled={offset + PAGE >= total || loading} onClick={() => setOffset(offset + PAGE)} className="p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-40"><ChevronRight className="w-4 h-4" /></button>
          </div>
        </div>
      </div>
    </div>
  );
};
