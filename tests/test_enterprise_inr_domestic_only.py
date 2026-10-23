"""D-011 (2026-10-23): rupee prices are paid with Indian payment methods.

An INR plan or credit charge to an org billed in India is sold "domestic-only". Each test pins
a rule whose failure either hands a foreign office the rupee price or costs a real Indian
customer their purchase:

  * a domestic-only ORDER that is auto-captured (the manual-capture fence missing), or a
    foreign-currency / Nepal-billed order that is fenced when it must not be;
  * a foreign card on a domestic-only order captured or granted under the "refund" policy,
    or a domestic payment left uncaptured;
  * "review" and "reprice" doing anything but what they promise (reprice: the org leaves INR,
    its INR mandate stops at the end of the period it paid for);
  * a mandate (no manual capture) whose foreign first charge or renewal is not refunded and
    cancelled, or a mandate sold BEFORE the rule being refused on renewal;
  * a refused payment that a replayed verify or a redelivered webhook then honours, refunds
    twice, or counts as "has paid".

sqlite in memory, the real router on a bare FastAPI app, Razorpay faked at _razorpay_request.
"""

import hashlib
import hmac
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import enterprise_access as access
from app import enterprise_billing as billing
from app import enterprise_credits as credits
from app import fx
from app import models
from app import schema_patch
from app.auth import get_current_active_user
from app.database import Base, get_db
from app.routers import enterprise


KEY_SECRET = "test-razorpay-secret"
WEBHOOK_SECRET = "test-credits-webhook-secret"


class FakeRazorpay:
    """Answers like Razorpay for checkout, capture, refund and cancel; records every call."""

    def __init__(self):
        self.calls = []
        self.payments = {}
        self.orders = {}
        self.fail_refunds = False
        self._n = 0

    def __call__(self, method, path, json_payload=None):
        method = method.upper()
        self.calls.append((method, path, json_payload))
        self._n += 1
        if path == "/orders":
            order_id = f"order_TEST{self._n:06d}"
            self.orders[order_id] = {
                "id": order_id, "amount": json_payload["amount"],
                "currency": json_payload["currency"], "status": "created",
            }
            return {"id": order_id}
        if path == "/subscriptions":
            return {"id": f"sub_TEST{self._n:06d}"}
        if path == "/plans":
            return {"id": f"plan_TEST{self._n:06d}"}
        if path.endswith("/capture"):
            pay = self.payments[path.split("/")[2]]
            pay.update(captured=True, status="captured")
            if pay.get("order_id") in self.orders:
                self.orders[pay["order_id"]]["status"] = "paid"
            return dict(pay)
        if path.endswith("/refund"):
            if self.fail_refunds:
                raise enterprise.HTTPException(status_code=502, detail="refund failed")
            pay = self.payments[path.split("/")[2]]
            pay["amount_refunded"] = int(pay.get("amount_refunded") or 0) + int(json_payload["amount"])
            return {"id": f"rfnd_TEST{self._n:06d}", "status": "processed"}
        if "/cancel" in path:
            return {"status": "cancelled"}
        if path.startswith("/payments/"):
            return dict(self.payments[path.rsplit("/", 1)[1]])
        if path.startswith("/orders/"):
            return dict(self.orders[path.rsplit("/", 1)[1]])
        raise AssertionError(f"unexpected Razorpay call {method} {path}")

    def posted(self, suffix):
        return [(p, body) for m, p, body in self.calls if m == "POST" and p.endswith(suffix)]


@pytest.fixture
def ctx(monkeypatch):
    monkeypatch.setattr(billing, "ENTERPRISE_FREE", False)
    monkeypatch.setattr(billing, "AI_PAUSE_ON_EXPIRY", True)
    monkeypatch.setattr(billing, "GRACE_UNTIL", None)
    monkeypatch.setattr(billing, "YEARLY_ENABLED", False)
    monkeypatch.setattr(billing, "INR_DOMESTIC_ONLY", True)
    monkeypatch.setattr(billing, "INR_MANUAL_CAPTURE", True)
    monkeypatch.setattr(billing, "INR_FOREIGN_CARD_POLICY", billing.FOREIGN_CARD_POLICY_REFUND)
    monkeypatch.setattr(credits, "ENFORCE", True)
    monkeypatch.setattr(fx, "get_usd_to_inr", lambda force=False: 95.0)
    monkeypatch.setattr(enterprise, "AUTO_RENEW", False)      # one-off orders unless a test says so
    monkeypatch.setattr(enterprise, "_enforce_rate_limit_or_429", lambda **kw: None)
    monkeypatch.setattr(enterprise, "send_enterprise_welcome_email", lambda **kw: True)
    fake = FakeRazorpay()
    monkeypatch.setattr(enterprise, "_razorpay_request", fake)
    monkeypatch.setattr(enterprise, "_razorpay_enabled", lambda: True)
    monkeypatch.setattr(enterprise, "_razorpay_credentials", lambda: ("rzp_test_key", KEY_SECRET))
    monkeypatch.setenv("RAZORPAY_CREDITS_WEBHOOK_SECRET", WEBHOOK_SECRET)

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
        yield SimpleNamespace(client=client, db=db, org=org, owner=owner, rzp=fake)
    db.close()
    engine.dispose()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def set_trial(c):
    sub = billing.get_or_create_org_subscription(c.db, c.org.id)
    sub.plan, sub.status = "sandbox", "trialing"
    sub.trial_ends_at = datetime.utcnow() + timedelta(days=10)
    sub.current_period_end = None
    c.db.commit()
    return sub


def set_country(c, code):
    c.org.country_code = code
    c.db.commit()


def sub_row(c):
    c.db.expire_all()
    return c.db.query(models.EnterpriseSubscription).filter_by(organization_id=c.org.id).one()


def sign(a, b):
    return hmac.new(KEY_SECRET.encode(), f"{a}|{b}".encode(), hashlib.sha256).hexdigest()


def authorized(body, payment_id, *, international, order=True):
    """A payment entity as Razorpay reports it once authorised (manual capture)."""
    return {
        "id": payment_id, "amount": body["amount"], "currency": body["currency"],
        "order_id": body["order_id"] if order else None,
        "status": "authorized", "captured": False, "international": international,
        "method": "card",
        "card": {"international": international, "network": "Visa", "issuer": None if international else "HDFC"},
    }


def plan_checkout(c, plan="starter", cycle="monthly"):
    res = c.client.post("/api/enterprise/billing/checkout", json={"plan": plan, "billing_cycle": cycle})
    assert res.status_code == 200, res.text
    return res.json()


def plan_verify(c, order_or_sub_id, payment_id, signature):
    return c.client.post("/api/enterprise/billing/verify", json={
        "razorpay_order_id": order_or_sub_id, "razorpay_payment_id": payment_id,
        "razorpay_signature": signature,
    })


def credits_checkout(c, package):
    res = c.client.post("/api/enterprise/credits/topup/checkout", json={"package": package})
    assert res.status_code == 200, res.text
    return res.json()


def first_package_key():
    return credits.packages_payload("INR")[0]["key"]


def webhook(c, event_name, entity):
    body = json.dumps({"event": event_name, "payload": {"payment": {"entity": entity}}}).encode()
    signature = hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return c.client.post(
        "/api/enterprise/webhook/razorpay-credits", content=body,
        headers={"X-Razorpay-Signature": signature, "Content-Type": "application/json"},
    )


def wallet_balance(c):
    """Credits granted by top-ups (the ledger, not the balance: a trial's own allowance is
    granted lazily on the first wallet read and would blur the count)."""
    c.db.expire_all()
    rows = c.db.query(models.EnterpriseCreditTransaction).filter_by(
        organization_id=c.org.id, type="topup").all()
    return sum(int(r.credits) for r in rows)


# ---------------------------------------------------------------------------
# Who is fenced
# ---------------------------------------------------------------------------

def test_domestic_only_applies_to_rupee_charges_billed_in_india():
    assert billing.domestic_only_charge("INR", "IN") is True
    assert billing.domestic_only_charge("INR", None) is True        # unknown = billed as Indian
    assert billing.domestic_only_charge("inr", "in") is True
    # Nepal & co. are billed in rupees but hold no Indian payment methods.
    assert billing.domestic_only_charge("INR", "NP") is False
    assert billing.domestic_only_charge("USD", "IN") is False
    assert billing.domestic_only_charge("GBP", "GB") is False


def test_the_kill_switch_turns_the_rule_off(monkeypatch):
    monkeypatch.setattr(billing, "INR_DOMESTIC_ONLY", False)
    assert billing.domestic_only_charge("INR", "IN") is False


def test_an_unknown_policy_falls_back_to_review(monkeypatch):
    monkeypatch.setenv("ENTERPRISE_INR_FOREIGN_CARD_POLICY", "refund-everything")
    assert billing._foreign_card_policy_env() == billing.FOREIGN_CARD_POLICY_REVIEW
    monkeypatch.setenv("ENTERPRISE_INR_FOREIGN_CARD_POLICY", "Reprice")
    assert billing._foreign_card_policy_env() == billing.FOREIGN_CARD_POLICY_REPRICE
    monkeypatch.delenv("ENTERPRISE_INR_FOREIGN_CARD_POLICY")
    assert billing._foreign_card_policy_env() == billing.FOREIGN_CARD_POLICY_REVIEW


def test_foreign_instrument_reads_either_flag():
    assert billing.paid_with_foreign_instrument({"international": True}) is True
    assert billing.paid_with_foreign_instrument({"international": False, "card": {"international": True}}) is True
    assert billing.paid_with_foreign_instrument({"method": "upi", "international": False}) is False
    assert billing.paid_with_foreign_instrument(None) is False


# ---------------------------------------------------------------------------
# Checkout: the order carries the fence; other orders don't
# ---------------------------------------------------------------------------

def test_inr_plan_order_is_manual_capture_and_says_so(ctx):
    set_trial(ctx)
    body = plan_checkout(ctx)
    assert body["currency"] == "INR" and body["checkout_mode"] == "order"
    (_, order_payload), = ctx.rzp.posted("/orders")
    assert order_payload["payment"]["capture"] == "manual"
    assert order_payload["payment"]["capture_options"] == {"refund_speed": "normal"}   # Razorpay's expiry
    assert body["domestic_only"] is True
    assert body["payment_rule"] == billing.DOMESTIC_ONLY_RULE
    assert {"method": "wallet", "wallets": ["paypal"]} in body["checkout_config"]["display"]["hide"]
    row = ctx.db.query(models.EnterpriseSubscriptionPayment).filter_by(razorpay_order_id=body["order_id"]).one()
    assert row.domestic_only is True


def test_foreign_currency_order_is_untouched(ctx):
    set_trial(ctx)
    set_country(ctx, "GB")
    body = plan_checkout(ctx)
    assert body["currency"] == "GBP"
    (_, order_payload), = ctx.rzp.posted("/orders")
    assert "payment" not in order_payload
    assert body["domestic_only"] is False and body["checkout_config"] is None
    row = ctx.db.query(models.EnterpriseSubscriptionPayment).filter_by(razorpay_order_id=body["order_id"]).one()
    assert row.domestic_only is False


def test_nepal_rupee_order_is_not_fenced(ctx):
    set_trial(ctx)
    set_country(ctx, "NP")
    body = plan_checkout(ctx)
    assert body["currency"] == "INR"
    (_, order_payload), = ctx.rzp.posted("/orders")
    assert "payment" not in order_payload
    assert body["domestic_only"] is False


def test_a_configured_capture_window_is_sent_and_clamped(monkeypatch):
    monkeypatch.setattr(billing, "INR_MANUAL_CAPTURE_EXPIRY_MINUTES", 60)
    assert billing.domestic_only_order_options()["payment"]["capture_options"] == {
        "refund_speed": "normal", "manual_expiry_period": 60,
    }
    monkeypatch.setattr(billing, "INR_MANUAL_CAPTURE_EXPIRY_MINUTES", 5)   # below Razorpay's 12
    assert "manual_expiry_period" not in billing.domestic_only_order_options()["payment"]["capture_options"]


def test_manual_capture_switch_off_leaves_orders_auto_captured(ctx, monkeypatch):
    monkeypatch.setattr(billing, "INR_MANUAL_CAPTURE", False)
    set_trial(ctx)
    body = plan_checkout(ctx)
    (_, order_payload), = ctx.rzp.posted("/orders")
    assert "payment" not in order_payload
    assert body["domestic_only"] is True          # still checked after capture


def test_inr_mandate_row_is_domestic_only_without_checkout_config(ctx, monkeypatch):
    monkeypatch.setattr(enterprise, "AUTO_RENEW", True)
    set_trial(ctx)
    body = plan_checkout(ctx)
    assert body["checkout_mode"] == "subscription"
    assert body["domestic_only"] is True and body["payment_rule"] == billing.DOMESTIC_ONLY_RULE
    assert "checkout_config" not in body
    row = ctx.db.query(models.EnterpriseSubscriptionPayment).filter_by(
        razorpay_subscription_id=body["subscription_id"]).one()
    assert row.domestic_only is True


def test_credit_topup_order_is_manual_capture_for_india_only(ctx):
    set_trial(ctx)
    body = credits_checkout(ctx, first_package_key())
    assert body["domestic_only"] is True and body["checkout_config"]
    (_, order_payload), = ctx.rzp.posted("/orders")
    assert order_payload["payment"]["capture"] == "manual"

    set_country(ctx, "US")
    ctx.org.billing_currency = None
    ctx.db.commit()
    body = credits_checkout(ctx, first_package_key())
    assert body["currency"] == "USD" and body["domestic_only"] is False
    assert "payment" not in ctx.rzp.posted("/orders")[-1][1]


def test_portal_payloads_carry_the_one_line_rule(ctx):
    set_trial(ctx)
    sub = ctx.client.get("/api/enterprise/billing/subscription").json()["subscription"]
    assert sub["inr_payment_rule"] == billing.DOMESTIC_ONLY_RULE and sub["inr_barred"] is False
    wallet = ctx.client.get("/api/enterprise/credits/wallet").json()
    assert wallet["inr_payment_rule"] == billing.DOMESTIC_ONLY_RULE
    set_country(ctx, "GB")
    assert ctx.client.get("/api/enterprise/billing/subscription").json()["subscription"]["inr_payment_rule"] is None


# ---------------------------------------------------------------------------
# /billing/verify on a one-off order
# ---------------------------------------------------------------------------

def test_domestic_payment_is_captured_and_activates(ctx):
    set_trial(ctx)
    body = plan_checkout(ctx)
    ctx.rzp.payments["pay_DOM1"] = authorized(body, "pay_DOM1", international=False)
    res = plan_verify(ctx, body["order_id"], "pay_DOM1", sign(body["order_id"], "pay_DOM1"))
    assert res.status_code == 200, res.text
    assert ctx.rzp.posted("/payments/pay_DOM1/capture") == [
        ("/payments/pay_DOM1/capture", {"amount": body["amount"], "currency": "INR"})
    ]
    assert sub_row(ctx).plan == "starter"


def test_refund_policy_never_captures_a_foreign_card_and_keeps_the_trial(ctx):
    trial = set_trial(ctx)
    trial_end = trial.trial_ends_at
    body = plan_checkout(ctx)
    ctx.rzp.payments["pay_FOR1"] = authorized(body, "pay_FOR1", international=True)
    res = plan_verify(ctx, body["order_id"], "pay_FOR1", sign(body["order_id"], "pay_FOR1"))
    assert res.status_code == 402
    assert res.json()["code"] == "inr_foreign_card"
    assert "issued outside India" in res.json()["detail"] and "wasn't taken" in res.json()["detail"]
    assert len(res.json()["detail"]) < 300                      # the portal's message cap
    assert ctx.rzp.posted("/capture") == [] and ctx.rzp.posted("/refund") == []
    sub = sub_row(ctx)
    assert sub.plan == "sandbox" and billing._as_naive(sub.trial_ends_at) == billing._as_naive(trial_end)
    row = ctx.db.query(models.EnterpriseSubscriptionPayment).filter_by(razorpay_order_id=body["order_id"]).one()
    assert row.status == billing.FOREIGN_CARD_REFUSED and row.is_international is True
    assert row.razorpay_payment_id == "pay_FOR1"
    # Not revenue, not "has paid": the billing country stays editable.
    assert credits._has_ever_paid(ctx.db, ctx.org.id) is False

    # A replay changes nothing and is told the same.
    again = plan_verify(ctx, body["order_id"], "pay_FOR1", sign(body["order_id"], "pay_FOR1"))
    assert again.status_code == 402 and again.json()["code"] == "inr_foreign_card"
    assert ctx.rzp.posted("/capture") == []
    assert sub_row(ctx).plan == "sandbox"


def test_review_policy_captures_a_foreign_card_and_flags_it(ctx, monkeypatch, caplog):
    monkeypatch.setattr(billing, "INR_FOREIGN_CARD_POLICY", billing.FOREIGN_CARD_POLICY_REVIEW)
    set_trial(ctx)
    body = plan_checkout(ctx)
    ctx.rzp.payments["pay_REV1"] = authorized(body, "pay_REV1", international=True)
    with caplog.at_level("ERROR"):
        res = plan_verify(ctx, body["order_id"], "pay_REV1", sign(body["order_id"], "pay_REV1"))
    assert res.status_code == 200, res.text
    assert ctx.rzp.posted("/payments/pay_REV1/capture")
    assert sub_row(ctx).plan == "starter"
    row = ctx.db.query(models.EnterpriseSubscriptionPayment).filter_by(razorpay_order_id=body["order_id"]).one()
    assert row.status == "verified" and row.is_international is True
    assert any("inr-card-rule" in r.getMessage() for r in caplog.records)
    ctx.db.refresh(ctx.org)
    assert ctx.org.inr_barred_at is None


def test_reprice_policy_accepts_and_moves_the_org_off_inr(ctx, monkeypatch):
    monkeypatch.setattr(billing, "INR_FOREIGN_CARD_POLICY", billing.FOREIGN_CARD_POLICY_REPRICE)
    set_trial(ctx)
    body = plan_checkout(ctx)
    ctx.rzp.payments["pay_REP1"] = authorized(body, "pay_REP1", international=True)
    res = plan_verify(ctx, body["order_id"], "pay_REP1", sign(body["order_id"], "pay_REP1"))
    assert res.status_code == 200, res.text
    assert "billed in USD" in res.json()["message"]
    assert sub_row(ctx).plan == "starter"
    ctx.db.refresh(ctx.org)
    assert ctx.org.inr_barred_at is not None
    # Every later quote and checkout is on the foreign ladder, though the org still says IN.
    assert billing.charge_currency_for_org(ctx.db, ctx.org, None) == "USD"
    state = ctx.client.get("/api/enterprise/billing/subscription").json()["subscription"]
    assert state["inr_barred"] is True and state["inr_payment_rule"] is None
    assert plan_checkout(ctx, "growth")["currency"] == "USD"


def test_foreign_currency_payment_with_a_foreign_card_is_unaffected(ctx):
    set_trial(ctx)
    set_country(ctx, "GB")
    body = plan_checkout(ctx)
    ctx.rzp.payments["pay_GBP1"] = {
        "id": "pay_GBP1", "amount": body["amount"], "currency": "GBP", "order_id": body["order_id"],
        "status": "captured", "captured": True, "international": True,
    }
    res = plan_verify(ctx, body["order_id"], "pay_GBP1", sign(body["order_id"], "pay_GBP1"))
    assert res.status_code == 200, res.text
    assert sub_row(ctx).plan == "starter"
    assert ctx.rzp.posted("/refund") == [] and ctx.rzp.posted("/capture") == []


# ---------------------------------------------------------------------------
# Mandates: no manual capture, so the check runs after the charge
# ---------------------------------------------------------------------------

def _mandate_checkout(c, monkeypatch):
    monkeypatch.setattr(enterprise, "AUTO_RENEW", True)
    body = plan_checkout(c)
    assert body["checkout_mode"] == "subscription"
    return body


def test_foreign_card_mandate_is_refunded_and_cancelled_once(ctx, monkeypatch):
    set_trial(ctx)
    body = _mandate_checkout(ctx, monkeypatch)
    sub_id = body["subscription_id"]
    ctx.rzp.payments["pay_MAN1"] = {
        "id": "pay_MAN1", "amount": body["amount"], "currency": "INR", "status": "captured",
        "captured": True, "international": True, "subscription_id": sub_id,
    }
    res = plan_verify(ctx, sub_id, "pay_MAN1", sign("pay_MAN1", sub_id))
    assert res.status_code == 402 and res.json()["code"] == "inr_foreign_card"
    assert "refunded it in full" in res.json()["detail"]
    assert ctx.rzp.posted("/payments/pay_MAN1/refund")[0][1]["amount"] == body["amount"]
    assert ("POST", f"/subscriptions/{sub_id}/cancel", {"cancel_at_cycle_end": 0}) in ctx.rzp.calls
    row = ctx.db.query(models.EnterpriseSubscriptionPayment).filter_by(razorpay_subscription_id=sub_id).one()
    assert row.status == billing.FOREIGN_CARD_REFUSED and row.refunded_amount_paise == body["amount"]
    sub = sub_row(ctx)
    assert sub.plan == "sandbox" and sub.razorpay_subscription_id is None

    # The same charge arriving by webhook afterwards is already handled: no second refund.
    out = webhook(ctx, "payment.captured", ctx.rzp.payments["pay_MAN1"])
    assert out.status_code == 200
    assert len(ctx.rzp.posted("/refund")) == 1
    assert sub_row(ctx).plan == "sandbox"


def test_webhook_refusal_of_a_first_charge_is_honoured_by_the_late_browser_verify(ctx, monkeypatch):
    set_trial(ctx)
    body = _mandate_checkout(ctx, monkeypatch)
    sub_id = body["subscription_id"]
    entity = {
        "id": "pay_MAN2", "amount": body["amount"], "currency": "INR", "status": "captured",
        "captured": True, "international": True, "subscription_id": sub_id,
    }
    ctx.rzp.payments["pay_MAN2"] = dict(entity)
    assert webhook(ctx, "payment.captured", entity).json()["status"] == "refused"
    assert len(ctx.rzp.posted("/refund")) == 1
    res = plan_verify(ctx, sub_id, "pay_MAN2", sign("pay_MAN2", sub_id))
    assert res.status_code == 402 and res.json()["code"] == "inr_foreign_card"
    assert len(ctx.rzp.posted("/refund")) == 1
    assert sub_row(ctx).plan == "sandbox"


def test_reprice_mandate_stops_at_the_end_of_the_paid_period(ctx, monkeypatch):
    monkeypatch.setattr(billing, "INR_FOREIGN_CARD_POLICY", billing.FOREIGN_CARD_POLICY_REPRICE)
    set_trial(ctx)
    body = _mandate_checkout(ctx, monkeypatch)
    sub_id = body["subscription_id"]
    ctx.rzp.payments["pay_MAN3"] = {
        "id": "pay_MAN3", "amount": body["amount"], "currency": "INR", "status": "captured",
        "captured": True, "international": True, "subscription_id": sub_id,
    }
    res = plan_verify(ctx, sub_id, "pay_MAN3", sign("pay_MAN3", sub_id))
    assert res.status_code == 200, res.text
    assert "won't renew in rupees" in res.json()["message"]
    assert ("POST", f"/subscriptions/{sub_id}/cancel", {"cancel_at_cycle_end": 1}) in ctx.rzp.calls
    sub = sub_row(ctx)
    assert sub.plan == "starter" and sub.cancel_at_period_end is True
    assert ctx.rzp.posted("/refund") == []


def _seed_mandate(c, *, domestic_only, sub_id="sub_RENEW1", amount=176_882):
    c.db.add(models.EnterpriseSubscriptionPayment(
        organization_id=c.org.id, plan="starter", billing_cycle="monthly", amount_paise=amount,
        currency="INR", razorpay_order_id=sub_id, razorpay_subscription_id=sub_id,
        razorpay_payment_id="pay_FIRST_" + sub_id, status="verified", domestic_only=domestic_only,
        verified_at=datetime.utcnow() - timedelta(days=30),
    ))
    sub = billing.get_or_create_org_subscription(c.db, c.org.id)
    sub.plan, sub.status = "starter", "active"
    sub.current_period_end = datetime.utcnow() + timedelta(hours=2)
    sub.razorpay_subscription_id, sub.mandate_status = sub_id, "active"
    c.db.commit()
    return sub_id, amount


def _renewal(sub_id, payment_id, amount, international=True):
    return {"event": "subscription.charged", "payload": {
        "payment": {"entity": {"id": payment_id, "subscription_id": sub_id, "amount": amount,
                               "currency": "INR", "status": "captured", "captured": True,
                               "international": international}},
        "subscription": {"entity": {"id": sub_id}},
    }}


def test_foreign_card_renewal_on_a_domestic_only_mandate_is_refunded(ctx):
    sub_id, amount = _seed_mandate(ctx, domestic_only=True)
    end_before = billing._as_naive(sub_row(ctx).current_period_end)
    ctx.rzp.payments["pay_REN1"] = {"id": "pay_REN1", "amount": amount, "currency": "INR"}
    out = enterprise._handle_subscription_charged(ctx.db, event=_renewal(sub_id, "pay_REN1", amount))
    assert out["status"] == "refused"
    assert ctx.rzp.posted("/payments/pay_REN1/refund")[0][1]["amount"] == amount
    sub = sub_row(ctx)
    assert billing._as_naive(sub.current_period_end) == end_before        # not extended
    assert sub.mandate_status == "cancelled" and sub.cancel_at_period_end is True
    charge = ctx.db.query(models.EnterpriseSubscriptionPayment).filter_by(razorpay_payment_id="pay_REN1").one()
    assert charge.status == billing.FOREIGN_CARD_REFUSED and charge.included_credits == 0
    # Redelivered: idempotent on the payment id, no second refund.
    again = enterprise._handle_subscription_charged(ctx.db, event=_renewal(sub_id, "pay_REN1", amount))
    assert again == {"status": "ok", "idempotent": True}
    assert len(ctx.rzp.posted("/refund")) == 1


def test_mandates_sold_before_the_rule_renew_unchanged(ctx):
    sub_id, amount = _seed_mandate(ctx, domestic_only=False)
    out = enterprise._handle_subscription_charged(ctx.db, event=_renewal(sub_id, "pay_OLD1", amount))
    assert out["status"] == "ok"
    assert ctx.rzp.posted("/refund") == []
    assert billing._as_naive(sub_row(ctx).current_period_end) > datetime.utcnow() + timedelta(days=29)


# ---------------------------------------------------------------------------
# Credit top-ups: browser verify and webhook
# ---------------------------------------------------------------------------

def _credits_verify(c, body, payment_id):
    return c.client.post("/api/enterprise/credits/topup/verify", json={
        "razorpay_order_id": body["order_id"], "razorpay_payment_id": payment_id,
        "razorpay_signature": sign(body["order_id"], payment_id),
    })


def test_credits_foreign_card_is_refused_and_credits_nothing(ctx):
    set_trial(ctx)
    before = wallet_balance(ctx)
    body = credits_checkout(ctx, first_package_key())
    ctx.rzp.payments["pay_CR1"] = authorized(body, "pay_CR1", international=True)
    ctx.rzp.orders[body["order_id"]]["status"] = "attempted"
    res = _credits_verify(ctx, body, "pay_CR1")
    assert res.status_code == 402 and res.json()["code"] == "inr_foreign_card"
    assert "Nothing was added to your wallet" in res.json()["detail"]
    assert ctx.rzp.posted("/capture") == []
    assert wallet_balance(ctx) == before
    row = ctx.db.query(models.EnterpriseCreditPayment).filter_by(razorpay_order_id=body["order_id"]).one()
    assert row.status == billing.FOREIGN_CARD_REFUSED

    # The webhook for the same authorisation agrees and still captures nothing.
    out = webhook(ctx, "payment.authorized", ctx.rzp.payments["pay_CR1"])
    assert out.json()["status"] == "refused"
    assert ctx.rzp.posted("/capture") == [] and wallet_balance(ctx) == before


def test_credits_domestic_payment_is_captured_then_credited_once(ctx):
    set_trial(ctx)
    before = wallet_balance(ctx)
    body = credits_checkout(ctx, first_package_key())
    ctx.rzp.payments["pay_CR2"] = authorized(body, "pay_CR2", international=False)
    ctx.rzp.orders[body["order_id"]]["status"] = "attempted"
    res = _credits_verify(ctx, body, "pay_CR2")
    assert res.status_code == 200, res.text
    assert len(ctx.rzp.posted("/payments/pay_CR2/capture")) == 1
    gained = wallet_balance(ctx) - before
    assert gained == body["total_credits"]
    # payment.captured follows our capture: no second grant.
    assert webhook(ctx, "payment.captured", ctx.rzp.payments["pay_CR2"]).json()["status"] == "ok"
    assert wallet_balance(ctx) - before == gained


def test_credits_webhook_captures_an_abandoned_domestic_authorisation(ctx):
    set_trial(ctx)
    before = wallet_balance(ctx)
    body = credits_checkout(ctx, first_package_key())
    ctx.rzp.payments["pay_CR3"] = authorized(body, "pay_CR3", international=False)
    out = webhook(ctx, "payment.authorized", ctx.rzp.payments["pay_CR3"])
    assert out.json()["status"] == "ok"
    assert len(ctx.rzp.posted("/payments/pay_CR3/capture")) == 1
    assert wallet_balance(ctx) - before == body["total_credits"]


def test_webhook_ignores_authorisations_of_auto_captured_orders(ctx):
    set_trial(ctx)
    set_country(ctx, "US")
    body = credits_checkout(ctx, first_package_key())
    entity = authorized(body, "pay_CR4", international=True)
    ctx.rzp.payments["pay_CR4"] = entity
    out = webhook(ctx, "payment.authorized", entity)
    assert out.json() == {"status": "ignored", "reason": "not_captured"}
    assert ctx.rzp.posted("/capture") == []


def test_a_failed_refund_is_left_due_and_retried_on_the_next_delivery(ctx, monkeypatch):
    monkeypatch.setattr(billing, "INR_MANUAL_CAPTURE", False)    # order auto-captured
    set_trial(ctx)
    before = wallet_balance(ctx)
    body = credits_checkout(ctx, first_package_key())
    entity = {
        "id": "pay_CR5", "amount": body["amount"], "currency": "INR", "order_id": body["order_id"],
        "status": "captured", "captured": True, "international": True,
    }
    ctx.rzp.payments["pay_CR5"] = dict(entity)
    ctx.rzp.fail_refunds = True
    assert webhook(ctx, "payment.captured", entity).json()["status"] == "refused"
    row = ctx.db.query(models.EnterpriseCreditPayment).filter_by(razorpay_order_id=body["order_id"]).one()
    assert row.status == billing.FOREIGN_CARD_REFUND_DUE
    assert wallet_balance(ctx) == before

    ctx.rzp.fail_refunds = False
    assert webhook(ctx, "payment.captured", entity).json()["status"] == "refused"
    ctx.db.expire_all()
    row = ctx.db.query(models.EnterpriseCreditPayment).filter_by(razorpay_order_id=body["order_id"]).one()
    assert row.status == billing.FOREIGN_CARD_REFUSED and row.refunded_amount_paise == body["amount"]
    assert wallet_balance(ctx) == before
    # A third delivery does not refund again.
    webhook(ctx, "payment.captured", entity)
    assert len([1 for m, p, _ in ctx.rzp.calls if m == "POST" and p.endswith("/refund")]) == 2


# ---------------------------------------------------------------------------
# Plan order reconciled by webhook
# ---------------------------------------------------------------------------

def test_plan_webhook_refuses_a_foreign_authorisation_and_captures_a_domestic_one(ctx):
    set_trial(ctx)
    body = plan_checkout(ctx)
    out = webhook(ctx, "payment.authorized", authorized(body, "pay_PW1", international=True))
    assert out.json()["status"] == "refused"
    assert ctx.rzp.posted("/capture") == [] and sub_row(ctx).plan == "sandbox"

    body2 = plan_checkout(ctx)
    ctx.rzp.payments["pay_PW2"] = authorized(body2, "pay_PW2", international=False)
    out = webhook(ctx, "payment.authorized", ctx.rzp.payments["pay_PW2"])
    assert out.json()["status"] == "ok"
    assert len(ctx.rzp.posted("/payments/pay_PW2/capture")) == 1
    assert sub_row(ctx).plan == "starter"


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def test_columns_exist_on_the_models():
    tables = {
        "enterprise_subscription_payments": models.EnterpriseSubscriptionPayment,
        "enterprise_credit_payments": models.EnterpriseCreditPayment,
        "enterprise_organizations": models.EnterpriseOrganization,
    }
    for table, columns in schema_patch._INR_DOMESTIC_ONLY_COLUMNS.items():
        model_cols = set(tables[table].__table__.columns.keys())
        for col, _ddl in columns:
            assert col in model_cols, f"{table}.{col} patched but missing from the model"


def test_column_patch_is_additive_and_idempotent(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    monkeypatch.setattr(schema_patch, "engine", engine)
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE enterprise_credit_payments (id INTEGER PRIMARY KEY, organization_id INTEGER, "
            "amount_paise INTEGER, razorpay_order_id VARCHAR)"
        ))
        conn.execute(text(
            "INSERT INTO enterprise_credit_payments (id, organization_id, amount_paise, razorpay_order_id) "
            "VALUES (1, 1, 100, 'order_1')"
        ))
        conn.execute(text("CREATE TABLE enterprise_organizations (id INTEGER PRIMARY KEY, company_name VARCHAR)"))
    schema_patch.ensure_enterprise_pricing_v2_columns()
    schema_patch.ensure_enterprise_pricing_v2_columns()
    cols = {c["name"] for c in inspect(engine).get_columns("enterprise_credit_payments")}
    assert "domestic_only" in cols
    assert "inr_barred_at" in {c["name"] for c in inspect(engine).get_columns("enterprise_organizations")}
    with engine.connect() as conn:
        assert conn.execute(text("SELECT domestic_only FROM enterprise_credit_payments")).scalar() in (0, False)
    engine.dispose()


# ---------------------------------------------------------------------------
# The assistant's help states the rule, and only the consequence the server applies
# ---------------------------------------------------------------------------

def test_help_states_the_rule_and_the_live_policy(monkeypatch):
    from app import enterprise_help

    monkeypatch.setattr(billing, "INR_FOREIGN_CARD_POLICY", billing.FOREIGN_CARD_POLICY_REVIEW)
    text = enterprise_help.render_topic("credits-billing")["content"]
    assert "Indian payment method: UPI, netbanking, or an India-issued card or wallet" in text
    assert "isn't accepted" not in text and "local currency (or USD)" not in text

    monkeypatch.setattr(billing, "INR_FOREIGN_CARD_POLICY", billing.FOREIGN_CARD_POLICY_REFUND)
    assert "isn't accepted for a rupee price" in enterprise_help.render_topic("credits-billing")["content"]

    monkeypatch.setattr(billing, "INR_FOREIGN_CARD_POLICY", billing.FOREIGN_CARD_POLICY_REPRICE)
    assert "local currency (or USD)" in enterprise_help.render_topic("credits-billing")["content"]

    monkeypatch.setattr(billing, "INR_DOMESTIC_ONLY", False)
    assert "Indian payment method" not in enterprise_help.render_topic("credits-billing")["content"]
    index = {t["key"]: t["summary"] for t in enterprise_help.topics_index()}
    assert "payment methods" in index["credits-billing"]
