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


def ensure_optimistic_concurrency_columns():
    """Add the `version` optimistic-concurrency token to the rows two people edit at once.

    Additive and idempotent. Existing rows are backfilled to 1 rather than 0 so a value is
    never falsy — the precondition check treats a missing/zero version as "client didn't
    send one" and a stored 0 would make every legacy row look unversioned.

    NOT NULL with a server default so a row inserted by any path (including raw SQL that
    predates this column) still lands with a usable version.
    """
    with engine.begin() as conn:
        for table in ("enterprise_clients", "enterprise_finance_entries"):
            if not _table_exists(conn, table):
                continue
            if "version" in _get_table_columns(conn, table):
                continue
            conn.execute(text(
                f"ALTER TABLE {table} ADD COLUMN version INTEGER NOT NULL DEFAULT 1"
            ))
            conn.execute(text(
                f"UPDATE {table} SET version = 1 WHERE version IS NULL OR version < 1"
            ))


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


def ensure_users_username_nullable():
    """Allow users.username to be NULL, matching `nullable=True` on the model.

    Every enterprise-origin account is created with username=None on purpose — the owner
    signs in with their email and the column is a legacy B2C artifact. models.py already
    declares it nullable, but create_all() only ever creates new TABLES; it never alters an
    existing COLUMN, so databases predating that change still carry the original NOT NULL and
    reject all four enterprise user-creation paths (workspace signup, invite acceptance,
    admin grant, startup seeding) with a NotNullViolation surfaced to the client as a 500.

    Postgres-only ALTER (idempotent); new SQLite DBs already get this from the model via
    create_all, and existing dev SQLite DBs are throwaway so no rebuild is attempted.

    The UNIQUE index on the column stays intact — Postgres treats NULLs as distinct, so any
    number of enterprise accounts can hold a NULL username without colliding.
    """
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        try:
            conn.execute(text("ALTER TABLE users ALTER COLUMN username DROP NOT NULL"))
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


def ensure_user_enterprise_account_column():
    """Add users.is_enterprise_account — marks accounts whose ORIGIN is the B2B Enterprise
    product (workspace owner via /api/enterprise/signup, or a teammate whose account was created
    BY the org). These accounts are blocked from the individual/B2C consumer app so the two
    products stay disconnected; B2C users who later join a team keep their consumer access.

    Idempotent ADD COLUMN for environments without full migrations. The historical backfill of
    existing rows lives in routers/enterprise.backfill_enterprise_account_flag (run at startup).
    """
    is_sqlite = engine.dialect.name == "sqlite"
    bool_false = "0" if is_sqlite else "FALSE"
    with engine.begin() as conn:
        user_columns = _get_table_columns(conn, "users")
        if "is_enterprise_account" not in user_columns:
            conn.execute(
                text(
                    f"ALTER TABLE users ADD COLUMN is_enterprise_account BOOLEAN NOT NULL DEFAULT {bool_false}"
                )
            )


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


def _is_sqlite(conn) -> bool:
    return conn.dialect.name == "sqlite"


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


# The client intake record — (column, DDL type). "TS" resolves to the dialect's timestamp
# type. Kept as data so the CREATE TABLE and the ALTER path can never disagree.
_ENTERPRISE_CLIENT_INTAKE_COLUMNS: list[tuple[str, str]] = [
    # contact & identity
    ("whatsapp_number", "VARCHAR"),
    ("current_city", "VARCHAR"),
    ("gender", "VARCHAR"),
    ("guardian_name", "VARCHAR"),
    ("guardian_relation", "VARCHAR"),
    ("guardian_phone", "VARCHAR"),
    # study plan & risk
    ("study_level", "VARCHAR"),
    ("field_of_study", "VARCHAR"),
    ("admission_stage", "VARCHAR"),
    ("prior_refusal_history", "VARCHAR"),
    ("prior_refusal_notes", "TEXT"),
    # academic profile & tests
    ("highest_qualification", "VARCHAR"),
    ("qualification_score", "VARCHAR"),
    ("qualification_scale", "VARCHAR"),
    ("year_of_passing", "INTEGER"),
    ("backlogs_count", "INTEGER"),
    ("work_experience_band", "VARCHAR"),
    ("english_test_status", "VARCHAR"),
    ("english_test_type", "VARCHAR"),
    ("english_test_score", "VARCHAR"),
    ("english_test_date", "DATE"),
    ("aptitude_test_type", "VARCHAR"),
    ("aptitude_test_score", "VARCHAR"),
    # funding
    ("budget_band", "VARCHAR"),
    ("funding_source", "VARCHAR"),
    # acquisition & ownership
    ("lead_source", "VARCHAR"),
    ("lead_source_detail", "VARCHAR"),
    ("branch_name", "VARCHAR"),
    ("next_followup_date", "DATE"),
    # purpose-specific consents
    ("marketing_consent_channels", "VARCHAR"),
    ("marketing_consent_at", "TS"),
    ("institution_share_consent_at", "TS"),
]


def _backfill_client_intake_from_stage_data(conn):
    """One-time move of the retired `new_lead` case-record answers into the intake columns.

    Those six questions (enquiry source, prior refusal history, admission stage, funding
    source, English/language test status) were destination-specific stage fields storing
    display labels; they are generic columns now. The original stage_data JSON is left
    untouched, so a label this map doesn't recognise costs nothing.
    """
    import json

    from app.enterprise_client_fields import RETIRED_STAGE_FIELD_BACKFILL

    targets = sorted({
        column
        for spec in RETIRED_STAGE_FIELD_BACKFILL.values()
        for mapping in spec["values"].values()
        for column in mapping
    } | {spec["fallback"] for spec in RETIRED_STAGE_FIELD_BACKFILL.values() if spec["fallback"]})

    rows = conn.execute(text(
        f"SELECT id, stage_data, {', '.join(targets)} FROM enterprise_clients "
        "WHERE stage_data IS NOT NULL AND stage_data <> ''"
    )).mappings().all()

    migrated = 0
    for row in rows:
        try:
            recorded = (json.loads(row["stage_data"]) or {}).get("new_lead") or {}
        except Exception:
            continue
        if not isinstance(recorded, dict):
            continue
        updates: dict[str, str] = {}
        for stage_key, spec in RETIRED_STAGE_FIELD_BACKFILL.items():
            value = str(recorded.get(stage_key) or "").strip()
            if not value:
                continue
            mapped = spec["values"].get(value)
            if mapped is None:
                if spec["fallback"]:
                    mapped = {spec["fallback"]: value}
                else:
                    continue
            for column, new_value in mapped.items():
                # Never overwrite something a counselor has already typed into the column.
                if row[column] is None and column not in updates:
                    updates[column] = new_value
        if not updates:
            continue
        assignments = ", ".join(f"{col} = :{col}" for col in updates)
        conn.execute(
            text(f"UPDATE enterprise_clients SET {assignments} WHERE id = :row_id"),
            {**updates, "row_id": row["id"]},
        )
        migrated += 1
    if migrated:
        print(f"[schema_patch] migrated lead-intake fields for {migrated} client(s)")


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
                    stage_data TEXT,
                    stage_visits TEXT,
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
        # Additive: per-stage, country-aware case record (JSON text).
        if "stage_data" not in client_cols:
            conn.execute(text("ALTER TABLE enterprise_clients ADD COLUMN stage_data TEXT"))
        # Additive: the stages a case has actually occupied, so the journey tracker can show a
        # jumped-over stage as skipped rather than complete. Deliberately NOT backfilled here:
        # an existing case's real history is unknowable, so it is seeded (as "assumed reached")
        # the first time that case's stage is written — see _record_stage_visit.
        if "stage_visits" not in client_cols:
            conn.execute(text("ALTER TABLE enterprise_clients ADD COLUMN stage_visits TEXT"))

        # Additive: the lead-intake record a consultancy keeps on every client — contact,
        # guardian, study plan, academic profile, tests, funding, lead source and the
        # purpose-specific consents. All nullable; nothing here is ever required.
        added_intake_cols = []
        for column, ddl_type in _ENTERPRISE_CLIENT_INTAKE_COLUMNS:
            if column in client_cols:
                continue
            sql_type = ts if ddl_type == "TS" else ddl_type
            conn.execute(text(f"ALTER TABLE enterprise_clients ADD COLUMN {column} {sql_type}"))
            added_intake_cols.append(column)
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_ent_clients_org_followup "
            "ON enterprise_clients(organization_id, next_followup_date)"
        ))
        # Six of these questions used to be per-stage case-record fields. They are columns
        # now, so move anything already recorded across — once, on the deploy that adds them.
        if "lead_source" in added_intake_cols:
            _backfill_client_intake_from_stage_data(conn)

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
                    direction VARCHAR NOT NULL DEFAULT 'outbound',
                    from_email VARCHAR,
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
                    validation_credits_charged INTEGER NOT NULL DEFAULT 0,
                    manually_accepted_at {ts},
                    manually_accepted_by VARCHAR,
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
            if "manually_accepted_at" not in doc_cols:
                conn.execute(text("ALTER TABLE enterprise_client_documents ADD COLUMN manually_accepted_at TIMESTAMP"))
            if "manually_accepted_by" not in doc_cols:
                conn.execute(text("ALTER TABLE enterprise_client_documents ADD COLUMN manually_accepted_by VARCHAR"))
            if "validation_credits_charged" not in doc_cols:
                conn.execute(text(
                    "ALTER TABLE enterprise_client_documents "
                    "ADD COLUMN validation_credits_charged INTEGER NOT NULL DEFAULT 0"
                ))

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
                    -- 'sandbox' since 2026-08-02. Pre-existing rows keep 'trial';
                    -- enterprise_billing.normalize_plan_key maps it, so no backfill runs.
                    plan VARCHAR NOT NULL DEFAULT 'sandbox',
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

        # --- enterprise_subscriptions: recurring-mandate columns -------------
        if _table_exists(conn, "enterprise_subscriptions"):
            sub_cols2 = _get_table_columns(conn, "enterprise_subscriptions")
            for col, ddl in (
                ("cancel_at_period_end", "BOOLEAN NOT NULL DEFAULT 0" if _is_sqlite(conn) else "BOOLEAN NOT NULL DEFAULT FALSE"),
                ("canceled_at", "TIMESTAMP"),
                ("mandate_status", "VARCHAR"),
            ):
                if col not in sub_cols2:
                    conn.execute(text(f"ALTER TABLE enterprise_subscriptions ADD COLUMN {col} {ddl}"))

        # --- enterprise_razorpay_plans (recurring mandate plan cache) --------
        if not _table_exists(conn, "enterprise_razorpay_plans"):
            conn.execute(text(f"""
                CREATE TABLE enterprise_razorpay_plans (
                    id {pk},
                    plan_key VARCHAR NOT NULL,
                    currency VARCHAR NOT NULL DEFAULT 'INR',
                    amount_minor INTEGER NOT NULL,
                    period VARCHAR NOT NULL DEFAULT 'monthly',
                    razorpay_plan_id VARCHAR NOT NULL UNIQUE,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_ent_rzp_plan "
                "ON enterprise_razorpay_plans (plan_key, currency, amount_minor, period)"
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
                    subtotal_paise INTEGER,
                    tax_paise INTEGER NOT NULL DEFAULT 0,
                    tax_percent NUMERIC(5, 2),
                    tax_label VARCHAR,
                    included_credits INTEGER NOT NULL DEFAULT 0,
                    refunded_amount_paise INTEGER NOT NULL DEFAULT 0,
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

        # Additive self-heal for an ALREADY-EXISTING payments table (the tiered-plan
        # rollout of 2026-08-02 added GST + included-credit columns). Historical rows
        # keep tax_paise = 0, which is correct: nothing before that date charged tax.
        if _table_exists(conn, "enterprise_subscription_payments"):
            sub_pay_cols = _get_table_columns(conn, "enterprise_subscription_payments")
            for col, ddl in (
                ("subtotal_paise", "INTEGER"),
                ("tax_paise", "INTEGER NOT NULL DEFAULT 0"),
                ("tax_percent", "NUMERIC(5, 2)"),
                ("tax_label", "VARCHAR"),
                ("included_credits", "INTEGER NOT NULL DEFAULT 0"),
                ("refunded_amount_paise", "INTEGER NOT NULL DEFAULT 0"),
            ):
                if col not in sub_pay_cols:
                    conn.execute(text(f"ALTER TABLE enterprise_subscription_payments ADD COLUMN {col} {ddl}"))

    # --- the stage-vocabulary backfill + invariant (guarded) ---------------
    # try/except sits OUTSIDE the `with`, so the DDL above is already committed and a backfill
    # failure only rolls back the backfill. It must never abort startup: this runs inside
    # main's startup path, where an exception takes the app down.
    try:
        with engine.begin() as conn:
            _backfill_retired_client_stage_keys(conn)
            _backfill_relocated_shortlisting_stage_keys(conn)
            _report_unknown_client_stage_keys(conn)
    except Exception as exc:  # noqa: BLE001 - never block startup on a data backfill
        print(f"[schema_patch] client stage-key backfill skipped: {exc}")


def _backfill_retired_client_stage_keys(conn):
    """One-time rewrite of the stage keys an earlier vocabulary change left in the data.

    `documents_pending` and `documents_collected` were the two halves of document collection
    before it became the single `documents` stage ("Collecting Documents" covers gathering
    AND holding them); no source file has mentioned either string since. Rows still carrying
    them are counted by no stage rollup — the dashboards tally catalog keys only — so a large
    slice of the book reads as missing from the pipeline.

    Deliberately narrow: these two values are the only ones with a decided mapping, and
    nothing may map to `submitted`, which would assert a filing that never happened. Any
    other unrecognised value is reported by _report_unknown_client_stage_keys and left
    exactly as stored — normalize_stage() coerces an unknown key to new_lead on read, and
    rewriting on a guess would make that guess permanent.
    """
    from app import enterprise_catalog as catalog

    retired_stage_keys = {
        "documents_pending": catalog.STAGE_DOCUMENTS,
        "documents_collected": catalog.STAGE_DOCUMENTS,
    }

    conn.execute(text(
        "CREATE TABLE IF NOT EXISTS app_data_migrations ("
        "migration_key VARCHAR PRIMARY KEY, "
        "applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL)"
    ))
    marker = "enterprise_client_retired_stage_keys_v1"
    if conn.execute(
        text("SELECT 1 FROM app_data_migrations WHERE migration_key = :k"),
        {"k": marker},
    ).fetchone():
        return

    rewritten = 0
    # held_from_status is the same vocabulary — a case put On Hold from a retired key resumes
    # into it, so leaving that column behind would reintroduce the orphan on one click.
    for column in ("status", "held_from_status"):
        for old_key, new_key in retired_stage_keys.items():
            result = conn.execute(
                text(f"UPDATE enterprise_clients SET {column} = :new WHERE {column} = :old"),
                {"new": new_key, "old": old_key},
            )
            rewritten += max(result.rowcount, 0)

    conn.execute(
        text("INSERT INTO app_data_migrations (migration_key) VALUES (:k)"),
        {"k": marker},
    )
    if rewritten:
        print(f"[schema_patch] remapped {rewritten} retired client stage value(s)")


# The six per-destination university-choice answers the catalog used to collect at new_lead and
# now declares under shortlisting — US, UK, AU, FR, IE and AE respectively. Spelled out rather
# than diffed against the catalog: the catalog only says where a field lives NOW, so reading the
# set from it would silently change what this one-time migration relocates the next time a field
# moves. Anything else in the new_lead bucket is not this migration's business.
_RELOCATED_SHORTLISTING_STAGE_KEYS = (
    "intended_program_and_university",
    "target_institutions",
    "preferred_providers",
    "target_programmes",
    "intended_institution",
    "licensed_institution_and_programme",
)


def _backfill_relocated_shortlisting_stage_keys(conn):
    """One-time move of those six answers from each client's `new_lead` bucket to `shortlisting`.

    Staff recorded the intended university on the lead record because shortlisting did not exist
    as a stage yet. The case-record form renders only the fields the catalog declares for a
    stage, so after the move the stored answer is invisible, and the portal's stage-record
    resolver drops keys the destination catalog no longer declares — the next save of new_lead
    writes the record back without them and the answer is gone for good.

    A value already recorded under shortlisting always wins; in that case the new_lead copy is
    left exactly where it is rather than dropped, so no reading of the two is ever discarded.
    """
    import json

    conn.execute(text(
        "CREATE TABLE IF NOT EXISTS app_data_migrations ("
        "migration_key VARCHAR PRIMARY KEY, "
        "applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL)"
    ))
    marker = "enterprise_client_shortlisting_stage_keys_v1"
    if conn.execute(
        text("SELECT 1 FROM app_data_migrations WHERE migration_key = :k"),
        {"k": marker},
    ).fetchone():
        return

    rows = conn.execute(text(
        "SELECT id, stage_data FROM enterprise_clients "
        "WHERE stage_data IS NOT NULL AND stage_data <> ''"
    )).mappings().all()

    moved = 0
    for row in rows:
        try:
            data = json.loads(row["stage_data"])
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        recorded = data.get("new_lead")
        shortlisting = data.get("shortlisting") or {}
        if not isinstance(recorded, dict) or not isinstance(shortlisting, dict):
            continue
        relocated = False
        for key in _RELOCATED_SHORTLISTING_STAGE_KEYS:
            value = recorded.get(key)
            if value is None or not str(value).strip():
                continue
            existing = shortlisting.get(key)
            if existing is not None and str(existing).strip():
                continue
            shortlisting[key] = recorded.pop(key)
            relocated = True
        if not relocated:
            continue
        data["shortlisting"] = shortlisting
        conn.execute(
            text("UPDATE enterprise_clients SET stage_data = :payload WHERE id = :row_id"),
            {"payload": json.dumps(data), "row_id": row["id"]},
        )
        moved += 1

    conn.execute(
        text("INSERT INTO app_data_migrations (migration_key) VALUES (:k)"),
        {"k": marker},
    )
    if moved:
        print(f"[schema_patch] moved shortlisting case-record answers on {moved} client(s)")


def _report_unknown_client_stage_keys(conn):
    """Every startup: name any stored client stage value the catalog no longer knows.

    The vocabulary is read from the catalog, never copied here — stage keys get added over
    time and a list in this file would go stale on the next insertion, which is exactly how
    the orphans above survived unnoticed. Reported only, not repaired: a value without a
    decided mapping is a migration someone has to author.
    """
    from app import enterprise_catalog as catalog

    unknown = []
    for column in ("status", "held_from_status"):
        rows = conn.execute(text(
            f"SELECT {column} AS value, COUNT(*) AS total FROM enterprise_clients "
            f"WHERE {column} IS NOT NULL AND {column} <> '' GROUP BY {column}"
        )).mappings().all()
        unknown.extend(
            f"{column}={row['value']!r} ({row['total']} row(s))"
            for row in rows
            if row["value"] not in catalog.CLIENT_STAGE_KEYS
        )
    if unknown:
        print(
            "[schema_patch] WARNING: enterprise_clients holds stage values outside "
            f"enterprise_catalog.CLIENT_STAGE_KEYS — {', '.join(unknown)}"
        )


# The 14 access-control columns added to enterprise_organization_members. "TS" is replaced by
# the dialect's timestamp type. Every NOT NULL entry carries a CONSTANT default (SQLite refuses
# a non-constant one on ADD COLUMN); every timestamp is plain nullable for the same reason.
# data_scope is intentionally nullable WITH NO DEFAULT — NULL means "inherit the role's scope",
# and a DEFAULT 'all' here would silently give every member workspace-wide access.
_ENTERPRISE_MEMBER_ACCESS_COLUMNS: list[tuple[str, str]] = [
    ("role_key", "VARCHAR NOT NULL DEFAULT 'viewer'"),
    ("custom_role_id", "INTEGER"),
    ("data_scope", "VARCHAR"),
    ("capability_grants_json", "TEXT"),
    ("capability_denies_json", "TEXT"),
    ("primary_branch_id", "INTEGER"),
    ("job_title", "VARCHAR"),
    ("phone", "VARCHAR"),
    ("status", "VARCHAR NOT NULL DEFAULT 'active'"),
    ("deactivated_at", "TS"),
    ("deactivated_by_user_id", "INTEGER"),
    ("invited_at", "TS"),
    ("invite_accepted_at", "TS"),
    ("last_active_at", "TS"),
]


def ensure_enterprise_access_control_tables():
    """Create the enterprise access-control schema — offices, custom roles, the member↔office
    link and the access audit log — and add the per-member access columns plus
    enterprise_clients.branch_id. Idempotent and additive; safe on every startup.

    Deliberately THREE separate transactions. On Postgres, an error caught inside a single
    `engine.begin()` turns the COMMIT into a silent ROLLBACK, so a hiccup in the data backfill
    would discard every CREATE/ALTER without raising — and the app would then 500 on every
    enterprise request, because the models map columns the database no longer has. The DDL
    therefore commits on its own and stays UNGUARDED (a failure must be loud and abort startup),
    while only the backfill is wrapped, outside its own `with`.
    """
    is_sqlite = engine.dialect.name == "sqlite"
    ts = "TIMESTAMP" if is_sqlite else "TIMESTAMPTZ"
    now_default = "CURRENT_TIMESTAMP" if is_sqlite else "NOW()"
    pk = "INTEGER PRIMARY KEY AUTOINCREMENT" if is_sqlite else "SERIAL PRIMARY KEY"
    bool_true = "1" if is_sqlite else "TRUE"
    bool_false = "0" if is_sqlite else "FALSE"

    # --- transaction 1: the new tables -------------------------------------
    with engine.begin() as conn:
        if not _table_exists(conn, "enterprise_branches"):
            conn.execute(text(f"""
                CREATE TABLE enterprise_branches (
                    id {pk},
                    organization_id INTEGER NOT NULL,
                    name VARCHAR NOT NULL,
                    code VARCHAR,
                    city VARCHAR,
                    state_region VARCHAR,
                    country_code VARCHAR,
                    address_line VARCHAR,
                    phone VARCHAR,
                    email VARCHAR,
                    timezone VARCHAR,
                    is_default BOOLEAN NOT NULL DEFAULT {bool_false},
                    is_active BOOLEAN NOT NULL DEFAULT {bool_true},
                    archived_at {ts},
                    created_by_user_id INTEGER,
                    created_at {ts} DEFAULT {now_default} NOT NULL,
                    updated_at {ts}
                )
            """))

        if not _table_exists(conn, "enterprise_member_branches"):
            conn.execute(text(f"""
                CREATE TABLE enterprise_member_branches (
                    id {pk},
                    organization_id INTEGER NOT NULL,
                    member_id INTEGER NOT NULL,
                    branch_id INTEGER NOT NULL,
                    created_at {ts} DEFAULT {now_default} NOT NULL
                )
            """))

        if not _table_exists(conn, "enterprise_roles"):
            conn.execute(text(f"""
                CREATE TABLE enterprise_roles (
                    id {pk},
                    organization_id INTEGER NOT NULL,
                    name VARCHAR NOT NULL,
                    slug VARCHAR NOT NULL,
                    description VARCHAR,
                    capabilities_json TEXT,
                    data_scope VARCHAR,
                    based_on_role_key VARCHAR,
                    is_active BOOLEAN NOT NULL DEFAULT {bool_true},
                    created_by_user_id INTEGER,
                    created_at {ts} DEFAULT {now_default} NOT NULL,
                    updated_at {ts}
                )
            """))

        if not _table_exists(conn, "enterprise_access_audit"):
            conn.execute(text(f"""
                CREATE TABLE enterprise_access_audit (
                    id {pk},
                    organization_id INTEGER NOT NULL,
                    action VARCHAR NOT NULL,
                    actor_user_id INTEGER,
                    actor_name VARCHAR,
                    target_user_id INTEGER,
                    target_name VARCHAR,
                    target_role_id INTEGER,
                    target_branch_id INTEGER,
                    summary VARCHAR NOT NULL,
                    detail_json TEXT,
                    ip_address VARCHAR,
                    created_at {ts} DEFAULT {now_default} NOT NULL
                )
            """))

        # Unconditional: create_all(checkfirst=True) never builds __table_args__ indexes on a
        # table that already exists, and an index added in a later release would otherwise
        # never reach a database created by an earlier one.
        for stmt in (
            "CREATE INDEX IF NOT EXISTS ix_enterprise_branches_organization_id ON enterprise_branches(organization_id)",
            "CREATE INDEX IF NOT EXISTS ix_enterprise_branches_is_default ON enterprise_branches(is_default)",
            "CREATE INDEX IF NOT EXISTS ix_enterprise_branches_is_active ON enterprise_branches(is_active)",
            "CREATE INDEX IF NOT EXISTS ix_enterprise_branches_created_by_user_id ON enterprise_branches(created_by_user_id)",
            "CREATE INDEX IF NOT EXISTS ix_ent_branch_org_active ON enterprise_branches(organization_id, is_active)",
            "CREATE INDEX IF NOT EXISTS ix_enterprise_member_branches_organization_id ON enterprise_member_branches(organization_id)",
            "CREATE INDEX IF NOT EXISTS ix_enterprise_member_branches_member_id ON enterprise_member_branches(member_id)",
            "CREATE INDEX IF NOT EXISTS ix_enterprise_member_branches_branch_id ON enterprise_member_branches(branch_id)",
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_ent_member_branch_unique ON enterprise_member_branches(member_id, branch_id)",
            "CREATE INDEX IF NOT EXISTS ix_ent_member_branch_org ON enterprise_member_branches(organization_id, branch_id)",
            "CREATE INDEX IF NOT EXISTS ix_enterprise_roles_organization_id ON enterprise_roles(organization_id)",
            "CREATE INDEX IF NOT EXISTS ix_enterprise_roles_is_active ON enterprise_roles(is_active)",
            "CREATE INDEX IF NOT EXISTS ix_enterprise_roles_created_by_user_id ON enterprise_roles(created_by_user_id)",
            "CREATE INDEX IF NOT EXISTS ix_ent_role_org_active ON enterprise_roles(organization_id, is_active)",
            "CREATE INDEX IF NOT EXISTS ix_ent_role_org_slug ON enterprise_roles(organization_id, slug)",
            "CREATE INDEX IF NOT EXISTS ix_enterprise_access_audit_organization_id ON enterprise_access_audit(organization_id)",
            "CREATE INDEX IF NOT EXISTS ix_enterprise_access_audit_action ON enterprise_access_audit(action)",
            "CREATE INDEX IF NOT EXISTS ix_enterprise_access_audit_actor_user_id ON enterprise_access_audit(actor_user_id)",
            "CREATE INDEX IF NOT EXISTS ix_enterprise_access_audit_target_user_id ON enterprise_access_audit(target_user_id)",
            "CREATE INDEX IF NOT EXISTS ix_ent_access_audit_org_created ON enterprise_access_audit(organization_id, created_at)",
            "CREATE INDEX IF NOT EXISTS ix_ent_access_audit_org_action ON enterprise_access_audit(organization_id, action)",
        ):
            conn.execute(text(stmt))

    # --- transaction 2: new columns on the existing tables -----------------
    with engine.begin() as conn:
        if _table_exists(conn, "enterprise_organization_members"):
            member_cols = _get_table_columns(conn, "enterprise_organization_members")
            for column, ddl_type in _ENTERPRISE_MEMBER_ACCESS_COLUMNS:
                if column in member_cols:
                    continue
                sql_type = ts if ddl_type == "TS" else ddl_type
                conn.execute(text(
                    f"ALTER TABLE enterprise_organization_members ADD COLUMN {column} {sql_type}"
                ))
            for stmt in (
                "CREATE INDEX IF NOT EXISTS ix_enterprise_organization_members_role_key ON enterprise_organization_members(role_key)",
                "CREATE INDEX IF NOT EXISTS ix_enterprise_organization_members_custom_role_id ON enterprise_organization_members(custom_role_id)",
                "CREATE INDEX IF NOT EXISTS ix_enterprise_organization_members_primary_branch_id ON enterprise_organization_members(primary_branch_id)",
                "CREATE INDEX IF NOT EXISTS ix_enterprise_organization_members_status ON enterprise_organization_members(status)",
                "CREATE INDEX IF NOT EXISTS ix_ent_member_org_role_key ON enterprise_organization_members(organization_id, role_key)",
            ):
                conn.execute(text(stmt))

        if _table_exists(conn, "enterprise_clients"):
            client_cols = _get_table_columns(conn, "enterprise_clients")
            if "branch_id" not in client_cols:
                conn.execute(text("ALTER TABLE enterprise_clients ADD COLUMN branch_id INTEGER"))
            for stmt in (
                "CREATE INDEX IF NOT EXISTS ix_enterprise_clients_branch_id ON enterprise_clients(branch_id)",
                "CREATE INDEX IF NOT EXISTS ix_enterprise_clients_created_by_user_id ON enterprise_clients(created_by_user_id)",
                "CREATE INDEX IF NOT EXISTS ix_ent_clients_org_branch ON enterprise_clients(organization_id, branch_id)",
                "CREATE INDEX IF NOT EXISTS ix_ent_clients_org_assigned ON enterprise_clients(organization_id, assigned_to_user_id)",
                "CREATE INDEX IF NOT EXISTS ix_ent_clients_org_creator ON enterprise_clients(organization_id, created_by_user_id)",
            ):
                conn.execute(text(stmt))

    # --- transaction 3: the data backfill (guarded) ------------------------
    # try/except sits OUTSIDE the `with`, so the DDL above is already committed and a backfill
    # failure only rolls back the backfill. It must never abort startup: this whole block runs
    # inside main.startup_backfill_subscriptions(), where an exception takes the app down.
    try:
        with engine.begin() as conn:
            _backfill_enterprise_access_control(conn)
    except Exception as exc:  # noqa: BLE001 - never block startup on a data backfill
        print(f"[schema_patch] enterprise access-control backfill skipped: {exc}")


def _backfill_enterprise_access_control(conn):
    """One-time upgrade of every existing organization to the access-control model.

    Runs once per database (app_data_migrations marker) and every statement is additionally
    written to be non-clobbering — guarded on "the value is still NULL / still the ADD COLUMN
    default" — so re-running it after the marker is cleared cannot undo an admin's later edits.

    What it guarantees, because the feature fails closed: without an office every client would
    be invisible to a branch-scoped member, and without an explicit data_scope every existing
    member would inherit their role's default (assigned) and lose sight of the caseload they
    had yesterday. So existing members get data_scope='all' explicitly; only members created
    from here on get NULL (= inherit).
    """
    is_sqlite = engine.dialect.name == "sqlite"
    bool_false = "0" if is_sqlite else "FALSE"
    bool_true = "1" if is_sqlite else "TRUE"
    MIGRATION_KEY = "enterprise_access_control_v1"

    if not _table_exists(conn, "enterprise_organizations"):
        return
    conn.execute(text(
        "CREATE TABLE IF NOT EXISTS app_data_migrations ("
        "migration_key VARCHAR PRIMARY KEY, "
        "applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL)"
    ))
    if conn.execute(
        text("SELECT 1 FROM app_data_migrations WHERE migration_key = :k"),
        {"k": MIGRATION_KEY},
    ).fetchone():
        return

    has_clients = _table_exists(conn, "enterprise_clients")
    has_branch_name = has_clients and "branch_name" in _get_table_columns(conn, "enterprise_clients")

    orgs = conn.execute(text(
        "SELECT id, created_by_user_id FROM enterprise_organizations ORDER BY id"
    )).fetchall()

    branches_created = 0
    clients_placed = 0
    members_touched = 0
    owners_set = 0

    for org_id, created_by_user_id in orgs:
        # 1. The org's offices, keyed on lower(trim(name)); the lowest id wins a tie so the
        #    mapping is stable across runs. Archived offices count — reusing one is right, and
        #    creating a second office with the same name is exactly what we must not do.
        by_lname: dict[str, int] = {}
        default_branch_id = None
        for bid, bname, is_default in conn.execute(
            text("SELECT id, name, is_default FROM enterprise_branches "
                 "WHERE organization_id = :org ORDER BY id"),
            {"org": org_id},
        ).fetchall():
            by_lname.setdefault((bname or "").strip().lower(), bid)
            if is_default and default_branch_id is None:
                default_branch_id = bid

        if default_branch_id is None:
            default_branch_id = by_lname.get("head office")
            if default_branch_id is not None:
                conn.execute(
                    text(f"UPDATE enterprise_branches SET is_default = {bool_true} WHERE id = :bid"),
                    {"bid": default_branch_id},
                )
            else:
                conn.execute(
                    text("INSERT INTO enterprise_branches "
                         "(organization_id, name, is_default, is_active, created_by_user_id) "
                         f"VALUES (:org, 'Head Office', {bool_true}, {bool_true}, :uid)"),
                    {"org": org_id, "uid": created_by_user_id},
                )
                default_branch_id = conn.execute(
                    text("SELECT id FROM enterprise_branches WHERE organization_id = :org "
                         "AND lower(trim(name)) = 'head office' ORDER BY id"),
                    {"org": org_id},
                ).scalar()
                by_lname["head office"] = default_branch_id
                branches_created += 1

        # 2. One office per distinct free-text branch_name already on this org's clients.
        #    Deduped in Python on lower(trim(...)) — "Banjara Hills", " banjara hills " and
        #    "BANJARA HILLS" are one office, and the first spelling seen becomes its name.
        if has_branch_name:
            seen_order: list[tuple[str, str]] = []
            for (raw_name,) in conn.execute(
                text("SELECT branch_name FROM enterprise_clients WHERE organization_id = :org "
                     "AND branch_name IS NOT NULL AND trim(branch_name) <> '' ORDER BY id"),
                {"org": org_id},
            ).fetchall():
                label = (raw_name or "").strip()
                lname = label.lower()
                if not lname or any(lname == existing for existing, _ in seen_order):
                    continue
                seen_order.append((lname, label))

            for lname, label in seen_order:
                if lname not in by_lname:
                    conn.execute(
                        text("INSERT INTO enterprise_branches "
                             "(organization_id, name, is_default, is_active, created_by_user_id) "
                             f"VALUES (:org, :name, {bool_false}, {bool_true}, :uid)"),
                        {"org": org_id, "name": label, "uid": created_by_user_id},
                    )
                    by_lname[lname] = conn.execute(
                        text("SELECT id FROM enterprise_branches WHERE organization_id = :org "
                             "AND lower(trim(name)) = :lname ORDER BY id"),
                        {"org": org_id, "lname": lname},
                    ).scalar()
                    branches_created += 1

                # 3. Place the clients. `branch_id IS NULL` is what makes this idempotent AND
                #    non-clobbering: a client an admin has since moved to another office keeps
                #    the office they moved it to.
                clients_placed += conn.execute(
                    text("UPDATE enterprise_clients SET branch_id = :bid "
                         "WHERE organization_id = :org AND branch_id IS NULL "
                         "AND lower(trim(branch_name)) = :lname"),
                    {"bid": by_lname[lname], "org": org_id, "lname": lname},
                ).rowcount or 0

        if has_clients:
            # Everything with no usable branch_name goes to the default office — a NULL
            # branch_id is only visible at workspace scope, so leaving any behind would hide
            # them from their own counsellor.
            clients_placed += conn.execute(
                text("UPDATE enterprise_clients SET branch_id = :bid "
                     "WHERE organization_id = :org AND branch_id IS NULL"),
                {"bid": default_branch_id, "org": org_id},
            ).rowcount or 0
            if has_branch_name:
                # branch_name is the server-written display copy of branch_id from now on, so
                # fill in the blanks. Never overwrites a spelling a consultancy already typed.
                conn.execute(
                    text("UPDATE enterprise_clients SET branch_name = ("
                         "  SELECT name FROM enterprise_branches WHERE id = enterprise_clients.branch_id) "
                         "WHERE organization_id = :org AND branch_id IS NOT NULL "
                         "AND (branch_name IS NULL OR trim(branch_name) = '')"),
                    {"org": org_id},
                )

        if not _table_exists(conn, "enterprise_organization_members"):
            continue

        # 4. role_key from the legacy role string — only where role_key is still the ADD COLUMN
        #    default, so a role already set through the new UI is never rewritten.
        members_touched += conn.execute(
            text("UPDATE enterprise_organization_members SET role_key = CASE "
                 "WHEN role = 'admin' THEN 'admin' "
                 "WHEN role = 'editor' THEN 'counsellor' ELSE 'viewer' END "
                 "WHERE organization_id = :org "
                 "AND (role_key IS NULL OR role_key = '' OR role_key = 'viewer')"),
            {"org": org_id},
        ).rowcount or 0

        # 5. Existing members keep the access they have today: an explicit 'all'. New members
        #    get NULL and inherit their role's scope.
        conn.execute(
            text("UPDATE enterprise_organization_members SET data_scope = 'all' "
                 "WHERE organization_id = :org AND data_scope IS NULL"),
            {"org": org_id},
        )

        # 6. Home office + one member↔office link each. NOT EXISTS keeps the unique index happy
        #    and makes a re-run a no-op; a member reassigned to another office is left alone.
        conn.execute(
            text("UPDATE enterprise_organization_members SET primary_branch_id = :bid "
                 "WHERE organization_id = :org AND primary_branch_id IS NULL"),
            {"bid": default_branch_id, "org": org_id},
        )
        conn.execute(
            text("INSERT INTO enterprise_member_branches (organization_id, member_id, branch_id) "
                 "SELECT m.organization_id, m.id, m.primary_branch_id "
                 "FROM enterprise_organization_members m "
                 "WHERE m.organization_id = :org AND m.primary_branch_id IS NOT NULL "
                 "AND NOT EXISTS (SELECT 1 FROM enterprise_member_branches mb "
                 "                WHERE mb.member_id = m.id AND mb.branch_id = m.primary_branch_id)"),
            {"org": org_id},
        )

        # 7. Exactly one owner per org — the person who created the workspace, then the
        #    longest-standing admin, then just the longest-standing member. `role` is the
        #    legacy mirror and owner maps to 'admin' there (see legacy_role_for).
        owner_member_id = conn.execute(
            text("SELECT id FROM enterprise_organization_members "
                 f"WHERE organization_id = :org AND user_id = :uid AND is_active = {bool_true} "
                 "ORDER BY id LIMIT 1"),
            {"org": org_id, "uid": created_by_user_id},
        ).scalar()
        if owner_member_id is None:
            owner_member_id = conn.execute(
                text("SELECT id FROM enterprise_organization_members "
                     f"WHERE organization_id = :org AND is_active = {bool_true} AND role = 'admin' "
                     "ORDER BY id LIMIT 1"),
                {"org": org_id},
            ).scalar()
        if owner_member_id is None:
            owner_member_id = conn.execute(
                text("SELECT id FROM enterprise_organization_members "
                     f"WHERE organization_id = :org AND is_active = {bool_true} ORDER BY id LIMIT 1"),
                {"org": org_id},
            ).scalar()
        if owner_member_id is not None:
            conn.execute(
                text("UPDATE enterprise_organization_members "
                     "SET role_key = 'owner', role = 'admin' WHERE id = :mid"),
                {"mid": owner_member_id},
            )
            owners_set += 1
            # A second owner would make the "exactly one" invariant unenforceable from day one.
            conn.execute(
                text("UPDATE enterprise_organization_members SET role_key = 'admin' "
                     "WHERE organization_id = :org AND role_key = 'owner' AND id <> :mid"),
                {"org": org_id, "mid": owner_member_id},
            )

        # 8. Lifecycle timestamps derived from what the old schema recorded.
        conn.execute(
            text("UPDATE enterprise_organization_members SET status = 'suspended' "
                 f"WHERE organization_id = :org AND is_active = {bool_false} "
                 "AND (status IS NULL OR status = 'active')"),
            {"org": org_id},
        )
        conn.execute(
            text("UPDATE enterprise_organization_members SET invited_at = created_at "
                 "WHERE organization_id = :org AND invited_at IS NULL AND created_at IS NOT NULL"),
            {"org": org_id},
        )
        conn.execute(
            text("UPDATE enterprise_organization_members "
                 "SET deactivated_at = COALESCE(updated_at, created_at) "
                 f"WHERE organization_id = :org AND is_active = {bool_false} "
                 "AND deactivated_at IS NULL"),
            {"org": org_id},
        )

    # 9. Marker last, inside the same transaction as the work it describes.
    conn.execute(
        text("INSERT INTO app_data_migrations (migration_key) VALUES (:k)"),
        {"k": MIGRATION_KEY},
    )
    print(
        "[schema_patch] enterprise access control backfilled: "
        f"{len(orgs)} org(s), {branches_created} office(s) created, "
        f"{clients_placed} client(s) placed, {members_touched} member role(s) mapped, "
        f"{owners_set} owner(s) set"
    )


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


def ensure_enterprise_client_email_reply_columns():
    """Add inbound-reply threading columns to enterprise_client_emails for older DBs
    (in-place, idempotent). direction backfills existing rows as 'outbound'."""
    with engine.begin() as conn:
        if not _table_exists(conn, "enterprise_client_emails"):
            return
        columns = _get_table_columns(conn, "enterprise_client_emails")
        if "direction" not in columns:
            conn.execute(text(
                "ALTER TABLE enterprise_client_emails ADD COLUMN direction VARCHAR NOT NULL DEFAULT 'outbound'"
            ))
        if "from_email" not in columns:
            conn.execute(text(
                "ALTER TABLE enterprise_client_emails ADD COLUMN from_email VARCHAR"
            ))
        # Concurrency-safe inbound dedupe: Svix redeliveries race the
        # check-then-insert, so back it with a partial unique index (works on
        # both sqlite and postgres). Self-healing on both create paths.
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_ent_client_emails_inbound_msg "
            "ON enterprise_client_emails(provider_message_id) "
            "WHERE direction = 'inbound' AND provider_message_id IS NOT NULL"
        ))


def ensure_enterprise_email_composer_schema():
    """Add the rich-text body column and the email-attachments table used by the
    client email composer. Idempotent and additive — safe to run on every startup.

    Attachment rows with a NULL email_id are drafts: uploaded while a message is
    still being written, bound to the email when it sends."""
    is_sqlite = engine.dialect.name == "sqlite"
    ts = "TIMESTAMP" if is_sqlite else "TIMESTAMPTZ"
    now_default = "CURRENT_TIMESTAMP" if is_sqlite else "NOW()"
    pk = "INTEGER PRIMARY KEY AUTOINCREMENT" if is_sqlite else "SERIAL PRIMARY KEY"
    with engine.begin() as conn:
        if _table_exists(conn, "enterprise_client_emails"):
            if "body_html" not in _get_table_columns(conn, "enterprise_client_emails"):
                conn.execute(text("ALTER TABLE enterprise_client_emails ADD COLUMN body_html TEXT"))

        if not _table_exists(conn, "enterprise_client_email_attachments"):
            conn.execute(text(f"""
                CREATE TABLE enterprise_client_email_attachments (
                    id {pk},
                    organization_id INTEGER NOT NULL,
                    email_id INTEGER REFERENCES enterprise_client_emails(id) ON DELETE CASCADE,
                    client_id INTEGER,
                    source_document_id INTEGER,
                    original_filename VARCHAR NOT NULL,
                    storage_key VARCHAR NOT NULL,
                    file_size INTEGER,
                    mime_type VARCHAR,
                    uploaded_by_user_id INTEGER,
                    created_at {ts} DEFAULT {now_default} NOT NULL
                )
            """))
            for stmt in (
                "CREATE INDEX IF NOT EXISTS ix_ent_email_attachments_organization_id ON enterprise_client_email_attachments(organization_id)",
                "CREATE INDEX IF NOT EXISTS ix_ent_email_attachments_email_id ON enterprise_client_email_attachments(email_id)",
                "CREATE INDEX IF NOT EXISTS ix_ent_email_attachments_client_id ON enterprise_client_email_attachments(client_id)",
                "CREATE INDEX IF NOT EXISTS ix_ent_email_attachments_uploaded_by ON enterprise_client_email_attachments(uploaded_by_user_id)",
                # The composer's own lookup: this user's still-unsent drafts for a client.
                "CREATE INDEX IF NOT EXISTS ix_ent_email_attachments_draft ON enterprise_client_email_attachments(client_id, uploaded_by_user_id, email_id)",
            ):
                conn.execute(text(stmt))


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


def ensure_enterprise_step_up_otps_table():
    """Create the enterprise_step_up_otps table (re-confirm codes for irreversible actions)."""
    is_sqlite = engine.dialect.name == "sqlite"
    ts = "TIMESTAMP" if is_sqlite else "TIMESTAMPTZ"
    now_default = "CURRENT_TIMESTAMP" if is_sqlite else "NOW()"
    pk = "INTEGER PRIMARY KEY AUTOINCREMENT" if is_sqlite else "SERIAL PRIMARY KEY"
    with engine.begin() as conn:
        # No early return when the table exists: `Base.metadata.create_all()` may have created
        # it from the model on an earlier boot, and the unique index below still has to land.
        if not _table_exists(conn, "enterprise_step_up_otps"):
            conn.execute(text(f"""
                CREATE TABLE enterprise_step_up_otps (
                    id {pk},
                    user_id INTEGER NOT NULL,
                    organization_id INTEGER NOT NULL,
                    purpose VARCHAR NOT NULL,
                    context_key VARCHAR,
                    code_hash VARCHAR NOT NULL,
                    expires_at {ts} NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    consumed_at {ts},
                    created_at {ts} DEFAULT {now_default} NOT NULL
                )
            """))
        # One live code per actor per purpose per workspace: re-requesting replaces, so an
        # older code stops working the moment a new one is sent.
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_enterprise_step_up_otps_scope "
            "ON enterprise_step_up_otps(user_id, organization_id, purpose)"
        ))


def ensure_enterprise_support_requests_table():
    """Create the enterprise_support_requests table (help & feature requests)."""
    is_sqlite = engine.dialect.name == "sqlite"
    ts = "TIMESTAMP" if is_sqlite else "TIMESTAMPTZ"
    now_default = "CURRENT_TIMESTAMP" if is_sqlite else "NOW()"
    pk = "INTEGER PRIMARY KEY AUTOINCREMENT" if is_sqlite else "SERIAL PRIMARY KEY"
    with engine.begin() as conn:
        if _table_exists(conn, "enterprise_support_requests"):
            # Additive: attachments_json (manifest of files forwarded to the support inbox).
            if "attachments_json" not in _get_table_columns(conn, "enterprise_support_requests"):
                conn.execute(text("ALTER TABLE enterprise_support_requests ADD COLUMN attachments_json TEXT"))
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
                attachments_json TEXT,
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


def ensure_enterprise_client_portal_shares_table():
    """Create the secure client portal-share table (read-only client tracking portal).

    A share is a tokenized, OTP-verified capability sent to a client's email so
    they can view (never edit) their own case: journey stages, stage records,
    profile details, documents, universities and payments. Idempotent and
    additive — safe to run on every startup."""
    is_sqlite = engine.dialect.name == "sqlite"
    ts = "TIMESTAMP" if is_sqlite else "TIMESTAMPTZ"
    now_default = "CURRENT_TIMESTAMP" if is_sqlite else "NOW()"
    pk = "INTEGER PRIMARY KEY AUTOINCREMENT" if is_sqlite else "SERIAL PRIMARY KEY"
    bool_false = "0" if is_sqlite else "FALSE"
    with engine.begin() as conn:
        if not _table_exists(conn, "enterprise_client_portal_shares"):
            conn.execute(text(f"""
                CREATE TABLE enterprise_client_portal_shares (
                    id {pk},
                    organization_id INTEGER NOT NULL,
                    client_id INTEGER NOT NULL,
                    token_hash VARCHAR NOT NULL,
                    email VARCHAR NOT NULL,
                    code_hash VARCHAR,
                    code_expires_at {ts},
                    code_attempts INTEGER NOT NULL DEFAULT 0,
                    expires_at {ts},
                    revoked BOOLEAN NOT NULL DEFAULT {bool_false},
                    last_opened_at {ts},
                    open_count INTEGER NOT NULL DEFAULT 0,
                    created_by_user_id INTEGER,
                    created_by_name VARCHAR,
                    created_at {ts} DEFAULT {now_default} NOT NULL,
                    updated_at {ts}
                )
            """))
            for stmt in (
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_enterprise_client_portal_shares_token ON enterprise_client_portal_shares(token_hash)",
                "CREATE INDEX IF NOT EXISTS ix_enterprise_client_portal_shares_organization_id ON enterprise_client_portal_shares(organization_id)",
                "CREATE INDEX IF NOT EXISTS ix_enterprise_client_portal_shares_client_id ON enterprise_client_portal_shares(client_id)",
                "CREATE INDEX IF NOT EXISTS ix_ent_portal_shares_client_created ON enterprise_client_portal_shares(client_id, created_at)",
            ):
                conn.execute(text(stmt))


def ensure_enterprise_copilot_invites_table():
    """Create the secure client Copilot-invite table (client-shared Copilot chat).

    An invite is a tokenized, OTP-verified capability sent to a client's email so
    they can chat with the org's AI copilot about their own case. Access is a
    flat per-client unlock (charged once at first verify) with a message cap.
    Idempotent and additive — safe to run on every startup."""
    is_sqlite = engine.dialect.name == "sqlite"
    ts = "TIMESTAMP" if is_sqlite else "TIMESTAMPTZ"
    now_default = "CURRENT_TIMESTAMP" if is_sqlite else "NOW()"
    pk = "INTEGER PRIMARY KEY AUTOINCREMENT" if is_sqlite else "SERIAL PRIMARY KEY"
    bool_false = "0" if is_sqlite else "FALSE"
    with engine.begin() as conn:
        if not _table_exists(conn, "enterprise_copilot_invites"):
            conn.execute(text(f"""
                CREATE TABLE enterprise_copilot_invites (
                    id {pk},
                    organization_id INTEGER NOT NULL,
                    client_id INTEGER NOT NULL,
                    token_hash VARCHAR NOT NULL,
                    email VARCHAR NOT NULL,
                    allowed_messages INTEGER NOT NULL DEFAULT 100,
                    used_messages INTEGER NOT NULL DEFAULT 0,
                    last_message_at {ts},
                    unlocked_at {ts},
                    credits_charged INTEGER NOT NULL DEFAULT 0,
                    code_hash VARCHAR,
                    code_expires_at {ts},
                    code_attempts INTEGER NOT NULL DEFAULT 0,
                    code_attempts_total INTEGER NOT NULL DEFAULT 0,
                    expires_at {ts},
                    revoked BOOLEAN NOT NULL DEFAULT {bool_false},
                    created_by_user_id INTEGER,
                    created_by_name VARCHAR,
                    created_at {ts} DEFAULT {now_default} NOT NULL,
                    updated_at {ts}
                )
            """))
        else:
            # Existing installs: the lifetime OTP budget is additive. Defaulting to 0
            # gives every live invite a full fresh budget, which is the intent — no
            # in-flight client is locked out by the deploy.
            if "code_attempts_total" not in _get_table_columns(conn, "enterprise_copilot_invites"):
                conn.execute(text(
                    "ALTER TABLE enterprise_copilot_invites ADD COLUMN code_attempts_total INTEGER NOT NULL DEFAULT 0"
                ))
        for stmt in (
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_enterprise_copilot_invites_token ON enterprise_copilot_invites(token_hash)",
            "CREATE INDEX IF NOT EXISTS ix_enterprise_copilot_invites_organization_id ON enterprise_copilot_invites(organization_id)",
            "CREATE INDEX IF NOT EXISTS ix_enterprise_copilot_invites_client_id ON enterprise_copilot_invites(client_id)",
            "CREATE INDEX IF NOT EXISTS ix_ent_copilot_invites_client_created ON enterprise_copilot_invites(client_id, created_at)",
            # Declared on the model but never created here — the staff "sent by" lookup.
            "CREATE INDEX IF NOT EXISTS ix_enterprise_copilot_invites_created_by_user_id ON enterprise_copilot_invites(created_by_user_id)",
        ):
            conn.execute(text(stmt))


def ensure_enterprise_deep_scan_table():
    """Create the stored Deep Scan results table (full-dossier AI audits, kept as
    per-client history). Idempotent and additive — safe to run on every startup."""
    is_sqlite = engine.dialect.name == "sqlite"
    ts = "TIMESTAMP" if is_sqlite else "TIMESTAMPTZ"
    now_default = "CURRENT_TIMESTAMP" if is_sqlite else "NOW()"
    pk = "INTEGER PRIMARY KEY AUTOINCREMENT" if is_sqlite else "SERIAL PRIMARY KEY"
    with engine.begin() as conn:
        if not _table_exists(conn, "enterprise_client_deep_scans"):
            conn.execute(text(f"""
                CREATE TABLE enterprise_client_deep_scans (
                    id {pk},
                    organization_id INTEGER NOT NULL,
                    client_id INTEGER NOT NULL,
                    risk_level VARCHAR NOT NULL DEFAULT 'medium',
                    summary TEXT,
                    findings TEXT,
                    checks_passed TEXT,
                    stats TEXT,
                    model_used VARCHAR,
                    credits_charged INTEGER NOT NULL DEFAULT 0,
                    triggered_by_user_id INTEGER,
                    triggered_by_name VARCHAR,
                    created_at {ts} DEFAULT {now_default} NOT NULL
                )
            """))
            for stmt in (
                "CREATE INDEX IF NOT EXISTS ix_enterprise_client_deep_scans_organization_id ON enterprise_client_deep_scans(organization_id)",
                "CREATE INDEX IF NOT EXISTS ix_enterprise_client_deep_scans_client_id ON enterprise_client_deep_scans(client_id)",
                "CREATE INDEX IF NOT EXISTS ix_enterprise_client_deep_scans_created_at ON enterprise_client_deep_scans(created_at)",
                "CREATE INDEX IF NOT EXISTS ix_ent_deep_scans_client_created ON enterprise_client_deep_scans(client_id, created_at)",
            ):
                conn.execute(text(stmt))
        # Monthly free-scan budget counters on the wallet (anti-farming guard).
        if _table_exists(conn, "enterprise_credit_wallets"):
            wallet_cols = _get_table_columns(conn, "enterprise_credit_wallets")
            if "deep_scan_free_month" not in wallet_cols:
                conn.execute(text("ALTER TABLE enterprise_credit_wallets ADD COLUMN deep_scan_free_month VARCHAR"))
            if "deep_scan_free_used" not in wallet_cols:
                conn.execute(text("ALTER TABLE enterprise_credit_wallets ADD COLUMN deep_scan_free_used INTEGER NOT NULL DEFAULT 0"))


def ensure_enterprise_ai_conversation_tables():
    """Create the saved Rilono AI Assistant thread tables (per-member conversations +
    their messages). The transcript lives server-side so /ai/chat replays history from
    the DB instead of trusting the client's copy. Idempotent and additive — safe to run
    on every startup."""
    is_sqlite = engine.dialect.name == "sqlite"
    ts = "TIMESTAMP" if is_sqlite else "TIMESTAMPTZ"
    now_default = "CURRENT_TIMESTAMP" if is_sqlite else "NOW()"
    pk = "INTEGER PRIMARY KEY AUTOINCREMENT" if is_sqlite else "SERIAL PRIMARY KEY"
    with engine.begin() as conn:
        if not _table_exists(conn, "enterprise_ai_conversations"):
            conn.execute(text(f"""
                CREATE TABLE enterprise_ai_conversations (
                    id {pk},
                    organization_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    title VARCHAR,
                    message_count INTEGER NOT NULL DEFAULT 0,
                    created_at {ts} DEFAULT {now_default} NOT NULL,
                    last_message_at {ts} DEFAULT {now_default} NOT NULL
                )
            """))
            for stmt in (
                "CREATE INDEX IF NOT EXISTS ix_enterprise_ai_conversations_organization_id ON enterprise_ai_conversations(organization_id)",
                "CREATE INDEX IF NOT EXISTS ix_enterprise_ai_conversations_user_id ON enterprise_ai_conversations(user_id)",
                "CREATE INDEX IF NOT EXISTS ix_enterprise_ai_conversations_last_message_at ON enterprise_ai_conversations(last_message_at)",
                "CREATE INDEX IF NOT EXISTS ix_ent_ai_convs_org_user_last ON enterprise_ai_conversations(organization_id, user_id, last_message_at)",
            ):
                conn.execute(text(stmt))
        if not _table_exists(conn, "enterprise_ai_messages"):
            conn.execute(text(f"""
                CREATE TABLE enterprise_ai_messages (
                    id {pk},
                    conversation_id INTEGER NOT NULL,
                    organization_id INTEGER NOT NULL,
                    role VARCHAR NOT NULL,
                    content TEXT NOT NULL,
                    created_at {ts} DEFAULT {now_default} NOT NULL
                )
            """))
            for stmt in (
                "CREATE INDEX IF NOT EXISTS ix_enterprise_ai_messages_conversation_id ON enterprise_ai_messages(conversation_id)",
                "CREATE INDEX IF NOT EXISTS ix_enterprise_ai_messages_organization_id ON enterprise_ai_messages(organization_id)",
                "CREATE INDEX IF NOT EXISTS ix_ent_ai_msgs_conv_id ON enterprise_ai_messages(conversation_id, id)",
            ):
                conn.execute(text(stmt))


def ensure_enterprise_writing_studio_table():
    """Create the enterprise Writing Studio drafts table (AI-written SOPs and LORs for
    a client, stored as an immutable version chain). Idempotent and additive — safe to
    run on every startup."""
    is_sqlite = engine.dialect.name == "sqlite"
    ts = "TIMESTAMP" if is_sqlite else "TIMESTAMPTZ"
    now_default = "CURRENT_TIMESTAMP" if is_sqlite else "NOW()"
    pk = "INTEGER PRIMARY KEY AUTOINCREMENT" if is_sqlite else "SERIAL PRIMARY KEY"
    with engine.begin() as conn:
        if not _table_exists(conn, "enterprise_client_writing_drafts"):
            conn.execute(text(f"""
                CREATE TABLE enterprise_client_writing_drafts (
                    id {pk},
                    organization_id INTEGER NOT NULL,
                    client_id INTEGER NOT NULL,
                    doc_type VARCHAR NOT NULL DEFAULT 'sop',
                    root_id INTEGER,
                    version INTEGER NOT NULL DEFAULT 1,
                    country_code VARCHAR,
                    university VARCHAR,
                    program VARCHAR,
                    study_level VARCHAR,
                    intake VARCHAR,
                    recommender_type VARCHAR,
                    recommender_name VARCHAR,
                    recommender_title VARCHAR,
                    recommender_org VARCHAR,
                    recommender_email VARCHAR,
                    relationship_context TEXT,
                    brief TEXT,
                    instruction TEXT,
                    title VARCHAR,
                    content_md TEXT NOT NULL,
                    notes_md TEXT,
                    word_count INTEGER NOT NULL DEFAULT 0,
                    model_used VARCHAR,
                    credits_charged INTEGER NOT NULL DEFAULT 0,
                    created_by_user_id INTEGER,
                    created_by_name VARCHAR,
                    created_at {ts} DEFAULT {now_default} NOT NULL
                )
            """))
            for stmt in (
                "CREATE INDEX IF NOT EXISTS ix_enterprise_client_writing_drafts_organization_id ON enterprise_client_writing_drafts(organization_id)",
                "CREATE INDEX IF NOT EXISTS ix_enterprise_client_writing_drafts_client_id ON enterprise_client_writing_drafts(client_id)",
                "CREATE INDEX IF NOT EXISTS ix_enterprise_client_writing_drafts_root_id ON enterprise_client_writing_drafts(root_id)",
                "CREATE INDEX IF NOT EXISTS ix_enterprise_client_writing_drafts_created_at ON enterprise_client_writing_drafts(created_at)",
                "CREATE INDEX IF NOT EXISTS ix_ent_writing_drafts_client_created ON enterprise_client_writing_drafts(client_id, created_at)",
                "CREATE INDEX IF NOT EXISTS ix_ent_writing_drafts_root_version ON enterprise_client_writing_drafts(root_id, version)",
            ):
                conn.execute(text(stmt))
        else:
            # Additive follow-ups for installs created before a column existed.
            cols = _get_table_columns(conn, "enterprise_client_writing_drafts")
            if "notes_md" not in cols:
                conn.execute(text("ALTER TABLE enterprise_client_writing_drafts ADD COLUMN notes_md TEXT"))


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
        # Off-platform ("manual") payment recording — self-healing on BOTH paths (fresh create and
        # augmented), since the fresh-create DDL above does not list this column.
        if "manual_method" not in _get_table_columns(conn, "enterprise_student_payments"):
            conn.execute(text("ALTER TABLE enterprise_student_payments ADD COLUMN manual_method VARCHAR"))
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


def ensure_enterprise_finance_tables():
    """Create the org-scoped finance books tables: the hand-recorded income/expense
    ledger and the per-org finance settings (hourly cost, opening balance, FY start,
    savings baselines).

    Only money the platform cannot already see is stored here — collected payments,
    Rilono fees, credit top-ups, refunds and chargebacks are derived at read time from
    their own tables (app/enterprise_finance.py). Idempotent and additive.
    """
    is_sqlite = engine.dialect.name == "sqlite"
    ts = "TIMESTAMP" if is_sqlite else "TIMESTAMPTZ"
    now_default = "CURRENT_TIMESTAMP" if is_sqlite else "NOW()"
    pk = "INTEGER PRIMARY KEY AUTOINCREMENT" if is_sqlite else "SERIAL PRIMARY KEY"
    bool_false = "0" if is_sqlite else "FALSE"
    with engine.begin() as conn:
        # --- enterprise_finance_entries (the manual books) ---
        if not _table_exists(conn, "enterprise_finance_entries"):
            conn.execute(text(f"""
                CREATE TABLE enterprise_finance_entries (
                    id {pk},
                    organization_id INTEGER NOT NULL,
                    kind VARCHAR NOT NULL DEFAULT 'expense',
                    category VARCHAR NOT NULL DEFAULT 'other_expense',
                    amount_paise INTEGER NOT NULL DEFAULT 0,
                    tax_paise INTEGER NOT NULL DEFAULT 0,
                    currency VARCHAR NOT NULL DEFAULT 'INR',
                    occurred_on DATE NOT NULL,
                    description VARCHAR,
                    counterparty VARCHAR,
                    payment_method VARCHAR,
                    reference VARCHAR,
                    notes TEXT,
                    client_id INTEGER,
                    client_name_snapshot VARCHAR,
                    repeat_monthly BOOLEAN NOT NULL DEFAULT {bool_false},
                    repeat_until DATE,
                    created_by_user_id INTEGER,
                    created_by_name VARCHAR,
                    created_at {ts} DEFAULT {now_default} NOT NULL,
                    updated_at {ts}
                )
            """))

        # --- enterprise_finance_settings (one row per org) ---
        if not _table_exists(conn, "enterprise_finance_settings"):
            conn.execute(text(f"""
                CREATE TABLE enterprise_finance_settings (
                    id {pk},
                    organization_id INTEGER NOT NULL,
                    hourly_cost_paise INTEGER NOT NULL DEFAULT 40000,
                    -- BIGINT: a bank balance can exceed int4's ~₹2.1 crore ceiling in paise.
                    opening_balance_paise BIGINT NOT NULL DEFAULT 0,
                    opening_balance_on DATE,
                    fy_start_month INTEGER NOT NULL DEFAULT 4,
                    savings_overrides_json TEXT,
                    updated_by_user_id INTEGER,
                    created_at {ts} DEFAULT {now_default} NOT NULL,
                    updated_at {ts}
                )
            """))

        # Additive self-heal, outside the create branch so it reaches an ALREADY-EXISTING
        # table too (a table created by an earlier build, or by Base.metadata.create_all
        # before a column was added). Every NOT NULL addition carries a DEFAULT.
        entry_cols = _get_table_columns(conn, "enterprise_finance_entries")
        for col, ddl in (
            ("kind", "VARCHAR NOT NULL DEFAULT 'expense'"),
            ("category", "VARCHAR NOT NULL DEFAULT 'other_expense'"),
            ("amount_paise", "INTEGER NOT NULL DEFAULT 0"),
            ("tax_paise", "INTEGER NOT NULL DEFAULT 0"),
            ("currency", "VARCHAR NOT NULL DEFAULT 'INR'"),
            ("description", "VARCHAR"),
            ("counterparty", "VARCHAR"),
            ("payment_method", "VARCHAR"),
            ("reference", "VARCHAR"),
            ("notes", "TEXT"),
            ("client_id", "INTEGER"),
            ("client_name_snapshot", "VARCHAR"),
            ("repeat_monthly", f"BOOLEAN NOT NULL DEFAULT {bool_false}"),
            ("repeat_until", "DATE"),
            ("created_by_user_id", "INTEGER"),
            ("created_by_name", "VARCHAR"),
            ("updated_at", ts),
        ):
            if col not in entry_cols:
                conn.execute(text(f"ALTER TABLE enterprise_finance_entries ADD COLUMN {col} {ddl}"))

        settings_cols = _get_table_columns(conn, "enterprise_finance_settings")
        for col, ddl in (
            ("hourly_cost_paise", "INTEGER NOT NULL DEFAULT 40000"),
            ("opening_balance_paise", "BIGINT NOT NULL DEFAULT 0"),
            ("opening_balance_on", "DATE"),
            ("fy_start_month", "INTEGER NOT NULL DEFAULT 4"),
            ("savings_overrides_json", "TEXT"),
            ("updated_by_user_id", "INTEGER"),
            ("updated_at", ts),
        ):
            if col not in settings_cols:
                conn.execute(text(f"ALTER TABLE enterprise_finance_settings ADD COLUMN {col} {ddl}"))

        # Indexes also run on BOTH paths — an index created only inside the `if not
        # _table_exists` branch never reaches a database that already has the table.
        for stmt in (
            "CREATE INDEX IF NOT EXISTS ix_enterprise_finance_entries_organization_id ON enterprise_finance_entries(organization_id)",
            "CREATE INDEX IF NOT EXISTS ix_enterprise_finance_entries_client_id ON enterprise_finance_entries(client_id)",
            "CREATE INDEX IF NOT EXISTS ix_enterprise_finance_entries_occurred_on ON enterprise_finance_entries(occurred_on)",
            "CREATE INDEX IF NOT EXISTS ix_enterprise_finance_entries_category ON enterprise_finance_entries(category)",
            "CREATE INDEX IF NOT EXISTS ix_enterprise_finance_entries_counterparty ON enterprise_finance_entries(counterparty)",
            "CREATE INDEX IF NOT EXISTS ix_enterprise_finance_entries_kind ON enterprise_finance_entries(kind)",
            "CREATE INDEX IF NOT EXISTS ix_enterprise_finance_entries_created_by ON enterprise_finance_entries(created_by_user_id)",
            "CREATE INDEX IF NOT EXISTS ix_ent_fin_entries_org_date ON enterprise_finance_entries(organization_id, occurred_on)",
            "CREATE INDEX IF NOT EXISTS ix_ent_fin_entries_org_kind ON enterprise_finance_entries(organization_id, kind)",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_ent_fin_settings_org ON enterprise_finance_settings(organization_id)",
            "CREATE INDEX IF NOT EXISTS ix_enterprise_finance_settings_updated_by ON enterprise_finance_settings(updated_by_user_id)",
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


def ensure_enterprise_calendar_attachment_table():
    """Create enterprise_calendar_event_attachments (reference files pinned to an event).

    A row with a NULL event_id and a draft_token is still a draft: uploaded while a brand-new
    reminder was being filled in, and bound to the event when it saves. Idempotent.
    """
    is_sqlite = engine.dialect.name == "sqlite"
    ts = "TIMESTAMP" if is_sqlite else "TIMESTAMPTZ"
    now_default = "CURRENT_TIMESTAMP" if is_sqlite else "NOW()"
    pk = "INTEGER PRIMARY KEY AUTOINCREMENT" if is_sqlite else "SERIAL PRIMARY KEY"
    with engine.begin() as conn:
        if not _table_exists(conn, "enterprise_calendar_event_attachments"):
            conn.execute(text(f"""
                CREATE TABLE enterprise_calendar_event_attachments (
                    id {pk},
                    organization_id INTEGER NOT NULL,
                    event_id INTEGER REFERENCES enterprise_calendar_events(id) ON DELETE CASCADE,
                    draft_token VARCHAR,
                    original_filename VARCHAR NOT NULL,
                    storage_key VARCHAR NOT NULL,
                    file_size INTEGER,
                    mime_type VARCHAR,
                    uploaded_by_user_id INTEGER,
                    uploaded_by_name VARCHAR,
                    created_at {ts} DEFAULT {now_default} NOT NULL
                )
            """))
            for stmt in (
                "CREATE INDEX IF NOT EXISTS ix_ent_cal_att_organization_id "
                "ON enterprise_calendar_event_attachments(organization_id)",
                "CREATE INDEX IF NOT EXISTS ix_ent_cal_att_event_id "
                "ON enterprise_calendar_event_attachments(event_id)",
                "CREATE INDEX IF NOT EXISTS ix_ent_cal_att_uploaded_by "
                "ON enterprise_calendar_event_attachments(uploaded_by_user_id)",
                "CREATE INDEX IF NOT EXISTS ix_ent_cal_att_created_at "
                "ON enterprise_calendar_event_attachments(created_at)",
                # The upload path's own lookup: this uploader's unbound drafts for one modal.
                "CREATE INDEX IF NOT EXISTS ix_ent_cal_att_draft "
                "ON enterprise_calendar_event_attachments(organization_id, draft_token, event_id)",
            ):
                conn.execute(text(stmt))


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
                    plan_credits_period VARCHAR,
                    plan_credits_granted INTEGER NOT NULL DEFAULT 0,
                    plan_credits_remaining INTEGER NOT NULL DEFAULT 0,
                    plan_credits_once_at TIMESTAMP,
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
            # Existing wallets: add the copilot-metering, staff-preview and plan-allowance
            # columns idempotently. plan_credits_* default to 0/NULL, which reads as "this
            # period's allowance has not been granted yet" — so the first wallet access
            # after deploy grants it. That is the intended behaviour, not a backfill gap.
            wallet_cols = _get_table_columns(conn, "enterprise_credit_wallets")
            for col, ddl in (
                ("copilot_usage_date", "VARCHAR"),
                ("copilot_msgs_today", "INTEGER NOT NULL DEFAULT 0"),
                ("copilot_unbilled_msgs", "INTEGER NOT NULL DEFAULT 0"),
                ("interview_staff_previews_used", "INTEGER NOT NULL DEFAULT 0"),
                ("plan_credits_period", "VARCHAR"),
                ("plan_credits_granted", "INTEGER NOT NULL DEFAULT 0"),
                ("plan_credits_remaining", "INTEGER NOT NULL DEFAULT 0"),
                ("plan_credits_once_at", "TIMESTAMP"),
            ):
                if col not in wallet_cols:
                    conn.execute(text(f"ALTER TABLE enterprise_credit_wallets ADD COLUMN {col} {ddl}"))
                    if col == "plan_credits_once_at":
                        # Backfill: a wallet already carrying a ":once" key has HAD its
                        # one-time grant. Without this the marker starts NULL for every
                        # existing org, and the first sandbox->paid->lapse cycle after this
                        # deploy would hand out the demo credits a second time.
                        conn.execute(text(
                            "UPDATE enterprise_credit_wallets SET plan_credits_once_at = created_at "
                            "WHERE plan_credits_period LIKE '%:once'"
                        ))

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


def ensure_enterprise_client_university_table():
    """Create enterprise_client_universities (per-client university shortlisting, B2B).

    Additive and idempotent — safe on every startup. Separate from the B2C
    university_shortlist_entries table because these rows are org+client scoped and staff
    managed, and they persist the AI's ranking/difficulty fields that consultants shortlist on.
    """
    is_sqlite = engine.dialect.name == "sqlite"
    ts = "TIMESTAMP" if is_sqlite else "TIMESTAMPTZ"
    now_default = "CURRENT_TIMESTAMP" if is_sqlite else "NOW()"
    pk = "INTEGER PRIMARY KEY AUTOINCREMENT" if is_sqlite else "SERIAL PRIMARY KEY"
    with engine.begin() as conn:
        if _table_exists(conn, "enterprise_client_universities"):
            # Table predates the link/fee columns (created earlier in this feature's rollout).
            # Add them additively so an existing install isn't left without them.
            existing = _get_table_columns(conn, "enterprise_client_universities")
            for col in ("application_fee", "website_url", "admissions_url"):
                if col not in existing:
                    conn.execute(text(f"ALTER TABLE enterprise_client_universities ADD COLUMN {col} VARCHAR"))
            return
        conn.execute(text(f"""
            CREATE TABLE enterprise_client_universities (
                id {pk},
                organization_id INTEGER NOT NULL,
                client_id INTEGER NOT NULL,
                country_code VARCHAR,
                university_name VARCHAR NOT NULL,
                program VARCHAR,
                location VARCHAR,
                status VARCHAR NOT NULL DEFAULT 'considering',
                source VARCHAR NOT NULL DEFAULT 'manual',
                est_tuition VARCHAR,
                rationale TEXT,
                notes TEXT,
                qs_world_rank VARCHAR,
                country_rank VARCHAR,
                admission_difficulty VARCHAR,
                key_requirements TEXT,
                application_fee VARCHAR,
                website_url VARCHAR,
                admissions_url VARCHAR,
                added_by_user_id INTEGER,
                added_by_name VARCHAR,
                created_at {ts} DEFAULT {now_default} NOT NULL,
                updated_at {ts}
            )
        """))
        for stmt in (
            "CREATE INDEX IF NOT EXISTS ix_enterprise_client_universities_organization_id ON enterprise_client_universities(organization_id)",
            "CREATE INDEX IF NOT EXISTS ix_enterprise_client_universities_client_id ON enterprise_client_universities(client_id)",
            "CREATE INDEX IF NOT EXISTS ix_enterprise_client_universities_added_by_user_id ON enterprise_client_universities(added_by_user_id)",
            "CREATE INDEX IF NOT EXISTS ix_enterprise_client_universities_client_created ON enterprise_client_universities(client_id, created_at)",
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
            # Google Search grounding is billed per request, not per token, so it needs
            # its own columns — estimated_cost_usd stays the TOTAL (tokens + search) and
            # pre-existing rows keep their meaning, with search columns defaulting to 0.
            if "search_queries" not in cols:
                conn.execute(text("ALTER TABLE gemini_usage_events ADD COLUMN search_queries INTEGER NOT NULL DEFAULT 0"))
            if "search_cost_usd" not in cols:
                conn.execute(text("ALTER TABLE gemini_usage_events ADD COLUMN search_cost_usd NUMERIC(12,6) NOT NULL DEFAULT 0"))
            if "status" not in cols:
                conn.execute(text("ALTER TABLE gemini_usage_events ADD COLUMN status VARCHAR NOT NULL DEFAULT 'ok'"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_gemini_usage_events_status ON gemini_usage_events(status)"))
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
                    search_queries INTEGER NOT NULL DEFAULT 0,
                    search_cost_usd NUMERIC(12,6) NOT NULL DEFAULT 0,
                    status VARCHAR NOT NULL DEFAULT 'ok',
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
                    search_queries INTEGER NOT NULL DEFAULT 0,
                    search_cost_usd NUMERIC(12,6) NOT NULL DEFAULT 0,
                    status VARCHAR NOT NULL DEFAULT 'ok',
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


def ensure_course_catalog_tables():
    """Create the Course Finder catalog tables: shared universities/courses data
    (written only by the background catalog-refresh agent), the agent's run-state
    table (UNIQUE run_date = multi-worker double-run guard), and the org-scoped
    stored AI recommendation history. Idempotent and additive — safe on every startup."""
    is_sqlite = engine.dialect.name == "sqlite"
    ts = "TIMESTAMP" if is_sqlite else "TIMESTAMPTZ"
    now_default = "CURRENT_TIMESTAMP" if is_sqlite else "NOW()"
    pk = "INTEGER PRIMARY KEY AUTOINCREMENT" if is_sqlite else "SERIAL PRIMARY KEY"
    bool_true = "1" if is_sqlite else "TRUE"
    bool_false = "0" if is_sqlite else "FALSE"
    with engine.begin() as conn:
        if not _table_exists(conn, "course_catalog_universities"):
            conn.execute(text(f"""
                CREATE TABLE course_catalog_universities (
                    id {pk},
                    country_code VARCHAR NOT NULL,
                    name VARCHAR NOT NULL,
                    name_key VARCHAR NOT NULL,
                    domain_key VARCHAR,
                    city VARCHAR,
                    qs_world_rank VARCHAR,
                    qs_rank_numeric INTEGER,
                    national_rank VARCHAR,
                    university_type VARCHAR,
                    website_url VARCHAR,
                    tuition_note VARCHAR,
                    summary TEXT,
                    scholarships_note TEXT,
                    seed_rank INTEGER,
                    is_active BOOLEAN NOT NULL DEFAULT {bool_true},
                    source_urls TEXT,
                    extra TEXT,
                    consecutive_failures INTEGER NOT NULL DEFAULT 0,
                    last_verified_at {ts},
                    created_at {ts} DEFAULT {now_default} NOT NULL,
                    updated_at {ts},
                    CONSTRAINT uq_course_catalog_uni_country_name UNIQUE (country_code, name_key)
                )
            """))
            for stmt in (
                "CREATE INDEX IF NOT EXISTS ix_course_catalog_universities_country_code ON course_catalog_universities(country_code)",
                "CREATE INDEX IF NOT EXISTS ix_course_catalog_universities_name_key ON course_catalog_universities(name_key)",
                "CREATE INDEX IF NOT EXISTS ix_course_catalog_universities_last_verified_at ON course_catalog_universities(last_verified_at)",
                "CREATE INDEX IF NOT EXISTS ix_course_catalog_uni_country_verified ON course_catalog_universities(country_code, last_verified_at)",
            ):
                conn.execute(text(stmt))

        # Added after launch: lets the refresh agent back off universities whose
        # enrichment keeps failing instead of burning the daily batch on them forever.
        uni_columns = _get_table_columns(conn, "course_catalog_universities")
        if "consecutive_failures" not in uni_columns:
            conn.execute(text(
                "ALTER TABLE course_catalog_universities ADD COLUMN consecutive_failures INTEGER NOT NULL DEFAULT 0"
            ))
        # Added 2026-07-26: domain-based identity. name_key alone let aliases of the
        # same university ("UNSW Sydney" vs "The University of New South Wales") both
        # insert; the official domain is stable, so it is the real dedup key.
        if "domain_key" not in uni_columns:
            conn.execute(text(
                "ALTER TABLE course_catalog_universities ADD COLUMN domain_key VARCHAR"
            ))
        # Added 2026-07-29: numeric rank behind the "within the top N" advanced filter
        # (qs_world_rank is a display string and can be a band like "301-350").
        if "qs_rank_numeric" not in uni_columns:
            conn.execute(text(
                "ALTER TABLE course_catalog_universities ADD COLUMN qs_rank_numeric INTEGER"
            ))
        for stmt in (
            "CREATE INDEX IF NOT EXISTS ix_course_catalog_universities_qs_rank_numeric ON course_catalog_universities(qs_rank_numeric)",
            "CREATE INDEX IF NOT EXISTS ix_course_catalog_universities_domain_key ON course_catalog_universities(domain_key)",
            # Partial unique: one row per (country, domain) once a domain is known,
            # while rows with an unknown domain stay exempt.
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_course_catalog_uni_country_domain "
            "ON course_catalog_universities(country_code, domain_key) WHERE domain_key IS NOT NULL",
        ):
            conn.execute(text(stmt))

        if not _table_exists(conn, "course_catalog_courses"):
            conn.execute(text(f"""
                CREATE TABLE course_catalog_courses (
                    id {pk},
                    university_id INTEGER NOT NULL REFERENCES course_catalog_universities(id) ON DELETE CASCADE,
                    country_code VARCHAR NOT NULL,
                    course_name VARCHAR NOT NULL,
                    name_key VARCHAR NOT NULL,
                    degree_level VARCHAR NOT NULL DEFAULT 'masters',
                    discipline VARCHAR,
                    duration VARCHAR,
                    annual_tuition VARCHAR,
                    tuition_amount INTEGER,
                    tuition_currency VARCHAR,
                    intakes TEXT,
                    application_deadline VARCHAR,
                    application_fee VARCHAR,
                    ielts_requirement VARCHAR,
                    toefl_requirement VARCHAR,
                    gre_gmat_requirement VARCHAR,
                    ielts_score FLOAT,
                    toefl_score INTEGER,
                    gre_gmat_required INTEGER,
                    duration_months INTEGER,
                    entry_requirements TEXT,
                    course_url VARCHAR,
                    is_active BOOLEAN NOT NULL DEFAULT {bool_true},
                    last_verified_at {ts},
                    created_at {ts} DEFAULT {now_default} NOT NULL,
                    updated_at {ts},
                    CONSTRAINT uq_course_catalog_course UNIQUE (university_id, name_key, degree_level)
                )
            """))
            for stmt in (
                "CREATE INDEX IF NOT EXISTS ix_course_catalog_courses_university_id ON course_catalog_courses(university_id)",
                "CREATE INDEX IF NOT EXISTS ix_course_catalog_courses_country_code ON course_catalog_courses(country_code)",
                "CREATE INDEX IF NOT EXISTS ix_course_catalog_courses_degree_level ON course_catalog_courses(degree_level)",
                "CREATE INDEX IF NOT EXISTS ix_course_catalog_courses_discipline ON course_catalog_courses(discipline)",
                "CREATE INDEX IF NOT EXISTS ix_course_catalog_course_country_level ON course_catalog_courses(country_code, degree_level)",
            ):
                conn.execute(text(stmt))

        # Added 2026-07-29: numeric columns behind the advanced browse filters. The
        # figures are published as free text ("6.5 overall (6.0 in each band)", "2 years",
        # "GRE optional"), and browse pages in SQL — so each one is parsed once on write
        # (course_catalog.apply_course_derived_fields) into something SQL can compare.
        course_columns = _get_table_columns(conn, "course_catalog_courses")
        for column, ddl_type in (
            ("ielts_score", "FLOAT"),
            ("toefl_score", "INTEGER"),
            ("gre_gmat_required", "INTEGER"),
            ("duration_months", "INTEGER"),
            # Parsed form of the free-text application_deadline, so read paths can hide a
            # deadline the moment it passes (a stored date that is valid today expires on
            # its own — only a read-time comparison catches that).
            ("application_deadline_date", "DATE"),
        ):
            if column not in course_columns:
                conn.execute(text(f"ALTER TABLE course_catalog_courses ADD COLUMN {column} {ddl_type}"))

        if not _table_exists(conn, "course_catalog_refresh_runs"):
            conn.execute(text(f"""
                CREATE TABLE course_catalog_refresh_runs (
                    id {pk},
                    run_date DATE NOT NULL UNIQUE,
                    status VARCHAR NOT NULL DEFAULT 'running',
                    started_at {ts} DEFAULT {now_default} NOT NULL,
                    completed_at {ts},
                    universities_discovered INTEGER NOT NULL DEFAULT 0,
                    universities_refreshed INTEGER NOT NULL DEFAULT 0,
                    courses_upserted INTEGER NOT NULL DEFAULT 0,
                    error_message TEXT,
                    detail TEXT
                )
            """))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_course_catalog_refresh_runs_run_date ON course_catalog_refresh_runs(run_date)"
            ))

        if not _table_exists(conn, "enterprise_course_finder_recs"):
            conn.execute(text(f"""
                CREATE TABLE enterprise_course_finder_recs (
                    id {pk},
                    organization_id INTEGER NOT NULL,
                    client_id INTEGER,
                    client_name VARCHAR,
                    country_code VARCHAR,
                    degree_level VARCHAR,
                    discipline VARCHAR,
                    query TEXT,
                    summary TEXT,
                    recommendations TEXT,
                    catalog_based BOOLEAN NOT NULL DEFAULT {bool_true},
                    grounded BOOLEAN NOT NULL DEFAULT {bool_false},
                    model_used VARCHAR,
                    credits_charged INTEGER NOT NULL DEFAULT 0,
                    created_by_user_id INTEGER,
                    created_by_name VARCHAR,
                    created_at {ts} DEFAULT {now_default} NOT NULL
                )
            """))
            for stmt in (
                "CREATE INDEX IF NOT EXISTS ix_enterprise_course_finder_recs_organization_id ON enterprise_course_finder_recs(organization_id)",
                "CREATE INDEX IF NOT EXISTS ix_enterprise_course_finder_recs_client_id ON enterprise_course_finder_recs(client_id)",
                "CREATE INDEX IF NOT EXISTS ix_enterprise_course_finder_recs_created_at ON enterprise_course_finder_recs(created_at)",
                "CREATE INDEX IF NOT EXISTS ix_ent_course_finder_recs_org_created ON enterprise_course_finder_recs(organization_id, created_at)",
            ):
                conn.execute(text(stmt))

        _backfill_course_catalog_derived_filters(conn)


def ensure_course_finder_b2c_schema():
    """B2C Course Finder (individual accounts): pass counter, richer shortlist columns,
    and the per-user stored-recommendations table. Additive and idempotent.

    Must run AFTER ensure_university_shortlist_table (it patches that table).
    """
    is_sqlite = engine.dialect.name == "sqlite"
    ts = "TIMESTAMP" if is_sqlite else "TIMESTAMPTZ"
    now_default = "CURRENT_TIMESTAMP" if is_sqlite else "NOW()"
    pk = "INTEGER PRIMARY KEY AUTOINCREMENT" if is_sqlite else "SERIAL PRIMARY KEY"
    bool_true = "1" if is_sqlite else "TRUE"
    bool_false = "0" if is_sqlite else "FALSE"
    with engine.begin() as conn:
        sub_columns = _get_table_columns(conn, "subscriptions")
        if "course_finder_runs_used" not in sub_columns:
            conn.execute(text(
                "ALTER TABLE subscriptions ADD COLUMN course_finder_runs_used INTEGER NOT NULL DEFAULT 0"
            ))

        # AI metadata parity with enterprise_client_universities: before these columns,
        # saving an AI recommendation dropped its ranks/fees/URLs/requirements.
        entry_columns = _get_table_columns(conn, "university_shortlist_entries")
        for col, ddl_type in (
            ("qs_world_rank", "VARCHAR"),
            ("country_rank", "VARCHAR"),
            ("admission_difficulty", "VARCHAR"),
            ("key_requirements", "TEXT"),
            ("application_fee", "VARCHAR"),
            ("website_url", "VARCHAR"),
            ("admissions_url", "VARCHAR"),
        ):
            if col not in entry_columns:
                conn.execute(text(
                    f"ALTER TABLE university_shortlist_entries ADD COLUMN {col} {ddl_type}"
                ))

        if not _table_exists(conn, "user_course_finder_recs"):
            conn.execute(text(f"""
                CREATE TABLE user_course_finder_recs (
                    id {pk},
                    user_id INTEGER NOT NULL,
                    country_code VARCHAR,
                    degree_level VARCHAR,
                    discipline VARCHAR,
                    query TEXT,
                    summary TEXT,
                    recommendations TEXT,
                    catalog_based BOOLEAN NOT NULL DEFAULT {bool_true},
                    grounded BOOLEAN NOT NULL DEFAULT {bool_false},
                    model_used VARCHAR,
                    created_at {ts} DEFAULT {now_default} NOT NULL
                )
            """))
            for stmt in (
                "CREATE INDEX IF NOT EXISTS ix_user_course_finder_recs_user_id ON user_course_finder_recs(user_id)",
                "CREATE INDEX IF NOT EXISTS ix_user_course_finder_recs_created_at ON user_course_finder_recs(created_at)",
                "CREATE INDEX IF NOT EXISTS ix_user_course_finder_recs_user_created ON user_course_finder_recs(user_id, created_at)",
            ):
                conn.execute(text(stmt))


def _backfill_course_catalog_derived_filters(conn):
    """One-time fill of the derived filter columns for catalog rows written before those
    columns existed.

    Every later write keeps itself in sync (the agent calls
    course_catalog.apply_course_derived_fields / parse_rank_number on each upsert), so
    this is guarded by an app_data_migrations marker and runs exactly once per database —
    a re-run on every boot would re-parse the whole catalog for no gain.
    """
    conn.execute(text(
        "CREATE TABLE IF NOT EXISTS app_data_migrations ("
        "migration_key VARCHAR PRIMARY KEY, "
        "applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL)"
    ))
    marker = "course_catalog_derived_filters_v1"
    if conn.execute(
        text("SELECT 1 FROM app_data_migrations WHERE migration_key = :k"),
        {"k": marker},
    ).fetchone():
        return

    # Local import: the parsers live with the agent that writes these columns, so the
    # backfill and every future write can never drift apart.
    from app import course_catalog

    course_rows = conn.execute(text(
        "SELECT id, ielts_requirement, toefl_requirement, gre_gmat_requirement, duration "
        "FROM course_catalog_courses"
    )).fetchall()
    for row in course_rows:
        values = {
            "i": course_catalog.parse_ielts_band(row[1]),
            "t": course_catalog.parse_toefl_score(row[2]),
            "g": course_catalog.parse_gre_requirement(row[3]),
            "d": course_catalog.parse_duration_months(row[4]),
        }
        if all(v is None for v in values.values()):
            continue  # nothing parseable — leave the row's columns NULL
        conn.execute(
            text(
                "UPDATE course_catalog_courses SET ielts_score = :i, toefl_score = :t, "
                "gre_gmat_required = :g, duration_months = :d WHERE id = :id"
            ),
            {**values, "id": row[0]},
        )

    uni_rows = conn.execute(text(
        "SELECT id, qs_world_rank FROM course_catalog_universities WHERE qs_world_rank IS NOT NULL"
    )).fetchall()
    for row in uni_rows:
        rank = course_catalog.parse_rank_number(row[1])
        if rank is None:
            continue
        conn.execute(
            text("UPDATE course_catalog_universities SET qs_rank_numeric = :r WHERE id = :id"),
            {"r": rank, "id": row[0]},
        )

    conn.execute(
        text("INSERT INTO app_data_migrations (migration_key) VALUES (:k)"),
        {"k": marker},
    )


def ensure_international_payment_columns():
    """Multi-currency settlement columns on the payment tables.

    Rilono now charges in more than INR (see app/money.py). Two facts follow:

      1. `amount_paise` is in the minor unit of that row's `currency`, so it can no
         longer be summed across rows. Revenue must sum the INR settlement figure
         Razorpay reports as `base_amount` — stored here as `base_amount_paise`.
      2. Whether a card was foreign is not derivable from the amount, but it changes
         both the cost of collection (~3% + GST vs ~2% domestic) and the GST
         export-of-services treatment. Hence `is_international`.

    Includes a ONE-TIME BACKFILL setting base_amount_paise = amount_paise for existing
    rows. That is trivially correct today *because every historical row is genuinely
    INR* — every write site stamped INR and every table defaults to it. It will never be
    true again, so this must run before the first non-INR order can be created. It is
    guarded on `base_amount_paise IS NULL` and on currency, so it is idempotent and can
    never touch a real foreign-currency row.
    """
    is_sqlite = engine.dialect.name == "sqlite"
    bool_false = "0" if is_sqlite else "FALSE"

    # (table, wants_full_settlement_set)
    # Route-collected rows (enterprise_student_payments) are INR-only because Razorpay
    # Route rejects non-INR transfers, so charged == settled there and only the
    # international-card flag is meaningful.
    targets = [
        ("subscription_payments", True),
        ("enterprise_credit_payments", True),
        ("enterprise_student_payments", False),
    ]

    with engine.begin() as conn:
        # Sticky per-org billing currency for Rilono's own charges (credit top-ups,
        # infra fee). NULL = not yet chosen -> fall back to country, then INR.
        if _table_exists(conn, "enterprise_organizations"):
            org_columns = _get_table_columns(conn, "enterprise_organizations")
            if "billing_currency" not in org_columns:
                conn.execute(text(
                    "ALTER TABLE enterprise_organizations ADD COLUMN billing_currency VARCHAR"
                ))

        for table, full_set in targets:
            if not _table_exists(conn, table):
                continue
            columns = _get_table_columns(conn, table)

            if "is_international" not in columns:
                conn.execute(text(
                    f"ALTER TABLE {table} ADD COLUMN is_international BOOLEAN NOT NULL "
                    f"DEFAULT {bool_false}"
                ))

            if not full_set:
                # Route-collected rows: also snapshot the payer's phone. Razorpay hard-fails
                # an international card payment when Checkout is given placeholder contact
                # details, and the pay page had no phone to send at all.
                if table == "enterprise_student_payments" and "payer_phone_snapshot" not in columns:
                    conn.execute(text(
                        f"ALTER TABLE {table} ADD COLUMN payer_phone_snapshot VARCHAR"
                    ))
                continue

            if "base_amount_paise" not in columns:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN base_amount_paise INTEGER"))
            if "base_currency" not in columns:
                conn.execute(text(
                    f"ALTER TABLE {table} ADD COLUMN base_currency VARCHAR NOT NULL DEFAULT 'INR'"
                ))
            if "fx_rate_used" not in columns:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN fx_rate_used NUMERIC(18,6)"))
            if "price_book_version" not in columns:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN price_book_version VARCHAR"))

            # Backfill: historical rows are all INR, so charged == settled.
            conn.execute(text(
                f"UPDATE {table} SET base_amount_paise = amount_paise "
                f"WHERE base_amount_paise IS NULL "
                f"AND (currency IS NULL OR UPPER(currency) = 'INR')"
            ))


def ensure_enterprise_lead_tables():
    """Create the lead-collection tables: org-branded public forms (raw shareable
    public_token — the link is public-by-design and must be re-copyable), the
    per-org leads inbox fed by anonymous submissions, and the files those
    submissions attach (staged before the lead exists, swept if abandoned).
    Indexes are created OUTSIDE
    the table-exists guard because Base.metadata.create_all() may have built the
    tables from the models on an earlier boot. Idempotent and additive — safe to
    run on every startup."""
    is_sqlite = engine.dialect.name == "sqlite"
    ts = "TIMESTAMP" if is_sqlite else "TIMESTAMPTZ"
    now_default = "CURRENT_TIMESTAMP" if is_sqlite else "NOW()"
    pk = "INTEGER PRIMARY KEY AUTOINCREMENT" if is_sqlite else "SERIAL PRIMARY KEY"
    bool_true = "1" if is_sqlite else "TRUE"
    with engine.begin() as conn:
        if not _table_exists(conn, "enterprise_lead_forms"):
            conn.execute(text(f"""
                CREATE TABLE enterprise_lead_forms (
                    id {pk},
                    organization_id INTEGER NOT NULL,
                    name VARCHAR NOT NULL,
                    title VARCHAR,
                    intro_text TEXT,
                    fields_json TEXT NOT NULL,
                    public_token VARCHAR NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT {bool_true},
                    submit_label VARCHAR,
                    success_message VARCHAR,
                    notify_email VARCHAR,
                    created_by_user_id INTEGER REFERENCES users(id),
                    created_by_name VARCHAR,
                    created_at {ts} DEFAULT {now_default} NOT NULL,
                    updated_at {ts},
                    FOREIGN KEY (organization_id) REFERENCES enterprise_organizations(id)
                )
            """))
        if not _table_exists(conn, "enterprise_leads"):
            conn.execute(text(f"""
                CREATE TABLE enterprise_leads (
                    id {pk},
                    organization_id INTEGER NOT NULL,
                    form_id INTEGER,
                    form_name VARCHAR,
                    full_name VARCHAR,
                    email VARCHAR,
                    phone VARCHAR,
                    answers_json TEXT NOT NULL,
                    status VARCHAR NOT NULL DEFAULT 'new',
                    converted_client_id INTEGER,
                    ip_address VARCHAR,
                    source VARCHAR,
                    created_at {ts} DEFAULT {now_default} NOT NULL,
                    updated_at {ts},
                    FOREIGN KEY (organization_id) REFERENCES enterprise_organizations(id),
                    FOREIGN KEY (form_id) REFERENCES enterprise_lead_forms(id) ON DELETE SET NULL,
                    FOREIGN KEY (converted_client_id) REFERENCES enterprise_clients(id) ON DELETE SET NULL
                )
            """))
        if not _table_exists(conn, "enterprise_lead_uploads"):
            conn.execute(text(f"""
                CREATE TABLE enterprise_lead_uploads (
                    id {pk},
                    organization_id INTEGER NOT NULL,
                    form_id INTEGER,
                    lead_id INTEGER,
                    field_key VARCHAR NOT NULL,
                    field_label VARCHAR,
                    upload_token VARCHAR NOT NULL,
                    original_filename VARCHAR NOT NULL,
                    storage_key VARCHAR NOT NULL,
                    file_size INTEGER,
                    mime_type VARCHAR,
                    ip_address VARCHAR,
                    converted_document_id INTEGER,
                    created_at {ts} DEFAULT {now_default} NOT NULL,
                    FOREIGN KEY (organization_id) REFERENCES enterprise_organizations(id),
                    FOREIGN KEY (form_id) REFERENCES enterprise_lead_forms(id) ON DELETE SET NULL,
                    FOREIGN KEY (lead_id) REFERENCES enterprise_leads(id) ON DELETE CASCADE
                )
            """))
        # Index names match what create_all() derives from the models, so a table built
        # either way ends up with exactly one copy of each index (a differently-named
        # unique index here would leave prod maintaining two identical ones forever).
        for stmt in (
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_enterprise_lead_forms_public_token ON enterprise_lead_forms(public_token)",
            "CREATE INDEX IF NOT EXISTS ix_enterprise_lead_forms_organization_id ON enterprise_lead_forms(organization_id)",
            "CREATE INDEX IF NOT EXISTS ix_enterprise_lead_forms_created_by_user_id ON enterprise_lead_forms(created_by_user_id)",
            "CREATE INDEX IF NOT EXISTS ix_ent_lead_forms_org_created ON enterprise_lead_forms(organization_id, created_at)",
            "CREATE INDEX IF NOT EXISTS ix_enterprise_leads_organization_id ON enterprise_leads(organization_id)",
            "CREATE INDEX IF NOT EXISTS ix_enterprise_leads_form_id ON enterprise_leads(form_id)",
            "CREATE INDEX IF NOT EXISTS ix_enterprise_leads_status ON enterprise_leads(status)",
            "CREATE INDEX IF NOT EXISTS ix_enterprise_leads_converted_client_id ON enterprise_leads(converted_client_id)",
            "CREATE INDEX IF NOT EXISTS ix_enterprise_leads_created_at ON enterprise_leads(created_at)",
            "CREATE INDEX IF NOT EXISTS ix_ent_leads_org_created ON enterprise_leads(organization_id, created_at)",
            "CREATE INDEX IF NOT EXISTS ix_ent_leads_org_status ON enterprise_leads(organization_id, status)",
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_enterprise_lead_uploads_upload_token ON enterprise_lead_uploads(upload_token)",
            "CREATE INDEX IF NOT EXISTS ix_enterprise_lead_uploads_organization_id ON enterprise_lead_uploads(organization_id)",
            "CREATE INDEX IF NOT EXISTS ix_enterprise_lead_uploads_form_id ON enterprise_lead_uploads(form_id)",
            "CREATE INDEX IF NOT EXISTS ix_enterprise_lead_uploads_lead_id ON enterprise_lead_uploads(lead_id)",
            "CREATE INDEX IF NOT EXISTS ix_enterprise_lead_uploads_created_at ON enterprise_lead_uploads(created_at)",
            "CREATE INDEX IF NOT EXISTS ix_ent_lead_uploads_lead ON enterprise_lead_uploads(lead_id, id)",
            "CREATE INDEX IF NOT EXISTS ix_ent_lead_uploads_staged ON enterprise_lead_uploads(form_id, lead_id, created_at)",
            # Retire the first-cut name so no DB keeps two identical unique indexes.
            "DROP INDEX IF EXISTS uq_enterprise_lead_forms_token",
        ):
            conn.execute(text(stmt))
