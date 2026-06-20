import os
import re
from datetime import datetime, timedelta
from html import escape
from urllib.parse import quote
from typing import Optional
import resend
from dotenv import load_dotenv
import secrets
from jose import JWTError, jwt

load_dotenv()

# Initialize Resend
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
RESEND_FROM_EMAIL = os.getenv("RESEND_FROM_EMAIL", "noreply@rilono.com")
RESEND_TRANSACTIONAL_FROM_EMAIL = os.getenv("RESEND_TRANSACTIONAL_FROM_EMAIL", RESEND_FROM_EMAIL)
RESEND_FROM_NAME = os.getenv("RESEND_FROM_NAME", "Rilono")
# For development: use Resend's test email (delivered@resend.dev) which doesn't require domain verification
USE_TEST_EMAIL = os.getenv("USE_TEST_EMAIL", "false").lower() == "true"
DEV_MODE = os.getenv("DEV_MODE", "false").lower() == "true"
DEFAULT_FOUNDER_ALERT_RECIPIENTS = ["gauravbr@rilono.com", "kushalb@rilono.com"]

if RESEND_API_KEY:
    resend.api_key = RESEND_API_KEY
else:
    print("WARNING: RESEND_API_KEY not found. Email functionality will be disabled.")

DEFAULT_PUBLIC_BASE_URL = (os.getenv("BASE_URL", "https://rilono.com").strip() or "https://rilono.com")
SECRET_KEY = os.getenv("SECRET_KEY", "")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
EMAIL_NOTIFICATIONS_UNSUB_TOKEN_HOURS = int(
    os.getenv("EMAIL_NOTIFICATIONS_UNSUB_TOKEN_HOURS", "720")  # 30 days
)


def _parse_founder_alert_recipients(raw_value: str | None) -> list[str]:
    items = [item.strip().lower() for item in str(raw_value or "").split(",") if item.strip()]
    deduped: list[str] = []
    for item in items:
        if item not in deduped:
            deduped.append(item)
    return deduped


FOUNDER_ALERT_RECIPIENTS = _parse_founder_alert_recipients(
    os.getenv("FOUNDER_ALERT_RECIPIENTS", ",".join(DEFAULT_FOUNDER_ALERT_RECIPIENTS))
)
if not FOUNDER_ALERT_RECIPIENTS:
    FOUNDER_ALERT_RECIPIENTS = DEFAULT_FOUNDER_ALERT_RECIPIENTS.copy()


def _resolve_resend_from_email() -> str:
    if USE_TEST_EMAIL or DEV_MODE:
        print("DEV MODE: Using test email sender (delivered@resend.dev)")
        return "delivered@resend.dev"
    return RESEND_FROM_EMAIL


def _resolve_transactional_from_email() -> str:
    """Auth/security emails must not depend on notification unsubscribe state."""
    if USE_TEST_EMAIL or DEV_MODE:
        print("DEV MODE: Using test email sender (delivered@resend.dev)")
        return "delivered@resend.dev"
    return RESEND_TRANSACTIONAL_FROM_EMAIL


def _extract_resend_email_id(email_response) -> Optional[str]:
    if isinstance(email_response, dict):
        return email_response.get("id")
    if email_response and hasattr(email_response, "id"):
        return email_response.id
    return None


def generate_email_notifications_unsubscribe_token(
    email: str,
    expires_hours: int = EMAIL_NOTIFICATIONS_UNSUB_TOKEN_HOURS,
) -> str:
    payload = {
        "sub": (email or "").strip().lower(),
        "purpose": "email_notifications_unsubscribe",
        "exp": datetime.utcnow() + timedelta(hours=max(1, int(expires_hours))),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def verify_email_notifications_unsubscribe_token(token: str) -> Optional[str]:
    token_value = (token or "").strip()
    if not token_value:
        return None
    try:
        payload = jwt.decode(token_value, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None

    purpose = str(payload.get("purpose") or "").strip().lower()
    if purpose != "email_notifications_unsubscribe":
        return None
    email = str(payload.get("sub") or "").strip().lower()
    if not email or "@" not in email:
        return None
    return email


def build_email_notifications_unsubscribe_url(email: str, base_url: str = DEFAULT_PUBLIC_BASE_URL) -> str:
    token = generate_email_notifications_unsubscribe_token(email=email)
    return f"{base_url.rstrip('/')}/unsubscribe-email?token={token}"


def generate_verification_token() -> str:
    """Generate a secure random token for email verification."""
    return secrets.token_urlsafe(32)


def send_verification_email(
    email: str,
    verification_token: str,
    base_url: str = DEFAULT_PUBLIC_BASE_URL,
    expires_in_hours: int = 24,
) -> bool:
    """
    Send email verification email using Resend.
    
    Args:
        email: Recipient email address
        verification_token: Token for verification
        base_url: Base URL of the application (for verification link)
        expires_in_hours: Verification link expiry in hours
    
    Returns:
        bool: True if email was sent successfully, False otherwise
    """
    if not RESEND_API_KEY:
        print(f"ERROR: Cannot send verification email - Resend not configured")
        return False
    
    verification_link = f"{base_url}/verify-email?token={verification_token}"
    
    # HTML email template
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Verify Your Email - Rilono</title>
    </head>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
        <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; text-align: center; border-radius: 10px 10px 0 0;">
            <h1 style="color: white; margin: 0; font-size: 28px;">Welcome to Rilono!</h1>
        </div>
        
        <div style="background: #ffffff; padding: 40px; border: 1px solid #e5e7eb; border-top: none; border-radius: 0 0 10px 10px;">
            <p style="font-size: 16px; margin-bottom: 20px;">Hi there,</p>
            
            <p style="font-size: 16px; margin-bottom: 20px;">
                Thank you for signing up for Rilono! To complete your registration and start using the platform,
                please verify your email address by clicking the button below:
            </p>
            
            <div style="text-align: center; margin: 30px 0;">
                <a href="{verification_link}" 
                   style="display: inline-block; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                          color: white; padding: 14px 28px; text-decoration: none; border-radius: 8px; 
                          font-weight: 600; font-size: 16px;">
                    Verify Email Address
                </a>
            </div>
            
            <p style="font-size: 14px; color: #6b7280; margin-top: 30px;">
                Or copy and paste this link into your browser:
            </p>
            <p style="font-size: 12px; color: #9ca3af; word-break: break-all; background: #f9fafb; padding: 10px; border-radius: 5px;">
                {verification_link}
            </p>
            
            <p style="font-size: 14px; color: #6b7280; margin-top: 30px;">
                This verification link will expire in {expires_in_hours} hours. If you didn't create an account with Rilono,
                please ignore this email.
            </p>
        </div>
        
        <div style="text-align: center; margin-top: 30px; padding: 20px; color: #9ca3af; font-size: 12px;">
            <p style="margin: 0;">© 2025 Rilono. All rights reserved.</p>
            <p style="margin: 5px 0 0 0;">Your F1 Visa Documentation Companion</p>
        </div>
    </body>
    </html>
    """
    
    # Plain text version
    text_content = f"""
    Welcome to Rilono!
    
    Thank you for signing up! To complete your registration, please verify your email address by clicking the link below:
    
    {verification_link}
    
    This verification link will expire in {expires_in_hours} hours. If you didn't create an account with Rilono, please ignore this email.
    
    © 2025 Rilono. All rights reserved.
    """
    
    try:
        from_email = _resolve_transactional_from_email()
        
        params = {
            "from": f"{RESEND_FROM_NAME} <{from_email}>",
            "to": [email],
            "subject": "Verify Your Email - Rilono",
            "html": html_content,
            "text": text_content,
        }
        
        email_response = resend.Emails.send(params)
        
        # Check if email was sent successfully
        # Resend response can be a dict with 'id' key or an object with 'id' attribute
        email_id = None
        if isinstance(email_response, dict):
            email_id = email_response.get('id')
        elif email_response and hasattr(email_response, 'id'):
            email_id = email_response.id
        
        if email_id:
            print(f"Verification email sent successfully to {email} (ID: {email_id})")
            if USE_TEST_EMAIL or DEV_MODE:
                print(f"  NOTE: Using test email sender. Check Resend dashboard for email preview.")
            return True
        else:
            print(f"Failed to send verification email to {email}. Response: {email_response}")
            return False
            
    except Exception as e:
        error_msg = str(e)
        print(f"Error sending verification email to {email}: {error_msg}")
        
        # If domain not verified error, suggest using test email mode
        if "domain is not verified" in error_msg.lower() or "not verified" in error_msg.lower():
            print("\n💡 TIP: For development/testing, add to your .env file:")
            print("   USE_TEST_EMAIL=true")
            print("   This will use Resend's test email sender (delivered@resend.dev)")
            print("   which doesn't require domain verification.\n")
        
        return False


def send_password_reset_email(email: str, reset_token: str, base_url: str = DEFAULT_PUBLIC_BASE_URL) -> bool:
    """
    Send password reset email using Resend.
    
    Args:
        email: Recipient email address
        reset_token: Token for password reset
        base_url: Base URL of the application (for reset link)
    
    Returns:
        bool: True if email was sent successfully, False otherwise
    """
    if not RESEND_API_KEY:
        print(f"ERROR: Cannot send password reset email - Resend not configured")
        return False
    
    reset_link = f"{base_url}/reset-password?token={reset_token}"
    
    # HTML email template
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Reset Your Password - Rilono</title>
    </head>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
        <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; text-align: center; border-radius: 10px 10px 0 0;">
            <h1 style="color: white; margin: 0; font-size: 28px;">Password Reset Request</h1>
        </div>
        
        <div style="background: #ffffff; padding: 40px; border: 1px solid #e5e7eb; border-top: none; border-radius: 0 0 10px 10px;">
            <p style="font-size: 16px; margin-bottom: 20px;">Hi there,</p>
            
            <p style="font-size: 16px; margin-bottom: 20px;">
                We received a request to reset your password for your Rilono account. 
                Click the button below to reset your password:
            </p>
            
            <div style="text-align: center; margin: 30px 0;">
                <a href="{reset_link}" 
                   style="display: inline-block; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                          color: white; padding: 14px 28px; text-decoration: none; border-radius: 8px; 
                          font-weight: 600; font-size: 16px;">
                    Reset Password
                </a>
            </div>
            
            <p style="font-size: 14px; color: #6b7280; margin-top: 30px;">
                Or copy and paste this link into your browser:
            </p>
            <p style="font-size: 12px; color: #9ca3af; word-break: break-all; background: #f9fafb; padding: 10px; border-radius: 5px;">
                {reset_link}
            </p>
            
            <p style="font-size: 14px; color: #6b7280; margin-top: 30px;">
                <strong>This link will expire in 1 hour.</strong> If you didn't request a password reset, 
                please ignore this email. Your password will remain unchanged.
            </p>
            
            <p style="font-size: 14px; color: #ef4444; margin-top: 20px; padding: 15px; background: #fef2f2; border-left: 4px solid #ef4444; border-radius: 4px;">
                <strong>Security Tip:</strong> If you didn't request this password reset, please secure your account immediately.
            </p>
        </div>
        
        <div style="text-align: center; margin-top: 30px; padding: 20px; color: #9ca3af; font-size: 12px;">
            <p style="margin: 0;">© 2025 Rilono. All rights reserved.</p>
            <p style="margin: 5px 0 0 0;">Your Student Marketplace</p>
        </div>
    </body>
    </html>
    """
    
    # Plain text version
    text_content = f"""
    Password Reset Request - Rilono
    
    We received a request to reset your password. Click the link below to reset it:
    
    {reset_link}
    
    This link will expire in 1 hour. If you didn't request a password reset, please ignore this email.
    
    © 2025 Rilono. All rights reserved.
    """
    
    try:
        from_email = _resolve_transactional_from_email()
        
        params = {
            "from": f"{RESEND_FROM_NAME} <{from_email}>",
            "to": [email],
            "subject": "Reset Your Password - Rilono",
            "html": html_content,
            "text": text_content,
        }
        
        email_response = resend.Emails.send(params)
        
        # Check if email was sent successfully
        # Resend response can be a dict with 'id' key or an object with 'id' attribute
        email_id = None
        if isinstance(email_response, dict):
            email_id = email_response.get('id')
        elif email_response and hasattr(email_response, 'id'):
            email_id = email_response.id
        
        if email_id:
            print(f"Password reset email sent successfully to {email} (ID: {email_id})")
            return True
        else:
            print(f"Failed to send password reset email to {email}. Response: {email_response}")
            return False
            
    except Exception as e:
        error_msg = str(e)
        print(f"Error sending password reset email to {email}: {error_msg}")
        
        # If domain not verified error, suggest using test email mode
        if "domain is not verified" in error_msg.lower() or "not verified" in error_msg.lower():
            print("\n💡 TIP: For development/testing, add to your .env file:")
            print("   USE_TEST_EMAIL=true")
            print("   This will use Resend's test email sender (delivered@resend.dev)")
            print("   which doesn't require domain verification.\n")
        
        return False


def send_university_change_email(email: str, new_university: str, change_token: str, base_url: str = DEFAULT_PUBLIC_BASE_URL) -> bool:
    """
    Send university change verification email using Resend.
    
    Args:
        email: New email address to verify
        new_university: Name of the new university
        change_token: Token for verification
        base_url: Base URL of the application (for verification link)
    
    Returns:
        bool: True if email was sent successfully, False otherwise
    """
    if not RESEND_API_KEY:
        print(f"ERROR: Cannot send university change email - Resend not configured")
        return False
    
    verification_link = f"{base_url}/verify-university-change?token={change_token}"
    
    # HTML email template
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Verify University Change - Rilono</title>
    </head>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
        <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; text-align: center; border-radius: 10px 10px 0 0;">
            <h1 style="color: white; margin: 0; font-size: 28px;">🎓 University Change Request</h1>
        </div>
        
        <div style="background: #ffffff; padding: 40px; border: 1px solid #e5e7eb; border-top: none; border-radius: 0 0 10px 10px;">
            <p style="font-size: 16px; margin-bottom: 20px;">Hi there,</p>
            
            <p style="font-size: 16px; margin-bottom: 20px;">
                You've requested to change your university to <strong>{new_university}</strong> on Rilono. 
                To confirm this change, please verify your new university email by clicking the button below:
            </p>
            
            <div style="text-align: center; margin: 30px 0;">
                <a href="{verification_link}" 
                   style="display: inline-block; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                          color: white; padding: 14px 28px; text-decoration: none; border-radius: 8px; 
                          font-weight: 600; font-size: 16px;">
                    Verify University Change
                </a>
            </div>
            
            <div style="background: #f0f9ff; border-left: 4px solid #667eea; padding: 15px; margin: 20px 0; border-radius: 0 5px 5px 0;">
                <p style="margin: 0; font-size: 14px; color: #1e40af;">
                    <strong>New University:</strong> {new_university}<br>
                    <strong>New Email:</strong> {email}
                </p>
            </div>
            
            <p style="font-size: 14px; color: #6b7280; margin-top: 30px;">
                Or copy and paste this link into your browser:
            </p>
            <p style="font-size: 12px; color: #9ca3af; word-break: break-all; background: #f9fafb; padding: 10px; border-radius: 5px;">
                {verification_link}
            </p>
            
            <p style="font-size: 14px; color: #6b7280; margin-top: 30px;">
                This verification link will expire in 24 hours. If you didn't request this change, 
                please ignore this email - your account will remain unchanged.
            </p>
        </div>
        
        <div style="text-align: center; margin-top: 30px; padding: 20px; color: #9ca3af; font-size: 12px;">
            <p style="margin: 0;">© 2026 Rilono. All rights reserved.</p>
            <p style="margin: 5px 0 0 0;">Your F1 Student Visa Assistant</p>
        </div>
    </body>
    </html>
    """
    
    # Plain text version
    text_content = f"""
    University Change Request - Rilono
    
    You've requested to change your university to {new_university} on Rilono.
    
    To confirm this change, click the link below:
    
    {verification_link}
    
    New University: {new_university}
    New Email: {email}
    
    This link will expire in 24 hours. If you didn't request this change, please ignore this email.
    
    © 2026 Rilono. All rights reserved.
    """
    
    try:
        from_email = _resolve_transactional_from_email()
        
        params = {
            "from": f"{RESEND_FROM_NAME} <{from_email}>",
            "to": [email],
            "subject": f"Verify University Change to {new_university} - Rilono",
            "html": html_content,
            "text": text_content,
        }
        
        email_response = resend.Emails.send(params)
        
        # Check if email was sent successfully
        email_id = None
        if isinstance(email_response, dict):
            email_id = email_response.get('id')
        elif email_response and hasattr(email_response, 'id'):
            email_id = email_response.id
        
        if email_id:
            print(f"University change verification email sent successfully to {email} (ID: {email_id})")
            return True
        else:
            print(f"Failed to send university change email to {email}. Response: {email_response}")
            return False
            
    except Exception as e:
        error_msg = str(e)
        print(f"Error sending university change email to {email}: {error_msg}")
        
        if "domain is not verified" in error_msg.lower() or "not verified" in error_msg.lower():
            print("\n💡 TIP: For development/testing, add to your .env file:")
            print("   USE_TEST_EMAIL=true")
        
        return False


def send_contact_form_email(
    name: str,
    email: str,
    subject: str,
    message: str,
    user_type: str = "visitor"
) -> bool:
    """
    Send contact form submission to contact@rilono.com.
    
    Args:
        name: Sender's name
        email: Sender's email address (for reply)
        subject: Message subject
        message: Message content
        user_type: Type of user (visitor, student, etc.)
    
    Returns:
        bool: True if email was sent successfully, False otherwise
    """
    if not RESEND_API_KEY:
        print(f"ERROR: Cannot send contact form email - Resend not configured")
        return False

    sender_name = re.sub(r"[\r\n]+", " ", (name or "").strip()) or "Unknown"
    sender_email = re.sub(r"[\r\n]+", " ", (email or "").strip())
    sender_subject = re.sub(r"[\r\n]+", " ", (subject or "").strip()) or "(No subject)"
    sender_message = (message or "").strip()
    sender_user_type = re.sub(r"[\r\n]+", " ", (user_type or "visitor").strip()) or "visitor"

    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", sender_email):
        print("ERROR: Invalid sender email in contact form payload")
        return False

    safe_name = escape(sender_name)
    safe_email = escape(sender_email)
    safe_subject = escape(sender_subject)
    safe_message = escape(sender_message)
    safe_user_type = escape(sender_user_type.title())
    safe_reply_subject = quote(f"Re: {sender_subject}", safe="")

    # Email to contact@rilono.com
    contact_email = "contact@rilono.com"
    
    # HTML email template for the contact form
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
                line-height: 1.6;
                color: #333;
                max-width: 600px;
                margin: 0 auto;
                padding: 20px;
            }}
            .header {{
                background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
                color: white;
                padding: 30px;
                border-radius: 12px 12px 0 0;
                text-align: center;
            }}
            .content {{
                background: #f8fafc;
                padding: 30px;
                border: 1px solid #e2e8f0;
                border-top: none;
                border-radius: 0 0 12px 12px;
            }}
            .field {{
                margin-bottom: 20px;
                padding: 15px;
                background: white;
                border-radius: 8px;
                border: 1px solid #e2e8f0;
            }}
            .field-label {{
                font-weight: 600;
                color: #6366f1;
                font-size: 12px;
                text-transform: uppercase;
                letter-spacing: 0.5px;
                margin-bottom: 5px;
            }}
            .field-value {{
                color: #1e293b;
                font-size: 15px;
            }}
            .message-content {{
                white-space: pre-wrap;
                background: white;
                padding: 20px;
                border-radius: 8px;
                border: 1px solid #e2e8f0;
                margin-top: 10px;
            }}
            .reply-btn {{
                display: inline-block;
                background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
                color: white;
                padding: 12px 24px;
                text-decoration: none;
                border-radius: 8px;
                font-weight: 600;
                margin-top: 20px;
            }}
            .footer {{
                text-align: center;
                margin-top: 20px;
                color: #64748b;
                font-size: 12px;
            }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1 style="margin: 0; font-size: 24px;">📬 New Contact Form Submission</h1>
            <p style="margin: 10px 0 0 0; opacity: 0.9;">Someone reached out through Rilono</p>
        </div>
        <div class="content">
            <div class="field">
                <div class="field-label">From</div>
                <div class="field-value">{safe_name}</div>
            </div>
            <div class="field">
                <div class="field-label">Email</div>
                <div class="field-value"><a href="mailto:{safe_email}">{safe_email}</a></div>
            </div>
            <div class="field">
                <div class="field-label">User Type</div>
                <div class="field-value">{safe_user_type}</div>
            </div>
            <div class="field">
                <div class="field-label">Subject</div>
                <div class="field-value">{safe_subject}</div>
            </div>
            <div class="field">
                <div class="field-label">Message</div>
                <div class="message-content">{safe_message}</div>
            </div>
            
            <div style="text-align: center;">
                <a href="mailto:{safe_email}?subject={safe_reply_subject}" class="reply-btn">Reply to {safe_name}</a>
            </div>
        </div>
        <div class="footer">
            <p>This message was sent via the Rilono contact form.</p>
        </div>
    </body>
    </html>
    """
    
    try:
        from_email = f"{RESEND_FROM_NAME} <{RESEND_FROM_EMAIL}>"
        
        params = {
            "from": from_email,
            "to": [contact_email],
            "reply_to": sender_email,  # So you can reply directly to the sender
            "subject": f"[Rilono Contact] {sender_subject}",
            "html": html_content
        }
        
        email_response = resend.Emails.send(params)
        
        if email_response and email_response.get("id"):
            print(f"✓ Contact form email sent successfully (ID: {email_response['id']})")
            return True
        else:
            print(f"✗ Failed to send contact form email: {email_response}")
            return False
            
    except Exception as e:
        error_msg = str(e)
        print(f"Error sending contact form email: {error_msg}")
        return False


def _format_datetime_for_subscription_email(value: Optional[datetime]) -> str:
    if not value:
        return "N/A"
    return value.strftime("%b %d, %Y %I:%M %p UTC")


def _format_amount_for_subscription_email(amount_paise: Optional[int], currency: str) -> str:
    if amount_paise is None:
        return "N/A"
    normalized_currency = (currency or "INR").upper()
    amount = amount_paise / 100
    symbols = {
        "INR": "₹",
        "USD": "$",
        "EUR": "€",
        "GBP": "£",
        "JPY": "¥",
    }
    symbol = symbols.get(normalized_currency, f"{normalized_currency} ")
    return f"{symbol}{amount:,.2f}"


def _subscription_plan_label(plan: str, pricing_model: Optional[str] = None) -> str:
    normalized_plan = str(plan or "").strip().lower()
    if normalized_plan != "pro":
        return (plan or "free").strip().title() or "Free"

    normalized_model = str(pricing_model or "").strip().lower()
    if normalized_model in {"pro_six_month", "pro_6_month", "pro_6month", "six_month", "6_month", "6month"}:
        return "Journey Pass"
    if normalized_model in {"pro_monthly", "pro", "monthly", ""}:
        return "Pro Monthly"
    return "Pro"


def send_subscription_change_email(
    email: str,
    full_name: Optional[str],
    event_type: str,
    plan: str,
    status: str,
    auto_renew_enabled: Optional[bool] = None,
    access_until: Optional[datetime] = None,
    next_renewal_at: Optional[datetime] = None,
    payment_amount_paise: Optional[int] = None,
    payment_currency: str = "INR",
    payment_status: Optional[str] = None,
    pricing_model: Optional[str] = None,
    base_url: str = DEFAULT_PUBLIC_BASE_URL,
    unsubscribe_url: Optional[str] = None,
) -> bool:
    """
    Send subscription/plan update email with a modern, structured template.
    """
    if not RESEND_API_KEY:
        print("ERROR: Cannot send subscription change email - Resend not configured")
        return False

    event_key = (event_type or "subscription_updated").strip().lower()
    event_content = {
        "pro_activated": {
            "subject": "Rilono Pro Activated",
            "title": "Your Pro plan is active",
            "summary": "Payment is verified and your Pro features are now unlocked.",
            "accent_bg": "#ecfdf5",
            "accent_fg": "#065f46",
        },
        "subscription_renewed": {
            "subject": "Rilono Subscription Renewed",
            "title": "Your subscription has renewed",
            "summary": "We received your latest recurring payment and your Pro access continues.",
            "accent_bg": "#eff6ff",
            "accent_fg": "#1e3a8a",
        },
        "auto_renew_cancelled": {
            "subject": "Rilono Auto-Renew Cancelled",
            "title": "Auto-renew has been turned off",
            "summary": "Your Pro plan remains active until the current access period ends.",
            "accent_bg": "#fffbeb",
            "accent_fg": "#92400e",
        },
        "downgraded_to_free": {
            "subject": "Rilono Plan Changed to Free",
            "title": "Your account is now on Free plan",
            "summary": "Your Pro access period has ended and your account is now on Free plan.",
            "accent_bg": "#fff7ed",
            "accent_fg": "#9a3412",
        },
        "payment_failed": {
            "subject": "Rilono Subscription Payment Failed",
            "title": "We could not process your payment",
            "summary": "Please update your payment method or retry to avoid service disruption.",
            "accent_bg": "#fef2f2",
            "accent_fg": "#991b1b",
        },
        "subscription_updated": {
            "subject": "Rilono Subscription Update",
            "title": "Your subscription details were updated",
            "summary": "A change was made to your subscription details.",
            "accent_bg": "#f5f3ff",
            "accent_fg": "#5b21b6",
        },
    }.get(event_key, {
        "subject": "Rilono Subscription Update",
        "title": "Your subscription details were updated",
        "summary": "A change was made to your subscription details.",
        "accent_bg": "#f5f3ff",
        "accent_fg": "#5b21b6",
    })

    plan_label = _subscription_plan_label(plan=plan, pricing_model=pricing_model)
    active_plan_label = plan_label if plan_label.lower() != "free" else "subscription"
    if event_key == "pro_activated":
        activation_subject = (
            "Rilono Journey Pass Activated" if plan_label == "Journey Pass" else "Rilono Pro Activated"
        )
        event_content = {
            **event_content,
            "subject": activation_subject,
            "title": f"Your {plan_label} is active",
            "summary": f"Payment is verified and your {active_plan_label} features are now unlocked.",
        }
    elif event_key == "subscription_renewed":
        event_content = {
            **event_content,
            "summary": f"We received your latest recurring payment and your {active_plan_label} access continues.",
        }
    elif event_key == "auto_renew_cancelled":
        event_content = {
            **event_content,
            "summary": f"Your {active_plan_label} remains active until the current access period ends.",
        }
    elif event_key == "downgraded_to_free":
        event_content = {
            **event_content,
            "summary": "Your paid subscription access has ended and your account is now on Free plan.",
        }

    safe_name = escape((full_name or "").strip() or "there")
    safe_plan = escape(plan_label)
    safe_status = escape((status or "active").strip().title())
    safe_payment_status = escape((payment_status or "N/A").strip().title())
    safe_payment_amount = escape(_format_amount_for_subscription_email(payment_amount_paise, payment_currency))
    safe_access_until = escape(_format_datetime_for_subscription_email(access_until))
    safe_next_renewal = escape(_format_datetime_for_subscription_email(next_renewal_at))
    auto_renew_text = "N/A" if auto_renew_enabled is None else ("Enabled" if auto_renew_enabled else "Disabled")
    safe_auto_renew = escape(auto_renew_text)
    manage_url = f"{base_url.rstrip('/')}/dashboard"
    safe_manage_url = escape(manage_url)
    safe_unsubscribe_url = escape((unsubscribe_url or "").strip())

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{escape(event_content['subject'])}</title>
    </head>
    <body style="margin:0;padding:0;background:#f8fafc;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f8fafc;padding:24px 12px;">
            <tr>
                <td align="center">
                    <table role="presentation" width="620" cellspacing="0" cellpadding="0" style="max-width:620px;background:#ffffff;border:1px solid #e2e8f0;border-radius:16px;overflow:hidden;">
                        <tr>
                            <td style="padding:26px 28px;background:linear-gradient(135deg,#6366f1 0%,#a855f7 100%);color:#ffffff;">
                                <div style="font-size:13px;letter-spacing:.06em;text-transform:uppercase;opacity:.95;">Rilono Subscription</div>
                                <h1 style="margin:10px 0 0 0;font-size:28px;line-height:1.2;">{escape(event_content['title'])}</h1>
                            </td>
                        </tr>
                        <tr>
                            <td style="padding:26px 28px;">
                                <p style="margin:0 0 14px 0;font-size:15px;color:#0f172a;">Hi {safe_name},</p>
                                <div style="background:{event_content['accent_bg']};color:{event_content['accent_fg']};padding:12px 14px;border-radius:10px;font-size:14px;line-height:1.5;margin-bottom:18px;">
                                    {escape(event_content['summary'])}
                                </div>
                                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:separate;border-spacing:0 10px;">
                                    <tr>
                                        <td style="width:50%;padding:12px;border:1px solid #e2e8f0;border-radius:10px;background:#f8fafc;">
                                            <div style="font-size:12px;color:#64748b;text-transform:uppercase;letter-spacing:.04em;">Plan</div>
                                            <div style="font-size:18px;font-weight:700;color:#0f172a;margin-top:4px;">{safe_plan}</div>
                                        </td>
                                        <td style="width:50%;padding:12px;border:1px solid #e2e8f0;border-radius:10px;background:#f8fafc;">
                                            <div style="font-size:12px;color:#64748b;text-transform:uppercase;letter-spacing:.04em;">Status</div>
                                            <div style="font-size:18px;font-weight:700;color:#0f172a;margin-top:4px;">{safe_status}</div>
                                        </td>
                                    </tr>
                                    <tr>
                                        <td style="padding:12px;border:1px solid #e2e8f0;border-radius:10px;background:#f8fafc;">
                                            <div style="font-size:12px;color:#64748b;text-transform:uppercase;letter-spacing:.04em;">Auto-Renew</div>
                                            <div style="font-size:16px;font-weight:600;color:#0f172a;margin-top:4px;">{safe_auto_renew}</div>
                                        </td>
                                        <td style="padding:12px;border:1px solid #e2e8f0;border-radius:10px;background:#f8fafc;">
                                            <div style="font-size:12px;color:#64748b;text-transform:uppercase;letter-spacing:.04em;">Access Until</div>
                                            <div style="font-size:16px;font-weight:600;color:#0f172a;margin-top:4px;">{safe_access_until}</div>
                                        </td>
                                    </tr>
                                    <tr>
                                        <td style="padding:12px;border:1px solid #e2e8f0;border-radius:10px;background:#f8fafc;">
                                            <div style="font-size:12px;color:#64748b;text-transform:uppercase;letter-spacing:.04em;">Next Renewal</div>
                                            <div style="font-size:16px;font-weight:600;color:#0f172a;margin-top:4px;">{safe_next_renewal}</div>
                                        </td>
                                        <td style="padding:12px;border:1px solid #e2e8f0;border-radius:10px;background:#f8fafc;">
                                            <div style="font-size:12px;color:#64748b;text-transform:uppercase;letter-spacing:.04em;">Latest Payment</div>
                                            <div style="font-size:16px;font-weight:600;color:#0f172a;margin-top:4px;">{safe_payment_amount} • {safe_payment_status}</div>
                                        </td>
                                    </tr>
                                </table>

                                <div style="text-align:center;margin-top:20px;">
                                    <a href="{safe_manage_url}" style="display:inline-block;padding:12px 22px;border-radius:10px;background:linear-gradient(135deg,#6366f1 0%,#a855f7 100%);color:#ffffff;font-size:14px;font-weight:700;text-decoration:none;">
                                        Manage Subscription
                                    </a>
                                </div>

                                <p style="margin:20px 0 0 0;font-size:13px;color:#64748b;">
                                    If this change wasn't made by you, contact us immediately at
                                    <a href="mailto:contact@rilono.com" style="color:#4f46e5;text-decoration:none;">contact@rilono.com</a>.
                                </p>
                                <p style="margin:10px 0 0 0;font-size:11px;color:#94a3b8;">
                                    {f'<a href="{safe_unsubscribe_url}" style="color:#94a3b8;text-decoration:none;">Unsubscribe from email notifications</a>' if safe_unsubscribe_url else ''}
                                </p>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
        </table>
    </body>
    </html>
    """

    unsubscribe_text_line = (
        f"Unsubscribe from email notifications: {unsubscribe_url}\n\n"
        if unsubscribe_url
        else ""
    )

    text_content = (
        f"{event_content['title']} - Rilono\n\n"
        f"Hi {full_name or 'there'},\n\n"
        f"{event_content['summary']}\n\n"
        f"Plan: {plan_label}\n"
        f"Status: {(status or 'active').title()}\n"
        f"Auto-Renew: {auto_renew_text}\n"
        f"Access Until: {_format_datetime_for_subscription_email(access_until)}\n"
        f"Next Renewal: {_format_datetime_for_subscription_email(next_renewal_at)}\n"
        f"Latest Payment: {_format_amount_for_subscription_email(payment_amount_paise, payment_currency)} • {(payment_status or 'N/A').title()}\n\n"
        f"Manage Subscription: {manage_url}\n\n"
        f"{unsubscribe_text_line}"
        "If this change wasn't made by you, contact contact@rilono.com.\n\n"
        "© 2026 Rilono. All rights reserved."
    )

    try:
        if USE_TEST_EMAIL or DEV_MODE:
            from_email = "delivered@resend.dev"
            print("DEV MODE: Using test email sender (delivered@resend.dev)")
        else:
            from_email = RESEND_FROM_EMAIL

        params = {
            "from": f"{RESEND_FROM_NAME} <{from_email}>",
            "to": [email],
            "subject": event_content["subject"],
            "html": html_content,
            "text": text_content,
        }
        email_response = resend.Emails.send(params)

        email_id = None
        if isinstance(email_response, dict):
            email_id = email_response.get("id")
        elif email_response and hasattr(email_response, "id"):
            email_id = email_response.id

        if email_id:
            print(f"Subscription update email sent to {email} (ID: {email_id})")
            return True

        print(f"Failed to send subscription update email to {email}. Response: {email_response}")
        return False
    except Exception as e:
        print(f"Error sending subscription update email to {email}: {str(e)}")
        return False


def _pricing_model_label_for_founder_email(pricing_model: Optional[str]) -> str:
    normalized = str(pricing_model or "").strip().lower()
    if normalized in {"pro_six_month", "pro_6_month", "pro_6month", "six_month", "6_month", "6month"}:
        return "Journey Pass (6 Months)"
    if normalized in {"pro_monthly", "pro", "monthly", ""}:
        return "Pro Monthly"
    return normalized.replace("_", " ").title()


def _enterprise_role_label(role: Optional[str]) -> str:
    normalized = str(role or "").strip().lower()
    labels = {
        "admin": "Admin",
        "editor": "Editor",
        "viewer": "Viewer (view-only)",
    }
    return labels.get(normalized, normalized.title() or "Viewer")


def send_enterprise_team_invite_email(
    *,
    invitee_email: str,
    invitee_name: Optional[str],
    organization_name: str,
    role: Optional[str],
    portal_url: Optional[str] = None,
    set_password_url: Optional[str] = None,
    password_setup_expires_hours: int = 72,
    invited_by_name: Optional[str] = None,
    invited_by_email: Optional[str] = None,
    base_url: str = DEFAULT_PUBLIC_BASE_URL,
) -> bool:
    """
    Send enterprise team invite email when an admin adds a user to an organization.
    """
    if not RESEND_API_KEY:
        print("ERROR: Cannot send enterprise invite email - Resend not configured")
        return False

    recipient = (invitee_email or "").strip().lower()
    if not recipient:
        print("ERROR: Cannot send enterprise invite email - invitee_email missing")
        return False

    org_name_raw = (organization_name or "").strip() or "your organization"
    portal_destination = (portal_url or "").strip() or f"{base_url.rstrip('/')}/enterprise"
    password_setup_destination = (
        (set_password_url or "").strip()
        or f"{base_url.rstrip('/')}/reset-password?token="
    )
    inviter_label = (
        (invited_by_name or "").strip()
        or (invited_by_email or "").strip()
        or "your organization admin"
    )

    safe_invitee_name = escape((invitee_name or "").strip() or "there")
    safe_org_name = escape(org_name_raw)
    safe_org_banner_name = escape(org_name_raw.upper())
    safe_role = escape(_enterprise_role_label(role))
    safe_portal_url = escape(portal_destination)
    safe_password_setup_url = escape(password_setup_destination)
    safe_inviter = escape(inviter_label)
    safe_expires_hours = max(1, int(password_setup_expires_hours))

    subject = f"You're invited to {org_name_raw} on Rilono Enterprise"
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>{escape(subject)}</title>
    </head>
    <body style="margin:0;padding:0;background:#f8fafc;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;">
      <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f8fafc;padding:24px 12px;">
        <tr>
          <td align="center">
            <table role="presentation" width="620" cellspacing="0" cellpadding="0" style="max-width:620px;background:#ffffff;border:1px solid #e2e8f0;border-radius:16px;overflow:hidden;">
              <tr>
                <td style="padding:26px 28px;background:linear-gradient(135deg,#1e3a8a 0%,#2563eb 100%);color:#ffffff;">
                  <div style="font-size:13px;letter-spacing:.06em;text-transform:uppercase;opacity:.95;">{safe_org_banner_name}</div>
                  <h1 style="margin:10px 0 0 0;font-size:28px;line-height:1.2;">Team Invitation</h1>
                </td>
              </tr>
              <tr>
                <td style="padding:26px 28px;color:#0f172a;">
                  <p style="margin:0 0 14px 0;font-size:15px;">Hi {safe_invitee_name},</p>
                  <p style="margin:0 0 14px 0;font-size:15px;line-height:1.6;">
                    You were added to <strong>{safe_org_name}</strong> on Rilono Enterprise by {safe_inviter}.
                  </p>
                  <div style="background:#eff6ff;color:#1e3a8a;padding:12px 14px;border-radius:10px;font-size:14px;line-height:1.5;margin-bottom:18px;">
                    Access Level: <strong>{safe_role}</strong>
                  </div>
                  <div style="text-align:center;margin-top:20px;">
                    <a href="{safe_password_setup_url}" style="display:inline-block;padding:12px 22px;border-radius:10px;background:linear-gradient(135deg,#6366f1 0%,#a855f7 100%);color:#ffffff;font-size:14px;font-weight:700;text-decoration:none;">
                      Set Password &amp; Continue
                    </a>
                  </div>
                  <p style="margin:18px 0 0 0;font-size:13px;color:#475569;line-height:1.6;">
                    Use this unique invitation link to create your password and sign in.
                    The link expires in <strong>{safe_expires_hours} hours</strong>.
                  </p>
                  <p style="margin:12px 0 0 0;font-size:13px;color:#64748b;line-height:1.6;">
                    For security, use a strong password with at least 10 characters, including uppercase, lowercase,
                    a number, and a special character.
                  </p>
                  <p style="margin:14px 0 0 0;font-size:13px;color:#64748b;line-height:1.6;">
                    Enterprise portal: <a href="{safe_portal_url}" style="color:#2563eb;text-decoration:none;">{safe_portal_url}</a>
                  </p>
                </td>
              </tr>
            </table>
          </td>
        </tr>
      </table>
    </body>
    </html>
    """

    text_content = (
        f"Team Invitation - {org_name_raw}\n\n"
        f"Hi {(invitee_name or '').strip() or 'there'},\n\n"
        f"You were added to {org_name_raw} on Rilono Enterprise by {inviter_label}.\n"
        f"Access Level: {_enterprise_role_label(role)}\n\n"
        f"Set Password & Continue: {password_setup_destination}\n"
        f"This unique invitation link expires in {safe_expires_hours} hours.\n"
        "Use a strong password with at least 10 characters including uppercase, lowercase, a number, "
        "and a special character.\n\n"
        f"Enterprise Portal: {portal_destination}\n"
    )

    try:
        params = {
            "from": f"{RESEND_FROM_NAME} <{_resolve_transactional_from_email()}>",
            "to": [recipient],
            "subject": subject,
            "html": html_content,
            "text": text_content,
        }
        email_response = resend.Emails.send(params)
        email_id = _extract_resend_email_id(email_response)
        if email_id:
            print(f"Enterprise invite email sent to {recipient} (ID: {email_id})")
            return True
        print(f"Failed to send enterprise invite email to {recipient}. Response: {email_response}")
        return False
    except Exception as e:
        print(f"Error sending enterprise invite email to {recipient}: {str(e)}")
        return False


def send_enterprise_client_email(
    *,
    to_email: str,
    subject: str,
    body: str,
    organization_name: str,
    sender_name: Optional[str] = None,
    logo_url: Optional[str] = None,
    reply_to: Optional[str] = None,
) -> tuple[bool, Optional[str], Optional[str]]:
    """
    Send an email composed by an enterprise team member to one of their clients.

    Returns (success, provider_message_id, error_message).
    """
    if not RESEND_API_KEY:
        return False, None, "Email service is not configured."

    recipient = (to_email or "").strip().lower()
    if not recipient:
        return False, None, "Recipient email is missing."

    clean_subject = (subject or "").strip() or f"A message from {organization_name}"
    org_label = (organization_name or "your consultancy").strip()
    signer = (sender_name or "").strip() or org_label

    safe_org = escape(org_label)
    safe_org_banner = escape(org_label.upper())
    safe_subject = escape(clean_subject)
    safe_signer = escape(signer)
    body_html = (escape(body or "").replace("\r\n", "\n").replace("\n", "<br>"))

    logo_block = ""
    clean_logo = (logo_url or "").strip()
    if clean_logo.startswith(("http://", "https://")):
        logo_block = (
            f'<img src="{escape(clean_logo)}" alt="{safe_org}" '
            'style="height:40px;width:40px;border-radius:10px;object-fit:cover;margin-bottom:10px;display:block;">'
        )

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>{safe_subject}</title>
    </head>
    <body style="margin:0;padding:0;background:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;">
      <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f1f5f9;padding:24px 12px;">
        <tr>
          <td align="center">
            <table role="presentation" width="600" cellspacing="0" cellpadding="0" style="max-width:600px;background:#ffffff;border:1px solid #e2e8f0;border-radius:16px;overflow:hidden;">
              <tr>
                <td style="padding:24px 28px;background:linear-gradient(135deg,#4338ca 0%,#7c3aed 100%);color:#ffffff;">
                  {logo_block}
                  <div style="font-size:12px;letter-spacing:.08em;text-transform:uppercase;opacity:.9;">{safe_org_banner}</div>
                  <h1 style="margin:8px 0 0 0;font-size:22px;line-height:1.3;">{safe_subject}</h1>
                </td>
              </tr>
              <tr>
                <td style="padding:28px;color:#0f172a;font-size:15px;line-height:1.7;">
                  {body_html}
                  <p style="margin:24px 0 0 0;color:#475569;font-size:14px;">Warm regards,<br><strong>{safe_signer}</strong><br>{safe_org}</p>
                </td>
              </tr>
              <tr>
                <td style="padding:16px 28px;background:#f8fafc;border-top:1px solid #e2e8f0;color:#94a3b8;font-size:12px;line-height:1.6;">
                  This message was sent by {safe_org} regarding your visa application.
                </td>
              </tr>
            </table>
          </td>
        </tr>
      </table>
    </body>
    </html>
    """

    text_content = (
        f"{clean_subject}\n\n"
        f"{(body or '').strip()}\n\n"
        f"Warm regards,\n{signer}\n{org_label}\n"
    )

    try:
        params = {
            "from": f"{org_label} <{_resolve_transactional_from_email()}>",
            "to": [recipient],
            "subject": clean_subject,
            "html": html_content,
            "text": text_content,
        }
        clean_reply_to = (reply_to or "").strip()
        if clean_reply_to:
            params["reply_to"] = clean_reply_to
        email_response = resend.Emails.send(params)
        email_id = _extract_resend_email_id(email_response)
        if email_id:
            return True, email_id, None
        return False, None, "Email provider did not confirm delivery."
    except Exception as e:
        return False, None, str(e)[:500]


def send_enterprise_interview_invite_email(
    *,
    to_email: str,
    client_name: Optional[str],
    organization_name: str,
    interview_url: str,
    allowed_count: int,
    destination_country: str,
    visa_type: str,
    logo_url: Optional[str] = None,
) -> tuple[bool, Optional[str], Optional[str]]:
    """Email a client a secure link to take self-serve mock visa interviews."""
    if not RESEND_API_KEY:
        return False, None, "Email service is not configured."
    recipient = (to_email or "").strip().lower()
    if not recipient:
        return False, None, "Recipient email is missing."

    org_label = (organization_name or "Your consultancy").strip()
    name = (client_name or "").strip() or "there"
    count = max(1, int(allowed_count or 1))
    count_text = "1 mock interview" if count == 1 else f"{count} mock interviews"
    safe_org = escape(org_label)
    safe_name = escape(name)
    safe_url = escape(interview_url)
    safe_country = escape(destination_country or "")
    safe_visa = escape(visa_type or "")
    logo_block = ""
    clean_logo = (logo_url or "").strip()
    if clean_logo.startswith(("http://", "https://")):
        logo_block = (f'<img src="{escape(clean_logo)}" alt="{safe_org}" '
                      'style="height:40px;width:40px;border-radius:10px;object-fit:cover;margin-bottom:10px;display:block;">')

    subject = f"Practice your {destination_country} visa interview — invite from {org_label}"
    html_content = f"""
    <!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
    <body style="margin:0;padding:0;background:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;">
      <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f1f5f9;padding:24px 12px;">
        <tr><td align="center">
          <table role="presentation" width="600" cellspacing="0" cellpadding="0" style="max-width:600px;background:#fff;border:1px solid #e2e8f0;border-radius:16px;overflow:hidden;">
            <tr><td style="padding:26px 28px;background:linear-gradient(135deg,#4338ca 0%,#7c3aed 100%);color:#fff;">
              {logo_block}
              <div style="font-size:12px;letter-spacing:.08em;text-transform:uppercase;opacity:.9;">{escape(org_label.upper())}</div>
              <h1 style="margin:8px 0 0 0;font-size:23px;">🎤 Mock visa interview</h1>
            </td></tr>
            <tr><td style="padding:28px;color:#0f172a;font-size:15px;line-height:1.7;">
              <p style="margin:0 0 14px;">Hi {safe_name},</p>
              <p style="margin:0 0 14px;">{safe_org} has invited you to practise your <strong>{safe_country}</strong> student-visa interview
              ({safe_visa}). An AI interviewer will play the real visa officer and give you honest feedback afterwards.</p>
              <div style="background:#eef2ff;color:#3730a3;padding:12px 14px;border-radius:10px;font-size:14px;margin-bottom:20px;">
                You can take <strong>{count_text}</strong> with this link.
              </div>
              <div style="text-align:center;margin:8px 0 18px;">
                <a href="{safe_url}" style="display:inline-block;padding:13px 26px;border-radius:10px;background:linear-gradient(135deg,#6366f1 0%,#a855f7 100%);color:#fff;font-size:15px;font-weight:700;text-decoration:none;">Start my mock interview →</a>
              </div>
              <p style="margin:14px 0 0;font-size:13px;color:#64748b;">For your security, you'll confirm a one-time code sent to this email before you begin. This link is personal to you — please don't share it.</p>
            </td></tr>
          </table>
        </td></tr>
      </table>
    </body></html>
    """
    text_content = (
        f"Hi {name},\n\n{org_label} has invited you to practise your {destination_country} student-visa interview "
        f"({visa_type}). You can take {count_text}.\n\nStart here: {interview_url}\n\n"
        "You'll confirm a one-time code sent to this email before you begin. This link is personal to you.\n"
    )
    try:
        params = {
            "from": f"{org_label} <{_resolve_transactional_from_email()}>",
            "to": [recipient],
            "subject": subject,
            "html": html_content,
            "text": text_content,
        }
        email_response = resend.Emails.send(params)
        email_id = _extract_resend_email_id(email_response)
        if email_id:
            return True, email_id, None
        return False, None, "Email provider did not confirm delivery."
    except Exception as e:
        return False, None, str(e)[:500]


def send_enterprise_interview_code_email(
    *,
    to_email: str,
    client_name: Optional[str],
    organization_name: str,
    code: str,
) -> tuple[bool, Optional[str], Optional[str]]:
    """Email the one-time verification code for the self-serve mock interview."""
    if not RESEND_API_KEY:
        return False, None, "Email service is not configured."
    recipient = (to_email or "").strip().lower()
    if not recipient:
        return False, None, "Recipient email is missing."
    org_label = (organization_name or "Your consultancy").strip()
    safe_org = escape(org_label)
    safe_code = escape(str(code))
    subject = f"{code} is your mock interview verification code"
    html_content = f"""
    <!DOCTYPE html><html><head><meta charset="UTF-8"></head>
    <body style="margin:0;padding:0;background:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;">
      <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f1f5f9;padding:24px 12px;">
        <tr><td align="center">
          <table role="presentation" width="520" cellspacing="0" cellpadding="0" style="max-width:520px;background:#fff;border:1px solid #e2e8f0;border-radius:16px;overflow:hidden;">
            <tr><td style="padding:28px;color:#0f172a;text-align:center;">
              <div style="font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#64748b;">{safe_org}</div>
              <p style="margin:14px 0 8px;font-size:15px;">Your mock interview verification code is:</p>
              <div style="font-size:34px;font-weight:800;letter-spacing:.18em;color:#4338ca;margin:6px 0 14px;">{safe_code}</div>
              <p style="margin:0;font-size:13px;color:#64748b;">This code expires in 15 minutes. If you didn't request it, you can ignore this email.</p>
            </td></tr>
          </table>
        </td></tr>
      </table>
    </body></html>
    """
    text_content = f"{org_label}\n\nYour mock interview verification code is: {code}\nThis code expires in 15 minutes.\n"
    try:
        params = {
            "from": f"{org_label} <{_resolve_transactional_from_email()}>",
            "to": [recipient],
            "subject": subject,
            "html": html_content,
            "text": text_content,
        }
        email_response = resend.Emails.send(params)
        email_id = _extract_resend_email_id(email_response)
        if email_id:
            return True, email_id, None
        return False, None, "Email provider did not confirm delivery."
    except Exception as e:
        return False, None, str(e)[:500]


def send_founder_new_verified_user_alert(
    *,
    user_id: int,
    user_email: str,
    full_name: Optional[str] = None,
    university: Optional[str] = None,
    current_residence_country: Optional[str] = None,
    verified_at: Optional[datetime] = None,
) -> bool:
    """
    Notify founders when a user completes email verification.
    """
    if not RESEND_API_KEY:
        print("ERROR: Cannot send founder verified-user alert - Resend not configured")
        return False
    if not FOUNDER_ALERT_RECIPIENTS:
        print("ERROR: Cannot send founder verified-user alert - no recipients configured")
        return False

    safe_email = escape((user_email or "").strip().lower() or "unknown")
    safe_name = escape((full_name or "").strip() or "Not provided")
    safe_university = escape((university or "").strip() or "Not provided")
    safe_country = escape((current_residence_country or "").strip() or "Not provided")
    safe_verified_at = escape(_format_datetime_for_subscription_email(verified_at or datetime.utcnow()))

    subject = f"New Verified User: {safe_email}"
    html_content = f"""
    <html>
      <body style="font-family:Arial,sans-serif;color:#0f172a;line-height:1.5;">
        <h2 style="margin:0 0 12px 0;">New user verified on Rilono</h2>
        <p style="margin:0 0 14px 0;">A user has completed email verification.</p>
        <table style="border-collapse:collapse;">
          <tr><td style="padding:4px 10px 4px 0;"><strong>User ID</strong></td><td>{int(user_id)}</td></tr>
          <tr><td style="padding:4px 10px 4px 0;"><strong>Email</strong></td><td>{safe_email}</td></tr>
          <tr><td style="padding:4px 10px 4px 0;"><strong>Full Name</strong></td><td>{safe_name}</td></tr>
          <tr><td style="padding:4px 10px 4px 0;"><strong>University</strong></td><td>{safe_university}</td></tr>
          <tr><td style="padding:4px 10px 4px 0;"><strong>Residence Country</strong></td><td>{safe_country}</td></tr>
          <tr><td style="padding:4px 10px 4px 0;"><strong>Verified At</strong></td><td>{safe_verified_at}</td></tr>
        </table>
      </body>
    </html>
    """
    text_content = (
        "New user verified on Rilono\n\n"
        f"User ID: {int(user_id)}\n"
        f"Email: {(user_email or '').strip().lower() or 'unknown'}\n"
        f"Full Name: {(full_name or '').strip() or 'Not provided'}\n"
        f"University: {(university or '').strip() or 'Not provided'}\n"
        f"Residence Country: {(current_residence_country or '').strip() or 'Not provided'}\n"
        f"Verified At: {_format_datetime_for_subscription_email(verified_at or datetime.utcnow())}\n"
    )

    try:
        params = {
            "from": f"{RESEND_FROM_NAME} <{_resolve_resend_from_email()}>",
            "to": FOUNDER_ALERT_RECIPIENTS,
            "subject": subject,
            "html": html_content,
            "text": text_content,
        }
        email_response = resend.Emails.send(params)
        email_id = _extract_resend_email_id(email_response)
        if email_id:
            print(f"Founder verified-user alert sent (ID: {email_id})")
            return True
        print(f"Failed to send founder verified-user alert. Response: {email_response}")
        return False
    except Exception as e:
        print(f"Error sending founder verified-user alert: {str(e)}")
        return False


def send_founder_first_subscription_purchase_alert(
    *,
    user_id: int,
    user_email: str,
    full_name: Optional[str] = None,
    university: Optional[str] = None,
    pricing_model: Optional[str] = None,
    payment_amount_paise: Optional[int] = None,
    payment_currency: str = "INR",
    payment_provider: Optional[str] = None,
    payment_reference: Optional[str] = None,
    purchased_at: Optional[datetime] = None,
) -> bool:
    """
    Notify founders when a user completes their first paid subscription purchase.
    """
    if not RESEND_API_KEY:
        print("ERROR: Cannot send founder subscription alert - Resend not configured")
        return False
    if not FOUNDER_ALERT_RECIPIENTS:
        print("ERROR: Cannot send founder subscription alert - no recipients configured")
        return False

    plan_label = _pricing_model_label_for_founder_email(pricing_model)
    safe_plan = escape(plan_label)
    safe_email = escape((user_email or "").strip().lower() or "unknown")
    safe_name = escape((full_name or "").strip() or "Not provided")
    safe_university = escape((university or "").strip() or "Not provided")
    safe_provider = escape((payment_provider or "").strip() or "Unknown")
    safe_reference = escape((payment_reference or "").strip() or "N/A")
    safe_amount = escape(_format_amount_for_subscription_email(payment_amount_paise, payment_currency))
    safe_purchased_at = escape(_format_datetime_for_subscription_email(purchased_at or datetime.utcnow()))

    subject = f"First Paid Subscription: {safe_plan} by {safe_email}"
    html_content = f"""
    <html>
      <body style="font-family:Arial,sans-serif;color:#0f172a;line-height:1.5;">
        <h2 style="margin:0 0 12px 0;">First paid subscription purchase</h2>
        <p style="margin:0 0 14px 0;">A user completed their first paid subscription purchase.</p>
        <table style="border-collapse:collapse;">
          <tr><td style="padding:4px 10px 4px 0;"><strong>User ID</strong></td><td>{int(user_id)}</td></tr>
          <tr><td style="padding:4px 10px 4px 0;"><strong>Email</strong></td><td>{safe_email}</td></tr>
          <tr><td style="padding:4px 10px 4px 0;"><strong>Full Name</strong></td><td>{safe_name}</td></tr>
          <tr><td style="padding:4px 10px 4px 0;"><strong>University</strong></td><td>{safe_university}</td></tr>
          <tr><td style="padding:4px 10px 4px 0;"><strong>Plan</strong></td><td>{safe_plan}</td></tr>
          <tr><td style="padding:4px 10px 4px 0;"><strong>Amount</strong></td><td>{safe_amount}</td></tr>
          <tr><td style="padding:4px 10px 4px 0;"><strong>Provider</strong></td><td>{safe_provider}</td></tr>
          <tr><td style="padding:4px 10px 4px 0;"><strong>Reference</strong></td><td>{safe_reference}</td></tr>
          <tr><td style="padding:4px 10px 4px 0;"><strong>Purchased At</strong></td><td>{safe_purchased_at}</td></tr>
        </table>
      </body>
    </html>
    """
    text_content = (
        "First paid subscription purchase\n\n"
        f"User ID: {int(user_id)}\n"
        f"Email: {(user_email or '').strip().lower() or 'unknown'}\n"
        f"Full Name: {(full_name or '').strip() or 'Not provided'}\n"
        f"University: {(university or '').strip() or 'Not provided'}\n"
        f"Plan: {plan_label}\n"
        f"Amount: {_format_amount_for_subscription_email(payment_amount_paise, payment_currency)}\n"
        f"Provider: {(payment_provider or '').strip() or 'Unknown'}\n"
        f"Reference: {(payment_reference or '').strip() or 'N/A'}\n"
        f"Purchased At: {_format_datetime_for_subscription_email(purchased_at or datetime.utcnow())}\n"
    )

    try:
        params = {
            "from": f"{RESEND_FROM_NAME} <{_resolve_resend_from_email()}>",
            "to": FOUNDER_ALERT_RECIPIENTS,
            "subject": subject,
            "html": html_content,
            "text": text_content,
        }
        email_response = resend.Emails.send(params)
        email_id = _extract_resend_email_id(email_response)
        if email_id:
            print(f"Founder first-subscription alert sent (ID: {email_id})")
            return True
        print(f"Failed to send founder first-subscription alert. Response: {email_response}")
        return False
    except Exception as e:
        print(f"Error sending founder first-subscription alert: {str(e)}")
        return False


def _sanitize_ai_email_html(html_content: str) -> str:
    if not html_content:
        return "<p>Please review your account for updates.</p>"
    cleaned = re.sub(r"(?is)<script.*?>.*?</script>", "", html_content)
    cleaned = re.sub(r"(?is)<style.*?>.*?</style>", "", cleaned)
    cleaned = cleaned.replace("javascript:", "")
    cleaned = cleaned.strip()
    return cleaned or "<p>Please review your account for updates.</p>"


def send_proactive_assistant_email(
    email: str,
    full_name: Optional[str],
    subject: str,
    html_body: str,
    base_url: str = DEFAULT_PUBLIC_BASE_URL,
    unsubscribe_url: Optional[str] = None,
) -> bool:
    """
    Send proactive F1 guidance emails generated by Gemini.
    """
    if not RESEND_API_KEY:
        print("ERROR: Cannot send proactive assistant email - Resend not configured")
        return False

    safe_subject = (subject or "").strip()[:140] or "Rilono F1 Visa Update"
    sanitized_body = _sanitize_ai_email_html(html_body)
    manage_url = f"{base_url.rstrip('/')}/dashboard"
    safe_unsubscribe_url = escape((unsubscribe_url or "").strip())

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>{escape(safe_subject)}</title>
    </head>
    <body style="margin:0;padding:0;background:#f8fafc;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;">
      <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f8fafc;padding:24px 12px;">
        <tr>
          <td align="center">
            <table role="presentation" width="620" cellspacing="0" cellpadding="0" style="max-width:620px;background:#ffffff;border:1px solid #e2e8f0;border-radius:16px;overflow:hidden;">
              <tr>
                <td style="padding:26px 28px;background:linear-gradient(135deg,#6366f1 0%,#a855f7 100%);color:#ffffff;">
                  <div style="font-size:13px;letter-spacing:.06em;text-transform:uppercase;opacity:.95;">Rilono AI Assistant</div>
                  <h1 style="margin:10px 0 0 0;font-size:28px;line-height:1.2;">{escape(safe_subject)}</h1>
                </td>
              </tr>
              <tr>
                <td style="padding:26px 28px;color:#0f172a;">
                  <div style="font-size:15px;line-height:1.6;color:#0f172a;">
                    {sanitized_body}
                  </div>
                  <div style="text-align:center;margin-top:22px;">
                    <a href="{escape(manage_url)}" style="display:inline-block;padding:12px 22px;border-radius:10px;background:linear-gradient(135deg,#6366f1 0%,#a855f7 100%);color:#ffffff;font-size:14px;font-weight:700;text-decoration:none;">
                      Open Dashboard
                    </a>
                  </div>
                  <p style="margin:20px 0 0 0;font-size:13px;color:#64748b;">
                    Need help? Reach out at
                    <a href="mailto:contact@rilono.com" style="color:#4f46e5;text-decoration:none;">contact@rilono.com</a>.
                  </p>
                  <p style="margin:10px 0 0 0;font-size:11px;color:#94a3b8;">
                    {f'<a href="{safe_unsubscribe_url}" style="color:#94a3b8;text-decoration:none;">Unsubscribe from email notifications</a>' if safe_unsubscribe_url else ''}
                  </p>
                </td>
              </tr>
            </table>
          </td>
        </tr>
      </table>
    </body>
    </html>
    """
    text_body = re.sub(r"<[^>]+>", " ", sanitized_body)
    text_body = re.sub(r"\\s+", " ", text_body).strip()
    text_content = (
        f"{safe_subject}\n\n"
        f"{text_body}\n\n"
        f"Open Dashboard: {manage_url}\n"
        + (f"\nUnsubscribe from email notifications: {unsubscribe_url}\n" if unsubscribe_url else "")
    )

    try:
        if USE_TEST_EMAIL or DEV_MODE:
            from_email = "delivered@resend.dev"
            print("DEV MODE: Using test email sender (delivered@resend.dev)")
        else:
            from_email = RESEND_FROM_EMAIL

        params = {
            "from": f"{RESEND_FROM_NAME} <{from_email}>",
            "to": [email],
            "subject": safe_subject,
            "html": html_content,
            "text": text_content,
        }
        email_response = resend.Emails.send(params)

        email_id = None
        if isinstance(email_response, dict):
            email_id = email_response.get("id")
        elif email_response and hasattr(email_response, "id"):
            email_id = email_response.id

        if email_id:
            print(f"Proactive assistant email sent to {email} (ID: {email_id})")
            return True

        print(f"Failed to send proactive assistant email to {email}. Response: {email_response}")
        return False
    except Exception as e:
        print(f"Error sending proactive assistant email to {email}: {str(e)}")
        return False
