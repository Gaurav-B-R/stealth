"""
Application Kit — SOP / Statement of Purpose generator API.

  GET    /api/sop/status              — entitlement + the student's statements (latest version per root)
  POST   /api/sop/generate            — create a new statement (consumes 1 SOP credit)
  POST   /api/sop/refine              — iterate on a statement (consumes 1 SOP credit)
  GET    /api/sop/history/{root_id}   — all versions of one statement
  DELETE /api/sop/drafts/{root_id}    — delete a statement (all versions)

Freemium: generate + refine share the `sop_generator` counter (free 3 actions, Pass
unlimited) — enough to feel the iterative loop before the paywall. Model calls are
metered under the `sop_generator` usage source with per-user attribution.
"""

import os
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import models
from app import visa_pass
from app import sop_kit
from app.ai_usage import set_usage_account
from app.database import get_db
from app.auth import get_current_active_user
from app.subscriptions import get_or_create_user_subscription
from app.utils.rate_limiter import check_ip_rate_limit

router = APIRouter(prefix="/api/sop", tags=["sop-generator"])
logger = logging.getLogger(__name__)


def _rate_limit_or_429(request: Request, scope: str, limit: int, window: int, user_id: int) -> None:
    allowed, retry_after = check_ip_rate_limit(
        request=request, scope=scope, limit=limit, window_seconds=window, extra_key=f"user:{user_id}",
    )
    if not allowed:
        raise HTTPException(status_code=429, detail="Too many requests. Please slow down.",
                            headers={"Retry-After": str(retry_after)})


class GenerateRequest(BaseModel):
    university: str = Field(..., min_length=2, max_length=200)
    program: str = Field(..., min_length=2, max_length=200)
    study_level: str | None = Field(None, max_length=60)
    intake: str | None = Field(None, max_length=60)
    highlights: str | None = Field(None, max_length=2000)


class RefineRequest(BaseModel):
    root_id: int
    instruction: str = Field(..., min_length=3, max_length=1000)


def _latest_versions(db: Session, user_id: int) -> list[models.SopDraft]:
    """Latest version per root, newest statement first."""
    rows = (
        db.query(models.SopDraft)
        .filter(models.SopDraft.user_id == user_id)
        .order_by(models.SopDraft.root_id.desc(), models.SopDraft.version.desc())
        .all()
    )
    latest: dict[int, models.SopDraft] = {}
    for row in rows:
        key = row.root_id or row.id
        if key not in latest:
            latest[key] = row
    return list(latest.values())


def _latest_of_root(db: Session, user_id: int, root_id: int) -> models.SopDraft | None:
    return (
        db.query(models.SopDraft)
        .filter(models.SopDraft.user_id == user_id, models.SopDraft.root_id == root_id)
        .order_by(models.SopDraft.version.desc())
        .first()
    )


@router.get("/status")
def sop_status(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    subscription = get_or_create_user_subscription(db, current_user.id)
    entitlement = visa_pass.feature_entitlement(subscription, "sop_generator")
    return {
        "entitlement": entitlement,
        "doc_name": sop_kit.doc_display_name(getattr(current_user, "destination_country_code", None)),
        "drafts": [sop_kit.serialize_draft(d) for d in _latest_versions(db, current_user.id)],
    }


@router.post("/generate")
def sop_generate(
    payload: GenerateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _rate_limit_or_429(request, "sop.generate", int(os.getenv("SOP_RATE_LIMIT", "10")), 600, current_user.id)
    subscription = get_or_create_user_subscription(db, current_user.id)
    visa_pass.enforce_feature_or_402(db, subscription, "sop_generator")

    token = set_usage_account(user_id=current_user.id)
    try:
        draft = sop_kit.generate_sop(
            db, current_user,
            university=payload.university, program=payload.program,
            study_level=payload.study_level, intake=payload.intake, highlights=payload.highlights,
        )
    except RuntimeError:
        logger.exception("SOP generation failed for user %s", current_user.id)
        raise HTTPException(status_code=503, detail="Rilono AI could not draft your statement right now. Please try again in a moment.")
    finally:
        from app.ai_usage import reset_usage_account
        reset_usage_account(token)

    visa_pass.consume_feature(db, subscription, "sop_generator", commit=True)
    return {
        "draft": sop_kit.serialize_draft(draft),
        "entitlement": visa_pass.feature_entitlement(subscription, "sop_generator"),
    }


@router.post("/refine")
def sop_refine(
    payload: RefineRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _rate_limit_or_429(request, "sop.refine", int(os.getenv("SOP_RATE_LIMIT", "10")), 600, current_user.id)
    latest = _latest_of_root(db, current_user.id, payload.root_id)
    if not latest:
        raise HTTPException(status_code=404, detail="Statement not found.")

    subscription = get_or_create_user_subscription(db, current_user.id)
    visa_pass.enforce_feature_or_402(db, subscription, "sop_generator")

    token = set_usage_account(user_id=current_user.id)
    try:
        draft = sop_kit.refine_sop(db, current_user, latest, payload.instruction)
    except RuntimeError:
        logger.exception("SOP refinement failed for user %s", current_user.id)
        raise HTTPException(status_code=503, detail="Rilono AI could not revise your statement right now. Please try again in a moment.")
    finally:
        from app.ai_usage import reset_usage_account
        reset_usage_account(token)

    visa_pass.consume_feature(db, subscription, "sop_generator", commit=True)
    return {
        "draft": sop_kit.serialize_draft(draft),
        "entitlement": visa_pass.feature_entitlement(subscription, "sop_generator"),
    }


@router.get("/history/{root_id}")
def sop_history(
    root_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    rows = (
        db.query(models.SopDraft)
        .filter(models.SopDraft.user_id == current_user.id, models.SopDraft.root_id == root_id)
        .order_by(models.SopDraft.version.asc())
        .all()
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Statement not found.")
    return {"versions": [sop_kit.serialize_draft(d) for d in rows]}


@router.delete("/drafts/{root_id}")
def sop_delete(
    root_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    deleted = (
        db.query(models.SopDraft)
        .filter(models.SopDraft.user_id == current_user.id, models.SopDraft.root_id == root_id)
        .delete(synchronize_session=False)
    )
    db.commit()
    if not deleted:
        raise HTTPException(status_code=404, detail="Statement not found.")
    return {"deleted_versions": deleted}
