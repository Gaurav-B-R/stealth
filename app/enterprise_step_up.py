"""
Rilono Enterprise — step-up email confirmation for irreversible workspace actions.

A capability check answers "is this session allowed to do this?". It cannot answer "is this
session still the person it was issued to?" — and for the handful of actions nobody can undo
afterwards, that second question is the one that matters. Transferring ownership is the first
of them: it hands over refunds and the payout bank account, and only the *new* owner can hand
it back.

So those actions take a second proof: a 6-digit code emailed to the ACTOR's own inbox, which
they type back in. Three properties make it worth the extra step:

  * **Bound to the action.** `context_key` records exactly what was confirmed (which member is
    being made owner), so a code obtained for one transfer can never be replayed for another.
  * **Single-use, and only if the action lands.** `consumed_at` is written inside the caller's
    transaction — if the action rolls back, the code is still good, and if it commits, the code
    is spent.
  * **Self-replacing.** One live row per (user, organization, purpose): re-requesting a code
    invalidates the previous one, so an older code left in an inbox stops working.

The router owns the transaction, exactly as in `enterprise_team.py` — with one deliberate
exception documented on `verify_code_or_400`: a *failed* attempt commits its own counter, or
the attempt limit could be defeated by simply retrying.
"""

from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import models
from app.utils.token_security import hash_token, token_matches

# Purposes. Each one is a distinct scope: a code issued for one is never valid for another.
PURPOSE_OWNER_TRANSFER = "owner_transfer"

CODE_EXPIRES_MINUTES = int(os.getenv("ENTERPRISE_STEP_UP_OTP_EXPIRES_MINUTES", "10") or "10")
MAX_ATTEMPTS = int(os.getenv("ENTERPRISE_STEP_UP_OTP_MAX_ATTEMPTS", "5") or "5")

# Rows are tiny, but a workspace that transfers ownership twice a year shouldn't keep the
# 2023 attempt forever. Spent/expired rows are swept when the same person requests a new one.
_STALE_AFTER = timedelta(days=1)


def context_key_for_target_user(target_user_id) -> str:
    """The action fingerprint for a transfer: which member is being made owner."""
    return f"target:{int(target_user_id)}"


def _naive(value):
    """Postgres hands back tz-aware datetimes, SQLite naive ones; compare in one shape."""
    if value is None:
        return None
    return value.replace(tzinfo=None) if getattr(value, "tzinfo", None) else value


def _row_for(db: Session, *, user_id: int, organization_id: int, purpose: str):
    O = models.EnterpriseStepUpOtp
    return (
        db.query(O)
        .filter(
            O.user_id == int(user_id),
            O.organization_id == int(organization_id),
            O.purpose == str(purpose),
        )
        .first()
    )


def _purge_stale(db: Session, *, user_id: int) -> None:
    """Drop this person's spent or long-expired codes. Bounded, indexed, best-effort."""
    O = models.EnterpriseStepUpOtp
    cutoff = datetime.utcnow() - _STALE_AFTER
    try:
        (
            db.query(O)
            .filter(O.user_id == int(user_id), O.expires_at < cutoff)
            .delete(synchronize_session=False)
        )
    except Exception:  # pragma: no cover - housekeeping must never break the action
        pass


def issue_code(
    db: Session,
    *,
    user_id: int,
    organization_id: int,
    purpose: str,
    context_key: str | None = None,
) -> str:
    """Mint a code for this actor/workspace/purpose and return the PLAINTEXT for emailing.

    Only the hash is stored, so a database reader cannot confirm an action on someone's
    behalf. The caller commits — and must email the code *after* that commit succeeds, or a
    failed transaction would leave a code in an inbox that the server has no record of.
    """
    code = f"{secrets.randbelow(1_000_000):06d}"
    expires_at = datetime.utcnow() + timedelta(minutes=CODE_EXPIRES_MINUTES)
    _purge_stale(db, user_id=user_id)

    row = _row_for(db, user_id=user_id, organization_id=organization_id, purpose=purpose)
    if row:
        # Re-request: overwrite in place. The previous code dies here, attempts reset.
        row.code_hash = hash_token(code)
        row.context_key = context_key
        row.expires_at = expires_at
        row.attempts = 0
        row.consumed_at = None
    else:
        db.add(models.EnterpriseStepUpOtp(
            user_id=int(user_id),
            organization_id=int(organization_id),
            purpose=str(purpose),
            context_key=context_key,
            code_hash=hash_token(code),
            expires_at=expires_at,
            attempts=0,
        ))
    db.flush()
    return code


def verify_code_or_400(
    db: Session,
    *,
    user_id: int,
    organization_id: int,
    purpose: str,
    context_key: str | None,
    code: str | None,
) -> None:
    """Check the code and mark it spent, or raise 400 with copy the user can act on.

    Call this BEFORE the action makes any change. A wrong code commits its own attempt
    counter (otherwise the request's rollback would hand back an unlimited number of guesses),
    so anything already staged in the session at that point would be committed with it.

    On success `consumed_at` is set but NOT committed — it lands with the caller's
    transaction, so the code is spent if and only if the action it authorised actually
    happened.
    """
    code_clean = "".join(ch for ch in str(code or "") if ch.isdigit())
    if len(code_clean) != 6:
        raise HTTPException(status_code=400, detail="Enter the 6-digit code we emailed you.")

    row = _row_for(db, user_id=user_id, organization_id=organization_id, purpose=purpose)
    if not row:
        raise HTTPException(
            status_code=400,
            detail="We couldn't find that confirmation code — request a new one.",
        )
    if row.consumed_at is not None:
        raise HTTPException(
            status_code=400,
            detail="That code has already been used — request a new one.",
        )
    if _naive(row.expires_at) < datetime.utcnow():
        raise HTTPException(status_code=400, detail="That code has expired — request a new one.")
    if int(row.attempts or 0) >= MAX_ATTEMPTS:
        raise HTTPException(
            status_code=400,
            detail="Too many incorrect attempts — request a new code.",
        )
    # A code proves an inbox; `context_key` proves it was the inbox for THIS action. Both a
    # mismatch and a wrong code burn an attempt, so neither can be probed for free.
    if (row.context_key or None) != (context_key or None) or not token_matches(code_clean, row.code_hash):
        row.attempts = int(row.attempts or 0) + 1
        db.commit()
        raise HTTPException(
            status_code=400,
            detail="That code isn't right — check the email and try again.",
        )

    row.consumed_at = datetime.utcnow()
    db.flush()
