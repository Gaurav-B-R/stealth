from typing import Dict
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app import models

PLAN_FREE = "free"
PLAN_PRO = "pro"
STATUS_ACTIVE = "active"

FREE_AI_MESSAGE_LIMIT = 25
FREE_DOCUMENT_UPLOAD_LIMIT = 5


def _normalize_datetime(value):
    if value is None:
        return None
    if getattr(value, "tzinfo", None):
        return value.replace(tzinfo=None)
    return value


def _apply_subscription_expiry(subscription: models.Subscription) -> bool:
    if subscription.plan != PLAN_PRO:
        return False

    ends_at = _normalize_datetime(subscription.ends_at)
    if ends_at is None:
        return False

    if ends_at > datetime.utcnow():
        return False

    # Downgrade expired Pro to Free and reset cycle counters.
    subscription.plan = PLAN_FREE
    subscription.status = STATUS_ACTIVE
    subscription.ends_at = None
    subscription.ai_messages_used = 0
    subscription.document_uploads_used = 0
    return True


def get_plan_limits(plan: str) -> Dict[str, int]:
    normalized_plan = (plan or PLAN_FREE).lower()
    if normalized_plan == PLAN_PRO:
        return {"ai_messages_limit": -1, "document_uploads_limit": -1}
    return {
        "ai_messages_limit": FREE_AI_MESSAGE_LIMIT,
        "document_uploads_limit": FREE_DOCUMENT_UPLOAD_LIMIT,
    }


def get_or_create_user_subscription(
    db: Session,
    user_id: int,
    commit: bool = True,
) -> models.Subscription:
    subscription = db.query(models.Subscription).filter(
        models.Subscription.user_id == user_id
    ).first()

    if subscription:
        if _apply_subscription_expiry(subscription):
            if commit:
                db.commit()
                db.refresh(subscription)
            else:
                db.flush()
        return subscription

    subscription = models.Subscription(
        user_id=user_id,
        plan=PLAN_FREE,
        status=STATUS_ACTIVE,
        ai_messages_used=0,
        document_uploads_used=0,
    )
    db.add(subscription)
    if commit:
        db.commit()
        db.refresh(subscription)
    else:
        db.flush()
    return subscription


def grant_pro_access_for_days(
    db: Session,
    user_id: int,
    days: int = 30,
    commit: bool = True,
) -> models.Subscription:
    subscription = get_or_create_user_subscription(db, user_id, commit=commit)
    now = datetime.utcnow()
    ends_at = _normalize_datetime(subscription.ends_at)

    # Respect existing perpetual Pro access (no end date).
    if subscription.plan == PLAN_PRO and subscription.status == STATUS_ACTIVE and ends_at is None:
        return subscription

    start_from = now
    if subscription.plan == PLAN_PRO and subscription.status == STATUS_ACTIVE and ends_at and ends_at > now:
        start_from = ends_at

    subscription.plan = PLAN_PRO
    subscription.status = STATUS_ACTIVE
    subscription.ends_at = start_from + timedelta(days=days)

    if commit:
        db.commit()
        db.refresh(subscription)
    else:
        db.flush()

    return subscription


def backfill_missing_subscriptions(db: Session) -> int:
    existing_ids = {
        user_id for (user_id,) in db.query(models.Subscription.user_id).all()
    }
    user_ids = [user_id for (user_id,) in db.query(models.User.id).all()]

    created = 0
    for user_id in user_ids:
        if user_id in existing_ids:
            continue
        db.add(
            models.Subscription(
                user_id=user_id,
                plan=PLAN_FREE,
                status=STATUS_ACTIVE,
                ai_messages_used=0,
                document_uploads_used=0,
            )
        )
        created += 1

    if created > 0:
        db.commit()
    return created
