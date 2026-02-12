"""Pydantic schemas for data validation - Python 3.13 compatible."""

from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List
from datetime import datetime
import uuid


class DocumentUploadRequest(BaseModel):
    """Schema for document upload request."""
    filename: str
    file_size_bytes: int
    
    model_config = ConfigDict(from_attributes=True)


class DocumentResponse(BaseModel):
    """Schema for document response."""
    document_id: uuid.UUID
    filename: str
    upload_date: datetime
    total_chunks: Optional[int] = None
    processed: bool
    
    model_config = ConfigDict(from_attributes=True)


class ChatMessageRequest(BaseModel):
    """Schema for chat message request."""
    message: str
    session_id: Optional[uuid.UUID] = None
    
    model_config = ConfigDict(from_attributes=True)


class ChatMessageResponse(BaseModel):
    """Schema for chat message response."""
    message_id: uuid.UUID
    role: str
    text: str
    timestamp: datetime
    
    model_config = ConfigDict(from_attributes=True)


class FeedbackRequest(BaseModel):
    """Schema for feedback submission."""
    message_id: uuid.UUID
    session_id: uuid.UUID
    rating: str  # 'yes' or 'no'
    comments: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)


class FeedbackResponse(BaseModel):
    """Schema for feedback response."""
    feedback_id: uuid.UUID
    rating: str
    email_sent: bool
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)
