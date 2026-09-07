"""Read Google billing exports and retain reproducible, replaceable reconciliation snapshots.

Google quantities retain their SKU/unit. A billing dollar is never converted into
an invented profile token count. No credentials or account changes are made here.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext

from sqlalchemy import Column, Date, DateTime, Integer, String, Text, UniqueConstraint, func, or_

from app.database import Base
from app import models
from app.ai_cost_reporting import resolve_range, range_filter, summarize


class AiBillingSnapshot(Base):
    __tablename__ = "ai_billing_snapshots"
    id = Column(Integer, primary_key=True)
    scope_key = Column(String(64), nullable=False, index=True)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    payload_json = Column(Text, nullable=False)
    synced_at = Column(DateTime(timezone=True), nullable=False)
    __table_args__ = (UniqueConstraint("scope_key", "start_date", "end_date", name="uq_ai_billing_window"),)


class BillingConfigurationError(ValueError):
    pass


class BillingSyncError(RuntimeError):
    pass


class BillingExportPending(BillingSyncError):
    """The configured export table is not yet available; no snapshot was imported."""


EXPORT_PENDING_MESSAGE = (
    "Google's billing export table is not available yet. Newly enabled exports can take time to appear. "
    "No new billing data was imported; any prior snapshot is retained. "
    "If this continues, verify the configured table name and dataset location."
)


DEFAULT_SERVICES = ["Vertex AI", "Gemini API", "Generative Language API", "Cloud Text-to-Speech API",
                    "Cloud Text-to-Speech", "Gemini Enterprise Agent Platform"]
SERVICE_PROVIDERS = {"Vertex AI": "vertex", "Gemini Enterprise Agent Platform": "vertex",
                     "Gemini API": "developer", "Generative Language API": "developer",
                     "Cloud Text-to-Speech API": "google_cloud_tts", "Cloud Text-to-Speech": "google_cloud_tts"}
SCOPE_NOTE = (
    "Imported Google charges cover the configured project and selected AI services, including B2B and shared work. "
    "Amounts and credits come directly from the billing export; USD uses Google's exported conversion rate. "
    "Provider quantities retain their own SKU units and are not interchangeable with application token counts. "
    "Billing can arrive late and be corrected. Project charges are never allocated to individual profiles. "
    "A displayed 0 without available billing data is a missing-data value, not a confirmed zero charge."
)


def configuration():
    table = os.getenv("AI_BILLING_BIGQUERY_TABLE", "").strip()
    project = os.getenv("AI_BILLING_USAGE_PROJECT", "").strip()
    query_project = os.getenv("AI_BILLING_QUERY_PROJECT", "").strip() or (table.split(".")[0] if table else "")
    services = [s.strip() for s in os.getenv("AI_BILLING_SERVICE_NAMES", ",".join(DEFAULT_SERVICES)).split(",") if s.strip()]
    if table and not re.fullmatch(r"[a-zA-Z0-9_-]+\.[a-zA-Z0-9_]+\.[a-zA-Z0-9_]+", table):
        raise BillingConfigurationError("Billing export table must be project.dataset.table.")
    for value in (project, query_project):
        if value and not re.fullmatch(r"[a-zA-Z0-9_-]+", value):
            raise BillingConfigurationError("Invalid billing project configuration.")
    cfg = {"table": table, "project": project, "query_project": query_project,
           "services": services, "location": os.getenv("AI_BILLING_LOCATION", "US").strip()}
    cfg["configured"] = bool(table and project and query_project and services)
    cfg["scope_key"] = hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()
    return cfg


def _client(cfg):
    from google.cloud import bigquery
    credentials = None
    credentials_path = os.getenv("AI_BILLING_CREDENTIALS", "").strip()
    if credentials_path:
        from google.oauth2 import service_account
        credentials = service_account.Credentials.from_service_account_file(
            credentials_path, scopes=["https://www.googleapis.com/auth/cloud-platform"])
    return bigquery.Client(project=cfg["query_project"], credentials=credentials, location=cfg["location"])


def query_export(cfg, start, end, *, client=None):
    from google.cloud import bigquery
    # Identifier comes only from strictly validated server configuration. All filters are parameters.
    query = f"""
        SELECT DATE(usage_start_time, 'UTC') AS usage_date,
               service.description AS service, sku.id AS sku_id, sku.description AS sku,
               usage.unit AS unit, currency, currency_conversion_rate,
               invoice.month AS invoice_month, cost_type,
               SUM(CAST(usage.amount AS NUMERIC)) AS usage_amount,
               SUM(CAST(cost AS NUMERIC)) AS cost,
               SUM(IFNULL((SELECT SUM(CAST(c.amount AS NUMERIC)) FROM UNNEST(credits) c), 0)) AS credits
        FROM `{cfg['table']}`
        WHERE usage_start_time >= TIMESTAMP(@start_date, 'UTC')
          AND usage_start_time < TIMESTAMP(DATE_ADD(@end_date, INTERVAL 1 DAY), 'UTC')
          AND project.id = @usage_project
          AND service.description IN UNNEST(@services)
        GROUP BY usage_date, service, sku_id, sku, unit, currency,
                 currency_conversion_rate, invoice_month, cost_type
        ORDER BY usage_date, service, sku_id, currency, unit
    """
    config = bigquery.QueryJobConfig(
        use_legacy_sql=False,
        maximum_bytes_billed=int(os.getenv("AI_BILLING_MAX_BYTES", "1000000000")),
        query_parameters=[bigquery.ScalarQueryParameter("start_date", "DATE", start),
                          bigquery.ScalarQueryParameter("end_date", "DATE", end),
                          bigquery.ScalarQueryParameter("usage_project", "STRING", cfg["project"]),
                          bigquery.ArrayQueryParameter("services", "STRING", cfg["services"])],
    )
    owner = client is None
    client = client or _client(cfg)
    try:
        result = client.query(query, job_config=config, location=cfg["location"]).result(timeout=45)
        # The SDK iterates every page. Decimal values are retained as strings in the snapshot.
        return [{str(k): (v.isoformat() if hasattr(v, "isoformat") else str(v) if isinstance(v, Decimal) else v)
                 for k, v in dict(row).items()} for row in result]
    finally:
        if owner:
            client.close()


def _decimal(value):
    try:
        result = Decimal(str(value if value is not None else 0))
    except InvalidOperation as exc:
        raise BillingSyncError("Billing export contained an invalid numeric value.") from exc
    if not result.is_finite():
        raise BillingSyncError("Billing export contained a non-finite numeric value.")
    return result


def _decimal_text(value):
    """JSON numbers cannot carry Google NUMERIC precision; preserve the exact decimal."""
    return format(_decimal(value), "f")


def _decimal_add(left, right):
    # Google NUMERIC supports 38 digits, beyond Python's default Decimal precision of 28.
    with localcontext() as context:
        context.prec = 80
        return left + right


def sync_billing(db, *, start=None, end=None, client=None):
    cfg = configuration()
    if not cfg["configured"]:
        raise BillingConfigurationError("Google billing export is not configured for this environment.")
    start, end = resolve_range(start, end)
    if (end - start).days > 366:
        raise BillingConfigurationError("Select at most 366 days for a billing sync. Profile lifetime totals have no such limit.")
    try:
        rows = query_export(cfg, start, end, client=client)
        # Validate before replacing a prior successful snapshot.
        for row in rows:
            for field in ("cost", "credits", "usage_amount", "currency_conversion_rate"):
                _decimal(row.get(field))
        payload = json.dumps(rows, sort_keys=True, allow_nan=False)
    except (BillingConfigurationError, BillingSyncError):
        raise
    except Exception as exc:
        from google.api_core.exceptions import NotFound
        if isinstance(exc, NotFound):
            raise BillingExportPending(EXPORT_PENDING_MESSAGE) from exc
        # Provider exception text may contain credential paths, queries or account details.
        raise BillingSyncError("Google billing sync failed. Check export access, location and query limits; the previous snapshot is retained.") from exc
    row = db.query(AiBillingSnapshot).filter_by(scope_key=cfg["scope_key"], start_date=start, end_date=end).first()
    if row is None:
        row = AiBillingSnapshot(scope_key=cfg["scope_key"], start_date=start, end_date=end)
        db.add(row)
    row.payload_json = payload
    row.synced_at = datetime.now(timezone.utc)
    db.commit()
    return build_reconciliation(db, start=start, end=end)


def build_reconciliation(db, *, start=None, end=None):
    cfg = configuration()
    start, end = resolve_range(start, end)
    response = {"configured": cfg["configured"], "status": "not_configured", "billing_status": "not_configured",
                "message": "Google billing is not connected. Displayed 0 means no imported charge is available.",
                "last_synced_at": None, "range": {"start": start.isoformat(), "end": end.isoformat()},
                "project_id": cfg["project"] or None, "totals": [], "usage_rows": [],
                "google_cost_usd": 0, "google_credits_usd": 0, "google_net_cost_usd": 0,
                "google_cost_available": False, "billing_data_available": False,
                "scope_note": SCOPE_NOTE}
    if not cfg["configured"]:
        return response
    snapshot = db.query(AiBillingSnapshot).filter_by(scope_key=cfg["scope_key"], start_date=start, end_date=end).first()
    if snapshot is None:
        response.update(status="no_data", billing_status="not_synced",
                        message="No Google billing snapshot for this date range. Displayed 0 means no imported charge is available.")
        return response
    rows = json.loads(snapshot.payload_json)
    totals = {}
    google_usd = Decimal(0)
    google_credits_usd = Decimal(0)
    currency_complete = True
    usage_rows = []
    for row in rows:
        currency = row.get("currency") or "UNKNOWN"
        cost, credits = _decimal(row.get("cost")), _decimal(row.get("credits"))
        item = totals.setdefault(currency, {"cost": Decimal(0), "credits": Decimal(0)})
        item["cost"] = _decimal_add(item["cost"], cost)
        item["credits"] = _decimal_add(item["credits"], credits)
        rate = _decimal(row.get("currency_conversion_rate"))
        # USD uses only Google's stored currency conversion rate. No current FX or list prices.
        # Tax remains in the currency totals; this USD figure represents service charges.
        if row.get("cost_type") != "tax":
            if currency == "USD":
                google_usd += cost
                google_credits_usd += credits
            elif rate > 0:
                google_usd += cost / rate
                google_credits_usd += credits / rate
            else:
                currency_complete = False
        usage_rows.append({**row, "usage_amount": _decimal_text(row.get("usage_amount")),
                           "cost": _decimal_text(cost), "credits": _decimal_text(credits),
                           "currency_conversion_rate": _decimal_text(row.get("currency_conversion_rate"))})
    E = models.GeminiUsageEvent
    period = range_filter(start, end)
    providers = sorted({SERVICE_PROVIDERS[s] for s in cfg["services"] if s in SERVICE_PROVIDERS})
    app = summarize(db, period, E.project_id == cfg["project"], E.provider.in_(providers))
    # Monetary placeholders belong to profile reports, not provider metering coverage.
    app = {key: value for key, value in app.items() if not key.startswith("billed_")}
    missing_scope = db.query(func.count(E.id)).filter(period, or_(E.project_id.is_(None), E.project_id == "")).scalar() or 0
    unknown_provider = db.query(func.count(E.id)).filter(period, E.project_id == cfg["project"],
                      or_(E.provider.is_(None), ~E.provider.in_(list(SERVICE_PROVIDERS.values())))).scalar() or 0
    incomplete = bool(app["unknown_calls"] or app["legacy_calls"] or missing_scope or unknown_provider
                      or any(service not in SERVICE_PROVIDERS for service in cfg["services"]))
    stamp = snapshot.synced_at
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    billing_status = "available" if rows and currency_complete else "currency_unavailable" if rows else "no_records"
    message = ("Google billing snapshot loaded. Recent usage and corrections can arrive later." if rows else
               "Google returned no billing rows for this range. Displayed 0 is not confirmation of a zero charge.")
    if rows and not currency_complete:
        message = "Google charges are available in the exported currencies. USD is 0 because the exported conversion rate is missing."
    response.update(status="available", billing_status=billing_status, message=message,
                    last_synced_at=stamp.isoformat(),
                    totals=[{"currency": key, "cost": _decimal_text(value["cost"]), "credits": _decimal_text(value["credits"]),
                             "net_cost": _decimal_text(_decimal_add(value["cost"], value["credits"]))} for key, value in sorted(totals.items())],
                    google_cost_usd=float(google_usd) if currency_complete and rows else 0,
                    google_credits_usd=float(google_credits_usd) if currency_complete and rows else 0,
                    google_net_cost_usd=float(google_usd + google_credits_usd) if currency_complete and rows else 0,
                    google_cost_available=bool(rows and currency_complete), billing_data_available=bool(rows),
                    metering_status="incomplete" if incomplete else "recorded",
                    usage_rows=usage_rows, coverage={"unknown_project_calls": missing_scope,
                                                    "unknown_provider_calls": unknown_provider, **app})
    return response
