"""
Rilono Enterprise — team, offices, custom roles and the access log (business logic).

This module is the whole write side of the advanced access-control feature. The router
(`app/routers/enterprise.py`) owns thin endpoint wrappers: it resolves the caller's
membership, gates on a capability, calls in here, and commits. Everything that decides
*what is allowed* and *what the copy says* lives in this file.

The three-layer split matters:

  * `app/enterprise_access.py` — the capability registry, the role presets and the pure
    resolution engine. No writes, no HTTP. It answers "what can this member do?".
  * `app/enterprise_team.py`  — this file. Validation, mutation, audit and notification
    for offices (branches), custom roles and member access. Raises `HTTPException` with
    user-facing copy. Never commits (the router owns the transaction, so one endpoint is
    one transaction and a half-applied permission change is impossible).
  * `app/routers/enterprise.py` — HTTP shapes, gates, scoping of client queries.

Two structural rules run through everything below:

  1. **`organization_id` is always passed in by the caller**, resolved from the
     authenticated membership. Nothing here ever reads a tenant id from a path, body or
     header, and every id that arrives from a request (`branch_id`, `custom_role_id`,
     `move_members_to`) is re-resolved through an org-filtered lookup before use.
  2. **Counts and lookups for list endpoints are bulk-resolved.** `/team` is on the hot
     path (the client list page awaits it on every client open), so the helpers here are
     written as one query each and joined in Python. An implementation that queries per
     member is wrong, not merely slow — it turns a 40-person workspace into 200 queries.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from zoneinfo import available_timezones

from fastapi import HTTPException
from sqlalchemy import and_, false, func, or_
from sqlalchemy.orm import Session

from app import models
from app import enterprise_access as access
from app import enterprise_billing as billing
from app import enterprise_notifications as notif

logger = logging.getLogger(__name__)


# ===========================================================================
# CONSTANTS
# ===========================================================================

# One reassignment call may move at most this many explicitly-listed clients. The
# whole-branch move (no ids) is unbounded by design — merging two offices must not need
# 40 requests — but an id list comes from a checkbox selection, and a 50k-element list
# would be an accidental (or deliberate) way to hold a transaction open for minutes.
MAX_REASSIGN_CLIENTS = 500

# Bulk id lists are chunked into UPDATE statements of this size so a merge of a big
# office never builds a single multi-thousand-parameter IN clause.
_UPDATE_CHUNK = 500

# Human copy for the access-log rows. Only actions this module actually writes appear
# here; anything else is prettified from the raw action key rather than shown blank.
ACTION_LABELS: dict[str, str] = {
    "branch_created": "Office added",
    "branch_updated": "Office updated",
    "branch_default_changed": "Default office changed",
    "branch_archived": "Office archived",
    "branch_reactivated": "Office reactivated",
    "branch_clients_reassigned": "Clients moved between offices",
    "role_created": "Role created",
    "role_updated": "Role updated",
    "role_duplicated": "Role duplicated",
    "role_archived": "Role archived",
    "member_invited": "Member invited",
    "member_role_changed": "Role changed",
    "member_scope_changed": "Access scope changed",
    "member_capabilities_changed": "Permissions changed",
    "member_branches_changed": "Offices changed",
    "member_profile_updated": "Profile updated",
    "member_deactivated": "Member deactivated",
    "member_reactivated": "Member reactivated",
    "owner_transfer_code_sent": "Ownership transfer code emailed",
    "owner_transferred": "Ownership transferred",
}

# Free-text fields on a branch that are NOT charset-restricted display names. They are
# rendered as plain text and never used as an identifier, so they only need control
# characters stripped and a length cap. `timezone` is deliberately NOT here — it is the
# one office field that has to survive being fed to a date library, so it gets validated
# against the tz database by _clean_timezone below.
_BRANCH_TEXT_LIMITS: dict[str, int] = {
    "city": 80,
    "state_region": 80,
    "address_line": 200,
}

# An office time zone is an IANA name ("Asia/Kolkata"), checked against the tz database the
# runtime actually ships so a stored value is always something ZoneInfo() can load later.
# Matched case-insensitively and stored canonically, because the value is compared as a
# string. If a slim image carries no tz database at all, `_TZ_NAMES` comes back empty and
# validation degrades to length-capped free text — a host missing tzdata must not turn
# every real zone into a 422.
try:
    _TZ_NAMES: frozenset[str] = frozenset(available_timezones())
except Exception:  # pragma: no cover — no tz database on this host
    _TZ_NAMES = frozenset()
_TZ_CANONICAL: dict[str, str] = {name.lower(): name for name in _TZ_NAMES}

# Browsers disagree on which spelling of a renamed zone they offer: older ICU lists
# "Asia/Calcutta" and has no "Asia/Kolkata" at all, newer ICU is the other way round. Both
# are links to identical rules, so this is not a correctness fix — it stops the same office
# being stored two different ways depending on who filled the form, and stops an Indian
# consultancy being filed under "Calcutta". Mirrors TZ_MODERN in static/enterprise.js;
# deliberately partial, because a rename it misses is cosmetic rather than wrong.
_TZ_RENAMED: dict[str, str] = {
    "asia/calcutta": "Asia/Kolkata",
    "asia/rangoon": "Asia/Yangon",
    "asia/saigon": "Asia/Ho_Chi_Minh",
    "asia/katmandu": "Asia/Kathmandu",
    "asia/dacca": "Asia/Dhaka",
    "asia/thimbu": "Asia/Thimphu",
    "europe/kiev": "Europe/Kyiv",
    "america/godthab": "America/Nuuk",
    "america/buenos_aires": "America/Argentina/Buenos_Aires",
    "atlantic/faeroe": "Atlantic/Faroe",
    "pacific/ponape": "Pacific/Pohnpei",
    "pacific/truk": "Pacific/Chuuk",
}

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]+")
_WHITESPACE = re.compile(r"\s+")
_PHONE_DISALLOWED = re.compile(r"[^0-9+()\-. ]+")
# Deliberately loose: a real address check is a delivery attempt, not a regex. This only
# rejects input that cannot possibly be an address, so a typo'd office email does not
# become a silently-unreachable contact field.
_EMAIL_SHAPE = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")

MEMBER_STATUS_ACTIVE = "active"
MEMBER_STATUS_SUSPENDED = "suspended"


# ===========================================================================
# SMALL HELPERS
# ===========================================================================

def _utcnow() -> datetime:
    # Naive UTC everywhere, matching the rest of the enterprise modules.
    return datetime.utcnow()


def _clean_text(value, max_len: int) -> str | None:
    """Trim, de-control-character and cap a free-text field. Empty → None."""
    if value is None:
        return None
    text = _CONTROL_CHARS.sub(" ", str(value))
    text = _WHITESPACE.sub(" ", text).strip()
    if not text:
        return None
    return text[:max_len].strip() or None


def _clean_person_name(value, max_len: int = 120) -> str | None:
    """Clean a person's name.

    Deliberately NOT `access.sanitize_display_name`: that charset is ASCII-only because
    branch and role names end up in identifiers and pickers. A person's name is only ever
    displayed, and stripping accents out of "José" or "Sağlam" is a bug, not hygiene.
    """
    return _clean_text(value, max_len)


def _clean_phone(value, max_len: int = 32) -> str | None:
    if value is None:
        return None
    text = _PHONE_DISALLOWED.sub("", str(value))
    text = _WHITESPACE.sub(" ", text).strip()
    return (text[:max_len].strip() or None) if text else None


def _clean_email(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    if not _EMAIL_SHAPE.match(text) or len(text) > 200:
        raise HTTPException(status_code=422, detail="That doesn't look like an email address.")
    return text


def _clean_timezone(value) -> str | None:
    """Validate an office time zone. Returns the canonically-cased IANA name, or None.

    Rejects rather than silently keeps: a zone the runtime can't load is worse than no
    zone at all, because it reads as configured while behaving as unset.
    """
    text = _clean_text(value, 60)
    if text is None:
        return None
    if not _TZ_NAMES:
        return text
    # Only modernise when this runtime's tz database actually carries the new name — an
    # older image that only ships "Asia/Calcutta" must not start 422ing on it.
    renamed = _TZ_RENAMED.get(text.lower())
    if renamed and renamed in _TZ_NAMES:
        return renamed
    canonical = _TZ_CANONICAL.get(text.lower())
    if canonical is None:
        raise HTTPException(
            status_code=422,
            detail=f"“{text}” isn't a time zone we recognise. Pick one like “Asia/Kolkata”.",
        )
    return canonical


def _int_or_none(value) -> int | None:
    if value is None or value is False:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _int_list(values) -> list[int]:
    """Distinct positive ints from a request list, order preserved."""
    out: list[int] = []
    seen: set[int] = set()
    for raw in (values or []):
        parsed = _int_or_none(raw)
        if parsed is None or parsed in seen:
            continue
        seen.add(parsed)
        out.append(parsed)
    return out


def _join_names(names) -> str:
    items = [str(n).strip() for n in (names or []) if str(n or "").strip()]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return f"{', '.join(items[:-1])} and {items[-1]}"


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    word = singular if int(count) == 1 else (plural or f"{singular}s")
    return f"{int(count)} {word}"


def _display_name(user) -> str:
    return str(getattr(user, "full_name", None) or getattr(user, "email", None) or "This member").strip()


def _first_name(user) -> str:
    full = _display_name(user)
    return full.split()[0] if full.split() else full


def _role_key_of(membership) -> str:
    """The membership's role key, normalized (blank/unknown → legacy mirror → viewer)."""
    return access.normalize_role_key(
        getattr(membership, "role_key", None), getattr(membership, "role", None)
    )


def _ctx_scope(ctx) -> str:
    """The actor's scope. The owner is always org-scope, whatever the column says."""
    if ctx is None:
        return access.SCOPE_ASSIGNED
    if bool(getattr(ctx, "is_owner", False)):
        return access.SCOPE_ALL
    return access.normalize_scope(getattr(ctx, "scope_kind", None))


def _ctx_branch_ids(ctx) -> set[int]:
    return {int(b) for b in (getattr(ctx, "branch_ids", None) or ())}


def _ctx_has(ctx, cap: str) -> bool:
    if ctx is None:
        return False
    return bool(getattr(ctx, "is_owner", False)) or cap in (getattr(ctx, "capabilities", None) or frozenset())


def _normalize_scope_input(raw, *, field: str = "access level") -> str | None:
    """Coerce a submitted `data_scope` to a scope key, or None for "inherit".

    NULL/"" /"inherit" all mean *inherit from the role*, which is the whole reason the
    column is nullable — a stored default would make every role's own default scope dead
    code. Anything unrecognised is a 422 rather than a silent fall-back, because failing
    closed on a scope the caller believed they set is still the wrong scope.
    """
    if raw is None:
        return None
    text = str(raw).strip().lower()
    if not text or text in {"inherit", "default", "role"}:
        return None
    if text not in access.SCOPE_ORDER:
        raise HTTPException(
            status_code=422,
            detail=f"Pick a valid {field}: the entire workspace, their office, or only their own clients.",
        )
    return text


def scope_sentence(scope_kind, branch_names=(), *, self_view: bool = False) -> str:
    """Plain-English "what can they actually see", for the edit modal and My access."""
    kind = access.normalize_scope(scope_kind)
    if kind == access.SCOPE_ALL:
        return ("You can see every client in the workspace."
                if self_view else "Sees every client in the workspace.")
    if kind == access.SCOPE_BRANCH:
        where = _join_names(branch_names) or "their offices"
        return (f"You can only see clients in {where}."
                if self_view else f"Only sees clients in {where}.")
    return ("You can only see clients assigned to you, plus ones you created."
            if self_view else "Only sees clients assigned to them, plus ones they created.")


def action_label(action) -> str:
    key = str(action or "").strip()
    if key in ACTION_LABELS:
        return ACTION_LABELS[key]
    return key.replace("_", " ").strip().capitalize() or "Change"


# ===========================================================================
# LOOKUPS / COUNTS
#
# Every lookup is org-filtered. That single filter is what makes a tenant boundary out
# of an integer that arrived in a URL, so none of these has an "unscoped" variant.
# ===========================================================================

def get_org_branch_or_404(db: Session, organization_id: int, branch_id) -> models.EnterpriseBranch:
    resolved = _int_or_none(branch_id)
    if resolved is None:
        raise HTTPException(status_code=404, detail="That office no longer exists.")
    branch = (
        db.query(models.EnterpriseBranch)
        .filter(
            models.EnterpriseBranch.id == resolved,
            models.EnterpriseBranch.organization_id == int(organization_id),
        )
        .first()
    )
    if not branch:
        raise HTTPException(status_code=404, detail="That office no longer exists.")
    return branch


def get_org_role_or_404(db: Session, organization_id: int, role_id) -> models.EnterpriseRole:
    resolved = _int_or_none(role_id)
    if resolved is None:
        raise HTTPException(status_code=404, detail="That role no longer exists.")
    role = (
        db.query(models.EnterpriseRole)
        .filter(
            models.EnterpriseRole.id == resolved,
            models.EnterpriseRole.organization_id == int(organization_id),
        )
        .first()
    )
    if not role:
        raise HTTPException(status_code=404, detail="That role no longer exists.")
    return role


def get_org_membership_or_404(
    db: Session, organization_id: int, user_id
) -> models.EnterpriseOrganizationMember:
    """The membership row for a user in this org — active OR deactivated.

    Deactivated rows must resolve: reactivate, the access log and the deactivated
    members list all address people who are, by definition, not active. Callers that
    need an active member check `.is_active` themselves.
    """
    resolved = _int_or_none(user_id)
    if resolved is None:
        raise HTTPException(status_code=404, detail="That person isn't part of this workspace.")
    membership = (
        db.query(models.EnterpriseOrganizationMember)
        .filter(
            models.EnterpriseOrganizationMember.organization_id == int(organization_id),
            models.EnterpriseOrganizationMember.user_id == resolved,
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=404, detail="That person isn't part of this workspace.")
    return membership


def list_branches(
    db: Session, organization_id: int, *, include_archived: bool = False
) -> list[models.EnterpriseBranch]:
    query = db.query(models.EnterpriseBranch).filter(
        models.EnterpriseBranch.organization_id == int(organization_id)
    )
    if not include_archived:
        query = query.filter(models.EnterpriseBranch.is_active.is_(True))
    return (
        query.order_by(
            models.EnterpriseBranch.is_active.desc(),
            models.EnterpriseBranch.is_default.desc(),
            models.EnterpriseBranch.name.asc(),
            models.EnterpriseBranch.id.asc(),
        )
        .all()
    )


def default_branch(db: Session, organization_id: int) -> models.EnterpriseBranch | None:
    """The org's default office. Only an ACTIVE branch can be the default.

    Archiving the default is blocked, so this should never diverge — but reading the
    flag without the is_active filter would let one bad row route every new client into
    an archived office where nobody at branch scope can see them.
    """
    return (
        db.query(models.EnterpriseBranch)
        .filter(
            models.EnterpriseBranch.organization_id == int(organization_id),
            models.EnterpriseBranch.is_default.is_(True),
            models.EnterpriseBranch.is_active.is_(True),
        )
        .order_by(models.EnterpriseBranch.id.asc())
        .first()
    )


def ensure_default_branch(
    db: Session,
    organization_id: int,
    *,
    actor_user_id=None,
    company_name=None,
) -> models.EnterpriseBranch:
    """Guarantee the org has somewhere to file a client. Idempotent.

    Safe to call on any request path, which is the point: an org created before this
    feature shipped, or created by an onboarding flow that runs before the backfill, must
    still have a default office — otherwise `POST /clients` has no branch to write and
    every branch-scoped member sees an empty pipeline.

    Three cases, in order:
      1. A default already exists → return it.
      2. Offices exist but none is flagged default → promote the oldest. Minting a second
         "Head Office" next to the offices the workspace already named itself would be
         confusing and would consume one of their MAX_BRANCHES slots.
      3. No offices at all → create "Head Office".

    Flushes but does NOT commit, so it rides the caller's transaction like everything
    else here. If that transaction rolls back, the next call simply creates it again.
    """
    existing = default_branch(db, organization_id)
    if existing:
        return existing

    oldest = (
        db.query(models.EnterpriseBranch)
        .filter(
            models.EnterpriseBranch.organization_id == int(organization_id),
            models.EnterpriseBranch.is_active.is_(True),
        )
        .order_by(models.EnterpriseBranch.id.asc())
        .first()
    )
    if oldest:
        oldest.is_default = True
        db.flush()
        return oldest

    branch = models.EnterpriseBranch(
        organization_id=int(organization_id),
        name="Head Office",
        is_default=True,
        is_active=True,
        created_by_user_id=_int_or_none(actor_user_id),
    )
    db.add(branch)
    db.flush()
    # No audit row: this is an automatic system repair, not somebody changing access.
    # `company_name` is accepted so callers can log/label it without a second query.
    logger.info(
        "enterprise_team: created default office for org %s (%s)",
        organization_id, (company_name or "").strip() or "unnamed",
    )
    return branch


def branch_client_counts(db: Session, organization_id: int) -> dict[int, int]:
    """branch_id → client count. ONE group-by query."""
    rows = (
        db.query(models.EnterpriseClient.branch_id, func.count(models.EnterpriseClient.id))
        .filter(
            models.EnterpriseClient.organization_id == int(organization_id),
            models.EnterpriseClient.branch_id.isnot(None),
        )
        .group_by(models.EnterpriseClient.branch_id)
        .all()
    )
    return {int(bid): int(count or 0) for bid, count in rows if bid is not None}


def branch_member_counts(db: Session, organization_id: int) -> dict[int, int]:
    """branch_id → active member count. ONE query, folded in Python.

    A member counts toward an office through EITHER a link row OR their
    `primary_branch_id`. Both matter: link rows are the authoritative "works out of this
    office" list, but an org-scope admin typically has a primary office and no link rows
    at all, and the Offices tab must not report their office as empty. The outer join
    returns one row per (member, office) pair — bounded and tiny — so the de-duplication
    happens here rather than in a UNION the two supported databases render differently.
    """
    M = models.EnterpriseOrganizationMember
    MB = models.EnterpriseMemberBranch
    rows = (
        db.query(M.id, M.primary_branch_id, MB.branch_id)
        .outerjoin(MB, MB.member_id == M.id)
        .filter(M.organization_id == int(organization_id), M.is_active.is_(True))
        .all()
    )
    counts: dict[int, int] = {}
    seen: set[tuple[int, int]] = set()
    for member_id, primary_id, link_id in rows:
        for branch_id in (primary_id, link_id):
            if branch_id is None:
                continue
            pair = (int(member_id), int(branch_id))
            if pair in seen:
                continue
            seen.add(pair)
            counts[int(branch_id)] = counts.get(int(branch_id), 0) + 1
    return counts


def member_branch_ids(db: Session, organization_id: int) -> dict[int, list[int]]:
    """member_id → [branch_id] for ACTIVE offices only. ONE query.

    The join to `enterprise_branches` on `is_active` is not cosmetic. Archiving an office
    deletes its link rows (see `archive_branch`), but a row that slips through — a manual
    DB edit, a half-applied older release — would otherwise show up as an office in a
    member's scope that matches zero clients: a non-empty scope set that selects nothing,
    i.e. a silent, total data blackout with no error to explain it.
    """
    MB = models.EnterpriseMemberBranch
    B = models.EnterpriseBranch
    rows = (
        db.query(MB.member_id, MB.branch_id)
        .join(B, B.id == MB.branch_id)
        .filter(
            B.organization_id == int(organization_id),
            B.is_active.is_(True),
        )
        .order_by(MB.member_id.asc(), MB.branch_id.asc())
        .all()
    )
    out: dict[int, list[int]] = {}
    for member_id, branch_id in rows:
        out.setdefault(int(member_id), []).append(int(branch_id))
    return out


def role_member_counts(db: Session, organization_id: int) -> dict[int, int]:
    """custom_role_id → active member count. ONE group-by query."""
    M = models.EnterpriseOrganizationMember
    rows = (
        db.query(M.custom_role_id, func.count(M.id))
        .filter(
            M.organization_id == int(organization_id),
            M.is_active.is_(True),
            M.custom_role_id.isnot(None),
        )
        .group_by(M.custom_role_id)
        .all()
    )
    return {int(rid): int(count or 0) for rid, count in rows if rid is not None}


def assigned_client_counts(db: Session, organization_id: int) -> dict[int, int]:
    """user_id → clients assigned to them. ONE group-by query."""
    C = models.EnterpriseClient
    rows = (
        db.query(C.assigned_to_user_id, func.count(C.id))
        .filter(
            C.organization_id == int(organization_id),
            C.assigned_to_user_id.isnot(None),
        )
        .group_by(C.assigned_to_user_id)
        .all()
    )
    return {int(uid): int(count or 0) for uid, count in rows if uid is not None}


def _custom_role_names(db: Session, organization_id: int) -> dict[int, str]:
    """custom_role_id → name, including archived roles. ONE query.

    Archived roles are included on purpose: a member can still be sitting on one until
    somebody moves them, and their badge must show the role's real name, not "Custom".
    """
    rows = (
        db.query(models.EnterpriseRole.id, models.EnterpriseRole.name)
        .filter(models.EnterpriseRole.organization_id == int(organization_id))
        .all()
    )
    return {int(rid): str(name or "Custom role") for rid, name in rows}


def _branch_names(db: Session, organization_id: int) -> dict[int, str]:
    """branch_id → name, including archived offices. ONE query."""
    rows = (
        db.query(models.EnterpriseBranch.id, models.EnterpriseBranch.name)
        .filter(models.EnterpriseBranch.organization_id == int(organization_id))
        .all()
    )
    return {int(bid): str(name or "Office") for bid, name in rows}


def _active_member_branch_ids(db: Session, organization_id: int, member_id) -> list[int]:
    """Active offices linked to ONE member (write paths; /team uses the bulk helper)."""
    MB = models.EnterpriseMemberBranch
    B = models.EnterpriseBranch
    rows = (
        db.query(MB.branch_id)
        .join(B, B.id == MB.branch_id)
        .filter(
            MB.member_id == int(member_id),
            B.organization_id == int(organization_id),
            B.is_active.is_(True),
        )
        .order_by(MB.branch_id.asc())
        .all()
    )
    return [int(bid) for (bid,) in rows if bid is not None]


# ===========================================================================
# SERIALIZERS
# ===========================================================================

def serialize_branch(branch, *, member_count: int = 0, client_count: int = 0) -> dict:
    name = str(getattr(branch, "name", "") or "")
    city = str(getattr(branch, "city", "") or "").strip()
    # `label` is what pickers render. Two offices called "Head Office" in different
    # cities are indistinguishable in a <select> otherwise, and choosing the wrong one
    # moves a client out of everyone's branch scope.
    label = name
    if city and city.lower() not in name.lower():
        label = f"{name} ({city})"
    return {
        "id": branch.id,
        "name": name,
        "label": label,
        "code": getattr(branch, "code", None),
        "city": getattr(branch, "city", None),
        "state_region": getattr(branch, "state_region", None),
        "country_code": getattr(branch, "country_code", None),
        "address_line": getattr(branch, "address_line", None),
        "phone": getattr(branch, "phone", None),
        "email": getattr(branch, "email", None),
        "timezone": getattr(branch, "timezone", None),
        "is_default": bool(getattr(branch, "is_default", False)),
        "is_active": bool(getattr(branch, "is_active", True)),
        "archived_at": getattr(branch, "archived_at", None),
        "created_at": getattr(branch, "created_at", None),
        "member_count": int(member_count or 0),
        "client_count": int(client_count or 0),
    }


def serialize_role(role, *, member_count: int = 0) -> dict:
    # Capabilities go out through sanitize_capabilities so a key retired in a later
    # release can never reach the UI as a checkbox that does nothing.
    capabilities = sorted(access.sanitize_capabilities(getattr(role, "capabilities_json", None)))
    return {
        "id": role.id,
        "name": getattr(role, "name", None),
        "slug": getattr(role, "slug", None),
        "description": getattr(role, "description", None),
        "data_scope": getattr(role, "data_scope", None),
        "capabilities": capabilities,
        "based_on_role_key": getattr(role, "based_on_role_key", None),
        "is_active": bool(getattr(role, "is_active", True)),
        "member_count": int(member_count or 0),
        "created_at": getattr(role, "created_at", None),
    }


def serialize_member(
    membership,
    user,
    *,
    branch_ids,
    branch_names,
    primary_branch_name,
    role_label,
    assigned_client_count: int = 0,
    include_capabilities: bool = False,
    capabilities=None,
) -> dict:
    """A team member row. A backwards-compatible SUPERSET of the router's old shape.

    `role` stays the legacy mirror string (`admin`/`editor`/`viewer`). The deployed SPA
    reads it, and so do several server paths that predate this feature, so it is a
    maintained mirror — never dropped, never repurposed.

    `capabilities` (the full effective list) is opt-in: it is ~58 strings per member and
    `/team` is awaited on every client open, so it is only included for the single-member
    access payload. `capabilities=` lets that caller hand in the set the real resolution
    engine produced, which is the only way to include an active custom role's keys; the
    fallback below is preset+overrides only and is documented as such.
    """
    role_key = _role_key_of(membership)
    preset = access.preset_for(role_key)
    grants = sorted(access.sanitize_capabilities(getattr(membership, "capability_grants_json", None)))
    denies = sorted(access.sanitize_capabilities(getattr(membership, "capability_denies_json", None)))

    stored_scope = access.normalize_scope(getattr(membership, "data_scope", None), default="") or None
    if role_key == access.ROLE_OWNER or preset["scope_locked"]:
        # Owner and Admin are org-scope by definition; showing a stored override for them
        # would offer the UI a radio that the engine ignores.
        resolved_scope = access.SCOPE_ALL
    else:
        resolved_scope = access.normalize_scope(
            stored_scope or preset["data_scope"], default=access.SCOPE_ASSIGNED
        )

    ids = [int(b) for b in (branch_ids or [])]
    names = [str(n) for n in (branch_names or [])]

    status = str(getattr(membership, "status", "") or "").strip().lower()
    if status not in (MEMBER_STATUS_ACTIVE, MEMBER_STATUS_SUSPENDED):
        status = MEMBER_STATUS_ACTIVE if bool(membership.is_active) else MEMBER_STATUS_SUSPENDED

    payload = {
        # --- existing keys: shape must not change -------------------------
        "user_id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "role": _legacy_role_mirror(membership),
        "is_active": bool(membership.is_active),
        "joined_at": getattr(membership, "created_at", None),
        "last_login_at": getattr(user, "last_login_at", None),
        # --- new -----------------------------------------------------------
        "member_id": membership.id,
        "role_key": role_key,
        "role_label": role_label or preset["label"],
        "custom_role_id": getattr(membership, "custom_role_id", None),
        "is_owner": role_key == access.ROLE_OWNER,
        "data_scope": resolved_scope,
        # The raw column: NULL means "inherit from the role". The edit modal needs to
        # know the difference between "explicitly set to assigned" and "inheriting".
        "data_scope_override": stored_scope,
        "scope_label": access.scope_label(resolved_scope, branch_count=len(ids)),
        "capability_grants": grants,
        "capability_denies": denies,
        "override_count": len(grants) + len(denies),
        "primary_branch_id": getattr(membership, "primary_branch_id", None),
        "primary_branch_name": primary_branch_name,
        "branch_ids": ids,
        "branch_names": names,
        "job_title": getattr(membership, "job_title", None),
        "phone": getattr(membership, "phone", None),
        "status": status,
        "deactivated_at": getattr(membership, "deactivated_at", None),
        "last_active_at": getattr(membership, "last_active_at", None),
        "invited_at": getattr(membership, "invited_at", None),
        "invite_accepted_at": getattr(membership, "invite_accepted_at", None),
        "assigned_client_count": int(assigned_client_count or 0),
    }

    if include_capabilities:
        if capabilities is None:
            capabilities = access.effective_capabilities(
                role_key=role_key,
                custom_role_caps=None,     # needs a DB read — see docstring
                custom_role_active=False,
                grants=getattr(membership, "capability_grants_json", None),
                denies=getattr(membership, "capability_denies_json", None),
            )
        payload["capabilities"] = sorted(capabilities)

    return payload


def _legacy_role_mirror(membership) -> str:
    """The value of the legacy `role` column, coerced into the three legal values.

    Read, never computed: the stored mirror is maintained on every write path by
    `access.legacy_role_for`. Recomputing it here from capabilities would create a second
    producer, and the two would eventually disagree — which is exactly the divergence the
    single-producer rule exists to kill.
    """
    raw = str(getattr(membership, "role", "") or "").strip().lower()
    if raw in access.LEGACY_ROLES:
        return raw
    if raw in {"owner", "org_admin", "organization_admin"}:
        return "admin"
    if raw in {"edit", "write", "counsellor"}:
        return "editor"
    return "viewer"


def serialize_audit_entry(row) -> dict:
    detail = None
    raw = getattr(row, "detail_json", None)
    if raw:
        try:
            parsed = json.loads(raw)
            detail = parsed if isinstance(parsed, dict) else {"value": parsed}
        except (TypeError, ValueError):
            detail = None
    return {
        "id": row.id,
        "action": getattr(row, "action", None),
        "action_label": action_label(getattr(row, "action", None)),
        "actor_user_id": getattr(row, "actor_user_id", None),
        "actor_name": getattr(row, "actor_name", None),
        "target_user_id": getattr(row, "target_user_id", None),
        "target_name": getattr(row, "target_name", None),
        "target_role_id": getattr(row, "target_role_id", None),
        "target_branch_id": getattr(row, "target_branch_id", None),
        "summary": getattr(row, "summary", None),
        "detail": detail,
        "created_at": getattr(row, "created_at", None),
    }


def list_members(
    db: Session, organization_id: int, *, include_inactive: bool = False, ctx=None
) -> list[dict]:
    """Every member of the org, fully decorated. Six queries total, never per member.

    `ctx` is the caller's access context. Off org scope the per-member caseload sizes are
    suppressed: `team.view` is in every preset, so without this a counsellor restricted to their
    own clients could still read exactly how many clients each colleague in every other office is
    carrying. That is the same call already made in three other places (the AI's team-workload
    tool refuses below org scope, the credits breakdown drops `by_member`, and the office list
    zeroes per-office counts) — this keeps the answer consistent.
    """
    org_id = int(organization_id)
    M = models.EnterpriseOrganizationMember

    query = (
        db.query(M, models.User)
        .join(models.User, models.User.id == M.user_id)
        .filter(M.organization_id == org_id)
    )
    if not include_inactive:
        query = query.filter(M.is_active.is_(True))
    rows = query.order_by(M.created_at.asc(), M.id.asc()).all()

    links = member_branch_ids(db, org_id)
    names = _branch_names(db, org_id)
    custom_names = _custom_role_names(db, org_id)
    # Caseload sizes are an org-scope-only figure (see the docstring). Everyone else sees their
    # own count and zeroes elsewhere, rather than the column vanishing and shifting the table.
    show_caseloads = ctx is None or getattr(ctx, "is_org_scope", True)
    assigned = assigned_client_counts(db, org_id)
    if not show_caseloads:
        own = int(getattr(ctx, "user_id", 0) or 0)
        assigned = {own: assigned.get(own, 0)} if own else {}

    members: list[dict] = []
    for membership, user in rows:
        ids = list(links.get(int(membership.id), []))
        primary_id = _int_or_none(getattr(membership, "primary_branch_id", None))
        # A primary office with no link row is normal (an org-scope admin filed under
        # Delhi), and the resolution engine unions it into the scope set, so the payload
        # has to agree with the engine or the UI shows an office the member can see but
        # is not listed under.
        if primary_id and primary_id in names and primary_id not in ids:
            ids.append(primary_id)
        members.append(
            serialize_member(
                membership,
                user,
                branch_ids=ids,
                branch_names=[names[b] for b in ids if b in names],
                primary_branch_name=names.get(primary_id) if primary_id else None,
                role_label=_role_label_for(membership, custom_names),
                assigned_client_count=assigned.get(int(user.id), 0),
            )
        )

    # Owner first, then admins, then alphabetical: the two rows a manager looks for are
    # always at the top regardless of join date.
    def _sort_key(row: dict):
        rank = 0 if row["role_key"] == access.ROLE_OWNER else (
            1 if row["role_key"] == access.ROLE_ADMIN else 2
        )
        return (rank, str(row.get("full_name") or row.get("email") or "").lower())

    members.sort(key=_sort_key)
    return members


def _role_label_for(membership, custom_names: dict[int, str] | None = None) -> str:
    role_key = _role_key_of(membership)
    if role_key == access.ROLE_CUSTOM:
        role_id = _int_or_none(getattr(membership, "custom_role_id", None))
        if role_id and custom_names and role_id in custom_names:
            return custom_names[role_id]
    return access.role_label_for(role_key)


def _serialize_one_member(
    db: Session,
    organization,
    membership,
    user,
    *,
    include_capabilities: bool = False,
    capabilities=None,
) -> dict:
    """serialize_member for a single member on a write path (a few small queries)."""
    org_id = int(organization.id)
    names = _branch_names(db, org_id)
    ids = _active_member_branch_ids(db, org_id, membership.id)
    primary_id = _int_or_none(getattr(membership, "primary_branch_id", None))
    if primary_id and primary_id in names and primary_id not in ids:
        ids.append(primary_id)
    assigned = int(
        db.query(func.count(models.EnterpriseClient.id))
        .filter(
            models.EnterpriseClient.organization_id == org_id,
            models.EnterpriseClient.assigned_to_user_id == int(user.id),
        )
        .scalar() or 0
    )
    return serialize_member(
        membership,
        user,
        branch_ids=ids,
        branch_names=[names[b] for b in ids if b in names],
        primary_branch_name=names.get(primary_id) if primary_id else None,
        role_label=_role_label_for(membership, _custom_role_names(db, org_id)),
        assigned_client_count=assigned,
        include_capabilities=include_capabilities,
        capabilities=capabilities,
    )


# ===========================================================================
# VALIDATION
#
# These five functions are the security core of the feature. Each one exists because an
# operation that skipped it would let a member end up with more access than the person
# who granted it, or leave the workspace unmanageable.
# ===========================================================================

def assert_can_grant(actor_ctx, capabilities) -> None:
    """Nobody may hand out a capability they do not hold themselves.

    Two separate rules:

      * Owner-only keys (refunds, the payout bank account, ownership transfer) can never
        be granted by ANYONE, including the owner. The resolution engine strips them from
        every non-owner, so a checkbox that "granted" one would be a lie in the UI.
      * Everything else must satisfy `actor.has(cap)`. Without this, a delegated
        `roles.manage` holder is a privilege-escalation primitive: create a role with
        every capability, assign it to yourself, done.

    Offending keys are reported in REGISTRY order, not set order — the 403 names "the
    first offending capability", and a set iterates unpredictably, so the same request
    would otherwise blame a different capability each time it was retried.
    """
    caps = access.sanitize_capabilities(capabilities)
    if not caps:
        return

    owner_only = caps & access.OWNER_ONLY_CAPABILITIES
    if owner_only:
        raise HTTPException(
            status_code=422,
            detail="Refunds, payout details and ownership transfer can only be done by the workspace owner.",
        )

    if actor_ctx is None:
        # Fail closed. A missing context means we could not work out what the caller
        # holds, and "unknown" must never be treated as "everything".
        raise HTTPException(
            status_code=403,
            detail="We couldn't confirm your access level. Reload the page and try again.",
        )
    if bool(getattr(actor_ctx, "is_owner", False)):
        return

    held = getattr(actor_ctx, "capabilities", None) or frozenset()
    for entry in access.ALL_CAPABILITIES:
        key = entry["key"]
        if key in caps and key not in held:
            raise HTTPException(
                status_code=403,
                detail=f'You can\'t grant "{entry["label"]}" because you don\'t have it yourself.',
            )


def assert_scope_allowed(actor_ctx, data_scope, branch_ids) -> None:
    """An actor may only hand out its own data scope or narrower.

    Clamped for EVERY actor, not just branch-scoped ones. The tempting shortcut — only
    check when the actor is branch-scoped — leaves an `assigned`-scope member with
    delegated `roles.manage` able to mint a second, workspace-wide identity (invite an
    account, give it `all` scope, log in as it). Scope is the record boundary; widening it
    is the same as reading records you were never granted.
    """
    actor_scope = _ctx_scope(actor_ctx)
    if actor_scope == access.SCOPE_ALL:
        return  # nothing is wider than the whole workspace

    if data_scope and access.scope_is_wider(data_scope, actor_scope):
        raise HTTPException(
            status_code=403,
            detail="You can only give someone the same level of access you have, or narrower.",
        )

    requested = {int(b) for b in (branch_ids or set())}
    if requested and not requested.issubset(_ctx_branch_ids(actor_ctx)):
        # Covers the assigned-scope actor too: their office set is empty, so any office
        # they try to hand out is an office they cannot see.
        raise HTTPException(
            status_code=403,
            detail="You can only give someone access to the offices you can see yourself.",
        )


def assert_not_self(actor_ctx, target_membership, what: str) -> None:
    """Block self-service on the destructive half of team management.

    A member may not change their own role, scope, offices, grants or denies — not even
    to narrow them, because "narrow" is unverifiable in one step (drop `roles.manage`,
    keep a grant that restores it) and because an admin who accidentally removes their
    own access locks the workspace. Deactivating yourself has the same effect.
    """
    if actor_ctx is None or target_membership is None:
        return
    actor_user_id = _int_or_none(getattr(actor_ctx, "user_id", None))
    target_user_id = _int_or_none(getattr(target_membership, "user_id", None))
    if actor_user_id and target_user_id and actor_user_id == target_user_id:
        raise HTTPException(
            status_code=400,
            detail=f"You can't {what} your own account. Ask another admin.",
        )


def assert_owner_protected(db: Session, organization_id, target_membership, *, action: str) -> None:
    """The workspace owner is immovable except through transfer-ownership.

    Every org has exactly one active owner and the owner holds every capability by
    definition, so an edit here is either a no-op or the start of an unrecoverable
    workspace (nobody left who can set a payout account or accept a DPA).
    """
    if target_membership is None:
        return
    if _role_key_of(target_membership) == access.ROLE_OWNER:
        logger.info(
            "enterprise_team: blocked '%s' against the owner of org %s", action, organization_id
        )
        raise HTTPException(
            status_code=400,
            detail="Transfer ownership to someone else before changing the workspace owner.",
        )


def assert_admin_remains(
    db: Session,
    organization_id,
    target_membership,
    *,
    next_role_key=None,
    deactivating: bool = False,
) -> None:
    """A workspace must always have at least one member who can administer it.

    Computed on `role_key in {owner, admin}` — the same definition `legacy_role_for` uses
    for the `role == "admin"` mirror, so this invariant and the older
    `_active_admin_count() >= 1` guard can never disagree. Rows written before this
    feature shipped may still have a blank `role_key`, so their legacy mirror counts too.
    """
    if target_membership is None:
        return
    current_key = _role_key_of(target_membership)
    if current_key not in (access.ROLE_OWNER, access.ROLE_ADMIN):
        return
    if not bool(getattr(target_membership, "is_active", False)):
        return
    if not deactivating:
        if next_role_key is None:
            return
        if access.normalize_role_key(next_role_key) in (access.ROLE_OWNER, access.ROLE_ADMIN):
            return

    M = models.EnterpriseOrganizationMember
    remaining = int(
        db.query(func.count(M.id))
        .filter(
            M.organization_id == int(organization_id),
            M.is_active.is_(True),
            M.id != int(target_membership.id),
            or_(
                M.role_key.in_((access.ROLE_OWNER, access.ROLE_ADMIN)),
                and_(
                    or_(M.role_key.is_(None), M.role_key == ""),
                    M.role == "admin",
                ),
            ),
        )
        .scalar() or 0
    )
    if remaining < 1:
        raise HTTPException(status_code=400, detail="Your workspace needs at least one admin.")


# ---------------------------------------------------------------------------
# Notification wrappers — a notification must never fail the operation
# ---------------------------------------------------------------------------

def _notify_user_safe(db: Session, organization_id: int, recipient_user_id, **kwargs) -> None:
    recipient = _int_or_none(recipient_user_id)
    if not recipient:
        return
    try:
        notif.notify_user(db, int(organization_id), recipient, commit=False, **kwargs)
    except Exception:
        logger.exception(
            "enterprise_team: notify_user failed (org=%s, recipient=%s)",
            organization_id, recipient,
        )


def _notify_org_safe(db: Session, organization_id: int, **kwargs) -> None:
    try:
        notif.notify_org(db, int(organization_id), commit=False, **kwargs)
    except TypeError:
        # `recipient_capability` is newer than some deployed copies of the notifications
        # module; fall back to a plain fan-out rather than losing the notification.
        kwargs.pop("recipient_capability", None)
        try:
            notif.notify_org(db, int(organization_id), commit=False, **kwargs)
        except Exception:
            logger.exception("enterprise_team: notify_org fallback failed (org=%s)", organization_id)
    except Exception:
        logger.exception("enterprise_team: notify_org failed (org=%s)", organization_id)


# ===========================================================================
# BRANCH (OFFICE) OPERATIONS
#
# None of these commits. The router wraps one endpoint in one transaction, so an archive
# that moves 300 clients and then fails cannot leave half of them in a dead office.
# ===========================================================================

def _branch_name_or_422(raw) -> str:
    name = access.sanitize_display_name(raw, max_len=access.BRANCH_NAME_MAX_LEN)
    if len(name) < access.BRANCH_NAME_MIN_LEN:
        raise HTTPException(status_code=422, detail="Give the office a name of at least 2 characters.")
    return name


def _assert_branch_name_free(
    db: Session, organization_id: int, name: str, *, exclude_id=None, active_only: bool = False
) -> None:
    """Case-insensitive uniqueness on `lower(trim(name))`, INCLUDING archived offices.

    Enforced here rather than as a DB unique index on purpose. A unique index over a
    case-sensitive column cannot express "case-insensitive", and combined with
    archive-retention (we never hard-delete an office, because its clients' history
    references it) it turns a normal user mistake — re-adding an office they archived
    last year — into an unhandled IntegrityError 500. Doing it in code lets us answer
    with the one message that actually helps: reactivate it instead.

    The row count is bounded by MAX_BRANCHES, so comparing in Python also sidesteps
    per-dialect `lower()`/collation differences between SQLite and Postgres.
    """
    target = name.strip().lower()
    rows = (
        db.query(models.EnterpriseBranch.id, models.EnterpriseBranch.name, models.EnterpriseBranch.is_active)
        .filter(models.EnterpriseBranch.organization_id == int(organization_id))
        .all()
    )
    for row_id, row_name, is_active in rows:
        if exclude_id is not None and int(row_id) == int(exclude_id):
            continue
        if str(row_name or "").strip().lower() != target:
            continue
        if bool(is_active):
            raise HTTPException(
                status_code=409, detail=f'You already have an office called "{row_name}".'
            )
        if not active_only:
            raise HTTPException(
                status_code=409,
                detail="An archived office already uses that name — reactivate it instead.",
            )


def _active_branch_count(db: Session, organization_id: int) -> int:
    return int(
        db.query(func.count(models.EnterpriseBranch.id))
        .filter(
            models.EnterpriseBranch.organization_id == int(organization_id),
            models.EnterpriseBranch.is_active.is_(True),
        )
        .scalar() or 0
    )


def _apply_branch_fields(branch, data: dict) -> dict:
    """Write the optional office fields present in `data`. Returns {field: new_value}."""
    changed: dict[str, object] = {}

    def _set(field: str, value):
        if getattr(branch, field, None) != value:
            setattr(branch, field, value)
            changed[field] = value

    if "code" in data:
        # Office codes end up in exports and search; same charset rules as the name.
        code = access.sanitize_display_name(data.get("code"), max_len=12) or None
        _set("code", code)
    for field, limit in _BRANCH_TEXT_LIMITS.items():
        if field in data:
            _set(field, _clean_text(data.get(field), limit))
    if "timezone" in data:
        _set("timezone", _clean_timezone(data.get("timezone")))
    if "country_code" in data:
        raw = str(data.get("country_code") or "").strip().upper()
        _set("country_code", (raw[:2] or None))
    if "phone" in data:
        _set("phone", _clean_phone(data.get("phone")))
    if "email" in data:
        _set("email", _clean_email(data.get("email")))
    return changed


def create_branch(db: Session, *, organization, actor_user, actor_ctx, data: dict) -> models.EnterpriseBranch:
    org_id = int(organization.id)
    name = _branch_name_or_422((data or {}).get("name"))

    if _active_branch_count(db, org_id) >= access.MAX_BRANCHES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"You can have up to {access.MAX_BRANCHES} offices. "
                "Archive one you no longer use to add another."
            ),
        )
    _assert_branch_name_free(db, org_id, name)

    branch = models.EnterpriseBranch(
        organization_id=org_id,
        name=name,
        is_active=True,
        # The very first office becomes the default, so a workspace always has somewhere
        # to file a client without an extra "set default" step nobody would think to do.
        is_default=(_active_branch_count(db, org_id) == 0),
        created_by_user_id=_int_or_none(getattr(actor_user, "id", None)),
    )
    _apply_branch_fields(branch, data or {})
    db.add(branch)
    db.flush()

    access.audit(
        db,
        organization_id=org_id,
        actor=actor_user,
        action="branch_created",
        summary=f"Added the office “{name}”",
        target_branch_id=branch.id,
        after={"name": name, "city": branch.city, "is_default": bool(branch.is_default)},
    )
    _notify_org_safe(
        db, org_id,
        type="branch_created",
        title=f"New office added — {name}",
        body=f"{_display_name(actor_user)} added the {name} office to your workspace.",
        actor_user_id=_int_or_none(getattr(actor_user, "id", None)),
        reference_type="branch",
        reference_id=branch.id,
        recipient_capability="branches.view",
    )
    return branch


def update_branch(
    db: Session, *, organization, actor_user, actor_ctx, branch, data: dict
) -> models.EnterpriseBranch:
    org_id = int(organization.id)
    data = data or {}
    before = {
        "name": branch.name, "code": branch.code, "city": branch.city,
        "state_region": branch.state_region, "country_code": branch.country_code,
        "phone": branch.phone, "email": branch.email,
    }

    renamed_to = None
    if "name" in data:
        name = _branch_name_or_422(data.get("name"))
        if name != branch.name:
            _assert_branch_name_free(db, org_id, name, exclude_id=branch.id)
            branch.name = name
            renamed_to = name

    changed = _apply_branch_fields(branch, data)
    if renamed_to:
        changed["name"] = renamed_to
    if not changed:
        return branch

    if renamed_to:
        # `enterprise_clients.branch_name` is a SNAPSHOT, not a join: it backs the client
        # search clause and the client profile display. Leaving it stale after a rename
        # means searching the new office name returns nothing and the profile shows an
        # office that no longer exists under that name.
        (
            db.query(models.EnterpriseClient)
            .filter(
                models.EnterpriseClient.organization_id == org_id,
                models.EnterpriseClient.branch_id == branch.id,
            )
            .update({"branch_name": renamed_to}, synchronize_session="fetch")
        )

    db.flush()
    access.audit(
        db,
        organization_id=org_id,
        actor=actor_user,
        action="branch_updated",
        summary=f"Updated the office “{branch.name}”",
        target_branch_id=branch.id,
        before={k: v for k, v in before.items() if k in changed},
        after=changed,
    )
    return branch


def set_default_branch(db: Session, *, organization, actor_user, actor_ctx, branch) -> None:
    org_id = int(organization.id)
    if not bool(branch.is_active):
        raise HTTPException(
            status_code=400,
            detail="Reactivate this office before making it the default.",
        )
    if bool(branch.is_default):
        return

    previous = default_branch(db, org_id)
    (
        db.query(models.EnterpriseBranch)
        .filter(
            models.EnterpriseBranch.organization_id == org_id,
            models.EnterpriseBranch.id != branch.id,
            models.EnterpriseBranch.is_default.is_(True),
        )
        .update({"is_default": False}, synchronize_session="fetch")
    )
    branch.is_default = True
    db.flush()

    access.audit(
        db,
        organization_id=org_id,
        actor=actor_user,
        action="branch_default_changed",
        summary=f"Made “{branch.name}” the default office",
        target_branch_id=branch.id,
        before={"default_office": getattr(previous, "name", None)},
        after={"default_office": branch.name},
    )


def _branch_member_rows(db: Session, organization_id: int, branch_id: int):
    """Active members attached to one office, by link row OR primary pointer.

    Both signals count. Link rows are the authoritative "works out of this office" list,
    but an org-scope admin usually has only a `primary_branch_id`; missing them here would
    let an office be archived while people are still filed under it.
    """
    M = models.EnterpriseOrganizationMember
    MB = models.EnterpriseMemberBranch
    linked_ids = [
        int(row[0])
        for row in db.query(MB.member_id)
        .filter(
            MB.organization_id == int(organization_id),
            MB.branch_id == int(branch_id),
        )
        .all()
        if row[0] is not None
    ]
    clauses = [M.primary_branch_id == int(branch_id)]
    if linked_ids:
        clauses.append(M.id.in_(linked_ids))
    return (
        db.query(M, models.User)
        .join(models.User, models.User.id == M.user_id)
        .filter(
            M.organization_id == int(organization_id),
            M.is_active.is_(True),
            or_(*clauses),
        )
        .order_by(M.id.asc())
        .all()
    )


def archive_branch(
    db: Session,
    *,
    organization,
    actor_user,
    actor_ctx,
    branch,
    reassign_clients_to_branch_id=None,
    reassign_members_to_branch_id=None,
) -> dict:
    org_id = int(organization.id)
    if bool(branch.is_default):
        raise HTTPException(
            status_code=400, detail="Make another office the default before archiving this one."
        )
    if not bool(branch.is_active):
        return {"moved_clients": 0, "moved_members": 0}

    client_count = int(
        db.query(func.count(models.EnterpriseClient.id))
        .filter(
            models.EnterpriseClient.organization_id == org_id,
            models.EnterpriseClient.branch_id == branch.id,
        )
        .scalar() or 0
    )
    member_rows = _branch_member_rows(db, org_id, branch.id)
    member_count = len(member_rows)

    needs_client_target = client_count > 0 and reassign_clients_to_branch_id is None
    needs_member_target = member_count > 0 and reassign_members_to_branch_id is None
    if needs_client_target or needs_member_target:
        # A dict detail (not a string) so the UI can render the "move them to…" pickers
        # with real numbers instead of a dead-end error. The SPA reads ex.detail.message.
        parts = []
        if client_count:
            parts.append(_plural(client_count, "client"))
        if member_count:
            parts.append(_plural(member_count, "team member"))
        raise HTTPException(
            status_code=409,
            detail={
                "code": "branch_not_empty",
                "message": (
                    f"{branch.name} still has {_join_names(parts)}. "
                    "Choose where they should go before archiving it."
                ),
                "client_count": client_count,
                "member_count": member_count,
            },
        )

    client_target = None
    if reassign_clients_to_branch_id is not None and client_count:
        client_target = _archive_target_branch(db, org_id, branch, reassign_clients_to_branch_id)
    member_target = None
    if reassign_members_to_branch_id is not None and member_count:
        member_target = _archive_target_branch(db, org_id, branch, reassign_members_to_branch_id)

    moved_clients = 0
    if client_target is not None:
        moved_clients = (
            db.query(models.EnterpriseClient)
            .filter(
                models.EnterpriseClient.organization_id == org_id,
                models.EnterpriseClient.branch_id == branch.id,
            )
            .update(
                {"branch_id": client_target.id, "branch_name": client_target.name},
                synchronize_session="fetch",
            )
        ) or 0

    moved_members = 0
    if member_target is not None:
        existing_links = {
            int(row[0])
            for row in db.query(models.EnterpriseMemberBranch.member_id)
            .filter(
                models.EnterpriseMemberBranch.organization_id == org_id,
                models.EnterpriseMemberBranch.branch_id == member_target.id,
            )
            .all()
        }
        for membership, _user in member_rows:
            if int(membership.id) not in existing_links:
                db.add(models.EnterpriseMemberBranch(
                    organization_id=org_id,
                    member_id=int(membership.id),
                    branch_id=int(member_target.id),
                ))
                existing_links.add(int(membership.id))
            if _int_or_none(membership.primary_branch_id) == int(branch.id):
                membership.primary_branch_id = int(member_target.id)
            moved_members += 1
        # FLUSH BEFORE THE BULK STATEMENTS BELOW. The app's session runs with
        # autoflush=False, so the primary_branch_id reassignments above are still pending;
        # the "null out any primary still pointing here" UPDATE would otherwise match the
        # un-flushed DB rows and wipe the office we just moved these people to.
        db.flush()

    # Deleting this office's link rows is ESSENTIAL, not tidy-up. The resolution engine
    # filters a member's offices on `is_active`, so an archived office left in their link
    # rows produces a branch scope that is non-empty (it looks configured) but matches
    # zero clients — a silent, complete data blackout for that member.
    (
        db.query(models.EnterpriseMemberBranch)
        .filter(
            models.EnterpriseMemberBranch.organization_id == org_id,
            models.EnterpriseMemberBranch.branch_id == branch.id,
        )
        .delete(synchronize_session="fetch")
    )
    # Same reasoning for a primary pointer nobody asked to move: a pointer at a dead
    # office would be handed to the client form as a default that cannot be saved.
    (
        db.query(models.EnterpriseOrganizationMember)
        .filter(
            models.EnterpriseOrganizationMember.organization_id == org_id,
            models.EnterpriseOrganizationMember.primary_branch_id == branch.id,
        )
        .update({"primary_branch_id": None}, synchronize_session="fetch")
    )

    branch.is_active = False
    branch.is_default = False
    branch.archived_at = _utcnow()
    db.flush()

    access.audit(
        db,
        organization_id=org_id,
        actor=actor_user,
        action="branch_archived",
        summary=f"Archived the office “{branch.name}”",
        target_branch_id=branch.id,
        before={"is_active": True, "clients": client_count, "members": member_count},
        after={
            "is_active": False,
            "clients_moved_to": getattr(client_target, "name", None),
            "members_moved_to": getattr(member_target, "name", None),
        },
    )
    return {"moved_clients": int(moved_clients), "moved_members": int(moved_members)}


def _archive_target_branch(db: Session, org_id: int, branch, target_id) -> models.EnterpriseBranch:
    target = get_org_branch_or_404(db, org_id, target_id)
    if int(target.id) == int(branch.id):
        raise HTTPException(status_code=400, detail="Pick a different office to move them to.")
    if not bool(target.is_active):
        raise HTTPException(
            status_code=400, detail=f"“{target.name}” is archived — pick an active office."
        )
    return target


def reactivate_branch(
    db: Session, *, organization, actor_user, actor_ctx, branch
) -> models.EnterpriseBranch:
    org_id = int(organization.id)
    if bool(branch.is_active):
        return branch
    if _active_branch_count(db, org_id) >= access.MAX_BRANCHES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"You already have {access.MAX_BRANCHES} active offices. "
                "Archive one before reactivating this."
            ),
        )
    # Only ACTIVE names block a reactivation — the archived row we are reviving is itself
    # an archived name match, and blocking on that would make the office unrecoverable.
    _assert_branch_name_free(db, org_id, str(branch.name or ""), exclude_id=branch.id, active_only=True)

    branch.is_active = True
    branch.archived_at = None
    db.flush()

    access.audit(
        db,
        organization_id=org_id,
        actor=actor_user,
        action="branch_reactivated",
        summary=f"Reactivated the office “{branch.name}”",
        target_branch_id=branch.id,
        before={"is_active": False},
        # Link rows were deleted on archive, so nobody is assigned to it yet. Saying so
        # in the log is the difference between "reactivated" and "reactivated and staffed".
        after={"is_active": True, "members": 0},
    )
    return branch


def reassign_branch_clients(
    db: Session,
    *,
    organization,
    actor_user,
    actor_ctx,
    branch,
    target_branch,
    client_ids: list[int] | None,
    scope_filter=None,
) -> int:
    """Move clients from one office to another. Also the "merge two offices" operation."""
    org_id = int(organization.id)
    if int(target_branch.id) == int(branch.id):
        raise HTTPException(status_code=400, detail="Pick a different office to move them to.")
    if not bool(target_branch.is_active):
        raise HTTPException(
            status_code=400, detail=f"“{target_branch.name}” is archived — pick an active office."
        )

    ids = _int_list(client_ids)
    if ids and len(ids) > MAX_REASSIGN_CLIENTS:
        raise HTTPException(
            status_code=422,
            detail=f"You can move up to {MAX_REASSIGN_CLIENTS} clients at a time.",
        )

    # The org + source-branch filter is unconditional; `client_ids` can only ever narrow
    # it, so a tampered id list can never reach another workspace's clients.
    query = db.query(models.EnterpriseClient.id).filter(
        models.EnterpriseClient.organization_id == org_id,
        models.EnterpriseClient.branch_id == branch.id,
    )
    if ids:
        query = query.filter(models.EnterpriseClient.id.in_(ids))
    if scope_filter is not None:
        # The router passes `scope_client_query`, so a branch-scoped actor cannot move a
        # client it is not allowed to see (it would vanish from its own scope).
        query = scope_filter(query)

    target_ids = [int(row[0]) for row in query.all()]
    moved = 0
    for start in range(0, len(target_ids), _UPDATE_CHUNK):
        chunk = target_ids[start:start + _UPDATE_CHUNK]
        moved += (
            db.query(models.EnterpriseClient)
            .filter(
                models.EnterpriseClient.organization_id == org_id,
                models.EnterpriseClient.id.in_(chunk),
            )
            .update(
                {"branch_id": target_branch.id, "branch_name": target_branch.name},
                synchronize_session="fetch",
            )
        ) or 0
    db.flush()

    if moved:
        access.audit(
            db,
            organization_id=org_id,
            actor=actor_user,
            action="branch_clients_reassigned",
            summary=f"Moved {_plural(moved, 'client')} from “{branch.name}” to “{target_branch.name}”",
            target_branch_id=target_branch.id,
            before={"office": branch.name, "clients": moved},
            after={"office": target_branch.name},
        )
    return int(moved)


def branch_members(db: Session, organization_id, branch) -> list[dict]:
    """The Offices tab drill-down: who works out of this office."""
    org_id = int(organization_id)
    custom_names = _custom_role_names(db, org_id)
    out = []
    for membership, user in _branch_member_rows(db, org_id, branch.id):
        out.append({
            "user_id": user.id,
            "full_name": user.full_name,
            "email": user.email,
            "role_label": _role_label_for(membership, custom_names),
            "is_primary": _int_or_none(membership.primary_branch_id) == int(branch.id),
        })
    out.sort(key=lambda r: (not r["is_primary"], str(r["full_name"] or r["email"] or "").lower()))
    return out


# ===========================================================================
# CUSTOM ROLE OPERATIONS
# ===========================================================================

def list_roles_payload(db: Session, organization_id, *, include_archived: bool = False) -> list[dict]:
    query = db.query(models.EnterpriseRole).filter(
        models.EnterpriseRole.organization_id == int(organization_id)
    )
    if not include_archived:
        query = query.filter(models.EnterpriseRole.is_active.is_(True))
    roles = query.order_by(
        models.EnterpriseRole.is_active.desc(),
        models.EnterpriseRole.name.asc(),
        models.EnterpriseRole.id.asc(),
    ).all()
    counts = role_member_counts(db, int(organization_id))
    return [serialize_role(role, member_count=counts.get(int(role.id), 0)) for role in roles]


def _role_name_or_422(raw) -> str:
    name = access.sanitize_display_name(raw, max_len=access.ROLE_NAME_MAX_LEN)
    if len(name) < access.ROLE_NAME_MIN_LEN:
        raise HTTPException(status_code=422, detail="Give the role a name of at least 2 characters.")
    return name


def _role_slug_or_409(db: Session, organization_id: int, name: str, *, exclude_id=None) -> str:
    """Slug a role name and prove it is free, INCLUDING against archived roles.

    Archived roles keep their slug because audit rows and member history still point at
    them; reusing one would silently re-label old log entries with a different role's
    permissions.
    """
    slug = access.slugify_role_name(name)
    if slug in access.RESERVED_ROLE_SLUGS:
        raise HTTPException(
            status_code=409,
            detail=f'"{name}" is a reserved role name in Rilono — pick another.',
        )
    rows = (
        db.query(models.EnterpriseRole.id, models.EnterpriseRole.name,
                 models.EnterpriseRole.slug, models.EnterpriseRole.is_active)
        .filter(models.EnterpriseRole.organization_id == int(organization_id))
        .all()
    )
    target_name = name.strip().lower()
    for row_id, row_name, row_slug, is_active in rows:
        if exclude_id is not None and int(row_id) == int(exclude_id):
            continue
        if str(row_slug or "").strip().lower() != slug and str(row_name or "").strip().lower() != target_name:
            continue
        if bool(is_active):
            raise HTTPException(status_code=409, detail=f'You already have a role called "{row_name}".')
        raise HTTPException(
            status_code=409,
            detail=f'An archived role already uses the name "{row_name}" — rename this one.',
        )
    return slug


def _active_role_count(db: Session, organization_id: int) -> int:
    return int(
        db.query(func.count(models.EnterpriseRole.id))
        .filter(
            models.EnterpriseRole.organization_id == int(organization_id),
            models.EnterpriseRole.is_active.is_(True),
        )
        .scalar() or 0
    )


def _role_capabilities_or_422(actor_ctx, raw) -> frozenset[str]:
    """Sanitize → expand implications → escalation check.

    Expansion happens BEFORE the escalation check so a role that grants "Delete clients"
    is checked against the "Edit clients" it silently implies too.
    """
    caps = access.expand_implied(access.sanitize_capabilities(raw))
    assert_can_grant(actor_ctx, caps)
    return caps


def create_role(db: Session, *, organization, actor_user, actor_ctx, data: dict) -> models.EnterpriseRole:
    org_id = int(organization.id)
    data = data or {}

    if _active_role_count(db, org_id) >= access.MAX_CUSTOM_ROLES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"You can have up to {access.MAX_CUSTOM_ROLES} custom roles. "
                "Archive one you no longer use to add another."
            ),
        )

    name = _role_name_or_422(data.get("name"))
    slug = _role_slug_or_409(db, org_id, name)
    caps = _role_capabilities_or_422(actor_ctx, data.get("capabilities"))
    scope = _normalize_scope_input(data.get("data_scope"))
    assert_scope_allowed(actor_ctx, scope, None)

    based_on = str(data.get("based_on_role_key") or "").strip().lower() or None
    if based_on and based_on not in access.ROLE_PRESETS:
        based_on = None

    role = models.EnterpriseRole(
        organization_id=org_id,
        name=name,
        slug=slug,
        description=_clean_text(data.get("description"), 300),
        capabilities_json=access.dump_capabilities(caps),
        data_scope=scope,
        based_on_role_key=based_on,
        is_active=True,
        created_by_user_id=_int_or_none(getattr(actor_user, "id", None)),
    )
    db.add(role)
    db.flush()

    access.audit(
        db,
        organization_id=org_id,
        actor=actor_user,
        action="role_created",
        summary=f"Created the role “{name}” with {_plural(len(caps), 'permission')}",
        target_role_id=role.id,
        after={"name": name, "data_scope": scope, "capabilities": sorted(caps)},
    )
    return role


def update_role(db: Session, *, organization, actor_user, actor_ctx, role, data: dict) -> models.EnterpriseRole:
    org_id = int(organization.id)
    data = data or {}
    before = {
        "name": role.name,
        "data_scope": role.data_scope,
        "capabilities": sorted(access.sanitize_capabilities(role.capabilities_json)),
    }
    after: dict[str, object] = {}

    if "name" in data:
        name = _role_name_or_422(data.get("name"))
        if name != role.name:
            role.slug = _role_slug_or_409(db, org_id, name, exclude_id=role.id)
            role.name = name
            after["name"] = name
    if "description" in data:
        role.description = _clean_text(data.get("description"), 300)
        after["description"] = role.description
    if "based_on_role_key" in data:
        based_on = str(data.get("based_on_role_key") or "").strip().lower() or None
        role.based_on_role_key = based_on if based_on in access.ROLE_PRESETS else None
    if "capabilities" in data:
        caps = _role_capabilities_or_422(actor_ctx, data.get("capabilities"))
        role.capabilities_json = access.dump_capabilities(caps)
        after["capabilities"] = sorted(caps)
    if "data_scope" in data:
        scope = _normalize_scope_input(data.get("data_scope"))
        assert_scope_allowed(actor_ctx, scope, None)
        role.data_scope = scope
        after["data_scope"] = scope

    if not after:
        return role
    db.flush()

    # Editing a role changes what its members can do, so their legacy `role` mirror has
    # to be recomputed — a member left mirrored as "editor" after the role lost
    # `clients.edit` would keep passing the old `can_edit_data` checks that still read
    # that column.
    if "capabilities" in after:
        _resync_custom_role_mirrors(db, organization, role)

    access.audit(
        db,
        organization_id=org_id,
        actor=actor_user,
        action="role_updated",
        summary=f"Updated the role “{role.name}”",
        target_role_id=role.id,
        before={k: v for k, v in before.items() if k in after},
        after=after,
    )
    return role


def _resync_custom_role_mirrors(db: Session, organization, role) -> None:
    caps = access.sanitize_capabilities(role.capabilities_json)
    members = (
        db.query(models.EnterpriseOrganizationMember)
        .filter(
            models.EnterpriseOrganizationMember.organization_id == int(organization.id),
            models.EnterpriseOrganizationMember.custom_role_id == int(role.id),
        )
        .all()
    )
    for membership in members:
        if _role_key_of(membership) != access.ROLE_CUSTOM:
            continue
        effective = access.effective_capabilities(
            role_key=access.ROLE_CUSTOM,
            custom_role_caps=caps,
            custom_role_active=bool(role.is_active),
            grants=membership.capability_grants_json,
            denies=membership.capability_denies_json,
        )
        membership.role = access.legacy_role_for(access.ROLE_CUSTOM, effective)


def duplicate_role(
    db: Session, *, organization, actor_user, actor_ctx, role, name: str
) -> models.EnterpriseRole:
    """Copy a role (system preset or custom) into a new editable custom role.

    Routed through create_role so the copy gets the same escalation, scope-clamp, slug
    and quota checks as a hand-built one — duplicating a preset must not be a way to
    acquire capabilities the actor does not hold.
    """
    raw_caps = getattr(role, "capabilities_json", None)
    if raw_caps is None:
        # Tolerate a preset-shaped source (a dict from ROLE_PRESETS) as well as a row, so
        # "Duplicate to customise" works from the system-role cards too.
        raw_caps = getattr(role, "capabilities", None)
        if raw_caps is None and isinstance(role, dict):
            raw_caps = role.get("capabilities")
    source_caps = sorted(access.sanitize_capabilities(raw_caps))
    new_role = create_role(
        db,
        organization=organization,
        actor_user=actor_user,
        actor_ctx=actor_ctx,
        data={
            "name": name,
            "description": getattr(role, "description", None),
            "capabilities": source_caps,
            "data_scope": getattr(role, "data_scope", None),
            "based_on_role_key": getattr(role, "based_on_role_key", None),
        },
    )
    access.audit(
        db,
        organization_id=int(organization.id),
        actor=actor_user,
        action="role_duplicated",
        summary=f"Duplicated “{getattr(role, 'name', 'a role')}” as “{new_role.name}”",
        target_role_id=new_role.id,
        before={"name": getattr(role, "name", None)},
        after={"name": new_role.name},
    )
    return new_role


def archive_role(
    db: Session, *, organization, actor_user, actor_ctx, role, move_members_to=None
) -> dict:
    org_id = int(organization.id)
    members = (
        db.query(models.EnterpriseOrganizationMember)
        .filter(
            models.EnterpriseOrganizationMember.organization_id == org_id,
            models.EnterpriseOrganizationMember.custom_role_id == int(role.id),
            models.EnterpriseOrganizationMember.is_active.is_(True),
        )
        .all()
    )
    members = [m for m in members if _role_key_of(m) == access.ROLE_CUSTOM]
    member_count = len(members)

    if member_count and move_members_to is None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "role_in_use",
                "message": (
                    f"{_plural(member_count, 'member')} still {'uses' if member_count == 1 else 'use'} "
                    f"“{role.name}”. Choose the role they should move to."
                ),
                "member_count": member_count,
            },
        )

    moved = 0
    target_label = None
    if member_count:
        target_key, target_role_id = _parse_role_assignment(move_members_to)
        target_role = None
        if target_key == access.ROLE_CUSTOM:
            if not target_role_id:
                raise HTTPException(status_code=422, detail="Pick a role to move these members to.")
            target_role = get_org_role_or_404(db, org_id, target_role_id)
            if int(target_role.id) == int(role.id) or not bool(target_role.is_active):
                raise HTTPException(status_code=422, detail="Pick a different, active role to move members to.")
            target_caps = access.sanitize_capabilities(target_role.capabilities_json)
            target_label = target_role.name
        else:
            if target_key == access.ROLE_OWNER or not access.preset_for(target_key)["assignable"]:
                raise HTTPException(status_code=422, detail="Pick a role that can be assigned.")
            target_caps = access.preset_for(target_key)["capabilities"]
            target_label = access.role_label_for(target_key)
        # Moving members INTO a role grants them its capabilities, so the same escalation
        # rule applies as anywhere else. Owner-only keys are excluded because the engine
        # strips them from every non-owner anyway.
        assert_can_grant(actor_ctx, set(target_caps) - set(access.OWNER_ONLY_CAPABILITIES))

        for membership in members:
            membership.role_key = target_key
            membership.custom_role_id = int(target_role.id) if target_role is not None else None
            # A member's explicit data_scope is deliberately preserved. Resetting it to
            # "inherit" here could WIDEN their access if the destination role's default
            # scope is broader — an archive is a clean-up, never a promotion.
            effective = access.effective_capabilities(
                role_key=target_key,
                custom_role_caps=(target_role.capabilities_json if target_role is not None else None),
                custom_role_active=bool(target_role is not None and target_role.is_active),
                grants=membership.capability_grants_json,
                denies=membership.capability_denies_json,
            )
            membership.role = access.legacy_role_for(target_key, effective)
            moved += 1

    # Archive, never delete: audit rows and member history reference this role by id, and
    # a hard delete would either orphan them or cascade the history away.
    role.is_active = False
    db.flush()

    access.audit(
        db,
        organization_id=org_id,
        actor=actor_user,
        action="role_archived",
        summary=f"Archived the role “{role.name}”",
        target_role_id=role.id,
        before={"is_active": True, "members": member_count},
        after={"is_active": False, "members_moved_to": target_label},
    )
    return {"moved_members": int(moved)}


# ===========================================================================
# MEMBER ACCESS
# ===========================================================================

def _parse_role_assignment(raw) -> tuple[str, int | None]:
    """`access.parse_role_assignment` with its ValueError turned into a 422."""
    try:
        return access.parse_role_assignment(raw)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc) or "That role doesn't exist.") from None


def _capability_states(db: Session, organization_id: int, membership, effective) -> dict[str, str]:
    """Per-capability state for the tri-state permission matrix.

    "inherited" comes from the role, "granted" was added for this person, "blocked" was
    explicitly taken away, "off" is simply not held. Surfacing the difference is the
    point of the My-access tab: a member who was individually blocked from something
    should be able to see that it was a decision, not a bug.
    """
    role_key = _role_key_of(membership)
    grants = access.sanitize_capabilities(getattr(membership, "capability_grants_json", None))
    denies = access.sanitize_capabilities(getattr(membership, "capability_denies_json", None))

    role_caps = set(access.preset_for(role_key)["capabilities"])
    if role_key == access.ROLE_OWNER:
        role_caps = set(access.CAPABILITY_KEYS)
    elif role_key == access.ROLE_CUSTOM:
        # Same tenant filter and same `role_key == "custom"` gate as the engine.
        role_id = _int_or_none(getattr(membership, "custom_role_id", None))
        if role_id:
            row = (
                db.query(models.EnterpriseRole)
                .filter(
                    models.EnterpriseRole.id == role_id,
                    models.EnterpriseRole.organization_id == int(organization_id),
                    models.EnterpriseRole.is_active.is_(True),
                )
                .first()
            )
            if row is not None:
                role_caps |= set(access.sanitize_capabilities(row.capabilities_json))
    role_caps = set(access.expand_implied(role_caps)) | set(access.BASE_CAPABILITIES)
    added = set(access.expand_implied(grants)) if grants else set()

    states: dict[str, str] = {}
    for key in access.CAPABILITY_KEYS:
        if key in effective:
            # A denied BASE capability still resolves as held (base keys are undeniable
            # app chrome), so it reads as inherited rather than blocked — anything else
            # would show the member a permission they demonstrably have as missing.
            states[key] = "granted" if (key in added and key not in role_caps) else "inherited"
        elif key in denies:
            states[key] = "blocked"
        else:
            states[key] = "off"
    return states


def _member_role_block(db: Session, organization_id: int, membership) -> dict:
    role_key = _role_key_of(membership)
    preset = access.preset_for(role_key)
    block = {
        "role_key": role_key,
        "label": _role_label_for(membership, _custom_role_names(db, int(organization_id))),
        "description": preset["description"],
        "custom_role_id": _int_or_none(getattr(membership, "custom_role_id", None)),
        "is_custom": role_key == access.ROLE_CUSTOM,
        "is_system": preset["is_system"],
        "default_data_scope": preset["data_scope"],
        "scope_locked": preset["scope_locked"],
    }
    if block["is_custom"] and block["custom_role_id"]:
        row = (
            db.query(models.EnterpriseRole)
            .filter(
                models.EnterpriseRole.id == int(block["custom_role_id"]),
                models.EnterpriseRole.organization_id == int(organization_id),
            )
            .first()
        )
        if row is not None:
            block["description"] = row.description or preset["description"]
            block["default_data_scope"] = row.data_scope or preset["data_scope"]
            block["is_active"] = bool(row.is_active)
    return block


def _member_access_view(db: Session, organization, membership, user, ctx, *, self_view: bool) -> dict:
    org_id = int(organization.id)
    names = _branch_names(db, org_id)
    branch_ids = _active_member_branch_ids(db, org_id, membership.id)
    primary_id = _int_or_none(getattr(membership, "primary_branch_id", None))
    if primary_id and primary_id in names and primary_id not in branch_ids:
        branch_ids.append(primary_id)
    branch_names = [names[b] for b in branch_ids if b in names]

    member = _serialize_one_member(
        db, organization, membership, user,
        include_capabilities=True, capabilities=ctx.capabilities,
    )
    states = _capability_states(db, org_id, membership, ctx.capabilities)
    role_block = _member_role_block(db, org_id, membership)
    # `capability_states` is the source of truth, but the UI also renders three flat lists (the
    # role's own baseline, what was added on top, what was blocked) and a role description. Derive
    # them here rather than making every caller re-invert the map — and so the shape stays stable
    # if the state vocabulary ever grows.
    inherited = sorted(k for k, s in states.items() if s == "inherited")
    added = sorted(k for k, s in states.items() if s == "granted")
    blocked = sorted(k for k, s in states.items() if s == "blocked")
    return {
        "member": member,
        "capability_states": states,
        "capabilities": sorted(ctx.capabilities),
        "role": role_block,
        # Flat aliases the Team UI reads directly.
        "role_capabilities": inherited,
        "inherited": inherited,
        "added": added,
        "blocked": blocked,
        "role_description": role_block.get("description"),
        "branches": [
            serialize_branch(b) for b in list_branches(db, org_id, include_archived=False)
            if int(b.id) in set(branch_ids)
        ],
        "scope": {
            "kind": ctx.scope_kind,
            "label": ctx.scope_label,
            "sentence": scope_sentence(ctx.scope_kind, branch_names, self_view=self_view),
            "branch_ids": sorted(ctx.branch_ids),
            "branch_names": branch_names,
            "is_org_scope": bool(ctx.is_org_scope),
        },
        "counts": {
            "total": len(access.CAPABILITY_KEYS),
            "allowed": sum(1 for s in states.values() if s in ("inherited", "granted")),
            "granted": sum(1 for s in states.values() if s == "granted"),
            "blocked": sum(1 for s in states.values() if s == "blocked"),
        },
    }


def member_access_payload(db: Session, *, organization, membership, user) -> dict:
    """Everything the edit-access modal needs about one member."""
    ctx = access.resolve_access_context(db, membership, organization)
    return _member_access_view(db, organization, membership, user, ctx, self_view=False)


def my_access_payload(db: Session, *, organization, membership, user, ctx) -> dict:
    """The self-service "My access" tab — available to EVERY member.

    A person subject to access controls should be able to read them without asking an
    admin. Same shape as `member_access_payload` so the frontend reuses one renderer;
    the copy is second-person and the matrix is read-only.
    """
    resolved = ctx or access.resolve_access_context(db, membership, organization)
    payload = _member_access_view(db, organization, membership, user, resolved, self_view=True)
    payload["self"] = True
    payload["organization"] = {
        "id": organization.id,
        "company_name": getattr(organization, "company_name", None),
    }
    return payload


def _resolve_role_assignment(
    db: Session, *, organization, actor_ctx, data: dict
) -> tuple[str, int | None, frozenset[str], object]:
    """Validate a requested role change → (role_key, custom_role_id, caps, role_row)."""
    org_id = int(organization.id)
    raw_key = data.get("role_key")
    supplied_custom_id = _int_or_none(data.get("custom_role_id"))

    # Three accepted shapes: a role key ("counsellor"), the picker's "custom:<id>", or a
    # bare custom_role_id from an older client that only knew about custom roles.
    if raw_key:
        role_key, custom_role_id = _parse_role_assignment(raw_key)
        if role_key == access.ROLE_CUSTOM and custom_role_id is None:
            custom_role_id = supplied_custom_id
    elif supplied_custom_id:
        role_key, custom_role_id = access.ROLE_CUSTOM, supplied_custom_id
    else:
        raise HTTPException(status_code=422, detail="Pick a role for this member.")

    if role_key == access.ROLE_OWNER:
        raise HTTPException(
            status_code=422, detail="Use Transfer ownership to change the workspace owner."
        )

    role_row = None
    if role_key == access.ROLE_CUSTOM:
        if not custom_role_id:
            raise HTTPException(status_code=422, detail="Pick which custom role to give them.")
        role_row = get_org_role_or_404(db, org_id, custom_role_id)
        if not bool(role_row.is_active):
            raise HTTPException(
                status_code=422, detail=f'The role "{role_row.name}" is archived — pick another.'
            )
        caps = access.sanitize_capabilities(role_row.capabilities_json)
        custom_role_id = int(role_row.id)
    else:
        preset = access.preset_for(role_key)
        if not preset["assignable"]:
            raise HTTPException(status_code=422, detail="That role can't be assigned directly.")
        caps = preset["capabilities"]
        custom_role_id = None  # see the caller: this null-out is load-bearing

    # Owner-only keys are stripped from every non-owner by the engine, so assigning a
    # role that contains them is not an escalation — excluding them here keeps the check
    # about what the member will really receive.
    assert_can_grant(actor_ctx, set(access.expand_implied(caps)) - set(access.OWNER_ONLY_CAPABILITIES))
    return role_key, custom_role_id, access.expand_implied(caps), role_row


def _apply_access_fields(
    db: Session, *, organization, actor_ctx, membership, data: dict
) -> tuple[list[str], dict, dict]:
    """The shared PATCH core behind update_member_access and reactivate_member.

    Returns (changed dimensions, before, after). Writes nothing that has not passed the
    escalation, scope-clamp and admin-remains checks.
    """
    org_id = int(organization.id)
    data = data or {}
    changed: list[str] = []
    before: dict[str, object] = {}
    after: dict[str, object] = {}

    role_key = _role_key_of(membership)
    old_role_key = role_key
    custom_role_id = _int_or_none(getattr(membership, "custom_role_id", None))
    role_row = None
    role_caps = None

    # --- role -------------------------------------------------------------
    wants_role = ("role_key" in data and data.get("role_key")) or (
        "custom_role_id" in data and data.get("custom_role_id")
    )
    if wants_role:
        new_key, new_custom_id, role_caps, role_row = _resolve_role_assignment(
            db, organization=organization, actor_ctx=actor_ctx, data=data
        )
        if new_key != role_key or new_custom_id != custom_role_id:
            assert_admin_remains(db, org_id, membership, next_role_key=new_key)
            before["role"] = _role_label_for(membership, _custom_role_names(db, org_id))
            membership.role_key = new_key
            # Nulling custom_role_id on a NON-custom role is load-bearing: leaving the old
            # id behind means a future release (or a hand-written query) that unions the
            # custom role's capabilities on "the row exists" silently keeps every
            # permission the member was just demoted out of.
            membership.custom_role_id = new_custom_id
            role_key, custom_role_id = new_key, new_custom_id
            after["role"] = (
                role_row.name if role_row is not None else access.role_label_for(new_key)
            )
            changed.append("role")
            # A role change resets the member's scope override to "inherit" so they land
            # on the new role's own default — unless the caller set a scope in the same
            # request. Otherwise a counsellor promoted to branch manager silently keeps
            # the narrower scope the old role gave them.
            if "data_scope" not in data:
                if getattr(membership, "data_scope", None) is not None:
                    membership.data_scope = None
                    changed.append("scope")
                    after["data_scope"] = "inherit"

    # --- capability overrides ---------------------------------------------
    if "capability_grants" in data or "capability_denies" in data:
        old_grants = access.sanitize_capabilities(membership.capability_grants_json)
        old_denies = access.sanitize_capabilities(membership.capability_denies_json)
        grants = old_grants
        denies = old_denies
        if "capability_grants" in data:
            grants = access.sanitize_capabilities(data.get("capability_grants"))
            # Checked through the implication closure: granting "Delete clients" hands
            # over "Edit clients" too, and an actor without it must not be able to.
            assert_can_grant(actor_ctx, access.expand_implied(grants))
        if "capability_denies" in data:
            # Denies need no escalation check — narrowing somebody is always allowed.
            denies = access.sanitize_capabilities(data.get("capability_denies"))
        if grants != old_grants or denies != old_denies:
            before["capabilities"] = {
                "granted": sorted(old_grants), "blocked": sorted(old_denies),
            }
            membership.capability_grants_json = access.dump_capabilities(grants)
            membership.capability_denies_json = access.dump_capabilities(denies)
            after["capabilities"] = {"granted": sorted(grants), "blocked": sorted(denies)}
            changed.append("caps")

    # --- offices ----------------------------------------------------------
    existing_links = _member_link_rows(db, org_id, membership.id)
    branch_ids: set[int] | None = None
    if "branch_ids" in data:
        branch_ids = set()
        for raw in _int_list(data.get("branch_ids")):
            branch = get_org_branch_or_404(db, org_id, raw)   # tenant guard, every id
            if not bool(branch.is_active):
                raise HTTPException(
                    status_code=422,
                    detail=f'“{branch.name}” is archived — pick an active office.',
                )
            branch_ids.add(int(branch.id))

    # --- scope ------------------------------------------------------------
    scope_supplied = "data_scope" in data
    new_scope = _normalize_scope_input(data.get("data_scope")) if scope_supplied else \
        access.normalize_scope(getattr(membership, "data_scope", None), default="") or None

    # The clamp runs on the RESULTING scope, not just the submitted field. A branch-scoped
    # actor assigning a role whose default scope is "all" (Finance, say) would otherwise
    # slip a workspace-wide identity past a check that only looked at `data_scope`.
    resulting_scope = access.normalize_scope(
        new_scope
        or (role_row.data_scope if role_row is not None else None)
        or access.preset_for(role_key)["data_scope"],
        default=access.SCOPE_ASSIGNED,
    )
    if access.preset_for(role_key)["scope_locked"] or role_key == access.ROLE_OWNER:
        resulting_scope = access.SCOPE_ALL

    resulting_branches = branch_ids if branch_ids is not None else set(existing_links)
    assert_scope_allowed(
        actor_ctx,
        resulting_scope if (scope_supplied or "role_key" in data) else None,
        branch_ids,
    )
    if resulting_scope == access.SCOPE_BRANCH and not resulting_branches:
        # `branch` with no office resolves to `assigned` in the engine (fail closed), so
        # saving it would silently give them something other than what was picked.
        raise HTTPException(status_code=422, detail="Pick at least one office for this level of access.")

    if scope_supplied and new_scope != (access.normalize_scope(getattr(membership, "data_scope", None), default="") or None):
        before.setdefault("data_scope", getattr(membership, "data_scope", None) or "inherit")
        membership.data_scope = new_scope
        after["data_scope"] = new_scope or "inherit"
        if "scope" not in changed:
            changed.append("scope")

    if branch_ids is not None and branch_ids != set(existing_links):
        names = _branch_names(db, org_id)
        before["offices"] = [names.get(b, str(b)) for b in sorted(existing_links)]
        _rewrite_member_branches(db, org_id, membership, branch_ids, existing_links)
        after["offices"] = [names.get(b, str(b)) for b in sorted(branch_ids)]
        changed.append("branches")
        resulting_branches = branch_ids

    # --- primary office ---------------------------------------------------
    if "primary_branch_id" in data:
        primary = _int_or_none(data.get("primary_branch_id"))
        if primary is not None:
            branch = get_org_branch_or_404(db, org_id, primary)
            if not bool(branch.is_active):
                raise HTTPException(
                    status_code=422, detail=f'“{branch.name}” is archived — pick an active office.'
                )
            if resulting_scope == access.SCOPE_BRANCH and int(branch.id) not in resulting_branches:
                raise HTTPException(
                    status_code=422,
                    detail="Their main office has to be one of the offices you selected.",
                )
            primary = int(branch.id)
        if primary != _int_or_none(getattr(membership, "primary_branch_id", None)):
            membership.primary_branch_id = primary
            if "branches" not in changed:
                changed.append("branches")
    elif resulting_scope == access.SCOPE_BRANCH:
        current_primary = _int_or_none(getattr(membership, "primary_branch_id", None))
        if current_primary is not None and current_primary not in resulting_branches:
            # A primary pointing outside the office set is dropped by the engine anyway;
            # leaving it stored would hand the client form a default that cannot be saved.
            membership.primary_branch_id = sorted(resulting_branches)[0] if resulting_branches else None
            if "branches" not in changed:
                changed.append("branches")

    if old_role_key != role_key and "role" not in changed:
        changed.append("role")
    return changed, before, after


def _member_link_rows(db: Session, organization_id: int, member_id) -> list[int]:
    rows = (
        db.query(models.EnterpriseMemberBranch.branch_id)
        .filter(
            models.EnterpriseMemberBranch.organization_id == int(organization_id),
            models.EnterpriseMemberBranch.member_id == int(member_id),
        )
        .all()
    )
    return [int(bid) for (bid,) in rows if bid is not None]


def _rewrite_member_branches(
    db: Session, organization_id: int, membership, branch_ids: set[int], existing: list[int]
) -> None:
    """Make the link rows exactly `branch_ids` — delete the missing, insert the new.

    Keyed on `member_id`, never `user_id`: a member id already implies a tenant, and seat
    counting counts member rows, so office membership must never be able to add a seat.
    """
    org_id = int(organization_id)
    stale = [b for b in existing if b not in branch_ids]
    if stale:
        (
            db.query(models.EnterpriseMemberBranch)
            .filter(
                models.EnterpriseMemberBranch.organization_id == org_id,
                models.EnterpriseMemberBranch.member_id == int(membership.id),
                models.EnterpriseMemberBranch.branch_id.in_(stale),
            )
            .delete(synchronize_session="fetch")
        )
    for branch_id in sorted(branch_ids - set(existing)):
        db.add(models.EnterpriseMemberBranch(
            organization_id=org_id,
            member_id=int(membership.id),
            branch_id=int(branch_id),
        ))
    db.flush()


def _recompute_role_mirror(db: Session, organization, membership):
    """Re-resolve the member through the real engine and refresh the legacy mirror.

    Re-resolving (instead of recomputing the capability set here) keeps ONE producer of
    effective capabilities. A second implementation in this module would drift from
    `enterprise_access` on the first change to the deny/implication ordering.
    """
    db.flush()
    ctx = access.resolve_access_context(db, membership, organization)
    membership.role = access.legacy_role_for(ctx.role_key, ctx.capabilities)
    return ctx


def update_member_access(
    db: Session, *, organization, actor_user, actor_ctx, membership, data: dict
) -> dict:
    org_id = int(organization.id)
    data = data or {}

    # 1. A member may not change their own access at all — not even to narrow it.
    assert_not_self(actor_ctx, membership, "change the access level of")
    # 2. The owner's role and scope are transfer-only.
    assert_owner_protected(db, org_id, membership, action="change access")

    changed, before, after = _apply_access_fields(
        db, organization=organization, actor_ctx=actor_ctx, membership=membership, data=data
    )
    user = db.query(models.User).filter(models.User.id == membership.user_id).first()
    ctx = _recompute_role_mirror(db, organization, membership)

    if not changed:
        return {
            "member": _serialize_one_member(db, organization, membership, user),
            "changed": [],
        }

    target_name = _display_name(user)
    # One audit row PER DIMENSION that actually changed, each with its own before/after.
    # A single blob row is unreadable in the log and impossible to filter on ("show me
    # every scope change") — which is the only reason anyone opens an access log.
    audit_map = [
        ("role", "member_role_changed", f"Changed {target_name}'s role to {after.get('role', ctx.role_label)}"),
        ("scope", "member_scope_changed",
         f"Changed {target_name}'s data access to {access.scope_label(ctx.scope_kind, branch_count=len(ctx.branch_ids))}"),
        ("caps", "member_capabilities_changed", f"Changed {target_name}'s individual permissions"),
        ("branches", "member_branches_changed", f"Changed which offices {target_name} works in"),
    ]
    for dimension, action, summary in audit_map:
        if dimension not in changed:
            continue
        access.audit(
            db,
            organization_id=org_id,
            actor=actor_user,
            action=action,
            summary=summary,
            target_user=user,
            before=before,
            after=after,
        )

    actor_name = _display_name(actor_user)
    _notify_user_safe(
        db, org_id, membership.user_id,
        type="member_access_changed",
        title="Your access was updated",
        body=(
            f"{actor_name} updated your access. You're now {ctx.role_label}. "
            f"{scope_sentence(ctx.scope_kind, self_view=True)}"
        ),
        actor_user_id=_int_or_none(getattr(actor_user, "id", None)),
        reference_type="team",
        reference_id=_int_or_none(membership.user_id),
    )
    _notify_org_safe(
        db, org_id,
        type=("member_role_changed" if "role" in changed else "member_access_changed"),
        title=f"{target_name}'s access changed",
        body=f"{actor_name} set {target_name} to {ctx.role_label}.",
        actor_user_id=_int_or_none(getattr(actor_user, "id", None)),
        reference_type="team",
        reference_id=_int_or_none(membership.user_id),
        recipient_capability="team.manage",
    )

    return {
        "member": _serialize_one_member(
            db, organization, membership, user,
            include_capabilities=True, capabilities=ctx.capabilities,
        ),
        "changed": changed,
    }


def update_member_profile(
    db: Session, *, organization, actor_user, actor_ctx, membership, user, data: dict
) -> dict:
    """Name, job title and phone. The router decides whether this is self or team.manage."""
    org_id = int(organization.id)
    data = data or {}
    changed: list[str] = []
    before: dict[str, object] = {}
    after: dict[str, object] = {}

    if "full_name" in data:
        name = _clean_person_name(data.get("full_name"))
        if name and name != user.full_name:
            before["full_name"] = user.full_name
            user.full_name = name
            after["full_name"] = name
            changed.append("full_name")
    for field, limit in (("job_title", 80), ("phone", 32)):
        if field not in data:
            continue
        value = _clean_phone(data.get(field)) if field == "phone" else _clean_text(data.get(field), limit)
        if value != getattr(membership, field, None):
            before[field] = getattr(membership, field, None)
            setattr(membership, field, value)
            after[field] = value
            changed.append(field)

    if changed:
        db.flush()
        access.audit(
            db,
            organization_id=org_id,
            actor=actor_user,
            action="member_profile_updated",
            summary=f"Updated {_display_name(user)}'s profile",
            target_user=user,
            before=before,
            after=after,
        )
    return {
        "member": _serialize_one_member(db, organization, membership, user),
        "changed": changed,
    }


def member_offboard_counts(db: Session, organization_id, user_id) -> dict:
    """What this member still owns — the numbers behind the offboarding 409."""
    org_id = int(organization_id)
    uid = int(user_id)
    clients = int(
        db.query(func.count(models.EnterpriseClient.id))
        .filter(
            models.EnterpriseClient.organization_id == org_id,
            models.EnterpriseClient.assigned_to_user_id == uid,
        )
        .scalar() or 0
    )
    # "Open" means not ticked off, regardless of date: an overdue reminder nobody owns is
    # exactly the thing that gets missed after somebody leaves.
    events = int(
        db.query(func.count(models.EnterpriseCalendarEvent.id))
        .filter(
            models.EnterpriseCalendarEvent.organization_id == org_id,
            models.EnterpriseCalendarEvent.created_by_user_id == uid,
            models.EnterpriseCalendarEvent.is_done.is_(False),
        )
        .scalar() or 0
    )
    return {"assigned_client_count": clients, "open_event_count": events}


def _active_member_or_422(db: Session, organization_id: int, user_id) -> models.EnterpriseOrganizationMember:
    membership = get_org_membership_or_404(db, organization_id, user_id)
    if not bool(membership.is_active):
        raise HTTPException(status_code=422, detail="Pick someone who's still on the team.")
    return membership


def deactivate_member(
    db: Session,
    *,
    organization,
    actor_user,
    actor_ctx,
    membership,
    user,
    reason=None,
    reassign_clients_to_user_id=None,
    reassign_events_to_user_id=None,
) -> dict:
    org_id = int(organization.id)

    assert_not_self(actor_ctx, membership, "deactivate")
    assert_owner_protected(db, org_id, membership, action="deactivate")
    assert_admin_remains(db, org_id, membership, deactivating=True)
    if not bool(membership.is_active):
        # Already off. Idempotent so a double-click cannot re-stamp deactivated_at or
        # re-invalidate a session the person may since have legitimately regained.
        return {
            "member": _serialize_one_member(db, organization, membership, user),
            "moved_clients": 0,
            "moved_events": 0,
        }

    counts = member_offboard_counts(db, org_id, membership.user_id)
    client_count = counts["assigned_client_count"]
    event_count = counts["open_event_count"]
    needs_clients = client_count > 0 and reassign_clients_to_user_id is None
    needs_events = event_count > 0 and reassign_events_to_user_id is None
    if needs_clients or needs_events:
        # Same contract as archiving an office. Without this, offboarding silently orphans
        # a caseload: the clients stay assigned to somebody who can no longer log in, and
        # nobody on the team ever sees them in "my clients" again.
        parts = []
        if client_count:
            parts.append(_plural(client_count, "client"))
        if event_count:
            parts.append(_plural(event_count, "open reminder"))
        raise HTTPException(
            status_code=409,
            detail={
                "code": "member_has_records",
                "message": (
                    f"{_first_name(user)} still has {_join_names(parts)}. "
                    "Choose who takes them over."
                ),
                "assigned_client_count": client_count,
                "open_event_count": event_count,
            },
        )

    moved_clients = 0
    if reassign_clients_to_user_id is not None and client_count:
        target = _active_member_or_422(db, org_id, reassign_clients_to_user_id)
        moved_clients = (
            db.query(models.EnterpriseClient)
            .filter(
                models.EnterpriseClient.organization_id == org_id,
                models.EnterpriseClient.assigned_to_user_id == int(membership.user_id),
            )
            .update({"assigned_to_user_id": int(target.user_id)}, synchronize_session="fetch")
        ) or 0

    moved_events = 0
    if reassign_events_to_user_id is not None and event_count:
        target = _active_member_or_422(db, org_id, reassign_events_to_user_id)
        target_user = db.query(models.User).filter(models.User.id == target.user_id).first()
        moved_events = (
            db.query(models.EnterpriseCalendarEvent)
            .filter(
                models.EnterpriseCalendarEvent.organization_id == org_id,
                models.EnterpriseCalendarEvent.created_by_user_id == int(membership.user_id),
                models.EnterpriseCalendarEvent.is_done.is_(False),
            )
            .update(
                {
                    "created_by_user_id": int(target.user_id),
                    "created_by_name": _display_name(target_user) if target_user else None,
                },
                synchronize_session="fetch",
            )
        ) or 0

    # The member's private AI-assistant threads leave with them: they were never
    # org-visible, and an offboarded account must not leave a client-PII transcript
    # behind. Deliberately NOT restored on reactivate — the purge is the point.
    _ai_conv_ids = [
        cid for (cid,) in db.query(models.EnterpriseAiConversation.id).filter(
            models.EnterpriseAiConversation.organization_id == org_id,
            models.EnterpriseAiConversation.user_id == int(membership.user_id),
        ).all()
    ]
    if _ai_conv_ids:
        db.query(models.EnterpriseAiMessage).filter(
            models.EnterpriseAiMessage.conversation_id.in_(_ai_conv_ids)
        ).delete(synchronize_session=False)
        db.query(models.EnterpriseAiConversation).filter(
            models.EnterpriseAiConversation.id.in_(_ai_conv_ids)
        ).delete(synchronize_session=False)

    membership.is_active = False
    membership.status = MEMBER_STATUS_SUSPENDED
    membership.deactivated_at = _utcnow()
    membership.deactivated_by_user_id = _int_or_none(getattr(actor_user, "id", None))
    # Hard eviction: a suspended member holding a valid cookie would otherwise keep the
    # session they already have until it expires.
    user.session_invalidated_at = _utcnow()
    # NOT touched, deliberately: `user.is_enterprise_account` and `user.university` are
    # the B2C-separation signals. Clearing the flag would hand an enterprise-created
    # account access to the consumer app; clearing `university` would break a real
    # consumer who also works at a consultancy.
    db.flush()

    access.audit(
        db,
        organization_id=org_id,
        actor=actor_user,
        action="member_deactivated",
        summary=f"Deactivated {_display_name(user)}",
        target_user=user,
        before={"is_active": True, "clients": client_count, "open_reminders": event_count},
        after={
            "is_active": False,
            "reason": _clean_text(reason, 300),
            "clients_moved": int(moved_clients),
            "reminders_moved": int(moved_events),
        },
    )
    _notify_org_safe(
        db, org_id,
        type="member_removed",
        title=f"{_display_name(user)} was removed from the team",
        body=f"{_display_name(actor_user)} deactivated their access to this workspace.",
        actor_user_id=_int_or_none(getattr(actor_user, "id", None)),
        reference_type="team",
        reference_id=_int_or_none(membership.user_id),
        recipient_capability="team.manage",
    )
    return {
        "member": _serialize_one_member(db, organization, membership, user),
        "moved_clients": int(moved_clients),
        "moved_events": int(moved_events),
    }


def reactivate_member(
    db: Session, *, organization, actor_user, actor_ctx, membership, user, data: dict
) -> dict:
    org_id = int(organization.id)
    data = data or {}

    if not bool(membership.is_active):
        # Nothing else checks the seat limit on this path — reactivating is the one way to
        # add a seat without going through the invite endpoint, so a lapsed plan could
        # otherwise be refilled past its cap for free. Called BEFORE the flag flips, since
        # the counter counts active members.
        billing.enforce_seat_limit_or_402(db, org_id)
        membership.is_active = True
        membership.status = MEMBER_STATUS_ACTIVE
        membership.deactivated_at = None
        membership.deactivated_by_user_id = None

    changed, before, after = _apply_access_fields(
        db, organization=organization, actor_ctx=actor_ctx, membership=membership,
        data={k: v for k, v in data.items() if k in
              ("role_key", "custom_role_id", "data_scope", "branch_ids", "primary_branch_id")},
    )
    ctx = _recompute_role_mirror(db, organization, membership)

    access.audit(
        db,
        organization_id=org_id,
        actor=actor_user,
        action="member_reactivated",
        summary=f"Reactivated {_display_name(user)} as {ctx.role_label}",
        target_user=user,
        before={"is_active": False, **before},
        after={"is_active": True, "role": ctx.role_label, **after},
    )
    _notify_user_safe(
        db, org_id, membership.user_id,
        type="member_access_changed",
        title="Your workspace access was restored",
        body=f"{_display_name(actor_user)} reactivated your account. You're {ctx.role_label}.",
        actor_user_id=_int_or_none(getattr(actor_user, "id", None)),
        reference_type="team",
        reference_id=_int_or_none(membership.user_id),
    )
    return {
        "member": _serialize_one_member(
            db, organization, membership, user,
            include_capabilities=True, capabilities=ctx.capabilities,
        ),
        "changed": changed,
    }


def _current_owner_membership(db: Session, organization_id: int):
    """The org's owner row, active or not (the recovery path needs the inactive one)."""
    M = models.EnterpriseOrganizationMember
    return (
        db.query(M)
        .filter(M.organization_id == int(organization_id), M.role_key == access.ROLE_OWNER)
        .order_by(M.is_active.desc(), M.id.asc())
        .first()
    )


def assert_transfer_ownership_allowed(
    db: Session,
    *,
    organization,
    actor_ctx,
    target_membership,
    target_user,
    confirm_email: str,
):
    """Everything that must hold before ownership can move. Returns the current owner row.

    Run twice by design: once before the confirmation code is emailed — so a caller who could
    never finish the transfer can't make Rilono send a security email about it — and again
    inside `transfer_ownership()` minutes later, because the emailed code proves an inbox, not
    a permission, and permissions can be revoked in between.
    """
    org_id = int(organization.id)

    if str(confirm_email or "").strip().lower() != str(target_user.email or "").strip().lower():
        raise HTTPException(
            status_code=400, detail="That email doesn't match — type the exact address to confirm."
        )
    if not bool(target_membership.is_active):
        raise HTTPException(status_code=400, detail="That person isn't an active member of this workspace.")
    if _int_or_none(getattr(actor_ctx, "user_id", None)) == _int_or_none(target_membership.user_id):
        raise HTTPException(status_code=400, detail="That's your own account — pick another member.")

    current_owner = _current_owner_membership(db, org_id)
    # Authorisation is nominally the router's gate, but it is re-checked here because this
    # is the one operation that cannot be undone by anybody else. The recovery path — a
    # team.manage holder transferring away from an owner whose membership is inactive —
    # exists because a workspace whose founder left is otherwise permanently unable to
    # accept a new DPA, set a payout account or issue a refund.
    is_owner = bool(getattr(actor_ctx, "is_owner", False))
    owner_inactive = current_owner is None or not bool(current_owner.is_active)
    if not is_owner and not (_ctx_has(actor_ctx, "team.manage") and owner_inactive):
        raise HTTPException(
            status_code=403,
            detail="Only the workspace owner can transfer ownership.",
        )
    return current_owner


def transfer_ownership(
    db: Session,
    *,
    organization,
    actor_user,
    actor_ctx,
    target_membership,
    target_user,
    confirm_email: str,
) -> dict:
    org_id = int(organization.id)

    current_owner = assert_transfer_ownership_allowed(
        db,
        organization=organization,
        actor_ctx=actor_ctx,
        target_membership=target_membership,
        target_user=target_user,
        confirm_email=confirm_email,
    )
    is_owner = bool(getattr(actor_ctx, "is_owner", False))
    previous_owner_user_id = _int_or_none(getattr(current_owner, "user_id", None)) if current_owner else None

    # Demote every other owner row first, so "exactly one active owner per org" holds even
    # if a bad backfill left two behind.
    M = models.EnterpriseOrganizationMember
    others = (
        db.query(M)
        .filter(
            M.organization_id == org_id,
            M.role_key == access.ROLE_OWNER,
            M.id != int(target_membership.id),
        )
        .all()
    )
    for row in others:
        row.role_key = access.ROLE_ADMIN
        row.custom_role_id = None
        row.role = access.legacy_role_for(access.ROLE_ADMIN, ())

    target_membership.role_key = access.ROLE_OWNER
    target_membership.custom_role_id = None
    target_membership.data_scope = None
    target_membership.status = MEMBER_STATUS_ACTIVE
    target_membership.role = access.legacy_role_for(access.ROLE_OWNER, ())
    db.flush()

    access.audit(
        db,
        organization_id=org_id,
        actor=actor_user,
        action="owner_transferred",
        summary=f"Transferred workspace ownership to {_display_name(target_user)}",
        target_user=target_user,
        before={"owner": _display_name(actor_user) if is_owner else previous_owner_user_id},
        after={"owner": _display_name(target_user)},
    )
    _notify_user_safe(
        db, org_id, target_membership.user_id,
        type="ownership_transferred",
        title="You're now the workspace owner",
        body=f"{_display_name(actor_user)} transferred ownership of this workspace to you.",
        actor_user_id=_int_or_none(getattr(actor_user, "id", None)),
        reference_type="team",
        reference_id=_int_or_none(target_membership.user_id),
    )
    if previous_owner_user_id and previous_owner_user_id != _int_or_none(target_membership.user_id):
        _notify_user_safe(
            db, org_id, previous_owner_user_id,
            type="ownership_transferred",
            title="Workspace ownership was transferred",
            body=f"{_display_name(target_user)} is now the owner of this workspace. You remain an admin.",
            actor_user_id=_int_or_none(getattr(actor_user, "id", None)),
            reference_type="team",
            reference_id=_int_or_none(target_membership.user_id),
        )
    _notify_org_safe(
        db, org_id,
        type="ownership_transferred",
        title="Workspace ownership changed",
        body=f"{_display_name(target_user)} is now the workspace owner.",
        actor_user_id=_int_or_none(getattr(actor_user, "id", None)),
        reference_type="team",
        reference_id=_int_or_none(target_membership.user_id),
        recipient_capability="team.manage",
    )

    # The members list is rebuilt from a query, and the session has autoflush=False, so
    # flush first or the payload would still show the old owner.
    db.flush()
    return {
        "owner_user_id": _int_or_none(target_membership.user_id),
        "previous_owner_user_id": previous_owner_user_id,
        "members": list_members(db, org_id),
    }


# ===========================================================================
# META / LOG / SELF-SERVICE
# ===========================================================================

def team_meta_payload(db: Session, *, organization, membership, ctx) -> dict:
    """Everything the Team screen needs to render its editors, in one response."""
    org_id = int(organization.id)
    payload = access.capability_registry_payload()

    client_counts = branch_client_counts(db, org_id)
    member_counts = branch_member_counts(db, org_id)
    visible = _ctx_branch_ids(ctx)
    org_scope = bool(getattr(ctx, "is_org_scope", False)) or bool(getattr(ctx, "is_owner", False))

    branches = []
    for branch in list_branches(db, org_id, include_archived=False):
        # Volumes are per-office business intelligence. A branch-scoped manager may need
        # the office LIST (to file a client), but must not learn how many clients every
        # other office is running.
        counts_visible = org_scope or int(branch.id) in visible
        row = serialize_branch(
            branch,
            member_count=member_counts.get(int(branch.id), 0) if counts_visible else 0,
            client_count=client_counts.get(int(branch.id), 0) if counts_visible else 0,
        )
        row["counts_visible"] = counts_visible
        branches.append(row)

    seats = billing.build_subscription_state(db, org_id)
    payload.update({
        "custom_roles": list_roles_payload(db, org_id, include_archived=False),
        "branches": branches,
        "limits": access.limits_payload(),
        "me": access.access_payload(ctx),
        "seats": {"used": seats.get("seats_used", 0), "max": seats.get("max_seats", billing.UNLIMITED)},
        # What the CALLER may hand out. Owner-only keys are excluded for everyone —
        # including the owner — because nobody can grant them (see assert_can_grant), and
        # a checkbox that always 422s is worse than no checkbox.
        "actor_capabilities": sorted(
            (set(access.CAPABILITY_KEYS) if getattr(ctx, "is_owner", False)
             else set(getattr(ctx, "capabilities", None) or frozenset()))
            - set(access.OWNER_ONLY_CAPABILITIES)
        ),
    })
    return payload


def access_log_payload(
    db: Session,
    *,
    organization,
    ctx,
    limit: int = 50,
    offset: int = 0,
    action=None,
    target_user_id=None,
    days: int = 90,
) -> dict:
    org_id = int(organization.id)
    A = models.EnterpriseAccessAudit

    try:
        limit = max(1, min(200, int(limit or 50)))
    except (TypeError, ValueError):
        limit = 50
    try:
        offset = max(0, int(offset or 0))
    except (TypeError, ValueError):
        offset = 0
    try:
        days = max(1, min(365, int(days or 90)))
    except (TypeError, ValueError):
        days = 90

    query = db.query(A).filter(
        A.organization_id == org_id,
        A.created_at >= (_utcnow() - timedelta(days=days)),
    )
    action_key = _clean_text(action, 100)
    if action_key:
        query = query.filter(A.action == action_key)
    target_uid = _int_or_none(target_user_id)
    if target_uid:
        query = query.filter(A.target_user_id == target_uid)

    if not (bool(getattr(ctx, "is_org_scope", False)) or bool(getattr(ctx, "is_owner", False))):
        # The org-wide permission map is reconnaissance: it names every admin, every
        # finance member and every office. A branch-scoped member sees only their own
        # offices' people, plus anything they did or that was done to them.
        branch_ids = _ctx_branch_ids(ctx)
        peer_ids: set[int] = set()
        if branch_ids:
            M = models.EnterpriseOrganizationMember
            MB = models.EnterpriseMemberBranch
            rows = (
                db.query(M.user_id)
                .outerjoin(MB, MB.member_id == M.id)
                .filter(
                    M.organization_id == org_id,
                    or_(MB.branch_id.in_(branch_ids), M.primary_branch_id.in_(branch_ids)),
                )
                .all()
            )
            peer_ids = {int(uid) for (uid,) in rows if uid is not None}
        me = _int_or_none(getattr(ctx, "user_id", None))
        if me:
            peer_ids.add(me)
        clauses = [A.actor_user_id == me, A.target_user_id == me] if me else []
        if peer_ids:
            clauses.append(A.target_user_id.in_(sorted(peer_ids)))
        query = query.filter(or_(*clauses)) if clauses else query.filter(false())

    total = int(query.with_entities(func.count(A.id)).scalar() or 0)
    rows = (
        query.order_by(A.created_at.desc(), A.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    entries = [serialize_audit_entry(row) for row in rows]
    return {
        "entries": entries,
        "total": total,
        "has_more": bool(offset + len(entries) < total),
        "limit": limit,
        "offset": offset,
        "days": days,
        # The filter dropdown, built from the actions this module can actually write, so
        # it never offers a filter that returns nothing.
        "actions": [{"key": key, "label": label} for key, label in ACTION_LABELS.items()],
    }
