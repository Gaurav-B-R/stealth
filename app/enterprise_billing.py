"""
Per-organization subscription billing for the Rilono enterprise platform (B2B).

Consultancies self-serve onto a tier. Since 2026-10-22 a tier is sized by OPEN student
files, not by every client ever entered, and caps four things — staff seats, open files,
the AI credits included each period, and the AI document "reads" included each period —
and the credit/read allowances are what tie this module to app/enterprise_credits.py:

    | Tier (internal key)          | Price/month | Seats | Open files | AI credits     | AI reads      |
    | 14-day free trial (sandbox)  | ₹0          |     3 |         15 | 50 once (+50*) | 50 for trial  |
    | Starter (starter)            | ₹1,499      |     5 |         40 | 150 / month    | 150 / month   |
    | Team (growth)                | ₹3,999      |    25 |        150 | 450 / month    | 500 / month   |
    | Multi-branch (scale)         | ₹9,999      |    50 |        500 | 1,200 / month  | 1,000 / month |
    (* +50 once, granted by Rilono staff after a demo call.)  Yearly = 10 × monthly.

Every number above is a default: each is env-overridable below, and Branch Packs and
per-org admin overrides adjust them per organization (see effective_limits). Nothing in
copy may restate them by hand — the feature bullets are generated from these constants.

Things about that table that are load-bearing:

  1. PRICES ARE EX-TAX. The listed number is the taxable subtotal; checkout charges
     subtotal + GST at ENTERPRISE_GST_PERCENT (see app/money.py::quote_with_tax), and at
     0% there is no tax line at all. Anything that renders a price must render the subtotal
     and money.tax_note(currency) ("+ GST" only while a rate is set); anything that creates
     a Razorpay order must send the total. `checkout_quote()` is the single place that
     produces both.

  2. INCLUDED CREDITS AND READS ARE GRANTED, NOT SIMULATED. Each billing period the org's
     wallet receives the allowance exactly once — see app/enterprise_credits.py. This
     module only declares the numbers (effective_limits).

  3. OPEN FILES, NOT ALL CLIENTS. Only clients in a stage with is_open=True in
     app/enterprise_catalog.py hold a slot; Approved, Rejected, Closed and On Hold do not.
     Going over is allowed for a grace window (FILE_LIMIT_GRACE_DAYS) so a busy month is
     never a hard wall, and a REOPEN is an add — otherwise close→add→reopen walks past it.

  4. THE TRIAL IS A REAL WORKSPACE THAT STOPS, NOT ONE THAT DISAPPEARS. At day 15 it stops
     accepting new clients and seats AND every AI path pauses (ai_access_state); everything
     already in it stays readable, so an evaluation that lapses never destroys data. A paid
     plan that lapses pauses AI the same way.

  5. FEATURES ARE GATED BY TIER ONLY FOR OFFICES/ROLES/BRANCH REPORTING. Every plan gets
     every AI feature. Creating/editing offices and custom roles, and per-branch reporting,
     are Team and Multi-branch only (and the live trial, which is an evaluation of Team).
     Existing offices/roles on a lower plan keep working — only new/edit is refused.

Razorpay order creation / verification lives in the enterprise router; this module owns
the plan catalog, the trial/lapse logic, limit and feature enforcement, the AI-paused gate
and the charge-currency rule. Prices themselves live in app/money.py's PRICE_BOOK (the
single source of truth for money), never here.

HISTORY: this replaced the "free CRM up to 50 students + ₹999/month infrastructure server
fee + purely prepaid credits" model on 2026-08-02, and was re-cut on 2026-10-22 from
Starter ₹2,999 (10 seats / 100 clients / 1,000 credits) / Growth ₹6,999 / Scale ₹14,999,
whose included credits earned ₹1.50–3.00 each against AI actions costing more than that.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app import enterprise_catalog as catalog
from app import models
from app import money


logger = logging.getLogger(__name__)

UNLIMITED = -1

# The free evaluation tier. `TRIAL_PLAN` is retained as an alias because rows written by
# the previous model carry plan="trial" verbatim; `normalize_plan_key` maps those (and the
# retired starter/growth/scale limits) onto the current catalog rather than migrating data.
SANDBOX_PLAN = "sandbox"
TRIAL_PLAN = SANDBOX_PLAN
LEGACY_TRIAL_KEYS = ("trial", "free")

# Input aliases for the customer-facing names. Internal keys never change — DB rows,
# Razorpay notes and the cached Razorpay plans all carry starter/growth/scale — but a
# request (or an admin) saying "team" or "multi-branch" must reach the same tier rather
# than falling through to the sandbox the way an unknown key does.
PLAN_ALIASES = {
    "trial": SANDBOX_PLAN,
    "free": SANDBOX_PLAN,
    "free_trial": SANDBOX_PLAN,
    "team": "growth",
    "multi_branch": "scale",
    "multibranch": "scale",
}

DEFAULT_TRIAL_DAYS = int(os.getenv("ENTERPRISE_TRIAL_DAYS", "14"))


def _int_env(env_key: str, default_value: int) -> int:
    raw = os.getenv(env_key, "").strip()
    if not raw:
        return default_value
    try:
        value = int(raw)
        return value if value >= 0 else default_value
    except ValueError:
        return default_value


def _bool_env(env_key: str, default_value: bool) -> bool:
    raw = os.getenv(env_key, "").strip().lower()
    if not raw:
        return default_value
    return raw in {"1", "true", "yes", "on"}


# --- Trial extras -------------------------------------------------------------------------
# The "demo call" bonus: Rilono staff grant this ONCE per org after a demo (admin console →
# credits/adjust kind=demo_call_bonus; enterprise_credits.grant_demo_call_bonus does the
# grant and stamps EnterpriseSubscription.demo_bonus_granted_at). Declared here because it
# is part of what the trial card promises.
TRIAL_DEMO_BONUS_CREDITS = _int_env("ENTERPRISE_TRIAL_DEMO_BONUS_CREDITS", 50)

# --- Branch Packs ---------------------------------------------------------------------------
# For networks above the top tier's open-file limit. Sold by invoice and set per org by an
# admin (EnterpriseSubscription.branch_packs); each pack adds this block on top of the plan
# (or on top of an admin override). Packs ride on a PAID entitlement only — see _limits_for.
BRANCH_PACK_FILES = _int_env("ENTERPRISE_BRANCH_PACK_FILES", 100)
BRANCH_PACK_SEATS = _int_env("ENTERPRISE_BRANCH_PACK_SEATS", 10)
BRANCH_PACK_CREDITS = _int_env("ENTERPRISE_BRANCH_PACK_CREDITS", 200)
BRANCH_PACK_READS = _int_env("ENTERPRISE_BRANCH_PACK_READS", 200)

# --- Open-file over-limit grace --------------------------------------------------------------
# An add that would put open files above the limit is still allowed while the org has been
# over for fewer than this many days (the clock starts at the first such add and is stored
# on the subscription). 0 = hard cap. Seats have no grace: a seat is a login, and an extra
# login cannot be "closed" the way a finished file can.
FILE_LIMIT_GRACE_DAYS = _int_env("ENTERPRISE_FILE_LIMIT_GRACE_DAYS", 14)

# --- The shared "AI paused" gate ----------------------------------------------------------------
# When true (default), an expired trial or a lapsed paid plan refuses every AI path with a
# 402 before any model call. The kill-switch exists so a mis-fire can be undone by config;
# it does NOT reopen adding clients/seats, which the expiry also stops.
AI_PAUSE_ON_EXPIRY = _bool_env("ENTERPRISE_AI_PAUSE_ON_EXPIRY", True)

# --- Yearly billing -------------------------------------------------------------------------------
# Sold only when explicitly enabled (default OFF): the owner gated yearly on the cheap-model
# document-reading quality test, because a year paid up front locks in an allowance whose AI
# cost is not yet proven. Yearly checkout is a one-off Razorpay ORDER (no mandate) covering
# YEARLY_PERIOD_DAYS; credits and reads are STILL granted per PLAN_PERIOD_DAYS sub-period
# inside that coverage (enterprise_credits._period_start_for walks monthly periods inside a
# long coverage), so a yearly buyer cannot draw twelve months of allowance on day one.
YEARLY_ENABLED = _bool_env("ENTERPRISE_YEARLY_ENABLED", False)
YEARLY_PERIOD_DAYS = _int_env("ENTERPRISE_YEARLY_PERIOD_DAYS", 365) or 365
_YEARLY_CYCLE_WORDS = {"yearly", "annual", "annually", "year", "12m"}


def _country_set_env(env_key: str, default_codes: tuple[str, ...]) -> frozenset[str]:
    raw = os.getenv(env_key, "")
    codes = {
        c.strip().upper() for c in re.split(r"[\s,;]+", raw or "")
        if len(c.strip()) == 2 and c.strip().isalpha()
    }
    if not codes:
        codes = set(default_codes)
    # India is the domestic market and the reason INR is sold at all; an override that
    # forgot it would bill every Indian consultancy in USD. Always included.
    codes.add("IN")
    return frozenset(codes)


# --- Currency regions ---------------------------------------------------------------------------
# Orgs in these countries are charged INR ONLY (the INR price, with a US$ estimate shown to
# the non-Indian ones); orgs anywhere else can NEVER be charged INR. The INR column of the
# price book was cut to fit Indian offices while the foreign ladders were not (₹1,499 vs $39),
# so letting a London consultancy pick INR would be a 60% discount — see app/money.py.
INR_REGION_COUNTRIES = _country_set_env(
    "ENTERPRISE_INR_REGION_COUNTRIES", ("IN", "NP", "BD", "LK", "NG", "GH", "KE")
)


# ---------------------------------------------------------------------------
# Plan catalog
# ---------------------------------------------------------------------------
#
# `price_product` names the app/money.py PRICE_BOOK entry holding the EX-TAX monthly
# subtotal — the price is NOT duplicated here, so there is exactly one number to change.
# `included_credits` / `max_reads` are the AI credit and reading allowances granted to the
# wallet each billing period (one-time for the sandbox; see `credits_recur`). `max_clients`
# is the OPEN-file limit (the key keeps its old name: the router, admin console and SPA all
# read it). `features_tier` selects TIER_FEATURES below. `features` (the card bullets) is
# generated from these numbers after the dict is built — never typed by hand.
PLANS = {
    SANDBOX_PLAN: {
        "key": SANDBOX_PLAN,
        # Built from DEFAULT_TRIAL_DAYS so ENTERPRISE_TRIAL_DAYS can never leave the card
        # promising a different length than the trial actually runs.
        "label": f"{DEFAULT_TRIAL_DAYS}-day free trial",
        "tagline": f"Try every feature for {DEFAULT_TRIAL_DAYS} days — no card needed",
        "price_product": None,          # free: never priced, never checked out
        "monthly_paise": 0,
        "yearly_paise": 0,
        "max_seats": _int_env("ENTERPRISE_SANDBOX_MAX_SEATS", 3),
        "max_clients": _int_env("ENTERPRISE_SANDBOX_MAX_CLIENTS", 15),
        "included_credits": _int_env("ENTERPRISE_SANDBOX_CREDITS", 50),
        "max_reads": _int_env("ENTERPRISE_SANDBOX_READS", 50),
        "credits_recur": False,         # granted ONCE for the trial, not per month
        # An ACTIVE trial evaluates Team (offices, roles, branch reporting). Once it expires
        # _feature_allowed refuses regardless of this tier.
        "features_tier": "team",
        "is_public": True,
        "is_popular": False,
        "purpose": f"{DEFAULT_TRIAL_DAYS}-day evaluation of every feature",
    },
    "starter": {
        "key": "starter",
        "label": "Starter",
        "tagline": "Owner-led or 1–5 person offices",
        "price_product": "plan_starter",
        "max_seats": _int_env("ENTERPRISE_STARTER_MAX_SEATS", 5),
        "max_clients": _int_env("ENTERPRISE_STARTER_MAX_CLIENTS", 40),
        "included_credits": _int_env("ENTERPRISE_STARTER_CREDITS", 150),
        "max_reads": _int_env("ENTERPRISE_STARTER_READS", 150),
        "credits_recur": True,
        "features_tier": "starter",
        "is_public": True,
        "is_popular": False,
        "purpose": "Owner-led or 1–5 person offices",
    },
    "growth": {
        "key": "growth",
        "label": "Team",
        "tagline": "Offices with 3–20 counsellors",
        "price_product": "plan_growth",
        "max_seats": _int_env("ENTERPRISE_GROWTH_MAX_SEATS", 25),
        "max_clients": _int_env("ENTERPRISE_GROWTH_MAX_CLIENTS", 150),
        "included_credits": _int_env("ENTERPRISE_GROWTH_CREDITS", 450),
        "max_reads": _int_env("ENTERPRISE_GROWTH_READS", 500),
        "credits_recur": True,
        "features_tier": "team",
        "is_public": True,
        "is_popular": True,
        "purpose": "Offices with 3–20 counsellors",
    },
    "scale": {
        "key": "scale",
        "label": "Multi-branch",
        "tagline": "Multi-branch firms with 10–40 counsellors",
        "price_product": "plan_scale",
        "max_seats": _int_env("ENTERPRISE_SCALE_MAX_SEATS", 50),
        "max_clients": _int_env("ENTERPRISE_SCALE_MAX_CLIENTS", 500),
        "included_credits": _int_env("ENTERPRISE_SCALE_CREDITS", 1_200),
        "max_reads": _int_env("ENTERPRISE_SCALE_READS", 1_000),
        "credits_recur": True,
        "features_tier": "team",
        "is_public": True,
        "is_popular": False,
        "purpose": "Multi-branch firms with 10–40 counsellors",
    },
}

PLAN_ORDER = [SANDBOX_PLAN, "starter", "growth", "scale"]
PAID_PLAN_KEYS = {"starter", "growth", "scale"}
CURRENCY = (os.getenv("ENTERPRISE_PLAN_CURRENCY", "INR").strip().upper() or "INR")

# The tier features that ARE gated by plan (owner decision 2026-10-22). Everything AI is on
# every plan. Kept as data so a future split (e.g. branch reporting on Starter) is one edit.
FEATURE_KEYS = ("branches", "custom_roles", "branch_reporting")
TIER_FEATURES = {
    "starter": frozenset(),
    "team": frozenset(FEATURE_KEYS),
}
_FEATURE_UPGRADE_COPY = {
    "branches": (
        "Adding or editing offices is part of the {team} plan. Upgrade to {team} to manage "
        "offices — your existing offices and their clients keep working."
    ),
    "custom_roles": (
        "Custom roles are part of the {team} plan. Upgrade to {team} to create or edit "
        "roles — everyone keeps the access they have today."
    ),
    "branch_reporting": (
        "Per-branch reporting is part of the {team} plan. Upgrade to {team} to filter and "
        "report by office."
    ),
}

# How long a paid MONTHLY period lasts, and the unit credits/reads are granted in for
# every cycle (a yearly plan is granted in PLAN_PERIOD_DAYS sub-periods — see YEARLY_*).
PLAN_PERIOD_DAYS = _int_env("ENTERPRISE_PLAN_PERIOD_DAYS", 30)

# Days past `current_period_end` that a paid tier keeps working before it lapses. Renewal
# is a manual re-purchase (checkout creates a one-off order, not an auto-debit mandate), so
# this is the dunning window: enough that a customer renewing a couple of days late is
# never cut off, short enough that a churned account stops accruing credit grants.
PLAN_GRACE_DAYS = _int_env("ENTERPRISE_PLAN_GRACE_DAYS", 3)

# Kill-switch that returns the platform to "free for everyone, no limits" — the state it
# was in between the infra-fee model and the tiered plans. Now defaults OFF: the tiers
# above ARE the live model. Set ENTERPRISE_FREE=true to disable billing in an emergency
# without a rollback; limits stop being enforced and no plan is offered for sale.
ENTERPRISE_FREE = os.getenv("ENTERPRISE_FREE", "false").strip().lower() in {"1", "true", "yes", "on"}


def _n(value: int) -> str:
    return f"{int(value):,}"


def _not_open_stage_labels() -> str:
    """'Approved, Rejected, Closed and On Hold' — from the catalog, so the "doesn't count"
    promise on the card can never name a stage that actually does count (or miss one)."""
    labels = [s["label"] for s in catalog.CLIENT_STAGES if not s["is_open"]]
    if len(labels) <= 1:
        return "".join(labels)
    return ", ".join(labels[:-1]) + " and " + labels[-1]


def _plan_features(key: str, plan: dict) -> list[str]:
    """The card bullets for one tier, built from the live constants.

    Every claim here is something the code enforces or grants: seats/files are the limits
    enforce_*_or_402 apply, credits/reads are what enterprise_credits grants, the office/
    role line is TIER_FEATURES, and Branch Packs are effective_limits. Do not add a bullet
    for something only a human promises (support SLAs etc.) — the card is a contract.
    """
    seats, files = plan["max_seats"], plan["max_clients"]
    credits, reads = plan["included_credits"], plan["max_reads"]
    if key == SANDBOX_PLAN:
        credit_line = f"{_n(credits)} AI credits at signup"
        if TRIAL_DEMO_BONUS_CREDITS > 0:
            credit_line += f", +{_n(TRIAL_DEMO_BONUS_CREDITS)} after a demo call"
        return [
            f"{_n(seats)} staff seats",
            f"{_n(files)} open student files",
            credit_line,
            f"{_n(reads)} AI document reads",
            "Every feature, including offices & custom roles",
            (
                "AI pauses when the trial ends — your data stays"
                if AI_PAUSE_ON_EXPIRY else "Your data stays when the trial ends"
            ),
        ]
    lines = [
        f"{_n(seats)} staff seats",
        f"{_n(files)} open student files",
        f"{_n(credits)} AI credits every month",
        f"{_n(reads)} AI document reads every month",
    ]
    if key == "starter":
        lines += [
            "Every AI feature — document checks, SOP & LOR studio, mock interviews, Deep Scan",
            "One office with the built-in roles",
        ]
    elif key == "growth":
        lines += [
            f"Everything in {PLANS['starter']['label']}",
            "Multiple offices, custom roles & per-branch reporting",
        ]
    elif key == "scale":
        lines += [f"Everything in {PLANS['growth']['label']}"]
        if BRANCH_PACK_FILES > 0:
            lines.append(
                f"Branch Packs above {_n(files)} files: +{_n(BRANCH_PACK_FILES)} files & "
                f"+{_n(BRANCH_PACK_SEATS)} staff each"
            )
    return lines


for _key, _plan in PLANS.items():
    _plan["features"] = _plan_features(_key, _plan)
del _key, _plan


# ---------------------------------------------------------------------------
# Grandfathering the orgs that predate paid plans
# ---------------------------------------------------------------------------
#
# Between the infra-fee model and these tiers the platform was free and UNCAPPED, so orgs
# signed up and grew past every number in the table above. Turning enforcement on without
# a ramp would, in one deploy, put a consultancy with 400 clients and 25 staff onto the
# sandbox's caps and 402 their next client create — a working product breaking at the
# moment we started charging for it, with no warning and nothing they did wrong.
#
# So limits are not enforced for a pre-existing org until GRACE_UNTIL. They keep working
# exactly as before, the UI shows them the deadline and their plan options, and on the day
# it lapses they are already on a plan. Nothing is ever deleted either way: over-cap orgs
# stop being able to ADD, they never lose what they have.
#
# Set ENTERPRISE_PLAN_GRACE_UNTIL to an ISO date (YYYY-MM-DD) to move the deadline, or to
# an empty string to enforce immediately for everyone.
_GRACE_RAW = os.getenv("ENTERPRISE_PLAN_GRACE_UNTIL", "2026-09-30").strip()
try:
    GRACE_UNTIL = datetime.strptime(_GRACE_RAW, "%Y-%m-%d") if _GRACE_RAW else None
except ValueError:
    # A typo must not silently mean "enforce on everyone today".
    GRACE_UNTIL = datetime(2026, 9, 30)

# Orgs whose subscription row predates this instant are the grandfathered population.
# Anyone signing up after it is on the published tiers from day one.
_CUTOVER_RAW = os.getenv("ENTERPRISE_PLAN_CUTOVER", "2026-08-02").strip()
try:
    PLAN_CUTOVER = datetime.strptime(_CUTOVER_RAW, "%Y-%m-%d") if _CUTOVER_RAW else datetime(2026, 8, 2)
except ValueError:
    PLAN_CUTOVER = datetime(2026, 8, 2)


def _as_naive(value):
    if value is None:
        return None
    return value.replace(tzinfo=None) if getattr(value, "tzinfo", None) else value


def is_grandfathered(sub, org_created_at=None) -> bool:
    """Whether this org predates paid plans and is still inside the grace window.

    AGE IS TAKEN FROM THE ORGANIZATION, NOT THE SUBSCRIPTION ROW. This is the whole
    correctness of the migration ramp. While ENTERPRISE_FREE was on,
    `build_subscription_state` short-circuited before `get_or_create_org_subscription`, so
    the free-era orgs — precisely the population the ramp exists to protect — have NO
    subscription row at all. The first read after this deploy creates one stamped with
    `created_at = now`, which is after PLAN_CUTOVER. Judging age by the subscription row
    would therefore mark every single legacy org as brand-new and cap it immediately, which
    is the exact failure the ramp was written to prevent.

    The subscription's own created_at is used only as a fallback for the case where the
    org's is unavailable.
    """
    if GRACE_UNTIL is None or datetime.utcnow() >= GRACE_UNTIL:
        return False
    # A row that has been paid for is not grandfathered — they chose a tier, so its caps
    # are the deal they agreed to.
    if normalize_plan_key(getattr(sub, "plan", None)) in PAID_PLAN_KEYS:
        return False
    created = _as_naive(org_created_at) or _as_naive(getattr(sub, "created_at", None))
    # No created_at at all (a row mid-flush) is treated as pre-existing: failing OPEN keeps
    # a working workspace working, where failing closed would 402 a live customer.
    return created is None or created < PLAN_CUTOVER


def _grandfathered_for(db: Session, sub, organization_id: int) -> bool:
    """is_grandfathered, querying the org's age only when the ramp can still apply — after
    GRACE_UNTIL (the normal case) this costs no query at all."""
    if GRACE_UNTIL is None or datetime.utcnow() >= GRACE_UNTIL:
        return False
    with db.no_autoflush:
        org_created_at = (
            db.query(models.EnterpriseOrganization.created_at)
            .filter(models.EnterpriseOrganization.id == int(organization_id))
            .scalar()
        )
    return is_grandfathered(sub, org_created_at)


def _free_subscription_state(db: Session, organization_id: int) -> dict:
    """Billing disabled (ENTERPRISE_FREE): no tier, no limits, nothing paused. Carries every
    key the paid shape does, so no consumer has to special-case the kill-switch."""
    open_count = open_client_count(db, organization_id)
    return {
        "plan": "free",
        "plan_label": "Free",
        "status": "active",
        "is_trial": False,
        "trial_expired": False,
        "trial_days_left": None,
        "trial_ends_at": None,
        "current_period_end": None,
        "max_clients": UNLIMITED,
        "max_seats": UNLIMITED,
        "clients_used": open_count,
        "open_files_used": open_count,
        "max_open_files": UNLIMITED,
        "clients_total": total_client_count(db, organization_id),
        "seats_used": active_seat_count(db, organization_id),
        "can_add_client": True,
        "can_add_seat": True,
        "files_over_limit": False,
        "files_over_limit_since": None,
        "files_grace_ends_at": None,
        "files_in_grace": False,
        "files_grace_days": FILE_LIMIT_GRACE_DAYS,
        "is_free_platform": True,
        "included_credits": 0,
        "credits_recur": False,
        "monthly_reads": UNLIMITED,
        "reads": {"granted": 0, "used": 0, "remaining": None, "period_ends_at": None,
                  "monthly_allowance": UNLIMITED, "unlimited": True},
        "features": {key: True for key in FEATURE_KEYS},
        "features_tier": "team",
        "ai_paused": False,
        "ai_paused_reason": None,
        "ai_paused_message": None,
        "yearly_enabled": False,
        "branch_packs": 0,
        "overrides": {"max_seats": None, "max_clients": None, "included_credits": None,
                      "monthly_reads": None},
        "trial_bonus_available": False,
        "trial_domain_blocked": False,
        "currency": CURRENCY,
    }


def normalize_plan_key(raw: str | None) -> str:
    """Map any stored or requested plan string onto a key that exists in the catalog.

    Rows predating 2026-08-02 carry plan="trial" (and _free_subscription_state emits
    "free"), and the retired catalogs reused the names starter/growth/scale for different
    limits. The names are deliberately reused rather than migrated: an org that was on
    "growth" is on the current Team tier, and the ONE thing that must never happen is an
    unknown key silently resolving to a paid tier's limits. Anything unrecognised lands on
    the sandbox, which is the most restrictive tier. Customer-facing names ("team",
    "multi-branch") resolve through PLAN_ALIASES.
    """
    key = re.sub(r"[\s\-]+", "_", str(raw or "").strip().lower())
    key = PLAN_ALIASES.get(key, key)
    return key if key in PLANS else SANDBOX_PLAN


def get_plan(plan_key: str | None) -> Optional[dict]:
    """The catalog entry for a plan key, or None. Legacy keys and aliases resolve; junk
    does not — callers such as the checkout endpoint rely on None to reject a bad request."""
    key = re.sub(r"[\s\-]+", "_", str(plan_key or "").strip().lower())
    key = PLAN_ALIASES.get(key, key)
    return PLANS.get(key)


# ---------------------------------------------------------------------------
# Billing cycle (monthly, and yearly when enabled)
# ---------------------------------------------------------------------------

def yearly_enabled() -> bool:
    """Whether yearly plans are on sale (ENTERPRISE_YEARLY_ENABLED; off by default)."""
    return bool(YEARLY_ENABLED) and not ENTERPRISE_FREE


def _is_yearly(cycle: str | None) -> bool:
    return str(cycle or "").strip().lower() in _YEARLY_CYCLE_WORDS


def normalize_billing_cycle(raw: str | None) -> str:
    """The cycle a REQUEST may buy: "yearly" only while yearly is on sale, else "monthly".

    This is the sales gate. Every endpoint that turns a client-supplied cycle into an order
    must pass it through here, so no request can be talked into a yearly order while yearly
    is switched off. (Historical rows may still say "yearly"; read their coverage with
    period_days_for, which deliberately does NOT gate.)"""
    if _is_yearly(raw) and yearly_enabled():
        return "yearly"
    return "monthly"


def period_days_for(cycle: str | None) -> int:
    """Coverage bought by one payment of `cycle`: YEARLY_PERIOD_DAYS for "yearly", else
    PLAN_PERIOD_DAYS. Not gated by yearly_enabled(): a yearly order created while yearly was
    on sale and verified after it was switched off must still get the year it paid for."""
    return int(YEARLY_PERIOD_DAYS) if _is_yearly(cycle) else int(PLAN_PERIOD_DAYS)


# ---------------------------------------------------------------------------
# Prices
# ---------------------------------------------------------------------------

def resolve_plan_currency(plan_key: str, currency: str | None = None) -> str:
    """The currency a plan can ACTUALLY be charged in — never merely the one requested.

    This exists to close a 100× overcharge. `CURRENCY` is env-driven
    (ENTERPRISE_PLAN_CURRENCY), and when the plan price book was INR-only, setting that
    env var to USD meant the amount stayed 299900 (paise) while the Razorpay order was
    created in USD — billing a ₹2,999 plan as $2,999. Price and currency must be resolved
    together, from the same lookup, or they can disagree; every caller therefore takes the
    currency from here rather than reading `CURRENCY` directly. The plan books carry the
    full launch ladder, so a requested launch currency resolves to itself; anything the
    book lacks still falls back to INR.

    NOTE: this answers "can this plan be priced in X", not "may this ORG be charged X" —
    that is charge_currency_for_org (the INR-region rule), which callers apply first.
    """
    plan = get_plan(plan_key)
    product = (plan or {}).get("price_product")
    code = (currency or CURRENCY or money.DEFAULT_CURRENCY).strip().upper()
    if not product:
        return money.DEFAULT_CURRENCY
    book = money.PRICE_BOOK.get(product) or {}
    return code if code in book else money.DEFAULT_CURRENCY


def plan_price_minor(plan_key: str, currency: str | None = None, billing_cycle: str = "monthly") -> int:
    """The EX-TAX list price for one period of `billing_cycle`, in the minor unit of the
    currency `resolve_plan_currency` settles on. Yearly = money.YEARLY_PRICE_MONTHS × the
    monthly price, in every currency. Sourced from money.PRICE_BOOK — the plan catalog never
    holds a price. Free plans and unknown keys return 0, which every caller treats as "not
    purchasable".

    `billing_cycle` is taken LITERALLY (so the cards can show the yearly price while yearly
    is not on sale); the sales gate is normalize_billing_cycle, applied by the caller."""
    plan = get_plan(plan_key)
    if not plan or not plan.get("price_product"):
        return 0
    code = resolve_plan_currency(plan_key, currency)
    monthly = int(money.price_minor(plan["price_product"], code))
    return money.yearly_minor(monthly) if _is_yearly(billing_cycle) else monthly


def plan_amount_paise(plan_key: str, billing_cycle: str | None = None) -> int:
    """Back-compat shim: the ex-tax list price in INR paise (monthly unless told otherwise).

    Pinned to INR explicitly (not CURRENCY): now that the plan books carry non-INR
    ladders, ENTERPRISE_PLAN_CURRENCY=USD would otherwise make this return cents while
    its remaining callers (the help KB's rupee price line) treat the figure as paise.

    NOTE FOR CALLERS: this is the LIST price, not the charged amount. A plan order must
    be created for `checkout_quote(...)["total_minor"]`, which adds any tax. Passing this
    figure to Razorpay undercharges every customer by the tax.
    """
    return plan_price_minor(plan_key, "INR", billing_cycle or "monthly")


def fallback_charge_currency(billing_currency: str | None, country_code: str | None) -> str:
    """The no-hint part of deciding what currency to charge an org in: the currency they
    were last billed in (if we can charge it) -> their country's currency -> INR.

    This is the RAW preference only. It does not know the INR-region rule, so its answer is
    not yet chargeable for an org outside India's region — use charge_currency_for_org (or
    region_charge_currency) for anything that decides a charge or a displayed quote.
    """
    stored = (billing_currency or "").strip()
    if stored and money.is_chargeable(stored):
        return money.normalize_currency(stored, strict=True)
    country = (country_code or "").strip().upper()
    if country:
        # Lazy import: routers.pricing imports nothing from this module, but keeping the
        # top-level import graph acyclic is why this lives here rather than at the top.
        from app.routers import pricing as pricing_fx
        guess = pricing_fx._COUNTRY_TO_CURRENCY.get(country)
        if guess and money.is_chargeable(guess):
            return money.normalize_currency(guess, strict=True)
    return money.DEFAULT_CURRENCY


def _norm_country(country_code: str | None) -> Optional[str]:
    code = str(country_code or "").strip().upper()
    return code if len(code) == 2 and code.isalpha() else None


def is_inr_region(country_code: str | None) -> bool:
    """Whether an org in `country_code` is charged INR (and only INR)."""
    code = _norm_country(country_code)
    return bool(code) and code in INR_REGION_COUNTRIES


def _ladder_currency_for_country(country_code: str) -> str:
    """The non-INR ladder currency for a country outside the INR region (USD if its own
    currency isn't one we charge in)."""
    from app.routers import pricing as pricing_fx

    guess = pricing_fx._COUNTRY_TO_CURRENCY.get(country_code)
    if guess and guess != "INR" and money.is_chargeable(guess):
        return money.normalize_currency(guess, strict=True)
    return "USD"


def region_charge_currency(candidate: str | None, country_code: str | None) -> str:
    """Clamp a candidate charge currency to the org's currency region.

      * INR-region country -> "INR", whatever the candidate (a buyer hint is ignored).
      * Known country outside the region -> the candidate, unless it is INR, which becomes
        that country's ladder currency (else USD). INR is not sold outside the region.
      * Unknown country -> the candidate as-is (INR allowed: the domestic default).
    """
    country = _norm_country(country_code)
    code = (candidate or money.DEFAULT_CURRENCY).strip().upper()
    if country and country in INR_REGION_COUNTRIES:
        return "INR"
    if country and code == "INR":
        return _ladder_currency_for_country(country)
    return code


def request_geo_country(request) -> Optional[str]:
    """The visitor country a fronting CDN attached to `request`, via the exact header logic
    of GET /api/pricing/geo (reused, not copied, so the two never disagree). None when
    there is no request or no usable header."""
    if request is None:
        return None
    try:
        from app.routers import pricing as pricing_fx

        return _norm_country((pricing_fx.detect_geo(request) or {}).get("country_code"))
    except Exception:
        logger.debug("geo country lookup failed", exc_info=True)
        return None


def charge_currency_for_org(db: Session, organization, hint: str | None, request=None) -> str:
    """Decide what currency to CHARGE (and quote) an organization in.

    Order: validate the buyer's hint strictly (an unknown or not-enabled code is a 400,
    never a silent coercion) -> candidate = hint, else the stored/country fallback
    (fallback_charge_currency) -> clamp to the org's currency region
    (region_charge_currency). The country is the org's own `country_code`; when that is
    missing, the request's CDN geo country; when both are unknown, INR stays allowed.

    `organization` may be the model or its id. Used for plan checkout, credit top-up
    checkout and every displayed quote, so the price a buyer sees is the price they pay.
    Only the CURRENCY is decided here — the amount always comes from the price book.
    """
    org = organization
    if isinstance(organization, int):
        org = db.get(models.EnterpriseOrganization, organization) if db is not None else None
    raw = (hint or "").strip()
    code: Optional[str] = None
    if raw:
        try:
            code = money.normalize_currency(raw, strict=True)
        except money.UnsupportedCurrency:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"We can't charge in {raw.upper()[:8]} yet. Supported: "
                    + ", ".join(money.supported_charge_currencies()) + "."
                ),
            )
    country = _norm_country(getattr(org, "country_code", None)) or request_geo_country(request)
    candidate = code or fallback_charge_currency(getattr(org, "billing_currency", None), country)
    return region_charge_currency(candidate, country)


def usd_estimate_minor(inr_minor: int) -> Optional[int]:
    """A whole-dollar US$ estimate (in cents) of an INR amount, for the non-Indian members
    of the INR region, who are charged INR but think in dollars. An ESTIMATE only — at the
    live/fallback FX rate of app/fx.py, rounded to the dollar — never a charge."""
    amount = int(inr_minor or 0)
    if amount <= 0:
        return None
    from app import fx

    try:
        rate = Decimal(str(fx.get_usd_to_inr()))
    except Exception:
        return None
    if rate <= 0:
        return None
    dollars = (Decimal(amount) / Decimal(100) / rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return max(1, int(dollars)) * 100


def _usd_estimate_display(cents: Optional[int]) -> Optional[str]:
    return f"≈ US{money.format_money(cents, 'USD')}" if cents else None


def included_credits_for(plan_key: str | None) -> int:
    """The PLAN's default AI credits per billing period (0 if none). Per-org overrides and
    Branch Packs are NOT applied — use effective_limits for what an org actually gets."""
    plan = get_plan(plan_key)
    return int(plan.get("included_credits") or 0) if plan else 0


def monthly_reads_for(plan_key: str | None) -> int:
    """The PLAN's default AI reads per period (see included_credits_for for the caveat)."""
    plan = get_plan(plan_key)
    return int(plan.get("max_reads") or 0) if plan else 0


def credits_recur_for(plan_key: str | None) -> bool:
    """Whether the allowances are granted every period (paid tiers) or once (sandbox)."""
    plan = get_plan(plan_key)
    return bool(plan.get("credits_recur")) if plan else False


def checkout_quote(
    plan_key: str,
    currency: str | None = None,
    *,
    discount_percent=None,
    billing_cycle: str = "monthly",
) -> dict:
    """The complete money breakdown for a plan purchase: list → discount → tax → total.

    The single place any plan price is turned into a payable amount. Order of operations
    is fixed and matters: a coupon reduces the TAXABLE value, so the discount is applied
    to the ex-tax subtotal and tax is computed on the reduced figure. Computing tax first
    would over-collect GST on money the customer never pays.

    `total_minor` is the only figure that may reach Razorpay; `list_minor` is the only one
    that may be displayed as the plan's price (alongside money.tax_note). `billing_cycle`
    is literal — pass it through normalize_billing_cycle first when it came from a request.
    """
    # Resolved, not requested — see resolve_plan_currency. `quote["currency"]` is what the
    # Razorpay order MUST be created in; callers must not fall back to CURRENCY.
    code = resolve_plan_currency(plan_key, currency)
    cycle = "yearly" if _is_yearly(billing_cycle) else "monthly"
    list_minor = plan_price_minor(plan_key, code, cycle)
    subtotal = list_minor
    applied_percent = None
    if discount_percent is not None:
        # Deliberately the coupon module's own function rather than the same arithmetic
        # written again here. The two differ in association — (a·b)/c versus a·(b/c) — and
        # with Decimal that can round apart by one minor unit on some percentages. The
        # checkout endpoint VALIDATES the coupon through apply_to_amount_or_400 and then
        # CHARGES what this returns, so a one-paise divergence between them is a real
        # (if small) mismatch between the amount approved and the amount taken. It is also
        # where the coupon cap (ENTERPRISE_COUPON_MAX_PERCENT) is applied.
        from app import enterprise_coupons

        applied_percent = min(
            Decimal(str(discount_percent)), enterprise_coupons.max_percent_off()
        )
        subtotal = enterprise_coupons.compute_discounted_amount_paise(
            list_minor, Decimal(str(discount_percent))
        )
    quote = money.quote_with_tax(subtotal, code)
    quote["list_minor"] = list_minor
    quote["list_display"] = money.format_money(list_minor, code)
    quote["discount_minor"] = list_minor - subtotal
    quote["discount_display"] = money.format_money(list_minor - subtotal, code)
    # The percent ACTUALLY taken off (capped) — what a payment row should record.
    quote["discount_percent"] = float(applied_percent) if applied_percent is not None else None
    quote["billing_cycle"] = cycle
    quote["period_days"] = period_days_for(cycle)
    quote["tax_note"] = money.tax_note(code)
    return quote


def _format_inr(paise: int) -> str:
    rupees = paise / 100.0
    if rupees == int(rupees):
        return f"₹{int(rupees):,}"
    return f"₹{rupees:,.2f}"


def trial_facts() -> dict:
    """What the free trial includes, for the public pricing endpoint and page tokens."""
    plan = PLANS[SANDBOX_PLAN]
    return {
        "label": plan["label"],
        "days": DEFAULT_TRIAL_DAYS,
        "max_seats": plan["max_seats"],
        "max_open_files": plan["max_clients"],
        "included_credits": plan["included_credits"],
        "demo_bonus_credits": TRIAL_DEMO_BONUS_CREDITS,
        "reads": plan["max_reads"],
        "ai_pauses_on_expiry": bool(AI_PAUSE_ON_EXPIRY),
        "features": list(plan["features"]),
    }


def branch_pack_facts() -> dict:
    """What one Branch Pack adds (sold by invoice; admin sets the count per org)."""
    return {
        "open_files": BRANCH_PACK_FILES,
        "seats": BRANCH_PACK_SEATS,
        "credits": BRANCH_PACK_CREDITS,
        "reads": BRANCH_PACK_READS,
    }


def public_plans_payload(currency: str | None = None, *, usd_estimate: bool = False) -> list[dict]:
    """The tier cards, priced in `currency` (any launch currency; INR when omitted).

    Every price field is the EX-TAX subtotal, and `tax_*`/`total_*` carry what checkout
    will actually charge, so a card can render "₹1,499/mo" + price_note and a breakdown
    without the frontend doing tax arithmetic of its own. `price_note` is "+ GST" only while
    a GST rate is set (money.tax_note) — never hardcode it in a template.

    Yearly fields are always present for paid tiers (the price is a fact even while yearly
    is not sold); `yearly_enabled` says whether it can be bought, and the legacy
    `yearly_paise` stays 0 until it can, so an old client's yearly branch renders nothing.

    `usd_estimate=True` adds a whole-dollar US$ estimate to INR cards (for the non-Indian
    members of the INR region; see charge_currency_for_org).

    Returns [] while ENTERPRISE_FREE is on — with billing disabled there is nothing to
    sell, and a price list nobody can buy from is worse than no price list.
    """
    if ENTERPRISE_FREE:
        return []
    requested = (currency or CURRENCY or money.DEFAULT_CURRENCY).strip().upper()
    code = requested if money.is_chargeable(requested) else money.DEFAULT_CURRENCY
    sell_yearly = yearly_enabled()
    files_note = f"{_not_open_stage_labels()} files don't count."
    payload = []
    for key in PLAN_ORDER:
        plan = PLANS[key]
        if not plan["is_public"]:
            continue
        quote = checkout_quote(key, code)
        monthly = quote["list_minor"]
        paid = bool(plan.get("price_product")) and monthly > 0
        yq = checkout_quote(key, code, billing_cycle="yearly") if paid else None
        yearly = yq["list_minor"] if yq else 0
        savings = (monthly * 12 - yearly) if yq else 0
        card = {
            "key": plan["key"],
            "label": plan["label"],
            "tagline": plan["tagline"],
            "purpose": plan["purpose"],
            # Ex-tax list price. `monthly_paise` keeps its legacy name (the deployed SPA
            # reads it) but is the minor unit of `currency`.
            "monthly_paise": monthly,
            "monthly_minor": monthly,
            "monthly_display": quote["list_display"],
            "currency": code,
            "is_free": monthly <= 0,
            # What checkout adds on top. tax_percent is 0 outside India and at a 0% rate.
            "tax_label": quote["tax_label"],
            "tax_percent": quote["tax_percent"],
            "tax_minor": quote["tax_minor"],
            "tax_display": quote["tax_display"],
            "total_minor": quote["total_minor"],
            "total_display": quote["total_display"],
            "price_note": (
                f"Free for {DEFAULT_TRIAL_DAYS} days" if monthly <= 0 else money.tax_note(code)
            ),
            # --- yearly ("2 months free") ---
            "yearly_enabled": sell_yearly,
            "yearly_minor": yearly,
            "yearly_display": yq["list_display"] if yq else None,
            "yearly_tax_minor": yq["tax_minor"] if yq else 0,
            "yearly_total_minor": yq["total_minor"] if yq else 0,
            "yearly_total_display": yq["total_display"] if yq else None,
            "yearly_savings_minor": savings,
            "yearly_savings_display": money.format_money(savings, code) if yq else None,
            "yearly_months_free": max(0, 12 - int(money.YEARLY_PRICE_MONTHS)) if yq else 0,
            # Legacy: non-zero only while yearly can actually be bought.
            "yearly_paise": yearly if sell_yearly else 0,
            # --- limits & allowances ---
            "max_clients": plan["max_clients"],
            "max_open_files": plan["max_clients"],
            "files_note": files_note,
            "max_seats": plan["max_seats"],
            "included_credits": plan["included_credits"],
            "credits_recur": plan["credits_recur"],
            "credits_note": (
                f"{_n(plan['included_credits'])} AI credits every month" if plan["credits_recur"]
                else f"{_n(plan['included_credits'])} AI credits at signup"
                + (f" (+{_n(TRIAL_DEMO_BONUS_CREDITS)} after a demo call)"
                   if key == SANDBOX_PLAN and TRIAL_DEMO_BONUS_CREDITS > 0 else "")
            ),
            "max_reads": plan["max_reads"],
            "monthly_reads": plan["max_reads"],
            "reads_note": (
                f"{_n(plan['max_reads'])} AI document reads every month" if plan["credits_recur"]
                else f"{_n(plan['max_reads'])} AI document reads for the trial"
            ),
            "features_tier": plan["features_tier"],
            "includes_branches": "branches" in TIER_FEATURES.get(plan["features_tier"], frozenset()),
            "is_popular": plan["is_popular"],
            "features": list(plan["features"]),
            "price_options": money.price_options(plan["price_product"]) if plan.get("price_product") else [],
            "trial_days": DEFAULT_TRIAL_DAYS if key == SANDBOX_PLAN else None,
            "demo_bonus_credits": TRIAL_DEMO_BONUS_CREDITS if key == SANDBOX_PLAN else 0,
        }
        if usd_estimate and code == "INR" and paid:
            m_est = usd_estimate_minor(quote["total_minor"])
            y_est = usd_estimate_minor(yq["total_minor"]) if yq else None
            card["usd_estimate"] = {
                "currency": "USD",
                "monthly_minor": m_est,
                "monthly_display": _usd_estimate_display(m_est),
                "yearly_minor": y_est,
                "yearly_display": _usd_estimate_display(y_est),
            }
        else:
            card["usd_estimate"] = None
        payload.append(card)
    return payload


def get_or_create_org_subscription(
    db: Session,
    organization_id: int,
    *,
    commit: bool = True,
) -> models.EnterpriseSubscription:
    sub = (
        db.query(models.EnterpriseSubscription)
        .filter(models.EnterpriseSubscription.organization_id == int(organization_id))
        .first()
    )
    if sub:
        return sub

    now = datetime.utcnow()
    sub = models.EnterpriseSubscription(
        organization_id=int(organization_id),
        plan=TRIAL_PLAN,
        status="trialing",
        trial_ends_at=now + timedelta(days=DEFAULT_TRIAL_DAYS),
    )
    db.add(sub)
    if commit:
        db.commit()
        db.refresh(sub)
    else:
        db.flush()
    return sub


def subscription_snapshot(db: Session, organization_id: int) -> models.EnterpriseSubscription:
    """Read the stored subscription, or return the unsaved defaults for a missing row."""
    with db.no_autoflush:
        sub = db.query(models.EnterpriseSubscription).filter(
            models.EnterpriseSubscription.organization_id == int(organization_id)
        ).first()
    if sub is not None:
        return sub
    now = datetime.utcnow()
    return models.EnterpriseSubscription(
        organization_id=int(organization_id), plan=TRIAL_PLAN, status="trialing",
        trial_ends_at=now + timedelta(days=DEFAULT_TRIAL_DAYS), created_at=now,
        cancel_at_period_end=False, branch_packs=0, trial_domain_blocked=False,
    )


def _is_trial_expired(sub: models.EnterpriseSubscription) -> bool:
    """Whether the sandbox trial has run out.

    Only ever true on the sandbox tier: a paid subscriber's `trial_ends_at` is a stale
    leftover from before they subscribed, and reading it for them would expire a paying
    customer on day 15.
    """
    if normalize_plan_key(sub.plan) != SANDBOX_PLAN:
        return False
    if not sub.trial_ends_at:
        return False
    ends = sub.trial_ends_at
    if getattr(ends, "tzinfo", None):
        ends = ends.replace(tzinfo=None)
    return ends < datetime.utcnow()


def _trial_still_running(sub) -> bool:
    """A future `trial_ends_at`, whatever the plan. Used only for a LAPSED paid row: an org
    that paid inside its first 14 days and lapsed before day 14 keeps the evaluation it
    would have had anyway, and an admin trial extension works for a lapsed org too."""
    ends = _as_naive(getattr(sub, "trial_ends_at", None))
    return bool(ends) and ends > datetime.utcnow()


def paid_period_expired(sub: models.EnterpriseSubscription) -> bool:
    """Whether a paid subscription's bought period has run out.

    THIS IS WHAT MAKES THE SUBSCRIPTION RECURRING. Checkout creates a one-off Razorpay
    ORDER, not a mandate, so nothing auto-debits and nothing external ever flips `status`
    away from "active" — the only two writes to it in the codebase both set it to "active".
    Gating solely on `status` therefore means one payment buys the tier forever, and
    (because the credit period key keeps advancing) mints a fresh allowance every 30 days at
    our cost. Expiry has to be derived from `current_period_end`.

    A short grace window absorbs the ordinary case of someone renewing a day or two late;
    it is deliberately generous, because cutting off a paying customer over a weekend is
    far worse than 3 extra days of service.
    """
    if normalize_plan_key(sub.plan) not in PAID_PLAN_KEYS:
        return False
    end = _as_naive(getattr(sub, "current_period_end", None))
    if not end:
        # A paid plan with no period end is a half-written row, not an entitlement.
        return True
    return (end + timedelta(days=PLAN_GRACE_DAYS)) < datetime.utcnow()


def effective_plan_key(sub: models.EnterpriseSubscription) -> str:
    """The plan whose limits currently apply.

    A paid tier applies only while it is BOTH active-status AND inside its paid period.
    Either failing drops the org to sandbox caps (read-mostly): they keep everything already
    in the workspace and stop being able to add to it — and, just as importantly, stop
    receiving the monthly credit allowance they are no longer paying for.
    """
    plan_key = normalize_plan_key(sub.plan)
    if plan_key in PAID_PLAN_KEYS:
        if str(sub.status or "").lower() not in {"active", "trialing"}:
            return SANDBOX_PLAN
        if paid_period_expired(sub):
            return SANDBOX_PLAN
    return plan_key


def _is_lapsed(sub, plan_key: str) -> bool:
    """A paid tier on the row whose entitlement has run out (effective plan fell back)."""
    subscribed = normalize_plan_key(getattr(sub, "plan", None))
    return subscribed in PAID_PLAN_KEYS and plan_key != subscribed


# ---------------------------------------------------------------------------
# Effective limits: plan defaults, per-org overrides, Branch Packs
# ---------------------------------------------------------------------------

def _override(value) -> Optional[int]:
    if value is None:
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


def _plus(base: int, extra: int) -> int:
    return base if base == UNLIMITED else int(base) + int(extra)


def _limits_for(sub, plan_key: str) -> dict:
    """The numbers that apply to this org right now, from an already-loaded row.

    Override REPLACES the plan's number; Branch Packs then ADD on top. Both ride on an
    entitlement, which is the subtle part:
      * Overrides apply unless the org is LAPSED. An admin sets them for a customer
        (a bigger trial, a negotiated paid deal); once a paid plan lapses the org must fall
        back to the bare sandbox numbers, or an override set for a paying customer keeps a
        churned account at its paid limits forever.
      * Branch Packs apply only while a PAID plan is in force: they are bought on top of a
        plan, and a lapsed or trial org has nothing for them to extend.
    """
    plan = PLANS[plan_key]
    lapsed = _is_lapsed(sub, plan_key)
    apply_overrides = not lapsed
    packs = max(0, int(getattr(sub, "branch_packs", 0) or 0)) if plan_key in PAID_PLAN_KEYS else 0

    def pick(base: int, override_value) -> int:
        value = _override(override_value) if apply_overrides else None
        return int(base) if value is None else value

    max_seats = pick(plan["max_seats"], getattr(sub, "override_max_seats", None))
    max_clients = pick(plan["max_clients"], getattr(sub, "override_max_clients", None))
    included_credits = pick(plan["included_credits"], getattr(sub, "override_included_credits", None))
    monthly_reads = pick(plan["max_reads"], getattr(sub, "override_monthly_reads", None))
    if packs:
        max_seats = _plus(max_seats, packs * BRANCH_PACK_SEATS)
        max_clients = _plus(max_clients, packs * BRANCH_PACK_FILES)
        included_credits = _plus(included_credits, packs * BRANCH_PACK_CREDITS)
        monthly_reads = _plus(monthly_reads, packs * BRANCH_PACK_READS)
    return {
        "plan": plan_key,
        "max_seats": max_seats,
        "max_clients": max_clients,
        "included_credits": included_credits,
        "monthly_reads": monthly_reads,
        "credits_recur": bool(plan["credits_recur"]),
        "branch_packs": packs,
        "overrides_applied": apply_overrides,
    }


def effective_limits(db: Session, organization_id: int) -> dict:
    """What THIS org gets: {max_seats, max_clients (open files), included_credits,
    monthly_reads} plus plan/credits_recur/branch_packs. Read-only (never creates rows).

    The credit/read allowances here are what enterprise_credits grants each period —
    included_credits_for()/monthly_reads_for() are only the plan's defaults. While billing is
    disabled (ENTERPRISE_FREE) seats/files/reads are UNLIMITED (-1) and nothing is granted.
    """
    if ENTERPRISE_FREE:
        return {
            "plan": "free", "max_seats": UNLIMITED, "max_clients": UNLIMITED,
            "included_credits": 0, "monthly_reads": UNLIMITED, "credits_recur": False,
            "branch_packs": 0, "overrides_applied": False,
        }
    sub = subscription_snapshot(db, organization_id)
    return _limits_for(sub, effective_plan_key(sub))


# ---------------------------------------------------------------------------
# Usage counts
# ---------------------------------------------------------------------------

def open_client_count(db: Session, organization_id: int) -> int:
    """Clients holding an open-file slot: those NOT in a non-open stage.

    Counted as "not in NOT_OPEN_STAGE_KEYS" rather than "in OPEN_STAGE_KEYS" on purpose: an
    unknown or legacy status reads as new_lead everywhere else (catalog.normalize_stage), so
    it must count as open here too — otherwise a stray value is a free, uncounted slot.
    """
    with db.no_autoflush:
        return int(
            db.query(func.count(models.EnterpriseClient.id))
            .filter(
                models.EnterpriseClient.organization_id == int(organization_id),
                or_(
                    models.EnterpriseClient.status.is_(None),
                    models.EnterpriseClient.status.notin_(sorted(catalog.NOT_OPEN_STAGE_KEYS)),
                ),
            )
            .scalar()
            or 0
        )


def active_client_count(db: Session, organization_id: int) -> int:
    """Alias of open_client_count, kept for callers that meant "usage against the client
    limit" — which, since plans are sized by open files, IS the open count."""
    return open_client_count(db, organization_id)


def total_client_count(db: Session, organization_id: int) -> int:
    """Every client in the workspace, open or not (for display only — never a limit)."""
    with db.no_autoflush:
        return int(
            db.query(func.count(models.EnterpriseClient.id))
            .filter(models.EnterpriseClient.organization_id == int(organization_id))
            .scalar()
            or 0
        )


def active_seat_count(db: Session, organization_id: int) -> int:
    return int(
        db.query(models.EnterpriseOrganizationMember)
        .filter(
            models.EnterpriseOrganizationMember.organization_id == int(organization_id),
            models.EnterpriseOrganizationMember.is_active.is_(True),
        )
        .count()
    )


# ---------------------------------------------------------------------------
# Open-file grace
# ---------------------------------------------------------------------------

def _file_limit_state(sub, used: int, limit: int) -> dict:
    """Where the org stands against its open-file limit, from the row alone (no writes).

    The stored stamp is honoured ONLY while the org is actually over: once open files are
    back at/below the limit any leftover stamp is stale (it is cleared on the next add), so
    it must never shorten a later, separate grace period.
    """
    if limit == UNLIMITED:
        return {"over": False, "since": None, "ends": None, "in_grace": False, "can_add": True}
    over = used > limit
    since = _as_naive(getattr(sub, "files_over_limit_since", None)) if over else None
    grace = timedelta(days=FILE_LIMIT_GRACE_DAYS)
    ends = since + grace if (since is not None and FILE_LIMIT_GRACE_DAYS > 0) else None
    now = datetime.utcnow()
    if used < limit:
        can_add = True
    elif FILE_LIMIT_GRACE_DAYS <= 0:
        can_add = False
    elif since is None:
        # At or over the limit with no clock running: the next add starts the grace clock.
        can_add = True
    else:
        can_add = now < ends
    return {
        "over": over,
        "since": since,
        "ends": ends,
        "in_grace": bool(over and ends is not None and now < ends),
        "can_add": can_add,
    }


# ---------------------------------------------------------------------------
# Features gated by tier
# ---------------------------------------------------------------------------

def _feature_allowed(sub, plan_key: str, feature: str, *, grandfathered: bool = False) -> bool:
    if grandfathered:
        return True
    if plan_key == SANDBOX_PLAN:
        # The trial evaluates Team — but only while it is running. A lapsed paid org keeps
        # the features only inside an (admin-extended or first-14-days) trial window.
        if _is_lapsed(sub, plan_key):
            if not _trial_still_running(sub):
                return False
        elif _is_trial_expired(sub):
            return False
    tier = PLANS[plan_key].get("features_tier") or "starter"
    return feature in TIER_FEATURES.get(tier, frozenset())


def _check_feature_key(feature: str) -> str:
    key = str(feature or "").strip().lower()
    if key not in FEATURE_KEYS:
        # A typo in a caller would otherwise read as "not on your plan" and 402 a paying
        # Team customer. Fail loudly instead — this is a programming error, not a state.
        raise ValueError(f"Unknown plan feature {feature!r}; expected one of {FEATURE_KEYS}.")
    return key


def has_feature(db: Session, organization_id: int, feature: str) -> bool:
    """Whether the org may use a tier-gated feature now ("branches" = create/edit offices,
    "custom_roles" = create/edit roles, "branch_reporting" = per-branch reports/filters).

    True on Team and Multi-branch, during a live trial, while billing is disabled, and for a
    grandfathered org inside the migration ramp. Never creates rows."""
    key = _check_feature_key(feature)
    if ENTERPRISE_FREE:
        return True
    sub = subscription_snapshot(db, organization_id)
    plan_key = effective_plan_key(sub)
    return _feature_allowed(
        sub, plan_key, key, grandfathered=_grandfathered_for(db, sub, organization_id)
    )


def feature_upgrade_message(feature: str) -> str:
    key = _check_feature_key(feature)
    return _FEATURE_UPGRADE_COPY[key].format(team=PLANS["growth"]["label"])


def enforce_feature_or_402(db: Session, organization_id: int, feature: str) -> None:
    """402 with an upgrade message naming the Team plan unless has_feature. Only creating /
    editing is gated — callers must NOT use this on reads of existing offices or roles,
    which keep working on every plan."""
    if has_feature(db, organization_id, feature):
        return
    raise HTTPException(status_code=402, detail=feature_upgrade_message(feature))


# ---------------------------------------------------------------------------
# The shared "AI paused" gate
# ---------------------------------------------------------------------------

AI_PAUSED_TRIAL_MESSAGE = (
    "Your free trial has ended — AI features are paused. Choose a plan to turn them back on. "
    "Everything in your workspace is still here."
)
AI_PAUSED_DOMAIN_MESSAGE = (
    "Your company has already used its free trial — AI features are paused. Choose a plan "
    "to turn them on. Everything in your workspace is still here."
)
AI_PAUSED_LAPSED_MESSAGE = (
    "Your {plan} plan has expired — AI features are paused. Renew to turn them back on. "
    "Everything in your workspace is still here."
)
# What a CLIENT (public interview link, client Copilot link) sees: they cannot choose a plan,
# and the consultancy's billing state is not theirs to read.
AI_PAUSED_CLIENT_MESSAGE = (
    "This AI feature is temporarily unavailable. Please contact your consultancy."
)


def _ai_access_for(sub, plan_key: str, *, grandfathered: bool = False) -> dict:
    allowed = {"allowed": True, "reason": None, "message": None}
    if ENTERPRISE_FREE or not AI_PAUSE_ON_EXPIRY:
        return allowed
    if plan_key in PAID_PLAN_KEYS or grandfathered:
        return allowed
    if _is_lapsed(sub, plan_key):
        if _trial_still_running(sub):
            return allowed
        label = (PLANS.get(normalize_plan_key(sub.plan)) or {}).get("label") or "paid"
        return {
            "allowed": False,
            "reason": "plan_lapsed",
            "message": AI_PAUSED_LAPSED_MESSAGE.format(plan=label),
        }
    if _is_trial_expired(sub):
        return {
            "allowed": False,
            "reason": "trial_expired",
            "message": (
                AI_PAUSED_DOMAIN_MESSAGE if bool(getattr(sub, "trial_domain_blocked", False))
                else AI_PAUSED_TRIAL_MESSAGE
            ),
        }
    return allowed


def ai_access_state(db: Session, organization_id: int) -> dict:
    """{allowed, reason: "trial_expired"|"plan_lapsed"|None, message} for every AI path.

    AI is paused when the sandbox trial has expired, or when a paid plan has lapsed (status
    no longer active/trialing, or past its period + PLAN_GRACE_DAYS) with no paid period in
    force. Never while billing is disabled or ENTERPRISE_AI_PAUSE_ON_EXPIRY=false. Read-only:
    safe on hot paths and inside a request that must not commit early."""
    if ENTERPRISE_FREE or not AI_PAUSE_ON_EXPIRY:
        return {"allowed": True, "reason": None, "message": None}
    sub = subscription_snapshot(db, organization_id)
    plan_key = effective_plan_key(sub)
    if plan_key in PAID_PLAN_KEYS:
        return {"allowed": True, "reason": None, "message": None}
    return _ai_access_for(
        sub, plan_key, grandfathered=_grandfathered_for(db, sub, organization_id)
    )


def enforce_ai_access_or_402(db: Session, organization_id: int, *, client_facing: bool = False) -> None:
    """Refuse an AI call with HTTP 402 while AI is paused — call BEFORE any model call or
    charge. `client_facing=True` swaps in a message for the consultancy's own clients (public
    interview / Copilot links), who cannot act on "choose a plan"."""
    state = ai_access_state(db, organization_id)
    if state["allowed"]:
        return
    raise HTTPException(
        status_code=402,
        detail=AI_PAUSED_CLIENT_MESSAGE if client_facing else state["message"],
    )


# ---------------------------------------------------------------------------
# Subscription state (what the portal, admin console and help KB render)
# ---------------------------------------------------------------------------

def build_subscription_state(
    db: Session, organization_id: int, *, read_only: bool = False, request=None,
) -> dict:
    """Render subscription state; read-only callers never initialize billing rows.

    `request` (optional) is the HTTP request the state is rendered for. It only matters for
    an org with no country_code on file: the quote currency then follows the request's CDN
    geo country — the same fallback charge_currency_for_org applies at /billing/plans and at
    checkout — so `currency`, the cards and the amount charged agree. Without it (admin
    console, background paths) an org with no country is quoted as before (INR allowed).
    """
    if read_only:
        # Suppress implicit writes too: a SELECT must not flush unrelated pending work.
        with db.no_autoflush:
            return _build_subscription_state(db, organization_id, read_only=True, request=request)
    return _build_subscription_state(db, organization_id, request=request)


def _reads_snapshot(db: Session, organization_id: int, limits: dict) -> dict:
    """The reading allowance as stored, for display. ALWAYS read-only, even on the default
    (provisioning) path: this state is built inside enforce_client_limit_or_402 and other
    request paths that have uncommitted work in the session, and a reads sync that commits
    there would commit the caller's half-done change (e.g. a reopen about to be refused).
    The grant itself happens on wallet access (enterprise_credits)."""
    from app import enterprise_credits as credits

    out: dict[str, Any]
    reads_state = getattr(credits, "reads_state", None)
    if callable(reads_state):
        out = dict(reads_state(db, organization_id, read_only=True) or {})
    else:
        wallet = credits.wallet_snapshot(db, organization_id)
        granted = int(getattr(wallet, "reads_granted", 0) or 0)
        used = int(getattr(wallet, "reads_used", 0) or 0)
        out = {"granted": granted, "used": used, "remaining": max(0, granted - used),
               "period_ends_at": None}
    out.setdefault("monthly_allowance", limits["monthly_reads"])
    out.setdefault("unlimited", False)
    return out


def _latest_plan_payment(db: Session, organization_id: int):
    with db.no_autoflush:
        return (
            db.query(
                models.EnterpriseSubscriptionPayment.currency,
                models.EnterpriseSubscriptionPayment.billing_cycle,
            )
            .filter(
                models.EnterpriseSubscriptionPayment.organization_id == int(organization_id),
                models.EnterpriseSubscriptionPayment.status.in_(
                    ("verified", "partially_refunded", "refunded")
                ),
            )
            .order_by(models.EnterpriseSubscriptionPayment.id.desc())
            .limit(1)
            .first()
        )


def _build_subscription_state(
    db: Session, organization_id: int, *, read_only: bool = False, sub=None, request=None,
) -> dict:
    if ENTERPRISE_FREE:
        return _free_subscription_state(db, organization_id)
    if sub is None:
        sub = subscription_snapshot(db, organization_id) if read_only else get_or_create_org_subscription(db, organization_id)
    plan_key = effective_plan_key(sub)
    plan = PLANS[plan_key]
    limits = _limits_for(sub, plan_key)
    clients_used = open_client_count(db, organization_id)
    seats_used = active_seat_count(db, organization_id)

    is_sandbox = plan_key == SANDBOX_PLAN
    trial_expired = _is_trial_expired(sub)
    trial_days_left = None
    if is_sandbox and sub.trial_ends_at:
        ends = sub.trial_ends_at.replace(tzinfo=None) if getattr(sub.trial_ends_at, "tzinfo", None) else sub.trial_ends_at
        trial_days_left = max(0, (ends - datetime.utcnow()).days)

    max_clients = limits["max_clients"]
    max_seats = limits["max_seats"]
    # The ORG's creation date decides the ramp — see is_grandfathered. Legacy orgs have no
    # subscription row until this very request creates one, so the subscription's own age is
    # always "just now" for exactly the accounts that must be protected.
    org_row = (
        db.query(
            models.EnterpriseOrganization.created_at,
            models.EnterpriseOrganization.billing_currency,
            models.EnterpriseOrganization.country_code,
        )
        .filter(models.EnterpriseOrganization.id == int(organization_id))
        .first()
    )
    org_created_at = org_row[0] if org_row else None
    # The org's own country, else the request's geo country — exactly the country
    # charge_currency_for_org decides by, so the region clamp below, `inr_region` and the
    # US$-estimate flag all match what /billing/plans shows and checkout charges. Ignoring
    # the request here once quoted a London office with no country on file in INR while its
    # cards (and its checkout) were in GBP.
    org_country = (_norm_country(org_row[2]) if org_row else None) or request_geo_country(request)
    grandfathered = is_grandfathered(sub, org_created_at)
    files = _file_limit_state(sub, clients_used, max_clients)
    can_add_client = files["can_add"] and not trial_expired
    can_add_seat = (max_seats == UNLIMITED or seats_used < max_seats) and not trial_expired
    if grandfathered:
        # Pre-existing org inside the ramp: caps are advisory, so an org that grew past
        # them while the platform was free keeps working while it picks a tier.
        can_add_client = True
        can_add_seat = True
    # Quote in the currency this org is ACTUALLY billed in: its latest verified plan payment
    # (a Razorpay mandate keeps charging the currency it was opened in), else the sticky
    # choice / country fallback — then clamped to the org's currency region, the same rule
    # checkout applies (charge_currency_for_org), so the chip never shows a price in a
    # currency checkout would refuse. The reported `currency` below comes from the quote so
    # the two can never disagree.
    latest_payment = _latest_plan_payment(db, organization_id)
    billed_currency = latest_payment[0] if latest_payment else None
    if billed_currency and money.is_chargeable(billed_currency):
        candidate = money.normalize_currency(billed_currency, strict=False)
    else:
        candidate = fallback_charge_currency(org_row[1] if org_row else None, org_country)
    quote_currency = resolve_plan_currency(plan_key, region_charge_currency(candidate, org_country))
    quote = checkout_quote(plan_key, quote_currency)
    yearly_quote = (
        checkout_quote(plan_key, quote_currency, billing_cycle="yearly")
        if plan.get("price_product") else None
    )

    # A LAPSED PAYING CUSTOMER IS NOT A NEW SANDBOX ORG. effective_plan_key drops them to
    # sandbox limits, but without saying so every surface would present a consultancy that
    # paid us last month as a fresh trial — "sandbox, ending today", renewal date hidden,
    # status still reading "active" — and the one thing they need to know (your plan expired,
    # renew to restore it) would appear nowhere. These fields carry that fact to the UI.
    subscribed_plan_key = normalize_plan_key(sub.plan)
    plan_lapsed = _is_lapsed(sub, plan_key)
    lapsed_plan = PLANS.get(subscribed_plan_key) if plan_lapsed else None

    ai = _ai_access_for(sub, plan_key, grandfathered=grandfathered)
    features = {
        key: _feature_allowed(sub, plan_key, key, grandfathered=grandfathered)
        for key in FEATURE_KEYS
    }
    reads = _reads_snapshot(db, organization_id, limits)
    trial_domain_blocked = bool(getattr(sub, "trial_domain_blocked", False))

    # The US$ estimate is for the NON-Indian members of the INR region (Nepal, Bangladesh,
    # …): they are charged INR and think in dollars. An Indian org, or one whose country is
    # unknown, gets none.
    show_usd_estimate = (
        quote["currency"] == "INR" and org_country is not None
        and org_country != "IN" and org_country in INR_REGION_COUNTRIES
    )
    usd_estimate = None
    if show_usd_estimate and quote["list_minor"] > 0:
        m_est = usd_estimate_minor(quote["total_minor"])
        usd_estimate = {
            "currency": "USD",
            "monthly_minor": m_est,
            "monthly_display": _usd_estimate_display(m_est),
            "total_minor": m_est,
            "total_display": _usd_estimate_display(m_est),
        }

    return {
        "plan": plan["key"],
        "plan_label": plan["label"],
        # "active" is the raw column and it is never written to anything else, so it must not
        # be reported as the live state once the paid period has run out.
        "status": "lapsed" if plan_lapsed else sub.status,
        "plan_lapsed": plan_lapsed,
        # Auto-renewal state. `auto_renews` is what the UI promises the customer; if it is
        # False the plan will simply stop at `current_period_end` and they must act.
        "auto_renews": bool(sub.razorpay_subscription_id) and not bool(sub.cancel_at_period_end),
        "has_mandate": bool(sub.razorpay_subscription_id),
        "cancel_at_period_end": bool(sub.cancel_at_period_end),
        "mandate_status": sub.mandate_status,
        "lapsed_plan": subscribed_plan_key if plan_lapsed else None,
        "lapsed_plan_label": lapsed_plan["label"] if lapsed_plan else None,
        "lapsed_at": sub.current_period_end if plan_lapsed else None,
        # The cycle of the latest plan payment ("monthly"/"yearly"); None if never paid.
        "billing_cycle": (latest_payment[1] or "monthly") if latest_payment else None,
        # `is_trial` keeps its name (the deployed SPA branches on it) and now means
        # "on the free sandbox tier".
        "is_trial": is_sandbox,
        "is_sandbox": is_sandbox,
        "trial_expired": trial_expired,
        "trial_days_left": trial_days_left,
        "trial_ends_at": sub.trial_ends_at,
        "trial_domain_blocked": trial_domain_blocked,
        # The demo-call bonus is still on offer: a live trial that has not had it.
        "trial_bonus_available": bool(
            is_sandbox and not plan_lapsed and not trial_expired and not trial_domain_blocked
            and getattr(sub, "demo_bonus_granted_at", None) is None
            and TRIAL_DEMO_BONUS_CREDITS > 0
        ),
        "trial_bonus_credits": TRIAL_DEMO_BONUS_CREDITS,
        "current_period_end": sub.current_period_end,
        # Limits as they apply to THIS org (overrides and Branch Packs included).
        # `max_clients`/`clients_used` keep their names and now mean OPEN files.
        "max_clients": max_clients,
        "max_seats": max_seats,
        "clients_used": clients_used,
        "open_files_used": clients_used,
        "max_open_files": max_clients,
        "clients_total": total_client_count(db, organization_id),
        "seats_used": seats_used,
        "can_add_client": can_add_client,
        "can_add_seat": can_add_seat,
        # Open-file grace: over the limit, when the clock started (None until the first add
        # while over), when adding stops, and whether that is still ahead.
        "files_over_limit": files["over"],
        "files_over_limit_since": files["since"],
        "files_grace_ends_at": files["ends"],
        "files_in_grace": files["in_grace"],
        "files_grace_days": FILE_LIMIT_GRACE_DAYS,
        # True while a pre-cutover org is inside the migration ramp: caps are shown but not
        # enforced, and `grace_ends_at` is the date they stop being advisory.
        "grandfathered": grandfathered,
        "grace_ends_at": GRACE_UNTIL if grandfathered else None,
        "over_cap": (
            (max_clients != UNLIMITED and clients_used > max_clients)
            or (max_seats != UNLIMITED and seats_used > max_seats)
        ),
        # What this tier includes and costs, so the header chip and the usage panel do not
        # need a second round trip to /billing/plans.
        "included_credits": limits["included_credits"],
        "credits_recur": plan["credits_recur"],
        "monthly_reads": limits["monthly_reads"],
        "reads": reads,
        "branch_packs": limits["branch_packs"],
        "overrides": {
            "max_seats": _override(getattr(sub, "override_max_seats", None)),
            "max_clients": _override(getattr(sub, "override_max_clients", None)),
            "included_credits": _override(getattr(sub, "override_included_credits", None)),
            "monthly_reads": _override(getattr(sub, "override_monthly_reads", None)),
        },
        "features_tier": plan["features_tier"],
        "features": features,
        # The shared AI gate (ai_access_state) as the UI needs it: a banner, not a 402.
        "ai_paused": not ai["allowed"],
        "ai_paused_reason": ai["reason"],
        "ai_paused_message": ai["message"],
        "currency": quote["currency"],
        "monthly_minor": quote["list_minor"],
        "monthly_display": quote["list_display"],
        "tax_label": quote["tax_label"],
        "tax_percent": quote["tax_percent"],
        "price_note": quote["tax_note"],
        "total_minor": quote["total_minor"],
        "total_display": quote["total_display"],
        "yearly_enabled": yearly_enabled(),
        "yearly_minor": yearly_quote["list_minor"] if yearly_quote else 0,
        "yearly_display": yearly_quote["list_display"] if yearly_quote else None,
        "yearly_total_minor": yearly_quote["total_minor"] if yearly_quote else 0,
        "yearly_total_display": yearly_quote["total_display"] if yearly_quote else None,
        "inr_region": org_country is None or org_country in INR_REGION_COUNTRIES,
        "show_usd_estimate": show_usd_estimate,
        "usd_estimate": usd_estimate,
    }


def _limit_word(limit: int) -> str:
    return "unlimited" if limit == UNLIMITED else f"{int(limit):,}"


def _trial_ended_detail(state: dict, action: str, reassurance: str) -> str:
    if state.get("trial_domain_blocked"):
        return f"Your company has already used its free trial — choose a plan to {action}."
    return (
        f"Your {DEFAULT_TRIAL_DAYS}-day free trial has ended. Choose a plan to {action} — "
        f"{reassurance}."
    )


def refresh_files_over_limit(db: Session, organization_id: int) -> None:
    """Clear a stale open-file grace stamp once the org is back at/below its limit.

    Optional hygiene for paths that FREE a slot (closing/approving/rejecting a file,
    deleting a client): enforce_client_limit_or_402 already ignores a stamp while the org
    is not over, so this only matters when an org dips under and then goes over again
    WITHOUT an add in between (a downgrade, a lowered override) — without it, that second
    overage would inherit the first one's spent grace. Flushes, never commits."""
    if ENTERPRISE_FREE:
        return
    sub = (
        db.query(models.EnterpriseSubscription)
        .filter(models.EnterpriseSubscription.organization_id == int(organization_id))
        .first()
    )
    if sub is None or sub.files_over_limit_since is None:
        return
    limit = _limits_for(sub, effective_plan_key(sub))["max_clients"]
    if limit == UNLIMITED or open_client_count(db, organization_id) <= limit:
        sub.files_over_limit_since = None
        db.flush()


def enforce_client_limit_or_402(db: Session, organization_id: int, *, adding: int = 1) -> None:
    """Refuse (402) an add that the org's open-file limit does not allow.

    An "add" is anything that takes an open-file slot: creating a client, converting a lead,
    and REOPENING a file (moving it from a non-open stage — Approved/Rejected/Closed/On Hold —
    into an open one; see catalog.is_reopen). Reopen must go through here too, or
    close→add→reopen is an unlimited loophole. `adding` is how many slots the operation takes
    (an import can pass its batch size).

    The 14-day grace: an add that puts the org above its limit is allowed while it has been
    over for fewer than FILE_LIMIT_GRACE_DAYS, and the first such add stamps
    `files_over_limit_since`. An add that leaves the org at/below the limit clears the stamp.
    After the grace — or immediately with FILE_LIMIT_GRACE_DAYS=0 — the add is refused.

    The stamp is FLUSHED, not committed: the caller's commit of the add itself persists it,
    so an add that then fails (and rolls back) does not start the grace clock.
    """
    if ENTERPRISE_FREE:
        return
    adding = max(0, int(adding or 0))
    if adding == 0:
        return
    sub = get_or_create_org_subscription(db, organization_id)
    state = _build_subscription_state(db, organization_id, sub=sub)
    if state["trial_expired"]:
        raise HTTPException(
            status_code=402,
            detail=_trial_ended_detail(
                state, "keep adding clients",
                "everything already in your workspace stays exactly as it is",
            ),
        )
    if state["grandfathered"]:
        return
    limit = state["max_clients"]
    used = int(state["clients_used"])
    if limit == UNLIMITED:
        return
    if used + adding <= limit:
        if sub.files_over_limit_since is not None:
            sub.files_over_limit_since = None
            db.flush()
        return
    # The stamp only counts while the org is ALREADY over; a leftover from an earlier
    # overage (it dipped back under without an add clearing it) starts a fresh window.
    stamp = _as_naive(sub.files_over_limit_since) if used > limit else None
    if FILE_LIMIT_GRACE_DAYS > 0:
        if stamp is None:
            sub.files_over_limit_since = datetime.utcnow()
            db.flush()
            return
        if datetime.utcnow() < stamp + timedelta(days=FILE_LIMIT_GRACE_DAYS):
            return
    grace_note = (
        f" Your {FILE_LIMIT_GRACE_DAYS}-day grace period for going over has ended."
        if FILE_LIMIT_GRACE_DAYS > 0 else ""
    )
    raise HTTPException(
        status_code=402,
        detail=(
            f"Your {state['plan_label']} plan covers {_limit_word(limit)} open files and you "
            f"have {used:,}.{grace_note} Close files you've finished ({_not_open_stage_labels()} "
            "files don't count) or upgrade to add more."
        ),
    )


def enforce_seat_limit_or_402(db: Session, organization_id: int) -> None:
    """Seats are a hard cap (no grace) at the org's EFFECTIVE limit (overrides and Branch
    Packs included)."""
    if ENTERPRISE_FREE:
        return
    state = build_subscription_state(db, organization_id)
    if state["can_add_seat"]:
        return
    if state["trial_expired"]:
        raise HTTPException(
            status_code=402,
            detail=_trial_ended_detail(
                state, "add team members", "your existing team keeps its access",
            ),
        )
    raise HTTPException(
        status_code=402,
        detail=(
            f"Your {state['plan_label']} plan covers {_limit_word(state['max_seats'])} team seats "
            f"and you're using {state['seats_used']}. Upgrade to add more."
        ),
    )
