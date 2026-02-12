-- PostgreSQL Database Schema for Secure PDF Chat Application
-- Ensure pgvector extension is installed first

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgvector";

-- Users table
CREATE TABLE users (
    user_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    clerk_user_id VARCHAR(255) UNIQUE NOT NULL,
    tenant_id UUID UNIQUE NOT NULL DEFAULT uuid_generate_v4(),
    email_encrypted BYTEA,
    created_at TIMESTAMP DEFAULT NOW(),
    last_active TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_clerk_user ON users(clerk_user_id);
CREATE INDEX idx_tenant ON users(tenant_id);

-- Documents table
CREATE TABLE documents (
    document_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES users(tenant_id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    
    document_hash VARCHAR(64) NOT NULL,
    encryption_key_id VARCHAR(255) NOT NULL,
    
    original_filename_encrypted BYTEA NOT NULL,
    s3_bucket VARCHAR(255) NOT NULL,
    s3_key_encrypted BYTEA NOT NULL,
    file_size_bytes BIGINT NOT NULL,
    
    total_chunks INT,
    embedding_model VARCHAR(100) DEFAULT 'amazon.titan-embed-text-v2:0',
    
    upload_date TIMESTAMP DEFAULT NOW(),
    processed_at TIMESTAMP,
    is_deleted BOOLEAN DEFAULT FALSE
);

CREATE INDEX idx_tenant_docs ON documents(tenant_id, is_deleted);
CREATE INDEX idx_doc_hash ON documents(document_hash);
CREATE UNIQUE INDEX idx_tenant_doc_hash ON documents(tenant_id, document_hash);

-- Document chunks with embeddings
CREATE TABLE document_chunks (
    chunk_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id UUID NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL,
    
    chunk_index INT NOT NULL,
    chunk_text_encrypted BYTEA NOT NULL,
    chunk_metadata JSONB,
    
    embedding vector(1024),
    
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_chunk_doc ON document_chunks(document_id);
CREATE INDEX idx_chunk_tenant ON document_chunks(tenant_id);
CREATE INDEX idx_chunk_embedding ON document_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- Chat sessions
CREATE TABLE chat_sessions (
    session_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES users(tenant_id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    
    session_name_encrypted BYTEA,
    created_at TIMESTAMP DEFAULT NOW(),
    last_message_at TIMESTAMP DEFAULT NOW(),
    is_active BOOLEAN DEFAULT TRUE,
    is_deleted BOOLEAN DEFAULT FALSE
);

CREATE INDEX idx_session_tenant ON chat_sessions(tenant_id, is_deleted);
CREATE INDEX idx_session_active ON chat_sessions(user_id, is_active);

-- Chat messages
CREATE TABLE chat_messages (
    message_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id UUID NOT NULL REFERENCES chat_sessions(session_id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL,
    
    role VARCHAR(20) NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    message_text_encrypted BYTEA NOT NULL,
    
    retrieved_chunks JSONB,
    model_used VARCHAR(100),
    
    timestamp TIMESTAMP DEFAULT NOW(),
    response_sequence INT
);

CREATE INDEX idx_msg_session ON chat_messages(session_id, timestamp);
CREATE INDEX idx_msg_tenant ON chat_messages(tenant_id);

-- Feedback
CREATE TABLE feedback (
    feedback_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL,
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    message_id UUID NOT NULL REFERENCES chat_messages(message_id) ON DELETE CASCADE,
    session_id UUID NOT NULL REFERENCES chat_sessions(session_id) ON DELETE CASCADE,
    
    rating VARCHAR(10) CHECK (rating IN ('yes', 'no')),
    comments_encrypted BYTEA,
    
    email_sent BOOLEAN DEFAULT FALSE,
    email_sent_at TIMESTAMP,
    
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_feedback_tenant ON feedback(tenant_id);
CREATE INDEX idx_feedback_email ON feedback(email_sent);

-- Audit log
CREATE TABLE audit_log (
    log_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID,
    user_id UUID,
    
    action VARCHAR(100) NOT NULL,
    resource_type VARCHAR(50),
    resource_id UUID,
    
    ip_address INET,
    user_agent TEXT,
    
    timestamp TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_audit_tenant ON audit_log(tenant_id, timestamp);
CREATE INDEX idx_audit_action ON audit_log(action);

-- Enable Row-Level Security (RLS)
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE chat_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE chat_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE feedback ENABLE ROW LEVEL SECURITY;

-- RLS Policies (example for documents table)
CREATE POLICY tenant_isolation_policy ON documents
    USING (tenant_id = current_setting('app.current_tenant_id', true)::UUID);

CREATE POLICY tenant_isolation_policy ON document_chunks
    USING (tenant_id = current_setting('app.current_tenant_id', true)::UUID);

CREATE POLICY tenant_isolation_policy ON chat_sessions
    USING (tenant_id = current_setting('app.current_tenant_id', true)::UUID);

CREATE POLICY tenant_isolation_policy ON chat_messages
    USING (tenant_id = current_setting('app.current_tenant_id', true)::UUID);

CREATE POLICY tenant_isolation_policy ON feedback
    USING (tenant_id = current_setting('app.current_tenant_id', true)::UUID);
