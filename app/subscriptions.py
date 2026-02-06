from typing import Dict

from sqlalchemy.orm import Session

from app import models

PLAN_FREE = "free"
PLAN_PRO = "pro"
STATUS_ACTIVE = "active"

FREE_AI_MESSAGE_LIMIT = 25
FREE_DOCUMENT_UPLOAD_LIMIT = 5


def get_plan_limits(plan: str) -> Dict[str, int]:
    normalized_plan = (plan or PLAN_FREE).lower()
    if normalized_plan == PLAN_PRO:
        return {"ai_messages_limit": -1, "document_uploads_limit": -1}
    return {
        "ai_messages_limit": FREE_AI_MESSAGE_LIMIT,
        "document_uploads_limit": FREE_DOCUMENT_UPLOAD_LIMIT,
    }


def get_or_create_user_subscription(db: Session, user_id: int) -> models.Subscription:
    subscription = db.query(models.Subscription).filter(
        models.Subscription.user_id == user_id
    ).first()

    if subscription:
        return subscription

    subscription = models.Subscription(
        user_id=user_id,
        plan=PLAN_FREE,
        status=STATUS_ACTIVE,
        ai_messages_used=0,
        document_uploads_used=0,
    )
    db.add(subscription)
    db.commit()
    db.refresh(subscription)
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
