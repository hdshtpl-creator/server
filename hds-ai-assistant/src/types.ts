/**
 * types.ts — Hình dạng dữ liệu trao đổi với backend hds-ai (FastAPI).
 * Mọi khoá ngoại (client_id, conversation_id, document_id...) đều là số nguyên
 * theo đúng schema PostgreSQL.
 */

export type UserRole =
  | 'admin'
  | 'ban_qt'
  | 'truong_bph'
  | 'chuyen_vien'
  | 'tro_ly'
  | 'client_free'
  | 'client_plus'
  | 'client_pro';

export interface User {
  id: number;
  email?: string;
  /** GET /auth/me trả về trường `name`; api.js đã chuẩn hoá về `full_name`. */
  full_name: string;
  role: UserRole;
  can_review: boolean;
  active?: boolean;
  client_id?: number | null;
  department_ids?: number[];
  head_of?: number[];
  monthly_quota?: number;
  used_this_month?: number;
  /** true với vai admin / ban_qt — được xem toàn bộ phòng ban. */
  is_banqt?: boolean;
}

export interface Stats {
  tai_lieu: number;
  da_duyet_nhan: number;
  cho_duyet_nhan: number;
  thieu_chu_so_huu: number;
  so_doan: number;
  hoi_thoai_cho_duyet: number;
  da_hoc: number;
  so_mau_phuong_phap: number;
  so_khach: number;
  vu_viec_dang_mo: number;
  so_bo_phan: number;
  bao_cao_cho_xu_ly?: number;
}

export interface Source {
  title: string;
  relevance_score?: number;
  doc_id?: string | number;
  snippet?: string;
}

export interface ChatResponse {
  answer: string;
  sources: Source[];
  conversation_id: number;
  latency_ms: number;
  message_id?: number;
  /** Chỉ có ở /chat/portal — hạn mức câu hỏi theo gói của khách. */
  quota?: { used: number; limit: number };
}

export interface ChatMessage {
  id: string;
  sender: 'user' | 'ai';
  text: string;
  sources?: Source[];
  timestamp: string;
  latency_ms?: number;
  used_temp_file?: string;
  used_method?: boolean;
  isError?: boolean;
  /** Mã tin nhắn do backend cấp — cần để gửi báo cáo chất lượng. */
  serverMessageId?: number;
}

export interface Conversation {
  id: string;
  title: string;
  created_at: string;
  messages: ChatMessage[];
  /**
   * Mã hội thoại do backend cấp (số nguyên). Chỉ có sau lần hỏi đầu tiên.
   * `id` phía trên là mã cục bộ của trình duyệt, KHÔNG được gửi lên server.
   */
  server_id?: number;
  temp_file?: {
    filename: string;
    content: string;
  };
}

export interface PendingReviewDoc {
  id: number;
  title: string;
  doc_type: string | null;
  access_level: string;
  client_id: number | null;
  client_name?: string | null;
  /** AI có thể chưa chấm điểm → null. */
  confidence: number | null;
  source_kind: string;
  preview: string | null;
}

export interface PendingLearnMessage {
  message_id: number;
  question: string | null;
  answer: string;
  created_at: string;
}

export interface MethodTemplate {
  id: number;
  case_type: string;
  /** Cột TEXT ở backend — mỗi bước một dòng. */
  steps: string | string[];
  approved: boolean;
}

export interface LearnedDocument {
  id: number;
  title: string;
  doc_type: string;
  access_level: string;
  summary: string;
  source_kind: string;
  created_at: string;
  client_name?: string | null;
  so_doan: number;
}

export interface BrowseDocument {
  id: number;
  title: string;
  can_open: boolean;
  doc_type?: string;
  access_level?: string;
  department?: string | null;
  /** Bị ẩn (null) khi người dùng không có quyền mở tài liệu. */
  summary?: string | null;
  created_at?: string;
}

export interface Client {
  id: number;
  name: string;
  code: string;
  department?: string | null;
}

export interface ClientProfile {
  history: string | null;
  issues: string | null;
  warnings: string | null;
  suggestions: string | null;
}

export interface ClientMatter {
  id: number;
  code?: string | null;
  title: string;
  /** schema.sql: 'tiep_nhan' | 'dang_xu_ly' | 'tam_dung' | 'hoan_thanh' */
  status: string;
  type?: string | null;
  matter_type?: string | null;
  deadline?: string | null;
  opened_at?: string | null;
}

export interface ClientDocument {
  id: number;
  title: string;
  doc_type: string;
  summary?: string | null;
  created_at: string;
  matter_id?: number | null;
}

export interface Client360Data {
  client: Client;
  profile: ClientProfile;
  matters: ClientMatter[];
  documents: ClientDocument[];
}

export interface Department {
  id: number;
  code: string;
  name: string;
}

export interface AppSettings {
  settings: Record<string, string>;
  editable_keys: string[];
  defaults: Record<string, string>;
}

export interface FeedbackItem {
  id: number;
  message_id: number;
  rating: 'good' | 'bad';
  note: string | null;
  created_at: string;
  reporter: string | null;
  reporter_role: string;
  question: string | null;
  answer: string;
}

export interface UploadResult {
  ok?: boolean;
  document_id?: number;
  filename?: string;
  bytes?: number;
  note?: string;
}
