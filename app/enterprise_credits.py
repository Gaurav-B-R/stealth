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
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_HALF_UP
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app import models
from app import fx
from app import money


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
        "label": "Deep Scan client audit",
        "description": (
            "Rilono AI strictly audits the client's ENTIRE dossier — profile, stage records, "
            "every document's contents, notes, emails, universities, interviews and payments — "
            "and flags anything irregular. Each client's first scan is free."
        ),
        "credits": _int_env("ENTERPRISE_CREDIT_COST_DEEP_SCAN", 20),
    },
    "mock_interview": {
        "key": "mock_interview",
        "label": "AI mock visa interview",
        "description": "A full dynamic mock visa interview tailored to the client's weak points.",
        "credits": _int_env("ENTERPRISE_CREDIT_COST_MOCK_INTERVIEW", 20),
    },
    "university_match": {
        "key": "university_match",
        "label": "AI university shortlist",
        "description": "Rilono AI recommends real universities matched to the client's destination, budget, grades and intake.",
        "credits": _int_env("ENTERPRISE_CREDIT_COST_UNIVERSITY_MATCH", 5),
    },
    "course_finder": {
        "key": "course_finder",
        "label": "Course Finder AI shortlist",
        "description": (
            "Rilono AI builds a personalized course shortlist from Rilono's verified "
            "universities & courses database — fees, intakes, deadlines and score "
            "requirements — tailored to the selected client. Browsing the catalog is free."
        ),
        "credits": _int_env("ENTERPRISE_CREDIT_COST_COURSE_FINDER", 5),
    },
    "writing_studio": {
        "key": "writing_studio",
        "label": "SOP / LOR draft",
        "description": (
            "Rilono AI writes a personalized, submission-ready Statement of Purpose or "
            "Letter of Recommendation for the selected client — grounded in their real "
            "dossier and exported as a formatted Word document. Refinements cost the same."
        ),
        "credits": _int_env("ENTERPRISE_CREDIT_COST_WRITING_STUDIO", 1),
    },
    "ai_copilot": {
        "key": "ai_copilot",
        "label": "Rilono AI assistant",
        "description": (
            f"Ask anything about your workspace — clients, documents, calendar, team, "
            f"credits, your books and Rilono's university catalog. First "
            f"{_int_env('ENTERPRISE_COPILOT_FREE_DAILY', 5)} messages/day are free, then "
            f"{_int_env('ENTERPRISE_CREDIT_COST_COPILOT_BUNDLE', 1)} credit per "
            f"{_int_env('ENTERPRISE_COPILOT_MSGS_PER_CREDIT', 5)} messages. A question that "
            f"needs several lookups counts as more than one message."
        ),
        # Cost is per BUNDLE of COPILOT_MSGS_PER_CREDIT messages (not per message).
        "credits": _int_env("ENTERPRISE_CREDIT_COST_COPILOT_BUNDLE", 1),
    },
    "copilot_client": {
        "key": "copilot_client",
        "label": "Client copilot access",
        "description": (
            f"Give a client their own secure Copilot chat about their application via an "
            f"emailed link (verified by a one-time code). Flat price per client, charged "
            f"once when the client first opens it — valid "
            f"{_int_env('ENTERPRISE_COPILOT_INVITE_EXPIRES_DAYS', 30)} days, up to "
            f"{_int_env('ENTERPRISE_COPILOT_INVITE_MESSAGES', 100)} messages."
        ),
        # Flat per-client unlock (NOT the per-message staff meter above).
        "credits": _int_env("ENTERPRISE_CREDIT_COST_COPILOT_CLIENT", 20),
    },
}

# Rilono AI assistant (copilot) metering. The copilot is a function-calling agent
# (the most expensive call type), so it must be metered — but gently: a free daily
# allowance per org, then 1 credit per bundle of messages.
COPILOT_ACTION_KEY = "ai_copilot"
COPILOT_FREE_DAILY = _int_env("ENTERPRISE_COPILOT_FREE_DAILY", 5)          # free messages / org / day
COPILOT_MSGS_PER_CREDIT = max(1, _int_env("ENTERPRISE_COPILOT_MSGS_PER_CREDIT", 5))  # billable msgs per credit

# Cost-weighted metering — the guarantee that a message can never be sold below cost.
#
# The assistant is an agent: one "message" is 1..MAX_TOOL_ROUNDS model round-trips, each
# re-sending the whole history plus every tool declaration. Counting turns instead of work
# means a question that fans out over six tools is sold at the same price as "hi", and the
# margin silently depends on which model the deployment happens to be pointed at.
#
# So a turn is weighted by what it actually cost: every COPILOT_TURN_COST_BUDGET_USD of
# model spend counts as one message against the free allowance and the billing bundle.
# Normal one- and two-lookup questions stay a single message; only genuinely heavy turns
# (or an expensive model) cost more. At 1 credit / 5 messages a message earns ₹2 ≈ $0.021,
# so a $0.007 budget floors the gross margin at ~3x by construction, whatever the model.
COPILOT_TURN_COST_BUDGET_USD = Decimal(
    os.getenv("ENTERPRISE_COPILOT_TURN_COST_BUDGET_USD", "0.007") or "0.007"
)
# A runaway turn must not empty a wallet in one message.
COPILOT_MAX_MSG_WEIGHT = max(1, _int_env("ENTERPRISE_COPILOT_MAX_MSG_WEIGHT", 8))


def copilot_message_weight(turn_cost_usd) -> int:
    """How many metered "messages" one assistant turn counts as, from its real model cost.

    Always at least 1 (so a cached/zero-cost turn still consumes an allowance slot) and
    never more than COPILOT_MAX_MSG_WEIGHT. Returns 1 when cost is unknown — the meter
    must never punish a turn whose usage we failed to read.
    """
    if COPILOT_TURN_COST_BUDGET_USD <= 0:
        return 1
    try:
        cost = Decimal(str(turn_cost_usd or 0))
    except (InvalidOperation, TypeError, ValueError):
        return 1
    if cost <= 0:
        return 1
    weight = int((cost / COPILOT_TURN_COST_BUDGET_USD).to_integral_value(rounding=ROUND_CEILING))
    return max(1, min(COPILOT_MAX_MSG_WEIGHT, weight))

# Free staff-run mock-interview "previews" per org. The self-serve link a student
# takes is the real, billed product; staff can run a few in-browser test interviews
# free (to try the software or interview a student sitting with them), then it costs
# the normal mock_interview price. Self-serve/public interviews always charge.
INTERVIEW_FREE_STAFF_PREVIEWS = _int_env("ENTERPRISE_INTERVIEW_FREE_STAFF_PREVIEWS", 3)

# Each CLIENT's first N Deep Scans are free (per client, not per org) so staff see the
# full audit's value on every new dossier before the 20-credit price kicks in. Counted
# from stored scan rows — a failed scan stores nothing, so it never burns the freebie.
DEEP_SCAN_FREE_SCANS_PER_CLIENT = _int_env("ENTERPRISE_DEEP_SCAN_FREE_SCANS_PER_CLIENT", 1)
# Anti-farming cap: scan rows die with their client (cascade), so create→scan→delete
# churn could otherwise mint unlimited free Gemini audits. The org's TOTAL free scans
# are therefore also capped per calendar month (generous for honest client intake —
# beyond it, a new client's first scan simply costs the normal price).
DEEP_SCAN_FREE_MONTHLY_ORG_CAP = _int_env("ENTERPRISE_DEEP_SCAN_FREE_MONTHLY_ORG_CAP", 25)


def _month_str() -> str:
    return datetime.utcnow().strftime("%Y-%m")


def deep_scan_free_budget_left(db: Session, organization_id: int) -> int:
    """How many free Deep Scans this org has left in the current month's budget."""
    wallet = get_or_create_wallet(db, organization_id, commit=False)
    used = int(getattr(wallet, "deep_scan_free_used", 0) or 0) \
        if getattr(wallet, "deep_scan_free_month", None) == _month_str() else 0
    return max(0, DEEP_SCAN_FREE_MONTHLY_ORG_CAP - used)


def consume_deep_scan_free(db: Session, organization_id: int) -> None:
    """Record one free Deep Scan against the org's monthly budget (call only after a
    successful free scan, inside the caller's transaction — no commit here)."""
    wallet = get_wallet_for_update(db, organization_id)
    month = _month_str()
    if getattr(wallet, "deep_scan_free_month", None) != month:
        wallet.deep_scan_free_month = month
        wallet.deep_scan_free_used = 0
    wallet.deep_scan_free_used = int(wallet.deep_scan_free_used or 0) + 1

# Maps a billed action to the Gemini cost-tracker `source` values it consumes, so
# the admin report can compute real per-action margin from app.ai_usage.
ACTION_SOURCE_MAP = {
    "deep_scan": ["deep_scan", "deep_scan_extract"],
    "mock_interview": ["mock_interview", "interview_feedback"],
    "ai_copilot": ["enterprise_copilot", "enterprise_copilot_extension"],
    "copilot_client": ["enterprise_copilot_client"],
    "university_match": ["enterprise_university_shortlist"],
    "course_finder": ["enterprise_course_finder"],
    "writing_studio": ["enterprise_writing_studio"],
}

# Every Gemini source the enterprise platform incurs cost on (billed or not).
# course_catalog_refresh is the Course Finder's shared catalog-build cost (the daily
# grounded agent): it belongs in the top-line margin but NOT in ACTION_SOURCE_MAP,
# whose per-action economics track marginal cost only.
ENTERPRISE_COST_SOURCES = [
    "deep_scan", "deep_scan_extract", "document_ai", "mock_interview", "interview_feedback",
    "enterprise_copilot", "enterprise_copilot_extension", "enterprise_copilot_client",
    "enterprise_university_shortlist",
    "enterprise_course_finder", "course_catalog_refresh",
    "enterprise_writing_studio",
]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def credits_to_paise(credits: int) -> int:
    return int(credits) * PAISE_PER_CREDIT


def paise_to_rupees(paise) -> float:
    return round(float(paise or 0) / 100.0, 2)


def format_inr(paise) -> str:
    """INR-only formatter (credits are an INR-denominated unit of account). For a
    customer's actual charge use money.format_money(minor, currency)."""
    return money.format_money(paise, "INR")


def usd_to_inr_paise(usd) -> int:
    """Convert a USD amount (Decimal/float) to INR paise at the live USD→INR rate
    (falls back to the static USD_TO_INR env value when the live rate is unavailable)."""
    try:
        rupees = Decimal(str(usd or 0)) * Decimal(str(fx.get_usd_to_inr()))
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


def get_wallet_for_update(db: Session, organization_id: int) -> models.EnterpriseCreditWallet:
    """Row-locked wallet fetch for read-modify-write paths (debits, copilot
    counters). Concurrent requests — e.g. the dashboard copilot and the Chrome
    extension hitting the same org wallet at once — would otherwise lose
    updates (both read balance N, both write N-1). FOR UPDATE serializes them
    on PostgreSQL; on SQLite it is a harmless no-op."""
    get_or_create_wallet(db, organization_id, commit=False)  # ensure the row exists
    locked = (
        db.query(models.EnterpriseCreditWallet)
        .filter(models.EnterpriseCreditWallet.organization_id == int(organization_id))
        .with_for_update()
        .first()
    )
    return locked or get_or_create_wallet(db, organization_id, commit=False)


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
    wallet = get_wallet_for_update(db, organization_id)
    if ENFORCE and int(wallet.balance_credits) < cost:
        enforce_action_or_402(db, organization_id, action_key)
    action = get_action(action_key)
    balance_before = int(wallet.balance_credits)
    wallet.balance_credits = balance_before - cost
    wallet.lifetime_spent_credits = int(wallet.lifetime_spent_credits) + cost
    txn = _record_transaction(
        db, wallet=wallet, txn_type="debit", credits=-cost, action_key=action_key,
        description=(description or (action["label"] if action else action_key)),
        reference_type=reference_type, reference_id=reference_id, user=user,
    )
    if commit:
        db.commit()
        db.refresh(txn)
    # One-time in-portal heads-up to org admins when this debit crosses the low-credit line.
    try:
        from app import enterprise_notifications
        enterprise_notifications.maybe_notify_credits_low(
            db, organization_id, balance_before, int(wallet.balance_credits))
        if commit:
            db.commit()
    except Exception:
        pass
    return txn


# ---------------------------------------------------------------------------
# Rilono AI assistant (copilot) metering
#
# The copilot chat is a Gemini function-calling agent — the most expensive call
# type in the app — so leaving it unmetered was a real margin leak. It is metered
# gently: every org gets COPILOT_FREE_DAILY free messages per day, then messages
# accrue toward a bundle and 1 credit is debited every COPILOT_MSGS_PER_CREDIT
# billable messages (≈ ₹2/message at the default 1 credit / 5 messages).
#
# Flow (mirrors deep_scan: enforce before the model call, charge after success):
#   1. copilot_precheck_or_402()  — read-only; blocks a paid message when the wallet
#      can't cover the next bundle (raised BEFORE any Gemini tokens are spent).
#   2. run the model.
#   3. record_copilot_message()   — increments counters and debits on bundle rollover.
# ---------------------------------------------------------------------------

def _today_str() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")


def _copilot_used_today(wallet: models.EnterpriseCreditWallet) -> int:
    """Messages already sent today (0 if the stored daily window is stale)."""
    if wallet.copilot_usage_date == _today_str():
        return int(wallet.copilot_msgs_today or 0)
    return 0


def copilot_message_is_free(db: Session, organization_id: int) -> bool:
    """Whether the NEXT copilot message falls within today's free allowance."""
    wallet = get_or_create_wallet(db, organization_id, commit=False)
    return _copilot_used_today(wallet) < COPILOT_FREE_DAILY


def copilot_precheck_or_402(db: Session, organization_id: int) -> None:
    """Pre-check before running a copilot message. Free within the daily allowance;
    beyond it, requires enough credits to cover the next bundle. Raises 402 otherwise
    (before any Gemini tokens are spent). No-op when enforcement is disabled."""
    if not ENFORCE:
        return
    wallet = get_or_create_wallet(db, organization_id, commit=False)
    if _copilot_used_today(wallet) < COPILOT_FREE_DAILY:
        return  # still within the free daily allowance
    cost = action_cost(COPILOT_ACTION_KEY)
    if cost <= 0 or int(wallet.balance_credits) >= cost:
        return
    raise HTTPException(
        status_code=402,
        detail=(
            f"You've used today's {COPILOT_FREE_DAILY} free Rilono AI assistant messages. "
            f"Further messages cost {cost} credit per {COPILOT_MSGS_PER_CREDIT}, and your wallet "
            f"is empty. Top up your Rilono Credits to keep chatting."
        ),
    )


def record_copilot_message(
    db: Session,
    organization_id: int,
    *,
    user: Optional[models.User] = None,
    turn_cost_usd=None,
    commit: bool = True,
) -> dict:
    """Record one copilot turn: advance the daily counter, and (once past the free
    allowance) accrue toward a bundle, debiting 1 credit each time a bundle completes.
    Call AFTER the model answered successfully. Returns a compact meter for the UI.

    `turn_cost_usd` is the turn's REAL model cost summed over every round-trip
    (enterprise_ai.TurnUsage.cost_usd). It converts the turn into a message weight so a
    heavy multi-tool answer is metered as the several messages' worth of work it is.
    Omitting it meters the turn as exactly one message — the pre-cost-weighting behavior.
    """
    wallet = get_wallet_for_update(db, organization_id)

    # Roll the daily window if the date changed.
    today = _today_str()
    if wallet.copilot_usage_date != today:
        wallet.copilot_usage_date = today
        wallet.copilot_msgs_today = 0

    weight = copilot_message_weight(turn_cost_usd) if turn_cost_usd is not None else 1

    # The free allowance is consumed one slot at a time so a heavy turn can straddle the
    # boundary: the slots inside today's allowance stay free and only the overflow bills.
    used_before = int(wallet.copilot_msgs_today or 0)
    wallet.copilot_msgs_today = used_before + weight
    free_slots = max(0, min(weight, COPILOT_FREE_DAILY - used_before))
    billable = weight - free_slots
    is_free = billable == 0

    charged = 0
    txn = None
    balance_before = int(wallet.balance_credits)
    if billable:
        # Billable slots accrue toward the next credit debit; a single heavy turn can
        # complete more than one bundle, so this drains in a loop rather than once.
        wallet.copilot_unbilled_msgs = int(wallet.copilot_unbilled_msgs or 0) + billable
        bundles = int(wallet.copilot_unbilled_msgs) // COPILOT_MSGS_PER_CREDIT
        if bundles:
            wallet.copilot_unbilled_msgs = int(wallet.copilot_unbilled_msgs) - bundles * COPILOT_MSGS_PER_CREDIT
            cost = (action_cost(COPILOT_ACTION_KEY) or 1) * bundles
            debit = min(cost, int(wallet.balance_credits))  # never overdraw below zero
            if debit > 0:
                wallet.balance_credits = int(wallet.balance_credits) - debit
                wallet.lifetime_spent_credits = int(wallet.lifetime_spent_credits) + debit
                charged = debit
                messages = bundles * COPILOT_MSGS_PER_CREDIT
                txn = _record_transaction(
                    db, wallet=wallet, txn_type="debit", credits=-debit, action_key=COPILOT_ACTION_KEY,
                    description=f"Rilono AI assistant — {messages} messages", user=user,
                )

    if commit:
        db.commit()
        if txn is not None:
            db.refresh(txn)

    # Same one-time low-credit heads-up charge_action gives: an org whose
    # balance drains purely through copilot bundles must not hit a hard 402
    # without ever being warned.
    if charged:
        try:
            from app import enterprise_notifications
            enterprise_notifications.maybe_notify_credits_low(
                db, organization_id, balance_before, int(wallet.balance_credits))
            if commit:
                db.commit()
        except Exception:
            pass

    used_today = int(wallet.copilot_msgs_today)
    return {
        "free": is_free,
        "credits_charged": charged,
        "free_daily": COPILOT_FREE_DAILY,
        "used_today": used_today,
        "free_remaining_today": max(0, COPILOT_FREE_DAILY - used_today),
        "msgs_per_credit": COPILOT_MSGS_PER_CREDIT,
        "balance_credits": int(wallet.balance_credits),
        # Surfaced so the UI can explain a turn that counted as more than one message
        # instead of the allowance appearing to jump for no reason.
        "message_weight": weight,
    }


# ---------------------------------------------------------------------------
# Staff-run mock-interview "previews" (a few free, then normal mock_interview price)
# ---------------------------------------------------------------------------

def staff_interview_preview_remaining(db: Session, organization_id: int) -> int:
    wallet = get_or_create_wallet(db, organization_id, commit=False)
    used = int(getattr(wallet, "interview_staff_previews_used", 0) or 0)
    return max(0, INTERVIEW_FREE_STAFF_PREVIEWS - used)


def staff_interview_next_is_free(db: Session, organization_id: int) -> bool:
    return staff_interview_preview_remaining(db, organization_id) > 0


def enforce_staff_interview_or_402(db: Session, organization_id: int) -> None:
    """Pre-check before a STAFF-run mock interview. Free while previews remain;
    otherwise it costs the normal mock_interview price (raises 402 if unaffordable)."""
    if staff_interview_next_is_free(db, organization_id):
        return
    enforce_action_or_402(db, organization_id, "mock_interview")


def consume_staff_interview(
    db: Session,
    organization_id: int,
    *,
    user: Optional[models.User] = None,
    reference_id: Optional[int] = None,
    description: Optional[str] = None,
    commit: bool = True,
) -> dict:
    """Called after a staff-run interview starts successfully. Consumes a free preview
    if any remain (no charge); otherwise debits the normal mock_interview cost."""
    wallet = get_or_create_wallet(db, organization_id, commit=False)
    used = int(getattr(wallet, "interview_staff_previews_used", 0) or 0)
    if used < INTERVIEW_FREE_STAFF_PREVIEWS:
        wallet.interview_staff_previews_used = used + 1
        if commit:
            db.commit()
        return {
            "charged": 0,
            "was_preview": True,
            "previews_remaining": max(0, INTERVIEW_FREE_STAFF_PREVIEWS - (used + 1)),
        }
    charge_action(
        db, organization_id, "mock_interview",
        user=user, reference_type="client", reference_id=reference_id,
        description=description, commit=commit,
    )
    return {"charged": action_cost("mock_interview"), "was_preview": False, "previews_remaining": 0}


# ---------------------------------------------------------------------------
# Infrastructure server fee (₹999/mo once past the free student limit)
# ---------------------------------------------------------------------------

def infra_fee_state(db: Session, organization_id: int, *, currency: str | None = None) -> dict:
    """Infra-fee status, priced in `currency` (defaults to INR).

    The fee is a real charge, so it must be quoted from the same price book the checkout
    will use — quoting ₹999 to an org that will be charged $12.99 makes the UI lie.
    """
    try:
        code = money.normalize_currency(currency or CURRENCY, strict=True)
    except money.UnsupportedCurrency:
        code = money.DEFAULT_CURRENCY
    fee_minor = money.price_minor("infra_fee", code)
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
        # Minor units of `currency` — paise for INR, cents for USD.
        "fee_paise": fee_minor,
        "fee_minor": fee_minor,
        "fee_display": money.format_money(fee_minor, code),
        "fee_period_days": INFRA_FEE_PERIOD_DAYS,
        "is_current": is_current,
        "fee_due": fee_due,
        "paid_until": wallet.infra_fee_paid_until,
        "currency": code,
        "price_options": money.price_options("infra_fee"),
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

def package_price_minor(package_key: str, currency: str) -> int:
    """The charge for a top-up package in `currency`, from the shared price book.

    PACKAGES[...]["amount_paise"] remains the INR list price (admin overrides and the
    charm-pricing rule apply to it), but a non-INR buyer is charged an owner-chosen
    price, never an FX conversion of it.
    """
    code = money.normalize_currency(currency, strict=True)
    if code == "INR":
        return int(PACKAGES[package_key]["amount_paise"])
    return money.price_minor(f"credits_{package_key}", code)


def packages_payload(currency: str | None = None) -> list[dict]:
    """Top-up packages priced in `currency` (defaults to INR).

    `amount_paise` is in the MINOR UNIT of `currency` — the legacy field name is kept so
    the deployed SPA keeps working, but it is cents for a USD quote, not paise.
    """
    try:
        code = money.normalize_currency(currency or CURRENCY, strict=True)
    except money.UnsupportedCurrency:
        code = money.DEFAULT_CURRENCY
    payload = []
    for key in PACKAGE_ORDER:
        pkg = PACKAGES[key]
        total = int(pkg["credits"]) + int(pkg["bonus_credits"])
        amount = package_price_minor(key, code)
        payload.append({
            "key": pkg["key"],
            "label": pkg["label"],
            "tagline": pkg["tagline"],
            "amount_paise": amount,
            "amount_minor": amount,
            "amount_display": money.format_money(amount, code),
            "credits": pkg["credits"],
            "bonus_credits": pkg["bonus_credits"],
            "total_credits": total,
            # Credits stay an INR-denominated unit of account (1 credit = ₹10) regardless
            # of the currency they were bought in — a Deep Scan costs 20 credits either way.
            "value_inr": paise_to_rupees(credits_to_paise(total)),
            "is_popular": pkg["is_popular"],
            "currency": code,
            "price_options": money.price_options(f"credits_{key}"),
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


def wallet_state(db: Session, organization_id: int, *, currency: str | None = None) -> dict:
    """Wallet + catalogue, with all real CHARGES priced in `currency`.

    Credits themselves stay an INR-denominated unit of account (1 credit = ₹10) whatever
    currency they were bought in — a Deep Scan costs 20 credits everywhere — so the
    *_inr fields keep their INR meaning. Only the things an org actually pays for
    (packages, infra fee) are re-priced.
    """
    try:
        code = money.normalize_currency(currency or CURRENCY, strict=True)
    except money.UnsupportedCurrency:
        code = money.DEFAULT_CURRENCY
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
        # The org's CHARGE currency (what a top-up costs them). The *_inr fields above
        # are the credit unit of account and stay INR regardless.
        "currency": code,
        "enforced": ENFORCE,
        "low_balance": balance < (action_cost("mock_interview") or 1),
        "actions": actions_payload(),
        "infra_fee": infra_fee_state(db, organization_id, currency=code),
        "staff_interview_previews": {
            "free": INTERVIEW_FREE_STAFF_PREVIEWS,
            "remaining": staff_interview_preview_remaining(db, organization_id),
        },
        # What an agency gets without spending a credit. Surfaced on the pricing
        # tab so the free tier is visible next to the prices, not buried in the
        # per-action descriptions.
        "free_tier": {
            "deep_scans_per_client": DEEP_SCAN_FREE_SCANS_PER_CLIENT,
            "deep_scans_monthly_cap": DEEP_SCAN_FREE_MONTHLY_ORG_CAP,
            "interview_previews": INTERVIEW_FREE_STAFF_PREVIEWS,
            "interview_previews_left": staff_interview_preview_remaining(db, organization_id),
            "copilot_msgs_daily": COPILOT_FREE_DAILY,
            "copilot_msgs_left_today": max(0, COPILOT_FREE_DAILY - _copilot_used_today(wallet)),
            "copilot_msgs_per_credit": COPILOT_MSGS_PER_CREDIT,
            "free_clients": FREE_STUDENT_LIMIT,
        },
    }


def usage_breakdown(db: Session, organization_id: int, *, member_limit: int = 12,
                    include_by_member: bool = True) -> dict:
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
    # Same reasoning as spend_analytics: who-spent-what across colleagues is not something a
    # scope-limited member should be able to read off the billing screen.
    if not include_by_member:
        by_member = []

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
# Org-facing spend analytics — "where did our credits actually go?"
#
# usage_breakdown() above is the compact all-time summary the wallet payload
# carries. This is the full report behind the Credits → Analytics tab: the same
# feature/member split but time-boxed, plus the two questions an agency owner
# actually asks — WHO were the credits spent on (per client) and WHEN (timeline)
# — followed by burn rate, runway, and the free allowances they still have.
# ---------------------------------------------------------------------------

# Selectable windows for the analytics tab. 0 = all time.
ANALYTICS_RANGES = [7, 30, 90, 365, 0]
DEFAULT_ANALYTICS_DAYS = 30

# Ledger rows read when bucketing the timeline. Every headline number comes from
# a SQL aggregate, so an org past this cap still gets correct totals — only the
# chart's oldest buckets would clip, and the response stays bounded.
ANALYTICS_TIMELINE_ROW_CAP = 20000

# Clients / members listed individually before the tail rolls into "Others".
ANALYTICS_CLIENT_LIMIT = 12
ANALYTICS_MEMBER_LIMIT = 12


def normalize_analytics_days(days) -> int:
    """Coerce a requested window to one of the supported ranges (default 30d)."""
    try:
        value = int(days)
    except (TypeError, ValueError):
        return DEFAULT_ANALYTICS_DAYS
    return value if value in ANALYTICS_RANGES else DEFAULT_ANALYTICS_DAYS


def _timeline_bucket(days: int) -> str:
    """Bucket width that keeps a chart readable: ~7-90 bars, never hundreds."""
    if 0 < days <= 90:
        return "day"
    if 0 < days <= 400:
        return "week"
    return "month"


def _bucket_key(dt: datetime, bucket: str) -> str:
    if bucket == "day":
        return dt.strftime("%Y-%m-%d")
    if bucket == "week":
        return (dt - timedelta(days=dt.weekday())).strftime("%Y-%m-%d")  # week starts Monday
    return dt.strftime("%Y-%m")


def _bucket_sequence(start: datetime, end: datetime, bucket: str) -> list[str]:
    """Every bucket key from start..end inclusive, so quiet days still draw a
    zero bar (a chart that silently skips them misreads as continuous usage)."""
    keys: list[str] = []
    if bucket == "month":
        year, month = start.year, start.month
        while (year, month) <= (end.year, end.month):
            keys.append(f"{year:04d}-{month:02d}")
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        return keys
    step = timedelta(days=7 if bucket == "week" else 1)
    cursor = datetime.strptime(_bucket_key(start, bucket), "%Y-%m-%d")
    last = _bucket_key(end, bucket)
    while True:
        key = cursor.strftime("%Y-%m-%d")
        keys.append(key)
        if key >= last or len(keys) > 800:  # guard: never build an unbounded axis
            break
        cursor += step
    return keys


def spend_analytics(
    db: Session,
    organization_id: int,
    *,
    days: int = DEFAULT_ANALYTICS_DAYS,
    client_limit: int = ANALYTICS_CLIENT_LIMIT,
    member_limit: int = ANALYTICS_MEMBER_LIMIT,
    include_by_member: bool = True,
    ctx=None,
) -> dict:
    """The full credit-spend report for one organization, over a time window.

    Every figure is scoped to `days` (0 = all time) EXCEPT the burn-rate block,
    which is deliberately a fixed 30-day rate — a runway estimate must not swing
    just because someone flipped the chart to "last 7 days".

    `include_by_member=False` drops the per-colleague breakdown. That block is a
    staff-productivity report, so it is withheld from members whose own record
    access is limited to one office or their own caseload.
    """
    T = models.EnterpriseCreditTransaction
    C = models.EnterpriseClient
    org_id = int(organization_id)
    days = normalize_analytics_days(days)
    now = datetime.utcnow()
    since = (now - timedelta(days=days)) if days > 0 else None

    def _scoped(query, *, debits_only: bool = True):
        query = query.filter(T.organization_id == org_id)
        if debits_only:
            query = query.filter(T.type == "debit")
        if since is not None:
            query = query.filter(T.created_at >= since)
        return query

    def _share(part: int, whole: int) -> float:
        return round((part / whole) * 100, 1) if whole > 0 else 0.0

    # --- Headline totals ----------------------------------------------------
    spent_credits, action_count = (
        _scoped(db.query(func.coalesce(func.sum(-T.credits), 0), func.count(T.id))).one()
    )
    spent_credits = int(spent_credits or 0)
    action_count = int(action_count or 0)

    added_credits = int(
        _scoped(db.query(func.coalesce(func.sum(T.credits), 0)), debits_only=False)
        .filter(T.credits > 0).scalar() or 0
    )
    first_activity = (
        db.query(func.min(T.created_at)).filter(T.organization_id == org_id).scalar()
    )

    # --- Where the credits went (per billable feature) ----------------------
    action_rows = _scoped(
        db.query(T.action_key, func.count(T.id), func.coalesce(func.sum(-T.credits), 0))
    ).group_by(T.action_key).all()
    raw_actions = {
        (key or ""): {"units": int(units or 0), "credits_spent": int(spent or 0)}
        for key, units, spent in action_rows
    }
    by_action = []
    for key, action in ACTIONS.items():
        stat = raw_actions.pop(key, {"units": 0, "credits_spent": 0})
        by_action.append({
            "key": key,
            "label": action["label"],
            "price_credits": int(action["credits"]),
            "units": stat["units"],
            "credits_spent": stat["credits_spent"],
            "value_display": format_inr(credits_to_paise(stat["credits_spent"])),
            "share_pct": _share(stat["credits_spent"], spent_credits),
        })
    leftover_units = sum(v["units"] for v in raw_actions.values())
    leftover_credits = sum(v["credits_spent"] for v in raw_actions.values())
    if leftover_units or leftover_credits:
        by_action.append({
            "key": "other", "label": "Other usage", "price_credits": 0,
            "units": leftover_units, "credits_spent": leftover_credits,
            "value_display": format_inr(credits_to_paise(leftover_credits)),
            "share_pct": _share(leftover_credits, spent_credits),
        })
    by_action.sort(key=lambda r: r["credits_spent"], reverse=True)

    # --- Who spent them (team member) ---------------------------------------
    member_rows = _scoped(
        db.query(
            T.created_by_user_id,
            func.max(T.created_by_name),
            func.count(T.id),
            func.coalesce(func.sum(-T.credits), 0),
            func.max(T.created_at),
        )
    ).group_by(T.created_by_user_id).all()
    by_member = []
    for uid, name, units, spent, last_at in member_rows:
        spent = int(spent or 0)
        by_member.append({
            "user_id": uid,
            "name": (name or "Unknown / system"),
            "units": int(units or 0),
            "credits_spent": spent,
            "value_display": format_inr(credits_to_paise(spent)),
            "share_pct": _share(spent, spent_credits),
            "last_used_at": last_at,
        })
    by_member.sort(key=lambda r: r["credits_spent"], reverse=True)
    member_total = len(by_member)
    if member_limit and member_total > member_limit:
        by_member = by_member[:member_limit]
    if not include_by_member:
        by_member = []
        member_total = 0

    # --- On WHOM they were spent (per client) -------------------------------
    # Per-client actions carry reference_type='client'; org-wide ones (the AI
    # assistant, a client-less Course Finder search) have no client and are
    # reported separately rather than silently dropped from the totals.
    # Restricting only the NAME lookup below is not enough: a row keyed to an out-of-scope client
    # still reports a real spend against a real client id, which is a usable oracle. The scope is
    # therefore applied to the transaction rows themselves.
    _scope_ids = None
    if ctx is not None and getattr(ctx, "scope_kind", "all") != "all":
        from app import enterprise_access as _access

        _scope_ids = [
            int(row[0])
            for row in _access.scope_client_query(
                db.query(C.id).filter(C.organization_id == org_id), ctx
            ).all()
        ] or [-1]

    def client_scope(q):
        q = _scoped(q).filter(T.reference_type == "client", T.reference_id.isnot(None))
        if _scope_ids is not None:
            q = q.filter(T.reference_id.in_(_scope_ids))
        return q
    client_rows = client_scope(
        db.query(
            T.reference_id,
            func.count(T.id),
            func.coalesce(func.sum(-T.credits), 0),
            func.max(T.created_at),
        )
    ).group_by(T.reference_id).all()

    per_client_actions: dict[int, dict[str, int]] = {}
    for cid, akey, spent in client_scope(
        db.query(T.reference_id, T.action_key, func.coalesce(func.sum(-T.credits), 0))
    ).group_by(T.reference_id, T.action_key).all():
        per_client_actions.setdefault(int(cid), {})[(akey or "other")] = int(spent or 0)

    client_names: dict[int, str] = {}
    ids = [int(r[0]) for r in client_rows]
    if ids:
        for cid, name in (
            db.query(C.id, C.full_name)
            .filter(C.organization_id == org_id, C.id.in_(ids)).all()
        ):
            client_names[int(cid)] = name

    by_client = []
    for cid, units, spent, last_at in client_rows:
        cid = int(cid)
        spent = int(spent or 0)
        breakdown = sorted(
            (
                {
                    "key": k,
                    "label": (ACTIONS.get(k, {}) or {}).get("label", "Other usage"),
                    "credits_spent": v,
                }
                for k, v in (per_client_actions.get(cid) or {}).items()
            ),
            key=lambda r: r["credits_spent"], reverse=True,
        )
        by_client.append({
            "client_id": cid,
            "name": client_names.get(cid) or "Deleted client",
            "exists": cid in client_names,
            "units": int(units or 0),
            "credits_spent": spent,
            "value_display": format_inr(credits_to_paise(spent)),
            "share_pct": _share(spent, spent_credits),
            "last_used_at": last_at,
            "actions": breakdown,
        })
    by_client.sort(key=lambda r: r["credits_spent"], reverse=True)
    clients_touched = len(by_client)
    client_attributed = sum(r["credits_spent"] for r in by_client)
    if client_limit and clients_touched > client_limit:
        tail = by_client[client_limit:]
        by_client = by_client[:client_limit]
        by_client.append({
            "client_id": None,
            "name": f"{len(tail)} other clients",
            "exists": False,
            "units": sum(r["units"] for r in tail),
            "credits_spent": sum(r["credits_spent"] for r in tail),
            "value_display": format_inr(credits_to_paise(sum(r["credits_spent"] for r in tail))),
            "share_pct": _share(sum(r["credits_spent"] for r in tail), spent_credits),
            "last_used_at": None,
            "actions": [],
            "is_rollup": True,
        })
    unattributed = max(0, spent_credits - client_attributed)

    # --- WHEN they were spent (timeline) ------------------------------------
    bucket = _timeline_bucket(days)
    rows = (
        _scoped(db.query(T.created_at, T.credits))
        .order_by(T.created_at.desc())
        .limit(ANALYTICS_TIMELINE_ROW_CAP)
        .all()
    )
    buckets: dict[str, dict[str, int]] = {}
    oldest = None
    for created_at, credit_delta in rows:
        stamp = _naive(created_at) or now
        oldest = stamp if (oldest is None or stamp < oldest) else oldest
        slot = buckets.setdefault(_bucket_key(stamp, bucket), {"credits": 0, "units": 0})
        slot["credits"] += int(-(credit_delta or 0))
        slot["units"] += 1
    span_start = since or oldest or now
    timeline = [
        {
            "key": key,
            "credits": (buckets.get(key) or {}).get("credits", 0),
            "units": (buckets.get(key) or {}).get("units", 0),
        }
        for key in _bucket_sequence(span_start, now, bucket)
    ]
    peak = max((b["credits"] for b in timeline), default=0)
    busiest = next((b for b in timeline if b["credits"] == peak and peak > 0), None)

    # --- Burn rate & runway (always a 30-day rate — see docstring) ----------
    spent_30d = int(
        db.query(func.coalesce(func.sum(-T.credits), 0))
        .filter(
            T.organization_id == org_id, T.type == "debit",
            T.created_at >= now - timedelta(days=30),
        ).scalar() or 0
    )
    wallet = get_or_create_wallet(db, org_id, commit=False)
    balance = int(wallet.balance_credits)
    daily_burn = round(spent_30d / 30.0, 2)
    days_left = int(balance / daily_burn) if daily_burn > 0 else None
    runs_out_on = (now + timedelta(days=days_left)).date().isoformat() if days_left is not None else None

    # --- Free allowances still on the table ---------------------------------
    free_scans_used = (
        int(getattr(wallet, "deep_scan_free_used", 0) or 0)
        if getattr(wallet, "deep_scan_free_month", None) == _month_str() else 0
    )
    previews_used = int(getattr(wallet, "interview_staff_previews_used", 0) or 0)
    copilot_today = _copilot_used_today(wallet)
    free_credits_value = (
        free_scans_used * action_cost("deep_scan")
        + previews_used * action_cost("mock_interview")
    )

    return {
        "range": {
            "days": days,
            "label": "All time" if days == 0 else f"Last {days} days",
            "since": (since.isoformat() if since else None),
            "until": now.isoformat(),
            "options": ANALYTICS_RANGES,
        },
        "summary": {
            "spent_credits": spent_credits,
            "spent_display": format_inr(credits_to_paise(spent_credits)),
            "added_credits": added_credits,
            "action_count": action_count,
            "avg_credits_per_action": round(spent_credits / action_count, 1) if action_count else 0,
            "clients_touched": clients_touched,
            "avg_credits_per_client": round(client_attributed / clients_touched, 1) if clients_touched else 0,
            "members_active": member_total,
            "unattributed_credits": unattributed,
            "first_activity_at": (first_activity.isoformat() if hasattr(first_activity, "isoformat") else first_activity),
            "top_action": (by_action[0] if by_action and by_action[0]["credits_spent"] > 0 else None),
            "top_member": (by_member[0] if by_member and by_member[0]["credits_spent"] > 0 else None),
            "top_client": (by_client[0] if by_client and by_client[0]["credits_spent"] > 0 else None),
        },
        "by_action": by_action,
        "by_member": by_member,
        "by_client": by_client,
        "timeline": {
            "bucket": bucket,
            "points": timeline,
            "peak_credits": peak,
            "busiest_key": (busiest or {}).get("key"),
            "truncated": len(rows) >= ANALYTICS_TIMELINE_ROW_CAP,
        },
        "burn": {
            "spent_last_30d_credits": spent_30d,
            "daily_credits": daily_burn,
            "daily_display": format_inr(int(round(PAISE_PER_CREDIT * daily_burn))),
            "monthly_credits": round(daily_burn * 30, 1),
            "balance_credits": balance,
            "days_remaining": days_left,
            "runs_out_on": runs_out_on,
            "low_balance": balance < (action_cost("mock_interview") or 1),
        },
        "allowances": {
            "deep_scan_free_per_client": DEEP_SCAN_FREE_SCANS_PER_CLIENT,
            "deep_scan_free_monthly_cap": DEEP_SCAN_FREE_MONTHLY_ORG_CAP,
            "deep_scan_free_used_this_month": free_scans_used,
            "deep_scan_free_left_this_month": max(0, DEEP_SCAN_FREE_MONTHLY_ORG_CAP - free_scans_used),
            "interview_previews_free": INTERVIEW_FREE_STAFF_PREVIEWS,
            "interview_previews_used": previews_used,
            "interview_previews_left": max(0, INTERVIEW_FREE_STAFF_PREVIEWS - previews_used),
            "copilot_free_daily": COPILOT_FREE_DAILY,
            "copilot_used_today": copilot_today,
            "copilot_left_today": max(0, COPILOT_FREE_DAILY - copilot_today),
            "copilot_msgs_per_credit": COPILOT_MSGS_PER_CREDIT,
            "free_credits_value": free_credits_value,
            "free_value_display": format_inr(credits_to_paise(free_credits_value)),
        },
    }


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


# Gemini sources the enterprise platform SHARES with the B2C student app. For these,
# only rows carrying an organization_id are enterprise spend — counting the source
# wholesale charges every student's own document extraction to the enterprise margin.
# (Measured on production: 21 of 23 document_ai events, 91% of that source's spend.)
SHARED_B2C_COST_SOURCES = frozenset({"document_ai"})


def _gemini_cost_usd_by_source(db: Session) -> dict[str, float]:
    E = models.GeminiUsageEvent
    rows = (
        db.query(E.source, E.organization_id.isnot(None),
                 func.coalesce(func.sum(E.estimated_cost_usd), 0), func.count(E.id))
        .group_by(E.source, E.organization_id.isnot(None))
        .all()
    )
    out: dict[str, dict] = {}
    for src, has_org, cost, calls in rows:
        # A shared source only counts when the row names an organization; a
        # dedicated enterprise source counts in full (its rows predate org
        # attribution being passed, so requiring it would zero the history).
        if src in SHARED_B2C_COST_SOURCES and not has_org:
            continue
        entry = out.setdefault(src, {"cost_usd": 0.0, "calls": 0})
        entry["cost_usd"] += float(cost or 0)
        entry["calls"] += int(calls or 0)
    return out


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
        # Sum the INR SETTLEMENT figure, never the charged amount: a $39 top-up stores
        # amount_paise=3900 (cents), and adding that to a ₹2,999 row's 299900 produces a
        # plausible-looking total that is neither currency. base_amount_paise is
        # Razorpay's own converted INR value. This whole report is compared against Gemini
        # cost in INR, so both sides must be INR.
        #
        # The amount_paise fallback is valid ONLY for INR rows, where charged == settled
        # (Razorpay omits base_amount on domestic payments, and every pre-migration row is
        # genuinely rupees). A non-INR row whose settlement figure has not landed yet
        # contributes 0 instead of having its cents added as paise — `unsettled` below
        # counts those so the total is never quietly wrong.
        settled_inr = case(
            (P.base_amount_paise.isnot(None), P.base_amount_paise),
            (func.upper(func.coalesce(P.currency, "INR")) == "INR", P.amount_paise),
            else_=0,
        )
        gross = _money_paise(
            db.query(func.coalesce(func.sum(settled_inr), 0))
            .filter(P.status.in_(REVENUE_PAYMENT_STATUSES), P.kind == kind).scalar()
        )
        # Refunds are recorded in the ORIGINAL currency, so they need the same treatment.
        # Scaling by the payment's own settlement rate keeps a partial refund of a USD
        # payment from being subtracted as though it were rupees. A non-INR row with no
        # rate yet is skipped on BOTH sides — its gross was excluded above, so subtracting
        # its refund here would double-count the gap.
        refunded_inr = case(
            (func.upper(func.coalesce(P.currency, "INR")) == "INR", P.refunded_amount_paise),
            (P.fx_rate_used.isnot(None), P.refunded_amount_paise * P.fx_rate_used),
            else_=0,
        )
        refunded = _money_paise(
            db.query(func.coalesce(func.sum(refunded_inr), 0))
            .filter(P.status.in_(REVENUE_PAYMENT_STATUSES), P.kind == kind).scalar()
        )
        count = int(
            db.query(func.count(P.id))
            .filter(P.status.in_(REVENUE_PAYMENT_STATUSES), P.kind == kind).scalar() or 0
        )
        return gross, refunded, count

    credit_gross_paise, credit_refunded_paise, credit_payment_count = _kind_money("credits")
    infra_gross_paise, infra_refunded_paise, infra_payment_count = _kind_money("infra_fee")
    # The `unsettled` count promised in _kind_money above: revenue-status foreign payments
    # that scored 0 because Razorpay's INR settlement figure has not landed on the row.
    # Without it the totals below are a confident rupee number that quietly omits real
    # money, which is the failure this whole settlement rule exists to prevent.
    unsettled_payments = int(
        db.query(func.count(P.id))
        .filter(
            P.status.in_(REVENUE_PAYMENT_STATUSES),
            P.base_amount_paise.is_(None),
            func.upper(func.coalesce(P.currency, "INR")) != "INR",
        )
        .scalar() or 0
    )
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

    _fx = fx.get_state()
    return {
        "currency": CURRENCY,
        "usd_to_inr": round(float(_fx.get("rate") or USD_TO_INR), 2),
        "fx_source": _fx.get("source", "fallback"),          # "live" | "fallback"
        "fx_updated_at": _fx.get("fetched_at") or None,       # epoch seconds
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
            # >0 means the revenue figures above EXCLUDE that many foreign payments whose
            # INR settlement hasn't arrived — a known understatement, not zero revenue.
            "unsettled_payments": unsettled_payments,
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
