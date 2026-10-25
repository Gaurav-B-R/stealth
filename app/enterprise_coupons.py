"""Per-account discount codes for enterprise checkout.

Admins create discount codes for a specific enterprise organization from the
Admin Console. Each code carries a percentage discount and can be scoped to
credit top-ups, plan billing, or both. The org's admins then redeem the code at
checkout, where the Razorpay order amount is reduced accordingly.

This module is the single source of truth for normalizing, validating, and
applying those codes, plus computing how many times a code has been redeemed.
Redemptions are counted live from *verified* payment rows that carry the code
(EnterpriseCreditPayment / EnterpriseSubscriptionPayment), so there is no
mutable counter to keep in sync.

Discount codes support 1–100% off, including fully covered purchases. Deployments may
set a lower maximum with ENTERPRISE_COUPON_MAX_PERCENT; saved and applied discounts
both respect that explicit limit.
"""
from __future__ import annotations

import logging
import os
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models

# Razorpay rejects orders below ₹1 (100 paise). A discount that pushes the
# payable amount under this floor can't go through online checkout.
MIN_CHECKOUT_PAISE = 100

# Where a coupon may be redeemed.
APPLIES_TO_VALUES = ("all", "credits", "billing")

logger = logging.getLogger(__name__)


def _max_percent_from_env() -> Decimal:
    raw = os.getenv("ENTERPRISE_COUPON_MAX_PERCENT", "").strip()
    default = Decimal("100")
    if not raw:
        return default
    try:
        value = Decimal(raw)
    except (InvalidOperation, ValueError):
        return default
    if not value.is_finite() or value < 1 or value > 100:
        return default
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# Admins can issue a fully covered purchase by default. An explicitly configured lower
# cap still applies at creation and checkout so a deployment's policy stays consistent.
MAX_PERCENT_OFF = _max_percent_from_env()


def max_percent_off() -> Decimal:
    """The live cap (read through a function so tests and callers see monkeypatches)."""
    return MAX_PERCENT_OFF


def normalize_code(raw_code: str | None) -> str:
    """Uppercase and strip a code down to [A-Z0-9_-] (matches B2C coupons)."""
    code = str(raw_code or "").strip().upper()
    if not code:
        return ""
    return re.sub(r"[^A-Z0-9_-]", "", code)


def format_percent_off(percent_off: Decimal | int | float) -> str:
    """Render a percent value without trailing zeros (e.g. '25', '12.5')."""
    value = Decimal(str(percent_off)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return format(value, "f").rstrip("0").rstrip(".")


def parse_percent_off(raw_value: Any) -> Decimal:
    """Coerce a percent discount into the allowed 1–100 band.

    Legacy stored values outside the range clamp (150 → 100, 0.5 → 1); invalid
    non-numeric values are a 400. New admin input uses strict validation below.

    This stored value's normal form ignores an explicitly configured lower cap so the
    console can still show the saved percentage. Use validate_percent_off_for_admin
    when saving a code and effective_percent_off when applying one."""
    try:
        value = Decimal(str(raw_value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Discount percentage is invalid.")
    if not value.is_finite():  # NaN survives quantize and would poison comparisons
        raise HTTPException(status_code=400, detail="Discount percentage is invalid.")
    return min(max(value, Decimal("1")), Decimal("100"))


def validate_percent_off_for_admin(raw_value: Any) -> Decimal:
    """Validate new admin input without silently clamping or rounding it into range."""
    try:
        value = Decimal(str(raw_value))
    except (InvalidOperation, ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Discount percentage is invalid.")
    if not value.is_finite():
        raise HTTPException(status_code=400, detail="Discount percentage is invalid.")
    cap = max_percent_off()
    if value < Decimal("1") or value > cap:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Discount codes must be between 1 and {format_percent_off(cap)}% off."
            ),
        )
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def effective_percent_off(raw_value: Any) -> Decimal:
    """The percent a code ACTUALLY takes off at checkout: its stored value, capped.

    Callers should record this (not the stored value) on the payment row, so the invoice
    says what was really discounted. A code above the cap is logged every time it is
    applied — that log line is the to-do list for deactivating it."""
    value = parse_percent_off(raw_value)
    cap = max_percent_off()
    if value > cap:
        logger.warning(
            "coupon: stored discount %s%% exceeds the %s%% cap; applying the cap",
            format_percent_off(value), format_percent_off(cap),
        )
        return cap
    return value


def parse_max_redemptions(raw_value: Any) -> Optional[int]:
    """Validate an optional total redemption cap (None / blank = unlimited)."""
    if raw_value is None:
        return None
    if str(raw_value).strip() == "":
        return None
    try:
        value = int(raw_value)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Redemption limit must be a whole number.")
    if value <= 0:
        raise HTTPException(status_code=400, detail="Redemption limit must be greater than 0.")
    return value


def normalize_applies_to(raw_value: Any) -> str:
    value = str(raw_value or "all").strip().lower()
    if value not in APPLIES_TO_VALUES:
        raise HTTPException(
            status_code=400,
            detail="Discount scope must be 'all', 'credits', or 'billing'.",
        )
    return value


def compute_discounted_amount_paise(base_amount_paise: int, percent_off: Decimal) -> int:
    """Apply a percentage discount to an amount in minor units (rounded, never < 0).

    The cap is applied HERE as well as in effective_percent_off, because this is the one
    function every discounted amount passes through (plan checkout via
    enterprise_billing.checkout_quote, credit top-ups, the coupon preview). A caller that
    hands over a raw stored percent therefore still cannot discount past the cap."""
    percent_off = Decimal(str(percent_off))
    if percent_off <= Decimal("0"):
        return int(base_amount_paise)
    cap = max_percent_off()
    if percent_off > cap:
        logger.warning(
            "coupon: discount %s%% requested above the %s%% cap; applying the cap",
            format_percent_off(percent_off), format_percent_off(cap),
        )
        percent_off = cap
    multiplier = (Decimal("100") - percent_off) / Decimal("100")
    discounted = (Decimal(int(base_amount_paise)) * multiplier).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return max(int(discounted), 0)


def find_coupon(db: Session, organization_id: int, code: str) -> Optional[models.EnterpriseCoupon]:
    """Look up a coupon for an org by normalized code (case-insensitive)."""
    normalized = normalize_code(code)
    if not normalized:
        return None
    coupon = (
        db.query(models.EnterpriseCoupon)
        .filter(
            models.EnterpriseCoupon.organization_id == organization_id,
            func.upper(models.EnterpriseCoupon.code) == normalized,
        )
        .first()
    )
    if coupon:
        return coupon
    # Fallback for any legacy rows stored with mixed case / extra symbols.
    for row in (
        db.query(models.EnterpriseCoupon)
        .filter(models.EnterpriseCoupon.organization_id == organization_id)
        .all()
    ):
        if normalize_code(row.code) == normalized:
            return row
    return None


def redemptions_used(db: Session, organization_id: int, code: str) -> int:
    """Count verified payments for an org that redeemed this code (both tables)."""
    normalized = normalize_code(code)
    if not normalized:
        return 0
    credit_count = int(
        db.query(func.count(models.EnterpriseCreditPayment.id))
        .filter(
            models.EnterpriseCreditPayment.organization_id == organization_id,
            models.EnterpriseCreditPayment.status == "verified",
            func.upper(models.EnterpriseCreditPayment.coupon_code) == normalized,
        )
        .scalar()
        or 0
    )
    billing_count = int(
        db.query(func.count(models.EnterpriseSubscriptionPayment.id))
        .filter(
            models.EnterpriseSubscriptionPayment.organization_id == organization_id,
            models.EnterpriseSubscriptionPayment.status == "verified",
            func.upper(models.EnterpriseSubscriptionPayment.coupon_code) == normalized,
        )
        .scalar()
        or 0
    )
    return credit_count + billing_count


def resolve_active_coupon_or_400(
    db: Session,
    organization_id: int,
    code: str,
    *,
    context: str,
) -> models.EnterpriseCoupon:
    """Validate a code for redemption in `context` ('credits' or 'billing').

    Raises HTTPException(400) for unknown / inactive / out-of-scope /
    exhausted codes. Returns the coupon row when it can be applied.
    """
    coupon = find_coupon(db, organization_id, code)
    if not coupon:
        raise HTTPException(status_code=400, detail="Invalid discount code for this account.")
    if not bool(coupon.is_active):
        raise HTTPException(status_code=400, detail="This discount code is no longer active.")

    applies_to = str(coupon.applies_to or "all").lower()
    if applies_to not in ("all", context):
        scope_label = "credit top-ups" if applies_to == "credits" else "plan billing"
        raise HTTPException(
            status_code=400,
            detail=f"This discount code only applies to {scope_label}.",
        )

    if coupon.max_redemptions is not None:
        used = redemptions_used(db, organization_id, coupon.code)
        if used >= int(coupon.max_redemptions):
            raise HTTPException(
                status_code=400,
                detail="This discount code has reached its redemption limit.",
            )
    return coupon


def is_free_checkout(amount_paise: int) -> bool:
    """True when an (already discounted) amount can't be charged online (< ₹1).

    A 100%-off code lands here at ₹0. Rather than blocking checkout, callers grant
    the purchase for free server-side."""
    return int(amount_paise) < MIN_CHECKOUT_PAISE


def apply_to_amount_or_400(base_amount_paise: int, percent_off: Decimal) -> int:
    """Discount an amount, rejecting results below the online-checkout floor.

    Use only where a free grant is NOT supported; checkout paths that can fulfil a
    fully-covered order for free should call compute_discounted_amount_paise +
    is_free_checkout instead."""
    amount = compute_discounted_amount_paise(base_amount_paise, percent_off)
    if amount < MIN_CHECKOUT_PAISE:
        raise HTTPException(
            status_code=400,
            detail=(
                "This discount makes the amount too low for online checkout. "
                "Use a smaller discount or contact us to apply it manually."
            ),
        )
    return amount


def serialize(db: Session, coupon: models.EnterpriseCoupon) -> dict:
    """Admin-facing representation of a coupon, including live redemption usage."""
    percent = parse_percent_off(coupon.percent_off)
    used = redemptions_used(db, int(coupon.organization_id), coupon.code)
    cap = max_percent_off()
    effective = min(percent, cap)
    return {
        "id": int(coupon.id),
        "organization_id": int(coupon.organization_id),
        "code": normalize_code(coupon.code),
        "percent_off": float(percent),
        "percent_display": format_percent_off(percent) + "%",
        # What checkout will really take off. Differs from percent_off only for a legacy
        # code saved before the cap existed; the console should flag those.
        "effective_percent_off": float(effective),
        "effective_percent_display": format_percent_off(effective) + "%",
        "above_cap": bool(percent > cap),
        "max_percent_off": float(cap),
        "is_active": bool(coupon.is_active),
        "applies_to": str(coupon.applies_to or "all").lower(),
        "max_redemptions": int(coupon.max_redemptions) if coupon.max_redemptions is not None else None,
        "redemptions_used": used,
        "note": coupon.note or None,
        "created_at": coupon.created_at.isoformat() if coupon.created_at else None,
    }
