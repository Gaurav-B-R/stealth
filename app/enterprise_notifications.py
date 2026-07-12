"""
Enterprise in-portal notifications (the topbar bell).

Design principles ("communications should be limited"):
- HIGH-SIGNAL EVENTS ONLY: client added, pipeline stage moved, mock interview completed,
  requested documents submitted, team membership changes, credits running low. Routine
  actions (notes, per-field edits, running a scan) deliberately do NOT notify.
- NEVER notify the actor about their own action — only teammates see it.
- DEDUPED: an identical event (same org/type/reference/title) within a short window is
  dropped, so bursts (e.g. rapid stage clicks) produce one notification, not five.
- BEST-EFFORT: notification failures never break the business action that triggered them.
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app import models

logger = logging.getLogger(__name__)

# Identical-event suppression window (minutes).
DEDUPE_MINUTES = 10
# Keep at most this many notifications per recipient (oldest pruned, best-effort).
MAX_PER_RECIPIENT = 200
# "Credits low" fires when a debit crosses below this balance (admins only).
CREDITS_LOW_THRESHOLD = 20


def _active_member_user_ids(db: Session, organization_id: int, roles: list[str] | None = None) -> list[int]:
    q = (
        db.query(models.EnterpriseOrganizationMember.user_id)
        .filter(
            models.EnterpriseOrganizationMember.organization_id == organization_id,
            models.EnterpriseOrganizationMember.is_active.is_(True),
        )
    )
    if roles:
        q = q.filter(models.EnterpriseOrganizationMember.role.in_(roles))
    return [row[0] for row in q.all()]


def _is_duplicate(db: Session, organization_id: int, type_: str, title: str,
                  reference_type: str | None, reference_id: int | None) -> bool:
    cutoff = datetime.utcnow() - timedelta(minutes=DEDUPE_MINUTES)
    q = (
        db.query(models.EnterpriseNotification.id)
        .filter(
            models.EnterpriseNotification.organization_id == organization_id,
            models.EnterpriseNotification.type == type_,
            models.EnterpriseNotification.title == title,
            models.EnterpriseNotification.created_at >= cutoff,
        )
    )
    if reference_type is not None:
        q = q.filter(models.EnterpriseNotification.reference_type == reference_type)
    if reference_id is not None:
        q = q.filter(models.EnterpriseNotification.reference_id == reference_id)
    return db.query(q.exists()).scalar() or False


def _prune_recipient(db: Session, recipient_user_id: int) -> None:
    """Best-effort cap on stored notifications per recipient."""
    try:
        ids = [
            row[0] for row in (
                db.query(models.EnterpriseNotification.id)
                .filter(models.EnterpriseNotification.recipient_user_id == recipient_user_id)
                .order_by(models.EnterpriseNotification.created_at.desc(), models.EnterpriseNotification.id.desc())
                .offset(MAX_PER_RECIPIENT)
                .limit(200)
                .all()
            )
        ]
        if ids:
            (db.query(models.EnterpriseNotification)
             .filter(models.EnterpriseNotification.id.in_(ids))
             .delete(synchronize_session=False))
    except Exception:
        pass


def notify_org(
    db: Session,
    organization_id: int,
    *,
    type: str,
    title: str,
    body: str | None = None,
    actor_user_id: int | None = None,
    reference_type: str | None = None,
    reference_id: int | None = None,
    recipient_roles: list[str] | None = None,
    commit: bool = False,
) -> int:
    """Fan a notification out to the org's active members (minus the actor).

    Returns the number of notifications created. Never raises — a notification
    failure must never break the action that produced it. Does NOT commit unless
    asked, so it can ride the caller's transaction.
    """
    try:
        if _is_duplicate(db, organization_id, type, title, reference_type, reference_id):
            return 0
        recipients = [
            uid for uid in _active_member_user_ids(db, organization_id, roles=recipient_roles)
            if uid != actor_user_id
        ]
        if not recipients:
            return 0
        for uid in recipients:
            db.add(models.EnterpriseNotification(
                organization_id=organization_id,
                recipient_user_id=uid,
                actor_user_id=actor_user_id,
                type=str(type)[:60],
                title=str(title)[:300],
                body=(str(body)[:1000] if body else None),
                reference_type=reference_type,
                reference_id=reference_id,
            ))
            _prune_recipient(db, uid)
        if commit:
            db.commit()
        return len(recipients)
    except Exception:
        logger.warning("enterprise notification fan-out failed (org=%s, type=%s)",
                       organization_id, type, exc_info=True)
        try:
            db.rollback() if commit else None
        except Exception:
            pass
        return 0


def maybe_notify_credits_low(db: Session, organization_id: int, balance_before: int, balance_after: int) -> None:
    """Notify org ADMINS once when a debit crosses below the low-credit threshold."""
    if balance_before >= CREDITS_LOW_THRESHOLD > balance_after:
        notify_org(
            db, organization_id,
            type="credits_low",
            title=f"Credits running low — {balance_after} left",
            body="Top up Rilono Credits so Deep Scans, mock interviews and the AI assistant keep working for your team.",
            reference_type="credits",
            recipient_roles=["admin"],
        )
