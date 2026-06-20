"""
Gemini AI usage & cost tracking.

Every Gemini call's token usage (from the response's usage_metadata) is logged with
an estimated USD cost so the admin console can show how much we're spending on the
Gemini API. The cost is an ESTIMATE from published per-token pricing — cross-check
against the actual GCP/AI Studio invoice for billing.
"""

import os
import logging
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timedelta

from sqlalchemy import func

from app.database import SessionLocal
from app import models

logger = logging.getLogger(__name__)

# Approx Gemini API pricing in USD per 1,000,000 tokens (input, output).
# Editable here or via env (GEMINI_PRICE_<input|output>_PER_M for the default rate).
# Keys are matched as substrings of the model name (longest match wins).
PRICING_PER_MILLION = {
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


def _rates_for(model_name: str) -> tuple[float, float]:
    name = str(model_name or "").strip().lower()
    best = None
    for key, rates in PRICING_PER_MILLION.items():
        if key in name and (best is None or len(key) > len(best[0])):
            best = (key, rates)
    return best[1] if best else (_DEFAULT_INPUT, _DEFAULT_OUTPUT)


def estimate_cost(model_name: str, prompt_tokens: int, output_tokens: int) -> Decimal:
    in_rate, out_rate = _rates_for(model_name)
    cost = (Decimal(prompt_tokens) / Decimal(1_000_000)) * Decimal(str(in_rate)) \
        + (Decimal(output_tokens) / Decimal(1_000_000)) * Decimal(str(out_rate))
    return cost.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def _extract_tokens(response) -> tuple[int, int, int]:
    um = getattr(response, "usage_metadata", None)
    if um is None:
        return 0, 0, 0
    def g(attr):
        try:
            return int(getattr(um, attr, 0) or 0)
        except (TypeError, ValueError):
            return 0
    pt = g("prompt_token_count")
    ot = g("candidates_token_count")
    tt = g("total_token_count") or (pt + ot)
    return pt, ot, tt


def record_gemini_usage(source: str, model_name: str, response) -> None:
    """Best-effort: log one Gemini call's token usage + estimated cost. Never raises."""
    try:
        pt, ot, tt = _extract_tokens(response)
        if tt <= 0:
            return
        cost = estimate_cost(model_name, pt, ot)
        db = SessionLocal()
        try:
            db.add(models.GeminiUsageEvent(
                source=str(source or "unknown")[:64],
                model=str(model_name or "unknown")[:80],
                prompt_tokens=pt, output_tokens=ot, total_tokens=tt,
                estimated_cost_usd=cost,
            ))
            db.commit()
        finally:
            db.close()
    except Exception:
        logger.debug("Failed to record Gemini usage (source=%s)", source, exc_info=True)


# ---------------------------------------------------------------------------
# Analytics for the admin console
# ---------------------------------------------------------------------------

SOURCE_LABELS = {
    "document_ai": "Document AI (validation & extraction)",
    "student_ai_chat": "Student AI chat",
    "enterprise_copilot": "Enterprise AI copilot",
    "deep_scan": "Deep Scan document audit",
    "mock_interview": "Mock interviews",
    "interview_feedback": "Interview feedback",
    "red_flag_scan": "Red-Flag scan (Visa Pass)",
    "ds160_autofill": "DS-160 auto-fill (Visa Pass)",
    "student_voice_interview": "Voice mock interview (Visa Pass)",
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
        )
        if start is not None:
            q = q.filter(E.created_at >= start)
        cost, tokens, calls = q.one()
        return {"cost_usd": _money(cost), "tokens": int(tokens or 0), "calls": int(calls or 0)}

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
