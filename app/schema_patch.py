from sqlalchemy import text
from app.database import engine


def _get_user_columns(conn):
    if engine.dialect.name == "sqlite":
        result = conn.execute(text("PRAGMA table_info(users)"))
        return {row[1] for row in result}

    result = conn.execute(
        text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'users'
            """
        )
    )
    return {row[0] for row in result}


def ensure_user_legal_consent_column():
    """
    Patch users table schema in-place for environments without full migrations.
    """
    with engine.begin() as conn:
        columns = _get_user_columns(conn)
        if "accepted_terms_privacy_at" not in columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN accepted_terms_privacy_at TIMESTAMP"))
