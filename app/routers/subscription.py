import hashlib
import hmac
import json
import logging
import math
import os
import re
import secrets
from datetime import datetime
from typing import Any

import requests
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import models, schemas
from app.auth import get_current_active_user
from app.database import get_db
from app.email_service import send_subscription_change_email
from app.subscriptions import (
    PLAN_FREE,
    PLAN_PRO,
    STATUS_ACTIVE,
    get_or_create_user_subscription,
    get_plan_limits,
    grant_pro_access_for_days,
)
from app.utils.rate_limiter import check_ip_rate_limit

router = APIRouter(prefix="/api/subscription", tags=["subscription"])
logger = logging.getLogger(__name__)

RAZORPAY_API_BASE = os.getenv("RAZORPAY_API_BASE", "https://api.razorpay.com/v1").rstrip("/")
UPGRADE_RATE_LIMIT = int(os.getenv("SUBSCRIPTION_UPGRADE_RATE_LIMIT", "8"))
UPGRADE_RATE_WINDOW_SECONDS = int(os.getenv("SUBSCRIPTION_UPGRADE_RATE_WINDOW_SECONDS", "900"))
VERIFY_RATE_LIMIT = int(os.getenv("SUBSCRIPTION_VERIFY_RATE_LIMIT", "20"))
VERIFY_RATE_WINDOW_SECONDS = int(os.getenv("SUBSCRIPTION_VERIFY_RATE_WINDOW_SECONDS", "900"))
WEBHOOK_RATE_LIMIT = int(os.getenv("SUBSCRIPTION_WEBHOOK_RATE_LIMIT", "120"))
WEBHOOK_RATE_WINDOW_SECONDS = int(os.getenv("SUBSCRIPTION_WEBHOOK_RATE_WINDOW_SECONDS", "60"))
RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "").strip()


def _enforce_rate_limit_or_429(
    request: Request,
    scope: str,
    limit: int,
    window_seconds: int,
    extra_key: str | None = None,
) -> None:
    allowed, retry_after = check_ip_rate_limit(
        request=request,
        scope=scope,
        limit=limit,
        window_seconds=window_seconds,
        extra_key=extra_key,
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )


def _looks_like_razorpay_id(value: str, prefix: str) -> bool:
    return bool(re.fullmatch(rf"{prefix}_[A-Za-z0-9]+", (value or "").strip()))


def _normalize_currency(raw_currency: str) -> str:
    currency = (raw_currency or "INR").strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", currency):
        return "INR"
    return currency


def _normalize_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if getattr(value, "tzinfo", None):
        return value.replace(tzinfo=None)
    return value


def _razorpay_credentials() -> tuple[str, str]:
    return (os.getenv("RAZORPAY_KEY_ID", "").strip(), os.getenv("RAZORPAY_KEY_SECRET", "").strip())


def _razorpay_checkout_enabled() -> bool:
    key_id, key_secret = _razorpay_credentials()
    return bool(key_id and key_secret)


def _razorpay_plan_id() -> str:
    return os.getenv("RAZORPAY_PLAN_ID", "").strip()


def _razorpay_recurring_total_count() -> int:
    raw = os.getenv("RAZORPAY_SUBSCRIPTION_TOTAL_COUNT", "120").strip()
    try:
        count = int(raw)
        if count <= 0:
            raise ValueError
        return count
    except ValueError:
        return 120


def _razorpay_recurring_enabled() -> bool:
    return _razorpay_checkout_enabled() and bool(_razorpay_plan_id())


def _pro_amount_paise() -> int:
    raw = os.getenv("PRO_MONTHLY_AMOUNT_PAISE", "69900").strip()
    try:
        amount = int(raw)
        if amount <= 0:
            raise ValueError
        return amount
    except ValueError:
        return 69900


def _normalize_coupon_code(raw_code: str | None) -> str:
    code = str(raw_code or "").strip().upper()
    if not code:
        return ""
    return re.sub(r"[^A-Z0-9_-]", "", code)


def _get_coupon_percent_off(db: Session, coupon_code: str) -> int:
    normalized_code = _normalize_coupon_code(coupon_code)
    if not normalized_code:
        return 0

    coupon_row = db.query(models.CouponCode).filter(
        models.CouponCode.coupon_code == normalized_code
    ).first()
    if not coupon_row:
        raise HTTPException(status_code=400, detail="Invalid coupon code.")

    try:
        percent_off = int(coupon_row.percent_off)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Coupon configuration is invalid.")
    if percent_off <= 0 or percent_off >= 100:
        raise HTTPException(status_code=400, detail="Coupon must be between 1% and 99% off.")
    return percent_off


def _compute_discounted_amount_paise(base_amount_paise: int, percent_off: int) -> int:
    if percent_off <= 0:
        return base_amount_paise
    discounted = int(math.floor((base_amount_paise * (100 - percent_off)) / 100))
    return max(discounted, 1)


def _create_discounted_plan_id(
    *,
    key_id: str,
    key_secret: str,
    currency: str,
    base_plan_id: str,
    discounted_amount_paise: int,
    percent_off: int,
) -> str:
    payload = {
        "period": "monthly",
        "interval": 1,
        "item": {
            "name": f"Rilono Pro Monthly ({percent_off}% OFF)",
            "description": f"Auto-generated discounted plan from {base_plan_id}",
            "amount": discounted_amount_paise,
            "currency": currency,
        },
        "notes": {
            "source_plan_id": base_plan_id,
            "discount_percent_off": str(percent_off),
        },
    }
    plan_data = _razorpay_request(
        method="POST",
        path="/plans",
        key_id=key_id,
        key_secret=key_secret,
        json_payload=payload,
    )
    plan_id = str(plan_data.get("id") or "").strip()
    if not _looks_like_razorpay_id(plan_id, "plan"):
        raise HTTPException(status_code=502, detail="Unable to create discounted plan right now.")
    return plan_id


def _pro_plan_currency() -> str:
    return _normalize_currency(os.getenv("PRO_PLAN_CURRENCY", "INR"))


def _pro_duration_days() -> int:
    raw = os.getenv("PRO_PLAN_DURATION_DAYS", "30").strip()
    try:
        days = int(raw)
        if days <= 0:
            raise ValueError
        return days
    except ValueError:
        return 30


def _is_provider_auto_renew_enabled(subscription_data: dict[str, Any]) -> bool:
    provider_status = str(subscription_data.get("status") or "").strip().lower()
    has_scheduled_changes = bool(subscription_data.get("has_scheduled_changes"))
    remaining_count = int(subscription_data.get("remaining_count", 0) or 0)
    cancel_at_cycle_end = bool(subscription_data.get("cancel_at_cycle_end"))
    cancel_scheduled_at = subscription_data.get("change_scheduled_at")
    ended_at = subscription_data.get("ended_at")

    if provider_status in {"cancelled", "completed", "expired", "halted", "paused"}:
        return False
    if cancel_at_cycle_end:
        return False
    if cancel_scheduled_at is not None:
        return False
    if ended_at is not None:
        return False
    if has_scheduled_changes:
        return False
    if remaining_count <= 0:
        return False
    return provider_status in {"created", "authenticated", "active", "pending"}


def _build_subscription_response(
    subscription: models.Subscription,
    *,
    auto_renew_enabled: bool | None = None,
    recurring_subscription_status: str | None = None,
    next_renewal_at: datetime | None = None,
    access_source: str | None = None,
    referral_bonus_active: bool = False,
    referral_bonus_granted_at: datetime | None = None,
    recurring_subscription_id: str | None = None,
    latest_payment_status: str | None = None,
    latest_payment_amount_paise: int | None = None,
    latest_payment_currency: str | None = None,
    latest_payment_verified_at: datetime | None = None,
) -> schemas.SubscriptionResponse:
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
        started_at=_normalize_datetime(subscription.started_at),
        ends_at=_normalize_datetime(subscription.ends_at),
        next_renewal_at=_normalize_datetime(next_renewal_at),
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
        is_pro=subscription.plan == PLAN_PRO,
        access_source=access_source,
        referral_bonus_active=referral_bonus_active,
        referral_bonus_granted_at=_normalize_datetime(referral_bonus_granted_at),
        recurring_subscription_id=recurring_subscription_id,
        latest_payment_status=latest_payment_status,
        latest_payment_amount_paise=latest_payment_amount_paise,
        latest_payment_currency=latest_payment_currency,
        latest_payment_verified_at=_normalize_datetime(latest_payment_verified_at),
        auto_renew_enabled=auto_renew_enabled,
        recurring_subscription_status=recurring_subscription_status,
    )


def _razorpay_request(
    method: str,
    path: str,
    key_id: str,
    key_secret: str,
    json_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = f"{RAZORPAY_API_BASE}/{path.lstrip('/')}"
    try:
        response = requests.request(
            method=method.upper(),
            url=url,
            auth=(key_id, key_secret),
            json=json_payload,
            timeout=15,
        )
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Failed to contact Razorpay: {str(exc)}")

    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail="Unable to process Razorpay request right now.")

    try:
        payload = response.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="Invalid response received from Razorpay.")

    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="Unexpected response format from Razorpay.")
    return payload


def _create_receipt(user_id: int) -> str:
    return f"rilono_pro_{user_id}_{secrets.token_hex(8)}"[:40]


def _mark_payment_failed(db: Session, payment_row: models.SubscriptionPayment, message: str) -> None:
    payment_row.status = "failed"
    payment_row.error_message = message[:1000]
    db.commit()


def _mark_payment_verified(
    payment_row: models.SubscriptionPayment,
    payment_id: str,
    subscription_id: str | None,
    invoice_id: str | None,
) -> None:
    now = datetime.utcnow()
    payment_row.razorpay_payment_id = payment_id
    payment_row.razorpay_subscription_id = subscription_id
    payment_row.razorpay_invoice_id = invoice_id
    payment_row.status = "verified"
    payment_row.signature_verified_at = now
    payment_row.verified_at = now
    payment_row.error_message = None


def _subscription_period_end(razorpay_subscription_data: dict[str, Any]) -> datetime | None:
    raw_end = razorpay_subscription_data.get("current_end")
    if raw_end is None:
        return None
    try:
        timestamp = int(raw_end)
    except (TypeError, ValueError):
        return None
    if timestamp <= 0:
        return None
    return datetime.utcfromtimestamp(timestamp)


def _subscription_next_renewal_at(razorpay_subscription_data: dict[str, Any]) -> datetime | None:
    # current_end is the most reliable next-cycle boundary for recurring subscriptions.
    raw_next = razorpay_subscription_data.get("current_end")
    if raw_next is None:
        raw_next = razorpay_subscription_data.get("charge_at")
    try:
        timestamp = int(raw_next or 0)
    except (TypeError, ValueError):
        return None
    if timestamp <= 0:
        return None
    return datetime.utcfromtimestamp(timestamp)


def _apply_pro_access_from_provider_period(
    db: Session,
    user_id: int,
    razorpay_subscription_data: dict[str, Any],
    commit: bool,
) -> models.Subscription:
    provider_period_end = _subscription_period_end(razorpay_subscription_data)
    now = datetime.utcnow()

    if provider_period_end and provider_period_end > now:
        subscription = get_or_create_user_subscription(db, user_id, commit=False)
        subscription.plan = PLAN_PRO
        subscription.status = STATUS_ACTIVE if _is_provider_auto_renew_enabled(razorpay_subscription_data) else "canceled"
        existing_end = _normalize_datetime(subscription.ends_at)
        if existing_end and existing_end > provider_period_end:
            subscription.ends_at = existing_end
        else:
            subscription.ends_at = provider_period_end

        if commit:
            db.commit()
            db.refresh(subscription)
        else:
            db.flush()
        return subscription

    return grant_pro_access_for_days(
        db=db,
        user_id=user_id,
        days=_pro_duration_days(),
        commit=commit,
    )


def _validate_razorpay_order_payment(
    current_user: models.User,
    payment_row: models.SubscriptionPayment,
    payload: schemas.RazorpayPaymentVerifyRequest,
    verify_checkout_signature: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    key_id, key_secret = _razorpay_credentials()
    if not key_id or not key_secret:
        raise HTTPException(status_code=503, detail="Payment verification is not configured.")

    if not _looks_like_razorpay_id(payload.razorpay_order_id, "order"):
        raise HTTPException(status_code=400, detail="Invalid Razorpay order id format.")
    if not _looks_like_razorpay_id(payload.razorpay_payment_id, "pay"):
        raise HTTPException(status_code=400, detail="Invalid Razorpay payment id format.")

    if verify_checkout_signature:
        signed_payload = f"{payload.razorpay_order_id}|{payload.razorpay_payment_id}".encode("utf-8")
        expected_signature = hmac.new(
            key_secret.encode("utf-8"),
            signed_payload,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected_signature, payload.razorpay_signature):
            raise HTTPException(status_code=400, detail="Invalid payment signature.")

    order_data = _razorpay_request(
        method="GET",
        path=f"/orders/{payload.razorpay_order_id}",
        key_id=key_id,
        key_secret=key_secret,
    )
    payment_data = _razorpay_request(
        method="GET",
        path=f"/payments/{payload.razorpay_payment_id}",
        key_id=key_id,
        key_secret=key_secret,
    )

    if order_data.get("id") != payment_row.razorpay_order_id:
        raise HTTPException(status_code=400, detail="Razorpay order mismatch.")
    if str(order_data.get("status", "")).lower() != "paid":
        raise HTTPException(status_code=400, detail="Payment order is not marked as paid yet.")
    if int(order_data.get("amount", 0) or 0) != int(payment_row.amount_paise):
        raise HTTPException(status_code=400, detail="Payment amount mismatch.")
    if _normalize_currency(order_data.get("currency", "")) != _normalize_currency(payment_row.currency):
        raise HTTPException(status_code=400, detail="Payment currency mismatch.")

    order_notes = order_data.get("notes") or {}
    order_user_id = str(order_notes.get("user_id", "")).strip()
    if order_user_id and order_user_id != str(current_user.id):
        raise HTTPException(status_code=403, detail="Payment order does not belong to this account.")

    if payment_data.get("id") != payload.razorpay_payment_id:
        raise HTTPException(status_code=400, detail="Razorpay payment mismatch.")
    if payment_data.get("order_id") != payment_row.razorpay_order_id:
        raise HTTPException(status_code=400, detail="Payment does not belong to this order.")
    if int(payment_data.get("amount", 0) or 0) != int(payment_row.amount_paise):
        raise HTTPException(status_code=400, detail="Payment amount validation failed.")
    if _normalize_currency(payment_data.get("currency", "")) != _normalize_currency(payment_row.currency):
        raise HTTPException(status_code=400, detail="Payment currency validation failed.")

    payment_status = str(payment_data.get("status", "")).lower()
    payment_captured = bool(payment_data.get("captured"))
    if payment_status != "captured" and not payment_captured:
        raise HTTPException(status_code=400, detail="Payment is not captured yet.")

    return order_data, payment_data


def _validate_razorpay_recurring_charge(
    current_user: models.User,
    payment_row: models.SubscriptionPayment,
    subscription_id: str,
    payment_id: str,
    signature: str | None,
    verify_checkout_signature: bool,
    allow_subscription_rebind: bool = False,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    key_id, key_secret = _razorpay_credentials()
    if not key_id or not key_secret:
        raise HTTPException(status_code=503, detail="Payment verification is not configured.")

    if not _looks_like_razorpay_id(subscription_id, "sub"):
        raise HTTPException(status_code=400, detail="Invalid Razorpay subscription id format.")
    if not _looks_like_razorpay_id(payment_id, "pay"):
        raise HTTPException(status_code=400, detail="Invalid Razorpay payment id format.")

    if verify_checkout_signature:
        signed_payload = f"{payment_id}|{subscription_id}".encode("utf-8")
        expected_signature = hmac.new(
            key_secret.encode("utf-8"),
            signed_payload,
            hashlib.sha256,
        ).hexdigest()
        if not signature or not hmac.compare_digest(expected_signature, signature):
            raise HTTPException(status_code=400, detail="Invalid recurring payment signature.")

    subscription_data = _razorpay_request(
        method="GET",
        path=f"/subscriptions/{subscription_id}",
        key_id=key_id,
        key_secret=key_secret,
    )
    payment_data = _razorpay_request(
        method="GET",
        path=f"/payments/{payment_id}",
        key_id=key_id,
        key_secret=key_secret,
    )

    if subscription_data.get("id") != subscription_id:
        raise HTTPException(status_code=400, detail="Razorpay subscription mismatch.")

    expected_plan_id = str(payment_row.razorpay_plan_id or "").strip()
    actual_plan_id = str(subscription_data.get("plan_id") or "").strip()
    if expected_plan_id and actual_plan_id != expected_plan_id:
        raise HTTPException(status_code=400, detail="Recurring subscription plan mismatch.")

    subscription_notes = subscription_data.get("notes") or {}
    notes_user_id = str(subscription_notes.get("user_id", "")).strip()
    notes_user_email = str(subscription_notes.get("user_email", "")).strip().lower()
    if not notes_user_id or not notes_user_email:
        raise HTTPException(status_code=400, detail="Subscription ownership metadata is missing.")
    if notes_user_id and notes_user_id != str(current_user.id):
        raise HTTPException(status_code=403, detail="This recurring subscription belongs to another account.")
    if notes_user_email and notes_user_email != (current_user.email or "").strip().lower():
        raise HTTPException(status_code=403, detail="This recurring subscription belongs to another account.")

    if payment_data.get("id") != payment_id:
        raise HTTPException(status_code=400, detail="Razorpay payment mismatch.")

    payment_subscription_id = str(payment_data.get("subscription_id") or "").strip()
    if not _looks_like_razorpay_id(payment_subscription_id, "sub"):
        # Some recurring payment methods may omit `subscription_id` on payment payload.
        # In that case, fallback to invoice lookup and resolve subscription ownership from invoice.
        invoice_id = str(payment_data.get("invoice_id") or "").strip()
        if _looks_like_razorpay_id(invoice_id, "inv"):
            invoice_data = _razorpay_request(
                method="GET",
                path=f"/invoices/{invoice_id}",
                key_id=key_id,
                key_secret=key_secret,
            )
            payment_subscription_id = str(invoice_data.get("subscription_id") or "").strip()

    effective_subscription_id = subscription_id
    if payment_subscription_id != subscription_id:
        if not allow_subscription_rebind:
            raise HTTPException(status_code=400, detail="Payment does not belong to this subscription.")
        if not _looks_like_razorpay_id(payment_subscription_id, "sub"):
            raise HTTPException(status_code=400, detail="Recurring payment is not linked to a valid subscription id.")
        rebound_subscription_data = _razorpay_request(
            method="GET",
            path=f"/subscriptions/{payment_subscription_id}",
            key_id=key_id,
            key_secret=key_secret,
        )
        if rebound_subscription_data.get("id") != payment_subscription_id:
            raise HTTPException(status_code=400, detail="Unable to verify subscription linked to this payment.")

        rebound_plan_id = str(rebound_subscription_data.get("plan_id") or "").strip()
        if expected_plan_id and rebound_plan_id != expected_plan_id:
            raise HTTPException(status_code=400, detail="Recurring payment was created for a different plan.")

        rebound_notes = rebound_subscription_data.get("notes") or {}
        rebound_user_id = str(rebound_notes.get("user_id", "")).strip()
        rebound_user_email = str(rebound_notes.get("user_email", "")).strip().lower()
        if rebound_user_id != str(current_user.id):
            raise HTTPException(status_code=403, detail="This recurring subscription belongs to another account.")
        if rebound_user_email != (current_user.email or "").strip().lower():
            raise HTTPException(status_code=403, detail="This recurring subscription belongs to another account.")

        subscription_data = rebound_subscription_data
        effective_subscription_id = payment_subscription_id

    payment_status = str(payment_data.get("status", "")).lower()
    payment_captured = bool(payment_data.get("captured"))
    if payment_status != "captured" and not payment_captured:
        raise HTTPException(status_code=400, detail="Recurring payment is not captured yet.")

    if payment_row.razorpay_plan_id:
        actual_amount = int(payment_data.get("amount", 0) or 0)
        actual_currency = _normalize_currency(payment_data.get("currency", ""))
        if actual_amount <= 0:
            raise HTTPException(status_code=400, detail="Recurring payment amount validation failed.")
        if not actual_currency:
            raise HTTPException(status_code=400, detail="Recurring payment currency validation failed.")

        # Self-heal amount/currency drift on pre-verified rows (for example, plan-price changes or
        # legacy rows from earlier validation logic). Source of truth is Razorpay capture payload.
        if int(payment_row.amount_paise or 0) != actual_amount:
            logger.warning(
                "Recurring payment amount drift corrected payment_row_id=%s stored=%s actual=%s",
                payment_row.id,
                payment_row.amount_paise,
                actual_amount,
            )
            payment_row.amount_paise = actual_amount
        if _normalize_currency(payment_row.currency) != actual_currency:
            logger.warning(
                "Recurring payment currency drift corrected payment_row_id=%s stored=%s actual=%s",
                payment_row.id,
                payment_row.currency,
                actual_currency,
            )
            payment_row.currency = actual_currency

    return subscription_data, payment_data, effective_subscription_id


def _find_latest_subscription_id_for_user(db: Session, user_id: int) -> str | None:
    row = (
        db.query(models.SubscriptionPayment)
        .filter(
            models.SubscriptionPayment.user_id == user_id,
            models.SubscriptionPayment.provider == "razorpay",
            models.SubscriptionPayment.razorpay_subscription_id.isnot(None),
        )
        .order_by(models.SubscriptionPayment.id.desc())
        .first()
    )
    if not row:
        return None
    return (row.razorpay_subscription_id or "").strip() or None


def _find_latest_payment_for_user(db: Session, user_id: int) -> models.SubscriptionPayment | None:
    return (
        db.query(models.SubscriptionPayment)
        .filter(
            models.SubscriptionPayment.user_id == user_id,
            models.SubscriptionPayment.provider == "razorpay",
        )
        .order_by(models.SubscriptionPayment.id.desc())
        .first()
    )


def _order_ref_for_subscription_payment(payment_data: dict[str, Any], subscription_id: str, payment_id: str) -> str:
    order_id = str(payment_data.get("order_id") or "").strip()
    if _looks_like_razorpay_id(order_id, "order"):
        return order_id
    return f"{subscription_id}:{payment_id}"


def _ensure_unique_order_ref(db: Session, proposed_ref: str) -> str:
    candidate = (proposed_ref or "").strip()[:255]
    if not candidate:
        candidate = f"subpay:{secrets.token_hex(8)}"

    exists = db.query(models.SubscriptionPayment.id).filter(
        models.SubscriptionPayment.razorpay_order_id == candidate
    ).first()
    if not exists:
        return candidate

    while True:
        suffix = secrets.token_hex(4)
        next_candidate = f"{candidate}:{suffix}"[:255]
        exists = db.query(models.SubscriptionPayment.id).filter(
            models.SubscriptionPayment.razorpay_order_id == next_candidate
        ).first()
        if not exists:
            return next_candidate


def _finalize_verified_payment(
    db: Session,
    user_id: int,
    payment_row: models.SubscriptionPayment,
    payment_id: str,
    subscription_id: str | None,
    invoice_id: str | None,
    provider_subscription_data: dict[str, Any] | None,
) -> models.Subscription:
    _mark_payment_verified(
        payment_row=payment_row,
        payment_id=payment_id,
        subscription_id=subscription_id,
        invoice_id=invoice_id,
    )

    if provider_subscription_data:
        subscription = _apply_pro_access_from_provider_period(
            db=db,
            user_id=user_id,
            razorpay_subscription_data=provider_subscription_data,
            commit=False,
        )
    else:
        subscription = grant_pro_access_for_days(
            db=db,
            user_id=user_id,
            days=_pro_duration_days(),
            commit=False,
        )

    db.commit()
    db.refresh(subscription)
    return subscription


def _resolve_user_from_subscription_notes(db: Session, subscription_data: dict[str, Any]) -> models.User | None:
    notes = subscription_data.get("notes") or {}

    user_id_raw = str(notes.get("user_id", "")).strip()
    if user_id_raw.isdigit():
        user = db.query(models.User).filter(models.User.id == int(user_id_raw)).first()
        if user:
            return user

    user_email = str(notes.get("user_email", "")).strip().lower()
    if user_email:
        return db.query(models.User).filter(models.User.email == user_email).first()

    return None


def _downgrade_to_free(subscription: models.Subscription) -> None:
    subscription.plan = PLAN_FREE
    subscription.status = STATUS_ACTIVE
    subscription.ends_at = None
    subscription.ai_messages_used = 0
    subscription.document_uploads_used = 0
    subscription.prep_sessions_used = 0
    subscription.mock_interviews_used = 0


def _subscription_change_snapshot(subscription: models.Subscription) -> dict[str, Any]:
    return {
        "plan": (subscription.plan or PLAN_FREE).strip().lower(),
        "status": (subscription.status or STATUS_ACTIVE).strip().lower(),
        "ends_at": _normalize_datetime(subscription.ends_at),
    }


def _send_subscription_change_email_safe(
    *,
    user: models.User,
    event_type: str,
    subscription: models.Subscription,
    auto_renew_enabled: bool | None = None,
    next_renewal_at: datetime | None = None,
    payment_status: str | None = None,
    payment_amount_paise: int | None = None,
    payment_currency: str | None = None,
) -> None:
    if not user.email:
        return
    try:
        send_subscription_change_email(
            email=user.email,
            full_name=user.full_name,
            event_type=event_type,
            plan=subscription.plan,
            status=subscription.status,
            auto_renew_enabled=auto_renew_enabled,
            access_until=_normalize_datetime(subscription.ends_at),
            next_renewal_at=_normalize_datetime(next_renewal_at),
            payment_amount_paise=payment_amount_paise,
            payment_currency=(payment_currency or "INR"),
            payment_status=payment_status,
        )
    except Exception:
        logger.exception(
            "Failed to send subscription change email user_id=%s event_type=%s",
            user.id,
            event_type,
        )


@router.get("/me", response_model=schemas.SubscriptionResponse)
def get_my_subscription(
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    subscription = get_or_create_user_subscription(db, current_user.id)
    auto_renew_enabled: bool | None = None
    recurring_subscription_status: str | None = None
    next_renewal_at: datetime | None = None
    recurring_subscription_id = _find_latest_subscription_id_for_user(db, current_user.id)

    if subscription.plan == PLAN_PRO:
        if str(subscription.status or "").strip().lower() == "canceled":
            auto_renew_enabled = False
            recurring_subscription_status = "cancelled"
        key_id, key_secret = _razorpay_credentials()
        if (
            recurring_subscription_id
            and _looks_like_razorpay_id(recurring_subscription_id, "sub")
            and key_id
            and key_secret
        ):
            try:
                subscription_data = _razorpay_request(
                    method="GET",
                    path=f"/subscriptions/{recurring_subscription_id}",
                    key_id=key_id,
                    key_secret=key_secret,
                )
                recurring_subscription_status = str(subscription_data.get("status") or "").strip().lower() or None
                auto_renew_enabled = _is_provider_auto_renew_enabled(subscription_data)
                next_renewal_at = _subscription_next_renewal_at(subscription_data)
            except HTTPException:
                pass

    latest_payment = _find_latest_payment_for_user(db, current_user.id)
    latest_verified_payment = (
        db.query(models.SubscriptionPayment)
        .filter(
            models.SubscriptionPayment.user_id == current_user.id,
            models.SubscriptionPayment.provider == "razorpay",
            models.SubscriptionPayment.status == "verified",
        )
        .order_by(models.SubscriptionPayment.id.desc())
        .first()
    )

    has_verified_payment = latest_verified_payment is not None
    ends_at = _normalize_datetime(subscription.ends_at)
    now = datetime.utcnow()
    referral_bonus_active = bool(
        subscription.plan == PLAN_PRO
        and current_user.referral_reward_granted_at
        and ends_at
        and ends_at > now
        and not has_verified_payment
        and not recurring_subscription_id
    )

    if subscription.plan != PLAN_PRO:
        access_source = "Free Plan"
    elif referral_bonus_active:
        access_source = "Referral Bonus (1 Month Pro)"
    elif has_verified_payment:
        if auto_renew_enabled is False:
            access_source = "Paid Pro (Auto-Renew Off)"
        elif auto_renew_enabled is True:
            access_source = "Paid Pro (Auto-Renew On)"
        else:
            access_source = "Paid Pro"
    elif ends_at and ends_at > now:
        access_source = "Pro Access (Time-Limited)"
    else:
        access_source = "Pro Access"

    return _build_subscription_response(
        subscription,
        auto_renew_enabled=auto_renew_enabled,
        recurring_subscription_status=recurring_subscription_status,
        next_renewal_at=next_renewal_at,
        access_source=access_source,
        referral_bonus_active=referral_bonus_active,
        referral_bonus_granted_at=_normalize_datetime(current_user.referral_reward_granted_at),
        recurring_subscription_id=recurring_subscription_id,
        latest_payment_status=(latest_payment.status if latest_payment else None),
        latest_payment_amount_paise=(latest_payment.amount_paise if latest_payment else None),
        latest_payment_currency=(latest_payment.currency if latest_payment else None),
        latest_payment_verified_at=(
            _normalize_datetime(latest_payment.verified_at) if latest_payment and latest_payment.verified_at else None
        ),
    )


@router.post("/upgrade")
def upgrade_to_pro(
    request: Request,
    payload: schemas.SubscriptionUpgradeRequest | None = Body(default=None),
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    _enforce_rate_limit_or_429(
        request=request,
        scope="subscription.upgrade",
        limit=UPGRADE_RATE_LIMIT,
        window_seconds=UPGRADE_RATE_WINDOW_SECONDS,
        extra_key=str(current_user.id),
    )

    if not current_user.email_verified:
        raise HTTPException(
            status_code=403,
            detail="Please verify your email before upgrading to Pro.",
        )

    subscription = get_or_create_user_subscription(db, current_user.id)
    key_id, key_secret = _razorpay_credentials()

    if subscription.plan == PLAN_PRO and subscription.status == STATUS_ACTIVE:
        auto_renew_enabled: bool | None = None
        recurring_subscription_status: str | None = None

        if _razorpay_recurring_enabled() and key_id and key_secret:
            existing_subscription_id = _find_latest_subscription_id_for_user(db, current_user.id)
            if existing_subscription_id and _looks_like_razorpay_id(existing_subscription_id, "sub"):
                try:
                    existing_subscription_data = _razorpay_request(
                        method="GET",
                        path=f"/subscriptions/{existing_subscription_id}",
                        key_id=key_id,
                        key_secret=key_secret,
                    )
                    recurring_subscription_status = (
                        str(existing_subscription_data.get("status") or "").strip().lower() or None
                    )
                    auto_renew_enabled = _is_provider_auto_renew_enabled(existing_subscription_data)
                except HTTPException:
                    auto_renew_enabled = None
                    recurring_subscription_status = None

        # If user is already Pro but auto-renew is OFF, allow renewing from checkout.
        if auto_renew_enabled is not False:
            return {
                "action": "already_pro",
                "message": "Your account is already on Pro.",
                "subscription": _build_subscription_response(
                    subscription,
                    auto_renew_enabled=auto_renew_enabled,
                    recurring_subscription_status=recurring_subscription_status,
                ).model_dump(),
            }

    if not _razorpay_checkout_enabled():
        return {
            "action": "contact_support",
            "message": "Pro checkout is being enabled. Please contact support to activate billing.",
            "contact_path": "/contact",
        }

    base_amount = _pro_amount_paise()
    currency = _pro_plan_currency()
    base_plan_id = _razorpay_plan_id()

    coupon_code = _normalize_coupon_code(payload.coupon_code if payload else "")
    percent_off = _get_coupon_percent_off(db, coupon_code) if coupon_code else 0
    effective_amount = _compute_discounted_amount_paise(base_amount, percent_off)
    effective_plan_id = base_plan_id
    coupon_applied_text = (
        f"Coupon {coupon_code} applied ({percent_off}% OFF)." if percent_off > 0 else None
    )

    if _razorpay_recurring_enabled():
        existing_subscription_id = _find_latest_subscription_id_for_user(db, current_user.id)
        if existing_subscription_id and _looks_like_razorpay_id(existing_subscription_id, "sub"):
            try:
                existing_subscription_data = _razorpay_request(
                    method="GET",
                    path=f"/subscriptions/{existing_subscription_id}",
                    key_id=key_id,
                    key_secret=key_secret,
                )
                existing_status = str(existing_subscription_data.get("status") or "").strip().lower()
                existing_plan_id = str(existing_subscription_data.get("plan_id") or "").strip()
                existing_notes = existing_subscription_data.get("notes") or {}
                existing_notes_user_id = str(existing_notes.get("user_id") or "").strip()
                existing_notes_user_email = str(existing_notes.get("user_email") or "").strip().lower()
                existing_coupon_code = _normalize_coupon_code(existing_notes.get("coupon_code"))
                existing_coupon_percent = str(existing_notes.get("coupon_percent_off") or "").strip()
                existing_coupon_match = (
                    percent_off > 0
                    and existing_coupon_code == coupon_code
                    and existing_coupon_percent == str(percent_off)
                )
                if (
                    existing_status in {"created", "authenticated", "active", "pending"}
                    and (
                        (percent_off <= 0 and existing_plan_id == base_plan_id)
                        or existing_coupon_match
                    )
                    and existing_notes_user_id == str(current_user.id)
                    and existing_notes_user_email == (current_user.email or "").strip().lower()
                ):
                    return {
                        "action": "razorpay_checkout",
                        "checkout_mode": "subscription",
                        "key_id": key_id,
                        "subscription_id": existing_subscription_id,
                        "amount": effective_amount,
                        "currency": currency,
                        "name": "Rilono",
                        "description": "Rilono Pro Subscription (Auto-renew, cancel anytime)",
                        "coupon_applied_text": coupon_applied_text,
                    }
            except HTTPException:
                pass

        if percent_off > 0:
            effective_plan_id = _create_discounted_plan_id(
                key_id=key_id,
                key_secret=key_secret,
                currency=currency,
                base_plan_id=base_plan_id,
                discounted_amount_paise=effective_amount,
                percent_off=percent_off,
            )

        recurring_payload = {
            "plan_id": effective_plan_id,
            "total_count": _razorpay_recurring_total_count(),
            "customer_notify": 1,
            "quantity": 1,
            "notes": {
                "user_id": str(current_user.id),
                "user_email": current_user.email,
                "plan": PLAN_PRO,
                "coupon_code": coupon_code,
                "coupon_percent_off": str(percent_off),
            },
        }
        recurring_data = _razorpay_request(
            method="POST",
            path="/subscriptions",
            key_id=key_id,
            key_secret=key_secret,
            json_payload=recurring_payload,
        )

        subscription_id = str(recurring_data.get("id", "")).strip()
        if not _looks_like_razorpay_id(subscription_id, "sub"):
            raise HTTPException(status_code=502, detail="Invalid recurring subscription response from Razorpay.")

        payment_row = models.SubscriptionPayment(
            user_id=current_user.id,
            provider="razorpay",
            plan=PLAN_PRO,
            amount_paise=effective_amount,
            currency=currency,
            razorpay_plan_id=effective_plan_id,
            razorpay_order_id=subscription_id,
            razorpay_subscription_id=subscription_id,
            status="created",
        )
        db.add(payment_row)
        db.commit()

        return {
            "action": "razorpay_checkout",
            "checkout_mode": "subscription",
            "key_id": key_id,
            "subscription_id": subscription_id,
            "amount": effective_amount,
            "currency": currency,
            "name": "Rilono",
            "description": "Rilono Pro Subscription (Auto-renew, cancel anytime)",
            "coupon_applied_text": coupon_applied_text,
        }

    receipt = _create_receipt(current_user.id)
    order_payload = {
        "amount": effective_amount,
        "currency": currency,
        "receipt": receipt,
        "notes": {
            "user_id": str(current_user.id),
            "user_email": current_user.email,
            "plan": PLAN_PRO,
            "coupon_code": coupon_code,
            "coupon_percent_off": str(percent_off),
        },
    }

    order_data = _razorpay_request(
        method="POST",
        path="/orders",
        key_id=key_id,
        key_secret=key_secret,
        json_payload=order_payload,
    )

    order_id = str(order_data.get("id", "")).strip()
    if not _looks_like_razorpay_id(order_id, "order"):
        raise HTTPException(status_code=502, detail="Invalid payment order response from Razorpay.")

    payment_row = models.SubscriptionPayment(
        user_id=current_user.id,
        provider="razorpay",
        plan=PLAN_PRO,
        amount_paise=effective_amount,
        currency=currency,
        razorpay_plan_id=effective_plan_id or None,
        razorpay_order_id=order_id,
        status="created",
    )
    db.add(payment_row)
    db.commit()

    return {
        "action": "razorpay_checkout",
        "checkout_mode": "order",
        "key_id": key_id,
        "order_id": order_id,
        "amount": int(order_data.get("amount", effective_amount) or effective_amount),
        "currency": _normalize_currency(order_data.get("currency", currency)),
        "name": "Rilono",
        "description": "Rilono Pro Subscription",
        "coupon_applied_text": coupon_applied_text,
    }


@router.post("/verify-payment", response_model=schemas.SubscriptionResponse)
def verify_payment_and_activate_pro(
    payload: schemas.RazorpayPaymentVerifyRequest,
    request: Request,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    _enforce_rate_limit_or_429(
        request=request,
        scope="subscription.verify_payment",
        limit=VERIFY_RATE_LIMIT,
        window_seconds=VERIFY_RATE_WINDOW_SECONDS,
        extra_key=str(current_user.id),
    )

    query = db.query(models.SubscriptionPayment).filter(
        models.SubscriptionPayment.user_id == current_user.id,
        models.SubscriptionPayment.razorpay_order_id == payload.razorpay_order_id,
        models.SubscriptionPayment.provider == "razorpay",
    )
    if db.bind and db.bind.dialect.name != "sqlite":
        query = query.with_for_update()
    payment_row = query.first()
    if not payment_row:
        raise HTTPException(status_code=404, detail="Payment order not found for this user.")

    existing_payment = db.query(models.SubscriptionPayment).filter(
        models.SubscriptionPayment.razorpay_payment_id == payload.razorpay_payment_id,
        models.SubscriptionPayment.id != payment_row.id,
    ).first()
    if existing_payment:
        if existing_payment.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Payment id is not valid for this user.")
        if existing_payment.status == "verified":
            subscription = get_or_create_user_subscription(db, current_user.id)
            return _build_subscription_response(subscription)
        raise HTTPException(status_code=400, detail="Payment is already tied to another order.")

    if payment_row.status == "verified":
        subscription = get_or_create_user_subscription(db, current_user.id)
        return _build_subscription_response(subscription)

    if payment_row.razorpay_payment_id and payment_row.razorpay_payment_id != payload.razorpay_payment_id:
        raise HTTPException(status_code=400, detail="Order is already linked to a different payment.")

    before_subscription = get_or_create_user_subscription(db, current_user.id, commit=False)
    before_snapshot = _subscription_change_snapshot(before_subscription)

    try:
        _validate_razorpay_order_payment(
            current_user=current_user,
            payment_row=payment_row,
            payload=payload,
            verify_checkout_signature=True,
        )
    except HTTPException as exc:
        _mark_payment_failed(db, payment_row, str(exc.detail))
        raise

    subscription = _finalize_verified_payment(
        db=db,
        user_id=current_user.id,
        payment_row=payment_row,
        payment_id=payload.razorpay_payment_id,
        subscription_id=None,
        invoice_id=None,
        provider_subscription_data=None,
    )
    after_snapshot = _subscription_change_snapshot(subscription)
    if before_snapshot != after_snapshot:
        event_type = "pro_activated" if before_snapshot["plan"] != PLAN_PRO else "subscription_renewed"
        _send_subscription_change_email_safe(
            user=current_user,
            event_type=event_type,
            subscription=subscription,
            auto_renew_enabled=False,
            next_renewal_at=_normalize_datetime(subscription.ends_at),
            payment_status="verified",
            payment_amount_paise=int(payment_row.amount_paise or 0),
            payment_currency=_normalize_currency(payment_row.currency or "INR"),
        )
    return _build_subscription_response(subscription)


@router.post("/verify-recurring-payment", response_model=schemas.SubscriptionResponse)
def verify_recurring_payment_and_activate_pro(
    payload: schemas.RazorpayRecurringPaymentVerifyRequest,
    request: Request,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    _enforce_rate_limit_or_429(
        request=request,
        scope="subscription.verify_payment",
        limit=VERIFY_RATE_LIMIT,
        window_seconds=VERIFY_RATE_WINDOW_SECONDS,
        extra_key=str(current_user.id),
    )

    before_subscription = get_or_create_user_subscription(db, current_user.id, commit=False)
    before_snapshot = _subscription_change_snapshot(before_subscription)

    existing_payment = db.query(models.SubscriptionPayment).filter(
        models.SubscriptionPayment.razorpay_payment_id == payload.razorpay_payment_id,
        models.SubscriptionPayment.provider == "razorpay",
    ).first()
    if existing_payment and existing_payment.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Payment id is not valid for this user.")
    if existing_payment and existing_payment.status == "verified":
        subscription = get_or_create_user_subscription(db, current_user.id)
        return _build_subscription_response(subscription)

    seed_row = existing_payment
    if not seed_row:
        query = db.query(models.SubscriptionPayment).filter(
            models.SubscriptionPayment.user_id == current_user.id,
            models.SubscriptionPayment.provider == "razorpay",
            models.SubscriptionPayment.razorpay_subscription_id == payload.razorpay_subscription_id,
        )
        if db.bind and db.bind.dialect.name != "sqlite":
            query = query.with_for_update()
        seed_row = query.order_by(models.SubscriptionPayment.id.desc()).first()

    if not seed_row:
        seed_row = models.SubscriptionPayment(
            user_id=current_user.id,
            provider="razorpay",
            plan=PLAN_PRO,
            amount_paise=_pro_amount_paise(),
            currency=_pro_plan_currency(),
            razorpay_plan_id=None,
            razorpay_order_id=payload.razorpay_subscription_id,
            razorpay_subscription_id=payload.razorpay_subscription_id,
            status="created",
        )
        db.add(seed_row)
        db.flush()

    try:
        subscription_data, payment_data, effective_subscription_id = _validate_razorpay_recurring_charge(
            current_user=current_user,
            payment_row=seed_row,
            subscription_id=payload.razorpay_subscription_id,
            payment_id=payload.razorpay_payment_id,
            signature=payload.razorpay_signature,
            verify_checkout_signature=True,
            allow_subscription_rebind=True,
        )
    except HTTPException as exc:
        # Persist payment id for debugging and reconciliation even when verification fails.
        if payload.razorpay_payment_id and not seed_row.razorpay_payment_id:
            seed_row.razorpay_payment_id = payload.razorpay_payment_id
        logger.warning(
            "Recurring payment verify failed user_id=%s payload_sub=%s seed_sub=%s payment_id=%s detail=%s",
            current_user.id,
            payload.razorpay_subscription_id,
            seed_row.razorpay_subscription_id,
            payload.razorpay_payment_id,
            str(exc.detail),
        )
        _mark_payment_failed(db, seed_row, str(exc.detail))
        raise

    target_row = seed_row
    if (target_row.razorpay_subscription_id or "").strip() != effective_subscription_id:
        existing_row = (
            db.query(models.SubscriptionPayment)
            .filter(
                models.SubscriptionPayment.user_id == current_user.id,
                models.SubscriptionPayment.provider == "razorpay",
                models.SubscriptionPayment.razorpay_subscription_id == effective_subscription_id,
            )
            .order_by(models.SubscriptionPayment.id.desc())
            .first()
        )
        if existing_row:
            target_row = existing_row
        else:
            target_row = models.SubscriptionPayment(
                user_id=current_user.id,
                provider="razorpay",
                plan=PLAN_PRO,
                amount_paise=seed_row.amount_paise,
                currency=seed_row.currency,
                razorpay_plan_id=seed_row.razorpay_plan_id,
                razorpay_order_id=_ensure_unique_order_ref(
                    db,
                    _order_ref_for_subscription_payment(
                        payment_data=payment_data,
                        subscription_id=effective_subscription_id,
                        payment_id=payload.razorpay_payment_id,
                    ),
                ),
                razorpay_subscription_id=effective_subscription_id,
                status="created",
            )
            db.add(target_row)

    if seed_row.razorpay_payment_id and seed_row.razorpay_payment_id != payload.razorpay_payment_id:
        proposed_order_ref = _order_ref_for_subscription_payment(
            payment_data=payment_data,
            subscription_id=effective_subscription_id,
            payment_id=payload.razorpay_payment_id,
        )
        target_row = models.SubscriptionPayment(
            user_id=current_user.id,
            provider="razorpay",
            plan=PLAN_PRO,
            amount_paise=seed_row.amount_paise,
            currency=seed_row.currency,
            razorpay_plan_id=seed_row.razorpay_plan_id,
            razorpay_order_id=_ensure_unique_order_ref(db, proposed_order_ref),
            razorpay_subscription_id=effective_subscription_id,
            status="created",
        )
        db.add(target_row)

    invoice_id = str(payment_data.get("invoice_id") or "").strip() or None
    subscription = _finalize_verified_payment(
        db=db,
        user_id=current_user.id,
        payment_row=target_row,
        payment_id=payload.razorpay_payment_id,
        subscription_id=effective_subscription_id,
        invoice_id=invoice_id,
        provider_subscription_data=subscription_data,
    )
    after_snapshot = _subscription_change_snapshot(subscription)
    if before_snapshot != after_snapshot:
        event_type = "pro_activated" if before_snapshot["plan"] != PLAN_PRO else "subscription_renewed"
        _send_subscription_change_email_safe(
            user=current_user,
            event_type=event_type,
            subscription=subscription,
            auto_renew_enabled=_is_provider_auto_renew_enabled(subscription_data),
            next_renewal_at=_subscription_next_renewal_at(subscription_data),
            payment_status=str(payment_data.get("status") or "verified"),
            payment_amount_paise=int(payment_data.get("amount", 0) or 0),
            payment_currency=_normalize_currency(payment_data.get("currency", "")),
        )
    return _build_subscription_response(subscription)


def _handle_recurring_payment_webhook(
    db: Session,
    payment_entity: dict[str, Any],
) -> dict[str, Any]:
    subscription_id = str(payment_entity.get("subscription_id") or "").strip()
    payment_id = str(payment_entity.get("id") or "").strip()
    if not _looks_like_razorpay_id(subscription_id, "sub") or not _looks_like_razorpay_id(payment_id, "pay"):
        return {"status": "ignored", "reason": "invalid_ids"}

    existing_payment = db.query(models.SubscriptionPayment).filter(
        models.SubscriptionPayment.provider == "razorpay",
        models.SubscriptionPayment.razorpay_payment_id == payment_id,
    ).first()
    if existing_payment and existing_payment.status == "verified":
        return {"status": "ok", "idempotent": True}

    seed_row = (
        db.query(models.SubscriptionPayment)
        .filter(
            models.SubscriptionPayment.provider == "razorpay",
            models.SubscriptionPayment.razorpay_subscription_id == subscription_id,
        )
        .order_by(models.SubscriptionPayment.id.desc())
        .first()
    )

    key_id, key_secret = _razorpay_credentials()
    if not key_id or not key_secret:
        return {"status": "ignored", "reason": "verification_not_configured"}

    try:
        subscription_data = _razorpay_request(
            method="GET",
            path=f"/subscriptions/{subscription_id}",
            key_id=key_id,
            key_secret=key_secret,
        )
    except HTTPException:
        if seed_row:
            _mark_payment_failed(db, seed_row, "webhook_subscription_fetch_failed")
        return {"status": "ignored", "reason": "subscription_fetch_failed"}

    user: models.User | None = None
    if seed_row:
        user = db.query(models.User).filter(models.User.id == seed_row.user_id).first()
    if not user:
        user = _resolve_user_from_subscription_notes(db, subscription_data)

    if not user:
        return {"status": "ignored", "reason": "user_not_found"}

    before_subscription = get_or_create_user_subscription(db, user.id, commit=False)
    before_snapshot = _subscription_change_snapshot(before_subscription)

    if not seed_row:
        seed_row = models.SubscriptionPayment(
            user_id=user.id,
            provider="razorpay",
            plan=PLAN_PRO,
            amount_paise=_pro_amount_paise(),
            currency=_pro_plan_currency(),
            razorpay_plan_id=str(subscription_data.get("plan_id") or "").strip() or None,
            razorpay_order_id=subscription_id,
            razorpay_subscription_id=subscription_id,
            status="created",
        )
        db.add(seed_row)
        db.flush()

    try:
        subscription_data, payment_data, effective_subscription_id = _validate_razorpay_recurring_charge(
            current_user=user,
            payment_row=seed_row,
            subscription_id=subscription_id,
            payment_id=payment_id,
            signature=None,
            verify_checkout_signature=False,
            allow_subscription_rebind=False,
        )
    except HTTPException:
        _mark_payment_failed(db, seed_row, "webhook_validation_failed")
        return {"status": "ignored", "reason": "validation_failed"}

    target_row = existing_payment or seed_row
    if target_row is seed_row and seed_row.razorpay_payment_id and seed_row.razorpay_payment_id != payment_id:
        proposed_order_ref = _order_ref_for_subscription_payment(
            payment_data=payment_data,
            subscription_id=effective_subscription_id,
            payment_id=payment_id,
        )
        target_row = models.SubscriptionPayment(
            user_id=user.id,
            provider="razorpay",
            plan=PLAN_PRO,
            amount_paise=seed_row.amount_paise,
            currency=seed_row.currency,
            razorpay_plan_id=seed_row.razorpay_plan_id,
            razorpay_order_id=_ensure_unique_order_ref(db, proposed_order_ref),
            razorpay_subscription_id=effective_subscription_id,
            status="created",
        )
        db.add(target_row)

    invoice_id = str(payment_data.get("invoice_id") or "").strip() or None
    _finalize_verified_payment(
        db=db,
        user_id=user.id,
        payment_row=target_row,
        payment_id=payment_id,
        subscription_id=effective_subscription_id,
        invoice_id=invoice_id,
        provider_subscription_data=subscription_data,
    )
    refreshed_subscription = get_or_create_user_subscription(db, user.id)
    after_snapshot = _subscription_change_snapshot(refreshed_subscription)
    if before_snapshot != after_snapshot:
        event_type = "pro_activated" if before_snapshot["plan"] != PLAN_PRO else "subscription_renewed"
        _send_subscription_change_email_safe(
            user=user,
            event_type=event_type,
            subscription=refreshed_subscription,
            auto_renew_enabled=_is_provider_auto_renew_enabled(subscription_data),
            next_renewal_at=_subscription_next_renewal_at(subscription_data),
            payment_status=str(payment_data.get("status") or "verified"),
            payment_amount_paise=int(payment_data.get("amount", 0) or 0),
            payment_currency=_normalize_currency(payment_data.get("currency", "")),
        )
    return {"status": "ok"}


def _handle_subscription_lifecycle_webhook(
    db: Session,
    event_payload: dict[str, Any],
) -> dict[str, Any]:
    subscription_entity = ((event_payload.get("payload") or {}).get("subscription") or {}).get("entity") or {}
    subscription_id = str(subscription_entity.get("id") or "").strip()
    if not _looks_like_razorpay_id(subscription_id, "sub"):
        return {"status": "ignored", "reason": "invalid_subscription_id"}

    key_id, key_secret = _razorpay_credentials()
    if not key_id or not key_secret:
        return {"status": "ignored", "reason": "verification_not_configured"}

    try:
        subscription_data = _razorpay_request(
            method="GET",
            path=f"/subscriptions/{subscription_id}",
            key_id=key_id,
            key_secret=key_secret,
        )
    except HTTPException:
        return {"status": "ignored", "reason": "subscription_fetch_failed"}

    payment_row = (
        db.query(models.SubscriptionPayment)
        .filter(
            models.SubscriptionPayment.provider == "razorpay",
            models.SubscriptionPayment.razorpay_subscription_id == subscription_id,
        )
        .order_by(models.SubscriptionPayment.id.desc())
        .first()
    )

    user: models.User | None = None
    if payment_row:
        user = db.query(models.User).filter(models.User.id == payment_row.user_id).first()
    if not user:
        user = _resolve_user_from_subscription_notes(db, subscription_data)
    if not user:
        return {"status": "ignored", "reason": "user_not_found"}

    before_subscription = get_or_create_user_subscription(db, user.id, commit=False)
    before_snapshot = _subscription_change_snapshot(before_subscription)

    status = str(subscription_data.get("status") or "").strip().lower()
    if status in {"cancelled", "completed", "expired", "halted"}:
        subscription = before_subscription
        provider_period_end = _subscription_period_end(subscription_data)
        if provider_period_end and provider_period_end > datetime.utcnow():
            subscription.plan = PLAN_PRO
            subscription.status = STATUS_ACTIVE
            subscription.ends_at = provider_period_end
        else:
            _downgrade_to_free(subscription)
        db.commit()
        db.refresh(subscription)
        after_snapshot = _subscription_change_snapshot(subscription)
        if before_snapshot != after_snapshot:
            event_type = "downgraded_to_free" if subscription.plan == PLAN_FREE else "auto_renew_cancelled"
            _send_subscription_change_email_safe(
                user=user,
                event_type=event_type,
                subscription=subscription,
                auto_renew_enabled=False,
                next_renewal_at=_subscription_next_renewal_at(subscription_data),
                payment_status=str(status or "updated"),
            )
        return {"status": "ok"}

    updated_subscription = _apply_pro_access_from_provider_period(
        db=db,
        user_id=user.id,
        razorpay_subscription_data=subscription_data,
        commit=True,
    )
    after_snapshot = _subscription_change_snapshot(updated_subscription)
    if before_snapshot != after_snapshot:
        if after_snapshot["status"] == "canceled" and before_snapshot["status"] != "canceled":
            event_type = "auto_renew_cancelled"
        elif before_snapshot["plan"] != PLAN_PRO:
            event_type = "pro_activated"
        else:
            event_type = "subscription_updated"
        _send_subscription_change_email_safe(
            user=user,
            event_type=event_type,
            subscription=updated_subscription,
            auto_renew_enabled=_is_provider_auto_renew_enabled(subscription_data),
            next_renewal_at=_subscription_next_renewal_at(subscription_data),
            payment_status=str(status or "updated"),
        )
    return {"status": "ok"}


def _handle_payment_failed_webhook(
    db: Session,
    event_payload: dict[str, Any],
) -> dict[str, Any]:
    payment_entity = ((event_payload.get("payload") or {}).get("payment") or {}).get("entity") or {}
    payment_id = str(payment_entity.get("id") or "").strip()
    if not _looks_like_razorpay_id(payment_id, "pay"):
        return {"status": "ignored", "reason": "invalid_payment_id"}

    payment_row = db.query(models.SubscriptionPayment).filter(
        models.SubscriptionPayment.provider == "razorpay",
        models.SubscriptionPayment.razorpay_payment_id == payment_id,
    ).first()
    if not payment_row:
        subscription_id = str(payment_entity.get("subscription_id") or "").strip()
        if _looks_like_razorpay_id(subscription_id, "sub"):
            payment_row = (
                db.query(models.SubscriptionPayment)
                .filter(
                    models.SubscriptionPayment.provider == "razorpay",
                    models.SubscriptionPayment.razorpay_subscription_id == subscription_id,
                )
                .order_by(models.SubscriptionPayment.id.desc())
                .first()
            )
    if not payment_row:
        return {"status": "ignored", "reason": "payment_not_found"}

    previous_status = str(payment_row.status or "").strip().lower()
    _mark_payment_failed(db, payment_row, "provider_payment_failed")
    if previous_status != "failed":
        user = db.query(models.User).filter(models.User.id == payment_row.user_id).first()
        subscription = get_or_create_user_subscription(db, payment_row.user_id)
        if user and subscription:
            _send_subscription_change_email_safe(
                user=user,
                event_type="payment_failed",
                subscription=subscription,
                payment_status="failed",
                payment_amount_paise=int(payment_entity.get("amount", 0) or 0),
                payment_currency=_normalize_currency(payment_entity.get("currency", "")),
            )
    return {"status": "ok"}


@router.post("/webhook/razorpay")
async def razorpay_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    _enforce_rate_limit_or_429(
        request=request,
        scope="subscription.razorpay_webhook",
        limit=WEBHOOK_RATE_LIMIT,
        window_seconds=WEBHOOK_RATE_WINDOW_SECONDS,
    )

    if not RAZORPAY_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="Webhook verification is not configured.")

    body = await request.body()
    provided_signature = (request.headers.get("X-Razorpay-Signature") or "").strip()
    if not provided_signature:
        raise HTTPException(status_code=400, detail="Missing webhook signature.")

    expected_signature = hmac.new(
        RAZORPAY_WEBHOOK_SECRET.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected_signature, provided_signature):
        raise HTTPException(status_code=400, detail="Invalid webhook signature.")

    try:
        event_payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid webhook payload.")

    event_name = str(event_payload.get("event") or "").strip()
    if event_name == "payment.failed":
        return _handle_payment_failed_webhook(db=db, event_payload=event_payload)

    if event_name in {"subscription.cancelled", "subscription.completed", "subscription.halted", "subscription.paused"}:
        return _handle_subscription_lifecycle_webhook(db=db, event_payload=event_payload)

    if event_name != "payment.captured":
        return {"status": "ignored", "event": event_name}

    payment_entity = ((event_payload.get("payload") or {}).get("payment") or {}).get("entity") or {}
    subscription_id = str(payment_entity.get("subscription_id") or "").strip()
    if _looks_like_razorpay_id(subscription_id, "sub"):
        return _handle_recurring_payment_webhook(db=db, payment_entity=payment_entity)

    order_id = str(payment_entity.get("order_id") or "").strip()
    payment_id = str(payment_entity.get("id") or "").strip()
    if not _looks_like_razorpay_id(order_id, "order") or not _looks_like_razorpay_id(payment_id, "pay"):
        return {"status": "ignored", "reason": "invalid_ids"}

    payment_row = db.query(models.SubscriptionPayment).filter(
        models.SubscriptionPayment.provider == "razorpay",
        models.SubscriptionPayment.razorpay_order_id == order_id,
    ).first()
    if not payment_row:
        return {"status": "ignored", "reason": "order_not_found"}

    if payment_row.status == "verified":
        return {"status": "ok", "idempotent": True}

    user = db.query(models.User).filter(models.User.id == payment_row.user_id).first()
    if not user:
        return {"status": "ignored", "reason": "user_not_found"}
    before_subscription = get_or_create_user_subscription(db, user.id, commit=False)
    before_snapshot = _subscription_change_snapshot(before_subscription)

    payload = schemas.RazorpayPaymentVerifyRequest(
        razorpay_order_id=order_id,
        razorpay_payment_id=payment_id,
        razorpay_signature=provided_signature,
    )
    try:
        _validate_razorpay_order_payment(
            current_user=user,
            payment_row=payment_row,
            payload=payload,
            verify_checkout_signature=False,
        )
        updated_subscription = _finalize_verified_payment(
            db=db,
            user_id=user.id,
            payment_row=payment_row,
            payment_id=payment_id,
            subscription_id=None,
            invoice_id=None,
            provider_subscription_data=None,
        )
        after_snapshot = _subscription_change_snapshot(updated_subscription)
        if before_snapshot != after_snapshot:
            event_type = "pro_activated" if before_snapshot["plan"] != PLAN_PRO else "subscription_renewed"
            _send_subscription_change_email_safe(
                user=user,
                event_type=event_type,
                subscription=updated_subscription,
                auto_renew_enabled=False,
                next_renewal_at=_normalize_datetime(updated_subscription.ends_at),
                payment_status=str(payment_entity.get("status") or "verified"),
                payment_amount_paise=int(payment_entity.get("amount", 0) or 0),
                payment_currency=_normalize_currency(payment_entity.get("currency", "")),
            )
    except HTTPException:
        _mark_payment_failed(db, payment_row, "webhook_validation_failed")
        return {"status": "ignored", "reason": "validation_failed"}

    return {"status": "ok"}


@router.post("/cancel", response_model=schemas.SubscriptionResponse)
def cancel_my_subscription(
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    subscription = get_or_create_user_subscription(db, current_user.id)
    before_snapshot = _subscription_change_snapshot(subscription)

    if subscription.plan != PLAN_PRO:
        return _build_subscription_response(subscription, auto_renew_enabled=False, recurring_subscription_status=None)

    subscription_id = _find_latest_subscription_id_for_user(db, current_user.id)
    key_id, key_secret = _razorpay_credentials()

    if subscription_id and _looks_like_razorpay_id(subscription_id, "sub") and key_id and key_secret:
        subscription_data = _razorpay_request(
            method="GET",
            path=f"/subscriptions/{subscription_id}",
            key_id=key_id,
            key_secret=key_secret,
        )
        provider_status = str(subscription_data.get("status") or "").strip().lower()

        if provider_status not in {"cancelled", "completed", "expired"}:
            subscription_data = _razorpay_request(
                method="POST",
                path=f"/subscriptions/{subscription_id}/cancel",
                key_id=key_id,
                key_secret=key_secret,
                json_payload={"cancel_at_cycle_end": 1},
            )
            # Force local state to reflect scheduled cancellation even if provider omits explicit flag in response.
            subscription_data["cancel_at_cycle_end"] = True

        updated_subscription = _apply_pro_access_from_provider_period(
            db=db,
            user_id=current_user.id,
            razorpay_subscription_data=subscription_data,
            commit=True,
        )
        after_snapshot = _subscription_change_snapshot(updated_subscription)
        if before_snapshot != after_snapshot:
            _send_subscription_change_email_safe(
                user=current_user,
                event_type="auto_renew_cancelled",
                subscription=updated_subscription,
                auto_renew_enabled=_is_provider_auto_renew_enabled(subscription_data),
                next_renewal_at=_subscription_next_renewal_at(subscription_data),
            )
        return _build_subscription_response(
            updated_subscription,
            auto_renew_enabled=_is_provider_auto_renew_enabled(subscription_data),
            recurring_subscription_status=str(subscription_data.get("status") or "").strip().lower() or None,
        )

    # Legacy one-time Pro subscriptions (without recurring subscription id) downgrade immediately.
    _downgrade_to_free(subscription)
    db.commit()
    db.refresh(subscription)
    after_snapshot = _subscription_change_snapshot(subscription)
    if before_snapshot != after_snapshot:
        _send_subscription_change_email_safe(
            user=current_user,
            event_type="downgraded_to_free",
            subscription=subscription,
            auto_renew_enabled=False,
        )
    return _build_subscription_response(subscription, auto_renew_enabled=False, recurring_subscription_status=None)


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
