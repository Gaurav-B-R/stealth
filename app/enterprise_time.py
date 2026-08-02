"""
The time zone an organization actually works in.

`enterprise_calendar_events` stores a naive wall-clock time ("14:30") next to a plain date —
no offset, no zone. That is only meaningful against some agreed-upon zone, and until now
there wasn't one. Three different components each picked their own answer to "what is today,
and is this overdue?":

  * the calendar endpoints asked the server process (`date.today()`),
  * the daily digest job asked UTC,
  * the browser rendered every time in whatever zone the reader's laptop was set to.

West of UTC those disagree by a whole day for part of every evening, which is how a reminder
for tomorrow ends up in an inbox labelled "Today". This module makes it one answer — the
org's operating zone, taken from its default office — and every place that decides "today",
computes "overdue", or prints a clock time goes through here.

An org that has set no office zone falls back to UTC, which is what the digest job already
did, so a workspace that never opens the office form sees no change in behaviour.

The office zone itself is validated on write (see `enterprise_team._clean_timezone`), but
this module still re-checks: rows predate that validation, and a tz database can lose a zone
between releases. An unloadable zone degrades to UTC rather than raising — a stale string in
one office must never take the calendar down.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from app import models

logger = logging.getLogger(__name__)

# What an org gets before anyone fills in an office zone. UTC and not, say, Asia/Kolkata:
# guessing a zone for a workspace that hasn't told us is how a London consultancy silently
# starts running on Indian dates.
DEFAULT_TIMEZONE = "UTC"


def resolve_zone(name: str | None) -> ZoneInfo:
    """A loadable ZoneInfo for `name`, falling back to UTC. Never raises."""
    text = (name or "").strip()
    if not text:
        return ZoneInfo(DEFAULT_TIMEZONE)
    try:
        return ZoneInfo(text)
    except (ZoneInfoNotFoundError, ValueError):
        # Pre-validation leftovers ("IST", "GMT+5:30") land here.
        logger.warning("Unloadable time zone %r — falling back to %s", text, DEFAULT_TIMEZONE)
        return ZoneInfo(DEFAULT_TIMEZONE)
    except Exception:  # pragma: no cover — no tz database on this host
        logger.exception("Time zone lookup failed for %r", text)
        return ZoneInfo(DEFAULT_TIMEZONE)


def configured_org_timezone(db: Session, organization_id: int) -> str | None:
    """The zone an office actually set, or None if nobody has.

    Kept distinct from `org_timezone`, which substitutes UTC. For date arithmetic UTC is a
    safe stand-in — it is what the digest job already used. For a printed LABEL it is a
    claim, and "14:30 UTC" beside a time a Hyderabad counsellor typed as local is worse
    than printing no zone at all. Callers that display use this one; callers that compute
    use `org_timezone`.

    Offices without a zone are skipped rather than counted — a workspace where only the
    Dubai branch filled the field should run on Dubai time, not fall back to UTC because
    Head Office was created before the field was a picker.
    """
    row = (
        db.query(models.EnterpriseBranch.timezone)
        .filter(
            models.EnterpriseBranch.organization_id == int(organization_id),
            models.EnterpriseBranch.is_active.is_(True),
            models.EnterpriseBranch.timezone.isnot(None),
            models.EnterpriseBranch.timezone != "",
        )
        # Default office wins; oldest office breaks the tie, so the answer is stable across
        # requests rather than dependent on row order.
        .order_by(models.EnterpriseBranch.is_default.desc(), models.EnterpriseBranch.id.asc())
        .first()
    )
    if not row or not row[0]:
        return None
    return str(resolve_zone(row[0]).key)


def org_timezone(db: Session, organization_id: int) -> str:
    """The zone to compute in. Always loadable; UTC when no office has set one."""
    return configured_org_timezone(db, organization_id) or DEFAULT_TIMEZONE


def today_in(tz_name: str | None) -> date:
    """The current calendar date in `tz_name` — the only correct basis for "is this overdue"."""
    return datetime.now(resolve_zone(tz_name)).date()


def org_today(db: Session, organization_id: int) -> date:
    return today_in(org_timezone(db, organization_id))


def org_clock(db: Session, organization_id: int) -> tuple[str | None, date, str]:
    """One query → (configured zone or None, today in it, short label or "").

    The three answers callers actually need, resolved together so a single response can't
    grade its events against one date and print another.
    """
    tz = configured_org_timezone(db, organization_id)
    return tz, today_in(tz), (zone_label(tz) if tz else "")


def zone_label(tz_name: str | None, when: datetime | None = None) -> str:
    """A short label to print next to a clock time — "IST", "BST", "EDT", "GMT+05:45".

    DST-aware, so it is resolved against `when` (default: now) rather than cached: a London
    office is "GMT" in January and "BST" in July, and a label that says the wrong one is
    worse than no label at all.
    """
    tz = resolve_zone(tz_name)
    moment = (when or datetime.now(timezone.utc)).astimezone(tz)
    abbrev = moment.strftime("%Z")
    # Zones with no common abbreviation render as a raw offset — "+04" for Dubai, "+0545"
    # for Kathmandu. Spell those as GMT+04 / GMT+05:45, which read as a time zone rather
    # than as a stray number.
    if abbrev and abbrev[0] in "+-":
        return f"GMT{abbrev[:3]}:{abbrev[3:5]}" if len(abbrev) >= 5 else f"GMT{abbrev}"
    return abbrev or "UTC"
