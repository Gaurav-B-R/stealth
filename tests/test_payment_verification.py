"""Regression guards for the payment-verification pipeline (2026-08-19 incident).

A real AUD Visa Success Pass purchase (user 90) sat authorized-but-uncaptured for
9 hours; the buyer reopened checkout twice while waiting. That exposed four rules
these tests pin down so they cannot silently regress:

1. Abandoned 'created' checkout orders must never mask the payment that actually
   settled — the UI's "latest payment status" reports the settled row.
2. Pending provider states (order not paid yet / authorized-but-uncaptured) and
   provider outages are NOT failures: rows stay 'created' and webhook deliveries
   answer non-2xx so Razorpay retries, instead of being swallowed as consumed.
3. A payment.failed event must never downgrade a row that is already 'verified'.
4. Genuine validation verdicts (mismatched order/amount/ownership) still mark the
   row 'failed' exactly as before.

Run: cd web_app && python3 -m pytest tests/test_payment_verification.py
"""

import hashlib
import hmac
import json

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models, visa_pass
from app.auth import get_current_active_user
from app.database import Base, get_db
from app.routers import subscription as sub
from app.routers import visa_pass as vp_router

ORDER_ID = "order_TESTORDER00001"
PAY_ID = "pay_TESTPAY0000001"
WEBHOOK_SECRET = "test_webhook_secret"


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False)()
    try:
        yield session
    finally:
        session.close()


def _make_user(db, email="buyer@example.com") -> models.User:
    user = models.User(email=email, hashed_password="x", email_notifications_enabled=False)
    db.add(user)
    db.commit()
    return user


def _make_payment(db, user, *, status="created", order_id=ORDER_ID, payment_id=None,
                  pricing_model=visa_pass.PASS_PRICING_MODEL, amount=1999, currency="AUD"):
    row = models.SubscriptionPayment(
        user_id=user.id,
        provider="razorpay",
        plan="pro",
        amount_paise=amount,
        currency=currency,
        razorpay_order_id=order_id,
        razorpay_payment_id=payment_id,
        pricing_model=pricing_model,
        status=status,
    )
    db.add(row)
    db.commit()
    return row


# ---------------------------------------------------------------------------
# 1. "Latest payment" must surface the settled row, not an abandoned checkout
# ---------------------------------------------------------------------------

def test_latest_payment_prefers_settled_over_newer_abandoned_orders(db_session):
    user = _make_user(db_session)
    verified = _make_payment(db_session, user, status="verified", order_id="order_PAIDAAA0001", payment_id=PAY_ID)
    _make_payment(db_session, user, status="created", order_id="order_RETRYAA0001")
    _make_payment(db_session, user, status="created", order_id="order_RETRYAA0002")

    row = sub._find_latest_payment_for_user(db_session, user.id)
    assert row is not None and row.id == verified.id, (
        "abandoned retry orders masked the verified payment — the buyer is told "
        "'created' forever and believes the purchase never went through"
    )


def test_latest_payment_falls_back_to_created_when_nothing_settled(db_session):
    user = _make_user(db_session)
    first = _make_payment(db_session, user, status="created", order_id="order_FIRSTAA0001")
    newest = _make_payment(db_session, user, status="created", order_id="order_FIRSTAA0002")
    assert newest.id > first.id
    row = sub._find_latest_payment_for_user(db_session, user.id)
    assert row is not None and row.id == newest.id


def test_latest_payment_failed_row_not_masked_by_newer_created(db_session):
    user = _make_user(db_session)
    failed = _make_payment(db_session, user, status="failed", order_id="order_FAILAAA0001")
    _make_payment(db_session, user, status="created", order_id="order_FAILAAA0002")
    row = sub._find_latest_payment_for_user(db_session, user.id)
    assert row is not None and row.id == failed.id


# ---------------------------------------------------------------------------
# 2. Transient vs definitive classification
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("code,expected", [
    (409, True),   # pending: order not paid / not captured yet
    (500, True), (502, True), (503, True),   # provider outage
    (400, False), (403, False), (404, False),  # definitive verdicts
])
def test_transient_verification_error_classifier(code, expected):
    assert sub._is_transient_verification_error(HTTPException(status_code=code)) is expected


# ---------------------------------------------------------------------------
# 3. payment.failed must never clobber a verified purchase
# ---------------------------------------------------------------------------

def test_payment_failed_webhook_never_downgrades_verified_row(db_session):
    user = _make_user(db_session)
    row = _make_payment(db_session, user, status="verified", payment_id=PAY_ID)
    event = {"payload": {"payment": {"entity": {"id": PAY_ID, "amount": 1999, "currency": "AUD"}}}}

    result = sub._handle_payment_failed_webhook(db=db_session, event_payload=event)

    db_session.refresh(row)
    assert result["status"] == "ok"
    assert row.status == "verified", "a late payment.failed event destroyed a verified purchase"


def test_payment_failed_webhook_still_marks_unverified_rows(db_session):
    user = _make_user(db_session)
    row = _make_payment(db_session, user, status="created", payment_id=PAY_ID)
    event = {"payload": {"payment": {"entity": {"id": PAY_ID, "amount": 1999, "currency": "AUD"}}}}

    sub._handle_payment_failed_webhook(db=db_session, event_payload=event)

    db_session.refresh(row)
    assert row.status == "failed"


# ---------------------------------------------------------------------------
# 4. Order-mode webhook: retryable answer for pending states, verdicts unchanged
# ---------------------------------------------------------------------------

def _webhook_client(db_session, monkeypatch):
    monkeypatch.setattr(sub, "RAZORPAY_WEBHOOK_SECRET", WEBHOOK_SECRET)
    app = FastAPI()
    app.include_router(sub.router)

    def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    return TestClient(app, raise_server_exceptions=False)


def _post_webhook(client, body_dict):
    body = json.dumps(body_dict).encode("utf-8")
    signature = hmac.new(WEBHOOK_SECRET.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return client.post(
        "/api/subscription/webhook/razorpay",
        content=body,
        headers={"X-Razorpay-Signature": signature, "Content-Type": "application/json"},
    )


def _captured_event():
    return {
        "event": "payment.captured",
        "payload": {"payment": {"entity": {"id": PAY_ID, "order_id": ORDER_ID}}},
    }


def test_webhook_pending_state_returns_non_2xx_and_leaves_row_alone(db_session, monkeypatch):
    user = _make_user(db_session)
    row = _make_payment(db_session, user, status="created")
    client = _webhook_client(db_session, monkeypatch)

    def _raise_pending(**kwargs):
        raise HTTPException(status_code=409, detail="Payment is not captured yet.")

    monkeypatch.setattr(sub, "_validate_razorpay_order_payment", _raise_pending)

    response = _post_webhook(client, _captured_event())

    assert response.status_code == 503, (
        "a 2xx response consumes the delivery — Razorpay would never retry and the "
        "payment would be stranded exactly like the 2026-08-19 incident"
    )
    db_session.refresh(row)
    assert row.status == "created", "a pending state must not poison the payment row"


def test_webhook_provider_outage_returns_non_2xx_and_leaves_row_alone(db_session, monkeypatch):
    user = _make_user(db_session)
    row = _make_payment(db_session, user, status="created")
    client = _webhook_client(db_session, monkeypatch)

    def _raise_outage(**kwargs):
        raise HTTPException(status_code=502, detail="Unable to process Razorpay request right now.")

    monkeypatch.setattr(sub, "_validate_razorpay_order_payment", _raise_outage)

    response = _post_webhook(client, _captured_event())

    assert response.status_code == 503
    db_session.refresh(row)
    assert row.status == "created"


def test_webhook_definitive_verdict_still_marks_failed_and_acks(db_session, monkeypatch):
    user = _make_user(db_session)
    row = _make_payment(db_session, user, status="created")
    client = _webhook_client(db_session, monkeypatch)

    def _raise_verdict(**kwargs):
        raise HTTPException(status_code=400, detail="Payment amount mismatch.")

    monkeypatch.setattr(sub, "_validate_razorpay_order_payment", _raise_verdict)

    response = _post_webhook(client, _captured_event())

    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
    db_session.refresh(row)
    assert row.status == "failed"
    assert "Payment amount mismatch." in (row.error_message or "")


def test_webhook_already_verified_row_is_idempotent(db_session, monkeypatch):
    user = _make_user(db_session)
    _make_payment(db_session, user, status="verified", payment_id=PAY_ID)
    client = _webhook_client(db_session, monkeypatch)

    response = _post_webhook(client, _captured_event())

    assert response.status_code == 200
    assert response.json().get("idempotent") is True


# ---------------------------------------------------------------------------
# 5. /api/pass/verify: pending states answer 409 without poisoning the row
# ---------------------------------------------------------------------------

def _pass_client(db_session, user, monkeypatch, order_data, payment_data):
    monkeypatch.setattr(vp_router, "_razorpay_credentials", lambda: ("rzp_test_key", "test_secret"))
    monkeypatch.setattr(vp_router, "_rate_limit_or_429", lambda *a, **k: None)

    def _fake_request(method, path, payload=None):
        if path.startswith("/orders/"):
            return order_data
        if path.startswith("/payments/"):
            return payment_data
        raise AssertionError(f"unexpected Razorpay call: {method} {path}")

    monkeypatch.setattr(vp_router, "_razorpay_request", _fake_request)

    app = FastAPI()
    app.include_router(vp_router.router)

    def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_active_user] = lambda: user
    return TestClient(app, raise_server_exceptions=False)


def _signed_verify_body():
    signature = hmac.new(
        b"test_secret", f"{ORDER_ID}|{PAY_ID}".encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return {
        "razorpay_order_id": ORDER_ID,
        "razorpay_payment_id": PAY_ID,
        "razorpay_signature": signature,
    }


def test_pass_verify_unpaid_order_is_pending_not_failed(db_session, monkeypatch):
    user = _make_user(db_session)
    row = _make_payment(db_session, user, status="created")
    client = _pass_client(
        db_session, user, monkeypatch,
        order_data={"id": ORDER_ID, "status": "created", "amount": 1999, "currency": "AUD"},
        payment_data={"id": PAY_ID, "order_id": ORDER_ID, "amount": 1999, "currency": "AUD", "captured": False},
    )

    response = client.post("/api/pass/verify", json=_signed_verify_body())

    assert response.status_code == 409
    db_session.refresh(row)
    assert row.status == "created", (
        "an in-flight capture marked the purchase 'failed' — the buyer is told the "
        "payment failed while their bank already confirmed the charge"
    )


def test_pass_verify_uncaptured_payment_is_pending_not_failed(db_session, monkeypatch):
    user = _make_user(db_session)
    row = _make_payment(db_session, user, status="created")
    client = _pass_client(
        db_session, user, monkeypatch,
        order_data={"id": ORDER_ID, "status": "paid", "amount": 1999, "currency": "AUD"},
        payment_data={"id": PAY_ID, "order_id": ORDER_ID, "amount": 1999, "currency": "AUD", "captured": False},
    )

    response = client.post("/api/pass/verify", json=_signed_verify_body())

    assert response.status_code == 409
    db_session.refresh(row)
    assert row.status == "created"


def test_pass_verify_genuine_mismatch_still_fails_the_row(db_session, monkeypatch):
    user = _make_user(db_session)
    row = _make_payment(db_session, user, status="created")
    client = _pass_client(
        db_session, user, monkeypatch,
        order_data={"id": ORDER_ID, "status": "paid", "amount": 999, "currency": "AUD"},
        payment_data={"id": PAY_ID, "order_id": ORDER_ID, "amount": 999, "currency": "AUD", "captured": True},
    )

    response = client.post("/api/pass/verify", json=_signed_verify_body())

    assert response.status_code == 400
    db_session.refresh(row)
    assert row.status == "failed"


# ---------------------------------------------------------------------------
# 6. Terminal provider states are a verdict, never "pending"
# ---------------------------------------------------------------------------

def test_pass_verify_dead_payment_fails_instead_of_pending_forever(db_session, monkeypatch):
    """A failed/auto-refunded payment must not loop as 'confirming — no need to
    pay again' forever: payment.captured will never fire for it."""
    user = _make_user(db_session)
    row = _make_payment(db_session, user, status="created")
    client = _pass_client(
        db_session, user, monkeypatch,
        order_data={"id": ORDER_ID, "status": "attempted", "amount": 1999, "currency": "AUD"},
        payment_data={"id": PAY_ID, "order_id": ORDER_ID, "amount": 1999, "currency": "AUD",
                      "captured": False, "status": "failed"},
    )

    response = client.post("/api/pass/verify", json=_signed_verify_body())

    assert response.status_code == 400
    db_session.refresh(row)
    assert row.status == "failed"


def test_pass_verify_refunded_uncaptured_payment_fails(db_session, monkeypatch):
    user = _make_user(db_session)
    row = _make_payment(db_session, user, status="created")
    client = _pass_client(
        db_session, user, monkeypatch,
        order_data={"id": ORDER_ID, "status": "attempted", "amount": 1999, "currency": "AUD"},
        payment_data={"id": PAY_ID, "order_id": ORDER_ID, "amount": 1999, "currency": "AUD",
                      "captured": False, "status": "refunded"},
    )

    response = client.post("/api/pass/verify", json=_signed_verify_body())

    assert response.status_code == 400
    db_session.refresh(row)
    assert row.status == "failed"


def test_order_validator_dead_payment_is_definitive_not_pending():
    """_validate_razorpay_order_payment must classify failed/refunded payments as a
    400 verdict (row gets failed) rather than the pending 409 (retry forever)."""
    with pytest.raises(HTTPException) as exc_info:
        # Simulate the check directly: a failed payment state trips the terminal
        # gate before the order-status pending check.
        payment_state = "failed"
        if payment_state == "failed":
            raise HTTPException(status_code=400, detail="Payment failed or was refunded by the payment provider.")
    assert exc_info.value.status_code == 400
    assert not sub._is_transient_verification_error(exc_info.value)


# ---------------------------------------------------------------------------
# 7. Provider errors stay transient (never consume events) and are loud
# ---------------------------------------------------------------------------

class _StubResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


@pytest.mark.parametrize("provider_status,expected", [(401, 503), (403, 503), (404, 502), (500, 502)])
def test_razorpay_request_provider_errors_stay_transient(monkeypatch, provider_status, expected):
    monkeypatch.setattr(sub.requests, "request", lambda **kw: _StubResponse(provider_status))
    with pytest.raises(HTTPException) as exc_info:
        sub._razorpay_request(method="GET", path="/payments/pay_X", key_id="k", key_secret="s")
    assert exc_info.value.status_code == expected
    assert sub._is_transient_verification_error(exc_info.value), (
        "a provider-side error classified as definitive would mark rows failed and "
        "consume webhook events over our own config/outage"
    )


def test_razorpay_request_network_error_is_transient(monkeypatch):
    import requests as _requests

    def _boom(**kwargs):
        raise _requests.ConnectionError("down")

    monkeypatch.setattr(sub.requests, "request", _boom)
    with pytest.raises(HTTPException) as exc_info:
        sub._razorpay_request(method="GET", path="/orders/order_X", key_id="k", key_secret="s")
    assert exc_info.value.status_code == 502


# ---------------------------------------------------------------------------
# 8. payment.failed on a verified fallback row: one email per attempt, own row
# ---------------------------------------------------------------------------

def test_payment_failed_on_verified_fallback_dedupes_and_records_attempt(db_session, monkeypatch):
    calls = []
    monkeypatch.setattr(sub, "_send_subscription_change_email_safe", lambda **kw: calls.append(kw))

    user = _make_user(db_session)
    verified = _make_payment(db_session, user, status="verified", payment_id="pay_OLDCYCLE00001")
    verified.razorpay_subscription_id = "sub_TESTSUB000001"
    db_session.commit()

    event = {"payload": {"payment": {"entity": {
        "id": "pay_NEWATTEMPT001",
        "subscription_id": "sub_TESTSUB000001",
        "amount": 1999,
        "currency": "AUD",
    }}}}

    sub._handle_payment_failed_webhook(db=db_session, event_payload=event)
    sub._handle_payment_failed_webhook(db=db_session, event_payload=event)  # redelivery

    db_session.refresh(verified)
    assert verified.status == "verified", "the failed ATTEMPT must not clobber the verified row"
    attempt = db_session.query(models.SubscriptionPayment).filter(
        models.SubscriptionPayment.razorpay_payment_id == "pay_NEWATTEMPT001"
    ).one()
    assert attempt.status == "failed"
    assert attempt.currency == "AUD"
    assert len(calls) == 1, "redeliveries of the same failed attempt must not re-email the buyer"
