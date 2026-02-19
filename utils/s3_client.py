# """AWS S3 client for encrypted document storage."""

# import boto3
# import logging
# from typing import Optional
# from config.settings import settings

# logger = logging.getLogger(__name__)


# class S3Client:
#     """AWS S3 client with encryption support."""
    
#     def __init__(self):
#         """Initialize S3 client."""
#         self.s3_client = boto3.client(
#             's3',
#             region_name=settings.S3_BUCKET_REGION,
#             aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
#             aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY
#         )
#         self.bucket_name = settings.S3_BUCKET_NAME
#         self.kms_key_id = settings.KMS_KEY_ID
    
#     def upload_file(
#         self,
#         file_bytes: bytes,
#         s3_key: str,
#         metadata: Optional[dict] = None
#     ) -> bool:
#         """
#         Upload file to S3 with server-side encryption.
        
#         Args:
#             file_bytes: File content as bytes
#             s3_key: S3 object key
#             metadata: Optional metadata dict
            
#         Returns:
#             True if successful, False otherwise
#         """
#         try:
#             extra_args = {
#                 'ServerSideEncryption': 'aws:kms',
#                 'SSEKMSKeyId': self.kms_key_id
#             }
            
#             if metadata:
#                 extra_args['Metadata'] = metadata
            
#             self.s3_client.put_object(
#                 Bucket=self.bucket_name,
#                 Key=s3_key,
#                 Body=file_bytes,
#                 **extra_args
#             )
            
#             logger.info(f"Uploaded file to S3: {s3_key}")
#             return True
            
#         except Exception as e:
#             logger.error(f"Failed to upload to S3: {str(e)}")
#             return False
    
#     def download_file(self, s3_key: str) -> Optional[bytes]:
#         """
#         Download file from S3.
        
#         Args:
#             s3_key: S3 object key
            
#         Returns:
#             File content as bytes, or None if failed
#         """
#         try:
#             response = self.s3_client.get_object(
#                 Bucket=self.bucket_name,
#                 Key=s3_key
#             )
            
#             file_bytes = response['Body'].read()
#             logger.info(f"Downloaded file from S3: {s3_key}")
#             return file_bytes
            
#         except Exception as e:
#             logger.error(f"Failed to download from S3: {str(e)}")
#             return None
    
#     def delete_file(self, s3_key: str) -> bool:
#         """
#         Delete file from S3.
        
#         Args:
#             s3_key: S3 object key
            
#         Returns:
#             True if successful, False otherwise
#         """
#         try:
#             self.s3_client.delete_object(
#                 Bucket=self.bucket_name,
#                 Key=s3_key
#             )
            
#             logger.info(f"Deleted file from S3: {s3_key}")
#             return True
            
#         except Exception as e:
#             logger.error(f"Failed to delete from S3: {str(e)}")
#             return False
    
#     def file_exists(self, s3_key: str) -> bool:
#         """
#         Check if file exists in S3.
        
#         Args:
#             s3_key: S3 object key
            
#         Returns:
#             True if exists, False otherwise
#         """
#         try:
#             self.s3_client.head_object(
#                 Bucket=self.bucket_name,
#                 Key=s3_key
#             )
#             return True
#         except:
#             return False
    
#     def list_files(self, prefix: str) -> list:
#         """
#         List files with given prefix.
        
#         Args:
#             prefix: S3 key prefix
            
#         Returns:
#             List of S3 keys
#         """
#         try:
#             response = self.s3_client.list_objects_v2(
#                 Bucket=self.bucket_name,
#                 Prefix=prefix
#             )
            
#             if 'Contents' in response:
#                 return [obj['Key'] for obj in response['Contents']]
#             else:
#                 return []
                
#         except Exception as e:
#             logger.error(f"Failed to list files: {str(e)}")
#             return []


# # Convenience function
# def upload_to_s3_encrypted(bucket: str, key: str, data: bytes, kms_key_id: str) -> bool:
#     """
#     Upload data to S3 with KMS encryption.
    
#     Args:
#         bucket: S3 bucket name
#         key: S3 object key
#         data: Data to upload
#         kms_key_id: KMS key ID for encryption
        
#     Returns:
#         True if successful
#     """
#     client = S3Client()
#     return client.upload_file(data, key)

"""AWS S3 client for encrypted document storage."""

import boto3
import logging
from typing import Optional
from config.settings import settings

logger = logging.getLogger(__name__)


class S3Client:
    """AWS S3 client with encryption support."""

    def __init__(self):
        """Initialize S3 client (uses IAM role on EC2 / AWS_PROFILE locally)."""
        self.s3_client = boto3.client(
            "s3",
            region_name=settings.S3_BUCKET_REGION,
        )
        self.bucket_name = settings.S3_BUCKET_NAME
        self.kms_key_id = settings.KMS_KEY_ID

    @staticmethod
    def build_tenant_key(tenant_id: str, relative_key: str) -> str:
        """
        Force tenant prefix for multi-tenant isolation.
        relative_key example: "documents/<uuid>/file.pdf"
        """
        relative_key = relative_key.lstrip("/")
        return f"tenant/{tenant_id}/{relative_key}"

    def upload_file(self, file_bytes: bytes, s3_key: str, metadata: Optional[dict] = None) -> bool:
        try:
            extra_args = {
                "ServerSideEncryption": "aws:kms",
                "SSEKMSKeyId": self.kms_key_id,
            }
            if metadata:
                extra_args["Metadata"] = metadata

            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=s3_key,
                Body=file_bytes,
                **extra_args,
            )
            logger.info(f"Uploaded file to S3: {s3_key}")
            return True

        except Exception as e:
            logger.error(f"Failed to upload to S3: {str(e)}")
            return False

    def download_file(self, s3_key: str) -> Optional[bytes]:
        try:
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key=s3_key)
            file_bytes = response["Body"].read()
            logger.info(f"Downloaded file from S3: {s3_key}")
            return file_bytes
        except Exception as e:
            logger.error(f"Failed to download from S3: {str(e)}")
            return None

    def delete_file(self, s3_key: str) -> bool:
        try:
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=s3_key)
            logger.info(f"Deleted file from S3: {s3_key}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete from S3: {str(e)}")
            return False

    def file_exists(self, s3_key: str) -> bool:
        try:
            self.s3_client.head_object(Bucket=self.bucket_name, Key=s3_key)
            return True
        except Exception:
            return False

    def list_files(self, prefix: str) -> list:
        try:
            response = self.s3_client.list_objects_v2(Bucket=self.bucket_name, Prefix=prefix)
            if "Contents" in response:
                return [obj["Key"] for obj in response["Contents"]]
            return []
        except Exception as e:
            logger.error(f"Failed to list files: {str(e)}")
            return []

