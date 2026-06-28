"""Post-signup onboarding for the personalized student journey.

Collects the student's destination country + visa type (required) and a few optional
details (home country, university, university email, intake). The destination + visa
type drive the entire personalized dashboard journey (see app/visa_catalog.py).
"""
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models, schemas
from app import visa_catalog
from app import enterprise_catalog
from app.auth import get_current_active_user
from app.database import get_db

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])


def _onboarding_state(user: models.User) -> dict:
    code = getattr(user, "destination_country_code", None)
    visa = getattr(user, "visa_type_key", None)
    completed = getattr(user, "onboarding_completed_at", None)
    return {
        "completed": completed is not None,
        "completed_at": completed.isoformat() if completed else None,
        "destination_country_code": code,
        "visa_type_key": visa,
        "visa_type_label": visa_catalog.visa_type_label(code, visa) if code and visa else None,
        "university": user.university,
        "university_email": getattr(user, "university_email", None),
        "home_country": user.current_residence_country,
        "intake": getattr(user, "preferred_intake", None),
    }


@router.get("/catalog")
def onboarding_catalog():
    """Countries + visa types + intakes for the onboarding wizard."""
    return visa_catalog.onboarding_catalog_payload()


@router.get("/status")
def onboarding_status(current_user: models.User = Depends(get_current_active_user)):
    return _onboarding_state(current_user)


@router.post("", response_model=schemas.UserResponse)
@router.post("/", response_model=schemas.UserResponse)
def submit_onboarding(
    payload: schemas.OnboardingRequest = Body(...),
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Save the student's destination + visa type (required) and optional details."""
    country = visa_catalog.normalize_country(payload.destination_country_code)
    if not country:
        raise HTTPException(status_code=400, detail="Please choose a valid destination country.")
    visa = visa_catalog.normalize_visa_type(country, payload.visa_type_key)
    if not visa:
        raise HTTPException(status_code=400, detail="Please choose a valid visa type for this country.")

    current_user.destination_country_code = country
    current_user.visa_type_key = visa

    # Keep the legacy documentation-preferences country in sync (display name).
    meta = enterprise_catalog.get_country(country)
    if meta and meta.get("name"):
        current_user.preferred_country = meta["name"]

    # Optional fields — only overwrite when provided.
    home = (payload.home_country or "").strip()
    if home:
        current_user.current_residence_country = home
    university = (payload.university or "").strip()
    if university:
        current_user.university = university
    university_email = (payload.university_email or "").strip().lower()
    if university_email:
        current_user.university_email = university_email
    intake = (payload.intake or "").strip()
    if intake:
        current_user.preferred_intake = intake

    if current_user.onboarding_completed_at is None:
        current_user.onboarding_completed_at = datetime.utcnow()

    db.commit()
    db.refresh(current_user)

    # Refresh the student's R2 profile snapshot so AI guidance picks up the new
    # destination/visa immediately (best-effort; never blocks onboarding).
    try:
        from app.routers.profile import _refresh_student_profile_snapshot_safe
        _refresh_student_profile_snapshot_safe(db=db, user_id=current_user.id)
    except Exception:
        pass

    return current_user
