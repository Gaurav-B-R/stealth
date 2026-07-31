"""
Enterprise refunds — admin-issued refunds for an enterprise account.

Two kinds, both recorded in the `enterprise_refunds` audit table:

  * credits — a goodwill credit grant added back to the wallet (no money moves).
  * money   — a real Razorpay refund against a specific credit/infra payment,
              optionally clawing back the matching credits.

Money refunds call the live Razorpay refund API; the call is isolated in
`_razorpay_refund` so tests can stub it (no real money in local/CI).
"""

from __future__ import annotations

import os
from typing import Optional

import requests
from fastapi import HTTPException
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app import models
from app import enterprise_credits as credits
from app import money


RAZORPAY_API_BASE = os.getenv("RAZORPAY_API_BASE", "https://api.razorpay.com/v1").rstrip("/")

# Safety cap so an admin slip can't grant an absurd goodwill amount in one click.
MAX_CREDIT_REFUND = int(os.getenv("ENTERPRISE_MAX_CREDIT_REFUND", "100000") or "100000")


def _razorpay_credentials() -> tuple[str, str]:
    return (os.getenv("RAZORPAY_KEY_ID", "").strip(), os.getenv("RAZORPAY_KEY_SECRET", "").strip())


def razorpay_enabled() -> bool:
    key_id, key_secret = _razorpay_credentials()
    return bool(key_id and key_secret)


def _razorpay_refund(payment_id: str, amount_paise: int, notes: Optional[dict] = None) -> dict:
    """Call Razorpay's refund API for `payment_id`. Isolated so it can be stubbed in tests."""
    key_id, key_secret = _razorpay_credentials()
    url = f"{RAZORPAY_API_BASE}/payments/{payment_id}/refund"
    payload: dict = {"amount": int(amount_paise), "speed": "optimum"}
    if notes:
        payload["notes"] = notes
    try:
        resp = requests.post(url, auth=(key_id, key_secret), json=payload, timeout=20)
    except requests.RequestException:
        raise HTTPException(status_code=502, detail="Failed to contact the payment gateway for the refund.")
    if resp.status_code >= 400:
        detail = "The payment gateway rejected the refund."
        try:
            err = (resp.json() or {}).get("error") or {}
            if err.get("description"):
                detail = f"Razorpay: {err['description']}"
        except Exception:
            pass
        raise HTTPException(status_code=502, detail=detail)
    try:
        data = resp.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="Invalid response from the payment gateway.")
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="Unexpected response from the payment gateway.")
    return data


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def payment_refundable_paise(payment: models.EnterpriseCreditPayment) -> int:
    """Money still refundable on a verified payment, in MINOR UNITS OF `payment.currency`.

    Paise on an INR charge, cents on a USD one — Razorpay issues a refund in the original
    payment's currency, so every amount on this path stays in that currency and is never
    converted, compared or summed against another one. (The `_paise` in the name is
    historical; it predates non-INR charges.)
    """
    if payment.status not in ("verified", "partially_refunded"):
        return 0
    return max(0, int(payment.amount_paise or 0) - int(payment.refunded_amount_paise or 0))


def proportional_credits(payment: models.EnterpriseCreditPayment, amount_paise: int) -> int:
    """Credits that correspond to refunding `amount_paise` of a credit top-up
    (suggested claw-back). Zero for infra-fee payments."""
    if (payment.kind or "") != "credits":
        return 0
    total_credits = int(payment.credits or 0) + int(payment.bonus_credits or 0)
    paid = int(payment.amount_paise or 0)
    if total_credits <= 0 or paid <= 0:
        return 0
    return int(round(total_credits * (int(amount_paise) / paid)))


def serialize_refund(refund: models.EnterpriseRefund) -> dict:
    return {
        "id": refund.id,
        "kind": refund.kind,
        "payment_id": refund.payment_id,
        "amount_paise": int(refund.amount_paise or 0),
        # A refund is recorded in the ORIGINAL payment's currency, so `amount_paise` is
        # minor units of `refund.currency` — format_inr() printed "₹60" for a $60 refund.
        "amount_display": money.format_money(refund.amount_paise, refund.currency or "INR"),
        "currency": refund.currency,
        "credits_delta": int(refund.credits_delta or 0),
        "provider": refund.provider,
        "razorpay_refund_id": refund.razorpay_refund_id,
        "status": refund.status,
        "reason": refund.reason,
        "created_by_name": refund.created_by_name,
        "created_at": refund.created_at.isoformat() if refund.created_at else None,
    }


def list_refunds(db: Session, organization_id: int, limit: int = 25) -> list[dict]:
    rows = (
        db.query(models.EnterpriseRefund)
        .filter(models.EnterpriseRefund.organization_id == int(organization_id))
        .order_by(desc(models.EnterpriseRefund.created_at), desc(models.EnterpriseRefund.id))
        .limit(limit)
        .all()
    )
    return [serialize_refund(r) for r in rows]


def total_refunded_paise(db: Session, organization_id: int) -> int:
    """Sum of money-refund amounts for an org — IN MIXED MINOR UNITS.

    A refund is always issued in the ORIGINAL payment's currency (Razorpay does not let
    you choose), so once an org has refunded a non-INR top-up this total adds cents to
    paise and is not a rupee figure. There is no settlement column on EnterpriseRefund to
    normalise against.

    Callers MUST check whether the org has any non-INR refund before presenting this as a
    number — see the `refunds_mixed_currency` guard in app/routers/admin.py, which
    suppresses the figure instead of printing a confident wrong one. Do not subtract this
    from a settled-INR revenue total unconditionally.
    """
    return int(
        db.query(func.coalesce(func.sum(models.EnterpriseRefund.amount_paise), 0))
        .filter(
            models.EnterpriseRefund.organization_id == int(organization_id),
            models.EnterpriseRefund.kind == "money",
            models.EnterpriseRefund.status != "failed",
        )
        .scalar() or 0
    )


# ---------------------------------------------------------------------------
# Issue refunds
# ---------------------------------------------------------------------------

def issue_credit_refund(
    db: Session,
    organization_id: int,
    credits_amount: int,
    reason: Optional[str],
    admin_user: models.User,
) -> models.EnterpriseRefund:
    """Add goodwill credits back to a wallet (no money moves). Records the ledger entry
    and an audit refund row."""
    n = int(credits_amount or 0)
    if n <= 0:
        raise HTTPException(status_code=400, detail="Credit refund must be greater than zero.")
    if n > MAX_CREDIT_REFUND:
        raise HTTPException(status_code=400, detail=f"Credit refund can't exceed {MAX_CREDIT_REFUND} credits.")

    _txn, applied = credits.apply_adjustment(
        db, organization_id, n,
        txn_type="refund",
        description=(reason or "Goodwill credit refund"),
        user=admin_user,
        commit=False,
    )
    refund = models.EnterpriseRefund(
        organization_id=int(organization_id),
        payment_id=None,
        kind="credits",
        amount_paise=0,
        currency=credits.CURRENCY,
        credits_delta=int(applied),
        provider=None,
        status="completed",
        reason=(reason or None),
        created_by_user_id=admin_user.id,
        created_by_name=(admin_user.full_name or admin_user.email),
    )
    db.add(refund)
    db.commit()
    db.refresh(refund)
    return refund


def issue_money_refund(
    db: Session,
    organization_id: int,
    payment: models.EnterpriseCreditPayment,
    amount_paise: int,
    clawback_credits: int,
    reason: Optional[str],
    admin_user: models.User,
) -> models.EnterpriseRefund:
    """Issue a real Razorpay refund against a payment, optionally clawing back credits.
    Calls the gateway FIRST; only on success do we update the wallet/payment and record it.

    `amount_paise` is minor units of `payment.currency`, NOT rupees — Razorpay refunds in
    the currency the payment was charged in, so the figure passes through to the gateway
    untouched and every message about it is formatted with that same currency.
    """
    if payment.organization_id != int(organization_id):
        raise HTTPException(status_code=400, detail="Payment does not belong to this account.")
    if payment.status not in ("verified", "partially_refunded"):
        raise HTTPException(status_code=400, detail="Only a verified payment can be refunded.")
    if not payment.razorpay_payment_id:
        raise HTTPException(status_code=400, detail="This payment has no Razorpay payment id to refund.")

    payment_currency = str(payment.currency or "INR").strip().upper() or "INR"
    amount_paise = int(amount_paise or 0)
    if amount_paise <= 0:
        raise HTTPException(status_code=400, detail="Refund amount must be greater than zero.")
    refundable = payment_refundable_paise(payment)
    if amount_paise > refundable:
        raise HTTPException(
            status_code=400,
            detail=(
                "Refund amount exceeds the refundable balance "
                f"({money.format_money(refundable, payment_currency)})."
            ),
        )
    if not razorpay_enabled():
        raise HTTPException(status_code=503, detail="Razorpay isn't configured, so a money refund can't be issued.")

    # Call the gateway first — if it fails we abort with nothing changed.
    rz = _razorpay_refund(
        payment.razorpay_payment_id,
        amount_paise,
        notes={"organization_id": str(organization_id), "reason": (reason or "")[:200]},
    )
    razorpay_refund_id = str(rz.get("id") or "").strip() or None
    rz_status = str(rz.get("status") or "processed").strip() or "processed"

    # Update the payment's refunded total + status.
    payment.refunded_amount_paise = int(payment.refunded_amount_paise or 0) + amount_paise
    payment.status = (
        "refunded" if payment.refunded_amount_paise >= int(payment.amount_paise or 0)
        else "partially_refunded"
    )

    # Optional credit claw-back (capped at the current balance so it never overdraws).
    applied_delta = 0
    clawback = max(0, int(clawback_credits or 0))
    if clawback > 0:
        _txn, applied_delta = credits.apply_adjustment(
            db, organization_id, -clawback,
            txn_type="refund",
            # Formatted in the payment's own currency: this string is PERSISTED on the
            # credit-ledger row, so format_inr() here permanently recorded "₹60" against a
            # $60 refund — a wrong number in the books, not just on a screen.
            description=f"Claw-back for {money.format_money(amount_paise, payment_currency)} refund",
            reference_type="payment",
            reference_id=payment.id,
            user=admin_user,
            commit=False,
        )

    refund = models.EnterpriseRefund(
        organization_id=int(organization_id),
        payment_id=payment.id,
        kind="money",
        amount_paise=amount_paise,
        # Normalised on the way in so the stored code is comparable: readers group by
        # currency to decide whether a net-paid total can be stated at all, and "usd" vs
        # "USD" would read as two currencies.
        currency=payment_currency,
        credits_delta=int(applied_delta),
        provider="razorpay",
        razorpay_payment_id=payment.razorpay_payment_id,
        razorpay_refund_id=razorpay_refund_id,
        status=rz_status,
        reason=(reason or None),
        created_by_user_id=admin_user.id,
        created_by_name=(admin_user.full_name or admin_user.email),
    )
    db.add(refund)
    db.commit()
    db.refresh(refund)
    return refund
