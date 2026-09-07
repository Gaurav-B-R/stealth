"""Read-only review imports keep real counters and exclude authentication data/cost guesses."""
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from scripts.import_ai_cost_review import import_retained_records


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
