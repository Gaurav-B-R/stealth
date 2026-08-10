"""
Rilono Credits — the AI metering unit for Rilono Enterprise (B2B).

A credit is what an AI action costs an agency. Credits reach a wallet two ways:

  1. INCLUDED WITH THE PLAN. Every organization is on a tier (app/enterprise_billing.py)
     and each tier carries a monthly allowance — 1,000 / 3,500 / 10,000 credits for
     Starter / Growth / Scale, and a one-time 100 on the free sandbox. `sync_plan_credits`
     grants it exactly once per billing period.
  2. PURCHASED AS A TOP-UP for overage, via Razorpay, from PACKAGES below. A team that
     burns its monthly allowance early buys more rather than being stopped.

We charge by the *value* of the task to the agency, not by the GCP compute cost — so the
margin per action is high, and `build_revenue_analytics` is what proves it, cross-checking
real Gemini spend (from app.ai_usage) against plan + top-up revenue.

Economics (all env-overridable):
  * 1 Rilono Credit = ₹10.
  * Top-up packages (Razorpay, charm-priced): Starter ₹999 → 100 cr; Pro ₹2,999 → 350 cr
    (50 bonus); Enterprise ₹4,999 → 650 cr (150 bonus).
  * Deep Scan client audit = 20 credits; document scan = 1; mock interview = 20;
    university match / course finder = 5 each; SOP-LOR draft = 1.

This module owns the credit math, wallet operations, the ledger, the plan-allowance grant,
and the admin revenue analytics. Razorpay order creation / verification lives in the
enterprise router; PRICES live in app/money.py. This module is the single source of truth
for credit costs, balances and reporting.

HISTORY (2026-08-02): the previous model — free CRM up to 50 students, then a flat ₹999/mo
infrastructure server fee, with credits available only as prepaid top-ups — was replaced by
the tiered plans. The infra fee is retired; see INFRA_FEE_RETIRED below for what remains.
"""

from __future__ import annotations

import logging
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

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration (all overridable via environment variables)
# ---------------------------------------------------------------------------

CURRENCY = (os.getenv("ENTERPRISE_CREDIT_CURRENCY", "INR").strip().upper() or "INR")

# 1 credit is worth this many paise (₹10 = 1000 paise).
PAISE_PER_CREDIT = int(os.getenv("ENTERPRISE_PAISE_PER_CREDIT", "1000") or "1000")

# Whether running a premium AI action with an empty wallet is hard-blocked (402).
# Prepaid means never run Gemini at a loss; set false for a soft/track-only launch.
ENFORCE = os.getenv("ENTERPRISE_CREDITS_ENFORCE", "true").strip().lower() in {"1", "true", "yes", "on"}

# Were the legacy all-in prices (credit top-ups, the retired infra fee) inclusive of GST?
# True is the correct default for a GST-registered supplier quoting a single price. This only
# affects REPORTING — no customer is charged differently either way.
LEGACY_PRICES_TAX_INCLUSIVE = os.getenv(
    "ENTERPRISE_LEGACY_PRICES_TAX_INCLUSIVE", "true"
).strip().lower() in {"1", "true", "yes", "on"}

# Whether the UNSPENT part of a period's included allowance carries into the next period.
# Default OFF, which is what "1,000 credits/month" means to a buyer and what keeps the
# deferred-liability line on the revenue report from compounding: at each rollover the
# remainder of the old grant is clawed back before the new one lands. PURCHASED credits
# are never touched by this — only the plan grant expires.
PLAN_CREDITS_ROLLOVER = os.getenv("ENTERPRISE_PLAN_CREDITS_ROLLOVER", "false").strip().lower() in {"1", "true", "yes", "on"}

# --- RETIRED: the infrastructure server fee ------------------------------------------
# Until 2026-08-02 the core CRM was free up to FREE_STUDENT_LIMIT active clients, after
# which a flat ₹999/month "infrastructure server fee" unlocked more. The tiered plans in
# app/enterprise_billing.py replaced both halves of that: a plan's `max_clients` is now the
# client cap and the plan fee is the recurring charge.
#
# These constants and the infra_fee_* functions below survive for exactly two reasons:
# historical `kind="infra_fee"` payment rows still need a price to render and refund
# against, and the admin revenue report still reports that revenue bucket. NOTHING creates
# a new infra-fee charge — `/credits/infra/checkout` returns 410 Gone.
FREE_STUDENT_LIMIT = int(os.getenv("ENTERPRISE_FREE_STUDENT_LIMIT", "50") or "50")
INFRA_FEE_PAISE = int(os.getenv("ENTERPRISE_INFRA_FEE_PAISE", "99900") or "99900")  # ₹999 / month
INFRA_FEE_PERIOD_DAYS = int(os.getenv("ENTERPRISE_INFRA_FEE_PERIOD_DAYS", "30") or "30")
INFRA_FEE_RETIRED = True

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
    "document_scan": {
        "key": "document_scan",
        "label": "Document scan & validate",
        "description": (
            "Rilono AI reads ONE uploaded document — checks it is the right type, genuine "
            "and still in date, then cross-validates it against the client's profile and "
            "their already-validated documents, and auto-fills any empty profile fields it "
            "can prove. Storing a document without a scan is always free."
        ),
        "credits": _int_env("ENTERPRISE_CREDIT_COST_DOCUMENT_SCAN", 1),
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
    # Only the BILLED validation call. The free text extraction that also runs on every
    # upload stays on the shared "document_ai" source below, so it is never mistaken for
    # revenue-bearing work in the per-action margin report.
    "document_scan": ["enterprise_document_scan"],
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
    "deep_scan", "deep_scan_extract", "document_ai", "enterprise_document_scan",
    "mock_interview", "interview_feedback",
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
        .populate_existing()          # see below — without this the lock is decorative
        .first()
    )
    if locked is not None:
        # THE LOCK ALONE IS NOT ENOUGH. The line above first put this row in the Session's
        # identity map via get_or_create_wallet, and SQLAlchemy will NOT overwrite the
        # attributes of an object it already holds unexpired — so the locked query returns
        # the same Python object still carrying values read BEFORE the lock was acquired.
        # The read-modify-write would then compute from a stale balance and write it back as
        # an absolute value: exactly the lost update this function exists to prevent, and the
        # window is long (a handler may load the wallet, spend 30-60s in a Gemini call, then
        # debit). populate_existing() forces the locked SELECT's values onto the instance.
        return locked
    return get_or_create_wallet(db, organization_id, commit=False)


def active_client_count(db: Session, organization_id: int) -> int:
    return int(
        db.query(models.EnterpriseClient)
        .filter(models.EnterpriseClient.organization_id == int(organization_id))
        .count()
    )


# ---------------------------------------------------------------------------
# Plan-included credit allowance
#
# Each tier includes N credits per billing period. Granting them is LAZY and
# IDEMPOTENT: `sync_plan_credits` runs on every wallet read and every spend, works out
# which period the org is in, and grants only if that period's key differs from the one
# already stamped on the wallet. There is no cron, so a renewal that lands while nobody is
# looking still credits correctly on the next request, and a request storm at renewal
# time grants once — the wallet row is locked for the read-modify-write.
# ---------------------------------------------------------------------------

def _period_start_for(sub, plan_key: str, *, now: Optional[datetime] = None) -> datetime:
    """The start of the org's CURRENT billing period.

    Paid tiers anchor to `current_period_end` (set at each verified payment) minus the
    period length, so the allowance refreshes on the org's own renewal date rather than on
    the 1st of the calendar month. A paid row with no period end yet — an org mid-upgrade,
    or a legacy row — falls back to the calendar month, which is stable and never grants
    twice. The sandbox anchors to its own creation so its one-time grant has a fixed key.
    """
    from app import enterprise_billing as billing

    now = now or datetime.utcnow()
    if plan_key in billing.PAID_PLAN_KEYS:
        end = _naive(getattr(sub, "current_period_end", None))
        if end:
            period = timedelta(days=billing.PLAN_PERIOD_DAYS)
            start = end - period
            # Legacy yearly rows cover far more than one period, so the anchor can start in
            # the future; step back until it holds `now`.
            while start > now:
                start -= period
            # Walk forward to the period containing `now`, but NEVER past the coverage that
            # was actually paid for. `effective_plan_key` keeps a paid tier alive for
            # PLAN_GRACE_DAYS after `current_period_end`; without the `< end` guard the key
            # would tick over the moment the period ended and hand out a whole free monthly
            # allowance inside that unpaid grace window — reintroducing exactly the
            # mint-credits-forever bug that paid_period_expired() exists to kill. Holding the
            # key at the last PAID period means the grace window grants nothing, and the next
            # real payment (which moves `current_period_end`) is what opens the next grant.
            while (start + period) <= now and (start + period) < end:
                start += period
            return start
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    created = _naive(getattr(sub, "created_at", None)) or now
    return created


def plan_credits_period_key(sub, plan_key: str, *, now: Optional[datetime] = None) -> str:
    """The idempotency key for one period's grant: "<plan>:<period-start>".

    The plan is part of the key on purpose. An org that upgrades Starter → Growth mid-month
    gets a NEW key, so the larger allowance is granted immediately rather than making them
    wait for the next renewal for the tier they just paid for.
    """
    return f"{plan_key}:{_period_start_for(sub, plan_key, now=now):%Y-%m-%d}"


def _has_ever_paid(db: Session, organization_id: int) -> bool:
    """Has this org ever completed a plan purchase? Used to deny the sandbox onboarding
    grant to a lapsed paying customer, who is churning rather than evaluating."""
    return db.query(
        db.query(models.EnterpriseSubscriptionPayment)
        .filter(
            models.EnterpriseSubscriptionPayment.organization_id == int(organization_id),
            models.EnterpriseSubscriptionPayment.status.in_(REVENUE_PAYMENT_STATUSES),
        )
        .exists()
    ).scalar() or False


def _previous_period_elapsed(wallet: models.EnterpriseCreditWallet) -> bool:
    """Has the period whose grant is still sitting in the wallet actually ended?

    The stored key is "<plan>:<period-start YYYY-MM-DD>" (or "<plan>:once"). A one-time
    grant has no period and never expires. Otherwise the previous period ended
    PLAN_PERIOD_DAYS after the start encoded in the key — so an upgrade or an early renewal,
    which also change the key, do NOT count as an expiry.

    An unparseable key returns False: failing towards "don't take credits away" is the only
    safe direction when we cannot prove the period is over.
    """
    from app import enterprise_billing as billing

    raw = str(wallet.plan_credits_period or "")
    if not raw or raw.endswith(":once"):
        return False
    _, _, start_str = raw.rpartition(":")
    try:
        start = datetime.strptime(start_str, "%Y-%m-%d")
    except ValueError:
        return False
    return (start + timedelta(days=billing.PLAN_PERIOD_DAYS)) <= datetime.utcnow()


def sync_plan_credits(
    db: Session,
    organization_id: int,
    *,
    commit: bool = True,
) -> Optional[models.EnterpriseCreditTransaction]:
    """Grant this billing period's included credits, exactly once. Returns the ledger row
    if a grant happened, else None.

    Safe to call on any path, at any frequency — it is a no-op once the current period's
    key is stamped on the wallet.
    """
    from app import enterprise_billing as billing

    if billing.ENTERPRISE_FREE:
        # Billing disabled: no tier, so no allowance to grant.
        return None

    sub = billing.get_or_create_org_subscription(db, organization_id, commit=False)
    plan_key = billing.effective_plan_key(sub)
    allowance = billing.included_credits_for(plan_key)
    recurring = billing.credits_recur_for(plan_key)

    # A one-time allowance (the sandbox's 100 demo credits) is keyed to the org, not to a
    # period — otherwise a sandbox left open for months would mint 100 credits every month.
    period_key = (
        plan_credits_period_key(sub, plan_key) if recurring else f"{plan_key}:once"
    )

    wallet = get_wallet_for_update(db, organization_id)
    if (wallet.plan_credits_period or "") == period_key:
        return None

    # "Once" must mean once per ORGANIZATION, not once per consecutive stretch on the plan.
    # `plan_credits_period` only remembers the LATEST key, so sandbox -> paid -> lapse walks
    # it sandbox:once -> starter:X -> sandbox:once and the equality guard above sees a
    # different value each time. A paid customer who lapses would be handed the 100 demo
    # credits again on every lapse cycle, unboundedly. This timestamp is the durable record.
    # The sandbox grant is an ONBOARDING allowance for someone evaluating the product. An org
    # that has already paid us and then lapsed is not evaluating — handing it 100 free credits
    # rewards churn, and it is the one case where the wallet's "never granted" marker is
    # legitimately empty (they went straight onto a paid tier and never held the sandbox).
    if not recurring and wallet.plan_credits_once_at is None and _has_ever_paid(db, organization_id):
        wallet.plan_credits_once_at = datetime.utcnow()

    suppress_grant = not recurring and wallet.plan_credits_once_at is not None

    granted_before = int(wallet.plan_credits_remaining or 0)
    # Expiry is a TIME event, not a key-change event. The key also changes on an upgrade or
    # an early renewal, and clawing back there would delete allowance the customer has
    # already paid for and not yet used — the moment they gave us more money. So the
    # remainder is only forfeited once the period it belonged to has actually elapsed.
    expired = 0
    if not PLAN_CREDITS_ROLLOVER and granted_before > 0 and _previous_period_elapsed(wallet):
        # Claw back the unspent remainder of the PREVIOUS period's grant before the new one
        # lands. Capped at the live balance so it can never eat purchased credits: if the
        # org spent its allowance and then topped up, `plan_credits_remaining` is already 0
        # and nothing is taken.
        expired = min(granted_before, int(wallet.balance_credits))
        if expired > 0:
            wallet.balance_credits = int(wallet.balance_credits) - expired
            _record_transaction(
                db, wallet=wallet, txn_type="adjustment", credits=-expired,
                action_key=None,
                description=f"Unused monthly plan credits expired ({expired})",
                reference_type="plan_credits",
            )

    # A suppressed one-time grant still ADVANCES the bookkeeping — it just hands out nothing.
    # Returning early instead (before the claw-back above) would let a lapsing paid org keep
    # its unspent monthly allowance forever: the counters would be zeroed without the matching
    # credits ever leaving `balance_credits`.
    if suppress_grant:
        allowance = 0

    wallet.plan_credits_period = period_key
    wallet.plan_credits_granted = int(allowance)
    wallet.plan_credits_remaining = int(allowance)
    if not recurring and int(allowance) > 0:
        # Stamp the durable "the one-time grant has been used" marker.
        wallet.plan_credits_once_at = datetime.utcnow()

    txn = None
    if allowance > 0:
        wallet.balance_credits = int(wallet.balance_credits) + int(allowance)
        plan = billing.get_plan(plan_key) or {}
        label = plan.get("label") or plan_key
        txn = _record_transaction(
            db, wallet=wallet, txn_type="bonus", credits=int(allowance), action_key=None,
            description=(
                f"{label} plan — {allowance:,} credits included this month" if recurring
                else f"{label} — {allowance:,} demo credits"
            ),
            reference_type="plan_credits",
        )

    if commit:
        db.commit()
        if txn is not None:
            db.refresh(txn)
    return txn


def _spend_from_wallet(wallet: models.EnterpriseCreditWallet, cost: int) -> None:
    """Apply a debit of `cost` to a wallet's counters.

    The ONLY place `balance_credits` is decremented for a spend. It also draws down
    `plan_credits_remaining` first (floored at 0), which is what lets the next rollover
    expire only the genuinely unused part of the allowance. Every debit path must go
    through here — a path that decrements the balance directly would leave the allowance
    counter overstated and expire credits the org had already spent.
    """
    cost = int(cost)
    if cost <= 0:
        return
    wallet.balance_credits = int(wallet.balance_credits) - cost
    wallet.plan_credits_remaining = max(0, int(wallet.plan_credits_remaining or 0) - cost)
    wallet.lifetime_spent_credits = int(wallet.lifetime_spent_credits) + cost


def plan_credits_state(db: Session, organization_id: int) -> dict:
    """The allowance panel: what this tier includes, how much of it is left, and when it
    refreshes. Read-only — call `sync_plan_credits` first if a grant may be due."""
    from app import enterprise_billing as billing

    wallet = get_or_create_wallet(db, organization_id, commit=False)
    sub = billing.get_or_create_org_subscription(db, organization_id, commit=False)
    plan_key = billing.effective_plan_key(sub)
    allowance = billing.included_credits_for(plan_key)
    recurring = billing.credits_recur_for(plan_key)
    renews_at = None
    if recurring:
        start = _period_start_for(sub, plan_key)
        renews_at = start + timedelta(days=billing.PLAN_PERIOD_DAYS)
    return {
        "plan": plan_key,
        "plan_label": (billing.get_plan(plan_key) or {}).get("label"),
        "included_credits": int(allowance),
        "recurring": bool(recurring),
        "remaining_this_period": int(wallet.plan_credits_remaining or 0),
        "used_this_period": max(0, int(wallet.plan_credits_granted or 0) - int(wallet.plan_credits_remaining or 0)),
        "rollover": PLAN_CREDITS_ROLLOVER,
        "renews_at": renews_at,
        "period_key": wallet.plan_credits_period,
    }


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
    if delta < 0:
        # CLAMP, don't subtract. The only negative delta comes from issue_money_refund clawing
        # back credits from a refunded TOP-UP, i.e. purchased credits — never plan credits. So
        # subtracting the full claw-back from the plan bucket would shrink an allowance the
        # refund never touched, and the next rollover would then under-expire. Clamping still
        # guarantees the invariant that matters (the plan bucket can never exceed the balance,
        # which is what makes a later expiry eat purchased credits), without stealing from it.
        wallet.plan_credits_remaining = min(
            int(wallet.plan_credits_remaining or 0), int(wallet.balance_credits)
        )
    txn = _record_transaction(
        db, wallet=wallet, txn_type=txn_type, credits=delta, action_key=None,
        description=description, reference_type=reference_type, reference_id=reference_id, user=user,
    )
    if commit:
        db.commit()
        db.refresh(txn)
    return txn, delta


def _sync_plan_credits_quietly(db: Session, organization_id: int, *, commit: bool = False) -> None:
    """Grant any due plan allowance before a balance is read or spent.

    Wrapped because this runs on hot read paths: an org whose allowance cannot be worked
    out (a half-created subscription, a DB hiccup) must still be able to spend the credits
    it already has, rather than have every AI action fail on the grant.

    `commit` defaults to FALSE because the spend paths that call this are mid-transaction —
    committing there would break the caller's atomicity by flushing a half-finished action
    (a document row written but not yet charged for). Those callers commit the grant along
    with their own work, so it still lands.

    `wallet_state` passes commit=True: it is a response builder, called after the handler's
    own commit, and it is the ONLY path a purely read-only organization ever takes. Without
    it, an org that looks at its balance but never spends would recompute the same grant on
    every request and never persist it.
    """
    try:
        # SAVEPOINT, not a bare rollback. A failed flush would otherwise leave the Session
        # raising PendingRollbackError on every later statement, so this has to clean up —
        # but `db.rollback()` here would discard the CALLER's uncommitted work too, and the
        # callers are mid-transaction (a document row written, an AI action already metered).
        # That trades a lost grant for lost customer work plus a charge for a vanished
        # result. begin_nested() rolls back only what happened inside it and leaves the
        # outer transaction intact and usable.
        # "No ledger row" does NOT mean "nothing to persist". A period rollover that grants
        # zero (a suppressed one-time grant, or a lapsed org) still advances
        # plan_credits_period and can claw credits back. Those writes would be silently dropped
        # on read-only paths, so the work would be redone on every request and the claw-back
        # would never stick. The period marker is the reliable signal — db.dirty is already
        # empty here because sync_plan_credits flushes before returning.
        before_key = (get_or_create_wallet(db, organization_id, commit=False).plan_credits_period or "")
        with db.begin_nested():
            txn = sync_plan_credits(db, organization_id, commit=False)
        after_key = (get_or_create_wallet(db, organization_id, commit=False).plan_credits_period or "")
        if commit and (txn is not None or after_key != before_key):
            db.commit()
    except Exception:
        logger.exception("plan-credits: grant sync failed for org %s", organization_id)


def can_afford(db: Session, organization_id: int, action_key: str) -> bool:
    if not ENFORCE:
        return True
    cost = action_cost(action_key)
    if cost <= 0:
        return True
    _sync_plan_credits_quietly(db, organization_id)
    wallet = get_or_create_wallet(db, organization_id, commit=False)
    return int(wallet.balance_credits) >= cost


def enforce_action_or_402(db: Session, organization_id: int, action_key: str) -> None:
    """Pre-check before running a billable AI action. Raises 402 when too poor."""
    if not ENFORCE:
        return
    cost = action_cost(action_key)
    if cost <= 0:
        return
    # A renewal that landed since the last request must credit BEFORE we refuse the action
    # — otherwise a paid-up org gets a "top up your wallet" wall on the day it renewed.
    _sync_plan_credits_quietly(db, organization_id)
    wallet = get_or_create_wallet(db, organization_id, commit=False)
    if int(wallet.balance_credits) >= cost:
        return
    action = get_action(action_key)
    label = action["label"] if action else "this AI action"
    raise HTTPException(
        status_code=402,
        detail=(
            f"Not enough credits for {label}. It costs {cost} credits and your balance is "
            f"{int(wallet.balance_credits)}. Your plan's monthly credits refresh on renewal — "
            "top up your Rilono Credits wallet to continue now."
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
    _sync_plan_credits_quietly(db, organization_id)
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
    _sync_plan_credits_quietly(db, organization_id)
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
    _sync_plan_credits_quietly(db, organization_id)
    wallet = get_wallet_for_update(db, organization_id)
    if ENFORCE and int(wallet.balance_credits) < cost:
        enforce_action_or_402(db, organization_id, action_key)
    action = get_action(action_key)
    balance_before = int(wallet.balance_credits)
    _spend_from_wallet(wallet, cost)
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
    # Same rule as every other 402 gate: a renewal that landed since the last request
    # must credit BEFORE we refuse the message, or a paid-up org hits a top-up wall on
    # the day it renewed — and on this surface that wall is the Chrome extension.
    _sync_plan_credits_quietly(db, organization_id)
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
    # Grant any due renewal before the wallet is read, exactly as charge_action does:
    # otherwise a bundle completing on renewal day debits against a stale balance and
    # the clamp below writes off credits the org has already paid for.
    _sync_plan_credits_quietly(db, organization_id)
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
            cost_each = action_cost(COPILOT_ACTION_KEY) or 1
            # Only drain the bundles the wallet can actually pay for. Draining all of
            # them and then clamping the debit at the balance forgave the shortfall
            # permanently; the unpaid remainder stays accrued for the next top-up.
            payable = min(bundles, int(wallet.balance_credits) // cost_each) if cost_each > 0 else bundles
            bundles = payable
            wallet.copilot_unbilled_msgs = int(wallet.copilot_unbilled_msgs) - bundles * COPILOT_MSGS_PER_CREDIT
            cost = cost_each * bundles
            debit = min(cost, int(wallet.balance_credits))  # never overdraw below zero
            if debit > 0:
                _spend_from_wallet(wallet, debit)
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
# Infrastructure server fee — RETIRED 2026-08-02
#
# Replaced by the tiered plans (app/enterprise_billing.py): a plan's `max_clients` is the
# client cap, and the plan fee is the recurring charge. What is left here is read-only
# history — `is_current`/`fee_due` are pinned so no surface can ask anyone to pay it again,
# and `enforce_infra_fee_or_402` no longer blocks anything. The functions themselves stay
# because the admin revenue report, the refund tooling and historical purchase receipts all
# still resolve `kind="infra_fee"` rows through them.
# ---------------------------------------------------------------------------

def infra_fee_state(db: Session, organization_id: int, *, currency: str | None = None) -> dict:
    """Legacy infra-fee status. `retired` is always True and `fee_due` always False.

    Kept so an old cached SPA bundle that still reads `wallet.infra_fee` renders a dormant
    banner instead of throwing — and so the shape stays stable for the admin console.
    """
    try:
        code = money.normalize_currency(currency or CURRENCY, strict=True)
    except money.UnsupportedCurrency:
        code = money.DEFAULT_CURRENCY
    fee_minor = money.price_minor("infra_fee", code)
    wallet = get_or_create_wallet(db, organization_id, commit=False)
    clients_used = active_client_count(db, organization_id)
    paid_until = _naive(wallet.infra_fee_paid_until)
    return {
        "retired": True,
        "free_student_limit": FREE_STUDENT_LIMIT,
        "clients_used": clients_used,
        "clients_remaining_free": 0,
        # Pinned False/True: the client cap now lives on the plan, so no surface may ever
        # again render "you are over the free limit, pay the infra fee".
        "over_free_limit": False,
        "fee_paise": fee_minor,
        "fee_minor": fee_minor,
        "fee_display": money.format_money(fee_minor, code),
        "fee_period_days": INFRA_FEE_PERIOD_DAYS,
        "is_current": True,
        "fee_due": False,
        "paid_until": wallet.infra_fee_paid_until,
        "currency": code,
        "price_options": money.price_options("infra_fee"),
    }


def enforce_infra_fee_or_402(db: Session, organization_id: int) -> None:
    """No-op since 2026-08-02.

    The client cap it used to guard is now `enterprise_billing.enforce_client_limit_or_402`,
    which the same call sites invoke. Kept as a no-op rather than deleted so a call site
    missed during the cutover fails open (client added) instead of raising ImportError at
    request time — and so the diff that removes the last caller is a clean one.
    """
    return


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
    # Every entry into the Credits screen is also the moment a due allowance should land,
    # so the balance the user is looking at is never one renewal behind.
    _sync_plan_credits_quietly(db, organization_id, commit=True)
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
        # What the org's plan includes each month and how much of it is left. This is the
        # primary "where do credits come from" panel now; top-ups are overage.
        "plan_credits": plan_credits_state(db, organization_id),
        # Retired — always dormant. Kept so a stale cached SPA bundle does not break.
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

# Custom windows: how far back one may be asked for, and the widest axis we will
# draw. Past the bar cap the requested grouping is widened (day → week → month)
# rather than truncated, so the chart still covers the whole period asked for.
ANALYTICS_MAX_CUSTOM_DAYS = 1100          # ~3 years
ANALYTICS_MAX_TIMELINE_BUCKETS = 400
ANALYTICS_BUCKETS = ["day", "week", "month"]


def normalize_analytics_days(days) -> int:
    """Coerce a requested window to one of the supported ranges (default 30d)."""
    try:
        value = int(days)
    except (TypeError, ValueError):
        return DEFAULT_ANALYTICS_DAYS
    return value if value in ANALYTICS_RANGES else DEFAULT_ANALYTICS_DAYS


def parse_analytics_date(value) -> Optional[datetime]:
    """A YYYY-MM-DD from a date input → midnight UTC. None if unparseable.

    Everything in this module timestamps with datetime.utcnow(), and the chart's
    bucket keys are UTC calendar days, so a picked date is read as a UTC day too.
    Mixing in the viewer's local midnight would put a row in one day on the chart
    and a different day in the range filter.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return _naive(value)
    text = str(value).strip()[:10]
    if not text:
        return None
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return None
    # strptime happily accepts 0001-01-01, and the resolver then subtracts a default
    # window from it — which overflows datetime.min and 500s the whole tab. No ledger
    # predates the product, so anything before 2000 is treated as unparseable.
    return parsed if parsed.year >= 2000 else None


def _range_label(start: datetime, end: datetime) -> str:
    """'2 Jul – 15 Jul 2026' — the year is stated once unless the window crosses one,
    and a one-day window is a date, not a range from a day to itself."""
    if start.date() == end.date():
        return end.strftime("%-d %b %Y")
    same_year = start.year == end.year
    left = start.strftime("%-d %b") if same_year else start.strftime("%-d %b %Y")
    return f"{left} – {end.strftime('%-d %b %Y')}"


def resolve_analytics_range(days=None, start=None, end=None) -> dict:
    """The window every analytics figure is measured over.

    Two ways in, one shape out: a preset (`days`, 0 = all time) or an explicit
    `start`/`end` pair from the date pickers. `until` is None for a preset — a
    preset always runs to "now" and needs no upper bound — and set for a custom
    window, which is what makes a closed historical period possible.

    A custom window is clamped rather than rejected wherever it can be: an end in
    the future becomes today (a period that includes tomorrow makes every rate
    read low), a reversed pair is swapped, and a start beyond the retention cap is
    pulled forward. Only a completely unparseable pair falls back to the preset.
    """
    now = datetime.utcnow()
    start_dt = parse_analytics_date(start)
    end_dt = parse_analytics_date(end)

    if start_dt is None and end_dt is None:
        window = normalize_analytics_days(days)
        # Whole calendar days, not a rolling 720 hours. A preset used to start at
        # `now - N days` — keeping the current time-of-day — which made the oldest
        # bar a PARTIAL day: the chart counted spend after 14:20 while clicking that
        # bar (and the day-by-day row) asked the ledger for the whole date. Anchoring
        # to midnight makes every bucket in the window a complete period, so the
        # chart, the breakdown table and the ledger under them always agree.
        since = (
            (now - timedelta(days=window - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
            if window > 0 else None
        )
        return {
            "key": str(window),
            "custom": False,
            "days": window,
            "since": since,
            "until": None,
            "label": "All time" if window == 0 else f"Last {window} days",
            "sub_label": "all time" if window == 0 else f"last {window} days",
        }

    # One half filled in is still a usable intent: "from X" means X → today, and
    # "until Y" means the default window ending at Y.
    if end_dt is None:
        end_dt = now
    if start_dt is None:
        start_dt = end_dt - timedelta(days=DEFAULT_ANALYTICS_DAYS)
    if start_dt > end_dt:
        start_dt, end_dt = end_dt, start_dt

    today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
    since = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    until = min(end_dt.replace(hour=23, minute=59, second=59, microsecond=999999), today_end)
    if since > until:
        since = until.replace(hour=0, minute=0, second=0, microsecond=0)
    if (until - since).days > ANALYTICS_MAX_CUSTOM_DAYS:
        since = (until - timedelta(days=ANALYTICS_MAX_CUSTOM_DAYS)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    span_days = (until.date() - since.date()).days + 1
    return {
        "key": "custom",
        "custom": True,
        "days": span_days,
        "since": since,
        "until": until,
        "label": _range_label(since, until),
        "sub_label": _range_label(since, until),
        "start_date": since.date().isoformat(),
        "end_date": until.date().isoformat(),
    }


def _timeline_bucket(days: int) -> str:
    """Bucket width that keeps a chart readable: ~7-90 bars, never hundreds."""
    if 0 < days <= 90:
        return "day"
    if 0 < days <= 400:
        return "week"
    return "month"


def _bucket_span_days(span_days: int, bucket: str) -> int:
    """Roughly how many bars `bucket` would draw across `span_days`."""
    if bucket == "week":
        return (span_days // 7) + 2
    if bucket == "month":
        return (span_days // 28) + 2
    return span_days


def resolve_timeline_bucket(span_days: int, requested=None) -> str:
    """Honour an explicit day/week/month grouping, widening it only when the axis
    it asks for would run past the bar cap — a 3-year day-by-day chart is 1,100
    unreadable slivers, and silently trimming it would hide the oldest months."""
    choice = str(requested or "").strip().lower()
    if choice not in ANALYTICS_BUCKETS:
        return _timeline_bucket(span_days if span_days > 0 else 0)
    for bucket in ANALYTICS_BUCKETS[ANALYTICS_BUCKETS.index(choice):]:
        if _bucket_span_days(span_days, bucket) <= ANALYTICS_MAX_TIMELINE_BUCKETS:
            return bucket
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
    start=None,
    end=None,
    bucket=None,
    client_limit: int = ANALYTICS_CLIENT_LIMIT,
    member_limit: int = ANALYTICS_MEMBER_LIMIT,
    include_by_member: bool = True,
    ctx=None,
) -> dict:
    """The full credit-spend report for one organization, over a time window.

    The window is either a preset (`days`, 0 = all time) or an explicit
    `start`/`end` pair from the date pickers; `bucket` ("day"/"week"/"month")
    overrides the automatic grouping so a long period can still be read a day at
    a time. Every figure is scoped to that window EXCEPT the burn-rate block,
    which is deliberately a fixed 30-day rate — a runway estimate must not swing
    just because someone flipped the chart to "last 7 days".

    `include_by_member=False` drops the per-colleague breakdown. That block is a
    staff-productivity report, so it is withheld from members whose own record
    access is limited to one office or their own caseload.
    """
    T = models.EnterpriseCreditTransaction
    C = models.EnterpriseClient
    org_id = int(organization_id)
    rng = resolve_analytics_range(days=days, start=start, end=end)
    days = rng["days"]
    now = datetime.utcnow()
    since = rng["since"]
    until = rng["until"]

    def _scoped(query, *, debits_only: bool = True):
        query = query.filter(T.organization_id == org_id)
        if debits_only:
            query = query.filter(T.type == "debit")
        if since is not None:
            query = query.filter(T.created_at >= since)
        if until is not None:
            query = query.filter(T.created_at <= until)
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

    # --- WHEN they were spent (timeline + per-period breakdown) -------------
    # One pass over the window's debits feeds both the chart and the day-by-day
    # table under it: same rows, so a bar and its table line can never disagree.
    rows = (
        _scoped(db.query(T.created_at, T.credits, T.action_key, T.reference_type, T.reference_id))
        .order_by(T.created_at.desc())
        .limit(ANALYTICS_TIMELINE_ROW_CAP)
        .all()
    )
    span_end = until or now
    oldest = None
    for created_at, *_ in rows:
        stamp = _naive(created_at) or now
        oldest = stamp if (oldest is None or stamp < oldest) else oldest
    span_start = since or oldest or span_end
    span_days = max(1, (span_end.date() - span_start.date()).days + 1)
    bucket_request = bucket
    bucket = resolve_timeline_bucket(span_days, bucket)

    buckets: dict[str, dict] = {}
    scope_set = set(_scope_ids) if _scope_ids is not None else None
    for created_at, credit_delta, action_key, ref_type, ref_id in rows:
        stamp = _naive(created_at) or now
        slot = buckets.setdefault(
            _bucket_key(stamp, bucket),
            {"credits": 0, "units": 0, "actions": {}, "clients": set()},
        )
        spent = int(-(credit_delta or 0))
        slot["credits"] += spent
        slot["units"] += 1
        # Retired / never-priced keys collapse into one "Other usage" line, exactly as
        # by_action does — otherwise a bucket shows the same label two or three times.
        act_key = action_key if action_key in ACTIONS else "other"
        act = slot["actions"].setdefault(act_key, {"credits": 0, "units": 0})
        act["credits"] += spent
        act["units"] += 1
        # Scope-limited members must not learn how many DIFFERENT clients the rest of the
        # org touched, so only the clients they can already see are counted here.
        if ref_type == "client" and ref_id is not None and (
            scope_set is None or int(ref_id) in scope_set
        ):
            slot["clients"].add(int(ref_id))

    def _bucket_actions(slot: dict) -> list[dict]:
        return sorted(
            (
                {
                    "key": key,
                    "label": (ACTIONS.get(key, {}) or {}).get("label", "Other usage"),
                    "credits": stat["credits"],
                    "units": stat["units"],
                }
                for key, stat in (slot.get("actions") or {}).items()
            ),
            key=lambda r: (-r["credits"], r["label"]),
        )

    timeline = []
    for key in _bucket_sequence(span_start, span_end, bucket):
        slot = buckets.get(key) or {}
        credits_spent = int(slot.get("credits", 0))
        timeline.append({
            "key": key,
            "credits": credits_spent,
            "units": int(slot.get("units", 0)),
            "clients": len(slot.get("clients") or ()),
            "value_display": format_inr(credits_to_paise(credits_spent)),
            "share_pct": _share(credits_spent, spent_credits),
            "actions": _bucket_actions(slot),
        })
    peak = max((b["credits"] for b in timeline), default=0)
    busiest = next((b for b in timeline if b["credits"] == peak and peak > 0), None)
    active_buckets = sum(1 for b in timeline if b["credits"] > 0)

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
            "key": rng["key"],
            "custom": rng["custom"],
            "days": days,
            "label": rng["label"],
            # Reads inside a sentence ("₹570 · last 30 days"), where the headline
            # label would have to be lowercased — and lowercasing a custom label
            # gives "2 jul – 15 jul 2026".
            "sub_label": rng["sub_label"],
            "since": (since.isoformat() if since else None),
            "until": (until or now).isoformat(),
            "start_date": rng.get("start_date") or (since.date().isoformat() if since else None),
            "end_date": rng.get("end_date") or (until or now).date().isoformat(),
            "options": ANALYTICS_RANGES,
            "max_custom_days": ANALYTICS_MAX_CUSTOM_DAYS,
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
            # What the caller asked for, so the UI can say when a day-by-day
            # request was widened to weeks rather than silently showing weeks.
            "requested_bucket": (str(bucket_request or "").strip().lower() or "auto"),
            "bucket_options": ANALYTICS_BUCKETS,
            "points": timeline,
            "peak_credits": peak,
            "busiest_key": (busiest or {}).get("key"),
            "active_buckets": active_buckets,
            "span_days": span_days,
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

    # --- Plan subscription revenue ----------------------------------------
    # Plan payments live in a DIFFERENT table (EnterpriseSubscriptionPayment) from credit
    # top-ups, because they always did — but before 2026-08-02 nothing was ever sold
    # through it, so this report could ignore it. Now the tiers are the primary revenue
    # line, and omitting them would report the platform's margin as if only top-ups
    # existed. Net of GST: tax collected is remitted to the government, never revenue.
    SP = models.EnterpriseSubscriptionPayment
    plan_rows = (
        db.query(SP.amount_paise, SP.tax_paise, SP.currency, SP.refunded_amount_paise)
        .filter(SP.status.in_(REVENUE_PAYMENT_STATUSES))
        .all()
    )
    plan_gross_paise = 0
    plan_tax_paise = 0
    plan_refunded_paise = 0
    plan_payment_count = 0
    for amount, tax, cur, refunded in plan_rows:
        # The plan book is INR-only, so a non-INR row here would be a bug, not a sale;
        # skip it rather than adding cents to paise.
        if (cur or "INR").strip().upper() != "INR":
            continue
        plan_payment_count += 1
        plan_gross_paise += max(0, _money_paise(amount) - _money_paise(tax))
        plan_tax_paise += _money_paise(tax)
        # A refund is issued against the gross charge, which included GST. Only the ex-tax
        # portion was ever counted as revenue, so only that portion may be reversed out —
        # subtracting the full refund would understate revenue by the tax we also returned.
        gross = _money_paise(amount)
        ref = min(_money_paise(refunded), gross)
        if ref and gross > 0:
            plan_refunded_paise += int(round(ref * (gross - _money_paise(tax)) / gross))
    plan_revenue_paise = max(0, plan_gross_paise - plan_refunded_paise)
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
    gross_revenue_paise = credit_gross_paise + infra_gross_paise + plan_gross_paise
    refunds_paise = credit_refunded_paise + infra_refunded_paise + plan_refunded_paise
    # ALL THREE BUCKETS MUST BE ON THE SAME TAX BASIS or the total is meaningless. The plan
    # bucket is already net of GST (the tax is a separate stamped line). The legacy credit
    # and infra lines were sold at one all-in price with no tax line, which for a registered
    # supplier means the price is deemed GST-INCLUSIVE — so the tax has to be backed out of
    # them too. Adding an ex-tax figure to tax-inclusive ones overstated both revenue and the
    # margin computed from it. Set ENTERPRISE_LEGACY_PRICES_TAX_INCLUSIVE=false if those
    # older sales were genuinely outside GST.
    credit_net_paise = (
        money.tax_inclusive_net_minor(credit_revenue_paise, "INR")
        if LEGACY_PRICES_TAX_INCLUSIVE else credit_revenue_paise
    )
    infra_net_paise = (
        money.tax_inclusive_net_minor(infra_revenue_paise, "INR")
        if LEGACY_PRICES_TAX_INCLUSIVE else infra_revenue_paise
    )
    legacy_tax_paise = (credit_revenue_paise - credit_net_paise) + (infra_revenue_paise - infra_net_paise)
    total_revenue_paise = credit_net_paise + infra_net_paise + plan_revenue_paise

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
            # NET of GST, on the same basis as plan revenue and total_revenue_paise — the
            # buckets are meant to sum to the total, and mixing bases made them disagree on
            # the same screen. The all-in figure is kept alongside for reconciliation.
            "credit_revenue_paise": credit_net_paise,
            "credit_revenue_display": format_inr(credit_net_paise),
            "credit_gross_paise": credit_revenue_paise,
            "credit_gross_display": format_inr(credit_revenue_paise),
            "credit_payment_count": credit_payment_count,
            # Recurring plan subscriptions — the primary revenue line since 2026-08-02.
            # Net of GST: `plan_tax_paise` is collected on behalf of the government and is
            # deliberately excluded from every revenue and margin figure below.
            "plan_revenue_paise": plan_revenue_paise,
            "plan_revenue_display": format_inr(plan_revenue_paise),
            "plan_payment_count": plan_payment_count,
            "plan_tax_paise": plan_tax_paise,
            "plan_tax_display": format_inr(plan_tax_paise),
            "plan_refunded_paise": plan_refunded_paise,
            "plan_refunded_display": format_inr(plan_refunded_paise),
            # Retired ₹999/mo infrastructure fee — historical rows only, never grows.
            "infra_revenue_paise": infra_net_paise,
            "infra_revenue_display": format_inr(infra_net_paise),
            "infra_gross_paise": infra_revenue_paise,
            "infra_gross_display": format_inr(infra_revenue_paise),
            "infra_payment_count": infra_payment_count,
            "infra_retired": INFRA_FEE_RETIRED,
            # Net revenue (after refunds) is the headline; gross + refunds shown for transparency.
            "gross_revenue_paise": gross_revenue_paise,
            "gross_revenue_display": format_inr(gross_revenue_paise),
            "refunds_paise": refunds_paise,
            "refunds_display": format_inr(refunds_paise),
            "legacy_tax_paise": legacy_tax_paise,
            "legacy_tax_display": format_inr(legacy_tax_paise),
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
