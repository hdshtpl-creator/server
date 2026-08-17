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

/** Model AI trên máy chủ, cho nút chọn model trong Cài đặt AI. */
export interface ModelInfo {
  ollama: boolean;
  /** Tên mọi model Ollama đã cài trên server. */
  available: string[];
  /** Chỉ model SINH câu trả lời (đã loại model tạo vector) — cho bộ chọn ô chat. */
  generation?: string[];
  /** Model đang nằm sẵn trong bộ nhớ — chọn nó thì không mất thời gian nạp. */
  loaded?: string[];
  /** Model đang dùng để sinh câu trả lời (rỗng nếu theo mặc định .env). */
  current: string | null;
  /** Model đang chọn có thật sự tồn tại trên server không. */
  current_ready: boolean;
  /** Model tạo vector — cố định, đổi là hỏng tra cứu. Chỉ hiển thị. */
  embed_model: string | null;
  embed_ready: boolean;
}

/** Kết quả đo tốc độ máy chủ — nói lên PHẦN CỨNG khoẻ tới đâu. */
export interface BenchmarkResult {
  ok: boolean;
  error?: string;
  model?: string;
  prompt_tokens?: number;
  gen_tokens?: number;
  load_ms?: number;
  prefill_ms?: number;
  gen_ms?: number;
  total_ms?: number;
  /** Tốc độ ĐỌC ngữ cảnh (token/giây) — quyết định phần lớn thời gian chờ. */
  read_tok_s?: number | null;
  /** Tốc độ VIẾT câu trả lời (token/giây). */
  write_tok_s?: number | null;
  /** Ước tính thời gian một lượt hỏi điển hình với cài đặt hiện tại (giây). */
  uoc_tinh_giay?: number;
}

/** Một vụ việc cần chú ý, tính trực tiếp từ view v_matter_alerts. */
export interface MatterAlert {
  matter_id: number;
  matter_code: string | null;
  matter_title: string;
  matter_type: string | null;
  status: string;
  deadline: string | null;
  /** Số ngày còn lại; âm là đã quá hạn; null khi chưa đặt hạn. */
  days_left: number | null;
  client_id: number;
  client_name: string;
  client_code: string | null;
  kind: 'qua_han' | 'den_han_gap' | 'den_han_gan' | 'thieu_han' | 'treo_lau';
  kind_label: string;
  severity: 'gap' | 'luu_y';
  last_doc_at: string | null;
}

export interface MatterAlerts {
  total: number;
  /** Số vụ ở mức gấp: đã quá hạn hoặc còn không quá 7 ngày. */
  urgent: number;
  items: MatterAlert[];
}

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
  /** Cờ trong CSDL: admin đã cấp quyền xem công nợ cho người này chưa. */
  can_view_finance?: boolean;
  /** Quyền xem công nợ có hiệu lực (admin luôn có, người khác phải được cấp). */
  can_finance?: boolean;
  /** Tài khoản khách này đã được cấp khoá API chưa. Backend không trả khoá. */
  has_api_key?: boolean;
  /** Ngày cấp khoá API gần nhất. */
  api_key_at?: string | null;
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

/**
 * Thời gian từng chặng của một lượt trả lời — để biết chậm ở đâu.
 * `prefill_ms` (đọc prompt) và `gen_ms` (viết câu trả lời) do Ollama báo về.
 */
export interface ChatTimings {
  /** Tra cứu vector trong kho tài liệu. */
  tim_kiem_ms?: number;
  /** Rút dữ liệu khách/vụ việc/nhân sự bằng SQL. */
  du_lieu_cong_ty_ms?: number;
  /** Tổng thời gian gọi model. */
  ai_ms?: number;
  /** Nạp model từ ổ cứng vào bộ nhớ (0 nếu model đã nằm sẵn). */
  load_ms?: number;
  /** Đọc prompt — tỉ lệ thuận với độ dài ngữ cảnh. */
  prefill_ms?: number;
  /** Sinh câu trả lời. */
  gen_ms?: number;
  prompt_tokens?: number;
  gen_tokens?: number;
  num_ctx?: number;
  model?: string;
  /** Số đoạn tài liệu thực sự đưa vào prompt. */
  so_doan?: number;
  /** Số đoạn bị loại vì điểm liên quan thấp. */
  bo_qua_doan_yeu?: number;
}

export interface ChatResponse {
  answer: string;
  sources: Source[];
  conversation_id: number;
  latency_ms: number;
  message_id?: number;
  timings?: ChatTimings;
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
  /** Phân tích thời gian, hiện khi bấm vào đồng hồ cạnh câu trả lời. */
  timings?: ChatTimings;
  /** Đang chảy chữ về — hiện con trỏ nhấp nháy, ẩn các nút thao tác. */
  isStreaming?: boolean;
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

/** Một sự kiện trên dòng trả lời chảy dần (/chat/stream). */
export interface ChatStreamEvent {
  type: 'start' | 'meta' | 'delta' | 'done' | 'error';
  conversation_id?: number;
  sources?: Source[];
  used_method?: string | null;
  /** Mẩu chữ mới, chỉ có ở type 'delta'. */
  text?: string;
  message_id?: number;
  latency_ms?: number;
  timings?: ChatTimings;
  quota?: { used: number; limit: number };
  message?: string;
}

/** Kết quả tìm trong lịch sử chat của chính mình. */
export interface ChatSearchHit {
  id: number;
  role: 'user' | 'assistant';
  content: string;
  created_at: string;
}

/** Ghi chú cá nhân trong khung chat. */
export interface Note {
  id: number;
  content: string;
  source_message_id?: number | null;
  created_at: string;
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
  /** Ghi chú người dùng viết khi bấm báo cáo — vì sao câu trả lời chưa ổn. */
  note?: string | null;
  /** Tên người báo cáo. */
  reporter?: string | null;
  /** Số lượt báo cáo cho cùng câu trả lời này. */
  report_count?: number;
  reported_at?: string | null;
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

export interface DriveSyncItem {
  name: string;
  location: string;
  doc_type?: string;
  access_level?: string;
  reason?: string;
  error?: string;
}

export interface DriveSyncCounts {
  scanned: number;
  new: number;
  updated: number;
  unchanged: number;
  unmapped: number;
  bad_format: number;
  errors: number;
}

export interface DriveSyncRun {
  folder_id: string;
  started_at: string;
  finished_at: string | null;
  finished: boolean;
  counts: DriveSyncCounts;
  new_items: DriveSyncItem[];
  updated_items: DriveSyncItem[];
  skipped_items: DriveSyncItem[];
  error_items: DriveSyncItem[];
}

export interface DriveSyncStatus {
  configured: boolean;
  last_run: DriveSyncRun | null;
}
