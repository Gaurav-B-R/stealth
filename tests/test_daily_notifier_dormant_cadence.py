"""Daily AI notifier: accounts that have not logged in for 30 days are scanned (and so can
be emailed) once every 14 days instead of daily.

2026-09-05 audit of production: the notifier made one Gemini call per active account per
day with no login gating; 26 of 46 accounts had not logged in for 30+ days or ever, and
they took two-thirds of the job's spend while receiving ~daily AI emails. The cadence is
stateless — a dormant user's scan day is derived from their id — so there is no
last-scanned column to drift, and a login returns them to the daily schedule at once.

Run: cd web_app && python3 -m pytest tests/test_daily_notifier_dormant_cadence.py
"""
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from app.services import daily_ai_notifications as job

NOW = datetime(2026, 9, 5, 6, 0, tzinfo=timezone.utc)
TODAY = NOW.date()


def _user(uid=1, **stamps):
    base = {"created_at": datetime(2026, 1, 1), "first_login_at": None, "last_login_at": None}
    base.update(stamps)
    return SimpleNamespace(id=uid, **base)


def _due_days(user, days=28):
    return [d for d in range(days) if job._is_user_due(user, TODAY + timedelta(days=d), NOW + timedelta(days=d))]


def test_defaults_match_the_product_rule():
    assert job.DAILY_AI_NOTIFIER_DORMANT_AFTER_DAYS == 30
    assert job.DAILY_AI_NOTIFIER_DORMANT_CADENCE_DAYS == 14


def test_recent_login_stays_daily_and_the_30th_day_is_the_boundary():
    assert _due_days(_user(last_login_at=NOW - timedelta(days=1))) == list(range(28))    # every day of the window
    assert not job._is_dormant(_user(last_login_at=NOW - timedelta(days=29, hours=23)), NOW)
    assert job._is_dormant(_user(last_login_at=NOW - timedelta(days=30)), NOW)


def test_dormant_account_is_scanned_exactly_once_per_fortnight():
    for uid in range(1, 40):
        days = _due_days(_user(uid, last_login_at=NOW - timedelta(days=120)))
        assert len(days) == 2 and days[1] - days[0] == 14, (uid, days)


def test_dormant_scans_are_spread_across_the_fortnight_not_piled_on_one_day():
    users = [_user(uid, last_login_at=NOW - timedelta(days=200)) for uid in range(1, 141)]
    per_day = [sum(job._is_user_due(u, TODAY + timedelta(days=d), NOW + timedelta(days=d)) for u in users) for d in range(14)]
    assert sum(per_day) == 140 and max(per_day) == 10 and min(per_day) == 10


def test_never_logged_in_uses_signup_date_then_goes_dormant():
    fresh = _user(created_at=NOW - timedelta(days=3))                 # 3-day-old signup, never verified/logged in
    assert not job._is_dormant(fresh, NOW) and _due_days(fresh, 7) == list(range(7))
    stale = _user(created_at=NOW - timedelta(days=90))                # abandoned signup
    assert job._is_dormant(stale, NOW) and len(_due_days(stale)) == 2
    assert job._is_dormant(SimpleNamespace(id=5, created_at=None, first_login_at=None, last_login_at=None), NOW)


def test_a_login_returns_the_account_to_daily_immediately():
    u = _user(7, last_login_at=NOW - timedelta(days=100))
    assert len(_due_days(u)) == 2
    u.last_login_at = NOW - timedelta(hours=1)
    assert _due_days(u) == list(range(28))


def test_naive_and_aware_timestamps_both_work():
    """Prod columns are naive UTC, the model says timezone=True, the job clock is aware —
    every combination must compare without raising (the 2026-08-23 incident class)."""
    naive_old = _user(last_login_at=datetime(2026, 5, 1, 12, 0))
    aware_old = _user(last_login_at=datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc))
    naive_new = _user(last_login_at=datetime(2026, 9, 4, 12, 0))
    aware_new = _user(last_login_at=datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc))
    for now in (NOW, NOW.replace(tzinfo=None)):
        assert job._is_dormant(naive_old, now) and job._is_dormant(aware_old, now)
        assert not job._is_dormant(naive_new, now) and not job._is_dormant(aware_new, now)


def test_dials_are_env_driven(monkeypatch):
    monkeypatch.setattr(job, "DAILY_AI_NOTIFIER_DORMANT_CADENCE_DAYS", 7)
    days = _due_days(_user(3, last_login_at=NOW - timedelta(days=60)))
    assert len(days) == 4 and all(b - a == 7 for a, b in zip(days, days[1:]))
    monkeypatch.setattr(job, "DAILY_AI_NOTIFIER_DORMANT_AFTER_DAYS", 0)       # 0 = feature off, everyone daily
    assert _due_days(_user(3, last_login_at=NOW - timedelta(days=400))) == list(range(28))
