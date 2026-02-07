"""
Migration script for referral program support.
Adds referral-related columns to users table and indexes.
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

        alterations = []
        if "referral_code" not in columns:
            alterations.append("ALTER TABLE users ADD COLUMN referral_code VARCHAR")
        if "referred_by_user_id" not in columns:
            if is_sqlite:
                alterations.append("ALTER TABLE users ADD COLUMN referred_by_user_id INTEGER")
            else:
                alterations.append("ALTER TABLE users ADD COLUMN referred_by_user_id INTEGER REFERENCES users(id)")
        if "first_login_at" not in columns:
            alterations.append("ALTER TABLE users ADD COLUMN first_login_at TIMESTAMP")
        if "referral_reward_granted_at" not in columns:
            alterations.append("ALTER TABLE users ADD COLUMN referral_reward_granted_at TIMESTAMP")

        for sql in alterations:
            conn.execute(text(sql))
            print(f"✅ Executed: {sql}")

        # Indexes (idempotent)
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_users_referral_code ON users(referral_code)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_users_referred_by_user_id ON users(referred_by_user_id)"))
        conn.commit()

        print("✅ Referral migration completed successfully.")
        print("Next: restart app so startup backfill can generate referral codes for existing users.")


if __name__ == "__main__":
    migrate()
