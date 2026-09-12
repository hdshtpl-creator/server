/**
 * api.ts — Cầu nối có kiểu cho `api.js`.
 * Logic thật nằm ở api.js; file này chỉ khai báo chữ ký để TypeScript kiểm tra.
 */
import * as ApiJs from './api.js';
import type {
  ChatResponse,
  Stats,
  PendingReviewDoc,
  PendingLearnMessage,
  MethodTemplate,
  User,
  LearnedDocument,
  BrowseDocument,
  Client,
  Client360Data,
  Department,
  AppSettings,
  FeedbackItem,
  UploadResult,
  KhoTang,
  KhoKetQuaTim,
  KhoHocKetQua,
  KhoTaiLenKetQua,
  DriveSyncStatus,
  MatterAlerts,
  ModelInfo,
  BenchmarkResult,
  ChatSearchHit,
  ChatStreamEvent,
  ConversationSummary,
  Note,
  DraftDocument,
  DraftCreateInput,
  DraftTemplate,
  DocumentDetail,
} from './types';

export const setUserId = ApiJs.setUserId as (id: string | number) => void;
export const getUserId = ApiJs.getUserId as () => string;
export const setAccessToken = ApiJs.setAccessToken as (token: string) => void;
export const getAccessToken = ApiJs.getAccessToken as () => string;
export const setApiBaseUrl = ApiJs.setApiBaseUrl as (url: string) => void;
export const getApiBaseUrl = ApiJs.getApiBaseUrl as () => string;
export const getDefaultApiBaseUrl = ApiJs.getDefaultApiBaseUrl as () => string;
export const setUseMockMode = ApiJs.setUseMockMode as (enabled: boolean) => void;
export const getUseMockMode = ApiJs.getUseMockMode as () => boolean;

/** Báo lỗi kết nối; api.js không tự chuyển sang dữ liệu giả lập. */
export const onMockFallback = ApiJs.onMockFallback as (
  listener: ((baseUrl: string) => void) | null
) => void;

/** Ép về số nguyên hợp lệ, ngược lại null. */
export const toIntOrNull = ApiJs.toIntOrNull as (value: unknown) => number | null;

export const login = ApiJs.login as (params: {
  email: string;
  password?: string;
}) => Promise<{ access_token: string; token_type: string; user: User }>;

export const getMe = ApiJs.getMe as () => Promise<User>;

export const changePassword = ApiJs.changePassword as (params: {
  old_password: string;
  new_password: string;
}) => Promise<{ ok?: boolean; message?: string }>;

export const chatInternal = ApiJs.chatInternal as (params: {
  question: string;
  conversation_id?: number | null;
  use_temp?: boolean;
  use_method?: boolean;
  /** '' = mặc định máy chủ | 'auto' | tên model cụ thể */
  model?: string;
  source_document_ids?: number[];
}) => Promise<ChatResponse>;

export const chatStream = ApiJs.chatStream as (
  params: {
    question: string;
    conversation_id?: number | null;
    use_temp?: boolean;
    use_method?: boolean;
    model?: string;
    source_document_ids?: number[];
    /** Tab "Kiểm tra pháp lý": 'legal_review' — chỉ vai nội bộ. */
    mode?: 'legal_review' | 'template_check' | null;
    /** Điền chủ thể vào file mẫu này (kệ HỢP ĐỒNG MẪU / THƯ MẪU). */
    template_doc_id?: number | null;
    /** "Tạo bộ file": AI tự lên danh sách văn bản cần soạn từ hồ sơ đính kèm. */
    make_files?: boolean;
    /** Nút "Dừng" của giao diện. Huỷ signal là đóng kết nối, và chính việc
     *  đóng kết nối báo cho máy chủ ngừng sinh chữ (xem rag.answer_stream). */
    signal?: AbortSignal;
  },
  onEvent: (evt: ChatStreamEvent) => void
) => Promise<ChatStreamEvent | null>;

/** Mã lỗi ném ra khi lượt bị NGƯỜI DÙNG bấm "Dừng" — không phải sự cố. */
export const DUNG_BOI_NGUOI_DUNG: string = ApiJs.DUNG_BOI_NGUOI_DUNG;

export const createConversation = ApiJs.createConversation as (
  kind?: 'chat' | 'legal'
) => Promise<{ conversation_id: number; kind?: string }>;

/** Đuôi file máy chủ đọc được cho ô đính kèm — nguồn sự thật là máy chủ. */
export const getUploadFormats = ApiJs.getUploadFormats as () => Promise<{
  extensions: string[];
  max_mb: number;
}>;

export const uploadExtract = ApiJs.uploadExtract as (params: {
  conversation_id: number;
  file: File;
}) => Promise<{
  ok?: boolean;
  mode?: string;
  filename?: string;
  chunks?: number;
  /** Id bản ghi file tạm — để gỡ thật qua DELETE /temp-files/{id}. */
  temp_file_id?: number;
  warnings?: string[];
  status?: 'ok' | 'warning' | string;
  text_chars?: number;
  note?: string;
}>;

export const getConversationTempFiles = ApiJs.getConversationTempFiles as (
  convId: number
) => Promise<{ items: Array<{ id: number; filename: string; chunks: number }> }>;

export const deleteTempFile = ApiJs.deleteTempFile as (
  tempFileId: number
) => Promise<{ ok?: boolean; note?: string }>;

export const listTemplateFiles = ApiJs.listTemplateFiles as () => Promise<{
  items: import('./types').TemplateFile[];
}>;

export const previewDocument = ApiJs.previewDocument as (
  docId: number
) => Promise<void>;

export const downloadTemplateFill = ApiJs.downloadTemplateFill as (
  token: string,
  filename?: string
) => Promise<void>;

export const chatPortal = ApiJs.chatPortal as (params: {
  question: string;
  conversation_id?: number | null;
}) => Promise<ChatResponse>;

export const getChatHistory = ApiJs.getChatHistory as (
  conversationId?: number | null,
  limit?: number
) => Promise<{ conversation_id: number | null; messages: ChatSearchHit[] }>;

export const listConversations = ApiJs.listConversations as (
  limit?: number,
  kind?: 'chat' | 'legal' | 'all'
) => Promise<ConversationSummary[]>;

export const renameConversation = ApiJs.renameConversation as (
  convId: number,
  title: string
) => Promise<{ ok?: boolean; id?: number; title?: string }>;

export const deleteConversation = ApiJs.deleteConversation as (
  convId: number
) => Promise<{ ok?: boolean; id?: number }>;

export const searchChat = ApiJs.searchChat as (
  q: string,
  limit?: number
) => Promise<ChatSearchHit[]>;

export const getNotes = ApiJs.getNotes as (limit?: number) => Promise<Note[]>;

export const addNote = ApiJs.addNote as (params: {
  content: string;
  source_message_id?: number | null;
}) => Promise<Note & { ok?: boolean }>;

export const deleteNote = ApiJs.deleteNote as (
  noteId: number
) => Promise<{ ok?: boolean; id?: number }>;

export const getStats = ApiJs.getStats as () => Promise<Stats>;

export const getPendingReviews = ApiJs.getPendingReviews as () => Promise<PendingReviewDoc[]>;

export const approveReview = ApiJs.approveReview as (
  id: number,
  data: {
    doc_type: string;
    access_level: string;
    client_id?: number | string | null;
    /* Danh tính văn bản pháp lý — không gửi = giữ giá trị máy bóc. */
    so_hieu?: string | null;
    loai_van_ban?: string | null;
    trich_yeu?: string | null;
    ngay_ban_hanh?: string | null;
    ngay_hieu_luc?: string | null;
    trang_thai_hieu_luc?: string | null;
  }
) => Promise<{ ok?: boolean; document_id?: number }>;

/** Nội dung trích xuất để người duyệt soát/sửa trước khi duyệt (PDF bắt buộc). */
export const getReviewContent = ApiJs.getReviewContent as (id: number) => Promise<{
  document_id: number;
  title: string;
  doc_type: string;
  extraction_status: string | null;
  extraction_warning: string | null;
  approved: boolean;
  label_verified: boolean;
  client_name: string | null;
  chunk_count: number;
  content: string;
}>;

/** Lưu nội dung đã sửa — backend chia đoạn và tạo vector lại. */
export const saveReviewContent = ApiJs.saveReviewContent as (
  id: number,
  content: string
) => Promise<{
  ok?: boolean;
  document_id?: number;
  chunks?: number;
  /** Danh tính bóc LẠI từ bản vừa sửa — form duyệt phải nạp đè giá trị cũ. */
  van_ban?: {
    so_hieu: string | null;
    loai_van_ban: string | null;
    trich_yeu: string | null;
    ngay_ban_hanh: string | null;
    ngay_hieu_luc: string | null;
    trang_thai_hieu_luc: string | null;
  };
}>;

export const getPendingLearns = ApiJs.getPendingLearns as () => Promise<PendingLearnMessage[]>;

export const reviewLearnMessage = ApiJs.reviewLearnMessage as (
  message_id: number,
  data: {
    action: 'approve' | 'edit' | 'reject';
    edited_content?: string;
    edit_reason?: string;
    access_level?: 'internal' | 'public';
  }
) => Promise<{ ok?: boolean; action?: string; document_id?: number }>;

export const getMethods = ApiJs.getMethods as () => Promise<MethodTemplate[]>;
export const getMethodTemplates = ApiJs.getMethodTemplates as () => Promise<MethodTemplate[]>;

export const createMethod = ApiJs.createMethod as (data: {
  case_type: string;
  steps: string | string[];
}) => Promise<{ ok?: boolean; method_id?: number } & Partial<MethodTemplate>>;

export const getUsers = ApiJs.getUsers as () => Promise<User[]>;

export const createUser = ApiJs.createUser as (data: {
  email: string;
  full_name: string;
  role: string;
  can_review: boolean;
  client_id?: number | string | null;
  department_ids?: number[];
  head_of?: number[];
  monthly_quota?: number;
}) => Promise<User & { ok?: boolean; user_id?: number }>;

export const updateUserReviewPermission = ApiJs.updateUserReviewPermission as (
  uid: number,
  grant: boolean
) => Promise<{ ok?: boolean; user_id?: number; can_review?: boolean }>;

export const updateUserFinancePermission = ApiJs.updateUserFinancePermission as (
  uid: number,
  grant: boolean
) => Promise<{ ok?: boolean; user_id?: number; can_view_finance?: boolean }>;

export const issueApiKey = ApiJs.issueApiKey as (
  uid: number
) => Promise<{ ok?: boolean; user_id?: number; api_key: string; note?: string }>;

export const revokeApiKey = ApiJs.revokeApiKey as (
  uid: number
) => Promise<{ ok?: boolean; user_id?: number }>;

export const getDocuments = ApiJs.getDocuments as (params?: {
  q?: string;
  doc_type?: string;
  limit?: number;
}) => Promise<LearnedDocument[]>;

export const getBrowseDocuments = ApiJs.getBrowseDocuments as (params?: {
  q?: string;
}) => Promise<BrowseDocument[]>;

export const getDocumentDetail = ApiJs.getDocumentDetail as (
  docId: number
) => Promise<DocumentDetail>;

export const addDocumentRelation = ApiJs.addDocumentRelation as (
  docId: number,
  data: { loai: string; so_hieu_dich?: string | null; ten_dich?: string | null; ghi_chu?: string | null }
) => Promise<{ ok: boolean; id: number }>;

export const deleteDocumentRelation = ApiJs.deleteDocumentRelation as (
  docId: number,
  relId: number
) => Promise<{ ok: boolean }>;

export const updateDocumentVanBan = ApiJs.updateDocumentVanBan as (
  docId: number,
  meta: {
    so_hieu?: string | null;
    loai_van_ban?: string | null;
    trich_yeu?: string | null;
    ngay_ban_hanh?: string | null;
    ngay_hieu_luc?: string | null;
    trang_thai_hieu_luc?: string | null;
  }
) => Promise<{ ok: boolean; document_id: number }>;

export const getClients = ApiJs.getClients as () => Promise<Client[]>;

export const getClient360 = ApiJs.getClient360 as (clientId: number) => Promise<Client360Data>;

export const updateClientProfile = ApiJs.updateClientProfile as (
  clientId: number,
  data: { history_note?: string; issues_note?: string; warnings?: string; suggestions?: string }
) => Promise<{ ok?: boolean; client_id?: number }>;

export const getDepartments = ApiJs.getDepartments as () => Promise<Department[]>;

export const getMatterAlerts = ApiJs.getMatterAlerts as (
  limit?: number
) => Promise<MatterAlerts>;

// ---------- Cài đặt AI ----------
export const getSettings = ApiJs.getSettings as () => Promise<AppSettings>;

export const updateSetting = ApiJs.updateSetting as (
  key: string,
  value: string
) => Promise<{ ok?: boolean; key?: string }>;

export const resetSetting = ApiJs.resetSetting as (
  key: string
) => Promise<{ ok?: boolean; key?: string; value?: string }>;

export const getDriveSyncStatus = ApiJs.getDriveSyncStatus as () => Promise<DriveSyncStatus>;

export const getModels = ApiJs.getModels as () => Promise<ModelInfo>;

export const benchmarkModel = ApiJs.benchmarkModel as (
  model?: string
) => Promise<BenchmarkResult>;

// ---------- Báo cáo chất lượng ----------
export const sendFeedback = ApiJs.sendFeedback as (params: {
  message_id: number;
  rating: 'good' | 'bad';
  note?: string;
}) => Promise<{ ok?: boolean; feedback_id?: number }>;

export const retractFeedback = ApiJs.retractFeedback as (
  feedbackId: number
) => Promise<{ ok?: boolean; id?: number }>;

export const getFeedbackPending = ApiJs.getFeedbackPending as () => Promise<FeedbackItem[]>;

export const reviewFeedback = ApiJs.reviewFeedback as (
  fid: number,
  data: {
    action: 'apply' | 'reject';
    corrected_answer?: string;
    admin_note?: string;
    access_level?: string;
  }
) => Promise<{ ok?: boolean; feedback_id?: number; action?: string; document_id?: number }>;

// ---------- Soạn tài liệu ----------
export const listDrafts = ApiJs.listDrafts as () => Promise<DraftDocument[]>;

export const listDraftTemplates = ApiJs.listDraftTemplates as () => Promise<DraftTemplate[]>;

export const getDraft = ApiJs.getDraft as (draftId: number) => Promise<DraftDocument>;

export const createDraft = ApiJs.createDraft as (
  data: DraftCreateInput
) => Promise<DraftDocument & { ok?: boolean; draft_id?: number }>;

export const generateDraft = ApiJs.generateDraft as (
  draftId: number,
  data?: { instructions?: string }
) => Promise<DraftDocument & { ok?: boolean }>;

export const reviseDraft = ApiJs.reviseDraft as (
  draftId: number,
  data: {
    instructions?: string;
    content_markdown?: string;
    source_document_ids?: number[];
    input_data?: Record<string, unknown>;
    model?: string;
    change_note?: string;
  }
) => Promise<DraftDocument & { ok?: boolean }>;

export const approveDraft = ApiJs.approveDraft as (
  draftId: number,
  data?: { note?: string; allow_placeholders?: boolean; confirm_needs_review?: boolean }
) => Promise<DraftDocument & { ok?: boolean }>;

export const exportDraft = ApiJs.exportDraft as (
  draftId: number,
  filename?: string,
  format?: 'docx' | 'pdf' | 'md'
) => Promise<void>;

/** Bóc thông tin cá nhân từ MỘT hồ sơ (CCCD/sơ yếu/CV — PDF, ảnh, DOCX) để
 *  điền sẵn input_data của bản nháp. File dùng xong bỏ, không vào kho. */
export const autofillDraft = ApiJs.autofillDraft as (file: File) => Promise<{
  ok: boolean;
  fields: Record<string, string>;
  field_labels: Record<string, string>;
  warnings: string[];
  method: string;
  text_chars: number;
}>;

// ---------- Tệp ----------
export const uploadDocument = ApiJs.uploadDocument as (params: {
  file: File;
  doc_type?: string;
  access_level?: string;
  client_id?: number | null;
  matter_id?: number | null;
  department_id?: number | null;
  auto_approve?: boolean;
  onProgress?: (percent: number) => void;
}) => Promise<UploadResult>;

export const downloadDocument = ApiJs.downloadDocument as (
  docId: number,
  filename?: string
) => Promise<void>;

/* ---------- Cây thư mục kho (Tổng quan) ---------- */
export const getKhoTang = ApiJs.getKhoTang as (params?: {
  path?: string;
  q?: string;
  offset?: number;
  limit?: number;
}) => Promise<KhoTang>;

export const timTrongKho = ApiJs.timTrongKho as (q: string) => Promise<KhoKetQuaTim[]>;

export const goTaiLieuKho = ApiJs.goTaiLieuKho as (
  documentId: number
) => Promise<{ ok: boolean; document_id: number; title?: string; da_chuyen_toi: string | null }>;

export const hocFileKho = ApiJs.hocFileKho as (params: {
  path: string;
  auto_approve?: boolean;
}) => Promise<KhoHocKetQua>;

export const quetKho = ApiJs.quetKho as () => Promise<{ ok: boolean; pid: number; started_at: string }>;

export const taoThuMucKho = ApiJs.taoThuMucKho as (params: {
  path?: string;
  ten: string;
}) => Promise<{ ok: boolean; path: string; ten: string }>;

export const taiLenKho = ApiJs.taiLenKho as (params: {
  path: string;
  files: File[] | FileList;
  auto_approve?: boolean;
  onProgress?: (percent: number) => void;
}) => Promise<KhoTaiLenKetQua>;
