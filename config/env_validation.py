"""Environment validation helpers.

Validate presence of critical environment variables at startup and mask secrets.
"""
from config.settings import settings
import logging

logger = logging.getLogger(__name__)

REQUIRED_VARS = [
    "DATABASE_URL",
    # Clerk keys are required in production but optional in development
    # Add AWS keys only for local development if not using IAM role
    "S3_BUCKET_NAME",
]

OPTIONAL_SECRETS = [
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "CLERK_API_KEY",
    "CLERK_SECRET_KEY",
]


def _mask(val: str) -> str:
    if not val:
        return "<missing>"
    if len(val) <= 8:
        return "****"
    return val[:4] + "..." + val[-4:]


def validate_env():
    """Check for required environment variables and log masked values.

    Raises RuntimeError if missing required variables.
    """
    missing = []
    for name in REQUIRED_VARS:
        val = getattr(settings, name, None)
        if not val:
            missing.append(name)

    if missing:
        logger.error("Missing required environment variables: %s", ", ".join(missing))
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")

    # Log a short masked summary for debugging
    summary = {}
    for name in REQUIRED_VARS + OPTIONAL_SECRETS:
        val = getattr(settings, name, None)
        if val is None:
            summary[name] = "<not set>"
        else:
            summary[name] = _mask(str(val))

    logger.info("Env summary: %s", summary)
