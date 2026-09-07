#!/usr/bin/env python3
"""Organization-level seed for the "Meridian Overseas Education" demo workspace.

Creates (idempotently) everything ABOVE the client level for the demo video:
users, organization, offices, custom role, memberships, paid Growth subscription
(+ settled payment), credit wallet + ledger + top-up, notifications, access-audit
rows, finance settings and a payable linked account.

Run from the web_app directory:

    /Users/gaurav/.pyenv/versions/3.11.6/bin/python3 seed_demo_org.py            # full seed
    /Users/gaurav/.pyenv/versions/3.11.6/bin/python3 seed_demo_org.py --dry-run  # purge lookups only, rolled back

Safety: the script pins DATABASE_URL to the sandbox SQLite file before importing
anything under app/ (python-dotenv never overrides an existing variable) and refuses
to run against any non-sqlite / non-"_demo_video.db" database.

The client-level seed can import helpers from this module:
    get_org(session), get_member_user_id(session, email), get_branch_id(session, name),
    get_user(session, email), member_map(session), link_client_references(session)
plus the constants ROSTER_CLIENT_NAMES, EXTRA_CLIENT_NAMES, CLIENT_COUNSELLOR.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal

# ---------------------------------------------------------------------------
# Environment pinning — MUST happen before any `app.*` import.
# ---------------------------------------------------------------------------
WEB_APP_DIR = os.path.dirname(os.path.abspath(__file__))
SANDBOX_DB_URL = "sqlite:///./_demo_video.db"
_env_url = os.environ.get("DATABASE_URL", "")
if not (_env_url.startswith("sqlite") and "_demo_video.db" in _env_url):
    os.environ["DATABASE_URL"] = SANDBOX_DB_URL
os.chdir(WEB_APP_DIR)
if WEB_APP_DIR not in sys.path:
    sys.path.insert(0, WEB_APP_DIR)

from sqlalchemy import func, text  # noqa: E402

from app import models  # noqa: E402
from app import enterprise_access as access  # noqa: E402
from app import enterprise_billing as billing  # noqa: E402
from app import enterprise_credits as credits  # noqa: E402
from app import legal, money  # noqa: E402
from app.auth import get_password_hash  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402

if not (str(engine.url).startswith("sqlite") and "_demo_video.db" in str(engine.url)):
    raise SystemExit(f"Refusing to seed a non-sandbox database: {engine.url}")

# ---------------------------------------------------------------------------
# Demo identity
# ---------------------------------------------------------------------------
NOW = datetime.utcnow().replace(microsecond=0)
# Org "today" is the IST date (the org's offices are all Asia/Kolkata, which is what the
# server's org_today() resolves); DEMO_TODAY=YYYY-MM-DD pins it, in step with the client seed.
TODAY = (date.fromisoformat(os.environ["DEMO_TODAY"]) if os.environ.get("DEMO_TODAY")
         else (NOW + timedelta(hours=5, minutes=30)).date())

ORG_SLUG = "meridian"
ORG_NAME = "Meridian Overseas Education"
ORG_LOGO_URL = "/api/enterprise/public/brand-mark/globe-00-1.png"
ORG_CREATED_AT = datetime(2026, 3, 14, 9, 30)
DEMO_PASSWORD = "Meridian@Demo2026!"
DEMO_IP = "103.21.58.10"
DEMO_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 Chrome/128.0 Safari/537.36"

# Billing period (Growth): 2026-08-20 -> 2026-09-19. If the seed is ever re-run within a
# day of the period end the whole period slides forward so the plan never reads as expired.
PERIOD_END = datetime(2026, 9, 19, 0, 0)
if NOW >= PERIOD_END - timedelta(days=1):
    PERIOD_END = (NOW + timedelta(days=12)).replace(hour=0, minute=0, second=0)
PERIOD_START = PERIOD_END - timedelta(days=billing.PLAN_PERIOD_DAYS)
TOPUP_AT = PERIOD_START - timedelta(days=3, hours=-9, minutes=-40)   # 3 days before renewal, 09:40 UTC
SANDBOX_GRANT_AT = datetime(2026, 8, 2, 10, 15)

RZP_SUBSCRIPTION_ID = "sub_MERIDIAN0GROWTH01"

BRANCHES = [
    # name, code, city, state, address, phone, email, created_at, is_default
    ("Bengaluru — Koramangala", "BLR-HQ", "Bengaluru", "Karnataka",
     "3rd Floor, 80 Feet Road, Koramangala 4th Block", "+91 80 4110 2345",
     "bengaluru@example.com", ORG_CREATED_AT, True),
    ("Hyderabad — Banjara Hills", "HYD-01", "Hyderabad", "Telangana",
     "Road No. 12, Banjara Hills", "+91 40 2335 6789",
     "hyderabad@example.com", datetime(2026, 4, 8, 6, 5), False),
    ("Kochi — MG Road", "COK-01", "Kochi", "Kerala",
     "2nd Floor, Oberon Mall Road, MG Road", "+91 484 235 4321",
     "kochi@example.com", datetime(2026, 5, 19, 5, 40), False),
]
HQ, HYD, KOCHI = (b[0] for b in BRANCHES)

CUSTOM_ROLE_NAME = "Document Reviewer"

# email, full name, role_key, data_scope, branch, job title, phone, joined_at, last_active delta, heard_about_us
DEMO_USERS = [
    ("ananya.rao@example.com", "Ananya Rao", "owner", "all", HQ, "Founder & Director",
     "+91 98450 12345", ORG_CREATED_AT, timedelta(minutes=6), "linkedin"),
    ("rahul.verma@example.com", "Rahul Verma", "admin", "all", HQ, "Operations Head",
     "+91 98860 23456", datetime(2026, 3, 16, 8, 10), timedelta(minutes=25), "friend"),
    ("priya.nair@example.com", "Priya Nair", "branch_manager", "branch", HYD, "Branch Manager",
     "+91 98490 34567", datetime(2026, 4, 10, 7, 20), timedelta(hours=1, minutes=50), "consultant"),
    ("arjun.menon@example.com", "Arjun Menon", "counsellor", "assigned", HQ, "Senior Counsellor",
     "+91 98440 45678", datetime(2026, 3, 20, 9, 5), timedelta(minutes=14), "friend"),
    ("kavya.krishnan@example.com", "Kavya Krishnan", "counsellor", "assigned", KOCHI, "Counsellor",
     "+91 98470 56789", datetime(2026, 5, 21, 6, 45), timedelta(hours=3, minutes=5), "instagram"),
    ("sanjay.patel@example.com", "Sanjay Patel", "finance", "all", HQ, "Accounts Manager",
     "+91 98800 67890", datetime(2026, 4, 2, 8, 30), timedelta(days=1, hours=2), "friend"),
    ("neha.gupta@example.com", "Neha Gupta", "viewer", "assigned", HQ, "Quality Reviewer",
     "+91 98450 78901", datetime(2026, 6, 15, 7, 0), timedelta(days=2, hours=5), "linkedin"),
    # Explicit "all" (not NULL/inherit): the Team table derives the scope chip from the
    # member row + preset and would otherwise show the custom preset's "assigned".
    ("deepak.iyer@example.com", "Deepak Iyer", "custom", "all", HYD, "Document Specialist",
     "+91 98480 89012", NOW - timedelta(days=6, hours=4), timedelta(hours=4), "friend"),
]
DEMO_EMAILS = [u[0] for u in DEMO_USERS]
OWNER_EMAIL = DEMO_EMAILS[0]
# Viewer Neha gets one explicit grant on top of her role ("+1" override pill in Team).
MEMBER_CAPABILITY_GRANTS = {"neha.gupta@example.com": ["documents.download"]}

# 14 named roster clients (client-level report §c) + counsellor who owns each case.
CLIENT_COUNSELLOR = {
    "Aarav Mehta": "arjun.menon@example.com",
    "Ishita Rao": "arjun.menon@example.com",
    "Karan Singh": "rahul.verma@example.com",
    "Meera Nair": "kavya.krishnan@example.com",
    "Divya Pillai": "arjun.menon@example.com",
    "Rohan Desai": "rahul.verma@example.com",
    "Sneha Iyer": "kavya.krishnan@example.com",
    "Aditya Kulkarni": "priya.nair@example.com",
    "Priyanka Reddy": "priya.nair@example.com",
    "Farhan Sheikh": "arjun.menon@example.com",
    "Neha Kapoor": "rahul.verma@example.com",
    "Vikram Joshi": "arjun.menon@example.com",
    "Ananya Sharma": "arjun.menon@example.com",
    "Siddharth Menon": "kavya.krishnan@example.com",
}
ROSTER_CLIENT_NAMES = list(CLIENT_COUNSELLOR)
# Earliest date an AI action may be recorded for a roster client (its creation date).
_CLIENT_NOT_BEFORE = {
    "Sneha Iyer": datetime(2026, 8, 13), "Aditya Kulkarni": datetime(2026, 7, 23),
    "Priyanka Reddy": datetime(2026, 9, 3, 6), "Ananya Sharma": datetime(2026, 9, 5, 8),
    "Karan Singh": datetime(2026, 6, 18), "Vikram Joshi": datetime(2026, 7, 10),
}
# Closed cases: no AI spend after these dates.
_CLIENT_NOT_AFTER = {
    "Rohan Desai": datetime(2026, 8, 12), "Neha Kapoor": datetime(2026, 7, 20),
    "Farhan Sheikh": datetime(2026, 8, 10),
}
# 24 lighter clients the client-level seed is expected to create, so the ledger and
# notifications can name them (and link to them once they exist).
EXTRA_CLIENT_NAMES = [
    ("Tanvi Agarwal", "FR"), ("Nikhil Bhat", "NL"), ("Riya Chatterjee", "IT"),
    ("Harsh Vardhan", "PL"), ("Pooja Hegde", "ES"), ("Zara Khan", "AE"),
    ("Manish Tiwari", "SE"), ("Aisha Siddiqui", "UK"), ("Dev Malhotra", "US"),
    ("Shruti Deshpande", "CA"), ("Kabir Chopra", "AU"), ("Lakshmi Venkatesh", "DE"),
    ("Omar Farooq", "IE"), ("Nandini Krishnamurthy", "SG"), ("Yash Thakur", "US"),
    ("Sana Mirza", "FR"), ("Abhishek Rao", "NL"), ("Tara Bhandari", "NZ"),
    ("Varun Nambiar", "CA"), ("Ritika Sen", "UK"), ("Pranav Saxena", "US"),
    ("Mehul Shah", "AE"), ("Anjali Menon", "AU"), ("Rehan Qureshi", "IT"),
]
_EXTRA_COUNSELLORS = ["arjun.menon@example.com", "kavya.krishnan@example.com",
                      "priya.nair@example.com", "rahul.verma@example.com"]
for _i, (_name, _cc) in enumerate(EXTRA_CLIENT_NAMES):
    CLIENT_COUNSELLOR.setdefault(_name, _EXTRA_COUNSELLORS[_i % len(_EXTRA_COUNSELLORS)])

DOC_TYPES = ["Passport", "Bank statement", "Degree certificate", "Academic transcripts",
             "IELTS score report", "Statement of Purpose", "Offer letter", "Financial affidavit",
             "Resume / CV", "Sponsor letter", "Birth certificate", "Passport-size photo"]

FINANCE_SAVINGS_OVERRIDES = {
    "deep_scan": 60, "mock_interview": 40, "writing_studio": 90, "course_finder": 35,
    "university_match": 30, "document_collected": 8, "client_email": 4, "portal_share": 20,
    "reminder_sent": 5, "copilot_message": 4, "payment_collected": 10,
}


# ---------------------------------------------------------------------------
# Lookup helpers (importable by the client-level seed)
# ---------------------------------------------------------------------------
def get_org(session):
    return (
        session.query(models.EnterpriseOrganization)
        .filter(models.EnterpriseOrganization.subdomain_slug == ORG_SLUG)
        .first()
    )


def get_user(session, email: str):
    return session.query(models.User).filter(models.User.email == email.strip().lower()).first()


def get_member_user_id(session, email: str) -> int:
    org = get_org(session)
    if org is None:
        raise LookupError("Meridian org is not seeded yet — run seed_demo_org.py first")
    row = (
        session.query(models.EnterpriseOrganizationMember.user_id)
        .join(models.User, models.User.id == models.EnterpriseOrganizationMember.user_id)
        .filter(
            models.EnterpriseOrganizationMember.organization_id == org.id,
            models.User.email == email.strip().lower(),
        )
        .first()
    )
    if row is None:
        raise LookupError(f"No Meridian member with email {email}")
    return int(row[0])


def get_branch_id(session, name: str) -> int:
    org = get_org(session)
    if org is None:
        raise LookupError("Meridian org is not seeded yet — run seed_demo_org.py first")
    needle = name.strip().lower()
    rows = (
        session.query(models.EnterpriseBranch)
        .filter(models.EnterpriseBranch.organization_id == org.id)
        .all()
    )
    for b in rows:
        if b.name.strip().lower() == needle:
            return int(b.id)
    # Forgiving match: "Kochi" -> "Kochi — MG Road".
    for b in rows:
        if needle and (needle in b.name.lower() or (b.city or "").lower() == needle):
            return int(b.id)
    raise LookupError(f"No Meridian branch named {name!r}")


def member_map(session) -> dict:
    """{email: user_id} for every Meridian member."""
    org = get_org(session)
    if org is None:
        return {}
    rows = (
        session.query(models.User.email, models.EnterpriseOrganizationMember.user_id)
        .join(models.EnterpriseOrganizationMember,
              models.EnterpriseOrganizationMember.user_id == models.User.id)
        .filter(models.EnterpriseOrganizationMember.organization_id == org.id)
        .all()
    )
    return {email: int(uid) for email, uid in rows}


def _client_name_from_description(desc: str | None) -> str | None:
    """'Deep Scan — Aarav Mehta' / 'Document scan — Passport · Aarav Mehta' -> 'Aarav Mehta'."""
    if not desc:
        return None
    text_ = str(desc)
    if " · " in text_:
        return text_.rsplit(" · ", 1)[1].strip() or None
    if " — " in text_:
        return text_.rsplit(" — ", 1)[1].strip() or None
    return None


def link_client_references(session, org_id: int | None = None) -> dict:
    """Point ledger rows and notifications at the enterprise_clients rows they name.

    The org seed runs before any client exists, so per-client debits and client
    notifications are written with reference_type='client' and reference_id NULL. Call this
    after the client-level seed has created the roster; rows whose client name is not found
    are left untouched. Does not commit.
    """
    if org_id is None:
        org = get_org(session)
        if org is None:
            return {"ledger": 0, "notifications": 0}
        org_id = org.id
    names = {
        (n or "").strip().lower(): cid
        for cid, n in session.query(models.EnterpriseClient.id, models.EnterpriseClient.full_name)
        .filter(models.EnterpriseClient.organization_id == org_id).all()
    }
    linked_ledger = 0
    T = models.EnterpriseCreditTransaction
    for txn in session.query(T).filter(T.organization_id == org_id, T.reference_type == "client",
                                       T.reference_id.is_(None)).all():
        cid = names.get((_client_name_from_description(txn.description) or "").lower())
        if cid:
            txn.reference_id = cid
            linked_ledger += 1
    linked_notif = 0
    N = models.EnterpriseNotification
    for n in session.query(N).filter(N.organization_id == org_id, N.reference_type == "client",
                                     N.reference_id.is_(None)).all():
        hay = f"{n.title or ''} {n.body or ''}".lower()
        for name, cid in names.items():
            if name and name in hay:
                n.reference_id = cid
                linked_notif += 1
                break
    session.flush()
    return {"ledger": linked_ledger, "notifications": linked_notif}


# ---------------------------------------------------------------------------
# Purge (idempotency)
# ---------------------------------------------------------------------------
def purge_org(session, org_id: int) -> dict:
    """Delete the org and every row that carries its organization_id, children first."""
    counts = {}
    for t in reversed(Base.metadata.sorted_tables):
        if t.name == "enterprise_organizations" or "organization_id" not in t.c:
            continue
        res = session.execute(t.delete().where(t.c.organization_id == org_id))
        if res.rowcount:
            counts[t.name] = res.rowcount
    res = session.execute(
        models.EnterpriseOrganization.__table__.delete()
        .where(models.EnterpriseOrganization.__table__.c.id == org_id)
    )
    if res.rowcount:
        counts["enterprise_organizations"] = res.rowcount
    return counts


def purge_users(session, emails: list[str]) -> dict:
    """Delete the demo users and everything that references them (FK-safe order)."""
    users_t = models.User.__table__
    ids = [int(r[0]) for r in session.execute(
        users_t.select().with_only_columns(users_t.c.id).where(users_t.c.email.in_(emails))
    )]
    counts = {}
    if not ids:
        return counts
    for t in reversed(Base.metadata.sorted_tables):
        if t.name == "users":
            continue
        for col in t.c:
            if not any(fk.column.table.name == "users" for fk in col.foreign_keys):
                continue
            if t.name == "enterprise_organizations":
                stray = session.execute(
                    t.select().with_only_columns(func.count()).where(col.in_(ids))
                ).scalar()
                if stray:
                    raise RuntimeError(
                        f"{stray} organization(s) other than meridian reference demo users via "
                        f"{t.name}.{col.name}; refusing to purge"
                    )
                continue
            if col.nullable:
                res = session.execute(t.update().where(col.in_(ids)).values({col.name: None}))
                if res.rowcount:
                    counts[f"{t.name}.{col.name} (nulled)"] = res.rowcount
            else:
                res = session.execute(t.delete().where(col.in_(ids)))
                if res.rowcount:
                    counts[f"{t.name}.{col.name}"] = res.rowcount
    session.execute(users_t.update().where(users_t.c.referred_by_user_id.in_(ids))
                    .values(referred_by_user_id=None))
    res = session.execute(users_t.delete().where(users_t.c.id.in_(ids)))
    counts["users"] = res.rowcount
    return counts


def purge_demo(session) -> dict:
    counts = {}
    org = get_org(session)
    if org is not None:
        counts.update(purge_org(session, org.id))
    counts.update(purge_users(session, DEMO_EMAILS))
    session.flush()
    return counts


# ---------------------------------------------------------------------------
# Seed steps
# ---------------------------------------------------------------------------
def create_users(session) -> dict:
    pwd_hash = get_password_hash(DEMO_PASSWORD)
    users = {}
    for email, name, _rk, _scope, _branch, _title, phone, joined_at, active_delta, heard in DEMO_USERS:
        u = models.User(
            email=email, username=None, hashed_password=pwd_hash, full_name=name,
            university=ORG_NAME, phone=phone, is_active=True, email_verified=True,
            is_admin=False, is_developer=False, is_enterprise_account=True,
            auth_provider="password", session_invalidated_at=None,
            accepted_terms_privacy_at=joined_at, accepted_terms_privacy_ip=DEMO_IP,
            accepted_terms_privacy_user_agent=DEMO_UA,
            accepted_terms_privacy_version=legal.LEGAL_TERMS_PRIVACY_VERSION,
            age_confirmed_at=joined_at, email_notifications_enabled=True,
            marketing_emails_consent=False, heard_about_us=heard,
            heard_about_us_at=joined_at + timedelta(minutes=3),
            first_login_at=joined_at + timedelta(minutes=2),
            last_login_at=NOW - active_delta, created_at=joined_at,
        )
        session.add(u)
        users[email] = u
    session.flush()
    return users


def create_org(session, users: dict):
    owner = users[OWNER_EMAIL]
    org = models.EnterpriseOrganization(
        company_name=ORG_NAME, subdomain_slug=ORG_SLUG, logo_url=ORG_LOGO_URL,
        country_code="IN", state_region="Karnataka", billing_currency="INR",
        created_by_user_id=owner.id,
        dpa_accepted_at=datetime(2026, 7, 27, 4, 45), dpa_accepted_version=legal.LEGAL_DPA_VERSION,
        dpa_accepted_by_user_id=owner.id, created_at=ORG_CREATED_AT,
    )
    session.add(org)
    session.flush()
    return org


def create_branches(session, org, users: dict) -> dict:
    owner = users[OWNER_EMAIL]
    branches = {}
    for name, code, city, state, address, phone, email, created_at, is_default in BRANCHES:
        b = models.EnterpriseBranch(
            organization_id=org.id, name=name, code=code, city=city, state_region=state,
            country_code="IN", address_line=address, phone=phone, email=email,
            timezone="Asia/Kolkata", is_default=is_default, is_active=True,
            created_by_user_id=owner.id, created_at=created_at,
        )
        session.add(b)
        branches[name] = b
    session.flush()
    return branches


def custom_role_capabilities() -> list[str]:
    base = set(access.ROLE_PRESETS["viewer"]["capabilities"])
    base |= {"documents.download", "documents.upload", "documents.accept", "documents.request",
             "notes.write", "calendar.view", "credits.spend"}
    return sorted(access.expand_implied(base))


def create_custom_role(session, org, users: dict):
    caps = custom_role_capabilities()
    role = models.EnterpriseRole(
        organization_id=org.id, name=CUSTOM_ROLE_NAME,
        slug=access.slugify_role_name(CUSTOM_ROLE_NAME),
        description=("Reviews and validates uploaded documents across every office. "
                     "Can open client files but cannot edit cases or spend on AI beyond scans."),
        capabilities_json=json.dumps(caps), data_scope="all", based_on_role_key="viewer",
        is_active=True, created_by_user_id=users[OWNER_EMAIL].id,
        created_at=NOW - timedelta(days=6, hours=5),
    )
    session.add(role)
    session.flush()
    return role, caps


def create_members(session, org, users: dict, branches: dict, custom_role, custom_caps) -> dict:
    owner = users[OWNER_EMAIL]
    members = {}
    for email, _name, role_key, scope, branch_name, title, phone, joined_at, active_delta, _h in DEMO_USERS:
        u = users[email]
        if role_key == "custom":
            caps = set(custom_caps)
        else:
            caps = set(access.ROLE_PRESETS[role_key]["capabilities"])
        grants = MEMBER_CAPABILITY_GRANTS.get(email)
        m = models.EnterpriseOrganizationMember(
            organization_id=org.id, user_id=u.id,
            role=access.legacy_role_for(role_key, caps), is_active=True,
            invited_by_user_id=(None if role_key == "owner" else owner.id),
            role_key=role_key, custom_role_id=(custom_role.id if role_key == "custom" else None),
            data_scope=scope,
            capability_grants_json=(json.dumps(grants) if grants else None),
            capability_denies_json=None,
            primary_branch_id=branches[branch_name].id, job_title=title, phone=phone,
            status="active", invited_at=joined_at,
            invite_accepted_at=joined_at + timedelta(minutes=2),
            last_active_at=NOW - active_delta, created_at=joined_at,
        )
        session.add(m)
        members[email] = m
    session.flush()
    for email, m in members.items():
        session.add(models.EnterpriseMemberBranch(
            organization_id=org.id, member_id=m.id, branch_id=m.primary_branch_id,
            created_at=m.created_at,
        ))
    session.flush()
    return members


def create_subscription(session, org, users: dict):
    sub = models.EnterpriseSubscription(
        organization_id=org.id, plan="growth", status="active", trial_ends_at=None,
        current_period_end=PERIOD_END, razorpay_subscription_id=RZP_SUBSCRIPTION_ID,
        cancel_at_period_end=False, canceled_at=None, mandate_status="active",
        created_at=SANDBOX_GRANT_AT - timedelta(minutes=1),
    )
    session.add(sub)
    quote = billing.checkout_quote("growth", "INR")
    paid_at = PERIOD_START + timedelta(hours=3, minutes=55)
    payment = models.EnterpriseSubscriptionPayment(
        organization_id=org.id, created_by_user_id=users[OWNER_EMAIL].id, provider="razorpay",
        plan="growth", billing_cycle="monthly",
        amount_paise=int(quote["total_minor"]), subtotal_paise=int(quote["subtotal_minor"]),
        tax_paise=int(quote["tax_minor"]), tax_percent=Decimal(str(quote["tax_percent"])),
        tax_label=quote["tax_label"], currency="INR",
        base_amount_paise=int(quote["total_minor"]), base_currency="INR", fx_rate_used=None,
        is_international=False, price_book_version=money.PRICE_BOOK_VERSION,
        included_credits=int(billing.included_credits_for("growth")),
        razorpay_order_id=f"order_MERIDIANgrowth{PERIOD_START:%m%d}",
        razorpay_payment_id=f"pay_MERIDIANgrowth{PERIOD_START:%m%d}",
        razorpay_subscription_id=RZP_SUBSCRIPTION_ID, status="verified",
        original_amount_paise=int(quote["list_minor"]), refunded_amount_paise=0,
        verified_at=paid_at, created_at=paid_at - timedelta(minutes=2),
    )
    session.add(payment)
    session.flush()
    # Guard rails: the app must see an active, unexpired, non-grandfathered Growth plan.
    assert billing.effective_plan_key(sub) == "growth", "Growth plan not effective"
    assert not billing.paid_period_expired(sub), "paid period reads as expired"
    assert not billing.is_grandfathered(sub, org.created_at), "org reads as grandfathered"
    return sub, payment


def _txn(org, when, ttype, credits_delta, *, action_key=None, description=None,
         reference_type=None, reference_id=None, user=None):
    return dict(
        organization_id=org.id, type=ttype, action_key=action_key, credits=int(credits_delta),
        description=description, reference_type=reference_type, reference_id=reference_id,
        created_by_user_id=(user.id if user is not None else None),
        created_by_name=(user.full_name if user is not None else None), created_at=when,
    )


def _business_time(rng: random.Random, day: datetime) -> datetime:
    """A business-hours time (09:00-19:00) on `day`, as IST WALL-CLOCK stored naive.

    The credits ledger prints created_at through the SPA's fmtDateTime(), which parses the
    API's offset-less ISO string in the browser zone (Asia/Kolkata for the demo) — so a UTC
    value would show 5h30 early ("4:05 am"). Storing the wall-clock keeps the ledger readable."""
    minutes = rng.randint(0, 600)
    return day.replace(hour=9, minute=0, second=0) + timedelta(minutes=minutes, seconds=rng.randint(0, 59))


def _client_debit_description(action_key: str, client: str, rng: random.Random) -> str:
    if action_key == "deep_scan":
        return f"Deep Scan — {client}"
    if action_key == "mock_interview":
        return f"Mock interview (self-serve) — {client}"
    if action_key == "document_scan":
        return f"Document scan — {rng.choice(DOC_TYPES)} · {client}"
    if action_key == "course_finder":
        return f"Course Finder shortlist — {client}"
    if action_key == "university_match":
        return f"AI university shortlist — {client}"
    if action_key == "writing_studio":
        return f"{rng.choice(['SOP draft', 'LOR draft', 'SOP revision'])} — {client}"
    if action_key == "copilot_client":
        return f"Client copilot access — {client}"
    return f"{credits.ACTIONS[action_key]['label']} — {client}"


def create_wallet_and_ledger(session, org, sub, users: dict) -> tuple:
    rng = random.Random(20260907)
    owner = users[OWNER_EMAIL]
    sanjay = users["sanjay.patel@example.com"]
    deepak = users["deepak.iyer@example.com"]
    cost = credits.action_cost

    # --- Top-up payment (Pro Pack, 3 days before the Growth renewal) ---------------------
    pack = credits.PACKAGES["pro"]
    topup = models.EnterpriseCreditPayment(
        organization_id=org.id, created_by_user_id=sanjay.id, provider="razorpay", kind="credits",
        package_key="pro", credits=int(pack["credits"]), bonus_credits=int(pack["bonus_credits"]),
        amount_paise=int(pack["amount_paise"]), currency="INR",
        base_amount_paise=int(pack["amount_paise"]), base_currency="INR", fx_rate_used=None,
        is_international=False, price_book_version=money.PRICE_BOOK_VERSION,
        razorpay_order_id=f"order_MERIDIANtopup{TOPUP_AT:%m%d}",
        razorpay_payment_id=f"pay_MERIDIANtopup{TOPUP_AT:%m%d}", status="verified",
        refunded_amount_paise=0, verified_at=TOPUP_AT, created_at=TOPUP_AT - timedelta(minutes=2),
    )
    session.add(topup)
    session.flush()
    topup_total = int(pack["credits"]) + int(pack["bonus_credits"])   # 350

    rows: list[dict] = []

    def client_user(client: str):
        return users[CLIENT_COUNSELLOR[client]]

    # 1) Sandbox demo grant at the plan cutover (the org predates paid plans) ...........
    rows.append(_txn(org, SANDBOX_GRANT_AT, "bonus", 100,
                     description="Self-serve sandbox — 100 demo credits", reference_type="plan_credits"))
    # ... and the 100 credits spent between 3 Aug and 14 Aug.
    pre_spend = [
        ("deep_scan", "Rohan Desai", datetime(2026, 8, 4, 5, 12)),
        ("mock_interview", "Meera Nair", datetime(2026, 8, 5, 9, 48)),
        ("deep_scan", "Meera Nair", datetime(2026, 8, 7, 6, 30)),
        ("copilot_client", "Aarav Mehta", datetime(2026, 8, 10, 4, 55)),
        ("course_finder", "Vikram Joshi", datetime(2026, 8, 11, 7, 20)),
        ("document_scan", "Aarav Mehta", datetime(2026, 8, 12, 5, 5)),
        ("document_scan", "Aarav Mehta", datetime(2026, 8, 12, 5, 9)),
        ("document_scan", "Karan Singh", datetime(2026, 8, 12, 8, 41)),
        ("document_scan", "Ishita Rao", datetime(2026, 8, 13, 6, 2)),
        ("writing_studio", "Aarav Mehta", datetime(2026, 8, 13, 10, 15)),
        ("ai_copilot", None, datetime(2026, 8, 13, 11, 40)),
        ("course_finder", "Sneha Iyer", datetime(2026, 8, 14, 4, 30)),
        ("writing_studio", "Aarav Mehta", datetime(2026, 8, 14, 6, 22)),
        ("writing_studio", "Aarav Mehta", datetime(2026, 8, 14, 6, 58)),
        ("document_scan", "Divya Pillai", datetime(2026, 8, 14, 9, 12)),
        ("ai_copilot", None, datetime(2026, 8, 14, 12, 5)),
    ]
    assert sum(cost(a) for a, _c, _w in pre_spend) == 100
    for action_key, client, when in pre_spend:
        when = when + timedelta(hours=5, minutes=30)   # fixed UTC-ish stamps -> IST wall-clock (see _business_time)
        if client is None:
            rows.append(_txn(org, when, "debit", -cost(action_key), action_key=action_key,
                             description="Rilono AI assistant — 5 messages", user=owner))
        else:
            rows.append(_txn(org, when, "debit", -cost(action_key), action_key=action_key,
                             description=_client_debit_description(action_key, client, rng),
                             reference_type="client", user=client_user(client)))

    # 2) Pro Pack top-up, then the pre-renewal interview week burns through it ..........
    rows.append(_txn(org, TOPUP_AT, "topup", topup_total,
                     description=f"{pack['label']} (+{topup_total} credits)",
                     reference_type="payment", reference_id=topup.id, user=sanjay))
    week_clients = ["Aarav Mehta", "Ishita Rao", "Karan Singh", "Meera Nair", "Divya Pillai",
                    "Aditya Kulkarni", "Vikram Joshi", "Siddharth Menon", "Kabir Chopra",
                    "Aisha Siddiqui", "Dev Malhotra", "Shruti Deshpande", "Lakshmi Venkatesh"]
    d0 = TOPUP_AT.replace(hour=0, minute=0, second=0)
    week_plan = [  # (day offset, action, client)
        (0, "mock_interview", "Aarav Mehta"), (0, "mock_interview", "Ishita Rao"),
        (0, "mock_interview", "Karan Singh"), (0, "mock_interview", "Aisha Siddiqui"),
        (0, "deep_scan", "Karan Singh"), (0, "deep_scan", "Dev Malhotra"),
        (1, "mock_interview", "Meera Nair"), (1, "mock_interview", "Divya Pillai"),
        (1, "mock_interview", "Kabir Chopra"), (1, "mock_interview", "Shruti Deshpande"),
        (1, "deep_scan", "Ishita Rao"), (1, "deep_scan", "Lakshmi Venkatesh"),
        (1, "copilot_client", "Karan Singh"),
        (2, "mock_interview", "Aditya Kulkarni"), (2, "mock_interview", "Vikram Joshi"),
        (2, "mock_interview", "Siddharth Menon"), (2, "copilot_client", "Ishita Rao"),
        (2, "course_finder", "Aditya Kulkarni"), (2, "course_finder", "Kabir Chopra"),
    ]
    assert sum(cost(a) for _d, a, _c in week_plan) == topup_total
    assert all(c in week_clients for _d, _a, c in week_plan)
    for day_off, action_key, client in week_plan:
        when = _business_time(rng, d0 + timedelta(days=day_off))
        if day_off == 0 and when <= TOPUP_AT:
            when = TOPUP_AT + timedelta(minutes=rng.randint(15, 240))
        rows.append(_txn(org, when, "debit", -cost(action_key), action_key=action_key,
                         description=_client_debit_description(action_key, client, rng),
                         reference_type="client", user=client_user(client)))

    # 3) Growth grant on the renewal morning ...........................................
    grant_at = PERIOD_START + timedelta(hours=9, minutes=42)   # renewal morning, IST wall-clock
    allowance = int(billing.included_credits_for("growth"))
    rows.append(_txn(org, grant_at, "bonus", allowance,
                     description=f"Growth plan — {allowance:,} credits included this month",
                     reference_type="plan_credits"))

    # 4) This period's spend: exactly 1,160 credits across ~124 actions .................
    mix = [("deep_scan", 32), ("mock_interview", 16), ("copilot_client", 4), ("course_finder", 10),
           ("university_match", 2), ("document_scan", 30), ("writing_studio", 20), ("ai_copilot", 10)]
    period_used = sum(cost(a) * n for a, n in mix)
    assert period_used == 1160, period_used
    open_roster = [n for n in ROSTER_CLIENT_NAMES if n not in _CLIENT_NOT_AFTER]
    hero_weighted = open_roster + ["Aarav Mehta"] * 3 + ["Ishita Rao"] * 2 + ["Karan Singh"] * 2
    pool = hero_weighted + [n for n, _cc in EXTRA_CLIENT_NAMES]
    day_span = max(1, (NOW - grant_at).days)
    latest = NOW - timedelta(minutes=12)

    def pick_time() -> datetime:
        for _ in range(40):
            day = (grant_at + timedelta(days=rng.randint(0, day_span))).replace(hour=0, minute=0, second=0)
            if day.weekday() == 6 and rng.random() < 0.8:      # quiet Sundays
                continue
            when = _business_time(rng, day)
            if grant_at + timedelta(minutes=20) <= when <= latest:
                return when
        return latest - timedelta(minutes=rng.randint(30, 600))

    def pick_client(when: datetime) -> str:
        for _ in range(60):
            c = rng.choice(pool)
            if when < _CLIENT_NOT_BEFORE.get(c, datetime(2026, 1, 1)):
                continue
            if when > _CLIENT_NOT_AFTER.get(c, datetime(2099, 1, 1)):
                continue
            return c
        return "Aarav Mehta"

    deepak_scan_quota = 9   # guaranteed scans inside Deepak's tenure so he shows in "by member"
    for action_key, count in mix:
        for idx in range(count):
            when = pick_time()
            if action_key == "document_scan" and idx < deepak_scan_quota:
                lo = deepak.created_at + timedelta(hours=1)
                span_min = max(60, int((latest - lo).total_seconds() // 60) - 30)
                when = lo + timedelta(minutes=rng.randint(30, span_min))
                if when.weekday() == 6:
                    when -= timedelta(days=1)
                when = when.replace(hour=rng.randint(9, 18), minute=rng.randint(0, 59), second=rng.randint(0, 59))
                when = max(lo, min(when, latest - timedelta(minutes=5)))
            if action_key == "ai_copilot":
                who = rng.choice([owner, users["rahul.verma@example.com"], users["arjun.menon@example.com"],
                                  users["priya.nair@example.com"], users["kavya.krishnan@example.com"]])
                rows.append(_txn(org, when, "debit", -cost(action_key), action_key=action_key,
                                 description="Rilono AI assistant — 5 messages", user=who))
                continue
            client = pick_client(when)
            if action_key == "document_scan":
                # Deepak (Document Specialist) took over most scans once he joined.
                if when >= deepak.created_at and rng.random() < 0.7:
                    who = deepak
                else:
                    who = client_user(client)
            elif action_key == "deep_scan" and rng.random() < 0.1:
                who = owner
            else:
                who = client_user(client)
            rows.append(_txn(org, when, "debit", -cost(action_key), action_key=action_key,
                             description=_client_debit_description(action_key, client, rng),
                             reference_type="client", user=who))

    # Make sure the ledger visibly ends "minutes ago" with a hero-client action.
    rows.append(_txn(org, latest, "debit", -cost("document_scan"), action_key="document_scan",
                     description="Document scan — Bank statement · Aarav Mehta",
                     reference_type="client", user=users["arjun.menon@example.com"]))
    # Balance the extra row by dropping one earlier document scan of the same cost.
    for i in range(len(rows) - 2, -1, -1):
        r = rows[i]
        if r["action_key"] == "document_scan" and r["created_at"] > grant_at and "Aarav" not in (r["description"] or ""):
            del rows[i]
            break

    # 5) Chain balances in time order ..................................................
    rows.sort(key=lambda r: r["created_at"])
    balance = 0
    lifetime_spent = 0
    lifetime_purchased = 0
    for r in rows:
        balance += r["credits"]
        assert balance >= 0, f"ledger went negative at {r}"
        r["balance_after"] = balance
        if r["credits"] < 0:
            lifetime_spent += -r["credits"]
        if r["type"] == "topup":
            lifetime_purchased += r["credits"]
    period_debits = sum(-r["credits"] for r in rows if r["credits"] < 0 and r["created_at"] > grant_at)
    assert balance == 2340, balance
    assert period_debits == 1160, period_debits

    for r in rows:
        session.add(models.EnterpriseCreditTransaction(**r))

    period_key = credits.plan_credits_period_key(sub, "growth")
    assert period_key == f"growth:{PERIOD_START:%Y-%m-%d}", period_key
    wallet = models.EnterpriseCreditWallet(
        organization_id=org.id, balance_credits=balance,
        lifetime_purchased_credits=lifetime_purchased, lifetime_spent_credits=lifetime_spent,
        plan_credits_period=period_key, plan_credits_granted=allowance,
        plan_credits_remaining=allowance - period_debits, plan_credits_once_at=SANDBOX_GRANT_AT,
        infra_fee_paid_until=None, copilot_usage_date=TODAY.isoformat(), copilot_msgs_today=2,
        copilot_unbilled_msgs=1, interview_staff_previews_used=3,
        deep_scan_free_month=TODAY.strftime("%Y-%m"), deep_scan_free_used=4,
        created_at=SANDBOX_GRANT_AT - timedelta(minutes=1),
    )
    session.add(wallet)
    session.flush()
    return wallet, topup, len(rows)


def create_notifications(session, org, users: dict) -> int:
    owner = users[OWNER_EMAIL]
    arjun = users["arjun.menon@example.com"]
    rahul = users["rahul.verma@example.com"]
    kavya = users["kavya.krishnan@example.com"]
    priya = users["priya.nair@example.com"]
    # (recipient, type, title, body, actor, reference_type, is_read, age)
    spec = [
        (owner, "lead_received", "New lead: Tanvi Agarwal via Website enquiries",
         "tanvi.agarwal@example.com", None, "lead", False, timedelta(minutes=35)),
        (owner, "interview_completed", "🎤 Ishita Rao completed their mock interview",
         "Verdict: likely approved", None, "client", False, timedelta(hours=2, minutes=10)),
        (owner, "docs_submitted", "📁 Aarav Mehta submitted all requested documents",
         None, None, "client", False, timedelta(hours=4, minutes=5)),
        (owner, "status_changed", "Rahul Verma moved Karan Singh to Application Submitted",
         None, rahul, "client", True, timedelta(days=1, hours=3)),
        (owner, "document_flagged",
         "⚠ Rilono AI flagged Bank statement (aarav_hdfc_statement_aug.pdf) for Aarav Mehta — needs review",
         None, None, "client", True, timedelta(days=1, hours=7, minutes=20)),
        (owner, "client_added", "Priya Nair added client Priyanka Reddy",
         "United States · F-1 Student Visa", priya, "client", True, timedelta(days=2, hours=20)),
        (owner, "member_added", "Rahul Verma added Deepak Iyer to the team",
         "Role: Document Reviewer", rahul, "team", True, timedelta(days=6, hours=4)),
        # A few for other staff so their bells are not empty either.
        (arjun, "docs_submitted", "📁 Aarav Mehta submitted all requested documents",
         None, None, "client", False, timedelta(hours=4, minutes=5)),
        (arjun, "interview_completed", "🎤 Ishita Rao completed their mock interview",
         "Verdict: likely approved", None, "client", False, timedelta(hours=2, minutes=10)),
        (rahul, "lead_received", "New lead: Tanvi Agarwal via Website enquiries",
         "tanvi.agarwal@example.com", None, "lead", False, timedelta(minutes=35)),
        (rahul, "client_added", "Priya Nair added client Priyanka Reddy",
         "United States · F-1 Student Visa", priya, "client", True, timedelta(days=2, hours=20)),
        (kavya, "status_changed", "Rahul Verma moved Karan Singh to Application Submitted",
         None, rahul, "client", True, timedelta(days=1, hours=3)),
    ]
    for recipient, ntype, title, body, actor, ref_type, is_read, age in spec:
        session.add(models.EnterpriseNotification(
            organization_id=org.id, recipient_user_id=recipient.id,
            actor_user_id=(actor.id if actor is not None else None), type=ntype, title=title,
            body=body, reference_type=ref_type, reference_id=None, is_read=is_read,
            created_at=NOW - age,
        ))
    session.flush()
    return len(spec)


def create_access_audit(session, org, users: dict, branches: dict, custom_role) -> int:
    owner = users[OWNER_EMAIL]
    rahul = users["rahul.verma@example.com"]
    deepak = users["deepak.iyer@example.com"]
    neha = users["neha.gupta@example.com"]
    priya = users["priya.nair@example.com"]
    kavya = users["kavya.krishnan@example.com"]
    kochi = branches[KOCHI]
    hyd = branches[HYD]
    # (age, action, actor, target_user, target_name, role_id, branch_id, summary, before, after)
    spec = [
        (timedelta(days=6, hours=5), "role_created", owner, None, CUSTOM_ROLE_NAME, custom_role.id, None,
         f'Created the role "{CUSTOM_ROLE_NAME}"', None,
         {"name": CUSTOM_ROLE_NAME, "data_scope": "all", "based_on": "viewer"}),
        (timedelta(days=6, hours=4, minutes=10), "member_invited", rahul, deepak, None, custom_role.id, None,
         f"Invited Deepak Iyer as {CUSTOM_ROLE_NAME}", None,
         {"role": CUSTOM_ROLE_NAME, "office": HYD, "job_title": "Document Specialist"}),
        (timedelta(days=6, hours=1), "member_branches_changed", rahul, deepak, None, None, hyd.id,
         "Changed which offices Deepak Iyer works in", {"branches": []}, {"branches": [HYD]}),
        (timedelta(days=5, hours=4), "member_role_changed", owner, neha, None, None, None,
         "Changed Neha Gupta's role to Viewer", {"role": "Counsellor"}, {"role": "Viewer"}),
        (timedelta(days=5, hours=3, minutes=40), "member_capabilities_changed", owner, neha, None, None, None,
         "Changed Neha Gupta's permissions", {"grants": [], "denies": []},
         {"grants": ["documents.download"], "denies": []}),
        (timedelta(days=4, hours=6), "member_scope_changed", owner, priya, None, None, hyd.id,
         "Changed Priya Nair's data access to Their office", {"data_scope": "all"}, {"data_scope": "branch"}),
        (timedelta(days=3, hours=2), "branch_updated", rahul, None, KOCHI, None, kochi.id,
         f'Updated the office "{KOCHI}"', {"phone": "+91 484 235 0000"}, {"phone": kochi.phone}),
        (timedelta(days=2, hours=7), "member_profile_updated", rahul, kavya, None, None, None,
         "Updated Kavya Krishnan's profile", {"job_title": "Junior Counsellor"}, {"job_title": "Counsellor"}),
        (timedelta(days=1, hours=4), "clients_exported", rahul, None, "Client list", None, None,
         "Exported the client list to CSV (38 clients)", None, {"format": "csv", "rows": 38}),
        (timedelta(hours=4, minutes=6), "member_signed_in", deepak, deepak, None, None, None,
         "Deepak Iyer signed in for the first time", None, {"ip": DEMO_IP}),
        (timedelta(minutes=48), "member_profile_updated", owner, owner, None, None, None,
         "Updated Ananya Rao's profile", {"phone": "+91 98450 00000"}, {"phone": "+91 98450 12345"}),
    ]
    for age, action, actor, target, target_name, role_id, branch_id, summary, before, after in spec:
        detail = None
        if before is not None or after is not None:
            detail = json.dumps({"before": before, "after": after}, default=str)
        session.add(models.EnterpriseAccessAudit(
            organization_id=org.id, action=action, actor_user_id=actor.id, actor_name=actor.full_name,
            target_user_id=(target.id if target is not None else None),
            target_name=(target_name or (target.full_name if target is not None else None)),
            target_role_id=role_id, target_branch_id=branch_id, summary=summary,
            detail_json=detail, ip_address=DEMO_IP, created_at=NOW - age,
        ))
    session.flush()
    return len(spec)


def create_finance_settings(session, org, users: dict):
    row = models.EnterpriseFinanceSettings(
        organization_id=org.id, hourly_cost_paise=55_000, opening_balance_paise=25_000_000,
        opening_balance_on=date(2026, 4, 1), fy_start_month=4,
        savings_overrides_json=json.dumps(FINANCE_SAVINGS_OVERRIDES),
        updated_by_user_id=users["sanjay.patel@example.com"].id,
        created_at=datetime(2026, 4, 3, 6, 20),
    )
    session.add(row)
    session.flush()
    return row


def create_linked_account(session, org, users: dict):
    """Payable Razorpay Route account so Finance shows no 'connect your bank' nudge."""
    owner = users[OWNER_EMAIL]
    row = models.EnterpriseLinkedAccount(
        organization_id=org.id, razorpay_account_id="acc_MERIDIAN0OVERSEAS1",
        razorpay_product_id="acc_prd_MERIDIAN01", razorpay_stakeholder_id="sth_MERIDIAN01",
        legal_business_name="Meridian Overseas Education Pvt Ltd", business_type="private_limited",
        contact_name=owner.full_name, contact_email=owner.email, contact_phone="+91 98450 12345",
        bank_account_last4="4821", bank_ifsc="HDFC0001234",
        beneficiary_name="Meridian Overseas Education Pvt Ltd", activation_status="activated",
        requirements_json="[]", is_payable=True, attested_service_delivery=True,
        attested_turnover_ok=True, attested_at=datetime(2026, 7, 28, 5, 10), attested_ip=DEMO_IP,
        attested_version=legal.FINANCE_ATTESTATION_VERSION, created_by_user_id=owner.id,
        created_at=datetime(2026, 7, 28, 5, 10),
    )
    session.add(row)
    session.flush()
    return row


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
JWT_MINT_CMD = (
    f"cd {WEB_APP_DIR} && DATABASE_URL='{SANDBOX_DB_URL}' "
    "/Users/gaurav/.pyenv/versions/3.11.6/bin/python3 -c \"from datetime import timedelta; "
    "from app.auth import create_access_token; "
    f"print(create_access_token(data={{'sub':'{OWNER_EMAIL}'}}, expires_delta=timedelta(hours=12)))\""
)


def seed(session) -> dict:
    purged = purge_demo(session)
    users = create_users(session)
    org = create_org(session, users)
    branches = create_branches(session, org, users)
    custom_role, custom_caps = create_custom_role(session, org, users)
    members = create_members(session, org, users, branches, custom_role, custom_caps)
    sub, plan_payment = create_subscription(session, org, users)
    wallet, topup, ledger_rows = create_wallet_and_ledger(session, org, sub, users)
    n_notif = create_notifications(session, org, users)
    n_audit = create_access_audit(session, org, users, branches, custom_role)
    create_finance_settings(session, org, users)
    create_linked_account(session, org, users)
    return {
        "purged": purged,
        "org_id": org.id,
        "users": {email: u.id for email, u in users.items()},
        "members": {email: m.id for email, m in members.items()},
        "branches": {name: b.id for name, b in branches.items()},
        "custom_role_id": custom_role.id,
        "subscription_id": sub.id,
        "plan_payment_id": plan_payment.id,
        "wallet": {"balance": wallet.balance_credits, "period": wallet.plan_credits_period,
                   "granted": wallet.plan_credits_granted, "remaining": wallet.plan_credits_remaining,
                   "purchased": wallet.lifetime_purchased_credits, "spent": wallet.lifetime_spent_credits},
        "topup_payment_id": topup.id,
        "ledger_rows": ledger_rows,
        "notifications": n_notif,
        "audit_rows": n_audit,
    }


def verify_app_view(session, org_id: int) -> dict:
    """Read the workspace back through the app's own builders (no HTTP) as a smoke test."""
    state = billing.build_subscription_state(session, org_id)
    wallet_state = credits.wallet_state(session, org_id)      # runs the lazy plan-credit sync
    plan = wallet_state["plan_credits"]
    return {
        "plan": state["plan"], "status": state["status"], "grandfathered": state["grandfathered"],
        "plan_lapsed": state["plan_lapsed"], "auto_renews": state["auto_renews"],
        "seats_used": state["seats_used"], "clients_used": state["clients_used"],
        "currency": state["currency"], "monthly_display": state["monthly_display"],
        "balance_after_sync": wallet_state["balance_credits"],
        "remaining_this_period": plan["remaining_this_period"], "used_this_period": plan["used_this_period"],
        "renews_at": str(plan["renews_at"]), "period_key": plan["period_key"],
        "low_balance": wallet_state["low_balance"],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true",
                        help="run the purge + lookups inside a transaction and roll back (nothing is written)")
    args = parser.parse_args(argv)

    session = SessionLocal()
    try:
        if args.dry_run:
            existing = get_org(session)
            print(f"DB: {engine.url}")
            print(f"existing meridian org: {existing.id if existing else None}")
            print(f"existing demo users: {[u.id for u in session.query(models.User).filter(models.User.email.in_(DEMO_EMAILS)).all()]}")
            counts = purge_demo(session)
            print(f"purge would delete: {counts or '{} (nothing to purge)'}")
            session.rollback()
            print("dry run complete — rolled back, nothing written")
            return 0

        summary = seed(session)
        session.commit()
        checks = verify_app_view(session, summary["org_id"])
        session.commit()
        assert checks["plan"] == "growth" and checks["status"] == "active"
        assert not checks["grandfathered"] and not checks["plan_lapsed"]
        assert checks["balance_after_sync"] == 2340, checks
        assert checks["remaining_this_period"] == 2340, checks
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    print("=== Meridian demo org seeded ===")
    print(f"DB: {engine.url}")
    print(f"purged: {summary['purged'] or '{}'}")
    print(f"org_id={summary['org_id']} slug={ORG_SLUG} custom_role_id={summary['custom_role_id']} "
          f"subscription_id={summary['subscription_id']} plan_payment_id={summary['plan_payment_id']} "
          f"topup_payment_id={summary['topup_payment_id']}")
    print(f"branches: {summary['branches']}")
    print(f"users: {summary['users']}")
    print(f"members: {summary['members']}")
    print(f"wallet: {summary['wallet']}  ledger_rows={summary['ledger_rows']} "
          f"notifications={summary['notifications']} audit_rows={summary['audit_rows']}")
    print(f"app view: {checks}")
    print(f"portal: http://{ORG_SLUG}.localhost:8099/enterprise   (password for all demo users: {DEMO_PASSWORD})")
    print("mint an owner JWT (cookie rilono_access_token):")
    print(JWT_MINT_CMD)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
