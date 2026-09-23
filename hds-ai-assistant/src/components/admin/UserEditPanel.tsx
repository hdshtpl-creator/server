import React, { useState } from 'react';
import * as api from '../../api';
import type { User, UserRole, Department, Client } from '../../types';
import { ROLE_META } from '../../constants';
import { Crown, Loader2, Save, X } from 'lucide-react';

/**
 * Sửa một tài khoản đã tạo (22/09/2026): họ tên, vai, hồ sơ khách, phòng ban,
 * trưởng phòng. Trước đó những việc này chỉ làm được bằng SQL trên máy chủ
 * (sổ tay IT mục 8.2) — đưa vào vận hành thì quản trị phải tự làm trên web.
 *
 * Gửi PATCH /users/{id}; máy chủ chặn tự đổi vai của mình và hạ vai admin
 * cuối cùng, giao diện chỉ lặp lại câu báo của máy chủ.
 */

const ROLE_OPTIONS: UserRole[] = [
  'admin',
  'ban_qt',
  'truong_bph',
  'chuyen_vien',
  'tro_ly',
  'client_free',
  'client_plus',
  'client_pro',
];

const inputClass =
  'w-full px-3 py-2 border border-slate-300 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 rounded-xl focus:ring-2 focus:ring-hds-blue focus:outline-none transition-colors text-xs';

interface Props {
  user: User;
  departments: Department[];
  clients: Client[];
  /** Tài khoản đang đăng nhập — không cho tự đổi vai. */
  isSelf: boolean;
  onSaved: () => Promise<void> | void;
  onCancel: () => void;
  showToast: (message: string, type?: 'success' | 'error' | 'info') => void;
}

export const UserEditPanel: React.FC<Props> = ({
  user,
  departments,
  clients,
  isSelf,
  onSaved,
  onCancel,
  showToast,
}) => {
  const [fullName, setFullName] = useState(user.full_name || '');
  const [role, setRole] = useState<UserRole>(user.role);
  const [clientId, setClientId] = useState<string>(
    user.client_id != null ? String(user.client_id) : ''
  );
  const [deptIds, setDeptIds] = useState<number[]>(user.department_ids || []);
  const [headOf, setHeadOf] = useState<number[]>(user.head_of || []);
  const [busy, setBusy] = useState(false);

  const isClientRole = role.startsWith('client_');

  const toggle = (setter: React.Dispatch<React.SetStateAction<number[]>>, id: number) =>
    setter((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!fullName.trim()) {
      showToast('Họ tên không được để trống.', 'error');
      return;
    }
    if (isClientRole && !clientId) {
      showToast('Tài khoản vai Khách hàng bắt buộc phải gắn với một khách hàng.', 'error');
      return;
    }
    setBusy(true);
    try {
      await api.updateUser(user.id, {
        full_name: fullName.trim(),
        role,
        client_id: isClientRole ? clientId : null,
        // Vai nội bộ: gửi trọn danh sách phòng (máy chủ ghi đè). Trưởng phòng
        // chỉ có nghĩa khi thuộc phòng đó — lọc trước cho khớp chốt máy chủ.
        department_ids: isClientRole ? [] : deptIds,
        head_of: isClientRole ? [] : headOf.filter((d) => deptIds.includes(d)),
      });
      showToast(`Đã lưu thay đổi cho ${fullName.trim()}.`, 'success');
      await onSaved();
    } catch (err: any) {
      showToast(err?.message || 'Không lưu được thay đổi.', 'error');
    } finally {
      setBusy(false);
    }
  };

  return (
    <form
      onSubmit={handleSave}
      className="mt-3 p-3.5 bg-slate-50 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700 rounded-xl space-y-3 text-xs"
      aria-label={`Sửa tài khoản ${user.email || user.id}`}
    >
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div>
          <label
            htmlFor={`edit-name-${user.id}`}
            className="block font-semibold text-slate-700 dark:text-slate-300 mb-1"
          >
            Họ và tên
          </label>
          <input
            id={`edit-name-${user.id}`}
            type="text"
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            className={inputClass}
          />
        </div>
        <div>
          <label
            htmlFor={`edit-role-${user.id}`}
            className="block font-semibold text-slate-700 dark:text-slate-300 mb-1"
          >
            Vai trò
            {isSelf && (
              <span className="ml-1 font-normal text-slate-400">(không tự đổi được)</span>
            )}
          </label>
          <select
            id={`edit-role-${user.id}`}
            value={role}
            disabled={isSelf}
            onChange={(e) => setRole(e.target.value as UserRole)}
            className={`${inputClass} font-medium disabled:opacity-60`}
          >
            {ROLE_OPTIONS.map((r) => (
              <option key={r} value={r}>
                {ROLE_META[r].label} ({r})
              </option>
            ))}
          </select>
        </div>
      </div>

      {isClientRole ? (
        <div>
          <label
            htmlFor={`edit-client-${user.id}`}
            className="font-semibold text-slate-700 dark:text-slate-300 mb-1 flex items-center justify-between"
          >
            <span>Khách hàng liên kết</span>
            <span className="text-[10px] text-hds-red dark:text-red-400 font-bold uppercase">
              Bắt buộc
            </span>
          </label>
          <select
            id={`edit-client-${user.id}`}
            value={clientId}
            onChange={(e) => setClientId(e.target.value)}
            className={`${inputClass} ${!clientId ? 'border-red-400 dark:border-red-700' : ''}`}
          >
            <option value="">— Chọn khách hàng —</option>
            {clients.map((c) => (
              <option key={c.id} value={String(c.id)}>
                [{c.code}] {c.name}
              </option>
            ))}
          </select>
        </div>
      ) : (
        departments.length > 0 && (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <span className="block font-semibold text-slate-700 dark:text-slate-300 mb-1">
                Thuộc phòng ban
              </span>
              <div className="space-y-1.5 bg-white dark:bg-slate-900 p-2.5 rounded-xl border border-slate-200 dark:border-slate-700">
                {departments.map((d) => (
                  <label
                    key={d.id}
                    className="flex items-center gap-2 cursor-pointer text-[11px] text-slate-700 dark:text-slate-300"
                  >
                    <input
                      type="checkbox"
                      checked={deptIds.includes(d.id)}
                      onChange={() => toggle(setDeptIds, d.id)}
                      className="rounded accent-[#1f3864]"
                    />
                    <span>
                      {d.name} <span className="font-mono text-slate-400">({d.code})</span>
                    </span>
                  </label>
                ))}
              </div>
            </div>
            <div>
              <span className="block font-semibold text-slate-700 dark:text-slate-300 mb-1">
                Làm trưởng bộ phận của
              </span>
              <div className="space-y-1.5 bg-white dark:bg-slate-900 p-2.5 rounded-xl border border-slate-200 dark:border-slate-700">
                {departments.map((d) => (
                  <label
                    key={d.id}
                    className={`flex items-center gap-2 text-[11px] ${
                      deptIds.includes(d.id)
                        ? 'cursor-pointer text-slate-700 dark:text-slate-300'
                        : 'text-slate-400 cursor-not-allowed'
                    }`}
                    title={deptIds.includes(d.id) ? '' : 'Phải thuộc phòng này trước'}
                  >
                    <input
                      type="checkbox"
                      disabled={!deptIds.includes(d.id)}
                      checked={headOf.includes(d.id) && deptIds.includes(d.id)}
                      onChange={() => toggle(setHeadOf, d.id)}
                      className="rounded accent-[#1f3864]"
                    />
                    <span className="flex items-center gap-1">
                      <Crown className="w-3 h-3 text-hds-gold shrink-0" />
                      {d.name}
                    </span>
                  </label>
                ))}
              </div>
            </div>
          </div>
        )
      )}

      <div className="flex flex-wrap items-center justify-end gap-2 pt-1">
        <button
          type="button"
          onClick={onCancel}
          disabled={busy}
          className="px-3 py-1.5 border border-slate-300 dark:border-slate-700 rounded-xl font-semibold text-slate-600 dark:text-slate-300 hover:bg-white dark:hover:bg-slate-800 inline-flex items-center gap-1 transition-colors"
        >
          <X className="w-3.5 h-3.5" />
          Huỷ
        </button>
        <button
          type="submit"
          disabled={busy}
          className="px-3 py-1.5 bg-hds-navy hover:bg-hds-navy-light text-white font-bold rounded-xl inline-flex items-center gap-1 transition-colors disabled:opacity-60"
        >
          {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
          Lưu thay đổi
        </button>
      </div>
    </form>
  );
};
