"""Behavioral accounting checks against the verified Google rate snapshot."""

import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.ai_cost_calculation import calculate_event, RATE_VERSION, VERIFIED_AT


def event(model="gemini-2.5-pro", prompt=1000, candidate=100, thinking=200, cached=0, **kwargs):
    total = prompt + candidate + thinking
    row = dict(model=model, prompt_tokens=prompt, candidate_tokens=candidate,
               thought_tokens=thinking, output_tokens=candidate + thinking,
               cached_tokens=cached, total_tokens=total, unit_type="tokens",
               metering_version=2, usage_state="measured", provider="developer",
               search_queries=0, tool_tokens=0, created_at="2026-09-07T12:00:00+00:00",
               raw_usage_json=json.dumps({"promptTokenCount": prompt,
                   "candidatesTokenCount": candidate, "thoughtsTokenCount": thinking,
                   "cachedContentTokenCount": cached, "totalTokenCount": total,
                   "promptTokensDetails": [{"modality": "TEXT", "tokenCount": prompt}],
                   "cacheTokensDetails": [{"modality": "TEXT", "tokenCount": cached}],
                   "_rilono_pricing": {"service_tier": "standard", "location": "global"}}))
    row.update(kwargs)
    return row


def test_provider_counts_price_cache_once_and_thinking_once():
    result = calculate_event(event(prompt=1000, candidate=100, thinking=200, cached=400))
    assert Decimal(result["calculated_cost_usd"]) == Decimal("0.0038")
    assert result["breakdown"]["fresh_input_cost_usd"] == "0.00075"
    assert result["breakdown"]["cached_input_cost_usd"] == "0.00005"
    assert result["breakdown"]["output_cost_usd"] == "0.003"
    assert result["calculation_status"] == "calculated"


@pytest.mark.parametrize("model,expected", [("gemini-2.5-pro", "0.25001"), ("gemini-3.1-pro-preview", "0.400012")])
def test_exact_200k_prompt_keeps_lower_tier(model, expected):
    result = calculate_event(event(model=model, prompt=200_000, candidate=1, thinking=0))
    assert Decimal(result["calculated_cost_usd"]) == Decimal(expected)
    assert result["context_tier"] == "up_to_200k"


@pytest.mark.parametrize("model,expected", [("gemini-2.5-pro", "0.5000175"), ("gemini-3.1-pro-preview", "0.800022")])
def test_long_context_prices_entire_request_at_higher_tier(model, expected):
    result = calculate_event(event(model=model, prompt=200_001, candidate=1, thinking=0))
    assert Decimal(result["calculated_cost_usd"]) == Decimal(expected)
    assert result["context_tier"] == "over_200k"


def test_context_tier_counts_cache_in_prompt():
    result = calculate_event(event(prompt=200_001, candidate=0, thinking=0, cached=200_000))
    assert Decimal(result["calculated_cost_usd"]) == Decimal("0.0500025")


def test_small_requests_keep_submicrodollar_precision():
    result = calculate_event(event(model="gemini-2.5-flash", prompt=1, candidate=0, thinking=0, cached=1))
    assert result["calculated_cost_usd"] == "0.00000003"
    assert sum([Decimal(result["calculated_cost_usd"])] * 1000) == Decimal("0.00003")


def test_legacy_output_is_combined_and_historical_price_not_claimed():
    row = event(metering_version=1, usage_state="legacy", raw_usage_json=None,
                provider=None, candidate_tokens=0, thought_tokens=0)
    result = calculate_event(SimpleNamespace(**row))
    assert Decimal(result["calculated_cost_usd"]) == Decimal("0.00425")
    assert result["historical_price_verified"] is False
    assert result["rate_basis"] == "current_standard_list_rates"
    assert result["calculation_status"] == "partial"
    assert result["verified_at"] == VERIFIED_AT
    assert result["rate_version"] == RATE_VERSION
    assert result["provider_scope"] == "shared_developer_vertex_standard_rates"
    assert len(result["source_urls"]) == 2


@pytest.mark.parametrize("model", ["unlisted-gemini-2.5-pro", "gemini-2.5-pro-preview", "gemini-3.1-pro-preview-customtools", "gemini-2.5-flash-tts", "gemini-newest"])
def test_unknown_models_never_substring_match(model):
    result = calculate_event(event(model=model))
    assert result["calculated_cost_usd"] == "0"
    assert result["unavailable_reason"] == "model_rate_not_verified"


def test_exact_google_resource_wrapper_is_supported():
    assert calculate_event(event(model="models/gemini-2.5-pro"))["calculation_status"] == "calculated"
    assert calculate_event(event(model="projects/p/locations/global/publishers/google/models/gemini-2.5-pro"))["calculation_status"] == "calculated"


@pytest.mark.parametrize("state", ["unknown", "pending", "error"])
def test_missing_usage_is_unavailable_zero(state):
    result = calculate_event(event(usage_state=state))
    assert result["calculated_cost_usd"] == "0"
    assert result["available"] is False
    assert result["unavailable_reason"] == "usage_not_measured"


@pytest.mark.parametrize("state", ["duplicate", "not_billed"])
def test_duplicate_or_definitively_not_billed_never_add_cost(state):
    result = calculate_event(event(usage_state=state))
    assert result["calculated_cost_usd"] == "0"
    assert result["calculation_status"] == "not_billable"
    assert result["available"] is True


@pytest.mark.parametrize("changes", [{"cached_tokens": 1001}, {"prompt_tokens": -1},
    {"prompt_tokens": True}, {"prompt_tokens": 1.5}, {"total_tokens": None},
    {"candidate_tokens": None}, {"raw_usage_json": None}, {"raw_usage_json": "{}"}])
def test_inconsistent_or_missing_counters_never_use_old_stored_cost(changes):
    result = calculate_event(event(estimated_cost_usd="123.45", **changes))
    assert result["calculated_cost_usd"] == "0"
    assert result["available"] is False


def test_mixed_audio_flash_uses_provider_modality_counters():
    row = event(model="gemini-2.5-flash", prompt=1000, candidate=100, thinking=0, cached=100)
    raw = json.loads(row["raw_usage_json"])
    raw["promptTokensDetails"] = [{"modality": "TEXT", "tokenCount": 600}, {"modality": "AUDIO", "tokenCount": 400}]
    raw["cacheTokensDetails"] = [{"modality": "TEXT", "tokenCount": 80}, {"modality": "AUDIO", "tokenCount": 20}]
    row["raw_usage_json"] = json.dumps(raw)
    result = calculate_event(row)
    assert Decimal(result["calculated_cost_usd"]) == Decimal("0.0007904")
    assert result["breakdown"]["audio_input_tokens"] == 400
    assert result["breakdown"]["audio_cached_tokens"] == 20


def test_flash_unknown_input_modality_is_not_silently_text_priced():
    row = event(model="gemini-2.5-flash", metering_version=1, usage_state="legacy", raw_usage_json=None)
    result = calculate_event(row)
    assert Decimal(result["calculated_cost_usd"]) == Decimal("0.00075")
    assert result["breakdown"]["fresh_input_cost_usd"] == "0"
    assert result["breakdown"]["cached_input_cost_usd"] == "0"
    assert result["breakdown"]["input_rate_per_million_usd"] is None
    assert "input_modality_not_recorded" in result["excluded_components"]
    assert result["calculation_status"] == "partial"


def test_dispatch_context_can_prove_non_audio_modalities_without_counters():
    row = event(model="gemini-2.5-flash", metering_version=1, usage_state="legacy", raw_usage_json=None,
                pricing_context={"input_modalities": ["TEXT", "IMAGE"], "service_tier": "standard"})
    result = calculate_event(row)
    assert Decimal(result["calculated_cost_usd"]) == Decimal("0.00105")


def test_flash_mixed_audio_context_alone_cannot_guess_ratio():
    result = calculate_event(event(model="gemini-2.5-flash", metering_version=1, usage_state="legacy", raw_usage_json=None,
        pricing_context={"input_modalities": ["TEXT", "AUDIO"]}))
    assert result["calculation_status"] == "partial"
    assert "input_modality_not_recorded" in result["excluded_components"]


def test_cached_modality_cannot_exceed_matching_prompt_modality():
    row = event(model="gemini-2.5-flash", cached=100)
    raw = json.loads(row["raw_usage_json"])
    raw["cacheTokensDetails"] = [{"modality": "AUDIO", "tokenCount": 100}]
    row["raw_usage_json"] = json.dumps(raw)
    assert calculate_event(row)["unavailable_reason"] == "cached_modality_counters_inconsistent"


def test_extra_grounding_cost_not_invented_or_reused_from_old_estimates():
    row = event(search_queries=3, search_cost_usd="100.00", estimated_cost_usd="200.00")
    result = calculate_event(row)
    assert Decimal(result["calculated_cost_usd"]) == Decimal("0.00425")
    assert result["calculation_status"] == "partial"
    assert result["excluded_components"] == ["grounding_fees_and_free_allowance"]
    assert result["breakdown"]["other_cost_usd"] == "0"


@pytest.mark.parametrize("unit", ["characters", "cache_token_hours"])
def test_non_token_units_do_not_masquerade_as_token_cost(unit):
    result = calculate_event(event(unit_type=unit, character_count=1000))
    assert result["unavailable_reason"] == "non_token_price_not_verified"


def test_unsupported_service_tier_not_charged_at_standard_rate():
    result = calculate_event(event(pricing_context={"service_tier": "priority"}))
    assert result["unavailable_reason"] == "service_tier_rate_not_verified"


def test_non_google_provider_not_charged_using_google_rates():
    assert calculate_event(event(provider="other"))["unavailable_reason"] == "provider_rate_not_verified"


def test_legacy_zero_defaults_remain_unavailable_but_provider_zero_is_valid():
    assert calculate_event(event(prompt=0, candidate=0, thinking=0))["calculation_status"] == "calculated"
    result = calculate_event(event(prompt=0, candidate=0, thinking=0, metering_version=1, usage_state="legacy", raw_usage_json=None))
    assert result["unavailable_reason"] == "legacy_zero_usage_unverified"


def test_discarded_successful_response_still_incurs_token_cost():
    result = calculate_event(event(status="empty"))
    assert Decimal(result["calculated_cost_usd"]) == Decimal("0.00425")


def test_call_does_not_mutate_ledger_or_metadata():
    row = event()
    before = dict(row)
    calculate_event(row)
    assert row == before


@pytest.mark.parametrize("created,reason", [
    ("2026-06-20T00:00:00+00:00", "historical_request_date_price_not_verified"),
    (None, "request_date_not_retained"),
])
def test_historical_or_missing_dates_are_partial_current_rate_calculations(created, reason):
    result = calculate_event(event(created_at=created))
    assert result["calculation_status"] == "partial"
    assert reason in result["coverage_reasons"]
    assert Decimal(result["calculated_cost_usd"]) == Decimal("0.00425")


def test_missing_dispatch_tier_cannot_be_presented_as_verified_standard_traffic():
    row = event()
    raw = json.loads(row["raw_usage_json"])
    raw.pop("_rilono_pricing")
    row["raw_usage_json"] = json.dumps(raw)
    result = calculate_event(row)
    assert result["calculation_status"] == "partial"
    assert "service_tier_not_retained_standard_rates_used" in result["coverage_reasons"]


def test_missing_vertex_region_keeps_global_rate_value_explicitly_partial():
    row = event(model="gemini-3.1-pro-preview", provider="vertex",
                pricing_context={"service_tier": "standard"})
    result = calculate_event(row)
    assert result["calculation_status"] == "partial"
    assert result["calculated_cost_usd"] == "0.0056"
    assert "region_not_retained_standard_global_rates_used" in result["coverage_reasons"]


def test_invalid_provider_modality_counters_not_hidden_by_dispatch_context():
    row = event(model="gemini-2.5-flash", pricing_context={"input_modalities": ["TEXT"]})
    raw = json.loads(row["raw_usage_json"])
    raw["promptTokensDetails"] = [{"modality": "TEXT", "tokenCount": 900}]
    row["raw_usage_json"] = json.dumps(raw)
    assert calculate_event(row)["unavailable_reason"] == "modality_counters_inconsistent"


def test_single_provider_modality_proves_cached_subset_modality():
    row = event(model="gemini-2.5-flash", cached=100)
    raw = json.loads(row["raw_usage_json"])
    raw.pop("cacheTokensDetails")
    row["raw_usage_json"] = json.dumps(raw)
    result = calculate_event(row)
    assert result["calculation_status"] == "calculated"
    assert Decimal(result["calculated_cost_usd"]) == Decimal("0.001023")


@pytest.mark.parametrize("provider,expected", [("developer", "0.200001"), ("vertex", "0.0600003")])
def test_flash_long_audio_uses_verified_provider_specific_rate(provider, expected):
    row = event(model="gemini-2.5-flash", provider=provider, prompt=200001, candidate=0, thinking=0)
    raw = json.loads(row["raw_usage_json"])
    raw["promptTokensDetails"] = [{"modality": "AUDIO", "tokenCount": 200001}]
    row["raw_usage_json"] = json.dumps(raw)
    assert Decimal(calculate_event(row)["calculated_cost_usd"]) == Decimal(expected)


def test_unknown_provider_cannot_choose_between_different_audio_rates():
    row = event(model="gemini-2.5-flash", provider=None, prompt=200001, candidate=0, thinking=0)
    raw = json.loads(row["raw_usage_json"])
    raw["promptTokensDetails"] = [{"modality": "AUDIO", "tokenCount": 200001}]
    row["raw_usage_json"] = json.dumps(raw)
    result = calculate_event(row)
    assert result["calculated_cost_usd"] == "0"
    assert result["unavailable_reason"] == "provider_required_for_audio_long_context_rate"


def test_flash_missing_modality_and_no_output_has_no_available_component():
    row = event(model="gemini-2.5-flash", candidate=0, thinking=0, metering_version=1,
                usage_state="legacy", raw_usage_json=None)
    result = calculate_event(row)
    assert result["calculated_cost_usd"] == "0"
    assert result["available"] is False
    assert result["unavailable_reason"] == "input_modality_not_recorded"


def test_explicit_cache_storage_excluded_from_per_request_token_cost():
    result = calculate_event(event(cached=400, pricing_context={"service_tier": "standard", "explicit_cache": True}))
    assert Decimal(result["calculated_cost_usd"]) == Decimal("0.0038")
    assert result["calculation_status"] == "partial"
    assert result["excluded_components"] == ["explicit_cache_storage"]


def test_provisioned_throughput_not_presented_as_pay_as_you_go_charge():
    row = event()
    raw = json.loads(row["raw_usage_json"])
    raw["trafficType"] = "PROVISIONED_THROUGHPUT"
    row["raw_usage_json"] = json.dumps(raw)
    result = calculate_event(row)
    assert Decimal(result["calculated_cost_usd"]) == Decimal("0.00425")
    assert result["calculation_status"] == "partial"
    assert "provisioned_throughput_standard_list_value_only" in result["coverage_reasons"]
