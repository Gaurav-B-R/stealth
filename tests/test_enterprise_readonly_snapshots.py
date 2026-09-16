"""Admin read views must not provision billing rows or alter customer balances."""

from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app import enterprise_billing as billing
from app import enterprise_credits as credits
from app import models
from app.database import Base


NOW = datetime(2026, 9, 13, 12)


class FixedDatetime(datetime):
    @classmethod
    def utcnow(cls):
        return NOW


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setattr(billing, "datetime", FixedDatetime)
    monkeypatch.setattr(credits, "datetime", FixedDatetime)
    monkeypatch.setattr(billing, "ENTERPRISE_FREE", False)
    monkeypatch.setattr(credits, "PLAN_CREDITS_ROLLOVER", False)
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    owner = models.User(email="snapshot-owner@example.com", hashed_password="test-only")
    session.add(owner)
    session.flush()
    org = models.EnterpriseOrganization(
        company_name="Snapshot test", created_by_user_id=owner.id, created_at=NOW,
    )
    session.add(org)
    session.commit()
    session.info["org_id"] = org.id
    yield session
    session.close()
    engine.dispose()


@contextmanager
def forbid_writes(db):
    def check_sql(_conn, _cursor, statement, _params, _context, _many):
        assert statement.lstrip().upper().startswith("SELECT"), statement

    engine = db.get_bind()
    before_new, before_dirty = set(db.new), set(db.dirty)
    event.listen(engine, "before_cursor_execute", check_sql)
    try:
        with patch.object(db, "flush", side_effect=AssertionError("read view flushed")), \
                patch.object(db, "commit", side_effect=AssertionError("read view committed")), \
                patch.object(db, "add", side_effect=AssertionError("read view added a row")), \
                patch.object(credits, "_sync_plan_credits_quietly", side_effect=AssertionError("read view synchronized credits")):
            yield
        assert set(db.new) == before_new
        assert set(db.dirty) == before_dirty
    finally:
        event.remove(engine, "before_cursor_execute", check_sql)


def test_missing_rows_render_defaults_without_provisioning(db):
    org_id = db.info["org_id"]
    with forbid_writes(db):
        wallet = credits.wallet_state(db, org_id, read_only=True)
        subscription = billing.build_subscription_state(db, org_id, read_only=True)
    assert wallet["balance_credits"] == 0
    assert wallet["plan_credits"]["remaining_this_period"] == 0
    assert wallet["plan_credits"]["period_key"] is None
    assert subscription["plan"] == billing.TRIAL_PLAN
    assert subscription["status"] == "trialing"
    assert subscription["trial_ends_at"] == NOW + timedelta(days=billing.DEFAULT_TRIAL_DAYS)
    assert db.query(models.EnterpriseCreditWallet).count() == 0
    assert db.query(models.EnterpriseSubscription).count() == 0
    assert db.query(models.EnterpriseCreditTransaction).count() == 0


def test_existing_lapsed_plan_snapshot_does_not_grant_or_claw_back(db):
    org_id = db.info["org_id"]
    db.add(models.EnterpriseSubscription(
        organization_id=org_id, plan="starter", status="active",
        current_period_end=NOW - timedelta(days=15),
    ))
    wallet = models.EnterpriseCreditWallet(
        organization_id=org_id, balance_credits=280,
        lifetime_purchased_credits=300, lifetime_spent_credits=20,
        plan_credits_period="starter:2026-07-01",
        plan_credits_granted=300, plan_credits_remaining=250,
    )
    db.add(wallet)
    db.commit()
    with forbid_writes(db):
        state = credits.wallet_state(db, org_id, read_only=True)
        subscription = billing.build_subscription_state(db, org_id, read_only=True)
    assert state["balance_credits"] == 280
    assert state["plan_credits"]["remaining_this_period"] == 250
    assert state["plan_credits"]["period_key"] == "starter:2026-07-01"
    assert subscription["status"] == "lapsed"
    assert subscription["lapsed_plan"] == "starter"
    db.refresh(wallet)
    assert wallet.balance_credits == 280
    assert wallet.plan_credits_remaining == 250
    assert db.query(models.EnterpriseCreditTransaction).count() == 0


def test_read_views_do_not_autoflush_unrelated_pending_work(db):
    pending = models.User(email="pending@example.com", hashed_password="test-only")
    db.add(pending)
    with forbid_writes(db):
        credits.wallet_state(db, db.info["org_id"], read_only=True)
        billing.build_subscription_state(db, db.info["org_id"], read_only=True)
    assert pending.id is None
    assert pending in db.new
    db.rollback()
    assert db.query(models.User).filter_by(email="pending@example.com").count() == 0


def test_default_view_still_provisions_grants_and_matches_stored_snapshot(db):
    org_id = db.info["org_id"]
    wallet = credits.wallet_state(db, org_id)
    subscription = billing.build_subscription_state(db, org_id)
    assert wallet["balance_credits"] == billing.included_credits_for(billing.TRIAL_PLAN)
    assert db.query(models.EnterpriseCreditWallet).count() == 1
    assert db.query(models.EnterpriseSubscription).count() == 1
    assert db.query(models.EnterpriseCreditTransaction).count() == 1
    with forbid_writes(db):
        assert credits.wallet_state(db, org_id, read_only=True) == wallet
        assert billing.build_subscription_state(db, org_id, read_only=True) == subscription


def test_free_platform_read_view_preserves_shape_without_writes(db, monkeypatch):
    monkeypatch.setattr(billing, "ENTERPRISE_FREE", True)
    with forbid_writes(db):
        state = billing.build_subscription_state(db, db.info["org_id"], read_only=True)
    assert state["is_free_platform"] is True
    assert state["plan"] == "free"
    assert state["max_clients"] == billing.UNLIMITED
    assert db.query(models.EnterpriseSubscription).count() == 0
