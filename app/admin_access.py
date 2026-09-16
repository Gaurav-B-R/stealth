"""Fresh, section-scoped authorization for the standalone platform admin console.

These memberships do not grant the global User.is_admin flag or Enterprise access.
Every console endpoint declares a policy, including endpoints whose GET reads can
mutate state. Unclassified endpoints are denied rather than inheriting access.
"""

from dataclasses import dataclass
import json
from typing import Literal

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr
from sqlalchemy.orm import Session

from app import models
from app.auth import is_enterprise_only_account
from app import admin_sessions
from app.admin_sessions import get_current_console_user
from app.database import get_db


SECTIONS = (
    {"key": "users", "label": "Student Accounts"},
    {"key": "enterprise", "label": "Enterprise Accounts"},
    {"key": "analytics", "label": "Analytics & Agent"},
    {"key": "finance", "label": "Investment Analytics"},
    {"key": "ai", "label": "AI Costs"},
    {"key": "team", "label": "Team"},
)
SECTION_KEYS = tuple(item["key"] for item in SECTIONS)
ROLES = ("admin", "editor", "viewer")
ROLE_RANK = {"viewer": 1, "editor": 2, "admin": 3}
SectionKey = Literal["users", "enterprise", "analytics", "finance", "ai", "team"]
Role = Literal["admin", "editor", "viewer"]


class TeamAccessUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Role
    sections: list[SectionKey] = Field(min_length=1, max_length=len(SECTION_KEYS))
    console_password: SecretStr | None = None


class TeamAccessCreate(TeamAccessUpdate):
    email: EmailStr


@dataclass(frozen=True)
class ConsoleAccess:
    role: str
    sections: frozenset[str]
    protected: bool = False

    def allows(self, section: str, action: str = "read") -> bool:
        if section not in self.sections or action not in {"read", "write", "delete"}:
            return False
        if section == "team" and self.role != "admin":
            return False
        return action == "read" or self.role == "admin" or (action == "write" and self.role == "editor")


@dataclass(frozen=True)
class RoutePolicy:
    section: str | None
    action: str
    legacy_admin: bool = False


def console_section(section: str | None, action: str = "read", *, legacy_admin: bool = False):
    if section is not None and section not in SECTION_KEYS:
        raise ValueError("Unknown admin console section")
    if action not in {"read", "write", "delete", "access"}:
        raise ValueError("Unknown admin console action")
    if (section is None) != (action == "access"):
        raise ValueError("Shared console routes must explicitly declare access")

    def decorate(endpoint):
        endpoint.admin_console_policy = RoutePolicy(section, action, legacy_admin)
        return endpoint
    return decorate


def is_legacy_admin(user) -> bool:
    return bool(getattr(user, "is_admin", False) or getattr(user, "is_developer", False))


def membership_for(db: Session, user_id: int):
    # populate_existing also observes edits in a reused Session; never trust JWT
    # claims or the ORM identity map for a membership's current permissions.
    return (db.query(models.AdminConsoleAccess).populate_existing()
            .filter(models.AdminConsoleAccess.user_id == user_id).first())


def access_for(db: Session, user, membership=None) -> ConsoleAccess | None:
    if is_legacy_admin(user):
        return ConsoleAccess("admin", frozenset(SECTION_KEYS), protected=True)
    row = membership if membership is not None else membership_for(db, user.id)
    if row is None or row.role not in ROLES:
        return None
    try:
        sections = json.loads(row.sections)
        if not isinstance(sections, list) or not sections or any(key not in SECTION_KEYS for key in sections):
            return None
        if len(sections) != len(set(sections)) or ("team" in sections and row.role != "admin"):
            return None
    except (TypeError, ValueError):
        return None
    return ConsoleAccess(row.role, frozenset(sections))


def require_access(db: Session, user) -> ConsoleAccess:
    access = access_for(db, user)
    if (not getattr(user, "is_active", False) or not getattr(user, "email_verified", False)
            or access is None or is_enterprise_only_account(user)):
        raise HTTPException(403, "Admin Console access required.")
    return access


def get_current_admin_user(
    request: Request,
    current_user: models.User = Depends(get_current_console_user),
    db: Session = Depends(get_db),
):
    """Console-only dependency; leave app.auth's global admin dependency unchanged."""
    access = require_access(db, current_user)
    endpoint = getattr(request.scope.get("route"), "endpoint", None)
    policy = getattr(endpoint, "admin_console_policy", None)
    if not isinstance(policy, RoutePolicy):
        raise HTTPException(403, "This Admin Console endpoint has no access policy.")
    if policy.legacy_admin and not access.protected:
        raise HTTPException(403, "This action requires an existing platform administrator.")
    if policy.action != "access" and not access.allows(policy.section, policy.action):
        raise HTTPException(403, "Your Admin Console role does not allow this action in this section.")
    return current_user


def ordered_sections(sections) -> list[str]:
    return [key for key in SECTION_KEYS if key in sections]


def access_payload(db: Session, user) -> dict:
    access = require_access(db, user)
    return {
        "user": {"id": user.id, "email": user.email, "full_name": user.full_name,
                 "is_admin": bool(user.is_admin), "is_developer": bool(user.is_developer)},
        "role": access.role,
        "sections": ordered_sections(access.sections),
        "can_manage_team": access.allows("team", "write"),
        "can_write_sections": [key for key in SECTION_KEYS if access.allows(key, "write")],
        "can_delete_sections": [key for key in SECTION_KEYS if access.allows(key, "delete")],
        "can_provision_enterprise": access.protected,
    }


def require_team_manager(db: Session, user) -> ConsoleAccess:
    access = require_access(db, user)
    if not access.allows("team", "write"):
        raise HTTPException(403, "Admin access to the Team section is required.")
    return access


def can_manage_member(db: Session, actor, target, *, target_membership=None) -> bool:
    actor_access = access_for(db, actor)
    if (actor.id == target.id or is_legacy_admin(target) or actor_access is None
            or not actor_access.allows("team", "write")):
        return False
    target_access = access_for(db, target, target_membership)
    if target_access is None:
        # A corrupt membership must not be mistaken for an unprivileged account.
        return membership_for(db, target.id) is None
    return (target_access.sections <= actor_access.sections
            and ROLE_RANK[target_access.role] <= ROLE_RANK[actor_access.role])


def assert_manageable_member(db: Session, actor, target) -> None:
    require_team_manager(db, actor)
    if not can_manage_member(db, actor, target):
        raise HTTPException(403, "You cannot manage your own, protected, or more broadly scoped console access.")


def validated_grant(db: Session, actor, payload: TeamAccessUpdate) -> list[str]:
    access = require_team_manager(db, actor)
    sections = list(payload.sections)
    if len(set(sections)) != len(sections):
        raise HTTPException(422, "Choose each section only once.")
    if "team" in sections and payload.role != "admin":
        raise HTTPException(422, "Only Admin roles can receive the Team section.")
    if not set(sections) <= access.sections or ROLE_RANK[payload.role] > ROLE_RANK[access.role]:
        raise HTTPException(403, "You cannot grant permissions outside your own access.")
    return ordered_sections(sections)


def serialize_member(db: Session, actor, target, membership=None) -> dict:
    access = access_for(db, target, membership)
    return {
        "user_id": target.id, "email": target.email, "full_name": target.full_name,
        "role": access.role if access else "viewer",
        "sections": ordered_sections(access.sections) if access else [],
        "protected": is_legacy_admin(target),
        "can_manage": can_manage_member(db, actor, target, target_membership=membership),
        "has_console_password": admin_sessions.has_console_password(db, target.id),
    }
