"""
Rilono Credits — the AI metering unit for Rilono Enterprise (B2B).

A credit is what an AI action costs an agency. Credits reach a wallet three ways:

  1. INCLUDED WITH THE PLAN. Every organization is on a tier (app/enterprise_billing.py)
     and each tier carries a per-period allowance — by default 150 / 450 / 1,200 credits a
     month for Starter / Team / Multi-branch, and 50 once for the 14-day free trial — plus
     whatever Branch Packs and admin overrides add (billing.effective_limits).
     `sync_plan_credits` grants it exactly once per billing period, and a plan change inside
     a live period only ever tops it up to the new tier (never a second full allowance).
  2. THE DEMO-CALL BONUS. Rilono staff grant TRIAL_DEMO_BONUS_CREDITS (50) once per org
     after a demo call (`grant_demo_call_bonus`, durable via demo_bonus_granted_at).
  3. PURCHASED AS A TOP-UP for overage, via Razorpay, from PACKAGES below. A team that
     burns its monthly allowance early buys more rather than being stopped — while its
     plan or trial is live; a lapsed org renews, it does not top up.

Next to credits, every plan includes AI document READS: the free text extraction that runs
on each upload, metered in 15-page blocks against a per-period allowance (150 / 500 / 1,000,
and 50 for the whole trial). Reads are a counter on the wallet, not credits: they are never
bought, never roll over, and an upload past the allowance is stored "not read" instead of
being refused (`consume_reads`, `reads_state`). A paid document check reads the file itself
and never touches the reads allowance.

We charge by the *value* of the task to the agency, not by the GCP compute cost — so the
margin per action is high, and `build_revenue_analytics` is what proves it, cross-checking
real Gemini spend (from app.ai_usage) against plan + top-up revenue.

Economics (defaults; every number is env-overridable and the action descriptions shown to
customers are GENERATED from these constants, never typed by hand):
  * 1 Rilono Credit = ₹10.
  * Top-up packages (Razorpay, charm-priced): Starter ₹999 → 100 cr; Pro ₹2,999 → 350 cr
    (50 bonus); Enterprise ₹4,999 → 650 cr (150 bonus).
  * Document check = 4 credits per 15-page block; SOP / LOR draft or refinement = 5;
    Course Finder / university shortlist = 5 each; mock interview = 20 per session (up to
    12 officer questions + one feedback report); Deep Scan = 40 per scan (up to 20
    documents, no free scans); AI assistant = 5 free messages per org per day, then 1 credit
    per 2 messages; client Copilot link = 30 credits for 5 messages over 30 days.
  * While the trial has expired or a paid plan has lapsed, AI is PAUSED: every enforce /
    charge / precheck function below calls billing.enforce_ai_access_or_402 before anything
    else, so no path can reach a model (or take a credit) for a paused org.

This module owns the credit math, wallet operations, the ledger, the plan-allowance and
reads grants, and the admin revenue analytics. Razorpay order creation / verification lives
in the enterprise router; PRICES live in app/money.py. This module is the single source of
truth for credit costs, balances and reporting.

HISTORY:
  * 2026-08-02 — the previous model (free CRM up to 50 students, then a flat ₹999/mo
    infrastructure server fee, with credits only as prepaid top-ups) was replaced by the
    tiered plans. The infra fee is retired; see INFRA_FEE_RETIRED below for what remains.
  * 2026-10-22 — re-priced. The included allowances were 1,000 / 3,500 / 10,000 credits,
    which earned ₹1.50–3.00 per credit against actions that cost more than that to run, and
    a document scan / SOP draft sold for 1 credit. Allowances were cut, action prices raised
    (document scan 1 → 4 per block, writing studio 1 → 5, Deep Scan 20 → 40 with no free
    scans, assistant 1 credit / 5 messages → 1 / 2, client Copilot 20 credits for 100
    messages → 30 for 5), and the reads allowance and the AI-paused gate were added.
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


def _plural(count: int, word: str) -> str:
    return f"{int(count):,} {word}" + ("" if int(count) == 1 else "s")


# ---------------------------------------------------------------------------
# Per-action limits that the PRICE depends on
#
# These are declared before ACTIONS because the customer-facing descriptions are generated
# from them: a description that restated "20 documents" or "100 messages" by hand is how the
# old copy drifted from what the code actually did. Where another module enforces the limit,
# the SAME env var is read here so the two can only disagree if someone edits a default in
# one place — and tests/test_enterprise_credits_v2.py pins each pair equal.
# ---------------------------------------------------------------------------

# Paid document checks are priced per block of this many pages — the SAME block the reads
# allowance uses (app/utils/gemini_service.READ_BLOCK_PAGES), so "4 credits per 15 pages" and
# "1 read per 15 pages" can never drift apart. Deliberately not env-overridable, for the
# reason given there: the block size is printed in the public price list.
DOCUMENT_BLOCK_PAGES = 15

# The most documents one Deep Scan processes (enforced by enterprise_ai.DEEP_SCAN_MAX_DOCUMENTS,
# same env var). It is what bounds a scan's worst-case model cost against its flat price.
DEEP_SCAN_MAX_DOCUMENTS = max(1, _int_env("DEEP_SCAN_MAX_DOCUMENTS", 20))

# Officer questions per mock-interview session (enforced server-side by
# enterprise_interview.MAX_INTERVIEW_QUESTIONS, same env var). One session = these questions
# plus ONE feedback report, sold at one flat price.
INTERVIEW_MAX_QUESTIONS = max(1, _int_env("ENTERPRISE_INTERVIEW_MAX_QUESTIONS", 12))

# Rilono AI assistant (copilot) metering. The copilot is a function-calling agent (the most
# expensive call type), so it must be metered — but gently: a free daily allowance per org,
# then 1 credit per bundle of COPILOT_MSGS_PER_CREDIT messages. At 2 messages per credit a
# message earns ₹5 (it was ₹2 at 5 per credit, re-cut with the rest of the price list).
COPILOT_ACTION_KEY = "ai_copilot"
COPILOT_FREE_DAILY = _int_env("ENTERPRISE_COPILOT_FREE_DAILY", 5)          # free messages / org / day
COPILOT_MSGS_PER_CREDIT = max(1, _int_env("ENTERPRISE_COPILOT_MSGS_PER_CREDIT", 2))  # billable msgs per credit

# The CLIENT Copilot link (a client chatting about their own case via an emailed link) is a
# flat per-client unlock, not the staff meter above. Interim pricing (owner, 2026-10-22):
# 30 credits buys 5 messages over 30 days — priced so the link can never be a loss, and not
# promoted in marketing until it is re-cut. A new invite's `allowed_messages` and expiry must
# come from COPILOT_CLIENT_MESSAGES / COPILOT_CLIENT_DAYS (same env vars the router has always
# read) so the counter the client hits and the price list's promise cannot drift apart.
COPILOT_CLIENT_ACTION_KEY = "copilot_client"
COPILOT_CLIENT_MESSAGES = max(1, _int_env("ENTERPRISE_COPILOT_INVITE_MESSAGES", 5))
COPILOT_CLIENT_DAYS = max(1, _int_env("ENTERPRISE_COPILOT_INVITE_EXPIRES_DAYS", 30))

# Each CLIENT's first N Deep Scans are free (per client, not per org). Default 0 since
# 2026-10-22: at 40 credits a scan, a free scan on every new dossier gave away more than a
# Starter plan's whole monthly allowance to an office adding four clients. Kept as a knob
# (with the per-org monthly cap below) so a promotion can switch it back on by config.
# Counted from stored scan rows — a failed scan stores nothing, so it never burns a freebie.
DEEP_SCAN_FREE_SCANS_PER_CLIENT = _int_env("ENTERPRISE_DEEP_SCAN_FREE_SCANS_PER_CLIENT", 0)
# Anti-farming cap: scan rows die with their client (cascade), so create→scan→delete
# churn could otherwise mint unlimited free Gemini audits. The org's TOTAL free scans
# are therefore also capped per calendar month (generous for honest client intake —
# beyond it, a new client's first scan simply costs the normal price).
DEEP_SCAN_FREE_MONTHLY_ORG_CAP = _int_env("ENTERPRISE_DEEP_SCAN_FREE_MONTHLY_ORG_CAP", 25)


def _deep_scan_description() -> str:
    text = (
        "Rilono AI strictly audits the client's ENTIRE dossier — profile, stage records, the "
        f"contents of up to {_plural(DEEP_SCAN_MAX_DOCUMENTS, 'document')}, notes, emails, "
        "universities, interviews and payments — and flags anything irregular."
    )
    if DEEP_SCAN_FREE_SCANS_PER_CLIENT == 1:
        text += " Each client's first scan is free."
    elif DEEP_SCAN_FREE_SCANS_PER_CLIENT > 1:
        text += f" Each client's first {DEEP_SCAN_FREE_SCANS_PER_CLIENT} scans are free."
    return text


# Premium AI actions and what they cost the agency, in credits. We charge by value
# (protecting a large university commission), not GCP compute cost.
#
# `credits` is the price of ONE `unit` (action_cost multiplies by units): a document check is
# priced per 15-page block, the assistant per bundle of messages, everything else per run.
# `unit_label` is how the price reads after the number ("4 credits per 15 pages").
ACTIONS = {
    "deep_scan": {
        "key": "deep_scan",
        "label": "Deep Scan client audit",
        "description": _deep_scan_description(),
        "credits": _int_env("ENTERPRISE_CREDIT_COST_DEEP_SCAN", 40),
        "unit": "scan",
        "unit_label": "per scan",
        "max_documents": DEEP_SCAN_MAX_DOCUMENTS,
    },
    "document_scan": {
        "key": "document_scan",
        "label": "Document scan & validate",
        "description": (
            "Rilono AI reads ONE uploaded document — checks it is the right type, genuine "
            "and still in date, then cross-validates it against the client's profile and "
            "their already-validated documents, and auto-fills any empty profile fields it "
            f"can prove. Priced per {DOCUMENT_BLOCK_PAGES}-page block (an image or text file is "
            "one block); the check reads the file itself, so it never uses your monthly "
            "document reads. Storing a document without a check is always free."
        ),
        "credits": _int_env("ENTERPRISE_CREDIT_COST_DOCUMENT_SCAN", 4),
        "unit": "block",
        "unit_label": f"per {DOCUMENT_BLOCK_PAGES} pages",
        "pages_per_unit": DOCUMENT_BLOCK_PAGES,
    },
    "mock_interview": {
        "key": "mock_interview",
        "label": "AI mock visa interview",
        "description": (
            "A full dynamic mock visa interview tailored to the client's weak points — up to "
            f"{_plural(INTERVIEW_MAX_QUESTIONS, 'officer question')} and one feedback report "
            "per session."
        ),
        "credits": _int_env("ENTERPRISE_CREDIT_COST_MOCK_INTERVIEW", 20),
        "unit": "session",
        "unit_label": "per interview",
        "max_questions": INTERVIEW_MAX_QUESTIONS,
    },
    "university_match": {
        "key": "university_match",
        "label": "AI university shortlist",
        "description": "Rilono AI recommends real universities matched to the client's destination, budget, grades and intake.",
        "credits": _int_env("ENTERPRISE_CREDIT_COST_UNIVERSITY_MATCH", 5),
        "unit": "shortlist",
        "unit_label": "per shortlist",
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
        "unit": "shortlist",
        "unit_label": "per shortlist",
    },
    "writing_studio": {
        "key": "writing_studio",
        "label": "SOP / LOR draft",
        "description": (
            "Rilono AI writes a personalized, submission-ready Statement of Purpose or "
            "Letter of Recommendation for the selected client — grounded in their real "
            "dossier and exported as a formatted Word document. Refinements cost the same."
        ),
        "credits": _int_env("ENTERPRISE_CREDIT_COST_WRITING_STUDIO", 5),
        "unit": "draft",
        "unit_label": "per draft or refinement",
    },
    "ai_copilot": {
        "key": "ai_copilot",
        "label": "Rilono AI assistant",
        "description": (
            "Ask anything about your workspace — clients, documents, calendar, team, "
            "credits, your books and Rilono's university catalog. First "
            f"{_plural(COPILOT_FREE_DAILY, 'message')}/day are free, then "
            f"{_plural(_int_env('ENTERPRISE_CREDIT_COST_COPILOT_BUNDLE', 1), 'credit')} per "
            f"{_plural(COPILOT_MSGS_PER_CREDIT, 'message')}. A question that needs several "
            "lookups counts as more than one message."
        ),
        # Cost is per BUNDLE of COPILOT_MSGS_PER_CREDIT messages (not per message).
        "credits": _int_env("ENTERPRISE_CREDIT_COST_COPILOT_BUNDLE", 1),
        "unit": "bundle",
        "unit_label": f"per {_plural(COPILOT_MSGS_PER_CREDIT, 'message')}",
        "messages_per_unit": COPILOT_MSGS_PER_CREDIT,
        "free_daily_messages": COPILOT_FREE_DAILY,
    },
    "copilot_client": {
        "key": "copilot_client",
        "label": "Client copilot access",
        "description": (
            "Give a client their own secure Copilot chat about their application via an "
            "emailed link (verified by a one-time code). Flat price per client, charged "
            "once when the client first opens it — valid "
            f"{_plural(COPILOT_CLIENT_DAYS, 'day')}, up to "
            f"{_plural(COPILOT_CLIENT_MESSAGES, 'message')}."
        ),
        # Flat per-client unlock (NOT the per-message staff meter above).
        "credits": _int_env("ENTERPRISE_CREDIT_COST_COPILOT_CLIENT", 30),
        "unit": "client",
        "unit_label": "per client link",
        "messages_included": COPILOT_CLIENT_MESSAGES,
        "valid_days": COPILOT_CLIENT_DAYS,
    },
}

# The wallet's "low balance" line, shared by the Credits screen banner (wallet_state) and the
# one-time admin notification (enterprise_notifications.maybe_notify_credits_low), so the two
# never disagree. Default: the price of the single most expensive action — below it, some AI
# action already refuses. (It used to be a fixed 20, the old Deep Scan price; at 40 a Deep
# Scan, a 20 line warned only after the org could no longer run one.)
LOW_BALANCE_CREDITS = _int_env(
    "ENTERPRISE_CREDITS_LOW_THRESHOLD",
    max([int(a["credits"]) for a in ACTIONS.values()] + [1]),
)

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
# (or an expensive model) cost more. At 1 credit / 2 messages a message earns ₹5 ≈ $0.058,
# so a $0.007 budget floors the gross margin at ~8x by construction, whatever the model.
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


def _month_str() -> str:
    return datetime.utcnow().strftime("%Y-%m")


def deep_scan_free_budget_left(db: Session, organization_id: int) -> int:
    """How many free Deep Scans this org has left in the current month's budget.

    0 while AI is paused: the router decides "free" from this number and skips the credit
    pre-check for a free scan, so a paused org must never be told it has a free one left.
    """
    from app import enterprise_billing as billing

    if not billing.ai_access_state(db, organization_id)["allowed"]:
        return 0
    wallet = get_or_create_wallet(db, organization_id, commit=False)
    used = int(getattr(wallet, "deep_scan_free_used", 0) or 0) \
        if getattr(wallet, "deep_scan_free_month", None) == _month_str() else 0
    return max(0, DEEP_SCAN_FREE_MONTHLY_ORG_CAP - used)


def consume_deep_scan_free(db: Session, organization_id: int) -> None:
    """Record one free Deep Scan against the org's monthly budget (call only after a
    successful free scan, inside the caller's transaction — no commit here). Refuses (402)
    while AI is paused, like every other charge path."""
    _ai_gate_or_402(db, organization_id)
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
    # upload stays on its own sources below ("document_ai" for legacy rows,
    # "enterprise_document_read" for the reads allowance), so it is never mistaken for
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
# whose per-action economics track marginal cost only. enterprise_document_read is the
# monthly reads allowance (gemini_service.ENTERPRISE_READ_USAGE_SOURCE): no credit is
# charged for it, but the plan fee pays for it, so it is a real cost against plan revenue.
ENTERPRISE_COST_SOURCES = [
    "deep_scan", "deep_scan_extract", "document_ai", "enterprise_document_read",
    "enterprise_document_scan",
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


def _units(units) -> int:
    """A billable unit count, floored at 1. A malformed or zero count must never make an
    action FREE — a 0-page document is still one block, an unknown count is one unit."""
    try:
        value = int(units)
    except (TypeError, ValueError):
        return 1
    return max(1, value)


def action_cost(action_key: str, units: int = 1) -> int:
    """Credits for `units` of an action: the per-unit price × units (0 for an unknown key).

    Units are action-specific — 15-page blocks for a document check (document_scan_units),
    message bundles for the assistant, and 1 for everything priced per run.
    """
    action = get_action(action_key)
    return int(action["credits"]) * _units(units) if action else 0


def document_scan_units(pages, max_blocks: Optional[int] = None) -> int:
    """Billable blocks for a paid document check of `pages` pages: ceil(pages / 15), >= 1.

    Delegates to gemini_service.read_blocks_for — the reader's own rounding — so the credits
    meter and the reads meter can never count the same file differently. Pass the same
    `max_blocks` the check reads with, so pages nobody read are never charged.
    """
    try:
        from app.utils.gemini_service import read_blocks_for
    except Exception:  # noqa: BLE001 — a reader import problem must not make checks free
        blocks = -(-_units(pages) // DOCUMENT_BLOCK_PAGES)
        if max_blocks is not None:
            blocks = min(blocks, _units(max_blocks))
        return max(1, blocks)
    return max(1, int(read_blocks_for(pages, max_blocks=max_blocks)))


def _action_price_label(action: dict, units: int = 1) -> str:
    """'4 credits per 15 pages', '40 credits per scan', '1 credit per 2 messages'."""
    return f"{_plural(int(action['credits']) * _units(units), 'credit')} {action.get('unit_label') or ''}".strip()


def _ai_gate_or_402(db: Session, organization_id: int, *, client_facing: bool = False) -> None:
    """The shared AI-paused gate (billing.enforce_ai_access_or_402), applied FIRST by every
    enforce / charge / precheck function in this module.

    It sits in front of the ENFORCE switch on purpose: ENTERPRISE_CREDITS_ENFORCE=false is a
    soft launch for the WALLET (spend past zero), not permission for an expired trial or a
    lapsed plan to keep running AI — that has its own switch, ENTERPRISE_AI_PAUSE_ON_EXPIRY.
    Read-only, so it is safe before the row-locked wallet work that follows.
    """
    from app import enterprise_billing as billing

    billing.enforce_ai_access_or_402(db, organization_id, client_facing=client_facing)


def _ai_allowed(db: Session, organization_id: int) -> bool:
    """The same gate as a predicate, for the can_* helpers that must answer rather than raise
    (they also feed GET payloads, where a 402 would break the screen)."""
    from app import enterprise_billing as billing

    return bool(billing.ai_access_state(db, organization_id)["allowed"])


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


def wallet_snapshot(db: Session, organization_id: int) -> models.EnterpriseCreditWallet:
    """Read the stored balance without granting credits or inserting a missing wallet."""
    with db.no_autoflush:
        wallet = db.query(models.EnterpriseCreditWallet).filter(
            models.EnterpriseCreditWallet.organization_id == int(organization_id)
        ).first()
    if wallet is not None:
        return wallet
    return models.EnterpriseCreditWallet(
        organization_id=int(organization_id), balance_credits=0,
        lifetime_purchased_credits=0, lifetime_spent_credits=0,
        plan_credits_granted=0, plan_credits_remaining=0,
        copilot_msgs_today=0, copilot_unbilled_msgs=0,
        interview_staff_previews_used=0,
        # Column defaults are not applied to a transient instance, so the reads counters
        # are spelled out — None here would read as "unknown", not 0.
        reads_period=None, reads_granted=0, reads_used=0,
    )


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
    """EVERY client in the workspace, open or not. NOT the plan-limit count — that is
    enterprise_billing.open_client_count (open files only). This one feeds the legacy
    infra-fee panel and the assistant's workspace overview, which describe the whole book."""
    return int(
        db.query(models.EnterpriseClient)
        .filter(models.EnterpriseClient.organization_id == int(organization_id))
        .count()
    )


# ---------------------------------------------------------------------------
# Plan-included allowances: AI credits and AI reads
#
# Each tier includes N credits and M reads per billing period (billing.effective_limits:
# the plan's numbers, admin overrides, Branch Packs). Granting them is LAZY and
# IDEMPOTENT: `sync_plan_credits` runs on every wallet read and every spend, works out
# which period the org is in, and grants only if that period's key differs from the one
# already stamped on the wallet. There is no cron, so a renewal that lands while nobody is
# looking still credits correctly on the next request, and a request storm at renewal
# time grants once — the wallet row is locked for the read-modify-write.
#
# A key change is one of three things, told apart by the STORED key (not the new one):
#   1. A GENUINE NEW PERIOD — the stored period has elapsed, there was none, or it was the
#      one-time trial key. The unspent plan remainder of the old period expires and the full
#      allowance lands.
#   2. A PLAN CHANGE INSIDE A LIVE PAID PERIOD — upgrade, downgrade, or a re-buy that
#      re-anchors the period. Only max(0, new allowance − already granted this period) lands,
#      and "granted" becomes max(old, new): a downgrade grants nothing and takes nothing.
#   3. NO key change but a RAISED allowance — an override or Branch Pack set mid-period.
#      The same difference lands now, so the customer gets what they just bought today
#      rather than at the next renewal; a lowered allowance takes nothing back.
# Reads follow the same rules on their own key (`reads_period`) with no ledger and no
# rollover: a genuine new period sets reads_used back to 0.
# ---------------------------------------------------------------------------

_PERIOD_CHAIN_LIMIT = 6


def _plan_coverage_chain(sub) -> list[int]:
    """Days of coverage bought by the org's most recent plan payments, newest first
    (billing.period_days_for of each payment's billing_cycle) — [] when unknown.

    The subscription row only stores WHERE the paid coverage ends, not how it was built up;
    the payment rows say what each purchase added (30 days monthly, 365 yearly), and that is
    what lets a yearly coverage be split into sub-periods from its START. Read through the
    row's own session so _period_start_for keeps its (sub, plan_key) signature; a transient
    row (subscription_snapshot's unsaved default) has no session and no payments anyway."""
    from sqlalchemy.orm import object_session

    from app import enterprise_billing as billing

    org_id = getattr(sub, "organization_id", None)
    try:
        session = object_session(sub)
    except Exception:  # not a mapped instance (a stand-in object in a test or a caller)
        session = None
    if session is None or org_id is None:
        return []
    with session.no_autoflush:
        rows = (
            session.query(models.EnterpriseSubscriptionPayment.billing_cycle)
            .filter(
                models.EnterpriseSubscriptionPayment.organization_id == int(org_id),
                # Same statuses as billing._latest_plan_payment: a payment that was later
                # refunded still extended current_period_end (nothing rolls coverage back).
                models.EnterpriseSubscriptionPayment.status.in_(REVENUE_PAYMENT_STATUSES),
            )
            .order_by(models.EnterpriseSubscriptionPayment.id.desc())
            .limit(_PERIOD_CHAIN_LIMIT)
            .all()
        )
    return [billing.period_days_for(cycle) for (cycle,) in rows]


def _coverage_bounds(
    end: datetime, chain: list[int], now: datetime, period: timedelta,
) -> tuple[datetime, datetime]:
    """(start, end) of the allowance sub-period that holds `now`, for paid coverage ending at
    `end` whose purchases (newest first) bought `chain` days each.

    THE YEARLY CASE. One 365-day payment must yield TWELVE monthly allowances, starting on the
    day it was bought. Walking 30-day periods back from `end` (the old rule, and still the
    monthly rule below) does not: 365 = 12 × 30 + 5, so the walk leaves a 5-day sliver at the
    START — a yearly buyer's first allowance expired after 5 days and the year held 13. Here a
    coverage longer than one period is cut forward from its own start (end − its days), and the
    final sub-period absorbs the remainder (35 days) instead of opening a 13th grant.

    A coverage that has NOT started yet (anchor > now: the latest payment was stacked onto a
    period still running, i.e. renewed early) is not the current one — the previous purchase's
    coverage is, and it ended exactly at this anchor. Recursing onto it keeps the CURRENT
    sub-period's key steady through an early renewal; recomputing it on a different grid would
    change the key mid-period and, in a yearly coverage's 35-day tail, read the old key as
    elapsed and hand out an extra allowance for the few days left.
    """
    days = chain[0] if chain else int(period.days)
    anchor = end - timedelta(days=days)
    if anchor > now and len(chain) > 1:
        return _coverage_bounds(anchor, chain[1:], now, period)
    if days <= period.days:
        # One period per payment (monthly) — the original rule, unchanged.
        start = end - period
        # The anchor can sit in the future (stacked renewals, or a long legacy row with no
        # payment history to split it by); step back until it holds `now`.
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
        return start, start + period
    if anchor > now:
        # A long coverage stacked on a period we know nothing about (no older payment row):
        # the best available grid is whole periods back from where this coverage begins.
        start = anchor
        while start > now:
            start -= period
        return start, start + period
    # Long (yearly) coverage that has begun: sub-periods counted FORWARD from its start. The
    # index is capped at the last full sub-period, which therefore runs to `end` — and that
    # cap is also what holds the key steady through the PLAN_GRACE_DAYS after `end`, the
    # same no-free-grant-in-grace rule as the monthly walk above.
    full = max(1, days // period.days)
    index = min(int((now - anchor) // period), full - 1)
    start = anchor + period * index
    return start, (end if index == full - 1 else start + period)


def _period_bounds_for(sub, plan_key: str, *, now: Optional[datetime] = None) -> tuple[datetime, datetime]:
    """(start, end) of the org's CURRENT allowance period — see _period_start_for. `end` is
    when the next grant is due (the renewal date shown as renews_at / period_ends_at)."""
    from app import enterprise_billing as billing

    now = now or datetime.utcnow()
    period = timedelta(days=billing.PLAN_PERIOD_DAYS)
    if plan_key in billing.PAID_PLAN_KEYS:
        end = _naive(getattr(sub, "current_period_end", None))
        if end:
            return _coverage_bounds(end, _plan_coverage_chain(sub), now, period)
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return start, start + period
    created = _naive(getattr(sub, "created_at", None)) or now
    return created, created + period


def _period_start_for(sub, plan_key: str, *, now: Optional[datetime] = None) -> datetime:
    """The start of the org's CURRENT billing period.

    Paid tiers anchor to `current_period_end` (set at each verified payment): a monthly
    coverage's period is the 30 days before it, so the allowance refreshes on the org's own
    renewal date rather than on the 1st of the calendar month; a yearly coverage is cut into
    monthly sub-periods from the day it was bought (see _coverage_bounds). A paid row with no
    period end yet — an org mid-upgrade, or a legacy row — falls back to the calendar month,
    which is stable and never grants twice. The sandbox anchors to its own creation so its
    one-time grant has a fixed key.
    """
    return _period_bounds_for(sub, plan_key, now=now)[0]


def plan_credits_period_key(sub, plan_key: str, *, now: Optional[datetime] = None) -> str:
    """The idempotency key for one period's grant: "<plan>:<period-start>".

    The plan is part of the key on purpose. An org that upgrades Starter → Team mid-month
    gets a NEW key, so sync_plan_credits notices the change on the very next request rather
    than at the next renewal — and then grants only the difference up to the new tier
    (rule 2 above), never a second full allowance for the same period.
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


ONCE_KEY_SUFFIX = ":once"


def _key_period_start(key) -> Optional[datetime]:
    """The period start encoded in a recurring key "<plan>:<YYYY-MM-DD>", else None — for a
    one-time "<plan>:once" key, an empty key, or anything unparseable."""
    raw = str(key or "")
    if not raw or raw.endswith(ONCE_KEY_SUFFIX):
        return None
    _, _, start_str = raw.rpartition(":")
    try:
        return datetime.strptime(start_str, "%Y-%m-%d")
    except ValueError:
        return None


def _period_key_elapsed(key) -> bool:
    """Has the period a stored key belongs to actually ended?

    The stored key is "<plan>:<period-start YYYY-MM-DD>" (or "<plan>:once"). A one-time
    grant has no period and never expires. Otherwise the period ended PLAN_PERIOD_DAYS after
    the start encoded in the key — so an upgrade or an early renewal, which also change the
    key, do NOT count as an expiry.

    An unparseable key returns False: failing towards "don't take credits away" is the only
    safe direction when we cannot prove the period is over.
    """
    from app import enterprise_billing as billing

    start = _key_period_start(key)
    if start is None:
        return False
    return (start + timedelta(days=billing.PLAN_PERIOD_DAYS)) <= datetime.utcnow()


def _period_key_live(key) -> bool:
    """A recurring (paid) key whose period has NOT ended yet. A key change away from one is
    a plan change INSIDE that period — not a renewal — so it earns only the difference up to
    the new tier. An empty, one-time or unparseable key is not live: an unreadable legacy key
    is no evidence that this period's allowance was already handed out, and the old code
    granted in full on any key change, so that is where the doubt falls."""
    return _key_period_start(key) is not None and not _period_key_elapsed(key)


def _previous_period_elapsed(wallet: models.EnterpriseCreditWallet) -> bool:
    """_period_key_elapsed for the wallet's stored CREDIT key."""
    return _period_key_elapsed(wallet.plan_credits_period)


def _grant_plan_credits(
    db: Session, wallet: models.EnterpriseCreditWallet, credits: int, description: str,
) -> Optional[models.EnterpriseCreditTransaction]:
    """Add `credits` of plan allowance to the balance with a ledger row (None if 0). The
    caller has already moved plan_credits_granted / plan_credits_remaining."""
    credits = int(credits)
    if credits <= 0:
        return None
    wallet.balance_credits = int(wallet.balance_credits) + credits
    return _record_transaction(
        db, wallet=wallet, txn_type="bonus", credits=credits, action_key=None,
        description=description, reference_type="plan_credits",
    )


def _explicit_override(sub, limits: dict, column: str) -> bool:
    """Did an admin set this number for this org (and does it currently apply)? Overrides
    are ignored on a lapsed org (billing._limits_for), and so is this."""
    return bool(limits.get("overrides_applied")) and getattr(sub, column, None) is not None


def sync_plan_credits(
    db: Session,
    organization_id: int,
    *,
    commit: bool = True,
) -> Optional[models.EnterpriseCreditTransaction]:
    """Grant this billing period's included credits AND AI reads, exactly once. Returns the
    credit ledger row if credits were granted, else None (reads never write a ledger row).

    Safe to call on any path, at any frequency — it is a no-op once the current period's
    keys are stamped on the wallet and the allowance has not been raised. See the section
    comment above for the three kinds of key change and what each grants.
    """
    from app import enterprise_billing as billing

    if billing.ENTERPRISE_FREE:
        # Billing disabled: no tier, so no allowance to grant (reads are unmetered).
        return None

    sub = billing.get_or_create_org_subscription(db, organization_id, commit=False)
    # What THIS org gets — the plan's numbers with admin overrides and Branch Packs applied
    # (neither on a lapsed org). Never included_credits_for(), which is the bare plan.
    limits = billing.effective_limits(db, organization_id)
    plan_key = limits["plan"]
    recurring = bool(limits["credits_recur"])

    # A one-time allowance (the trial's credits and reads) is keyed to the org, not to a
    # period — otherwise a sandbox left open for months would mint them every month.
    period_key = (
        plan_credits_period_key(sub, plan_key) if recurring else f"{plan_key}{ONCE_KEY_SUFFIX}"
    )

    wallet = get_wallet_for_update(db, organization_id)
    txn, once_suppressed = _sync_credit_allowance(
        db, wallet, sub, organization_id,
        plan_key=plan_key, period_key=period_key, recurring=recurring,
        allowance=max(0, int(limits["included_credits"] or 0)),
        explicit_override=_explicit_override(sub, limits, "override_included_credits"),
    )
    _sync_read_allowance(
        db, wallet, sub, organization_id,
        period_key=period_key, recurring=recurring,
        allowance=limits["monthly_reads"],
        explicit_override=_explicit_override(sub, limits, "override_monthly_reads"),
        once_suppressed=once_suppressed,
    )

    if commit:
        db.commit()
        if txn is not None:
            db.refresh(txn)
    return txn


def _sync_credit_allowance(
    db: Session,
    wallet: models.EnterpriseCreditWallet,
    sub,
    organization_id: int,
    *,
    plan_key: str,
    period_key: str,
    recurring: bool,
    allowance: int,
    explicit_override: bool,
) -> tuple[Optional[models.EnterpriseCreditTransaction], Optional[bool]]:
    """The credit half of sync_plan_credits (wallet already row-locked).

    Returns (ledger row or None, once_suppressed). `once_suppressed` is the one-time-grant
    decision when this call moved the wallet ONTO a one-time key, else None — the reads half
    applies the same decision, so a lapsed payer or a repeat company domain is denied trial
    reads exactly when it is denied trial credits.
    """
    from app import enterprise_billing as billing

    stored = wallet.plan_credits_period or ""
    granted = int(wallet.plan_credits_granted or 0)
    plan = billing.get_plan(plan_key) or {}
    label = plan.get("label") or plan_key

    if stored == period_key:
        # Same period. The only thing that can be due is a RAISED allowance — an admin
        # override or a Branch Pack set mid-period — topped up by the difference. A one-time
        # key tops up only if its grant actually happened (granted > 0) or an admin set the
        # number for this org explicitly: a SUPPRESSED trial grant (lapsed payer, repeat
        # company domain) has granted == 0 < allowance and must stay suppressed.
        if allowance <= granted or not (recurring or granted > 0 or explicit_override):
            return None, None
        delta = allowance - granted
        wallet.plan_credits_granted = allowance
        wallet.plan_credits_remaining = int(wallet.plan_credits_remaining or 0) + delta
        if not recurring and wallet.plan_credits_once_at is None:
            wallet.plan_credits_once_at = datetime.utcnow()
        return _grant_plan_credits(
            db, wallet, delta,
            f"{label} — allowance raised to {allowance:,}: +{delta:,} credits this period",
        ), None

    if recurring and _period_key_live(stored):
        # A plan change INSIDE a paid period whose grant is still live: an upgrade, a
        # downgrade, or a re-buy that re-anchored the period. Top up to the new tier only —
        # max(0, new − already granted this period) — and keep the period's high-water mark
        # at max(old, new). Granting the full new allowance here (the old behaviour, because
        # the plan is part of the key) let Starter → Team → Starter → Team inside one month
        # mint a full Team allowance on every hop. Nothing expires either: the period the
        # unspent remainder belongs to has not ended, and the remainder stays this period's.
        delta = max(0, allowance - granted)
        wallet.plan_credits_period = period_key
        wallet.plan_credits_granted = max(granted, allowance)
        wallet.plan_credits_remaining = int(wallet.plan_credits_remaining or 0) + delta
        return _grant_plan_credits(
            db, wallet, delta,
            f"{label} plan — +{delta:,} credits for the rest of this period (plan changed)",
        ), None

    # A genuine new period: a renewal, the first grant, or a move onto / off the one-time
    # trial key.
    #
    # "Once" must mean once per ORGANIZATION, not once per consecutive stretch on the plan.
    # `plan_credits_period` only remembers the LATEST key, so sandbox -> paid -> lapse walks
    # it sandbox:once -> starter:X -> sandbox:once and the equality guard above sees a
    # different value each time. A paid customer who lapses would be handed the trial
    # credits again on every lapse cycle, unboundedly. This timestamp is the durable record.
    # The sandbox grant is an ONBOARDING allowance for someone evaluating the product. An org
    # that has already paid us and then lapsed is not evaluating — handing it free credits
    # rewards churn, and it is the one case where the wallet's "never granted" marker is
    # legitimately empty (they went straight onto a paid tier and never held the sandbox).
    # A company whose email domain already used a trial (trial_domain_blocked) gets none
    # either; signup stamps the marker too, this is the belt to that brace.
    if not recurring and wallet.plan_credits_once_at is None and (
        bool(getattr(sub, "trial_domain_blocked", False)) or _has_ever_paid(db, organization_id)
    ):
        wallet.plan_credits_once_at = datetime.utcnow()

    suppress_grant = not recurring and wallet.plan_credits_once_at is not None

    granted_before = int(wallet.plan_credits_remaining or 0)
    # Expiry is a TIME event, not a key-change event. The key also changes on an upgrade or
    # an early renewal, and clawing back there would delete allowance the customer has
    # already paid for and not yet used — the moment they gave us more money. So the
    # remainder is only forfeited once the period it belonged to has actually elapsed.
    if not PLAN_CREDITS_ROLLOVER and granted_before > 0 and _period_key_elapsed(stored):
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

    txn = _grant_plan_credits(
        db, wallet, allowance,
        f"{label} plan — {allowance:,} credits included this month" if recurring
        else f"{label} — {allowance:,} credits included",
    )
    return txn, (suppress_grant if not recurring else None)


def _sync_read_allowance(
    db: Session,
    wallet: models.EnterpriseCreditWallet,
    sub,
    organization_id: int,
    *,
    period_key: str,
    recurring: bool,
    allowance: int,
    explicit_override: bool,
    once_suppressed: Optional[bool],
) -> None:
    """The reads half of sync_plan_credits: the same three rules on `reads_period`.

    Reads are a counter pair, not a ledger: `reads_granted` is this period's allowance
    (raised to the high-water mark on a mid-period plan change, exactly like credits) and
    `reads_used` what uploads have consumed. A genuine new period resets used to 0 — there
    is no rollover, so nothing has to be clawed back.
    """
    from app import enterprise_billing as billing

    if allowance == billing.UNLIMITED:
        # Only ENTERPRISE_FREE reports unlimited reads, and it never reaches here; if a
        # future limit ever does, there is simply nothing to meter.
        return
    allowance = max(0, int(allowance or 0))
    stored = wallet.reads_period or ""
    granted = int(wallet.reads_granted or 0)

    if stored == period_key:
        # Same period: a raised allowance (override / Branch Pack) tops up now; a lowered one
        # takes nothing back. Same suppressed-trial guard as credits.
        if allowance > granted and (recurring or granted > 0 or explicit_override):
            wallet.reads_granted = allowance
        return

    if recurring and _period_key_live(stored):
        # Plan change inside a live paid period: raise to the new tier, keep what was used.
        wallet.reads_period = period_key
        wallet.reads_granted = max(granted, allowance)
        return

    if not recurring:
        suppressed = once_suppressed
        if suppressed is None:
            # The credit key was already on this one-time key (a wallet from before reads
            # existed): decide from the durable facts instead. A reads key that last held a
            # PAID period, a repeat company domain or any past payment all mean this org is
            # not evaluating the product for the first time.
            suppressed = (
                bool(getattr(sub, "trial_domain_blocked", False))
                or _key_period_start(stored) is not None
                or _has_ever_paid(db, organization_id)
            )
        if suppressed:
            allowance = 0

    wallet.reads_period = period_key
    wallet.reads_granted = allowance
    wallet.reads_used = 0


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


def plan_credits_state(db: Session, organization_id: int, *, read_only: bool = False) -> dict:
    """The allowance panel: what this org's tier includes (overrides and Branch Packs
    applied), how much of it is left, and when it refreshes. Read-only — call
    `sync_plan_credits` first if a grant may be due."""
    from app import enterprise_billing as billing

    wallet = wallet_snapshot(db, organization_id) if read_only else get_or_create_wallet(db, organization_id, commit=False)
    sub = billing.subscription_snapshot(db, organization_id) if read_only else billing.get_or_create_org_subscription(db, organization_id, commit=False)
    plan_key = billing.effective_plan_key(sub)
    # effective_limits, not included_credits_for: the panel must show the number the grant
    # actually uses, or an org with a Branch Pack sees 1,200 "included" and receives 1,400.
    limits = billing.effective_limits(db, organization_id)
    allowance = int(limits["included_credits"] or 0)
    recurring = bool(limits["credits_recur"])
    renews_at = None
    if recurring:
        # The sub-period's own end: 30 days after its start, except a yearly coverage's last
        # sub-period, which runs to the coverage end (see _coverage_bounds).
        renews_at = _period_bounds_for(sub, plan_key)[1]
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


# ---------------------------------------------------------------------------
# Monthly AI reading allowance ("reads")
#
# Every upload's free text extraction — what the assistant, Deep Scan and the interview
# officer later read instead of the raw file — is metered here, one read per 15-page block
# (gemini_service.enterprise_read_units). The allowance is granted by sync_plan_credits
# alongside the credits, on the same period key. When it runs out, or AI is paused, the
# upload is still STORED, just not read: the router marks it read_status="not_read" and
# offers "Read now" once allowance is back. A paid document check never consumes reads.
# ---------------------------------------------------------------------------

def _reads_payload(sub, wallet, limits: dict) -> dict:
    from app import enterprise_billing as billing

    granted = int(getattr(wallet, "reads_granted", 0) or 0)
    used = int(getattr(wallet, "reads_used", 0) or 0)
    plan_key = limits["plan"]
    recurring = bool(limits["credits_recur"])
    period_ends_at = None
    if recurring:
        period_ends_at = _period_bounds_for(sub, plan_key)[1]
    elif billing.normalize_plan_key(getattr(sub, "plan", None)) == billing.SANDBOX_PLAN:
        # The trial's reads are granted once and last for the trial.
        period_ends_at = _naive(getattr(sub, "trial_ends_at", None))
    return {
        "granted": granted,
        "used": used,
        "remaining": max(0, granted - used),
        "period_ends_at": period_ends_at,
        "period_key": getattr(wallet, "reads_period", None),
        "monthly_allowance": int(limits["monthly_reads"]),
        "recurring": recurring,
        "unlimited": False,
        "pages_per_read": DOCUMENT_BLOCK_PAGES,
        "enforced": ENFORCE,
    }


def _unlimited_reads_payload() -> dict:
    from app import enterprise_billing as billing

    return {
        "granted": 0, "used": 0, "remaining": None, "period_ends_at": None,
        "period_key": None, "monthly_allowance": billing.UNLIMITED, "recurring": False,
        "unlimited": True, "pages_per_read": DOCUMENT_BLOCK_PAGES, "enforced": False,
    }


def reads_state(db: Session, organization_id: int, *, read_only: bool = False) -> dict:
    """The reading allowance: {granted, used, remaining, period_ends_at} plus period_key,
    monthly_allowance (overrides and Branch Packs applied), recurring, unlimited and
    pages_per_read. `remaining` is None only when reads are unmetered (ENTERPRISE_FREE).

    read_only=True is a PURE READ — no row is created, nothing is granted or flushed. It
    must stay that way: enterprise_billing.build_subscription_state calls it from inside
    request paths with uncommitted work (enforce_client_limit_or_402), and it must never call
    back into build_subscription_state, which would recurse. The default path first grants
    any due allowance (without committing — the caller owns the transaction).
    """
    from app import enterprise_billing as billing

    if billing.ENTERPRISE_FREE:
        return _unlimited_reads_payload()
    if read_only:
        wallet = wallet_snapshot(db, organization_id)
        sub = billing.subscription_snapshot(db, organization_id)
    else:
        _sync_plan_credits_quietly(db, organization_id)
        wallet = get_or_create_wallet(db, organization_id, commit=False)
        sub = billing.get_or_create_org_subscription(db, organization_id, commit=False)
    return _reads_payload(sub, wallet, billing.effective_limits(db, organization_id))


def consume_reads(db: Session, organization_id: int, reads: int, *, commit: bool = True) -> bool:
    """Take `reads` from this period's reading allowance, atomically.

    True  — consumed: go ahead and read the upload.
    False — not enough allowance left, or AI is paused: NOTHING was consumed, and the caller
            stores the upload unread (read_status="not_read").

    All-or-nothing on purpose: a caller that wants to read only what is left asks
    reads_state() for `remaining` and passes that as the reader's max_blocks instead. A
    count below 1 is read as 1 — a file is never free to read.

    The check-and-increment runs under the wallet's row lock (get_wallet_for_update), so two
    uploads landing together cannot both spend the last read. commit=True (the default)
    commits before returning, which also RELEASES that lock before the caller's model call:
    holding a FOR UPDATE through a 30-60 s read would queue every other wallet operation of
    the org behind one upload. With ENTERPRISE_CREDITS_ENFORCE=false (soft launch) reads are
    tracked but never refused, the same way credits may then go past zero.
    """
    from app import enterprise_billing as billing

    needed = _units(reads)
    if billing.ENTERPRISE_FREE:
        return True  # billing disabled: reading is unmetered
    if not _ai_allowed(db, organization_id):
        # Same gate as every AI path, but answered rather than raised: the upload itself must
        # still succeed for a paused org — only the reading is withheld.
        return False
    # A period that rolled since the last request must refill BEFORE we refuse — otherwise
    # the first upload of a new month is stored unread against last month's count.
    _sync_plan_credits_quietly(db, organization_id)
    wallet = get_wallet_for_update(db, organization_id)
    granted = int(wallet.reads_granted or 0)
    used = int(wallet.reads_used or 0)
    ok = (granted - used) >= needed or not ENFORCE
    if ok:
        wallet.reads_used = used + needed
    if commit:
        db.commit()
    return ok


def release_reads(
    db: Session,
    organization_id: int,
    reads: int,
    *,
    period_key: Optional[str] = None,
    commit: bool = True,
) -> int:
    """Give back reads that a FAILED read consumed (the reader errored before producing any
    text, so the upload ends read_status="failed"). Returns the reads actually released.

    Pass the `period_key` reads_state() reported before consuming, and nothing is released
    if the period has rolled since — the new period's count is not the one that was charged.
    Either way `reads_used` is floored at 0, so a release can never lift an org above its
    allowance.
    """
    wallet = get_wallet_for_update(db, organization_id)
    if period_key is not None and (wallet.reads_period or "") != str(period_key):
        if commit:
            db.commit()
        return 0
    used = int(wallet.reads_used or 0)
    released = min(_units(reads), used)
    wallet.reads_used = used - released
    if commit:
        db.commit()
    return released


# ---------------------------------------------------------------------------
# The trial's demo-call bonus
# ---------------------------------------------------------------------------

def grant_demo_call_bonus(
    db: Session,
    organization_id: int,
    user: Optional[models.User] = None,
    *,
    commit: bool = True,
) -> int:
    """Grant billing.TRIAL_DEMO_BONUS_CREDITS (default 50) once per organization — the bonus
    Rilono staff hand out after a demo call. Returns the credits granted: 0 if this org has
    already had it (or the bonus is configured to 0).

    The once-guard is a CONDITIONAL UPDATE on subscription.demo_bonus_granted_at, not a
    read-then-write: two admins clicking together, or a double-submitted form, must not both
    grant. The marker lives on the subscription (never reset by a plan change), unlike the
    wallet's grant keys, which every period change overwrites.

    The credits are a gift, not plan allowance: they are not added to plan_credits_remaining,
    so no period rollover ever expires them — and not counted as purchased either. It is not
    an AI call, so the AI-paused gate does not apply; an admin extending a lapsed trial may
    grant it in either order.
    """
    from app import enterprise_billing as billing

    amount = int(billing.TRIAL_DEMO_BONUS_CREDITS or 0)
    if amount <= 0:
        return 0
    sub = billing.get_or_create_org_subscription(db, organization_id, commit=False)
    claimed = (
        db.query(models.EnterpriseSubscription)
        .filter(
            models.EnterpriseSubscription.id == sub.id,
            models.EnterpriseSubscription.demo_bonus_granted_at.is_(None),
        )
        .update({"demo_bonus_granted_at": datetime.utcnow()}, synchronize_session=False)
    )
    if not claimed:
        return 0
    # The bulk UPDATE bypassed the identity map; make the next read see the stamp.
    db.expire(sub, ["demo_bonus_granted_at"])
    get_wallet_for_update(db, organization_id)  # serialize the balance write with spends
    add_credits(
        db, organization_id, amount,
        txn_type="bonus",
        description=f"Demo call bonus — {amount:,} credits",
        reference_type="demo_call_bonus",
        user=user,
        count_as_purchase=False,
        commit=False,
    )
    if commit:
        db.commit()
    return amount


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


def _grant_marker(wallet: models.EnterpriseCreditWallet) -> tuple:
    """Everything a grant can move without writing a ledger row: both period keys and both
    granted marks. Compared before/after a sync to decide whether there is work to commit."""
    return (
        wallet.plan_credits_period or "",
        int(wallet.plan_credits_granted or 0),
        wallet.reads_period or "",
        int(wallet.reads_granted or 0),
    )


def _sync_plan_credits_quietly(db: Session, organization_id: int, *, commit: bool = False) -> None:
    """Grant any due plan allowance (credits and reads) before a balance is read or spent.

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
        # plan_credits_period and can claw credits back, and a reads grant never writes a
        # ledger row at all. Those writes would be silently dropped on read-only paths, so the
        # work would be redone on every request and the claw-back would never stick. The
        # keys and granted marks are the reliable signal — db.dirty is already empty here
        # because the savepoint flushes on release.
        before = _grant_marker(get_or_create_wallet(db, organization_id, commit=False))
        with db.begin_nested():
            txn = sync_plan_credits(db, organization_id, commit=False)
        after = _grant_marker(get_or_create_wallet(db, organization_id, commit=False))
        if commit and (txn is not None or after != before):
            db.commit()
    except Exception:
        logger.exception("plan-credits: grant sync failed for org %s", organization_id)


def can_afford(db: Session, organization_id: int, action_key: str, *, units: int = 1) -> bool:
    """Whether the org may run `units` of a billable action right now. False while AI is
    paused (answered, not raised: this also feeds GET payloads such as a "can afford" chip,
    and the public client-facing gates that word their own 402)."""
    if not _ai_allowed(db, organization_id):
        return False
    if not ENFORCE:
        return True
    cost = action_cost(action_key, units)
    if cost <= 0:
        return True
    _sync_plan_credits_quietly(db, organization_id)
    wallet = get_or_create_wallet(db, organization_id, commit=False)
    return int(wallet.balance_credits) >= cost


def _unit_phrase(action: Optional[dict], units: int) -> str:
    """' (3 × 4 credits per 15 pages)' for a multi-unit charge, '' for a single one."""
    if not action or _units(units) <= 1:
        return ""
    return f" ({_units(units)} × {_action_price_label(action)})"


def enforce_action_or_402(
    db: Session,
    organization_id: int,
    action_key: str,
    *,
    units: int = 1,
    client_facing: bool = False,
) -> None:
    """Pre-check before running a billable AI action. Raises 402 while AI is paused, or when
    the wallet cannot cover `units` of the action (e.g. the 15-page blocks of a document).

    `client_facing=True` swaps the paused message for one the consultancy's own client can
    act on; the credits message is staff-only, so client surfaces should use can_afford and
    word their own refusal."""
    _ai_gate_or_402(db, organization_id, client_facing=client_facing)
    if not ENFORCE:
        return
    cost = action_cost(action_key, units)
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
            f"Not enough credits for {label}. It costs {cost} credits{_unit_phrase(action, units)} "
            f"and your balance is {int(wallet.balance_credits)}. Your plan's monthly credits "
            "refresh on renewal — top up your Rilono Credits wallet to continue now."
        ),
    )


def can_afford_units(db: Session, organization_id: int, action_key: str, units: int = 1) -> bool:
    """Whether the wallet can cover `units` of a billable action (e.g. N invited interviews)."""
    return can_afford(db, organization_id, action_key, units=units)


def enforce_units_or_402(db: Session, organization_id: int, action_key: str, units: int = 1) -> None:
    """Staff-facing pre-check before *issuing* N billable units (e.g. an interview link
    that lets a client take `units` interviews). Blocks sending a link the wallet can't
    fund, so the client never hits a dead 'contact your consultancy' wall. Raises 402
    with an explicit, staff-readable top-up message (this is never shown to clients) — and
    while AI is paused, because a link issued then would only ever reach that wall."""
    _ai_gate_or_402(db, organization_id)
    if not ENFORCE:
        return
    units = _units(units)
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
    units: int = 1,
    user: Optional[models.User] = None,
    reference_type: Optional[str] = None,
    reference_id: Optional[int] = None,
    description: Optional[str] = None,
    client_facing: bool = False,
    commit: bool = True,
) -> Optional[models.EnterpriseCreditTransaction]:
    """Debit the cost of `units` of a billable action. Raises 402 if AI is paused, or if
    enforced and unaffordable.

    The paused check runs even though callers pre-check: a charge is the last line, and
    several flows charge without an enforce_* call of their own (the public interview link,
    the client Copilot unlock, background document checks)."""
    _ai_gate_or_402(db, organization_id, client_facing=client_facing)
    units = _units(units)
    cost = action_cost(action_key, units)
    if cost <= 0:
        return None
    _sync_plan_credits_quietly(db, organization_id)
    wallet = get_wallet_for_update(db, organization_id)
    if ENFORCE and int(wallet.balance_credits) < cost:
        enforce_action_or_402(db, organization_id, action_key, units=units, client_facing=client_facing)
    action = get_action(action_key)
    balance_before = int(wallet.balance_credits)
    _spend_from_wallet(wallet, cost)
    default_description = action["label"] if action else action_key
    if action and units > 1:
        default_description = f"{default_description}{_unit_phrase(action, units)}"
    txn = _record_transaction(
        db, wallet=wallet, txn_type="debit", credits=-cost, action_key=action_key,
        description=(description or default_description),
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
# billable messages (≈ ₹5/message at the default 1 credit / 2 messages).
#
# Flow (mirrors deep_scan: enforce before the model call, charge after success):
#   1. copilot_turn_budget()      — read-mostly; refuses when neither free messages nor
#      credits are left, and otherwise returns the COST BUDGET the turn may spend (None =
#      unbounded). copilot_precheck_or_402() is the raising form of the same check.
#   2. run the model with that budget (enterprise_ai stops calling tools once the turn's
#      running cost reaches it, then forces the final answer).
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


def _copilot_out_of_messages_detail(cost: int) -> str:
    return (
        f"You've used today's {COPILOT_FREE_DAILY} free Rilono AI assistant messages. "
        f"Further messages cost {_plural(cost, 'credit')} per {_plural(COPILOT_MSGS_PER_CREDIT, 'message')}, "
        "and your wallet can't cover the next one. Top up your Rilono Credits to keep chatting."
    )


def copilot_turn_budget(db: Session, organization_id: int) -> dict:
    """The RESERVATION for one assistant turn: may it run, and how much may it spend?

    Returns {allowed, cost_budget_usd, reason, message, free_left, covered_units,
    max_units, msgs_per_credit}:
      * allowed=True, cost_budget_usd=None, reason=None — the free allowance plus the wallet
        can pay for the WORST-CASE turn (COPILOT_MAX_MSG_WEIGHT messages), so the turn runs
        unbounded, exactly as before.
      * allowed=True, cost_budget_usd=Decimal, reason="balance_limited" — they cannot. The turn
        still runs, but enterprise_ai must stop calling tools once its running cost reaches
        covered_units × COPILOT_TURN_COST_BUDGET_USD and answer from what it has. Without
        this a single "free" turn could fan out into eight messages' worth of work on an
        empty wallet, and the bill would land as unpayable debt.
      * allowed=False, reason="insufficient_credits" (+ message) — no free message left and
        not one bundle affordable: the caller answers 402 with `message`, as before.
    Raises 402 first while AI is paused, like every other precheck.

    covered_units = free messages left today + what the wallet's whole bundles buy, minus
    messages already accrued unpaid toward the next bundle (copilot_unbilled_msgs: those are
    owed first, so they are not the new turn's to spend). With nothing accrued this is the
    spec's free_left + affordable_bundles × COPILOT_MSGS_PER_CREDIT.
    """
    _ai_gate_or_402(db, organization_id)
    worst = COPILOT_MAX_MSG_WEIGHT if COPILOT_TURN_COST_BUDGET_USD > 0 else 1
    result = {
        "allowed": True, "cost_budget_usd": None, "reason": None, "message": None,
        "free_left": None, "covered_units": None, "max_units": worst,
        "msgs_per_credit": COPILOT_MSGS_PER_CREDIT,
    }
    if not ENFORCE:
        return result
    # Same rule as every other 402 gate: a renewal that landed since the last request
    # must credit BEFORE we refuse the message, or a paid-up org hits a top-up wall on
    # the day it renewed — and on this surface that wall is the Chrome extension.
    _sync_plan_credits_quietly(db, organization_id)
    wallet = get_or_create_wallet(db, organization_id, commit=False)
    free_left = max(0, COPILOT_FREE_DAILY - _copilot_used_today(wallet))
    result["free_left"] = free_left
    cost_each = action_cost(COPILOT_ACTION_KEY)
    if cost_each <= 0:
        return result  # messages are free: nothing to reserve
    bundles = max(0, int(wallet.balance_credits)) // cost_each
    owed = max(0, int(wallet.copilot_unbilled_msgs or 0))
    covered = free_left + max(0, bundles * COPILOT_MSGS_PER_CREDIT - owed)
    result["covered_units"] = covered
    if covered >= worst:
        return result
    if covered <= 0:
        result.update(
            allowed=False, reason="insufficient_credits",
            cost_budget_usd=Decimal("0"),
            message=_copilot_out_of_messages_detail(cost_each),
        )
        return result
    if COPILOT_TURN_COST_BUDGET_USD > 0:
        result["cost_budget_usd"] = Decimal(covered) * COPILOT_TURN_COST_BUDGET_USD
        result["reason"] = "balance_limited"
    return result


def copilot_precheck_or_402(db: Session, organization_id: int) -> None:
    """Pre-check before running a copilot message: the raising form of copilot_turn_budget.
    402 while AI is paused, or when there is neither a free message left today nor a bundle
    the wallet can pay for (raised BEFORE any Gemini tokens are spent). A turn the wallet can
    only partly cover passes — copilot_turn_budget's cost budget is what bounds it."""
    budget = copilot_turn_budget(db, organization_id)
    if not budget["allowed"]:
        raise HTTPException(status_code=402, detail=budget["message"])


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

    Refuses (402) while AI is paused, like every charge path: the precheck already did, so
    this only fires for a trial that expired during the turn itself.
    """
    _ai_gate_or_402(db, organization_id)
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

def staff_interview_preview_remaining(db: Session, organization_id: int, *, read_only: bool = False) -> int:
    wallet = wallet_snapshot(db, organization_id) if read_only else get_or_create_wallet(db, organization_id, commit=False)
    used = int(getattr(wallet, "interview_staff_previews_used", 0) or 0)
    return max(0, INTERVIEW_FREE_STAFF_PREVIEWS - used)


def staff_interview_next_is_free(db: Session, organization_id: int) -> bool:
    return staff_interview_preview_remaining(db, organization_id) > 0


def enforce_staff_interview_or_402(db: Session, organization_id: int) -> None:
    """Pre-check before a STAFF-run mock interview. 402 while AI is paused — a free preview
    is still a model call. Otherwise free while previews remain, then the normal
    mock_interview price (402 if unaffordable)."""
    _ai_gate_or_402(db, organization_id)
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
    if any remain (no charge); otherwise debits the normal mock_interview cost. Refuses
    (402) while AI is paused, like every charge path."""
    _ai_gate_or_402(db, organization_id)
    # Row-locked: two staff starting interviews together must not both take the last
    # free preview (a plain read here let both see `used < limit`).
    wallet = get_wallet_for_update(db, organization_id)
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

def infra_fee_state(db: Session, organization_id: int, *, currency: str | None = None, read_only: bool = False) -> dict:
    """Legacy infra-fee status. `retired` is always True and `fee_due` always False.

    Kept so an old cached SPA bundle that still reads `wallet.infra_fee` renders a dormant
    banner instead of throwing — and so the shape stays stable for the admin console.
    """
    try:
        code = money.normalize_currency(currency or CURRENCY, strict=True)
    except money.UnsupportedCurrency:
        code = money.DEFAULT_CURRENCY
    fee_minor = money.price_minor("infra_fee", code)
    wallet = wallet_snapshot(db, organization_id) if read_only else get_or_create_wallet(db, organization_id, commit=False)
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
            # of the currency they were bought in — a Deep Scan costs the same credits either way.
            "value_inr": paise_to_rupees(credits_to_paise(total)),
            "is_popular": pkg["is_popular"],
            "currency": code,
            "price_options": money.price_options(f"credits_{key}"),
        })
    return payload


def actions_payload() -> list[dict]:
    """The per-action price list. `credits` is the price of ONE unit (kept under its old
    name: the SPA divides pack sizes by it); `unit` / `unit_label` / `price_label` say what a
    unit is — "4 credits per 15 pages" for a document check, "1 credit per 2 messages" for
    the assistant — so no surface has to hardcode that a price is per block or per bundle.
    The per-unit limits a price depends on (pages per block, documents per scan, questions
    per interview, messages per bundle / per client link) ride along for the same reason."""
    payload = []
    for key, action in ACTIONS.items():
        payload.append({
            "key": action["key"],
            "label": action["label"],
            "description": action["description"],
            "credits": action["credits"],
            "price_inr": paise_to_rupees(credits_to_paise(action["credits"])),
            "price_display": format_inr(credits_to_paise(action["credits"])),
            "unit": action.get("unit"),
            "unit_label": action.get("unit_label"),
            "price_label": _action_price_label(action),
            "per_unit": action.get("unit") in {"block", "bundle"},
            "pages_per_unit": action.get("pages_per_unit"),
            "messages_per_unit": action.get("messages_per_unit"),
            "free_daily_messages": action.get("free_daily_messages"),
            "max_documents": action.get("max_documents"),
            "max_questions": action.get("max_questions"),
            "messages_included": action.get("messages_included"),
            "valid_days": action.get("valid_days"),
        })
    return payload


def wallet_state(db: Session, organization_id: int, *, currency: str | None = None, read_only: bool = False) -> dict:
    """Render the wallet; read-only views preserve the stored balance and grant period."""
    if read_only:
        with db.no_autoflush:
            return _wallet_state(db, organization_id, currency=currency, read_only=True)
    return _wallet_state(db, organization_id, currency=currency)


def _wallet_state(db: Session, organization_id: int, *, currency: str | None = None, read_only: bool = False) -> dict:
    """Wallet + catalogue, with all real CHARGES priced in `currency`.

    Credits themselves stay an INR-denominated unit of account (1 credit = ₹10) whatever
    currency they were bought in — a Deep Scan costs the same credits everywhere — so the
    *_inr fields keep their INR meaning. Only the things an org actually pays for
    (packages, infra fee) are re-priced.
    """
    try:
        code = money.normalize_currency(currency or CURRENCY, strict=True)
    except money.UnsupportedCurrency:
        code = money.DEFAULT_CURRENCY
    from app import enterprise_billing as billing

    # Every entry into the Credits screen is also the moment a due allowance should land,
    # so the balance the user is looking at is never one renewal behind.
    if not read_only:
        _sync_plan_credits_quietly(db, organization_id, commit=True)
    wallet = wallet_snapshot(db, organization_id) if read_only else get_or_create_wallet(db, organization_id, commit=False)
    balance = int(wallet.balance_credits)
    # Both are pure reads (the grant above already ran), so the read-only view and the
    # default view render the same stored state identically.
    reads = reads_state(db, organization_id, read_only=True)
    ai = billing.ai_access_state(db, organization_id)
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
        "low_balance": balance < LOW_BALANCE_CREDITS,
        "low_balance_threshold": LOW_BALANCE_CREDITS,
        # The shared AI-paused gate, as a banner: while true every AI action (and a top-up)
        # answers 402, and the wallet is read-only until the plan is chosen or renewed.
        "ai_paused": not ai["allowed"],
        "ai_paused_reason": ai["reason"],
        "ai_paused_message": ai["message"],
        "actions": actions_payload(),
        # The monthly AI reading allowance (free upload reading, in 15-page blocks).
        "reads": reads,
        # What the org's plan includes each month and how much of it is left. This is the
        # primary "where do credits come from" panel now; top-ups are overage.
        "plan_credits": plan_credits_state(db, organization_id, read_only=read_only),
        # Retired — always dormant. Kept so a stale cached SPA bundle does not break.
        "infra_fee": infra_fee_state(db, organization_id, currency=code, read_only=read_only),
        "staff_interview_previews": {
            "free": INTERVIEW_FREE_STAFF_PREVIEWS,
            "remaining": staff_interview_preview_remaining(db, organization_id, read_only=read_only),
        },
        # What an agency gets without spending a credit. Surfaced on the pricing
        # tab so the free tier is visible next to the prices, not buried in the
        # per-action descriptions.
        "free_tier": {
            "deep_scans_per_client": DEEP_SCAN_FREE_SCANS_PER_CLIENT,
            "deep_scans_monthly_cap": DEEP_SCAN_FREE_MONTHLY_ORG_CAP,
            "interview_previews": INTERVIEW_FREE_STAFF_PREVIEWS,
            "interview_previews_left": staff_interview_preview_remaining(db, organization_id, read_only=read_only),
            "copilot_msgs_daily": COPILOT_FREE_DAILY,
            "copilot_msgs_left_today": max(0, COPILOT_FREE_DAILY - _copilot_used_today(wallet)),
            "copilot_msgs_per_credit": COPILOT_MSGS_PER_CREDIT,
            # Upload reading is free up to the plan's reads allowance (not a credit spend).
            "reads_allowance": reads["monthly_allowance"],
            "reads_left": reads["remaining"],
            "pages_per_read": DOCUMENT_BLOCK_PAGES,
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
        db.query(
            SP.amount_paise, SP.tax_paise, SP.currency, SP.refunded_amount_paise,
            SP.base_amount_paise, SP.fx_rate_used,
        )
        .filter(SP.status.in_(REVENUE_PAYMENT_STATUSES))
        .all()
    )
    plan_gross_paise = 0
    plan_tax_paise = 0
    plan_refunded_paise = 0
    plan_payment_count = 0
    for amount, tax, cur, refunded, base_amount, fx_rate in plan_rows:
        plan_payment_count += 1
        if (cur or "INR").strip().upper() == "INR":
            # Prefer the settlement figure even for INR (charged == settled, so it is
            # normally identical) because a webhook-first mandate seed row is stamped
            # base 0: the money lives on the webhook-created renewal row, and summing
            # the shell's amount_paise here counted that first charge twice.
            charged = _money_paise(base_amount) if base_amount is not None else _money_paise(amount)
            if charged <= 0:
                continue
            plan_gross_paise += max(0, charged - _money_paise(tax))
            plan_tax_paise += _money_paise(tax)
            # A refund is issued against the gross charge, which included GST. Only the
            # ex-tax portion was ever counted as revenue, so only that portion may be
            # reversed out — subtracting the full refund would understate revenue by the
            # tax we also returned.
            ref = min(_money_paise(refunded), charged)
            if ref:
                plan_refunded_paise += int(round(ref * (charged - _money_paise(tax)) / charged))
            continue
        # Non-INR plan sale: a zero-rated export (tax 0), so the settled INR figure IS the
        # ex-tax revenue. Same settlement rule as _kind_money above — only Razorpay's own
        # base_amount may be summed; a row whose figure hasn't landed contributes 0 and is
        # reported by the unsettled counter below rather than silently dropped.
        if base_amount is None:
            continue
        plan_gross_paise += max(0, _money_paise(base_amount))
        # Refunds are recorded in the row's own currency; scale by the payment's own
        # settlement rate (never our own FX) so a $39 refund is not subtracted as paise.
        ref = min(_money_paise(refunded), _money_paise(amount))
        if ref and fx_rate is not None:
            plan_refunded_paise += int(round(float(ref) * float(fx_rate)))
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
    ) + int(
        # The plan table can hold foreign rows too now — same rule, same counter.
        db.query(func.count(SP.id))
        .filter(
            SP.status.in_(REVENUE_PAYMENT_STATUSES),
            SP.base_amount_paise.is_(None),
            func.upper(func.coalesce(SP.currency, "INR")) != "INR",
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
        # Margin against what a DEBIT ROW actually earned, not the per-unit list price: one
        # row is a whole document check (several 15-page blocks) or several assistant
        # bundles, while avg_cost_paise is per row. Comparing a per-row cost with a per-block
        # price reported a profitable 60-page check as a loss.
        avg_price_paise = int(revenue_paise / units) if units > 0 else price_paise
        action_margin_pct = (
            round(((avg_price_paise - avg_cost_paise) / avg_price_paise) * 100, 1) if avg_price_paise > 0 else None
        )
        per_action.append({
            "key": key,
            "label": action["label"],
            "price_credits": action["credits"],
            "price_paise": price_paise,
            "price_display": format_inr(price_paise),
            "unit_label": action.get("unit_label"),
            "avg_price_per_unit_paise": avg_price_paise,
            "avg_price_per_unit_display": format_inr(avg_price_paise),
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
