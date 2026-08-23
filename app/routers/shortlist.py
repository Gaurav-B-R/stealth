"""University shortlist (B2C student dashboard) — shown as Course Finder's "My shortlist" tab.

- GET    /api/shortlist            list the student's saved universities
- POST   /api/shortlist            add a university (manual, or saved from a Course Finder rec)
- PATCH  /api/shortlist/{id}       update status / notes
- DELETE /api/shortlist/{id}       remove a university

The old POST /api/shortlist/recommend (Gemini university recommendations, Visa-Pass gated)
was removed on 2026-08-22: Course Finder's catalog-grounded AI shortlist replaced it.
"""
import json
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app import models
from app import visa_catalog
from app import visa_pass
from app import university_shortlist
from app.auth import get_current_active_user
from app.database import get_db
from app.subscriptions import get_or_create_user_subscription

router = APIRouter(prefix="/api/shortlist", tags=["shortlist"])

class ShortlistEntryCreate(BaseModel):
    university_name: str = Field(..., min_length=1, max_length=200)
    program: Optional[str] = Field(default=None, max_length=200)
    location: Optional[str] = Field(default=None, max_length=160)
    status: Optional[str] = None
    source: Optional[str] = "manual"  # manual | ai
    est_tuition: Optional[str] = Field(default=None, max_length=80)
    rationale: Optional[str] = Field(default=None, max_length=600)
    notes: Optional[str] = Field(default=None, max_length=1000)
    # AI metadata (present when saving from a recommendation; parity with enterprise).
    qs_world_rank: Optional[str] = Field(default=None, max_length=20)
    country_rank: Optional[str] = Field(default=None, max_length=20)
    admission_difficulty: Optional[str] = Field(default=None, max_length=20)  # reach|match|safety
    key_requirements: Optional[list[str]] = None
    application_fee: Optional[str] = Field(default=None, max_length=60)
    website_url: Optional[str] = Field(default=None, max_length=400)
    admissions_url: Optional[str] = Field(default=None, max_length=400)


class ShortlistEntryUpdate(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = Field(default=None, max_length=1000)


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
    difficulty = (payload.admission_difficulty or "").strip().lower()
    requirements = [
        str(r).strip()[:140] for r in (payload.key_requirements or []) if str(r).strip()
    ][:6]
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
        # AI metadata is model output relayed by the client — ranks re-cleaned and URLs
        # re-checked server-side (stored-XSS guard), never trusted from the request.
        qs_world_rank=university_shortlist._clean_rank(payload.qs_world_rank),
        country_rank=university_shortlist._clean_rank(payload.country_rank),
        admission_difficulty=difficulty if difficulty in {"reach", "match", "safety"} else None,
        key_requirements=json.dumps(requirements) if requirements else None,
        application_fee=(payload.application_fee or "").strip()[:60] or None,
        website_url=university_shortlist._clean_url(payload.website_url),
        admissions_url=university_shortlist._clean_url(payload.admissions_url),
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
