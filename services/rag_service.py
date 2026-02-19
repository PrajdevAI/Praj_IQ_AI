"""RAG (Retrieval-Augmented Generation) service."""

import boto3
import json
import logging
import uuid
from typing import List, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import text
from models.database_models import DocumentChunk
from services.embedding_service import generate_embeddings
from security.encryption import encryption_manager
from config.settings import settings

logger = logging.getLogger(__name__)


class RAGService:
    """Service for RAG: retrieval + generation."""
    
    def __init__(self, db: Session, tenant_id: uuid.UUID):
        self.db = db
        self.tenant_id = tenant_id
        # self.bedrock = boto3.client(
        #     'bedrock-runtime',
        #     region_name=settings.AWS_REGION,
        #     aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        #     aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY
        # )
        self.kms_client = boto3.client("bedrock-runtime", region_name=settings.AWS_REGION)
    def retrieve_relevant_chunks(
        self, 
        query: str, 
        top_k: int = 5
    ) -> List[Tuple[str, float, uuid.UUID]]:
        """
        Retrieve most relevant chunks using vector similarity.
        Excludes chunks from deleted documents.
        """
        # Generate query embedding
        query_embedding = generate_embeddings([query])[0]
        
        # Convert to PostgreSQL array format
        embedding_str = '[' + ','.join(map(str, query_embedding)) + ']'
        
        # Vector similarity search with TENANT ISOLATION + DELETED DOCUMENT FILTERING
        # Use inline embedding string instead of parameter to avoid PostgreSQL vector cast issues
        sql = text(f"""
            SELECT 
                dc.chunk_id,
                dc.chunk_text_encrypted,
                1 - (dc.embedding <=> '{embedding_str}'::vector) as similarity
            FROM document_chunks dc
            INNER JOIN documents d ON dc.document_id = d.document_id
            WHERE dc.tenant_id = :tenant_id
            AND d.is_deleted = false
            ORDER BY dc.embedding <=> '{embedding_str}'::vector
            LIMIT :top_k
        """)
        
        results = self.db.execute(
            sql,
            {'tenant_id': str(self.tenant_id), 'top_k': top_k}
        ).fetchall()
        
        logger.info(f"RAG: Vector search found {len(results)} chunks for query (excluding deleted documents)")
        
        # Decrypt chunks - skip any that fail to decrypt (old data or corruption)
        data_key = encryption_manager.get_or_create_dek(str(self.tenant_id))
        
        decrypted_chunks = []
        failed_count = 0
        for row in results:
            chunk_id = row[0]
            encrypted_text = row[1]
            similarity = row[2]
            
            try:
                plaintext = encryption_manager.decrypt_field(encrypted_text, data_key)
                decrypted_chunks.append((plaintext, similarity, chunk_id))
            except Exception as e:
                # Log error but skip this chunk - don't fail the whole RAG query
                logger.warning(f"Failed to decrypt chunk {chunk_id}: {type(e).__name__}: {str(e)}")
                failed_count += 1
                continue
        
        logger.info(f"RAG: Successfully decrypted {len(decrypted_chunks)} chunks, {failed_count} failed decryption")
        
        return decrypted_chunks
    
    def generate_response(
        self, 
        query: str, 
        context_chunks: List[str]
    ) -> str:
        """Generate response using Mistral via Bedrock."""
        # Construct prompt
        context = "\n\n".join([
            f"[Context {i+1}]: {chunk}" 
            for i, chunk in enumerate(context_chunks)
        ])
        
        prompt = f"""You are a helpful assistant. Answer the user's question using ONLY the provided context. If the answer is not in the context, say "I don't have enough information to answer that question based on the provided documents."

Context:
{context}

User Question: {query}

Answer:"""
        
        # Call Bedrock Mistral
        try:
            request_body = {
                "prompt": f"<s>[INST] {prompt} [/INST]",
                "max_tokens": 512,
                "temperature": 0.7,
                "top_p": 0.9
            }
            
            response = self.bedrock.invoke_model(
                modelId=settings.BEDROCK_LLM_MODEL,
                body=json.dumps(request_body),
                contentType='application/json',
                accept='application/json'
            )
            
            response_body = json.loads(response['body'].read())
            return response_body['outputs'][0]['text']
            
        except Exception as e:
            logger.error(f"LLM generation failed: {str(e)}")
            return "I apologize, but I encountered an error generating a response. Please try again."
    
    def chat(self, query: str) -> Tuple[str, List[uuid.UUID]]:
        """Complete RAG pipeline."""
        # Retrieve relevant chunks
        chunks_with_metadata = self.retrieve_relevant_chunks(query, top_k=5)
        
        if not chunks_with_metadata:
            logger.warning(f"No chunks retrieved for query. This could mean: 1) No documents uploaded 2) Documents exist but chunk decryption failed 3) Vector search returned no results")
            return "I don't have any documents to answer this question. Please ensure documents are uploaded and try refreshing.", []
        
        # Extract text and IDs
        chunk_texts = [chunk[0] for chunk in chunks_with_metadata]
        chunk_ids = [chunk[2] for chunk in chunks_with_metadata]
        
        # Generate response
        response = self.generate_response(query, chunk_texts)
        
        return response, chunk_ids
