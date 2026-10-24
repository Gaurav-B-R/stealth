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
6. Enterprise CRM clients (not users) get the same flag: every org's row with the address,
   an org-neutral detail (never the triggering send's subject or diagnostic), a warning in
   the client payload, a reset on email change, and no automatic calendar reminder.
7. A signed-in student sees their own flag (a boolean + plain-words reason) on
   GET /api/auth/me, and nowhere unauthenticated.

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
    assert response.json() == {
        "status": "flagged", "event": "email.suppressed", "matched": 1, "changed": 1,
        "clients_matched": 0, "clients_changed": 0,
    }
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
    assert _post(webhook, removed).json() == {
        "status": "cleared", "event": "suppression.removed", "matched": 1, "changed": 1,
        "clients_matched": 0, "clients_changed": 0,
    }
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


# ---------------------------------------------------------------------------
# 6. Enterprise CRM clients
# ---------------------------------------------------------------------------

def _org(db, name):
    owner = _user(db, f"owner@{name.lower().replace(' ', '-')}.example", is_enterprise_account=True)
    org = models.EnterpriseOrganization(
        company_name=name, created_by_user_id=owner.id,
        subdomain_slug=name.lower().replace(" ", "-"), country_code="IN",
    )
    db.add(org)
    db.commit()
    return org, owner


def _crm_client(db, org, owner, email, name="Priya Sharma"):
    client = models.EnterpriseClient(
        organization_id=org.id, full_name=name, email=email, created_by_user_id=owner.id,
        destination_country_code="US", destination_country_name="United States", visa_type="F-1",
    )
    db.add(client)
    db.commit()
    return client


def test_bounce_flags_every_orgs_client_row_with_an_org_neutral_detail(webhook, db):
    acme, acme_owner = _org(db, "Acme Visas")
    globe, globe_owner = _org(db, "Globe Overseas")
    at_acme = _crm_client(db, acme, acme_owner, "priya@student.example")
    # Another org's file for the same student, typed with different case and stray spaces.
    at_globe = _crm_client(db, globe, globe_owner, "  Priya@Student.example ")
    unrelated = _crm_client(db, acme, acme_owner, "someone-else@student.example", name="Arjun Rao")

    # Acme's payment-link email bounced. Its subject and Resend's free-text diagnostic name
    # Acme and its sender: none of that may land on Globe's row.
    bounce = {"type": "email.bounced", "created_at": _iso(datetime.utcnow()), "data": {
        "to": ["priya@student.example"],
        "from": "Acme Visas <acme-visas@mail.rilono.com>",
        "subject": "Your payment link from Acme Visas (INR 45,000)",
        "bounce": {"type": "Permanent", "subType": "NoEmail",
                   "message": "550 5.1.1 <priya@student.example>: rejected mail from acme-visas@mail.rilono.com"}}}
    response = _post(webhook, bounce)

    assert response.status_code == 200, response.text
    # Counts only: no addresses, ids or org names go back to the provider.
    assert response.json() == {
        "status": "flagged", "event": "email.bounced", "matched": 0, "changed": 0,
        "clients_matched": 2, "clients_changed": 2,
    }
    db.expire_all()
    for row in (at_acme, at_globe):
        assert deliverability.is_undeliverable(row)
        assert row.email_undeliverable_reason == "bounced"
        assert row.email_undeliverable_detail == "Permanent / NoEmail"
    assert not deliverability.is_undeliverable(unrelated)

    status = deliverability.client_status(at_globe)
    assert status == {
        "undeliverable": True, "reason": "bounced", "label": "Email bouncing",
        "message": deliverability.CLIENT_REASON_MESSAGES["bounced"], "code": "Permanent / NoEmail",
    }
    leaked = json.dumps(status).lower()
    for marker in ("acme", "payment link", "45,000", "550", "mail.rilono.com", "resend"):
        assert marker not in leaked, marker
    assert deliverability.client_status(unrelated) is None


def test_client_suppression_round_trip_and_out_of_order_retries(webhook, db):
    org, owner = _org(db, "Acme Visas")
    client = _crm_client(db, org, owner, "priya@student.example")
    t0 = datetime.utcnow() - timedelta(minutes=10)

    added = {"type": "suppression.added", "created_at": _iso(t0), "data": {
        "email": "priya@student.example", "origin": "complaint"}}
    assert _post(webhook, added).json()["clients_changed"] == 1
    db.expire_all()
    assert client.email_undeliverable_reason == "complained"
    assert client.email_undeliverable_detail is None  # nothing org-specific to keep

    removed = {"type": "suppression.removed", "created_at": _iso(t0 + timedelta(minutes=5)),
               "data": {"email": "priya@student.example"}}
    assert _post(webhook, removed).json()["clients_changed"] == 1
    db.expire_all()
    assert not deliverability.is_undeliverable(client)
    assert client.email_undeliverable_cleared_by == "resend:suppression.removed"

    # A retried suppression from before the removal can't re-flag the row.
    assert _post(webhook, _suppressed_event("priya@student.example", at=t0)).json()["clients_changed"] == 0
    db.expire_all()
    assert not deliverability.is_undeliverable(client)


def test_user_and_client_at_the_same_address_are_both_flagged(webhook, db):
    org, owner = _org(db, "Acme Visas")
    user = _user(db, "priya@student.example")
    client = _crm_client(db, org, owner, "priya@student.example")

    body = _post(webhook, _suppressed_event("priya@student.example")).json()

    assert (body["changed"], body["clients_changed"]) == (1, 1)
    db.expire_all()
    # The B2C account keeps the full support detail; the CRM row only Resend's code.
    assert 'Email: "Reset your Rilono password"' in user.email_undeliverable_detail
    assert client.email_undeliverable_detail == "OnAccountSuppressionList"


@pytest.fixture
def crm_api(db, monkeypatch):
    from app.auth import get_current_active_user
    from app.routers import enterprise as enterprise_router
    from app import enterprise_access as access

    monkeypatch.setattr(enterprise_router, "_enforce_rate_limit_or_429", lambda *a, **kw: None)
    org, owner = _org(db, "Acme Visas")
    db.add(models.EnterpriseOrganizationMember(
        organization_id=org.id, user_id=owner.id, role_key=access.ROLE_OWNER, role="admin", is_active=True,
    ))
    db.commit()
    app = FastAPI()
    app.include_router(enterprise_router.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_active_user] = lambda: owner
    with TestClient(app) as client:
        yield client, org, owner


def test_client_payload_carries_the_flag_and_an_email_change_clears_it(crm_api, webhook, db):
    api, org, owner = crm_api
    other_org, other_owner = _org(db, "Globe Overseas")
    client = _crm_client(db, org, owner, "priya@student.example")
    other = _crm_client(db, other_org, other_owner, "priya@student.example")
    url = f"/api/enterprise/clients/{client.id}"

    first = api.get(url)
    assert first.status_code == 200, first.text
    assert first.json()["client"]["email_delivery"] is None

    _post(webhook, _suppressed_event("priya@student.example", subject="Globe Overseas: your visa slot"))
    payload = api.get(url).json()["client"]
    assert payload["email_delivery"]["label"] == "Email blocked"
    assert "globe" not in json.dumps(payload).lower()

    # An unrelated edit keeps the flag; a new address (what the chip asks for) clears it.
    response = api.patch(url, json={"phone": "+91 98450 00000"})
    assert response.status_code == 200, response.text
    assert response.json()["client"]["email_delivery"]["undeliverable"] is True
    response = api.patch(url, json={"email": "Priya.New@Student.example"})
    assert response.status_code == 200, response.text
    assert response.json()["client"]["email_delivery"] is None
    db.expire_all()
    assert client.email == "priya.new@student.example"
    assert client.email_undeliverable_cleared_by == "email_changed"
    # The other org's file still has the bad address, so it stays flagged.
    assert deliverability.is_undeliverable(other)
    # Another org's client is not reachable through this org's API.
    assert api.get(f"/api/enterprise/clients/{other.id}").status_code == 404


def test_client_calendar_reminder_skips_flagged_clients(db, monkeypatch):
    from app.services import enterprise_calendar_reminders as cal

    sent = []
    monkeypatch.setattr(cal, "send_enterprise_client_calendar_reminder_email",
                        lambda **kw: sent.append(kw["to_email"]) or True)
    org, owner = _org(db, "Acme Visas")
    healthy = _crm_client(db, org, owner, "arjun@student.example", name="Arjun Rao")
    flagged = _crm_client(db, org, owner, "priya@student.example")
    deliverability.mark_undeliverable(flagged, reason="bounced", detail=None, at=datetime.utcnow())
    today = date.today()
    events = [
        models.EnterpriseCalendarEvent(
            organization_id=org.id, client_id=c.id, title="Biometrics appointment",
            event_date=today, notify_client=True, is_done=False,
        )
        for c in (healthy, flagged)
    ]
    db.add_all(events)
    db.commit()

    assert cal._notify_linked_clients(db, org, today, today - timedelta(days=7), "IST") == 1

    assert sent == ["arjun@student.example"]
    db.expire_all()
    # Handled either way, like a client with no email: no daily re-scan of the same event.
    assert all(ev.client_notified_at is not None for ev in events)


def test_schema_patch_adds_columns_to_existing_enterprise_clients_table(tmp_path, monkeypatch):
    from app import schema_patch

    scratch = create_engine(f"sqlite:///{tmp_path / 'scratch.db'}")
    monkeypatch.setattr(schema_patch, "engine", scratch)
    schema_patch.ensure_enterprise_client_email_deliverability_columns()  # no table yet: no-op
    with scratch.begin() as conn:
        conn.execute(text("CREATE TABLE enterprise_clients (id INTEGER PRIMARY KEY, email VARCHAR)"))
        conn.execute(text("INSERT INTO enterprise_clients (id, email) VALUES (1, 'legacy@example.com')"))

    schema_patch.ensure_enterprise_client_email_deliverability_columns()
    schema_patch.ensure_enterprise_client_email_deliverability_columns()  # idempotent

    with scratch.connect() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(enterprise_clients)"))}
        row = conn.execute(text("SELECT email_undeliverable_at FROM enterprise_clients WHERE id = 1")).one()
    assert {
        "email_undeliverable_at", "email_undeliverable_reason", "email_undeliverable_detail",
        "email_undeliverable_cleared_at", "email_undeliverable_cleared_by",
    } <= columns
    assert row[0] is None
    scratch.dispose()


# ---------------------------------------------------------------------------
# 7. The student's own notice (GET /api/auth/me -> dashboard banner)
# ---------------------------------------------------------------------------

def _bearer(user):
    from app.auth import create_access_token

    return {"Authorization": f"Bearer {create_access_token(data={'sub': user.email})}"}


@pytest.mark.parametrize("reason", ["bounced", "complained", "suppressed"])
def test_me_tells_a_flagged_student_why_in_plain_words(db, monkeypatch, reason):
    student = _user(db, "flagged@example.com")
    deliverability.mark_undeliverable(
        student, reason=reason, at=datetime.utcnow(),
        detail="OnAccountSuppressionList: internal provider message · Email: \"Reset\"",
    )
    db.commit()
    client = _auth_client(db, monkeypatch, [])

    body = client.get("/api/auth/me", headers=_bearer(student)).json()

    assert body["email_delivery_issue"] is True
    assert body["email_delivery_issue_reason"] == deliverability.STUDENT_REASON_LABELS[reason]
    assert "Resend" not in body["email_delivery_issue_reason"]
    # Only the boolean + label reach the student: no provider detail, times or reason code.
    serialized = json.dumps(body)
    assert "OnAccountSuppressionList" not in serialized
    assert not any(key.startswith("email_undeliverable") for key in body)


def test_me_reports_no_issue_for_a_deliverable_or_cleared_student(db, monkeypatch):
    fine = _user(db, "fine@example.com")
    cleared = _user(db, "cleared@example.com")
    _flag(db, cleared)
    deliverability.clear_undeliverable(cleared, by="admin:support@rilono.example", force=True)
    db.commit()
    client = _auth_client(db, monkeypatch, [])

    for user in (fine, cleared):
        body = client.get("/api/auth/me", headers=_bearer(user)).json()
        assert body["email"] == user.email
        assert body["email_delivery_issue"] is False
        assert body["email_delivery_issue_reason"] is None


def test_delivery_notice_is_never_on_unauthenticated_responses(db, monkeypatch):
    from app import schemas

    _flag(db, _user(db, "flagged@example.com"))
    client = _auth_client(db, monkeypatch, [])

    anonymous = client.get("/api/auth/me")
    assert anonymous.status_code == 401
    assert "email_delivery" not in anonymous.text
    forgot = client.post("/api/auth/forgot-password", json={"email": "flagged@example.com"})
    assert "email_delivery" not in forgot.text and "undeliverable" not in forgot.text
    # UserResponse also backs POST /register (unauthenticated) and nested document
    # uploaders, so the notice must live only on /me's own schema.
    assert "email_delivery_issue" not in schemas.UserResponse.model_fields
    assert "email_delivery_issue" in schemas.CurrentUserResponse.model_fields
