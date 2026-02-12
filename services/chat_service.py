"""
Chat session and message management service.
"""

import uuid
import json
import logging
from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session
from sqlalchemy import func

from models.database_models import ChatSession, ChatMessage
from security.encryption import encryption_manager
from security.audit_logger import log_action
from config.database import ensure_tenant_context, ensure_rls_for_query

logger = logging.getLogger(__name__)


class ChatService:
    """Service for managing chat sessions and messages."""

    def __init__(self, db: Session, tenant_id: uuid.UUID, user_id: uuid.UUID):
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id

    # =====================================================
    # SESSION MANAGEMENT
    # =====================================================

    def create_session(self) -> ChatSession:
        """
        Create new chat session.
        Avoids SQLAlchemy refresh() issues with RLS + connection pooling.
        """

        try:
            session = ChatSession(
                tenant_id=self.tenant_id,
                user_id=self.user_id,
            )

            self.db.add(session)
            self.db.flush()  # generate session_id

            new_session_id = session.session_id

            ensure_tenant_context(self.db)
            self.db.commit()

            # Re-query safely under RLS
            ensure_rls_for_query(self.db)

            session = (
                self.db.query(ChatSession)
                .filter(
                    ChatSession.session_id == new_session_id,
                    ChatSession.tenant_id == self.tenant_id,
                    ChatSession.user_id == self.user_id,
                    ChatSession.is_deleted == False,
                )
                .first()
            )

            if not session:
                raise Exception("Session creation failed under RLS.")

            log_action(
                db=self.db,
                action="chat_session_created",
                tenant_id=self.tenant_id,
                user_id=self.user_id,
                resource_type="chat_session",
                resource_id=session.session_id,
            )

            return session

        except Exception as e:
            self.db.rollback()
            logger.error("Failed to create session: %s", e)
            raise

    def get_active_session(self) -> ChatSession:
        """Get active session or create one."""

        ensure_rls_for_query(self.db)

        session = (
            self.db.query(ChatSession)
            .filter(
                ChatSession.tenant_id == self.tenant_id,
                ChatSession.user_id == self.user_id,
                ChatSession.is_active == True,
                ChatSession.is_deleted == False,
            )
            .order_by(ChatSession.created_at.desc())
            .first()
        )

        if not session:
            session = self.create_session()

        return session

    def get_session_by_id(self, session_id: uuid.UUID) -> Optional[ChatSession]:
        """Fetch session safely under RLS."""

        ensure_rls_for_query(self.db)

        return (
            self.db.query(ChatSession)
            .filter(
                ChatSession.session_id == session_id,
                ChatSession.tenant_id == self.tenant_id,
                ChatSession.user_id == self.user_id,
                ChatSession.is_deleted == False,
            )
            .first()
        )

    def list_sessions(self, include_deleted: bool = False) -> List[dict]:
        """List all sessions for this user."""

        ensure_rls_for_query(self.db)

        query = (
            self.db.query(ChatSession)
            .filter(
                ChatSession.tenant_id == self.tenant_id,
                ChatSession.user_id == self.user_id,
            )
        )

        if not include_deleted:
            query = query.filter(ChatSession.is_deleted == False)

        sessions = query.order_by(ChatSession.last_message_at.desc()).all()

        data_key = encryption_manager.get_or_create_dek(str(self.tenant_id))

        result = []

        for s in sessions:
            try:
                title = "New Chat"
                if s.session_name_encrypted:
                    title = encryption_manager.decrypt_field(
                        s.session_name_encrypted, data_key
                    )

                result.append(
                    {
                        "session_id": str(s.session_id),
                        "title": title,
                        "created_at": s.created_at,
                        "last_message_at": s.last_message_at,
                        "is_active": s.is_active,
                        "is_deleted": s.is_deleted,
                    }
                )
            except Exception as e:
                logger.error("Failed to decrypt session title: %s", e)

        return result

    def update_session_title(self, session_id: uuid.UUID, title: str) -> None:
        """Update a session's title."""
        try:
            ensure_rls_for_query(self.db)
            
            session = self.get_session_by_id(session_id)
            if session:
                data_key = encryption_manager.get_or_create_dek(str(self.tenant_id))
                session.session_name_encrypted = encryption_manager.encrypt_field(title, data_key)
                
                ensure_tenant_context(self.db)
                self.db.commit()
                
                log_action(
                    db=self.db,
                    action="chat_session_renamed",
                    tenant_id=self.tenant_id,
                    user_id=self.user_id,
                    resource_type="chat_session",
                    resource_id=session_id,
                    details={"title": title[:100]},  # Log truncated title for privacy
                )
                
                logger.info("Updated title for session %s", session_id)
            else:
                logger.warning("Session %s not found for title update", session_id)
                
        except Exception as e:
            self.db.rollback()
            logger.error("Failed to update session title %s: %s", session_id, e)
            raise

    def auto_title_session(self, session_id: uuid.UUID) -> None:
        """
        Automatically generate a title for a session based on its first user message.
        Called after the first user message is sent.
        """
        try:
            # Get messages for this session
            messages = self.get_messages(session_id)
            
            # Filter user messages
            user_messages = [msg for msg in messages if msg["role"] == "user"]
            
            if user_messages:
                # Take first user message and truncate for title
                first_message = user_messages[0]["text"].strip()
                
                # Clean up the message: remove extra whitespace, newlines
                first_message = ' '.join(first_message.split())
                
                # Generate title (max 50 chars, with ellipsis if longer)
                title = first_message[:50]
                if len(first_message) > 50:
                    title += "..."
                
                # Don't use empty or whitespace-only titles
                if title.strip():
                    self.update_session_title(session_id, title)
                    logger.info("Auto-titled session %s as: %s", session_id, title)
                else:
                    logger.warning("No valid content to auto-title session %s", session_id)
            else:
                logger.warning("No user messages found to auto-title session %s", session_id)
                
        except Exception as e:
            logger.error("Failed to auto-title session %s: %s", session_id, e)
            # Don't raise - auto-titling should not break the chat flow

    # =====================================================
    # MESSAGE MANAGEMENT
    # =====================================================

    def get_messages(self, session_id: uuid.UUID) -> List[dict]:
        """Fetch all messages for a session."""

        ensure_rls_for_query(self.db)

        messages = (
            self.db.query(ChatMessage)
            .filter(
                ChatMessage.session_id == session_id,
                ChatMessage.tenant_id == self.tenant_id,
            )
            .order_by(ChatMessage.timestamp.asc())
            .all()
        )

        data_key = encryption_manager.get_or_create_dek(str(self.tenant_id))

        result = []

        for msg in messages:
            try:
                result.append(
                    {
                        "message_id": str(msg.message_id),
                        "role": msg.role,
                        "text": encryption_manager.decrypt_field(
                            msg.message_text_encrypted, data_key
                        ),
                        "timestamp": msg.timestamp,
                        "metadata": json.loads(msg.retrieved_chunks)
                        if msg.retrieved_chunks
                        else None,
                    }
                )
            except Exception as e:
                logger.error("Failed to decrypt message %s: %s", msg.message_id, e)

        return result

    def count_assistant_responses(self, session_id: uuid.UUID) -> int:
        """
        Counts how many assistant messages exist for a given session.
        UI uses this to trigger feedback after N assistant responses.
        """
        ensure_rls_for_query(self.db)

        count = (
            self.db.query(func.count(ChatMessage.message_id))
            .filter(
                ChatMessage.session_id == session_id,
                ChatMessage.tenant_id == self.tenant_id,
                ChatMessage.role == "assistant",
            )
            .scalar()
        )

        return int(count or 0)

    # Backward compatibility for UI
    def get_chat_history(self, session_id: uuid.UUID) -> List[dict]:
        """Alias for UI compatibility."""
        return self.get_messages(session_id)

    def add_message(
        self,
        session_id: uuid.UUID = None,
        role: str = "",
        content: str = "",
        metadata_json=None,
        conversation_id: uuid.UUID = None,  # UI passes this
    ) -> dict:
        """
        Add message to a session.

        Backward compatible:
        - UI may call add_message(conversation_id=...)
        - New code may call add_message(session_id=...)
        """

        if session_id is None:
            session_id = conversation_id

        if session_id is None:
            raise ValueError("add_message requires session_id or conversation_id")

        try:
            data_key = encryption_manager.get_or_create_dek(str(self.tenant_id))

            message = ChatMessage(
                session_id=session_id,
                tenant_id=self.tenant_id,
                role=role,
                message_text_encrypted=encryption_manager.encrypt_field(
                    content, data_key
                ),
                retrieved_chunks=json.dumps(metadata_json) if metadata_json else None,
            )

            self.db.add(message)

            # update last_message_at
            session = (
                self.db.query(ChatSession)
                .filter(ChatSession.session_id == session_id)
                .first()
            )

            if session:
                session.last_message_at = datetime.utcnow()

            ensure_tenant_context(self.db)
            self.db.commit()

            # Auto-title the session if this is the first user message
            if role == "user":
                # Check if this is the first user message
                user_message_count = (
                    self.db.query(func.count(ChatMessage.message_id))
                    .filter(
                        ChatMessage.session_id == session_id,
                        ChatMessage.tenant_id == self.tenant_id,
                        ChatMessage.role == "user",
                    )
                    .scalar()
                )
                
                # If this is the first user message (count == 1 after adding this one)
                if user_message_count == 1:
                    # Trigger auto-titling asynchronously or in background
                    # Since we're in a transaction, we might want to do this after commit
                    # For simplicity, we'll call it directly but wrap in try/except
                    try:
                        self.auto_title_session(session_id)
                    except Exception as e:
                        logger.error("Failed to auto-title after first message: %s", e)

            return {
                "message_id": str(message.message_id),
                "timestamp": message.timestamp,
            }

        except Exception as e:
            self.db.rollback()
            logger.error("Failed to add message: %s", e)
            raise