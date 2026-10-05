import React, { useEffect, useState } from 'react';
import * as api from '../../api';
import { useApp } from '../../context/AppContext';
import type { LichChay } from '../../types';
import { AlarmClock, AlertTriangle, Loader2, RefreshCw, Wrench } from 'lucide-react';

/**
 * Lịch chạy tự động (01/10/2026): bật/tắt từng việc định kỳ của máy chủ
 * (quét kho, sao lưu, tự duyệt…) mà không cần IT SSH vào. Máy chủ chỉ thêm /
 * bỏ tiền tố tắt ở đúng dòng lịch — không sửa lệnh hay giờ chạy.
 */

function fmtLuc(iso?: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString('vi-VN', { hour12: false, day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
}

const CHIP: Record<LichChay['trang_thai'], { text: string; cls: string }> = {
  bat: { text: 'Đang bật', cls: 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-300 dark:border-emerald-900' },
  tat: { text: 'Đã tắt', cls: 'bg-slate-100 text-slate-600 border-slate-300 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-700' },
  chua_cai: { text: 'Chưa có trên máy chủ', cls: 'bg-amber-50 text-amber-800 border-amber-300 dark:bg-amber-950/40 dark:text-amber-300 dark:border-amber-800' },
};

export const LichChayCard: React.FC = () => {
  const { showToast } = useApp();
  const [ds, setDs] = useState<LichChay[]>([]);
  const [loading, setLoading] = useState(true);
  const [loi, setLoi] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      const r = await api.getLichChay();
      setDs(Array.isArray(r) ? r : []);
      setLoi(null);
    } catch (err: any) {
      setLoi(err?.message || 'Không tải được lịch chạy');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const doi = async (l: LichChay) => {
    const bat = l.trang_thai !== 'bat';
    if (!bat) {
      const hoi = `Tắt "${l.ten}"?\n\n${l.khi_tat || ''}\n\nLượt đang chạy (nếu có) vẫn chạy tới hết; các lượt sau sẽ bỏ cho tới khi bật lại.`;
      if (!window.confirm(hoi)) return;
    }
    setBusy(l.ma);
    try {
      const moi = await api.datLichChay(l.ma, bat);
      setDs((prev) => prev.map((x) => (x.ma === l.ma ? moi : x)));
      showToast(`${bat ? 'Đã bật' : 'Đã tắt'} "${l.ten}".`, 'success');
    } catch (err: any) {
      showToast(err?.message || 'Không đổi được lịch', 'error');
    } finally {
      setBusy(null);
    }
  };

  const cai = async (l: LichChay) => {
    setBusy(l.ma);
    try {
      const moi = await api.caiLichChay(l.ma);
      setDs((prev) => prev.map((x) => (x.ma === l.ma ? moi : x)));
      showToast(`Đã cài lại "${l.ten}".`, 'success');
    } catch (err: any) {
      showToast(err?.message || 'Không cài lại được', 'error');
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 p-5 shadow-sm space-y-4">
      <div className="flex items-start justify-between gap-3 pb-2 border-b border-slate-100 dark:border-slate-800">
        <div>
          <h3 className="font-bold text-sm text-slate-900 dark:text-slate-100 flex items-center gap-2">
            <AlarmClock className="w-4 h-4 text-hds-gold" />
            Lịch chạy tự động
          </h3>
          <p className="text-[11px] text-slate-500 dark:text-slate-400 mt-1 max-w-3xl leading-relaxed">
            Các việc máy chủ tự làm theo giờ. Tắt khi cần tạm dừng — ví dụ tắt <strong>Quét kho tài liệu</strong> trong
            lúc chép lô hồ sơ từ USB, chép xong bật lại. Tắt không dừng lượt đang chạy.
          </p>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold border border-slate-300 dark:border-slate-700 text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-800 shrink-0"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} /> Tải lại
        </button>
      </div>

      {loi && (
        <p className="text-xs text-hds-red dark:text-red-400 flex items-center gap-1.5">
          <AlertTriangle className="w-4 h-4" /> {loi}
        </p>
      )}
      {loading && ds.length === 0 && !loi && (
        <p className="text-xs text-slate-500 flex items-center gap-2">
          <Loader2 className="w-4 h-4 animate-spin" /> Đang đọc lịch trên máy chủ…
        </p>
      )}

      <ul className="divide-y divide-slate-100 dark:divide-slate-800">
        {ds.map((l) => {
          const chip = CHIP[l.trang_thai];
          const dangBat = l.trang_thai === 'bat';
          return (
            <li key={l.ma} className="py-3 flex flex-wrap items-start gap-3">
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold text-slate-900 dark:text-slate-100 flex flex-wrap items-center gap-2">
                  {l.ten}
                  <span className={`px-2 py-0.5 rounded-lg text-[10px] font-semibold border ${chip.cls}`}>{chip.text}</span>
                  {l.dang_chay && (
                    <span className="px-2 py-0.5 rounded-lg text-[10px] font-semibold border bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-950/40 dark:text-blue-300 dark:border-blue-900 inline-flex items-center gap-1">
                      <Loader2 className="w-3 h-3 animate-spin" /> đang chạy
                    </span>
                  )}
                  {l.nguy_hiem && !dangBat && (
                    <span className="text-[10px] font-semibold text-hds-red dark:text-red-400 inline-flex items-center gap-1">
                      <AlertTriangle className="w-3 h-3" /> nên bật lại sớm
                    </span>
                  )}
                </p>
                {l.mo_ta && <p className="text-[11px] text-slate-500 dark:text-slate-400 mt-0.5 leading-snug">{l.mo_ta}</p>}
                <p className="text-[11px] text-slate-500 dark:text-slate-400 mt-1">
                  {l.lich_mo_ta || l.lich || '—'}
                  {dangBat && l.ke_tiep ? ` · lần tới ${fmtLuc(l.ke_tiep)}` : ''}
                  {` · chạy gần nhất ${fmtLuc(l.lan_cuoi)}`}
                </p>
                {l.ket_qua_cuoi && (
                  <p className="text-[10.5px] font-mono text-slate-400 dark:text-slate-500 mt-0.5 break-all">{l.ket_qua_cuoi}</p>
                )}
              </div>
              <div className="shrink-0 flex items-center gap-2 pt-0.5">
                {l.trang_thai === 'chua_cai' ? (
                  l.cai_duoc ? (
                    <button
                      onClick={() => cai(l)}
                      disabled={busy === l.ma}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold bg-hds-navy text-hds-gold hover:opacity-90 disabled:opacity-60"
                    >
                      {busy === l.ma ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Wrench className="w-3.5 h-3.5" />}
                      Cài lại
                    </button>
                  ) : (
                    <span className="text-[11px] text-slate-500">Nhờ IT cài</span>
                  )
                ) : (
                  <button
                    id={`lich-${l.ma}`}
                    role="switch"
                    aria-checked={dangBat}
                    aria-label={`${dangBat ? 'Tắt' : 'Bật'} ${l.ten}`}
                    onClick={() => doi(l)}
                    disabled={busy === l.ma}
                    className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-hds-blue disabled:opacity-60 ${
                      dangBat ? 'bg-emerald-500' : 'bg-slate-300 dark:bg-slate-600'
                    }`}
                  >
                    <span
                      className={`inline-block h-5 w-5 transform rounded-full bg-white shadow transition-transform ${
                        dangBat ? 'translate-x-5' : 'translate-x-0.5'
                      }`}
                    />
                  </button>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
};
