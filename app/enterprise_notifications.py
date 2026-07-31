"""
Enterprise in-portal notifications (the topbar bell).

Design principles ("communications should be limited"):
- HIGH-SIGNAL EVENTS ONLY: client added, pipeline stage moved, mock interview completed,
  requested documents submitted, team membership changes, credits running low. Routine
  actions (notes, per-field edits, running a scan) deliberately do NOT notify.
- NEVER notify the actor about their own action — only teammates see it.
- DEDUPED: an identical event (same org/type/reference/title) within a short window is
  dropped, so bursts (e.g. rapid stage clicks) produce one notification, not five.
- BEST-EFFORT: notification failures never break the business action that triggered them.
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app import models

logger = logging.getLogger(__name__)

# Identical-event suppression window (minutes).
DEDUPE_MINUTES = 10
# Keep at most this many notifications per recipient (oldest pruned, best-effort).
MAX_PER_RECIPIENT = 200
# "Credits low" fires when a debit crosses below this balance (admins only).
CREDITS_LOW_THRESHOLD = 20


def _active_member_user_ids(db: Session, organization_id: int, roles: list[str] | None = None) -> list[int]:
    q = (
        db.query(models.EnterpriseOrganizationMember.user_id)
        .filter(
            models.EnterpriseOrganizationMember.organization_id == organization_id,
            models.EnterpriseOrganizationMember.is_active.is_(True),
        )
    )
    if roles:
        q = q.filter(models.EnterpriseOrganizationMember.role.in_(roles))
    return [row[0] for row in q.all()]


def _resolved_org_members(db: Session, organization_id: int) -> list[dict]:
    """Every active member's effective capabilities and record scope, in THREE queries total.

    Notification fan-out runs inside the caller's write transaction on hot paths (every client
    add, every stage move), so resolving each member's context individually — two queries per
    member — would turn a 2-query fan-out into 60+ on a 30-person agency while holding a lock.
    Instead we pull members, their office links and the org's custom roles in bulk and do the
    capability/scope arithmetic in Python.
    """
    from app import enterprise_access as access

    members = (
        db.query(models.EnterpriseOrganizationMember)
        .filter(
            models.EnterpriseOrganizationMember.organization_id == organization_id,
            models.EnterpriseOrganizationMember.is_active.is_(True),
        )
        .all()
    )
    if not members:
        return []

    # Only ACTIVE offices count: an archived office left on a member's row would otherwise look
    # like a real, non-empty scope that matches nothing.
    branch_rows = (
        db.query(models.EnterpriseMemberBranch.member_id, models.EnterpriseMemberBranch.branch_id)
        .join(models.EnterpriseBranch, models.EnterpriseBranch.id == models.EnterpriseMemberBranch.branch_id)
        .filter(
            models.EnterpriseMemberBranch.organization_id == organization_id,
            models.EnterpriseBranch.is_active.is_(True),
        )
        .all()
    )
    branches_by_member: dict[int, list[int]] = {}
    for member_id, branch_id in branch_rows:
        branches_by_member.setdefault(int(member_id), []).append(int(branch_id))

    custom_roles = {
        int(row.id): row
        for row in db.query(models.EnterpriseRole)
        .filter(models.EnterpriseRole.organization_id == organization_id)
        .all()
    }

    resolved: list[dict] = []
    for member in members:
        role_key = access.normalize_role_key(
            getattr(member, "role_key", None), getattr(member, "role", None)
        )
        custom = custom_roles.get(int(getattr(member, "custom_role_id", None) or 0))
        capabilities = access.effective_capabilities(
            role_key=role_key,
            custom_role_caps=(custom.capabilities_json if custom else None),
            custom_role_active=bool(custom is not None and custom.is_active),
            grants=getattr(member, "capability_grants_json", None),
            denies=getattr(member, "capability_denies_json", None),
        )
        branch_ids = branches_by_member.get(int(member.id), [])
        scope_kind, scope_branches = access.effective_scope(
            role_key=role_key,
            member_scope=getattr(member, "data_scope", None),
            custom_role_scope=(custom.data_scope if custom else None),
            branch_ids=branch_ids,
            primary_branch_id=getattr(member, "primary_branch_id", None),
        )
        resolved.append({
            "user_id": int(member.user_id),
            "role_key": role_key,
            "capabilities": capabilities,
            "scope_kind": scope_kind,
            "branch_ids": scope_branches,
        })
    return resolved


def _client_scope_predicate(client, resolved: dict) -> bool:
    """Would this member be allowed to open the client the notification points at?

    Without this, a scope-restricted member gets a live activity feed of the whole workspace —
    client names, stage moves and all — and clicking through 404s, which itself confirms the
    record exists. Filtering at the FAN-OUT means the link is never created in the first place.
    """
    if resolved["scope_kind"] == "all":
        return True
    if client is None:
        return False
    if resolved["scope_kind"] == "branch":
        branch_id = getattr(client, "branch_id", None)
        return bool(branch_id) and int(branch_id) in resolved["branch_ids"]
    user_id = resolved["user_id"]
    assigned = getattr(client, "assigned_to_user_id", None)
    created = getattr(client, "created_by_user_id", None)
    return (assigned is not None and int(assigned) == user_id) or (
        created is not None and int(created) == user_id
    )


def _is_duplicate(db: Session, organization_id: int, type_: str, title: str,
                  reference_type: str | None, reference_id: int | None) -> bool:
    cutoff = datetime.utcnow() - timedelta(minutes=DEDUPE_MINUTES)
    q = (
        db.query(models.EnterpriseNotification.id)
        .filter(
            models.EnterpriseNotification.organization_id == organization_id,
            models.EnterpriseNotification.type == type_,
            models.EnterpriseNotification.title == title,
            models.EnterpriseNotification.created_at >= cutoff,
        )
    )
    if reference_type is not None:
        q = q.filter(models.EnterpriseNotification.reference_type == reference_type)
    if reference_id is not None:
        q = q.filter(models.EnterpriseNotification.reference_id == reference_id)
    return db.query(q.exists()).scalar() or False


def _prune_recipient(db: Session, recipient_user_id: int) -> None:
    """Best-effort cap on stored notifications per recipient."""
    try:
        ids = [
            row[0] for row in (
                db.query(models.EnterpriseNotification.id)
                .filter(models.EnterpriseNotification.recipient_user_id == recipient_user_id)
                .order_by(models.EnterpriseNotification.created_at.desc(), models.EnterpriseNotification.id.desc())
                .offset(MAX_PER_RECIPIENT)
                .limit(200)
                .all()
            )
        ]
        if ids:
            (db.query(models.EnterpriseNotification)
             .filter(models.EnterpriseNotification.id.in_(ids))
             .delete(synchronize_session=False))
    except Exception:
        pass


def notify_org(
    db: Session,
    organization_id: int,
    *,
    type: str,
    title: str,
    body: str | None = None,
    actor_user_id: int | None = None,
    reference_type: str | None = None,
    reference_id: int | None = None,
    recipient_roles: list[str] | None = None,
    recipient_capability: str | None = None,
    client_scope_id: int | None = None,
    commit: bool = False,
) -> int:
    """Fan a notification out to the org's active members (minus the actor).

    Returns the number of notifications created. Never raises — a notification
    failure must never break the action that produced it. Does NOT commit unless
    asked, so it can ride the caller's transaction.

    `recipient_capability` targets by what people can DO rather than by role string, which is
    what makes a Finance member or a custom role still receive (say) low-credit warnings.
    `client_scope_id` restricts the fan-out to members whose record scope actually covers that
    client, so a branch- or caseload-scoped member never sees another office's activity.
    """
    try:
        if _is_duplicate(db, organization_id, type, title, reference_type, reference_id):
            return 0
        # A notification that points AT a client is, by definition, about that client — and its
        # title usually contains their name. So derive the scope from the reference rather than
        # relying on ~8 call sites to remember a kwarg (and every future one to remember it too).
        # An explicit client_scope_id still wins.
        if client_scope_id is None and reference_type == "client" and reference_id:
            client_scope_id = int(reference_id)
        if recipient_capability or client_scope_id:
            resolved = _resolved_org_members(db, organization_id)
            client = None
            if client_scope_id:
                client = (
                    db.query(models.EnterpriseClient)
                    .filter(
                        models.EnterpriseClient.id == int(client_scope_id),
                        models.EnterpriseClient.organization_id == organization_id,
                    )
                    .first()
                )
            recipients = [
                r["user_id"] for r in resolved
                if r["user_id"] != actor_user_id
                and (
                    not recipient_capability
                    or r["role_key"] == "owner"
                    or recipient_capability in r["capabilities"]
                )
                and (not client_scope_id or _client_scope_predicate(client, r))
            ]
        else:
            recipients = [
                uid for uid in _active_member_user_ids(db, organization_id, roles=recipient_roles)
                if uid != actor_user_id
            ]
        if not recipients:
            return 0
        for uid in recipients:
            db.add(models.EnterpriseNotification(
                organization_id=organization_id,
                recipient_user_id=uid,
                actor_user_id=actor_user_id,
                type=str(type)[:60],
                title=str(title)[:300],
                body=(str(body)[:1000] if body else None),
                reference_type=reference_type,
                reference_id=reference_id,
            ))
            _prune_recipient(db, uid)
        if commit:
            db.commit()
        return len(recipients)
    except Exception:
        logger.warning("enterprise notification fan-out failed (org=%s, type=%s)",
                       organization_id, type, exc_info=True)
        try:
            db.rollback() if commit else None
        except Exception:
            pass
        return 0


def notify_user(
    db: Session,
    organization_id: int,
    recipient_user_id: int,
    *,
    type: str,
    title: str,
    body: str | None = None,
    actor_user_id: int | None = None,
    reference_type: str | None = None,
    reference_id: int | None = None,
    commit: bool = False,
) -> int:
    """Notify ONE specific member — including when they are the actor.

    `notify_org` deliberately excludes the actor, which structurally cannot tell someone that
    something happened *to them*: "an admin changed your access" has to reach the person whose
    access changed. Same best-effort contract — never raises.
    """
    try:
        if not recipient_user_id:
            return 0
        if _is_duplicate(db, organization_id, type, title, reference_type, reference_id):
            return 0
        db.add(models.EnterpriseNotification(
            organization_id=organization_id,
            recipient_user_id=int(recipient_user_id),
            actor_user_id=actor_user_id,
            type=str(type)[:60],
            title=str(title)[:300],
            body=(str(body)[:1000] if body else None),
            reference_type=reference_type,
            reference_id=reference_id,
        ))
        _prune_recipient(db, int(recipient_user_id))
        if commit:
            db.commit()
        return 1
    except Exception:
        logger.warning("enterprise notification to user failed (org=%s, user=%s, type=%s)",
                       organization_id, recipient_user_id, type, exc_info=True)
        try:
            db.rollback() if commit else None
        except Exception:
            pass
        return 0


def maybe_notify_credits_low(db: Session, organization_id: int, balance_before: int, balance_after: int) -> None:
    """Notify whoever can act on it once a debit crosses below the low-credit threshold.

    Targeted by capability, not by the legacy `role` string: the people who need to see this are
    the ones who can top the wallet up, which now includes a Finance member or a custom role — an
    `role == "admin"` filter would silently miss them.
    """
    if balance_before >= CREDITS_LOW_THRESHOLD > balance_after:
        notify_org(
            db, organization_id,
            type="credits_low",
            title=f"Credits running low — {balance_after} left",
            body="Top up Rilono Credits so Deep Scans, mock interviews and the AI assistant keep working for your team.",
            reference_type="credits",
            recipient_capability="credits.purchase",
        )
