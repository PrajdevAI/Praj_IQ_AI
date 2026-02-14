"""Chat interface component with inline feedback every 5th response."""

import streamlit as st
import uuid
import logging
from services.chat_service import ChatService
from services.rag_service import RAGService
from config.settings import settings
from models.database_models import ChatSession

logger = logging.getLogger(__name__)

FEEDBACK_INTERVAL = 5  # Show feedback prompt every N assistant responses


def _send_inline_feedback(rating: str, msg_index: int, msg_text: str = ""):
    """Send inline chat feedback email. One-click, non-blocking."""
    first_name = st.session_state.get("_fb_first_name", "Unknown")
    last_name = st.session_state.get("_fb_last_name", "")
    email = st.session_state.get("_fb_email", "unknown")
    tenant_id = st.session_state.get("_fb_tenant_id", "unknown")

    body = (
        f"Inline Chat Feedback\n"
        f"{'=' * 40}\n\n"
        f"Tenant ID: {tenant_id}\n"
        f"First Name: {first_name}\n"
        f"Last Name: {last_name}\n"
        f"User Email: {email}\n\n"
        f"Rating: {rating}\n"
        f"Response #: {msg_index}\n\n"
        f"Message Context (truncated):\n{msg_text[:500]}\n"
    )

    try:
        import utils.email_sender as _es
        _es.email_sender.send_email(
            to_email="dev@acadiaconsultants.com",
            subject=f"Chat Feedback: {rating} from {first_name} {last_name}",
            body_text=body,
        )
        logger.info("Inline feedback sent: %s for response #%d", rating, msg_index)
    except Exception as e:
        logger.warning("Failed to send inline feedback: %s", e)


def render_chat_interface(
    chat_service: ChatService,
    rag_service: RAGService,
    session_id: uuid.UUID
) -> list:
    """
    Render chat interface with auto-titling and inline feedback.
    
    Shows 👍/👎 after every 5th assistant response. One-click sends
    feedback to dev@acadiaconsultants.com without blocking chat.
    """
    # Track which messages have already received feedback
    if "inline_feedback_given" not in st.session_state:
        st.session_state["inline_feedback_given"] = set()

    # Get chat history
    chat_history = chat_service.get_chat_history(session_id)

    # Count assistant messages for feedback interval
    assistant_count = 0

    # Display chat messages
    for msg in chat_history:
        with st.chat_message(msg["role"]):
            st.write(msg["text"])

        # Track assistant responses and show feedback at intervals
        if msg["role"] == "assistant":
            assistant_count += 1

            # Show feedback after every Nth assistant response
            if (
                assistant_count > 0
                and assistant_count % FEEDBACK_INTERVAL == 0
                and assistant_count not in st.session_state["inline_feedback_given"]
            ):
                fb_col1, fb_col2, fb_col3 = st.columns([1, 1, 10])
                with fb_col1:
                    if st.button("👍", key=f"inline_like_{assistant_count}", help="Helpful"):
                        st.session_state["inline_feedback_given"].add(assistant_count)
                        _send_inline_feedback("👍 Helpful", assistant_count, msg["text"])
                        st.rerun()
                with fb_col2:
                    if st.button("👎", key=f"inline_dislike_{assistant_count}", help="Not helpful"):
                        st.session_state["inline_feedback_given"].add(assistant_count)
                        _send_inline_feedback("👎 Not helpful", assistant_count, msg["text"])
                        st.rerun()
                with fb_col3:
                    st.caption("_How was this response?_")

            # Show a small "✓ Thanks!" where feedback was already given
            elif (
                assistant_count > 0
                and assistant_count % FEEDBACK_INTERVAL == 0
                and assistant_count in st.session_state["inline_feedback_given"]
            ):
                st.caption("✅ _Feedback received — thanks!_")

    # Chat input
    if prompt := st.chat_input("Ask a question about your documents..."):
        with st.chat_message("user"):
            st.write(prompt)

        chat_service.add_message(
            conversation_id=session_id,
            role="user",
            content=prompt
        )

        # Auto-title session on first user message
        msg_count = chat_service.count_assistant_responses(session_id)
        if msg_count == 0:
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

        # Save assistant message
        if assistant_response:
            metadata = None
            if retrieved_chunk_ids:
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

    return chat_history