from fastapi import APIRouter, Depends, HTTPException, status, Request, Form, Response
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from sqlalchemy import or_
from datetime import timedelta, datetime
from urllib.parse import urlparse
from app.database import get_db
from app import models, schemas
from app.legal import LEGAL_TERMS_PRIVACY_VERSION
from app.auth import (
    authenticate_user,
    create_access_token,
    get_password_hash,
    get_current_active_user,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    validate_password_strength,
    is_enterprise_only_account,
    ENTERPRISE_ACCOUNT_ON_B2C_DETAIL,
    _decode_token_subject,
)
from app.email_service import (
    generate_verification_token,
    send_verification_email,
    send_email_otp,
    send_password_reset_email,
    send_contact_form_email,
    send_feature_request_confirmation,
    send_founder_new_verified_user_alert,
    send_student_welcome_email,
    verify_email_notifications_unsubscribe_token,
)
from app.utils.turnstile import is_turnstile_enabled, verify_turnstile_token
from app.subscriptions import get_or_create_user_subscription
from app.referrals import (
    ensure_user_referral_code,
    generate_unique_referral_code,
    get_user_by_referral_code,
    is_disposable_email,
    maybe_award_referral_bonus_on_login,
)
from app.utils.rate_limiter import (
    check_ip_rate_limit,
    extract_client_ip,
    is_request_ip_whitelisted,
)
from app.utils.token_security import hash_token, token_matches
import os
import logging

router = APIRouter(prefix="/api/auth", tags=["authentication"])
logger = logging.getLogger(__name__)
DEFAULT_PUBLIC_BASE_URL = "https://rilono.com"

# B2C: when open (default), students can sign up / log in with ANY email (Gmail etc.)
# and university becomes optional. Set false to restore the university-domain gate.
B2C_OPEN_SIGNUP = os.getenv("B2C_OPEN_SIGNUP", "true").strip().lower() in {"1", "true", "yes", "on"}

REGISTER_RATE_LIMIT = int(os.getenv("REGISTER_RATE_LIMIT", "5"))
REGISTER_RATE_WINDOW_SECONDS = int(os.getenv("REGISTER_RATE_WINDOW_SECONDS", "900"))
LOGIN_RATE_LIMIT = int(os.getenv("LOGIN_RATE_LIMIT", "12"))
LOGIN_RATE_WINDOW_SECONDS = int(os.getenv("LOGIN_RATE_WINDOW_SECONDS", "300"))
FORGOT_PASSWORD_RATE_LIMIT = int(os.getenv("FORGOT_PASSWORD_RATE_LIMIT", "5"))
FORGOT_PASSWORD_RATE_WINDOW_SECONDS = int(os.getenv("FORGOT_PASSWORD_RATE_WINDOW_SECONDS", "900"))
CONTACT_RATE_LIMIT = int(os.getenv("CONTACT_RATE_LIMIT", "5"))
CONTACT_RATE_WINDOW_SECONDS = int(os.getenv("CONTACT_RATE_WINDOW_SECONDS", "1800"))
EMAIL_VERIFICATION_TOKEN_EXPIRES_HOURS = int(os.getenv("EMAIL_VERIFICATION_TOKEN_EXPIRES_HOURS", "24"))
# Stepped signup uses a short-lived 6-digit OTP (hashed into verification_token).
EMAIL_OTP_EXPIRES_MINUTES = int(os.getenv("EMAIL_OTP_EXPIRES_MINUTES", "10"))
OTP_VERIFY_RATE_LIMIT = int(os.getenv("OTP_VERIFY_RATE_LIMIT", "10"))
OTP_VERIFY_RATE_WINDOW_SECONDS = int(os.getenv("OTP_VERIFY_RATE_WINDOW_SECONDS", "300"))
OTP_RESEND_RATE_LIMIT = int(os.getenv("OTP_RESEND_RATE_LIMIT", "5"))
OTP_RESEND_RATE_WINDOW_SECONDS = int(os.getenv("OTP_RESEND_RATE_WINDOW_SECONDS", "600"))
AUTH_COOKIE_NAME = os.getenv("AUTH_COOKIE_NAME", "rilono_access_token").strip() or "rilono_access_token"


def _generate_email_otp() -> str:
    """A 6-digit numeric one-time code for email verification."""
    import secrets as _s
    return f"{_s.randbelow(1_000_000):06d}"


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _refresh_student_profile_snapshot_safe(db: Session, user_id: int) -> None:
    """
    Best-effort sync of STUDENT_PROFILE_AND_F1_VISA_STATUS.json after account changes.
    """
    try:
        from app.routers.documents import refresh_student_profile_snapshot_for_user_id
        refresh_student_profile_snapshot_for_user_id(user_id=user_id, db=db)
    except Exception:
        logger.exception(
            "Failed to refresh STUDENT_PROFILE_AND_F1_VISA_STATUS.json for user_id=%s",
            user_id,
        )


def _send_founder_verified_user_alert_safe(user: models.User) -> None:
    if not user or not user.email:
        return
    try:
        send_founder_new_verified_user_alert(
            user_id=user.id,
            user_email=user.email,
            full_name=user.full_name,
            university=user.university,
            current_residence_country=getattr(user, "current_residence_country", None),
            verified_at=datetime.utcnow(),
        )
    except Exception:
        logger.exception("Failed to send founder verified-user alert for user_id=%s", user.id)


def _cookie_secure_default() -> bool:
    env = os.getenv("ENVIRONMENT", "production").strip().lower()
    return env != "development"


def _is_development_env() -> bool:
    return os.getenv("ENVIRONMENT", "production").strip().lower() == "development"


def _is_turnstile_required() -> bool:
    return is_turnstile_enabled() and not _is_development_env()


AUTH_COOKIE_SECURE = _bool_env("AUTH_COOKIE_SECURE", _cookie_secure_default())
AUTH_COOKIE_DOMAIN = (os.getenv("AUTH_COOKIE_DOMAIN", "").strip() or None)
# Default "lax" so the auth cookie survives the OAuth redirect landing (see app/auth.py).
_cookie_samesite_raw = os.getenv("AUTH_COOKIE_SAMESITE", "lax").strip().lower()
AUTH_COOKIE_SAMESITE = _cookie_samesite_raw if _cookie_samesite_raw in {"lax", "strict", "none"} else "lax"
ENFORCE_LOGOUT_CSRF_ORIGIN_CHECK = _bool_env("ENFORCE_LOGOUT_CSRF_ORIGIN_CHECK", True)

if not AUTH_COOKIE_SECURE and _cookie_secure_default():
    raise RuntimeError(
        "AUTH_COOKIE_SECURE must be true outside development. "
        "Refusing to start with insecure auth cookies."
    )


def _is_local_hostname(hostname: str) -> bool:
    host = (hostname or "").strip().lower()
    return (
        host in {"localhost", "127.0.0.1", "::1", "localtest.me", "lvh.me"}
        or host.endswith(".localtest.me")
        or host.endswith(".lvh.me")
    )


def _request_uses_https(request: Request) -> bool:
    forwarded_proto = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    if forwarded_proto:
        return forwarded_proto == "https"
    return request.url.scheme == "https"


def _resolve_auth_cookie_secure(request: Request) -> bool:
    if AUTH_COOKIE_SECURE:
        return True

    # Fail-safe: in non-development deployments, never issue insecure auth cookies.
    if _cookie_secure_default():
        return True

    # Development-only exception: allow insecure cookies only for local HTTP usage.
    if _is_local_hostname(request.url.hostname) and not _request_uses_https(request):
        return False
    return True


def _effective_cookie_domain(request: Request) -> str | None:
    """The configured cookie domain, but only when it actually matches the request host.
    A cookie whose Domain= doesn't match the host is silently dropped by the browser
    (e.g. Domain=.lvh.me on a localhost OAuth callback), so fall back to a host-only
    cookie in that case instead of losing the session."""
    if not AUTH_COOKIE_DOMAIN:
        return None
    host = (request.url.hostname or "").strip().lower()
    base = AUTH_COOKIE_DOMAIN.lstrip(".").lower()
    if host == base or host.endswith("." + base):
        return AUTH_COOKIE_DOMAIN
    return None


def _set_auth_cookie(request: Request, response: Response, access_token: str, max_age_seconds: int) -> None:
    secure_cookie = _resolve_auth_cookie_secure(request)
    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=access_token,
        max_age=max_age_seconds,
        httponly=True,
        secure=secure_cookie,
        samesite=AUTH_COOKIE_SAMESITE,
        domain=_effective_cookie_domain(request),
        path="/",
    )


def _clear_auth_cookie(response: Response, request: Request | None = None) -> None:
    # Clear EVERY domain variant the cookie could have been set with (host-only AND the
    # configured domain), so a domain mismatch can never leave the session cookie behind.
    domains: list[str | None] = [None]
    if AUTH_COOKIE_DOMAIN and AUTH_COOKIE_DOMAIN not in domains:
        domains.append(AUTH_COOKIE_DOMAIN)
    if request is not None:
        eff = _effective_cookie_domain(request)
        if eff and eff not in domains:
            domains.append(eff)
    for d in domains:
        response.delete_cookie(key=AUTH_COOKIE_NAME, domain=d, path="/")


def _normalize_origin(value: str | None) -> str | None:
    candidate = (value or "").split(",")[0].strip()
    if not candidate:
        return None
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def _parse_csrf_trusted_origins() -> set[str]:
    raw = os.getenv("CSRF_TRUSTED_ORIGINS", "").strip()
    if raw:
        values = {_normalize_origin(item) for item in raw.split(",")}
        return {item for item in values if item}

    if _is_development_env():
        return {
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:8000",
            "http://127.0.0.1:8000",
        }

    return {
        "https://rilono.com",
        "https://www.rilono.com",
    }


CSRF_TRUSTED_ORIGINS = _parse_csrf_trusted_origins()


def _request_origin(request: Request) -> str | None:
    forwarded_proto = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    scheme = forwarded_proto if forwarded_proto in {"http", "https"} else request.url.scheme.lower()
    host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc).split(",")[0].strip().lower()
    if not host:
        return None
    return f"{scheme}://{host}"


def _origin_is_trusted_for_request(request: Request) -> bool:
    request_origin = _request_origin(request)

    origin = _normalize_origin(request.headers.get("origin"))
    if origin:
        return origin == request_origin or origin in CSRF_TRUSTED_ORIGINS

    referer = _normalize_origin(request.headers.get("referer"))
    if referer:
        return referer == request_origin or referer in CSRF_TRUSTED_ORIGINS

    return False


def _enforce_logout_csrf_guard(request: Request) -> None:
    """
    Protect cookie-authenticated logout from cross-site form submissions.
    """
    if not ENFORCE_LOGOUT_CSRF_ORIGIN_CHECK:
        return
    if AUTH_COOKIE_NAME not in request.cookies:
        return
    if _is_development_env():
        return
    if _origin_is_trusted_for_request(request):
        return
    raise HTTPException(status_code=403, detail="Cross-site logout request blocked.")


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
    if not is_turnstile_enabled():
        return {"site_key": ""}
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

    # Age confirmation. Minors need a parent/guardian to consent on their behalf
    # (India DPDP: under 18; EU/UK GDPR: under 16). We capture a self-attestation
    # here; true verifiable parental consent is a separate, fuller flow.
    if not user.age_confirmed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You must confirm you are 18 or older, or that a parent/guardian agrees on your behalf, to register."
        )

    # Whitelisted IPs (configured via IP_WHITELIST) can bypass Turnstile gating.
    turnstile_token = user.cf_turnstile_token
    ip_whitelisted = is_request_ip_whitelisted(request)
    if is_turnstile_enabled() and not ip_whitelisted:
        if turnstile_token:
            client_ip = extract_client_ip(request) if request else None
            if not verify_turnstile_token(turnstile_token, client_ip):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Security verification failed. Please try again."
                )
        elif _is_turnstile_required():
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
        # Auto-fill university from the domain when we recognize it.
        university = db.query(models.USUniversity).filter(
            models.USUniversity.email_domain == email_domain
        ).first()
        if university:
            university_name = university.university_name
        elif B2C_OPEN_SIGNUP:
            # Open B2C signup: any email is allowed; university is optional.
            university_name = None
        else:
            raise HTTPException(
                status_code=403,
                detail="Registration is restricted to students with valid university email addresses. Please use your university email domain."
            )
    
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
        # Anti-abuse: don't bind a referral for obvious throwaway signups. The
        # valuable reward is additionally gated at purchase time (same-device + cap),
        # so a self-referrer can never earn a free pass without a real payment.
        if referrer and is_disposable_email(user.email):
            referrer = None
    
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
    
    # Generate a 6-digit email OTP (hashed at rest, short-lived).
    otp_code = _generate_email_otp()
    verification_token_hash = hash_token(otp_code)
    token_expires = datetime.utcnow() + timedelta(minutes=EMAIL_OTP_EXPIRES_MINUTES)

    # Capture proof-of-consent: when, from where (IP + user agent), and which
    # version of the legal documents was agreed to.
    now = datetime.utcnow()
    consent_ip = extract_client_ip(request) if request else None
    consent_user_agent = (request.headers.get("user-agent") if request else None) or None
    if consent_user_agent:
        consent_user_agent = consent_user_agent[:1000]

    # First-touch acquisition attribution (where this signup came from).
    from app import acquisition
    acq = acquisition.classify(
        utm_source=user.acq_source,
        utm_medium=user.acq_medium,
        utm_campaign=user.acq_campaign,
        referrer=user.acq_referrer,
        has_referral_code=bool(referrer),
    )
    acq_landing = (user.acq_landing or "").strip()[:500] or None

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
        acquisition_channel=acq["acquisition_channel"],
        acquisition_source=acq["acquisition_source"],
        acquisition_medium=acq["acquisition_medium"],
        acquisition_campaign=acq["acquisition_campaign"],
        acquisition_referrer=acq["acquisition_referrer"],
        acquisition_landing_page=acq_landing,
        accepted_terms_privacy_at=now,
        accepted_terms_privacy_ip=consent_ip,
        accepted_terms_privacy_user_agent=consent_user_agent,
        accepted_terms_privacy_version=LEGAL_TERMS_PRIVACY_VERSION,
        age_confirmed_at=now,
        marketing_emails_consent=bool(user.marketing_emails_consent),
        marketing_emails_consent_at=(now if user.marketing_emails_consent else None),
        email_verified=False,
        verification_token=verification_token_hash,
        verification_token_expires=token_expires
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    get_or_create_user_subscription(db, db_user.id)
    _refresh_student_profile_snapshot_safe(db=db, user_id=db_user.id)
    
    # Email the 6-digit code for the stepped signup flow.
    email_sent = send_email_otp(
        user.email,
        otp_code,
        expires_in_minutes=EMAIL_OTP_EXPIRES_MINUTES,
    )

    if not email_sent:
        # Log error but don't fail registration - user can request a resend.
        print(f"Warning: Failed to send verification OTP to {user.email}")
        print("   User can request a new code via /api/auth/resend-otp.")

    response.headers["X-OTP-Expires-Minutes"] = str(EMAIL_OTP_EXPIRES_MINUTES)
    return db_user


@router.post("/verify-otp", response_model=schemas.Token)
def verify_otp(
    payload: schemas.OtpVerifyRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Verify the 6-digit signup OTP and, on success, auto-login (set the cookie)."""
    _enforce_rate_limit_or_429(
        request=request,
        scope="auth.verify_otp",
        limit=OTP_VERIFY_RATE_LIMIT,
        window_seconds=OTP_VERIFY_RATE_WINDOW_SECONDS,
    )
    email = (payload.email or "").strip().lower()
    code = "".join(ch for ch in str(payload.code or "") if ch.isdigit())
    invalid = HTTPException(status_code=400, detail="Invalid or expired code. Please try again or resend.")

    user = db.query(models.User).filter(models.User.email == email).first()
    if not user or len(code) != 6:
        raise invalid
    if user.email_verified:
        raise HTTPException(status_code=400, detail="This email is already verified. Please log in.")

    expires = user.verification_token_expires
    if expires is not None and getattr(expires, "tzinfo", None) is not None:
        expires = expires.replace(tzinfo=None)
    if not user.verification_token or expires is None or expires < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Your code has expired. Tap resend to get a new one.")
    if not token_matches(code, user.verification_token):
        raise invalid

    # Product separation: an Enterprise (B2B) account must never obtain a B2C session, not even
    # through the signup email-verification step. Checked AFTER the OTP is validated (like the
    # login gate is checked after the password) so this endpoint can't be used to enumerate which
    # emails are Enterprise accounts. (Enterprise accounts are created already verified, so this
    # path is normally unreachable for them — this is defense-in-depth.)
    if is_enterprise_only_account(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ENTERPRISE_ACCOUNT_ON_B2C_DETAIL,
        )

    # Verified — clear the OTP and treat this as the first login.
    user.email_verified = True
    user.verification_token = None
    user.verification_token_expires = None
    now = datetime.utcnow()
    if user.first_login_at is None:
        user.first_login_at = now
    user.last_login_at = now
    ensure_user_referral_code(db, user, commit=False)
    reward_payload: dict = {}
    try:
        reward_payload = maybe_award_referral_bonus_on_login(db, user, commit=False) or {}
    except Exception:
        reward_payload = {}
    db.commit()
    try:
        _refresh_student_profile_snapshot_safe(db=db, user_id=user.id)
    except Exception:
        pass

    # Warm welcome email — best-effort, never block verification.
    try:
        send_student_welcome_email(to_email=user.email, full_name=user.full_name or "")
    except Exception:
        logger.exception("Student welcome email failed for %s", user.email)

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(data={"sub": user.email}, expires_delta=access_token_expires)
    _set_auth_cookie(request, response, access_token, int(access_token_expires.total_seconds()))
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "referral_bonus_awarded": bool(reward_payload.get("awarded")),
        "referral_bonus_message": reward_payload.get("message"),
    }


@router.post("/resend-otp")
def resend_otp(
    payload: schemas.OtpResendRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Email a fresh signup OTP. Always returns a generic message (no account enumeration)."""
    _enforce_rate_limit_or_429(
        request=request,
        scope="auth.resend_otp",
        limit=OTP_RESEND_RATE_LIMIT,
        window_seconds=OTP_RESEND_RATE_WINDOW_SECONDS,
    )
    email = (payload.email or "").strip().lower()
    generic = {"message": "If that account exists and isn't verified yet, a new code is on its way."}

    user = db.query(models.User).filter(models.User.email == email).first()
    if not user or user.email_verified:
        return generic

    otp_code = _generate_email_otp()
    user.verification_token = hash_token(otp_code)
    user.verification_token_expires = datetime.utcnow() + timedelta(minutes=EMAIL_OTP_EXPIRES_MINUTES)
    db.commit()
    send_email_otp(user.email, otp_code, expires_in_minutes=EMAIL_OTP_EXPIRES_MINUTES)
    return generic


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
    
    ip_whitelisted = is_request_ip_whitelisted(request)
    if is_turnstile_enabled() and not ip_whitelisted:
        if turnstile_token:
            client_ip = extract_client_ip(request) if request else None
            if not verify_turnstile_token(turnstile_token, client_ip):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Security verification failed. Please try again."
                )
        elif _is_turnstile_required():
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

    # Product separation: an Enterprise (B2B) account can't sign in to the individual/B2C app,
    # even with the correct password. They belong on the Enterprise portal. (Checked only after
    # the password is verified so we never disclose enterprise status to a wrong-password guess.)
    if is_enterprise_only_account(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ENTERPRISE_ACCOUNT_ON_B2C_DETAIL,
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
    
    if not dev_email and not B2C_OPEN_SIGNUP:
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
    refresh_profile_snapshot = not had_referral_code

    reward_payload = {"awarded": False, "message": None}
    now = datetime.utcnow()
    changes_pending = False
    if user.first_login_at is None:
        user.first_login_at = now
        changes_pending = True
        refresh_profile_snapshot = True
    user.last_login_at = now
    changes_pending = True

    reward_payload = maybe_award_referral_bonus_on_login(db, user, commit=False)
    if reward_payload.get("awarded"):
        changes_pending = True
        refresh_profile_snapshot = True

    if changes_pending:
        db.commit()
        if refresh_profile_snapshot:
            _refresh_student_profile_snapshot_safe(db=db, user_id=user.id)
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    # Store email in token instead of username
    access_token = create_access_token(
        data={"sub": user.email}, expires_delta=access_token_expires
    )
    _set_auth_cookie(request, response, access_token, int(access_token_expires.total_seconds()))
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "referral_bonus_awarded": bool(reward_payload.get("awarded")),
        "referral_bonus_message": reward_payload.get("message"),
    }


# ===========================================================================
# Social login (OAuth) — Google / Microsoft / Apple
# ===========================================================================

import secrets as _secrets
from jose import jwt as _jose_jwt, JWTError as _JWTError
from fastapi.responses import RedirectResponse
from app import oauth as social_oauth
from app.auth import SECRET_KEY as _AUTH_SECRET_KEY, ALGORITHM as _AUTH_ALGORITHM

OAUTH_STATE_TTL_SECONDS = int(os.getenv("OAUTH_STATE_TTL_SECONDS", "600"))
OAUTH_RATE_LIMIT = int(os.getenv("OAUTH_RATE_LIMIT", "20"))
OAUTH_RATE_WINDOW_SECONDS = int(os.getenv("OAUTH_RATE_WINDOW_SECONDS", "300"))


def _oauth_state_encode(provider: str, nonce: str, *, consent: bool = False) -> str:
    payload = {
        "p": provider, "n": nonce,
        # Whether the user affirmatively accepted the Terms & Privacy (and age) before
        # starting this flow. Required to create a *new* account via social login.
        "c": bool(consent),
        "v": LEGAL_TERMS_PRIVACY_VERSION,
        "exp": datetime.utcnow() + timedelta(seconds=OAUTH_STATE_TTL_SECONDS),
        "iat": datetime.utcnow(),
    }
    return _jose_jwt.encode(payload, _AUTH_SECRET_KEY, algorithm=_AUTH_ALGORITHM)


def _oauth_state_decode(token: str) -> dict:
    return _jose_jwt.decode(token, _AUTH_SECRET_KEY, algorithms=[_AUTH_ALGORITHM])


OAUTH_NONCE_COOKIE_NAME = os.getenv("OAUTH_NONCE_COOKIE_NAME", "rilono_oauth_nonce").strip() or "rilono_oauth_nonce"


def _set_oauth_nonce_cookie(request: Request, response: Response, nonce: str) -> None:
    """Bind the OAuth flow to THIS browser: store the flow nonce in a short-lived HttpOnly
    cookie at /start and require it to match the state nonce at /callback. An attacker can't
    set this cookie in a victim's browser, which blocks login-CSRF / session fixation.

    Apple returns via a cross-site POST (form_post), and a SameSite=lax cookie is NOT sent on
    cross-site POST — so use SameSite=none (requires Secure) on https. On local http we fall
    back to lax (Secure/None is invalid without https; Apple isn't tested on localhost).
    """
    secure = _resolve_auth_cookie_secure(request)
    samesite = "none" if secure else "lax"
    response.set_cookie(
        key=OAUTH_NONCE_COOKIE_NAME,
        value=nonce,
        max_age=OAUTH_STATE_TTL_SECONDS,
        httponly=True,
        secure=secure,
        samesite=samesite,
        domain=_effective_cookie_domain(request),
        path="/",
    )


def _clear_oauth_nonce_cookie(response: Response, request: Request | None = None) -> None:
    domains: list[str | None] = [None]
    if request is not None:
        eff = _effective_cookie_domain(request)
        if eff and eff not in domains:
            domains.append(eff)
    for d in domains:
        response.delete_cookie(key=OAUTH_NONCE_COOKIE_NAME, domain=d, path="/")


def _app_redirect(path: str, *, error: str | None = None) -> RedirectResponse:
    base = os.getenv("BASE_URL", DEFAULT_PUBLIC_BASE_URL).rstrip("/")
    target = path if path.startswith("http") else f"{base}{path}"
    if error:
        sep = "&" if "?" in target else "?"
        from urllib.parse import quote as _q
        target = f"{target}{sep}auth_error={_q(error)}"
    return RedirectResponse(url=target, status_code=302)


class _OAuthConsentRequired(Exception):
    """Raised when a social login would create a *new* account but the user has not
    affirmatively accepted the Terms & Privacy (and age confirmation)."""


def _find_or_create_oauth_user(
    db: Session,
    *,
    email: str,
    name: str | None,
    provider: str,
    consent: bool = False,
    consent_ip: str | None = None,
    consent_user_agent: str | None = None,
) -> models.User:
    """Find an existing user by email or create a verified one for this provider.

    For a brand-new account, an affirmative consent is required; otherwise
    ``_OAuthConsentRequired`` is raised so the caller can send the user to the
    sign-up page to accept the Terms. Existing users are logged in unchanged.
    """
    email = (email or "").strip().lower()
    user = db.query(models.User).filter(models.User.email == email).first()
    if user:
        # An Enterprise (B2B) account can't sign in to the B2C app via social login. Return it
        # UNCHANGED so the caller's product-separation gate rejects it — never link a provider or
        # mutate the row on a login we're about to deny (keeps "existing users logged in unchanged").
        if is_enterprise_only_account(user):
            return user
        if not user.auth_provider:
            user.auth_provider = provider
        if not user.email_verified:
            user.email_verified = True  # provider has verified the email
        db.commit()
        return user

    # New account: never silently accept the Terms on the user's behalf.
    if not consent:
        raise _OAuthConsentRequired()

    # Username from email local-part, de-duplicated.
    base_username = (email.split("@")[0] or "user")[:40]
    username = base_username
    counter = 1
    while db.query(models.User).filter(models.User.username == username).first():
        username = f"{base_username}{counter}"
        counter += 1

    # Auto-fill university only when the domain is recognized; otherwise optional.
    domain = extract_email_domain(email)
    university = (
        db.query(models.USUniversity).filter(models.USUniversity.email_domain == domain).first()
        if domain else None
    )

    now = datetime.utcnow()
    user = models.User(
        email=email,
        username=username,
        hashed_password=get_password_hash(_secrets.token_urlsafe(32)),  # unusable; reset to set one
        full_name=(name or None),
        university=(university.university_name if university else None),
        current_residence_country="United States",
        referral_code=generate_unique_referral_code(db),
        accepted_terms_privacy_at=now,
        accepted_terms_privacy_ip=consent_ip,
        accepted_terms_privacy_user_agent=consent_user_agent,
        accepted_terms_privacy_version=LEGAL_TERMS_PRIVACY_VERSION,
        age_confirmed_at=now,
        email_verified=True,
        auth_provider=provider,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    get_or_create_user_subscription(db, user.id)
    _refresh_student_profile_snapshot_safe(db=db, user_id=user.id)
    # New OAuth signup → warm welcome email (best-effort; provider already verified email).
    try:
        send_student_welcome_email(to_email=user.email, full_name=user.full_name or "")
    except Exception:
        logger.exception("Student welcome email failed for OAuth user %s", user.email)
    return user


@router.get("/oauth/providers")
def oauth_providers():
    """List the social-login providers that are currently configured (have env creds)."""
    return {"providers": social_oauth.enabled_providers()}


@router.get("/oauth/{provider}/start")
def oauth_start(provider: str, request: Request, consent: bool = False):
    provider = (provider or "").strip().lower()
    if not social_oauth.is_enabled(provider):
        return _app_redirect("/login", error="This sign-in option isn't available right now.")
    _enforce_rate_limit_or_429(
        request=request, scope="auth.oauth.start",
        limit=OAUTH_RATE_LIMIT, window_seconds=OAUTH_RATE_WINDOW_SECONDS,
    )
    nonce = _secrets.token_urlsafe(16)
    # `consent=1` is appended by the sign-up view once the user ticks the consent box;
    # it authorizes creating a new account on this social login.
    state = _oauth_state_encode(provider, nonce, consent=bool(consent))
    resp = RedirectResponse(url=social_oauth.build_authorize_url(provider, state=state, nonce=nonce), status_code=302)
    # Bind this flow to the browser so the callback can't be replayed in someone else's session.
    _set_oauth_nonce_cookie(request, resp, nonce)
    return resp


@router.api_route("/oauth/{provider}/callback", methods=["GET", "POST"])
async def oauth_callback(provider: str, request: Request, db: Session = Depends(get_db)):
    provider = (provider or "").strip().lower()
    if provider not in social_oauth.PROVIDERS:
        return _app_redirect("/login", error="Unknown sign-in provider.")

    # Apple posts the callback as form data; others use query params.
    if request.method == "POST":
        form = await request.form()
        params = dict(form)
    else:
        params = dict(request.query_params)

    if params.get("error"):
        return _app_redirect("/login", error="Sign-in was cancelled.")

    code = params.get("code")
    state = params.get("state")
    if not code or not state:
        return _app_redirect("/login", error="Sign-in response was incomplete.")
    try:
        decoded = _oauth_state_decode(state)
        if decoded.get("p") != provider:
            raise ValueError("provider mismatch")
    except (_JWTError, ValueError):
        return _app_redirect("/login", error="Your sign-in link expired. Please try again.")

    # Login-CSRF / session-fixation defense: the state nonce must match the HttpOnly cookie set
    # on THIS browser at /start. An attacker can't set that cookie in a victim's browser, so a
    # pre-generated flow can't be completed in (and hijack) someone else's session.
    cookie_nonce = (request.cookies.get(OAUTH_NONCE_COOKIE_NAME) or "").strip()
    state_nonce = str(decoded.get("n") or "")
    if not cookie_nonce or not state_nonce or not _secrets.compare_digest(cookie_nonce, state_nonce):
        resp = _app_redirect("/login", error="Your sign-in session couldn't be verified. Please try again.")
        _clear_oauth_nonce_cookie(resp, request)
        return resp

    try:
        tokens = social_oauth.exchange_code(provider, code)
        identity = social_oauth.fetch_identity(provider, tokens, apple_user=params.get("user"))
    except Exception as exc:
        logger.warning("OAuth callback failed (%s): %s", provider, exc)
        return _app_redirect("/login", error=str(exc) or "Could not complete sign-in.")

    # Proof-of-consent for new social accounts: which version, from where.
    consent_given = bool(decoded.get("c"))
    consent_ip = extract_client_ip(request) if request else None
    consent_user_agent = (request.headers.get("user-agent") if request else None) or None
    if consent_user_agent:
        consent_user_agent = consent_user_agent[:1000]
    try:
        user = _find_or_create_oauth_user(
            db,
            email=identity["email"],
            name=identity.get("name"),
            provider=provider,
            consent=consent_given,
            consent_ip=consent_ip,
            consent_user_agent=consent_user_agent,
        )
    except _OAuthConsentRequired:
        # New user arrived without accepting the Terms (e.g. used social from the
        # login view). Send them to sign-up to accept before the account is created.
        return _app_redirect(
            "/register",
            error="Please accept the Terms & Conditions and Privacy Policy to create your account.",
        )
    if not user.is_active:
        return _app_redirect("/login", error="Your account is deactivated. Please contact support.")

    # Product separation: an Enterprise (B2B) account can't sign in to the individual/B2C app
    # via social login either. (A brand-new OAuth account created just above is B2C-origin, so
    # its flag is False and it is NOT blocked — only pre-existing enterprise accounts are.)
    if is_enterprise_only_account(user):
        return _app_redirect("/login", error=ENTERPRISE_ACCOUNT_ON_B2C_DETAIL)

    now = datetime.utcnow()
    if user.first_login_at is None:
        user.first_login_at = now
    user.last_login_at = now
    ensure_user_referral_code(db, user, commit=False)
    try:
        maybe_award_referral_bonus_on_login(db, user, commit=False)
    except Exception:
        pass
    db.commit()

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(data={"sub": user.email}, expires_delta=access_token_expires)
    response = _app_redirect("/dashboard")
    _set_auth_cookie(request, response, access_token, int(access_token_expires.total_seconds()))
    _clear_oauth_nonce_cookie(response, request)  # one-time use — drop the flow nonce
    logger.info(
        "OAuth login OK: %s via %s | host=%s scheme=%s | cookie name=%s secure=%s domain=%r samesite=%s -> %s",
        user.email, provider, request.url.hostname, request.url.scheme, AUTH_COOKIE_NAME,
        _resolve_auth_cookie_secure(request), _effective_cookie_domain(request), AUTH_COOKIE_SAMESITE,
        response.headers.get("location"),
    )
    return response


@router.get("/me", response_model=schemas.UserResponse)
def read_users_me(
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    get_or_create_user_subscription(db, current_user.id)
    had_referral_code = bool(current_user.referral_code)
    ensure_user_referral_code(db, current_user, commit=True)
    if not had_referral_code and current_user.referral_code:
        _refresh_student_profile_snapshot_safe(db=db, user_id=current_user.id)
    return current_user


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    # Logout must NEVER fail silently. We always clear the cookie and invalidate the
    # session server-side. We do NOT hard-block on the CSRF origin check here: a forced
    # cross-site logout is low severity, whereas a logout that doesn't take effect is a
    # real security problem. (Login/sensitive actions remain CSRF-guarded elsewhere.)
    _clear_auth_cookie(response, request)

    # Invalidate every access token issued for this user up to now, so any lingering
    # token copy in the browser (localStorage/cookie/cache) is rejected on next use.
    token = (request.cookies.get(AUTH_COOKIE_NAME) or "").strip()
    if not token:
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()
    if token:
        try:
            email = (_decode_token_subject(token) or "").strip()
        except Exception:
            email = ""
        if email:
            user = db.query(models.User).filter(models.User.email == email).first()
            if user is not None:
                user.session_invalidated_at = datetime.utcnow()
                db.commit()

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
    turnstile_token = (payload.cf_turnstile_token or "").strip()
    ip_whitelisted = is_request_ip_whitelisted(request)
    
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")

    if is_turnstile_enabled() and not ip_whitelisted:
        if turnstile_token:
            client_ip = extract_client_ip(request) if request else None
            if not verify_turnstile_token(turnstile_token, client_ip):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Security verification failed. Please try again."
                )
        elif _is_turnstile_required():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Security verification is required"
            )
    
    generic_message = {
        "message": (
            "If an account with this email exists, a password reset email has been requested. "
            "Check your inbox and spam folder in a few minutes."
        )
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
    
    # Password reset is transactional; do not gate it on email_notifications_enabled.
    base_url = os.getenv("BASE_URL", DEFAULT_PUBLIC_BASE_URL)
    email_accepted = send_password_reset_email(user.email, reset_token, base_url)
    
    if not email_accepted:
        # Log only, keep external response generic to prevent enumeration.
        print(f"Warning: Email provider did not accept password reset email for {email}")

    return generic_message

@router.post("/reset-password")
def reset_password(
    payload: schemas.PasswordReset,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Reset password using the reset token.
    """
    token = payload.token
    new_password = payload.new_password
    turnstile_token = (payload.cf_turnstile_token or "").strip()

    ip_whitelisted = is_request_ip_whitelisted(request)
    if is_turnstile_enabled() and not ip_whitelisted:
        if turnstile_token:
            client_ip = extract_client_ip(request) if request else None
            if not verify_turnstile_token(turnstile_token, client_ip):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Security verification failed. Please try again."
                )
        elif _is_turnstile_required():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Security verification is required"
            )
    
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
    enterprise_credential = (
        db.query(models.EnterpriseCredential)
        .filter(models.EnterpriseCredential.email == user.email)
        .first()
    )
    if enterprise_credential:
        enterprise_credential.password_hash = hashed_password

    # Encrypted documents are protected by a key derived from the password. A reset has
    # no access to the OLD password, so file keys wrapped under it cannot be re-wrapped
    # and those documents are unrecoverable by design (the inherent trade-off of
    # user-held keys). Unlike a password *change* — which re-wraps keys — we can only be
    # honest about it here, so the user isn't left thinking files are intact.
    orphaned_encrypted_documents = (
        db.query(models.Document)
        .filter(
            models.Document.user_id == user.id,
            models.Document.encrypted_file_key.isnot(None),
        )
        .count()
    )
    db.commit()

    if orphaned_encrypted_documents:
        logger.warning(
            "reset_password: %s encrypted document(s) for user_id=%s are now unrecoverable "
            "(no old password to re-wrap their keys).",
            orphaned_encrypted_documents,
            user.id,
        )
        return {
            "message": (
                "Password reset successfully! You can now log in with your new password. "
                "Note: documents you encrypted before this reset were protected by your "
                "previous password and can no longer be decrypted — please re-upload them."
            ),
            "encrypted_documents_unrecoverable": orphaned_encrypted_documents,
        }

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
    _send_founder_verified_user_alert_safe(user)
    _refresh_student_profile_snapshot_safe(db=db, user_id=user.id)
    
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
    _refresh_student_profile_snapshot_safe(db=db, user_id=current_user.id)
    
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
        _refresh_student_profile_snapshot_safe(db=db, user_id=user.id)
        
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
    _refresh_student_profile_snapshot_safe(db=db, user_id=user.id)
    
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
    _refresh_student_profile_snapshot_safe(db=db, user_id=current_user.id)
    
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
        # The in-app "Feature Request" modal posts here with subject "Feature Request: <title>".
        # Send the requester a warm confirmation (best-effort — never fail the submit on it).
        subject_clean = subject.strip()
        if subject_clean.lower().startswith("feature request:"):
            try:
                feature_title = subject_clean.split(":", 1)[1].strip() or subject_clean
                send_feature_request_confirmation(
                    to_email=email.strip(),
                    full_name=name.strip(),
                    request_summary=feature_title,
                    product="Rilono",
                )
            except Exception:
                logging.getLogger(__name__).exception("Feature-request confirmation email failed")
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

    # App-level notification opt-out only; provider suppression can block account recovery emails.
    user.email_notifications_enabled = False
    user.email_notifications_unsubscribed_at = datetime.utcnow()
    user.email_notifications_unsubscribe_reason = reason or None
    db.commit()
    _refresh_student_profile_snapshot_safe(db=db, user_id=user.id)

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


@router.get("/marketing-emails/preference", response_model=schemas.MarketingEmailPreferenceResponse)
def get_marketing_email_preference(
    current_user: models.User = Depends(get_current_active_user),
):
    """Return the signed-in user's current marketing-email consent state."""
    return schemas.MarketingEmailPreferenceResponse(
        marketing_emails_consent=bool(current_user.marketing_emails_consent),
        marketing_emails_consent_at=current_user.marketing_emails_consent_at,
    )


@router.post("/marketing-emails/preference", response_model=schemas.MarketingEmailPreferenceResponse)
def set_marketing_email_preference(
    payload: schemas.MarketingEmailPreferenceRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """Let a signed-in user opt in or out of marketing emails at any time.

    This is the in-app 'unsubscribe whenever you want' control. Setting it to
    False removes the user from the marketing audience on the next sync; the
    timestamp records when consent was last changed (proof of consent)."""
    enabled = bool(payload.enabled)
    if bool(current_user.marketing_emails_consent) != enabled:
        current_user.marketing_emails_consent = enabled
        current_user.marketing_emails_consent_at = datetime.utcnow()
        db.commit()
        db.refresh(current_user)
    return schemas.MarketingEmailPreferenceResponse(
        marketing_emails_consent=bool(current_user.marketing_emails_consent),
        marketing_emails_consent_at=current_user.marketing_emails_consent_at,
    )
