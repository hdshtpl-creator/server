-- =============================================================
-- SCHEMA CSDL — HỆ THỐNG TRỢ LÝ AI HDS (bản Lớp 1 + Lớp 2)
-- Chạy: bash scripts/10_init_db.sh
--
-- NGUYÊN TẮC: Phân quyền dữ liệu ở TẦNG CSDL (Row-Level Security),
--   KHÔNG ở prompt, KHÔNG ở if trong Python.
--
-- Thêm ở bản này:
--   - departments + user_departments (1 người nhiều phòng)
--   - cấp: admin | ban_qt | truong_bph | chuyen_vien | tro_ly | client_*
--   - access_rules: ma trận quyền loại tài liệu × cấp × phòng
--   - matters (vụ việc) + tài liệu gắn vụ việc
--   - client_profiles: hồ sơ 360° (admin train)
--   - cơ chế "hiện tên che / khóa mở" (Cách B)
-- =============================================================

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS departments (
  id    SERIAL PRIMARY KEY,
  code  TEXT UNIQUE NOT NULL,
  name  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS clients (
  id            SERIAL PRIMARY KEY,
  name          TEXT NOT NULL,
  code          TEXT UNIQUE,
  department_id INT REFERENCES departments(id),
  note          TEXT,
  created_at    TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_clients_name_trgm ON clients USING gin(lower(name) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_clients_code_lower ON clients(lower(code));

CREATE TABLE IF NOT EXISTS users (
  id            SERIAL PRIMARY KEY,
  email         TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  full_name     TEXT,
  role          TEXT NOT NULL CHECK (role IN
                  ('admin','ban_qt','truong_bph','chuyen_vien','tro_ly',
                   'client_free','client_plus','client_pro')),
  can_review    BOOLEAN DEFAULT false,
  -- Quyền xem số liệu tài chính/công nợ của khách. Mặc định KHÔNG ai có,
  -- admin cấp từng người. Chặn thật ở RLS bên dưới (app.can_finance), không
  -- phải chỉ ẩn trên giao diện.
  can_view_finance BOOLEAN DEFAULT false,
  client_id     INT REFERENCES clients(id),
  -- Băm SHA-256 của khoá API, KHÔNG phải khoá thật. Khoá thật chỉ hiện một lần
  -- lúc cấp. Xem app/auth.py: new_api_key().
  api_key_hash  TEXT UNIQUE,
  api_key_at    TIMESTAMPTZ,
  monthly_quota INT DEFAULT 0,
  used_this_month INT DEFAULT 0,
  quota_reset_at  DATE DEFAULT date_trunc('month', now()) + interval '1 month',
  active        BOOLEAN DEFAULT true,
  created_at    TIMESTAMPTZ DEFAULT now(),
  CONSTRAINT client_role_needs_client_id
    CHECK (role NOT IN ('client_free','client_plus','client_pro')
           OR client_id IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_users_active_role ON users(active, role);
-- CSDL tạo từ bản trước có cột 'api_key' (chưa bao giờ được ghi vào, nên đổi
-- tên là an toàn tuyệt đối). Đổi tên thay vì thêm cột mới để không để lại một
-- cột tên 'api_key' mà thực chất chứa bản băm — dễ khiến người sau tưởng là
-- khoá thật rồi đem hiển thị ra ngoài.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns
              WHERE table_name='users' AND column_name='api_key')
     AND NOT EXISTS (SELECT 1 FROM information_schema.columns
              WHERE table_name='users' AND column_name='api_key_hash') THEN
    ALTER TABLE users RENAME COLUMN api_key TO api_key_hash;
  END IF;
END $$;
ALTER TABLE users ADD COLUMN IF NOT EXISTS api_key_hash TEXT UNIQUE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS api_key_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_users_apikey ON users(api_key_hash)
  WHERE api_key_hash IS NOT NULL;

CREATE TABLE IF NOT EXISTS user_departments (
  user_id       INT REFERENCES users(id) ON DELETE CASCADE,
  department_id INT REFERENCES departments(id) ON DELETE CASCADE,
  is_head       BOOLEAN DEFAULT false,
  PRIMARY KEY (user_id, department_id)
);
CREATE INDEX IF NOT EXISTS idx_user_departments_department_user
  ON user_departments(department_id, user_id);

CREATE TABLE IF NOT EXISTS matters (
  id            SERIAL PRIMARY KEY,
  code          TEXT UNIQUE,
  title         TEXT NOT NULL,
  client_id     INT NOT NULL REFERENCES clients(id),
  department_id INT REFERENCES departments(id),
  matter_type   TEXT,
  status        TEXT DEFAULT 'dang_xu_ly'
                CHECK (status IN ('tiep_nhan','dang_xu_ly','tam_dung','hoan_thanh')),
  deadline      DATE,
  opened_at     DATE DEFAULT now(),
  created_at    TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_matter_client ON matters(client_id);

CREATE TABLE IF NOT EXISTS documents (
  id             SERIAL PRIMARY KEY,
  title          TEXT,
  source_path    TEXT,
  source_kind    TEXT DEFAULT 'manual'
                 CHECK (source_kind IN ('drive','manual','chat','web')),
  drive_file_id  TEXT UNIQUE,
  checksum       TEXT,
  doc_type       TEXT CHECK (doc_type IN
                  ('law','ban_an','an_le','mau_hd','nhan_hieu','thu_mau',
                   'quy_trinh','ho_so_ns','ho_so_kh','advisory','filing','contract',
                   'cong_no','other')),
  access_level   TEXT NOT NULL DEFAULT 'internal'
                 CHECK (access_level IN ('public','internal','client')),
  client_id      INT REFERENCES clients(id),
  department_id  INT REFERENCES departments(id),
  matter_id      INT REFERENCES matters(id),
  approved       BOOLEAN DEFAULT false,
  label_verified BOOLEAN DEFAULT false,
  confidence     REAL,
  summary        TEXT,
  uploaded_by    INT REFERENCES users(id),
  created_at     TIMESTAMPTZ DEFAULT now(),
  updated_at     TIMESTAMPTZ DEFAULT now(),
  CONSTRAINT client_doc_must_have_owner
    CHECK (access_level <> 'client' OR client_id IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_doc_access ON documents(access_level, client_id, department_id);
CREATE INDEX IF NOT EXISTS idx_doc_pending ON documents(label_verified) WHERE label_verified = false;

-- Trạng thái trích xuất/version phải nằm ngay trên tài liệu để bộ tra cứu có thể
-- loại file lỗi và không vô tình dùng bản Drive cũ. Các ALTER này giữ schema
-- tương thích với CSDL đã chạy từ những bản trước.
ALTER TABLE documents ADD COLUMN IF NOT EXISTS extraction_status TEXT DEFAULT 'ready';
ALTER TABLE documents ADD COLUMN IF NOT EXISTS extraction_error TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS source_version INT DEFAULT 1;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS active BOOLEAN DEFAULT true;
CREATE INDEX IF NOT EXISTS idx_doc_ready_active
  ON documents(active, extraction_status, approved, label_verified);

-- -------------------------------------------------------------
-- NÂNG CẤP CSDL TẠO TỪ BẢN TRƯỚC
-- CREATE TABLE IF NOT EXISTS ở trên không chạm vào bảng đã tồn tại, nên cột và
-- ràng buộc mới phải thêm bằng ALTER. deploy/update.sh nạp lại đúng file này
-- mỗi lần cập nhật, nên khai ở đây là máy chủ tự lên phiên bản mới.
-- -------------------------------------------------------------
ALTER TABLE users ADD COLUMN IF NOT EXISTS can_view_finance BOOLEAN DEFAULT false;
ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_doc_type_check;
ALTER TABLE documents ADD CONSTRAINT documents_doc_type_check CHECK (doc_type IN
  ('law','ban_an','an_le','mau_hd','nhan_hieu','thu_mau','quy_trinh','ho_so_ns',
   'ho_so_kh','advisory','filing','contract','cong_no','other'));

CREATE TABLE IF NOT EXISTS access_rules (
  role_level      TEXT NOT NULL,
  department_code TEXT DEFAULT '*',
  doc_type        TEXT NOT NULL,
  can_view        BOOLEAN DEFAULT true,
  can_open        BOOLEAN DEFAULT true,
  PRIMARY KEY (role_level, department_code, doc_type)
);

CREATE TABLE IF NOT EXISTS client_profiles (
  client_id    INT PRIMARY KEY REFERENCES clients(id) ON DELETE CASCADE,
  history_note TEXT,
  issues_note  TEXT,
  warnings     TEXT,
  suggestions  TEXT,
  updated_by   INT REFERENCES users(id),
  updated_at   TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS document_versions (
  id           SERIAL PRIMARY KEY,
  document_id  INT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  version_no   INT NOT NULL,
  content      TEXT NOT NULL,
  edited_by    INT REFERENCES users(id),
  edit_note    TEXT,
  created_at   TIMESTAMPTZ DEFAULT now(),
  UNIQUE (document_id, version_no)
);

CREATE TABLE IF NOT EXISTS chunks (
  id            BIGSERIAL PRIMARY KEY,
  document_id   INT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  chunk_index   INT NOT NULL,
  content       TEXT NOT NULL,
  page_number   INT,
  section_title TEXT,
  source_locator TEXT,
  access_level  TEXT NOT NULL,
  client_id     INT,
  department_id INT,
  doc_type      TEXT,
  embedding     vector(1024),
  created_at    TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS page_number INT;
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS section_title TEXT;
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS source_locator TEXT;
-- Chỉ mục từ khóa cho hybrid retrieval. Cấu hình 'simple' không làm mất mã hồ
-- sơ, số điều/khoản và vẫn hoạt động tốt với tiếng Việt không có stemmer riêng.
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS search_vector tsvector
  GENERATED ALWAYS AS (to_tsvector('simple', coalesce(content, ''))) STORED;
CREATE INDEX IF NOT EXISTS idx_chunks_vec ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_chunks_access ON chunks(access_level, client_id, department_id);
CREATE INDEX IF NOT EXISTS idx_chunks_fts ON chunks USING gin(search_vector);
CREATE INDEX IF NOT EXISTS idx_chunks_content_trgm ON chunks USING gin(lower(content) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_documents_title_trgm ON documents USING gin(lower(title) gin_trgm_ops);

CREATE OR REPLACE FUNCTION sync_chunk_labels() RETURNS TRIGGER AS $$
BEGIN
  UPDATE chunks SET access_level=NEW.access_level, client_id=NEW.client_id,
         department_id=NEW.department_id, doc_type=NEW.doc_type
   WHERE document_id=NEW.id;
  RETURN NEW;
END; $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_sync_chunk_labels ON documents;
CREATE TRIGGER trg_sync_chunk_labels
  AFTER UPDATE OF access_level, client_id, department_id, doc_type ON documents
  FOR EACH ROW EXECUTE FUNCTION sync_chunk_labels();

CREATE TABLE IF NOT EXISTS conversations (
  id          SERIAL PRIMARY KEY,
  user_id     INT REFERENCES users(id),
  channel     TEXT NOT NULL CHECK (channel IN ('public','internal','portal')),
  client_id   INT REFERENCES clients(id),
  title       TEXT,
  context_state JSONB DEFAULT '{}'::jsonb,
  started_at  TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS context_state JSONB DEFAULT '{}'::jsonb;

CREATE TABLE IF NOT EXISTS messages (
  id              BIGSERIAL PRIMARY KEY,
  conversation_id INT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  role            TEXT NOT NULL CHECK (role IN ('user','assistant')),
  content         TEXT NOT NULL,
  sources         JSONB,
  answer_mode     TEXT,
  grounding_status TEXT,
  evidence        JSONB,
  model_used      TEXT,
  latency_ms      INT,
  review_status   TEXT DEFAULT 'pending'
                  CHECK (review_status IN ('pending','approved','edited','rejected')),
  reviewed_by     INT REFERENCES users(id),
  reviewed_at     TIMESTAMPTZ,
  edited_content  TEXT,
  edit_reason     TEXT,
  promoted_doc_id INT REFERENCES documents(id),
  created_at      TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE messages ADD COLUMN IF NOT EXISTS answer_mode TEXT;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS grounding_status TEXT;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS evidence JSONB;
CREATE INDEX IF NOT EXISTS idx_msg_review ON messages(review_status) WHERE review_status='pending';
CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_msg_conv_desc ON messages(conversation_id, id DESC);

-- =============================================================
-- DỮ LIỆU NHÂN SỰ CÓ CẤU TRÚC
-- Không dùng users.active làm quân số: users là tài khoản đăng nhập, còn hai
-- bảng này mới là nguồn sự thật cho nhân sự và hợp đồng lao động.
-- =============================================================
CREATE TABLE IF NOT EXISTS employees (
  id                 SERIAL PRIMARY KEY,
  employee_code      TEXT UNIQUE NOT NULL,
  full_name          TEXT NOT NULL,
  title              TEXT,
  department_id      INT REFERENCES departments(id),
  employment_status  TEXT DEFAULT 'active',
  active             BOOLEAN DEFAULT true,
  source_document_id INT REFERENCES documents(id) ON DELETE SET NULL,
  created_at         TIMESTAMPTZ DEFAULT now(),
  updated_at         TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_employees_active ON employees(active, employment_status);
CREATE INDEX IF NOT EXISTS idx_employees_department ON employees(department_id);

CREATE TABLE IF NOT EXISTS employment_contracts (
  id                 SERIAL PRIMARY KEY,
  employee_id        INT NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
  contract_no        TEXT,
  start_date         DATE,
  end_date           DATE,
  status             TEXT DEFAULT 'active',
  source_document_id INT REFERENCES documents(id) ON DELETE SET NULL,
  created_at         TIMESTAMPTZ DEFAULT now(),
  updated_at         TIMESTAMPTZ DEFAULT now(),
  UNIQUE (employee_id, contract_no)
);
CREATE INDEX IF NOT EXISTS idx_contract_employee ON employment_contracts(employee_id);
CREATE INDEX IF NOT EXISTS idx_contract_active_dates
  ON employment_contracts(status, start_date, end_date);

-- =============================================================
-- SOẠN THẢO CÓ NGUỒN, VERSION VÀ DUYỆT
-- Nội dung phiên bản và bằng chứng là snapshot bất biến; sửa bản nháp luôn tạo
-- version mới để có thể kiểm toán chính xác tài liệu đã được duyệt.
-- =============================================================
CREATE TABLE IF NOT EXISTS document_templates (
  id                  SERIAL PRIMARY KEY,
  code                TEXT UNIQUE NOT NULL,
  name                TEXT NOT NULL,
  document_type       TEXT NOT NULL DEFAULT 'other',
  description         TEXT,
  system_instructions TEXT,
  body_template       TEXT NOT NULL,
  required_fields     JSONB DEFAULT '[]'::jsonb,
  active              BOOLEAN DEFAULT true,
  created_by          INT REFERENCES users(id),
  created_at          TIMESTAMPTZ DEFAULT now(),
  updated_at          TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS document_drafts (
  id                SERIAL PRIMARY KEY,
  title             TEXT NOT NULL,
  document_type     TEXT NOT NULL DEFAULT 'other',
  template_id       INT REFERENCES document_templates(id) ON DELETE SET NULL,
  client_id         INT REFERENCES clients(id) ON DELETE SET NULL,
  matter_id         INT REFERENCES matters(id) ON DELETE SET NULL,
  department_id     INT REFERENCES departments(id) ON DELETE SET NULL,
  instructions      TEXT,
  input_data        JSONB DEFAULT '{}'::jsonb,
  status            TEXT NOT NULL DEFAULT 'draft',
  current_version   INT NOT NULL DEFAULT 0,
  created_by        INT NOT NULL REFERENCES users(id),
  approved_by       INT REFERENCES users(id),
  approved_at       TIMESTAMPTZ,
  approval_note     TEXT,
  created_at        TIMESTAMPTZ DEFAULT now(),
  updated_at        TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_drafts_owner_time ON document_drafts(created_by, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_drafts_review ON document_drafts(status, department_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS document_draft_sources (
  draft_id     INT NOT NULL REFERENCES document_drafts(id) ON DELETE CASCADE,
  document_id  INT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  added_by     INT REFERENCES users(id),
  created_at   TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (draft_id, document_id)
);
CREATE INDEX IF NOT EXISTS idx_draft_sources_document ON document_draft_sources(document_id);

CREATE TABLE IF NOT EXISTS document_draft_versions (
  id                 SERIAL PRIMARY KEY,
  draft_id           INT NOT NULL REFERENCES document_drafts(id) ON DELETE CASCADE,
  version_no         INT NOT NULL,
  content_markdown   TEXT NOT NULL,
  change_note        TEXT,
  model_used         TEXT,
  grounding_status   TEXT NOT NULL DEFAULT 'needs_review',
  placeholder_count  INT NOT NULL DEFAULT 0,
  evidence_snapshot  JSONB DEFAULT '[]'::jsonb,
  created_by         INT NOT NULL REFERENCES users(id),
  created_at         TIMESTAMPTZ DEFAULT now(),
  UNIQUE (draft_id, version_no)
);
CREATE INDEX IF NOT EXISTS idx_draft_versions_draft ON document_draft_versions(draft_id, version_no DESC);

CREATE TABLE IF NOT EXISTS document_draft_evidence (
  id                SERIAL PRIMARY KEY,
  draft_version_id  INT NOT NULL REFERENCES document_draft_versions(id) ON DELETE CASCADE,
  document_id       INT REFERENCES documents(id) ON DELETE SET NULL,
  document_title    TEXT NOT NULL DEFAULT '',
  source_version    INT,
  chunk_id          BIGINT REFERENCES chunks(id) ON DELETE SET NULL,
  citation_key      TEXT NOT NULL,
  excerpt           TEXT NOT NULL,
  page_number       INT,
  section_title     TEXT,
  source_locator    TEXT,
  created_at        TIMESTAMPTZ DEFAULT now(),
  UNIQUE (draft_version_id, citation_key)
);
ALTER TABLE document_draft_evidence ADD COLUMN IF NOT EXISTS document_title TEXT NOT NULL DEFAULT '';
ALTER TABLE document_draft_evidence ADD COLUMN IF NOT EXISTS source_version INT;
-- Bản Drive cũ có thể được thay thế. Nguồn đang chọn tự rời bản nháp, còn bằng
-- chứng của version cũ giữ title/excerpt snapshot và chỉ mất liên kết tới row cũ.
ALTER TABLE document_draft_sources
  DROP CONSTRAINT IF EXISTS document_draft_sources_document_id_fkey;
ALTER TABLE document_draft_sources
  ADD CONSTRAINT document_draft_sources_document_id_fkey
  FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE;
ALTER TABLE document_draft_evidence
  DROP CONSTRAINT IF EXISTS document_draft_evidence_document_id_fkey;
ALTER TABLE document_draft_evidence ALTER COLUMN document_id DROP NOT NULL;
ALTER TABLE document_draft_evidence
  ADD CONSTRAINT document_draft_evidence_document_id_fkey
  FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_draft_evidence_version ON document_draft_evidence(draft_version_id);

INSERT INTO document_templates
  (code, name, document_type, description, system_instructions, body_template, required_fields)
VALUES
  ('legal_advice', 'Thư tư vấn pháp lý', 'advisory',
   'Bản tư vấn có vấn đề, căn cứ, phân tích, rủi ro và kiến nghị.',
   'Chỉ kết luận từ dữ liệu đầu vào và bằng chứng được cung cấp. Mọi dữ kiện thiếu phải để placeholder.',
   E'# THƯ TƯ VẤN PHÁP LÝ\n\n## 1. Thông tin và yêu cầu\n[CẦN BỔ SUNG: thông tin khách hàng và yêu cầu tư vấn]\n\n## 2. Căn cứ\n[CẦN BỔ SUNG: căn cứ có nguồn]\n\n## 3. Phân tích\n[CẦN BỔ SUNG: phân tích bám nguồn]\n\n## 4. Rủi ro và kiến nghị\n[CẦN BỔ SUNG: rủi ro và kiến nghị]\n',
   '["client_name", "request"]'::jsonb),
  ('matter_report', 'Báo cáo vụ việc', 'filing',
   'Báo cáo tiến độ, sự kiện, tài liệu và công việc tiếp theo.',
   'Không tự tạo ngày, số hồ sơ, cơ quan, tên người hoặc trạng thái vụ việc.',
   E'# BÁO CÁO VỤ VIỆC\n\n## 1. Thông tin chung\n[CẦN BỔ SUNG: mã và tên vụ việc]\n\n## 2. Diễn biến\n[CẦN BỔ SUNG: diễn biến có nguồn]\n\n## 3. Tình trạng hiện tại\n[CẦN BỔ SUNG: tình trạng đã xác minh]\n\n## 4. Công việc tiếp theo\n[CẦN BỔ SUNG: đầu việc, người phụ trách và hạn]\n',
   '["matter_code", "report_date"]'::jsonb),
  ('generic_grounded', 'Tài liệu có căn cứ', 'other',
   'Mẫu chung để soạn nội dung từ bộ nguồn đã chọn.',
   'Giữ cấu trúc rõ ràng, đánh dấu mọi thông tin còn thiếu và gắn trích dẫn vào từng nhận định.',
   E'# [CẦN BỔ SUNG: tên tài liệu]\n\n## Mục đích\n[CẦN BỔ SUNG: mục đích]\n\n## Nội dung\n[CẦN BỔ SUNG: nội dung có nguồn]\n\n## Việc cần xác minh\n[CẦN BỔ SUNG: danh sách dữ liệu còn thiếu]\n',
   '[]'::jsonb)
ON CONFLICT (code) DO NOTHING;

CREATE TABLE IF NOT EXISTS analysis_methods (
  id          SERIAL PRIMARY KEY,
  case_type   TEXT NOT NULL,
  steps       TEXT NOT NULL,
  created_by  INT REFERENCES users(id),
  approved    BOOLEAN DEFAULT false,
  embedding   vector(1024),
  created_at  TIMESTAMPTZ DEFAULT now(),
  updated_at  TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_method_vec ON analysis_methods USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS temp_files (
  id              BIGSERIAL PRIMARY KEY,
  conversation_id INT REFERENCES conversations(id) ON DELETE CASCADE,
  user_id         INT REFERENCES users(id),
  filename        TEXT,
  content         TEXT,
  embedding_json  JSONB,
  expires_at      TIMESTAMPTZ DEFAULT (now() + interval '6 hours'),
  created_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_temp_expire ON temp_files(expires_at);

CREATE TABLE IF NOT EXISTS leads (
  id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name TEXT, phone TEXT, email TEXT, need TEXT,
  conversation_id INT REFERENCES conversations(id),
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS audit_log (
  id BIGSERIAL PRIMARY KEY,
  user_id INT, action TEXT NOT NULL, entity TEXT, entity_id INT,
  detail JSONB, created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_log(created_at DESC);
CREATE OR REPLACE FUNCTION block_audit_change() RETURNS TRIGGER AS $$
BEGIN RAISE EXCEPTION 'audit_log chi duoc ghi them'; END; $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_audit_immutable ON audit_log;
CREATE TRIGGER trg_audit_immutable BEFORE UPDATE OR DELETE ON audit_log
  FOR EACH ROW EXECUTE FUNCTION block_audit_change();

-- =============================================================
-- ROW-LEVEL SECURITY
-- App set trước mỗi truy vấn:
--   app.role      = 'internal' | 'client' | 'public'
--   app.client_id = id khách (khi client)
--   app.dept_ids  = CSV phòng user thuộc (khi internal), VD '1,3'
--   app.is_banqt  = 'yes' nếu Ban QT/admin (thấy mọi phòng)
-- =============================================================
-- Mật khẩu vai hds_app truyền từ ngoài vào, không nằm trong mã nguồn:
--   psql -v app_pass="$APP_DB_PASSWORD" -v ON_ERROR_STOP=1 -f sql/schema.sql
-- (scripts/10_init_db.sh đã làm sẵn việc này.)
\if :{?app_pass}
\else
\set app_pass ''
\endif

SELECT (:'app_pass' <> '') AS hds_app_pass_ok \gset

\if :hds_app_pass_ok
\else
\echo ''
\echo '!! DỪNG: thiếu APP_DB_PASSWORD. Sửa .env rồi chạy lại scripts/10_init_db.sh'
\echo ''
\quit
\endif

-- format(%L) trích dẫn an toàn; \gexec vì psql không nội suy biến trong khối $$.
SELECT format('CREATE ROLE hds_app LOGIN PASSWORD %L', :'app_pass')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hds_app')
\gexec
GRANT USAGE ON SCHEMA public TO hds_app;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO hds_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO hds_app;
REVOKE UPDATE, DELETE ON audit_log FROM hds_app;

CREATE OR REPLACE FUNCTION app_in_dept(dept INT) RETURNS BOOLEAN AS $$
  SELECT CASE
    WHEN current_setting('app.is_banqt', true) = 'yes' THEN true
    WHEN dept IS NULL THEN true
    ELSE dept = ANY (string_to_array(
                 NULLIF(current_setting('app.dept_ids', true),''), ',')::INT[])
  END;
$$ LANGUAGE sql STABLE;

-- Tài liệu công nợ/tài chính: chỉ người được admin cấp quyền mới đọc được.
-- Chặn ở đây thì bộ tìm kiếm vector cũng không lôi ra được đoạn công nợ cho
-- người không có quyền — bịt ở tầng Python là bịt hờ, câu hỏi khéo vẫn lọt.
CREATE OR REPLACE FUNCTION app_can_finance() RETURNS BOOLEAN AS $$
  SELECT coalesce(current_setting('app.can_finance', true) = 'yes', false);
$$ LANGUAGE sql STABLE;

ALTER TABLE chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE chunks FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS chunk_access ON chunks;
CREATE POLICY chunk_access ON chunks FOR SELECT USING (
  (doc_type IS DISTINCT FROM 'cong_no' OR app_can_finance())
  AND CASE current_setting('app.role', true)
    WHEN 'internal' THEN
      access_level IN ('public','internal')
      OR (access_level='client' AND app_in_dept(department_id))
    WHEN 'client' THEN
      access_level='public'
      OR (access_level='client'
          AND client_id = NULLIF(current_setting('app.client_id', true),'')::INT)
    WHEN 'public' THEN access_level='public'
    ELSE false
  END
);

ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS doc_access ON documents;
CREATE POLICY doc_access ON documents FOR SELECT USING (
  (doc_type IS DISTINCT FROM 'cong_no' OR app_can_finance())
  AND CASE current_setting('app.role', true)
    WHEN 'internal' THEN true
    WHEN 'client'   THEN access_level='public'
                      OR (access_level='client'
                          AND client_id = NULLIF(current_setting('app.client_id', true),'')::INT)
    WHEN 'public'   THEN access_level='public'
    ELSE false
  END
);
DROP POLICY IF EXISTS doc_ins ON documents;
CREATE POLICY doc_ins ON documents FOR INSERT WITH CHECK (true);
DROP POLICY IF EXISTS doc_upd ON documents;
CREATE POLICY doc_upd ON documents FOR UPDATE USING (current_setting('app.role', true)='internal');

-- Dữ liệu nhân sự và khu vực soạn thảo không bao giờ lộ sang kênh khách/public.
-- Quyền sở hữu/phòng ban của từng bản nháp còn được kiểm tra chặt tại API vì
-- app.user_id không phải session setting của các bản triển khai cũ.
ALTER TABLE employees ENABLE ROW LEVEL SECURITY;
ALTER TABLE employees FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS employee_internal ON employees;
CREATE POLICY employee_internal ON employees FOR ALL
  USING (current_setting('app.role', true)='internal')
  WITH CHECK (current_setting('app.role', true)='internal');

ALTER TABLE employment_contracts ENABLE ROW LEVEL SECURITY;
ALTER TABLE employment_contracts FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS employment_contract_internal ON employment_contracts;
CREATE POLICY employment_contract_internal ON employment_contracts FOR ALL
  USING (current_setting('app.role', true)='internal')
  WITH CHECK (current_setting('app.role', true)='internal');

ALTER TABLE document_templates ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_templates FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS document_template_internal ON document_templates;
CREATE POLICY document_template_internal ON document_templates FOR ALL
  USING (current_setting('app.role', true)='internal')
  WITH CHECK (current_setting('app.role', true)='internal');

ALTER TABLE document_drafts ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_drafts FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS document_draft_internal ON document_drafts;
CREATE POLICY document_draft_internal ON document_drafts FOR ALL
  USING (current_setting('app.role', true)='internal')
  WITH CHECK (current_setting('app.role', true)='internal');

ALTER TABLE document_draft_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_draft_sources FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS document_draft_source_internal ON document_draft_sources;
CREATE POLICY document_draft_source_internal ON document_draft_sources FOR ALL
  USING (current_setting('app.role', true)='internal')
  WITH CHECK (current_setting('app.role', true)='internal');

ALTER TABLE document_draft_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_draft_versions FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS document_draft_version_internal ON document_draft_versions;
CREATE POLICY document_draft_version_internal ON document_draft_versions FOR ALL
  USING (current_setting('app.role', true)='internal')
  WITH CHECK (current_setting('app.role', true)='internal');

ALTER TABLE document_draft_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_draft_evidence FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS document_draft_evidence_internal ON document_draft_evidence;
CREATE POLICY document_draft_evidence_internal ON document_draft_evidence FOR ALL
  USING (current_setting('app.role', true)='internal')
  WITH CHECK (current_setting('app.role', true)='internal');

-- =============================================================
-- CẢNH BÁO VỤ VIỆC — tính trực tiếp, không lưu sẵn
--
-- Cố tình làm VIEW thay vì bảng + tiến trình quét định kỳ:
--   · luôn đúng tại thời điểm hỏi, không có cảnh báo cũ còn treo lại;
--   · sửa hạn hoặc đóng vụ là cảnh báo tự mất, không cần ai bấm "đã xử lý";
--   · không thêm tiến trình nền nào để mà hỏng.
-- Ngưỡng: gấp = quá hạn hoặc còn ≤7 ngày; lưu ý = còn ≤30 ngày, thiếu hạn,
-- hoặc treo quá 60 ngày không có tài liệu mới.
--
-- Bảng matters KHÔNG có RLS nên tầng API phải tự lọc theo phòng ban.
-- =============================================================
CREATE OR REPLACE VIEW v_matter_alerts AS
SELECT
  mt.id                        AS matter_id,
  mt.code                      AS matter_code,
  mt.title                     AS matter_title,
  mt.matter_type,
  mt.status,
  mt.deadline,
  mt.department_id,
  mt.client_id,
  cl.name                      AS client_name,
  cl.code                      AS client_code,
  (mt.deadline - current_date) AS days_left,
  agg.last_doc_at,
  CASE
    WHEN mt.deadline <  current_date      THEN 'qua_han'
    WHEN mt.deadline <= current_date + 7  THEN 'den_han_gap'
    WHEN mt.deadline <= current_date + 30 THEN 'den_han_gan'
    WHEN mt.deadline IS NULL              THEN 'thieu_han'
    ELSE 'treo_lau'
  END AS kind,
  CASE
    WHEN mt.deadline < current_date OR mt.deadline <= current_date + 7 THEN 'gap'
    ELSE 'luu_y'
  END AS severity
FROM matters mt
JOIN clients cl ON cl.id = mt.client_id
LEFT JOIN LATERAL (
  SELECT max(d.created_at) AS last_doc_at FROM documents d WHERE d.matter_id = mt.id
) agg ON true
WHERE mt.status IN ('tiep_nhan','dang_xu_ly','tam_dung')
  AND (
    mt.deadline <= current_date + 30
    OR (mt.deadline IS NULL AND mt.status = 'dang_xu_ly')
    OR (mt.status = 'dang_xu_ly'
        AND coalesce(agg.last_doc_at, mt.created_at) < now() - interval '60 days')
  );

CREATE OR REPLACE VIEW v_kb_stats AS
SELECT d.access_level, d.doc_type,
       count(DISTINCT d.id) AS so_tai_lieu, count(c.id) AS so_doan,
       count(DISTINCT d.id) FILTER (WHERE NOT d.label_verified) AS chua_duyet
FROM documents d LEFT JOIN chunks c ON c.document_id=d.id
GROUP BY 1,2 ORDER BY 1,2;

-- GRANT ở phần trên chạy TRƯỚC khi các view này tồn tại nên không với tới
-- chúng. Cấp lại ở đây để vai ứng dụng đọc được mà không phải mở phiên admin.
GRANT SELECT ON v_matter_alerts, v_kb_stats TO hds_app;

-- =============================================================
-- CÀI ĐẶT ỨNG DỤNG (admin sửa trên web, không cần sửa code)
-- Chứa: phong cách tư vấn / system prompt cho từng kênh,
--        bản đồ thư mục Drive → nhãn tài liệu, tham số sinh câu trả lời.
-- =============================================================
CREATE TABLE IF NOT EXISTS app_settings (
  key        TEXT PRIMARY KEY,
  value      TEXT NOT NULL,
  updated_by INT REFERENCES users(id),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- =============================================================
-- BÁO CÁO CHẤT LƯỢNG CÂU TRẢ LỜI
-- Mọi vai đều gửi được (nút nhỏ cạnh câu trả lời của AI).
-- Chỉ admin/người có quyền duyệt được xem và xử lý.
-- =============================================================
CREATE TABLE IF NOT EXISTS answer_feedback (
  id          BIGSERIAL PRIMARY KEY,
  message_id  BIGINT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
  user_id     INT REFERENCES users(id),
  rating      TEXT NOT NULL CHECK (rating IN ('good','bad')),
  note        TEXT,
  status      TEXT NOT NULL DEFAULT 'pending'
              CHECK (status IN ('pending','applied','rejected')),
  admin_note  TEXT,
  reviewed_by INT REFERENCES users(id),
  reviewed_at TIMESTAMPTZ,
  created_at  TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_feedback_pending ON answer_feedback(status) WHERE status='pending';
CREATE INDEX IF NOT EXISTS idx_feedback_msg ON answer_feedback(message_id);

-- =============================================================
-- GHI CHÚ CÁ NHÂN (mỗi người tự ghi lại điều quan trọng trong khung chat)
-- Có thể gắn với một câu trả lời của AI (source_message_id) để "lưu note" nhanh.
-- =============================================================
CREATE TABLE IF NOT EXISTS notes (
  id                BIGSERIAL PRIMARY KEY,
  user_id           INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  content           TEXT NOT NULL,
  source_message_id BIGINT REFERENCES messages(id) ON DELETE SET NULL,
  created_at        TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_notes_user ON notes(user_id, created_at DESC);
GRANT SELECT, INSERT, UPDATE, DELETE ON notes TO hds_app;
GRANT USAGE, SELECT ON SEQUENCE notes_id_seq TO hds_app;

-- ============================================================
-- TÀI LIỆU CÓ TRONG DRIVE NHƯNG KHÔNG HỌC ĐƯỢC
-- ------------------------------------------------------------
-- Trước đây lỗi đọc file chỉ nằm trong JSON của LẦN QUÉT GẦN NHẤT. File hỏng
-- từ ba lần quét trước sẽ biến mất khỏi báo cáo (lần sau nó không đổi nên
-- không được quét lại), nên không ai biết mà đi sửa — tài liệu cứ thiếu âm
-- thầm trong kho. Bảng này giữ lỗi cho tới khi file được học thành công.
CREATE TABLE IF NOT EXISTS ingest_failures (
  id            SERIAL PRIMARY KEY,
  drive_file_id TEXT UNIQUE,
  file_name     TEXT NOT NULL,
  location      TEXT,                    -- đường dẫn thư mục trong Drive
  error_code    TEXT NOT NULL,           -- mã ổn định: pdf_no_text, unsupported…
  error_message TEXT,
  hint          TEXT,                    -- cách sửa, hiện thẳng cho admin
  attempts      INT DEFAULT 1,
  first_seen_at TIMESTAMPTZ DEFAULT now(),
  last_seen_at  TIMESTAMPTZ DEFAULT now(),
  resolved_at   TIMESTAMPTZ              -- có giá trị = đã học được, chỉ để đối chiếu
);
CREATE INDEX IF NOT EXISTS idx_ingest_failures_open
  ON ingest_failures(resolved_at, last_seen_at DESC);
