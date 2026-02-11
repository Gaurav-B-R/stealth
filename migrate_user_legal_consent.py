"""
Migration script to add legal consent tracking column to users table.
"""
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./rilono.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)


def _sqlite_columns(conn):
    result = conn.execute(text("PRAGMA table_info(users)"))
    return [row[1] for row in result]


def _postgres_columns(conn):
    result = conn.execute(
        text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'users'
            """
        )
    )
    return [row[0] for row in result]


def migrate():
    is_sqlite = DATABASE_URL.startswith("sqlite")
    with engine.connect() as conn:
        columns = _sqlite_columns(conn) if is_sqlite else _postgres_columns(conn)

        if "accepted_terms_privacy_at" not in columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN accepted_terms_privacy_at TIMESTAMP"))
            print("✅ Added column: accepted_terms_privacy_at")
        else:
            print("⏭️  Column already exists: accepted_terms_privacy_at")

        conn.commit()
        print("✅ Legal consent migration completed.")


if __name__ == "__main__":
    migrate()
