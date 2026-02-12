"""Main Streamlit application for Secure PDF Chat."""
import logging
import streamlit as st
import uuid

from auth.clerk_middleware import ClerkAuthManager, show_login_page
from auth.session_manager import check_session_timeout, display_session_timer
from config.env_validation import validate_env
from config.database import get_tenant_db_session, resolve_or_create_user
from config.settings import settings
from models.database_models import User
from services.document_service import DocumentService
from services.chat_service import ChatService
from services.rag_service import RAGService
from services.feedback_service import FeedbackService
from ui.components.sidebar import render_sidebar
from ui.components.chat_interface import render_chat_interface
from dotenv import load_dotenv
load_dotenv()


# ----------------------------
# Logging
# ----------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ----------------------------
# Streamlit page config + CSS
# ----------------------------
st.set_page_config(
    page_title="Secure PDF Chat",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
    .stChatMessage {
        padding: 1rem;
        border-radius: 0.5rem;
        margin-bottom: 0.5rem;
    }
    .user-message {
        background-color: #e3f2fd;
    }
    .assistant-message {
        background-color: #f5f5f5;
    }
    .stButton button {
        width: 100%;
    }
</style>
""",
    unsafe_allow_html=True,
)


def _extract_email_and_clerk_id(user_info: dict) -> tuple[str, str]:
    """
    Extract email + Clerk user id from whatever shape validate_session() returns.
    """
    if not user_info:
        raise ValueError("user_info is empty")

    email = (
        user_info.get("email")
        or user_info.get("email_address")
        or user_info.get("primary_email")
    )
    
    if not email:
        raise ValueError(f"Email not found in user_info keys: {list(user_info.keys())}")

    clerk_user_id = (
        user_info.get("clerk_user_id")
        or user_info.get("user_id")
        or user_info.get("id")
        or user_info.get("sub")
    )

    if not clerk_user_id:
        logger.info("clerk_user_id missing; will be generated from email in resolve_or_create_user")
        clerk_user_id = None

    return email, clerk_user_id


def _clear_user_session_state():
    """
    Clear ONLY user-specific session state (chat sessions, tenant info).
    Does NOT clear auth state — that's handled by logout().
    
    This is critical for multi-tenant: when a different user logs in,
    we must not carry over the previous user's session IDs.
    """
    keys_to_clear = [
        "current_session_id",
        "tenant_id",
        "user_id",
        "db_user_id",
        "chat_messages",
    ]
    for key in keys_to_clear:
        if key in st.session_state:
            del st.session_state[key]
    logger.debug("Cleared user-specific session state")


def main():
    """Main application entry point."""

    # 1) Validate environment variables
    try:
        validate_env()
    except Exception as e:
        logger.error("Environment validation failed: %s", e)
        st.error(f"Environment validation failed: {e}")
        st.stop()

    # 2) Initialize auth manager
    auth_manager = ClerkAuthManager()

    # 3) Handle logout FIRST — clear EVERYTHING and redirect to login
    if st.session_state.get("force_logout", False):
        logger.info("Processing logout request")
        try:
            auth_manager.logout()
        except Exception as e:
            logger.warning("Logout error (continuing): %s", e)

        st.query_params.clear()
        st.session_state.clear()
        st.rerun()

    # 4) Validate/get user session from Clerk
    user_info = auth_manager.validate_session()

    if not user_info:
        logger.info("User not authenticated, showing login page")
        show_login_page()
        st.stop()

    # 5) Extract email + clerk_user_id
    try:
        email, clerk_user_id = _extract_email_and_clerk_id(user_info)
    except Exception as e:
        logger.error("Auth data extraction failed: %s", e, exc_info=True)
        st.error(f"❌ Authentication data missing: {e}")
        st.session_state.clear()
        st.rerun()
        return

    # =========================================================================
    # 6) MULTI-TENANT FIX: Detect user switch and clear stale session state
    # =========================================================================
    # If the email changed since last render, a different user logged in.
    # We MUST clear the previous user's session_id, tenant context, etc.
    previous_email = st.session_state.get("email")
    if previous_email and previous_email != email:
        logger.info(
            "🔄 User switch detected: %s → %s. Clearing previous session state.",
            previous_email[:15], email[:15]
        )
        _clear_user_session_state()

    st.session_state["email"] = email
    logger.info("User authenticated: %s", email[:20])

    # =========================================================================
    # 7) Resolve user in DB (find existing or create new)
    #    This is the SINGLE source of truth for user_id and tenant_id.
    # =========================================================================
    try:
        user_obj, tenant_id_str = resolve_or_create_user(
            email=email, 
            clerk_user_id=clerk_user_id
        )
        tenant_id = uuid.UUID(tenant_id_str) if isinstance(tenant_id_str, str) else tenant_id_str
        user_id = user_obj.user_id
        
        logger.info(
            "✅ Resolved user: email=%s user_id=%s tenant_id=%s",
            email[:15], str(user_id)[:8], str(tenant_id)[:8]
        )
    except Exception as e:
        logger.error("Failed to resolve user: %s", e, exc_info=True)
        st.error(f"❌ Failed to resolve user account: {e}")
        st.stop()
        return

    # Store resolved IDs in session state for debugging / other components
    st.session_state["user_id"] = str(user_id)
    st.session_state["tenant_id"] = str(tenant_id)

    # =========================================================================
    # 8) Create tenant-aware DB session with RLS context
    # =========================================================================
    db = get_tenant_db_session(email, clerk_user_id)

    try:
        # 9) Verify RLS context (dev only)
        if settings.ENVIRONMENT == "development":
            try:
                from sqlalchemy import text
                tenant_check = db.execute(
                    text("SELECT current_setting('app.current_tenant_id', true)")
                ).scalar()
                if tenant_check:
                    logger.debug(
                        "RLS tenant context verified: %s (expected: %s)",
                        tenant_check[:8], str(tenant_id)[:8]
                    )
                else:
                    logger.warning("⚠️ RLS tenant context is NULL!")
            except Exception as e:
                logger.warning("Could not verify RLS tenant context: %s", e)

        # =====================================================================
        # 10) Initialize services — using the RESOLVED user_id and tenant_id
        #     NOT re-querying the User table (avoids the clerk_user_id mismatch)
        # =====================================================================
        doc_service = DocumentService(db, tenant_id)
        rag_service = RAGService(db, tenant_id)
        chat_service = ChatService(db, tenant_id, user_id)
        feedback_service = FeedbackService(db, tenant_id, user_id)

        # =====================================================================
        # 11) UI
        # =====================================================================
        st.title("📄 Secure PDF Chat")
        st.caption("Ask questions about your uploaded documents")

        with st.sidebar:
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(f"**User:** {email[:30]}")
            with col2:
                if st.button("🚪 Logout", use_container_width=True):
                    st.session_state["force_logout"] = True
                    st.rerun()

            st.markdown("---")
            render_sidebar(doc_service, chat_service, user_id)

        col1, col2 = st.columns([1, 3])

        with col1:
            st.markdown("### 🔧 Settings")
            st.selectbox(
                "LLM Model",
                [settings.BEDROCK_LLM_MODEL],
                disabled=True,
                help="Using configured Bedrock model",
            )
            _temperature = st.slider("Temperature", 0.0, 1.0, 0.7)

        with col2:
            st.markdown("### 💬 Chat")
            try:
                # =============================================================
                # MULTI-TENANT FIX: Validate that current_session_id belongs
                # to THIS user before using it. If it belongs to a different
                # user (from a previous login), discard it.
                # =============================================================
                current_session_id = st.session_state.get("current_session_id")
                session_id = None
                
                if current_session_id:
                    try:
                        session_uuid = uuid.UUID(current_session_id)
                        # Verify this session belongs to the current user
                        existing_session = chat_service.get_session_by_id(session_uuid)
                        if existing_session:
                            session_id = session_uuid
                            logger.debug("Loaded existing session: %s", str(session_id)[:8])
                        else:
                            # Session doesn't belong to this user (RLS filtered it out)
                            # or it was deleted. Clear it.
                            logger.info(
                                "⚠️ Stored session %s not found for current user. "
                                "Creating new session.",
                                current_session_id[:8]
                            )
                            del st.session_state["current_session_id"]
                            current_session_id = None
                    except (ValueError, Exception) as e:
                        logger.warning("Invalid session_id in state: %s", e)
                        del st.session_state["current_session_id"]
                        current_session_id = None

                if session_id is None:
                    # Get the user's most recent active session, or create one
                    session = chat_service.get_active_session()
                    session_id = session.session_id
                    st.session_state["current_session_id"] = str(session_id)
                    logger.info("Using session: %s", str(session_id)[:8])
                
                render_chat_interface(chat_service, rag_service, session_id)
            except Exception as e:
                logger.error("Chat interface error: %s", e, exc_info=True)
                st.error(f"Chat interface error: {e}")

        st.markdown("---")
        st.success("✅ **Status:** Authenticated & Connected")

        # Dev debug panel
        if settings.ENVIRONMENT == "development":
            with st.expander("🔍 Debug: Multi-Tenant Info"):
                st.write(f"**Email:** {email}")
                st.write(f"**User ID:** {str(user_id)[:8]}...")
                st.write(f"**Tenant ID:** {str(tenant_id)[:8]}...")
                st.write(f"**Session ID:** {st.session_state.get('current_session_id', 'none')[:8]}...")
                st.write(f"**Clerk User ID:** {clerk_user_id[:20] if clerk_user_id else 'None'}...")

    except Exception as e:
        logger.error("Application error: %s", e, exc_info=True)
        st.error(f"An error occurred: {e}")
    finally:
        try:
            db.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
