/**
 * constants.ts — Nguồn dữ liệu chuẩn cho các giá trị enum của hệ thống.
 *
 * Mọi giá trị dưới đây phải khớp tuyệt đối với ràng buộc CHECK trong
 * `hds-ai/sql/schema.sql` và bảng `DOC_TYPE_VN` trong `hds-ai/app/rag.py`.
 * Gửi sai giá trị sẽ làm backend trả 500 do vi phạm CHECK constraint.
 */
import type { UserRole } from './types';

/* --------------------------------------------------------------
   Loại tài liệu — schema.sql: documents.doc_type CHECK (...)
-------------------------------------------------------------- */
export const DOC_TYPES = [
  { value: 'law', label: 'Văn bản luật' },
  { value: 'ban_an', label: 'Bản án' },
  { value: 'an_le', label: 'Án lệ' },
  { value: 'mau_hd', label: 'Mẫu hợp đồng' },
  { value: 'contract', label: 'Hợp đồng' },
  { value: 'advisory', label: 'Thư tư vấn' },
  { value: 'filing', label: 'Hồ sơ nộp' },
  { value: 'nhan_hieu', label: 'Data nhãn hiệu' },
  { value: 'thu_mau', label: 'Thư mẫu' },
  { value: 'quy_trinh', label: 'Quy trình' },
  { value: 'ho_so_ns', label: 'Hồ sơ nhân sự' },
  { value: 'ho_so_kh', label: 'Hồ sơ khách hàng' },
  { value: 'cong_no', label: 'Công nợ - Tài chính' },
  { value: 'other', label: 'Khác' },
] as const;

export const DOC_TYPE_LABELS: Record<string, string> = Object.fromEntries(
  DOC_TYPES.map((d) => [d.value, d.label])
);

/* --------------------------------------------------------------
   Mức truy cập — schema.sql chỉ cho phép 3 giá trị.
   (Bản cũ có 'senior_only' — giá trị này KHÔNG tồn tại, đã bỏ.)
-------------------------------------------------------------- */
export const ACCESS_LEVELS = [
  {
    value: 'public',
    label: 'Công khai',
    hint: 'Ai cũng tra cứu được, kể cả kênh hỏi đáp công khai.',
  },
  {
    value: 'internal',
    label: 'Nội bộ toàn công ty',
    hint: 'Chỉ 5 vai nội bộ của HDS đọc được.',
  },
  {
    value: 'client',
    label: 'Hồ sơ khách hàng',
    hint: 'Bắt buộc chọn khách hàng. Chỉ Ban QT và người cùng phòng mở được.',
  },
] as const;

export const ACCESS_LEVEL_BADGES: Record<string, { label: string; badge: string }> = {
  public: {
    label: 'Công khai',
    badge:
      'bg-emerald-100 text-emerald-800 border-emerald-300 dark:bg-emerald-950 dark:text-emerald-300 dark:border-emerald-800',
  },
  internal: {
    label: 'Nội bộ',
    badge:
      'bg-blue-100 text-blue-800 border-blue-300 dark:bg-blue-950 dark:text-blue-300 dark:border-blue-800',
  },
  client: {
    label: 'Hồ sơ khách',
    badge:
      'bg-purple-100 text-purple-800 border-purple-300 dark:bg-purple-950 dark:text-purple-300 dark:border-purple-800',
  },
};

/* --------------------------------------------------------------
   Nguồn nạp tài liệu — schema.sql: documents.source_kind CHECK (...)
-------------------------------------------------------------- */
export const SOURCE_KIND_BADGES: Record<string, { label: string; badge: string }> = {
  drive: {
    label: 'Google Drive',
    badge:
      'bg-sky-100 text-sky-800 border-sky-300 dark:bg-sky-950 dark:text-sky-300 dark:border-sky-800',
  },
  manual: {
    label: 'Nhập tay',
    badge:
      'bg-slate-100 text-slate-700 border-slate-300 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-700',
  },
  chat: {
    label: 'Từ hội thoại',
    badge:
      'bg-indigo-100 text-indigo-800 border-indigo-300 dark:bg-indigo-950 dark:text-indigo-300 dark:border-indigo-800',
  },
  web: {
    label: 'Tải lên web',
    badge:
      'bg-amber-100 text-amber-800 border-amber-300 dark:bg-amber-950 dark:text-amber-300 dark:border-amber-800',
  },
};

/* --------------------------------------------------------------
   Trạng thái vụ việc — schema.sql: matters.status CHECK (...)
-------------------------------------------------------------- */
export const MATTER_STATUS_BADGES: Record<string, { label: string; badge: string }> = {
  tiep_nhan: {
    label: 'Mới tiếp nhận',
    badge:
      'bg-blue-100 text-blue-800 border-blue-300 dark:bg-blue-950 dark:text-blue-300 dark:border-blue-800',
  },
  dang_xu_ly: {
    label: 'Đang xử lý',
    badge:
      'bg-emerald-100 text-emerald-800 border-emerald-300 dark:bg-emerald-950 dark:text-emerald-300 dark:border-emerald-800',
  },
  tam_dung: {
    label: 'Tạm dừng',
    badge:
      'bg-amber-100 text-amber-800 border-amber-300 dark:bg-amber-950 dark:text-amber-300 dark:border-amber-800',
  },
  hoan_thanh: {
    label: 'Hoàn thành',
    badge:
      'bg-slate-100 text-slate-700 border-slate-300 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-700',
  },
};

/* --------------------------------------------------------------
   Vai người dùng — schema.sql: users.role CHECK (...)
-------------------------------------------------------------- */
export const ROLE_META: Record<UserRole, { label: string; short: string; badge: string }> = {
  admin: {
    label: 'Quản trị hệ thống',
    short: 'Admin',
    badge:
      'bg-red-100 text-red-800 border-red-300 dark:bg-red-950 dark:text-red-300 dark:border-red-800',
  },
  ban_qt: {
    label: 'Ban Quản trị',
    short: 'Ban QT',
    badge:
      'bg-purple-100 text-purple-800 border-purple-300 dark:bg-purple-950 dark:text-purple-300 dark:border-purple-800',
  },
  truong_bph: {
    label: 'Trưởng bộ phận',
    short: 'Trưởng BPh',
    badge:
      'bg-amber-100 text-amber-800 border-amber-300 dark:bg-amber-950 dark:text-amber-300 dark:border-amber-800',
  },
  chuyen_vien: {
    label: 'Chuyên viên',
    short: 'Chuyên viên',
    badge:
      'bg-blue-100 text-blue-800 border-blue-300 dark:bg-blue-950 dark:text-blue-300 dark:border-blue-800',
  },
  tro_ly: {
    label: 'Trợ lý',
    short: 'Trợ lý',
    badge:
      'bg-emerald-100 text-emerald-800 border-emerald-300 dark:bg-emerald-950 dark:text-emerald-300 dark:border-emerald-800',
  },
  client_free: {
    label: 'Khách — gói Free',
    short: 'Khách Free',
    badge:
      'bg-slate-100 text-slate-700 border-slate-300 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-700',
  },
  client_plus: {
    label: 'Khách — gói Plus',
    short: 'Khách Plus',
    badge:
      'bg-indigo-100 text-indigo-800 border-indigo-300 dark:bg-indigo-950 dark:text-indigo-300 dark:border-indigo-800',
  },
  client_pro: {
    label: 'Khách — gói Pro',
    short: 'Khách Pro',
    badge:
      'bg-rose-100 text-rose-800 border-rose-300 dark:bg-rose-950 dark:text-rose-300 dark:border-rose-800',
  },
};

export const INTERNAL_ROLES: UserRole[] = [
  'admin',
  'ban_qt',
  'truong_bph',
  'chuyen_vien',
  'tro_ly',
];

export const isClientRole = (role?: string): boolean =>
  Boolean(role && role.startsWith('client_'));

/** Ai được mở khu Quản trị (khớp require_reviewer / require(admin) ở api.py). */
export const canAccessAdmin = (user?: { role?: string; can_review?: boolean } | null): boolean =>
  Boolean(user && (user.role === 'admin' || user.role === 'ban_qt' || user.can_review));
