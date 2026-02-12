"""Security tests for tenant isolation."""

import pytest
import uuid
from sqlalchemy.orm import Session
from models.database_models import Document, User
from security.encryption import encryption_manager


def test_tenant_isolation(db_session: Session):
    """Test that tenants cannot access each other's data."""
    # Create two tenants
    tenant_a_id = uuid.uuid4()
    tenant_b_id = uuid.uuid4()
    
    user_a = User(
        clerk_user_id="user_a",
        tenant_id=tenant_a_id
    )
    user_b = User(
        clerk_user_id="user_b",
        tenant_id=tenant_b_id
    )
    
    db_session.add(user_a)
    db_session.add(user_b)
    db_session.commit()
    
    # Tenant A uploads document
    doc_a = Document(
        tenant_id=tenant_a_id,
        user_id=user_a.user_id,
        document_hash="hash_a",
        encryption_key_id="key_a",
        original_filename_encrypted=b"file_a",
        s3_bucket="bucket",
        s3_key_encrypted=b"key",
        file_size_bytes=1000
    )
    db_session.add(doc_a)
    db_session.commit()
    
    # Set tenant B context
    db_session.execute(f"SET app.current_tenant_id = '{tenant_b_id}'")
    
    # Tenant B tries to query documents
    # With RLS enabled, this should return empty
    docs = db_session.query(Document).all()
    
    assert len(docs) == 0, "Tenant B should not see Tenant A's documents"
    
    # Set tenant A context
    db_session.execute(f"SET app.current_tenant_id = '{tenant_a_id}'")
    
    # Tenant A can see their own documents
    docs = db_session.query(Document).all()
    
    assert len(docs) == 1, "Tenant A should see their own documents"
    assert docs[0].document_id == doc_a.document_id


def test_encryption_decryption():
    """Test encryption and decryption."""
    tenant_id = str(uuid.uuid4())
    plaintext = "Sensitive data"
    
    # Get DEK
    dek = encryption_manager.get_or_create_dek(tenant_id)
    
    # Encrypt
    encrypted = encryption_manager.encrypt_field(plaintext, dek)
    
    assert encrypted != plaintext.encode()
    assert len(encrypted) > len(plaintext)
    
    # Decrypt
    decrypted = encryption_manager.decrypt_field(encrypted, dek)
    
    assert decrypted == plaintext


def test_different_tenant_cannot_decrypt():
    """Test that different tenant cannot decrypt data."""
    tenant_a_id = str(uuid.uuid4())
    tenant_b_id = str(uuid.uuid4())
    
    plaintext = "Tenant A secret"
    
    # Tenant A encrypts
    dek_a = encryption_manager.get_or_create_dek(tenant_a_id)
    encrypted = encryption_manager.encrypt_field(plaintext, dek_a)
    
    # Tenant B tries to decrypt with their key
    dek_b = encryption_manager.get_or_create_dek(tenant_b_id)
    
    # This should fail or return garbage
    with pytest.raises(Exception):
        decrypted = encryption_manager.decrypt_field(encrypted, dek_b)


@pytest.fixture
def db_session():
    """Create test database session."""
    from config.database import SessionLocal, engine
    from models.database_models import Base
    
    # Create tables
    Base.metadata.create_all(bind=engine)
    
    session = SessionLocal()
    
    yield session
    
    session.close()
    
    # Cleanup
    Base.metadata.drop_all(bind=engine)
