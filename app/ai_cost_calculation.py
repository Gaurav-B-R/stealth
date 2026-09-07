"""Calculate a published-rate value for recorded Gemini token usage.

This is deliberately independent of the ledger's old ``estimated_cost_usd``.
It never turns an invoice total into a per-person allocation. The catalog is an
auditable snapshot of Google's USD list prices, not a claim about discounts or
the historical price charged on an event's date. Keep old catalog versions when
adding a new one; verification time is not a price's effective-from date.

Unknown models, missing usage, and ambiguous modalities have no fallback price.
All arithmetic remains Decimal until the JSON-safe result is returned.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, localcontext

RATE_VERSION = "google-standard-list-2026-09-07-v1"
VERIFIED_AT = "2026-09-07"
DEVELOPER_SOURCE = "https://ai.google.dev/gemini-api/docs/pricing"
VERTEX_SOURCE = "https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing"
SOURCE_URLS = (DEVELOPER_SOURCE, VERTEX_SOURCE)
RATE_BASIS = "current_standard_list_rates"
RATE_BASIS_DESCRIPTION = (
    "Recorded tokens valued at Google's published standard USD rates verified "
    "on 2026-09-07. Historical request-date prices, free allowances, discounts, "
    "credits, tax, and currency conversion are not inferred."
)

# Exact model identifiers only. Values are USD per million tokens, for the
# complete prompt <=200,000 / >200,000. Cached tokens remain part of that prompt.
# Both official pages list identical standard Pro rates for every input modality.
RATE_CATALOG = {
    "gemini-2.5-pro": {
        "input": ("1.25", "2.50"), "output": ("10.00", "15.00"),
        "cache": ("0.125", "0.25"), "audio": None,
    },
    "gemini-3.1-pro-preview": {
        "input": ("2.00", "4.00"), "output": ("12.00", "18.00"),
        "cache": ("0.20", "0.40"), "audio": None,
    },
    "gemini-2.5-flash": {
        "input": ("0.30", "0.30"), "output": ("2.50", "2.50"),
        "cache": ("0.03", "0.03"), "audio": ("1.00", "1.00"),
        "audio_cache": ("0.10", "0.10"),
    },
}

_MILLION = Decimal(1_000_000)
_NON_AUDIO = frozenset({"TEXT", "IMAGE", "VIDEO"})


def _get(value, name, default=None):
    if isinstance(value, Mapping):
        if name in value:
            return value[name]
        parts = name.split("_")
        return value.get(parts[0] + "".join(part.title() for part in parts[1:]), default)
    return getattr(value, name, default)


def _integer(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
        if number.is_finite() and number >= 0 and number == number.to_integral_value():
            return int(number)
    except (InvalidOperation, ValueError, TypeError, OverflowError):
        pass
    return None


def _amount(value):
    return "0" if value == 0 else format(value, "f")


def _model_id(value):
    name = str(value or "").strip()
    # These documented resource wrappers name the same exact model. No substring
    # matching, invented version aliases, or fallback to a different model family.
    match = re.fullmatch(r"(?:models/|publishers/google/models/|projects/[^/]+/locations/[^/]+/publishers/google/models/)?([^/]+)", name)
    return match.group(1) if match else name


def _metadata(event):
    raw = _get(event, "raw_usage_json")
    if isinstance(raw, Mapping):
        return dict(raw)
    if raw:
        try:
            value = json.loads(raw)
            if isinstance(value, dict):
                return value
        except (ValueError, TypeError):
            pass
    return {}


def _result():
    return {
        "calculated_cost_usd": "0", "calculation_status": "unavailable",
        "available": False, "unavailable_reason": None, "excluded_components": [], "coverage_reasons": [],
        "rate_version": RATE_VERSION, "source_urls": list(SOURCE_URLS),
        "verified_at": VERIFIED_AT, "rate_basis": RATE_BASIS,
        "rate_basis_description": RATE_BASIS_DESCRIPTION,
        "historical_price_verified": False, "provider_scope": None,
        "service_tier": "standard", "context_tier": None,
        "assumptions": [],
        "breakdown": {
            "fresh_input_cost_usd": "0", "cached_input_cost_usd": "0",
            "output_cost_usd": "0", "token_cost_usd": "0",
            "voice_cost_usd": "0", "other_cost_usd": "0",
            "input_tokens": 0, "cached_tokens": 0, "output_tokens": 0,
            "input_rate_per_million_usd": None,
            "cached_rate_per_million_usd": None,
            "output_rate_per_million_usd": None,
        },
    }


def _unavailable(result, reason):
    result["unavailable_reason"] = reason
    return result


def _modality_counts(raw, field, expected):
    """None means absent/incomplete evidence, never an assumed text request."""
    if expected == 0:
        return {"audio": 0, "other": 0}
    details = _get(raw, field)
    if not isinstance(details, (list, tuple)) or not details:
        return None
    result = {"audio": 0, "other": 0}
    for detail in details:
        modality = str(_get(detail, "modality", "")).upper().split(".")[-1]
        number = _integer(_get(detail, "token_count"))
        if number is None or modality not in _NON_AUDIO | {"AUDIO"}:
            return None
        result["audio" if modality == "AUDIO" else "other"] += number
    return result if sum(result.values()) == expected else None


def _context_modality_counts(context, expected):
    modalities = context.get("input_modalities")
    if not isinstance(modalities, (list, tuple)) or not modalities:
        return None
    names = {str(item).upper().split(".")[-1] for item in modalities}
    if names <= _NON_AUDIO:
        return {"audio": 0, "other": expected}
    if names == {"AUDIO"}:
        return {"audio": expected, "other": 0}
    return None  # Mixed audio requests need actual counters for each modality.


def calculate_event(event) -> dict:
    """Return a zero or exact Decimal-string calculation for one retained event.

    Accept an ORM row or a mapping. ``partial`` means token value is available,
    but separately metered tools/grounding/storage are excluded. No state or
    database is modified. ``not_billable`` and ``duplicate`` attempts add zero.
    """
    result = _result()
    state = _get(event, "usage_state")
    if state in {"duplicate", "not_billed"}:
        result.update(available=True, calculation_status="not_billable", rate_basis="not_billable")
        return result
    version = _integer(_get(event, "metering_version", 1)) or 1
    if state not in {"measured", "legacy"} and not (version < 2 and state is None):
        return _unavailable(result, "usage_not_measured")
    if _get(event, "unit_type", "tokens") not in {None, "tokens"}:
        return _unavailable(result, "non_token_price_not_verified")

    model = _model_id(_get(event, "model"))
    rate = RATE_CATALOG.get(model)
    if rate is None:
        return _unavailable(result, "model_rate_not_verified")
    provider = _get(event, "provider")
    if provider not in {None, "", "developer", "vertex"}:
        return _unavailable(result, "provider_rate_not_verified")
    result["provider_scope"] = provider or "shared_developer_vertex_standard_rates"
    if not provider:
        result["coverage_reasons"].append("historical_provider_not_retained_shared_standard_rates_used")
    result["source_urls"] = [VERTEX_SOURCE] if provider == "vertex" else [DEVELOPER_SOURCE] if provider == "developer" else list(SOURCE_URLS)

    created = _get(event, "created_at")
    try:
        if isinstance(created, str):
            created = datetime.fromisoformat(created.replace("Z", "+00:00"))
        event_date = created.date() if isinstance(created, datetime) else created
        if not isinstance(event_date, date):
            raise ValueError("Event date unavailable")
        if event_date < date.fromisoformat(VERIFIED_AT):
            result["coverage_reasons"].append("historical_request_date_price_not_verified")
    except (ValueError, TypeError):
        result["coverage_reasons"].append("request_date_not_retained")

    raw = _metadata(event)
    context = _get(event, "pricing_context") or raw.get("_rilono_pricing") or {}
    if not isinstance(context, Mapping):
        context = {}
    if context.get("explicit_cache"):
        result["excluded_components"].append("explicit_cache_storage")
    traffic_type = str(_get(raw, "traffic_type", "")).upper().split(".")[-1]
    if traffic_type == "PROVISIONED_THROUGHPUT":
        result["coverage_reasons"].append("provisioned_throughput_standard_list_value_only")
    tier = str(context.get("service_tier") or "standard").lower()
    if tier != "standard":
        return _unavailable(result, "service_tier_rate_not_verified")
    if not context.get("service_tier"):
        result["assumptions"].append("valued_at_standard_list_rates_service_tier_not_retained")
        result["coverage_reasons"].append("service_tier_not_retained_standard_rates_used")
    if model == "gemini-3.1-pro-preview" and provider == "vertex" and context.get("location") not in {None, "", "global"}:
        return _unavailable(result, "region_rate_not_verified")
    if model == "gemini-3.1-pro-preview" and provider == "vertex" and not context.get("location"):
        result["coverage_reasons"].append("region_not_retained_standard_global_rates_used")

    prompt = _integer(_get(event, "prompt_tokens"))
    cached = _integer(_get(event, "cached_tokens"))
    total = _integer(_get(event, "total_tokens"))
    if version < 2:
        # The pre-v2 ledger already combined candidate and thinking tokens.
        output = _integer(_get(event, "output_tokens"))
        result["assumptions"].append("historical_counters_retained_without_raw_provider_metadata")
    else:
        if not raw:
            return _unavailable(result, "provider_usage_metadata_missing")
        raw_prompt = _integer(_get(raw, "prompt_token_count"))
        raw_total = _integer(_get(raw, "total_token_count"))
        candidate = _integer(_get(raw, "candidates_token_count", 0))
        thinking = _integer(_get(raw, "thoughts_token_count", 0))
        raw_cached = _integer(_get(raw, "cached_content_token_count", 0))
        if raw_prompt != prompt or raw_total != total or raw_cached != cached:
            return _unavailable(result, "provider_counters_do_not_match_ledger")
        if candidate is None or thinking is None:
            return _unavailable(result, "invalid_output_counters")
        output = candidate + thinking
        ledger_candidate = _integer(_get(event, "candidate_tokens"))
        ledger_thinking = _integer(_get(event, "thought_tokens"))
        if ledger_candidate is None or ledger_thinking is None or output != ledger_candidate + ledger_thinking:
            return _unavailable(result, "provider_counters_do_not_match_ledger")
    if any(value is None for value in (prompt, cached, total, output)):
        return _unavailable(result, "token_counters_missing_or_invalid")
    if cached > prompt or total < prompt + output:
        return _unavailable(result, "token_counters_inconsistent")
    if total == 0 and prompt + output == 0 and version < 2:
        # The old table's defaults cannot distinguish an absent response from an
        # explicitly reported zero. New records carry the raw provider metadata.
        return _unavailable(result, "legacy_zero_usage_unverified")

    large = int(prompt > 200_000)
    result["context_tier"] = "over_200k" if large else "up_to_200k"
    input_rate, output_rate, cached_rate = (Decimal(rate[key][large]) for key in ("input", "output", "cache"))
    prompt_parts, cache_parts = {"audio": 0, "other": prompt}, {"audio": 0, "other": cached}
    audio_rate = audio_cache_rate = Decimal(0)
    if rate["audio"] is not None:
        prompt_parts = _modality_counts(raw, "prompt_tokens_details", prompt)
        cache_parts = _modality_counts(raw, "cache_tokens_details", cached)
        if (_get(raw, "prompt_tokens_details") and prompt_parts is None) or (_get(raw, "cache_tokens_details") and cache_parts is None):
            return _unavailable(result, "modality_counters_inconsistent")
        prompt_parts = prompt_parts or _context_modality_counts(context, prompt)
        cache_parts = cache_parts or _context_modality_counts(context, cached)
        if cache_parts is None and prompt_parts is not None:
            if prompt_parts["audio"] == 0:
                cache_parts = {"audio": 0, "other": cached}
            elif prompt_parts["other"] == 0:
                cache_parts = {"audio": cached, "other": 0}
        if prompt_parts is None or cache_parts is None:
            # The model has a single text-output rate including thinking. Keep
            # that known component rather than inventing an audio/text input mix.
            result["excluded_components"].append("input_modality_not_recorded")
            prompt_parts = cache_parts = {"audio": 0, "other": 0}
            if not output:
                return _unavailable(result, "input_modality_not_recorded")
        if any(cache_parts[key] > prompt_parts[key] for key in ("audio", "other")):
            return _unavailable(result, "cached_modality_counters_inconsistent")
        audio_rate = Decimal(rate["audio"][large])
        audio_cache_rate = Decimal(rate["audio_cache"][large])
        # Google's current Vertex table lists a different long-prompt audio rate.
        # Do not choose between provider prices when historical provider is absent.
        if large and prompt_parts["audio"]:
            if not provider:
                return _unavailable(result, "provider_required_for_audio_long_context_rate")
            if provider == "vertex":
                audio_rate = Decimal("0.30")

    with localcontext() as decimal_context:
        decimal_context.prec = 80
        fresh_cost = ((prompt_parts["other"] - cache_parts["other"]) * input_rate
                      + (prompt_parts["audio"] - cache_parts["audio"]) * audio_rate) / _MILLION
        cached_cost = (cache_parts["other"] * cached_rate + cache_parts["audio"] * audio_cache_rate) / _MILLION
        output_cost = output * output_rate / _MILLION
        token_cost = fresh_cost + cached_cost + output_cost
    parts = result["breakdown"]
    parts.update(fresh_input_cost_usd=_amount(fresh_cost), cached_input_cost_usd=_amount(cached_cost),
                 output_cost_usd=_amount(output_cost), token_cost_usd=_amount(token_cost),
                 input_tokens=prompt, cached_tokens=cached, output_tokens=output,
                 input_rate_per_million_usd=_amount(input_rate), cached_rate_per_million_usd=_amount(cached_rate),
                 output_rate_per_million_usd=_amount(output_rate), audio_input_tokens=prompt_parts["audio"],
                 audio_cached_tokens=cache_parts["audio"], audio_input_rate_per_million_usd=_amount(audio_rate),
                 audio_cached_rate_per_million_usd=_amount(audio_cache_rate))
    if "input_modality_not_recorded" in result["excluded_components"]:
        parts.update(input_rate_per_million_usd=None, cached_rate_per_million_usd=None,
                     audio_input_rate_per_million_usd=None, audio_cached_rate_per_million_usd=None)
    if (_integer(_get(event, "search_queries")) or 0) > 0:
        result["excluded_components"].append("grounding_fees_and_free_allowance")
    tool_tokens = _integer(_get(event, "tool_tokens")) or 0
    if tool_tokens or total > prompt + output:
        result["excluded_components"].append("tool_or_unclassified_tokens")
    result.update(calculated_cost_usd=_amount(token_cost), available=True,
                  calculation_status="partial" if result["excluded_components"] or result["coverage_reasons"] else "calculated")
    return result
