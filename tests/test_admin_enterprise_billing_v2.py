"""Admin console billing controls (pricing v2, 2026-10-22).

POST /api/admin/enterprise/accounts/{org}/offline-payment, POST …/credits/adjust and
PUT …/overrides, plus the coupon cap on admin create/update and the new facts on the
account-details payload.

Each test pins a rule whose failure costs money or a customer's access: one bank transfer
honoured twice (two periods, two allowances), a yearly invoice recorded as a month because
self-serve yearly is off, a non-INR payment that never reaches the INR revenue totals, a
deduction that drives a wallet negative, a demo bonus granted twice, an override that
half-applies, and an Editor handing out plan time.
"""

from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import enterprise_billing as billing
from app import enterprise_coupons
from app import enterprise_credits as credits
from app import fx
from app import models
from app import money
from app.admin_sessions import get_current_console_user
from app.database import Base, get_db
from app.routers import admin


ACCOUNTS = "/api/admin/enterprise/accounts"


@pytest.fixture
def ctx(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    # autoflush=False like app.database.SessionLocal, so the tests see the production
    # session's flush behaviour (and a read path cannot be rescued by an implicit flush).
    db = sessionmaker(bind=engine, autoflush=False)()
    actor = models.User(
        email="founder@rilono.example", full_name="Console Founder", hashed_password="x",
        is_admin=True, is_active=True, email_verified=True,
    )
    db.add(actor)
    db.commit()
    current = {"user": actor}

    monkeypatch.setattr(billing, "ENTERPRISE_FREE", False)
    monkeypatch.setattr(billing, "GRACE_UNTIL", None)  # post-cutover customers
    monkeypatch.setattr(billing, "AI_PAUSE_ON_EXPIRY", True)
    monkeypatch.setattr(billing, "YEARLY_ENABLED", False)  # self-serve yearly OFF (the default)
    monkeypatch.setattr(credits, "ENFORCE", True)
    monkeypatch.setattr(credits, "PLAN_CREDITS_ROLLOVER", False)
    monkeypatch.setattr(money, "GST_PERCENT", Decimal(18))
    monkeypatch.setattr(fx, "get_usd_to_inr", lambda force=False: 95.0)
    monkeypatch.setattr(admin, "_is_admin_turnstile_required", lambda request: False)
    monkeypatch.setattr(admin, "check_ip_rate_limit", lambda **kwargs: (True, 0))

    app = FastAPI()
    app.include_router(admin.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_console_user] = lambda: current["user"]
    with TestClient(app) as client:
        yield SimpleNamespace(db=db, client=client, actor=actor, current=current)
    db.close()
    engine.dispose()


def _org(ctx, name="Acme Visas", **sub_fields):
    org = models.EnterpriseOrganization(
        company_name=name, created_by_user_id=ctx.actor.id, created_at=datetime.utcnow(),
    )
    ctx.db.add(org)
    ctx.db.flush()
    fields = {"plan": "sandbox", "status": "trialing",
              "trial_ends_at": datetime.utcnow() + timedelta(days=14),
              "created_at": datetime.utcnow()}
    fields.update(sub_fields)
    ctx.db.add(models.EnterpriseSubscription(organization_id=org.id, **fields))
    ctx.db.commit()
    return org.id


def _sub(ctx, org_id) -> models.EnterpriseSubscription:
    ctx.db.expire_all()
    return ctx.db.query(models.EnterpriseSubscription).filter_by(organization_id=org_id).one()


def _wallet(ctx, org_id) -> models.EnterpriseCreditWallet:
    ctx.db.expire_all()
    return ctx.db.query(models.EnterpriseCreditWallet).filter_by(organization_id=org_id).one()


def _plan_rows(ctx, org_id=None):
    ctx.db.expire_all()
    query = ctx.db.query(models.EnterpriseSubscriptionPayment)
    if org_id is not None:
        query = query.filter_by(organization_id=org_id)
    return query.order_by(models.EnterpriseSubscriptionPayment.id).all()


def _list_total(plan, currency="INR", cycle="monthly"):
    return billing.checkout_quote(plan, currency, billing_cycle=cycle)["total_minor"]


def _pay(ctx, org_id, **overrides):
    body = {
        "plan": "growth", "billing_cycle": "monthly", "amount_minor": _list_total("growth"),
        "currency": "INR", "reference": "UTR0001", "provider": "bank_transfer",
    }
    body.update(overrides)
    return ctx.client.post(f"{ACCOUNTS}/{org_id}/offline-payment", json=body)


def _adjust(ctx, org_id, **body):
    return ctx.client.post(f"{ACCOUNTS}/{org_id}/credits/adjust", json=body)


def _overrides(ctx, org_id, **body):
    return ctx.client.put(f"{ACCOUNTS}/{org_id}/overrides", json=body)


def _close(a: datetime, b: datetime, seconds=120) -> bool:
    return abs((a.replace(tzinfo=None) - b.replace(tzinfo=None)).total_seconds()) < seconds


# ---------------------------------------------------------------------------
# Offline payment
# ---------------------------------------------------------------------------

def test_offline_payment_activates_plan_extends_period_and_grants_the_allowance(ctx):
    org_id = _org(ctx)
    total = _list_total("growth")
    response = _pay(ctx, org_id, note="Paid after the demo call")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["duplicate"] is False
    assert data["warnings"] == []  # paid exactly the list price, no mandate

    [row] = _plan_rows(ctx, org_id)
    assert row.status == "verified" and row.verified_at is not None
    assert row.provider == "bank_transfer"
    assert row.razorpay_order_id == "offline:UTR0001"
    assert row.razorpay_payment_id is None
    assert (row.plan, row.billing_cycle, row.currency) == ("growth", "monthly", "INR")
    assert row.amount_paise == total
    # Tax backed out of the total with the same helpers checkout prices with.
    assert row.subtotal_paise == money.tax_inclusive_net_minor(total, "INR") == 399900
    assert row.tax_paise == total - 399900
    assert Decimal(str(row.tax_percent)) == Decimal(18) and row.tax_label == "GST"
    # INR settles at its own amount, so the revenue totals can sum it.
    assert row.base_amount_paise == total and row.is_international is False
    assert row.created_by_user_id == ctx.actor.id
    assert row.included_credits == billing.PLANS["growth"]["included_credits"]
    assert row.original_amount_paise is None  # not a discounted deal

    sub = _sub(ctx, org_id)
    assert (sub.plan, sub.status) == ("growth", "active")
    assert _close(sub.current_period_end, datetime.utcnow() + timedelta(days=billing.PLAN_PERIOD_DAYS))

    # The paid period's allowance landed immediately (credits AND reads).
    wallet = _wallet(ctx, org_id)
    assert wallet.balance_credits == billing.PLANS["growth"]["included_credits"]
    assert wallet.reads_granted == billing.PLANS["growth"]["max_reads"]
    assert data["credits_granted"] == billing.PLANS["growth"]["included_credits"]
    assert data["subscription"]["plan"] == "growth" and data["subscription"]["ai_paused"] is False
    assert data["payment"]["is_offline"] is True
    assert data["payment"]["reference"] == "UTR0001"
    assert data["payment"]["provider_label"] == "Bank transfer"
    assert data["period"]["days_added"] == billing.PLAN_PERIOD_DAYS


def test_offline_payment_is_idempotent_on_reference(ctx):
    org_id = _org(ctx)
    first = _pay(ctx, org_id)
    assert first.status_code == 200, first.text
    end_after_first = _sub(ctx, org_id).current_period_end
    balance_after_first = _wallet(ctx, org_id).balance_credits

    # A double-submit, and the same invoice typed in another case: one payment.
    for reference in ("UTR0001", "utr0001"):
        again = _pay(ctx, org_id, reference=reference)
        assert again.status_code == 200, again.text
        assert again.json()["duplicate"] is True
        assert "not extended again" in again.json()["message"]
    assert len(_plan_rows(ctx)) == 1
    assert _sub(ctx, org_id).current_period_end == end_after_first
    assert _wallet(ctx, org_id).balance_credits == balance_after_first

    # Same reference, different terms — or on another account — is a conflict, not a replay.
    conflict = _pay(ctx, org_id, amount_minor=_list_total("growth") - 100)
    assert conflict.status_code == 409
    assert "already recorded" in conflict.json()["detail"]
    other_org = _org(ctx, "Other Org")
    assert _pay(ctx, other_org).status_code == 409
    assert len(_plan_rows(ctx)) == 1
    assert _sub(ctx, other_org).plan == "sandbox"


def test_offline_payment_stacks_on_paid_time_and_restarts_a_lapsed_plan(ctx):
    remaining = datetime.utcnow() + timedelta(days=10)
    active = _org(ctx, "Active", plan="starter", status="active", current_period_end=remaining)
    assert _pay(ctx, active, plan="starter", amount_minor=_list_total("starter")).status_code == 200
    # Never loses the 10 days already paid for — same stacking as checkout.
    assert _close(_sub(ctx, active).current_period_end, remaining + timedelta(days=billing.PLAN_PERIOD_DAYS))

    lapsed = _org(ctx, "Lapsed", plan="starter", status="active",
                  current_period_end=datetime.utcnow() - timedelta(days=40))
    assert _pay(ctx, lapsed, plan="starter", amount_minor=_list_total("starter"),
                reference="UTR0002").status_code == 200
    assert _close(_sub(ctx, lapsed).current_period_end,
                  datetime.utcnow() + timedelta(days=billing.PLAN_PERIOD_DAYS))


def test_yearly_invoice_is_recorded_even_while_self_serve_yearly_is_off(ctx):
    assert billing.yearly_enabled() is False
    org_id = _org(ctx)
    response = _pay(ctx, org_id, billing_cycle="yearly", provider="invoice", reference="INV-2026/014",
                    amount_minor=_list_total("growth", cycle="yearly"))
    assert response.status_code == 200, response.text
    [row] = _plan_rows(ctx, org_id)
    assert row.billing_cycle == "yearly" and row.provider == "invoice"
    assert row.subtotal_paise == billing.plan_price_minor("growth", "INR", "yearly")
    assert _close(_sub(ctx, org_id).current_period_end,
                  datetime.utcnow() + timedelta(days=billing.YEARLY_PERIOD_DAYS))
    # Allowances are still granted per monthly sub-period, never twelve at once.
    assert _wallet(ctx, org_id).balance_credits == billing.PLANS["growth"]["included_credits"]
    assert response.json()["subscription"]["billing_cycle"] == "yearly"


def test_tax_is_derived_from_the_configured_rate_or_taken_as_stated(ctx, monkeypatch):
    org_id = _org(ctx)
    # GST 0 end-to-end: no tax line at all on a payment recorded without one.
    monkeypatch.setattr(money, "GST_PERCENT", Decimal(0))
    assert _pay(ctx, org_id, amount_minor=399900, reference="UTR-GST0").status_code == 200
    row = _plan_rows(ctx, org_id)[-1]
    assert (row.subtotal_paise, row.tax_paise, row.tax_label) == (399900, 0, None)
    assert Decimal(str(row.tax_percent)) == 0

    # A stated tax records the rate it actually represents — and its label — even at 0% now.
    assert _pay(ctx, org_id, amount_minor=110000, tax_minor=10000, reference="UTR-STATED").status_code == 200
    row = _plan_rows(ctx, org_id)[-1]
    assert (row.subtotal_paise, row.tax_paise, row.tax_label) == (100000, 10000, "GST")
    assert Decimal(str(row.tax_percent)) == Decimal("10.00")

    bad = _pay(ctx, org_id, amount_minor=1000, tax_minor=1000, reference="UTR-BADTAX")
    assert bad.status_code == 400
    assert "less than the amount" in bad.json()["detail"]


def test_non_inr_payment_must_state_its_inr_settlement(ctx):
    org_id = _org(ctx)
    usd_total = _list_total("growth", "USD")
    missing = _pay(ctx, org_id, currency="USD", amount_minor=usd_total, reference="WIRE-1")
    assert missing.status_code == 400
    assert "INR amount that settled" in missing.json()["detail"]
    assert _plan_rows(ctx) == []

    ok = _pay(ctx, org_id, currency="USD", amount_minor=usd_total, settled_inr_minor=usd_total * 90,
              reference="WIRE-1")
    assert ok.status_code == 200, ok.text
    [row] = _plan_rows(ctx, org_id)
    assert row.currency == "USD" and row.is_international is True
    assert row.base_amount_paise == usd_total * 90
    assert Decimal(str(row.fx_rate_used)) == Decimal("90")
    assert row.tax_paise == 0 and row.tax_label is None  # zero-rated export

    # The INR revenue totals on the details page include it at its settlement figure.
    details = ctx.client.get(f"{ACCOUNTS}/{org_id}/details").json()
    assert details["totals"]["plan_revenue_paise"] == usd_total * 90
    assert details["totals"]["unsettled_payment_count"] == 0

    mismatch = _pay(ctx, org_id, amount_minor=1000, settled_inr_minor=999, reference="UTR-MISMATCH")
    assert mismatch.status_code == 400


@pytest.mark.parametrize("overrides,status,needle", [
    ({"plan": "sandbox"}, 400, "Choose a paid plan"),
    ({"plan": "platinum"}, 400, "Choose a paid plan"),
    ({"billing_cycle": "weekly"}, 400, "monthly or yearly"),
    ({"provider": "razorpay"}, 400, "Payment method"),
    ({"reference": "UTR 0001"}, 400, "no spaces"),
    ({"reference": "U1"}, 400, "payment reference"),
    ({"amount_minor": 0}, 400, "greater than zero"),
    ({"amount_minor": -5}, 400, "greater than zero"),
    ({"amount_minor": admin.ADMIN_OFFLINE_PAYMENT_MAX_MINOR + 1}, 400, "minor units"),
    ({"currency": "JPY"}, 400, "Currency must be one of"),
    ({"note": "x" * (admin.ADMIN_NOTE_MAX + 1)}, 400, "note"),
])
def test_offline_payment_validation_writes_nothing(ctx, overrides, status, needle):
    org_id = _org(ctx)
    response = _pay(ctx, org_id, **overrides)
    assert response.status_code == status, response.text
    assert needle in response.json()["detail"]
    assert _plan_rows(ctx) == []
    assert _sub(ctx, org_id).plan == "sandbox"


def test_offline_payment_refused_while_billing_is_off_and_for_unknown_org(ctx, monkeypatch):
    assert _pay(ctx, 999999).status_code == 404
    org_id = _org(ctx)
    monkeypatch.setattr(billing, "ENTERPRISE_FREE", True)
    response = _pay(ctx, org_id)
    assert response.status_code == 400 and "ENTERPRISE_FREE" in response.json()["detail"]


def test_payment_link_pay_id_cannot_honour_a_checkout_payment_twice(ctx):
    org_id = _org(ctx, plan="growth", status="active", current_period_end=datetime.utcnow() + timedelta(days=20))
    ctx.db.add(models.EnterpriseSubscriptionPayment(
        organization_id=org_id, provider="razorpay", plan="growth", billing_cycle="monthly",
        amount_paise=_list_total("growth"), currency="INR", razorpay_order_id="order_Live123",
        razorpay_payment_id="pay_Live123abc", status="verified", verified_at=datetime.utcnow(),
    ))
    ctx.db.commit()
    end_before = _sub(ctx, org_id).current_period_end
    response = _pay(ctx, org_id, provider="payment_link", reference="pay_Live123abc")
    assert response.status_code == 409
    assert len(_plan_rows(ctx, org_id)) == 1
    assert _sub(ctx, org_id).current_period_end == end_before

    # A fresh Payment Link payment is recorded with its pay_ id in the unique column too.
    assert _pay(ctx, org_id, provider="payment_link", reference="pay_Link777xyz").status_code == 200
    assert _plan_rows(ctx, org_id)[-1].razorpay_payment_id == "pay_Link777xyz"


def test_cross_tier_offline_payment_inside_a_prepaid_year_needs_an_explicit_tier_change(ctx):
    org_id = _org(ctx)
    assert _pay(ctx, org_id, plan="starter", billing_cycle="yearly", provider="invoice",
                reference="INV-Y-1", amount_minor=_list_total("starter", cycle="yearly")).status_code == 200
    year_end = _sub(ctx, org_id).current_period_end
    controls = ctx.client.get(f"{ACCOUNTS}/{org_id}/details").json()["billing_controls"]
    assert controls["term_locked_plan"] == "starter" and controls["term_locked_until"]

    # A month of Multi-branch must not re-tier the rest of the Starter year.
    refused = _pay(ctx, org_id, plan="scale", amount_minor=_list_total("scale"), reference="UTR-SCALE-1")
    assert refused.status_code == 409, refused.text
    assert "change_tier_now" in refused.json()["detail"]
    assert len(_plan_rows(ctx, org_id)) == 1
    assert _sub(ctx, org_id).plan == "starter" and _close(_sub(ctx, org_id).current_period_end, year_end)

    # The same tier stacks as before.
    same = _pay(ctx, org_id, plan="starter", amount_minor=_list_total("starter"), reference="UTR-STARTER-2")
    assert same.status_code == 200, same.text
    assert _close(_sub(ctx, org_id).current_period_end, year_end + timedelta(days=billing.PLAN_PERIOD_DAYS))

    # Prorated by hand: the new tier starts today and replaces the old term.
    forced = _pay(ctx, org_id, plan="scale", amount_minor=_list_total("scale"), reference="UTR-SCALE-2",
                  change_tier_now=True)
    assert forced.status_code == 200, forced.text
    sub = _sub(ctx, org_id)
    assert sub.plan == "scale"
    assert _close(sub.current_period_end, datetime.utcnow() + timedelta(days=billing.PLAN_PERIOD_DAYS))
    assert any("replaced from today" in w for w in forced.json()["warnings"])


def test_offline_payment_warns_about_a_live_mandate_and_an_off_list_amount(ctx):
    org_id = _org(ctx, plan="growth", status="active", current_period_end=datetime.utcnow() + timedelta(days=3),
                  razorpay_subscription_id="sub_Mandate1", mandate_status="active")
    response = _pay(ctx, org_id, amount_minor=400000)
    assert response.status_code == 200, response.text
    warnings = " ".join(response.json()["warnings"])
    assert "mandate" in warnings
    assert "differs from the list price" in warnings


# ---------------------------------------------------------------------------
# Credits: adjustments and the demo-call bonus
# ---------------------------------------------------------------------------

def test_credit_adjustment_moves_the_balance_with_an_attributed_ledger_line(ctx):
    org_id = _org(ctx)
    response = _adjust(ctx, org_id, kind="adjustment", credits=120, reason="Goodwill — slow support week")
    assert response.status_code == 200, response.text
    data = response.json()
    assert (data["requested"], data["applied"], data["capped"]) == (120, 120, False)
    wallet = _wallet(ctx, org_id)
    assert wallet.balance_credits == 120
    assert wallet.lifetime_purchased_credits == 0  # a gift is not a purchase
    txn = ctx.db.query(models.EnterpriseCreditTransaction).filter_by(
        organization_id=org_id, reference_type="admin_adjustment").one()
    assert txn.type == "adjustment" and txn.credits == 120
    assert txn.created_by_name == "Console Founder"
    assert "Goodwill — slow support week" in txn.description
    assert data["wallet"]["balance_credits"] == 120


def test_credit_deduction_is_capped_at_the_balance(ctx):
    org_id = _org(ctx)
    assert _adjust(ctx, org_id, credits=30, reason="Seed").status_code == 200
    response = _adjust(ctx, org_id, credits=-100, reason="Clawback of a duplicate grant")
    assert response.status_code == 200, response.text
    data = response.json()
    assert (data["requested"], data["applied"], data["capped"]) == (-100, -30, True)
    assert _wallet(ctx, org_id).balance_credits == 0

    empty = _adjust(ctx, org_id, credits=-5, reason="Nothing left")
    assert empty.status_code == 400 and "no credits to deduct" in empty.json()["detail"]


@pytest.mark.parametrize("body,needle", [
    ({"credits": 0, "reason": "zero"}, "non-zero"),
    ({"reason": "missing"}, "non-zero"),
    ({"credits": admin.ADMIN_CREDIT_ADJUST_MAX + 1, "reason": "typo"}, "at most"),
    ({"credits": 10}, "Give a reason"),
    ({"credits": 10, "reason": "x" * (admin.ADMIN_REASON_MAX + 1)}, "under"),
    ({"kind": "refund", "credits": 10, "reason": "wrong kind"}, "kind must be"),
])
def test_credit_adjustment_validation(ctx, body, needle):
    org_id = _org(ctx)
    response = _adjust(ctx, org_id, **body)
    assert response.status_code == 400, response.text
    assert needle in response.json()["detail"]
    assert ctx.db.query(models.EnterpriseCreditTransaction).count() == 0


def test_demo_call_bonus_is_granted_once_per_account(ctx):
    org_id = _org(ctx)
    bonus = billing.TRIAL_DEMO_BONUS_CREDITS
    first = _adjust(ctx, org_id, kind="demo_call_bonus", reason="Demo with the owner")
    assert first.status_code == 200, first.text
    assert (first.json()["granted"], first.json()["already_granted"]) == (bonus, False)
    assert first.json()["transaction"]["credits"] == bonus
    assert _sub(ctx, org_id).demo_bonus_granted_at is not None
    assert _wallet(ctx, org_id).balance_credits == bonus

    second = _adjust(ctx, org_id, kind="demo_call_bonus")
    assert second.status_code == 200
    assert (second.json()["granted"], second.json()["already_granted"]) == (0, True)
    assert "already granted" in second.json()["message"]
    assert _wallet(ctx, org_id).balance_credits == bonus

    details = ctx.client.get(f"{ACCOUNTS}/{org_id}/details").json()["billing_controls"]
    assert details["demo_bonus_available"] is False and details["demo_bonus_granted_at"]


def test_demo_call_bonus_size_is_configuration_not_a_per_click_choice(ctx, monkeypatch):
    org_id = _org(ctx)
    wrong = _adjust(ctx, org_id, kind="demo_call_bonus", credits=billing.TRIAL_DEMO_BONUS_CREDITS * 2)
    assert wrong.status_code == 400 and "fixed at" in wrong.json()["detail"]
    assert _sub(ctx, org_id).demo_bonus_granted_at is None

    monkeypatch.setattr(billing, "TRIAL_DEMO_BONUS_CREDITS", 0)
    off = _adjust(ctx, org_id, kind="demo_call_bonus")
    assert off.status_code == 400 and "switched off" in off.json()["detail"]


# ---------------------------------------------------------------------------
# Overrides
# ---------------------------------------------------------------------------

def _paid_team_org(ctx):
    org_id = _org(ctx, plan="growth", status="active",
                  current_period_end=datetime.utcnow() + timedelta(days=20))
    credits.sync_plan_credits(ctx.db, org_id, commit=True)  # this period's 450 granted
    return org_id


def test_raised_overrides_apply_now_and_top_up_the_difference(ctx):
    org_id = _paid_team_org(ctx)
    team = billing.PLANS["growth"]
    assert _wallet(ctx, org_id).balance_credits == team["included_credits"]

    response = _overrides(ctx, org_id, max_seats=35, included_credits=team["included_credits"] + 150,
                          monthly_reads=team["max_reads"] + 100)
    assert response.status_code == 200, response.text
    data = response.json()
    assert set(data["changes"]) == {"max_seats", "included_credits", "monthly_reads"}
    assert data["credits_granted"] == 150
    assert data["effective_changes"]["max_seats"] == {"before": team["max_seats"], "after": 35}

    sub = _sub(ctx, org_id)
    assert (sub.override_max_seats, sub.override_included_credits) == (35, team["included_credits"] + 150)
    assert sub.override_max_clients is None  # partial update: untouched
    assert _wallet(ctx, org_id).balance_credits == team["included_credits"] + 150
    assert _wallet(ctx, org_id).reads_granted == team["max_reads"] + 100
    assert data["subscription"]["max_seats"] == 35

    # null = back to the plan default; lowering takes nothing back this period.
    reset = _overrides(ctx, org_id, included_credits=None, max_seats=None)
    assert reset.status_code == 200, reset.text
    assert _sub(ctx, org_id).override_included_credits is None
    assert _wallet(ctx, org_id).balance_credits == team["included_credits"] + 150
    assert any("taken back" in w for w in reset.json()["warnings"])
    assert reset.json()["subscription"]["max_seats"] == team["max_seats"]


def test_branch_packs_add_on_top_of_a_paid_plan_only(ctx):
    org_id = _paid_team_org(ctx)
    team = billing.PLANS["growth"]
    response = _overrides(ctx, org_id, branch_packs=2)
    assert response.status_code == 200, response.text
    state = response.json()["subscription"]
    assert state["branch_packs"] == 2
    assert state["max_seats"] == team["max_seats"] + 2 * billing.BRANCH_PACK_SEATS
    assert state["max_open_files"] == team["max_clients"] + 2 * billing.BRANCH_PACK_FILES
    assert response.json()["credits_granted"] == 2 * billing.BRANCH_PACK_CREDITS

    trial_org = _org(ctx, "Trial Org")
    on_trial = _overrides(ctx, trial_org, branch_packs=1)
    assert on_trial.status_code == 200
    assert on_trial.json()["subscription"]["branch_packs"] == 0  # stored, not applied
    assert any("Branch Packs apply only while a paid plan" in w for w in on_trial.json()["warnings"])
    controls = ctx.client.get(f"{ACCOUNTS}/{trial_org}/details").json()["billing_controls"]
    assert (controls["branch_packs"], controls["branch_packs_applied"]) == (1, 0)

    # null packs = none.
    assert _overrides(ctx, org_id, branch_packs=None).status_code == 200
    assert _sub(ctx, org_id).branch_packs == 0


def test_trial_extension_unpauses_ai_for_an_expired_trial(ctx):
    org_id = _org(ctx, trial_ends_at=datetime.utcnow() - timedelta(days=2))
    assert billing.ai_access_state(ctx.db, org_id)["allowed"] is False
    target = (datetime.utcnow() + timedelta(days=7)).date()
    response = _overrides(ctx, org_id, trial_ends_at=target.isoformat())
    assert response.status_code == 200, response.text
    sub = _sub(ctx, org_id)
    # A bare date means the END of that day, so the trial still works on that date.
    assert sub.trial_ends_at.replace(tzinfo=None) == datetime(target.year, target.month, target.day, 23, 59, 59)
    assert billing.ai_access_state(ctx.db, org_id)["allowed"] is True
    assert response.json()["subscription"]["ai_paused"] is False
    assert list(response.json()["changes"]) == ["trial_ends_at"]


@pytest.mark.parametrize("body,needle", [
    ({}, "Nothing to change"),
    ({"max_seats": 0}, "between 1"),
    ({"max_seats": -1}, "between 1"),
    ({"max_clients": admin.ADMIN_OVERRIDE_MAX + 1}, "between 1"),
    ({"included_credits": admin.ADMIN_CREDIT_ADJUST_MAX + 1}, "between 0"),
    ({"monthly_reads": -3}, "between 0"),
    ({"branch_packs": admin.ADMIN_MAX_BRANCH_PACKS + 1}, "Branch Packs must be"),
    ({"branch_packs": -1}, "Branch Packs must be"),
    ({"trial_ends_at": None}, "can't be cleared"),
    ({"trial_ends_at": "next tuesday"}, "date like"),
    ({"trial_ends_at": "2020-01-01"}, "in the future"),
    ({"max_seats": 30, "trial_ends_at": "2020-01-01"}, "in the future"),
])
def test_override_validation_never_half_applies(ctx, body, needle):
    org_id = _org(ctx)
    before = _sub(ctx, org_id)
    snapshot = (before.override_max_seats, before.branch_packs, before.trial_ends_at)
    response = _overrides(ctx, org_id, **body)
    assert response.status_code == 400, response.text
    assert needle in response.json()["detail"]
    after = _sub(ctx, org_id)
    assert (after.override_max_seats, after.branch_packs, after.trial_ends_at) == snapshot


def test_staff_can_change_the_billing_country_owners_can_no_longer_touch(ctx):
    org_id = _org(ctx)
    assert _pay(ctx, org_id, reference="UTR-COUNTRY").status_code == 200   # now locked for owners
    response = _overrides(ctx, org_id, country_code="ke")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["changes"] == {"country_code": {"before": None, "after": "KE"}}
    assert data["overrides"]["country_code"] == "KE"
    assert "Billing country" in data["message"]
    ctx.db.expire_all()
    assert ctx.db.get(models.EnterpriseOrganization, org_id).country_code == "KE"
    # Only the country: nothing else in the body means nothing else changes.
    assert _sub(ctx, org_id).override_max_seats is None
    assert _overrides(ctx, org_id, country_code="Kenya").status_code == 400
    assert _overrides(ctx, org_id, country_code=None).json()["overrides"]["country_code"] is None


def test_trial_extension_is_bounded(ctx):
    org_id = _org(ctx)
    too_far = (datetime.utcnow() + timedelta(days=admin.ADMIN_MAX_TRIAL_DAYS + 2)).date().isoformat()
    response = _overrides(ctx, org_id, trial_ends_at=too_far)
    assert response.status_code == 400 and "at most" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Coupon cap on admin create/update
# ---------------------------------------------------------------------------

def test_admin_cannot_create_or_raise_a_coupon_above_the_cap(ctx):
    org_id = _org(ctx)
    cap = enterprise_coupons.max_percent_off()
    above = ctx.client.post(f"{ACCOUNTS}/{org_id}/coupons", json={"code": "BIG", "percent_off": float(cap) + 5})
    assert above.status_code == 400 and "at most" in above.json()["detail"]
    assert ctx.db.query(models.EnterpriseCoupon).count() == 0

    at_cap = ctx.client.post(f"{ACCOUNTS}/{org_id}/coupons", json={"code": "OK", "percent_off": float(cap)})
    assert at_cap.status_code == 200, at_cap.text
    coupon_id = at_cap.json()["coupon"]["id"]
    raised = ctx.client.patch(f"{ACCOUNTS}/{org_id}/coupons/{coupon_id}", json={"percent_off": float(cap) + 1})
    assert raised.status_code == 400

    # A legacy code stored above the cap can still be paused without re-pricing it.
    legacy = models.EnterpriseCoupon(organization_id=org_id, code="LEGACY50", percent_off=Decimal(50),
                                     is_active=True, applies_to="all")
    ctx.db.add(legacy)
    ctx.db.commit()
    paused = ctx.client.patch(f"{ACCOUNTS}/{org_id}/coupons/{legacy.id}", json={"is_active": False})
    assert paused.status_code == 200, paused.text
    assert paused.json()["coupon"]["is_active"] is False


def test_promo_email_for_a_legacy_code_advertises_the_capped_percent(ctx, monkeypatch):
    org_id = _org(ctx)
    # Saved before the cap existed (bypasses the admin create validation).
    coupon = models.EnterpriseCoupon(organization_id=org_id, code="LAUNCH50", percent_off=Decimal("50"),
                                     is_active=True, applies_to="all")
    ctx.db.add(coupon)
    ctx.db.commit()
    sent = []
    monkeypatch.setattr(admin.email_service, "send_enterprise_discount_promo_email",
                        lambda **kwargs: sent.append(kwargs) or True)
    response = ctx.client.post(f"{ACCOUNTS}/{org_id}/coupons/{coupon.id}/send-email",
                               json={"email": "owner@acme-visas.example"})
    assert response.status_code == 200, response.text
    cap = enterprise_coupons.max_percent_off()
    assert [m["percent_display"] for m in sent] == [enterprise_coupons.format_percent_off(cap) + "%"]


# ---------------------------------------------------------------------------
# Account details + capability
# ---------------------------------------------------------------------------

def test_details_list_offline_payments_and_the_admin_set_facts(ctx):
    org_id = _org(ctx)
    assert _pay(ctx, org_id, provider="invoice", reference="INV-77", amount_minor=400000).status_code == 200
    assert _overrides(ctx, org_id, branch_packs=3, max_seats=40).status_code == 200
    details = ctx.client.get(f"{ACCOUNTS}/{org_id}/details")
    assert details.status_code == 200, details.text
    data = details.json()

    [payment] = data["plan_payments"]
    assert payment["is_offline"] is True and payment["provider"] == "invoice"
    assert payment["reference"] == "INV-77"
    assert payment["created_by_name"] == "Console Founder"
    assert payment["amount_display"] == money.format_money(400000, "INR")
    assert payment["original_amount_display"] == money.format_money(399900, "INR")  # paid below list
    assert data["purchases"] == []  # credit top-ups only; nothing here to refund via Razorpay
    assert data["totals"]["plan_payment_count"] == 1

    controls = data["billing_controls"]
    assert controls["branch_packs"] == controls["branch_packs_applied"] == 3
    assert controls["overrides"] == {"max_seats": 40, "max_clients": None,
                                     "included_credits": None, "monthly_reads": None}
    assert controls["plan_defaults"]["max_seats"] == billing.PLANS["growth"]["max_seats"]
    assert controls["effective_limits"]["max_seats"] == 40 + 3 * billing.BRANCH_PACK_SEATS
    assert [p["key"] for p in controls["plans"]] == ["starter", "growth", "scale"]
    assert {p["key"] for p in controls["providers"]} == {"payment_link", "bank_transfer", "invoice"}
    assert controls["demo_bonus_available"] is True
    assert controls["yearly_enabled"] is False
    team_monthly_inr = [row for row in controls["price_list"]
                        if (row["plan"], row["billing_cycle"], row["currency"]) == ("growth", "monthly", "INR")]
    assert team_monthly_inr[0]["total_minor"] == _list_total("growth")
    assert data["subscription"]["reads"]["granted"] >= 0


@pytest.mark.parametrize("country,expected", [("AE", "AED"), ("GB", "GBP"), ("IN", "INR"), (None, "INR")])
def test_offline_form_defaults_a_trial_org_to_its_billing_currency(ctx, country, expected):
    # A trial org's subscription quote is the sandbox plan's, which is always INR — not
    # what a UAE consultancy closing a deal after its demo call pays in.
    org_id = _org(ctx)
    ctx.db.get(models.EnterpriseOrganization, org_id).country_code = country
    ctx.db.commit()
    controls = ctx.client.get(f"{ACCOUNTS}/{org_id}/details").json()["billing_controls"]
    assert controls["default_currency"] == expected
    hint = [r for r in controls["price_list"]
            if (r["plan"], r["billing_cycle"], r["currency"]) == ("growth", "monthly", expected)]
    assert hint and (hint[0]["tax_minor"] == 0) == (expected != "INR")


def test_offline_form_defaults_a_lapsed_payer_to_the_currency_it_paid_in(ctx):
    org_id = _org(ctx, plan="growth", status="active",
                  current_period_end=datetime.utcnow() - timedelta(days=40))
    ctx.db.get(models.EnterpriseOrganization, org_id).country_code = "AE"
    ctx.db.add(models.EnterpriseSubscriptionPayment(
        organization_id=org_id, provider="bank_transfer", plan="growth", amount_paise=32_900,
        currency="AED", razorpay_order_id="offline:UTR-AED-1", status="verified",
        verified_at=datetime.utcnow() - timedelta(days=70),
    ))
    ctx.db.commit()
    controls = ctx.client.get(f"{ACCOUNTS}/{org_id}/details").json()["billing_controls"]
    assert controls["default_currency"] == "AED"


def test_details_billing_controls_create_nothing_for_an_org_without_rows(ctx, monkeypatch):
    org = models.EnterpriseOrganization(company_name="Bare", created_by_user_id=ctx.actor.id)
    ctx.db.add(org)
    ctx.db.commit()

    def refuse_write(*args, **kwargs):
        raise AssertionError("A details GET must not flush or commit")

    monkeypatch.setattr(ctx.db, "flush", refuse_write)
    monkeypatch.setattr(ctx.db, "commit", refuse_write)
    response = ctx.client.get(f"{ACCOUNTS}/{org.id}/details")
    assert response.status_code == 200, response.text
    assert response.json()["billing_controls"]["stored_plan"] == "sandbox"
    assert response.json()["plan_payments"] == []
    assert ctx.db.query(models.EnterpriseSubscription).count() == 0
    assert ctx.db.query(models.EnterpriseCreditWallet).count() == 0


NEW_ROUTES = [
    ("POST", "/api/admin/enterprise/accounts/{organization_id}/offline-payment"),
    ("POST", "/api/admin/enterprise/accounts/{organization_id}/credits/adjust"),
    ("PUT", "/api/admin/enterprise/accounts/{organization_id}/overrides"),
]


def test_billing_controls_are_admin_role_actions():
    policies = {
        (next(iter(route.methods)), route.path): route.endpoint.admin_console_policy
        for route in admin.router.routes if isinstance(route, APIRoute)
    }
    for key in NEW_ROUTES:
        assert (policies[key].section, policies[key].action) == ("enterprise", "delete"), key


@pytest.mark.parametrize("method,path", NEW_ROUTES)
def test_an_editor_cannot_hand_out_plan_time_or_credits(ctx, method, path):
    org_id = _org(ctx)
    editor = models.User(email="editor@rilono.example", full_name="Editor", hashed_password="x",
                         is_active=True, email_verified=True)
    ctx.db.add(editor)
    ctx.db.flush()
    ctx.db.add(models.AdminConsoleAccess(user_id=editor.id, role="editor", sections='["enterprise"]'))
    ctx.db.commit()
    ctx.current["user"] = editor
    body = {"plan": "growth", "amount_minor": 100000, "reference": "UTR-EDITOR",
            "credits": 50, "reason": "nope", "max_seats": 99}
    response = ctx.client.request(method, path.replace("{organization_id}", str(org_id)), json=body)
    assert response.status_code == 403
    assert _plan_rows(ctx) == []
    assert _sub(ctx, org_id).override_max_seats is None
    assert ctx.db.query(models.EnterpriseCreditTransaction).count() == 0
    # The same Editor can still read the account.
    assert ctx.client.get(f"{ACCOUNTS}/{org_id}/details").status_code == 200
