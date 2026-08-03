"""Org-scoped finance books, analytics and Rilono ROI for the enterprise portal.

`enterprise_payments.py` handles money MOVING (Razorpay Route collection, refunds,
settlement). This module is the accounting layer on top of it: what the consultancy
earned, what it spent, what it is still owed, and what the Rilono platform itself
saved them in staff time and money.

Two ideas make the whole thing consistent:

1. ONE ledger, built at read time. Money that already lives in the platform is never
   copied into the finance tables — collected student payments, the Rilono commission
   on them, credit top-ups, infra fees, refunds and lost chargebacks are DERIVED from
   their own authoritative rows on every request. Only money Rilono cannot see (fees
   collected off-platform, salaries, rent, ads, university commissions received…) is
   stored, in `enterprise_finance_entries`. So there is no sync job, no double
   counting, and no way for the ledger and the analytics to disagree — every number
   on the Finance tab comes from `build_book()`.

2. Savings are measured, not marketed. The ROI panel counts real completed work
   (Deep Scans run, interviews taken, drafts written, documents collected…), multiplies
   by an editable minutes-per-task baseline and the org's own blended hourly cost, and
   then subtracts what the org actually paid Rilono. Every assumption is on screen and
   every one is editable — an unbelievable number is worse than no number.

Money is integer paise, INR only (matching enterprise_payments). Dates are naive UTC.
"""
from __future__ import annotations

import calendar
import json
from datetime import date, datetime, timedelta
from typing import Iterable, Optional

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import enterprise_credits as credits
from app import enterprise_payments as payments
from app import models

# ---------------------------------------------------------------------------
# Categories. Curated on purpose: a fixed set is what makes "expenses by
# category" comparable month over month (free-text categories degenerate into
# "Marketing", "marketing " and "Ads" within a quarter). AUTO_* categories are
# platform-derived and never selectable in the form.
# ---------------------------------------------------------------------------

INCOME_CATEGORIES: dict[str, str] = {
    "student_fee": "Student fees & payments",
    "rilono_refund": "Refund from Rilono",
    "service_fee": "Consulting / service fee",
    "university_commission": "University commission",
    "test_prep": "Test prep & coaching",
    "visa_filing": "Visa & application fees",
    "document_service": "Documentation & translation",
    "travel_forex": "Travel, forex & insurance commission",
    "other_income": "Other income",
}

EXPENSE_CATEGORIES: dict[str, str] = {
    "salaries": "Salaries & wages",
    "agent_commission": "Agent / referral commissions",
    "rent_utilities": "Rent & utilities",
    "marketing": "Marketing & advertising",
    "software": "Software & subscriptions",
    "travel_events": "Travel & events",
    "professional": "Professional & legal fees",
    "office": "Office & admin",
    "taxes": "Taxes & government fees",
    "bank_charges": "Bank & payment charges",
    "student_refund": "Refunds to students",
    "rilono_platform": "Rilono platform fee",
    "rilono_credits": "Rilono AI credits",
    "rilono_plan": "Rilono plan subscription",
    "rilono_infra": "Rilono infrastructure fee",
    "chargeback": "Chargebacks lost",
    "other_expense": "Other expense",
}

# Derived from platform data — shown in the books, never hand-entered.
AUTO_INCOME_CATEGORIES = {"student_fee", "rilono_refund"}
AUTO_EXPENSE_CATEGORIES = {"rilono_platform", "rilono_credits", "rilono_plan", "rilono_infra", "chargeback", "student_refund"}

# Where a ledger row came from.
SOURCE_MANUAL = "manual"
SOURCE_RECURRING = "recurring"
SOURCE_STUDENT_PAYMENT = "student_payment"
SOURCE_STUDENT_REFUND = "student_refund"
SOURCE_RILONO_FEE = "rilono_fee"
SOURCE_RILONO_CREDITS = "rilono_credits"
SOURCE_CHARGEBACK = "chargeback"

SOURCE_LABELS: dict[str, str] = {
    SOURCE_MANUAL: "Recorded by your team",
    SOURCE_RECURRING: "Repeats monthly",
    SOURCE_STUDENT_PAYMENT: "Student payment",
    SOURCE_STUDENT_REFUND: "Refund issued",
    SOURCE_RILONO_FEE: "Rilono fee",
    SOURCE_RILONO_CREDITS: "Rilono billing",
    SOURCE_CHARGEBACK: "Chargeback",
}

# Reuse the same method vocabulary the offline-payment recorder already uses, so a
# fee recorded on a client and an income row recorded here read identically.
PAYMENT_METHODS: dict[str, str] = dict(payments.MANUAL_PAYMENT_METHODS)
PAYMENT_METHODS["razorpay"] = "Online (Razorpay)"

# A student payment counts as INCOME once the money was actually captured. This set is
# enterprise_payments.client_payment_totals' "collected" set PLUS 'refunded': a fully
# refunded payment really did bring money in, and the refund is emitted as its own dated
# expense row — booking the refund without the income would show a phantom loss. 'on_hold'
# stays out (the gateway is holding it, so the cash isn't theirs yet), as do
# created/failed/cancelled.
COLLECTED_PAYMENT_STATUSES = ("paid", "transferred", "settled", "partially_refunded", "refunded")
OUTSTANDING_PAYMENT_STATUSES = ("created",)

# Same per-entry ceiling the payment recorder enforces, so a mistyped amount is
# caught in the books exactly as it would be on a payment.
MAX_AMOUNT_PAISE = payments.MAX_AMOUNT_PAISE

# Row caps per source. Headline figures come from the same capped set the ledger
# shows, so a truncated book is always disclosed in the payload (never silently).
MAX_MANUAL_ENTRIES = 6000
MAX_PAYMENT_ROWS = 20000
MAX_CREDIT_ROWS = 4000
MAX_RECURRING_OCCURRENCES = 240      # 20 years of a monthly template, per entry
MAX_PROJECTED_ROWS = 24000           # total projected occurrences per book (disclosed)
LEDGER_PAGE_SIZE = 50

# Individually listed rows before the tail rolls up into "Others".
TOP_CLIENT_LIMIT = 12
TOP_COUNTERPARTY_LIMIT = 8
TOP_MEMBER_LIMIT = 10
MOM_MONTHS = 6

# ---------------------------------------------------------------------------
# Savings baselines: how long the same task takes WITHOUT Rilono. Deliberately
# conservative — the panel has to survive an owner saying "no, that takes us 20
# minutes", which is exactly why every number here is editable per org.
# ---------------------------------------------------------------------------

SAVINGS_ACTIVITIES: list[dict] = [
    {
        "key": "deep_scan", "label": "Deep Scan dossier audits", "unit": "scan",
        "minutes": 45, "icon": "🔍",
        "manual": "Reading a full client file end to end and writing up every risk by hand.",
    },
    {
        "key": "mock_interview", "label": "AI mock visa interviews", "unit": "interview",
        "minutes": 40, "icon": "🎤",
        "manual": "A counsellor sitting the interview with the student, then writing the feedback.",
    },
    {
        "key": "writing_studio", "label": "SOP / LOR documents drafted", "unit": "document",
        "minutes": 90, "icon": "✍️",
        "manual": "Writing a first-draft statement or recommendation letter from scratch.",
    },
    {
        "key": "writing_refine", "label": "Rewrites of those documents", "unit": "rewrite",
        "minutes": 25, "icon": "🔁",
        "manual": "Reworking a draft by hand after the counsellor's feedback.",
    },
    {
        "key": "course_finder", "label": "Course Finder shortlists", "unit": "shortlist",
        "minutes": 35, "icon": "🎓",
        "manual": "Checking fees, intakes, deadlines and score cut-offs across university sites.",
    },
    {
        "key": "university_match", "label": "AI university shortlists", "unit": "shortlist",
        "minutes": 30, "icon": "🏛",
        "manual": "Building a matched university list by hand from memory and old spreadsheets.",
    },
    {
        "key": "document_collected", "label": "Documents collected by secure link", "unit": "document",
        "minutes": 8, "icon": "📄",
        "manual": "Chasing a document over WhatsApp/email, then renaming and filing it.",
    },
    {
        "key": "client_email", "label": "Emails sent from the client file", "unit": "email",
        "minutes": 6, "icon": "✉️",
        "manual": "Composing in a mail client, attaching files, then logging what was sent.",
    },
    {
        "key": "portal_share", "label": "Client portals shared", "unit": "portal",
        "minutes": 20, "icon": "🔗",
        "manual": "The status calls and 'any update?' emails a self-serve portal answers.",
    },
    {
        "key": "reminder_sent", "label": "Automatic client reminders", "unit": "reminder",
        "minutes": 5, "icon": "⏰",
        "manual": "Remembering the deadline and sending the nudge yourself.",
    },
    {
        "key": "copilot_message", "label": "AI assistant answers", "unit": "answer",
        "minutes": 4, "icon": "✨",
        "manual": "Digging the same answer out of the portal, files and spreadsheets by hand.",
    },
    {
        "key": "payment_collected", "label": "Payments collected online", "unit": "payment",
        "minutes": 10, "icon": "💳",
        "manual": "Sharing bank details, matching a transfer to a student, issuing a receipt.",
    },
]

SAVINGS_ACTIVITY_MAP = {a["key"]: a for a in SAVINGS_ACTIVITIES}

DEFAULT_HOURLY_COST_PAISE = 40000        # ₹400/hour blended counsellor cost
MAX_HOURLY_COST_PAISE = 5_000_00         # ₹5,000/hour — sanity ceiling on the input
# Opening bank balance ceiling: ₹1,000 crore, comfortably inside the BIGINT column and
# far above any real consultancy. A typo is rejected rather than silently truncated.
MAX_OPENING_BALANCE_PAISE = 1_000_00_00_000 * 100
WORKING_HOURS_PER_DAY = 8
DEFAULT_FY_START_MONTH = 4               # Indian financial year: April–March


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _settled_inr_paise(row) -> int:
    """The INR value of a payment/refund row that may not be denominated in INR.

    This whole ledger is INR: the entry form takes rupees, every total is summed as paise
    and the client renders it with the INR formatter. But the rows Rilono bills the org
    (EnterpriseCreditPayment / EnterpriseRefund) now carry their own `currency`, and their
    `amount_paise` is minor units OF THAT CURRENCY — a $12.99 top-up is 1299. Booking that
    integer straight into an INR book records ₹12.99 for a payment of roughly ₹1,100, and
    it feeds "You paid Rilono", the ROI multiple and the cost split.

    Razorpay's own settlement figure (`base_amount_paise`, captured at verify time from the
    payment entity — see money.settled_inr_minor) is the only INR number that may be summed
    here. Never convert with our own FX rate: it will not match the processing bank's and
    the books would drift permanently out of reconciliation. A non-INR row with no
    settlement figure yet returns 0 so the caller drops it — an omission is recoverable,
    a number that is wrong by two orders of magnitude is not.
    """
    currency = str(getattr(row, "currency", None) or "INR").strip().upper()
    if currency == "INR":
        # Charged == settled. Unchanged for every row that predates multi-currency.
        return _int(getattr(row, "amount_paise", 0))
    base = getattr(row, "base_amount_paise", None)
    return _int(base) if base is not None else 0


def _as_date(value) -> Optional[date]:
    """Coerce a stored timestamp/date (tz-aware or not) to a plain date."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)[:19]).date()
    except ValueError:
        return None


def _iso(value) -> Optional[str]:
    d = _as_date(value)
    return d.isoformat() if d else None


def _share(part: int, whole: int) -> float:
    return round((part / whole) * 100, 1) if whole > 0 else 0.0


def _pct_change(current: int, previous: int) -> Optional[float]:
    """Growth vs the previous period. None when there is no base to grow from —
    '+∞%' on the first month with revenue is noise, not insight."""
    if previous == 0:
        return None
    return round(((current - previous) / abs(previous)) * 100, 1)


def format_inr(paise) -> str:
    return credits.format_inr(paise)


def signed_display(paise) -> str:
    """A net figure with the minus OUTSIDE the symbol ("−₹4,200", not "₹-4,200").
    Only used in exported/plain-text surfaces — the UI formats from *_paise so it can
    honour the org's display currency."""
    amount = _int(paise)
    return ("−" if amount < 0 else "") + credits.format_inr(abs(amount))


def category_label(kind: str, key: str | None) -> str:
    table = INCOME_CATEGORIES if kind == "income" else EXPENSE_CATEGORIES
    return table.get(key or "", (key or "Uncategorised").replace("_", " ").title())


def _month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _month_start(d: date) -> date:
    return date(d.year, d.month, 1)


def _month_end(d: date) -> date:
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def _add_months(d: date, months: int) -> date:
    """Same day-of-month `months` later, clamped to the target month's length —
    a rent template dated the 31st still lands on 28 Feb rather than vanishing."""
    total = (d.year * 12 + (d.month - 1)) + months
    year, month = divmod(total, 12)
    month += 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


MAX_TIMELINE_BUCKETS = 400


def _month_sequence(start: date, end: date) -> list[str]:
    """Month keys from start..end. If the span is longer than the axis can draw, the
    OLDEST months are dropped — a chart that hides the current month to show 1994 is
    worse than one that starts late. Totals never come from this list."""
    span = (end.year * 12 + end.month) - (start.year * 12 + start.month) + 1
    if span > MAX_TIMELINE_BUCKETS:
        start = _add_months(_month_start(end), -(MAX_TIMELINE_BUCKETS - 1))
    keys: list[str] = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        keys.append(f"{year:04d}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return keys


# ---------------------------------------------------------------------------
# Ranges. The finance tab thinks in accounting periods (this month, this
# quarter, this financial year), not in "last 7 days".
# ---------------------------------------------------------------------------

RANGE_KEYS = ["this_month", "last_month", "this_quarter", "last_quarter", "this_fy", "last_12m", "all", "custom"]
DEFAULT_RANGE = "this_month"


def _fy_start(today: date, fy_start_month: int) -> date:
    year = today.year if today.month >= fy_start_month else today.year - 1
    return date(year, fy_start_month, 1)


def _quarter_start(today: date, fy_start_month: int) -> date:
    """Quarters are aligned to the org's financial year, not to January."""
    offset = (today.month - fy_start_month) % 12
    return _add_months(date(today.year, today.month, 1), -(offset % 3))


def resolve_range(
    range_key: str | None,
    *,
    start: str | None = None,
    end: str | None = None,
    fy_start_month: int = DEFAULT_FY_START_MONTH,
    today: date | None = None,
) -> dict:
    """Turn a range key (plus optional custom bounds) into concrete dates + a label.

    `start` is None for 'all' (unbounded); `end` is always a real date so a
    projected recurring expense can never run past the period the user asked for.
    """
    today = today or datetime.utcnow().date()
    key = (range_key or DEFAULT_RANGE).strip().lower()
    if key not in RANGE_KEYS:
        key = DEFAULT_RANGE
    fy_start_month = min(12, max(1, _int(fy_start_month, DEFAULT_FY_START_MONTH)))

    if key == "custom":
        s = _parse_date_input(start) or _month_start(today)
        e = _parse_date_input(end) or today
        # Clamp first (a period can't run into the future), THEN order — clamping after a
        # swap can leave start > end when only one bound was supplied.
        s = min(s, today)
        e = min(e, today)
        if s > e:
            s, e = e, s
        return {
            "key": "custom", "start": s, "end": e,
            "label": f"{s.strftime('%d %b %Y')} – {e.strftime('%d %b %Y')}",
        }

    if key == "this_month":
        s, e = _month_start(today), _month_end(today)
        label = today.strftime("%B %Y")
    elif key == "last_month":
        prev = _add_months(_month_start(today), -1)
        s, e = _month_start(prev), _month_end(prev)
        label = prev.strftime("%B %Y")
    elif key == "this_quarter":
        s = _quarter_start(today, fy_start_month)
        e = _month_end(_add_months(s, 2))
        label = f"Quarter · {s.strftime('%b')}–{e.strftime('%b %Y')}"
    elif key == "last_quarter":
        s = _add_months(_quarter_start(today, fy_start_month), -3)
        e = _month_end(_add_months(s, 2))
        label = f"Quarter · {s.strftime('%b')}–{e.strftime('%b %Y')}"
    elif key == "this_fy":
        s = _fy_start(today, fy_start_month)
        e = _month_end(_add_months(s, 11))
        label = (f"FY {s.strftime('%Y')}–{str(e.year)[-2:]}" if fy_start_month != 1
                 else f"FY {s.year}")
    elif key == "last_12m":
        s = _month_start(_add_months(today, -11))
        e = _month_end(today)
        label = "Last 12 months"
    else:  # all
        return {"key": "all", "start": None, "end": today, "label": "All time"}

    # Never let a period run into the future: an accounting period that includes
    # tomorrow makes "this month vs last month" look like a collapse.
    if e > today:
        e = today
    return {"key": key, "start": s, "end": e, "label": label}


def _parse_date_input(value) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return datetime.strptime(str(value).strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def range_payload(rng: dict) -> dict:
    return {
        "key": rng["key"],
        "label": rng["label"],
        "start": rng["start"].isoformat() if rng.get("start") else None,
        "end": rng["end"].isoformat() if rng.get("end") else None,
    }


def _timeline_bucket(start: Optional[date], end: date) -> str:
    """Bucket width that keeps the chart between ~6 and ~90 bars."""
    if start is None:
        return "month"
    span = (end - start).days + 1
    if span <= 62:
        return "day"
    if span <= 400:
        return "week"
    return "month"


def _bucket_key(d: date, bucket: str) -> str:
    if bucket == "day":
        return d.isoformat()
    if bucket == "week":
        return (d - timedelta(days=d.weekday())).isoformat()   # weeks start Monday
    return _month_key(d)


def _bucket_sequence(start: date, end: date, bucket: str) -> list[str]:
    """Every bucket in the period, so a quiet week still draws a zero bar."""
    if bucket == "month":
        return _month_sequence(start, end)
    step = timedelta(days=7 if bucket == "week" else 1)
    cursor = date.fromisoformat(_bucket_key(start, bucket))
    last = _bucket_key(end, bucket)
    keys: list[str] = []
    while True:
        key = cursor.isoformat()
        keys.append(key)
        if key >= last or len(keys) > 800:
            break
        cursor += step
    return keys


# ---------------------------------------------------------------------------
# Per-org finance settings (hourly cost, opening balance, FY start, savings
# baseline overrides).
# ---------------------------------------------------------------------------

def get_or_create_settings(db: Session, organization_id: int, *, commit: bool = True) -> models.EnterpriseFinanceSettings:
    """The org's settings row, created on first read.

    Every finance endpoint calls this, so two concurrent first-ever requests would both
    try to insert — and uq_ent_fin_settings_org makes the loser fail. The IntegrityError
    is caught and the row is re-read, which is the correct resolution: the other request
    created exactly the row we wanted.
    """
    org_id = int(organization_id)

    def _load():
        return (
            db.query(models.EnterpriseFinanceSettings)
            .filter(models.EnterpriseFinanceSettings.organization_id == org_id)
            .first()
        )

    row = _load()
    if row:
        return row
    row = models.EnterpriseFinanceSettings(
        organization_id=org_id,
        hourly_cost_paise=DEFAULT_HOURLY_COST_PAISE,
        opening_balance_paise=0,
        fy_start_month=DEFAULT_FY_START_MONTH,
    )
    db.add(row)
    try:
        if commit:
            db.commit()
            db.refresh(row)
        else:
            db.flush()
    except IntegrityError:
        db.rollback()
        existing = _load()
        if existing is None:      # not the unique-index race — let it surface
            raise
        return existing
    return row


def savings_minutes(settings: models.EnterpriseFinanceSettings | None) -> dict[str, int]:
    """Effective minutes-per-task for every activity: baseline, then org overrides."""
    out = {a["key"]: int(a["minutes"]) for a in SAVINGS_ACTIVITIES}
    raw = getattr(settings, "savings_overrides_json", None) if settings else None
    if raw:
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            parsed = {}
        if isinstance(parsed, dict):
            for key, value in parsed.items():
                if key in out:
                    out[key] = max(0, min(600, _int(value, out[key])))
    return out


def settings_payload(settings: models.EnterpriseFinanceSettings) -> dict:
    minutes = savings_minutes(settings)
    hourly = _int(getattr(settings, "hourly_cost_paise", 0), DEFAULT_HOURLY_COST_PAISE) or DEFAULT_HOURLY_COST_PAISE
    return {
        "hourly_cost_paise": hourly,
        "hourly_cost_display": format_inr(hourly),
        "hourly_cost_default_paise": DEFAULT_HOURLY_COST_PAISE,
        "opening_balance_paise": _int(getattr(settings, "opening_balance_paise", 0)),
        "opening_balance_on": _iso(getattr(settings, "opening_balance_on", None)),
        "fy_start_month": _int(getattr(settings, "fy_start_month", DEFAULT_FY_START_MONTH), DEFAULT_FY_START_MONTH),
        "savings_minutes": minutes,
        "savings_defaults": {a["key"]: int(a["minutes"]) for a in SAVINGS_ACTIVITIES},
        "working_hours_per_day": WORKING_HOURS_PER_DAY,
    }


def categories_payload() -> dict:
    """Selectable categories for the entry form + every label the ledger can show."""
    return {
        "income": [
            {"key": k, "label": v, "auto": k in AUTO_INCOME_CATEGORIES}
            for k, v in INCOME_CATEGORIES.items()
        ],
        "expense": [
            {"key": k, "label": v, "auto": k in AUTO_EXPENSE_CATEGORIES}
            for k, v in EXPENSE_CATEGORIES.items()
        ],
        "payment_methods": [{"key": k, "label": v} for k, v in PAYMENT_METHODS.items()],
        "sources": SOURCE_LABELS,
    }


def normalize_category(kind: str, raw: str | None) -> str:
    """Coerce a submitted category to a selectable key for its kind."""
    key = (raw or "").strip().lower().replace(" ", "_").replace("-", "_")
    if kind == "income":
        if key in INCOME_CATEGORIES and key not in AUTO_INCOME_CATEGORIES:
            return key
        return "other_income"
    if key in EXPENSE_CATEGORIES and key not in AUTO_EXPENSE_CATEGORIES:
        return key
    return "other_expense"


def normalize_method(raw: str | None) -> Optional[str]:
    key = (raw or "").strip().lower().replace(" ", "_")
    return key if key in PAYMENT_METHODS else None


def serialize_entry(entry: models.EnterpriseFinanceEntry) -> dict:
    """The stored row itself (not a ledger line) — what the edit form reads back."""
    kind = "income" if entry.kind == "income" else "expense"
    return {
        "id": entry.id,
        "kind": kind,
        "category": entry.category,
        "category_label": category_label(kind, entry.category),
        "amount_paise": _int(entry.amount_paise),
        "tax_paise": _int(entry.tax_paise),
        "occurred_on": _iso(entry.occurred_on),
        "description": entry.description or "",
        "counterparty": entry.counterparty or "",
        "payment_method": entry.payment_method,
        "reference": entry.reference,
        "notes": entry.notes,
        "client_id": entry.client_id,
        "client_name": entry.client_name_snapshot,
        "repeat_monthly": bool(getattr(entry, "repeat_monthly", False)),
        "repeat_until": _iso(getattr(entry, "repeat_until", None)),
        "created_by": entry.created_by_name,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
    }


def apply_entry_fields(
    entry: models.EnterpriseFinanceEntry,
    payload,
    *,
    client: models.EnterpriseClient | None = None,
    clear_client: bool = False,
) -> models.EnterpriseFinanceEntry:
    """Write a validated request payload onto an entry (create or edit).

    The router owns validation that needs HTTP (400s, org-scoped client lookup); this
    owns the coercion and truncation so both paths land identical rows.
    """
    kind = "income" if (payload.kind or "").strip().lower() == "income" else "expense"
    entry.kind = kind
    entry.category = normalize_category(kind, payload.category)
    entry.amount_paise = max(0, _int(payload.amount_paise))
    entry.tax_paise = max(0, min(_int(getattr(payload, "tax_paise", 0)), entry.amount_paise))
    entry.currency = "INR"
    entry.occurred_on = _parse_date_input(payload.occurred_on) or datetime.utcnow().date()
    entry.description = (payload.description or "").strip()[:300] or None
    entry.counterparty = (getattr(payload, "counterparty", "") or "").strip()[:160] or None
    entry.payment_method = normalize_method(getattr(payload, "payment_method", None))
    entry.reference = (getattr(payload, "reference", "") or "").strip()[:120] or None
    entry.notes = (getattr(payload, "notes", "") or "").strip()[:2000] or None
    entry.repeat_monthly = bool(getattr(payload, "repeat_monthly", False))
    repeat_until = _parse_date_input(getattr(payload, "repeat_until", None))
    # An end date before the start would silently swallow the entry entirely.
    entry.repeat_until = repeat_until if (entry.repeat_monthly and repeat_until
                                         and repeat_until >= entry.occurred_on) else None
    if client is not None:
        entry.client_id = client.id
        entry.client_name_snapshot = client.full_name
    elif clear_client:
        entry.client_id = None
        entry.client_name_snapshot = None
    return entry


# ---------------------------------------------------------------------------
# Ledger row builders. Every builder returns the same normalized shape so the
# ledger, the analytics and the export all read one list of dicts.
# ---------------------------------------------------------------------------

def _row(
    *, row_id: str, kind: str, source: str, category: str, amount_paise: int, occurred_on: date,
    description: str = "", counterparty: str = "", client_id: int | None = None,
    client_name: str | None = None, method: str | None = None, reference: str | None = None,
    tax_paise: int = 0, entry_id: int | None = None, editable: bool = False,
    locked_reason: str | None = None, recurring: bool = False, created_by: str | None = None,
    link: dict | None = None, series_start: date | None = None, repeat_until: date | None = None,
    notes: str | None = None,
) -> dict:
    return {
        "id": row_id,
        "kind": kind,
        "source": source,
        "source_label": SOURCE_LABELS.get(source, source),
        "category": category,
        "category_label": category_label(kind, category),
        "amount_paise": int(amount_paise),
        "amount_display": format_inr(amount_paise),
        "tax_paise": int(tax_paise or 0),
        "occurred_on": occurred_on.isoformat(),
        "description": description or "",
        "counterparty": counterparty or "",
        "client_id": client_id,
        "client_name": client_name,
        "method": method,
        "method_label": PAYMENT_METHODS.get(method or "", None),
        "reference": reference,
        "entry_id": entry_id,
        "editable": bool(editable),
        "locked_reason": locked_reason,
        "recurring": bool(recurring),
        # The template's own date. A projected occurrence is not editable in place, but
        # the UI needs this to open the series that produced it (the template can easily
        # sit outside the period on screen).
        "series_start": series_start.isoformat() if series_start else None,
        "repeat_until": repeat_until.isoformat() if repeat_until else None,
        "notes": notes,
        "created_by": created_by,
        "link": link,
    }


def _in_range(d: date | None, start: Optional[date], end: date) -> bool:
    if d is None:
        return False
    if start is not None and d < start:
        return False
    return d <= end


def _expand_recurring(entry: models.EnterpriseFinanceEntry, start: Optional[date], end: date,
                      today: date) -> list[date]:
    """Dates a monthly template actually falls on inside the period.

    Occurrences are projected at read time instead of being written as rows: no
    cron, no drift, and editing the template retroactively fixes every month.
    They stop at today — a projected future cost is a forecast, not a book entry.
    """
    first = _as_date(entry.occurred_on)
    if not first:
        return []
    if not bool(getattr(entry, "repeat_monthly", False)):
        return [first] if _in_range(first, start, end) else []

    stop = min(end, today)
    until = _as_date(getattr(entry, "repeat_until", None))
    if until:
        stop = min(stop, until)
    if stop < first:
        return [first] if _in_range(first, start, end) else []

    # Start at the first occurrence that can land inside the window instead of counting
    # up from the template's own date — a template from 2005 would otherwise burn the
    # occurrence cap long before reaching the period the user asked for.
    index = 0
    if start is not None and start > first:
        index = max(0, (start.year - first.year) * 12 + (start.month - first.month) - 1)

    dates: list[date] = []
    steps = 0
    while steps <= MAX_RECURRING_OCCURRENCES:
        occurrence = _add_months(first, index)
        if occurrence > stop:
            break
        if _in_range(occurrence, start, end):
            dates.append(occurrence)
        index += 1
        steps += 1
    return dates


def _manual_rows(db: Session, org_id: int, start: Optional[date], end: date,
                 today: date) -> tuple[list[dict], bool]:
    """Hand-recorded income/expense rows, with monthly templates expanded."""
    E = models.EnterpriseFinanceEntry
    query = db.query(E).filter(E.organization_id == org_id)
    # A template dated before the window can still produce occurrences inside it,
    # so only non-repeating rows can be date-filtered in SQL.
    if start is not None:
        query = query.filter(
            (E.repeat_monthly.is_(True)) | (E.occurred_on >= start)
        )
    query = query.filter((E.repeat_monthly.is_(True)) | (E.occurred_on <= end))
    entries = query.order_by(E.occurred_on.desc(), E.id.desc()).limit(MAX_MANUAL_ENTRIES + 1).all()
    truncated = len(entries) > MAX_MANUAL_ENTRIES
    entries = entries[:MAX_MANUAL_ENTRIES]

    rows: list[dict] = []
    projected = 0
    for entry in entries:
        kind = "income" if entry.kind == "income" else "expense"
        first = _as_date(entry.occurred_on)
        occurrences = _expand_recurring(entry, start, end, today)
        # A per-entry cap is not enough: thousands of monthly templates over a long window
        # would multiply into a response big enough to hurt the shared server.
        if projected + len(occurrences) > MAX_PROJECTED_ROWS:
            occurrences = occurrences[: max(0, MAX_PROJECTED_ROWS - projected)]
            truncated = True
        projected += len(occurrences)
        for occurrence in occurrences:
            is_template = (occurrence == first)
            rows.append(_row(
                row_id=f"entry-{entry.id}" if is_template else f"entry-{entry.id}@{_month_key(occurrence)}",
                kind=kind,
                source=SOURCE_MANUAL if is_template else SOURCE_RECURRING,
                category=entry.category,
                amount_paise=_int(entry.amount_paise),
                occurred_on=occurrence,
                description=entry.description or "",
                counterparty=entry.counterparty or "",
                client_id=entry.client_id,
                client_name=entry.client_name_snapshot,
                method=entry.payment_method,
                reference=entry.reference,
                tax_paise=_int(entry.tax_paise),
                entry_id=entry.id,
                editable=is_template,
                locked_reason=None if is_template else (
                    f"One month of a series that started {first.strftime('%d %b %Y')} — editing it changes every month."
                    if first else "Projected from a monthly entry."
                ),
                recurring=bool(getattr(entry, "repeat_monthly", False)),
                series_start=first if bool(getattr(entry, "repeat_monthly", False)) else None,
                repeat_until=_as_date(getattr(entry, "repeat_until", None)),
                notes=entry.notes,
                created_by=entry.created_by_name,
            ))
    return rows, truncated


def _payment_rows(db: Session, org_id: int, start: Optional[date], end: date) -> tuple[list[dict], bool]:
    """Collected student payments → income, Rilono's cut → expense, refunds and
    lost chargebacks → their own dated rows."""
    P = models.EnterpriseStudentPayment
    query = db.query(P).filter(
        P.organization_id == org_id,
        P.status.in_(COLLECTED_PAYMENT_STATUSES),
    )
    if start is not None:
        query = query.filter(func.coalesce(P.paid_at, P.created_at) >= datetime.combine(start, datetime.min.time()))
    query = query.filter(
        func.coalesce(P.paid_at, P.created_at) < datetime.combine(end + timedelta(days=1), datetime.min.time())
    )
    records = query.order_by(P.id.desc()).limit(MAX_PAYMENT_ROWS + 1).all()
    truncated = len(records) > MAX_PAYMENT_ROWS
    records = records[:MAX_PAYMENT_ROWS]

    rows: list[dict] = []
    for p in records:
        occurred = _as_date(p.paid_at) or _as_date(p.created_at)
        if not occurred:
            continue
        client_name = p.client_name_snapshot or "Student"
        label = p.description or (p.invoice_number and f"Invoice {p.invoice_number}") or "Student payment"
        is_manual = (p.provider == "manual")
        rows.append(_row(
            row_id=f"pay-{p.id}",
            kind="income",
            source=SOURCE_STUDENT_PAYMENT,
            category="student_fee",
            amount_paise=_int(p.amount_paise),
            occurred_on=occurred,
            description=label,
            counterparty=client_name,
            client_id=p.client_id,
            client_name=client_name,
            method=(p.manual_method if is_manual else "razorpay"),
            reference=p.invoice_number or p.utr,
            editable=False,
            locked_reason=(
                "Recorded on the client's Payments tab — edit it there."
                if is_manual else
                "Collected online through Rilono. Payment records can't be edited."
            ),
            link={"type": "client_payments", "client_id": p.client_id} if p.client_id else None,
        ))
        commission = _int(p.commission_paise)
        # A FULL refund reverses the transfer, which claws Rilono's commission back too
        # (issue_full_refund sets reverse_all). Booking the fee as a cost in that case
        # would charge the org for a fee they got back.
        if commission > 0 and p.status != "refunded":
            rows.append(_row(
                row_id=f"fee-{p.id}",
                kind="expense",
                source=SOURCE_RILONO_FEE,
                category="rilono_platform",
                amount_paise=commission,
                occurred_on=occurred,
                description=f"Rilono collection fee on {format_inr(p.amount_paise)} from {client_name}",
                counterparty="Rilono",
                client_id=p.client_id,
                client_name=client_name,
                method="razorpay",
                reference=p.invoice_number,
                editable=False,
                locked_reason="Deducted automatically when the payment settled.",
            ))
    return rows, truncated


def _refund_rows(db: Session, org_id: int, start: Optional[date], end: date) -> list[dict]:
    """Refunds returned to students. Dated when they were issued, so a refund in
    July never rewrites June's revenue."""
    R = models.EnterprisePaymentRefund
    query = db.query(R).filter(R.organization_id == org_id, R.status != "failed")
    if start is not None:
        query = query.filter(R.created_at >= datetime.combine(start, datetime.min.time()))
    query = query.filter(R.created_at < datetime.combine(end + timedelta(days=1), datetime.min.time()))
    refunds = query.order_by(R.id.desc()).limit(MAX_CREDIT_ROWS).all()

    # Carry the student AND their client_id across from the payment: a refund is a direct
    # cost of that case, and per-client profit would otherwise count the fee they paid
    # without the money handed back.
    payment_ids = [r.student_payment_id for r in refunds if r.student_payment_id]
    owners: dict[int, tuple] = {}
    if payment_ids:
        for pid, name, client_id, invoice in (
            db.query(
                models.EnterpriseStudentPayment.id,
                models.EnterpriseStudentPayment.client_name_snapshot,
                models.EnterpriseStudentPayment.client_id,
                models.EnterpriseStudentPayment.invoice_number,
            )
            .filter(
                models.EnterpriseStudentPayment.organization_id == org_id,
                models.EnterpriseStudentPayment.id.in_(payment_ids),
            )
            .all()
        ):
            owners[pid] = (name or "Student", client_id, invoice)

    rows: list[dict] = []
    for r in refunds:
        occurred = _as_date(r.created_at)
        amount = _int(r.amount_paise)
        if not occurred or amount <= 0:
            continue
        who, client_id, invoice = owners.get(r.student_payment_id or 0, ("Student", None, None))
        rows.append(_row(
            row_id=f"refund-{r.id}",
            kind="expense",
            source=SOURCE_STUDENT_REFUND,
            category="student_refund",
            amount_paise=amount,
            occurred_on=occurred,
            description=f"Refund issued to {who}" + (f" · {r.reason.strip()[:120]}" if r.reason else ""),
            counterparty=who,
            client_id=client_id,
            client_name=who,
            reference=invoice,
            method="razorpay",
            editable=False,
            locked_reason="Issued from the client's Payments tab.",
            created_by=r.created_by_name,
        ))
    return rows


def _unrecorded_refund_rows(db: Session, org_id: int, start: Optional[date], end: date) -> list[dict]:
    """Refunds the gateway knows about but the app has no audit row for.

    `refund.processed` webhooks bump EnterpriseStudentPayment.refunded_amount_paise but only
    mark an EXISTING EnterprisePaymentRefund as processed — a refund issued straight from the
    Razorpay dashboard therefore leaves no audit row. Without this pass the income row would
    stand alone and the books would overstate profit by the refunded amount. So: reconcile the
    payment's own refunded total against its audit rows and book the difference.
    """
    P = models.EnterpriseStudentPayment
    R = models.EnterprisePaymentRefund
    E = models.EnterprisePaymentEvent

    # Candidates are chosen WITHOUT a date filter, then dated from the refund's own
    # webhook event. `updated_at` cannot be the filter or the date: any later write to
    # the payment row (a settlement webhook, a dispute update) moves it, and a book entry
    # that changes period on unrelated activity is not a book entry.
    candidates = (
        db.query(P)
        .filter(
            P.organization_id == org_id,
            P.refunded_amount_paise > 0,
            P.status.in_(COLLECTED_PAYMENT_STATUSES),
        )
        .order_by(P.id.desc())
        .limit(MAX_PAYMENT_ROWS)
        .all()
    )
    if not candidates:
        return []
    payment_ids = [p.id for p in candidates]

    recorded: dict[int, int] = {}
    for payment_id, total in (
        db.query(R.student_payment_id, func.coalesce(func.sum(R.amount_paise), 0))
        .filter(
            R.organization_id == org_id,
            R.status != "failed",
            R.student_payment_id.in_(payment_ids),
        )
        .group_by(R.student_payment_id)
        .all()
    ):
        recorded[int(payment_id)] = _int(total)

    # When the refund arrived by webhook, its event row carries the real date.
    event_dates: dict[int, datetime] = {}
    for payment_id, stamp in (
        db.query(E.student_payment_id, func.max(E.created_at))
        .filter(
            E.student_payment_id.in_(payment_ids),
            E.event_type.like("refund%"),
        )
        .group_by(E.student_payment_id)
        .all()
    ):
        if payment_id is not None and stamp is not None:
            event_dates[int(payment_id)] = stamp

    rows: list[dict] = []
    for p in candidates:
        shortfall = _int(p.refunded_amount_paise) - recorded.get(p.id, 0)
        if shortfall <= 0:
            continue
        occurred = _as_date(event_dates.get(p.id)) or _as_date(p.paid_at) or _as_date(p.created_at)
        if not occurred or not _in_range(occurred, start, end):
            continue
        who = p.client_name_snapshot or "Student"
        rows.append(_row(
            row_id=f"gwrefund-{p.id}",
            kind="expense",
            source=SOURCE_STUDENT_REFUND,
            category="student_refund",
            amount_paise=shortfall,
            occurred_on=occurred,
            description=f"Refund to {who} recorded by the payment gateway",
            counterparty=who,
            client_id=p.client_id,
            client_name=who,
            method="razorpay",
            reference=p.invoice_number,
            editable=False,
            locked_reason=(
                "Reconciled from the gateway — this refund was issued outside Rilono, so it has "
                "no in-app record. Refund from the client's Payments tab to keep the trail here."
            ),
        ))
    return rows


def _chargeback_rows(db: Session, org_id: int, start: Optional[date], end: date) -> list[dict]:
    """Disputes the org lost — real money out, and easy to forget at month end.

    A lost dispute usually claws the money back through a refund/adjustment (see the note
    in enterprise_payments.apply_webhook_event), which bumps the payment's
    refunded_amount_paise — and that is already booked out by the refund passes above.
    Booking the dispute again would take the same rupees out twice, so only the portion
    the refund path does NOT cover is booked here.
    """
    D = models.EnterprisePaymentDispute
    P = models.EnterpriseStudentPayment
    query = db.query(D).filter(D.organization_id == org_id, D.status == "lost")
    stamp = func.coalesce(D.resolved_at, D.created_at)
    if start is not None:
        query = query.filter(stamp >= datetime.combine(start, datetime.min.time()))
    query = query.filter(stamp < datetime.combine(end + timedelta(days=1), datetime.min.time()))
    disputes = query.order_by(D.id.desc()).limit(MAX_CREDIT_ROWS).all()
    if not disputes:
        return []

    # How much of each disputed payment has already left through the refund path.
    already_out: dict[int, int] = {}
    payment_ids = [d.student_payment_id for d in disputes if d.student_payment_id]
    if payment_ids:
        for payment_id, refunded in (
            db.query(P.id, P.refunded_amount_paise)
            .filter(P.organization_id == org_id, P.id.in_(payment_ids))
            .all()
        ):
            already_out[int(payment_id)] = _int(refunded)

    rows: list[dict] = []
    for d in disputes:
        occurred = _as_date(d.resolved_at) or _as_date(d.created_at)
        amount = _int(d.amount_paise)
        if not occurred or amount <= 0:
            continue
        covered = already_out.get(d.student_payment_id or 0, 0)
        uncovered = amount - covered
        if uncovered <= 0:
            continue          # the refund passes already booked this money out
        rows.append(_row(
            row_id=f"dispute-{d.id}",
            kind="expense",
            source=SOURCE_CHARGEBACK,
            category="chargeback",
            amount_paise=uncovered,
            occurred_on=occurred,
            description=(
                "Chargeback lost" + (f" · {d.reason_code}" if d.reason_code else "")
                + (f" (net of {format_inr(covered)} already refunded)" if covered else "")
            ),
            counterparty="Card issuer",
            method="razorpay",
            editable=False,
            locked_reason="Recorded from the payment gateway's dispute outcome.",
        ))
    return rows


def _rilono_billing_rows(db: Session, org_id: int, start: Optional[date], end: date) -> list[dict]:
    """What the org paid Rilono: AI credit top-ups and the infrastructure fee."""
    C = models.EnterpriseCreditPayment
    stamp = func.coalesce(C.verified_at, C.created_at)
    query = db.query(C).filter(
        C.organization_id == org_id,
        C.status.in_(("verified", "partially_refunded", "refunded")),
    )
    if start is not None:
        query = query.filter(stamp >= datetime.combine(start, datetime.min.time()))
    query = query.filter(stamp < datetime.combine(end + timedelta(days=1), datetime.min.time()))

    rows: list[dict] = []
    for c in query.order_by(C.id.desc()).limit(MAX_CREDIT_ROWS).all():
        occurred = _as_date(c.verified_at) or _as_date(c.created_at)
        # NOT _int(c.amount_paise): that is minor units of c.currency, so a non-INR top-up
        # would be booked into this INR ledger at ~1/85th of what the org actually paid.
        gross = _settled_inr_paise(c)
        if not occurred or gross <= 0:
            continue
        is_infra = (c.kind == "infra_fee")
        total_credits = _int(c.credits) + _int(c.bonus_credits)
        description = ("Rilono infrastructure fee" if is_infra
                       else f"Rilono AI credits top-up · {total_credits} credits")
        rows.append(_row(
            row_id=f"rilono-{c.id}",
            kind="expense",
            source=SOURCE_RILONO_CREDITS,
            category="rilono_infra" if is_infra else "rilono_credits",
            amount_paise=gross,
            occurred_on=occurred,
            description=description,
            counterparty="Rilono",
            method="razorpay",
            reference=c.razorpay_payment_id or c.razorpay_order_id,
            editable=False,
            locked_reason="Billed by Rilono — see Credits & Billing for the receipt.",
        ))

    # Rilono plan subscriptions. These live in a DIFFERENT table from credit top-ups
    # (EnterpriseSubscriptionPayment), so before the tiered plans launched on 2026-08-02
    # nothing here read it — and an org's own books would have shown their AI top-ups but
    # not the monthly plan fee that is now their largest Rilono line.
    S = models.EnterpriseSubscriptionPayment
    sub_stamp = func.coalesce(S.verified_at, S.created_at)
    sub_query = db.query(S).filter(
        S.organization_id == org_id,
        S.status.in_(("verified", "partially_refunded", "refunded")),
    )
    if start is not None:
        sub_query = sub_query.filter(sub_stamp >= datetime.combine(start, datetime.min.time()))
    sub_query = sub_query.filter(sub_stamp < datetime.combine(end + timedelta(days=1), datetime.min.time()))
    for sp in sub_query.order_by(S.id.desc()).limit(MAX_CREDIT_ROWS).all():
        occurred = _as_date(sp.verified_at) or _as_date(sp.created_at)
        # The plan book is INR-only; anything else would be a bug, and booking cents as
        # paise is exactly the error the credit loop above guards against.
        if (sp.currency or "INR").strip().upper() != "INR":
            continue
        gross = _int(sp.amount_paise)
        if not occurred or gross <= 0:
            continue
        label = str(sp.plan or "").replace("_", " ").title() or "Rilono"
        tax = _int(sp.tax_paise)
        rows.append(_row(
            row_id=f"rilono-plan-{sp.id}",
            kind="expense",
            source=SOURCE_RILONO_CREDITS,
            category="rilono_plan",
            # The full charge INCLUDING GST is what left the bank account, so that is what
            # the expense row is. `tax_paise` records the recoverable input-credit portion.
            amount_paise=gross,
            tax_paise=tax,
            occurred_on=occurred,
            description=f"Rilono {label} plan · monthly subscription",
            counterparty="Rilono",
            method="razorpay",
            reference=sp.razorpay_payment_id or sp.razorpay_order_id,
            editable=False,
            locked_reason="Billed by Rilono — see Plans & Billing for the receipt.",
        ))

    # Money Rilono sent back. Dated when the refund was issued rather than netted off the
    # original charge — netting would silently restate a month that was already closed.
    F = models.EnterpriseRefund
    refunds = db.query(F).filter(
        F.organization_id == org_id,
        F.kind == "money",
        F.status != "failed",
        F.amount_paise > 0,
    )
    if start is not None:
        refunds = refunds.filter(F.created_at >= datetime.combine(start, datetime.min.time()))
    refunds = refunds.filter(F.created_at < datetime.combine(end + timedelta(days=1), datetime.min.time()))
    for r in refunds.order_by(F.id.desc()).limit(MAX_CREDIT_ROWS).all():
        occurred = _as_date(r.created_at)
        # A refund is stored in the currency of the payment it reverses, so the same rule
        # as the charge above applies. EnterpriseRefund carries no settlement column, so a
        # non-INR refund is dropped rather than booked as rupees — it would otherwise
        # overstate income here and be netted off "You paid Rilono" at the wrong scale.
        back = _settled_inr_paise(r)
        if not occurred or back <= 0:
            continue
        rows.append(_row(
            row_id=f"rilonoref-{r.id}",
            kind="income",
            source=SOURCE_RILONO_CREDITS,
            category="rilono_refund",
            amount_paise=back,
            occurred_on=occurred,
            description="Refund from Rilono" + (f" · {r.reason.strip()[:120]}" if r.reason else ""),
            counterparty="Rilono",
            method="razorpay",
            reference=r.razorpay_refund_id,
            editable=False,
            locked_reason="Issued by Rilono — see Credits & Billing for the receipt.",
        ))
    return rows


def new_cache() -> dict:
    """A per-REQUEST memo for build_book. One HTTP request can legitimately ask for the
    same period more than once (the export builds the ledger, the analytics and the
    savings, all over the selected period), and each build is ~6 queries. Never hold one
    across requests — it would serve a stale book after a write."""
    return {}


def build_book(db: Session, organization_id: int, rng: dict, *, today: date | None = None,
               cache: dict | None = None) -> dict:
    """The org's complete ledger for a period: stored entries + derived platform rows.

    Everything the Finance tab shows is computed from this one list, so the ledger
    and the analytics can never drift apart.
    """
    org_id = int(organization_id)
    today = today or datetime.utcnow().date()
    start, end = rng.get("start"), rng.get("end") or today

    if cache is not None:
        key = (org_id, start, end, today)
        hit = cache.get(key)
        if hit is not None:
            return hit

    manual, manual_truncated = _manual_rows(db, org_id, start, end, today)
    payment_rows, payments_truncated = _payment_rows(db, org_id, start, end)
    rows = manual + payment_rows
    rows += _refund_rows(db, org_id, start, end)
    rows += _unrecorded_refund_rows(db, org_id, start, end)
    rows += _chargeback_rows(db, org_id, start, end)
    rows += _rilono_billing_rows(db, org_id, start, end)
    rows.sort(key=lambda r: (r["occurred_on"], r["id"]), reverse=True)

    book = {
        "rows": rows,
        "truncated": bool(manual_truncated or payments_truncated),
        "truncated_note": (
            "This period has more rows than the ledger can show at once — narrow the "
            "period or export the book for the complete list."
            if (manual_truncated or payments_truncated) else None
        ),
    }
    if cache is not None:
        cache[(org_id, start, end, today)] = book
    return book


# ---------------------------------------------------------------------------
# Totals & the ledger page
# ---------------------------------------------------------------------------

def summarize(rows: Iterable[dict]) -> dict:
    income = expense = 0
    income_count = expense_count = 0
    rilono_cost = tax_collected = 0
    for r in rows:
        amount = _int(r["amount_paise"])
        if r["kind"] == "income":
            income += amount
            income_count += 1
        else:
            expense += amount
            expense_count += 1
            if r["category"] in ("rilono_platform", "rilono_credits", "rilono_plan", "rilono_infra"):
                rilono_cost += amount
        tax_collected += _int(r.get("tax_paise"))
    net = income - expense
    # Margin is only meaningful against income; with no income at all it is undefined
    # rather than 0% (and must never render as "-0%").
    margin = 0.0 if income <= 0 else (_share(net, income) if net >= 0 else -_share(-net, income))
    return {
        "income_paise": income,
        "expense_paise": expense,
        "net_paise": net,
        "margin_pct": margin,
        "margin_is_meaningful": income > 0,
        "income_count": income_count,
        "expense_count": expense_count,
        "entry_count": income_count + expense_count,
        "rilono_cost_paise": rilono_cost,
        "tax_paise": tax_collected,
        "income_display": format_inr(income),
        "expense_display": format_inr(expense),
        "net_display": signed_display(net),
    }


def filter_rows(rows: list[dict], *, kind: str | None = None, category: str | None = None,
                source: str | None = None, client_id: int | None = None, q: str | None = None) -> list[dict]:
    needle = (q or "").strip().lower()
    out = []
    for r in rows:
        if kind in ("income", "expense") and r["kind"] != kind:
            continue
        if category and r["category"] != category:
            continue
        if source and r["source"] != source:
            continue
        if client_id and r.get("client_id") != client_id:
            continue
        if needle:
            haystack = " ".join(filter(None, [
                r.get("description"), r.get("counterparty"), r.get("client_name"),
                r.get("reference"), r.get("category_label"),
            ])).lower()
            if needle not in haystack:
                continue
        out.append(r)
    return out


def ledger_page(rows: list[dict], *, offset: int = 0, limit: int = LEDGER_PAGE_SIZE) -> dict:
    limit = max(1, min(200, _int(limit, LEDGER_PAGE_SIZE)))
    offset = max(0, _int(offset))
    return {
        "rows": rows[offset:offset + limit],
        "total": len(rows),
        "offset": offset,
        "limit": limit,
        "has_more": (offset + limit) < len(rows),
    }


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

def _by_category(rows: list[dict], kind: str) -> list[dict]:
    buckets: dict[str, dict] = {}
    total = 0
    for r in rows:
        if r["kind"] != kind:
            continue
        amount = _int(r["amount_paise"])
        total += amount
        bucket = buckets.setdefault(r["category"], {
            "key": r["category"], "label": r["category_label"], "amount_paise": 0, "count": 0,
            "auto": r["category"] in (AUTO_INCOME_CATEGORIES if kind == "income" else AUTO_EXPENSE_CATEGORIES),
        })
        bucket["amount_paise"] += amount
        bucket["count"] += 1
    out = sorted(buckets.values(), key=lambda b: b["amount_paise"], reverse=True)
    for bucket in out:
        bucket["share_pct"] = _share(bucket["amount_paise"], total)
        bucket["amount_display"] = format_inr(bucket["amount_paise"])
    return out


def _timeline(rows: list[dict], start: Optional[date], end: date) -> dict:
    first_row = min((r["occurred_on"] for r in rows), default=None)
    effective_start = start or (_parse_date_input(first_row) or _month_start(end))
    if effective_start > end:
        effective_start = _month_start(end)
    bucket = _timeline_bucket(start, end)
    keys = _bucket_sequence(effective_start, end, bucket)
    index = {k: {"key": k, "income_paise": 0, "expense_paise": 0} for k in keys}

    for r in rows:
        d = _parse_date_input(r["occurred_on"])
        if not d:
            continue
        key = _bucket_key(d, bucket)
        point = index.get(key)
        if point is None:      # a row outside the drawn axis (only when capped)
            continue
        if r["kind"] == "income":
            point["income_paise"] += _int(r["amount_paise"])
        else:
            point["expense_paise"] += _int(r["amount_paise"])

    points = []
    for key in keys:
        point = index[key]
        point["net_paise"] = point["income_paise"] - point["expense_paise"]
        points.append(point)
    peak = max([max(p["income_paise"], p["expense_paise"]) for p in points], default=0)
    return {
        "bucket": bucket,
        "points": points,
        "peak_paise": peak,
        "peak_display": format_inr(peak),
    }


def _by_client(db: Session, org_id: int, rows: list[dict]) -> dict:
    """Per-case profitability: fees in, directly-attributed costs out."""
    buckets: dict[int, dict] = {}
    unassigned_income = unassigned_expense = 0
    for r in rows:
        client_id = r.get("client_id")
        amount = _int(r["amount_paise"])
        if not client_id:
            if r["kind"] == "income":
                unassigned_income += amount
            else:
                unassigned_expense += amount
            continue
        bucket = buckets.setdefault(client_id, {
            "client_id": client_id, "name": r.get("client_name") or "Client",
            "income_paise": 0, "expense_paise": 0, "count": 0,
        })
        bucket["count"] += 1
        if r["kind"] == "income":
            bucket["income_paise"] += amount
        else:
            bucket["expense_paise"] += amount

    # Which of those clients still exist (a deleted client keeps its money rows).
    alive: dict[int, str] = {}
    if buckets:
        for cid, name in (
            db.query(models.EnterpriseClient.id, models.EnterpriseClient.full_name)
            .filter(
                models.EnterpriseClient.organization_id == org_id,
                models.EnterpriseClient.id.in_(list(buckets.keys())),
            ).all()
        ):
            alive[cid] = name

    ranked = sorted(buckets.values(), key=lambda b: b["income_paise"] - b["expense_paise"], reverse=True)
    listed = ranked[:TOP_CLIENT_LIMIT]
    tail = ranked[TOP_CLIENT_LIMIT:]
    out = []
    for bucket in listed:
        net = bucket["income_paise"] - bucket["expense_paise"]
        out.append({
            **bucket,
            "name": alive.get(bucket["client_id"], bucket["name"]),
            "exists": bucket["client_id"] in alive,
            "net_paise": net,
            "margin_pct": _share(net, bucket["income_paise"]) if net >= 0 else -_share(-net, bucket["income_paise"]),
            "income_display": format_inr(bucket["income_paise"]),
            "expense_display": format_inr(bucket["expense_paise"]),
            "net_display": signed_display(net),
        })
    if tail:
        income = sum(b["income_paise"] for b in tail)
        expense = sum(b["expense_paise"] for b in tail)
        out.append({
            "client_id": None, "name": f"{len(tail)} other clients", "exists": False,
            "is_rollup": True, "count": sum(b["count"] for b in tail),
            "income_paise": income, "expense_paise": expense, "net_paise": income - expense,
            "margin_pct": _share(income - expense, income),
            "income_display": format_inr(income), "expense_display": format_inr(expense),
            "net_display": signed_display(income - expense),
        })
    return {
        "clients": out,
        "unassigned_income_paise": unassigned_income,
        "unassigned_expense_paise": unassigned_expense,
        "unassigned_income_display": format_inr(unassigned_income),
        "unassigned_expense_display": format_inr(unassigned_expense),
    }


def _by_counterparty(rows: list[dict]) -> list[dict]:
    buckets: dict[str, dict] = {}
    total = 0
    for r in rows:
        if r["kind"] != "expense":
            continue
        name = (r.get("counterparty") or "").strip() or "Unnamed"
        amount = _int(r["amount_paise"])
        total += amount
        bucket = buckets.setdefault(name, {"name": name, "amount_paise": 0, "count": 0})
        bucket["amount_paise"] += amount
        bucket["count"] += 1
    ranked = sorted(buckets.values(), key=lambda b: b["amount_paise"], reverse=True)[:TOP_COUNTERPARTY_LIMIT]
    for bucket in ranked:
        bucket["share_pct"] = _share(bucket["amount_paise"], total)
        bucket["amount_display"] = format_inr(bucket["amount_paise"])
    return ranked


def _client_dimensions(db: Session, org_id: int, rows: list[dict]) -> dict:
    """Revenue sliced by the client attributes an owner actually steers on:
    destination, lead source and branch."""
    client_ids = {r["client_id"] for r in rows if r.get("client_id") and r["kind"] == "income"}
    if not client_ids:
        return {"destinations": [], "lead_sources": [], "branches": []}

    meta: dict[int, tuple] = {}
    for cid, code, name, source, branch in (
        db.query(
            models.EnterpriseClient.id,
            models.EnterpriseClient.destination_country_code,
            models.EnterpriseClient.destination_country_name,
            models.EnterpriseClient.lead_source,
            models.EnterpriseClient.branch_name,
        ).filter(
            models.EnterpriseClient.organization_id == org_id,
            models.EnterpriseClient.id.in_(list(client_ids)),
        ).all()
    ):
        meta[cid] = (code, name, source, branch)

    dest: dict[str, dict] = {}
    lead: dict[str, dict] = {}
    branch_map: dict[str, dict] = {}
    total = 0
    for r in rows:
        if r["kind"] != "income":
            continue
        info = meta.get(r.get("client_id") or 0)
        if not info:
            continue
        code, name, source, branch = info
        amount = _int(r["amount_paise"])
        total += amount
        d = dest.setdefault(code or "??", {"code": code or "??", "label": name or "Unknown", "amount_paise": 0, "clients": set()})
        d["amount_paise"] += amount
        d["clients"].add(r["client_id"])
        if source:
            l = lead.setdefault(source, {"label": source.replace("_", " ").title(), "amount_paise": 0, "clients": set()})
            l["amount_paise"] += amount
            l["clients"].add(r["client_id"])
        if branch:
            b = branch_map.setdefault(branch, {"label": branch, "amount_paise": 0, "clients": set()})
            b["amount_paise"] += amount
            b["clients"].add(r["client_id"])

    def _finish(bucket_map: dict) -> list[dict]:
        out = []
        for bucket in sorted(bucket_map.values(), key=lambda b: b["amount_paise"], reverse=True)[:10]:
            clients = len(bucket.pop("clients"))
            out.append({
                **bucket,
                "clients": clients,
                "share_pct": _share(bucket["amount_paise"], total),
                "amount_display": format_inr(bucket["amount_paise"]),
                "avg_per_client_display": format_inr(bucket["amount_paise"] // clients if clients else 0),
            })
        return out

    return {"destinations": _finish(dest), "lead_sources": _finish(lead), "branches": _finish(branch_map)}


def _receivables(db: Session, org_id: int, today: date) -> dict:
    """Money raised but not collected, aged. Independent of the period filter — an
    invoice from March is still owed today."""
    P = models.EnterpriseStudentPayment
    records = (
        db.query(P)
        .filter(P.organization_id == org_id, P.status.in_(OUTSTANDING_PAYMENT_STATUSES))
        .order_by(P.created_at.asc())
        .limit(MAX_PAYMENT_ROWS)
        .all()
    )
    buckets = [
        {"key": "not_due", "label": "Not due yet", "amount_paise": 0, "count": 0},
        {"key": "d1_7", "label": "1–7 days late", "amount_paise": 0, "count": 0},
        {"key": "d8_30", "label": "8–30 days late", "amount_paise": 0, "count": 0},
        {"key": "d31_60", "label": "31–60 days late", "amount_paise": 0, "count": 0},
        {"key": "d60_plus", "label": "60+ days late", "amount_paise": 0, "count": 0},
    ]
    index = {b["key"]: b for b in buckets}
    total = overdue = 0
    items: list[dict] = []
    for p in records:
        amount = _int(p.amount_paise)
        if amount <= 0:
            continue
        due = _as_date(p.due_date) or _as_date(p.created_at)
        days_late = (today - due).days if due else 0
        if days_late <= 0:
            key = "not_due"
        elif days_late <= 7:
            key = "d1_7"
        elif days_late <= 30:
            key = "d8_30"
        elif days_late <= 60:
            key = "d31_60"
        else:
            key = "d60_plus"
        index[key]["amount_paise"] += amount
        index[key]["count"] += 1
        total += amount
        if key != "not_due":
            overdue += amount
        if len(items) < 25:
            items.append({
                "payment_id": p.id,
                "client_id": p.client_id,
                "client_name": p.client_name_snapshot or "Student",
                "amount_paise": amount,
                "amount_display": format_inr(amount),
                "invoice_number": p.invoice_number,
                "due_date": _iso(p.due_date),
                "raised_on": _iso(p.created_at),
                "days_late": max(0, days_late),
                "email_sent": bool(p.email_sent_at),
            })
    items.sort(key=lambda i: i["days_late"], reverse=True)
    for bucket in buckets:
        bucket["share_pct"] = _share(bucket["amount_paise"], total)
        bucket["amount_display"] = format_inr(bucket["amount_paise"])
    return {
        "total_paise": total,
        "total_display": format_inr(total),
        "overdue_paise": overdue,
        "overdue_display": format_inr(overdue),
        "count": sum(b["count"] for b in buckets),
        "aging": buckets,
        "oldest": items[:12],
    }


def _collections(db: Session, org_id: int, start: Optional[date], end: date) -> dict:
    """How well the org converts a raised payment request into money in the bank."""
    P = models.EnterpriseStudentPayment
    lo = datetime.combine(start, datetime.min.time()) if start is not None else None
    hi = datetime.combine(end + timedelta(days=1), datetime.min.time())

    # Raised in this period (by when the request was created) → conversion rate.
    raised_q = db.query(P).filter(P.organization_id == org_id, P.status != "cancelled")
    if lo is not None:
        raised_q = raised_q.filter(P.created_at >= lo)
    raised_records = raised_q.filter(P.created_at < hi).limit(MAX_PAYMENT_ROWS).all()

    # Collected in this period (by when the money actually arrived) → matches the ledger's
    # income rows exactly, so the KPI and the books can never disagree.
    paid_stamp = func.coalesce(P.paid_at, P.created_at)
    paid_q = db.query(P).filter(
        P.organization_id == org_id, P.status.in_(COLLECTED_PAYMENT_STATUSES)
    )
    if lo is not None:
        paid_q = paid_q.filter(paid_stamp >= lo)
    paid_records = paid_q.filter(paid_stamp < hi).limit(MAX_PAYMENT_ROWS).all()

    raised = refunded = 0
    raised_count = 0
    raised_collected = 0
    for p in raised_records:
        amount = _int(p.amount_paise)
        raised += amount
        raised_count += 1
        if p.status in COLLECTED_PAYMENT_STATUSES:
            raised_collected += amount
        refunded += _int(p.refunded_amount_paise)

    collected = online = offline = 0
    collected_count = 0
    days_to_pay: list[int] = []
    for p in paid_records:
        amount = _int(p.amount_paise)
        collected += amount
        collected_count += 1
        if p.provider == "manual":
            offline += amount
        else:
            online += amount
        paid_at, created_at = _as_date(p.paid_at), _as_date(p.created_at)
        if paid_at and created_at:
            days_to_pay.append(max(0, (paid_at - created_at).days))

    avg_days = round(sum(days_to_pay) / len(days_to_pay), 1) if days_to_pay else None
    return {
        "raised_paise": raised,
        "raised_display": format_inr(raised),
        "raised_count": raised_count,
        "collected_paise": collected,
        "collected_display": format_inr(collected),
        "collected_count": collected_count,
        "refunded_paise": refunded,
        "refunded_display": format_inr(refunded),
        "collection_rate_pct": _share(raised_collected, raised),
        "avg_days_to_pay": avg_days,
        "avg_invoice_paise": (collected // collected_count) if collected_count else 0,
        "avg_invoice_display": format_inr((collected // collected_count) if collected_count else 0),
        "online_paise": online,
        "online_display": format_inr(online),
        "offline_paise": offline,
        "offline_display": format_inr(offline),
        "online_share_pct": _share(online, collected),
    }


def _by_member(db: Session, org_id: int, start: Optional[date], end: date) -> list[dict]:
    """Who collected the money. Payment requests carry their creator, so this is
    the closest thing to per-counsellor revenue the platform can prove."""
    P = models.EnterpriseStudentPayment
    query = (
        db.query(P.created_by_user_id, func.count(P.id), func.coalesce(func.sum(P.amount_paise), 0))
        .filter(P.organization_id == org_id, P.status.in_(COLLECTED_PAYMENT_STATUSES))
    )
    stamp = func.coalesce(P.paid_at, P.created_at)
    if start is not None:
        query = query.filter(stamp >= datetime.combine(start, datetime.min.time()))
    query = query.filter(stamp < datetime.combine(end + timedelta(days=1), datetime.min.time()))
    rows = query.group_by(P.created_by_user_id).all()
    if not rows:
        return []

    user_ids = [uid for uid, _, _ in rows if uid]
    names: dict[int, str] = {}
    if user_ids:
        for uid, full_name, email in (
            db.query(models.User.id, models.User.full_name, models.User.email)
            .filter(models.User.id.in_(user_ids)).all()
        ):
            names[uid] = full_name or (email or "").split("@")[0] or "Team member"

    total = sum(_int(amount) for _, _, amount in rows)
    out = []
    for uid, count, amount in rows:
        amount = _int(amount)
        out.append({
            "user_id": uid,
            "name": names.get(uid or 0, "Unassigned"),
            "payments": _int(count),
            "amount_paise": amount,
            "amount_display": format_inr(amount),
            "share_pct": _share(amount, total),
        })
    out.sort(key=lambda m: m["amount_paise"], reverse=True)
    return out[:TOP_MEMBER_LIMIT]


def _monthly_trend(db: Session, org_id: int, today: date, fy_start_month: int,
                   months: int = MOM_MONTHS, cache: dict | None = None) -> dict:
    """Complete-month history + a trailing-average projection for next month.

    Built from its own full-range book (not the selected period) so the trend
    stays stable while the user flips the period buttons above it.
    """
    start = _month_start(_add_months(today, -(months - 1)))
    rng = {"key": "custom", "start": start, "end": today, "label": "trend"}
    rows = build_book(db, org_id, rng, today=today, cache=cache)["rows"]

    index = {key: {"key": key, "income_paise": 0, "expense_paise": 0} for key in _month_sequence(start, today)}
    for r in rows:
        d = _parse_date_input(r["occurred_on"])
        if not d:
            continue
        point = index.get(_month_key(d))
        if not point:
            continue
        if r["kind"] == "income":
            point["income_paise"] += _int(r["amount_paise"])
        else:
            point["expense_paise"] += _int(r["amount_paise"])

    series = []
    for key in sorted(index.keys()):
        point = index[key]
        point["net_paise"] = point["income_paise"] - point["expense_paise"]
        point["label"] = datetime.strptime(key, "%Y-%m").strftime("%b %Y")
        point["is_partial"] = (key == _month_key(today))
        series.append(point)

    complete = [p for p in series if not p["is_partial"]]
    current = series[-1] if series else None
    previous = complete[-1] if complete else None
    trailing = complete[-3:]
    projection = None
    if len(trailing) >= 2:
        avg_income = sum(p["income_paise"] for p in trailing) // len(trailing)
        avg_expense = sum(p["expense_paise"] for p in trailing) // len(trailing)
        projection = {
            "months_used": len(trailing),
            "income_paise": avg_income,
            "expense_paise": avg_expense,
            "net_paise": avg_income - avg_expense,
            "income_display": format_inr(avg_income),
            "expense_display": format_inr(avg_expense),
            "net_display": signed_display(avg_income - avg_expense),
            "label": _add_months(_month_start(today), 1).strftime("%b %Y"),
        }
    return {
        "series": series,
        "projection": projection,
        "income_growth_pct": _pct_change(current["income_paise"], previous["income_paise"]) if current and previous else None,
        "net_growth_pct": _pct_change(current["net_paise"], previous["net_paise"]) if current and previous else None,
        "note": "Growth compares the current month so far with the last complete month.",
    }


def _cash_position(db: Session, org_id: int, settings: models.EnterpriseFinanceSettings,
                   today: date, cache: dict | None = None) -> dict:
    """Opening balance + every book entry since it, i.e. money the org should have."""
    opening = _int(getattr(settings, "opening_balance_paise", 0))
    opened_on = _as_date(getattr(settings, "opening_balance_on", None))
    if not (opening or opened_on):
        # Not configured: the UI shows a "set your opening balance" prompt instead, so
        # there is no reason to scan every row the org has ever had.
        return {
            "opening_paise": 0, "opening_display": format_inr(0), "opening_on": None,
            "movement_paise": 0, "balance_paise": 0, "balance_display": format_inr(0),
            "is_configured": False,
        }
    rng = {"key": "custom", "start": opened_on, "end": today, "label": "cash"}
    totals = summarize(build_book(db, org_id, rng, today=today, cache=cache)["rows"])
    balance = opening + totals["net_paise"]
    return {
        "opening_paise": opening,
        "opening_display": format_inr(opening),
        "opening_on": opened_on.isoformat() if opened_on else None,
        "movement_paise": totals["net_paise"],
        "balance_paise": balance,
        "balance_display": signed_display(balance),
        "is_configured": bool(opening or opened_on),
    }


def _previous_period(rng: dict, start: date, end: date) -> tuple[date, date, str]:
    """The comparable preceding period for a range, plus a label for the UI.

    Month/quarter/FY ranges step back one whole unit and are then truncated to the same
    number of elapsed days, so a partial current period is compared against the same slice
    of the previous one. Anything else falls back to an equal-length window.
    """
    key = rng.get("key") or ""
    elapsed = (end - start).days
    if key in ("this_month", "last_month"):
        prev_start = _add_months(_month_start(start), -1)
        label = prev_start.strftime("%B %Y")
    elif key in ("this_quarter", "last_quarter"):
        prev_start = _add_months(start, -3)
        label = f"quarter from {prev_start.strftime('%b %Y')}"
    elif key == "this_fy":
        prev_start = _add_months(start, -12)
        label = f"FY from {prev_start.strftime('%b %Y')}"
    elif key == "last_12m":
        prev_start = _add_months(start, -12)
        label = "the 12 months before that"
    else:
        prev_end = start - timedelta(days=1)
        return prev_end - timedelta(days=elapsed), prev_end, "the previous period"
    # Same elapsed length, never spilling past the unit we stepped back into.
    unit_end = _month_end(_add_months(prev_start, {"this_quarter": 2, "last_quarter": 2}.get(key, 0)))
    if key in ("this_fy", "last_12m"):
        unit_end = _month_end(_add_months(prev_start, 11))
    prev_end = min(prev_start + timedelta(days=elapsed), unit_end)
    return prev_start, prev_end, label


def analytics(db: Session, organization_id: int, rng: dict, *,
              settings: models.EnterpriseFinanceSettings | None = None,
              today: date | None = None, cache: dict | None = None) -> dict:
    """The whole Finance → Overview payload."""
    org_id = int(organization_id)
    today = today or datetime.utcnow().date()
    settings = settings or get_or_create_settings(db, org_id)
    start, end = rng.get("start"), rng.get("end") or today

    book = build_book(db, org_id, rng, today=today, cache=cache)
    rows = book["rows"]
    totals = summarize(rows)

    # "vs previous" has to compare like with like: the SAME calendar unit one step back,
    # truncated to the same elapsed length so a month-to-date is never measured against a
    # full month. A day-count window would compare "this month so far" with a 29-day
    # window straddling two months.
    previous_totals = None
    previous_label = None
    if start is not None:
        prev_start, prev_end, previous_label = _previous_period(rng, start, end)
        previous_totals = summarize(
            build_book(db, org_id, {"key": "custom", "start": prev_start, "end": prev_end,
                                    "label": "previous"}, today=today, cache=cache)["rows"]
        )

    return {
        "range": range_payload(rng),
        "totals": totals,
        "previous": ({
            "label": previous_label,
            "income_paise": previous_totals["income_paise"],
            "expense_paise": previous_totals["expense_paise"],
            "net_paise": previous_totals["net_paise"],
            "income_change_pct": _pct_change(totals["income_paise"], previous_totals["income_paise"]),
            "expense_change_pct": _pct_change(totals["expense_paise"], previous_totals["expense_paise"]),
            "net_change_pct": _pct_change(totals["net_paise"], previous_totals["net_paise"]),
        } if previous_totals else None),
        "timeline": _timeline(rows, start, end),
        "income_by_category": _by_category(rows, "income"),
        "expense_by_category": _by_category(rows, "expense"),
        "by_client": _by_client(db, org_id, rows),
        "top_counterparties": _by_counterparty(rows),
        "dimensions": _client_dimensions(db, org_id, rows),
        "receivables": _receivables(db, org_id, today),
        "collections": _collections(db, org_id, start, end),
        "by_member": _by_member(db, org_id, start, end),
        "trend": _monthly_trend(
            db, org_id, today,
            _int(getattr(settings, "fy_start_month", DEFAULT_FY_START_MONTH), DEFAULT_FY_START_MONTH),
            cache=cache,
        ),
        "cash": _cash_position(db, org_id, settings, today, cache=cache),
        "truncated": book["truncated"],
        "truncated_note": book["truncated_note"],
    }


# ---------------------------------------------------------------------------
# "Saved with Rilono" — measured, editable, and netted against what Rilono cost.
# ---------------------------------------------------------------------------

def _activity_units(db: Session, org_id: int, start: Optional[date], end: date) -> dict[str, int]:
    """Count the real work the platform did for this org in the period."""
    lo = datetime.combine(start, datetime.min.time()) if start else None
    hi = datetime.combine(end + timedelta(days=1), datetime.min.time())

    def _count(model, stamp_column, *filters) -> int:
        query = db.query(func.count()).select_from(model).filter(model.organization_id == org_id, *filters)
        if lo is not None:
            query = query.filter(stamp_column >= lo)
        return _int(query.filter(stamp_column < hi).scalar())

    units: dict[str, int] = {
        "deep_scan": _count(models.EnterpriseClientDeepScan, models.EnterpriseClientDeepScan.created_at),
        "mock_interview": _count(models.EnterpriseInterviewSession, models.EnterpriseInterviewSession.created_at),
        "course_finder": _count(models.EnterpriseCourseFinderRec, models.EnterpriseCourseFinderRec.created_at),
        "client_email": _count(
            models.EnterpriseClientEmail, models.EnterpriseClientEmail.created_at,
            models.EnterpriseClientEmail.direction == "outbound",
            models.EnterpriseClientEmail.status == "sent",
        ),
        "document_collected": _count(
            models.EnterpriseDocumentRequestItem, models.EnterpriseDocumentRequestItem.received_at,
            models.EnterpriseDocumentRequestItem.status == "received",
        ),
        # Only portals the client actually OPENED count — an unopened share saved nobody
        # a status call, and the ROI panel has to survive that objection.
        "portal_share": _count(
            models.EnterpriseClientPortalShare, models.EnterpriseClientPortalShare.created_at,
            models.EnterpriseClientPortalShare.last_opened_at.isnot(None),
        ),
        "reminder_sent": _count(
            models.EnterpriseCalendarEvent, models.EnterpriseCalendarEvent.client_notified_at,
            models.EnterpriseCalendarEvent.client_notified_at.isnot(None),
        ),
        "payment_collected": _count(
            models.EnterpriseStudentPayment,
            func.coalesce(models.EnterpriseStudentPayment.paid_at, models.EnterpriseStudentPayment.created_at),
            models.EnterpriseStudentPayment.status.in_(COLLECTED_PAYMENT_STATUSES),
            models.EnterpriseStudentPayment.provider != "manual",
        ),
    }

    # Writing Studio versions are immutable: version 1 is a new document, every later
    # version in the same root chain is a rewrite. They are worth very different amounts
    # of saved time, so they are counted (and priced) separately.
    W = models.EnterpriseClientWritingDraft
    units["writing_studio"] = _count(W, W.created_at, W.version <= 1)
    units["writing_refine"] = _count(W, W.created_at, W.version > 1)

    # University shortlists and copilot answers leave no table of their own — the
    # credit ledger is their record. Copilot counts BILLED bundles only (the free
    # daily allowance isn't logged), so this under-counts rather than inflates.
    T = models.EnterpriseCreditTransaction
    txn = db.query(T.action_key, func.count(T.id), func.coalesce(func.sum(-T.credits), 0)).filter(
        T.organization_id == org_id, T.type == "debit",
        T.action_key.in_(("university_match", "ai_copilot")),
    )
    if lo is not None:
        txn = txn.filter(T.created_at >= lo)
    for action_key, count, spent in txn.filter(T.created_at < hi).group_by(T.action_key).all():
        if action_key == "university_match":
            units["university_match"] = _int(count)
        else:
            units["copilot_message"] = _int(spent) * credits.COPILOT_MSGS_PER_CREDIT
    units.setdefault("university_match", 0)
    units.setdefault("copilot_message", 0)
    return units


def savings(db: Session, organization_id: int, rng: dict, *,
            settings: models.EnterpriseFinanceSettings | None = None,
            today: date | None = None, cache: dict | None = None) -> dict:
    """Time and money the platform saved this org, net of what they paid Rilono."""
    org_id = int(organization_id)
    today = today or datetime.utcnow().date()
    settings = settings or get_or_create_settings(db, org_id)
    start, end = rng.get("start"), rng.get("end") or today

    hourly = _int(getattr(settings, "hourly_cost_paise", 0), DEFAULT_HOURLY_COST_PAISE) or DEFAULT_HOURLY_COST_PAISE
    minutes_map = savings_minutes(settings)
    defaults = {a["key"]: int(a["minutes"]) for a in SAVINGS_ACTIVITIES}
    units = _activity_units(db, org_id, start, end)

    activities = []
    total_minutes = total_units = 0
    for activity in SAVINGS_ACTIVITIES:
        key = activity["key"]
        count = _int(units.get(key))
        each = _int(minutes_map.get(key), defaults[key])
        minutes = count * each
        total_minutes += minutes
        total_units += count
        activities.append({
            "key": key,
            "label": activity["label"],
            "icon": activity["icon"],
            "unit": activity["unit"],
            "manual_equivalent": activity["manual"],
            "units": count,
            "minutes_each": each,
            "minutes": minutes,
            "hours": round(minutes / 60, 1),
            "value_paise": int(round(minutes / 60 * hourly)),
            "value_display": format_inr(int(round(minutes / 60 * hourly))),
            "is_custom": each != defaults[key],
        })
    activities.sort(key=lambda a: a["minutes"], reverse=True)
    for activity in activities:
        activity["share_pct"] = _share(activity["minutes"], total_minutes)

    hours = total_minutes / 60
    value_paise = int(round(hours * hourly))

    # What Rilono actually cost them in the same period — straight from the book,
    # so the ROI figure can never disagree with the expense ledger.
    book_rows = build_book(db, org_id, rng, today=today, cache=cache)["rows"]
    cost_by_category = {"rilono_credits": 0, "rilono_plan": 0, "rilono_infra": 0, "rilono_platform": 0}
    refunded_by_rilono = 0
    for r in book_rows:
        if r["kind"] == "expense" and r["category"] in cost_by_category:
            cost_by_category[r["category"]] += _int(r["amount_paise"])
        elif r["kind"] == "income" and r["category"] == "rilono_refund":
            refunded_by_rilono += _int(r["amount_paise"])
    # What they actually paid = charges minus anything Rilono refunded in the same period.
    cost_total = max(0, sum(cost_by_category.values()) - refunded_by_rilono)
    net = value_paise - cost_total

    return {
        "range": range_payload(rng),
        "hourly_cost_paise": hourly,
        "hourly_cost_display": format_inr(hourly),
        "activities": activities,
        "totals": {
            "units": total_units,
            "minutes": total_minutes,
            "hours": round(hours, 1),
            "hours_display": f"{hours:,.1f}",
            "workdays": round(hours / WORKING_HOURS_PER_DAY, 1),
            "value_paise": value_paise,
            "value_display": format_inr(value_paise),
        },
        "rilono_cost": {
            "refunded_paise": refunded_by_rilono,
            "refunded_display": format_inr(refunded_by_rilono),
            "credits_paise": cost_by_category["rilono_credits"],
            "credits_display": format_inr(cost_by_category["rilono_credits"]),
            "plan_paise": cost_by_category["rilono_plan"],
            "plan_display": format_inr(cost_by_category["rilono_plan"]),
            "infra_paise": cost_by_category["rilono_infra"],
            "infra_display": format_inr(cost_by_category["rilono_infra"]),
            "platform_fee_paise": cost_by_category["rilono_platform"],
            "platform_fee_display": format_inr(cost_by_category["rilono_platform"]),
            "total_paise": cost_total,
            "total_display": format_inr(cost_total),
        },
        "net_paise": net,
        "net_display": signed_display(net),
        "is_net_positive": net >= 0,
        "roi_multiple": (round(value_paise / cost_total, 1) if cost_total > 0 else None),
        "roi_pct": (round(((value_paise - cost_total) / cost_total) * 100) if cost_total > 0 else None),
        "method_note": (
            "Time saved = how many times your team used each feature × how long the same task "
            "takes by hand. Money saved values that time at your own hourly cost. Both numbers "
            "are yours to change — nothing here is a marketing estimate."
        ),
    }


# ---------------------------------------------------------------------------
# Export. Sections become sheets in the workbook (or stacked blocks in the CSV).
# ---------------------------------------------------------------------------

def export_sections(*, rng: dict, book: dict, ana: dict, save: dict) -> list[dict]:
    totals = ana["totals"]
    summary_rows = [
        ["Rilono — Finance book", rng["label"]],
        ["Generated (UTC)", datetime.utcnow().strftime("%Y-%m-%d %H:%M")],
        [],
        ["Income", totals["income_paise"] / 100],
        ["Expenses", totals["expense_paise"] / 100],
        ["Net profit", totals["net_paise"] / 100],
        ["Margin %", totals["margin_pct"]],
        ["Entries", totals["entry_count"]],
        [],
        ["Outstanding receivables", ana["receivables"]["total_paise"] / 100],
        ["Overdue", ana["receivables"]["overdue_paise"] / 100],
        ["Collection rate %", ana["collections"]["collection_rate_pct"]],
        ["Average days to pay", ana["collections"]["avg_days_to_pay"]],
        [],
        ["Cash balance", ana["cash"]["balance_paise"] / 100],
        [],
        ["Hours saved with Rilono", save["totals"]["hours"]],
        ["Value of time saved", save["totals"]["value_paise"] / 100],
        ["Paid to Rilono", save["rilono_cost"]["total_paise"] / 100],
        ["Net gain", save["net_paise"] / 100],
    ]

    ledger_rows = [[
        "Date", "Type", "Category", "Description", "Client", "Counterparty",
        "Method", "Reference", "Amount (INR)", "Tax (INR)", "Source", "Recorded by",
    ]]
    for r in book["rows"]:
        ledger_rows.append([
            # A real date object, not a string, so Excel sorts and filters the column
            # (the CSV writer stringifies it again) — same trick as the admin export.
            _parse_date_input(r["occurred_on"]) or r["occurred_on"],
            "Income" if r["kind"] == "income" else "Expense",
            r["category_label"],
            r["description"],
            r.get("client_name") or "",
            r.get("counterparty") or "",
            r.get("method_label") or "",
            r.get("reference") or "",
            _int(r["amount_paise"]) / 100,
            _int(r.get("tax_paise")) / 100,
            r["source_label"],
            r.get("created_by") or "",
        ])

    # Always the trailing six months (the trend block), independent of the chosen period.
    monthly_rows = [["Month", "Income (INR)", "Expenses (INR)", "Net (INR)"]]
    for point in ana["trend"]["series"]:
        monthly_rows.append([
            point["label"], point["income_paise"] / 100,
            point["expense_paise"] / 100, point["net_paise"] / 100,
        ])

    category_rows = [["Type", "Category", "Amount (INR)", "Share %", "Entries"]]
    for bucket in ana["income_by_category"]:
        category_rows.append(["Income", bucket["label"], bucket["amount_paise"] / 100, bucket["share_pct"], bucket["count"]])
    for bucket in ana["expense_by_category"]:
        category_rows.append(["Expense", bucket["label"], bucket["amount_paise"] / 100, bucket["share_pct"], bucket["count"]])

    client_rows = [["Client", "Income (INR)", "Direct costs (INR)", "Net (INR)", "Margin %"]]
    for bucket in ana["by_client"]["clients"]:
        client_rows.append([
            bucket["name"], bucket["income_paise"] / 100,
            bucket["expense_paise"] / 100, bucket["net_paise"] / 100, bucket["margin_pct"],
        ])

    receivable_rows = [["Client", "Invoice", "Amount (INR)", "Raised", "Due", "Days late"]]
    for item in ana["receivables"]["oldest"]:
        receivable_rows.append([
            item["client_name"], item.get("invoice_number") or "",
            item["amount_paise"] / 100,
            _parse_date_input(item.get("raised_on")) or "",
            _parse_date_input(item.get("due_date")) or "",
            item["days_late"],
        ])

    savings_rows = [["Activity", "Times used", "Minutes saved each", "Hours saved", "Value (INR)"]]
    for activity in save["activities"]:
        savings_rows.append([
            activity["label"], activity["units"], activity["minutes_each"],
            activity["hours"], activity["value_paise"] / 100,
        ])

    # `money`/`percent`/`date` are 1-based column indexes. Declaring them beats guessing
    # from the Python type — a share of 55.5 is a float too, and Excel would happily
    # render it as ₹55.50.
    return [
        {"title": "Summary", "rows": summary_rows, "is_table": False,
         "money_rows": [4, 5, 6, 10, 11, 15, 18, 19, 20], "money": [2]},
        {"title": "Ledger", "rows": ledger_rows, "is_table": True, "money": [9, 10], "date": [1]},
        {"title": "Last 6 months", "rows": monthly_rows, "is_table": True, "money": [2, 3, 4]},
        {"title": "Categories", "rows": category_rows, "is_table": True, "money": [3], "percent": [4]},
        {"title": "Clients", "rows": client_rows, "is_table": True, "money": [2, 3, 4], "percent": [5]},
        {"title": "Receivables", "rows": receivable_rows, "is_table": True, "money": [3], "date": [4, 5]},
        {"title": "Saved with Rilono", "rows": savings_rows, "is_table": True, "money": [5]},
    ]
