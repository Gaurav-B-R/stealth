"""Visa-decision OUTCOME capture (B2C) — closes the journey loop past interview prep.

The student dashboard shows a "did you get your decision?" card once they're deep enough in
the journey; recording it here powers the admin approval-rate metric (esp. red-flag-scan users
vs. not) — the pricing-power / marketing stat.

- GET  /api/outcomes/status          current decision + whether to show the capture card
- POST /api/outcomes/visa-decision   record the final decision (approved|refused|withdrawn|deferred)
- POST /api/outcomes/snooze          hide the capture card for a while (no decision yet)
"""
import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import models
from app.auth import get_current_active_user
from app.database import get_db
from app.subscriptions import get_or_create_user_subscription
from app.utils.rate_limiter import check_ip_rate_limit

router = APIRouter(prefix="/api/outcomes", tags=["outcomes"])


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

# Allowed final decisions. "deferred" = admin review / 221(g)-type hold; "withdrawn" = student pulled out.
VALID_DECISIONS = ("approved", "refused", "withdrawn", "deferred")
SNOOZE_DAYS = int(os.getenv("OUTCOME_PROMPT_SNOOZE_DAYS", "14") or "14")
DECISION_RATE_LIMIT = int(os.getenv("OUTCOME_RATE_LIMIT", "30") or "30")
DECISION_RATE_WINDOW = int(os.getenv("OUTCOME_RATE_WINDOW", "600") or "600")


class VisaDecisionIn(BaseModel):
    decision: str = Field(..., description="approved|refused|withdrawn|deferred")
    decided_on: Optional[str] = Field(default=None, description="ISO date the decision was received (optional)")


def _prompt_eligible(user: models.User, sub: models.Subscription) -> bool:
    """Show the capture card only when it makes sense: no decision yet, not snoozed, and the
    student has actually reached interview prep (the point the journey used to end)."""
    if user.visa_decision:
        return False
    snoozed = user.visa_decision_prompt_snoozed_until
    if snoozed is not None and snoozed > datetime.utcnow():
        return False
    reached_interview_prep = bool(
        (getattr(sub, "mock_interviews_used", 0) or 0) > 0
        or (getattr(sub, "prep_sessions_used", 0) or 0) > 0
        or (getattr(sub, "pass_voice_interviews_used", 0) or 0) > 0
    )
    return reached_interview_prep


def _status_payload(user: models.User, sub: models.Subscription) -> dict:
    return {
        "decision": user.visa_decision,
        "decision_at": user.visa_decision_at.isoformat() if user.visa_decision_at else None,
        "prompt_eligible": _prompt_eligible(user, sub),
    }


@router.get("/status")
def outcome_status(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    sub = get_or_create_user_subscription(db, current_user.id)
    return _status_payload(current_user, sub)


@router.post("/visa-decision")
def record_visa_decision(
    request: Request,
    payload: VisaDecisionIn = Body(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _rate_limit_or_429(request, "outcome_decision", DECISION_RATE_LIMIT, DECISION_RATE_WINDOW, current_user.id)
    decision = (payload.decision or "").strip().lower()
    if decision not in VALID_DECISIONS:
        raise HTTPException(status_code=422, detail="Invalid decision.")

    decided_at = datetime.utcnow()
    if payload.decided_on:
        # Accept an explicit decision date (date-only or ISO); fall back to now on parse failure.
        raw = payload.decided_on.strip()
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
            try:
                decided_at = datetime.strptime(raw, fmt)
                break
            except ValueError:
                continue

    current_user.visa_decision = decision
    current_user.visa_decision_at = decided_at
    current_user.visa_decision_source = "self_reported"
    current_user.visa_decision_prompt_snoozed_until = None
    db.commit()
    db.refresh(current_user)
    sub = get_or_create_user_subscription(db, current_user.id)
    return _status_payload(current_user, sub)


@router.post("/snooze")
def snooze_prompt(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    current_user.visa_decision_prompt_snoozed_until = datetime.utcnow() + timedelta(days=SNOOZE_DAYS)
    db.commit()
    db.refresh(current_user)
    sub = get_or_create_user_subscription(db, current_user.id)
    return _status_payload(current_user, sub)
