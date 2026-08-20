// src/api.js
// Module API tập trung cho frontend HDS AI.
// Tự động đính kèm Authorization: Bearer <token> cho mọi request.
//
// Backend tham chiếu: hds-ai/app/api.py (FastAPI).
// LƯU Ý QUAN TRỌNG VỀ KIỂU DỮ LIỆU — backend dùng Pydantic nên sai kiểu là 422:
//   - conversation_id : int | None   (KHÔNG phải chuỗi 'conv-...')
//   - client_id       : int | None   (KHÔNG phải mã chữ 'CLI-8821')
//   - doc_id / uid    : int
//   - methods.steps   : str          (cột TEXT, không phải mảng)

// Địa chỉ backend mặc định.
//   - Khi dev: không đặt gì -> 'http://localhost:8000'.
//   - Khi build production (deploy một máy chủ): đặt VITE_API_BASE_URL=/api
//     trong .env.production; nginx sẽ reverse-proxy /api sang FastAPI cùng origin,
//     nhờ vậy KHÔNG cần CORS và KHÔNG dính mixed-content.
// Vite thay import.meta.env.VITE_API_BASE_URL bằng hằng số lúc build.
const DEFAULT_API_BASE_URL = String(
  import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
).replace(/\/$/, '');

let currentUserId = '1';
let accessToken = localStorage.getItem('hds_access_token') || '';
let apiBaseUrl = DEFAULT_API_BASE_URL;
let useMockBackend = false;

/** Địa chỉ backend mặc định lúc build (dùng làm giá trị khởi tạo cho context). */
export function getDefaultApiBaseUrl() {
  return DEFAULT_API_BASE_URL;
}

export function setUserId(userId) {
  currentUserId = String(userId);
}

export function getUserId() {
  return currentUserId;
}

export function setAccessToken(token) {
  accessToken = token || '';
  if (token) {
    localStorage.setItem('hds_access_token', token);
  } else {
    localStorage.removeItem('hds_access_token');
  }
}

export function getAccessToken() {
  return accessToken;
}

export function setApiBaseUrl(url) {
  apiBaseUrl = String(url || '').replace(/\/$/, '');
}

export function getApiBaseUrl() {
  return apiBaseUrl;
}

export function setUseMockMode(enabled) {
  useMockBackend = Boolean(enabled);
}

export function getUseMockMode() {
  return useMockBackend;
}

/**
 * Hook tương thích ngược. Mock Mode chỉ được bật bằng thao tác tường minh
 * của người dùng; lỗi mạng không bao giờ được phép đổi dữ liệu thật sang dữ
 * liệu mẫu. Giữ API này để không làm hỏng các bản giao diện cũ.
 */
let fallbackListener = null;
export function onMockFallback(listener) {
  fallbackListener = typeof listener === 'function' ? listener : null;
}

// ==================== TIỆN ÍCH ====================

/** Ép về số nguyên hợp lệ, ngược lại trả null. Dùng cho mọi id gửi lên backend. */
export function toIntOrNull(value) {
  if (value === null || value === undefined || value === '') return null;
  const n = Number(value);
  return Number.isFinite(n) && Number.isInteger(n) ? n : null;
}

/**
 * Bóc thông điệp lỗi của FastAPI.
 * FastAPI trả {"detail": "..."} hoặc {"detail":[{loc,msg,...}]} cho lỗi 422.
 * Nếu không bóc được thì mới hiện nguyên văn — tránh đập raw JSON vào mặt người dùng.
 */
function parseErrorBody(rawText, status) {
  if (!rawText) return `Lỗi máy chủ (${status})`;
  try {
    const data = JSON.parse(rawText);
    const detail = data.detail ?? data.message ?? data.error;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) {
      const msgs = detail
        .map((d) => {
          const field = Array.isArray(d.loc) ? d.loc[d.loc.length - 1] : '';
          return field ? `${field}: ${d.msg}` : d.msg;
        })
        .filter(Boolean);
      if (msgs.length) return `Dữ liệu gửi lên không hợp lệ — ${msgs.join('; ')}`;
    }
    if (detail) return String(detail);
  } catch {
    // không phải JSON — dùng nguyên văn bên dưới
  }
  return rawText.length > 300 ? `Lỗi máy chủ (${status})` : rawText;
}

/**
 * Chuẩn hoá đối tượng người dùng.
 * GET /auth/me trả về {id, role, name, can_review, is_banqt, dept_ids}
 * còn GET /users trả {id, email, full_name, role, can_review, active}.
 * Frontend dùng chung một hình dạng nên phải ánh xạ lại, nếu không header
 * sẽ hiện trống sau khi đăng nhập.
 */
export function normalizeUser(u) {
  if (!u || typeof u !== 'object') return u;
  return {
    ...u,
    full_name: u.full_name ?? u.name ?? '',
    department_ids: u.department_ids ?? u.dept_ids ?? [],
  };
}

// Lớp bọc fetch
async function request(endpoint, options = {}) {
  const headers = {
    'Content-Type': 'application/json',
    'X-User-Id': currentUserId,
    ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
    ...(options.headers || {}),
  };

  const url = `${apiBaseUrl}${endpoint}`;

  if (useMockBackend) {
    return handleMockRequest(endpoint, options, headers);
  }

  let response;
  try {
    response = await fetch(url, { ...options, headers });
  } catch (err) {
    console.error(`[HDS AI] Không kết nối được ${url}.`, err);
    if (fallbackListener) fallbackListener(apiBaseUrl);
    throw new Error(
      `Không kết nối được backend tại ${apiBaseUrl}. ` +
        'Dữ liệu giả lập không được tự động sử dụng; hãy kiểm tra máy chủ hoặc CORS.'
    );
  }

  if (!response.ok) {
    const rawText = await response.text().catch(() => '');
    const detail = parseErrorBody(rawText, response.status);

    if (response.status === 401) throw new Error(detail || 'Phiên đăng nhập đã hết hạn (401)');
    if (response.status === 403) throw new Error(detail || 'Tài khoản không đủ quyền (403)');
    if (response.status === 429) throw new Error(detail || 'Đã hết lượt hỏi trong tháng (429)');
    throw new Error(detail);
  }

  if (response.status === 204) return null;
  return response.json();
}

// ==================== 0. XÁC THỰC ====================

// POST /auth/login {email, password}
export async function login({ email, password }) {
  const data = await request('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  });
  if (data && data.access_token) {
    setAccessToken(data.access_token);
    if (data.user && data.user.id) {
      setUserId(data.user.id);
      data.user = normalizeUser(data.user);
    }
  }
  return data;
}

// GET /auth/me
export async function getMe() {
  return normalizeUser(await request('/auth/me', { method: 'GET' }));
}

// POST /auth/change-password
export async function changePassword({ old_password, new_password }) {
  return request('/auth/change-password', {
    method: 'POST',
    body: JSON.stringify({ old_password, new_password }),
  });
}

// ==================== 1. HỘI THOẠI ====================

// POST /chat/internal — conversation_id phải là số hoặc bỏ hẳn
export async function chatInternal({
  question,
  conversation_id,
  use_temp,
  use_method,
  model,
  source_document_ids,
}) {
  return request('/chat/internal', {
    method: 'POST',
    body: JSON.stringify({
      question,
      conversation_id: toIntOrNull(conversation_id),
      use_temp: Boolean(use_temp),
      use_method: Boolean(use_method),
      model: model || undefined,
      source_document_ids: Array.isArray(source_document_ids) && source_document_ids.length
        ? source_document_ids.map(toIntOrNull).filter((id) => id !== null)
        : undefined,
    }),
  });
}

/**
 * POST /chat/stream — hỏi và nhận câu trả lời CHẢY DẦN (Server-Sent Events).
 *
 * Dùng cho cả nhân viên nội bộ lẫn khách đã đăng nhập; máy chủ tự chọn kênh
 * theo vai của tài khoản. `onEvent` được gọi cho từng sự kiện:
 *   {type:'start', conversation_id}      mở dòng
 *   {type:'meta',  sources}              nguồn trích dẫn, biết trước khi viết
 *   {type:'delta', text}                 một mẩu chữ
 *   {type:'done',  message_id, timings}  viết xong, đã lưu
 *   {type:'error', message}              lỗi giữa chừng
 *
 * Trả về sự kiện 'done' cuối cùng để nơi gọi dùng tiếp.
 */
export async function chatStream(
  { question, conversation_id, use_temp, use_method, model, source_document_ids },
  onEvent
) {
  const payload = {
    question,
    conversation_id: toIntOrNull(conversation_id),
    use_temp: Boolean(use_temp),
    use_method: Boolean(use_method),
    model: model || undefined,
    source_document_ids: Array.isArray(source_document_ids) && source_document_ids.length
      ? source_document_ids.map(toIntOrNull).filter((id) => id !== null)
      : undefined,
  };

  if (useMockBackend) return mockChatStream(payload, onEvent);

  let response;
  try {
    response = await fetch(`${apiBaseUrl}/chat/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-User-Id': currentUserId,
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      },
      body: JSON.stringify(payload),
    });
  } catch (err) {
    console.error('[HDS AI] Không kết nối được /chat/stream.', err);
    if (fallbackListener) fallbackListener(apiBaseUrl);
    throw new Error(
      `Không kết nối được backend tại ${apiBaseUrl}. ` +
        'Câu hỏi chưa được gửi và hệ thống không thay bằng câu trả lời mẫu.'
    );
  }

  if (!response.ok || !response.body) {
    const rawText = await response.text().catch(() => '');
    throw new Error(parseErrorBody(rawText, response.status));
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let last = null;

  // Một sự kiện SSE kết thúc bằng dòng trống. Mẩu dữ liệu từ mạng có thể cắt
  // ngang giữa sự kiện nên phải gom đệm rồi mới tách.
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let sep;
    while ((sep = buffer.indexOf('\n\n')) >= 0) {
      const raw = buffer.slice(0, sep).trim();
      buffer = buffer.slice(sep + 2);
      if (!raw.startsWith('data:')) continue;
      let evt;
      try {
        evt = JSON.parse(raw.slice(5).trim());
      } catch {
        continue;
      }
      if (evt.type === 'error') throw new Error(evt.message || 'Máy chủ báo lỗi giữa chừng.');
      onEvent?.(evt);
      last = evt;
    }
  }
  if (!last || last.type !== 'done') {
    throw new Error(
      'Kết nối bị đóng trước khi máy chủ xác nhận đã lưu xong câu trả lời.'
    );
  }
  return last;
}

// POST /chat/portal (dành cho khách hàng)
export async function chatPortal({ question, conversation_id }) {
  return request('/chat/portal', {
    method: 'POST',
    body: JSON.stringify({
      question,
      conversation_id: toIntOrNull(conversation_id),
    }),
  });
}

// GET /chat/history — lịch sử khung chat bền của người đang đăng nhập
// GET /chat/history — tin nhắn của MỘT hội thoại (không truyền id thì lấy hội
// thoại mới hoạt động gần nhất).
export async function getChatHistory(conversationId = null, limit = 300) {
  const qs = new URLSearchParams({ limit: String(Number(limit) || 300) });
  if (conversationId) qs.set('conversation_id', String(conversationId));
  return request(`/chat/history?${qs.toString()}`, { method: 'GET' });
}

// ---------- Nhiều hội thoại (kiểu ChatGPT) ----------
export async function listConversations(limit = 100) {
  return request(`/conversations?limit=${Number(limit) || 100}`, { method: 'GET' });
}

export async function renameConversation(convId, title) {
  return request(`/conversations/${convId}`, {
    method: 'PATCH',
    body: JSON.stringify({ title }),
  });
}

export async function deleteConversation(convId) {
  return request(`/conversations/${convId}`, { method: 'DELETE' });
}

// GET /chat/search — tìm trong lịch sử chat của chính mình
export async function searchChat(q, limit = 40) {
  return request(`/chat/search?q=${encodeURIComponent(q)}&limit=${Number(limit) || 40}`, {
    method: 'GET',
  });
}

// ---------- Ghi chú cá nhân ----------
export async function getNotes(limit = 100) {
  return request(`/notes?limit=${Number(limit) || 100}`, { method: 'GET' });
}

export async function addNote({ content, source_message_id }) {
  return request('/notes', {
    method: 'POST',
    body: JSON.stringify({ content, source_message_id: source_message_id ?? null }),
  });
}

export async function deleteNote(noteId) {
  return request(`/notes/${noteId}`, { method: 'DELETE' });
}

// POST /upload — backend yêu cầu conversation_id kiểu int (bắt buộc)
export async function uploadFile({ conversation_id, filename, content, mode }) {
  const convId = toIntOrNull(conversation_id);
  if (convId === null && !useMockBackend) {
    throw new Error(
      'Cần gửi ít nhất một câu hỏi trong cuộc trò chuyện này trước khi tải tài liệu lên, ' +
        'để hệ thống cấp mã hội thoại.'
    );
  }
  return request('/upload', {
    method: 'POST',
    body: JSON.stringify({
      conversation_id: convId,
      filename,
      content,
      mode, // 'temp' | 'save'
    }),
  });
}

// ==================== 2. THỐNG KÊ ====================

export async function getStats() {
  return request('/stats', { method: 'GET' });
}

// ==================== 3. DUYỆT NHÃN TÀI LIỆU ====================

export async function getPendingReviews() {
  return request('/review/pending', { method: 'GET' });
}

// POST /review/{id}/approve — client_id là khoá ngoại kiểu int
/** Nội dung TRÍCH XUẤT của tài liệu chờ duyệt — để người duyệt đọc và sửa
 * (PDF scan bắt buộc soát nội dung, không chỉ soát nhãn). */
export async function getReviewContent(id) {
  return request(`/review/${id}/content`);
}

/** Lưu nội dung người duyệt đã sửa: backend chia đoạn + tạo vector lại. */
export async function saveReviewContent(id, content) {
  return request(`/review/${id}/content`, {
    method: 'PUT',
    body: JSON.stringify({ content }),
  });
}

export async function approveReview(id, { doc_type, access_level, client_id }) {
  const clientId = toIntOrNull(client_id);
  if (access_level === 'client' && clientId === null) {
    throw new Error('Tài liệu mức "Hồ sơ khách hàng" bắt buộc phải chọn khách hàng.');
  }
  return request(`/review/${id}/approve`, {
    method: 'POST',
    body: JSON.stringify({
      doc_type,
      access_level,
      client_id: clientId,
    }),
  });
}

// ==================== 4. DUYỆT HỘI THOẠI (TỰ HỌC) ====================

export async function getPendingLearns() {
  return request('/learn/pending', { method: 'GET' });
}

export async function reviewLearnMessage(message_id, { action, edited_content, edit_reason }) {
  return request(`/learn/${message_id}`, {
    method: 'POST',
    body: JSON.stringify({
      action, // 'approve' | 'edit' | 'reject'
      edited_content: edited_content || undefined,
      edit_reason: edit_reason || undefined,
    }),
  });
}

// ==================== 5. MẪU PHƯƠNG PHÁP ====================

export async function getMethods() {
  return request('/methods', { method: 'GET' });
}
export const getMethodTemplates = getMethods;

// POST /methods — cột analysis_methods.steps là TEXT, phải gửi chuỗi
export async function createMethod({ case_type, steps }) {
  const stepsText = Array.isArray(steps) ? steps.join('\n') : String(steps || '');
  return request('/methods', {
    method: 'POST',
    body: JSON.stringify({ case_type, steps: stepsText }),
  });
}

// ==================== 6. TÀI LIỆU ====================

export async function getDocuments({ q = '', doc_type = '', limit = 50 } = {}) {
  const params = new URLSearchParams();
  if (q) params.append('q', q);
  if (doc_type) params.append('doc_type', doc_type);
  if (limit) params.append('limit', String(limit));
  const queryStr = params.toString();
  return request(`/documents${queryStr ? `?${queryStr}` : ''}`, { method: 'GET' });
}

// GET /documents/browse — danh mục che tên cho mọi nhân viên nội bộ
export async function getBrowseDocuments({ q = '' } = {}) {
  const params = new URLSearchParams();
  if (q) params.append('q', q);
  const queryStr = params.toString();
  return request(`/documents/browse${queryStr ? `?${queryStr}` : ''}`, { method: 'GET' });
}

// ==================== 7. KHÁCH HÀNG 360° ====================

export async function getClients() {
  return request('/clients', { method: 'GET' });
}

export async function getClient360(clientId) {
  return request(`/clients/${clientId}/360`, { method: 'GET' });
}

export async function updateClientProfile(
  clientId,
  { history_note, issues_note, warnings, suggestions }
) {
  return request(`/clients/${clientId}/profile`, {
    method: 'POST',
    body: JSON.stringify({
      history_note: history_note || undefined,
      issues_note: issues_note || undefined,
      warnings: warnings || undefined,
      suggestions: suggestions || undefined,
    }),
  });
}

export async function getDepartments() {
  return request('/departments', { method: 'GET' });
}

// ==================== 8. NGƯỜI DÙNG ====================

export async function getUsers() {
  const list = await request('/users', { method: 'GET' });
  return Array.isArray(list) ? list.map(normalizeUser) : list;
}

// POST /users — client_id kiểu int; vai client_* bắt buộc có client_id (CHECK constraint)
export async function createUser({
  email,
  full_name,
  role,
  can_review,
  client_id,
  department_ids,
  head_of,
  monthly_quota,
}) {
  const clientId = toIntOrNull(client_id);
  if (String(role || '').startsWith('client_') && clientId === null) {
    throw new Error('Tài khoản vai Khách hàng bắt buộc phải gắn với một khách hàng.');
  }
  const created = await request('/users', {
    method: 'POST',
    body: JSON.stringify({
      email,
      full_name,
      role,
      can_review: Boolean(can_review),
      client_id: clientId,
      department_ids: Array.isArray(department_ids) ? department_ids : [],
      head_of: Array.isArray(head_of) ? head_of : [],
      monthly_quota: Number(monthly_quota) || 0,
    }),
  });
  return normalizeUser(created);
}

// POST /users/{uid}/review-permission?grant=true|false
export async function updateUserReviewPermission(uid, grant) {
  return request(`/users/${uid}/review-permission?grant=${Boolean(grant)}`, {
    method: 'POST',
  });
}

// POST /users/{uid}/finance-permission?grant=true|false
// Quyền xem công nợ khách. Không có quyền thì tài liệu công nợ bị CSDL chặn.
export async function updateUserFinancePermission(uid, grant) {
  return request(`/users/${uid}/finance-permission?grant=${Boolean(grant)}`, {
    method: 'POST',
  });
}

// POST /users/{uid}/api-key — cấp khoá API mới cho tài khoản khách.
// Khoá thật chỉ trả về đúng lần này, backend chỉ lưu bản băm.
export async function issueApiKey(uid) {
  return request(`/users/${uid}/api-key`, { method: 'POST' });
}

// DELETE /users/{uid}/api-key — thu hồi khoá, chặn ngay mọi lời gọi bằng khoá cũ
export async function revokeApiKey(uid) {
  return request(`/users/${uid}/api-key`, { method: 'DELETE' });
}

// GET /alerts — vụ việc quá hạn / sắp đến hạn / treo lâu, lọc theo phòng ban
export async function getMatterAlerts(limit = 100) {
  return request(`/alerts?limit=${Number(limit) || 100}`, { method: 'GET' });
}

// ==================== 9. CÀI ĐẶT AI ====================

export async function getSettings() {
  return request('/settings', { method: 'GET' });
}

// GET /models — model Ollama có trên máy chủ + model đang dùng
export async function getModels() {
  return request('/models', { method: 'GET' });
}

/** Đo tốc độ đọc/viết thật của máy chủ. Chạy lâu (vài chục giây trên máy yếu). */
export async function benchmarkModel(model) {
  const qs = model ? `?model=${encodeURIComponent(model)}` : '';
  return request(`/models/benchmark${qs}`, { method: 'GET' });
}

export async function updateSetting(key, value) {
  return request(`/settings/${key}`, {
    method: 'PUT',
    body: JSON.stringify({ value }),
  });
}

export async function resetSetting(key) {
  return request(`/settings/${key}/reset`, { method: 'POST' });
}

// GET /drive/sync-status — trạng thái lần bot quét Google Drive gần nhất
export async function getDriveSyncStatus() {
  return request('/drive/sync-status', { method: 'GET' });
}

// ==================== 10. BÁO CÁO CHẤT LƯỢNG ====================

export async function sendFeedback({ message_id, rating, note }) {
  return request('/feedback', {
    method: 'POST',
    body: JSON.stringify({
      message_id: toIntOrNull(message_id),
      rating,
      note: note || undefined,
    }),
  });
}

// DELETE /feedback/{id} — rút lại đánh giá vừa gửi (lỡ bấm nhầm)
export async function retractFeedback(feedbackId) {
  return request(`/feedback/${feedbackId}`, { method: 'DELETE' });
}

export async function getFeedbackPending() {
  return request('/feedback/pending', { method: 'GET' });
}

export async function reviewFeedback(fid, { action, corrected_answer, admin_note, access_level }) {
  return request(`/feedback/${fid}/review`, {
    method: 'POST',
    body: JSON.stringify({
      action,
      corrected_answer: corrected_answer || undefined,
      admin_note: admin_note || undefined,
      access_level: access_level || 'internal',
    }),
  });
}

// ==================== 11. SOẠN TÀI LIỆU ====================

export async function listDrafts() {
  const data = await request('/drafts', { method: 'GET' });
  // Chấp nhận cả response mảng và response phân trang {items:[...]}.
  return Array.isArray(data) ? data : data?.items || data?.drafts || [];
}

export async function listDraftTemplates() {
  const data = await request('/draft-templates', { method: 'GET' });
  return Array.isArray(data) ? data : data?.items || [];
}

export async function getDraft(draftId) {
  return request(`/drafts/${toIntOrNull(draftId)}`, { method: 'GET' });
}

export async function createDraft(data) {
  return request('/drafts', {
    method: 'POST',
    body: JSON.stringify({
      title: data.title,
      document_type: data.document_type || data.draft_type || 'other',
      template_id: toIntOrNull(data.template_id),
      instructions: data.instructions || '',
      client_id: toIntOrNull(data.client_id),
      matter_id: toIntOrNull(data.matter_id),
      department_id: toIntOrNull(data.department_id),
      input_data: data.input_data && typeof data.input_data === 'object' ? data.input_data : {},
      source_document_ids: Array.isArray(data.source_document_ids)
        ? data.source_document_ids.map(toIntOrNull).filter((id) => id !== null)
        : [],
    }),
  });
}

export async function generateDraft(draftId, data = {}) {
  return request(`/drafts/${toIntOrNull(draftId)}/generate`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function reviseDraft(draftId, data = {}) {
  return request(`/drafts/${toIntOrNull(draftId)}/revise`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function approveDraft(draftId, data = {}) {
  return request(`/drafts/${toIntOrNull(draftId)}/approve`, {
    method: 'POST',
    body: JSON.stringify({
      note: data.note || undefined,
      allow_placeholders: Boolean(data.allow_placeholders),
      confirm_needs_review: Boolean(data.confirm_needs_review),
    }),
  });
}

// POST /drafts/autofill (multipart) — tải MỘT hồ sơ (CCCD/sơ yếu/CV: PDF, ảnh,
// DOCX), backend trích văn bản (OCR nếu cần) rồi bóc các trường định danh để
// điền sẵn input_data. File dùng xong bỏ, không vào kho.
export async function autofillDraft(file) {
  if (useMockBackend) {
    await new Promise((r) => setTimeout(r, 300));
    return {
      ok: true,
      fields: { ho_ten: 'Nguyễn Thị Ngân (demo)', so_cccd: '049195003678' },
      field_labels: { ho_ten: 'Họ và tên', so_cccd: 'Số CCCD/CMND' },
      warnings: [],
      method: 'demo',
      text_chars: 0,
    };
  }
  const form = new FormData();
  form.append('file', file);
  const res = await fetch(`${apiBaseUrl}/drafts/autofill`, {
    method: 'POST',
    headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
    body: form, // KHÔNG tự đặt Content-Type — trình duyệt phải tự thêm boundary
  });
  if (!res.ok) {
    const rawText = await res.text().catch(() => '');
    throw new Error(parseErrorBody(rawText, res.status));
  }
  return res.json();
}

export async function exportDraft(draftId, filename) {
  if (useMockBackend) {
    const blob = new Blob(['Bản demo — chỉ xuất tệp khi kết nối backend thật.'], {
      type: 'text/plain;charset=utf-8',
    });
    triggerDownload(blob, filename || `ban-nhap-${draftId}.txt`);
    return;
  }
  const res = await fetch(`${apiBaseUrl}/drafts/${toIntOrNull(draftId)}/export?format=docx`, {
    method: 'GET',
    headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
  });
  if (!res.ok) {
    const rawText = await res.text().catch(() => '');
    throw new Error(parseErrorBody(rawText, res.status));
  }
  const blob = await res.blob();
  const cd = res.headers.get('Content-Disposition') || '';
  const m = cd.match(/filename\*?=(?:UTF-8'')?"?([^";]+)"?/i);
  triggerDownload(blob, filename || (m ? decodeURIComponent(m[1]) : `ban-nhap-${draftId}.docx`));
}

// ==================== 12. TỆP: TẢI LÊN / TẢI VỀ THẬT ====================

// POST /files/upload (multipart) — gửi tệp thật, server tự trích văn bản + OCR.
export async function uploadDocument({
  file,
  doc_type = 'other',
  access_level = 'internal',
  client_id,
  matter_id,
  department_id,
  auto_approve = false,
  onProgress,
}) {
  if (useMockBackend) {
    await new Promise((r) => setTimeout(r, 400));
    if (onProgress) onProgress(100);
    mockState.stats.cho_duyet_nhan += auto_approve ? 0 : 1;
    mockState.stats.da_duyet_nhan += auto_approve ? 1 : 0;
    return {
      ok: true, document_id: Date.now(), filename: file.name, bytes: file.size,
      note: auto_approve ? 'Đã nạp vào kho.' : 'Đã vào hàng chờ duyệt nhãn.',
    };
  }

  const form = new FormData();
  form.append('file', file);
  form.append('doc_type', doc_type);
  form.append('access_level', access_level);
  form.append('auto_approve', String(Boolean(auto_approve)));
  if (client_id != null) form.append('client_id', String(client_id));
  if (matter_id != null) form.append('matter_id', String(matter_id));
  if (department_id != null) form.append('department_id', String(department_id));

  // XMLHttpRequest để có tiến trình tải lên; KHÔNG tự đặt Content-Type (trình
  // duyệt tự thêm boundary cho multipart).
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${apiBaseUrl}/files/upload`);
    if (accessToken) xhr.setRequestHeader('Authorization', `Bearer ${accessToken}`);
    xhr.upload.onprogress = (e) => {
      if (onProgress && e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
    };
    xhr.onload = () => {
      let data = {};
      try { data = JSON.parse(xhr.responseText); } catch { /* để rơi xuống nhánh lỗi */ }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data);
      else reject(new Error(parseErrorBody(xhr.responseText, xhr.status)));
    };
    xhr.onerror = () => reject(new Error('Không kết nối được máy chủ khi tải tệp lên.'));
    xhr.send(form);
  });
}

// GET /files/{id}/download → tải bản gốc về máy người dùng.
export async function downloadDocument(docId, filename) {
  if (useMockBackend) {
    const blob = new Blob(
      [`Bản demo — nội dung tệp gốc của tài liệu #${docId} sẽ tải về từ máy chủ thật.`],
      { type: 'text/plain' }
    );
    triggerDownload(blob, filename || `tai-lieu-${docId}.txt`);
    return;
  }
  const res = await fetch(`${apiBaseUrl}/files/${docId}/download`, {
    headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(parseErrorBody(text, res.status));
  }
  const blob = await res.blob();
  const cd = res.headers.get('Content-Disposition') || '';
  const m = cd.match(/filename\*?=(?:UTF-8'')?"?([^";]+)"?/i);
  triggerDownload(blob, filename || (m ? decodeURIComponent(m[1]) : `tai-lieu-${docId}`));
}

function triggerDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// ==================== CHẾ ĐỘ GIẢ LẬP (MOCK) ====================
// Dữ liệu mẫu bám sát seed thật của backend:
//   - 4 bộ phận trong app/seed_departments.py
//   - tài khoản trong app/seed_accounts.py
//   - enum doc_type / access_level / matters.status trong sql/schema.sql

let mockState = {
  stats: {
    tai_lieu: 148,
    da_duyet_nhan: 134,
    cho_duyet_nhan: 14,
    thieu_chu_so_huu: 2,
    so_doan: 4520,
    hoi_thoai_cho_duyet: 2,
    da_hoc: 96,
    so_mau_phuong_phap: 2,
    so_khach: 3,
    vu_viec_dang_mo: 4,
    so_bo_phan: 4,
    bao_cao_cho_xu_ly: 2,
  },
  departments: [
    { id: 1, code: 'dn-dt', name: 'Doanh nghiệp - Đầu tư' },
    { id: 2, code: 'htpl-tvtx', name: 'Hỗ trợ pháp lý - Tư vấn thường xuyên' },
    { id: 3, code: 'tranh-tung', name: 'Tranh tụng' },
    { id: 4, code: 'shtt', name: 'Sở hữu trí tuệ' },
  ],
  users: [
    { id: 1, email: 'admin@hdslaw.vn', full_name: 'Quản trị hệ thống', role: 'admin', can_review: true, can_view_finance: true, active: true, department_ids: [], head_of: [], monthly_quota: 0 },
    { id: 2, email: 'giamdoc@hdslaw.vn', full_name: 'Giám đốc (Ban QT)', role: 'ban_qt', can_review: true, can_view_finance: true, active: true, department_ids: [], head_of: [], monthly_quota: 0 },
    { id: 3, email: 'truong.dndt@hdslaw.vn', full_name: 'Trưởng phòng DN-ĐT', role: 'truong_bph', can_review: true, can_view_finance: false, active: true, department_ids: [1], head_of: [1], monthly_quota: 0 },
    { id: 4, email: 'cv.tranhtung@hdslaw.vn', full_name: 'Chuyên viên Tranh tụng', role: 'chuyen_vien', can_review: false, can_view_finance: false, active: true, department_ids: [3], head_of: [], monthly_quota: 0 },
    { id: 5, email: 'troly@hdslaw.vn', full_name: 'Trợ lý', role: 'tro_ly', can_review: false, can_view_finance: false, active: true, department_ids: [2], head_of: [], monthly_quota: 0 },
    { id: 6, email: 'lienhe@sungroup.vn', full_name: 'Đại diện SunGroup', role: 'client_plus', can_review: false, can_view_finance: false, active: true, client_id: 1, department_ids: [], head_of: [], monthly_quota: 50 },
  ],
  clients: [
    { id: 1, name: 'Tập đoàn SunGroup', code: 'SUNGROUP', department: 'Doanh nghiệp - Đầu tư' },
    { id: 2, name: 'Công ty CP Vinapharma', code: 'VINAPHARMA', department: 'Tranh tụng' },
    { id: 3, name: 'Công ty TechLogistics', code: 'TECHLOG', department: 'Sở hữu trí tuệ' },
  ],
  clientProfiles: {
    1: {
      history: 'Khách hàng thân thiết từ năm 2021. Đã ký 14 hợp đồng tư vấn tái cấu trúc và M&A.',
      issues: 'Đang vướng tranh chấp đền bù giải phóng mặt bằng dự án nghỉ dưỡng tại Phú Quốc.',
      warnings: 'Chú ý thời hiệu khởi kiện vụ hợp đồng thầu phụ, dự kiến hết hạn 15/10/2026.',
      suggestions: 'Khuyến nghị đàm phán phụ lục gia hạn tiến độ và lập biên bản hoà giải có bên thứ ba xác nhận.',
    },
    2: {
      history: 'Khách hàng ký hợp đồng tư vấn thường xuyên theo năm.',
      issues: 'Rà soát hợp đồng nhượng quyền thương hiệu dòng sản phẩm dược đông y.',
      warnings: 'Đơn đăng ký nhãn hiệu đang bị Cục SHTT phản đối do trùng lắp hình ảnh.',
      suggestions: 'Soạn thư giải trình kèm tài liệu chứng minh sử dụng rộng rãi trước ngày nộp đơn.',
    },
    3: {
      history: 'Tư vấn đăng ký bản quyền phần mềm quản lý kho vận.',
      issues: 'Tranh chấp hợp đồng mua bán cổ phần với nhóm nhà đầu tư Singapore.',
      warnings: 'Nhà đầu tư đe doạ rút vốn và khởi kiện tại Trọng tài SIAC Singapore.',
      suggestions: 'Rà soát điều khoản giải quyết tranh chấp trong SHA để xác định luật áp dụng.',
    },
  },
  clientMatters: {
    1: [
      { id: 1, code: 'M-2026-001', title: 'Tái cấu trúc vốn công ty con SunPhuQuoc', matter_type: 'Doanh nghiệp', status: 'dang_xu_ly', deadline: '2026-09-30', opened_at: '2026-06-10' },
      { id: 2, code: 'M-2026-014', title: 'Thương lượng hợp đồng thuê đất thương mại', matter_type: 'Tư vấn thường xuyên', status: 'tiep_nhan', deadline: null, opened_at: '2026-07-01' },
      { id: 3, code: 'M-2025-088', title: 'Tư vấn phát hành trái phiếu doanh nghiệp', matter_type: 'Doanh nghiệp', status: 'hoan_thanh', deadline: null, opened_at: '2025-11-20' },
    ],
    2: [
      { id: 4, code: 'M-2026-021', title: 'Bảo hộ nhãn hiệu Vinapharma Đông Y', matter_type: 'Sở hữu trí tuệ', status: 'dang_xu_ly', deadline: '2026-10-15', opened_at: '2026-05-15' },
    ],
    3: [
      { id: 5, code: 'M-2026-033', title: 'Tranh chấp SHA với SIAC Investor Group', matter_type: 'Tranh tụng', status: 'tam_dung', deadline: '2026-08-30', opened_at: '2026-08-01' },
    ],
  },
  clientDocuments: {
    1: [
      { id: 11, title: 'Hợp đồng Li-xăng Nhãn hiệu Thương mại.pdf', doc_type: 'contract', summary: 'Quyền sử dụng nhãn hiệu độc quyền khu vực Đông Nam Á.', created_at: '2026-06-18' },
      { id: 12, title: 'Biên bản Thẩm định Pháp lý LDD-PhuQuoc.docx', doc_type: 'advisory', summary: 'Báo cáo thẩm định pháp lý dự án Phú Quốc.', created_at: '2026-06-25' },
    ],
    2: [
      { id: 13, title: 'Dự thảo Hợp đồng Chuyển nhượng Cổ phần Vinapharma.docx', doc_type: 'contract', summary: 'Chuyển nhượng 500.000 cổ phần phổ thông.', created_at: '2026-08-02' },
    ],
    3: [
      { id: 14, title: 'Ý kiến Pháp lý Thuế TNDN chuyển nhượng vốn.pdf', doc_type: 'advisory', summary: 'Phân tích nghĩa vụ thuế TNDN 20% khi chuyển nhượng vốn.', created_at: '2026-07-22' },
    ],
  },
  pendingReviews: [
    {
      id: 101,
      title: 'Hợp đồng Chuyển nhượng Cổ phần - Vinapharma 2026.txt',
      doc_type: 'contract',
      access_level: 'internal',
      client_id: 2,
      client_name: 'Công ty CP Vinapharma',
      confidence: 0.92,
      source_kind: 'chat',
      preview:
        'Bên Chuyển Nhượng đồng ý chuyển nhượng 500.000 cổ phần phổ thông với giá trị tương đương 15.000.000.000 VNĐ...',
    },
    {
      id: 102,
      title: 'Dự thảo Ý kiến Pháp lý Tranh chấp Đất đai Q.2.txt',
      doc_type: 'advisory',
      access_level: 'internal',
      client_id: null,
      client_name: null,
      confidence: null, // cố ý để trống — kiểm tra giao diện khi AI chưa chấm điểm
      source_kind: 'drive',
      preview:
        'Dựa trên Luật Đất đai 2024 và Giấy chứng nhận QSDĐ cấp năm 2018, diện tích tranh chấp thuộc quyền thừa kế hợp pháp...',
    },
    {
      id: 103,
      title: 'Quy trình Tranh tụng Lao động Ngoại tòa HDS-2026.txt',
      doc_type: 'quy_trinh',
      access_level: 'public',
      client_id: null,
      client_name: null,
      confidence: 0.95,
      source_kind: 'manual',
      preview:
        'Các bước hoà giải tranh chấp lao động cá nhân theo Bộ luật Lao động 2019 trước khi gửi đơn ra Toà án nhân dân...',
    },
  ],
  pendingLearns: [
    {
      message_id: 501,
      question: 'Thời hạn đăng ký thay đổi người đại diện theo pháp luật của công ty TNHH là bao lâu?',
      answer:
        'Theo Điều 12 Luật Doanh nghiệp 2020, doanh nghiệp phải đăng ký thay đổi người đại diện theo pháp luật trong thời hạn 10 ngày kể từ ngày có thay đổi.',
      created_at: '2026-08-07 09:15',
      note: 'Sai thời hạn — thực tế là trong 10 ngày nhưng dẫn nhầm Điều. Cần dẫn đúng Điều 30 Luật Doanh nghiệp 2020 về đăng ký thay đổi nội dung ĐKDN.',
      reporter: 'Chuyên viên Tranh tụng',
      report_count: 2,
      reported_at: '2026-08-07 09:40',
    },
    {
      message_id: 502,
      question: 'Thủ tục xin cấp Giấy phép Bưu chính quốc tế cần những văn bản gì?',
      answer:
        'Hồ sơ gồm: đơn đề nghị, bản sao Giấy chứng nhận ĐKKD, phương án kinh doanh bưu chính, mẫu hợp đồng cung ứng dịch vụ và văn bản xác nhận vốn tối thiểu 5 tỷ đồng.',
      created_at: '2026-08-07 10:30',
      note: 'Thiếu điều kiện về vốn pháp định thực tế và bản cam kết chất lượng dịch vụ.',
      reporter: 'Trưởng phòng DN-ĐT',
      report_count: 1,
      reported_at: '2026-08-07 10:52',
    },
  ],
  // steps là chuỗi nhiều dòng — giống hệt cột TEXT của backend
  methods: [
    {
      id: 1,
      case_type: 'Rà soát Hợp đồng M&A / Mua bán Doanh nghiệp',
      steps: [
        'Bước 1: Kiểm tra tư cách pháp lý của các bên và thẩm quyền ký kết',
        'Bước 2: Rà soát danh mục tài sản, khoản nợ và nghĩa vụ thuế tồn đọng',
        'Bước 3: Đánh giá điều khoản chuyển nhượng, thanh toán và điều kiện tiên quyết',
        'Bước 4: Phân tích rủi ro bồi thường và chế tài vi phạm',
        'Bước 5: Lập Báo cáo Thẩm định Pháp lý (Legal Due Diligence Report)',
      ].join('\n'),
      approved: true,
    },
    {
      id: 2,
      case_type: 'Giải quyết Tranh chấp Hợp đồng Thương mại',
      steps: [
        'Bước 1: Nghiên cứu hồ sơ hợp đồng, phụ lục và biên bản trao đổi',
        'Bước 2: Lập bảng hệ thống thời hiệu và nghĩa vụ vi phạm của đối phương',
        'Bước 3: Gửi Thư cảnh báo / Thương lượng lần cuối (Notice of Default)',
        'Bước 4: Nộp đơn khởi kiện tại Trung tâm Trọng tài Thương mại hoặc Toà án',
      ].join('\n'),
      approved: true,
    },
  ],
  documents: [
    {
      id: 1,
      title: 'Luật Doanh nghiệp số 59/2020/QH14',
      doc_type: 'law',
      access_level: 'public',
      summary:
        'Quy định về thành lập, tổ chức quản lý, tổ chức lại, giải thể và hoạt động có liên quan của doanh nghiệp.',
      source_kind: 'manual',
      created_at: '2026-01-10',
      client_name: null,
      so_doan: 1420,
      department: 'Doanh nghiệp - Đầu tư',
      can_open: true,
    },
    {
      id: 2,
      title: 'Bộ luật Lao động số 45/2019/QH14',
      doc_type: 'law',
      access_level: 'public',
      summary:
        'Quy định tiêu chuẩn lao động; quyền, nghĩa vụ và trách nhiệm của người lao động, người sử dụng lao động.',
      source_kind: 'manual',
      created_at: '2026-01-12',
      client_name: null,
      so_doan: 980,
      department: 'Hỗ trợ pháp lý - Tư vấn thường xuyên',
      can_open: true,
    },
    {
      id: 3,
      title: 'Hợp đồng Li-xăng Nhãn hiệu Thương mại - SunGroup',
      doc_type: 'contract',
      access_level: 'client',
      summary: 'Mẫu hợp đồng quyền sử dụng nhãn hiệu độc quyền tại khu vực Đông Nam Á.',
      source_kind: 'drive',
      created_at: '2026-06-18',
      client_name: 'Tập đoàn SunGroup',
      so_doan: 45,
      department: 'Doanh nghiệp - Đầu tư',
      can_open: false,
    },
    {
      id: 4,
      title: 'Ý kiến Pháp lý về Thuế TNDN khi chuyển nhượng vốn',
      doc_type: 'advisory',
      access_level: 'client',
      summary:
        'Phân tích nghĩa vụ kê khai thuế TNDN 20% trên thu nhập chịu thuế khi nhà đầu tư nước ngoài chuyển nhượng vốn.',
      source_kind: 'manual',
      created_at: '2026-07-22',
      client_name: 'Công ty TechLogistics',
      so_doan: 32,
      department: 'Sở hữu trí tuệ',
      can_open: false,
    },
    {
      id: 5,
      title: 'Dự thảo Hợp đồng Chuyển nhượng Cổ phần - Vinapharma',
      doc_type: 'contract',
      access_level: 'internal',
      summary: 'Chuyển nhượng 500.000 cổ phần phổ thông với giá trị 15.000.000.000 VNĐ.',
      source_kind: 'chat',
      created_at: '2026-08-02',
      client_name: 'Công ty CP Vinapharma',
      so_doan: 28,
      department: 'Tranh tụng',
      can_open: true,
    },
  ],
  settings: {
    prompt_public:
      'Bạn là trợ lý của Công ty Luật HDS, trả lời khách trên website. Chỉ dựa vào TÀI LIỆU THAM KHẢO. Trả lời NGẮN GỌN, khái quát. Nếu câu hỏi chưa rõ, hỏi lại một câu để làm rõ. Không đủ căn cứ thì nói rõ và mời liên hệ luật sư HDS.',
    prompt_internal:
      'Bạn là trợ lý pháp lý của HDS Law Firm — trò chuyện TỰ NHIÊN, THÂN THIỆN, chủ động như đồng nghiệp giỏi, không cộc lốc hay máy móc. Dựa trên TÀI LIỆU THAM KHẢO và DỮ LIỆU CÔNG TY. LUÔN đọc DIỄN BIẾN TRAO ĐỔI TRƯỚC ĐÓ để hiểu câu nối tiếp; nếu người dùng nói lại cho rõ ("ý tôi là…", "tôi hỏi X mà") thì hiểu là chỉnh lại câu trước và trả lời luôn. Trả lời rõ ràng, đủ ý, dễ đọc nhưng không lan man. Có ngày/thời hạn thì tự so với HÔM NAY để biết còn hạn hay đã hết. Dữ liệu chưa có thứ cần thì nói thẳng nhẹ nhàng và gợi ý bước tiếp theo, đừng bịa. Trích Điều/Khoản và [Nguồn n] khi dùng tài liệu. Bản nháp tham khảo; luật sư chịu trách nhiệm cuối cùng.',
    prompt_portal:
      'Bạn là trợ lý của HDS phục vụ khách hàng đã ký hợp đồng. Chỉ dùng tài liệu thuộc về khách đang đăng nhập, không nhắc tới khách khác. Trả lời NGẮN GỌN, dễ hiểu. Câu hỏi chưa rõ thì hỏi lại. Không đủ căn cứ thì đề nghị liên hệ luật sư phụ trách.',
    llm_temperature: '0.2',
    // Nhóm tham số quyết định tốc độ — giữ khớp DEFAULTS trong hds-ai/app/settings.py
    retrieval_top_k: '5',
    context_char_budget: '6000',
    chunk_char_limit: '1500',
    min_relevance: '0.25',
    llm_num_ctx: '8192',
    llm_num_predict: '700',
    llm_num_thread: '0',
    chat_history_turns: '3',
    llm_model: '',
    drive_map: JSON.stringify(
      {
        categories: {
          'văn bản pháp luật': { doc_type: 'law', access_level: 'public' },
          'bản án - án lệ': { doc_type: 'ban_an', access_level: 'internal' },
          'hợp đồng mẫu': { doc_type: 'mau_hd', access_level: 'internal' },
          'quan điểm pháp lý': { doc_type: 'advisory', access_level: 'internal' },
        },
        client_roots: ['hồ sơ khách hàng'],
        client_subcategories: { 'dự án': 'ho_so_kh', 'hợp đồng': 'contract' },
      },
      null,
      2
    ),
  },
  driveSyncStatus: {
    folder_id: '1uoDwXCX1CO6F3KukOQOIlf2Byuy6U8ng',
    started_at: '2026-08-11T02:00:03+00:00',
    finished_at: '2026-08-11T02:00:41+00:00',
    finished: true,
    counts: {
      scanned: 18, new: 3, updated: 1, unchanged: 12, unmapped: 2, bad_format: 0, errors: 0,
    },
    new_items: [
      { name: '90_2025_QH15_662379', location: '1. Văn bản pháp luật', doc_type: 'law', access_level: 'public' },
      { name: '100_2026_ND-CP_695468', location: '1. Văn bản pháp luật', doc_type: 'law', access_level: 'public' },
      { name: 'Mau_HD_Tu_van_Phap_ly.docx', location: '3. Hợp đồng mẫu', doc_type: 'mau_hd', access_level: 'internal' },
    ],
    updated_items: [
      { name: '07_2022_QH15_458435.pdf', location: '1. Văn bản pháp luật', doc_type: 'law', access_level: 'public' },
    ],
    skipped_items: [
      {
        name: 'Ghi_chu_noi_bo_thang_8.docx',
        location: '(gốc)',
        reason: "nằm ở thư mục gốc (không rõ loại)",
      },
      {
        name: 'Hop_dong_dich_vu_ABC.pdf',
        location: '9. Hồ sơ khách hàng/Công ty ABC',
        reason:
          "chưa xác định được khách từ thư mục 'Công ty ABC'. Đặt tên dạng '[MÃ_KHÁCH] Tên khách' và tạo khách trong hệ thống trước",
      },
    ],
    error_items: [],
  },
  ingestFailures: [
    {
      id: 1,
      file_name: 'Quyet dinh 1234 (ban scan).pdf',
      location: 'Hồ sơ khách hàng / [SPQ] SunPhuQuoc / Hồ sơ nộp cơ quan',
      error_code: 'pdf_no_text',
      error_message: 'PDF không có lớp văn bản và OCR không đọc được nội dung.',
      hint: 'Cài gói OCR tiếng Việt trên máy chủ, hoặc thay bằng bản PDF gốc có chữ.',
      attempts: 3,
      first_seen_at: '2026-08-14 02:10:00',
      last_seen_at: '2026-08-19 02:10:00',
      drive_file_id: 'drv_err_1',
    },
    {
      id: 2,
      file_name: 'Bang ke chi phi Q2.xlsx',
      location: 'Hồ sơ khách hàng / [SPQ] SunPhuQuoc / Công nợ - Tài chính',
      error_code: 'office_archive_too_large',
      error_message: 'File Office sau giải nén vượt giới hạn cho phép.',
      hint: 'Tách file hoặc bỏ ảnh nhúng quá lớn rồi tải lại.',
      attempts: 1,
      first_seen_at: '2026-08-19 02:10:00',
      last_seen_at: '2026-08-19 02:10:00',
      drive_file_id: 'drv_err_2',
    },
  ],
  matterAlerts: [
    {
      matter_id: 1, matter_code: 'M-2026-001',
      matter_title: 'Tái cấu trúc vốn SunPhuQuoc', matter_type: 'Doanh nghiệp',
      status: 'dang_xu_ly', deadline: '2026-08-10', days_left: -3,
      client_id: 1, client_name: 'Tập đoàn SunGroup', client_code: 'SUNGROUP',
      kind: 'qua_han', kind_label: 'ĐÃ QUÁ HẠN', severity: 'gap',
      last_doc_at: '2026-07-28',
    },
    {
      matter_id: 2, matter_code: 'M-2026-014',
      matter_title: 'Thuê đất thương mại', matter_type: 'Đất đai',
      status: 'dang_xu_ly', deadline: '2026-08-18', days_left: 5,
      client_id: 1, client_name: 'Tập đoàn SunGroup', client_code: 'SUNGROUP',
      kind: 'den_han_gap', kind_label: 'sắp hết hạn trong 7 ngày', severity: 'gap',
      last_doc_at: '2026-08-09',
    },
    {
      matter_id: 3, matter_code: 'M-2026-009',
      matter_title: 'Tranh chấp hợp đồng phân phối', matter_type: 'Tranh tụng',
      status: 'dang_xu_ly', deadline: '2026-09-05', days_left: 23,
      client_id: 2, client_name: 'Công ty CP Vinapharma', client_code: 'VINAPHARMA',
      kind: 'den_han_gan', kind_label: 'đến hạn trong 30 ngày', severity: 'luu_y',
      last_doc_at: '2026-08-01',
    },
    {
      matter_id: 4, matter_code: 'M-2026-022',
      matter_title: 'Đăng ký nhãn hiệu nhóm 35', matter_type: 'SHTT',
      status: 'dang_xu_ly', deadline: null, days_left: null,
      client_id: 3, client_name: 'Công ty TechLogistics', client_code: 'TECHLOG',
      kind: 'thieu_han', kind_label: 'đang xử lý nhưng chưa đặt hạn',
      severity: 'luu_y', last_doc_at: '2026-08-05',
    },
  ],
  feedback: [
    {
      id: 1,
      message_id: 8001,
      rating: 'bad',
      note: 'Trả lời thiếu căn cứ điều khoản cụ thể, chỉ nói chung chung.',
      created_at: '2026-08-10 14:20',
      reporter: 'Nguyễn Chuyên Viên',
      reporter_role: 'chuyen_vien',
      question: 'Thời hạn góp vốn của công ty TNHH là bao lâu?',
      answer:
        'Công ty TNHH phải hoàn tất góp vốn trong thời hạn nhất định kể từ ngày được cấp Giấy chứng nhận đăng ký doanh nghiệp.',
    },
    {
      id: 2,
      message_id: 8002,
      rating: 'good',
      note: null,
      created_at: '2026-08-10 15:05',
      reporter: 'Phạm Trợ Lý',
      reporter_role: 'tro_ly',
      question: 'Người đại diện theo pháp luật có bắt buộc cư trú tại Việt Nam?',
      answer:
        'Theo khoản 3 Điều 12 Luật Doanh nghiệp 2020, doanh nghiệp phải bảo đảm luôn có ít nhất một người đại diện theo pháp luật cư trú tại Việt Nam.',
    },
  ],
  nextConversationId: 9000,
  nextMessageId: 8100,
  // Nhiều hội thoại (mô hình ChatGPT). Mỗi hội thoại có lịch sử riêng.
  conversations: [
    {
      id: 7001,
      title: 'Vụ việc SunGroup',
      updated_at: '2026-08-14 09:12',
      messages: [
        { id: 6001, role: 'user', content: 'Khách SUNGROUP đang có mấy vụ việc?', created_at: '2026-08-14 09:10' },
        { id: 6002, role: 'assistant', content: 'Tập đoàn SunGroup hiện có 2 vụ việc đang xử lý: [M-2026-001] Tái cấu trúc vốn SunPhuQuoc (đã quá hạn 3 ngày) và [M-2026-014] Thuê đất thương mại (còn 5 ngày).', created_at: '2026-08-14 09:10' },
      ],
    },
    {
      id: 7002,
      title: 'Thời hiệu khởi kiện thương mại',
      updated_at: '2026-08-13 15:02',
      messages: [
        { id: 6003, role: 'user', content: 'Thời hiệu khởi kiện tranh chấp hợp đồng thương mại là bao lâu?', created_at: '2026-08-13 15:00' },
        { id: 6004, role: 'assistant', content: 'Theo Điều 319 Luật Thương mại 2005, thời hiệu khởi kiện áp dụng đối với tranh chấp thương mại là 2 năm kể từ thời điểm quyền và lợi ích hợp pháp bị xâm phạm.', created_at: '2026-08-13 15:02' },
      ],
    },
  ],
  notes: [
    { id: 501, content: 'Thời hiệu khởi kiện tranh chấp thương mại: 2 năm (Điều 319 LTM 2005).', source_message_id: 6004, created_at: '2026-08-14 09:13' },
    { id: 502, content: 'Nhắc SunGroup gia hạn vụ M-2026-001 — đã quá hạn.', source_message_id: null, created_at: '2026-08-14 09:15' },
  ],
  nextNoteId: 600,
};

/**
 * Giả lập luồng chảy dần: nhả từng chữ với nhịp gần giống model chạy CPU.
 * Nhờ có bản này mà giao diện chảy chữ kiểm chứng được khi backend chưa chạy.
 */
async function mockChatStream(payload, onEvent) {
  const wait = (ms) => new Promise((res) => setTimeout(res, ms));
  // Không có conversation_id → "cuộc trò chuyện mới": tạo hội thoại mới, đặt
  // tiêu đề từ câu hỏi, đúng như backend thật.
  let convObj = mockState.conversations.find(
    (c) => c.id === toIntOrNull(payload.conversation_id)
  );
  if (!convObj) {
    convObj = {
      id: ++mockState.nextConversationId,
      title: (payload.question || 'Cuộc trò chuyện mới').slice(0, 60),
      updated_at: new Date().toISOString().replace('T', ' ').slice(0, 16),
      messages: [],
    };
    mockState.conversations.unshift(convObj);
  }
  const conv = convObj.id;

  onEvent?.({ type: 'start', conversation_id: conv });
  await wait(1200); // giai đoạn model đọc ngữ cảnh — im lặng, chưa có chữ nào

  onEvent?.({
    type: 'meta',
    sources: [
      { n: 1, title: 'Luật Doanh nghiệp số 59/2020/QH14 (Điều 12, Điều 15)', score: 0.94, document_id: 1, drive_file_id: '1AbCdEfGhIjKmock' },
      { n: 2, title: 'Nghị định 01/2021/NĐ-CP về Đăng ký Doanh nghiệp', score: 0.89, document_id: 9 },
    ],
    used_method: null,
  });

  await wait(900); // mô phỏng giai đoạn đọc tài liệu — hiện chỉ báo "đang đọc…"

  const text =
    `Với câu hỏi "${payload.question}": doanh nghiệp **phải thông báo thay đổi** ` +
    'tới Cơ quan Đăng ký Kinh doanh trong thời hạn luật định [Nguồn 1].\n\n' +
    '**Căn cứ pháp lý:**\n' +
    '- khoản 1 Điều 12 Luật Doanh nghiệp số 59/2020/QH14 [Nguồn 1]\n' +
    '- Điều 15 Nghị định 01/2021/NĐ-CP về Đăng ký Doanh nghiệp [Nguồn 2]\n\n' +
    '**Lưu ý thực tiễn:** cần rà soát biên bản họp và quyết định của Hội đồng ' +
    'thành viên trước khi nộp hồ sơ [Nguồn 2].\n\n' +
    '---\n' +
    '*Đây là bản nháp tham khảo — luật sư phụ trách kiểm chứng lại trước khi gửi khách.*';

  const words = text.split(' ');
  for (let i = 0; i < words.length; i += 1) {
    onEvent?.({ type: 'delta', text: (i ? ' ' : '') + words[i] });
    await wait(45);
  }

  const done = {
    type: 'done',
    message_id: ++mockState.nextMessageId,
    latency_ms: 1200 + words.length * 45,
    timings: {
      tim_kiem_ms: 240,
      du_lieu_cong_ty_ms: 60,
      ai_ms: 1200 + words.length * 45,
      load_ms: 0,
      prefill_ms: 1200,
      gen_ms: words.length * 45,
      prompt_tokens: 1840,
      gen_tokens: words.length,
      num_ctx: 8192,
      model: mockState.settings.llm_model || 'qwen3:8b',
      so_doan: 2,
      bo_qua_doan_yeu: 3,
    },
  };
  // Ghi vào hội thoại mock để lịch sử + danh sách phản ánh đúng
  const now = new Date().toISOString().replace('T', ' ').slice(0, 16);
  convObj.messages.push(
    { id: ++mockState.nextMessageId, role: 'user', content: payload.question, created_at: now },
    { id: done.message_id, role: 'assistant', content: text, created_at: now }
  );
  convObj.updated_at = now;
  onEvent?.(done);
  return done;
}

async function handleMockRequest(endpoint, options, headers) {
  await new Promise((res) => setTimeout(res, 200));
  const method = (options.method || 'GET').toUpperCase();
  // Chỉ CÂU TRẢ LỜI (POST) mới cần trễ để giống model suy nghĩ và thấy chỉ báo
  // "đang trả lời…". History/search/notes phải nhanh.
  const isChatAnswer =
    method === 'POST' &&
    (endpoint === '/chat/internal' || endpoint === '/chat/portal' || endpoint === '/chat/public');
  if (isChatAnswer) {
    await new Promise((res) => setTimeout(res, 1300));
  }
  const body = options.body ? JSON.parse(options.body) : {};

  // ---------- Xác thực ----------
  if (endpoint === '/auth/login' && method === 'POST') {
    const email = String(body.email || '').trim().toLowerCase();
    const user = mockState.users.find((u) => u.email.toLowerCase() === email);
    // Mock không kiểm mật khẩu — chỉ để thử giao diện khi backend chưa chạy.
    if (!user) throw new Error('Sai email hoặc mật khẩu');
    const token = `mock_token_${user.id}_${Date.now()}`;
    setAccessToken(token);
    setUserId(user.id);
    return { access_token: token, token_type: 'bearer', user: { ...user } };
  }

  if (endpoint === '/auth/me') {
    const uid = headers['X-User-Id'] || currentUserId || '1';
    const user = mockState.users.find((u) => String(u.id) === String(uid)) || mockState.users[0];
    return { ...user };
  }

  if (endpoint === '/auth/change-password' && method === 'POST') {
    if (!body.new_password || body.new_password.length < 6) {
      throw new Error('Mật khẩu mới tối thiểu 6 ký tự');
    }
    return { ok: true, message: 'Cập nhật mật khẩu thành công.' };
  }

  const uid = headers['X-User-Id'] || '1';
  const me = mockState.users.find((u) => String(u.id) === uid) || mockState.users[0];
  const isReviewer = me.role === 'admin' || me.role === 'ban_qt' || me.can_review;

  // Mô phỏng require_reviewer của backend
  const needsReviewer =
    endpoint.startsWith('/review') ||
    endpoint.startsWith('/learn') ||
    (endpoint.startsWith('/documents') && !endpoint.startsWith('/documents/browse'));
  if (needsReviewer && !isReviewer) {
    throw new Error('Chỉ admin hoặc người được cấp quyền duyệt mới thực hiện được (403)');
  }
  if (endpoint.startsWith('/users') && me.role !== 'admin') {
    throw new Error('Không đủ quyền (403) — chỉ admin quản lý người dùng');
  }

  // ---------- Nhiều hội thoại + tìm kiếm + ghi chú ----------
  if (endpoint.startsWith('/conversations')) {
    const convId = toIntOrNull(endpoint.split('/')[2]);
    if (method === 'GET') {
      return mockState.conversations.map((c) => ({
        id: c.id,
        title: c.title,
        updated_at: c.updated_at,
        message_count: c.messages.length,
      }));
    }
    if (method === 'PATCH') {
      const c = mockState.conversations.find((x) => x.id === convId);
      if (c) c.title = (body.title || 'Cuộc trò chuyện').slice(0, 120);
      return { ok: true, id: convId, title: c ? c.title : '' };
    }
    if (method === 'DELETE') {
      mockState.conversations = mockState.conversations.filter((x) => x.id !== convId);
      return { ok: true, id: convId };
    }
  }
  if (endpoint.startsWith('/chat/history')) {
    const params = new URLSearchParams((endpoint.split('?')[1] || ''));
    const wantId = toIntOrNull(params.get('conversation_id'));
    const c =
      mockState.conversations.find((x) => x.id === wantId) || mockState.conversations[0] || null;
    return c
      ? { conversation_id: c.id, messages: [...c.messages] }
      : { conversation_id: null, messages: [] };
  }
  if (endpoint.startsWith('/chat/search')) {
    const q = decodeURIComponent((endpoint.split('q=')[1] || '').split('&')[0]).toLowerCase();
    if (q.length < 2) return [];
    const hits = [];
    for (const c of mockState.conversations) {
      for (const m of c.messages) {
        if (m.content.toLowerCase().includes(q)) {
          hits.push({ ...m, conversation_id: c.id, conversation_title: c.title });
        }
      }
    }
    return hits.reverse();
  }
  if (endpoint.startsWith('/notes')) {
    const noteId = endpoint.split('/')[2];
    if (method === 'GET') return [...mockState.notes];
    if (method === 'POST') {
      const item = {
        id: ++mockState.nextNoteId,
        content: (body.content || '').trim(),
        source_message_id: body.source_message_id ?? null,
        created_at: new Date().toLocaleString('vi-VN'),
      };
      mockState.notes.unshift(item);
      return { ok: true, ...item };
    }
    if (method === 'DELETE') {
      mockState.notes = mockState.notes.filter((n) => String(n.id) !== String(noteId));
      return { ok: true, id: Number(noteId) };
    }
  }

  // ---------- Hội thoại ----------
  if (endpoint === '/chat/internal' && method === 'POST') {
    const { question, use_temp, use_method } = body;
    let prefix = '';
    if (use_method) {
      prefix +=
        '📋 **[Đã áp dụng mẫu phương pháp phân tích của HDS]**\n' +
        '- Bước 1: Xác định căn cứ pháp luật áp dụng.\n' +
        '- Bước 2: Phân tích quyền và nghĩa vụ các bên.\n' +
        '- Bước 3: Đưa ra khuyến nghị và phương án xử lý.\n\n';
    }
    if (use_temp) {
      prefix += '📎 *(Có tham chiếu tài liệu tạm bạn vừa tải lên trong phiên này)*\n\n';
    }

    return {
      answer: `${prefix}Dựa trên kho văn bản pháp luật và tiền lệ tư vấn của HDS Law Firm:

Với câu hỏi "${question}":

1. **Cơ sở pháp lý**
   - Căn cứ quy định tại Điều 12 Luật Doanh nghiệp 2020 và các văn bản hướng dẫn thi hành hiện hành.
   - Doanh nghiệp có nghĩa vụ tuân thủ trình tự thủ tục hành chính và bảo đảm hồ sơ hợp lệ khi làm việc với Cơ quan Đăng ký Kinh doanh.

2. **Khuyến nghị của luật sư HDS**
   - Rà soát kỹ biên bản họp và quyết định của Hội đồng thành viên / Đại hội đồng cổ đông.
   - Kiểm tra trường hợp có cần chấp thuận trước của cơ quan quản lý chuyên ngành hay không.
   - Chuẩn bị đầy đủ tờ khai và giấy uỷ quyền đại diện thực hiện thủ tục.`,
      sources: [
        { title: 'Luật Doanh nghiệp số 59/2020/QH14 (Điều 12, Điều 15)', relevance_score: 0.94, doc_id: '1' },
        { title: 'Nghị định 01/2021/NĐ-CP về Đăng ký Doanh nghiệp', relevance_score: 0.89, doc_id: '9' },
        { title: 'Sổ tay Thủ tục Pháp lý Doanh nghiệp — HDS Law Firm', relevance_score: 0.82, doc_id: '12' },
      ],
      conversation_id: toIntOrNull(body.conversation_id) ?? ++mockState.nextConversationId,
      latency_ms: 8420,
      message_id: ++mockState.nextMessageId,
      // Số liệu giả nhưng đúng hình dạng máy chủ thật trả về, để bảng phân tích
      // thời gian trong khung chat có cái mà hiển thị khi chạy chế độ giả lập.
      timings: {
        tim_kiem_ms: 240,
        du_lieu_cong_ty_ms: 60,
        ai_ms: 8420,
        load_ms: 0,
        prefill_ms: 2100,
        gen_ms: 6300,
        prompt_tokens: 1840,
        gen_tokens: 320,
        num_ctx: 4096,
        model: 'qwen3:8b',
        so_doan: 3,
        bo_qua_doan_yeu: 2,
      },
    };
  }

  if (endpoint === '/chat/portal' && method === 'POST') {
    return {
      answer: `[Cổng thông tin Khách hàng HDS] Cảm ơn quý khách đã đặt câu hỏi "${body.question}". Luật sư phụ trách sẽ phản hồi chi tiết trong thời gian sớm nhất.`,
      sources: [{ title: 'Tài liệu hướng dẫn dịch vụ pháp lý HDS', relevance_score: 0.9 }],
      conversation_id: toIntOrNull(body.conversation_id) ?? ++mockState.nextConversationId,
      latency_ms: 290,
      quota: { used: 1, limit: me.monthly_quota || 50 },
      message_id: ++mockState.nextMessageId,
    };
  }

  if (endpoint === '/upload' && method === 'POST') {
    if (body.mode === 'save') {
      mockState.stats.cho_duyet_nhan += 1;
      mockState.pendingReviews.unshift({
        id: Date.now(),
        title: body.filename,
        doc_type: 'other',
        access_level: 'internal',
        client_id: null,
        client_name: null,
        confidence: null,
        source_kind: 'chat',
        preview: (body.content || '').substring(0, 180) || 'Nội dung tài liệu tải lên từ giao diện.',
      });
      return { ok: true, mode: 'save', note: 'Đã vào hàng chờ duyệt. Duyệt xong mới thành tri thức lâu dài.' };
    }
    return { ok: true, mode: 'temp', chunks: 3, note: 'File dùng xong bỏ — tự xoá sau 6 giờ, không vào kho.' };
  }

  // ---------- Thống kê ----------
  if (endpoint === '/stats') return { ...mockState.stats };

  // ---------- Duyệt nhãn ----------
  if (endpoint === '/review/pending') return [...mockState.pendingReviews];

  if (/^\/review\/[^/]+\/approve$/.test(endpoint) && method === 'POST') {
    const id = endpoint.split('/')[2];
    mockState.pendingReviews = mockState.pendingReviews.filter((d) => String(d.id) !== String(id));
    mockState.stats.cho_duyet_nhan = Math.max(0, mockState.stats.cho_duyet_nhan - 1);
    mockState.stats.da_duyet_nhan += 1;
    const client = mockState.clients.find((c) => c.id === body.client_id);
    mockState.documents.unshift({
      id: Number(id),
      title: `Tài liệu đã duyệt #${id}`,
      doc_type: body.doc_type || 'other',
      access_level: body.access_level || 'internal',
      summary: 'Tài liệu đã được kiểm duyệt và nạp vào kho tri thức của HDS AI.',
      source_kind: 'chat',
      created_at: new Date().toISOString().slice(0, 10),
      client_name: client ? client.name : null,
      so_doan: 15,
      department: client ? client.department : 'Doanh nghiệp - Đầu tư',
      can_open: true,
    });
    return { ok: true, document_id: Number(id) };
  }

  // ---------- Duyệt hội thoại ----------
  if (endpoint === '/learn/pending') return [...mockState.pendingLearns];

  if (/^\/learn\/[^/]+$/.test(endpoint) && method === 'POST') {
    const msgId = endpoint.split('/')[2];
    mockState.pendingLearns = mockState.pendingLearns.filter(
      (m) => String(m.message_id) !== String(msgId)
    );
    mockState.stats.hoi_thoai_cho_duyet = Math.max(0, mockState.stats.hoi_thoai_cho_duyet - 1);
    if (body.action !== 'reject') mockState.stats.da_hoc += 1;
    return { ok: true, action: body.action };
  }

  // ---------- Mẫu phương pháp (POST phải xét TRƯỚC GET) ----------
  if (endpoint === '/methods' && method === 'POST') {
    const newMethod = {
      id: mockState.methods.length + 1,
      case_type: body.case_type,
      steps: body.steps,
      approved: true,
    };
    mockState.methods.push(newMethod);
    mockState.stats.so_mau_phuong_phap += 1;
    return { ok: true, method_id: newMethod.id };
  }

  if (endpoint === '/methods') return [...mockState.methods];

  // ---------- Tài liệu ----------
  if (endpoint.startsWith('/documents/browse')) {
    const q = (new URL(`http://x${endpoint}`).searchParams.get('q') || '').toLowerCase();
    return mockState.documents
      .filter((d) => !q || d.title.toLowerCase().includes(q) || (d.summary || '').toLowerCase().includes(q))
      .map((d) => {
        const canOpen = isReviewer || d.can_open || d.access_level !== 'client';
        return {
          id: d.id,
          title: canOpen
            ? d.title
            : `[Hồ sơ khách hàng - ${d.department}] 🔒 Tài khoản chưa có quyền xem`,
          doc_type: d.doc_type,
          access_level: d.access_level,
          department: d.department,
          can_open: canOpen,
          summary: canOpen ? d.summary : null,
          created_at: d.created_at,
        };
      });
  }

  if (endpoint.startsWith('/documents')) {
    const params = new URL(`http://x${endpoint}`).searchParams;
    const q = (params.get('q') || '').toLowerCase();
    const docType = params.get('doc_type') || '';
    return mockState.documents.filter(
      (d) =>
        (!q || d.title.toLowerCase().includes(q) || (d.summary || '').toLowerCase().includes(q)) &&
        (!docType || d.doc_type === docType)
    );
  }

  // ---------- Khách hàng ----------
  if (endpoint === '/clients') return [...mockState.clients];

  if (/^\/clients\/[^/]+\/360$/.test(endpoint)) {
    const cid = endpoint.split('/')[2];
    const client = mockState.clients.find((c) => String(c.id) === String(cid)) || mockState.clients[0];
    return {
      client,
      profile:
        mockState.clientProfiles[client.id] || {
          history: null,
          issues: null,
          warnings: null,
          suggestions: null,
        },
      matters: mockState.clientMatters[client.id] || [],
      documents: mockState.clientDocuments[client.id] || [],
    };
  }

  if (/^\/clients\/[^/]+\/profile$/.test(endpoint) && method === 'POST') {
    const cid = endpoint.split('/')[2];
    const stamp = new Date().toLocaleDateString('vi-VN');
    const p = (mockState.clientProfiles[cid] ??= {
      history: '',
      issues: '',
      warnings: '',
      suggestions: '',
    });
    if (body.history_note) p.history = `${p.history || ''}\n- [${stamp}] ${body.history_note}`.trim();
    if (body.issues_note) p.issues = `${p.issues || ''}\n- [${stamp}] ${body.issues_note}`.trim();
    if (body.warnings !== undefined) p.warnings = body.warnings;
    if (body.suggestions !== undefined) p.suggestions = body.suggestions;
    return { ok: true, client_id: Number(cid) };
  }

  if (endpoint === '/departments') return [...mockState.departments];

  // ---------- Người dùng (POST phải xét TRƯỚC GET) ----------
  if (endpoint === '/users' && method === 'POST') {
    const newUser = {
      id: Math.max(...mockState.users.map((u) => u.id)) + 1,
      email: body.email,
      full_name: body.full_name,
      role: body.role || 'chuyen_vien',
      can_review: Boolean(body.can_review),
      active: true,
      client_id: body.client_id ?? null,
      department_ids: body.department_ids || [],
      head_of: body.head_of || [],
      monthly_quota: body.monthly_quota || 0,
    };
    mockState.users.push(newUser);
    return newUser;
  }

  if (endpoint === '/users') return [...mockState.users];

  if (endpoint.includes('/review-permission')) {
    const targetId = endpoint.split('/')[2];
    const grant = endpoint.includes('grant=true');
    const u = mockState.users.find((x) => String(x.id) === String(targetId));
    if (u) u.can_review = grant;
    return { ok: true, user_id: Number(targetId), can_review: grant };
  }

  if (endpoint.includes('/finance-permission')) {
    const targetId = endpoint.split('/')[2];
    const grant = endpoint.includes('grant=true');
    const u = mockState.users.find((x) => String(x.id) === String(targetId));
    if (u) u.can_view_finance = grant;
    return { ok: true, user_id: Number(targetId), can_view_finance: grant };
  }

  if (endpoint.includes('/api-key')) {
    const targetId = Number(endpoint.split('/')[2]);
    const u = mockState.users.find((x) => x.id === targetId);
    if (method === 'DELETE') {
      if (u) u.has_api_key = false;
      return { ok: true, user_id: targetId };
    }
    if (u) u.has_api_key = true;
    return {
      ok: true,
      user_id: targetId,
      api_key: 'hds_GIA_LAP_khong_dung_that_' + Math.random().toString(36).slice(2, 14),
      note: 'Lưu lại ngay — khoá này không hiển thị lại lần nào nữa.',
    };
  }

  // ---------- Cài đặt AI ----------
  if (endpoint === '/settings' && method === 'GET') {
    return {
      settings: { ...mockState.settings },
      editable_keys: Object.keys(mockState.settings),
      defaults: { ...mockState.settings },
    };
  }

  if (/^\/settings\/[^/]+$/.test(endpoint) && method === 'PUT') {
    const key = endpoint.split('/')[2];
    if (key === 'drive_map') JSON.parse(body.value);
    mockState.settings[key] = body.value;
    return { ok: true, key };
  }

  if (/^\/settings\/[^/]+\/reset$/.test(endpoint) && method === 'POST') {
    const key = endpoint.split('/')[2];
    return { ok: true, key, value: mockState.settings[key] };
  }

  if (endpoint === '/drive/sync-status') {
    return {
      configured: true,
      last_run: mockState.driveSyncStatus,
      failures: mockState.ingestFailures,
    };
  }

  if (endpoint.startsWith('/alerts')) {
    const items = [...mockState.matterAlerts];
    return {
      total: items.length,
      urgent: items.filter((x) => x.severity === 'gap').length,
      items,
    };
  }

  if (endpoint.startsWith('/models/benchmark')) {
    return {
      ok: true,
      model: mockState.settings.llm_model || 'qwen3:8b',
      prompt_tokens: 1340,
      gen_tokens: 12,
      load_ms: 0,
      prefill_ms: 1850,
      gen_ms: 900,
      total_ms: 2750,
      read_tok_s: 724,
      write_tok_s: 13.3,
      uoc_tinh_giay: 56.4,
    };
  }

  if (endpoint === '/models') {
    return {
      ollama: true,
      available: ['qwen3:8b', 'qwen2.5:14b', 'llama3.1:8b', 'bge-m3'],
      generation: ['qwen3:8b', 'qwen2.5:14b', 'llama3.1:8b'],
      loaded: ['qwen3:8b', 'bge-m3'],
      current: mockState.settings.llm_model || 'qwen3:8b',
      current_ready: true,
      embed_model: 'bge-m3',
      embed_ready: true,
    };
  }

  // ---------- Báo cáo chất lượng ----------
  if (/^\/feedback\/\d+$/.test(endpoint) && method === 'DELETE') {
    const fid = Number(endpoint.split('/')[2]);
    mockState.feedback = mockState.feedback.filter((f) => f.id !== fid);
    return { ok: true, id: fid };
  }

  if (endpoint === '/feedback' && method === 'POST') {
    const item = {
      id: Date.now(),
      message_id: body.message_id,
      rating: body.rating,
      note: body.note || null,
      created_at: new Date().toLocaleString('vi-VN'),
      reporter: me.full_name,
      reporter_role: me.role,
      question: '(câu hỏi trong phiên chat hiện tại)',
      answer: '(câu trả lời được báo cáo)',
    };
    mockState.feedback.unshift(item);
    // Báo cáo 'chưa tốt' đi thẳng vào hàng chờ Duyệt câu trả lời bị báo cáo
    if (body.rating === 'bad') {
      mockState.pendingLearns.unshift({
        message_id: body.message_id,
        question: '(câu hỏi trong phiên chat hiện tại)',
        answer: '(câu trả lời bị báo cáo — bạn sửa lại rồi lưu để dạy AI)',
        created_at: new Date().toLocaleString('vi-VN'),
        note: body.note || null,
        reporter: me.full_name,
        report_count: 1,
        reported_at: new Date().toLocaleString('vi-VN'),
      });
      mockState.stats.hoi_thoai_cho_duyet += 1;
    }
    return { ok: true, feedback_id: item.id };
  }

  if (endpoint === '/feedback/pending') return [...mockState.feedback];

  if (/^\/feedback\/[^/]+\/review$/.test(endpoint) && method === 'POST') {
    const fid = endpoint.split('/')[2];
    mockState.feedback = mockState.feedback.filter((f) => String(f.id) !== String(fid));
    mockState.stats.bao_cao_cho_xu_ly = Math.max(0, mockState.stats.bao_cao_cho_xu_ly - 1);
    if (body.action === 'apply') mockState.stats.da_hoc += 1;
    return { ok: true, feedback_id: Number(fid), action: body.action };
  }

  throw new Error(`Đường dẫn chưa được hỗ trợ trong chế độ giả lập: ${endpoint}`);
}
