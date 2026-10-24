"""
Email deliverability: know when Resend can't reach a user, and stop paying to try.

`resend.Emails.send` returning an id only means "accepted". When the recipient is on
Resend's suppression list (an old hard bounce or a spam complaint) the message is dropped
afterwards, reported only as an async event, and the app never heard about it: the user
saw "reset link sent" and nothing arrived, while the daily AI nudge kept paying Gemini to
write emails nobody could receive (2026-10: two accounts with every send since 2026-09-26
at last_event=suppressed).

A Svix-signed Resend webhook, POST /api/webhooks/resend/email-events (app/routers/
email_events.py), feeds a per-user flag on `users` (email_undeliverable_*, added by
app.schema_patch.ensure_user_email_deliverability_columns):

    email.bounced         permanent bounce              -> flag "bounced"
    email.complained      recipient marked it as spam   -> flag "complained"
    email.suppressed      Resend refused to send        -> flag "suppressed"
    suppression.added     address put on the list       -> flag (by origin)
    suppression.removed   address taken off the list    -> clear the flag

Env:
    RESEND_DELIVERABILITY_WEBHOOK_SECRET  the Svix signing secret ("whsec_...") of the Resend
                                          webhook subscribed to the events above. Its own
                                          secret, separate from RESEND_INBOUND_WEBHOOK_SECRET.

Policy:
  * Non-transactional sends (daily AI nudge, enterprise calendar digest, discount promos,
    the marketing-audience sync) skip flagged users. The daily nudge skips them in the
    candidate SQL, so no snapshot, R2 read or Gemini call runs for them.
  * Transactional sends (password reset, OTPs, verification) are still attempted: the flag
    can be stale, and a suppressed send costs nothing.
  * The admin console's account view shows the flag and reason and can clear it after
    support has removed the address from Resend's suppression list (a suppression.removed
    event clears it on its own).

The flag belongs to the user's CURRENT address: the one email-change path
(routers/auth confirm-university-change) clears it.

Svix retries can deliver an old event after a newer one. `email_undeliverable_at` therefore
holds the time of the LATEST bad event and every clear records `email_undeliverable_cleared_at`:
a flag event older than the last clear is ignored, and a removal older than the current flag
doesn't clear it.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Iterable, Mapping, Optional

from sqlalchemy import func

from app import models

logger = logging.getLogger(__name__)

REASON_BOUNCED = "bounced"
REASON_COMPLAINED = "complained"
REASON_SUPPRESSED = "suppressed"

REASON_LABELS = {
    REASON_BOUNCED: "Hard bounce",
    REASON_COMPLAINED: "Spam complaint",
    REASON_SUPPRESSED: "On Resend's suppression list",
}

_EMAIL_EVENT_REASONS = {
    "email.bounced": REASON_BOUNCED,
    "email.complained": REASON_COMPLAINED,
    "email.suppressed": REASON_SUPPRESSED,
}
# suppression.added `origin`: bounce | complaint | manual (dashboard/API).
_SUPPRESSION_ORIGIN_REASONS = {
    "bounce": REASON_BOUNCED,
    "complaint": REASON_COMPLAINED,
    "manual": REASON_SUPPRESSED,
}
# email.bounced is documented as permanent-only, but the payload carries the type; a soft
# bounce (mailbox full, greylisting) must not switch off someone's emails.
_TRANSIENT_BOUNCE_TYPES = {"transient", "temporary"}

_DETAIL_MAX_CHARS = 500
_ADDRESS_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


def webhook_secret() -> str:
    return (os.getenv("RESEND_DELIVERABILITY_WEBHOOK_SECRET") or "").strip()


def is_undeliverable(user) -> bool:
    return getattr(user, "email_undeliverable_at", None) is not None


def deliverable_clause():
    """SQL predicate: the user's email is NOT flagged undeliverable."""
    return models.User.email_undeliverable_at.is_(None)


def _naive_utc(value: Optional[datetime]) -> Optional[datetime]:
    """Columns are ALTER-added TIMESTAMP (naive UTC) in prod but declared timezone=True,
    so normalise both shapes before comparing."""
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _parse_timestamp(value) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return _naive_utc(datetime.fromisoformat(text))
    except ValueError:
        return None


def _addresses(value) -> list[str]:
    """Bare lowercase addresses from "a@b", "Name <a@b>" or a list of those."""
    found: list[str] = []
    if value is None:
        return found
    if isinstance(value, (list, tuple)):
        for item in value:
            found.extend(_addresses(item))
        return found
    for match in _ADDRESS_RE.findall(str(value)):
        address = match.lower()
        if address not in found:
            found.append(address)
    return found


def _clip(text: str) -> str:
    text = " ".join(str(text or "").split())
    return text[:_DETAIL_MAX_CHARS]


def _email_event_detail(event_type: str, data: Mapping) -> str:
    """Support-facing one-liner: what Resend said, plus which of our emails hit it."""
    def kind_and_message(kind: str, message) -> str:
        message = str(message or "").strip()
        return f"{kind}: {message}" if kind and message else (kind or message)

    parts: list[str] = []
    if event_type == "email.bounced":
        bounce = data.get("bounce") if isinstance(data.get("bounce"), Mapping) else {}
        kind = " / ".join(str(v) for v in (bounce.get("type"), bounce.get("subType")) if v)
        parts.append(kind_and_message(kind, bounce.get("message")))
    elif event_type == "email.suppressed":
        suppressed = data.get("suppressed") if isinstance(data.get("suppressed"), Mapping) else {}
        parts.append(kind_and_message(str(suppressed.get("type") or ""), suppressed.get("message")))
    elif event_type == "email.complained":
        parts.append("The recipient marked one of our emails as spam.")
    subject = str(data.get("subject") or "").strip()
    if subject:
        parts.append(f'Email: "{subject}"')
    return _clip(" · ".join(p for p in parts if p))


def _users_for_addresses(db, addresses: Iterable[str]) -> list:
    lowered = sorted({a.strip().lower() for a in addresses if a and a.strip()})
    if not lowered:
        return []
    return db.query(models.User).filter(func.lower(models.User.email).in_(lowered)).all()


def mark_undeliverable(user, *, reason: str, detail: str, at: datetime) -> bool:
    """Flag the user's address. Returns True when the stored state changed."""
    at = _naive_utc(at)
    cleared_at = _naive_utc(getattr(user, "email_undeliverable_cleared_at", None))
    if cleared_at is not None and at <= cleared_at:
        return False  # a retry of an event from before the last clear
    current = _naive_utc(getattr(user, "email_undeliverable_at", None))
    if current is not None and at < current:
        return False  # we already hold a newer event
    user.email_undeliverable_at = at
    user.email_undeliverable_reason = reason
    user.email_undeliverable_detail = detail or None
    return True


def clear_undeliverable(user, *, at: Optional[datetime] = None, by: str, force: bool = False) -> bool:
    """Clear the flag. `force` (an admin, an email change) clears whatever is stored; an
    unforced clear (suppression.removed) leaves a flag set by a NEWER event alone. Either
    way the clear time is recorded so late retries of older bad events stay ignored."""
    at = _naive_utc(at) or datetime.utcnow()
    current = _naive_utc(getattr(user, "email_undeliverable_at", None))
    if current is not None and at < current:
        if not force:
            return False
        at = current  # provider clock ahead of ours: still outrank the event we clear
    previous_clear = _naive_utc(getattr(user, "email_undeliverable_cleared_at", None))
    user.email_undeliverable_at = None
    user.email_undeliverable_reason = None
    user.email_undeliverable_detail = None
    user.email_undeliverable_cleared_at = max(at, previous_clear) if previous_clear else at
    user.email_undeliverable_cleared_by = (by or "")[:120] or None
    return current is not None


def apply_event(db, event: Mapping) -> dict:
    """Apply one verified Resend webhook event and commit. Returns a counts-only summary
    (no addresses or ids: it is the webhook's response body)."""
    event_type = str(event.get("type") or "").strip()
    data = event.get("data") if isinstance(event.get("data"), Mapping) else {}
    at = _parse_timestamp(event.get("created_at")) or datetime.utcnow()

    if event_type in _EMAIL_EVENT_REASONS:
        reason = _EMAIL_EVENT_REASONS[event_type]
        if event_type == "email.bounced":
            bounce = data.get("bounce") if isinstance(data.get("bounce"), Mapping) else {}
            if str(bounce.get("type") or "").strip().lower() in _TRANSIENT_BOUNCE_TYPES:
                return {"status": "ignored", "reason": "transient_bounce"}
        detail = _email_event_detail(event_type, data)
        users = _users_for_addresses(db, _addresses(data.get("to")))
        changed = [u.id for u in users if mark_undeliverable(u, reason=reason, detail=detail, at=at)]
        db.commit()
        for user_id in changed:
            logger.warning("email deliverability: user_id=%s flagged %s (%s)", user_id, reason, event_type)
        return {"status": "flagged", "event": event_type, "matched": len(users), "changed": len(changed)}

    if event_type == "suppression.added":
        origin = str(data.get("origin") or "").strip().lower()
        reason = _SUPPRESSION_ORIGIN_REASONS.get(origin, REASON_SUPPRESSED)
        detail = _clip(f"Added to Resend's suppression list (origin: {origin or 'unknown'}).")
        users = _users_for_addresses(db, _addresses(data.get("email")))
        changed = [u.id for u in users if mark_undeliverable(u, reason=reason, detail=detail, at=at)]
        db.commit()
        for user_id in changed:
            logger.warning("email deliverability: user_id=%s flagged %s (suppression.added)", user_id, reason)
        return {"status": "flagged", "event": event_type, "matched": len(users), "changed": len(changed)}

    if event_type == "suppression.removed":
        users = _users_for_addresses(db, _addresses(data.get("email")))
        changed = [u.id for u in users if clear_undeliverable(u, at=at, by="resend:suppression.removed")]
        db.commit()
        for user_id in changed:
            logger.info("email deliverability: user_id=%s cleared (suppression.removed)", user_id)
        return {"status": "cleared", "event": event_type, "matched": len(users), "changed": len(changed)}

    return {"status": "ignored", "event": event_type or None}


def _iso(value: Optional[datetime]) -> Optional[str]:
    value = _naive_utc(value)
    return value.replace(tzinfo=timezone.utc).isoformat() if value else None


def admin_status(user) -> dict:
    """The admin console's view of the flag (internal only, never shown to the student)."""
    reason = getattr(user, "email_undeliverable_reason", None)
    return {
        "undeliverable": is_undeliverable(user),
        "reason": reason,
        "reason_label": REASON_LABELS.get(reason or "", reason),
        "detail": getattr(user, "email_undeliverable_detail", None),
        "flagged_at": _iso(getattr(user, "email_undeliverable_at", None)),
        "cleared_at": _iso(getattr(user, "email_undeliverable_cleared_at", None)),
        "cleared_by": getattr(user, "email_undeliverable_cleared_by", None),
    }
