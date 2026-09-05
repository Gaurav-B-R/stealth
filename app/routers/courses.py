"""B2C Course Finder (individual student accounts).

The same shared course catalog the enterprise Course Finder browses — the catalog
tables are global (no org/user scoping), only these thin routes differ:

- GET  /api/courses/meta            filter vocabularies + per-country stats + entitlement
- GET  /api/courses/catalog         FREE advanced-filter browse (paged)
- POST /api/courses/recommend       AI course shortlist (Visa-Pass metered)
- GET  /api/courses/recs            the student's stored past shortlists
- GET  /api/courses/recs/{id}       one stored shortlist (free tier: first picks only, rest masked)
- POST /api/courses/recs/{id}/save  copy one recommendation onto the shortlist tab

Country-specific by design: browse and AI both default to the student's profile
destination, and the AI run is personalized from their profile (home country, visa
type, intake, scores from the form) plus their existing university shortlist with
outcomes — so a paid run never re-suggests a university that already admitted or
rejected them (same rule as enterprise).

Metering follows the house choreography: rate-limit → 402 pre-check → generate →
fail WITHOUT consuming → persist result + consume quota atomically. Browsing costs
nothing because no AI call happens.
"""
import json
import os
import re
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app import ai_usage
from app import course_catalog
from app import models
from app import university_shortlist
from app import visa_catalog
from app import visa_pass
from app.auth import get_current_active_user
from app.database import get_db
from app.subscriptions import get_or_create_user_subscription
from app.utils.rate_limiter import check_ip_rate_limit

router = APIRouter(prefix="/api/courses", tags=["courses"])

FEATURE_KEY = "course_finder"
USAGE_SOURCE = "course_finder"  # B2C bucket — must stay in visa_pass.B2C_COST_SOURCES

RECOMMEND_RATE_LIMIT = int(os.getenv("COURSES_RECOMMEND_RATE_LIMIT", "20") or "20")
RECOMMEND_RATE_WINDOW = int(os.getenv("COURSES_RECOMMEND_RATE_WINDOW", "600") or "600")
BROWSE_RATE_LIMIT = int(os.getenv("COURSES_BROWSE_RATE_LIMIT", "120") or "120")
BROWSE_RATE_WINDOW = int(os.getenv("COURSES_BROWSE_RATE_WINDOW", "600") or "600")
# Same page-size dial as the enterprise browse — the catalog itself is shared, so the
# response-size reasoning is identical.
BROWSE_PAGE_SIZE = max(10, min(200, int(os.getenv("COURSE_CATALOG_BROWSE_PAGE_SIZE", "60") or "60")))
HISTORY_CONTEXT_ROWS = 40  # shortlist rows fed to the AI as never-re-suggest context


class CourseRecommendRequest(BaseModel):
    country_code: Optional[str] = Field(default=None, max_length=8)
    degree_level: Optional[str] = Field(default=None, max_length=20)
    discipline: Optional[str] = Field(default=None, max_length=80)
    field_of_study: Optional[str] = Field(default=None, max_length=120)
    budget: Optional[str] = Field(default=None, max_length=60)
    gpa: Optional[str] = Field(default=None, max_length=60)
    test_scores: Optional[str] = Field(default=None, max_length=160)
    notes: Optional[str] = Field(default=None, max_length=300)
    max_results: int = Field(default=6, ge=1, le=8)


class SaveRecItemRequest(BaseModel):
    index: int = Field(..., ge=0, le=31)


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


def _resolve_country_or_400(user: models.User, requested: Optional[str]) -> str:
    """The catalog country for this call: an explicit valid code wins (students explore
    neighbouring destinations before committing), otherwise the profile destination."""
    code = (requested or "").strip().upper()
    if code:
        if not course_catalog.country_name(code):
            raise HTTPException(status_code=400, detail="Unknown destination country.")
        return code
    code, _ = _destination(user)
    if not course_catalog.country_name(code):
        raise HTTPException(status_code=400, detail="Set your destination country in your profile first.")
    return code


def _student_profile_block(user: models.User, payload: CourseRecommendRequest) -> str:
    """Compact personalization dossier — the B2C analogue of the enterprise client
    profile block. Profile facts come from the account; academics come from the form
    (B2C has no typed columns for them, same as enterprise stage_data)."""
    _, dest_name = _destination(user)
    lines = [
        f"- Name: {user.full_name or 'Not recorded'}",
        f"- Home country: {getattr(user, 'current_residence_country', None) or 'Not recorded'}",
        f"- Destination: {dest_name}",
    ]
    intake = (getattr(user, "preferred_intake", None) or "").strip()
    if intake:
        lines.append(f"- Preferred intake: {intake}")
    if (payload.gpa or "").strip():
        lines.append(f"- GPA / grades: {payload.gpa.strip()}")
    if (payload.test_scores or "").strip():
        lines.append(f"- Test scores: {payload.test_scores.strip()}")
    return "\n".join(lines)


def _student_history_block(db: Session, user: models.User, country_code: str) -> str:
    """The student's own shortlist with outcomes, in the exact line format
    recommend_courses expects for its never-re-suggest rule. Scoped to the target
    country — an admit in Canada shouldn't block a US suggestion of the same brand."""
    rows = (
        db.query(models.UniversityShortlistEntry)
        .filter(
            models.UniversityShortlistEntry.user_id == user.id,
            models.UniversityShortlistEntry.country_code == country_code,
        )
        .order_by(desc(models.UniversityShortlistEntry.created_at))
        .limit(HISTORY_CONTEXT_ROWS)
        .all()
    )
    lines = []
    for row in rows:
        name = (row.university_name or "").strip()
        if not name:
            continue
        program = (row.program or "").strip()
        status_key = (row.status or "considering").strip().lower()
        outcome = course_catalog._SHORTLIST_STATUS_TEXT.get(status_key, status_key or "on the shortlist")
        lines.append(f"- {name}" + (f" — {program}" if program else "") + f" [{outcome}]")
    return "\n".join(lines)


def _mask_items_for_free(items: list) -> list:
    """Free tier: the first FREE_COURSE_FINDER_VISIBLE_RESULTS picks in full, every later
    pick reduced to {locked, fit_level}. The stored row keeps the full list; the client
    never receives a hidden pick's name, fees, requirements or URLs, so the blur cannot
    be lifted from devtools. fit_level alone is kept as the teaser ("High chance 🔒").
    Like the red-flag scan, masking keys off has_active_pass only — the VISA_PASS_ENFORCE
    kill switch governs quota, never what a free account gets to see."""
    visible = max(0, int(visa_pass.FREE_COURSE_FINDER_VISIBLE_RESULTS))
    hidden = [it for it in items[visible:] if isinstance(it, dict)]
    out = []
    for i, item in enumerate(items):
        if i < visible:
            out.append(_scrub_hidden_names(item, hidden) if isinstance(item, dict) else item)
            continue
        fit = str(item.get("fit_level") or "").strip().lower() if isinstance(item, dict) else ""
        out.append({"locked": True, "fit_level": fit if fit in {"reach", "match", "safety"} else None})
    return out


def _hidden_name_patterns(hidden: list) -> list:
    """Regexes for each hidden pick's university name (case-insensitive, leading "The"
    optional). Course names are deliberately NOT scrubbed: two picks often share one
    ("Master of Data Science"), and a program name identifies nothing on its own."""
    pats = []
    for it in hidden:
        name = re.sub(r"^(?i:the)\s+", "", str(it.get("university_name") or "").strip())
        if len(name) >= 4:
            pats.append(re.compile(r"(?i)\b(?:the\s+)?" + re.escape(name) + r"\b"))
    return pats


def _scrub_hidden_names(item: dict, hidden: list) -> dict:
    """A visible pick's prose is generated in the same model call as the hidden ones and
    can cross-reference them ("cheaper than Monash…") — worse, the student's own notes
    are spliced into that prompt, so "compare every university in pick 1" is a one-run
    bypass with no devtools. Replace any hidden university's name in the visible pick's
    free-text fields. Exact-name only; the prompt's no-cross-reference rule covers the
    abbreviations this cannot."""
    pats = _hidden_name_patterns(hidden)
    if not pats:
        return item
    def clean(text):
        out = str(text)
        for pat in pats:
            out = pat.sub("another university", out)
        return out
    scrubbed = dict(item)
    if scrubbed.get("why_recommended"):
        scrubbed["why_recommended"] = clean(scrubbed["why_recommended"])
    reqs = scrubbed.get("key_requirements")
    if isinstance(reqs, list):
        scrubbed["key_requirements"] = [clean(r) if isinstance(r, str) else r for r in reqs]
    return scrubbed


def _serialize_rec(row: models.UserCourseFinderRec, *, include_items: bool = True, reveal_all: bool) -> dict:
    """`reveal_all` is deliberately required (no default): forgetting it must fail at the
    call site rather than ship a free account the full shortlist."""
    try:
        items = json.loads(row.recommendations) if row.recommendations else []
        if not isinstance(items, list):
            items = []
    except Exception:
        items = []
    try:
        query = json.loads(row.query) if row.query else {}
        if not isinstance(query, dict):
            query = {}
    except Exception:
        query = {}
    visible = max(0, int(visa_pass.FREE_COURSE_FINDER_VISIBLE_RESULTS))
    locked_count = 0 if reveal_all else max(0, len(items) - visible)
    data = {
        "id": int(row.id),
        "country_code": row.country_code,
        "degree_level": row.degree_level,
        "discipline": row.discipline,
        "query": query,
        # The overview is written with the whole shortlist in view and routinely names
        # the universities in it — with picks hidden it would hand over exactly what the
        # blur withholds, so a free account gets no summary until the pass unlocks it.
        "summary": None if locked_count else row.summary,
        "catalog_based": bool(row.catalog_based),
        "grounded": bool(row.grounded),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "count": len(items),
        # Free tier: how many picks are masked (0 for pass holders) — drives the CTA.
        "locked_count": locked_count,
        # model_used deliberately omitted — internal only, same as enterprise.
    }
    if include_items:
        data["recommendations"] = items if reveal_all else _mask_items_for_free(items)
    return data


@router.get("/meta")
def courses_meta(
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Filter vocabularies + per-country catalog stats + the student's entitlement.

    Vocabularies are served rather than duplicated in the frontend so every option
    the UI offers is an option the browse query is known to accept (same contract
    as the enterprise meta endpoint).
    """
    subscription = get_or_create_user_subscription(db, current_user.id)
    dest_code, dest_name = _destination(current_user)
    stats = course_catalog.catalog_stats(db)
    return {
        "countries": stats["countries"],
        "disciplines": course_catalog.DISCIPLINES,
        "degree_levels": course_catalog.DEGREE_LEVELS,
        "intakes": course_catalog.INTAKE_BUCKETS,
        "sorts": course_catalog.CATALOG_SORTS,
        "university_types": course_catalog.UNIVERSITY_TYPES,
        "gre_filters": course_catalog.GRE_FILTERS,
        "ai_available": course_catalog.ai_available(),
        "destination_country_code": dest_code,
        "destination_country": dest_name,
        "entitlement": visa_pass.feature_entitlement(subscription, FEATURE_KEY),
    }


@router.get("/catalog")
def courses_catalog_browse(
    request: Request,
    country: Optional[str] = None,
    level: Optional[str] = None,
    discipline: Optional[str] = None,
    q: Optional[str] = None,
    max_tuition: Optional[int] = None,
    # --- advanced filters (all optional; validated + clamped by course_catalog) ---
    min_tuition: Optional[int] = None,
    require_tuition: Optional[bool] = None,
    max_ielts: Optional[float] = None,
    max_toefl: Optional[int] = None,
    tests_include_unknown: Optional[bool] = None,
    gre: Optional[str] = None,
    intake: Optional[str] = None,
    max_duration: Optional[int] = None,
    no_app_fee: Optional[bool] = None,
    has_deadline: Optional[bool] = None,
    max_qs_rank: Optional[int] = None,
    uni_type: Optional[str] = None,
    city: Optional[str] = None,
    verified_only: Optional[bool] = None,
    scholarships_only: Optional[bool] = None,
    sort: Optional[str] = None,
    offset: int = 0,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """FREE catalog browse — universities with their matching courses (paged).

    `country` defaults to the student's profile destination so the page opens on
    their own journey; any launch country can be requested explicitly.
    """
    _rate_limit_or_429(request, "courses.catalog_browse", BROWSE_RATE_LIMIT, BROWSE_RATE_WINDOW, current_user.id)
    code = _resolve_country_or_400(current_user, country)
    safe_max_tuition = None
    if max_tuition is not None:
        try:
            safe_max_tuition = max(0, min(int(max_tuition), 10_000_000)) or None
        except Exception:
            safe_max_tuition = None
    safe_offset = max(0, min(int(offset or 0), 100_000))
    # One validation gate for the deep filters: unknown enum values and out-of-range
    # numbers are dropped (broader search) instead of 400-ing a stale bookmark.
    advanced = course_catalog.normalize_catalog_filters({
        "min_tuition": min_tuition,
        "require_tuition": require_tuition,
        "max_ielts": max_ielts,
        "max_toefl": max_toefl,
        "tests_include_unknown": tests_include_unknown,
        "gre": gre,
        "intake": intake,
        "max_duration_months": max_duration,
        "no_app_fee": no_app_fee,
        "has_deadline": has_deadline,
        "max_qs_rank": max_qs_rank,
        "university_type": uni_type,
        "city": city,
        "verified_only": verified_only,
        "scholarships_only": scholarships_only,
        "sort": sort,
    })

    rows, total = course_catalog.query_catalog(
        db,
        country_code=code,
        degree_level=(level or "").strip().lower() or None,
        discipline=(discipline or "").strip() or None,
        q=(q or "").strip() or None,
        max_tuition=safe_max_tuition,
        advanced=advanced,
        limit_universities=BROWSE_PAGE_SIZE,
        offset_universities=safe_offset,
    )
    return {
        "country_code": code,
        "universities": [course_catalog.serialize_university(u, courses) for u, courses in rows],
        "total_universities": total,
        "page_courses": sum(len(courses) for _u, courses in rows),
        "offset": safe_offset,
        "page_size": BROWSE_PAGE_SIZE,
        "has_more": (safe_offset + len(rows)) < total,
        "applied_filters": advanced,
        "sort": advanced.get("sort") or "rank",
    }


@router.post("/recommend")
def courses_recommend(
    payload: CourseRecommendRequest,
    request: Request,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """AI course shortlist (Visa-Pass metered). Catalog-first with grounded live-search
    fallback, personalized to the student's profile, destination and shortlist history.
    Quota choreography: rate-limit → atomically RESERVE one run (402 when none left) →
    generate → refund the reservation on any failure. Reserve-before-generate (rather
    than the older check→generate→consume) is deliberate: this is the one B2C feature
    with a finite paid cap whose purpose is bounding real Gemini/Search spend, and the
    old shape let N parallel requests each pass the check and lost-update the counter."""
    # Validate the brief first: a bad request is a 400 before any rate-limit, paywall or
    # model-availability state is consulted (same order as the enterprise endpoint).
    try:
        discipline, field_query = course_catalog.resolve_subject(payload.discipline, payload.field_of_study)
        budget = course_catalog.normalize_budget(payload.budget)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _rate_limit_or_429(request, "courses.recommend", RECOMMEND_RATE_LIMIT, RECOMMEND_RATE_WINDOW, current_user.id)
    subscription = get_or_create_user_subscription(db, current_user.id)

    if not course_catalog.ai_available():
        raise HTTPException(status_code=503, detail="AI recommendations are not configured.")

    code = _resolve_country_or_400(current_user, payload.country_code)

    catalog_rows, _total = course_catalog.query_catalog(
        db,
        country_code=code,
        degree_level=(payload.degree_level or "").strip().lower() or None,
        discipline=discipline,
        q=field_query or None,
        limit_universities=20,
    )
    if field_query and sum(len(c) for _u, c in catalog_rows) < course_catalog.RECOMMEND_MIN_CATALOG_ROWS:
        # A literal name search can be too narrow ("ML" won't match "Machine Learning"
        # rows verbatim) — widen to the discipline/level slice and let the model pick.
        catalog_rows, _total = course_catalog.query_catalog(
            db,
            country_code=code,
            degree_level=(payload.degree_level or "").strip().lower() or None,
            discipline=discipline,
            limit_universities=20,
        )

    # Atomically claim one run BEFORE spending tokens (raises 402 when none left).
    # `reserved` is False only with the VISA_PASS_ENFORCE kill switch off, where the
    # call proceeds unclaimed and there is nothing to refund.
    reserved = visa_pass.reserve_feature_or_402(db, subscription, FEATURE_KEY)

    try:
        usage_token = ai_usage.set_usage_account(user_id=current_user.id)
        try:
            result = course_catalog.recommend_courses(
                destination_country=course_catalog.country_name(code),
                catalog_rows=catalog_rows,
                client=None,
                for_student=True,
                student_profile=_student_profile_block(current_user, payload),
                student_history=_student_history_block(db, current_user, code),
                field_of_study=field_query or None,
                degree_level=(payload.degree_level or "").strip().lower() or None,
                discipline=discipline,
                budget=budget,
                notes=payload.notes,
                max_results=payload.max_results,
                usage_source=USAGE_SOURCE,
            )
        finally:
            ai_usage.reset_usage_account(usage_token)

        if not result.get("available"):
            raise HTTPException(status_code=503, detail=result.get("message") or "Recommendations are unavailable right now.")
        recommendations = result.get("recommendations") or []
        if not recommendations:
            raise HTTPException(
                status_code=502,
                detail="Couldn't generate a shortlist. Refine the field of study or filters and retry.",
            )

        rec_row = models.UserCourseFinderRec(
            user_id=current_user.id,
            country_code=code,
            degree_level=(payload.degree_level or "").strip().lower() or None,
            discipline=discipline,
            query=json.dumps({
                "field_of_study": field_query or None,
                "budget": budget,
                "gpa": (payload.gpa or "").strip() or None,
                "test_scores": (payload.test_scores or "").strip() or None,
                "notes": (payload.notes or "").strip() or None,
                "max_results": payload.max_results,
            }),
            summary=result.get("summary"),
            recommendations=json.dumps(recommendations),
            catalog_based=bool(result.get("catalog_based")),
            grounded=bool(result.get("grounded")),
            model_used=result.get("model"),
        )
        db.add(rec_row)
        db.commit()
        db.refresh(rec_row)
    except Exception:
        # Any failure after the reservation — AI down (503), empty result (502),
        # persist error — returns the claimed run, so a run that produced nothing
        # usable is never charged (never-charge-on-empty, reservation edition).
        db.rollback()
        if reserved:
            visa_pass.refund_feature(db, subscription, FEATURE_KEY)
        raise

    return {
        "destination_country": course_catalog.country_name(code),
        "rec": _serialize_rec(rec_row, reveal_all=visa_pass.has_active_pass(subscription)),
        "entitlement": visa_pass.feature_entitlement(subscription, FEATURE_KEY),
    }


@router.get("/recs")
def courses_recs_list(
    limit: int = 20,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """The student's stored past shortlists (newest first) — a metered result is
    never lost to a reload."""
    take = max(1, min(int(limit or 20), 50))
    # Subscription first: resolving it can commit (pass expiry downgrade), which would
    # expire already-loaded rows and re-SELECT each one during serialization.
    reveal_all = visa_pass.has_active_pass(get_or_create_user_subscription(db, current_user.id))
    rows = (
        db.query(models.UserCourseFinderRec)
        .filter(models.UserCourseFinderRec.user_id == current_user.id)
        .order_by(desc(models.UserCourseFinderRec.created_at), desc(models.UserCourseFinderRec.id))
        .limit(take)
        .all()
    )
    return {"recs": [_serialize_rec(r, include_items=False, reveal_all=reveal_all) for r in rows]}


@router.get("/recs/{rec_id}")
def courses_rec_detail(
    rec_id: int,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    # Masked from the stored full row at read time: a pass bought after the run
    # unlocks it here, an expired pass re-locks it. (Subscription before the row —
    # see courses_recs_list.)
    reveal_all = visa_pass.has_active_pass(get_or_create_user_subscription(db, current_user.id))
    row = (
        db.query(models.UserCourseFinderRec)
        .filter(
            models.UserCourseFinderRec.id == rec_id,
            models.UserCourseFinderRec.user_id == current_user.id,
        )
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Shortlist not found.")
    return {"rec": _serialize_rec(row, reveal_all=reveal_all)}


@router.post("/recs/{rec_id}/save")
def courses_rec_save_to_shortlist(
    rec_id: int,
    payload: SaveRecItemRequest = Body(...),
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Copy one recommendation onto the student's university shortlist (free,
    idempotent on university+program — clicking twice must not duplicate)."""
    has_pass = visa_pass.has_active_pass(get_or_create_user_subscription(db, current_user.id))
    row = (
        db.query(models.UserCourseFinderRec)
        .filter(
            models.UserCourseFinderRec.id == rec_id,
            models.UserCourseFinderRec.user_id == current_user.id,
        )
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Shortlist not found.")
    try:
        items = json.loads(row.recommendations) if row.recommendations else []
    except Exception:
        items = []
    if not isinstance(items, list) or payload.index >= len(items):
        raise HTTPException(status_code=400, detail="Recommendation not found in this shortlist.")
    # The client hides the save button on masked picks; this is the server-side half —
    # otherwise POSTing a hidden index would copy the pick's real name/fees onto the
    # shortlist and lift the blur.
    if payload.index >= max(0, int(visa_pass.FREE_COURSE_FINDER_VISIBLE_RESULTS)) and not has_pass:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="This pick is hidden on the free plan — unlock the Visa Success Pass to save it.",
        )
    item = items[payload.index]
    if not isinstance(item, dict):
        raise HTTPException(status_code=400, detail="Recommendation not found in this shortlist.")

    name = str(item.get("university_name") or "").strip()[:200]
    program = str(item.get("course_name") or "").strip()[:200] or None
    if not name:
        raise HTTPException(status_code=400, detail="Recommendation is missing a university name.")

    existing = (
        db.query(models.UniversityShortlistEntry)
        .filter(models.UniversityShortlistEntry.user_id == current_user.id)
        .all()
    )
    for entry in existing:
        if (entry.university_name or "").strip().lower() == name.lower() and \
                ((entry.program or "").strip().lower() == (program or "").lower()):
            return {"entry": university_shortlist.serialize_entry(entry), "already_saved": True}

    fit = str(item.get("fit_level") or "").strip().lower()
    reqs = item.get("key_requirements")
    requirements = [str(r).strip()[:140] for r in reqs if str(r).strip()][:6] if isinstance(reqs, list) else []
    # Stored values are model output: URLs re-checked by the same stored-XSS guard the
    # rest of the pipeline uses, ranks/fees re-cleaned rather than trusted.
    entry = models.UniversityShortlistEntry(
        user_id=current_user.id,
        country_code=(row.country_code or "").strip().upper() or None,
        university_name=name,
        program=program,
        location=str(item.get("location") or "").strip()[:160] or None,
        status=university_shortlist.DEFAULT_STATUS,
        source="ai",
        est_tuition=str(item.get("annual_tuition") or "").strip()[:80] or None,
        rationale=str(item.get("why_recommended") or "").strip()[:600] or None,
        qs_world_rank=university_shortlist._clean_rank(item.get("qs_world_rank")),
        admission_difficulty=fit if fit in {"reach", "match", "safety"} else None,
        key_requirements=json.dumps(requirements) if requirements else None,
        application_fee=str(item.get("application_fee") or "").strip()[:60] or None,
        website_url=university_shortlist._clean_url(item.get("website_url")),
        admissions_url=university_shortlist._clean_url(item.get("course_url")),
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return {"entry": university_shortlist.serialize_entry(entry), "already_saved": False}
