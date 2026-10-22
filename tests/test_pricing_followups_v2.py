"""Pricing v2 follow-ups (2026-10-22): the backend loose ends left after phases 1 and 2.

Each test pins a rule whose failure misleads a customer or misstates money:

  * a welcome email promising the OLD trial ("2 users, 10 active clients and 100 AI
    credits"), or promising a trial at all to a company whose domain already used one;
  * a client Copilot link email promising help "any time" on a 5-message link;
  * the subscription chip quoting INR to a London office with no country on file while its
    cards and checkout are in GBP; a signup that never records the company's country;
  * a plan change in the last 5 days of a yearly coverage minting a whole extra allowance
    (the bare 30-day rule read the 35-day final sub-period as already over);
  * an offline payment's receipt reading "offline:UTR…" and naming the Rilono admin who
    recorded it as the buyer; a refunded plan charge shown (and summed) at its full amount;
  * in-progress / abandoned interview sessions counted as interviews by the assistant, the
    Deep Scan dossier and the ROI panel; assistant answers from before the re-price
    under-counted 2.5x;
  * revenue by branch shown on a plan without per-branch reporting;
  * the offline-payment note accepted by the console and then dropped.

sqlite in memory; the real routers mounted on bare FastAPI apps; email delivery captured.
"""

import re
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import email_service
from app import enterprise_access as access
from app import enterprise_ai
from app import enterprise_billing as billing
from app import enterprise_credits as credits
from app import enterprise_finance as finance
from app import fx
from app import models
from app import money
from app import schema_patch
from app.admin_sessions import get_current_console_user
from app.auth import get_current_active_user
from app.database import Base, get_db
from app.routers import admin
from app.routers import enterprise
from app.utils.token_security import hash_token


START = datetime(2026, 10, 22, 12)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sent(monkeypatch):
    """Every Resend send, captured (and answered as delivered)."""
    calls = []

    def _send(params):
        calls.append(params)
        return {"id": f"em_{len(calls)}"}

    monkeypatch.setattr(email_service, "RESEND_API_KEY", "re_test")
    monkeypatch.setattr(email_service.resend.Emails, "send", _send)
    return calls


def _plain(html: str) -> str:
    """Visible text of an email body, whitespace collapsed (tags and entities stripped)."""
    text_only = re.sub(r"<[^>]+>", " ", html).replace("&amp;", "&").replace("&rarr;", "→")
    return re.sub(r"\s+", " ", text_only).strip()


@pytest.fixture
def ctx(monkeypatch):
    """The enterprise router on in-memory sqlite, signed in as an Indian org's owner."""
    monkeypatch.setattr(billing, "ENTERPRISE_FREE", False)
    monkeypatch.setattr(billing, "AI_PAUSE_ON_EXPIRY", True)
    monkeypatch.setattr(billing, "GRACE_UNTIL", None)
    monkeypatch.setattr(billing, "YEARLY_ENABLED", False)
    monkeypatch.setattr(credits, "ENFORCE", True)
    monkeypatch.setattr(fx, "get_usd_to_inr", lambda force=False: 95.0)
    monkeypatch.setattr(enterprise, "ENTERPRISE_ONE_TRIAL_PER_DOMAIN", True)
    monkeypatch.setattr(enterprise, "_enforce_rate_limit_or_429", lambda *a, **kw: None)
    welcome = []
    monkeypatch.setattr(
        enterprise, "send_enterprise_welcome_email", lambda **kw: welcome.append(kw) or True,
    )

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, autoflush=False)()
    owner = models.User(
        email="owner@acme-consult.example", hashed_password="x", full_name="Owner",
        is_active=True, email_verified=True, is_enterprise_account=True,
    )
    db.add(owner)
    db.flush()
    org = models.EnterpriseOrganization(
        company_name="Acme Consult", subdomain_slug="acme-consult", created_by_user_id=owner.id,
        country_code="IN",
    )
    db.add(org)
    db.flush()
    db.add(models.EnterpriseOrganizationMember(
        organization_id=org.id, user_id=owner.id, role_key=access.ROLE_OWNER, role="admin",
        is_active=True,
    ))
    db.commit()

    app = FastAPI()
    app.include_router(enterprise.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_active_user] = lambda: owner
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, db=db, org=org, owner=owner, welcome=welcome)
    db.close()
    engine.dispose()


def _set_plan(c, plan="starter", **fields):
    sub = billing.get_or_create_org_subscription(c.db, c.org.id)
    now = datetime.utcnow()
    values = {"plan": plan, "status": "active", "current_period_end": now + timedelta(days=20),
              "trial_ends_at": now - timedelta(days=40)}
    if plan == "sandbox":
        values = {"plan": "sandbox", "status": "trialing", "current_period_end": None,
                  "trial_ends_at": now + timedelta(days=10)}
    values.update(fields)
    for key, value in values.items():
        setattr(sub, key, value)
    c.db.commit()
    return sub


def _signup(c, email, slug, headers=None):
    c.db.add(models.EnterpriseSignupOtp(
        email=email, code_hash=hash_token("123456"),
        expires_at=datetime.utcnow() + timedelta(minutes=10),
    ))
    c.db.commit()
    return c.client.post("/api/enterprise/signup", headers=headers or {}, json={
        "company_name": f"Company {slug}", "subdomain_slug": slug, "full_name": "New Owner",
        "email": email, "password": "Strong-Test-Password9!", "accepted_terms_privacy": True,
        "accepted_dpa": True, "email_otp": "123456",
    })


def _org_by_slug(c, slug):
    c.db.expire_all()
    return c.db.query(models.EnterpriseOrganization).filter_by(subdomain_slug=slug).one()


def _client(c, **fields):
    row = models.EnterpriseClient(
        organization_id=c.org.id, full_name=fields.pop("full_name", "Riya Sharma"),
        status=fields.pop("status", "new_lead"), destination_country_code="GB",
        destination_country_name="United Kingdom", visa_type="Student visa",
        created_by_user_id=c.owner.id, **fields,
    )
    c.db.add(row)
    c.db.commit()
    return row


# ---------------------------------------------------------------------------
# Welcome email: the trial it describes is the trial the workspace got
# ---------------------------------------------------------------------------

STALE_TRIAL_COPY = ("sandbox", "2 users", "10 active clients", "100 AI credits", "+ GST")


def test_welcome_email_describes_the_live_trial(sent, monkeypatch):
    monkeypatch.setattr(billing, "ENTERPRISE_FREE", False)
    assert email_service.send_enterprise_welcome_email(
        to_email="asha@acme.example", full_name="Asha Rao", company="Acme",
    ) is True
    text = _plain(sent[-1]["html"])
    facts = billing.trial_facts()
    assert f"Your {facts['label']} includes" in text
    assert f"{facts['max_seats']:,} staff seats" in text
    assert f"{facts['max_open_files']:,} open student files" in text
    assert f"{facts['included_credits']:,} AI credits" in text
    assert f"{facts['reads']:,} AI document reads" in text
    assert "no card needed" in text
    if facts["demo_bonus_credits"]:
        assert f"+{facts['demo_bonus_credits']:,} after a demo call" in text
    for stale in STALE_TRIAL_COPY:
        assert stale not in text, stale


def test_welcome_email_follows_the_catalog_not_hand_typed_numbers(sent, monkeypatch):
    monkeypatch.setattr(billing, "ENTERPRISE_FREE", False)
    monkeypatch.setattr(billing, "trial_facts", lambda: {
        "label": "21-day free trial", "days": 21, "max_seats": 7, "max_open_files": 1234,
        "included_credits": 70, "demo_bonus_credits": 0, "reads": 33,
        "ai_pauses_on_expiry": False, "features": [],
    })
    email_service.send_enterprise_welcome_email(to_email="a@b.example", company="B")
    text = _plain(sent[-1]["html"])
    assert ("Your 21-day free trial includes 7 staff seats, 1,234 open student files, "
            "70 AI credits and 33 AI document reads") in text
    # No bonus configured, no pause configured: neither is promised.
    assert "demo call" not in text
    assert "pause" not in text


def test_welcome_email_says_when_ai_pauses(sent, monkeypatch):
    monkeypatch.setattr(billing, "ENTERPRISE_FREE", False)
    monkeypatch.setattr(billing, "AI_PAUSE_ON_EXPIRY", True)
    email_service.send_enterprise_welcome_email(to_email="a@b.example")
    assert "AI features pause until you choose a plan — your data stays" in _plain(sent[-1]["html"])


def test_welcome_email_promises_no_trial_to_a_repeat_company_domain(sent, monkeypatch):
    monkeypatch.setattr(billing, "ENTERPRISE_FREE", False)
    email_service.send_enterprise_welcome_email(
        to_email="second@acme.example", company="Acme 2", trial_domain_blocked=True,
    )
    text = _plain(sent[-1]["html"])
    assert "already used its free trial" in text
    assert "Next steps: choose a plan in Plans & Billing" in text
    assert "Think that's a mistake" in text
    assert "includes" not in text and "no card needed" not in text
    assert str(billing.trial_facts()["label"]) not in text


def test_welcome_email_describes_no_trial_while_billing_is_off(sent, monkeypatch):
    monkeypatch.setattr(billing, "ENTERPRISE_FREE", True)
    email_service.send_enterprise_welcome_email(to_email="a@b.example")
    text = _plain(sent[-1]["html"])
    assert "trial" not in text.lower()
    assert "Next steps: add your first student" in text


def test_signup_passes_the_trial_decision_to_the_welcome_email(ctx):
    assert _signup(ctx, "founder@brand-new-agency.example", "brand-new").status_code == 200
    assert ctx.welcome[-1]["trial_domain_blocked"] is False
    # The fixture org's owner already holds acme-consult.example: no second trial.
    assert _signup(ctx, "second@acme-consult.example", "acme-second").status_code == 200
    assert ctx.welcome[-1]["trial_domain_blocked"] is True


# ---------------------------------------------------------------------------
# Client Copilot link email: states the link's real limits
# ---------------------------------------------------------------------------

def _copilot_email(**extra):
    return email_service.send_enterprise_copilot_invite_email(
        to_email="student@example.com", client_name="Riya", organization_name="Acme",
        copilot_url="https://acme.rilono.com/assist?t=x", destination_country="United Kingdom",
        visa_type="Student visa", **extra,
    )


def test_copilot_email_states_the_message_allowance_and_end_date(sent):
    ok, _, _ = _copilot_email(messages_included=5, expires_at=datetime(2026, 11, 21, 9, 30))
    assert ok
    text = _plain(sent[-1]["html"])
    assert "This link includes 5 messages and works until 21 Nov 2026." in text
    assert "any time" not in text
    assert "This link includes 5 messages" in sent[-1]["text"]
    assert "any time" not in sent[-1]["text"]


def test_copilot_email_singular_and_legacy_callers(sent):
    _copilot_email(messages_included=1)
    assert "This link includes 1 message." in _plain(sent[-1]["html"])
    _copilot_email()   # no limits known: the old open-ended copy, unchanged
    assert "any time" in _plain(sent[-1]["html"])
    assert "This link includes" not in _plain(sent[-1]["html"])


def test_copilot_invite_endpoint_emails_the_links_limits(ctx, monkeypatch):
    _set_plan(ctx, "starter")
    credits.sync_plan_credits(ctx.db, ctx.org.id)
    client = _client(ctx, email="riya@example.com")
    captured = []
    monkeypatch.setattr(
        enterprise, "send_enterprise_copilot_invite_email",
        lambda **kw: captured.append(kw) or (True, "em_1", None),
    )
    res = ctx.client.post(f"/api/enterprise/clients/{client.id}/copilot/invite")
    assert res.status_code == 200, res.text
    assert captured[-1]["messages_included"] == credits.COPILOT_CLIENT_MESSAGES
    invite = ctx.db.query(models.EnterpriseCopilotInvite).filter_by(client_id=client.id).one()
    assert captured[-1]["expires_at"] == invite.expires_at


# ---------------------------------------------------------------------------
# Subscription currency follows the request's geo when the org has no country
# ---------------------------------------------------------------------------

def _geo(country):
    return SimpleNamespace(headers={"cf-ipcountry": country} if country else {})


@pytest.mark.parametrize("geo,currency,inr_region,usd_estimate", [
    ("GB", "GBP", False, False),   # London office, no country on file: never INR
    ("AE", "AED", False, False),
    ("NP", "INR", True, True),     # INR region outside India: INR plus a US$ estimate
    ("IN", "INR", True, False),
    (None, "INR", True, False),    # unknown everywhere: the domestic default
])
def test_state_currency_uses_request_geo_without_an_org_country(ctx, geo, currency, inr_region, usd_estimate):
    _set_plan(ctx, "starter")
    ctx.org.country_code = None
    ctx.db.commit()
    state = billing.build_subscription_state(ctx.db, ctx.org.id, request=_geo(geo))
    assert state["currency"] == currency
    assert state["inr_region"] is inr_region
    assert state["show_usd_estimate"] is usd_estimate
    # ...and it is the currency checkout would charge (one rule, one answer).
    assert enterprise._resolve_charge_currency(None, ctx.org, db=ctx.db, request=_geo(geo)) == currency


def test_org_country_beats_the_request_geo(ctx):
    _set_plan(ctx, "starter")
    state = billing.build_subscription_state(ctx.db, ctx.org.id, request=_geo("GB"))
    assert state["currency"] == "INR"


def test_state_without_a_request_is_unchanged(ctx):
    _set_plan(ctx, "starter")
    ctx.org.country_code = None
    ctx.db.commit()
    assert billing.build_subscription_state(ctx.db, ctx.org.id)["currency"] == "INR"
    assert billing.build_subscription_state(ctx.db, ctx.org.id, read_only=True)["currency"] == "INR"


@pytest.mark.parametrize("path", ["/api/enterprise/billing/plans", "/api/enterprise/billing/subscription"])
def test_billing_endpoints_agree_on_currency_for_a_geo_only_org(ctx, path):
    _set_plan(ctx, "starter")
    ctx.org.country_code = None
    ctx.db.commit()
    body = ctx.client.get(path, headers={"cf-ipcountry": "GB"}).json()
    assert body["currency"] == "GBP"
    assert body["subscription"]["currency"] == "GBP"
    starter = next(p for p in body["plans"] if p["key"] == "starter")
    assert starter["currency"] == "GBP"
    assert body["subscription"]["monthly_minor"] == starter["monthly_minor"]


def test_signup_records_the_company_country_from_geo(ctx):
    assert _signup(ctx, "boss@london-agency.example", "london", headers={"cf-ipcountry": "GB"}).status_code == 200
    assert _org_by_slug(ctx, "london").country_code == "GB"
    # The new workspace's own subscription is quoted in GBP from then on, with no request.
    org = _org_by_slug(ctx, "london")
    assert billing.build_subscription_state(ctx.db, org.id, read_only=True)["inr_region"] is False


def test_signup_without_geo_leaves_the_country_unknown(ctx):
    assert _signup(ctx, "boss@nowhere-agency.example", "nowhere").status_code == 200
    assert _org_by_slug(ctx, "nowhere").country_code is None


# ---------------------------------------------------------------------------
# Yearly coverage: a plan change in the 35-day final sub-period is NOT a new period
# ---------------------------------------------------------------------------

@pytest.fixture
def credit_db(monkeypatch):
    monkeypatch.setattr(billing, "ENTERPRISE_FREE", False)
    monkeypatch.setattr(billing, "GRACE_UNTIL", None)
    monkeypatch.setattr(credits, "PLAN_CREDITS_ROLLOVER", False)
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    owner = models.User(email="yearly@followups.example", hashed_password="x")
    db.add(owner)
    db.flush()
    org = models.EnterpriseOrganization(company_name="Yearly Co", created_by_user_id=owner.id)
    db.add(org)
    db.commit()
    db.info["org_id"] = org.id
    yield db
    db.close()
    engine.dispose()


@pytest.fixture
def clock(monkeypatch):
    state = {"now": START}

    class Fixed(datetime):
        @classmethod
        def utcnow(cls):
            return state["now"]

    monkeypatch.setattr(billing, "datetime", Fixed)
    monkeypatch.setattr(credits, "datetime", Fixed)
    return state


def _covered_sub(db, *, end, cycles, plan="growth"):
    org_id = db.info["org_id"]
    for i, cycle in enumerate(cycles):
        db.add(models.EnterpriseSubscriptionPayment(
            organization_id=org_id, plan=plan, billing_cycle=cycle, amount_paise=1,
            currency="INR", razorpay_order_id=f"order_f{i}", status="verified",
        ))
    sub = models.EnterpriseSubscription(
        organization_id=org_id, plan=plan, status="active", current_period_end=end,
        trial_ends_at=START - timedelta(days=60), created_at=START - timedelta(days=60),
    )
    db.add(sub)
    db.commit()
    return sub


def _wallet(db):
    db.expire_all()
    return db.query(models.EnterpriseCreditWallet).filter_by(organization_id=db.info["org_id"]).one()


def _key(plan, day):
    return f"{plan}:{(START + timedelta(days=day)):%Y-%m-%d}"


def test_final_yearly_subperiod_ends_with_the_coverage(credit_db):
    sub = _covered_sub(credit_db, end=START + timedelta(days=365), cycles=["yearly"])
    # The 12th sub-period starts on day 330 and runs 35 days, to the coverage end.
    assert credits._key_period_end(_key("growth", 330), sub) == START + timedelta(days=365)
    # An ordinary sub-period ends 30 days after its real start.
    assert credits._key_period_end(_key("growth", 300), sub) == START + timedelta(days=330)
    # Without the subscription the key alone can only say "30 days" (the old rule).
    key_day = datetime.combine((START + timedelta(days=330)).date(), datetime.min.time())
    assert credits._key_period_end(_key("growth", 330)) == key_day + timedelta(days=30)


def test_final_yearly_subperiod_is_live_until_the_coverage_end(credit_db, clock):
    sub = _covered_sub(credit_db, end=START + timedelta(days=365), cycles=["yearly"])
    key = _key("growth", 330)
    clock["now"] = START + timedelta(days=362)
    assert credits._period_key_elapsed(key) is True          # the bug: bare 30-day rule
    assert credits._period_key_elapsed(key, sub) is False
    assert credits._period_key_live(key, sub) is True
    clock["now"] = START + timedelta(days=365, hours=1)
    assert credits._period_key_elapsed(key, sub) is True


def test_plan_change_in_the_last_days_of_a_year_grants_only_the_difference(credit_db, clock):
    org_id = credit_db.info["org_id"]
    sub = _covered_sub(credit_db, end=START + timedelta(days=365), cycles=["yearly"])
    team = billing.PLANS["growth"]
    multi = billing.PLANS["scale"]
    clock["now"] = START + timedelta(days=340)
    credits.sync_plan_credits(credit_db, org_id)
    wallet = _wallet(credit_db)
    assert wallet.plan_credits_granted == team["included_credits"]
    assert wallet.plan_credits_period == _key("growth", 330)
    wallet.reads_used = 7
    credit_db.commit()

    # Upgrade Team -> Multi-branch on day 362 of the year (inside the 35-day tail).
    clock["now"] = START + timedelta(days=362)
    sub.plan = "scale"
    credit_db.commit()
    txn = credits.sync_plan_credits(credit_db, org_id)

    assert txn is not None
    assert txn.credits == multi["included_credits"] - team["included_credits"]
    wallet = _wallet(credit_db)
    assert wallet.plan_credits_granted == multi["included_credits"]
    assert wallet.balance_credits == multi["included_credits"]
    # Nothing expired (the period hasn't ended) and the reads count carried over.
    expired = credit_db.query(models.EnterpriseCreditTransaction).filter_by(
        organization_id=org_id, type="adjustment",
    ).count()
    assert expired == 0
    assert wallet.reads_used == 7
    assert wallet.reads_granted == max(team["max_reads"], multi["max_reads"])


def test_downgrade_in_the_last_days_of_a_year_grants_nothing(credit_db, clock):
    org_id = credit_db.info["org_id"]
    sub = _covered_sub(credit_db, end=START + timedelta(days=365), cycles=["yearly"], plan="scale")
    clock["now"] = START + timedelta(days=331)
    credits.sync_plan_credits(credit_db, org_id)
    before = _wallet(credit_db).balance_credits
    clock["now"] = START + timedelta(days=363)
    sub.plan = "starter"
    credit_db.commit()
    assert credits.sync_plan_credits(credit_db, org_id) is None
    assert _wallet(credit_db).balance_credits == before


def test_monthly_periods_still_end_after_thirty_days(credit_db, clock):
    sub = _covered_sub(credit_db, end=START + timedelta(days=30), cycles=["monthly"])
    key = _key("growth", 0)
    assert credits._key_period_end(key, sub) == START + timedelta(days=30)
    clock["now"] = START + timedelta(days=29)
    assert credits._period_key_live(key, sub) is True
    clock["now"] = START + timedelta(days=30, minutes=1)
    assert credits._period_key_elapsed(key, sub) is True


def test_a_key_off_the_current_grid_keeps_the_thirty_day_rule(credit_db):
    # A lapse and a fresh start re-anchor the grid: a key from the old grid must not borrow
    # a period end from the new one.
    sub = _covered_sub(credit_db, end=START + timedelta(days=20), cycles=["monthly"])
    old_key = "growth:2026-01-05"
    assert credits._key_period_end(old_key, sub) == datetime(2026, 2, 4)


def test_one_time_and_unknown_keys_have_no_end(credit_db):
    sub = _covered_sub(credit_db, end=START + timedelta(days=30), cycles=["monthly"])
    assert credits._key_period_end("sandbox:once", sub) is None
    assert credits._key_period_end("", sub) is None
    assert credits._key_period_end("growth:not-a-date", sub) is None
    assert credits._period_key_elapsed("sandbox:once", sub) is False
    # A non-paid plan prefix never consults the paid grid.
    assert credits._key_period_end("sandbox:2026-10-22", sub) == datetime(2026, 11, 21)


def test_twelve_allowances_a_year_even_with_a_late_upgrade(credit_db, clock):
    """End to end: a yearly Team buyer upgrading on day 362 gets 12 period grants plus ONE
    top-up difference — not a 13th full allowance."""
    org_id = credit_db.info["org_id"]
    sub = _covered_sub(credit_db, end=START + timedelta(days=365), cycles=["yearly"])
    for day in range(0, 368):
        clock["now"] = START + timedelta(days=day, hours=3)
        if day == 362:
            sub.plan = "scale"
            credit_db.commit()
        credits.sync_plan_credits(credit_db, org_id, commit=True)
    grants = (
        credit_db.query(models.EnterpriseCreditTransaction)
        .filter_by(organization_id=org_id, reference_type="plan_credits", type="bonus")
        .order_by(models.EnterpriseCreditTransaction.id)
        .all()
    )
    team = billing.PLANS["growth"]["included_credits"]
    multi = billing.PLANS["scale"]["included_credits"]
    assert [g.credits for g in grants] == [team] * 12 + [multi - team]


# ---------------------------------------------------------------------------
# Customer receipts: offline plan payments
# ---------------------------------------------------------------------------

def test_receipts_show_offline_reference_and_method_never_the_rilono_admin(ctx):
    staff = models.User(email="staff@rilono.example", full_name="Rilono Staffer", hashed_password="x")
    ctx.db.add(staff)
    ctx.db.flush()
    ctx.db.add(models.EnterpriseSubscriptionPayment(
        organization_id=ctx.org.id, created_by_user_id=staff.id, provider="bank_transfer",
        plan="growth", billing_cycle="yearly", amount_paise=4718820, tax_paise=719820,
        currency="INR", razorpay_order_id=f"{admin.OFFLINE_ORDER_PREFIX}UTR778899",
        status="verified", verified_at=datetime.utcnow(), note="internal: paid by NEFT",
    ))
    ctx.db.add(models.EnterpriseSubscriptionPayment(
        organization_id=ctx.org.id, created_by_user_id=ctx.owner.id, provider="razorpay",
        plan="starter", billing_cycle="monthly", amount_paise=176882, currency="INR",
        razorpay_order_id="order_ABC123", razorpay_payment_id="pay_XYZ789",
        status="partially_refunded", refunded_amount_paise=50000,
        verified_at=datetime.utcnow() - timedelta(days=40),
    ))
    ctx.db.commit()
    body = ctx.client.get("/api/enterprise/credits/payments").json()
    rows = {r["package_key"]: r for r in body["payments"] if r["kind"] == "plan"}

    offline = rows["growth"]
    assert offline["payment_reference"] == "Bank transfer · UTR778899"
    assert "offline:" not in offline["payment_reference"]
    assert offline["payment_provider"] == "bank_transfer"
    assert offline["is_offline"] is True
    assert offline["label"].endswith("· yearly")
    assert offline["created_by_name"] == "Recorded by Rilono"
    flat = repr(body)
    assert "Rilono Staffer" not in flat and "staff@rilono.example" not in flat
    assert "internal: paid by NEFT" not in flat   # the admin note is internal

    online = rows["starter"]
    assert online["payment_reference"] == "pay_XYZ789"
    assert online["payment_provider_label"] == "Razorpay"
    assert online["created_by_name"] == "Owner"
    assert online["label"].endswith("· monthly")
    assert online["refunded_amount_paise"] == 50000
    assert online["net_amount_paise"] == 176882 - 50000
    inr = next(c for c in body["summary"]["collected_by_currency"] if c["currency"] == "INR")
    assert inr["amount_minor"] == 4718820 + 176882 - 50000


# ---------------------------------------------------------------------------
# Interviews = completed sessions (assistant, Deep Scan dossier, ROI panel)
# ---------------------------------------------------------------------------

def _session(c, client, status, *, hours_ago, verdict=None, feedback=None):
    fields = dict(
        organization_id=c.org.id, client_id=client.id, mode="chat",
        verdict=verdict, feedback=feedback, transcript="[]",
        created_at=datetime.utcnow() - timedelta(hours=hours_ago),
    )
    if status is not None:   # None = a legacy row: the column default ("completed") applies
        fields["status"] = status
    row = models.EnterpriseInterviewSession(**fields)
    c.db.add(row)
    c.db.commit()
    return row


@pytest.fixture
def interviews(ctx):
    client = _client(ctx)
    done = _session(ctx, client, "completed", hours_ago=72, verdict="Likely approved",
                    feedback="Clear answers about funding.")
    legacy = _session(ctx, client, None, hours_ago=96, verdict="Needs work", feedback="Old report.")
    running = _session(ctx, client, "in_progress", hours_ago=1)
    dropped = _session(ctx, client, "abandoned", hours_ago=5)
    return SimpleNamespace(client=client, done=done, legacy=legacy, running=running, dropped=dropped)


def _tools(c):
    return {t.__name__: t for t in enterprise_ai.build_org_tools(c.db, c.org.id, viewer_user_id=c.owner.id)}


def test_model_criterion_matches_the_router_lists(ctx, interviews):
    S = models.EnterpriseInterviewSession
    ids = {r.id for r in ctx.db.query(S).filter(S.counts_as_interview()).all()}
    via_router = {r.id for r in ctx.db.query(S).filter(enterprise._completed_interview_filter()).all()}
    assert ids == via_router == {interviews.done.id, interviews.legacy.id}
    assert enterprise.INTERVIEW_STATUS_COMPLETED == models.INTERVIEW_SESSION_COMPLETED


def test_casework_summary_counts_completed_interviews_only(ctx, interviews):
    out = _tools(ctx)["get_client_casework_summary"](client_id=interviews.client.id)
    assert out["mock_interviews"] == 2
    # The newest row is the in-progress run — the latest INTERVIEW is the completed one.
    assert out["latest_interview"]["id"] == interviews.done.id
    assert out["latest_interview"]["verdict"] == "Likely approved"


def test_interview_report_tool_refuses_an_unfinished_session(ctx, interviews):
    report = _tools(ctx)["get_mock_interview_report"]
    assert report(interviews.running.id) == {"error": "No such interview session."}
    assert report(interviews.dropped.id) == {"error": "No such interview session."}
    assert report(interviews.done.id)["verdict"] == "Likely approved"


def test_deep_scan_dossier_lists_completed_interviews_only(ctx, interviews):
    block = enterprise_ai._deep_scan_interviews_block(ctx.db, interviews.client.id)
    lines = [line for line in block.splitlines() if line.strip()]
    assert len(lines) == 2
    assert "verdict: n/a" not in block
    assert "Likely approved" in block and "Needs work" in block


def test_roi_panel_counts_completed_interviews_only(ctx, interviews):
    units = finance._activity_units(ctx.db, ctx.org.id, None, datetime.utcnow().date())
    assert units["mock_interview"] == 2


# ---------------------------------------------------------------------------
# ROI panel: assistant answers at the rate in force when each debit was written
# ---------------------------------------------------------------------------

def _debit(c, credits_spent, when, action="ai_copilot"):
    c.db.add(models.EnterpriseCreditTransaction(
        organization_id=c.org.id, type="debit", action_key=action, credits=-credits_spent,
        balance_after=0, description="Rilono AI assistant", created_at=when,
    ))
    c.db.commit()


def test_assistant_answers_use_the_rate_of_their_day(ctx, monkeypatch):
    monkeypatch.setattr(credits, "COPILOT_RATE_CHANGED_AT", datetime(2026, 10, 22))
    monkeypatch.setattr(credits, "COPILOT_LEGACY_MSGS_PER_CREDIT", 5)
    monkeypatch.setattr(credits, "COPILOT_MSGS_PER_CREDIT", 2)
    _debit(ctx, 10, datetime(2026, 10, 1, 9))     # 10 credits at 5 msgs  = 50
    _debit(ctx, 4, datetime(2026, 10, 21, 23))    # 4 credits at 5 msgs   = 20
    _debit(ctx, 6, datetime(2026, 10, 22, 0, 5))  # 6 credits at 2 msgs   = 12
    _debit(ctx, 3, datetime(2026, 10, 22, 8), action="university_match")
    units = finance._activity_units(
        ctx.db, ctx.org.id, datetime(2026, 9, 1).date(), datetime(2026, 10, 23).date(),
    )
    assert units["copilot_message"] == 50 + 20 + 12
    assert units["university_match"] == 1
    # A range entirely after the change uses today's rate only.
    after = finance._activity_units(
        ctx.db, ctx.org.id, datetime(2026, 10, 22).date(), datetime(2026, 10, 23).date(),
    )
    assert after["copilot_message"] == 12


def test_copilot_message_conversion_helper(monkeypatch):
    monkeypatch.setattr(credits, "COPILOT_LEGACY_MSGS_PER_CREDIT", 5)
    monkeypatch.setattr(credits, "COPILOT_MSGS_PER_CREDIT", 2)
    assert credits.copilot_messages_for_credits(3, 4) == 15 + 8
    assert credits.copilot_messages_for_credits(0, 0) == 0
    assert credits.copilot_messages_for_credits(-3, -1) == 0


# ---------------------------------------------------------------------------
# Finance: revenue by branch is per-branch reporting (Team / Multi-branch)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("plan,expected", [("starter", False), ("growth", True), ("scale", True)])
def test_revenue_by_branch_follows_the_plan(ctx, monkeypatch, plan, expected):
    _set_plan(ctx, plan)
    branches = [{"label": "Pune office", "amount_paise": 100, "clients": 1}]
    monkeypatch.setattr(finance, "_client_dimensions", lambda db, org_id, rows: {
        "destinations": [{"label": "UK"}], "lead_sources": [], "branches": list(branches),
    })
    out = finance.analytics(ctx.db, ctx.org.id, finance.resolve_range("this_month"), cache=finance.new_cache())
    assert out["branch_reporting"] is expected
    assert out["dimensions"]["branches"] == (branches if expected else [])
    assert out["dimensions"]["destinations"] == [{"label": "UK"}]   # the rest is every plan's


def test_revenue_by_branch_during_a_live_trial(ctx, monkeypatch):
    _set_plan(ctx, "sandbox")
    monkeypatch.setattr(finance, "_client_dimensions", lambda db, org_id, rows: {
        "destinations": [], "lead_sources": [], "branches": [{"label": "HQ"}],
    })
    out = finance.analytics(ctx.db, ctx.org.id, finance.resolve_range("this_month"), cache=finance.new_cache())
    assert out["branch_reporting"] is True and out["dimensions"]["branches"] == [{"label": "HQ"}]


# ---------------------------------------------------------------------------
# Assistant: prices and allowances it can't misquote
# ---------------------------------------------------------------------------

def test_assistant_pricing_tool_quotes_per_unit_prices(ctx):
    _set_plan(ctx, "starter")
    out = _tools(ctx)["get_credit_pricing"]()
    by_label = {a["action"]: a for a in out["actions"]}
    scan = by_label[credits.ACTIONS["document_scan"]["label"]]
    assert scan["price"] == next(
        a["price_label"] for a in credits.actions_payload() if a["key"] == "document_scan"
    )
    assert "15 pages" in scan["price"]


def test_assistant_free_allowances_include_document_reads(ctx):
    _set_plan(ctx, "starter")
    credits.sync_plan_credits(ctx.db, ctx.org.id)
    out = _tools(ctx)["get_credit_free_allowances"]()
    reads = out["document_reads"]
    assert reads["allowance"] == billing.PLANS["starter"]["max_reads"]
    assert reads["left"] == billing.PLANS["starter"]["max_reads"]
    assert reads["unlimited"] is False


def test_workspace_profile_reports_open_files_next_to_the_limit(ctx):
    _set_plan(ctx, "starter")
    _client(ctx, status="new_lead", full_name="Open One")
    _client(ctx, status="approved", full_name="Done One")
    plan = _tools(ctx)["get_workspace_profile"]()["plan"]
    assert plan["open_files_used"] == 1
    assert plan["max_open_files"] == billing.PLANS["starter"]["max_clients"]


# ---------------------------------------------------------------------------
# Offline payment note: stored, and shown to Rilono staff
# ---------------------------------------------------------------------------

ACCOUNTS = "/api/admin/enterprise/accounts"


@pytest.fixture
def admin_ctx(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, autoflush=False)()
    actor = models.User(
        email="founder@rilono.example", full_name="Console Founder", hashed_password="x",
        is_admin=True, is_active=True, email_verified=True,
    )
    db.add(actor)
    db.commit()
    monkeypatch.setattr(billing, "ENTERPRISE_FREE", False)
    monkeypatch.setattr(billing, "GRACE_UNTIL", None)
    monkeypatch.setattr(billing, "YEARLY_ENABLED", False)
    monkeypatch.setattr(money, "GST_PERCENT", Decimal(18))
    monkeypatch.setattr(fx, "get_usd_to_inr", lambda force=False: 95.0)
    monkeypatch.setattr(admin, "_is_admin_turnstile_required", lambda request: False)
    monkeypatch.setattr(admin, "check_ip_rate_limit", lambda **kwargs: (True, 0))
    org = models.EnterpriseOrganization(company_name="Acme Visas", created_by_user_id=actor.id)
    db.add(org)
    db.flush()
    db.add(models.EnterpriseSubscription(
        organization_id=org.id, plan="sandbox", status="trialing",
        trial_ends_at=datetime.utcnow() + timedelta(days=14),
    ))
    db.commit()
    app = FastAPI()
    app.include_router(admin.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_console_user] = lambda: actor
    with TestClient(app) as client:
        yield SimpleNamespace(db=db, client=client, org_id=org.id)
    db.close()
    engine.dispose()


def _offline(c, **overrides):
    body = {
        "plan": "growth", "billing_cycle": "monthly",
        "amount_minor": billing.checkout_quote("growth", "INR")["total_minor"],
        "currency": "INR", "reference": "UTR0001", "provider": "bank_transfer",
    }
    body.update(overrides)
    return c.client.post(f"{ACCOUNTS}/{c.org_id}/offline-payment", json=body)


def test_offline_payment_note_is_stored_and_shown_in_details(admin_ctx):
    res = _offline(admin_ctx, note="  Deal agreed on the 20 Oct demo call; UTR from HDFC advice.  ")
    assert res.status_code == 200, res.text
    assert res.json()["payment"]["note"] == "Deal agreed on the 20 Oct demo call; UTR from HDFC advice."
    admin_ctx.db.expire_all()
    row = admin_ctx.db.query(models.EnterpriseSubscriptionPayment).one()
    assert row.note == "Deal agreed on the 20 Oct demo call; UTR from HDFC advice."
    details = admin_ctx.client.get(f"{ACCOUNTS}/{admin_ctx.org_id}/details").json()
    assert details["plan_payments"][0]["note"] == row.note


def test_offline_payment_without_a_note_stores_none(admin_ctx):
    assert _offline(admin_ctx, reference="UTR0002", note="   ").status_code == 200
    admin_ctx.db.expire_all()
    assert admin_ctx.db.query(models.EnterpriseSubscriptionPayment).one().note is None


def test_offline_payment_note_length_is_still_capped(admin_ctx):
    res = _offline(admin_ctx, reference="UTR0003", note="x" * (admin.ADMIN_NOTE_MAX + 1))
    assert res.status_code == 400
    assert admin_ctx.db.query(models.EnterpriseSubscriptionPayment).count() == 0


# ---------------------------------------------------------------------------
# Schema patch: the note column lands idempotently on a legacy database
# ---------------------------------------------------------------------------

def test_followup_columns_exist_on_the_models():
    tables = {"enterprise_subscription_payments": models.EnterpriseSubscriptionPayment}
    for table, columns in schema_patch._PRICING_V2_FOLLOWUP_COLUMNS.items():
        model_cols = set(tables[table].__table__.columns.keys())
        for col, _ddl in columns:
            assert col in model_cols, f"{table}.{col} patched but missing from the model"


def test_note_column_patch_is_additive_and_idempotent(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    monkeypatch.setattr(schema_patch, "engine", engine)
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE enterprise_subscription_payments (id INTEGER PRIMARY KEY, "
            "organization_id INTEGER, amount_paise INTEGER, razorpay_order_id VARCHAR)"
        ))
        conn.execute(text(
            "INSERT INTO enterprise_subscription_payments (id, organization_id, amount_paise, "
            "razorpay_order_id) VALUES (1, 1, 100, 'order_1')"
        ))
    schema_patch.ensure_enterprise_pricing_v2_columns()
    schema_patch.ensure_enterprise_pricing_v2_columns()   # second run is a no-op
    cols = {c["name"]: c for c in inspect(engine).get_columns("enterprise_subscription_payments")}
    assert "note" in cols and cols["note"]["nullable"] is True
    with engine.connect() as conn:
        assert conn.execute(text("SELECT note FROM enterprise_subscription_payments")).scalar() is None
    engine.dispose()
