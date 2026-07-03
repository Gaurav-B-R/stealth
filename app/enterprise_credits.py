"""
Rilono Credits — the prepaid-wallet revenue model for Rilono Enterprise (B2B).

Consultancies get the core CRM for free (up to a student limit), then:
  1. Pay a flat monthly "Infrastructure Server Fee" once they pass the free
     student limit (covers our hosting/data costs — they never lose money on us).
  2. Prepay "Rilono Credits" (like an IRCTC / telecom top-up) and spend them on the
     premium Gemini features. We charge by the *value* of the task to the agency,
     not by the GCP compute cost — so margins are very high.

Economics (all env-overridable):
  * 1 Rilono Credit = ₹10.
  * Top-up packages (Razorpay, charm-priced): Starter ₹999 → 100 cr; Pro ₹2,999 → 350 cr
    (50 bonus); Enterprise ₹4,999 → 650 cr (150 bonus).
  * Deep Scan document audit  = 5 credits  (₹50).
  * AI mock interview         = 20 credits (₹200).

This module owns the credit math, wallet operations, the ledger, infra-fee logic,
and the admin revenue analytics that cross-references real Gemini cost (from the
app.ai_usage tracker) against credit revenue to show our true margin.

Razorpay order creation / verification lives in the enterprise router; this module
is the single source of truth for prices, costs, balances and reporting.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models


# ---------------------------------------------------------------------------
# Configuration (all overridable via environment variables)
# ---------------------------------------------------------------------------

CURRENCY = (os.getenv("ENTERPRISE_CREDIT_CURRENCY", "INR").strip().upper() or "INR")

# 1 credit is worth this many paise (₹10 = 1000 paise).
PAISE_PER_CREDIT = int(os.getenv("ENTERPRISE_PAISE_PER_CREDIT", "1000") or "1000")

# Whether running a premium AI action with an empty wallet is hard-blocked (402).
# Prepaid means never run Gemini at a loss; set false for a soft/track-only launch.
ENFORCE = os.getenv("ENTERPRISE_CREDITS_ENFORCE", "true").strip().lower() in {"1", "true", "yes", "on"}

# Core CRM is free up to this many active clients; beyond it the infra fee applies.
FREE_STUDENT_LIMIT = int(os.getenv("ENTERPRISE_FREE_STUDENT_LIMIT", "50") or "50")
INFRA_FEE_PAISE = int(os.getenv("ENTERPRISE_INFRA_FEE_PAISE", "99900") or "99900")  # ₹999 / month
INFRA_FEE_PERIOD_DAYS = int(os.getenv("ENTERPRISE_INFRA_FEE_PERIOD_DAYS", "30") or "30")

# Used only to translate the USD figures from the Gemini cost tracker into INR for
# the admin margin report. Cross-check against the actual GCP invoice & FX rate.
USD_TO_INR = float(os.getenv("USD_TO_INR", "86") or "86")


def _paise(env_key: str, default_paise: int) -> int:
    raw = os.getenv(env_key, "").strip()
    if not raw:
        return default_paise
    try:
        value = int(raw)
        return value if value >= 0 else default_paise
    except ValueError:
        return default_paise


def _int_env(env_key: str, default_value: int) -> int:
    raw = os.getenv(env_key, "").strip()
    if not raw:
        return default_value
    try:
        value = int(raw)
        return value if value >= 0 else default_value
    except ValueError:
        return default_value


def charm_paise(round_paise: int) -> int:
    """Apply charm (psychological) pricing to a round amount in paise.

    A round ₹ price ending in 00 is nudged down by ₹1 so it ends in 99 — ₹1,000 → ₹999,
    ₹3,000 → ₹2,999, ₹5,000 → ₹4,999. This is a REAL price the customer pays (the card,
    the checkout breakdown and the Razorpay order all use it, so they always agree).
    Amounts that aren't a whole multiple of ₹100, or are already charm-priced, are left
    untouched so admin overrides are respected verbatim."""
    paise = int(round_paise)
    rupees, sub = divmod(paise, 100)
    if sub == 0 and rupees >= 100 and rupees % 100 == 0:
        return (rupees - 1) * 100  # e.g. 3000 → 2999, in paise: 300000 → 299900
    return paise


# Top-up packages. `credits` is the base amount; `bonus_credits` is promotional.
PACKAGES = {
    "starter": {
        "key": "starter",
        "label": "Starter Pack",
        "tagline": "Low-friction entry to premium AI",
        "amount_paise": _paise("ENTERPRISE_CREDIT_STARTER_PAISE", charm_paise(100000)),   # ₹999
        "credits": _int_env("ENTERPRISE_CREDIT_STARTER_CREDITS", 100),
        "bonus_credits": _int_env("ENTERPRISE_CREDIT_STARTER_BONUS", 0),
        "is_popular": False,
    },
    "pro": {
        "key": "pro",
        "label": "Pro Pack",
        "tagline": "Best value — bonus credits applied",
        "amount_paise": _paise("ENTERPRISE_CREDIT_PRO_PAISE", charm_paise(300000)),       # ₹2,999
        "credits": _int_env("ENTERPRISE_CREDIT_PRO_CREDITS", 300),
        "bonus_credits": _int_env("ENTERPRISE_CREDIT_PRO_BONUS", 50),        # → 350 total
        "is_popular": True,
    },
    "enterprise": {
        "key": "enterprise",
        "label": "Enterprise Pack",
        "tagline": "For high-volume offices",
        "amount_paise": _paise("ENTERPRISE_CREDIT_ENTERPRISE_PAISE", charm_paise(500000)),  # ₹4,999
        "credits": _int_env("ENTERPRISE_CREDIT_ENTERPRISE_CREDITS", 500),
        "bonus_credits": _int_env("ENTERPRISE_CREDIT_ENTERPRISE_BONUS", 150),  # → 650 total
        "is_popular": False,
    },
}
PACKAGE_ORDER = ["starter", "pro", "enterprise"]


# Premium AI actions and what they cost the agency, in credits. We charge by value
# (protecting a large university commission), not GCP compute cost.
ACTIONS = {
    "deep_scan": {
        "key": "deep_scan",
        "label": "Deep Scan document audit",
        "description": "Rilono AI cross-references the client's documents for mismatched dates, names and missing funds.",
        "credits": _int_env("ENTERPRISE_CREDIT_COST_DEEP_SCAN", 5),
    },
    "mock_interview": {
        "key": "mock_interview",
        "label": "AI mock visa interview",
        "description": "A full dynamic mock consular interview tailored to the client's weak points.",
        "credits": _int_env("ENTERPRISE_CREDIT_COST_MOCK_INTERVIEW", 20),
    },
}

# Maps a billed action to the Gemini cost-tracker `source` values it consumes, so
# the admin report can compute real per-action margin from app.ai_usage.
ACTION_SOURCE_MAP = {
    "deep_scan": ["deep_scan"],
    "mock_interview": ["mock_interview", "interview_feedback"],
}

# Every Gemini source the enterprise platform incurs cost on (billed or not).
ENTERPRISE_COST_SOURCES = ["deep_scan", "document_ai", "mock_interview", "interview_feedback", "enterprise_copilot"]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def credits_to_paise(credits: int) -> int:
    return int(credits) * PAISE_PER_CREDIT


def paise_to_rupees(paise) -> float:
    return round(float(paise or 0) / 100.0, 2)


def format_inr(paise) -> str:
    rupees = float(paise or 0) / 100.0
    if rupees == int(rupees):
        return f"₹{int(rupees):,}"
    return f"₹{rupees:,.2f}"


def usd_to_inr_paise(usd) -> int:
    """Convert a USD amount (Decimal/float) to INR paise using USD_TO_INR."""
    try:
        rupees = Decimal(str(usd or 0)) * Decimal(str(USD_TO_INR))
    except Exception:
        return 0
    return int((rupees * Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def get_action(action_key: str | None) -> Optional[dict]:
    return ACTIONS.get(str(action_key or "").strip().lower())


def action_cost(action_key: str) -> int:
    action = get_action(action_key)
    return int(action["credits"]) if action else 0


def _naive(dt) -> Optional[datetime]:
    if dt is None:
        return None
    return dt.replace(tzinfo=None) if getattr(dt, "tzinfo", None) else dt


# ---------------------------------------------------------------------------
# Wallet operations
# ---------------------------------------------------------------------------

def get_or_create_wallet(
    db: Session,
    organization_id: int,
    *,
    commit: bool = True,
) -> models.EnterpriseCreditWallet:
    wallet = (
        db.query(models.EnterpriseCreditWallet)
        .filter(models.EnterpriseCreditWallet.organization_id == int(organization_id))
        .first()
    )
    if wallet:
        return wallet
    wallet = models.EnterpriseCreditWallet(
        organization_id=int(organization_id),
        balance_credits=0,
        lifetime_purchased_credits=0,
        lifetime_spent_credits=0,
    )
    db.add(wallet)
    if commit:
        db.commit()
        db.refresh(wallet)
    else:
        db.flush()
    return wallet


def active_client_count(db: Session, organization_id: int) -> int:
    return int(
        db.query(models.EnterpriseClient)
        .filter(models.EnterpriseClient.organization_id == int(organization_id))
        .count()
    )


def _record_transaction(
    db: Session,
    *,
    wallet: models.EnterpriseCreditWallet,
    txn_type: str,
    credits: int,
    action_key: Optional[str] = None,
    description: Optional[str] = None,
    reference_type: Optional[str] = None,
    reference_id: Optional[int] = None,
    user: Optional[models.User] = None,
) -> models.EnterpriseCreditTransaction:
    txn = models.EnterpriseCreditTransaction(
        organization_id=wallet.organization_id,
        type=txn_type,
        action_key=action_key,
        credits=int(credits),
        balance_after=int(wallet.balance_credits),
        description=(description or None),
        reference_type=reference_type,
        reference_id=reference_id,
        created_by_user_id=(getattr(user, "id", None) if user else None),
        created_by_name=((user.full_name or user.email) if user else None),
    )
    db.add(txn)
    return txn


def add_credits(
    db: Session,
    organization_id: int,
    credits: int,
    *,
    txn_type: str = "topup",
    action_key: Optional[str] = None,
    description: Optional[str] = None,
    reference_type: Optional[str] = None,
    reference_id: Optional[int] = None,
    user: Optional[models.User] = None,
    count_as_purchase: bool = True,
    commit: bool = True,
) -> models.EnterpriseCreditTransaction:
    """Add credits to a wallet (top-up / bonus / positive adjustment) + ledger row."""
    credits = int(credits)
    wallet = get_or_create_wallet(db, organization_id, commit=False)
    wallet.balance_credits = int(wallet.balance_credits) + credits
    if count_as_purchase and credits > 0:
        wallet.lifetime_purchased_credits = int(wallet.lifetime_purchased_credits) + credits
    txn = _record_transaction(
        db, wallet=wallet, txn_type=txn_type, credits=credits, action_key=action_key,
        description=description, reference_type=reference_type, reference_id=reference_id, user=user,
    )
    if commit:
        db.commit()
        db.refresh(txn)
    return txn


def apply_adjustment(
    db: Session,
    organization_id: int,
    credits_delta: int,
    *,
    txn_type: str = "adjustment",
    description: Optional[str] = None,
    reference_type: Optional[str] = None,
    reference_id: Optional[int] = None,
    user: Optional[models.User] = None,
    commit: bool = True,
) -> tuple[models.EnterpriseCreditTransaction, int]:
    """Apply a signed credit adjustment to a wallet + ledger row (used for refunds and
    refund claw-backs). A negative delta is capped so the balance never goes below zero.
    Returns (txn, applied_delta) where applied_delta is what actually moved the balance."""
    wallet = get_or_create_wallet(db, organization_id, commit=False)
    delta = int(credits_delta)
    if delta < 0:
        delta = -min(-delta, int(wallet.balance_credits))  # never overdraw below 0
    wallet.balance_credits = int(wallet.balance_credits) + delta
    txn = _record_transaction(
        db, wallet=wallet, txn_type=txn_type, credits=delta, action_key=None,
        description=description, reference_type=reference_type, reference_id=reference_id, user=user,
    )
    if commit:
        db.commit()
        db.refresh(txn)
    return txn, delta


def can_afford(db: Session, organization_id: int, action_key: str) -> bool:
    if not ENFORCE:
        return True
    cost = action_cost(action_key)
    if cost <= 0:
        return True
    wallet = get_or_create_wallet(db, organization_id, commit=False)
    return int(wallet.balance_credits) >= cost


def enforce_action_or_402(db: Session, organization_id: int, action_key: str) -> None:
    """Pre-check before running a billable AI action. Raises 402 when too poor."""
    if not ENFORCE:
        return
    cost = action_cost(action_key)
    if cost <= 0:
        return
    wallet = get_or_create_wallet(db, organization_id, commit=False)
    if int(wallet.balance_credits) >= cost:
        return
    action = get_action(action_key)
    label = action["label"] if action else "this AI action"
    raise HTTPException(
        status_code=402,
        detail=(
            f"Not enough credits for {label}. It costs {cost} credits and your balance is "
            f"{int(wallet.balance_credits)}. Top up your Rilono Credits wallet to continue."
        ),
    )


def can_afford_units(db: Session, organization_id: int, action_key: str, units: int = 1) -> bool:
    """Whether the wallet can cover `units` of a billable action (e.g. N invited interviews)."""
    if not ENFORCE:
        return True
    units = max(1, int(units))
    needed = action_cost(action_key) * units
    if needed <= 0:
        return True
    wallet = get_or_create_wallet(db, organization_id, commit=False)
    return int(wallet.balance_credits) >= needed


def enforce_units_or_402(db: Session, organization_id: int, action_key: str, units: int = 1) -> None:
    """Staff-facing pre-check before *issuing* N billable units (e.g. an interview link
    that lets a client take `units` interviews). Blocks sending a link the wallet can't
    fund, so the client never hits a dead 'contact your consultancy' wall. Raises 402
    with an explicit, staff-readable top-up message (this is never shown to clients)."""
    if not ENFORCE:
        return
    units = max(1, int(units))
    cost_each = action_cost(action_key)
    if cost_each <= 0:
        return
    needed = cost_each * units
    wallet = get_or_create_wallet(db, organization_id, commit=False)
    balance = int(wallet.balance_credits)
    if balance >= needed:
        return
    action = get_action(action_key)
    label = action["label"] if action else "this action"
    unit_word = label if units == 1 else f"{units}× {label}"
    raise HTTPException(
        status_code=402,
        detail=(
            f"Not enough Rilono Credits to send {unit_word}. That needs {needed} credits "
            f"({cost_each} each) and your wallet has {balance}. Top up your wallet, then send the link."
        ),
    )


def charge_action(
    db: Session,
    organization_id: int,
    action_key: str,
    *,
    user: Optional[models.User] = None,
    reference_type: Optional[str] = None,
    reference_id: Optional[int] = None,
    description: Optional[str] = None,
    commit: bool = True,
) -> Optional[models.EnterpriseCreditTransaction]:
    """Debit the cost of a billable action. Raises 402 if enforced and unaffordable."""
    cost = action_cost(action_key)
    if cost <= 0:
        return None
    wallet = get_or_create_wallet(db, organization_id, commit=False)
    if ENFORCE and int(wallet.balance_credits) < cost:
        enforce_action_or_402(db, organization_id, action_key)
    action = get_action(action_key)
    wallet.balance_credits = int(wallet.balance_credits) - cost
    wallet.lifetime_spent_credits = int(wallet.lifetime_spent_credits) + cost
    txn = _record_transaction(
        db, wallet=wallet, txn_type="debit", credits=-cost, action_key=action_key,
        description=(description or (action["label"] if action else action_key)),
        reference_type=reference_type, reference_id=reference_id, user=user,
    )
    if commit:
        db.commit()
        db.refresh(txn)
    return txn


# ---------------------------------------------------------------------------
# Infrastructure server fee (₹999/mo once past the free student limit)
# ---------------------------------------------------------------------------

def infra_fee_state(db: Session, organization_id: int) -> dict:
    wallet = get_or_create_wallet(db, organization_id, commit=False)
    clients_used = active_client_count(db, organization_id)
    paid_until = _naive(wallet.infra_fee_paid_until)
    is_current = bool(paid_until and paid_until >= datetime.utcnow())
    over_free_limit = clients_used >= FREE_STUDENT_LIMIT
    # The fee is "due" when they're at/over the free limit and not currently paid.
    fee_due = over_free_limit and not is_current
    return {
        "free_student_limit": FREE_STUDENT_LIMIT,
        "clients_used": clients_used,
        "clients_remaining_free": max(0, FREE_STUDENT_LIMIT - clients_used),
        "over_free_limit": over_free_limit,
        "fee_paise": INFRA_FEE_PAISE,
        "fee_display": format_inr(INFRA_FEE_PAISE),
        "fee_period_days": INFRA_FEE_PERIOD_DAYS,
        "is_current": is_current,
        "fee_due": fee_due,
        "paid_until": wallet.infra_fee_paid_until,
        "currency": CURRENCY,
    }


def enforce_infra_fee_or_402(db: Session, organization_id: int) -> None:
    """Block adding clients past the free limit until the infra fee is current."""
    state = infra_fee_state(db, organization_id)
    if not state["over_free_limit"] or state["is_current"]:
        return
    raise HTTPException(
        status_code=402,
        detail=(
            f"You've reached the free limit of {FREE_STUDENT_LIMIT} students. "
            f"Activate the {state['fee_display']}/month infrastructure server fee to keep adding clients."
        ),
    )


def mark_infra_fee_paid(
    db: Session,
    organization_id: int,
    *,
    period_days: Optional[int] = None,
    commit: bool = True,
) -> models.EnterpriseCreditWallet:
    wallet = get_or_create_wallet(db, organization_id, commit=False)
    now = datetime.utcnow()
    base = _naive(wallet.infra_fee_paid_until)
    start = base if (base and base > now) else now  # stack if paid early
    wallet.infra_fee_paid_until = start + timedelta(days=int(period_days or INFRA_FEE_PERIOD_DAYS))
    if commit:
        db.commit()
        db.refresh(wallet)
    return wallet


# ---------------------------------------------------------------------------
# Payloads for the frontend
# ---------------------------------------------------------------------------

def packages_payload() -> list[dict]:
    payload = []
    for key in PACKAGE_ORDER:
        pkg = PACKAGES[key]
        total = int(pkg["credits"]) + int(pkg["bonus_credits"])
        payload.append({
            "key": pkg["key"],
            "label": pkg["label"],
            "tagline": pkg["tagline"],
            "amount_paise": pkg["amount_paise"],
            "amount_display": format_inr(pkg["amount_paise"]),
            "credits": pkg["credits"],
            "bonus_credits": pkg["bonus_credits"],
            "total_credits": total,
            "value_inr": paise_to_rupees(credits_to_paise(total)),
            "is_popular": pkg["is_popular"],
            "currency": CURRENCY,
        })
    return payload


def actions_payload() -> list[dict]:
    payload = []
    for key, action in ACTIONS.items():
        payload.append({
            "key": action["key"],
            "label": action["label"],
            "description": action["description"],
            "credits": action["credits"],
            "price_inr": paise_to_rupees(credits_to_paise(action["credits"])),
            "price_display": format_inr(credits_to_paise(action["credits"])),
        })
    return payload


def wallet_state(db: Session, organization_id: int) -> dict:
    wallet = get_or_create_wallet(db, organization_id, commit=False)
    balance = int(wallet.balance_credits)
    return {
        "balance_credits": balance,
        "balance_value_inr": paise_to_rupees(credits_to_paise(balance)),
        "balance_display": format_inr(credits_to_paise(balance)),
        "lifetime_purchased_credits": int(wallet.lifetime_purchased_credits),
        "lifetime_spent_credits": int(wallet.lifetime_spent_credits),
        "paise_per_credit": PAISE_PER_CREDIT,
        "credit_value_inr": paise_to_rupees(PAISE_PER_CREDIT),
        "currency": CURRENCY,
        "enforced": ENFORCE,
        "low_balance": balance < (action_cost("mock_interview") or 1),
        "actions": actions_payload(),
        "infra_fee": infra_fee_state(db, organization_id),
    }


def usage_breakdown(db: Session, organization_id: int, *, member_limit: int = 12) -> dict:
    """How an org's credits have actually been spent — the in-app usage tracker.

    Aggregates the debit ledger so consultancies can see *where* credits went
    (which premium feature) and *who* on the team spent them. Used by the
    "Credit usage" section of the enterprise Credits & Billing page.
    """
    T = models.EnterpriseCreditTransaction
    org_id = int(organization_id)

    # --- By feature (billable action) --------------------------------------
    action_rows = (
        db.query(
            T.action_key,
            func.count(T.id),
            func.coalesce(func.sum(-T.credits), 0),
        )
        .filter(T.organization_id == org_id, T.type == "debit")
        .group_by(T.action_key)
        .all()
    )
    raw = {(k or ""): {"units": int(u or 0), "credits_spent": int(c or 0)} for k, u, c in action_rows}

    by_action = []
    total_spent = 0
    for key, action in ACTIONS.items():
        stat = raw.pop(key, {"units": 0, "credits_spent": 0})
        total_spent += stat["credits_spent"]
        by_action.append({
            "key": key,
            "label": action["label"],
            "price_credits": int(action["credits"]),
            "units": stat["units"],
            "credits_spent": stat["credits_spent"],
            "value_display": format_inr(credits_to_paise(stat["credits_spent"])),
        })
    # Any leftover (legacy / unknown) debit action keys roll up into "Other".
    other_units = sum(v["units"] for v in raw.values())
    other_credits = sum(v["credits_spent"] for v in raw.values())
    if other_units or other_credits:
        total_spent += other_credits
        by_action.append({
            "key": "other", "label": "Other usage", "price_credits": 0,
            "units": other_units, "credits_spent": other_credits,
            "value_display": format_inr(credits_to_paise(other_credits)),
        })

    for row in by_action:
        row["share_pct"] = round((row["credits_spent"] / total_spent) * 100, 1) if total_spent > 0 else 0.0

    # --- By team member ----------------------------------------------------
    member_rows = (
        db.query(
            T.created_by_user_id,
            func.max(T.created_by_name),
            func.count(T.id),
            func.coalesce(func.sum(-T.credits), 0),
        )
        .filter(T.organization_id == org_id, T.type == "debit")
        .group_by(T.created_by_user_id)
        .all()
    )
    by_member = []
    for uid, name, units, spent in member_rows:
        spent = int(spent or 0)
        by_member.append({
            "user_id": uid,
            "name": (name or "Unknown / system"),
            "units": int(units or 0),
            "credits_spent": spent,
            "value_display": format_inr(credits_to_paise(spent)),
            "share_pct": round((spent / total_spent) * 100, 1) if total_spent > 0 else 0.0,
        })
    by_member.sort(key=lambda r: r["credits_spent"], reverse=True)
    if member_limit and len(by_member) > member_limit:
        by_member = by_member[:member_limit]

    # --- Last 30 days spend ------------------------------------------------
    since = datetime.utcnow() - timedelta(days=30)
    spent_30d = int(
        db.query(func.coalesce(func.sum(-T.credits), 0))
        .filter(T.organization_id == org_id, T.type == "debit", T.created_at >= since)
        .scalar() or 0
    )

    return {
        "total_spent_credits": total_spent,
        "total_spent_display": format_inr(credits_to_paise(total_spent)),
        "spent_last_30d_credits": spent_30d,
        "spent_last_30d_display": format_inr(credits_to_paise(spent_30d)),
        "by_action": by_action,
        "by_member": by_member,
    }


def get_package(package_key: str | None) -> Optional[dict]:
    return PACKAGES.get(str(package_key or "").strip().lower())


# ---------------------------------------------------------------------------
# Admin revenue analytics — credit revenue vs real Gemini cost = our margin
# ---------------------------------------------------------------------------

# Payment statuses that represent money we actually collected. A refund flips a
# payment to 'refunded' / 'partially_refunded', so revenue must include these and
# then net out P.refunded_amount_paise.
REVENUE_PAYMENT_STATUSES = ("verified", "partially_refunded", "refunded")


def _money_paise(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _gemini_cost_usd_by_source(db: Session) -> dict[str, float]:
    E = models.GeminiUsageEvent
    rows = (
        db.query(E.source, func.coalesce(func.sum(E.estimated_cost_usd), 0), func.count(E.id))
        .group_by(E.source)
        .all()
    )
    return {src: {"cost_usd": float(cost or 0), "calls": int(calls or 0)} for src, cost, calls in rows}


def build_revenue_analytics(db: Session) -> dict:
    """Combine prepaid-credit revenue + infra fees with the real Gemini cost from
    the app.ai_usage tracker to show the enterprise revenue model's true margin."""
    P = models.EnterpriseCreditPayment
    T = models.EnterpriseCreditTransaction
    W = models.EnterpriseCreditWallet

    # --- Revenue (collected Razorpay payments, NET of refunds) -------------
    # A payment that was refunded has its status flipped to 'refunded' /
    # 'partially_refunded', so we count every payment that ever cleared and then
    # subtract what we refunded (P.refunded_amount_paise) to get true net revenue.
    def _kind_money(kind: str) -> tuple[int, int, int]:
        gross = _money_paise(
            db.query(func.coalesce(func.sum(P.amount_paise), 0))
            .filter(P.status.in_(REVENUE_PAYMENT_STATUSES), P.kind == kind).scalar()
        )
        refunded = _money_paise(
            db.query(func.coalesce(func.sum(P.refunded_amount_paise), 0))
            .filter(P.status.in_(REVENUE_PAYMENT_STATUSES), P.kind == kind).scalar()
        )
        count = int(
            db.query(func.count(P.id))
            .filter(P.status.in_(REVENUE_PAYMENT_STATUSES), P.kind == kind).scalar() or 0
        )
        return gross, refunded, count

    credit_gross_paise, credit_refunded_paise, credit_payment_count = _kind_money("credits")
    infra_gross_paise, infra_refunded_paise, infra_payment_count = _kind_money("infra_fee")
    credit_revenue_paise = max(0, credit_gross_paise - credit_refunded_paise)
    infra_revenue_paise = max(0, infra_gross_paise - infra_refunded_paise)
    gross_revenue_paise = credit_gross_paise + infra_gross_paise
    refunds_paise = credit_refunded_paise + infra_refunded_paise
    total_revenue_paise = credit_revenue_paise + infra_revenue_paise

    # --- Credits sold / spent / outstanding (deferred liability) -----------
    credits_sold = int(
        db.query(func.coalesce(func.sum(P.credits + P.bonus_credits), 0))
        .filter(P.status.in_(REVENUE_PAYMENT_STATUSES), P.kind == "credits").scalar() or 0
    )
    credits_spent = int(
        db.query(func.coalesce(func.sum(-T.credits), 0)).filter(T.type == "debit").scalar() or 0
    )
    credits_outstanding = int(db.query(func.coalesce(func.sum(W.balance_credits), 0)).scalar() or 0)

    # --- Real Gemini cost from the tracker (USD → INR paise) ---------------
    cost_by_source = _gemini_cost_usd_by_source(db)
    gemini_cost_usd = sum(
        cost_by_source.get(src, {}).get("cost_usd", 0.0) for src in ENTERPRISE_COST_SOURCES
    )
    gemini_cost_paise = usd_to_inr_paise(gemini_cost_usd)

    gross_margin_paise = total_revenue_paise - gemini_cost_paise
    margin_pct = round((gross_margin_paise / total_revenue_paise) * 100, 1) if total_revenue_paise > 0 else None

    # --- Per-action unit economics -----------------------------------------
    per_action = []
    for key, action in ACTIONS.items():
        units = int(
            db.query(func.count(T.id)).filter(T.type == "debit", T.action_key == key).scalar() or 0
        )
        credits_charged = int(
            db.query(func.coalesce(func.sum(-T.credits), 0))
            .filter(T.type == "debit", T.action_key == key).scalar() or 0
        )
        revenue_paise = credits_to_paise(credits_charged)
        # Real cost of the Gemini source(s) this action consumes.
        src_usd = sum(cost_by_source.get(s, {}).get("cost_usd", 0.0) for s in ACTION_SOURCE_MAP.get(key, []))
        src_calls = sum(cost_by_source.get(s, {}).get("calls", 0) for s in ACTION_SOURCE_MAP.get(key, []))
        cost_paise = usd_to_inr_paise(src_usd)
        avg_cost_paise = int(cost_paise / units) if units > 0 else (int(cost_paise / src_calls) if src_calls > 0 else 0)
        price_paise = credits_to_paise(action["credits"])
        action_margin_pct = (
            round(((price_paise - avg_cost_paise) / price_paise) * 100, 1) if price_paise > 0 else None
        )
        per_action.append({
            "key": key,
            "label": action["label"],
            "price_credits": action["credits"],
            "price_paise": price_paise,
            "price_display": format_inr(price_paise),
            "units_sold": units,
            "credits_charged": credits_charged,
            "revenue_paise": revenue_paise,
            "revenue_display": format_inr(revenue_paise),
            "real_cost_paise": cost_paise,
            "real_cost_display": format_inr(cost_paise),
            "avg_cost_per_unit_paise": avg_cost_paise,
            "avg_cost_per_unit_display": format_inr(avg_cost_paise),
            "margin_pct": action_margin_pct,
        })

    # --- Recent collected payments (incl. refunded), with net amount -------
    recent = []
    for p in (
        db.query(P).filter(P.status.in_(REVENUE_PAYMENT_STATUSES))
        .order_by(P.verified_at.desc().nullslast(), P.id.desc()).limit(10).all()
    ):
        refunded = int(p.refunded_amount_paise or 0)
        net = max(0, int(p.amount_paise or 0) - refunded)
        recent.append({
            "id": p.id,
            "organization_id": p.organization_id,
            "kind": p.kind,
            "package_key": p.package_key,
            "credits": int(p.credits) + int(p.bonus_credits),
            "amount_paise": p.amount_paise,
            "amount_display": format_inr(p.amount_paise),
            "status": p.status,
            "refunded_amount_paise": refunded,
            "refunded_display": format_inr(refunded),
            "net_amount_paise": net,
            "net_amount_display": format_inr(net),
            "verified_at": p.verified_at.isoformat() if p.verified_at else None,
        })

    return {
        "currency": CURRENCY,
        "usd_to_inr": USD_TO_INR,
        "is_estimate": True,
        "credit_value_inr": paise_to_rupees(PAISE_PER_CREDIT),
        "summary": {
            "credit_revenue_paise": credit_revenue_paise,
            "credit_revenue_display": format_inr(credit_revenue_paise),
            "credit_payment_count": credit_payment_count,
            "infra_revenue_paise": infra_revenue_paise,
            "infra_revenue_display": format_inr(infra_revenue_paise),
            "infra_payment_count": infra_payment_count,
            # Net revenue (after refunds) is the headline; gross + refunds shown for transparency.
            "gross_revenue_paise": gross_revenue_paise,
            "gross_revenue_display": format_inr(gross_revenue_paise),
            "refunds_paise": refunds_paise,
            "refunds_display": format_inr(refunds_paise),
            "total_revenue_paise": total_revenue_paise,
            "total_revenue_display": format_inr(total_revenue_paise),
            "gemini_cost_paise": gemini_cost_paise,
            "gemini_cost_display": format_inr(gemini_cost_paise),
            "gemini_cost_usd": round(gemini_cost_usd, 4),
            "gross_margin_paise": gross_margin_paise,
            "gross_margin_display": format_inr(gross_margin_paise),
            "margin_pct": margin_pct,
            "credits_sold": credits_sold,
            "credits_spent": credits_spent,
            "credits_outstanding": credits_outstanding,
            "credits_outstanding_value_paise": credits_to_paise(credits_outstanding),
            "credits_outstanding_display": format_inr(credits_to_paise(credits_outstanding)),
        },
        "per_action": per_action,
        "packages": packages_payload(),
        "recent_payments": recent,
        "pricing_note": (
            "Revenue is net of refunds (collected Razorpay payments minus refunded amounts). "
            "Gemini cost is estimated from per-token pricing (app.ai_usage) and converted at "
            "USD_TO_INR — cross-check the GCP invoice & FX."
        ),
    }
