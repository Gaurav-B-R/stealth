import os
import re
import hmac
import uuid
import secrets
import logging
import hashlib
import threading
from typing import Optional
from urllib.parse import quote, urlparse

import requests
from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Request, Response, UploadFile, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session
from datetime import timedelta, datetime, date
from pydantic import BaseModel, EmailStr, Field

from app.database import get_db, SessionLocal
from app import models
from app import enterprise_catalog as catalog
from app import enterprise_billing as billing
from app import enterprise_ai
from app import enterprise_storage
from app.utils import gemini_service
from app.auth import (
    authenticate_user,
    create_access_token,
    get_current_active_user,
    get_password_hash,
    validate_password_strength,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    set_auth_cookie,
)
from app.utils.rate_limiter import (
    check_ip_rate_limit,
    extract_client_ip,
    is_request_ip_whitelisted,
)
from app.utils.turnstile import is_turnstile_enabled, verify_turnstile_token
from app.email_service import send_enterprise_team_invite_email, send_enterprise_client_email
from app.email_service import generate_verification_token, DEFAULT_PUBLIC_BASE_URL
from app.utils.token_security import hash_token

RAZORPAY_API_BASE = os.getenv("RAZORPAY_API_BASE", "https://api.razorpay.com/v1").rstrip("/")

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
ENTERPRISE_PORTAL_PORT = os.getenv("ENTERPRISE_PORTAL_PORT", "").strip().lstrip(":")
ENTERPRISE_GENERIC_SUBDOMAINS = {
    item.strip().lower()
    for item in os.getenv("ENTERPRISE_GENERIC_SUBDOMAINS", "enterprise,portal").split(",")
    if item.strip()
}
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
ENTERPRISE_TEAM_INVITE_RATE_LIMIT = int(os.getenv("ENTERPRISE_TEAM_INVITE_RATE_LIMIT", "20"))
ENTERPRISE_TEAM_INVITE_RATE_WINDOW_SECONDS = int(os.getenv("ENTERPRISE_TEAM_INVITE_RATE_WINDOW_SECONDS", "3600"))
ENTERPRISE_CLIENT_EMAIL_RATE_LIMIT = int(os.getenv("ENTERPRISE_CLIENT_EMAIL_RATE_LIMIT", "60"))
ENTERPRISE_CLIENT_EMAIL_RATE_WINDOW_SECONDS = int(os.getenv("ENTERPRISE_CLIENT_EMAIL_RATE_WINDOW_SECONDS", "3600"))
ENTERPRISE_BULK_EMAIL_RATE_LIMIT = int(os.getenv("ENTERPRISE_BULK_EMAIL_RATE_LIMIT", "10"))
ENTERPRISE_BULK_EMAIL_RATE_WINDOW_SECONDS = int(os.getenv("ENTERPRISE_BULK_EMAIL_RATE_WINDOW_SECONDS", "3600"))
ENTERPRISE_INVITE_ONLY_DETAIL = (
    "Enterprise access is invite-only. Request access via Contact Sales."
)
ENTERPRISE_LOGO_URL_MAX_LENGTH = 2048
ENTERPRISE_STUDENT_NAME_MAX_LENGTH = 160
ENTERPRISE_STUDY_COUNTRY_CODE_MAX_LENGTH = 12
ENTERPRISE_STUDY_COUNTRY_NAME_MAX_LENGTH = 120
ENTERPRISE_VISA_TYPE_MAX_LENGTH = 120
ENTERPRISE_INTAKE_MAX_LENGTH = 120
ENTERPRISE_STUDY_DESTINATION_OPTIONS = [
    {
        "code": "US",
        "name": "United States",
        "flag_emoji": "🇺🇸",
        "iconic_place": "Statue of Liberty",
        "visa_types": [
            "F-1 Student Visa",
            "J-1 Exchange Visitor Visa",
            "M-1 Vocational Student Visa",
        ],
        "intakes_by_visa": {
            "F-1 Student Visa": ["Spring", "Summer", "Fall"],
            "J-1 Exchange Visitor Visa": ["Spring", "Fall"],
            "M-1 Vocational Student Visa": ["Spring", "Summer", "Fall"],
        },
    },
    {
        "code": "CA",
        "name": "Canada",
        "flag_emoji": "🇨🇦",
        "iconic_place": "Niagara Falls",
        "visa_types": [
            "Study Permit",
            "Student Direct Stream (SDS)",
        ],
        "intakes_by_visa": {
            "Study Permit": ["January", "May", "September"],
            "Student Direct Stream (SDS)": ["January", "May", "September"],
        },
    },
    {
        "code": "UK",
        "name": "United Kingdom",
        "flag_emoji": "🇬🇧",
        "iconic_place": "Big Ben",
        "visa_types": [
            "UK Student Visa",
            "Child Student Visa",
        ],
        "intakes_by_visa": {
            "UK Student Visa": ["January", "September"],
            "Child Student Visa": ["January", "September"],
        },
    },
    {
        "code": "AU",
        "name": "Australia",
        "flag_emoji": "🇦🇺",
        "iconic_place": "Sydney Opera House",
        "visa_types": [
            "Subclass 500 Student Visa",
            "Subclass 590 Student Guardian Visa",
        ],
        "intakes_by_visa": {
            "Subclass 500 Student Visa": ["February", "July", "November"],
            "Subclass 590 Student Guardian Visa": ["February", "July", "November"],
        },
    },
    {
        "code": "DE",
        "name": "Germany",
        "flag_emoji": "🇩🇪",
        "iconic_place": "Brandenburg Gate",
        "visa_types": [
            "National Visa (Type D) - Study",
            "Student Applicant Visa",
        ],
        "intakes_by_visa": {
            "National Visa (Type D) - Study": ["Summer Semester", "Winter Semester"],
            "Student Applicant Visa": ["Summer Semester", "Winter Semester"],
        },
    },
    {
        "code": "FR",
        "name": "France",
        "flag_emoji": "🇫🇷",
        "iconic_place": "Eiffel Tower",
        "visa_types": [
            "Long-Stay Student Visa (VLS-TS)",
        ],
        "intakes_by_visa": {
            "Long-Stay Student Visa (VLS-TS)": ["September", "January"],
        },
    },
    {
        "code": "IE",
        "name": "Ireland",
        "flag_emoji": "🇮🇪",
        "iconic_place": "Cliffs of Moher",
        "visa_types": [
            "D Study Visa",
        ],
        "intakes_by_visa": {
            "D Study Visa": ["January", "September"],
        },
    },
    {
        "code": "NZ",
        "name": "New Zealand",
        "flag_emoji": "🇳🇿",
        "iconic_place": "Milford Sound",
        "visa_types": [
            "Fee Paying Student Visa",
        ],
        "intakes_by_visa": {
            "Fee Paying Student Visa": ["February", "July"],
        },
    },
]
ENTERPRISE_STUDY_DESTINATION_MAP = {
    str(item["code"]).strip().upper(): item for item in ENTERPRISE_STUDY_DESTINATION_OPTIONS
}
ENTERPRISE_INTAKE_START_MONTH_HINTS = {
    "spring": 1,
    "summer": 5,
    "fall": 8,
    "winter": 11,
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
    "summer semester": 4,
    "winter semester": 10,
}


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


class EnterpriseBrandingUpdateRequest(BaseModel):
    company_name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    logo_url: Optional[str] = Field(default=None, max_length=ENTERPRISE_LOGO_URL_MAX_LENGTH)
    generate_random_logo: bool = False


class EnterpriseStudentCreateRequest(BaseModel):
    student_name: str = Field(..., min_length=2, max_length=ENTERPRISE_STUDENT_NAME_MAX_LENGTH)
    study_country_code: str = Field(..., min_length=2, max_length=ENTERPRISE_STUDY_COUNTRY_CODE_MAX_LENGTH)
    visa_type: str = Field(..., min_length=2, max_length=ENTERPRISE_VISA_TYPE_MAX_LENGTH)
    intake: str = Field(..., min_length=2, max_length=ENTERPRISE_INTAKE_MAX_LENGTH)


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


def _build_default_enterprise_logo_url(
    *,
    organization_id: int | None,
    company_name: str | None,
    subdomain_slug: str | None,
    randomize: bool = False,
) -> str:
    seed_parts = [
        f"org-{int(organization_id)}" if organization_id is not None else "org-pending",
        (company_name or "").strip().lower(),
        (subdomain_slug or "").strip().lower(),
    ]
    if randomize:
        seed_parts.append(secrets.token_hex(6))
    seed_source = "|".join(seed_parts)
    seed_hash = hashlib.sha256(seed_source.encode("utf-8")).hexdigest()[:20]
    return f"https://picsum.photos/seed/rilono-org-{seed_hash}/256/256"


def _normalize_enterprise_logo_url_or_400(raw_logo_url: str | None) -> str | None:
    value = str(raw_logo_url or "").strip()
    if not value:
        return None
    if len(value) > ENTERPRISE_LOGO_URL_MAX_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Logo URL must be at most {ENTERPRISE_LOGO_URL_MAX_LENGTH} characters.",
        )

    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(
            status_code=400,
            detail="Logo URL must start with http:// or https://",
        )
    return value


def _resolve_enterprise_logo_url(organization: models.EnterpriseOrganization) -> str:
    raw_logo = str(getattr(organization, "logo_url", "") or "").strip()
    if raw_logo:
        parsed = urlparse(raw_logo)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return raw_logo

    return _build_default_enterprise_logo_url(
        organization_id=getattr(organization, "id", None),
        company_name=getattr(organization, "company_name", None),
        subdomain_slug=getattr(organization, "subdomain_slug", None),
        randomize=False,
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


def _is_development_env() -> bool:
    return os.getenv("ENVIRONMENT", "production").strip().lower() == "development"


def _request_port_for_local_enterprise_url(request: Request | None) -> str | None:
    if ENTERPRISE_PORTAL_PORT:
        return ENTERPRISE_PORTAL_PORT
    if not request or not _is_development_env():
        return None
    port = request.url.port
    if not port or int(port) in {80, 443}:
        return None
    return str(port)


def _build_enterprise_portal_url(
    subdomain_slug: str | None,
    request: Request | None = None,
) -> str | None:
    subdomain = str(subdomain_slug or "").strip().lower()
    if not subdomain:
        return None
    host = f"{subdomain}.{ENTERPRISE_ROOT_DOMAIN}"
    port = _request_port_for_local_enterprise_url(request)
    if port:
        host = f"{host}:{port}"
    return f"{ENTERPRISE_PORTAL_SCHEME}://{host}/enterprise"


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
    if subdomain_part in ENTERPRISE_GENERIC_SUBDOMAINS:
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
            detail=f"Use your organization URL: {_build_enterprise_portal_url(org_subdomain, request)}",
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


def _has_enterprise_access(db: Session, user: models.User) -> bool:
    email = (user.email or "").strip().lower()
    if not email:
        return False
    credential = (
        db.query(models.EnterpriseCredential.id)
        .filter(
            models.EnterpriseCredential.email == email,
            models.EnterpriseCredential.is_active.is_(True),
        )
        .first()
    )
    if credential:
        return True

    if user.id is None:
        return False

    membership = (
        db.query(models.EnterpriseOrganizationMember.id)
        .filter(
            models.EnterpriseOrganizationMember.user_id == int(user.id),
            models.EnterpriseOrganizationMember.is_active.is_(True),
        )
        .first()
    )
    return bool(membership)


def _enforce_enterprise_access_or_403(db: Session, user: models.User) -> None:
    if _has_enterprise_access(db, user):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=ENTERPRISE_INVITE_ONLY_DETAIL,
    )


def _build_enterprise_context(
    db: Session,
    user: models.User,
    request: Request | None = None,
) -> dict:
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
    logo_url = _resolve_enterprise_logo_url(organization)
    onboarding_required = not company_name or not subdomain_slug

    subscription_summary = None
    if not onboarding_required:
        try:
            subscription_summary = _serialize_subscription_state(
                billing.build_subscription_state(db, organization.id)
            )
        except Exception:
            logger.exception("Failed to build subscription state for org_id=%s", organization.id)

    return {
        "onboarding_required": onboarding_required,
        "organization": {
            "id": organization.id,
            "company_name": company_name or organization.company_name,
            "subdomain_slug": subdomain_slug or None,
            "logo_url": logo_url,
            "portal_url": _build_enterprise_portal_url(subdomain_slug, request),
            "created_at": organization.created_at,
        },
        "membership": {
            "role": normalized_role,
            "is_active": bool(membership.is_active),
            "joined_at": membership.created_at,
        },
        "subscription": subscription_summary,
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
    require_edit_data: bool = False,
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
    if require_edit_data and role not in {ENTERPRISE_ROLE_ADMIN, ENTERPRISE_ROLE_EDITOR}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins or editors can modify student records.",
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


def _enterprise_student_options_payload() -> dict:
    return {
        "countries": [
            {
                "code": item["code"],
                "name": item["name"],
                "flag_emoji": str(item.get("flag_emoji") or "").strip(),
                "iconic_place": str(item.get("iconic_place") or "").strip(),
                "visa_types": list(item["visa_types"]),
                "intakes_by_visa": {
                    str(visa_name): _materialize_future_intakes(intakes or [])
                    for visa_name, intakes in (item.get("intakes_by_visa") or {}).items()
                },
            }
            for item in ENTERPRISE_STUDY_DESTINATION_OPTIONS
        ]
    }


def _resolve_intake_start_month(intake_label: str) -> int:
    normalized = str(intake_label or "").strip().lower()
    if not normalized:
        return 9
    if normalized in ENTERPRISE_INTAKE_START_MONTH_HINTS:
        return int(ENTERPRISE_INTAKE_START_MONTH_HINTS[normalized])

    for key, month in ENTERPRISE_INTAKE_START_MONTH_HINTS.items():
        if key in normalized:
            return int(month)
    return 9


def _materialize_future_intakes(intake_labels: list[str]) -> list[str]:
    now_utc = datetime.utcnow()
    current_month = int(now_utc.month)
    current_year = int(now_utc.year)
    sortable_results: list[tuple[int, int, str, str]] = []
    seen: set[str] = set()

    for raw_label in intake_labels:
        base_label = str(raw_label or "").strip()
        if not base_label:
            continue
        start_month = _resolve_intake_start_month(base_label)
        year = current_year if start_month > current_month else (current_year + 1)
        future_label = f"{base_label} {year}"
        dedupe_key = future_label.lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        sortable_results.append((year, start_month, base_label.lower(), future_label))

    sortable_results.sort(key=lambda item: (item[0], item[1], item[2]))
    return [item[3] for item in sortable_results]


def _parse_enterprise_student_payload_or_400(
    payload: EnterpriseStudentCreateRequest,
) -> tuple[str, str, str, str, str]:
    student_name = str(payload.student_name or "").strip()
    if len(student_name) < 2:
        raise HTTPException(status_code=400, detail="Student name must be at least 2 characters.")
    if len(student_name) > ENTERPRISE_STUDENT_NAME_MAX_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Student name must be at most {ENTERPRISE_STUDENT_NAME_MAX_LENGTH} characters.",
        )

    study_country_code = str(payload.study_country_code or "").strip().upper()
    country_meta = ENTERPRISE_STUDY_DESTINATION_MAP.get(study_country_code)
    if not country_meta:
        raise HTTPException(status_code=400, detail="Please select a valid study destination country.")

    visa_type_input = str(payload.visa_type or "").strip()
    if not visa_type_input:
        raise HTTPException(status_code=400, detail="Please select a visa type.")

    canonical_visa_type = ""
    for visa_option in country_meta["visa_types"]:
        if str(visa_option).strip().lower() == visa_type_input.lower():
            canonical_visa_type = str(visa_option).strip()
            break
    if not canonical_visa_type:
        raise HTTPException(
            status_code=400,
            detail="Selected visa type does not match the selected study destination.",
        )

    intake_input = str(payload.intake or "").strip()
    if not intake_input:
        raise HTTPException(status_code=400, detail="Please select an intake.")

    intakes_by_visa = country_meta.get("intakes_by_visa") or {}
    allowed_base_intakes = list(intakes_by_visa.get(canonical_visa_type) or [])
    allowed_intakes = _materialize_future_intakes(allowed_base_intakes)
    canonical_intake = ""
    for intake_option in allowed_intakes:
        if str(intake_option).strip().lower() == intake_input.lower():
            canonical_intake = str(intake_option).strip()
            break
    if not canonical_intake:
        for raw_base_intake in allowed_base_intakes:
            base_intake = str(raw_base_intake).strip()
            if base_intake and base_intake.lower() == intake_input.lower():
                canonical_list = _materialize_future_intakes([base_intake])
                canonical_intake = canonical_list[0] if canonical_list else base_intake
                break
    if not canonical_intake:
        raise HTTPException(
            status_code=400,
            detail="Selected intake does not match the selected country and visa type.",
        )

    return (
        student_name,
        study_country_code,
        str(country_meta["name"]).strip(),
        canonical_visa_type,
        canonical_intake,
    )


def _serialize_enterprise_student(student: models.EnterpriseStudent) -> dict:
    return {
        "id": student.id,
        "student_name": student.student_name,
        "study_country_code": student.study_country_code,
        "study_country_name": student.study_country_name,
        "visa_type": student.visa_type,
        "intake": student.intake,
        "created_at": student.created_at,
    }


def _list_enterprise_students(db: Session, organization_id: int) -> list[dict]:
    rows = (
        db.query(models.EnterpriseStudent)
        .filter(models.EnterpriseStudent.organization_id == int(organization_id))
        .order_by(models.EnterpriseStudent.created_at.desc(), models.EnterpriseStudent.id.desc())
        .all()
    )
    return [_serialize_enterprise_student(item) for item in rows]


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

    login_email = payload.email.lower().strip()
    candidate_user = db.query(models.User).filter(models.User.email == login_email).first()
    if not candidate_user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ENTERPRISE_INVITE_ONLY_DETAIL,
        )

    _enforce_enterprise_access_or_403(db, candidate_user)

    user = authenticate_user(db, login_email, payload.password)
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

    context = _build_enterprise_context(db, user, request)
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
    _enforce_enterprise_access_or_403(db, current_user)
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
        **_build_enterprise_context(db, current_user, request),
    }


@router.get("/students/options")
def enterprise_student_options(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, role = _require_enterprise_membership(db=db, user=current_user, request=request)
    return {
        "organization_id": organization.id,
        "permissions": _enterprise_permissions_for_role(role),
        "options": _enterprise_student_options_payload(),
    }


@router.get("/students")
def enterprise_students(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, role = _require_enterprise_membership(db=db, user=current_user, request=request)
    students = _list_enterprise_students(db, organization.id)
    return {
        "organization_id": organization.id,
        "permissions": _enterprise_permissions_for_role(role),
        "students_count": len(students),
        "students": students,
    }


@router.post("/students")
def enterprise_add_student(
    payload: EnterpriseStudentCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, role = _require_enterprise_membership(
        db=db,
        user=current_user,
        request=request,
        require_edit_data=True,
    )
    student_name, study_country_code, study_country_name, visa_type, intake = _parse_enterprise_student_payload_or_400(payload)

    student = models.EnterpriseStudent(
        organization_id=organization.id,
        student_name=student_name,
        study_country_code=study_country_code,
        study_country_name=study_country_name,
        visa_type=visa_type,
        intake=intake,
        created_by_user_id=current_user.id,
    )
    db.add(student)
    db.commit()
    db.refresh(student)

    students_count = int(
        db.query(models.EnterpriseStudent)
        .filter(models.EnterpriseStudent.organization_id == int(organization.id))
        .count()
    )

    return {
        "message": "Student added successfully.",
        "permissions": _enterprise_permissions_for_role(role),
        "students_count": students_count,
        "student": _serialize_enterprise_student(student),
    }


@router.post("/onboarding")
def enterprise_onboarding(
    payload: EnterpriseOnboardingRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _enforce_enterprise_access_or_403(db, current_user)
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
                **_build_enterprise_context(db, current_user, request),
            }

        _assert_subdomain_available(
            db=db,
            subdomain_slug=subdomain_slug,
            exclude_organization_id=existing_org.id,
        )
        existing_org.company_name = company_name
        existing_org.subdomain_slug = subdomain_slug
        if not str(existing_org.logo_url or "").strip():
            existing_org.logo_url = _build_default_enterprise_logo_url(
                organization_id=existing_org.id,
                company_name=company_name,
                subdomain_slug=subdomain_slug,
                randomize=True,
            )
        db.commit()
        return {
            "message": "Enterprise organization setup complete.",
            **_build_enterprise_context(db, current_user, request),
        }

    _assert_subdomain_available(db=db, subdomain_slug=subdomain_slug)

    organization = models.EnterpriseOrganization(
        company_name=company_name,
        subdomain_slug=subdomain_slug,
        logo_url=_build_default_enterprise_logo_url(
            organization_id=None,
            company_name=company_name,
            subdomain_slug=subdomain_slug,
            randomize=True,
        ),
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
        **_build_enterprise_context(db, current_user, request),
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
            "logo_url": _resolve_enterprise_logo_url(organization),
            "portal_url": _build_enterprise_portal_url(organization.subdomain_slug, request),
        },
        "current_role": role,
        "permissions": _enterprise_permissions_for_role(role),
        "members": members,
    }


@router.patch("/organization/branding")
def enterprise_update_branding(
    payload: EnterpriseBrandingUpdateRequest,
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

    has_update = False
    new_company_name: str | None = None
    if payload.company_name is not None:
        new_company_name = (payload.company_name or "").strip()
        if len(new_company_name) < 2:
            raise HTTPException(status_code=400, detail="Company name must be at least 2 characters.")
        has_update = True

    if payload.generate_random_logo:
        organization.logo_url = _build_default_enterprise_logo_url(
            organization_id=organization.id,
            company_name=new_company_name or organization.company_name,
            subdomain_slug=organization.subdomain_slug,
            randomize=True,
        )
        has_update = True
    elif payload.logo_url is not None:
        normalized_logo = _normalize_enterprise_logo_url_or_400(payload.logo_url)
        if normalized_logo:
            organization.logo_url = normalized_logo
        else:
            organization.logo_url = _build_default_enterprise_logo_url(
                organization_id=organization.id,
                company_name=new_company_name or organization.company_name,
                subdomain_slug=organization.subdomain_slug,
                randomize=True,
            )
        has_update = True

    if new_company_name is not None:
        organization.company_name = new_company_name

    if not has_update:
        raise HTTPException(status_code=400, detail="Nothing to update.")

    db.commit()

    context = _build_enterprise_context(db, current_user, request)
    return {
        "message": "Organization branding updated successfully.",
        "organization": context.get("organization"),
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
    _enforce_rate_limit_or_429(
        request=request,
        scope="enterprise.team_invite",
        limit=ENTERPRISE_TEAM_INVITE_RATE_LIMIT,
        window_seconds=ENTERPRISE_TEAM_INVITE_RATE_WINDOW_SECONDS,
        extra_key=f"org:{organization.id}:user:{current_user.id}",
    )

    target_email = (payload.email or "").strip().lower()
    if not target_email:
        raise HTTPException(status_code=400, detail="Email is required.")

    target_role = _parse_enterprise_role_or_400(payload.role)

    user = db.query(models.User).filter(models.User.email == target_email).first()

    # Pre-check the seat limit when this invite would consume a NEW active seat.
    existing_membership = None
    if user:
        existing_membership = (
            db.query(models.EnterpriseOrganizationMember)
            .filter(
                models.EnterpriseOrganizationMember.organization_id == organization.id,
                models.EnterpriseOrganizationMember.user_id == user.id,
            )
            .first()
        )
    consumes_new_seat = not (existing_membership and existing_membership.is_active)
    if consumes_new_seat:
        billing.enforce_seat_limit_or_402(db, organization.id)

    created_user = False
    if not user:
        # The invitee sets their own password via the emailed one-time link, so we
        # seed a random unusable hash. Access is granted by their org membership.
        fallback_name = target_email.split("@")[0].replace(".", " ").replace("_", " ").title()
        user = models.User(
            email=target_email,
            username=None,
            hashed_password=get_password_hash(secrets.token_urlsafe(24)),
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

    portal_url = _build_enterprise_portal_url(organization.subdomain_slug, request)
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


# ===========================================================================
# CRM: catalog, clients, notes, client emails, dashboard
# ===========================================================================

ENTERPRISE_CLIENT_NAME_MAX = 160
ENTERPRISE_NOTE_MAX = 5000
ENTERPRISE_EMAIL_SUBJECT_MAX = 200
ENTERPRISE_EMAIL_BODY_MAX = 20000
ENTERPRISE_SIGNUP_RATE_LIMIT = int(os.getenv("ENTERPRISE_SIGNUP_RATE_LIMIT", "6"))
ENTERPRISE_SIGNUP_RATE_WINDOW_SECONDS = int(os.getenv("ENTERPRISE_SIGNUP_RATE_WINDOW_SECONDS", "900"))
ENTERPRISE_BULK_EMAIL_MAX_RECIPIENTS = int(os.getenv("ENTERPRISE_BULK_EMAIL_MAX_RECIPIENTS", "200"))


class EnterpriseSignupRequest(BaseModel):
    company_name: str = Field(..., min_length=2, max_length=120)
    subdomain_slug: str = Field(
        ...,
        min_length=ENTERPRISE_SUBDOMAIN_MIN_LENGTH,
        max_length=ENTERPRISE_SUBDOMAIN_MAX_LENGTH,
    )
    full_name: str = Field(..., min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=200)
    cf_turnstile_token: Optional[str] = None


class EnterpriseClientCreateRequest(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=ENTERPRISE_CLIENT_NAME_MAX)
    visa_category: Optional[str] = Field(default="student", max_length=40)
    destination_country_code: str = Field(..., min_length=2, max_length=12)
    visa_type: str = Field(..., min_length=2, max_length=160)
    intake: Optional[str] = Field(default=None, max_length=120)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(default=None, max_length=40)
    nationality: Optional[str] = Field(default=None, max_length=80)
    date_of_birth: Optional[str] = Field(default=None, max_length=20)
    passport_number: Optional[str] = Field(default=None, max_length=60)
    passport_expiry: Optional[str] = Field(default=None, max_length=20)
    priority: Optional[str] = Field(default=None, max_length=20)
    status: Optional[str] = Field(default=None, max_length=30)
    target_date: Optional[str] = Field(default=None, max_length=20)
    application_reference: Optional[str] = Field(default=None, max_length=120)
    assigned_to_user_id: Optional[int] = None
    initial_note: Optional[str] = Field(default=None, max_length=ENTERPRISE_NOTE_MAX)


class EnterpriseClientUpdateRequest(BaseModel):
    full_name: Optional[str] = Field(default=None, min_length=2, max_length=ENTERPRISE_CLIENT_NAME_MAX)
    visa_category: Optional[str] = Field(default=None, max_length=40)
    destination_country_code: Optional[str] = Field(default=None, max_length=12)
    visa_type: Optional[str] = Field(default=None, max_length=160)
    intake: Optional[str] = Field(default=None, max_length=120)
    email: Optional[str] = Field(default=None, max_length=200)
    phone: Optional[str] = Field(default=None, max_length=40)
    nationality: Optional[str] = Field(default=None, max_length=80)
    date_of_birth: Optional[str] = Field(default=None, max_length=20)
    passport_number: Optional[str] = Field(default=None, max_length=60)
    passport_expiry: Optional[str] = Field(default=None, max_length=20)
    priority: Optional[str] = Field(default=None, max_length=20)
    status: Optional[str] = Field(default=None, max_length=30)
    target_date: Optional[str] = Field(default=None, max_length=20)
    application_reference: Optional[str] = Field(default=None, max_length=120)
    assigned_to_user_id: Optional[int] = None


class EnterpriseClientStatusRequest(BaseModel):
    status: str = Field(..., min_length=2, max_length=30)


class EnterpriseClientNoteRequest(BaseModel):
    body: str = Field(..., min_length=1, max_length=ENTERPRISE_NOTE_MAX)


class EnterpriseClientEmailRequest(BaseModel):
    subject: str = Field(..., min_length=1, max_length=ENTERPRISE_EMAIL_SUBJECT_MAX)
    body: str = Field(..., min_length=1, max_length=ENTERPRISE_EMAIL_BODY_MAX)


class EnterpriseBulkEmailRequest(BaseModel):
    client_ids: list[int] = Field(..., min_length=1)
    subject: str = Field(..., min_length=1, max_length=ENTERPRISE_EMAIL_SUBJECT_MAX)
    body: str = Field(..., min_length=1, max_length=ENTERPRISE_EMAIL_BODY_MAX)


class EnterpriseBillingCheckoutRequest(BaseModel):
    plan: str = Field(..., min_length=2, max_length=30)
    billing_cycle: str = Field(default="monthly", max_length=12)


class EnterpriseBillingVerifyRequest(BaseModel):
    razorpay_order_id: str = Field(..., min_length=6, max_length=64)
    razorpay_payment_id: str = Field(..., min_length=6, max_length=64)
    razorpay_signature: str = Field(..., min_length=6, max_length=256)


def _parse_iso_date_or_400(value: Optional[str], field_label: str) -> Optional[date]:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw[:10], "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{field_label} must be a valid date (YYYY-MM-DD).")


def _serialize_subscription_state(state: dict) -> dict:
    return {
        "plan": state["plan"],
        "plan_label": state["plan_label"],
        "status": state["status"],
        "is_trial": state["is_trial"],
        "trial_expired": state["trial_expired"],
        "trial_days_left": state["trial_days_left"],
        "trial_ends_at": state["trial_ends_at"],
        "current_period_end": state["current_period_end"],
        "max_clients": state["max_clients"],
        "max_seats": state["max_seats"],
        "clients_used": state["clients_used"],
        "seats_used": state["seats_used"],
        "can_add_client": state["can_add_client"],
        "can_add_seat": state["can_add_seat"],
    }


def _country_brief(country_code: str | None) -> dict:
    country = catalog.get_country(country_code)
    if not country:
        return {
            "code": str(country_code or "").upper(),
            "name": str(country_code or "").upper(),
            "flag_emoji": "🌐",
            "landmark": "",
            "gradient_from": "#6366f1",
            "gradient_to": "#8b5cf6",
            "accent": "#eef2ff",
        }
    return {
        "code": country["code"],
        "name": country["name"],
        "flag_emoji": country["flag_emoji"],
        "landmark": country["landmark"],
        "gradient_from": country["gradient_from"],
        "gradient_to": country["gradient_to"],
        "accent": country["accent"],
    }


def _stage_brief(status_key: str | None) -> dict:
    stage = catalog.CLIENT_STAGE_MAP.get(catalog.normalize_stage(status_key))
    return {
        "key": stage["key"],
        "label": stage["label"],
        "color": stage["color"],
        "is_open": stage["is_open"],
        "is_terminal": stage["is_terminal"],
    }


def _category_label(category_key: str | None) -> str:
    item = catalog.VISA_CATEGORY_MAP.get(str(category_key or "").strip().lower())
    return item["label"] if item else str(category_key or "").title()


def _org_member_name_map(db: Session, organization_id: int) -> dict[int, str]:
    rows = (
        db.query(models.EnterpriseOrganizationMember.user_id, models.User.full_name, models.User.email)
        .join(models.User, models.User.id == models.EnterpriseOrganizationMember.user_id)
        .filter(
            models.EnterpriseOrganizationMember.organization_id == int(organization_id),
            models.EnterpriseOrganizationMember.is_active.is_(True),
        )
        .all()
    )
    return {int(uid): (full_name or email or "Team member") for uid, full_name, email in rows}


def _is_active_org_member(db: Session, organization_id: int, user_id: int) -> bool:
    return bool(
        db.query(models.EnterpriseOrganizationMember.id)
        .filter(
            models.EnterpriseOrganizationMember.organization_id == int(organization_id),
            models.EnterpriseOrganizationMember.user_id == int(user_id),
            models.EnterpriseOrganizationMember.is_active.is_(True),
        )
        .first()
    )


def _iso(value) -> Optional[str]:
    if value is None:
        return None
    try:
        return value.isoformat()
    except Exception:
        return str(value)


def _serialize_client(client: models.EnterpriseClient, member_names: dict[int, str] | None = None) -> dict:
    assigned_name = None
    if client.assigned_to_user_id and member_names is not None:
        assigned_name = member_names.get(int(client.assigned_to_user_id))
    return {
        "id": client.id,
        "full_name": client.full_name,
        "email": client.email,
        "phone": client.phone,
        "nationality": client.nationality,
        "date_of_birth": _iso(client.date_of_birth),
        "passport_number": client.passport_number,
        "passport_expiry": _iso(client.passport_expiry),
        "visa_category": client.visa_category,
        "visa_category_label": _category_label(client.visa_category),
        "destination_country_code": client.destination_country_code,
        "destination_country_name": client.destination_country_name,
        "country": _country_brief(client.destination_country_code),
        "visa_type": client.visa_type,
        "intake": client.intake,
        "application_reference": client.application_reference,
        "status": client.status,
        "stage": _stage_brief(client.status),
        "priority": client.priority,
        "target_date": _iso(client.target_date),
        "assigned_to_user_id": client.assigned_to_user_id,
        "assigned_to_name": assigned_name,
        "created_at": _iso(client.created_at),
        "updated_at": _iso(client.updated_at),
    }


def _serialize_note(note: models.EnterpriseClientNote) -> dict:
    return {
        "id": note.id,
        "client_id": note.client_id,
        "author_user_id": note.author_user_id,
        "author_name": note.author_name,
        "body": note.body,
        "created_at": _iso(note.created_at),
    }


def _serialize_client_email(row: models.EnterpriseClientEmail) -> dict:
    return {
        "id": row.id,
        "client_id": row.client_id,
        "to_email": row.to_email,
        "subject": row.subject,
        "body": row.body,
        "status": row.status,
        "sent_by_name": row.sent_by_name,
        "error_message": row.error_message,
        "created_at": _iso(row.created_at),
    }


def _get_org_client_or_404(db: Session, organization_id: int, client_id: int) -> models.EnterpriseClient:
    client = (
        db.query(models.EnterpriseClient)
        .filter(
            models.EnterpriseClient.id == int(client_id),
            models.EnterpriseClient.organization_id == int(organization_id),
        )
        .first()
    )
    if not client:
        raise HTTPException(status_code=404, detail="Client not found.")
    return client


@router.get("/catalog")
def enterprise_catalog(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _require_enterprise_membership(db=db, user=current_user, request=request)
    return catalog.build_catalog_payload()


@router.get("/clients")
def enterprise_list_clients(
    request: Request,
    status_filter: Optional[str] = None,
    category: Optional[str] = None,
    country: Optional[str] = None,
    assigned_to: Optional[int] = None,
    q: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, role = _require_enterprise_membership(db=db, user=current_user, request=request)

    base = db.query(models.EnterpriseClient).filter(
        models.EnterpriseClient.organization_id == organization.id
    )

    query = base
    if status_filter and status_filter in catalog.CLIENT_STAGE_KEYS:
        query = query.filter(models.EnterpriseClient.status == status_filter)
    normalized_category = catalog.normalize_category(category) if category else None
    if normalized_category:
        query = query.filter(models.EnterpriseClient.visa_category == normalized_category)
    if country:
        query = query.filter(models.EnterpriseClient.destination_country_code == country.strip().upper())
    if assigned_to:
        query = query.filter(models.EnterpriseClient.assigned_to_user_id == int(assigned_to))
    if q and q.strip():
        q_norm = q.strip().lower()
        like = f"%{q_norm}%"
        matching_stage_keys = [
            stage["key"]
            for stage in catalog.CLIENT_STAGES
            if q_norm in stage["key"].replace("_", " ").lower()
            or q_norm in stage["label"].lower()
        ]
        matching_country_codes = [
            country_item["code"]
            for country_item in catalog.COUNTRIES
            if q_norm in country_item["code"].lower()
            or q_norm in country_item["name"].lower()
            or q_norm in country_item.get("landmark", "").lower()
        ]
        matching_category_keys = [
            item["key"]
            for item in catalog.VISA_CATEGORIES
            if q_norm in item["key"].lower()
            or q_norm in item["label"].lower()
            or q_norm in item.get("short_label", "").lower()
        ]
        matching_assignee_ids = [
            int(row[0])
            for row in (
                db.query(models.EnterpriseOrganizationMember.user_id)
                .join(models.User, models.User.id == models.EnterpriseOrganizationMember.user_id)
                .filter(
                    models.EnterpriseOrganizationMember.organization_id == organization.id,
                    models.EnterpriseOrganizationMember.is_active.is_(True),
                    or_(
                        func.lower(models.User.full_name).like(like),
                        func.lower(models.User.email).like(like),
                    ),
                )
                .all()
            )
        ]

        search_clauses = [
            func.lower(models.EnterpriseClient.full_name).like(like),
            func.lower(models.EnterpriseClient.email).like(like),
            func.lower(models.EnterpriseClient.phone).like(like),
            func.lower(models.EnterpriseClient.nationality).like(like),
            func.lower(models.EnterpriseClient.passport_number).like(like),
            func.lower(models.EnterpriseClient.application_reference).like(like),
            func.lower(models.EnterpriseClient.visa_type).like(like),
            func.lower(models.EnterpriseClient.intake).like(like),
            func.lower(models.EnterpriseClient.destination_country_code).like(like),
            func.lower(models.EnterpriseClient.destination_country_name).like(like),
            func.lower(models.EnterpriseClient.status).like(like),
            func.lower(models.EnterpriseClient.priority).like(like),
        ]
        if matching_stage_keys:
            search_clauses.append(models.EnterpriseClient.status.in_(matching_stage_keys))
        if matching_country_codes:
            search_clauses.append(models.EnterpriseClient.destination_country_code.in_(matching_country_codes))
        if matching_category_keys:
            search_clauses.append(models.EnterpriseClient.visa_category.in_(matching_category_keys))
        if matching_assignee_ids:
            search_clauses.append(models.EnterpriseClient.assigned_to_user_id.in_(matching_assignee_ids))

        query = query.filter(or_(*search_clauses))

    clients = query.order_by(
        models.EnterpriseClient.created_at.desc(), models.EnterpriseClient.id.desc()
    ).all()

    member_names = _org_member_name_map(db, organization.id)

    status_counts = {stage["key"]: 0 for stage in catalog.CLIENT_STAGES}
    for status_key, count in (
        db.query(models.EnterpriseClient.status, func.count(models.EnterpriseClient.id))
        .filter(models.EnterpriseClient.organization_id == organization.id)
        .group_by(models.EnterpriseClient.status)
        .all()
    ):
        if status_key in status_counts:
            status_counts[status_key] = int(count)

    total_clients = sum(status_counts.values())

    return {
        "organization_id": organization.id,
        "permissions": _enterprise_permissions_for_role(role),
        "total_clients": total_clients,
        "filtered_count": len(clients),
        "status_counts": status_counts,
        "clients": [_serialize_client(c, member_names) for c in clients],
    }


def _apply_client_case_fields(target: models.EnterpriseClient, *, category, country_code, visa_type, intake):
    try:
        resolved = catalog.resolve_visa_case(
            category=category,
            country_code=country_code,
            visa_type=visa_type,
            intake=intake,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    target.visa_category = resolved["category"]
    target.destination_country_code = resolved["country_code"]
    target.destination_country_name = resolved["country_name"]
    target.visa_type = resolved["visa_type"]
    target.intake = resolved["intake"]


@router.post("/clients")
def enterprise_create_client(
    payload: EnterpriseClientCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, role = _require_enterprise_membership(
        db=db, user=current_user, request=request, require_edit_data=True
    )
    billing.enforce_client_limit_or_402(db, organization.id)

    full_name = (payload.full_name or "").strip()
    if len(full_name) < 2:
        raise HTTPException(status_code=400, detail="Client name must be at least 2 characters.")

    if payload.assigned_to_user_id and not _is_active_org_member(db, organization.id, payload.assigned_to_user_id):
        raise HTTPException(status_code=400, detail="Assigned team member is not part of this organization.")

    client = models.EnterpriseClient(
        organization_id=organization.id,
        full_name=full_name,
        email=(str(payload.email).strip().lower() if payload.email else None),
        phone=(payload.phone or "").strip() or None,
        nationality=(payload.nationality or "").strip() or None,
        date_of_birth=_parse_iso_date_or_400(payload.date_of_birth, "Date of birth"),
        passport_number=(payload.passport_number or "").strip() or None,
        passport_expiry=_parse_iso_date_or_400(payload.passport_expiry, "Passport expiry"),
        application_reference=(payload.application_reference or "").strip() or None,
        status=catalog.normalize_stage(payload.status) if payload.status else catalog.DEFAULT_CLIENT_STAGE,
        priority=catalog.normalize_priority(payload.priority),
        target_date=_parse_iso_date_or_400(payload.target_date, "Target date"),
        assigned_to_user_id=payload.assigned_to_user_id,
        created_by_user_id=current_user.id,
    )
    _apply_client_case_fields(
        client,
        category=payload.visa_category,
        country_code=payload.destination_country_code,
        visa_type=payload.visa_type,
        intake=payload.intake,
    )
    db.add(client)
    db.flush()

    initial_note = (payload.initial_note or "").strip()
    if initial_note:
        db.add(models.EnterpriseClientNote(
            organization_id=organization.id,
            client_id=client.id,
            author_user_id=current_user.id,
            author_name=current_user.full_name or current_user.email,
            body=initial_note,
        ))

    db.commit()
    db.refresh(client)

    member_names = _org_member_name_map(db, organization.id)
    return {
        "message": "Client added successfully.",
        "permissions": _enterprise_permissions_for_role(role),
        "client": _serialize_client(client, member_names),
        "subscription": _serialize_subscription_state(billing.build_subscription_state(db, organization.id)),
    }


@router.get("/clients/{client_id}")
def enterprise_get_client(
    client_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, role = _require_enterprise_membership(db=db, user=current_user, request=request)
    client = _get_org_client_or_404(db, organization.id, client_id)
    member_names = _org_member_name_map(db, organization.id)

    notes = (
        db.query(models.EnterpriseClientNote)
        .filter(models.EnterpriseClientNote.client_id == client.id)
        .order_by(models.EnterpriseClientNote.created_at.desc(), models.EnterpriseClientNote.id.desc())
        .all()
    )
    emails = (
        db.query(models.EnterpriseClientEmail)
        .filter(models.EnterpriseClientEmail.client_id == client.id)
        .order_by(models.EnterpriseClientEmail.created_at.desc(), models.EnterpriseClientEmail.id.desc())
        .all()
    )
    documents = (
        db.query(models.EnterpriseClientDocument)
        .filter(models.EnterpriseClientDocument.client_id == client.id)
        .order_by(models.EnterpriseClientDocument.created_at.desc(), models.EnterpriseClientDocument.id.desc())
        .all()
    )
    return {
        "permissions": _enterprise_permissions_for_role(role),
        "client": _serialize_client(client, member_names),
        "notes": [_serialize_note(n) for n in notes],
        "emails": [_serialize_client_email(e) for e in emails],
        "documents": [_serialize_client_document(d) for d in documents],
    }


@router.patch("/clients/{client_id}")
def enterprise_update_client(
    client_id: int,
    payload: EnterpriseClientUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, role = _require_enterprise_membership(
        db=db, user=current_user, request=request, require_edit_data=True
    )
    client = _get_org_client_or_404(db, organization.id, client_id)

    data = payload.model_dump(exclude_unset=True)

    if "full_name" in data:
        full_name = (data["full_name"] or "").strip()
        if len(full_name) < 2:
            raise HTTPException(status_code=400, detail="Client name must be at least 2 characters.")
        client.full_name = full_name

    # Visa case fields are validated together when any of them change.
    if any(k in data for k in ("visa_category", "destination_country_code", "visa_type", "intake")):
        _apply_client_case_fields(
            client,
            category=data.get("visa_category", client.visa_category),
            country_code=data.get("destination_country_code", client.destination_country_code),
            visa_type=data.get("visa_type", client.visa_type),
            intake=data.get("intake", client.intake),
        )

    if "email" in data:
        email_val = (data["email"] or "").strip().lower()
        client.email = email_val or None
    if "phone" in data:
        client.phone = (data["phone"] or "").strip() or None
    if "nationality" in data:
        client.nationality = (data["nationality"] or "").strip() or None
    if "passport_number" in data:
        client.passport_number = (data["passport_number"] or "").strip() or None
    if "application_reference" in data:
        client.application_reference = (data["application_reference"] or "").strip() or None
    if "date_of_birth" in data:
        client.date_of_birth = _parse_iso_date_or_400(data["date_of_birth"], "Date of birth")
    if "passport_expiry" in data:
        client.passport_expiry = _parse_iso_date_or_400(data["passport_expiry"], "Passport expiry")
    if "target_date" in data:
        client.target_date = _parse_iso_date_or_400(data["target_date"], "Target date")
    if "priority" in data:
        client.priority = catalog.normalize_priority(data["priority"])
    if "status" in data and data["status"]:
        client.status = catalog.normalize_stage(data["status"])
    if "assigned_to_user_id" in data:
        new_assignee = data["assigned_to_user_id"]
        if new_assignee and not _is_active_org_member(db, organization.id, new_assignee):
            raise HTTPException(status_code=400, detail="Assigned team member is not part of this organization.")
        client.assigned_to_user_id = new_assignee

    db.commit()
    db.refresh(client)
    member_names = _org_member_name_map(db, organization.id)
    return {
        "message": "Client updated.",
        "permissions": _enterprise_permissions_for_role(role),
        "client": _serialize_client(client, member_names),
    }


@router.patch("/clients/{client_id}/status")
def enterprise_update_client_status(
    client_id: int,
    payload: EnterpriseClientStatusRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, role = _require_enterprise_membership(
        db=db, user=current_user, request=request, require_edit_data=True
    )
    client = _get_org_client_or_404(db, organization.id, client_id)
    new_status = payload.status.strip().lower()
    if new_status not in catalog.CLIENT_STAGE_KEYS:
        raise HTTPException(status_code=400, detail="Invalid status.")
    client.status = new_status
    db.commit()
    db.refresh(client)
    member_names = _org_member_name_map(db, organization.id)
    return {
        "message": "Status updated.",
        "permissions": _enterprise_permissions_for_role(role),
        "client": _serialize_client(client, member_names),
    }


@router.delete("/clients/{client_id}")
def enterprise_delete_client(
    client_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, role = _require_enterprise_membership(
        db=db, user=current_user, request=request, require_edit_data=True
    )
    client = _get_org_client_or_404(db, organization.id, client_id)
    db.delete(client)
    db.commit()
    return {
        "message": "Client deleted.",
        "permissions": _enterprise_permissions_for_role(role),
    }


@router.post("/clients/{client_id}/notes")
def enterprise_add_client_note(
    client_id: int,
    payload: EnterpriseClientNoteRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, role = _require_enterprise_membership(
        db=db, user=current_user, request=request, require_edit_data=True
    )
    client = _get_org_client_or_404(db, organization.id, client_id)
    body = (payload.body or "").strip()
    if not body:
        raise HTTPException(status_code=400, detail="Note cannot be empty.")

    note = models.EnterpriseClientNote(
        organization_id=organization.id,
        client_id=client.id,
        author_user_id=current_user.id,
        author_name=current_user.full_name or current_user.email,
        body=body,
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    return {
        "message": "Note added.",
        "permissions": _enterprise_permissions_for_role(role),
        "note": _serialize_note(note),
    }


def _send_and_log_client_email(
    db: Session,
    *,
    organization: models.EnterpriseOrganization,
    client: models.EnterpriseClient,
    subject: str,
    body: str,
    current_user: models.User,
) -> models.EnterpriseClientEmail:
    success, message_id, error = send_enterprise_client_email(
        to_email=client.email,
        subject=subject,
        body=body,
        organization_name=organization.company_name,
        sender_name=current_user.full_name or current_user.email,
        logo_url=_resolve_enterprise_logo_url(organization),
        reply_to=current_user.email,
    )
    row = models.EnterpriseClientEmail(
        organization_id=organization.id,
        client_id=client.id,
        sent_by_user_id=current_user.id,
        sent_by_name=current_user.full_name or current_user.email,
        to_email=client.email,
        subject=subject,
        body=body,
        status="sent" if success else "failed",
        provider_message_id=message_id,
        error_message=error,
    )
    db.add(row)
    return row


@router.post("/clients/{client_id}/email")
def enterprise_email_client(
    client_id: int,
    payload: EnterpriseClientEmailRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, role = _require_enterprise_membership(
        db=db, user=current_user, request=request, require_edit_data=True
    )
    _enforce_rate_limit_or_429(
        request=request,
        scope="enterprise.client_email",
        limit=ENTERPRISE_CLIENT_EMAIL_RATE_LIMIT,
        window_seconds=ENTERPRISE_CLIENT_EMAIL_RATE_WINDOW_SECONDS,
        extra_key=f"org:{organization.id}:user:{current_user.id}",
    )
    client = _get_org_client_or_404(db, organization.id, client_id)
    if not (client.email or "").strip():
        raise HTTPException(status_code=400, detail="This client has no email address on file.")

    subject = payload.subject.strip()
    body = payload.body.strip()
    row = _send_and_log_client_email(
        db, organization=organization, client=client, subject=subject, body=body, current_user=current_user
    )
    db.commit()
    db.refresh(row)

    if row.status != "sent":
        raise HTTPException(status_code=502, detail=row.error_message or "Email could not be sent.")

    return {
        "message": f"Email sent to {client.full_name}.",
        "permissions": _enterprise_permissions_for_role(role),
        "email": _serialize_client_email(row),
    }


@router.post("/clients/email/bulk")
def enterprise_email_clients_bulk(
    payload: EnterpriseBulkEmailRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, role = _require_enterprise_membership(
        db=db, user=current_user, request=request, require_edit_data=True
    )
    _enforce_rate_limit_or_429(
        request=request,
        scope="enterprise.bulk_client_email",
        limit=ENTERPRISE_BULK_EMAIL_RATE_LIMIT,
        window_seconds=ENTERPRISE_BULK_EMAIL_RATE_WINDOW_SECONDS,
        extra_key=f"org:{organization.id}:user:{current_user.id}",
    )
    client_ids = list(dict.fromkeys(payload.client_ids))[:ENTERPRISE_BULK_EMAIL_MAX_RECIPIENTS]
    subject = payload.subject.strip()
    body = payload.body.strip()

    clients = (
        db.query(models.EnterpriseClient)
        .filter(
            models.EnterpriseClient.organization_id == organization.id,
            models.EnterpriseClient.id.in_(client_ids),
        )
        .all()
    )

    sent = 0
    failed = 0
    skipped = 0
    for client in clients:
        if not (client.email or "").strip():
            skipped += 1
            continue
        row = _send_and_log_client_email(
            db, organization=organization, client=client, subject=subject, body=body, current_user=current_user
        )
        if row.status == "sent":
            sent += 1
        else:
            failed += 1

    db.commit()
    return {
        "message": f"Sent {sent} email(s). {failed} failed, {skipped} skipped (no email).",
        "permissions": _enterprise_permissions_for_role(role),
        "sent": sent,
        "failed": failed,
        "skipped": skipped,
    }


@router.get("/dashboard")
def enterprise_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, role = _require_enterprise_membership(db=db, user=current_user, request=request)
    org_id = organization.id

    base = db.query(models.EnterpriseClient).filter(models.EnterpriseClient.organization_id == org_id)
    total_clients = base.count()

    # Counts by status
    status_counts = {stage["key"]: 0 for stage in catalog.CLIENT_STAGES}
    for status_key, count in (
        db.query(models.EnterpriseClient.status, func.count(models.EnterpriseClient.id))
        .filter(models.EnterpriseClient.organization_id == org_id)
        .group_by(models.EnterpriseClient.status)
        .all()
    ):
        if status_key in status_counts:
            status_counts[status_key] = int(count)

    open_stage_keys = {s["key"] for s in catalog.CLIENT_STAGES if s["is_open"]}
    active_clients = sum(v for k, v in status_counts.items() if k in open_stage_keys)
    approved = status_counts.get(catalog.STAGE_APPROVED, 0)
    rejected = status_counts.get(catalog.STAGE_REJECTED, 0)
    decided = approved + rejected
    approval_rate = round((approved / decided) * 100) if decided else None

    # Counts by category
    category_counts = []
    cat_raw = dict(
        db.query(models.EnterpriseClient.visa_category, func.count(models.EnterpriseClient.id))
        .filter(models.EnterpriseClient.organization_id == org_id)
        .group_by(models.EnterpriseClient.visa_category)
        .all()
    )
    for cat in catalog.VISA_CATEGORIES:
        category_counts.append({
            "key": cat["key"],
            "label": cat["label"],
            "accent": cat["accent"],
            "count": int(cat_raw.get(cat["key"], 0)),
        })

    # Counts by specific visa type (top 6)
    visa_type_rows = (
        db.query(models.EnterpriseClient.visa_type, func.count(models.EnterpriseClient.id))
        .filter(models.EnterpriseClient.organization_id == org_id)
        .group_by(models.EnterpriseClient.visa_type)
        .order_by(func.count(models.EnterpriseClient.id).desc())
        .limit(6)
        .all()
    )
    visa_type_counts = [
        {"visa_type": vt or "—", "count": int(count)} for vt, count in visa_type_rows
    ]

    # Top destination countries
    country_rows = (
        db.query(
            models.EnterpriseClient.destination_country_code,
            func.count(models.EnterpriseClient.id),
        )
        .filter(models.EnterpriseClient.organization_id == org_id)
        .group_by(models.EnterpriseClient.destination_country_code)
        .order_by(func.count(models.EnterpriseClient.id).desc())
        .limit(8)
        .all()
    )
    top_countries = []
    for code, count in country_rows:
        brief = _country_brief(code)
        brief["count"] = int(count)
        top_countries.append(brief)

    # New clients this month
    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    new_this_month = (
        base.filter(models.EnterpriseClient.created_at >= month_start).count()
    )

    member_names = _org_member_name_map(db, org_id)

    # Upcoming deadlines (target_date today or later), nearest first
    today = date.today()
    upcoming = (
        db.query(models.EnterpriseClient)
        .filter(
            models.EnterpriseClient.organization_id == org_id,
            models.EnterpriseClient.target_date.isnot(None),
            models.EnterpriseClient.target_date >= today,
            models.EnterpriseClient.status.notin_([catalog.STAGE_APPROVED, catalog.STAGE_REJECTED]),
        )
        .order_by(models.EnterpriseClient.target_date.asc())
        .limit(8)
        .all()
    )

    # Recent clients
    recent = (
        base.order_by(models.EnterpriseClient.created_at.desc(), models.EnterpriseClient.id.desc())
        .limit(6)
        .all()
    )

    pipeline = []
    for stage in catalog.CLIENT_STAGES:
        pipeline.append({
            "key": stage["key"],
            "label": stage["label"],
            "color": stage["color"],
            "count": status_counts.get(stage["key"], 0),
        })

    return {
        "organization": {
            "id": organization.id,
            "company_name": organization.company_name,
            "logo_url": _resolve_enterprise_logo_url(organization),
        },
        "permissions": _enterprise_permissions_for_role(role),
        "kpis": {
            "total_clients": total_clients,
            "active_clients": active_clients,
            "approved": approved,
            "rejected": rejected,
            "approval_rate": approval_rate,
            "new_this_month": new_this_month,
        },
        "pipeline": pipeline,
        "category_counts": category_counts,
        "visa_type_counts": visa_type_counts,
        "top_countries": top_countries,
        "upcoming_deadlines": [_serialize_client(c, member_names) for c in upcoming],
        "recent_clients": [_serialize_client(c, member_names) for c in recent],
        "subscription": _serialize_subscription_state(billing.build_subscription_state(db, org_id)),
    }


# ===========================================================================
# Billing (per-organization subscriptions) + self-serve signup
# ===========================================================================

def _razorpay_credentials() -> tuple[str, str]:
    return (os.getenv("RAZORPAY_KEY_ID", "").strip(), os.getenv("RAZORPAY_KEY_SECRET", "").strip())


def _razorpay_enabled() -> bool:
    key_id, key_secret = _razorpay_credentials()
    return bool(key_id and key_secret)


def _razorpay_request(method: str, path: str, json_payload: dict | None = None) -> dict:
    key_id, key_secret = _razorpay_credentials()
    url = f"{RAZORPAY_API_BASE}/{path.lstrip('/')}"
    try:
        resp = requests.request(method.upper(), url, auth=(key_id, key_secret), json=json_payload, timeout=15)
    except requests.RequestException:
        raise HTTPException(status_code=502, detail="Failed to contact the payment gateway.")
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail="Unable to process the payment request right now.")
    try:
        data = resp.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="Invalid response from the payment gateway.")
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="Unexpected response from the payment gateway.")
    return data


@router.get("/billing/plans")
def enterprise_billing_plans(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, role = _require_enterprise_membership(db=db, user=current_user, request=request)
    return {
        "plans": billing.public_plans_payload(),
        "currency": billing.CURRENCY,
        "checkout_enabled": _razorpay_enabled(),
        "razorpay_key_id": os.getenv("RAZORPAY_KEY_ID", "").strip() or None,
        "permissions": _enterprise_permissions_for_role(role),
        "subscription": _serialize_subscription_state(billing.build_subscription_state(db, organization.id)),
    }


@router.get("/billing/subscription")
def enterprise_billing_subscription(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, role = _require_enterprise_membership(db=db, user=current_user, request=request)
    return {
        "permissions": _enterprise_permissions_for_role(role),
        "subscription": _serialize_subscription_state(billing.build_subscription_state(db, organization.id)),
        "plans": billing.public_plans_payload(),
    }


@router.post("/billing/checkout")
def enterprise_billing_checkout(
    payload: EnterpriseBillingCheckoutRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, _ = _require_enterprise_membership(
        db=db, user=current_user, request=request, require_manage_users=True
    )
    if billing.ENTERPRISE_FREE:
        return {"action": "free", "message": "Rilono Enterprise is free — no billing required."}
    plan = billing.get_plan(payload.plan)
    if not plan or plan["key"] not in billing.PAID_PLAN_KEYS:
        raise HTTPException(status_code=400, detail="Please choose a valid paid plan.")
    cycle = billing.normalize_billing_cycle(payload.billing_cycle)
    amount = billing.plan_amount_paise(plan["key"], cycle)
    if amount <= 0:
        raise HTTPException(status_code=400, detail="This plan is not available for online checkout.")

    if not _razorpay_enabled():
        return {
            "action": "contact_sales",
            "message": "Online checkout is being enabled. Please contact sales to activate your plan.",
        }

    receipt = f"reln_{organization.id}_{secrets.token_hex(6)}"[:40]
    order = _razorpay_request("POST", "/orders", {
        "amount": amount,
        "currency": billing.CURRENCY,
        "receipt": receipt,
        "notes": {
            "organization_id": str(organization.id),
            "plan": plan["key"],
            "billing_cycle": cycle,
            "user_id": str(current_user.id),
        },
    })
    order_id = str(order.get("id") or "").strip()
    if not order_id:
        raise HTTPException(status_code=502, detail="Could not create the payment order.")

    db.add(models.EnterpriseSubscriptionPayment(
        organization_id=organization.id,
        created_by_user_id=current_user.id,
        provider="razorpay",
        plan=plan["key"],
        billing_cycle=cycle,
        amount_paise=amount,
        currency=billing.CURRENCY,
        razorpay_order_id=order_id,
        status="created",
    ))
    db.commit()

    return {
        "action": "checkout",
        "razorpay_key_id": os.getenv("RAZORPAY_KEY_ID", "").strip(),
        "order_id": order_id,
        "amount": amount,
        "currency": billing.CURRENCY,
        "plan": plan["key"],
        "plan_label": plan["label"],
        "billing_cycle": cycle,
        "organization_name": organization.company_name,
        "prefill": {
            "name": current_user.full_name or "",
            "email": current_user.email or "",
        },
    }


@router.post("/billing/verify")
def enterprise_billing_verify(
    payload: EnterpriseBillingVerifyRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, _ = _require_enterprise_membership(
        db=db, user=current_user, request=request, require_manage_users=True
    )
    key_id, key_secret = _razorpay_credentials()
    if not key_id or not key_secret:
        raise HTTPException(status_code=503, detail="Payment verification is not configured.")

    payment_row = (
        db.query(models.EnterpriseSubscriptionPayment)
        .filter(
            models.EnterpriseSubscriptionPayment.razorpay_order_id == payload.razorpay_order_id.strip(),
            models.EnterpriseSubscriptionPayment.organization_id == organization.id,
        )
        .first()
    )
    if not payment_row:
        raise HTTPException(status_code=404, detail="Payment order not found for this organization.")

    expected_signature = hmac.new(
        key_secret.encode("utf-8"),
        f"{payload.razorpay_order_id}|{payload.razorpay_payment_id}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected_signature, payload.razorpay_signature):
        payment_row.status = "failed"
        payment_row.error_message = "Invalid payment signature."
        db.commit()
        raise HTTPException(status_code=400, detail="Invalid payment signature.")

    now = datetime.utcnow()
    payment_row.razorpay_payment_id = payload.razorpay_payment_id.strip()
    payment_row.status = "verified"
    payment_row.verified_at = now
    payment_row.error_message = None

    period_days = 365 if payment_row.billing_cycle == "yearly" else 30
    sub = billing.get_or_create_org_subscription(db, organization.id, commit=False)
    sub.plan = payment_row.plan
    sub.status = "active"
    sub.current_period_end = now + timedelta(days=period_days)

    db.commit()

    return {
        "message": f"Your {billing.get_plan(payment_row.plan)['label']} plan is now active.",
        "subscription": _serialize_subscription_state(billing.build_subscription_state(db, organization.id)),
    }


@router.post("/signup")
async def enterprise_signup(
    payload: EnterpriseSignupRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    _enforce_rate_limit_or_429(
        request=request,
        scope="enterprise.signup",
        limit=ENTERPRISE_SIGNUP_RATE_LIMIT,
        window_seconds=ENTERPRISE_SIGNUP_RATE_WINDOW_SECONDS,
    )

    turnstile_token = (payload.cf_turnstile_token or "").strip()
    if is_turnstile_enabled() and not is_request_ip_whitelisted(request):
        if turnstile_token:
            client_ip = extract_client_ip(request) if request else None
            if not verify_turnstile_token(turnstile_token, client_ip):
                raise HTTPException(status_code=400, detail="Security verification failed. Please try again.")
        elif _is_turnstile_required():
            raise HTTPException(status_code=400, detail="Security verification is required.")

    company_name = (payload.company_name or "").strip()
    if len(company_name) < 2:
        raise HTTPException(status_code=400, detail="Company name must be at least 2 characters.")
    full_name = (payload.full_name or "").strip()
    if len(full_name) < 2:
        raise HTTPException(status_code=400, detail="Your name must be at least 2 characters.")
    email = payload.email.lower().strip()
    subdomain_slug = _parse_enterprise_subdomain_or_400(payload.subdomain_slug)

    password_error = validate_password_strength(payload.password, email)
    if password_error:
        raise HTTPException(status_code=400, detail=password_error)

    existing_user = db.query(models.User).filter(models.User.email == email).first()
    if existing_user:
        raise HTTPException(
            status_code=409,
            detail="An account with this email already exists. Please sign in instead.",
        )

    _assert_subdomain_available(db=db, subdomain_slug=subdomain_slug)

    password_hash = get_password_hash(payload.password)

    # Create the owner user. Enterprise access is granted via their organization
    # membership below (see _has_enterprise_access) — NOT via an EnterpriseCredential.
    # Credentials are reserved for platform-admin-granted accounts and would otherwise
    # be promoted to is_admin by seed_enterprise_user() on the next restart.
    user = models.User(
        email=email,
        username=None,
        hashed_password=password_hash,
        full_name=full_name,
        university=company_name,
        is_active=True,
        email_verified=True,
        accepted_terms_privacy_at=datetime.utcnow(),
    )
    db.add(user)
    db.flush()

    organization = models.EnterpriseOrganization(
        company_name=company_name,
        subdomain_slug=subdomain_slug,
        logo_url=_build_default_enterprise_logo_url(
            organization_id=None,
            company_name=company_name,
            subdomain_slug=subdomain_slug,
            randomize=True,
        ),
        created_by_user_id=user.id,
    )
    db.add(organization)
    db.flush()

    db.add(models.EnterpriseOrganizationMember(
        organization_id=organization.id,
        user_id=user.id,
        role=ENTERPRISE_ROLE_ADMIN,
        is_active=True,
        invited_by_user_id=user.id,
    ))
    organization.logo_url = _build_default_enterprise_logo_url(
        organization_id=organization.id,
        company_name=company_name,
        subdomain_slug=subdomain_slug,
        randomize=True,
    )
    billing.get_or_create_org_subscription(db, organization.id, commit=False)

    user.last_login_at = datetime.utcnow()
    user.first_login_at = datetime.utcnow()
    db.commit()
    db.refresh(user)

    access_token = create_access_token(
        data={"sub": user.email},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    set_auth_cookie(request, response, access_token)

    context = _build_enterprise_context(db, user, request)
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "is_admin": user.is_admin,
        },
        "portal_url": _build_enterprise_portal_url(subdomain_slug, request),
        **context,
    }


# ===========================================================================
# AI copilot (Gemini function-calling agent, read-only, org-scoped)
# ===========================================================================

ENTERPRISE_AI_RATE_LIMIT = int(os.getenv("ENTERPRISE_AI_RATE_LIMIT", "30"))
ENTERPRISE_AI_RATE_WINDOW_SECONDS = int(os.getenv("ENTERPRISE_AI_RATE_WINDOW_SECONDS", "300"))

ENTERPRISE_AI_SUGGESTIONS = [
    "How many clients got approved this week?",
    "Which clients need my attention right now?",
    "How many clients are at the interview stage?",
    "Show me clients applying to Canada.",
    "What's happened in the portal in the last 7 days?",
    "How is the team's workload split?",
]


class EnterpriseAIChatTurn(BaseModel):
    role: str = Field(..., max_length=16)
    content: str = Field(..., max_length=6000)


class EnterpriseAIChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    history: Optional[list[EnterpriseAIChatTurn]] = None


@router.get("/ai/meta")
def enterprise_ai_meta(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _require_enterprise_membership(db=db, user=current_user, request=request)
    return {
        "enabled": enterprise_ai.is_ai_configured(),
        "suggestions": ENTERPRISE_AI_SUGGESTIONS,
    }


@router.post("/ai/chat")
def enterprise_ai_chat(
    payload: EnterpriseAIChatRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, role = _require_enterprise_membership(db=db, user=current_user, request=request)
    _enforce_rate_limit_or_429(
        request=request,
        scope="enterprise.ai",
        limit=ENTERPRISE_AI_RATE_LIMIT,
        window_seconds=ENTERPRISE_AI_RATE_WINDOW_SECONDS,
        extra_key=str(current_user.id),
    )

    if not enterprise_ai.is_ai_configured():
        raise HTTPException(
            status_code=503,
            detail="The AI assistant isn't available right now. Please try again later.",
        )

    history = [turn.model_dump() for turn in (payload.history or [])]
    try:
        answer = enterprise_ai.run_enterprise_ai_chat(
            db=db,
            organization=organization,
            user=current_user,
            role=role,
            message=payload.message,
            history=history,
        )
    except Exception:
        logger.exception("Enterprise AI chat failed (org_id=%s)", organization.id)
        raise HTTPException(
            status_code=502,
            detail="The AI assistant ran into a problem answering that. Please try again.",
        )

    return {"answer": answer, "permissions": _enterprise_permissions_for_role(role)}


# ===========================================================================
# Per-client documents (private R2 storage, authenticated streaming)
# ===========================================================================

ENTERPRISE_DOC_MAX_BYTES = int(os.getenv("ENTERPRISE_DOC_MAX_BYTES", str(25 * 1024 * 1024)))
ENTERPRISE_DOC_ALLOWED_EXT = {
    ".pdf", ".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic",
    ".doc", ".docx", ".xls", ".xlsx", ".csv", ".txt",
}
ENTERPRISE_DOC_INLINE_EXT = {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".gif"}


def _serialize_client_document(doc: models.EnterpriseClientDocument) -> dict:
    return {
        "id": doc.id,
        "client_id": doc.client_id,
        "document_type": doc.document_type,
        "original_filename": doc.original_filename,
        "file_size": doc.file_size,
        "mime_type": doc.mime_type,
        "uploaded_by_name": doc.uploaded_by_name,
        "created_at": _iso(doc.created_at),
        "download_url": f"/api/enterprise/clients/{doc.client_id}/documents/{doc.id}/download",
    }


def _safe_filename(name: str) -> str:
    base = os.path.basename(str(name or "").strip()) or "document"
    base = re.sub(r"[\r\n\"]+", "", base)
    return base[:160]


@router.get("/clients/{client_id}/documents")
def enterprise_list_client_documents(
    client_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, role = _require_enterprise_membership(db=db, user=current_user, request=request)
    client = _get_org_client_or_404(db, organization.id, client_id)
    rows = (
        db.query(models.EnterpriseClientDocument)
        .filter(models.EnterpriseClientDocument.client_id == client.id)
        .order_by(models.EnterpriseClientDocument.created_at.desc(), models.EnterpriseClientDocument.id.desc())
        .all()
    )
    return {
        "permissions": _enterprise_permissions_for_role(role),
        "document_types": list(catalog.STUDENT_DOCUMENT_TYPES),
        "documents": [_serialize_client_document(d) for d in rows],
    }


@router.post("/clients/{client_id}/documents")
async def enterprise_upload_client_document(
    client_id: int,
    request: Request,
    document_type: str = Form("Other"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, role = _require_enterprise_membership(
        db=db, user=current_user, request=request, require_edit_data=True
    )
    client = _get_org_client_or_404(db, organization.id, client_id)

    if not enterprise_storage.is_configured():
        raise HTTPException(status_code=503, detail="Document storage is not configured.")

    original = _safe_filename(file.filename)
    ext = os.path.splitext(original)[1].lower()
    if ext not in ENTERPRISE_DOC_ALLOWED_EXT:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Allowed: PDF, images, Word/Excel, CSV, or text.",
        )

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="The file is empty.")
    if len(data) > ENTERPRISE_DOC_MAX_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"File is too large. Maximum size is {ENTERPRISE_DOC_MAX_BYTES // (1024 * 1024)} MB.",
        )

    storage_key = f"enterprise/{organization.id}/clients/{client.id}/{uuid.uuid4().hex}{ext}"
    try:
        enterprise_storage.store_document(storage_key, data, content_type=file.content_type)
    except Exception:
        logger.exception("Failed to store client document (org_id=%s, client_id=%s)", organization.id, client.id)
        raise HTTPException(status_code=502, detail="Could not store the document right now. Please try again.")

    doc = models.EnterpriseClientDocument(
        organization_id=organization.id,
        client_id=client.id,
        document_type=catalog.normalize_document_type(document_type),
        original_filename=original,
        storage_key=storage_key,
        file_size=len(data),
        mime_type=(file.content_type or None),
        uploaded_by_user_id=current_user.id,
        uploaded_by_name=current_user.full_name or current_user.email,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    # Extract the document's text in the background so the AI copilot can read it,
    # without slowing down the upload response.
    _start_document_text_extraction(doc.id, data, original, file.content_type)

    return {
        "message": "Document uploaded.",
        "permissions": _enterprise_permissions_for_role(role),
        "document": _serialize_client_document(doc),
    }


def _start_document_text_extraction(document_id: int, data: bytes, filename: str, mime_type: str | None) -> None:
    def _worker():
        try:
            extracted = gemini_service.extract_text_from_document(data, filename, mime_type or "application/octet-stream")
            if not extracted:
                return
            db2 = SessionLocal()
            try:
                row = (
                    db2.query(models.EnterpriseClientDocument)
                    .filter(models.EnterpriseClientDocument.id == int(document_id))
                    .first()
                )
                if row is not None:
                    row.extracted_text = extracted[:200000]
                    db2.commit()
            finally:
                db2.close()
        except Exception:
            logger.exception("Background document text extraction failed (document_id=%s)", document_id)

    threading.Thread(target=_worker, daemon=True).start()


@router.get("/clients/{client_id}/documents/{document_id}/download")
def enterprise_download_client_document(
    client_id: int,
    document_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, _ = _require_enterprise_membership(db=db, user=current_user, request=request)
    doc = (
        db.query(models.EnterpriseClientDocument)
        .filter(
            models.EnterpriseClientDocument.id == int(document_id),
            models.EnterpriseClientDocument.client_id == int(client_id),
            models.EnterpriseClientDocument.organization_id == organization.id,
        )
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    try:
        data = enterprise_storage.fetch_document(doc.storage_key)
    except Exception:
        logger.exception("Failed to fetch client document id=%s", doc.id)
        raise HTTPException(status_code=502, detail="Could not retrieve the document right now.")

    ext = os.path.splitext(doc.original_filename)[1].lower()
    disposition = "inline" if ext in ENTERPRISE_DOC_INLINE_EXT else "attachment"
    filename = _safe_filename(doc.original_filename)
    return Response(
        content=data,
        media_type=(doc.mime_type or "application/octet-stream"),
        headers={"Content-Disposition": f'{disposition}; filename="{filename}"'},
    )


@router.delete("/clients/{client_id}/documents/{document_id}")
def enterprise_delete_client_document(
    client_id: int,
    document_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, role = _require_enterprise_membership(
        db=db, user=current_user, request=request, require_edit_data=True
    )
    doc = (
        db.query(models.EnterpriseClientDocument)
        .filter(
            models.EnterpriseClientDocument.id == int(document_id),
            models.EnterpriseClientDocument.client_id == int(client_id),
            models.EnterpriseClientDocument.organization_id == organization.id,
        )
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    enterprise_storage.delete_document(doc.storage_key)
    db.delete(doc)
    db.commit()
    return {"message": "Document deleted.", "permissions": _enterprise_permissions_for_role(role)}
