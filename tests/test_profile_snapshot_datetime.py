"""Regression guard: the profile-snapshot builder must cope with a timezone-aware pass end date.

2026-08-23 incident: a Pro user with a referral reward AND an end date (a 100%-coupon pass
activation) hit `ends_at > datetime.utcnow()` in documents._build_subscription_snapshot_for_profile
with a tz-aware `ends_at` → TypeError on every snapshot refresh → the Rilono AI chat and the
extension Copilot answered "Sorry, I encountered an issue…" (HTTP 500) for that user.

Run: cd web_app && python3 -m pytest tests/test_profile_snapshot_datetime.py
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.database import Base


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False)()
    try:
        yield session
    finally:
        session.close()


def _pro_user_with_referral_and_end_date(db, ends_at):
    user = models.User(email="kushal@example.com", hashed_password="x", full_name="Kushal",
                       referral_reward_granted_at=datetime(2026, 2, 13, 3, 17, tzinfo=timezone.utc))
    db.add(user); db.commit()
    sub = models.Subscription(user_id=user.id, plan="pro", status="active", ends_at=ends_at)
    db.add(sub); db.commit()
    return user


@pytest.mark.parametrize("ends_at", [
    datetime.now(timezone.utc) + timedelta(days=30),      # tz-aware (what Postgres returns)
    datetime.utcnow() + timedelta(days=30),               # naive (what SQLite returns)
])
def test_snapshot_builder_handles_aware_and_naive_end_dates(db, ends_at):
    from app.routers.documents import _build_subscription_snapshot_for_profile
    user = _pro_user_with_referral_and_end_date(db, ends_at)
    # Force the exact object the production session held: a tz-aware value on the instance.
    sub = db.query(models.Subscription).filter(models.Subscription.user_id == user.id).first()
    sub.ends_at = ends_at
    snapshot = _build_subscription_snapshot_for_profile(user, db)      # must not raise
    assert snapshot["plan"] == "pro"
    # no verified payment + referral reward + future end date => referral-bonus access
    assert "Referral Bonus" in snapshot.get("access_source", "")


def test_chat_does_not_500_when_the_snapshot_refresh_raises(monkeypatch):
    """Even if a future snapshot bug appears, the chat answers from the cached profile."""
    import inspect
    from app.routers import ai_chat
    src = inspect.getsource(ai_chat.chat_with_ai)
    assert "try:\n            refresh_student_profile_if_stale(current_user, db)" in src
    assert "profile snapshot refresh failed" in src
