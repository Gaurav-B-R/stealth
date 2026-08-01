"""
Per-organization subscription billing for the Rilono enterprise platform.

Consultancies self-serve onto a plan. Each plan caps how many active clients and
team seats an organization may have. New organizations start on a free trial.

Razorpay order creation / verification lives in the enterprise router; this module
owns the plan catalog, the trial logic, and limit enforcement.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import models


UNLIMITED = -1
TRIAL_PLAN = "trial"
DEFAULT_TRIAL_DAYS = int(os.getenv("ENTERPRISE_TRIAL_DAYS", "14"))


def _paise(env_key: str, default_paise: int) -> int:
    raw = os.getenv(env_key, "").strip()
    if not raw:
        return default_paise
    try:
        value = int(raw)
        return value if value >= 0 else default_paise
    except ValueError:
        return default_paise


# Plan catalog. Monthly amounts are in paise (INR). Yearly = ~10 months (2 free).
PLANS = {
    TRIAL_PLAN: {
        "key": TRIAL_PLAN,
        "label": "Free Trial",
        "tagline": "Explore everything for 14 days",
        "monthly_paise": 0,
        "yearly_paise": 0,
        "max_clients": 25,
        "max_seats": 2,
        "is_public": False,
        "is_popular": False,
        "features": [
            "Up to 25 clients",
            "2 team seats",
            "Full client pipeline & notes",
            "Client emails",
        ],
    },
    "starter": {
        "key": "starter",
        "label": "Starter",
        "tagline": "For solo agents & small offices",
        "monthly_paise": _paise("ENTERPRISE_STARTER_MONTHLY_PAISE", 149900),
        "yearly_paise": _paise("ENTERPRISE_STARTER_YEARLY_PAISE", 1499000),
        "max_clients": 150,
        "max_seats": 3,
        "is_public": True,
        "is_popular": False,
        "features": [
            "Up to 150 active clients",
            "3 team seats",
            "Client pipeline, notes & reminders",
            "Send client emails",
            "Dashboard analytics",
        ],
    },
    "growth": {
        "key": "growth",
        "label": "Growth",
        "tagline": "For growing consultancies",
        "monthly_paise": _paise("ENTERPRISE_GROWTH_MONTHLY_PAISE", 399900),
        "yearly_paise": _paise("ENTERPRISE_GROWTH_YEARLY_PAISE", 3999000),
        "max_clients": 750,
        "max_seats": 10,
        "is_public": True,
        "is_popular": True,
        "features": [
            "Up to 750 active clients",
            "10 team seats",
            "Everything in Starter",
            "Bulk client emails",
            "Priority support",
        ],
    },
    "scale": {
        "key": "scale",
        "label": "Scale",
        "tagline": "For multi-branch agencies",
        "monthly_paise": _paise("ENTERPRISE_SCALE_MONTHLY_PAISE", 899900),
        "yearly_paise": _paise("ENTERPRISE_SCALE_YEARLY_PAISE", 8999000),
        "max_clients": UNLIMITED,
        "max_seats": 30,
        "is_public": True,
        "is_popular": False,
        "features": [
            "Unlimited clients",
            "30 team seats",
            "Everything in Growth",
            "Dedicated onboarding",
            "Priority support",
        ],
    },
}

PLAN_ORDER = [TRIAL_PLAN, "starter", "growth", "scale"]
PAID_PLAN_KEYS = {"starter", "growth", "scale"}
CURRENCY = (os.getenv("ENTERPRISE_PLAN_CURRENCY", "INR").strip().upper() or "INR")

# The enterprise platform is currently FREE for everyone: no pricing, no trial, no
# client/seat limits. Set ENTERPRISE_FREE=false to re-enable the paid plan model.
ENTERPRISE_FREE = os.getenv("ENTERPRISE_FREE", "true").strip().lower() in {"1", "true", "yes", "on"}


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
    }


def get_plan(plan_key: str | None) -> Optional[dict]:
    return PLANS.get(str(plan_key or "").strip().lower())


def normalize_billing_cycle(raw: str | None) -> str:
    value = str(raw or "").strip().lower()
    return "yearly" if value in {"yearly", "annual", "year"} else "monthly"


def plan_amount_paise(plan_key: str, billing_cycle: str) -> int:
    plan = get_plan(plan_key)
    if not plan:
        return 0
    return plan["yearly_paise"] if normalize_billing_cycle(billing_cycle) == "yearly" else plan["monthly_paise"]


def _format_inr(paise: int) -> str:
    rupees = paise / 100.0
    if rupees == int(rupees):
        return f"₹{int(rupees):,}"
    return f"₹{rupees:,.2f}"


def public_plans_payload() -> list[dict]:
    # New pricing model: the platform is credit-based and free-to-use. The legacy
    # seat-subscription plans (Starter/Growth/Scale + trial) must never be shown or
    # sold while ENTERPRISE_FREE is on — the credit model (see enterprise_credits.py)
    # is the only paid surface. Set ENTERPRISE_FREE=false to re-expose paid plans.
    if ENTERPRISE_FREE:
        return []
    payload = []
    for key in PLAN_ORDER:
        plan = PLANS[key]
        if not plan["is_public"]:
            continue
        payload.append({
            "key": plan["key"],
            "label": plan["label"],
            "tagline": plan["tagline"],
            "monthly_paise": plan["monthly_paise"],
            "yearly_paise": plan["yearly_paise"],
            "monthly_display": _format_inr(plan["monthly_paise"]),
            "yearly_display": _format_inr(plan["yearly_paise"]),
            "currency": CURRENCY,
            "max_clients": plan["max_clients"],
            "max_seats": plan["max_seats"],
            "is_popular": plan["is_popular"],
            "features": list(plan["features"]),
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
    if sub.plan != TRIAL_PLAN:
        return False
    if not sub.trial_ends_at:
        return False
    ends = sub.trial_ends_at
    if getattr(ends, "tzinfo", None):
        ends = ends.replace(tzinfo=None)
    return ends < datetime.utcnow()


def effective_plan_key(sub: models.EnterpriseSubscription) -> str:
    """The plan whose limits currently apply (paid plans require active status)."""
    plan_key = (sub.plan or TRIAL_PLAN).strip().lower()
    if plan_key in PAID_PLAN_KEYS and str(sub.status or "").lower() not in {"active", "trialing"}:
        # Lapsed paid plan falls back to trial-tier caps (read-mostly).
        return TRIAL_PLAN
    return plan_key if plan_key in PLANS else TRIAL_PLAN


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

    trial_expired = _is_trial_expired(sub)
    trial_days_left = None
    if sub.plan == TRIAL_PLAN and sub.trial_ends_at:
        ends = sub.trial_ends_at.replace(tzinfo=None) if getattr(sub.trial_ends_at, "tzinfo", None) else sub.trial_ends_at
        trial_days_left = max(0, (ends - datetime.utcnow()).days)

    max_clients = plan["max_clients"]
    max_seats = plan["max_seats"]
    can_add_client = (max_clients == UNLIMITED or clients_used < max_clients) and not trial_expired
    can_add_seat = (max_seats == UNLIMITED or seats_used < max_seats) and not trial_expired

    return {
        "plan": plan["key"],
        "plan_label": plan["label"],
        "status": sub.status,
        "is_trial": sub.plan == TRIAL_PLAN,
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
    }


def enforce_client_limit_or_402(db: Session, organization_id: int) -> None:
    if ENTERPRISE_FREE:
        return
    state = build_subscription_state(db, organization_id)
    if state["can_add_client"]:
        return
    if state["trial_expired"]:
        raise HTTPException(
            status_code=402,
            detail="Your free trial has ended. Upgrade your plan to keep adding clients.",
        )
    raise HTTPException(
        status_code=402,
        detail=(
            f"You've reached your plan limit of {state['max_clients']} clients. "
            "Upgrade your plan to add more."
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
            detail="Your free trial has ended. Upgrade your plan to add team members.",
        )
    raise HTTPException(
        status_code=402,
        detail=(
            f"You've reached your plan limit of {state['max_seats']} team seats. "
            "Upgrade your plan to add more."
        ),
    )
