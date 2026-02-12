"""Encryption and decryption utilities using AES-256-GCM."""

import os
import logging
import hmac
import hashlib
from typing import Tuple, Optional
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.backends import default_backend
from config.settings import settings

logger = logging.getLogger(__name__)


class EncryptionManager:
    """Manages encryption/decryption using AES-256-GCM."""
    
    def __init__(self):
        """Initialize encryption manager."""
        self.algorithm = settings.ENCRYPTION_ALGORITHM
        self.enabled = settings.ENABLE_ENCRYPTION
        
        # In-memory cache for DEKs (in production, use Redis with TTL)
        self._dek_cache = {}
    
    def generate_key(self) -> bytes:
        """Generate a random 256-bit key."""
        return os.urandom(32)  # 256 bits
    
    def encrypt_field(self, plaintext: str, data_key: bytes) -> bytes:
        """
        Encrypt a field using AES-256-GCM.
        
        Args:
            plaintext: The text to encrypt
            data_key: 256-bit encryption key
            
        Returns:
            Encrypted data (nonce + ciphertext)
        """
        if not self.enabled:
            return plaintext.encode('utf-8')
        
        if not plaintext:
            return b''
        
        try:
            # Generate random nonce (96 bits for GCM)
            nonce = os.urandom(12)
            
            # Encrypt
            aesgcm = AESGCM(data_key)
            ciphertext = aesgcm.encrypt(
                nonce, 
                plaintext.encode('utf-8'), 
                None  # No additional authenticated data
            )
            
            # Return nonce + ciphertext
            return nonce + ciphertext
            
        except Exception as e:
            logger.error(f"Encryption failed: {str(e)}")
            raise
    
    def decrypt_field(self, encrypted_data: bytes, data_key: bytes) -> str:
        """
        Decrypt a field using AES-256-GCM.
        
        Args:
            encrypted_data: The encrypted data (nonce + ciphertext)
            data_key: 256-bit encryption key
            
        Returns:
            Decrypted plaintext
        """
        if not self.enabled:
            return encrypted_data.decode('utf-8')
        
        if not encrypted_data:
            return ''
        
        try:
            # Extract nonce and ciphertext
            nonce = encrypted_data[:12]
            ciphertext = encrypted_data[12:]
            
            # Decrypt
            aesgcm = AESGCM(data_key)
            plaintext = aesgcm.decrypt(nonce, ciphertext, None)
            
            return plaintext.decode('utf-8')
            
        except Exception as e:
            logger.error(f"Decryption failed: {str(e)}")
            raise
    
    def get_or_create_dek(self, tenant_id: str) -> bytes:
        """
        Get or create a Data Encryption Key for a tenant.
        Uses deterministic HMAC-based derivation so the DEK is consistent across restarts.
        
        Args:
            tenant_id: The tenant identifier
            
        Returns:
            256-bit data encryption key
        """
        # Normalize tenant id to string
        tenant_key = str(tenant_id)

        # Check cache first (optimization for repeated calls in same session)
        if tenant_key in self._dek_cache:
            logger.debug(f"DEK cache hit for tenant: {tenant_key[:8]}...")
            return self._dek_cache[tenant_key]
        
        # DETERMINISTIC DEK GENERATION: Use HMAC-SHA256 to derive a consistent DEK
        # from tenant_id using a master secret from environment or KMS.
        # This ensures the same tenant_id always generates the same DEK,
        # even after app restart.
        try:
            # Get master encryption key from settings (in production, from AWS KMS)
            master_key = settings.MASTER_ENCRYPTION_KEY
            if not master_key:
                # Fallback: use a default hardcoded key (should be from KMS in production)
                master_key = "acadia-default-master-key-2026"
                logger.warning("Using default master key - in production, set MASTER_ENCRYPTION_KEY via AWS KMS")
            
            # Derive DEK deterministically using HMAC-SHA256
            # HMAC = Hash(key, message), so HMAC(master_key, tenant_id) always produces same output
            dek = hmac.new(
                master_key.encode('utf-8'),
                tenant_id.encode('utf-8'),
                hashlib.sha256
            ).digest()  # Returns 32 bytes (256 bits)
            
            # Cache it for performance (only in current session)
            self._dek_cache[tenant_key] = dek
            
            logger.info(f"Derived deterministic DEK for tenant: {tenant_key[:8]}...")
            return dek
            
        except Exception as e:
            logger.error(f"Failed to derive DEK for tenant {tenant_key}: {str(e)}")
            raise


# Singleton instance
encryption_manager = EncryptionManager()


# Convenience functions for easy import
def encrypt_field(plaintext: str, tenant_id: Optional[str] = None) -> bytes:
    """
    Encrypt a field. Uses tenant-specific DEK.
    
    Args:
        plaintext: Text to encrypt
        tenant_id: Tenant identifier (optional)
        
    Returns:
        Encrypted bytes
    """
    if tenant_id:
        data_key = encryption_manager.get_or_create_dek(tenant_id)
    else:
        # Fallback: generate ephemeral key
        data_key = encryption_manager.generate_key()
    
    return encryption_manager.encrypt_field(plaintext, data_key)


def decrypt_field(encrypted_data: bytes, tenant_id: str) -> str:
    """
    Decrypt a field using tenant's DEK.
    
    Args:
        encrypted_data: Encrypted bytes
        tenant_id: Tenant identifier
        
    Returns:
        Decrypted plaintext
    """
    data_key = encryption_manager.get_or_create_dek(tenant_id)
    return encryption_manager.decrypt_field(encrypted_data, data_key)
