import React, { useEffect, useState } from 'react';
import { useApp } from '../../context/AppContext';
import * as api from '../../api';
import type { User, UserRole, Department, Client, TinhNang } from '../../types';
import { ROLE_META } from '../../constants';
import { SuDungCard } from './SuDungCard';
import { UserEditPanel } from './UserEditPanel';
import {
  Users,
  UserPlus,
  ShieldCheck,
  ShieldAlert,
  RefreshCw,
  Mail,
  Building2,
  Building,
  Crown,
  Info,
  Loader2,
  Wallet,
  WalletMinimal,
  KeyRound,
  Copy,
  AlertTriangle,
  Pencil,
  Lock,
  Unlock,
  Clock,
} from 'lucide-react';

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
  'w-full px-3 py-2 border border-slate-300 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 rounded-xl focus:ring-2 focus:ring-hds-blue focus:outline-none transition-colors';

/**
 * Bí mật vừa cấp (khoá API hoặc mật khẩu tạm) — chỉ tồn tại trong phiên này.
 * Máy chủ lưu bản băm nên không có đường xem lại; quản trị phải chép ngay.
 */
interface SecretOnce {
  uid: number;
  kind: 'api_key' | 'password';
  value: string;
  /** Email/tên người nhận để quản trị biết gửi cho ai. */
  who: string;
}

export const UserManagementTab: React.FC = () => {
  const { showToast, reloadUsers, currentUser } = useApp();
  const [userList, setUserList] = useState<User[]>([]);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [clients, setClients] = useState<Client[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  // Biểu mẫu tạo tài khoản
  const [email, setEmail] = useState('');
  const [fullName, setFullName] = useState('');
  const [role, setRole] = useState<UserRole>('chuyen_vien');
  const [canReview, setCanReview] = useState(false);
  const [clientId, setClientId] = useState('');
  const [selectedDeptIds, setSelectedDeptIds] = useState<number[]>([]);
  const [selectedHeadOfIds, setSelectedHeadOfIds] = useState<number[]>([]);
  const [monthlyQuota, setMonthlyQuota] = useState<number>(0);
  // Mật khẩu khởi tạo: để trống = máy chủ tự sinh mật khẩu tạm (22/09/2026,
  // thay cho "hds12345" cố định ai cũng biết).
  const [password, setPassword] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Tài khoản đang mở bảng sửa (họ tên / vai / phòng ban) và tài khoản đang
  // chờ máy chủ trả lời cho thao tác khoá / đặt lại mật khẩu.
  const [editingId, setEditingId] = useState<number | null>(null);
  const [actionBusyId, setActionBusyId] = useState<number | null>(null);

  // Chức năng mở cho tài khoản sắp tạo. Rỗng = theo mặc định của vai (khách
  // chỉ hỏi đáp). Danh mục lấy từ máy chủ để giao diện không tự bịa ra tên.
  const [tinhNang, setTinhNang] = useState<TinhNang[]>([]);
  const [macDinhKhach, setMacDinhKhach] = useState<Record<string, boolean>>({});
  const [featureTick, setFeatureTick] = useState<Record<string, boolean>>({});
  const [featureBusyId, setFeatureBusyId] = useState<number | null>(null);

  // Khoá API / mật khẩu tạm vừa cấp — chỉ tồn tại trong phiên này
  const [secret, setSecret] = useState<SecretOnce | null>(null);
  const [keyBusyId, setKeyBusyId] = useState<number | null>(null);

  const isClientRoleSelected = role.startsWith('client_');

  const fetchAll = async () => {
    setIsLoading(true);
    try {
      const [uData, dData, cData, tnData] = await Promise.all([
        api.getUsers(),
        api.getDepartments().catch(() => [] as Department[]),
        api.getClients().catch(() => [] as Client[]),
        api.getTinhNang().catch(() => null),
      ]);
      setUserList(uData);
      setDepartments(dData);
      setClients(cData);
      if (tnData) {
        setTinhNang(tnData.items || []);
        setMacDinhKhach(tnData.mac_dinh_khach || {});
      }
    } catch (err: any) {
      showToast(err?.message || 'Lỗi khi tải danh sách người dùng', 'error');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const toggleId = (setter: React.Dispatch<React.SetStateAction<number[]>>, id: number) => {
    setter((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };

  const resetForm = () => {
    setEmail('');
    setFullName('');
    setRole('chuyen_vien');
    setCanReview(false);
    setClientId('');
    setSelectedDeptIds([]);
    setSelectedHeadOfIds([]);
    setMonthlyQuota(0);
    setPassword('');
  };

  /** Bật/tắt một chức năng cho tài khoản đã tạo. Gửi TRỌN bộ tick hiện tại
   *  chứ không gửi mỗi ô vừa đổi: máy chủ lưu nguyên dict, gửi thiếu là mất
   *  những ô đã bật trước đó. */
  const toggleFeature = async (u: User, ma: string, bat: boolean) => {
    const hienTai = { ...(u.features || {}), [ma]: bat };
    setFeatureBusyId(u.id);
    setUserList((prev) =>
      prev.map((x) => (x.id === u.id ? { ...x, features: hienTai } : x))
    );
    try {
      const res = await api.updateUserFeatures(u.id, { features: hienTai });
      setUserList((prev) =>
        prev.map((x) => (x.id === u.id ? { ...x, features: res.features } : x))
      );
    } catch (err: any) {
      // Trả ô tick về trạng thái cũ khi máy chủ từ chối
      setUserList((prev) =>
        prev.map((x) => (x.id === u.id ? { ...x, features: u.features } : x))
      );
      showToast(err?.message || 'Không đổi được chức năng.', 'error');
    } finally {
      setFeatureBusyId(null);
    }
  };

  const handleCreateUser = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim() || !fullName.trim()) {
      showToast('Vui lòng nhập đầy đủ email và họ tên.', 'error');
      return;
    }
    // Ràng buộc client_role_needs_client_id trong schema.sql
    if (isClientRoleSelected && !clientId) {
      showToast('Tài khoản vai Khách hàng bắt buộc phải gắn với một khách hàng.', 'error');
      return;
    }

    setIsSubmitting(true);
    try {
      const res = await api.createUser({
        email: email.trim(),
        full_name: fullName.trim(),
        role,
        can_review: canReview,
        client_id: clientId || null,
        department_ids: selectedDeptIds,
        head_of: selectedHeadOfIds,
        monthly_quota: monthlyQuota,
        features: Object.keys(featureTick).length ? featureTick : null,
        password: password.trim() || null,
      });

      showToast(`Đã tạo tài khoản ${fullName.trim()}.`, 'success');
      // Mật khẩu tạm chỉ về đúng lần này — hiện hộp chép ngay dưới thẻ tài khoản.
      if (res?.user_id && res.mat_khau_tam) {
        setSecret({
          uid: res.user_id,
          kind: 'password',
          value: res.mat_khau_tam,
          who: `${fullName.trim()} <${email.trim().toLowerCase()}>`,
        });
      }
      resetForm();
      setFeatureTick({});
      // POST /users chỉ trả {ok, user_id} nên phải tải lại danh sách
      await fetchAll();
      reloadUsers().catch(() => {});
    } catch (err: any) {
      showToast(err?.message || 'Lỗi khi tạo người dùng', 'error');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleToggleReviewPermission = async (uid: number, currentCanReview: boolean) => {
    const grant = !currentCanReview;
    // Cập nhật lạc quan để nút phản hồi ngay, hoàn tác nếu backend từ chối
    setUserList((prev) => prev.map((u) => (u.id === uid ? { ...u, can_review: grant } : u)));
    try {
      await api.updateUserReviewPermission(uid, grant);
      showToast(`Đã ${grant ? 'cấp' : 'thu'} quyền duyệt cho tài khoản #${uid}.`, 'success');
      reloadUsers().catch(() => {});
    } catch (err: any) {
      setUserList((prev) =>
        prev.map((u) => (u.id === uid ? { ...u, can_review: currentCanReview } : u))
      );
      showToast(err?.message || 'Lỗi khi thay đổi quyền duyệt', 'error');
    }
  };

  const handleIssueApiKey = async (u: User) => {
    setKeyBusyId(u.id);
    try {
      const res = await api.issueApiKey(u.id);
      // Chỉ giữ trong state của phiên này. Backend lưu bản băm nên không có
      // đường nào xem lại — người dùng phải copy ngay.
      setSecret({ uid: u.id, kind: 'api_key', value: res.api_key, who: u.email || u.full_name });
      setUserList((prev) =>
        prev.map((x) => (x.id === u.id ? { ...x, has_api_key: true } : x))
      );
    } catch (err: any) {
      showToast(err?.message || 'Không cấp được khoá API', 'error');
    } finally {
      setKeyBusyId(null);
    }
  };

  const handleRevokeApiKey = async (uid: number) => {
    setKeyBusyId(uid);
    try {
      await api.revokeApiKey(uid);
      setUserList((prev) =>
        prev.map((u) => (u.id === uid ? { ...u, has_api_key: false } : u))
      );
      if (secret?.uid === uid && secret.kind === 'api_key') setSecret(null);
      showToast(`Đã thu hồi khoá API của tài khoản #${uid}.`, 'success');
    } catch (err: any) {
      showToast(err?.message || 'Không thu hồi được khoá API', 'error');
    } finally {
      setKeyBusyId(null);
    }
  };

  /** Khoá / mở tài khoản. Khoá là chặn đăng nhập ngay và thu khoá API;
   *  dữ liệu, lịch sử, nhật ký giữ nguyên nên không có nút xoá. */
  const handleToggleActive = async (u: User) => {
    const khoa = u.active !== false;
    if (khoa) {
      const ok = window.confirm(
        `Khoá tài khoản ${u.full_name} (${u.email})?\n\nNgười này sẽ không đăng nhập được nữa cho tới khi mở lại. Phiên đang mở (nếu có) cũng bị chặn ở lượt gọi kế tiếp.`
      );
      if (!ok) return;
    }
    setActionBusyId(u.id);
    try {
      await api.updateUser(u.id, { active: !khoa });
      setUserList((prev) =>
        prev.map((x) =>
          x.id === u.id ? { ...x, active: !khoa, has_api_key: khoa ? false : x.has_api_key } : x
        )
      );
      showToast(`Đã ${khoa ? 'khoá' : 'mở lại'} tài khoản ${u.full_name}.`, 'success');
      reloadUsers().catch(() => {});
    } catch (err: any) {
      showToast(err?.message || 'Không đổi được trạng thái tài khoản.', 'error');
    } finally {
      setActionBusyId(null);
    }
  };

  /** Đặt lại mật khẩu cho người quên: máy chủ sinh mật khẩu tạm, trả về một
   *  lần; người dùng bị bắt đổi ngay lần đăng nhập kế tiếp. */
  const handleResetPassword = async (u: User) => {
    const ok = window.confirm(
      `Đặt lại mật khẩu cho ${u.full_name} (${u.email})?\n\nMật khẩu hiện tại sẽ mất hiệu lực ngay. Mật khẩu tạm mới chỉ hiện MỘT LẦN — hãy chép và gửi cho đúng người.`
    );
    if (!ok) return;
    setActionBusyId(u.id);
    try {
      const res = await api.resetUserPassword(u.id);
      setSecret({ uid: u.id, kind: 'password', value: res.mat_khau_tam, who: `${u.full_name} <${u.email}>` });
      setUserList((prev) =>
        prev.map((x) => (x.id === u.id ? { ...x, must_change_password: true } : x))
      );
    } catch (err: any) {
      showToast(err?.message || 'Không đặt lại được mật khẩu.', 'error');
    } finally {
      setActionBusyId(null);
    }
  };

  const handleToggleFinancePermission = async (uid: number, current: boolean) => {
    const grant = !current;
    setUserList((prev) =>
      prev.map((u) => (u.id === uid ? { ...u, can_view_finance: grant } : u))
    );
    try {
      await api.updateUserFinancePermission(uid, grant);
      showToast(
        `Đã ${grant ? 'cấp' : 'thu'} quyền xem công nợ cho tài khoản #${uid}.`,
        'success'
      );
      reloadUsers().catch(() => {});
    } catch (err: any) {
      setUserList((prev) =>
        prev.map((u) => (u.id === uid ? { ...u, can_view_finance: current } : u))
      );
      showToast(err?.message || 'Lỗi khi thay đổi quyền xem công nợ', 'error');
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center p-12 text-slate-500 dark:text-slate-400 gap-2 text-sm">
        <RefreshCw className="w-5 h-5 animate-spin text-hds-navy dark:text-blue-400" />
        <span>Đang tải danh sách tài khoản và phòng ban…</span>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Tiêu đề khu vực */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 bg-white dark:bg-slate-900 p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm">
        <div>
          <h2 className="text-lg font-bold text-slate-900 dark:text-slate-100">
            Tài khoản, phòng ban và phân quyền
          </h2>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
            Tạo tài khoản cho nhân viên và khách, gán vai và phòng ban, cấp quyền duyệt / xem
            công nợ, bật tắt chức năng, khoá tài khoản và đặt lại mật khẩu
          </p>
        </div>
        <button
          onClick={fetchAll}
          className="flex items-center gap-1.5 px-3.5 py-2 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 font-semibold text-xs rounded-xl transition-colors shrink-0"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          <span>Tải lại</span>
        </button>
      </div>

      {/* Ai đang dùng đến đâu — chỉ admin, chỉ số đếm (18/09/2026) */}
      <SuDungCard />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Biểu mẫu tạo tài khoản */}
        <div className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 p-5 shadow-sm space-y-4 lg:col-span-1 h-fit">
          <div className="flex items-center gap-2 pb-3 border-b border-slate-100 dark:border-slate-800">
            <span className="p-2 bg-hds-soft dark:bg-slate-800 text-hds-navy dark:text-blue-300 rounded-xl">
              <UserPlus className="w-5 h-5" />
            </span>
            <div>
              <h3 className="font-bold text-sm text-slate-900 dark:text-slate-100">
                Thêm người dùng
              </h3>
              <p className="text-[11px] text-slate-500 dark:text-slate-400 font-mono">POST /users</p>
            </div>
          </div>

          <form onSubmit={handleCreateUser} className="space-y-3.5 text-xs">
            <div>
              <label htmlFor="new-user-name" className="block font-semibold text-slate-700 dark:text-slate-300 mb-1">
                Họ và tên
              </label>
              <input
                id="new-user-name"
                type="text"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                placeholder="Ví dụ: Nguyễn Văn A"
                className={inputClass}
              />
            </div>

            <div>
              <label htmlFor="new-user-email" className="block font-semibold text-slate-700 dark:text-slate-300 mb-1">
                Email đăng nhập
              </label>
              <input
                id="new-user-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="ten.ban@hdslaw.vn"
                className={inputClass}
              />
            </div>

            <div>
              <label htmlFor="new-user-role" className="block font-semibold text-slate-700 dark:text-slate-300 mb-1">
                Vai trò
              </label>
              <select
                id="new-user-role"
                value={role}
                onChange={(e) => setRole(e.target.value as UserRole)}
                className={`${inputClass} font-medium`}
              >
                {ROLE_OPTIONS.map((r) => (
                  <option key={r} value={r}>
                    {ROLE_META[r].label} ({r})
                  </option>
                ))}
              </select>
            </div>

            {/* Khách hàng — bắt buộc với vai client_* */}
            <div>
              <label htmlFor="new-user-client" className="font-semibold text-slate-700 dark:text-slate-300 mb-1 flex items-center justify-between gap-2">
                <span>Khách hàng liên kết</span>
                {isClientRoleSelected && (
                  <span className="text-[10px] text-hds-red dark:text-red-400 font-bold uppercase">
                    Bắt buộc
                  </span>
                )}
              </label>
              <select
                id="new-user-client"
                value={clientId}
                onChange={(e) => setClientId(e.target.value)}
                className={`${inputClass} ${
                  isClientRoleSelected && !clientId
                    ? 'border-red-400 dark:border-red-700 bg-red-50/40 dark:bg-red-950/30'
                    : ''
                }`}
              >
                <option value="">— Không liên kết (tài khoản nội bộ) —</option>
                {clients.map((c) => (
                  <option key={c.id} value={String(c.id)}>
                    [{c.code}] {c.name}
                  </option>
                ))}
              </select>
            </div>

            {/* Phòng ban */}
            {departments.length > 0 && !isClientRoleSelected && (
              <>
                <div>
                  <span className="block font-semibold text-slate-700 dark:text-slate-300 mb-1">
                    Thuộc phòng ban
                  </span>
                  <div className="space-y-1.5 bg-slate-50 dark:bg-slate-800/60 p-2.5 rounded-xl border border-slate-200 dark:border-slate-700">
                    {departments.map((d) => (
                      <label
                        key={d.id}
                        className="flex items-center gap-2 cursor-pointer text-[11px] text-slate-700 dark:text-slate-300"
                      >
                        <input
                          type="checkbox"
                          checked={selectedDeptIds.includes(d.id)}
                          onChange={() => toggleId(setSelectedDeptIds, d.id)}
                          className="rounded accent-[#1f3864]"
                        />
                        <span>
                          {d.name}{' '}
                          <span className="font-mono text-slate-400">({d.code})</span>
                        </span>
                      </label>
                    ))}
                  </div>
                </div>

                <div>
                  <span className="block font-semibold text-slate-700 dark:text-slate-300 mb-1">
                    Làm trưởng bộ phận của
                  </span>
                  <div className="space-y-1.5 bg-slate-50 dark:bg-slate-800/60 p-2.5 rounded-xl border border-slate-200 dark:border-slate-700">
                    {departments.map((d) => (
                      <label
                        key={d.id}
                        className="flex items-center gap-2 cursor-pointer text-[11px] text-slate-700 dark:text-slate-300"
                      >
                        <input
                          type="checkbox"
                          checked={selectedHeadOfIds.includes(d.id)}
                          onChange={() => toggleId(setSelectedHeadOfIds, d.id)}
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
              </>
            )}

            {/* Chức năng mở cho tài khoản (20/09/2026).
                Không tick gì = theo mặc định của vai: khách chỉ hỏi đáp,
                nhân viên nội bộ mở hết. */}
            {tinhNang.length > 0 && (
              <div>
                <span className="block font-semibold text-slate-700 dark:text-slate-300 mb-1">
                  Chức năng được dùng
                </span>
                <div className="space-y-2 bg-slate-50 dark:bg-slate-800/60 p-2.5 rounded-xl border border-slate-200 dark:border-slate-700">
                  {tinhNang.map((tn) => {
                    const macDinh = isClientRoleSelected
                      ? Boolean(macDinhKhach[tn.ma])
                      : true;
                    const dangBat = tn.ma in featureTick ? featureTick[tn.ma] : macDinh;
                    return (
                      <label
                        key={tn.ma}
                        className="flex items-start gap-2 cursor-pointer text-[11px] text-slate-700 dark:text-slate-300"
                      >
                        <input
                          type="checkbox"
                          checked={dangBat}
                          onChange={(e) =>
                            setFeatureTick((prev) => ({ ...prev, [tn.ma]: e.target.checked }))
                          }
                          className="rounded accent-[#1f3864] mt-0.5"
                        />
                        <span>
                          <span className="font-semibold">{tn.ten}</span>
                          <span className="block text-[10px] text-slate-500 dark:text-slate-400">
                            {tn.mo_ta}
                          </span>
                        </span>
                      </label>
                    );
                  })}
                </div>
                <p className="text-[10px] text-slate-500 dark:text-slate-400 mt-1">
                  {isClientRoleSelected
                    ? 'Tài khoản khách mặc định chỉ được hỏi đáp. Tick thêm để mở từng chức năng.'
                    : 'Nhân viên nội bộ mặc định mở hết; bỏ tick để khoá bớt.'}
                </p>
              </div>
            )}

            {/* Hạn mức — chỉ có ý nghĩa với tài khoản khách */}
            {isClientRoleSelected && (
              <div>
                <label htmlFor="new-user-quota" className="block font-semibold text-slate-700 dark:text-slate-300 mb-1">
                  Hạn mức câu hỏi mỗi tháng
                </label>
                <input
                  id="new-user-quota"
                  type="number"
                  min={0}
                  value={monthlyQuota}
                  onChange={(e) => setMonthlyQuota(Math.max(0, Number(e.target.value)))}
                  className={inputClass}
                />
                <p className="text-[10px] text-slate-500 dark:text-slate-400 mt-1">
                  Đặt 0 nghĩa là không giới hạn.
                </p>
              </div>
            )}

            {/* Quyền duyệt */}
            <label className="p-3 bg-slate-50 dark:bg-slate-800/60 rounded-xl border border-slate-200 dark:border-slate-700 flex items-center justify-between gap-3 cursor-pointer">
              <span>
                <span className="font-semibold text-slate-900 dark:text-slate-100 block">
                  Cấp quyền duyệt
                </span>
                <span className="text-[10px] text-slate-500 dark:text-slate-400">
                  Duyệt nhãn tài liệu và hội thoại AI
                </span>
              </span>
              <input
                type="checkbox"
                checked={canReview}
                onChange={(e) => setCanReview(e.target.checked)}
                className="w-4 h-4 rounded accent-[#1f3864] shrink-0"
              />
            </label>

            <div>
              <label htmlFor="new-user-password" className="block font-semibold text-slate-700 dark:text-slate-300 mb-1">
                Mật khẩu khởi tạo{' '}
                <span className="font-normal text-slate-400">(không bắt buộc)</span>
              </label>
              <input
                id="new-user-password"
                type="text"
                autoComplete="off"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Để trống: hệ thống tự sinh mật khẩu tạm"
                className={`${inputClass} font-mono`}
              />
            </div>

            <div className="flex items-start gap-2 text-[10px] text-slate-500 dark:text-slate-400 bg-hds-soft dark:bg-slate-800/60 border border-blue-100 dark:border-slate-700 rounded-lg p-2.5">
              <Info className="w-3.5 h-3.5 shrink-0 mt-px text-hds-blue" />
              <span>
                Mật khẩu tạm hiện <b>đúng một lần</b> sau khi tạo — chép và gửi riêng cho người
                dùng. Lần đăng nhập đầu, hệ thống bắt họ đặt mật khẩu mới (tối thiểu 8 ký tự, có
                chữ và số) rồi mới cho làm việc.
              </span>
            </div>

            <button
              type="submit"
              disabled={isSubmitting}
              className="w-full py-2.5 rounded-xl font-bold text-white shadow-sm flex items-center justify-center gap-2 bg-hds-navy hover:bg-hds-navy-light disabled:bg-slate-300 dark:disabled:bg-slate-700 disabled:cursor-not-allowed transition-colors"
            >
              {isSubmitting ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>Đang tạo…</span>
                </>
              ) : (
                <>
                  <UserPlus className="w-4 h-4 text-hds-gold" />
                  <span>Tạo tài khoản</span>
                </>
              )}
            </button>
          </form>
        </div>

        {/* Danh sách người dùng */}
        <div className="lg:col-span-2 space-y-4">
          <h3 className="font-bold text-sm text-slate-800 dark:text-slate-200 flex items-center gap-2">
            <Users className="w-4 h-4 text-hds-navy dark:text-blue-400" />
            <span>Danh sách tài khoản ({userList.length})</span>
          </h3>

          <div className="space-y-3">
            {userList.map((u) => {
              const meta = ROLE_META[u.role];

              return (
                <div
                  key={u.id}
                  className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 p-4 shadow-sm hover:border-slate-300 dark:hover:border-slate-700 transition-colors"
                >
                 <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                  <div className="space-y-1.5 min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-[11px] font-bold bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 px-2 py-0.5 rounded">
                        #{u.id}
                      </span>
                      <h4 className="font-bold text-sm text-slate-900 dark:text-slate-100 break-words">
                        {u.full_name}
                      </h4>
                      <span
                        className={`text-[10px] font-semibold px-2 py-0.5 rounded-full border whitespace-nowrap ${
                          meta?.badge ||
                          'bg-slate-100 text-slate-700 border-slate-300 dark:bg-slate-800 dark:text-slate-300'
                        }`}
                      >
                        {meta?.label || u.role}
                      </span>
                      {u.active === false && (
                        <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full border bg-slate-100 text-slate-500 border-slate-300 dark:bg-slate-800 dark:text-slate-400 dark:border-slate-700">
                          Đã khoá
                        </span>
                      )}
                      {u.active !== false && u.must_change_password && (
                        <span
                          className="text-[10px] font-semibold px-2 py-0.5 rounded-full border bg-amber-50 text-amber-800 border-amber-300 dark:bg-amber-950/40 dark:text-amber-300 dark:border-amber-800"
                          title="Đang dùng mật khẩu tạm do quản trị cấp — sẽ bị bắt đổi khi đăng nhập"
                        >
                          Chưa đổi mật khẩu tạm
                        </span>
                      )}
                      {currentUser?.id === u.id && (
                        <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full border bg-hds-soft text-hds-navy border-blue-200 dark:bg-slate-800 dark:text-blue-300 dark:border-slate-700">
                          Bạn
                        </span>
                      )}
                    </div>

                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500 dark:text-slate-400">
                      {u.email && (
                        <span className="flex items-center gap-1 min-w-0">
                          <Mail className="w-3.5 h-3.5 shrink-0" />
                          <span className="truncate">{u.email}</span>
                        </span>
                      )}
                      {u.department_ids && u.department_ids.length > 0 && (
                        <span className="flex items-center gap-1 text-slate-700 dark:text-slate-300">
                          <Building className="w-3 h-3 text-hds-blue shrink-0" />
                          {u.department_ids
                            .map((id) => departments.find((d) => d.id === id)?.name || `#${id}`)
                            .join(', ')}
                        </span>
                      )}
                      {u.client_id != null && (
                        <span className="flex items-center gap-1 text-slate-700 dark:text-slate-300 font-medium">
                          <Building2 className="w-3.5 h-3.5 text-hds-blue shrink-0" />
                          {u.client_name ||
                            clients.find((c) => c.id === u.client_id)?.name ||
                            `Khách #${u.client_id}`}
                          {u.client_code && (
                            <span className="font-mono text-[10px] text-slate-400">
                              ({u.client_code})
                            </span>
                          )}
                        </span>
                      )}
                      {u.has_api_key && (
                        <span className="flex items-center gap-1 text-[11px] text-indigo-700 dark:text-indigo-300 bg-indigo-50 dark:bg-indigo-950 px-1.5 py-0.5 rounded border border-indigo-200 dark:border-indigo-800 font-semibold">
                          <KeyRound className="w-3 h-3 shrink-0" />
                          Có khoá API
                          {u.api_key_at && <span className="font-mono">({u.api_key_at})</span>}
                        </span>
                      )}
                      {typeof u.monthly_quota === 'number' && u.monthly_quota > 0 && (
                        <span className="text-[11px] font-mono bg-hds-soft dark:bg-slate-800 text-hds-navy dark:text-blue-300 px-1.5 py-0.5 rounded border border-blue-100 dark:border-slate-700">
                          {u.monthly_quota} câu hỏi/tháng
                          {typeof u.used_this_month === 'number' && (
                            <span className="text-slate-400"> · đã dùng {u.used_this_month}</span>
                          )}
                        </span>
                      )}
                      {'last_login_at' in u && (
                        <span
                          className="flex items-center gap-1 text-[11px]"
                          title="Mốc đăng nhập gần nhất"
                        >
                          <Clock className="w-3 h-3 shrink-0" />
                          {u.last_login_at
                            ? `Đăng nhập gần nhất ${u.last_login_at}`
                            : 'Chưa đăng nhập lần nào'}
                        </span>
                      )}
                    </div>

                    {/* Chức năng đang mở cho tài khoản này — bấm để bật/tắt
                        ngay, không phải vào màn hình khác. */}
                    {tinhNang.length > 0 && u.features && (
                      <div className="mt-2 flex flex-wrap items-center gap-1.5">
                        <span className="text-[10px] uppercase font-bold text-slate-400 mr-0.5">
                          Chức năng
                        </span>
                        {tinhNang.map((tn) => {
                          const bat = Boolean(u.features?.[tn.ma]);
                          return (
                            <button
                              key={tn.ma}
                              type="button"
                              disabled={featureBusyId === u.id}
                              onClick={() => toggleFeature(u, tn.ma, !bat)}
                              title={`${tn.ten} — ${tn.mo_ta}`}
                              className={`px-2 py-0.5 rounded-full border text-[10px] font-semibold transition-colors disabled:opacity-50 ${
                                bat
                                  ? 'bg-emerald-50 text-emerald-800 border-emerald-300 dark:bg-emerald-950/40 dark:text-emerald-300 dark:border-emerald-800'
                                  : 'bg-slate-100 text-slate-500 border-slate-300 line-through dark:bg-slate-800 dark:text-slate-500 dark:border-slate-700'
                              }`}
                            >
                              {tn.ten}
                            </button>
                          );
                        })}
                      </div>
                    )}
                  </div>

                  {/* Bật/tắt các quyền đặc biệt */}
                  <div className="flex flex-col gap-2 shrink-0">
                    {/* Sửa / đặt lại mật khẩu / khoá — hiện thường trực, không
                        giấu sau rê chuột (bài học 18/09). */}
                    <div className="flex flex-wrap gap-1.5">
                      <button
                        type="button"
                        onClick={() => setEditingId(editingId === u.id ? null : u.id)}
                        className={`px-2.5 py-1.5 rounded-xl font-bold text-[11px] border inline-flex items-center gap-1 transition-colors ${
                          editingId === u.id
                            ? 'bg-hds-navy text-white border-hds-navy'
                            : 'bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-200 border-slate-300 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-700'
                        }`}
                        title="Sửa họ tên, vai, phòng ban, hồ sơ khách"
                      >
                        <Pencil className="w-3.5 h-3.5" />
                        Sửa
                      </button>
                      <button
                        type="button"
                        disabled={actionBusyId === u.id}
                        onClick={() => handleResetPassword(u)}
                        className="px-2.5 py-1.5 rounded-xl font-bold text-[11px] border bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-200 border-slate-300 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-700 inline-flex items-center gap-1 transition-colors disabled:opacity-50"
                        title="Cấp mật khẩu tạm mới cho người quên mật khẩu"
                      >
                        <KeyRound className="w-3.5 h-3.5" />
                        Đặt lại mật khẩu
                      </button>
                      <button
                        type="button"
                        disabled={actionBusyId === u.id || currentUser?.id === u.id}
                        onClick={() => handleToggleActive(u)}
                        className={`px-2.5 py-1.5 rounded-xl font-bold text-[11px] border inline-flex items-center gap-1 transition-colors disabled:opacity-50 ${
                          u.active === false
                            ? 'bg-emerald-50 dark:bg-emerald-950 text-emerald-800 dark:text-emerald-300 border-emerald-300 dark:border-emerald-800 hover:bg-emerald-100'
                            : 'bg-white dark:bg-slate-800 text-hds-red dark:text-red-400 border-red-200 dark:border-red-900 hover:bg-red-50 dark:hover:bg-red-950/40'
                        }`}
                        title={
                          currentUser?.id === u.id
                            ? 'Không tự khoá tài khoản của chính mình'
                            : u.active === false
                              ? 'Cho phép đăng nhập trở lại'
                              : 'Chặn đăng nhập, giữ nguyên dữ liệu và nhật ký'
                        }
                      >
                        {actionBusyId === u.id ? (
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        ) : u.active === false ? (
                          <Unlock className="w-3.5 h-3.5" />
                        ) : (
                          <Lock className="w-3.5 h-3.5" />
                        )}
                        {u.active === false ? 'Mở khoá' : 'Khoá'}
                      </button>
                    </div>

                    <button
                      onClick={() => handleToggleReviewPermission(u.id, u.can_review)}
                      className={`px-3 py-1.5 rounded-xl font-bold text-xs border flex items-center gap-1.5 justify-between transition-colors ${
                        u.can_review
                          ? 'bg-emerald-50 dark:bg-emerald-950 text-emerald-800 dark:text-emerald-300 border-emerald-300 dark:border-emerald-800 hover:bg-emerald-100'
                          : 'bg-slate-50 dark:bg-slate-800 text-slate-600 dark:text-slate-300 border-slate-300 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-700'
                      }`}
                      title="Bấm để cấp hoặc thu quyền duyệt"
                      aria-pressed={u.can_review}
                    >
                      {u.can_review ? (
                        <>
                          <ShieldCheck className="w-4 h-4" />
                          <span>Có quyền duyệt</span>
                        </>
                      ) : (
                        <>
                          <ShieldAlert className="w-4 h-4 text-slate-400" />
                          <span>Không có quyền duyệt</span>
                        </>
                      )}
                    </button>

                    {/* Khoá API — chỉ tài khoản khách dùng để gọi API trực tiếp */}
                    {u.role.startsWith('client_') && (
                      <button
                        onClick={() =>
                          u.has_api_key ? handleRevokeApiKey(u.id) : handleIssueApiKey(u)
                        }
                        disabled={keyBusyId === u.id}
                        className={`px-3 py-1.5 rounded-xl font-bold text-xs border flex items-center gap-1.5 justify-between transition-colors disabled:opacity-50 ${
                          u.has_api_key
                            ? 'bg-indigo-50 dark:bg-indigo-950 text-indigo-800 dark:text-indigo-300 border-indigo-300 dark:border-indigo-800 hover:bg-indigo-100'
                            : 'bg-slate-50 dark:bg-slate-800 text-slate-600 dark:text-slate-300 border-slate-300 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-700'
                        }`}
                        title={
                          u.has_api_key
                            ? 'Thu hồi khoá API hiện tại'
                            : 'Cấp khoá API để khách gọi trực tiếp'
                        }
                      >
                        {keyBusyId === u.id ? (
                          <Loader2 className="w-4 h-4 animate-spin" />
                        ) : (
                          <KeyRound className="w-4 h-4" />
                        )}
                        <span>{u.has_api_key ? 'Thu hồi khoá API' : 'Cấp khoá API'}</span>
                      </button>
                    )}

                    {/* Quyền xem công nợ — chỉ có nghĩa với tài khoản nội bộ.
                        Vai admin luôn có quyền này nên không cần nút bật/tắt. */}
                    {!u.role.startsWith('client_') && u.role !== 'admin' && (
                      <button
                        onClick={() =>
                          handleToggleFinancePermission(u.id, Boolean(u.can_view_finance))
                        }
                        className={`px-3 py-1.5 rounded-xl font-bold text-xs border flex items-center gap-1.5 justify-between transition-colors ${
                          u.can_view_finance
                            ? 'bg-amber-50 dark:bg-amber-950 text-amber-800 dark:text-amber-300 border-amber-300 dark:border-amber-800 hover:bg-amber-100'
                            : 'bg-slate-50 dark:bg-slate-800 text-slate-600 dark:text-slate-300 border-slate-300 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-700'
                        }`}
                        title="Quyền đọc tài liệu công nợ, tài chính của khách"
                        aria-pressed={Boolean(u.can_view_finance)}
                      >
                        {u.can_view_finance ? (
                          <>
                            <Wallet className="w-4 h-4" />
                            <span>Xem được công nợ</span>
                          </>
                        ) : (
                          <>
                            <WalletMinimal className="w-4 h-4 text-slate-400" />
                            <span>Không xem công nợ</span>
                          </>
                        )}
                      </button>
                    )}
                  </div>
                 </div>

                  {/* Bảng sửa tài khoản — mở/đóng bằng nút Sửa */}
                  {editingId === u.id && (
                    <UserEditPanel
                      user={u}
                      departments={departments}
                      clients={clients}
                      isSelf={currentUser?.id === u.id}
                      showToast={showToast}
                      onCancel={() => setEditingId(null)}
                      onSaved={async () => {
                        setEditingId(null);
                        await fetchAll();
                        reloadUsers().catch(() => {});
                      }}
                    />
                  )}

                  {/* Khoá API / mật khẩu tạm vừa cấp — hiện đúng một lần, backend chỉ giữ bản băm */}
                  {secret?.uid === u.id && (
                    <div className="mt-3 p-3 bg-amber-50 dark:bg-amber-950/40 border border-amber-300 dark:border-amber-800 rounded-xl space-y-2">
                      <p className="text-[11px] font-bold text-amber-900 dark:text-amber-200 flex items-center gap-1.5">
                        <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
                        {secret.kind === 'password'
                          ? `Mật khẩu tạm của ${secret.who} — chép ngay, không hiển thị lại lần nào nữa`
                          : 'Sao chép ngay — khoá này không hiển thị lại lần nào nữa'}
                      </p>
                      <code className="block bg-white dark:bg-slate-900 border border-amber-200 dark:border-amber-900 rounded-lg p-2.5 font-mono text-[13px] tracking-wide text-slate-900 dark:text-slate-100 break-all select-all">
                        {secret.value}
                      </code>
                      <div className="flex flex-wrap items-center gap-2">
                        <button
                          onClick={() => {
                            navigator.clipboard
                              ?.writeText(secret.value)
                              .then(() =>
                                showToast(
                                  secret.kind === 'password' ? 'Đã sao chép mật khẩu tạm.' : 'Đã sao chép khoá API.',
                                  'success'
                                )
                              )
                              .catch(() => showToast('Không sao chép được, hãy chọn và copy tay.', 'error'));
                          }}
                          className="px-2.5 py-1 bg-hds-navy hover:bg-hds-navy-light text-white text-[11px] font-bold rounded-lg inline-flex items-center gap-1 transition-colors"
                        >
                          <Copy className="w-3 h-3" />
                          Sao chép
                        </button>
                        <button
                          onClick={() => setSecret(null)}
                          className="px-2.5 py-1 bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-300 border border-slate-300 dark:border-slate-700 text-[11px] font-semibold rounded-lg transition-colors"
                        >
                          Tôi đã lưu, ẩn đi
                        </button>
                      </div>
                      <p className="text-[10px] text-amber-800 dark:text-amber-300 leading-relaxed">
                        {secret.kind === 'password' ? (
                          <>
                            Gửi riêng cho đúng người (không gửi vào nhóm chung). Lần đăng nhập
                            đầu, hệ thống bắt họ đặt mật khẩu mới rồi mới cho làm việc.
                          </>
                        ) : (
                          <>
                            Khách gửi khoá này ở header{' '}
                            <code className="font-mono font-semibold">X-API-Key</code> khi gọi{' '}
                            <code className="font-mono font-semibold">POST /chat/portal</code>. Phạm
                            vi dữ liệu giống hệt khi đăng nhập web.
                          </>
                        )}
                      </p>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
};
