import os
from typing import Optional
import resend
from dotenv import load_dotenv
import secrets

load_dotenv()

# Initialize Resend
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
RESEND_FROM_EMAIL = os.getenv("RESEND_FROM_EMAIL", "noreply@rilono.com")
RESEND_FROM_NAME = os.getenv("RESEND_FROM_NAME", "Rilono")
# For development: use Resend's test email (delivered@resend.dev) which doesn't require domain verification
USE_TEST_EMAIL = os.getenv("USE_TEST_EMAIL", "false").lower() == "true"
DEV_MODE = os.getenv("DEV_MODE", "false").lower() == "true"

if RESEND_API_KEY:
    resend.api_key = RESEND_API_KEY
else:
    print("WARNING: RESEND_API_KEY not found. Email functionality will be disabled.")


def generate_verification_token() -> str:
    """Generate a secure random token for email verification."""
    return secrets.token_urlsafe(32)


def send_verification_email(email: str, verification_token: str, base_url: str = "http://localhost:8000") -> bool:
    """
    Send email verification email using Resend.
    
    Args:
        email: Recipient email address
        verification_token: Token for verification
        base_url: Base URL of the application (for verification link)
    
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
                Thank you for signing up for Rilono! To complete your registration and start using our student marketplace, 
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
                This verification link will expire in 24 hours. If you didn't create an account with Rilono, 
                please ignore this email.
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
    Welcome to Rilono!
    
    Thank you for signing up! To complete your registration, please verify your email address by clicking the link below:
    
    {verification_link}
    
    This verification link will expire in 24 hours. If you didn't create an account with Rilono, please ignore this email.
    
    © 2025 Rilono. All rights reserved.
    """
    
    try:
        # In development mode, use Resend's test email sender (doesn't require domain verification)
        if USE_TEST_EMAIL or DEV_MODE:
            from_email = "delivered@resend.dev"  # Resend's test email - works without domain verification
            print(f"DEV MODE: Using test email sender (delivered@resend.dev)")
        else:
            from_email = RESEND_FROM_EMAIL
        
        params = {
            "from": f"{RESEND_FROM_NAME} <{from_email}>",
            "to": [email],
            "subject": "Verify Your Email - Rilono",
            "html": html_content,
            "text": text_content,
        }
        
        email_response = resend.Emails.send(params)
        
        if email_response and hasattr(email_response, 'id'):
            print(f"Verification email sent successfully to {email}")
            if USE_TEST_EMAIL or DEV_MODE:
                print(f"  NOTE: Using test email sender. Check Resend dashboard for email preview.")
            return True
        else:
            print(f"Failed to send verification email to {email}")
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


def send_password_reset_email(email: str, reset_token: str, base_url: str = "http://localhost:8000") -> bool:
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
        # In development mode, use Resend's test email sender
        if USE_TEST_EMAIL or DEV_MODE:
            from_email = "delivered@resend.dev"
            print(f"DEV MODE: Using test email sender (delivered@resend.dev)")
        else:
            from_email = RESEND_FROM_EMAIL
        
        params = {
            "from": f"{RESEND_FROM_NAME} <{from_email}>",
            "to": [email],
            "subject": "Reset Your Password - Rilono",
            "html": html_content,
            "text": text_content,
        }
        
        email_response = resend.Emails.send(params)
        
        if email_response and hasattr(email_response, 'id'):
            print(f"Password reset email sent successfully to {email}")
            return True
        else:
            print(f"Failed to send password reset email to {email}")
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
