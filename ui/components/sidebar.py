"""Sidebar component for conversation and document management."""

import streamlit as st
import uuid
import logging
from datetime import datetime
from services.document_service import DocumentService
from services.chat_service import ChatService
from models.database_models import ChatSession

logger = logging.getLogger(__name__)


def render_sidebar(doc_service: DocumentService, chat_service: ChatService, user_id: uuid.UUID):
    """
    Render sidebar with conversation management and document upload/management.
    
    Args:
        doc_service: Document service instance
        chat_service: Chat service instance
        user_id: Current user ID
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
                # Auto-title will be set from first message
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
                
                # Format timestamp
                if last_msg_at:
                    time_str = last_msg_at.strftime("%b %d, %H:%M")
                else:
                    time_str = "Just now"
                
                # Highlight current session
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
                            # Mark as deleted (soft delete)
                            chat_service.db.query(ChatSession).filter(
                                ChatSession.session_id == uuid.UUID(session_id)
                            ).update({"is_deleted": True})
                            chat_service.db.commit()
                            
                            # If deleting current conversation, switch to another
                            if is_current and sessions:
                                for s in sessions:
                                    if s["session_id"] != session_id:
                                        st.session_state["current_session_id"] = s["session_id"]
                                        break
                            
                            st.success("✅ Conversation deleted")
                            st.rerun()
                        except Exception as e:
                            logger.error(f"Error deleting conversation: {str(e)}", exc_info=True)
                            st.error(f"❌ Delete failed: {str(e)}")
    
    except Exception as e:
        logger.error(f"Error loading conversations: {str(e)}", exc_info=True)
        st.sidebar.warning(f"⚠️ Error loading conversations: {str(e)}")
    
    st.sidebar.divider()
    
    # ========== DOCUMENTS SECTION ==========
    st.sidebar.title("📄 Documents")
    
    # Document upload section
    st.sidebar.subheader("Upload PDF")
    uploaded_file = st.sidebar.file_uploader(
        "Choose a PDF file",
        type=['pdf'],
        help="Max 50MB per file",
        key="pdf_uploader"
    )
    
    if uploaded_file is not None:
        if st.sidebar.button("Upload", key="upload_btn"):
            try:
                with st.spinner("Uploading and processing document..."):
                    file_bytes = uploaded_file.read()
                    filename = uploaded_file.name
                    
                    document = doc_service.upload_document(
                        file_bytes=file_bytes,
                        filename=filename,
                        user_id=user_id
                    )
                    
                    st.sidebar.success(f"✅ {filename} uploaded successfully!")
                    st.rerun()
                    
            except ValueError as e:
                # Validation errors (duplicates, invalid file, etc.)
                st.sidebar.error(f"❌ {str(e)}")
            except RuntimeError as e:
                # S3 or processing errors
                st.sidebar.error(f"❌ {str(e)}")
            except Exception as e:
                logger.error(f"Upload error: {str(e)}", exc_info=True)
                # Try to rollback session if available
                try:
                    doc_service.db.rollback()
                except:
                    pass
                st.sidebar.error(f"❌ Upload failed: {str(e)}")
    
    # List documents section
    st.sidebar.subheader("My Documents")
    
    # Add refresh button
    col1, col2 = st.sidebar.columns([3, 1])
    with col2:
        if st.button("🔄", help="Refresh documents", key="refresh_docs"):
            st.rerun()
    
    try:
        # Initialize deleted docs tracking in session state
        if "deleted_docs" not in st.session_state:
            st.session_state.deleted_docs = set()
        
        documents = doc_service.list_documents(user_id)
        
        # Filter out deleted documents
        active_documents = [
            doc for doc in documents 
            if str(doc['document_id']) not in st.session_state.deleted_docs
        ]
        
        if not active_documents:
            st.sidebar.info("📭 No documents uploaded yet.\n\nUpload a PDF above to get started!")
        else:
            st.sidebar.markdown(f"**Total: {len(active_documents)} document(s)**")
            
            # Display documents in a cleaner way
            for idx, doc in enumerate(active_documents):
                doc_id_str = str(doc['document_id'])
                with st.sidebar.expander(f"📄 {doc['filename'][:40]}{'...' if len(doc['filename']) > 40 else ''}"):
                    # Document details
                    col1, col2 = st.columns([2, 1])
                    with col1:
                        st.caption(f"📅 {doc['upload_date'].strftime('%b %d, %Y')}")
                        st.caption(f"🔗 ID: {str(doc['document_id'])[:8]}...")
                    with col2:
                        status = "✅ Ready" if doc['processed'] else "⏳ Processing"
                        st.caption(status)
                    
                    if doc['total_chunks']:
                        st.caption(f"📊 Chunks: {doc['total_chunks']}")
                    
                    # Delete button
                    if st.button(
                        "🗑️ Delete",
                        key=f"del_{doc['document_id']}",
                        use_container_width=True
                    ):
                        with st.spinner("Deleting document from S3, vectors, and database..."):
                            try:
                                success = doc_service.delete_document(doc['document_id'], user_id)
                                if success:
                                    # Track deleted document and remove from UI
                                    st.session_state.deleted_docs.add(doc_id_str)
                                    st.sidebar.success("✅ Document deleted permanently")
                                else:
                                    st.sidebar.error("❌ Deletion failed - document still in use")
                            except Exception as e:
                                logger.error(f"Delete error: {str(e)}", exc_info=True)
                                st.sidebar.error(f"❌ Failed to delete: {str(e)}")
    
    except Exception as e:
        logger.error(f"Error loading documents: {str(e)}", exc_info=True)
        # Try to recover session from bad state
        try:
            doc_service.db.rollback()
            st.sidebar.warning(f"⚠️ Error loading documents (session recovered). Please refresh: {str(e)}")
        except:
            st.sidebar.error(f"❌ Error loading documents (session corrupted): {str(e)}")
    
    # ========== ACCOUNT SECTION ==========
    st.sidebar.markdown("---")
    st.sidebar.markdown("### Account")
    
    if st.sidebar.button("🚪 Sign Out", use_container_width=True):
        logger.info(f"User {user_id} requested sign out")
        st.session_state["force_logout"] = True
        st.rerun()


