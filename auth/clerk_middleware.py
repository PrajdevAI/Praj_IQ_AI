"""Clerk authentication middleware.""" 

import streamlit as st
import logging
from typing import Optional, Dict
import uuid
from functools import wraps
from urllib.parse import quote
from config.settings import settings
from config.database import get_tenant_db_session, resolve_or_create_user, set_tenant_context
from models.database_models import User
from sqlalchemy.orm import Session 
import os
import jwt
import requests
import hashlib
from datetime import datetime

logger = logging.getLogger(__name__)


class InvalidTokenError(Exception):
    """Raised when token verification fails."""
    pass


class ClerkAuthManager:
    """Manages Clerk authentication and user sessions."""
    
    def __init__(self):
        """Initialize Clerk authentication manager."""
        sk = settings.CLERK_SECRET_KEY
        legacy = settings.CLERK_API_KEY
        if sk and isinstance(sk, str) and sk.startswith("sk_"):
            self.secret_key = sk
        elif legacy and isinstance(legacy, str) and legacy.startswith("sk_"):
            self.secret_key = legacy
        else:
            self.secret_key = sk or legacy
        
        self.frontend_api = settings.CLERK_FRONTEND_API or os.getenv("CLERK_PUBLISHABLE_KEY")
        
        if self.secret_key and isinstance(self.secret_key, str) and self.secret_key.startswith("pk_"):
            logger.warning("⚠️ CLERK secret key appears to be a publishable key (pk_). Check .env values.")
    
    # =========================================================================
    # TOKEN VERIFICATION
    # =========================================================================
    
    def _verify_clerk_session_token(self, token: str) -> Dict:
        """
        Verify Clerk session token.
        
        For JWT tokens (production): verify signature and extract claims.
        For dvb_ tokens (development): use Clerk Backend API to get session info.
        """
        # JWT token — verify directly
        if token.count('.') == 2:
            try:
                return self._verify_jwt_token(token)
            except Exception as e:
                logger.warning(f"JWT verification failed: {e}")
                raise InvalidTokenError(f"JWT verification failed: {e}")
        
        # dvb_ dev token — try to get session via Clerk API
        try:
            logger.info("Verifying token via Clerk API...")
            
            clerk_api_url = f"https://api.clerk.com/v1/sessions/{token}/verify"
            headers = {
                "Authorization": f"Bearer {self.secret_key}",
                "Content-Type": "application/json"
            }
            
            response = requests.post(clerk_api_url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                session_data = response.json()
                user_id = session_data.get("user_id")
                user_info = self._get_clerk_user_info(user_id)
                
                email = f"{user_id}@clerk.local"
                email_addresses = user_info.get("email_addresses", [])
                if email_addresses:
                    email = email_addresses[0].get("email_address", email)
                
                return {
                    "user_id": user_id,
                    "claims": {
                        "email": email,
                        "email_verified": True,
                        "first_name": user_info.get("first_name", ""),
                        "last_name": user_info.get("last_name", "")
                    }
                }
            else:
                logger.warning(
                    f"Clerk session verify returned {response.status_code}. "
                    f"Token may be expired (normal for dvb_ dev tokens)."
                )
                raise InvalidTokenError(f"API verification failed: {response.status_code}")
                
        except requests.RequestException as e:
            logger.error(f"Network error during Clerk API call: {e}")
            raise InvalidTokenError(f"Network error: {str(e)}")
    
    def _verify_jwt_token(self, token: str) -> Dict:
        """Verify JWT token from Clerk using JWKS."""
        try:
            unverified_header = jwt.get_unverified_header(token)
            
            jwks_url = os.getenv("CLERK_JWKS_URL")
            if not jwks_url and self.frontend_api:
                jwks_url = f"https://clerk.{self.frontend_api.split('.')[-2]}.{self.frontend_api.split('.')[-1]}/.well-known/jwks.json"
            
            if not jwks_url:
                raise InvalidTokenError("No JWKS URL available")
            
            jwks_client = jwt.PyJWKClient(jwks_url)
            signing_key = jwks_client.get_signing_key_from_jwt(token)
            
            decoded = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                options={"verify_exp": True}
            )
            
            logger.info("JWT token verified successfully")
            
            return {
                "user_id": decoded.get("sub"),
                "claims": decoded
            }
            
        except jwt.ExpiredSignatureError:
            raise InvalidTokenError("Token has expired")
        except jwt.InvalidTokenError as e:
            raise InvalidTokenError(f"Invalid JWT: {str(e)}")
        except Exception as e:
            raise InvalidTokenError(f"Verification error: {str(e)}")
    
    def _get_clerk_user_info(self, user_id: str) -> Dict:
        """Get user information from Clerk Backend API."""
        try:
            user_url = f"https://api.clerk.com/v1/users/{user_id}"
            headers = {
                "Authorization": f"Bearer {self.secret_key}",
                "Content-Type": "application/json"
            }
            
            response = requests.get(user_url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Failed to get user info: {response.status_code}")
                return {}
                
        except Exception as e:
            logger.error(f"Error getting user info: {e}")
            return {}
    
    def _get_clerk_active_sessions(self) -> list:
        """
        Get all active sessions from Clerk Backend API.
        Fallback when dvb_ tokens expire (410 Gone).
        """
        try:
            url = "https://api.clerk.com/v1/sessions?status=active"
            headers = {
                "Authorization": f"Bearer {self.secret_key}",
                "Content-Type": "application/json"
            }
            
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                sessions = response.json()
                if isinstance(sessions, dict) and "data" in sessions:
                    return sessions["data"]
                elif isinstance(sessions, list):
                    return sessions
                return []
            else:
                logger.warning(f"Failed to get active sessions: {response.status_code}")
                return []
                
        except Exception as e:
            logger.error(f"Error getting active sessions: {e}")
            return []

    def _resolve_dev_token_via_clerk_api(self, token: str) -> Optional[Dict]:
        """
        When a dvb_ token expires (410 Gone), find the user through
        Clerk's Backend API.
        
        Strategy 1: Get active sessions → find most recent → get user
        Strategy 2: List users sorted by last sign-in → get most recent
        """
        logger.info("🔍 Resolving expired dev token via Clerk Backend API...")
        
        # Strategy 1: Active sessions
        try:
            sessions = self._get_clerk_active_sessions()
            
            if sessions:
                sessions.sort(
                    key=lambda s: s.get("created_at", 0), 
                    reverse=True
                )
                
                most_recent = sessions[0]
                user_id = most_recent.get("user_id")
                
                if user_id:
                    logger.info(f"✅ Found active session for user: {user_id[:20]}...")
                    user_info = self._get_clerk_user_info(user_id)
                    
                    email = f"{user_id}@clerk.local"
                    email_addresses = user_info.get("email_addresses", [])
                    if email_addresses:
                        email = email_addresses[0].get("email_address", email)
                    
                    return {
                        "user_id": user_id,
                        "claims": {
                            "email": email,
                            "email_address": email,
                            "email_verified": True,
                            "first_name": user_info.get("first_name", ""),
                            "last_name": user_info.get("last_name", "")
                        }
                    }
        except Exception as e:
            logger.warning(f"Active sessions lookup failed: {e}")
        
        # Strategy 2: Most recently signed-in user
        try:
            url = "https://api.clerk.com/v1/users?order_by=-last_sign_in_at&limit=1"
            headers = {
                "Authorization": f"Bearer {self.secret_key}",
                "Content-Type": "application/json"
            }
            
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                users = response.json()
                if isinstance(users, dict) and "data" in users:
                    users = users["data"]
                
                if users and len(users) > 0:
                    user = users[0]
                    user_id = user.get("id")
                    
                    email = f"{user_id}@clerk.local"
                    email_addresses = user.get("email_addresses", [])
                    if email_addresses:
                        email = email_addresses[0].get("email_address", email)
                    
                    logger.info(f"✅ Found most recently signed-in user: {email[:15]}...")
                    
                    return {
                        "user_id": user_id,
                        "claims": {
                            "email": email,
                            "email_address": email,
                            "email_verified": True,
                            "first_name": user.get("first_name", ""),
                            "last_name": user.get("last_name", "")
                        }
                    }
        except Exception as e:
            logger.warning(f"Users list lookup failed: {e}")
        
        return None
    
    # =========================================================================
    # DEVELOPMENT MODE AUTH
    # =========================================================================
    
    def _development_mode_auth(self, email: str) -> Dict:
        """
        Development mode authentication with a known email.
        ⚠️ ONLY USE IN DEVELOPMENT
        """
        logger.warning("⚠️ USING DEVELOPMENT MODE AUTHENTICATION")
        
        normalized = email.strip().lower()
        email_hash = hashlib.md5(normalized.encode()).hexdigest()[:12]
        stable_clerk_id = f"dev_{email_hash}"
        
        logger.info(f"✅ Dev auth: email={normalized[:15]}... clerk_id={stable_clerk_id}")
        
        return {
            "user_id": stable_clerk_id,
            "claims": {
                "email": normalized,
                "email_address": normalized,
                "email_verified": True,
                "first_name": "Dev",
                "last_name": "User"
            }
        }
    
    # =========================================================================
    # SESSION VALIDATION — Main entry point
    # =========================================================================
    
    def validate_session(self) -> Optional[Dict]:
        """
        Validate Clerk session.
        
        Flow:
          1. Check existing Streamlit session state
          2. Check query params for Clerk redirect token
          3. If token verification fails in dev mode:
             a. Try Clerk Backend API to find the active user
             b. Fall back to DEV_USER_EMAIL if set
          4. Check dev_mode_authenticated flag
        """
        # ── STEP 1: Existing session ──
        if "user_info" in st.session_state and st.session_state.get("authenticated"):
            logger.debug("Found existing authenticated session")
            return st.session_state["user_info"]
        
        # ── STEP 2: Check query params ──
        query_params = st.query_params
        
        if query_params:
            logger.info(f"Query params: {list(query_params.keys())}")
        
        possible_keys = [
            "__clerk_db_jwt", "__clerk_handshake", 
            "session_token", "clerk_session", "__session"
        ]
        token = None
        
        for key in possible_keys:
            if key in query_params:
                val = query_params.get(key)
                if isinstance(val, (list, tuple)) and len(val) > 0:
                    token = val[0]
                elif isinstance(val, str):
                    token = val
                if token:
                    logger.info(f"Found token in param: {key}")
                    break
        
        # ── STEP 3: Verify token ──
        if token:
            try:
                logger.info(
                    f"Verifying token (len={len(token)}, "
                    f"starts={token[:10]}...)"
                )
                
                is_dev_mode = (
                    os.getenv("BYPASS_JWT_VERIFICATION") == "true" 
                    or settings.ENVIRONMENT == "development"
                )
                
                info = None
                
                # Try real verification first
                try:
                    info = self._verify_clerk_session_token(token)
                    logger.info("✅ Token verified via Clerk API")
                except Exception as api_error:
                    logger.warning(f"Clerk API failed: {api_error}")
                    
                    if is_dev_mode:
                        # FIX: Use Clerk Backend API to find the user
                        logger.info("🔍 Trying Clerk Backend API to resolve user...")
                        info = self._resolve_dev_token_via_clerk_api(token)
                        
                        if info:
                            logger.info(
                                f"✅ Resolved via Clerk API: "
                                f"{info['claims'].get('email', 'unknown')[:15]}..."
                            )
                        else:
                            # Last resort: DEV_USER_EMAIL
                            dev_email = os.getenv("DEV_USER_EMAIL", "").strip()
                            if dev_email and "@" in dev_email:
                                logger.warning(f"Using DEV_USER_EMAIL: {dev_email[:15]}...")
                                info = self._development_mode_auth(dev_email)
                            else:
                                logger.error(
                                    "❌ Cannot determine user email! "
                                    "Set DEV_USER_EMAIL in .env"
                                )
                    else:
                        raise
                
                if not info:
                    return None
                
                user_info = {
                    "clerk_user_id": info["user_id"],
                    "email": info["claims"].get(
                        "email", f"{info['user_id']}@clerk.local"
                    ),
                    "claims": info["claims"],
                    "session_id": token
                }
                
                logger.info(f"✅ Authenticated: {user_info['email']}")
                
                st.session_state["user_info"] = user_info
                st.session_state["authenticated"] = True
                st.session_state["_auth_verified"] = True
                
                if not st.session_state.get("_params_cleared", False):
                    st.session_state["_params_cleared"] = True
                    st.query_params.clear()
                    st.rerun()
                
                return user_info
                
            except InvalidTokenError as e:
                logger.error(f"Token verification failed: {e}")
                st.error(f"Authentication failed: {str(e)}")
                return None
            except Exception as e:
                logger.error(f"Unexpected auth error: {e}", exc_info=True)
                st.error(f"Authentication error: {str(e)}")
                
                if settings.ENVIRONMENT == "development":
                    with st.expander("🔍 Debug Error Details"):
                        st.code(str(e))
                
                return None
        
        # ── STEP 4: Dev mode manual auth ──
        if (settings.ENVIRONMENT == "development" 
                and st.session_state.get("dev_mode_authenticated")):
            return st.session_state.get("user_info")
        
        logger.debug("No valid authentication found")
        return None
    
    # =========================================================================
    # USER + TENANT MANAGEMENT
    # =========================================================================
    
    def get_or_create_user(self, db, clerk_user_info: Dict):
        """Get existing user or create new one."""
        clerk_id = clerk_user_info.get("clerk_user_id")
        email = clerk_user_info.get("email")

        if db and isinstance(db, Session):
            user = db.query(User).filter(User.clerk_user_id == clerk_id).first()
            if user:
                return user
            user = User(clerk_user_id=clerk_id, email=email)
            db.add(user)
            db.commit()
            db.refresh(user)
            logger.info(f"Created new user for clerk_user_id={clerk_id}")
            return user

        user, tenant_id = resolve_or_create_user(email=email, clerk_user_id=clerk_id)
        return user
    
    def setup_tenant_context(self, db, tenant_id):
        """Set PostgreSQL session variable for RLS policies."""
        try:
            set_tenant_context(db, str(tenant_id))
        except Exception as e:
            logger.error(f"Failed to set tenant context: {e}")
    
    def logout(self):
        """Clear session, logout user, and redirect to Clerk sign-out."""
        keys_to_clear = [
            "user_info", "authenticated", "tenant_id", "user_id",
            "last_activity", "dev_mode_authenticated", "_auth_verified",
            "_params_cleared", "email", "current_session_id"
        ]
        
        for key in keys_to_clear:
            if key in st.session_state:
                del st.session_state[key]
        
        logger.info("User session cleared locally")
        
        CLERK_AUTH_BASE_URL = os.getenv("CLERK_AUTH_BASE_URL")
        APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:8501")
        
        if CLERK_AUTH_BASE_URL:
            encoded_redirect = quote(APP_BASE_URL, safe=":/?#[]@!$&'()*+,;=")
            clerk_signout_url = f"{CLERK_AUTH_BASE_URL}/sign-out?redirect_url={encoded_redirect}"
            
            st.markdown(
                f'<script>window.location.href = "{clerk_signout_url}";</script>',
                unsafe_allow_html=True
            )
            st.stop()
        else:
            logger.warning("CLERK_AUTH_BASE_URL not set")


def require_auth(func):
    """Decorator for Streamlit functions that require authentication."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        auth_manager = ClerkAuthManager()
        user_info = auth_manager.validate_session()
        
        if not user_info:
            show_login_page()
            st.stop()
        
        import time
        st.session_state["last_activity"] = time.time()
        return func(*args, **kwargs)
    
    return wrapper


def show_login_page():
    """Display Clerk authentication page."""
    st.title("🔐 Secure PDF Chat")
    
    CLERK_AUTH_BASE_URL = os.getenv("CLERK_AUTH_BASE_URL")
    APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:8501")
    
    auth_manager = ClerkAuthManager()
    existing_user = auth_manager.validate_session()
    
    if existing_user:
        email = existing_user.get("email") or existing_user.get("email_address")
        st.warning("⚠️ You are already signed in!")
        st.info(f"Current account: **{email}**")
        
        st.markdown("---")
        st.markdown("### Switch to a Different Account")
        
        if st.button("🚪 Sign Out", use_container_width=True, type="primary"):
            st.session_state["force_logout"] = True
            st.rerun()
        st.stop()
    
    if not CLERK_AUTH_BASE_URL:
        st.error("❌ CLERK_AUTH_BASE_URL not configured")
        st.stop()
    
    st.write("Sign in with Clerk to access your secure PDF chat.")
    
    col1, col2 = st.columns(2)
    encoded_redirect_url = quote(APP_BASE_URL, safe=":/?#[]@!$&'()*+,;=")
    signin_url = f"{CLERK_AUTH_BASE_URL}/sign-in?redirect_url={encoded_redirect_url}"
    signup_url = f"{CLERK_AUTH_BASE_URL}/sign-up?redirect_url={encoded_redirect_url}"
    
    with col1:
        st.link_button("📝 Sign In", signin_url, use_container_width=True)
    with col2:
        st.link_button("✍️ Sign Up", signup_url, use_container_width=True)
    
    st.markdown("---")
    
    if settings.ENVIRONMENT == "development":
        with st.expander("🔍 Debug Info"):
            st.write(f"Sign In: {signin_url}")
            st.write(f"Sign Up: {signup_url}")
            params = dict(st.query_params)
            if params:
                st.json({k: (v[:10]+"..."+v[-5:] if isinstance(v,str) and len(v)>20 else v) for k,v in params.items()})
            st.write(f"Authenticated: {st.session_state.get('authenticated', False)}")
            st.write(f"DEV_USER_EMAIL: {os.getenv('DEV_USER_EMAIL', '(not set)')}")