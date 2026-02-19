"""Embedding generation service using AWS Bedrock Titan."""

import boto3
import json
import logging
from typing import List
from config.settings import settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Service for generating text embeddings using AWS Bedrock Titan."""
    
    def __init__(self):
        """Initialize Bedrock client."""
        # self.bedrock = boto3.client(
        #     'bedrock-runtime',
        #     region_name=settings.AWS_REGION,
        #     aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        #     aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY
        # )
        self.kms_client = boto3.client("bedrock-runtime", region_name=settings.AWS_REGION)
        self.model_id = settings.BEDROCK_EMBEDDING_MODEL
    
    def generate_embedding(self, text: str) -> List[float]:
        """
        Generate embedding for a single text.
        
        Args:
            text: Input text
            
        Returns:
            Embedding vector (1024 dimensions for Titan v2)
        """
        try:
            request_body = {
                "inputText": text
            }
            
            response = self.bedrock.invoke_model(
                modelId=self.model_id,
                body=json.dumps(request_body),
                contentType='application/json',
                accept='application/json'
            )
            
            response_body = json.loads(response['body'].read())
            embedding = response_body['embedding']
            
            return embedding
            
        except Exception as e:
            logger.error(f"Failed to generate embedding: {str(e)}")
            raise
    
    def generate_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for multiple texts.
        
        Args:
            texts: List of input texts
            
        Returns:
            List of embedding vectors
        """
        embeddings = []
        
        for text in texts:
            try:
                embedding = self.generate_embedding(text)
                embeddings.append(embedding)
            except Exception as e:
                logger.error(f"Failed to generate embedding for text: {str(e)}")
                # Use zero vector as fallback
                embeddings.append([0.0] * 1024)
        
        return embeddings


# Singleton instance
embedding_service = EmbeddingService()


def generate_embeddings(texts: List[str]) -> List[List[float]]:
    """
    Convenience function to generate embeddings.
    
    Args:
        texts: List of text strings
        
    Returns:
        List of embedding vectors
    """
    return embedding_service.generate_embeddings_batch(texts)
