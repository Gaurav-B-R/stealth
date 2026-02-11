from fastapi import APIRouter, Depends, HTTPException, status, Request, Form
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import timedelta, datetime
from app.database import get_db
from app import models, schemas
from app.auth import (
    authenticate_user,
    create_access_token,
    get_password_hash,
    get_current_active_user,
    ACCESS_TOKEN_EXPIRE_MINUTES
)
from app.email_service import generate_verification_token, send_verification_email, send_password_reset_email
from app.utils.turnstile import verify_turnstile_token
from app.subscriptions import get_or_create_user_subscription
from app.referrals import (
    ensure_user_referral_code,
    generate_unique_referral_code,
    get_user_by_referral_code,
    maybe_award_referral_bonus_on_login,
)
import os

router = APIRouter(prefix="/api/auth", tags=["authentication"])
DEFAULT_PUBLIC_BASE_URL = "https://rilono.com"

@router.get("/turnstile-site-key")
def get_turnstile_site_key():
    """Get the Cloudflare Turnstile site key for frontend use."""
    site_key = os.getenv("TURNSTILE_SITE_KEY", "")
    return {"site_key": site_key}

def extract_email_domain(email: str) -> str:
    """Extract domain from email address."""
    if '@' not in email:
        return ""
    return email.split('@')[1].lower()

@router.get("/university-by-email", response_model=schemas.UniversityInfo)
def get_university_by_email(email: str, db: Session = Depends(get_db)):
    """Get university information based on email domain."""
    email_lower = email.lower()
    
    # First check if it's a developer email
    dev_email = db.query(models.DeveloperEmail).filter(
        models.DeveloperEmail.email == email_lower
    ).first()
    
    if dev_email:
        return {
            "university_name": dev_email.university_name,
            "email_domain": extract_email_domain(email),
            "is_valid": True
        }
    
    # Otherwise check university domains
    email_domain = extract_email_domain(email)
    if not email_domain:
        raise HTTPException(status_code=400, detail="Invalid email format")
    
    university = db.query(models.USUniversity).filter(
        models.USUniversity.email_domain == email_domain
    ).first()
    
    if not university:
        return {"university_name": None, "email_domain": email_domain, "is_valid": False}
    
    return {
        "university_name": university.university_name,
        "email_domain": university.email_domain,
        "is_valid": True
    }

@router.post("/register", response_model=schemas.UserResponse, status_code=status.HTTP_201_CREATED)
def register(user: schemas.UserCreate, db: Session = Depends(get_db), request: Request = None):
    if not user.accepted_terms_privacy:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You must accept the Terms & Conditions and Privacy Policy to register."
        )

    # Verify Turnstile token if provided
    turnstile_token = user.cf_turnstile_token
    if turnstile_token:
        client_ip = request.client.host if request else None
        if not verify_turnstile_token(turnstile_token, client_ip):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Security verification failed. Please try again."
            )
    else:
        # In production, require Turnstile token
        if os.getenv("ENVIRONMENT", "production").lower() != "development":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Security verification is required"
            )
    
    # Extract email domain
    email_domain = extract_email_domain(user.email)
    
    if not email_domain:
        raise HTTPException(status_code=400, detail="Invalid email format")
    
    # Check if this is a developer email (exception)
    dev_email = db.query(models.DeveloperEmail).filter(
        models.DeveloperEmail.email == user.email.lower()
    ).first()
    
    if dev_email:
        # Developer email - allow registration with special university name
        university_name = dev_email.university_name
    else:
        # Validate email domain against us_universities table
        university = db.query(models.USUniversity).filter(
            models.USUniversity.email_domain == email_domain
        ).first()
        
        if not university:
            raise HTTPException(
                status_code=403,
                detail="Registration is restricted to students with valid university email addresses. Please use your university email domain."
            )
        university_name = university.university_name
    
    # Check if user already exists
    db_user = db.query(models.User).filter(models.User.email == user.email).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")

    referrer = None
    normalized_referral_code = (user.referral_code or "").strip().upper()
    if normalized_referral_code:
        referrer = get_user_by_referral_code(db, normalized_referral_code)
        if not referrer:
            raise HTTPException(status_code=400, detail="Invalid referral code")
    
    # Auto-generate username from email if not provided
    username = user.username
    if not username:
        # Use email as username (or extract part before @)
        username = user.email.split('@')[0]
    
    # Check if auto-generated username already exists (unlikely but possible)
    db_user = db.query(models.User).filter(models.User.username == username).first()
    if db_user:
        # If username exists, append a number
        counter = 1
        while db.query(models.User).filter(models.User.username == f"{username}{counter}").first():
            counter += 1
        username = f"{username}{counter}"
    
    # Validate password length
    if len(user.password.encode('utf-8')) > 200:
        raise HTTPException(status_code=400, detail="Password is too long. Maximum 200 characters allowed.")
    
    # Create new user with auto-filled university name
    try:
        hashed_password = get_password_hash(user.password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Password hashing error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail="An error occurred during registration. Please try again.")
    
    # Generate verification token
    verification_token = generate_verification_token()
    token_expires = datetime.utcnow() + timedelta(hours=24)  # Token expires in 24 hours
    
    # Auto-fill university name from the database (ignore user-provided university)
    db_user = models.User(
        email=user.email,
        username=username,  # Auto-generated from email
        hashed_password=hashed_password,
        full_name=user.full_name,
        university=university_name,  # Auto-filled from database (or developer email)
        phone=user.phone,
        current_residence_country=user.current_residence_country or "United States",
        referral_code=generate_unique_referral_code(db),
        referred_by_user_id=referrer.id if referrer else None,
        accepted_terms_privacy_at=datetime.utcnow(),
        email_verified=False,
        verification_token=verification_token,
        verification_token_expires=token_expires
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    get_or_create_user_subscription(db, db_user.id)
    
    # Send verification email
    base_url = os.getenv("BASE_URL", DEFAULT_PUBLIC_BASE_URL)
    email_sent = send_verification_email(user.email, verification_token, base_url)
    
    if not email_sent:
        # Log error but don't fail registration - user can request resend later
        print(f"Warning: Failed to send verification email to {user.email}")
        print("   User can still request a resend verification email later.")
    
    return db_user

@router.post("/login", response_model=schemas.Token)
async def login(
    request: Request,
    db: Session = Depends(get_db)
):
    # Read form data manually to get both OAuth2 fields and Turnstile token
    form = await request.form()
    
    # Extract OAuth2 fields
    username = form.get("username")
    password = form.get("password")
    
    if not username or not password:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Username and password are required"
        )
    
    # Get Turnstile token
    turnstile_token = form.get("cf_turnstile_token")
    if isinstance(turnstile_token, list) and turnstile_token:
        turnstile_token = turnstile_token[0]
    
    # Verify Turnstile token
    if turnstile_token:
        client_ip = request.client.host if request else None
        if not verify_turnstile_token(turnstile_token, client_ip):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Security verification failed. Please try again."
            )
    else:
        # In production, require Turnstile token
        if os.getenv("ENVIRONMENT", "production").lower() != "development":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Security verification is required"
            )
    
    # Use username field as email (OAuth2PasswordRequestForm convention)
    user = authenticate_user(db, username, password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Check if email is verified
    if not user.email_verified:
        raise HTTPException(
            status_code=403,
            detail="Please verify your email address before logging in. Check your inbox for the verification email or request a new one."
        )
    
    # Additional validation: Check if user's email domain is still valid
    # Skip validation for developer emails
    dev_email = db.query(models.DeveloperEmail).filter(
        models.DeveloperEmail.email == user.email.lower()
    ).first()
    
    if not dev_email:
        email_domain = extract_email_domain(user.email)
        if email_domain:
            university = db.query(models.USUniversity).filter(
                models.USUniversity.email_domain == email_domain
            ).first()
            if not university:
                raise HTTPException(
                    status_code=403,
                    detail="Your account email domain is no longer valid. Please contact support."
                )

    # Ensure legacy users also have a default subscription record.
    get_or_create_user_subscription(db, user.id)
    had_referral_code = bool(user.referral_code)
    ensure_user_referral_code(db, user, commit=False)

    reward_payload = {"awarded": False, "message": None}
    now = datetime.utcnow()
    changes_pending = not had_referral_code
    if user.first_login_at is None:
        user.first_login_at = now
        changes_pending = True

    reward_payload = maybe_award_referral_bonus_on_login(db, user, commit=False)
    if reward_payload.get("awarded"):
        changes_pending = True

    if changes_pending:
        db.commit()
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    # Store email in token instead of username
    access_token = create_access_token(
        data={"sub": user.email}, expires_delta=access_token_expires
    )
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "referral_bonus_awarded": bool(reward_payload.get("awarded")),
        "referral_bonus_message": reward_payload.get("message"),
    }

@router.get("/me", response_model=schemas.UserResponse)
def read_users_me(
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    get_or_create_user_subscription(db, current_user.id)
    ensure_user_referral_code(db, current_user, commit=True)
    return current_user

@router.post("/forgot-password")
def forgot_password(request: schemas.PasswordResetRequest, db: Session = Depends(get_db)):
    """
    Request password reset. Sends a password reset email.
    """
    email = request.email.lower().strip()
    
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")
    
    # Find user by email
    user = db.query(models.User).filter(models.User.email == email).first()
    
    # Check if account exists
    if not user:
        raise HTTPException(
            status_code=404,
            detail="No account found with this email address. Please create an account first."
        )
    
    # Generate password reset token
    reset_token = generate_verification_token()
    token_expires = datetime.utcnow() + timedelta(hours=1)  # Token expires in 1 hour
    
    # Save reset token to user
    user.password_reset_token = reset_token
    user.password_reset_token_expires = token_expires
    db.commit()
    
    # Send password reset email
    base_url = os.getenv("BASE_URL", DEFAULT_PUBLIC_BASE_URL)
    email_sent = send_password_reset_email(user.email, reset_token, base_url)
    
    if email_sent:
        return {
            "message": "Password reset link has been sent to your email. Please check your inbox."
        }
    else:
        raise HTTPException(
            status_code=500,
            detail="Failed to send password reset email. Please try again later or contact support."
        )

@router.post("/reset-password")
def reset_password(request: schemas.PasswordReset, db: Session = Depends(get_db)):
    """
    Reset password using the reset token.
    """
    token = request.token
    new_password = request.new_password
    
    if not token:
        raise HTTPException(status_code=400, detail="Reset token is required")
    
    if not new_password or len(new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters long")
    
    if len(new_password.encode('utf-8')) > 200:
        raise HTTPException(status_code=400, detail="Password is too long. Maximum 200 characters allowed.")
    
    # Find user by reset token
    user = db.query(models.User).filter(
        models.User.password_reset_token == token
    ).first()
    
    if not user:
        raise HTTPException(
            status_code=404,
            detail="Invalid or expired password reset token"
        )
    
    # Check if token has expired
    if user.password_reset_token_expires and user.password_reset_token_expires < datetime.utcnow():
        raise HTTPException(
            status_code=400,
            detail="Password reset token has expired. Please request a new password reset."
        )
    
    # Hash new password
    try:
        hashed_password = get_password_hash(new_password)
    except Exception as e:
        raise HTTPException(status_code=500, detail="An error occurred while resetting your password.")
    
    # Update password and clear reset token
    user.hashed_password = hashed_password
    user.password_reset_token = None
    user.password_reset_token_expires = None
    db.commit()
    
    return {
        "message": "Password reset successfully! You can now log in with your new password."
    }

@router.get("/verify-email")
def verify_email(token: str, db: Session = Depends(get_db)):
    """
    Verify user email using the verification token.
    """
    if not token:
        raise HTTPException(status_code=400, detail="Verification token is required")
    
    # Find user by verification token
    user = db.query(models.User).filter(
        models.User.verification_token == token
    ).first()
    
    if not user:
        raise HTTPException(
            status_code=404,
            detail="Invalid or expired verification token"
        )
    
    # Check if token has expired
    if user.verification_token_expires and user.verification_token_expires < datetime.utcnow():
        raise HTTPException(
            status_code=400,
            detail="Verification token has expired. Please request a new verification email."
        )
    
    # Check if already verified
    if user.email_verified:
        return {
            "message": "Email is already verified",
            "verified": True
        }
    
    # Verify the email
    user.email_verified = True
    user.verification_token = None  # Clear the token after verification
    user.verification_token_expires = None
    db.commit()
    
    return {
        "message": "Email verified successfully! You can now log in.",
        "verified": True
    }

@router.post("/resend-verification")
def resend_verification_email(request: schemas.ResendVerificationRequest, db: Session = Depends(get_db)):
    """
    Resend verification email to user.
    """
    email = request.email
    
    user = db.query(models.User).filter(models.User.email == email).first()
    
    if not user:
        # Don't reveal if email exists or not for security
        return {
            "message": "If an account with this email exists and is not verified, a verification email has been sent."
        }
    
    # Check if already verified
    if user.email_verified:
        return {
            "message": "Email is already verified"
        }
    
    # Generate new verification token
    verification_token = generate_verification_token()
    token_expires = datetime.utcnow() + timedelta(hours=24)
    
    user.verification_token = verification_token
    user.verification_token_expires = token_expires
    db.commit()
    
    # Send verification email
    base_url = os.getenv("BASE_URL", DEFAULT_PUBLIC_BASE_URL)
    email_sent = send_verification_email(user.email, verification_token, base_url)
    
    if email_sent:
        return {
            "message": "Verification email sent successfully. Please check your inbox."
        }
    else:
        # Return helpful error message
        error_detail = (
            "Failed to send verification email. "
            "If you're in development mode, make sure RESEND_API_KEY is set and "
            "consider using USE_TEST_EMAIL=true in your .env file to use Resend's test email sender."
        )
        raise HTTPException(
            status_code=500,
            detail=error_detail
        )


@router.post("/request-university-change")
def request_university_change(
    request: Request,
    change_request: schemas.UniversityChangeRequest,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Request to change university. Sends verification email to the new .edu email.
    """
    from app.email_service import generate_verification_token, send_university_change_email
    
    new_email = change_request.new_email.lower().strip()
    new_university = change_request.new_university.strip()
    
    # Validate that new email is different from current
    if new_email == current_user.email:
        raise HTTPException(
            status_code=400,
            detail="New email must be different from your current email."
        )
    
    # Validate that new email is a valid .edu email or developer email
    email_domain = extract_email_domain(new_email)
    
    # Check if it's a developer email
    dev_email = db.query(models.DeveloperEmail).filter(
        models.DeveloperEmail.email == new_email
    ).first()
    
    if not dev_email:
        # Check if domain is a valid university domain
        university = db.query(models.UniversityDomain).filter(
            models.UniversityDomain.email_domain == email_domain
        ).first()
        
        if not university:
            raise HTTPException(
                status_code=400,
                detail="Please use a valid university .edu email address."
            )
        
        # Verify university name matches domain
        if university.university_name.lower() != new_university.lower():
            raise HTTPException(
                status_code=400,
                detail=f"The email domain does not match {new_university}."
            )
    
    # Check if new email is already registered to another user
    existing_user = db.query(models.User).filter(
        models.User.email == new_email,
        models.User.id != current_user.id
    ).first()
    
    if existing_user:
        raise HTTPException(
            status_code=400,
            detail="This email is already registered to another account."
        )
    
    # Generate verification token
    change_token = generate_verification_token()
    token_expires = datetime.utcnow() + timedelta(hours=24)
    
    # Store pending change info
    current_user.pending_email = new_email
    current_user.pending_university = new_university
    current_user.university_change_token = change_token
    current_user.university_change_token_expires = token_expires
    
    db.commit()
    
    # Get base URL
    base_url = str(request.base_url).rstrip('/')
    if 'localhost' not in base_url and 'http://' in base_url:
        base_url = base_url.replace('http://', 'https://')
    
    # Send verification email
    email_sent = send_university_change_email(new_email, new_university, change_token, base_url)
    
    if email_sent:
        return {
            "message": f"Verification email sent to {new_email}. Please check your inbox to confirm the university change."
        }
    else:
        raise HTTPException(
            status_code=500,
            detail="Failed to send verification email. Please try again later."
        )


@router.get("/verify-university-change")
def verify_university_change(token: str, db: Session = Depends(get_db)):
    """
    Verify and complete university change using the verification token.
    """
    if not token:
        raise HTTPException(
            status_code=400,
            detail="Verification token is required."
        )
    
    # Find user with this token
    user = db.query(models.User).filter(
        models.User.university_change_token == token
    ).first()
    
    if not user:
        raise HTTPException(
            status_code=400,
            detail="Invalid verification token. Please request a new university change."
        )
    
    # Check if token has expired
    if user.university_change_token_expires and user.university_change_token_expires < datetime.utcnow():
        # Clear the pending change
        user.pending_email = None
        user.pending_university = None
        user.university_change_token = None
        user.university_change_token_expires = None
        db.commit()
        
        raise HTTPException(
            status_code=400,
            detail="Verification token has expired. Please request a new university change."
        )
    
    # Check if pending info exists
    if not user.pending_email or not user.pending_university:
        raise HTTPException(
            status_code=400,
            detail="No pending university change found."
        )
    
    # Update user's email and university
    old_email = user.email
    old_university = user.university
    
    user.email = user.pending_email
    user.university = user.pending_university
    
    # Clear pending change info
    user.pending_email = None
    user.pending_university = None
    user.university_change_token = None
    user.university_change_token_expires = None
    
    db.commit()
    
    return {
        "message": f"University successfully changed to {user.university}!",
        "old_email": old_email,
        "new_email": user.email,
        "old_university": old_university,
        "new_university": user.university
    }


@router.get("/pending-university-change")
def get_pending_university_change(
    current_user: models.User = Depends(get_current_active_user)
):
    """
    Check if there's a pending university change request.
    """
    if current_user.pending_email and current_user.pending_university:
        return {
            "has_pending_change": True,
            "pending_email": current_user.pending_email,
            "pending_university": current_user.pending_university,
            "expires": current_user.university_change_token_expires.isoformat() if current_user.university_change_token_expires else None
        }
    
    return {"has_pending_change": False}


@router.post("/cancel-university-change")
def cancel_university_change(
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Cancel a pending university change request.
    """
    if not current_user.pending_email:
        raise HTTPException(
            status_code=400,
            detail="No pending university change to cancel."
        )
    
    current_user.pending_email = None
    current_user.pending_university = None
    current_user.university_change_token = None
    current_user.university_change_token_expires = None
    
    db.commit()
    
    return {"message": "University change request cancelled."}


@router.post("/contact")
async def submit_contact_form(
    name: str = Form(...),
    email: str = Form(...),
    subject: str = Form(...),
    message: str = Form(...),
    user_type: str = Form("visitor")
):
    """
    Submit contact form - sends email to contact@rilono.com.
    No authentication required.
    """
    from ..email_service import send_contact_form_email
    
    # Basic validation
    if not name or len(name.strip()) < 2:
        raise HTTPException(status_code=400, detail="Please provide your name")
    
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Please provide a valid email address")
    
    if not subject or len(subject.strip()) < 1:
        raise HTTPException(status_code=400, detail="Please provide a subject")
    
    if not message or len(message.strip()) < 1:
        raise HTTPException(status_code=400, detail="Please provide a message")
    
    # Send the email
    success = send_contact_form_email(
        name=name.strip(),
        email=email.strip(),
        subject=subject.strip(),
        message=message.strip(),
        user_type=user_type
    )
    
    if success:
        return {"message": "Thank you for contacting us! We'll get back to you soon."}
    else:
        raise HTTPException(
            status_code=500,
            detail="Failed to send your message. Please try again or email us directly at contact@rilono.com"
        )
