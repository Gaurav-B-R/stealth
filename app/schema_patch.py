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
        if "first_login_at" not in columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN first_login_at TIMESTAMP"))
        if "last_login_at" not in columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN last_login_at TIMESTAMP"))
        if "accepted_terms_privacy_at" not in columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN accepted_terms_privacy_at TIMESTAMP"))
        if "current_situation_story" not in columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN current_situation_story TEXT"))

        if "email_notifications_enabled" not in columns:
            conn.execute(
                text("ALTER TABLE users ADD COLUMN email_notifications_enabled BOOLEAN NOT NULL DEFAULT TRUE")
            )

        if "email_notifications_unsubscribed_at" not in columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN email_notifications_unsubscribed_at TIMESTAMP"))

        if "email_notifications_unsubscribe_reason" not in columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN email_notifications_unsubscribe_reason TEXT"))


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


def ensure_document_catalog_columns():
    """
    Patch document_type_catalog table schema for environments without full migrations.
    """
    with engine.begin() as conn:
        columns = _get_table_columns(conn, "document_type_catalog")

        if "stage_gate_requires_validation" not in columns:
            conn.execute(
                text(
                    "ALTER TABLE document_type_catalog "
                    "ADD COLUMN stage_gate_requires_validation BOOLEAN NOT NULL DEFAULT FALSE"
                )
            )


def ensure_subscription_payment_recurring_columns():
    """
    Patch subscription_payments schema for recurring Razorpay metadata.
    """
    with engine.begin() as conn:
        columns = _get_table_columns(conn, "subscription_payments")

        if "razorpay_subscription_id" not in columns:
            conn.execute(text("ALTER TABLE subscription_payments ADD COLUMN razorpay_subscription_id VARCHAR"))

        if "razorpay_invoice_id" not in columns:
            conn.execute(text("ALTER TABLE subscription_payments ADD COLUMN razorpay_invoice_id VARCHAR"))

        if "razorpay_plan_id" not in columns:
            conn.execute(text("ALTER TABLE subscription_payments ADD COLUMN razorpay_plan_id VARCHAR"))

        if "coupon_code" not in columns:
            conn.execute(text("ALTER TABLE subscription_payments ADD COLUMN coupon_code VARCHAR"))

        if "coupon_percent_off" not in columns:
            conn.execute(text("ALTER TABLE subscription_payments ADD COLUMN coupon_percent_off NUMERIC(5,2)"))

        if "pricing_model" not in columns:
            conn.execute(text("ALTER TABLE subscription_payments ADD COLUMN pricing_model VARCHAR"))


def ensure_coupon_percent_column():
    """
    Ensure coupon_codes.percent_off supports decimal discounts and normalized codes.
    """
    with engine.begin() as conn:
        columns = _get_table_columns(conn, "coupon_codes")
        if "coupon_code" not in columns or "percent_off" not in columns:
            return

        if engine.dialect.name == "postgresql":
            # Support decimal discounts (example: 99.99%).
            conn.execute(
                text(
                    "ALTER TABLE coupon_codes "
                    "ALTER COLUMN percent_off TYPE NUMERIC(5,2) "
                    "USING percent_off::numeric"
                )
            )


def ensure_coupon_usage_limit_column():
    """
    Allow configuring per-user usage limits for coupon codes.
    """
    with engine.begin() as conn:
        columns = _get_table_columns(conn, "coupon_codes")
        if "coupon_code" not in columns:
            return

        if "max_uses_per_user" not in columns:
            conn.execute(text("ALTER TABLE coupon_codes ADD COLUMN max_uses_per_user INTEGER"))


def ensure_referral_columns():
    """
    Patch users table schema for referral program fields in environments without full migrations.
    """
    with engine.begin() as conn:
        columns = _get_table_columns(conn, "users")

        if "referral_code" not in columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN referral_code VARCHAR"))

        if "referred_by_user_id" not in columns:
            if engine.dialect.name == "sqlite":
                conn.execute(text("ALTER TABLE users ADD COLUMN referred_by_user_id INTEGER"))
            else:
                conn.execute(
                    text("ALTER TABLE users ADD COLUMN referred_by_user_id INTEGER REFERENCES users(id)")
                )

        if "referral_reward_granted_at" not in columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN referral_reward_granted_at TIMESTAMP"))

        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_users_referral_code ON users(referral_code)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_users_referred_by_user_id ON users(referred_by_user_id)"))


def _table_exists(conn, table_name: str) -> bool:
    if engine.dialect.name == "sqlite":
        result = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name=:tbl"),
            {"tbl": table_name},
        )
        return result.fetchone() is not None

    result = conn.execute(
        text(
            "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = :tbl)"
        ),
        {"tbl": table_name},
    )
    return bool(result.scalar())


def ensure_f1_visa_news_table():
    """
    Ensure f1_visa_news table exists for environments without full migrations.
    Defence-in-depth alongside Base.metadata.create_all().
    """
    with engine.begin() as conn:
        if _table_exists(conn, "f1_visa_news"):
            return

        if engine.dialect.name == "sqlite":
            conn.execute(text("""
                CREATE TABLE f1_visa_news (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title VARCHAR NOT NULL,
                    summary TEXT NOT NULL,
                    why_it_matters TEXT,
                    source_name VARCHAR NOT NULL DEFAULT 'Source',
                    source_url VARCHAR,
                    published_date VARCHAR,
                    ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
                )
            """))
        else:
            conn.execute(text("""
                CREATE TABLE f1_visa_news (
                    id SERIAL PRIMARY KEY,
                    title VARCHAR NOT NULL,
                    summary TEXT NOT NULL,
                    why_it_matters TEXT,
                    source_name VARCHAR NOT NULL DEFAULT 'Source',
                    source_url VARCHAR,
                    published_date VARCHAR,
                    ingested_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
                )
            """))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_f1_visa_news_ingested_at ON f1_visa_news (ingested_at)"
            ))


def ensure_rilono_ai_chat_upload_events_table():
    """
    Ensure 24-hour Rilono AI chat upload usage table exists for quota tracking.
    """
    with engine.begin() as conn:
        if _table_exists(conn, "rilono_ai_chat_upload_events"):
            return

        if engine.dialect.name == "sqlite":
            conn.execute(text("""
                CREATE TABLE rilono_ai_chat_upload_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    attachment_id VARCHAR NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            """))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_rilono_ai_chat_upload_events_user_attachment "
                "ON rilono_ai_chat_upload_events (user_id, attachment_id)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_rilono_ai_chat_upload_events_created_at "
                "ON rilono_ai_chat_upload_events (created_at)"
            ))
        else:
            conn.execute(text("""
                CREATE TABLE rilono_ai_chat_upload_events (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    attachment_id VARCHAR NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
                )
            """))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_rilono_ai_chat_upload_events_user_attachment "
                "ON rilono_ai_chat_upload_events (user_id, attachment_id)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_rilono_ai_chat_upload_events_created_at "
                "ON rilono_ai_chat_upload_events (created_at)"
            ))
