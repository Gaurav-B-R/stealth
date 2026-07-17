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


def ensure_subscription_payments_user_id_nullable():
    """Allow subscription_payments.user_id to be NULL so payment (financial) records can be
    RETAINED and de-identified on account deletion instead of hard-deleted.

    Postgres-only ALTER (idempotent); new SQLite DBs already get this from the model via
    create_all, and existing dev SQLite DBs are throwaway so no rebuild is attempted.
    """
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        try:
            conn.execute(text("ALTER TABLE subscription_payments ALTER COLUMN user_id DROP NOT NULL"))
        except Exception:
            # Already nullable, or the table doesn't exist yet — safe to ignore.
            pass


def ensure_e2e_encryption_columns():
    """
    Add client-side end-to-end encryption (E2E v2) columns to users + documents.

    Idempotent ADD COLUMN migration for environments without full migrations. The new
    columns hold only opaque, client-wrapped key material (see app/routers/e2e.py); the
    server can never unwrap them.
    """
    is_sqlite = engine.dialect.name == "sqlite"
    bool_false = "0" if is_sqlite else "FALSE"
    ts = "TIMESTAMP"
    with engine.begin() as conn:
        user_columns = _get_table_columns(conn, "users")
        if "e2e_enabled" not in user_columns:
            conn.execute(text(f"ALTER TABLE users ADD COLUMN e2e_enabled BOOLEAN NOT NULL DEFAULT {bool_false}"))
        if "e2e_kdf" not in user_columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN e2e_kdf VARCHAR"))
        if "e2e_wrapped_master_key" not in user_columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN e2e_wrapped_master_key TEXT"))
        if "e2e_recovery_wrapped_master_key" not in user_columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN e2e_recovery_wrapped_master_key TEXT"))
        if "e2e_setup_at" not in user_columns:
            conn.execute(text(f"ALTER TABLE users ADD COLUMN e2e_setup_at {ts}"))

        document_columns = _get_table_columns(conn, "documents")
        if "e2e_scheme" not in document_columns:
            conn.execute(text("ALTER TABLE documents ADD COLUMN e2e_scheme VARCHAR"))
        if "e2e_wrapped_dek" not in document_columns:
            conn.execute(text("ALTER TABLE documents ADD COLUMN e2e_wrapped_dek TEXT"))
        if "e2e_extracted_wrapped_dek" not in document_columns:
            conn.execute(text("ALTER TABLE documents ADD COLUMN e2e_extracted_wrapped_dek TEXT"))


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
        if "accepted_terms_privacy_ip" not in columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN accepted_terms_privacy_ip VARCHAR"))
        if "accepted_terms_privacy_user_agent" not in columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN accepted_terms_privacy_user_agent TEXT"))
        if "accepted_terms_privacy_version" not in columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN accepted_terms_privacy_version VARCHAR"))
        if "age_confirmed_at" not in columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN age_confirmed_at TIMESTAMP"))
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

        if "marketing_emails_consent" not in columns:
            conn.execute(
                text("ALTER TABLE users ADD COLUMN marketing_emails_consent BOOLEAN NOT NULL DEFAULT FALSE")
            )
        if "marketing_emails_consent_at" not in columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN marketing_emails_consent_at TIMESTAMP"))

        # Social login (Google/Microsoft/Apple) — which provider created/owns the account.
        if "auth_provider" not in columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN auth_provider VARCHAR"))

        # Server-side logout: tokens issued at/before this instant are rejected.
        if "session_invalidated_at" not in columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN session_invalidated_at TIMESTAMP"))


def ensure_account_deletion_otp_columns():
    """Add the account-deletion OTP columns (secondary confirmation for B2C delete)."""
    with engine.begin() as conn:
        columns = _get_table_columns(conn, "users")
        if "account_deletion_otp" not in columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN account_deletion_otp VARCHAR"))
        if "account_deletion_otp_expires" not in columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN account_deletion_otp_expires TIMESTAMP"))


def ensure_country_change_otp_columns():
    """Add the destination-country change OTP + pending-selection columns (B2C)."""
    with engine.begin() as conn:
        columns = _get_table_columns(conn, "users")
        if "country_change_otp" not in columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN country_change_otp VARCHAR"))
        if "country_change_otp_expires" not in columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN country_change_otp_expires TIMESTAMP"))
        if "country_change_pending_country" not in columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN country_change_pending_country VARCHAR"))
        if "country_change_pending_visa" not in columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN country_change_pending_visa VARCHAR"))


def ensure_university_country_column():
    """Tag the universities registry by country (US default; AU rows are code-seeded)."""
    with engine.begin() as conn:
        if not _table_exists(conn, "us_universities"):
            return
        columns = _get_table_columns(conn, "us_universities")
        if "country_code" not in columns:
            conn.execute(text("ALTER TABLE us_universities ADD COLUMN country_code VARCHAR DEFAULT 'US'"))


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

        # Visa Success Pass (B2C one-time pass) freemium counters.
        if "ds160_autofills_used" not in columns:
            conn.execute(text("ALTER TABLE subscriptions ADD COLUMN ds160_autofills_used INTEGER NOT NULL DEFAULT 0"))
        if "red_flag_scans_used" not in columns:
            conn.execute(text("ALTER TABLE subscriptions ADD COLUMN red_flag_scans_used INTEGER NOT NULL DEFAULT 0"))
        if "pass_voice_interviews_used" not in columns:
            conn.execute(text("ALTER TABLE subscriptions ADD COLUMN pass_voice_interviews_used INTEGER NOT NULL DEFAULT 0"))
        if "university_recommendations_used" not in columns:
            conn.execute(text("ALTER TABLE subscriptions ADD COLUMN university_recommendations_used INTEGER NOT NULL DEFAULT 0"))


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


def ensure_coupon_account_columns():
    """
    Per-account coupons (admin console): restrict a code to one user + track creation time.
    """
    with engine.begin() as conn:
        columns = _get_table_columns(conn, "coupon_codes")
        if "coupon_code" not in columns:
            return

        if "restricted_to_user_id" not in columns:
            conn.execute(text("ALTER TABLE coupon_codes ADD COLUMN restricted_to_user_id INTEGER"))
        if "created_at" not in columns:
            conn.execute(text("ALTER TABLE coupon_codes ADD COLUMN created_at TIMESTAMP"))


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


def ensure_visa_outcome_columns():
    """Patch users with visa-DECISION outcome-capture columns (approved/refused loop). Additive/idempotent."""
    with engine.begin() as conn:
        columns = _get_table_columns(conn, "users")
        if "visa_decision" not in columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN visa_decision VARCHAR"))
        if "visa_decision_at" not in columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN visa_decision_at TIMESTAMP"))
        if "visa_decision_source" not in columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN visa_decision_source VARCHAR"))
        if "visa_decision_prompt_snoozed_until" not in columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN visa_decision_prompt_snoozed_until TIMESTAMP"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_users_visa_decision ON users(visa_decision)"))


def ensure_user_acquisition_columns():
    """Patch users with first-touch acquisition (traffic-source) columns. Additive/idempotent."""
    with engine.begin() as conn:
        columns = _get_table_columns(conn, "users")
        for col in (
            "acquisition_channel",
            "acquisition_source",
            "acquisition_medium",
            "acquisition_campaign",
            "acquisition_referrer",
            "acquisition_landing_page",
        ):
            if col not in columns:
                conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} VARCHAR"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_users_acquisition_channel ON users(acquisition_channel)"))
        # Self-reported "How did you hear about us?" (asked once post-signup).
        if "heard_about_us" not in columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN heard_about_us VARCHAR"))
        if "heard_about_us_detail" not in columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN heard_about_us_detail VARCHAR"))
        if "heard_about_us_at" not in columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN heard_about_us_at TIMESTAMP"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_users_heard_about_us ON users(heard_about_us)"))


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
        # Data Processing Agreement acceptance (proof-of-consent for the org as controller).
        if "dpa_accepted_at" not in columns:
            conn.execute(text("ALTER TABLE enterprise_organizations ADD COLUMN dpa_accepted_at TIMESTAMP"))
        if "dpa_accepted_version" not in columns:
            conn.execute(text("ALTER TABLE enterprise_organizations ADD COLUMN dpa_accepted_version VARCHAR"))
        if "dpa_accepted_by_user_id" not in columns:
            conn.execute(text("ALTER TABLE enterprise_organizations ADD COLUMN dpa_accepted_by_user_id INTEGER"))
        # Company location (records) + portal display-currency driver.
        if "country_code" not in columns:
            conn.execute(text("ALTER TABLE enterprise_organizations ADD COLUMN country_code VARCHAR"))
        if "state_region" not in columns:
            conn.execute(text("ALTER TABLE enterprise_organizations ADD COLUMN state_region VARCHAR"))

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


def ensure_f1_visa_news_country_column():
    """Add per-destination tagging to f1_visa_news so each user sees their own country's news."""
    with engine.begin() as conn:
        if not _table_exists(conn, "f1_visa_news"):
            return
        columns = _get_table_columns(conn, "f1_visa_news")
        if "destination_country_code" not in columns:
            conn.execute(text(
                "ALTER TABLE f1_visa_news ADD COLUMN destination_country_code VARCHAR"
            ))
            # Existing rows were all US F-1 news — tag them so they stay scoped to US.
            conn.execute(text(
                "UPDATE f1_visa_news SET destination_country_code = 'US' WHERE destination_country_code IS NULL"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_f1_visa_news_destination "
                "ON f1_visa_news (destination_country_code)"
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


def ensure_enterprise_crm_tables():
    """
    Create the enterprise CRM tables (clients, notes, client emails, org
    subscriptions & payments) for environments without full migrations.

    Idempotent and additive — safe to run on every startup. On first creation
    of enterprise_clients, any existing enterprise_students rows are copied over
    so no data is lost when upgrading from the legacy students model.
    """
    is_sqlite = engine.dialect.name == "sqlite"
    ts = "TIMESTAMP" if is_sqlite else "TIMESTAMPTZ"
    now_default = "CURRENT_TIMESTAMP" if is_sqlite else "NOW()"
    pk = "INTEGER PRIMARY KEY AUTOINCREMENT" if is_sqlite else "SERIAL PRIMARY KEY"

    with engine.begin() as conn:
        # --- enterprise_clients ------------------------------------------------
        clients_existed = _table_exists(conn, "enterprise_clients")
        if not clients_existed:
            conn.execute(text(f"""
                CREATE TABLE enterprise_clients (
                    id {pk},
                    organization_id INTEGER NOT NULL,
                    full_name VARCHAR NOT NULL,
                    email VARCHAR,
                    phone VARCHAR,
                    nationality VARCHAR,
                    date_of_birth DATE,
                    passport_number VARCHAR,
                    passport_expiry DATE,
                    visa_category VARCHAR NOT NULL DEFAULT 'student',
                    destination_country_code VARCHAR NOT NULL,
                    destination_country_name VARCHAR NOT NULL,
                    visa_type VARCHAR NOT NULL,
                    intake VARCHAR,
                    application_reference VARCHAR,
                    status VARCHAR NOT NULL DEFAULT 'new_lead',
                    held_from_status VARCHAR,
                    priority VARCHAR NOT NULL DEFAULT 'normal',
                    target_date DATE,
                    assigned_to_user_id INTEGER,
                    created_by_user_id INTEGER NOT NULL,
                    created_at {ts} DEFAULT {now_default} NOT NULL,
                    updated_at {ts}
                )
            """))
            for stmt in (
                "CREATE INDEX IF NOT EXISTS ix_enterprise_clients_organization_id ON enterprise_clients(organization_id)",
                "CREATE INDEX IF NOT EXISTS ix_enterprise_clients_status ON enterprise_clients(status)",
                "CREATE INDEX IF NOT EXISTS ix_enterprise_clients_email ON enterprise_clients(email)",
                "CREATE INDEX IF NOT EXISTS ix_enterprise_clients_assigned_to_user_id ON enterprise_clients(assigned_to_user_id)",
                "CREATE INDEX IF NOT EXISTS ix_ent_clients_org_status ON enterprise_clients(organization_id, status)",
                "CREATE INDEX IF NOT EXISTS ix_ent_clients_org_created ON enterprise_clients(organization_id, created_at)",
            ):
                conn.execute(text(stmt))

            # One-time migration of legacy students into the richer clients table.
            if _table_exists(conn, "enterprise_students"):
                conn.execute(text("""
                    INSERT INTO enterprise_clients
                        (organization_id, full_name, visa_category, destination_country_code,
                         destination_country_name, visa_type, intake, status, priority,
                         created_by_user_id, created_at)
                    SELECT organization_id, student_name, 'student', study_country_code,
                           study_country_name, visa_type, intake, 'new_lead', 'normal',
                           created_by_user_id, created_at
                    FROM enterprise_students
                """))

        # Additive: end-client consent proof columns (safe for new & existing tables).
        client_cols = _get_table_columns(conn, "enterprise_clients")
        if "client_consent_confirmed_at" not in client_cols:
            conn.execute(text("ALTER TABLE enterprise_clients ADD COLUMN client_consent_confirmed_at TIMESTAMP"))
        if "client_consent_confirmed_by_user_id" not in client_cols:
            conn.execute(text("ALTER TABLE enterprise_clients ADD COLUMN client_consent_confirmed_by_user_id INTEGER"))
        # Additive: remembers the stage a case was held FROM (for one-click Resume).
        if "held_from_status" not in client_cols:
            conn.execute(text("ALTER TABLE enterprise_clients ADD COLUMN held_from_status VARCHAR"))

        # --- enterprise_client_notes ------------------------------------------
        if not _table_exists(conn, "enterprise_client_notes"):
            conn.execute(text(f"""
                CREATE TABLE enterprise_client_notes (
                    id {pk},
                    organization_id INTEGER NOT NULL,
                    client_id INTEGER NOT NULL,
                    author_user_id INTEGER,
                    author_name VARCHAR,
                    body TEXT NOT NULL,
                    created_at {ts} DEFAULT {now_default} NOT NULL
                )
            """))
            for stmt in (
                "CREATE INDEX IF NOT EXISTS ix_enterprise_client_notes_organization_id ON enterprise_client_notes(organization_id)",
                "CREATE INDEX IF NOT EXISTS ix_enterprise_client_notes_client_id ON enterprise_client_notes(client_id)",
                "CREATE INDEX IF NOT EXISTS ix_enterprise_client_notes_created_at ON enterprise_client_notes(created_at)",
            ):
                conn.execute(text(stmt))

        # --- enterprise_client_emails -----------------------------------------
        if not _table_exists(conn, "enterprise_client_emails"):
            conn.execute(text(f"""
                CREATE TABLE enterprise_client_emails (
                    id {pk},
                    organization_id INTEGER NOT NULL,
                    client_id INTEGER,
                    sent_by_user_id INTEGER,
                    sent_by_name VARCHAR,
                    to_email VARCHAR NOT NULL,
                    subject VARCHAR NOT NULL,
                    body TEXT NOT NULL,
                    status VARCHAR NOT NULL DEFAULT 'sent',
                    provider_message_id VARCHAR,
                    error_message TEXT,
                    created_at {ts} DEFAULT {now_default} NOT NULL
                )
            """))
            for stmt in (
                "CREATE INDEX IF NOT EXISTS ix_enterprise_client_emails_organization_id ON enterprise_client_emails(organization_id)",
                "CREATE INDEX IF NOT EXISTS ix_enterprise_client_emails_client_id ON enterprise_client_emails(client_id)",
                "CREATE INDEX IF NOT EXISTS ix_enterprise_client_emails_created_at ON enterprise_client_emails(created_at)",
            ):
                conn.execute(text(stmt))

        # --- enterprise_client_documents --------------------------------------
        if not _table_exists(conn, "enterprise_client_documents"):
            conn.execute(text(f"""
                CREATE TABLE enterprise_client_documents (
                    id {pk},
                    organization_id INTEGER NOT NULL,
                    client_id INTEGER NOT NULL,
                    document_type VARCHAR NOT NULL DEFAULT 'Other',
                    original_filename VARCHAR NOT NULL,
                    storage_key VARCHAR NOT NULL,
                    file_size INTEGER,
                    mime_type VARCHAR,
                    extracted_text TEXT,
                    deep_scan_facts TEXT,
                    deep_scan_facts_hash VARCHAR,
                    validation_status VARCHAR,
                    validation_message TEXT,
                    extracted_fields TEXT,
                    validated_at {ts},
                    uploaded_by_user_id INTEGER,
                    uploaded_by_name VARCHAR,
                    created_at {ts} DEFAULT {now_default} NOT NULL
                )
            """))
            for stmt in (
                "CREATE INDEX IF NOT EXISTS ix_enterprise_client_documents_organization_id ON enterprise_client_documents(organization_id)",
                "CREATE INDEX IF NOT EXISTS ix_enterprise_client_documents_client_id ON enterprise_client_documents(client_id)",
                "CREATE INDEX IF NOT EXISTS ix_enterprise_client_documents_created_at ON enterprise_client_documents(created_at)",
            ):
                conn.execute(text(stmt))
        else:
            doc_cols = _get_table_columns(conn, "enterprise_client_documents")
            if "extracted_text" not in doc_cols:
                conn.execute(text("ALTER TABLE enterprise_client_documents ADD COLUMN extracted_text TEXT"))
            if "deep_scan_facts" not in doc_cols:
                conn.execute(text("ALTER TABLE enterprise_client_documents ADD COLUMN deep_scan_facts TEXT"))
            if "deep_scan_facts_hash" not in doc_cols:
                conn.execute(text("ALTER TABLE enterprise_client_documents ADD COLUMN deep_scan_facts_hash VARCHAR"))
            if "validation_status" not in doc_cols:
                conn.execute(text("ALTER TABLE enterprise_client_documents ADD COLUMN validation_status VARCHAR"))
            if "validation_message" not in doc_cols:
                conn.execute(text("ALTER TABLE enterprise_client_documents ADD COLUMN validation_message TEXT"))
            if "extracted_fields" not in doc_cols:
                conn.execute(text("ALTER TABLE enterprise_client_documents ADD COLUMN extracted_fields TEXT"))
            if "validated_at" not in doc_cols:
                conn.execute(text("ALTER TABLE enterprise_client_documents ADD COLUMN validated_at TIMESTAMP"))

        # --- enterprise_interview_sessions ------------------------------------
        if not _table_exists(conn, "enterprise_interview_sessions"):
            conn.execute(text(f"""
                CREATE TABLE enterprise_interview_sessions (
                    id {pk},
                    organization_id INTEGER NOT NULL,
                    client_id INTEGER NOT NULL,
                    conducted_by_user_id INTEGER,
                    conducted_by_name VARCHAR,
                    mode VARCHAR NOT NULL DEFAULT 'chat',
                    transcript TEXT,
                    feedback TEXT,
                    verdict VARCHAR,
                    created_at {ts} DEFAULT {now_default} NOT NULL
                )
            """))
            for stmt in (
                "CREATE INDEX IF NOT EXISTS ix_enterprise_interview_sessions_organization_id ON enterprise_interview_sessions(organization_id)",
                "CREATE INDEX IF NOT EXISTS ix_enterprise_interview_sessions_client_id ON enterprise_interview_sessions(client_id)",
                "CREATE INDEX IF NOT EXISTS ix_enterprise_interview_sessions_created_at ON enterprise_interview_sessions(created_at)",
            ):
                conn.execute(text(stmt))

        # --- enterprise_interview_invites -------------------------------------
        if not _table_exists(conn, "enterprise_interview_invites"):
            conn.execute(text(f"""
                CREATE TABLE enterprise_interview_invites (
                    id {pk},
                    organization_id INTEGER NOT NULL,
                    client_id INTEGER NOT NULL,
                    token_hash VARCHAR NOT NULL,
                    email VARCHAR NOT NULL,
                    allowed_count INTEGER NOT NULL DEFAULT 1,
                    used_count INTEGER NOT NULL DEFAULT 0,
                    code_hash VARCHAR,
                    code_expires_at {ts},
                    code_attempts INTEGER NOT NULL DEFAULT 0,
                    expires_at {ts},
                    revoked BOOLEAN NOT NULL DEFAULT {'0' if is_sqlite else 'FALSE'},
                    created_by_user_id INTEGER,
                    created_by_name VARCHAR,
                    created_at {ts} DEFAULT {now_default} NOT NULL,
                    updated_at {ts}
                )
            """))
            for stmt in (
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_enterprise_interview_invites_token ON enterprise_interview_invites(token_hash)",
                "CREATE INDEX IF NOT EXISTS ix_enterprise_interview_invites_client_id ON enterprise_interview_invites(client_id)",
                "CREATE INDEX IF NOT EXISTS ix_enterprise_interview_invites_organization_id ON enterprise_interview_invites(organization_id)",
            ):
                conn.execute(text(stmt))

        # --- enterprise_subscriptions -----------------------------------------
        if not _table_exists(conn, "enterprise_subscriptions"):
            conn.execute(text(f"""
                CREATE TABLE enterprise_subscriptions (
                    id {pk},
                    organization_id INTEGER NOT NULL,
                    plan VARCHAR NOT NULL DEFAULT 'trial',
                    status VARCHAR NOT NULL DEFAULT 'trialing',
                    trial_ends_at {ts},
                    current_period_end {ts},
                    razorpay_subscription_id VARCHAR,
                    created_at {ts} DEFAULT {now_default} NOT NULL,
                    updated_at {ts}
                )
            """))
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_enterprise_subscriptions_org "
                "ON enterprise_subscriptions(organization_id)"
            ))

        # --- enterprise_subscription_payments ---------------------------------
        if not _table_exists(conn, "enterprise_subscription_payments"):
            conn.execute(text(f"""
                CREATE TABLE enterprise_subscription_payments (
                    id {pk},
                    organization_id INTEGER NOT NULL,
                    created_by_user_id INTEGER,
                    provider VARCHAR NOT NULL DEFAULT 'razorpay',
                    plan VARCHAR NOT NULL DEFAULT 'starter',
                    billing_cycle VARCHAR NOT NULL DEFAULT 'monthly',
                    amount_paise INTEGER NOT NULL,
                    currency VARCHAR NOT NULL DEFAULT 'INR',
                    razorpay_order_id VARCHAR NOT NULL,
                    razorpay_payment_id VARCHAR,
                    razorpay_subscription_id VARCHAR,
                    status VARCHAR NOT NULL DEFAULT 'created',
                    verified_at {ts},
                    error_message TEXT,
                    created_at {ts} DEFAULT {now_default} NOT NULL,
                    updated_at {ts}
                )
            """))
            for stmt in (
                "CREATE INDEX IF NOT EXISTS ix_enterprise_subscription_payments_org ON enterprise_subscription_payments(organization_id)",
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_enterprise_subscription_payments_order ON enterprise_subscription_payments(razorpay_order_id)",
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_enterprise_subscription_payments_payment ON enterprise_subscription_payments(razorpay_payment_id)",
            ):
                conn.execute(text(stmt))


def ensure_enterprise_interview_invite_columns():
    """Add interview completion-tracking columns for older DBs (in-place, idempotent)."""
    is_sqlite = engine.dialect.name == "sqlite"
    ts = "TIMESTAMP" if is_sqlite else "TIMESTAMPTZ"
    with engine.begin() as conn:
        if not _table_exists(conn, "enterprise_interview_invites"):
            return
        columns = _get_table_columns(conn, "enterprise_interview_invites")
        if "completed_count" not in columns:
            conn.execute(text(
                "ALTER TABLE enterprise_interview_invites ADD COLUMN completed_count INTEGER NOT NULL DEFAULT 0"
            ))
        if "last_completed_at" not in columns:
            conn.execute(text(
                f"ALTER TABLE enterprise_interview_invites ADD COLUMN last_completed_at {ts}"
            ))


def ensure_enterprise_demo_requests_table():
    """Create the enterprise_demo_requests table (public 'book a demo' leads)."""
    is_sqlite = engine.dialect.name == "sqlite"
    ts = "TIMESTAMP" if is_sqlite else "TIMESTAMPTZ"
    now_default = "CURRENT_TIMESTAMP" if is_sqlite else "NOW()"
    pk = "INTEGER PRIMARY KEY AUTOINCREMENT" if is_sqlite else "SERIAL PRIMARY KEY"
    with engine.begin() as conn:
        if _table_exists(conn, "enterprise_demo_requests"):
            return
        conn.execute(text(f"""
            CREATE TABLE enterprise_demo_requests (
                id {pk},
                full_name VARCHAR NOT NULL,
                work_email VARCHAR NOT NULL,
                company VARCHAR,
                phone VARCHAR,
                team_size VARCHAR,
                students_count VARCHAR,
                message TEXT,
                source VARCHAR,
                ip_address VARCHAR,
                status VARCHAR NOT NULL DEFAULT 'new',
                created_at {ts} DEFAULT {now_default} NOT NULL
            )
        """))
        for stmt in (
            "CREATE INDEX IF NOT EXISTS ix_enterprise_demo_requests_work_email ON enterprise_demo_requests(work_email)",
            "CREATE INDEX IF NOT EXISTS ix_enterprise_demo_requests_status ON enterprise_demo_requests(status)",
            "CREATE INDEX IF NOT EXISTS ix_enterprise_demo_requests_created_at ON enterprise_demo_requests(created_at)",
        ):
            conn.execute(text(stmt))


def ensure_enterprise_signup_otps_table():
    """Create the enterprise_signup_otps table (signup email-verification codes)."""
    is_sqlite = engine.dialect.name == "sqlite"
    ts = "TIMESTAMP" if is_sqlite else "TIMESTAMPTZ"
    now_default = "CURRENT_TIMESTAMP" if is_sqlite else "NOW()"
    pk = "INTEGER PRIMARY KEY AUTOINCREMENT" if is_sqlite else "SERIAL PRIMARY KEY"
    with engine.begin() as conn:
        if _table_exists(conn, "enterprise_signup_otps"):
            return
        conn.execute(text(f"""
            CREATE TABLE enterprise_signup_otps (
                id {pk},
                email VARCHAR NOT NULL,
                code_hash VARCHAR NOT NULL,
                expires_at {ts} NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                created_at {ts} DEFAULT {now_default} NOT NULL
            )
        """))
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_enterprise_signup_otps_email ON enterprise_signup_otps(email)"
        ))


def ensure_enterprise_support_requests_table():
    """Create the enterprise_support_requests table (help & feature requests)."""
    is_sqlite = engine.dialect.name == "sqlite"
    ts = "TIMESTAMP" if is_sqlite else "TIMESTAMPTZ"
    now_default = "CURRENT_TIMESTAMP" if is_sqlite else "NOW()"
    pk = "INTEGER PRIMARY KEY AUTOINCREMENT" if is_sqlite else "SERIAL PRIMARY KEY"
    with engine.begin() as conn:
        if _table_exists(conn, "enterprise_support_requests"):
            return
        conn.execute(text(f"""
            CREATE TABLE enterprise_support_requests (
                id {pk},
                organization_id INTEGER NOT NULL,
                user_id INTEGER,
                requester_name VARCHAR,
                requester_email VARCHAR,
                request_type VARCHAR NOT NULL DEFAULT 'support',
                subject VARCHAR NOT NULL,
                message TEXT NOT NULL,
                status VARCHAR NOT NULL DEFAULT 'open',
                created_at {ts} DEFAULT {now_default} NOT NULL,
                updated_at {ts}
            )
        """))
        for stmt in (
            "CREATE INDEX IF NOT EXISTS ix_enterprise_support_requests_organization_id ON enterprise_support_requests(organization_id)",
            "CREATE INDEX IF NOT EXISTS ix_enterprise_support_requests_request_type ON enterprise_support_requests(request_type)",
            "CREATE INDEX IF NOT EXISTS ix_enterprise_support_requests_created_at ON enterprise_support_requests(created_at)",
            "CREATE INDEX IF NOT EXISTS ix_ent_support_org_created ON enterprise_support_requests(organization_id, created_at)",
        ):
            conn.execute(text(stmt))


def ensure_enterprise_document_request_tables():
    """Create the secure client document-request tables (the email-upload feature).

    A request is a tokenized, OTP-verified capability sent to a client's email so
    they can upload the specific document types staff asked for. Idempotent and
    additive — safe to run on every startup."""
    is_sqlite = engine.dialect.name == "sqlite"
    ts = "TIMESTAMP" if is_sqlite else "TIMESTAMPTZ"
    now_default = "CURRENT_TIMESTAMP" if is_sqlite else "NOW()"
    pk = "INTEGER PRIMARY KEY AUTOINCREMENT" if is_sqlite else "SERIAL PRIMARY KEY"
    bool_false = "0" if is_sqlite else "FALSE"
    with engine.begin() as conn:
        if not _table_exists(conn, "enterprise_document_requests"):
            conn.execute(text(f"""
                CREATE TABLE enterprise_document_requests (
                    id {pk},
                    organization_id INTEGER NOT NULL,
                    client_id INTEGER NOT NULL,
                    token_hash VARCHAR NOT NULL,
                    email VARCHAR NOT NULL,
                    message TEXT,
                    status VARCHAR NOT NULL DEFAULT 'pending',
                    code_hash VARCHAR,
                    code_expires_at {ts},
                    code_attempts INTEGER NOT NULL DEFAULT 0,
                    expires_at {ts},
                    revoked BOOLEAN NOT NULL DEFAULT {bool_false},
                    completed_at {ts},
                    created_by_user_id INTEGER,
                    created_by_name VARCHAR,
                    created_at {ts} DEFAULT {now_default} NOT NULL,
                    updated_at {ts}
                )
            """))
            for stmt in (
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_enterprise_document_requests_token ON enterprise_document_requests(token_hash)",
                "CREATE INDEX IF NOT EXISTS ix_enterprise_document_requests_organization_id ON enterprise_document_requests(organization_id)",
                "CREATE INDEX IF NOT EXISTS ix_enterprise_document_requests_client_id ON enterprise_document_requests(client_id)",
                "CREATE INDEX IF NOT EXISTS ix_ent_docreq_client_created ON enterprise_document_requests(client_id, created_at)",
            ):
                conn.execute(text(stmt))

        if not _table_exists(conn, "enterprise_document_request_items"):
            conn.execute(text(f"""
                CREATE TABLE enterprise_document_request_items (
                    id {pk},
                    request_id INTEGER NOT NULL,
                    organization_id INTEGER NOT NULL,
                    document_type VARCHAR NOT NULL DEFAULT 'Other',
                    status VARCHAR NOT NULL DEFAULT 'pending',
                    document_id INTEGER,
                    received_at {ts},
                    created_at {ts} DEFAULT {now_default} NOT NULL
                )
            """))
            for stmt in (
                "CREATE INDEX IF NOT EXISTS ix_enterprise_document_request_items_request_id ON enterprise_document_request_items(request_id)",
                "CREATE INDEX IF NOT EXISTS ix_enterprise_document_request_items_organization_id ON enterprise_document_request_items(organization_id)",
            ):
                conn.execute(text(stmt))


def ensure_enterprise_refunds_table():
    """Create the enterprise_refunds audit table and the refunded-amount tracker on
    credit payments. Idempotent and additive — safe to run on every startup."""
    is_sqlite = engine.dialect.name == "sqlite"
    ts = "TIMESTAMP" if is_sqlite else "TIMESTAMPTZ"
    now_default = "CURRENT_TIMESTAMP" if is_sqlite else "NOW()"
    pk = "INTEGER PRIMARY KEY AUTOINCREMENT" if is_sqlite else "SERIAL PRIMARY KEY"
    with engine.begin() as conn:
        if _table_exists(conn, "enterprise_credit_payments"):
            cols = _get_table_columns(conn, "enterprise_credit_payments")
            if "refunded_amount_paise" not in cols:
                conn.execute(text(
                    "ALTER TABLE enterprise_credit_payments "
                    "ADD COLUMN refunded_amount_paise INTEGER NOT NULL DEFAULT 0"
                ))

        if not _table_exists(conn, "enterprise_refunds"):
            conn.execute(text(f"""
                CREATE TABLE enterprise_refunds (
                    id {pk},
                    organization_id INTEGER NOT NULL,
                    payment_id INTEGER,
                    kind VARCHAR NOT NULL DEFAULT 'credits',
                    amount_paise INTEGER NOT NULL DEFAULT 0,
                    currency VARCHAR NOT NULL DEFAULT 'INR',
                    credits_delta INTEGER NOT NULL DEFAULT 0,
                    provider VARCHAR,
                    razorpay_payment_id VARCHAR,
                    razorpay_refund_id VARCHAR,
                    status VARCHAR NOT NULL DEFAULT 'completed',
                    reason TEXT,
                    created_by_user_id INTEGER,
                    created_by_name VARCHAR,
                    created_at {ts} DEFAULT {now_default} NOT NULL
                )
            """))
            for stmt in (
                "CREATE INDEX IF NOT EXISTS ix_enterprise_refunds_organization_id ON enterprise_refunds(organization_id)",
                "CREATE INDEX IF NOT EXISTS ix_enterprise_refunds_payment_id ON enterprise_refunds(payment_id)",
                "CREATE INDEX IF NOT EXISTS ix_enterprise_refunds_created_at ON enterprise_refunds(created_at)",
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_enterprise_refunds_razorpay_refund ON enterprise_refunds(razorpay_refund_id)",
            ):
                conn.execute(text(stmt))


def ensure_enterprise_payments_tables():
    """Create the marketplace-payments tables (Razorpay Route): linked accounts,
    student payment requests, the webhook reconciliation ledger, and the refund audit.

    Idempotent and additive — safe on every startup. Tables are created in dependency
    order (linked_accounts -> student_payments -> events/refunds). Money is integer paise.
    Requires enterprise_clients to exist (run after ensure_enterprise_crm_tables)."""
    is_sqlite = engine.dialect.name == "sqlite"
    ts = "TIMESTAMP" if is_sqlite else "TIMESTAMPTZ"
    now_default = "CURRENT_TIMESTAMP" if is_sqlite else "NOW()"
    pk = "INTEGER PRIMARY KEY AUTOINCREMENT" if is_sqlite else "SERIAL PRIMARY KEY"
    bfalse = "0" if is_sqlite else "FALSE"
    with engine.begin() as conn:
        if not _table_exists(conn, "enterprise_linked_accounts"):
            conn.execute(text(f"""
                CREATE TABLE enterprise_linked_accounts (
                    id {pk},
                    organization_id INTEGER NOT NULL,
                    razorpay_account_id VARCHAR,
                    razorpay_product_id VARCHAR,
                    razorpay_stakeholder_id VARCHAR,
                    legal_business_name VARCHAR,
                    business_type VARCHAR,
                    contact_name VARCHAR,
                    contact_email VARCHAR,
                    contact_phone VARCHAR,
                    business_pan VARCHAR,
                    gst_number VARCHAR,
                    bank_account_last4 VARCHAR,
                    bank_ifsc VARCHAR,
                    beneficiary_name VARCHAR,
                    activation_status VARCHAR NOT NULL DEFAULT 'not_started',
                    requirements_json TEXT,
                    is_payable BOOLEAN NOT NULL DEFAULT {bfalse},
                    attested_service_delivery BOOLEAN NOT NULL DEFAULT {bfalse},
                    attested_turnover_ok BOOLEAN NOT NULL DEFAULT {bfalse},
                    attested_at {ts},
                    attested_ip VARCHAR,
                    attested_version VARCHAR,
                    created_by_user_id INTEGER,
                    created_at {ts} DEFAULT {now_default} NOT NULL,
                    updated_at {ts}
                )
            """))
            for stmt in (
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_ent_linked_acct_org ON enterprise_linked_accounts(organization_id)",
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_ent_linked_acct_rzp ON enterprise_linked_accounts(razorpay_account_id)",
                "CREATE INDEX IF NOT EXISTS ix_ent_linked_acct_status ON enterprise_linked_accounts(activation_status)",
            ):
                conn.execute(text(stmt))
        else:
            # Additive: attestation wording version (proof survives copy changes).
            la_cols = _get_table_columns(conn, "enterprise_linked_accounts")
            if "attested_version" not in la_cols:
                conn.execute(text("ALTER TABLE enterprise_linked_accounts ADD COLUMN attested_version VARCHAR"))

        if not _table_exists(conn, "enterprise_student_payments"):
            conn.execute(text(f"""
                CREATE TABLE enterprise_student_payments (
                    id {pk},
                    organization_id INTEGER NOT NULL,
                    client_id INTEGER,
                    client_name_snapshot VARCHAR,
                    linked_account_id INTEGER,
                    invoice_number VARCHAR,
                    description VARCHAR,
                    amount_paise INTEGER NOT NULL,
                    commission_paise INTEGER NOT NULL DEFAULT 0,
                    payout_paise INTEGER NOT NULL DEFAULT 0,
                    currency VARCHAR NOT NULL DEFAULT 'INR',
                    provider VARCHAR NOT NULL DEFAULT 'razorpay',
                    razorpay_order_id VARCHAR,
                    razorpay_payment_id VARCHAR,
                    razorpay_transfer_id VARCHAR,
                    status VARCHAR NOT NULL DEFAULT 'created',
                    settlement_status VARCHAR,
                    on_hold BOOLEAN NOT NULL DEFAULT {bfalse},
                    on_hold_until {ts},
                    utr VARCHAR,
                    refunded_amount_paise INTEGER NOT NULL DEFAULT 0,
                    due_date DATE,
                    created_by_user_id INTEGER,
                    paid_at {ts},
                    settled_at {ts},
                    created_at {ts} DEFAULT {now_default} NOT NULL,
                    updated_at {ts},
                    pay_token_hash VARCHAR,
                    payer_email_snapshot VARCHAR,
                    email_sent_at {ts},
                    cancelled_at {ts},
                    dispute_status VARCHAR,
                    disputed_at {ts}
                )
            """))
            for stmt in (
                "CREATE INDEX IF NOT EXISTS ix_ent_student_pay_org ON enterprise_student_payments(organization_id)",
                "CREATE INDEX IF NOT EXISTS ix_ent_student_pay_client ON enterprise_student_payments(client_id)",
                "CREATE INDEX IF NOT EXISTS ix_ent_student_pay_org_created ON enterprise_student_payments(organization_id, created_at)",
                "CREATE INDEX IF NOT EXISTS ix_ent_student_pay_org_status ON enterprise_student_payments(organization_id, status)",
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_ent_student_pay_order ON enterprise_student_payments(razorpay_order_id)",
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_ent_student_pay_payment ON enterprise_student_payments(razorpay_payment_id)",
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_ent_student_pay_transfer ON enterprise_student_payments(razorpay_transfer_id)",
            ):
                conn.execute(text(stmt))
        else:
            # Phase 2 (emailed secure pay-link) — additive columns for DBs created by Phase 0.
            cols = _get_table_columns(conn, "enterprise_student_payments")
            for col, ddl in (
                ("pay_token_hash", "VARCHAR"),
                ("payer_email_snapshot", "VARCHAR"),
                ("email_sent_at", ts),
                ("cancelled_at", ts),
                ("dispute_status", "VARCHAR"),
                ("disputed_at", ts),
            ):
                if col not in cols:
                    conn.execute(text(f"ALTER TABLE enterprise_student_payments ADD COLUMN {col} {ddl}"))
        # Self-healing on both paths (fresh create and augmented).
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_ent_student_pay_token ON enterprise_student_payments(pay_token_hash)"
        ))

        if not _table_exists(conn, "enterprise_payment_events"):
            conn.execute(text(f"""
                CREATE TABLE enterprise_payment_events (
                    id {pk},
                    organization_id INTEGER,
                    student_payment_id INTEGER,
                    razorpay_event_id VARCHAR,
                    event_type VARCHAR,
                    entity_type VARCHAR,
                    entity_id VARCHAR,
                    amount_paise INTEGER,
                    payload_json TEXT,
                    processed_at {ts},
                    created_at {ts} DEFAULT {now_default} NOT NULL
                )
            """))
            for stmt in (
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_ent_pay_evt_event_id ON enterprise_payment_events(razorpay_event_id)",
                "CREATE INDEX IF NOT EXISTS ix_ent_pay_evt_org ON enterprise_payment_events(organization_id)",
                "CREATE INDEX IF NOT EXISTS ix_ent_pay_evt_entity ON enterprise_payment_events(entity_id)",
                "CREATE INDEX IF NOT EXISTS ix_ent_pay_evt_org_created ON enterprise_payment_events(organization_id, created_at)",
            ):
                conn.execute(text(stmt))

        if not _table_exists(conn, "enterprise_payment_refunds"):
            conn.execute(text(f"""
                CREATE TABLE enterprise_payment_refunds (
                    id {pk},
                    organization_id INTEGER NOT NULL,
                    student_payment_id INTEGER,
                    kind VARCHAR NOT NULL DEFAULT 'money',
                    amount_paise INTEGER NOT NULL DEFAULT 0,
                    currency VARCHAR NOT NULL DEFAULT 'INR',
                    provider VARCHAR NOT NULL DEFAULT 'razorpay',
                    razorpay_refund_id VARCHAR,
                    razorpay_reversal_id VARCHAR,
                    reverse_all BOOLEAN NOT NULL DEFAULT {bfalse},
                    status VARCHAR NOT NULL DEFAULT 'created',
                    reason TEXT,
                    created_by_user_id INTEGER,
                    created_by_name VARCHAR,
                    created_at {ts} DEFAULT {now_default} NOT NULL
                )
            """))
            for stmt in (
                "CREATE INDEX IF NOT EXISTS ix_ent_pay_refund_org ON enterprise_payment_refunds(organization_id)",
                "CREATE INDEX IF NOT EXISTS ix_ent_pay_refund_payment ON enterprise_payment_refunds(student_payment_id)",
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_ent_pay_refund_rzp ON enterprise_payment_refunds(razorpay_refund_id)",
            ):
                conn.execute(text(stmt))

        # Chargeback/dispute audit ledger (payment.dispute.* webhooks).
        if not _table_exists(conn, "enterprise_payment_disputes"):
            conn.execute(text(f"""
                CREATE TABLE enterprise_payment_disputes (
                    id {pk},
                    organization_id INTEGER,
                    student_payment_id INTEGER,
                    razorpay_dispute_id VARCHAR,
                    razorpay_payment_id VARCHAR,
                    amount_paise INTEGER NOT NULL DEFAULT 0,
                    currency VARCHAR NOT NULL DEFAULT 'INR',
                    phase VARCHAR,
                    status VARCHAR NOT NULL DEFAULT 'open',
                    reason_code VARCHAR,
                    respond_by {ts},
                    resolved_at {ts},
                    created_at {ts} DEFAULT {now_default} NOT NULL,
                    updated_at {ts}
                )
            """))
            for stmt in (
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_ent_pay_dispute_rzp ON enterprise_payment_disputes(razorpay_dispute_id)",
                "CREATE INDEX IF NOT EXISTS ix_ent_pay_dispute_org ON enterprise_payment_disputes(organization_id)",
                "CREATE INDEX IF NOT EXISTS ix_ent_pay_dispute_payment ON enterprise_payment_disputes(student_payment_id)",
            ):
                conn.execute(text(stmt))


def ensure_enterprise_calendar_reminder_runs_table():
    """Create the run-log table that makes the daily calendar-reminder email job idempotent."""
    is_sqlite = engine.dialect.name == "sqlite"
    ts = "TIMESTAMP" if is_sqlite else "TIMESTAMPTZ"
    now_default = "CURRENT_TIMESTAMP" if is_sqlite else "NOW()"
    pk = "INTEGER PRIMARY KEY AUTOINCREMENT" if is_sqlite else "SERIAL PRIMARY KEY"
    with engine.begin() as conn:
        if _table_exists(conn, "enterprise_calendar_reminder_runs"):
            return
        conn.execute(text(f"""
            CREATE TABLE enterprise_calendar_reminder_runs (
                id {pk},
                run_date DATE NOT NULL,
                status VARCHAR NOT NULL DEFAULT 'running',
                started_at {ts} DEFAULT {now_default} NOT NULL,
                completed_at {ts},
                recipients_emailed INTEGER NOT NULL DEFAULT 0,
                events_considered INTEGER NOT NULL DEFAULT 0,
                error_message TEXT
            )
        """))
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_enterprise_calendar_reminder_runs_date "
            "ON enterprise_calendar_reminder_runs(run_date)"
        ))


def ensure_enterprise_calendar_table():
    """Create the enterprise_calendar_events table (staff reminders/tasks/deadlines)."""
    is_sqlite = engine.dialect.name == "sqlite"
    ts = "TIMESTAMP" if is_sqlite else "TIMESTAMPTZ"
    now_default = "CURRENT_TIMESTAMP" if is_sqlite else "NOW()"
    pk = "INTEGER PRIMARY KEY AUTOINCREMENT" if is_sqlite else "SERIAL PRIMARY KEY"
    bool_false = "0" if is_sqlite else "FALSE"
    with engine.begin() as conn:
        if not _table_exists(conn, "enterprise_calendar_events"):
            conn.execute(text(f"""
                CREATE TABLE enterprise_calendar_events (
                    id {pk},
                    organization_id INTEGER NOT NULL,
                    client_id INTEGER,
                    title VARCHAR NOT NULL,
                    notes TEXT,
                    event_type VARCHAR NOT NULL DEFAULT 'reminder',
                    event_date DATE NOT NULL,
                    event_time VARCHAR,
                    is_done BOOLEAN NOT NULL DEFAULT {bool_false},
                    notify_client BOOLEAN NOT NULL DEFAULT {bool_false},
                    client_notified_at {ts},
                    created_by_user_id INTEGER,
                    created_by_name VARCHAR,
                    created_at {ts} DEFAULT {now_default} NOT NULL,
                    updated_at {ts}
                )
            """))
            for stmt in (
                "CREATE INDEX IF NOT EXISTS ix_enterprise_calendar_events_organization_id ON enterprise_calendar_events(organization_id)",
                "CREATE INDEX IF NOT EXISTS ix_enterprise_calendar_events_client_id ON enterprise_calendar_events(client_id)",
                "CREATE INDEX IF NOT EXISTS ix_enterprise_calendar_events_event_date ON enterprise_calendar_events(event_date)",
                "CREATE INDEX IF NOT EXISTS ix_enterprise_calendar_events_is_done ON enterprise_calendar_events(is_done)",
                "CREATE INDEX IF NOT EXISTS ix_ent_calendar_org_date ON enterprise_calendar_events(organization_id, event_date)",
            ):
                conn.execute(text(stmt))

        # Additive columns for existing deployments (client @-mention notification).
        cols = _get_table_columns(conn, "enterprise_calendar_events")
        if "notify_client" not in cols:
            conn.execute(text(f"ALTER TABLE enterprise_calendar_events ADD COLUMN notify_client BOOLEAN NOT NULL DEFAULT {bool_false}"))
        if "client_notified_at" not in cols:
            conn.execute(text(f"ALTER TABLE enterprise_calendar_events ADD COLUMN client_notified_at {ts}"))


def ensure_enterprise_credit_tables():
    """
    Create the prepaid-credit ('Rilono Credits') tables that power the enterprise
    revenue model: per-org wallets, the credit ledger, and Razorpay credit/infra
    payments. Idempotent and additive — safe to run on every startup.
    """
    is_sqlite = engine.dialect.name == "sqlite"
    ts = "TIMESTAMP" if is_sqlite else "TIMESTAMPTZ"
    now_default = "CURRENT_TIMESTAMP" if is_sqlite else "NOW()"
    pk = "INTEGER PRIMARY KEY AUTOINCREMENT" if is_sqlite else "SERIAL PRIMARY KEY"

    with engine.begin() as conn:
        # --- enterprise_credit_wallets ----------------------------------------
        if not _table_exists(conn, "enterprise_credit_wallets"):
            conn.execute(text(f"""
                CREATE TABLE enterprise_credit_wallets (
                    id {pk},
                    organization_id INTEGER NOT NULL,
                    balance_credits INTEGER NOT NULL DEFAULT 0,
                    lifetime_purchased_credits INTEGER NOT NULL DEFAULT 0,
                    lifetime_spent_credits INTEGER NOT NULL DEFAULT 0,
                    infra_fee_paid_until {ts},
                    copilot_usage_date VARCHAR,
                    copilot_msgs_today INTEGER NOT NULL DEFAULT 0,
                    copilot_unbilled_msgs INTEGER NOT NULL DEFAULT 0,
                    interview_staff_previews_used INTEGER NOT NULL DEFAULT 0,
                    created_at {ts} DEFAULT {now_default} NOT NULL,
                    updated_at {ts}
                )
            """))
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_enterprise_credit_wallets_org "
                "ON enterprise_credit_wallets(organization_id)"
            ))
        else:
            # Existing wallets: add the copilot-metering + staff-preview columns idempotently.
            wallet_cols = _get_table_columns(conn, "enterprise_credit_wallets")
            if "copilot_usage_date" not in wallet_cols:
                conn.execute(text("ALTER TABLE enterprise_credit_wallets ADD COLUMN copilot_usage_date VARCHAR"))
            if "copilot_msgs_today" not in wallet_cols:
                conn.execute(text("ALTER TABLE enterprise_credit_wallets ADD COLUMN copilot_msgs_today INTEGER NOT NULL DEFAULT 0"))
            if "copilot_unbilled_msgs" not in wallet_cols:
                conn.execute(text("ALTER TABLE enterprise_credit_wallets ADD COLUMN copilot_unbilled_msgs INTEGER NOT NULL DEFAULT 0"))
            if "interview_staff_previews_used" not in wallet_cols:
                conn.execute(text("ALTER TABLE enterprise_credit_wallets ADD COLUMN interview_staff_previews_used INTEGER NOT NULL DEFAULT 0"))

        # --- enterprise_credit_transactions -----------------------------------
        if not _table_exists(conn, "enterprise_credit_transactions"):
            conn.execute(text(f"""
                CREATE TABLE enterprise_credit_transactions (
                    id {pk},
                    organization_id INTEGER NOT NULL,
                    type VARCHAR NOT NULL,
                    action_key VARCHAR,
                    credits INTEGER NOT NULL,
                    balance_after INTEGER NOT NULL DEFAULT 0,
                    description VARCHAR,
                    reference_type VARCHAR,
                    reference_id INTEGER,
                    created_by_user_id INTEGER,
                    created_by_name VARCHAR,
                    created_at {ts} DEFAULT {now_default} NOT NULL
                )
            """))
            for stmt in (
                "CREATE INDEX IF NOT EXISTS ix_enterprise_credit_transactions_organization_id ON enterprise_credit_transactions(organization_id)",
                "CREATE INDEX IF NOT EXISTS ix_enterprise_credit_transactions_type ON enterprise_credit_transactions(type)",
                "CREATE INDEX IF NOT EXISTS ix_enterprise_credit_transactions_action_key ON enterprise_credit_transactions(action_key)",
                "CREATE INDEX IF NOT EXISTS ix_enterprise_credit_transactions_created_at ON enterprise_credit_transactions(created_at)",
                "CREATE INDEX IF NOT EXISTS ix_ent_credit_txn_org_created ON enterprise_credit_transactions(organization_id, created_at)",
            ):
                conn.execute(text(stmt))

        # --- enterprise_credit_payments ---------------------------------------
        if not _table_exists(conn, "enterprise_credit_payments"):
            conn.execute(text(f"""
                CREATE TABLE enterprise_credit_payments (
                    id {pk},
                    organization_id INTEGER NOT NULL,
                    created_by_user_id INTEGER,
                    provider VARCHAR NOT NULL DEFAULT 'razorpay',
                    kind VARCHAR NOT NULL DEFAULT 'credits',
                    package_key VARCHAR,
                    credits INTEGER NOT NULL DEFAULT 0,
                    bonus_credits INTEGER NOT NULL DEFAULT 0,
                    amount_paise INTEGER NOT NULL,
                    currency VARCHAR NOT NULL DEFAULT 'INR',
                    razorpay_order_id VARCHAR NOT NULL,
                    razorpay_payment_id VARCHAR,
                    status VARCHAR NOT NULL DEFAULT 'created',
                    verified_at {ts},
                    error_message TEXT,
                    created_at {ts} DEFAULT {now_default} NOT NULL,
                    updated_at {ts}
                )
            """))
            for stmt in (
                "CREATE INDEX IF NOT EXISTS ix_enterprise_credit_payments_org ON enterprise_credit_payments(organization_id)",
                "CREATE INDEX IF NOT EXISTS ix_enterprise_credit_payments_kind ON enterprise_credit_payments(kind)",
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_enterprise_credit_payments_order ON enterprise_credit_payments(razorpay_order_id)",
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_enterprise_credit_payments_payment ON enterprise_credit_payments(razorpay_payment_id)",
            ):
                conn.execute(text(stmt))


def ensure_enterprise_payment_coupon_columns():
    """
    Add per-account discount columns to the enterprise payment tables so a
    coupon applied at checkout is recorded alongside the charge. Idempotent.
    """
    with engine.begin() as conn:
        for table in ("enterprise_credit_payments", "enterprise_subscription_payments"):
            if not _table_exists(conn, table):
                continue
            columns = _get_table_columns(conn, table)
            if "coupon_code" not in columns:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN coupon_code VARCHAR"))
            if "coupon_percent_off" not in columns:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN coupon_percent_off NUMERIC(5,2)"))
            if "original_amount_paise" not in columns:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN original_amount_paise INTEGER"))


def ensure_enterprise_coupons_table():
    """
    Create the enterprise_coupons table that powers admin-managed, per-account
    discount codes redeemed at enterprise checkout. Idempotent and additive —
    safe to run on every startup.
    """
    is_sqlite = engine.dialect.name == "sqlite"
    ts = "TIMESTAMP" if is_sqlite else "TIMESTAMPTZ"
    now_default = "CURRENT_TIMESTAMP" if is_sqlite else "NOW()"
    pk = "INTEGER PRIMARY KEY AUTOINCREMENT" if is_sqlite else "SERIAL PRIMARY KEY"
    bool_true = "1" if is_sqlite else "TRUE"

    with engine.begin() as conn:
        if not _table_exists(conn, "enterprise_coupons"):
            conn.execute(text(f"""
                CREATE TABLE enterprise_coupons (
                    id {pk},
                    organization_id INTEGER NOT NULL,
                    code VARCHAR NOT NULL,
                    percent_off NUMERIC(5,2) NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT {bool_true},
                    applies_to VARCHAR NOT NULL DEFAULT 'all',
                    max_redemptions INTEGER,
                    note VARCHAR,
                    created_by_user_id INTEGER,
                    created_at {ts} DEFAULT {now_default} NOT NULL,
                    updated_at {ts}
                )
            """))
            for stmt in (
                "CREATE INDEX IF NOT EXISTS ix_enterprise_coupons_organization_id ON enterprise_coupons(organization_id)",
                "CREATE INDEX IF NOT EXISTS ix_enterprise_coupons_code ON enterprise_coupons(code)",
                "CREATE INDEX IF NOT EXISTS ix_enterprise_coupons_created_by_user_id ON enterprise_coupons(created_by_user_id)",
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_enterprise_coupon_org_code ON enterprise_coupons(organization_id, code)",
            ):
                conn.execute(text(stmt))


def ensure_student_journey_country_columns():
    """
    Multi-country B2C journey: add destination/visa fields to users and scope the
    document_type_catalog by (country, visa type). Backfills run **once** (inside the
    column-add branch) so existing users land on US/F-1 with onboarding marked
    complete, while brand-new users keep NULL onboarding and must complete the wizard.
    """
    is_sqlite = engine.dialect.name == "sqlite"
    now_default = "CURRENT_TIMESTAMP" if is_sqlite else "NOW()"
    with engine.begin() as conn:
        # --- users -----------------------------------------------------------
        ucols = _get_table_columns(conn, "users")
        if "destination_country_code" not in ucols:
            conn.execute(text("ALTER TABLE users ADD COLUMN destination_country_code VARCHAR"))
            conn.execute(text(
                "UPDATE users SET destination_country_code='US' WHERE destination_country_code IS NULL"
            ))
        if "visa_type_key" not in ucols:
            conn.execute(text("ALTER TABLE users ADD COLUMN visa_type_key VARCHAR"))
            conn.execute(text(
                "UPDATE users SET visa_type_key='us_f1' WHERE visa_type_key IS NULL"
            ))
        if "university_email" not in ucols:
            conn.execute(text("ALTER TABLE users ADD COLUMN university_email VARCHAR"))
        if "onboarding_completed_at" not in ucols:
            conn.execute(text("ALTER TABLE users ADD COLUMN onboarding_completed_at TIMESTAMP"))
            # Existing users predate onboarding -> mark complete so they aren't gated.
            conn.execute(text(
                f"UPDATE users SET onboarding_completed_at={now_default} "
                "WHERE onboarding_completed_at IS NULL"
            ))

        # --- document_type_catalog scoping -----------------------------------
        if _table_exists(conn, "document_type_catalog"):
            dcols = _get_table_columns(conn, "document_type_catalog")
            added_scope = False
            if "country_code" not in dcols:
                conn.execute(text(
                    "ALTER TABLE document_type_catalog ADD COLUMN country_code VARCHAR NOT NULL DEFAULT 'US'"
                ))
                added_scope = True
            if "visa_type_key" not in dcols:
                conn.execute(text(
                    "ALTER TABLE document_type_catalog ADD COLUMN visa_type_key VARCHAR NOT NULL DEFAULT 'us_f1'"
                ))
                added_scope = True
            # Replace the legacy single-column unique on document_type with the
            # composite (country, visa, document_type) scope. Postgres-only DDL; fresh
            # sqlite test DBs already get the composite via create_all.
            if added_scope and not is_sqlite:
                conn.execute(text("DROP INDEX IF EXISTS ix_document_type_catalog_document_type"))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS ix_document_type_catalog_document_type "
                    "ON document_type_catalog(document_type)"
                ))
                conn.execute(text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_doc_catalog_scope "
                    "ON document_type_catalog(country_code, visa_type_key, document_type)"
                ))


def ensure_university_shortlist_table():
    """Create the university_shortlist_entries table (B2C university shortlisting)."""
    is_sqlite = engine.dialect.name == "sqlite"
    ts = "TIMESTAMP" if is_sqlite else "TIMESTAMPTZ"
    now_default = "CURRENT_TIMESTAMP" if is_sqlite else "NOW()"
    pk = "INTEGER PRIMARY KEY AUTOINCREMENT" if is_sqlite else "SERIAL PRIMARY KEY"
    with engine.begin() as conn:
        if _table_exists(conn, "university_shortlist_entries"):
            return
        conn.execute(text(f"""
            CREATE TABLE university_shortlist_entries (
                id {pk},
                user_id INTEGER NOT NULL,
                country_code VARCHAR,
                university_name VARCHAR NOT NULL,
                program VARCHAR,
                location VARCHAR,
                status VARCHAR NOT NULL DEFAULT 'considering',
                source VARCHAR NOT NULL DEFAULT 'manual',
                est_tuition VARCHAR,
                rationale TEXT,
                notes TEXT,
                created_at {ts} DEFAULT {now_default} NOT NULL,
                updated_at {ts}
            )
        """))
        for stmt in (
            "CREATE INDEX IF NOT EXISTS ix_university_shortlist_entries_user_id ON university_shortlist_entries(user_id)",
            "CREATE INDEX IF NOT EXISTS ix_university_shortlist_user_created ON university_shortlist_entries(user_id, created_at)",
        ):
            conn.execute(text(stmt))


def ensure_enterprise_notifications_table():
    """In-portal notification bell for enterprise staff (one row per recipient)."""
    is_sqlite = engine.dialect.name == "sqlite"
    ts = "TIMESTAMP" if is_sqlite else "TIMESTAMPTZ"
    now_default = "CURRENT_TIMESTAMP" if is_sqlite else "NOW()"
    pk = "INTEGER PRIMARY KEY AUTOINCREMENT" if is_sqlite else "SERIAL PRIMARY KEY"
    bool_type = "BOOLEAN" if not is_sqlite else "BOOLEAN"
    with engine.begin() as conn:
        if not _table_exists(conn, "enterprise_notifications"):
            conn.execute(text(f"""
                CREATE TABLE enterprise_notifications (
                    id {pk},
                    organization_id INTEGER NOT NULL,
                    recipient_user_id INTEGER NOT NULL,
                    actor_user_id INTEGER,
                    type VARCHAR NOT NULL,
                    title VARCHAR NOT NULL,
                    body TEXT,
                    reference_type VARCHAR,
                    reference_id INTEGER,
                    is_read {bool_type} NOT NULL DEFAULT FALSE,
                    created_at {ts} DEFAULT {now_default} NOT NULL
                )
            """))
        for stmt in (
            "CREATE INDEX IF NOT EXISTS ix_enterprise_notifications_organization_id ON enterprise_notifications(organization_id)",
            "CREATE INDEX IF NOT EXISTS ix_enterprise_notifications_recipient_user_id ON enterprise_notifications(recipient_user_id)",
            "CREATE INDEX IF NOT EXISTS ix_ent_notif_recipient_read ON enterprise_notifications(recipient_user_id, is_read)",
            "CREATE INDEX IF NOT EXISTS ix_ent_notif_org_created ON enterprise_notifications(organization_id, created_at)",
        ):
            conn.execute(text(stmt))


def ensure_sop_feature_schema():
    """Application Kit — SOP/Motivation-letter generator: drafts table + freemium counter."""
    is_sqlite = engine.dialect.name == "sqlite"
    ts = "TIMESTAMP" if is_sqlite else "TIMESTAMPTZ"
    now_default = "CURRENT_TIMESTAMP" if is_sqlite else "NOW()"
    pk = "INTEGER PRIMARY KEY AUTOINCREMENT" if is_sqlite else "SERIAL PRIMARY KEY"
    with engine.begin() as conn:
        sub_columns = _get_table_columns(conn, "subscriptions")
        if "sop_generations_used" not in sub_columns:
            conn.execute(text("ALTER TABLE subscriptions ADD COLUMN sop_generations_used INTEGER NOT NULL DEFAULT 0"))

        if not _table_exists(conn, "sop_drafts"):
            conn.execute(text(f"""
                CREATE TABLE sop_drafts (
                    id {pk},
                    user_id INTEGER NOT NULL,
                    root_id INTEGER,
                    version INTEGER NOT NULL DEFAULT 1,
                    country_code VARCHAR,
                    visa_type_key VARCHAR,
                    university VARCHAR NOT NULL,
                    program VARCHAR NOT NULL,
                    study_level VARCHAR,
                    intake VARCHAR,
                    highlights TEXT,
                    instruction TEXT,
                    content_md TEXT NOT NULL,
                    word_count INTEGER NOT NULL DEFAULT 0,
                    model_used VARCHAR,
                    created_at {ts} DEFAULT {now_default} NOT NULL
                )
            """))
        for stmt in (
            "CREATE INDEX IF NOT EXISTS ix_sop_drafts_user_id ON sop_drafts(user_id)",
            "CREATE INDEX IF NOT EXISTS ix_sop_drafts_root_id ON sop_drafts(root_id)",
            "CREATE INDEX IF NOT EXISTS ix_sop_drafts_user_root_version ON sop_drafts(user_id, root_id, version)",
        ):
            conn.execute(text(stmt))


def ensure_ai_optimization_events_table():
    """Ensure the ai_optimization_events table exists (Part 3 cost-optimization metrics)."""
    is_sqlite = engine.dialect.name == "sqlite"
    ts = "TIMESTAMP" if is_sqlite else "TIMESTAMPTZ"
    now_default = "CURRENT_TIMESTAMP" if is_sqlite else "NOW()"
    pk = "INTEGER PRIMARY KEY AUTOINCREMENT" if is_sqlite else "SERIAL PRIMARY KEY"
    with engine.begin() as conn:
        if _table_exists(conn, "ai_optimization_events"):
            return
        conn.execute(text(f"""
            CREATE TABLE ai_optimization_events (
                id {pk},
                kind VARCHAR NOT NULL,
                source VARCHAR NOT NULL,
                tokens_saved INTEGER NOT NULL DEFAULT 0,
                cost_saved_usd NUMERIC(12,6) NOT NULL DEFAULT 0,
                detail VARCHAR,
                created_at {ts} DEFAULT {now_default} NOT NULL
            )
        """))
        for stmt in (
            "CREATE INDEX IF NOT EXISTS ix_ai_optimization_events_kind ON ai_optimization_events(kind)",
            "CREATE INDEX IF NOT EXISTS ix_ai_optimization_events_source ON ai_optimization_events(source)",
            "CREATE INDEX IF NOT EXISTS ix_ai_optimization_events_created_at ON ai_optimization_events(created_at)",
        ):
            conn.execute(text(stmt))


def ensure_gemini_usage_table():
    """Ensure the gemini_usage_events table exists for the admin AI-cost tracker, and
    that it carries per-account attribution columns (user_id, organization_id)."""
    with engine.begin() as conn:
        if _table_exists(conn, "gemini_usage_events"):
            # Backfill per-account attribution columns on existing installs.
            cols = _get_table_columns(conn, "gemini_usage_events")
            if "user_id" not in cols:
                conn.execute(text("ALTER TABLE gemini_usage_events ADD COLUMN user_id INTEGER"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_gemini_usage_events_user_id ON gemini_usage_events(user_id)"))
            if "organization_id" not in cols:
                conn.execute(text("ALTER TABLE gemini_usage_events ADD COLUMN organization_id INTEGER"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_gemini_usage_events_organization_id ON gemini_usage_events(organization_id)"))
            if "cached_tokens" not in cols:
                conn.execute(text("ALTER TABLE gemini_usage_events ADD COLUMN cached_tokens INTEGER NOT NULL DEFAULT 0"))
            return
        if engine.dialect.name == "sqlite":
            conn.execute(text("""
                CREATE TABLE gemini_usage_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source VARCHAR NOT NULL,
                    model VARCHAR NOT NULL,
                    user_id INTEGER,
                    organization_id INTEGER,
                    prompt_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0,
                    cached_tokens INTEGER NOT NULL DEFAULT 0,
                    estimated_cost_usd NUMERIC(12,6) NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
                )
            """))
        else:
            conn.execute(text("""
                CREATE TABLE gemini_usage_events (
                    id SERIAL PRIMARY KEY,
                    source VARCHAR NOT NULL,
                    model VARCHAR NOT NULL,
                    user_id INTEGER,
                    organization_id INTEGER,
                    prompt_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0,
                    cached_tokens INTEGER NOT NULL DEFAULT 0,
                    estimated_cost_usd NUMERIC(12,6) NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
                )
            """))
        for stmt in (
            "CREATE INDEX IF NOT EXISTS ix_gemini_usage_events_source ON gemini_usage_events(source)",
            "CREATE INDEX IF NOT EXISTS ix_gemini_usage_events_model ON gemini_usage_events(model)",
            "CREATE INDEX IF NOT EXISTS ix_gemini_usage_events_user_id ON gemini_usage_events(user_id)",
            "CREATE INDEX IF NOT EXISTS ix_gemini_usage_events_organization_id ON gemini_usage_events(organization_id)",
            "CREATE INDEX IF NOT EXISTS ix_gemini_usage_events_created_at ON gemini_usage_events(created_at)",
        ):
            conn.execute(text(stmt))


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
                        paid_by VARCHAR NOT NULL DEFAULT 'Gaurav',
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
                        paid_by VARCHAR NOT NULL DEFAULT 'Gaurav',
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
        if "paid_by" not in columns:
            conn.execute(text("ALTER TABLE company_finance_entries ADD COLUMN paid_by VARCHAR NOT NULL DEFAULT 'Gaurav'"))
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
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_company_finance_entries_paid_by "
            "ON company_finance_entries(paid_by)"
        ))

        # One-time bootstrap/reconcile guard. The DATABASE is the source of truth for finance
        # entries (the admin console reads AND now edits them). We populate the baseline dataset
        # and apply the founder split EXACTLY ONCE per database, then never touch these rows on a
        # later deploy — so edits made in the console persist and are never clobbered. A brand-new/
        # empty DB is bootstrapped once; an already-populated prod DB gets the split applied once.
        # Only bump SEED_MARKER if a deliberate future one-time data change is intended.
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS app_data_migrations ("
            "migration_key VARCHAR PRIMARY KEY, "
            "applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL)"
        ))
        SEED_MARKER = "company_finance_seed_v2_founder_split"
        if conn.execute(
            text("SELECT 1 FROM app_data_migrations WHERE migration_key = :k"),
            {"k": SEED_MARKER},
        ).fetchone():
            return  # Already seeded/reconciled — the DB is authoritative; never overwrite edits.

        # Founder-investment attribution. Each seeded expense that Gaurav originally paid is
        # split into a Gaurav share + a Kushal share, sized so that exactly $267.00 of the
        # $295.02 Gaurav-seeded spend is re-attributed to Kushal (proportionally, ~90.5% of
        # each line). Per-line halves sum back to the original amount, so every vendor total
        # and the grand total invested are unchanged — only the paid_by split shifts.
        # Resulting seeded split: Kushal $329.00, Gaurav $28.02.
        seed_entries = [
            ("rilono-seed-001", "2026-02-17", "AI Coding Tools", "Cursor", "Cursor editor subscription (Gaurav share)", "-2.05", "Gaurav"),
            ("rilono-seed-001-k", "2026-02-17", "AI Coding Tools", "Cursor", "Cursor editor subscription (Kushal share)", "-19.52", "Kushal"),
            ("rilono-seed-002", "2026-02-22", "AI Model Tools", "Claude", "Claude workspace subscription (Gaurav share)", "-2.02", "Gaurav"),
            ("rilono-seed-002-k", "2026-02-22", "AI Model Tools", "Claude", "Claude workspace subscription (Kushal share)", "-19.23", "Kushal"),
            ("rilono-seed-003", "2026-02-28", "AI Coding Tools", "Cursor", "Cursor editor subscription (Gaurav share)", "-2.02", "Gaurav"),
            ("rilono-seed-003-k", "2026-02-28", "AI Coding Tools", "Cursor", "Cursor editor subscription (Kushal share)", "-19.23", "Kushal"),
            ("rilono-seed-004", "2026-03-04", "AI Coding Tools", "Cursor", "Cursor usage and tooling (Gaurav share)", "-3.00", "Gaurav"),
            ("rilono-seed-004-k", "2026-03-04", "AI Coding Tools", "Cursor", "Cursor usage and tooling (Kushal share)", "-28.56", "Kushal"),
            ("rilono-seed-005", "2026-03-09", "Cloud Infrastructure", "Render", "Render hosting usage (Gaurav share)", "-0.41", "Gaurav"),
            ("rilono-seed-005-k", "2026-03-09", "Cloud Infrastructure", "Render", "Render hosting usage (Kushal share)", "-3.92", "Kushal"),
            ("rilono-seed-006", "2026-03-15", "AI Platform", "OpenAI", "OpenAI API and product usage (Gaurav share)", "-2.53", "Gaurav"),
            ("rilono-seed-006-k", "2026-03-15", "AI Platform", "OpenAI", "OpenAI API and product usage (Kushal share)", "-24.10", "Kushal"),
            ("rilono-seed-007", "2026-03-19", "Email & Domain", "Name Cheap Email", "Namecheap email service (Gaurav share)", "-0.27", "Gaurav"),
            ("rilono-seed-007-k", "2026-03-19", "Email & Domain", "Name Cheap Email", "Namecheap email service (Kushal share)", "-2.54", "Kushal"),
            ("rilono-seed-008", "2026-03-24", "Product Distribution", "Chrome Extension", "Chrome extension registration (Gaurav share)", "-0.47", "Gaurav"),
            ("rilono-seed-008-k", "2026-03-24", "Product Distribution", "Chrome Extension", "Chrome extension registration (Kushal share)", "-4.53", "Kushal"),
            ("rilono-seed-009", "2026-03-30", "Cloud Infrastructure", "Render Pro", "Render Pro plan (Gaurav share)", "-0.66", "Gaurav"),
            ("rilono-seed-009-k", "2026-03-30", "Cloud Infrastructure", "Render Pro", "Render Pro plan (Kushal share)", "-6.34", "Kushal"),
            ("rilono-seed-010", "2026-04-04", "Email & Domain", "Domain", "Domain purchase/renewal (Gaurav share)", "-1.04", "Gaurav"),
            ("rilono-seed-010-k", "2026-04-04", "Email & Domain", "Domain", "Domain purchase/renewal (Kushal share)", "-9.96", "Kushal"),
            ("rilono-seed-011", "2026-04-10", "Cloud Infrastructure", "Render", "Render hosting usage (Gaurav share)", "-1.08", "Gaurav"),
            ("rilono-seed-011-k", "2026-04-10", "Cloud Infrastructure", "Render", "Render hosting usage (Kushal share)", "-10.31", "Kushal"),
            ("rilono-seed-012", "2026-04-17", "Cloud Infrastructure", "Render", "Render hosting usage (Gaurav share)", "-0.99", "Gaurav"),
            ("rilono-seed-012-k", "2026-04-17", "Cloud Infrastructure", "Render", "Render hosting usage (Kushal share)", "-9.40", "Kushal"),
            ("rilono-seed-013", "2026-04-25", "AI Model Tools", "Claude", "Claude workspace subscription (Gaurav share)", "-2.02", "Gaurav"),
            ("rilono-seed-013-k", "2026-04-25", "AI Model Tools", "Claude", "Claude workspace subscription (Kushal share)", "-19.23", "Kushal"),
            ("rilono-seed-014", "2026-05-02", "AI Coding Tools", "Cursor", "Cursor editor subscription (Gaurav share)", "-2.02", "Gaurav"),
            ("rilono-seed-014-k", "2026-05-02", "AI Coding Tools", "Cursor", "Cursor editor subscription (Kushal share)", "-19.23", "Kushal"),
            ("rilono-seed-015", "2026-05-10", "Cloud Infrastructure", "Render", "Render hosting usage (Gaurav share)", "-1.34", "Gaurav"),
            ("rilono-seed-015-k", "2026-05-10", "Cloud Infrastructure", "Render", "Render hosting usage (Kushal share)", "-12.77", "Kushal"),
            ("rilono-seed-016", "2026-05-18", "AI Coding Tools", "Cursor", "Cursor usage adjustment (Gaurav share)", "-0.10", "Gaurav"),
            ("rilono-seed-016-k", "2026-05-18", "AI Coding Tools", "Cursor", "Cursor usage adjustment (Kushal share)", "-0.96", "Kushal"),
            ("rilono-seed-017", "2026-05-24", "Email & Domain", "Namecheap", "Namecheap domain/email services (Gaurav share)", "-3.10", "Gaurav"),
            ("rilono-seed-017-k", "2026-05-24", "Email & Domain", "Namecheap", "Namecheap domain/email services (Kushal share)", "-29.54", "Kushal"),
            ("rilono-seed-018", "2026-06-02", "Cloud Infrastructure", "Render", "Render hosting usage (Gaurav share)", "-1.36", "Gaurav"),
            ("rilono-seed-018-k", "2026-06-02", "Cloud Infrastructure", "Render", "Render hosting usage (Kushal share)", "-12.94", "Kushal"),
            ("rilono-seed-019", "2026-06-08", "Security", "CyberSecurity", "Cybersecurity tools and review", "-62.00", "Kushal"),
            ("rilono-seed-020", "2026-06-13", "Cloud Infrastructure", "Render", "Render hosting usage (Gaurav share)", "-1.54", "Gaurav"),
            ("rilono-seed-020-k", "2026-06-13", "Cloud Infrastructure", "Render", "Render hosting usage (Kushal share)", "-14.69", "Kushal"),
        ]

        for seed_key, occurred_on, category, vendor, description, amount_usd, paid_by in seed_entries:
            existing = conn.execute(
                text("SELECT id FROM company_finance_entries WHERE seed_key = :seed_key"),
                {"seed_key": seed_key},
            ).fetchone()
            if existing:
                # Seeds are the authoritative source for these rows, so keep amount/category/
                # vendor/description in sync too (not just paid_by). This lets the founder-split
                # above re-attribute AND resize existing prod rows on deploy without a manual DB
                # write — e.g. reducing a Gaurav line and inserting its paired Kushal share.
                conn.execute(
                    text("""
                        UPDATE company_finance_entries
                        SET paid_by = :paid_by,
                            amount_usd = :amount_usd,
                            category = :category,
                            vendor = :vendor,
                            description = :description
                        WHERE seed_key = :seed_key
                    """),
                    {
                        "seed_key": seed_key,
                        "paid_by": paid_by,
                        "amount_usd": amount_usd,
                        "category": category,
                        "vendor": vendor,
                        "description": description,
                    },
                )
                continue

            conn.execute(
                text("""
                    INSERT INTO company_finance_entries
                        (seed_key, entry_type, category, vendor, description, amount_usd, occurred_on, paid_by, source)
                    VALUES
                        (:seed_key, 'expense', :category, :vendor, :description, :amount_usd, :occurred_on, :paid_by, 'seed')
                """),
                {
                    "seed_key": seed_key,
                    "category": category,
                    "vendor": vendor,
                    "description": description,
                    "amount_usd": amount_usd,
                    "occurred_on": occurred_on,
                    "paid_by": paid_by,
                },
            )

        # Record that this DB has been seeded/reconciled so we never re-run and overwrite edits.
        conn.execute(
            text("INSERT INTO app_data_migrations (migration_key) VALUES (:k)"),
            {"k": SEED_MARKER},
        )
