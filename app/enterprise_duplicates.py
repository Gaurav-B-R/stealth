"""Soft duplicate detection for enterprise clients.

Nothing in the schema stops an organization from holding the same student twice, and the
ways it happens are ordinary: a walk-in the Mumbai office already opened turns up on the
public lead form and is converted by someone in Pune; a counselor re-types a returning
applicant rather than searching for them. The cost is not cosmetic — each duplicate burns
a slot against the plan's active-client cap, splits the case history and the document
locker in two, and lets both files email the same student.

The check is deliberately SOFT. A hard unique constraint would be wrong here: two siblings
legitimately share a guardian's phone number, a family shares one email address, and a
consultancy occasionally does want the same person on two separate cases (a refused
application re-filed for a different country). So this module only answers "does this look
like someone you already have, and why" — the router turns that into a 409 the caller can
knowingly override, never into a refusal.

Matching is on four signals, each of which is strong enough to state as a fact to staff:

    email      normalized address, exact
    phone      last 9 digits of either the phone or the WhatsApp number, cross-matched
    passport   alphanumerics only, exact
    name_dob   same normalized name AND same date of birth

Name alone is NOT a signal. In this market a workspace holds several Rahul Sharmas, and a
warning that fires on every one of them is a warning staff learn to click through.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models

logger = logging.getLogger(__name__)

# How many trailing digits of a phone number make the match key. Nine is the sweet spot for
# the numbers this product actually sees: it survives a country code present on one record
# and absent on the other ("+91 98765 43210" vs "9876543210") and a leading trunk zero
# (UK "07911 123456" vs "+44 7911 123456"), while still carrying enough entropy that two
# unrelated students colliding is a curiosity rather than a daily event.
PHONE_KEY_DIGITS = 9
# Below this a value isn't a phone number — it's an extension, a placeholder or a typo.
PHONE_MIN_DIGITS = 7

# The fuzzy rules are matched in Python, which means loading candidate rows. Plan caps top
# out at 2,000 ACTIVE clients but closed cases stay forever, so a long-lived workspace can
# hold more than that; scan the most recent rows and stop. Email — the strongest signal and
# the only indexed one — is re-checked in SQL afterwards and is never subject to this bound.
SCAN_LIMIT = 5000

# Most-severe first. Two records sharing a passport number are the same human being;
# two sharing a phone number might be brother and sister.
REASON_WEIGHT = {"passport": 4, "email": 3, "name_dob": 2, "phone": 1}

REASON_LABELS = {
    "email": "Same email address",
    "phone": "Same phone / WhatsApp number",
    "passport": "Same passport number",
    "name_dob": "Same name and date of birth",
}

_NON_DIGITS = re.compile(r"\D+")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_WHITESPACE = re.compile(r"\s+")


def email_key(value) -> Optional[str]:
    """Casefolded address, and deliberately nothing cleverer.

    No plus-tag or gmail-dot folding: a match is shown to staff as a plain statement of
    fact ("Same email address"), and a normalization rule they can't see would read to
    them as the product being wrong rather than being clever.
    """
    text = str(value or "").strip().lower()
    return text if "@" in text and len(text) > 2 else None


def phone_key(value) -> Optional[str]:
    digits = _NON_DIGITS.sub("", str(value or ""))
    if len(digits) < PHONE_MIN_DIGITS:
        return None
    return digits[-PHONE_KEY_DIGITS:]


def name_key(value) -> Optional[str]:
    text = _WHITESPACE.sub(" ", str(value or "").strip().lower())
    return text or None


def passport_key(value) -> Optional[str]:
    text = _NON_ALNUM.sub("", str(value or "").strip().lower())
    return text or None


@dataclass(frozen=True)
class Fingerprint:
    """The comparable identity of one client record.

    Frozen and value-comparable on purpose: the edit path builds one before applying the
    payload and one after, and skips the whole check when they are equal — so saving a
    stage change on a client who happens to share a phone number with their sibling
    doesn't re-litigate a duplicate the org already accepted.
    """

    email: Optional[str] = None
    phones: frozenset = frozenset()
    name: Optional[str] = None
    dob: Optional[date] = None
    passport: Optional[str] = None

    @property
    def is_checkable(self) -> bool:
        """Whether there is anything here worth searching on. A record carrying only a
        name (no contact details, no DOB) can't be matched under any of the rules."""
        return bool(self.email or self.phones or self.passport or (self.name and self.dob))


def fingerprint(row: Any) -> Fingerprint:
    """Build the match keys from anything carrying the client column names — the pending
    ORM object on the create path, a narrow result row on the scan side."""
    phones = {
        phone_key(getattr(row, "phone", None)),
        phone_key(getattr(row, "whatsapp_number", None)),
    }
    # guardian_phone is deliberately absent. A shared parent number is the norm for
    # siblings applying through the same agency, so matching on it would flag the one
    # case staff most need to keep as two separate files.
    return Fingerprint(
        email=email_key(getattr(row, "email", None)),
        phones=frozenset(p for p in phones if p),
        name=name_key(getattr(row, "full_name", None)),
        dob=getattr(row, "date_of_birth", None),
        passport=passport_key(getattr(row, "passport_number", None)),
    )


def match_reasons(subject: Fingerprint, other: Fingerprint) -> list[str]:
    """Which rules fire between two fingerprints, strongest first."""
    reasons: list[str] = []
    if subject.passport and subject.passport == other.passport:
        reasons.append("passport")
    if subject.email and subject.email == other.email:
        reasons.append("email")
    if subject.name and subject.dob and subject.name == other.name and subject.dob == other.dob:
        reasons.append("name_dob")
    # Cross-matched: the phone one record files as the primary number is routinely the
    # WhatsApp number on the other.
    if subject.phones and (subject.phones & other.phones):
        reasons.append("phone")
    return reasons


@dataclass
class DuplicateMatch:
    row: Any
    reasons: list[str]

    @property
    def weight(self) -> int:
        return sum(REASON_WEIGHT.get(r, 0) for r in self.reasons)


def mask_phone(value) -> Optional[str]:
    """Last four digits only — enough for staff to recognize a number they just typed,
    not enough to read one off a record they aren't allowed to open."""
    digits = _NON_DIGITS.sub("", str(value or ""))
    if not digits:
        return None
    return "•" * max(2, len(digits) - 4) + digits[-4:]


def find_duplicates(
    db: Session,
    *,
    organization_id: int,
    subject: Any,
    exclude_client_id: Optional[int] = None,
    limit: int = 6,
) -> list[DuplicateMatch]:
    """Clients in this organization that look like the same person as `subject`.

    Searches the WHOLE organization, NOT the caller's record scope. The duplicate that
    matters most is the one another office already opened, and a check that could not see
    across offices would miss exactly the case it exists for. The caller owns the other
    half of that bargain: what it shows of an out-of-scope match must be redacted (see
    _serialize_duplicate in the enterprise router).

    `subject` is any object with the client column names, or a ready Fingerprint.
    """
    fp = subject if isinstance(subject, Fingerprint) else fingerprint(subject)
    if not fp.is_checkable:
        return []

    columns = [
        models.EnterpriseClient.id,
        models.EnterpriseClient.full_name,
        models.EnterpriseClient.email,
        models.EnterpriseClient.phone,
        models.EnterpriseClient.whatsapp_number,
        models.EnterpriseClient.date_of_birth,
        models.EnterpriseClient.status,
        models.EnterpriseClient.destination_country_code,
        models.EnterpriseClient.destination_country_name,
        models.EnterpriseClient.branch_id,
        models.EnterpriseClient.branch_name,
        models.EnterpriseClient.assigned_to_user_id,
        models.EnterpriseClient.created_by_user_id,
        models.EnterpriseClient.created_at,
    ]
    if fp.passport:
        # Passport numbers are encrypted at rest, so this column can only be matched by
        # decrypting every row loaded. Pay that cost only when the record in hand actually
        # has a number to match against — at intake, most don't.
        columns.append(models.EnterpriseClient.passport_number)

    base = db.query(*columns).filter(models.EnterpriseClient.organization_id == organization_id)
    if exclude_client_id:
        base = base.filter(models.EnterpriseClient.id != int(exclude_client_id))

    # no_autoflush because both callers hold an unsaved or dirty client at this point, and
    # a duplicate check must not be the thing that writes it.
    with db.no_autoflush:
        rows = base.order_by(models.EnterpriseClient.id.desc()).limit(SCAN_LIMIT).all()
        if len(rows) >= SCAN_LIMIT and fp.email:
            # Past the scan window the fuzzy rules go dark, but email is indexed and
            # exact — so the oldest file in a very large workspace is still findable by it.
            logger.info(
                "Duplicate scan hit its row cap (org_id=%s); falling back to an indexed "
                "email lookup for anything older.", organization_id,
            )
            seen = {r.id for r in rows}
            rows.extend(
                r for r in base.filter(func.lower(models.EnterpriseClient.email) == fp.email).all()
                if r.id not in seen
            )

    matches = [
        DuplicateMatch(row=row, reasons=reasons)
        for row in rows
        if (reasons := match_reasons(fp, fingerprint(row)))
    ]
    matches.sort(key=lambda m: (-m.weight, -int(m.row.id)))
    return matches[:limit]
