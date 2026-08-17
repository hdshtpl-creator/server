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
  DriveSyncStatus,
  MatterAlerts,
  ModelInfo,
  BenchmarkResult,
  ChatSearchHit,
  ChatStreamEvent,
  ConversationSummary,
  Note,
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

/** Được gọi khi api.js tự rơi về chế độ giả lập vì không kết nối được backend. */
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
}) => Promise<ChatResponse>;

export const chatStream = ApiJs.chatStream as (
  params: {
    question: string;
    conversation_id?: number | null;
    use_temp?: boolean;
    use_method?: boolean;
    model?: string;
  },
  onEvent: (evt: ChatStreamEvent) => void
) => Promise<ChatStreamEvent | null>;

export const chatPortal = ApiJs.chatPortal as (params: {
  question: string;
  conversation_id?: number | null;
}) => Promise<ChatResponse>;

export const getChatHistory = ApiJs.getChatHistory as (
  conversationId?: number | null,
  limit?: number
) => Promise<{ conversation_id: number | null; messages: ChatSearchHit[] }>;

export const listConversations = ApiJs.listConversations as (
  limit?: number
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

export const uploadFile = ApiJs.uploadFile as (params: {
  conversation_id?: number | null;
  filename: string;
  content: string;
  mode: 'temp' | 'save';
}) => Promise<{ ok?: boolean; mode?: string; chunks?: number; note?: string }>;

export const getStats = ApiJs.getStats as () => Promise<Stats>;

export const getPendingReviews = ApiJs.getPendingReviews as () => Promise<PendingReviewDoc[]>;

export const approveReview = ApiJs.approveReview as (
  id: number,
  data: { doc_type: string; access_level: string; client_id?: number | string | null }
) => Promise<{ ok?: boolean; document_id?: number }>;

export const getPendingLearns = ApiJs.getPendingLearns as () => Promise<PendingLearnMessage[]>;

export const reviewLearnMessage = ApiJs.reviewLearnMessage as (
  message_id: number,
  data: { action: 'approve' | 'edit' | 'reject'; edited_content?: string; edit_reason?: string }
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
