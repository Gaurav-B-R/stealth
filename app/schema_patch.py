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
        if "visa_case_status" not in columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN visa_case_status VARCHAR"))
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


def ensure_enterprise_organization_columns():
    """
    Ensure enterprise organization table has immutable subdomain storage.
    """
    with engine.begin() as conn:
        if not _table_exists(conn, "enterprise_organizations"):
            return

        columns = _get_table_columns(conn, "enterprise_organizations")
        if "subdomain_slug" not in columns:
            conn.execute(text("ALTER TABLE enterprise_organizations ADD COLUMN subdomain_slug VARCHAR"))
        if "logo_url" not in columns:
            conn.execute(text("ALTER TABLE enterprise_organizations ADD COLUMN logo_url VARCHAR"))

        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "uq_enterprise_organizations_subdomain_slug "
                "ON enterprise_organizations(subdomain_slug)"
            )
        )


def ensure_enterprise_students_table():
    """
    Ensure enterprise_students table exists for enterprise student management.
    """
    with engine.begin() as conn:
        if _table_exists(conn, "enterprise_students"):
            columns = _get_table_columns(conn, "enterprise_students")
            if "intake" not in columns:
                conn.execute(text("ALTER TABLE enterprise_students ADD COLUMN intake VARCHAR"))
            return

        if engine.dialect.name == "sqlite":
            conn.execute(text("""
                CREATE TABLE enterprise_students (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    organization_id INTEGER NOT NULL,
                    student_name VARCHAR NOT NULL,
                    study_country_code VARCHAR NOT NULL,
                    study_country_name VARCHAR NOT NULL,
                    visa_type VARCHAR NOT NULL,
                    intake VARCHAR,
                    created_by_user_id INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP,
                    FOREIGN KEY(organization_id) REFERENCES enterprise_organizations(id),
                    FOREIGN KEY(created_by_user_id) REFERENCES users(id)
                )
            """))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_enterprise_students_organization_id "
                "ON enterprise_students(organization_id)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_enterprise_students_created_by_user_id "
                "ON enterprise_students(created_by_user_id)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_enterprise_students_org_created "
                "ON enterprise_students(organization_id, created_at)"
            ))
            return

        conn.execute(text("""
            CREATE TABLE enterprise_students (
                id SERIAL PRIMARY KEY,
                organization_id INTEGER NOT NULL REFERENCES enterprise_organizations(id),
                student_name VARCHAR NOT NULL,
                study_country_code VARCHAR NOT NULL,
                study_country_name VARCHAR NOT NULL,
                visa_type VARCHAR NOT NULL,
                intake VARCHAR,
                created_by_user_id INTEGER NOT NULL REFERENCES users(id),
                created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
                updated_at TIMESTAMPTZ
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_enterprise_students_organization_id "
            "ON enterprise_students(organization_id)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_enterprise_students_created_by_user_id "
            "ON enterprise_students(created_by_user_id)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_enterprise_students_org_created "
            "ON enterprise_students(organization_id, created_at)"
        ))


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


def ensure_company_finance_entries_table():
    """
    Ensure admin company finance analytics table exists and seed baseline spend once.
    """
    with engine.begin() as conn:
        if not _table_exists(conn, "company_finance_entries"):
            if engine.dialect.name == "sqlite":
                conn.execute(text("""
                    CREATE TABLE company_finance_entries (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        seed_key VARCHAR UNIQUE,
                        entry_type VARCHAR NOT NULL DEFAULT 'expense',
                        category VARCHAR NOT NULL,
                        vendor VARCHAR NOT NULL,
                        description TEXT,
                        amount_usd NUMERIC(12, 2) NOT NULL,
                        occurred_on DATE NOT NULL,
                        source VARCHAR NOT NULL DEFAULT 'manual',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
                        updated_at TIMESTAMP
                    )
                """))
            else:
                conn.execute(text("""
                    CREATE TABLE company_finance_entries (
                        id SERIAL PRIMARY KEY,
                        seed_key VARCHAR UNIQUE,
                        entry_type VARCHAR NOT NULL DEFAULT 'expense',
                        category VARCHAR NOT NULL,
                        vendor VARCHAR NOT NULL,
                        description TEXT,
                        amount_usd NUMERIC(12, 2) NOT NULL,
                        occurred_on DATE NOT NULL,
                        source VARCHAR NOT NULL DEFAULT 'manual',
                        created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
                        updated_at TIMESTAMPTZ
                    )
                """))

        columns = _get_table_columns(conn, "company_finance_entries")
        if "seed_key" not in columns:
            conn.execute(text("ALTER TABLE company_finance_entries ADD COLUMN seed_key VARCHAR"))
        if "entry_type" not in columns:
            conn.execute(text("ALTER TABLE company_finance_entries ADD COLUMN entry_type VARCHAR NOT NULL DEFAULT 'expense'"))
        if "category" not in columns:
            conn.execute(text("ALTER TABLE company_finance_entries ADD COLUMN category VARCHAR NOT NULL DEFAULT 'Operations'"))
        if "vendor" not in columns:
            conn.execute(text("ALTER TABLE company_finance_entries ADD COLUMN vendor VARCHAR NOT NULL DEFAULT 'Unknown'"))
        if "description" not in columns:
            conn.execute(text("ALTER TABLE company_finance_entries ADD COLUMN description TEXT"))
        if "amount_usd" not in columns:
            conn.execute(text("ALTER TABLE company_finance_entries ADD COLUMN amount_usd NUMERIC(12,2) NOT NULL DEFAULT 0"))
        if "occurred_on" not in columns:
            conn.execute(text("ALTER TABLE company_finance_entries ADD COLUMN occurred_on DATE NOT NULL DEFAULT '2026-01-01'"))
        if "source" not in columns:
            conn.execute(text("ALTER TABLE company_finance_entries ADD COLUMN source VARCHAR NOT NULL DEFAULT 'manual'"))
        if "created_at" not in columns:
            conn.execute(text("ALTER TABLE company_finance_entries ADD COLUMN created_at TIMESTAMP"))
        if "updated_at" not in columns:
            conn.execute(text("ALTER TABLE company_finance_entries ADD COLUMN updated_at TIMESTAMP"))

        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_company_finance_entries_seed_key "
            "ON company_finance_entries(seed_key)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_company_finance_entries_occurred_on "
            "ON company_finance_entries(occurred_on)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_company_finance_entries_vendor "
            "ON company_finance_entries(vendor)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_company_finance_entries_category "
            "ON company_finance_entries(category)"
        ))

        seed_entries = [
            ("rilono-seed-001", "2026-02-17", "AI Coding Tools", "Cursor", "Cursor editor subscription", "-21.57"),
            ("rilono-seed-002", "2026-02-22", "AI Model Tools", "Claude", "Claude workspace subscription", "-21.25"),
            ("rilono-seed-003", "2026-02-28", "AI Coding Tools", "Cursor", "Cursor editor subscription", "-21.25"),
            ("rilono-seed-004", "2026-03-04", "AI Coding Tools", "Cursor", "Cursor usage and tooling", "-31.56"),
            ("rilono-seed-005", "2026-03-09", "Cloud Infrastructure", "Render", "Render hosting usage", "-4.33"),
            ("rilono-seed-006", "2026-03-15", "AI Platform", "OpenAI", "OpenAI API and product usage", "-26.63"),
            ("rilono-seed-007", "2026-03-19", "Email & Domain", "Name Cheap Email", "Namecheap email service", "-2.81"),
            ("rilono-seed-008", "2026-03-24", "Product Distribution", "Chrome Extension", "Chrome extension registration", "-5.00"),
            ("rilono-seed-009", "2026-03-30", "Cloud Infrastructure", "Render Pro", "Render Pro plan", "-7.00"),
            ("rilono-seed-010", "2026-04-04", "Email & Domain", "Domain", "Domain purchase/renewal", "-11.00"),
            ("rilono-seed-011", "2026-04-10", "Cloud Infrastructure", "Render", "Render hosting usage", "-11.39"),
            ("rilono-seed-012", "2026-04-17", "Cloud Infrastructure", "Render", "Render hosting usage", "-10.39"),
            ("rilono-seed-013", "2026-04-25", "AI Model Tools", "Claude", "Claude workspace subscription", "-21.25"),
            ("rilono-seed-014", "2026-05-02", "AI Coding Tools", "Cursor", "Cursor editor subscription", "-21.25"),
            ("rilono-seed-015", "2026-05-10", "Cloud Infrastructure", "Render", "Render hosting usage", "-14.11"),
            ("rilono-seed-016", "2026-05-18", "AI Coding Tools", "Cursor", "Cursor usage adjustment", "-1.06"),
            ("rilono-seed-017", "2026-05-24", "Email & Domain", "Namecheap", "Namecheap domain/email services", "-32.64"),
            ("rilono-seed-018", "2026-06-02", "Cloud Infrastructure", "Render", "Render hosting usage", "-14.30"),
            ("rilono-seed-019", "2026-06-08", "Security", "CyberSecurity", "Cybersecurity tools and review", "-62.00"),
            ("rilono-seed-020", "2026-06-13", "Cloud Infrastructure", "Render", "Render hosting usage", "-16.23"),
        ]

        for seed_key, occurred_on, category, vendor, description, amount_usd in seed_entries:
            existing = conn.execute(
                text("SELECT id FROM company_finance_entries WHERE seed_key = :seed_key"),
                {"seed_key": seed_key},
            ).fetchone()
            if existing:
                continue

            conn.execute(
                text("""
                    INSERT INTO company_finance_entries
                        (seed_key, entry_type, category, vendor, description, amount_usd, occurred_on, source)
                    VALUES
                        (:seed_key, 'expense', :category, :vendor, :description, :amount_usd, :occurred_on, 'seed')
                """),
                {
                    "seed_key": seed_key,
                    "category": category,
                    "vendor": vendor,
                    "description": description,
                    "amount_usd": amount_usd,
                    "occurred_on": occurred_on,
                },
            )
