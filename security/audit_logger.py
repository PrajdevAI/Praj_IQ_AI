"""Security audit logging utilities."""

import logging
from datetime import datetime
from functools import wraps
from typing import Optional
import uuid
from sqlalchemy.orm import Session
from models.database_models import AuditLog

logger = logging.getLogger(__name__)


def log_action(
    db: Session,
    action: str,
    tenant_id: Optional[uuid.UUID] = None,
    user_id: Optional[uuid.UUID] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[uuid.UUID] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None
):
    """
    Log a security-relevant action to the audit log.
    
    Args:
        db: Database session
        action: Action performed (e.g., 'document_upload', 'chat_delete')
        tenant_id: Tenant identifier
        user_id: User identifier
        resource_type: Type of resource (e.g., 'document', 'chat_session')
        resource_id: Resource identifier
        ip_address: Client IP address
        user_agent: Client user agent
    """
    try:
        audit_entry = AuditLog(
            tenant_id=tenant_id,
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            ip_address=ip_address,
            user_agent=user_agent
        )
        
        db.add(audit_entry)
        db.commit()
        
        logger.info(
            f"Audit log: {action} by tenant={tenant_id} user={user_id} "
            f"resource={resource_type}:{resource_id}"
        )
        
    except Exception as e:
        logger.error(f"Failed to write audit log: {str(e)}")
        # Don't raise - audit logging shouldn't break functionality


def audit_log(action: str, resource_type: Optional[str] = None):
    """
    Decorator to automatically log function calls.
    
    Usage:
        @audit_log(action="document_upload", resource_type="document")
        def upload_document(db, tenant_id, user_id, file):
            # implementation
            pass
    
    Args:
        action: The action being performed
        resource_type: The type of resource being acted upon
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Execute the function
            result = func(*args, **kwargs)
            
            # Try to extract common parameters
            db = kwargs.get('db') or (args[0] if len(args) > 0 else None)
            tenant_id = kwargs.get('tenant_id') or (args[1] if len(args) > 1 else None)
            user_id = kwargs.get('user_id') or (args[2] if len(args) > 2 else None)
            
            # Log the action
            if db and isinstance(db, Session):
                resource_id = None
                
                # Try to extract resource_id from result
                if hasattr(result, 'document_id'):
                    resource_id = result.document_id
                elif hasattr(result, 'session_id'):
                    resource_id = result.session_id
                elif hasattr(result, 'message_id'):
                    resource_id = result.message_id
                
                log_action(
                    db=db,
                    action=action,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    resource_type=resource_type,
                    resource_id=resource_id
                )
            
            return result
        
        return wrapper
    return decorator


class AuditLogger:
    """Context manager for audit logging."""
    
    def __init__(
        self,
        db: Session,
        action: str,
        tenant_id: Optional[uuid.UUID] = None,
        user_id: Optional[uuid.UUID] = None
    ):
        self.db = db
        self.action = action
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.start_time = None
    
    def __enter__(self):
        self.start_time = datetime.utcnow()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        # Log completion or failure
        if exc_type is not None:
            action = f"{self.action}_failed"
        else:
            action = f"{self.action}_completed"
        
        log_action(
            db=self.db,
            action=action,
            tenant_id=self.tenant_id,
            user_id=self.user_id
        )
