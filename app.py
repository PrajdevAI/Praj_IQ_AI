"""Main Streamlit application for Secure PDF Chat."""
import logging
import streamlit as st
import uuid

from auth.clerk_middleware import ClerkAuthManager, show_login_page
from auth.session_manager import check_session_timeout, display_session_timer
from config.env_validation import validate_env
from config.database import get_tenant_db_session, resolve_or_create_user
from config.settings import settings
from models.database_models import User, UserProfile
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
    .user-message { background-color: #e3f2fd; }
    .assistant-message { background-color: #f5f5f5; }
    .stButton button { width: 100%; }
</style>
""",
    unsafe_allow_html=True,
)


# =========================================================================
# HELPER FUNCTIONS
# =========================================================================

def _extract_email_and_clerk_id(user_info: dict) -> tuple[str, str]:
    """Extract email + Clerk user id from validate_session() result."""
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
        logger.info("clerk_user_id missing; will be generated from email")
        clerk_user_id = None

    return email, clerk_user_id


def _clear_user_session_state():
    """Clear user-specific session state on user switch."""
    keys_to_clear = [
        "current_session_id", "tenant_id", "user_id", "db_user_id",
        "chat_messages", "profile_completed",
        "doc_summary", "summary_feedback_given", "summary_feedback_doc_count",
        "summary_reaction", "first_time_summary_done",
    ]
    for key in keys_to_clear:
        if key in st.session_state:
            del st.session_state[key]


def _ensure_tables():
    """Create all tables if they don't exist."""
    try:
        from config.database import Base, engine
        from models import database_models  # noqa: F401
        Base.metadata.create_all(bind=engine)
    except Exception as e:
        logger.warning("Could not ensure DB tables: %s", e)


def _check_profile_exists(db, user_id) -> bool:
    """Check if UserProfile exists for this user."""
    try:
        profile = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
        return profile is not None
    except Exception as e:
        msg = str(e).lower()
        try:
            db.rollback()
        except Exception:
            pass
        if "user_profiles" in msg or "does not exist" in msg or "undefinedtable" in msg:
            _ensure_tables()
            try:
                profile = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
                return profile is not None
            except Exception:
                try:
                    db.rollback()
                except Exception:
                    pass
        return False


def _get_user_profile(db, user_id):
    """Get the UserProfile for this user."""
    try:
        return db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        return None


def _send_profile_notification(first_name, last_name, company_name, company_email, phone_number, email, user_id):
    """Send email notification about new user profile."""
    body = (
        f"New user profile submitted:\n\n"
        f"First Name: {first_name}\n"
        f"Last Name: {last_name}\n"
        f"Company Name: {company_name}\n"
        f"Company Email: {company_email}\n"
        f"Phone: {phone_number or 'N/A'}\n"
        f"Login Email: {email}\n"
        f"User ID: {user_id}\n"
    )
    try:
        import utils.email_sender as _es
        _es.email_sender.send_email(
            to_email="dev@acadiaconsultants.com",
            subject="New user profile submitted",
            body_text=body,
        )
    except Exception as e:
        logger.warning("Failed to send profile notification email: %s", e)


def _save_profile(email, clerk_user_id, user_id, first_name, last_name, company_name, company_email, phone_number):
    """Save UserProfile to DB."""
    for attempt in range(2):
        db = None
        try:
            db = get_tenant_db_session(email, clerk_user_id)
            new_profile = UserProfile(
                user_id=user_id,
                first_name=first_name.strip(),
                last_name=last_name.strip(),
                company_name=company_name.strip(),
                company_email=company_email.strip(),
                phone_number=phone_number.strip() or None,
            )
            db.add(new_profile)
            db.commit()
            logger.info("✅ Profile saved for user %s", str(user_id)[:8])
            return True
        except Exception as e:
            msg = str(e).lower()
            if db:
                try:
                    db.rollback()
                except Exception:
                    pass
            if attempt == 0 and ("user_profiles" in msg or "does not exist" in msg or "undefinedtable" in msg):
                _ensure_tables()
                continue
            raise
        finally:
            if db:
                try:
                    db.close()
                except Exception:
                    pass
    return False


def _show_profile_form(email, clerk_user_id, user_id):
    """Show mandatory profile form for first-time users."""
    st.title("📋 Complete Your Profile")
    st.markdown("Please fill in your details before continuing.")
    st.markdown("")

    with st.form(key="mandatory_profile_form"):
        col1, col2 = st.columns(2)
        with col1:
            first_name = st.text_input("First Name *", value="", placeholder="John")
        with col2:
            last_name = st.text_input("Last Name *", value="", placeholder="Doe")

        company_name = st.text_input("Company Name *", value="", placeholder="Acadia Consultants")
        company_email = st.text_input("Company Email *", value=email, placeholder="john.doe@company.com")
        phone_number = st.text_input("Phone Number (optional)", value="", placeholder="+1-555-123-4567")

        st.markdown("")
        submitted = st.form_submit_button("Submit and Continue", use_container_width=True)

    if not submitted:
        st.info("Please complete the form above to access the PDF chat.")
        st.stop()
        return

    errors = []
    if not first_name.strip():
        errors.append("First Name is required.")
    if not last_name.strip():
        errors.append("Last Name is required.")
    if not company_name.strip():
        errors.append("Company Name is required.")
    if not company_email.strip():
        errors.append("Company Email is required.")

    if errors:
        for err in errors:
            st.error(err)
        st.stop()
        return

    try:
        _save_profile(email=email, clerk_user_id=clerk_user_id, user_id=user_id,
                       first_name=first_name, last_name=last_name,
                       company_name=company_name, company_email=company_email,
                       phone_number=phone_number)
    except Exception as e:
        st.error(f"Failed to save profile: {e}")
        st.stop()
        return

    _send_profile_notification(first_name.strip(), last_name.strip(),
                                company_name.strip(), company_email.strip(),
                                phone_number.strip(), email, user_id)

    st.success("✅ Profile saved! Redirecting...")
    st.session_state["profile_completed"] = True
    st.rerun()


# =========================================================================
# EMAIL HELPER — used by summary, inline chat, and sidebar feedback
# =========================================================================

def _send_feedback_email(
    first_name, last_name, email, tenant_id,
    feedback_type, rating, comments, context=""
):
    """
    Send any feedback email to dev@acadiaconsultants.com.

    feedback_type: 'summary', 'chat_inline', or 'general'
    rating: '👍' or '👎' or emoji label
    comments: user text (may be empty)
    context: extra info (summary text, message text, etc.)
    """
    body = (
        f"Feedback Received ({feedback_type})\n"
        f"{'=' * 40}\n\n"
        f"Tenant ID: {tenant_id}\n"
        f"First Name: {first_name}\n"
        f"Last Name: {last_name}\n"
        f"User Email: {email}\n\n"
        f"Rating: {rating}\n"
        f"Comments: {comments or 'No comments provided'}\n\n"
    )
    if context:
        body += f"{'=' * 40}\nContext:\n{context}\n"

    try:
        import utils.email_sender as _es
        _es.email_sender.send_email(
            to_email="dev@acadiaconsultants.com",
            subject=f"Feedback ({feedback_type}): {rating} from {first_name} {last_name}",
            body_text=body,
        )
        logger.info("Feedback email sent: type=%s rating=%s", feedback_type, rating)
    except Exception as e:
        logger.warning("Failed to send feedback email: %s", e)


# =========================================================================
# DOCUMENT SUMMARY (shown for all users, feedback gate FIRST TIME ONLY)
# =========================================================================

def _generate_document_summary(rag_service, doc_list) -> str:
    """Generate a concise 2-3 line summary of uploaded documents."""
    if not doc_list:
        return ""

    doc_names = ", ".join(d["filename"] for d in doc_list[:10])

    summary_query = (
        f"Provide a concise 2-3 line summary of the key topics and content covered in "
        f"the uploaded documents: {doc_names}. "
        f"Focus on the main themes and what the user can ask about."
    )

    try:
        response, _ = rag_service.chat(summary_query)
        return response
    except Exception as e:
        logger.warning("Failed to generate document summary: %s", e)
        return (
            f"You have {len(doc_list)} document(s) uploaded: {doc_names}. "
            f"You can ask questions about any of these documents."
        )


def _is_first_time_user(db, user_id) -> bool:
    """
    Check if this is the user's very first session (no prior summary feedback).
    We track this via a 'summary_feedback_at' column on user_profiles.
    Falls back to session_state flag if column doesn't exist yet.
    """
    try:
        profile = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
        if profile and hasattr(profile, "summary_feedback_at") and profile.summary_feedback_at:
            return False
        # Column may not exist yet — check session state
        return not st.session_state.get("first_time_summary_done", False)
    except Exception:
        return not st.session_state.get("first_time_summary_done", False)


def _mark_summary_feedback_done(db, user_id):
    """Mark that user has completed first-time summary feedback."""
    st.session_state["first_time_summary_done"] = True
    try:
        profile = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
        if profile and hasattr(profile, "summary_feedback_at"):
            from datetime import datetime
            profile.summary_feedback_at = datetime.utcnow()
            db.commit()
    except Exception as e:
        logger.debug("Could not persist summary_feedback_at (non-critical): %s", e)
        try:
            db.rollback()
        except Exception:
            pass


def _render_summary_and_feedback(
    rag_service, doc_service, db, user_id,
    first_name, last_name, email, tenant_id
):
    """
    Render document summary.
    Feedback gate only for FIRST-TIME users.
    Existing users always have chat unlocked.

    Returns True if chat should be unlocked.
    """
    doc_list = doc_service.list_documents(user_id)

    if not doc_list:
        st.info("📂 No documents uploaded yet. Upload documents from the sidebar to get started!")
        return True  # No docs = chat open (nothing to chat about anyway)

    current_doc_count = len(doc_list)

    # Regenerate summary if docs changed
    prev_doc_count = st.session_state.get("summary_feedback_doc_count", 0)
    if current_doc_count != prev_doc_count and prev_doc_count > 0:
        st.session_state.pop("doc_summary", None)
        st.session_state.pop("summary_reaction", None)

    st.session_state["summary_feedback_doc_count"] = current_doc_count

    # ── Document Summary ──
    st.markdown("### 📑 Summary of Your Documents")

    if "doc_summary" not in st.session_state or not st.session_state["doc_summary"]:
        with st.spinner("Generating document summary..."):
            summary = _generate_document_summary(rag_service, doc_list)
            st.session_state["doc_summary"] = summary
    else:
        summary = st.session_state["doc_summary"]

    st.markdown(
        f"""<div style="background-color: #f0f7ff; padding: 1rem; border-radius: 0.5rem; 
        border-left: 4px solid #1976d2; margin-bottom: 1rem;">
        {summary}
        </div>""",
        unsafe_allow_html=True,
    )

    # ── Check if first-time user ──
    is_first_time = _is_first_time_user(db, user_id)

    if not is_first_time:
        # Existing user — always show summary, never gate chat
        return True

    # ── FIRST TIME ONLY: feedback gate ──
    feedback_given = st.session_state.get("summary_feedback_given", False)
    if feedback_given:
        return True

    st.markdown("**How was this summary?**")

    col_like, col_dislike, col_spacer = st.columns([1, 1, 6])
    with col_like:
        if st.button("👍", key="summary_like", help="Good summary"):
            # Like = send email immediately, unlock chat
            _send_feedback_email(
                first_name=first_name, last_name=last_name, email=email,
                tenant_id=str(tenant_id), feedback_type="summary",
                rating="👍 Good", comments="", context=summary,
            )
            st.session_state["summary_feedback_given"] = True
            _mark_summary_feedback_done(db, user_id)
            st.success("✅ Thanks! Chat is now unlocked.")
            st.rerun()

    with col_dislike:
        if st.button("👎", key="summary_dislike", help="Poor summary"):
            st.session_state["summary_reaction"] = "dislike"
            st.rerun()

    # If disliked — show ONLY comment box (no rating section)
    reaction = st.session_state.get("summary_reaction")
    if reaction == "dislike":
        st.markdown("---")
        st.markdown("#### 📝 What could be improved?")

        feedback_comments = st.text_area(
            "Your feedback (optional)",
            placeholder="Tell us how we can improve the summary...",
            key="summary_dislike_comments",
        )

        if st.button("✅ Submit Feedback", key="submit_summary_dislike", use_container_width=True):
            _send_feedback_email(
                first_name=first_name, last_name=last_name, email=email,
                tenant_id=str(tenant_id), feedback_type="summary",
                rating="👎 Needs Improvement", comments=feedback_comments,
                context=summary,
            )
            st.session_state["summary_feedback_given"] = True
            st.session_state.pop("summary_reaction", None)
            _mark_summary_feedback_done(db, user_id)
            st.success("✅ Thanks for your feedback! Chat is now unlocked.")
            st.rerun()

    # Chat LOCKED until feedback
    st.markdown("---")
    st.warning("💬 **Chat is locked.** Please provide feedback on the summary above to unlock the chat.")
    return False


# =========================================================================
# MAIN
# =========================================================================

def main():
    """Main application entry point."""

    # 1) Validate environment
    try:
        validate_env()
    except Exception as e:
        logger.error("Environment validation failed: %s", e)
        st.error(f"Environment validation failed: {e}")
        st.stop()

    _ensure_tables()

    # 2) Auth manager
    auth_manager = ClerkAuthManager()

    # 3) Handle logout
    if st.session_state.get("force_logout", False):
        try:
            auth_manager.logout()
        except Exception as e:
            logger.warning("Logout error: %s", e)
        st.query_params.clear()
        st.session_state.clear()
        st.rerun()

    # 4) Validate session
    user_info = auth_manager.validate_session()
    if not user_info:
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

    # 6) Detect user switch
    previous_email = st.session_state.get("email")
    if previous_email and previous_email != email:
        _clear_user_session_state()

    st.session_state["email"] = email

    # 7) Resolve user in DB
    try:
        user_obj, tenant_id_str = resolve_or_create_user(email=email, clerk_user_id=clerk_user_id)
        tenant_id = uuid.UUID(tenant_id_str) if isinstance(tenant_id_str, str) else tenant_id_str
        user_id = user_obj.user_id
    except Exception as e:
        logger.error("Failed to resolve user: %s", e, exc_info=True)
        st.error(f"❌ Failed to resolve user account: {e}")
        st.stop()
        return

    st.session_state["user_id"] = str(user_id)
    st.session_state["tenant_id"] = str(tenant_id)

    # 8) Profile gate
    db = get_tenant_db_session(email, clerk_user_id)

    try:
        profile_completed = st.session_state.get("profile_completed", False)
        if not profile_completed:
            profile_completed = _check_profile_exists(db, user_id)
            st.session_state["profile_completed"] = profile_completed

        if not profile_completed:
            try:
                db.close()
            except Exception:
                pass
            _show_profile_form(email, clerk_user_id, user_id)
            return

        # =====================================================================
        # 9) MAIN APP
        # =====================================================================
        profile = _get_user_profile(db, user_id)
        first_name = profile.first_name if profile else "there"
        last_name = profile.last_name if profile else ""

        # 10) Initialize services
        doc_service = DocumentService(db, tenant_id)
        rag_service = RAGService(db, tenant_id)
        chat_service = ChatService(db, tenant_id, user_id)
        feedback_service = FeedbackService(db, tenant_id, user_id)

        # Store user info in session state for chat_interface inline feedback
        st.session_state["_fb_first_name"] = first_name
        st.session_state["_fb_last_name"] = last_name
        st.session_state["_fb_email"] = email
        st.session_state["_fb_tenant_id"] = str(tenant_id)

        # 11) Personalized greeting
        st.title(f"👋 Welcome, {first_name}!")
        st.caption("Ask questions about your uploaded documents")

        # Sidebar
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

        # 12) Summary + Feedback Gate (first-time only)
        chat_unlocked = _render_summary_and_feedback(
            rag_service=rag_service,
            doc_service=doc_service,
            db=db,
            user_id=user_id,
            first_name=first_name,
            last_name=last_name,
            email=email,
            tenant_id=tenant_id,
        )

        # 13) Chat — only if unlocked
        if chat_unlocked:
            st.markdown("---")
            st.markdown("### 💬 Chat")
            try:
                current_session_id = st.session_state.get("current_session_id")
                session_id = None

                if current_session_id:
                    try:
                        session_uuid = uuid.UUID(current_session_id)
                        existing_session = chat_service.get_session_by_id(session_uuid)
                        if existing_session:
                            session_id = session_uuid
                        else:
                            del st.session_state["current_session_id"]
                    except (ValueError, Exception) as e:
                        logger.warning("Invalid session_id: %s", e)
                        if "current_session_id" in st.session_state:
                            del st.session_state["current_session_id"]

                if session_id is None:
                    session = chat_service.get_active_session()
                    session_id = session.session_id
                    st.session_state["current_session_id"] = str(session_id)

                render_chat_interface(chat_service, rag_service, session_id)
            except Exception as e:
                logger.error("Chat interface error: %s", e, exc_info=True)
                st.error(f"Chat interface error: {e}")

        st.markdown("---")

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