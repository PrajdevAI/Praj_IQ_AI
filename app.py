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
        "current_session_id",
        "tenant_id",
        "user_id",
        "db_user_id",
        "chat_messages",
        "profile_completed",
        "doc_summary",
        "summary_feedback_given",
        "summary_feedback_doc_count",
        "summary_reaction",
    ]
    for key in keys_to_clear:
        if key in st.session_state:
            del st.session_state[key]
    logger.debug("Cleared user-specific session state")


def _ensure_tables():
    """Create all tables if they don't exist."""
    try:
        from config.database import Base, engine
        from models import database_models  # noqa: F401
        Base.metadata.create_all(bind=engine)
        logger.info("Ensured database tables exist")
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
        logger.info("Profile notification email sent for user %s", str(user_id)[:8])
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
            logger.error("Failed to save profile (attempt %d): %s", attempt + 1, e)
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
    st.markdown("Please fill in your details before continuing to the PDF chat.")
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
# DOCUMENT SUMMARY + FEEDBACK
# =========================================================================

def _generate_document_summary(rag_service, doc_list) -> str:
    """Generate a concise 2-3 line summary of uploaded documents using the LLM."""
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


def _send_summary_feedback_email(
    first_name, last_name, email, tenant_id, rating_emoji, rating_label, comments, doc_summary
):
    """Send summary feedback email to dev@acadiaconsultants.com."""
    body = (
        f"Document Summary Feedback\n"
        f"{'=' * 40}\n\n"
        f"Tenant ID: {tenant_id}\n"
        f"First Name: {first_name}\n"
        f"Last Name: {last_name}\n"
        f"User Email: {email}\n\n"
        f"Rating: {rating_emoji} {rating_label}\n\n"
        f"Comments:\n{comments or 'No comments provided'}\n\n"
        f"{'=' * 40}\n"
        f"Document Summary:\n{doc_summary}\n"
    )

    try:
        import utils.email_sender as _es
        _es.email_sender.send_email(
            to_email="dev@acadiaconsultants.com",
            subject=f"Summary Feedback: {rating_emoji} {rating_label} from {first_name} {last_name}",
            body_text=body,
        )
        logger.info("Summary feedback email sent: %s %s", rating_emoji, rating_label)
    except Exception as e:
        logger.warning("Failed to send summary feedback email: %s", e)


def _render_summary_and_feedback(
    rag_service, doc_service, user_id, first_name, last_name, email, tenant_id
):
    """
    Render document summary with feedback gate.
    Returns True if feedback given (chat unlocked), False if waiting.
    """
    doc_list = doc_service.list_documents(user_id)

    if not doc_list:
        st.info("📂 No documents uploaded yet. Upload documents from the sidebar to get started!")
        return True  # No docs = no summary needed, chat open

    current_doc_count = len(doc_list)

    # Reset feedback gate if new documents uploaded
    prev_doc_count = st.session_state.get("summary_feedback_doc_count", 0)
    feedback_given = st.session_state.get("summary_feedback_given", False)

    if current_doc_count != prev_doc_count and prev_doc_count > 0:
        feedback_given = False
        st.session_state["summary_feedback_given"] = False
        st.session_state.pop("doc_summary", None)
        st.session_state.pop("summary_reaction", None)
        logger.info("New documents detected — resetting feedback gate")

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

    # ── Feedback Gate ──
    if not feedback_given:
        st.markdown("**How was this summary?**")

        col_like, col_dislike, col_spacer = st.columns([1, 1, 6])
        with col_like:
            if st.button("👍", key="summary_like", help="Good summary"):
                st.session_state["summary_reaction"] = "like"
                st.rerun()
        with col_dislike:
            if st.button("👎", key="summary_dislike", help="Poor summary"):
                st.session_state["summary_reaction"] = "dislike"
                st.rerun()

        reaction = st.session_state.get("summary_reaction")
        if reaction:
            st.markdown("---")
            st.markdown("#### 📝 Share Your Feedback")

            rating_options = {
                "😄 Excellent": ("😄", "Excellent"),
                "🙂 Good": ("🙂", "Good"),
                "😐 Okay": ("😐", "Okay"),
                "😞 Bad": ("😞", "Bad"),
            }

            default_idx = 1 if reaction == "like" else 3

            selected_rating = st.radio(
                "Rate the summary:",
                list(rating_options.keys()),
                index=default_idx,
                horizontal=True,
                key="summary_rating_radio",
            )

            feedback_comments = st.text_area(
                "Any suggestions or comments? (optional)",
                placeholder="Tell us how we can improve...",
                key="summary_feedback_comments",
            )

            if st.button("✅ Submit Feedback", key="submit_summary_feedback", use_container_width=True):
                emoji, label = rating_options[selected_rating]

                _send_summary_feedback_email(
                    first_name=first_name,
                    last_name=last_name,
                    email=email,
                    tenant_id=str(tenant_id),
                    rating_emoji=emoji,
                    rating_label=label,
                    comments=feedback_comments,
                    doc_summary=summary,
                )

                st.session_state["summary_feedback_given"] = True
                st.session_state["summary_feedback_doc_count"] = current_doc_count
                st.session_state.pop("summary_reaction", None)

                st.success("✅ Thank you for your feedback! Chat is now unlocked.")
                st.rerun()

        # Chat LOCKED
        st.markdown("---")
        st.warning("💬 **Chat is locked.** Please provide feedback on the summary above to unlock the chat.")
        return False

    # Feedback already given — chat unlocked
    return True


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
        logger.info("Processing logout request")
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

    # 6) Detect user switch
    previous_email = st.session_state.get("email")
    if previous_email and previous_email != email:
        logger.info("🔄 User switch: %s → %s", previous_email[:15], email[:15])
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

        if settings.ENVIRONMENT == "development":
            try:
                from sqlalchemy import text
                tenant_check = db.execute(
                    text("SELECT current_setting('app.current_tenant_id', true)")
                ).scalar()
                if tenant_check:
                    logger.debug("RLS context verified: %s", tenant_check[:8])
            except Exception as e:
                logger.warning("Could not verify RLS context: %s", e)

        # 10) Initialize services
        doc_service = DocumentService(db, tenant_id)
        rag_service = RAGService(db, tenant_id)
        chat_service = ChatService(db, tenant_id, user_id)
        feedback_service = FeedbackService(db, tenant_id, user_id)

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

        # 12) Summary + Feedback Gate
        chat_unlocked = _render_summary_and_feedback(
            rag_service=rag_service,
            doc_service=doc_service,
            user_id=user_id,
            first_name=first_name,
            last_name=last_name,
            email=email,
            tenant_id=tenant_id,
        )

        # 13) Chat — only if feedback given
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