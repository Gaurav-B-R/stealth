"""Pricing v2 (2026-10-22), router half: billing, checkout, signup, open files and plan gates.

Each test pins a rule whose failure either costs money or locks a customer out:

  * a yearly buyer handed 13 monthly allowances (5-day first sub-period), or a mandate that
    auto-debits the YEARLY total every month;
  * a coupon above the cap recorded on the invoice at its stored (uncapped) percent;
  * a top-up sold to an org whose AI is paused, or a captured top-up NOT credited;
  * the INR-region rule skipped at checkout (a London office buying the rupee price);
  * the same company taking a second free trial, or a gmail user refused one;
  * close → add → reopen walking past the open-file limit, or a refused reopen that still
    saved half the form;
  * offices / custom roles created on Starter, or EXISTING ones broken by the gate;
  * Closed treated as an open stage (reminders, the journey tracker, the assistant);
  * the public price list disagreeing with checkout, or not cacheable.

sqlite in memory, the real router mounted on a bare FastAPI app, Razorpay faked at
_razorpay_request (nothing leaves the process).
"""

import hashlib
import hmac
import json
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import email_domains
from app import enterprise_access as access
from app import enterprise_ai
from app import enterprise_billing as billing
from app import enterprise_catalog as catalog
from app import enterprise_coupons
from app import enterprise_credits as credits
from app import fx
from app import models
from app import money
from app.auth import get_current_active_user
from app.database import Base, get_db
from app.routers import enterprise
from app.services import enterprise_calendar_reminders as reminders
from app.utils.token_security import hash_token


KEY_SECRET = "test-razorpay-secret"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class FakeRazorpay:
    """Records every gateway call; answers like Razorpay for the paths checkout uses."""

    def __init__(self):
        self.calls = []
        self.payments = {}
        self.orders = {}
        self._n = 0

    def __call__(self, method, path, json_payload=None):
        self.calls.append((method.upper(), path, json_payload))
        self._n += 1
        if path == "/orders":
            return {"id": f"order_TEST{self._n:06d}"}
        if path == "/subscriptions":
            return {"id": f"sub_TEST{self._n:06d}"}
        if path == "/plans":
            return {"id": f"plan_TEST{self._n:06d}"}
        if path.startswith("/payments/"):
            return self.payments[path.rsplit("/", 1)[1]]
        if path.startswith("/orders/"):
            return self.orders[path.rsplit("/", 1)[1]]
        if "/cancel" in path:
            return {"status": "cancelled"}
        raise AssertionError(f"unexpected Razorpay call {method} {path}")

    def paths(self):
        return [p for _, p, _ in self.calls]


@pytest.fixture
def ctx(monkeypatch):
    monkeypatch.setattr(billing, "ENTERPRISE_FREE", False)
    monkeypatch.setattr(billing, "AI_PAUSE_ON_EXPIRY", True)
    monkeypatch.setattr(billing, "GRACE_UNTIL", None)      # post-cutover: limits enforced
    monkeypatch.setattr(billing, "YEARLY_ENABLED", False)
    monkeypatch.setattr(billing, "FILE_LIMIT_GRACE_DAYS", 14)
    monkeypatch.setattr(credits, "ENFORCE", True)
    monkeypatch.setattr(fx, "get_usd_to_inr", lambda force=False: 95.0)
    monkeypatch.setattr(enterprise, "AUTO_RENEW", True)
    monkeypatch.setattr(enterprise, "ENTERPRISE_ONE_TRIAL_PER_DOMAIN", True)
    rate_calls = []
    monkeypatch.setattr(enterprise, "_enforce_rate_limit_or_429", lambda **kw: rate_calls.append(kw))
    monkeypatch.setattr(enterprise, "send_enterprise_welcome_email", lambda **kw: True)
    fake = FakeRazorpay()
    monkeypatch.setattr(enterprise, "_razorpay_request", fake)
    monkeypatch.setattr(enterprise, "_razorpay_enabled", lambda: True)
    monkeypatch.setattr(enterprise, "_razorpay_credentials", lambda: ("rzp_test_key", KEY_SECRET))

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
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
        yield SimpleNamespace(
            client=client, db=db, org=org, owner=owner, rzp=fake, rate_calls=rate_calls,
        )
    db.close()
    engine.dispose()


def set_plan(c, plan="starter", **fields):
    """Put the org on `plan`: paid → active with 20 days left; sandbox → a live trial."""
    db = c.db
    sub = billing.get_or_create_org_subscription(db, c.org.id)
    now = datetime.utcnow()
    if plan == "sandbox":
        values = {"plan": "sandbox", "status": "trialing", "trial_ends_at": now + timedelta(days=10),
                  "current_period_end": None}
    else:
        values = {"plan": plan, "status": "active", "current_period_end": now + timedelta(days=20),
                  "trial_ends_at": now - timedelta(days=40)}
    values.update(fields)
    for key, value in values.items():
        setattr(sub, key, value)
    db.commit()
    return sub


def expire_trial(c):
    return set_plan(c, "sandbox", trial_ends_at=datetime.utcnow() - timedelta(days=1))


def add_client(c, status="new_lead", name="Student One", **fields):
    client = models.EnterpriseClient(
        organization_id=c.org.id, full_name=name, status=status,
        destination_country_code="GB", destination_country_name="United Kingdom",
        visa_type="Student visa", created_by_user_id=c.owner.id, **fields,
    )
    c.db.add(client)
    c.db.commit()
    return client


def add_branch(c, name, *, is_default=False, is_active=True):
    branch = models.EnterpriseBranch(
        organization_id=c.org.id, name=name, is_default=is_default, is_active=is_active,
    )
    c.db.add(branch)
    c.db.commit()
    return branch


def add_coupon(c, code="SAVE50", percent="50", applies_to="all"):
    c.db.add(models.EnterpriseCoupon(
        organization_id=c.org.id, code=code, percent_off=Decimal(percent), is_active=True,
        applies_to=applies_to,
    ))
    c.db.commit()


# ---------------------------------------------------------------------------
# Yearly sub-periods (enterprise_credits._period_start_for)
# ---------------------------------------------------------------------------

START = datetime(2026, 10, 22, 12)


class _Sub(SimpleNamespace):
    pass


def _old_period_start(end, now, period_days=30):
    """The pre-fix algorithm, verbatim, as the monthly oracle."""
    period = timedelta(days=period_days)
    start = end - period
    while start > now:
        start -= period
    while (start + period) <= now and (start + period) < end:
        start += period
    return start


@pytest.fixture
def credit_db(monkeypatch):
    monkeypatch.setattr(billing, "ENTERPRISE_FREE", False)
    monkeypatch.setattr(billing, "GRACE_UNTIL", None)
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    owner = models.User(email="yearly@credits.example", hashed_password="x")
    db.add(owner)
    db.flush()
    org = models.EnterpriseOrganization(company_name="Yearly Co", created_by_user_id=owner.id)
    db.add(org)
    db.commit()
    db.info["org_id"] = org.id
    yield db
    db.close()
    engine.dispose()


def _yearly_sub(db, *, end, payments):
    """A Team subscription ending at `end`, built from `payments` (cycles, oldest first)."""
    org_id = db.info["org_id"]
    for i, cycle in enumerate(payments):
        db.add(models.EnterpriseSubscriptionPayment(
            organization_id=org_id, plan="growth", billing_cycle=cycle, amount_paise=1,
            currency="INR", razorpay_order_id=f"order_y{i}", status="verified",
        ))
    sub = models.EnterpriseSubscription(
        organization_id=org_id, plan="growth", status="active", current_period_end=end,
        trial_ends_at=START - timedelta(days=60), created_at=START - timedelta(days=60),
    )
    db.add(sub)
    db.commit()
    return sub


def test_yearly_coverage_is_cut_into_twelve_subperiods_from_its_start(credit_db):
    sub = _yearly_sub(credit_db, end=START + timedelta(days=365), payments=["yearly"])
    keys = []
    for day in range(0, 365):
        start = credits._period_start_for(sub, "growth", now=START + timedelta(days=day, hours=1))
        if not keys or keys[-1] != start:
            keys.append(start)
    # Twelve allowances a year — not thirteen — and the FIRST one starts the day it was bought
    # and lasts a full 30 days (the old walk-back-from-the-end gave it 5).
    assert len(keys) == 12
    assert keys[0] == START
    assert credits._period_start_for(sub, "growth", now=START + timedelta(days=29, hours=23)) == START
    assert credits._period_start_for(sub, "growth", now=START + timedelta(days=30, hours=1)) == START + timedelta(days=30)
    assert keys[-1] == START + timedelta(days=330)
    # The last sub-period absorbs the 5-day remainder and ends WITH the coverage.
    bounds = credits._period_bounds_for(sub, "growth", now=START + timedelta(days=362))
    assert bounds == (START + timedelta(days=330), START + timedelta(days=365))


def test_yearly_grace_window_after_coverage_grants_no_new_period(credit_db):
    sub = _yearly_sub(credit_db, end=START + timedelta(days=365), payments=["yearly"])
    for day in (365, 366, 367):
        assert credits._period_start_for(sub, "growth", now=START + timedelta(days=day, hours=2)) \
            == START + timedelta(days=330)


def test_early_yearly_renewal_keeps_the_current_subperiod_key(credit_db):
    """Renewing a year 3 days early must not re-key the running sub-period (in the 35-day tail
    the old key reads as elapsed, so a re-key would hand out a 13th allowance)."""
    sub = _yearly_sub(credit_db, end=START + timedelta(days=365), payments=["yearly"])
    now = START + timedelta(days=362)
    before = credits.plan_credits_period_key(sub, "growth", now=now)
    credit_db.add(models.EnterpriseSubscriptionPayment(
        organization_id=credit_db.info["org_id"], plan="growth", billing_cycle="yearly",
        amount_paise=1, currency="INR", razorpay_order_id="order_renew", status="verified",
    ))
    sub.current_period_end = START + timedelta(days=730)
    credit_db.commit()
    assert credits.plan_credits_period_key(sub, "growth", now=now) == before
    # ...and the new year starts its own grid on the day the old coverage ended.
    assert credits._period_start_for(sub, "growth", now=START + timedelta(days=366)) == START + timedelta(days=365)
    assert credits._period_start_for(sub, "growth", now=START + timedelta(days=396)) == START + timedelta(days=395)


def test_yearly_stacked_on_a_running_month_waits_for_that_month_to_end(credit_db):
    end = START + timedelta(days=30 + 365)
    sub = _yearly_sub(credit_db, end=end, payments=["monthly", "yearly"])
    assert credits._period_start_for(sub, "growth", now=START + timedelta(days=20)) == START
    assert credits._period_start_for(sub, "growth", now=START + timedelta(days=31)) == START + timedelta(days=30)
    starts = {
        credits._period_start_for(sub, "growth", now=START + timedelta(days=d, hours=1))
        for d in range(30, 395)
    }
    assert len(starts) == 12


@pytest.mark.parametrize("payments,end_days", [
    ([], 20),                                  # no payment history at all
    (["monthly"], 20),
    (["monthly", "monthly"], 50),              # renewed early once (stacked)
    (["monthly", "monthly", "monthly"], 75),   # stacked twice
    ([], 400),                                 # a long legacy row with no payments
])
def test_monthly_periods_are_unchanged(credit_db, payments, end_days):
    end = START + timedelta(days=end_days)
    sub = _yearly_sub(credit_db, end=end, payments=payments)
    for hour in range(-24 * 40, 24 * (end_days + 4), 7):
        now = START + timedelta(hours=hour)
        assert credits._period_start_for(sub, "growth", now=now) == _old_period_start(end, now), now


def test_period_start_tolerates_unmapped_subscription_objects():
    end = START + timedelta(days=20)
    fake = _Sub(organization_id=1, current_period_end=end, created_at=START)
    assert credits._period_start_for(fake, "growth", now=START) == _old_period_start(end, START)


def test_a_yearly_buyer_receives_exactly_twelve_allowances(credit_db, monkeypatch):
    clock = {"now": START}

    class Fixed(datetime):
        @classmethod
        def utcnow(cls):
            return clock["now"]

    monkeypatch.setattr(billing, "datetime", Fixed)
    monkeypatch.setattr(credits, "datetime", Fixed)
    monkeypatch.setattr(credits, "PLAN_CREDITS_ROLLOVER", False)
    org_id = credit_db.info["org_id"]
    _yearly_sub(credit_db, end=START + timedelta(days=365), payments=["yearly"])
    for day in range(0, 368):
        clock["now"] = START + timedelta(days=day, hours=3)
        credits.sync_plan_credits(credit_db, org_id, commit=True)
    grants = (
        credit_db.query(models.EnterpriseCreditTransaction)
        .filter_by(organization_id=org_id, reference_type="plan_credits", type="bonus")
        .all()
    )
    assert len(grants) == 12
    assert {g.credits for g in grants} == {billing.PLANS["growth"]["included_credits"]}
    state = credits.plan_credits_state(credit_db, org_id)
    assert state["renews_at"] == START + timedelta(days=365)


# ---------------------------------------------------------------------------
# Currency region at the router (delegation to billing.charge_currency_for_org)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("country,hint,geo,expected", [
    ("IN", "USD", None, 409),       # INR region: another currency is refused, not swapped
    ("IN", None, None, "INR"),
    ("NP", None, None, "INR"),
    ("GB", "INR", None, 409),       # outside the region INR is never charged
    ("GB", "GBP", None, "GBP"),     # the hint the portal sends: the currency it displayed
    ("US", "INR", None, 409),
    ("US", "GBP", None, 409),       # nor another country's ladder (D-010: one currency)
    ("US", None, None, "USD"),
    (None, None, "GB", "GBP"),      # no country on file: the request's geo decides
    (None, None, "NP", "INR"),
    (None, None, None, "INR"),      # unknown everywhere: domestic default
])
def test_resolve_charge_currency_applies_the_region_rule(ctx, country, hint, geo, expected):
    ctx.org.country_code = country
    ctx.db.commit()
    request = SimpleNamespace(headers={"cf-ipcountry": geo} if geo else {})
    # The model and the org id form (how billing is called from places without the row).
    for org in (ctx.org, ctx.org.id):
        if expected == 409:
            with pytest.raises(HTTPException) as exc:
                enterprise._resolve_charge_currency(hint, org, db=ctx.db, request=request)
            assert exc.value.status_code == 409
        else:
            assert enterprise._resolve_charge_currency(hint, org, db=ctx.db, request=request) == expected
    if expected != 409:
        assert enterprise._org_charge_currencies(ctx.org, request) == [expected]


def test_coupon_preview_prices_in_the_region_currency(ctx):
    set_plan(ctx, "starter")
    ctx.org.country_code = "AE"
    ctx.db.commit()
    add_coupon(ctx, "TEN", "10")
    body = ctx.client.post(
        "/api/enterprise/coupons/validate",
        json={"code": "TEN", "context": "credits", "package": "starter", "currency": "AED"},
    ).json()
    assert body["currency"] == "AED"
    assert body["base_amount_paise"] == credits.package_price_minor("starter", "AED")
    # Another country's currency is not this workspace's to preview in.
    res = ctx.client.post(
        "/api/enterprise/coupons/validate",
        json={"code": "TEN", "context": "credits", "package": "starter", "currency": "INR"},
    )
    assert res.status_code == 409


def test_resolve_charge_currency_still_refuses_unsupported_hints(ctx):
    with pytest.raises(HTTPException) as exc:
        enterprise._resolve_charge_currency("JPY", ctx.org, db=ctx.db)
    assert exc.value.status_code == 400


# The org's country is owner-editable, so an INR-region claim must agree with where the
# request comes from (ENTERPRISE_INR_REQUIRE_GEO_MATCH, default on).
@pytest.mark.parametrize("country,hint,geo,expected", [
    ("IN", None, "GB", "GBP"),      # a London office that set IN in Settings
    ("IN", "INR", "US", 409),       # ...can't get INR by asking for it
    ("IN", "EUR", "US", 409),       # ...nor another country's ladder: its currency is USD
    ("IN", "USD", "US", "USD"),
    ("NP", None, "JP", "USD"),      # geo country with no ladder of its own → USD
    ("IN", None, None, "INR"),      # geo unknown: the org's country is trusted
    ("IN", None, "IN", "INR"),
    ("IN", "USD", "NP", 409),       # geo inside the region: INR only, as before
    ("GB", "INR", "IN", 409),       # the rule only ever takes INR away, never grants it
    ("GB", None, "IN", "GBP"),
])
def test_inr_needs_the_request_geo_to_agree_with_the_org_country(ctx, country, hint, geo, expected):
    ctx.org.country_code = country
    ctx.db.commit()
    request = SimpleNamespace(headers={"cf-ipcountry": geo} if geo else {})
    if expected == 409:
        with pytest.raises(HTTPException) as exc:
            enterprise._resolve_charge_currency(hint, ctx.org, db=ctx.db, request=request)
        assert exc.value.status_code == 409
    else:
        assert enterprise._resolve_charge_currency(hint, ctx.org, db=ctx.db, request=request) == expected


def test_portal_payloads_carry_only_the_workspaces_one_currency(ctx):
    """D-010 in the signed-in portal: /billing/plans, /credits/wallet and the checkout
    response's wallet all speak the org's ONE currency — no other ladder, no INR infra-fee."""
    set_plan(ctx, "sandbox")
    ctx.org.country_code = "US"
    ctx.db.commit()
    plans = ctx.client.get("/api/enterprise/billing/plans").json()
    assert plans["currency"] == "USD" and plans["charge_currencies"] == ["USD"]
    for card in plans["plans"]:
        assert {o["currency"] for o in card.get("price_options") or []} <= {"USD"}
    wallet = ctx.client.get("/api/enterprise/credits/wallet").json()
    assert wallet["charge_currencies"] == ["USD"]
    infra = wallet["wallet"]["infra_fee"]
    assert [o["currency"] for o in infra["price_options"]] == ["USD"]
    # No rupee display string anywhere a USD workspace's browser receives (D-010). The
    # numeric credit unit (credit_value_inr) stays: the portal converts it for display.
    assert "₹" not in json.dumps(wallet, ensure_ascii=False)
    assert wallet["wallet"]["credit_value_inr"] == 10
    analytics = ctx.client.get("/api/enterprise/credits/analytics").json()
    assert "₹" not in json.dumps(analytics, ensure_ascii=False)
    history = ctx.client.get("/api/enterprise/credits/payments").json()
    assert history["summary"]["collected_display"] == "$0"
    # An INR workspace keeps its rupee strings.
    ctx.org.country_code = "IN"
    ctx.db.commit()
    inr_wallet = ctx.client.get("/api/enterprise/credits/wallet", headers={"CF-IPCountry": "IN"}).json()
    assert inr_wallet["wallet"]["balance_display"].startswith("₹")


def test_display_currency_follows_the_billing_country(ctx):
    """A workspace with no company country on file is displayed in its browsing country's
    currency, the same country billing uses — not rupees (D-010)."""
    ctx.org.country_code = None
    ctx.db.commit()
    request = SimpleNamespace(headers={"cf-ipcountry": "GB"})
    assert enterprise._org_display_currency(ctx.org, request)["code"] == "GBP"
    assert enterprise._org_display_currency(ctx.org, SimpleNamespace(headers={"cf-ipcountry": "IN"}))["code"] == "INR"
    ctx.org.country_code = "IN"     # an INR claim the geo contradicts follows the geo, as billing does
    ctx.db.commit()
    assert enterprise._org_display_currency(ctx.org, request)["code"] == "GBP"


def test_inr_geo_match_kill_switch(ctx, monkeypatch):
    monkeypatch.setattr(billing, "INR_REQUIRE_GEO_MATCH", False)
    ctx.org.country_code = "IN"
    ctx.db.commit()
    request = SimpleNamespace(headers={"cf-ipcountry": "GB"})
    assert enterprise._resolve_charge_currency(None, ctx.org, db=ctx.db, request=request) == "INR"
    with pytest.raises(HTTPException) as exc:
        enterprise._resolve_charge_currency("GBP", ctx.org, db=ctx.db, request=request)
    assert exc.value.status_code == 409


def test_inr_claim_from_abroad_is_quoted_and_charged_in_the_geo_ladder(ctx):
    set_plan(ctx, "sandbox")
    ctx.org.country_code = "IN"
    ctx.org.billing_currency = "INR"
    ctx.db.commit()
    geo = {"CF-IPCountry": "GB"}
    body = ctx.client.get("/api/enterprise/billing/plans", headers=geo).json()
    assert body["currency"] == "GBP" and body["charge_currencies"] == ["GBP"]
    assert body["subscription"]["inr_region"] is False
    assert all(p["currency"] == "GBP" for p in body["plans"])
    # Asking for INR from London is refused outright (not quietly re-priced)...
    refused = ctx.client.post(
        "/api/enterprise/billing/checkout", headers=geo,
        json={"plan": "starter", "billing_cycle": "monthly", "currency": "INR"},
    )
    assert refused.status_code == 409
    assert "billed in GBP" in refused.json()["detail"]
    # ...and the displayed GBP is what checkout charges.
    res = ctx.client.post(
        "/api/enterprise/billing/checkout", headers=geo,
        json={"plan": "starter", "billing_cycle": "monthly", "currency": "GBP"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["currency"] == "GBP"
    assert res.json()["amount"] == billing.checkout_quote("starter", "GBP")["total_minor"]
    assert ctx.client.post(
        "/api/enterprise/credits/topup/checkout", headers=geo, json={"package": "starter", "currency": "INR"},
    ).status_code == 409
    topup = ctx.client.post(
        "/api/enterprise/credits/topup/checkout", headers=geo, json={"package": "starter"},
    )
    assert topup.status_code == 200, topup.text
    assert topup.json()["currency"] == "GBP"
    # The same org from inside India is still an INR customer.
    assert ctx.client.get("/api/enterprise/billing/plans", headers={"CF-IPCountry": "IN"}).json()["currency"] == "INR"


def _verified_plan_payment(c, ref="order_PAID0001"):
    c.db.add(models.EnterpriseSubscriptionPayment(
        organization_id=c.org.id, plan="starter", amount_paise=176_882, currency="INR",
        razorpay_order_id=ref, status="verified", verified_at=datetime.utcnow(),
    ))
    c.db.commit()


def test_owner_can_set_the_country_until_the_first_plan_payment(ctx):
    res = ctx.client.patch("/api/enterprise/organization/branding", json={"country_code": "KE"})
    assert res.status_code == 200, res.text
    assert res.json()["organization"]["country_code"] == "KE"
    assert res.json()["organization"]["billing_country_locked"] is False


def test_owner_cannot_change_the_billing_country_after_paying(ctx):
    _verified_plan_payment(ctx)
    res = ctx.client.patch(
        "/api/enterprise/organization/branding", json={"country_code": "GB", "state_region": "London"},
    )
    assert res.status_code == 400
    assert "Contact support to change your billing country" in res.json()["detail"]
    ctx.db.expire_all()
    org = ctx.db.get(models.EnterpriseOrganization, ctx.org.id)
    assert org.country_code == "IN" and org.state_region is None    # nothing half-applied
    # Clearing it is a change too.
    assert ctx.client.patch("/api/enterprise/organization/branding", json={"country_code": ""}).status_code == 400
    # Saving the location form with the SAME country (it always sends it) still works.
    same = ctx.client.patch(
        "/api/enterprise/organization/branding", json={"country_code": "in", "state_region": "Karnataka"},
    )
    assert same.status_code == 200, same.text
    assert same.json()["organization"]["state_region"] == "Karnataka"
    assert same.json()["organization"]["billing_country_locked"] is True


def test_settings_country_list_covers_the_whole_inr_region():
    # "Other" (XX) means OUTSIDE the INR region, so every region member must be pickable.
    import re
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "static" / "enterprise.js").read_text(encoding="utf-8")
    block = re.search(r"const ORG_COUNTRIES = \[(.*?)\];", source, re.S)
    assert block, "ORG_COUNTRIES moved — update this test"
    codes = set(re.findall(r'\["([A-Z]{2})",', block.group(1)))
    assert set(billing.INR_REGION_COUNTRIES) <= codes, sorted(set(billing.INR_REGION_COUNTRIES) - codes)


def test_topup_checkout_charges_the_region_currency(ctx):
    set_plan(ctx, "starter")
    ctx.org.country_code = "GB"
    ctx.db.commit()
    assert ctx.client.post(
        "/api/enterprise/credits/topup/checkout", json={"package": "starter", "currency": "INR"},
    ).status_code == 409
    res = ctx.client.post("/api/enterprise/credits/topup/checkout", json={"package": "starter", "currency": "GBP"})
    assert res.status_code == 200, res.text
    assert res.json()["currency"] == "GBP"
    order = [p for m, path, p in ctx.rzp.calls if path == "/orders"][-1]
    assert order["currency"] == "GBP"
    wallet = ctx.client.get("/api/enterprise/credits/wallet").json()
    assert wallet["charge_currencies"] == ["GBP"]
    for pack in wallet["packages"]:
        assert [o["currency"] for o in pack["price_options"]] == ["GBP"]


# ---------------------------------------------------------------------------
# Subscription state passthrough + /billing/plans
# ---------------------------------------------------------------------------

NEW_STATE_KEYS = (
    "open_files_used", "max_open_files", "clients_total", "files_over_limit",
    "files_over_limit_since", "files_grace_ends_at", "files_in_grace", "files_grace_days",
    "reads", "monthly_reads", "features", "features_tier", "ai_paused", "ai_paused_reason",
    "ai_paused_message", "yearly_enabled", "yearly_minor", "yearly_display", "yearly_total_minor",
    "yearly_total_display", "branch_packs", "overrides", "trial_bonus_available",
    "trial_bonus_credits", "trial_domain_blocked", "inr_region", "show_usd_estimate",
    "usd_estimate", "price_note", "billing_cycle",
)


def test_serialized_subscription_state_carries_every_v2_key(ctx):
    set_plan(ctx, "growth", branch_packs=1)
    state = billing.build_subscription_state(ctx.db, ctx.org.id)
    out = enterprise._serialize_subscription_state(state)
    missing = [k for k in NEW_STATE_KEYS if k not in out]
    assert not missing
    for key in NEW_STATE_KEYS:
        assert out[key] == state[key], key
    assert out["features"] == {"branches": True, "custom_roles": True, "branch_reporting": True}


def test_serialized_state_works_for_the_free_platform_shape(ctx, monkeypatch):
    monkeypatch.setattr(billing, "ENTERPRISE_FREE", True)
    out = enterprise._serialize_subscription_state(billing.build_subscription_state(ctx.db, ctx.org.id))
    assert out["ai_paused"] is False and out["features"]["branches"] is True
    assert out["price_note"] == ""


def test_billing_plans_attach_a_usd_estimate_only_for_non_indian_inr_region(ctx):
    set_plan(ctx, "starter")
    ctx.org.country_code = "NP"
    ctx.db.commit()
    body = ctx.client.get("/api/enterprise/billing/plans").json()
    assert body["currency"] == "INR"
    assert body["subscription"]["show_usd_estimate"] is True
    paid = [p for p in body["plans"] if not p["is_free"]]
    assert paid and all(p["usd_estimate"] and p["usd_estimate"]["currency"] == "USD" for p in paid)
    assert body["charge_currencies"] == ["INR"]
    assert body["tax"]["percent"] == float(money.tax_percent_for("INR"))

    ctx.org.country_code = "IN"
    ctx.db.commit()
    body = ctx.client.get("/api/enterprise/billing/plans").json()
    assert all(p["usd_estimate"] is None for p in body["plans"])

    ctx.org.country_code = "GB"
    ctx.db.commit()
    body = ctx.client.get("/api/enterprise/billing/subscription").json()
    assert body["currency"] == "GBP" and "INR" not in body["charge_currencies"]


# ---------------------------------------------------------------------------
# Plan checkout: yearly = one-off order, capped coupon, coverage
# ---------------------------------------------------------------------------

def test_monthly_checkout_opens_a_mandate(ctx):
    set_plan(ctx, "sandbox")
    res = ctx.client.post("/api/enterprise/billing/checkout", json={"plan": "starter", "billing_cycle": "monthly"})
    assert res.status_code == 200, res.text
    assert res.json()["checkout_mode"] == "subscription"
    assert "/subscriptions" in ctx.rzp.paths()


def test_yearly_checkout_is_a_one_off_order_never_a_mandate(ctx, monkeypatch):
    monkeypatch.setattr(billing, "YEARLY_ENABLED", True)
    set_plan(ctx, "sandbox")
    res = ctx.client.post("/api/enterprise/billing/checkout", json={"plan": "team", "billing_cycle": "yearly"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["checkout_mode"] == "order" and body["auto_renew"] is False
    assert body["billing_cycle"] == "yearly" and body["period_days"] == 365
    assert "/subscriptions" not in ctx.rzp.paths() and "/plans" not in ctx.rzp.paths()
    quote = billing.checkout_quote("growth", "INR", billing_cycle="yearly")
    assert body["amount"] == quote["total_minor"]
    assert body["original_amount"] == billing.plan_price_minor("growth", "INR", "yearly")
    row = ctx.db.query(models.EnterpriseSubscriptionPayment).filter_by(razorpay_order_id=body["order_id"]).one()
    assert row.billing_cycle == "yearly" and row.razorpay_subscription_id is None
    assert row.amount_paise == quote["total_minor"]


def test_yearly_checkout_refused_while_yearly_is_not_on_sale(ctx):
    set_plan(ctx, "sandbox")
    res = ctx.client.post("/api/enterprise/billing/checkout", json={"plan": "starter", "billing_cycle": "yearly"})
    assert res.status_code == 400
    assert "Yearly" in res.json()["detail"]
    assert ctx.rzp.calls == []
    res = ctx.client.post(
        "/api/enterprise/coupons/validate",
        json={"code": "X", "context": "billing", "plan": "starter", "billing_cycle": "annual"},
    )
    assert res.status_code == 400 and "Yearly" in res.json()["detail"]


def test_checkout_records_the_capped_coupon_percent(ctx, monkeypatch):
    monkeypatch.setattr(enterprise_coupons, "MAX_PERCENT_OFF", Decimal("15"))
    monkeypatch.setattr(enterprise, "AUTO_RENEW", False)
    set_plan(ctx, "sandbox")
    add_coupon(ctx, "LEGACY50", "50")       # saved before the cap existed
    res = ctx.client.post(
        "/api/enterprise/billing/checkout",
        json={"plan": "starter", "billing_cycle": "monthly", "coupon_code": "legacy50"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    cap = enterprise_coupons.max_percent_off()
    assert body["coupon_percent_off"] == float(cap)
    expected = billing.checkout_quote("starter", "INR", discount_percent=cap)
    assert body["amount"] == expected["total_minor"]
    row = ctx.db.query(models.EnterpriseSubscriptionPayment).filter_by(razorpay_order_id=body["order_id"]).one()
    assert Decimal(str(row.coupon_percent_off)) == cap

    preview = ctx.client.post(
        "/api/enterprise/coupons/validate",
        json={"code": "LEGACY50", "context": "billing", "plan": "starter"},
    ).json()
    assert preview["percent_off"] == float(cap)
    assert preview["amount_paise"] == expected["subtotal_minor"]


def _sign(order_id, payment_id):
    return hmac.new(KEY_SECRET.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()


def test_verifying_a_yearly_order_buys_365_days(ctx, monkeypatch):
    monkeypatch.setattr(billing, "YEARLY_ENABLED", True)
    set_plan(ctx, "sandbox")
    body = ctx.client.post("/api/enterprise/billing/checkout", json={"plan": "starter", "billing_cycle": "yearly"}).json()
    # Switched off between checkout and payment: the year that was paid for is still honoured.
    monkeypatch.setattr(billing, "YEARLY_ENABLED", False)
    ctx.rzp.payments["pay_YEARLY0001"] = {
        "amount": body["amount"], "currency": "INR", "order_id": body["order_id"], "captured": True,
    }
    before = datetime.utcnow()
    res = ctx.client.post("/api/enterprise/billing/verify", json={
        "razorpay_order_id": body["order_id"], "razorpay_payment_id": "pay_YEARLY0001",
        "razorpay_signature": _sign(body["order_id"], "pay_YEARLY0001"),
    })
    assert res.status_code == 200, res.text
    ctx.db.expire_all()
    sub = ctx.db.query(models.EnterpriseSubscription).filter_by(organization_id=ctx.org.id).one()
    end = billing._as_naive(sub.current_period_end)
    assert timedelta(days=364, hours=23) < end - before < timedelta(days=365, hours=1)
    assert res.json()["subscription"]["billing_cycle"] == "yearly"
    # Only ONE month of the year's allowance lands now.
    assert res.json()["credits_granted"] == billing.PLANS["starter"]["included_credits"]


def test_webhook_reconcile_of_a_yearly_order_buys_365_days(ctx):
    set_plan(ctx, "sandbox")
    row = models.EnterpriseSubscriptionPayment(
        organization_id=ctx.org.id, plan="starter", billing_cycle="yearly", amount_paise=1_768_820,
        currency="INR", razorpay_order_id="order_WEBHOOKY1", status="created",
    )
    ctx.db.add(row)
    ctx.db.commit()
    before = datetime.utcnow()
    out = enterprise._reconcile_plan_payment(
        ctx.db, plan_row=row,
        entity={"id": "pay_WH1", "amount": 1_768_820, "currency": "INR"}, order_id="order_WEBHOOKY1",
    )
    assert out == {"status": "ok"}
    sub = ctx.db.query(models.EnterpriseSubscription).filter_by(organization_id=ctx.org.id).one()
    assert billing._as_naive(sub.current_period_end) - before > timedelta(days=364)


# ---------------------------------------------------------------------------
# A one-off plan payment replaces a live monthly mandate (no double billing, no re-tier)
# ---------------------------------------------------------------------------

def _sign_mandate(payment_id, subscription_id):
    return hmac.new(KEY_SECRET.encode(), f"{payment_id}|{subscription_id}".encode(), hashlib.sha256).hexdigest()


def _buy_monthly_mandate(c, plan="starter", payment_id="pay_MANDATE0001"):
    """Checkout + browser verify of a monthly mandate; returns its subscription id."""
    body = c.client.post("/api/enterprise/billing/checkout", json={"plan": plan, "billing_cycle": "monthly"}).json()
    assert body["checkout_mode"] == "subscription", body
    sub_id = body["subscription_id"]
    c.rzp.payments[payment_id] = {"amount": body["amount"], "currency": body["currency"], "captured": True}
    res = c.client.post("/api/enterprise/billing/verify", json={
        "razorpay_order_id": sub_id, "razorpay_payment_id": payment_id,
        "razorpay_signature": _sign_mandate(payment_id, sub_id),
    })
    assert res.status_code == 200, res.text
    return sub_id, body["amount"]


def _buy_yearly_order(c, plan="growth", payment_id="pay_YEARLYOVER1"):
    body = c.client.post("/api/enterprise/billing/checkout", json={"plan": plan, "billing_cycle": "yearly"}).json()
    assert body["checkout_mode"] == "order", body
    c.rzp.payments[payment_id] = {
        "amount": body["amount"], "currency": body["currency"], "order_id": body["order_id"], "captured": True,
    }
    return body, c.client.post("/api/enterprise/billing/verify", json={
        "razorpay_order_id": body["order_id"], "razorpay_payment_id": payment_id,
        "razorpay_signature": _sign(body["order_id"], payment_id),
    })


def _sub_row(c):
    c.db.expire_all()
    return c.db.query(models.EnterpriseSubscription).filter_by(organization_id=c.org.id).one()


def _charged_event(subscription_id, payment_id, amount, currency="INR"):
    return {"event": "subscription.charged", "payload": {
        "payment": {"entity": {"id": payment_id, "subscription_id": subscription_id,
                               "amount": amount, "currency": currency}},
        "subscription": {"entity": {"id": subscription_id}},
    }}


def test_yearly_order_cancels_the_live_monthly_mandate(ctx, monkeypatch):
    monkeypatch.setattr(billing, "YEARLY_ENABLED", True)
    set_plan(ctx, "sandbox")
    mandate, _ = _buy_monthly_mandate(ctx, "starter")
    assert _sub_row(ctx).razorpay_subscription_id == mandate

    _, res = _buy_yearly_order(ctx, "growth")
    assert res.status_code == 200, res.text
    assert ("POST", f"/subscriptions/{mandate}/cancel", {"cancel_at_cycle_end": 0}) in ctx.rzp.calls
    state = res.json()["subscription"]
    assert state["plan"] == "growth" and state["billing_cycle"] == "yearly"
    assert state["has_mandate"] is False and state["auto_renews"] is False
    sub = _sub_row(ctx)
    assert sub.razorpay_subscription_id is None and sub.mandate_status == "cancelled"


def test_late_charge_on_the_superseded_mandate_does_not_re_tier_a_paid_year(ctx, monkeypatch):
    monkeypatch.setattr(billing, "YEARLY_ENABLED", True)
    set_plan(ctx, "sandbox")
    mandate, monthly_amount = _buy_monthly_mandate(ctx, "starter")
    _buy_yearly_order(ctx, "growth")
    end_before = billing._as_naive(_sub_row(ctx).current_period_end)
    calls_before = len(ctx.rzp.calls)

    out = enterprise._handle_subscription_charged(
        ctx.db, event=_charged_event(mandate, "pay_STRAY0001", monthly_amount),
    )
    assert out["status"] == "superseded" and out["refund_required"] is True
    sub = _sub_row(ctx)
    assert sub.plan == "growth"                                   # not knocked down to Starter
    assert billing._as_naive(sub.current_period_end) == end_before  # no extra 30 days stacked
    assert sub.razorpay_subscription_id is None
    # The money is on record for a refund, but it is not coverage or the org's cycle.
    stray = ctx.db.query(models.EnterpriseSubscriptionPayment).filter_by(razorpay_payment_id="pay_STRAY0001").one()
    assert stray.status == "superseded" and stray.amount_paise == monthly_amount
    assert billing.build_subscription_state(ctx.db, ctx.org.id)["billing_cycle"] == "yearly"
    # ...and the mandate is cancelled again.
    assert ("POST", f"/subscriptions/{mandate}/cancel", {"cancel_at_cycle_end": 0}) in ctx.rzp.calls[calls_before:]


def test_webhook_reconciled_yearly_order_also_cancels_the_mandate(ctx, monkeypatch):
    monkeypatch.setattr(billing, "YEARLY_ENABLED", True)
    set_plan(ctx, "sandbox")
    mandate, _ = _buy_monthly_mandate(ctx, "starter")
    body = ctx.client.post("/api/enterprise/billing/checkout", json={"plan": "growth", "billing_cycle": "yearly"}).json()
    row = ctx.db.query(models.EnterpriseSubscriptionPayment).filter_by(razorpay_order_id=body["order_id"]).one()
    out = enterprise._reconcile_plan_payment(
        ctx.db, plan_row=row, entity={"id": "pay_WHY0001", "amount": body["amount"], "currency": "INR"},
        order_id=body["order_id"],
    )
    assert out == {"status": "ok"}
    assert f"/subscriptions/{mandate}/cancel" in ctx.rzp.paths()
    sub = _sub_row(ctx)
    assert sub.plan == "growth" and sub.razorpay_subscription_id is None


def test_first_charge_of_a_new_mandate_by_webhook_still_applies_and_replaces_the_old(ctx):
    set_plan(ctx, "sandbox")
    old_mandate, _ = _buy_monthly_mandate(ctx, "starter")
    # Upgrade: a new mandate is opened, and its FIRST charge arrives by webhook before the
    # browser verify (closed tab). It is not a superseded charge — it must apply.
    body = ctx.client.post("/api/enterprise/billing/checkout", json={"plan": "growth", "billing_cycle": "monthly"}).json()
    new_mandate = body["subscription_id"]
    end_before = billing._as_naive(_sub_row(ctx).current_period_end)
    out = enterprise._handle_subscription_charged(
        ctx.db, event=_charged_event(new_mandate, "pay_FIRST0001", body["amount"]),
    )
    assert out["status"] == "ok", out
    sub = _sub_row(ctx)
    assert sub.plan == "growth" and sub.razorpay_subscription_id == new_mandate
    assert billing._as_naive(sub.current_period_end) > end_before
    # The browser verify then finds it already applied — so the old mandate had to be
    # cancelled here, not there.
    assert f"/subscriptions/{old_mandate}/cancel" in ctx.rzp.paths()
    # A renewal on the CURRENT mandate is never mistaken for a superseded one.
    renewal = enterprise._handle_subscription_charged(
        ctx.db, event=_charged_event(new_mandate, "pay_RENEW0001", body["amount"]),
    )
    assert renewal["status"] == "ok"


def test_fully_covered_activation_cancels_a_live_mandate(ctx, monkeypatch):
    set_plan(ctx, "sandbox")
    mandate, _ = _buy_monthly_mandate(ctx, "starter")
    add_coupon(ctx, "COMPTEAM", "100")
    res = ctx.client.post(
        "/api/enterprise/billing/checkout",
        json={"plan": "growth", "billing_cycle": "monthly", "coupon_code": "COMPTEAM"},
    )
    assert res.status_code == 200 and res.json()["action"] == "activated", res.text
    assert f"/subscriptions/{mandate}/cancel" in ctx.rzp.paths()
    assert _sub_row(ctx).razorpay_subscription_id is None


# ---------------------------------------------------------------------------
# No change of tier inside a prepaid yearly term (billing.live_term_lock)
# ---------------------------------------------------------------------------

def _yearly_term(c, plan="starter", days_left=300, order_id="offline:INV-Y1"):
    """An org holding a prepaid yearly term with `days_left` to run (an offline invoice)."""
    sub = set_plan(c, plan, current_period_end=datetime.utcnow() + timedelta(days=days_left))
    c.db.add(models.EnterpriseSubscriptionPayment(
        organization_id=c.org.id, provider="invoice", plan=plan, billing_cycle="yearly",
        amount_paise=1_768_820, currency="INR", razorpay_order_id=order_id, status="verified",
        verified_at=datetime.utcnow() - timedelta(days=365 - days_left),
    ))
    c.db.commit()
    return sub


def test_tier_change_is_refused_inside_a_prepaid_year(ctx):
    _yearly_term(ctx, "starter")
    end_before = billing._as_naive(_sub_row(ctx).current_period_end)
    for plan in ("scale", "growth"):
        res = ctx.client.post("/api/enterprise/billing/checkout", json={"plan": plan, "billing_cycle": "monthly"})
        assert res.status_code == 409, res.text
        assert "paid up to" in res.json()["detail"] and "contact us" in res.json()["detail"]
    assert ctx.rzp.calls == []
    # The coupon preview refuses the same purchase.
    add_coupon(ctx, "TEN", "10")
    preview = ctx.client.post(
        "/api/enterprise/coupons/validate", json={"code": "TEN", "context": "billing", "plan": "scale"},
    )
    assert preview.status_code == 409
    # Renewing the SAME tier early is still allowed and simply stacks a month.
    res = ctx.client.post("/api/enterprise/billing/checkout", json={"plan": "starter", "billing_cycle": "monthly"})
    assert res.status_code == 200, res.text
    assert billing._as_naive(_sub_row(ctx).current_period_end) == end_before   # nothing applied yet
    state = ctx.client.get("/api/enterprise/billing/subscription").json()["subscription"]
    assert state["term_locked_until"] is not None
    assert state["term_locked_until"].startswith(end_before.date().isoformat())


def test_downgrade_inside_a_prepaid_year_is_refused_too(ctx):
    _yearly_term(ctx, "growth")
    res = ctx.client.post("/api/enterprise/billing/checkout", json={"plan": "starter", "billing_cycle": "monthly"})
    assert res.status_code == 409
    assert _sub_row(ctx).plan == "growth"


def test_monthly_orgs_and_the_last_month_of_a_year_can_change_tier(ctx):
    set_plan(ctx, "starter")      # monthly coverage only: no lock
    assert billing.live_term_lock(ctx.db, ctx.org.id) is None
    res = ctx.client.post("/api/enterprise/billing/checkout", json={"plan": "scale", "billing_cycle": "monthly"})
    assert res.status_code == 200, res.text
    assert ctx.client.get("/api/enterprise/billing/subscription").json()["subscription"]["term_locked_until"] is None


def test_last_month_of_a_yearly_term_is_not_locked(ctx):
    _yearly_term(ctx, "starter", days_left=20)
    assert billing.live_term_lock(ctx.db, ctx.org.id) is None
    res = ctx.client.post("/api/enterprise/billing/checkout", json={"plan": "growth", "billing_cycle": "monthly"})
    assert res.status_code == 200, res.text


def test_a_month_stacked_on_a_yearly_term_keeps_the_lock(ctx):
    _yearly_term(ctx, "starter", days_left=200)
    sub = _sub_row(ctx)
    sub.current_period_end = billing._as_naive(sub.current_period_end) + timedelta(days=30)
    ctx.db.add(models.EnterpriseSubscriptionPayment(
        organization_id=ctx.org.id, plan="starter", billing_cycle="monthly", amount_paise=176_882,
        currency="INR", razorpay_order_id="order_STACKED1", status="verified", verified_at=datetime.utcnow(),
    ))
    ctx.db.commit()
    lock = billing.live_term_lock(ctx.db, ctx.org.id)
    assert lock and lock["plan"] == "starter"


def test_fully_covered_yearly_plan_activates_for_a_year(ctx, monkeypatch):
    monkeypatch.setattr(billing, "YEARLY_ENABLED", True)
    set_plan(ctx, "sandbox")
    add_coupon(ctx, "COMP100", "100")
    before = datetime.utcnow()
    res = ctx.client.post(
        "/api/enterprise/billing/checkout",
        json={"plan": "starter", "billing_cycle": "yearly", "coupon_code": "COMP100"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["action"] == "activated"
    assert ctx.rzp.calls == []
    ctx.db.expire_all()
    sub = ctx.db.query(models.EnterpriseSubscription).filter_by(organization_id=ctx.org.id).one()
    assert billing._as_naive(sub.current_period_end) - before > timedelta(days=364)
    row = ctx.db.query(models.EnterpriseSubscriptionPayment).filter_by(organization_id=ctx.org.id).one()
    assert row.billing_cycle == "yearly" and Decimal(str(row.coupon_percent_off)) == Decimal("100")


@pytest.mark.parametrize("country,currency", [("IN", "INR"), ("GB", "GBP")])
def test_hundred_percent_code_restores_an_expired_trial_without_a_gateway(ctx, monkeypatch, country, currency):
    """The default discount range covers the entire plan, including GST, in any region."""
    ctx.org.country_code = country
    ctx.db.commit()
    expire_trial(ctx)
    add_coupon(ctx, "COMP100", "100", "billing")
    monkeypatch.setattr(enterprise, "_razorpay_enabled", lambda: False)
    before = datetime.utcnow()

    preview = ctx.client.post("/api/enterprise/coupons/validate", json={
        "code": "comp100", "context": "billing", "plan": "starter", "currency": currency,
    })
    assert preview.status_code == 200, preview.text
    assert preview.json()["percent_off"] == 100
    assert preview.json()["free"] is True
    assert preview.json()["amount_paise"] == 0
    assert preview.json()["currency"] == currency

    response = ctx.client.post("/api/enterprise/billing/checkout", json={
        "plan": "starter", "billing_cycle": "monthly", "coupon_code": "comp100", "currency": currency,
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["action"] == "activated" and body["free"] is True
    assert body["subscription"]["plan"] == "starter"
    assert body["subscription"]["ai_paused"] is False
    assert ctx.rzp.calls == []
    ctx.db.expire_all()
    sub = _sub_row(ctx)
    assert sub.status == "active" and sub.razorpay_subscription_id is None
    assert billing._as_naive(sub.current_period_end) - before > timedelta(days=29)
    payment = ctx.db.query(models.EnterpriseSubscriptionPayment).filter_by(organization_id=ctx.org.id).one()
    assert payment.status == "verified" and payment.currency == currency
    assert (payment.amount_paise, payment.subtotal_paise, payment.tax_paise, payment.base_amount_paise) == (0, 0, 0, 0)
    assert payment.original_amount_paise == billing.plan_price_minor("starter", currency, "monthly")
    assert payment.coupon_code == "COMP100" and payment.coupon_percent_off == Decimal("100")
    assert enterprise_coupons.redemptions_used(ctx.db, ctx.org.id, "COMP100") == 1
    wallet = ctx.db.query(models.EnterpriseCreditWallet).filter_by(organization_id=ctx.org.id).one()
    assert wallet.plan_credits_remaining == billing.get_plan("starter")["included_credits"]


@pytest.mark.parametrize("first_context,second_context", [("billing", "credits"), ("credits", "billing")])
def test_free_redemptions_share_the_limit_between_plans_and_topups(ctx, monkeypatch, first_context, second_context):
    set_plan(ctx, "starter")
    add_coupon(ctx, "ONCE100", "100")
    coupon = ctx.db.query(models.EnterpriseCoupon).filter_by(organization_id=ctx.org.id, code="ONCE100").one()
    coupon.max_redemptions = 1
    ctx.db.commit()
    monkeypatch.setattr(enterprise, "_razorpay_enabled", lambda: False)
    purchases = {
        "billing": ("/api/enterprise/billing/checkout", {"plan": "starter", "coupon_code": "ONCE100"}, "activated"),
        "credits": ("/api/enterprise/credits/topup/checkout", {"package": "starter", "coupon_code": "ONCE100"}, "granted"),
    }
    endpoint, payload, action = purchases[first_context]
    first = ctx.client.post(endpoint, json=payload)
    assert first.status_code == 200 and first.json()["action"] == action, first.text
    assert enterprise_coupons.redemptions_used(ctx.db, ctx.org.id, "ONCE100") == 1

    preview = ctx.client.post("/api/enterprise/coupons/validate", json={
        "code": "ONCE100", "context": second_context, "plan": "starter", "package": "starter",
    })
    assert preview.status_code == 400 and "redemption limit" in preview.json()["detail"]
    endpoint, payload, _ = purchases[second_context]
    second = ctx.client.post(endpoint, json=payload)
    assert second.status_code == 400 and "redemption limit" in second.json()["detail"]
    assert enterprise_coupons.redemptions_used(ctx.db, ctx.org.id, "ONCE100") == 1
    assert ctx.rzp.calls == []


@pytest.mark.parametrize("restriction,expected", [
    ("other_account", "Invalid discount code for this account"),
    ("inactive", "no longer active"),
    ("credits_only", "only applies to credit top-ups"),
])
def test_full_discount_preserves_account_activation_and_scope_guards(ctx, restriction, expected):
    expire_trial(ctx)
    coupon_org_id = ctx.org.id
    if restriction == "other_account":
        other = models.EnterpriseOrganization(company_name="Other", subdomain_slug="other", created_by_user_id=ctx.owner.id)
        ctx.db.add(other)
        ctx.db.flush()
        coupon_org_id = other.id
    ctx.db.add(models.EnterpriseCoupon(
        organization_id=coupon_org_id, code="RESTRICTED100", percent_off=Decimal("100"),
        is_active=restriction != "inactive", applies_to="credits" if restriction == "credits_only" else "all",
    ))
    ctx.db.commit()
    for endpoint, payload in [
        ("/api/enterprise/coupons/validate", {"code": "RESTRICTED100", "context": "billing", "plan": "starter"}),
        ("/api/enterprise/billing/checkout", {"coupon_code": "RESTRICTED100", "plan": "starter"}),
    ]:
        response = ctx.client.post(endpoint, json=payload)
        assert response.status_code == 400 and expected in response.json()["detail"], response.text
    assert ctx.db.query(models.EnterpriseSubscriptionPayment).count() == 0
    assert _sub_row(ctx).plan == "sandbox"
    assert ctx.rzp.calls == []


def test_payment_history_labels_the_cycle(ctx):
    set_plan(ctx, "starter")
    ctx.db.add(models.EnterpriseSubscriptionPayment(
        organization_id=ctx.org.id, plan="starter", billing_cycle="yearly", amount_paise=100,
        currency="INR", razorpay_order_id="order_HIST1", status="verified", verified_at=datetime.utcnow(),
    ))
    ctx.db.commit()
    rows = ctx.client.get("/api/enterprise/credits/payments").json()["payments"]
    plan_rows = [r for r in rows if r["kind"] == "plan"]
    assert plan_rows[0]["label"].endswith("· yearly") and plan_rows[0]["billing_cycle"] == "yearly"


# ---------------------------------------------------------------------------
# Credit top-ups while AI is paused
# ---------------------------------------------------------------------------

def test_topup_checkout_refused_while_ai_is_paused(ctx):
    expire_trial(ctx)
    res = ctx.client.post("/api/enterprise/credits/topup/checkout", json={"package": "starter"})
    assert res.status_code == 402
    assert res.json()["detail"] == billing.AI_PAUSED_TRIAL_MESSAGE
    assert ctx.rzp.calls == []
    wallet = ctx.client.get("/api/enterprise/credits/wallet").json()
    assert wallet["topup_allowed"] is False


def test_topup_checkout_allowed_on_a_live_trial(ctx):
    set_plan(ctx, "sandbox")
    res = ctx.client.post("/api/enterprise/credits/topup/checkout", json={"package": "starter"})
    assert res.status_code == 200, res.text
    assert res.json()["action"] == "checkout"


def test_already_captured_topup_is_credited_even_while_paused(ctx):
    expire_trial(ctx)
    ctx.db.add(models.EnterpriseCreditPayment(
        organization_id=ctx.org.id, provider="razorpay", kind="credits", package_key="starter",
        credits=100, bonus_credits=0, amount_paise=99_900, currency="INR",
        razorpay_order_id="order_PAUSED01", status="created",
    ))
    ctx.db.commit()
    ctx.rzp.payments["pay_PAUSED01"] = {
        "amount": 99_900, "currency": "INR", "order_id": "order_PAUSED01", "captured": True,
        "status": "captured",
    }
    ctx.rzp.orders["order_PAUSED01"] = {
        "id": "order_PAUSED01", "status": "paid", "amount": 99_900, "currency": "INR",
    }
    res = ctx.client.post("/api/enterprise/credits/topup/verify", json={
        "razorpay_order_id": "order_PAUSED01", "razorpay_payment_id": "pay_PAUSED01",
        "razorpay_signature": _sign("order_PAUSED01", "pay_PAUSED01"),
    })
    assert res.status_code == 200, res.text
    wallet = ctx.db.query(models.EnterpriseCreditWallet).filter_by(organization_id=ctx.org.id).one()
    assert wallet.balance_credits >= 100


def test_topup_records_the_capped_coupon_percent(ctx, monkeypatch):
    monkeypatch.setattr(enterprise_coupons, "MAX_PERCENT_OFF", Decimal("15"))
    set_plan(ctx, "starter")
    add_coupon(ctx, "BIG40", "40")
    body = ctx.client.post(
        "/api/enterprise/credits/topup/checkout", json={"package": "starter", "coupon_code": "BIG40"},
    ).json()
    cap = enterprise_coupons.max_percent_off()
    assert body["coupon_percent_off"] == float(cap)
    row = ctx.db.query(models.EnterpriseCreditPayment).filter_by(razorpay_order_id=body["order_id"]).one()
    assert Decimal(str(row.coupon_percent_off)) == cap


# ---------------------------------------------------------------------------
# One trial per company email domain
# ---------------------------------------------------------------------------

def _signup(c, email, slug):
    c.db.add(models.EnterpriseSignupOtp(
        email=email, code_hash=hash_token("123456"),
        expires_at=datetime.utcnow() + timedelta(minutes=10),
    ))
    c.db.commit()
    return c.client.post("/api/enterprise/signup", json={
        "company_name": f"Company {slug}", "subdomain_slug": slug, "full_name": "New Owner",
        "email": email, "password": "Strong-Test-Password9!", "accepted_terms_privacy": True,
        "accepted_dpa": True, "email_otp": "123456",
    })


def _org_by_slug(c, slug):
    c.db.expire_all()
    return c.db.query(models.EnterpriseOrganization).filter_by(subdomain_slug=slug).one()


def test_second_workspace_on_a_company_domain_gets_no_trial(ctx):
    # The fixture org's owner is owner@acme-consult.example — the domain has had its trial.
    res = _signup(ctx, "second@acme-consult.example", "acme-second")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["trial_domain_blocked"] is True
    assert body["message"] == enterprise.ENTERPRISE_TRIAL_DOMAIN_BLOCKED_MESSAGE
    assert body["subscription"]["trial_domain_blocked"] is True
    org = _org_by_slug(ctx, "acme-second")
    sub = ctx.db.query(models.EnterpriseSubscription).filter_by(organization_id=org.id).one()
    assert sub.trial_domain_blocked is True
    assert billing._as_naive(sub.trial_ends_at) <= datetime.utcnow()
    wallet = ctx.db.query(models.EnterpriseCreditWallet).filter_by(organization_id=org.id).one()
    assert wallet.plan_credits_once_at is not None
    credits.sync_plan_credits(ctx.db, org.id)
    ctx.db.expire_all()
    wallet = ctx.db.query(models.EnterpriseCreditWallet).filter_by(organization_id=org.id).one()
    assert wallet.balance_credits == 0 and int(wallet.reads_granted or 0) == 0
    state = billing.ai_access_state(ctx.db, org.id)
    assert state["allowed"] is False and state["message"] == billing.AI_PAUSED_DOMAIN_MESSAGE


def test_domain_rule_matches_any_member_case_insensitively(ctx):
    colleague = models.User(email="Former.Staff@Widget-Agency.example", hashed_password="x",
                            last_login_at=datetime.utcnow() - timedelta(days=90))
    ctx.db.add(colleague)
    ctx.db.flush()
    ctx.db.add(models.EnterpriseOrganizationMember(
        organization_id=ctx.org.id, user_id=colleague.id, role_key="viewer", role="viewer",
        is_active=False,   # offboarded — still counts
    ))
    ctx.db.commit()
    assert _signup(ctx, "boss@widget-agency.example", "widget-new").json()["trial_domain_blocked"] is True


def _invite_then_remove(c, monkeypatch, email):
    monkeypatch.setattr(enterprise, "send_enterprise_team_invite_email", lambda **kw: True)
    res = c.client.post("/api/enterprise/team/users", json={"email": email, "role": "viewer"})
    assert res.status_code == 200, res.text
    user = c.db.query(models.User).filter_by(email=email).one()
    assert c.client.delete(f"/api/enterprise/team/users/{user.id}").status_code == 200
    return user


def test_an_invite_alone_cannot_use_up_another_companys_trial(ctx, monkeypatch):
    # Any workspace can type any address into "Add user". That row proves nothing about the
    # invitee's company, so it must not deny that company its trial.
    set_plan(ctx, "sandbox")
    _invite_then_remove(ctx, monkeypatch, "nobody@victim-agency.example")
    res = _signup(ctx, "founder@victim-agency.example", "victim")
    assert res.status_code == 200, res.text
    assert res.json()["trial_domain_blocked"] is False
    assert res.json()["subscription"]["ai_paused"] is False


def test_an_invited_member_who_signed_in_does_count(ctx, monkeypatch):
    set_plan(ctx, "sandbox")
    user = _invite_then_remove(ctx, monkeypatch, "staff@used-agency.example")
    user.last_login_at = datetime.utcnow() - timedelta(days=3)
    ctx.db.commit()
    assert _signup(ctx, "founder@used-agency.example", "used").json()["trial_domain_blocked"] is True
    # Using the portal (membership.last_active_at) is the same evidence.
    other = _invite_then_remove(ctx, monkeypatch, "staff@active-agency.example")
    membership = ctx.db.query(models.EnterpriseOrganizationMember).filter_by(user_id=other.id).one()
    membership.last_active_at = datetime.utcnow()
    ctx.db.commit()
    assert enterprise._company_domain_already_trialled(ctx.db, "active-agency.example") is True


@pytest.mark.parametrize("email", [
    "someone@gmail.com", "someone@yahoo.co.in", "someone@outlook.de", "someone@proton.me",
])
def test_free_mailbox_signups_always_get_a_trial(ctx, email):
    first = _signup(ctx, email, "free-first")
    assert first.status_code == 200, first.text
    local, _, domain = email.partition("@")
    second = _signup(ctx, f"other.{local}@{domain}", "free-second")
    assert second.status_code == 200, second.text
    assert second.json()["trial_domain_blocked"] is False
    assert second.json()["message"] is None
    org = _org_by_slug(ctx, "free-second")
    assert billing.ai_access_state(ctx.db, org.id)["allowed"] is True


def test_first_workspace_on_a_new_company_domain_gets_its_trial(ctx):
    res = _signup(ctx, "founder@brand-new-agency.example", "brand-new")
    assert res.status_code == 200, res.text
    assert res.json()["trial_domain_blocked"] is False
    assert res.json()["subscription"]["ai_paused"] is False


def test_domain_rule_kill_switch(ctx, monkeypatch):
    monkeypatch.setattr(enterprise, "ENTERPRISE_ONE_TRIAL_PER_DOMAIN", False)
    assert _signup(ctx, "again@acme-consult.example", "acme-again").json()["trial_domain_blocked"] is False


def test_domain_like_pattern_cannot_be_widened(ctx):
    # "_" is a LIKE wildcard: a_me.example must not match acme.example's members.
    assert enterprise._company_domain_already_trialled(ctx.db, "acme_consult.example") is False
    assert enterprise._company_domain_already_trialled(ctx.db, "acme-consult.example") is True


@pytest.mark.parametrize("email,expected", [
    ("a@gmail.com", None), ("a@GoogleMail.com", None), ("a@hotmail.co.uk", None),
    ("a@yahoo.com.br", None), ("a@live.in", None), ("a@rediffmail.com", None),
    ("a@zoho.com", None), ("a@icloud.com", None), ("a@mail.com", None),
    ("a@acme.co.uk", "acme.co.uk"), ("a@Studyabroad.IN", "studyabroad.in"),
    ("a@live.acme.com", "live.acme.com"), ("a@outlook.example.in", "outlook.example.in"),
    ("a@mailinator.com", "mailinator.com"),   # disposable is NOT a free mailbox here
    ("not-an-email", None), ("a@@b.com", None), ("", None),
])
def test_company_domain_classification(email, expected):
    assert email_domains.company_domain(email) == expected


def test_free_mail_extra_domains_from_env(monkeypatch):
    monkeypatch.setenv("ENTERPRISE_FREE_MAIL_DOMAINS_EXTRA", "corp-mail.example, @other.example")
    assert email_domains.company_domain("x@corp-mail.example") is None
    assert email_domains.company_domain("x@other.example") is None
    assert email_domains.like_suffix_pattern("a_b%c.com") == "%@a\\_b\\%c.com"


# ---------------------------------------------------------------------------
# Open files: reopen is an add; closing frees the grace stamp
# ---------------------------------------------------------------------------

def _at_limit(c, limit=2, grace_days=0, monkeypatch=None):
    if monkeypatch is not None:
        monkeypatch.setattr(billing, "FILE_LIMIT_GRACE_DAYS", grace_days)
    set_plan(c, "starter", override_max_clients=limit)
    for i in range(limit):
        add_client(c, "documents", name=f"Open {i}")


@pytest.mark.parametrize("from_status", ["closed", "approved", "rejected", "on_hold"])
def test_reopening_a_file_past_the_limit_is_refused(ctx, monkeypatch, from_status):
    _at_limit(ctx, monkeypatch=monkeypatch)
    done = add_client(ctx, from_status, name="Finished")
    res = ctx.client.patch(f"/api/enterprise/clients/{done.id}/status", json={"status": "documents"})
    assert res.status_code == 402, res.text
    assert "open files" in res.json()["detail"]
    ctx.db.expire_all()
    assert ctx.db.get(models.EnterpriseClient, done.id).status == from_status


def test_moves_that_do_not_reopen_are_never_limited(ctx, monkeypatch):
    _at_limit(ctx, monkeypatch=monkeypatch)
    done = add_client(ctx, "approved", name="Finished")
    assert ctx.client.patch(f"/api/enterprise/clients/{done.id}/status", json={"status": "closed"}).status_code == 200
    open_one = ctx.db.query(models.EnterpriseClient).filter_by(status="documents").first()
    assert ctx.client.patch(f"/api/enterprise/clients/{open_one.id}/status", json={"status": "submitted"}).status_code == 200
    assert ctx.client.patch(f"/api/enterprise/clients/{open_one.id}/status", json={"status": "closed"}).status_code == 200
    # One slot freed → the reopen now fits.
    assert ctx.client.patch(f"/api/enterprise/clients/{done.id}/status", json={"status": "documents"}).status_code == 200


def test_refused_reopen_through_edit_saves_nothing(ctx, monkeypatch):
    _at_limit(ctx, monkeypatch=monkeypatch)
    done = add_client(ctx, "closed", name="Finished File")
    res = ctx.client.patch(
        f"/api/enterprise/clients/{done.id}",
        json={"status": "documents", "full_name": "Renamed In Same Save", "phone": "+44 7911 123456"},
    )
    assert res.status_code == 402, res.text
    ctx.db.expire_all()
    row = ctx.db.get(models.EnterpriseClient, done.id)
    assert row.status == "closed" and row.full_name == "Finished File" and row.phone is None


def test_reopen_inside_the_grace_window_stamps_the_clock(ctx, monkeypatch):
    _at_limit(ctx, grace_days=14, monkeypatch=monkeypatch)
    done = add_client(ctx, "closed", name="Finished")
    res = ctx.client.patch(f"/api/enterprise/clients/{done.id}/status", json={"status": "documents"})
    assert res.status_code == 200, res.text
    ctx.db.expire_all()
    sub = ctx.db.query(models.EnterpriseSubscription).filter_by(organization_id=ctx.org.id).one()
    assert sub.files_over_limit_since is not None
    # Closing a file brings the org back to its limit and clears the stamp.
    res = ctx.client.patch(f"/api/enterprise/clients/{done.id}/status", json={"status": "closed"})
    assert res.status_code == 200
    ctx.db.expire_all()
    assert ctx.db.query(models.EnterpriseSubscription).filter_by(organization_id=ctx.org.id).one().files_over_limit_since is None


def test_deleting_an_open_file_clears_a_stale_stamp(ctx, monkeypatch):
    _at_limit(ctx, grace_days=14, monkeypatch=monkeypatch)
    extra = add_client(ctx, "documents", name="Over")
    sub = ctx.db.query(models.EnterpriseSubscription).filter_by(organization_id=ctx.org.id).one()
    sub.files_over_limit_since = datetime.utcnow() - timedelta(days=3)
    ctx.db.commit()
    assert ctx.client.delete(f"/api/enterprise/clients/{extra.id}").status_code == 200
    ctx.db.expire_all()
    assert ctx.db.query(models.EnterpriseSubscription).filter_by(organization_id=ctx.org.id).one().files_over_limit_since is None


def test_reopen_on_an_expired_trial_is_refused(ctx):
    expire_trial(ctx)
    done = add_client(ctx, "closed", name="Finished")
    res = ctx.client.patch(f"/api/enterprise/clients/{done.id}/status", json={"status": "new_lead"})
    assert res.status_code == 402


# ---------------------------------------------------------------------------
# Closed is terminal everywhere
# ---------------------------------------------------------------------------

def test_closed_sits_off_the_linear_journey_like_a_refusal(ctx):
    client = add_client(ctx, "closed", name="Closed File")
    linear = enterprise._linear_stage_keys(client)
    assert catalog.STAGE_CLOSED not in linear and catalog.STAGE_REJECTED not in linear
    assert catalog.STAGE_APPROVED in linear
    # Nothing after the furthest stage it reached counts as "passed over".
    import json as _json
    client.stage_visits = _json.dumps({"from": "new_lead", "visits": {"new_lead": None, "shortlisting": None}})
    assert enterprise._stages_behind(client, "closed", None) == ["new_lead", "shortlisting"]


def test_closed_files_drop_out_of_calendar_and_reminders(ctx):
    set_plan(ctx, "starter")
    today = datetime.utcnow().date()
    add_client(ctx, "closed", name="Closed Deadline", target_date=today)
    add_client(ctx, "documents", name="Open Deadline", target_date=today)
    events = enterprise._collect_calendar_events(
        ctx.db, ctx.org.id, today - timedelta(days=1), today + timedelta(days=1), today=today,
    )
    names = {e.get("client_name") for e in events if e.get("type") == "client_deadline"}
    assert names == {"Open Deadline"}
    by_recipient = reminders._collect_org_items_by_recipient(ctx.db, ctx.org.id, today, today - timedelta(days=7))
    reminded = {item.get("client_name") for items in by_recipient.values() for item in items}
    assert "Open Deadline" in reminded and "Closed Deadline" not in reminded


def test_assistant_groups_closed_with_closed_and_paused():
    assert enterprise_ai._stage_phase(catalog.STAGE_CLOSED) == "Closed / paused"
    assert enterprise_ai._stage_phase(catalog.STAGE_ON_HOLD) == "Closed / paused"
    assert enterprise_ai._stage_phase(catalog.STAGE_APPROVED) == "Closed / paused"
    source = open(enterprise_ai.__file__).read()
    assert "[catalog.STAGE_APPROVED, catalog.STAGE_REJECTED]" not in source
    assert "{catalog.STAGE_APPROVED, catalog.STAGE_REJECTED}" not in source


# ---------------------------------------------------------------------------
# Feature gates: offices, custom roles, per-branch reporting
# ---------------------------------------------------------------------------

TEAM_LABEL = billing.PLANS["growth"]["label"]


def test_starter_can_create_its_first_office_but_not_a_second(ctx):
    set_plan(ctx, "starter")
    first = ctx.client.post("/api/enterprise/branches", json={"name": "Head Office"})
    assert first.status_code == 200, first.text
    second = ctx.client.post("/api/enterprise/branches", json={"name": "Second Office"})
    assert second.status_code == 402
    assert TEAM_LABEL in second.json()["detail"]
    assert ctx.db.query(models.EnterpriseBranch).filter_by(organization_id=ctx.org.id).count() == 1


def test_starter_keeps_editing_its_default_office_only(ctx):
    set_plan(ctx, "starter")
    head = add_branch(ctx, "Head Office", is_default=True)
    other = add_branch(ctx, "Legacy Branch")   # left over from a Team period
    ok = ctx.client.patch(f"/api/enterprise/branches/{head.id}", json={"city": "Pune", "timezone": "Asia/Kolkata"})
    assert ok.status_code == 200, ok.text
    for res in (
        ctx.client.patch(f"/api/enterprise/branches/{other.id}", json={"city": "Delhi"}),
        ctx.client.post(f"/api/enterprise/branches/{other.id}/set-default"),
        ctx.client.post(f"/api/enterprise/branches/{other.id}/archive", json={}),
    ):
        assert res.status_code == 402, res.text
    archived = add_branch(ctx, "Archived Branch", is_active=False)
    assert ctx.client.post(f"/api/enterprise/branches/{archived.id}/reactivate").status_code == 402
    # Reads are never gated.
    assert ctx.client.get(f"/api/enterprise/branches/{other.id}/members").status_code == 200


def test_team_and_live_trial_manage_offices_freely(ctx):
    set_plan(ctx, "growth")
    add_branch(ctx, "Head Office", is_default=True)
    assert ctx.client.post("/api/enterprise/branches", json={"name": "Branch Two"}).status_code == 200
    set_plan(ctx, "sandbox")
    assert ctx.client.post("/api/enterprise/branches", json={"name": "Branch Three"}).status_code == 200
    expire_trial(ctx)
    assert ctx.client.post("/api/enterprise/branches", json={"name": "Branch Four"}).status_code == 402


def test_custom_roles_are_gated_on_starter_but_existing_ones_keep_working(ctx):
    set_plan(ctx, "growth")
    created = ctx.client.post("/api/enterprise/roles", json={
        "name": "Front desk", "capabilities": ["clients.view"], "data_scope": "all",
    })
    assert created.status_code == 200, created.text
    role_id = created.json()["role"]["id"]

    set_plan(ctx, "starter")
    for res in (
        ctx.client.post("/api/enterprise/roles", json={"name": "Another", "capabilities": ["clients.view"]}),
        ctx.client.patch(f"/api/enterprise/roles/{role_id}", json={"name": "Renamed"}),
        ctx.client.post(f"/api/enterprise/roles/{role_id}/duplicate", json={"name": "Copy"}),
        ctx.client.post(f"/api/enterprise/roles/{role_id}/archive", json={}),
    ):
        assert res.status_code == 402, res.text
        assert TEAM_LABEL in res.json()["detail"]
    # Listing is a read.
    roles = ctx.client.get("/api/enterprise/roles").json()
    assert any(r["id"] == role_id for r in roles.get("custom_roles", []))


def _add_member(c, email="staff@acme-consult.example", role_key="counsellor", **fields):
    user = models.User(email=email, hashed_password="x", full_name="Staff", is_active=True)
    c.db.add(user)
    c.db.flush()
    c.db.add(models.EnterpriseOrganizationMember(
        organization_id=c.org.id, user_id=user.id, role_key=role_key, role="editor",
        is_active=True, **fields,
    ))
    c.db.commit()
    return user


def test_individual_permission_overrides_need_team_but_can_always_be_removed(ctx):
    set_plan(ctx, "starter")
    import json as _json
    staff = _add_member(ctx, capability_grants_json=_json.dumps(["finance.view"]))
    add = ctx.client.patch(
        f"/api/enterprise/team/users/{staff.id}/access",
        json={"capability_grants": ["finance.view", "documents.download"]},
    )
    assert add.status_code == 402, add.text
    remove = ctx.client.patch(
        f"/api/enterprise/team/users/{staff.id}/access", json={"capability_grants": []},
    )
    assert remove.status_code == 200, remove.text
    # Plain preset changes are not a custom role.
    preset = ctx.client.patch(
        f"/api/enterprise/team/users/{staff.id}/access", json={"role_key": "viewer"},
    )
    assert preset.status_code == 200, preset.text


def test_per_branch_reporting_is_a_team_feature(ctx):
    set_plan(ctx, "starter")
    head = add_branch(ctx, "Head Office", is_default=True)
    res = ctx.client.get(f"/api/enterprise/dashboard?branch_id={head.id}")
    assert res.status_code == 402 and TEAM_LABEL in res.json()["detail"]
    assert ctx.client.get(f"/api/enterprise/clients?branch_id={head.id}").status_code == 402
    # The unfiltered views are never gated.
    assert ctx.client.get("/api/enterprise/clients").status_code == 200
    assert ctx.client.get("/api/enterprise/dashboard").status_code == 200
    set_plan(ctx, "growth")
    assert ctx.client.get(f"/api/enterprise/clients?branch_id={head.id}").status_code == 200
    assert ctx.client.get(f"/api/enterprise/dashboard?branch_id={head.id}").status_code == 200


# ---------------------------------------------------------------------------
# Public price list
# ---------------------------------------------------------------------------

def test_public_plans_is_anonymous_cacheable_and_rate_limited(ctx):
    anon = TestClient(ctx.client.app)
    ctx.client.app.dependency_overrides.pop(get_current_active_user)
    res = anon.get("/api/enterprise/public/plans", headers={"cf-ipcountry": "IN"})
    assert res.status_code == 200, res.text
    assert res.headers["cache-control"] == "public, max-age=300"
    assert "CF-IPCountry" in res.headers["vary"]
    assert ctx.rate_calls and ctx.rate_calls[-1]["scope"] == "enterprise.public_plans"
    body = res.json()
    assert body["currency"] == "INR"
    for key in ("plans", "actions", "packages", "trial", "branch_pack", "file_grace_days",
                "yearly_enabled", "currencies", "tax"):
        assert key in body, key
    assert body["tax"] == {
        "percent": float(money.tax_percent_for("INR")),
        "label": money.tax_label_for("INR"), "note": money.tax_note("INR"),
    }
    assert [p["key"] for p in body["plans"]] == billing.PLAN_ORDER
    starter = next(p for p in body["plans"] if p["key"] == "starter")
    assert starter["monthly_minor"] == billing.plan_price_minor("starter", "INR")
    assert body["trial"] == billing.trial_facts()
    assert body["branch_pack"] == billing.branch_pack_facts()
    assert body["file_grace_days"] == billing.FILE_LIMIT_GRACE_DAYS
    assert body["actions"] == credits.actions_payload()
    assert body["packages"] == credits.packages_payload("INR")
    # India's region is priced in INR only: no other ladder anywhere in the response.
    assert body["currencies"] == ["INR"]
    assert "all_currencies" not in body
    for row in body["plans"] + body["packages"]:
        assert {o["currency"] for o in row.get("price_options") or []} <= {"INR"}


@pytest.mark.parametrize("geo,hint,currency,usd", [
    ("NP", "USD", "INR", True),    # INR region: INR whatever is asked, with a US$ estimate
    ("IN", None, "INR", False),
    ("GB", "INR", "GBP", False),   # never INR outside the region
    ("US", "EUR", "USD", False),   # a hint is ignored: a visitor sees their own country's only
    ("GB", None, "GBP", False),
    ("IN", "USD", "INR", False),   # never the foreign ladder inside the region
    (None, "JPY", "USD", False),   # unsupported hint ignored, not a 400
    (None, "INR", "USD", False),   # an unknown country is never quoted the INR ladder
    (None, None, "USD", False),
])
def test_public_plans_region_rule(ctx, geo, hint, currency, usd):
    headers = {"cf-ipcountry": geo} if geo else {}
    url = "/api/enterprise/public/plans" + (f"?currency={hint}" if hint else "")
    body = ctx.client.get(url, headers=headers).json()
    assert body["currency"] == currency
    assert body["show_usd_estimate"] is usd
    paid = [p for p in body["plans"] if not p["is_free"]]
    assert all(p["currency"] == currency for p in body["plans"])
    assert all((p["usd_estimate"] is not None) is usd for p in paid)
    if hint == "JPY":
        assert body["requested_currency_supported"] is False
    # One currency per visitor: their own, and nothing else listed.
    assert body["currencies"] == [currency]
    # One region's prices only, anywhere in the response — not even unrendered in a ladder.
    for row in body["plans"] + body["packages"]:
        assert {o["currency"] for o in row.get("price_options") or []} <= set(body["currencies"])
    if currency != "INR":
        assert "₹" not in json.dumps(body, ensure_ascii=False)
        assert all("price_inr" not in a and "price_display" not in a for a in body["actions"])
        assert all("value_inr" not in p for p in body["packages"])


def test_public_plans_reports_tax_zero_without_inventing_gst(ctx, monkeypatch):
    monkeypatch.setattr(money, "GST_PERCENT", Decimal(0))
    body = ctx.client.get("/api/enterprise/public/plans").json()
    assert body["tax"] == {"percent": 0.0, "label": None, "note": ""}
    starter = next(p for p in body["plans"] if p["key"] == "starter")
    assert starter["total_minor"] == starter["monthly_minor"]


def test_team_meta_reports_plan_features_for_the_editors(ctx):
    set_plan(ctx, "starter")
    meta = ctx.client.get("/api/enterprise/team/meta").json()
    assert meta["plan_features"] == {"branches": False, "custom_roles": False, "branch_reporting": False}
    assert TEAM_LABEL in meta["plan_upgrade_messages"]["branches"]
    set_plan(ctx, "growth")
    meta = ctx.client.get("/api/enterprise/team/meta").json()
    assert all(meta["plan_features"].values())
