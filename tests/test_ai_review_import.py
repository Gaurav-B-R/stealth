"""Read-only review imports keep real counters and exclude authentication data/cost guesses."""
import json
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from scripts.import_ai_cost_review import import_retained_records, sanitize_usage_metadata


def source_database(path):
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as db:
        db.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT, full_name TEXT, hashed_password TEXT, password_reset_token TEXT, is_enterprise_account BOOLEAN)"))
        db.execute(text("INSERT INTO users VALUES (1, 'fixture@example.com', 'Test fixture', 'private-password', 'private-token', 0)"))
        db.execute(text("CREATE TABLE gemini_usage_events (id INTEGER PRIMARY KEY, user_id INTEGER, source TEXT, model TEXT, total_tokens INTEGER, prompt_tokens INTEGER, output_tokens INTEGER, estimated_cost_usd NUMERIC, created_at DATETIME)"))
        db.execute(text("INSERT INTO gemini_usage_events VALUES (1, 1, 'student_ai_chat', 'retained-model', 123, 100, 23, 7.25, '2026-09-01 00:00:00')"))
    engine.dispose()


def test_import_preserves_counters_and_source_excludes_secrets_and_estimates(tmp_path, monkeypatch):
    for key in ["PYTHON_DOTENV_DISABLED", "DATABASE_URL", "GEMINI_API_KEY", "RESEND_API_KEY", "FIELD_ENCRYPTION_KEY"]:
        monkeypatch.setenv(key, "")
    source, target = tmp_path / "source.sqlite3", tmp_path / "review.sqlite3"
    source_database(source)
    counts = import_retained_records(f"sqlite:///{source}", target)
    assert (counts["users"], counts["usage_events"]) == (1, 1)
    assert target.stat().st_mode & 0o777 == 0o600
    local = create_engine(f"sqlite:///{target}")
    with local.connect() as db:
        user = db.execute(text("SELECT * FROM users")).mappings().one()
        event = db.execute(text("SELECT * FROM gemini_usage_events")).mappings().one()
        assert user["hashed_password"] == "" and user["password_reset_token"] is None
        assert event["total_tokens"] == 123 and event["metering_version"] == 1
        assert event["estimated_cost_usd"] == 0 and event["pricing_status"] == "unavailable"
    local.dispose()
    remote = create_engine(f"sqlite:///{source}")
    with remote.connect() as db:
        assert db.execute(text("SELECT hashed_password FROM users")).scalar() == "private-password"
        assert float(db.execute(text("SELECT estimated_cost_usd FROM gemini_usage_events")).scalar()) == 7.25
    remote.dispose()


def test_failed_refresh_retains_existing_local_database(tmp_path, monkeypatch):
    for key in ["PYTHON_DOTENV_DISABLED", "DATABASE_URL", "GEMINI_API_KEY", "RESEND_API_KEY", "FIELD_ENCRYPTION_KEY"]:
        monkeypatch.setenv(key, "")
    source, target = tmp_path / "source.sqlite3", tmp_path / "review.sqlite3"
    source_database(source)
    import_retained_records(f"sqlite:///{source}", target)
    before = target.read_bytes()
    engine = create_engine(f"sqlite:///{source}")
    with engine.begin() as db:
        db.execute(text("DROP TABLE gemini_usage_events"))
    engine.dispose()
    with pytest.raises(Exception):
        import_retained_records(f"sqlite:///{source}", target)
    assert target.read_bytes() == before


def test_import_keeps_safe_provider_usage_for_calculation_without_prompts_or_arbitrary_metadata(tmp_path, monkeypatch):
    from app.ai_cost_calculation import calculate_event
    for key in ["PYTHON_DOTENV_DISABLED", "DATABASE_URL", "GEMINI_API_KEY", "RESEND_API_KEY", "FIELD_ENCRYPTION_KEY"]:
        monkeypatch.setenv(key, "")
    source, target = tmp_path / "source.sqlite3", tmp_path / "review.sqlite3"
    source_database(source)
    raw = {"promptTokenCount": 100, "candidatesTokenCount": 20, "thoughtsTokenCount": 3,
           "cachedContentTokenCount": 40, "totalTokenCount": 123, "toolUsePromptTokenCount": 0,
           "promptTokensDetails": [{"modality": "TEXT", "tokenCount": 100, "prompt": "private-detail"}],
           "cacheTokensDetails": [{"modality": "TEXT", "tokenCount": 40}],
           "trafficType": "PROVISIONED_THROUGHPUT", "prompt": "private-prompt",
           "response": "private-response", "api_key": "private-key",
           "_rilono_pricing": {"service_tier": "standard", "location": "global",
                               "input_modalities": ["TEXT"], "explicit_cache": True,
                               "prompt": "private-context", "credentials": {"secret": "private-nested-key"}}}
    engine = create_engine(f"sqlite:///{source}")
    with engine.begin() as db:
        for declaration in ("raw_usage_json TEXT", "metering_version INTEGER", "usage_state TEXT",
                            "provider TEXT", "candidate_tokens INTEGER", "thought_tokens INTEGER", "cached_tokens INTEGER"):
            db.execute(text(f"ALTER TABLE gemini_usage_events ADD COLUMN {declaration}"))
        db.execute(text("UPDATE gemini_usage_events SET model='gemini-2.5-flash', metering_version=2, usage_state='measured', provider='vertex', candidate_tokens=20, thought_tokens=3, cached_tokens=40, raw_usage_json=:raw"), {"raw": json.dumps(raw)})
    engine.dispose()
    before = source.read_bytes()
    import_retained_records(f"sqlite:///{source}", target)
    assert source.read_bytes() == before
    local = create_engine(f"sqlite:///{target}")
    with local.connect() as db:
        event = db.execute(text("SELECT * FROM gemini_usage_events")).mappings().one()
        metadata = json.loads(event["raw_usage_json"])
        assert "private" not in event["raw_usage_json"]
        assert metadata["prompt_token_count"] == 100
        assert metadata["prompt_tokens_details"] == [{"modality": "TEXT", "token_count": 100}]
        assert metadata["_rilono_pricing"] == {"service_tier": "standard", "location": "global",
                                               "input_modalities": ["TEXT"], "explicit_cache": True}
        assert metadata["traffic_type"] == "PROVISIONED_THROUGHPUT"
        result = calculate_event(event)
        assert Decimal(result["calculated_cost_usd"]) == Decimal(".0000767")
        assert result["calculation_status"] == "partial"
        assert "explicit_cache_storage" in result["excluded_components"]
        assert "provisioned_throughput_standard_list_value_only" in result["coverage_reasons"]
        assert event["estimated_cost_usd"] == event["search_cost_usd"] == 0
    local.dispose()


@pytest.mark.parametrize("raw", [None, "invalid-json", "[]", [], {"prompt": "secret"},
    {"prompt_token_count": True, "total_token_count": -1, "candidates_token_count": 1.5},
    {"prompt_tokens_details": [{"modality": {"prompt": "secret"}, "token_count": 1}]},
    {"_rilono_pricing": {"service_tier": "secret", "location": "private-location",
                         "input_modalities": ["private-prompt"], "explicit_cache": "private-key"}}])
def test_usage_metadata_sanitizer_rejects_arbitrary_or_invalid_values(raw):
    assert sanitize_usage_metadata(raw) is None


def test_usage_metadata_sanitizer_keeps_exact_counts_but_not_incomplete_modality_lists():
    data = {"prompt_token_count": "9007199254740993", "total_token_count": 9007199254740993,
            "cached_content_token_count": 0,
            "prompt_tokens_details": [{"modality": "TEXT", "token_count": 1},
                                      {"modality": "private-prompt", "token_count": 9}],
            "tool_use_prompt_tokens_details": [{"modality": "TEXT", "token_count": 0}],
            "_rilono_pricing": {"service_tier": "flex", "location": "us-central1", "explicit_cache": False}}
    clean = json.loads(sanitize_usage_metadata(data))
    assert clean["prompt_token_count"] == clean["total_token_count"] == 9007199254740993
    assert clean["cached_content_token_count"] == 0
    assert "prompt_tokens_details" not in clean
    assert clean["tool_use_prompt_tokens_details"] == [{"modality": "TEXT", "token_count": 0}]
    assert clean["_rilono_pricing"] == {"service_tier": "flex", "location": "us-central1", "explicit_cache": False}
