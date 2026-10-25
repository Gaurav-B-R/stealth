"""The 2026-10-22 B2B pricing model: plan catalog, open files + grace, effective limits,
tier features, the shared AI-paused gate, the currency-region rule, yearly billing, the
coupon discounts and the schema patch.

Each test pins a rule whose failure costs money or locks a customer out: an expired trial
that keeps spending AI, an org outside India buying at the INR price, a close→add→reopen
loophole, a fully covered purchase failing to activate, a lapsed org keeping its Branch Packs.
"""

from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from app import enterprise_billing as billing
from app import enterprise_catalog as catalog
from app import enterprise_coupons as coupons
from app import enterprise_credits as credits
from app import fx
from app import models
from app import money
from app import schema_patch
from app.database import Base


START = datetime(2026, 10, 22, 12)
_clock = {"now": START}


class FixedDatetime(datetime):
    @classmethod
    def utcnow(cls):
        return _clock["now"]


def advance(days: float) -> None:
    _clock["now"] = _clock["now"] + timedelta(days=days)


@pytest.fixture
def db(monkeypatch):
    _clock["now"] = START
    monkeypatch.setattr(billing, "datetime", FixedDatetime)
    monkeypatch.setattr(credits, "datetime", FixedDatetime)
    monkeypatch.setattr(billing, "ENTERPRISE_FREE", False)
    monkeypatch.setattr(billing, "AI_PAUSE_ON_EXPIRY", True)
    monkeypatch.setattr(billing, "FILE_LIMIT_GRACE_DAYS", 14)
    monkeypatch.setattr(billing, "YEARLY_ENABLED", False)
    # Grandfathering ramp off: these orgs are post-cutover customers.
    monkeypatch.setattr(billing, "GRACE_UNTIL", None)
    monkeypatch.setattr(fx, "get_usd_to_inr", lambda force=False: 95.0)
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    owner = models.User(email="owner@agency.example", hashed_password="test-only")
    session.add(owner)
    session.flush()
    org = models.EnterpriseOrganization(
        company_name="Plans v2", created_by_user_id=owner.id, created_at=START,
    )
    session.add(org)
    session.commit()
    session.info["org_id"] = org.id
    session.info["owner_id"] = owner.id
    yield session
    session.close()
    engine.dispose()


def _sub(db, **fields) -> models.EnterpriseSubscription:
    org_id = db.info["org_id"]
    sub = db.query(models.EnterpriseSubscription).filter_by(organization_id=org_id).first()
    if sub is None:
        sub = models.EnterpriseSubscription(
            organization_id=org_id, plan="sandbox", status="trialing",
            trial_ends_at=START + timedelta(days=14), created_at=START,
        )
        db.add(sub)
    for key, value in fields.items():
        setattr(sub, key, value)
    db.commit()
    return sub


def _paid(db, plan="starter", **fields):
    values = {
        "plan": plan, "status": "active",
        "current_period_end": _clock["now"] + timedelta(days=20),
        "trial_ends_at": START - timedelta(days=30),
    }
    values.update(fields)
    return _sub(db, **values)


def _client(db, status="new_lead"):
    row = models.EnterpriseClient(
        organization_id=db.info["org_id"], full_name="Student", status=status,
        destination_country_code="GB", destination_country_name="United Kingdom",
        visa_type="Student visa", created_by_user_id=db.info["owner_id"],
    )
    db.add(row)
    db.commit()
    return row


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

def test_catalog_matches_the_owner_approved_card():
    expect = {
        #            label                seats files credits reads tier
        "sandbox": ("14-day free trial",  3,   15,   50,     50,   "team"),
        "starter": ("Starter",            5,   40,   150,    150,  "starter"),
        "growth":  ("Team",               25,  150,  450,    500,  "team"),
        "scale":   ("Multi-branch",       50,  500,  1_200,  1_000, "team"),
    }
    for key, (label, seats, files, creds, reads, tier) in expect.items():
        plan = billing.PLANS[key]
        assert plan["label"] == label
        assert plan["max_seats"] == seats
        assert plan["max_clients"] == files
        assert plan["included_credits"] == creds
        assert plan["max_reads"] == reads
        assert plan["features_tier"] == tier
    assert billing.PLANS["growth"]["is_popular"] is True
    assert billing.PLANS["sandbox"]["credits_recur"] is False
    assert billing.TRIAL_DEMO_BONUS_CREDITS == 50


def test_feature_bullets_come_from_constants_and_never_hardcode_tax():
    for key, plan in billing.PLANS.items():
        text_ = " | ".join(plan["features"])
        assert f"{plan['max_seats']:,} staff seats" in text_
        assert f"{plan['max_clients']:,} open student files" in text_
        assert f"{plan['included_credits']:,} AI credits" in text_
        assert f"{plan['max_reads']:,} AI document reads" in text_
        assert "GST" not in text_, f"{key} feature copy hardcodes tax wording"
        assert "priority" not in text_.lower(), "no code backs a support-SLA claim"
    assert any("Multiple offices" in f for f in billing.PLANS["growth"]["features"])
    assert not any("Multiple offices" in f for f in billing.PLANS["starter"]["features"])


@pytest.mark.parametrize("raw,expected", [
    ("team", "growth"), ("Team", "growth"), ("multi_branch", "scale"),
    ("multibranch", "scale"), ("Multi-branch", "scale"), ("multi branch", "scale"),
    ("trial", "sandbox"), ("free", "sandbox"), ("starter", "starter"),
    ("enterprise", "sandbox"), (None, "sandbox"),
])
def test_plan_aliases(raw, expected):
    assert billing.normalize_plan_key(raw) == expected


def test_get_plan_resolves_aliases_but_rejects_junk():
    assert billing.get_plan("team")["key"] == "growth"
    assert billing.get_plan("multi-branch")["key"] == "scale"
    assert billing.get_plan("enterprise") is None
    assert billing.get_plan("") is None


# ---------------------------------------------------------------------------
# The Closed stage and what counts as an open file
# ---------------------------------------------------------------------------

def test_closed_stage_is_terminal_not_open_and_ordered_after_rejected():
    closed = catalog.CLIENT_STAGE_MAP[catalog.STAGE_CLOSED]
    assert closed["label"] == "Closed"
    assert closed["is_open"] is False and closed["is_terminal"] is True
    assert "doesn't count" in closed["description"]
    assert closed["order"] > catalog.CLIENT_STAGE_MAP[catalog.STAGE_REJECTED]["order"]
    # on_hold kept its (not-open) status.
    assert catalog.CLIENT_STAGE_MAP[catalog.STAGE_ON_HOLD]["is_open"] is False
    assert catalog.NOT_OPEN_STAGE_KEYS == {"approved", "rejected", "closed", "on_hold"}
    assert catalog.TERMINAL_STAGE_KEYS == {"approved", "rejected", "closed"}
    # Every destination still resolves a unique order with the new stage in place.
    for code in catalog.COUNTRY_MAP:
        orders = [s["order"] for s in catalog.stages_for(code)]
        assert len(orders) == len(set(orders))


def test_reopen_detection():
    assert catalog.is_reopen("closed", "documents") is True
    assert catalog.is_reopen("approved", "new_lead") is True
    assert catalog.is_reopen("on_hold", "submitted") is True
    assert catalog.is_reopen("documents", "closed") is False
    assert catalog.is_reopen("new_lead", "documents") is False
    assert catalog.is_reopen("rejected", "closed") is False


def test_open_client_count_skips_finished_and_paused_files(db):
    org_id = db.info["org_id"]
    for status in ("new_lead", "documents", "submitted", "approved", "rejected", "closed", "on_hold"):
        _client(db, status)
    # An unknown legacy value reads as new_lead everywhere else, so it must count as open.
    _client(db, "documents_pending")
    assert billing.open_client_count(db, org_id) == 4
    assert billing.active_client_count(db, org_id) == 4
    assert billing.total_client_count(db, org_id) == 8
    state = billing.build_subscription_state(db, org_id)
    assert state["clients_used"] == state["open_files_used"] == 4
    assert state["clients_total"] == 8


# ---------------------------------------------------------------------------
# Open-file grace
# ---------------------------------------------------------------------------

def test_over_limit_add_starts_a_grace_clock_then_blocks_after_it(db):
    org_id = db.info["org_id"]
    sub = _paid(db, "starter", override_max_clients=2)
    _client(db)
    _client(db)
    # At the limit: the next add is allowed and starts the clock.
    billing.enforce_client_limit_or_402(db, org_id)
    assert sub.files_over_limit_since == START
    _client(db)  # the add itself commits the stamp
    state = billing.build_subscription_state(db, org_id)
    assert state["files_over_limit"] is True
    assert state["files_over_limit_since"] == START
    assert state["files_grace_ends_at"] == START + timedelta(days=14)
    assert state["files_in_grace"] is True
    assert state["can_add_client"] is True

    advance(13)
    billing.enforce_client_limit_or_402(db, org_id)  # still inside the grace
    _client(db)

    advance(2)  # day 15
    with pytest.raises(HTTPException) as exc:
        billing.enforce_client_limit_or_402(db, org_id)
    assert exc.value.status_code == 402
    assert "covers 2 open files" in exc.value.detail
    assert "Closed" in exc.value.detail
    assert billing.build_subscription_state(db, org_id)["can_add_client"] is False


def test_reopen_is_an_add_and_back_under_the_limit_clears_the_stamp(db):
    org_id = db.info["org_id"]
    sub = _paid(db, "starter", override_max_clients=2)
    a, b = _client(db), _client(db)
    billing.enforce_client_limit_or_402(db, org_id)
    c = _client(db)
    advance(15)
    # Close one: back AT the limit. Reopening it (an add of 1) would go over again.
    c.status = "closed"
    db.commit()
    # Not over right now, so the old stamp is stale: this add starts a NEW window.
    billing.enforce_client_limit_or_402(db, org_id, adding=1)
    assert sub.files_over_limit_since == _clock["now"]
    # Close two more: an add that lands at/below the limit clears the stamp.
    a.status, b.status = "approved", "closed"
    db.commit()
    billing.enforce_client_limit_or_402(db, org_id, adding=1)
    assert sub.files_over_limit_since is None


def test_zero_grace_is_a_hard_cap(db, monkeypatch):
    monkeypatch.setattr(billing, "FILE_LIMIT_GRACE_DAYS", 0)
    org_id = db.info["org_id"]
    _paid(db, "starter", override_max_clients=1)
    billing.enforce_client_limit_or_402(db, org_id)  # 0 -> 1 is fine
    _client(db)
    with pytest.raises(HTTPException) as exc:
        billing.enforce_client_limit_or_402(db, org_id)
    assert exc.value.status_code == 402
    assert "grace" not in exc.value.detail


def test_adding_zero_is_a_no_op_and_expired_trial_blocks_adds(db):
    org_id = db.info["org_id"]
    _sub(db, trial_ends_at=START - timedelta(days=1))
    billing.enforce_client_limit_or_402(db, org_id, adding=0)
    with pytest.raises(HTTPException) as exc:
        billing.enforce_client_limit_or_402(db, org_id)
    assert exc.value.status_code == 402
    assert "free trial has ended" in exc.value.detail


def test_refresh_clears_a_stale_stamp_once_under(db):
    org_id = db.info["org_id"]
    sub = _paid(db, "starter", override_max_clients=1, files_over_limit_since=START)
    billing.refresh_files_over_limit(db, org_id)
    assert sub.files_over_limit_since is None


# ---------------------------------------------------------------------------
# Effective limits: overrides + Branch Packs
# ---------------------------------------------------------------------------

def test_overrides_replace_and_packs_add_on_top(db):
    org_id = db.info["org_id"]
    _paid(db, "scale", branch_packs=2, override_max_seats=60, override_monthly_reads=1_500)
    limits = billing.effective_limits(db, org_id)
    assert limits["max_seats"] == 60 + 2 * billing.BRANCH_PACK_SEATS
    assert limits["max_clients"] == 500 + 2 * billing.BRANCH_PACK_FILES
    assert limits["included_credits"] == 1_200 + 2 * billing.BRANCH_PACK_CREDITS
    assert limits["monthly_reads"] == 1_500 + 2 * billing.BRANCH_PACK_READS
    state = billing.build_subscription_state(db, org_id)
    assert state["max_clients"] == limits["max_clients"]
    assert state["included_credits"] == limits["included_credits"]
    assert state["monthly_reads"] == limits["monthly_reads"]
    assert state["branch_packs"] == 2
    assert state["overrides"]["max_seats"] == 60
    assert state["overrides"]["max_clients"] is None


def test_a_lapsed_org_falls_back_to_bare_sandbox_numbers(db):
    org_id = db.info["org_id"]
    _paid(db, "scale", branch_packs=3, override_max_clients=900)
    advance(30)  # period end + grace passed
    limits = billing.effective_limits(db, org_id)
    sandbox = billing.PLANS["sandbox"]
    assert limits["plan"] == "sandbox"
    assert limits["max_clients"] == sandbox["max_clients"]
    assert limits["max_seats"] == sandbox["max_seats"]
    assert limits["branch_packs"] == 0


def test_packs_do_not_apply_to_a_trial_but_overrides_do(db):
    org_id = db.info["org_id"]
    _sub(db, branch_packs=5, override_max_clients=30)
    limits = billing.effective_limits(db, org_id)
    assert limits["max_clients"] == 30
    assert limits["max_seats"] == billing.PLANS["sandbox"]["max_seats"]


def test_effective_limits_never_create_rows_and_free_mode_is_unlimited(db, monkeypatch):
    org_id = db.info["org_id"]
    assert billing.effective_limits(db, org_id)["max_clients"] == 15
    assert db.query(models.EnterpriseSubscription).count() == 0
    monkeypatch.setattr(billing, "ENTERPRISE_FREE", True)
    limits = billing.effective_limits(db, org_id)
    assert limits["max_clients"] == billing.UNLIMITED
    assert limits["monthly_reads"] == billing.UNLIMITED


# ---------------------------------------------------------------------------
# Tier features (offices, roles, branch reporting)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("plan,expected", [("starter", False), ("growth", True), ("scale", True)])
def test_features_follow_the_tier(db, plan, expected):
    org_id = db.info["org_id"]
    _paid(db, plan)
    for feature in billing.FEATURE_KEYS:
        assert billing.has_feature(db, org_id, feature) is expected
    assert billing.build_subscription_state(db, org_id)["features"] == {
        f: expected for f in billing.FEATURE_KEYS
    }


def test_live_trial_gets_team_features_expired_trial_does_not(db):
    org_id = db.info["org_id"]
    _sub(db)
    assert billing.has_feature(db, org_id, "branches") is True
    advance(15)
    assert billing.has_feature(db, org_id, "branches") is False
    with pytest.raises(HTTPException) as exc:
        billing.enforce_feature_or_402(db, org_id, "custom_roles")
    assert exc.value.status_code == 402
    assert "Team plan" in exc.value.detail


def test_lapsed_team_org_loses_features_and_unknown_feature_is_a_bug(db, monkeypatch):
    org_id = db.info["org_id"]
    _paid(db, "growth")
    advance(30)
    assert billing.has_feature(db, org_id, "branch_reporting") is False
    with pytest.raises(ValueError):
        billing.has_feature(db, org_id, "brnaches")
    monkeypatch.setattr(billing, "ENTERPRISE_FREE", True)
    assert billing.has_feature(db, org_id, "branches") is True


# ---------------------------------------------------------------------------
# The shared AI-paused gate
# ---------------------------------------------------------------------------

def test_expired_trial_pauses_ai_with_the_spec_message(db):
    org_id = db.info["org_id"]
    _sub(db)
    assert billing.ai_access_state(db, org_id)["allowed"] is True
    billing.enforce_ai_access_or_402(db, org_id)
    advance(15)
    state = billing.ai_access_state(db, org_id)
    assert state == {
        "allowed": False,
        "reason": "trial_expired",
        "message": (
            "Your free trial has ended — AI features are paused. Choose a plan to turn them "
            "back on. Everything in your workspace is still here."
        ),
    }
    with pytest.raises(HTTPException) as exc:
        billing.enforce_ai_access_or_402(db, org_id)
    assert exc.value.status_code == 402
    with pytest.raises(HTTPException) as exc:
        billing.enforce_ai_access_or_402(db, org_id, client_facing=True)
    assert "contact your consultancy" in exc.value.detail
    sub_state = billing.build_subscription_state(db, org_id)
    assert sub_state["ai_paused"] is True
    assert sub_state["ai_paused_reason"] == "trial_expired"


def test_lapsed_paid_plan_pauses_ai_and_naming_the_plan(db):
    org_id = db.info["org_id"]
    _paid(db, "growth")
    assert billing.ai_access_state(db, org_id)["allowed"] is True
    advance(22)  # period end (20d) + 3d grace not yet passed
    assert billing.ai_access_state(db, org_id)["allowed"] is True
    advance(2)
    state = billing.ai_access_state(db, org_id)
    assert state["allowed"] is False
    assert state["reason"] == "plan_lapsed"
    assert state["message"].startswith("Your Team plan has expired")


def test_cancelled_status_pauses_ai_even_inside_the_period(db):
    org_id = db.info["org_id"]
    _paid(db, "starter", status="canceled")
    assert billing.ai_access_state(db, org_id)["reason"] == "plan_lapsed"


def test_domain_blocked_org_is_paused_from_day_one(db):
    org_id = db.info["org_id"]
    _sub(db, trial_ends_at=START, trial_domain_blocked=True)
    advance(0.001)
    state = billing.ai_access_state(db, org_id)
    assert state["reason"] == "trial_expired"
    assert "already used its free trial" in state["message"]
    sub_state = billing.build_subscription_state(db, org_id)
    assert sub_state["trial_domain_blocked"] is True
    assert sub_state["trial_bonus_available"] is False


def test_ai_gate_kill_switches(db, monkeypatch):
    org_id = db.info["org_id"]
    _sub(db, trial_ends_at=START - timedelta(days=1))
    monkeypatch.setattr(billing, "AI_PAUSE_ON_EXPIRY", False)
    assert billing.ai_access_state(db, org_id)["allowed"] is True
    monkeypatch.setattr(billing, "AI_PAUSE_ON_EXPIRY", True)
    monkeypatch.setattr(billing, "ENTERPRISE_FREE", True)
    assert billing.ai_access_state(db, org_id)["allowed"] is True


def test_ai_access_state_never_writes(db):
    org_id = db.info["org_id"]
    billing.ai_access_state(db, org_id)
    assert db.query(models.EnterpriseSubscription).count() == 0


# ---------------------------------------------------------------------------
# Currency regions
# ---------------------------------------------------------------------------

def _org(**fields):
    return SimpleNamespace(country_code=None, billing_currency=None, **fields)


@pytest.mark.parametrize("country,stored,expected", [
    ("IN", None, "INR"),
    ("NP", "USD", "INR"),           # INR region: a stored non-INR currency doesn't stand
    ("KE", None, "INR"),
    ("GB", None, "GBP"),
    ("GB", "INR", "GBP"),           # outside the region INR is never sold, even if stored
    ("US", "GBP", "USD"),           # a stored choice from the old selector doesn't pin it
    ("DE", None, "EUR"),
    ("US", None, "USD"),
    ("JP", None, "USD"),            # JPY isn't chargeable -> USD
    ("BR", None, "USD"),            # no ladder currency for the country -> USD
    (None, None, "INR"),            # unknown country: the domestic default stands
])
def test_charge_currency_for_org(db, country, stored, expected):
    """ONE currency per workspace (D-010): its own. A hint may only confirm it."""
    org = _org()
    org.country_code, org.billing_currency = country, stored
    assert billing.charge_currency_for_org(db, org, None) == expected
    assert billing.charge_currency_for_org(db, org, expected) == expected
    for other in money.supported_charge_currencies():
        if other == expected:
            continue
        with pytest.raises(HTTPException) as exc:
            billing.charge_currency_for_org(db, org, other)
        assert exc.value.status_code == 409, (country, other)
        assert f"billed in {expected}" in exc.value.detail


def test_a_running_plan_pins_its_currency_and_the_quote_agrees(db):
    """own_currency (D-010): a workspace is billed in the currency its RUNNING plan was bought
    in (billed_currency_pin), else its country's — and the subscription quote (the
    current-plan line) decides the same way as checkout, so one page never shows two. A
    stale stored choice, an abandoned checkout, a refunded or a long-lapsed plan pin nothing."""
    org = db.get(models.EnterpriseOrganization, db.info["org_id"])
    org.country_code, org.billing_currency = "US", "GBP"
    sub = billing.get_or_create_org_subscription(db, org.id)
    sub.plan, sub.status = "starter", "active"
    sub.current_period_end = START + timedelta(days=20)
    db.commit()
    # Only a stale stored choice: USD, its country's.
    assert billing.charge_currency_for_org(db, org, None) == "USD"
    # An abandoned GBP checkout (status 'created') changes nothing either.
    db.add(models.EnterpriseSubscriptionPayment(
        organization_id=org.id, plan="starter", amount_paise=2900, currency="GBP",
        razorpay_order_id="order_abandoned", status="created",
    ))
    db.commit()
    assert billing.charge_currency_for_org(db, org, None) == "USD"
    # A verified GBP plan payment (made under the old selector) for the RUNNING plan pins GBP.
    db.add(models.EnterpriseSubscriptionPayment(
        organization_id=org.id, plan="starter", amount_paise=2900, currency="GBP",
        razorpay_order_id="order_paid_gbp", status="verified",
    ))
    db.commit()
    assert billing.charge_currency_for_org(db, org, None) == "GBP"
    assert billing.charge_currency_for_org(None, org, None) == "GBP"   # session from the row
    assert billing.build_subscription_state(db, org.id)["currency"] == "GBP"
    # Once that plan has lapsed (no live mandate), the workspace is back on its own country's.
    sub.current_period_end = START - timedelta(days=400)
    db.commit()
    assert billing.charge_currency_for_org(db, org, None) == "USD"
    assert billing.build_subscription_state(db, org.id)["currency"] == "USD"
    # ...unless a live mandate is still charging it.
    sub.razorpay_subscription_id, sub.mandate_status = "sub_live", "active"
    db.commit()
    assert billing.charge_currency_for_org(db, org, None) == "GBP"
    sub.mandate_status = "cancelled"
    db.commit()
    assert billing.charge_currency_for_org(db, org, None) == "USD"
    # A fully refunded payment pins nothing, even while the period runs.
    sub.current_period_end = START + timedelta(days=20)
    db.query(models.EnterpriseSubscriptionPayment).filter_by(razorpay_order_id="order_paid_gbp").update({"status": "refunded"})
    db.commit()
    assert billing.charge_currency_for_org(db, org, None) == "USD"
    # ...and it is always clamped to the region: a verified INR payment can't follow an office abroad.
    org.country_code = "GB"
    db.add(models.EnterpriseSubscriptionPayment(
        organization_id=org.id, plan="starter", amount_paise=149900, currency="INR",
        razorpay_order_id="order_paid_inr", status="verified",
    ))
    db.commit()
    assert billing.charge_currency_for_org(db, org, None) == "GBP"


def test_charge_currency_uses_geo_header_when_country_unknown(db):
    request = SimpleNamespace(headers={"cf-ipcountry": "GB"})
    assert billing.charge_currency_for_org(db, _org(), None, request=request) == "GBP"
    with pytest.raises(HTTPException) as exc:
        billing.charge_currency_for_org(db, _org(), "INR", request=request)
    assert exc.value.status_code == 409
    request = SimpleNamespace(headers={"cf-ipcountry": "LK"})
    assert billing.charge_currency_for_org(db, _org(), None, request=request) == "INR"
    with pytest.raises(HTTPException):
        billing.charge_currency_for_org(db, _org(), "USD", request=request)
    # The org's own country beats the visitor's location...
    org = _org()
    org.country_code = "GB"
    assert billing.charge_currency_for_org(db, org, None, request=SimpleNamespace(
        headers={"cf-ipcountry": "IN"})) == "GBP"
    # ...except an INR-region claim the visitor's (known) location contradicts: the country
    # is owner-editable, so "IN" set from London buys at GBP (ENTERPRISE_INR_REQUIRE_GEO_MATCH).
    org.country_code = "IN"
    assert billing.charge_currency_for_org(db, org, None, request=SimpleNamespace(
        headers={"cf-ipcountry": "GB"})) == "GBP"
    assert billing.charge_currency_for_org(db, org, None, request=SimpleNamespace(
        headers={"cf-ipcountry": "NP"})) == "INR"
    assert billing.charge_currency_for_org(db, org, None, request=SimpleNamespace(headers={})) == "INR"


def test_charge_currency_rejects_unsupported_hints_and_accepts_an_org_id(db):
    with pytest.raises(HTTPException) as exc:
        billing.charge_currency_for_org(db, _org(), "JPY")
    assert exc.value.status_code == 400
    org = db.get(models.EnterpriseOrganization, db.info["org_id"])
    org.country_code = "GB"
    db.commit()
    assert billing.charge_currency_for_org(db, db.info["org_id"], None) == "GBP"


def test_inr_region_env_parsing_always_keeps_india(monkeypatch):
    monkeypatch.setenv("ENTERPRISE_INR_REGION_COUNTRIES", "np, bd ;xx1")
    codes = billing._country_set_env("ENTERPRISE_INR_REGION_COUNTRIES", ("IN",))
    assert codes == {"IN", "NP", "BD"}
    assert billing.INR_REGION_COUNTRIES == {"IN", "NP", "BD", "LK", "NG", "GH", "KE"}


def test_subscription_quote_follows_the_region_and_estimates_usd(db):
    org_id = db.info["org_id"]
    org = db.get(models.EnterpriseOrganization, org_id)
    org.country_code, org.billing_currency = "NP", "USD"
    _paid(db, "starter")
    state = billing.build_subscription_state(db, org_id)
    assert state["currency"] == "INR"
    assert state["inr_region"] is True and state["show_usd_estimate"] is True
    # ₹1,499 (+ tax at the live rate) / 95 rounded to whole dollars.
    total = state["total_minor"]
    expected = int((Decimal(total) / 100 / Decimal(95)).quantize(Decimal("1"))) * 100
    assert state["usd_estimate"]["monthly_minor"] == expected
    assert state["usd_estimate"]["monthly_display"].startswith("≈ US$")

    org.country_code = "IN"
    db.commit()
    state = billing.build_subscription_state(db, org_id)
    assert state["usd_estimate"] is None and state["show_usd_estimate"] is False

    org.country_code, org.billing_currency = "GB", "INR"
    db.commit()
    state = billing.build_subscription_state(db, org_id)
    assert state["currency"] == "GBP" and state["inr_region"] is False


# ---------------------------------------------------------------------------
# Yearly billing
# ---------------------------------------------------------------------------

def test_yearly_is_gated_but_priced(monkeypatch):
    assert billing.normalize_billing_cycle("yearly") == "monthly"
    assert billing.normalize_billing_cycle("annual") == "monthly"
    monkeypatch.setattr(billing, "YEARLY_ENABLED", True)
    monkeypatch.setattr(billing, "ENTERPRISE_FREE", False)
    assert billing.yearly_enabled() is True
    assert billing.normalize_billing_cycle("yearly") == "yearly"
    assert billing.normalize_billing_cycle("Annual") == "yearly"
    assert billing.normalize_billing_cycle("monthly") == "monthly"
    assert billing.normalize_billing_cycle(None) == "monthly"


def test_period_days_for_is_not_gated():
    # A yearly order verified after yearly was switched off still gets its year.
    assert billing.period_days_for("yearly") == 365
    assert billing.period_days_for("monthly") == billing.PLAN_PERIOD_DAYS == 30
    assert billing.period_days_for(None) == 30


def test_yearly_checkout_quote():
    quote = billing.checkout_quote("growth", "INR", billing_cycle="yearly")
    assert quote["list_minor"] == 3_999_000
    assert quote["billing_cycle"] == "yearly"
    assert quote["period_days"] == 365
    assert quote["total_minor"] == quote["subtotal_minor"] + quote["tax_minor"]
    usd = billing.checkout_quote("growth", "USD", billing_cycle="yearly")
    assert usd["list_minor"] == 89_000 and usd["tax_minor"] == 0


def test_public_payload_yearly_fields_and_legacy_gate(monkeypatch):
    monkeypatch.setattr(billing, "ENTERPRISE_FREE", False)
    monkeypatch.setattr(billing, "YEARLY_ENABLED", False)
    cards = {c["key"]: c for c in billing.public_plans_payload("INR")}
    starter = cards["starter"]
    assert starter["yearly_enabled"] is False
    assert starter["yearly_minor"] == 1_499_000
    assert starter["yearly_display"] == "₹14,990"
    assert starter["yearly_savings_minor"] == 2 * 149_900
    assert starter["yearly_months_free"] == 2
    assert starter["yearly_paise"] == 0   # deployed SPA's yearly branch stays dormant
    assert cards["sandbox"]["yearly_minor"] == 0 and cards["sandbox"]["yearly_display"] is None
    monkeypatch.setattr(billing, "YEARLY_ENABLED", True)
    cards = {c["key"]: c for c in billing.public_plans_payload("INR")}
    assert cards["starter"]["yearly_paise"] == 1_499_000


def test_public_payload_reads_features_and_notes(monkeypatch):
    monkeypatch.setattr(billing, "ENTERPRISE_FREE", False)
    monkeypatch.setattr(fx, "get_usd_to_inr", lambda force=False: 95.0)
    cards = {c["key"]: c for c in billing.public_plans_payload("INR", usd_estimate=True)}
    assert cards["growth"]["label"] == "Team"
    assert cards["growth"]["max_reads"] == 500
    assert cards["growth"]["includes_branches"] is True
    assert cards["starter"]["includes_branches"] is False
    assert "Closed" in cards["starter"]["files_note"]
    assert "On Hold" in cards["starter"]["files_note"]
    assert cards["sandbox"]["price_note"] == "Free for 14 days"
    assert cards["sandbox"]["trial_days"] == 14
    assert cards["sandbox"]["demo_bonus_credits"] == 50
    assert cards["starter"]["usd_estimate"]["monthly_display"].startswith("≈ US$")
    assert cards["sandbox"]["usd_estimate"] is None
    usd_cards = billing.public_plans_payload("USD", usd_estimate=True)
    assert all(c["usd_estimate"] is None for c in usd_cards)
    # An unchargeable currency is quoted (and labelled) as INR, never mislabelled.
    assert {c["currency"] for c in billing.public_plans_payload("JPY")} == {"INR"}


def test_trial_and_branch_pack_facts():
    facts = billing.trial_facts()
    assert facts["days"] == 14 and facts["max_seats"] == 3 and facts["max_open_files"] == 15
    assert facts["included_credits"] == 50 and facts["demo_bonus_credits"] == 50
    assert facts["reads"] == 50 and facts["ai_pauses_on_expiry"] is True
    assert billing.branch_pack_facts() == {"open_files": 100, "seats": 10, "credits": 200, "reads": 200}


# ---------------------------------------------------------------------------
# Subscription state shape
# ---------------------------------------------------------------------------

def test_state_carries_every_new_contract_field(db):
    org_id = db.info["org_id"]
    state = billing.build_subscription_state(db, org_id)
    for key in (
        "open_files_used", "max_open_files", "clients_total", "files_over_limit",
        "files_over_limit_since", "files_grace_ends_at", "files_in_grace", "reads",
        "monthly_reads", "features", "ai_paused", "ai_paused_reason", "ai_paused_message",
        "yearly_enabled", "yearly_minor", "branch_packs", "overrides",
        "trial_bonus_available", "inr_region", "usd_estimate", "trial_domain_blocked",
        "features_tier", "price_note",
    ):
        assert key in state, key
    assert set(state["reads"]) >= {"granted", "used", "remaining", "period_ends_at"}
    assert state["trial_bonus_available"] is True
    assert state["plan_label"] == "14-day free trial"
    assert state["max_seats"] == 3 and state["max_clients"] == 15


def test_trial_bonus_is_offered_once(db):
    org_id = db.info["org_id"]
    _sub(db, demo_bonus_granted_at=START)
    assert billing.build_subscription_state(db, org_id)["trial_bonus_available"] is False


def test_free_platform_state_has_the_same_keys(db, monkeypatch):
    org_id = db.info["org_id"]
    paid_keys = set(billing.build_subscription_state(db, org_id))
    monkeypatch.setattr(billing, "ENTERPRISE_FREE", True)
    free = billing.build_subscription_state(db, org_id)
    missing = {
        "ai_paused", "features", "reads", "monthly_reads", "files_over_limit",
        "branch_packs", "overrides", "trial_bonus_available",
    } - set(free)
    assert not missing
    assert free["ai_paused"] is False
    assert all(free["features"].values())
    assert paid_keys  # sanity


def test_seat_limit_uses_effective_limits(db):
    org_id = db.info["org_id"]
    _paid(db, "starter", override_max_seats=1)
    db.add(models.EnterpriseOrganizationMember(
        organization_id=org_id, user_id=db.info["owner_id"], role="owner", is_active=True,
    ))
    db.commit()
    with pytest.raises(HTTPException) as exc:
        billing.enforce_seat_limit_or_402(db, org_id)
    assert "covers 1 team seats" in exc.value.detail


# ---------------------------------------------------------------------------
# Coupon discounts
# ---------------------------------------------------------------------------

def test_coupon_supports_up_to_100_percent_by_default():
    assert coupons.max_percent_off() == Decimal("100")
    assert coupons.validate_percent_off_for_admin("100") == Decimal("100")
    assert coupons.validate_percent_off_for_admin("99.99") == Decimal("99.99")
    assert coupons.validate_percent_off_for_admin("1") == Decimal("1")
    assert coupons.effective_percent_off(Decimal("100")) == Decimal("100")
    assert coupons.compute_discounted_amount_paise(100_000, Decimal("100")) == 0
    assert coupons.compute_discounted_amount_paise(100_000, Decimal("50")) == 50_000
    assert coupons.compute_discounted_amount_paise(100_000, Decimal("99.99")) == 10


@pytest.mark.parametrize("percent", ("0", "0.999", "-1", "100.001", "101", "150", "NaN", "Infinity", "-Infinity", "abc", None))
def test_admin_coupon_percentage_rejects_invalid_input(percent):
    with pytest.raises(HTTPException) as exc:
        coupons.validate_percent_off_for_admin(percent)
    assert exc.value.status_code == 400


def test_explicit_coupon_cap_at_creation_and_application(monkeypatch):
    monkeypatch.setattr(coupons, "MAX_PERCENT_OFF", Decimal("15"))
    assert coupons.validate_percent_off_for_admin("15") == Decimal("15")
    assert coupons.validate_percent_off_for_admin(10) == Decimal("10")
    for too_much in ("15.01", 20, "100", 150):
        with pytest.raises(HTTPException) as exc:
            coupons.validate_percent_off_for_admin(too_much)
        assert exc.value.status_code == 400
        assert "15%" in exc.value.detail
    # A legacy 100% code is honoured AT the cap, never more.
    assert coupons.effective_percent_off(Decimal("100")) == Decimal("15")
    assert coupons.effective_percent_off(Decimal("12.5")) == Decimal("12.5")
    assert coupons.compute_discounted_amount_paise(100_000, Decimal("100")) == 85_000
    assert coupons.compute_discounted_amount_paise(100_000, Decimal("10")) == 90_000
    # The stored value's normal form is unchanged (the console still shows "100%").
    assert coupons.parse_percent_off("100") == Decimal("100")


@pytest.mark.parametrize("currency", ("INR", "USD", "GBP", "CAD", "AUD"))
@pytest.mark.parametrize("billing_cycle", ("monthly", "yearly"))
def test_checkout_quote_reports_fully_covered_purchase(currency, billing_cycle, monkeypatch):
    monkeypatch.setattr(billing, "YEARLY_ENABLED", True)
    quote = billing.checkout_quote("starter", currency, discount_percent=Decimal("100"), billing_cycle=billing_cycle)
    assert quote["discount_percent"] == 100.0
    assert quote["list_minor"] > 0
    assert quote["discount_minor"] == quote["list_minor"]
    assert quote["subtotal_minor"] == 0
    assert quote["tax_minor"] == 0
    assert quote["total_minor"] == 0


def test_checkout_quote_applies_and_reports_an_explicit_lower_cap(monkeypatch):
    monkeypatch.setattr(coupons, "MAX_PERCENT_OFF", Decimal("15"))
    quote = billing.checkout_quote("starter", "INR", discount_percent=Decimal("100"))
    assert quote["discount_percent"] == 15.0
    assert quote["subtotal_minor"] == 127_415   # ₹1,499 − 15%, half-up
    assert quote["discount_minor"] == 149_900 - 127_415
    assert quote["total_minor"] > 0


def test_coupon_cap_env_parsing(monkeypatch):
    monkeypatch.delenv("ENTERPRISE_COUPON_MAX_PERCENT", raising=False)
    assert coupons._max_percent_from_env() == Decimal("100")
    monkeypatch.setenv("ENTERPRISE_COUPON_MAX_PERCENT", "25")
    assert coupons._max_percent_from_env() == Decimal("25")
    monkeypatch.setenv("ENTERPRISE_COUPON_MAX_PERCENT", "100")
    assert coupons._max_percent_from_env() == Decimal("100")
    for junk in ("", "0", "101", "abc", "-3", "NaN", "Infinity"):
        monkeypatch.setenv("ENTERPRISE_COUPON_MAX_PERCENT", junk)
        assert coupons._max_percent_from_env() == Decimal("100")


def test_coupon_serialize_reports_the_full_discount(db):
    row = models.EnterpriseCoupon(
        organization_id=db.info["org_id"], code="LAUNCH100", percent_off=Decimal("100"),
        is_active=True, applies_to="all",
    )
    db.add(row)
    db.commit()
    out = coupons.serialize(db, row)
    assert out["percent_off"] == 100.0
    assert out["percent_display"] == "100%"
    assert out["effective_percent_off"] == 100.0
    assert out["effective_percent_display"] == "100%"
    assert out["max_percent_off"] == 100.0
    assert out["above_cap"] is False


def test_coupon_serialize_flags_codes_above_an_explicit_cap(db, monkeypatch):
    monkeypatch.setattr(coupons, "MAX_PERCENT_OFF", Decimal("15"))
    row = models.EnterpriseCoupon(
        organization_id=db.info["org_id"], code="LAUNCH100", percent_off=Decimal("100"),
        is_active=True, applies_to="all",
    )
    db.add(row)
    db.commit()
    out = coupons.serialize(db, row)
    assert out["percent_off"] == 100.0
    assert out["effective_percent_off"] == 15.0
    assert out["above_cap"] is True


# ---------------------------------------------------------------------------
# Schema patch
# ---------------------------------------------------------------------------

def test_patch_columns_exist_on_the_models():
    tables = {
        "enterprise_subscriptions": models.EnterpriseSubscription,
        "enterprise_credit_wallets": models.EnterpriseCreditWallet,
        "enterprise_client_documents": models.EnterpriseClientDocument,
        "enterprise_interview_sessions": models.EnterpriseInterviewSession,
    }
    for table, columns in schema_patch._PRICING_V2_COLUMNS.items():
        model_cols = set(tables[table].__table__.columns.keys())
        for col, _ddl in columns:
            assert col in model_cols, f"{table}.{col} patched but missing from the model"


def test_pricing_v2_patch_is_additive_and_idempotent(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    monkeypatch.setattr(schema_patch, "engine", engine)
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE enterprise_subscriptions (id INTEGER PRIMARY KEY, organization_id INTEGER, "
            "plan VARCHAR, status VARCHAR)"
        ))
        conn.execute(text(
            "CREATE TABLE enterprise_credit_wallets (id INTEGER PRIMARY KEY, organization_id INTEGER)"
        ))
        conn.execute(text(
            "CREATE TABLE enterprise_client_documents (id INTEGER PRIMARY KEY, organization_id INTEGER)"
        ))
        conn.execute(text(
            "CREATE TABLE enterprise_interview_sessions (id INTEGER PRIMARY KEY, organization_id INTEGER, "
            "transcript TEXT)"
        ))
        conn.execute(text("INSERT INTO enterprise_interview_sessions (id, organization_id) VALUES (1, 1)"))
        conn.execute(text("INSERT INTO enterprise_subscriptions (id, organization_id, plan, status) "
                          "VALUES (1, 1, 'starter', 'active')"))
    schema_patch.ensure_enterprise_pricing_v2_columns()
    schema_patch.ensure_enterprise_pricing_v2_columns()   # second run is a no-op
    insp = inspect(engine)
    for table, columns in schema_patch._PRICING_V2_COLUMNS.items():
        have = {c["name"] for c in insp.get_columns(table)}
        assert {c for c, _ in columns} <= have
    index_names = {i["name"] for i in insp.get_indexes("enterprise_interview_sessions")}
    assert "ix_enterprise_interview_sessions_run_token_hash" in index_names
    with engine.connect() as conn:
        legacy = conn.execute(text(
            "SELECT status, questions_asked, credits_charged FROM enterprise_interview_sessions"
        )).one()
        assert tuple(legacy) == ("completed", 0, 0)
        sub = conn.execute(text(
            "SELECT branch_packs, trial_domain_blocked, override_max_seats FROM enterprise_subscriptions"
        )).one()
        assert tuple(sub) == (0, 0, None)
    engine.dispose()


def test_patch_skips_missing_tables(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    monkeypatch.setattr(schema_patch, "engine", engine)
    schema_patch.ensure_enterprise_pricing_v2_columns()
    assert inspect(engine).get_table_names() == []
    engine.dispose()
