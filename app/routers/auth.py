from fastapi import APIRouter, Depends, HTTPException, status, Request, Form, Response
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from sqlalchemy import or_
from datetime import timedelta, datetime
from app.database import get_db
from app import models, schemas
from app.auth import (
    authenticate_user,
    create_access_token,
    get_password_hash,
    get_current_active_user,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    validate_password_strength,
)
from app.email_service import (
    generate_verification_token,
    send_verification_email,
    send_password_reset_email,
    send_contact_form_email,
    verify_email_notifications_unsubscribe_token,
)
from app.utils.turnstile import verify_turnstile_token
from app.subscriptions import get_or_create_user_subscription
from app.referrals import (
    ensure_user_referral_code,
    generate_unique_referral_code,
    get_user_by_referral_code,
    maybe_award_referral_bonus_on_login,
)
from app.utils.rate_limiter import check_ip_rate_limit
from app.utils.token_security import hash_token, token_matches
import os

router = APIRouter(prefix="/api/auth", tags=["authentication"])
DEFAULT_PUBLIC_BASE_URL = "https://rilono.com"

REGISTER_RATE_LIMIT = int(os.getenv("REGISTER_RATE_LIMIT", "5"))
REGISTER_RATE_WINDOW_SECONDS = int(os.getenv("REGISTER_RATE_WINDOW_SECONDS", "900"))
LOGIN_RATE_LIMIT = int(os.getenv("LOGIN_RATE_LIMIT", "12"))
LOGIN_RATE_WINDOW_SECONDS = int(os.getenv("LOGIN_RATE_WINDOW_SECONDS", "300"))
FORGOT_PASSWORD_RATE_LIMIT = int(os.getenv("FORGOT_PASSWORD_RATE_LIMIT", "5"))
FORGOT_PASSWORD_RATE_WINDOW_SECONDS = int(os.getenv("FORGOT_PASSWORD_RATE_WINDOW_SECONDS", "900"))
CONTACT_RATE_LIMIT = int(os.getenv("CONTACT_RATE_LIMIT", "5"))
CONTACT_RATE_WINDOW_SECONDS = int(os.getenv("CONTACT_RATE_WINDOW_SECONDS", "1800"))
EMAIL_VERIFICATION_TOKEN_EXPIRES_HOURS = int(os.getenv("EMAIL_VERIFICATION_TOKEN_EXPIRES_HOURS", "24"))
AUTH_COOKIE_NAME = os.getenv("AUTH_COOKIE_NAME", "rilono_access_token").strip() or "rilono_access_token"


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _cookie_secure_default() -> bool:
    env = os.getenv("ENVIRONMENT", "production").strip().lower()
    return env != "development"


AUTH_COOKIE_SECURE = _bool_env("AUTH_COOKIE_SECURE", _cookie_secure_default())
AUTH_COOKIE_DOMAIN = (os.getenv("AUTH_COOKIE_DOMAIN", "").strip() or None)
_cookie_samesite_raw = os.getenv("AUTH_COOKIE_SAMESITE", "strict").strip().lower()
AUTH_COOKIE_SAMESITE = _cookie_samesite_raw if _cookie_samesite_raw in {"lax", "strict", "none"} else "strict"


def _set_auth_cookie(response: Response, access_token: str, max_age_seconds: int) -> None:
    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=access_token,
        max_age=max_age_seconds,
        httponly=True,
        secure=AUTH_COOKIE_SECURE,
        samesite=AUTH_COOKIE_SAMESITE,
        domain=AUTH_COOKIE_DOMAIN,
        path="/",
    )


def _clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(
        key=AUTH_COOKIE_NAME,
        domain=AUTH_COOKIE_DOMAIN,
        path="/",
    )


def _enforce_rate_limit_or_429(
    request: Request,
    scope: str,
    limit: int,
    window_seconds: int,
    extra_key: str | None = None,
) -> None:
    allowed, retry_after = check_ip_rate_limit(
        request=request,
        scope=scope,
        limit=limit,
        window_seconds=window_seconds,
        extra_key=extra_key,
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )

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
def register(
    user: schemas.UserCreate,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    _enforce_rate_limit_or_429(
        request=request,
        scope="auth.register",
        limit=REGISTER_RATE_LIMIT,
        window_seconds=REGISTER_RATE_WINDOW_SECONDS,
    )

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
        raise HTTPException(
            status_code=400,
            detail="Unable to complete registration. Please check your details or log in if you already have an account."
        )

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
    
    # Validate password strength
    password_error = validate_password_strength(user.password, user.email)
    if password_error:
        raise HTTPException(status_code=400, detail=password_error)
    
    # Create new user with auto-filled university name
    try:
        hashed_password = get_password_hash(user.password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Password hashing error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail="An error occurred during registration. Please try again.")
    
    # Generate verification token
    verification_token = generate_verification_token()
    verification_token_hash = hash_token(verification_token)
    token_expires = datetime.utcnow() + timedelta(hours=EMAIL_VERIFICATION_TOKEN_EXPIRES_HOURS)
    
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
        verification_token=verification_token_hash,
        verification_token_expires=token_expires
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    get_or_create_user_subscription(db, db_user.id)
    
    # Send verification email
    base_url = os.getenv("BASE_URL", DEFAULT_PUBLIC_BASE_URL)
    email_sent = send_verification_email(
        user.email,
        verification_token,
        base_url,
        expires_in_hours=EMAIL_VERIFICATION_TOKEN_EXPIRES_HOURS,
    )
    
    if not email_sent:
        # Log error but don't fail registration - user can request resend later
        print(f"Warning: Failed to send verification email to {user.email}")
        print("   User can still request a resend verification email later.")
    
    response.headers["X-Verification-Link-Expires-Hours"] = str(EMAIL_VERIFICATION_TOKEN_EXPIRES_HOURS)
    return db_user

@router.post("/login", response_model=schemas.Token)
async def login(
    request: Request,
    response: Response,
    db: Session = Depends(get_db)
):
    _enforce_rate_limit_or_429(
        request=request,
        scope="auth.login",
        limit=LOGIN_RATE_LIMIT,
        window_seconds=LOGIN_RATE_WINDOW_SECONDS,
    )

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
    _set_auth_cookie(response, access_token, int(access_token_expires.total_seconds()))
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


@router.post("/logout")
def logout(response: Response):
    _clear_auth_cookie(response)
    return {"message": "Logged out successfully."}

@router.post("/forgot-password")
def forgot_password(
    payload: schemas.PasswordResetRequest,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Request password reset. Sends a password reset email.
    """
    _enforce_rate_limit_or_429(
        request=request,
        scope="auth.forgot_password",
        limit=FORGOT_PASSWORD_RATE_LIMIT,
        window_seconds=FORGOT_PASSWORD_RATE_WINDOW_SECONDS,
    )

    email = payload.email.lower().strip()
    
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")
    
    generic_message = {
        "message": "If an account with this email exists, a password reset link has been sent."
    }

    # Find user by email
    user = db.query(models.User).filter(models.User.email == email).first()
    
    # Do not reveal whether account exists
    if not user:
        return generic_message
    
    # Generate password reset token
    reset_token = generate_verification_token()
    reset_token_hash = hash_token(reset_token)
    token_expires = datetime.utcnow() + timedelta(hours=1)  # Token expires in 1 hour
    
    # Save reset token to user
    user.password_reset_token = reset_token_hash
    user.password_reset_token_expires = token_expires
    db.commit()
    
    # Send password reset email
    base_url = os.getenv("BASE_URL", DEFAULT_PUBLIC_BASE_URL)
    email_sent = send_password_reset_email(user.email, reset_token, base_url)
    
    if not email_sent:
        # Log only, keep external response generic to prevent enumeration.
        print(f"Warning: Failed to send password reset email to {email}")

    return generic_message

@router.post("/reset-password")
def reset_password(request: schemas.PasswordReset, db: Session = Depends(get_db)):
    """
    Reset password using the reset token.
    """
    token = request.token
    new_password = request.new_password
    
    if not token:
        raise HTTPException(status_code=400, detail="Reset token is required")
    
    password_error = validate_password_strength(new_password)
    if password_error:
        raise HTTPException(status_code=400, detail=password_error)
    
    token_hash = hash_token(token)

    # Find user by hashed token, with legacy plaintext fallback support.
    user = db.query(models.User).filter(
        or_(
            models.User.password_reset_token == token_hash,
            models.User.password_reset_token == token,
        )
    ).first()
    
    if not user or not token_matches(token, user.password_reset_token):
        raise HTTPException(
            status_code=404,
            detail="Invalid or expired password reset token"
        )

    # Validate again with user context (e.g., disallow password containing email username).
    password_error_with_user = validate_password_strength(new_password, user.email)
    if password_error_with_user:
        raise HTTPException(status_code=400, detail=password_error_with_user)
    
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
    
    token_hash = hash_token(token)

    # Find user by hashed token, with legacy plaintext fallback support.
    user = db.query(models.User).filter(
        or_(
            models.User.verification_token == token_hash,
            models.User.verification_token == token,
        )
    ).first()
    
    if not user or not token_matches(token, user.verification_token):
        raise HTTPException(
            status_code=404,
            detail="Invalid or expired verification token"
        )
    
    # Check if token has expired
    if user.verification_token_expires and user.verification_token_expires < datetime.utcnow():
        raise HTTPException(
            status_code=400,
            detail=f"Verification token has expired. The link is valid for {EMAIL_VERIFICATION_TOKEN_EXPIRES_HOURS} hours. Please request a new verification email."
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
def resend_verification_email(
    payload: schemas.ResendVerificationRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db)
):
    """
    Resend verification email to user.
    """
    _enforce_rate_limit_or_429(
        request=request,
        scope="auth.resend_verification",
        limit=FORGOT_PASSWORD_RATE_LIMIT,
        window_seconds=FORGOT_PASSWORD_RATE_WINDOW_SECONDS,
    )

    email = payload.email.lower().strip()
    generic_message = {
        "message": (
            "If an account with this email exists and is not verified, a verification email has been sent. "
            f"The link expires in {EMAIL_VERIFICATION_TOKEN_EXPIRES_HOURS} hours."
        )
    }

    if not email:
        return generic_message
    
    user = db.query(models.User).filter(models.User.email == email).first()
    
    if not user:
        return generic_message
    
    # Check if already verified
    if user.email_verified:
        return generic_message
    
    # Generate new verification token
    verification_token = generate_verification_token()
    verification_token_hash = hash_token(verification_token)
    token_expires = datetime.utcnow() + timedelta(hours=EMAIL_VERIFICATION_TOKEN_EXPIRES_HOURS)
    
    user.verification_token = verification_token_hash
    user.verification_token_expires = token_expires
    db.commit()
    
    # Send verification email
    base_url = os.getenv("BASE_URL", DEFAULT_PUBLIC_BASE_URL)
    email_sent = send_verification_email(
        user.email,
        verification_token,
        base_url,
        expires_in_hours=EMAIL_VERIFICATION_TOKEN_EXPIRES_HOURS,
    )
    
    if not email_sent:
        # Keep response generic to avoid account/email state leaks.
        print(f"Warning: Failed to resend verification email to {email}")

    response.headers["X-Verification-Link-Expires-Hours"] = str(EMAIL_VERIFICATION_TOKEN_EXPIRES_HOURS)
    return generic_message


@router.post("/request-university-change")
def request_university_change(
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
        university = db.query(models.USUniversity).filter(
            models.USUniversity.email_domain == email_domain
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
    change_token_hash = hash_token(change_token)
    token_expires = datetime.utcnow() + timedelta(hours=24)
    
    # Store pending change info
    current_user.pending_email = new_email
    current_user.pending_university = new_university
    current_user.university_change_token = change_token_hash
    current_user.university_change_token_expires = token_expires
    
    db.commit()
    
    # Use configured public base URL only (do not trust request Host header).
    base_url = os.getenv("BASE_URL", DEFAULT_PUBLIC_BASE_URL).rstrip("/")
    if not base_url:
        base_url = DEFAULT_PUBLIC_BASE_URL
    
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
    
    token_hash = hash_token(token)

    # Find user by hashed token, with legacy plaintext fallback support.
    user = db.query(models.User).filter(
        or_(
            models.User.university_change_token == token_hash,
            models.User.university_change_token == token,
        )
    ).first()
    
    if not user or not token_matches(token, user.university_change_token):
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
    request: Request,
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
    _enforce_rate_limit_or_429(
        request=request,
        scope="auth.contact",
        limit=CONTACT_RATE_LIMIT,
        window_seconds=CONTACT_RATE_WINDOW_SECONDS,
    )

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


@router.get("/email-notifications/unsubscribe-preview", response_model=schemas.EmailNotificationUnsubscribePreview)
def get_email_unsubscribe_preview(
    token: str,
    db: Session = Depends(get_db),
):
    email = verify_email_notifications_unsubscribe_token(token)
    if not email:
        raise HTTPException(status_code=400, detail="Invalid or expired unsubscribe link.")

    user = db.query(models.User).filter(models.User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="Account not found for this unsubscribe link.")

    return schemas.EmailNotificationUnsubscribePreview(
        email=user.email,
        subscribed=bool(user.email_notifications_enabled),
    )


@router.post("/email-notifications/unsubscribe")
def unsubscribe_email_notifications(
    payload: schemas.EmailNotificationUnsubscribeRequest,
    db: Session = Depends(get_db),
):
    email = verify_email_notifications_unsubscribe_token(payload.token)
    if not email:
        raise HTTPException(status_code=400, detail="Invalid or expired unsubscribe link.")

    user = db.query(models.User).filter(models.User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="Account not found for this unsubscribe link.")

    reason = (payload.reason or "").strip()
    if len(reason) < 3:
        raise HTTPException(status_code=400, detail="Please provide a short reason for unsubscribing.")
    if len(reason) > 2000:
        raise HTTPException(status_code=400, detail="Reason is too long.")

    user.email_notifications_enabled = False
    user.email_notifications_unsubscribed_at = datetime.utcnow()
    user.email_notifications_unsubscribe_reason = reason or None
    db.commit()

    feedback_subject = "Email Notification Unsubscribe Feedback"
    feedback_message = (
        f"User email: {user.email}\n"
        f"User id: {user.id}\n"
        f"Unsubscribed at (UTC): {user.email_notifications_unsubscribed_at.isoformat() if user.email_notifications_unsubscribed_at else 'N/A'}\n"
        f"Reason: {reason or 'No reason provided'}"
    )
    # Best-effort feedback forwarding; unsubscribe should succeed regardless.
    try:
        send_contact_form_email(
            name=user.full_name or user.username or user.email.split("@")[0],
            email=user.email,
            subject=feedback_subject,
            message=feedback_message,
            user_type="student",
        )
    except Exception:
        pass

    return {"message": "You have unsubscribed from email notifications successfully."}
