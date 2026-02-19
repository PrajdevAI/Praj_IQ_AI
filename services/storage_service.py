"""
Tenant storage tracking service.

Tracks per-tenant S3 storage usage for monitoring, billing, and alerts.
Designed to be easily extensible for threshold-based notifications.
"""

import uuid
import logging
from datetime import datetime
from typing import Optional, Dict

from sqlalchemy.orm import Session

from models.database_models import TenantStorage

logger = logging.getLogger(__name__)


class StorageService:
    """Service for tracking and managing per-tenant storage usage."""

    def __init__(self, db: Session, tenant_id: uuid.UUID):
        self.db = db
        self.tenant_id = tenant_id

    # =====================================================
    # CORE TRACKING
    # =====================================================

    def _get_or_create_record(self) -> TenantStorage:
        """Get existing storage record or create one for this tenant."""
        record = (
            self.db.query(TenantStorage)
            .filter(TenantStorage.tenant_id == self.tenant_id)
            .first()
        )

        if not record:
            record = TenantStorage(
                tenant_id=self.tenant_id,
                total_bytes=0,
                document_count=0,
                peak_bytes=0,
            )
            self.db.add(record)
            self.db.flush()
            logger.info(
                "Created storage tracking record for tenant %s",
                str(self.tenant_id)[:8],
            )

        return record

    def record_upload(self, file_size_bytes: int) -> TenantStorage:
        """
        Record a document upload — increase usage.

        Args:
            file_size_bytes: Size of the uploaded file in bytes

        Returns:
            Updated TenantStorage record
        """
        try:
            record = self._get_or_create_record()
            record.total_bytes += file_size_bytes
            record.document_count += 1
            record.updated_at = datetime.utcnow()

            # Track peak usage
            if record.total_bytes > record.peak_bytes:
                record.peak_bytes = record.total_bytes

            self.db.flush()

            logger.info(
                "📊 Storage updated (upload): tenant=%s total=%sMB docs=%d",
                str(self.tenant_id)[:8],
                record.total_mb,
                record.document_count,
            )

            # Check threshold (non-blocking, for future alerts)
            self._check_threshold(record)

            return record

        except Exception as e:
            logger.error("Failed to record upload storage: %s", e)
            # Don't raise — storage tracking should never block uploads
            return None

    def record_delete(self, file_size_bytes: int) -> TenantStorage:
        """
        Record a document deletion — decrease usage.

        Args:
            file_size_bytes: Size of the deleted file in bytes

        Returns:
            Updated TenantStorage record
        """
        try:
            record = self._get_or_create_record()
            record.total_bytes = max(0, record.total_bytes - file_size_bytes)
            record.document_count = max(0, record.document_count - 1)
            record.updated_at = datetime.utcnow()

            self.db.flush()

            logger.info(
                "📊 Storage updated (delete): tenant=%s total=%sMB docs=%d",
                str(self.tenant_id)[:8],
                record.total_mb,
                record.document_count,
            )

            return record

        except Exception as e:
            logger.error("Failed to record delete storage: %s", e)
            return None

    # =====================================================
    # USAGE QUERIES
    # =====================================================

    def get_usage(self) -> Dict:
        """
        Get current storage usage for this tenant.

        Returns:
            Dict with usage details
        """
        try:
            record = self._get_or_create_record()
            return {
                "tenant_id": str(self.tenant_id),
                "total_bytes": record.total_bytes,
                "total_mb": record.total_mb,
                "total_gb": record.total_gb,
                "document_count": record.document_count,
                "peak_bytes": record.peak_bytes,
                "peak_mb": round(record.peak_bytes / (1024 * 1024), 2),
                "usage_percent": record.usage_percent,
                "threshold_gb": round(
                    record.alert_threshold_bytes / (1024 * 1024 * 1024), 2
                ),
                "last_alert_sent_at": record.last_alert_sent_at,
                "updated_at": record.updated_at,
            }
        except Exception as e:
            logger.error("Failed to get storage usage: %s", e)
            return {
                "tenant_id": str(self.tenant_id),
                "total_bytes": 0,
                "total_mb": 0,
                "document_count": 0,
                "error": str(e),
            }

    # =====================================================
    # THRESHOLD ALERTS (foundation for future use)
    # =====================================================

    def _check_threshold(self, record: TenantStorage):
        """
        Check if tenant has exceeded storage threshold.

        Currently just logs a warning. Future enhancement:
        send email to user + CC acadia when threshold exceeded.

        To enable email alerts later, implement _send_threshold_alert()
        and call it here when usage_percent >= 100.
        """
        usage_pct = record.usage_percent

        if usage_pct >= 100:
            logger.warning(
                "🚨 STORAGE THRESHOLD EXCEEDED: tenant=%s usage=%s%% (%sGB / %sGB)",
                str(self.tenant_id)[:8],
                usage_pct,
                record.total_gb,
                round(record.alert_threshold_bytes / (1024 * 1024 * 1024), 2),
            )
            # Future: self._send_threshold_alert(record)
        elif usage_pct >= 80:
            logger.warning(
                "⚠️ Storage nearing threshold: tenant=%s usage=%s%%",
                str(self.tenant_id)[:8],
                usage_pct,
            )
        elif usage_pct >= 50:
            logger.info(
                "📊 Storage at %s%% for tenant %s",
                usage_pct,
                str(self.tenant_id)[:8],
            )

    def _send_threshold_alert(self, record: TenantStorage):
        """
        FUTURE: Send storage threshold alert email.

        When implemented, this should:
        1. Send email to the tenant user (To:)
        2. CC dev@praj.ai
        3. Include current usage, threshold, and recommendation
        4. Update record.last_alert_sent_at to avoid spamming
        5. Only send once per threshold crossing (check last_alert_sent_at)

        Example implementation:
            from utils.email_sender import email_sender
            from datetime import timedelta

            # Don't send more than once per 24 hours
            if record.last_alert_sent_at:
                if datetime.utcnow() - record.last_alert_sent_at < timedelta(hours=24):
                    return

            email_sender.send_email(
                to_email=tenant_user_email,
                subject=f"Storage Alert: {record.usage_percent}% used",
                body_text=f"Your storage usage is {record.total_gb}GB of {threshold}GB..."
            )

            record.last_alert_sent_at = datetime.utcnow()
            self.db.flush()
        """
        pass


def recalculate_tenant_storage(db: Session, tenant_id: uuid.UUID) -> Dict:
    """
    Recalculate storage from actual documents in DB.
    Useful if tracking gets out of sync.

    Args:
        db: Database session
        tenant_id: Tenant to recalculate

    Returns:
        Dict with recalculated usage
    """
    from models.database_models import Document

    try:
        from sqlalchemy import func

        result = (
            db.query(
                func.coalesce(func.sum(Document.file_size_bytes), 0),
                func.count(Document.document_id),
            )
            .filter(
                Document.tenant_id == tenant_id,
                Document.is_deleted == False,
            )
            .first()
        )

        actual_bytes = int(result[0])
        actual_count = int(result[1])

        # Update the tracking record
        record = (
            db.query(TenantStorage)
            .filter(TenantStorage.tenant_id == tenant_id)
            .first()
        )

        if record:
            record.total_bytes = actual_bytes
            record.document_count = actual_count
            if actual_bytes > record.peak_bytes:
                record.peak_bytes = actual_bytes
            record.updated_at = datetime.utcnow()
            db.flush()

        logger.info(
            "Recalculated storage for tenant %s: %dMB, %d docs",
            str(tenant_id)[:8],
            actual_bytes // (1024 * 1024),
            actual_count,
        )

        return {
            "tenant_id": str(tenant_id),
            "total_bytes": actual_bytes,
            "total_mb": round(actual_bytes / (1024 * 1024), 2),
            "document_count": actual_count,
        }

    except Exception as e:
        logger.error("Failed to recalculate storage: %s", e)
        return {"error": str(e)}
