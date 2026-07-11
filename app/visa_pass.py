"""
The "Visa Success Pass" — B2C "Anxiety Paywall" revenue model for individual students.

Indian students are anxious but price-sensitive and hate subscriptions (they only need
to pass the visa interview once). So instead of a recurring plan we use:

  1. A FREEMIUM HOOK on signup / Chrome-extension install:
       * 1 free document "Red Flag" scan (shows ONE error, blurs the rest)
  2. A ONE-TIME "Visa Success Pass" — ₹999, 30-day validity (under the ₹1000
     psychological line). Unlocks:
       * Unlimited Chrome-extension usage + document audits
       * 3 full AI voice mock interviews
       * Full red-flag reveal (no blur)

The Pass is implemented as a one-time 30-day grant of the existing Pro access
(`app.subscriptions.grant_pro_access_for_days`), so all the broad "unlimited" Pro
benefits (AI chat, uploads) apply automatically. This module layers the three NEW
metered features on top via dedicated counters on the Subscription row, plus the
admin economics that prove the ~₹950 profit per pass against real Gemini cost.
"""

from __future__ import annotations

import os
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models
from app import fx
from app import subscriptions as subs


# ---------------------------------------------------------------------------
# Configuration (all overridable via environment variables)
# ---------------------------------------------------------------------------

CURRENCY = (os.getenv("VISA_PASS_CURRENCY", "INR").strip().upper() or "INR")
PASS_PRICE_PAISE = int(os.getenv("VISA_PASS_PRICE_PAISE", "99900") or "99900")     # ₹999
PASS_DURATION_DAYS = int(os.getenv("VISA_PASS_DURATION_DAYS", "30") or "30")
PASS_PRICING_MODEL = "visa_pass"  # stored on SubscriptionPayment.pricing_model

# Freemium quota (free tier) + pass quota.
FREE_RED_FLAG_SCANS = int(os.getenv("VISA_PASS_FREE_RED_FLAG", "1") or "1")
PASS_VOICE_INTERVIEWS = int(os.getenv("VISA_PASS_VOICE_INTERVIEWS", "3") or "3")
FREE_UNIVERSITY_RECOMMENDATIONS = int(os.getenv("VISA_PASS_FREE_UNIVERSITY_RECS", "1") or "1")
# SOP generator (Application Kit): generate + each refinement share one counter, so the
# free tier tastes the iterative loop (1 draft + 2 edits) before hitting the paywall.
FREE_SOP_GENERATIONS = int(os.getenv("VISA_PASS_FREE_SOP", "3") or "3")

# Hard-paywall when the free quota is exhausted (the whole point of the model).
ENFORCE = os.getenv("VISA_PASS_ENFORCE", "true").strip().lower() in {"1", "true", "yes", "on"}

# For the admin economics card only: rough ceiling cost to serve one maxed-out pass.
MAX_SERVE_COST_PAISE = int(os.getenv("VISA_PASS_MAX_SERVE_COST_PAISE", "5000") or "5000")  # ₹50
USD_TO_INR = float(os.getenv("USD_TO_INR", "86") or "86")

UNLIMITED = -1

# The metered Visa-Pass features.
FEATURES = {
    "red_flag_scan": {
        "key": "red_flag_scan",
        "label": "Document Red-Flag scan",
        "counter": "red_flag_scans_used",
        "free_limit": FREE_RED_FLAG_SCANS,
        "pass_limit": UNLIMITED,
    },
    "voice_interview": {
        "key": "voice_interview",
        "label": "AI voice mock interview",
        "counter": "pass_voice_interviews_used",
        "free_limit": 0,                      # voice interviews are pass-only
        "pass_limit": PASS_VOICE_INTERVIEWS,
    },
    "university_shortlist": {
        "key": "university_shortlist",
        "label": "AI University Shortlist",
        "counter": "university_recommendations_used",
        "free_limit": FREE_UNIVERSITY_RECOMMENDATIONS,
        "pass_limit": UNLIMITED,
    },
    "sop_generator": {
        "key": "sop_generator",
        "label": "AI SOP / Motivation-letter generator",
        "counter": "sop_generations_used",
        "free_limit": FREE_SOP_GENERATIONS,
        "pass_limit": UNLIMITED,
    },
}

# Gemini cost-tracker sources that are EXCLUSIVELY B2C-student features (used for the
# aggregate cost estimate). `document_ai` is shared with enterprise, so it's excluded
# here and instead attributed precisely per-account via user_id (see account report).
# (Dropped phantom sources `ds160_autofill` [no Gemini] and `student_voice_interview`
#  [never recorded — voice runs through the chat endpoint as student_ai_chat].)
# `student_ai_chat_copilot` is the Chrome-extension Copilot chat (split out of
# student_ai_chat so the admin AI-cost view can show extension spend separately).
B2C_COST_SOURCES = ["student_ai_chat", "student_ai_chat_copilot", "red_flag_scan", "university_shortlist"]


# ---------------------------------------------------------------------------
# Money helpers
# ---------------------------------------------------------------------------

def paise_to_rupees(paise) -> float:
    return round(float(paise or 0) / 100.0, 2)


def format_inr(paise) -> str:
    rupees = float(paise or 0) / 100.0
    if rupees == int(rupees):
        return f"₹{int(rupees):,}"
    return f"₹{rupees:,.2f}"


def usd_to_inr_paise(usd) -> int:
    """Convert USD → INR paise at the live rate (static USD_TO_INR fallback)."""
    try:
        rupees = Decimal(str(usd or 0)) * Decimal(str(fx.get_usd_to_inr()))
    except Exception:
        return 0
    return int((rupees * Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _naive(dt) -> Optional[datetime]:
    if dt is None:
        return None
    return dt.replace(tzinfo=None) if getattr(dt, "tzinfo", None) else dt


# ---------------------------------------------------------------------------
# Pass status
# ---------------------------------------------------------------------------

def has_active_pass(subscription: models.Subscription) -> bool:
    """True when the user currently holds an active (unexpired) Visa Success Pass.

    The pass is a 30-day Pro grant; perpetual Pro (no end date) also counts.
    `get_or_create_user_subscription` already downgrades expired passes to free.
    """
    if subscription is None:
        return False
    if (subscription.plan or "").lower() != subs.PLAN_PRO:
        return False
    if (subscription.status or "").lower() != subs.STATUS_ACTIVE:
        return False
    ends_at = _naive(subscription.ends_at)
    return ends_at is None or ends_at > datetime.utcnow()


def pass_days_left(subscription: models.Subscription) -> Optional[int]:
    if not has_active_pass(subscription):
        return None
    ends_at = _naive(subscription.ends_at)
    if ends_at is None:
        return None
    return max(0, (ends_at - datetime.utcnow()).days)


def get_feature(feature_key: str | None) -> Optional[dict]:
    return FEATURES.get(str(feature_key or "").strip().lower())


def feature_entitlement(subscription: models.Subscription, feature_key: str) -> dict:
    feature = get_feature(feature_key)
    if not feature:
        raise ValueError(f"Unknown Visa Pass feature: {feature_key}")
    is_pass = has_active_pass(subscription)
    used = int(getattr(subscription, feature["counter"], 0) or 0)
    limit = feature["pass_limit"] if is_pass else feature["free_limit"]
    unlimited = (limit == UNLIMITED)
    if unlimited:
        remaining = UNLIMITED
        locked = False
    else:
        remaining = max(limit - used, 0)
        locked = used >= limit
    return {
        "key": feature["key"],
        "label": feature["label"],
        "tier": "pass" if is_pass else "free",
        "used": used,
        "limit": limit,
        "remaining": remaining,
        "unlimited": unlimited,
        "locked": bool(locked),
    }


def pass_benefits() -> list[str]:
    return [
        "Unlimited Chrome-extension usage",
        "Unlimited document audits (Gemini)",
        f"{PASS_VOICE_INTERVIEWS} full AI voice mock interviews",
        "Full red-flag reveal — no blur",
        f"{PASS_DURATION_DAYS}-day validity",
    ]


def entitlements_state(db: Session, subscription: models.Subscription) -> dict:
    is_pass = has_active_pass(subscription)
    return {
        "has_pass": is_pass,
        "plan": "pass" if is_pass else "free",
        "enforced": ENFORCE,
        "currency": CURRENCY,
        "pass": {
            "active": is_pass,
            "price_paise": PASS_PRICE_PAISE,
            "price_display": format_inr(PASS_PRICE_PAISE),
            "duration_days": PASS_DURATION_DAYS,
            "ends_at": subscription.ends_at if is_pass else None,
            "days_left": pass_days_left(subscription),
            "benefits": pass_benefits(),
        },
        "features": {key: feature_entitlement(subscription, key) for key in FEATURES},
    }


# ---------------------------------------------------------------------------
# Gating & consumption
# ---------------------------------------------------------------------------

def _paywall_detail(feature: dict, ent: dict) -> str:
    # Pass holder who exhausted a metered pass feature (voice interviews).
    if ent["tier"] == "pass":
        return (
            f"You've used all {ent['limit']} {feature['label'].lower()}s in your Visa Success Pass."
        )
    if feature["free_limit"] <= 0:
        return (
            f"{feature['label']}s are part of the Visa Success Pass ({format_inr(PASS_PRICE_PAISE)}, "
            f"{PASS_DURATION_DAYS} days). Unlock the pass to continue."
        )
    return (
        f"You've used your {feature['free_limit']} free {feature['label'].lower()}"
        f"{'s' if feature['free_limit'] != 1 else ''}. Unlock the Visa Success Pass "
        f"({format_inr(PASS_PRICE_PAISE)}, {PASS_DURATION_DAYS} days) for unlimited access."
    )


def enforce_feature_or_402(db: Session, subscription: models.Subscription, feature_key: str) -> dict:
    """Pre-check before a metered Visa-Pass action. Returns the entitlement dict
    (so callers can read `tier`/`remaining`); raises 402 when locked & enforced."""
    feature = get_feature(feature_key)
    if not feature:
        raise HTTPException(status_code=400, detail="Unknown feature.")
    ent = feature_entitlement(subscription, feature_key)
    if ent["locked"] and ENFORCE:
        raise HTTPException(status_code=402, detail=_paywall_detail(feature, ent))
    return ent


def consume_feature(
    db: Session,
    subscription: models.Subscription,
    feature_key: str,
    *,
    commit: bool = True,
) -> int:
    """Increment a feature's usage counter. Returns the new used count."""
    feature = get_feature(feature_key)
    if not feature:
        raise HTTPException(status_code=400, detail="Unknown feature.")
    current = int(getattr(subscription, feature["counter"], 0) or 0)
    setattr(subscription, feature["counter"], current + 1)
    if commit:
        db.commit()
        db.refresh(subscription)
    return current + 1


def grant_pass(db: Session, user_id: int, *, commit: bool = True) -> models.Subscription:
    """Grant a fresh 30-day Visa Success Pass: extend Pro access and reset the
    pass-scoped voice-interview allowance to a fresh allotment."""
    subscription = subs.grant_pro_access_for_days(
        db, user_id, days=PASS_DURATION_DAYS, commit=False
    )
    subscription.pass_voice_interviews_used = 0  # fresh 3 interviews per pass
    if commit:
        db.commit()
        db.refresh(subscription)
    return subscription


# ---------------------------------------------------------------------------
# Admin economics — pass revenue vs real Gemini cost = our margin
# ---------------------------------------------------------------------------

def _b2c_gemini_cost_usd(db: Session) -> tuple[float, dict]:
    E = models.GeminiUsageEvent
    rows = (
        db.query(E.source, func.coalesce(func.sum(E.estimated_cost_usd), 0), func.count(E.id))
        .filter(E.source.in_(B2C_COST_SOURCES))
        .group_by(E.source)
        .all()
    )
    by_source = {src: {"cost_usd": float(cost or 0), "calls": int(calls or 0)} for src, cost, calls in rows}
    total = sum(v["cost_usd"] for v in by_source.values())
    return total, by_source


def build_revenue_analytics(db: Session) -> dict:
    """B2C 'Visa Success Pass' economics: pass revenue (verified one-time payments)
    vs the real Gemini cost from the app.ai_usage tracker."""
    P = models.SubscriptionPayment

    pass_q = db.query(P).filter(P.status == "verified", P.pricing_model == PASS_PRICING_MODEL)
    passes_sold = int(pass_q.with_entities(func.count(P.id)).scalar() or 0)
    revenue_paise = int(pass_q.with_entities(func.coalesce(func.sum(P.amount_paise), 0)).scalar() or 0)

    # Active passes right now (Pro + active + not expired).
    now = datetime.utcnow()
    active_passes = int(
        db.query(func.count(models.Subscription.id))
        .filter(
            models.Subscription.plan == subs.PLAN_PRO,
            models.Subscription.status == subs.STATUS_ACTIVE,
            (models.Subscription.ends_at.is_(None)) | (models.Subscription.ends_at > now),
        )
        .scalar() or 0
    )

    gemini_cost_usd, by_source = _b2c_gemini_cost_usd(db)
    gemini_cost_paise = usd_to_inr_paise(gemini_cost_usd)
    gross_margin_paise = revenue_paise - gemini_cost_paise
    margin_pct = round((gross_margin_paise / revenue_paise) * 100, 1) if revenue_paise > 0 else None
    avg_cost_per_pass_paise = int(gemini_cost_paise / passes_sold) if passes_sold > 0 else 0

    # Free-funnel adoption (how many people are in the freemium hook).
    free_users = int(
        db.query(func.count(models.Subscription.id))
        .filter(models.Subscription.plan == subs.PLAN_FREE)
        .scalar() or 0
    )
    free_feature_usage = {}
    for key, feature in FEATURES.items():
        col = getattr(models.Subscription, feature["counter"])
        free_feature_usage[key] = int(db.query(func.coalesce(func.sum(col), 0)).scalar() or 0)

    by_source_payload = [
        {
            "source": src,
            "cost_paise": usd_to_inr_paise(v["cost_usd"]),
            "cost_display": format_inr(usd_to_inr_paise(v["cost_usd"])),
            "calls": v["calls"],
        }
        for src, v in sorted(by_source.items(), key=lambda kv: kv[1]["cost_usd"], reverse=True)
    ]

    return {
        "currency": CURRENCY,
        "usd_to_inr": round(float(fx.get_state().get("rate") or USD_TO_INR), 2),
        "fx_source": fx.get_state().get("source", "fallback"),
        "fx_updated_at": fx.get_state().get("fetched_at") or None,
        "is_estimate": True,
        "pass": {
            "price_paise": PASS_PRICE_PAISE,
            "price_display": format_inr(PASS_PRICE_PAISE),
            "duration_days": PASS_DURATION_DAYS,
            "max_serve_cost_paise": MAX_SERVE_COST_PAISE,
            "max_serve_cost_display": format_inr(MAX_SERVE_COST_PAISE),
            "target_profit_paise": PASS_PRICE_PAISE - MAX_SERVE_COST_PAISE,
            "target_profit_display": format_inr(PASS_PRICE_PAISE - MAX_SERVE_COST_PAISE),
        },
        "summary": {
            "passes_sold": passes_sold,
            "active_passes": active_passes,
            "free_users": free_users,
            "conversion_pct": round((passes_sold / free_users) * 100, 1) if free_users > 0 else None,
            "revenue_paise": revenue_paise,
            "revenue_display": format_inr(revenue_paise),
            "gemini_cost_paise": gemini_cost_paise,
            "gemini_cost_display": format_inr(gemini_cost_paise),
            "gemini_cost_usd": round(gemini_cost_usd, 4),
            "gross_margin_paise": gross_margin_paise,
            "gross_margin_display": format_inr(gross_margin_paise),
            "margin_pct": margin_pct,
            "avg_cost_per_pass_paise": avg_cost_per_pass_paise,
            "avg_cost_per_pass_display": format_inr(avg_cost_per_pass_paise),
        },
        "free_feature_usage": free_feature_usage,
        "cost_by_source": by_source_payload,
        "pricing_note": (
            "Revenue is verified one-time Visa Pass payments. Gemini cost is estimated from per-token "
            "pricing (app.ai_usage), B2C sources only, converted at USD_TO_INR — cross-check the GCP invoice."
        ),
    }


def build_account_cost_profit(db: Session, *, limit: int = 100) -> dict:
    """Per-ACCOUNT economics: for each student, their actual attributed Gemini cost
    (all sources, via GeminiUsageEvent.user_id) vs their Visa Pass revenue = profit.
    This is the precise per-account view (includes shared sources like document_ai)."""
    E = models.GeminiUsageEvent
    P = models.SubscriptionPayment
    U = models.User

    cost_rows = (
        db.query(E.user_id, func.coalesce(func.sum(E.estimated_cost_usd), 0), func.count(E.id))
        .filter(E.user_id.isnot(None))
        .group_by(E.user_id)
        .all()
    )
    cost_by_user = {int(uid): {"cost_usd": float(c or 0), "calls": int(n or 0)} for uid, c, n in cost_rows}

    rev_rows = (
        db.query(P.user_id, func.coalesce(func.sum(P.amount_paise), 0), func.count(P.id))
        .filter(P.status == "verified", P.pricing_model == PASS_PRICING_MODEL, P.user_id.isnot(None))
        .group_by(P.user_id)
        .all()
    )
    rev_by_user = {int(uid): {"paise": int(r or 0), "count": int(n or 0)} for uid, r, n in rev_rows}

    user_ids = set(cost_by_user) | set(rev_by_user)
    users = {u.id: u for u in db.query(U).filter(U.id.in_(user_ids)).all()} if user_ids else {}

    accounts = []
    tot_cost = tot_rev = 0
    unattributed = _b2c_unattributed_cost_paise(db)
    for uid in user_ids:
        cost_paise = usd_to_inr_paise(cost_by_user.get(uid, {}).get("cost_usd", 0.0))
        rev_paise = rev_by_user.get(uid, {}).get("paise", 0)
        tot_cost += cost_paise
        tot_rev += rev_paise
        u = users.get(uid)
        accounts.append({
            "user_id": uid,
            "email": (u.email if u else None),
            "name": (u.full_name if u else None),
            "has_pass": rev_by_user.get(uid, {}).get("count", 0) > 0,
            "ai_calls": cost_by_user.get(uid, {}).get("calls", 0),
            "gemini_cost_paise": cost_paise,
            "gemini_cost_display": format_inr(cost_paise),
            "revenue_paise": rev_paise,
            "revenue_display": format_inr(rev_paise),
            "profit_paise": rev_paise - cost_paise,
            "profit_display": format_inr(rev_paise - cost_paise),
        })
    accounts.sort(key=lambda a: (a["revenue_paise"], a["gemini_cost_paise"]), reverse=True)

    return {
        "currency": CURRENCY,
        "usd_to_inr": round(float(fx.get_state().get("rate") or USD_TO_INR), 2),
        "fx_source": fx.get_state().get("source", "fallback"),
        "fx_updated_at": fx.get_state().get("fetched_at") or None,
        "is_estimate": True,
        "total_accounts": len(accounts),
        "totals": {
            "attributed_cost_paise": tot_cost,
            "attributed_cost_display": format_inr(tot_cost),
            "revenue_paise": tot_rev,
            "revenue_display": format_inr(tot_rev),
            "profit_paise": tot_rev - tot_cost,
            "profit_display": format_inr(tot_rev - tot_cost),
            "unattributed_cost_paise": unattributed,
            "unattributed_cost_display": format_inr(unattributed),
        },
        "accounts": accounts[:max(1, min(int(limit or 100), 500))],
        "note": (
            "Per-account Gemini cost is attributed via GeminiUsageEvent.user_id (all sources). "
            "'Unattributed' = AI events with no user_id (e.g. pre-attribution history or background jobs)."
        ),
    }


def _b2c_unattributed_cost_paise(db: Session) -> int:
    E = models.GeminiUsageEvent
    usd = float(
        db.query(func.coalesce(func.sum(E.estimated_cost_usd), 0))
        .filter(E.user_id.is_(None), E.organization_id.is_(None))
        .scalar() or 0
    )
    return usd_to_inr_paise(usd)
