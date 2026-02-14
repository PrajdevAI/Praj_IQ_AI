"""SQLAlchemy database models."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Column,
    String,
    Integer,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    CheckConstraint,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID, BYTEA, JSONB, INET
from sqlalchemy.orm import relationship
from sqlalchemy import LargeBinary
from pgvector.sqlalchemy import Vector

from config.database import Base


class User(Base):
    """User model - authentication handled by Clerk."""

    __tablename__ = "users"

    user_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    clerk_user_id = Column(String(255), unique=True, nullable=False, index=True)

    email_encrypted = Column(LargeBinary, unique=True, nullable=False, index=True)

    tenant_id = Column(UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4, index=True)

    email = Column(String(255), unique=True, nullable=True, index=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    last_active = Column(DateTime, default=datetime.utcnow)

    # Relationships
    documents = relationship(
        "Document",
        back_populates="user",
        cascade="all, delete-orphan",
        foreign_keys="Document.user_id",
    )
    chat_sessions = relationship(
        "ChatSession",
        back_populates="user",
        cascade="all, delete-orphan",
        foreign_keys="ChatSession.user_id",
    )
    feedback = relationship("Feedback", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User(clerk_user_id={self.clerk_user_id}, tenant_id={self.tenant_id})>"


class Document(Base):
    """Document model for uploaded files."""

    __tablename__ = "documents"

    document_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("users.tenant_id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)

    # Security fields
    document_hash = Column(String(64), nullable=False, index=True)
    encryption_key_id = Column(String(255), nullable=False)

    # Document metadata
    original_filename_encrypted = Column(BYTEA, nullable=False)
    s3_bucket = Column(String(255), nullable=False)
    s3_key_encrypted = Column(BYTEA, nullable=False)
    file_size_bytes = Column(BigInteger, nullable=False)

    # Processing metadata
    total_chunks = Column(Integer, nullable=True)
    embedding_model = Column(String(100), default="amazon.titan-embed-text-v2:0")

    upload_date = Column(DateTime, default=datetime.utcnow)
    processed_at = Column(DateTime, nullable=True)
    is_deleted = Column(Boolean, default=False, index=True)

    # Relationships
    user = relationship("User", back_populates="documents", foreign_keys=[user_id])
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")

    # Indexes
    __table_args__ = (
        Index("idx_tenant_docs", "tenant_id", "is_deleted"),
        Index("idx_doc_hash", "document_hash"),
        Index("idx_tenant_doc_hash", "tenant_id", "document_hash", unique=True),
    )

    def __repr__(self):
        return f"<Document(document_id={self.document_id}, tenant_id={self.tenant_id})>"


class DocumentChunk(Base):
    """Document chunks with vector embeddings."""

    __tablename__ = "document_chunks"

    chunk_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.document_id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    chunk_index = Column(Integer, nullable=False)
    chunk_text_encrypted = Column(BYTEA, nullable=False)
    chunk_metadata = Column(JSONB, nullable=True)

    # Vector embedding (1024 dimensions for Titan v2)
    embedding = Column(Vector(1024), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    document = relationship("Document", back_populates="chunks")

    # Indexes
    __table_args__ = (
        Index("idx_chunk_doc", "document_id"),
        Index("idx_chunk_tenant", "tenant_id"),
        Index(
            "idx_chunk_embedding",
            "embedding",
            postgresql_using="ivfflat",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    def __repr__(self):
        return f"<DocumentChunk(chunk_id={self.chunk_id}, document_id={self.document_id})>"


class ChatSession(Base):
    """Chat session model."""

    __tablename__ = "chat_sessions"

    session_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("users.tenant_id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True)

    session_name_encrypted = Column(BYTEA, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_message_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True, index=True)
    is_deleted = Column(Boolean, default=False, index=True)

    # Relationships
    user = relationship("User", back_populates="chat_sessions", foreign_keys=[user_id])
    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan")
    feedback = relationship("Feedback", back_populates="session", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_session_tenant", "tenant_id", "is_deleted"),
        Index("idx_session_active", "user_id", "is_active"),
    )

    def __repr__(self):
        return f"<ChatSession(session_id={self.session_id}, tenant_id={self.tenant_id})>"


class ChatMessage(Base):
    """Chat message model."""

    __tablename__ = "chat_messages"

    message_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("chat_sessions.session_id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    role = Column(String(20), nullable=False)
    message_text_encrypted = Column(BYTEA, nullable=False)

    retrieved_chunks = Column(JSONB, nullable=True)
    model_used = Column(String(100), nullable=True)

    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    response_sequence = Column(Integer, nullable=True)

    session = relationship("ChatSession", back_populates="messages")
    feedback = relationship("Feedback", back_populates="message", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant', 'system')", name="check_role"),
        Index("idx_msg_session", "session_id", "timestamp"),
        Index("idx_msg_tenant", "tenant_id"),
    )

    def __repr__(self):
        return f"<ChatMessage(message_id={self.message_id}, role={self.role})>"


class Feedback(Base):
    """Feedback model."""

    __tablename__ = "feedback"

    feedback_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    message_id = Column(UUID(as_uuid=True), ForeignKey("chat_messages.message_id", ondelete="CASCADE"), nullable=False)
    session_id = Column(UUID(as_uuid=True), ForeignKey("chat_sessions.session_id", ondelete="CASCADE"), nullable=False)

    rating = Column(String(10), nullable=True)
    comments_encrypted = Column(BYTEA, nullable=True)

    email_sent = Column(Boolean, default=False, index=True)
    email_sent_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="feedback")
    message = relationship("ChatMessage", back_populates="feedback")
    session = relationship("ChatSession", back_populates="feedback")

    __table_args__ = (
        CheckConstraint("rating IN ('yes', 'no')", name="check_rating"),
        Index("idx_feedback_tenant", "tenant_id"),
        Index("idx_feedback_email", "email_sent"),
    )

    def __repr__(self):
        return f"<Feedback(feedback_id={self.feedback_id}, rating={self.rating})>"


class AuditLog(Base):
    """Audit log model for security monitoring."""

    __tablename__ = "audit_log"

    log_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    user_id = Column(UUID(as_uuid=True), nullable=True)

    action = Column(String(100), nullable=False, index=True)
    resource_type = Column(String(50), nullable=True)
    resource_id = Column(UUID(as_uuid=True), nullable=True)

    ip_address = Column(INET, nullable=True)
    user_agent = Column(Text, nullable=True)

    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("idx_audit_tenant", "tenant_id", "timestamp"),
        Index("idx_audit_action", "action"),
    )

    def __repr__(self):
        return f"<AuditLog(log_id={self.log_id}, action={self.action})>"


class UserProfile(Base):
    """Stores optional profile details collected once after verification."""

    __tablename__ = "user_profiles"

    profile_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, unique=True, index=True)

    first_name = Column(String(120), nullable=False)
    last_name = Column(String(120), nullable=False)
    company_name = Column(String(255), nullable=False, default="")
    company_email = Column(String(255), nullable=False)
    phone_number = Column(String(50), nullable=True)

    # Tracks when user completed first-time summary feedback (NULL = not done yet)
    summary_feedback_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<UserProfile(user_id={self.user_id}, company_email={self.company_email})>"


class TenantStorage(Base):
    """
    Tracks per-tenant storage usage in S3.
    
    Updated on every document upload and delete.
    Designed for future threshold-based alerts and billing.
    """

    __tablename__ = "tenant_storage"

    storage_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.tenant_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    # Current usage
    total_bytes = Column(BigInteger, nullable=False, default=0)
    document_count = Column(Integer, nullable=False, default=0)

    # High-water mark for billing/analytics
    peak_bytes = Column(BigInteger, nullable=False, default=0)

    # Alert tracking
    last_alert_sent_at = Column(DateTime, nullable=True)
    alert_threshold_bytes = Column(
        BigInteger, nullable=False, default=53_687_091_200  # 50 GB
    )

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_tenant_storage_tenant", "tenant_id"),
    )

    @property
    def total_mb(self) -> float:
        return round(self.total_bytes / (1024 * 1024), 2)

    @property
    def total_gb(self) -> float:
        return round(self.total_bytes / (1024 * 1024 * 1024), 4)

    @property
    def usage_percent(self) -> float:
        """Percentage of alert threshold used."""
        if self.alert_threshold_bytes == 0:
            return 0.0
        return round((self.total_bytes / self.alert_threshold_bytes) * 100, 2)

    def __repr__(self):
        return (
            f"<TenantStorage(tenant_id={self.tenant_id}, "
            f"total={self.total_mb}MB, docs={self.document_count})>"
        )