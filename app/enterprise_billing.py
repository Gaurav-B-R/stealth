"""
Per-organization subscription billing for the Rilono enterprise platform (B2B).

Consultancies self-serve onto a monthly tier. A tier caps three things — team seats,
active clients, and the AI credits included each month — and the credit allowance is
what ties this module to the prepaid wallet in app/enterprise_credits.py:

    | Tier               | Price/month  | Seats | Active clients | Included AI credits |
    | Self-serve sandbox | ₹0           |    2  |             10 | 100, one-time       |
    | Starter            | ₹2,999 + GST |   10  |            100 | 1,000 / month       |
    | Growth             | ₹6,999 + GST |   30  |            500 | 3,500 / month       |
    | Scale              | ₹14,999 +GST |  100  |          2,000 | 10,000 / month      |

Three things about that table are load-bearing:

  1. PRICES ARE EX-GST. The listed number is the taxable subtotal; checkout charges
     subtotal + 18% GST (see app/money.py::quote_with_tax). Anything that renders a price
     must render the subtotal and say "+ GST"; anything that creates a Razorpay order must
     send the total. `checkout_quote()` is the single place that produces both.

  2. INCLUDED CREDITS ARE GRANTED, NOT SIMULATED. Each billing period the org's wallet
     receives `included_credits` as a real ledger entry, exactly once per period — see
     app/enterprise_credits.py::sync_plan_credits. This module only declares the number.

  3. THE SANDBOX IS THE FREE TIER, NOT A TEASER. It is a real (if small) working
     workspace for 14 days with a one-time 100-credit grant. At day 15 it stops accepting
     new clients and seats and keeps everything already in it readable, so an evaluation
     that lapses never destroys data.

Razorpay order creation / verification lives in the enterprise router; this module owns
the plan catalog, the sandbox-evaluation logic, and limit enforcement. Prices themselves
live in app/money.py's PRICE_BOOK (the single source of truth for money), never here.

HISTORY: this replaced the "free CRM up to 50 students + ₹999/month infrastructure server
fee + purely prepaid credits" model on 2026-08-02. The infra fee is retired — see
app/enterprise_credits.py::infra_fee_state for what remains of it and why.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import models
from app import money


UNLIMITED = -1

# The free evaluation tier. `TRIAL_PLAN` is retained as an alias because rows written by
# the previous model carry plan="trial" verbatim; `normalize_plan_key` maps those (and the
# retired starter/growth/scale limits) onto the current catalog rather than migrating data.
SANDBOX_PLAN = "sandbox"
TRIAL_PLAN = SANDBOX_PLAN
LEGACY_TRIAL_KEYS = ("trial", "free")

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


# Plan catalog.
#
# `price_product` names the app/money.py PRICE_BOOK entry holding the EX-GST monthly
# subtotal — the price is NOT duplicated here, so there is exactly one number to change.
# `included_credits` is the AI credit allowance granted to the wallet each billing period
# (one-time for the sandbox; see `credits_recur`).
#
# Billing is MONTHLY ONLY. The published tier card quotes a per-month price and no annual
# price has been set, so quoting one here would be inventing it. The `billing_cycle`
# plumbing (DB column, Razorpay note) survives for the historical yearly rows that already
# exist and so re-introducing an annual tier is additive.
PLANS = {
    SANDBOX_PLAN: {
        "key": SANDBOX_PLAN,
        "label": "Self-serve sandbox",
        "tagline": "14-day evaluation — no card, no custom setup",
        "price_product": None,          # free: never priced, never checked out
        "monthly_paise": 0,
        "yearly_paise": 0,
        "max_seats": _int_env("ENTERPRISE_SANDBOX_MAX_SEATS", 2),
        "max_clients": _int_env("ENTERPRISE_SANDBOX_MAX_CLIENTS", 10),
        "included_credits": _int_env("ENTERPRISE_SANDBOX_CREDITS", 100),
        "credits_recur": False,         # 100 demo credits ONCE, not 100/month
        "is_public": True,
        "is_popular": False,
        "purpose": "14-day evaluation; no custom setup",
        "features": [
            "2 team seats",
            "Up to 10 active clients",
            "100 demo AI credits (one-time)",
            "Full client pipeline, notes & documents",
            "14-day evaluation — no card required",
        ],
    },
    "starter": {
        "key": "starter",
        "label": "Starter",
        "tagline": "Small consultancy or single branch",
        "price_product": "plan_starter",
        "yearly_paise": 0,
        "max_seats": _int_env("ENTERPRISE_STARTER_MAX_SEATS", 10),
        "max_clients": _int_env("ENTERPRISE_STARTER_MAX_CLIENTS", 100),
        "included_credits": _int_env("ENTERPRISE_STARTER_CREDITS", 1_000),
        "credits_recur": True,
        "is_public": True,
        "is_popular": False,
        "purpose": "Small consultancy or single branch",
        "features": [
            "10 team seats",
            "Up to 100 active clients",
            "1,000 AI credits every month",
            "Client pipeline, notes, documents & reminders",
            "Course Finder, shortlisting & client emails",
        ],
    },
    "growth": {
        "key": "growth",
        "label": "Growth",
        "tagline": "Multi-counsellor, multi-branch office",
        "price_product": "plan_growth",
        "yearly_paise": 0,
        "max_seats": _int_env("ENTERPRISE_GROWTH_MAX_SEATS", 30),
        "max_clients": _int_env("ENTERPRISE_GROWTH_MAX_CLIENTS", 500),
        "included_credits": _int_env("ENTERPRISE_GROWTH_CREDITS", 3_500),
        "credits_recur": True,
        "is_public": True,
        "is_popular": True,
        "purpose": "Multi-counsellor, multi-branch office",
        "features": [
            "30 team seats",
            "Up to 500 active clients",
            "3,500 AI credits every month",
            "Everything in Starter",
            "Offices, roles & per-branch reporting",
        ],
    },
    "scale": {
        "key": "scale",
        "label": "Scale",
        "tagline": "Larger consultancies and networks",
        "price_product": "plan_scale",
        "yearly_paise": 0,
        "max_seats": _int_env("ENTERPRISE_SCALE_MAX_SEATS", 100),
        "max_clients": _int_env("ENTERPRISE_SCALE_MAX_CLIENTS", 2_000),
        "included_credits": _int_env("ENTERPRISE_SCALE_CREDITS", 10_000),
        "credits_recur": True,
        "is_public": True,
        "is_popular": False,
        "purpose": "Larger consultancies and networks",
        "features": [
            "100 team seats",
            "Up to 2,000 active clients",
            "10,000 AI credits every month",
            "Everything in Growth",
            "Priority support & onboarding",
        ],
    },
}

PLAN_ORDER = [SANDBOX_PLAN, "starter", "growth", "scale"]
PAID_PLAN_KEYS = {"starter", "growth", "scale"}
CURRENCY = (os.getenv("ENTERPRISE_PLAN_CURRENCY", "INR").strip().upper() or "INR")

# How long a paid period lasts. Monthly only (see the PLANS comment).
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


# ---------------------------------------------------------------------------
# Grandfathering the orgs that predate paid plans
# ---------------------------------------------------------------------------
#
# Between the infra-fee model and these tiers the platform was free and UNCAPPED, so orgs
# signed up and grew past every number in the table above. Turning enforcement on without
# a ramp would, in one deploy, put a consultancy with 400 clients and 25 staff onto the
# sandbox's 10/2 caps and 402 their next client create — a working product breaking at the
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


def _free_subscription_state(db: Session, organization_id: int) -> dict:
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
        "clients_used": active_client_count(db, organization_id),
        "seats_used": active_seat_count(db, organization_id),
        "can_add_client": True,
        "can_add_seat": True,
        "is_free_platform": True,
        "included_credits": 0,
        "credits_recur": False,
        "currency": CURRENCY,
    }


def normalize_plan_key(raw: str | None) -> str:
    """Map any stored plan string onto a key that exists in the current catalog.

    Rows predating 2026-08-02 carry plan="trial" (and _free_subscription_state emits
    "free"), and the retired catalog reused the names starter/growth/scale for different
    limits. The names are deliberately reused rather than migrated: an org that was on
    "growth" is on the new Growth tier, and the ONE thing that must never happen is an
    unknown key silently resolving to a paid tier's limits. Anything unrecognised lands on
    the sandbox, which is the most restrictive tier.
    """
    key = str(raw or "").strip().lower()
    if key in LEGACY_TRIAL_KEYS:
        return SANDBOX_PLAN
    return key if key in PLANS else SANDBOX_PLAN


def get_plan(plan_key: str | None) -> Optional[dict]:
    """The catalog entry for a plan key, or None. Legacy keys resolve; junk does not —
    callers such as the checkout endpoint rely on None to reject a bad request."""
    key = str(plan_key or "").strip().lower()
    if key in LEGACY_TRIAL_KEYS:
        key = SANDBOX_PLAN
    return PLANS.get(key)


def normalize_billing_cycle(raw: str | None) -> str:
    """Billing is monthly-only (see the PLANS comment). Historical rows may carry
    "yearly"; this collapses every request to the cycle actually sold, so no endpoint can
    be talked into quoting an annual price that does not exist."""
    return "monthly"


def resolve_plan_currency(plan_key: str, currency: str | None = None) -> str:
    """The currency a plan can ACTUALLY be charged in — never merely the one requested.

    This exists to close a 100× overcharge. `CURRENCY` is env-driven
    (ENTERPRISE_PLAN_CURRENCY), and when the plan price book was INR-only, setting that
    env var to USD meant the amount stayed 299900 (paise) while the Razorpay order was
    created in USD — billing a ₹2,999 plan as $2,999. Price and currency must be resolved
    together, from the same lookup, or they can disagree; every caller therefore takes the
    currency from here rather than reading `CURRENCY` directly. The plan books now carry
    the full launch ladder, so a requested launch currency resolves to itself; anything
    the book lacks still falls back to INR.
    """
    plan = get_plan(plan_key)
    product = (plan or {}).get("price_product")
    code = (currency or CURRENCY or money.DEFAULT_CURRENCY).strip().upper()
    if not product:
        return money.DEFAULT_CURRENCY
    book = money.PRICE_BOOK.get(product) or {}
    return code if code in book else money.DEFAULT_CURRENCY


def plan_price_minor(plan_key: str, currency: str | None = None) -> int:
    """The EX-GST monthly subtotal for a plan, in the minor unit of the currency
    `resolve_plan_currency` settles on. Sourced from money.PRICE_BOOK — the plan catalog
    never holds a price. Free plans and unknown keys return 0, which every caller treats
    as "not purchasable"."""
    plan = get_plan(plan_key)
    if not plan or not plan.get("price_product"):
        return 0
    code = resolve_plan_currency(plan_key, currency)
    return int(money.price_minor(plan["price_product"], code))


def plan_amount_paise(plan_key: str, billing_cycle: str | None = None) -> int:
    """Back-compat shim: the ex-GST monthly subtotal in INR paise.

    Pinned to INR explicitly (not CURRENCY): now that the plan books carry non-INR
    ladders, ENTERPRISE_PLAN_CURRENCY=USD would otherwise make this return cents while
    its remaining callers (the help KB's rupee price line) treat the figure as paise.

    NOTE FOR CALLERS: this is the LIST price, not the charged amount. A plan order must
    be created for `checkout_quote(...)["total_minor"]`, which adds GST. Passing this
    figure to Razorpay undercharges every customer by the tax.
    """
    return plan_price_minor(plan_key, "INR")


def fallback_charge_currency(billing_currency: str | None, country_code: str | None) -> str:
    """The no-hint part of deciding what currency to charge an org in: the currency they
    were last billed in (if we can charge it) -> their country's currency -> INR.

    Shared by routers.enterprise._resolve_charge_currency (which adds strict validation
    of an explicit buyer hint on top) and build_subscription_state (which has no request
    to take a hint from), so the two can never rank the fallbacks differently.
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


def included_credits_for(plan_key: str | None) -> int:
    """AI credits included with a plan per billing period (0 if the plan has none)."""
    plan = get_plan(plan_key)
    return int(plan.get("included_credits") or 0) if plan else 0


def credits_recur_for(plan_key: str | None) -> bool:
    """Whether `included_credits` is granted every period (paid tiers) or once (sandbox)."""
    plan = get_plan(plan_key)
    return bool(plan.get("credits_recur")) if plan else False


def checkout_quote(
    plan_key: str,
    currency: str | None = None,
    *,
    discount_percent=None,
) -> dict:
    """The complete money breakdown for a plan purchase: list → discount → GST → total.

    The single place any plan price is turned into a payable amount. Order of operations
    is fixed and matters: a coupon reduces the TAXABLE value, so the discount is applied
    to the ex-GST subtotal and tax is computed on the reduced figure. Computing tax first
    would over-collect GST on money the customer never pays.

    `total_minor` is the only figure that may reach Razorpay; `list_minor` is the only one
    that may be displayed as the plan's price (alongside "+ GST").
    """
    # Resolved, not requested — see resolve_plan_currency. `quote["currency"]` is what the
    # Razorpay order MUST be created in; callers must not fall back to CURRENCY.
    code = resolve_plan_currency(plan_key, currency)
    list_minor = plan_price_minor(plan_key, code)
    subtotal = list_minor
    if discount_percent is not None:
        # Deliberately the coupon module's own function rather than the same arithmetic
        # written again here. The two differ in association — (a·b)/c versus a·(b/c) — and
        # with Decimal that can round apart by one minor unit on some percentages. The
        # checkout endpoint VALIDATES the coupon through apply_to_amount_or_400 and then
        # CHARGES what this returns, so a one-paise divergence between them is a real
        # (if small) mismatch between the amount approved and the amount taken.
        from app import enterprise_coupons

        subtotal = enterprise_coupons.compute_discounted_amount_paise(
            list_minor, Decimal(str(discount_percent))
        )
    quote = money.quote_with_tax(subtotal, code)
    quote["list_minor"] = list_minor
    quote["list_display"] = money.format_money(list_minor, code)
    quote["discount_minor"] = list_minor - subtotal
    quote["discount_display"] = money.format_money(list_minor - subtotal, code)
    return quote


def _format_inr(paise: int) -> str:
    rupees = paise / 100.0
    if rupees == int(rupees):
        return f"₹{int(rupees):,}"
    return f"₹{rupees:,.2f}"


def public_plans_payload(currency: str | None = None) -> list[dict]:
    """The tier cards, priced in `currency` (any launch currency; INR when omitted).

    Every price field is the EX-GST subtotal, and `tax_*`/`total_*` carry what checkout
    will actually charge, so a card can render "₹2,999/mo + GST" and a breakdown without
    the frontend doing tax arithmetic of its own.

    Returns [] while ENTERPRISE_FREE is on — with billing disabled there is nothing to
    sell, and a price list nobody can buy from is worse than no price list.
    """
    if ENTERPRISE_FREE:
        return []
    code = (currency or CURRENCY or money.DEFAULT_CURRENCY).strip().upper()
    payload = []
    for key in PLAN_ORDER:
        plan = PLANS[key]
        if not plan["is_public"]:
            continue
        quote = checkout_quote(key, code)
        monthly = quote["list_minor"]
        payload.append({
            "key": plan["key"],
            "label": plan["label"],
            "tagline": plan["tagline"],
            "purpose": plan["purpose"],
            # Ex-GST list price. `monthly_paise` keeps its legacy name (the deployed SPA
            # reads it) but is the minor unit of `currency`.
            "monthly_paise": monthly,
            "monthly_minor": monthly,
            "monthly_display": quote["list_display"],
            # Monthly-only: retained at 0 so an old client's yearly branch renders nothing.
            "yearly_paise": 0,
            "yearly_display": None,
            "currency": code,
            "is_free": monthly <= 0,
            # What checkout adds on top. tax_percent is 0 outside India.
            "tax_label": quote["tax_label"],
            "tax_percent": quote["tax_percent"],
            "tax_minor": quote["tax_minor"],
            "tax_display": quote["tax_display"],
            "total_minor": quote["total_minor"],
            "total_display": quote["total_display"],
            "price_note": (
                "Free for 14 days" if monthly <= 0
                else (f"+ {quote['tax_label']}" if quote["tax_label"] and quote["tax_minor"] else "")
            ),
            "max_clients": plan["max_clients"],
            "max_seats": plan["max_seats"],
            "included_credits": plan["included_credits"],
            "credits_recur": plan["credits_recur"],
            "credits_note": (
                f"{plan['included_credits']:,} AI credits every month" if plan["credits_recur"]
                else f"{plan['included_credits']:,} demo AI credits (one-time)"
            ),
            "is_popular": plan["is_popular"],
            "features": list(plan["features"]),
            "price_options": money.price_options(plan["price_product"]) if plan.get("price_product") else [],
        })
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


def _is_trial_expired(sub: models.EnterpriseSubscription) -> bool:
    """Whether the 14-day sandbox evaluation has run out.

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


def paid_period_expired(sub: models.EnterpriseSubscription) -> bool:
    """Whether a paid subscription's bought period has run out.

    THIS IS WHAT MAKES THE SUBSCRIPTION RECURRING. Checkout creates a one-off Razorpay
    ORDER, not a mandate, so nothing auto-debits and nothing external ever flips `status`
    away from "active" — the only two writes to it in the codebase both set it to "active".
    Gating solely on `status` therefore means one ₹2,999 payment buys the tier forever, and
    (because the credit period key keeps advancing) mints a fresh 1,000-credit allowance
    every 30 days at our cost. Expiry has to be derived from `current_period_end`.

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


def active_client_count(db: Session, organization_id: int) -> int:
    return int(
        db.query(models.EnterpriseClient)
        .filter(models.EnterpriseClient.organization_id == int(organization_id))
        .count()
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


def build_subscription_state(db: Session, organization_id: int) -> dict:
    if ENTERPRISE_FREE:
        return _free_subscription_state(db, organization_id)
    sub = get_or_create_org_subscription(db, organization_id)
    plan_key = effective_plan_key(sub)
    plan = PLANS[plan_key]
    clients_used = active_client_count(db, organization_id)
    seats_used = active_seat_count(db, organization_id)

    is_sandbox = plan_key == SANDBOX_PLAN
    trial_expired = _is_trial_expired(sub)
    trial_days_left = None
    if is_sandbox and sub.trial_ends_at:
        ends = sub.trial_ends_at.replace(tzinfo=None) if getattr(sub.trial_ends_at, "tzinfo", None) else sub.trial_ends_at
        trial_days_left = max(0, (ends - datetime.utcnow()).days)

    max_clients = plan["max_clients"]
    max_seats = plan["max_seats"]
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
    grandfathered = is_grandfathered(sub, org_created_at)
    can_add_client = (max_clients == UNLIMITED or clients_used < max_clients) and not trial_expired
    can_add_seat = (max_seats == UNLIMITED or seats_used < max_seats) and not trial_expired
    if grandfathered:
        # Pre-existing org inside the ramp: caps are advisory, so an org that grew past
        # them while the platform was free keeps working while it picks a tier.
        can_add_client = True
        can_add_seat = True
    # Quote in the currency this org is ACTUALLY billed in. For an org that has ever paid
    # for a plan, that is the currency of its latest verified plan payment — a Razorpay
    # mandate keeps charging the currency it was opened in forever, so deriving the chip
    # from the sticky-choice/country fallback would restyle a live ₹3,538.82 mandate as
    # "$39/mo" (or flip a $39 mandate to rupees after an INR credit top-up). The fallback
    # chain is only for prospective pricing: sandbox and never-paid orgs. The reported
    # `currency` below comes from the quote so the two can never disagree.
    billed_currency = (
        db.query(models.EnterpriseSubscriptionPayment.currency)
        .filter(
            models.EnterpriseSubscriptionPayment.organization_id == int(organization_id),
            models.EnterpriseSubscriptionPayment.status.in_(
                ("verified", "partially_refunded", "refunded")
            ),
        )
        .order_by(models.EnterpriseSubscriptionPayment.id.desc())
        .limit(1)
        .scalar()
    )
    if billed_currency and money.is_chargeable(billed_currency):
        quote_currency = resolve_plan_currency(
            plan_key, money.normalize_currency(billed_currency, strict=False)
        )
    else:
        quote_currency = resolve_plan_currency(
            plan_key,
            fallback_charge_currency(org_row[1] if org_row else None, org_row[2] if org_row else None),
        )
    quote = checkout_quote(plan_key, quote_currency)

    # A LAPSED PAYING CUSTOMER IS NOT A NEW SANDBOX ORG. effective_plan_key drops them to
    # sandbox limits, but without saying so every surface would present a consultancy that
    # paid us last month as a fresh trial — "sandbox, ending today", renewal date hidden,
    # status still reading "active" — and the one thing they need to know (your plan expired,
    # renew to restore it) would appear nowhere. These fields carry that fact to the UI.
    subscribed_plan_key = normalize_plan_key(sub.plan)
    plan_lapsed = subscribed_plan_key in PAID_PLAN_KEYS and plan_key != subscribed_plan_key
    lapsed_plan = PLANS.get(subscribed_plan_key) if plan_lapsed else None

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
        # `is_trial` keeps its name (the deployed SPA branches on it) and now means
        # "on the free sandbox tier".
        "is_trial": is_sandbox,
        "is_sandbox": is_sandbox,
        "trial_expired": trial_expired,
        "trial_days_left": trial_days_left,
        "trial_ends_at": sub.trial_ends_at,
        "current_period_end": sub.current_period_end,
        "max_clients": max_clients,
        "max_seats": max_seats,
        "clients_used": clients_used,
        "seats_used": seats_used,
        "can_add_client": can_add_client,
        "can_add_seat": can_add_seat,
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
        "included_credits": plan["included_credits"],
        "credits_recur": plan["credits_recur"],
        "currency": quote["currency"],
        "monthly_minor": quote["list_minor"],
        "monthly_display": quote["list_display"],
        "tax_label": quote["tax_label"],
        "tax_percent": quote["tax_percent"],
        "total_minor": quote["total_minor"],
        "total_display": quote["total_display"],
    }


def _limit_word(limit: int) -> str:
    return "unlimited" if limit == UNLIMITED else f"{int(limit):,}"


def enforce_client_limit_or_402(db: Session, organization_id: int) -> None:
    if ENTERPRISE_FREE:
        return
    state = build_subscription_state(db, organization_id)
    if state["can_add_client"]:
        return
    if state["trial_expired"]:
        raise HTTPException(
            status_code=402,
            detail=(
                "Your 14-day sandbox evaluation has ended. Choose a plan to keep adding clients — "
                "everything already in your workspace stays exactly as it is."
            ),
        )
    raise HTTPException(
        status_code=402,
        detail=(
            f"Your {state['plan_label']} plan covers {_limit_word(state['max_clients'])} active clients "
            f"and you have {state['clients_used']}. Upgrade to add more."
        ),
    )


def enforce_seat_limit_or_402(db: Session, organization_id: int) -> None:
    if ENTERPRISE_FREE:
        return
    state = build_subscription_state(db, organization_id)
    if state["can_add_seat"]:
        return
    if state["trial_expired"]:
        raise HTTPException(
            status_code=402,
            detail=(
                "Your 14-day sandbox evaluation has ended. Choose a plan to add team members — "
                "your existing team keeps its access."
            ),
        )
    raise HTTPException(
        status_code=402,
        detail=(
            f"Your {state['plan_label']} plan covers {_limit_word(state['max_seats'])} team seats "
            f"and you're using {state['seats_used']}. Upgrade to add more."
        ),
    )
