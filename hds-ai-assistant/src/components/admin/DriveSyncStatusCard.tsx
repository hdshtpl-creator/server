import React, { useEffect, useState } from 'react';
import { useApp } from '../../context/AppContext';
import * as api from '../../api';
import type { DriveSyncStatus } from '../../types';
import {
  RefreshCw,
  CloudOff,
  Clock,
  FilePlus2,
  FileClock,
  FileCheck2,
  FileWarning,
  AlertTriangle,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';

function timeAgo(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const min = Math.floor(diffMs / 60000);
  if (min < 1) return 'vừa xong';
  if (min < 60) return `${min} phút trước`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr} giờ trước`;
  return `${Math.floor(hr / 24)} ngày trước`;
}

const CountBadge: React.FC<{
  label: string;
  value: number;
  tone: string;
  icon: React.ComponentType<{ className?: string }>;
}> = ({ label, value, tone, icon: Icon }) => (
  <div className="flex items-center gap-2 bg-slate-50 dark:bg-slate-800/60 rounded-xl px-3 py-2 border border-slate-200 dark:border-slate-700">
    <span className={`p-1.5 rounded-lg ${tone}`}>
      <Icon className="w-3.5 h-3.5" />
    </span>
    <div>
      <div className="text-sm font-black text-slate-900 dark:text-slate-100 leading-none">
        {value}
      </div>
      <div className="text-[10px] text-slate-500 dark:text-slate-400 mt-0.5">{label}</div>
    </div>
  </div>
);

export const DriveSyncStatusCard: React.FC = () => {
  const { showToast } = useApp();
  const [status, setStatus] = useState<DriveSyncStatus | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [showSkipped, setShowSkipped] = useState(false);
  const [showFailures, setShowFailures] = useState(false);

  const load = async () => {
    setIsLoading(true);
    try {
      setStatus(await api.getDriveSyncStatus());
    } catch (err: any) {
      showToast(err?.message || 'Không tải được trạng thái đồng bộ Drive.', 'error');
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
        Đang tải trạng thái đồng bộ Google Drive…
      </div>
    );
  }

  if (!status?.configured) {
    return (
      <div className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 p-4 shadow-sm flex items-start gap-3 text-xs">
        <CloudOff className="w-5 h-5 text-slate-400 shrink-0 mt-0.5" />
        <div>
          <p className="font-bold text-slate-700 dark:text-slate-200">
            Chưa kết nối Google Drive
          </p>
          <p className="text-slate-500 dark:text-slate-400 mt-0.5">
            Đặt <code className="font-mono">DRIVE_FOLDER_ID</code> trong <code className="font-mono">.env</code> trên máy chủ. Xem{' '}
            <code className="font-mono">deploy/TRAIN_DRIVE.md</code>.
          </p>
        </div>
      </div>
    );
  }

  const run = status.last_run;
  const failures = status.failures ?? [];

  return (
    <div className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 p-4 shadow-sm space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="font-bold text-sm text-slate-900 dark:text-slate-100">
            Đồng bộ Google Drive
          </h3>
          <p className="text-[11px] text-slate-500 dark:text-slate-400 flex items-center gap-1 mt-0.5">
            <Clock className="w-3 h-3" />
            {run?.finished_at
              ? `Quét lần cuối: ${timeAgo(run.finished_at)} (${new Date(run.finished_at).toLocaleString('vi-VN')})`
              : 'Chưa quét lần nào — bot tự chạy mỗi 15 phút, hoặc chạy tay: bash deploy/auto-learn.sh'}
          </p>
        </div>
        <button
          onClick={load}
          className="flex items-center gap-1.5 px-2.5 py-1.5 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 font-semibold text-[11px] rounded-lg transition-colors"
        >
          <RefreshCw className="w-3 h-3" />
          Tải lại
        </button>
      </div>

      {run && (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            <CountBadge
              label="Mới học"
              value={run.counts.new}
              icon={FilePlus2}
              tone="bg-emerald-50 dark:bg-emerald-950 text-hds-green dark:text-emerald-400"
            />
            <CountBadge
              label="Cập nhật"
              value={run.counts.updated}
              icon={FileCheck2}
              tone="bg-blue-50 dark:bg-blue-950 text-hds-blue dark:text-blue-400"
            />
            <CountBadge
              label="Không đổi"
              value={run.counts.unchanged}
              icon={FileCheck2}
              tone="bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400"
            />
            <CountBadge
              label="Chưa học được"
              value={run.counts.unmapped + run.counts.errors}
              icon={FileClock}
              tone="bg-amber-50 dark:bg-amber-950 text-amber-600 dark:text-amber-400"
            />
          </div>

          {run.skipped_items.length > 0 && (
            <div className="pt-1">
              <button
                onClick={() => setShowSkipped((v) => !v)}
                className="flex items-center justify-between w-full text-[11px] font-semibold bg-amber-50 dark:bg-amber-950/40 hover:bg-amber-100 dark:hover:bg-amber-950/60 text-amber-900 dark:text-amber-200 px-3 py-2 rounded-lg border border-amber-200 dark:border-amber-900 transition-colors"
              >
                <span className="flex items-center gap-1.5">
                  <AlertTriangle className="w-3.5 h-3.5" />
                  {run.skipped_items.length} tệp trong Drive chưa xác định được nhãn — cần sửa để bot học
                </span>
                {showSkipped ? (
                  <ChevronUp className="w-3.5 h-3.5" />
                ) : (
                  <ChevronDown className="w-3.5 h-3.5" />
                )}
              </button>

              {showSkipped && (
                <ul className="mt-2 space-y-1.5">
                  {run.skipped_items.map((it, idx) => (
                    <li
                      key={idx}
                      className="text-[11px] bg-slate-50 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700 rounded-lg p-2.5"
                    >
                      <div className="font-semibold text-slate-800 dark:text-slate-100 break-words">
                        {it.name}
                      </div>
                      <div className="text-slate-400 dark:text-slate-500 font-mono text-[10px] mt-0.5">
                        {it.location}
                      </div>
                      <div className="text-amber-700 dark:text-amber-300 mt-1 leading-relaxed">
                        {it.reason}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {run.counts.unmapped === 0 && run.counts.errors === 0 && run.counts.new === 0 && run.counts.updated === 0 && (
            <p className="text-[11px] text-slate-400 dark:text-slate-500">
              Không có gì mới kể từ lần quét trước.
            </p>
          )}
        </>
      )}

      {/* Tài liệu KHÔNG ĐỌC ĐƯỢC — nằm ngoài khối `run` vì đây là lỗi tích luỹ
          qua mọi lần quét, không phải ảnh chụp lần quét cuối. File hỏng từ lần
          trước sẽ không xuất hiện trong `run` (nội dung không đổi nên không
          được học lại), nhưng vẫn đang thiếu trong kho và phải hiện ở đây. */}
      {failures.length > 0 && (
        <div className="pt-3 mt-3 border-t border-slate-200 dark:border-slate-700">
          <button
            onClick={() => setShowFailures((v) => !v)}
            className="flex items-center justify-between w-full text-[11px] font-semibold bg-red-50 dark:bg-red-950/40 hover:bg-red-100 dark:hover:bg-red-950/60 text-red-900 dark:text-red-200 px-3 py-2 rounded-lg border border-red-200 dark:border-red-900 transition-colors"
          >
            <span className="flex items-center gap-1.5 text-left">
              <FileWarning className="w-3.5 h-3.5 shrink-0" />
              {failures.length} tài liệu có trong Drive nhưng bot chưa đọc được — đang thiếu trong kho
            </span>
            {showFailures ? (
              <ChevronUp className="w-3.5 h-3.5 shrink-0" />
            ) : (
              <ChevronDown className="w-3.5 h-3.5 shrink-0" />
            )}
          </button>

          {showFailures && (
            <ul className="mt-2 space-y-1.5">
              {failures.map((it) => (
                <li
                  key={it.id}
                  className="text-[11px] bg-slate-50 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700 rounded-lg p-2.5"
                >
                  <div className="font-semibold text-slate-800 dark:text-slate-100 break-words">
                    {it.file_name}
                  </div>
                  {it.location && (
                    <div className="text-slate-400 dark:text-slate-500 font-mono text-[10px] mt-0.5 break-words">
                      {it.location}
                    </div>
                  )}
                  <div className="text-red-700 dark:text-red-300 mt-1 leading-relaxed">
                    {it.error_message || it.error_code}
                  </div>
                  {it.hint && (
                    <div className="text-emerald-700 dark:text-emerald-300 mt-1 leading-relaxed">
                      Cách sửa: {it.hint}
                    </div>
                  )}
                  <div className="text-slate-400 dark:text-slate-500 text-[10px] mt-1">
                    Đã thử {it.attempts} lần · lần đầu {it.first_seen_at.slice(0, 10)}
                    {' · '}mã lỗi <span className="font-mono">{it.error_code}</span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
};
