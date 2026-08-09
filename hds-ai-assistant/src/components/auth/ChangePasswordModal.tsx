import React, { useState } from 'react';
import { useApp } from '../../context/AppContext';
import * as api from '../../api';
import { Lock, KeyRound, AlertCircle, CheckCircle2, X, Loader2 } from 'lucide-react';

interface ChangePasswordModalProps {
  isOpen: boolean;
  onClose: () => void;
}

const MIN_LENGTH = 6; // khớp kiểm tra ở backend: app/api.py change_password

const inputClass =
  'w-full pl-9 pr-3 py-2 border border-slate-300 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 rounded-xl focus:ring-2 focus:ring-hds-blue focus:outline-none text-xs transition-colors';

export const ChangePasswordModal: React.FC<ChangePasswordModalProps> = ({ isOpen, onClose }) => {
  const { showToast } = useApp();

  const [oldPassword, setOldPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');

  if (!isOpen) return null;

  const handleClose = () => {
    setOldPassword('');
    setNewPassword('');
    setConfirmPassword('');
    setErrorMsg('');
    onClose();
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!oldPassword || !newPassword) {
      setErrorMsg('Vui lòng nhập mật khẩu hiện tại và mật khẩu mới.');
      return;
    }
    if (newPassword.length < MIN_LENGTH) {
      setErrorMsg(`Mật khẩu mới phải có ít nhất ${MIN_LENGTH} ký tự.`);
      return;
    }
    if (newPassword !== confirmPassword) {
      setErrorMsg('Mật khẩu mới và ô xác nhận không trùng khớp.');
      return;
    }
    if (newPassword === oldPassword) {
      setErrorMsg('Mật khẩu mới phải khác mật khẩu hiện tại.');
      return;
    }

    setIsLoading(true);
    setErrorMsg('');

    try {
      const res = await api.changePassword({
        old_password: oldPassword,
        new_password: newPassword,
      });
      showToast(res?.message || 'Đổi mật khẩu thành công.', 'success');
      handleClose();
    } catch (err: any) {
      setErrorMsg(err?.message || 'Không đổi được mật khẩu. Vui lòng kiểm tra lại.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div
      className="fixed inset-0 bg-slate-900/60 backdrop-blur-sm flex items-center justify-center z-50 p-4 animate-fade-in"
      onClick={handleClose}
      role="presentation"
    >
      <div
        className="bg-white dark:bg-slate-900 rounded-2xl shadow-2xl border border-slate-200 dark:border-slate-700 w-full max-w-md p-6 text-slate-800 dark:text-slate-100 animate-pop-in max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="password-modal-title"
      >
        <div className="flex items-start justify-between pb-4 border-b border-slate-100 dark:border-slate-800">
          <div className="flex items-center gap-2.5">
            <span className="p-2 bg-hds-soft dark:bg-hds-navy text-hds-navy dark:text-blue-200 rounded-lg">
              <KeyRound className="w-5 h-5" />
            </span>
            <div>
              <h3 id="password-modal-title" className="font-bold text-base">
                Đổi mật khẩu
              </h3>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                Cập nhật mật khẩu tài khoản cá nhân
              </p>
            </div>
          </div>
          <button
            onClick={handleClose}
            className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 p-1"
            aria-label="Đóng"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="mt-4 space-y-4 text-xs">
          {errorMsg && (
            <div
              role="alert"
              className="p-3 bg-red-50 dark:bg-red-950/60 border border-red-200 dark:border-red-900 rounded-xl text-red-800 dark:text-red-200 flex items-start gap-2 animate-shake"
            >
              <AlertCircle className="w-4 h-4 shrink-0 mt-px" />
              <span>{errorMsg}</span>
            </div>
          )}

          <div>
            <label
              htmlFor="old-password"
              className="block font-semibold text-slate-700 dark:text-slate-300 mb-1"
            >
              Mật khẩu hiện tại
            </label>
            <div className="relative flex items-center">
              <Lock className="w-4 h-4 text-slate-400 absolute left-3 pointer-events-none" />
              <input
                id="old-password"
                type="password"
                required
                autoComplete="current-password"
                value={oldPassword}
                onChange={(e) => setOldPassword(e.target.value)}
                placeholder="••••••••"
                className={inputClass}
              />
            </div>
          </div>

          <div>
            <label
              htmlFor="new-password"
              className="block font-semibold text-slate-700 dark:text-slate-300 mb-1"
            >
              Mật khẩu mới
            </label>
            <div className="relative flex items-center">
              <Lock className="w-4 h-4 text-slate-400 absolute left-3 pointer-events-none" />
              <input
                id="new-password"
                type="password"
                required
                minLength={MIN_LENGTH}
                autoComplete="new-password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                placeholder={`Tối thiểu ${MIN_LENGTH} ký tự`}
                className={inputClass}
              />
            </div>
          </div>

          <div>
            <label
              htmlFor="confirm-password"
              className="block font-semibold text-slate-700 dark:text-slate-300 mb-1"
            >
              Xác nhận mật khẩu mới
            </label>
            <div className="relative flex items-center">
              <Lock className="w-4 h-4 text-slate-400 absolute left-3 pointer-events-none" />
              <input
                id="confirm-password"
                type="password"
                required
                autoComplete="new-password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                placeholder="Nhập lại mật khẩu mới"
                className={inputClass}
              />
            </div>
          </div>

          <div className="pt-3 border-t border-slate-100 dark:border-slate-800 flex justify-end gap-2">
            <button
              type="button"
              onClick={handleClose}
              className="px-4 py-2 border border-slate-300 dark:border-slate-700 rounded-xl font-semibold text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors"
            >
              Huỷ
            </button>
            <button
              type="submit"
              disabled={isLoading}
              className="px-4 py-2 bg-hds-navy hover:bg-hds-navy-light text-white font-semibold rounded-xl flex items-center gap-1.5 shadow-sm transition-colors disabled:bg-slate-300 dark:disabled:bg-slate-700 disabled:cursor-not-allowed"
            >
              {isLoading ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>Đang lưu…</span>
                </>
              ) : (
                <>
                  <CheckCircle2 className="w-4 h-4" />
                  <span>Xác nhận đổi</span>
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
