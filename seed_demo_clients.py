"""Client-level demo seed for the "Meridian Overseas Education" workspace.

Runs AFTER seed_demo_org.py (which creates the organization, users, members,
branches, subscription, wallet/credits, notifications, audit log, finance
settings and the linked account). This script adds everything that hangs off
clients: the roster, stage records, universities, documents (with real
placeholder PDFs written through the app's own encrypted storage), notes,
emails, calendar, document requests, portal shares, interview sessions,
Writing Studio drafts, Deep Scan, Course Finder shortlists, copilot invite,
lead forms + leads, finance entries + student payments, AI assistant threads
and the catalog "verified" timestamps.

Usage (from web_app/):
    DATABASE_URL='sqlite:///./_demo_video.db' ENTERPRISE_DOCS_DIR='./_docs_demo' \
        python3 seed_demo_clients.py [--reset]

--reset purges every client-level row this script owns for the org first, so
the seed can be re-run cleanly. Without it the script refuses to run when the
org already has clients.

All dates are computed relative to "today" (IST) at run time so nothing is
ever overdue on capture day. Every person and company is fictional.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
# Must be set BEFORE importing anything under app/ (app.database reads it at import).
os.environ.setdefault("DATABASE_URL", "sqlite:///./_demo_video.db")
os.environ.setdefault("ENTERPRISE_DOCS_DIR", "./_docs_demo")
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(HERE, ".env"))  # SECRET_KEY etc. — same values the server uses

import difflib  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import random  # noqa: E402
import re  # noqa: E402
import secrets  # noqa: E402
import shutil  # noqa: E402
from datetime import date, datetime, time, timedelta, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

from app import enterprise_catalog as catalog  # noqa: E402
from app import enterprise_storage  # noqa: E402
from app import models  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.utils.token_security import hash_token  # noqa: E402
from sqlalchemy import func as sa_func  # noqa: E402

try:  # helpers from the org-level seed (optional — local fallbacks below).
    # seed_demo_org refuses (SystemExit) to import against a non-sandbox engine, so catch BaseException.
    import seed_demo_org as _org_seed  # type: ignore
except BaseException:  # noqa: BLE001
    _org_seed = None

# ---------------------------------------------------------------------------
# Identity / constants
# ---------------------------------------------------------------------------
ORG_SLUG = "meridian"
ORG_NAME = "Meridian Overseas Education"

MEMBERS = {
    "ananya": ("ananya.rao@example.com", "Ananya Rao"),
    "rahul": ("rahul.verma@example.com", "Rahul Verma"),
    "priya": ("priya.nair@example.com", "Priya Nair"),
    "arjun": ("arjun.menon@example.com", "Arjun Menon"),
    "kavya": ("kavya.krishnan@example.com", "Kavya Krishnan"),
    "sanjay": ("sanjay.patel@example.com", "Sanjay Patel"),
    "neha": ("neha.gupta@example.com", "Neha Gupta"),
    "deepak": ("deepak.iyer@example.com", "Deepak Iyer"),
}
BRANCHES = {
    "BLR": "Bengaluru — Koramangala",
    "HYD": "Hyderabad — Banjara Hills",
    "KOC": "Kochi — MG Road",
}
WEBSITE_FORM_TOKEN = "meridian-website-enquiries-9f3a7c2e"
INSTAGRAM_FORM_TOKEN = "meridian-instagram-sep-intake-b81d4e60"

UTC_NOW = datetime.utcnow().replace(microsecond=0)
IST_OFFSET = timedelta(hours=5, minutes=30)
TODAY: date = (UTC_NOW + IST_OFFSET).date()  # org "today" (Asia/Kolkata)
UTC = timezone.utc


def d(n: int) -> date:
    return TODAY + timedelta(days=n)


def ds(n: int) -> str:
    return d(n).isoformat()


def at(day_offset: int, hhmm: str = "10:00") -> datetime:
    """Naive UTC datetime for an IST wall-clock time on TODAY+day_offset."""
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime.combine(d(day_offset), time(h, m)) - IST_OFFSET


def on(day: date, hhmm: str = "10:00") -> datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime.combine(day, time(h, m)) - IST_OFFSET


def visit_iso(dt: datetime) -> str:
    """The offset-qualified ISO string _record_stage_visit writes."""
    return dt.replace(tzinfo=UTC).isoformat()


def fmt_long(day: date) -> str:
    return f"{day.day} {day.strftime('%b %Y')}"


def _rng(*parts) -> random.Random:
    seed = int(hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:12], 16)
    return random.Random(seed)


def _code(seed: str, pattern: str) -> str:
    """Deterministic identifier from a pattern: A = letter, 9 = digit, other chars verbatim."""
    r = _rng(seed)
    out = []
    for ch in pattern:
        if ch == "A":
            out.append(r.choice("ABCDEFGHJKLMNPQRSTUVWXYZ"))
        elif ch == "9":
            out.append(str(r.randint(0, 9)))
        else:
            out.append(ch)
    return "".join(out)


def new_token_hash() -> str:
    return hash_token(secrets.token_urlsafe(32))


# ---------------------------------------------------------------------------
# Org-seed helpers with local fallbacks
# ---------------------------------------------------------------------------
def _try_helper(name, *arg_sets):
    fn = getattr(_org_seed, name, None) if _org_seed else None
    if fn is None:
        return None
    for args in arg_sets:
        try:
            value = fn(*args)
        except TypeError:
            continue
        except Exception:  # noqa: BLE001
            return None
        if value is not None:
            return value
    return None


def resolve_org(db) -> models.EnterpriseOrganization:
    org = _try_helper("get_org", (db,), (db, ORG_SLUG))
    if isinstance(org, int):
        org = db.get(models.EnterpriseOrganization, org)
    if org is None:
        org = (
            db.query(models.EnterpriseOrganization)
            .filter(models.EnterpriseOrganization.subdomain_slug == ORG_SLUG)
            .first()
        )
    if org is None:
        raise SystemExit(f"Organization with slug '{ORG_SLUG}' not found — run seed_demo_org.py first.")
    return org


def resolve_member_user_id(db, org, key: str) -> int:
    email, _name = MEMBERS[key]
    uid = _try_helper("get_member_user_id", (db, org, email), (db, org.id, email), (db, email), (email,))
    if isinstance(uid, models.User):
        uid = uid.id
    if not uid:
        user = db.query(models.User).filter(models.User.email == email).first()
        if user is None:
            raise SystemExit(f"Member user {email} not found — run seed_demo_org.py first.")
        uid = user.id
    return int(uid)


def resolve_branch_id(db, org, key: str) -> int:
    name = BRANCHES[key]
    bid = _try_helper("get_branch_id", (db, org, name), (db, org.id, name), (db, name), (name,))
    if isinstance(bid, models.EnterpriseBranch):
        bid = bid.id
    if not bid:
        row = (
            db.query(models.EnterpriseBranch)
            .filter(
                models.EnterpriseBranch.organization_id == org.id,
                models.EnterpriseBranch.name == name,
            )
            .first()
        )
        if row is None:  # tolerate a slightly different office name (e.g. "Bengaluru — Koramangala (HQ)")
            first_word = name.split(" ")[0]
            row = (
                db.query(models.EnterpriseBranch)
                .filter(
                    models.EnterpriseBranch.organization_id == org.id,
                    models.EnterpriseBranch.name.ilike(f"{first_word}%"),
                )
                .first()
            )
        if row is None:
            raise SystemExit(f"Branch '{name}' not found — run seed_demo_org.py first.")
        bid = row.id
    return int(bid)


# ---------------------------------------------------------------------------
# Placeholder PDF bytes (valid single-page PDF, ~1 KB)
# ---------------------------------------------------------------------------
def make_pdf_bytes(title: str, lines: list[str]) -> bytes:
    def esc(s: str) -> str:
        s = s.encode("latin-1", "replace").decode("latin-1")
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    ops = ["BT", "/F1 16 Tf", "50 780 Td", f"({esc(title)}) Tj", "/F1 11 Tf", "0 -28 Td"]
    for ln in lines:
        ops += [f"({esc(ln)}) Tj", "0 -16 Td"]
    ops += ["/F1 8 Tf", "0 -20 Td", "(Placeholder document generated for the Rilono product demo. Not a real record.) Tj", "ET"]
    stream = "\n".join(ops).encode("latin-1")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(out)


# ---------------------------------------------------------------------------
# Stage records: fill every REQUIRED field of every visited stage with a
# plausible value so the journey tracker shows no gap dots.
# ---------------------------------------------------------------------------
_POSITIVE = [
    "complete", "verified", "attended", "received", "confirmed", "cleared", "issued", "paid",
    "held", "in hand", "signed", "registered", "granted", "passed", "agreed", "finalised",
    "done", "given", "credited", "unconditional", "obtained", "downloaded", "arrived",
    "compiled", "reviewed", "public", "ready", "enrolled", "lodged", "filed", "captured",
    "transferred", "validated", "approved", "assigned", "purchased", "allocated", "affixed",
    "printed", "ordered", "transmitted", "booked", "scheduled", "yes —", "no large", "no prior",
]
_PROGRESS = [
    "scheduled", "booked", "pending", "awaiting", "in progress", "under", "submitted",
    "partially", "requested", "drafting", "drafted", "planned", "being", "forwarded",
    "in flight", "sent", "applied",
]
_NEGATIVE = [
    "not started", "no-show", "missed", "refused", "declined", "rejected", "error", "wrong",
    "failed", "cancelled", "ban", "overstay", "suspension", "visa brake", "ineligible",
    "unpaid", "not applicable", "withdrew", "terminated", "denied", "unexplained deposit",
    "risk", "not on", "not retrievable", "overdue", "not compliant", "not permitted",
    "doubted", "lapsed", "exceeds", "cannot", "not yet", "to be confirmed", "not checked",
    "not confirmed", "unclear", "no status", "not required", "not booked", "not due",
    "not created", "not arranged", "not challenged", "not appealing", "not given",
    "not summoned", "not reviewed", "not determined", "undecided", "not called",
    "not applying", "not being", "fail", "funds short", "below", "frozen", "no action",
    "not filed", "not lodged", "not reapplying", "absconding", "already in", "from inside", "job-seeking",
]
_LOCATION_PREFS = ["Bengaluru", "Chennai", "Mumbai", "Hyderabad", "New Delhi"]


def _score_option(opt: str, done: bool) -> int:
    low = opt.lower()
    pos = sum(1 for k in _POSITIVE if k in low)
    prog = sum(1 for k in _PROGRESS if k in low)
    neg = sum(1 for k in _NEGATIVE if k in low)
    wp, wq = (3, 1) if done else (1, 3)
    return pos * wp + prog * wq - neg * 4


_LEVEL_KEYS = {"study_program_type", "intended_course_level", "study_route", "education_sector", "course_duration_bracket"}
_LEVEL_WORDS = {
    "masters": ["master", "postgraduate taught", "laurea magistrale", "higher education (aqf 7-9)", "higher education", "24 months"],
    "mba": ["master", "postgraduate taught", "higher education (aqf 7-9)", "higher education", "24 months"],
    "phd": ["phd", "doctor", "postgraduate research"],
    "bachelors": ["bachelor", "undergraduate", "degree —", "higher education (aqf 7-9)", "higher education", "24 months"],
    "pg_diploma": ["diploma", "college", "vet", "postgraduate taught", "over 12 months"],
    "diploma": ["diploma", "vet", "college", "over 12 months"],
}
# Keys whose options describe a PROGRESSION (done stages should read as completed).
_STATUS_HINTS = ("status", "_filed", "deposited", "retained", "forwarded", "outcome", "avis")


def choose_option(key: str, options: list[str], *, done: bool, study_level: str | None = None) -> str:
    if not options:
        return ""
    lk = key.lower()
    if any(t in lk for t in ("location", "consular_post", "mission", "embassy", "jurisdiction", "submission_office")):
        for pref in _LOCATION_PREFS:
            for opt in options:
                if pref.lower() in opt.lower():
                    return opt
        return options[0]
    if lk in _LEVEL_KEYS and study_level:
        for word in _LEVEL_WORDS.get(study_level, []):
            for opt in options:
                if word in opt.lower():
                    return opt
        return options[0]
    first_low = options[0].lower()
    first_negative = any(k in first_low for k in _NEGATIVE)
    status_like = any(h in lk for h in _STATUS_HINTS)
    if not first_negative and not (done and status_like):
        return options[0]
    scored = [(_score_option(o, done), -i, o) for i, o in enumerate(options)]
    best = max(scored)
    if best[0] < 0:  # everything looks negative — fall back to the first option
        return options[0]
    return best[2]


_INTAKE_MONTH_HINTS = {
    "spring": 1, "summer": 5, "fall": 8, "autumn": 8, "winter": 11,
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7,
    "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "summer semester": 4, "winter semester": 10,
}


def intake_start_date(intake: str | None) -> date:
    text = str(intake or "").strip()
    year_match = re.search(r"(20\d{2})", text)
    low = text.lower()
    month = 9
    for k in sorted(_INTAKE_MONTH_HINTS, key=len, reverse=True):
        if k in low:
            month = _INTAKE_MONTH_HINTS[k]
            break
    if year_match:
        year = int(year_match.group(1))
    else:
        year = TODAY.year if month >= TODAY.month else TODAY.year + 1
    return date(year, month, 15)


_FUTURE_DATE_RE = re.compile(
    r"(valid_to|expir|until|deadline|due|expected|next_|start_date|arrival|departure|planned|"
    r"collection|term_expiry|period_expiry|decision_sla|window|valid_until|permit_valid|"
    r"registration_deadline|follow_up)"
)
_ID_TEXT_RE = re.compile(
    r"(reference|number|_id$|uci|trn|uan|ihs|code|receipt|case|_no$|account|policy|"
    r"application$|summary|solar|avats|gwf|ds160|i901|sevis|hap|loa|dli|pal|cas$|"
    r"portal|studielink|ind_|migrationsverket|e_konsulat|france_visas|icp|record|"
    r"registration$|licence|barcode|passport_data|_ref$)"
)


class StageContext:
    def __init__(self, *, cc: str, name: str, email: str, intake: str, visits: dict[str, datetime],
                 study_level: str | None, institutions: str | None = None):
        self.cc = cc
        self.name = name
        self.email = email
        self.course_start = intake_start_date(intake)
        self.visits = visits
        self.study_level = study_level or "masters"
        self.institutions = institutions or "See shortlist"


def gen_value(field: dict, stage: str, ctx: StageContext, *, done: bool) -> str:
    key = field["key"]
    ftype = field.get("type") or "text"
    lk = key.lower()
    visit = ctx.visits.get(stage)
    visit_day = (visit + IST_OFFSET).date() if visit else d(-20)
    seed = f"{ctx.name}|{stage}|{key}"

    if ftype == "select":
        return choose_option(key, field.get("options") or [], done=done, study_level=ctx.study_level)
    if ftype == "date":
        if lk == "status_last_checked":
            return ds(-1)
        if lk in ("on_hold_since",):
            return visit_day.isoformat()
        if lk in ("course_start_date",):
            return ctx.course_start.isoformat()
        if lk.startswith("visa_valid_from") or lk in ("intended_departure_date", "arrival_date_in_uae",
                                                       "arrival_date_in_singapore", "arrival_date_in_france",
                                                       "declared_entry_date", "planned_arrival_date"):
            return (ctx.course_start - timedelta(days=12)).isoformat()
        if re.search(r"(valid_to|expir|until|permit_valid|permission_expiry|residence_permit_valid)", lk):
            return (ctx.course_start + timedelta(days=730)).isoformat()
        if _FUTURE_DATE_RE.search(lk):
            return ds(10 + _rng(seed).randint(0, 14))
        # past event inside this stage
        day = min(visit_day + timedelta(days=_rng(seed).randint(1, 6)), d(-1))
        return day.isoformat()
    if ftype == "number":
        if "funds_evidenced" in lk:
            return str(_rng(seed).choice([28000, 32450, 38000, 42000, 52000]))
        if "tuition_deposit" in lk or "deposit" in lk:
            return "2000"
        if "tuition" in lk:
            return "18900"
        if "fee" in lk:
            return "185"
        if "monthly" in lk or "cost" in lk:
            return "1800"
        if "months" in lk:
            return "24"
        if "count" in lk:
            return "3"
        return "1"
    if ftype == "textarea":
        return "Discussed with the client; supporting evidence is on file."
    # text
    if "email" in lk:
        return ctx.email
    if "datetime" in lk:
        when = ds(7 + _rng(seed).randint(0, 12)) if not done else (visit_day + timedelta(days=3)).isoformat()
        return f"{when} 10:30"
    if "location" in lk:
        return "VFS Global, Bengaluru"
    if "language_test_result" in lk or lk.endswith("test_score"):
        return "IELTS 7.0 overall"
    if "conditions" in lk:
        return "8105 — 48 hours per fortnight; 8202 — course attendance"
    if "intended_course_level" in lk:
        return {"bachelors": "Bachelor (AQF 7)", "masters": "Master by coursework (AQF 9)",
                "mba": "MBA (AQF 9)", "phd": "PhD (AQF 10)", "diploma": "Diploma (AQF 5)",
                "pg_diploma": "Graduate Diploma (AQF 8)"}.get(ctx.study_level, "Master by coursework (AQF 9)")
    if "institution" in lk or "programme" in lk or "universit" in lk or "provider" in lk:
        return ctx.institutions
    if "name" in lk or "contact" in lk or "physician" in lk or "adviser" in lk:
        return "S. Raghavan (licensed adviser)"
    if "campaign" in lk:
        return "Études en France 2026-27"
    if _ID_TEXT_RE.search(lk):
        prefix = re.sub(r"[^A-Z]", "", key.upper())[:3] or "REF"
        return _code(seed, f"{prefix}-99999999")
    return "Recorded — see notes"


def build_stage_data(cc: str, status: str, held_from: str | None, overrides: dict, ctx: StageContext) -> dict:
    """Return {stage: {field: value}} for every stage the case has stood at."""
    linear = [s["key"] for s in catalog.stages_for(cc) if s["key"] not in (catalog.STAGE_REJECTED, catalog.STAGE_ON_HOLD)]
    anchor = held_from if status == catalog.STAGE_ON_HOLD else status
    if status == catalog.STAGE_REJECTED:
        worked = [k for k in overrides if k in linear]
        last = max((linear.index(k) for k in worked), default=len(linear) - 3)
        visited = linear[: last + 1] + [catalog.STAGE_REJECTED]
    elif status == catalog.STAGE_ON_HOLD:
        visited = linear[: linear.index(anchor) + 1] + [catalog.STAGE_ON_HOLD]
    else:
        visited = linear[: linear.index(anchor) + 1]
    out: dict[str, dict[str, str]] = {}
    for stage in visited:
        done = stage != visited[-1]
        bucket = {str(k): str(v) for k, v in (overrides.get(stage) or {}).items() if v not in (None, "")}
        for retired in catalog.RETIRED_STAGE_FIELDS.get(stage, ()):
            bucket.pop(retired, None)
        for field in catalog.stage_fields_for(cc, stage):
            key = field["key"]
            options = field.get("options") or []
            if key in bucket and field.get("type") == "select" and options and bucket[key] not in options:
                close = difflib.get_close_matches(bucket[key], options, n=1, cutoff=0.4)
                fixed = close[0] if close else choose_option(key, options, done=done, study_level=ctx.study_level)
                print(f"  ! {ctx.name}: {stage}.{key} '{bucket[key]}' is not an option — using '{fixed}'")
                bucket[key] = fixed
            if field.get("required") and not bucket.get(key, "").strip():
                bucket[key] = gen_value(field, stage, ctx, done=done)
        if not bucket:  # a visited stage must leave a trace or the journey calls it skipped
            fields = catalog.stage_fields_for(cc, stage)
            if fields:
                f0 = fields[0]
                bucket[f0["key"]] = gen_value(f0, stage, ctx, done=done)
        out[stage] = bucket
    return out


def missing_required(cc: str, stage_data: dict) -> list[str]:
    gaps = []
    for stage, bucket in stage_data.items():
        for field in catalog.stage_fields_for(cc, stage):
            if field.get("required") and not str(bucket.get(field["key"], "") or "").strip():
                gaps.append(f"{stage}.{field['key']}")
            if field.get("type") == "select" and field.get("options") and bucket.get(field["key"]) \
                    and bucket[field["key"]] not in field["options"]:
                gaps.append(f"{stage}.{field['key']}=BAD_OPTION")
    return gaps


def build_visits(cc: str, status: str, held_from: str | None, created_at: datetime, last_at: datetime,
                 stage_data: dict, explicit: dict[str, datetime] | None = None) -> dict[str, datetime]:
    """First-arrival timestamps for every visited stage, spread between creation and last_at."""
    order = list(stage_data.keys())
    visits: dict[str, datetime] = {}
    if explicit:
        visits.update(explicit)
    remaining = [k for k in order if k not in visits]
    if remaining:
        span = max((last_at - created_at).total_seconds(), 3600.0)
        n = len(order)
        for i, key in enumerate(order):
            if key in visits:
                continue
            frac = 0.0 if n == 1 else i / (n - 1)
            visits[key] = (created_at + timedelta(seconds=span * frac)).replace(microsecond=0)
    return {k: visits[k] for k in order}


def admission_stage_for(status: str, held_from: str | None, has_admit: bool) -> str:
    key = held_from if status == catalog.STAGE_ON_HOLD and held_from else status
    mapping = {
        "new_lead": "exploring", "shortlisting": "shortlisting", "applications_sent": "applied",
        "offer_accepted": "offer_accepted", "documents": "doc_in_hand", "submitted": "doc_in_hand",
        "appointment": "doc_in_hand", "decision": "doc_in_hand", "approved": "doc_in_hand",
        "rejected": "doc_in_hand",
    }
    value = mapping.get(key, "exploring")
    if key == "applications_sent" and has_admit:
        return "admitted"
    return value


# ---------------------------------------------------------------------------
# Reference pools
# ---------------------------------------------------------------------------
COUNTRY_NAME = {c["code"]: c["name"] for c in catalog.COUNTRIES}
STUDENT_VISA = {c["code"]: c["visa_types"]["student"][0] for c in catalog.COUNTRIES}

UNIVERSITY_POOL: dict[str, list[tuple[str, str, str, str, str, str]]] = {
    # (name, program, location, qs, tuition, website)
    "US": [("University of Illinois Urbana-Champaign", "MS Computer Science", "Urbana, Illinois", "64", "USD 38,000 / yr", "https://illinois.edu"),
           ("Arizona State University", "MS Computer Science", "Tempe, Arizona", "179", "USD 33,000 / yr", "https://www.asu.edu"),
           ("University of Texas at Dallas", "MS Computer Science", "Richardson, Texas", "501", "USD 30,500 / yr", "https://www.utdallas.edu"),
           ("Purdue University", "MS Agricultural Economics", "West Lafayette, Indiana", "89", "USD 31,000 / yr", "https://www.purdue.edu")],
    "UK": [("University of Leeds", "MSc International Business", "Leeds", "82", "GBP 26,500 / yr", "https://www.leeds.ac.uk"),
           ("University of Manchester", "MSc Management", "Manchester", "34", "GBP 29,000 / yr", "https://www.manchester.ac.uk"),
           ("University of Birmingham", "MSc International Business", "Birmingham", "80", "GBP 25,000 / yr", "https://www.birmingham.ac.uk"),
           ("University of Sheffield", "MSc Data Science", "Sheffield", "105", "GBP 27,500 / yr", "https://www.sheffield.ac.uk")],
    "CA": [("Conestoga College", "PG Certificate — Applied AI", "Kitchener, Ontario", "—", "CAD 18,900 / yr", "https://www.conestogac.on.ca"),
           ("Humber Polytechnic", "PG Certificate — Data Analytics", "Toronto, Ontario", "—", "CAD 19,500 / yr", "https://humber.ca"),
           ("University of Waterloo", "MDSAI", "Waterloo, Ontario", "115", "CAD 32,000 / yr", "https://uwaterloo.ca"),
           ("University of Toronto", "MEd Educational Leadership", "Toronto, Ontario", "25", "CAD 38,000 / yr", "https://www.utoronto.ca")],
    "AU": [("Deakin University", "Master of Nursing Practice", "Melbourne, Victoria", "197", "AUD 38,000 / yr", "https://www.deakin.edu.au"),
           ("Monash University", "Master of Business Administration", "Melbourne, Victoria", "37", "AUD 52,000 / yr", "https://www.monash.edu"),
           ("University of Wollongong", "Master of Information Technology", "Wollongong, NSW", "167", "AUD 36,000 / yr", "https://www.uow.edu.au"),
           ("University of Queensland", "Master of Data Science", "Brisbane, Queensland", "40", "AUD 48,000 / yr", "https://www.uq.edu.au")],
    "DE": [("RWTH Aachen University", "MSc Mechanical Engineering", "Aachen", "99", "EUR 0 (semester fee)", "https://www.rwth-aachen.de"),
           ("Technical University of Munich", "MSc Informatics", "Munich", "28", "EUR 6,000 / yr", "https://www.tum.de"),
           ("TU Darmstadt", "MSc Information Systems", "Darmstadt", "246", "EUR 0 (semester fee)", "https://www.tu-darmstadt.de")],
    "IE": [("University College Dublin", "MSc Data Analytics", "Dublin", "126", "EUR 21,000 / yr", "https://www.ucd.ie"),
           ("Trinity College Dublin", "MSc Computer Science", "Dublin", "87", "EUR 24,000 / yr", "https://www.tcd.ie"),
           ("University of Galway", "MSc Business Analytics", "Galway", "273", "EUR 19,500 / yr", "https://www.universityofgalway.ie")],
    "FR": [("ESSEC Business School", "MSc in Management", "Cergy, Paris", "—", "EUR 24,000 / yr", "https://www.essec.edu"),
           ("Grenoble Ecole de Management", "MSc Marketing Management", "Grenoble", "—", "EUR 19,000 / yr", "https://www.grenoble-em.com"),
           ("Sorbonne University", "MSc Computer Science", "Paris", "63", "EUR 3,879 / yr", "https://www.sorbonne-universite.fr")],
    "ES": [("IE University", "Master in Management", "Madrid", "—", "EUR 39,000 / yr", "https://www.ie.edu"),
           ("Universitat Pompeu Fabra", "MSc Data Science", "Barcelona", "179", "EUR 6,800 / yr", "https://www.upf.edu"),
           ("University of Barcelona", "MSc Business Analytics", "Barcelona", "165", "EUR 7,200 / yr", "https://www.ub.edu")],
    "NL": [("University of Amsterdam", "MSc Business Analytics", "Amsterdam", "55", "EUR 18,000 / yr", "https://www.uva.nl"),
           ("Delft University of Technology", "MSc Computer Science", "Delft", "49", "EUR 20,000 / yr", "https://www.tudelft.nl"),
           ("Eindhoven University of Technology", "MSc Data Science & AI", "Eindhoven", "136", "EUR 19,500 / yr", "https://www.tue.nl")],
    "AE": [("University of Wollongong in Dubai", "Master of Business Administration", "Dubai", "—", "AED 98,000 / yr", "https://www.uowdubai.ac.ae"),
           ("Heriot-Watt University Dubai", "MSc Data Science", "Dubai", "—", "AED 95,000 / yr", "https://www.hw.ac.uk/dubai"),
           ("American University of Sharjah", "MSc Computer Engineering", "Sharjah", "272", "AED 88,000 / yr", "https://www.aus.edu")],
    "PL": [("University of Warsaw", "MA Data Science & Business Analytics", "Warsaw", "262", "EUR 4,500 / yr", "https://en.uw.edu.pl"),
           ("Warsaw University of Technology", "MSc Computer Science", "Warsaw", "521", "EUR 4,000 / yr", "https://www.pw.edu.pl"),
           ("Jagiellonian University", "MSc Comparative Heritage Studies", "Kraków", "304", "EUR 3,800 / yr", "https://en.uj.edu.pl")],
    "NZ": [("Auckland University of Technology", "Bachelor of International Hospitality Management", "Auckland", "412", "NZD 34,000 / yr", "https://www.aut.ac.nz"),
           ("Otago Polytechnic", "Bachelor of Applied Management", "Dunedin", "—", "NZD 27,500 / yr", "https://www.op.ac.nz"),
           ("Lincoln University", "Bachelor of Commerce (Hotel & Tourism)", "Lincoln, Canterbury", "362", "NZD 31,000 / yr", "https://www.lincoln.ac.nz"),
           ("Unitec Institute of Technology", "NZ Diploma in Engineering (Civil)", "Auckland", "—", "NZD 25,000 / yr", "https://www.unitec.ac.nz")],
    "SG": [("National University of Singapore", "MSc Finance", "Singapore", "8", "SGD 65,000 total", "https://www.nus.edu.sg"),
           ("Nanyang Technological University", "MSc Financial Engineering", "Singapore", "15", "SGD 58,000 total", "https://www.ntu.edu.sg"),
           ("Singapore Management University", "MSc Applied Finance", "Singapore", "585", "SGD 52,000 total", "https://www.smu.edu.sg")],
    "IT": [("Politecnico di Milano", "MSc Architecture", "Milan", "111", "EUR 3,900 / yr", "https://www.polimi.it"),
           ("University of Bologna", "MSc Computer Engineering", "Bologna", "133", "EUR 3,500 / yr", "https://www.unibo.it"),
           ("Sapienza University of Rome", "MSc Data Science", "Rome", "132", "EUR 2,900 / yr", "https://www.uniroma1.it")],
    "SE": [("KTH Royal Institute of Technology", "MSc Machine Learning", "Stockholm", "74", "SEK 310,000 / yr", "https://www.kth.se"),
           ("Lund University", "MSc Data Analytics", "Lund", "75", "SEK 145,000 / yr", "https://www.lunduniversity.lu.se"),
           ("Chalmers University of Technology", "MSc Data Science & AI", "Gothenburg", "129", "SEK 160,000 / yr", "https://www.chalmers.se")],
}

CITY_POOL = ["Bengaluru", "Mysuru", "Hyderabad", "Kochi", "Chennai", "Mumbai", "Pune", "Coimbatore",
             "Thiruvananthapuram", "Vijayawada", "Mangaluru", "Hubballi"]


# ---------------------------------------------------------------------------
# Roster
# ---------------------------------------------------------------------------
# Detailed clients: full intake profile + hand-authored stage records (from the
# seeding guide), dates made relative to TODAY where they touch the calendar.
# Keys starting with "_" are seed directives, not columns.
def _email(name: str) -> str:
    return name.lower().replace(" ", ".") + "@example.com"


DETAILED: list[dict] = [
    {
        "_key": "aarav", "full_name": "Aarav Mehta", "phone": "+91 98200 11223", "current_city": "Mumbai",
        "gender": "male", "date_of_birth": date(2003, 4, 18), "passport_number": "P1234567",
        "passport_expiry": date(2031, 2, 10), "guardian_name": "Rakesh Mehta", "guardian_relation": "father",
        "guardian_phone": "+91 98200 44556", "destination_country_code": "US", "visa_type": "F-1 Student Visa",
        "intake": "Spring 2027", "study_level": "masters", "field_of_study": "Computer Science / IT",
        "priority": "high", "status": "documents", "highest_qualification": "bachelors_4yr",
        "qualification_score": "8.6", "qualification_scale": "cgpa_10", "year_of_passing": 2025, "backlogs_count": 0,
        "work_experience_band": "lt_1", "english_test_status": "score_available", "english_test_type": "toefl_ibt",
        "english_test_score": "104", "english_test_date": date(2026, 1, 20), "aptitude_test_type": "gre",
        "aptitude_test_score": "324", "budget_band": "25_40l", "funding_source": "loan_sanctioned",
        "lead_source": "referral", "lead_source_detail": "Rohan Desai (2025 batch)",
        "marketing_consent_channels": "whatsapp,email", "prior_refusal_history": "none",
        "_branch": "BLR", "_assigned": "arjun", "_created": on(date(2026, 6, 3), "09:15"), "_updated": at(-1, "18:40"),
        "_followup": 2, "_target": 37,
        "_visits": {"new_lead": on(date(2026, 6, 3), "09:15"), "shortlisting": on(date(2026, 6, 12), "11:00"),
                    "applications_sent": on(date(2026, 6, 24), "15:30"), "offer_accepted": on(date(2026, 7, 16), "10:20"),
                    "documents": on(date(2026, 8, 3), "12:05")},
        "_stage": {
            "new_lead": {"first_consultation_date": "2026-06-03", "entry_suspension_screening": "Nationality not listed — no restriction"},
            "shortlisting": {"shortlist_status": "Shortlist agreed with client", "target_university_count": "5",
                             "intended_program_and_university": "MS Computer Science — UIUC / ASU / UT Dallas",
                             "sop_status": "Finalised — tailored per institution", "lor_status": "All received", "lor_received_count": "3",
                             "shortlisting_notes": "Strong CGPA + GRE 324; two reach, two match, one safety. Prefers systems research groups."},
            "applications_sent": {"applications_submitted_count": "5", "first_application_date": "2026-06-20",
                                  "offers_received_count": "3", "rejections_received_count": "1", "next_decision_expected_date": "2026-07-10"},
            "offer_accepted": {"chosen_institution": "University of Illinois Urbana-Champaign", "chosen_course": "MS Computer Science",
                               "offer_accepted_date": "2026-07-15", "tuition_deposit_amount": "1500", "tuition_deposit_paid_date": "2026-07-18",
                               "enrolment_document_requested_date": "2026-07-18"},
            "documents": {"course_start_date": "2027-01-19", "funds_evidence_status": "Complete and verified", "funds_evidenced_amount": "68500",
                          "sevis_id": "N0034567890", "i20_issue_date": "2026-08-01", "school_code": "CHI214F00171000",
                          "i20_program_end_date": "2028-12-20", "sevis_record_type": "Initial attendance — new SEVIS record",
                          "social_media_disclosure_status": "All listed profiles set to public", "i20_major_cip_code": "11.0701",
                          "f2_dependents_count": "0"},
        },
        "_institutions": "UIUC, Arizona State University, UT Dallas",
    },
    {
        "_key": "ishita", "full_name": "Ishita Rao", "phone": "+91 99010 22334", "current_city": "Bengaluru",
        "gender": "female", "date_of_birth": date(2002, 11, 2), "passport_number": "R9876543",
        "passport_expiry": date(2030, 6, 30), "guardian_name": "Suresh Rao", "guardian_relation": "father",
        "guardian_phone": "+91 99010 55667", "destination_country_code": "UK", "visa_type": "Student Visa",
        "intake": "January 2027", "study_level": "masters", "field_of_study": "Business & Management",
        "priority": "normal", "status": "documents", "highest_qualification": "bachelors_3yr",
        "qualification_score": "74%", "qualification_scale": "percentage", "year_of_passing": 2024, "backlogs_count": 0,
        "work_experience_band": "1_2", "english_test_status": "score_available", "english_test_type": "ielts_ukvi",
        "english_test_score": "7.0", "english_test_date": date(2026, 3, 8), "aptitude_test_type": "none",
        "budget_band": "25_40l", "funding_source": "loan_applied", "lead_source": "partner_agent",
        "lead_source_detail": "Sunrise Overseas, Rajkot", "marketing_consent_channels": "whatsapp,email,sms",
        "prior_refusal_history": "none",
        "_branch": "BLR", "_assigned": "arjun", "_created": at(-70, "10:30"), "_updated": at(-2, "16:10"),
        "_followup": 1, "_target": 74,
        "_stage": {
            "new_lead": {"first_consultation_date": ds(-70), "intended_course_level": "Postgraduate taught (RQF 7)",
                         "student_route_entry_screen": "Cleared — nationality not restricted", "dependants_planned": "No dependants"},
            "shortlisting": {"shortlist_status": "Shortlist agreed with client", "target_university_count": "4",
                             "sop_status": "Finalised — UCAS (one statement, all choices)", "lor_status": "All received", "lor_received_count": "2",
                             "target_institutions": "University of Leeds, University of Manchester, University of Birmingham, University of Sheffield"},
            "applications_sent": {"applications_submitted_count": "4", "first_application_date": ds(-52), "offers_received_count": "2",
                                  "rejections_received_count": "1"},
            "offer_accepted": {"chosen_institution": "University of Leeds", "chosen_course": "MSc International Business",
                               "offer_accepted_date": ds(-27), "tuition_deposit_amount": "3000", "tuition_deposit_paid_date": ds(-23),
                               "enrolment_document_requested_date": ds(-23)},
            "documents": {"course_start_date": "2027-01-18", "funds_evidence_status": "Awaiting loan / sponsor / bank", "funds_evidenced_amount": "12006",
                          "cas_number": "E4G2LEEDS2026X1", "cas_issue_date": ds(-9), "maintenance_funds_held_from": ds(-32),
                          "pre_cas_interview_status": "Passed — CAS to be assigned",
                          "english_requirement_met_by": "UKVI-approved SELT (IELTS for UKVI etc.)", "funds_statement_closing_date": ds(-4),
                          "outstanding_tuition_on_cas": "18500", "sponsor_licence_number": "L4E3E2D1S0"},
        },
        "_institutions": "University of Leeds, University of Manchester",
    },
    {
        "_key": "karan", "full_name": "Karan Singh", "phone": "+91 98140 55667", "current_city": "Ludhiana",
        "gender": "male", "date_of_birth": date(2001, 7, 9), "passport_number": "T4455667",
        "passport_expiry": date(2029, 9, 15), "destination_country_code": "CA", "visa_type": "Study Permit",
        "intake": "January 2027", "study_level": "pg_diploma", "field_of_study": "Data Science & AI",
        "priority": "urgent", "status": "submitted", "highest_qualification": "bachelors_4yr",
        "qualification_score": "7.1", "qualification_scale": "cgpa_10", "year_of_passing": 2023, "backlogs_count": 1,
        "work_experience_band": "2_5", "english_test_status": "score_available", "english_test_type": "ielts_academic",
        "english_test_score": "7.0", "english_test_date": date(2026, 2, 14), "budget_band": "15_25l",
        "funding_source": "loan_sanctioned", "lead_source": "google_ads", "lead_source_detail": "canada-pgwp-jan27",
        "marketing_consent_channels": "whatsapp,email", "prior_refusal_history": "none",
        "_branch": "BLR", "_assigned": "rahul", "_created": on(date(2026, 6, 17), "11:45"), "_updated": at(-1, "09:20"),
        "_followup": 1, "_target": 6,
        "_stage": {
            "new_lead": {"first_consultation_date": "2026-06-17", "preferred_province": "Ontario",
                         "ca_application_route": "New study permit — applying from outside Canada",
                         "pal_cap_exposure": "PAL required — undergraduate or college at a public DLI",
                         "pgwp_intent": "PGWP is the goal — college programme, field-of-study screen needed",
                         "accompanying_family": "Applicant travelling alone"},
            "shortlisting": {"shortlist_status": "Shortlist agreed with client", "sop_status": "Finalised — single generic version",
                             "target_institutions": "Conestoga College, Humber Polytechnic, University of Waterloo"},
            "applications_sent": {"applications_submitted_count": "3", "first_application_date": ds(-62), "offers_received_count": "2"},
            "offer_accepted": {"chosen_institution": "Conestoga College", "chosen_course": "PG Certificate — Applied AI",
                               "offer_accepted_date": ds(-46), "tuition_deposit_paid_date": ds(-43), "tuition_deposit_amount": "2500"},
            "documents": {"course_start_date": "2027-01-08", "funds_evidence_status": "Complete and verified", "funds_evidenced_amount": "32450",
                          "dli_number": "O19376158572", "loa_number": "LOA-2026-004417", "pal_tal_number": "PAL-ON-2026-88431",
                          "gic_certificate_number": "GIC-555777", "language_test_result": "IELTS 7.0 overall",
                          "loa_verification_status": "DLI confirms the LOA was verified", "first_year_tuition_cad": "18900",
                          "pgwp_field_of_study_check": "CIP code confirmed on the eligible list"},
            "submitted": {"application_submitted_date": ds(-8), "visa_fee_amount_paid": "235", "ircc_application_number": "S312345678",
                          "uci": "1122334455", "filing_channel": "IRCC Portal (online, outside Canada)",
                          "imm5476_filed": "Yes — RCIC / lawyer named", "rcic_name_and_licence": "Harpreet Gill — R712345"},
        },
        "_institutions": "Conestoga College, Humber Polytechnic",
    },
    {
        "_key": "meera", "full_name": "Meera Nair", "phone": "+91 98470 33445", "current_city": "Kochi",
        "gender": "female", "date_of_birth": date(2002, 3, 21), "passport_number": "M2233445",
        "passport_expiry": date(2032, 1, 5), "guardian_name": "Anil Nair", "guardian_relation": "father",
        "destination_country_code": "AU", "visa_type": "Subclass 500 Student Visa", "intake": "February 2027",
        "study_level": "masters", "field_of_study": "Health, Nursing & Allied", "priority": "high", "status": "decision",
        "highest_qualification": "bachelors_4yr", "qualification_score": "7.9", "qualification_scale": "cgpa_10",
        "year_of_passing": 2024, "backlogs_count": 0, "work_experience_band": "1_2", "english_test_status": "score_available",
        "english_test_type": "pte_academic", "english_test_score": "68", "english_test_date": date(2026, 4, 2),
        "budget_band": "25_40l", "funding_source": "mixed", "lead_source": "education_fair",
        "lead_source_detail": "Kochi Study Abroad Expo, June", "marketing_consent_channels": "whatsapp,email",
        "prior_refusal_history": "none",
        "_branch": "KOC", "_assigned": "kavya", "_created": at(-110, "10:00"), "_updated": at(-2, "11:30"),
        "_followup": 4, "_target": 18,
        "_stage": {
            "new_lead": {"first_consultation_date": ds(-110), "intended_course_level": "Master of Nursing (AQF 9)",
                         "lodgement_route": "Offshore — first Australian student visa", "education_sector": "Higher education (AQF 7-9)"},
            "shortlisting": {"shortlist_status": "Shortlist agreed with client", "sop_status": "Finalised — single generic version",
                             "preferred_providers": "Melbourne / Sydney"},
            "applications_sent": {"applications_submitted_count": "3", "offers_received_count": "2", "first_application_date": ds(-92)},
            "offer_accepted": {"chosen_institution": "Deakin University", "chosen_course": "Master of Nursing Practice",
                               "offer_accepted_date": ds(-68), "tuition_deposit_paid_date": ds(-63), "tuition_deposit_amount": "5000",
                               "enrolment_document_requested_date": ds(-63)},
            "documents": {"course_start_date": "2027-02-22", "funds_evidence_status": "Complete — funds route", "funds_evidenced_amount": "52000",
                          "coe_number": "0A1B2C3D4E", "cricos_course_code": "093784K", "oshc_policy_number": "Medibank OSHC 2201-99871",
                          "gs_statement_status": "Final — client approved", "funds_holding_status": "Held 3+ months — no unexplained credits"},
            "submitted": {"application_submitted_date": ds(-32), "visa_fee_receipt_number": "VFS-KOC-118823", "visa_fee_amount_paid": "2000",
                          "trn": "EGOK2X8L9M", "immiaccount_email": "meera.nair@example.com", "applicant_location": "Offshore"},
            "appointment": {"biometrics_status": "Attended — biometrics captured", "biometrics_completed_date": ds(-25),
                            "hap_id": "HAP20261234567", "medical_status": "Cleared", "medical_clinic_date": ds(-23)},
            "decision": {"case_status": "Further assessment", "status_last_checked": ds(-1), "processing_office": "Adelaide — Student Visa Processing"},
        },
        "_institutions": "Deakin University, Monash University",
    },
    {
        "_key": "divya", "full_name": "Divya Pillai", "phone": "+91 90040 77889", "current_city": "Chennai",
        "gender": "female", "date_of_birth": date(2003, 9, 12), "passport_number": "N7788990",
        "passport_expiry": date(2030, 11, 11), "destination_country_code": "DE", "visa_type": "National Visa (Type D) – Study",
        "intake": "Winter Semester 2026", "study_level": "masters", "field_of_study": "Engineering (other)",
        "priority": "normal", "status": "on_hold", "held_from_status": "documents", "highest_qualification": "bachelors_4yr",
        "qualification_score": "8.2", "qualification_scale": "cgpa_10", "year_of_passing": 2025, "backlogs_count": 0,
        "english_test_status": "score_available", "english_test_type": "ielts_academic", "english_test_score": "7.5",
        "budget_band": "10_15l", "funding_source": "self_family", "lead_source": "website",
        "lead_source_detail": "Germany landing page", "marketing_consent_channels": "email", "prior_refusal_history": "none",
        "_branch": "BLR", "_assigned": "arjun", "_created": at(-120, "14:00"), "_updated": at(-9, "10:00"),
        "_followup": 3, "_target": 11,
        "_stage": {
            "new_lead": {"first_consultation_date": ds(-120), "study_program_type": "Master",
                         "admission_status": "Unconditional admission (Zulassungsbescheid) received", "aps_required": "Yes — APS India",
                         "german_language_level": "A2 German / IELTS 7.5"},
            "shortlisting": {"shortlist_status": "Shortlist agreed with client", "target_institutions": "TU Munich, RWTH Aachen, TU Darmstadt",
                             "sop_status": "Finalised — tailored per institution"},
            "applications_sent": {"applications_submitted_count": "3", "offers_received_count": "1", "uni_assist_vpd_number": "VPD-2026-556781",
                                  "first_application_date": ds(-98)},
            "offer_accepted": {"chosen_institution": "RWTH Aachen", "chosen_course": "MSc Mechanical Engineering", "offer_accepted_date": ds(-40)},
            "documents": {"course_start_date": "2026-10-12", "funds_evidence_status": "Awaiting loan / sponsor / bank", "funds_evidenced_amount": "6000",
                          "aps_certificate_number": "APS-IN-2026-44812", "admission_letter_reference": "RWTH-ZUL-2026-1183",
                          "blocked_account_provider": "Expatrio", "blocked_account_number": "EXP-882134",
                          "health_insurance_type": "Statutory (TK / AOK / Barmer etc.)",
                          "funds_threshold_applied": "€11,904 / €992 a month — §16b studies"},
            "on_hold": {"hold_reason": "Blocked account funding pending", "on_hold_since": ds(-9), "next_follow_up_date": ds(3),
                        "hold_notes": "Family transferring the remaining €5,904; Expatrio confirmation expected this week."},
        },
        "_institutions": "RWTH Aachen, TU Munich",
    },
    {
        "_key": "rohan", "full_name": "Rohan Desai", "phone": "+91 98250 66778", "current_city": "Ahmedabad",
        "gender": "male", "date_of_birth": date(2002, 12, 1), "passport_number": "K5566778",
        "passport_expiry": date(2031, 8, 20), "destination_country_code": "IE", "visa_type": "D Study Visa",
        "intake": "September 2026", "study_level": "masters", "field_of_study": "Data Science & AI", "priority": "normal",
        "status": "approved", "highest_qualification": "bachelors_4yr", "qualification_score": "8.9", "qualification_scale": "cgpa_10",
        "year_of_passing": 2025, "backlogs_count": 0, "english_test_status": "score_available", "english_test_type": "ielts_academic",
        "english_test_score": "7.5", "budget_band": "15_25l", "funding_source": "loan_sanctioned", "lead_source": "repeat_client",
        "lead_source_detail": "Sister Priya Desai (UK 2024)", "marketing_consent_channels": "whatsapp,email", "prior_refusal_history": "none",
        "_branch": "BLR", "_assigned": "rahul", "_created": at(-170, "10:00"), "_updated": at(-30, "12:00"),
        "_stage": {
            "new_lead": {"first_consultation_date": ds(-170), "visa_requirement_status": "Visa required — D Study visa needed before travel",
                         "intended_course_level": "Postgraduate taught", "programme_eligibility_list": "On the ILEP (Programme Reference No held)"},
            "shortlisting": {"shortlist_status": "Shortlist agreed with client", "intended_institution": "University College Dublin",
                             "sop_status": "Finalised — single generic version", "lor_status": "All received"},
            "applications_sent": {"applications_submitted_count": "3", "offers_received_count": "3", "first_application_date": ds(-150)},
            "offer_accepted": {"chosen_institution": "University College Dublin", "chosen_course": "MSc Data Analytics",
                               "offer_accepted_date": ds(-139), "tuition_deposit_paid_date": ds(-131), "tuition_deposit_amount": "6000"},
            "documents": {"course_start_date": "2026-09-07", "funds_evidence_status": "Complete and verified", "funds_evidenced_amount": "12000",
                          "tuition_deposit_paid": "21000", "letter_of_acceptance_ref": "UCD-2026-04481", "tuition_payment_receipt_ref": "UCD-RCPT-88213",
                          "medical_insurance_policy_number": "StudyCover IE-556712",
                          "financial_summary_form_status": "Complete — filed with the application",
                          "large_lodgement_explanation_status": "Loan sanction letter obtained",
                          "learner_protection_status": "Exempt — publicly funded HEI / designated awarding body",
                          "english_evidence_route": "Test certificate meets the ISD visa minimum",
                          "medical_insurance_route": "College group scheme — stated on the acceptance letter"},
            "submitted": {"application_submitted_date": ds(-93), "visa_fee_receipt_number": "AVATS-RCPT-3391", "avats_application_number": "AVATS-2026-118823",
                          "visa_class_applied": "Long Stay (D) Study — multiple entry", "submission_office": "VFS Global visa application centre",
                          "documents_lodged_date": ds(-86), "avats_document_deadline": ds(-63)},
            "appointment": {"appointment_datetime": f"{ds(-86)} 11:00", "appointment_location": "VFS Global, Ahmedabad",
                            "biometrics_status": "Attended", "appointment_type": "VFS document submission",
                            "biometrics_requirement": "Required — resident in India"},
            "decision": {"case_status": "Decision made — awaiting passport return", "status_last_checked": ds(-38)},
            "approved": {"visa_decision_date": ds(-37), "visa_document_number": "IRL-2026-778812", "visa_valid_from": ds(-18),
                         "visa_valid_to": (d(-18) + timedelta(days=364)).isoformat(), "passport_received_date": ds(-32),
                         "entries_permitted": "Multiple entry", "first_registration_booking_status": "Portal account created — no appointment released"},
        },
        "_institutions": "University College Dublin",
    },
    {
        "_key": "sneha", "full_name": "Sneha Iyer", "phone": "+91 98400 88990", "current_city": "Chennai",
        "gender": "female", "date_of_birth": date(2008, 5, 30), "destination_country_code": "NZ",
        "visa_type": "Fee Paying Student Visa", "intake": "February 2027", "study_level": "bachelors",
        "field_of_study": "Hospitality & Tourism", "priority": "normal", "status": "shortlisting",
        "highest_qualification": "class_12", "qualification_score": "88%", "qualification_scale": "percentage",
        "year_of_passing": 2026, "backlogs_count": 0, "work_experience_band": "none", "english_test_status": "booked",
        "english_test_type": "ielts_academic", "english_test_date": d(20), "budget_band": "15_25l",
        "funding_source": "self_family", "lead_source": "social", "lead_source_detail": "Instagram — NZ reel",
        "guardian_name": "Lakshmi Iyer", "guardian_relation": "mother", "guardian_phone": "+91 98400 11221",
        "marketing_consent_channels": "whatsapp", "prior_refusal_history": "none",
        "_branch": "KOC", "_assigned": "kavya", "_created": on(date(2026, 8, 12), "15:20"), "_updated": at(-3, "10:15"),
        "_followup": 6, "_target": 84,
        "_stage": {
            "new_lead": {"first_consultation_date": "2026-08-12", "visa_route": "Fee Paying Student Visa",
                         "course_duration_bracket": "24 months or more — INZ 1007 + 1096 + PCC", "study_gap_profile": "No gap — course follows prior study",
                         "funding_route": "Family savings — 6 months of statements available"},
            "shortlisting": {"shortlist_status": "Draft shortlist shared with client", "target_university_count": "4",
                             "target_institutions": "AUT, Otago Polytechnic, Lincoln University", "sop_status": "Brief taken from client",
                             "lor_status": "Recommenders identified", "code_signatory_check": "All shortlisted providers verified as Code signatories"},
        },
        "_institutions": "AUT, Otago Polytechnic, Lincoln University",
    },
    {
        "_key": "aditya", "full_name": "Aditya Kulkarni", "phone": "+91 98900 12121", "current_city": "Pune",
        "gender": "male", "date_of_birth": date(2001, 1, 25), "passport_number": "U9988776", "passport_expiry": date(2033, 3, 14),
        "destination_country_code": "SG", "visa_type": "Student's Pass (IHL Track)", "intake": "January 2027",
        "study_level": "masters", "field_of_study": "Finance & Accounting", "priority": "high", "status": "applications_sent",
        "highest_qualification": "bachelors_3yr", "qualification_score": "3.7", "qualification_scale": "gpa_4",
        "year_of_passing": 2024, "backlogs_count": 0, "work_experience_band": "1_2", "english_test_status": "score_available",
        "english_test_type": "ielts_academic", "english_test_score": "8.0", "aptitude_test_type": "gmat", "aptitude_test_score": "710",
        "budget_band": "above_40l", "funding_source": "employer", "lead_source": "walk_in", "marketing_consent_channels": "email,phone",
        "prior_refusal_history": "prior_no_refusal",
        "_branch": "HYD", "_assigned": "priya", "_created": on(date(2026, 7, 22), "12:10"), "_updated": at(-4, "17:00"),
        "_followup": 28, "_target": 89,
        "_stage": {
            "new_lead": {"first_consultation_date": "2026-07-22", "institution_track": "IHL — autonomous university (NUS, NTU, SMU, SUTD, SIT, SUSS)",
                         "full_time_course_check": "Full-time approved course — STP eligible",
                         "entry_visa_requirement": "Visa-required national — visa embedded in the IPA, S$30 MJV at issuance"},
            "shortlisting": {"shortlist_status": "Shortlist agreed with client", "target_institutions": "NUS, NTU, SMU",
                             "sop_status": "Finalised — tailored per institution", "edutrust_register_check": "All IHLs — EduTrust not needed"},
            "applications_sent": {"applications_submitted_count": "3", "first_application_date": ds(-20), "offers_received_count": "1",
                                  "rejections_received_count": "0", "next_decision_expected_date": ds(38)},
        },
        "_institutions": "NUS, NTU, SMU",
    },
    {
        "_key": "priyanka", "full_name": "Priyanka Reddy", "phone": "+91 99490 34343", "current_city": "Hyderabad",
        "gender": "female", "date_of_birth": date(2001, 10, 4), "destination_country_code": "US", "visa_type": "F-1 Student Visa",
        "intake": "Fall 2027", "study_level": "phd", "field_of_study": "Agriculture & Life Sciences", "priority": "normal",
        "status": "new_lead", "highest_qualification": "masters", "qualification_score": "9.1", "qualification_scale": "cgpa_10",
        "year_of_passing": 2026, "backlogs_count": 0, "work_experience_band": "none", "english_test_status": "preparing",
        "aptitude_test_type": "gre", "budget_band": "not_sure", "funding_source": "scholarship", "lead_source": "whatsapp",
        "lead_source_detail": "Sept scholarship broadcast", "marketing_consent_channels": "whatsapp", "prior_refusal_history": "none",
        "_branch": "HYD", "_assigned": "priya", "_created": on(date(2026, 9, 3), "10:35"), "_updated": on(date(2026, 9, 3), "10:35"),
        "_followup": 2, "_target": None,
        "_stage": {"new_lead": {"first_consultation_date": "2026-09-03", "entry_suspension_screening": "Nationality not listed — no restriction"}},
    },
    {
        "_key": "farhan", "full_name": "Farhan Sheikh", "phone": "+91 98330 45454", "current_city": "Mumbai",
        "gender": "male", "date_of_birth": date(1999, 6, 17), "passport_number": "J3344556", "passport_expiry": date(2029, 3, 3),
        "destination_country_code": "UK", "visa_type": "Student Visa", "intake": "September 2026", "study_level": "masters",
        "field_of_study": "Law", "priority": "low", "status": "rejected", "highest_qualification": "professional",
        "english_test_status": "score_available", "english_test_type": "ielts_ukvi", "english_test_score": "6.5",
        "budget_band": "25_40l", "funding_source": "sponsor_relative", "prior_refusal_history": "refused_this_destination",
        "prior_refusal_notes": "Refused Aug 2026 — Appendix Finance: 28-day maintenance not met.", "lead_source": "cold_call",
        "marketing_consent_channels": "email", "work_experience_band": "2_5",
        "_branch": "BLR", "_assigned": "arjun", "_created": at(-150, "10:00"), "_updated": at(-26, "13:00"),
        "_stage": {
            "documents": {"course_start_date": "2026-09-21", "funds_evidence_status": "Partially collected", "cas_number": "E4G2KCL2026X9",
                          "cas_issue_date": ds(-67), "maintenance_funds_held_from": ds(-73), "pre_cas_interview_status": "Passed — CAS to be assigned",
                          "english_requirement_met_by": "UKVI-approved SELT (IELTS for UKVI etc.)", "funds_statement_closing_date": ds(-58),
                          "outstanding_tuition_on_cas": "16000"},
            "submitted": {"application_submitted_date": ds(-54), "gwf_uan_number": "GWF0771234567", "ihs_reference": "IHS-2026-9981234",
                          "priority_service": "Standard", "application_location": "Entry clearance — applying outside the UK"},
            "appointment": {"appointment_datetime": f"{ds(-50)} 10:00", "appointment_location": "VFS Global, Mumbai",
                            "biometrics_status": "Attended — biometrics captured", "appointment_provider": "VFS Global"},
            "decision": {"decision_sla_target_date": ds(-30), "credibility_interview_status": "Not called so far"},
            "rejected": {"refusal_date": ds(-27), "refusal_ground": "Financial requirement (Appendix Finance)",
                         "refusal_notes": "Funds dipped below £12,006 for three days in July. Reapply for January with a fresh 28-day statement.",
                         "appeal_deadline": ds(1), "appeal_status": "AR declined — reapplying", "next_step": "Reapply — later intake",
                         "reapply_target_date": ds(44)},
        },
        "_institutions": "King's College London",
    },
    {
        "_key": "nehak", "full_name": "Neha Kapoor", "phone": "+91 98110 56565", "current_city": "Delhi NCR",
        "gender": "female", "date_of_birth": date(2002, 2, 8), "passport_number": "W1122334", "passport_expiry": date(2033, 5, 15),
        "destination_country_code": "CA", "visa_type": "Study Permit", "intake": "September 2026", "study_level": "masters",
        "field_of_study": "Social Sciences & Education", "priority": "normal", "status": "approved",
        "highest_qualification": "bachelors_3yr", "qualification_score": "81%", "qualification_scale": "percentage",
        "year_of_passing": 2024, "backlogs_count": 0, "english_test_status": "score_available", "english_test_type": "ielts_academic",
        "english_test_score": "7.5", "budget_band": "25_40l", "funding_source": "loan_sanctioned", "lead_source": "institution_referral",
        "lead_source_detail": "University of Toronto India office", "marketing_consent_channels": "email", "prior_refusal_history": "none",
        "_branch": "BLR", "_assigned": "rahul", "_created": at(-200, "10:00"), "_updated": at(-12, "09:30"),
        "_stage": {
            "offer_accepted": {"chosen_institution": "University of Toronto", "chosen_course": "MEd Educational Leadership", "offer_accepted_date": ds(-120)},
            "approved": {"visa_decision_date": ds(-47), "visa_valid_to": "2028-08-31", "poe_loi_number": "LOI-2026-9912345",
                         "entry_document": "TRV (visa counterfoil in passport)", "permit_valid_until": "2028-08-31",
                         "planned_arrival_date": ds(-13), "poe_permit_issued_date": ds(-12), "study_permit_number": "F123456789"},
        },
        "_institutions": "University of Toronto",
    },
    {
        "_key": "vikram", "full_name": "Vikram Joshi", "phone": "+91 98210 67676", "current_city": "Mumbai",
        "gender": "male", "date_of_birth": date(1998, 8, 3), "passport_number": "V6677889", "passport_expiry": date(2031, 4, 22),
        "destination_country_code": "AU", "visa_type": "Subclass 500 Student Visa", "intake": "February 2027", "study_level": "mba",
        "field_of_study": "Business & Management", "priority": "high", "status": "offer_accepted",
        "highest_qualification": "bachelors_4yr", "qualification_score": "7.4", "qualification_scale": "cgpa_10", "year_of_passing": 2021,
        "backlogs_count": 0, "work_experience_band": "2_5", "english_test_status": "score_available", "english_test_type": "pte_academic",
        "english_test_score": "72", "aptitude_test_type": "gmat", "aptitude_test_score": "650", "budget_band": "above_40l",
        "funding_source": "loan_applied", "lead_source": "google_ads", "lead_source_detail": "australia-mba-2027",
        "marketing_consent_channels": "whatsapp,email", "prior_refusal_history": "none",
        "_branch": "BLR", "_assigned": "arjun", "_created": on(date(2026, 7, 9), "16:00"), "_updated": at(-5, "12:45"),
        "_followup": 26, "_target": 53,
        "_stage": {
            "new_lead": {"first_consultation_date": "2026-07-09", "intended_course_level": "MBA (AQF 9)",
                         "lodgement_route": "Offshore — first Australian student visa", "education_sector": "Higher education (AQF 7-9)"},
            "shortlisting": {"shortlist_status": "Shortlist agreed with client", "sop_status": "Finalised — single generic version",
                             "preferred_providers": "Monash, UQ, UOW"},
            "applications_sent": {"applications_submitted_count": "3", "offers_received_count": "2", "first_application_date": ds(-40)},
            "offer_accepted": {"chosen_institution": "Monash University", "chosen_course": "Master of Business Administration",
                               "offer_accepted_date": ds(-12), "tuition_deposit_amount": "5000", "tuition_deposit_paid_date": ds(-5),
                               "enrolment_document_requested_date": ds(-5), "letter_of_offer_reference": "MON-OFF-2026-33128"},
        },
        "_institutions": "Monash University, University of Queensland",
    },
    {
        "_key": "ananyas", "full_name": "Ananya Sharma", "phone": "+91 98765 43210", "current_city": "Jaipur",
        "gender": "female", "date_of_birth": date(2008, 3, 11), "destination_country_code": "DE", "visa_type": "Student Applicant Visa",
        "intake": "Summer Semester 2027", "study_level": "bachelors", "field_of_study": "Computer Science / IT", "priority": "normal",
        "status": "new_lead", "highest_qualification": "class_12", "qualification_score": "91%", "qualification_scale": "percentage",
        "year_of_passing": 2026, "backlogs_count": 0, "english_test_status": "not_taken", "budget_band": "under_10l",
        "funding_source": "self_family", "lead_source": "website", "lead_source_detail": "Website enquiries form",
        "guardian_name": "Manish Sharma", "guardian_relation": "father", "guardian_phone": "+91 98765 00011",
        "marketing_consent_channels": "whatsapp,email", "prior_refusal_history": "none",
        "_branch": "BLR", "_assigned": "arjun", "_created": on(date(2026, 9, 5), "12:48"), "_updated": on(date(2026, 9, 5), "12:48"),
        "_followup": 3, "_target": None,
        "_stage": {"new_lead": {"first_consultation_date": "2026-09-05", "study_program_type": "Studienkolleg (foundation)",
                                "admission_status": "Not yet applied", "aps_required": "Yes — APS India"}},
    },
    {
        "_key": "siddharth", "full_name": "Siddharth Menon", "phone": "+91 98460 78787", "current_city": "Thiruvananthapuram",
        "gender": "male", "date_of_birth": date(2004, 11, 19), "passport_number": "L9090121", "passport_expiry": date(2026, 11, 30),
        "destination_country_code": "NZ", "visa_type": "Pathway Student Visa", "intake": "February 2027", "study_level": "diploma",
        "field_of_study": "Engineering (other)", "priority": "urgent", "status": "decision", "highest_qualification": "diploma_3yr",
        "qualification_score": "78%", "qualification_scale": "percentage", "year_of_passing": 2025, "backlogs_count": 0,
        "english_test_status": "score_available", "english_test_type": "pte_academic", "english_test_score": "58", "budget_band": "10_15l",
        "funding_source": "loan_sanctioned", "lead_source": "referral", "lead_source_detail": "Meera Nair",
        "marketing_consent_channels": "whatsapp", "prior_refusal_history": "none", "work_experience_band": "none",
        "_branch": "KOC", "_assigned": "kavya", "_created": at(-100, "09:40"), "_updated": at(-1, "15:25"),
        "_followup": 2, "_target": 13,
        "_stage": {
            "documents": {"course_start_date": "2027-02-15", "funds_evidence_status": "Complete — every lump sum source-documented",
                          "funds_evidenced_amount": "38000", "offer_of_place_status": "Unconditional — Code signatory and legal name verified",
                          "emedical_status": "Completed — full medical (INZ 1007) + X-ray", "police_certificate_status": "In hand — under 6 months old",
                          "insurance_policy_status": "Policy purchased — whole visa period"},
            "submitted": {"application_submitted_date": ds(-30), "visa_fee_receipt_number": "INZ-CARD-77123", "immigration_online_reference": "IO-2026-4471123",
                          "visa_category_filed": "Pathway Student Visa", "filed_by": "Licensed Immigration Adviser (LIA)"},
            "appointment": {"appointment_location": "VFS Global, Chennai", "biometrics_status": "Attended — photo and fingerprints enrolled",
                            "biometrics_completed_date": ds(-19)},
            "decision": {"case_status": "AIP issued — tuition payment due", "status_last_checked": ds(-1), "aip_received_date": ds(-5),
                         "aip_tuition_deadline": ds(13)},
        },
        "_institutions": "Unitec Institute of Technology",
    },
]

# Lighter roster: (key, name, cc, status, intake, level, field, branch, assigned, gender, city,
#                  priority, created_days_ago, followup_offset|None, target_offset|None, extras)
LIGHT: list[tuple] = [
    ("tanvi", "Tanvi Agarwal", "FR", "documents", "January 2027", "masters", "Business & Management", "BLR", "arjun", "female", "Bengaluru", "high", 75, 5, 40, {}),
    ("nikhil", "Nikhil Bhat", "NL", "documents", "February 2027", "masters", "Data Science & AI", "KOC", "kavya", "male", "Kochi", "normal", 68, None, 45, {}),
    ("kabir", "Kabir Chopra", "AU", "documents", "February 2027", "masters", "Computer Science / IT", "HYD", "priya", "male", "Hyderabad", "normal", 82, 4, 33, {}),
    ("dev", "Dev Malhotra", "US", "documents", "Spring 2027", "masters", "Engineering (other)", "BLR", "arjun", "male", "Mysuru", "high", 90, None, 42, {}),
    ("riya", "Riya Chatterjee", "IT", "shortlisting", "September 2027", "masters", "Architecture", "HYD", "priya", "female", "Hyderabad", "normal", 30, None, 120, {}),
    ("manish", "Manish Tiwari", "SE", "shortlisting", "August 2027", "masters", "Data Science & AI", "HYD", "priya", "male", "Vijayawada", "normal", 26, None, 130, {}),
    ("shruti", "Shruti Deshpande", "CA", "shortlisting", "May 2027", "pg_diploma", "Business & Management", "KOC", "kavya", "female", "Kochi", "low", 34, 24, 110, {"stale": 16}),
    ("ritika", "Ritika Sen", "UK", "shortlisting", "January 2027", "masters", "Media & Communications", "BLR", "rahul", "female", "Bengaluru", "normal", 28, None, 95, {}),
    ("pooja", "Pooja Hegde", "ES", "shortlisting", "September 2027", "masters", "Business & Management", "BLR", "arjun", "female", "Mangaluru", "normal", 41, 27, 125, {"stale": 19}),
    ("harsh", "Harsh Vardhan", "PL", "applications_sent", "February 2027", "masters", "Computer Science / IT", "BLR", "rahul", "male", "Bengaluru", "normal", 58, None, 70, {}),
    ("zara", "Zara Khan", "AE", "applications_sent", "January 2027", "mba", "Business & Management", "KOC", "kavya", "female", "Kochi", "normal", 64, 25, 66, {"stale": 23}),
    ("yash", "Yash Thakur", "US", "applications_sent", "Fall 2027", "masters", "Data Science & AI", "HYD", "priya", "male", "Hyderabad", "high", 52, None, 100, {}),
    ("rehan", "Rehan Qureshi", "IT", "applications_sent", "September 2027", "masters", "Computer Science / IT", "BLR", "rahul", "male", "Bengaluru", "normal", 47, None, 90, {}),
    ("sana", "Sana Mirza", "FR", "submitted", "September 2026", "masters", "Arts & Design", "BLR", "rahul", "female", "Bengaluru", "urgent", 96, None, 8, {}),
    ("mehul", "Mehul Shah", "AE", "submitted", "January 2027", "masters", "Computer Science / IT", "KOC", "kavya", "male", "Thiruvananthapuram", "normal", 88, None, 30, {}),
    ("tara", "Tara Bhandari", "NZ", "submitted", "February 2027", "diploma", "Hospitality & Tourism", "KOC", "kavya", "female", "Kochi", "normal", 84, None, 35, {}),
    ("nandini", "Nandini Krishnamurthy", "SG", "new_lead", "August 2027", "masters", "Finance & Accounting", "KOC", "kavya", "female", "Kochi", "normal", 2, 4, None, {}),
    ("varun", "Varun Nambiar", "CA", "new_lead", "September 2027", "bachelors", "Computer Science / IT", "HYD", "priya", "male", "Hyderabad", "normal", 5, 7, None, {}),
    ("abhishek", "Abhishek Rao", "NL", "new_lead", "September 2027", "masters", "Psychology", "BLR", "arjun", "male", "Bengaluru", "low", 4, None, None, {}),
    ("omar", "Omar Farooq", "IE", "offer_accepted", "January 2027", "masters", "Computer Science / IT", "BLR", "arjun", "male", "Bengaluru", "normal", 72, None, 60, {}),
    ("aisha", "Aisha Siddiqui", "UK", "offer_accepted", "January 2027", "masters", "Law", "BLR", "rahul", "female", "Bengaluru", "normal", 66, None, 65, {}),
    ("lakshmi", "Lakshmi Venkatesh", "DE", "appointment", "Winter Semester 2026", "masters", "Computer Science / IT", "BLR", "rahul", "female", "Coimbatore", "high", 130, None, 14, {}),
    ("pranav", "Pranav Saxena", "US", "approved", "Spring 2027", "masters", "Engineering (other)", "BLR", "arjun", "male", "Bengaluru", "normal", 120, None, None, {"approved_days_ago": 5}),
    ("anjali", "Anjali Menon", "AU", "approved", "November 2026", "masters", "Health, Nursing & Allied", "HYD", "priya", "female", "Hyderabad", "normal", 100, None, None, {"approved_days_ago": 3}),
]


# ---------------------------------------------------------------------------
# Seed context
# ---------------------------------------------------------------------------
class Ctx:
    def __init__(self, db, org):
        self.db = db
        self.org = org
        self.org_id = org.id
        self.uid = {k: resolve_member_user_id(db, org, k) for k in MEMBERS}
        self.uname = {k: v[1] for k, v in MEMBERS.items()}
        self.bid = {k: resolve_branch_id(db, org, k) for k in BRANCHES}
        self.clients: dict[str, models.EnterpriseClient] = {}
        self.docs: dict[str, list[models.EnterpriseClientDocument]] = {}
        self.counts: dict[str, int] = {}

    def add(self, obj, table: str | None = None):
        self.db.add(obj)
        key = table or obj.__tablename__
        self.counts[key] = self.counts.get(key, 0) + 1
        return obj

    def user_name(self, key: str) -> str:
        return self.uname[key]


PROFILE_COLUMNS = {
    "full_name", "email", "phone", "whatsapp_number", "current_city", "gender", "nationality", "date_of_birth",
    "passport_number", "passport_expiry", "guardian_name", "guardian_relation", "guardian_phone", "visa_category",
    "destination_country_code", "destination_country_name", "visa_type", "intake", "application_reference",
    "study_level", "field_of_study", "admission_stage", "prior_refusal_history", "prior_refusal_notes",
    "highest_qualification", "qualification_score", "qualification_scale", "year_of_passing", "backlogs_count",
    "work_experience_band", "english_test_status", "english_test_type", "english_test_score", "english_test_date",
    "aptitude_test_type", "aptitude_test_score", "budget_band", "funding_source", "lead_source", "lead_source_detail",
    "branch_name", "branch_id", "next_followup_date", "status", "held_from_status", "priority", "target_date",
    "stage_data", "stage_visits", "client_consent_confirmed_at", "client_consent_confirmed_by_user_id",
    "marketing_consent_channels", "marketing_consent_at", "institution_share_consent_at", "assigned_to_user_id",
    "created_by_user_id", "created_at", "updated_at", "version",
}


def _light_to_spec(row: tuple, idx: int) -> dict:
    (key, name, cc, status, intake, level, field, branch, assigned, gender, city, priority,
     created_ago, followup, target, extras) = row
    r = _rng("light", key)
    created = at(-created_ago, f"{9 + r.randint(0, 8):02d}:{r.choice(['05', '20', '35', '50'])}")
    stale_days = extras.get("stale")
    if stale_days:
        updated = at(-stale_days, "12:00")
    elif status == "approved":
        updated = at(-extras.get("approved_days_ago", 5), "11:30")
    elif status == "new_lead":
        updated = created
    else:
        updated = at(-r.randint(1, 8), f"{10 + r.randint(0, 7):02d}:15")
    spec = {
        "_key": key, "full_name": name, "phone": f"+91 9{r.randint(1000, 9999)} {r.randint(10000, 99999)}",
        "current_city": city, "gender": gender, "date_of_birth": date(2000 + r.randint(0, 6), r.randint(1, 12), r.randint(1, 28)),
        "destination_country_code": cc, "visa_type": STUDENT_VISA[cc], "intake": intake, "study_level": level,
        "field_of_study": field, "priority": priority, "status": status,
        "highest_qualification": "class_12" if level == "bachelors" else r.choice(["bachelors_3yr", "bachelors_4yr"]),
        "qualification_score": r.choice(["7.6", "8.1", "8.4", "72%", "79%", "84%"]),
        "qualification_scale": "cgpa_10", "year_of_passing": 2023 + r.randint(0, 3), "backlogs_count": 0,
        "work_experience_band": r.choice(["none", "lt_1", "1_2", "2_5"]),
        "english_test_status": "score_available" if status not in ("new_lead",) else r.choice(["booked", "preparing", "score_available"]),
        "english_test_type": r.choice(["ielts_academic", "pte_academic", "toefl_ibt", "duolingo"]),
        "budget_band": r.choice(["10_15l", "15_25l", "25_40l"]),
        "funding_source": r.choice(["self_family", "loan_planning", "loan_sanctioned", "mixed"]),
        "lead_source": r.choice(["website", "referral", "social", "google_ads", "walk_in", "education_fair", "whatsapp"]),
        "marketing_consent_channels": r.choice(["whatsapp", "whatsapp,email", "email"]),
        "prior_refusal_history": "none", "aptitude_test_type": "none",
        "_branch": branch, "_assigned": assigned, "_created": created, "_updated": updated,
        "_followup": followup, "_target": target, "_stage": {}, "_light": True,
    }
    if spec["qualification_scale"] == "cgpa_10" and "%" in spec["qualification_score"]:
        spec["qualification_scale"] = "percentage"
    if spec["english_test_status"] == "score_available":
        spec["english_test_score"] = {"ielts_academic": "7.0", "pte_academic": "65", "toefl_ibt": "98", "duolingo": "120"}[spec["english_test_type"]]
    if status not in ("new_lead", "shortlisting"):
        spec["passport_number"] = _code(key, "A9999999")
        spec["passport_expiry"] = date(2030 + r.randint(0, 4), r.randint(1, 12), r.randint(1, 28))
    if status in ("submitted", "appointment", "decision", "approved", "documents"):
        pool = UNIVERSITY_POOL[cc]
        spec["_stage"] = {"offer_accepted": {"chosen_institution": pool[0][0], "chosen_course": pool[0][1]}}
    if extras.get("lead_source_detail"):
        spec["lead_source_detail"] = extras["lead_source_detail"]
    spec["_institutions"] = ", ".join(u[0] for u in UNIVERSITY_POOL[cc][:2])
    return spec


def seed_clients(ctx: Ctx) -> None:
    specs = list(DETAILED) + [_light_to_spec(row, i) for i, row in enumerate(LIGHT)]
    for n, spec in enumerate(specs, start=1):
        key = spec["_key"]
        cc = spec["destination_country_code"]
        status = spec["status"]
        held_from = spec.get("held_from_status")
        created: datetime = spec["_created"]
        updated: datetime = spec["_updated"]
        assigned_key = spec["_assigned"]
        branch_key = spec["_branch"]
        stage_ctx = StageContext(cc=cc, name=spec["full_name"], email=_email(spec["full_name"]), intake=spec["intake"],
                                 visits={}, study_level=spec.get("study_level"), institutions=spec.get("_institutions"))
        # visits first (generator needs them for past dates), then records, then re-align.
        provisional = build_stage_data(cc, status, held_from, spec.get("_stage") or {}, stage_ctx)
        visits = build_visits(cc, status, held_from, created, updated, provisional, spec.get("_visits"))
        stage_ctx.visits = visits
        stage_data = build_stage_data(cc, status, held_from, spec.get("_stage") or {}, stage_ctx)
        gaps = missing_required(cc, stage_data)
        if gaps:
            raise RuntimeError(f"{spec['full_name']}: stage records still have gaps: {gaps}")
        has_admit = status in ("offer_accepted", "documents", "submitted", "appointment", "decision", "approved") \
            or (status == "applications_sent" and key == "aditya")
        followup = spec.get("_followup")
        target = spec.get("_target")
        client = models.EnterpriseClient(
            organization_id=ctx.org_id,
            visa_category="student",
            destination_country_name=COUNTRY_NAME[cc],
            nationality="Indian",
            email=_email(spec["full_name"]),
            whatsapp_number=spec.get("phone"),
            application_reference=f"MOE-{cc}-2026-{n + 140:04d}",
            admission_stage=admission_stage_for(status, held_from, has_admit),
            branch_id=ctx.bid[branch_key],
            branch_name=BRANCHES[branch_key],
            next_followup_date=d(followup) if followup is not None else None,
            target_date=d(target) if target is not None else None,
            stage_data=json.dumps(stage_data, ensure_ascii=False),
            stage_visits=json.dumps({"from": "new_lead", "visits": {k: visit_iso(v) for k, v in visits.items()}}),
            client_consent_confirmed_at=created,
            client_consent_confirmed_by_user_id=ctx.uid[assigned_key],
            marketing_consent_at=created,
            institution_share_consent_at=created,
            assigned_to_user_id=ctx.uid[assigned_key],
            created_by_user_id=ctx.uid[assigned_key],
            created_at=created,
            updated_at=updated,
            version=1,
        )
        for col, value in spec.items():
            if col.startswith("_") or col not in PROFILE_COLUMNS:
                continue
            setattr(client, col, value)
        ctx.add(client)
        ctx.clients[key] = client
        spec["_visits_resolved"] = visits
    ctx.db.flush()
    ctx.specs = {s["_key"]: s for s in specs}


# ---------------------------------------------------------------------------
# Universities
# ---------------------------------------------------------------------------
def _uni_row(ctx: Ctx, client, entry, *, status, source, difficulty, added_by, created_at, rationale=None,
             requirements=None, notes=None, country_rank=None, fee=None, admissions_url=None):
    name, program, location, qs, tuition, site = entry
    return ctx.add(models.EnterpriseClientUniversity(
        organization_id=ctx.org_id, client_id=client.id, country_code=client.destination_country_code,
        university_name=name, program=program, location=location, status=status, source=source,
        est_tuition=tuition, rationale=rationale, notes=notes, qs_world_rank=(None if qs == "—" else qs),
        country_rank=country_rank, admission_difficulty=difficulty,
        key_requirements=json.dumps(requirements or []), application_fee=fee, website_url=site,
        admissions_url=admissions_url, added_by_user_id=ctx.uid[added_by], added_by_name=ctx.user_name(added_by),
        created_at=created_at,
    ))


def seed_universities(ctx: Ctx) -> None:
    c = ctx.clients
    us = UNIVERSITY_POOL["US"]
    _uni_row(ctx, c["aarav"], us[0], status="admitted", source="ai", difficulty="reach", added_by="arjun",
             created_at=on(date(2026, 6, 14), "11:20"), country_rank="12", fee="USD 90",
             rationale="Top-5 systems group; his Raft key-value store project is exactly the profile they admit. Admit + $4k fellowship.",
             requirements=["GPA 3.5+", "TOEFL 103+", "3 LORs", "GRE optional"], notes="Admit accepted 15 Jul; I-20 issued 1 Aug.",
             admissions_url="https://cs.illinois.edu/academics/graduate")
    _uni_row(ctx, c["aarav"], us[1], status="applied", source="ai", difficulty="match", added_by="arjun",
             created_at=on(date(2026, 6, 14), "11:22"), country_rank="60", fee="USD 115",
             rationale="Large CS faculty with a big-data track; fits budget with the Engineering Grad Scholarship.",
             requirements=["GPA 3.0+", "TOEFL 80+", "GRE optional"], admissions_url="https://scai.engineering.asu.edu/graduate-degree-programs/")
    _uni_row(ctx, c["aarav"], us[2], status="admitted", source="manual", difficulty="safety", added_by="rahul",
             created_at=on(date(2026, 6, 16), "09:05"), fee="USD 50",
             rationale="Spring intake and the lowest tuition on the list — kept as the secure fallback.",
             requirements=["GPA 3.0+", "TOEFL 80+ / IELTS 6.5+"])
    uk = UNIVERSITY_POOL["UK"]
    for i, (entry, st, diff) in enumerate([(uk[0], "admitted", "match"), (uk[1], "rejected", "reach"),
                                           (uk[2], "admitted", "match"), (uk[3], "considering", "safety")]):
        _uni_row(ctx, c["ishita"], entry, status=st, source="ai" if i < 3 else "manual", difficulty=diff, added_by="arjun",
                 created_at=at(-58, f"1{i}:1{i}"), country_rank=str(10 + i * 7), fee="GBP 25",
                 rationale="Triple-accredited business school; 74% with 1-2 years' experience sits comfortably in the admit band.",
                 requirements=["2:2 honours or 60%+", "IELTS UKVI 6.5", "2 references"])
    ca = UNIVERSITY_POOL["CA"]
    for i, (entry, st, diff) in enumerate([(ca[0], "admitted", "match"), (ca[1], "admitted", "safety"), (ca[2], "rejected", "reach")]):
        _uni_row(ctx, c["karan"], entry, status=st, source="ai", difficulty=diff, added_by="rahul",
                 created_at=at(-70, f"1{i}:30"), fee="CAD 100",
                 rationale="PGWP-eligible CIP code; co-op term in the second semester matches his 3 years of analytics experience.",
                 requirements=["Bachelor's degree", "IELTS 6.5 (no band < 6.0)"])
    sg = UNIVERSITY_POOL["SG"]
    for i, (entry, st, diff) in enumerate([(sg[0], "applied", "reach"), (sg[1], "admitted", "match"), (sg[2], "applied", "match")]):
        _uni_row(ctx, c["aditya"], entry, status=st, source="ai", difficulty=diff, added_by="priya",
                 created_at=at(-33, f"1{i}:05"), fee="SGD 100",
                 rationale="GMAT 710 and employer sponsorship make the finance track a strong fit.",
                 requirements=["Bachelor's degree", "GMAT 650+", "IELTS 7.0"])
    au = UNIVERSITY_POOL["AU"]
    _uni_row(ctx, c["meera"], au[0], status="admitted", source="ai", difficulty="match", added_by="kavya", created_at=at(-100, "10:10"),
             rationale="AHPRA-accredited nursing pathway with a Melbourne clinical placement network.", requirements=["Nursing degree", "PTE 65 (no band < 58)"])
    _uni_row(ctx, c["meera"], au[3], status="applied", source="ai", difficulty="reach", added_by="kavya", created_at=at(-100, "10:12"),
             rationale="Higher entry bar; kept as the stretch option.", requirements=["Nursing degree", "PTE 65"])
    _uni_row(ctx, c["vikram"], au[1], status="admitted", source="ai", difficulty="match", added_by="arjun", created_at=at(-50, "12:00"),
             rationale="GMAT 650 with 3 years' experience matches the Monash MBA median.", requirements=["GMAT 600+", "3 yrs experience", "PTE 65"])
    _uni_row(ctx, c["vikram"], au[3], status="applied", source="manual", difficulty="reach", added_by="arjun", created_at=at(-50, "12:05"))
    nz = UNIVERSITY_POOL["NZ"]
    for i, (entry, diff) in enumerate([(nz[0], "match"), (nz[1], "safety"), (nz[2], "match")]):
        _uni_row(ctx, c["sneha"], entry, status="considering", source="ai", difficulty=diff, added_by="kavya", created_at=at(-12, f"1{i}:40"),
                 rationale="Code-signatory provider with an integrated industry placement year.", requirements=["Class 12 with 70%+", "IELTS 6.0"])
    de = UNIVERSITY_POOL["DE"]
    for i, (entry, st) in enumerate([(de[0], "admitted"), (de[1], "rejected"), (de[2], "applied")]):
        _uni_row(ctx, c["divya"], entry, status=st, source="ai", difficulty=["match", "reach", "match"][i], added_by="arjun",
                 created_at=at(-105, f"1{i}:00"), rationale="Tuition-free public university; APS + IELTS 7.5 clear the entry bar.",
                 requirements=["APS certificate", "IELTS 6.5", "GPA equivalent 2.5 (German scale)"])
    ie = UNIVERSITY_POOL["IE"]
    _uni_row(ctx, c["rohan"], ie[0], status="admitted", source="ai", difficulty="match", added_by="rahul", created_at=at(-160, "10:00"),
             rationale="ILEP-listed programme with a Stamp 1G graduate route.", requirements=["2:1 honours", "IELTS 6.5"])
    _uni_row(ctx, c["rohan"], ie[1], status="admitted", source="ai", difficulty="reach", added_by="rahul", created_at=at(-160, "10:02"))
    _uni_row(ctx, c["nehak"], ca[3], status="admitted", source="manual", difficulty="match", added_by="rahul", created_at=at(-185, "10:00"))
    _uni_row(ctx, c["siddharth"], nz[3], status="admitted", source="manual", difficulty="safety", added_by="kavya", created_at=at(-88, "10:00"))
    _uni_row(ctx, c["farhan"], uk[1], status="admitted", source="manual", difficulty="match", added_by="arjun", created_at=at(-130, "10:00"))
    # lighter clients at shortlisting or beyond: 2 rows each from the destination pool
    for key, spec in ctx.specs.items():
        if not spec.get("_light"):
            continue
        client = ctx.clients[key]
        if client.status == "new_lead":
            continue
        pool = UNIVERSITY_POOL[client.destination_country_code]
        beyond = client.status not in ("shortlisting", "applications_sent")
        for i, entry in enumerate(pool[:2]):
            st = "admitted" if (beyond and i == 0) else ("applied" if client.status != "shortlisting" else "considering")
            _uni_row(ctx, client, entry, status=st, source="ai" if i == 0 else "manual", difficulty=["match", "safety"][i],
                     added_by=spec["_assigned"], created_at=spec["_created"] + timedelta(days=6 + i, hours=2),
                     rationale="Fits the budget band and the intake the client wants." if i == 0 else None,
                     requirements=["Bachelor's degree", "IELTS 6.5"] if i == 0 else [])
    ctx.db.flush()


# ---------------------------------------------------------------------------
# Documents (real placeholder PDFs written through the app's encrypted storage)
# ---------------------------------------------------------------------------
def _doc(ctx: Ctx, client, *, label: str, filename: str, uploaded_by: str, created_at: datetime, status: str = "valid",
         message: str | None = None, fields: dict | None = None, filled: list | None = None, conflicts: list | None = None,
         flags: list | None = None, manual_by: str | None = None, manual_at: datetime | None = None,
         text: str | None = None, lines: list[str] | None = None, credits: int | None = None):
    ext = os.path.splitext(filename)[1].lower() or ".pdf"
    body = make_pdf_bytes(f"{label} — {client.full_name}", lines or [
        f"Client: {client.full_name}", f"Document: {label}", f"Destination: {client.destination_country_name}",
        f"Reference: {_code(client.full_name + label, 'AA-99999999')}", f"Issued: {fmt_long((created_at + IST_OFFSET).date())}",
    ])
    storage_key = f"enterprise/{ctx.org_id}/clients/{client.id}/{secrets.token_hex(16)}{ext}"
    enterprise_storage.store_document(storage_key, body, content_type="application/pdf")
    extracted = None
    if status in ("valid", "invalid") or manual_at:
        payload = {"fields": fields or {}, "autofill": {"filled": filled or [], "conflicts": conflicts or []},
                   "cross_validation_flags": flags or []}
        if manual_at:
            payload["accepted_by"] = manual_by
            payload["accepted_at"] = visit_iso(manual_at)
            payload["ai_flag_before_accept"] = message
        extracted = json.dumps(payload, ensure_ascii=False)
    scanned = status in ("valid", "invalid") or bool(manual_at)
    doc = ctx.add(models.EnterpriseClientDocument(
        organization_id=ctx.org_id, client_id=client.id, document_type=label, original_filename=filename,
        storage_key=storage_key, file_size=len(body), mime_type="application/pdf",
        extracted_text=text or f"{label} for {client.full_name}. {' '.join(lines or [])}",
        validation_status=("valid" if manual_at else status), validation_message=message, extracted_fields=extracted,
        validated_at=(created_at + timedelta(minutes=2) if scanned else None),
        validation_credits_charged=(credits if credits is not None else (1 if scanned else 0)),
        manually_accepted_at=manual_at, manually_accepted_by=manual_by,
        uploaded_by_user_id=ctx.uid[uploaded_by], uploaded_by_name=ctx.user_name(uploaded_by), created_at=created_at,
    ))
    ctx.docs.setdefault(client.id, []).append(doc)
    return doc


def _country_doc_labels(ctx: Ctx, cc: str) -> list[str]:
    rows = (
        ctx.db.query(models.DocumentTypeCatalog.label)
        .filter(models.DocumentTypeCatalog.visa_type_key == "enterprise", models.DocumentTypeCatalog.country_code == cc)
        .order_by(models.DocumentTypeCatalog.sort_order.asc())
        .all()
    )
    labels = [r[0] for r in rows if r[0] and r[0] != "Other"]
    if not labels:
        labels = [item["label"] for item in catalog.document_types_for_country(cc) if item["label"] != "Other"]
    return labels


def seed_documents(ctx: Ctx) -> None:
    c = ctx.clients
    a = c["aarav"]
    _doc(ctx, a, label="Passport", filename="Aarav_Mehta_Passport.pdf", uploaded_by="arjun", created_at=on(date(2026, 6, 5), "10:30"),
         message="Genuine Indian passport, valid until Feb 2031 — beyond the I-20 program end date. Name and date of birth match the profile.",
         fields={"name": "Aarav Mehta", "date_of_birth": "2003-04-18", "document_number": "P1234567", "expiration_date": "2031-02-10",
                 "issue_date": "2021-02-11", "country": "India"},
         filled=[{"field": "Passport expiry", "attr": "passport_expiry", "value": "2031-02-10"},
                 {"field": "Date of birth", "attr": "date_of_birth", "value": "2003-04-18"}],
         flags=[{"field": "name", "status": "match", "current_document_value": "Aarav Mehta", "reference_value": "Aarav Mehta", "note": "Matches profile"}],
         text="REPUBLIC OF INDIA PASSPORT Type P Passport No. P1234567 Surname MEHTA Given Names AARAV Nationality INDIAN "
              "Date of Birth 18/04/2003 Date of Issue 11/02/2021 Date of Expiry 10/02/2031 Place of Issue MUMBAI",
         lines=["REPUBLIC OF INDIA - PASSPORT", "Surname: MEHTA   Given names: AARAV", "Passport No: P1234567", "Date of birth: 18/04/2003",
                "Date of issue: 11/02/2021   Date of expiry: 10/02/2031", "Place of issue: MUMBAI"])
    _doc(ctx, a, label="University Admission / Offer Letter", filename="UIUC_Admission_Letter.pdf", uploaded_by="arjun",
         created_at=on(date(2026, 7, 17), "12:10"),
         message="Unconditional admit to MS Computer Science for Spring 2027; program dates match the I-20 request.",
         fields={"university": "University of Illinois Urbana-Champaign", "program": "MS Computer Science", "term": "Spring 2027", "tuition_first_year": "USD 38,000"},
         text="University of Illinois Urbana-Champaign — Graduate College. Dear Aarav Mehta, congratulations on your admission to the "
              "MS in Computer Science program beginning Spring 2027 (January 19, 2027). Estimated first-year tuition USD 38,000.",
         lines=["University of Illinois Urbana-Champaign - Graduate College", "Dear Aarav Mehta,", "We are pleased to offer you admission to the",
                "MS in Computer Science, Spring 2027 (start January 19, 2027).", "Estimated first-year tuition: USD 38,000"])
    _doc(ctx, a, label="Form I-20 (signed)", filename="Aarav_Mehta_I20.pdf", uploaded_by="arjun", created_at=on(date(2026, 8, 4), "09:50"),
         status="invalid",
         message="Name on the I-20 reads MEHTA, AARAV RAKESH — the passport shows AARAV MEHTA with no middle name. "
                 "Ask the DSO to reissue the I-20 with the passport name before the DS-160 is filed.",
         fields={"sevis_id": "N0034567890", "school_code": "CHI214F00171000", "program_start": "2027-01-19", "program_end": "2028-12-20",
                 "student_name": "MEHTA, AARAV RAKESH", "estimated_expenses": "USD 68,500"},
         flags=[{"field": "name", "status": "conflict", "current_document_value": "MEHTA, AARAV RAKESH", "reference_value": "Aarav Mehta",
                 "note": "Middle name on the I-20 does not appear on the passport — consulates flag this at the window"},
                {"field": "sevis_id", "status": "match", "current_document_value": "N0034567890", "reference_value": "N0034567890", "note": "Matches case record"}],
         text="DEPARTMENT OF HOMELAND SECURITY Form I-20 Certificate of Eligibility for Nonimmigrant Student Status. SEVIS ID N0034567890. "
              "Student name MEHTA, AARAV RAKESH. School University of Illinois Urbana-Champaign, code CHI214F00171000. Program start 19 JAN 2027, end 20 DEC 2028. "
              "Estimated expenses USD 68,500.",
         lines=["DEPARTMENT OF HOMELAND SECURITY - FORM I-20", "SEVIS ID: N0034567890", "Student: MEHTA, AARAV RAKESH", "School code: CHI214F00171000",
                "Program: 19 JAN 2027 - 20 DEC 2028", "Estimated expenses: USD 68,500"])
    _doc(ctx, a, label="SEVIS I-901 Fee Receipt", filename="I901_Fee_Receipt.pdf", uploaded_by="deepak", created_at=on(date(2026, 8, 13), "15:40"),
         message="I-901 fee of USD 350 paid on 12 Aug 2026 against SEVIS ID N0034567890 — matches the I-20.",
         fields={"sevis_id": "N0034567890", "amount": "USD 350", "paid_on": "2026-08-12", "receipt_number": "I901-2026-77812"},
         text="SEVIS I-901 Fee Payment Confirmation. Receipt I901-2026-77812. SEVIS ID N0034567890. Amount USD 350.00 paid 12 Aug 2026.",
         lines=["SEVIS I-901 FEE PAYMENT CONFIRMATION", "Receipt: I901-2026-77812", "SEVIS ID: N0034567890", "Amount: USD 350.00", "Paid: 12 Aug 2026"])
    _doc(ctx, a, label="Bank Statements / Balance Certificate", filename="HDFC_Statement_Jul2026.pdf", uploaded_by="deepak",
         created_at=on(date(2026, 8, 20), "11:15"), status="invalid",
         message="Account holder is RAKESH MEHTA (sponsor), not the applicant — attach the sponsor affidavit of support or mark this as the sponsor's account. "
                 "Closing balance ₹32,40,000 covers about 9 months of the I-20 estimate; the loan sanction covers the rest.",
         fields={"account_holder": "RAKESH MEHTA", "closing_balance": "INR 32,40,000", "statement_period": "01 Feb 2026 – 31 Jul 2026", "bank": "HDFC Bank"},
         flags=[{"field": "account_holder_name", "status": "conflict", "current_document_value": "RAKESH MEHTA", "reference_value": "Aarav Mehta",
                 "note": "Statement belongs to the sponsor (father), not the applicant"},
                {"field": "closing_balance_vs_i20_expenses", "status": "unknown", "current_document_value": "INR 32,40,000", "reference_value": "USD 68,500",
                 "note": "Covers ~9 months; loan sanction letter covers the balance"}],
         text="HDFC Bank statement for account holder RAKESH MEHTA, period 01 Feb 2026 to 31 Jul 2026. Closing balance INR 32,40,000.00.",
         lines=["HDFC BANK - ACCOUNT STATEMENT", "Account holder: RAKESH MEHTA", "Period: 01 Feb 2026 - 31 Jul 2026", "Closing balance: INR 32,40,000.00"])
    _doc(ctx, a, label="Education Loan Sanction Letter", filename="SBI_Loan_Sanction.pdf", uploaded_by="arjun", created_at=on(date(2026, 8, 22), "16:05"),
         status="invalid",
         message="Sanction letter lists the course as 'MS Computer Engineering' while the admit is for MS Computer Science.",
         manual_by=ctx.user_name("arjun"), manual_at=on(date(2026, 8, 23), "10:20"),
         fields={"bank": "State Bank of India", "sanctioned_amount": "INR 35,00,000", "borrower": "Aarav Mehta", "co_borrower": "Rakesh Mehta", "course": "MS Computer Engineering"},
         flags=[{"field": "course_name", "status": "conflict", "current_document_value": "MS Computer Engineering", "reference_value": "MS Computer Science",
                 "note": "Bank used the department name; amount and borrower are correct"}],
         text="State Bank of India — Education Loan Sanction. Borrower Aarav Mehta, co-borrower Rakesh Mehta. Sanctioned amount INR 35,00,000 "
              "for MS Computer Engineering at University of Illinois Urbana-Champaign.",
         lines=["STATE BANK OF INDIA - EDUCATION LOAN SANCTION", "Borrower: Aarav Mehta   Co-borrower: Rakesh Mehta", "Sanctioned amount: INR 35,00,000",
                "Course: MS Computer Engineering, UIUC"])
    _doc(ctx, a, label="Academic Transcripts & Marksheets", filename="RVCE_Consolidated_Transcript.pdf", uploaded_by="arjun",
         created_at=on(date(2026, 6, 9), "13:25"),
         message="Consolidated B.E. transcript, CGPA 8.60/10, no backlogs — matches the profile.",
         fields={"institution": "RV College of Engineering", "degree": "B.E. Computer Science", "cgpa": "8.60", "year": "2025"},
         filled=[{"field": "Marks / GPA", "attr": "qualification_score", "value": "8.6"}],
         text="RV College of Engineering, Bengaluru — Consolidated transcript. Aarav Mehta, B.E. Computer Science & Engineering, 2021-2025. CGPA 8.60 / 10. No backlogs.",
         lines=["RV COLLEGE OF ENGINEERING - CONSOLIDATED TRANSCRIPT", "Aarav Mehta, B.E. Computer Science & Engineering (2021-2025)", "CGPA: 8.60 / 10   Backlogs: 0"])

    i = c["ishita"]
    _doc(ctx, i, label="Passport", filename="Ishita_Rao_Passport.pdf", uploaded_by="arjun", created_at=at(-60, "10:00"),
         message="Valid until Jun 2030; name and DOB match the profile.",
         fields={"name": "Ishita Rao", "document_number": "R9876543", "expiration_date": "2030-06-30"},
         filled=[{"field": "Passport expiry", "attr": "passport_expiry", "value": "2030-06-30"}])
    _doc(ctx, i, label="Unconditional Offer Letter", filename="Leeds_Offer_Letter.pdf", uploaded_by="arjun", created_at=at(-28, "11:30"),
         message="Unconditional offer for MSc International Business, January 2027 entry; deposit terms match the case record.",
         fields={"university": "University of Leeds", "program": "MSc International Business", "start": "2027-01-18"})
    _doc(ctx, i, label="CAS Statement", filename="Leeds_CAS_Statement.pdf", uploaded_by="deepak", created_at=at(-8, "14:20"),
         message="CAS E4G2LEEDS2026X1 issued; course dates, fees paid (£3,000) and SELT reference all agree with the offer letter.",
         fields={"cas_number": "E4G2LEEDS2026X1", "sponsor_licence": "L4E3E2D1S0", "fees_paid": "GBP 3,000", "outstanding": "GBP 18,500"})
    _doc(ctx, i, label="SELT / IELTS-for-UKVI Result", filename="IELTS_UKVI_TRF.pdf", uploaded_by="arjun", created_at=at(-55, "16:00"),
         message="IELTS for UKVI Academic — overall 7.0, no band below 6.0; UKVI number verified.",
         fields={"overall": "7.0", "listening": "7.5", "reading": "7.0", "writing": "6.5", "speaking": "7.0"},
         filled=[{"field": "Overall score", "attr": "english_test_score", "value": "7.0"}])
    _doc(ctx, i, label="28-Day Bank Statement / Financial Evidence", filename="ICICI_Statement_Aug2026.pdf", uploaded_by="deepak",
         created_at=at(-3, "17:45"), status="not_scanned")

    k = c["karan"]
    _doc(ctx, k, label="Passport", filename="Karan_Singh_Passport.pdf", uploaded_by="rahul", created_at=at(-72, "10:00"),
         message="Valid until Sep 2029; name and DOB match the profile.",
         fields={"name": "Karan Singh", "document_number": "T4455667", "expiration_date": "2029-09-15"},
         filled=[{"field": "Passport expiry", "attr": "passport_expiry", "value": "2029-09-15"}])
    _doc(ctx, k, label="Letter of Acceptance (LOA)", filename="Conestoga_LOA.pdf", uploaded_by="rahul", created_at=at(-44, "12:15"),
         message="LOA LOA-2026-004417 from Conestoga College (DLI O19376158572) for January 2027; DLI number matches the case record.",
         fields={"dli": "O19376158572", "loa_number": "LOA-2026-004417", "program": "PG Certificate — Applied AI", "start": "2027-01-08"})
    _doc(ctx, k, label="Provincial / Territorial Attestation Letter (PAL/TAL)", filename="Ontario_PAL.pdf", uploaded_by="deepak", created_at=at(-30, "09:30"),
         message="Ontario PAL PAL-ON-2026-88431 issued for the same DLI and programme as the LOA.",
         fields={"pal_number": "PAL-ON-2026-88431", "province": "Ontario"})
    _doc(ctx, k, label="GIC Certificate", filename="GIC_Certificate_Scotiabank.pdf", uploaded_by="rahul", created_at=at(-26, "15:05"),
         message="GIC of CAD 20,635 confirmed — meets the 2026 living-cost requirement.",
         fields={"gic_number": "GIC-555777", "amount": "CAD 20,635"})

    m = c["meera"]
    _doc(ctx, m, label="Passport", filename="Meera_Nair_Passport.pdf", uploaded_by="kavya", created_at=at(-100, "10:00"),
         message="Valid until Jan 2032; matches the profile.", fields={"name": "Meera Nair", "document_number": "M2233445"})
    _doc(ctx, m, label="Confirmation of Enrolment (CoE)", filename="Deakin_CoE.pdf", uploaded_by="kavya", created_at=at(-50, "11:00"),
         message="CoE 0A1B2C3D4E for CRICOS 093784K, course start 22 Feb 2027 — matches the case record.",
         fields={"coe": "0A1B2C3D4E", "cricos": "093784K", "start": "2027-02-22"})
    _doc(ctx, m, label="OSHC Policy Certificate", filename="Medibank_OSHC.pdf", uploaded_by="kavya", created_at=at(-48, "11:20"),
         message="OSHC cover runs from 8 Feb 2027 to 30 Mar 2029 — covers the full visa period.",
         fields={"policy": "Medibank OSHC 2201-99871", "cover_from": "2027-02-08", "cover_to": "2029-03-30"})
    # a handful of lighter clients with 1-2 valid documents each (labels from the destination catalog)
    for key, n_docs in (("tanvi", 2), ("nikhil", 2), ("kabir", 2), ("dev", 2), ("sana", 2), ("mehul", 1), ("tara", 1),
                        ("lakshmi", 2), ("pranav", 1), ("anjali", 1), ("rohan", 2), ("siddharth", 2), ("divya", 2), ("vikram", 1), ("nehak", 1)):
        client = c[key]
        if client.id in ctx.docs:
            continue
        labels = _country_doc_labels(ctx, client.destination_country_code)
        spec = ctx.specs[key]
        picks = [labels[0]] + labels[2:2 + n_docs - 1]
        for j, label in enumerate(picks):
            _doc(ctx, client, label=label, filename=f"{client.full_name.replace(' ', '_')}_{re.sub(r'[^A-Za-z0-9]+', '_', label)[:28].strip('_')}.pdf",
                 uploaded_by=spec["_assigned"], created_at=spec["_created"] + timedelta(days=4 + j * 5, hours=3),
                 message=f"{label} checked against the profile — details consistent.", fields={"document": label, "client": client.full_name})
    ctx.db.flush()


# ---------------------------------------------------------------------------
# Notes & emails
# ---------------------------------------------------------------------------
def _note(ctx: Ctx, client, author: str | None, body: str, created_at: datetime):
    return ctx.add(models.EnterpriseClientNote(
        organization_id=ctx.org_id, client_id=client.id,
        author_user_id=(ctx.uid[author] if author else None),
        author_name=(ctx.user_name(author) if author else "Rilono AI"),
        body=body, created_at=created_at,
    ))


def seed_notes(ctx: Ctx) -> None:
    c = ctx.clients
    a = c["aarav"]
    _note(ctx, a, "arjun", "Call with Aarav + father: SBI disbursement letter received. Asked the UIUC DSO (Ms. Lee) to reissue the I-20 with the passport name — "
                           "she expects a corrected copy within a week. DS-160 to be filed the day it lands.", at(-1, "18:40"))
    _note(ctx, a, "arjun", "Mock interview 2 done — funding answer much sharper, still vague on the return plan. One more prep session before the DS-160 goes in.", at(-4, "12:30"))
    _note(ctx, a, None, "Auto-filled from validated Passport: Passport expiry, Date of birth.", on(date(2026, 6, 5), "10:33"))
    _note(ctx, a, "rahul", "UIUC admit accepted; $1,500 deposit paid 18 Jul. I-20 requested from the DSO; loan sanction letter to follow from SBI.", on(date(2026, 7, 18), "11:05"))

    i = c["ishita"]
    _note(ctx, i, "arjun", "CAS received (E4G2LEEDS2026X1). Reminded Ishita the £12,006 maintenance must sit untouched for 28 days — statement closes on the 4th.", at(-8, "15:10"))
    _note(ctx, i, None, "Auto-filled from validated SELT / IELTS-for-UKVI Result: Overall score.", at(-55, "16:02"))
    _note(ctx, i, "arjun", "Leeds offer firmed. Sunrise Overseas (Rajkot) confirmed the sub-agent split at 20% on the service fee.", at(-27, "10:45"))

    k = c["karan"]
    _note(ctx, k, "rahul", f"IRCC BIL received — biometrics must be given by {fmt_long(d(6))}. VFS Chandigarh slot booked for {fmt_long(d(3))}, 10:40. Reminded Karan to carry the BIL printout.", at(-1, "09:20"))
    _note(ctx, k, "rahul", "Study permit application submitted on the IRCC portal (S312345678). IMM 5476 filed naming the RCIC.", at(-8, "17:35"))
    _note(ctx, k, "deepak", "PAL and GIC scanned and verified; LOA verification confirmed by Conestoga in the DLI portal.", at(-26, "15:30"))

    _note(ctx, c["meera"], "kavya", "Immi status moved to Further assessment; no request for information yet. Following up with Deakin about the CoE start-date confirmation.", at(-2, "11:30"))
    _note(ctx, c["divya"], "arjun", "On hold until the family tops up the Expatrio blocked account (€5,904 short). Father confirmed the transfer goes out this week.", at(-9, "10:05"))
    _note(ctx, c["siddharth"], "kavya", f"AIP issued by INZ — tuition of NZD 18,500 due by {fmt_long(d(13))}. Passport expires 30 Nov 2026: renewal appointment at PSK Trivandrum booked for {fmt_long(d(9))}.", at(-1, "15:25"))
    _note(ctx, c["sneha"], "kavya", "Draft shortlist shared: AUT, Otago Polytechnic, Lincoln. IELTS booked for the 27th; family wants a Christchurch option too.", at(-3, "10:15"))
    _note(ctx, c["vikram"], "arjun", "Monash MBA accepted; AUD 5,000 deposit paid. Loan application with Axis Bank — sanction expected in two weeks.", at(-5, "12:45"))
    _note(ctx, c["aditya"], "priya", "NTU offer in hand (MSc Financial Engineering). NUS decision expected mid-October; employer sponsorship letter received.", at(-4, "17:00"))
    _note(ctx, c["priyanka"], "priya", "Scholarship-first strategy: targeting fully funded PhD positions (Purdue, UC Davis). GRE booked for November.", at(-3, "11:05"))
    lead_ts = on(date(2026, 9, 5), "12:48")
    _note(ctx, c["ananyas"], "arjun",
          f'From lead form "Website enquiries" ({fmt_long(date(2026, 9, 5))} · 12:48 PM):\nFull name: Ananya Sharma\nEmail: ananya.sharma@example.com\n'
          "Phone / WhatsApp: +91 98765 43210\nWhich country are you interested in?: Germany\nPreferred intake: September 2027\n"
          "Anything you'd like to tell us?: Class 12 with 91%, interested in a CS bachelor's at a public university. Would like to know about Studienkolleg.",
          lead_ts)
    _note(ctx, c["rohan"], "rahul", "Visa granted — passport collected from VFS. Pre-departure briefing done; IRP registration to be booked after arrival.", at(-30, "12:00"))
    _note(ctx, c["nehak"], "rahul", "Landed in Toronto; study permit issued at POE. Case closed as approved.", at(-12, "09:30"))
    _note(ctx, c["pranav"], "arjun", "F-1 visa stamped — passport collected from the Mumbai consulate. SEVIS check-in and pre-departure briefing booked.", at(-5, "11:30"))
    _note(ctx, c["anjali"], "priya", "Subclass 500 granted — VEVO checked, conditions 8105 and 8202 explained.", at(-3, "11:30"))
    _note(ctx, c["sana"], "rahul", "France-Visas file lodged; VFS biometrics appointment confirmed for next week.", at(-6, "14:00"))
    _note(ctx, c["lakshmi"], "rahul", "Consulate General Bengaluru appointment confirmed; Sperrkonto and TK insurance certificate ready.", at(-3, "10:00"))
    ctx.db.flush()


def _email_row(ctx: Ctx, client, *, sent_by: str | None, subject: str, body: str, body_html: str | None, created_at: datetime,
           inbound: bool = False):
    if inbound:
        return ctx.add(models.EnterpriseClientEmail(
            organization_id=ctx.org_id, client_id=client.id, sent_by_user_id=None, sent_by_name=None,
            to_email=MEMBERS["arjun"][0] if sent_by is None else MEMBERS[sent_by][0], subject=subject, body=body, body_html=None,
            status="received", direction="inbound", from_email=client.email, created_at=created_at,
        ))
    return ctx.add(models.EnterpriseClientEmail(
        organization_id=ctx.org_id, client_id=client.id, sent_by_user_id=ctx.uid[sent_by], sent_by_name=ctx.user_name(sent_by),
        to_email=client.email, subject=subject, body=body, body_html=body_html, status="sent", direction="outbound",
        provider_message_id=f"re_demo_{secrets.token_hex(4)}", created_at=created_at,
    ))


def seed_emails(ctx: Ctx) -> None:
    c = ctx.clients
    a = c["aarav"]
    _email_row(ctx, a, sent_by="arjun", subject="Your I-20 has arrived — two things to fix before we file the DS-160",
           body=("Hi Aarav,\n\nYour I-20 from UIUC is in (SEVIS ID N0034567890) and the I-901 fee is paid. Two items came up in our checks:\n\n"
                 "1. The I-20 shows your name as MEHTA, AARAV RAKESH — your passport has no middle name. I have asked the DSO for a corrected copy.\n"
                 "2. The HDFC statement is in your father's name — please send the signed sponsor affidavit so the two go together.\n\n"
                 "Once both land we file the DS-160 the same day and book the OFC + interview slots.\n\nBest,\nArjun"),
           body_html=("<p>Hi Aarav,</p><p>Your I-20 from UIUC is in (SEVIS ID <b>N0034567890</b>) and the I-901 fee is paid. Two items came up in our checks:</p>"
                      "<ol><li>The I-20 shows your name as <b>MEHTA, AARAV RAKESH</b> — your passport has no middle name. I have asked the DSO for a corrected copy.</li>"
                      "<li>The HDFC statement is in your father's name — please send the signed <b>sponsor affidavit</b> so the two go together.</li></ol>"
                      "<p>Once both land we file the DS-160 the same day and book the OFC + interview slots.</p><p>Best,<br>Arjun</p>"),
           created_at=on(date(2026, 8, 24), "12:10"))
    _email_row(ctx, a, sent_by=None, subject="Re: Your I-20 has arrived — two things to fix before we file the DS-160",
           body="Thanks Arjun! Dad will sign the affidavit tomorrow. Should he also attach his ITR for the last two years?",
           body_html=None, created_at=on(date(2026, 8, 24), "19:42"), inbound=True)
    _email_row(ctx, a, sent_by="arjun", subject="Mock interview 2 — feedback and what to practise",
           body=("Hi Aarav,\n\nGood progress today. Your funding answer is now crisp (loan + father's savings, with the USD figures).\n\n"
                 "Work on: the return-plan answer — name the role and the employer type you are targeting in Bengaluru, and keep every answer under 20 seconds.\n\n"
                 "We will do one more session before the DS-160 goes in.\n\nBest,\nArjun"),
           body_html=("<p>Hi Aarav,</p><p>Good progress today. Your funding answer is now crisp (loan + father's savings, with the USD figures).</p>"
                      "<p><b>Work on:</b> the return-plan answer — name the role and the employer type you are targeting in Bengaluru, and keep every answer under 20 seconds.</p>"
                      "<p>We will do one more session before the DS-160 goes in.</p><p>Best,<br>Arjun</p>"),
           created_at=at(-4, "13:05"))
    i = c["ishita"]
    _email_row(ctx, i, sent_by="arjun", subject="CAS issued — your 28-day maintenance window",
           body=("Hi Ishita,\n\nLeeds has issued your CAS (E4G2LEEDS2026X1). The £12,006 maintenance must stay in your account for 28 consecutive days — "
                 "your statement closes on the 4th, so please do not move any money before then.\n\nNext: IHS payment and the online application.\n\nBest,\nArjun"),
           body_html=("<p>Hi Ishita,</p><p>Leeds has issued your CAS (<b>E4G2LEEDS2026X1</b>). The £12,006 maintenance must stay in your account for "
                      "<b>28 consecutive days</b> — your statement closes on the 4th, so please do not move any money before then.</p>"
                      "<p>Next: IHS payment and the online application.</p><p>Best,<br>Arjun</p>"),
           created_at=at(-8, "15:20"))
    _email_row(ctx, i, sent_by=None, subject="Re: CAS issued — your 28-day maintenance window",
           body="Got it, thank you! The loan disbursement letter should be ready by Monday — I will upload it through the link.",
           body_html=None, created_at=at(-7, "09:10"), inbound=True)
    k = c["karan"]
    _email_row(ctx, k, sent_by="rahul", subject=f"Biometrics booked — VFS Chandigarh, {fmt_long(d(3))}",
           body=(f"Hi Karan,\n\nYour biometrics appointment is confirmed for {fmt_long(d(3))} at 10:40, VFS Global Chandigarh. Carry the BIL printout and your passport.\n\n"
                 f"The IRCC deadline is {fmt_long(d(6))}, so please do not reschedule.\n\nBest,\nRahul"),
           body_html=(f"<p>Hi Karan,</p><p>Your biometrics appointment is confirmed for <b>{fmt_long(d(3))} at 10:40</b>, VFS Global Chandigarh. Carry the BIL printout and your passport.</p>"
                      f"<p>The IRCC deadline is <b>{fmt_long(d(6))}</b>, so please do not reschedule.</p><p>Best,<br>Rahul</p>"),
           created_at=at(-1, "09:30"))
    _email_row(ctx, k, sent_by="rahul", subject="Study permit application submitted — what happens next",
           body="Hi Karan,\n\nYour study permit application is in (S312345678). IRCC will send a biometrics instruction letter within a few days; we will book VFS as soon as it lands.\n\nBest,\nRahul",
           body_html="<p>Hi Karan,</p><p>Your study permit application is in (<b>S312345678</b>). IRCC will send a biometrics instruction letter within a few days; we will book VFS as soon as it lands.</p><p>Best,<br>Rahul</p>",
           created_at=at(-8, "17:50"))
    _email_row(ctx, c["meera"], sent_by="kavya", subject="Visa status update — further assessment",
           body="Hi Meera,\n\nYour ImmiAccount shows the application in further assessment. No documents have been requested; we check daily and will let you know the moment it changes.\n\nBest,\nKavya",
           body_html="<p>Hi Meera,</p><p>Your ImmiAccount shows the application in <b>further assessment</b>. No documents have been requested; we check daily and will let you know the moment it changes.</p><p>Best,<br>Kavya</p>",
           created_at=at(-2, "11:35"))
    _email_row(ctx, c["siddharth"], sent_by="kavya", subject=f"AIP received — tuition due by {fmt_long(d(13))}",
           body=f"Hi Siddharth,\n\nImmigration New Zealand has approved your visa in principle. Unitec tuition (NZD 18,500) must reach them by {fmt_long(d(13))}; the loan disbursement is scheduled for the 12th.\n\nBest,\nKavya",
           body_html=f"<p>Hi Siddharth,</p><p>Immigration New Zealand has <b>approved your visa in principle</b>. Unitec tuition (NZD 18,500) must reach them by <b>{fmt_long(d(13))}</b>; the loan disbursement is scheduled for the 12th.</p><p>Best,<br>Kavya</p>",
           created_at=at(-4, "16:20"))
    ctx.db.flush()


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------
def seed_calendar(ctx: Ctx) -> None:
    c = ctx.clients
    rows = [
        # (client key|None, title, type, day offset, time|None, created_by, notify, done, notes)
        ("ishita", "Chase @Ishita Rao for loan disbursement letter", "follow_up", 1, None, "arjun", False, False, "Statement closes on the 4th; disbursement letter promised by Monday."),
        ("karan", "IRCC BIL printout — confirm @Karan Singh has it before VFS", "task", 1, "09:30", "rahul", False, False, None),
        ("aarav", "Review corrected I-20 with @Aarav Mehta", "task", 2, "11:00", "arjun", True, False, "DSO reissue expected; file DS-160 the same day if the name is right."),
        (None, "Weekly pipeline review", "other", 2, "16:00", "ananya", False, False, "All offices — dial in from Hyderabad and Kochi."),
        ("karan", "VFS biometrics @Karan Singh — Chandigarh", "appointment", 3, "10:40", "rahul", True, False, None),
        ("kabir", "GS statement review @Kabir Chopra", "task", 4, "15:00", "priya", False, False, "Draft v2 from the client; check the return-to-India paragraph."),
        ("divya", "Sperrkonto top-up confirmation due @Divya Pillai", "reminder", 5, None, "arjun", True, False, "Expatrio confirmation of the remaining EUR 5,904."),
        ("karan", "IRCC biometrics deadline @Karan Singh", "deadline", 6, None, "rahul", False, False, None),
        ("sana", "VFS biometrics @Sana Mirza — Bengaluru", "appointment", 8, "09:15", "rahul", True, False, None),
        ("siddharth", "Passport renewal appointment @Siddharth Menon — PSK Trivandrum", "appointment", 9, "11:30", "kavya", True, False, "Current passport expires 30 Nov 2026 — before the February intake."),
        ("sneha", "Call @Sneha Iyer — IELTS prep check-in", "follow_up", 10, "17:30", "kavya", False, False, None),
        ("siddharth", "AIP tuition payment deadline @Siddharth Menon", "deadline", 13, None, "kavya", True, False, "NZD 18,500 to Unitec; loan disbursement on the 12th."),
        ("lakshmi", "Consulate appointment @Lakshmi Venkatesh — Bengaluru", "appointment", 14, "08:45", "rahul", True, False, "Carry the original Sperrkonto confirmation and TK certificate."),
        ("aisha", "Send firm acceptance to Birmingham @Aisha Siddiqui", "task", 23, None, "rahul", False, False, None),
        (None, "Team training — Deep Scan & Writing Studio", "other", 17, "15:00", "rahul", False, False, "45 minutes, all counsellors."),
        ("vikram", "Loan sanction follow-up @Vikram Joshi (Axis Bank)", "reminder", 26, "12:00", "arjun", False, False, None),
        (None, "Education fair — Hyderabad (HICC)", "other", 29, "10:00", "priya", False, False, "Stall 42; Priya + Deepak on the desk."),
        ("meera", "Check Immi status @Meera Nair", "task", -3, "10:00", "kavya", False, True, None),
        ("aarav", "Mock interview 2 @Aarav Mehta", "task", -4, "12:00", "arjun", False, True, None),
    ]
    for key, title, etype, off, tm, by, notify, done, notes in rows:
        ctx.add(models.EnterpriseCalendarEvent(
            organization_id=ctx.org_id, client_id=(c[key].id if key else None), title=title, notes=notes, event_type=etype,
            event_date=d(off), event_time=tm, is_done=done, notify_client=notify,
            created_by_user_id=ctx.uid[by], created_by_name=ctx.user_name(by),
            created_at=at(min(off, 0) - 3, "09:00"),
        ))
    ctx.db.flush()


# ---------------------------------------------------------------------------
# Document requests, portal shares, interview + copilot invites
# ---------------------------------------------------------------------------
def seed_links(ctx: Ctx) -> None:
    c = ctx.clients
    a = c["aarav"]
    docs_a = {doc.document_type: doc for doc in ctx.docs[a.id]}
    req = ctx.add(models.EnterpriseDocumentRequest(
        organization_id=ctx.org_id, client_id=a.id, token_hash=new_token_hash(), email=a.email,
        message="Please upload the signed sponsor affidavit and your father's ITR for FY24-25 and FY25-26.",
        status="partial", expires_at=at(18, "00:00"), revoked=False,
        created_by_user_id=ctx.uid["arjun"], created_by_name=ctx.user_name("arjun"), created_at=on(date(2026, 8, 19), "10:00"),
    ))
    ctx.db.flush()
    for label, doc_label, received_at in (
        ("Bank Statements / Balance Certificate", "Bank Statements / Balance Certificate", on(date(2026, 8, 20), "11:15")),
        ("Education Loan Sanction Letter", "Education Loan Sanction Letter", on(date(2026, 8, 22), "16:05")),
        ("Sponsor Affidavit of Support", None, None),
        ("Sponsor Income Tax Returns (ITR / Form 16)", None, None),
    ):
        doc = docs_a.get(doc_label) if doc_label else None
        ctx.add(models.EnterpriseDocumentRequestItem(
            request_id=req.id, organization_id=ctx.org_id, document_type=label,
            status=("received" if doc else "pending"), document_id=(doc.id if doc else None), received_at=received_at,
            created_at=req.created_at,
        ))
    i = c["ishita"]
    docs_i = {doc.document_type: doc for doc in ctx.docs[i.id]}
    req2 = ctx.add(models.EnterpriseDocumentRequest(
        organization_id=ctx.org_id, client_id=i.id, token_hash=new_token_hash(), email=i.email,
        message="CAS-stage documents — please upload originals as PDF.", status="completed", expires_at=at(20, "00:00"),
        revoked=False, completed_at=at(-3, "17:45"), created_by_user_id=ctx.uid["arjun"], created_by_name=ctx.user_name("arjun"),
        created_at=at(-10, "09:30"),
    ))
    ctx.db.flush()
    for label in ("CAS Statement", "SELT / IELTS-for-UKVI Result", "28-Day Bank Statement / Financial Evidence"):
        doc = docs_i.get(label)
        ctx.add(models.EnterpriseDocumentRequestItem(
            request_id=req2.id, organization_id=ctx.org_id, document_type=label, status="received",
            document_id=(doc.id if doc else None), received_at=(doc.created_at if doc else at(-3, "17:45")), created_at=req2.created_at,
        ))
    # portal shares (opened — feeds "Saved with Rilono")
    for key, opens, created_off, last_off, by in (("aarav", 3, -30, -2, "arjun"), ("ishita", 5, -25, -1, "arjun"),
                                                  ("karan", 4, -20, -1, "rahul"), ("meera", 2, -40, -6, "kavya")):
        cl = c[key]
        ctx.add(models.EnterpriseClientPortalShare(
            organization_id=ctx.org_id, client_id=cl.id, token_hash=new_token_hash(), email=cl.email,
            expires_at=at(created_off + 180, "00:00"), revoked=False, last_opened_at=at(last_off, "20:15"), open_count=opens,
            created_by_user_id=ctx.uid[by], created_by_name=ctx.user_name(by), created_at=at(created_off, "09:00"),
        ))
    # interview invites
    ctx.add(models.EnterpriseInterviewInvite(
        organization_id=ctx.org_id, client_id=a.id, token_hash=new_token_hash(), email=a.email, allowed_count=3, used_count=2,
        completed_count=2, last_completed_at=at(-4, "12:30"), expires_at=at(14, "00:00"), revoked=False,
        created_by_user_id=ctx.uid["arjun"], created_by_name=ctx.user_name("arjun"), created_at=at(-16, "09:00"),
    ))
    ctx.add(models.EnterpriseInterviewInvite(
        organization_id=ctx.org_id, client_id=i.id, token_hash=new_token_hash(), email=i.email, allowed_count=2, used_count=1,
        completed_count=1, last_completed_at=at(-6, "19:05"), expires_at=at(22, "00:00"), revoked=False,
        created_by_user_id=ctx.uid["arjun"], created_by_name=ctx.user_name("arjun"), created_at=at(-8, "15:30"),
    ))
    # copilot invite (activated, 12 of 100 messages used)
    ctx.add(models.EnterpriseCopilotInvite(
        organization_id=ctx.org_id, client_id=a.id, token_hash=new_token_hash(), email=a.email, allowed_messages=100,
        used_messages=12, last_message_at=at(-1, "21:10"), unlocked_at=at(-11, "18:30"), credits_charged=20,
        code_attempts=0, code_attempts_total=1, expires_at=at(18, "00:00"), revoked=False,
        created_by_user_id=ctx.uid["arjun"], created_by_name=ctx.user_name("arjun"), created_at=at(-12, "09:05"),
    ))
    ctx.db.flush()


# ---------------------------------------------------------------------------
# Mock interviews
# ---------------------------------------------------------------------------
def seed_interviews(ctx: Ctx) -> None:
    c = ctx.clients
    a = c["aarav"]
    latest = [
        {"role": "officer", "content": "Good morning. Which university are you going to, and why that one?"},
        {"role": "user", "content": "Good morning, officer. The University of Illinois Urbana-Champaign, for an MS in Computer Science. I chose it for the distributed-systems group — my final-year project was a Raft-based key-value store, and their systems faculty is the best fit for it."},
        {"role": "officer", "content": "Who is paying for this, and what is the total cost for the first year?"},
        {"role": "user", "content": "The I-20 shows 68,500 dollars for the first year. An education loan of 35 lakh rupees from SBI — about 42,000 dollars — is sanctioned, and my father covers the rest from his savings; his HDFC statement shows around 32 lakh."},
        {"role": "officer", "content": "What will you do after the degree?"},
        {"role": "user", "content": "I plan to come back to Bengaluru and work on payment infrastructure. There is a lot of demand for that profile in India right now."},
        {"role": "officer", "content": "Thank you. Please wait — your application needs a little more review before a decision."},
    ]
    feedback_latest = (
        "**Verdict:** Borderline · **Readiness:** 3/5\n\n"
        "### What went well\n"
        "- **Clear program fit** — named the systems group and tied it to his own project.\n"
        "- **Funding figures were specific** — I-20 total, loan amount and sponsor savings all quoted.\n\n"
        "### Red flags\n"
        "- **Return plan is vague** — \"a lot of demand\" names no role, employer or salary band.\n"
        "- **Sponsor income unmentioned** — savings alone read like a one-off deposit.\n"
        "- **Name mismatch risk** — the I-20 middle name may be raised at the window; no answer prepared.\n\n"
        "### How to improve\n"
        "- **Name a concrete role** — e.g. 'backend engineer on a UPI payments team in Bengaluru, ₹18–22 LPA'.\n"
        "- **State sponsor income** — father's annual income and occupation in one line.\n"
        "- **Rehearse the I-20 name answer** — say the corrected I-20 is issued and carry both copies.\n\n"
        "### Model answer\n"
        "After the MS I will return to Bengaluru to work as a backend engineer on payment infrastructure — my current employer has an applied-systems team "
        "that hires exactly this profile at ₹18–22 lakh a year. My parents, my father's business and my home are all in Bengaluru."
    )
    earlier = [
        {"role": "officer", "content": "Good morning. Why do you want to study in the United States?"},
        {"role": "user", "content": "Because US universities are the best for computer science and I want a good career."},
        {"role": "officer", "content": "How will you pay for it?"},
        {"role": "user", "content": "My father will pay, and I am applying for a loan."},
        {"role": "officer", "content": "Do you plan to stay in the US after graduation?"},
        {"role": "user", "content": "Maybe for some time, if I get a good job. I have not decided yet."},
        {"role": "officer", "content": "I am not able to issue the visa today. You may reapply."},
    ]
    feedback_earlier = (
        "**Verdict:** Needs Work · **Readiness:** 2/5\n\n"
        "### What went well\n"
        "- **Calm delivery** — short answers, no rambling.\n\n"
        "### Red flags\n"
        "- **No specific university reason** — 'the best for computer science' fits any applicant.\n"
        "- **Funding unquantified** — no loan amount, no first-year figure, loan not yet sanctioned.\n"
        "- **Immigrant intent signalled** — 'maybe stay' is the single most damaging answer under 214(b).\n\n"
        "### How to improve\n"
        "- **Name the program and a professor** — connect UIUC to your own project.\n"
        "- **Quote the numbers** — first-year cost, loan amount, sponsor savings.\n"
        "- **Commit to a return plan** — a role, a city, family ties.\n\n"
        "### Model answer\n"
        "My first year costs 68,500 dollars. A sanctioned SBI loan of about 42,000 dollars covers most of it and my father's savings cover the rest; "
        "after the degree I am returning to Bengaluru, where my family and my job prospects in fintech are."
    )
    ctx.add(models.EnterpriseInterviewSession(
        organization_id=ctx.org_id, client_id=a.id, conducted_by_user_id=None, conducted_by_name="Aarav Mehta (self-serve)",
        mode="voice", transcript=json.dumps(latest, ensure_ascii=False), feedback=feedback_latest, verdict="Borderline",
        created_at=at(-4, "12:30"),
    ))
    ctx.add(models.EnterpriseInterviewSession(
        organization_id=ctx.org_id, client_id=a.id, conducted_by_user_id=ctx.uid["arjun"], conducted_by_name=ctx.user_name("arjun"),
        mode="chat", transcript=json.dumps(earlier, ensure_ascii=False), feedback=feedback_earlier, verdict="Needs Work",
        created_at=at(-15, "11:10"),
    ))
    i = c["ishita"]
    transcript_i = [
        {"role": "officer", "content": "Good afternoon. Tell me about the course you have chosen and why Leeds."},
        {"role": "user", "content": "MSc International Business at the University of Leeds. Leeds is triple-accredited, the course has a consulting project with a real client, and my two years at a Bengaluru export house are exactly what the module on emerging-market strategy builds on."},
        {"role": "officer", "content": "How are you funding the course and your living costs?"},
        {"role": "user", "content": "Tuition is £21,500 — £3,000 is paid as the deposit and the rest is covered by a sanctioned HDFC Credila loan. For maintenance I hold £12,006 in my own account; it has been there for over 28 days as the rules require."},
        {"role": "officer", "content": "What will you do once the course finishes?"},
        {"role": "user", "content": "I intend to return to Bengaluru and rejoin the export sector at a strategy level. My family's business is there, and the UK degree is the credential that opens the senior roles."},
        {"role": "officer", "content": "Thank you — that is all I need."},
    ]
    feedback_i = (
        "**Verdict:** Likely Approved · **Readiness:** 4/5\n\n"
        "### What went well\n"
        "- **Specific course rationale** — accreditation, module and work history linked together.\n"
        "- **Maintenance rule understood** — quoted the 28-day requirement and the exact figure.\n"
        "- **Credible return plan** — family business and sector named.\n\n"
        "### Red flags\n"
        "- **Loan sanction date** — be ready to say when the Credila sanction was issued.\n"
        "- **Slightly rehearsed tone** — vary the pacing on the funding answer.\n\n"
        "### How to improve\n"
        "- **Lead with the total** — £21,500 tuition first, then the split.\n"
        "- **Name the role** — 'strategy manager' rather than 'strategy level'.\n"
        "- **Keep answers under 25 seconds** — the credibility interview is short.\n\n"
        "### Model answer\n"
        "Tuition is £21,500: £3,000 paid to Leeds already and £18,500 from a Credila loan sanctioned on 14 August. Maintenance of £12,006 has been in my ICICI account since early August."
    )
    ctx.add(models.EnterpriseInterviewSession(
        organization_id=ctx.org_id, client_id=i.id, conducted_by_user_id=None, conducted_by_name="Ishita Rao (self-serve)",
        mode="chat", transcript=json.dumps(transcript_i, ensure_ascii=False), feedback=feedback_i, verdict="Likely Approved",
        created_at=at(-6, "19:05"),
    ))
    ctx.db.flush()


# ---------------------------------------------------------------------------
# Writing Studio drafts
# ---------------------------------------------------------------------------
SOP_V1 = """# Statement of Purpose

**Aarav Mehta · MS Computer Science · University of Illinois Urbana-Champaign · Spring 2027**

The first production incident I owned was a settlement batch that silently dropped 0.3% of transactions under load. Tracing it to a race in a badly partitioned queue taught me more about distributed systems in a week than a semester of lectures had — and it is why I want to spend the next two years studying them properly.

## Academic background

I graduated in 2025 with a B.E. in Computer Science (CGPA 8.6/10) from RV College of Engineering, Bengaluru, with no backlogs. My final-year project, a Raft-based key-value store benchmarked against etcd, won the department's systems award, and my GRE score of 324 (Q 168) reflects the same quantitative grounding.

## Why Illinois

The Distributed Protocols Research Group's work on consistency in geo-replicated storage maps directly onto the failure I described above. CS 425 Distributed Systems, CS 525 Advanced Distributed Systems and the cloud-computing sequence are the exact toolkit my first year in industry lacked, and Professor [PLACEHOLDER: faculty name]'s group is where I would like to spend my second year.

## Plans after graduation

India's UPI network clears more than 15 billion transactions a month, and the engineers who can keep those rails resilient are in short supply. I intend to return to Bengaluru and rejoin the payments-infrastructure space at a senior engineering level, where a US master's degree is the credential that opens those doors.

Thank you for considering my application.

Sincerely,
Aarav Mehta"""

SOP_V2 = """# Statement of Purpose

**Aarav Mehta · MS Computer Science · University of Illinois Urbana-Champaign · Spring 2027**

The first production incident I owned was a settlement batch that dropped 0.3% of transactions once throughput crossed 4,000 messages a second. The root cause was a partition-key collision in a Kafka consumer group that let two workers claim the same offset; fixing it meant re-deriving the key from the merchant ledger and adding an idempotency table. That week taught me more about distributed systems than a semester of lectures — and it is why I want to spend two years studying them properly.

## Academic background

I graduated in 2025 with a B.E. in Computer Science (CGPA 8.6/10) from RV College of Engineering, Bengaluru, with no backlogs. My final-year project, a Raft-based key-value store, reached a 99th-percentile write latency of 4.1 ms against etcd's 3.6 ms at 5,000 ops/s on the same three-node cluster, and won the department's systems award. My GRE score of 324 (Q 168) reflects the same quantitative grounding.

## Why Illinois

The Distributed Protocols Research Group's work on consistency in geo-replicated storage maps directly onto the failure I described above. CS 425 Distributed Systems, CS 525 Advanced Distributed Systems and CS 598 Cloud Computing are the exact toolkit my first year in industry lacked, and Professor [PLACEHOLDER: faculty name]'s group is where I would like to spend my second year.

## Plans after graduation

India's UPI network clears more than 15 billion transactions a month, and the engineers who can keep those rails resilient are in short supply. I intend to return to Bengaluru and rejoin the payments-infrastructure space as a senior backend engineer, where a US master's degree is the credential that opens those doors.

Thank you for considering my application.

Sincerely,
Aarav Mehta"""

LOR_AARAV = """Dr. Shalini Rao
Associate Professor, Department of Computer Science & Engineering
RV College of Engineering, Bengaluru
shalini.rao@example.com

[PLACEHOLDER: date]

To the Graduate Admissions Committee, University of Illinois Urbana-Champaign

Dear Committee Members,

It is my pleasure to recommend Aarav Mehta for the MS in Computer Science. I taught Aarav in Distributed Systems (CS-702) during 2024-25 and supervised his final-year project, so I have seen him both in a lecture hall of 120 students and across a table for eight months.

Of roughly [PLACEHOLDER: cohort size] students I have taught this module since 2019, Aarav sits comfortably in the top five. His examination answers were unusual not for length but for precision — he was the only student that year to reason correctly about the linearizability of a two-phase-commit variant under coordinator failure.

His project, a Raft-based key-value store, was the strongest systems project I have supervised. He benchmarked it honestly against etcd, reported where it lost, and then spent three weeks closing the gap in the log-compaction path rather than in the demo. When the department's server cluster failed a week before the review, he rebuilt the test harness on borrowed laptops without asking for an extension.

If I have one reservation it is that Aarav can be slow to ask for help; he prefers to have exhausted his own ideas first. He has grown noticeably in this respect and now runs a weekly reading group for juniors.

I recommend him without hesitation and would be glad to discuss his work further.

Sincerely,

Dr. Shalini Rao
Associate Professor, Dept. of CSE"""

PS_ISHITA = """# Personal Statement

**Ishita Rao · MSc International Business · University of Leeds · January 2027**

Two years of pricing export consignments for a Bengaluru garment house taught me that the difference between a profitable order and a loss-making one is rarely the product — it is the market knowledge behind the quote. That gap is what I want to close at Leeds.

## Academic foundation

I graduated in 2024 with a B.Com (74%) from Christ University, Bengaluru, with a specialisation in international trade. My dissertation on tariff pass-through in Indian textile exports was shortlisted for the department prize.

## Professional experience

At [PLACEHOLDER: employer name] I moved from documentation to pricing within a year, and now own quotes for the European buyers. In the 2025-26 season I renegotiated freight terms that saved the company roughly 4% on landed cost.

## Why Leeds

The triple-accredited Business School, the live consulting project and the module on emerging-market strategy are a direct match for the work I already do. Leeds' alumni network in South Asian trade is a further draw.

## Career plan

I will return to Bengaluru after the course to lead export strategy for a mid-sized manufacturer, where a UK master's degree opens senior roles that a B.Com alone does not.

Thank you for considering my application."""


def seed_writing(ctx: Ctx) -> None:
    c = ctx.clients
    a = c["aarav"]
    v1 = ctx.add(models.EnterpriseClientWritingDraft(
        organization_id=ctx.org_id, client_id=a.id, doc_type="sop", version=1, country_code="US",
        university="University of Illinois Urbana-Champaign", program="MS Computer Science", study_level="Master's", intake="Spring 2027",
        brief="Lead with the settlement-batch incident; connect it to distributed-systems coursework; keep the return plan (Bengaluru payments) explicit; under 550 words.",
        title="Statement of Purpose", content_md=SOP_V1,
        notes_md=("- **[PLACEHOLDER: faculty name]** — confirm the professor Aarav wants to name (no faculty preference in the dossier).\n"
                  "- Word count is 418; UIUC has no hard limit but under 600 reads best.\n"
                  "- The return-plan paragraph is the interview spine — keep it consistent with what he says at the consulate."),
        word_count=418, model_used="gemini-2.5-pro", credits_charged=1, created_by_user_id=ctx.uid["arjun"],
        created_by_name=ctx.user_name("arjun"), created_at=on(date(2026, 6, 18), "12:00"),
    ))
    ctx.db.flush()
    v1.root_id = v1.id
    ctx.add(models.EnterpriseClientWritingDraft(
        organization_id=ctx.org_id, client_id=a.id, doc_type="sop", root_id=v1.id, version=2, country_code="US",
        university="University of Illinois Urbana-Champaign", program="MS Computer Science", study_level="Master's", intake="Spring 2027",
        brief=None, instruction="Make it more technical and name the etcd benchmark numbers", title="Statement of Purpose", content_md=SOP_V2,
        notes_md="- Faculty name is still a **[PLACEHOLDER]**.\n- Verify the 4.1 ms / 3.6 ms latency figures against the project report before submission.",
        word_count=471, model_used="gemini-2.5-pro", credits_charged=1, created_by_user_id=ctx.uid["arjun"],
        created_by_name=ctx.user_name("arjun"), created_at=at(-3, "09:30"),
    ))
    lor = ctx.add(models.EnterpriseClientWritingDraft(
        organization_id=ctx.org_id, client_id=a.id, doc_type="lor", version=1, country_code="US",
        university="University of Illinois Urbana-Champaign", program="MS Computer Science", study_level="Master's", intake="Spring 2027",
        recommender_type="professor", recommender_name="Dr. Shalini Rao", recommender_title="Associate Professor, Dept. of CSE",
        recommender_org="RV College of Engineering", recommender_email="shalini.rao@example.com",
        relationship_context="Taught Distributed Systems (CS-702) in 2024-25 and supervised the Raft key-value store final-year project.",
        brief="Lean on the project, not grades. One candid limitation.", title="Letter of Recommendation", content_md=LOR_AARAV,
        notes_md=("- This is a draft for Dr. Rao to review, edit and sign on RVCE letterhead — never submit as drafted.\n"
                  "- **[PLACEHOLDER: cohort size]** — she must state the number of students behind the 'top five' claim.\n"
                  "- **[PLACEHOLDER: date]** — date it when signed."),
        word_count=352, model_used="gemini-2.5-pro", credits_charged=1, created_by_user_id=ctx.uid["arjun"],
        created_by_name=ctx.user_name("arjun"), created_at=on(date(2026, 6, 21), "10:00"),
    ))
    ctx.db.flush()
    lor.root_id = lor.id
    ps = ctx.add(models.EnterpriseClientWritingDraft(
        organization_id=ctx.org_id, client_id=c["ishita"].id, doc_type="sop", version=1, country_code="UK",
        university="University of Leeds", program="MSc International Business", study_level="Master's", intake="January 2027",
        brief="Export-house pricing experience first; keep it under 500 words; UK spelling.", title="Personal Statement", content_md=PS_ISHITA,
        notes_md="- **[PLACEHOLDER: employer name]** — the dossier has the sector but not the company; confirm with Ishita.\n- Word count 296 — room to add one concrete client story.",
        word_count=296, model_used="gemini-2.5-pro", credits_charged=1, created_by_user_id=ctx.uid["arjun"],
        created_by_name=ctx.user_name("arjun"), created_at=at(-48, "11:20"),
    ))
    ctx.db.flush()
    ps.root_id = ps.id
    ctx.db.flush()


# ---------------------------------------------------------------------------
# Deep Scan (hero client)
# ---------------------------------------------------------------------------
def seed_deep_scan(ctx: Ctx) -> None:
    a = ctx.clients["aarav"]
    n_docs = len(ctx.docs[a.id])
    findings = [
        {"severity": "critical", "category": "identity", "area": "documents",
         "title": "Passport name differs from I-20",
         "detail": "The passport reads AARAV MEHTA with no middle name; the I-20 issued by UIUC on 1 Aug 2026 reads MEHTA, AARAV RAKESH. "
                   "Consular officers cross-check the two at the window and a mismatch is the most common reason a Spring applicant is sent back for a corrected I-20.",
         "evidence": ["Passport (Aarav_Mehta_Passport.pdf): Surname MEHTA, Given names AARAV",
                      "Form I-20 (Aarav_Mehta_I20.pdf): Student name MEHTA, AARAV RAKESH",
                      "Profile: full_name = Aarav Mehta"],
         "recommendation": "Ask the UIUC DSO to reissue the I-20 with the passport name exactly; upload the corrected copy and re-scan it before the DS-160 is filed."},
        {"severity": "warning", "category": "financial", "area": "documents",
         "title": "Bank statement is in the sponsor's name and no affidavit is on file",
         "detail": "The HDFC statement belongs to Rakesh Mehta (father). Without a signed sponsor affidavit the statement does not evidence funds available to the applicant.",
         "evidence": ["Bank Statements / Balance Certificate: account holder RAKESH MEHTA, closing balance INR 32,40,000",
                      "Document request: 'Sponsor Affidavit of Support' still pending"],
         "recommendation": "Collect the signed affidavit and the father's ITR through the open document request, then scan both."},
        {"severity": "warning", "category": "process", "area": "interviews",
         "title": "Latest mock interview scored 3/5 with a weak return-plan answer",
         "detail": "The 2 Sep self-serve mock was rated Borderline; the officer probe on post-study plans drew a vague answer with no named role or employer.",
         "evidence": ["Mock interview (voice): Verdict Borderline · Readiness 3/5",
                      "Red flag: 'Return plan is vague — names no role, employer or salary band'"],
         "recommendation": "Run one more preview focused on ties to India before the DS-160 is filed."},
        {"severity": "info", "category": "timeline", "area": "stage_records",
         "title": "DS-160 not yet filed with 19 weeks to the course start",
         "detail": "Course starts 19 Jan 2027; Mumbai interview wait times for F-1 run 6-8 weeks in October, so the DS-160 should go in as soon as the corrected I-20 lands.",
         "evidence": ["stage_records.documents.course_start_date = 2027-01-19", "Stage: I-20 & Financial Evidence (DS-160 not recorded)"],
         "recommendation": "File the DS-160 the day the corrected I-20 arrives and book the OFC slot immediately."},
        {"severity": "info", "category": "data_quality", "area": "profile",
         "title": "Loan sanction letter names the course as MS Computer Engineering",
         "detail": "Staff accepted the SBI letter manually; the amount and borrower are correct but the course name differs from the admit. Not a blocker — worth a one-line explanation if asked.",
         "evidence": ["Education Loan Sanction Letter: course 'MS Computer Engineering' (manually approved by Arjun Menon)",
                      "Admission letter: MS Computer Science"],
         "recommendation": "No action needed; brief Aarav to say the bank used the department name."},
    ]
    checks = [
        "Date of birth on the passport (18 Apr 2003) matches the profile and the transcript",
        "Passport valid to Feb 2031 — beyond the I-20 program end date (Dec 2028)",
        "SEVIS ID N0034567890 on the I-20 matches the I-901 fee receipt",
        "University and program on the admission letter match the accepted offer on the shortlist",
        "Funds evidenced (loan INR 35,00,000 + sponsor savings INR 32,40,000) exceed the I-20 estimate of USD 68,500",
        "Transcript CGPA 8.60 and TOEFL 104 / GRE 324 match the profile",
    ]
    stats = {"critical": 1, "warning": 2, "info": 2, "documents_analyzed": n_docs, "documents_total": n_docs,
             "documents_skipped": 0, "documents_over_cap": 0, "extraction_failures": 0}
    ctx.add(models.EnterpriseClientDeepScan(
        organization_id=ctx.org_id, client_id=a.id, risk_level="medium",
        summary=("Aarav's file is largely consistent — academics, SEVIS details and funding all reconcile. One item must be fixed before the DS-160 is filed: "
                 "the I-20 carries a middle name the passport does not. The sponsor's bank statement also needs the affidavit that is still pending on the document request."),
        findings=json.dumps(findings, ensure_ascii=False), checks_passed=json.dumps(checks, ensure_ascii=False),
        stats=json.dumps(stats), model_used="gemini-2.5-pro", credits_charged=20,
        triggered_by_user_id=ctx.uid["arjun"], triggered_by_name=ctx.user_name("arjun"), created_at=at(-2, "10:05"),
    ))
    ctx.db.flush()


# ---------------------------------------------------------------------------
# Course Finder AI shortlists
# ---------------------------------------------------------------------------
def _rec_item(uni, course, level, location, fit, why, tuition, intakes, deadline, fee, reqs, course_url, site, qs, in_catalog):
    return {"university_name": uni, "course_name": course, "degree_level": level, "location": location, "fit_level": fit,
            "why_recommended": why, "annual_tuition": tuition, "intakes": intakes, "application_deadline": deadline,
            "application_fee": fee, "key_requirements": reqs, "course_url": course_url, "website_url": site,
            "qs_world_rank": qs, "in_catalog": in_catalog}


def seed_course_finder(ctx: Ctx) -> None:
    c = ctx.clients
    a = c["aarav"]
    recs_a = [
        _rec_item("University of Illinois Urbana-Champaign", "MS Computer Science", "masters", "Urbana, Illinois", "reach",
                  "Top-5 CS program with the strongest distributed-systems group on the list; his Raft project is exactly the profile it admits.",
                  "USD 38,000", "Fall, Spring", "15 Oct 2026 (Spring)", "USD 90", ["GPA 3.5+", "TOEFL 103+", "3 LORs"],
                  "https://cs.illinois.edu/academics/graduate", "https://illinois.edu", "64", True),
        _rec_item("Arizona State University", "MS Computer Science", "masters", "Tempe, Arizona", "match",
                  "Large CS faculty with a big-data track and a January start; consistently admits Indian applicants with an 8.6 CGPA.",
                  "USD 33,000", "Fall, Spring", "1 Oct 2026 (Spring)", "USD 115", ["GPA 3.0+", "TOEFL 80+", "GRE optional"],
                  "https://scai.engineering.asu.edu/graduate-degree-programs/", "https://www.asu.edu", "179", True),
        _rec_item("University of Texas at Dallas", "MS Computer Science", "masters", "Richardson, Texas", "match",
                  "Spring intake matches the plan, tuition sits under budget, and the Dallas corridor gives strong fintech internship access.",
                  "USD 30,500", "Fall, Spring", "15 Oct 2026 (Spring)", "USD 50", ["GPA 3.0+", "TOEFL 80+ / IELTS 6.5+", "GRE recommended"],
                  "https://cs.utdallas.edu/education/graduate/ms-cs/", "https://www.utdallas.edu", "501", True),
        _rec_item("Northeastern University", "MS Computer Science (Align)", "masters", "Boston, Massachusetts", "match",
                  "Co-op programme adds paid industry experience; strong fintech placement record in Boston and New York.",
                  "USD 34,000", "Fall, Spring", "1 Oct 2026 (Spring)", "USD 100", ["GPA 3.0+", "TOEFL 100+"],
                  "https://www.khoury.northeastern.edu/programs/computer-science-ms/", "https://www.northeastern.edu", "375", False),
        _rec_item("University of Texas at Arlington", "MS Computer Science", "masters", "Arlington, Texas", "safety",
                  "Rolling admission and the lowest tuition band keep this as a secure fallback in the same metro as UT Dallas.",
                  "USD 22,000", "Fall, Spring, Summer", "Rolling", "USD 75", ["GPA 3.0+", "TOEFL 79+"],
                  "https://www.uta.edu/academics/schools-colleges/engineering", "https://www.uta.edu", "801", False),
    ]
    ctx.add(models.EnterpriseCourseFinderRec(
        organization_id=ctx.org_id, client_id=a.id, client_name=a.full_name, country_code="US", degree_level="masters",
        discipline="Computer Science & IT",
        query=json.dumps({"client_id": a.id, "country_code": "US", "degree_level": "masters", "discipline": "Computer Science & IT",
                          "field_of_study": "MS Computer Science — distributed systems", "budget": "USD 35,000 / yr",
                          "notes": "Spring 2027 start preferred; STEM OPT important; loan sanctioned", "max_results": 5}),
        summary=("Five STEM-designated MS Computer Science programs matched to an 8.6 CGPA, GRE 324 and TOEFL 104 profile with a ~USD 35k budget. "
                 "One reach with the strongest systems group (UIUC), three solid matches with January starts, and one rolling-admission safety."),
        recommendations=json.dumps(recs_a, ensure_ascii=False), catalog_based=True, grounded=False, model_used="gemini-2.5-pro",
        credits_charged=5, created_by_user_id=ctx.uid["arjun"], created_by_name=ctx.user_name("arjun"), created_at=on(date(2026, 6, 13), "10:45"),
    ))
    i = c["ishita"]
    recs_i = [
        _rec_item("University of Leeds", "MSc International Business", "masters", "Leeds", "match",
                  "Triple-accredited, live consulting project, and a January 2027 start; 74% with two years' experience sits in the admit band.",
                  "GBP 26,500", "September, January", "30 Sep 2026 (January)", "GBP 25", ["2:2 honours or 60%+", "IELTS UKVI 6.5", "2 references"],
                  "https://courses.leeds.ac.uk", "https://www.leeds.ac.uk", "82", True),
        _rec_item("University of Manchester", "MSc Management", "masters", "Manchester", "reach",
                  "Alliance MBS is the most selective on the list; a strong reference on the export-pricing work would be needed.",
                  "GBP 29,000", "September", "15 Jan 2027 (September)", "GBP 60", ["2:1 honours", "IELTS 7.0", "Work experience preferred"],
                  "https://www.manchester.ac.uk/study/masters", "https://www.manchester.ac.uk", "34", True),
        _rec_item("University of Birmingham", "MSc International Business", "masters", "Birmingham", "match",
                  "Good fit for a trade-focused profile; January intake available and tuition below the budget ceiling.",
                  "GBP 25,000", "September, January", "31 Oct 2026 (January)", "GBP 0", ["2:2 honours", "IELTS 6.5"],
                  "https://www.birmingham.ac.uk/postgraduate", "https://www.birmingham.ac.uk", "80", True),
        _rec_item("University of Sheffield", "MSc International Management", "masters", "Sheffield", "safety",
                  "Reliable admit for the profile, strong scholarship coverage for Indian applicants.",
                  "GBP 24,000", "September", "1 Feb 2027", "GBP 0", ["2:2 honours", "IELTS 6.5"],
                  "https://www.sheffield.ac.uk/postgraduate", "https://www.sheffield.ac.uk", "105", True),
        _rec_item("Coventry University", "MSc Global Business", "masters", "Coventry", "safety",
                  "Lowest tuition on the list with a January cohort; keeps the plan safe if Leeds' CAS slips.",
                  "GBP 18,500", "September, January, May", "Rolling", "GBP 0", ["Any honours degree", "IELTS 6.5"],
                  "https://www.coventry.ac.uk/course-structure", "https://www.coventry.ac.uk", "651", False),
    ]
    ctx.add(models.EnterpriseCourseFinderRec(
        organization_id=ctx.org_id, client_id=i.id, client_name=i.full_name, country_code="UK", degree_level="masters",
        discipline="Business & Management",
        query=json.dumps({"client_id": i.id, "country_code": "UK", "degree_level": "masters", "discipline": "Business & Management",
                          "field_of_study": "MSc International Business", "budget": "GBP 27,000 / yr",
                          "notes": "January 2027 entry; export-trade background; sub-agent case", "max_results": 5}),
        summary=("Five business-school options for a 74% B.Com with two years of export-pricing experience and a GBP 27k tuition ceiling: one reach (Manchester), "
                 "two matches with January cohorts, and two safeties with rolling admission."),
        recommendations=json.dumps(recs_i, ensure_ascii=False), catalog_based=True, grounded=False, model_used="gemini-2.5-pro",
        credits_charged=5, created_by_user_id=ctx.uid["arjun"], created_by_name=ctx.user_name("arjun"), created_at=at(-60, "14:10"),
    ))
    k = c["karan"]
    recs_k = [
        _rec_item("Conestoga College", "PG Certificate — Applied AI", "diploma", "Kitchener, Ontario", "match",
                  "PGWP-eligible CIP code, co-op term and a January start; matches three years of analytics experience.",
                  "CAD 18,900", "January, May, September", "Rolling", "CAD 100", ["Bachelor's degree", "IELTS 6.5"],
                  "https://www.conestogac.on.ca/fulltime", "https://www.conestogac.on.ca", None, True),
        _rec_item("Humber Polytechnic", "PG Certificate — Data Analytics", "diploma", "Toronto, Ontario", "safety",
                  "Large Toronto job market and a PAL-eligible public DLI; slightly higher tuition.",
                  "CAD 19,500", "January, September", "Rolling", "CAD 75", ["Bachelor's degree", "IELTS 6.5"],
                  "https://humber.ca/programs", "https://humber.ca", None, True),
        _rec_item("University of Waterloo", "Master of Data Science and AI", "masters", "Waterloo, Ontario", "reach",
                  "Top-ranked AI programme; a 7.1 CGPA makes this a stretch without a strong statement of purpose.",
                  "CAD 32,000", "September", "1 Dec 2026", "CAD 125", ["B+ average", "IELTS 7.0", "Programming background"],
                  "https://uwaterloo.ca/data-science", "https://uwaterloo.ca", "115", True),
    ]
    ctx.add(models.EnterpriseCourseFinderRec(
        organization_id=ctx.org_id, client_id=k.id, client_name=k.full_name, country_code="CA", degree_level="diploma",
        discipline="Data Science & AI",
        query=json.dumps({"client_id": k.id, "country_code": "CA", "degree_level": "diploma", "discipline": "Data Science & AI",
                          "field_of_study": "Applied AI / Data Analytics", "budget": "CAD 20,000 / yr", "notes": "PGWP is the goal; Ontario preferred", "max_results": 3}),
        summary="Three PGWP-eligible Ontario options for a 7.1 CGPA with three years of analytics experience: two college PG certificates inside budget and one university reach.",
        recommendations=json.dumps(recs_k, ensure_ascii=False), catalog_based=True, grounded=False, model_used="gemini-2.5-pro",
        credits_charged=5, created_by_user_id=ctx.uid["rahul"], created_by_name=ctx.user_name("rahul"), created_at=at(-71, "12:40"),
    ))
    ctx.db.flush()


# ---------------------------------------------------------------------------
# Lead forms + leads
# ---------------------------------------------------------------------------
WEBSITE_FIELDS = [
    {"key": "full_name", "label": "Full name", "type": "text", "required": True, "placeholder": "Your name"},
    {"key": "email", "label": "Email", "type": "email", "required": True},
    {"key": "phone_whatsapp", "label": "Phone / WhatsApp", "type": "phone", "required": False},
    {"key": "which_country_are_you_interested_in", "label": "Which country are you interested in?", "type": "select", "required": True,
     "options": ["USA", "UK", "Canada", "Australia", "Germany", "Ireland", "New Zealand", "Singapore", "Other"]},
    {"key": "preferred_intake", "label": "Preferred intake", "type": "select", "required": False,
     "options": ["January 2027", "May 2027", "September 2027", "Not sure yet"]},
    {"key": "anything_you_d_like_to_tell_us", "label": "Anything you'd like to tell us?", "type": "textarea", "required": False},
]
INSTAGRAM_FIELDS = [
    {"key": "full_name", "label": "Full name", "type": "text", "required": True},
    {"key": "phone_whatsapp", "label": "Phone / WhatsApp", "type": "phone", "required": True},
    {"key": "email", "label": "Email", "type": "email", "required": False},
    {"key": "which_country_are_you_interested_in", "label": "Which country are you interested in?", "type": "select", "required": True,
     "options": ["USA", "UK", "Canada", "Australia", "Germany", "Ireland", "New Zealand", "Singapore", "Other"]},
    {"key": "i_agree_to_be_contacted_on_whatsapp", "label": "I agree to be contacted on WhatsApp", "type": "checkbox", "required": False},
]


def _answers(fields: list[dict], values: dict) -> list[dict]:
    out = []
    for f in fields:
        value = values.get(f["key"], "")
        if value == "" and f["type"] != "checkbox":
            continue
        out.append({"key": f["key"], "label": f["label"], "type": f["type"], "value": value})
    return out


def seed_leads(ctx: Ctx) -> None:
    web = ctx.add(models.EnterpriseLeadForm(
        organization_id=ctx.org_id, name="Website enquiries", title="Plan your study-abroad journey",
        intro_text="Tell us a little about yourself and a counsellor will call you within one working day.",
        fields_json=json.dumps(WEBSITE_FIELDS), public_token=WEBSITE_FORM_TOKEN, is_active=True,
        submit_label="Get a free consultation", success_message="Thanks! A counsellor will reach out within 24 hours.",
        notify_email="hello@meridian.example.com", created_by_user_id=ctx.uid["rahul"], created_by_name=ctx.user_name("rahul"),
        created_at=at(-62, "11:00"),
    ))
    insta = ctx.add(models.EnterpriseLeadForm(
        organization_id=ctx.org_id, name="Instagram campaign", title="September intake — free profile check",
        intro_text="Drop your details and we'll WhatsApp you a free shortlist for your country of choice.",
        fields_json=json.dumps(INSTAGRAM_FIELDS), public_token=INSTAGRAM_FORM_TOKEN, is_active=True,
        submit_label="Get my free shortlist", success_message="Done! We'll WhatsApp you within a few hours.",
        notify_email="hello@meridian.example.com", created_by_user_id=ctx.uid["rahul"], created_by_name=ctx.user_name("rahul"),
        created_at=at(-21, "16:30"),
    ))
    ctx.db.flush()
    leads = [
        # (form, name, email, phone, country, intake, message, status, source, day offset, time, converted key)
        (web, "Ritika Menon", "ritika.menon@example.com", "+91 98470 22110", "Canada", "September 2027",
         "B.Sc. Nursing final year, looking at Ontario colleges with a PGWP pathway.", "new", "google / utm_campaign=canada-nursing", -1, "10:12", None),
        (insta, "Sana Qureshi", "sana.qureshi@example.com", "+91 99860 33445", "Australia", "",
         "", "new", "instagram / utm_campaign=sep-intake", -1, "18:40", None),
        (web, "Vivek Anand", "vivek.anand@example.com", "+91 98440 77123", "USA", "September 2027",
         "MS in Data Science; GRE 318, 2 years at a Bengaluru startup. Budget around 30 lakh.", "new", "website", -2, "09:35", None),
        (insta, "Prerna Joshi", "prerna.joshi@example.com", "+91 90080 55671", "Germany", "",
         "", "new", "instagram / utm_campaign=sep-intake", -3, "21:05", None),
        (web, "Tanya Kapoor", "tanya.kapoor@example.com", "+91 98310 44567", "UK", "January 2027",
         "LLM at a Russell Group university; need help with the personal statement.", "contacted", "referral", -4, "14:20", None),
        (insta, "Mohit Saini", "mohit.saini@example.com", "+91 97170 66890", "Canada", "",
         "", "contacted", "instagram / utm_campaign=sep-intake", -6, "12:48", None),
        (web, "Arnav Bhat", "arnav.bhat@example.com", "+91 99450 11234", "Ireland", "September 2027",
         "MSc Computer Science in Dublin; want to compare UCD and TCD costs.", "contacted", "google / utm_campaign=ireland-msc", -7, "16:15", None),
        (web, "Ananya Sharma", "ananya.sharma@example.com", "+91 98765 43210", "Germany", "September 2027",
         "Class 12 with 91%, interested in a CS bachelor's at a public university. Would like to know about Studienkolleg.",
         "converted", "instagram / utm_campaign=sep-intake", -2, "12:48", "ananyas"),
        (web, "Kabir Shah", "kabir.shah@example.com", "+91 98200 99887", "Singapore", "Not sure yet",
         "Already holds an NUS offer — only needs help with the Student's Pass.", "closed", "website", -9, "11:00", None),
    ]
    for form, name, email, phone, country, intake, message, status, source, off, tm, conv in leads:
        if form is web:
            answers = _answers(WEBSITE_FIELDS, {"full_name": name, "email": email, "phone_whatsapp": phone,
                                                 "which_country_are_you_interested_in": country, "preferred_intake": intake,
                                                 "anything_you_d_like_to_tell_us": message})
        else:
            answers = _answers(INSTAGRAM_FIELDS, {"full_name": name, "phone_whatsapp": phone, "email": email,
                                                   "which_country_are_you_interested_in": country,
                                                   "i_agree_to_be_contacted_on_whatsapp": "Yes"})
        ctx.add(models.EnterpriseLead(
            organization_id=ctx.org_id, form_id=form.id, form_name=form.name, full_name=name, email=email, phone=phone,
            answers_json=json.dumps(answers, ensure_ascii=False), status=status,
            converted_client_id=(ctx.clients[conv].id if conv else None), ip_address=f"103.21.{_rng(name).randint(10, 99)}.{_rng(name, 2).randint(10, 250)}",
            source=source, created_at=(ctx.clients[conv].created_at if conv else at(off, tm)),
            updated_at=(at(off + 1, "10:00") if status != "new" else None),
        ))
    ctx.db.flush()


# ---------------------------------------------------------------------------
# Finance: settings (get-or-create), entries, student payments, payment events
# ---------------------------------------------------------------------------
def seed_finance(ctx: Ctx) -> None:
    c = ctx.clients
    settings = ctx.db.query(models.EnterpriseFinanceSettings).filter(
        models.EnterpriseFinanceSettings.organization_id == ctx.org_id).first()
    if settings is None:
        ctx.add(models.EnterpriseFinanceSettings(
            organization_id=ctx.org_id, hourly_cost_paise=55_000, opening_balance_paise=12_500_000,
            opening_balance_on=date(2026, 4, 1), fy_start_month=4,
            savings_overrides_json=json.dumps({"deep_scan": 60, "mock_interview": 40, "writing_studio": 90, "course_finder": 35,
                                               "university_match": 30, "document_collected": 8, "client_email": 4, "portal_share": 20,
                                               "reminder_sent": 5, "copilot_message": 4, "payment_collected": 10}),
            updated_by_user_id=ctx.uid["sanjay"], created_at=at(-150, "10:00"),
        ))

    def entry(off, kind, cat, amount, method, counterparty, desc, client_key=None, tax=0, ref=None, repeat=False, by="sanjay"):
        cl = c[client_key] if client_key else None
        occurred = d(off) if not repeat else d(off).replace(day=1)
        ctx.add(models.EnterpriseFinanceEntry(
            organization_id=ctx.org_id, kind=kind, category=cat, amount_paise=amount, tax_paise=tax, currency="INR",
            occurred_on=occurred, description=desc, counterparty=counterparty, payment_method=method, reference=ref,
            client_id=(cl.id if cl else None), client_name_snapshot=(cl.full_name if cl else None), repeat_monthly=repeat,
            created_by_user_id=ctx.uid[by], created_by_name=ctx.user_name(by), created_at=on(occurred, "18:00"), version=1,
        ))

    entry(-58, "income", "service_fee", 4_500_000, "upi", "Rohan Desai", "Counselling & application service fee — 3 universities", "rohan", tax=810_000, ref="RCPT-2026-0412")
    entry(-52, "income", "university_commission", 12_000_000, "bank_transfer", "University of Wollongong", "Commission — July 2026 intake (2 students)", ref="UOW-COM-0726")
    entry(-4, "income", "university_commission", 18_500_000, "bank_transfer", "Deakin University", "Commission — February 2027 intake (3 students)", ref="DKN-COM-0926")
    entry(-5, "income", "service_fee", 4_500_000, "bank_transfer", "Meera Nair", "Service fee instalment 3 of 3", "meera", tax=810_000, ref="RCPT-2026-0474")
    entry(-3, "income", "service_fee", 3_500_000, "upi", "Tanvi Agarwal", "Service fee instalment 2 of 3", "tanvi", tax=630_000, ref="RCPT-2026-0479")
    entry(-45, "income", "test_prep", 1_200_000, "cash", "Sneha Iyer", "IELTS coaching — 6 weeks", "sneha")
    entry(-40, "expense", "marketing", 6_500_000, "card", "Meta Ads", "Instagram lead campaign — September intake", tax=1_170_000, ref="META-INV-88213")
    entry(-33, "income", "visa_filing", 2_500_000, "upi", "Karan Singh", "IRCC filing & biometrics assistance", "karan", ref="RCPT-2026-0447")
    entry(-27, "expense", "agent_commission", 2_000_000, "bank_transfer", "Sunrise Overseas, Rajkot", "Sub-agent commission — Ishita Rao", "ishita", ref="SUNRISE-0826")
    entry(-20, "expense", "software", 380_000, "card", "Zoom / Google Workspace", "Team subscriptions — August", tax=68_400)
    entry(-14, "income", "document_service", 800_000, "cash", "Divya Pillai", "Apostille & German translations", "divya")
    entry(-9, "expense", "travel_events", 3_200_000, "card", "Bengaluru Education Fair", "Stall + travel — September fair", ref="BEF-2026-19")
    entry(-6, "income", "test_prep", 1_500_000, "upi", "Varun Nambiar", "IELTS coaching — 8 weeks", "varun", ref="RCPT-2026-0471")
    entry(-5, "expense", "marketing", 2_400_000, "card", "Google Ads", "Search campaign — Canada PGWP & Australia MBA", tax=432_000, ref="GADS-SEP-01")
    entry(-3, "expense", "office", 450_000, "upi", "Stationery Mart", "Printing & courier — September")
    entry(-2, "income", "document_service", 600_000, "upi", "Lakshmi Venkatesh", "Sperrkonto & insurance paperwork", "lakshmi", ref="RCPT-2026-0478")
    entry(-1, "income", "service_fee", 3_000_000, "bank_transfer", "Aditya Kulkarni", "Application service fee — NUS / NTU / SMU", "aditya", tax=540_000, ref="RCPT-2026-0481")
    entry(-160, "expense", "salaries", 22_000_000, "bank_transfer", "Staff payroll", "Monthly salaries (4 counsellors + admin)", repeat=True)
    entry(-160, "expense", "rent_utilities", 6_500_000, "bank_transfer", "Landlord — Koramangala", "Office rent & utilities", repeat=True)

    def razorpay(client_key, amount, desc, invoice, off_created, off_paid, off_settled, status, settlement, due_off=None, by="sanjay"):
        cl = c[client_key]
        commission = max(int(round(amount * 0.02)), 4_900)
        sfx = _code(invoice, "AAAAAAAAAAAAAA")
        p = ctx.add(models.EnterpriseStudentPayment(
            organization_id=ctx.org_id, client_id=cl.id, client_name_snapshot=cl.full_name, invoice_number=invoice, description=desc,
            amount_paise=amount, commission_paise=commission, payout_paise=amount - commission, currency="INR", provider="razorpay",
            is_international=False, razorpay_order_id=f"order_{sfx}", razorpay_payment_id=(f"pay_{sfx}" if status != "created" else None),
            razorpay_transfer_id=(f"trf_{sfx}" if status in ("transferred", "settled") else None), status=status,
            settlement_status=settlement, utr=(f"HDFCR5{_code(invoice, '99999999999')}" if status == "settled" else None),
            refunded_amount_paise=0, due_date=(d(due_off) if due_off is not None else d(off_created + 7)),
            created_by_user_id=ctx.uid[by], paid_at=(at(off_paid, "14:05") if off_paid is not None else None),
            settled_at=(at(off_settled, "03:00") if off_settled is not None else None), created_at=at(off_created, "09:00"),
            pay_token_hash=new_token_hash(), payer_email_snapshot=cl.email, payer_phone_snapshot=cl.phone,
            email_sent_at=at(off_created, "09:01"),
        ))
        ctx.db.flush()
        if status != "created":
            ctx.add(models.EnterprisePaymentEvent(
                organization_id=ctx.org_id, student_payment_id=p.id, razorpay_event_id=f"evt_{sfx}cap", event_type="payment.captured",
                entity_type="payment", entity_id=f"pay_{sfx}", amount_paise=amount,
                payload_json=json.dumps({"event": "payment.captured", "payment_id": f"pay_{sfx}", "amount": amount}),
                processed_at=at(off_paid, "14:06"), created_at=at(off_paid, "14:06"),
            ))
        if status in ("transferred", "settled"):
            ctx.add(models.EnterprisePaymentEvent(
                organization_id=ctx.org_id, student_payment_id=p.id, razorpay_event_id=f"evt_{sfx}trf", event_type="transfer.processed",
                entity_type="transfer", entity_id=f"trf_{sfx}", amount_paise=amount - commission,
                payload_json=json.dumps({"event": "transfer.processed", "transfer_id": f"trf_{sfx}", "amount": amount - commission}),
                processed_at=at(off_settled, "03:01"), created_at=at(off_settled, "03:01"),
            ))
        return p

    def manual(client_key, amount, desc, method, ref, off, by="sanjay"):
        cl = c[client_key]
        p = ctx.add(models.EnterpriseStudentPayment(
            organization_id=ctx.org_id, client_id=cl.id, client_name_snapshot=cl.full_name, description=desc, amount_paise=amount,
            commission_paise=0, payout_paise=amount, currency="INR", provider="manual", manual_method=method, status="paid", utr=ref,
            refunded_amount_paise=0, paid_at=on(d(off), "00:00") + IST_OFFSET, created_by_user_id=ctx.uid[by], created_at=at(off, "11:30"),
        ))
        ctx.db.flush()
        p.invoice_number = f"MAN-{ctx.org_id}-{p.id:06d}"
        return p

    razorpay("aarav", 4_500_000, "University application service fee (5 applications)", "INV-2026-0142", -78, -76, -73, "settled", "settled", by="arjun")
    razorpay("rohan", 4_500_000, "Visa filing & pre-departure package", "INV-2026-0151", -70, -68, -65, "settled", "settled", by="rahul")
    razorpay("meera", 6_500_000, "Application & visa service fee — Deakin", "INV-2026-0163", -55, -53, -50, "settled", "settled", by="kavya")
    razorpay("nehak", 3_000_000, "Pre-departure & POE support", "INV-2026-0177", -40, -38, -35, "settled", "settled")
    razorpay("karan", 2_500_000, "IRCC filing & biometrics assistance", "INV-2026-0204", -6, -4, None, "paid", "pending", by="rahul")
    razorpay("vikram", 3_500_000, "MBA application service fee — Monash", "INV-2026-0209", -4, -2, None, "paid", "pending", by="arjun")
    razorpay("aarav", 800_000, "Pre-departure & SEVIS check-in support", "INV-2026-0214", -2, None, None, "created", None, due_off=13, by="arjun")
    razorpay("aditya", 3_000_000, "Visa filing package — Student's Pass", "INV-2026-0215", -1, None, None, "created", None, due_off=9, by="priya")
    manual("aarav", 200_000, "Initial consultation fee", "upi", "UPI-416223889012", -95)
    manual("ishita", 1_500_000, "Service fee instalment 2 of 3", "bank_transfer", "NEFT-HDFC-71823490", -6, by="arjun")
    manual("sneha", 1_200_000, "IELTS coaching — 6 weeks", "cash", "CASH-0906", -45)
    ctx.db.flush()


# ---------------------------------------------------------------------------
# AI assistant threads for the owner
# ---------------------------------------------------------------------------
def seed_ai_conversations(ctx: Ctx) -> None:
    owner = ctx.uid["ananya"]

    def conversation(title, started: datetime, turns: list[tuple[str, str]], gap_minutes=3):
        conv = ctx.add(models.EnterpriseAiConversation(
            organization_id=ctx.org_id, user_id=owner, title=title, message_count=len(turns) * 2,
            created_at=started, last_message_at=started + timedelta(minutes=gap_minutes * (len(turns) - 1) + 1),
        ))
        ctx.db.flush()
        t = started
        for user_msg, model_msg in turns:
            ctx.add(models.EnterpriseAiMessage(conversation_id=conv.id, organization_id=ctx.org_id, role="user", content=user_msg, created_at=t))
            ctx.add(models.EnterpriseAiMessage(conversation_id=conv.id, organization_id=ctx.org_id, role="model", content=model_msg,
                                               created_at=t + timedelta(seconds=25)))
            t += timedelta(minutes=gap_minutes)
        return conv

    attention = (
        "Three clients need your attention today, most urgent first:\n\n"
        f"- **Siddharth Menon** (New Zealand · Pathway Student Visa) — passport expires **30 Nov 2026**, before his February 2027 intake; "
        f"INZ has issued the AIP and the NZD 18,500 tuition is due by **{fmt_long(d(13))}**. Renewal appointment is booked for {fmt_long(d(9))}.\n"
        f"- **Karan Singh** (Canada · Study Permit) — IRCC biometrics deadline is in **6 days** ({fmt_long(d(6))}); VFS Chandigarh slot is on {fmt_long(d(3))}. "
        "Rahul has reminded him to carry the BIL printout.\n"
        "- **Aarav Mehta** (United States · F-1) — **2 documents need review** before the DS-160 goes in: the I-20 carries a middle name the passport does not, "
        "and the HDFC statement is in the sponsor's name with no affidavit on file. A corrected I-20 is expected from the DSO this week.\n\n"
        "**Suggested next step:** start with Siddharth — confirm the loan disbursement date with the bank today so the tuition lands before the AIP deadline."
    )
    whatsapp = (
        "Here's a short WhatsApp reminder for Siddharth:\n\n"
        f"Hi Siddharth, Kavya here from Meridian. Two quick reminders: (1) your passport renewal appointment at PSK Trivandrum is on **{fmt_long(d(9))} at 11:30** — "
        f"please carry the old passport and two photos; (2) Unitec's tuition of NZD 18,500 must reach them by **{fmt_long(d(13))}** for the AIP. "
        "Let me know once the bank confirms the disbursement. Thanks!"
    )
    conversation("Clients needing attention", at(-0, "09:12"), [
        ("Which clients need my attention today?", attention),
        ("Draft a WhatsApp reminder for Siddharth", whatsapp),
    ])
    pipeline = (
        "**August 2026 in one view:**\n\n"
        "- **New clients:** 9 added (Bengaluru 5, Hyderabad 2, Kochi 2)\n"
        "- **Moved forward:** 14 stage moves — 4 offers accepted, 3 applications submitted, 2 biometrics done\n"
        "- **Decisions:** 1 approved (Rohan Desai · Ireland), 1 refused (Farhan Sheikh · UK — Appendix Finance)\n"
        "- **Busiest destinations:** Australia (5 active), United States (4), Canada (4)\n"
        "- **Credits used:** 640 — Deep Scans and mock interviews were the largest share\n\n"
        "**Takeaway:** the August refusal was a maintenance-funds slip; every open UK case now has a 28-day statement check on its calendar."
    )
    pipeline_2 = (
        "Two cases look at risk this month:\n\n"
        "- **Divya Pillai** (Germany) — on hold for 9 days waiting on the Expatrio top-up; her Winter Semester course starts 12 Oct.\n"
        "- **Sana Mirza** (France) — file lodged, course starts in under three weeks; VFS biometrics are booked but any delay pushes her past the start date.\n\n"
        "Everything else is inside its normal processing window."
    )
    conversation("Pipeline summary for August", at(-5, "17:40"), [
        ("Give me a pipeline summary for August", pipeline),
        ("Which cases are at risk this month?", pipeline_2),
    ])
    cas = (
        "**UK Student visa — maintenance funds rule (Appendix Finance):**\n\n"
        "- **Amount:** £1,483 per month outside London (£1,529 in London) for up to 9 months, plus any first-year tuition still outstanding on the CAS.\n"
        "- **Holding period:** the money must sit in the account for **28 consecutive days**, and the closing balance date must be within **31 days** of the application.\n"
        "- **Whose account:** the student's own, or a parent's with a consent letter and birth certificate.\n\n"
        "For **Ishita Rao** that means £12,006 + £18,500 outstanding tuition — her ICICI statement closes on the 4th, so the application can go in from then."
    )
    cas_2 = (
        "**Yes — a parent's account is accepted** if three things are attached: the parent's bank statement covering the same 28 days, a signed letter "
        "confirming the relationship and consent to use the funds, and the student's birth certificate. A joint account in both names needs no consent letter."
    )
    conversation("UK CAS funds rule", at(-9, "11:05"), [
        ("Explain the UK CAS funds rule for Ishita", cas),
        ("Can the money be in her father's account?", cas_2),
    ])
    ctx.db.flush()


# ---------------------------------------------------------------------------
# Catalog "Verified" badges
# ---------------------------------------------------------------------------
def seed_catalog_verified(ctx: Ctx) -> int:
    updated = 0
    for cc in ("US", "UK", "CA", "AU", "DE", "IE"):
        rows = (
            ctx.db.query(models.CourseCatalogUniversity)
            .filter(models.CourseCatalogUniversity.country_code == cc, models.CourseCatalogUniversity.is_active.is_(True))
            .order_by(models.CourseCatalogUniversity.seed_rank.asc().nulls_last(), models.CourseCatalogUniversity.id.asc())
            .limit(8)
            .all()
        )
        for i, row in enumerate(rows):
            row.last_verified_at = UTC_NOW - timedelta(days=1 + (i * 3 + updated) % 13, hours=(i * 5) % 23)
            row.updated_at = row.last_verified_at
            updated += 1
    ctx.db.flush()
    ctx.counts["course_catalog_universities (verified)"] = updated
    return updated


# ---------------------------------------------------------------------------
# Notifications — only if the org seed left the bell empty
# ---------------------------------------------------------------------------
def seed_notifications_if_missing(ctx: Ctx) -> None:
    existing = ctx.db.query(models.EnterpriseNotification).filter(models.EnterpriseNotification.organization_id == ctx.org_id).count()
    if existing:
        return
    c = ctx.clients
    owner = ctx.uid["ananya"]
    rows = [
        ("status_changed", ctx.uid["rahul"], f"Rahul Verma moved Karan Singh to Submitted to IRCC", None, "client", c["karan"].id, False, at(-0, "08:20")),
        ("interview_completed", None, "🎤 Ishita Rao completed their mock interview", "Verdict: Likely Approved", "client", c["ishita"].id, False, at(-0, "07:55")),
        ("lead_received", None, "New lead: Ritika Menon via Website enquiries", "ritika.menon@example.com · +91 98470 22110", "lead", None, False, at(-1, "10:12")),
        ("document_flagged", None, "⚠ Rilono AI flagged Form I-20 (signed) for Aarav Mehta — name differs from passport", None, "client", c["aarav"].id, True, at(-1, "09:52")),
        ("client_added", ctx.uid["arjun"], "Arjun Menon added client Ananya Sharma", "Germany · Student Applicant Visa", "client", c["ananyas"].id, True, at(-1, "16:50")),
        ("docs_submitted", None, "📁 Ishita Rao submitted all requested documents", None, "client", c["ishita"].id, True, at(-3, "17:46")),
    ]
    for ntype, actor, title, body, ref_type, ref_id, read, created in rows:
        ctx.add(models.EnterpriseNotification(
            organization_id=ctx.org_id, recipient_user_id=owner, actor_user_id=actor, type=ntype, title=title, body=body,
            reference_type=ref_type, reference_id=ref_id, is_read=read, created_at=created,
        ))
    ctx.db.flush()


def link_org_seed_references(ctx: Ctx) -> None:
    """The org seed writes per-client credit debits and client notifications with
    reference_id NULL (no clients existed yet); point them at the roster now."""
    fn = getattr(_org_seed, "link_client_references", None) if _org_seed else None
    if fn is None:
        return
    try:
        linked = fn(ctx.db, ctx.org_id)
    except TypeError:
        linked = fn(ctx.db)
    ctx.counts["linked org-seed references"] = sum(int(v) for v in (linked or {}).values()) if isinstance(linked, dict) else 0


# ---------------------------------------------------------------------------
# Reset (purge every client-level row this script owns for the org)
# ---------------------------------------------------------------------------
def purge(db, org_id: int) -> None:
    client_ids = [r[0] for r in db.query(models.EnterpriseClient.id).filter(models.EnterpriseClient.organization_id == org_id).all()]
    org_filter = lambda m: m.organization_id == org_id  # noqa: E731
    db.query(models.EnterprisePaymentEvent).filter(org_filter(models.EnterprisePaymentEvent)).delete(synchronize_session=False)
    db.query(models.EnterpriseStudentPayment).filter(org_filter(models.EnterpriseStudentPayment)).delete(synchronize_session=False)
    db.query(models.EnterpriseFinanceEntry).filter(org_filter(models.EnterpriseFinanceEntry)).delete(synchronize_session=False)
    event_ids = [r[0] for r in db.query(models.EnterpriseCalendarEvent.id).filter(org_filter(models.EnterpriseCalendarEvent)).all()]
    if event_ids:
        db.query(models.EnterpriseCalendarEventAttachment).filter(models.EnterpriseCalendarEventAttachment.event_id.in_(event_ids)).delete(synchronize_session=False)
    db.query(models.EnterpriseCalendarEvent).filter(org_filter(models.EnterpriseCalendarEvent)).delete(synchronize_session=False)
    db.query(models.EnterpriseLeadUpload).filter(org_filter(models.EnterpriseLeadUpload)).delete(synchronize_session=False)
    db.query(models.EnterpriseLead).filter(org_filter(models.EnterpriseLead)).delete(synchronize_session=False)
    db.query(models.EnterpriseLeadForm).filter(org_filter(models.EnterpriseLeadForm)).delete(synchronize_session=False)
    db.query(models.EnterpriseAiMessage).filter(org_filter(models.EnterpriseAiMessage)).delete(synchronize_session=False)
    db.query(models.EnterpriseAiConversation).filter(org_filter(models.EnterpriseAiConversation)).delete(synchronize_session=False)
    db.query(models.EnterpriseCourseFinderRec).filter(org_filter(models.EnterpriseCourseFinderRec)).delete(synchronize_session=False)
    db.query(models.EnterpriseCopilotInvite).filter(org_filter(models.EnterpriseCopilotInvite)).delete(synchronize_session=False)
    db.query(models.EnterpriseClientPortalShare).filter(org_filter(models.EnterpriseClientPortalShare)).delete(synchronize_session=False)
    db.query(models.EnterpriseDocumentRequestItem).filter(org_filter(models.EnterpriseDocumentRequestItem)).delete(synchronize_session=False)
    db.query(models.EnterpriseDocumentRequest).filter(org_filter(models.EnterpriseDocumentRequest)).delete(synchronize_session=False)
    db.query(models.EnterpriseInterviewInvite).filter(org_filter(models.EnterpriseInterviewInvite)).delete(synchronize_session=False)
    db.query(models.EnterpriseInterviewSession).filter(org_filter(models.EnterpriseInterviewSession)).delete(synchronize_session=False)
    db.query(models.EnterpriseClientWritingDraft).filter(org_filter(models.EnterpriseClientWritingDraft)).delete(synchronize_session=False)
    db.query(models.EnterpriseClientDeepScan).filter(org_filter(models.EnterpriseClientDeepScan)).delete(synchronize_session=False)
    db.query(models.EnterpriseClientEmailAttachment).filter(org_filter(models.EnterpriseClientEmailAttachment)).delete(synchronize_session=False)
    db.query(models.EnterpriseClientEmail).filter(org_filter(models.EnterpriseClientEmail)).delete(synchronize_session=False)
    db.query(models.EnterpriseClientDocument).filter(org_filter(models.EnterpriseClientDocument)).delete(synchronize_session=False)
    db.query(models.EnterpriseClientNote).filter(org_filter(models.EnterpriseClientNote)).delete(synchronize_session=False)
    db.query(models.EnterpriseClientUniversity).filter(org_filter(models.EnterpriseClientUniversity)).delete(synchronize_session=False)
    # Rows owned by the org seed that merely POINT at clients (notifications, credit debits):
    # unlink rather than delete, so link_org_seed_references() re-attaches them after a reseed.
    for model in (models.EnterpriseNotification, models.EnterpriseCreditTransaction):
        db.query(model).filter(
            model.organization_id == org_id, model.reference_type == "client",
            model.reference_id.in_(client_ids or [-1]),
        ).update({model.reference_id: None}, synchronize_session=False)
    db.query(models.EnterpriseClient).filter(org_filter(models.EnterpriseClient)).delete(synchronize_session=False)
    db.flush()
    docs_dir = Path(os.environ["ENTERPRISE_DOCS_DIR"]) / "enterprise" / str(org_id) / "clients"
    if docs_dir.exists():
        shutil.rmtree(docs_dir)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(argv: list[str]) -> int:
    reset = "--reset" in argv
    from app.database import engine  # the engine was bound BEFORE seed_demo_org could touch os.environ
    db_url = str(engine.url)
    if "_demo_video.db" not in db_url and "--allow-any-db" not in argv:
        raise SystemExit(f"Refusing to seed DATABASE_URL={db_url!r} — expected the _demo_video.db sandbox (pass --allow-any-db to override).")
    if not enterprise_storage.is_configured() or not enterprise_storage.LOCAL_DIR:
        raise SystemExit("ENTERPRISE_DOCS_DIR must point at a local directory (e.g. ./_docs_demo).")
    print(f"Seeding client-level demo data for '{ORG_SLUG}' · today={TODAY.isoformat()} (IST) · db={db_url} · docs={enterprise_storage.LOCAL_DIR}")
    db = SessionLocal()
    try:
        org = resolve_org(db)
        existing = db.query(models.EnterpriseClient).filter(models.EnterpriseClient.organization_id == org.id).count()
        if existing and not reset:
            raise SystemExit(f"Org {org.id} already has {existing} clients — re-run with --reset to purge and reseed.")
        if reset:
            purge(db, org.id)
            print(f"  purged existing client-level rows for org {org.id}")
        ctx = Ctx(db, org)
        seed_clients(ctx)
        seed_universities(ctx)
        seed_documents(ctx)
        seed_notes(ctx)
        seed_emails(ctx)
        seed_calendar(ctx)
        seed_links(ctx)
        seed_interviews(ctx)
        seed_writing(ctx)
        seed_deep_scan(ctx)
        seed_course_finder(ctx)
        seed_leads(ctx)
        seed_finance(ctx)
        seed_ai_conversations(ctx)
        seed_catalog_verified(ctx)
        seed_notifications_if_missing(ctx)
        link_org_seed_references(ctx)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    # Summary
    db = SessionLocal()
    try:
        org = resolve_org(db)
        hero = db.query(models.EnterpriseClient).filter(models.EnterpriseClient.organization_id == org.id,
                                                        models.EnterpriseClient.full_name == "Aarav Mehta").first()
        print("\nRows created:")
        for table, n in sorted(ctx.counts.items()):
            print(f"  {table:45s} {n}")
        status_rows = (
            db.query(models.EnterpriseClient.status, sa_func.count(models.EnterpriseClient.id))
            .filter(models.EnterpriseClient.organization_id == org.id)
            .group_by(models.EnterpriseClient.status).all()
        )
        print("\nClients by stage: " + ", ".join(f"{s}={n}" for s, n in sorted(status_rows)))
        print(f"Hero client id: {hero.id if hero else '?'}  ·  website form token: {WEBSITE_FORM_TOKEN}")
        print(f"Portal: http://{ORG_SLUG}.localhost:8099/enterprise/clients/{hero.id if hero else ''}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
