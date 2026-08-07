"""Is this date one a human could have meant to type, and is it pointing the right way?

Every staff-entered date in the CRM used to be checked for FORMAT and nothing else
(`_parse_iso_date_or_400` in routers/enterprise.py, `_parse_date_input` in
enterprise_finance.py). A slipped digit therefore stored cleanly and only surfaced
downstream, where the damage is quiet and permanent: a payment dated 2099 counts toward
"Collected this month" forever (the dashboard bounds only the lower end) while vanishing
from the Finance period report (which bounds both), so two screens disagree about the same
money and neither looks wrong on its own.

Two layers, because they answer different questions:

  * SANITY (`is_sane`) — could this be a real date at all? A wide window, sized to catch
    the ways a year actually gets mistyped (a leading-digit slip renders as 0226 or 1026;
    a stuck key as 20999 → clamped, or 2099). Deliberately loose: it must never reject a
    date someone legitimately meant, so it is a typo net, not a business rule.

  * DIRECTION (`direction=`) — must this one point backwards or forwards? Only applied
    where the answer is unambiguous. Money already received cannot arrive tomorrow; an
    invoice cannot fall due yesterday; nobody is born in the future. Most date fields have
    NO honest direction and must not be given one — an expired passport, a follow-up that
    is overdue, and an English test already sat are all real records a counsellor must be
    able to enter, so `passport_expiry`, `next_followup_date`, `target_date` and
    `english_test_date` get sanity bounds only.

"Future" is judged against the ORG's calendar, not the server's: an org that has set no
office zone computes in UTC (see `enterprise_time`), so a counsellor in IST filling a form
before 05:30 local is already on "tomorrow" by that reckoning. `GRACE_DAYS` absorbs that.

Callers that take user input raise (`validate` / `validate_for_org`); callers processing
machine output — the AI document extraction — ask `is_sane` and skip the field instead, so
one bad OCR read drops a value rather than 400-ing an upload the counsellor can't fix.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import enterprise_time

# Nothing this product records predates the 20th century. Chosen to sit below any real
# date of birth (a 100-year-old client was born in the 1920s) while still catching every
# leading-digit slip, which lands in the first millennium.
EARLIEST_SANE_DATE = date(1900, 1, 1)

# Approximate years on purpose (366-day) — a sanity ceiling needs no calendar precision,
# and `date.replace(year=…)` raises on 29 February. Nothing here legitimately reaches 25
# years out: the longest passport is 10, and an intake deadline is at most ~5.
MAX_FUTURE_DAYS = 25 * 366

# Zone offsets top out at UTC+14, so one day covers every browser-vs-org-calendar gap.
GRACE_DAYS = 1

# `direction` values. NOT_FUTURE/NOT_PAST are relative to the org's today plus grace.
NOT_FUTURE = "not_future"
NOT_PAST = "not_past"


def latest_sane_date(today: date) -> date:
    return today + timedelta(days=MAX_FUTURE_DAYS)


def is_sane(value: Optional[date], today: Optional[date] = None) -> bool:
    """True if `value` could plausibly be a real date someone meant to enter.

    `None` is sane — an absent optional date is not an error. Takes `today` so a caller
    that already resolved the org's calendar doesn't re-query for it.
    """
    if value is None:
        return True
    if not isinstance(value, date):
        return False
    return EARLIEST_SANE_DATE <= value <= latest_sane_date(today or date.today())


def validate(
    value: Optional[date],
    label: str,
    *,
    today: date,
    direction: Optional[str] = None,
    earliest: Optional[date] = None,
    future_hint: str = "",
    past_hint: str = "",
) -> Optional[date]:
    """Bound one staff-entered date, or raise a 400 naming the field.

    `label` is the field as the user sees it, capitalized for the start of a sentence
    ("The date received"). `earliest` overrides the shared floor for fields with a tighter
    one — a payment before 2000 is absurd where a date of birth is not. The `*_hint`
    strings are appended to the directional message to say what to do instead.
    """
    if value is None:
        return None

    # Phrased so `label` always leads the sentence: it arrives already capitalized and may be
    # a full field name from the stage catalog ("Approval / Decision Date"), which reads wrong
    # forced to lower case and wrong again dropped mid-sentence.
    floor = earliest or EARLIEST_SANE_DATE
    if value < floor:
        raise HTTPException(
            status_code=400,
            detail=f"{label} can't be before {floor:%d %b %Y} — check the year.",
        )
    if value > latest_sane_date(today):
        raise HTTPException(
            status_code=400,
            detail=f"{label} is too far in the future — check the year.",
        )

    if direction == NOT_FUTURE and value > today + timedelta(days=GRACE_DAYS):
        raise HTTPException(status_code=400, detail=f"{label} can't be in the future.{future_hint}")
    if direction == NOT_PAST and value < today - timedelta(days=GRACE_DAYS):
        raise HTTPException(status_code=400, detail=f"{label} can't be in the past.{past_hint}")
    return value


def validate_for_org(
    *,
    db: Session,
    organization_id: int,
    value: Optional[date],
    label: str,
    direction: Optional[str] = None,
    earliest: Optional[date] = None,
    future_hint: str = "",
    past_hint: str = "",
) -> Optional[date]:
    """`validate` against the org's own calendar. One query, skipped when there's no date."""
    if value is None:
        return None
    return validate(
        value,
        label,
        today=enterprise_time.org_today(db, int(organization_id)),
        direction=direction,
        earliest=earliest,
        future_hint=future_hint,
        past_hint=past_hint,
    )
