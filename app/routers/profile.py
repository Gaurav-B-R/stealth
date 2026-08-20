from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from sqlalchemy.orm import Session
from urllib.parse import urlparse
import os
import logging
from app.database import get_db
from app import models, schemas, visa_catalog
from app.auth import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    ACCESS_TOKEN_REFRESH_HEADER,
    AUTH_COOKIE_NAME,
    create_access_token,
    get_current_active_user,
    set_auth_cookie,
    verify_password,
    get_password_hash,
    validate_password_strength,
)
from app import referrals
from app.referrals import ensure_user_referral_code
from app.utils.rate_limiter import check_ip_rate_limit
from app.utils.security import rewrap_file_key, decode_salt_from_storage
from app.utils.token_security import hash_token, token_matches
from app.email_service import send_account_deletion_otp_email, send_country_change_otp_email
from datetime import datetime, timedelta
import secrets

router = APIRouter(prefix="/api/profile", tags=["profile"])
logger = logging.getLogger(__name__)
CHANGE_PASSWORD_RATE_LIMIT = int(os.getenv("CHANGE_PASSWORD_RATE_LIMIT", "5"))
CHANGE_PASSWORD_RATE_WINDOW_SECONDS = int(os.getenv("CHANGE_PASSWORD_RATE_WINDOW_SECONDS", "900"))
# Account deletion requires an emailed 6-digit OTP as a second factor.
ACCOUNT_DELETE_OTP_EXPIRES_MINUTES = int(os.getenv("ACCOUNT_DELETE_OTP_EXPIRES_MINUTES", "10"))
ACCOUNT_DELETE_OTP_RATE_LIMIT = int(os.getenv("ACCOUNT_DELETE_OTP_RATE_LIMIT", "5"))
ACCOUNT_DELETE_OTP_RATE_WINDOW_SECONDS = int(os.getenv("ACCOUNT_DELETE_OTP_RATE_WINDOW_SECONDS", "900"))
ACCOUNT_DELETE_VERIFY_RATE_LIMIT = int(os.getenv("ACCOUNT_DELETE_VERIFY_RATE_LIMIT", "10"))
ACCOUNT_DELETE_VERIFY_RATE_WINDOW_SECONDS = int(os.getenv("ACCOUNT_DELETE_VERIFY_RATE_WINDOW_SECONDS", "900"))
# Changing the destination country requires an emailed 6-digit OTP as a second factor.
COUNTRY_CHANGE_OTP_EXPIRES_MINUTES = int(os.getenv("COUNTRY_CHANGE_OTP_EXPIRES_MINUTES", "10"))
COUNTRY_CHANGE_OTP_RATE_LIMIT = int(os.getenv("COUNTRY_CHANGE_OTP_RATE_LIMIT", "5"))
COUNTRY_CHANGE_OTP_RATE_WINDOW_SECONDS = int(os.getenv("COUNTRY_CHANGE_OTP_RATE_WINDOW_SECONDS", "900"))
COUNTRY_CHANGE_VERIFY_RATE_LIMIT = int(os.getenv("COUNTRY_CHANGE_VERIFY_RATE_LIMIT", "10"))
COUNTRY_CHANGE_VERIFY_RATE_WINDOW_SECONDS = int(os.getenv("COUNTRY_CHANGE_VERIFY_RATE_WINDOW_SECONDS", "900"))

# Documents that carry over on a country change (portable, real-world artifacts). Anything
# NOT in this set and NOT in the new country's checklist is country-specific (I-20, DS-160,
# SEVIS, CAS, GIC, CoE, OSHC, visa forms/stamps…) and is removed on confirm.
UNIVERSAL_REUSABLE_DOCUMENT_TYPES = {
    "passport",
    "photograph-2x2",
    # academics / transcripts / certificates
    "high-school-transcripts", "bachelors-transcript", "masters-transcript",
    "academic-transcripts", "other-school-college-degree-certificates",
    "provisional-certificates", "experience-letters", "salary-slips",
    # English / standardized tests
    "english-language-test", "standardized-test-scores", "standardized-test-scores-gre-gmat",
    # statements / CV
    "statement-of-purpose-lors", "resume",
    # finances
    "bank-statement", "bank-balance-certificate", "loan-approval-letter", "loan-sanction-letter",
    "affidavit-of-support", "ca-statement", "sponsor-income-proof",
    "financial-evidence", "proof-of-funds", "financial-capacity-evidence",
}


def _generate_delete_otp() -> str:
    """A 6-digit numeric code emailed to confirm account deletion."""
    return f"{secrets.randbelow(1_000_000):06d}"


# Checklist keys that appear in MORE THAN ONE country's checklist yet name inherently
# country-bound artifacts: a UK "Online Visa Application Confirmation" and AU's
# "ImmiAccount Visa Application Confirmation" share the key "visa-application-form",
# and Document rows carry no country — so without this set, a validated UK form
# would silently satisfy AU's stage-5 gate after a UK→AU destination change.
COUNTRY_BOUND_SHARED_DOCUMENT_TYPES = {
    "visa-application-form",            # UK ↔ AU
    "biometrics-confirmation",          # CA ↔ AU
    "biometric-appointment-confirmation",  # US ↔ UK
    "visa-fee-receipt",                 # US ↔ DE
    "university-offer-letter",          # US/UK/AU — offers are institution-bound
    "accommodation-proof",              # UK/CA/AU/DE — booked in the old country
}


def _prune_documents_for_country_change(
    db: Session,
    user: models.User,
    new_country: str,
    new_visa: str,
    old_country: str | None = None,
) -> list[str]:
    """Delete documents that are specific to the OLD country and not needed in the new one.

    Keeps the student's portable documents (passport, transcripts, test scores, financials,
    SOP, resume, photo) and anything present in the NEW country's checklist. Removes the rest
    (I-20/DS-160/SEVIS/CAS/GIC/CoE/OSHC/visa forms…), including their R2 objects. Untyped
    uploads are always kept. Returns the list of removed document types.

    When the destination COUNTRY actually changed, keys in COUNTRY_BOUND_SHARED_DOCUMENT_TYPES
    are pruned even if the new checklist reuses the key — the old country's artifact does not
    satisfy the new country's requirement. A same-country visa-type change keeps them.
    """
    new_types = {
        (d.get("document_type") or "").strip()
        for d in visa_catalog.documents_for(new_country, new_visa)
    }
    country_changed = bool(old_country) and old_country != new_country
    if country_changed:
        new_types -= COUNTRY_BOUND_SHARED_DOCUMENT_TYPES
    keep_types = UNIVERSAL_REUSABLE_DOCUMENT_TYPES | new_types

    documents = db.query(models.Document).filter(models.Document.user_id == user.id).all()
    removed: list[str] = []
    r2_client = R2_DOCUMENTS_BUCKET = None
    try:
        from app.routers.documents import r2_client as _r2, R2_DOCUMENTS_BUCKET as _bucket
        r2_client, R2_DOCUMENTS_BUCKET = _r2, _bucket
    except Exception:
        pass

    for doc in documents:
        dtype = (doc.document_type or "").strip()
        # Keep untyped uploads and anything reusable / in the new checklist.
        if not dtype or dtype in keep_types:
            continue
        if r2_client is not None:
            for key in (doc.filename, doc.extracted_text_file_url):
                if not key:
                    continue
                try:
                    r2_client.delete_object(Bucket=R2_DOCUMENTS_BUCKET, Key=key)
                except Exception:
                    pass  # best-effort; object may already be gone
        db.delete(doc)
        removed.append(dtype)
    return removed


def _purge_all_user_r2_objects(db: Session, user: models.User) -> int:
    """Erase every R2 object belonging to a user (documents, extracted text, profile snapshot).

    Called on account deletion so the actual sensitive files are removed from object storage —
    not just their database rows. The DB cascade removes the Document rows but does NOT touch
    R2, so without this a user's uploaded passports / financial statements would linger in
    storage indefinitely after they delete their account (a right-to-erasure gap). Best-effort:
    a failure on one object is logged but must not block the deletion. Returns keys attempted.
    """
    r2_client = R2_DOCUMENTS_BUCKET = None
    try:
        from app.routers.documents import r2_client as _r2, R2_DOCUMENTS_BUCKET as _bucket
        r2_client, R2_DOCUMENTS_BUCKET = _r2, _bucket
    except Exception:
        pass
    if r2_client is None:
        logger.warning("delete_account: R2 client unavailable; could not purge objects for user_id=%s", user.id)
        return 0

    # Read every object key BEFORE the DB rows are cascade-deleted.
    keys: list[str] = []
    for doc in db.query(models.Document).filter(models.Document.user_id == user.id).all():
        if doc.filename:
            keys.append(doc.filename)
        if doc.extracted_text_file_url:
            keys.append(doc.extracted_text_file_url)
    keys.append(f"user_{user.id}/STUDENT_PROFILE_AND_F1_VISA_STATUS.json")

    for key in keys:
        try:
            r2_client.delete_object(Bucket=R2_DOCUMENTS_BUCKET, Key=key)
        except Exception:
            logger.warning("delete_account: failed to delete R2 object key=%s for user_id=%s", key, user.id)
    logger.info("delete_account: purged %s R2 object(s) for user_id=%s", len(keys), user.id)
    return len(keys)


def _is_safe_profile_picture_url(value: str) -> bool:
    """Allow only absolute http(s) URLs or root-relative paths."""
    if not value:
        return False

    candidate = value.strip()
    if not candidate:
        return False

    if candidate.startswith("/"):
        return True

    parsed = urlparse(candidate)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


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


def _refresh_student_profile_snapshot_safe(db: Session, user_id: int) -> None:
    try:
        from app.routers.documents import refresh_student_profile_snapshot_for_user_id
        refresh_student_profile_snapshot_for_user_id(user_id=user_id, db=db)
    except Exception:
        logger.exception(
            "Failed to refresh STUDENT_PROFILE_AND_F1_VISA_STATUS.json for user_id=%s",
            user_id,
        )


@router.get("/", response_model=schemas.UserResponse)
def get_profile(
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get current user's profile"""
    ensure_user_referral_code(db, current_user, commit=True)
    return current_user


@router.get("/referral-summary")
def get_referral_summary(
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    code = ensure_user_referral_code(db, current_user, commit=True)

    total_invited = db.query(models.User).filter(
        models.User.referred_by_user_id == current_user.id
    ).count()
    successful_referrals = db.query(models.User).filter(
        models.User.referred_by_user_id == current_user.id,
        models.User.referral_reward_granted_at.isnot(None)
    ).count()
    pending_referrals = max(total_invited - successful_referrals, 0)

    return {
        "referral_code": code,
        "total_invited": total_invited,
        "successful_referrals": successful_referrals,
        "pending_referrals": pending_referrals,
        "reward": referrals.referral_reward_summary(),
        "referee_discount_display": referrals.referee_discount_display(),
        # The reward is a flat ₹200 off ₹999 that checkout applies as the same PROPORTION
        # in whatever currency the friend buys in. The percentage is the only figure that
        # is true in every currency, so the UI can render an accurate local amount from
        # the price ladder instead of quoting rupees to a dollar buyer.
        "referee_discount_percent": referrals.referee_discount_percent(),
        "referrer_bonus_days": referrals.REFERRAL_BONUS_DAYS,
    }

@router.put("/", response_model=schemas.UserResponse)
def update_profile(
    user_update: schemas.UserUpdate,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Update current user's profile"""
    update_data = user_update.dict(exclude_unset=True)

    # Don't let a user blank out their name — it breaks greetings ("Hi !") and
    # downstream personalization. Trim and require non-empty.
    if "full_name" in update_data:
        cleaned_name = (update_data.get("full_name") or "").strip()
        if not cleaned_name:
            raise HTTPException(status_code=400, detail="Please enter your full name.")
        update_data["full_name"] = cleaned_name

    # University is not editable - it's derived from .edu email at registration
    protected_fields = {'university', 'email', 'username', 'is_active', 'is_verified'}
    
    for field, value in update_data.items():
        if field not in protected_fields:
            if field == "profile_picture" and value is not None and not _is_safe_profile_picture_url(value):
                raise HTTPException(
                    status_code=400,
                    detail="Invalid profile picture URL. Only http(s) URLs or relative paths are allowed."
                )
            setattr(current_user, field, value)
    
    db.commit()
    db.refresh(current_user)
    _refresh_student_profile_snapshot_safe(db=db, user_id=current_user.id)
    return current_user


def _rewrap_encrypted_documents_on_password_change(
    db: Session,
    user: models.User,
    old_password: str,
    new_password: str,
) -> None:
    """Rotate the password-derived wrapping key on every encrypted document the user owns.

    The file-key wrapping key is derived from the user's password, so without this step
    every document encrypted under the old password would become permanently
    undecryptable after a change. Only the wrapping key is rotated — the per-file content
    key and the ciphertext in object storage are untouched.

    Mutates Document rows in the current session; the caller commits them atomically with
    the new password hash. Keys that can't be unwrapped with the current password were
    already orphaned by an earlier reset — they're logged and left as-is so we never
    overwrite a recoverable key with a bad value.
    """
    if not user.encryption_salt:
        return
    documents = (
        db.query(models.Document)
        .filter(
            models.Document.user_id == user.id,
            models.Document.encrypted_file_key.isnot(None),
        )
        .all()
    )
    if not documents:
        return
    try:
        salt_bytes = decode_salt_from_storage(user.encryption_salt)
    except Exception:
        logger.exception(
            "change_password: could not decode encryption_salt for user_id=%s", user.id
        )
        return

    rewrapped = 0
    orphaned = 0
    for document in documents:
        try:
            document.encrypted_file_key = rewrap_file_key(
                document.encrypted_file_key,
                old_password,
                new_password,
                salt_bytes,
            )
            rewrapped += 1
        except Exception:
            orphaned += 1
            logger.warning(
                "change_password: could not re-wrap document_id=%s for user_id=%s "
                "(likely orphaned by an earlier reset); leaving as-is.",
                document.id,
                user.id,
            )
    logger.info(
        "change_password: re-wrapped %s document key(s), %s unrecoverable, for user_id=%s",
        rewrapped,
        orphaned,
        user.id,
    )


@router.post("/change-password")
def change_password(
    payload: schemas.PasswordChangeRequest,
    request: Request,
    response: Response,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Change current user's password after verifying the current password."""
    _enforce_rate_limit_or_429(
        request=request,
        scope="profile.change_password",
        limit=CHANGE_PASSWORD_RATE_LIMIT,
        window_seconds=CHANGE_PASSWORD_RATE_WINDOW_SECONDS,
    )

    current_password = payload.current_password or ""
    new_password = payload.new_password or ""

    if not current_password:
        raise HTTPException(status_code=400, detail="Current password is required.")
    if not new_password:
        raise HTTPException(status_code=400, detail="New password is required.")

    if not verify_password(current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")

    if verify_password(new_password, current_user.hashed_password):
        raise HTTPException(
            status_code=400,
            detail="New password must be different from your current password."
        )

    password_error = validate_password_strength(new_password, current_user.email)
    if password_error:
        raise HTTPException(status_code=400, detail=password_error)

    # Re-wrap encrypted document keys from the old password to the new one BEFORE the
    # hash changes, so the user keeps access to files encrypted under the current
    # password. Without this, the password-derived wrapping key would change and every
    # encrypted document would become permanently undecryptable.
    _rewrap_encrypted_documents_on_password_change(
        db=db,
        user=current_user,
        old_password=current_password,
        new_password=new_password,
    )

    try:
        current_user.hashed_password = get_password_hash(new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="An error occurred while updating your password."
        )

    # Invalidate any pending reset token after successful password change.
    current_user.password_reset_token = None
    current_user.password_reset_token_expires = None

    # Revoke every OTHER signed-in session. Sessions renew themselves on each authenticated
    # request, so a session opened on a shared or stolen device would otherwise outlive the
    # password it was created under — leaving the old password's holder with access forever.
    # This used to be delegated to the user ("please log in again on any other devices"),
    # which is advice, not enforcement.
    invalidated_at = datetime.utcnow()
    current_user.session_invalidated_at = invalidated_at
    db.commit()

    # ...but not the browser making this request. get_current_active_user already refreshed
    # the cookie DURING dependency resolution — that token was minted before the line above,
    # so if the request straddles a second boundary it would now be rejected and the user
    # would be logged out for changing their own password. Mint a replacement AFTER the
    # invalidation instant and re-issue it on the same channel the caller authenticated on.
    fresh_token = create_access_token(
        data={"sub": current_user.email},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    if request.cookies.get(AUTH_COOKIE_NAME):
        set_auth_cookie(request, response, fresh_token)
    else:
        response.headers[ACCESS_TOKEN_REFRESH_HEADER] = fresh_token

    return {
        "message": "Password changed successfully. You've been signed out on all other devices."
    }

@router.get("/documentation-preferences")
def get_documentation_preferences(
    current_user: models.User = Depends(get_current_active_user)
):
    """Get user's documentation preferences"""
    return {
        "country": current_user.preferred_country or "United States",
        "intake": current_user.preferred_intake,
        "year": current_user.preferred_year
    }

@router.put("/documentation-preferences")
def update_documentation_preferences(
    preferences: schemas.DocumentationPreferences,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Update user's documentation preferences (country, intake, year)"""
    if preferences.country:
        current_user.preferred_country = preferences.country
    if preferences.intake:
        current_user.preferred_intake = preferences.intake
    if preferences.year:
        current_user.preferred_year = preferences.year
    
    db.commit()
    db.refresh(current_user)
    _refresh_student_profile_snapshot_safe(db=db, user_id=current_user.id)
    
    return {
        "message": "Documentation preferences updated successfully",
        "preferences": {
            "country": current_user.preferred_country,
            "intake": current_user.preferred_intake,
            "year": current_user.preferred_year
        }
    }


@router.post("/email-notifications/subscribe")
def subscribe_email_notifications(
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Re-enable email notifications for the current user."""
    if current_user.email_notifications_enabled:
        return {"message": "Email notifications are already enabled."}

    current_user.email_notifications_enabled = True
    current_user.email_notifications_unsubscribed_at = None
    current_user.email_notifications_unsubscribe_reason = None
    db.commit()
    db.refresh(current_user)
    _refresh_student_profile_snapshot_safe(db=db, user_id=current_user.id)

    return {"message": "Email notifications enabled successfully."}

# Note: This route must come AFTER specific paths like /documentation-preferences
# because {user_id} would otherwise match any path segment
@router.get("/{user_id}", response_model=schemas.PublicUserResponse)
def get_user_profile(
    user_id: int,
    db: Session = Depends(get_db)
):
    """Get a user's public profile (safe non-sensitive fields only)."""
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return user


@router.post("/delete/request-code", status_code=status.HTTP_200_OK)
def request_account_deletion_code(
    request: Request,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Email a 6-digit code the user must enter to confirm account deletion."""
    _enforce_rate_limit_or_429(
        request=request,
        scope="profile.delete.request_code",
        limit=ACCOUNT_DELETE_OTP_RATE_LIMIT,
        window_seconds=ACCOUNT_DELETE_OTP_RATE_WINDOW_SECONDS,
        extra_key=f"user:{current_user.id}",
    )
    code = _generate_delete_otp()
    current_user.account_deletion_otp = hash_token(code)
    current_user.account_deletion_otp_expires = datetime.utcnow() + timedelta(
        minutes=ACCOUNT_DELETE_OTP_EXPIRES_MINUTES
    )
    db.commit()
    send_account_deletion_otp_email(
        current_user.email, code, expires_in_minutes=ACCOUNT_DELETE_OTP_EXPIRES_MINUTES
    )
    return {
        "message": "A confirmation code has been sent to your email.",
        "expires_in_minutes": ACCOUNT_DELETE_OTP_EXPIRES_MINUTES,
    }


@router.delete("/", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    payload: schemas.AccountDeleteRequest,
    request: Request,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Delete the account — requires the emailed OTP as a second factor (security)."""
    _enforce_rate_limit_or_429(
        request=request,
        scope="profile.delete.verify",
        limit=ACCOUNT_DELETE_VERIFY_RATE_LIMIT,
        window_seconds=ACCOUNT_DELETE_VERIFY_RATE_WINDOW_SECONDS,
        extra_key=f"user:{current_user.id}",
    )
    code = "".join(ch for ch in str(payload.code or "") if ch.isdigit())
    expires = current_user.account_deletion_otp_expires
    if expires is not None and getattr(expires, "tzinfo", None) is not None:
        expires = expires.replace(tzinfo=None)

    if (
        not current_user.account_deletion_otp
        or expires is None
        or expires < datetime.utcnow()
        or len(code) != 6
        or not token_matches(code, current_user.account_deletion_otp)
    ):
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired confirmation code. Request a new code and try again.",
        )

    # Erase the user's sensitive files from object storage BEFORE removing the DB rows. The DB
    # cascade deletes Document rows but does NOT touch R2, so this prevents uploaded passports /
    # financial documents from lingering in storage after account deletion (right-to-erasure).
    try:
        _purge_all_user_r2_objects(db, current_user)
    except Exception:
        logger.exception("delete_account: R2 purge failed for user_id=%s; proceeding with DB delete", current_user.id)

    # Retain payment (financial) records for accounting/tax obligations, but sever the PII link:
    # null the user_id so the row survives account deletion de-identified rather than being
    # cascade-deleted. Amounts + Razorpay IDs remain for reconciliation; the user link does not.
    try:
        db.query(models.SubscriptionPayment).filter(
            models.SubscriptionPayment.user_id == current_user.id
        ).update({models.SubscriptionPayment.user_id: None}, synchronize_session=False)
    except Exception:
        logger.exception("delete_account: failed to de-link payment records for user_id=%s", current_user.id)

    # The user's saved enterprise AI-assistant threads (a B2C member can also belong to a
    # consultancy workspace) are NOT covered by the users-table cascade — delete them
    # explicitly, messages first, or the dangling FK breaks the user delete on Postgres.
    try:
        _ai_conv_ids = [
            cid for (cid,) in db.query(models.EnterpriseAiConversation.id).filter(
                models.EnterpriseAiConversation.user_id == current_user.id
            ).all()
        ]
        if _ai_conv_ids:
            db.query(models.EnterpriseAiMessage).filter(
                models.EnterpriseAiMessage.conversation_id.in_(_ai_conv_ids)
            ).delete(synchronize_session=False)
            db.query(models.EnterpriseAiConversation).filter(
                models.EnterpriseAiConversation.id.in_(_ai_conv_ids)
            ).delete(synchronize_session=False)
    except Exception:
        logger.exception("delete_account: failed to purge enterprise AI threads for user_id=%s", current_user.id)

    # B2C shortlist + Course Finder rows have no ORM cascade (no User relationship) and
    # their tables are created by schema_patch without FK constraints, so the users-table
    # cascade never reaches them — delete explicitly or they orphan (right-to-erasure).
    try:
        db.query(models.UserCourseFinderRec).filter(
            models.UserCourseFinderRec.user_id == current_user.id
        ).delete(synchronize_session=False)
        db.query(models.UniversityShortlistEntry).filter(
            models.UniversityShortlistEntry.user_id == current_user.id
        ).delete(synchronize_session=False)
    except Exception:
        logger.exception("delete_account: failed to purge shortlist/course-finder rows for user_id=%s", current_user.id)

    # Verified — delete the user explicitly; other related data is removed by cascade.
    db.delete(current_user)
    db.commit()
    return None


@router.post("/country/request-code", status_code=status.HTTP_200_OK)
def request_country_change_code(
    payload: schemas.CountryChangeRequest,
    request: Request,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Email a 6-digit code to confirm changing the student's destination country."""
    _enforce_rate_limit_or_429(
        request=request,
        scope="profile.country.request_code",
        limit=COUNTRY_CHANGE_OTP_RATE_LIMIT,
        window_seconds=COUNTRY_CHANGE_OTP_RATE_WINDOW_SECONDS,
        extra_key=f"user:{current_user.id}",
    )
    country = visa_catalog.normalize_country(payload.destination_country_code)
    if not country:
        raise HTTPException(status_code=400, detail="Please choose a valid destination country.")
    visa = visa_catalog.normalize_visa_type(country, payload.visa_type_key) or visa_catalog.default_visa_type(country)
    if not visa:
        raise HTTPException(status_code=400, detail="Please choose a valid visa type for this country.")

    if country == (current_user.destination_country_code or "") and visa == (current_user.visa_type_key or ""):
        raise HTTPException(status_code=400, detail="That is already your current destination and visa type.")

    code = _generate_delete_otp()
    current_user.country_change_otp = hash_token(code)
    current_user.country_change_otp_expires = datetime.utcnow() + timedelta(
        minutes=COUNTRY_CHANGE_OTP_EXPIRES_MINUTES
    )
    current_user.country_change_pending_country = country
    current_user.country_change_pending_visa = visa
    db.commit()

    country_name = (visa_catalog.country_meta(country) or {}).get("name", country)
    send_country_change_otp_email(
        current_user.email, code, country_name=country_name,
        expires_in_minutes=COUNTRY_CHANGE_OTP_EXPIRES_MINUTES,
    )
    return {
        "message": "A confirmation code has been sent to your email.",
        "destination_country_code": country,
        "visa_type_key": visa,
        "country_name": country_name,
        "visa_type_label": visa_catalog.visa_type_label(country, visa),
        "expires_in_minutes": COUNTRY_CHANGE_OTP_EXPIRES_MINUTES,
    }


@router.post("/country/confirm", response_model=schemas.UserResponse)
def confirm_country_change(
    payload: schemas.CountryChangeConfirm,
    request: Request,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Verify the emailed code, then switch destination country and re-scope everything."""
    _enforce_rate_limit_or_429(
        request=request,
        scope="profile.country.confirm",
        limit=COUNTRY_CHANGE_VERIFY_RATE_LIMIT,
        window_seconds=COUNTRY_CHANGE_VERIFY_RATE_WINDOW_SECONDS,
        extra_key=f"user:{current_user.id}",
    )
    code = "".join(ch for ch in str(payload.code or "") if ch.isdigit())
    expires = current_user.country_change_otp_expires
    if expires is not None and getattr(expires, "tzinfo", None) is not None:
        expires = expires.replace(tzinfo=None)

    if (
        not current_user.country_change_otp
        or not current_user.country_change_pending_country
        or expires is None
        or expires < datetime.utcnow()
        or len(code) != 6
        or not token_matches(code, current_user.country_change_otp)
    ):
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired confirmation code. Request a new code and try again.",
        )

    country = visa_catalog.normalize_country(current_user.country_change_pending_country)
    visa = (
        visa_catalog.normalize_visa_type(country, current_user.country_change_pending_visa)
        or visa_catalog.default_visa_type(country)
    )
    if not country or not visa:
        raise HTTPException(status_code=400, detail="Pending destination is no longer valid. Please try again.")

    # Apply the new destination + visa, keep the legacy display country in sync.
    old_country = visa_catalog.normalize_country(current_user.destination_country_code)
    current_user.destination_country_code = country
    current_user.visa_type_key = visa
    meta = visa_catalog.country_meta(country)
    if meta and meta.get("name"):
        current_user.preferred_country = meta["name"]

    # Remove documents specific to the old country (keep passport + portable docs).
    removed_types = _prune_documents_for_country_change(
        db, current_user, country, visa, old_country=old_country
    )

    # Clear the one-time OTP state.
    current_user.country_change_otp = None
    current_user.country_change_otp_expires = None
    current_user.country_change_pending_country = None
    current_user.country_change_pending_visa = None

    db.commit()
    db.refresh(current_user)
    _refresh_student_profile_snapshot_safe(db=db, user_id=current_user.id)
    logger.info(
        "Country change confirmed for user_id=%s -> %s/%s (removed %d country-specific docs)",
        current_user.id, country, visa, len(removed_types),
    )
    return current_user


# Rate limit for the data-export endpoint (right of access / portability).
DATA_EXPORT_RATE_LIMIT = int(os.getenv("DATA_EXPORT_RATE_LIMIT", "5"))
DATA_EXPORT_RATE_WINDOW_SECONDS = int(os.getenv("DATA_EXPORT_RATE_WINDOW_SECONDS", "3600"))


def _iso(value):
    """Serialize a datetime/date to ISO-8601, or pass through None."""
    return value.isoformat() if value is not None and hasattr(value, "isoformat") else value


@router.get("/export")
def export_my_data(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """Self-service data export (GDPR right of access / data portability, India DPDP).

    Returns a machine-readable JSON copy of the account data we hold about the user:
    profile, consents, subscription, and document metadata. Document file *contents*
    are not included — they can be downloaded individually from the dashboard (and E2E
    files can only be decrypted client-side with the user's passphrase).
    """
    from fastapi.responses import JSONResponse

    check_ip_rate_limit(
        request=request,
        scope="profile.data_export",
        limit=DATA_EXPORT_RATE_LIMIT,
        window_seconds=DATA_EXPORT_RATE_WINDOW_SECONDS,
    )

    u = current_user
    subscription = (
        db.query(models.Subscription)
        .filter(models.Subscription.user_id == u.id)
        .first()
    )
    documents = (
        db.query(models.Document)
        .filter(models.Document.user_id == u.id)
        .order_by(models.Document.created_at.desc())
        .all()
    )

    export = {
        "export_generated_at": datetime.utcnow().isoformat() + "Z",
        "notice": (
            "This is a copy of the personal data Rilono holds about your account. "
            "Document file contents are not included; download them from your dashboard. "
            "For questions contact contact@rilono.com."
        ),
        "account": {
            "id": u.id,
            "email": u.email,
            "username": u.username,
            "full_name": u.full_name,
            "university": getattr(u, "university", None),
            "university_email": getattr(u, "university_email", None),
            "phone": getattr(u, "phone", None),
            "current_residence_country": getattr(u, "current_residence_country", None),
            "preferred_country": getattr(u, "preferred_country", None),
            "destination_country_code": getattr(u, "destination_country_code", None),
            "visa_type_key": getattr(u, "visa_type_key", None),
            "auth_provider": getattr(u, "auth_provider", None),
            "email_verified": getattr(u, "email_verified", None),
            "referral_code": getattr(u, "referral_code", None),
            "referred_by_user_id": getattr(u, "referred_by_user_id", None),
            "created_at": _iso(getattr(u, "created_at", None)),
            "first_login_at": _iso(getattr(u, "first_login_at", None)),
            "last_login_at": _iso(getattr(u, "last_login_at", None)),
            "onboarding_completed_at": _iso(getattr(u, "onboarding_completed_at", None)),
        },
        "consents": {
            "accepted_terms_privacy_at": _iso(getattr(u, "accepted_terms_privacy_at", None)),
            "accepted_terms_privacy_version": getattr(u, "accepted_terms_privacy_version", None),
            "accepted_terms_privacy_ip": getattr(u, "accepted_terms_privacy_ip", None),
            "age_confirmed_at": _iso(getattr(u, "age_confirmed_at", None)),
            "marketing_emails_consent": getattr(u, "marketing_emails_consent", None),
            "marketing_emails_consent_at": _iso(getattr(u, "marketing_emails_consent_at", None)),
            "email_notifications_enabled": getattr(u, "email_notifications_enabled", None),
        },
        "subscription": None if subscription is None else {
            "plan": subscription.plan,
            "status": subscription.status,
            "started_at": _iso(getattr(subscription, "started_at", None)),
            "ends_at": _iso(getattr(subscription, "ends_at", None)),
            "ai_messages_used": getattr(subscription, "ai_messages_used", None),
        },
        "documents": [
            {
                "id": d.id,
                "original_filename": d.original_filename,
                "document_type": d.document_type,
                "country": d.country,
                "file_size": d.file_size,
                "is_encrypted_end_to_end": bool(getattr(d, "e2e_scheme", None)),
                "created_at": _iso(getattr(d, "created_at", None)),
            }
            for d in documents
        ],
    }

    filename = f"rilono-data-export-{u.id}-{datetime.utcnow().strftime('%Y%m%d')}.json"
    return JSONResponse(
        content=export,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
