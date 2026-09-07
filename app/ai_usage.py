"""Durable AI usage accounting with provider counters and explicit estimate quality.

Every application-level Gemini attempt is retained independently of whether the
caller uses its output. Counters are recorded from provider usage metadata; missing
metadata is unknown. Monetary values are versioned list-price estimates and must be
reconciled with Google billing. TTS characters and cache storage are separate units.
"""

import os
import logging
import contextvars
import hashlib
import json
import threading
import fcntl
from contextlib import contextmanager
import uuid
from pathlib import Path
from collections.abc import Mapping
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timedelta, time as dtime

from sqlalchemy import func, case

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
                      organization_id: int | None = None, product: str | None = None,
                      trigger: str | None = None) -> "contextvars.Token":
    """Mark the current request's billing account. Returns a token for reset_usage_account()."""
    return _usage_account.set({"email": email, "user_id": user_id, "organization_id": organization_id,
                               "product": product, "trigger": trigger})


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


def _rates_for(model_name: str, prompt_tokens: int = 0) -> tuple[float, float] | None:
    name = str(model_name or "").strip().lower()
    best = None
    for key, rates in PRICING_PER_MILLION.items():
        if key in name and (best is None or len(key) > len(best[0])):
            best = (key, rates)
    if best is None:
        if name and name not in _warned_models:
            _warned_models.add(name)
            logger.warning(
                "No Gemini price entry for model %r; usage is recorded as unpriced.", name,
            )
        return None
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
    rates = _rates_for(model_name, prompt_tokens)
    if rates is None:
        # Legacy callers require a Decimal. The ledger exposes pricing_status so
        # this absence is never presented as an accurately measured zero cost.
        return Decimal("0")
    in_rate, out_rate = rates
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
        for candidate in (_attr(response, "candidates", None) or []):
            meta = _attr(candidate, "grounding_metadata", None)
            if meta is None:
                continue
            for query in (_attr(meta, "web_search_queries", None) or []):
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


METERING_VERSION = 2
PRICING_VERSION = "gemini-list-estimate-2026-09-06-v2"
_SPOOL_LOCK = threading.Lock()
_metering_health = {"last_write_failure_at": None, "last_replay_at": None, "unrecoverable_writes": 0}


def _attr(obj, name, default=None):
    if isinstance(obj, Mapping):
        if name in obj:
            return obj[name]
        bits = name.split("_")
        return obj.get(bits[0] + "".join(x.title() for x in bits[1:]), default)
    return getattr(obj, name, default)


def _raw_usage(response) -> dict | None:
    """Serialize only Google's usage metadata, never response text or prompts."""
    um = _attr(response, "usage_metadata")
    if um is None:
        return None
    if isinstance(um, Mapping):
        return dict(um)
    if hasattr(um, "model_dump"):
        return um.model_dump(mode="json", exclude_none=True)
    # proto-plus exposes to_dict as a class method.
    converter = getattr(type(um), "to_dict", None)
    if converter:
        try:
            return converter(um)
        except (TypeError, ValueError):
            pass
    names = ("prompt_token_count", "candidates_token_count", "total_token_count",
             "cached_content_token_count", "thoughts_token_count", "tool_use_prompt_token_count",
             "prompt_tokens_details", "cache_tokens_details", "candidates_tokens_details",
             "tool_use_prompt_tokens_details", "traffic_type")
    return {name: getattr(um, name) for name in names if getattr(um, name, None) is not None}


def _counter(raw, name) -> int | None:
    value = _attr(raw or {}, name)
    if value is None or isinstance(value, bool):
        return None
    try:
        number = int(value)
        return number if number >= 0 and number == float(value) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _usage_values(response) -> dict:
    raw = _raw_usage(response)
    prompt = _counter(raw, "prompt_token_count")
    candidate = _counter(raw, "candidates_token_count")
    thought = _counter(raw, "thoughts_token_count")
    tool = _counter(raw, "tool_use_prompt_token_count")
    total = _counter(raw, "total_token_count")
    cached = _counter(raw, "cached_content_token_count")
    # Do not infer thinking from the remainder: tools and other provider counters
    # can contribute to total_token_count. Cached tokens already belong to prompt.
    return {
        "prompt_tokens": prompt or 0, "candidate_tokens": candidate or 0,
        "thought_tokens": thought or 0, "tool_tokens": tool or 0,
        "output_tokens": (candidate or 0) + (thought or 0),
        "total_tokens": total or 0, "cached_tokens": cached or 0,
        "raw_usage_json": json.dumps(raw, default=str, separators=(",", ":")) if raw is not None else None,
        "usage_state": "measured" if prompt is not None and total is not None else "unknown",
    }


def _extract_tokens(response) -> tuple[int, int, int, int]:
    """Compatibility accessor. Missing metadata is flagged by the event's state."""
    values = _usage_values(response)
    return tuple(values[k] for k in ("prompt_tokens", "output_tokens", "total_tokens", "cached_tokens"))


def _resolve_account(db, *, user_id, organization_id) -> tuple[int | None, int | None]:
    if user_id is None and organization_id is None:
        ctx = _usage_account.get() or {}
        user_id, organization_id = ctx.get("user_id"), ctx.get("organization_id")
        if user_id is None and ctx.get("email"):
            row = db.query(models.User.id).filter(models.User.email == ctx["email"]).first()
            user_id = row[0] if row else None
    return user_id, organization_id


def gemini_pricing_context(contents=None, *, generation_config=None, base_generation_config=None, explicit_cache=False):
    """Retain dispatch facts for normal generateContent calls, never prompt text.

    Callers supply their actual generation config. Unknown content types are left
    to Google's modality counters instead of assuming they are text or audio.
    """
    config = generation_config or {}
    tier = _attr(config, "service_tier") or _attr(base_generation_config, "service_tier") or "standard"
    context = {"service_tier": str(getattr(tier, "value", tier)).lower()}
    if os.getenv("GEMINI_PROVIDER", "developer").strip().lower() == "vertex":
        context["location"] = (os.getenv("GOOGLE_CLOUD_LOCATION") or os.getenv("GCP_LOCATION") or "global").strip()
    if isinstance(contents, str) or (isinstance(contents, (list, tuple)) and contents and all(isinstance(part, str) for part in contents)):
        context["input_modalities"] = ["TEXT"]
    if explicit_cache:
        context["explicit_cache"] = True
    return context


def _event_base(source, model_name, *, user_id=None, organization_id=None,
                product=None, trigger=None, event_key=None, provider=None, project_id=None,
                pricing_context=None):
    ctx = _usage_account.get() or {}
    product = product or ctx.get("product")
    if product == "shared":
        user_id = organization_id = None
    elif user_id is None and organization_id is None:
        user_id, organization_id = ctx.get("user_id"), ctx.get("organization_id")
    # Organization attribution wins before any source-based inference. Legacy
    # mock_interview/interview_feedback names are shared by enterprise and B2C.
    if organization_id is not None:
        product = "b2b"
    elif not product:
        if source == "growth_agent" or source == "course_catalog_refresh" or str(source).startswith("news."):
            product = "shared"
            user_id = None
        elif user_id is not None or source in {
                "student_ai_chat", "student_ai_chat_copilot", "student_mock_interview",
                "student_interview_report", "student_visa_prep", "mock_interview_tts",
                "student_voice_interview", "daily_ai_notifier", "sop_generator", "sop_kit",
                "course_finder", "university_shortlist", "red_flag_scan", "growth_agent_single"}:
            product = "b2c"
        else:
            product = "unknown"
    provider = provider or ("vertex" if os.getenv("GEMINI_PROVIDER", "developer").lower() == "vertex" else "developer")
    # Developer API keys do not tell us their owning project. A separate explicit
    # metering project setting avoids falsely assigning them to a Vertex project.
    if not project_id:
        if provider == "vertex":
            project_id = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT")
        elif provider == "developer":
            project_id = os.getenv("GEMINI_DEVELOPER_PROJECT_ID")
    return {"event_key": event_key or uuid.uuid4().hex, "source": str(source or "unknown")[:64],
            "model": str(model_name or "unknown")[:80], "user_id": user_id, "organization_id": organization_id,
            "provider": provider, "project_id": str(project_id)[:128] if project_id else None,
            "product": str(product)[:24], "trigger": str(trigger or ctx.get("trigger") or "unknown")[:24],
            "metering_version": METERING_VERSION, "unit_type": "tokens", "character_count": 0,
            "usage_state": "pending", "pricing_status": "pending", "pricing_version": f"{provider}:{PRICING_VERSION}",
            "created_at": datetime.utcnow().isoformat(), "status": "pending",
            "raw_usage_json": json.dumps({"_rilono_pricing": pricing_context}, separators=(",", ":")) if pricing_context else None,
            # Resolved only inside the database transaction; never persisted in spool.
            "_lookup_email": ctx.get("email") if product != "shared" and user_id is None and organization_id is None else None}


def _spool_dir() -> Path:
    return Path(os.getenv("AI_USAGE_SPOOL_DIR", str(Path(__file__).resolve().parents[1] / "data" / "ai_usage_spool")))


@contextmanager
def _spool_guard():
    # Multi-worker servers may replay while a different worker is completing the
    # same event. A process-shared lock keeps read/replace/unlink atomic together.
    with _SPOOL_LOCK:
        directory = _spool_dir()
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(directory / ".lock", os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield directory
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)


def _spool(payload) -> bool:
    """Atomically retain failed ledger writes on a private local filesystem.

    A persistent volume is required for recovery across host replacement. No prompts,
    generated content, credentials or email addresses are written here.
    """
    try:
        with _spool_guard() as directory:
            target = directory / (hashlib.sha256(payload["event_key"].encode()).hexdigest() + ".json")
            safe = {k: v for k, v in payload.items() if not k.startswith("_")}
            if target.exists():
                old = json.loads(target.read_text())
                # A delayed pending write must never overwrite a completed event.
                if safe.get("usage_state") == "pending" and old.get("usage_state") != "pending":
                    return True
                old.update(safe)
                safe = old
            tmp = directory / (uuid.uuid4().hex + ".tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as handle:
                json.dump(safe, handle, default=str, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, target)
            directory_fd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            return True
    except Exception:
        _metering_health["unrecoverable_writes"] += 1
        logger.error("AI usage recovery spool write failed; manual reconciliation required", exc_info=True)
        return False


def _persist(payload) -> None:
    data = dict(payload)
    email = data.pop("_lookup_email", None)
    if isinstance(data.get("created_at"), str):
        data["created_at"] = datetime.fromisoformat(data["created_at"])
    db = SessionLocal()
    try:
        E = models.GeminiUsageEvent
        row = db.query(E).filter(E.event_key == data["event_key"]).first()
        if row is not None and data.get("usage_state") == "pending" and row.usage_state != "pending":
            return
        if row is not None and row.usage_state == "duplicate" and not data.get("response_id"):
            return  # a late caller status must not erase the duplicate audit marker
        if data.get("response_id"):
            canonical_query = db.query(E).filter(
                E.response_id == data["response_id"], E.provider == data.get("provider"),
                E.project_id == data.get("project_id"), E.usage_state != "duplicate")
            if row is not None:
                canonical_query = canonical_query.filter(E.id != row.id)
            canonical = canonical_query.order_by(E.id).first()
            if canonical is not None:
                if row is None:
                    # Standalone reporting of an existing response is idempotent;
                    # it must never replace the original profile/source or counts.
                    return
                # A separately tracked callback has its own durable pending row.
                # Retain that attempt but contribute no usage or cost a second time.
                data.update(usage_state="duplicate", status="duplicate", pricing_status="duplicate",
                            prompt_tokens=0, output_tokens=0, total_tokens=0, cached_tokens=0,
                            candidate_tokens=0, thought_tokens=0, tool_tokens=0, character_count=0,
                            search_queries=0, search_cost_usd="0", estimated_cost_usd="0")
        if email and data.get("user_id") is None and data.get("organization_id") is None:
            account = db.query(models.User.id).filter(models.User.email == email).first()
            if account:
                data["user_id"] = account[0]
                if data.get("product") == "unknown":
                    data["product"] = "b2c"
        if row is None:
            row = E(**data)
            db.add(row)
        else:
            # Keep initial attribution/time stable when a response is reported again.
            immutable = {"event_key", "created_at", "source", "user_id", "organization_id", "product", "trigger"}
            for key, value in data.items():
                if key not in immutable:
                    setattr(row, key, value)
        db.commit()
    finally:
        db.close()


def _write_event(payload) -> bool:
    try:
        _persist(payload)
        return True
    except Exception:
        _metering_health["last_write_failure_at"] = datetime.utcnow().isoformat()
        logger.error("AI usage database write failed (event=%s); retaining recovery record", payload.get("event_key"), exc_info=True)
        return _spool(payload)


def replay_usage_spool(limit: int = 1000) -> dict:
    """Retry local records idempotently. Safe to run from an authenticated admin job."""
    result = {"replayed": 0, "failed": 0}
    directory = _spool_dir()
    if directory.exists():
        for path in sorted(directory.glob("*.json"))[:max(0, min(int(limit), 10000))]:
            try:
                with _spool_guard():
                    if not path.exists():
                        continue
                    payload = json.loads(path.read_text())
                    _persist(payload)
                    path.unlink()
                result["replayed"] += 1
            except Exception:
                logger.error("AI usage spool replay failed (record=%s)", path.name, exc_info=True)
                result["failed"] += 1
    _metering_health["last_replay_at"] = datetime.utcnow().isoformat()
    return result


def get_metering_health() -> dict:
    try:
        pending = len(list(_spool_dir().glob("*.json")))
    except OSError:
        pending = None
    provider = os.getenv("GEMINI_PROVIDER", "developer").strip().lower()
    project_id = ((os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT")) if provider == "vertex"
                  else os.getenv("GEMINI_DEVELOPER_PROJECT_ID"))
    return {**_metering_health, "spooled_events": pending,
            "spool_requires_persistent_volume": True, "provider": provider,
            "configured_project_id": project_id or None,
            "project_attribution_configured": bool(project_id),
            "authentication_check": "not_performed"}


def _response_event_key(response):
    return _attr(response, "_rilono_usage_event_key")


def _tag_response(response, event_key):
    try:
        if isinstance(response, dict):
            response["_rilono_usage_event_key"] = event_key
        else:
            object.__setattr__(response, "_rilono_usage_event_key", event_key)
    except (AttributeError, TypeError):
        pass


def _complete_event(base, response, status="ok") -> dict:
    result = dict(base)
    result.update(_usage_values(response))
    dispatch = json.loads(base.get("raw_usage_json") or "{}").get("_rilono_pricing")
    if dispatch:
        raw = json.loads(result.get("raw_usage_json") or "{}")
        raw["_rilono_pricing"] = dispatch
        result["raw_usage_json"] = json.dumps(raw, default=str, separators=(",", ":"))
    result["response_id"] = _attr(response, "response_id")
    actual_model = _attr(response, "model_version")
    if actual_model:
        result["model"] = str(actual_model)[:80]
    result["status"] = str(status or "ok")[:16]
    queries = _extract_search_queries(response)
    units = _search_units(result["model"], queries)
    result["search_queries"] = units
    # Grounding allowances depend on provider, project and tier. Never deduct a
    # reconstructed app-only free tier and present it as the billed amount.
    per_1k = SEARCH_USD_PER_1K_GEMINI_3 if _bills_search_per_query(result["model"]) else SEARCH_USD_PER_1K_LEGACY
    search_cost = (Decimal(units) * Decimal(str(per_1k)) / Decimal(1000)).quantize(Decimal("0.000001"))
    result["search_cost_usd"] = str(search_cost)
    rates = _rates_for(result["model"], result["prompt_tokens"] + result["tool_tokens"])
    status = "estimated" if rates else "unpriced"
    if result["usage_state"] != "measured":
        status = "unknown"
    elif rates:
        model = result["model"].lower()
        raw = (result["raw_usage_json"] or "").lower()
        # This table prices ordinary text generation. Preserve exact counters for
        # other modalities/unknown total components but mark financial coverage.
        unaccounted = result["total_tokens"] != (result["prompt_tokens"] + result["output_tokens"] + result["tool_tokens"])
        if any(term in model for term in ("audio", "image", "tts", "live")):
            status = "unpriced"
        elif unaccounted or 'audio' in raw or result["cached_tokens"] > result["prompt_tokens"]:
            status = "partial"
        elif units:
            status = "partial"  # list search estimate; shared allowance not known
        elif result["provider"] == "vertex":
            # The inherited rate table is a Developer API estimate. Vertex billing
            # can differ by SKU, region and processing tier; do not claim coverage.
            status = "partial"
    token_cost = estimate_cost(result["model"], result["prompt_tokens"] + result["tool_tokens"],
                               result["output_tokens"], result["cached_tokens"]) if status in {"estimated", "partial"} else Decimal("0")
    result["estimated_cost_usd"] = str(token_cost + search_cost)
    result["pricing_status"] = status
    return result


def _record_cache_saving(event):
    """Preserve the existing optimization dashboard without changing accounting."""
    cached = int(event.get("cached_tokens") or 0)
    rates = _rates_for(event.get("model"))
    if cached <= 0 or rates is None or event.get("usage_state") != "measured":
        return
    try:
        from app import ai_guardrails
        saved = Decimal(cached) / Decimal(1_000_000) * Decimal(str(rates[0])) \
            * (Decimal(1) - Decimal(str(CACHED_INPUT_MULTIPLIER)))
        ai_guardrails.record_cache_event("cache_hit", event["source"], tokens_saved=cached,
                                         model=event["model"], cost_saved_usd=saved.quantize(Decimal("0.000001")))
    except Exception:
        logger.debug("Could not update cache optimization estimate", exc_info=True)


def tracked_gemini_call(source: str, model_name: str, call, *, user_id=None,
                        organization_id=None, product=None, trigger=None, pricing_context=None):
    """Record a durable pending attempt, then provider metadata before parsing.

    SDK-internal retries must be disabled at the client factory: this wrapper sees
    one callback invocation. Local timeouts stay unknown because work may finish
    remotely. The original provider response/exception is returned unchanged.
    """
    base = _event_base(source, model_name, user_id=user_id, organization_id=organization_id,
                       product=product, trigger=trigger, pricing_context=pricing_context)
    if not _write_event(base):
        raise RuntimeError("AI usage accounting is unavailable; request was not sent")
    try:
        response = call()
    except Exception as exc:
        failure = dict(base)
        code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
        if callable(code):
            try:
                code = code()
            except Exception:
                code = None
        # Google's billing FAQ states HTTP 400/500 token requests are uncharged;
        # cancellation/timeouts and other failures are not inferred to be free.
        definitive = isinstance(code, int) and code in (400, 500)
        failure.update(status="error", usage_state="not_billed" if definitive else "unknown",
                       pricing_status="not_billed" if definitive else "unknown")
        _write_event(failure)
        raise
    try:
        completed = _complete_event(base, response)
    except Exception:
        logger.error("Provider usage metadata could not be normalized (event=%s)", base["event_key"], exc_info=True)
        completed = {**base, "status": "ok", "usage_state": "unknown", "pricing_status": "unknown"}
    _write_event(completed)
    _record_cache_saving(completed)
    _tag_response(response, base["event_key"])
    return response


def record_gemini_usage(source: str, model_name: str, response, *, user_id=None,
                        organization_id=None, status="ok", product=None, trigger=None,
                        event_key=None, provider=None, project_id=None) -> None:
    """Backwards-compatible response recorder; wrapped responses cannot double count.

    Use tracked_gemini_call for new code so an attempt is recorded before dispatch.
    Missing usage is retained as unknown, never dropped or claimed to be free.
    """
    try:
        tagged = _response_event_key(response)
        if tagged:
            if status != "ok":
                _write_event({"event_key": tagged, "status": str(status)[:16]})
            return
        base = _event_base(source, model_name, user_id=user_id, organization_id=organization_id,
                           product=product, trigger=trigger, event_key=event_key,
                           provider=provider, project_id=project_id)
        response_id = _attr(response, "response_id")
        if response_id and not event_key:
            identity = json.dumps([base["provider"], base["project_id"], str(response_id)])
            base["event_key"] = "response-" + hashlib.sha256(identity.encode()).hexdigest()
        completed = _complete_event(base, response, status)
        _write_event(completed)
        _record_cache_saving(completed)
        _tag_response(response, base["event_key"])
    except Exception:
        logger.error("Failed to record Gemini usage (source=%s); reconciliation required", source, exc_info=True)


def record_tts_usage(source: str, voice_name: str, characters: int | None, *,
                     cost_usd: float | None, user_id=None, organization_id=None,
                     product=None, trigger=None, status="ok", usage_state=None,
                     event_key=None) -> bool:
    """Record Cloud TTS characters separately from Gemini token counters."""
    try:
        base = _event_base(source, "gcp-tts/" + str(voice_name or "unknown")[:60],
                           user_id=user_id, organization_id=organization_id, product=product,
                           trigger=trigger, event_key=event_key, provider="google_cloud_tts",
                           project_id=(os.getenv("GOOGLE_TTS_BILLING_PROJECT_ID") or
                                       ((os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT"))
                                        if os.getenv("GEMINI_PROVIDER", "developer").lower() == "vertex" else None)))
        chars = max(0, int(characters or 0))
        state = usage_state or ("measured" if characters is not None else "unknown")
        base.update(unit_type="characters", character_count=chars, prompt_tokens=0,
                    output_tokens=0, total_tokens=0, cached_tokens=0, candidate_tokens=0,
                    thought_tokens=0, tool_tokens=0, usage_state=state, status=status,
                    pricing_status=("estimated" if cost_usd is not None and state == "measured" else state),
                    pricing_version="cloud-tts-caller-estimate-v2",
                    estimated_cost_usd=str(Decimal(str(cost_usd or 0)).quantize(Decimal("0.000001"))))
        return _write_event(base)
    except Exception:
        logger.error("Failed to record TTS usage (source=%s); reconciliation required", source, exc_info=True)
        return False


def record_cache_storage_usage(source: str, model_name: str, *, cache_name=None,
                               total_token_count=None, ttl_seconds=None, event_key=None,
                               status="pending", usage_state="pending", user_id=None,
                               organization_id=None, product=None, trigger=None) -> bool:
    """Track cache operations without mixing cached contents into generated tokens.

    Tokens multiplied by requested TTL are not actual billed token-hours: deletion,
    TTL changes and provider behavior can alter the duration. Billing export remains
    the authority, so successful creation still has unknown storage consumption.
    """
    try:
        base = _event_base(source, model_name, user_id=user_id, organization_id=organization_id,
                           product=product, trigger=trigger, event_key=event_key)
        metadata = {"cache_reference_hash": hashlib.sha256(str(cache_name).encode()).hexdigest() if cache_name else None,
                    "cached_content_token_count": total_token_count, "requested_ttl_seconds": ttl_seconds}
        base.update(unit_type="cache_token_hours", status=status,
                    prompt_tokens=0, output_tokens=0, total_tokens=0, cached_tokens=0,
                    candidate_tokens=0, thought_tokens=0, tool_tokens=0,
                    usage_state="pending" if usage_state == "pending" else "unknown",
                    pricing_status="pending" if usage_state == "pending" else "unpriced",
                    raw_usage_json=json.dumps(metadata, default=str, separators=(",", ":")),
                    estimated_cost_usd="0")
        return _write_event(base)
    except Exception:
        logger.error("Failed to record Gemini cache storage event (source=%s)", source, exc_info=True)
        return False


# ---------------------------------------------------------------------------
# Analytics for the admin console
# ---------------------------------------------------------------------------

SOURCE_LABELS = {
    "mock_interview_tts": "Mock interview — officer neural voice (TTS)",
    "document_ai": "Document AI (validation & extraction)",
    "enterprise_document_scan": "Document scan & validate (per document, billed)",
    "student_ai_chat": "Student AI chat (website)",
    "student_mock_interview": "Mock interview conversation",
    "student_interview_report": "Mock interview feedback report",
    "student_visa_prep": "Visa preparation",
    "sop_generator": "Statement of purpose generation",
    "mock_interview_report": "Mock interview report",
    "sop_kit": "Statement of purpose generation",
    "sop_generation": "Statement of purpose generation",
    "visa_prep": "Visa preparation",
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


def _token_column(E, column):
    """Historical TTS rows held characters in token fields; exclude until migrated."""
    return case((E.model.like("gcp-tts/%"), 0), (E.unit_type == "characters", 0), else_=column)


def _character_column(E):
    """Read migrated characters, with a fallback for untouched legacy TTS rows."""
    legacy_chars = case((E.prompt_tokens > E.total_tokens, E.prompt_tokens), else_=E.total_tokens)
    return case((E.unit_type == "characters", E.character_count),
                ((E.model.like("gcp-tts/%")) & (E.metering_version < 2), legacy_chars), else_=0)


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
            func.coalesce(func.sum(_token_column(E, E.total_tokens)), 0),
            func.count(E.id),
            func.coalesce(func.sum(_token_column(E, E.cached_tokens)), 0),
            func.coalesce(func.sum(_token_column(E, E.prompt_tokens)), 0),
            func.coalesce(func.sum(E.search_cost_usd), 0),
            func.coalesce(func.sum(E.search_queries), 0),
            func.coalesce(func.sum(case((E.model.like("gcp-tts/%"), E.estimated_cost_usd),
                                        (E.unit_type != "tokens", E.estimated_cost_usd), else_=0)), 0),
            func.coalesce(func.sum(_character_column(E)), 0),
        )
        if start is not None:
            q = q.filter(E.created_at >= start)
        if end is not None:
            q = q.filter(E.created_at < end)
        cost, tokens, calls, cached, prompt, search_cost, searches, other_cost, characters = q.one()
        cached = int(cached or 0); prompt = int(prompt or 0)
        # Money saved by caching ≈ cached tokens × input rate × the cache discount.
        saved = round(float(cached) / 1_000_000 * float(_DEFAULT_INPUT) * (1 - CACHED_INPUT_MULTIPLIER), 6)
        total = _money(cost)
        search_usd = _money(search_cost)
        return {
            "cost_usd": total, "tokens": int(tokens or 0), "calls": int(calls or 0),
            "cached_tokens": cached, "tts_characters": int(characters or 0),
            "cache_hit_pct": round(cached / prompt * 100, 1) if prompt else 0.0,
            "cache_saved_usd": saved,
            # cost_usd is the TOTAL; split it so grounding is visible next to tokens.
            # Search fees have their own free tier and scale with searches-per-prompt,
            # not with traffic, so they move independently of the token line.
            "token_cost_usd": _money(float(total) - float(search_usd) - float(other_cost)),
            "other_cost_usd": _money(other_cost),
            "search_cost_usd": search_usd,
            "search_queries": int(searches or 0),
        }

    def in_range(q):
        return q.filter(E.created_at >= range_start, E.created_at < range_end)

    by_source = []
    for src, cost, tokens, calls, search_cost, searches, characters in in_range(
        db.query(E.source, func.coalesce(func.sum(E.estimated_cost_usd), 0),
                 func.coalesce(func.sum(_token_column(E, E.total_tokens)), 0), func.count(E.id),
                 func.coalesce(func.sum(E.search_cost_usd), 0),
                 func.coalesce(func.sum(E.search_queries), 0),
                 func.coalesce(func.sum(_character_column(E)), 0))
    ).group_by(E.source).all():
        by_source.append({
            "source": src, "label": SOURCE_LABELS.get(src, src),
            "cost_usd": _money(cost), "tokens": int(tokens or 0), "calls": int(calls or 0),
            "search_cost_usd": _money(search_cost), "search_queries": int(searches or 0),
            "tts_characters": int(characters or 0),
        })
    by_source.sort(key=lambda r: r["cost_usd"], reverse=True)

    by_model = []
    for mdl, cost, tokens, calls, characters in in_range(
        db.query(E.model, func.coalesce(func.sum(E.estimated_cost_usd), 0),
                 func.coalesce(func.sum(_token_column(E, E.total_tokens)), 0), func.count(E.id),
                 func.coalesce(func.sum(_character_column(E)), 0))
    ).group_by(E.model).all():
        by_model.append({
            "model": mdl, "cost_usd": _money(cost), "tokens": int(tokens or 0), "calls": int(calls or 0),
            "tts_characters": int(characters or 0),
        })
    by_model.sort(key=lambda r: r["cost_usd"], reverse=True)

    # Per-day series over the selected range, bucketed in Python for dialect portability.
    buckets = {}
    for created_at, cost, tokens in in_range(
        db.query(E.created_at, E.estimated_cost_usd, _token_column(E, E.total_tokens))
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
            "List-price estimates only; missing usage and unknown prices are reported separately. "
            "Grounding estimates do not deduct a shared free allowance. Google billing export is "
            "the authority for billed amounts, credits and non-token charges."
        ),
    }
