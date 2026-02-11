from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from urllib.parse import urlparse
from app.database import get_db
from app import models, schemas
from app.auth import get_current_active_user
from app.referrals import ensure_user_referral_code

router = APIRouter(prefix="/api/profile", tags=["profile"])


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
