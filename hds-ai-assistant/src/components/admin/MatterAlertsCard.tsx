import React, { useEffect, useState } from 'react';
import { useApp } from '../../context/AppContext';
import * as api from '../../api';
import type { MatterAlert, MatterAlerts } from '../../types';
import { MATTER_STATUS_BADGES } from '../../constants';
import {
  AlarmClock,
  CalendarClock,
  CalendarX2,
  CircleHelp,
  PauseCircle,
  RefreshCw,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Building2,
} from 'lucide-react';

/** Biểu tượng và màu theo loại cảnh báo. Khớp `kind` do backend trả về. */
const KIND_STYLE: Record<
  MatterAlert['kind'],
  { icon: React.ComponentType<{ className?: string }>; row: string; chip: string }
> = {
  qua_han: {
    icon: CalendarX2,
    row: 'border-l-4 border-l-hds-red',
    chip: 'bg-red-100 text-red-800 border-red-300 dark:bg-red-950 dark:text-red-300 dark:border-red-800',
  },
  den_han_gap: {
    icon: AlarmClock,
    row: 'border-l-4 border-l-amber-500',
    chip: 'bg-amber-100 text-amber-900 border-amber-300 dark:bg-amber-950 dark:text-amber-300 dark:border-amber-800',
  },
  den_han_gan: {
    icon: CalendarClock,
    row: 'border-l-4 border-l-blue-400',
    chip: 'bg-blue-100 text-blue-800 border-blue-300 dark:bg-blue-950 dark:text-blue-300 dark:border-blue-800',
  },
  thieu_han: {
    icon: CircleHelp,
    row: 'border-l-4 border-l-slate-300 dark:border-l-slate-600',
    chip: 'bg-slate-100 text-slate-700 border-slate-300 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-700',
  },
  treo_lau: {
    icon: PauseCircle,
    row: 'border-l-4 border-l-slate-300 dark:border-l-slate-600',
    chip: 'bg-slate-100 text-slate-700 border-slate-300 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-700',
  },
};

/** Diễn giải số ngày còn lại thành câu người đọc hiểu ngay. */
function daysText(a: MatterAlert): string {
  if (a.days_left === null) return 'chưa đặt hạn';
  if (a.days_left < 0) return `quá hạn ${Math.abs(a.days_left)} ngày`;
  if (a.days_left === 0) return 'hết hạn hôm nay';
  return `còn ${a.days_left} ngày`;
}

const AlertRow: React.FC<{ alert: MatterAlert }> = ({ alert }) => {
  const style = KIND_STYLE[alert.kind] || KIND_STYLE.thieu_han;
  const Icon = style.icon;
  const status = MATTER_STATUS_BADGES[alert.status];

  return (
    <li
      className={`bg-slate-50 dark:bg-slate-800/60 rounded-lg p-3 flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-3 ${style.row}`}
    >
      <Icon className="w-4 h-4 shrink-0 text-slate-500 dark:text-slate-400" />

      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex flex-wrap items-center gap-1.5">
          {alert.matter_code && (
            <span className="font-mono text-[10px] font-bold bg-white dark:bg-slate-900 text-slate-600 dark:text-slate-300 px-1.5 py-0.5 rounded border border-slate-200 dark:border-slate-700">
              {alert.matter_code}
            </span>
          )}
          <span className="font-semibold text-xs text-slate-900 dark:text-slate-100 break-words">
            {alert.matter_title}
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[11px] text-slate-500 dark:text-slate-400">
          <span className="flex items-center gap-1 min-w-0">
            <Building2 className="w-3 h-3 shrink-0" />
            <span className="truncate">{alert.client_name}</span>
          </span>
          {alert.deadline && <span className="font-mono">hạn {alert.deadline}</span>}
          {status && (
            <span className={`px-1.5 py-0.5 rounded border ${status.badge}`}>{status.label}</span>
          )}
        </div>
      </div>

      <span
        className={`text-[10px] font-bold px-2 py-1 rounded-full border whitespace-nowrap shrink-0 ${style.chip}`}
      >
        {daysText(alert)}
      </span>
    </li>
  );
};

export const MatterAlertsCard: React.FC = () => {
  const { showToast } = useApp();
  const [data, setData] = useState<MatterAlerts | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [showAll, setShowAll] = useState(false);

  const load = async () => {
    setIsLoading(true);
    try {
      setData(await api.getMatterAlerts());
    } catch (err: any) {
      showToast(err?.message || 'Không tải được danh sách cảnh báo vụ việc.', 'error');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (isLoading) {
    return (
      <div className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 p-4 shadow-sm flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
        <RefreshCw className="w-4 h-4 animate-spin text-hds-navy dark:text-blue-400" />
        Đang kiểm tra hạn chót các vụ việc…
      </div>
    );
  }

  if (!data) return null;

  const urgent = data.items.filter((x) => x.severity === 'gap');
  const later = data.items.filter((x) => x.severity !== 'gap');
  const shown = showAll ? data.items : urgent.length > 0 ? urgent : data.items.slice(0, 3);
  const hiddenCount = data.items.length - shown.length;

  return (
    <div className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 p-4 shadow-sm space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="font-bold text-sm text-slate-900 dark:text-slate-100 flex items-center gap-1.5">
            <AlarmClock className="w-4 h-4 text-hds-red" />
            Hạn chót vụ việc
          </h3>
          <p className="text-[11px] text-slate-500 dark:text-slate-400 mt-0.5">
            {data.total === 0
              ? 'Không có vụ nào quá hạn hoặc sắp đến hạn'
              : `${data.urgent} vụ gấp, ${later.length} vụ cần theo dõi — trong phạm vi bạn phụ trách`}
          </p>
        </div>
        <button
          onClick={load}
          className="flex items-center gap-1.5 px-2.5 py-1.5 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 font-semibold text-[11px] rounded-lg transition-colors"
        >
          <RefreshCw className="w-3 h-3" />
          Kiểm tra lại
        </button>
      </div>

      {data.total === 0 ? (
        <div className="flex items-center gap-2 text-xs text-hds-green dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-900 rounded-lg p-3">
          <CheckCircle2 className="w-4 h-4 shrink-0" />
          <span>Mọi vụ việc đang trong hạn. Không có gì cần xử lý gấp.</span>
        </div>
      ) : (
        <>
          <ul className="space-y-2">
            {shown.map((a) => (
              <AlertRow key={a.matter_id} alert={a} />
            ))}
          </ul>

          {hiddenCount > 0 && (
            <button
              onClick={() => setShowAll(true)}
              className="flex items-center justify-center gap-1.5 w-full text-[11px] font-semibold text-hds-navy dark:text-blue-300 hover:bg-slate-50 dark:hover:bg-slate-800 py-2 rounded-lg transition-colors"
            >
              <ChevronDown className="w-3.5 h-3.5" />
              Xem thêm {hiddenCount} vụ cần theo dõi
            </button>
          )}
          {showAll && data.items.length > 3 && (
            <button
              onClick={() => setShowAll(false)}
              className="flex items-center justify-center gap-1.5 w-full text-[11px] font-semibold text-slate-500 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800 py-2 rounded-lg transition-colors"
            >
              <ChevronUp className="w-3.5 h-3.5" />
              Thu gọn
            </button>
          )}
        </>
      )}
    </div>
  );
};
