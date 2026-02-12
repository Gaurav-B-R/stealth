from sqlalchemy import text

from app.database import engine


def _get_table_columns(conn, table_name: str):
    if engine.dialect.name == "sqlite":
        result = conn.execute(text(f"PRAGMA table_info({table_name})"))
        return {row[1] for row in result}

    result = conn.execute(
        text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = :table_name
            """
        ),
        {"table_name": table_name},
    )
    return {row[0] for row in result}


def ensure_user_legal_consent_column():
    """
    Patch users table schema in-place for environments without full migrations.
    """
    with engine.begin() as conn:
        columns = _get_table_columns(conn, "users")
        if "accepted_terms_privacy_at" not in columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN accepted_terms_privacy_at TIMESTAMP"))


def ensure_subscription_usage_columns():
    """
    Patch subscriptions table schema in-place for environments without full migrations.
    """
    with engine.begin() as conn:
        columns = _get_table_columns(conn, "subscriptions")

        if "prep_sessions_used" not in columns:
            conn.execute(text("ALTER TABLE subscriptions ADD COLUMN prep_sessions_used INTEGER NOT NULL DEFAULT 0"))

        if "mock_interviews_used" not in columns:
            conn.execute(text("ALTER TABLE subscriptions ADD COLUMN mock_interviews_used INTEGER NOT NULL DEFAULT 0"))
