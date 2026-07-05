"""B2C growth analytics for the admin console.

Two things the usage/cost dashboards don't answer:

1. build_activation_funnel(db)  — the conversion funnel signup -> activated -> ran red-flag
   scan -> purchased the Visa Pass, with per-step counts + drop-off. "You can't fix conversion
   you can't see."

2. build_outcome_analytics(db)  — the visa-DECISION approval rate (from the outcome-capture loop),
   segmented by whether the student used the red-flag scan. This is the pricing-power stat:
   "students who used Rilono's red-flag scan were approved at X% vs. the ~35-48% market baseline."

Both cover B2C students only (admins/developers excluded). Cheap COUNT/aggregate queries; safe
to call on the live DB.
"""
import os
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models

# The public market baseline for student-visa approval, shown alongside our own rate for context.
# Env-overridable; defaults to the ~35-48% band commonly cited for high-scrutiny posts.
MARKET_BASELINE_LOW = float(os.getenv("OUTCOME_MARKET_BASELINE_LOW", "35") or "35")
MARKET_BASELINE_HIGH = float(os.getenv("OUTCOME_MARKET_BASELINE_HIGH", "48") or "48")

# Decisions that count as a "decision on the merits" for the approval-rate denominator.
# withdrawn / deferred are excluded (the student pulled out or it's still pending admin review).
_DECIDED_ON_MERITS = ("approved", "refused")


def _students_query(db: Session):
    """B2C students only: exclude admin/developer accounts (.isnot(True) also catches NULL)."""
    return db.query(models.User).filter(
        models.User.is_admin.isnot(True),
        models.User.is_developer.isnot(True),
    )


def _pct(part: int, whole: int) -> Optional[float]:
    if not whole:
        return None
    return round(part / whole * 100, 1)


def build_activation_funnel(db: Session, days: Optional[int] = None) -> dict:
    """signup -> activated -> ran red-flag scan -> purchased Visa Pass."""
    U, S, P = models.User, models.Subscription, models.SubscriptionPayment

    q = _students_query(db)
    if days:
        q = q.filter(U.created_at >= datetime.utcnow() - timedelta(days=int(days)))

    # Pull only the student ids + the subscription counters we need, in one join.
    rows = (
        q.outerjoin(S, S.user_id == U.id)
        .with_entities(
            U.id,
            func.coalesce(S.ai_messages_used, 0),
            func.coalesce(S.document_uploads_used, 0),
            func.coalesce(S.prep_sessions_used, 0),
            func.coalesce(S.mock_interviews_used, 0),
            func.coalesce(S.red_flag_scans_used, 0),
            func.coalesce(S.ds160_autofills_used, 0),
            func.coalesce(S.pass_voice_interviews_used, 0),
        )
        .all()
    )

    # Everyone who has ever bought a Visa Pass (verified payment), among these students.
    student_ids = {r[0] for r in rows}
    purchaser_ids = set()
    if student_ids:
        for (uid,) in (
            db.query(P.user_id)
            .filter(P.status == "verified", P.pricing_model == "visa_pass", P.user_id.in_(student_ids))
            .distinct()
            .all()
        ):
            purchaser_ids.add(uid)

    signups = len(rows)
    activated = 0
    scanned = 0
    scanned_ids = set()
    for uid, ai, docs, prep, mock, redflag, ds160, voice in rows:
        if (ai + docs + prep + mock + redflag + ds160 + voice) > 0:
            activated += 1
        if redflag > 0:
            scanned += 1
            scanned_ids.add(uid)

    purchased = len(purchaser_ids)
    scanned_and_purchased = len(scanned_ids & purchaser_ids)

    stages = [
        {"key": "signup", "label": "Signed up", "users": signups, "pct_of_signups": 100.0 if signups else None},
        {"key": "activated", "label": "Activated (used a feature)", "users": activated, "pct_of_signups": _pct(activated, signups)},
        {"key": "red_flag_scan", "label": "Ran a red-flag scan", "users": scanned, "pct_of_signups": _pct(scanned, signups)},
        {"key": "purchased", "label": "Purchased Visa Pass", "users": purchased, "pct_of_signups": _pct(purchased, signups)},
    ]

    # Step-to-step conversions (the actionable ones). scan->purchase uses the nested subset so it
    # reads as "of students who scanned, how many then bought".
    key_conversions = {
        "signup_to_activated": _pct(activated, signups),
        "activated_to_scan": _pct(scanned, activated),
        "scan_to_purchase": _pct(scanned_and_purchased, scanned),
        "overall_signup_to_purchase": _pct(purchased, signups),
    }

    # Biggest leak = the largest step-over-step drop, to point attention.
    drops = []
    for i in range(1, len(stages)):
        prev, cur = stages[i - 1], stages[i]
        if prev["users"]:
            drops.append((stages[i - 1]["label"] + " → " + cur["label"], prev["users"] - cur["users"]))
    biggest_leak = max(drops, key=lambda d: d[1])[0] if drops else None

    return {
        "window_days": days,
        "stages": stages,
        "key_conversions": key_conversions,
        "biggest_leak": biggest_leak,
    }


def build_outcome_analytics(db: Session) -> dict:
    """Visa-decision approval rate overall + segmented by red-flag-scan usage / Pass ownership."""
    U, S = models.User, models.Subscription

    rows = (
        _students_query(db)
        .filter(U.visa_decision.isnot(None))
        .outerjoin(S, S.user_id == U.id)
        .with_entities(
            U.visa_decision,
            func.coalesce(S.red_flag_scans_used, 0),
            S.plan,
        )
        .all()
    )

    def _bucket():
        return {"approved": 0, "refused": 0, "withdrawn": 0, "deferred": 0}

    overall = _bucket()
    used_scan = _bucket()
    no_scan = _bucket()

    for decision, redflag, plan in rows:
        d = (decision or "").lower()
        if d not in overall:
            continue
        overall[d] += 1
        (used_scan if (redflag or 0) > 0 else no_scan)[d] += 1

    def _summ(bucket: dict) -> dict:
        decided = bucket["approved"] + bucket["refused"]
        total = sum(bucket.values())
        return {
            **bucket,
            "decided_on_merits": decided,
            "total_recorded": total,
            "approval_rate": _pct(bucket["approved"], decided),
        }

    scan_summary = _summ(used_scan)
    noscan_summary = _summ(no_scan)
    lift = None
    if scan_summary["approval_rate"] is not None and noscan_summary["approval_rate"] is not None:
        lift = round(scan_summary["approval_rate"] - noscan_summary["approval_rate"], 1)

    return {
        "overall": _summ(overall),
        "red_flag_scan_users": scan_summary,
        "non_red_flag_scan_users": noscan_summary,
        "red_flag_lift_pts": lift,
        "market_baseline": {"low": MARKET_BASELINE_LOW, "high": MARKET_BASELINE_HIGH},
        # Guardrail for the marketing team: don't quote a rate off a tiny sample.
        "sample_is_thin": (overall["approved"] + overall["refused"]) < 30,
    }
