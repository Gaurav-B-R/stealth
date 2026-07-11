"""University shortlisting + AI recommendations (B2C student dashboard).

- GET    /api/shortlist            list the student's saved universities
- POST   /api/shortlist            add a university (manual, or saved from an AI rec)
- PATCH  /api/shortlist/{id}       update status / notes
- DELETE /api/shortlist/{id}       remove a university
- POST   /api/shortlist/recommend  AI university recommendations (Visa-Pass gated)
"""
import os
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app import models
from app import visa_catalog
from app import visa_pass
from app import university_shortlist
from app import ai_usage
from app.auth import get_current_active_user
from app.database import get_db
from app.subscriptions import get_or_create_user_subscription
from app.utils.rate_limiter import check_ip_rate_limit

router = APIRouter(prefix="/api/shortlist", tags=["shortlist"])

RECOMMEND_RATE_LIMIT = int(os.getenv("SHORTLIST_RECOMMEND_RATE_LIMIT", "20") or "20")
RECOMMEND_RATE_WINDOW = int(os.getenv("SHORTLIST_RECOMMEND_RATE_WINDOW", "600") or "600")


class ShortlistEntryCreate(BaseModel):
    university_name: str = Field(..., min_length=1, max_length=200)
    program: Optional[str] = Field(default=None, max_length=200)
    location: Optional[str] = Field(default=None, max_length=160)
    status: Optional[str] = None
    source: Optional[str] = "manual"  # manual | ai
    est_tuition: Optional[str] = Field(default=None, max_length=80)
    rationale: Optional[str] = Field(default=None, max_length=600)
    notes: Optional[str] = Field(default=None, max_length=1000)


class ShortlistEntryUpdate(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = Field(default=None, max_length=1000)


class RecommendRequest(BaseModel):
    field_of_study: str = Field(..., min_length=1, max_length=120)
    level: Optional[str] = Field(default=None, max_length=60)         # Bachelors | Masters | PhD ...
    budget: Optional[str] = Field(default=None, max_length=60)
    gpa: Optional[str] = Field(default=None, max_length=60)
    test_scores: Optional[str] = Field(default=None, max_length=160)
    preferences: Optional[str] = Field(default=None, max_length=300)
    max_results: int = Field(default=6, ge=1, le=8)


def _rate_limit_or_429(request: Request, scope: str, limit: int, window: int, user_id: int) -> None:
    allowed, retry_after = check_ip_rate_limit(
        request=request, scope=scope, limit=limit, window_seconds=window, extra_key=f"user:{user_id}",
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please slow down and try again shortly.",
            headers={"Retry-After": str(retry_after or window)},
        )


def _destination(user: models.User) -> tuple[str, str]:
    """(country_code, country_name) for the student's destination (defaults to US)."""
    code, _ = visa_catalog.resolve_selection(
        getattr(user, "destination_country_code", None),
        getattr(user, "visa_type_key", None),
    )
    name = (visa_catalog.country_meta(code) or {}).get("name", code)
    return code, name


@router.get("")
@router.get("/")
def list_shortlist(
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(models.UniversityShortlistEntry)
        .filter(models.UniversityShortlistEntry.user_id == current_user.id)
        .order_by(desc(models.UniversityShortlistEntry.created_at), desc(models.UniversityShortlistEntry.id))
        .all()
    )
    subscription = get_or_create_user_subscription(db, current_user.id)
    code, name = _destination(current_user)
    return {
        "entries": [university_shortlist.serialize_entry(r) for r in rows],
        "destination_country_code": code,
        "destination_country": name,
        "recommend_available": university_shortlist.ai_available(),
        "entitlement": visa_pass.feature_entitlement(subscription, "university_shortlist"),
    }


@router.get("/universities")
def search_universities(
    q: str = "",
    limit: int = 8,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Typeahead: universities in the student's destination country whose name matches `q`.

    Backs the university autocomplete (SOP Studio, manual shortlist add). Deduplicates by
    name (the registry keys by email domain, so one university can have several rows) and
    surfaces prefix matches before substring matches.
    """
    term = (q or "").strip()
    if len(term) < 2:
        return {"results": []}
    code, _ = _destination(current_user)
    take = max(1, min(int(limit or 8), 15))
    like = f"%{term}%"
    rows = (
        db.query(models.USUniversity.university_name, models.USUniversity.location)
        .filter(
            models.USUniversity.country_code == code,
            models.USUniversity.university_name.ilike(like),
        )
        .order_by(models.USUniversity.university_name.asc())
        .limit(take * 6)  # over-fetch so name-dedupe still fills the list
        .all()
    )
    term_lc = term.lower()
    seen: set[str] = set()
    prefix: list[dict] = []
    contains: list[dict] = []
    for name, location in rows:
        key = (name or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        bucket = prefix if key.startswith(term_lc) else contains
        bucket.append({"name": name, "location": location})
    return {"country_code": code, "results": (prefix + contains)[:take]}


@router.post("", status_code=status.HTTP_201_CREATED)
@router.post("/", status_code=status.HTTP_201_CREATED)
def add_shortlist_entry(
    payload: ShortlistEntryCreate = Body(...),
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    name = (payload.university_name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="University name is required.")
    code, _ = _destination(current_user)
    source = "ai" if (payload.source or "").strip().lower() == "ai" else "manual"
    entry = models.UniversityShortlistEntry(
        user_id=current_user.id,
        country_code=code,
        university_name=name[:200],
        program=(payload.program or "").strip()[:200] or None,
        location=(payload.location or "").strip()[:160] or None,
        status=university_shortlist.normalize_status(payload.status),
        source=source,
        est_tuition=(payload.est_tuition or "").strip()[:80] or None,
        rationale=(payload.rationale or "").strip()[:600] or None,
        notes=(payload.notes or "").strip()[:1000] or None,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return {"entry": university_shortlist.serialize_entry(entry)}


@router.patch("/{entry_id}")
def update_shortlist_entry(
    entry_id: int,
    payload: ShortlistEntryUpdate = Body(...),
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    entry = (
        db.query(models.UniversityShortlistEntry)
        .filter(
            models.UniversityShortlistEntry.id == entry_id,
            models.UniversityShortlistEntry.user_id == current_user.id,
        )
        .first()
    )
    if not entry:
        raise HTTPException(status_code=404, detail="University not found.")
    provided = payload.model_dump(exclude_unset=True)
    if "status" in provided and provided["status"] is not None:
        entry.status = university_shortlist.normalize_status(provided["status"])
    if "notes" in provided:
        entry.notes = (provided["notes"] or "").strip()[:1000] or None
    db.commit()
    db.refresh(entry)
    return {"entry": university_shortlist.serialize_entry(entry)}


@router.delete("/{entry_id}")
def delete_shortlist_entry(
    entry_id: int,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    entry = (
        db.query(models.UniversityShortlistEntry)
        .filter(
            models.UniversityShortlistEntry.id == entry_id,
            models.UniversityShortlistEntry.user_id == current_user.id,
        )
        .first()
    )
    if not entry:
        raise HTTPException(status_code=404, detail="University not found.")
    db.delete(entry)
    db.commit()
    return {"deleted": True, "id": entry_id}


@router.post("/recommend")
def recommend(
    payload: RecommendRequest,
    request: Request,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    _rate_limit_or_429(request, "shortlist.recommend", RECOMMEND_RATE_LIMIT, RECOMMEND_RATE_WINDOW, current_user.id)
    subscription = get_or_create_user_subscription(db, current_user.id)
    # Free quota / Visa-Pass gating (raises 402 when locked).
    visa_pass.enforce_feature_or_402(db, subscription, "university_shortlist")

    ai_usage.set_usage_account(user_id=current_user.id)
    _, destination_country = _destination(current_user)
    result = university_shortlist.recommend_universities(
        destination_country=destination_country,
        field_of_study=payload.field_of_study.strip(),
        level=(payload.level or "").strip() or None,
        budget=(payload.budget or "").strip() or None,
        gpa=(payload.gpa or "").strip() or None,
        test_scores=(payload.test_scores or "").strip() or None,
        home_country=getattr(current_user, "current_residence_country", None),
        preferences=(payload.preferences or "").strip() or None,
        max_results=payload.max_results,
    )

    if not result.get("available"):
        raise HTTPException(
            status_code=503,
            detail=result.get("message") or "AI recommendations are temporarily unavailable.",
        )
    if not result.get("universities"):
        # Don't burn the quota when the model returned nothing usable.
        raise HTTPException(status_code=502, detail="Couldn't generate recommendations. Please refine your inputs and retry.")

    # Only consume the metered quota once we have real results.
    visa_pass.consume_feature(db, subscription, "university_shortlist", commit=True)
    return {
        "destination_country": destination_country,
        "universities": result["universities"],
        "entitlement": visa_pass.feature_entitlement(subscription, "university_shortlist"),
    }
