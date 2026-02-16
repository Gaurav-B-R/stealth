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
