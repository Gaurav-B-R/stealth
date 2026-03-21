import os
import re
import secrets
import logging
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func
from sqlalchemy.orm import Session
from datetime import timedelta, datetime
from pydantic import BaseModel, EmailStr, Field

from app.database import get_db, SessionLocal
from app import models
from app.auth import (
    authenticate_user,
    create_access_token,
    get_current_active_user,
    get_password_hash,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    set_auth_cookie,
)
from app.utils.rate_limiter import (
    check_ip_rate_limit,
    extract_client_ip,
    is_request_ip_whitelisted,
)
from app.utils.turnstile import is_turnstile_enabled, verify_turnstile_token
from app.email_service import send_enterprise_team_invite_email
from app.email_service import generate_verification_token, DEFAULT_PUBLIC_BASE_URL
from app.utils.token_security import hash_token

router = APIRouter(prefix="/api/enterprise", tags=["enterprise"])
logger = logging.getLogger(__name__)

ENTERPRISE_ROLE_ADMIN = "admin"
ENTERPRISE_ROLE_EDITOR = "editor"
ENTERPRISE_ROLE_VIEWER = "viewer"
ENTERPRISE_ALLOWED_ROLES = {ENTERPRISE_ROLE_ADMIN, ENTERPRISE_ROLE_EDITOR, ENTERPRISE_ROLE_VIEWER}

ENTERPRISE_SUBDOMAIN_MIN_LENGTH = 3
ENTERPRISE_SUBDOMAIN_MAX_LENGTH = 32
ENTERPRISE_SUBDOMAIN_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,30}[a-z0-9])$")
ENTERPRISE_RESERVED_SUBDOMAINS = {
    "www",
    "app",
    "api",
    "admin",
    "auth",
    "portal",
    "enterprise",
    "mail",
    "status",
    "support",
    "docs",
    "blog",
    "cdn",
    "m",
    "ftp",
    "smtp",
    "imap",
    "pop",
    "rilono",
}
ENTERPRISE_ROOT_DOMAIN = (os.getenv("ENTERPRISE_ROOT_DOMAIN", "rilono.com").strip().lower() or "rilono.com").lstrip(".")
ENTERPRISE_PORTAL_SCHEME = os.getenv("ENTERPRISE_PORTAL_SCHEME", "https").strip().lower() or "https"
ENTERPRISE_PASSWORD_SETUP_BASE_URL = (
    os.getenv("BASE_URL", DEFAULT_PUBLIC_BASE_URL).strip() or DEFAULT_PUBLIC_BASE_URL
).rstrip("/")
ENTERPRISE_INVITE_PASSWORD_SETUP_EXPIRES_HOURS = max(
    1,
    int(os.getenv("ENTERPRISE_INVITE_PASSWORD_SETUP_EXPIRES_HOURS", "72")),
)
ENTERPRISE_LOGIN_RATE_LIMIT = int(os.getenv("ENTERPRISE_LOGIN_RATE_LIMIT", os.getenv("LOGIN_RATE_LIMIT", "12")))
ENTERPRISE_LOGIN_RATE_WINDOW_SECONDS = int(
    os.getenv("ENTERPRISE_LOGIN_RATE_WINDOW_SECONDS", os.getenv("LOGIN_RATE_WINDOW_SECONDS", "300"))
)


class EnterpriseLoginRequest(BaseModel):
    email: EmailStr
    password: str
    cf_turnstile_token: Optional[str] = None


class EnterpriseOnboardingRequest(BaseModel):
    company_name: str = Field(..., min_length=2, max_length=120)
    subdomain_slug: str = Field(
        ...,
        min_length=ENTERPRISE_SUBDOMAIN_MIN_LENGTH,
        max_length=ENTERPRISE_SUBDOMAIN_MAX_LENGTH,
    )


class EnterpriseTeamAddUserRequest(BaseModel):
    email: EmailStr
    role: str = Field(default=ENTERPRISE_ROLE_VIEWER, min_length=3, max_length=16)
    full_name: Optional[str] = Field(default=None, max_length=120)


class EnterpriseTeamRoleUpdateRequest(BaseModel):
    role: str = Field(..., min_length=3, max_length=16)


def _is_development_env() -> bool:
    return os.getenv("ENVIRONMENT", "production").strip().lower() == "development"


def _is_turnstile_required() -> bool:
    return is_turnstile_enabled() and not _is_development_env()


def _enforce_rate_limit_or_429(
    request: Request,
    scope: str,
    limit: int,
    window_seconds: int,
    extra_key: str | None = None,
) -> None:
    allowed, retry_after = check_ip_rate_limit(
        request=request,
        scope=scope,
        limit=limit,
        window_seconds=window_seconds,
        extra_key=extra_key,
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )


def _normalize_enterprise_role(raw_role: str | None) -> str:
    normalized = str(raw_role or "").strip().lower()
    if normalized in {"owner", "org_admin", "organization_admin"}:
        return ENTERPRISE_ROLE_ADMIN
    if normalized in {"edit", "write"}:
        return ENTERPRISE_ROLE_EDITOR
    if normalized in {"read", "view"}:
        return ENTERPRISE_ROLE_VIEWER
    if normalized in ENTERPRISE_ALLOWED_ROLES:
        return normalized
    return ENTERPRISE_ROLE_VIEWER


def _parse_enterprise_role_or_400(raw_role: str | None) -> str:
    normalized = str(raw_role or "").strip().lower()
    if normalized in {"owner", "org_admin", "organization_admin"}:
        return ENTERPRISE_ROLE_ADMIN
    if normalized in {"edit", "write"}:
        return ENTERPRISE_ROLE_EDITOR
    if normalized in {"read", "view"}:
        return ENTERPRISE_ROLE_VIEWER
    if normalized in ENTERPRISE_ALLOWED_ROLES:
        return normalized
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Invalid role. Use admin, editor, or viewer.",
    )


def _enterprise_permissions_for_role(role: str) -> dict[str, bool]:
    normalized = _normalize_enterprise_role(role)
    return {
        "can_view_data": True,
        "can_edit_data": normalized in {ENTERPRISE_ROLE_ADMIN, ENTERPRISE_ROLE_EDITOR},
        "can_manage_users": normalized == ENTERPRISE_ROLE_ADMIN,
    }


def _blocked_enterprise_permissions() -> dict[str, bool]:
    return {
        "can_view_data": False,
        "can_edit_data": False,
        "can_manage_users": False,
    }


def _build_enterprise_portal_url(subdomain_slug: str | None) -> str | None:
    subdomain = str(subdomain_slug or "").strip().lower()
    if not subdomain:
        return None
    return f"{ENTERPRISE_PORTAL_SCHEME}://{subdomain}.{ENTERPRISE_ROOT_DOMAIN}/enterprise"


def _extract_enterprise_subdomain_from_request(request: Request | None) -> str | None:
    if request is None:
        return None

    host = (
        request.headers.get("x-forwarded-host")
        or request.headers.get("host")
        or request.url.netloc
        or ""
    ).split(",")[0].strip().lower()
    if not host:
        return None
    host = host.split(":")[0].strip()
    if not host:
        return None

    root_domain = ENTERPRISE_ROOT_DOMAIN.lower()
    if host == root_domain or host == f"www.{root_domain}":
        return None

    suffix = f".{root_domain}"
    if not host.endswith(suffix):
        return None

    subdomain_part = host[: -len(suffix)].strip(".")
    if not subdomain_part:
        return None
    return subdomain_part


def _enforce_request_subdomain_matches_org(
    request: Request | None,
    organization: models.EnterpriseOrganization | None,
) -> None:
    if not request or not organization:
        return
    request_subdomain = _extract_enterprise_subdomain_from_request(request)
    if not request_subdomain:
        return
    org_subdomain = str(organization.subdomain_slug or "").strip().lower()
    if not org_subdomain:
        return
    if request_subdomain != org_subdomain:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Use your organization URL: {_build_enterprise_portal_url(org_subdomain)}",
        )


def _enforce_payload_subdomain_matches_request(
    request: Request | None,
    payload_subdomain: str,
) -> None:
    request_subdomain = _extract_enterprise_subdomain_from_request(request)
    if not request_subdomain:
        return
    if request_subdomain != payload_subdomain:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Organization URL must match the current subdomain. "
                f"You are currently on {request_subdomain}.{ENTERPRISE_ROOT_DOMAIN}."
            ),
        )


def _parse_enterprise_subdomain_or_400(raw_subdomain: str | None) -> str:
    normalized = str(raw_subdomain or "").strip().lower()
    if not normalized:
        raise HTTPException(status_code=400, detail="Organization URL is required.")
    if len(normalized) < ENTERPRISE_SUBDOMAIN_MIN_LENGTH or len(normalized) > ENTERPRISE_SUBDOMAIN_MAX_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Organization URL must be {ENTERPRISE_SUBDOMAIN_MIN_LENGTH}-"
                f"{ENTERPRISE_SUBDOMAIN_MAX_LENGTH} characters."
            ),
        )
    if normalized in ENTERPRISE_RESERVED_SUBDOMAINS:
        raise HTTPException(
            status_code=400,
            detail="This organization URL is reserved. Please choose a different one.",
        )
    if not ENTERPRISE_SUBDOMAIN_PATTERN.fullmatch(normalized):
        raise HTTPException(
            status_code=400,
            detail=(
                "Organization URL can only contain lowercase letters, numbers, and hyphens, "
                "and cannot start or end with a hyphen."
            ),
        )
    return normalized


def _assert_subdomain_available(
    db: Session,
    subdomain_slug: str,
    *,
    exclude_organization_id: int | None = None,
) -> None:
    query = (
        db.query(models.EnterpriseOrganization)
        .filter(func.lower(models.EnterpriseOrganization.subdomain_slug) == subdomain_slug.lower())
    )
    if exclude_organization_id is not None:
        query = query.filter(models.EnterpriseOrganization.id != int(exclude_organization_id))
    existing = query.first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"The URL {subdomain_slug}.{ENTERPRISE_ROOT_DOMAIN} is already taken.",
        )


def _get_active_enterprise_membership(
    db: Session,
    user_id: int,
) -> tuple[models.EnterpriseOrganizationMember | None, models.EnterpriseOrganization | None]:
    membership = (
        db.query(models.EnterpriseOrganizationMember)
        .filter(
            models.EnterpriseOrganizationMember.user_id == int(user_id),
            models.EnterpriseOrganizationMember.is_active.is_(True),
        )
        .order_by(models.EnterpriseOrganizationMember.id.asc())
        .first()
    )
    if not membership:
        return None, None
    organization = (
        db.query(models.EnterpriseOrganization)
        .filter(models.EnterpriseOrganization.id == membership.organization_id)
        .first()
    )
    if not organization:
        return None, None
    return membership, organization


def _build_enterprise_context(db: Session, user: models.User) -> dict:
    membership, organization = _get_active_enterprise_membership(db, user.id)
    if not membership or not organization:
        return {
            "onboarding_required": True,
            "organization": None,
            "membership": None,
            "permissions": _blocked_enterprise_permissions(),
        }

    normalized_role = _normalize_enterprise_role(membership.role)
    company_name = (organization.company_name or "").strip()
    subdomain_slug = (organization.subdomain_slug or "").strip().lower()
    onboarding_required = not company_name or not subdomain_slug
    return {
        "onboarding_required": onboarding_required,
        "organization": {
            "id": organization.id,
            "company_name": company_name or organization.company_name,
            "subdomain_slug": subdomain_slug or None,
            "portal_url": _build_enterprise_portal_url(subdomain_slug),
            "created_at": organization.created_at,
        },
        "membership": {
            "role": normalized_role,
            "is_active": bool(membership.is_active),
            "joined_at": membership.created_at,
        },
        "permissions": (
            _enterprise_permissions_for_role(normalized_role)
            if not onboarding_required
            else _blocked_enterprise_permissions()
        ),
    }


def _require_enterprise_membership(
    *,
    db: Session,
    user: models.User,
    request: Request | None = None,
    require_manage_users: bool = False,
) -> tuple[models.EnterpriseOrganizationMember, models.EnterpriseOrganization, str]:
    membership, organization = _get_active_enterprise_membership(db, user.id)
    if not membership or not organization:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Enterprise onboarding is required before accessing this feature.",
        )

    role = _normalize_enterprise_role(membership.role)
    subdomain_slug = (organization.subdomain_slug or "").strip().lower()
    if not subdomain_slug:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Complete enterprise onboarding by setting your organization URL first.",
        )
    _enforce_request_subdomain_matches_org(request, organization)
    if require_manage_users and role != ENTERPRISE_ROLE_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only organization admins can manage users.",
        )
    return membership, organization, role


def _serialize_team_member(
    membership: models.EnterpriseOrganizationMember,
    user: models.User,
) -> dict:
    return {
        "user_id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "role": _normalize_enterprise_role(membership.role),
        "is_active": bool(membership.is_active),
        "joined_at": membership.created_at,
        "last_login_at": user.last_login_at,
    }


def _list_organization_members(
    db: Session,
    organization_id: int,
) -> list[dict]:
    rows = (
        db.query(models.EnterpriseOrganizationMember, models.User)
        .join(
            models.User,
            models.User.id == models.EnterpriseOrganizationMember.user_id,
        )
        .filter(
            models.EnterpriseOrganizationMember.organization_id == int(organization_id),
            models.EnterpriseOrganizationMember.is_active.is_(True),
        )
        .order_by(models.EnterpriseOrganizationMember.created_at.asc())
        .all()
    )
    return [_serialize_team_member(member, user) for member, user in rows]


def _active_admin_count(db: Session, organization_id: int) -> int:
    return int(
        db.query(models.EnterpriseOrganizationMember)
        .filter(
            models.EnterpriseOrganizationMember.organization_id == int(organization_id),
            models.EnterpriseOrganizationMember.is_active.is_(True),
            models.EnterpriseOrganizationMember.role == ENTERPRISE_ROLE_ADMIN,
        )
        .count()
    )


def seed_enterprise_user() -> None:
    """
    Sync enterprise credential rows from PostgreSQL into users table for auth/session reuse.
    """
    db = SessionLocal()
    try:
        credentials = (
            db.query(models.EnterpriseCredential)
            .filter(models.EnterpriseCredential.is_active.is_(True))
            .all()
        )
        if not credentials:
            return

        changes_made = False
        for entry in credentials:
            email = (entry.email or "").strip().lower()
            password_hash = (entry.password_hash or "").strip()
            if not email or not password_hash:
                continue

            existing = db.query(models.User).filter(models.User.email == email).first()
            if existing:
                existing.hashed_password = password_hash
                existing.is_active = True
                existing.email_verified = True
                existing.is_admin = True
                if not existing.full_name:
                    existing.full_name = (entry.full_name or "Enterprise Admin").strip()
                if not existing.university:
                    existing.university = "Enterprise Account"
                if existing.accepted_terms_privacy_at is None:
                    existing.accepted_terms_privacy_at = datetime.utcnow()
                changes_made = True
                continue

            user = models.User(
                email=email,
                username=None,
                hashed_password=password_hash,
                full_name=(entry.full_name or "Enterprise Admin").strip(),
                university="Enterprise Account",
                is_active=True,
                email_verified=True,
                is_admin=True,
                accepted_terms_privacy_at=datetime.utcnow(),
            )
            db.add(user)
            changes_made = True

        if changes_made:
            db.commit()
    finally:
        db.close()


@router.post("/login")
async def enterprise_login(
    payload: EnterpriseLoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    _enforce_rate_limit_or_429(
        request=request,
        scope="enterprise.login",
        limit=ENTERPRISE_LOGIN_RATE_LIMIT,
        window_seconds=ENTERPRISE_LOGIN_RATE_WINDOW_SECONDS,
    )

    turnstile_token = (payload.cf_turnstile_token or "").strip()
    ip_whitelisted = is_request_ip_whitelisted(request)
    if is_turnstile_enabled() and not ip_whitelisted:
        if turnstile_token:
            client_ip = extract_client_ip(request) if request else None
            if not verify_turnstile_token(turnstile_token, client_ip):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Security verification failed. Please try again.",
                )
        elif _is_turnstile_required():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Security verification is required",
            )

    user = authenticate_user(db, payload.email.lower().strip(), payload.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated.")

    user.last_login_at = datetime.utcnow()
    db.commit()

    access_token = create_access_token(
        data={"sub": user.email},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    set_auth_cookie(request, response, access_token)

    _, organization = _get_active_enterprise_membership(db, user.id)
    _enforce_request_subdomain_matches_org(request, organization)

    context = _build_enterprise_context(db, user)
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "is_admin": user.is_admin,
        },
        **context,
    }


@router.get("/me")
def enterprise_me(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization = _get_active_enterprise_membership(db, current_user.id)
    _enforce_request_subdomain_matches_org(request, organization)
    return {
        "user": {
            "id": current_user.id,
            "email": current_user.email,
            "full_name": current_user.full_name,
            "is_admin": bool(current_user.is_admin),
            "is_developer": bool(current_user.is_developer),
        },
        **_build_enterprise_context(db, current_user),
    }


@router.post("/onboarding")
def enterprise_onboarding(
    payload: EnterpriseOnboardingRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    existing_membership, existing_org = _get_active_enterprise_membership(db, current_user.id)
    company_name = (payload.company_name or "").strip()
    if len(company_name) < 2:
        raise HTTPException(status_code=400, detail="Company name must be at least 2 characters.")
    subdomain_slug = _parse_enterprise_subdomain_or_400(payload.subdomain_slug)
    _enforce_payload_subdomain_matches_request(request, subdomain_slug)

    if existing_membership and existing_org:
        if (existing_org.subdomain_slug or "").strip():
            _enforce_request_subdomain_matches_org(request, existing_org)
            return {
                "message": "Enterprise organization already configured.",
                **_build_enterprise_context(db, current_user),
            }

        _assert_subdomain_available(
            db=db,
            subdomain_slug=subdomain_slug,
            exclude_organization_id=existing_org.id,
        )
        existing_org.company_name = company_name
        existing_org.subdomain_slug = subdomain_slug
        db.commit()
        return {
            "message": "Enterprise organization setup complete.",
            **_build_enterprise_context(db, current_user),
        }

    _assert_subdomain_available(db=db, subdomain_slug=subdomain_slug)

    organization = models.EnterpriseOrganization(
        company_name=company_name,
        subdomain_slug=subdomain_slug,
        created_by_user_id=current_user.id,
    )
    db.add(organization)
    db.flush()

    membership = models.EnterpriseOrganizationMember(
        organization_id=organization.id,
        user_id=current_user.id,
        role=ENTERPRISE_ROLE_ADMIN,
        is_active=True,
        invited_by_user_id=current_user.id,
    )
    db.add(membership)
    db.commit()

    return {
        "message": "Enterprise organization setup complete.",
        **_build_enterprise_context(db, current_user),
    }


@router.get("/team")
def enterprise_team_members(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, role = _require_enterprise_membership(db=db, user=current_user, request=request)
    members = _list_organization_members(db, organization.id)
    return {
        "organization": {
            "id": organization.id,
            "company_name": organization.company_name,
            "subdomain_slug": (organization.subdomain_slug or "").strip().lower() or None,
            "portal_url": _build_enterprise_portal_url(organization.subdomain_slug),
        },
        "current_role": role,
        "permissions": _enterprise_permissions_for_role(role),
        "members": members,
    }


@router.post("/team/users")
def enterprise_team_add_user(
    payload: EnterpriseTeamAddUserRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, _ = _require_enterprise_membership(
        db=db,
        user=current_user,
        request=request,
        require_manage_users=True,
    )

    target_email = (payload.email or "").strip().lower()
    if not target_email:
        raise HTTPException(status_code=400, detail="Email is required.")

    target_role = _parse_enterprise_role_or_400(payload.role)
    created_user = False

    user = db.query(models.User).filter(models.User.email == target_email).first()
    if not user:
        random_password = secrets.token_urlsafe(20)
        fallback_name = target_email.split("@")[0].replace(".", " ").replace("_", " ").title()
        user = models.User(
            email=target_email,
            username=None,
            hashed_password=get_password_hash(random_password),
            full_name=(payload.full_name or fallback_name or "Enterprise User").strip(),
            university=organization.company_name,
            is_active=True,
            email_verified=True,
            accepted_terms_privacy_at=datetime.utcnow(),
        )
        db.add(user)
        db.flush()
        created_user = True
    else:
        if payload.full_name and not user.full_name:
            user.full_name = payload.full_name.strip()
        if not user.is_active:
            user.is_active = True

    existing_membership = (
        db.query(models.EnterpriseOrganizationMember)
        .filter(
            models.EnterpriseOrganizationMember.organization_id == organization.id,
            models.EnterpriseOrganizationMember.user_id == user.id,
        )
        .first()
    )
    if existing_membership:
        existing_membership.is_active = True
        existing_membership.role = target_role
        existing_membership.invited_by_user_id = current_user.id
    else:
        db.add(
            models.EnterpriseOrganizationMember(
                organization_id=organization.id,
                user_id=user.id,
                role=target_role,
                is_active=True,
                invited_by_user_id=current_user.id,
            )
        )

    # Every invite issues a fresh one-time password setup link for this recipient.
    password_setup_token = generate_verification_token()
    user.password_reset_token = hash_token(password_setup_token)
    user.password_reset_token_expires = datetime.utcnow() + timedelta(
        hours=ENTERPRISE_INVITE_PASSWORD_SETUP_EXPIRES_HOURS
    )

    db.commit()

    portal_url = _build_enterprise_portal_url(organization.subdomain_slug)
    password_setup_url = (
        f"{ENTERPRISE_PASSWORD_SETUP_BASE_URL}/reset-password"
        f"?token={quote(password_setup_token, safe='')}"
    )
    invite_email_sent = False
    try:
        invite_email_sent = send_enterprise_team_invite_email(
            invitee_email=target_email,
            invitee_name=user.full_name,
            organization_name=organization.company_name,
            role=target_role,
            portal_url=portal_url,
            set_password_url=password_setup_url,
            password_setup_expires_hours=ENTERPRISE_INVITE_PASSWORD_SETUP_EXPIRES_HOURS,
            invited_by_name=current_user.full_name,
            invited_by_email=current_user.email,
        )
    except Exception:
        logger.exception(
            "Failed to send enterprise invite email (org_id=%s, invitee=%s)",
            organization.id,
            target_email,
        )

    base_message = (
        "User added to organization."
        if not created_user
        else "User account created and added to organization."
    )
    if invite_email_sent:
        response_message = f"{base_message} Invitation email sent."
    else:
        response_message = (
            f"{base_message} Invite email could not be sent right now. "
            "Ask the user to request a fresh password setup link from the login screen."
        )

    return {
        "message": response_message,
        "created_user": created_user,
        "invite_email_sent": invite_email_sent,
        "invite_email_to": target_email,
        "organization_portal_url": portal_url,
        "members": _list_organization_members(db, organization.id),
    }


@router.patch("/team/users/{member_user_id}/role")
def enterprise_team_update_role(
    member_user_id: int,
    payload: EnterpriseTeamRoleUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, _ = _require_enterprise_membership(
        db=db,
        user=current_user,
        request=request,
        require_manage_users=True,
    )

    target_role = _parse_enterprise_role_or_400(payload.role)
    membership = (
        db.query(models.EnterpriseOrganizationMember)
        .filter(
            models.EnterpriseOrganizationMember.organization_id == organization.id,
            models.EnterpriseOrganizationMember.user_id == int(member_user_id),
            models.EnterpriseOrganizationMember.is_active.is_(True),
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=404, detail="Organization member not found.")

    current_target_role = _normalize_enterprise_role(membership.role)
    if current_target_role == ENTERPRISE_ROLE_ADMIN and target_role != ENTERPRISE_ROLE_ADMIN:
        if _active_admin_count(db, organization.id) <= 1:
            raise HTTPException(
                status_code=400,
                detail="At least one active admin is required for the organization.",
            )
    if int(member_user_id) == current_user.id and target_role != ENTERPRISE_ROLE_ADMIN:
        raise HTTPException(
            status_code=400,
            detail="You cannot demote your own account from admin.",
        )

    membership.role = target_role
    db.commit()
    return {
        "message": "Role updated successfully.",
        "members": _list_organization_members(db, organization.id),
    }


@router.delete("/team/users/{member_user_id}")
def enterprise_team_remove_user(
    member_user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, _ = _require_enterprise_membership(
        db=db,
        user=current_user,
        request=request,
        require_manage_users=True,
    )

    if int(member_user_id) == current_user.id:
        raise HTTPException(status_code=400, detail="You cannot remove your own account.")

    membership = (
        db.query(models.EnterpriseOrganizationMember)
        .filter(
            models.EnterpriseOrganizationMember.organization_id == organization.id,
            models.EnterpriseOrganizationMember.user_id == int(member_user_id),
            models.EnterpriseOrganizationMember.is_active.is_(True),
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=404, detail="Organization member not found.")

    if _normalize_enterprise_role(membership.role) == ENTERPRISE_ROLE_ADMIN:
        if _active_admin_count(db, organization.id) <= 1:
            raise HTTPException(
                status_code=400,
                detail="At least one active admin is required for the organization.",
            )

    membership.is_active = False
    db.commit()
    return {
        "message": "User removed from organization.",
        "members": _list_organization_members(db, organization.id),
    }
