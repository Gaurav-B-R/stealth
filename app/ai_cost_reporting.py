"""B2C usage reports. Recorded history is never presented as recovered history."""
from __future__ import annotations

import csv
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, localcontext
from io import StringIO

from sqlalchemy import and_, case, func, or_

from app import ai_cost_calculation, ai_usage, models


COVERAGE_NOTE = (
    "Lifetime means all retained usage records, not guaranteed usage since signup. "
    "Legacy records can have missing attribution or combined token categories. "
    "A displayed 0 means no recorded value is available; it does not establish that no usage or charge occurred. "
    "Google billing does not identify individual profiles, so profile billed costs remain 0 with an unavailable status. "
    "Calculated AI costs use each retained request's recorded usage and supported published rates, separately from billed charges. "
    "A partial calculation includes only supported components; its excluded costs remain unknown. "
    "Shared AI work is shown separately."
)


class CalculatedCosts:
    """Add request-level prices without rounding cents or re-pricing aggregate tokens."""

    def __init__(self):
        self.calls = self.priced = self.unpriced = self.partial = 0
        self.amounts = {key: Decimal(0) for key in ("total", "token", "voice", "other")}
        self.bases, self.sources, self.versions, self.exclusions = set(), set(), set(), set()
        self.basis_descriptions, self.assumptions, self.coverage_reasons = set(), set(), set()
        self.historical_price_checks = 0
        self.all_historical_prices_verified = True
        self.verified_at = None

    def add(self, calculation):
        self.calls += 1
        status = calculation["calculation_status"]
        if status in ("calculated", "not_billable"):
            self.priced += 1
        else:
            self.unpriced += 1
            self.partial += status == "partial"
        breakdown = calculation.get("breakdown") or {}
        # Google token counts may exceed JavaScript's integer precision. Keep all
        # money decimal from the first request through the JSON/CSV boundary.
        with localcontext() as ctx:
            ctx.prec = 96
            self.amounts["total"] += Decimal(calculation["calculated_cost_usd"])
            for key in ("token", "voice", "other"):
                self.amounts[key] += Decimal(breakdown.get(f"{key}_cost_usd") or "0")
        if calculation.get("rate_basis"):
            self.bases.add(calculation["rate_basis"])
        if calculation.get("rate_basis_description"):
            self.basis_descriptions.add(calculation["rate_basis_description"])
        self.assumptions.update(calculation.get("assumptions") or [])
        self.coverage_reasons.update(calculation.get("coverage_reasons") or [])
        if status in ("calculated", "partial"):
            self.historical_price_checks += 1
            self.all_historical_prices_verified &= bool(calculation.get("historical_price_verified"))
        self.sources.update(calculation.get("source_urls") or [])
        if calculation.get("rate_version"):
            self.versions.add(calculation["rate_version"])
        self.exclusions.update(calculation.get("excluded_components") or [])
        if calculation.get("unavailable_reason"):
            self.exclusions.add(calculation["unavailable_reason"])
        verified = calculation.get("verified_at")
        if verified:
            self.verified_at = max(self.verified_at or verified, verified)

    def as_dict(self):
        status = ("no_usage" if not self.calls else "complete" if not self.unpriced else
                  "partial" if self.priced or self.partial else "unavailable")
        return {"calculated_cost_usd": format(self.amounts["total"], "f"),
                "calculated_cost_status": status,
                "calculated_cost_available": status in ("complete", "partial"),
                "priced_calls": self.priced, "unpriced_calls": self.unpriced,
                "partially_priced_calls": self.partial,
                **{f"calculated_{key}_cost_usd": format(self.amounts[key], "f") for key in ("token", "voice", "other")},
                "rate_basis": sorted(self.bases), "rate_sources": sorted(self.sources),
                "rate_versions": sorted(self.versions), "rates_verified_at": self.verified_at,
                "rate_basis_descriptions": sorted(self.basis_descriptions),
                "calculation_assumptions": sorted(self.assumptions),
                "rate_coverage_reasons": sorted(self.coverage_reasons),
                "historical_prices_verified": bool(self.historical_price_checks) and self.all_historical_prices_verified,
                "cost_exclusions": sorted(self.exclusions)}

    def merge(self, other):
        if other is None:
            return
        self.calls += other.calls
        self.priced += other.priced
        self.unpriced += other.unpriced
        self.partial += other.partial
        with localcontext() as ctx:
            ctx.prec = 96
            for key in self.amounts:
                self.amounts[key] += other.amounts[key]
        self.bases.update(other.bases)
        self.sources.update(other.sources)
        self.versions.update(other.versions)
        self.exclusions.update(other.exclusions)
        self.basis_descriptions.update(other.basis_descriptions)
        self.assumptions.update(other.assumptions)
        self.coverage_reasons.update(other.coverage_reasons)
        self.historical_price_checks += other.historical_price_checks
        self.all_historical_prices_verified &= other.all_historical_prices_verified
        if other.verified_at:
            self.verified_at = max(self.verified_at or other.verified_at, other.verified_at)


def _event_day(event):
    stamp = event.created_at
    if isinstance(stamp, datetime):
        if stamp.tzinfo is not None:
            stamp = stamp.astimezone(timezone.utc)
        return stamp.date()
    return date.fromisoformat(str(stamp)[:10]) if stamp else None


def calculated_stats(stats=None, costs=None):
    return {**(stats if stats is not None else stats_dict()),
            **(costs or CalculatedCosts()).as_dict()}


def resolve_range(start=None, end=None):
    today = datetime.now(timezone.utc).date()
    end = min(end or today, today)
    start = min(start or end - timedelta(days=29), today)
    if start > end:
        start, end = end, start
    return start, end


def range_filter(start, end):
    E = models.GeminiUsageEvent
    return and_(E.created_at >= datetime.combine(start, time.min),
                E.created_at < datetime.combine(end + timedelta(days=1), time.min))


def b2c_filter():
    E = models.GeminiUsageEvent
    from app.visa_pass import B2C_COST_SOURCES
    return and_(E.organization_id.is_(None), or_(
        E.product == "b2c",
        and_(func.coalesce(E.metering_version, 1) < 2, E.source.in_(B2C_COST_SOURCES)),
    ))


def _iso(value):
    if not value:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, datetime) and value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def stat_columns():
    E = models.GeminiUsageEvent
    tokens = and_(~E.model.like("gcp-tts/%"), or_(E.unit_type == "tokens", E.unit_type.is_(None)))
    legacy = func.coalesce(E.metering_version, 1) < 2
    def total(field, condition=None):
        expr = getattr(E, field)
        if condition is not None:
            expr = case((condition, expr), else_=0)
        return func.coalesce(func.sum(expr), 0)
    return [
        func.count(E.id).label("calls"),
        total("prompt_tokens", tokens).label("input_tokens"),
        # Legacy output contains thinking; expose that limitation in coverage, not an invented split.
        func.coalesce(func.sum(case((tokens, case((legacy, E.output_tokens), else_=E.candidate_tokens)), else_=0)), 0).label("output_tokens"),
        total("thought_tokens", tokens).label("thinking_tokens"),
        total("cached_tokens", tokens).label("cached_tokens"),
        total("tool_tokens", tokens).label("tool_tokens"),
        total("total_tokens", tokens).label("total_tokens"),
        func.coalesce(func.sum(case((and_(E.model.like("gcp-tts/%"), legacy, E.character_count == 0), E.total_tokens), else_=E.character_count)), 0).label("tts_characters"),
        func.sum(case((E.usage_state.in_(["unknown", "pending"]), 1), else_=0)).label("unknown_calls"),
        func.sum(case((legacy, 1), else_=0)).label("legacy_calls"),
        func.min(E.created_at).label("first_event_at"),
        func.max(E.created_at).label("last_event_at"),
    ]


def stats_dict(row=None):
    fields = [c.name for c in stat_columns()]
    values = dict(zip(fields, row or [None] * len(fields)))
    return {**{k: (_iso(v) if k.endswith("_at") else int(v or 0)) for k, v in values.items()},
            "billed_cost_usd": 0, "billed_cost_available": False,
            "billed_cost_status": "not_attributable"}


def summarize(db, *conditions):
    return stats_dict(db.query(*stat_columns()).filter(*conditions).one())


def profile_activity(db, start, end):
    """Per-profile B2C usage inside the selected dates.

    The profile table follows the date filter: only profiles with recorded usage in the range are
    listed, ordered by what they used in that range. Lifetime figures stay per listed profile.
    """
    E = models.GeminiUsageEvent
    return (db.query(E.user_id.label("user_id"), *stat_columns())
            .filter(b2c_filter(), range_filter(start, end), E.user_id.isnot(None))
            .group_by(E.user_id).subquery())


def profile_query(db, search="", *, activity=None):
    U = models.User
    q = db.query(U).filter(U.is_enterprise_account.is_(False))
    if activity is not None:
        q = q.join(activity, activity.c.user_id == U.id)
    search = str(search or "").strip()[:200]
    if search:
        # Escape LIKE wildcards: a search is literal, never a SQL pattern.
        needle = "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        q = q.filter(or_(U.email.ilike(needle, escape="\\"), U.full_name.ilike(needle, escape="\\")))
    return q


def profile_rows(db, users, start, end):
    E = models.GeminiUsageEvent
    ids = [u.id for u in users]
    if not ids:
        return []
    def grouped(*extra):
        rows = db.query(E.user_id, *stat_columns()).filter(b2c_filter(), E.user_id.in_(ids), *extra).group_by(E.user_id).all()
        return {row[0]: stats_dict(row[1:]) for row in rows}
    lifetime = grouped()
    selected = grouped(range_filter(start, end))
    lifetime_costs, selected_costs = defaultdict(CalculatedCosts), defaultdict(CalculatedCosts)
    # One streamed scan for the entire page, not one query per profile. Pricing is
    # applied before aggregation because model, context tier and date can differ.
    for event in db.query(E).filter(b2c_filter(), E.user_id.in_(ids)).yield_per(1000):
        calculation = ai_cost_calculation.calculate_event(event)
        lifetime_costs[event.user_id].add(calculation)
        day = _event_day(event)
        if day is not None and start <= day <= end:
            selected_costs[event.user_id].add(calculation)
    return [{"user_id": u.id, "name": u.full_name, "email": u.email,
             "range": calculated_stats(selected.get(u.id), selected_costs.get(u.id)),
             "lifetime": calculated_stats(lifetime.get(u.id), lifetime_costs.get(u.id))} for u in users]


def coverage(db, start, end):
    E = models.GeminiUsageEvent
    period = range_filter(start, end)
    b2c = summarize(db, b2c_filter(), period)
    return {
        "first_recorded_at": _iso(db.query(func.min(E.created_at)).filter(b2c_filter()).scalar()),
        "measured_calls": db.query(func.count(E.id)).filter(b2c_filter(), period, E.usage_state == "measured").scalar() or 0,
        "legacy_calls": b2c["legacy_calls"], "unknown_calls": b2c["unknown_calls"],
        "shared": summarize(db, period, E.product == "shared"),
        "unattributed": summarize(db, period, E.organization_id.is_(None),
                                   or_(E.product != "shared", E.product.is_(None)),
                                   or_(E.user_id.is_(None), ~b2c_filter())),
        "note": COVERAGE_NOTE,
    }


def build_profiles(db, *, start=None, end=None, search="", page=1, page_size=25):
    start, end = resolve_range(start, end)
    page, page_size = max(1, int(page)), max(1, min(100, int(page_size)))
    activity = profile_activity(db, start, end)
    q = profile_query(db, search, activity=activity)
    total = q.count()
    users = (q.order_by(activity.c.total_tokens.desc(), activity.c.calls.desc(), models.User.id)
             .offset((page - 1) * page_size).limit(page_size).all())
    return {"range": {"start": start.isoformat(), "end": end.isoformat()},
            "page": page, "page_size": page_size, "total": total,
            "profiles": profile_rows(db, users, start, end), "coverage": coverage(db, start, end),
            "metering_health": ai_usage.get_metering_health()}


def build_profile_detail(db, user_id, *, start=None, end=None):
    U, E = models.User, models.GeminiUsageEvent
    user = profile_query(db).filter(U.id == user_id).first()
    if user is None:
        return None
    start, end = resolve_range(start, end)
    base = [b2c_filter(), E.user_id == user_id]
    def grouped(*extra):
        return {r[0]: stats_dict(r[1:]) for r in db.query(E.source, *stat_columns()).filter(*base, *extra).group_by(E.source).all()}
    lifetime, selected = grouped(), grouped(range_filter(start, end))
    lifetime_cost, range_cost = CalculatedCosts(), CalculatedCosts()
    lifetime_features, range_features, daily_costs = (defaultdict(CalculatedCosts) for _ in range(3))
    for event in db.query(E).filter(*base).yield_per(1000):
        calculation = ai_cost_calculation.calculate_event(event)
        lifetime_cost.add(calculation)
        lifetime_features[event.source].add(calculation)
        day = _event_day(event)
        if day is not None and start <= day <= end:
            range_cost.add(calculation)
            range_features[event.source].add(calculation)
            daily_costs[day.isoformat()].add(calculation)
    daily = []
    for row in db.query(func.date(E.created_at), *stat_columns()).filter(
            *base, range_filter(start, end)).group_by(func.date(E.created_at)).order_by(func.date(E.created_at)):
        day = str(row[0])
        daily.append({"date": day, **calculated_stats(stats_dict(row[1:]), daily_costs.get(day))})
    return {"profile": {"user_id": user.id, "name": user.full_name, "email": user.email},
            "range": {"start": start.isoformat(), "end": end.isoformat()},
            "range_totals": calculated_stats(summarize(db, *base, range_filter(start, end)), range_cost),
            "lifetime_totals": calculated_stats(summarize(db, *base), lifetime_cost),
            "features": [{"source": src, "label": ai_usage.SOURCE_LABELS.get(src, src),
                          "range": calculated_stats(selected.get(src), range_features.get(src)),
                          "lifetime": calculated_stats(lifetime[src], lifetime_features.get(src))}
                         for src in sorted(lifetime)], "daily": daily, "coverage_note": COVERAGE_NOTE}


EXPORT_FIELDS = ["calls", "input_tokens", "output_tokens", "thinking_tokens", "cached_tokens",
                 "tool_tokens", "total_tokens", "tts_characters", "calculated_cost_usd",
                 "calculated_cost_status", "priced_calls", "unpriced_calls", "partially_priced_calls",
                 "calculated_token_cost_usd", "calculated_voice_cost_usd", "calculated_other_cost_usd",
                 "rate_basis", "rate_versions", "rates_verified_at", "rate_coverage_reasons",
                 "calculation_assumptions", "historical_prices_verified", "cost_exclusions", "billed_cost_usd",
                 "billed_cost_available", "billed_cost_status", "unknown_calls", "legacy_calls"]


def _csv_safe(value):
    text = str(value or "")
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text


def _csv_field(value):
    return "; ".join(value) if isinstance(value, list) else value


def profiles_csv(db, *, start=None, end=None, search=""):
    """Export every matching profile in bounded pages, independent of UI pagination."""
    start, end = resolve_range(start, end)
    output = StringIO()
    writer = csv.writer(output)
    fields = EXPORT_FIELDS
    writer.writerow(["Profile ID", "Name", "Email", "From UTC", "To UTC"] +
                    [f"{scope} {key}" for scope in ("Range", "Lifetime recorded") for key in fields])
    safe, field_value = _csv_safe, _csv_field
    activity = profile_activity(db, start, end)
    last_id = 0
    while True:
        users = (profile_query(db, search, activity=activity).filter(models.User.id > last_id)
                 .order_by(models.User.id).limit(250).all())
        if not users:
            break
        for row in profile_rows(db, users, start, end):
            writer.writerow([row["user_id"], safe(row["name"]), safe(row["email"]), start, end] +
                            [field_value(row[scope][key]) for scope in ("range", "lifetime") for key in fields])
        last_id = users[-1].id
    return "\ufeff" + output.getvalue()


# Every recorded call lands in exactly one of these buckets; together they are the whole ledger,
# which is what the imported Google charge for the same dates should be compared with.
ACCOUNT_BUCKETS = (
    ("b2c", "B2C profiles", "Students on the individual product, including AI run for them in the background."),
    ("b2b", "Enterprise organisations", "Consultancy workspaces and their clients: Copilot, Deep Scan, Course Finder, Writing Studio."),
    ("shared", "Shared platform work", "Rilono's own background jobs such as news ingestion and catalog refresh, tied to no account."),
    ("unattributed", "Unattributed calls", "Calls recorded without an account or product classification, mostly older records."),
)
ACCOUNTS_NOTE = ("Every recorded call is counted once, in one bucket. Google bills the project as a whole and never names an "
                 "account, so the split comes from the app ledger; the ledger total is what the imported Google charge for "
                 "the same dates should be compared with. Calls before 2026-09-07 ran on a different Google account.")
UNKNOWN_ORGANIZATION = "Enterprise (organisation not recorded)"


def _bucket_expr():
    E = models.GeminiUsageEvent
    return case((or_(E.organization_id.isnot(None), E.product == "b2b"), "b2b"),
                (b2c_filter(), "b2c"),
                (E.product == "shared", "shared"),
                else_="unattributed")


def event_bucket(event):
    """Python twin of _bucket_expr(); keep the two in step."""
    from app.visa_pass import B2C_COST_SOURCES
    if event.organization_id is not None or event.product == "b2b":
        return "b2b"
    legacy = (event.metering_version if event.metering_version is not None else 1) < 2
    if event.product == "b2c" or (legacy and event.source in B2C_COST_SOURCES):
        return "b2c"
    if event.product == "shared":
        return "shared"
    return "unattributed"


def _google_for_range(db, start, end):
    from app import ai_billing
    try:
        rec = ai_billing.build_reconciliation(db, start=start, end=end)
    except ai_billing.BillingConfigurationError as exc:
        return {"available": False, "status": "not_configured", "message": str(exc)}
    return {"available": bool(rec.get("google_cost_available")), "status": rec.get("status"),
            "billing_status": rec.get("billing_status"), "message": rec.get("message"),
            "cost_before_credits_usd": rec.get("google_cost_usd"), "credits_usd": rec.get("google_credits_usd"),
            "net_cost_usd": rec.get("google_net_cost_usd"), "totals": rec.get("totals") or [],
            "last_synced_at": rec.get("last_synced_at"), "derived": bool(rec.get("derived")),
            "source_range": rec.get("source_range"),
            # Ledger calls before this day cannot be in the import (for example, the old Google account).
            "first_usage_date": min((row.get("usage_date") or "" for row in rec.get("usage_rows") or []), default=None) or None}


def build_usage_by_account(db, *, start=None, end=None):
    """All recorded AI usage for the dates, split by bucket, organisation and feature, plus Google."""
    start, end = resolve_range(start, end)
    E = models.GeminiUsageEvent
    period = range_filter(start, end)
    bucket = _bucket_expr()
    org_key = func.coalesce(E.organization_id, 0)

    def grouped(key, *conditions):
        rows = db.query(key.label("key"), *stat_columns()).filter(*conditions).group_by(key).all()
        return {row[0]: stats_dict(row[1:]) for row in rows}
    bucket_life, bucket_range = grouped(bucket), grouped(bucket, period)
    org_life, org_range = grouped(org_key, bucket == "b2b"), grouped(org_key, bucket == "b2b", period)
    feature_life = {key: grouped(E.source, bucket == key) for key in ("shared", "unattributed")}
    feature_range = {key: grouped(E.source, bucket == key, period) for key in ("shared", "unattributed")}

    # B2C calls the profile table cannot list: accounts flagged enterprise-origin (they cannot sign in to
    # the B2C app, yet background AI can still run for them) and calls with no profile id at all.
    U = models.User
    flagged_ids = {row[0] for row in db.query(U.id).filter(U.is_enterprise_account.is_(True)).all()}
    unlisted = and_(bucket == "b2c", or_(E.user_id.is_(None), E.user_id.in_(sorted(flagged_ids)) if flagged_ids else False))
    user_key = func.coalesce(E.user_id, 0)
    unlisted_life, unlisted_range = grouped(user_key, unlisted), grouped(user_key, unlisted, period)

    costs = {scope: {"bucket": defaultdict(CalculatedCosts), "org": defaultdict(CalculatedCosts),
                     "shared": defaultdict(CalculatedCosts), "unattributed": defaultdict(CalculatedCosts),
                     "unlisted": defaultdict(CalculatedCosts)}
             for scope in ("lifetime", "range")}
    # One streamed scan prices every retained request once; aggregation never re-prices tokens.
    for event in db.query(E).yield_per(1000):
        calculation = ai_cost_calculation.calculate_event(event)
        key = event_bucket(event)
        day = _event_day(event)
        scopes = ("lifetime", "range") if day is not None and start <= day <= end else ("lifetime",)
        for scope in scopes:
            costs[scope]["bucket"][key].add(calculation)
            if key == "b2b":
                costs[scope]["org"][event.organization_id or 0].add(calculation)
            elif key in ("shared", "unattributed"):
                costs[scope][key][event.source].add(calculation)
            elif event.user_id is None or event.user_id in flagged_ids:
                costs[scope]["unlisted"][event.user_id or 0].add(calculation)

    def both(stats_range, stats_life, cost_range, cost_life):
        return {"range": calculated_stats(stats_range, cost_range), "lifetime": calculated_stats(stats_life, cost_life)}
    buckets = [{"key": key, "label": label, "description": description,
                **both(bucket_range.get(key), bucket_life.get(key), costs["range"]["bucket"].get(key), costs["lifetime"]["bucket"].get(key))}
               for key, label, description in ACCOUNT_BUCKETS]
    ledger_costs = {}
    for scope in ("lifetime", "range"):
        merged = CalculatedCosts()
        for part in costs[scope]["bucket"].values():
            merged.merge(part)
        ledger_costs[scope] = merged
    ledger = both(summarize(db, period), summarize(db), ledger_costs["range"], ledger_costs["lifetime"])

    org_ids = [key for key in org_range if key]
    names = {row.id: row for row in db.query(models.EnterpriseOrganization).filter(models.EnterpriseOrganization.id.in_(org_ids)).all()} if org_ids else {}
    organizations = [{"organization_id": key or None,
                      "name": (getattr(names.get(key), "company_name", None) or f"Organisation {key}") if key else UNKNOWN_ORGANIZATION,
                      "subdomain": getattr(names.get(key), "subdomain_slug", None) if key else None,
                      **both(org_range.get(key), org_life.get(key), costs["range"]["org"].get(key), costs["lifetime"]["org"].get(key))}
                     for key in org_range]
    features = {key: [{"source": source, **both(feature_range[key].get(source), feature_life[key].get(source),
                                                 costs["range"][key].get(source), costs["lifetime"][key].get(source))}
                      for source in feature_range[key]] for key in ("shared", "unattributed")}
    unlisted_users = {row.id: row for row in db.query(U).filter(U.id.in_([k for k in unlisted_range if k])).all()} if any(unlisted_range) else {}
    b2c_unlisted = [{"user_id": key or None,
                     "name": (getattr(unlisted_users.get(key), "full_name", None) or getattr(unlisted_users.get(key), "email", None) or f"Profile {key}") if key else "No profile id recorded",
                     "email": getattr(unlisted_users.get(key), "email", None) if key else None,
                     "reason": "enterprise_origin_account" if key else "no_profile_id",
                     **both(unlisted_range.get(key), unlisted_life.get(key), costs["range"]["unlisted"].get(key), costs["lifetime"]["unlisted"].get(key))}
                    for key in unlisted_range]
    unlisted_costs = {}
    for scope in ("lifetime", "range"):
        merged = CalculatedCosts()
        for part in costs[scope]["unlisted"].values():
            merged.merge(part)
        unlisted_costs[scope] = merged
    b2c_unlisted_total = both(summarize(db, unlisted, period), summarize(db, unlisted), unlisted_costs["range"], unlisted_costs["lifetime"])
    by_range_usage = lambda row: (-int(row["range"]["total_tokens"] or 0), -int(row["range"]["calls"] or 0))
    return {"range": {"start": start.isoformat(), "end": end.isoformat()},
            "buckets": buckets, "ledger": ledger, "google": _google_for_range(db, start, end),
            "b2c_unlisted": sorted(b2c_unlisted, key=by_range_usage), "b2c_unlisted_total": b2c_unlisted_total,
            "organizations": sorted(organizations, key=by_range_usage),
            "shared": sorted(features["shared"], key=by_range_usage),
            "unattributed": sorted(features["unattributed"], key=by_range_usage),
            "note": ACCOUNTS_NOTE}


def usage_by_account_csv(db, *, start=None, end=None):
    start, end = resolve_range(start, end)
    data = build_usage_by_account(db, start=start, end=end)
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Section", "Name", "Identifier", "From UTC", "To UTC"] +
                    [f"{scope} {key}" for scope in ("Range", "Lifetime recorded") for key in EXPORT_FIELDS])
    def emit(section, name, identifier, row):
        writer.writerow([section, _csv_safe(name), _csv_safe(identifier), start, end] +
                        [_csv_field(row[scope][key]) for scope in ("range", "lifetime") for key in EXPORT_FIELDS])
    emit("Ledger total", "All recorded AI usage", "", data["ledger"])
    for bucket in data["buckets"]:
        emit("Bucket", bucket["label"], bucket["key"], bucket)
    for row in data["b2c_unlisted"]:
        emit("B2C usage not in the profile table", row["name"], row["email"] or row["reason"], row)
    for org in data["organizations"]:
        emit("Enterprise organisation", org["name"], org["organization_id"] or "", org)
    for key, section in (("shared", "Shared platform work"), ("unattributed", "Unattributed calls")):
        for row in data[key]:
            emit(section, row["source"], "", row)
    return "\ufeff" + output.getvalue()


def recorded_usage_analytics(db, *, start=None, end=None):
    """Retained counters and request-level calculations; stored old estimates stay internal."""
    raw = ai_usage.build_ai_usage_analytics(db, start=start, end=end)
    counter_keys = ("tokens", "calls", "cached_tokens", "tts_characters", "cache_hit_pct", "search_queries")
    def counters(value):
        return {key: value[key] for key in counter_keys if key in value}
    daily = [{"date": row["date"], **counters(row)} for row in raw["daily"]]
    series = [{**{key: row[key] for key in ("date", "end", "label")}, **counters(row)} for row in raw["series"]]
    window = raw["range"]
    top_day = max(daily, key=lambda row: row["tokens"]) if daily else None
    by_source = [{"source": row["source"], "label": row["label"], **counters(row)} for row in raw["by_source"]]
    by_model = [{"model": row["model"], **counters(row)} for row in raw["by_model"]]
    now = datetime.now(timezone.utc)
    cutoffs = {"today": now.replace(hour=0, minute=0, second=0, microsecond=0),
               "last_7_days": now - timedelta(days=7),
               "this_month": now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)}
    totals_costs = {key: CalculatedCosts() for key in raw["totals"]}
    range_costs = CalculatedCosts()
    source_costs, model_costs, daily_costs = (defaultdict(CalculatedCosts) for _ in range(3))
    start_date, end_date = date.fromisoformat(window["start"]), date.fromisoformat(window["end"])
    # This overview intentionally retains its existing all-product scope. Profile
    # reports above apply the B2C filter; neither assigns a project bill to people.
    for event in db.query(models.GeminiUsageEvent).yield_per(1000):
        calculation = ai_cost_calculation.calculate_event(event)
        totals_costs["all_time"].add(calculation)
        stamp = event.created_at
        if stamp and stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        for key, cutoff in cutoffs.items():
            if stamp and stamp >= cutoff:
                totals_costs[key].add(calculation)
        day = _event_day(event)
        if day is not None and start_date <= day <= end_date:
            range_costs.add(calculation)
            source_costs[event.source].add(calculation)
            model_costs[event.model].add(calculation)
            daily_costs[day.isoformat()].add(calculation)
    for row in by_source:
        row.update(source_costs[row["source"]].as_dict())
    for row in by_model:
        row.update(model_costs[row["model"]].as_dict())
    for row in daily:
        row.update(daily_costs[row["date"]].as_dict())
    for row in series:
        costs = CalculatedCosts()
        for day in daily:
            if row["date"] <= day["date"] <= row["end"]:
                costs.merge(daily_costs[day["date"]])
        row.update(costs.as_dict())
    return {"data_status": "recorded_usage", "coverage_note": COVERAGE_NOTE,
            "calculated_cost_scope": "all_retained_ai_usage",
            "totals": {key: {**counters(value), **totals_costs[key].as_dict()} for key, value in raw["totals"].items()},
            "range": {**counters(window), **range_costs.as_dict(),
                      **{key: window[key] for key in ("start", "end", "days", "active_days", "granularity")},
                      "top_day": {"date": top_day["date"], "tokens": top_day["tokens"]} if top_day and top_day["tokens"] else None},
            "earliest_event_date": raw["earliest_event_date"],
            "by_source": sorted(by_source, key=lambda row: row["tokens"], reverse=True),
            "by_model": sorted(by_model, key=lambda row: row["tokens"], reverse=True),
            "daily": daily, "series": series}


def recorded_b2c_revenue(raw):
    """Keep verified sales; no billed B2C allocation exists from a project export."""
    derived_keys = ("gemini_cost_paise", "gemini_cost_display", "gemini_cost_usd", "gross_margin_paise",
                    "gross_margin_display", "margin_pct", "avg_cost_per_pass_paise", "avg_cost_per_pass_display")
    summary = dict(raw["summary"])
    for key in derived_keys:
        summary[key] = "₹0" if key.endswith("_display") else 0
    summary.update(billed_cost_available=False, billed_cost_status="not_attributable", margin_available=False)
    return {"currency": raw["currency"],
            "pass": {key: raw["pass"][key] for key in ("price_paise", "price_display", "duration_days")},
            "summary": summary, "free_feature_usage": raw["free_feature_usage"],
            "cost_by_source": [{"source": row["source"], "calls": row["calls"], "cost_paise": 0,
                                "cost_display": "₹0", "billed_cost_available": False,
                                "billed_cost_status": "not_attributable"} for row in sorted(raw["cost_by_source"], key=lambda item: item["source"])],
            "billing_note": "Revenue contains verified payments. B2C billed cost and margin are 0 because imported Google charges are not attributable to B2C sales."}


def recorded_b2c_accounts(raw):
    """A missing billed profile cost never turns revenue into a claimed profit."""
    def clear_derived(value):
        result = dict(value)
        for key in result:
            if "cost" in key or "profit" in key:
                result[key] = "₹0" if key.endswith("_display") else 0
        result.update(billed_cost_available=False, billed_cost_status="not_attributable", profit_available=False)
        return result
    accounts = sorted((clear_derived(row) for row in raw["accounts"]),
                      key=lambda row: (-row["revenue_paise"], row["user_id"]))
    return {"currency": raw["currency"], "total_accounts": raw["total_accounts"],
            "totals": clear_derived(raw["totals"]), "accounts": accounts,
            "note": "Revenue contains verified payments. Profile billed cost and profit are 0 because no profile-level Google billing attribution is available."}


def recorded_optimization_counts(db):
    """Blocked-event counts are recorded; hypothetical avoided tokens are not usage."""
    E = models.AiOptimizationEvent
    counts = {kind: int(count or 0) for kind, count in db.query(E.kind, func.count(E.id)).group_by(E.kind).all()}
    by_source = [{"source": source, "label": ai_usage.SOURCE_LABELS.get(source, source), "blocks": int(count or 0)}
                 for source, count in db.query(E.source, func.count(E.id)).filter(E.kind == "guardrail_block").group_by(E.source).all()]
    return {"guardrail": {"count": counts.get("guardrail_block", 0)},
            "cache_hits": {"count": counts.get("cache_hit", 0)},
            "cache_misses": {"count": counts.get("cache_miss", 0)},
            "guardrail_blocks_by_source": sorted(by_source, key=lambda row: row["blocks"], reverse=True),
            "data_status": "recorded_event_counts"}
