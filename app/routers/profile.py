from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from urllib.parse import urlparse
import os
from app.database import get_db
from app import models, schemas
from app.auth import (
    get_current_active_user,
    verify_password,
    get_password_hash,
    validate_password_strength,
)
from app.referrals import ensure_user_referral_code
from app.utils.rate_limiter import check_ip_rate_limit

router = APIRouter(prefix="/api/profile", tags=["profile"])
CHANGE_PASSWORD_RATE_LIMIT = int(os.getenv("CHANGE_PASSWORD_RATE_LIMIT", "5"))
CHANGE_PASSWORD_RATE_WINDOW_SECONDS = int(os.getenv("CHANGE_PASSWORD_RATE_WINDOW_SECONDS", "900"))


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
        "reward": "Both users receive 1 month Pro after email verification and first login",
    }

@router.put("/", response_model=schemas.UserResponse)
def update_profile(
    user_update: schemas.UserUpdate,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Update current user's profile"""
    update_data = user_update.dict(exclude_unset=True)
    
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
    return current_user


@router.post("/change-password")
def change_password(
    payload: schemas.PasswordChangeRequest,
    request: Request,
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
    db.commit()

    return {
        "message": "Password changed successfully. Please log in again on any other devices for security."
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


@router.delete("/", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Delete the current user's account and all associated data"""
    user_id = current_user.id
    
    # Delete the user explicitly; related documents will be removed by cascade
    db.delete(current_user)
    db.commit()
    
    return None
