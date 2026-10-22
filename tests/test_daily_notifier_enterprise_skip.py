"""Daily AI notifier: Rilono Enterprise (B2B) accounts are never scanned.

Pricing-model review, Phase 0 ("stop the daily notifier scanning enterprise staff
accounts"): the job ran a profile-snapshot rebuild (an R2 write), R2 reads and one Gemini
call per active user per day, including workspace owners and their staff, who have no
student journey to nudge. An account counts as enterprise when users.is_enterprise_account
is set OR it holds ANY active enterprise_organization_members row. The exclusion is in the
SQL that lists candidates (and re-checked when each user is loaded), so no snapshot, R2 or
Gemini work can run for such an account, and the dormancy cadence / USER_LIMIT only ever
see consumer accounts.

These tests run the real job against an in-memory SQLite database with the external
steps (snapshot refresh, R2, Gemini) replaced by recorders.

Run: cd web_app && python3 -m pytest tests/test_daily_notifier_enterprise_skip.py
"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.database import Base
from app.services import daily_ai_notifications as job


RECENT = datetime.utcnow() - timedelta(days=1)          # active account: due every day
LONG_AGO = datetime.utcnow() - timedelta(days=400)      # dormant account


@pytest.fixture
def env(monkeypatch):
    """Fresh shared in-memory DB wired into the job's SessionLocal, with every external
    side effect replaced by a recorder so a test can assert exactly which users reached
    the snapshot refresh (the R2 write) and the Gemini call."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    monkeypatch.setattr(job, "SessionLocal", Session)

    calls = {"snapshot": [], "profile": [], "docs": [], "gemini": []}

    def fake_snapshot(*, user, db):
        calls["snapshot"].append(user.id)

    def fake_profile(user_id, r2_client):
        calls["profile"].append(user_id)
        return "{}"

    def fake_docs(user_id, db_session, r2_client):
        calls["docs"].append(user_id)
        return []

    def fake_analyze(model, prompt, user_id, model_name):
        calls["gemini"].append(user_id)
        return job.DailyAssistantDecision(notification_needed=False, reasoning="nothing to do")

    monkeypatch.setattr(job, "refresh_student_profile_snapshot_for_user", fake_snapshot)
    monkeypatch.setattr(job, "_load_profile_raw_json", fake_profile)
    monkeypatch.setattr(job, "_load_user_document_payload", fake_docs)
    monkeypatch.setattr(job, "_analyze_user", fake_analyze)
    monkeypatch.setattr(job, "_build_gemini_model", lambda model_name=None: (object(), "genai"))
    monkeypatch.setattr(job, "_build_r2_client", lambda: object())
    monkeypatch.setattr(job, "DAILY_AI_NOTIFIER_USER_LIMIT", 0)

    session = Session()
    yield session, calls
    session.close()
    engine.dispose()


def _user(db, email, *, enterprise=False, active=True, last_login=RECENT, **extra):
    user = models.User(
        email=email,
        hashed_password="test-only",
        is_active=active,
        is_enterprise_account=enterprise,
        last_login_at=last_login,
        **extra,
    )
    db.add(user)
    db.flush()
    return user


def _org(db, owner, name="Acme Overseas"):
    org = models.EnterpriseOrganization(company_name=name, created_by_user_id=owner.id)
    db.add(org)
    db.flush()
    return org


def _member(db, org, user, *, active=True):
    db.add(models.EnterpriseOrganizationMember(
        organization_id=org.id, user_id=user.id, role="viewer", role_key="viewer",
        is_active=active, status="active" if active else "suspended",
    ))
    db.flush()


def _all_external_calls(calls):
    return set(calls["snapshot"]) | set(calls["profile"]) | set(calls["docs"]) | set(calls["gemini"])


def test_enterprise_accounts_never_reach_snapshot_r2_or_gemini(env):
    db, calls = env
    student = _user(db, "student@example.com")
    owner = _user(db, "owner@acme.example", enterprise=True)          # flagged, no member row yet
    org = _org(db, owner)
    _member(db, org, owner)
    flagged_only = _user(db, "invitee@acme.example", enterprise=True)  # flag alone is enough
    joined_b2c = _user(db, "joined@example.com")                      # B2C user who joined a team
    _member(db, org, joined_b2c)
    left_team = _user(db, "left@example.com")                         # membership deactivated
    _member(db, org, left_team, active=False)
    _user(db, "gone@example.com", active=False)                       # inactive: excluded as before
    db.commit()

    result = job.run_daily_ai_notification_job(force=True)

    assert result["status"] == "completed", result
    scanned = {student.id, left_team.id}
    assert set(calls["snapshot"]) == scanned
    assert set(calls["gemini"]) == scanned
    assert _all_external_calls(calls) == scanned
    assert not ({owner.id, flagged_only.id, joined_b2c.id} & _all_external_calls(calls))
    assert result["users_scanned"] == 2
    assert result["users_skipped_enterprise"] == 3
    assert result["users_skipped_dormant"] == 0


def test_any_active_membership_skips_even_with_an_old_inactive_one_and_multiple_orgs(env):
    db, calls = env
    owner_a = _user(db, "a@agency-a.example", enterprise=True)
    owner_b = _user(db, "b@agency-b.example", enterprise=True)
    org_a, org_b = _org(db, owner_a, "Agency A"), _org(db, owner_b, "Agency B")
    two_orgs = _user(db, "consultant@example.com")
    _member(db, org_a, two_orgs)
    _member(db, org_b, two_orgs)
    mixed = _user(db, "mixed@example.com")
    _member(db, org_a, mixed, active=False)
    _member(db, org_b, mixed, active=True)
    student = _user(db, "student@example.com")
    db.commit()

    result = job.run_daily_ai_notification_job(force=True)

    assert _all_external_calls(calls) == {student.id}
    # NOT EXISTS, not a join: a user in two orgs is still one skipped account.
    assert result["users_skipped_enterprise"] == 4
    assert result["users_scanned"] == 1


def test_platform_staff_in_a_workspace_are_skipped_too(env):
    """Unlike auth.is_enterprise_only_account (a LOGIN rule), admins are not exempt here."""
    db, calls = env
    owner = _user(db, "owner@acme.example", enterprise=True)
    org = _org(db, owner)
    admin = _user(db, "staff@rilono.example", is_admin=True)
    _member(db, org, admin)
    dev_flagged = _user(db, "dev@rilono.example", is_developer=True, enterprise=True)
    student = _user(db, "student@example.com")
    db.commit()

    job.run_daily_ai_notification_job(force=True)

    assert _all_external_calls(calls) == {student.id}
    assert admin.id not in calls["snapshot"] and dev_flagged.id not in calls["snapshot"]


def test_enterprise_accounts_do_not_use_up_the_user_limit(env, monkeypatch):
    db, calls = env
    owner = _user(db, "owner@acme.example", enterprise=True)          # lowest id
    org = _org(db, owner)
    _member(db, org, owner)
    student = _user(db, "student@example.com")
    db.commit()
    assert owner.id < student.id
    monkeypatch.setattr(job, "DAILY_AI_NOTIFIER_USER_LIMIT", 1)

    result = job.run_daily_ai_notification_job(force=True)

    assert calls["gemini"] == [student.id]
    assert result["users_scanned"] == 1


def test_dormancy_cadence_still_applies_to_consumers_and_ignores_enterprise(env):
    db, calls = env
    cadence = job.DAILY_AI_NOTIFIER_DORMANT_CADENCE_DAYS
    today = datetime.utcnow().date().toordinal() % cadence
    # Explicit ids so the fortnightly-day maths is deterministic whatever date the suite
    # runs on: a dormant consumer is due only when today % cadence == id % cadence.
    not_due_id = 1000 * cadence + (today + 1) % cadence
    due_id = 2000 * cadence + today
    dormant_deferred = _user(db, "dormant-deferred@example.com", last_login=LONG_AGO, id=not_due_id)
    dormant_due = _user(db, "dormant-due@example.com", last_login=LONG_AGO, id=due_id)
    # A dormant enterprise owner on ITS due day: still never scanned.
    dormant_enterprise = _user(db, "old-owner@acme.example", enterprise=True, last_login=LONG_AGO,
                               id=3000 * cadence + today)
    student = _user(db, "student@example.com")
    db.commit()

    result = job.run_daily_ai_notification_job(force=True)

    assert _all_external_calls(calls) == {student.id, dormant_due.id}
    assert dormant_deferred.id not in _all_external_calls(calls)
    assert dormant_enterprise.id not in _all_external_calls(calls)
    # The enterprise owner is filtered in SQL, so it is reported as an enterprise skip,
    # never as a dormant deferral.
    assert result["users_skipped_dormant"] == 1
    assert result["users_skipped_enterprise"] == 1
    assert result["users_scanned"] == 2


def test_process_single_user_rechecks_so_a_mid_run_join_is_dropped_before_the_snapshot(env):
    """A run walks due users one Gemini call at a time; a user who joins a workspace after
    the candidate list was built must still be dropped before the snapshot's R2 write."""
    db, calls = env
    owner = _user(db, "owner@acme.example", enterprise=True)
    org = _org(db, owner)
    joiner = _user(db, "joiner@example.com")
    student = _user(db, "student@example.com")
    _member(db, org, joiner)
    db.commit()

    assert job._process_single_user(joiner.id, model=object(), model_name="m", r2_client=object()) is False
    assert job._process_single_user(owner.id, model=object(), model_name="m", r2_client=object()) is False
    assert _all_external_calls(calls) == set()

    job._process_single_user(student.id, model=object(), model_name="m", r2_client=object())
    assert calls["snapshot"] == [student.id] and calls["gemini"] == [student.id]


def test_clause_is_a_correlated_not_exists_that_treats_a_null_flag_as_consumer():
    """Pin the SQL shape on PostgreSQL (production): `IS NOT true` keeps a NULL flag in the
    consumer set, and the membership test is a NOT EXISTS (no join, no duplicate rows)."""
    stmt = select(models.User.id).where(job._consumer_account_clause())
    sql = str(stmt.compile(dialect=postgresql.dialect())).replace("\n", " ")
    assert "users.is_enterprise_account IS NOT true" in sql
    assert "NOT (EXISTS (SELECT" in sql
    assert "enterprise_organization_members.user_id = users.id" in sql
    assert "enterprise_organization_members.is_active IS true" in sql
    assert " JOIN " not in sql
