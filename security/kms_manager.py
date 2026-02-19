"""AWS KMS Key Management Service integration."""

import boto3
import logging
from typing import Tuple
from config.settings import settings

logger = logging.getLogger(__name__)


class KMSManager:
    """Manages data encryption keys using AWS KMS."""
    
    def __init__(self):
        """Initialize KMS client."""
        # self.kms_client = boto3.client(
        #     'kms',
        #     region_name=settings.AWS_REGION,
        #     aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        #     aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY
        # )
        self.kms_client = boto3.client("kms", region_name=settings.AWS_REGION)
        self.master_key_id = settings.KMS_KEY_ID
    
    def generate_data_key(self, tenant_id: str) -> Tuple[bytes, bytes]:
        """
        Generate a unique DEK for each tenant using KMS.
        
        Args:
            tenant_id: Tenant identifier for encryption context
            
        Returns:
            Tuple of (plaintext_key, encrypted_key)
        """
        try:
            response = self.kms_client.generate_data_key(
                KeyId=self.master_key_id,
                KeySpec='AES_256',
                EncryptionContext={'tenant_id': str(tenant_id)}
            )
            
            logger.info(f"Generated DEK for tenant: {tenant_id}")
            
            return (
                response['Plaintext'],
                response['CiphertextBlob']
            )
            
        except Exception as e:
            logger.error(f"Failed to generate DEK: {str(e)}")
            raise
    
    def decrypt_data_key(self, encrypted_key: bytes, tenant_id: str) -> bytes:
        """
        Decrypt DEK using KMS.
        
        Args:
            encrypted_key: The encrypted data key
            tenant_id: Tenant identifier for encryption context
            
        Returns:
            Decrypted plaintext key
        """
        try:
            response = self.kms_client.decrypt(
                CiphertextBlob=encrypted_key,
                EncryptionContext={'tenant_id': str(tenant_id)}
            )
            
            return response['Plaintext']
            
        except Exception as e:
            logger.error(f"Failed to decrypt DEK: {str(e)}")
            raise
    
    def encrypt_data(self, plaintext: bytes, tenant_id: str) -> bytes:
        """
        Directly encrypt data using KMS (for small data < 4KB).
        
        Args:
            plaintext: Data to encrypt
            tenant_id: Tenant identifier
            
        Returns:
            Encrypted data
        """
        try:
            response = self.kms_client.encrypt(
                KeyId=self.master_key_id,
                Plaintext=plaintext,
                EncryptionContext={'tenant_id': str(tenant_id)}
            )
            
            return response['CiphertextBlob']
            
        except Exception as e:
            logger.error(f"Failed to encrypt data: {str(e)}")
            raise
    
    def decrypt_data(self, ciphertext: bytes, tenant_id: str) -> bytes:
        """
        Directly decrypt data using KMS.
        
        Args:
            ciphertext: Encrypted data
            tenant_id: Tenant identifier
            
        Returns:
            Decrypted data
        """
        try:
            response = self.kms_client.decrypt(
                CiphertextBlob=ciphertext,
                EncryptionContext={'tenant_id': str(tenant_id)}
            )
            
            return response['Plaintext']
            
        except Exception as e:
            logger.error(f"Failed to decrypt data: {str(e)}")
            raise


# Singleton instance
kms_manager = KMSManager()
