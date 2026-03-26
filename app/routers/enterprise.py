import os
import re
import secrets
import logging
import hashlib
from typing import Optional
from urllib.parse import quote, urlparse

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
    logo_url = _resolve_enterprise_logo_url(organization)
    onboarding_required = not company_name or not subdomain_slug
    return {
        "onboarding_required": onboarding_required,
        "organization": {
            "id": organization.id,
            "company_name": company_name or organization.company_name,
            "subdomain_slug": subdomain_slug or None,
            "logo_url": logo_url,
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
        **_build_enterprise_context(db, current_user),
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
                **_build_enterprise_context(db, current_user),
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
            **_build_enterprise_context(db, current_user),
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
            "logo_url": _resolve_enterprise_logo_url(organization),
            "portal_url": _build_enterprise_portal_url(organization.subdomain_slug),
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

    context = _build_enterprise_context(db, current_user)
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

    target_email = (payload.email or "").strip().lower()
    if not target_email:
        raise HTTPException(status_code=400, detail="Email is required.")

    target_role = _parse_enterprise_role_or_400(payload.role)
    target_credential = (
        db.query(models.EnterpriseCredential)
        .filter(
            models.EnterpriseCredential.email == target_email,
            models.EnterpriseCredential.is_active.is_(True),
        )
        .first()
    )
    if not target_credential:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Enterprise access has not been granted for this email yet. "
                "Grant access first from /admin_console."
            ),
        )

    created_user = False

    user = db.query(models.User).filter(models.User.email == target_email).first()
    if not user:
        fallback_name = target_email.split("@")[0].replace(".", " ").replace("_", " ").title()
        user = models.User(
            email=target_email,
            username=None,
            hashed_password=target_credential.password_hash,
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
