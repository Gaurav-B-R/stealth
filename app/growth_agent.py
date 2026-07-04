"""
Internal Growth / Conversion Agent (Rilono admins only).

Analyses free-plan student accounts and their real product activity, then recommends
*which accounts need what kind of promotion* to convert them to the Visa Success Pass.

Architecture (deliberate, learned from Deep Scan):
- The **math is deterministic in Python** — per-account usage ratios vs the free-tier
  caps, recency, tenure and a 0-100 intent score. LLMs are unreliable at arithmetic over
  raw rows and it would blow the context window on a large user base, so Python does the
  scoring and shortlisting.
- **Gemini does the strategy** — over the compact, pre-scored shortlist it decides the
  segment, the specific promotion/offer, a ready-to-send message, the channel and a
  priority for each account. This is what an "advanced thinking model" is good at.

Model: configurable via ADMIN_GROWTH_AGENT_MODEL, defaulting to a capable thinking model
(gemini-2.5-pro). NOTE: there is no "Gemini 3.1 Pro" model id; point the env at any newer
model when it ships.

This module is INTERNAL. It is only ever reached through admin-gated endpoints.
"""

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app import models
from app import ai_usage
from app import subscriptions as subs
from app import visa_pass
from app import visa_catalog
from app.enterprise_ai import is_ai_configured  # reuse the standard Gemini availability check
from app.utils import gemini_service as gemini_utils

logger = logging.getLogger(__name__)

genai = gemini_utils.genai

# How many of the highest-intent free accounts to hand to the model per run.
GROWTH_AGENT_MAX_CANDIDATES = int(os.getenv("ADMIN_GROWTH_AGENT_MAX_CANDIDATES", "30") or "30")

# The promotion levers the agent is allowed to recommend (kept to what we can actually
# deliver today). The model must pick from these ids.
PROMOTION_PLAYS = [
    {"id": "limit_reached_offer", "label": "Hit-a-limit upgrade nudge",
     "desc": "They exhausted a free quota — surface the Pass with the exact feature they ran out of."},
    {"id": "value_recap_discount", "label": "Value recap + first-Pass discount",
     "desc": "Active user close to converting — recap what they've done and offer the referral/first-time ₹200 off."},
    {"id": "feature_highlight", "label": "Feature highlight",
     "desc": "Nudge toward a Pass-only feature they haven't tried (voice mock, Deep Scan, unlimited chat)."},
    {"id": "interview_urgency", "label": "Interview-timing urgency",
     "desc": "Interview/intake approaching — emphasise unlimited mock interviews before the date."},
    {"id": "reengagement", "label": "Re-engagement first (no hard sell)",
     "desc": "Went quiet — win them back into the product before pitching the Pass."},
    {"id": "onboarding_prompt", "label": "Finish onboarding",
     "desc": "Signed up but never set destination/visa — get them activated first."},
    {"id": "hold", "label": "Hold / do not contact yet",
     "desc": "Too early or too little signal — don't burn goodwill with a pitch."},
]
_PROMOTION_IDS = {p["id"] for p in PROMOTION_PLAYS}


def _model_candidates() -> list:
    """Ordered models to try. Defaults to Google's latest thinking model with fallbacks;
    override entirely via ADMIN_GROWTH_AGENT_MODEL / ADMIN_GROWTH_AGENT_MODEL_CANDIDATES."""
    return gemini_utils.get_model_candidates(
        primary_env="ADMIN_GROWTH_AGENT_MODEL",
        candidates_env="ADMIN_GROWTH_AGENT_MODEL_CANDIDATES",
        defaults=["gemini-3.1-pro-preview", "gemini-3-pro-preview", "gemini-2.5-pro", "gemini-2.5-flash"],
    )


def _ratio(used, limit) -> float:
    used = int(used or 0)
    limit = int(limit or 0)
    if limit <= 0:
        return 0.0
    return min(1.0, used / limit)


def _days_since(dt) -> Optional[int]:
    if not dt:
        return None
    naive = dt.replace(tzinfo=None) if getattr(dt, "tzinfo", None) else dt
    return max(0, (datetime.utcnow() - naive).days)


def _intent_score(f: dict) -> float:
    """Deterministic 0-100 purchase-intent score from real usage (the 'math')."""
    s = 0.0
    s += 22 * f["ai_usage_ratio"]
    s += 16 * f["mock_usage_ratio"]
    s += 14 * f["prep_usage_ratio"]
    s += 12 * f["upload_usage_ratio"]
    s += 10 * f["scan_usage_ratio"]
    # Hitting a hard free-tier wall is the single strongest buy signal.
    if f["hit_any_limit"]:
        s += 25
    d = f["days_since_last_login"]
    if d is not None:
        if d <= 3:
            s += 14
        elif d <= 7:
            s += 10
        elif d <= 14:
            s += 5
        elif d > 45:
            s -= 8
    if f["onboarding_completed"]:
        s += 6
    # Brand new with zero activity = too early to pitch.
    if f["tenure_days"] < 1 and f["engagement_events"] == 0:
        s -= 12
    return round(max(0.0, min(100.0, s)), 1)


def _features_for(user, sub) -> dict:
    """Deterministic per-account feature/score dict (reused for the batch run and single account)."""
    dest = getattr(user, "destination_country_code", None)
    engagement_events = int(
        (sub.ai_messages_used or 0) + (sub.document_uploads_used or 0)
        + (sub.prep_sessions_used or 0) + (sub.mock_interviews_used or 0)
        + (sub.red_flag_scans_used or 0) + (sub.ds160_autofills_used or 0)
    )
    hit_any_limit = (
        (sub.ai_messages_used or 0) >= subs.FREE_AI_MESSAGE_LIMIT
        or (sub.document_uploads_used or 0) >= subs.FREE_DOCUMENT_UPLOAD_LIMIT
        or (sub.prep_sessions_used or 0) >= subs.FREE_PREP_SESSION_LIMIT
        or (sub.mock_interviews_used or 0) >= subs.FREE_MOCK_INTERVIEW_LIMIT
        or (sub.red_flag_scans_used or 0) >= visa_pass.FREE_RED_FLAG_SCANS
    )
    feat = {
        "user_id": user.id,
        "email": user.email,
        "name": user.full_name or (user.email.split("@")[0] if user.email else "Student"),
        "destination": (visa_catalog.country_meta(dest) or {}).get("name") if dest else None,
        "visa_type": visa_catalog.visa_type_label(dest, getattr(user, "visa_type_key", None)) if dest else None,
        "onboarding_completed": getattr(user, "onboarding_completed_at", None) is not None,
        "heard_about_us": getattr(user, "heard_about_us", None),
        "acquisition_channel": getattr(user, "acquisition_channel", None),
        "tenure_days": _days_since(user.created_at) or 0,
        "days_since_last_login": _days_since(getattr(user, "last_login_at", None)),
        "engagement_events": engagement_events,
        "hit_any_limit": hit_any_limit,
        "ai_usage_ratio": round(_ratio(sub.ai_messages_used, subs.FREE_AI_MESSAGE_LIMIT), 2),
        "upload_usage_ratio": round(_ratio(sub.document_uploads_used, subs.FREE_DOCUMENT_UPLOAD_LIMIT), 2),
        "prep_usage_ratio": round(_ratio(sub.prep_sessions_used, subs.FREE_PREP_SESSION_LIMIT), 2),
        "mock_usage_ratio": round(_ratio(sub.mock_interviews_used, subs.FREE_MOCK_INTERVIEW_LIMIT), 2),
        "scan_usage_ratio": round(_ratio(sub.red_flag_scans_used, visa_pass.FREE_RED_FLAG_SCANS), 2),
        "usage_detail": {
            "ai_messages": f"{sub.ai_messages_used or 0}/{subs.FREE_AI_MESSAGE_LIMIT}",
            "document_uploads": f"{sub.document_uploads_used or 0}/{subs.FREE_DOCUMENT_UPLOAD_LIMIT}",
            "prep_sessions": f"{sub.prep_sessions_used or 0}/{subs.FREE_PREP_SESSION_LIMIT}",
            "mock_interviews": f"{sub.mock_interviews_used or 0}/{subs.FREE_MOCK_INTERVIEW_LIMIT}",
            "red_flag_scans": f"{sub.red_flag_scans_used or 0}/{visa_pass.FREE_RED_FLAG_SCANS}",
        },
    }
    feat["intent_score"] = _intent_score(feat)
    return feat


def compute_candidates(db: Session, limit: int = GROWTH_AGENT_MAX_CANDIDATES) -> tuple[list[dict], int]:
    """Return (top_candidates, total_free_accounts). Deterministic — no AI here."""
    limit = max(1, min(100, int(limit or GROWTH_AGENT_MAX_CANDIDATES)))

    rows = (
        db.query(models.User, models.Subscription)
        .join(models.Subscription, models.Subscription.user_id == models.User.id)
        .filter(
            models.User.email_verified.is_(True),
            models.User.is_admin.is_(False),
            models.User.is_developer.is_(False),
        )
        .all()
    )

    candidates: list[dict] = []
    total_free = 0
    for user, sub in rows:
        # Only free-plan accounts are conversion targets (skip active Pass holders).
        if visa_pass.has_active_pass(sub):
            continue
        total_free += 1
        candidates.append(_features_for(user, sub))

    candidates.sort(key=lambda c: c["intent_score"], reverse=True)
    return candidates[:limit], total_free


# --------------------------------------------------------------------------- #
# The AI strategy layer
# --------------------------------------------------------------------------- #

def _build_prompt(candidates: list[dict]) -> str:
    price = f"₹{visa_pass.PASS_PRICE_PAISE // 100}"
    plays = "\n".join(f"  - {p['id']}: {p['desc']}" for p in PROMOTION_PLAYS)
    # Feed the model only the compact, pre-scored features (never raw DB rows).
    payload = [
        {k: c[k] for k in (
            "user_id", "name", "intent_score", "hit_any_limit", "tenure_days",
            "days_since_last_login", "engagement_events", "onboarding_completed",
            "destination", "visa_type", "heard_about_us", "acquisition_channel", "usage_detail",
        )}
        for c in candidates
    ]
    return f"""You are Rilono's internal Growth Strategist AI, used only by Rilono's own admins.

PRODUCT: the "Visa Success Pass" — a one-time {price} purchase granting 30 days of full
access: unlimited Rilono AI chat, unlimited document uploads & red-flag audits, 3 AI voice
mock interviews, unlimited DS-160 auto-fills and the Chrome copilot. The free tier is
capped (25 AI messages, 5 uploads, 3 interview-prep sessions, 2 mock interviews, 1 red-flag
scan). A referred user's FIRST Pass is ₹200 off.

TASK: for EACH free-plan account below, decide the single best conversion move right now,
based on their real usage. The intent_score (0-100, already computed) reflects how close
they are to buying — weight it heavily but use judgement.

Choose recommended_promotion from EXACTLY these ids:
{plays}

Return ONLY a JSON array (no prose, no code fences). One object per account, same order:
[{{
  "user_id": <int>,
  "intent": "high" | "medium" | "low",
  "segment": "<=4-word label, e.g. 'Power user, hit limit'",
  "recommended_promotion": "<one id from the list>",
  "suggested_message": "1-2 sentence ready-to-send copy, warm and specific to their usage",
  "channel": "email" | "in_app" | "push",
  "priority": <int 1-100, higher = contact sooner>,
  "reason": "one sentence: the usage signal that justifies this play"
}}]

Do not invent facts beyond the data. If signal is weak, use "hold" or "reengagement".

ACCOUNTS:
{json.dumps(payload, ensure_ascii=False)}
"""


def _parse_json_array(text: Optional[str]):
    s = (text or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        s = re.sub(r"\n?```$", "", s).strip()
    try:
        data = json.loads(s)
    except Exception:
        m = re.search(r"\[.*\]", s, re.DOTALL)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except Exception:
            return None
    return data if isinstance(data, list) else None


def _rule_based_reco(c: dict) -> dict:
    """Deterministic fallback so the panel still works when AI is unavailable."""
    if c["hit_any_limit"]:
        play, seg, intent = "limit_reached_offer", "Hit a free limit", "high"
    elif c["days_since_last_login"] is not None and c["days_since_last_login"] > 21:
        play, seg, intent = "reengagement", "Gone quiet", "low"
    elif not c["onboarding_completed"]:
        play, seg, intent = "onboarding_prompt", "Not activated", "low"
    elif c["intent_score"] >= 45:
        play, seg, intent = "value_recap_discount", "Active, warming up", "medium"
    elif c["engagement_events"] == 0:
        play, seg, intent = "hold", "No activity yet", "low"
    else:
        play, seg, intent = "feature_highlight", "Exploring", "medium"
    return {
        "user_id": c["user_id"], "intent": intent, "segment": seg,
        "recommended_promotion": play, "suggested_message": "", "channel": "email",
        "priority": int(c["intent_score"]), "reason": "Rule-based (AI model unavailable).",
    }


def run_conversion_analysis(db: Session, limit: int = GROWTH_AGENT_MAX_CANDIDATES) -> dict:
    candidates, total_free = compute_candidates(db, limit=limit)
    now_iso = datetime.now(timezone.utc).isoformat()
    by_id = {c["user_id"]: c for c in candidates}

    if not candidates:
        return {"generated_at": now_iso, "model_used": None, "ai_used": False,
                "total_free_accounts": total_free, "analyzed_count": 0, "recommendations": []}

    plays_by_id = {p["id"]: p["label"] for p in PROMOTION_PLAYS}
    recos_by_user: dict[int, dict] = {}
    ai_used = False
    model_used = None

    if is_ai_configured():
        prompt = _build_prompt(candidates)
        parsed = None
        for candidate_model in _model_candidates():
            try:
                model = genai.GenerativeModel(candidate_model)
                response = model.generate_content(prompt)
                ai_usage.record_gemini_usage("growth_agent", candidate_model, response)
                parsed = _parse_json_array(getattr(response, "text", None))
                if parsed:
                    model_used = candidate_model
                    break
            except Exception:
                logger.warning("Growth agent model '%s' failed; trying next candidate", candidate_model)
                continue
        if parsed:
            ai_used = True
            for item in parsed:
                try:
                    uid = int(item.get("user_id"))
                except Exception:
                    continue
                if uid not in by_id:
                    continue
                play = str(item.get("recommended_promotion") or "").strip()
                recos_by_user[uid] = {
                    "user_id": uid,
                    "intent": str(item.get("intent") or "").lower() or "medium",
                    "segment": str(item.get("segment") or "")[:60],
                    "recommended_promotion": play if play in _PROMOTION_IDS else "feature_highlight",
                    "suggested_message": str(item.get("suggested_message") or "")[:400],
                    "channel": str(item.get("channel") or "email").lower(),
                    "priority": max(1, min(100, int(item.get("priority") or by_id[uid]["intent_score"]))),
                    "reason": str(item.get("reason") or "")[:300],
                }

    # Assemble final rows for every candidate (AI reco if present, else rule-based),
    # enriched with the deterministic account data for display.
    recommendations = []
    for c in candidates:
        r = recos_by_user.get(c["user_id"]) or _rule_based_reco(c)
        r["promotion_label"] = plays_by_id.get(r["recommended_promotion"], r["recommended_promotion"])
        recommendations.append({**r, "account": {
            "user_id": c["user_id"], "name": c["name"], "email": c["email"],
            "destination": c["destination"], "visa_type": c["visa_type"],
            "intent_score": c["intent_score"], "tenure_days": c["tenure_days"],
            "days_since_last_login": c["days_since_last_login"],
            "hit_any_limit": c["hit_any_limit"], "usage_detail": c["usage_detail"],
            "heard_about_us": c["heard_about_us"], "acquisition_channel": c["acquisition_channel"],
        }})

    recommendations.sort(key=lambda x: x["priority"], reverse=True)
    return {
        "generated_at": now_iso,
        "model_used": model_used,
        "ai_used": ai_used,
        "total_free_accounts": total_free,
        "analyzed_count": len(recommendations),
        "recommendations": recommendations,
    }


def analyze_account(db: Session, user_id: int) -> dict:
    """Single-account conversion recommendation (for the admin 'Manage account' view)."""
    user = db.query(models.User).filter(models.User.id == int(user_id)).first()
    if not user:
        return {"found": False}
    sub = db.query(models.Subscription).filter(models.Subscription.user_id == user.id).first()
    if not sub:
        return {"found": True, "is_pass_active": False, "features": None,
                "recommendation": None, "ai_used": False, "model_used": None}

    is_pass = visa_pass.has_active_pass(sub)
    feat = _features_for(user, sub)
    plays_by_id = {p["id"]: p["label"] for p in PROMOTION_PLAYS}

    reco = None
    ai_used = False
    model_used = None
    if is_ai_configured():
        prompt = _build_prompt([feat])
        for candidate_model in _model_candidates():
            try:
                model = genai.GenerativeModel(candidate_model)
                response = model.generate_content(prompt)
                ai_usage.record_gemini_usage("growth_agent_single", candidate_model, response)
                parsed = _parse_json_array(getattr(response, "text", None))
                if parsed:
                    item = parsed[0]
                    play = str(item.get("recommended_promotion") or "").strip()
                    reco = {
                        "user_id": feat["user_id"],
                        "intent": str(item.get("intent") or "").lower() or "medium",
                        "segment": str(item.get("segment") or "")[:60],
                        "recommended_promotion": play if play in _PROMOTION_IDS else "feature_highlight",
                        "suggested_message": str(item.get("suggested_message") or "")[:400],
                        "channel": str(item.get("channel") or "email").lower(),
                        "priority": max(1, min(100, int(item.get("priority") or feat["intent_score"]))),
                        "reason": str(item.get("reason") or "")[:300],
                    }
                    model_used = candidate_model
                    ai_used = True
                    break
            except Exception:
                logger.warning("analyze_account model '%s' failed; trying next", candidate_model)
                continue

    if reco is None:
        reco = _rule_based_reco(feat)
    reco["promotion_label"] = plays_by_id.get(reco["recommended_promotion"], reco["recommended_promotion"])
    return {"found": True, "is_pass_active": is_pass, "features": feat,
            "recommendation": reco, "ai_used": ai_used, "model_used": model_used}
