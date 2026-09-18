import React, { useCallback, useEffect, useRef, useState } from 'react';
import * as api from '../../api';
import { useApp } from '../../context/AppContext';
import type { TienDoHoc } from '../../types';
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Clock,
  FileClock,
  FilePlus2,
  Loader2,
  Pause,
  RefreshCw,
  ScanSearch,
} from 'lucide-react';

/**
 * Thẻ "Đang học tài liệu" trên Tổng quan (18/09/2026, yêu cầu chủ dự án:
 * "đang đẩy tài liệu từ máy tôi và máy cũng đang học, làm thêm thẻ dashboard
 * để theo dõi trên web").
 *
 * Trả lời đúng ba câu của người đang đổ tài liệu vào kho: máy CÓ đang học
 * không, đã học thêm được BAO NHIÊU, còn KẸT gì. Trong lúc bộ quét chạy thì
 * thăm dò 8 giây/lần (và chỉ khi tab đang mở — tab ẩn thì ngừng hỏi máy chủ),
 * lúc nghỉ giãn ra 60 giây.
 */

const CHU_KY_DANG_QUET = 8_000;
const CHU_KY_NGHI = 60_000;

function truoc(iso?: string | null): string {
  if (!iso) return '';
  const phut = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (phut < 1) return 'vừa xong';
  if (phut < 60) return `${phut} phút trước`;
  const gio = Math.floor(phut / 60);
  if (gio < 24) return `${gio} giờ trước`;
  return `${Math.floor(gio / 24)} ngày trước`;
}

function baoLau(iso?: string | null): string {
  if (!iso) return '';
  const phut = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (phut < 1) return 'chưa tới 1 phút';
  if (phut < 60) return `${phut} phút`;
  return `${Math.floor(phut / 60)} giờ ${phut % 60} phút`;
}

const O_SO: React.FC<{
  nhan: string;
  so: number;
  icon: React.ComponentType<{ className?: string }>;
  tone: string;
  nhan_mach?: boolean;
}> = ({ nhan, so, icon: Icon, tone, nhan_mach }) => (
  <div
    className={`flex items-center gap-2 rounded-xl px-3 py-2 border ${
      nhan_mach
        ? 'border-emerald-300 bg-emerald-50/70 dark:border-emerald-800 dark:bg-emerald-950/40'
        : 'border-slate-200 bg-slate-50 dark:border-slate-700 dark:bg-slate-800/60'
    }`}
  >
    <span className={`p-1.5 rounded-lg ${tone}`}>
      <Icon className="w-3.5 h-3.5" />
    </span>
    <div>
      <div className="text-sm font-black leading-none text-slate-900 dark:text-slate-100">{so}</div>
      <div className="mt-0.5 text-[10px] text-slate-500 dark:text-slate-400">{nhan}</div>
    </div>
  </div>
);

export const TienDoHocCard: React.FC<{ onMoKho?: () => void }> = ({ onMoKho }) => {
  const { showToast } = useApp();
  const [data, setData] = useState<TienDoHoc | null>(null);
  const [dangNap, setDangNap] = useState(true);
  const [loi, setLoi] = useState<string | null>(null);
  const [bamQuet, setBamQuet] = useState(false);
  const timer = useRef<number | undefined>(undefined);

  const nap = useCallback(async (im = false) => {
    if (!im) setDangNap(true);
    try {
      const res = await api.getTienDoHoc();
      setData(res);
      setLoi(null);
    } catch (err: any) {
      setLoi(err?.message || 'Không đọc được tiến độ học.');
    } finally {
      setDangNap(false);
    }
  }, []);

  useEffect(() => {
    void nap();
  }, [nap]);

  // Nhịp thăm dò đi theo trạng thái: đang quét thì dày, nghỉ thì thưa. Tab ẩn
  // (người dùng chuyển cửa sổ) thì KHÔNG hỏi — đỡ tải cho máy chủ đang bận học.
  const dangChay = Boolean(data?.quet?.dang_chay);
  useEffect(() => {
    const chu_ky = dangChay ? CHU_KY_DANG_QUET : CHU_KY_NGHI;
    timer.current = window.setInterval(() => {
      if (document.visibilityState === 'visible') void nap(true);
    }, chu_ky);
    return () => window.clearInterval(timer.current);
  }, [dangChay, nap]);

  const quetNgay = async () => {
    if (bamQuet) return;
    setBamQuet(true);
    try {
      await api.quetKho();
      showToast('Đã bật một lượt quét kho — theo dõi ngay tại thẻ này.', 'success');
      await nap(true);
    } catch (err: any) {
      showToast(err?.message || 'Không bật được lượt quét.', 'error');
    } finally {
      setBamQuet(false);
    }
  };

  const nhip = data?.nhip;
  const tong = data?.tong;
  const quet = data?.quet;
  const lanCuoi = data?.lan_cuoi;
  const logTail = (quet?.log_tail || []).slice(-4);

  return (
    <div className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm">
      <div className="p-5 flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 dark:border-slate-800">
        <div>
          <h3 className="text-base font-bold text-slate-900 dark:text-slate-100 flex items-center gap-2">
            <Activity className="w-5 h-5 text-hds-gold" />
            Đang học tài liệu
            {dangChay ? (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                Đang quét
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                <Pause className="w-3 h-3" /> Nghỉ
              </span>
            )}
          </h3>
          <p className="mt-0.5 text-[11px] text-slate-500 dark:text-slate-400">
            {dangChay
              ? `Bộ quét chạy được ${baoLau(quet?.started_at)}${
                  quet?.nguon === 'ngoai' ? ' (khởi động từ máy chủ)' : ''
                }${
                  typeof data?.tu_luc_quet === 'number'
                    ? ` · đã học thêm ${data.tu_luc_quet} tài liệu`
                    : ''
                }`
              : 'Máy tự quét kho theo lịch; bấm “Quét ngay” nếu vừa đổ tài liệu vào và muốn học liền.'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => void nap()}
            className="flex items-center gap-1.5 px-3 py-2 rounded-xl bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 text-xs font-semibold"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${dangNap ? 'animate-spin' : ''}`} /> Làm mới
          </button>
          <button
            type="button"
            onClick={() => void quetNgay()}
            disabled={bamQuet || dangChay}
            className="flex items-center gap-1.5 px-3 py-2 rounded-xl bg-hds-navy text-hds-gold text-xs font-bold disabled:opacity-50"
            title={dangChay ? 'Đang có lượt quét chạy' : 'Quét kho và học file mới ngay'}
          >
            {bamQuet ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <ScanSearch className="w-3.5 h-3.5" />}
            Quét ngay
          </button>
        </div>
      </div>

      <div className="p-5 space-y-3">
        {loi ? (
          <p className="text-xs text-hds-red flex items-center gap-1.5">
            <AlertTriangle className="w-4 h-4" /> {loi}
          </p>
        ) : !data ? (
          <p className="text-xs text-slate-500 flex items-center gap-1.5">
            <Loader2 className="w-4 h-4 animate-spin" /> Đang đọc tiến độ…
          </p>
        ) : (
          <>
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-2">
              <O_SO
                nhan="học 10 phút qua"
                so={nhip?.phut_10 || 0}
                icon={FilePlus2}
                tone="bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300"
                nhan_mach={(nhip?.phut_10 || 0) > 0}
              />
              <O_SO
                nhan="học 1 giờ qua"
                so={nhip?.gio_1 || 0}
                icon={Clock}
                tone="bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-300"
              />
              <O_SO
                nhan="học hôm nay"
                so={nhip?.hom_nay || 0}
                icon={CheckCircle2}
                tone="bg-slate-200 text-slate-700 dark:bg-slate-700 dark:text-slate-200"
              />
              <O_SO
                nhan="chờ duyệt nhãn"
                so={tong?.cho_duyet || 0}
                icon={FileClock}
                tone="bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300"
              />
            </div>

            <p className="text-[11px] text-slate-500 dark:text-slate-400">
              Kho tri thức đang có <b>{tong?.tai_lieu || 0}</b> tài liệu
              {(nhip?.cap_nhat_gio_1 || 0) > 0 && (
                <> · {nhip?.cap_nhat_gio_1} tài liệu được cập nhật lại trong 1 giờ qua</>
              )}
              .
            </p>

            {dangChay && logTail.length > 0 && (
              <div className="rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-950/90 p-3 overflow-x-auto">
                <p className="text-[10px] font-semibold text-slate-400 mb-1">
                  Bộ quét đang làm gì (nhật ký máy chủ)
                </p>
                <pre className="text-[10px] leading-relaxed text-emerald-300 whitespace-pre-wrap break-words">
                  {logTail.join('\n')}
                </pre>
              </div>
            )}

            {!dangChay && lanCuoi && (
              <p className="text-[11px] text-slate-600 dark:text-slate-300">
                Lượt quét gần nhất {truoc(lanCuoi.finished_at)}: soi <b>{lanCuoi.quet}</b> tệp →{' '}
                <b className="text-emerald-700 dark:text-emerald-300">{lanCuoi.moi} học mới</b>,{' '}
                {lanCuoi.cap_nhat} cập nhật, {lanCuoi.khong_doi} không đổi
                {lanCuoi.loi > 0 && (
                  <span className="text-hds-red"> , {lanCuoi.loi} lỗi</span>
                )}
                .
              </p>
            )}

            {!dangChay && quet?.ket_thuc && quet.ket_thuc.ma_thoat !== 0 && (
              <p className="text-[11px] text-hds-red">
                Lượt quét bấm từ web kết thúc bất thường (mã {quet.ket_thuc.ma_thoat}) — xem nhật ký
                ở <b>Kho tài liệu đã học</b>.
              </p>
            )}

            {(tong?.loi || 0) > 0 && (
              <button
                type="button"
                onClick={onMoKho}
                className="w-full text-left p-2.5 rounded-xl border border-rose-200 dark:border-rose-900 bg-rose-50/70 dark:bg-rose-950/30 text-[11px] text-rose-800 dark:text-rose-200 hover:bg-rose-100 dark:hover:bg-rose-950/60"
              >
                <AlertTriangle className="w-3.5 h-3.5 inline mr-1" />
                <b>{tong?.loi}</b> tệp chưa học được (hỏng, thiếu quyền đọc, định dạng lạ) —
                {onMoKho ? ' bấm để mở Kho tài liệu đã học xem lý do.' : ' xem ở Kho tài liệu đã học.'}
              </button>
            )}

            {(tong?.cho_duyet || 0) > 0 && (
              <p className="text-[11px] text-amber-800 dark:text-amber-300">
                {tong?.cho_duyet} tài liệu đã đọc xong nhưng <b>chờ duyệt nhãn</b> — bot chưa dùng
                để trả lời cho tới khi được duyệt.
              </p>
            )}
          </>
        )}
      </div>
    </div>
  );
};
