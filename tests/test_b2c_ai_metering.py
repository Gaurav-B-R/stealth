"""Offline request-boundary accounting: fallbacks, profile attribution and units."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from google.genai import types

from app import ai_usage, course_catalog, growth_agent, officer_tts
from app.routers import ai_chat, news
from app.services import daily_ai_notifications
from app.utils import gemini_cache, gemini_service


def response(text="A complete answer.", *, finish="STOP", prompt=11, output=3, thoughts=7):
    return SimpleNamespace(
        text=text,
        candidates=[SimpleNamespace(finish_reason=finish)],
        usage_metadata=SimpleNamespace(
            prompt_token_count=prompt, candidates_token_count=output,
            thoughts_token_count=thoughts, total_token_count=prompt + output + thoughts,
        ),
    )


@pytest.fixture
def ledger(monkeypatch):
    """Exercise the real accounting wrapper; replace only persistence and network."""
    events = {}

    def write(payload):
        events.setdefault(payload["event_key"], {}).update(payload)
        return True

    monkeypatch.setattr(ai_usage, "_write_event", write)
    monkeypatch.setattr(
        officer_tts.requests, "post",
        Mock(side_effect=AssertionError("Outbound HTTP is forbidden in offline metering tests")),
    )
    token = ai_usage.set_usage_account(user_id=42, product="b2c", trigger="user")
    yield events
    ai_usage.reset_usage_account(token)


@pytest.mark.parametrize("source,expected", [
    ("rilono_ai_chat", "student_ai_chat"),
    ("rilono_ai_copilot", "student_ai_chat_copilot"),
    ("mock_interview", "student_mock_interview"),
    ("mock_interview_report", "student_interview_report"),
    ("visa_prep", "student_visa_prep"),
])
def test_chat_counts_discarded_truncated_response_for_each_feature(monkeypatch, ledger, source, expected):
    replies = [response("Cut off", finish="MAX_TOKENS"), response()]
    provider = Mock(side_effect=replies)
    monkeypatch.setattr(gemini_service, "USE_VERTEX_AI", False)
    monkeypatch.setattr(gemini_service, "is_ai_configured", lambda: True)
    monkeypatch.setattr(gemini_service, "get_model_candidates", lambda **kwargs: ["gemini-2.5-pro", "gemini-2.5-flash"])
    monkeypatch.setattr(ai_chat, "_build_ai_chat_model", lambda *args, **kwargs: SimpleNamespace(generate_content=provider))
    monkeypatch.setattr(ai_chat, "build_system_prompt", lambda **kwargs: "Offline system prompt")

    text = ai_chat.generate_ai_response("Practice", "Test", "", "", "", source=source)

    assert text == "A complete answer."
    assert provider.call_count == 2
    assert len(ledger) == 2
    assert sum(item["total_tokens"] for item in ledger.values()) == 42
    assert all(item["source"] == expected and item["user_id"] == 42 for item in ledger.values())
    assert all(item["product"] == "b2c" and item["trigger"] == "user" for item in ledger.values())
    assert all(call.kwargs["request_options"]["retry"] is None for call in provider.call_args_list)


def test_shared_model_records_unknown_attempt_then_fallback_and_cannot_be_wrapped_twice(monkeypatch, ledger):
    first = SimpleNamespace(generate_content=Mock(side_effect=TimeoutError("offline timeout")))
    second = SimpleNamespace(generate_content=Mock(return_value=response()))
    factory = Mock(side_effect=[first, second])
    monkeypatch.setattr(gemini_service, "USE_VERTEX_AI", False)
    monkeypatch.setattr(gemini_service, "GENAI_AVAILABLE", True)
    monkeypatch.setattr(gemini_service, "genai", SimpleNamespace(GenerativeModel=factory))

    result = gemini_service._generate_content_with_fallback(
        ["gemini-2.5-pro", "gemini-2.5-flash"], "Offline prompt", usage_source="document_ai",
    )
    rows = list(ledger.values())
    assert [row["usage_state"] for row in rows] == ["unknown", "measured"]
    assert rows[0]["status"] == "error" and rows[1]["total_tokens"] == 21

    gemini_service._instrument_usage(second, "gemini-2.5-flash", "document_ai")
    second.generate_content("Another call", request_options={"timeout": 4, "retry": "old"})
    assert len(ledger) == 3
    # A compatibility recorder must not create another record for an already tracked response.
    ai_usage.record_gemini_usage("wrong_source", "gemini-2.5-flash", result)
    assert len(ledger) == 3


@pytest.mark.parametrize("valid", [True, False])
def test_personalized_automation_is_counted_even_without_an_email_or_valid_json(monkeypatch, ledger, valid):
    text = json.dumps({"notification_needed": False, "reasoning": "No action needed"}) if valid else "not json"
    model = SimpleNamespace(generate_content=Mock(return_value=response(text)))
    monkeypatch.setattr(gemini_service, "USE_VERTEX_AI", False)
    if valid:
        decision = daily_ai_notifications._analyze_user(model, "Offline prompt", 87, "gemini-2.5-pro")
        assert decision.notification_needed is False
    else:
        with pytest.raises(ValueError):
            daily_ai_notifications._analyze_user(model, "Offline prompt", 87, "gemini-2.5-pro")
    row, = ledger.values()
    assert (row["source"], row["user_id"], row["trigger"]) == ("daily_ai_notifier", 87, "automation")
    assert row["total_tokens"] == 21 and row["usage_state"] == "measured"


def test_single_growth_analysis_belongs_to_student_instead_of_initiating_admin(monkeypatch, ledger):
    db = Mock()
    db.query.return_value.filter.return_value.first.side_effect = [SimpleNamespace(id=87), object()]
    monkeypatch.setattr(growth_agent.visa_pass, "has_active_pass", lambda sub: False)
    monkeypatch.setattr(growth_agent, "_features_for", lambda user, sub: {"user_id": user.id, "intent_score": 40})
    monkeypatch.setattr(growth_agent, "_build_prompt", lambda candidates: "Offline prompt")
    monkeypatch.setattr(growth_agent, "is_ai_configured", lambda: True)
    monkeypatch.setattr(growth_agent, "_model_candidates", lambda: ["gemini-2.5-pro"])
    generate = Mock(return_value=response('[{"user_id":87,"recommended_promotion":"hold"}]'))
    monkeypatch.setattr(growth_agent, "genai", SimpleNamespace(GenerativeModel=lambda name: SimpleNamespace(generate_content=generate)))
    result = growth_agent.analyze_account(db, 87)
    assert result["ai_used"] is True
    row, = ledger.values()
    assert row["user_id"] == 87 and row["source"] == "growth_agent_single"
    assert row["trigger"] == "automation" and row["product"] == "b2c"


def test_bulk_growth_is_shared_and_never_allocated_to_current_profile(monkeypatch, ledger):
    candidate = dict(user_id=87, name="Test", email="test@example.invalid", destination="US",
                     visa_type="F1", intent_score=40, tenure_days=5, days_since_last_login=1,
                     hit_any_limit=False, usage_detail={}, heard_about_us="", acquisition_channel="")
    monkeypatch.setattr(growth_agent, "compute_candidates", lambda db, limit: ([candidate], 1))
    monkeypatch.setattr(growth_agent, "_build_prompt", lambda candidates: "Offline prompt")
    monkeypatch.setattr(growth_agent, "is_ai_configured", lambda: True)
    monkeypatch.setattr(growth_agent, "_model_candidates", lambda: ["gemini-2.5-pro"])
    generate = Mock(return_value=response('[{"user_id":87,"recommended_promotion":"hold"}]'))
    monkeypatch.setattr(growth_agent, "genai", SimpleNamespace(GenerativeModel=lambda name: SimpleNamespace(generate_content=generate)))
    result = growth_agent.run_conversion_analysis(Mock())
    assert result["analyzed_count"] == 1
    row, = ledger.values()
    assert row["user_id"] is None and row["organization_id"] is None
    assert row["product"] == "shared" and row["trigger"] == "automation"


def test_catalog_grounding_stays_disabled_when_old_flag_is_true(monkeypatch, ledger):
    factory = Mock(side_effect=AssertionError("Catalog must not create a search client"))
    monkeypatch.setattr(gemini_service, "is_ai_configured", lambda: True)
    monkeypatch.setattr(gemini_service, "get_genai_client", factory)
    monkeypatch.setattr(course_catalog, "GROUNDING_ENABLED", True)
    assert course_catalog._grounded_generate("Offline prompt", ["gemini-2.5-pro"], "catalog_test") is None
    factory.assert_not_called()
    assert not ledger


def test_experiences_records_provider_attempt_before_response_logging_can_fail(monkeypatch, ledger):
    generate = Mock(side_effect=[response("first"), response("second")])
    client = SimpleNamespace(models=SimpleNamespace(generate_content=generate))
    monkeypatch.setattr(news, "latest_genai_types", types)
    monkeypatch.setattr(news, "_log_gemini_prompt", Mock())
    monkeypatch.setattr(news, "_log_gemini_response", Mock(side_effect=[ValueError("offline parsing issue"), None]))
    result, meta = news._generate_content_with_grounding(client, "Offline prompt", "gemini-2.5-pro", "news.f1_interview_experiences", False)
    assert result.text == "second" and meta["grounded"]
    assert len(ledger) == 2 and all(row["usage_state"] == "measured" for row in ledger.values())
    assert all(row["product"] == "shared" and row["user_id"] is None for row in ledger.values())


def test_tts_counts_success_before_audio_validation_and_keeps_timeouts_unknown(monkeypatch, ledger):
    monkeypatch.setattr(gemini_service, "USE_VERTEX_AI", False)
    monkeypatch.setenv("GOOGLE_TTS_API_KEY", "offline-key")
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-offline-key")
    monkeypatch.setattr(officer_tts, "_service_account_token", lambda: None)
    post = Mock(side_effect=[TimeoutError("offline timeout"), SimpleNamespace(ok=True, json=lambda: {"audioContent": "a"})])
    monkeypatch.setattr(officer_tts.requests, "post", post)
    with pytest.raises(officer_tts.TtsUnavailable, match="undecodable"):
        officer_tts.synthesize_officer_line("**Hello.** [smiles]", user_id=87)
    rows = list(ledger.values())
    assert len(rows) == 2 and [row["usage_state"] for row in rows] == ["unknown", "measured"]
    assert rows[1]["character_count"] == 6
    assert all(row["unit_type"] == "characters" and row["total_tokens"] == 0 for row in rows)
    assert all(row["user_id"] == 87 and row["provider"] == "google_cloud_tts" for row in rows)


def test_tts_records_nothing_when_no_provider_request_is_sent(monkeypatch, ledger):
    monkeypatch.setattr(gemini_service, "USE_VERTEX_AI", True)
    monkeypatch.setattr(officer_tts, "_cloud_tts_headers", lambda: None)
    with pytest.raises(officer_tts.TtsUnavailable):
        officer_tts.synthesize_officer_line("Hello", user_id=87)
    assert not ledger


def test_cached_generation_records_storage_once_without_inventing_token_hours(monkeypatch, ledger):
    cache = SimpleNamespace(name="cachedContents/offline", usage_metadata=SimpleNamespace(total_token_count=100))
    create = Mock(return_value=cache)
    generate = Mock(side_effect=[response(), response()])
    fake_genai = SimpleNamespace(
        caching=SimpleNamespace(CachedContent=SimpleNamespace(create=create, get=lambda name: cache)),
        GenerativeModel=SimpleNamespace(from_cached_content=lambda **kwargs: SimpleNamespace(generate_content=generate)),
    )
    monkeypatch.setattr(gemini_service, "genai", fake_genai)
    monkeypatch.setattr(gemini_cache, "is_enabled", lambda: True)
    monkeypatch.setattr(gemini_cache, "MIN_CHARS", 1)
    monkeypatch.setattr(gemini_cache, "_REGISTRY", {})
    from app import ai_guardrails
    monkeypatch.setattr(ai_guardrails, "record_cache_event", Mock())

    for _ in range(2):
        assert gemini_cache.generate_content_cached(
            prompt="Offline prompt", context_text="Offline reusable context",
            model_name="gemini-2.5-pro", source="document_ai",
        ) is not None

    create.assert_called_once()
    storage = [row for row in ledger.values() if row["unit_type"] == "cache_token_hours"]
    generated = [row for row in ledger.values() if row["unit_type"] == "tokens"]
    assert len(storage) == 1 and len(generated) == 2
    assert storage[0]["pricing_status"] == "unpriced" and storage[0]["usage_state"] == "unknown"
    assert storage[0]["total_tokens"] == 0 and storage[0]["product"] == "shared"
    assert storage[0]["user_id"] is None
    assert sum(row["total_tokens"] for row in generated) == 42


def test_tts_does_not_dispatch_when_both_ledger_and_spool_are_unavailable(monkeypatch, ledger):
    monkeypatch.setattr(gemini_service, "USE_VERTEX_AI", True)
    monkeypatch.setattr(officer_tts, "_cloud_tts_headers", lambda: {"Authorization": "offline"})
    monkeypatch.setattr(ai_usage, "_write_event", lambda payload: False)
    with pytest.raises(officer_tts.TtsUnavailable, match="accounting is unavailable"):
        officer_tts.synthesize_officer_line("Hello", user_id=87)
    officer_tts.requests.post.assert_not_called()


def test_cache_creation_does_not_dispatch_when_accounting_cannot_be_persisted(monkeypatch, ledger):
    create = Mock()
    genai = SimpleNamespace(caching=SimpleNamespace(CachedContent=SimpleNamespace(create=create)))
    monkeypatch.setattr(ai_usage, "_write_event", lambda payload: False)
    monkeypatch.setattr(gemini_cache, "_REGISTRY", {})
    assert gemini_cache._get_or_create_cache(genai, "gemini-2.5-pro", "Offline context", "document_ai") == (None, False)
    create.assert_not_called()
