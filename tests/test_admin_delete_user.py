"""Regression guards for permanent account deletion (admin console + self-service).

2026-08-20 incident: the admin console's Delete action 500ed ("Failed to delete user
account. Please try again.") for any user with rows in one of the ~40 tables that
reference users.id with no ORM cascade and no manual cleanup — production Postgres is
NO ACTION on every users FK except user_course_finder_recs, so one leftover row aborts
the whole delete. Blockers seen in the wild: university_shortlist_entries + sop_drafts
for B2C students; virtually every enterprise_* table for staff.

These tests pin down the fix (app/utils/user_deletion.py, shared by both endpoints):

1. Users with shortlist / SOP-draft / Course-Finder / AI-upload rows delete cleanly:
   their personal rows are erased, financial + referral rows survive de-identified.
2. Enterprise members delete cleanly: membership / notification / AI-thread / step-up
   OTP rows are removed, shared audit rows survive with the actor de-linked.
3. Owners of NOT NULL enterprise records (organizations / CRM clients / legacy
   students) get a clear 409 up front, never an opaque 500.
4. The self-service delete_account path shares the same cleanup (SOP drafts used to
   block it too).

The SQLite test engine enables PRAGMA foreign_keys so FK enforcement matches Postgres.

Run: cd web_app && python3 -m pytest tests/test_admin_delete_user.py
"""

from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.auth import get_current_active_user, get_current_admin_user
from app.database import Base, get_db
from app.routers import admin as admin_router
from app.routers import profile as profile_router
from app.utils.token_security import hash_token


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # Match Postgres: without this pragma SQLite ignores FK constraints entirely and
    # the tests would pass even if the cleanup regressed.
    @event.listens_for(engine, "connect")
    def _enable_sqlite_fks(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False)()
    try:
        yield session
    finally:
        session.close()


def _make_user(db, email, **extra) -> models.User:
    user = models.User(email=email, hashed_password="x", email_notifications_enabled=False, **extra)
    db.add(user)
    db.commit()
    return user


def _admin_client(db, admin_user) -> TestClient:
    app = FastAPI()
    app.include_router(admin_router.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_admin_user] = lambda: admin_user
    app.dependency_overrides[admin_router.require_admin_turnstile_proof] = lambda: None
    return TestClient(app)


def _profile_client(db, current_user) -> TestClient:
    app = FastAPI()
    app.include_router(profile_router.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_active_user] = lambda: current_user
    return TestClient(app)


def _make_org(db, owner) -> models.EnterpriseOrganization:
    org = models.EnterpriseOrganization(company_name="Acme", created_by_user_id=owner.id)
    db.add(org)
    db.commit()
    return org


def test_admin_delete_bare_user_succeeds(db_session):
    admin = _make_user(db_session, "admin@example.com", is_admin=True)
    victim = _make_user(db_session, "bare@example.com")

    response = _admin_client(db_session, admin).delete(f"/api/admin/users/{victim.id}")

    assert response.status_code == 200
    assert db_session.query(models.User).filter_by(id=victim.id).first() is None


def test_admin_delete_student_with_related_rows(db_session):
    """The exact 2026-08-20 failure: shortlist + SOP rows used to 500 the delete."""
    admin = _make_user(db_session, "admin@example.com", is_admin=True)
    victim = _make_user(db_session, "student@example.com")
    referred = _make_user(db_session, "friend@example.com", referred_by_user_id=victim.id)

    db_session.add_all([
        models.UniversityShortlistEntry(user_id=victim.id, university_name="MIT"),
        models.SopDraft(user_id=victim.id, university="MIT", program="CS", content_md="draft"),
        models.UserCourseFinderRec(user_id=victim.id),
        models.RilonoAiChatUploadEvent(user_id=victim.id, attachment_id="att_1"),
        models.SubscriptionPayment(
            user_id=victim.id, amount_paise=99900, razorpay_order_id="order_DEL_TEST_1"
        ),
        models.CouponCode(coupon_code="ONLYYOU10", percent_off=10, restricted_to_user_id=victim.id),
    ])
    db_session.commit()

    response = _admin_client(db_session, admin).delete(f"/api/admin/users/{victim.id}")

    assert response.status_code == 200, response.json()
    assert db_session.query(models.User).filter_by(id=victim.id).first() is None
    # Personal rows erased.
    assert db_session.query(models.UniversityShortlistEntry).count() == 0
    assert db_session.query(models.SopDraft).count() == 0
    assert db_session.query(models.UserCourseFinderRec).count() == 0
    assert db_session.query(models.RilonoAiChatUploadEvent).count() == 0
    # A per-account coupon must not fall open to everyone — it is deleted.
    assert db_session.query(models.CouponCode).count() == 0
    # Financial record survives de-identified; referral link is severed.
    payment = db_session.query(models.SubscriptionPayment).one()
    assert payment.user_id is None
    db_session.refresh(referred)
    assert referred.referred_by_user_id is None


def test_admin_delete_enterprise_member_succeeds(db_session):
    admin = _make_user(db_session, "admin@example.com", is_admin=True)
    owner = _make_user(db_session, "owner@example.com")
    victim = _make_user(db_session, "staff@example.com")
    org = _make_org(db_session, owner)

    conversation = models.EnterpriseAiConversation(organization_id=org.id, user_id=victim.id)
    branch = models.EnterpriseBranch(organization_id=org.id, name="HQ")
    membership = models.EnterpriseOrganizationMember(
        organization_id=org.id, user_id=victim.id, invited_by_user_id=owner.id
    )
    db_session.add_all([conversation, branch, membership])
    db_session.commit()
    db_session.add_all([
        models.EnterpriseAiMessage(
            conversation_id=conversation.id, organization_id=org.id, role="user", content="hi"
        ),
        models.EnterpriseMemberBranch(
            organization_id=org.id, member_id=membership.id, branch_id=branch.id
        ),
        models.EnterpriseSupportRequest(
            organization_id=org.id,
            user_id=victim.id,
            requester_name="Staff Member",
            requester_email="staff@example.com",
            subject="help",
            message="please",
        ),
        models.EnterpriseNotification(
            organization_id=org.id,
            recipient_user_id=victim.id,
            actor_user_id=owner.id,
            type="client_added",
            title="t",
        ),
        models.EnterpriseNotification(
            organization_id=org.id,
            recipient_user_id=owner.id,
            actor_user_id=victim.id,
            type="member_added",
            title="t",
        ),
        models.EnterpriseStepUpOtp(
            user_id=victim.id,
            organization_id=org.id,
            purpose="owner_transfer",
            code_hash="h",
            expires_at=datetime.utcnow() + timedelta(minutes=5),
        ),
        models.EnterpriseAccessAudit(
            organization_id=org.id,
            action="member_role_changed",
            actor_user_id=victim.id,
            summary="changed a role",
        ),
    ])
    db_session.commit()

    response = _admin_client(db_session, admin).delete(f"/api/admin/users/{victim.id}")

    assert response.status_code == 200, response.json()
    assert db_session.query(models.User).filter_by(id=victim.id).first() is None
    # The member's own rows are gone...
    assert db_session.query(models.EnterpriseOrganizationMember).count() == 0
    assert db_session.query(models.EnterpriseMemberBranch).count() == 0
    assert db_session.query(models.EnterpriseAiConversation).count() == 0
    assert db_session.query(models.EnterpriseAiMessage).count() == 0
    assert db_session.query(models.EnterpriseStepUpOtp).count() == 0
    # ...support requests survive but are truly de-identified (they carry name+email too)...
    support_request = db_session.query(models.EnterpriseSupportRequest).one()
    assert support_request.user_id is None
    assert support_request.requester_name is None
    assert support_request.requester_email is None
    # ...notifications TO them are gone, notifications BY them survive de-linked...
    remaining_notification = db_session.query(models.EnterpriseNotification).one()
    assert remaining_notification.recipient_user_id == owner.id
    assert remaining_notification.actor_user_id is None
    # ...and the audit trail survives with the actor de-linked.
    audit_row = db_session.query(models.EnterpriseAccessAudit).one()
    assert audit_row.actor_user_id is None


def test_admin_delete_current_workspace_owner_gets_clear_409(db_session):
    """Ownership can be transferred after creation (role_key='owner' moves, created_by
    does not) — the current owner must be blocked too, or the workspace goes ownerless."""
    admin = _make_user(db_session, "admin@example.com", is_admin=True)
    creator = _make_user(db_session, "creator@example.com")
    new_owner = _make_user(db_session, "newowner@example.com")
    org = _make_org(db_session, creator)
    db_session.add(
        models.EnterpriseOrganizationMember(
            organization_id=org.id, user_id=new_owner.id, role_key="owner"
        )
    )
    db_session.commit()

    response = _admin_client(db_session, admin).delete(f"/api/admin/users/{new_owner.id}")

    assert response.status_code == 409
    assert "transfer workspace ownership" in response.json()["detail"]
    assert db_session.query(models.User).filter_by(id=new_owner.id).first() is not None


def test_every_users_fk_is_classified_for_deletion():
    """Drift guard: a future model referencing users.id must be classified in
    app/utils/user_deletion.py (delete / de-link / blocker) or it silently reintroduces
    the FK-violation 500 this suite exists to prevent."""
    from app.database import Base as AppBase
    from app.utils import user_deletion

    covered = set()
    for model, column in user_deletion._DELETE_USER_ROWS:
        covered.add((model.__tablename__, column))
    for model, column in user_deletion._DELINK_USER_COLUMNS:
        covered.add((model.__tablename__, column))
    for _label, model, column in user_deletion._OWNERSHIP_BLOCKERS:
        covered.add((model.__tablename__, column))
    covered |= {
        # ORM cascades on the User relationships (models.py).
        ("documents", "user_id"),
        ("subscriptions", "user_id"),
        ("user_notifications", "user_id"),
        # Special-cased inside purge_user_references.
        ("enterprise_ai_conversations", "user_id"),
        ("enterprise_organization_members", "user_id"),
        ("enterprise_support_requests", "user_id"),
        ("coupon_codes", "restricted_to_user_id"),
        ("users", "referred_by_user_id"),
    }

    unclassified = []
    for table in AppBase.metadata.tables.values():
        for column in table.columns:
            for fk in column.foreign_keys:
                if fk.column.table.name == "users" and (table.name, column.name) not in covered:
                    unclassified.append(f"{table.name}.{column.name}")

    assert not unclassified, (
        "New users.id FK(s) not handled by account deletion — classify them in "
        f"app/utils/user_deletion.py: {sorted(unclassified)}"
    )


def test_admin_delete_org_owner_gets_clear_409(db_session):
    admin = _make_user(db_session, "admin@example.com", is_admin=True)
    owner = _make_user(db_session, "owner@example.com")
    _make_org(db_session, owner)

    response = _admin_client(db_session, admin).delete(f"/api/admin/users/{owner.id}")

    assert response.status_code == 409
    assert "enterprise organization" in response.json()["detail"]
    assert db_session.query(models.User).filter_by(id=owner.id).first() is not None


def _arm_delete_otp(db, user, code="123456"):
    user.account_deletion_otp = hash_token(code)
    user.account_deletion_otp_expires = datetime.utcnow() + timedelta(minutes=10)
    db.commit()
    return code


def test_self_service_delete_with_sop_draft_succeeds(db_session):
    """sop_drafts used to block delete_account too — nothing cleaned that table."""
    user = _make_user(db_session, "student@example.com")
    db_session.add(models.SopDraft(user_id=user.id, university="MIT", program="CS", content_md="draft"))
    db_session.commit()
    code = _arm_delete_otp(db_session, user)

    response = _profile_client(db_session, user).request(
        "DELETE", "/api/profile/", json={"code": code}
    )

    assert response.status_code == 204, response.text
    assert db_session.query(models.User).filter_by(id=user.id).first() is None
    assert db_session.query(models.SopDraft).count() == 0


def test_self_service_delete_org_owner_gets_clear_409(db_session):
    owner = _make_user(db_session, "owner@example.com")
    _make_org(db_session, owner)
    code = _arm_delete_otp(db_session, owner)

    response = _profile_client(db_session, owner).request(
        "DELETE", "/api/profile/", json={"code": code}
    )

    assert response.status_code == 409
    assert db_session.query(models.User).filter_by(id=owner.id).first() is not None
