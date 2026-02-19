"""Application settings and environment configuration."""


from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Application
    APP_NAME: str = "Secure PDF Chat"
    SESSION_TIMEOUT_MINUTES: int = 3
    ENVIRONMENT: str = "development"
    # auth mode controls whether frontend sign-in is mandatory
    AUTH_MODE: str = "development"  # one of 'development' or 'production'

    # Clerk Authentication
    # Backend secret (sk_...) -- required in production, optional in development
    CLERK_API_KEY: Optional[str] = None
    # Frontend publishable key (pk_...) -- used by frontend (Vite) as VITE_CLERK_PUBLISHABLE_KEY
    CLERK_FRONTEND_API: Optional[str] = None
    # Backwards-compatible alias
    CLERK_SECRET_KEY: Optional[str] = None
    
    # Database
    DATABASE_URL: str
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_RECYCLE: int = 3600
    
    # AWS Configuration
    AWS_REGION: str = "us-east-1"
    AWS_ACCESS_KEY_ID: str
    AWS_SECRET_ACCESS_KEY: str
    
    # Bedrock Models
    BEDROCK_EMBEDDING_MODEL: str = "amazon.titan-embed-text-v2:0"
    BEDROCK_LLM_MODEL: str = "mistral.mistral-7b-instruct-v0:2"
    
    # S3 Configuration
    S3_BUCKET_NAME: str
    S3_BUCKET_REGION: str = "us-east-1"
    
    # KMS
    KMS_KEY_ID: str
    
    # Email Configuration
    DEVELOPER_EMAIL: str = "dev@praj.ai"
    SES_SENDER_EMAIL: str
    SES_REGION: str = "us-east-1"
    EMAIL_HASH_KEY: str = ""
    
    # Security
    ENCRYPTION_ALGORITHM: str = "AES-256-GCM"
    MASTER_ENCRYPTION_KEY: Optional[str] = None  # For deterministic DEK derivation; if not set, uses default
    MAX_FILE_SIZE_MB: int = 50
    ALLOWED_FILE_TYPES: str = "pdf"
    
    # Feature Flags
    ENABLE_AUDIT_LOGGING: bool = True
    ENABLE_ENCRYPTION: bool = True
    ENABLE_RLS: bool = True
    
    # Python 3.13 compatible model config
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore"
    )


# Singleton instance
settings = Settings()
