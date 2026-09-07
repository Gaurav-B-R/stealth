"""Offline metering invariants: actual attempts, provider counters and recovery."""

import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import ai_usage, models, schema_patch


@pytest.fixture()
def ledger(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    # Only the accounting table is needed. No network, credentials, or app startup.
    models.GeminiUsageEvent.__table__.create(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(ai_usage, "SessionLocal", factory)
    monkeypatch.setattr(ai_usage, "_record_cache_saving", lambda _: None)
    monkeypatch.setenv("AI_USAGE_SPOOL_DIR", str(tmp_path / "private-spool"))
    monkeypatch.setenv("GEMINI_PROVIDER", "developer")
    monkeypatch.delenv("GEMINI_DEVELOPER_PROJECT_ID", raising=False)
    ai_usage.reset_usage_account()
    with factory() as session:
        yield session, factory, engine
    ai_usage.reset_usage_account()
    engine.dispose()


def answer(*, response_id=None, **counters):
    defaults = dict(prompt_token_count=100, candidates_token_count=30, thoughts_token_count=20,
                    tool_use_prompt_token_count=10, total_token_count=160, cached_content_token_count=40)
    defaults.update(counters)
    return SimpleNamespace(usage_metadata=SimpleNamespace(**defaults), response_id=response_id,
                           candidates=[], text="private generated text must not be stored")


def rows(ledger):
    db, _, _ = ledger
    db.expire_all()
    return db.query(models.GeminiUsageEvent).order_by(models.GeminiUsageEvent.id).all()


def test_exact_provider_components_and_no_prompt_content(ledger):
    response = answer(response_id="provider-id")
    ai_usage.tracked_gemini_call("mock_interview", "gemini-2.5-flash", lambda: response,
                                  user_id=42, product="b2c", trigger="user")
    event, = rows(ledger)
    assert (event.prompt_tokens, event.candidate_tokens, event.thought_tokens, event.tool_tokens) == (100, 30, 20, 10)
    assert event.output_tokens == 50
    assert event.total_tokens == 160  # cache already belongs to prompt
    assert event.cached_tokens == 40
    assert (event.user_id, event.product, event.trigger) == (42, "b2c", "user")
    assert event.usage_state == "measured"
    assert event.metering_version == 2
    assert event.response_id == "provider-id"
    assert "private generated" not in event.raw_usage_json
    assert json.loads(event.raw_usage_json)["thoughts_token_count"] == 20


def test_dispatch_pricing_context_survives_completion_without_prompt_content(ledger, monkeypatch):
    monkeypatch.setenv("GEMINI_PROVIDER", "vertex")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "global")
    context = ai_usage.gemini_pricing_context("private student prompt")

    def dispatched():
        pending, = rows(ledger)
        assert json.loads(pending.raw_usage_json)["_rilono_pricing"] == context
        return answer(response_id="priced", tool_use_prompt_token_count=0, total_token_count=150)

    ai_usage.tracked_gemini_call("student_ai_chat", "gemini-2.5-flash", dispatched, pricing_context=context)
    event, = rows(ledger)
    metadata = json.loads(event.raw_usage_json)
    assert metadata["_rilono_pricing"] == {"service_tier": "standard", "location": "global", "input_modalities": ["TEXT"]}
    assert metadata["prompt_token_count"] == 100
    assert "private" not in event.raw_usage_json
    from app.ai_cost_calculation import calculate_event
    # (60 uncached × .30 + 40 cached × .03 + 50 output × 2.50) / 1M.
    assert calculate_event(event)["calculated_cost_usd"] == "0.0001442"


def test_pricing_context_keeps_base_service_tier_when_other_settings_change():
    context = ai_usage.gemini_pricing_context("text", base_generation_config={"service_tier": "priority"}, generation_config={"max_output_tokens": 10})
    assert context["service_tier"] == "priority"
    override = ai_usage.gemini_pricing_context("text", base_generation_config={"service_tier": "priority"}, generation_config={"service_tier": "flex"})
    assert override["service_tier"] == "flex"
    assert "input_modalities" not in ai_usage.gemini_pricing_context(["text", {"inline_data": {"mime_type": "audio/wav"}}])


def test_dispatch_context_never_turns_missing_provider_usage_into_measured_usage(ledger):
    ai_usage.tracked_gemini_call("student_ai_chat", "gemini-2.5-flash", lambda: SimpleNamespace(text="private"),
                                 pricing_context=ai_usage.gemini_pricing_context("private prompt"))
    event, = rows(ledger)
    assert event.usage_state == "unknown"
    from app.ai_cost_calculation import calculate_event
    assert calculate_event(event)["calculation_status"] == "unavailable"


def test_each_callback_attempt_pending_before_dispatch_and_discarded_response_kept(ledger):
    def first():
        assert rows(ledger)[0].usage_state == "pending"
        return answer(response_id="first")
    response = ai_usage.tracked_gemini_call("mock_interview", "gemini-2.5-flash", first, user_id=42)
    ai_usage.record_gemini_usage("student_ai_chat", "gemini-2.5-flash", response, status="empty")
    ai_usage.tracked_gemini_call("mock_interview", "gemini-2.5-flash", lambda: answer(response_id="second"), user_id=42)
    events = rows(ledger)
    assert len(events) == 2
    assert events[0].status == "empty"
    assert events[0].source == "mock_interview"
    assert sum(event.total_tokens for event in events) == 320


def test_legacy_explicit_recorder_cannot_double_count_wrapped_response(ledger):
    response = ai_usage.tracked_gemini_call("mock_interview", "gemini-2.5-flash", lambda: answer())
    ai_usage.record_gemini_usage("old_source", "gemini-2.5-flash", response)
    assert len(rows(ledger)) == 1


def test_provider_response_id_deduplicates_separate_response_objects(ledger):
    ai_usage.record_gemini_usage("student_ai_chat", "gemini-2.5-flash", answer(response_id="same"))
    ai_usage.record_gemini_usage("student_ai_chat", "gemini-2.5-flash", answer(response_id="same"))
    assert len(rows(ledger)) == 1


def test_missing_metadata_retains_unknown_usage(ledger):
    response = SimpleNamespace(candidates=[], text="answer without counters")
    assert ai_usage.tracked_gemini_call("chat", "gemini-2.5-flash", lambda: response) is response
    event, = rows(ledger)
    assert event.usage_state == "unknown"
    assert event.pricing_status == "unknown"
    assert event.raw_usage_json is None


def test_no_inferred_thinking_or_total(ledger):
    response = answer(thoughts_token_count=None, tool_use_prompt_token_count=None)
    ai_usage.record_gemini_usage("chat", "gemini-2.5-flash", response)
    event, = rows(ledger)
    assert event.thought_tokens == 0
    assert event.total_tokens == 160
    assert event.output_tokens == 30
    assert event.pricing_status == "partial"
    ai_usage.record_gemini_usage("chat", "gemini-2.5-flash", answer(total_token_count=None))
    assert rows(ledger)[1].usage_state == "unknown"


def test_unknown_model_preserves_usage_without_fallback_pricing(ledger):
    ai_usage.record_gemini_usage("chat", "future-model-unpriced", answer())
    event, = rows(ledger)
    assert event.total_tokens == 160
    assert event.pricing_status == "unpriced"
    assert event.estimated_cost_usd == 0


def test_timeout_is_unknown_and_original_exception_rethrown(ledger):
    original = TimeoutError("private request context")
    def fail():
        raise original
    with pytest.raises(TimeoutError) as caught:
        ai_usage.tracked_gemini_call("chat", "gemini-2.5-flash", fail)
    assert caught.value is original
    event, = rows(ledger)
    assert event.usage_state == "unknown"
    assert event.status == "error"
    assert event.raw_usage_json is None


@pytest.mark.parametrize("status_code", [400, 500])
def test_definitive_provider_unbilled_failure(ledger, status_code):
    exc = RuntimeError("provider failure")
    exc.status_code = status_code
    def fail():
        raise exc
    with pytest.raises(RuntimeError):
        ai_usage.tracked_gemini_call("chat", "gemini-2.5-flash", fail)
    assert rows(ledger)[0].usage_state == "not_billed"


def test_shared_automation_never_inherits_admin_profile(ledger):
    token = ai_usage.set_usage_account(user_id=1, product="b2c", trigger="user")
    try:
        ai_usage.tracked_gemini_call("growth_agent", "gemini-2.5-flash", lambda: answer(),
                                     product="shared", trigger="automation")
    finally:
        ai_usage.reset_usage_account(token)
    event, = rows(ledger)
    assert event.user_id is None and event.organization_id is None
    assert event.product == "shared" and event.trigger == "automation"


def test_developer_project_is_not_inferred_from_vertex_setting(ledger, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "unrelated-cloud-project")
    ai_usage.record_gemini_usage("chat", "gemini-2.5-flash", answer())
    assert rows(ledger)[0].project_id is None
    monkeypatch.setenv("GEMINI_DEVELOPER_PROJECT_ID", "explicit-developer-project")
    ai_usage.record_gemini_usage("chat", "gemini-2.5-flash", answer())
    assert rows(ledger)[1].project_id == "explicit-developer-project"


def test_tts_uses_characters_with_idempotent_pending_completion(ledger):
    ai_usage.record_tts_usage("mock_interview_tts", "officer", None, cost_usd=None,
                              user_id=42, event_key="tts-attempt", usage_state="pending", status="pending")
    ai_usage.record_tts_usage("mock_interview_tts", "officer", 250, cost_usd=.01,
                              user_id=42, event_key="tts-attempt")
    event, = rows(ledger)
    assert event.character_count == 250 and event.unit_type == "characters"
    assert event.provider == "google_cloud_tts"
    assert event.total_tokens == event.prompt_tokens == 0
    assert float(event.estimated_cost_usd) == pytest.approx(.01)


def test_failed_database_write_spools_and_replays_once(ledger, monkeypatch):
    _, factory, _ = ledger
    def unavailable():
        raise OSError("database offline")
    monkeypatch.setattr(ai_usage, "SessionLocal", unavailable)
    ai_usage.tracked_gemini_call("chat", "gemini-2.5-flash", lambda: answer(response_id="spooled"), user_id=42)
    assert ai_usage.get_metering_health()["spooled_events"] == 1
    spool, = list(ai_usage._spool_dir().glob("*.json"))
    assert spool.stat().st_mode & 0o777 == 0o600
    assert "private generated" not in spool.read_text()
    monkeypatch.setattr(ai_usage, "SessionLocal", factory)
    assert ai_usage.replay_usage_spool() == {"replayed": 1, "failed": 0}
    assert ai_usage.replay_usage_spool() == {"replayed": 0, "failed": 0}
    event, = rows(ledger)
    assert event.total_tokens == 160 and event.usage_state == "measured"


def test_unsafely_untracked_call_is_not_sent(ledger, monkeypatch):
    monkeypatch.setattr(ai_usage, "_write_event", lambda _: False)
    calls = []
    with pytest.raises(RuntimeError, match="not sent"):
        ai_usage.tracked_gemini_call("chat", "gemini-2.5-flash", lambda: calls.append(1))
    assert calls == []


def test_legacy_tts_migration_is_idempotent_without_invented_history(monkeypatch):
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("""CREATE TABLE gemini_usage_events (
            id INTEGER PRIMARY KEY, source VARCHAR NOT NULL, model VARCHAR NOT NULL,
            prompt_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0,
            total_tokens INTEGER NOT NULL DEFAULT 0, estimated_cost_usd NUMERIC(12,6) NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL)"""))
        conn.execute(text("""INSERT INTO gemini_usage_events (source,model,prompt_tokens,total_tokens)
                          VALUES ('mock_interview_tts','gcp-tts/officer',120,120),
                                 ('student_ai_chat','gemini-2.5-flash',100,130)"""))
    monkeypatch.setattr(schema_patch, "engine", engine)
    schema_patch.ensure_gemini_usage_table()
    schema_patch.ensure_gemini_usage_table()
    with sessionmaker(bind=engine)() as db:
        tts, chat = db.query(models.GeminiUsageEvent).order_by(models.GeminiUsageEvent.id).all()
        assert tts.character_count == 120 and tts.total_tokens == 0
        assert chat.total_tokens == 130
        assert chat.user_id is None and chat.provider is None
        assert chat.product == "unknown" and chat.usage_state == "legacy" and chat.metering_version == 1
    engine.dispose()


def test_legacy_analytics_excludes_tts_characters_before_migration(ledger):
    db, _, _ = ledger
    db.add(models.GeminiUsageEvent(source="mock_interview_tts", model="gcp-tts/officer",
                                   total_tokens=500, prompt_tokens=500, estimated_cost_usd=.1))
    db.add(models.GeminiUsageEvent(source="chat", model="gemini-2.5-flash",
                                   total_tokens=130, prompt_tokens=100, estimated_cost_usd=.2))
    db.commit()
    report = ai_usage.build_ai_usage_analytics(db)
    assert report["totals"]["all_time"]["tokens"] == 130
    assert report["totals"]["all_time"]["tts_characters"] == 500
    assert sum(row["tts_characters"] for row in report["by_source"]) == 500
    assert sum(row["tts_characters"] for row in report["by_model"]) == 500
    assert sum(row["tokens"] for row in report["by_source"]) == 130
    assert sum(row["tokens"] for row in report["by_model"]) == 130
    assert sum(row["tokens"] for row in report["daily"]) == 130


def test_camelcase_provider_json_is_metered_without_double_counting_cache(ledger):
    response = {"usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5,
                                  "thoughtsTokenCount": 3, "totalTokenCount": 18,
                                  "cachedContentTokenCount": 8}, "responseId": "json-provider-response"}
    ai_usage.record_gemini_usage("chat", "gemini-2.5-flash", response)
    event, = rows(ledger)
    assert event.total_tokens == 18 and event.cached_tokens == 8
    assert event.output_tokens == 8 and event.usage_state == "measured"


def test_cache_storage_never_inflates_generated_tokens_or_claims_actual_duration(ledger):
    ai_usage.record_cache_storage_usage("chat_cache", "gemini-2.5-flash", event_key="cache-op")
    ai_usage.record_cache_storage_usage("chat_cache", "gemini-2.5-flash", event_key="cache-op",
                                        cache_name="provider-cache-resource", total_token_count=1000,
                                        ttl_seconds=3600, status="ok", usage_state="measured")
    event, = rows(ledger)
    assert event.unit_type == "cache_token_hours" and event.total_tokens == 0
    assert event.usage_state == "unknown" and event.pricing_status == "unpriced"
    assert "provider-cache-resource" not in event.raw_usage_json
    assert json.loads(event.raw_usage_json)["cached_content_token_count"] == 1000


def test_stale_pending_spool_cannot_overwrite_measured_event(ledger):
    response = ai_usage.tracked_gemini_call("chat", "gemini-2.5-flash", lambda: answer())
    event, = rows(ledger)
    ai_usage._spool({"event_key": event.event_key, "source": "chat", "model": "gemini-2.5-flash",
                     "usage_state": "pending", "pricing_status": "pending"})
    assert ai_usage.replay_usage_spool()["replayed"] == 1
    assert rows(ledger)[0].usage_state == "measured"
    assert rows(ledger)[0].total_tokens == 160


def test_vertex_rates_are_explicitly_partial_until_rate_card_verified(ledger, monkeypatch):
    monkeypatch.setenv("GEMINI_PROVIDER", "vertex")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-vertex-project")
    ai_usage.record_gemini_usage("chat", "gemini-2.5-flash", answer())
    event, = rows(ledger)
    assert event.provider == "vertex" and event.project_id == "test-vertex-project"
    assert event.pricing_status == "partial"
    assert event.pricing_version.startswith("vertex:")
    health = ai_usage.get_metering_health()
    assert health["configured_project_id"] == "test-vertex-project"
    assert health["authentication_check"] == "not_performed"


@pytest.mark.parametrize("source", ["mock_interview", "interview_feedback"])
def test_enterprise_context_precedes_ambiguous_legacy_feature(ledger, source):
    token = ai_usage.set_usage_account(user_id=91, organization_id=7)
    try:
        ai_usage.tracked_gemini_call(source, "gemini-2.5-flash", lambda: answer())
    finally:
        ai_usage.reset_usage_account(token)
    event, = rows(ledger)
    assert event.product == "b2b"
    assert event.organization_id == 7 and event.user_id == 91


def test_ambiguous_feature_without_account_remains_unknown(ledger):
    ai_usage.record_gemini_usage("mock_interview", "gemini-2.5-flash", answer())
    event, = rows(ledger)
    assert event.product == "unknown" and event.user_id is None


def test_two_tracked_attempts_same_response_keep_one_canonical_measurement(ledger):
    ai_usage.tracked_gemini_call("student_mock_interview", "gemini-2.5-flash",
                                lambda: answer(response_id="one-provider-response"), user_id=42)
    duplicate = ai_usage.tracked_gemini_call("student_ai_chat", "gemini-2.5-flash",
                                            lambda: answer(response_id="one-provider-response"), user_id=99)
    ai_usage.record_gemini_usage("different_source", "gemini-2.5-flash", duplicate, status="empty")
    canonical, repeated = rows(ledger)
    assert canonical.user_id == 42 and canonical.source == "student_mock_interview"
    assert canonical.total_tokens == 160 and canonical.usage_state == "measured"
    assert repeated.usage_state == repeated.status == repeated.pricing_status == "duplicate"
    assert repeated.total_tokens == repeated.prompt_tokens == repeated.output_tokens == repeated.cached_tokens == 0
    assert repeated.search_queries == 0 and repeated.estimated_cost_usd == 0
    assert sum(event.total_tokens for event in rows(ledger)) == 160
    assert json.loads(repeated.raw_usage_json)["total_token_count"] == 160  # audit evidence retained


def test_same_response_id_in_different_project_is_independent(ledger, monkeypatch):
    monkeypatch.setenv("GEMINI_DEVELOPER_PROJECT_ID", "project-a")
    ai_usage.tracked_gemini_call("chat", "gemini-2.5-flash", lambda: answer(response_id="same-id"))
    monkeypatch.setenv("GEMINI_DEVELOPER_PROJECT_ID", "project-b")
    ai_usage.tracked_gemini_call("chat", "gemini-2.5-flash", lambda: answer(response_id="same-id"))
    assert sum(event.total_tokens for event in rows(ledger)) == 320
    assert all(event.usage_state == "measured" for event in rows(ledger))


def test_database_constraint_prevents_duplicate_response_race(ledger):
    from sqlalchemy.exc import IntegrityError
    db, _, _ = ledger
    db.add(models.GeminiUsageEvent(event_key="canonical", response_id="race", provider="developer",
                                   source="chat", model="model", usage_state="measured"))
    db.commit()
    db.add(models.GeminiUsageEvent(event_key="different", response_id="race", provider="developer",
                                   source="chat", model="model", usage_state="measured"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    assert len(rows(ledger)) == 1


def test_duplicate_completion_spool_replays_without_inflating_usage(ledger, monkeypatch):
    ai_usage.tracked_gemini_call("chat", "gemini-2.5-flash", lambda: answer(response_id="same"))
    base = ai_usage._event_base("other_source", "gemini-2.5-flash", user_id=99)
    ai_usage._persist(base)
    ai_usage._spool(ai_usage._complete_event(base, answer(response_id="same")))
    assert ai_usage.replay_usage_spool() == {"replayed": 1, "failed": 0}
    canonical, duplicate = rows(ledger)
    assert canonical.total_tokens == 160 and duplicate.total_tokens == 0
    assert duplicate.usage_state == "duplicate"


def test_migration_retains_early_v2_duplicate_attempt_without_double_usage(ledger, monkeypatch):
    db, _, engine = ledger
    with engine.begin() as conn:
        conn.execute(text("DROP INDEX uq_gemini_usage_provider_response"))
    for key in ("first", "repeated"):
        db.add(models.GeminiUsageEvent(event_key=key, response_id="early-v2-duplicate", provider="developer",
                                       source="chat", model="gemini-2.5-flash", usage_state="measured",
                                       metering_version=2, total_tokens=160, estimated_cost_usd=.01))
    db.commit()
    monkeypatch.setattr(schema_patch, "engine", engine)
    schema_patch.ensure_gemini_usage_table()
    schema_patch.ensure_gemini_usage_table()
    canonical, duplicate = rows(ledger)
    assert canonical.total_tokens == 160 and canonical.usage_state == "measured"
    assert duplicate.total_tokens == 0 and duplicate.usage_state == "duplicate"
    assert duplicate.estimated_cost_usd == 0
