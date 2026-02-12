"""Email sending utilities for feedback notifications."""

import boto3
import logging
from typing import Optional
from config.settings import settings

logger = logging.getLogger(__name__)


class EmailSender:
    """Email sender using AWS SES."""
    
    def __init__(self):
        """Initialize SES client."""
        self.ses_client = boto3.client(
            'ses',
            region_name=settings.SES_REGION,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY
        )
        self.sender_email = settings.SES_SENDER_EMAIL
        self.developer_email = settings.DEVELOPER_EMAIL
    
    def send_email(
        self,
        to_email: str,
        subject: str,
        body_text: str,
        body_html: Optional[str] = None
    ) -> bool:
        """
        Send email via AWS SES.
        
        Args:
            to_email: Recipient email address
            subject: Email subject
            body_text: Plain text body
            body_html: Optional HTML body
            
        Returns:
            True if successful, False otherwise
        """
        try:
            message = {
                'Subject': {'Data': subject},
                'Body': {
                    'Text': {'Data': body_text}
                }
            }
            
            if body_html:
                message['Body']['Html'] = {'Data': body_html}
            
            response = self.ses_client.send_email(
                Source=self.sender_email,
                Destination={'ToAddresses': [to_email]},
                Message=message
            )
            
            logger.info(f"Email sent successfully to {to_email}: {response['MessageId']}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send email: {str(e)}")
            return False
    
    def send_feedback_email(
        self,
        rating: str,
        comments: Optional[str] = None,
        user_email: Optional[str] = None,
        session_id: Optional[str] = None
    ) -> bool:
        """
        Send feedback notification to developer.
        
        Args:
            rating: Feedback rating ('yes' or 'no')
            comments: Optional user comments
            user_email: Optional user email
            session_id: Optional session ID
            
        Returns:
            True if successful
        """
        subject = f"PDF Chat Feedback: {rating.upper()}"
        
        body_text = f"""
New feedback received from Secure PDF Chat application.

Rating: {rating.upper()}
User Email: {user_email or 'Anonymous'}
Session ID: {session_id or 'N/A'}

"""
        
        if comments:
            body_text += f"""
Comments/Suggestions:
{comments}
"""
        else:
            body_text += "\nNo additional comments provided.\n"
        
        body_text += "\n---\nSecure PDF Chat Application\n"
        
        # HTML version
        body_html = f"""
<html>
<head></head>
<body>
    <h2>New Feedback Received</h2>
    <p><strong>Rating:</strong> {rating.upper()}</p>
    <p><strong>User Email:</strong> {user_email or 'Anonymous'}</p>
    <p><strong>Session ID:</strong> {session_id or 'N/A'}</p>
"""
        
        if comments:
            body_html += f"""
    <h3>Comments/Suggestions:</h3>
    <p>{comments}</p>
"""
        else:
            body_html += "<p><em>No additional comments provided.</em></p>"
        
        body_html += """
    <hr>
    <p><small>Secure PDF Chat Application</small></p>
</body>
</html>
"""
        
        return self.send_email(
            to_email=self.developer_email,
            subject=subject,
            body_text=body_text,
            body_html=body_html
        )


# Singleton instance
email_sender = EmailSender()


def send_feedback_email(
    rating: str,
    comments: Optional[str] = None,
    user_email: Optional[str] = None,
    session_id: Optional[str] = None
) -> bool:
    """
    Convenience function to send feedback email.
    
    Args:
        rating: 'yes' or 'no'
        comments: Optional improvement suggestions
        user_email: Optional user email
        session_id: Optional session ID
        
    Returns:
        True if successful
    """
    return email_sender.send_feedback_email(
        rating=rating,
        comments=comments,
        user_email=user_email,
        session_id=session_id
    )
