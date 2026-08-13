import React, { useEffect, useState } from 'react';
import { useApp } from '../../context/AppContext';
import * as api from '../../api';
import type { Stats } from '../../types';
import {
  FileText,
  CheckCircle2,
  Clock,
  AlertTriangle,
  Layers,
  MessageSquareText,
  GraduationCap,
  Boxes,
  RefreshCw,
  ArrowRight,
  Users2,
  Briefcase,
  Building,
  MessageSquareWarning,
} from 'lucide-react';
import { MatterAlertsCard } from './MatterAlertsCard';

type IconType = React.ComponentType<{ className?: string }>;

interface StatCardProps {
  label: string;
  value: number | null | undefined;
  hint: string;
  icon: IconType;
  /** Lớp màu cho ô biểu tượng và con số. */
  tone: { icon: string; value: string };
  onClick?: () => void;
}

/** Hiển thị "—" khi backend không trả về số, thay vì bịa một giá trị mặc định. */
const StatCard: React.FC<StatCardProps> = ({ label, value, hint, icon: Icon, tone, onClick }) => {
  const isMissing = value === null || value === undefined;
  const Wrapper = onClick ? 'button' : 'div';

  return (
    <Wrapper
      onClick={onClick}
      className={`bg-white dark:bg-slate-900 p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm text-left w-full transition-colors ${
        onClick
          ? 'hover:border-hds-blue dark:hover:border-blue-600 cursor-pointer'
          : 'hover:border-slate-300 dark:hover:border-slate-700'
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
          {label}
        </span>
        <span className={`p-2 rounded-xl shrink-0 ${tone.icon}`}>
          <Icon className="w-5 h-5" />
        </span>
      </div>
      <div className="mt-3">
        <div className={`text-2xl font-black ${isMissing ? 'text-slate-400' : tone.value}`}>
          {isMissing ? '—' : value.toLocaleString('vi-VN')}
        </div>
        <p className="text-[11px] text-slate-500 dark:text-slate-400 mt-0.5 flex items-center gap-1">
          <span>{hint}</span>
          {onClick && <ArrowRight className="w-3 h-3 shrink-0" />}
        </p>
      </div>
    </Wrapper>
  );
};

const TONES = {
  navy: { icon: 'bg-hds-soft dark:bg-slate-800 text-hds-navy dark:text-blue-300', value: 'text-slate-900 dark:text-slate-100' },
  green: { icon: 'bg-emerald-50 dark:bg-emerald-950 text-hds-green dark:text-emerald-400', value: 'text-hds-green dark:text-emerald-400' },
  amber: { icon: 'bg-amber-50 dark:bg-amber-950 text-amber-600 dark:text-amber-400', value: 'text-amber-600 dark:text-amber-400' },
  indigo: { icon: 'bg-indigo-50 dark:bg-indigo-950 text-indigo-600 dark:text-indigo-400', value: 'text-indigo-600 dark:text-indigo-400' },
  rose: { icon: 'bg-rose-50 dark:bg-rose-950 text-rose-600 dark:text-rose-400', value: 'text-rose-600 dark:text-rose-400' },
  cyan: { icon: 'bg-cyan-50 dark:bg-cyan-950 text-cyan-600 dark:text-cyan-400', value: 'text-slate-900 dark:text-slate-100' },
  purple: { icon: 'bg-purple-50 dark:bg-purple-950 text-purple-600 dark:text-purple-400', value: 'text-slate-900 dark:text-slate-100' },
  teal: { icon: 'bg-teal-50 dark:bg-teal-950 text-teal-600 dark:text-teal-400', value: 'text-teal-600 dark:text-teal-400' },
};

export const OverviewTab: React.FC = () => {
  const { showToast, setAdminTab } = useApp();
  const [stats, setStats] = useState<Stats | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const fetchStats = async () => {
    setIsLoading(true);
    setLoadError(null);
    try {
      setStats(await api.getStats());
    } catch (err: any) {
      const msg = err?.message || 'Không tải được số liệu tổng quan.';
      setLoadError(msg);
      showToast(msg, 'error');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchStats();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center p-12 text-slate-500 dark:text-slate-400 gap-2 text-sm">
        <RefreshCw className="w-5 h-5 animate-spin text-hds-navy dark:text-blue-400" />
        <span>Đang tải số liệu thống kê hệ thống…</span>
      </div>
    );
  }

  if (loadError || !stats) {
    return (
      <div className="bg-white dark:bg-slate-900 rounded-2xl p-10 text-center border border-slate-200 dark:border-slate-800 space-y-3">
        <AlertTriangle className="w-10 h-10 text-hds-red mx-auto" />
        <h3 className="font-bold text-slate-800 dark:text-slate-100">
          Không tải được số liệu tổng quan
        </h3>
        <p className="text-xs text-slate-500 dark:text-slate-400 max-w-md mx-auto">
          {loadError || 'Máy chủ không trả về dữ liệu.'}
        </p>
        <button
          onClick={fetchStats}
          className="mt-2 px-4 py-2 bg-hds-navy hover:bg-hds-navy-light text-white text-xs font-semibold rounded-xl inline-flex items-center gap-1.5 transition-colors"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          <span>Thử lại</span>
        </button>
      </div>
    );
  }

  const missingOwner = stats.thieu_chu_so_huu ?? 0;

  return (
    <div className="space-y-6">
      {/* Tiêu đề khu vực */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 bg-white dark:bg-slate-900 p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm">
        <div>
          <h2 className="text-lg font-bold text-slate-900 dark:text-slate-100">
            Tổng quan hệ thống HDS AI
          </h2>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
            Thống kê tài liệu, trạng thái kiểm duyệt, hồ sơ khách hàng và vụ việc đang mở
          </p>
        </div>
        <button
          onClick={fetchStats}
          className="flex items-center gap-1.5 px-3.5 py-2 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 font-semibold text-xs rounded-xl transition-colors shrink-0"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          <span>Cập nhật số liệu</span>
        </button>
      </div>

      {/* Hạn chót vụ việc — việc cần làm hôm nay, đặt trước mọi số liệu */}
      <MatterAlertsCard />

      {/* Cảnh báo tài liệu thiếu chủ sở hữu */}
      {missingOwner > 0 && (
        <div
          role="alert"
          className="p-4 bg-hds-red text-white rounded-2xl shadow-md flex flex-col sm:flex-row sm:items-center justify-between gap-4"
        >
          <div className="flex items-start gap-3">
            <span className="p-2.5 bg-white/20 rounded-xl shrink-0">
              <AlertTriangle className="w-6 h-6" />
            </span>
            <div>
              <h4 className="font-extrabold text-sm uppercase tracking-wide">
                Cảnh báo an toàn dữ liệu
              </h4>
              <p className="text-xs text-red-50 mt-0.5 leading-relaxed">
                Có <span className="font-black text-sm">{missingOwner}</span> tài liệu ở mức "Hồ sơ
                khách hàng" nhưng chưa gán chủ sở hữu. Con số này phải luôn bằng 0.
              </p>
            </div>
          </div>
          <button
            onClick={() => setAdminTab('review')}
            className="px-4 py-2 bg-white text-hds-red hover:bg-red-50 font-bold text-xs rounded-xl shadow-sm flex items-center justify-center gap-1 shrink-0 transition-colors"
          >
            <span>Duyệt bổ sung ngay</span>
            <ArrowRight className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Lưới số liệu */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          label="Tài liệu"
          value={stats.tai_lieu}
          hint="Tổng số văn bản trong hệ thống"
          icon={FileText}
          tone={TONES.navy}
        />
        <StatCard
          label="Đã duyệt nhãn"
          value={stats.da_duyet_nhan}
          hint="Đã gán nhãn phân quyền chuẩn"
          icon={CheckCircle2}
          tone={TONES.green}
        />
        <StatCard
          label="Chờ duyệt nhãn"
          value={stats.cho_duyet_nhan}
          hint="Hàng chờ kiểm duyệt"
          icon={Clock}
          tone={TONES.amber}
          onClick={() => setAdminTab('review')}
        />

        {/* Thẻ thiếu chủ sở hữu — tô đỏ nổi bật khi > 0 */}
        <div
          className={`p-5 rounded-2xl border transition-colors ${
            missingOwner > 0
              ? 'bg-hds-red text-white border-red-800 shadow-md'
              : 'bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800 shadow-sm'
          }`}
        >
          <div className="flex items-center justify-between gap-2">
            <span
              className={`text-xs font-semibold uppercase tracking-wider ${
                missingOwner > 0 ? 'text-red-100' : 'text-slate-500 dark:text-slate-400'
              }`}
            >
              Thiếu chủ sở hữu
            </span>
            <span
              className={`p-2 rounded-xl shrink-0 ${
                missingOwner > 0
                  ? 'bg-white text-hds-red'
                  : 'bg-red-50 dark:bg-red-950 text-hds-red dark:text-red-400'
              }`}
            >
              <AlertTriangle className="w-5 h-5" />
            </span>
          </div>
          <div className="mt-3">
            <div
              className={`font-black ${
                missingOwner > 0 ? 'text-3xl text-white' : 'text-2xl text-slate-900 dark:text-slate-100'
              }`}
            >
              {missingOwner}
            </div>
            <p
              className={`text-[11px] mt-0.5 ${
                missingOwner > 0
                  ? 'text-red-100 font-semibold'
                  : 'text-slate-500 dark:text-slate-400'
              }`}
            >
              {missingOwner > 0
                ? 'Bắt buộc duyệt bổ sung khách hàng sở hữu'
                : 'Tất cả tài liệu đều đủ thông tin'}
            </p>
          </div>
        </div>

        <StatCard
          label="Khách hàng"
          value={stats.so_khach}
          hint="Hồ sơ khách hàng 360°"
          icon={Users2}
          tone={TONES.indigo}
          onClick={() => setAdminTab('clients_360')}
        />
        <StatCard
          label="Vụ việc đang mở"
          value={stats.vu_viec_dang_mo}
          hint="Hồ sơ chưa hoàn thành"
          icon={Briefcase}
          tone={TONES.rose}
          onClick={() => setAdminTab('clients_360')}
        />
        <StatCard
          label="Phòng / Bộ phận"
          value={stats.so_bo_phan}
          hint="Cấu trúc bộ phận nội bộ"
          icon={Building}
          tone={TONES.cyan}
        />
        <StatCard
          label="Số đoạn trích"
          value={stats.so_doan}
          hint="Đoạn văn bản đã vector hoá cho RAG"
          icon={Layers}
          tone={TONES.purple}
        />
        <StatCard
          label="Hội thoại chờ học"
          value={stats.hoi_thoai_cho_duyet}
          hint="Cần thẩm định câu trả lời"
          icon={MessageSquareText}
          tone={TONES.indigo}
          onClick={() => setAdminTab('learn')}
        />
        <StatCard
          label="Báo cáo chờ xử lý"
          value={stats.bao_cao_cho_xu_ly}
          hint="Người dùng báo chất lượng câu trả lời"
          icon={MessageSquareWarning}
          tone={TONES.rose}
          onClick={() => setAdminTab('feedback')}
        />
        <StatCard
          label="Đã tiếp thu"
          value={stats.da_hoc}
          hint="Câu trả lời đã nạp thành tri thức"
          icon={GraduationCap}
          tone={TONES.teal}
        />
        <StatCard
          label="Mẫu phương pháp"
          value={stats.so_mau_phuong_phap}
          hint="Quy trình xử lý vụ việc"
          icon={Boxes}
          tone={TONES.amber}
          onClick={() => setAdminTab('methods')}
        />
      </div>
    </div>
  );
};
