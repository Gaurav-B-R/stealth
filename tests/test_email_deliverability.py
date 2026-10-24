"""Resend deliverability webhook -> per-user "email undeliverable" flag.

2026-10 incident: password-reset emails "sent" but never arrived. Resend had the addresses
on its suppression list (old hard bounce / spam complaint) and reported every send as
last_event=suppressed, but only asynchronously, and the app had no webhook for it. Users saw
"reset link sent", and the daily AI nudge kept paying Gemini to write emails nobody could
receive.

These tests pin down the fix (app/email_deliverability.py + app/routers/email_events.py):

1. The webhook only accepts Svix-signed payloads under its OWN secret
   (RESEND_DELIVERABILITY_WEBHOOK_SECRET) and records bounced / complained / suppressed,
   ignores soft bounces, and clears on suppression.removed; out-of-order retries can't
   undo a newer state.
2. A flagged user is dropped from the daily AI nudge BEFORE the snapshot/R2/Gemini work,
   from calendar digests, promos and the marketing-audience sync.
3. Transactional sends still go out, and forgot-password keeps its generic response.
4. The admin account view shows the flag + reason and can clear it.
5. The schema patch adds the columns to an existing users table, idempotently.

Every test runs on SQLite with fake payloads; no email is sent and no model is called.

Run: cd web_app && python3 -m pytest tests/test_email_deliverability.py
"""
import base64
import hashlib
import hmac
import json
import time
from datetime import date, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import email_deliverability as deliverability
from app import models
from app.database import Base, get_db
from app.routers import admin as admin_router
from app.routers import auth as auth_router
from app.routers import email_events

SECRET = "whsec_" + base64.b64encode(b"deliverability-test-signing-key!").decode()
OTHER_SECRET = "whsec_" + base64.b64encode(b"some-other-webhook-signing-key!!").decode()


@pytest.fixture
def engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def Session(engine):
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


@pytest.fixture
def db(Session):
    session = Session()
    yield session
    session.close()


@pytest.fixture
def webhook(db, monkeypatch):
    monkeypatch.setenv("RESEND_DELIVERABILITY_WEBHOOK_SECRET", SECRET)
    # The limiter is process-wide; earlier suites' calls must not 429 these.
    monkeypatch.setattr(email_events, "check_ip_rate_limit", lambda **kwargs: (True, 0))
    app = FastAPI()
    app.include_router(email_events.router)
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def _user(db, email, **extra):
    extra.setdefault("last_login_at", datetime.utcnow() - timedelta(days=1))
    user = models.User(email=email, hashed_password="test-only", is_active=True, **extra)
    db.add(user)
    db.commit()
    return user


def _signed_headers(body: bytes, *, secret=SECRET, msg_id="msg_test_1", timestamp=None):
    timestamp = str(int(time.time()) if timestamp is None else timestamp)
    key = base64.b64decode(secret[len("whsec_"):])
    signature = base64.b64encode(
        hmac.new(key, f"{msg_id}.{timestamp}.".encode() + body, hashlib.sha256).digest()
    ).decode()
    return {
        "svix-id": msg_id,
        "svix-timestamp": timestamp,
        "svix-signature": f"v1,{signature}",
        "content-type": "application/json",
    }


def _post(client, event, **sign_kwargs):
    body = json.dumps(event).encode()
    return client.post("/api/webhooks/resend/email-events", content=body, headers=_signed_headers(body, **sign_kwargs))


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _suppressed_event(to, at=None, subject="Reset your Rilono password"):
    at = at or datetime.utcnow()
    return {
        "type": "email.suppressed",
        "created_at": _iso(at),
        "data": {
            "created_at": _iso(at),
            "email_id": "56761188-7520-42d8-8898-ff6fc54ce618",
            "from": "Rilono <noreply@rilono.com>",
            "to": to if isinstance(to, list) else [to],
            "subject": subject,
            "suppressed": {
                "message": "Resend has suppressed sending to this address because it is on the "
                           "account-level suppression list.",
                "type": "OnAccountSuppressionList",
            },
        },
    }


# ---------------------------------------------------------------------------
# 1. Webhook
# ---------------------------------------------------------------------------

def test_signed_suppressed_event_flags_the_user(webhook, db):
    user = _user(db, "student@example.com")
    other = _user(db, "fine@example.com")

    response = _post(webhook, _suppressed_event("Student@Example.com"))

    assert response.status_code == 200, response.text
    assert response.json() == {"status": "flagged", "event": "email.suppressed", "matched": 1, "changed": 1}
    db.expire_all()
    assert deliverability.is_undeliverable(user)
    assert user.email_undeliverable_reason == "suppressed"
    assert "OnAccountSuppressionList" in user.email_undeliverable_detail
    assert 'Email: "Reset your Rilono password"' in user.email_undeliverable_detail
    assert not deliverability.is_undeliverable(other)


def test_rejects_unsigned_wrong_secret_stale_and_unconfigured(webhook, db, monkeypatch):
    user = _user(db, "student@example.com")
    body = json.dumps(_suppressed_event(user.email)).encode()
    url = "/api/webhooks/resend/email-events"

    assert webhook.post(url, content=body, headers={"content-type": "application/json"}).status_code == 400
    # Signed with another webhook's secret (e.g. the inbound-email one): refused.
    assert webhook.post(url, content=body, headers=_signed_headers(body, secret=OTHER_SECRET)).status_code == 400
    # Replay outside Svix's 5-minute window.
    assert webhook.post(url, content=body, headers=_signed_headers(body, timestamp=int(time.time()) - 600)).status_code == 400
    # Body tampered after signing.
    headers = _signed_headers(body)
    assert webhook.post(url, content=body.replace(b"student", b"studenx"), headers=headers).status_code == 400
    # The inbound-email secret alone does not configure this endpoint.
    monkeypatch.delenv("RESEND_DELIVERABILITY_WEBHOOK_SECRET")
    monkeypatch.setenv("RESEND_INBOUND_WEBHOOK_SECRET", SECRET)
    assert webhook.post(url, content=body, headers=_signed_headers(body)).status_code == 503

    db.expire_all()
    assert not deliverability.is_undeliverable(user)


def test_bounce_and_complaint_flag_soft_bounce_does_not(webhook, db):
    bounced = _user(db, "bounced@example.com")
    complained = _user(db, "complained@example.com")
    soft = _user(db, "mailbox-full@example.com")
    now = datetime.utcnow()

    hard = {"type": "email.bounced", "created_at": _iso(now), "data": {
        "to": ["bounced@example.com"], "subject": "Your daily visa checklist",
        "bounce": {"type": "Permanent", "subType": "General", "message": "550 5.1.1 user unknown"}}}
    spam = {"type": "email.complained", "created_at": _iso(now), "data": {
        "to": ["Complained <complained@example.com>"], "subject": "Your daily visa checklist"}}
    temporary = {"type": "email.bounced", "created_at": _iso(now), "data": {
        "to": ["mailbox-full@example.com"],
        "bounce": {"type": "Transient", "subType": "MailboxFull", "message": "mailbox full"}}}

    assert _post(webhook, hard).json()["changed"] == 1
    assert _post(webhook, spam).json()["changed"] == 1
    assert _post(webhook, temporary).json() == {"status": "ignored", "reason": "transient_bounce"}

    db.expire_all()
    assert bounced.email_undeliverable_reason == "bounced"
    assert bounced.email_undeliverable_detail.startswith("Permanent / General: 550 5.1.1 user unknown")
    assert complained.email_undeliverable_reason == "complained"
    assert not deliverability.is_undeliverable(soft)


def test_unknown_address_and_unhandled_types_return_200(webhook, db):
    _user(db, "student@example.com")
    assert _post(webhook, _suppressed_event("nobody@example.com")).json()["matched"] == 0
    delivered = {"type": "email.delivered", "created_at": _iso(datetime.utcnow()), "data": {"to": ["student@example.com"]}}
    response = _post(webhook, delivered)
    assert response.status_code == 200 and response.json()["status"] == "ignored"


def test_suppression_added_and_removed_round_trip(webhook, db):
    user = _user(db, "student@example.com")
    t0 = datetime.utcnow() - timedelta(minutes=2)

    added = {"type": "suppression.added", "created_at": _iso(t0), "data": {
        "id": "sup_1", "email": "student@example.com", "origin": "complaint", "source_id": "em_1"}}
    assert _post(webhook, added).json()["changed"] == 1
    db.expire_all()
    assert user.email_undeliverable_reason == "complained"

    removed = {"type": "suppression.removed", "created_at": _iso(t0 + timedelta(minutes=1)), "data": {
        "id": "sup_1", "email": "student@example.com", "origin": "complaint"}}
    assert _post(webhook, removed).json() == {"status": "cleared", "event": "suppression.removed", "matched": 1, "changed": 1}
    db.expire_all()
    assert not deliverability.is_undeliverable(user)
    assert user.email_undeliverable_cleared_by == "resend:suppression.removed"


def test_out_of_order_retries_cannot_undo_newer_state(webhook, db):
    user = _user(db, "student@example.com")
    t0 = datetime.utcnow() - timedelta(minutes=10)

    # Removal at t0+5 arrives first; a retried suppression from t0 arrives later: ignored.
    removed = {"type": "suppression.removed", "created_at": _iso(t0 + timedelta(minutes=5)),
               "data": {"email": "student@example.com", "origin": "bounce"}}
    _post(webhook, removed)
    assert _post(webhook, _suppressed_event(user.email, at=t0)).json()["changed"] == 0
    db.expire_all()
    assert not deliverability.is_undeliverable(user)

    # A NEW suppression at t0+8 flags; a late removal from t0+6 must not clear it.
    assert _post(webhook, _suppressed_event(user.email, at=t0 + timedelta(minutes=8))).json()["changed"] == 1
    late_removed = {"type": "suppression.removed", "created_at": _iso(t0 + timedelta(minutes=6)),
                    "data": {"email": "student@example.com"}}
    assert _post(webhook, late_removed).json()["changed"] == 0
    db.expire_all()
    assert deliverability.is_undeliverable(user)


# ---------------------------------------------------------------------------
# 2. Non-transactional sends skip flagged users
# ---------------------------------------------------------------------------

def _flag(db, user, reason="suppressed"):
    deliverability.mark_undeliverable(user, reason=reason, detail="test", at=datetime.utcnow())
    db.commit()


def test_daily_ai_nudge_skips_flagged_user_before_any_gemini_call(Session, db, monkeypatch):
    from app.services import daily_ai_notifications as job

    monkeypatch.setattr(job, "SessionLocal", Session)
    calls = {"snapshot": [], "profile": [], "docs": [], "gemini": [], "email": []}
    monkeypatch.setattr(job, "refresh_student_profile_snapshot_for_user",
                        lambda *, user, db: calls["snapshot"].append(user.id))
    monkeypatch.setattr(job, "_load_profile_raw_json", lambda uid, r2: calls["profile"].append(uid) or "{}")
    monkeypatch.setattr(job, "_load_user_document_payload", lambda uid, s, r2: calls["docs"].append(uid) or [])

    def fake_analyze(model, prompt, user_id, model_name):
        calls["gemini"].append(user_id)
        return job.DailyAssistantDecision(
            notification_needed=True, reasoning="x", email_subject="Upload your I-20",
            email_body="<p>hi</p>", in_app_message="Upload your I-20",
        )

    monkeypatch.setattr(job, "_analyze_user", fake_analyze)
    monkeypatch.setattr(job, "send_proactive_assistant_email", lambda **kw: calls["email"].append(kw["email"]) or True)
    monkeypatch.setattr(job, "build_email_notifications_unsubscribe_url", lambda email: "https://example.test/u")
    monkeypatch.setattr(job, "_build_gemini_model", lambda model_name=None: (object(), "genai"))
    monkeypatch.setattr(job, "_build_r2_client", lambda: object())
    monkeypatch.setattr(job, "DAILY_AI_NOTIFIER_USER_LIMIT", 0)

    healthy = _user(db, "healthy@example.com")
    flagged = _user(db, "gauravhsn8@example.com")
    _flag(db, flagged)

    result = job.run_daily_ai_notification_job(force=True)

    assert result["status"] == "completed", result
    for step in ("snapshot", "profile", "docs", "gemini"):
        assert calls[step] == [healthy.id], step
    assert calls["email"] == ["healthy@example.com"]
    assert result["users_skipped_undeliverable"] == 1
    assert result["users_scanned"] == 1


def test_daily_ai_nudge_rechecks_flag_when_loading_each_user(Session, db, monkeypatch):
    """A bounce landing mid-run (after the candidate listing) still stops that user's scan."""
    from app.services import daily_ai_notifications as job

    monkeypatch.setattr(job, "SessionLocal", Session)
    snapshot = []
    monkeypatch.setattr(job, "refresh_student_profile_snapshot_for_user", lambda *, user, db: snapshot.append(user.id))
    user = _user(db, "student@example.com")
    _flag(db, user, "bounced")

    assert job._process_single_user(user_id=user.id, model=object(), model_name="m", r2_client=object()) is False
    assert snapshot == []


def test_calendar_digest_skips_flagged_staff(Session, db, monkeypatch):
    from app.services import enterprise_calendar_reminders as cal

    monkeypatch.setattr(cal, "SessionLocal", Session)
    sent = []
    monkeypatch.setattr(cal, "send_enterprise_calendar_digest_email", lambda **kw: sent.append(kw["to_email"]) or True)
    healthy = _user(db, "consultant@agency.example")
    flagged = _user(db, "bouncing@agency.example")
    _flag(db, flagged, "bounced")
    org = models.EnterpriseOrganization(company_name="Acme", created_by_user_id=healthy.id)
    db.add(org)
    db.flush()
    item = {"date": date.today(), "time": None, "title": "Call", "overdue": False}
    monkeypatch.setattr(cal, "_collect_org_items_by_recipient",
                        lambda _db, org_id, today, floor: {healthy.id: [dict(item)], flagged.id: [dict(item)]})
    monkeypatch.setattr(cal, "_is_active_member", lambda _db, org_id, user_id: True)
    monkeypatch.setattr(cal, "_notify_linked_clients", lambda *a, **k: 0)
    db.commit()

    result = cal.run_calendar_reminder_job(force=True)

    assert result["status"] == "completed", result
    assert sent == ["consultant@agency.example"]
    assert result["recipients_skipped_undeliverable"] == 1


def test_marketing_audience_sync_excludes_flagged_users(Session, db, monkeypatch):
    from app.services import resend_contacts_sync as sync

    monkeypatch.setattr(sync, "SessionLocal", Session)
    ok = _user(db, "optin@example.com", email_verified=True, marketing_emails_consent=True)
    flagged = _user(db, "complained@example.com", email_verified=True, marketing_emails_consent=True)
    _flag(db, flagged, "complained")

    assert [u.email for u in sync._load_eligible_users()] == [ok.email]


# ---------------------------------------------------------------------------
# 3. Transactional sends + the public forgot-password response
# ---------------------------------------------------------------------------

def _auth_client(db, monkeypatch, sent):
    monkeypatch.setattr(auth_router, "is_turnstile_enabled", lambda: False)
    monkeypatch.setattr(auth_router, "_enforce_rate_limit_or_429", lambda **kwargs: None)
    monkeypatch.setattr(auth_router, "send_password_reset_email",
                        lambda email, token, base_url: sent.append(email) or True)
    app = FastAPI()
    app.include_router(auth_router.router)
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def test_forgot_password_still_sends_and_keeps_the_generic_response(db, monkeypatch):
    flagged = _user(db, "suppressed@example.com")
    _flag(db, flagged)
    sent = []
    client = _auth_client(db, monkeypatch, sent)

    for_flagged = client.post("/api/auth/forgot-password", json={"email": "suppressed@example.com"})
    for_nobody = client.post("/api/auth/forgot-password", json={"email": "nobody@example.com"})

    assert for_flagged.status_code == for_nobody.status_code == 200
    assert for_flagged.json() == for_nobody.json()  # no account-existence or flag leak
    assert sent == ["suppressed@example.com"]       # transactional: still attempted


# ---------------------------------------------------------------------------
# 4. Admin console
# ---------------------------------------------------------------------------

def _admin_client(db, admin_user, monkeypatch):
    monkeypatch.setattr(admin_router, "_enforce_rate_limit_or_429", lambda **kwargs: None)
    app = FastAPI()
    app.include_router(admin_router.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[admin_router.get_current_admin_user] = lambda: admin_user
    app.dependency_overrides[admin_router.require_admin_turnstile_proof] = lambda: None
    return TestClient(app)


def test_admin_detail_shows_flag_and_clear_resets_it(webhook, db, monkeypatch):
    admin = _user(db, "admin@rilono.example", is_admin=True)
    student = _user(db, "student@example.com")
    _post(webhook, _suppressed_event(student.email))
    client = _admin_client(db, admin, monkeypatch)

    detail = client.get(f"/api/admin/users/{student.id}/detail")
    assert detail.status_code == 200, detail.text
    status = detail.json()["account"]["email_delivery"]
    assert status["undeliverable"] is True
    assert status["reason"] == "suppressed"
    assert status["reason_label"] == "On Resend's suppression list"
    assert "OnAccountSuppressionList" in status["detail"]
    assert status["flagged_at"]

    cleared = client.post(f"/api/admin/users/{student.id}/email-delivery/clear")
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["cleared"] is True
    assert cleared.json()["email_delivery"]["undeliverable"] is False
    assert cleared.json()["email_delivery"]["cleared_by"] == "admin:admin@rilono.example"

    db.expire_all()
    assert not deliverability.is_undeliverable(student)
    # A retry of the event that was just cleared doesn't re-flag...
    _post(webhook, _suppressed_event(student.email, at=datetime.utcnow() - timedelta(minutes=1)))
    db.expire_all()
    assert not deliverability.is_undeliverable(student)
    # ...but a fresh suppression (still on Resend's list) does.
    _post(webhook, _suppressed_event(student.email, at=datetime.utcnow() + timedelta(seconds=5)))
    db.expire_all()
    assert deliverability.is_undeliverable(student)


def test_admin_promo_email_skips_undeliverable_members(db, monkeypatch):
    from app import email_service

    admin = _user(db, "admin@rilono.example", is_admin=True)
    owner = _user(db, "owner@agency.example")
    flagged = _user(db, "bouncing@agency.example")
    _flag(db, flagged, "bounced")
    org = models.EnterpriseOrganization(company_name="Acme", created_by_user_id=owner.id)
    db.add(org)
    db.flush()
    for member in (owner, flagged):
        db.add(models.EnterpriseOrganizationMember(
            organization_id=org.id, user_id=member.id, role="owner", role_key="owner",
            is_active=True, status="active",
        ))
    coupon = models.EnterpriseCoupon(organization_id=org.id, code="ACME20", percent_off=20)
    db.add(coupon)
    db.commit()
    sent = []
    monkeypatch.setattr(email_service, "send_enterprise_discount_promo_email",
                        lambda **kw: sent.append(kw["recipient_email"]) or True)

    response = _admin_client(db, admin, monkeypatch).post(
        f"/api/admin/enterprise/accounts/{org.id}/coupons/{coupon.id}/send-email", json={},
    )

    assert response.status_code == 200, response.text
    assert sent == ["owner@agency.example"]
    assert response.json()["skipped_undeliverable"] == ["bouncing@agency.example"]
    assert "Skipped 1 undeliverable address." in response.json()["message"]


# ---------------------------------------------------------------------------
# 5. Schema patch
# ---------------------------------------------------------------------------

def test_schema_patch_adds_columns_to_existing_users_table(tmp_path, monkeypatch):
    from app import schema_patch

    scratch = create_engine(f"sqlite:///{tmp_path / 'scratch.db'}")
    with scratch.begin() as conn:
        conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, email VARCHAR NOT NULL)"))
        conn.execute(text("INSERT INTO users (id, email) VALUES (1, 'legacy@example.com')"))
    monkeypatch.setattr(schema_patch, "engine", scratch)

    schema_patch.ensure_user_email_deliverability_columns()
    schema_patch.ensure_user_email_deliverability_columns()  # idempotent

    with scratch.connect() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(users)"))}
        row = conn.execute(text("SELECT email_undeliverable_at FROM users WHERE id = 1")).one()
    assert {
        "email_undeliverable_at", "email_undeliverable_reason", "email_undeliverable_detail",
        "email_undeliverable_cleared_at", "email_undeliverable_cleared_by",
    } <= columns
    assert row[0] is None  # existing users start deliverable
    scratch.dispose()
