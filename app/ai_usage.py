"""
Gemini AI usage & cost tracking.

Every Gemini call's token usage (from the response's usage_metadata) is logged with
an estimated USD cost so the admin console can show how much we're spending on the
Gemini API. The cost is an ESTIMATE from published pricing — cross-check against the
actual GCP/AI Studio invoice for billing.

Google never returns a price. A response carries token COUNTS only, so every dollar
figure here is our own arithmetic against the tables below; when Google changes a
rate, nothing breaks and nothing warns — the numbers just quietly go wrong. That is
why `_rates_for` now logs unknown models instead of silently defaulting.

Cost has TWO components, because Google bills two different ways:
1. Tokens — input / output / cached, priced per million (PRICING_PER_MILLION).
2. Google Search grounding — billed PER REQUEST above a free tier, with NO token
   field to read (SEARCH_PRICING). A grounded prompt can fire a dozen searches; the
   2026-07 invoice showed $35.39 of search fees against $77.37 of tokens, i.e. a
   third of the bill was invisible to a token-only meter. The executed queries ARE
   on the response as grounding_metadata.web_search_queries, so they are metered
   here off the response itself — never off which code branch ran, because the
   ungrounded fallback path logs under the same usage source.

Known gaps vs the invoice (kept deliberately, documented here):
- Explicit context-cache STORAGE (per token-hour) is not modeled; only the cached-
  input token discount is. Explicit caching is off (GEMINI_CONTEXT_CACHE_ENABLED),
  so this is $0 today.
- Free-tier consumption is reconstructed from OUR ledger, so calls made with the
  same API key from outside this app (local dev, scripts) shift the real free-tier
  boundary without us seeing it.
"""

import os
import logging
import contextvars
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timedelta, time as dtime

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
    "gemini-3.1-pro": (200_000, 4.00, 18.00),
    "gemini-3-pro": (200_000, 4.00, 18.00),
    "gemini-2.5-pro": (200_000, 2.50, 15.00),
    "gemini-1.5-pro": (128_000, 2.50, 10.00),
}

# Cached input tokens (implicit on 2.5+, or explicit) bill at a discount. Google prices
# cached input at 10% of the normal input rate, consistently across the current lineup —
# 3.1 Pro $0.20 vs $2.00, 2.5 Pro $0.125 vs $1.25, 2.5 Flash $0.03 vs $0.30. This was
# 0.25 until the 2026-08 invoice reconciliation, which OVERSTATED cached spend 2.5x.
CACHED_INPUT_MULTIPLIER = float(os.getenv("GEMINI_CACHED_INPUT_MULTIPLIER", "0.10"))

# Models we have billed and priced. Anything outside this set silently fell through to
# _DEFAULT_* before — the 2026-07 invoice carried gemini-3.5-flash and
# gemini-3.1-flash-lite-preview SKUs that no table entry matched. Warn once per unknown
# model rather than inventing a rate: a wrong price is worse than a loud gap.
_warned_models: set[str] = set()


def _rates_for(model_name: str, prompt_tokens: int = 0) -> tuple[float, float]:
    name = str(model_name or "").strip().lower()
    best = None
    for key, rates in PRICING_PER_MILLION.items():
        if key in name and (best is None or len(key) > len(best[0])):
            best = (key, rates)
    if best is None:
        if name and name not in _warned_models:
            _warned_models.add(name)
            logger.warning(
                "No Gemini price entry for model %r — billing it at the default "
                "$%s/$%s per M. Add it to PRICING_PER_MILLION; its real cost is unknown.",
                name, _DEFAULT_INPUT, _DEFAULT_OUTPUT,
            )
        return (_DEFAULT_INPUT, _DEFAULT_OUTPUT)
    tier = LONG_CONTEXT_TIERS.get(best[0])
    if tier and int(prompt_tokens or 0) > tier[0]:
        return (tier[1], tier[2])
    return best[1]


# ---------------------------------------------------------------------------
# Google Search grounding — a PER-REQUEST fee, not a token cost
# ---------------------------------------------------------------------------
# Gemini 3.x bills every individual search query the model decides to run ("if the
# model decides to execute multiple search queries to answer a single prompt ... this
# counts as two billable uses"). Gemini 2.5 and older bill per grounded PROMPT instead,
# however many searches it triggers. Both sit above a free allowance, which is why cost
# stays flat for weeks and then steps up mid-month — on 2026-07-30 the 5,000 free
# searches ran out and the daily bill roughly tripled with no change in traffic.
SEARCH_FREE_PER_MONTH_GEMINI_3 = int(os.getenv("GEMINI_SEARCH_FREE_PER_MONTH", "5000"))
SEARCH_USD_PER_1K_GEMINI_3 = float(os.getenv("GEMINI_SEARCH_USD_PER_1K", "14.0"))
SEARCH_FREE_PER_DAY_LEGACY = int(os.getenv("GEMINI_SEARCH_FREE_PER_DAY_LEGACY", "1500"))
SEARCH_USD_PER_1K_LEGACY = float(os.getenv("GEMINI_SEARCH_USD_PER_1K_LEGACY", "35.0"))


def _bills_search_per_query(model_name: str) -> bool:
    """True for Gemini 3.x (billed per search query), False for 2.5 and older (per prompt)."""
    return "gemini-3" in str(model_name or "").strip().lower()


def _search_units(model_name: str, search_queries: int) -> int:
    """Billable grounding units for one call: distinct queries on 3.x, else 1 per prompt."""
    queries = max(0, int(search_queries or 0))
    if queries <= 0:
        return 0
    return queries if _bills_search_per_query(model_name) else 1


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


def _extract_search_queries(response) -> int:
    """Count the DISTINCT non-empty Google Search queries this response's model executed.

    Read off grounding_metadata.web_search_queries, which every grounded response already
    carries — the same object course_catalog/news already walk for citation URLs. Counting
    here (rather than at the grounded call sites) is deliberate: those helpers fall back to
    an UNGROUNDED request under the same usage source, so branch-based counting over-bills.
    An empty list means no search ran and nothing is charged.

    Distinct + non-empty matches Google's stated rule: "we ignore the empty web search
    queries when counting unique queries".
    """
    queries: set[str] = set()
    try:
        for candidate in (getattr(response, "candidates", None) or []):
            meta = getattr(candidate, "grounding_metadata", None)
            if meta is None:
                continue
            for query in (getattr(meta, "web_search_queries", None) or []):
                text = str(query or "").strip()
                if text:
                    queries.add(text)
    except Exception:
        return 0
    return len(queries)


def _search_units_already_used(db, model_name: str, now: datetime) -> int:
    """Grounding units this billing period has already consumed, from our own ledger.

    Needed because the fee is zero until a free allowance is exhausted, so the SAME call
    costs $0 or $0.014 depending only on what ran before it. Gemini 3.x pools 5,000 free
    searches per CALENDAR MONTH; 2.5 and older get a daily grounded-prompt allowance.
    """
    E = models.GeminiUsageEvent
    per_query = _bills_search_per_query(model_name)
    if per_query:
        period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        period_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    q = db.query(func.coalesce(func.sum(E.search_queries), 0)).filter(
        E.created_at >= period_start, E.search_queries > 0
    )
    # The two allowances are separate pools, so only count the matching model family.
    q = q.filter(E.model.ilike("gemini-3%")) if per_query else q.filter(~E.model.ilike("gemini-3%"))
    try:
        return int(q.scalar() or 0)
    except Exception:
        return 0


def estimate_search_cost(model_name: str, units: int, already_used: int = 0) -> Decimal:
    """USD for `units` grounding requests, given how many the period already consumed.

    Only the portion past the free allowance is charged, so a call that straddles the
    boundary is split rather than billed all-or-nothing.
    """
    units = max(0, int(units or 0))
    if units <= 0:
        return Decimal("0")
    if _bills_search_per_query(model_name):
        free, per_1k = SEARCH_FREE_PER_MONTH_GEMINI_3, SEARCH_USD_PER_1K_GEMINI_3
    else:
        free, per_1k = SEARCH_FREE_PER_DAY_LEGACY, SEARCH_USD_PER_1K_LEGACY
    used = max(0, int(already_used or 0))
    billable = max(0, (used + units) - free) - max(0, used - free)
    cost = (Decimal(billable) / Decimal(1000)) * Decimal(str(per_1k))
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
    # Thinking models (Gemini 2.5+) spend reasoning tokens that Google BILLS at the
    # OUTPUT rate. Newer SDKs surface them as thoughts_token_count, but the pinned
    # google-ai-generativelanguage exposes only prompt/candidates/cached/total on
    # UsageMetadata — so reading that attribute alone silently prices every thinking
    # token at zero (on gemini-3.1-pro that is $12/M of real spend recorded as $0).
    # total_token_count DOES include them, so anything the total can't account for is
    # attributed to thinking. Both paths are kept: whichever is available wins, and when
    # neither reports anything extra the derived value is 0 and nothing changes.
    ot = g("candidates_token_count")
    tt_reported = g("total_token_count")
    thoughts = g("thoughts_token_count") or max(0, tt_reported - pt - ot)
    ot += thoughts
    tt = tt_reported or (pt + ot)
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
                        user_id: int | None = None, organization_id: int | None = None,
                        status: str = "ok") -> None:
    """Best-effort: log one Gemini call's token usage, grounding fees and estimated cost,
    attributed to the account that incurred it (explicit args, else the request context).

    `status` marks what the CALLER did with the response, not whether the call succeeded:
    pass "empty" when the response was billed but discarded (no text, failed parse, a
    fallback chain moving to the next candidate). Google charged for it either way, so it
    belongs in the ledger — silently dropping those is how a retry loop bills three times
    and records once. Never raises.
    """
    try:
        pt, ot, tt, ct = _extract_tokens(response)
        searches = _extract_search_queries(response)
        # A grounded call can bill search fees even when usage_metadata is missing, so
        # only bail when there is genuinely nothing chargeable to record.
        if tt <= 0 and searches <= 0:
            return
        ct = max(0, min(ct, pt))
        token_cost = estimate_cost(model_name, pt, ot, cached_tokens=ct)
        db = SessionLocal()
        try:
            units = _search_units(model_name, searches)
            search_cost = (
                estimate_search_cost(model_name, units, _search_units_already_used(db, model_name, datetime.utcnow()))
                if units else Decimal("0")
            )
            uid, oid = _resolve_account(db, user_id=user_id, organization_id=organization_id)
            db.add(models.GeminiUsageEvent(
                source=str(source or "unknown")[:64],
                model=str(model_name or "unknown")[:80],
                user_id=uid, organization_id=oid,
                prompt_tokens=pt, output_tokens=ot, total_tokens=tt, cached_tokens=ct,
                search_queries=units,
                search_cost_usd=search_cost,
                status=str(status or "ok")[:16],
                estimated_cost_usd=token_cost + search_cost,
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
    "enterprise_document_scan": "Document scan & validate (per document, billed)",
    "student_ai_chat": "Student AI chat (website)",
    "student_ai_chat_copilot": "Student AI chat — Rilono Copilot (Chrome extension)",
    "enterprise_copilot": "Enterprise AI assistant",
    "enterprise_copilot_extension": "Enterprise Copilot — staff mode (Chrome extension)",
    "enterprise_copilot_client": "Enterprise Copilot — client invite link",
    "deep_scan": "Deep Scan client audit",
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
    "course_catalog_refresh": "Course catalog agent — discovery & refresh (scheduled, grounded)",
    "enterprise_course_finder": "Course Finder — AI shortlist (enterprise)",
    "course_finder": "Course Finder — AI shortlist (Visa Success Pass)",
    "university_shortlist": "AI University Shortlist (Visa Success Pass)",
    "enterprise_university_shortlist": "University shortlist — AI recommend (enterprise)",
}


def _money(value) -> float:
    return round(float(value or 0), 6)


# Default window for the admin console's date filter, and the span thresholds at which
# the timeline chart switches to coarser buckets (a 6-month range as 180 daily bars is
# unreadable). The per-day table is always per-day regardless of the chart granularity.
DEFAULT_RANGE_DAYS = 30
WEEKLY_BUCKET_AFTER_DAYS = 62
MONTHLY_BUCKET_AFTER_DAYS = 210


def build_ai_usage_analytics(db, *, start=None, end=None) -> dict:
    """Usage/cost analytics. `start`/`end` are inclusive UTC dates bounding the filtered
    view — the range summary, the timeline, the per-day table and both breakdowns all
    honour them. The fixed today/7-day/month/all-time totals ignore the filter on purpose,
    so those anchors stay comparable whatever range is selected."""
    E = models.GeminiUsageEvent
    now = datetime.utcnow()
    today = now.date()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    week_start = now - timedelta(days=7)

    # --- resolve the requested window ---------------------------------------
    earliest_at = db.query(func.min(E.created_at)).scalar()
    earliest_date = earliest_at.date() if hasattr(earliest_at, "date") else None

    # Clamp BOTH bounds to today before swapping a reversed pair — no data can exist in
    # the future, and a future bound would inflate the day count behind avg-per-day.
    end_date = min(end or today, today)
    start_date = min(start or (end_date - timedelta(days=DEFAULT_RANGE_DAYS - 1)), today)
    if start_date > end_date:
        start_date, end_date = end_date, start_date
    range_start = datetime.combine(start_date, dtime.min)
    range_end = datetime.combine(end_date, dtime.min) + timedelta(days=1)  # end is inclusive

    def stats(start=None, end=None):
        q = db.query(
            func.coalesce(func.sum(E.estimated_cost_usd), 0),
            func.coalesce(func.sum(E.total_tokens), 0),
            func.count(E.id),
            func.coalesce(func.sum(E.cached_tokens), 0),
            func.coalesce(func.sum(E.prompt_tokens), 0),
            func.coalesce(func.sum(E.search_cost_usd), 0),
            func.coalesce(func.sum(E.search_queries), 0),
        )
        if start is not None:
            q = q.filter(E.created_at >= start)
        if end is not None:
            q = q.filter(E.created_at < end)
        cost, tokens, calls, cached, prompt, search_cost, searches = q.one()
        cached = int(cached or 0); prompt = int(prompt or 0)
        # Money saved by caching ≈ cached tokens × input rate × the cache discount.
        saved = round(float(cached) / 1_000_000 * float(_DEFAULT_INPUT) * (1 - CACHED_INPUT_MULTIPLIER), 6)
        total = _money(cost)
        search_usd = _money(search_cost)
        return {
            "cost_usd": total, "tokens": int(tokens or 0), "calls": int(calls or 0),
            "cached_tokens": cached,
            "cache_hit_pct": round(cached / prompt * 100, 1) if prompt else 0.0,
            "cache_saved_usd": saved,
            # cost_usd is the TOTAL; split it so grounding is visible next to tokens.
            # Search fees have their own free tier and scale with searches-per-prompt,
            # not with traffic, so they move independently of the token line.
            "token_cost_usd": _money(float(total) - float(search_usd)),
            "search_cost_usd": search_usd,
            "search_queries": int(searches or 0),
        }

    def in_range(q):
        return q.filter(E.created_at >= range_start, E.created_at < range_end)

    by_source = []
    for src, cost, tokens, calls, search_cost, searches in in_range(
        db.query(E.source, func.coalesce(func.sum(E.estimated_cost_usd), 0),
                 func.coalesce(func.sum(E.total_tokens), 0), func.count(E.id),
                 func.coalesce(func.sum(E.search_cost_usd), 0),
                 func.coalesce(func.sum(E.search_queries), 0))
    ).group_by(E.source).all():
        by_source.append({
            "source": src, "label": SOURCE_LABELS.get(src, src),
            "cost_usd": _money(cost), "tokens": int(tokens or 0), "calls": int(calls or 0),
            "search_cost_usd": _money(search_cost), "search_queries": int(searches or 0),
        })
    by_source.sort(key=lambda r: r["cost_usd"], reverse=True)

    by_model = []
    for mdl, cost, tokens, calls in in_range(
        db.query(E.model, func.coalesce(func.sum(E.estimated_cost_usd), 0),
                 func.coalesce(func.sum(E.total_tokens), 0), func.count(E.id))
    ).group_by(E.model).all():
        by_model.append({
            "model": mdl, "cost_usd": _money(cost), "tokens": int(tokens or 0), "calls": int(calls or 0),
        })
    by_model.sort(key=lambda r: r["cost_usd"], reverse=True)

    # Per-day series over the selected range, bucketed in Python for dialect portability.
    buckets = {}
    for created_at, cost, tokens in in_range(
        db.query(E.created_at, E.estimated_cost_usd, E.total_tokens)
    ).all():
        if created_at is None:
            continue
        day = created_at.date() if hasattr(created_at, "date") else today
        b = buckets.setdefault(day, {"cost_usd": 0.0, "tokens": 0, "calls": 0})
        b["cost_usd"] += float(cost or 0); b["tokens"] += int(tokens or 0); b["calls"] += 1

    span_days = (end_date - start_date).days + 1
    daily = []
    for i in range(span_days):
        d = start_date + timedelta(days=i)
        b = buckets.get(d, {"cost_usd": 0.0, "tokens": 0, "calls": 0})
        daily.append({"date": d.isoformat(), "cost_usd": round(b["cost_usd"], 6),
                      "tokens": b["tokens"], "calls": b["calls"]})

    # Chart series: daily for short ranges, rolled up to weeks/months for long ones.
    if span_days <= WEEKLY_BUCKET_AFTER_DAYS:
        granularity, group_size = "day", 1
    elif span_days <= MONTHLY_BUCKET_AFTER_DAYS:
        granularity, group_size = "week", 7
    else:
        granularity, group_size = "month", 0  # calendar months, not fixed-width groups

    series = []
    if granularity == "month":
        month_buckets = {}
        for row in daily:
            key = row["date"][:7]  # YYYY-MM
            b = month_buckets.setdefault(key, {"start": row["date"], "end": row["date"],
                                               "cost_usd": 0.0, "tokens": 0, "calls": 0})
            b["end"] = row["date"]
            b["cost_usd"] += row["cost_usd"]; b["tokens"] += row["tokens"]; b["calls"] += row["calls"]
        for key in sorted(month_buckets):
            b = month_buckets[key]
            series.append({"date": b["start"], "end": b["end"], "label": key,
                           "cost_usd": round(b["cost_usd"], 6), "tokens": b["tokens"], "calls": b["calls"]})
    else:
        for i in range(0, len(daily), group_size):
            chunk = daily[i:i + group_size]
            series.append({
                "date": chunk[0]["date"], "end": chunk[-1]["date"],
                "label": chunk[0]["date"][5:],   # MM-DD of the day / week start
                "cost_usd": round(sum(c["cost_usd"] for c in chunk), 6),
                "tokens": sum(c["tokens"] for c in chunk),
                "calls": sum(c["calls"] for c in chunk),
            })

    range_stats = stats(range_start, range_end)
    active_days = [r for r in daily if r["calls"] > 0]
    top_day = max(daily, key=lambda r: r["cost_usd"]) if daily else None

    return {
        "currency": "USD",
        "is_estimate": True,
        "totals": {
            "today": stats(today_start),
            "last_7_days": stats(week_start),
            "this_month": stats(month_start),
            "all_time": stats(None),
        },
        "range": {
            **range_stats,
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
            "days": span_days,
            "active_days": len(active_days),
            "avg_per_day_usd": round(range_stats["cost_usd"] / span_days, 6) if span_days else 0.0,
            "top_day": ({"date": top_day["date"], "cost_usd": top_day["cost_usd"]}
                        if top_day and top_day["cost_usd"] > 0 else None),
            "granularity": granularity,
        },
        "earliest_event_date": earliest_date.isoformat() if earliest_date else None,
        "by_source": by_source,
        "by_model": by_model,
        "daily": daily,
        "series": series,
        "pricing_note": (
            "Estimated from Gemini list pricing: per-token cost plus Google Search "
            "grounding request fees (free tier applied). Google returns token counts, "
            "never prices — cross-check the GCP invoice grouped by SKU."
        ),
    }
