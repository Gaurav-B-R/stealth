"""Accounting scope, lifetime history, exports and admin-only billing reconciliation."""
import csv
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from io import StringIO
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import ai_billing, ai_cost_reporting as reports, ai_usage, models, visa_pass
from app.database import Base, get_db
from app.admin_sessions import get_current_console_user
from app.routers import admin
from app.services import ai_billing_sync

START, END = date(2026, 8, 1), date(2026, 8, 31)


@pytest.fixture
def db(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    monkeypatch.setenv("AI_USAGE_SPOOL_DIR", str(tmp_path / "spool"))
    for key in ["AI_BILLING_BIGQUERY_TABLE", "AI_BILLING_USAGE_PROJECT", "AI_BILLING_QUERY_PROJECT", "AI_BILLING_SERVICE_NAMES"]:
        monkeypatch.delenv(key, raising=False)
    for uid in range(1, 4):
        session.add(models.User(id=uid, email=f"student{uid}@example.com", full_name=f"Student {uid}",
                                hashed_password="test", is_enterprise_account=uid == 3))
    session.commit()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture(autouse=True)
def credit_breakdown_stub(monkeypatch):
    """Sync tests stub query_export; the credit-name query is stubbed empty unless a test overrides it."""
    original = ai_billing.query_credit_breakdown
    monkeypatch.setattr(ai_billing, "query_credit_breakdown", lambda cfg, start, end, *, client=None, as_of=None: [])
    return original


def credit_row(**changes):
    data = {"usage_date": "2026-08-03", "currency": "USD", "credit_type": "PROMOTION", "credit_name": "FreeTrial:Credit-1",
            "credit_id": "FreeTrial:Credit-1", "credit_full_name": "Free Trial", "amount": "-0.5"}
    data.update(changes)
    return data


def event(db, **changes):
    data = dict(user_id=1, source="student_ai_chat", model="gemini-2.5-flash", product="b2c",
                metering_version=2, usage_state="measured", pricing_status="estimated", provider="vertex",
                project_id="test-project", prompt_tokens=100, candidate_tokens=30, thought_tokens=20,
                output_tokens=50, cached_tokens=40, total_tokens=150, estimated_cost_usd=Decimal("1"),
                created_at=datetime(2026, 8, 3))
    data.update(changes)
    row = models.GeminiUsageEvent(**data)
    db.add(row)
    db.commit()
    return row


def test_profile_range_lifetime_feature_and_product_scope(db):
    event(db)
    event(db, source="student_mock_interview", total_tokens=300, created_at=datetime(2026, 7, 1))
    event(db, source="enterprise_copilot", organization_id=9, product="b2b", total_tokens=9999)
    event(db, source="course_catalog_refresh", user_id=None, product="shared", total_tokens=400)
    event(db, source="unknown", user_id=None, product="unknown", total_tokens=500)
    data = reports.build_profiles(db, start=START, end=END)
    # Profile 2 has no usage in the selected dates and the enterprise-origin profile is excluded.
    assert data["total"] == 1
    row = data["profiles"][0]
    assert row["range"]["total_tokens"] == 150
    assert row["lifetime"]["total_tokens"] == 450
    assert row["range"]["output_tokens"] == 30
    assert row["range"]["thinking_tokens"] == 20
    assert data["coverage"]["shared"]["total_tokens"] == 400
    assert data["coverage"]["unattributed"]["total_tokens"] == 500
    detail = reports.build_profile_detail(db, 1, start=START, end=END)
    assert [r["source"] for r in detail["features"]] == ["student_ai_chat", "student_mock_interview"]
    assert detail["features"][1]["range"]["calls"] == 0
    assert detail["features"][1]["lifetime"]["calls"] == 1
    assert reports.build_profile_detail(db, 3, start=START, end=END) is None


def test_legacy_ambiguous_profile_usage_stays_unclassified(db):
    event(db, source="enterprise_copilot", product="unknown", organization_id=None,
          metering_version=1, usage_state="legacy")
    event(db, source="document_ai", product="unknown", organization_id=None,
          metering_version=1, usage_state="legacy")
    data = reports.build_profiles(db, start=START, end=END)
    # Unclassified usage never puts a profile in the table; it only shows in coverage.
    assert data["profiles"] == []
    assert data["coverage"]["unattributed"]["calls"] == 2
    assert data["coverage"]["first_recorded_at"] is None


def test_legacy_and_unknown_not_claimed_complete_tts_not_tokens(db):
    event(db, usage_state="legacy", metering_version=1, pricing_status="legacy_estimate", product="unknown")
    event(db, usage_state="unknown", pricing_status="unpriced", total_tokens=0, prompt_tokens=0, output_tokens=0)
    event(db, model="gcp-tts/en-US-Neural2-D", unit_type="characters", character_count=600,
          total_tokens=0, prompt_tokens=0, output_tokens=0, candidate_tokens=0, thought_tokens=0)
    result = reports.build_profiles(db, start=START, end=END)
    value = result["profiles"][0]["range"]
    assert value["total_tokens"] == 150
    assert value["tts_characters"] == 600
    assert (value["legacy_calls"], value["unknown_calls"]) == (1, 1)
    assert value["unpriced_calls"] >= 1
    assert value["billed_cost_usd"] == 0
    assert value["billed_cost_available"] is False
    assert "not guaranteed" in result["coverage"]["note"]


def test_export_all_pages_literal_search_and_spreadsheet_safety(db):
    first = db.get(models.User, 1)
    first.full_name = "=HYPERLINK(\"https://example.com\")"
    for uid in range(10, 277):
        db.add(models.User(id=uid, email=f"student{uid}@example.com", full_name="Student", hashed_password="test"))
    db.commit()
    # Only profiles with usage in the selected dates are exported, so give every B2C profile one call.
    for uid in [1, 2, *range(10, 277)]:
        event(db, user_id=uid)
    assert reports.build_profiles(db, start=START, end=END, page_size=1)["total"] == 269
    rows = list(csv.DictReader(StringIO(reports.profiles_csv(db, start=START, end=END).lstrip("\ufeff"))))
    assert len(rows) == 269
    assert rows[0]["Name"].startswith("'=")
    assert reports.build_profiles(db, search="%", start=START, end=END)["total"] == 0
    assert reports.build_profiles(db, search="student2@", start=START, end=END)["total"] == 1


def test_b2c_revenue_includes_personal_automation_and_excludes_organization(db):
    event(db, source="daily_ai_notifier", estimated_cost_usd=2)
    event(db, source="sop_generator", estimated_cost_usd=3)
    event(db, source="document_ai", estimated_cost_usd=4)
    event(db, source="document_ai", product="b2b", organization_id=9, estimated_cost_usd=99)
    event(db, source="course_catalog_refresh", user_id=None, product="shared", estimated_cost_usd=50)
    cost, _ = visa_pass._b2c_gemini_cost_usd(db)
    assert cost == 9


def configured(monkeypatch):
    monkeypatch.setenv("AI_BILLING_BIGQUERY_TABLE", "billing-project.billing.gcp_billing_export_v1_test")
    monkeypatch.setenv("AI_BILLING_USAGE_PROJECT", "test-project")


def google_row(**changes):
    row = dict(usage_date="2026-08-03", service="Vertex AI", sku_id="sku-input", sku="Input tokens",
               unit="count", currency="INR", currency_conversion_rate="80", invoice_month="202608",
               cost_type="regular", usage_amount="150", cost="80", credits="-40")
    row.update(changes)
    return row


def test_google_reconciliation_currency_credits_corrections_and_no_double_import(db, monkeypatch):
    configured(monkeypatch)
    event(db)
    provider_rows = [google_row()]
    monkeypatch.setattr(ai_billing, "query_export", lambda *a, **k: provider_rows)
    first = ai_billing.sync_billing(db, start=START, end=END)
    assert first["totals"] == [dict(currency="INR", cost="80", credits="-40", net_cost="40")]
    assert first["google_cost_usd"] == 1
    assert first["google_credits_usd"] == -0.5
    assert first["google_net_cost_usd"] == 0.5
    assert first["google_cost_available"] is True
    assert first["billing_status"] == "available"
    assert "difference_usd" not in first
    assert "app_estimated_cost_usd" not in first
    assert first["usage_rows"][0]["unit"] == "count"
    # Re-fetching replaces the range; appended Google corrections are included once.
    provider_rows.append(google_row(cost="-8", credits="0", usage_amount="-15", cost_type="adjustment"))
    ai_billing.sync_billing(db, start=START, end=END)
    third = ai_billing.sync_billing(db, start=START, end=END)
    assert db.query(ai_billing.AiBillingSnapshot).count() == 1
    assert third["google_cost_usd"] == 0.9
    assert third["google_net_cost_usd"] == 0.4
    assert third["billing_status"] == "available"
    assert db.query(models.GeminiUsageEvent).one().total_tokens == 150  # never rescale user tokens


def test_no_export_and_unknown_history_do_not_claim_zero_bill(db, monkeypatch):
    disconnected = ai_billing.build_reconciliation(db, start=START, end=END)
    assert disconnected["google_cost_usd"] == 0
    assert disconnected["google_cost_available"] is False
    assert disconnected["billing_status"] == "not_configured"
    configured(monkeypatch)
    event(db, project_id=None, metering_version=1, usage_state="legacy")
    monkeypatch.setattr(ai_billing, "query_export", lambda *a, **k: [])
    data = ai_billing.sync_billing(db, start=START, end=END)
    assert data["google_cost_usd"] == 0
    assert data["google_cost_available"] is False
    assert data["billing_status"] == "no_records"
    assert data["metering_status"] == "incomplete"


def test_billing_service_filter_matches_application_provider_scope(db, monkeypatch):
    configured(monkeypatch)
    monkeypatch.setenv("AI_BILLING_SERVICE_NAMES", "Vertex AI")
    event(db, estimated_cost_usd=1)
    event(db, model="gcp-tts/voice", provider="google_cloud_tts", estimated_cost_usd=99)
    monkeypatch.setattr(ai_billing, "query_export", lambda *a, **k: [google_row()])
    result = ai_billing.sync_billing(db, start=START, end=END)
    assert result["coverage"]["calls"] == 1
    assert result["coverage"]["total_tokens"] == 150
    assert "estimated_cost_usd" not in result["coverage"]
    assert "unpriced_calls" not in result["coverage"]


def test_daily_worker_disabled_by_default_and_claims_once_across_sessions(db, monkeypatch):
    configured(monkeypatch)
    monkeypatch.delenv("AI_BILLING_SYNC_ENABLED", raising=False)
    calls = []
    monkeypatch.setattr(ai_billing, "sync_billing", lambda *args, **kwargs: calls.append(kwargs))
    now = datetime(2026, 9, 6)
    assert ai_billing_sync.run_once(db, now=now) is False
    monkeypatch.setenv("AI_BILLING_SYNC_ENABLED", "true")
    assert ai_billing_sync.run_once(db, now=now) is True
    with sessionmaker(bind=db.bind)() as worker2:
        assert ai_billing_sync.run_once(worker2, now=now) is False
    assert len(calls) == 3
    assert {r["start"] for r in calls} == {date(2026, 8, 8), date(2026, 8, 1), date(2026, 9, 1)}


def test_failed_sync_keeps_previous_snapshot_and_validates_identifier(db, monkeypatch):
    configured(monkeypatch)
    monkeypatch.setattr(ai_billing, "query_export", lambda *a, **k: [google_row()])
    first = ai_billing.sync_billing(db, start=START, end=END)
    def failure(*args, **kwargs):
        raise RuntimeError("SECRET_NOT_FOR_BROWSER")
    monkeypatch.setattr(ai_billing, "query_export", failure)
    with pytest.raises(ai_billing.BillingSyncError) as exc:
        ai_billing.sync_billing(db, start=START, end=END)
    assert "SECRET" not in str(exc.value)
    assert ai_billing.build_reconciliation(db, start=START, end=END)["last_synced_at"] == first["last_synced_at"]
    monkeypatch.setenv("AI_BILLING_BIGQUERY_TABLE", "x.y.z`; DELETE FROM foo --")
    with pytest.raises(ai_billing.BillingConfigurationError):
        ai_billing.configuration()


def test_bigquery_query_is_bounded_parameterized_and_reads_all_result_pages(monkeypatch):
    configured(monkeypatch)
    captured = {}
    class Client:
        def query(self, sql, **kwargs):
            captured.update(sql=sql, **kwargs)
            return SimpleNamespace(result=lambda timeout: iter([google_row(), google_row(currency="USD")]))
    rows = ai_billing.query_export(ai_billing.configuration(), START, END, client=Client())
    assert len(rows) == 2
    assert "@usage_project" in captured["sql"]
    assert "@services" in captured["sql"]
    assert captured["job_config"].maximum_bytes_billed == 1000000000
    assert captured["job_config"].query_parameters[2].value == "test-project"


def test_admin_endpoints_enforce_access_validate_dates_and_do_not_cache(db, monkeypatch):
    application = FastAPI()
    application.include_router(admin.router)
    actor = models.User(id=9000, email="admin@example.com", is_admin=True, is_active=True, email_verified=True)
    application.dependency_overrides[get_db] = lambda: db
    application.dependency_overrides[get_current_console_user] = lambda: actor
    monkeypatch.setattr(admin, "_is_admin_turnstile_required", lambda request: False)
    monkeypatch.setattr(admin, "check_ip_rate_limit", lambda **kwargs: (True, 0))
    with TestClient(application) as client:
        r = client.get("/api/admin/ai-usage/profiles", params={"start": str(START), "end": str(END)})
        assert r.status_code == 200, r.text
        assert r.headers["cache-control"] == "no-store"
        usage = client.get("/api/admin/ai-usage/analytics")
        assert usage.status_code == 200
        assert usage.headers["cache-control"] == "no-store"
        assert "estimated_cost_usd" not in usage.text
        assert "calculated_cost_usd" in usage.text
        assert "is_estimate" not in usage.text
        assert client.get("/api/admin/ai-usage/profiles/export").status_code == 200
        accounts = client.get("/api/admin/ai-usage/accounts", params={"start": str(START), "end": str(END)})
        assert accounts.status_code == 200, accounts.text
        assert accounts.headers["cache-control"] == "no-store"
        assert [b["key"] for b in accounts.json()["buckets"]] == ["b2c", "b2b", "shared", "unattributed"]
        export = client.get("/api/admin/ai-usage/accounts/export", params={"start": str(START), "end": str(END)})
        assert export.status_code == 200 and export.headers["content-type"].startswith("text/csv")
        assert "Ledger total" in export.text
        assert client.get("/api/admin/ai-usage/accounts?start=bad").status_code in (400, 422)
        assert client.get("/api/admin/ai-usage/profiles/3").status_code == 404
        assert client.get("/api/admin/ai-usage/profiles?start=bad").status_code in (400, 422)
        assert client.post("/api/admin/ai-usage/reconciliation/sync", json={"start": 9}).status_code == 422
        assert client.post("/api/admin/ai-usage/reconciliation/sync", json={}).status_code == 409
        actor.is_admin = False
        for path in ["profiles", "profiles/export", "profiles/1", "reconciliation"]:
            assert client.get("/api/admin/ai-usage/" + path).status_code == 403
        assert client.post("/api/admin/ai-usage/reconciliation/sync", json={}).status_code == 403


def test_profile_reports_never_expose_stored_estimates_or_allocate_project_bill(db, monkeypatch):
    event(db, estimated_cost_usd=999999)
    configured(monkeypatch)
    monkeypatch.setattr(ai_billing, "query_export", lambda *a, **k: [google_row(cost="800")])
    ai_billing.sync_billing(db, start=START, end=END)
    data = reports.build_profile_detail(db, 1, start=START, end=END)
    for value in [data["range_totals"], data["lifetime_totals"], data["features"][0]["range"]]:
        assert value["billed_cost_usd"] == 0
        assert value["billed_cost_available"] is False
        assert value["billed_cost_status"] == "not_attributable"
        assert "estimated_cost_usd" not in value
    output = reports.profiles_csv(db, start=START, end=END)
    assert "estimated" not in output
    assert "999999" not in output
    assert "billed_cost_status" in output
    assert "not_attributable" in output


def test_imported_zero_differs_from_no_records_and_missing_currency_rate(db, monkeypatch):
    configured(monkeypatch)
    not_synced = ai_billing.build_reconciliation(db, start=START, end=END)
    assert not_synced["google_cost_usd"] == 0
    assert not_synced["billing_status"] == "not_synced"
    assert not_synced["google_cost_available"] is False
    provider_rows = [google_row(cost="0", credits="0")]
    monkeypatch.setattr(ai_billing, "query_export", lambda *a, **k: provider_rows)
    zero = ai_billing.sync_billing(db, start=START, end=END)
    assert zero["google_cost_usd"] == 0
    assert zero["google_cost_available"] is True
    assert zero["billing_status"] == "available"
    provider_rows[:] = [google_row(currency_conversion_rate=None)]
    missing_rate = ai_billing.sync_billing(db, start=START, end=END)
    assert missing_rate["google_cost_usd"] == 0
    assert missing_rate["google_cost_available"] is False
    assert missing_rate["billing_data_available"] is True
    assert missing_rate["billing_status"] == "currency_unavailable"
    assert missing_rate["totals"][0]["cost"] == "80"


def test_legacy_admin_analytics_never_expose_stored_estimates(db):
    event(db, estimated_cost_usd=999999, search_cost_usd=222222, search_queries=3)
    data = reports.recorded_usage_analytics(db, start=START, end=END)
    assert data["range"]["tokens"] == 150
    assert data["range"]["search_queries"] == 3
    assert data["range"]["top_day"] == {"date": "2026-08-03", "tokens": 150}
    def assert_no_stored_estimates(value):
        if isinstance(value, dict):
            for key, item in value.items():
                assert key not in ("cost_usd", "token_cost_usd", "search_cost_usd", "other_cost_usd", "estimated_cost_usd")
                assert not any(word in key for word in ("saved", "estimate", "pricing")), key
                assert_no_stored_estimates(item)
        elif isinstance(value, list):
            for item in value:
                assert_no_stored_estimates(item)
    assert_no_stored_estimates(data)
    assert data["range"]["calculated_cost_usd"] == "0"
    assert data["range"]["calculated_cost_status"] == "unavailable"
    assert data["by_source"][0]["tokens"] == 150


def test_revenue_unknown_billed_cost_never_claims_profit(db, monkeypatch):
    from app import fx
    monkeypatch.setattr(fx, "get_state", lambda: {"rate": 80, "source": "test"})
    event(db, estimated_cost_usd=100)
    data = reports.recorded_b2c_revenue(visa_pass.build_revenue_analytics(db))
    assert data["summary"]["gemini_cost_usd"] == 0
    assert data["summary"]["gross_margin_paise"] == 0
    assert data["summary"]["margin_available"] is False
    assert data["summary"]["billed_cost_available"] is False
    assert "is_estimate" not in data
    assert "pricing_note" not in data
    assert "target_profit_paise" not in data["pass"]
    accounts = reports.recorded_b2c_accounts(visa_pass.build_account_cost_profit(db))
    assert accounts["accounts"][0]["gemini_cost_paise"] == 0
    assert accounts["accounts"][0]["profit_paise"] == 0
    assert accounts["accounts"][0]["profit_available"] is False
    assert "usd_to_inr" not in accounts


def test_guardrail_counts_do_not_expose_hypothetical_saved_tokens_or_money(db):
    db.add(models.AiOptimizationEvent(kind="guardrail_block", source="student_ai_chat", tokens_saved=10000, cost_saved_usd=20))
    db.commit()
    result = reports.recorded_optimization_counts(db)
    assert result["guardrail"] == {"count": 1}
    assert "tokens_saved" not in str(result)
    assert "cost_saved" not in str(result)


def test_billing_export_pending_keeps_previous_snapshot_and_does_not_create_empty_one(db, monkeypatch):
    from google.api_core.exceptions import NotFound
    configured(monkeypatch)
    def not_yet_exported(*args, **kwargs):
        raise NotFound("SECRET table is unavailable")
    monkeypatch.setattr(ai_billing, "query_export", not_yet_exported)
    with pytest.raises(ai_billing.BillingExportPending) as exc:
        ai_billing.sync_billing(db, start=START, end=END)
    assert "SECRET" not in str(exc.value)
    assert db.query(ai_billing.AiBillingSnapshot).count() == 0
    assert ai_billing.build_reconciliation(db, start=START, end=END)["last_synced_at"] is None
    monkeypatch.setattr(ai_billing, "query_export", lambda *args, **kwargs: [google_row()])
    previous = ai_billing.sync_billing(db, start=START, end=END)
    monkeypatch.setattr(ai_billing, "query_export", not_yet_exported)
    with pytest.raises(ai_billing.BillingExportPending):
        ai_billing.sync_billing(db, start=START, end=END)
    retained = ai_billing.build_reconciliation(db, start=START, end=END)
    assert retained["last_synced_at"] == previous["last_synced_at"]
    assert retained["totals"] == previous["totals"]


def test_sync_endpoint_reports_pending_export_without_claiming_success(db, monkeypatch):
    from google.api_core.exceptions import NotFound
    configured(monkeypatch)
    application = FastAPI()
    application.include_router(admin.router)
    actor = models.User(id=9000, email="admin@example.com", is_admin=True, is_active=True, email_verified=True)
    application.dependency_overrides[get_db] = lambda: db
    application.dependency_overrides[get_current_console_user] = lambda: actor
    monkeypatch.setattr(admin, "_is_admin_turnstile_required", lambda request: False)
    monkeypatch.setattr(admin, "check_ip_rate_limit", lambda **kwargs: (True, 0))
    def not_yet_exported(*args, **kwargs):
        raise NotFound("No export table")
    monkeypatch.setattr(ai_billing, "query_export", not_yet_exported)
    with TestClient(application) as client:
        response = client.post("/api/admin/ai-usage/reconciliation/sync", json={"start": str(START), "end": str(END)})
        assert response.status_code == 202
        data = response.json()
        assert data["sync_status"] == data["billing_status"] == "awaiting_export"
        assert data["google_cost_usd"] == 0
        assert data["google_cost_available"] is False
        assert data["last_synced_at"] is None
        assert data["totals"] == []
        assert db.query(ai_billing.AiBillingSnapshot).count() == 0
        monkeypatch.setattr(ai_billing, "query_export", lambda *args, **kwargs: [google_row()])
        previous = ai_billing.sync_billing(db, start=START, end=END)
        monkeypatch.setattr(ai_billing, "query_export", not_yet_exported)
        response = client.post("/api/admin/ai-usage/reconciliation/sync", json={"start": str(START), "end": str(END)})
        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "available"
        assert data["sync_status"] == "awaiting_export"
        assert data["last_synced_at"] == previous["last_synced_at"]
        assert data["totals"] == previous["totals"]


def test_google_numeric_money_and_usage_precision_survives_json(db, monkeypatch):
    configured(monkeypatch)
    # Values deliberately exceed both JavaScript's integer precision and Decimal's default precision.
    provider_rows = [google_row(currency="USD", currency_conversion_rate="1", cost="12345678901234567890123456789.123456789",
                               credits="-0.000000001", usage_amount="9007199254740993.123456789"),
                     google_row(currency="USD", currency_conversion_rate="1", cost="0.000000001", credits="0")]
    monkeypatch.setattr(ai_billing, "query_export", lambda *args, **kwargs: provider_rows)
    data = ai_billing.sync_billing(db, start=START, end=END)
    assert data["usage_rows"][0]["usage_amount"] == "9007199254740993.123456789"
    assert data["usage_rows"][0]["cost"] == "12345678901234567890123456789.123456789"
    assert data["totals"] == [{"currency": "USD", "cost": "12345678901234567890123456789.123456790",
                                "credits": "-0.000000001", "net_cost": "12345678901234567890123456789.123456789"}]


def calculation(amount="0", status="calculated", *, reason=None, token=None, voice="0"):
    return {"calculated_cost_usd": amount, "calculation_status": status,
            "available": status != "unavailable", "unavailable_reason": reason,
            "excluded_components": ["grounding"] if status == "partial" else [],
            "rate_basis": "recorded_request_standard_rates", "source_urls": ["https://cloud.google.com/vertex-ai/generative-ai/pricing"],
            "rate_version": "test-v1", "verified_at": "2026-09-07",
            "breakdown": {"token_cost_usd": amount if token is None else token,
                          "voice_cost_usd": voice, "other_cost_usd": "0"}}


def test_calculated_profile_costs_price_requests_before_aggregating_and_keep_day_feature_scope(db, monkeypatch):
    first = event(db, prompt_tokens=100000, created_at=datetime(2026, 8, 2, 23, 59, 59))
    second = event(db, prompt_tokens=100000, source="daily_ai_notifier", created_at=datetime(2026, 8, 3))
    old = event(db, prompt_tokens=200000, source="student_mock_interview", created_at=datetime(2026, 7, 4))
    event(db, organization_id=7, product="b2b", prompt_tokens=900000)
    seen = []
    def price_request(row):
        seen.append(row.id)
        rate = Decimal("2") if row.prompt_tokens > 150000 else Decimal("1")
        return calculation(format(Decimal(row.prompt_tokens) * rate / 1000000, "f"))
    monkeypatch.setattr(reports.ai_cost_calculation, "calculate_event", price_request)
    detail = reports.build_profile_detail(db, 1, start=START, end=END)
    assert seen == [first.id, second.id, old.id]
    assert Decimal(detail["range_totals"]["calculated_cost_usd"]) == Decimal("0.2")
    assert Decimal(detail["lifetime_totals"]["calculated_cost_usd"]) == Decimal("0.6")
    assert detail["range_totals"]["calculated_cost_status"] == "complete"
    assert detail["range_totals"]["priced_calls"] == 2
    assert [row["date"] for row in detail["daily"]] == ["2026-08-02", "2026-08-03"]
    assert [Decimal(row["calculated_cost_usd"]) for row in detail["daily"]] == [Decimal(".1"), Decimal(".1")]
    assert sum(Decimal(row["range"]["calculated_cost_usd"]) for row in detail["features"]) == Decimal(".2")
    assert sum(Decimal(row["lifetime"]["calculated_cost_usd"]) for row in detail["features"]) == Decimal(".6")
    assert all(row["billed_cost_usd"] == 0 and not row["billed_cost_available"] for row in detail["daily"])


def test_calculated_costs_do_not_round_or_hide_incomplete_records_and_export_basis(db, monkeypatch):
    event(db, estimated_cost_usd=999999, created_at=datetime(2026, 8, 3))
    event(db, source="student_mock_interview", usage_state="unknown", created_at=datetime(2026, 8, 4))
    event(db, source="daily_ai_notifier", search_queries=1, created_at=datetime(2026, 8, 5))
    def calculate(row):
        if row.usage_state == "unknown":
            return calculation(status="unavailable", reason="missing_usage")
        if row.search_queries:
            return calculation("0.000000000001", "partial")
        return calculation("0.000000000002")
    monkeypatch.setattr(reports.ai_cost_calculation, "calculate_event", calculate)
    data = reports.build_profiles(db, start=START, end=END)
    value = data["profiles"][0]["range"]
    assert value["calculated_cost_usd"] == "0.000000000003"
    assert value["calculated_cost_status"] == "partial"
    assert (value["priced_calls"], value["unpriced_calls"], value["partially_priced_calls"]) == (1, 2, 1)
    assert value["cost_exclusions"] == ["grounding", "missing_usage"]
    assert value["rate_versions"] == ["test-v1"]
    # Profile 2 has no usage in the selected dates, so the table omits it; its detail still says so.
    assert [row["user_id"] for row in data["profiles"]] == [1]
    assert reports.build_profile_detail(db, 2, start=START, end=END)["range_totals"]["calculated_cost_status"] == "no_usage"
    assert reports.build_profile_detail(db, 2, start=START, end=END)["range_totals"]["calculated_cost_usd"] == "0"
    detail = reports.build_profile_detail(db, 1, start=START, end=END)
    assert detail["daily"][1]["calculated_cost_status"] == "unavailable"
    assert detail["daily"][1]["calculated_cost_usd"] == "0"
    output = reports.profiles_csv(db, start=START, end=END)
    rows = list(csv.DictReader(StringIO(output.lstrip("\ufeff"))))
    assert rows[0]["Range calculated_cost_usd"] == "0.000000000003"
    assert rows[0]["Range calculated_cost_status"] == "partial"
    assert rows[0]["Range billed_cost_status"] == "not_attributable"
    assert rows[0]["Range rate_basis"] == "recorded_request_standard_rates"
    assert "999999" not in output


def test_profile_cost_query_count_does_not_grow_per_profile(db, monkeypatch):
    from sqlalchemy import event as sqlalchemy_event
    for uid in range(10, 35):
        db.add(models.User(id=uid, email=f"cost{uid}@example.com", full_name="Cost", hashed_password="test"))
    db.commit()
    event(db)
    users = reports.profile_query(db).all()
    monkeypatch.setattr(reports.ai_cost_calculation, "calculate_event", lambda row: calculation(".01"))
    statements = []
    def record_sql(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)
    sqlalchemy_event.listen(db.bind, "before_cursor_execute", record_sql)
    try:
        rows = reports.profile_rows(db, users, START, END)
    finally:
        sqlalchemy_event.remove(db.bind, "before_cursor_execute", record_sql)
    assert len(rows) == 27
    assert len(statements) == 3


def test_real_rate_engine_matches_profile_daily_feature_and_global_cost_sums(db):
    event(db, model="gemini-2.5-pro", metering_version=1, usage_state="legacy",
          prompt_tokens=150000, cached_tokens=10000, output_tokens=50000, total_tokens=200000,
          created_at=datetime(2026, 8, 2))
    event(db, model="gemini-2.5-pro", metering_version=1, usage_state="legacy",
          prompt_tokens=150000, cached_tokens=0, output_tokens=50000, total_tokens=200000,
          source="student_mock_interview", created_at=datetime(2026, 8, 3))
    event(db, model="gemini-2.5-pro", metering_version=1, usage_state="legacy",
          prompt_tokens=250000, cached_tokens=0, output_tokens=50000, total_tokens=300000,
          created_at=datetime(2026, 7, 1))
    # Each 150k-token request gets the <=200k rate independently, even though the
    # combined range exceeds 200k. The old request uses the >200k tier.
    detail = reports.build_profile_detail(db, 1, start=START, end=END)
    assert Decimal(detail["range_totals"]["calculated_cost_usd"]) == Decimal("1.36375")
    assert Decimal(detail["lifetime_totals"]["calculated_cost_usd"]) == Decimal("2.73875")
    assert detail["range_totals"]["historical_prices_verified"] is False
    assert detail["range_totals"]["rate_basis_descriptions"]
    assert sum(Decimal(row["calculated_cost_usd"]) for row in detail["daily"]) == Decimal("1.36375")
    data = reports.recorded_usage_analytics(db, start=date(2026, 6, 1), end=END)
    assert data["range"]["granularity"] == "week"
    assert data["calculated_cost_scope"] == "all_retained_ai_usage"
    for field in ("by_source", "by_model", "daily", "series"):
        assert sum(Decimal(row["calculated_cost_usd"]) for row in data[field]) == Decimal("2.73875")
    assert Decimal(data["range"]["calculated_cost_usd"]) == Decimal("2.73875")
    assert Decimal(data["totals"]["all_time"]["calculated_cost_usd"]) == Decimal("2.73875")


def test_credits_are_tracked_separately_from_the_charge_before_credits(db, monkeypatch):
    configured(monkeypatch)
    monkeypatch.setattr(ai_billing, "query_export", lambda *a, **k: [
        google_row(currency="USD", currency_conversion_rate="1", cost="0.5", credits="-0.5")])
    monkeypatch.setattr(ai_billing, "query_credit_breakdown", lambda *a, **k: [
        credit_row(), credit_row(credit_type="DISCOUNT", credit_name="Committed use", credit_full_name="", amount="0")])
    data = ai_billing.sync_billing(db, start=START, end=END)
    # The charge before credits stays the tracked usage cost even when a free-trial credit makes net 0.
    assert data["google_cost_usd"] == 0.5
    assert data["google_credits_usd"] == -0.5
    assert data["google_net_cost_usd"] == 0
    assert data["totals"][0]["cost"] == "0.5" and data["totals"][0]["net_cost"] == "0.0"
    assert data["credits_applied"] is True
    assert data["credit_breakdown_available"] is True
    assert data["credit_breakdown"][0] == {"currency": "USD", "type": "PROMOTION", "name": "FreeTrial:Credit-1",
                                           "id": "FreeTrial:Credit-1", "full_name": "Free Trial", "amount": "-0.5"}
    assert [c["amount"] for c in data["credit_breakdown"]] == ["-0.5", "0"]
    # Row snapshots keep their original list shape; credit names live in their own table so a
    # build without credit support keeps reading and rewriting the row snapshot unchanged.
    assert isinstance(json.loads(db.query(ai_billing.AiBillingSnapshot).one().payload_json), list)
    credit_snapshot = db.query(ai_billing.AiBillingCreditSnapshot).one()
    assert credit_snapshot.synced_at == db.query(ai_billing.AiBillingSnapshot).one().synced_at
    assert [c["credit_name"] for c in json.loads(credit_snapshot.payload_json)] == ["FreeTrial:Credit-1", "Committed use"]
    # Invalid credit values are rejected before the previous snapshot is replaced.
    monkeypatch.setattr(ai_billing, "query_credit_breakdown", lambda *a, **k: [credit_row(amount="NaN")])
    with pytest.raises(ai_billing.BillingSyncError):
        ai_billing.sync_billing(db, start=START, end=END)
    retained = ai_billing.build_reconciliation(db, start=START, end=END)
    assert retained["credit_breakdown"][0]["amount"] == "-0.5"
    assert retained["last_synced_at"] == data["last_synced_at"]


def test_snapshots_written_before_credit_breakdowns_still_render(db, monkeypatch):
    configured(monkeypatch)
    cfg = ai_billing.configuration()
    legacy_rows = [google_row(currency="USD", currency_conversion_rate="1", cost="2", credits="-2")]
    db.add(ai_billing.AiBillingSnapshot(scope_key=cfg["scope_key"], start_date=START, end_date=END,
                                        payload_json=json.dumps(legacy_rows), synced_at=datetime(2026, 9, 1, tzinfo=timezone.utc)))
    db.commit()
    data = ai_billing.build_reconciliation(db, start=START, end=END)
    assert data["status"] == "available"
    assert data["google_cost_usd"] == 2
    assert data["credits_applied"] is True
    assert data["credit_breakdown"] == []
    assert data["credit_breakdown_available"] is False
    uncredited = ai_billing.build_reconciliation(db, start=date(2026, 7, 1), end=date(2026, 7, 2))
    assert uncredited["credits_applied"] is False and uncredited["credit_breakdown"] == []
    # A credit snapshot older than the rows (rows re-imported by a build without credit support)
    # is not paired with those rows.
    db.add(ai_billing.AiBillingCreditSnapshot(scope_key=cfg["scope_key"], start_date=START, end_date=END,
                                              payload_json=json.dumps([credit_row()]), synced_at=datetime(2026, 8, 31, tzinfo=timezone.utc)))
    db.commit()
    stale = ai_billing.build_reconciliation(db, start=START, end=END)
    assert stale["credit_breakdown"] == [] and stale["credit_breakdown_available"] is False
    monkeypatch.setattr(ai_billing, "query_export", lambda *a, **k: legacy_rows)
    monkeypatch.setattr(ai_billing, "query_credit_breakdown", lambda *a, **k: [credit_row()])
    fresh = ai_billing.sync_billing(db, start=START, end=END)
    assert fresh["credit_breakdown_available"] is True and fresh["credit_breakdown"][0]["full_name"] == "Free Trial"


def test_credit_breakdown_query_is_scoped_bounded_and_parameterized(monkeypatch, credit_breakdown_stub):
    configured(monkeypatch)
    captured = {}
    class Client:
        def query(self, sql, **kwargs):
            captured.update(sql=sql, **kwargs)
            return SimpleNamespace(result=lambda timeout: iter([credit_row(amount=Decimal("-1.5"))]))
    rows = credit_breakdown_stub(ai_billing.configuration(), START, END, client=Client())
    assert rows == [credit_row(amount="-1.5")]
    assert "UNNEST(credits)" in captured["sql"]
    assert "FOR SYSTEM_TIME AS OF @as_of" in captured["sql"]
    assert "@usage_project" in captured["sql"] and "@services" in captured["sql"] and "@start_date" in captured["sql"]
    assert captured["job_config"].maximum_bytes_billed == 1000000000
    assert [param.name for param in captured["job_config"].query_parameters] == ["start_date", "end_date", "usage_project", "services", "as_of"]
    as_of = captured["job_config"].query_parameters[4].value
    assert as_of.tzinfo is not None and as_of < datetime.now(timezone.utc)


def test_both_sync_queries_share_one_read_point_and_credits_alone_count(db, monkeypatch):
    configured(monkeypatch)
    seen = []
    monkeypatch.setattr(ai_billing, "query_export", lambda cfg, start, end, *, client=None, as_of=None: seen.append(as_of) or [
        google_row(currency="USD", currency_conversion_rate="1", cost="1", credits="0")])
    monkeypatch.setattr(ai_billing, "query_credit_breakdown", lambda cfg, start, end, *, client=None, as_of=None: seen.append(as_of) or [credit_row(amount="-1")])
    data = ai_billing.sync_billing(db, start=START, end=END)
    assert len(seen) == 2 and seen[0] == seen[1] and seen[0] is not None
    assert seen[0] <= datetime.now(timezone.utc) - timedelta(seconds=59)
    # A credit that the row totals do not show yet is still reported rather than hidden.
    assert data["totals"][0]["credits"] == "0"
    assert data["credits_applied"] is True
    assert data["credit_breakdown"][0]["amount"] == "-1"


def test_credit_query_failure_after_rows_keeps_previous_snapshot(db, monkeypatch):
    from google.api_core.exceptions import NotFound
    configured(monkeypatch)
    monkeypatch.setattr(ai_billing, "query_export", lambda cfg, start, end, *, client=None, as_of=None: [google_row()])
    monkeypatch.setattr(ai_billing, "query_credit_breakdown", lambda cfg, start, end, *, client=None, as_of=None: [credit_row()])
    previous = ai_billing.sync_billing(db, start=START, end=END)
    def boom(cfg, start, end, *, client=None, as_of=None):
        raise RuntimeError("SECRET credit query failure")
    monkeypatch.setattr(ai_billing, "query_credit_breakdown", boom)
    with pytest.raises(ai_billing.BillingSyncError) as exc:
        ai_billing.sync_billing(db, start=START, end=END)
    assert "SECRET" not in str(exc.value)
    retained = ai_billing.build_reconciliation(db, start=START, end=END)
    assert retained["last_synced_at"] == previous["last_synced_at"]
    assert retained["totals"] == previous["totals"]
    assert retained["credit_breakdown"] == previous["credit_breakdown"]
    def not_yet_exported(cfg, start, end, *, client=None, as_of=None):
        raise NotFound("no table")
    monkeypatch.setattr(ai_billing, "query_credit_breakdown", not_yet_exported)
    fresh_start, fresh_end = date(2026, 7, 1), date(2026, 7, 31)
    with pytest.raises(ai_billing.BillingExportPending):
        ai_billing.sync_billing(db, start=fresh_start, end=fresh_end)
    assert db.query(ai_billing.AiBillingSnapshot).filter_by(start_date=fresh_start).count() == 0
    assert db.query(ai_billing.AiBillingCreditSnapshot).filter_by(start_date=fresh_start).count() == 0


def test_profiles_table_follows_selected_dates_and_orders_by_range_usage(db):
    db.add(models.User(id=4, email="student4@example.com", full_name="Student 4", hashed_password="test"))
    db.commit()
    event(db, user_id=1, total_tokens=150)
    event(db, user_id=2, total_tokens=5000, created_at=datetime(2026, 8, 20))
    event(db, user_id=2, total_tokens=90000, created_at=datetime(2026, 6, 15))   # outside the selected dates
    event(db, user_id=4, total_tokens=70000, created_at=datetime(2026, 7, 4))    # only outside the selected dates
    data = reports.build_profiles(db, start=START, end=END)
    assert data["total"] == 2
    assert [row["user_id"] for row in data["profiles"]] == [2, 1]   # ordered by tokens in the range, not by id
    assert data["profiles"][0]["range"]["total_tokens"] == 5000
    assert data["profiles"][0]["lifetime"]["total_tokens"] == 95000  # lifetime stays per listed profile
    july = reports.build_profiles(db, start=date(2026, 7, 1), end=date(2026, 7, 31))
    assert [row["user_id"] for row in july["profiles"]] == [4]
    exported = list(csv.DictReader(StringIO(reports.profiles_csv(db, start=START, end=END).lstrip("\ufeff"))))
    assert sorted(int(row["Profile ID"]) for row in exported) == [1, 2]
    assert reports.build_profiles(db, search="student4", start=START, end=END)["total"] == 0


def test_dates_inside_an_import_are_served_from_the_freshest_covering_import(db, monkeypatch):
    configured(monkeypatch)
    rows = [google_row(currency="USD", currency_conversion_rate="1", cost="1", credits="-1", usage_date="2026-08-05"),
            google_row(currency="USD", currency_conversion_rate="1", cost="2", credits="-2", usage_date="2026-08-20")]
    credits = [credit_row(amount="-1", usage_date="2026-08-05"), credit_row(amount="-2", usage_date="2026-08-20")]
    monkeypatch.setattr(ai_billing, "query_export", lambda *a, **k: rows)
    monkeypatch.setattr(ai_billing, "query_credit_breakdown", lambda *a, **k: credits)
    month = ai_billing.sync_billing(db, start=START, end=END)   # August, the worker's window
    assert month["derived"] is False and month["credit_breakdown"][0]["amount"] == "-3"
    # A custom range inside that import is answered from it, per usage day, without a manual sync.
    sub = ai_billing.build_reconciliation(db, start=date(2026, 8, 15), end=date(2026, 8, 25))
    assert sub["status"] == "available" and sub["derived"] is True
    assert sub["source_range"] == {"start": "2026-08-01", "end": "2026-08-31"}
    assert sub["last_synced_at"] == month["last_synced_at"]
    assert sub["totals"] == [{"currency": "USD", "cost": "2", "credits": "-2", "net_cost": "0"}]
    assert sub["google_cost_usd"] == 2
    assert [c["amount"] for c in sub["credit_breakdown"]] == ["-2"] and sub["credit_breakdown_available"] is True
    assert [r["usage_date"] for r in sub["usage_rows"]] == ["2026-08-20"]
    assert "import covering 2026-08-01 to 2026-08-31" in sub["message"]
    empty = ai_billing.build_reconciliation(db, start=date(2026, 8, 10), end=date(2026, 8, 12))
    assert empty["derived"] is True and empty["totals"] == [] and empty["billing_status"] == "no_records"
    # Dates not fully covered by any import still need a sync.
    wide = ai_billing.build_reconciliation(db, start=date(2026, 7, 1), end=END)
    assert wide["status"] == "no_data" and "Sync billing" in wide["message"]
    # A later exact sync is fresher, so it wins over the wider import.
    monkeypatch.setattr(ai_billing, "query_export", lambda *a, **k: [
        google_row(currency="USD", currency_conversion_rate="1", cost="5", credits="0", usage_date="2026-08-20")])
    monkeypatch.setattr(ai_billing, "query_credit_breakdown", lambda *a, **k: [])
    exact = ai_billing.sync_billing(db, start=date(2026, 8, 15), end=date(2026, 8, 25))
    assert exact["derived"] is False and exact["google_cost_usd"] == 5
    # Credits imported before per-day grouping existed cannot be split by date.
    legacy = db.query(ai_billing.AiBillingCreditSnapshot).filter_by(start_date=START, end_date=END).one()
    legacy.payload_json = json.dumps([{k: v for k, v in credit_row(amount="-3").items() if k != "usage_date"}])
    db.commit()
    assert ai_billing.build_reconciliation(db, start=date(2026, 8, 3), end=date(2026, 8, 6))["credit_breakdown_available"] is False
    assert ai_billing.build_reconciliation(db, start=START, end=END)["credit_breakdown"][0]["amount"] == "-3"


def test_usage_by_account_counts_every_call_once_and_holds_the_ledger_against_google(db, monkeypatch):
    org = models.EnterpriseOrganization(id=7, company_name="Brembo overseas", subdomain_slug="brembo", created_by_user_id=3)
    db.add(org)
    db.commit()
    event(db, user_id=1, total_tokens=1000)                                                   # b2c
    event(db, user_id=None, organization_id=7, product="b2b", source="enterprise_copilot", total_tokens=2000)
    event(db, user_id=None, organization_id=None, product="b2b", source="enterprise_deep_scan", total_tokens=300)  # b2b, org not recorded
    event(db, user_id=None, product="shared", source="news.ingestion.au", total_tokens=400)
    event(db, user_id=None, product="shared", source="course_catalog_refresh", total_tokens=50)
    event(db, user_id=None, product="unknown", source="daily_ai_notifier", metering_version=2, total_tokens=600)
    event(db, user_id=1, total_tokens=90000, created_at=datetime(2026, 6, 1))                # outside the dates
    event(db, user_id=3, total_tokens=700, source="daily_ai_notifier")                          # enterprise-flagged account, B2C feature
    event(db, user_id=None, product="b2c", source="daily_ai_notifier", total_tokens=80)        # b2c call with no profile id
    data = reports.build_usage_by_account(db, start=START, end=END)
    buckets = {b["key"]: b for b in data["buckets"]}
    assert [b["key"] for b in data["buckets"]] == ["b2c", "b2b", "shared", "unattributed"]
    # Every recorded call in the dates is in exactly one bucket, and the buckets add up to the ledger.
    assert {k: b["range"]["calls"] for k, b in buckets.items()} == {"b2c": 3, "b2b": 2, "shared": 2, "unattributed": 1}
    assert sum(b["range"]["total_tokens"] for b in buckets.values()) == data["ledger"]["range"]["total_tokens"] == 5130
    assert data["ledger"]["range"]["calls"] == 8 and data["ledger"]["lifetime"]["calls"] == 9
    # B2C calls the profile table cannot list are named, so the B2C card is fully traceable.
    assert [(row["name"], row["user_id"], row["reason"], row["range"]["total_tokens"]) for row in data["b2c_unlisted"]] == [
        ("Student 3", 3, "enterprise_origin_account", 700), ("No profile id recorded", None, "no_profile_id", 80)]
    assert data["b2c_unlisted_total"]["range"]["calls"] == 2 and data["b2c_unlisted_total"]["range"]["total_tokens"] == 780
    assert reports.build_profiles(db, start=START, end=END)["total"] == 1   # the profile table lists only user 1
    assert Decimal(data["ledger"]["range"]["calculated_cost_usd"]) == sum(Decimal(b["range"]["calculated_cost_usd"]) for b in buckets.values())
    assert buckets["b2c"]["lifetime"]["total_tokens"] == 91780   # 1000 + 90000 outside the dates + 700 + 80 unlisted
    # Organisations, shared jobs and unattributed calls are broken down by name, ordered by usage in the dates.
    assert [(o["name"], o["organization_id"], o["range"]["total_tokens"]) for o in data["organizations"]] == [
        ("Brembo overseas", 7, 2000), (reports.UNKNOWN_ORGANIZATION, None, 300)]
    assert data["organizations"][0]["subdomain"] == "brembo"
    assert [(r["source"], r["range"]["total_tokens"]) for r in data["shared"]] == [("news.ingestion.au", 400), ("course_catalog_refresh", 50)]
    assert [(r["source"], r["range"]["total_tokens"]) for r in data["unattributed"]] == [("daily_ai_notifier", 600)]
    # Without a billing connection the Google side says so instead of showing a false zero.
    assert data["google"]["available"] is False
    # With an import covering the dates, the ledger is held against Google's charge before credits.
    configured(monkeypatch)
    monkeypatch.setattr(ai_billing, "query_export", lambda *a, **k: [
        google_row(currency="USD", currency_conversion_rate="1", cost="3.5", credits="-3.5", usage_date="2026-08-03")])
    ai_billing.sync_billing(db, start=START, end=END)
    with_google = reports.build_usage_by_account(db, start=START, end=END)["google"]
    assert with_google["available"] is True and with_google["cost_before_credits_usd"] == 3.5 and with_google["net_cost_usd"] == 0
    assert with_google["first_usage_date"] == "2026-08-03"
    output = reports.usage_by_account_csv(db, start=START, end=END)
    rows = list(csv.DictReader(StringIO(output.lstrip("\ufeff"))))
    assert [r["Section"] for r in rows][:5] == ["Ledger total", "Bucket", "Bucket", "Bucket", "Bucket"]
    assert {r["Name"] for r in rows if r["Section"] == "Enterprise organisation"} == {"Brembo overseas", reports.UNKNOWN_ORGANIZATION}
    assert {r["Name"] for r in rows if r["Section"] == "Shared platform work"} == {"news.ingestion.au", "course_catalog_refresh"}
    assert int(rows[0]["Range total_tokens"]) == 5130
    assert {r["Name"] for r in rows if r["Section"] == "B2C usage not in the profile table"} == {"Student 3", "No profile id recorded"}


def test_event_bucket_matches_the_sql_bucket_expression(db):
    event(db, user_id=1)                                                                       # b2c
    event(db, user_id=1, product="unknown", metering_version=1, source="student_ai_chat")     # legacy b2c source
    event(db, user_id=1, product="unknown", metering_version=1, source="enterprise_copilot")  # legacy, ambiguous
    event(db, organization_id=9, product="b2c")                                               # org wins
    event(db, user_id=None, product="shared", source="news.ingestion.us")
    event(db, user_id=None, product="unknown", metering_version=2, source="daily_ai_notifier")
    E = models.GeminiUsageEvent
    sql = {row[0]: row[1] for row in db.query(E.id, reports._bucket_expr()).all()}
    python = {e.id: reports.event_bucket(e) for e in db.query(E).all()}
    assert sql == python
    assert sorted(python.values()) == ["b2b", "b2c", "b2c", "shared", "unattributed", "unattributed"]
