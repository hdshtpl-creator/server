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
-- Tên THƯ MỤC CON trong "8. HỒ SƠ NHÂN SỰ" mà file thuộc về ("Ngân", "Mai").
-- Nguyên tắc 21/08/2026: CÂY THƯ MỤC là nguồn sự thật về số lượng — bao nhiêu
-- bộ (thư mục con) là bấy nhiêu nhân sự, chi tiết nằm trong từng bộ; giống
-- cách mỗi thư mục [MÃ] trong ngăn 9 là một khách hàng (bảng clients).
ALTER TABLE documents ADD COLUMN IF NOT EXISTS person_folder TEXT;
-- Danh tính nguồn CŨ trước khi chuyển kho từ Drive về máy chủ (27/08/2026).
-- Giữ lại để `python -m app.local_learn --chuyen-doi --nguoc` còn đường lùi.
ALTER TABLE documents ADD COLUMN IF NOT EXISTS prev_source_key TEXT;
-- Tỉ lệ token KHÔNG đọc được trong nội dung đã trích xuất (app/chat_luong.py),
-- do `python -m app.duyet_hang_loat` chấm. Dùng để duyệt nhãn hàng loạt mà vẫn
-- giữ file OCR hỏng lại cho mắt người, và để tab Duyệt nhãn xếp cái tệ lên
-- trước. NULL = chưa chấm bao giờ.
ALTER TABLE documents ADD COLUMN IF NOT EXISTS ty_le_rac REAL;
CREATE INDEX IF NOT EXISTS idx_doc_ready_active
  ON documents(active, extraction_status, approved, label_verified);
-- Bộ quét thư mục dò file ĐỔI TÊN / CHUYỂN THƯ MỤC bằng md5 nội dung: không có
-- chỉ mục này thì mỗi file lạ phải quét toàn bảng documents.
CREATE INDEX IF NOT EXISTS idx_doc_checksum ON documents(checksum);

-- -------------------------------------------------------------
-- NÂNG CẤP CSDL TẠO TỪ BẢN TRƯỚC
-- CREATE TABLE IF NOT EXISTS ở trên không chạm vào bảng đã tồn tại, nên cột và
-- ràng buộc mới phải thêm bằng ALTER. deploy/update.sh nạp lại đúng file này
-- mỗi lần cập nhật, nên khai ở đây là máy chủ tự lên phiên bản mới.
-- -------------------------------------------------------------
ALTER TABLE users ADD COLUMN IF NOT EXISTS can_view_finance BOOLEAN DEFAULT false;
-- 27/08/2026: bỏ Google Drive, kho tài liệu chuyển hẳn về thư mục trên máy chủ.
-- Thêm nguồn 'local' cho tài liệu do bộ quét thư mục nội bộ (app/local_learn.py)
-- nạp vào. Giữ 'drive' để tài liệu học từ Drive trước đây vẫn hợp lệ.
ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_source_kind_check;
ALTER TABLE documents ADD CONSTRAINT documents_source_kind_check CHECK (source_kind IN
  ('drive','local','manual','chat','web'));
ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_doc_type_check;
ALTER TABLE documents ADD CONSTRAINT documents_doc_type_check CHECK (doc_type IN
  ('law','ban_an','an_le','mau_hd','nhan_hieu','thu_mau','quy_trinh','ho_so_ns',
   'ho_so_kh','advisory','filing','contract','cong_no','other'));

-- 31/08/2026: DANH TÍNH VĂN BẢN PHÁP LUẬT. Trước đây kho chỉ biết tên file —
-- không số hiệu, không ngày, không trạng thái hiệu lực: luật 2012 đã bị thay
-- và luật 2019 thay nó nằm cạnh nhau mà bộ tra cứu không phân biệt được.
-- Bóc tự động lúc học (app/van_ban.py), người duyệt sửa được khi duyệt nhãn.
-- Tất cả nullable: văn bản không phải luật không có các trường này — bình thường.
ALTER TABLE documents ADD COLUMN IF NOT EXISTS so_hieu TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS loai_van_ban TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS trich_yeu TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS ngay_ban_hanh DATE;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS ngay_hieu_luc DATE;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS trang_thai_hieu_luc TEXT DEFAULT 'chua_ro';
ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_trang_thai_hieu_luc_check;
ALTER TABLE documents ADD CONSTRAINT documents_trang_thai_hieu_luc_check CHECK
  (trang_thai_hieu_luc IN ('chua_ro','con_hieu_luc','het_hieu_luc_mot_phan','het_hieu_luc'));
-- Khoá đối chiếu giữa các văn bản: JOIN theo lower(so_hieu) ở bảng quan hệ.
CREATE INDEX IF NOT EXISTS idx_doc_so_hieu ON documents(lower(so_hieu))
  WHERE so_hieu IS NOT NULL;

-- QUAN HỆ GIỮA CÁC VĂN BẢN: A thay_the B, A sua_doi_bo_sung B, A huong_dan B…
-- Khoá theo SỐ HIỆU chứ KHÔNG theo documents.id — mỗi lần file được học lại,
-- learn_one XOÁ bản ghi documents cũ và INSERT bản mới với id MỚI (chunks
-- CASCADE theo); quan hệ khoá theo id sẽ bốc hơi im lặng sau mỗi lần sửa file.
-- Văn bản đích có thể CHƯA có trong kho: giữ so_hieu_dich/ten_dich để hiển thị,
-- tự nối khi văn bản đó được học về sau.
-- KHÔNG bật RLS — có chủ ý: quan hệ chỉ tồn tại giữa văn bản luật (kệ public,
-- xem drive_map), và cảnh báo hết hiệu lực phải chạy được cả trên kênh public.
-- Tiêu đề tài liệu đối ứng khi hiển thị vẫn đi qua can_open_doc/mask_title ở
-- tầng API.
CREATE TABLE IF NOT EXISTS van_ban_quan_he (
  id             SERIAL PRIMARY KEY,
  so_hieu_nguon  TEXT NOT NULL,
  ten_nguon      TEXT,
  loai           TEXT NOT NULL CHECK (loai IN
                   ('thay_the','bai_bo','sua_doi_bo_sung','huong_dan',
                    'hop_nhat','can_cu','lien_quan')),
  so_hieu_dich   TEXT,
  ten_dich       TEXT,
  nguon          TEXT NOT NULL DEFAULT 'auto' CHECK (nguon IN ('auto','manual')),
  ghi_chu        TEXT,
  created_by     INT REFERENCES users(id),
  created_at     TIMESTAMPTZ DEFAULT now(),
  CONSTRAINT quan_he_phai_co_dich CHECK (so_hieu_dich IS NOT NULL OR ten_dich IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_vbqh_nguon ON van_ban_quan_he(lower(so_hieu_nguon));
CREATE INDEX IF NOT EXISTS idx_vbqh_dich ON van_ban_quan_he(lower(so_hieu_dich))
  WHERE so_hieu_dich IS NOT NULL;
-- Chặn trùng khi học lại chạy song song; app tự khử trùng trước bằng NOT EXISTS.
CREATE UNIQUE INDEX IF NOT EXISTS idx_vbqh_duy_nhat ON van_ban_quan_he
  (lower(so_hieu_nguon), loai, lower(coalesce(so_hieu_dich,'')), lower(coalesce(ten_dich,'')));
-- GRANT cho hds_app nằm DƯỚI khối tạo role (sau dòng \quit) — đặt ở đây thì
-- CSDL dựng mới chết vì role chưa tồn tại. Tìm "van_ban_quan_he TO hds_app".

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
-- Tìm trong MỘT văn bản (câu hỏi nêu đích danh luật, hồ sơ một người, đoạn
-- liền kề): không có chỉ mục này là quét tuần tự cả kho 540.000 đoạn cho
-- mỗi lượt (08/09/2026).
CREATE INDEX IF NOT EXISTS idx_chunks_doc_idx ON chunks(document_id, chunk_index);
-- Lọc theo kệ (doc_type=ANY) trước khi so từ khoá: không có thì lượt OR trên
-- kệ luật 4.000 đoạn vẫn quét cả 540.000 đoạn (11/09/2026).
CREATE INDEX IF NOT EXISTS idx_chunks_doc_type ON chunks(doc_type);
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
-- Loại hội thoại: 'chat' = tab Hội thoại AI; 'legal' = tab Kiểm tra pháp lý.
-- Tách ra để hai tab có lịch sử riêng — phiên kiểm tra hồ sơ không lẫn vào cột
-- hội thoại thường và ngược lại.
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'chat';
-- BỘ NHỚ DÀI (kiểu Claude/ChatGPT): hội thoại vượt cửa sổ nhớ nguyên văn thì
-- phần cũ được LLM cô đọng vào `summary`; `summary_upto` là id tin nhắn cuối
-- cùng đã gộp — các tin sau mốc này vẫn đưa vào prompt nguyên văn.
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS summary TEXT;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS summary_upto BIGINT NOT NULL DEFAULT 0;
-- Chuyển các phiên tab Kiểm tra pháp lý tạo TRƯỚC khi có cột kind. File này
-- được update.sh chạy lại MỖI lần nâng cấp, nên mẫu so khớp phải chặt đúng
-- title máy đóng dấu ("Kiểm tra pháp lý 28/08 12:33") — so LIKE 'Kiểm tra
-- pháp lý%' là vơ luôn hội thoại thường mà CÂU HỎI ĐẦU của người dùng mở đầu
-- bằng mấy chữ đó (title chat đặt theo câu hỏi đầu), âm thầm giấu nó khỏi cột
-- chat ở lần deploy kế tiếp.
UPDATE conversations SET kind='legal'
 WHERE kind='chat'
   AND title ~ '^Kiểm tra pháp lý [0-9]{2}/[0-9]{2} [0-9]{2}:[0-9]{2}$';

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
  -- Bản .docx GỐC của file đính kèm (data/work/chat_uploads/…): luồng "tạo bộ
  -- file" dùng nó làm khuôn giữ định dạng. NULL với định dạng khác.
  source_path     TEXT,
  expires_at      TIMESTAMPTZ DEFAULT (now() + interval '6 hours'),
  created_at      TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE temp_files ADD COLUMN IF NOT EXISTS source_path TEXT;
-- Bản tóm tắt của TỪNG file đính kèm, LLM sinh ở luồng nền sau khi tải lên.
-- Đây là cách đọc "10 file cùng lúc": cửa sổ model chỉ ~85 nghìn ký tự nên
-- không nhét trọn 10 file vào một lượt được — thay vào đó mỗi file được đọc
-- riêng thành một bản tóm tắt, và câu hỏi khái quát ("tóm tắt", "so sánh")
-- nhận đủ 10 bản tóm tắt + các đoạn chi tiết liên quan nhất.
ALTER TABLE temp_files ADD COLUMN IF NOT EXISTS summary TEXT;
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

-- temp_files: file "dùng xong bỏ" phải XOÁ THẬT được bằng tài khoản ứng dụng —
-- nút × trong chat (DELETE /temp-files/{id}) và lượt dọn quá hạn 6 giờ đều
-- chạy trên kết nối hds_app. GRANT chung ở trên KHÔNG có DELETE, nên trước
-- bản vá này nút × trả 500 "Internal Server Error", còn lượt dọn quá hạn chết
-- im lặng trong try/except — hồ sơ khách nằm lại vô hạn (ca thật 29/08/2026).
GRANT SELECT, INSERT, UPDATE, DELETE ON temp_files TO hds_app;

-- van_ban_quan_he: khai ở khối nâng cấp phía trên (trước khi role hds_app chắc
-- chắn tồn tại) nên GRANT nằm đây. Cần DELETE thật: gỡ một dòng quan hệ sai là
-- thao tác thường ngày của người duyệt, thiếu DELETE thì nút gỡ trả 500 im lặng
-- (đúng vết xe temp_files 29/08/2026).
GRANT SELECT, INSERT, UPDATE, DELETE ON van_ban_quan_he TO hds_app;
GRANT USAGE, SELECT ON SEQUENCE van_ban_quan_he_id_seq TO hds_app;

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

-- ============================================================
-- BỘ MẪU HỒ SƠ (15/09/2026)
-- ------------------------------------------------------------
-- Một "bộ mẫu" = nhóm file .docx mẫu đi cùng nhau (hợp đồng + phụ lục + biên
-- bản bàn giao…), tải lên từ Quản trị → Bộ mẫu hồ sơ. Trong chat, chọn bộ
-- (hoặc gọi tên bộ trong câu lệnh) là AI điền dữ liệu khách vào TỪNG file
-- của bộ trong một lượt — dữ liệu lấy từ file đính kèm, lịch sử hội thoại và
-- câu lệnh. Tệp gốc nằm ở data/work/bo_mau/<id>/ (ngoài kho tri thức: mẫu
-- không cần học/duyệt nhãn, chỉ cần điền).
-- department_id NULL = cả công ty dùng được; có giá trị = chỉ phòng đó
-- (và Ban quản trị/admin).
CREATE TABLE IF NOT EXISTS bo_mau (
  id            SERIAL PRIMARY KEY,
  ten           TEXT NOT NULL,
  mo_ta         TEXT,
  department_id INT REFERENCES departments(id),
  created_by    INT REFERENCES users(id),
  active        BOOLEAN NOT NULL DEFAULT true,
  created_at    TIMESTAMPTZ DEFAULT now(),
  updated_at    TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS bo_mau_file (
  id            SERIAL PRIMARY KEY,
  bo_mau_id     INT NOT NULL REFERENCES bo_mau(id) ON DELETE CASCADE,
  ten_file      TEXT NOT NULL,          -- tên hiển thị (tên file gốc)
  duong_dan     TEXT NOT NULL,          -- data/work/bo_mau/<bo>/<uuid>_<tên>.docx
  thu_tu        INT NOT NULL DEFAULT 0,
  placeholders  JSONB,                  -- {{…}} quét sẵn lúc tải lên
  so_ky_tu      INT,
  created_at    TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_bo_mau_file_bo ON bo_mau_file(bo_mau_id, thu_tu, id);
-- Tài khoản ứng dụng cần DELETE thật (gỡ bộ / gỡ file là thao tác thường ngày
-- của người duyệt) — GRANT chung phía trên không có DELETE, đúng vết xe
-- temp_files 29/08/2026.
GRANT SELECT, INSERT, UPDATE, DELETE ON bo_mau, bo_mau_file TO hds_app;
GRANT USAGE, SELECT ON SEQUENCE bo_mau_id_seq, bo_mau_file_id_seq TO hds_app;

-- ============================================================
-- HOÀN THIỆN GIAI ĐOẠN 1 (15/09/2026)
-- ------------------------------------------------------------
-- (a) Lý do sửa nội dung tài liệu kho — kế hoạch ngày 3: "mỗi lần chỉnh sửa
--     ghi nhận lý do (Luật thay đổi / Rủi ro / Yêu cầu khách hàng)". Bảng
--     document_versions có từ đầu nhưng chưa ai ghi vào; nay PUT
--     /review/{id}/content lưu bản cũ + bản mới kèm lý do.
ALTER TABLE document_versions ADD COLUMN IF NOT EXISTS edit_reason TEXT;
GRANT SELECT, INSERT ON document_versions TO hds_app;
GRANT USAGE, SELECT ON SEQUENCE document_versions_id_seq TO hds_app;

-- (b) Kiểm tra mâu thuẫn pháp lý CHẠY NỀN sau mỗi lần lưu bản thảo (kế hoạch
--     ngày 9). Một dòng cho mỗi (bản nháp, phiên bản); items là bảng từng
--     cam kết/thời hạn/con số với kết luận hop_le / canh_bao / khong_ro.
CREATE TABLE IF NOT EXISTS draft_checks (
  id            SERIAL PRIMARY KEY,
  draft_id      INT NOT NULL REFERENCES document_drafts(id) ON DELETE CASCADE,
  version_no    INT NOT NULL,
  status        TEXT NOT NULL DEFAULT 'running',   -- running | done | error
  ket_luan      TEXT,                              -- hop_le | canh_bao | khong_ro
  so_canh_bao   INT DEFAULT 0,
  so_muc        INT DEFAULT 0,
  phuong_phap   TEXT,
  items         JSONB DEFAULT '[]'::jsonb,
  error         TEXT,
  started_at    TIMESTAMPTZ DEFAULT now(),
  finished_at   TIMESTAMPTZ,
  UNIQUE (draft_id, version_no)
);
GRANT SELECT, INSERT, UPDATE, DELETE ON draft_checks TO hds_app;
GRANT USAGE, SELECT ON SEQUENCE draft_checks_id_seq TO hds_app;

-- (c) Khách quan tâm từ khung chat nhúng website (kế hoạch ngày 4–5). Bảng
--     leads có sẵn nhưng chưa có cột xử lý; nay thêm trạng thái để Ban QT
--     theo dõi đã liên hệ chưa.
ALTER TABLE leads ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'moi';  -- moi | da_lien_he | bo_qua
ALTER TABLE leads ADD COLUMN IF NOT EXISTS handled_by INT REFERENCES users(id);
ALTER TABLE leads ADD COLUMN IF NOT EXISTS handled_at TIMESTAMPTZ;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS note TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS source TEXT DEFAULT 'website';
ALTER TABLE leads ADD COLUMN IF NOT EXISTS ip TEXT;
CREATE INDEX IF NOT EXISTS idx_leads_status_time ON leads(status, created_at DESC);
GRANT SELECT, INSERT, UPDATE ON leads TO hds_app;
GRANT USAGE, SELECT ON SEQUENCE leads_id_seq TO hds_app;

-- ============================================================
-- BỘ QUÉT KHO: KHÔNG THỬ LẠI TỆP HỎNG MỖI LƯỢT (16/09/2026)
-- ------------------------------------------------------------
-- Đo 16/09: một lượt quét mất 5 phút 32 giây, trong khi đi hết 42.103 tệp và
-- so md5 chỉ tốn 8 giây. Hơn 5 phút còn lại là 65 tệp KHÔNG ĐỌC ĐƯỢC bị thử
-- lại mỗi lượt — 54 tệp trong đó là PDF không có lớp chữ nên lần nào cũng
-- chạy OCR từ đầu rồi lại hỏng (một tệp đã thử 924 lần từ 19/08).
-- Nhớ md5 của tệp lúc hỏng: lượt sau tệp còn nguyên md5 thì bỏ qua, chỉ thử
-- lại khi NỘI DUNG đổi (người sửa/quét lại) hoặc khi chạy tay --thu-lai-loi.
ALTER TABLE ingest_failures ADD COLUMN IF NOT EXISTS checksum TEXT;
