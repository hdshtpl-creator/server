import React, { useEffect, useRef, useState } from 'react';
import { useApp } from '../../context/AppContext';
import * as api from '../../api';
import type { DriveSyncStatus } from '../../types';
import {
  RefreshCw,
  ScanSearch,
  CloudOff,
  Clock,
  FilePlus2,
  FileClock,
  FileCheck2,
  FileWarning,
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  FolderInput,
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
  const [showMissing, setShowMissing] = useState(false);
  const [dangBamQuet, setDangBamQuet] = useState(false);
  const daChayRef = useRef(false);

  const load = async (silent = false) => {
    if (!silent) setIsLoading(true);
    try {
      setStatus(await api.getDriveSyncStatus());
    } catch (err: any) {
      if (!silent) showToast(err?.message || 'Không tải được trạng thái đồng bộ Drive.', 'error');
    } finally {
      if (!silent) setIsLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Bộ quét chạy nền trên máy chủ (POST /kho/quet): trong lúc chạy, thăm dò
  // trạng thái mỗi 10 giây; lúc xong thì báo và số liệu bên dưới đã là của
  // lượt vừa rồi.
  const quet = status?.quet ?? null;
  const dangChay = Boolean(quet?.dang_chay);
  useEffect(() => {
    if (!dangChay) return;
    const id = window.setInterval(() => load(true), 10000);
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dangChay]);
  useEffect(() => {
    if (daChayRef.current && !dangChay) {
      const kt = quet?.ket_thuc;
      if (kt && kt.ma_thoat !== 0) showToast('Lượt quét dừng với lỗi — xem dòng cuối nhật ký trong thẻ.', 'error');
      else showToast('Quét kho xong.', 'success');
    }
    daChayRef.current = dangChay;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dangChay]);

  const quetLai = async () => {
    setDangBamQuet(true);
    try {
      await api.quetKho();
      showToast('Đã khởi động lượt quét kho — theo dõi ngay tại đây.', 'info');
      await load(true);
    } catch (err: any) {
      showToast(err?.message || 'Không khởi động được lượt quét.', 'error');
    } finally {
      setDangBamQuet(false);
    }
  };

  const nutQuet = dangChay ? (
    <span className="flex items-center gap-1.5 px-2.5 py-1.5 bg-blue-50 dark:bg-blue-950 text-hds-blue dark:text-blue-300 font-semibold text-[11px] rounded-lg border border-blue-200 dark:border-blue-900">
      <RefreshCw className="w-3 h-3 animate-spin" />
      Đang quét
      {quet?.started_at
        ? ` từ ${new Date(quet.started_at).toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })}`
        : quet?.nguon === 'ngoai'
          ? ' (khởi động từ máy chủ)'
          : ''}
      …
    </span>
  ) : (
    <button
      onClick={quetLai}
      disabled={dangBamQuet}
      title="Quét cả kho trên máy chủ ngay: học file mới thả vào, nhận file đổi/đổi tên, báo file mất"
      className="flex items-center gap-1.5 px-3 py-1.5 bg-hds-navy hover:bg-hds-navy-light text-white font-bold text-[11px] rounded-lg transition-colors disabled:opacity-60"
    >
      {dangBamQuet ? <RefreshCw className="w-3 h-3 animate-spin" /> : <ScanSearch className="w-3 h-3" />}
      Quét lại
    </button>
  );

  if (isLoading) {
    return (
      <div className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 p-4 shadow-sm flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
        <RefreshCw className="w-4 h-4 animate-spin text-hds-navy dark:text-blue-400" />
        Đang tải trạng thái quét kho tài liệu…
      </div>
    );
  }

  // Từ 27/08/2026 nguồn mặc định là thư mục trên máy chủ; máy chủ cũ còn khai
  // DRIVE_FOLDER_ID thì backend trả source='drive' và thẻ này đổi chữ theo.
  const isDrive = status?.source === 'drive';

  if (!status?.configured) {
    return (
      <div className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 p-4 shadow-sm flex items-start justify-between gap-3 text-xs">
        <div className="flex items-start gap-3">
          <CloudOff className="w-5 h-5 text-slate-400 shrink-0 mt-0.5" />
          <div>
            <p className="font-bold text-slate-700 dark:text-slate-200">
              Chưa quét kho tài liệu lần nào
            </p>
            <p className="text-slate-500 dark:text-slate-400 mt-0.5">
              Bấm <b>Quét lại</b> để bot đọc thư mục kho trên máy chủ, hoặc bật lịch 15 phút bằng{' '}
              <code className="font-mono">sudo bash deploy/hoc-tu-thu-muc.sh --install-timer</code>.
            </p>
          </div>
        </div>
        {nutQuet}
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
            {isDrive ? 'Đồng bộ Google Drive' : 'Quét kho tài liệu trên máy chủ'}
          </h3>
          {!isDrive && status?.library_root && (
            <p className="text-[11px] text-slate-500 dark:text-slate-400 font-mono truncate">
              {status.library_root}
            </p>
          )}
          <p className="text-[11px] text-slate-500 dark:text-slate-400 flex items-center gap-1 mt-0.5">
            <Clock className="w-3 h-3" />
            {run?.finished_at
              ? `Quét lần cuối: ${timeAgo(run.finished_at)} (${new Date(run.finished_at).toLocaleString('vi-VN')})`
              : 'Chưa quét lần nào — bấm Quét lại.'}
          </p>
        </div>
        {nutQuet}
      </div>

      {/* Đuôi nhật ký lúc đang quét — thấy bộ quét đang ở file nào, không phải
          nhìn vòng xoay mù mờ suốt 10 phút. */}
      {dangChay && (quet?.log_tail?.length ?? 0) > 0 && (
        <pre className="text-[10px] font-mono text-slate-600 dark:text-slate-300 bg-slate-50 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700 rounded-lg p-2 overflow-x-auto whitespace-pre-wrap max-h-24">
          {quet!.log_tail!.slice(-3).join('\n')}
        </pre>
      )}
      {!dangChay && quet?.ket_thuc && quet.ket_thuc.ma_thoat !== 0 && (
        <div className="text-[11px] bg-red-50 dark:bg-red-950/40 text-red-900 dark:text-red-200 border border-red-200 dark:border-red-900 rounded-lg px-3 py-2">
          <p className="font-semibold">
            Lượt quét vừa rồi dừng với lỗi (mã {quet.ket_thuc.ma_thoat}) — chưa ghi kết quả, số liệu bên dưới là của lượt trước.
          </p>
          {quet.ket_thuc.log_tail.length > 0 && (
            <pre className="mt-1 text-[10px] font-mono whitespace-pre-wrap overflow-x-auto">
              {quet.ket_thuc.log_tail.slice(-4).join('\n')}
            </pre>
          )}
        </div>
      )}

      {run && (() => {
        // Hai con số CHÍNH XÁC cho phần "chưa học được" — lấy từ counts.
        const bqDinhDang = run.counts.bad_format ?? 0;
        const bqNhan = run.counts.unmapped ?? 0;
        return (
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
            {/* Phải cộng cả bad_format: thiếu nó thì một thư mục toàn .xlsx
                hiện "0 chưa học được" trong khi chẳng file nào vào kho. */}
            <CountBadge
              label="Chưa học được"
              value={run.counts.unmapped + run.counts.errors + (run.counts.bad_format ?? 0)}
              icon={FileClock}
              tone="bg-amber-50 dark:bg-amber-950 text-amber-600 dark:text-amber-400"
            />
          </div>

          {/* Đổi tên / chuyển thư mục: bot giữ nguyên bản ghi cũ (không học lại,
              không mất trạng thái duyệt). Chỉ hiện khi thực sự có. */}
          {(run.counts.moved ?? 0) > 0 && (
            <p className="flex items-center gap-1.5 text-[11px] text-slate-600 dark:text-slate-300 bg-slate-50 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700 rounded-lg px-3 py-2">
              <FolderInput className="w-3.5 h-3.5 shrink-0 text-hds-blue" />
              <span>
                <b>{run.counts.moved}</b> tệp đổi tên hoặc chuyển thư mục — bot nhận ra là cùng
                một file, giữ nguyên bản ghi cũ và trạng thái duyệt.
              </span>
            </p>
          )}

          {/* Hai lý do bỏ qua khác hẳn nhau, cách xử lý cũng khác: sai định dạng
              thì phải đổi file sang .docx/.pdf; chưa xác định được nhãn thì chỉ
              cần chuyển file vào đúng ngăn thư mục. Gộp một cục là người quản
              trị đọc xong không biết phải làm gì. */}
          {run.skipped_items.length > 0 && (
            <div className="pt-1">
              <button
                onClick={() => setShowSkipped((v) => !v)}
                className="flex items-center justify-between w-full text-[11px] font-semibold bg-amber-50 dark:bg-amber-950/40 hover:bg-amber-100 dark:hover:bg-amber-950/60 text-amber-900 dark:text-amber-200 px-3 py-2 rounded-lg border border-amber-200 dark:border-amber-900 transition-colors"
              >
                <span className="flex items-center gap-1.5 text-left">
                  <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
                  <span>
                    {/* Đếm theo COUNTS chứ không theo skipped_items: máy chủ chỉ
                        lưu 30 dòng chi tiết cuối cùng (MAX_STATUS_ITEMS), đếm
                        trên danh sách đó thì 400 file bỏ qua vẫn hiện "30". */}
                    {bqNhan + bqDinhDang} tệp trong {isDrive ? 'Drive' : 'kho'} bot chưa học được
                    {(() => {
                      const parts: string[] = [];
                      if (bqNhan) parts.push(`${bqNhan} chưa xác định được nhãn`);
                      if (bqDinhDang) parts.push(`${bqDinhDang} sai định dạng`);
                      return parts.length ? ` (${parts.join(', ')})` : '';
                    })()}
                  </span>
                </span>
                {showSkipped ? (
                  <ChevronUp className="w-3.5 h-3.5" />
                ) : (
                  <ChevronDown className="w-3.5 h-3.5" />
                )}
              </button>

              {showSkipped && (
                <ul className="mt-2 space-y-1.5">
                  {bqNhan + bqDinhDang > run.skipped_items.length && (
                    <li className="text-[10px] text-slate-400 dark:text-slate-500 px-1">
                      Chỉ liệt kê {run.skipped_items.length} tệp gần nhất — xem đủ trong nhật ký
                      lần quét trên máy chủ.
                    </li>
                  )}
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
                        <span className="inline-block mr-1.5 px-1.5 py-px rounded bg-amber-100 dark:bg-amber-950 border border-amber-300 dark:border-amber-800 text-[10px] font-bold">
                          {it.code === 'unsupported_format' ? 'Sai định dạng' : 'Chưa có nhãn'}
                        </span>
                        {it.reason}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {/* Tài liệu ĐANG PHỤC VỤ vừa rơi lại hàng chờ duyệt. Phải nổi bật:
              đây là lúc bot lặng lẽ mất một tài liệu người dùng vẫn tưởng có. */}
          {(run.unapproved_items?.length ?? 0) > 0 && (
            <div className="pt-1">
              <div className="flex items-start gap-2 text-[11px] bg-orange-50 dark:bg-orange-950/40 text-orange-900 dark:text-orange-200 px-3 py-2 rounded-lg border border-orange-200 dark:border-orange-900">
                <FileWarning className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                <div>
                  <p className="font-semibold">
                    {run.unapproved_items!.length} tài liệu đang phục vụ vừa rơi lại hàng chờ duyệt
                  </p>
                  <p className="mt-0.5 leading-relaxed">
                    Bot KHÔNG dùng các tài liệu này cho tới khi duyệt lại — mở{' '}
                    <b>Duyệt nhãn tài liệu</b>.
                  </p>
                  <ul className="mt-1 space-y-0.5">
                    {run.unapproved_items!.slice(0, 8).map((it, idx) => (
                      <li key={idx} className="font-mono text-[10px] opacity-80 break-words">
                        {it.name} — {it.reason}
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </div>
          )}

          {/* Tài liệu còn trong kho tri thức nhưng tệp đã biến mất khỏi thư mục.
              Đây là "cần quyết định", không phải lỗi — tông xanh xám, không đỏ. */}
          {(run.missing_items?.length ?? 0) > 0 && (
            <div className="pt-1">
              <button
                onClick={() => setShowMissing((v) => !v)}
                className="flex items-center justify-between w-full text-[11px] font-semibold bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 px-3 py-2 rounded-lg border border-slate-300 dark:border-slate-600 transition-colors"
              >
                <span className="flex items-center gap-1.5">
                  <FileClock className="w-3.5 h-3.5" />
                  {run.missing_items!.length} tài liệu còn trong kho tri thức nhưng KHÔNG còn tệp trong{' '}
                  {isDrive ? 'Drive' : 'thư mục'}
                </span>
                {showMissing ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
              </button>

              {showMissing && (
                <>
                  <p className="text-[11px] text-slate-500 dark:text-slate-400 mt-2 leading-relaxed">
                    Bot vẫn trả lời bằng nội dung đã học. Muốn bot dùng lại bản mới nhất thì đưa tệp
                    trở lại đúng thư mục; muốn gỡ hẳn khỏi kho thì nhờ IT (xem{' '}
                    <code className="font-mono">deploy/CHUYEN_VE_LOCAL.md</code>).
                  </p>
                  <ul className="mt-2 space-y-1.5">
                    {run.missing_items!.map((it, idx) => (
                      <li
                        key={idx}
                        className="text-[11px] bg-slate-50 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700 rounded-lg p-2.5"
                      >
                        <div className="font-semibold text-slate-800 dark:text-slate-100 break-words">
                          {it.document_id != null && (
                            <span className="text-slate-400 dark:text-slate-500 mr-1">#{it.document_id}</span>
                          )}
                          {it.name}
                        </div>
                        <div className="text-slate-400 dark:text-slate-500 font-mono text-[10px] mt-0.5 break-all">
                          {it.location}
                        </div>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </div>
          )}

          {run.counts.unmapped === 0 && run.counts.errors === 0 && run.counts.new === 0 &&
            run.counts.updated === 0 && (run.counts.moved ?? 0) === 0 &&
            (run.counts.bad_format ?? 0) === 0 &&
            (run.missing_items?.length ?? 0) === 0 && (
            <p className="text-[11px] text-slate-400 dark:text-slate-500">
              Không có gì mới kể từ lần quét trước.
            </p>
          )}
        </>
        );
      })()}

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
              {failures.length} tài liệu có trong {isDrive ? 'Drive' : 'thư mục'} nhưng bot chưa đọc được — đang thiếu trong kho
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
