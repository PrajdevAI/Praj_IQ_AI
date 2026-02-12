"""Feedback dialog component."""

import streamlit as st
import uuid
from services.feedback_service import FeedbackService


def render_feedback_dialog(
    feedback_service: FeedbackService,
    message_id: uuid.UUID,
    session_id: uuid.UUID
):
    """
    Render feedback dialog after 4th response.
    
    Args:
        feedback_service: Feedback service instance
        message_id: ID of message to get feedback for
        session_id: Current session ID
    """
    # Check if feedback already given
    if feedback_service.has_feedback(message_id):
        return
    
    # Check if we should show feedback (only after 4th response)
    st.markdown("---")
    st.subheader("📝 Feedback")
    st.write("Is this response helpful?")
    
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("👍 Yes", key=f"fb_yes_{message_id}"):
            feedback_service.submit_feedback(
                message_id=message_id,
                session_id=session_id,
                rating="yes",
                user_email=st.session_state.get("user_info", {}).get("email")
            )
            st.success("Thank you for your feedback!")
            st.rerun()
    
    with col2:
        if st.button("👎 No", key=f"fb_no_{message_id}"):
            st.session_state["show_feedback_form"] = True
    
    # Show feedback form if "No" clicked
    if st.session_state.get("show_feedback_form"):
        with st.form(key=f"feedback_form_{message_id}"):
            st.write("Please help us improve:")
            comments = st.text_area(
                "What could be better?",
                placeholder="Enter your suggestions here..."
            )
            
            submit = st.form_submit_button("Submit Feedback")
            
            if submit:
                feedback_service.submit_feedback(
                    message_id=message_id,
                    session_id=session_id,
                    rating="no",
                    comments=comments if comments.strip() else None,
                    user_email=st.session_state.get("user_info", {}).get("email")
                )
                st.success("Thank you for your feedback!")
                st.session_state["show_feedback_form"] = False
                st.rerun()
