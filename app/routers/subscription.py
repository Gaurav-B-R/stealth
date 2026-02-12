import hashlib
import hmac
import os
import time

import requests
from fastapi import APIRouter, Depends
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import models, schemas
from app.auth import get_current_active_user
from app.database import get_db
from app.subscriptions import (
    PLAN_PRO,
    STATUS_ACTIVE,
    get_or_create_user_subscription,
    get_plan_limits,
    grant_pro_access_for_days,
)

router = APIRouter(prefix="/api/subscription", tags=["subscription"])


def _razorpay_credentials() -> tuple[str, str]:
    return (os.getenv("RAZORPAY_KEY_ID", "").strip(), os.getenv("RAZORPAY_KEY_SECRET", "").strip())


def _razorpay_checkout_enabled() -> bool:
    key_id, key_secret = _razorpay_credentials()
    return bool(key_id and key_secret)


def _pro_amount_paise() -> int:
    raw = os.getenv("PRO_MONTHLY_AMOUNT_PAISE", "69900").strip()
    try:
        amount = int(raw)
        if amount <= 0:
            raise ValueError
        return amount
    except ValueError:
        return 69900


def _pro_duration_days() -> int:
    raw = os.getenv("PRO_PLAN_DURATION_DAYS", "30").strip()
    try:
        days = int(raw)
        if days <= 0:
            raise ValueError
        return days
    except ValueError:
        return 30


def _build_subscription_response(subscription: models.Subscription) -> schemas.SubscriptionResponse:
    limits = get_plan_limits(subscription.plan)
    ai_limit = limits["ai_messages_limit"]
    doc_limit = limits["document_uploads_limit"]
    prep_limit = limits["prep_sessions_limit"]
    mock_limit = limits["mock_interviews_limit"]

    ai_remaining = -1 if ai_limit < 0 else max(ai_limit - subscription.ai_messages_used, 0)
    docs_remaining = -1 if doc_limit < 0 else max(doc_limit - subscription.document_uploads_used, 0)
    prep_remaining = -1 if prep_limit < 0 else max(prep_limit - subscription.prep_sessions_used, 0)
    mock_remaining = -1 if mock_limit < 0 else max(mock_limit - subscription.mock_interviews_used, 0)

    return schemas.SubscriptionResponse(
        plan=subscription.plan,
        status=subscription.status,
        ai_messages_used=subscription.ai_messages_used,
        ai_messages_limit=ai_limit,
        ai_messages_remaining=ai_remaining,
        document_uploads_used=subscription.document_uploads_used,
        document_uploads_limit=doc_limit,
        document_uploads_remaining=docs_remaining,
        prep_sessions_used=subscription.prep_sessions_used,
        prep_sessions_limit=prep_limit,
        prep_sessions_remaining=prep_remaining,
        mock_interviews_used=subscription.mock_interviews_used,
        mock_interviews_limit=mock_limit,
        mock_interviews_remaining=mock_remaining,
        is_pro=subscription.plan == PLAN_PRO and subscription.status == STATUS_ACTIVE,
    )


@router.get("/me", response_model=schemas.SubscriptionResponse)
def get_my_subscription(
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    subscription = get_or_create_user_subscription(db, current_user.id)
    return _build_subscription_response(subscription)


@router.post("/upgrade")
def upgrade_to_pro(
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    subscription = get_or_create_user_subscription(db, current_user.id)
    if subscription.plan == PLAN_PRO and subscription.status == STATUS_ACTIVE:
        return {
            "action": "already_pro",
            "message": "Your account is already on Pro.",
            "subscription": _build_subscription_response(subscription).model_dump(),
        }

    if not _razorpay_checkout_enabled():
        return {
            "action": "contact_support",
            "message": "Pro checkout is being enabled. Please contact support to activate billing.",
            "contact_path": "/contact",
        }

    key_id, key_secret = _razorpay_credentials()
    order_payload = {
        "amount": _pro_amount_paise(),
        "currency": os.getenv("PRO_PLAN_CURRENCY", "INR"),
        "receipt": f"rilono_pro_{current_user.id}_{int(time.time())}"[:40],
        "notes": {
            "user_id": str(current_user.id),
            "user_email": current_user.email,
            "plan": "pro",
        },
    }

    try:
        response = requests.post(
            "https://api.razorpay.com/v1/orders",
            auth=(key_id, key_secret),
            json=order_payload,
            timeout=15,
        )
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Failed to contact Razorpay: {str(exc)}")

    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail="Unable to create payment order right now. Please try again.")

    data = response.json()
    order_id = data.get("id")
    if not order_id:
        raise HTTPException(status_code=502, detail="Invalid payment order response from Razorpay.")

    return {
        "action": "razorpay_checkout",
        "key_id": key_id,
        "order_id": order_id,
        "amount": data.get("amount", order_payload["amount"]),
        "currency": data.get("currency", order_payload["currency"]),
        "name": "Rilono",
        "description": "Rilono Pro Subscription",
    }


@router.post("/verify-payment", response_model=schemas.SubscriptionResponse)
def verify_payment_and_activate_pro(
    payload: schemas.RazorpayPaymentVerifyRequest,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    key_id, key_secret = _razorpay_credentials()
    if not key_id or not key_secret:
        raise HTTPException(status_code=503, detail="Payment verification is not configured.")

    signed_payload = f"{payload.razorpay_order_id}|{payload.razorpay_payment_id}".encode("utf-8")
    expected_signature = hmac.new(
        key_secret.encode("utf-8"),
        signed_payload,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_signature, payload.razorpay_signature):
        raise HTTPException(status_code=400, detail="Invalid payment signature.")

    try:
        order_response = requests.get(
            f"https://api.razorpay.com/v1/orders/{payload.razorpay_order_id}",
            auth=(key_id, key_secret),
            timeout=15,
        )
        if order_response.status_code >= 400:
            raise HTTPException(status_code=502, detail="Unable to verify payment order details.")
        order_data = order_response.json()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Failed to verify payment order: {str(exc)}")

    order_user_id = str((order_data.get("notes") or {}).get("user_id", "")).strip()
    if order_user_id and order_user_id != str(current_user.id):
        raise HTTPException(status_code=403, detail="Payment order does not belong to this account.")

    if order_data.get("status") != "paid":
        raise HTTPException(status_code=400, detail="Payment is not marked as paid yet.")

    subscription = grant_pro_access_for_days(
        db=db,
        user_id=current_user.id,
        days=_pro_duration_days(),
        commit=True,
    )
    return _build_subscription_response(subscription)


@router.post("/cancel", response_model=schemas.SubscriptionResponse)
def cancel_my_subscription(
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    subscription = get_or_create_user_subscription(db, current_user.id)

    if subscription.plan != PLAN_PRO:
        return _build_subscription_response(subscription)

    # Until full recurring billing lifecycle is live, cancellation downgrades immediately.
    subscription.plan = "free"
    subscription.status = STATUS_ACTIVE
    subscription.ends_at = None
    subscription.ai_messages_used = 0
    subscription.document_uploads_used = 0
    subscription.prep_sessions_used = 0
    subscription.mock_interviews_used = 0
    db.commit()
    db.refresh(subscription)
    return _build_subscription_response(subscription)


@router.post("/consume-session", response_model=schemas.SubscriptionResponse)
def consume_session_quota(
    payload: schemas.SubscriptionSessionConsumeRequest,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    session_type = (payload.session_type or "").strip().lower()
    if session_type not in {"prep", "mock"}:
        raise HTTPException(status_code=400, detail="Invalid session type. Use 'prep' or 'mock'.")

    subscription = get_or_create_user_subscription(db, current_user.id)
    limits = get_plan_limits(subscription.plan)

    if session_type == "prep":
        limit = limits["prep_sessions_limit"]
        if limit >= 0 and subscription.prep_sessions_used >= limit:
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Free plan prep limit reached ({limit} sessions). "
                    "Upgrade to Pro for unlimited interview prep sessions."
                ),
            )
        subscription.prep_sessions_used += 1
    else:
        limit = limits["mock_interviews_limit"]
        if limit >= 0 and subscription.mock_interviews_used >= limit:
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Free plan mock interview limit reached ({limit} sessions). "
                    "Upgrade to Pro for unlimited mock interviews."
                ),
            )
        subscription.mock_interviews_used += 1

    db.commit()
    db.refresh(subscription)
    return _build_subscription_response(subscription)
