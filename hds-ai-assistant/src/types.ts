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
  /** Model gọi qua API ngoài, đã cấu hình khoá. Rỗng = chưa cấu hình. */
  cloud?: string[];
  /** Admin đã bật nhánh API ngoài chưa. Chưa bật thì chọn cũng tự về local. */
  cloud_enabled?: boolean;
  /** Model API dùng khi chọn "Cloud" ở ô chat. */
  cloud_model?: string | null;
  /** Kênh được phép gọi API, phân tách bằng dấu phẩy. */
  cloud_channels?: string | null;
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
  /** Con số ước tính dựa trên bao nhiêu token đọc vào / viết ra. */
  uoc_tinh_dien_giai?: string;
  /** Mức xấu nhất khi answer_review='auto' và lượt bot đọc lại có chạy. */
  uoc_tinh_giay_toi_da?: number;
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
  /** Điểm do backend trả về; tương đương relevance_score. */
  score?: number;
  /** Số thứ tự [Nguồn n] đã dùng trong câu trả lời. */
  n?: number;
  /** Mã tài liệu trong CSDL — để tải bản gốc qua /files/{id}/download. */
  document_id?: number | null;
  /** ID file trên Google Drive — để mở bản gốc trên Drive (kiểu NotebookLM). */
  drive_file_id?: string | null;
  doc_id?: string | number;
  chunk_id?: number | string;
  snippet?: string;
  /** Vị trí bằng chứng chính xác nếu pipeline trích xuất giữ được. */
  page?: number | string | null;
  page_number?: number | string | null;
  section?: string | null;
  section_title?: string | null;
  quote?: string | null;
  excerpt?: string | null;
  citation_key?: string | null;
  document_title?: string | null;
  source_locator?: string | null;
  source_version?: number | string | null;
  semantic_score?: number;
  lexical_score?: number;
  /* Danh tính + hiệu lực văn bản pháp lý (31/08/2026). Optional hết:
     tin nhắn cũ trong lịch sử là snapshot JSONB không có các trường này. */
  so_hieu?: string | null;
  loai_van_ban?: string | null;
  trich_yeu?: string | null;
  ngay_ban_hanh?: string | null;
  ngay_hieu_luc?: string | null;
  trang_thai_hieu_luc?: string | null;
  /** Tên văn bản đã thay thế/sửa đổi văn bản này (nếu có trong kho). */
  thay_the_boi?: string | null;
  /** document (kho) · attachment (file đính kèm) · user_provided (dán vào chat)
   *  · notice (lời nhắn cho model, không hiện) · system (dữ liệu vận hành). */
  kind?: string;
  /** Tên file đính kèm — các đoạn cùng tên gom thành một thẻ trong panel nguồn. */
  attachment_name?: string | null;
  /** Đoạn này là bản tóm tắt cả file (file dài), không phải trích nguyên văn. */
  is_summary?: boolean;
}

export type GroundingStatus = 'grounded' | 'partial' | 'uncited' | 'insufficient' | string;

/**
 * Thời gian từng chặng của một lượt trả lời — để biết chậm ở đâu.
 * `prefill_ms` (đọc prompt) và `gen_ms` (viết câu trả lời) do Ollama báo về.
 */
export interface ChatTimings {
  cai_dat_ms?: number;
  lich_su_ms?: number;
  du_lieu_cau_truc_ms?: number;
  embed_ms?: number;
  embed_load_ms?: number;
  embed_total_ms?: number;
  vector_db_ms?: number;
  chon_model_ms?: number;
  chuan_bi_ms?: number;
  tong_ms?: number;
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
  search_question?: string;
}

export interface ChatResponse {
  answer: string;
  sources: Source[];
  conversation_id: number;
  latency_ms: number;
  end_to_end_ms?: number;
  message_id?: number;
  timings?: ChatTimings;
  /** Chỉ có ở /chat/portal — hạn mức câu hỏi theo gói của khách. */
  quota?: { used: number; limit: number };
  grounding_status?: GroundingStatus;
  answer_mode?: string;
}

export interface ChatMessage {
  id: string;
  sender: 'user' | 'ai';
  text: string;
  sources?: Source[];
  timestamp: string;
  latency_ms?: number;
  /** Tên các file đính kèm mà lượt hỏi này đọc được. */
  used_temp_files?: string[];
  used_method?: boolean;
  isError?: boolean;
  /** Mã tin nhắn do backend cấp — cần để gửi báo cáo chất lượng. */
  serverMessageId?: number;
  /** Phân tích thời gian, hiện khi bấm vào đồng hồ cạnh câu trả lời. */
  timings?: ChatTimings;
  /** Đang chảy chữ về — hiện con trỏ nhấp nháy, ẩn các nút thao tác. */
  isStreaming?: boolean;
  /** Mốc tiến trình đang chạy ("Đang tìm trong kho tài liệu…") — chỉ hiện khi
   *  isStreaming, để máy chậm không giống bị treo (kiểu ChatGPT/NotebookLM). */
  statusLabel?: string;
  /** Trạng thái kiểm chứng sau khi model viết xong. */
  grounding_status?: GroundingStatus;
  answer_mode?: string;
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
  /** File đang đính kèm trong hội thoại này (nhiều file, như Claude/ChatGPT). */
  attachments?: TempAttachment[];
}

/**
 * Một file người dùng đính kèm vào hội thoại. Máy chủ đã trích văn bản/OCR
 * xong; ở đây chỉ giữ phần để hiện chip và gỡ đúng bản ghi.
 *
 * KHÔNG giữ nội dung file trong state trình duyệt: nội dung nằm ở máy chủ
 * (bảng temp_files) và bot đọc thẳng từ đó — kéo cả hồ sơ khách vào bộ nhớ
 * tab chỉ để hiện một cái chip là thừa và rủi ro.
 */
export interface TempAttachment {
  /** Mốc bắt đầu đọc (Date.now()). Chip đếm giây từ đây — OCR một bản scan
   *  mất hàng phút, chip đứng im nhìn y hệt bị treo. */
  startedAt?: number;
  /** Id bản ghi temp_files trên máy chủ — để nút × gỡ THẬT, không chỉ ẩn chip.
   *  null khi file còn đang tải lên (chip tạm). */
  id: number | null;
  filename: string;
  /** Số đoạn máy chủ cắt được; 0 khi chip còn đang tải. */
  chunks: number;
  /** 'uploading' = đang gửi | 'ok' = đọc sạch | 'warning' = scan/đọc thiếu. */
  status: string;
  /** Máy chủ nói rõ đọc file gặp vấn đề gì — hiện nguyên văn cho người dùng. */
  warnings: string[];
  /** Số ký tự đọc được — con số nhỏ bất thường là dấu hiệu bản scan mờ. */
  textChars: number;
}

/** Một sự kiện trên dòng trả lời chảy dần (/chat/stream). */
export interface ChatStreamEvent {
  type: 'start' | 'meta' | 'status' | 'delta' | 'replace' | 'done' | 'error';
  conversation_id?: number;
  sources?: Source[];
  used_method?: string | null;
  /** Mẩu chữ mới, chỉ có ở type 'delta'. */
  text?: string;
  /** Mốc tiến trình đang chạy, chỉ có ở type 'status'. */
  label?: string;
  message_id?: number;
  latency_ms?: number;
  timings?: ChatTimings;
  quota?: { used: number; limit: number };
  message?: string;
  grounding_status?: GroundingStatus;
  answer_mode?: string;
}

/** Một file trong kệ mẫu (HỢP ĐỒNG MẪU / THƯ MẪU - BIỂU MẪU) — GET /templates/files. */
export interface TemplateFile {
  id: number;
  title: string;
  doc_type: 'mau_hd' | 'thu_mau' | string;
  /** Tên thư mục cha trong kho tài liệu trên máy chủ. */
  folder: string;
  /** Chỉ file .docx còn tệp gốc mới điền tự động được. */
  fillable: boolean;
}

/** Một file .docx mẫu trong BỘ MẪU HỒ SƠ — GET /bo-mau. */
export interface BoMauFile {
  id: number;
  ten_file: string;
  thu_tu: number;
  /** Các chỗ trống {{…}} quét sẵn lúc tải lên (nguyên văn). */
  placeholders: string[];
  so_placeholder: number;
  so_ky_tu: number;
}

/** Bộ mẫu hồ sơ: nhóm .docx mẫu đi cùng nhau, AI điền cả bộ trong một lượt chat. */
export interface BoMau {
  id: number;
  ten: string;
  mo_ta: string;
  /** null = cả công ty dùng được; có giá trị = chỉ phòng đó (+ Ban QT/admin). */
  department_id: number | null;
  active: boolean;
  created_at: string | null;
  so_file: number;
  files: BoMauFile[];
}

export interface BoMauListResponse {
  items: BoMau[];
  max_bo: number;
  max_file_moi_bo: number;
  /** Người đang đăng nhập có quyền tạo/sửa/xoá bộ (admin hoặc can_review). */
  co_quyen_sua: boolean;
}

/** Một ô thông tin của bộ (chỗ trống {{…}} đã gộp trùng theo khoá). */
export interface BoMauChoTrong {
  khoa: string;
  literal: string;
  /** Nhãn trích từ file mẫu để biết ô này là gì ("Tên công ty"). */
  goi_y: string;
  /** Mục của phiếu chứa ô này ("A. THÔNG TIN DOANH NGHIỆP") — để gom nhóm. */
  muc?: string;
  files: string[];
  so_lan?: number;
}

export interface BoMauChoTrongResponse {
  bo: { id: number; ten: string };
  items: BoMauChoTrong[];
  loi_mau: Array<{ ten_file: string; loi: string }>;
  so_file: number;
}

/** Một file kết quả sau khi điền cả bộ. token = chỗ tải/xem nhanh (24 giờ). */
export interface BoMauFileDaDien {
  file_id: number;
  ten_file: string;
  ten_ket_qua: string | null;
  token: string | null;
  so_thay: number;
  da_dien: Array<{ literal: string; gia_tri: string; so_cho: number; nguon: string }>;
  con_trong: string[];
  loi: string | null;
}

export interface BoMauDienResult {
  bo: { id: number; ten: string };
  files: BoMauFileDaDien[];
  /** Gói .zip cả bộ (chỉ có khi từ 2 file trở lên). */
  zip_token: string | null;
  so_o: number;
  da_dien: Array<{ khoa: string; literal: string; gia_tri: string; nguon: string }>;
  con_thieu: BoMauChoTrong[];
  /** Từng file tải lên đã được đọc theo cách nào. */
  doc_file: Array<{ ten_file: string; cach: string; so_o: number; loi: string | null;
                    mau?: string }>;
  loi_mau: Array<{ ten_file: string; loi: string }>;
  loi_tai_len?: Array<{ ten_file: string; loi: string }>;
  gia_tri_thua: number;
  ghi_chu_ai: string;
}

export interface BoMauUploadResult {
  ok: boolean;
  ket_qua: Array<{
    ok: boolean;
    id?: number;
    ten_file: string;
    so_placeholder?: number;
    placeholders?: string[];
    loi?: string;
  }>;
}

export type DraftStatus =
  | 'draft'
  | 'generating'
  | 'generated'
  | 'needs_review'
  | 'approved'
  | 'failed'
  | string;

/** Bản nháp do module Soạn tài liệu quản lý. Các khoá tuỳ chọn giúp
 * frontend tương thích với bản backend cũ trong lúc triển khai cuốn chiếu. */
export interface DraftDocument {
  id: number;
  title: string;
  draft_type?: string;
  document_type?: string;
  template_id?: number | null;
  template_name?: string | null;
  department_id?: number | null;
  status: DraftStatus;
  instructions?: string | null;
  content?: string | null;
  content_markdown?: string | null;
  current_version?: number;
  grounding_status?: GroundingStatus;
  placeholder_count?: number;
  client_id?: number | null;
  client_name?: string | null;
  matter_id?: number | null;
  matter_title?: string | null;
  source_document_ids?: number[];
  sources?: Source[];
  missing_fields?: string[];
  created_at?: string;
  updated_at?: string;
  approved_at?: string | null;
  /** id người tạo — giao diện dựa vào đây để chỉ chìa nút xoá cho đúng người. */
  created_by?: number;
  creator_name?: string | null;
  error?: string | null;
  versions?: DraftVersion[];
  latest_version?: DraftVersion | null;
  source_documents?: Array<{ id: number; title: string; doc_type?: string }>;
}

export interface DraftVersion {
  id?: number;
  version_no: number;
  content_markdown: string;
  change_note?: string | null;
  model_used?: string | null;
  grounding_status?: GroundingStatus;
  placeholder_count?: number;
  evidence_snapshot?: Source[];
  evidence?: Source[];
  created_at?: string;
}

export interface DraftTemplate {
  id: number;
  code: string;
  name: string;
  document_type: string;
  description?: string | null;
  body_template?: string;
  required_fields?: Array<
    | string
    | { key?: string; name?: string; label?: string; required?: boolean; placeholder?: string }
  >;
}

export interface DraftCreateInput {
  title: string;
  document_type: string;
  draft_type?: string;
  template_id?: number | null;
  instructions?: string;
  client_id?: number | null;
  matter_id?: number | null;
  department_id?: number | null;
  input_data?: Record<string, unknown>;
  source_document_ids?: number[];
}

/** Một hội thoại trong danh sách bên trái (mô hình ChatGPT). */
export interface ConversationSummary {
  id: number;
  title: string;
  updated_at: string;
  message_count: number;
}

/** Kết quả tìm trong lịch sử chat của chính mình. */
export interface ChatSearchHit {
  id: number;
  role: 'user' | 'assistant';
  content: string;
  created_at: string;
  /** Hội thoại chứa đoạn này — để mở đúng hội thoại rồi nhảy tới. */
  conversation_id?: number;
  conversation_title?: string;
  sources?: Source[];
  evidence?: Source[];
  grounding_status?: GroundingStatus;
  answer_mode?: string;
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
  /* Metadata máy bóc sẵn — form duyệt điền trước cho người soát/sửa. */
  so_hieu?: string | null;
  loai_van_ban?: string | null;
  trich_yeu?: string | null;
  ngay_ban_hanh?: string | null;
  ngay_hieu_luc?: string | null;
  trang_thai_hieu_luc?: string | null;
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
  so_hieu?: string | null;
  loai_van_ban?: string | null;
  trich_yeu?: string | null;
  trang_thai_hieu_luc?: string | null;
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
  so_hieu?: string | null;
  loai_van_ban?: string | null;
  trich_yeu?: string | null;
  trang_thai_hieu_luc?: string | null;
}

/** Một dòng quan hệ văn bản (GET /documents/{id}/detail). */
export interface DocRelation {
  id: number;
  loai: string;
  loai_vn: string;
  nguon: 'auto' | 'manual';
  ghi_chu?: string | null;
  so_hieu_nguon: string;
  ten_nguon?: string | null;
  so_hieu_dich?: string | null;
  ten_dich?: string | null;
  /** null = văn bản đối ứng chưa có trong kho. */
  document_id?: number | null;
  title?: string | null;
  can_open: boolean;
  trang_thai_hieu_luc?: string | null;
}

/** Thẻ căn cước tài liệu + văn bản liên quan hai chiều. */
export interface DocumentDetail {
  id: number;
  title: string;
  doc_type: string;
  access_level: string;
  client_name?: string | null;
  department?: string | null;
  summary?: string | null;
  source_kind: string;
  created_at: string;
  so_hieu?: string | null;
  loai_van_ban?: string | null;
  trich_yeu?: string | null;
  ten_day_du: string;
  ngay_ban_hanh?: string | null;
  ngay_hieu_luc?: string | null;
  trang_thai_hieu_luc?: string | null;
  extraction_status?: string | null;
  /** Tỉ lệ token đọc lỗi (0-1) do lượt duyệt hàng loạt chấm; null = chưa chấm. */
  ty_le_rac?: number | null;
  so_doan: number;
  can_open: boolean;
  /** Văn bản này nói về ai (thay thế/sửa đổi/căn cứ văn bản nào). */
  quan_he_xuoi: DocRelation[];
  /** Ai nói về nó (bị ai thay thế/sửa đổi/hướng dẫn). */
  quan_he_nguoc: DocRelation[];
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
  /** Còn tệp gốc trên máy chủ → mới bật được nút Xem / Tải về. */
  has_file?: boolean;
  /** Cùng cửa quyền với /files/{id}/download; false thì tên đã bị che. */
  can_open?: boolean;
  access_level?: string | null;
  department_id?: number | null;
  department_name?: string | null;
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
  /** 'unsupported_format' = đuôi file chưa hỗ trợ (khác hẳn với chưa xác định
   *  được nhãn: file đúng chỗ nhưng bot không đọc nổi định dạng). */
  code?: string;
  /** Chỉ có ở danh sách "không còn tệp" — để IT tra đúng bản ghi. */
  document_id?: number;
}

export interface DriveSyncCounts {
  scanned: number;
  new: number;
  updated: number;
  unchanged: number;
  unmapped: number;
  bad_format: number;
  errors: number;
  /** Chỉ có ở chế độ quét thư mục: file đổi tên / chuyển thư mục. */
  moved?: number;
  /** Tài liệu còn trong kho tri thức nhưng không còn tệp trong thư mục. */
  missing?: number;
  /** Tài liệu đang phục vụ vừa rơi lại hàng chờ duyệt. */
  unapproved?: number;
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
  /** Bộ quét Drive không phát ra hai mục này — để tuỳ chọn. */
  missing_items?: DriveSyncItem[];
  unapproved_items?: DriveSyncItem[];
}

/** Một tài liệu có trong Drive nhưng chưa học được, còn tồn qua nhiều lần quét. */
export interface IngestFailure {
  id: number;
  file_name: string;
  location: string | null;
  error_code: string;
  error_message: string | null;
  hint: string | null;
  attempts: number;
  first_seen_at: string;
  last_seen_at: string;
  drive_file_id: string | null;
}

export interface DriveSyncStatus {
  configured: boolean;
  /** 'local' = quét thư mục trên máy chủ (mặc định từ 27/08/2026); 'drive' = Google Drive. */
  source?: 'local' | 'drive' | string;
  /** Đường dẫn thư mục kho, chỉ có ở chế độ local. */
  library_root?: string | null;
  last_run: DriveSyncRun | null;
  /** Lỗi tích luỹ, KHÁC last_run.error_items vốn chỉ là ảnh chụp lần quét cuối. */
  failures: IngestFailure[];
  /** Lượt quét đang chạy / kết quả lượt bấm "Quét lại" gần nhất (POST /kho/quet). */
  quet?: KhoQuetTrangThai | null;
}

export interface KhoQuetKetThuc {
  started_at?: string | null;
  finished_at?: string | null;
  /** 0 = xong bình thường; khác 0 = bộ quét dừng vì chốt an toàn hoặc lỗi. */
  ma_thoat: number;
  log_tail: string[];
}

/** Nhịp học tài liệu cho thẻ theo dõi trên Tổng quan (GET /kho/tien-do). */
export interface TienDoHoc {
  quet: KhoQuetTrangThai;
  /** Số tài liệu HỌC MỚI trong từng khoảng thời gian. */
  nhip: { phut_10: number; gio_1: number; hom_nay: number; cap_nhat_gio_1: number };
  tong: { tai_lieu: number; cho_duyet: number; loi?: number };
  /** Học thêm được bao nhiêu kể từ lúc lượt quét đang chạy bắt đầu. */
  tu_luc_quet: number | null;
  lan_cuoi: {
    finished_at?: string | null;
    started_at?: string | null;
    quet: number;
    moi: number;
    cap_nhat: number;
    khong_doi: number;
    loi: number;
  } | null;
}

export interface KhoQuetTrangThai {
  dang_chay: boolean;
  started_at?: string | null;
  pid?: number | null;
  /** 'web' = bấm từ giao diện; 'ngoai' = ai đó chạy từ SSH. */
  nguon?: 'web' | 'ngoai' | null;
  log_tail?: string[];
  ket_thuc?: KhoQuetKetThuc | null;
}

/* --------------------------------------------------------------
   Cây thư mục kho trên máy chủ — GET /kho/cay, /kho/tim (app/kho.py).
   Trạng thái từng file suy từ bản ghi documents theo đúng luật của bộ quét.
-------------------------------------------------------------- */
export type KhoTrangThai =
  | 'da_hoc'
  | 'canh_bao'
  | 'cho_duyet'
  | 'chua_hoc'
  | 'loi'
  | 'khong_ho_tro';

export interface KhoThuMuc {
  ten: string;
  /** Đường dẫn tương đối trong kho, dấu / xuôi. */
  path: string;
  /** Số file trên đĩa (đệ quy), kể cả file chưa học. */
  so_file: number;
  da_hoc: number;
  cho_duyet: number;
  tong_ban_ghi: number;
}

export interface KhoLoiHoc {
  code?: string | null;
  message?: string | null;
  hint?: string | null;
}

export interface KhoTapTin {
  ten: string;
  path: string;
  kich_thuoc: number;
  sua_luc: string;
  trang_thai: KhoTrangThai;
  document_id: number | null;
  title: string | null;
  doc_type: string | null;
  access_level: string | null;
  so_hieu: string | null;
  client_name: string | null;
  so_doan: number | null;
  loi: KhoLoiHoc | null;
}

export interface KhoTang {
  path: string;
  ten: string;
  root: string;
  thu_muc: KhoThuMuc[];
  tap_tin: KhoTapTin[];
  tong_tap_tin: number;
  offset: number;
  limit: number;
}

/* Thư mục hồ sơ khách nhìn từ phía đĩa (18/09/2026): mỗi thư mục khách một
   dòng kể cả trống, số tệp theo nhãn học, và từng tệp khi mở dòng. */
export type KhoTinhTrangKhach =
  | 'trong'
  | 'bo_qua'
  | 'khong_doc_duoc'
  | 'chua_hoc'
  | 'cho_duyet'
  | 'mot_phan'
  | 'da_hoc';

export interface KhoDemTrangThai {
  da_hoc: number;
  canh_bao: number;
  cho_duyet: number;
  chua_hoc: number;
  loi: number;
  khong_ho_tro: number;
}

export interface KhoThuMucKhach {
  ten: string;
  /** Đường dẫn tương đối trong kho, dấu / xuôi. */
  path: string;
  /** Mã khách tách từ tên thư mục ('1729. Tên' → '1729'); null = không tách được. */
  ma: string | null;
  ten_khach: string | null;
  /** Có bản ghi khách trong hệ thống chưa (chỉ sinh khi đã học ≥ 1 tệp). */
  client_id: number | null;
  client_name: string | null;
  /** Lý do bộ quét bỏ qua cả thư mục; null = thư mục hợp lệ. */
  ly_do: string | null;
  so_file: number;
  dem: KhoDemTrangThai;
  tinh_trang: KhoTinhTrangKhach;
}

export interface KhoDanhSachKhach {
  /** Các ngăn 'Hồ sơ khách hàng' ở gốc kho. */
  goc: string[];
  tong: {
    tong_thu_muc: number;
    tong_tep: number;
    theo_tinh_trang: Record<KhoTinhTrangKhach, number>;
    dem: KhoDemTrangThai;
  };
  thu_muc: KhoThuMucKhach[];
  tong_khop: number;
  offset: number;
  limit: number;
}

export interface KhoTepKhach extends KhoTapTin {
  /** Thư mục con (trong thư mục khách) chứa tệp; '' = nằm ngay trong thư mục khách. */
  thu_muc_con: string;
}

export interface KhoTepTrongThuMucKhach extends KhoThuMucKhach {
  tap_tin: KhoTepKhach[];
  so_thu_muc_con: number;
}

export interface KhoKetQuaTim {
  document_id: number;
  title: string;
  doc_type: string;
  access_level: string;
  so_hieu: string | null;
  client_name: string | null;
  /** null khi tài liệu không có file trong kho (nạp từ hội thoại). */
  path: string | null;
  thu_muc: string;
  ten: string | null;
  trang_thai: KhoTrangThai;
}

export interface KhoHocKetQua {
  ok: boolean;
  document_id?: number;
  title?: string;
  trang_thai?: KhoTrangThai;
  warnings?: string[];
  note?: string;
  filename?: string;
  bytes?: number;
  path?: string;
  /** Lý do khi ok=false. */
  loi?: string;
  /** File đã nằm trong kho dù học hỏng — bộ quét sẽ thử lại. */
  da_luu?: boolean;
}

export interface KhoTaiLenKetQua {
  ok: boolean;
  ket_qua: KhoHocKetQua[];
}

// ===================== HOÀN THIỆN GIAI ĐOẠN 1 (15/09/2026) =====================

/** Một mảnh trong đoạn đã so sánh mức từ (app/so_sanh.py). */
export interface SoSanhPhan {
  op: 'equal' | 'delete' | 'insert';
  text: string;
}
export interface SoSanhDoan {
  op: 'equal' | 'delete' | 'insert' | 'replace';
  cu: string | null;
  moi: string | null;
  phan: SoSanhPhan[];
}
export interface SoSanhKetQua {
  tu: number;
  den: number;
  doan: SoSanhDoan[];
  thong_ke: {
    them: number;
    xoa: number;
    doan_them: number;
    doan_xoa: number;
    doan_sua: number;
    giong_nhau: number;
  };
  tom_tat: string;
}

/** Một mục trong kết quả kiểm tra mâu thuẫn pháp lý (app/kiem_tra_mau_thuan.py). */
export interface DraftCheckItem {
  loai: string;
  trich?: string;
  vi_tri?: string | null;
  gia_tri?: number | null;
  don_vi?: string | null;
  ket_luan: 'hop_le' | 'canh_bao' | 'khong_ro' | string;
  ly_do?: string;
  can_cu?: string;
  phuong_phap?: string;
  noi_dung?: string;
  nguon?: Array<{ document_id?: number; chunk_id?: number; title?: string }>;
}
export interface DraftCheck {
  version_no: number;
  status: 'running' | 'done' | 'error' | string;
  ket_luan: 'hop_le' | 'canh_bao' | 'khong_ro' | null;
  so_canh_bao: number;
  so_muc: number;
  phuong_phap?: string | null;
  items: DraftCheckItem[];
  error?: string | null;
  started_at?: string;
  finished_at?: string | null;
}

/** Khách để lại liên hệ từ khung chat nhúng website. */
export interface Lead {
  id: number;
  name: string;
  phone?: string | null;
  email?: string | null;
  need?: string | null;
  status: 'moi' | 'da_lien_he' | 'bo_qua' | string;
  note?: string | null;
  source?: string | null;
  conversation_id?: number | null;
  created_at: string;
  handled_at?: string | null;
  handled_by_name?: string | null;
}
export interface LeadsResponse {
  items: Lead[];
  counts: Record<string, number>;
  statuses: Record<string, string>;
}

/** Một dòng nhật ký hệ thống (audit_log — chỉ đọc). */
export interface AuditEntry {
  id: number;
  user_id: number | null;
  user_name?: string | null;
  user_email?: string | null;
  action: string;
  entity?: string | null;
  entity_id?: number | null;
  detail: Record<string, unknown>;
  created_at: string;
  tom_tat: string;
}
export interface AuditResponse {
  items: AuditEntry[];
  total: number;
  limit: number;
  offset: number;
}

/** Phiên bản nội dung của một tài liệu kho (document_versions). */
export interface DocumentVersion {
  version_no: number;
  edit_reason?: string | null;
  edit_reason_label?: string;
  edit_note?: string | null;
  created_at: string;
  edited_by_name?: string;
  characters?: number;
}

/** Kết quả rà soát rủi ro theo danh mục điều khoản (app/ra_soat_rui_ro.py). */
export interface RaSoatMuc {
  ma: string;
  ten: string;
  trang_thai: 'dat' | 'canh_bao' | 'thieu' | string;
  dieu_khoan?: string | null;
  trich?: string | null;
  giai_thich?: string;
  de_xuat?: string;
  can_cu?: string;
  can_cu_kho?: Array<{ document_id?: number; title?: string; so_hieu?: string | null; trich?: string }>;
}
export interface RaSoatKetQua {
  loai: string;
  ten_loai: string;
  do_tin_cay: number;
  so_dieu_khoan: number;
  muc: RaSoatMuc[];
  tong_ket: { dat: number; canh_bao: number; thieu: number; muc_rui_ro: 'thap' | 'trung_binh' | 'cao' | string };
  tieu_de?: string;
  so_ky_tu?: number;
  thoi_gian_ms?: number;
}
export interface RaSoatLoai {
  ma: string;
  ten: string;
  so_dieu_khoan: number;
  so_nguong: number;
}
