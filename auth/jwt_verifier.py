# """Verify Clerk session JWTs using JWKS.

# This module fetches JWKS from the token issuer (iss claim) and verifies
# signature, exp/nbf, and issuer. It returns the verified claims and user id.

# Requires: python-jose[cryptography], requests
# """

# import time
# import logging
# from typing import Dict, Any
# import requests
# from jose import jwt

# from config.settings import settings

# logger = logging.getLogger(__name__)

# # Simple in-memory JWKS cache
# _JWKS_CACHE: Dict[str, Dict[str, Any]] = {}
# _JWKS_CACHE_TTL = 60 * 60  # 1 hour


# def _fetch_jwks(jwks_url: str) -> Dict[str, Any]:
#     now = int(time.time())
#     cached = _JWKS_CACHE.get(jwks_url)
#     if cached and cached.get("expires_at", 0) > now:
#         return cached["jwks"]

#     resp = requests.get(jwks_url, timeout=5)
#     resp.raise_for_status()
#     jwks = resp.json()

#     _JWKS_CACHE[jwks_url] = {
#         "jwks": jwks,
#         "expires_at": now + _JWKS_CACHE_TTL
#     }
#     return jwks


# class InvalidTokenError(Exception):
#     pass


# def verify_clerk_token(token: str) -> Dict[str, Any]:
#     """Verify a Clerk session JWT and return claims.

#     Returns dictionary with keys: user_id (sub) and claims (full payload).
#     Raises InvalidTokenError on failure.
#     """
#     try:
#         # Get unverified header and claims to determine issuer and kid
#         header = jwt.get_unverified_header(token)
#         claims = jwt.get_unverified_claims(token)
#     except Exception as e:
#         logger.exception("Failed to parse token header/claims")
#         raise InvalidTokenError("Malformed token") from e

#     issuer = claims.get("iss")
#     if not issuer:
#         raise InvalidTokenError("Token missing issuer (iss)")

#     # Construct JWKS URL from issuer
#     jwks_url = issuer.rstrip("/") + "/.well-known/jwks.json"

#     try:
#         jwks = _fetch_jwks(jwks_url)
#     except Exception as e:
#         logger.exception("Failed to fetch JWKS")
#         raise InvalidTokenError("Unable to fetch JWKS") from e

#     kid = header.get("kid")
#     if not kid:
#         raise InvalidTokenError("Token header missing kid")

#     # locate key
#     keys = jwks.get("keys", [])
#     key_dict = None
#     for k in keys:
#         if k.get("kid") == kid:
#             key_dict = k
#             break

#     if not key_dict:
#         raise InvalidTokenError("Matching JWK not found")

#     # Use jose to verify. We need to build a key suitable for jose.jwt.decode
#     try:
#         # Verify signature and standard claims (exp, nbf, iss)
#         # Do not verify audience by default; callers can do so if desired
#         decoded = jwt.decode(
#             token,
#             key_dict,
#             algorithms=[header.get("alg", "RS256")],
#             issuer=issuer,
#             options={
#                 "verify_aud": False
#             }
#         )
#     except Exception as e:
#         logger.exception("JWT verification failed")
#         raise InvalidTokenError("JWT verification failed") from e

#     # Additional checks: exp/nbf handled by jose
#     user_id = decoded.get("sub")
#     if not user_id:
#         raise InvalidTokenError("Token missing subject (sub)")

#     return {"user_id": user_id, "claims": decoded}

"""Verify Clerk session JWTs using JWKS or exchange session tokens.

This module fetches JWKS from the token issuer (iss claim) and verifies
signature, exp/nbf, and issuer. It returns the verified claims and user id.

For development session tokens (dvb_*, sess_*), it exchanges them for JWTs
using Clerk's API.

Requires: python-jose[cryptography], requests
"""

import time
import logging
import os
from typing import Dict, Any
import requests
from jose import jwt

from config.settings import settings

logger = logging.getLogger(__name__)

# Simple in-memory JWKS cache
_JWKS_CACHE: Dict[str, Dict[str, Any]] = {}
_JWKS_CACHE_TTL = 60 * 60  # 1 hour


def _fetch_jwks(jwks_url: str) -> Dict[str, Any]:
    now = int(time.time())
    cached = _JWKS_CACHE.get(jwks_url)
    if cached and cached.get("expires_at", 0) > now:
        return cached["jwks"]

    resp = requests.get(jwks_url, timeout=5)
    resp.raise_for_status()
    jwks = resp.json()

    _JWKS_CACHE[jwks_url] = {
        "jwks": jwks,
        "expires_at": now + _JWKS_CACHE_TTL
    }
    return jwks


class InvalidTokenError(Exception):
    pass


def _is_session_token(token: str) -> bool:
    """Check if token is a Clerk session token (not a JWT)."""
    # Clerk session tokens start with specific prefixes
    session_prefixes = ["sess_", "dvb_", "deb_"]
    return any(token.startswith(prefix) for prefix in session_prefixes)


def _exchange_session_token_for_jwt(session_token: str) -> str:
    """Exchange a Clerk session token for a JWT.
    
    This uses Clerk's Backend API to verify the session and get user info.
    """
    secret_key = settings.CLERK_SECRET_KEY
    if not secret_key:
        raise InvalidTokenError("CLERK_SECRET_KEY not configured")
    
    # Clerk Backend API endpoint to verify session
    # Format: https://api.clerk.com/v1/sessions/{session_id}/verify
    clerk_api_base = os.getenv("CLERK_API_BASE_URL", "https://api.clerk.com")
    
    try:
        # Try to get session info using the session token
        headers = {
            "Authorization": f"Bearer {secret_key}",
            "Content-Type": "application/json"
        }
        
        # For development tokens, we need to get the session ID
        # The token format is: dvb_{session_id_encoded}
        logger.info(f"Attempting to verify session token: {session_token[:15]}...")
        
        # Try the sessions verify endpoint
        url = f"{clerk_api_base}/v1/sessions/{session_token}/verify"
        response = requests.post(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            user_id = data.get("user_id")
            session_id = data.get("id")
            
            if not user_id:
                raise InvalidTokenError("Session verification response missing user_id")
            
            logger.info(f"Session token verified successfully for user: {user_id}")
            
            # Get user details to extract email
            user_url = f"{clerk_api_base}/v1/users/{user_id}"
            user_response = requests.get(user_url, headers=headers, timeout=10)
            
            if user_response.status_code == 200:
                user_data = user_response.json()
                email_addresses = user_data.get("email_addresses", [])
                email = email_addresses[0].get("email_address") if email_addresses else f"{user_id}@clerk.local"
            else:
                email = f"{user_id}@clerk.local"
            
            # Return a dict that looks like decoded JWT claims
            return {
                "user_id": user_id,
                "claims": {
                    "sub": user_id,
                    "email": email,
                    "email_verified": True,
                    "session_id": session_id,
                    "iss": "clerk_session_token"
                }
            }
        else:
            logger.error(f"Session verification failed: {response.status_code} - {response.text}")
            raise InvalidTokenError(f"Session verification failed: {response.status_code}")
            
    except requests.RequestException as e:
        logger.error(f"Network error during session verification: {e}")
        raise InvalidTokenError(f"Failed to verify session token: {str(e)}")


def verify_clerk_token(token: str) -> Dict[str, Any]:
    """Verify a Clerk session JWT and return claims.

    Returns dictionary with keys: user_id (sub) and claims (full payload).
    Raises InvalidTokenError on failure.
    
    Handles both JWTs and Clerk session tokens.
    """
    # Check if this is a session token instead of a JWT
    if _is_session_token(token):
        logger.info("Detected Clerk session token, exchanging for user info...")
        return _exchange_session_token_for_jwt(token)
    
    # Otherwise, proceed with JWT verification
    try:
        # Get unverified header and claims to determine issuer and kid
        header = jwt.get_unverified_header(token)
        claims = jwt.get_unverified_claims(token)
    except Exception as e:
        logger.exception("Failed to parse token header/claims")
        raise InvalidTokenError("Malformed token") from e

    issuer = claims.get("iss")
    if not issuer:
        raise InvalidTokenError("Token missing issuer (iss)")

    # Construct JWKS URL from issuer
    jwks_url = issuer.rstrip("/") + "/.well-known/jwks.json"

    try:
        jwks = _fetch_jwks(jwks_url)
    except Exception as e:
        logger.exception("Failed to fetch JWKS")
        raise InvalidTokenError("Unable to fetch JWKS") from e

    kid = header.get("kid")
    if not kid:
        raise InvalidTokenError("Token header missing kid")

    # locate key
    keys = jwks.get("keys", [])
    key_dict = None
    for k in keys:
        if k.get("kid") == kid:
            key_dict = k
            break

    if not key_dict:
        raise InvalidTokenError("Matching JWK not found")

    # Use jose to verify. We need to build a key suitable for jose.jwt.decode
    try:
        # Verify signature and standard claims (exp, nbf, iss)
        # Do not verify audience by default; callers can do so if desired
        decoded = jwt.decode(
            token,
            key_dict,
            algorithms=[header.get("alg", "RS256")],
            issuer=issuer,
            options={
                "verify_aud": False
            }
        )
    except Exception as e:
        logger.exception("JWT verification failed")
        raise InvalidTokenError("JWT verification failed") from e

    # Additional checks: exp/nbf handled by jose
    user_id = decoded.get("sub")
    if not user_id:
        raise InvalidTokenError("Token missing subject (sub)")

    return {"user_id": user_id, "claims": decoded}