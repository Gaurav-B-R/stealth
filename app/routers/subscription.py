from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import models, schemas
from app.auth import get_current_active_user
from app.database import get_db
from app.subscriptions import PLAN_PRO, STATUS_ACTIVE, get_or_create_user_subscription, get_plan_limits

router = APIRouter(prefix="/api/subscription", tags=["subscription"])


def _build_subscription_response(subscription: models.Subscription) -> schemas.SubscriptionResponse:
    limits = get_plan_limits(subscription.plan)
    ai_limit = limits["ai_messages_limit"]
    doc_limit = limits["document_uploads_limit"]

    ai_remaining = -1 if ai_limit < 0 else max(ai_limit - subscription.ai_messages_used, 0)
    docs_remaining = -1 if doc_limit < 0 else max(doc_limit - subscription.document_uploads_used, 0)

    return schemas.SubscriptionResponse(
        plan=subscription.plan,
        status=subscription.status,
        ai_messages_used=subscription.ai_messages_used,
        ai_messages_limit=ai_limit,
        ai_messages_remaining=ai_remaining,
        document_uploads_used=subscription.document_uploads_used,
        document_uploads_limit=doc_limit,
        document_uploads_remaining=docs_remaining,
        is_pro=subscription.plan == PLAN_PRO and subscription.status == STATUS_ACTIVE,
    )


@router.get("/me", response_model=schemas.SubscriptionResponse)
def get_my_subscription(
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    subscription = get_or_create_user_subscription(db, current_user.id)
    return _build_subscription_response(subscription)


@router.post("/upgrade", response_model=schemas.SubscriptionResponse)
def upgrade_to_pro(
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    subscription = get_or_create_user_subscription(db, current_user.id)
    subscription.plan = PLAN_PRO
    subscription.status = STATUS_ACTIVE
    subscription.started_at = datetime.now(timezone.utc)
    subscription.ends_at = None
    db.commit()
    db.refresh(subscription)
    return _build_subscription_response(subscription)
