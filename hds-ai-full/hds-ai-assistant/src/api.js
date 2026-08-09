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
 * Đăng ký hàm được gọi khi module TỰ chuyển sang chế độ giả lập vì backend
 * không kết nối được. Nhờ đó giao diện cập nhật lại huy hiệu trạng thái thay vì
 * tiếp tục báo "Backend FastAPI" trong khi dữ liệu hiển thị là dữ liệu mẫu.
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
    // Backend không chạy / sai URL / CORS chặn → chuyển sang chế độ giả lập
    console.warn(`[HDS AI] Không kết nối được ${url}. Tự chuyển sang Mock Mode.`, err);
    const wasLive = !useMockBackend;
    useMockBackend = true;
    if (wasLive && fallbackListener) fallbackListener(apiBaseUrl);
    return handleMockRequest(endpoint, options, headers);
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
export async function chatInternal({ question, conversation_id, use_temp, use_method }) {
  return request('/chat/internal', {
    method: 'POST',
    body: JSON.stringify({
      question,
      conversation_id: toIntOrNull(conversation_id),
      use_temp: Boolean(use_temp),
      use_method: Boolean(use_method),
    }),
  });
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
  },
  departments: [
    { id: 1, code: 'dn-dt', name: 'Doanh nghiệp - Đầu tư' },
    { id: 2, code: 'htpl-tvtx', name: 'Hỗ trợ pháp lý - Tư vấn thường xuyên' },
    { id: 3, code: 'tranh-tung', name: 'Tranh tụng' },
    { id: 4, code: 'shtt', name: 'Sở hữu trí tuệ' },
  ],
  users: [
    { id: 1, email: 'admin@hdslaw.vn', full_name: 'Quản trị hệ thống', role: 'admin', can_review: true, active: true, department_ids: [], head_of: [], monthly_quota: 0 },
    { id: 2, email: 'giamdoc@hdslaw.vn', full_name: 'Giám đốc (Ban QT)', role: 'ban_qt', can_review: true, active: true, department_ids: [], head_of: [], monthly_quota: 0 },
    { id: 3, email: 'truong.dndt@hdslaw.vn', full_name: 'Trưởng phòng DN-ĐT', role: 'truong_bph', can_review: true, active: true, department_ids: [1], head_of: [1], monthly_quota: 0 },
    { id: 4, email: 'cv.tranhtung@hdslaw.vn', full_name: 'Chuyên viên Tranh tụng', role: 'chuyen_vien', can_review: false, active: true, department_ids: [3], head_of: [], monthly_quota: 0 },
    { id: 5, email: 'troly@hdslaw.vn', full_name: 'Trợ lý', role: 'tro_ly', can_review: false, active: true, department_ids: [2], head_of: [], monthly_quota: 0 },
    { id: 6, email: 'lienhe@sungroup.vn', full_name: 'Đại diện SunGroup', role: 'client_plus', can_review: false, active: true, client_id: 1, department_ids: [], head_of: [], monthly_quota: 50 },
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
    },
    {
      message_id: 502,
      question: 'Thủ tục xin cấp Giấy phép Bưu chính quốc tế cần những văn bản gì?',
      answer:
        'Hồ sơ gồm: đơn đề nghị, bản sao Giấy chứng nhận ĐKKD, phương án kinh doanh bưu chính, mẫu hợp đồng cung ứng dịch vụ và văn bản xác nhận vốn tối thiểu 5 tỷ đồng.',
      created_at: '2026-08-07 10:30',
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
  nextConversationId: 9000,
};

async function handleMockRequest(endpoint, options, headers) {
  await new Promise((res) => setTimeout(res, 200));
  const method = (options.method || 'GET').toUpperCase();
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
      latency_ms: 380,
    };
  }

  if (endpoint === '/chat/portal' && method === 'POST') {
    return {
      answer: `[Cổng thông tin Khách hàng HDS] Cảm ơn quý khách đã đặt câu hỏi "${body.question}". Luật sư phụ trách sẽ phản hồi chi tiết trong thời gian sớm nhất.`,
      sources: [{ title: 'Tài liệu hướng dẫn dịch vụ pháp lý HDS', relevance_score: 0.9 }],
      conversation_id: toIntOrNull(body.conversation_id) ?? ++mockState.nextConversationId,
      latency_ms: 290,
      quota: { used: 1, limit: me.monthly_quota || 50 },
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

  throw new Error(`Đường dẫn chưa được hỗ trợ trong chế độ giả lập: ${endpoint}`);
}
