"""Session management and timeout handling."""

import streamlit as st
import time
import logging
from config.settings import settings

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages user session timeout and activity tracking."""
    
    @staticmethod
    def update_activity():
        """Update last activity timestamp."""
        st.session_state["last_activity"] = time.time()
    
    @staticmethod
    def check_timeout() -> bool:
        """
        Check if session has timed out due to inactivity.
        
        Returns:
            True if session has timed out, False otherwise
        """
        if "last_activity" not in st.session_state:
            st.session_state["last_activity"] = time.time()
            return False
        
        last_activity = st.session_state["last_activity"]
        current_time = time.time()
        
        # Calculate time since last activity in minutes
        inactive_time = (current_time - last_activity) / 60
        
        timeout_minutes = settings.SESSION_TIMEOUT_MINUTES
        
        if inactive_time > timeout_minutes:
            logger.info(f"Session timed out after {inactive_time:.2f} minutes of inactivity")
            return True
        
        return False
    
    @staticmethod
    def get_remaining_time() -> float:
        """
        Get remaining time before session timeout.
        
        Returns:
            Remaining time in minutes
        """
        if "last_activity" not in st.session_state:
            return settings.SESSION_TIMEOUT_MINUTES
        
        last_activity = st.session_state["last_activity"]
        current_time = time.time()
        
        inactive_time = (current_time - last_activity) / 60
        remaining = settings.SESSION_TIMEOUT_MINUTES - inactive_time
        
        return max(0, remaining)
    
    @staticmethod
    def clear_session():
        """Clear all session data."""
        keys_to_clear = list(st.session_state.keys())
        for key in keys_to_clear:
            del st.session_state[key]
        
        logger.info("Session cleared")


def check_session_timeout() -> bool:
    """
    Convenience function to check session timeout.
    
    Returns:
        True if session has timed out, False otherwise
    """
    session_manager = SessionManager()
    
    if session_manager.check_timeout():
        # Clear session
        session_manager.clear_session()
        return True
    
    # Update activity
    session_manager.update_activity()
    return False


def display_session_timer():
    """Display remaining session time in the UI."""
    session_manager = SessionManager()
    remaining = session_manager.get_remaining_time()
    
    if remaining > 0:
        minutes = int(remaining)
        seconds = int((remaining - minutes) * 60)
        
        if minutes < 1:
            st.sidebar.warning(f"⏱️ Session expires in {seconds}s")
        else:
            st.sidebar.info(f"⏱️ Session active: {minutes}m {seconds}s remaining")
    else:
        st.sidebar.error("⏱️ Session expired")
