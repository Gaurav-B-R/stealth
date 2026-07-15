"""
Gemini AI usage & cost tracking.

Every Gemini call's token usage (from the response's usage_metadata) is logged with
an estimated USD cost so the admin console can show how much we're spending on the
Gemini API. The cost is an ESTIMATE from published per-token pricing — cross-check
against the actual GCP/AI Studio invoice for billing.

Known gaps vs the invoice (kept deliberately, documented here):
- Google Search grounding (news feed/ingestion) is billed PER REQUEST above a free
  tier, not per token — those request fees are not modeled here.
- Explicit context-cache STORAGE (per token-hour) is not modeled; only the cached-
  input token discount is.
"""

import os
import logging
import contextvars
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timedelta

from sqlalchemy import func

from app.database import SessionLocal
from app import models

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Per-account attribution context
# ---------------------------------------------------------------------------
# A request-scoped marker of WHO is incurring AI cost, so every Gemini call can be
# attributed to a user (B2C) or organization (B2B). Set by middleware/endpoints;
# read by record_gemini_usage. Falls back to None (cost still recorded, unattributed).
_usage_account: "contextvars.ContextVar[dict | None]" = contextvars.ContextVar("rilono_usage_account", default=None)


def set_usage_account(*, email: str | None = None, user_id: int | None = None,
                      organization_id: int | None = None) -> "contextvars.Token":
    """Mark the current request's billing account. Returns a token for reset_usage_account()."""
    return _usage_account.set({"email": email, "user_id": user_id, "organization_id": organization_id})


def reset_usage_account(token: "contextvars.Token | None" = None) -> None:
    try:
        if token is not None:
            _usage_account.reset(token)
        else:
            _usage_account.set(None)
    except Exception:
        pass


def current_usage_account() -> dict | None:
    return _usage_account.get()

# Approx Gemini API pricing in USD per 1,000,000 tokens (input, output).
# Editable here or via env (GEMINI_PRICE_<input|output>_PER_M for the default rate).
# Keys are matched as substrings of the model name (longest match wins).
PRICING_PER_MILLION = {
    # Gemini 3-series Pro (substring match also covers gemini-3.1-pro-preview).
    # Based on Gemini 3 Pro list pricing (≤200k context) — cross-check the invoice.
    "gemini-3.1-pro": (2.00, 12.00),
    "gemini-3-pro": (2.00, 12.00),
    "gemini-2.5-pro": (1.25, 10.00),
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.0-flash-lite": (0.075, 0.30),
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-1.5-pro": (1.25, 5.00),
    "gemini-1.5-flash-8b": (0.0375, 0.15),
    "gemini-1.5-flash": (0.075, 0.30),
}
_DEFAULT_INPUT = float(os.getenv("GEMINI_PRICE_INPUT_PER_M", "0.30"))
_DEFAULT_OUTPUT = float(os.getenv("GEMINI_PRICE_OUTPUT_PER_M", "2.50"))

# Pro models charge a higher rate once the prompt exceeds a context threshold:
# model-key -> (prompt_token_threshold, input_rate, output_rate) for the large tier.
LONG_CONTEXT_TIERS = {
    "gemini-2.5-pro": (200_000, 2.50, 15.00),
    "gemini-1.5-pro": (128_000, 2.50, 10.00),
}

# Gemini 2.5 caches (implicit by default, or explicit) bill cached input tokens at a
# discount. Google prices cached input at ~25% of the normal input rate (a 75% saving).
CACHED_INPUT_MULTIPLIER = float(os.getenv("GEMINI_CACHED_INPUT_MULTIPLIER", "0.25"))


def _rates_for(model_name: str, prompt_tokens: int = 0) -> tuple[float, float]:
    name = str(model_name or "").strip().lower()
    best = None
    for key, rates in PRICING_PER_MILLION.items():
        if key in name and (best is None or len(key) > len(best[0])):
            best = (key, rates)
    if best is None:
        return (_DEFAULT_INPUT, _DEFAULT_OUTPUT)
    tier = LONG_CONTEXT_TIERS.get(best[0])
    if tier and int(prompt_tokens or 0) > tier[0]:
        return (tier[1], tier[2])
    return best[1]


def estimate_cost(model_name: str, prompt_tokens: int, output_tokens: int, cached_tokens: int = 0) -> Decimal:
    """Estimate a call's USD cost. `cached_tokens` is the subset of prompt_tokens served
    from Gemini's context cache — billed at CACHED_INPUT_MULTIPLIER of the input rate."""
    in_rate, out_rate = _rates_for(model_name, prompt_tokens)
    cached = max(0, min(int(cached_tokens or 0), int(prompt_tokens or 0)))
    fresh_input = int(prompt_tokens or 0) - cached
    cost = (Decimal(fresh_input) / Decimal(1_000_000)) * Decimal(str(in_rate)) \
        + (Decimal(cached) / Decimal(1_000_000)) * Decimal(str(in_rate)) * Decimal(str(CACHED_INPUT_MULTIPLIER)) \
        + (Decimal(output_tokens) / Decimal(1_000_000)) * Decimal(str(out_rate))
    return cost.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def _extract_tokens(response) -> tuple[int, int, int, int]:
    um = getattr(response, "usage_metadata", None)
    if um is None:
        return 0, 0, 0, 0
    def g(attr):
        try:
            return int(getattr(um, attr, 0) or 0)
        except (TypeError, ValueError):
            return 0
    pt = g("prompt_token_count")
    # Thinking models (Gemini 2.5+) report reasoning tokens separately in
    # thoughts_token_count, but Google BILLS them at the output rate — omitting
    # them silently undercounts every thinking-model call's cost.
    ot = g("candidates_token_count") + g("thoughts_token_count")
    tt = g("total_token_count") or (pt + ot)
    ct = g("cached_content_token_count")  # cached input tokens (implicit or explicit)
    return pt, ot, tt, ct


def _resolve_account(db, *, user_id, organization_id) -> tuple[int | None, int | None]:
    """Resolve (user_id, organization_id) from explicit args first, then the request
    context. If only an email is known in context, look up the user id."""
    if user_id is None and organization_id is None:
        ctx = _usage_account.get() or {}
        user_id = ctx.get("user_id")
        organization_id = ctx.get("organization_id")
        if user_id is None and ctx.get("email"):
            try:
                row = db.query(models.User.id).filter(models.User.email == ctx["email"]).first()
                user_id = row[0] if row else None
            except Exception:
                user_id = None
    return user_id, organization_id


def record_gemini_usage(source: str, model_name: str, response, *,
                        user_id: int | None = None, organization_id: int | None = None) -> None:
    """Best-effort: log one Gemini call's token usage + estimated cost, attributed to the
    account that incurred it (explicit args, else the request context). Never raises."""
    try:
        pt, ot, tt, ct = _extract_tokens(response)
        if tt <= 0:
            return
        ct = max(0, min(ct, pt))
        cost = estimate_cost(model_name, pt, ot, cached_tokens=ct)
        db = SessionLocal()
        try:
            uid, oid = _resolve_account(db, user_id=user_id, organization_id=organization_id)
            db.add(models.GeminiUsageEvent(
                source=str(source or "unknown")[:64],
                model=str(model_name or "unknown")[:80],
                user_id=uid, organization_id=oid,
                prompt_tokens=pt, output_tokens=ot, total_tokens=tt, cached_tokens=ct,
                estimated_cost_usd=cost,
            ))
            db.commit()
        finally:
            db.close()
        # Surface the caching win in the AI-optimization dashboard (best-effort).
        if ct > 0:
            try:
                from app import ai_guardrails
                in_rate, _ = _rates_for(model_name)
                saved = (Decimal(ct) / Decimal(1_000_000)) * Decimal(str(in_rate)) \
                    * (Decimal("1") - Decimal(str(CACHED_INPUT_MULTIPLIER)))
                ai_guardrails.record_cache_event(
                    "cache_hit", source, tokens_saved=ct, model=model_name,
                    cost_saved_usd=saved.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP),
                )
            except Exception:
                pass
    except Exception:
        logger.debug("Failed to record Gemini usage (source=%s)", source, exc_info=True)


def record_tts_usage(source: str, voice_name: str, characters: int, *,
                     cost_usd: float, user_id: int | None = None) -> None:
    """Best-effort: log one neural-TTS synthesis in the same usage ledger as Gemini
    calls, so voice spend shows up in the admin cost tracker per source/user.
    Characters are stored in the token columns (TTS bills per character). Never raises."""
    try:
        chars = max(0, int(characters or 0))
        if chars <= 0:
            return
        db = SessionLocal()
        try:
            uid, oid = _resolve_account(db, user_id=user_id, organization_id=None)
            db.add(models.GeminiUsageEvent(
                source=str(source or "unknown")[:64],
                model=f"gcp-tts/{str(voice_name or 'unknown')[:60]}",
                user_id=uid, organization_id=oid,
                prompt_tokens=chars, output_tokens=0, total_tokens=chars, cached_tokens=0,
                estimated_cost_usd=Decimal(str(cost_usd or 0)).quantize(
                    Decimal("0.000001"), rounding=ROUND_HALF_UP),
            ))
            db.commit()
        finally:
            db.close()
    except Exception:
        logger.debug("Failed to record TTS usage (source=%s)", source, exc_info=True)


# ---------------------------------------------------------------------------
# Analytics for the admin console
# ---------------------------------------------------------------------------

SOURCE_LABELS = {
    "mock_interview_tts": "Mock interview — officer neural voice (TTS)",
    "document_ai": "Document AI (validation & extraction)",
    "student_ai_chat": "Student AI chat (website)",
    "student_ai_chat_copilot": "Student AI chat — Rilono Copilot (Chrome extension)",
    "enterprise_copilot": "Enterprise AI assistant",
    "enterprise_copilot_extension": "Enterprise Copilot — staff mode (Chrome extension)",
    "deep_scan": "Deep Scan document audit",
    "deep_scan_extract": "Deep Scan — per-document extraction",
    "mock_interview": "Mock interviews",
    "interview_feedback": "Interview feedback",
    "red_flag_scan": "Red-Flag scan (Visa Success Pass)",
    "student_voice_interview": "Voice mock interview (Visa Success Pass)",
    "growth_agent": "Conversion Agent — bulk scan (internal)",
    "growth_agent_single": "Conversion Agent — single account (internal)",
    "news.f1_latest": "Visa news feed (grounded search)",
    "news.f1_interview_experiences": "Interview experiences feed (grounded search)",
    "news.f1_ingestion": "Visa news ingestion (scheduled, grounded)",  # legacy (pre multi-destination)
    "news.ingestion.us": "Visa news ingestion — US (scheduled)",
    "news.ingestion.uk": "Visa news ingestion — UK (scheduled)",
    "news.ingestion.ca": "Visa news ingestion — Canada (scheduled)",
    "news.ingestion.au": "Visa news ingestion — Australia (scheduled)",
    "news.ingestion.de": "Visa news ingestion — Germany (scheduled)",
    "news.ingestion.ie": "Visa news ingestion — Ireland (scheduled)",
    "daily_ai_notifier": "Daily AI notifications",
}


def _money(value) -> float:
    return round(float(value or 0), 6)


def build_ai_usage_analytics(db) -> dict:
    E = models.GeminiUsageEvent
    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    week_start = now - timedelta(days=7)
    thirty_start = (now - timedelta(days=29)).replace(hour=0, minute=0, second=0, microsecond=0)

    def stats(start=None):
        q = db.query(
            func.coalesce(func.sum(E.estimated_cost_usd), 0),
            func.coalesce(func.sum(E.total_tokens), 0),
            func.count(E.id),
            func.coalesce(func.sum(E.cached_tokens), 0),
            func.coalesce(func.sum(E.prompt_tokens), 0),
        )
        if start is not None:
            q = q.filter(E.created_at >= start)
        cost, tokens, calls, cached, prompt = q.one()
        cached = int(cached or 0); prompt = int(prompt or 0)
        # Money saved by caching ≈ cached tokens × input rate × the 75% discount.
        saved = round(float(cached) / 1_000_000 * float(_DEFAULT_INPUT) * (1 - CACHED_INPUT_MULTIPLIER), 6)
        return {
            "cost_usd": _money(cost), "tokens": int(tokens or 0), "calls": int(calls or 0),
            "cached_tokens": cached,
            "cache_hit_pct": round(cached / prompt * 100, 1) if prompt else 0.0,
            "cache_saved_usd": saved,
        }

    by_source = []
    for src, cost, tokens, calls in (
        db.query(E.source, func.coalesce(func.sum(E.estimated_cost_usd), 0),
                 func.coalesce(func.sum(E.total_tokens), 0), func.count(E.id))
        .group_by(E.source).all()
    ):
        by_source.append({
            "source": src, "label": SOURCE_LABELS.get(src, src),
            "cost_usd": _money(cost), "tokens": int(tokens or 0), "calls": int(calls or 0),
        })
    by_source.sort(key=lambda r: r["cost_usd"], reverse=True)

    by_model = []
    for mdl, cost, tokens, calls in (
        db.query(E.model, func.coalesce(func.sum(E.estimated_cost_usd), 0),
                 func.coalesce(func.sum(E.total_tokens), 0), func.count(E.id))
        .group_by(E.model).all()
    ):
        by_model.append({
            "model": mdl, "cost_usd": _money(cost), "tokens": int(tokens or 0), "calls": int(calls or 0),
        })
    by_model.sort(key=lambda r: r["cost_usd"], reverse=True)

    # Daily series (last 30 days) bucketed in Python for dialect portability.
    buckets = {}
    for created_at, cost, tokens in (
        db.query(E.created_at, E.estimated_cost_usd, E.total_tokens)
        .filter(E.created_at >= thirty_start).all()
    ):
        if created_at is None:
            continue
        day = (created_at.date() if hasattr(created_at, "date") else datetime.utcnow().date())
        b = buckets.setdefault(day, {"cost_usd": 0.0, "tokens": 0, "calls": 0})
        b["cost_usd"] += float(cost or 0); b["tokens"] += int(tokens or 0); b["calls"] += 1
    daily = []
    for i in range(29, -1, -1):
        d = (now - timedelta(days=i)).date()
        b = buckets.get(d, {"cost_usd": 0.0, "tokens": 0, "calls": 0})
        daily.append({"date": d.isoformat(), "cost_usd": round(b["cost_usd"], 6), "tokens": b["tokens"], "calls": b["calls"]})

    return {
        "currency": "USD",
        "is_estimate": True,
        "totals": {
            "today": stats(today_start),
            "last_7_days": stats(week_start),
            "this_month": stats(month_start),
            "all_time": stats(None),
        },
        "by_source": by_source,
        "by_model": by_model,
        "daily": daily,
        "pricing_note": "Estimated from Gemini per-token pricing; cross-check the GCP/AI Studio invoice.",
    }
