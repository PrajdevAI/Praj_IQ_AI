--
-- PostgreSQL database dump
--

-- Dumped from database version 16.11
-- Dumped by pg_dump version 17.4

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: uuid-ossp; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA public;


--
-- Name: EXTENSION "uuid-ossp"; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION "uuid-ossp" IS 'generate universally unique identifiers (UUIDs)';


--
-- Name: vector; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;


--
-- Name: EXTENSION vector; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION vector IS 'vector data type and ivfflat and hnsw access methods';


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: audit_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_log (
    log_id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    tenant_id uuid,
    user_id uuid,
    action character varying(100) NOT NULL,
    resource_type character varying(50),
    resource_id uuid,
    ip_address inet,
    user_agent text,
    "timestamp" timestamp without time zone DEFAULT now()
);


--
-- Name: chat_messages; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.chat_messages (
    message_id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    session_id uuid NOT NULL,
    tenant_id uuid NOT NULL,
    role character varying(20) NOT NULL,
    message_text_encrypted bytea NOT NULL,
    retrieved_chunks jsonb,
    model_used character varying(100),
    "timestamp" timestamp without time zone DEFAULT now(),
    response_sequence integer,
    CONSTRAINT chat_messages_role_check CHECK (((role)::text = ANY ((ARRAY['user'::character varying, 'assistant'::character varying, 'system'::character varying])::text[])))
);


--
-- Name: chat_sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.chat_sessions (
    session_id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    tenant_id uuid NOT NULL,
    user_id uuid NOT NULL,
    session_name_encrypted bytea,
    created_at timestamp without time zone DEFAULT now(),
    last_message_at timestamp without time zone DEFAULT now(),
    is_active boolean DEFAULT true,
    is_deleted boolean DEFAULT false
);


--
-- Name: document_chunks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.document_chunks (
    chunk_id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    document_id uuid NOT NULL,
    tenant_id uuid NOT NULL,
    chunk_index integer NOT NULL,
    chunk_text_encrypted bytea NOT NULL,
    chunk_metadata jsonb,
    embedding public.vector(1024),
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: documents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.documents (
    document_id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    tenant_id uuid NOT NULL,
    user_id uuid NOT NULL,
    document_hash character varying(64) NOT NULL,
    encryption_key_id character varying(255) NOT NULL,
    original_filename_encrypted bytea NOT NULL,
    s3_bucket character varying(255) NOT NULL,
    s3_key_encrypted bytea NOT NULL,
    file_size_bytes bigint NOT NULL,
    total_chunks integer,
    embedding_model character varying(100) DEFAULT 'amazon.titan-embed-text-v2:0'::character varying,
    upload_date timestamp without time zone DEFAULT now(),
    processed_at timestamp without time zone,
    is_deleted boolean DEFAULT false
);


--
-- Name: feedback; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.feedback (
    feedback_id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    tenant_id uuid NOT NULL,
    user_id uuid NOT NULL,
    message_id uuid NOT NULL,
    session_id uuid NOT NULL,
    rating character varying(10),
    comments_encrypted bytea,
    email_sent boolean DEFAULT false,
    email_sent_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now(),
    CONSTRAINT feedback_rating_check CHECK (((rating)::text = ANY ((ARRAY['yes'::character varying, 'no'::character varying])::text[])))
);


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    user_id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    clerk_user_id character varying(255) NOT NULL,
    tenant_id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    email_encrypted bytea,
    created_at timestamp without time zone DEFAULT now(),
    last_active timestamp without time zone DEFAULT now(),
    email text
);


--
-- Name: audit_log audit_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_log
    ADD CONSTRAINT audit_log_pkey PRIMARY KEY (log_id);


--
-- Name: chat_messages chat_messages_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_messages
    ADD CONSTRAINT chat_messages_pkey PRIMARY KEY (message_id);


--
-- Name: chat_sessions chat_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_sessions
    ADD CONSTRAINT chat_sessions_pkey PRIMARY KEY (session_id);


--
-- Name: document_chunks document_chunks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_chunks
    ADD CONSTRAINT document_chunks_pkey PRIMARY KEY (chunk_id);


--
-- Name: documents documents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.documents
    ADD CONSTRAINT documents_pkey PRIMARY KEY (document_id);


--
-- Name: feedback feedback_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.feedback
    ADD CONSTRAINT feedback_pkey PRIMARY KEY (feedback_id);


--
-- Name: users users_clerk_user_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_clerk_user_id_key UNIQUE (clerk_user_id);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (user_id);


--
-- Name: users users_tenant_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_tenant_id_key UNIQUE (tenant_id);


--
-- Name: idx_audit_action; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_action ON public.audit_log USING btree (action);


--
-- Name: idx_audit_tenant; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_tenant ON public.audit_log USING btree (tenant_id, "timestamp");


--
-- Name: idx_chunk_doc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_chunk_doc ON public.document_chunks USING btree (document_id);


--
-- Name: idx_chunk_embedding; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_chunk_embedding ON public.document_chunks USING ivfflat (embedding public.vector_cosine_ops) WITH (lists='100');


--
-- Name: idx_chunk_tenant; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_chunk_tenant ON public.document_chunks USING btree (tenant_id);


--
-- Name: idx_clerk_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_clerk_user ON public.users USING btree (clerk_user_id);


--
-- Name: idx_doc_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_doc_hash ON public.documents USING btree (document_hash);


--
-- Name: idx_feedback_email; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_feedback_email ON public.feedback USING btree (email_sent);


--
-- Name: idx_feedback_tenant; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_feedback_tenant ON public.feedback USING btree (tenant_id);


--
-- Name: idx_msg_session; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_msg_session ON public.chat_messages USING btree (session_id, "timestamp");


--
-- Name: idx_msg_tenant; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_msg_tenant ON public.chat_messages USING btree (tenant_id);


--
-- Name: idx_session_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_session_active ON public.chat_sessions USING btree (user_id, is_active);


--
-- Name: idx_session_tenant; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_session_tenant ON public.chat_sessions USING btree (tenant_id, is_deleted);


--
-- Name: idx_tenant; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tenant ON public.users USING btree (tenant_id);


--
-- Name: idx_tenant_doc_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_tenant_doc_hash ON public.documents USING btree (tenant_id, document_hash);


--
-- Name: idx_tenant_docs; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tenant_docs ON public.documents USING btree (tenant_id, is_deleted);


--
-- Name: ix_users_email; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_users_email ON public.users USING btree (email);


--
-- Name: ux_users_email_encrypted; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ux_users_email_encrypted ON public.users USING btree (email_encrypted);


--
-- Name: chat_messages chat_messages_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_messages
    ADD CONSTRAINT chat_messages_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.chat_sessions(session_id) ON DELETE CASCADE;


--
-- Name: chat_sessions chat_sessions_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_sessions
    ADD CONSTRAINT chat_sessions_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.users(tenant_id) ON DELETE CASCADE;


--
-- Name: chat_sessions chat_sessions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_sessions
    ADD CONSTRAINT chat_sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(user_id) ON DELETE CASCADE;


--
-- Name: document_chunks document_chunks_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_chunks
    ADD CONSTRAINT document_chunks_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.documents(document_id) ON DELETE CASCADE;


--
-- Name: documents documents_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.documents
    ADD CONSTRAINT documents_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.users(tenant_id) ON DELETE CASCADE;


--
-- Name: documents documents_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.documents
    ADD CONSTRAINT documents_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(user_id) ON DELETE CASCADE;


--
-- Name: feedback feedback_message_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.feedback
    ADD CONSTRAINT feedback_message_id_fkey FOREIGN KEY (message_id) REFERENCES public.chat_messages(message_id) ON DELETE CASCADE;


--
-- Name: feedback feedback_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.feedback
    ADD CONSTRAINT feedback_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.chat_sessions(session_id) ON DELETE CASCADE;


--
-- Name: feedback feedback_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.feedback
    ADD CONSTRAINT feedback_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(user_id) ON DELETE CASCADE;


--
-- Name: chat_messages; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.chat_messages ENABLE ROW LEVEL SECURITY;

--
-- Name: chat_sessions; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.chat_sessions ENABLE ROW LEVEL SECURITY;

--
-- Name: document_chunks; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.document_chunks ENABLE ROW LEVEL SECURITY;

--
-- Name: documents; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.documents ENABLE ROW LEVEL SECURITY;

--
-- Name: feedback; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.feedback ENABLE ROW LEVEL SECURITY;

--
-- Name: chat_messages tenant_isolation_policy; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_isolation_policy ON public.chat_messages USING ((tenant_id = (current_setting('app.current_tenant_id'::text, true))::uuid));


--
-- Name: chat_sessions tenant_isolation_policy; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_isolation_policy ON public.chat_sessions USING ((tenant_id = (current_setting('app.current_tenant_id'::text, true))::uuid));


--
-- Name: document_chunks tenant_isolation_policy; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_isolation_policy ON public.document_chunks USING ((tenant_id = (current_setting('app.current_tenant_id'::text, true))::uuid));


--
-- Name: documents tenant_isolation_policy; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_isolation_policy ON public.documents USING ((tenant_id = (current_setting('app.current_tenant_id'::text, true))::uuid));


--
-- Name: feedback tenant_isolation_policy; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_isolation_policy ON public.feedback USING ((tenant_id = (current_setting('app.current_tenant_id'::text, true))::uuid));


--
-- PostgreSQL database dump complete
--

