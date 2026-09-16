"""HTTP permission regressions for the console's independent, persisted Team roles.

Use real signed session tokens and SQLite rows, without importing app.main or
contacting storage, email, AI, billing, or any production database.
"""

import json
import re

import pytest
from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import admin_access, auth, models
from app.database import Base, get_db
from app.routers import admin as admin_router


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def user(db, email="person@example.com", **flags):
    row = models.User(email=email, hashed_password="unchanged-password-hash", full_name=email.split("@")[0],
                      email_verified=True, email_notifications_enabled=False, **flags)
    db.add(row)
    db.commit()
    return row


def grant(db, person, role="viewer", sections=("users",)):
    row = models.AdminConsoleAccess(user_id=person.id, role=role, sections=json.dumps(list(sections)))
    db.add(row)
    db.commit()
    return row


def headers(person, **claims):
    return {"Authorization": "Bearer " + auth.create_access_token({"sub": person.email, **claims})}


@pytest.fixture
def client(db, monkeypatch):
    # Keep actual auth and section dependencies active. Only bypass external
    # Turnstile proof and rate limiting, which have their own existing tests.
    monkeypatch.setattr(admin_router, "_enforce_rate_limit_or_429", lambda **kwargs: None)
    app = FastAPI()
    app.include_router(admin_router.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[admin_router.require_admin_turnstile_proof] = lambda: None

    @app.get("/global-admin", dependencies=[Depends(auth.get_current_admin_user)])
    def global_admin():
        return {"ok": True}

    @app.get("/unclassified-console", dependencies=[Depends(admin_access.get_current_admin_user)])
    def unclassified_console():
        return {"ok": True}

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def owner(db):
    return user(db, "owner@example.com", is_admin=True)


def test_all_console_routes_have_explicit_policies_and_enforcement():
    routes = [route for route in admin_router.router.routes if isinstance(route, APIRoute)]
    assert len(routes) >= 48
    for route in routes:
        policy = getattr(route.endpoint, "admin_console_policy", None)
        assert isinstance(policy, admin_access.RoutePolicy), route.path
        assert any(dep.call is admin_access.get_current_admin_user for dep in route.dependant.dependencies), route.path
    # These similar-looking endpoints belong to different sidebar sections.
    policies = {(next(iter(route.methods)), route.path): route.endpoint.admin_console_policy for route in routes}
    assert policies[("GET", "/api/admin/b2c/revenue")].section == "finance"
    assert policies[("POST", "/api/admin/users/{user_id}/conversion-reco")].section == "users"
    assert policies[("POST", "/api/admin/growth/conversion-analysis")].section == "analytics"
    assert policies[("GET", "/api/admin/ai-usage/profiles/export")].section == "ai"
    assert policies[("POST", "/api/admin/enterprise/accounts/{organization_id}/refunds")].action == "delete"
    assert policies[("POST", "/api/admin/enterprise/credentials")].legacy_admin is True


def test_every_unassigned_or_mutating_route_rejects_forged_viewer_requests(client, db):
    viewer = user(db)
    grant(db, viewer)
    forged_headers = headers(viewer, is_admin=True, role="admin", sections=list(admin_access.SECTION_KEYS))
    denied = 0
    for route in admin_router.router.routes:
        if not isinstance(route, APIRoute):
            continue
        policy = route.endpoint.admin_console_policy
        if policy.action == "access" or (policy.section == "users" and policy.action == "read"):
            continue
        path = re.sub(r"\{[^}]+\}", "99999", route.path)
        for method in route.methods:
            response = client.request(method, path, headers=forged_headers, json={})
            assert response.status_code == 403, (method, path, response.text)
            denied += 1
    assert denied >= 35
    assert db.query(models.User).count() == 1
    assert db.query(models.AdminConsoleAccess).count() == 1
    assert db.query(models.EnterpriseCredential).count() == 0


def test_unclassified_endpoints_fail_closed_even_for_legacy_owner(client, owner):
    response = client.get("/unclassified-console", headers=headers(owner))
    assert response.status_code == 403
    assert "no access policy" in response.json()["detail"]


@pytest.mark.parametrize("role,writable,deletable", [("viewer", [], []), ("editor", ["users", "ai"], []),
                                                       ("admin", ["users", "ai"], ["users", "ai"])])
def test_access_contract_and_global_admin_boundary(client, db, role, writable, deletable):
    person = user(db)
    grant(db, person, role, ["ai", "users"])
    response = client.get("/api/admin/access", headers=headers(person))
    assert response.status_code == 200, response.text
    data = response.json()
    assert response.headers["cache-control"] == "no-store"
    assert data["role"] == role
    assert data["sections"] == ["users", "ai"]
    assert data["can_write_sections"] == writable
    assert data["can_delete_sections"] == deletable
    assert data["can_manage_team"] is False
    assert data["can_provision_enterprise"] is False
    assert data["user"]["is_admin"] is False and data["user"]["is_developer"] is False
    assert client.get("/global-admin", headers=headers(person)).status_code == 403
    assert client.get("/api/admin/users", headers=headers(person)).status_code == 200


def test_legacy_access_and_access_before_turnstile(client, owner, monkeypatch):
    client.app.dependency_overrides.pop(admin_router.require_admin_turnstile_proof)
    monkeypatch.setattr(admin_router, "_is_admin_turnstile_required", lambda request: True)
    response = client.get("/api/admin/access", headers=headers(owner))
    assert response.status_code == 200
    assert response.json()["sections"] == list(admin_access.SECTION_KEYS)
    assert response.json()["can_manage_team"] is True
    assert response.json()["can_provision_enterprise"] is True
    assert client.get("/api/admin/users", headers=headers(owner)).status_code == 403
    assert client.post("/api/admin/turnstile/clear", headers=headers(owner)).status_code == 200


@pytest.mark.parametrize("role,expected", [("viewer", 403), ("editor", 200), ("admin", 200)])
def test_status_write_role_matrix(client, db, role, expected):
    actor, target = user(db), user(db, "target@example.com")
    grant(db, actor, role)
    response = client.patch(f"/api/admin/users/{target.id}/status", headers=headers(actor), json={"is_active": False})
    assert response.status_code == expected, response.text
    db.refresh(target)
    assert target.is_active is (expected != 200)


@pytest.mark.parametrize("role,expected", [("viewer", 403), ("editor", 403), ("admin", 200)])
def test_permanent_account_delete_role_matrix(client, db, role, expected):
    actor, target = user(db), user(db, "target@example.com")
    grant(db, actor, role)
    target_id = target.id
    response = client.delete(f"/api/admin/users/{target_id}", headers=headers(actor))
    assert response.status_code == expected, response.text
    assert (db.get(models.User, target_id) is None) is (expected == 200)


def test_team_crud_keeps_personal_account_and_applies_immediately(client, db, owner):
    member = user(db, "Teammate@example.com")
    token = headers(member)
    assert client.get("/api/admin/access", headers=token).status_code == 403
    response = client.post("/api/admin/team", headers=headers(owner), json={
        "email": "teammate@example.com", "role": "viewer", "sections": ["users"]})
    assert response.status_code == 201, response.text
    assert response.json()["user_id"] == member.id
    assert response.json()["can_manage"] is True
    assert client.get("/api/admin/users", headers=token).status_code == 200
    assert client.post("/api/admin/team", headers=headers(owner), json={
        "email": member.email, "role": "viewer", "sections": ["users"]}).status_code == 409
    update = client.patch(f"/api/admin/team/{member.id}", headers=headers(owner), json={"role": "editor", "sections": ["ai"]})
    assert update.status_code == 200, update.text
    assert client.get("/api/admin/users", headers=token).status_code == 403
    access = client.get("/api/admin/access", headers=token).json()
    assert access["role"] == "editor" and access["sections"] == ["ai"]
    revoke = client.delete(f"/api/admin/team/{member.id}", headers=headers(owner))
    assert revoke.status_code == 200, revoke.text
    assert client.get("/api/admin/access", headers=token).status_code == 403
    assert client.get("/api/admin/ai-usage/profiles", headers=token).status_code == 403
    db.refresh(member)
    assert member.is_active and not member.is_admin and not member.is_developer
    assert member.hashed_password == "unchanged-password-hash"
    assert db.query(models.User).count() == 2
    assert db.query(models.AdminConsoleAccess).count() == 0
    assert db.query(models.EnterpriseCredential).count() == 0


def test_concurrent_add_returns_conflict_without_overwriting_first_grant(client, db, owner, monkeypatch):
    member = user(db)
    member_id = member.id
    real_flush = db.flush

    def concurrent_flush(*args, **kwargs):
        # A second administrator wins the insert after this request's existence
        # check. The first grant must survive this request's uniqueness failure.
        with sessionmaker(bind=db.bind)() as other_session:
            other_session.add(models.AdminConsoleAccess(user_id=member_id, role="viewer", sections='["ai"]'))
            other_session.commit()
        real_flush(*args, **kwargs)

    monkeypatch.setattr(db, "flush", concurrent_flush)
    response = client.post("/api/admin/team", headers=headers(owner), json={
        "email": member.email, "role": "admin", "sections": ["users", "team"]})
    assert response.status_code == 409, response.text
    membership = db.get(models.AdminConsoleAccess, member_id)
    assert membership.role == "viewer" and json.loads(membership.sections) == ["ai"]
    assert db.query(models.AdminConsoleAccess).count() == 1


@pytest.mark.parametrize("extra,expected", [({"email": "absent@example.com"}, 404),
    ({"role": "owner"}, 422), ({"sections": []}, 422), ({"sections": ["users", "users"]}, 422),
    ({"sections": ["unknown"]}, 422), ({"sections": ["team"]}, 422), ({"is_admin": True}, 422)])
def test_invalid_grants_never_create_or_promote_accounts(client, db, owner, extra, expected):
    member = user(db)
    payload = {"email": member.email, "role": "editor", "sections": ["users"], **extra}
    response = client.post("/api/admin/team", headers=headers(owner), json=payload)
    assert response.status_code == expected, response.text
    assert db.query(models.AdminConsoleAccess).count() == 0
    assert db.query(models.User).count() == 2
    db.refresh(member)
    assert not member.is_admin and not member.is_developer


@pytest.mark.parametrize("flags", [{"is_active": False}, {"is_enterprise_account": True}])
def test_unusable_login_accounts_cannot_be_assigned(client, db, owner, flags):
    member = user(db, **flags)
    response = client.post("/api/admin/team", headers=headers(owner), json={
        "email": member.email, "role": "viewer", "sections": ["users"]})
    assert response.status_code == 400
    assert db.query(models.AdminConsoleAccess).count() == 0


def test_scoped_manager_cannot_grant_broader_access_or_take_over_broader_target(client, db):
    manager, target = user(db, "manager@example.com"), user(db, "target@example.com")
    grant(db, manager, "admin", ["users", "team"])
    response = client.post("/api/admin/team", headers=headers(manager), json={
        "email": target.email, "role": "admin", "sections": ["users", "ai"]})
    assert response.status_code == 403
    grant(db, target, "viewer", ["ai"])
    for method in ["PATCH", "DELETE"]:
        response = client.request(method, f"/api/admin/team/{target.id}", headers=headers(manager),
                                  json={"role": "viewer", "sections": ["users"]})
        assert response.status_code == 403, response.text
    rows = client.get("/api/admin/team", headers=headers(manager)).json()["members"]
    assert all(not item["can_manage"] for item in rows)
    assert json.loads(db.get(models.AdminConsoleAccess, target.id).sections) == ["ai"]


def test_team_self_and_legacy_accounts_are_protected(client, db, owner):
    developer = user(db, "developer@example.com", is_developer=True)
    ordinary = user(db, "ordinary@example.com")
    grant(db, ordinary, "viewer", ["users"])
    manager = user(db, "manager@example.com")
    grant(db, manager, "admin", admin_access.SECTION_KEYS)
    for actor, target in [(owner, owner), (owner, developer), (developer, owner), (manager, manager), (manager, owner)]:
        for method in ["PATCH", "DELETE"]:
            response = client.request(method, f"/api/admin/team/{target.id}", headers=headers(actor),
                                      json={"role": "viewer", "sections": ["users"]})
            assert response.status_code == 403, response.text
    result = client.get("/api/admin/team", headers=headers(owner))
    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    data = result.json()
    assert data["sections"] == list(admin_access.SECTIONS)
    by_id = {item["user_id"]: item for item in data["members"]}
    assert by_id[owner.id]["protected"] and not by_id[owner.id]["can_manage"]
    assert by_id[developer.id]["protected"] and not by_id[developer.id]["can_manage"]
    assert not by_id[ordinary.id]["protected"] and by_id[ordinary.id]["can_manage"]


@pytest.mark.parametrize("operation", ["activate", "deactivate", "delete"])
@pytest.mark.parametrize("actor_sections,target_sections,expected", [
    (["users"], ["users"], 403),
    (["users", "team"], ["ai"], 403),
    (["users", "team"], ["users"], 200),
])
def test_student_account_actions_cannot_bypass_team_scope(client, db, operation, actor_sections, target_sections, expected):
    actor = user(db, "actor@example.com")
    target = user(db, "target@example.com", is_active=operation != "activate")
    grant(db, actor, "admin", actor_sections)
    grant(db, target, "editor", target_sections)
    target_id = target.id
    if operation == "delete":
        response = client.delete(f"/api/admin/users/{target_id}", headers=headers(actor))
    else:
        response = client.patch(f"/api/admin/users/{target_id}/status", headers=headers(actor),
                                json={"is_active": operation == "activate"})
    assert response.status_code == expected, response.text
    if expected == 403:
        db.refresh(target)
        assert target.is_active is (operation != "activate")
        assert db.get(models.AdminConsoleAccess, target_id) is not None


@pytest.mark.parametrize("flag", ["is_admin", "is_developer"])
def test_student_account_actions_retain_legacy_developer_guard(client, db, owner, flag):
    target = user(db, "protected@example.com", **{flag: True})
    assert client.patch(f"/api/admin/users/{target.id}/status", headers=headers(owner),
                        json={"is_active": False}).status_code == 403
    assert client.delete(f"/api/admin/users/{target.id}", headers=headers(owner)).status_code == 403


def test_delegates_cannot_mint_global_admins_via_enterprise_credentials(client, db):
    actor = user(db)
    grant(db, actor, "admin", admin_access.SECTION_KEYS)
    response = client.post("/api/admin/enterprise/credentials", headers=headers(actor),
                           json={"email": "minted@example.com", "full_name": "Minted"})
    assert response.status_code == 403
    assert db.query(models.User).count() == 1
    assert db.query(models.EnterpriseCredential).count() == 0


def test_editor_cannot_issue_refund_even_though_method_is_post(client, db):
    actor = user(db)
    grant(db, actor, "editor", ["enterprise"])
    response = client.post("/api/admin/enterprise/accounts/999/refunds", headers=headers(actor), json={})
    assert response.status_code == 403


@pytest.mark.parametrize("role,sections", [("owner", '["users"]'), ("viewer", "broken"),
    ("viewer", '["team"]'), ("admin", '["unknown"]'), ("admin", '[]'), ("admin", '{}'),
    ("admin", '["users","users"]'), ("admin", '[["users"]]')])
def test_corrupt_membership_fails_closed(client, db, role, sections):
    person = user(db)
    db.add(models.AdminConsoleAccess(user_id=person.id, role=role, sections=sections))
    db.commit()
    assert client.get("/api/admin/access", headers=headers(person)).status_code == 403


@pytest.mark.parametrize("flags,expected", [({"is_active": False}, 400), ({"is_enterprise_account": True}, 401)])
def test_membership_cannot_override_account_auth_boundary(client, db, flags, expected):
    person = user(db, **flags)
    grant(db, person, "admin", admin_access.SECTION_KEYS)
    assert client.get("/api/admin/access", headers=headers(person)).status_code == expected


def test_viewer_enterprise_details_creates_no_wallet_or_subscription(client, db, monkeypatch):
    viewer = user(db)
    grant(db, viewer, "viewer", ["enterprise"])
    org = models.EnterpriseOrganization(company_name="Example", created_by_user_id=viewer.id)
    db.add(org)
    db.commit()

    def refuse_write(*args, **kwargs):
        raise AssertionError("A Viewer GET must not flush or commit")

    monkeypatch.setattr(db, "flush", refuse_write)
    monkeypatch.setattr(db, "commit", refuse_write)
    response = client.get(f"/api/admin/enterprise/accounts/{org.id}/details", headers=headers(viewer))
    assert response.status_code == 200, response.text
    assert db.query(models.EnterpriseCreditWallet).count() == 0
    assert db.query(models.EnterpriseSubscription).count() == 0
    assert db.query(models.EnterpriseCreditTransaction).count() == 0
