"""Document management service."""

import hashlib
import uuid
import logging
from datetime import datetime
from sqlalchemy.orm import Session
from typing import Optional
from models.database_models import Document, DocumentChunk
from security.encryption import encryption_manager
from security.audit_logger import log_action
from utils.pdf_parser import extract_text_from_pdf, validate_pdf
from utils.chunking import chunk_text
from utils.s3_client import S3Client
from services.embedding_service import generate_embeddings
from config.settings import settings

logger = logging.getLogger(__name__)


class DocumentService:
    """Service for managing document uploads and processing."""
    
    def __init__(self, db: Session, tenant_id: uuid.UUID):
        """
        Initialize document service.
        
        Args:
            db: Database session
            tenant_id: Tenant identifier
        """
        self.db = db
        self.tenant_id = tenant_id
        self.s3_client = S3Client()
    
    def calculate_hash(self, file_bytes: bytes) -> str:
        """Calculate SHA-256 hash of file."""
        return hashlib.sha256(file_bytes).hexdigest()
    
    def check_duplicate(self, doc_hash: str) -> bool:
        """Check if document already exists for this tenant."""
        exists = self.db.query(Document).filter(
            Document.tenant_id == self.tenant_id,
            Document.document_hash == doc_hash,
            Document.is_deleted == False
        ).first()
        
        return exists is not None
    
    def upload_document(
        self,
        file_bytes: bytes,
        filename: str,
        user_id: uuid.UUID
    ) -> Document:
        """
        Upload and process PDF document.
        
        Args:
            file_bytes: PDF file bytes
            filename: Original filename
            user_id: User ID
            
        Returns:
            Document object
            
        Raises:
            ValueError: For validation errors or duplicates
            RuntimeError: For S3 or processing errors
        """
        try:
            # Validate PDF
            if not validate_pdf(file_bytes):
                raise ValueError("Invalid PDF file")
            
            # Check file size
            file_size_mb = len(file_bytes) / (1024 * 1024)
            if file_size_mb > settings.MAX_FILE_SIZE_MB:
                raise ValueError(f"File too large: {file_size_mb:.2f}MB (max: {settings.MAX_FILE_SIZE_MB}MB)")
            
            # Calculate hash
            doc_hash = self.calculate_hash(file_bytes)
            
            # Check for duplicates BEFORE any database operations
            if self.check_duplicate(doc_hash):
                raise ValueError("Document already uploaded for this tenant")
            
            # Clean up any soft-deleted records with this hash to avoid constraint violations
            # (UNIQUE constraint includes soft-deleted rows)
            try:
                old_deleted = self.db.query(Document).filter(
                    Document.tenant_id == self.tenant_id,
                    Document.document_hash == doc_hash,
                    Document.is_deleted == True
                ).all()
                
                for old_doc in old_deleted:
                    self.db.delete(old_doc)
                    logger.info(f"Hard-deleted old soft-deleted document: {old_doc.document_id}")
                
                self.db.commit()
            except Exception as e:
                logger.warning(f"Could not clean up old deleted records: {str(e)}")
                self.db.rollback()
            
            # Get DEK for this tenant
            data_key = encryption_manager.get_or_create_dek(str(self.tenant_id))
            
            # Upload to S3
            s3_key = f"documents/{self.tenant_id}/{uuid.uuid4()}/{filename}"
            success = self.s3_client.upload_file(
                file_bytes=file_bytes,
                s3_key=s3_key,
                metadata={
                    'tenant_id': str(self.tenant_id),
                    'user_id': str(user_id),
                    'original_filename': filename
                }
            )
            
            if not success:
                raise RuntimeError("Failed to upload file to S3")
            
            # Create document record
            document = Document(
                tenant_id=self.tenant_id,
                user_id=user_id,
                document_hash=doc_hash,
                encryption_key_id=settings.KMS_KEY_ID,
                original_filename_encrypted=filename.encode('utf-8'),  # Plaintext for display (S3 key still encrypted)
                s3_bucket=settings.S3_BUCKET_NAME,
                s3_key_encrypted=encryption_manager.encrypt_field(s3_key, data_key),
                file_size_bytes=len(file_bytes)
            )
            
            self.db.add(document)
            
            # Re-apply RLS context before commit (handles connection pool reuse)
            from config.database import ensure_tenant_context
            ensure_tenant_context(self.db)
            
            self.db.commit()
            self.db.refresh(document)
            
            # Log action
            log_action(
                db=self.db,
                action="document_upload",
                tenant_id=self.tenant_id,
                user_id=user_id,
                resource_type="document",
                resource_id=document.document_id
            )
            
            # Process document
            self._process_document(document, file_bytes, data_key)
            
            logger.info(f"Document uploaded: {document.document_id}")
            return document
            
        except (ValueError, RuntimeError):
            # These are expected validation/user errors, re-raise as-is
            self.db.rollback()
            raise
        except Exception as e:
            # Unexpected errors: rollback session and provide context
            self.db.rollback()
            logger.error(f"Unexpected upload error: {type(e).__name__}: {str(e)}", exc_info=True)
            raise RuntimeError(f"Upload failed: {type(e).__name__}: {str(e)}")
    
    def _process_document(
        self,
        document: Document,
        file_bytes: bytes,
        data_key: bytes
    ):
        """Process document: extract text, chunk, generate embeddings."""
        try:
            # Extract text
            text = extract_text_from_pdf(file_bytes)
            
            if not text.strip():
                raise ValueError("No text extracted from PDF")
            
            # Chunk text
            chunks = chunk_text(text, chunk_size=512, overlap=50)
            
            # Generate embeddings
            embeddings = generate_embeddings(chunks)
            
            # Store chunks with embeddings
            for idx, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                chunk_record = DocumentChunk(
                    document_id=document.document_id,
                    tenant_id=self.tenant_id,
                    chunk_index=idx,
                    chunk_text_encrypted=encryption_manager.encrypt_field(
                        chunk, data_key
                    ),
                    embedding=embedding,
                    chunk_metadata={"chunk_index": idx, "total_chunks": len(chunks)}
                )
                self.db.add(chunk_record)
            
            # Update document status
            document.total_chunks = len(chunks)
            document.processed_at = datetime.utcnow()
            
            # Re-apply RLS context before commit
            from config.database import ensure_tenant_context
            ensure_tenant_context(self.db)
            
            self.db.commit()
            
            logger.info(f"Document processed: {len(chunks)} chunks created")
            
        except Exception as e:
            logger.error(f"Document processing failed: {str(e)}")
            # Mark document as failed but don't delete
            raise
    
    def list_documents(self, user_id: uuid.UUID) -> list:
        """List all documents for this tenant."""
        try:
            from config.database import ensure_rls_for_query
            from sqlalchemy import text
            
            # Ensure RLS context is set for this query
            ensure_rls_for_query(self.db)
            logger.info(f"Querying documents: tenant_id={self.tenant_id}, user_id={user_id}")
            
            # DEBUG: Check if RLS is enabled
            if getattr(settings, 'ENABLE_RLS', True):
                logger.info("RLS is ENABLED - row filtering should apply")
            else:
                logger.warning("RLS is DISABLED - all rows may be visible")
            
            # DEBUG: Check current tenant context
            current_context = self.db.execute(
                text("SELECT current_setting('app.current_tenant_id', true)")
            ).scalar()
            logger.info(f"DEBUG: Current RLS context: {current_context}")
            
            # DEBUG: Raw count with explicit tenant/user filter
            raw_count = self.db.execute(
                text(f"SELECT COUNT(*) FROM documents WHERE tenant_id = '{self.tenant_id}' AND user_id = '{user_id}' AND is_deleted = false")
            ).scalar()
            logger.info(f"DEBUG: Raw SQL count: {raw_count} documents for this user")
            
            # Now do the ORM query 
            documents = self.db.query(Document).filter(
                Document.tenant_id == self.tenant_id,
                Document.user_id == user_id,
                Document.is_deleted == False
            ).order_by(Document.upload_date.desc()).all()
            
            logger.info(f"ORM query returned {len(documents)} documents")
            
            # Diagnose chunk encryption status if documents exist
            if documents:
                self.diagnose_chunks()
            
            result = []
            for doc in documents:
                try:
                    # Filename: Try UTF-8 decode first (new format), then decrypt (old format)
                    filename = None
                    if isinstance(doc.original_filename_encrypted, bytes):
                        # Try UTF-8 decode first (new plaintext format)
                        try:
                            filename = doc.original_filename_encrypted.decode('utf-8')
                            logger.debug(f"Decoded filename as plaintext: {filename}")
                        except UnicodeDecodeError:
                            # Old format: encrypted binary. Try to decrypt
                            try:
                                from security.encryption import encryption_manager
                                data_key = encryption_manager.get_or_create_dek(str(self.tenant_id))
                                filename = encryption_manager.decrypt_field(doc.original_filename_encrypted, data_key)
                                logger.debug(f"Decrypted filename: {filename}")
                            except Exception as decrypt_err:
                                # Both decode and decrypt failed, use document ID as fallback
                                logger.warning(f"Could not decode/decrypt filename for {doc.document_id}: {str(decrypt_err)}. Using document_id as fallback.")
                                filename = f"Document_{doc.document_id}"
                    else:
                        # Already a string
                        filename = doc.original_filename_encrypted
                    
                    result.append({
                        'document_id': doc.document_id,
                        'filename': filename,
                        'upload_date': doc.upload_date,
                        'total_chunks': doc.total_chunks,
                        'processed': doc.processed_at is not None
                    })
                    logger.debug(f"Added document: {filename}")
                except Exception as e:
                    logger.error(f"Failed to process doc {doc.document_id}: {str(e)}")
                    continue
            
            logger.info(f"Returning {len(result)} documents to UI")
            return result
            
        except Exception as e:
            logger.error(f"Error listing documents: {str(e)}", exc_info=True)
            raise
    
    def diagnose_chunks(self) -> dict:
        """Diagnose chunk encryption status - helps debug why LLM can't find documents."""
        try:
            from sqlalchemy import text
            
            # Count total chunks for this tenant
            total_chunks = self.db.execute(
                text(f"SELECT COUNT(*) FROM document_chunks WHERE tenant_id = '{self.tenant_id}'")
            ).scalar()
            
            # Try to decrypt a sample of chunks
            sample_chunks = self.db.query(DocumentChunk).filter(
                DocumentChunk.tenant_id == self.tenant_id
            ).limit(3).all()
            
            decryptable_count = 0
            data_key = encryption_manager.get_or_create_dek(str(self.tenant_id))
            
            for chunk in sample_chunks:
                try:
                    encryption_manager.decrypt_field(chunk.chunk_text_encrypted, data_key)
                    decryptable_count += 1
                except Exception as e:
                    logger.debug(f"Chunk {chunk.chunk_id} not decryptable: {type(e).__name__}")
            
            diagnosis = {
                "total_chunks": total_chunks,
                "sample_tested": len(sample_chunks),
                "decryptable_from_sample": decryptable_count,
                "issue": "CHUNKS_NOT_DECRYPTABLE" if decryptable_count == 0 and total_chunks > 0 else None
            }
            
            logger.warning(f"Chunk diagnosis: {diagnosis}")
            return diagnosis
            
        except Exception as e:
            logger.error(f"Diagnosis failed: {str(e)}")
            return {"error": str(e)}
    
    def cleanup_undecryptable_chunks(self) -> int:
        """
        Remove chunks that can't be decrypted (old data with incompatible DEK).
        This is necessary when DEK has changed and old chunks can't be recovered.
        """
        from sqlalchemy import text
        
        try:
            # Get all chunks for this tenant
            chunks = self.db.query(DocumentChunk).filter(
                DocumentChunk.tenant_id == self.tenant_id
            ).all()
            
            data_key = encryption_manager.get_or_create_dek(str(self.tenant_id))
            undecryptable = []
            
            for chunk in chunks:
                try:
                    encryption_manager.decrypt_field(chunk.chunk_text_encrypted, data_key)
                except Exception:
                    undecryptable.append(chunk.chunk_id)
            
            # Delete undecryptable chunks
            if undecryptable:
                chunk_ids_csv = ','.join(f"'{cid}'" for cid in undecryptable)
                self.db.execute(
                    text(f"DELETE FROM document_chunks WHERE chunk_id IN ({chunk_ids_csv})")
                )
                self.db.commit()
                logger.warning(f"Cleaned up {len(undecryptable)} undecryptable chunks for tenant {self.tenant_id}")
                return len(undecryptable)
            
            return 0
            
        except Exception as e:
            logger.error(f"Cleanup failed: {str(e)}")
            raise
    
    def delete_document(self, document_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        """
        Fully delete document: S3 + vector chunks + database.
        
        Args:
            document_id: Document to delete
            user_id: User performing delete (for permission check)
            
        Returns:
            True if deletion successful
        """
        from services.delete_service import DeleteService
        
        delete_service = DeleteService(self.db, self.tenant_id)
        return delete_service.delete_document(document_id, user_id, hard_delete=False)
