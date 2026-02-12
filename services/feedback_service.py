"""Feedback collection and email notification service."""

import uuid
import logging
from datetime import datetime
from sqlalchemy.orm import Session
from typing import Optional
from models.database_models import Feedback
from security.encryption import encryption_manager
from security.audit_logger import log_action
from utils.email_sender import send_feedback_email

logger = logging.getLogger(__name__)


class FeedbackService:
    """Service for collecting and processing user feedback."""
    
    def __init__(self, db: Session, tenant_id: uuid.UUID, user_id: uuid.UUID):
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id
    
    def submit_feedback(
        self,
        message_id: uuid.UUID,
        session_id: uuid.UUID,
        rating: str,
        comments: Optional[str] = None,
        user_email: Optional[str] = None
    ) -> Feedback:
        """
        Submit user feedback.
        
        Args:
            message_id: ID of the message being rated
            session_id: Chat session ID
            rating: 'yes' or 'no'
            comments: Optional improvement suggestions
            user_email: Optional user email
            
        Returns:
            Feedback object
        """
        data_key = encryption_manager.get_or_create_dek(str(self.tenant_id))
        
        # Create feedback record
        feedback = Feedback(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            message_id=message_id,
            session_id=session_id,
            rating=rating,
            comments_encrypted=encryption_manager.encrypt_field(
                comments, data_key
            ) if comments else None
        )
        
        self.db.add(feedback)
        self.db.commit()
        self.db.refresh(feedback)
        
        # Send email notification
        try:
            success = send_feedback_email(
                rating=rating,
                comments=comments,
                user_email=user_email,
                session_id=str(session_id)
            )
            
            if success:
                feedback.email_sent = True
                feedback.email_sent_at = datetime.utcnow()
                self.db.commit()
        except Exception as e:
            logger.error(f"Failed to send feedback email: {str(e)}")
        
        # Log action
        log_action(
            db=self.db,
            action="feedback_submitted",
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            resource_type="feedback",
            resource_id=feedback.feedback_id
        )
        
        logger.info(f"Feedback submitted: {rating} for message {message_id}")
        return feedback
    
    def has_feedback(self, message_id: uuid.UUID) -> bool:
        """Check if feedback already exists for a message."""
        exists = self.db.query(Feedback).filter(
            Feedback.message_id == message_id,
            Feedback.tenant_id == self.tenant_id
        ).first()
        
        return exists is not None
