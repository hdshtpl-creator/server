-- ====================================================================
-- HDS Law Firm - Internal PostgreSQL Schema & Row-Level Security (RLS)
-- Cơ sở dữ liệu: hds_legal_db (Chạy Docker trên Ubuntu nội bộ)
-- ====================================================================
--
-- CÁCH CHẠY (mật khẩu lấy từ biến môi trường, không nằm trong tệp này):
--
--   set -a && . ./.env && set +a
--   psql -v ON_ERROR_STOP=1 -d hds_legal_db -f init_schema.sql
--
-- Yêu cầu psql 15 trở lên (dùng lệnh \getenv). Với bản cũ hơn, truyền tay:
--
--   psql -v ON_ERROR_STOP=1 \
--        -v admin_pass="$DB_PASS_ADMIN" -v app_pass="$DB_PASS_APP" \
--        -d hds_legal_db -f init_schema.sql
-- ====================================================================

-- 1. KÍCH HOẠT EXTENSION PGVECTOR (1024 chiều từ Ollama bge-m3)
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. TẠO HAI TÀI KHOẢN CSDL TÁCH BIỆT
-- Ưu tiên giá trị truyền bằng -v; nếu không có thì đọc từ biến môi trường.
-- Chỉ đặt chuỗi rỗng khi cả hai đều vắng, để phần kiểm tra bên dưới luôn chạy
-- được thay vì lỗi cú pháp do biến chưa tồn tại.
\if :{?admin_pass}
\else
\getenv admin_pass DB_PASS_ADMIN
\endif
\if :{?admin_pass}
\else
\set admin_pass ''
\endif

\if :{?app_pass}
\else
\getenv app_pass DB_PASS_APP
\endif
\if :{?app_pass}
\else
\set app_pass ''
\endif

SELECT (:'admin_pass' <> '' AND :'app_pass' <> '') AS hds_creds_ok \gset

\if :hds_creds_ok
\else
\echo ''
\echo '!! DỪNG: chưa có DB_PASS_ADMIN và/hoặc DB_PASS_APP trong môi trường.'
\echo '!! Sao chép .env.example thành .env, điền mật khẩu, rồi nạp lại:'
\echo '!!   set -a && . ./.env && set +a'
\echo ''
\quit
\endif

-- format(%L) trích dẫn mật khẩu đúng chuẩn nên ký tự đặc biệt không phá cú pháp.
-- Dùng \gexec vì psql KHÔNG nội suy biến bên trong khối $$ ... $$.
SELECT format('CREATE ROLE hds WITH LOGIN SUPERUSER PASSWORD %L', :'admin_pass')
 WHERE NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'hds')
\gexec

SELECT format(
         'CREATE ROLE hds_app WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %L',
         :'app_pass')
 WHERE NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'hds_app')
\gexec

-- 3. BẢNG KHÁCH HÀNG (clients)
CREATE TABLE IF NOT EXISTS clients (
    id VARCHAR(50) PRIMARY KEY,
    code VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    phone VARCHAR(50),
    email VARCHAR(100),
    department VARCHAR(100),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 4. BẢNG NGƯỜI DÙNG (users)
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    full_name VARCHAR(150) NOT NULL,
    email VARCHAR(150) UNIQUE NOT NULL,
    role VARCHAR(50) NOT NULL DEFAULT 'chuyen_vien', -- admin, ban_qt, truong_bph, chuyen_vien, tro_ly, client_free, client_plus, client_pro
    can_review BOOLEAN DEFAULT FALSE,
    client_id VARCHAR(50) REFERENCES clients(id) ON DELETE SET NULL,
    department_ids INTEGER[] DEFAULT '{1}',
    head_of INTEGER[] DEFAULT '{}',
    monthly_quota INTEGER DEFAULT 300,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 5. BẢNG VĂN BẢN & HỒ SƠ TÀI LIỆU (documents)
CREATE TABLE IF NOT EXISTS documents (
    id VARCHAR(100) PRIMARY KEY,
    title TEXT NOT NULL,
    doc_type VARCHAR(100) DEFAULT 'legal_doc',
    access_level VARCHAR(20) NOT NULL DEFAULT 'internal', -- 'internal', 'client', 'public'
    department_id INTEGER DEFAULT 1,
    client_id VARCHAR(50) REFERENCES clients(id) ON DELETE SET NULL,
    review_status VARCHAR(30) DEFAULT 'da_duyet', -- 'cho_duyet', 'da_duyet'
    file_path TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 6. BẢNG ĐOẠN TRÍCH VECTOR (chunks) - 1024 CHIỀU CHO BGE-M3 OLLAMA
CREATE TABLE IF NOT EXISTS chunks (
    id VARCHAR(100) PRIMARY KEY,
    doc_id VARCHAR(100) REFERENCES documents(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    embedding vector(1024), -- Vector 1024 chiều cho Ollama bge-m3 / Qwen3
    access_level VARCHAR(20) NOT NULL DEFAULT 'internal', -- 'internal', 'client', 'public'
    client_id VARCHAR(50) REFERENCES clients(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 7. BẢNG HỘI THOẠI AI (conversations)
CREATE TABLE IF NOT EXISTS conversations (
    id VARCHAR(100) PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    client_id VARCHAR(50) REFERENCES clients(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 8. BẢNG TIN NHẮN (messages)
CREATE TABLE IF NOT EXISTS messages (
    id VARCHAR(100) PRIMARY KEY,
    conversation_id VARCHAR(100) REFERENCES conversations(id) ON DELETE CASCADE,
    sender VARCHAR(20) NOT NULL, -- 'user', 'ai'
    text TEXT NOT NULL,
    sources JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 9. BẢNG MẪU PHƯƠNG PHÁP XỬ LÝ VỤ VIỆC (analysis_methods)
CREATE TABLE IF NOT EXISTS analysis_methods (
    id SERIAL PRIMARY KEY,
    case_type VARCHAR(150) NOT NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    steps JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 10. BẢNG FILE TẠM THỜI CHAT (temp_files)
CREATE TABLE IF NOT EXISTS temp_files (
    id VARCHAR(100) PRIMARY KEY,
    conversation_id VARCHAR(100) REFERENCES conversations(id) ON DELETE CASCADE,
    filename VARCHAR(255) NOT NULL,
    file_path TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 11. BẢNG NHẬT KÝ TÁC VỤ AN NINH (audit_log)
CREATE TABLE IF NOT EXISTS audit_log (
    id SERIAL PRIMARY KEY,
    action VARCHAR(100) NOT NULL,
    user_id INTEGER,
    client_id VARCHAR(50),
    details JSONB,
    ip_address VARCHAR(45),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- ====================================================================
-- CẤP QUYỀN VÀ THIẾT LẬP ROW-LEVEL SECURITY (RLS) TẦNG CSDL
-- ====================================================================

-- Cấp quyền bảng cho hds_app
GRANT USAGE ON SCHEMA public TO hds_app;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO hds_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO hds_app;

-- BẢO VỆ NHẬT KÝ AUDIT: hds_app CHỈ ĐƯỢC INSERT, KHÔNG ĐƯỢC XÓA SỬA
REVOKE UPDATE, DELETE ON audit_log FROM hds_app;

-- BẬT ROW LEVEL SECURITY (RLS) TRÊN BẢNG DOCUMENTS VÀ CHUNKS
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE chunks ENABLE ROW LEVEL SECURITY;

-- Bỏ các policy cũ nếu có
DROP POLICY IF EXISTS rls_documents_policy ON documents;
DROP POLICY IF EXISTS rls_chunks_policy ON chunks;

-- POLICY BẢNG DOCUMENTS
CREATE POLICY rls_documents_policy ON documents
    FOR SELECT
    USING (
        -- Thẩm quyền Nhân viên / Admin HDS: Xem được tất cả
        current_setting('app.role', true) = 'internal'
        OR
        -- Thẩm quyền Khách hàng: Xem tài liệu public HOẶC đúng client_id sở hữu
        (
            current_setting('app.role', true) = 'client'
            AND (
                access_level = 'public'
                OR (access_level = 'client' AND client_id IS NOT NULL AND client_id = current_setting('app.client_id', true))
            )
        )
        OR
        -- Thẩm quyền Công khai / Khách vãng lai
        (
            current_setting('app.role', true) = 'public'
            AND access_level = 'public'
        )
    );

-- POLICY BẢNG CHUNKS
CREATE POLICY rls_chunks_policy ON chunks
    FOR SELECT
    USING (
        current_setting('app.role', true) = 'internal'
        OR
        (
            current_setting('app.role', true) = 'client'
            AND (
                access_level = 'public'
                OR (access_level = 'client' AND client_id IS NOT NULL AND client_id = current_setting('app.client_id', true))
            )
        )
        OR
        (
            current_setting('app.role', true) = 'public'
            AND access_level = 'public'
        )
    );
