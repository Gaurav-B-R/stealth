"""
Visa Success Pass — B2C "Anxiety Paywall" API (one-time ₹999 / 30-day pass).

Surfaces both the rilono.com web app and the Chrome extension. Endpoints:
  GET  /api/pass/status                 — entitlements (free quota / pass status)
  POST /api/pass/checkout               — create one-time Razorpay order (₹999)
  POST /api/pass/verify                 — verify signature → grant 30-day pass
  POST /api/pass/red-flag-scan          — Gemini red-flag audit (free=1 blurred, pass=full)
  POST /api/pass/ds160/autofill         — DS-160 auto-fill (free 3, pass unlimited)
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

import requests
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import models
from app import visa_pass
from app import ai_usage
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


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

@router.get("/status")
def pass_status(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    subscription = get_or_create_user_subscription(db, current_user.id)
    return {
        "entitlements": visa_pass.entitlements_state(db, subscription),
        "checkout_enabled": _razorpay_enabled(),
        "razorpay_key_id": os.getenv("RAZORPAY_KEY_ID", "").strip() or None,
    }


# ---------------------------------------------------------------------------
# Purchase (one-time ₹999 / 30-day)
# ---------------------------------------------------------------------------

@router.post("/checkout")
def pass_checkout(
    request: Request,
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

    amount = int(visa_pass.PASS_PRICE_PAISE)
    if not _razorpay_enabled():
        return {
            "action": "unavailable",
            "message": "Online payment is being enabled. Please try again shortly.",
        }

    receipt = f"reln_pass_{current_user.id}_{secrets.token_hex(5)}"[:40]
    order = _razorpay_request("POST", "/orders", {
        "amount": amount,
        "currency": visa_pass.CURRENCY,
        "receipt": receipt,
        "notes": {
            "user_id": str(current_user.id),
            "product": "visa_success_pass",
        },
    })
    order_id = str(order.get("id") or "").strip()
    if not order_id:
        raise HTTPException(status_code=502, detail="Could not create the payment order.")

    db.add(models.SubscriptionPayment(
        user_id=current_user.id,
        provider="razorpay",
        plan=PLAN_PRO,
        amount_paise=amount,
        currency=visa_pass.CURRENCY,
        razorpay_order_id=order_id,
        pricing_model=visa_pass.PASS_PRICING_MODEL,
        status="created",
    ))
    db.commit()

    return {
        "action": "checkout",
        "razorpay_key_id": os.getenv("RAZORPAY_KEY_ID", "").strip(),
        "order_id": order_id,
        "amount": amount,
        "currency": visa_pass.CURRENCY,
        "product_label": "Visa Success Pass",
        "duration_days": visa_pass.PASS_DURATION_DAYS,
        "prefill": {"name": current_user.full_name or "", "email": current_user.email or ""},
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

    payment_row = (
        db.query(models.SubscriptionPayment)
        .filter(
            models.SubscriptionPayment.razorpay_order_id == payload.razorpay_order_id.strip(),
            models.SubscriptionPayment.user_id == current_user.id,
            models.SubscriptionPayment.pricing_model == visa_pass.PASS_PRICING_MODEL,
        )
        .first()
    )
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

    already_verified = payment_row.status == "verified"
    if not already_verified:
        now = datetime.utcnow()
        payment_row.razorpay_payment_id = payload.razorpay_payment_id.strip()
        payment_row.status = "verified"
        payment_row.verified_at = now
        payment_row.signature_verified_at = now
        payment_row.error_message = None
        visa_pass.grant_pass(db, current_user.id, commit=False)
        db.commit()

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
    result = gemini_service.scan_document_red_flags(data, file.filename or "document", file.content_type or "")
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


@router.post("/ds160/autofill")
def ds160_autofill(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _rate_limit_or_429(request, "pass.ds160", int(os.getenv("VISA_PASS_DS160_RATE_LIMIT", "60")), 600, current_user.id)
    subscription = get_or_create_user_subscription(db, current_user.id)
    visa_pass.enforce_feature_or_402(db, subscription, "ds160_autofill")

    # Map the user's known profile into DS-160 fields the extension can fill.
    fields = {
        "surname": (current_user.full_name or "").split(" ")[-1] if current_user.full_name else "",
        "given_names": " ".join((current_user.full_name or "").split(" ")[:-1]) if current_user.full_name else "",
        "full_name": current_user.full_name or "",
        "email": current_user.email or "",
        "phone": current_user.phone or "",
        "country_of_residence": current_user.current_residence_country or "",
        "intended_university": current_user.university or "",
        "purpose_of_travel": "Study (F-1 student)",
        "intended_intake": current_user.preferred_intake or "",
        "intended_year": current_user.preferred_year or "",
    }
    used = visa_pass.consume_feature(db, subscription, "ds160_autofill", commit=True)

    return {
        "fields": fields,
        "autofills_used": used,
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
