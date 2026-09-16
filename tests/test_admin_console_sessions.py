"""Separate console credentials never authenticate the student/Enterprise apps."""

from datetime import datetime, timedelta, timezone
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import admin_sessions, auth, models
from app.database import Base, get_db
from app.routers import admin, admin_auth, auth as auth_router, enterprise


ORIGIN = "https://console.example.test"
PERSONAL_PASSWORD = "MyPersonal!4829"
CONSOLE_PASSWORD = "ConsoleOnly!4829"
NEW_PASSWORD = "Replacement!5829"


@pytest.fixture(scope="module")
def personal_hash():
    return auth.get_password_hash(PERSONAL_PASSWORD)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setattr(admin, "_enforce_rate_limit_or_429", lambda **kwargs: None)
    monkeypatch.setattr(admin_auth, "_enforce_rate_limit_or_429", lambda **kwargs: None)
    monkeypatch.setattr(admin_auth, "_is_admin_turnstile_required", lambda request: False)
    app = FastAPI()
    for router in [admin.router, admin_auth.router, auth_router.router, enterprise.router]:
        app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[admin.require_admin_turnstile_proof] = lambda: None
    with TestClient(app, base_url=ORIGIN, headers={"Origin": ORIGIN}) as test_client:
        yield test_client


def person(db, personal_hash, email="member@example.com", **fields):
    row = models.User(email=email, hashed_password=personal_hash, full_name="Example Person", email_verified=True,
                      email_notifications_enabled=False, **fields)
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def owner(db, personal_hash):
    return person(db, personal_hash, "owner@example.com", is_admin=True)


@pytest.fixture
def member(db, personal_hash):
    row = person(db, personal_hash)
    db.add(models.AdminConsoleAccess(user_id=row.id, role="viewer", sections='["users"]'))
    db.commit()
    return row


def main_headers(user):
    # Explicit empty Cookie permits a separate administrator's API call while
    # the test browser retains another person's dedicated console cookie.
    return {"Authorization": "Bearer " + auth.create_access_token({"sub": user.email}), "Cookie": ""}


def console_headers(token):
    return {"Cookie": f"{admin_sessions.COOKIE_NAME}={token}", admin_sessions.REQUIRED_HEADER: "required"}


def login(client, member, password=PERSONAL_PASSWORD):
    response = client.post("/api/admin-auth/login", json={"email": member.email, "password": password},
                           headers={admin_sessions.REQUIRED_HEADER: "required"})
    return response


def set_password(client, owner, member, password=CONSOLE_PASSWORD):
    response = client.patch(f"/api/admin/team/{member.id}", headers=main_headers(owner),
                            json={"role": "viewer", "sections": ["users"], "console_password": password})
    assert response.status_code == 200, response.text
    assert response.json()["has_console_password"] is True
    assert password not in response.text
    return response


def test_main_password_login_creates_only_opaque_console_session(client, db, owner):
    response = login(client, owner)
    assert response.status_code == 200, response.text
    assert "access_token" not in response.json()
    cookie_headers = response.headers.get_list("set-cookie")
    session_cookie = next(value for value in cookie_headers if value.startswith(admin_sessions.COOKIE_NAME + "="))
    assert "HttpOnly" in session_cookie and "Secure" in session_cookie and "SameSite=strict" in session_cookie
    assert "Path=/api" in session_cookie and "Domain=" not in session_cookie
    assert not any(value.startswith(auth.AUTH_COOKIE_NAME + "=") for value in cookie_headers)
    token = client.cookies.get(admin_sessions.COOKIE_NAME)
    session = db.query(models.AdminConsoleSession).one()
    assert session.token_hash == admin_sessions.token_hash(token) and session.token_hash != token
    assert session.auth_source == "personal"
    assert token not in response.text and PERSONAL_PASSWORD not in response.text
    assert client.get("/api/admin/access", headers=console_headers(token)).status_code == 200
    assert db.query(models.Subscription).count() == 0  # no student login side effects


@pytest.mark.parametrize("route", ["/api/auth/me", "/api/enterprise/me"])
@pytest.mark.parametrize("transport", ["own_cookie", "main_cookie", "bearer"])
def test_console_session_cannot_authenticate_other_products(client, member, route, transport):
    assert login(client, member).status_code == 200
    token = client.cookies.get(admin_sessions.COOKIE_NAME)
    if transport == "own_cookie":
        header = console_headers(token)
    elif transport == "main_cookie":
        header = {"Cookie": f"{auth.AUTH_COOKIE_NAME}={token}"}
    else:
        header = {"Cookie": "", "Authorization": "Bearer " + token}
    assert client.get(route, headers=header).status_code == 401


def test_team_create_with_password_preserves_existing_account(client, db, owner, personal_hash):
    member = person(db, personal_hash)
    member.e2e_enabled = True
    member.e2e_wrapped_master_key = "existing-wrapped-key"
    db.commit()
    response = client.post("/api/admin/team", headers=main_headers(owner), json={"email": member.email,
                           "role": "viewer", "sections": ["users"], "console_password": CONSOLE_PASSWORD})
    assert response.status_code == 201, response.text
    assert response.json()["has_console_password"] is True
    assert CONSOLE_PASSWORD not in response.text
    credential = db.get(models.AdminConsoleCredential, member.id)
    assert credential.password_hash != CONSOLE_PASSWORD
    assert auth.verify_password(CONSOLE_PASSWORD, credential.password_hash)
    db.refresh(member)
    assert member.hashed_password == personal_hash
    assert member.e2e_enabled and member.e2e_wrapped_master_key == "existing-wrapped-key"
    assert not member.is_admin and not member.is_developer
    assert db.query(models.User).count() == 2 and db.query(models.EnterpriseCredential).count() == 0
    assert login(client, member, PERSONAL_PASSWORD).status_code == 401
    assert login(client, member, CONSOLE_PASSWORD).status_code == 200


def test_password_reset_invalidates_every_console_session_and_main_auth_bypass(client, db, owner, member, personal_hash):
    assert login(client, member).status_code == 200
    personal_session = client.cookies.get(admin_sessions.COOKIE_NAME)
    set_password(client, owner, member)
    assert db.query(models.AdminConsoleSession).count() == 0
    assert client.get("/api/admin/access", headers=console_headers(personal_session)).status_code == 401
    assert login(client, member, CONSOLE_PASSWORD).status_code == 200
    first = client.cookies.get(admin_sessions.COOKIE_NAME)
    assert login(client, member, CONSOLE_PASSWORD).status_code == 200
    second = client.cookies.get(admin_sessions.COOKIE_NAME)
    assert first != second and db.query(models.AdminConsoleSession).count() == 2
    set_password(client, owner, member, NEW_PASSWORD)
    assert db.query(models.AdminConsoleSession).count() == 0
    for token in [first, second]:
        assert client.get("/api/admin/access", headers=console_headers(token)).status_code == 401
    # Omit the opt-in header entirely: the server still rejects personal auth
    # when a delegated member has a dedicated credential.
    assert client.get("/api/admin/access", headers=main_headers(member)).status_code == 401
    main_cookie = {"Cookie": f"{auth.AUTH_COOKIE_NAME}={auth.create_access_token({'sub': member.email})}"}
    assert client.get("/api/admin/access", headers=main_cookie).status_code == 401
    assert login(client, member, CONSOLE_PASSWORD).status_code == 401
    assert login(client, member, NEW_PASSWORD).status_code == 200
    db.refresh(member)
    assert member.hashed_password == personal_hash and member.session_invalidated_at is None


def test_revoke_and_readd_never_resurrect_old_sessions(client, db, owner, member):
    set_password(client, owner, member)
    assert login(client, member, CONSOLE_PASSWORD).status_code == 200
    token = client.cookies.get(admin_sessions.COOKIE_NAME)
    response = client.delete(f"/api/admin/team/{member.id}", headers=main_headers(owner))
    assert response.status_code == 200, response.text
    assert db.query(models.AdminConsoleSession).count() == 0
    assert db.query(models.AdminConsoleCredential).count() == 0
    response = client.post("/api/admin/team", headers=main_headers(owner), json={"email": member.email,
                           "role": "viewer", "sections": ["users"], "console_password": NEW_PASSWORD})
    assert response.status_code == 201
    assert client.get("/api/admin/access", headers=console_headers(token)).status_code == 401


@pytest.mark.parametrize("state", ["invalid", "expired", "required_without_cookie"])
def test_console_auth_does_not_fall_back_to_valid_personal_auth(client, db, member, state):
    assert login(client, member).status_code == 200
    token = client.cookies.get(admin_sessions.COOKIE_NAME)
    if state == "expired":
        db.query(models.AdminConsoleSession).one().expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    elif state == "invalid":
        token = "invalid-console-token"
    request_headers = main_headers(member)
    if state == "required_without_cookie":
        request_headers[admin_sessions.REQUIRED_HEADER] = "required"
    else:
        request_headers["Cookie"] = f"{admin_sessions.COOKIE_NAME}={token}"
    assert client.get("/api/admin/access", headers=request_headers).status_code == 401


@pytest.mark.parametrize("change", ["personal_password", "personal_logout"])
def test_main_password_backed_sessions_observe_personal_reset(client, db, member, change):
    assert login(client, member).status_code == 200
    token = client.cookies.get(admin_sessions.COOKIE_NAME)
    if change == "personal_password":
        member.hashed_password = "a-different-existing-hash"
    else:
        member.session_invalidated_at = datetime.now(timezone.utc)
    db.commit()
    assert client.get("/api/admin/access", headers=console_headers(token)).status_code == 401


def test_console_password_session_is_independent_of_personal_logout(client, db, owner, member):
    set_password(client, owner, member)
    assert login(client, member, CONSOLE_PASSWORD).status_code == 200
    token = client.cookies.get(admin_sessions.COOKIE_NAME)
    member.session_invalidated_at = datetime.now(timezone.utc)
    db.commit()
    assert client.get("/api/admin/access", headers=console_headers(token)).status_code == 200


@pytest.mark.parametrize("change", ["inactive", "unverified", "enterprise", "revoked", "sections"])
def test_sessions_observe_fresh_account_and_membership_changes(client, db, member, change):
    assert login(client, member).status_code == 200
    token = client.cookies.get(admin_sessions.COOKIE_NAME)
    if change == "inactive":
        member.is_active = False
    elif change == "unverified":
        member.email_verified = False
    elif change == "enterprise":
        member.is_enterprise_account = True
    elif change == "revoked":
        db.delete(db.get(models.AdminConsoleAccess, member.id))
    else:
        db.get(models.AdminConsoleAccess, member.id).sections = '["ai"]'
    db.commit()
    assert client.get("/api/admin/users", headers=console_headers(token)).status_code == 403


def test_logout_deletes_only_its_console_session_and_preserves_personal_session(client, db, member):
    assert login(client, member).status_code == 200
    first = client.cookies.get(admin_sessions.COOKIE_NAME)
    assert login(client, member).status_code == 200
    second = client.cookies.get(admin_sessions.COOKIE_NAME)
    response = client.post("/api/admin-auth/logout", headers=console_headers(first))
    assert response.status_code == 200
    assert not any(cookie.startswith(auth.AUTH_COOKIE_NAME + "=") for cookie in response.headers.get_list("set-cookie"))
    assert client.get("/api/admin/access", headers=console_headers(first)).status_code == 401
    assert client.get("/api/admin/access", headers=console_headers(second)).status_code == 200
    db.refresh(member)
    assert member.session_invalidated_at is None


@pytest.mark.parametrize("endpoint", ["/api/admin-auth/login", "/api/admin-auth/logout", "/api/admin/team"])
def test_cross_origin_console_mutations_are_rejected(client, db, owner, endpoint):
    assert login(client, owner).status_code == 200
    token = client.cookies.get(admin_sessions.COOKIE_NAME)
    request_headers = {**console_headers(token), "Origin": "https://other.example.test"}
    payload = {"email": owner.email, "password": PERSONAL_PASSWORD} if endpoint.endswith("login") else {}
    response = client.post(endpoint, headers=request_headers, json=payload)
    assert response.status_code == 403, response.text
    assert db.query(models.AdminConsoleSession).count() == 1


def test_login_turnstile_and_rate_limit_gates_run_before_credentials(client, member, monkeypatch):
    monkeypatch.setattr(admin_auth, "_is_admin_turnstile_required", lambda request: True)
    monkeypatch.setattr(admin_auth, "verify_turnstile_token", lambda *args: False)
    assert login(client, member).status_code == 400
    calls = []
    monkeypatch.setattr(admin_auth, "_enforce_rate_limit_or_429", lambda **kwargs: calls.append(kwargs))
    login(client, member)
    assert calls[0]["scope"] == "admin.console.login"
    assert calls[0]["limit"] == 12 and calls[0]["window_seconds"] == 300


@pytest.mark.parametrize("state", ["inactive", "unverified", "enterprise", "no_grant"])
def test_login_requires_active_verified_personal_console_member(client, db, member, state):
    if state == "inactive":
        member.is_active = False
    elif state == "unverified":
        member.email_verified = False
    elif state == "enterprise":
        member.is_enterprise_account = True
    else:
        db.delete(db.get(models.AdminConsoleAccess, member.id))
    db.commit()
    assert login(client, member).status_code == 401
    assert db.query(models.AdminConsoleSession).count() == 0


@pytest.mark.parametrize("route", ["login", "team_create", "team_update"])
@pytest.mark.parametrize("malformation", ["invalid_type", "extra_field", "too_long", "invalid_json"])
def test_password_payload_validation_never_echoes_secret(client, db, owner, member, route, malformation):
    secret = "NeverEchoThis!9374"
    password_field = "password" if route == "login" else "console_password"
    payload = {"email": member.email, password_field: secret} if route == "login" else {
        "role": "viewer", "sections": ["users"], password_field: secret}
    if route == "team_create":
        new_user = person(db, member.hashed_password, "new@example.com")
        payload["email"] = new_user.email
    if malformation == "invalid_type":
        payload[password_field] = {"secret": secret}
    elif malformation == "extra_field":
        payload["unexpected"] = secret
    elif malformation == "too_long":
        payload[password_field] = secret * 30
    path = "/api/admin-auth/login" if route == "login" else "/api/admin/team"
    method = "POST"
    if route == "team_update":
        path += f"/{member.id}"
        method = "PATCH"
    request_headers = main_headers(owner)
    if malformation == "invalid_json":
        response = client.request(method, path, headers={**request_headers, "Content-Type": "application/json"},
                                  content='{"' + password_field + '":"' + secret + '",BROKEN')
    else:
        response = client.request(method, path, headers=request_headers, json=payload)
    assert response.status_code in {400, 401, 422}, response.text
    assert secret not in response.text
    if response.status_code == 422:
        assert all(set(item) <= {"loc", "msg", "type"} for item in response.json()["detail"])
    assert db.query(models.AdminConsoleCredential).count() == 0
    assert db.query(models.AdminConsoleSession).count() == 0


def test_password_reset_reuses_protected_target_and_scope_guards(client, db, owner, member, personal_hash):
    response = client.patch(f"/api/admin/team/{owner.id}", headers=main_headers(owner),
                            json={"role": "admin", "sections": ["team"], "console_password": CONSOLE_PASSWORD})
    assert response.status_code == 403
    manager = person(db, personal_hash, "manager@example.com")
    db.add(models.AdminConsoleAccess(user_id=manager.id, role="admin", sections='["team","ai"]'))
    db.commit()
    response = client.patch(f"/api/admin/team/{member.id}", headers=main_headers(manager),
                            json={"role": "viewer", "sections": ["ai"], "console_password": CONSOLE_PASSWORD})
    assert response.status_code == 403
    assert db.query(models.AdminConsoleCredential).count() == 0


@pytest.mark.parametrize("operation", ["login", "create", "update", "revoke"])
def test_login_and_team_changes_lock_same_user_before_rechecking_grant(client, db, owner, member, operation):
    """SQLite ignores row locks; inspect the actual queries with Postgres dialect.

    Login issuance and Team reset/revoke/regrant must serialize on User, even
    when no credential or membership row exists yet. This pins that lock order.
    """
    if operation == "create":
        db.delete(db.get(models.AdminConsoleAccess, member.id))
        db.commit()
    statements = []

    def capture(execution):
        if execution.is_select:
            statements.append(str(execution.statement.compile(dialect=postgresql.dialect())))

    event.listen(db, "do_orm_execute", capture)
    try:
        if operation == "login":
            response = login(client, member)
        elif operation == "create":
            response = client.post("/api/admin/team", headers=main_headers(owner),
                                   json={"email": member.email, "role": "viewer", "sections": ["users"]})
        elif operation == "update":
            response = client.patch(f"/api/admin/team/{member.id}", headers=main_headers(owner),
                                    json={"role": "viewer", "sections": ["ai"]})
        else:
            response = client.delete(f"/api/admin/team/{member.id}", headers=main_headers(owner))
        assert response.status_code in {200, 201}, response.text
    finally:
        event.remove(db, "do_orm_execute", capture)
    locks = [index for index, sql in enumerate(statements) if "FROM users" in sql and "FOR UPDATE" in sql]
    assert len(locks) == 1
    assert any("FROM admin_console_access" in sql for sql in statements[locks[0] + 1:])


def test_console_viewer_read_does_not_write_billing_or_session_state(client, db, member, monkeypatch):
    db.get(models.AdminConsoleAccess, member.id).sections = '["enterprise"]'
    org = models.EnterpriseOrganization(company_name="Read-only account", created_by_user_id=member.id)
    db.add(org)
    db.commit()
    assert login(client, member).status_code == 200
    token = client.cookies.get(admin_sessions.COOKIE_NAME)
    org_id = org.id

    def forbidden(*args, **kwargs):
        raise AssertionError("A console Viewer GET must not write")

    monkeypatch.setattr(db, "flush", forbidden)
    monkeypatch.setattr(db, "commit", forbidden)
    assert client.get(f"/api/admin/enterprise/accounts/{org_id}/details", headers=console_headers(token)).status_code == 200
    assert db.query(models.EnterpriseCreditWallet).count() == 0
    assert db.query(models.EnterpriseSubscription).count() == 0
