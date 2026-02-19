"""Sidebar component for conversation, document management, and feedback."""

import streamlit as st
import uuid
import logging
from datetime import datetime
from services.document_service import DocumentService
from services.chat_service import ChatService
from models.database_models import ChatSession
from utils.file_parser import UPLOAD_EXTENSIONS

logger = logging.getLogger(__name__)


# File type icons for display
FILE_ICONS = {
    ".pdf": "📄", ".docx": "📝", ".doc": "📝",
    ".xlsx": "📊", ".xls": "📊", ".csv": "📊", ".tsv": "📊",
    ".txt": "📃", ".md": "📃", ".log": "📃",
    ".json": "🔧", ".xml": "🔧", ".yaml": "🔧", ".yml": "🔧",
    ".html": "🌐", ".htm": "🌐",
    ".png": "🖼️", ".jpg": "🖼️", ".jpeg": "🖼️",
    ".tiff": "🖼️", ".tif": "🖼️", ".bmp": "🖼️", ".webp": "🖼️",
    ".svg": "🖼️",
}


def _get_file_icon(filename: str) -> str:
    """Get an emoji icon for the file type."""
    import os
    ext = os.path.splitext(filename.lower())[1]
    return FILE_ICONS.get(ext, "📎")


def _send_general_feedback_email(rating, comments):
    """Send general/sidebar feedback email."""
    first_name = st.session_state.get("_fb_first_name", "Unknown")
    last_name = st.session_state.get("_fb_last_name", "")
    email = st.session_state.get("_fb_email", "unknown")
    tenant_id = st.session_state.get("_fb_tenant_id", "unknown")

    body = (
        f"General Feedback\n"
        f"{'=' * 40}\n\n"
        f"Tenant ID: {tenant_id}\n"
        f"First Name: {first_name}\n"
        f"Last Name: {last_name}\n"
        f"User Email: {email}\n\n"
        f"Rating: {rating}\n"
        f"Comments: {comments or 'No comments provided'}\n"
    )

    try:
        import utils.email_sender as _es
        _es.email_sender.send_email(
            to_email="dev@praj.ai",
            subject=f"General Feedback: {rating} from {first_name} {last_name}",
            body_text=body,
        )
        logger.info("General feedback email sent: %s", rating)
    except Exception as e:
        logger.warning("Failed to send general feedback email: %s", e)


def render_sidebar(doc_service: DocumentService, chat_service: ChatService, user_id: uuid.UUID):
    """
    Render sidebar with conversations, document management, feedback, and account.
    """
    # ========== CONVERSATIONS SECTION ==========
    st.sidebar.title("💬 Conversations")

    col1, col2 = st.sidebar.columns([3, 1])
    with col1:
        st.sidebar.markdown("**Chats**")
    with col2:
        if st.button("➕", help="New conversation", key="new_chat_btn", use_container_width=False):
            try:
                new_session = chat_service.create_session()
                st.session_state["current_session_id"] = str(new_session.session_id)
                st.success("✅ New conversation created")
                st.rerun()
            except Exception as e:
                logger.error(f"Error creating new conversation: {str(e)}", exc_info=True)
                st.error(f"❌ Failed to create conversation: {str(e)}")

    # List conversations
    try:
        sessions = chat_service.list_sessions(include_deleted=False)

        if not sessions:
            st.sidebar.info("💭 No conversations yet.\n\nClick ➕ to start a new chat!")
        else:
            current_session = st.session_state.get("current_session_id")

            for session in sessions:
                session_id = session["session_id"]
                title = session["title"]
                last_msg_at = session["last_message_at"]

                if last_msg_at:
                    time_str = last_msg_at.strftime("%b %d, %H:%M")
                else:
                    time_str = "Just now"

                is_current = session_id == current_session
                prefix = "✓ " if is_current else "  "

                col1, col2 = st.sidebar.columns([4, 1])
                with col1:
                    if st.button(
                        f"{prefix}{title}\n{time_str}",
                        key=f"conv_{session_id}",
                        use_container_width=True
                    ):
                        st.session_state["current_session_id"] = session_id
                        st.rerun()

                with col2:
                    if st.button("✕", key=f"del_conv_{session_id}", help="Delete chat"):
                        try:
                            chat_service.db.query(ChatSession).filter(
                                ChatSession.session_id == uuid.UUID(session_id)
                            ).update({"is_deleted": True})
                            chat_service.db.commit()

                            if is_current and sessions:
                                for s in sessions:
                                    if s["session_id"] != session_id:
                                        st.session_state["current_session_id"] = s["session_id"]
                                        break

                            st.rerun()
                        except Exception as e:
                            logger.error(f"Error deleting conversation: {str(e)}", exc_info=True)
                            st.error(f"❌ Delete failed: {str(e)}")

    except Exception as e:
        logger.error(f"Error loading conversations: {str(e)}", exc_info=True)
        st.sidebar.warning(f"⚠️ Error loading conversations: {str(e)}")

    st.sidebar.divider()

    # ========== DOCUMENTS SECTION ==========
    st.sidebar.title("📁 Documents")

    st.sidebar.subheader("Upload Documents")

    upload_types = [ext.lstrip('.') for ext in UPLOAD_EXTENSIONS]

    # Dynamic key to clear file selection after upload
    uploader_key = f"file_uploader_{st.session_state.get('uploader_key', 0)}"

    uploaded_files = st.sidebar.file_uploader(
        "Choose files to upload",
        type=upload_types,
        accept_multiple_files=True,
        help="Select one or more files. Supported: PDF, Word, Excel, CSV, Text, Images (max 50MB each)",
        key=uploader_key
    )

    if uploaded_files:
        total_size = sum(f.size for f in uploaded_files)
        total_size_mb = total_size / (1024 * 1024)
        st.sidebar.caption(f"**{len(uploaded_files)} file(s) selected** ({total_size_mb:.1f} MB total)")

        for f in uploaded_files:
            icon = _get_file_icon(f.name)
            size_mb = f.size / (1024 * 1024)
            st.sidebar.caption(f"{icon} {f.name} ({size_mb:.1f} MB)")

        if st.sidebar.button("📤 Upload All", key="upload_btn", use_container_width=True):
            success_count = 0
            fail_count = 0
            progress = st.sidebar.progress(0, text="Uploading...")

            for i, uploaded_file in enumerate(uploaded_files):
                progress.progress(
                    (i) / len(uploaded_files),
                    text=f"Processing {uploaded_file.name} ({i+1}/{len(uploaded_files)})..."
                )
                try:
                    file_bytes = uploaded_file.read()
                    filename = uploaded_file.name

                    doc_service.upload_document(
                        file_bytes=file_bytes,
                        filename=filename,
                        user_id=user_id
                    )
                    success_count += 1

                except ValueError as e:
                    st.sidebar.error(f"❌ {filename}: {str(e)}")
                    fail_count += 1
                except RuntimeError as e:
                    st.sidebar.error(f"❌ {filename}: {str(e)}")
                    fail_count += 1
                except Exception as e:
                    logger.error(f"Upload error for {uploaded_file.name}: {str(e)}", exc_info=True)
                    try:
                        doc_service.db.rollback()
                    except:
                        pass
                    st.sidebar.error(f"❌ {uploaded_file.name}: {str(e)}")
                    fail_count += 1

            progress.progress(1.0, text="Done!")

            if success_count > 0:
                st.sidebar.success(f"✅ {success_count} file(s) uploaded successfully!")
                # Clear cached summary so it regenerates
                st.session_state.pop("doc_summary", None)
                st.session_state.pop("summary_feedback_given", None)
                st.session_state.pop("summary_feedback_doc_count", None)
                # Increment uploader key to clear file selection
                st.session_state["uploader_key"] = st.session_state.get("uploader_key", 0) + 1
            if fail_count > 0:
                st.sidebar.warning(f"⚠️ {fail_count} file(s) failed")

            st.rerun()

    # List documents section
    st.sidebar.subheader("My Documents")

    col1, col2 = st.sidebar.columns([3, 1])
    with col2:
        if st.button("🔄", help="Refresh documents", key="refresh_docs"):
            st.rerun()

    try:
        if "deleted_docs" not in st.session_state:
            st.session_state.deleted_docs = set()

        documents = doc_service.list_documents(user_id)

        active_documents = [
            doc for doc in documents
            if str(doc['document_id']) not in st.session_state.deleted_docs
        ]

        if not active_documents:
            st.sidebar.info("🔭 No documents uploaded yet.\n\nUpload a file above to get started!")
        else:
            st.sidebar.markdown(f"**Total: {len(active_documents)} document(s)**")

            for idx, doc in enumerate(active_documents):
                doc_id_str = str(doc['document_id'])
                file_icon = _get_file_icon(doc['filename'])
                display_name = doc['filename'][:40] + ('...' if len(doc['filename']) > 40 else '')

                with st.sidebar.expander(f"{file_icon} {display_name}"):
                    col1, col2 = st.columns([2, 1])
                    with col1:
                        st.caption(f"📅 {doc['upload_date'].strftime('%b %d, %Y')}")
                        st.caption(f"🔗 ID: {str(doc['document_id'])[:8]}...")
                    with col2:
                        status = "✅ Ready" if doc['processed'] else "⏳ Processing"
                        st.caption(status)

                    if doc['total_chunks']:
                        st.caption(f"📊 Chunks: {doc['total_chunks']}")

                    if st.button(
                        "🗑️ Delete",
                        key=f"del_{doc['document_id']}",
                        use_container_width=True
                    ):
                        with st.spinner("Deleting document..."):
                            try:
                                success = doc_service.delete_document(doc['document_id'], user_id)
                                if success:
                                    st.session_state.deleted_docs.add(doc_id_str)
                                    st.session_state.pop("doc_summary", None)
                                    st.rerun()
                                else:
                                    st.sidebar.error("❌ Deletion failed")
                            except Exception as e:
                                logger.error(f"Delete error: {str(e)}", exc_info=True)
                                st.sidebar.error(f"❌ Failed to delete: {str(e)}")

    except Exception as e:
        logger.error(f"Error loading documents: {str(e)}", exc_info=True)
        try:
            doc_service.db.rollback()
            st.sidebar.warning(f"⚠️ Error loading documents. Please refresh: {str(e)}")
        except:
            st.sidebar.error(f"❌ Error loading documents: {str(e)}")

    st.sidebar.divider()

    # ========== FEEDBACK SECTION (always visible) ==========
    st.sidebar.markdown("### 📝 Give Feedback")

    # Toggle feedback form open/closed
    if "sidebar_feedback_open" not in st.session_state:
        st.session_state["sidebar_feedback_open"] = False

    if st.sidebar.button(
        "💬 Share your thoughts...",
        key="open_sidebar_feedback",
        use_container_width=True
    ):
        st.session_state["sidebar_feedback_open"] = not st.session_state["sidebar_feedback_open"]
        st.rerun()

    if st.session_state.get("sidebar_feedback_open"):
        with st.sidebar.form(key="sidebar_feedback_form"):
            rating = st.radio(
                "How's your experience?",
                ["😄 Excellent", "🙂 Good", "😐 Okay", "😞 Bad"],
                index=1,
                horizontal=True,
            )
            comments = st.text_area(
                "Comments (optional)",
                placeholder="Tell us what you think...",
                key="sidebar_fb_comments",
            )
            submitted = st.form_submit_button("Submit Feedback", use_container_width=True)

        if submitted:
            _send_general_feedback_email(rating=rating, comments=comments)
            st.session_state["sidebar_feedback_open"] = False
            st.sidebar.success("✅ Thanks for your feedback!")
            st.rerun()

    # ========== ACCOUNT SECTION ==========
    # st.sidebar.markdown("---")
    # st.sidebar.markdown("### Account")

    # if st.sidebar.button("🚪 Sign Out", use_container_width=True):
    #     logger.info(f"User {user_id} requested sign out")
    #     st.session_state["force_logout"] = True
    #     st.rerun()