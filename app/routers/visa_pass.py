"""
Visa Success Pass — B2C "Anxiety Paywall" API (one-time ₹999 / 30-day pass).

Surfaces both the rilono.com web app and the Chrome extension. Endpoints:
  GET  /api/pass/status                 — entitlements (free quota / pass status)
  POST /api/pass/checkout               — create one-time Razorpay order (₹999)
  POST /api/pass/verify                 — verify signature → grant 30-day pass
  POST /api/pass/red-flag-scan          — Gemini red-flag audit (free=1 blurred, pass=full)
  POST /api/pass/voice-interview/consume— meter an AI voice mock interview (pass: 3)

The pass itself is a 30-day Pro grant (app.subscriptions); this router owns the
metered Visa-Pass features, the paywall (HTTP 402), and the one-time purchase flow.
"""

import os
import hmac
import hashlib
import secrets
import logging
from datetime import datetime
from typing import Optional

import requests
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import models
from app import money
from app import visa_pass
from app import ai_usage
from app import referrals
from app.database import get_db
from app.auth import get_current_active_user
from app.subscriptions import get_or_create_user_subscription, PLAN_PRO
from app.utils import gemini_service
from app.utils.rate_limiter import check_ip_rate_limit, extract_client_ip

router = APIRouter(prefix="/api/pass", tags=["visa-pass"])
logger = logging.getLogger(__name__)

RAZORPAY_API_BASE = os.getenv("RAZORPAY_API_BASE", "https://api.razorpay.com/v1").rstrip("/")
SCAN_MAX_BYTES = int(os.getenv("VISA_PASS_SCAN_MAX_BYTES", str(15 * 1024 * 1024)))
SCAN_ALLOWED_EXT = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".txt"}


# ---------------------------------------------------------------------------
# Razorpay helpers (one-time order + HMAC verify)
# ---------------------------------------------------------------------------

def _razorpay_credentials() -> tuple[str, str]:
    return (os.getenv("RAZORPAY_KEY_ID", "").strip(), os.getenv("RAZORPAY_KEY_SECRET", "").strip())


def _razorpay_enabled() -> bool:
    key_id, key_secret = _razorpay_credentials()
    return bool(key_id and key_secret)


def _razorpay_request(method: str, path: str, json_payload: dict | None = None) -> dict:
    key_id, key_secret = _razorpay_credentials()
    url = f"{RAZORPAY_API_BASE}/{path.lstrip('/')}"
    try:
        resp = requests.request(method.upper(), url, auth=(key_id, key_secret), json=json_payload, timeout=15)
    except requests.RequestException:
        raise HTTPException(status_code=502, detail="Failed to contact the payment gateway.")
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail="Unable to process the payment request right now.")
    try:
        data = resp.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="Invalid response from the payment gateway.")
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="Unexpected response from the payment gateway.")
    return data


def _rate_limit_or_429(request: Request, scope: str, limit: int, window: int, user_id: int) -> None:
    allowed, retry_after = check_ip_rate_limit(
        request=request, scope=scope, limit=limit, window_seconds=window, extra_key=f"user:{user_id}",
    )
    if not allowed:
        raise HTTPException(status_code=429, detail="Too many requests. Please slow down.",
                            headers={"Retry-After": str(retry_after)})


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class PassVerifyRequest(BaseModel):
    razorpay_order_id: str = Field(..., min_length=6, max_length=64)
    razorpay_payment_id: str = Field(..., min_length=6, max_length=64)
    razorpay_signature: str = Field(..., min_length=6, max_length=256)


class PassCheckoutRequest(BaseModel):
    # Optional discount code (admin-issued per-account "conversion play" coupons or
    # global codes). Validated server-side; the client never sets the price.
    coupon_code: Optional[str] = Field(default=None, max_length=64)
    # Which currency to charge in. A HINT ONLY: the server maps it to a price from
    # app/money.py PRICE_BOOK. The client never sends an amount, and an unrecognised
    # code is rejected rather than coerced — see money.normalize_currency(strict=True).
    currency: Optional[str] = Field(default=None, max_length=3)


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

@router.get("/status")
def pass_status(
    currency: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """Entitlements + the pass price.

    `currency` quotes the price in that currency (and the response carries the full
    ladder in `entitlements.pass.price_options` so the paywall can render a selector).
    An unsupported value quietly falls back to INR rather than 400-ing, because this is
    a read-only status call — the strict check that matters happens at /checkout, where
    money is actually decided.
    """
    subscription = get_or_create_user_subscription(db, current_user.id)
    return {
        "entitlements": visa_pass.entitlements_state(db, subscription, currency=currency),
        "checkout_enabled": _razorpay_enabled(),
        "razorpay_key_id": os.getenv("RAZORPAY_KEY_ID", "").strip() or None,
        "charge_currencies": list(money.supported_charge_currencies()),
    }


# ---------------------------------------------------------------------------
# Purchase (one-time ₹999 / 30-day)
# ---------------------------------------------------------------------------

@router.post("/checkout")
def pass_checkout(
    request: Request,
    payload: Optional[PassCheckoutRequest] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _rate_limit_or_429(request, "pass.checkout", int(os.getenv("VISA_PASS_CHECKOUT_RATE_LIMIT", "8")), 600, current_user.id)
    if not current_user.email_verified:
        raise HTTPException(status_code=403, detail="Please verify your email before buying the Visa Success Pass.")

    subscription = get_or_create_user_subscription(db, current_user.id)
    if visa_pass.has_active_pass(subscription):
        return {
            "action": "already_active",
            "message": "Your Visa Success Pass is already active.",
            "entitlements": visa_pass.entitlements_state(db, subscription),
        }

    # Resolve the charge currency, then the price. The client hints at a currency; the
    # PRICE is always looked up server-side from the price book. An unsupported code is a
    # 400, never a silent fall back to INR — coercing here would charge someone in a
    # currency they did not choose.
    raw_currency = (payload.currency if payload else None) or money.DEFAULT_CURRENCY
    try:
        currency = money.normalize_currency(raw_currency, strict=True)
    except money.UnsupportedCurrency:
        raise HTTPException(
            status_code=400,
            detail=f"We can't charge in {str(raw_currency).upper()[:8]} yet. Supported: "
                   + ", ".join(money.supported_charge_currencies()) + ".",
        )
    base_price = money.price_minor("visa_pass", currency)
    amount = int(base_price)
    # Currency-aware floor — the old hardcoded 100 was "₹1", which is $1.00 in USD.
    floor = money.min_charge_minor(currency)

    # Referred-friend incentive: a one-time discount off their FIRST Visa Success
    # Pass. Computed server-side (never trusted from the client) and gated by the
    # same anti-sybil hygiene as the referrer reward.
    is_first_pass_purchase = (
        db.query(models.SubscriptionPayment)
        .filter(
            models.SubscriptionPayment.user_id == current_user.id,
            models.SubscriptionPayment.pricing_model == visa_pass.PASS_PRICING_MODEL,
            models.SubscriptionPayment.status == "verified",
        )
        .first()
        is None
    )
    # The reward is defined as a flat ₹200 off ₹999. A flat INR amount cannot be
    # subtracted from a foreign price — ₹200 off $12.99 (stored as 1299 cents) would go
    # deeply negative and clamp to the floor, giving the pass away. So convert it to the
    # equivalent PROPORTION of the INR list price and apply that, which preserves the
    # intent (~20% off) in every currency and self-adjusts if either price changes.
    referral_discount_inr = referrals.referee_discount_paise(db, current_user, is_first_pass_purchase)
    referral_discount = 0
    if referral_discount_inr > 0:
        if currency == "INR":
            referral_discount = referral_discount_inr
        else:
            inr_list = money.price_minor("visa_pass", "INR")
            ratio = min(1.0, referral_discount_inr / inr_list) if inr_list > 0 else 0.0
            referral_discount = int(round(base_price * ratio))
        amount = max(floor, amount - referral_discount)
        referral_discount = base_price - amount   # what was actually granted, post-floor

    # Optional coupon code (admin-issued per-account or global). Reuses the exact
    # validation the recurring checkout uses: existence, per-account restriction and
    # per-user usage caps all enforced server-side. Applied AFTER the referral
    # discount; validated before the Razorpay gate so a bad code errors cleanly.
    coupon_code = None
    coupon_percent_off = None
    coupon_discount = 0
    raw_coupon = (payload.coupon_code if payload else None) or ""
    if raw_coupon.strip():
        from app.routers.subscription import (
            _normalize_coupon_code,
            _get_coupon_details,
            _compute_discounted_amount_paise,
        )
        coupon_code = _normalize_coupon_code(raw_coupon)
        if not coupon_code:
            raise HTTPException(status_code=400, detail="Invalid coupon code.")
        percent_off, _max_uses = _get_coupon_details(db, coupon_code, current_user.id)
        # Percentage discounts are currency-agnostic; only the floor needs to be.
        discounted = max(floor, _compute_discounted_amount_paise(amount, percent_off))
        coupon_discount = amount - discounted
        coupon_percent_off = float(percent_off)
        amount = discounted

    if not _razorpay_enabled():
        return {
            "action": "unavailable",
            "message": "Online payment is being enabled. Please try again shortly.",
        }

    # Receipt carries the currency so provider-side reconciliation can tell a $12.99 row
    # from a ₹999 one without joining back to our DB.
    receipt = f"reln_pass_{current_user.id}_{currency.lower()}_{secrets.token_hex(4)}"[:40]
    order = _razorpay_request("POST", "/orders", {
        "amount": amount,
        "currency": currency,
        "receipt": receipt,
        # Capture automatically on authorization (mirrors the enterprise flow).
        # Without this, capture timing rides on Razorpay dashboard settings, and an
        # international card can sit authorized-but-uncaptured for hours — the
        # buyer's bank says "paid" while the pass never activates.
        "payment_capture": 1,
        "notes": {
            "user_id": str(current_user.id),
            "product": "visa_success_pass",
            "currency": currency,
            # Which price list produced this amount — without it an in-flight price
            # change makes the order unreconcilable after the fact.
            "price_book_version": money.PRICE_BOOK_VERSION,
        },
    })
    order_id = str(order.get("id") or "").strip()
    if not order_id:
        raise HTTPException(status_code=502, detail="Could not create the payment order.")
    logger.info(
        "Pass checkout order created: %s user %s (%s %s)",
        order_id,
        current_user.id,
        amount,
        currency,
    )

    db.add(models.SubscriptionPayment(
        user_id=current_user.id,
        provider="razorpay",
        plan=PLAN_PRO,
        amount_paise=amount,
        currency=currency,
        price_book_version=money.PRICE_BOOK_VERSION,
        razorpay_order_id=order_id,
        pricing_model=visa_pass.PASS_PRICING_MODEL,
        coupon_code=coupon_code or ("REFERRAL" if referral_discount > 0 else None),
        coupon_percent_off=coupon_percent_off,
        status="created",
    ))
    db.commit()

    return {
        "action": "checkout",
        "razorpay_key_id": os.getenv("RAZORPAY_KEY_ID", "").strip(),
        "order_id": order_id,
        "amount": amount,
        "original_amount": int(base_price),
        "referral_discount": int(referral_discount),
        "coupon_code": coupon_code,
        "coupon_percent_off": coupon_percent_off,
        "coupon_discount": int(coupon_discount),
        "currency": currency,
        "amount_display": money.format_money(amount, currency),
        "product_label": "Visa Success Pass",
        "duration_days": visa_pass.PASS_DURATION_DAYS,
        # Razorpay: "Your international payment will fail if you send us a dummy email id
        # and phone number of the customer." Send the real contact we hold, and send
        # nothing rather than a placeholder.
        # https://razorpay.com/docs/payments/international-payments/?preferred-country=IN
        "prefill": {
            "name": current_user.full_name or "",
            "email": current_user.email or "",
            "contact": (getattr(current_user, "phone", None) or ""),
        },
    }


@router.post("/verify")
def pass_verify(
    payload: PassVerifyRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _rate_limit_or_429(request, "pass.verify", int(os.getenv("VISA_PASS_VERIFY_RATE_LIMIT", "20")), 600, current_user.id)
    key_id, key_secret = _razorpay_credentials()
    if not key_id or not key_secret:
        raise HTTPException(status_code=503, detail="Payment verification is not configured.")

    query = db.query(models.SubscriptionPayment).filter(
        models.SubscriptionPayment.razorpay_order_id == payload.razorpay_order_id.strip(),
        models.SubscriptionPayment.user_id == current_user.id,
        models.SubscriptionPayment.pricing_model == visa_pass.PASS_PRICING_MODEL,
    )
    # Lock the row so two concurrent verifies of the SAME order serialize. Without this
    # both can pass the `already_verified` check below and each call grant_pass(), and
    # grant_pro_access_for_days() EXTENDS from the existing ends_at — so one payment
    # would buy 60 days.
    if db.bind and db.bind.dialect.name != "sqlite":
        query = query.with_for_update()
    payment_row = query.first()
    if not payment_row:
        raise HTTPException(status_code=404, detail="Payment order not found.")

    expected = hmac.new(
        key_secret.encode("utf-8"),
        f"{payload.razorpay_order_id}|{payload.razorpay_payment_id}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, payload.razorpay_signature):
        payment_row.status = "failed"
        payment_row.error_message = "Invalid payment signature."
        db.commit()
        raise HTTPException(status_code=400, detail="Invalid payment signature.")

    # The signature only proves "order_id|payment_id" came from Razorpay. It says NOTHING
    # about how much was paid, in what currency, or whether the money was actually
    # captured. Re-fetch both entities and assert against what we stored at checkout.
    # (Mirrors app/routers/subscription.py::_validate_razorpay_order_payment.)
    order_data = _razorpay_request("GET", f"/orders/{payload.razorpay_order_id.strip()}")
    payment_data = _razorpay_request("GET", f"/payments/{payload.razorpay_payment_id.strip()}")

    def _reject(detail: str) -> None:
        if bool(payment_data.get("captured")):
            # With payment_capture=1 the money has already been collected; rejecting
            # the verification strands captured funds — a manual dashboard refund is
            # likely needed. Error level so it pages, not just logs.
            logger.error(
                "Pass verify rejected a CAPTURED payment — manual refund may be needed: order %s payment %s user %s: %s",
                payment_row.razorpay_order_id,
                payload.razorpay_payment_id,
                current_user.id,
                detail,
            )
        else:
            logger.warning(
                "Pass verify rejected: order %s user %s: %s",
                payment_row.razorpay_order_id,
                current_user.id,
                detail,
            )
        payment_row.status = "failed"
        payment_row.error_message = detail
        db.commit()
        raise HTTPException(status_code=400, detail=detail)

    def _pending(detail: str) -> None:
        # Authorized-but-not-yet-captured (or order not yet flipped to paid) is a
        # PENDING state, not a verdict — capture on international cards can trail
        # authorization by hours. Marking the row failed here poisons a purchase
        # that is still completing; leave it 'created' so the payment.captured
        # webhook (or a verify retry) can still activate the pass.
        logger.info(
            "Pass verify pending: order %s user %s: %s",
            payment_row.razorpay_order_id,
            current_user.id,
            detail,
        )
        raise HTTPException(
            status_code=409,
            detail=(
                "Your payment is still being confirmed by the payment provider. "
                "The pass activates automatically once it completes — no need to pay again."
            ),
        )

    expected_currency = money.normalize_currency(payment_row.currency, strict=False)
    if str(order_data.get("id") or "") != payment_row.razorpay_order_id:
        _reject("Razorpay order mismatch.")
    # Terminal payment states are a verdict and must be caught BEFORE the pending
    # paths below, or a dead payment loops as "confirming — no need to pay again"
    # forever (payment.captured will never fire for it). A refunded payment with
    # captured=true was a real purchase later refunded — refund handling, not a
    # verification failure.
    payment_state = str(payment_data.get("status", "")).lower()
    if payment_state == "failed" or (payment_state == "refunded" and not bool(payment_data.get("captured"))):
        _reject("This payment failed or was refunded by the payment provider. Please try again.")
    if str(order_data.get("status", "")).lower() != "paid":
        _pending("order not marked paid yet")
    if int(order_data.get("amount", 0) or 0) != int(payment_row.amount_paise):
        _reject("Payment amount mismatch.")
    if money.normalize_currency(order_data.get("currency"), strict=False) != expected_currency:
        _reject("Payment currency mismatch.")
    if str(payment_data.get("order_id") or "") != payment_row.razorpay_order_id:
        _reject("Payment does not belong to this order.")
    if int(payment_data.get("amount", 0) or 0) != int(payment_row.amount_paise):
        _reject("Payment amount mismatch.")
    if money.normalize_currency(payment_data.get("currency"), strict=False) != expected_currency:
        _reject("Payment currency mismatch.")
    # An authorized-but-uncaptured payment can still yield a valid checkout signature, and
    # capture failure is materially more common on international cards. Without this the
    # pass is granted for money that never arrives. It is a pending state, not a failure:
    # capture usually follows within moments (payment_capture=1 on the order).
    if not bool(payment_data.get("captured")):
        _pending("payment authorized but not captured yet")

    already_verified = payment_row.status == "verified"
    if not already_verified:
        now = datetime.utcnow()
        payment_row.razorpay_payment_id = payload.razorpay_payment_id.strip()
        # Razorpay's own INR settlement figure — the ONLY amount that may be summed for
        # revenue once rows carry different currencies.
        base_minor, fx_rate = money.settled_inr_minor(payment_data)
        if base_minor is not None:
            payment_row.base_amount_paise = base_minor
            payment_row.fx_rate_used = fx_rate
        payment_row.base_currency = "INR"
        payment_row.is_international = bool(payment_data.get("international"))
        payment_row.status = "verified"
        payment_row.verified_at = now
        payment_row.signature_verified_at = now
        payment_row.error_message = None
        visa_pass.grant_pass(db, current_user.id, commit=False)
        # This is a real, paid conversion — reward the referrer (if any) now, not on
        # the friend's free login. Best-effort: never fail the purchase over a reward.
        try:
            referrals.award_referral_reward_on_purchase(db, current_user, commit=False)
        except Exception:
            logger.exception("Referral reward on purchase failed (user_id=%s)", current_user.id)
        db.commit()
        logger.info(
            "Pass verified: order %s payment %s user %s (%s %s)",
            payment_row.razorpay_order_id,
            payment_row.razorpay_payment_id,
            current_user.id,
            payment_row.amount_paise,
            payment_row.currency,
        )

    subscription = get_or_create_user_subscription(db, current_user.id)
    return {
        "message": "Your Visa Success Pass is now active for 30 days.",
        "entitlements": visa_pass.entitlements_state(db, subscription),
    }


# ---------------------------------------------------------------------------
# Metered features
# ---------------------------------------------------------------------------

def _blur(text: str) -> str:
    return "🔒 Unlock the Visa Success Pass to reveal this finding."


@router.post("/red-flag-scan")
async def red_flag_scan(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _rate_limit_or_429(request, "pass.red_flag", int(os.getenv("VISA_PASS_SCAN_RATE_LIMIT", "30")), 600, current_user.id)
    subscription = get_or_create_user_subscription(db, current_user.id)

    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in SCAN_ALLOWED_EXT:
        raise HTTPException(status_code=400, detail="Unsupported file. Use PDF, an image, or text.")

    # Hard paywall BEFORE spending Gemini tokens.
    ent = visa_pass.enforce_feature_or_402(db, subscription, "red_flag_scan")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="The file is empty.")
    if len(data) > SCAN_MAX_BYTES:
        raise HTTPException(status_code=400, detail=f"File too large (max {SCAN_MAX_BYTES // (1024*1024)} MB).")

    # Attribute this scan's Gemini cost to the account that ran it.
    ai_usage.set_usage_account(user_id=current_user.id)
    result = gemini_service.scan_document_red_flags(
        data,
        file.filename or "document",
        file.content_type or "",
        destination_country_code=current_user.destination_country_code,
    )
    if result is None:
        raise HTTPException(status_code=503, detail="The red-flag scan isn't available right now.")

    # Charge the free quota only on a successful scan.
    visa_pass.consume_feature(db, subscription, "red_flag_scan", commit=True)

    reveal_all = visa_pass.has_active_pass(subscription)
    flags = result.get("flags") or []
    total = len(flags)
    out_flags = []
    for i, f in enumerate(flags):
        # Free tier: reveal the first flag, blur the rest (the "anxiety" hook).
        revealed = reveal_all or i == 0
        out_flags.append({
            "title": f["title"] if revealed else "Hidden issue",
            "detail": f["detail"] if revealed else _blur(f["detail"]),
            "severity": f["severity"],
            "locked": (not revealed),
        })

    return {
        "summary": result.get("summary") or "",
        "flags": out_flags,
        "total_flags": total,
        "hidden_flags": 0 if reveal_all else max(0, total - 1),
        "reveal_all": reveal_all,
        "entitlements": visa_pass.entitlements_state(db, subscription),
    }


@router.post("/voice-interview/consume")
def consume_voice_interview(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """Meter one AI voice mock interview. Free tier is paywalled; a pass grants 3."""
    _rate_limit_or_429(request, "pass.voice", int(os.getenv("VISA_PASS_VOICE_RATE_LIMIT", "20")), 600, current_user.id)
    subscription = get_or_create_user_subscription(db, current_user.id)
    visa_pass.enforce_feature_or_402(db, subscription, "voice_interview")
    used = visa_pass.consume_feature(db, subscription, "voice_interview", commit=True)
    ent = visa_pass.feature_entitlement(subscription, "voice_interview")
    return {
        "interviews_used": used,
        "remaining": ent["remaining"],
        "entitlements": visa_pass.entitlements_state(db, subscription),
    }
