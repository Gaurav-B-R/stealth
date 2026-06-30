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
"""
from __future__ import annotations

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
    """Coerce/validate a percent discount into 0–100 (raises 400 otherwise)."""
    try:
        value = Decimal(str(raw_value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Discount percentage is invalid.")
    if value <= Decimal("0") or value > Decimal("100"):
        raise HTTPException(status_code=400, detail="Discount must be between 0% and 100%.")
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
    """Apply a percentage discount to an amount in paise (rounded, never < 0)."""
    if percent_off <= Decimal("0"):
        return int(base_amount_paise)
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
    return {
        "id": int(coupon.id),
        "organization_id": int(coupon.organization_id),
        "code": normalize_code(coupon.code),
        "percent_off": float(percent),
        "percent_display": format_percent_off(percent) + "%",
        "is_active": bool(coupon.is_active),
        "applies_to": str(coupon.applies_to or "all").lower(),
        "max_redemptions": int(coupon.max_redemptions) if coupon.max_redemptions is not None else None,
        "redemptions_used": used,
        "note": coupon.note or None,
        "created_at": coupon.created_at.isoformat() if coupon.created_at else None,
    }
