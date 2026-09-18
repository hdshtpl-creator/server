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

/** Luồng trả lời im lặng quá bấy nhiêu mili giây thì coi như kết nối đã chết.
 *  Máy chủ phát nhịp tim mỗi 15 giây (HEARTBEAT_SEC trong api.py) nên đây là
 *  5 nhịp liên tiếp mất tăm — đủ rộng để không cắt nhầm lượt trả lời chậm
 *  trên máy CPU, đủ chặt để người dùng không ngồi trước khung chat khoá cứng. */
const SSE_SILENCE_MS = 75_000;

/** Mã lỗi của lượt bị NGƯỜI DÙNG bấm "Dừng" — khác hẳn lỗi mạng: không phải
 *  sự cố, không báo đỏ, chỉ chốt lại phần chữ đã viết được. */
export const DUNG_BOI_NGUOI_DUNG = 'hds/dung-boi-nguoi-dung';

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
  { question, conversation_id, use_temp, use_method, model, source_document_ids,
    mode, template_doc_id, make_files, bo_mau_id, bo_mau_file_ids, signal },
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
    // Tab "Kiểm tra pháp lý & tạo file mẫu" — backend bỏ qua với vai khách.
    mode: mode || undefined,
    template_doc_id: toIntOrNull(template_doc_id) ?? undefined,
    make_files: make_files ? true : undefined,
    // Bộ mẫu hồ sơ đang chọn dưới khung chat — máy chủ chỉ điền khi lượt là
    // lệnh tạo file (make_files hoặc câu "tạo bộ hồ sơ…").
    bo_mau_id: toIntOrNull(bo_mau_id) ?? undefined,
    bo_mau_file_ids: Array.isArray(bo_mau_file_ids) && bo_mau_file_ids.length
      ? bo_mau_file_ids.map(toIntOrNull).filter((id) => id !== null)
      : undefined,
  };

  // `signal` không đi vào thân yêu cầu (payload gửi lên máy chủ) — chỉ chuyền
  // riêng cho bản giả lập để nó cũng dừng được.
  if (useMockBackend) return mockChatStream({ ...payload, signal }, onEvent);

  // ĐỒNG HỒ CANH IM LẶNG. Máy chủ phát nhịp tim ': hb' mỗi 15 giây kể cả khi
  // model đang nghĩ (HEARTBEAT_SEC trong api.py), nên byte luôn về đều đặn.
  // Im quá 5 nhịp = kết nối đã chết: backend khởi động lại giữa chừng, máy
  // tính ngủ dậy, rớt Wi-Fi, hoặc proxy giữ một socket rỗng. Trong những ca
  // đó reader.read() KHÔNG bao giờ trả về mà cũng KHÔNG báo lỗi — không có
  // đồng hồ này thì lời gọi treo vĩnh viễn, khối finally bên ChatLayout không
  // chạy, cờ isChatStreaming kẹt true và cả khung chat xám ngắt: ô nhập bị
  // khoá, nút "Cuộc trò chuyện mới" mờ 40%, người dùng phải tải lại trang mới
  // gõ tiếp được. Hết giờ thì huỷ kết nối để lỗi nổi lên và giao diện mở lại.
  const control = new AbortController();
  let lastByteAt = Date.now();
  let imLang = false;
  const watchdog = setInterval(() => {
    if (Date.now() - lastByteAt > SSE_SILENCE_MS) {
      imLang = true;
      control.abort();
    }
  }, 5000);
  const loiImLang = () =>
    new Error(
      'Máy chủ ngừng phản hồi giữa chừng (mất mạng hoặc backend vừa khởi động lại). ' +
        'Câu trả lời này chưa được lưu — hãy gửi lại câu hỏi.'
    );
  const loiDung = () =>
    Object.assign(new Error('Đã dừng theo yêu cầu.'), { code: DUNG_BOI_NGUOI_DUNG });

  // Nút "Dừng" của giao diện đi vào đây. Đóng kết nối cũng chính là cách báo
  // cho máy chủ: Starlette đóng generator SSE, backend bật cờ huỷ và model
  // ngừng sinh chữ ngay (xem rag.answer_stream) — không chỉ là giấu chữ đi.
  let nguoiDungDung = false;
  const dung = () => {
    nguoiDungDung = true;
    control.abort();
  };
  if (signal) {
    if (signal.aborted) dung();
    else signal.addEventListener('abort', dung, { once: true });
  }

  try {
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
        signal: control.signal,
      });
    } catch (err) {
      if (nguoiDungDung) throw loiDung();
      if (imLang) throw loiImLang();
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
      let value;
      let done;
      try {
        ({ value, done } = await reader.read());
      } catch (err) {
        if (nguoiDungDung) throw loiDung();
        if (imLang) throw loiImLang();
        throw err;
      }
      if (done) break;
      // MỌI byte đều tính, kể cả nhịp tim ': hb' (không mở đầu bằng 'data:'
      // nên không sinh sự kiện) — chính nó chứng minh kết nối còn sống.
      lastByteAt = Date.now();
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
  } finally {
    clearInterval(watchdog);
    if (signal) signal.removeEventListener('abort', dung);
  }
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
export async function listConversations(limit = 100, kind = 'chat') {
  // kind: 'chat' (tab Hoi thoai AI) | 'legal' (tab Kiem tra phap ly) | 'all'.
  const qs = new URLSearchParams({ limit: String(Number(limit) || 100), kind });
  return request(`/conversations?${qs.toString()}`, { method: 'GET' });
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
// PUT /review/{id}/content — lưu bản sửa KÈM LÝ DO (kế hoạch ngày 3: mỗi lần
// chỉnh sửa ghi nhận vì sao). Backend cất bản cũ vào document_versions.
export async function saveReviewContent(id, content, edit_reason = 'sua_loi_trich_xuat', edit_note = '') {
  return request(`/review/${id}/content`, {
    method: 'PUT',
    body: JSON.stringify({ content, edit_reason, edit_note: edit_note || null }),
  });
}

// ==================== HOÀN THIỆN GIAI ĐOẠN 1 (15/09/2026) ====================

/** Tải file về từ một endpoint GET có xác thực; tên file lấy từ Content-Disposition. */
async function downloadGet(path, fallbackName) {
  if (useMockBackend) {
    triggerDownload(new Blob(['Bản demo — chỉ xuất tệp khi kết nối backend thật.'], {
      type: 'text/plain;charset=utf-8',
    }), fallbackName.replace(/\.docx$/, '.txt'));
    return;
  }
  const res = await fetch(`${apiBaseUrl}${path}`, {
    method: 'GET',
    headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
  });
  if (!res.ok) {
    const rawText = await res.text().catch(() => '');
    throw new Error(parseErrorBody(rawText, res.status));
  }
  const blob = await res.blob();
  const cd = res.headers.get('Content-Disposition') || '';
  const m = cd.match(/filename\*=UTF-8''([^;]+)/i) || cd.match(/filename="?([^";]+)"?/i);
  triggerDownload(blob, m ? decodeURIComponent(m[1]) : fallbackName);
}

async function downloadPost(path, body, fallbackName) {
  if (useMockBackend) {
    triggerDownload(new Blob(['Bản demo — chỉ xuất tệp khi kết nối backend thật.'], {
      type: 'text/plain;charset=utf-8',
    }), fallbackName.replace(/\.docx$/, '.txt'));
    return;
  }
  const res = await fetch(`${apiBaseUrl}${path}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const rawText = await res.text().catch(() => '');
    throw new Error(parseErrorBody(rawText, res.status));
  }
  const blob = await res.blob();
  const cd = res.headers.get('Content-Disposition') || '';
  const m = cd.match(/filename\*=UTF-8''([^;]+)/i) || cd.match(/filename="?([^";]+)"?/i);
  triggerDownload(blob, m ? decodeURIComponent(m[1]) : fallbackName);
}

// --- So sánh phiên bản bản thảo (kế hoạch ngày 8) ---
export async function compareDraftVersions(draftId, tu, den) {
  const qs = new URLSearchParams();
  if (tu) qs.set('tu', String(tu));
  if (den) qs.set('den', String(den));
  const q = qs.toString();
  return request(`/drafts/${toIntOrNull(draftId)}/compare${q ? `?${q}` : ''}`, { method: 'GET' });
}
export async function exportDraftCompare(draftId, tu, den, filename) {
  return downloadGet(
    `/drafts/${toIntOrNull(draftId)}/compare/export?tu=${tu}&den=${den}`,
    filename || `so-sanh-v${tu}-v${den}.docx`,
  );
}

// --- Kiểm tra mâu thuẫn pháp lý chạy nền (kế hoạch ngày 9) ---
export async function getDraftChecks(draftId) {
  const data = await request(`/drafts/${toIntOrNull(draftId)}/checks`, { method: 'GET' });
  return Array.isArray(data) ? data : data?.items || [];
}
export async function runDraftCheck(draftId, dongBo = false) {
  const data = await request(`/drafts/${toIntOrNull(draftId)}/checks${dongBo ? '?dong_bo=true' : ''}`, {
    method: 'POST',
  });
  return data?.items || [];
}

// --- Khách quan tâm từ website ---
export async function getLeads(status = '', limit = 200) {
  const qs = new URLSearchParams();
  if (status) qs.set('status', status);
  qs.set('limit', String(limit));
  return request(`/leads?${qs.toString()}`, { method: 'GET' });
}
export async function updateLead(leadId, { status, note } = {}) {
  return request(`/leads/${toIntOrNull(leadId)}`, {
    method: 'PATCH',
    body: JSON.stringify({ status: status || null, note: note ?? null }),
  });
}

// --- Nhật ký hệ thống (chỉ đọc) ---
export async function getAuditLog({ limit = 100, offset = 0, action = '', user_id = null, q = '' } = {}) {
  const qs = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (action) qs.set('action', action);
  if (user_id) qs.set('user_id', String(user_id));
  if (q) qs.set('q', q);
  return request(`/audit?${qs.toString()}`, { method: 'GET' });
}
export async function getAuditActions() {
  const data = await request('/audit/actions', { method: 'GET' });
  return data?.items || [];
}

// --- Lịch sử phiên bản tài liệu kho + so sánh ---
export async function getDocumentVersions(docId) {
  return request(`/documents/${toIntOrNull(docId)}/versions`, { method: 'GET' });
}
export async function getDocumentVersion(docId, versionNo) {
  return request(`/documents/${toIntOrNull(docId)}/versions/${versionNo}`, { method: 'GET' });
}
export async function compareDocumentVersions(docId, tu, den) {
  return request(`/documents/${toIntOrNull(docId)}/versions/compare?tu=${tu}&den=${den}`, { method: 'GET' });
}
export async function exportDocumentCompare(docId, tu, den, filename) {
  return downloadGet(
    `/documents/${toIntOrNull(docId)}/versions/compare/export?tu=${tu}&den=${den}`,
    filename || `tai-lieu-${docId}-so-sanh-v${tu}-v${den}.docx`,
  );
}

// --- Rà soát rủi ro theo danh mục điều khoản chuẩn (kế hoạch ngày 7–8) ---
export async function getRaSoatLoai() {
  const data = await request('/legal/ra-soat/loai', { method: 'GET' });
  return data?.items || [];
}
export async function raSoatHopDong({ text, temp_file_id, draft_id, document_id, loai, tieu_de, tra_luat = true } = {}) {
  return request('/legal/ra-soat', {
    method: 'POST',
    body: JSON.stringify({
      text: text || null,
      temp_file_id: toIntOrNull(temp_file_id),
      draft_id: toIntOrNull(draft_id),
      document_id: toIntOrNull(document_id),
      loai: loai || null,
      tieu_de: tieu_de || null,
      tra_luat: Boolean(tra_luat),
    }),
  });
}
export async function exportRaSoat(ket_qua, tieu_de, filename) {
  return downloadPost('/legal/ra-soat/export', { ket_qua, tieu_de }, filename || 'ra-soat-rui-ro.docx');
}

export async function approveReview(id, { doc_type, access_level, client_id, ...vanBanMeta }) {
  const clientId = toIntOrNull(client_id);
  if (access_level === 'client' && clientId === null) {
    throw new Error('Tài liệu mức "Hồ sơ khách hàng" bắt buộc phải chọn khách hàng.');
  }
  // vanBanMeta: so_hieu / loai_van_ban / trich_yeu / ngay_ban_hanh /
  // ngay_hieu_luc / trang_thai_hieu_luc — chỉ gửi trường có mặt (backend hiểu
  // "không gửi" là "không đổi").
  return request(`/review/${id}/approve`, {
    method: 'POST',
    body: JSON.stringify({
      doc_type,
      access_level,
      client_id: clientId,
      ...vanBanMeta,
    }),
  });
}

// ==================== 4. DUYỆT HỘI THOẠI (TỰ HỌC) ====================

export async function getPendingLearns() {
  return request('/learn/pending', { method: 'GET' });
}

export async function reviewLearnMessage(
  message_id,
  { action, edited_content, edit_reason, access_level }
) {
  return request(`/learn/${message_id}`, {
    method: 'POST',
    body: JSON.stringify({
      action, // 'approve' | 'edit' | 'reject'
      edited_content: edited_content || undefined,
      edit_reason: edit_reason || undefined,
      // Không gửi thì máy chủ mặc định 'internal' — người duyệt phải chủ động
      // chọn 'public' nếu muốn câu này trả lời được cả ở kênh người dân.
      access_level: access_level || undefined,
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

// GET /documents/{id}/detail — thẻ căn cước tài liệu + văn bản liên quan hai chiều
export async function getDocumentDetail(docId) {
  return request(`/documents/${docId}/detail`, { method: 'GET' });
}

// POST /documents/{id}/relations — người duyệt nối tay một quan hệ văn bản
export async function addDocumentRelation(docId, { loai, so_hieu_dich, ten_dich, ghi_chu }) {
  return request(`/documents/${docId}/relations`, {
    method: 'POST',
    body: JSON.stringify({ loai, so_hieu_dich, ten_dich, ghi_chu }),
  });
}

// DELETE /documents/{id}/relations/{relId} — gỡ một dòng quan hệ sai
export async function deleteDocumentRelation(docId, relId) {
  return request(`/documents/${docId}/relations/${relId}`, { method: 'DELETE' });
}

// PUT /documents/{id}/van-ban — sửa danh tính văn bản của tài liệu đã duyệt
export async function updateDocumentVanBan(docId, meta) {
  return request(`/documents/${docId}/van-ban`, {
    method: 'PUT',
    body: JSON.stringify(meta),
  });
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

// ==================== 9b. CÂY THƯ MỤC KHO TRÊN TRANG TỔNG QUAN ====================
// Backend: app/kho.py — đường dẫn là TƯƠNG ĐỐI trong kho, dấu / xuôi.

function mockKhoTang(path) {
  const goc = {
    path: '', ten: 'Kho tài liệu', root: '/home/pc/hds-ai-full/hds-ai/data/raw',
    thu_muc: [
      { ten: '1. VĂN BẢN LUẬT', path: '1. VĂN BẢN LUẬT', so_file: 63, da_hoc: 63, cho_duyet: 0, tong_ban_ghi: 63 },
      { ten: '2. BẢN ÁN - ÁN LỆ', path: '2. BẢN ÁN - ÁN LỆ', so_file: 32895, da_hoc: 32895, cho_duyet: 0, tong_ban_ghi: 32895 },
    ],
    tap_tin: [], tong_tap_tin: 0, offset: 0, limit: 200,
  };
  if (!path) return goc;
  return {
    path, ten: path.split('/').pop(), root: goc.root, thu_muc: [], offset: 0, limit: 200, tong_tap_tin: 2,
    tap_tin: [
      { ten: 'Bộ-luật-91-2015-QH13.docx', path: `${path}/Bộ-luật-91-2015-QH13.docx`, kich_thuoc: 812345,
        sua_luc: '2026-09-01 10:00', trang_thai: 'da_hoc', document_id: 399, title: 'Bộ-luật-91-2015-QH13',
        doc_type: 'law', access_level: 'public', so_hieu: '91/2015/QH13', client_name: null, so_doan: 690, loi: null },
      { ten: 'ghi-chu.pdf', path: `${path}/ghi-chu.pdf`, kich_thuoc: 12345, sua_luc: '2026-09-10 08:00',
        trang_thai: 'chua_hoc', document_id: null, title: null, doc_type: null, access_level: null,
        so_hieu: null, client_name: null, so_doan: null, loi: null },
    ],
  };
}

// GET /kho/cay — một tầng: thư mục con (kèm số đã học) + file trong thư mục
export async function getKhoTang({ path = '', q = '', offset = 0, limit = 200 } = {}) {
  if (useMockBackend) return mockKhoTang(path);
  const params = new URLSearchParams({ path, offset: String(offset), limit: String(limit) });
  if (q) params.append('q', q);
  return request(`/kho/cay?${params.toString()}`, { method: 'GET' });
}

// GET /kho/ho-so-khach — MỌI thư mục khách trên đĩa (kể cả trống) + số tệp theo nhãn học
function mockThuMucKhach(q, loc, offset, limit) {
  const dem = (o = {}) => ({ da_hoc: 0, canh_bao: 0, cho_duyet: 0, chua_hoc: 0, loi: 0, khong_ho_tro: 0, ...o });
  const goc = '9. HỒ SƠ KHÁCH HÀNG';
  const tat_ca = [
    { ten: '9. CHI NHÁNH CÔNG TY TNHH KIỂM TOÁN DFK VIỆT NAM', ma: '9', ten_khach: 'CHI NHÁNH CÔNG TY TNHH KIỂM TOÁN DFK VIỆT NAM',
      client_id: 3, client_name: 'CHI NHÁNH CÔNG TY TNHH KIỂM TOÁN DFK VIỆT NAM', ly_do: null, so_file: 380,
      dem: dem({ da_hoc: 366, cho_duyet: 9, chua_hoc: 2, loi: 1, khong_ho_tro: 2 }), tinh_trang: 'mot_phan' },
    { ten: '1000. Anh Huy Siam', ma: '1000', ten_khach: 'Anh Huy Siam', client_id: 41, client_name: 'Anh Huy Siam', ly_do: null,
      so_file: 2, dem: dem({ da_hoc: 2 }), tinh_trang: 'da_hoc' },
    { ten: '1001. Lâm Ngọc Minh', ma: '1001', ten_khach: 'Lâm Ngọc Minh', client_id: null, client_name: null, ly_do: null,
      so_file: 0, dem: dem(), tinh_trang: 'trong' },
    { ten: '1004. Hồ Ngọc Hiệp', ma: '1004', ten_khach: 'Hồ Ngọc Hiệp', client_id: 44, client_name: 'Hồ Ngọc Hiệp', ly_do: null,
      so_file: 5, dem: dem({ da_hoc: 3, cho_duyet: 2 }), tinh_trang: 'mot_phan' },
    { ten: '1006. CÔNG TY TNHH THƯƠNG MẠI VÀ DỊCH VỤ AGRITECK', ma: '1006', ten_khach: 'CÔNG TY TNHH THƯƠNG MẠI VÀ DỊCH VỤ AGRITECK',
      client_id: null, client_name: null, ly_do: null, so_file: 0, dem: dem(), tinh_trang: 'trong' },
    { ten: '1076. Đinh Thị Thu Thủy', ma: '1076', ten_khach: 'Đinh Thị Thu Thủy', client_id: null, client_name: null, ly_do: null,
      so_file: 2, dem: dem({ khong_ho_tro: 2 }), tinh_trang: 'khong_doc_duoc' },
    { ten: '1755. MAI NGỌC SƠN', ma: '1755', ten_khach: 'MAI NGỌC SƠN', client_id: 301, client_name: 'MAI NGỌC SƠN', ly_do: null,
      so_file: 4, dem: dem({ da_hoc: 1, loi: 1, chua_hoc: 2 }), tinh_trang: 'mot_phan' },
    { ten: 'Ms Vân (TEEL)', ma: null, ten_khach: null, client_id: null, client_name: null,
      ly_do: "Chưa tách được mã khách từ tên thư mục — đặt tên dạng '1729. Tên công ty' hoặc '[MÃ] Tên khách' rồi bộ quét sẽ học",
      so_file: 3, dem: dem({ chua_hoc: 3 }), tinh_trang: 'bo_qua' },
  ].map((d) => ({ ...d, path: `${goc}/${d.ten}` }));
  const tong = { tong_thu_muc: tat_ca.length, tong_tep: 0,
    theo_tinh_trang: { trong: 0, bo_qua: 0, khong_doc_duoc: 0, chua_hoc: 0, cho_duyet: 0, mot_phan: 0, da_hoc: 0 }, dem: dem() };
  for (const d of tat_ca) {
    tong.tong_tep += d.so_file;
    tong.theo_tinh_trang[d.tinh_trang] += 1;
    for (const k of Object.keys(tong.dem)) tong.dem[k] += d.dem[k];
  }
  const qq = (q || '').toLowerCase();
  const ket = tat_ca.filter((d) => {
    if (loc === 'co_tep' && d.so_file === 0) return false;
    if (loc === 'can_xu_ly' && (d.tinh_trang === 'trong' || d.tinh_trang === 'da_hoc')) return false;
    if (loc && loc !== 'co_tep' && loc !== 'can_xu_ly' && d.tinh_trang !== loc) return false;
    return !qq || d.ten.toLowerCase().includes(qq);
  });
  return { goc: [goc], tong, thu_muc: ket.slice(offset, offset + limit), tong_khop: ket.length, offset, limit };
}

function mockTepThuMucKhach(path) {
  const ten = path.split('/').pop();
  const tep = (t, sub, trang_thai, extra = {}) => ({
    ten: t, path: `${path}/${sub ? sub + '/' : ''}${t}`, kich_thuoc: 120000, sua_luc: '2026-09-12 08:00',
    trang_thai, document_id: null, title: null, doc_type: null, access_level: null, so_hieu: null,
    client_name: null, so_doan: null, loi: null, thu_muc_con: sub, ...extra });
  const tap_tin = ten.startsWith('1001.') || ten.startsWith('1006.') ? [] : [
    tep('CCCD.jpg', '1. Thông tin khách hàng', 'da_hoc', { document_id: 501, title: 'CCCD', so_doan: 1 }),
    tep('Giấy ủy quyền.docx', '2. Dự án/896. Thành lập chi nhánh/2. Hồ sơ soạn thảo', 'cho_duyet', { document_id: 502, title: 'Giấy ủy quyền' }),
    tep('Điều lệ.pdf', '2. Dự án/896. Thành lập chi nhánh/3. Hồ sơ hoàn thiện', 'chua_hoc'),
    tep('Scan GPKD.pdf', '2. Dự án/896. Thành lập chi nhánh/5. Kết quả', 'loi', { loi: { code: 'no_text', message: 'PDF scan không có lớp chữ', hint: 'OCR không đọc được — quét lại rõ hơn' } }),
    tep('ho-so.zip', '2. Dự án/896. Thành lập chi nhánh/5. Kết quả', 'khong_ho_tro'),
  ];
  const d = mockThuMucKhach('', '', 0, 100).thu_muc.find((x) => x.path === path) || {
    ten, path, ma: null, ten_khach: null, client_id: null, client_name: null, ly_do: null, so_file: tap_tin.length,
    dem: { da_hoc: 0, canh_bao: 0, cho_duyet: 0, chua_hoc: 0, loi: 0, khong_ho_tro: 0 }, tinh_trang: 'chua_hoc' };
  return { ...d, tap_tin, so_thu_muc_con: tap_tin.length ? 7 : 2 };
}

export async function getThuMucKhach({ q = '', loc = '', offset = 0, limit = 100 } = {}) {
  if (useMockBackend) return mockThuMucKhach(q, loc, offset, limit);
  const params = new URLSearchParams({ offset: String(offset), limit: String(limit) });
  if (q) params.append('q', q);
  if (loc) params.append('loc', loc);
  return request(`/kho/ho-so-khach?${params.toString()}`, { method: 'GET' });
}

// GET /kho/ho-so-khach/tep?path= — từng tệp trong MỘT thư mục khách kèm nhãn học
export async function getTepThuMucKhach(path) {
  if (useMockBackend) return mockTepThuMucKhach(path);
  const params = new URLSearchParams({ path });
  return request(`/kho/ho-so-khach/tep?${params.toString()}`, { method: 'GET' });
}

// GET /kho/tim?q= — tìm tài liệu đã có bản ghi, trả kèm thư mục chứa
export async function timTrongKho(q) {
  if (useMockBackend) return [];
  const params = new URLSearchParams({ q });
  return request(`/kho/tim?${params.toString()}`, { method: 'GET' });
}

// POST /kho/go — gỡ tài liệu (admin): bot ngừng dùng, file sang thùng đã gỡ
export async function goTaiLieuKho(documentId) {
  if (useMockBackend) return { ok: true, document_id: documentId, da_chuyen_toi: null };
  return request('/kho/go', {
    method: 'POST',
    body: JSON.stringify({ document_id: toIntOrNull(documentId) }),
  });
}

// POST /kho/hoc — học ngay một file đang nằm trong kho
export async function hocFileKho({ path, auto_approve = false }) {
  if (useMockBackend) return { ok: true, document_id: Date.now(), trang_thai: 'cho_duyet', warnings: [], note: 'Đã học (giả lập).' };
  return request('/kho/hoc', {
    method: 'POST',
    body: JSON.stringify({ path, auto_approve: Boolean(auto_approve) }),
  });
}

// POST /kho/quet — khởi động bộ quét cả kho chạy nền (theo dõi qua /drive/sync-status)
export async function quetKho() {
  if (useMockBackend) return { ok: true, pid: 0, started_at: new Date().toISOString() };
  return request('/kho/quet', { method: 'POST' });
}

// GET /kho/tien-do — nhịp học tài liệu cho thẻ theo dõi trên Tổng quan.
// Nhẹ và thăm dò dày (8 giây/lần khi đang quét) nên mọi con số lấy từ CSDL,
// không đi đếm file trên đĩa.
export async function getTienDoHoc() {
  if (useMockBackend) {
    const dangChay = Math.floor(Date.now() / 20000) % 2 === 0;
    return {
      quet: {
        dang_chay: dangChay,
        started_at: dangChay ? new Date(Date.now() - 4 * 60000).toISOString() : null,
        pid: dangChay ? 12345 : null,
        nguon: dangChay ? 'web' : null,
        log_tail: dangChay
          ? ['   [MỚI] Hop dong thue nha.pdf  ← 3. HỢP ĐỒNG  → contract',
             '   [CẬP NHẬT] Quy trinh khoi kien.docx  ← 6. QUY TRÌNH  → quy_trinh']
          : [],
        ket_thuc: null,
      },
      nhip: { phut_10: dangChay ? 7 : 0, gio_1: 24, hom_nay: 96, cap_nhat_gio_1: 3 },
      tong: { tai_lieu: 1480, cho_duyet: 12, loi: 2 },
      tu_luc_quet: dangChay ? 7 : null,
      lan_cuoi: {
        finished_at: new Date(Date.now() - 9 * 60000).toISOString(),
        started_at: new Date(Date.now() - 12 * 60000).toISOString(),
        quet: 332, moi: 18, cap_nhat: 4, khong_doi: 310, loi: 0,
      },
    };
  }
  return request('/kho/tien-do');
}

// GET /users/su-dung — admin xem từng người dùng đã làm gì, giữ bao nhiêu dung lượng.
export async function getSuDungNguoiDung() {
  if (useMockBackend) {
    return {
      giu_ngay: 7,
      tong_dung_luong: 18_432_000,
      khong_ro_chu: { so_file: 2, bytes: 240_000 },
      items: [
        { id: 1, full_name: 'Quản trị hệ thống', email: 'admin@hdslaw.vn', role: 'admin',
          active: true, hoi_thoai: 42, tin_nhan: 318, ban_nhap: 9, tai_lieu_da_nap: 120,
          file_dang_giu: 14, dung_luong: 12_800_000, hoat_dong_cuoi: '2026-09-18 11:20:00' },
        { id: 4, full_name: 'Nguyễn Thị Hương', email: 'huong@hdslaw.vn', role: 'chuyen_vien',
          active: true, hoi_thoai: 15, tin_nhan: 96, ban_nhap: 3, tai_lieu_da_nap: 8,
          file_dang_giu: 5, dung_luong: 5_392_000, hoat_dong_cuoi: '2026-09-18 09:05:00' },
      ],
    };
  }
  return request('/users/su-dung');
}

// POST /kho/thu-muc — tạo thư mục con trong kho
export async function taoThuMucKho({ path = '', ten }) {
  if (useMockBackend) return { ok: true, path: path ? `${path}/${ten}` : ten, ten };
  return request('/kho/thu-muc', {
    method: 'POST',
    body: JSON.stringify({ path, ten }),
  });
}

// POST /kho/tai-len — tải một hay nhiều file vào đúng thư mục rồi học ngay từng file
export async function taiLenKho({ path, files, auto_approve = false, onProgress }) {
  if (useMockBackend) {
    await new Promise((r) => setTimeout(r, 300));
    if (onProgress) onProgress(100);
    return {
      ok: true,
      ket_qua: Array.from(files).map((f) => ({
        ok: true, filename: f.name, bytes: f.size, trang_thai: auto_approve ? 'da_hoc' : 'cho_duyet',
        note: auto_approve ? 'Đã học, bot dùng được ngay.' : 'Đã học, đang chờ duyệt nhãn.',
      })),
    };
  }
  const form = new FormData();
  form.append('path', path);
  form.append('auto_approve', String(Boolean(auto_approve)));
  Array.from(files).forEach((f) => form.append('files', f));
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${apiBaseUrl}/kho/tai-len`);
    if (accessToken) xhr.setRequestHeader('Authorization', `Bearer ${accessToken}`);
    xhr.upload.onprogress = (e) => {
      if (onProgress && e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
    };
    xhr.onload = () => {
      let data = {};
      try { data = JSON.parse(xhr.responseText); } catch { /* rơi xuống nhánh lỗi */ }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data);
      else reject(new Error(parseErrorBody(xhr.responseText, xhr.status)));
    };
    xhr.onerror = () => reject(new Error('Không kết nối được máy chủ khi tải tệp lên.'));
    xhr.send(form);
  });
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

// DELETE /drafts/{id} — xoá hẳn bản nháp cùng mọi phiên bản (không khôi phục).
export async function deleteDraft(draftId) {
  return request(`/drafts/${toIntOrNull(draftId)}`, { method: 'DELETE' });
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

export async function exportDraft(draftId, filename, format = 'docx') {
  // format: 'docx' | 'pdf' | 'md'. PDF do LibreOffice tren may chu chuyen tu
  // chinh ban .docx nen bo cuc giong het, khong phai ban dung lai.
  const dinhDang = ['docx', 'pdf', 'md'].includes(format) ? format : 'docx';
  if (useMockBackend) {
    const blob = new Blob(['Bản demo — chỉ xuất tệp khi kết nối backend thật.'], {
      type: 'text/plain;charset=utf-8',
    });
    triggerDownload(blob, filename || `ban-nhap-${draftId}.txt`);
    return;
  }
  const res = await fetch(
    `${apiBaseUrl}/drafts/${toIntOrNull(draftId)}/export?format=${dinhDang}`, {
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
  triggerDownload(
    blob, filename || (m ? decodeURIComponent(m[1]) : `ban-nhap-${draftId}.${dinhDang}`));
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
  const tuMayChu = m ? decodeURIComponent(m[1]) : null;
  // Tên các màn hình truyền vào là TIÊU ĐỀ tài liệu, thường KHÔNG có đuôi
  // ("Thư tư vấn mẫu") — lưu ra máy thành file không đuôi thì Windows không
  // biết mở bằng gì. Giữ tiêu đề tiếng Việt cho dễ đọc nhưng mượn đuôi của
  // tên máy chủ trả về.
  const coDuoi = (n) => /\.[A-Za-z0-9]{1,8}$/.test(n || '');
  const duoi = tuMayChu && coDuoi(tuMayChu) ? tuMayChu.match(/\.[A-Za-z0-9]{1,8}$/)[0] : '';
  let ten = filename || tuMayChu || `tai-lieu-${docId}`;
  if (filename && !coDuoi(filename) && duoi) ten = filename + duoi;
  triggerDownload(blob, ten);
}

function triggerDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  // Tiêu đề tài liệu có thể chứa dấu gạch chéo ("HĐ 05/2026") — thay đi để
  // trình duyệt không cắt tên file thành thư mục.
  a.download = String(filename || '').replace(/[\\/]+/g, '-');
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// ==================== 13. KIỂM TRA PHÁP LÝ & TẠO FILE MẪU ====================

// POST /conversations — tạo hội thoại nội bộ TRƯỚC câu hỏi đầu tiên, để đính
// kèm file trước rồi mới hỏi. `kind` quyết định hội thoại hiện ở cột lịch sử
// nào: 'legal' = tab Kiểm tra pháp lý, 'chat' = tab Hội thoại AI.
export async function createConversation(kind = 'legal') {
  const safeKind = kind === 'chat' ? 'chat' : 'legal';
  if (useMockBackend) {
    // Tao ban ghi THAT trong mockState — khong thi danh sach "phien truoc"
    // cua tab Kiem tra phap ly trong che do gia lap luon trong.
    const stamp = new Date().toLocaleString('vi-VN', {
      day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
    });
    const conv = {
      id: ++mockState.nextConversationId,
      title: `${safeKind === 'legal' ? 'Kiểm tra pháp lý' : 'Cuộc trò chuyện'} ${stamp}`,
      kind: safeKind,
      updated_at: new Date().toISOString().replace('T', ' ').slice(0, 16),
      messages: [],
    };
    mockState.conversations.unshift(conv);
    return { conversation_id: conv.id, kind: safeKind };
  }
  return request(`/conversations?kind=${safeKind}`, { method: 'POST' });
}

// GET /upload/formats — đuôi file máy chủ đọc được. Lấy từ máy chủ thay vì
// chép tay vào giao diện: chép tay là có ngày hộp thoại chặn đúng cái file mà
// máy chủ đọc được (hoặc ngược lại) mà không ai biết vì sao.
export async function getUploadFormats() {
  if (useMockBackend) {
    return {
      extensions: ['.pdf', '.docx', '.doc', '.txt', '.md', '.csv', '.xlsx', '.jpg',
                   '.png', '.eml', '.pptx', '.rtf'],
      max_mb: 50,
    };
  }
  return request('/upload/formats', { method: 'GET' });
}

// POST /upload/extract — file 'dùng xong bỏ' mọi định dạng (.pdf/.docx/ảnh…),
// máy chủ tự trích văn bản + OCR. Không vào kho, tự xoá sau 6 giờ.
export async function uploadExtract({ conversation_id, file }) {
  if (useMockBackend) {
    await new Promise((r) => setTimeout(r, 300));
    return { ok: true, mode: 'temp', filename: file.name, chunks: 3,
             temp_file_id: Date.now(), warnings: [], status: 'ok', text_chars: 1234,
             note: 'File dùng xong bỏ — tự xóa sau 6 giờ, không vào kho.' };
  }
  const form = new FormData();
  form.append('conversation_id', String(toIntOrNull(conversation_id)));
  form.append('file', file);
  // KHÔNG tự đặt Content-Type — trình duyệt thêm boundary cho multipart.
  const res = await fetch(`${apiBaseUrl}/upload/extract`, {
    method: 'POST',
    headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
    body: form,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(parseErrorBody(text, res.status));
  }
  return res.json();
}

// GET /templates/files — danh sách file trong kệ mẫu cho menu "Tạo file mẫu".
export async function listTemplateFiles() {
  if (useMockBackend) {
    return { items: [
      { id: 901, title: 'Hợp đồng lao động mẫu 2026', doc_type: 'mau_hd',
        folder: '3.3 Lao động', fillable: true },
      { id: 902, title: 'Hợp đồng dịch vụ pháp lý mẫu', doc_type: 'mau_hd',
        folder: '3.2 Thương mại', fillable: true },
      { id: 903, title: 'Thư tư vấn mẫu', doc_type: 'thu_mau',
        folder: '5.1 Thư tư vấn mẫu', fillable: false },
    ] };
  }
  return request('/templates/files');
}

// GET /files/{id}/preview — XEM TRƯỚC bản gốc trong tab mới của trình duyệt.
// Phải fetch bằng token rồi mở blob URL (thẻ <a> trần không mang được token).
// Tab được MỞ NGAY trong cú bấm (trước fetch): lần đầu xem file Word máy chủ
// còn phải chạy LibreOffice chuyển PDF, chờ xong mới window.open thì đã ra
// ngoài "user activation" và trình popup-blocker chặn mất.
export async function previewDocument(docId) {
  if (useMockBackend) {
    const blob = new Blob(
      [`Bản demo — bản xem trước của tài liệu #${docId} sẽ mở từ máy chủ thật.`],
      { type: 'text/plain' }
    );
    window.open(URL.createObjectURL(blob), '_blank');
    return;
  }
  const win = window.open('', '_blank');
  try {
    const res = await fetch(`${apiBaseUrl}/files/${docId}/preview`, {
      headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
    });
    if (!res.ok) {
      const text = await res.text().catch(() => '');
      throw new Error(parseErrorBody(text, res.status));
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    if (win) {
      win.opener = null;
      win.location = url;
    } else {
      // Popup vẫn bị chặn — mở tại chỗ còn hơn nuốt cú bấm.
      window.location.assign(url);
    }
    // Thu hồi sau khi tab mới kịp nạp — thu ngay là tab trắng.
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
  } catch (err) {
    if (win) win.close(); // đừng bỏ lại tab trắng khi máy chủ báo lỗi
    throw err;
  }
}

// DELETE /temp-files/{id} — gỡ file 'dùng xong bỏ' THẬT trên máy chủ.
// File 'dung xong bo' con han cua mot hoi thoai — de tab Kiem tra phap ly
// mo lai phien cu dung lai dung cac chip dinh kem con dung duoc.
export async function getConversationTempFiles(convId) {
  if (useMockBackend) return { items: [] };
  return request(`/conversations/${convId}/temp-files`, { method: 'GET' });
}

export async function deleteTempFile(tempFileId) {
  if (useMockBackend) return { ok: true };
  return request(`/temp-files/${toIntOrNull(tempFileId)}`, { method: 'DELETE' });
}

// GET /template-fills/{token}/download — tải file mẫu ĐÃ ĐIỀN chủ thể.
export async function downloadTemplateFill(token, filename) {
  if (useMockBackend) {
    const blob = new Blob(['Bản demo — file đã điền sẽ tải về từ máy chủ thật.'],
                          { type: 'text/plain' });
    triggerDownload(blob, filename || 'file-da-dien.txt');
    return;
  }
  const res = await fetch(`${apiBaseUrl}/template-fills/${encodeURIComponent(token)}/download`, {
    headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(parseErrorBody(text, res.status));
  }
  const blob = await res.blob();
  const cd = res.headers.get('Content-Disposition') || '';
  const m = cd.match(/filename\*?=(?:UTF-8'')?"?([^";]+)"?/i);
  triggerDownload(blob, filename || (m ? decodeURIComponent(m[1]) : 'file-da-dien.docx'));
}

// ==================== BỘ MẪU HỒ SƠ (15/09/2026) ====================
// Nhóm .docx mẫu tải lên từ Quản trị; trong chat chọn bộ (hoặc gọi tên bộ
// trong câu) là AI điền dữ liệu khách vào từng file của bộ.

// GET /bo-mau — bộ mẫu người đang đăng nhập dùng được, kèm file từng bộ.
export async function listBoMau() {
  if (useMockBackend) {
    return { items: [...mockState.boMau], max_bo: 100, max_file_moi_bo: 100, co_quyen_sua: true };
  }
  return request('/bo-mau');
}

// POST /bo-mau {ten, mo_ta, department_id}
export async function createBoMau({ ten, mo_ta, department_id }) {
  if (useMockBackend) {
    const id = Date.now() % 100000;
    mockState.boMau.push({ id, ten, mo_ta: mo_ta || '', department_id: department_id ?? null,
                           active: true, created_at: new Date().toISOString(), so_file: 0, files: [] });
    return { ok: true, id };
  }
  return request('/bo-mau', {
    method: 'POST',
    body: JSON.stringify({ ten, mo_ta: mo_ta || undefined, department_id: department_id ?? null }),
  });
}

// PUT /bo-mau/{id}
export async function updateBoMau(boId, data) {
  if (useMockBackend) {
    const bo = mockState.boMau.find((b) => b.id === toIntOrNull(boId));
    if (bo) Object.assign(bo, { ...data, doi_pham_vi: undefined });
    return { ok: true, changed: Boolean(bo) };
  }
  return request(`/bo-mau/${toIntOrNull(boId)}`, { method: 'PUT', body: JSON.stringify(data) });
}

// DELETE /bo-mau/{id}
export async function deleteBoMau(boId) {
  if (useMockBackend) {
    mockState.boMau = mockState.boMau.filter((b) => b.id !== toIntOrNull(boId));
    return { ok: true };
  }
  return request(`/bo-mau/${toIntOrNull(boId)}`, { method: 'DELETE' });
}

// POST /bo-mau/{id}/files — multipart nhiều file .docx, có tiến trình tải lên.
export async function uploadBoMauFiles({ boId, files, onProgress }) {
  if (useMockBackend) {
    await new Promise((r) => setTimeout(r, 300));
    if (onProgress) onProgress(100);
    const bo = mockState.boMau.find((b) => b.id === toIntOrNull(boId));
    const base = bo ? bo.files.length : 0;
    const ket_qua = Array.from(files).map((f, i) => {
      const item = { id: Date.now() + i, ten_file: f.name, thu_tu: base + i + 1,
                     placeholders: ['{{ten_ben_a}}'], so_placeholder: 1, so_ky_tu: 1200 };
      if (bo) { bo.files.push(item); bo.so_file = bo.files.length; }
      return { ok: true, ...item };
    });
    return { ok: true, ket_qua };
  }
  const form = new FormData();
  Array.from(files).forEach((f) => form.append('files', f));
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${apiBaseUrl}/bo-mau/${toIntOrNull(boId)}/files`);
    if (accessToken) xhr.setRequestHeader('Authorization', `Bearer ${accessToken}`);
    xhr.upload.onprogress = (e) => {
      if (onProgress && e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
    };
    xhr.onload = () => {
      let data = {};
      try { data = JSON.parse(xhr.responseText); } catch { /* rơi xuống nhánh lỗi */ }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data);
      else reject(new Error(parseErrorBody(xhr.responseText, xhr.status)));
    };
    xhr.onerror = () => reject(new Error('Không kết nối được máy chủ khi tải tệp lên.'));
    xhr.send(form);
  });
}

// DELETE /bo-mau/{id}/files/{fid}
export async function deleteBoMauFile(boId, fileId) {
  if (useMockBackend) {
    const bo = mockState.boMau.find((b) => b.id === toIntOrNull(boId));
    if (bo) { bo.files = bo.files.filter((f) => f.id !== toIntOrNull(fileId)); bo.so_file = bo.files.length; }
    return { ok: true };
  }
  return request(`/bo-mau/${toIntOrNull(boId)}/files/${toIntOrNull(fileId)}`, { method: 'DELETE' });
}

// GET /bo-mau/{id}/files/{fid}/download — tải bản gốc một file mẫu trong bộ.
export async function downloadBoMauFile(boId, fileId, filename) {
  if (useMockBackend) {
    triggerDownload(new Blob(['Bản demo'], { type: 'text/plain' }), filename || 'mau.txt');
    return;
  }
  const res = await fetch(
    `${apiBaseUrl}/bo-mau/${toIntOrNull(boId)}/files/${toIntOrNull(fileId)}/download`,
    { headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {} }
  );
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(parseErrorBody(text, res.status));
  }
  const blob = await res.blob();
  const cd = res.headers.get('Content-Disposition') || '';
  const m = cd.match(/filename\*?=(?:UTF-8'')?"?([^";]+)"?/i);
  triggerDownload(blob, filename || (m ? decodeURIComponent(m[1]) : 'mau.docx'));
}

// ==================== ĐIỀN CẢ BỘ TỪ TỜ KHAI (18/09/2026) ====================
// Nhân viên tải TỜ KHAI về, điền, tải lên → máy điền vào từng file của bộ rồi
// trả bản xem nhanh ngay trên giao diện.

// GET /bo-mau/{id}/cho-trong — mọi ô {{…}} của bộ (gộp trùng theo khoá).
export async function getBoMauChoTrong(boId) {
  if (useMockBackend) {
    const bo = mockState.boMau.find((b) => b.id === toIntOrNull(boId));
    return {
      bo: { id: toIntOrNull(boId), ten: bo ? bo.ten : 'Bộ mẫu' },
      items: [
        { khoa: 'ten_ben_a', literal: '{{ten_ben_a}}', goi_y: 'Bên A',
          files: ['01 Hop dong.docx'], so_lan: 2 },
      ],
      loi_mau: [],
      so_file: bo ? bo.so_file : 0,
    };
  }
  return request(`/bo-mau/${toIntOrNull(boId)}/cho-trong`);
}

// GET /bo-mau/{id}/to-khai — tải file TỜ KHAI THÔNG TIN (.docx) của bộ.
export async function downloadBoMauToKhai(boId, filename) {
  if (useMockBackend) {
    triggerDownload(new Blob(['Bản demo — tờ khai sẽ tải về từ máy chủ thật.'],
                             { type: 'text/plain' }), filename || 'to-khai.txt');
    return;
  }
  const res = await fetch(`${apiBaseUrl}/bo-mau/${toIntOrNull(boId)}/to-khai`, {
    headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(parseErrorBody(text, res.status));
  }
  const blob = await res.blob();
  const cd = res.headers.get('Content-Disposition') || '';
  const m = cd.match(/filename\*?=(?:UTF-8'')?"?([^";]+)"?/i);
  triggerDownload(blob, filename || (m ? decodeURIComponent(m[1]) : 'to-khai.docx'));
}

// POST /bo-mau/{id}/dien — multipart: tờ khai đã điền / hồ sơ rời + ô gõ tay.
export async function dienBoMau({ boId, files = [], fileIds = [], giaTri = {},
                                  dungAi = true, onProgress } = {}) {
  if (useMockBackend) {
    await new Promise((r) => setTimeout(r, 400));
    if (onProgress) onProgress(100);
    const bo = mockState.boMau.find((b) => b.id === toIntOrNull(boId));
    const dsFile = (bo ? bo.files : []).map((f, i) => ({
      file_id: f.id, ten_file: f.ten_file, ten_ket_qua: f.ten_file,
      token: `mock${i}`, so_thay: 3, loi: null,
      da_dien: [{ literal: '{{ten_ben_a}}', gia_tri: 'Công ty TNHH ABC', so_cho: 1,
                  nguon: 'tờ khai «to-khai.docx»' }],
      con_trong: [],
    }));
    return {
      bo: { id: toIntOrNull(boId), ten: bo ? bo.ten : 'Bộ mẫu' },
      files: dsFile, zip_token: dsFile.length > 1 ? 'mockzip' : null,
      so_o: 1,
      da_dien: [{ khoa: 'ten_ben_a', literal: '{{ten_ben_a}}',
                  gia_tri: 'Công ty TNHH ABC', nguon: 'tờ khai «to-khai.docx»' }],
      con_thieu: [], doc_file: [], loi_mau: [], loi_tai_len: [],
      gia_tri_thua: 0, ghi_chu_ai: '',
    };
  }
  const form = new FormData();
  Array.from(files || []).forEach((f) => form.append('files', f));
  form.append('file_ids', JSON.stringify((fileIds || []).map((x) => Number(x))));
  form.append('gia_tri', JSON.stringify(giaTri || {}));
  form.append('dung_ai', dungAi ? 'true' : 'false');
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${apiBaseUrl}/bo-mau/${toIntOrNull(boId)}/dien`);
    if (accessToken) xhr.setRequestHeader('Authorization', `Bearer ${accessToken}`);
    xhr.upload.onprogress = (e) => {
      if (onProgress && e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
    };
    xhr.onload = () => {
      let data = {};
      try { data = JSON.parse(xhr.responseText); } catch { /* rơi xuống nhánh lỗi */ }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data);
      else reject(new Error(parseErrorBody(xhr.responseText, xhr.status)));
    };
    xhr.onerror = () => reject(new Error('Không kết nối được máy chủ khi tải tệp lên.'));
    xhr.send(form);
  });
}

// POST /ho-so/theo-ban-cu — dựng bộ hồ sơ khách MỚI theo bộ hồ sơ khách CŨ
// (không cần mã chỗ trống; AI đọc hiểu rồi thay thông tin chủ thể).
export async function dienTheoBanCu({ cu = [], moi = [], ghiChu = '', onProgress } = {}) {
  if (useMockBackend) {
    await new Promise((r) => setTimeout(r, 500));
    if (onProgress) onProgress(100);
    return {
      files: Array.from(cu).map((f, i) => ({
        ten_file: f.name, ten_ket_qua: `${f.name} - khach moi.docx`, token: `mockcu${i}`,
        so_thay: 6, loi: null, ghi_chu: '',
        da_thay: [
          { cu: 'CÔNG TY TNHH ABC', moi: 'CÔNG TY CỔ PHẦN XYZ', so_cho: 3 },
          { cu: '0101234567', moi: '0209988776', so_cho: 1 },
        ],
        khong_thay: [{ cu: 'Ông Trần Văn A', ly_do: 'không tìm thấy nguyên văn trong file' }],
      })),
      zip_token: cu.length > 1 ? 'mockcuzip' : null,
      so_file_cu: cu.length,
      truong_doc_duoc: [{ khoa: 'ho_ten', nhan: 'Họ tên', gia_tri: 'Lê Thị B' }],
      chua_thay_duoc: [],
      loi_tai_len: [],
      canh_bao: ['Bộ này được dựng bằng cách thay thông tin khách cũ — hãy đọc TOÀN VĂN từng file.'],
    };
  }
  const form = new FormData();
  Array.from(cu).forEach((f) => form.append('cu', f));
  Array.from(moi).forEach((f) => form.append('moi', f));
  form.append('ghi_chu', ghiChu || '');
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${apiBaseUrl}/ho-so/theo-ban-cu`);
    if (accessToken) xhr.setRequestHeader('Authorization', `Bearer ${accessToken}`);
    xhr.upload.onprogress = (e) => {
      if (onProgress && e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
    };
    xhr.onload = () => {
      let data = {};
      try { data = JSON.parse(xhr.responseText); } catch { /* rơi xuống nhánh lỗi */ }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data);
      else reject(new Error(parseErrorBody(xhr.responseText, xhr.status)));
    };
    xhr.onerror = () => reject(new Error('Không kết nối được máy chủ khi tải tệp lên.'));
    xhr.send(form);
  });
}

// GET /template-fills/{token}/xem — XEM NHANH nội dung file đã điền (không tải về).
export async function xemTemplateFill(token) {
  if (useMockBackend) {
    return { ten_file: 'ban-demo.docx', cat_bot: false,
             doan: ['CỘNG HOÀ XÃ HỘI CHỦ NGHĨA VIỆT NAM',
                    'Bên A: Công ty TNHH ABC'] };
  }
  return request(`/template-fills/${encodeURIComponent(token)}/xem`);
}

// GET /template-fills/{token}/preview — bản PDF giữ nguyên định dạng Word.
// Mở tab NGAY trong cú bấm (giống previewDocument) để popup-blocker không chặn.
export async function previewTemplateFill(token) {
  if (useMockBackend) {
    const blob = new Blob(['Bản demo — bản xem trước sẽ mở từ máy chủ thật.'],
                          { type: 'text/plain' });
    window.open(URL.createObjectURL(blob), '_blank');
    return;
  }
  const win = window.open('', '_blank');
  try {
    const res = await fetch(
      `${apiBaseUrl}/template-fills/${encodeURIComponent(token)}/preview`,
      { headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {} }
    );
    if (!res.ok) {
      const text = await res.text().catch(() => '');
      throw new Error(parseErrorBody(text, res.status));
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    if (win) {
      win.opener = null;
      win.location = url;
    } else {
      window.location.assign(url);
    }
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
  } catch (err) {
    if (win) win.close();
    throw err;
  }
}

// ---- BỘ HỒ SƠ ĐÃ ĐIỀN: LƯU LẠI ĐỂ MỞ TRONG 7 NGÀY (18/09/2026) ----
// Chỉ lưu con trỏ tới file đã điền (token), không tải file lên lần nữa.

// POST /ho-so-da-luu
export async function luuHoSoDaDien(body = {}) {
  if (useMockBackend) {
    const files = (body.files || []).map((f) => ({ ...f, con: true }));
    const ghi = {
      ma: `${Date.now().toString(16)}${'0'.repeat(32)}`.slice(0, 32),
      ten: body.ten || 'Bộ hồ sơ đã điền',
      kieu: body.kieu || 'bo_mau',
      bo_id: body.bo_id ?? null,
      bo_ten: body.bo_ten || '',
      luc: Date.now() / 1000,
      so_o: body.so_o || 0,
      so_da_dien: (body.da_dien || []).length,
      so_thieu: (body.con_thieu || []).length,
      so_file: files.length,
      so_file_con: files.length,
      con_lai_ngay: 7,
      zip_token: body.zip_token || null,
      zip_con: Boolean(body.zip_token),
      files,
      da_dien: body.da_dien || [],
      con_thieu: body.con_thieu || [],
    };
    mockState.hoSoDaLuu = [ghi, ...(mockState.hoSoDaLuu || [])];
    return ghi;
  }
  return request('/ho-so-da-luu', { method: 'POST', body: JSON.stringify(body) });
}

// GET /ho-so-da-luu
export async function listHoSoDaLuu() {
  if (useMockBackend) {
    return { items: mockState.hoSoDaLuu || [], giu_ngay: 7, toi_da: 50 };
  }
  return request('/ho-so-da-luu');
}

// GET /ho-so-da-luu/{ma}
export async function getHoSoDaLuu(ma) {
  if (useMockBackend) {
    const ghi = (mockState.hoSoDaLuu || []).find((x) => x.ma === ma);
    if (!ghi) throw new Error('Hồ sơ đã lưu không còn.');
    return ghi;
  }
  return request(`/ho-so-da-luu/${encodeURIComponent(ma)}`);
}

// PUT /ho-so-da-luu/{ma}
export async function renameHoSoDaLuu(ma, ten) {
  if (useMockBackend) {
    const ghi = (mockState.hoSoDaLuu || []).find((x) => x.ma === ma);
    if (ghi) ghi.ten = ten;
    return ghi || {};
  }
  return request(`/ho-so-da-luu/${encodeURIComponent(ma)}`, {
    method: 'PUT', body: JSON.stringify({ ten }),
  });
}

// DELETE /ho-so-da-luu/{ma}
export async function deleteHoSoDaLuu(ma) {
  if (useMockBackend) {
    mockState.hoSoDaLuu = (mockState.hoSoDaLuu || []).filter((x) => x.ma !== ma);
    return { ok: true };
  }
  return request(`/ho-so-da-luu/${encodeURIComponent(ma)}`, { method: 'DELETE' });
}

// ==================== CHẾ ĐỘ GIẢ LẬP (MOCK) ====================
// Dữ liệu mẫu bám sát seed thật của backend:
//   - 4 bộ phận trong app/seed_departments.py
//   - tài khoản trong app/seed_accounts.py
//   - enum doc_type / access_level / matters.status trong sql/schema.sql

let mockState = {
  // Bộ mẫu hồ sơ (chế độ giả lập bắt đầu trống — tạo qua tab Quản trị).
  boMau: [],
  // Bộ hồ sơ đã điền mà người dùng bấm Lưu (18/09/2026).
  hoSoDaLuu: [],
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
    { id: 1, name: 'Tập đoàn SunGroup', code: '1729', department: 'Doanh nghiệp - Đầu tư' },
    { id: 2, name: 'Công ty CP Vinapharma', code: '9', department: 'Tranh tụng' },
    { id: 3, name: 'Công ty TechLogistics', code: '712', department: 'Sở hữu trí tuệ' },
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
      // Nạp từ hội thoại → không có tệp gốc: nút Xem / Tải về phải tắt sẵn.
      { id: 15, title: 'Ghi chú trao đổi về điều khoản bảo đảm (nạp từ hội thoại)', doc_type: 'advisory', summary: 'Tóm tắt trao đổi, không có tệp đính kèm gốc.', created_at: '2026-08-11', has_file: false },
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
  // Chế độ giả lập cũng phải tôn trọng nút "Dừng" — không thì demo và bản
  // thật cư xử khác nhau ở đúng chỗ người ta cần tin tưởng nhất.
  const { signal } = payload;
  const kiemTraDung = () => {
    if (signal?.aborted) {
      throw Object.assign(new Error('Đã dừng theo yêu cầu.'), {
        code: DUNG_BOI_NGUOI_DUNG,
      });
    }
  };
  const wait = (ms) =>
    new Promise((res, rej) => {
      const t = setTimeout(res, ms);
      signal?.addEventListener(
        'abort',
        () => {
          clearTimeout(t);
          rej(
            Object.assign(new Error('Đã dừng theo yêu cầu.'), {
              code: DUNG_BOI_NGUOI_DUNG,
            })
          );
        },
        { once: true }
      );
    });
  kiemTraDung();
  // Không có conversation_id → "cuộc trò chuyện mới": tạo hội thoại mới, đặt
  // tiêu đề từ câu hỏi, đúng như backend thật.
  let convObj = mockState.conversations.find(
    (c) => c.id === toIntOrNull(payload.conversation_id)
  );
  if (!convObj) {
    convObj = {
      id: ++mockState.nextConversationId,
      title: (payload.question || 'Cuộc trò chuyện mới').slice(0, 60),
      kind: 'chat',
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
    // Đúng hình dạng máy chủ thật: nguồn kho có số hiệu/điểm khớp, file đính
    // kèm có nhiều đoạn cùng tên (panel phải gom thành một thẻ), một đoạn bot
    // đọc mà không dẫn (phải thu gọn dưới "Xem thêm").
    sources: [
      { n: 1, kind: 'document', title: 'Luật Doanh nghiệp số 59/2020/QH14', so_hieu: '59/2020/QH14', loai_van_ban: 'Luật', trich_yeu: 'Doanh nghiệp', section_title: 'Điều 12', score: 0.94, document_id: 1, drive_file_id: '1AbCdEfGhIjKmock', quote: 'Doanh nghiệp phải thông báo với Cơ quan đăng ký kinh doanh khi thay đổi một trong các nội dung sau: ngành, nghề kinh doanh; cổ đông sáng lập và cổ đông là nhà đầu tư nước ngoài…' },
      { n: 2, kind: 'document', title: 'Nghị định 01/2021/NĐ-CP về Đăng ký Doanh nghiệp', so_hieu: '01/2021/NĐ-CP', loai_van_ban: 'Nghị định', section_title: 'Điều 15', score: 0.89, document_id: 9, quote: 'Trường hợp thay đổi nội dung đăng ký doanh nghiệp, doanh nghiệp nộp hồ sơ tới Phòng Đăng ký kinh doanh nơi doanh nghiệp đặt trụ sở chính…' },
      { n: 3, kind: 'attachment', attachment_name: 'HĐ mua bán căn hộ 005_2024.pdf', title: '[File: HĐ mua bán căn hộ 005_2024.pdf]', page_number: '1–2', score: 1, quote: 'Điều 3. Thời hạn bàn giao: Bên bán bàn giao căn hộ cho Bên mua trong vòng 30 ngày kể từ ngày Bên mua thanh toán đủ đợt 3…' },
      { n: 4, kind: 'attachment', attachment_name: 'HĐ mua bán căn hộ 005_2024.pdf', title: '[File: HĐ mua bán căn hộ 005_2024.pdf]', page_number: 3, score: 1, quote: 'Điều 7. Phạt vi phạm: Bên nào vi phạm nghĩa vụ thanh toán hoặc bàn giao phải chịu phạt 0,05%/ngày trên số tiền chậm…' },
      { n: 5, kind: 'attachment', attachment_name: 'HĐ mua bán căn hộ 005_2024.pdf', title: '[File: HĐ mua bán căn hộ 005_2024.pdf]', page_number: 5, score: 1, quote: 'Điều 12. Giải quyết tranh chấp: hai bên thương lượng, không được thì đưa ra Toà án có thẩm quyền…' },
    ],
    used_method: null,
  });

  await wait(900); // mô phỏng giai đoạn đọc tài liệu — hiện chỉ báo "đang đọc…"

  const text =
    `Với câu hỏi "${payload.question}": doanh nghiệp **phải thông báo thay đổi** ` +
    'tới Cơ quan Đăng ký Kinh doanh trong thời hạn luật định [Nguồn 1].\n\n' +
    '**Căn cứ pháp lý:**\n' +
    '- khoản 1 Điều 12 Luật Doanh nghiệp số 59/2020/QH14 [Nguồn 1]\n' +
    '- Điều 15 Nghị định 01/2021/NĐ-CP về Đăng ký Doanh nghiệp [Nguồn 2]\n' +
    '- Điều 3 hợp đồng anh/chị đính kèm quy định thời hạn bàn giao 30 ngày [Nguồn 3]\n\n' +
    '| Tiêu chí | Theo luật | Theo hợp đồng đính kèm |\n' +
    '|---|---|---|\n' +
    '| Thời hạn | 10 ngày làm việc [Nguồn 1] | 30 ngày [Nguồn 3] |\n' +
    '| Cơ quan nhận | Phòng Đăng ký kinh doanh [Nguồn 2] | Không quy định |\n' +
    '| Chế tài | Phạt hành chính | Phạt 0,05%/ngày [Nguồn 4] |\n\n' +
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
    (endpoint.startsWith('/documents') &&
      !endpoint.startsWith('/documents/browse') &&
      // Chi tiết tài liệu mở cho mọi nhân viên nội bộ (backend: INTERNAL_ROLES)
      !/^\/documents\/\d+\/detail$/.test(endpoint));
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
      const params = new URLSearchParams(endpoint.split('?')[1] || '');
      const kind = params.get('kind') || 'chat';
      return mockState.conversations
        .filter((c) => kind === 'all' || (c.kind || 'chat') === kind)
        .map((c) => ({
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

  // Chi tiết tài liệu + quan hệ văn bản — demo trả bộ khung tối thiểu.
  const detailMatch = endpoint.match(/^\/documents\/(\d+)\/detail$/);
  if (detailMatch) {
    const doc = mockState.documents.find((d) => d.id === Number(detailMatch[1]));
    if (!doc) throw new Error('Không thấy tài liệu (404)');
    return {
      ...doc,
      ten_day_du: doc.title,
      so_hieu: doc.so_hieu || null,
      trang_thai_hieu_luc: doc.trang_thai_hieu_luc || 'chua_ro',
      so_doan: 3,
      can_open: true,
      quan_he_xuoi: [],
      quan_he_nguoc: [],
    };
  }
  if (/^\/documents\/\d+\/relations/.test(endpoint) || /^\/documents\/\d+\/van-ban$/.test(endpoint)) {
    return { ok: true, id: 1 };
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
      // Backend thật trả kèm has_file/can_open (cửa can_open_doc) — giả lập
      // theo để nút Xem / Tải về hiện đúng trạng thái khi xem thử giao diện.
      documents: (mockState.clientDocuments[client.id] || []).map((d) => ({
        has_file: true,
        can_open: true,
        ...d,
      })),
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

  // ---------- Soạn tài liệu: chỉ đủ để thử danh sách / mở / xoá bản nháp ----------
  if (endpoint.startsWith('/drafts')) {
    if (!mockState.drafts) {
      mockState.drafts = [
        { id: 501, title: 'Đơn khởi kiện tranh chấp hợp đồng thuê đất', document_type: 'petition', status: 'draft', current_version: 1, created_by: 4, creator_name: 'Chuyên viên Tranh tụng', updated_at: '2026-09-14 16:20', client_id: 1 },
        { id: 502, title: 'Thư tư vấn phát hành trái phiếu', document_type: 'advisory', status: 'approved', current_version: 2, created_by: 4, creator_name: 'Chuyên viên Tranh tụng', updated_at: '2026-09-10 10:05', approved_at: '2026-09-11 08:00', client_id: 1 },
        { id: 503, title: 'Hợp đồng dịch vụ pháp lý Vinapharma', document_type: 'contract', status: 'generated', current_version: 1, created_by: 1, creator_name: 'Quản trị hệ thống', updated_at: '2026-09-12 14:40', client_id: 2 },
      ];
    }
    if (endpoint === '/drafts' && method === 'GET') return { items: [...mockState.drafts] };
    const dm = endpoint.match(/^\/drafts\/(\d+)$/);
    if (dm) {
      const idx = mockState.drafts.findIndex((d) => String(d.id) === dm[1]);
      if (idx < 0) throw new Error('Không thấy bản nháp (404)');
      const d = mockState.drafts[idx];
      if (method === 'GET') {
        return {
          ...d,
          input_data: {},
          source_documents: [],
          versions: [],
          latest_version: d.current_version
            ? { version_no: d.current_version, content_markdown: `# ${d.title}\n\n(nội dung giả lập)`, evidence: [] }
            : null,
        };
      }
      if (method === 'DELETE') {
        // Cùng luật với DELETE /drafts thật: người tạo xoá bản chưa duyệt; Ban QT xoá mọi bản.
        const me = mockState.users.find((u) => String(u.id) === String(uid)) || mockState.users[0];
        const banQt = me.role === 'admin' || me.role === 'ban_qt';
        if (!banQt && d.created_by !== me.id) throw new Error('Chỉ người tạo hoặc Ban quản trị được sửa bản nháp (403)');
        if (!banQt && d.status === 'approved') throw new Error('Bản đã duyệt chỉ Ban quản trị mới xoá được (409)');
        mockState.drafts.splice(idx, 1);
        return { ok: true, id: d.id };
      }
    }
  }

  // ---------- Hoàn thiện giai đoạn 1 (15/09/2026): mock đủ để xem thử giao diện ----------
  const cmpMatch = endpoint.match(/^\/drafts\/(\d+)\/compare(?:\?.*)?$/);
  if (cmpMatch) {
    return {
      draft_id: Number(cmpMatch[1]), tu: 1, den: 2,
      doan: [
        { op: 'equal', cu: '# Hợp đồng dịch vụ pháp lý', moi: '# Hợp đồng dịch vụ pháp lý', phan: [{ op: 'equal', text: '# Hợp đồng dịch vụ pháp lý' }] },
        { op: 'replace', cu: 'Thời hạn hợp đồng là 12 tháng kể từ ngày ký.', moi: 'Thời hạn hợp đồng là 24 tháng kể từ ngày ký.',
          phan: [{ op: 'equal', text: 'Thời hạn hợp đồng là ' }, { op: 'delete', text: '12' }, { op: 'insert', text: '24' }, { op: 'equal', text: ' tháng kể từ ngày ký.' }] },
        { op: 'delete', cu: 'Phí dịch vụ thanh toán một lần.', moi: null, phan: [{ op: 'delete', text: 'Phí dịch vụ thanh toán một lần.' }] },
        { op: 'insert', cu: null, moi: 'Phí dịch vụ thanh toán theo 2 đợt: 50% khi ký, 50% khi nghiệm thu.', phan: [{ op: 'insert', text: 'Phí dịch vụ thanh toán theo 2 đợt: 50% khi ký, 50% khi nghiệm thu.' }] },
      ],
      thong_ke: { them: 14, xoa: 7, doan_them: 1, doan_xoa: 1, doan_sua: 1, giong_nhau: 0.62 },
      tom_tat: 'Thêm 14 từ, xoá 7 từ; 1 đoạn sửa, 1 đoạn thêm, 1 đoạn xoá; giống nhau 62%',
    };
  }
  const chkMatch = endpoint.match(/^\/drafts\/(\d+)\/checks(?:\?.*)?$/);
  if (chkMatch) {
    mockState.draftChecks = mockState.draftChecks || {};
    const id = chkMatch[1];
    if (method === 'POST') {
      mockState.draftChecks[id] = [{
        version_no: 2, status: 'done', ket_luan: 'canh_bao', so_canh_bao: 1, so_muc: 3, phuong_phap: 'quy_tac+ai',
        items: [
          { loai: 'lai_suat', trich: 'lãi suất chậm thanh toán 3%/tháng', vi_tri: 'Điều 5', ket_luan: 'canh_bao', ly_do: 'Quy ra 36%/năm, vượt trần 20%/năm', can_cu: 'Điều 468 Bộ luật Dân sự 2015' },
          { loai: 'phat_vi_pham', trich: 'phạt vi phạm 8% giá trị phần nghĩa vụ bị vi phạm', vi_tri: 'Điều 7', ket_luan: 'hop_le', ly_do: 'Đúng mức tối đa', can_cu: 'Điều 301 Luật Thương mại 2005' },
          { loai: 'thoi_han', trich: 'trong vòng 15 ngày làm việc', vi_tri: 'Điều 4', ket_luan: 'khong_ro', ly_do: 'Thoả thuận, không có ngưỡng luật' },
        ],
        started_at: new Date().toISOString(), finished_at: new Date().toISOString(),
      }];
    }
    return { ok: true, items: mockState.draftChecks[id] || [] };
  }
  if (endpoint.startsWith('/leads')) {
    mockState.leads = mockState.leads || [
      { id: 1, name: 'Nguyễn Văn An', phone: '0912345678', email: null, need: 'Tranh chấp hợp đồng thuê mặt bằng, muốn được tư vấn khởi kiện.', status: 'moi', created_at: '2026-09-15 09:12', source: 'website' },
      { id: 2, name: 'Trần Thị Bích', phone: null, email: 'bich.tran@example.com', need: 'Đăng ký nhãn hiệu cho quán cà phê.', status: 'da_lien_he', note: 'Đã gọi, hẹn gặp thứ 5', created_at: '2026-09-14 15:40', handled_at: '2026-09-14 16:00', handled_by_name: 'Giám đốc (Ban QT)', source: 'website' },
    ];
    const lm = endpoint.match(/^\/leads\/(\d+)$/);
    if (lm && method === 'PATCH') {
      const body = JSON.parse(options.body || '{}');
      const l = mockState.leads.find((x) => String(x.id) === lm[1]);
      if (l) { if (body.status) l.status = body.status; if (body.note != null) l.note = body.note; l.handled_at = new Date().toISOString(); l.handled_by_name = me.full_name; }
      return { ok: true };
    }
    const counts = { moi: 0, da_lien_he: 0, bo_qua: 0 };
    mockState.leads.forEach((l) => { counts[l.status] = (counts[l.status] || 0) + 1; });
    return { items: [...mockState.leads], counts, statuses: { moi: 'Mới', da_lien_he: 'Đã liên hệ', bo_qua: 'Bỏ qua' } };
  }
  if (endpoint === '/audit/actions') {
    return { items: [{ action: 'chat_query', count: 368, label: 'Hỏi AI' }, { action: 'approve_label', count: 99, label: 'Duyệt nhãn tài liệu' }, { action: 'auto_learn', count: 40043, label: 'Bộ quét học tài liệu' }] };
  }
  if (endpoint.startsWith('/audit')) {
    const rows = [
      { id: 40714, user_id: 1, user_name: 'Quản trị hệ thống', action: 'chat_query', entity: 'conversations', entity_id: 43, detail: { question: 'Thời hiệu khởi kiện tranh chấp hợp đồng?' }, created_at: '2026-09-15 11:20', tom_tat: 'Hỏi AI · conversations#43 · question=Thời hiệu khởi kiện tranh chấp hợp đồng?' },
      { id: 40713, user_id: 2, user_name: 'Giám đốc (Ban QT)', action: 'approve_label', entity: 'documents', entity_id: 40291, detail: { doc_type: 'ho_so_kh' }, created_at: '2026-09-15 10:02', tom_tat: 'Duyệt nhãn tài liệu · documents#40291' },
      { id: 40712, user_id: null, user_name: 'Hệ thống', action: 'auto_learn', entity: 'documents', entity_id: 40290, detail: { file: 'BCTC.pdf' }, created_at: '2026-09-15 09:58', tom_tat: 'Bộ quét học tài liệu · documents#40290 · file=BCTC.pdf' },
    ];
    return { items: rows, total: 40714, limit: 100, offset: 0 };
  }
  const verCmp = endpoint.match(/^\/documents\/(\d+)\/versions\/compare/);
  if (verCmp) {
    return { document_id: Number(verCmp[1]), tu: 1, den: 2,
      doan: [{ op: 'replace', cu: 'Số: 91/2015/QH13', moi: 'Số: 91/2015/QH13 (đã soát OCR)', phan: [{ op: 'equal', text: 'Số: 91/2015/QH13' }, { op: 'insert', text: ' (đã soát OCR)' }] }],
      thong_ke: { them: 3, xoa: 0, doan_them: 0, doan_xoa: 0, doan_sua: 1, giong_nhau: 0.9 }, tom_tat: 'Thêm 3 từ, xoá 0 từ; 1 đoạn sửa, 0 đoạn thêm, 0 đoạn xoá; giống nhau 90%' };
  }
  const verList = endpoint.match(/^\/documents\/(\d+)\/versions$/);
  if (verList) {
    return { document_id: Number(verList[1]), reasons: { luat_thay_doi: 'Luật thay đổi', rui_ro: 'Rủi ro', yeu_cau_khach: 'Yêu cầu khách hàng', sua_loi_trich_xuat: 'Sửa lỗi trích xuất / OCR', khac: 'Khác' },
      items: [
        { version_no: 2, edit_reason: 'sua_loi_trich_xuat', edit_reason_label: 'Sửa lỗi trích xuất / OCR', edit_note: 'Chữa số hiệu OCR đọc sai', created_at: '2026-09-15 10:30', edited_by_name: 'Giám đốc (Ban QT)', characters: 12040 },
        { version_no: 1, edit_reason: 'ban_goc', edit_reason_label: 'Bản gốc', edit_note: 'Bản trích xuất ban đầu', created_at: '2026-09-15 10:30', edited_by_name: 'Hệ thống', characters: 12010 },
      ] };
  }
  if (endpoint === '/legal/ra-soat/loai') {
    return { items: [
      { ma: 'hop_dong_lao_dong', ten: 'Hợp đồng lao động', so_dieu_khoan: 10, so_nguong: 5 },
      { ma: 'hop_dong_dich_vu', ten: 'Hợp đồng dịch vụ', so_dieu_khoan: 10, so_nguong: 2 },
      { ma: 'hop_dong_thue', ten: 'Hợp đồng thuê', so_dieu_khoan: 8, so_nguong: 1 },
    ] };
  }
  if (endpoint === '/legal/ra-soat' && method === 'POST') {
    return {
      loai: 'hop_dong_dich_vu', ten_loai: 'Hợp đồng dịch vụ', do_tin_cay: 0.8, so_dieu_khoan: 9, tieu_de: 'HĐ dịch vụ (demo)', so_ky_tu: 8210, thoi_gian_ms: 120,
      muc: [
        { ma: 'tranh_chap', ten: 'Giải quyết tranh chấp', trang_thai: 'thieu', giai_thich: 'Không thấy điều khoản chọn toà án / trọng tài.', de_xuat: 'Bổ sung điều khoản giải quyết tranh chấp (toà án có thẩm quyền hoặc trọng tài).', can_cu: 'Điều 513–520 Bộ luật Dân sự 2015', can_cu_kho: [{ document_id: 12, title: 'Bộ luật Dân sự 2015', so_hieu: '91/2015/QH13', trich: 'Điều 513. Hợp đồng dịch vụ…' }] },
        { ma: 'phat_vi_pham', ten: 'Phạt vi phạm', trang_thai: 'canh_bao', dieu_khoan: 'Điều 8. Phạt vi phạm', trich: 'phạt 12% giá trị hợp đồng', giai_thich: 'Mức phạt 12% vượt trần 8% với hợp đồng thương mại.', de_xuat: 'Hạ mức phạt về tối đa 8% giá trị phần nghĩa vụ bị vi phạm.', can_cu: 'Điều 301 Luật Thương mại 2005' },
        { ma: 'gia_thanh_toan', ten: 'Giá và thanh toán', trang_thai: 'dat', dieu_khoan: 'Điều 3. Phí dịch vụ', trich: 'Phí dịch vụ 120.000.000 đồng, thanh toán 2 đợt', giai_thich: 'Có điều khoản.', de_xuat: '', can_cu: 'Điều 519 Bộ luật Dân sự 2015' },
      ],
      tong_ket: { dat: 1, canh_bao: 1, thieu: 1, muc_rui_ro: 'cao' },
    };
  }

  throw new Error(`Đường dẫn chưa được hỗ trợ trong chế độ giả lập: ${endpoint}`);
}
