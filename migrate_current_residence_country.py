"""
Migration script to add current_residence_country to users table.
Also backfills existing users with India as requested.
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

        if "current_residence_country" not in columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN current_residence_country VARCHAR"))
            print("✅ Added column: current_residence_country")
        else:
            print("⏭️  Column already exists: current_residence_country")

        # Backfill existing users as requested.
        result = conn.execute(
            text(
                """
                UPDATE users
                SET current_residence_country = 'India'
                WHERE current_residence_country IS NULL OR current_residence_country = ''
                """
            )
        )
        conn.commit()
        print(f"✅ Backfilled users to India where empty: {result.rowcount}")


if __name__ == "__main__":
    migrate()
