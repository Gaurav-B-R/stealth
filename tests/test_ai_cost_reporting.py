"""Accounting scope, lifetime history, exports and admin-only billing reconciliation."""
import csv
from datetime import date, datetime
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
from app.auth import get_current_user
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
    assert data["total"] == 2  # enterprise-origin profile excluded
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
    assert data["profiles"][0]["lifetime"]["calls"] == 0
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
    assert "unpriced_calls" not in value
    assert value["billed_cost_usd"] == 0
    assert value["billed_cost_available"] is False
    assert "not guaranteed" in result["coverage"]["note"]


def test_export_all_pages_literal_search_and_spreadsheet_safety(db):
    first = db.get(models.User, 1)
    first.full_name = "=HYPERLINK(\"https://example.com\")"
    for uid in range(10, 277):
        db.add(models.User(id=uid, email=f"student{uid}@example.com", full_name="Student", hashed_password="test"))
    db.commit()
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
    actor = models.User(id=9000, email="admin@example.com", is_admin=True, is_active=True)
    application.dependency_overrides[get_db] = lambda: db
    application.dependency_overrides[get_current_user] = lambda: actor
    monkeypatch.setattr(admin, "_is_admin_turnstile_required", lambda request: False)
    monkeypatch.setattr(admin, "check_ip_rate_limit", lambda **kwargs: (True, 0))
    with TestClient(application) as client:
        r = client.get("/api/admin/ai-usage/profiles", params={"start": str(START), "end": str(END)})
        assert r.status_code == 200, r.text
        assert r.headers["cache-control"] == "no-store"
        usage = client.get("/api/admin/ai-usage/analytics")
        assert usage.status_code == 200
        assert usage.headers["cache-control"] == "no-store"
        assert "cost_usd" not in usage.text
        assert "is_estimate" not in usage.text
        assert client.get("/api/admin/ai-usage/profiles/export").status_code == 200
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


def test_legacy_admin_analytics_serve_only_recorded_counters(db):
    event(db, estimated_cost_usd=999999, search_cost_usd=222222, search_queries=3)
    data = reports.recorded_usage_analytics(db, start=START, end=END)
    assert data["range"]["tokens"] == 150
    assert data["range"]["search_queries"] == 3
    assert data["range"]["top_day"] == {"date": "2026-08-03", "tokens": 150}
    def assert_no_monetary_fields(value):
        if isinstance(value, dict):
            for key, item in value.items():
                assert not any(word in key for word in ("cost", "saved", "estimate", "pricing", "currency")), key
                assert_no_monetary_fields(item)
        elif isinstance(value, list):
            for item in value:
                assert_no_monetary_fields(item)
    assert_no_monetary_fields(data)
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
    actor = models.User(id=9000, email="admin@example.com", is_admin=True, is_active=True)
    application.dependency_overrides[get_db] = lambda: db
    application.dependency_overrides[get_current_user] = lambda: actor
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
