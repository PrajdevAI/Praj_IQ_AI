"""Chat interface component."""

import streamlit as st
import uuid
import logging
from services.chat_service import ChatService
from services.rag_service import RAGService
from config.settings import settings
from models.database_models import ChatSession

logger = logging.getLogger(__name__)


def render_chat_interface(
    chat_service: ChatService,
    rag_service: RAGService,
    session_id: uuid.UUID
) -> list:
    """
    Render chat interface with auto-titling on first message.
    
    Args:
        chat_service: Chat service instance
        rag_service: RAG service instance
        session_id: Current session ID
        
    Returns:
        List of chat messages
    """
    # Get chat history
    chat_history = chat_service.get_chat_history(session_id)
    
    # Display chat messages
    for msg in chat_history:
        with st.chat_message(msg["role"]):
            st.write(msg["text"])
    
    # Chat input
    if prompt := st.chat_input("Ask a question about your documents..."):
        # Display user message
        with st.chat_message("user"):
            st.write(prompt)
        
        # Save user message (no metadata)
        chat_service.add_message(
            conversation_id=session_id,
            role="user",
            content=prompt
        )
        
        # Auto-title session on first user message
        msg_count = chat_service.count_assistant_responses(session_id)
        if msg_count == 0:  # First interaction - title from this first message
            chat_service.auto_title_session(session_id)
        
        # Generate response
        assistant_response = None
        retrieved_chunk_ids = None
        
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                try:
                    assistant_response, retrieved_chunk_ids = rag_service.chat(prompt)
                    st.write(assistant_response)
                except Exception as e:
                    logger.error(f"RAG error: {str(e)}", exc_info=True)
                    st.error(f"❌ Failed to generate response: {str(e)}")
                    assistant_response = f"Error: {str(e)}"
                    retrieved_chunk_ids = []
        
        # Save assistant message with metadata (chunk IDs only, NOT chunk text)
        if assistant_response:
            metadata = None
            if retrieved_chunk_ids:
                # Store only chunk IDs in metadata, never raw chunk text
                metadata = {
                    "retrieved_chunk_ids": [str(cid) for cid in retrieved_chunk_ids],
                    "model_used": settings.BEDROCK_LLM_MODEL
                }
            
            try:
                chat_service.add_message(
                    conversation_id=session_id,
                    role="assistant",
                    content=assistant_response,
                    metadata_json=metadata
                )
            except Exception as e:
                logger.error(f"Error saving assistant message: {str(e)}", exc_info=True)
        
        st.rerun()
    
    # Chat controls
    # col1, col2, col3 = st.columns([1, 1, 2])
    
    # with col1:
    #     if st.button("🗑️ Clear Chat"):
    #         try:
    #             chat_service.delete_session(session_id)
    #             logger.info(f"Session {session_id} deleted")
    #         except Exception as e:
    #             logger.error(f"Error clearing chat: {str(e)}", exc_info=True)
    #             st.error(f"❌ Failed to clear chat: {str(e)}")
    
    # with col2:
    #     def create_new_conversation():
    #         """Create new conversation and set as active (callback)."""
    #         try:
    #             new_session = chat_service.create_session()
    #             st.session_state["current_session_id"] = str(new_session.session_id)
    #             logger.info(f"New conversation created: {new_session.session_id}")
    #         except Exception as e:
    #             logger.error(f"Error creating conversation: {str(e)}", exc_info=True)
    #             st.error(f"❌ Failed to create conversation: {str(e)}")
        
        # st.button("🔄 New Chat", on_click=create_new_conversation, use_container_width=True)
    
    return chat_history
