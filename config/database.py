"""Database connection and session management (RDS + RLS + Clerk)."""

import os
import logging
import hmac
import hashlib
from urllib.parse import urlparse, urlunparse, quote

from sqlalchemy import create_engine, event, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import SQLAlchemyError

from config.settings import settings

logger = logging.getLogger(__name__)


# Import ORM models lazily to avoid circular imports at module load time
def _import_models():
    from models.database_models import User
    return User


# ----------------------------
# Helpers
# ----------------------------
def _sanitize_db_url(db_url: str) -> str:
    """Percent-encode username/password in a DB URL to handle special chars."""
    try:
        parsed = urlparse(db_url)
        netloc = parsed.netloc
        if not netloc or "@" not in netloc:
            return db_url

        creds, _, hostport = netloc.rpartition("@")
        if ":" in creds:
            user, pwd = creds.split(":", 1)
            user_enc = quote(user, safe="")
            pwd_enc = quote(pwd, safe="")
            new_netloc = f"{user_enc}:{pwd_enc}@{hostport}"
            new_parsed = parsed._replace(netloc=new_netloc)
            return urlunparse(new_parsed)
        return db_url
    except Exception:
        return db_url


def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def _get_hash_key() -> str:
    """
    Prefer EMAIL_HASH_KEY. Fallback to EMAIL_ENCRYPTION_KEY if that's what you have.
    """
    key = (
        os.getenv("EMAIL_HASH_KEY")
        or getattr(settings, "EMAIL_HASH_KEY", None)
        or os.getenv("EMAIL_ENCRYPTION_KEY")
        or getattr(settings, "EMAIL_ENCRYPTION_KEY", None)
    )
    
    if not key or key == "":
        if settings.ENVIRONMENT == "development":
            logger.warning(
                "⚠️ EMAIL_HASH_KEY not set! Using development default. "
                "SET THIS IN PRODUCTION!"
            )
            key = "dev-key-change-this-in-production-please-use-real-key"
        else:
            raise RuntimeError(
                "Missing EMAIL_HASH_KEY (recommended) or EMAIL_ENCRYPTION_KEY in settings/.env"
            )
    
    return key


def _email_hmac_bytes(email: str) -> bytes:
    """
    Deterministic HMAC-SHA256 of email.
    RETURNS BYTES (for BYTEA column).
    """
    key = _get_hash_key()
    normalized = _normalize_email(email)

    digest = hmac.new(
        key.encode("utf-8"),
        normalized.encode("utf-8"),
        hashlib.sha256,
    ).digest()

    if isinstance(digest, memoryview):
        digest = digest.tobytes()

    return digest


# ----------------------------
# Engine / Session
# ----------------------------
safe_db_url = _sanitize_db_url(settings.DATABASE_URL)

engine = create_engine(
    safe_db_url,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_recycle=settings.DB_POOL_RECYCLE,
    pool_pre_ping=True,
    echo=settings.ENVIRONMENT == "development",
)

try:
    parsed = urlparse(safe_db_url)
    logger.info(
        "Database engine created for user=%s host=%s",
        parsed.username or "<none>",
        parsed.hostname or "<none>",
    )
except Exception:
    logger.info("Database engine created (details unavailable)")

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """Dependency function to get database session (FastAPI style)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Initialize database - create all tables."""
    from models import database_models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created successfully")


def set_tenant_context(db: Session, tenant_id: str):
    """Set PostgreSQL session variable for Row-Level Security."""
    if settings.ENABLE_RLS:
        try:
            tenant_id_str = str(tenant_id)
            db.execute(text(f"SET app.current_tenant_id = '{tenant_id_str}'"))
            logger.info("RLS context set for tenant: %s", tenant_id_str[:8])
        except Exception as e:
            logger.error("Failed to set RLS context: %s", e)
            raise


# ----------------------------
# User resolution / creation
# ----------------------------
def resolve_or_create_user(email: str, clerk_user_id: str = None):
    """
    Resolve user by (in priority order):
      1) email (plaintext) — MOST RELIABLE for multi-tenant
      2) clerk_user_id — secondary (can change in dev mode)
      3) email_encrypted (BYTEA) — legacy fallback

    Creates user if not found by any method.

    MULTI-TENANT KEY PRINCIPLE:
      Same email → same user_id → same tenant_id. Always.
      clerk_user_id is secondary and gets updated on the existing row.

    Returns:
        tuple: (User object, tenant_id string)
    """
    if not email:
        raise ValueError("email is required")

    User = _import_models()
    db = SessionLocal()

    try:
        normalized_email = _normalize_email(email)
        
        logger.info(
            "🔍 resolve_or_create_user: email=%s clerk_id=%s",
            normalized_email[:15],
            (clerk_user_id or "None")[:20]
        )
        
        # =================================================================
        # LOOKUP 1: Email (most stable — this is the multi-tenant anchor)
        # =================================================================
        user = db.query(User).filter(User.email == normalized_email).first()
        if user:
            needs_commit = False
            if clerk_user_id and user.clerk_user_id != clerk_user_id:
                logger.info(
                    "🔗 Updating clerk_user_id for user %s: %s → %s",
                    str(user.user_id)[:8],
                    (user.clerk_user_id or "None")[:15],
                    clerk_user_id[:15]
                )
                user.clerk_user_id = clerk_user_id
                needs_commit = True
            
            if needs_commit:
                db.commit()
                db.refresh(user)
            
            logger.info(
                "✅ Found user by email | user_id=%s | tenant_id=%s",
                str(user.user_id)[:8], str(user.tenant_id)[:8]
            )
            return user, str(user.tenant_id)

        # =================================================================
        # LOOKUP 2: clerk_user_id (if email not found, clerk_id might match)
        # =================================================================
        if clerk_user_id and not clerk_user_id.startswith("dev_"):
            user = db.query(User).filter(User.clerk_user_id == clerk_user_id).first()
            if user:
                logger.info(
                    "🔗 Found by clerk_id, updating email: %s → %s",
                    (user.email or "None")[:15], normalized_email[:15]
                )
                user.email = normalized_email
                db.commit()
                db.refresh(user)
                return user, str(user.tenant_id)
        
        # =================================================================
        # LOOKUP 3: email_encrypted (legacy BYTEA rows)
        # =================================================================
        email_hash_bytes = _email_hmac_bytes(normalized_email)
        user = db.query(User).filter(User.email_encrypted == email_hash_bytes).first()
        if user:
            logger.info(
                "🔄 Migrating legacy user to plaintext email | user_id=%s",
                str(user.user_id)[:8]
            )
            user.email = normalized_email
            if clerk_user_id:
                user.clerk_user_id = clerk_user_id
            db.commit()
            db.refresh(user)
            return user, str(user.tenant_id)

        # =================================================================
        # CREATE: Genuinely new user
        # =================================================================
        logger.info(
            "🆕 Creating NEW user: email=%s clerk_id=%s",
            normalized_email[:15], (clerk_user_id or "None")[:20]
        )
        
        if not clerk_user_id:
            email_hash = hashlib.md5(normalized_email.encode()).hexdigest()[:12]
            clerk_user_id = f"dev_{email_hash}"
            logger.info("🔑 Generated dev clerk_user_id: %s", clerk_user_id)
        
        new_user = User(
            clerk_user_id=clerk_user_id,
            email=normalized_email,
            email_encrypted=email_hash_bytes,
        )

        db.add(new_user)
        db.commit()
        db.refresh(new_user)

        logger.info(
            "✅ Created user | email=%s | user_id=%s | tenant_id=%s",
            normalized_email[:15],
            str(new_user.user_id)[:8],
            str(new_user.tenant_id)[:8],
        )
        
        return new_user, str(new_user.tenant_id)

    except SQLAlchemyError as e:
        logger.error("❌ Database error in resolve_or_create_user: %s", e, exc_info=True)
        db.rollback()
        raise
    except Exception as e:
        logger.error("❌ Unexpected error in resolve_or_create_user: %s", e, exc_info=True)
        db.rollback()
        raise
    finally:
        db.close()


def ensure_tenant_context(db: Session):
    """Re-apply RLS context before commit to handle connection pool reuse."""
    if settings.ENABLE_RLS and hasattr(db, '_acadia_tenant_id'):
        try:
            tenant_id_str = str(db._acadia_tenant_id)
            db.connection().execute(text(f"SET app.current_tenant_id = '{tenant_id_str}'"))
            logger.debug("RLS context re-applied for tenant: %s", tenant_id_str[:8])
        except Exception as e:
            logger.debug("Could not re-apply RLS context: %s", e)


def ensure_rls_for_query(db: Session):
    """Ensure RLS context is set before executing queries."""
    if settings.ENABLE_RLS and hasattr(db, '_acadia_tenant_id'):
        try:
            tenant_id_str = str(db._acadia_tenant_id)
            db.execute(text(f"SET app.current_tenant_id = '{tenant_id_str}'"))
            logger.debug("RLS context set for query: tenant %s", tenant_id_str[:8])
        except Exception as e:
            logger.warning("Could not set RLS context for query: %s", e)


def get_tenant_db_session(email: str, clerk_user_id: str):
    """
    Return a DB session with tenant context set for RLS.
    Caller must close returned session.
    """
    user, tenant_id = resolve_or_create_user(email=email, clerk_user_id=clerk_user_id)

    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        setattr(db, "_acadia_user_id", str(user.user_id))
        setattr(db, "_acadia_tenant_id", tenant_id)
        
        logger.info(
            "🔒 Tenant DB session created | user_id=%s | tenant_id=%s",
            str(user.user_id)[:8], str(tenant_id)[:8]
        )
        return db
    except Exception:
        db.close()
        raise


# ----------------------------
# Connection parameters
# ----------------------------
@event.listens_for(engine, "connect")
def set_postgresql_parameters(dbapi_conn, connection_record):
    """Set PostgreSQL session parameters on connection."""
    cursor = dbapi_conn.cursor()
    cursor.execute("SET timezone='UTC'")
    cursor.execute("SET statement_timeout = 30000")
    cursor.close()
