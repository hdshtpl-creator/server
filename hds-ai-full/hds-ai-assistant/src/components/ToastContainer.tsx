import React from 'react';
import { useApp } from '../context/AppContext';
import { CheckCircle2, AlertCircle, Info, X } from 'lucide-react';

const TOAST_STYLES = {
  success: {
    box: 'bg-hds-green text-white border-emerald-800',
    icon: 'text-emerald-200',
    Icon: CheckCircle2,
  },
  error: {
    box: 'bg-hds-red text-white border-red-900',
    icon: 'text-red-200',
    Icon: AlertCircle,
  },
  info: {
    box: 'bg-hds-navy text-white border-hds-navy-dark',
    icon: 'text-blue-200',
    Icon: Info,
  },
} as const;

export const ToastContainer: React.FC = () => {
  const { toasts, removeToast } = useApp();

  if (toasts.length === 0) return null;

  return (
    <div
      className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 w-full max-w-sm px-4 sm:px-0 sm:right-6 pointer-events-none"
      role="region"
      aria-label="Thông báo hệ thống"
    >
      {toasts.map((toast) => {
        const style = TOAST_STYLES[toast.type];
        const Icon = style.Icon;

        return (
          <div
            key={toast.id}
            role={toast.type === 'error' ? 'alert' : 'status'}
            className={`pointer-events-auto p-3.5 rounded-xl shadow-xl border flex items-start gap-3 animate-slide-up ${style.box}`}
          >
            <Icon className={`w-5 h-5 shrink-0 mt-px ${style.icon}`} />

            <p className="flex-1 text-xs leading-relaxed break-words">{toast.message}</p>

            <button
              onClick={() => removeToast(toast.id)}
              className="text-white/60 hover:text-white p-0.5 rounded shrink-0 transition-colors"
              aria-label="Đóng thông báo"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        );
      })}
    </div>
  );
};
