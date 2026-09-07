"""B2C usage reports. Recorded history is never presented as recovered history."""
from __future__ import annotations

import csv
from datetime import date, datetime, time, timedelta, timezone
from io import StringIO

from sqlalchemy import and_, case, func, or_

from app import ai_usage, models


COVERAGE_NOTE = (
    "Lifetime means all retained usage records, not guaranteed usage since signup. "
    "Legacy records can have missing attribution or combined token categories. "
    "A displayed 0 means no recorded value is available; it does not establish that no usage or charge occurred. "
    "Google billing does not identify individual profiles, so profile billed costs remain 0 with an unavailable status. "
    "Shared AI work is shown separately."
)


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


def profile_query(db, search=""):
    U = models.User
    q = db.query(U).filter(U.is_enterprise_account.is_(False))
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
    return [{"user_id": u.id, "name": u.full_name, "email": u.email,
             "range": selected.get(u.id, stats_dict()), "lifetime": lifetime.get(u.id, stats_dict())} for u in users]


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
    q = profile_query(db, search)
    total = q.count()
    users = q.order_by(models.User.id).offset((page - 1) * page_size).limit(page_size).all()
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
    return {"profile": {"user_id": user.id, "name": user.full_name, "email": user.email},
            "range": {"start": start.isoformat(), "end": end.isoformat()},
            "range_totals": summarize(db, *base, range_filter(start, end)),
            "lifetime_totals": summarize(db, *base),
            "features": [{"source": src, "label": ai_usage.SOURCE_LABELS.get(src, src),
                          "range": selected.get(src, stats_dict()), "lifetime": lifetime[src]}
                         for src in sorted(lifetime)], "coverage_note": COVERAGE_NOTE}


def profiles_csv(db, *, start=None, end=None, search=""):
    """Export every matching profile in bounded pages, independent of UI pagination."""
    start, end = resolve_range(start, end)
    output = StringIO()
    writer = csv.writer(output)
    fields = ["calls", "input_tokens", "output_tokens", "thinking_tokens", "cached_tokens",
              "tool_tokens", "total_tokens", "tts_characters", "billed_cost_usd",
              "billed_cost_available", "billed_cost_status", "unknown_calls", "legacy_calls"]
    writer.writerow(["Profile ID", "Name", "Email", "From UTC", "To UTC"] +
                    [f"{scope} {key}" for scope in ("Range", "Lifetime recorded") for key in fields])
    def safe(value):
        text = str(value or "")
        return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text
    last_id = 0
    while True:
        users = profile_query(db, search).filter(models.User.id > last_id).order_by(models.User.id).limit(250).all()
        if not users:
            break
        for row in profile_rows(db, users, start, end):
            writer.writerow([row["user_id"], safe(row["name"]), safe(row["email"]), start, end] +
                            [row[scope][key] for scope in ("range", "lifetime") for key in fields])
        last_id = users[-1].id
    return "\ufeff" + output.getvalue()


def recorded_usage_analytics(db, *, start=None, end=None):
    """Expose retained usage counters only; legacy list-price calculations stay internal."""
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
    return {"data_status": "recorded_usage", "coverage_note": COVERAGE_NOTE,
            "totals": {key: counters(value) for key, value in raw["totals"].items()},
            "range": {**counters(window),
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
