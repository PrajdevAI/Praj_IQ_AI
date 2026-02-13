"""Document deletion service - removes from S3, vector store, and database."""

import uuid
import logging
from typing import List
from sqlalchemy.orm import Session
from sqlalchemy import text

from models.database_models import Document, DocumentChunk
from utils.s3_client import S3Client
from security.encryption import encryption_manager
from config.settings import settings
from config.database import ensure_tenant_context
from security.audit_logger import log_action
from services.storage_service import StorageService

logger = logging.getLogger(__name__)


class DeleteService:
    """Service for comprehensive document deletion across S3, vector store, and database."""
    
    def __init__(self, db: Session, tenant_id: uuid.UUID):
        self.db = db
        self.tenant_id = tenant_id
        self.s3_client = S3Client()
    
    def delete_document(
        self,
        doc_id: uuid.UUID,
        user_id: uuid.UUID,
        hard_delete: bool = False
    ) -> bool:
        """
        Fully delete a document:
        1) Remove from S3
        2) Delete from vector store (via document_chunks soft-delete)
        3) Soft-delete or hard-delete document metadata
        4) Update tenant storage tracking
        """
        try:
            # Verify document exists and user has permission
            doc = self.db.query(Document).filter(
                Document.document_id == doc_id,
                Document.tenant_id == self.tenant_id,
                Document.user_id == user_id,
                Document.is_deleted == False
            ).first()
            
            if not doc:
                logger.warning(f"Document {doc_id} not found or already deleted")
                return False
            
            logger.info(f"Starting deletion process for document {doc_id} (tenant: {self.tenant_id})")
            
            # Capture file size before deletion for storage tracking
            file_size_bytes = doc.file_size_bytes or 0
            
            # Step 1: Get S3 key for deletion
            data_key = encryption_manager.get_or_create_dek(str(self.tenant_id))
            try:
                s3_key_encrypted = doc.s3_key_encrypted
                s3_key = encryption_manager.decrypt_field(s3_key_encrypted, data_key)
                logger.info(f"S3 key decrypted: {s3_key}")
            except Exception as e:
                logger.warning(f"Could not decrypt S3 key for {doc_id}: {str(e)}")
                s3_key = None
            
            # Step 2: Delete from S3
            if s3_key:
                try:
                    self.s3_client.delete_file(s3_key)
                    logger.info(f"✅ Deleted from S3: {s3_key}")
                except Exception as e:
                    logger.error(f"❌ S3 deletion failed: {str(e)}")
                    return False
            
            # Step 3: Delete chunks from DB
            deleted_chunk_count = self._delete_chunks(doc_id)
            logger.info(f"✅ Deleted {deleted_chunk_count} chunks from database")
            
            # Step 4: Mark document as deleted
            ensure_tenant_context(self.db)
            
            if hard_delete:
                self.db.delete(doc)
                logger.info(f"✅ Hard-deleted document metadata: {doc_id}")
            else:
                doc.is_deleted = True
                logger.info(f"✅ Soft-deleted document metadata: {doc_id}")
            
            self.db.commit()
            
            # Step 5: Update storage tracking
            try:
                storage_svc = StorageService(self.db, self.tenant_id)
                storage_svc.record_delete(file_size_bytes)
                self.db.commit()
            except Exception as storage_err:
                logger.warning(f"Storage tracking update failed (non-blocking): {storage_err}")
            
            # Log audit
            log_action(
                db=self.db,
                action="document_delete",
                tenant_id=self.tenant_id,
                user_id=user_id,
                resource_type="document",
                resource_id=doc_id
            )
            
            logger.info(f"✅ Document {doc_id} fully deleted (S3 + chunks + metadata)")
            return True
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"❌ Document deletion failed: {str(e)}", exc_info=True)
            return False
    
    def _delete_chunks(self, doc_id: uuid.UUID) -> int:
        """Delete all chunks for a document."""
        try:
            count = self.db.query(DocumentChunk).filter(
                DocumentChunk.document_id == doc_id,
                DocumentChunk.tenant_id == self.tenant_id
            ).count()
            
            if count == 0:
                logger.info(f"No chunks found for document {doc_id}")
                return 0
            
            deleted = self.db.query(DocumentChunk).filter(
                DocumentChunk.document_id == doc_id,
                DocumentChunk.tenant_id == self.tenant_id
            ).delete()
            
            self.db.commit()
            
            logger.info(f"Deleted {deleted} chunks for document {doc_id}")
            return deleted
            
        except Exception as e:
            logger.error(f"Error deleting chunks: {str(e)}", exc_info=True)
            self.db.rollback()
            return 0
    
    def get_document_deletion_info(self, doc_id: uuid.UUID, user_id: uuid.UUID) -> dict:
        """Get deletion info for logging/audit purposes."""
        doc = self.db.query(Document).filter(
            Document.document_id == doc_id,
            Document.tenant_id == self.tenant_id,
            Document.user_id == user_id
        ).first()
        
        if not doc:
            return {}
        
        chunk_count = self.db.query(DocumentChunk).filter(
            DocumentChunk.document_id == doc_id
        ).count()
        
        return {
            "document_id": str(doc_id),
            "filename": doc.original_filename_encrypted.decode('utf-8') if isinstance(doc.original_filename_encrypted, bytes) else doc.original_filename_encrypted,
            "s3_bucket": doc.s3_bucket,
            "chunk_count": chunk_count,
            "size_bytes": doc.file_size_bytes
        }
